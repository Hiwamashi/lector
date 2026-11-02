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
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from .config import Settings
from .context_classification import same_label
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
    MatchKind,
    PaperlessInvoice,
    RecipientCache,
    RecipientRow,
    RecipientStatus,
    RecipientSuggestion,
    SevdeskStatus,
    SevdeskVoucher,
)
from .paperless import (
    CF_TYPE_BOOLEAN,
    CF_TYPE_DATE,
    CF_TYPE_STRING,
    DocumentPage,
    NoteEntry,
    PaperlessClient,
    PaperlessDocument,
    SelectField,
)
from .recipient_llm import RecipientSuggester
from .repository import Repository
from .sevdesk import SevdeskClient, _as_iso_date
from .sevdesk_export_checks import (
    ExportBlockers,
    ExportOutcome,
    ExportStatus,
    export_blockers,
)
from .sevdesk_matching import compute_matches

log = logging.getLogger("lector.paperless_sync")

# „Alle Rechnungen“ für die Neuberechnung des Abgleichs (list_invoices ist sonst auf 200 begrenzt).
_ALL_INVOICES = 1_000_000

# Seitengröße der Empfänger-Übersicht.
RECIPIENT_PAGE_SIZE = 50

# Nach so vielen Fehlschlägen in Folge wird der Lauf beendet: ein dauerhaft gedrosseltes
# oder fehlkonfiguriertes Konto soll nicht wirkungslos durch hunderte Dokumente laufen.
BATCH_ERROR_STREAK = 10
# Der Lauf meldet Fortschritt höchstens so oft — sonst erzeugt ein Lauf über 1500
# Dokumente ebenso viele SSE-Ereignisse für jeden verbundenen Client.
BATCH_PUBLISH_INTERVAL = 2.0


# Lebensdauer der Namenslisten (Korrespondenten, Dokumenttypen, Tags, Felder), siehe Design D4.
NAME_CACHE_TTL = 600.0

# So lange gilt eine nach dem Neuladen weiter unbekannte ID als „fehlt“ und löst kein
# weiteres Neuladen aus (gelöscht oder für Lectors Zugang nicht sichtbar).
NAME_MISS_TTL = 60.0

# Art der Namensliste -> Methode des Paperless-Clients, die ``{id: name}`` liefert.
_NAME_LOADERS = {
    "correspondent": "correspondent_map",
    "document_type": "document_type_map",
    "tag": "tag_map",
    "field": "custom_field_map",
}


@dataclass
class CustomFieldValue:
    """Ein Custom Field eines Dokuments mit Namen und lesbarem Wert (nur Anzeige)."""

    name: str
    value: str


@dataclass
class DocumentView:
    """Alles, was die Dokumentansicht zu einem Paperless-Dokument anzeigt."""

    paperless_id: int
    title: str
    correspondent: str | None
    document_type: str | None
    created: datetime | None
    added: datetime | None
    archive_serial_number: int | None
    page_count: int | None
    tags: list[str]
    custom_fields: list[CustomFieldValue]
    notes: list[NoteEntry]
    # Lector-Rechnung zu diesem Dokument (nur bei bekannter Rechnung), sonst ``None``.
    invoice: PaperlessInvoice | None
    # Empfänger-Feld: existiert es, welche Optionen gibt es, welcher Wert ist gesetzt.
    recipient_field_present: bool
    recipient_options: list[str]
    current_recipient: str | None


def _select_options_of(definitions: list[dict]) -> dict[int, dict[str, str]]:
    """Liest die Optionen aller select-Felder: ``{field_id: {wert: label}}``.

    Paperless 2.x liefert ``extra_data.select_options`` als Liste von ``{id, label}`` (der
    Wert am Dokument ist die Options-ID), ältere Versionen als Liste von Texten (der Wert ist
    der Index).
    """
    result: dict[int, dict[str, str]] = {}
    for f in definitions:
        if f.get("data_type") != "select" or f.get("id") is None:
            continue
        options: dict[str, str] = {}
        for index, opt in enumerate((f.get("extra_data") or {}).get("select_options") or []):
            if isinstance(opt, dict):
                if opt.get("id") is not None and opt.get("label"):
                    options[str(opt["id"])] = str(opt["label"])
            else:
                options[str(index)] = str(opt)
        result[int(f["id"])] = options
    return result


def _format_field_value(value: object) -> str:
    """Lesbare Darstellung eines Custom-Field-Werts; leer wird zu „—“."""
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value)


def _write_back_error(exc: Exception) -> str:
    """Gekürzte Fehlermeldung für das Ereignis „Rückschrieb fehlgeschlagen“."""
    return f"{type(exc).__name__}: {exc}"[:200]


