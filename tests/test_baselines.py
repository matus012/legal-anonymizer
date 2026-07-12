"""The harness grading itself (context.md §8, steps 4 & 5) — permanent in the suite.

A harness that passes a do-nothing redactor is broken; a harness that reports success by
finding nothing is equally broken. Two baselines pin both failure modes:

* NULL      — copy input to output unchanged → MASSIVE leaks, ~0%% recall.
* SCORCH    — destroy every character → 0 leaks, 100%% recall, terrible precision (decoys
              destroyed too).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from corpus.generate import generate
from eval.baselines import null_redactor, scorch_redactor
from eval.run import run_eval


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=17, formats=["docx", "pdf"])
    return out


def _apply(redactor, corpus: Path, dst: Path) -> Path:
    """Run ``redactor`` over every gradeable corpus file into ``dst`` (refused fixtures skipped)."""
    dst.mkdir(parents=True, exist_ok=True)
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["must_be_refused"]:
            continue  # a real redactor refuses these; emit no output
        src = corpus / gt["source_file"]
        redactor(src, dst / src.name)
    return dst


def test_null_redactor_leaks_massively_and_scores_zero_recall(corpus, tmp_path):
    out = _apply(null_redactor, corpus, tmp_path / "null")
    outcome = run_eval(corpus, out)

    assert not outcome.passed, "harness must FAIL a no-op redactor"
    assert len(outcome.leaks) > 100, f"expected massive leaks, got {len(outcome.leaks)}"
    for t in outcome.metrics.per_type.values():
        if t.auto_total:
            assert t.recall == 0.0, f"{t.type}: no-op must score 0 recall, got {t.recall}"


def test_scorch_redactor_zero_leaks_full_recall_terrible_precision(corpus, tmp_path):
    out = _apply(scorch_redactor, corpus, tmp_path / "scorch")
    outcome = run_eval(corpus, out)

    assert outcome.leaks == [], f"scorch must leak nothing, leaked {outcome.leaks[:3]}"
    assert outcome.metrics.formatting_integrity == 1.0, "scorched files must still open"
    for t in outcome.metrics.per_type.values():
        if t.auto_total:
            assert t.recall == 1.0, f"{t.type}: scorch must score perfect recall"
    total_decoy = sum(t.decoy_total for t in outcome.metrics.per_type.values())
    preserved = sum(t.decoy_preserved for t in outcome.metrics.per_type.values())
    assert total_decoy > 0 and preserved == 0, "scorch must destroy every decoy (bad precision)"


def test_run_eval_reports_refused_fixture(corpus, tmp_path):
    # The image-only PDF must be refused: no output is the correct behaviour, not a miss.
    out = _apply(scorch_redactor, corpus, tmp_path / "ref")
    outcome = run_eval(corpus, out)
    assert outcome.refused, "expected the image-only fixture to be recognised as refused"
    assert not outcome.unexpected_outputs
