"""§8.2 metrics (context.md §8) — per-PII-type recall / decoy-survival / flag-survival.

Recall is the headline number and is **never averaged across types**: a weak detector on one
type must be visible, not hidden in a mean. The three ground-truth classes are reported
separately (context.md §7 three-state decision), and each has its own per-type metric — none
of them are aggregated into a single corpus-wide figure that could hide a type-specific
failure:

* ``auto_redact``  → must be redacted. ``recall`` = fraction removed from the output.
* ``decoy``        → must NOT be redacted. ``decoy_survival`` = fraction still present.
* ``should_flag``  → must reach the review bucket, i.e. survive in the output (never
  auto-redacted) — checksum-invalid RČ/IČO/IBAN are the §4.1 hard negatives this exists to
  protect. ``flag_survival`` = fraction still present.

There is no per-type "precision" metric. It was deleted (context.md rejection round 2,
defect D4): decoys are always recorded under a DIFFERENT type from the auto-redact type they
mimic (e.g. ``ARTICLE_NO`` decoys never share a type with ``RODNE_CISLO``), so a type's own
``decoy_total`` is always 0 and the old formula (``auto_removed / (auto_removed +
decoy_removed)``) degenerated to exactly ``recall`` under a second name for every real type —
a scorched corpus that destroyed every decoy still read "100% precision" on all 21 real
types. ``decoy_survival`` (per type, gated in ``eval/run.py``) is the only honest precision
proxy this harness has.

Detection is by substring presence in the extracted text — the same primitive as the leak
test. A redactor destroys a surface (replacing it with a label), so a surviving substring
means "not removed". The unit is the unique surface string per document: a plain text search
cannot count occurrences once redaction labels change offsets. This is pessimistic about
recall when one inflected form is a substring of another still present — the safe direction
(context.md §6, recall over precision).

``flagged``/``flag_in_review`` are reserved for the redactor's own review-bucket report
artifact, which does not exist at this build stage (context.md §11, step 2 precedes the
detectors) — ``flag_survival`` (raw "is it still in the output text at all") is what's gated
until that report format lands.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .extract import ExtractResult
from .retention import score as retention_score


@dataclass
class TypeMetrics:
    """Per-PII-type tallies over the corpus. Unit: unique surface string per document."""
    type: str
    auto_total: int = 0
    auto_removed: int = 0
    decoy_total: int = 0
    decoy_preserved: int = 0
    flag_total: int = 0
    flag_retained: int = 0
    flag_in_review: int = 0

    @property
    def recall(self) -> float | None:
        """Fraction of auto_redact surfaces removed. ``None`` when the type has none."""
        return None if self.auto_total == 0 else self.auto_removed / self.auto_total

    @property
    def decoy_removed(self) -> int:
        return self.decoy_total - self.decoy_preserved

    @property
    def decoy_survival(self) -> float | None:
        """Fraction of this type's decoys (must NOT be redacted) still present in the output.
        ``None`` when the type has no decoys. Gated per type in ``eval/run.py`` (defect D6) —
        a detector that eats 100%% of one decoy class must not hide inside a corpus-wide sum."""
        return None if self.decoy_total == 0 else self.decoy_preserved / self.decoy_total

    @property
    def flag_survival(self) -> float | None:
        """Fraction of this type's should_flag surfaces (checksum-invalid — must reach the
        review bucket, never be auto-redacted) still present in the output. ``None`` when the
        type has none. Gated per type in ``eval/run.py`` at 100%% (defect D5): any loss here
        is a checksum-invalid RČ/IČO/IBAN silently auto-redacted, exactly what §4.1 forbids."""
        return None if self.flag_total == 0 else self.flag_retained / self.flag_total


@dataclass
class CorpusMetrics:
    per_type: dict[str, TypeMetrics] = field(default_factory=dict)
    files_total: int = 0
    files_opened: int = 0
    retention_survived: int = 0
    retention_total: int = 0

    @property
    def formatting_integrity(self) -> float:
        """Fraction of output files that opened and extracted without error (§8.2)."""
        return 1.0 if self.files_total == 0 else self.files_opened / self.files_total

    @property
    def retention(self) -> float | None:
        """§8.3 retention gate: fraction of non-PII tokens surviving in the output, aggregated
        over the whole corpus. ``None`` when no originals were supplied (gate not computed) or
        every document was entirely PII (denominator zero) — never silently 0%%."""
        return None if self.retention_total == 0 else self.retention_survived / self.retention_total

    @property
    def decoy_total(self) -> int:
        return sum(t.decoy_total for t in self.per_type.values())

    @property
    def decoy_preserved(self) -> int:
        return sum(t.decoy_preserved for t in self.per_type.values())

    @property
    def decoy_survival(self) -> float | None:
        """Corpus-wide decoy survival, for the report line only — NOT what's gated. A
        detector that eats 100%% of one decoy class while preserving the rest would still
        read fine in this aggregate; the actual gate (``EvalOutcome.decoy_survival_ok`` in
        ``eval/run.py``) checks every ``TypeMetrics.decoy_survival`` individually (defect D6).
        ``None`` when the corpus has no decoys."""
        return None if self.decoy_total == 0 else self.decoy_preserved / self.decoy_total


def _unique_by_class(gt: dict) -> dict[str, dict[str, set[str]]]:
    """{class: {type: {surface, ...}}} deduped within the document. A surface that is
    auto_redact in any occurrence is counted as auto (recall governs, context.md §6)."""
    auto: dict[str, set[str]] = {}
    flag: dict[str, set[str]] = {}
    decoy: dict[str, set[str]] = {}
    for pii in gt["pii"]:
        if pii["auto_redact"]:
            auto.setdefault(pii["type"], set()).add(pii["surface"])
        elif pii["should_flag"]:
            flag.setdefault(pii["type"], set()).add(pii["surface"])
        else:
            decoy.setdefault(pii["type"], set()).add(pii["surface"])
    # A string counted as auto must not be double-counted as flag/decoy for the same type.
    for ptype, surfaces in auto.items():
        flag.get(ptype, set()).difference_update(surfaces)
        decoy.get(ptype, set()).difference_update(surfaces)
    return {"auto": auto, "flag": flag, "decoy": decoy}


def evaluate(
    graded: list[tuple[dict, ExtractResult]],
    *,
    files_total: int | None = None,
    files_opened: int | None = None,
    flagged: dict[str, set[str]] | None = None,
    originals: list[ExtractResult] | None = None,
) -> CorpusMetrics:
    """Score a corpus.

    ``graded`` pairs each ground-truth dict with the extraction of its redacted output.
    ``flagged`` optionally maps ``source_file`` -> the set of surfaces the redactor sent to
    its review bucket, enabling should_flag review-bucket coverage once a report exists.
    ``originals``, if given, is the pre-redaction extraction of each ``graded`` entry in the
    same order — required to compute the §8.3 retention gate (:attr:`CorpusMetrics.retention`).
    """
    metrics = CorpusMetrics()
    flagged = flagged or {}

    def bucket(ptype: str) -> TypeMetrics:
        return metrics.per_type.setdefault(ptype, TypeMetrics(type=ptype))

    if originals is not None:
        if len(originals) != len(graded):
            raise ValueError("originals must be the same length as graded, same order")
        for (gt, res), original in zip(graded, originals):
            survived, total = retention_score(gt, original, res)
            metrics.retention_survived += survived
            metrics.retention_total += total

    for gt, res in graded:
        classes = _unique_by_class(gt)
        review = flagged.get(gt["source_file"], set())
        for ptype, surfaces in classes["auto"].items():
            tm = bucket(ptype)
            for s in surfaces:
                tm.auto_total += 1
                if s not in res.full_text:
                    tm.auto_removed += 1
        for ptype, surfaces in classes["decoy"].items():
            tm = bucket(ptype)
            for s in surfaces:
                tm.decoy_total += 1
                if s in res.full_text:
                    tm.decoy_preserved += 1
        for ptype, surfaces in classes["flag"].items():
            tm = bucket(ptype)
            for s in surfaces:
                tm.flag_total += 1
                if s in res.full_text:
                    tm.flag_retained += 1
                if s in review:
                    tm.flag_in_review += 1

    n = len(graded)
    metrics.files_total = n if files_total is None else files_total
    metrics.files_opened = n if files_opened is None else files_opened
    return metrics
