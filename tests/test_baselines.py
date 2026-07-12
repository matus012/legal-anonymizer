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
from eval.baselines import (
    empty_output_redactor,
    greedy_redactor,
    null_redactor,
    refuse_all_redactor,
    scorch_redactor,
)
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


def test_scorch_redactor_fails_the_overall_verdict(corpus, tmp_path):
    # context.md rejection: a redactor that destroys everything must not exit 0. Zero leaks
    # and perfect recall are necessary but not sufficient — it must also fail the retention
    # gate (nothing but PII survived) and the decoy-survival gate (every decoy destroyed too).
    out = _apply(scorch_redactor, corpus, tmp_path / "scorch")
    outcome = run_eval(corpus, out)
    assert outcome.leaks == []
    assert not outcome.retention_ok, "scorch destroyed all non-PII content; retention gate must fire"
    assert not outcome.decoy_survival_ok, "scorch destroyed every decoy; decoy gate must fire"
    assert not outcome.passed, "scorch_redactor must not exit 0 (context.md rejection)"


def test_empty_output_redactor_fails_the_retention_gate(corpus, tmp_path):
    # A valid-but-empty output: zero leaks, perfect recall, and MUST still fail overall
    # because nothing but PII survived (context.md rejection, defect 1a).
    out = _apply(empty_output_redactor, corpus, tmp_path / "empty")
    outcome = run_eval(corpus, out)
    assert outcome.leaks == []
    for t in outcome.metrics.per_type.values():
        if t.auto_total:
            assert t.recall == 1.0
    assert not outcome.retention_ok
    assert not outcome.passed


def test_decoy_survival_gate_fires_even_when_aggregate_passes():
    # One type at 0%% decoy survival, buried among many types near 100%% — the aggregate sum
    # clears the 95%% bar easily, but the per-type gate must still catch it (defect D6: this
    # is the exact "hides in the sum" failure already rejected once for recall).
    from eval.metrics import CorpusMetrics, TypeMetrics
    from eval.run import EvalOutcome

    metrics = CorpusMetrics()
    metrics.per_type["GOOD_A"] = TypeMetrics(type="GOOD_A", decoy_total=100, decoy_preserved=100)
    metrics.per_type["GOOD_B"] = TypeMetrics(type="GOOD_B", decoy_total=100, decoy_preserved=100)
    metrics.per_type["BAD"] = TypeMetrics(type="BAD", decoy_total=5, decoy_preserved=0)
    outcome = EvalOutcome(metrics=metrics)

    assert metrics.decoy_survival > 0.95, "sanity: the aggregate must look fine"
    assert not outcome.decoy_survival_ok, "per-type gate must still fire for BAD"


def test_decoy_survival_gate_is_per_type(corpus, tmp_path):
    # A detector that destroys every decoy of just ONE type, while the corpus-wide sum would
    # still look mostly fine, must be caught (context.md rejection round 2, defect D6).
    out = _apply(scorch_redactor, corpus, tmp_path / "scorch")
    outcome = run_eval(corpus, out)
    decoy_types = [t for t in outcome.metrics.per_type.values() if t.decoy_total > 0]
    assert decoy_types
    for t in decoy_types:
        assert t.decoy_survival == 0.0
    assert not outcome.decoy_survival_ok


def test_refuse_all_redactor_fails_the_coverage_gate(corpus, tmp_path):
    # Refuses every input (not just no-text-layer fixtures): writes nothing at all. Zero
    # leaks, but every gradeable doc is missing its output (context.md rejection, defect 1b).
    out = _apply(refuse_all_redactor, corpus, tmp_path / "refuse")
    outcome = run_eval(corpus, out)
    assert outcome.leaks == []
    assert outcome.missing_outputs, "expected every gradeable doc to be reported missing"
    assert not outcome.coverage_ok
    assert not outcome.passed


def test_retention_distinguishes_real_redaction_from_destruction(corpus, tmp_path):
    # context.md rejection round 3, defect B2: retention must NOT mask the redacted side —
    # doing so let a no-op and a correct redactor score identically on retention's own axis.
    # Proof, with the redacted side read completely unmasked (measured exactly 1.0/1.0/0.0/0.0
    # on the full data/synthetic corpus; a tolerance is used here since this fixture is a
    # smaller n=6 sample):
    #   null_redactor    (copies input, PII still glued to its neighbors) -> retention ~1.0
    #   greedy_redactor  (real redaction, oracle-correct on auto+flag)    -> retention ~1.0
    #   scorch_redactor  (valid but empty file)                          -> retention ~0.0
    #   empty_output_redactor (same)                                     -> retention ~0.0
    results = {}
    for name, fn in (
        ("null", null_redactor),
        ("greedy", greedy_redactor),
        ("scorch", scorch_redactor),
        ("empty_output", empty_output_redactor),
    ):
        out = _apply(fn, corpus, tmp_path / name)
        outcome = run_eval(corpus, out)
        results[name] = outcome.metrics.retention

    assert results["null"] >= 0.95, results
    assert results["greedy"] >= 0.95, results
    assert results["scorch"] <= 0.05, results
    assert results["empty_output"] <= 0.05, results


def test_greedy_redactor_fails_the_flag_gate_alone(corpus, tmp_path):
    # context.md rejection round 2, defect D5: greedy_redactor auto-redacts every auto_redact
    # surface AND every checksum-invalid RODNE_CISLO/ICO/IBAN (the §7 hard negatives). It
    # leaks nothing, preserves everything else, preserves all decoys — and must fail ONLY on
    # the flag gate. That is the acceptance criterion the user will re-check directly.
    out = _apply(greedy_redactor, corpus, tmp_path / "greedy")
    outcome = run_eval(corpus, out)

    assert outcome.leaks == [], f"greedy must leak nothing, leaked {outcome.leaks[:5]}"
    assert outcome.coverage_ok
    assert outcome.retention_ok, f"retention {outcome.metrics.retention!r} must clear the bar"
    assert outcome.decoy_survival_ok, "greedy must not touch decoys"

    flag_types = [t for t in outcome.metrics.per_type.values() if t.flag_total > 0]
    assert flag_types, "corpus needs should_flag PII to exercise this"
    for t in flag_types:
        assert t.flag_survival == 0.0, f"{t.type}: greedy must auto-redact every flag item"
    assert not outcome.flag_survival_ok

    assert not outcome.passed, "greedy_redactor must not exit 0 — flag gate alone must fail it"
