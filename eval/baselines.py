"""Baseline "redactors" that grade the harness itself (context.md §8, steps 4 & 5).

None are real detectors — they exist so the test suite can prove the eval harness can
actually FAIL, and fail for the right reason. Each drives a known, deliberate failure mode.
The harness verdict is a vector of the seven booleans ``EvalOutcome`` exposes (eval/run.py):
no-leak, no-integrity-failure, no-unexpected-output, ``coverage_ok``, ``retention_ok``,
``decoy_survival_ok``, ``flag_survival_ok``. There is NO "each baseline fails exactly one
gate" property — that was never true (see scorch/empty_output below). Measured against the
mutation-test corpus (n=10, seed=23), each baseline trips exactly these gates, all others
green (pinned in ``tests/test_baseline_gate_matrix.py``):

* :func:`null_redactor` copies the input byte-for-byte. Trips the LEAK gate alone (every
  ``auto_redact`` surface survives, ~0%% recall). A harness that passes this is broken.
* :func:`scorch_redactor` / :func:`empty_output_redactor` destroy every character (emit a
  valid but empty file). Both trip THREE gates together — ``retention_ok`` (no non-PII
  content survived), ``decoy_survival_ok`` (every decoy destroyed) and ``flag_survival_ok``
  (every checksum-invalid ``should_flag`` hard-negative destroyed). Tripping three gates is
  the CORRECT behaviour of total destruction, not a defect: the point (context.md rejection,
  defect 1a) is that zero leaks and 100%% recall must NOT read as success when the file was
  simply annihilated — the exact scenario the original harness passed with ``VERDICT: PASS``
  on a corpus of blank pages. The two are the same strategy under two names and so measure to
  an IDENTICAL vector (see DISCRIMINATION below).
* :func:`refuse_all_redactor` writes NO output for any input, not just the no-text-layer
  fixtures a real redactor is allowed to refuse. Trips the COVERAGE gate alone: zero leaks is
  not success when nothing was produced (context.md rejection, defect 1b).
* :func:`greedy_redactor` is an ORACLE (it reads the ground truth alongside each input to
  know exactly what to redact — no detection logic, no stage-3 dependency): it redacts every
  ``auto_redact`` surface AND every checksum-invalid RODNE_CISLO/ICO/IBAN (``should_flag``
  hard negatives that must reach the review bucket, never be auto-redacted, per §4.1). It
  leaks nothing, retains everything else, preserves every decoy, produces output for every
  doc — so it trips the FLAG-SURVIVAL gate (a checksum-invalid identifier auto-redacted
  instead of routed to review, context.md rejection round 2, defect D5). A harness that
  cannot catch an over-eager detector auto-redacting a checksum-invalid identifier is exactly
  the bug §4.1's checksum requirement exists to prevent.

Two properties over the whole set, both pinned in ``tests/test_baseline_gate_matrix.py``:

  COVERAGE       — every §8.3 falsification gate (leak, coverage, retention, decoy_survival,
                   flag_survival) is tripped red by at least one baseline; a gate no baseline
                   can trip has never been proven to fire. The other two ``EvalOutcome``
                   gates — integrity (a corrupt, unopenable output) and unexpected-output (an
                   output for a ``must_be_refused`` doc) — are structural invariants none of
                   these five trip: none emit a corrupt file, none are handed a refused doc.
  DISCRIMINATION — no two baselines share a gate vector, with ONE known, intentional
                   exception: :func:`scorch_redactor` and :func:`empty_output_redactor` are
                   two names for the same total-destruction strategy and measure identically.
                   Any OTHER collision means a baseline has gone redundant as a falsification
                   instrument and must be investigated.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import docx
import fitz
from lxml import etree


def null_redactor(src: Path, dst: Path) -> None:
    """No-op: copy the file byte-for-byte. Every PII surface survives."""
    shutil.copyfile(src, dst)


def _empty_file(src: Path, dst: Path) -> None:
    suffix = src.suffix.lower()
    if suffix == ".docx":
        docx.Document().save(str(dst))
    elif suffix == ".pdf":
        doc = fitz.open()
        doc.new_page()
        doc.save(str(dst))
        doc.close()
    else:
        raise ValueError(f"unsupported file type: {src.suffix!r} ({src.name})")


def scorch_redactor(src: Path, dst: Path) -> None:
    """Destroy everything: emit a valid, empty file of the same format. No text, no metadata,
    so no surface — auto, flag, or decoy — survives, and the file still opens cleanly."""
    _empty_file(src, dst)


def empty_output_redactor(src: Path, dst: Path) -> None:
    """Same mechanics as :func:`scorch_redactor` (valid, empty file) — named separately
    because it targets the §8.3 retention gate specifically: destroying ALL content, not
    just PII, must fail even when the leak and recall gates report a perfect score."""
    _empty_file(src, dst)


def refuse_all_redactor(src: Path, dst: Path) -> None:
    """Refuse every input: write nothing at all, for every document — not just the
    no-text-layer fixtures a real redactor is allowed to refuse (context.md §3). Targets the
    §8.3 coverage gate: zero leaks is not success if nothing was produced."""
    return


# ---------------------------------------------------------------- greedy_redactor (oracle)
_GREEDY_LABEL = "[REDACTED]"
_FLAG_TYPES = {"RODNE_CISLO", "ICO", "IBAN"}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TEXT_TAGS = (_W + "t", _W + "delText")
_DOCX_CONTENT_PART = re.compile(
    r"^word/(document\.xml|footnotes\.xml|endnotes\.xml|comments\.xml|header\d*\.xml|footer\d*\.xml)$"
)
_DOCX_METADATA_PART = {"docProps/core.xml", "docProps/app.xml"}


def _greedy_targets(gt: dict) -> list[str]:
    """Every auto_redact surface, plus every checksum-invalid RODNE_CISLO/ICO/IBAN
    (should_flag) — the over-eager behaviour §8.3's flag gate exists to catch."""
    surfaces = {
        p["surface"] for p in gt["pii"]
        if p["auto_redact"] or (p["should_flag"] and p["type"] in _FLAG_TYPES)
    }
    return sorted(surfaces)


