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
# v1.1 crash safety (CONTRACTS_v11.md Amendment 11). A detector that raised on this document
# produced NO candidates for the unit it raised on, so the document may be UNDER-REDACTED in a
# way nothing else in this report shows: the missing rows look exactly like "there was nothing
# there". This block therefore sits ABOVE the redaction tables, not below them, and is emitted
# only when there is something to say -- a warning that appears on every clean document is a
# warning nobody reads.
_FAILURE_HEADER = "[!! DETECTOR FAILURES -- THIS DOCUMENT MAY BE UNDER-REDACTED !!]"
_FAILURE_COLS = _SEP.join(["detector", "location", "error"])
# Red-team round 6 (R6-10). A surface detect() marked auto=True that search_for could not
# locate -- or located with a degenerate, zero-width rect -- is STILL IN THE DOCUMENT, and the
# pass reaches ``continue`` before record_occurrence, with record_low_confidence on the other
# branch. So the document that is under-redacted produced the report of a document in which
# nothing was found: the reviewer's only signal was an exception the GUI may have logged and
# they may never see. Same framing and same position as the detector-failure block above,
# because it is the same class of fact -- something is missing from the tables below -- and
# emitted only when there is something to say.
_UNLOCATED_HEADER = "[!! NOT REDACTED -- THIS DOCUMENT MAY BE UNDER-REDACTED !!]"
_UNLOCATED_COLS = _SEP.join(["type", "surface", "location"])
_UNLOCATED_NOTE = (
    "These surfaces WERE detected as personal data and the tool FAILED to remove them:\n"
    "it could not find them on the page, or found only part of them. They are still in\n"
    "the document, unlabelled and unmarked. Remove them by hand before sharing this file."
)
_FAILURE_NOTE = (
    "One or more detectors could not run on part of this document. Whatever they would\n"
    "have found is NOT in the table below and was NOT removed. Review those locations by\n"
    "hand before sharing this file, and report the error text to the maintainer."
)
# v1.1 checksum column (CONTRACTS_v11.md §10) — appended ONLY when the caller supplies the
# matching side-channel, so the v1 layout is reproduced byte-for-byte when it is omitted.
_CHECKSUM_COL = "checksum"
_NA = "n/a"


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
    checksums: dict[str, str] | None = None,
    lc_checksums: list[str] | None = None,
    detector_failures: list[tuple[str, str, str]] | None = None,
    unlocated: list[tuple[str, str, str]] | None = None,
) -> str:
    """Pure formatter — no I/O. Return the deterministic report string for the two captures.

    ``occurrences``: label -> [(location, surface), ...] (repeats included; count = len).
    ``low_confidence``: [(location, type, surface), ...] in capture order.

    v1.1 (CONTRACTS_v11.md §10): ``checksums`` (label -> checksum) and ``lc_checksums``
    (index-aligned with ``low_confidence``) are the OPTIONAL checksum side-channels. When a
    side-channel is given, a ``checksum`` column is appended to that table — header included.
    When BOTH are omitted the output is byte-identical to v1: the column is not emitted at
    all, so no existing report, test or diff shifts by a single byte. A label/index missing
    from a supplied side-channel reads ``"n/a"`` rather than raising — a report must never be
    the thing that crashes a redaction pass.

    ``detector_failures``: [(detector, location, error), ...]. When non-empty a WARNING BLOCK
    is emitted ABOVE the redaction tables. When omitted or empty nothing is emitted and the
    output is byte-identical to a report without the parameter -- same discipline as the
    checksum side-channels above, for the same reason: a v1 report, test or diff must not
    shift by a byte because a v1.1 feature exists.

    ``unlocated``: [(location, type, surface), ...] -- auto=True surfaces the pass could not
    remove (red-team round 6, R6-10). Emitted as a WARNING BLOCK above the tables, under the
    same omitted-means-byte-identical discipline as the two side-channels above.
    """
    lines: list[str] = [_HEADER]

    # Section 0 DETECTOR FAILURES -- first, because it changes how the rest should be read.
    if detector_failures:
        lines.append(_FAILURE_HEADER)
        lines.append(_FAILURE_NOTE)
        lines.append(_FAILURE_COLS)
        for detector, location, error in detector_failures:
            lines.append(_SEP.join([detector, location, error]))
        lines.append("")

    # Section 0b NOT REDACTED -- above the tables for the same reason as section 0: what is
    # missing from them is the thing the reviewer must act on.
    if unlocated:
        lines.append(_UNLOCATED_HEADER)
        lines.append(_UNLOCATED_NOTE)
        lines.append(_UNLOCATED_COLS)
        for location, type_, surface in unlocated:
            lines.append(_SEP.join([type_, surface, location]))
        lines.append("")

    lines.append(_REDACTED_HEADER)

    # Section 1 REDACTED: one row per label, sorted by (TYPE, numeric N).
    lines.append(_REDACTED_COLS if checksums is None else _SEP.join([_REDACTED_COLS, _CHECKSUM_COL]))
    for label in sorted(occurrences, key=_type_and_number):
        type_, _n = _type_and_number(label)
        occ = occurrences[label]
        count = len(occ)  # all locations, repeats counted
        locations = ", ".join(sorted({loc for loc, _surface in occ}))  # sorted set
        row = [type_, label, str(count), locations]
        if checksums is not None:
            row.append(checksums.get(label, _NA))
        lines.append(_SEP.join(row))

    # Section 2 LOW CONFIDENCE / NOT REDACTED: capture (list) order, "(none)" when empty.
    lines.append("")
    lines.append(_LOWCONF_HEADER)
    lines.append(_LOWCONF_COLS if lc_checksums is None else _SEP.join([_LOWCONF_COLS, _CHECKSUM_COL]))
    if low_confidence:
        for i, (location, type_, surface) in enumerate(low_confidence):
            row = [type_, surface, location]
            if lc_checksums is not None:
                row.append(lc_checksums[i] if i < len(lc_checksums) else _NA)
            lines.append(_SEP.join(row))
    else:
        lines.append(_NONE)

    return "\n".join(lines) + "\n"


