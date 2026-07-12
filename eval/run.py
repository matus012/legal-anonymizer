"""Eval harness CLI (context.md §8) — point it at a dir of redacted outputs + the corpus GT.

    python -m eval.run --corpus data/synthetic --redacted data/redacted

For each ground-truth file it resolves the matching redacted output, extracts every surface,
runs the §8.1 leak test, and accumulates §8.2 per-type recall / precision. Any leak or any
formatting-integrity failure fails the run (non-zero exit). Documents flagged
``must_be_refused`` (image-only PDFs, §3) are expected to have NO output — an output for one
is itself a failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .extract import extract
from .leak import Leak, find_leaks
from .metrics import CorpusMetrics, evaluate

# §8.3 gate thresholds (context.md rejection, defect 1). A redactor that destroys everything
# scores 0 leaks / 100% recall on both the leak test and per-type recall — neither gate can
# tell redaction from destruction. Retention and decoy-survival close that hole.
RETENTION_MIN = 0.98
DECOY_SURVIVAL_MIN = 0.95
# §4.1 hard negatives (checksum-invalid RČ/IČO/IBAN) must reach the review bucket — i.e.
# survive in the output — 100% of the time. Any loss is a checksum-invalid identifier
# silently auto-redacted, the exact bug §4.1's checksum requirement exists to prevent
# (context.md rejection round 2, defect D5). No tolerance: this is a correctness bug, not a
# recall trade-off.
FLAG_SURVIVAL_MIN = 1.0


@dataclass
class EvalOutcome:
    leaks: list[tuple[str, Leak]] = field(default_factory=list)
    metrics: CorpusMetrics = field(default_factory=CorpusMetrics)
    refused: list[str] = field(default_factory=list)
    unexpected_outputs: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    integrity_failures: list[str] = field(default_factory=list)

    @property
    def coverage_ok(self) -> bool:
        """Every non-refused input must produce an output file — exact count equality."""
        return not self.missing_outputs

    @property
    def retention_ok(self) -> bool:
        """§8.3 retention gate: an empty/near-empty output must not pass just because it
        leaked nothing. ``None`` (gate not computed, e.g. no gradeable docs) is not a failure."""
        r = self.metrics.retention
        return r is None or r >= RETENTION_MIN

    @property
    def decoy_survival_ok(self) -> bool:
        """§8.3 precision gate: decoys (must NOT be redacted) must mostly survive. Checked PER
        TYPE (defect D6) — a corpus-wide sum can clear the bar while one decoy class is wiped
        out entirely; that must still fail."""
        return all(
            t.decoy_survival is None or t.decoy_survival >= DECOY_SURVIVAL_MIN
            for t in self.metrics.per_type.values()
        )

    @property
    def flag_survival_ok(self) -> bool:
        """§4.1/§8.3 flag gate: should_flag surfaces (checksum-invalid RČ/IČO/IBAN) must
        survive in the output 100%% of the time, per type — they belong in the review bucket,
        never auto-redacted (defect D5)."""
        return all(
            t.flag_survival is None or t.flag_survival >= FLAG_SURVIVAL_MIN
            for t in self.metrics.per_type.values()
        )

    @property
    def passed(self) -> bool:
        """§8.3 gates: zero leaks, full coverage, no corrupt outputs, no refused doc slipping
        through, non-PII content retained, decoys preserved per type, and flag items (hard
        negatives) preserved per type."""
        return not (
            self.leaks
            or self.integrity_failures
            or self.unexpected_outputs
        ) and self.coverage_ok and self.retention_ok and self.decoy_survival_ok and self.flag_survival_ok


def _resolve_output(redacted_dir: Path, source_file: str) -> Path | None:
    """Find the redacted output for ``source_file``: exact name, then ``<stem>_anon<ext>``
    (the §9 export naming). Returns None if neither exists."""
    src = Path(source_file)
    for name in (src.name, f"{src.stem}_anon{src.suffix}"):
        cand = redacted_dir / name
        if cand.exists():
            return cand
    return None


def run_eval(corpus_dir: Path | str, redacted_dir: Path | str) -> EvalOutcome:
    corpus_dir, redacted_dir = Path(corpus_dir), Path(redacted_dir)
    outcome = EvalOutcome()
    graded: list = []
    originals: list = []
    files_total = 0
    files_opened = 0

    for gt_path in sorted(corpus_dir.glob("*.gt.json")):
        gt = json.loads(gt_path.read_text("utf-8"))
        source = gt["source_file"]
        out = _resolve_output(redacted_dir, source)

        if gt["must_be_refused"]:
            if out is not None:
                outcome.unexpected_outputs.append(source)
            else:
                outcome.refused.append(source)
            continue

        if out is None:
            outcome.missing_outputs.append(source)
            continue

        files_total += 1
        try:
            res = extract(out)
        except Exception:  # a file that will not open is the integrity failure §8.2 wants
            outcome.integrity_failures.append(source)
            continue
        files_opened += 1
        graded.append((gt, res))
        originals.append(extract(corpus_dir / source))
        for lk in find_leaks(gt, res):
            outcome.leaks.append((source, lk))

    outcome.metrics = evaluate(
        graded, files_total=files_total, files_opened=files_opened, originals=originals
    )
    return outcome


# ---------------------------------------------------------------- reporting
def _format_report(outcome: EvalOutcome) -> str:
    m = outcome.metrics
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("EVAL HARNESS — context.md §8")
    lines.append("=" * 72)

    # §8.1 leak test — the headline verdict.
    if outcome.leaks:
        lines.append(f"\n[LEAK] HARD FAIL — {len(outcome.leaks)} leaked surface(s):")
        for source, lk in outcome.leaks[:50]:
            where = ",".join(lk.found_in)
            lines.append(f"  {source}: {lk.type} {lk.surface!r} leaked in [{where}]")
        if len(outcome.leaks) > 50:
            lines.append(f"  ... and {len(outcome.leaks) - 50} more")
    else:
        lines.append("\n[LEAK] zero leaks.")

    # §8.2 per-type recall / decoy-survival / flag-survival — never averaged. No precision
    # column: it is unmeasurable from output text alone (context.md rejection round 2,
    # defect D4) — decoy_survival is the only honest precision proxy this harness has.
    lines.append("\n[PER-TYPE] recall (auto_redact) / decoy survival / flag survival (should_flag):")
    lines.append(f"  {'TYPE':<16} {'recall':>8} {'decoy':>10} {'flag':>10}")
    for ptype in sorted(m.per_type):
        t = m.per_type[ptype]
        rec = "   n/a" if t.recall is None else f"{t.recall:6.1%}"
        dec = "      n/a" if t.decoy_survival is None else f"{t.decoy_preserved:>3}/{t.decoy_total:<3} {t.decoy_survival:5.0%}"
        flg = "      n/a" if t.flag_survival is None else f"{t.flag_retained:>3}/{t.flag_total:<3} {t.flag_survival:5.0%}"
        lines.append(f"  {ptype:<16} {rec:>8} {dec:>10} {flg:>10}")

    lines.append(f"\n[FORMATTING] {m.files_opened}/{m.files_total} outputs opened cleanly "
                 f"({m.formatting_integrity:.0%}).")

    # §8.3 gates that a redactor could otherwise cheat by destroying everything.
    ret = "n/a" if m.retention is None else f"{m.retention:.1%}"
    ret_verdict = "PASS" if outcome.retention_ok else f"FAIL (< {RETENTION_MIN:.0%})"
    lines.append(f"[RETENTION] non-PII content surviving: {ret} — {ret_verdict}")

    # Decoy survival and flag survival are GATED PER TYPE (defect D6 / D5) — a corpus-wide
    # aggregate is reported for context only; the verdict lists which types actually failed.
    agg = "n/a" if m.decoy_survival is None else f"{m.decoy_survival:.1%}"
    failing_decoy = sorted(
        t.type for t in m.per_type.values()
        if t.decoy_survival is not None and t.decoy_survival < DECOY_SURVIVAL_MIN
    )
    dec_verdict = "PASS" if outcome.decoy_survival_ok else f"FAIL ({', '.join(failing_decoy)})"
    lines.append(f"[DECOY SURVIVAL] {m.decoy_preserved}/{m.decoy_total} decoys preserved "
                 f"(aggregate {agg}, gate is per-type at >= {DECOY_SURVIVAL_MIN:.0%}) — {dec_verdict}")

    failing_flag = sorted(
        t.type for t in m.per_type.values()
        if t.flag_survival is not None and t.flag_survival < FLAG_SURVIVAL_MIN
    )
    flag_verdict = "PASS" if outcome.flag_survival_ok else f"FAIL ({', '.join(failing_flag)})"
    lines.append(f"[FLAG SURVIVAL] should_flag items must survive 100% per type — {flag_verdict}")

    cov_verdict = "PASS" if outcome.coverage_ok else f"FAIL ({len(outcome.missing_outputs)} missing)"
    lines.append(f"[COVERAGE] {cov_verdict}")

    if outcome.refused:
        lines.append(f"[REFUSED] {len(outcome.refused)} no-text-layer fixture(s) correctly refused.")
    if outcome.unexpected_outputs:
        lines.append(f"[REFUSED] FAIL — output produced for {len(outcome.unexpected_outputs)} "
                     f"doc(s) that must be refused: {outcome.unexpected_outputs}")
    if outcome.missing_outputs:
        lines.append(f"[MISSING] no output for {len(outcome.missing_outputs)} doc(s): "
                     f"{outcome.missing_outputs[:10]}")
    if outcome.integrity_failures:
        lines.append(f"[CORRUPT] {len(outcome.integrity_failures)} output(s) failed to open: "
                     f"{outcome.integrity_failures[:10]}")

    lines.append("")
    lines.append("VERDICT: " + ("PASS" if outcome.passed else "FAIL"))
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Redaction eval harness (context.md §8)")
    ap.add_argument("--corpus", type=Path, required=True, help="dir with the *.gt.json ground truth")
    ap.add_argument("--redacted", type=Path, required=True, help="dir with redacted output files")
    args = ap.parse_args(argv)

    # The report prints Slovak surfaces (and box glyphs); the Windows console defaults to
    # cp1250 and raises on anything outside it. Force UTF-8 so a leak is never masked by an
    # encoding crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if not args.corpus.is_dir():
        ap.error(f"corpus dir not found: {args.corpus}")
    if not args.redacted.is_dir():
        ap.error(f"redacted dir not found: {args.redacted}")

    outcome = run_eval(args.corpus, args.redacted)
    print(_format_report(outcome))
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    sys.exit(main())