def _greedy_decoys(gt: dict) -> list[str]:
    """Every decoy surface (auto_redact=False, should_flag=False) — must never be touched.
    CAPITALISED_COMMON decoys are deliberately built to share a stem/prefix with a seeded
    surname (context.md §5, rejection round 5, e.g. surname "Novák" -> decoy "Novákov dom"),
    which means a target like "Novák" is a literal substring of the decoy. A plain
    ``str.replace`` would clip into it; span-exclusion (see ``_find_spans``) is what makes
    this oracle actually correct instead of just usually-correct."""
    return sorted({p["surface"] for p in gt["pii"] if not p["auto_redact"] and not p["should_flag"]})


def _find_spans(text: str, surfaces: list[str]) -> list[tuple[int, int]]:
    """Every occurrence of every surface in ``text``, by exact character offset."""
    spans = []
    for s in surfaces:
        start = 0
        while True:
            idx = text.find(s, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(s)))
            start = idx + len(s)
    return spans


def _substitute(text: str, targets: list[str], decoys: list[str] | None = None) -> str:
    """Replace every occurrence of every target with the label, EXCEPT an occurrence that
    falls entirely inside a decoy's own span — that's not an independent target occurrence,
    it's a substring artifact of a decoy that must survive untouched (e.g. "Novák" inside the
    decoy "Novákov dom")."""
    decoy_spans = _find_spans(text, decoys) if decoys else []
    target_spans = [
        span for span in _find_spans(text, targets)
        if not any(
            d0 <= span[0] and span[1] <= d1 and (d1 - d0) > (span[1] - span[0])
            for d0, d1 in decoy_spans
        )
    ]
    if not target_spans:
        return text
    target_spans.sort()
    merged: list[list[int]] = []
    for start, end in target_spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: list[str] = []
    pos = 0
    for start, end in merged:
        out.append(text[pos:start])
        out.append(_GREEDY_LABEL)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _redact_docx_xml_part(blob: bytes, targets: list[str], decoys: list[str]) -> bytes:
    """Collapse this part's ENTIRE reconstructed text (all its w:t/w:delText nodes, matching
    how eval/extract.py reconstructs a part — no separator) into its first text-bearing node
    after substitution, blanking the rest. Token/substring-based checks (leak, retention) only
    care about the final reconstructed text, not which node carries it — exact span-preserving
    edits are a stage-4 concern, not needed for this oracle test baseline."""
    root = etree.fromstring(blob)
    nodes = [el for el in root.iter() if el.tag in _TEXT_TAGS]
    if not nodes:
        return blob
    joined = "".join(el.text or "" for el in nodes)
    new_text = _substitute(joined, targets, decoys)
    if new_text == joined:
        return blob
    nodes[0].text = new_text
    for el in nodes[1:]:
        el.text = ""
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _redact_docx(src: Path, dst: Path, targets: list[str], decoys: list[str]) -> None:
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        blobs = {i.filename: zin.read(i.filename) for i in infos}

    for name in list(blobs):
        if _DOCX_CONTENT_PART.match(name):
            blobs[name] = _redact_docx_xml_part(blobs[name], targets, decoys)
        elif name in _DOCX_METADATA_PART:
            blobs[name] = _substitute(blobs[name].decode("utf-8"), targets, decoys).encode("utf-8")

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:
            zout.writestr(i.filename, blobs[i.filename])


