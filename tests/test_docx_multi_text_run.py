"""R3-B1: a <w:r> holding MORE THAN ONE text-bearing child.

WHY NO EXISTING TEST COULD HAVE CAUGHT THIS
--------------------------------------------------------------------------------------
Every document this project measures on is built by ``corpus/docx_builder.py``, which uses
python-docx — and python-docx emits exactly ONE ``<w:t>`` per ``<w:r>``. So the shape below
cannot occur anywhere in the 70-document corpus, and the leak gate, the mutation gate, the
cross-format gate and every test in ``tests/`` were all blind to it, not because they are
weak but because the population they run over does not contain the shape.

Word produces it constantly. A Shift+Enter inside a formatting run is a ``<w:br/>``; a tab is
``<w:tab/>``; and ``<w:lastRenderedPageBreak/>`` is inserted mid-run by Word on every save.
A real ``.docx`` has several on its first page.

WHAT WENT WRONG
``_rebuild_run`` deep-copied the whole ``<w:r>`` and then set the text of its FIRST ``<w:t>``.
Every other text-bearing child came along in the copy with its ORIGINAL TEXT — and the copy is
made once per fragment, so the PII did not merely survive the redaction, it was DUPLICATED,
appearing several times beside the label claiming to have removed it.

The fixtures are built by hand with lxml, because the tool that builds the corpus is exactly
the tool that cannot produce this shape.
"""
import os
import tempfile

import pytest
from docx import Document
from docx.oxml.ns import qn

from writer.docx_body import redact_docx_body

NAME = "Mária Kováčová"
RC = "850315/0018"


def _run_with_children(paragraph, pieces):
    """Append ONE <w:r> whose children are ``pieces``: ('t', text) | ('br',) | ('tab',)."""
    run = paragraph.add_run()
    r = run._r
    for t in list(r):
        if t.tag == qn("w:t"):
            r.remove(t)
    for piece in pieces:
        if piece[0] == "t":
            el = r.makeelement(qn("w:t"), {})
            el.text = piece[1]
            el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        elif piece[0] == "br":
            el = r.makeelement(qn("w:br"), {})
        else:
            el = r.makeelement(qn("w:tab"), {})
        r.append(el)
    return run


def _build(path, pieces):
    doc = Document()
    _run_with_children(doc.add_paragraph(), pieces)
    doc.save(path)


def _redact(pieces):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.docx")
        out = os.path.join(tmp, "out.docx")
        _build(src, pieces)
        redact_docx_body(src, out, known_entities=[NAME])
        doc = Document(out)
        return "\n".join(p.text for p in doc.paragraphs)


def test_the_fixture_really_produces_a_multi_text_run():
    """The control. If python-docx quietly collapsed these into one <w:t>, every assertion
    below would pass while testing nothing — which is precisely how this shape stayed
    invisible for the whole project."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.docx")
        _build(src, [("t", "Predávajúci: "), ("br",), ("t", NAME)])
        doc = Document(src)
        r = doc.paragraphs[0].runs[0]._r
        assert len(r.findall(qn("w:t"))) == 2, "fixture did not produce two w:t in one run"


@pytest.mark.parametrize("pieces", [
    [("t", "Predávajúci: "), ("br",), ("t", NAME)],
    [("t", NAME), ("br",), ("t", " a ďalší")],
    [("t", "Meno a priezvisko:"), ("tab",), ("t", NAME)],
    [("t", "A "), ("t", NAME), ("t", " B")],
    [("t", "Rodné číslo:"), ("tab",), ("t", RC)],
])
def test_pii_in_a_multi_text_run_is_removed_and_not_duplicated(pieces):
    text = _redact(pieces)
    secret = NAME if any(p[1:] == (NAME,) for p in pieces if p[0] == "t") else RC
    assert secret not in text, f"PII survived in a multi-child run: {text!r}"
    # The duplication half. Before the fix the name came back several times BESIDE the label,
    # so asserting only on the label would have passed on a leaking document.
    assert text.count(secret) == 0


def test_surviving_text_in_the_run_is_kept_exactly_once():
    """The other half of the contract: the fix must not eat the run's non-PII text, and must
    not repeat it either — every fragment is a copy of the same run."""
    text = _redact([("t", "Predávajúci: "), ("br",), ("t", NAME), ("t", " súhlasí.")])
    assert text.count("Predávajúci:") == 1
    assert text.count("súhlasí.") == 1


def test_a_tab_stays_a_tab_and_a_break_stays_a_break():
    """A rebuilt run re-emits <w:tab/> and <w:br/> as ELEMENTS rather than writing "\\t" and
    "\\n" into a <w:t>. XML whitespace normalisation would turn the newline into a space, so
    the document would quietly lose a line break wherever a redaction touched one."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.docx")
        out = os.path.join(tmp, "out.docx")
        _build(src, [("t", "Meno:"), ("tab",), ("t", NAME), ("br",), ("t", "ďalej")])
        redact_docx_body(src, out, known_entities=[NAME])
        r_elems = Document(out).paragraphs[0]._p.findall(qn("w:r"))
        tags = [child.tag for r in r_elems for child in r]
        assert qn("w:tab") in tags, "the tab was flattened into text"
        assert qn("w:br") in tags, "the line break was flattened into text"
