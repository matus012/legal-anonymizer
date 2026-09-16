"""Scan/decisions/export logic for the GUI — pure functions, no Qt, fully headless-testable.

Scan runs the REAL writer into a throwaway temp dir and harvests its LabelMap side-channels;
export re-runs the same writer with the reviewer's RedactionDecisions. Detection is
deterministic, so both runs see identical candidates — the review screen can never disagree
with the export (docs/superpowers/specs/2026-07-21-gui-design.md).
"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass

from detect.config import DetectConfig
from writer.decisions import RedactionDecisions
from writer.docx_body import redact_docx_collect
from writer.labelmap import LabelMap
from writer.pdf_body import NoTextLayerError, RedactionIncompleteError, redact_pdf_collect
from writer.report import report_path_for

SUPPORTED = {".docx", ".pdf"}

MSG_NO_TEXT_LAYER = (
    "Tento PDF nemá textovú vrstvu (pravdepodobne sken). Skeny v1 nepodporuje — súbor bol odmietnutý."
)
MSG_INCOMPLETE = (
    "Dokument sa nedá úplne redigovať automaticky ({n} nájditeľných miest zlyhalo). "
    "Súbor je z dávky vylúčený — spracujte ho manuálne."
)
MSG_DETECTOR_FAILED = (
    "POZOR: časť rozpoznávania na tomto dokumente ZLYHALA ({names}). Čo by tieto\n"
    "detektory našli, NIE JE v tabuľke nižšie a NEBUDE odstránené. Dokument\n"
    "skontrolujte ručne a chybu nahláste správcovi."
)
MSG_FILENAME_LEAK = (
    "Pozor: názov tohto súboru obsahuje osobný údaj ({names}). Redigovaný dokument sa volá "
    "rovnako, takže údaj uniká už v názve prílohy. Zapnite „Anonymizovať názvy súborov“ "
    "v Rozšírených nastaveniach, alebo súbor pred odoslaním premenujte."
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
    # v1.1 (CONTRACTS_v11.md §1/§10): the detector's checksum TAG for this group —
    # "valid" | "invalid" | "n/a". A review column only; it never decides the bucket.
    checksum: str = "n/a"


@dataclass
class FileScan:
    src: str
    rows: list[ReviewRow]
    error: str | None = None
    # v1.1 Phase F: representative surfaces that also occur in the SOURCE FILENAME. The
    # redaction cleans the document body and then writes `Novak_zmluva_anon.docx` — the
    # leak walks out in the attachment name. Carried here so the review screen can say so.
    filename_hits: tuple[str, ...] = ()
    # v1.1 crash safety (CONTRACTS_v11.md Amendment 11): detectors that RAISED during the
    # scan, as (detector, location, error). This is the ONE case where the review table
    # cannot be trusted to be complete -- the rows a failed detector would have produced
    # are simply absent, and absent rows look exactly like a clean document. The screen
    # must say so out loud; silence here is the failure mode.
    detector_failures: tuple[tuple[str, str, str], ...] = ()


# Tokens worth testing against a filename: ≥3 chars, letters/digits only after folding.
# Shorter runs ("a", "ul") match half the filenames in a law office and would make the
# warning noise, which is the only way to make a warning worse than not having one.
_TOKEN_RE = re.compile(r"[0-9a-z]{3,}")


def _fold(s: str) -> str:
    """Lowercase + drop combining marks: `Ján Novák` -> `jan novak`. A filename is typed by a
    human who almost never types the diacritics, so an unfolded comparison misses the case
    the whole feature exists for."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(ch)
    )


def filename_leak_hits(src: str, rows) -> tuple[str, ...]:
    """Surfaces from ``rows`` whose folded tokens appear in ``src``'s stem, in row order.

    Token-level, not substring-level: the document says `Ján Novák` and the file is called
    `Novak_kupna_zmluva.docx`, so whole-surface containment finds nothing. Deliberately
    over-matches (recall over precision, context.md §6) — a false warning costs one glance."""
    stem = _fold(os.path.splitext(os.path.basename(src))[0])
    return tuple(
        r.text for r in rows
        if any(tok in stem for tok in _TOKEN_RE.findall(_fold(r.text)))
    )


def out_path_for(src: str, index: int | None = None, anonymize_names: bool = False) -> str:
    """The single place that decides an output path.

    ``anonymize_names`` + a 1-based ``index`` replaces the stem entirely with ``doc_NNN``,
    because `<stem>_anon.docx` faithfully preserves whatever PII the lawyer's own filename
    carried. The mapping back to the original name lives in the report's MANIFEST section.
    Flag off (the default) is the v1 rule, unchanged, index or no index."""
    root, ext = os.path.splitext(src)
    if anonymize_names and index is not None:
        return os.path.join(os.path.dirname(src), f"doc_{index:03d}_anon{ext}")
    return f"{root}_anon{ext}"


