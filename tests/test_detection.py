import pikepdf
from reportlab.pdfgen import canvas

from app.detection import detect, is_supported
from app.models import DocType

UBL_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>123</ID>
</Invoice>"""

CII_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
  <rsm:ExchangedDocument/>
</rsm:CrossIndustryInvoice>"""

PLAIN_XML = """<?xml version="1.0"?><note><body>hello</body></note>"""


def _make_pdf(path, text="Seite 1"):
    c = canvas.Canvas(str(path))
    c.drawString(100, 700, text)
    c.showPage()
    c.save()


def test_xrechnung_ubl(tmp_path):
    p = tmp_path / "rechnung.xml"
    p.write_text(UBL_INVOICE, encoding="utf-8")
    d = detect(p)
    assert d.doc_type == DocType.ERECHNUNG_XML
    assert d.is_erechnung is True


def test_xrechnung_cii(tmp_path):
    p = tmp_path / "rechnung.xml"
    p.write_text(CII_INVOICE, encoding="utf-8")
    assert detect(p).is_erechnung is True


def test_plain_xml_not_erechnung(tmp_path):
    p = tmp_path / "note.xml"
    p.write_text(PLAIN_XML, encoding="utf-8")
    assert detect(p).is_erechnung is False


def test_plain_pdf(tmp_path):
    p = tmp_path / "scan.pdf"
    _make_pdf(p)
    d = detect(p)
    assert d.doc_type == DocType.PDF
    assert d.is_erechnung is False


def test_zugferd_pdf_with_embedded_xml(tmp_path):
    base = tmp_path / "base.pdf"
    _make_pdf(base)
    out = tmp_path / "zugferd.pdf"
    with pikepdf.open(base) as pdf:
        fs = pikepdf.AttachedFileSpec(pdf, CII_INVOICE.encode("utf-8"), mime_type="text/xml")
        pdf.attachments["factur-x.xml"] = fs
        pdf.save(out)
    d = detect(out)
    assert d.doc_type == DocType.ERECHNUNG_PDF
    assert d.is_erechnung is True


def test_image_and_tiff(tmp_path):
    assert detect(tmp_path / "foto.jpg").doc_type == DocType.IMAGE
    assert detect(tmp_path / "scan.tiff").doc_type == DocType.TIFF


def test_is_supported():
    assert is_supported(tmp_path_like("a.pdf"))
    assert is_supported(tmp_path_like("a.PNG"))
    assert not is_supported(tmp_path_like("a.docx"))


def tmp_path_like(name):
    from pathlib import Path

    return Path(name)
