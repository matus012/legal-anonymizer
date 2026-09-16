"""Per-type precision — Phase E gate 1, REPORT ONLY, NO THRESHOLD (CONTRACTS_v11.md).

    python -m eval.precision_report

Governing rule (context.md §6): **recall over precision**. This module NEVER gates and NEVER
prints anything that reads as a pass/fail verdict — a low precision number here is exactly
what the policy predicts (every ambiguous decision resolves toward over-detection), so it is
INFORMATION about the trade-off being made on purpose, not a defect. ``exit(0)`` always,
whatever the numbers say.

--------------------------------------------------------------------------------------
WHAT IS MEASURED, EXACTLY
--------------------------------------------------------------------------------------
**Unit = one ``<w:p>``**, reconstructed exactly as ``writer/docx_body.py`` hands it to
``detect()`` — reuses :func:`eval.mutation_gate.docx_units`, the same production-faithful
reconstruction that module already proved (tracked revisions accepted, footnotes/endnotes/
comments/headers/footers included). Measuring over a different string than production would
measure a precision number nobody's output ever produces.

**Population = every ``detect()`` candidate**, over EVERY document in the corpus that has a
ground-truth file, called production-faithfully with this document's own known-entities list
(the same ``known`` the leak gate builds: canonical names of ``MENO`` entities). For each
candidate of type ``T`` at span ``[start, end)`` in some unit, it is BACKED when the unit
contains SOME ground-truth PII occurrence of the SAME type ``T`` whose own span overlaps
``[start, end)`` at all. Any overlap counts as backed — this is deliberately generous in
the direction that would UNDERSTATE a precision problem, never invent one, because the
governing rule (§6) already tells us to expect low precision and a stricter definition here
would risk manufacturing a "regression" out of an anchor that legitimately grabs one extra
character of context.

The GT lookup uses ALL of a document's ``pii`` rows, not only ``auto_redact`` ones — a decoy
row is recorded under a type DIFFERENT from the real type it mimics (``eval/metrics.py``
docstring), so it can never accidentally "back" a false positive of the real type; it is
present here only so a candidate that (correctly) lands on a ``should_flag`` bare-name still
counts as backed rather than as a false positive of its own type.

**Exclusions, counted:**
* corpus files with no ``.gt.json`` — same convention as ``eval/leak_gate.py`` — skipped,
  named, counted.
* the image-only PDF fixture (``must_be_refused=True``) — never scanned, has no text layer.
* a type with zero candidates in the whole corpus prints ``n/a`` rather than a fabricated
  ``0/0 -> 100%``.

This module imports ``detect/`` directly (like ``eval/mutation_gate.py``, unlike
``eval/leak_gate.py``): its premise is to grade the detector's own output, not the writers'.

Exit code: always 0. This module cannot fail a build.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from detect.core import detect
from eval.mutation_gate import docx_units


@dataclass
class TypeTally:
    candidates: int = 0
    backed: int = 0

    @property
    def precision(self) -> float | None:
        return None if self.candidates == 0 else self.backed / self.candidates


def _gt_type_spans(unit: str, pii_rows: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """{type: [(start, end), ...]} for every occurrence of every recorded surface (any class:
    auto_redact, should_flag, decoy alike — see module docstring) inside this unit's text."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for pii in pii_rows:
        surface = pii["surface"]
        if not surface:
            continue
        start = 0
        while True:
            idx = unit.find(surface, start)
            if idx == -1:
                break
            spans.setdefault(pii["type"], []).append((idx, idx + len(surface)))
            start = idx + 1
    return spans


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def measure(corpus_dir: Path) -> tuple[dict[str, TypeTally], list[str], int]:
    """Returns (per-type tallies, skipped filenames, files measured)."""
    tallies: dict[str, TypeTally] = {}
    skipped: list[str] = []
    measured = 0
    for src in sorted(corpus_dir.glob("*.docx")):
        gt_path = Path(f"{src}.gt.json")
        if not gt_path.exists():
            skipped.append(src.name)
            continue
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        if gt.get("must_be_refused"):
            skipped.append(src.name)
            continue
        known = [e["canonical"] for e in gt["entities"] if e.get("category") == "MENO"]
        measured += 1
        for unit in docx_units(src):
            gt_spans = _gt_type_spans(unit, gt["pii"])
            for cand in detect(unit, known):
                tally = tallies.setdefault(cand.type, TypeTally())
                tally.candidates += 1
                occurrences = gt_spans.get(cand.type, [])
                if any(_overlaps(cand.start, cand.end, s, e) for s, e in occurrences):
                    tally.backed += 1
    return tallies, skipped, measured


def _print_report(tallies: dict[str, TypeTally], skipped: list[str], measured: int) -> None:
    print(f"per-type precision report: {measured} docx file(s) measured, "
          f"{len(skipped)} skipped (no ground truth, or must_be_refused fixture): "
          f"{', '.join(skipped) or '-'}")
    print()
    print("REPORT ONLY — governing rule is recall over precision (context.md §6). A low "
          "number here is the policy working as designed, not a failure. This never gates.")
    print()
    header = f"  {'TYPE':<20} {'backed':>8} {'candidates':>12} {'precision':>11}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for type_ in sorted(tallies):
        t = tallies[type_]
        prec = "n/a" if t.precision is None else f"{t.precision:.1%}"
        print(f"  {type_:<20} {t.backed:>8} {t.candidates:>12} {prec:>11}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    corpus_dir = Path("data/synthetic")
    if not corpus_dir.is_dir():
        print(f"no corpus at {corpus_dir} — regenerate it first:")
        print("  python -m corpus.generate --n 60 --out data/synthetic --seed 42 "
              "--formats docx,pdf")
        return 0  # report-only module — never fails a build, even on a missing corpus
    tallies, skipped, measured = measure(corpus_dir)
    _print_report(tallies, skipped, measured)
    return 0


if __name__ == "__main__":
    sys.exit(main())
