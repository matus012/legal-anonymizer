"""Tests for the two-population form of eval/cross_format_gate.py (QUESTIONS.md Q14, final step).

``tests/test_cross_format_gate.py`` covers the original single-population comparison logic and
stays as it is. This file covers what was added when the gate started grading the real corpus
alongside its authored controls:

* the three asymmetry KINDS are kept apart (ground truth vs output);
* ``strict`` decides whether a one-sided comparable surface is a fixture bug (authored
  controls, raises) or a measurement (corpus, recorded);
* the surviving-surface predicate matches ``eval/leak_gate.py``'s, including the opaque
  attributability rule and the fact that every set-aside is RECORDED, never dropped;
* the part tables are the ones in ``corpus/builders_plan.py``, not a second copy.
"""
from __future__ import annotations

import corpus.builders_plan as builders_plan
import pytest
from eval.cross_format_gate import (
    COMPARABLE_PARTS,
    DOCX_ONLY_PARTS,
    PDF_ONLY_PARTS,
    SHARED_NON_COMPARABLE_PARTS,
    Verdict,
    corpus_stems,
    judge_pair,
)


def _row(type_: str, surface: str, part: str, auto_redact: bool = True,
         should_flag: bool = False) -> dict:
    return {
        "type": type_,
        "surface": surface,
        "auto_redact": auto_redact,
        "should_flag": should_flag,
        "location": {"surface_part": part, "detail": {}},
    }


def test_part_tables_are_the_builders_plan_tables_not_a_second_copy():
    """A second copy of DOCX_ONLY/PDF_ONLY would drift away from the renderer's own table and
    start explaining (or failing to explain) format differences the corpus does not have."""
    assert DOCX_ONLY_PARTS is builders_plan.DOCX_ONLY_PARTS
    assert PDF_ONLY_PARTS is builders_plan.PDF_ONLY_PARTS


def test_part_classification_is_still_a_partition_with_the_shared_bucket():
    buckets = [COMPARABLE_PARTS, set(DOCX_ONLY_PARTS), set(PDF_ONLY_PARTS),
               SHARED_NON_COMPARABLE_PARTS]
    for i, a in enumerate(buckets):
        for b in buckets[i + 1:]:
            assert not (a & b)


def test_one_sided_comparable_surface_is_a_fixture_bug_when_strict():
    docx_gt = {"pii": [_row("EMAIL", "jan@example.sk", "body")]}
    pdf_gt = {"pii": []}
    with pytest.raises(AssertionError, match="only one format"):
        judge_pair("authored", docx_gt, pdf_gt, "", "", strict=True)


def test_one_sided_comparable_surface_is_a_ground_truth_asymmetry_when_not_strict():
    """On the corpus the same observation is kind 1 — the corpus itself differs — and must be
    reported with the format that has it, not raised and not silently skipped."""
    docx_gt = {"pii": [_row("EMAIL", "jan@example.sk", "body"),
                       _row("TELEFON", "0905123456", "body")]}
    pdf_gt = {"pii": [_row("TELEFON", "0905123456", "body")]}

    v = judge_pair("zmluva_000", docx_gt, pdf_gt, "", "", strict=False)

    assert v.pairs == 1
    assert v.checked == 1                       # only the shared TELEFON is comparable
    assert v.gt_asymmetries == [("zmluva_000", "EMAIL", "jan@example.sk", "docx")]
    assert v.asymmetries == []
    assert v.failed is True                     # a GT asymmetry fails the gate too


def test_shared_non_comparable_metadata_is_excluded_and_counted():
    docx_gt = {"pii": [_row("MENO", "JUDr. Novák", "metadata_core")]}
    pdf_gt = {"pii": [_row("MENO", "JUDr. Novák", "metadata")]}

    v = judge_pair("meta", docx_gt, pdf_gt, "", "", strict=False)

    assert v.checked == 0
    assert v.excluded_shared_non_comparable == 2
    assert v.gt_asymmetries == []
    assert v.asymmetries == []


def test_opaque_only_match_is_set_aside_and_recorded_not_counted_as_surviving():
    """The real first-run FAIL, reduced: a four-digit KOD_BANKY still present in the PDF's
    object source only. Under the leak gate's attributability rule that is chance collision
    with font machinery, so it is not an output asymmetry — but it MUST still be recorded."""
    gt = {"pii": [_row("KOD_BANKY", "1100", "body")]}
    docx_by_surface = {"text_layer": "redacted"}
    pdf_by_surface = {"text_layer": "redacted",
                      "pdf_objects": "1046 1099 750 1100 1102 318 1103"}

    v = judge_pair("zmluva_020", gt, gt, "", "", strict=False,
                   docx_by_surface=docx_by_surface, pdf_by_surface=pdf_by_surface)

    assert v.asymmetries == []
    assert v.set_aside == [("zmluva_020", "KOD_BANKY", "1100", "pdf", ("pdf_objects",))]
    assert v.failed is False


def test_text_surface_match_counts_however_short_the_needle():
    """The attributability rule is scoped to OPAQUE surfaces. The same short needle sitting
    in the extracted TEXT of one format is a real output asymmetry and must fail."""
    gt = {"pii": [_row("KOD_BANKY", "1100", "body")]}

    v = judge_pair("zmluva_020", gt, gt, "", "", strict=False,
                   docx_by_surface={"text_layer": "redacted"},
                   pdf_by_surface={"text_layer": "kod banky 1100 v texte"})

    assert v.set_aside == []
    assert v.asymmetries == [("zmluva_020", "KOD_BANKY", "1100", True, False)]
    assert v.failed is True


def test_decoys_suppress_a_match_inside_a_longer_must_survive_string():
    gt = {"pii": [_row("ICO", "12345678", "body"),
                  _row("SPIS", "REF-12345678-X", "body", auto_redact=False)]}

    v = judge_pair("decoy", gt, gt, "", "", strict=False,
                   docx_by_surface={"text_layer": "spis REF-12345678-X"},
                   pdf_by_surface={"text_layer": "spis REF-12345678-X"})

    assert v.checked == 1
    assert v.asymmetries == []


def test_corpus_stems_finds_only_stems_present_in_both_formats(tmp_path):
    for name in ("a.docx", "a.pdf", "b.docx", "scan_image_only_c.docx",
                 "scan_image_only_c.pdf"):
        (tmp_path / name).write_bytes(b"x")
        (tmp_path / f"{name}.gt.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.pdf.gt.json").write_text("{}", encoding="utf-8")  # GT but no document

    stems = corpus_stems(tmp_path)

    assert [s for s, _, _ in stems] == ["a"]


def test_verdict_failed_is_false_only_when_both_kinds_are_empty():
    assert Verdict().failed is False
    assert Verdict(asymmetries=[("d", "t", "s", True, False)]).failed is True
    assert Verdict(gt_asymmetries=[("d", "t", "s", "docx")]).failed is True
    assert Verdict(set_aside=[("d", "t", "s", "pdf", ("raw_bytes",))]).failed is False