def _collect(src: str, out: str, known, decisions, config: DetectConfig | None = None) -> LabelMap:
    if src.lower().endswith(".docx"):
        return redact_docx_collect(src, out, known, decisions=decisions, config=config)
    return redact_pdf_collect(src, out, known, decisions=decisions, config=config)


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
            checksum=lm.checksums.get(label, "n/a"),
        ))
    # Low-confidence: dedup into groups the same way the writers key decisions. Snippet AND
    # checksum both come from the group's FIRST record (setdefault), matching the auto rows'
    # first-seen-wins rule.
    lc: dict[tuple, dict] = {}
    for i, (location, type_, surface) in enumerate(lm.low_confidence):
        key = (type_, lm.group_key_for(type_, surface))
        e = lc.setdefault(key, {"surface": surface, "snippet": lm.lc_contexts[i],
                                "checksum": lm.lc_checksums[i] if i < len(lm.lc_checksums) else "n/a",
                                "locations": set(), "count": 0})
        e["locations"].add(location)
        e["count"] += 1
    for key, e in lc.items():
        rows.append(ReviewRow(
            group=key, type=key[0], text=e["surface"], snippet=e["snippet"],
            locations=tuple(sorted(e["locations"])), count=e["count"], bucket="review",
            checksum=e["checksum"],
        ))
    return rows


def scan_file(src: str, known_entities, extra_terms: tuple[str, ...] = (),
              config: DetectConfig | None = None) -> FileScan:
    decisions = RedactionDecisions(extra_terms=extra_terms) if extra_terms else None
    with tempfile.TemporaryDirectory(prefix="anon_scan_") as tmp:
        out = os.path.join(tmp, "scan" + os.path.splitext(src)[1])
        try:
            lm = _collect(src, out, known_entities, decisions, config)
        except NoTextLayerError:
            return FileScan(src, [], MSG_NO_TEXT_LAYER)
        except RedactionIncompleteError as e:
            return FileScan(src, [], MSG_INCOMPLETE.format(n=len(e.surfaces)))
        rows = _rows_from(lm)
        return FileScan(src, rows, filename_hits=filename_leak_hits(src, rows),
                        detector_failures=tuple(lm.detector_failures))


def build_decisions(rows, checked: dict[tuple, bool], extra_terms) -> RedactionDecisions:
    """checked maps group -> ticked?  Unticked auto row -> suppress; ticked review row -> force."""
    suppress = frozenset(r.group for r in rows if r.bucket == "auto" and not checked.get(r.group, True))
    force = frozenset(r.group for r in rows if r.bucket == "review" and checked.get(r.group, False))
    return RedactionDecisions(extra_terms=tuple(extra_terms), suppress_groups=suppress, force_groups=force)


MANIFEST_HEADER = "[MANIFEST — VÝSTUPNÝ NÁZOV -> PÔVODNÝ SÚBOR]"
_MANIFEST_COLS = "výstup | pôvodný súbor"


def _append_manifest(report: str, manifest) -> None:
    """Append the batch's output-name -> original-name table to an ALREADY WRITTEN report.

    Appended rather than passed into ``writer.report.build_report`` on purpose: the manifest
    is a GUI-batch fact (it needs the other files in the batch), and build_report's output is
    contractually byte-stable (CONTRACTS_v11.md §10). The report already lists un-redacted
    low-confidence surfaces, so it was never a file to send anywhere — the original filenames
    do not change that posture."""
    lines = ["", MANIFEST_HEADER, _MANIFEST_COLS]
    lines += [f"{out_name} | {original}" for out_name, original in manifest]
    with open(report, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def export_file(src: str, known_entities, decisions: RedactionDecisions,
                config: DetectConfig | None = None, *, index: int | None = None,
                anonymize_names: bool = False, manifest=None) -> tuple[str, str]:
    """Redact ``src`` next to itself as <stem>_anon.<ext>; returns (out_path, report_path).

    ``index`` / ``anonymize_names`` are handed to ``out_path_for``; ``manifest`` (an iterable
    of ``(output_name, original_name)``) is appended to the report. All three default to the
    off value, so an unchanged call is byte-identical to v1.

    Raises the writer's own errors — the caller (worker) turns them into per-file messages.

    On RedactionIncompleteError the PDF writer has ALREADY saved a partially redacted
    output (+ report) before raising — a file a non-technical user must never find lying
    next to the source (context.md §3: never silently produce an unredacted file). Delete
    both, then re-raise so the UI shows the per-file failure."""
    out = out_path_for(src, index, anonymize_names)
    # The report path is the writer's OWN rule, called — not re-derived here. Duplicating it is
    # exactly how the v1.1 Phase F collision fix would have missed this cleanup path and left a
    # stale report from a failed export lying next to the source.
    report = report_path_for(out)
    try:
        _collect(src, out, known_entities, decisions, config)
    except RedactionIncompleteError:
        for p in (out, report):
            if os.path.exists(p):
                os.remove(p)
        raise
    if manifest:
        _append_manifest(report, manifest)
    return out, report
