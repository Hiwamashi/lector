"""Orchestrierung des entkoppelten GiroCode-/SevDesk-Features.

``PaperlessSync`` ist der einzige Ort, der Paperless- und SevDesk-Client zusammenführt:

- ``sync_once`` wird periodisch vom Worker aufgerufen: liest Rechnungen (anhand des
  Paperless-Dokumententyps), ermittelt fehlende GiroCode-Zahldaten und merkt mit dem SevDesk-
  Tag versehene Dokumente zum Export vor (bzw. exportiert automatisch).
- ``export_invoice`` / ``set_paid`` / ``save_giro_edits`` sind die UI-Aktionen.

Alle Schreibvorgänge nach Paperless (Custom Fields, Tags, Notiz) laufen über
``_write_back_*``-Helfer, damit der Rückschrieb an einer Stelle gebündelt ist.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from .config import Settings
from .detection import extract_embedded_invoice_xml
from .girocode import (
    PaymentData,
    extract_from_einvoice_xml,
    extract_from_ocr_text,
    valid_iban,
)
from .models import (
    GiroStatus,
    InvoiceEventType,
    RecipientRow,
    RecipientStatus,
    RecipientSuggestion,
    SevdeskStatus,
)
from .paperless import (
    CF_TYPE_BOOLEAN,
    CF_TYPE_DATE,
    CF_TYPE_STRING,
    DocumentPage,
    PaperlessClient,
    PaperlessDocument,
    SelectField,
)
from .recipient_llm import RecipientSuggester
from .repository import Repository
from .sevdesk import SevdeskClient

log = logging.getLogger("lector.paperless_sync")

# Seitengröße der Empfänger-Übersicht.
RECIPIENT_PAGE_SIZE = 50

# Nach so vielen Fehlschlägen in Folge wird der Lauf beendet: ein dauerhaft gedrosseltes
# oder fehlkonfiguriertes Konto soll nicht wirkungslos durch hunderte Dokumente laufen.
BATCH_ERROR_STREAK = 10
# Der Lauf meldet Fortschritt höchstens so oft — sonst erzeugt ein Lauf über 1500
# Dokumente ebenso viele SSE-Ereignisse für jeden verbundenen Client.
BATCH_PUBLISH_INTERVAL = 2.0


def _parse_paperless_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class BatchProgress:
    """Zustand des KI-Batch-Laufs. Lebt nur im Prozess — ein Neustart verwirft ihn."""

    running: bool = False
    total: int = 0
    done: int = 0
    failed: int = 0
    # Dokumente, die zwischen Einplanung und Verarbeitung anderweitig einen Empfänger
    # oder Vorschlag bekommen haben (manuell oder Einzelvorschlag) — zählen bewusst
    # weder als "done" noch als "failed", sollen aber sichtbar sein statt den
    # Fortschrittsbalken einfach stehen zu lassen.
    skipped: int = 0
    remaining: int = 0
    stopped: bool = False
    aborted_reason: str | None = None
    finished_at: datetime | None = None


class PaperlessSync:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self._ids: dict[str, int | None] | None = None
        self._lock = asyncio.Lock()
        # Empfänger-Feature: aufgelöstes select-Feld + Korrespondenten-Map (lazy gecacht).
        self._recipient_field: SelectField | None = None
        self._recipient_field_resolved = False
        self._corr_map: dict[int, str] | None = None
        self._progress = BatchProgress()
        self._batch_stop = False
        # Referenz auf den laufenden Batch-Task halten, damit der Event-Loop ihn nicht
        # (er hält nur schwache Referenzen) mitten im Lauf garbage-collected.
        self._batch_task: asyncio.Task[int] | None = None
        # Serialisiert das Zurückschreiben des Empfängers (manuell vs. KI-Batch), damit
        # ein nebenläufiger Batch-Write keinen gerade manuell gesetzten Empfänger überschreibt.
        self._recipient_write_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(s.feature_paperless_sync and s.paperless_url and s.paperless_token)

    @property
    def sevdesk_enabled(self) -> bool:
        s = self.settings
        return bool(s.feature_sevdesk_export and s.sevdesk_api_token)

    @property
    def recipient_enabled(self) -> bool:
        """Empfänger-Verwaltung benötigt nur die Paperless-Anbindung (unabhängig vom Sync)."""
        s = self.settings
        return bool(s.paperless_url and s.paperless_token)

    @property
    def recipient_llm_enabled(self) -> bool:
        s = self.settings
        return bool(self.recipient_enabled and s.feature_recipient_llm and s.anthropic_api_key)

    @property
    def batch_progress(self) -> BatchProgress:
        return self._progress

    def stop_batch(self) -> None:
        """Bittet den laufenden Batch, nach dem aktuellen Dokument zu enden."""
        if self._progress.running:
            self._batch_stop = True

    async def shutdown(self) -> None:
        """Bricht einen laufenden Batch beim Herunterfahren des Prozesses ab und wartet ihn ab.

        Ohne diesen Schritt könnte der Task bei einem SIGTERM mitten im Lauf auf eine
        bereits geschlossene Repository-Verbindung zugreifen, weil das Lifespan-``finally``
        sonst sofort mit ``repo.close()`` fortfährt, während der Task noch läuft.
        """
        task = self._batch_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _paperless(self) -> PaperlessClient:
        return PaperlessClient(self.settings.paperless_url, self.settings.paperless_token)

    def _sevdesk(self) -> SevdeskClient:
        return SevdeskClient(self.settings.sevdesk_base_url, self.settings.sevdesk_api_token)

    def _suggester(self) -> RecipientSuggester:
        return RecipientSuggester(
            self.settings.anthropic_api_key, self.settings.recipient_llm_model
        )

    # ---- ID-Auflösung (Doctype, Tags, Custom Fields) ---------------------

    async def _resolve(self, client: PaperlessClient) -> dict[str, int | None]:
        if self._ids is not None:
            return self._ids
        s = self.settings
        ids: dict[str, int | None] = {}
        ids["doctype"] = await client.resolve_document_type_id(s.paperless_invoice_doctype)
        ids["sevdesk_tag"] = await self._tag_id(client, s.sevdesk_tag, create=True)
        ids["tag_sevdesk_done"] = await self._tag_id(client, s.tag_sevdesk_done, create=True)
        ids["tag_paid"] = await self._tag_id(client, s.tag_paid, create=True)
        ids["cf_giro_iban"] = await self._field_id(client, s.cf_giro_iban, CF_TYPE_STRING)
        ids["cf_giro_amount"] = await self._field_id(client, s.cf_giro_amount, CF_TYPE_STRING)
        ids["cf_sevdesk_id"] = await self._field_id(client, s.cf_sevdesk_id, CF_TYPE_STRING)
        ids["cf_exported_at"] = await self._field_id(client, s.cf_exported_at, CF_TYPE_DATE)
        ids["cf_paid"] = await self._field_id(client, s.cf_paid, CF_TYPE_BOOLEAN)
        self._ids = ids
        return ids

    async def _field_id(self, client: PaperlessClient, name: str, dtype: str) -> int | None:
        if self.settings.paperless_auto_create_fields:
            return await client.ensure_custom_field(name, dtype)
        for field in await client.list_custom_fields():
            if field.get("name", "").lower() == name.lower():
                return int(field["id"])
        log.warning("Custom Field '%s' fehlt in Paperless (Auto-Anlage deaktiviert)", name)
        return None

    async def _tag_id(self, client: PaperlessClient, name: str, *, create: bool) -> int | None:
        for tag in await client.list_tags():
            if tag.get("name", "").lower() == name.lower():
                return int(tag["id"])
        if create and self.settings.paperless_auto_create_fields:
            return await client.ensure_tag(name)
        return None

    # ---- periodischer Sync ----------------------------------------------

    async def sync_once(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            try:
                async with self._paperless() as client:
                    ids = await self._resolve(client)
                    await self._sync_invoices(client, ids)
                    await self._sync_sevdesk_tag(client, ids)
            except httpx.ConnectError as exc:
                # Paperless (noch) nicht erreichbar — typisch beim Start, wenn der
                # webserver-Container später hochfährt. Nächster Lauf greift erneut.
                log.warning("Paperless nicht erreichbar, überspringe Sync: %s", exc)
            except Exception:
                log.exception("Paperless-Sync fehlgeschlagen")

    async def _sync_invoices(self, client: PaperlessClient, ids: dict[str, int | None]) -> None:
        doctype_id = ids.get("doctype")
        if doctype_id is None:
            log.warning(
                "Dokumententyp '%s' in Paperless nicht gefunden",
                self.settings.paperless_invoice_doctype,
            )
            return
        for doc in await client.list_documents(document_type_id=doctype_id):
            correspondent = await self._correspondent_name(client, doc)
            # Stammdaten vor dem Upsert lesen, damit ein SYNCED-Event nur bei echter
            # Änderung (Neuanlage/geänderter Titel/Korrespondent) entsteht — sonst würde
            # invoice_events bei jedem Idle-Sync unbegrenzt wachsen.
            before = self.repo.get_invoice_by_paperless(doc.id)
            invoice_id = self.repo.upsert_invoice(
                paperless_id=doc.id,
                title=doc.title,
                correspondent=correspondent,
                document_date=doc.created,
            )
            is_new = before is None
            if is_new or before.title != doc.title or before.correspondent != correspondent:
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.SYNCED)
            if is_new or before.giro_status == GiroStatus.NONE:
                await self._extract_and_store(client, ids, invoice_id, doc)

    async def _sync_sevdesk_tag(self, client: PaperlessClient, ids: dict[str, int | None]) -> None:
        tag_id = ids.get("sevdesk_tag")
        if tag_id is None:
            return
        for doc in await client.list_documents(tag_ids=[tag_id]):
            invoice_id = self.repo.upsert_invoice(
                paperless_id=doc.id,
                title=doc.title,
                correspondent=await self._correspondent_name(client, doc),
                document_date=doc.created,
            )
            inv = self.repo.get_invoice(invoice_id)
            if inv and inv.sevdesk_status == SevdeskStatus.NONE:
                self.repo.set_sevdesk_status(invoice_id, SevdeskStatus.QUEUED)
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.SEVDESK_QUEUED)
                if self.sevdesk_enabled and self.settings.sevdesk_auto_export:
                    await self.export_invoice(invoice_id)

    async def _correspondent_name(
        self, client: PaperlessClient, doc: PaperlessDocument
    ) -> str | None:
        if not doc.correspondent_id:
            return None
        try:
            return await client.get_correspondent_name(doc.correspondent_id)
        except Exception:
            return None

    async def _extract_and_store(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        invoice_id: int,
        doc: PaperlessDocument,
    ) -> None:
        try:
            pdata, source = await self._extract_payment(client, doc)
        except Exception:
            log.exception("GiroCode-Extraktion für Dokument %s fehlgeschlagen", doc.id)
            self.repo.set_giro_data(
                invoice_id, creditor_name=None, iban=None, bic=None, amount=None,
                currency="EUR", purpose=None, source="error", giro_status=GiroStatus.FAILED,
            )
            return
        status = GiroStatus.READY if valid_iban(pdata.iban) else GiroStatus.FAILED
        self.repo.set_giro_data(
            invoice_id,
            creditor_name=pdata.creditor_name,
            iban=pdata.iban,
            bic=pdata.bic,
            amount=pdata.amount,
            currency=pdata.currency,
            purpose=pdata.purpose,
            source=source,
            giro_status=status,
        )
        self.repo.add_invoice_event(
            invoice_id,
            InvoiceEventType.GIRO_EXTRACTED,
            f"Quelle={source}, IBAN={'ok' if valid_iban(pdata.iban) else 'fehlt'}",
        )
        if status == GiroStatus.READY:
            await self._write_back_giro(client, ids, doc.id, pdata)

    async def _extract_payment(
        self, client: PaperlessClient, doc: PaperlessDocument
    ) -> tuple[PaymentData, str]:
        content, filename = await client.download_original(doc.id)
        pdata: PaymentData | None = None
        source = "ocr"
        if filename.lower().endswith(".xml"):
            pdata = extract_from_einvoice_xml(content)
            source = "einvoice"
        else:
            embedded = extract_embedded_invoice_xml(content)
            if embedded:
                pdata = extract_from_einvoice_xml(embedded)
                source = "einvoice"

        creditor = None
        if self.settings.girocode_creditor_from_correspondent and doc.correspondent_id:
            creditor = await self._correspondent_name(client, doc)

        if pdata is None or not pdata.iban:
            ocr = extract_from_ocr_text(doc.content, fallback_creditor=creditor)
            if pdata is None:
                return ocr, "ocr"
            # E-Rechnung lieferte keine IBAN: OCR-Fallback ergänzen.
            pdata.iban = pdata.iban or ocr.iban
            pdata.amount = pdata.amount if pdata.amount is not None else ocr.amount

        if not pdata.creditor_name:
            pdata.creditor_name = creditor
        return pdata, source

    # ---- UI-Aktionen -----------------------------------------------------

    async def save_giro_edits(
        self,
        invoice_id: int,
        *,
        creditor_name: str | None,
        iban: str | None,
        bic: str | None,
        amount: float | None,
        purpose: str | None,
    ) -> None:
        inv = self.repo.get_invoice(invoice_id)
        if inv is None:
            return
        pdata = PaymentData(
            creditor_name=creditor_name,
            iban=iban,
            bic=bic,
            amount=amount,
            currency=inv.currency,
            purpose=purpose,
        )
        self.repo.set_giro_data(
            invoice_id,
            creditor_name=pdata.creditor_name,
            iban=pdata.iban,
            bic=pdata.bic,
            amount=pdata.amount,
            currency=pdata.currency,
            purpose=pdata.purpose,
            source="manual",
            giro_status=GiroStatus.EDITED if valid_iban(pdata.iban) else GiroStatus.FAILED,
        )
        self.repo.add_invoice_event(invoice_id, InvoiceEventType.GIRO_EDITED)
        if self.enabled and valid_iban(pdata.iban):
            try:
                async with self._paperless() as client:
                    ids = await self._resolve(client)
                    await self._write_back_giro(client, ids, inv.paperless_id, pdata)
            except Exception:
                log.exception("Rückschrieb der GiroCode-Daten fehlgeschlagen")

    async def export_invoice(self, invoice_id: int) -> None:
        inv = self.repo.get_invoice(invoice_id)
        if inv is None:
            return
        if not self.sevdesk_enabled:
            self.repo.set_sevdesk_status(
                invoice_id, SevdeskStatus.FAILED, error_message="SevDesk-Export ist deaktiviert"
            )
            return
        # Atomarer Claim: verhindert Doppel-Belege bei gleichzeitigen oder wiederholten
        # Export-Aufrufen (UI-Doppelklick, Auto-Export trifft auf manuellen Klick, Re-Sync).
        if not self.repo.claim_for_export(invoice_id):
            log.info(
                "SevDesk-Export übersprungen — Rechnung %s bereits exportiert oder in Arbeit",
                invoice_id,
            )
            return
        # Datei laden + Temp-Upload erzeugen noch KEINEN Beleg → Fehler sind eindeutig
        # retrybar (Status failed).
        try:
            async with self._paperless() as client:
                content, filename = await client.download_original(inv.paperless_id)
            mime = mimetypes.guess_type(filename)[0] or "application/pdf"
            async with self._sevdesk() as sev:
                temp_name = await sev.upload_temp_file(content, filename, mime)
        except Exception as exc:
            log.exception("SevDesk-Vorbereitung für Rechnung %s fehlgeschlagen", invoice_id)
            self._mark_export_failed(invoice_id, exc)
            return

        # saveVoucher legt den Beleg an. Hier ist die Fehlerklassifizierung entscheidend:
        # - HTTPStatusError = Server hat abgelehnt → kein Beleg → retrybar (failed).
        # - alles andere (Transportfehler/Timeout, fehlende Beleg-ID in 200) = mehrdeutig,
        #   der Beleg könnte angelegt worden sein → NICHT auto-retrybar (uncertain).
        try:
            async with self._sevdesk() as sev:
                result = await sev.save_voucher_from_temp(
                    temp_name, description=inv.title or filename
                )
        except httpx.HTTPStatusError as exc:
            # Nur eindeutige Client-Ablehnungen (4xx) sind retrybar — dabei wurde kein Beleg
            # angelegt. 5xx ist mehrdeutig, weil der Server den Beleg evtl. schon erzeugt hat,
            # bevor die Fehlerantwort kam → kein Auto-Retry.
            status = exc.response.status_code
            if status < 500:
                log.warning(
                    "SevDesk lehnte Beleg für Rechnung %s ab (HTTP %s)", invoice_id, status
                )
                self._mark_export_failed(invoice_id, exc)
            else:
                log.warning(
                    "SevDesk-Serverfehler (HTTP %s) für Rechnung %s — mehrdeutig",
                    status,
                    invoice_id,
                )
                self._mark_export_uncertain(invoice_id, exc)
            return
        except Exception as exc:
            log.exception(
                "SevDesk-Export für Rechnung %s mehrdeutig fehlgeschlagen", invoice_id
            )
            self._mark_export_uncertain(invoice_id, exc)
            return

        self.repo.set_sevdesk_status(
            invoice_id, SevdeskStatus.EXPORTED, voucher_id=result.voucher_id
        )
        self.repo.add_invoice_event(
            invoice_id, InvoiceEventType.SEVDESK_EXPORTED, f"Beleg {result.voucher_id}"
        )
        if self.enabled:
            try:
                await self._write_back_export(inv.paperless_id, result.voucher_id, result.link)
                self.repo.mark_written_back(invoice_id)
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.WRITTEN_BACK)
            except Exception:
                log.exception("Rückschrieb des SevDesk-Exports fehlgeschlagen")

    def _mark_export_failed(self, invoice_id: int, exc: Exception) -> None:
        """Eindeutiger Fehlschlag ohne angelegten Beleg → retrybar (Status failed)."""
        self.repo.set_sevdesk_status(
            invoice_id, SevdeskStatus.FAILED, error_message=str(exc)[:500]
        )
        self.repo.add_invoice_event(invoice_id, InvoiceEventType.SEVDESK_FAILED, str(exc)[:200])

    def _mark_export_uncertain(self, invoice_id: int, exc: Exception) -> None:
        """Mehrdeutiger Fehlschlag — Beleg könnte angelegt sein → kein Auto-Retry (uncertain)."""
        self.repo.set_sevdesk_status(
            invoice_id,
            SevdeskStatus.UNCERTAIN,
            error_message=(
                "Mehrdeutiger Fehler beim Anlegen des Belegs — in SevDesk prüfen, ob der "
                f"Beleg existiert, bevor erneut exportiert wird. Ursache: {str(exc)[:300]}"
            ),
        )
        self.repo.add_invoice_event(
            invoice_id, InvoiceEventType.SEVDESK_FAILED, f"mehrdeutig: {str(exc)[:180]}"
        )

    async def set_paid(self, invoice_id: int, paid: bool) -> None:
        inv = self.repo.get_invoice(invoice_id)
        if inv is None:
            return
        self.repo.set_paid(invoice_id, paid)
        self.repo.add_invoice_event(
            invoice_id, InvoiceEventType.MARKED_PAID, "überwiesen" if paid else "zurückgesetzt"
        )
        if self.enabled:
            try:
                async with self._paperless() as client:
                    ids = await self._resolve(client)
                    if ids.get("cf_paid") is not None:
                        await client.set_custom_fields(
                            inv.paperless_id, {ids["cf_paid"]: paid}
                        )
                    if paid and ids.get("tag_paid") is not None:
                        await client.add_tags(inv.paperless_id, [ids["tag_paid"]])
                    await client.add_note(
                        inv.paperless_id,
                        "Als überwiesen markiert (Lector)" if paid else "Überweisung zurückgesetzt",
                    )
            except Exception:
                log.exception("Rückschrieb 'überwiesen' fehlgeschlagen")

    async def fetch_preview(self, invoice_id: int) -> tuple[bytes, str] | None:
        """Lädt die Dokumentvorschau einer Rechnung über Paperless (für den UI-Proxy).

        Gibt ``None`` zurück, wenn die Rechnung unbekannt ist oder die Paperless-
        Anbindung nicht konfiguriert ist.
        """
        if not self.enabled:
            return None
        inv = self.repo.get_invoice(invoice_id)
        if inv is None:
            return None
        async with self._paperless() as client:
            return await client.download_preview(inv.paperless_id)

    # ---- Empfänger-Zuordnung --------------------------------------------

    async def _recipient_field_cached(self, client: PaperlessClient) -> SelectField | None:
        if not self._recipient_field_resolved:
            self._recipient_field = await client.resolve_select_field(self.settings.cf_recipient)
            self._recipient_field_resolved = True
        return self._recipient_field

    async def _corr_map_cached(self, client: PaperlessClient) -> dict[int, str]:
        if self._corr_map is None:
            self._corr_map = await client.correspondent_map()
        return self._corr_map

    @property
    def recipient_options(self) -> list[str]:
        return self._recipient_field.labels if self._recipient_field else []

    async def count_missing_recipients(self) -> int:
        """Zählt Dokumente ohne gesetzten Empfänger (nur der Zähler, keine Seiteninhalte)."""
        async with self._paperless() as client:
            field = await self._recipient_field_cached(client)
            if field is None:
                return 0
            page = await client.search_documents(
                page=1, page_size=1, missing_field_id=field.field_id
            )
            return page.count

    async def list_recipient_documents(
        self, *, page: int = 1, search: str | None = None, only_missing: bool = False
    ) -> tuple[list[RecipientRow], DocumentPage, SelectField | None]:
        async with self._paperless() as client:
            field = await self._recipient_field_cached(client)
            missing_id = field.field_id if (only_missing and field) else None
            page_obj = await client.search_documents(
                page=page,
                page_size=RECIPIENT_PAGE_SIZE,
                query=search,
                missing_field_id=missing_id,
            )
            corr = await self._corr_map_cached(client)
            caches = self.repo.get_recipient_caches([d.id for d in page_obj.documents])
            rows: list[RecipientRow] = []
            for d in page_obj.documents:
                current = None
                if field:
                    opt_id = client.select_value(d, field.field_id)
                    current = field.id_to_label.get(opt_id) if opt_id else None
                rows.append(
                    RecipientRow(
                        paperless_id=d.id,
                        title=d.title or f"#{d.id}",
                        correspondent=(
                            corr.get(d.correspondent_id) if d.correspondent_id else None
                        ),
                        document_date=_parse_paperless_date(d.created),
                        current_recipient=current,
                        cache=caches.get(d.id),
                    )
                )
            return rows, page_obj, field

    async def set_recipient(self, paperless_id: int, label: str | None) -> bool:
        """Schreibt den Empfänger (oder leert ihn bei ``label=None``) ins Paperless-Feld.

        Liefert ``False``, wenn das select-Feld fehlt oder ein unbekanntes Label übergeben wurde.
        """
        if not self.recipient_enabled:
            return False
        async with self._paperless() as client:
            field = await self._recipient_field_cached(client)
            if field is None:
                return False
            value: object | None
            if label is None:
                value = None
            else:
                value = field.label_to_id.get(label)
                if value is None:
                    log.warning("Unbekanntes Empfänger-Label '%s' ignoriert", label)
                    return False
            async with self._recipient_write_lock:
                await client.set_custom_fields(paperless_id, {field.field_id: value})
                self.repo.mark_recipient_applied(paperless_id)
        return True

    async def suggest_recipient(self, paperless_id: int) -> RecipientSuggestion | None:
        """KI-Vorschlag für ein einzelnes Dokument; wendet ihn ggf. automatisch an."""
        if not self.recipient_llm_enabled:
            return None
        async with self._paperless() as client:
            field = await self._recipient_field_cached(client)
            if field is None or not field.labels:
                return None
            doc = await client.get_document(paperless_id)
            correspondent = await self._correspondent_name(client, doc)
            async with self._suggester() as suggester:
                return await self._suggest_for_doc(client, suggester, field, doc, correspondent)

    def start_batch(self, limit: int | None = None) -> None:
        """Startet den Batch-Lauf im Hintergrund und hält eine Task-Referenz.

        Ohne gehaltene Referenz könnte der Event-Loop den Task verwerfen, da er nur
        schwache Referenzen auf Tasks hält.
        """
        # _batch_task deckt auch das Fenster ab, in dem der Task erstellt, aber noch nicht
        # gelaufen ist (dort ist _progress.running noch False) — verhindert doppelte Läufe.
        if (
            not self.recipient_llm_enabled
            or self._progress.running
            or self._batch_task is not None
        ):
            return
        self._batch_task = asyncio.create_task(self.suggest_recipients_batch(limit))
        self._batch_task.add_done_callback(lambda _: setattr(self, "_batch_task", None))

    async def suggest_recipients_batch(self, limit: int | None = None) -> int:
        """Schlägt für bis zu ``limit`` Dokumente ohne Empfänger einen vor (Hintergrund-Lauf).

        ``None`` bedeutet die in den Einstellungen hinterlegte Obergrenze. Liefert die
        Anzahl verarbeiteter Dokumente. Bereits mit Vorschlag/Empfänger versehene
        Dokumente werden übersprungen, sodass der Lauf gefahrlos wiederholbar ist.
        """
        if not self.recipient_llm_enabled or self._progress.running:
            return 0
        maximum = self.settings.recipient_batch_max
        effective = maximum if limit is None else min(limit, maximum)
        self._batch_stop = False
        self._progress = BatchProgress(running=True)
        streak = 0
        last_publish = 0.0
        # Nur die jenseits des Limits gefundenen Dokumente (aus _collect_missing_ids) —
        # bleibt der Lauf durch Stopp/Fehlerserie/Ausnahme vor dem Ende der Liste stehen,
        # zählt das ``finally`` unten die eingeplanten, aber nicht mehr erreichten
        # Dokumente hinzu. Vorbelegt, falls die Ausnahme schon vor der Zuweisung greift.
        rest = 0

        def publish(force: bool = False) -> None:
            nonlocal last_publish
            now = time.monotonic()
            if force or now - last_publish >= BATCH_PUBLISH_INTERVAL:
                last_publish = now
                self.repo.notify_batch()

        try:
            async with self._paperless() as client:
                field = await self._recipient_field_cached(client)
                if field is None or not field.labels:
                    self._progress.aborted_reason = (
                        "Empfänger-Feld ist in Paperless nicht vorhanden oder hat keine "
                        "Auswahloptionen — Lauf beendet, ohne ein Dokument zu bearbeiten."
                    )
                    return 0
                doc_ids, rest = await self._collect_missing_ids(client, field, effective)
                self._progress.total = len(doc_ids)
                self._progress.remaining = rest
                publish(force=True)
                async with self._suggester() as suggester:
                    for doc_id in doc_ids:
                        if self._batch_stop:
                            self._progress.stopped = True
                            break
                        # Erneut prüfen: Der Lauf kann lange dauern; in der Zwischenzeit kann
                        # ein Dokument per UI bearbeitet worden sein (manueller Empfänger /
                        # Einzelvorschlag). Dann nicht erneut verarbeiten/überschreiben — zählt
                        # aber sichtbar als "übersprungen", nicht stillschweigend gar nicht.
                        cache = self.repo.get_recipient_cache(doc_id)
                        if cache and cache.status != RecipientStatus.NONE:
                            self._progress.skipped += 1
                        else:
                            try:
                                doc = await client.get_document(doc_id)
                                correspondent = await self._correspondent_name(client, doc)
                                await self._suggest_for_doc(
                                    client, suggester, field, doc, correspondent,
                                    guard_concurrent=True,
                                )
                                self._progress.done += 1
                                streak = 0
                            except Exception:
                                log.exception(
                                    "Empfänger-Vorschlag für Dokument %s fehlgeschlagen", doc_id
                                )
                                self._progress.failed += 1
                                streak += 1
                                if streak >= BATCH_ERROR_STREAK:
                                    self._progress.aborted_reason = (
                                        f"{streak} Fehler in Folge — Lauf abgebrochen. "
                                        "Bitte Log und API-Zugang prüfen."
                                    )
                                    publish()
                                    break
                        # Auch beim Überspringen melden — sonst bleibt der Fortschrittsbalken
                        # bei vielen Übersprüngen in Folge minutenlang stehen, weil publish()
                        # sonst nur bei done/failed erreicht würde.
                        publish()
        except Exception as exc:
            # Ausnahme VOR/ZWISCHEN der Dokumentschleife (z.B. Paperless während des
            # Batch-Starts neu gestartet) darf den Lauf nicht wortlos mit "0 verarbeitet"
            # enden lassen — sonst zeigt die Oberfläche einen unauffälligen Erfolg vor.
            log.exception("Empfänger-Batch vor/während der Verarbeitung abgebrochen")
            self._progress.aborted_reason = (
                f"Lauf abgebrochen — unerwarteter Fehler: {exc}"
            )
        finally:
            self._progress.running = False
            # Eingeplante, aber wegen Stopp/Fehlerserie/Ausnahme nicht mehr erreichte
            # Dokumente zählen zum offenen Rest dazu — sonst zeigt "offen" nur den
            # Limit-Rest und unterschlägt einen abgebrochenen Lauf fast vollständig.
            processed = self._progress.done + self._progress.failed + self._progress.skipped
            unprocessed = max(0, self._progress.total - processed)
            self._progress.remaining = rest + unprocessed
            self._progress.finished_at = datetime.now(UTC)
            publish(force=True)
        log.info(
            "Empfänger-Batch beendet: %s verarbeitet, %s übersprungen, %s Fehler, %s offen",
            self._progress.done, self._progress.skipped, self._progress.failed,
            self._progress.remaining,
        )
        return self._progress.done

    async def _collect_missing_ids(
        self, client: PaperlessClient, field: SelectField, limit: int
    ) -> tuple[list[int], int]:
        """Sammelt bis zu ``limit`` IDs von Dokumenten ohne Empfänger und ohne Vorschlag.

        Liefert zusätzlich den Rest: wie viele passende Dokumente wegen des Limits
        **nicht** eingeplant wurden. Bereits gecachte Dokumente (Status != ``none``)
        werden übersprungen, damit ein wiederholter Lauf tatsächlich neue Dokumente
        erreicht und nicht an den ersten hängen bleibt.
        """
        ids: list[int] = []
        rest = 0
        page = 1
        while True:
            page_obj = await client.search_documents(
                page=page, page_size=RECIPIENT_PAGE_SIZE, missing_field_id=field.field_id
            )
            if not page_obj.documents:
                break
            page_ids = [d.id for d in page_obj.documents]
            caches = self.repo.get_recipient_caches(page_ids)
            for doc_id in page_ids:
                cache = caches.get(doc_id)
                if cache and cache.status != RecipientStatus.NONE:
                    continue
                if len(ids) < limit:
                    ids.append(doc_id)
                else:
                    rest += 1
            if page >= page_obj.total_pages:
                break
            page += 1
        return ids, rest

    async def _suggest_for_doc(
        self,
        client: PaperlessClient,
        suggester: RecipientSuggester,
        field: SelectField,
        doc: PaperlessDocument,
        correspondent: str | None,
        *,
        guard_concurrent: bool = False,
    ) -> RecipientSuggestion:
        suggestion = await suggester.suggest(
            title=doc.title,
            correspondent=correspondent,
            content=doc.content,
            options=field.labels,
        )
        s = self.settings
        auto = (
            s.recipient_llm_auto_apply
            and suggestion.label is not None
            and suggestion.confidence >= s.recipient_llm_min_confidence
        )
        # Check + Write atomar unter dem Write-Lock: Der LLM-Call oben dauert; in dieser Zeit
        # kann das Dokument einen Empfänger bekommen haben. Der Lock serialisiert gegen
        # set_recipient, sodass der Re-Check unmittelbar vor dem Write greift. Maßgeblich ist
        # das Paperless-Feld SELBST (nicht nur Lectors Cache): Es kann auch direkt in Paperless
        # gesetzt worden sein. Daher live gegenprüfen und einen vorhandenen Empfänger nicht
        # überschreiben. Beim nutzerinitiierten Einzel-Vorschlag ist Überschreiben gewollt
        # (guard_concurrent=False).
        async with self._recipient_write_lock:
            if guard_concurrent:
                fresh = await client.get_document(doc.id)
                if client.select_value(fresh, field.field_id):
                    return suggestion
                cache = self.repo.get_recipient_cache(doc.id)
                if cache and cache.status != RecipientStatus.NONE:
                    return suggestion
            # Im Batch-Lauf (guard_concurrent=True) löst JEDES Dokument sonst zusätzlich zum
            # gedrosselten "batch:recipient"-Ereignis ein eigenes ungedrosseltes "rec:<id>"
            # aus — 1500 Dokumente erzeugen dann 1500 SSE-Ereignisse, die die Drossel gerade
            # verhindern soll. Der Einzel-Vorschlag (guard_concurrent=False) meldet weiterhin
            # sofort, weil dort kein Batch-Ereignis nachzieht.
            notify = not guard_concurrent
            if auto:
                option_id = field.label_to_id.get(suggestion.label or "")
                if option_id:
                    await client.set_custom_fields(doc.id, {field.field_id: option_id})
                    self.repo.mark_recipient_applied(doc.id, notify=notify)
                    return suggestion
            status = RecipientStatus.SUGGESTED if suggestion.label else RecipientStatus.UNKNOWN
            self.repo.set_recipient_cache(
                doc.id,
                suggested_label=suggestion.label,
                confidence=suggestion.confidence,
                reasoning=suggestion.reasoning,
                status=status,
                notify=notify,
            )
        return suggestion

    # ---- Rückschrieb-Helfer ---------------------------------------------

    async def _write_back_giro(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        paperless_id: int,
        pdata: PaymentData,
    ) -> None:
        values: dict[int, object] = {}
        if ids.get("cf_giro_iban") is not None and pdata.iban:
            values[ids["cf_giro_iban"]] = pdata.iban  # type: ignore[index]
        if ids.get("cf_giro_amount") is not None and pdata.amount is not None:
            values[ids["cf_giro_amount"]] = f"{pdata.amount:.2f} {pdata.currency}"  # type: ignore[index]
        if values:
            await client.set_custom_fields(paperless_id, values)

    async def _write_back_export(
        self, paperless_id: int, voucher_id: str, link: str | None
    ) -> None:
        async with self._paperless() as client:
            ids = await self._resolve(client)
            values: dict[int, object] = {}
            if ids.get("cf_sevdesk_id") is not None:
                values[ids["cf_sevdesk_id"]] = voucher_id  # type: ignore[index]
            if ids.get("cf_exported_at") is not None:
                values[ids["cf_exported_at"]] = datetime.now(UTC).strftime("%Y-%m-%d")  # type: ignore[index]
            if values:
                await client.set_custom_fields(paperless_id, values)
            if ids.get("tag_sevdesk_done") is not None:
                await client.add_tags(paperless_id, [ids["tag_sevdesk_done"]])  # type: ignore[list-item]
            note = f"Nach SevDesk exportiert — Beleg {voucher_id}"
            if link:
                note += f" ({link})"
            await client.add_note(paperless_id, note)
