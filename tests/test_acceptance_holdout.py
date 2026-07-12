"""Acceptance-only gate (context.md rejection, defect D2/D7) — the held-out corpus, seed 1337.

``data/holdout/`` is generated ONCE (``python -m corpus.generate --n 60 --out data/holdout
--seed 1337 --formats docx,pdf``) and never regenerated to chase a result. It is never
iterated against, never tuned to, and its individual per-document failures are never read
during development — every other test file in this suite runs against the seed-42
``data/synthetic`` corpus instead. Without this separation, a detector's recall numbers get
silently fit to the exact corpus the agentic loop keeps looking at, and the number stops
meaning anything about real recall.

Structurally enforced, not just documented: this module is marked ``acceptance`` and
``tests/conftest.py`` skips that marker by default. It only runs when invoked explicitly:

    pytest --run-acceptance
    pytest -m acceptance

A holdout corpus that is never actually evaluated is not a holdout, it is a directory
(context.md rejection round 2, defect D7). Five known-bad baselines exist NOW — null, scorch,
empty_output, refuse_all, greedy — so this module runs every one of them against the holdout
corpus through the real ``run_eval`` pipeline and asserts each fails on its specific named
gate. There is no real detector yet (context.md §11 build order, step 3+); when one lands,
add its acceptance run here alongside these.
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

pytestmark = pytest.mark.acceptance

HOLDOUT = Path("data/holdout")


def test_holdout_corpus_exists():
    assert HOLDOUT.is_dir(), (
        "data/holdout/ is missing. Regenerate ONCE with: "
        "python -m corpus.generate --n 60 --out data/holdout --seed 1337 --formats docx,pdf "
        "(context.md rejection, defect D2). Do not regenerate this to chase a passing result."
    )
    gts = list(HOLDOUT.glob("*.gt.json"))
    assert len(gts) == 60 * 2 + 1, f"expected 121 ground-truth files, found {len(gts)}"


def test_holdout_corpus_is_seed_1337():
    # corpus.generate derives each file's seed as `1337 * 1000 + i * 10 + f_idx`, and the
    # image-only fixture as `1337 * 1000 + 99999` — both land in this range.
    lo, hi = 1337_000, 1337_000 + 99_999
    for gt_path in HOLDOUT.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        assert lo <= gt["seed"] <= hi, (
            f"{gt_path.name}: seed {gt['seed']} does not derive from 1337 — this is not the "
            "acceptance corpus (or it was regenerated with the wrong seed)"
        )


def _redact_holdout(redactor, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for gt_path in HOLDOUT.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["must_be_refused"]:
            continue
        src = HOLDOUT / gt["source_file"]
        redactor(src, out / src.name)
    return out


# Each baseline's known failure mode, named by the specific §8.3 gate it must trip on the
# holdout corpus — the same mapping already proven on data/synthetic in tests/test_baselines.py.
_BASELINES = [
    ("null", null_redactor, "leak"),
    ("scorch", scorch_redactor, "retention"),
    ("empty_output", empty_output_redactor, "retention"),
    ("refuse_all", refuse_all_redactor, "coverage"),
    ("greedy", greedy_redactor, "flag"),
]


@pytest.mark.parametrize("name,redactor,failing_gate", _BASELINES, ids=[b[0] for b in _BASELINES])
def test_known_bad_baseline_fails_holdout_on_its_named_gate(name, redactor, failing_gate, tmp_path):
    out = _redact_holdout(redactor, tmp_path / name)
    outcome = run_eval(HOLDOUT, out)

    gate_ok = {
        "leak": not outcome.leaks,
        "retention": outcome.retention_ok,
        "coverage": outcome.coverage_ok,
        "decoy": outcome.decoy_survival_ok,
        "flag": outcome.flag_survival_ok,
    }
    assert not gate_ok[failing_gate], (
        f"{name}: expected the {failing_gate} gate to fail on the HOLDOUT corpus, it passed. "
        f"leak={not outcome.leaks} retention={outcome.retention_ok} "
        f"coverage={outcome.coverage_ok} decoy={outcome.decoy_survival_ok} "
        f"flag={outcome.flag_survival_ok}"
    )
    assert not outcome.passed, f"{name} must not pass the holdout corpus"
