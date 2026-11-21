"""RECALL_FLOORS gate (eval/run.py) — per-type recall floor, currently {"ULICA": 0.98}.

Mirrors the shape of DECOY_SURVIVAL_MIN / FLAG_SURVIVAL_MIN: only a type with an explicit
entry in RECALL_FLOORS is gated, and the floor is checked per type, never averaged.

Per the task brief: "A gate that has never been seen to fail is not known to be a gate" —
this file's main job is proving the floor actually FIRES on a constructed failing case, not
just that it passes on today's corpus (that is eval.run's own CLI report).
"""
from __future__ import annotations

from eval.metrics import CorpusMetrics, TypeMetrics
from eval.run import RECALL_FLOORS, EvalOutcome, _format_report


def _outcome(per_type: dict[str, TypeMetrics]) -> EvalOutcome:
    metrics = CorpusMetrics(per_type=per_type, files_total=1, files_opened=1)
    return EvalOutcome(metrics=metrics)


def test_ulica_floor_is_pinned_at_098() -> None:
    # THE FLOOR IS 0.98 AND DOES NOT MOVE (task brief). Pin the constant itself so a future
    # edit that quietly loosens it is caught here, not just in a passing corpus run.
    assert RECALL_FLOORS["ULICA"] == 0.98


def test_recall_floor_fires_on_a_constructed_failing_case() -> None:
    """49/51 ULICA surfaces removed is 96.1% recall — below the 98% floor — and must FAIL."""
    ulica = TypeMetrics(type="ULICA", auto_total=51, auto_removed=49)
    assert ulica.recall is not None and ulica.recall < 0.98

    outcome = _outcome({"ULICA": ulica})
    assert outcome.recall_floors_ok is False
    assert outcome.passed is False

    report = _format_report(outcome)
    assert "[RECALL FLOOR] ULICA" in report
    assert "FAIL" in report.split("[RECALL FLOOR] ULICA")[1].splitlines()[0]


def test_recall_floor_passes_when_the_floor_is_met() -> None:
    """50/51 is 98.0% — exactly the floor — must PASS (the gate is >=, not >)."""
    ulica = TypeMetrics(type="ULICA", auto_total=51, auto_removed=50)
    assert ulica.recall == 50 / 51 >= 0.98 or round(ulica.recall, 4) >= 0.98

    outcome = _outcome({"ULICA": ulica})
    assert outcome.recall_floors_ok is True

    report = _format_report(outcome)
    line = [ln for ln in report.splitlines() if ln.startswith("[RECALL FLOOR] ULICA")][0]
    assert "PASS" in line


def test_unlisted_type_is_not_gated() -> None:
    """A type with no entry in RECALL_FLOORS (e.g. OBEC) must never fail this gate, no
    matter how low its recall — only explicitly listed types are gated (task brief: "do NOT
    silently gate every type")."""
    obec = TypeMetrics(type="OBEC", auto_total=100, auto_removed=1)
    assert obec.recall == 0.01

    # ULICA is included and PASSING so this test isolates the claim it is actually making.
    # Without it the outcome fails for an unrelated reason -- the pinned ULICA floor having no
    # population at all (see test_a_pinned_floor_with_no_population_FAILS_as_vacuous) -- and a
    # green result here would have meant nothing about OBEC.
    ulica = TypeMetrics(type="ULICA", auto_total=51, auto_removed=51)

    outcome = _outcome({"OBEC": obec, "ULICA": ulica})
    assert outcome.recall_floors_ok is True
    assert "OBEC" not in RECALL_FLOORS


def test_a_pinned_floor_with_no_population_FAILS_as_vacuous() -> None:
    """INVERTED 2026-09-17, deliberately. This test used to assert the opposite — that a run
    with no ULICA surfaces at all "must not be treated as a floor violation", because absent
    is "not computed", not "failed".

    That is the permissive reading, and on THIS project it is the wrong one. Red-team round 2
    finding C-2 is exactly this shape: "ULICA has a detector and ZERO corpus coverage, so no
    gate grades it. A type nothing asks about is untested whether it is excluded explicitly or
    simply absent, and the second is harder to see." A floor of 0.98 over an empty population
    reports PASS forever while asking nothing — the project has already had one gate go
    unfireable without anyone noticing.

    An entry in RECALL_FLOORS is a request to WATCH a type. If the population disappears, that
    request has stopped being served, and the run says so instead of printing a reassuring
    "n/a". The fix for a legitimately empty run is to remove the pin, which is a visible edit.
    """
    outcome = _outcome({})
    assert outcome.recall_floors_ok is False
    assert outcome.passed is False

    line = [ln for ln in _format_report(outcome).splitlines()
            if ln.startswith("[RECALL FLOOR] ULICA")][0]
    assert "NO GRADEABLE SURFACES" in line and "FAIL" in line and "vacuous" in line


def test_a_pinned_floor_with_an_uncomputable_recall_FAILS_as_vacuous() -> None:
    """The same hole reached the other way: the type IS present but has no gradeable surfaces,
    so ``recall`` is None. Both routes must reach the same verdict, or the guard is only half
    applied."""
    ulica = TypeMetrics(type="ULICA", auto_total=0, auto_removed=0)
    assert ulica.recall is None

    outcome = _outcome({"ULICA": ulica})
    assert outcome.recall_floors_ok is False