def report_path_for(out_path: str) -> str:
    """The report path DERIVED from ``out_path``: same directory, filename = out_path stem +
    "_" + the source extension (no dot) + "_report.txt"
    (foo_anon.docx -> foo_anon_docx_report.txt, foo_anon.pdf -> foo_anon_pdf_report.txt).

    v1.1 Phase F: the extension is IN the report name because a batch exporting zmluva.docx and
    zmluva.pdf produced two outputs with the same stem, and the v1 rule (stem + "_report.txt")
    gave both the SAME report path — the second export silently overwrote the first, destroying
    the record of a document that had just been redacted. An out_path with no extension keeps
    the v1 name (there is no format to disambiguate). One source of truth — never a param."""
    directory = os.path.dirname(out_path)
    stem, ext = os.path.splitext(os.path.basename(out_path))
    suffix = f"_{ext[1:]}_report.txt" if ext[1:] else "_report.txt"
    return os.path.join(directory, stem + suffix)


def write_report(
    out_path: str,
    occurrences: dict[str, list[tuple[str, str]]],
    low_confidence: list[tuple[str, str, str]],
    checksums: dict[str, str] | None = None,
    lc_checksums: list[str] | None = None,
    detector_failures: list[tuple[str, str, str]] | None = None,
    unlocated: list[tuple[str, str, str]] | None = None,
) -> str:
    """Build the report and write it as UTF-8 next to ``out_path`` (path via ``report_path_for``).
    Returns the written path. This is the only entry point the writer calls."""
    path = report_path_for(out_path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            build_report(
                occurrences, low_confidence, checksums, lc_checksums, detector_failures,
                unlocated,
            )
        )
    return path
