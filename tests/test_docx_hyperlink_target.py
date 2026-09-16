"""A hyperlink's DESTINATION is PII too, and it does not live in the paragraph.

Word stores a hyperlink target in a ``.rels`` part, not in ``document.xml``. Redacting the
display text therefore does nothing to it — and the result is the worst shape a redaction can
take: the document READS ``Kontakt: [EMAIL_1]`` while the package still contains
``mailto:jan.novak@advokat.sk``. Anyone who unzips the .docx, and any tool that follows the
link, gets the address back out of a file that looks finished.

This is not an exotic shape. Word auto-hyperlinks every e-mail address and URL the moment you
type one and press space, so a real contract with a contact line has one.

The fixtures are hand-built with lxml because ``corpus/docx_builder.py`` (python-docx) cannot
emit a hyperlink at all, which is why no corpus document has ever contained one and no gate
in this repo could have caught this.
"""
import os
import tempfile
import zipfile

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

from writer.docx_body import redact_docx_body

EMAIL = "jan.novak@advokat.sk"
NAME = "Ján Novák"


def _with_hyperlink(path, target: str, display: str) -> None:
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Kontakt: ")
    rel_id = p.part.relate_to(target, RT.HYPERLINK, is_external=True)
    link = p._p.makeelement(qn("w:hyperlink"), {qn("r:id"): rel_id})
    run = p._p.makeelement(qn("w:r"), {})
    t = run.makeelement(qn("w:t"), {})
    t.text = display
    run.append(t)
    link.append(run)
    p._p.append(link)
    doc.save(path)


def _redact(target: str, display: str):
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "in.docx")
    out = os.path.join(tmp, "out.docx")
    _with_hyperlink(src, target, display)
    redact_docx_body(src, out, known_entities=[NAME])
    visible = "\n".join(p.text for p in Document(out).paragraphs)
    with zipfile.ZipFile(out) as z:
        rels = "\n".join(
            z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".rels")
        )
    return visible, rels


def test_the_display_text_is_redacted():
    visible, _ = _redact(f"mailto:{EMAIL}", EMAIL)
    assert EMAIL not in visible
    assert "[EMAIL_1]" in visible


def test_the_mailto_TARGET_is_scrubbed_too():
    """The half that made the document a liability: visible text clean, package not."""
    _, rels = _redact(f"mailto:{EMAIL}", EMAIL)
    assert EMAIL not in rels


def test_a_target_carrying_a_NAME_is_scrubbed_even_when_the_display_text_does_not():
    """The display text is the reader's view and the target is the machine's. They can carry
    different PII — 'kliknite sem' linking to a URL with the client's name in the path is the
    ordinary case — so the target is examined on its own, not inferred from the text."""
    _, rels = _redact("https://example.com/klienti/Jan-Novak/zmluva.pdf", "kliknite sem")
    assert "Jan-Novak" not in rels


def test_a_percent_encoded_target_is_scrubbed():
    """Word percent-encodes what it stores. 'Jan%20Novak' has to be detectable as 'Jan Novak'
    or the scrub misses exactly the names it exists for."""
    _, rels = _redact("https://example.com/k/Jan%20Novak/zmluva.pdf", "zmluva")
    assert "Jan%20Novak" not in rels
    assert "Jan Novak" not in rels


def test_an_innocuous_target_is_left_alone():
    """The quiet half. Scrubbing every hyperlink would break the document's real links, and a
    tool that mangles working links gets switched off."""
    _, rels = _redact("https://www.slov-lex.sk/", "Zbierka zákonov")
    assert "slov-lex.sk" in rels


def test_an_internal_relationship_is_never_touched():
    """Only EXTERNAL targets are URLs. An internal target is a path inside the package, and
    rewriting one would corrupt the file."""
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "in.docx")
    out = os.path.join(tmp, "out.docx")
    doc = Document()
    doc.add_paragraph(f"Predávajúci: {NAME}")
    doc.save(src)
    redact_docx_body(src, out, known_entities=[NAME])
    with zipfile.ZipFile(out) as z:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "styles.xml" in rels, "an internal relationship was damaged"
    # and the file still opens
    assert Document(out).paragraphs
