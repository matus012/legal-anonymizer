"""§8.2 metrics (context.md §8) — per-PII-type recall / precision, reported per type.

Recall is the headline number and is **never averaged across types**: a weak detector on one
type must be visible, not hidden in a mean. The three ground-truth classes are reported
separately (context.md §7 three-state decision):

* ``auto_redact``  → must be redacted. recall = fraction removed from the output.
* ``decoy``        → must NOT be redacted. a redacted decoy is a precision failure.
* ``should_flag``  → must reach the review bucket; may legitimately remain in the document.

Detection is by substring presence in the extracted text — the same primitive as the leak
test. A redactor destroys a surface (replacing it with a label), so a surviving substring
means "not removed". The unit is the unique surface string per document: a plain text search
cannot count occurrences once redaction labels change offsets. This is pessimistic about
recall when one inflected form is a substring of another still present — the safe direction
(context.md §6, recall over precision).

Review-bucket grading for ``should_flag`` needs the redactor's report artifact, which does
not exist at this build stage (context.md §11, step 2 precedes the detectors). ``evaluate``
accepts an optional ``flagged`` set per document so it is ready the moment a report format
lands; until then it reports raw retention.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .extract import ExtractResult


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
    def precision(self) -> float | None:
        """auto_removed / (auto_removed + decoy_removed): of everything this type redacted,
        the fraction that should have been. ``None`` when the type redacted nothing."""
        redacted = self.auto_removed + self.decoy_removed
        return None if redacted == 0 else self.auto_removed / redacted


@dataclass
class CorpusMetrics:
    per_type: dict[str, TypeMetrics] = field(default_factory=dict)
    files_total: int = 0
    files_opened: int = 0

    @property
    def formatting_integrity(self) -> float:
        """Fraction of output files that opened and extracted without error (§8.2)."""
        return 1.0 if self.files_total == 0 else self.files_opened / self.files_total


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
) -> CorpusMetrics:
    """Score a corpus.

    ``graded`` pairs each ground-truth dict with the extraction of its redacted output.
    ``flagged`` optionally maps ``source_file`` -> the set of surfaces the redactor sent to
    its review bucket, enabling should_flag review-bucket coverage once a report exists.
    """
    metrics = CorpusMetrics()
    flagged = flagged or {}

    def bucket(ptype: str) -> TypeMetrics:
        return metrics.per_type.setdefault(ptype, TypeMetrics(type=ptype))

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
