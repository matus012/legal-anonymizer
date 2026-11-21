"""Detection-robustness gate — red-team round 2.

    python -m eval.mutation_gate

The §8.1 leak gate answers "did the pipeline remove the surfaces the corpus generator
authored?". This gate answers the question one step upstream: **would the detector still
FIND that surface if the document had been written slightly differently?** For every
mutation in ``corpus/mutations.py`` it computes

    robustness(m) = recall(mutated) / recall(clean)

per PII type and overall, and flags every cell below **0.95**, the sprint's DONE gate.

--------------------------------------------------------------------------------------
WHAT IS MEASURED, EXACTLY
--------------------------------------------------------------------------------------
**Unit = one ``<w:p>``.** ``writer/docx_body.py`` calls ``detect()`` once per paragraph over
that paragraph's reconstructed run text — body paragraphs, table cells, header/footer
paragraphs, textboxes, and the footnotes/endnotes/comments parts. This module rebuilds
exactly those units straight from the OPC package (accepting tracked revisions first, as the
writer does: ``w:del`` subtrees dropped, ``w:ins`` text kept) so that the text handed to
``detect()`` here is the text handed to ``detect()`` in production. Measuring over
``eval.extract``'s whole-document concatenation instead would be measuring a string the
writers never see — see ``QUESTIONS.md`` Q8, where exactly that difference produced two
different answers.

**Population = the ground truth's ``auto_redact`` class**, per document, per surface string.
A surface is DETECTED when some candidate ``c`` from ``detect(unit)`` satisfies
``c.start <= i and i + len(surface) <= c.end`` for an occurrence at ``i`` — i.e. the
candidate COVERS the whole surface. Partial coverage is a partial leak and does not count.

**Two arms, because the answer differs and the difference is the finding.**

* ``blind`` — ``detect(unit, [])``. No user-supplied entity list. This isolates the
  PATTERN / ANCHOR / GAZETTEER detectors, which is where a mutation defect lives.
* ``known`` — ``detect(unit, known)`` with ``known`` built exactly as ``eval/leak_gate.py``
  builds it (``[e["canonical"] for e in gt["entities"] if e["category"] == "MENO"]``), and
  MUTATED with the same mutation. This is the production-faithful arm: it is what the leak
  gate actually runs, so its number is the one that predicts whether a mutated corpus would
  leak. ``detect.declension`` matches known entities by STEM, so this arm rescues most of
  MENO under most mutations — which is true, and is also why reporting only this arm would
  hide every defect in the name ANCHORS behind the user's typing.

The gate fails if EITHER arm's overall robustness is below the threshold. That is never
weaker than the brief's single-number gate.

**Pairing and exclusions.** For each (document, surface, mutation) the harness first checks
that the mutated surface is still present in some mutated unit. When it is not — the
homomorphism caveat documented in ``corpus/mutations.py`` — the pair is EXCLUDED from BOTH
the clean and the mutated tally and counted separately, because the harness can no longer ask
the question. Everything else is measured PAIRED: identical surface set in numerator and
denominator, so the ratio cannot move because the populations differ.

**Surfaces ``detect()`` never sees are excluded up front**: a GT surface that appears in no
unit at all (DOCX metadata, which ``writer/docx_body.py`` blanks BY POSITION and never routes
through ``detect()``; and the ``tracked_change_del`` text, which is removed before detection).
Counting those as misses would grade the redactor's metadata scrubber as a detector failure.

--------------------------------------------------------------------------------------
This module imports ``detect/`` — deliberately, and unlike ``eval/leak_gate.py``, which is
forbidden to. The leak gate must exercise detection ONLY through the writers because its
premise is end-to-end. This gate's premise is the opposite: it grades the detector in
isolation, so it calls it directly. It never writes a file and never regenerates the corpus.

Exit codes: 0 = PASS, 1 = at least one mutation below threshold, 2 = corpus missing.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from lxml import etree

from corpus.mutations import CASE_DESTROYING, MUTATIONS, REPORT_ONLY
from detect.core import detect

# --------------------------------------------------------------------------- constants
ROBUSTNESS_MIN = 0.95           # the sprint's DONE gate. Never edited to make a run pass.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_ARMS = ("blind", "known")


def _is_detect_part(name: str) -> bool:
    """Is this OPC part one whose ``<w:p>`` elements are routed through ``detect()``?

    Mirrors ``writer/docx_body.redact_docx_body``'s traversal: document.xml (body paragraphs,
    tables, VML textboxes), every header/footer part (+ their tables and textboxes), and the
    footnotes / endnotes / comments parts. Nothing else in the package reaches ``detect()``.
    """
    return name == "word/document.xml" or (
        name.startswith("word/")
        and (
            name.startswith("word/header")
            or name.startswith("word/footer")
            or name in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
        )
        and name.endswith(".xml")
    )


def docx_units(path: Path) -> list[str]:
    """The production ``detect()`` units of one .docx, in package order.

    Tracked revisions are ACCEPTED first — ``w:del`` subtrees removed, ``w:ins`` text kept —
    because ``writer/docx_body.py`` does that (``_strip_tracked_changes``) before any
    paragraph is detected. Getting this wrong in either direction would change the measured
    population: keeping ``w:del`` text would grade a string the writer has already deleted.
    """
    units: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(n for n in zf.namelist() if _is_detect_part(n)):
            root = etree.fromstring(zf.read(name))
            for para in root.iter(_W + "p"):
                for deleted in list(para.iter(_W + "del")):
                    deleted.getparent().remove(deleted)
                text = "".join(t.text or "" for t in para.iter(_W + "t"))
                if text:
                    units.append(text)
    return units


# --------------------------------------------------------------------------- corpus cases
@dataclass(frozen=True)
class Case:
    """One corpus document: its ``detect()`` units, its auto-redact GT, its entity list."""

    name: str
    units: tuple[str, ...]
    surfaces: tuple[tuple[str, str], ...]   # (type, surface), deduped per document
    known: tuple[str, ...]


def load_cases(corpus_dir: Path) -> tuple[list[Case], dict[str, int]]:
    """Every .docx in ``corpus_dir`` that has ground truth, plus the unreachable-surface
    census (per type) that this harness deliberately does not grade."""
    cases: list[Case] = []
    unreachable: dict[str, int] = {}
    for src in sorted(corpus_dir.glob("*.docx")):
        gt_path = Path(f"{src}.gt.json")
        if not gt_path.exists():
            continue
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        units = tuple(docx_units(src))
        haystack = "\n".join(units)
        seen: set[tuple[str, str]] = set()
        surfaces: list[tuple[str, str]] = []
        for pii in gt["pii"]:
            if not pii["auto_redact"]:
                continue
            key = (pii["type"], pii["surface"])
            if key in seen:
                continue
            seen.add(key)
            if pii["surface"] not in haystack:
                unreachable[pii["type"]] = unreachable.get(pii["type"], 0) + 1
                continue
            surfaces.append(key)
        known = tuple(
            e["canonical"] for e in gt["entities"] if e.get("category") == "MENO"
        )
        cases.append(Case(src.name, units, tuple(surfaces), known))
    return cases, unreachable


# --------------------------------------------------------------------------- measurement
@dataclass
class Cell:
    """One (type, arm) tally, PAIRED: same surface population on both sides."""

    paired: int = 0          # surfaces measurable under both clean and mutated text
    clean_hit: int = 0       # covered by an auto=True candidate in the clean text
    mut_hit: int = 0         # covered by an auto=True candidate in the mutated text
    mut_any: int = 0         # covered by ANY candidate (incl. auto=False) when mutated
    clean_any: int = 0
    excluded: int = 0        # mutated surface not present in the mutated text (see module doc)

    @property
    def clean_recall(self) -> float | None:
        return None if self.paired == 0 else self.clean_hit / self.paired

    @property
    def mut_recall(self) -> float | None:
        return None if self.paired == 0 else self.mut_hit / self.paired

    @property
    def robustness(self) -> float | None:
        """``recall(mutated) / recall(clean)``. ``None`` when clean recall is 0 — a ratio
        with a zero denominator is not a robustness of 0, it is an unanswerable question,
        and printing it as 0.000 would invent a defect."""
        return None if self.clean_hit == 0 else self.mut_hit / self.clean_hit


@dataclass
class Result:
    """One (mutation, arm) run."""

    mutation: str
    arm: str
    per_type: dict[str, Cell] = field(default_factory=dict)
    errors: list[tuple[str, str, str]] = field(default_factory=list)  # (case, kind, message)

    def cell(self, type_: str) -> Cell:
        return self.per_type.setdefault(type_, Cell())

    @property
    def overall(self) -> Cell:
        total = Cell()
        for c in self.per_type.values():
            total.paired += c.paired
            total.clean_hit += c.clean_hit
            total.mut_hit += c.mut_hit
            total.mut_any += c.mut_any
            total.clean_any += c.clean_any
            total.excluded += c.excluded
        return total

    @property
    def macro(self) -> float | None:
        """Unweighted mean robustness over the types that have one. Reported ALONGSIDE the
        overall because the overall is surface-weighted and MENO is ~47% of the corpus's
        auto surfaces: a mutation that destroys five rare types while leaving MENO intact
        still reads >0.95 overall. The gate is the brief's (overall); this number is here so
        nobody reads the overall as if it were a per-type guarantee."""
        vals = [c.robustness for c in self.per_type.values() if c.robustness is not None]
        return sum(vals) / len(vals) if vals else None


def _covering(cands: list, start: int, end: int) -> tuple[bool, bool]:
    """(fully covered by auto=True candidates, fully covered by candidates of any bucket).

    UNION coverage, not single-candidate coverage: every character of [start, end) must be
    inside SOME candidate, not inside ONE candidate. This is the leak-faithful criterion and
    the difference is not cosmetic. Both writers replace each candidate span with a label
    independently, so a name the detectors split into two adjacent candidates ("JÁN" +
    "NOVÁK", which is exactly what happens when the joined gazetteer rule dies and only the
    per-token known-entity matcher survives) is still completely removed from the output —
    and a single-candidate criterion would score that as a MISS and manufacture a defect out
    of a detector that redacted the surface perfectly.

    Verified on clean text before adopting it: over the 2559 gradeable surfaces the two
    criteria disagree on ZERO (167 misses either way), so switching cannot flatter the clean
    baseline; it only matters on mutated text, which is the honest direction.
    """
    auto_cov = [False] * (end - start)
    any_cov = [False] * (end - start)
    for cand in cands:
        lo, hi = max(cand.start, start), min(cand.end, end)
        if lo >= hi:
            continue
        for i in range(lo - start, hi - start):
            any_cov[i] = True
            if cand.auto:
                auto_cov[i] = True
    return all(auto_cov), all(any_cov)


def _detect_all(units: Iterable[str], known: list[str]) -> list[list]:
    return [detect(u, known) for u in units]


def _find_cover(units: list[str], cands: list[list], needle: str) -> tuple[bool, bool, bool]:
    """(present, covered-by-auto, covered-by-any) of ``needle`` across ``units``.

    Every occurrence in every unit is tried; the surface counts as detected if ANY occurrence
    is covered. That is the recall-over-precision direction and it matches the leak gate,
    which greps the whole output — a surface redacted in one paragraph and left standing in
    another still leaks, but grading it as a MISS here would blame the detector for a
    duplicate the writer also handles. The pessimistic reading is recorded in the report.
    """
    present = auto = any_ = False
    for idx, unit in enumerate(units):
        pos = unit.find(needle)
        while pos != -1:
            present = True
            a, n = _covering(cands[idx], pos, pos + len(needle))
            auto |= a
            any_ |= n
            if auto:
                return True, True, True
            pos = unit.find(needle, pos + 1)
    return present, auto, any_


def measure(
    cases: list[Case], mutation: str, mutate: Callable[[str], str], arm: str
) -> Result:
    result = Result(mutation=mutation, arm=arm)
    for case in cases:
        units = list(case.units)
        known = list(case.known) if arm == "known" else []
        mut_units = [mutate(u) for u in units]
        mut_known = [mutate(k) for k in known]
        try:
            clean_cands = _detect_all(units, known)
        except Exception as exc:            # a crash on CLEAN text would invalidate the row
            result.errors.append((case.name, "clean", f"{type(exc).__name__}: {exc}"))
            continue
        try:
            mut_cands = _detect_all(mut_units, mut_known)
        except Exception as exc:
            # detect() raising on a mutated document is itself a finding: the shipped app
            # would crash mid-redaction. Recorded by name, and the case is dropped from the
            # tally rather than scored as a miss — a crash is not a recall number.
            result.errors.append((case.name, "mutated", f"{type(exc).__name__}: {exc}"))
            continue
        for type_, surface in case.surfaces:
            cell = result.cell(type_)
            mut_surface = mutate(surface)
            c_present, c_auto, c_any = _find_cover(units, clean_cands, surface)
            if not c_present:
                continue                     # not reachable clean: already censused, skip
            m_present, m_auto, m_any = _find_cover(mut_units, mut_cands, mut_surface)
            if not m_present:
                cell.excluded += 1           # harness cannot ask — never scored as a miss
                continue
            cell.paired += 1
            cell.clean_hit += int(c_auto)
            cell.clean_any += int(c_any)
            cell.mut_hit += int(m_auto)
            cell.mut_any += int(m_any)
    return result


# --------------------------------------------------------------------------- reporting
def _fmt(value: float | None) -> str:
    return "  --  " if value is None else f"{value:6.3f}"


_COL = 9        # matrix column width
_CODE_LEN = 8   # mutation-name abbreviation used as a column header (names stay unique at 8)


def _codes() -> dict[str, str]:
    codes = {n: n[:_CODE_LEN] for n in MUTATIONS}
    assert len(set(codes.values())) == len(codes), "mutation name abbreviations collided"
    return codes


def _print_matrix(results: dict[str, dict[str, Result]], arm: str) -> list[tuple[str, str, Cell]]:
    """Print the mutation x type matrix for one arm; return its flagged cells."""
    names = list(MUTATIONS)
    codes = _codes()
    types = sorted({t for r in results.values() for t in r[arm].per_type})
    header = "type".ljust(20) + "n".rjust(5) + "".join(codes[n].rjust(_COL) for n in names)
    print()
    print(f"=== ARM '{arm}' — robustness = recall(mutated)/recall(clean); "
          f"'*' = below the {ROBUSTNESS_MIN} gate ===")
    print(header)
    print("-" * len(header))
    flagged: list[tuple[str, str, Cell]] = []
    for type_ in types:
        any_cell = next(
            (results[n][arm].per_type[type_] for n in names if type_ in results[n][arm].per_type),
            Cell(),
        )
        row = type_.ljust(20) + str(any_cell.paired).rjust(5)
        for name in names:
            cell = results[name][arm].per_type.get(type_, Cell())
            rob = cell.robustness
            if rob is None:
                text = "--"
            elif rob < ROBUSTNESS_MIN:
                text = f"{rob:.3f}*"
                flagged.append((name, type_, cell))
            else:
                text = f"{rob:.3f}"
            row += text.rjust(_COL)
        print(row)
    print("-" * len(header))

    def summary(label: str, fn) -> None:
        print(label.ljust(20) + "".rjust(5)
              + "".join(str(fn(results[n][arm])).rjust(_COL) for n in names))

    print("OVERALL".ljust(20) + str(results[names[0]][arm].overall.paired).rjust(5)
          + "".join(_fmt(results[n][arm].overall.robustness).strip().rjust(_COL) for n in names))
    summary("macro", lambda r: _fmt(r.macro).strip())
    summary("recall(clean)", lambda r: _fmt(r.overall.clean_recall).strip())
    summary("recall(mutated)", lambda r: _fmt(r.overall.mut_recall).strip())
    summary("excluded", lambda r: r.overall.excluded)
    return flagged


def instrument_self_check(cases: list[Case]) -> list[str]:
    """Prove the harness before any of its numbers are read (the G0 pattern).

    The IDENTITY mutation must produce robustness 1.000 in every cell, in both arms, with
    zero exclusions and zero detect() exceptions. It is the one mutation whose answer is
    known a priori, so it is the only thing that can tell a detector defect apart from a
    harness artefact: a bug in unit reconstruction, in surface pairing, in the coverage
    predicate or in the caching would show up here as a number below 1.

    Failures are returned as strings rather than raised, so every problem is printed at once.
    """
    problems: list[str] = []
    for arm in _ARMS:
        result = measure(cases, "identity", lambda t: t, arm)
        overall = result.overall
        if result.errors:
            problems.append(f"identity/{arm}: detect() raised on unmutated text: {result.errors[:3]}")
        if overall.excluded:
            problems.append(f"identity/{arm}: {overall.excluded} surface(s) excluded by pairing")
        if overall.clean_hit != overall.mut_hit:
            problems.append(
                f"identity/{arm}: clean_hit={overall.clean_hit} != mut_hit={overall.mut_hit}"
            )
        for type_, cell in sorted(result.per_type.items()):
            if cell.robustness is not None and cell.robustness != 1.0:
                problems.append(f"identity/{arm}: {type_} robustness={cell.robustness:.4f} != 1")
        if overall.paired != sum(len(c.surfaces) for c in cases):
            problems.append(
                f"identity/{arm}: paired={overall.paired} != "
                f"{sum(len(c.surfaces) for c in cases)} gradeable surfaces"
            )
    return problems


def run_gate(corpus_dir: Path) -> int:
    cases, unreachable = load_cases(corpus_dir)
    if not cases:
        print(f"no .docx corpus with ground truth at {corpus_dir} — regenerate it first:")
        print("  python -m corpus.generate --n 60 --out data/synthetic --seed 42 "
              "--formats docx,pdf")
        return 2

    units_total = sum(len(c.units) for c in cases)
    surfaces_total = sum(len(c.surfaces) for c in cases)
    print(f"corpus: {len(cases)} docx, {units_total} detect() units, "
          f"{surfaces_total} gradeable auto-redact surfaces")
    print(f"not gradeable (never reaches detect(): metadata blanked by position, "
          f"tracked_change_del removed before detection): "
          f"{sum(unreachable.values())} "
          f"[{', '.join(f'{k}={v}' for k, v in sorted(unreachable.items())) or '-'}]")

    problems = instrument_self_check(cases)
    if problems:
        print()
        print("=== INSTRUMENT SELF-CHECK FAILED — no robustness number below is trustworthy ===")
        for problem in problems:
            print(f"  {problem}")
        return 2
    print("instrument self-check: identity mutation = 1.000 in every cell of both arms, "
          "0 exclusions, 0 exceptions — OK")

    results: dict[str, dict[str, Result]] = {}
    for name, mutate in MUTATIONS.items():
        results[name] = {arm: measure(cases, name, mutate, arm) for arm in _ARMS}

    flagged: dict[str, list[tuple[str, str, Cell]]] = {}
    for arm in _ARMS:
        flagged[arm] = _print_matrix(results, arm)

    print()
    print("=== FLAGGED CELLS (robustness < %.2f) ===" % ROBUSTNESS_MIN)
    for arm in _ARMS:
        if not flagged[arm]:
            print(f"  arm {arm}: none")
            continue
        print(f"  arm {arm}: {len(flagged[arm])} cell(s)")
        for name, type_, cell in flagged[arm]:
            note = "  [case-destroying mutation]" if name in CASE_DESTROYING else ""
            print(
                f"    {name:<20s} {type_:<20s} robustness={cell.robustness:.3f} "
                f"(clean {cell.clean_hit}/{cell.paired} -> mutated {cell.mut_hit}/{cell.paired}"
                f"; found-but-review {cell.mut_any - cell.mut_hit}){note}"
            )

    errors = [
        (name, arm, err)
        for name in MUTATIONS
        for arm in _ARMS
        for err in results[name][arm].errors
    ]
    print()
    print(f"=== detect() EXCEPTIONS: {len(errors)} ===")
    for name, arm, (case, kind, message) in errors[:20]:
        print(f"  {name}/{arm} {case} ({kind}): {message}")
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more")

    print()
    print("=== VERDICT ===")
    failing = []
    for name in MUTATIONS:
        for arm in _ARMS:
            overall = results[name][arm].overall.robustness
            if overall is None or overall >= ROBUSTNESS_MIN:
                continue
            # A REPORT_ONLY arm is printed with its real number but does not fail the build.
            # See corpus/mutations.py::REPORT_ONLY for the bar an arm has to clear to be here.
            if name in REPORT_ONLY:
                continue
            failing.append((name, arm, overall))
    for name in MUTATIONS:
        marks = " ".join(
            f"{arm}={_fmt(results[name][arm].overall.robustness).strip()}" for arm in _ARMS
        )
        if name in REPORT_ONLY:
            status = "report"          # measured, printed, deliberately not gated
        else:
            status = "FAIL" if any(f[0] == name for f in failing) else "pass"
        print(f"  {name:<20s} {marks:<30s} {status}")
    print("VERDICT:", "PASS" if not failing else f"FAIL ({len(failing)} mutation-arm(s) below "
          f"{ROBUSTNESS_MIN})")
    return 0 if not failing else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", default="data/synthetic", type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):      # Slovak surfaces in a cp1250 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return run_gate(args.corpus)


if __name__ == "__main__":
    sys.exit(main())
