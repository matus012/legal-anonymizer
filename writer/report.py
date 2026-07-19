"""W5b-2 Step 1 (context.md §9 / "The report file"): the per-document <stem>_report.txt.

This is an ADDITIVE side-effect of a redaction pass — it reads the LabelMap the pass populated
(``occurrences`` + ``low_confidence``) and writes a plain-text record NEXT TO the redacted file.
It changes NO redaction behaviour, NO label string and NONE of the redacted .docx bytes.

Two layers, split so the formatting is unit-testable without touching disk:

  * ``build_report`` is PURE (no I/O): it turns the two capture structures into one deterministic
    UTF-8 string. REDACTED rows are sorted by (TYPE, numeric N) — the number is parsed as an int,
    so [MENO_2] precedes [MENO_10] (a lexical sort would invert them) and types group together.
    LOW CONFIDENCE rows stay in capture (list) order — that is the document order a reviewer
    reads in — and an empty section prints an explicit "(none)" rather than a blank block.
  * ``write_report`` DERIVES the report path from ``out_path`` (same dir, stem + "_report.txt"),
    so the report can never desync from the document it describes, and writes ``build_report``'s
    string as UTF-8.

Liability posture (context.md): the report is a record of what the tool CHANGED and what it was
UNSURE about — it does NOT certify the document is clean. The human review step is required.
"""
from __future__ import annotations

import os

# Literal section markers. Kept as module constants so callers/tests can locate sections without
# depending on surrounding layout. Columns are delimited by " | " — deterministic, no padding.
_SEP = " | "
_HEADER = (
    "=== LEGAL ANONYMIZER — REDACTION REPORT ===\n"
    "\n"
    "This report records what the tool CHANGED and what it was UNSURE about.\n"
    "It does NOT certify that the document is clean. A human must review the\n"
    "redacted document before it is shared or filed.\n"
)
_REDACTED_HEADER = "[REDACTED]"
_REDACTED_COLS = _SEP.join(["TYPE", "label", "count", "locations"])
_LOWCONF_HEADER = "[LOW CONFIDENCE / NOT REDACTED]"
_LOWCONF_COLS = _SEP.join(["type", "surface", "location"])
_NONE = "(none)"


def _type_and_number(label: str) -> tuple[str, int]:
    """Recover (TYPE, N) from a "[TYPE_N]" label. Strip the outer brackets, then rsplit on "_"
    exactly ONCE and take the left part — so a multi-underscore TYPE ("[RODNE_CISLO_1]") yields
    ("RODNE_CISLO", 1), never ("RODNE", ...) from a first-"_" split. N is int for numeric sort."""
    inner = label[1:-1] if label.startswith("[") and label.endswith("]") else label
    type_, n_str = inner.rsplit("_", 1)
    return type_, int(n_str)


def build_report(
    occurrences: dict[str, list[tuple[str, str]]],
    low_confidence: list[tuple[str, str, str]],
) -> str:
    """Pure formatter — no I/O. Return the deterministic report string for the two captures.

    ``occurrences``: label -> [(location, surface), ...] (repeats included; count = len).
    ``low_confidence``: [(location, type, surface), ...] in capture order.
    """
    lines: list[str] = [_HEADER, _REDACTED_HEADER, _REDACTED_COLS]

    # Section 1 REDACTED: one row per label, sorted by (TYPE, numeric N).
    for label in sorted(occurrences, key=_type_and_number):
        type_, _n = _type_and_number(label)
        occ = occurrences[label]
        count = len(occ)  # all locations, repeats counted
        locations = ", ".join(sorted({loc for loc, _surface in occ}))  # sorted set
        lines.append(_SEP.join([type_, label, str(count), locations]))

    # Section 2 LOW CONFIDENCE / NOT REDACTED: capture (list) order, "(none)" when empty.
    lines.append("")
    lines.append(_LOWCONF_HEADER)
    lines.append(_LOWCONF_COLS)
    if low_confidence:
        for location, type_, surface in low_confidence:
            lines.append(_SEP.join([type_, surface, location]))
    else:
        lines.append(_NONE)

    return "\n".join(lines) + "\n"


def report_path_for(out_path: str) -> str:
    """The report path DERIVED from ``out_path``: same directory, filename = out_path stem +
    "_report.txt" (foo_anon.docx -> foo_anon_report.txt). One source of truth — never a param."""
    directory = os.path.dirname(out_path)
    stem = os.path.splitext(os.path.basename(out_path))[0]
    return os.path.join(directory, stem + "_report.txt")


def write_report(
    out_path: str,
    occurrences: dict[str, list[tuple[str, str]]],
    low_confidence: list[tuple[str, str, str]],
) -> str:
    """Build the report and write it as UTF-8 next to ``out_path`` (path via ``report_path_for``).
    Returns the written path. This is the only entry point the writer calls."""
    path = report_path_for(out_path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_report(occurrences, low_confidence))
    return path
