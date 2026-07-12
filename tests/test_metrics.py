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
from eval.metrics import evaluate


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
