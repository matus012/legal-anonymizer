"""§8.1 leak test (context.md §8) — the only test that truly matters.

For a redacted output: extract all text, then search for every ground-truth surface whose
GT flag is ``auto_redact=True``. Any hit is a HARD FAIL — the redactor left extractable PII
in the file. The classic bug it catches: drawing a black box over PDF text leaves the glyphs
underneath, so the box is theatre, not redaction.

``should_flag`` entries are NOT leaks — they go to the review bucket and may legitimately
remain. Decoys are not leaks either. A string that is auto_redact in one occurrence is a
real leak even if the same string also appears as a decoy elsewhere: recall governs.
"""
from __future__ import annotations

from dataclasses import dataclass

from .extract import ExtractResult


@dataclass(frozen=True)
class Leak:
    """One auto_redact surface still extractable from the redacted output."""
    surface: str
    type: str
    found_in: tuple[str, ...]   # physical surfaces where the string was found
    gt_parts: tuple[str, ...]   # surface_part(s) the ground truth expected it in


def _fmt_of(gt: dict) -> str:
    return "docx" if str(gt["source_file"]).lower().endswith(".docx") else "pdf"


def find_leaks(gt: dict, extracted: ExtractResult) -> list[Leak]:
    """Return one :class:`Leak` per unique auto_redact surface still present in ``extracted``.

    Detection is by substring presence: a redactor destroys the surface (replacing it with a
    label), so a surviving substring means the PII is still readable. Unit is the unique
    surface string — a plain text search cannot count occurrences once labels change offsets.
    """
    fmt = _fmt_of(gt)
    # Collect, per unique auto_redact surface, the GT parts it was recorded in.
    auto_parts: dict[tuple[str, str], set[str]] = {}
    for pii in gt["pii"]:
        if not pii["auto_redact"]:
            continue
        key = (pii["surface"], pii["type"])
        auto_parts.setdefault(key, set()).add(pii["location"]["surface_part"])

    leaks: list[Leak] = []
    for (surface, ptype), parts in auto_parts.items():
        found_in = tuple(
            name for name, text in extracted.by_surface.items() if surface in text
        )
        if found_in:
            leaks.append(
                Leak(
                    surface=surface,
                    type=ptype,
                    found_in=found_in,
                    gt_parts=tuple(sorted(parts)),
                )
            )
    return leaks