def _search_variants(page, s: str) -> list:
    """PyMuPDF's font-subsetting artifact that turns a drawn hyphen-minus into U+00AD (see
    eval/extract.py) affects search_for() too, not just get_text() — a literal hyphen in the
    query can silently fail to match. Fall back to the soft-hyphen form when the plain search
    misses."""
    rects = page.search_for(s)
    if not rects and "-" in s:
        rects = page.search_for(s.replace("-", "\xad"))
    return rects


def _rect_inside(inner, outer) -> bool:
    """True only when ``outer`` STRICTLY covers ``inner``: fully containing it AND strictly
    larger in area. The geometric analog of eval/leak.py::surface_present's
    ``(d1 - d0) > target_len`` — an EQUAL rect satisfies all four ``<=`` comparisons but
    suppresses nothing, so a decoy box coinciding exactly with a target box can never blind
    the PDF path to that PII (mirrors the round-8 equal-span fix)."""
    covers = (outer.x0 <= inner.x0 and outer.y0 <= inner.y0
              and inner.x1 <= outer.x1 and inner.y1 <= outer.y1)
    outer_area = (outer.x1 - outer.x0) * (outer.y1 - outer.y0)
    inner_area = (inner.x1 - inner.x0) * (inner.y1 - inner.y0)
    return covers and outer_area > inner_area


def _redact_pdf(src: Path, dst: Path, targets: list[str], decoys: list[str]) -> None:
    doc = fitz.open(src)
    try:
        # apply_redactions() clears EVERY FreeText annotation on the page as a side effect,
        # not just ones overlapping a redaction rect (confirmed empirically: an annotation
        # with no spatial relation to the redacted text still vanished). Snapshot content
        # first, delete, redact the text layer, then re-add with substitutions applied — the
        # only way to keep annotation text (and its own target substitutions) alive.
        saved_annots = []
        for page in doc:
            for annot in page.annots():
                saved_annots.append((page.number, annot.rect, annot.info.get("content") or ""))
            for annot in list(page.annots()):
                page.delete_annot(annot)

        # text layer: genuine glyph destruction via PyMuPDF redaction annotations, the
        # real technique context.md §10 specifies — not a text-substitution hack. A target
        # rect fully inside a decoy's own rect is a substring artifact (e.g. "Novák" is a
        # literal substring of the decoy "Novákov"), not an independent occurrence — skip it,
        # same reasoning as the DOCX span-exclusion in ``_substitute``.
        for page in doc:
            decoy_rects = [r for s in decoys for r in _search_variants(page, s)]
            for s in targets:
                for rect in _search_variants(page, s):
                    if any(_rect_inside(rect, dr) for dr in decoy_rects):
                        continue
                    page.add_redact_annot(rect, text=_GREEDY_LABEL, fill=(1, 1, 1))
            page.apply_redactions()

        for page_no, rect, content in saved_annots:
            new_content = _substitute(content, targets, decoys)
            doc[page_no].add_freetext_annot(rect, new_content, fontsize=10)

        for page in doc:
            for widget in page.widgets():
                value = widget.field_value or ""
                new_value = _substitute(value, targets, decoys)
                if new_value != value:
                    widget.field_value = new_value
                    widget.update()

        for name in doc.embfile_names():
            text = doc.embfile_get(name).decode("utf-8", "replace")
            new_text = _substitute(text, targets, decoys)
            if new_text != text:
                # embfile_upd(buffer_=...) hits a bytes/Buffer mismatch in this PyMuPDF
                # build; delete-and-re-add is the stable path to replace embedded content.
                doc.embfile_del(name)
                doc.embfile_add(name, new_text.encode("utf-8"))

        meta = dict(doc.metadata or {})
        changed = False
        for k, v in list(meta.items()):
            if isinstance(v, str) and v:
                new_v = _substitute(v, targets, decoys)
                if new_v != v:
                    meta[k] = new_v
                    changed = True
        if changed:
            doc.set_metadata(meta)

        xmp = doc.get_xml_metadata() or ""
        new_xmp = _substitute(xmp, targets, decoys)
        if new_xmp != xmp:
            doc.set_xml_metadata(new_xmp)

        doc.save(str(dst))
    finally:
        doc.close()


def greedy_redactor(src: Path, dst: Path) -> None:
    """Oracle redactor: reads ``<src>.gt.json`` alongside ``src`` and redacts every
    auto_redact surface AND every checksum-invalid RODNE_CISLO/ICO/IBAN, while protecting
    every decoy surface from substring collateral damage. See module docstring — must fail
    the §8.3 flag-survival gate alone."""
    gt_path = src.parent / f"{src.name}.gt.json"
    gt = json.loads(gt_path.read_text("utf-8"))
    targets = _greedy_targets(gt)
    decoys = _greedy_decoys(gt)
    suffix = src.suffix.lower()
    if suffix == ".docx":
        _redact_docx(src, dst, targets, decoys)
    elif suffix == ".pdf":
        _redact_pdf(src, dst, targets, decoys)
    else:
        raise ValueError(f"unsupported file type: {src.suffix!r} ({src.name})")
