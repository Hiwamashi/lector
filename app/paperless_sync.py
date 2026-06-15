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
from .models import GiroStatus, InvoiceEventType, SevdeskStatus
from .paperless import (
    CF_TYPE_BOOLEAN,
    CF_TYPE_DATE,
    CF_TYPE_STRING,
    PaperlessClient,
    PaperlessDocument,
)
from .repository import Repository
from .sevdesk import SevdeskClient

log = logging.getLogger("lector.paperless_sync")


class PaperlessSync:
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self._ids: dict[str, int | None] | None = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(s.feature_paperless_sync and s.paperless_url and s.paperless_token)

    @property
    def sevdesk_enabled(self) -> bool:
        s = self.settings
        return bool(s.feature_sevdesk_export and s.sevdesk_api_token)

    def _paperless(self) -> PaperlessClient:
        return PaperlessClient(self.settings.paperless_url, self.settings.paperless_token)

    def _sevdesk(self) -> SevdeskClient:
        return SevdeskClient(self.settings.sevdesk_base_url, self.settings.sevdesk_api_token)

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
            invoice_id = self.repo.upsert_invoice(
                paperless_id=doc.id,
                title=doc.title,
                correspondent=await self._correspondent_name(client, doc),
            )
            self.repo.add_invoice_event(invoice_id, InvoiceEventType.SYNCED)
            existing = self.repo.get_invoice(invoice_id)
            if existing and existing.giro_status == GiroStatus.NONE:
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
