from app.girocode import (
    PaymentData,
    epc_payload,
    extract_from_einvoice_xml,
    extract_from_ocr_text,
    qr_svg,
    valid_iban,
)

# Gültige Beispiel-IBAN (ISO-13616-konform).
IBAN = "DE89370400440532013000"

UBL_INVOICE = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>RE-2024-001</cbc:ID>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyLegalEntity>
      <cbc:RegistrationName>Muster GmbH</cbc:RegistrationName>
    </cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:PaymentMeans>
    <cac:PayeeFinancialAccount>
      <cbc:ID>{IBAN}</cbc:ID>
      <cac:FinancialInstitutionBranch><cbc:ID>COBADEFFXXX</cbc:ID></cac:FinancialInstitutionBranch>
    </cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""

CII_INVOICE = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
  <rsm:ExchangedDocument><ram:ID>CII-77</ram:ID></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Verkauf AG</ram:Name></ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{IBAN}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>
        <ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>MARKDEF1100</ram:BICID></ram:PayeeSpecifiedCreditorFinancialInstitution>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:DuePayableAmount>250.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


def test_valid_iban():
    assert valid_iban(IBAN)
    assert valid_iban("DE89 3704 0044 0532 0130 00")  # mit Leerzeichen
    assert not valid_iban("DE00370400440532013000")   # falsche Prüfziffer
    assert not valid_iban("foobar")
    assert not valid_iban(None)


def test_extract_from_ubl():
    data = extract_from_einvoice_xml(UBL_INVOICE.encode("utf-8"))
    assert data is not None
    assert data.iban == IBAN
    assert data.bic == "COBADEFFXXX"
    assert data.amount == 119.00
    assert data.currency == "EUR"
    assert data.creditor_name == "Muster GmbH"
    assert data.purpose == "RE-2024-001"


def test_extract_from_cii():
    data = extract_from_einvoice_xml(CII_INVOICE.encode("utf-8"))
    assert data is not None
    assert data.iban == IBAN
    assert data.bic == "MARKDEF1100"
    assert data.amount == 250.00
    assert data.creditor_name == "Verkauf AG"
    assert data.purpose == "CII-77"


def test_extract_from_ocr_text():
    text = "Rechnung Nr 5\nIBAN: DE89 3704 0044 0532 0130 00\nZahlbetrag: 1.234,56 EUR\n"
    data = extract_from_ocr_text(text, fallback_creditor="Scan Lieferant")
    assert data.iban == IBAN
    assert data.amount == 1234.56
    assert data.creditor_name == "Scan Lieferant"


def test_extract_from_garbage_xml():
    assert extract_from_einvoice_xml(b"<<not xml") is None


def test_epc_payload_structure():
    data = PaymentData(
        creditor_name="Muster GmbH", iban=IBAN, bic="COBADEFFXXX",
        amount=119.0, currency="EUR", purpose="RE-2024-001",
    )
    payload = epc_payload(data)
    lines = payload.split("\n")
    assert lines[0] == "BCD"
    assert lines[1] == "002"
    assert lines[3] == "SCT"
    assert lines[5] == "Muster GmbH"
    assert lines[6] == IBAN
    assert lines[7] == "EUR119.00"
    assert lines[-1] == "RE-2024-001"


def test_epc_payload_requires_iban():
    import pytest

    with pytest.raises(ValueError):
        epc_payload(PaymentData(creditor_name="X", iban=None))


def test_qr_svg_renders():
    data = PaymentData(creditor_name="Muster GmbH", iban=IBAN, amount=10.0)
    svg = qr_svg(data)
    assert "<svg" in svg


def test_is_payable():
    assert PaymentData(creditor_name="A", iban=IBAN).is_payable
    assert not PaymentData(creditor_name="A", iban="DE00370400440532013000").is_payable
    assert not PaymentData(creditor_name=None, iban=IBAN).is_payable
