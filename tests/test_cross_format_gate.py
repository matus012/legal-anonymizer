"""Tests for eval/cross_format_gate.py (Phase E gate 2, GATED).

The pure comparison logic (:func:`eval.cross_format_gate.judge_pair`) is tested directly on
hand-built ground-truth dicts and fake extracted text — no real docx/pdf, no writer calls —
so the FAIL case (defect (4) of the task: "a gate nobody has seen fail is not known to work")
is fast and deterministic. One slower end-to-end smoke test proves the real fixture-authoring
+ redaction + extraction path also runs and currently passes.
"""
from __future__ import annotations

from eval.cross_format_gate import (
    COMPARABLE_PARTS,
    DOCX_ONLY_PARTS,
    PDF_ONLY_PARTS,
    judge_pair,
    main,
    run_gate,
)


def _row(type_: str, surface: str, part: str, auto_redact: bool = True) -> dict:
    return {
        "type": type_,
        "surface": surface,
        "auto_redact": auto_redact,
        "should_flag": False,
        "location": {"surface_part": part, "detail": {}},
    }


def test_judge_pair_flags_a_real_asymmetry():
    """The synthetic FAIL input: the SAME surface, in a COMPARABLE part in both formats'
    ground truth, is removed from the docx output but survives in the pdf output. This is
    exactly the historical bug class (NBSP/line-break inside an anchor) the gate exists to
    catch, and the gate must not pass it."""
    docx_gt = {"pii": [_row("RODNE_CISLO", "850315/0018", "body")]}
    pdf_gt = {"pii": [_row("RODNE_CISLO", "850315/0018", "body")]}
    docx_text = "dokument bez rodneho cisla"          # redacted away
    pdf_text = "rodne cislo je 850315/0018 v texte"    # leaked

    v = judge_pair("case1", docx_gt, pdf_gt, docx_text, pdf_text)

    assert v.checked == 1
    assert len(v.asymmetries) == 1
    name, type_, surface, docx_redacted, pdf_redacted = v.asymmetries[0]
    assert (type_, surface) == ("RODNE_CISLO", "850315/0018")
    assert docx_redacted is True
    assert pdf_redacted is False


def test_judge_pair_no_asymmetry_when_both_agree():
    docx_gt = {"pii": [_row("EMAIL", "jan@example.sk", "body")]}
    pdf_gt = {"pii": [_row("EMAIL", "jan@example.sk", "body")]}
    docx_text = "text bez emailu"
    pdf_text = "text tiez bez emailu"

    v = judge_pair("case2", docx_gt, pdf_gt, docx_text, pdf_text)

    assert v.checked == 1
    assert v.asymmetries == []


def test_judge_pair_excludes_format_only_parts_by_name_and_counts_them():
    docx_gt = {"pii": [
        _row("EMAIL", "footer@example.sk", "footer"),          # DOCX-only part
        _row("TELEFON", "0905123456", "body"),                  # comparable
    ]}
    pdf_gt = {"pii": [
        _row("MENO", "Ján Novák", "annotation"),                 # PDF-only part
        _row("TELEFON", "0905123456", "body"),                   # comparable
    ]}
    # Both comparable surfaces agree (both leaked, say) so the only interesting numbers are
    # the exclusion counts, not the asymmetry list.
    v = judge_pair("case3", docx_gt, pdf_gt, "0905123456 v texte", "0905123456 v texte")

    assert v.checked == 1                     # only TELEFON/body is comparable
    assert v.excluded_docx_only == 1           # the footer EMAIL row
    assert v.excluded_pdf_only == 1            # the annotation MENO row
    assert v.asymmetries == []


def test_judge_pair_rejects_an_unclassified_surface_part():
    """A surface_part this module has never seen must be triaged (added to COMPARABLE_PARTS,
    DOCX_ONLY_PARTS or PDF_ONLY_PARTS) rather than silently falling through the comparison —
    silently ignoring an unknown part would quietly stop testing whatever it is."""
    docx_gt = {"pii": [_row("MENO", "X", "some_new_part_nobody_classified")]}
    pdf_gt = {"pii": []}
    try:
        judge_pair("case4", docx_gt, pdf_gt, "", "")
    except AssertionError as exc:
        assert "some_new_part_nobody_classified" in str(exc)
    else:
        raise AssertionError("expected judge_pair to reject an unclassified surface_part")


def test_part_classification_is_a_partition():
    """COMPARABLE_PARTS, DOCX_ONLY_PARTS and PDF_ONLY_PARTS must never overlap — a part
    counted as both comparable and excluded (or excluded on both sides) would double-count
    or silently drop surfaces."""
    assert not (COMPARABLE_PARTS & DOCX_ONLY_PARTS)
    assert not (COMPARABLE_PARTS & PDF_ONLY_PARTS)
    assert not (DOCX_ONLY_PARTS & PDF_ONLY_PARTS)


def test_end_to_end_gate_runs_and_currently_passes():
    """Integration SMOKE test: the real fixture-authoring + redaction + extraction + compare
    path must run to completion. Currently PASS on this codebase — if it ever starts failing,
    that is a real product finding (per-format detection divergence), not a reason to weaken
    this gate.

    CAPPED AT TWO CORPUS PAIRS, 2026-09-17. The gate gained the whole 70-pair corpus that day
    (QUESTIONS.md Q14 made the .docx and .pdf of one index the same document at last), which
    took this one test from ~5s to ~80s and the full suite from 170s to 245s. The six AUTHORED
    pairs are still graded in full here — they are the population this test was written for,
    and the one whose content the gate controls. The corpus population is what the GATE is for,
    and `python -m eval.cross_format_gate` still grades every pair of it.

    What this test asserts is that the PATH WORKS. What the gate asserts is that the corpus is
    consistent. Those are different questions and only the first one belongs in the suite."""
    assert run_gate(limit=2) == 0
