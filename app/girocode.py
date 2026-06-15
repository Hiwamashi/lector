"""GiroCode (EPC069-12) — Zahldaten aus Rechnungen gewinnen und als QR-Code rendern.

Dieses Modul ist bewusst engine-unabhängig und ohne Netzwerk/IO testbar:

- ``extract_from_einvoice_xml`` liest IBAN/Betrag/BIC/Empfänger **deterministisch** aus
  XRechnung (UBL) bzw. ZUGFeRD/Factur-X (UN/CEFACT CII) — passend zum „keine KI-Raterei"-
  Prinzip von Lector.
- ``extract_from_ocr_text`` ist die heuristische Notlösung für eingescannte Papierrechnungen
  (IBAN per Regex + Mod-97-Prüfung, Betrag per Schlüsselwort-Nähe, Gläubiger als Fallback aus
  dem Paperless-Korrespondenten).
- ``epc_payload`` / ``qr_svg`` bauen den standardisierten GiroCode-Payload und das SVG.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import segno

# Schlüsselwörter, in deren Nähe der Zahlbetrag auf Papierrechnungen steht.
_AMOUNT_KEYWORDS = (
    "zahlbetrag",
    "gesamtbetrag",
    "rechnungsbetrag",
    "gesamt brutto",
    "gesamtsumme",
    "summe",
    "total",
    "betrag",
)

# Geldbetrag im deutschen Format: 1.234,56 oder 1234,56 oder 1234.56
_AMOUNT_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*|\d+)[,.](\d{2})\b")
# IBAN-Kandidat (kann Leerzeichen in 4er-Gruppen enthalten).
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){11,30})\b")


@dataclass
class PaymentData:
    creditor_name: str | None = None
    iban: str | None = None
    bic: str | None = None
    amount: float | None = None
    currency: str = "EUR"
    purpose: str | None = None

    @property
    def is_payable(self) -> bool:
        """Genügend Daten für einen sinnvollen GiroCode (Name + gültige IBAN)."""
        return bool(self.creditor_name) and valid_iban(self.iban)


def normalize_iban(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", "", value).upper()


def valid_iban(value: str | None) -> bool:
    """Formale IBAN-Prüfung nach ISO 13616 (Länge + Mod-97-Prüfziffer)."""
    iban = normalize_iban(value)
    if not iban or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


# ---------------------------------------------------------------------------
# E-Rechnung (deterministisch)
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    name = name.lower()
    for elem in root.iter():
        if _local(elem.tag) == name:
            return elem
    return None


def _find_within(root: ET.Element, parent: str, child: str) -> ET.Element | None:
    parent, child = parent.lower(), child.lower()
    for p in root.iter():
        if _local(p.tag) == parent:
            for c in p.iter():
                if c is not p and _local(c.tag) == child:
                    return c
    return None


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    value = elem.text.strip()
    return value or None


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return round(float(value.strip()), 2)
    except ValueError:
        return None


def extract_from_einvoice_xml(data: bytes) -> PaymentData | None:
    """Liest Zahldaten aus XRechnung (UBL) oder ZUGFeRD/Factur-X (CII).

    Gibt ``None`` zurück, wenn das XML nicht geparst werden kann.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    iban = _text(_find_first(root, "ibanid")) or _text(
        _find_within(root, "payeefinancialaccount", "id")
    )
    bic = _text(_find_first(root, "bicid")) or _text(
        _find_within(root, "financialinstitutionbranch", "id")
    )
    # Hinweis: ET-Elemente ohne Kinder sind "falsy", daher kein ``or``-Chaining.
    amount_el = _find_first(root, "duepayableamount")
    if amount_el is None:
        amount_el = _find_first(root, "payableamount")
    if amount_el is None:
        amount_el = _find_first(root, "grandtotalamount")
    amount = _parse_amount(_text(amount_el))

    # Gläubiger/Empfänger: Verkäufer-Partei.
    creditor = _text(_find_within(root, "sellertradeparty", "name"))
    if not creditor:
        creditor = _text(_find_within(root, "accountingsupplierparty", "registrationname"))
    if not creditor:
        creditor = _text(_find_within(root, "accountingsupplierparty", "name"))

    # Verwendungszweck: Zahlungsreferenz bzw. Rechnungsnummer.
    purpose = _text(_find_first(root, "paymentreference"))
    if not purpose:
        # Rechnungsnummer: erstes ID-Element direkt im Beleg-Kopf.
        head = _find_first(root, "exchangeddocument")
        if head is not None:
            purpose = _text(_find_within(head, "exchangeddocument", "id"))
        if not purpose:
            top_id = _find_first(root, "id")
            purpose = _text(top_id)

    currency = "EUR"
    if amount_el is not None:
        currency = amount_el.get("currencyID") or amount_el.get("currencyId") or "EUR"

    return PaymentData(
        creditor_name=creditor,
        iban=normalize_iban(iban),
        bic=(bic.strip() if bic else None),
        amount=amount,
        currency=currency,
        purpose=purpose,
    )