def _recipient_cache_complete(cache: RecipientCache | None) -> bool:
    """Ein Cache-Eintrag gilt als vollständig, wenn ein Vorschlag (Status != ``none``) UND
    eine IT-Consulting-Einschätzung vorliegen. Alte Einträge aus der Zeit vor der
    Export-Übersicht haben keinen Wert und werden vom Batch-Lauf nachgeholt. Ein
    Vorschlag „unbekannt“ mit gültigem Wert ist vollständig."""
    return (
        cache is not None
        and cache.status != RecipientStatus.NONE
        and cache.it_probability is not None
    )


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
        # Namenslisten je Art: ``{art: (Ladezeitpunkt, {id: name})}``, siehe ``_names``.
        self._name_cache: dict[str, tuple[float, dict[int, str]]] = {}
        # Negativ-Cache: ``{(art, id): Zeitpunkt}`` für IDs, die nach einem Neuladen fehlten.
        self._name_misses: dict[tuple[str, int], float] = {}
        # Select-Optionen je Custom Field (``{field_id: {wert: label}}``), zusammen mit der
        # Feldnamen-Liste geladen und von ihr verwaltet.
        self._field_options: dict[int, dict[str, str]] = {}
        self._progress = BatchProgress()
        self._batch_stop = False
        # Referenz auf den laufenden Batch-Task halten, damit der Event-Loop ihn nicht
        # (er hält nur schwache Referenzen) mitten im Lauf garbage-collected.
        self._batch_task: asyncio.Task[int] | None = None
        # Serialisiert das Zurückschreiben des Empfängers (manuell vs. KI-Batch), damit
        # ein nebenläufiger Batch-Write keinen gerade manuell gesetzten Empfänger überschreibt.
        self._recipient_write_lock = asyncio.Lock()
        # Verhindert überlappende Belegabrufe (Worker-Takt vs. Knopf in der Übersicht).
        self._voucher_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(s.feature_paperless_sync and s.paperless_url and s.paperless_token)

    @property
    def view_enabled(self) -> bool:
        """Dokumentansicht und Vorschau-Proxy brauchen nur URL + Token (wie die Empfänger)."""
        s = self.settings
        return bool(s.paperless_url and s.paperless_token)

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
        # Mit Label fordert der Aufruf zusätzlich die IT-Consulting-Wahrscheinlichkeit an;
        # das Label steht beim Start fest, damit das Prompt-Caching erhalten bleibt.
        return RecipientSuggester(
            self.settings.anthropic_api_key,
            self.settings.recipient_llm_model,
            context_label=self.settings.sevdesk_context_label,
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
                    # Korrespondenten-Karte EINMAL je Lauf holen statt je Dokument einzeln
                    # abzufragen (vormals ein HTTP-Aufruf pro Dokument — bei geteilten
                    # Korrespondenten mehrere hundert Anfragen je Lauf). Bewusst NICHT
                    # prozessweit gecacht wie ``_corr_map_cached``: ein in Paperless
                    # umbenannter Korrespondent soll sofort im nächsten Lauf stimmen,
                    # nicht erst nach einem Neustart.
                    corr_map = await client.correspondent_map()
                    # Empfänger-Feld ebenfalls einmal je Lauf auflösen (Optionen-ID ->
                    # Label); fehlt es, bleibt recipient_label lokal unangetastet.
                    recipient_field = await client.resolve_select_field(
                        self.settings.cf_recipient
                    )
                    if recipient_field is not None:
                        self._recipient_field = recipient_field
                        self._recipient_field_resolved = True
                    await self._sync_invoices(client, ids, corr_map, recipient_field)
                    await self._sync_sevdesk_tag(client, ids, corr_map, recipient_field)
                    await self._retry_write_backs(client, ids)
            except httpx.ConnectError as exc:
                # Paperless (noch) nicht erreichbar — typisch beim Start, wenn der
                # webserver-Container später hochfährt. Nächster Lauf greift erneut.
                log.warning("Paperless nicht erreichbar, überspringe Sync: %s", exc)
            except Exception:
                log.exception("Paperless-Sync fehlgeschlagen")
        # Gespiegelte Felder (Empfänger, Beleg-Vermerk) und Rechnungen haben sich ggf.
        # geändert: Treffer neu berechnen — ohne SevDesk-Aufruf, auf Basis des Abzugs.
        try:
            self.recompute_matches()
        except Exception:
            log.exception("Neuberechnung des Belegabgleichs nach dem Sync fehlgeschlagen")

    def _mirrored_fields(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        doc: PaperlessDocument,
        recipient_field: SelectField | None,
    ) -> dict[str, str | None]:
        """Paperless-Felder, die lokal gespiegelt werden (Design 2), als ``upsert_invoice``-kwargs.

        Nur Felder, die in Paperless auflösbar sind, kommen vor: Fehlt das Empfänger-Feld
        oder das Feld „SevDesk-Beleg“, fehlt der kwarg und die lokale Spalte bleibt, wie sie
        ist (kein NULL aus Unkenntnis). Ist das Feld vorhanden, aber am Dokument leer oder
        entfernt, ergibt das ``None`` und damit lokal NULL.
        """
        mirrored: dict[str, str | None] = {}
        if recipient_field is not None:
            option_id = client.select_value(doc, recipient_field.field_id)
            mirrored["recipient_label"] = (
                recipient_field.id_to_label.get(option_id) if option_id else None
            )
        voucher_field_id = ids.get("cf_sevdesk_id")
        if voucher_field_id is not None:
            value: str | None = None
            for cf in doc.custom_fields:
                if int(cf.get("field")) == voucher_field_id:
                    raw = cf.get("value")
                    value = str(raw).strip() if raw is not None else None
                    break
            mirrored["paperless_voucher_ref"] = value or None
        return mirrored

    async def _sync_invoices(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        corr_map: dict[int, str],
        recipient_field: SelectField | None = None,
    ) -> None:
        doctype_id = ids.get("doctype")
        if doctype_id is None:
            log.warning(
                "Dokumententyp '%s' in Paperless nicht gefunden",
                self.settings.paperless_invoice_doctype,
            )
            return
        for doc in await client.list_documents(document_type_id=doctype_id):
            correspondent = await self._correspondent_name(client, doc, corr_map)
            # Stammdaten vor dem Upsert lesen, damit ein SYNCED-Event nur bei echter
            # Änderung (Neuanlage/geänderter Titel/Korrespondent) entsteht — sonst würde
            # invoice_events bei jedem Idle-Sync unbegrenzt wachsen.
            before = self.repo.get_invoice_by_paperless(doc.id)
            invoice_id = self.repo.upsert_invoice(
                paperless_id=doc.id,
                title=doc.title,
                correspondent=correspondent,
                document_date=doc.created,
                **self._mirrored_fields(client, ids, doc, recipient_field),
            )
            is_new = before is None
            if is_new or before.title != doc.title or before.correspondent != correspondent:
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.SYNCED)
            if is_new or before.giro_status == GiroStatus.NONE:
                await self._extract_and_store(client, ids, invoice_id, doc, corr_map)

    async def _sync_sevdesk_tag(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        corr_map: dict[int, str],
        recipient_field: SelectField | None = None,
    ) -> None:
        tag_id = ids.get("sevdesk_tag")
        if tag_id is None:
            return
        for doc in await client.list_documents(tag_ids=[tag_id]):
            invoice_id = self.repo.upsert_invoice(
                paperless_id=doc.id,
                title=doc.title,
                correspondent=await self._correspondent_name(client, doc, corr_map),
                document_date=doc.created,
                **self._mirrored_fields(client, ids, doc, recipient_field),
            )
            inv = self.repo.get_invoice(invoice_id)
            if not inv:
                continue
            auto_export = self.sevdesk_enabled and self.settings.sevdesk_auto_export
            # Aus `none` wird vorgemerkt. Eine bereits `queued`e Rechnung wird nur bei
            # Auto-Export erneut bewertet (sie wartete ggf. auf den ersten Belegabruf).
            # `review` (Nutzer entscheidet, auch wenn die Gründe inzwischen weggefallen
            # sind) und `dismissed` bleiben, wie sie sind.
            was_queued = inv.sevdesk_status == SevdeskStatus.QUEUED
            if inv.sevdesk_status != SevdeskStatus.NONE and not (was_queued and auto_export):
                continue
            # Auto-Export nur mit Abgleich: ohne je erfolgreichen Belegabruf fehlt der Abzug,
            # gegen den Dubletten erkannt werden — dann nur vormerken (wie ohne Auto-Export).
            sync_available = self.repo.get_sevdesk_sync_state().last_success_at is not None
            if was_queued and not sync_available:
                continue
            blockers = self._blockers_for(inv)
            if blockers.hard:
                # Schon in SevDesk: weder vormerken noch exportieren. Der Status bleibt;
                # das Ereignis entsteht nur beim ersten Erkennen bzw. wenn sich der
                # Grund ändert, damit nicht jeder Sync-Lauf eines schreibt.
                prefix = "nicht exportiert" if was_queued else "nicht vorgemerkt"
                self._add_event_once(
                    invoice_id,
                    InvoiceEventType.SEVDESK_REVIEW,
                    f"{prefix}: {blockers.hard}",
                )
                continue
            if blockers.reasons:
                # Rückfragegrund: nie automatisch exportieren, auch nicht bei Auto-Export.
                reason = "; ".join(blockers.reasons)
                if self.repo.set_review(invoice_id, reason):
                    self.repo.add_invoice_event(
                        invoice_id, InvoiceEventType.SEVDESK_REVIEW, reason
                    )
                continue
            if not was_queued:
                self.repo.set_sevdesk_status(invoice_id, SevdeskStatus.QUEUED)
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.SEVDESK_QUEUED)
            if auto_export and sync_available:
                outcome = await self.export_invoice(invoice_id)
                if outcome.status != ExportStatus.EXPORTED:
                    log.info(
                        "Auto-Export Rechnung %s: %s (%s)",
                        invoice_id,
                        outcome.status.value,
                        outcome.message,
                    )

    def _blockers_for(self, inv) -> ExportBlockers:
        """``export_blockers`` mit den aktuellen Treffern und dem lokalen Belegabzug."""
        matches = self.repo.list_matches([inv.id])
        refs = {m.voucher_id for m in matches} | {
            v.strip()
            for v in (inv.sevdesk_voucher_id, inv.paperless_voucher_ref)
            if v and v.strip()
        }
        in_cache = {v for v in refs if self.repo.get_voucher(v) is not None}
        return export_blockers(
            inv, matches, in_cache, context_label=self.settings.sevdesk_context_label
        )

    def _add_event_once(
        self, invoice_id: int, event_type: InvoiceEventType, message: str
    ) -> None:
        """Schreibt das Ereignis nur, wenn das letzte gleichartige nicht dieselbe Meldung trägt."""
        last = next(
            (
                e
                for e in reversed(self.repo.list_invoice_events(invoice_id))
                if e["event_type"] == event_type.value
            ),
            None,
        )
        if last is None or last["message"] != message:
            self.repo.add_invoice_event(invoice_id, event_type, message)

    def dismiss_invoice(self, invoice_id: int) -> bool:
        """Verwirft einen Prüffall (Status ``dismissed``, Ereignis) für die Oberfläche.

        Wirkungslos (``False``) bei ``exported``/``exporting``/``uncertain``. ``dismissed``
        wird vom Tag-Weg nicht erneut vorgemerkt.
        """
        if not self.repo.dismiss(invoice_id):
            return False
        self.repo.add_invoice_event(invoice_id, InvoiceEventType.SEVDESK_DISMISSED)
        return True

    async def _correspondent_name(
        self,
        client: PaperlessClient,
        doc: PaperlessDocument,
        corr_map: dict[int, str] | None = None,
    ) -> str | None:
        """Löst den Korrespondentennamen eines Dokuments auf.

        ``corr_map`` ist optional: Ist eine (je Lauf gebaute) Karte übergeben und enthält
        sie die ID, wird sie ohne HTTP-Aufruf benutzt. Fehlt die ID in der Karte (z.B. ein
        Korrespondent, der nach dem Bau der Karte angelegt wurde) oder wird gar keine Karte
        übergeben — wie beim Einzelvorschlag für genau ein Dokument —, greift der bisherige
        Einzelabruf als Rückfall, damit der Name nicht stillschweigend verloren geht.
        """
        if not doc.correspondent_id:
            return None
        if corr_map is not None and doc.correspondent_id in corr_map:
            return corr_map[doc.correspondent_id]
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
        corr_map: dict[int, str],
    ) -> None:
        try:
            pdata, source = await self._extract_payment(client, doc, corr_map)
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
        self, client: PaperlessClient, doc: PaperlessDocument, corr_map: dict[int, str]
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
            creditor = await self._correspondent_name(client, doc, corr_map)

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

    # ---- SevDesk-Belegabzug und Abgleich ----------------------------------

    async def sync_vouchers(self) -> bool:
        """Ruft alle Belege aus SevDesk ab und berechnet danach den Abgleich neu.

        Läuft nur bei aktivem SevDesk-Export und höchstens einmal gleichzeitig (Worker-Takt
        und „Abgleich aktualisieren“ können sich überlappen). Der Abzug wird ausschließlich
        nach einem VOLLSTÄNDIG durchgelaufenen Abruf ersetzt; scheitert der Abruf (auch
        mitten im Blättern), bleibt der alte Abzug stehen und der Fehler landet im
        Sync-Zustand. Wirft nie nach außen. Liefert ``True`` bei Erfolg.
        """
        if not self.sevdesk_enabled:
            return False
        async with self._voucher_lock:
            try:
                async with self._sevdesk() as sev:
                    vouchers = await sev.list_vouchers()
                deleted = self.repo.replace_vouchers(vouchers)
                self.repo.set_sevdesk_sync_success()
            except Exception as exc:
                log.exception("Abruf der SevDesk-Belege fehlgeschlagen")
                try:
                    self.repo.set_sevdesk_sync_error(f"{type(exc).__name__}: {exc}"[:500])
                except Exception:
                    log.exception("SevDesk-Abrufzustand konnte nicht gespeichert werden")
                self.repo.notify_vouchers()
                return False
            log.info(
                "SevDesk-Belege abgerufen: %s Belege, %s entfernt", len(vouchers), deleted
            )
            try:
                self.recompute_matches()
            except Exception:
                log.exception("Neuberechnung des Belegabgleichs fehlgeschlagen")
            self.repo.notify_vouchers()
            return True

    def recompute_matches(self) -> int:
        """Berechnet die automatischen Treffer aus Rechnungen und lokalem Abzug neu.

        Ohne SevDesk-Aufruf (nach dem Rechnungs-Sync, nach Nutzerentscheidungen, nach einem
        Export). Ohne bisher erfolgreichen Abruf passiert nichts — ein Teilabzug würde
        sonst „kein Treffer“ behaupten. Rechnungen, deren Treffer sich geändert haben,
        erhalten ein Ereignis (das auch deren Detailseite per SSE auffrischt). Liefert die
        Zahl dieser Rechnungen.
        """
        if self.repo.get_sevdesk_sync_state().last_success_at is None:
            return 0
        s = self.settings
        existing = self.repo.list_matches()
        matches = compute_matches(
            self.repo.list_invoices(limit=_ALL_INVOICES),
            self.repo.list_vouchers(),
            existing,
            window_days=s.sevdesk_match_window_days,
            min_score=s.sevdesk_match_min_score,
        )
        self.repo.replace_auto_matches(matches)

        def auto_pairs(items) -> set[tuple[int, str, str]]:
            return {
                (m.invoice_id, m.voucher_id, m.kind.value)
                for m in items
                if m.kind in (MatchKind.ID, MatchKind.SIMILAR)
            }

        changed = {
            pair[0]
            for pair in auto_pairs(existing) ^ auto_pairs(self.repo.list_matches())
        }
        for invoice_id in sorted(changed):
            self.repo.add_invoice_event(invoice_id, InvoiceEventType.VOUCHERS_SYNCED)
        if changed:
            self.repo.notify_vouchers()
        return len(changed)

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

    async def export_invoice(self, invoice_id: int, confirmed: bool = False) -> ExportOutcome:
        """Exportiert eine Rechnung nach SevDesk und meldet das Ergebnis als ``ExportOutcome``.

        Ablauf: Rechnung und aktuelle Treffer laden, ``export_blockers`` auswerten.
        - harte Sperre → ``blocked``, am Status ändert sich NICHTS (auch nicht bei
          ``none``/``queued``/``review``);
        - Rückfragegründe ohne ``confirmed`` → ``needs_confirmation``, nichts exportiert;
        - sonst Claim und Export wie bisher (``failed`` retrybar, ``uncertain`` nicht).
        """
        inv = self.repo.get_invoice(invoice_id)
        if inv is None:
            return ExportOutcome(ExportStatus.SKIPPED, "Rechnung nicht gefunden")
        blockers = self._blockers_for(inv)
        if blockers.hard:
            return ExportOutcome(ExportStatus.BLOCKED, blockers.hard)
        if blockers.reasons and not confirmed:
            return ExportOutcome(
                ExportStatus.NEEDS_CONFIRMATION,
                "Rückfrage nötig: " + "; ".join(blockers.reasons),
                reasons=list(blockers.reasons),
            )
        if not self.sevdesk_enabled:
            message = "SevDesk-Export ist deaktiviert"
            self.repo.set_sevdesk_status(invoice_id, SevdeskStatus.FAILED, error_message=message)
            return ExportOutcome(ExportStatus.FAILED, message)
        # Atomarer Claim: verhindert Doppel-Belege bei gleichzeitigen oder wiederholten
        # Export-Aufrufen (UI-Doppelklick, Auto-Export trifft auf manuellen Klick, Re-Sync).
        if not self.repo.claim_for_export(invoice_id):
            log.info(
                "SevDesk-Export übersprungen — Rechnung %s bereits exportiert oder in Arbeit",
                invoice_id,
            )
            return ExportOutcome(ExportStatus.SKIPPED, "bereits exportiert oder in Arbeit")
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
            return ExportOutcome(ExportStatus.FAILED, str(exc)[:200])

        # Betrag nur bei gesichertem Wert (automatisch ermittelt oder manuell bestätigt) UND
        # konfiguriertem Konto: SevDesk braucht für die Summe eine Belegposition mit Konto
        # (Design 9). Nur dann geht die Summe wirklich mit — sonst bleibt der Beleg ohne.
        account = self.settings.sevdesk_account_datev_id
        amount = (
            inv.amount
            if inv.giro_status in (GiroStatus.READY, GiroStatus.EDITED)
            else None
        )
        position_sent = amount is not None and bool(account)
        sent_amount = amount if position_sent else None

        # saveVoucher legt den Beleg an. Hier ist die Fehlerklassifizierung entscheidend:
        # - HTTPStatusError = Server hat abgelehnt → kein Beleg → retrybar (failed).
        # - alles andere (Transportfehler/Timeout, fehlende Beleg-ID in 200) = mehrdeutig,
        #   der Beleg könnte angelegt worden sein → NICHT auto-retrybar (uncertain).
        try:
            async with self._sevdesk() as sev:
                result = await sev.save_voucher_from_temp(
                    temp_name,
                    description=inv.title or filename,
                    # Pflichtangaben des Belegs: ohne sie lehnt SevDesk mit HTTP 422 ab.
                    voucher_date=inv.document_date,
                    supplier_name=inv.creditor_name or inv.correspondent,
                    currency=inv.currency,
                    amount=amount,
                    account_datev_id=account,
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
                return ExportOutcome(ExportStatus.FAILED, str(exc)[:200])
            log.warning(
                "SevDesk-Serverfehler (HTTP %s) für Rechnung %s — mehrdeutig",
                status,
                invoice_id,
            )
            self._mark_export_uncertain(invoice_id, exc)
            return ExportOutcome(ExportStatus.UNCERTAIN, str(exc)[:200])
        except Exception as exc:
            log.exception(
                "SevDesk-Export für Rechnung %s mehrdeutig fehlgeschlagen", invoice_id
            )
            self._mark_export_uncertain(invoice_id, exc)
            return ExportOutcome(ExportStatus.UNCERTAIN, str(exc)[:200])

        self.repo.set_sevdesk_status(
            invoice_id, SevdeskStatus.EXPORTED, voucher_id=result.voucher_id
        )
        self.repo.add_invoice_event(
            invoice_id, InvoiceEventType.SEVDESK_EXPORTED, f"Beleg {result.voucher_id}"
        )
        # Den neuen Beleg sofort in den Abzug übernehmen, damit der sichere Treffer ohne
        # Warten auf den nächsten Abruf da ist. Scheitert das, ist der Export trotzdem
        # gelungen — der nächste Abruf holt den Beleg dann nach.
        try:
            self.repo.upsert_voucher(
                SevdeskVoucher(
                    voucher_id=result.voucher_id,
                    voucher_date=_as_iso_date(inv.document_date),
                    supplier_name=inv.creditor_name or inv.correspondent,
                    # Mit Position führt SevDesk den Beleg mit dem gesendeten Betrag; ohne
                    # Position steht er auf 0 — dann kommt der echte Betrag erst mit dem
                    # nächsten Abruf.
                    sum_gross=sent_amount,
                    currency=inv.currency,
                    description=inv.title or filename,
                    status="50",
                )
            )
            self.recompute_matches()
            self.repo.notify_vouchers()
        except Exception:
            log.exception("Beleg %s konnte nicht in den Abzug übernommen werden", result.voucher_id)
        if self.enabled:
            try:
                await self._write_back_export(
                    invoice_id, inv.paperless_id, result.voucher_id, result.link
                )
                self.repo.mark_written_back(invoice_id)
                self.repo.add_invoice_event(invoice_id, InvoiceEventType.WRITTEN_BACK)
            except Exception as exc:
                # written_back_at bleibt leer: der nächste Sync holt den Rückschrieb nach.
                # Der Fehler steht zusätzlich als Ereignis an der Rechnung (Spec: sichtbar).
                log.exception("Rückschrieb des SevDesk-Exports fehlgeschlagen")
                self._add_event_once(
                    invoice_id, InvoiceEventType.WRITE_BACK_FAILED, _write_back_error(exc)
                )
        return ExportOutcome(
            ExportStatus.EXPORTED, f"Beleg {result.voucher_id}", voucher_id=result.voucher_id
        )

    async def export_invoices(
        self, invoice_ids: list[int]
    ) -> list[tuple[int, ExportOutcome]]:
        """Mehrfachexport: sequenziell, nur Rechnungen ohne harte Sperre und ohne Rückfragegrund.

        Alle anderen (Sperre oder Rückfragegrund) werden NICHT exportiert und kommen als
        ``skipped`` mit Grund in ``message``/``reasons`` zurück. Fehlgeschlagene und
        unklare Exporte behalten ihren Status (``failed``/``uncertain``).
        """
        results: list[tuple[int, ExportOutcome]] = []
        for invoice_id in invoice_ids:
            try:
                outcome = await self.export_invoice(invoice_id, confirmed=False)
            except Exception as exc:
                log.exception("Mehrfachexport: Rechnung %s fehlgeschlagen", invoice_id)
                outcome = ExportOutcome(ExportStatus.FAILED, str(exc)[:200])
            if outcome.status in (ExportStatus.BLOCKED, ExportStatus.NEEDS_CONFIRMATION):
                outcome = ExportOutcome(
                    ExportStatus.SKIPPED,
                    outcome.message,
                    reasons=outcome.reasons or [outcome.message],
                )
            results.append((invoice_id, outcome))
        return results

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

    async def _names(
        self, client: PaperlessClient, kind: str, need: Iterable[int] = ()
    ) -> dict[int, str]:
        """Liefert die Namensliste ``{id: name}`` der Art ``kind`` aus dem Zwischenspeicher.

        Geladen wird neu, wenn die Liste älter als ``NAME_CACHE_TTL`` ist oder eine der in
        ``need`` genannten IDs fehlt (z. B. ein Tag, der seit dem letzten Abruf neu
        entstand) — dann genau einmal je Aufruf. Bleibt eine ID auch danach unbekannt, löst
        der Aufrufer sie als ``#<id>`` auf, und ``NAME_MISS_TTL`` Sekunden lang löst diese ID
        kein weiteres Neuladen aus.
        """
        now = time.monotonic()
        entry = self._name_cache.get(kind)
        if entry is not None and now - entry[0] < NAME_CACHE_TTL:
            unknown = [
                i
                for i in need
                if i not in entry[1]
                and now - self._name_misses.get((kind, i), -NAME_MISS_TTL) >= NAME_MISS_TTL
            ]
            if not unknown:
                return entry[1]
        if kind == "field":
            # Eine Abfrage liefert Namen und Select-Optionen.
            definitions = await client.list_custom_fields()
            mapping = {
                int(f["id"]): str(f.get("name") or "")
                for f in definitions
                if f.get("id") is not None
            }
            self._field_options = _select_options_of(definitions)
        else:
            mapping = await getattr(client, _NAME_LOADERS[kind])()
        loaded = time.monotonic()
        self._name_cache[kind] = (loaded, mapping)
        for i in need:
            if i not in mapping:
                self._name_misses[(kind, i)] = loaded
        return mapping

    async def _corr_map_cached(self, client: PaperlessClient) -> dict[int, str]:
        return await self._names(client, "correspondent")

    async def load_document_view(self, paperless_id: int) -> DocumentView | None:
        """Liest ein Paperless-Dokument samt Notizen und löst alle Namen auf.

        Dokument und Notizen laufen parallel. Kennt Paperless das Dokument nicht oder gibt es
        für Lectors Zugang nicht frei (404/403), kommt ``None`` zurück; jeder andere Fehler
        (Paperless nicht erreichbar, 5xx) läuft als Ausnahme durch.
        """
        if not self.view_enabled:
            return None
        async with self._paperless() as client:
            doc_res, notes_res = await asyncio.gather(
                client.get_document(paperless_id),
                client.get_note_entries(paperless_id),
                return_exceptions=True,
            )
            if isinstance(doc_res, httpx.HTTPStatusError) and doc_res.response.status_code in (
                403,
                404,
            ):
                return None
            if isinstance(doc_res, BaseException):
                raise doc_res
            if isinstance(notes_res, BaseException):
                raise notes_res
            doc: PaperlessDocument = doc_res
            field_ids = [
                int(cf["field"]) for cf in doc.custom_fields if cf.get("field") is not None
            ]
            corr_ids = [doc.correspondent_id] if doc.correspondent_id else []
            type_ids = [doc.document_type_id] if doc.document_type_id else []
            corr, types, tags, fields, recipient_field = await asyncio.gather(
                self._names(client, "correspondent", corr_ids),
                self._names(client, "document_type", type_ids),
                self._names(client, "tag", doc.tag_ids),
                self._names(client, "field", field_ids),
                self._recipient_field_cached(client),
            )

        current_recipient = None
        values: list[CustomFieldValue] = []
        for cf in doc.custom_fields:
            if cf.get("field") is None:
                continue
            fid = int(cf["field"])
            value = cf.get("value")
            if recipient_field is not None and fid == recipient_field.field_id:
                current_recipient = recipient_field.id_to_label.get(str(value)) if value else None
                value = current_recipient
            options = self._field_options.get(fid)
            if options is not None and value not in (None, "", []):
                value = options.get(str(value), value)
            values.append(
                CustomFieldValue(
                    name=fields.get(fid) or f"#{fid}", value=_format_field_value(value)
                )
            )
        return DocumentView(
            paperless_id=doc.id,
            title=doc.title or f"#{doc.id}",
            correspondent=(
                (corr.get(doc.correspondent_id) or f"#{doc.correspondent_id}")
                if doc.correspondent_id
                else None
            ),
            document_type=(
                (types.get(doc.document_type_id) or f"#{doc.document_type_id}")
                if doc.document_type_id
                else None
            ),
            created=_parse_paperless_date(doc.created),
            added=_parse_paperless_date(doc.added),
            archive_serial_number=doc.archive_serial_number,
            page_count=doc.page_count,
            tags=[tags.get(t) or f"#{t}" for t in doc.tag_ids],
            custom_fields=values,
            notes=notes_res,
            invoice=self.repo.get_invoice_by_paperless(doc.id),
            recipient_field_present=recipient_field is not None,
            recipient_options=recipient_field.labels if recipient_field else [],
            current_recipient=current_recipient,
        )

    async def fetch_document_preview(self, paperless_id: int) -> tuple[bytes, str] | None:
        """Lädt die Vorschau eines beliebigen Paperless-Dokuments (für den UI-Proxy).

        Anders als ``fetch_preview`` ohne Rechnungs-Lookup (Design D3). ``None``, wenn die
        Anbindung fehlt oder Paperless das Dokument nicht kennt bzw. nicht freigibt.
        """
        if not self.view_enabled:
            return None
        async with self._paperless() as client:
            try:
                return await client.download_preview(paperless_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    return None
                raise

    @property
    def recipient_options(self) -> list[str]:
        return self._recipient_field.labels if self._recipient_field else []

    def recipient_option_available(self, label: str) -> bool | None:
        """Ob die Kontext-Option im Empfänger-Feld existiert — ohne Paperless-Aufruf.

        Liest nur den im Prozess gecachten Feldzustand (gefüllt vom Sync bzw. der
        Empfänger-Verwaltung). ``None`` = noch nicht aufgelöst, also unbekannt; die Übersicht
        nimmt die Option dann als vorhanden an. ``False`` nur, wenn das Feld aufgelöst ist
        und die Option sicher fehlt (oder das Feld selbst fehlt).
        """
        if not self._recipient_field_resolved:
            return None
        if self._recipient_field is None:
            return False
        return any(same_label(label, option) for option in self._recipient_field.label_to_id)

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
            # Bewusst OHNE Karte: Dies ist der Einzelvorschlag für genau EIN Dokument — die
            # vollständige Korrespondenten-Karte zu holen wäre hier teurer als der direkte
            # Einzelabruf, den _correspondent_name ohne übergebene Karte ohnehin nutzt.
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
                # Korrespondenten-Karte einmal für DIESEN Batch-Lauf holen (eigener Lauf,
                # unabhängig vom periodischen Sync — siehe sync_once). Nur bei tatsächlich
                # anstehenden Dokumenten abrufen, damit ein leerer Lauf keine unnötige
                # Anfrage auslöst.
                corr_map = await client.correspondent_map() if doc_ids else {}
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
                        if _recipient_cache_complete(cache):
                            self._progress.skipped += 1
                        else:
                            try:
                                doc = await client.get_document(doc_id)
                                correspondent = await self._correspondent_name(
                                    client, doc, corr_map
                                )
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
        **nicht** eingeplant wurden. Vollständig gecachte Dokumente (Status != ``none``
        UND ``it_probability`` vorhanden) werden übersprungen, damit ein wiederholter Lauf
        tatsächlich neue Dokumente erreicht und nicht an den ersten hängen bleibt. Alte
        Einträge ohne IT-Consulting-Einschätzung werden dagegen nachgeholt.
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
                if _recipient_cache_complete(caches.get(doc_id)):
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
                if _recipient_cache_complete(self.repo.get_recipient_cache(doc.id)):
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
                it_probability=suggestion.it_probability,
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
        self, invoice_id: int, paperless_id: int, voucher_id: str, link: str | None
    ) -> None:
        async with self._paperless() as client:
            ids = await self._resolve(client)
            await self._apply_export_write_back(
                client, ids, invoice_id, paperless_id, voucher_id, link
            )

    async def _apply_export_write_back(
        self,
        client: PaperlessClient,
        ids: dict[str, int | None],
        invoice_id: int,
        paperless_id: int,
        voucher_id: str,
        link: str | None,
        *,
        retry: bool = False,
    ) -> None:
        """Rückschrieb eines Exports, idempotent (auch für das Nachholen im Sync).

        Felder setzen und Tag hinzufügen sind wiederholbar; die Notiz entsteht nur, wenn
        noch keine Notiz „Nach SevDesk exportiert — Beleg <id>“ existiert. Der Empfänger geht
        auf die Kontext-Option; fehlt sie im Feld, werden die übrigen Felder trotzdem
        geschrieben und der Hinweis als Ereignis vermerkt.

        Beim Erstexport (``retry=False``) wird der Empfänger gesetzt — dort hat der Nutzer
        bestätigt. Im Nachholpfad (``retry=True``) liegt der Export womöglich Stunden zurück:
        das Dokument wird live gelesen und der Empfänger nur gesetzt, wenn das Feld leer ist
        oder schon der Kontext-Option entspricht. Ein anderer, inzwischen gesetzter Empfänger
        wird NICHT überschrieben (Ereignis „Hinweis“, einmalig).
        """
        values: dict[int, object] = {}
        if ids.get("cf_sevdesk_id") is not None:
            values[ids["cf_sevdesk_id"]] = voucher_id  # type: ignore[index]
        if ids.get("cf_exported_at") is not None:
            values[ids["cf_exported_at"]] = datetime.now(UTC).strftime("%Y-%m-%d")  # type: ignore[index]
        label = self.settings.sevdesk_context_label
        field = await self._recipient_field_cached(client)
        option_id = None
        if field is not None:
            option_id = next(
                (oid for lbl, oid in field.label_to_id.items() if same_label(lbl, label)), None
            )
        set_recipient = option_id is not None
        if option_id is not None and field is not None and retry:
            doc = await client.get_document(paperless_id)
            current = client.select_value(doc, field.field_id)
            if current is not None and current != option_id:
                set_recipient = False
                other = field.id_to_label.get(current, current)
                hint = (
                    f"Empfänger nicht überschrieben: am Dokument steht inzwischen „{other}“ "
                    f"(nicht „{label}“)"
                )
                log.warning("Rückschrieb Rechnung %s: %s", invoice_id, hint)
                self._add_event_once(
                    invoice_id, InvoiceEventType.WRITTEN_BACK, f"Hinweis: {hint}"
                )
        if option_id is None:
            hint = (
                f"Empfänger nicht gesetzt: Option „{label}“ fehlt im Feld "
                f"„{self.settings.cf_recipient}“ bzw. das Feld ist nicht vorhanden"
            )
            log.warning("Rückschrieb Rechnung %s: %s", invoice_id, hint)
            self._add_event_once(invoice_id, InvoiceEventType.WRITTEN_BACK, f"Hinweis: {hint}")
        elif set_recipient and field is not None:
            values[field.field_id] = option_id
        if values:
            await client.set_custom_fields(paperless_id, values)
        if set_recipient and option_id is not None:
            # Erst nach erfolgreichem Schreiben: sonst stünde lokal ein Empfänger, den
            # Paperless nicht kennt (der nächste Sync würde ihn ohnehin zurücksetzen).
            self.repo.update_invoice(invoice_id, recipient_label=label)
        if ids.get("tag_sevdesk_done") is not None:
            await client.add_tags(paperless_id, [ids["tag_sevdesk_done"]])  # type: ignore[list-item]
        prefix = f"Nach SevDesk exportiert — Beleg {voucher_id}"
        existing = await client.get_notes(paperless_id)
        # Wortgrenze: Beleg „12“ darf nicht durch eine Notiz zu Beleg „123“ als vorhanden gelten.
        pattern = re.compile(re.escape(prefix) + r"(?!\w)")
        if not any(pattern.search(n) for n in existing):
            note = prefix
            if link:
                note += f" ({link})"
            await client.add_note(paperless_id, note)

    async def _retry_write_backs(
        self, client: PaperlessClient, ids: dict[str, int | None]
    ) -> None:
        """Holt Rückschriebe nach, die beim Export scheiterten (``written_back_at`` leer)."""
        for inv in self.repo.list_invoices(
            sevdesk_status=SevdeskStatus.EXPORTED, limit=_ALL_INVOICES
        ):
            if inv.written_back_at is not None or not inv.sevdesk_voucher_id:
                continue
            try:
                await self._apply_export_write_back(
                    client, ids, inv.id, inv.paperless_id, inv.sevdesk_voucher_id, None,
                    retry=True,
                )  # fmt: skip
                self.repo.mark_written_back(inv.id)
                self.repo.add_invoice_event(
                    inv.id, InvoiceEventType.WRITTEN_BACK, "Rückschrieb nachgeholt"
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    log.exception(
                        "Nachholen des Rückschriebs für Rechnung %s fehlgeschlagen", inv.id
                    )
                    self._add_event_once(
                        inv.id, InvoiceEventType.WRITE_BACK_FAILED, _write_back_error(exc)
                    )
                    continue
                # Dokument in Paperless gelöscht: es gibt nichts mehr zurückzuschreiben und
                # ein erneuter Versuch würde jeden Lauf wieder mit 404 scheitern. Deshalb
                # als erledigt markieren (written_back_at) und einmalig vermerken.
                log.warning(
                    "Rückschrieb Rechnung %s: Dokument %s in Paperless nicht mehr vorhanden",
                    inv.id,
                    inv.paperless_id,
                )
                self.repo.mark_written_back(inv.id)
                self._add_event_once(
                    inv.id,
                    InvoiceEventType.WRITTEN_BACK,
                    "Hinweis: Dokument in Paperless nicht mehr vorhanden — "
                    "Rückschrieb entfällt",
                )
            except Exception as exc:
                log.exception("Nachholen des Rückschriebs für Rechnung %s fehlgeschlagen", inv.id)
                self._add_event_once(
                    inv.id, InvoiceEventType.WRITE_BACK_FAILED, _write_back_error(exc)
                )
