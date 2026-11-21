"""A field code's ARGUMENT is sometimes a hyperlink destination and usually is not.

Word has three spellings for a hyperlink and two of them are FIELD CODES, which carry the
destination inside the field instruction rather than in a ``.rels`` part:

    <w:fldSimple w:instr=' HYPERLINK "mailto:jan.novak@advokat.sk" '>
    <w:r><w:instrText> HYPERLINK "mailto:jan.novak@advokat.sk" </w:instrText></w:r>

Neither goes through ``.rels``, so ``_scrub_rel_targets`` never saw them, and ``w:instrText``
is not text ``Run.text`` renders, so ``detect()`` never saw them either (red-team round 4,
R4-T4 / R4-T5). Both are scrubbed now.

WHY THIS FILE EXISTS SEPARATELY. The first version of that scrub ran the destination predicate
over the arguments of EVERY field, and a Word auto-bookmark (``_Ref``/``_Toc`` + eight or nine
digits) has the IČO shape half the time:

    REF _Ref53871234 \\h      ->  REF https://removed.invalid/ \\h
    PAGEREF _Toc12345678 \\h  ->  PAGEREF https://removed.invalid/ \\h

That breaks the cross-references and the table of contents of an ordinary filing, on a coin
flip of the digit count. It is the same category error that destroyed the slov-lex links
twice: a predicate about a URI destination applied to something that is not a destination.
``tests/test_docx_hyperlink_target.py`` is what stopped that happening again with links; this
file is its counterpart for fields, and the survival list below is the point of it.
"""
import zipfile

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn

from detect.config import DEFAULT
from writer.docx_body import _scrub_field_instruction, redact_docx_body

NAME = "Ján Novák"
KNOWN = [NAME, "Mária Kováčová"]

# Ordinary fields in a Slovak filing. Every one of these MUST come back byte-identical: a
# bookmark name, a sequence label, a style name, a date picture and a switch are not
# destinations, and rewriting one breaks the document rather than redacting it.
FIELDS_THAT_MUST_SURVIVE = [
    r"REF _Ref123456789 \r \h",          # 9-digit bookmark -- survived even the blanket rule
    r"REF _Ref53871234 \h",              # 8-digit bookmark -- read as an ICO, was DESTROYED
    r"NOTEREF _Ref99887766 \h",
    r"PAGEREF _Toc12345678 \h",
    r'TOC \o "1-3" \h \z \u',
    r"SEQ Tabulka \* ARABIC",
    r'DATE \@ "d.M.yyyy"',
    r"PAGE \* MERGEFORMAT",
    r"NUMPAGES \* MERGEFORMAT",
    r'STYLEREF "Nadpis 1" \* MERGEFORMAT',
    r'IF 1 = 1 "Predavajuci" "Kupujuci"',
    r"FILENAME \p",
    r"SECTION",
    r"LISTNUM \l 1",
    # A HYPERLINK to the statute book is a listed field and IS examined -- and must still come
    # back unchanged, because it carries no personal data. This is the link half of the same
    # promise, inside a field.
    r'HYPERLINK "https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/2016/18/20180101"',
    r'HYPERLINK "https://www.justice.gov.sk/Stranky/Sudy/Zoznam-sudov.aspx"',
]

FIELDS_THAT_MUST_BE_SCRUBBED = [
    r'HYPERLINK "mailto:jan.novak@advokat.sk"',
    r'HYPERLINK "file:///C:/Users/jan.novak/Documents/zmluva.docx"',
    r'HYPERLINK "tel:+421905123456"',
    r'HYPERLINK "https://dms.firma.sk/klienti/Jan%20Novak/zmluva.pdf"',
    r'INCLUDETEXT "\\\\fileserver\\users\\jan.novak\\matter\\zmluva.docx"',
]