# ---------------------------------------------------------------------------
# OCR-Text (heuristisch)
# ---------------------------------------------------------------------------

def _amount_from_text(text: str) -> float | None:
    """Sucht den Zahlbetrag bevorzugt in der Nähe typischer Schlüsselwörter."""
    lowered = text.lower()
    best: float | None = None
    for keyword in _AMOUNT_KEYWORDS:
        start = lowered.find(keyword)
        if start == -1:
            continue
        window = text[start : start + 80]
        match = _AMOUNT_RE.search(window)
        if match:
            value = float(f"{match.group(1).replace('.', '').replace(' ', '')}.{match.group(2)}")
            # Größter plausibler Treffer in Schlüsselwort-Nähe gewinnt.
            if best is None or value > best:
                best = value
    return best


def extract_from_ocr_text(text: str, *, fallback_creditor: str | None = None) -> PaymentData:
    """Heuristische Extraktion aus OCR-Text. Liefert immer ein (ggf. unvollständiges) Objekt."""
    iban: str | None = None
    for candidate in _IBAN_RE.findall(text):
        normalized = normalize_iban(candidate)
        if valid_iban(normalized):
            iban = normalized
            break

    return PaymentData(
        creditor_name=fallback_creditor,
        iban=iban,
        bic=None,
        amount=_amount_from_text(text),
        currency="EUR",
        purpose=None,
    )


# ---------------------------------------------------------------------------
# EPC069-12-Payload + QR
# ---------------------------------------------------------------------------

def epc_payload(data: PaymentData) -> str:
    """Baut den EPC069-12-Payload (Version 002, UTF-8) für SEPA-Überweisungen.

    Erwartet gültige Pflichtdaten (Name + IBAN). Betrag/Verwendungszweck sind optional.
    """
    iban = normalize_iban(data.iban)
    if not data.creditor_name or not valid_iban(iban):
        raise ValueError("GiroCode benötigt Empfängername und gültige IBAN")

    name = data.creditor_name.strip()[:70]
    amount_line = ""
    if data.amount is not None and 0.01 <= data.amount <= 999_999_999.99:
        amount_line = f"{data.currency or 'EUR'}{data.amount:.2f}"
    remittance = (data.purpose or "").strip()[:140]

    lines = [
        "BCD",
        "002",
        "1",
        "SCT",
        (data.bic or "").strip(),
        name,
        iban or "",
        amount_line,
        "",          # Purpose-Code (optional, leer)
        "",          # strukturierte Referenz (optional, leer)
        remittance,  # unstrukturierter Verwendungszweck
    ]
    # EPC erlaubt das Weglassen leerer Endfelder.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def qr_svg(data: PaymentData, *, scale: int = 4) -> str:
    """Rendert den GiroCode als eigenständiges SVG (für Inline-Einbettung im HTML)."""
    import io

    qr = segno.make(epc_payload(data), error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True)
    return buffer.getvalue().decode("utf-8")
