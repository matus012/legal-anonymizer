"""Scan/decisions/export logic for the GUI — pure functions, no Qt, fully headless-testable.

Scan runs the REAL writer into a throwaway temp dir and harvests its LabelMap side-channels;
export re-runs the same writer with the reviewer's RedactionDecisions. Detection is
deterministic, so both runs see identical candidates — the review screen can never disagree
with the export (docs/superpowers/specs/2026-07-21-gui-design.md).
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from writer.decisions import RedactionDecisions
from writer.docx_body import redact_docx_collect
from writer.labelmap import LabelMap
from writer.pdf_body import NoTextLayerError, RedactionIncompleteError, redact_pdf_collect

SUPPORTED = {".docx", ".pdf"}

MSG_NO_TEXT_LAYER = (
    "Tento PDF nemá textovú vrstvu (pravdepodobne sken). Skeny v1 nepodporuje — súbor bol odmietnutý."
)
MSG_INCOMPLETE = (
    "Dokument sa nedá úplne redigovať automaticky ({n} nájditeľných miest zlyhalo). "
    "Súbor je z dávky vylúčený — spracujte ho manuálne."
)


@dataclass(frozen=True)
class ReviewRow:
    group: tuple            # (type, group_key) — the decision key
    type: str
    text: str               # representative surface (first occurrence)
    snippet: str
    locations: tuple[str, ...]
    count: int
    bucket: str             # "auto" (pre-ticked) | "review" (unticked)


@dataclass
class FileScan:
    src: str
    rows: list[ReviewRow]
    error: str | None = None


def out_path_for(src: str) -> str:
    root, ext = os.path.splitext(src)
    return f"{root}_anon{ext}"


def _collect(src: str, out: str, known, decisions) -> LabelMap:
    if src.lower().endswith(".docx"):
        return redact_docx_collect(src, out, known, decisions=decisions)
    return redact_pdf_collect(src, out, known, decisions=decisions)


def _rows_from(lm: LabelMap) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    for label, (type_, gkey) in lm.groups().items():
        occ = lm.occurrences.get(label, [])
        if not occ:
            continue  # defensive: label minted but nothing recorded
        rows.append(ReviewRow(
            group=(type_, gkey), type=type_, text=occ[0][1],
            snippet=lm.contexts.get(label, ""),
            locations=tuple(sorted({loc for loc, _s in occ})),
            count=len(occ), bucket="auto",
        ))
    # Low-confidence: dedup into groups the same way the writers key decisions.
    lc: dict[tuple, dict] = {}
    for i, (location, type_, surface) in enumerate(lm.low_confidence):
        key = (type_, lm.group_key_for(type_, surface))
        e = lc.setdefault(key, {"surface": surface, "snippet": lm.lc_contexts[i],
                                "locations": set(), "count": 0})
        e["locations"].add(location)
        e["count"] += 1
    for key, e in lc.items():
        rows.append(ReviewRow(
            group=key, type=key[0], text=e["surface"], snippet=e["snippet"],
            locations=tuple(sorted(e["locations"])), count=e["count"], bucket="review",
        ))
    return rows


def scan_file(src: str, known_entities, extra_terms: tuple[str, ...] = ()) -> FileScan:
    decisions = RedactionDecisions(extra_terms=extra_terms) if extra_terms else None
    with tempfile.TemporaryDirectory(prefix="anon_scan_") as tmp:
        out = os.path.join(tmp, "scan" + os.path.splitext(src)[1])
        try:
            lm = _collect(src, out, known_entities, decisions)
        except NoTextLayerError:
            return FileScan(src, [], MSG_NO_TEXT_LAYER)
        except RedactionIncompleteError as e:
            return FileScan(src, [], MSG_INCOMPLETE.format(n=len(e.surfaces)))
        return FileScan(src, _rows_from(lm))


def build_decisions(rows, checked: dict[tuple, bool], extra_terms) -> RedactionDecisions:
    """checked maps group -> ticked?  Unticked auto row -> suppress; ticked review row -> force."""
    suppress = frozenset(r.group for r in rows if r.bucket == "auto" and not checked.get(r.group, True))
    force = frozenset(r.group for r in rows if r.bucket == "review" and checked.get(r.group, False))
    return RedactionDecisions(extra_terms=tuple(extra_terms), suppress_groups=suppress, force_groups=force)


def export_file(src: str, known_entities, decisions: RedactionDecisions) -> tuple[str, str]:
    """Redact ``src`` next to itself as <stem>_anon.<ext>; returns (out_path, report_path).
    Raises the writer's own errors — the caller (worker) turns them into per-file messages.

    On RedactionIncompleteError the PDF writer has ALREADY saved a partially redacted
    output (+ report) before raising — a file a non-technical user must never find lying
    next to the source (context.md §3: never silently produce an unredacted file). Delete
    both, then re-raise so the UI shows the per-file failure."""
    out = out_path_for(src)
    root, _ = os.path.splitext(out)
    report = f"{root}_report.txt"
    try:
        _collect(src, out, known_entities, decisions)
    except RedactionIncompleteError:
        for p in (out, report):
            if os.path.exists(p):
                os.remove(p)
        raise
    return out, report