@pytest.mark.parametrize("instr", FIELDS_THAT_MUST_SURVIVE)
def test_an_ordinary_field_instruction_is_not_touched(instr):
    assert _scrub_field_instruction(instr, KNOWN, DEFAULT) is None, (
        f"the scrub would damage an ordinary Word field: {instr}"
    )


@pytest.mark.parametrize("instr", FIELDS_THAT_MUST_BE_SCRUBBED)
def test_a_field_argument_carrying_personal_data_is_scrubbed(instr):
    """The other side of the same narrowing: restricting the rule must not blind it."""
    out = _scrub_field_instruction(instr, KNOWN, DEFAULT)
    assert out is not None, f"a PII-bearing field argument survived: {instr}"
    assert "removed.invalid" in out
    assert out.split(None, 1)[0] == instr.split(None, 1)[0], "the field type was rewritten"


def test_an_unlisted_field_is_left_alone_even_when_its_argument_looks_like_pii():
    """The recall cost of the whitelist, pinned so it is visible rather than assumed.

    An unlisted field's argument is NOT scrubbed. That is a deliberate trade and it is safe in
    both directions that matter: the instruction is word/document.xml bytes, which the leak
    gate grades as a strict surface, and the field's displayed result is a separate run that
    detect() reads on the page. The alternative -- examining every field -- is certain damage
    to the cross-references of an ordinary filing."""
    assert _scrub_field_instruction(r"REF _Ref53871234 \h", KNOWN, DEFAULT) is None


def test_the_field_type_itself_is_never_rewritten():
    """AUTHOR is a listed field with no arguments at all. The first token is the field type and
    must survive even when it would match something on its own."""
    assert _scrub_field_instruction("AUTHOR", KNOWN, DEFAULT) is None
    assert _scrub_field_instruction(r"PAGE \* MERGEFORMAT", KNOWN, DEFAULT) is None


NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ')


def _doc_with_fields(path, instrs):
    """A document carrying one <w:fldSimple> per instruction. python-docx cannot emit a field,
    so the paragraphs are built as raw OOXML and grafted into the body."""
    d = Document()
    body = d.element.body
    sect = body.find(qn("w:sectPr"))
    for instr in instrs:
        frag = (f'<w:p {NS}><w:fldSimple w:instr="{instr}">'
                '<w:r><w:t xml:space="preserve">vysledok pola</w:t></w:r></w:fldSimple></w:p>')
        sect.addprevious(parse_xml(frag))
    d.save(str(path))
    return str(path)


def test_end_to_end_a_document_of_ordinary_fields_comes_back_intact(tmp_path):
    """The unit tests above are on the predicate; this is the document. A filing with a table
    of contents, cross-references and page numbers must round-trip through the writer with
    every field instruction byte-identical."""
    instrs = [i.replace("\\", "\\").replace('"', "&quot;")
              for i in FIELDS_THAT_MUST_SURVIVE]
    src = _doc_with_fields(tmp_path / "fields.docx", instrs)
    out = str(tmp_path / "fields_r.docx")
    redact_docx_body(src, out, known_entities=KNOWN)

    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert "removed.invalid" not in xml, "an ordinary field was rewritten"
    for instr in ("_Ref53871234", "_Toc12345678", "_Ref99887766", "Nadpis 1", "d.M.yyyy"):
        assert instr in xml, f"{instr} was lost from the document"
    assert Document(out).element.body is not None


def test_end_to_end_a_hyperlink_field_is_still_scrubbed(tmp_path):
    src = _doc_with_fields(
        tmp_path / "link.docx",
        ["HYPERLINK &quot;mailto:jan.novak@advokat.sk&quot;",
         "HYPERLINK &quot;https://www.slov-lex.sk/&quot;"])
    out = str(tmp_path / "link_r.docx")
    redact_docx_body(src, out, known_entities=KNOWN)

    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert "jan.novak@advokat.sk" not in xml
    assert "removed.invalid" in xml
    assert "https://www.slov-lex.sk/" in xml, "a working link to the statute book was destroyed"
