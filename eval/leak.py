"""§8.1 leak test (context.md §8) — the only test that truly matters.

For a redacted output: extract all text, then search for every ground-truth surface whose
GT flag is ``auto_redact=True``. Any hit is a HARD FAIL — the redactor left extractable PII
in the file. The classic bug it catches: drawing a black box over PDF text leaves the glyphs
underneath, so the box is theatre, not redaction.

``should_flag`` entries are NOT leaks — they go to the review bucket and may legitimately
remain. Decoys are not leaks either. A string that is auto_redact in one occurrence is a
real leak even if the same string also appears as a decoy elsewhere: recall governs.

Matching is by :func:`surface_present`: an occurrence of a target surface counts as present
UNLESS its exact character span falls entirely inside the exact span of a KNOWN decoy surface
recorded in this same document's ground truth (context.md rejection round 7, defect: the
leak test cannot tell a real leak from a surface merely embedded inside a longer, unrelated,
real Slovak word — e.g. "Kováč" is a literal substring of "Kováčska", blacksmith's, a real
adjective and a recorded CAPITALISED_COMMON decoy — but flagging every such embedding as a
leak makes it impossible for any redactor to pass the leak test while a stem-sharing decoy
survives).

**A prior version (round 6) tried to solve this with a character-class rule**: exclude a
match only when the adjacent character was a lowercase letter, reasoning that a live Slovak
morphological suffix is always lowercase. That rule was REJECTED — it is not decidable
lexically. ``"Novák"`` immediately followed by ``"nadobúda"`` (a real Slovak word, "acquires")
is character-for-character indistinguishable from ``"Novák"`` followed by ``"ovcov"`` (a real
declension, "of the Nováks"): both are a letter-starting lowercase continuation. Since DOCX
paragraph/run reconstruction has NO separator (context.md §10), a genuine leak glued to an
ordinary lowercase word is common, and the character-class rule silently misses it — the
exact split-run failure mode this whole project exists to catch. See
``tests/test_leak.py::test_surface_glued_to_a_lowercase_word_with_no_separator_is_still_present``,
which is RED under that rule and pinned permanently.

**The fix uses EXACT KNOWLEDGE instead of a character heuristic.** Ground truth already
names every decoy surface in this document. A target occurrence is excluded only when it
sits at a text position that is ENTIRELY WITHIN a decoy's OWN exact span — found by literal
substring search, not guessed from adjacent character class. This has no false-negative risk
on ordinary prose: "Novák" glued to "nadobúda" is not inside any decoy's span (there is no
decoy there at all), so it still counts as present. It only excludes a match when the
characters truly belong to a different, specifically-recorded, must-survive string.
"""
from __future__ import annotations

from dataclasses import dataclass

from .extract import ExtractResult


def _find_spans(text: str, surfaces: list[str]) -> list[tuple[int, int]]:
    """Every occurrence of every surface in ``text``, by exact character offset."""
    spans: list[tuple[int, int]] = []
    for s in surfaces:
        if not s:
            continue
        start = 0
        while True:
            idx = text.find(s, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(s)))
            start = idx + len(s)
    return spans


def surface_present(text: str, surface: str, decoy_surfaces: list[str] | None = None) -> bool:
    """True if ``surface`` occurs in ``text`` at a position that is not STRICTLY inside the
    exact span of one of ``decoy_surfaces``. With no decoy surfaces given, this is a plain,
    maximally paranoid substring check (context.md §6: recall over precision — a false
    positive costs a reviewer two seconds, a false negative is a data breach).

    "Strictly inside" requires the decoy span to be STRICTLY LONGER than the target span AND
    to fully cover it. A decoy span EQUAL to the target span never suppresses (context.md
    rejection round 8, defect: keying exclusion on ``d0 <= start and end <= d1`` alone also
    accepts ``d0 == start and d1 == end`` — a decoy string identical to a real auto_redact
    surface then blinds the leak gate to every occurrence of that string, letting a single
    corpus-generation mistake poison the test that is supposed to catch exactly this).
    """
    if not surface:
        return False
    decoy_spans = _find_spans(text, decoy_surfaces) if decoy_surfaces else []
    for start, end in _find_spans(text, [surface]):
        target_len = end - start
        if not any(
            d0 <= start and end <= d1 and (d1 - d0) > target_len for d0, d1 in decoy_spans
        ):
            return True
    return False


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

    Detection is by :func:`surface_present`: a redactor destroys the surface (replacing it
    with a label), so a surviving occurrence — outside any recorded decoy's own exact span —
    means the PII is still readable. Unit is the unique surface string — a plain text search
    cannot count occurrences once labels change offsets.
    """
    # Collect, per unique auto_redact surface, the GT parts it was recorded in.
    auto_parts: dict[tuple[str, str], set[str]] = {}
    for pii in gt["pii"]:
        if not pii["auto_redact"]:
            continue
        key = (pii["surface"], pii["type"])
        auto_parts.setdefault(key, set()).add(pii["location"]["surface_part"])

    decoy_surfaces = [
        pii["surface"] for pii in gt["pii"] if not pii["auto_redact"] and not pii["should_flag"]
    ]

    leaks: list[Leak] = []
    for (surface, ptype), parts in auto_parts.items():
        found_in = tuple(
            name for name, text in extracted.by_surface.items()
            if surface_present(text, surface, decoy_surfaces)
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
