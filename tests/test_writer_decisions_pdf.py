"""Phase 6 Task 3: RedactionDecisions threaded through the PDF writer.

PDF counterpart of the DOCX decision-plumbing tests: hand-built fitz fixtures, the real
writer, and the (type, group_key) decision keys resolved via LabelMap.group_key_for.
"""
import fitz

from writer.pdf_body import redact_pdf, redact_pdf_collect


def _mk_pdf(tmp_path, text):
    p = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(p))
    doc.close()
    return str(p)


def _pdf_text(path):
    doc = fitz.open(path)
    t = "\n".join(pg.get_text("text") for pg in doc)
    doc.close()
    return t


def test_pdf_suppress_keeps_surface_in_output(tmp_path):
    src = _mk_pdf(tmp_path, "Konatel Jan Novak, DIC 2023456789, uhradi sumu.")
    out_plain = str(tmp_path / "plain.pdf")
    lm = redact_pdf_collect(src, out_plain, known_entities=["Jan Novak"])
    assert "2023456789" not in _pdf_text(out_plain)
    key = ("DIC", lm.group_key_for("DIC", "2023456789"))
    out = str(tmp_path / "sup.pdf")
    from writer.decisions import RedactionDecisions
    redact_pdf(src, out, known_entities=["Jan Novak"],
               decisions=RedactionDecisions(suppress_groups=frozenset({key})))
    txt = _pdf_text(out)
    assert "2023456789" in txt
    assert "Novak" not in txt


def test_pdf_force_redacts_low_confidence_group(tmp_path):
    src = _mk_pdf(tmp_path, "rodne cislo: 835112/0009")
    out_plain = str(tmp_path / "plain.pdf")
    lm = redact_pdf_collect(src, out_plain, known_entities=None)
    assert "835112/0009" in _pdf_text(out_plain)
    key = ("RODNE_CISLO", lm.group_key_for("RODNE_CISLO", "835112/0009"))
    out = str(tmp_path / "forced.pdf")
    from writer.decisions import RedactionDecisions
    redact_pdf(src, out, known_entities=None,
               decisions=RedactionDecisions(force_groups=frozenset({key})))
    assert "835112/0009" not in _pdf_text(out)


def test_pdf_decisions_none_is_default_behaviour(tmp_path):
    src = _mk_pdf(tmp_path, "Konatel Jan Novak, DIC 2023456789.")
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    redact_pdf(src, a, known_entities=["Jan Novak"])
    redact_pdf(src, b, known_entities=["Jan Novak"], decisions=None)
    assert _pdf_text(a) == _pdf_text(b)
