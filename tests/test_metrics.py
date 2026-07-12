"""§8.2 metrics — per-type recall / precision, reported per type, never averaged.

Two anchors pin the metrics honest:
* the UNREDACTED corpus (no-op) must score recall 0 and preserve every decoy;
* a fully-scorched extraction (all text destroyed) must score recall 1.0 and preserve no
  decoy — terrible precision, the price of destroying everything.
A metrics module that cannot tell these two apart is useless as a grader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from corpus.generate import generate
from eval.extract import ExtractResult, extract
from eval.metrics import TypeMetrics, evaluate


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=13, formats=["docx", "pdf"])
    return out


def _graded(corpus: Path, *, scorch: bool):
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if not gt["text_layer"]:
            continue
        if scorch:
            res = ExtractResult(full_text="", by_surface={})
        else:
            res = extract(corpus / gt["source_file"])
        yield gt, res


def test_unredacted_recall_is_zero_and_decoys_preserved(corpus):
    m = evaluate(list(_graded(corpus, scorch=False)))
    assert m.per_type, "no types scored"
    for t in m.per_type.values():
        if t.auto_total:
            assert t.recall == 0.0, f"{t.type}: expected 0 recall on no-op, got {t.recall}"
        if t.decoy_total:
            assert t.decoy_preserved == t.decoy_total, f"{t.type}: decoys were redacted"


def test_scorched_recall_is_perfect_and_no_decoy_preserved(corpus):
    m = evaluate(list(_graded(corpus, scorch=True)))
    for t in m.per_type.values():
        if t.auto_total:
            assert t.recall == 1.0, f"{t.type}: expected perfect recall when scorched"
        if t.decoy_total:
            assert t.decoy_preserved == 0, f"{t.type}: decoy survived a total scorch"


def test_metrics_are_reported_per_type_not_averaged(corpus):
    m = evaluate(list(_graded(corpus, scorch=False)))
    # Several distinct PII types must each carry their own numbers.
    assert len(m.per_type) >= 5
    assert "MENO" in m.per_type and "ICO" in m.per_type


def test_formatting_integrity_tracks_opened_files(corpus):
    graded = list(_graded(corpus, scorch=False))
    m = evaluate(graded, files_total=len(graded), files_opened=len(graded))
    assert m.formatting_integrity == 1.0


# --------------------------------------------------------------------------- retention (defect 1a)
def test_retention_is_none_without_originals(corpus):
    # No originals supplied -> the gate cannot be computed, and must not silently claim 0%%.
    m = evaluate(list(_graded(corpus, scorch=False)))
    assert m.retention is None


def test_retention_is_near_one_when_output_equals_original(corpus):
    graded = list(_graded(corpus, scorch=False))
    originals = [extract(corpus / gt["source_file"]) for gt, _ in graded]
    m = evaluate(graded, originals=originals)
    assert m.retention is not None
    assert m.retention > 0.99


def test_retention_is_zero_when_output_is_scorched(corpus):
    graded_full = list(_graded(corpus, scorch=False))
    originals = [extract(corpus / gt["source_file"]) for gt, _ in graded_full]
    scorched = [(gt, ExtractResult(full_text="", by_surface={})) for gt, _ in graded_full]
    m = evaluate(scorched, originals=originals)
    assert m.retention is not None
    assert m.retention < 0.01


# --------------------------------------------------------------------------- decoy survival (defect 1c)
def test_decoy_survival_aggregate_full_on_unredacted(corpus):
    m = evaluate(list(_graded(corpus, scorch=False)))
    assert m.decoy_total > 0
    assert m.decoy_survival == 1.0


def test_decoy_survival_aggregate_zero_on_scorch(corpus):
    m = evaluate(list(_graded(corpus, scorch=True)))
    assert m.decoy_total > 0
    assert m.decoy_survival == 0.0


# --------------------------------------------------------------------------- precision deleted (defect D4)
def test_precision_property_does_not_exist():
    # Per-type "precision" is unmeasurable from output text alone: since decoys are always a
    # DIFFERENT type from the auto-redact types they mimic, a type's own decoy_total is always
    # 0, so the old formula degenerated to recall printed under a second name. Deleted, not
    # just hidden from the report.
    assert not hasattr(TypeMetrics(type="X"), "precision")


# --------------------------------------------------------------------------- per-type decoy gate (defect D6)
def test_decoy_survival_is_per_type_not_only_aggregate(corpus):
    # A detector that destroys 100%% of ONE decoy type while preserving all others must be
    # visible in that type's own number, not hidden inside a corpus-wide sum.
    m = evaluate(list(_graded(corpus, scorch=False)))
    decoy_types = [t for t in m.per_type.values() if t.decoy_total > 0]
    assert len(decoy_types) >= 2, "need multiple decoy types to prove per-type isolation"
    for t in decoy_types:
        assert t.decoy_survival == 1.0


def test_decoy_survival_per_type_zero_on_scorch(corpus):
    m = evaluate(list(_graded(corpus, scorch=True)))
    decoy_types = [t for t in m.per_type.values() if t.decoy_total > 0]
    assert decoy_types
    for t in decoy_types:
        assert t.decoy_survival == 0.0


# --------------------------------------------------------------------------- flag survival gate (defect D5)
def test_flag_survival_full_on_unredacted(corpus):
    m = evaluate(list(_graded(corpus, scorch=False)))
    flag_types = [t for t in m.per_type.values() if t.flag_total > 0]
    assert flag_types, "corpus needs should_flag PII (checksum-invalid RC/ICO/IBAN)"
    for t in flag_types:
        assert t.flag_survival == 1.0


def test_flag_survival_zero_on_scorch(corpus):
    m = evaluate(list(_graded(corpus, scorch=True)))
    flag_types = [t for t in m.per_type.values() if t.flag_total > 0]
    assert flag_types
    for t in flag_types:
        assert t.flag_survival == 0.0
