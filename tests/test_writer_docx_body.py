"""W1 unit tests (context.md §10): redact PII in DOCX top-level body paragraphs, remapping
detect() spans onto <w:r> runs even when a surface starts and/or ends MID-RUN.

Fixtures are hand-built in memory with python-docx (NO corpus import). Each test first
asserts the naive/pre-fix precondition (the surface is still extractable, or an rPr-bearing
run is intact), then asserts redact_docx_body destroyed the surface while preserving the
surrounding text and formatting. The input file is never mutated.
"""
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

from writer.docx_body import redact_docx_body


def _build(paragraphs: list[list[tuple]], path) -> None:
    """paragraphs: list of paragraphs; each paragraph a list of (text, bold?) run specs.

    Runs are emitted verbatim and in order, so a caller can split a single logical surface
    across several <w:r> runs (including mid-token) exactly like the real corpus does.
    """
    doc = Document()
    for runs in paragraphs:
        p = doc.add_paragraph()
        for spec in runs:
            text = spec[0]
            bold = spec[1] if len(spec) > 1 else None
            r = p.add_run(text)
            if bold:
                r.bold = True
    doc.save(str(path))


def _body_text(path) -> str:
    """Top-level body reconstruction, identical to the leak-gate probe: join paragraph.text
    (== concatenation of run.text) with NO separator inside a paragraph (context.md §10)."""
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


# ---------------------------------------------------------------- (a) mid-token, run-aligned
def test_name_split_mid_token_across_three_runs_is_redacted(tmp_path):
    src, out = tmp_path / "a_in.docx", tmp_path / "a_out.docx"
    # runs reconstruct to 'Lucie Molnárovej' (declined) — the corpus split-run shape.
    _build([[("Luc",), ("ie Molnáro",), ("vej",)]], src)

    # precondition: the glued surface is extractable from the input.
    assert "Lucie Molnárovej" in _body_text(src)

    redact_docx_body(str(src), str(out), known_entities=["Lucia Molnárová"])

    txt = _body_text(out)
    assert "Lucie" not in txt
    assert "Molnárovej" not in txt
    assert "[MENO]" in txt
    # input file untouched.
    assert "Lucie Molnárovej" in _body_text(src)


# ---------------------------------------------------------------- (b) starts AND ends mid-run
def test_name_starting_and_ending_mid_run_is_redacted_keeping_surrounding_text(tmp_path):
    src, out = tmp_path / "b_in.docx", tmp_path / "b_out.docx"
    # 'Jánom Novákom' starts inside run 0 (after 'Zmluva medzi ') and ends inside run 1
    # (before ' dnes') — the case the corpus never produces and W1 exists to handle.
    _build([[("Zmluva medzi Ján",), ("om Novákom dnes",)]], src)

    assert "Jánom Novákom" in _body_text(src)

    redact_docx_body(str(src), str(out), known_entities=["Ján Novák"])

    txt = _body_text(out)
    assert "Jánom" not in txt
    assert "Novákom" not in txt
    assert "[MENO]" in txt
    # the non-PII head and tail glued into the boundary runs must survive intact.
    assert txt.startswith("Zmluva medzi ")
    assert txt.endswith(" dnes")


# ---------------------------------------------------------------- (c) rPr survives a partial hit
def test_partially_overlapped_bold_run_keeps_its_rpr_on_surviving_fragment(tmp_path):
    src, out = tmp_path / "c_in.docx", tmp_path / "c_out.docx"
    # run 1 is bold and holds 'Ján Novák súhlasí'; only 'Ján Novák' is redacted, so the
    # surviving ' súhlasí' fragment must stay bold.
    _build([[("Kontakt: ",), ("Ján Novák súhlasí", True)]], src)

    # precondition: bold run is intact and the surface is extractable.
    src_doc = Document(str(src))
    src_bold = [r for p in src_doc.paragraphs for r in p.runs if r.bold]
    assert any("Ján Novák" in r.text for r in src_bold)

    redact_docx_body(str(src), str(out), known_entities=["Ján Novák"])

    txt = _body_text(out)
    assert "Ján Novák" not in txt
    assert "[MENO]" in txt

    doc = Document(str(out))
    survivors = [r for p in doc.paragraphs for r in p.runs if "súhlasí" in r.text]
    assert survivors, "surviving ' súhlasí' fragment vanished"
    assert all(r.bold for r in survivors), "surviving fragment lost its <w:rPr> (bold)"


# ---------------------------------------------------------------- (d) self-detecting identifier
def test_valid_ico_self_detects_without_known_entities(tmp_path):
    src, out = tmp_path / "d_in.docx", tmp_path / "d_out.docx"
    # 12345679 is a checksum-valid IČO (auto=True), matched with no known_entities.
    _build([[("IČO spoločnosti 12345679 tu.",)]], src)

    assert "12345679" in _body_text(src)

    redact_docx_body(str(src), str(out))  # known_entities omitted

    txt = _body_text(out)
    assert "12345679" not in txt
    assert "[ICO]" in txt


# ---------------------------------------------------------------- output integrity
def test_output_reopens_cleanly_and_input_is_never_mutated(tmp_path):
    src, out = tmp_path / "e_in.docx", tmp_path / "e_out.docx"
    _build([[("Kupujúci ",), ("Ján Novák",), (" a IČO 12345679.",)]], src)
    before = src.read_bytes()

    redact_docx_body(str(src), str(out), known_entities=["Ján Novák"])

    # reopens without XML corruption
    reopened = Document(str(out))
    assert reopened.paragraphs, "output has no body paragraphs"
    # input bytes unchanged
    assert src.read_bytes() == before
