"""Baseline gate MATRIX — coverage, discrimination, and pinned vectors.

eval/baselines.py's five baseline "redactors" exist to prove the eval harness can actually
FAIL, and fail for the right reason. The property they must satisfy is NOT "each fails exactly
one gate" — that was never true: scorch and empty_output destroy every character and therefore
trip three gates at once. The real, weaker, true properties are:

  1. COVERAGE       — every §8.3 falsification gate (leak, coverage, retention, decoy_survival,
                      flag_survival) is tripped red by at least one baseline. A gate no baseline
                      can trip has never been proven to fire.
  2. DISCRIMINATION — no two baselines share a gate vector, with ONE known, intentional
                      exception: scorch_redactor and empty_output_redactor are two names for the
                      same total-destruction strategy and measure identically.
  3. PINNED VECTORS — each baseline's FULL 7-gate vector is pinned to its measured value as an
                      explicit literal below, so any change under eval/ that shifts a vector
                      turns this file red and demands review.

The corpus is the SAME fixture the mutation tests use (imported, not re-declared).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.baselines import (
    empty_output_redactor,
    greedy_redactor,
    null_redactor,
    refuse_all_redactor,
    scorch_redactor,
)
from eval.run import run_eval

# Reuse the EXACT corpus fixture the mutation tests use (generate n=10, seed=23). Imported so
# it can never silently drift from the corpus those tests measured against.
from tests.test_harness_mutations import corpus  # noqa: F401  (used as a pytest fixture)


# Every boolean gate EvalOutcome exposes, in the order eval/run.py::EvalOutcome.passed ANDs
# them. Value: predicate that is True when the gate is GREEN (holds / passes).
GATES = {
    "no_leaks": lambda o: not o.leaks,
    "no_integrity_failures": lambda o: not o.integrity_failures,
    "no_unexpected_outputs": lambda o: not o.unexpected_outputs,
    "coverage_ok": lambda o: o.coverage_ok,
    "retention_ok": lambda o: o.retention_ok,
    "decoy_survival_ok": lambda o: o.decoy_survival_ok,
    "flag_survival_ok": lambda o: o.flag_survival_ok,
}

BASELINES = {
    "null_redactor": null_redactor,
    "scorch_redactor": scorch_redactor,
    "empty_output_redactor": empty_output_redactor,
    "refuse_all_redactor": refuse_all_redactor,
    "greedy_redactor": greedy_redactor,
}

# The five §8.3 falsification gates the baselines exist to exercise. COVERAGE is asserted over
# exactly this set.
FALSIFICATION_GATES = frozenset({
    "no_leaks", "coverage_ok", "retention_ok", "decoy_survival_ok", "flag_survival_ok",
})
# The remaining two EvalOutcome gates. NO baseline here trips them, by construction: none emit
# a corrupt/unopenable file (integrity), and none are handed a must_be_refused doc, so none
# produce an output-for-a-refused-doc (unexpected). They are structural invariants, exercised
# elsewhere — pinned here so a future baseline that DOES trip one is caught.
STRUCTURAL_INVARIANTS = frozenset({"no_integrity_failures", "no_unexpected_outputs"})

# scorch and empty_output are two names for the same total-destruction strategy (both emit a
# valid empty file) and therefore MUST share a vector. This is the only allowed collision.
KNOWN_DUPLICATE = frozenset({"scorch_redactor", "empty_output_redactor"})

# Full 7-gate vector MEASURED for each baseline against the corpus above. True = GREEN (gate
# holds); False = RED (gate tripped). Written out as explicit literals — not derived — so a
# drift is visible in a diff.
PINNED = {
    "null_redactor": {
        "no_leaks": False,              # RED — copies input verbatim, every surface leaks
        "no_integrity_failures": True,
        "no_unexpected_outputs": True,
        "coverage_ok": True,
        "retention_ok": True,
        "decoy_survival_ok": True,
        "flag_survival_ok": True,
    },
    "scorch_redactor": {
        "no_leaks": True,
        "no_integrity_failures": True,
        "no_unexpected_outputs": True,
        "coverage_ok": True,
        "retention_ok": False,          # RED — no non-PII content survived
        "decoy_survival_ok": False,     # RED — every decoy destroyed
        "flag_survival_ok": False,      # RED — every should_flag hard-negative destroyed
    },
    "empty_output_redactor": {
        "no_leaks": True,
        "no_integrity_failures": True,
        "no_unexpected_outputs": True,
        "coverage_ok": True,
        "retention_ok": False,          # RED }
        "decoy_survival_ok": False,     # RED } identical vector to scorch — same strategy
        "flag_survival_ok": False,      # RED }
    },
    "refuse_all_redactor": {
        "no_leaks": True,
        "no_integrity_failures": True,
        "no_unexpected_outputs": True,
        "coverage_ok": False,           # RED — writes no output for any gradeable doc
        "retention_ok": True,           # (no graded docs -> gate not computed -> not a failure)
        "decoy_survival_ok": True,
        "flag_survival_ok": True,
    },
    "greedy_redactor": {
        "no_leaks": True,
        "no_integrity_failures": True,
        "no_unexpected_outputs": True,
        "coverage_ok": True,
        "retention_ok": True,
        "decoy_survival_ok": True,
        "flag_survival_ok": False,      # RED — auto-redacts checksum-invalid hard-negatives
    },
}


def _apply(redactor, corpus: Path, dst: Path) -> None:
    """Run ``redactor`` over every non-refused corpus doc. Mirrors eval/run.py's contract:
    ``must_be_refused`` docs are expected to have NO output, so no baseline is handed one."""
    dst.mkdir(parents=True, exist_ok=True)
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["must_be_refused"]:
            continue
        redactor(corpus / gt["source_file"], dst / gt["source_file"])


@pytest.fixture(scope="module")
def measured(corpus, tmp_path_factory) -> dict[str, dict[str, bool]]:
    """Measure the full 7-gate vector of every baseline once, against the shared corpus."""
    root = tmp_path_factory.mktemp("gate_matrix")
    vectors: dict[str, dict[str, bool]] = {}
    for name, redactor in BASELINES.items():
        dst = root / name
        _apply(redactor, corpus, dst)
        outcome = run_eval(corpus, dst)
        vectors[name] = {gate: is_green(outcome) for gate, is_green in GATES.items()}
    return vectors


# --------------------------------------------------------------- property 3: PINNED VECTORS
@pytest.mark.parametrize("name", list(BASELINES), ids=list(BASELINES))
def test_full_gate_vector_is_pinned(name, measured):
    assert measured[name] == PINNED[name], (
        f"{name}: gate vector drifted from its pinned value — investigate before re-pinning.\n"
        f"  pinned:   {PINNED[name]}\n"
        f"  measured: {measured[name]}"
    )


# --------------------------------------------------------------- property 1: COVERAGE
def test_every_falsification_gate_is_tripped_by_some_baseline(measured):
    tripped = {gate for v in measured.values() for gate, green in v.items() if not green}

    missing = FALSIFICATION_GATES - tripped
    assert not missing, f"§8.3 gate(s) no baseline can trip (never proven to fire): {missing}"

    # Exactly the falsification gates are tripped: the two structural-invariant gates
    # (integrity, unexpected-output) stay green across all five, by construction.
    assert tripped == set(FALSIFICATION_GATES), (
        f"a gate outside the falsification set was tripped: {tripped - FALSIFICATION_GATES}"
    )
    assert FALSIFICATION_GATES | STRUCTURAL_INVARIANTS == set(GATES), (
        "the falsification + structural gate sets must partition every EvalOutcome gate"
    )


# --------------------------------------------------------------- property 2: DISCRIMINATION
def test_baselines_discriminate_except_the_known_total_destruction_duplicate(measured):
    groups: dict[tuple, set[str]] = {}
    for name, vector in measured.items():
        groups.setdefault(tuple(sorted(vector.items())), set()).add(name)
    collisions = {frozenset(names) for names in groups.values() if len(names) > 1}
    assert collisions == {KNOWN_DUPLICATE}, (
        "baseline vector collisions changed. Expected exactly the known total-destruction "
        f"duplicate {set(KNOWN_DUPLICATE)} and no other; got {[set(c) for c in collisions]}"
    )
