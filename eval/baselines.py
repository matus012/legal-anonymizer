"""Baseline "redactors" that grade the harness itself (context.md §8, steps 4 & 5).

None are real detectors — they exist so the test suite can prove the harness is not lying
in any direction:

* :func:`null_redactor` copies the input unchanged. The harness MUST report massive leaks
  and ~0%% recall. A harness that passes this is broken.
* :func:`scorch_redactor` / :func:`empty_output_redactor` destroy every character (emit a
  valid but empty file). The harness MUST report zero leaks, 100%% recall, terrible decoy
  survival, AND fail the §8.3 retention gate. A harness that reports success by finding
  nothing is caught here (context.md rejection, defect 1a) — this is the exact scenario the
  original harness passed with ``VERDICT: PASS`` on a corpus of blank pages.
* :func:`refuse_all_redactor` writes NO output for any input, not just the no-text-layer
  fixtures a real redactor is allowed to refuse. The harness MUST fail the §8.3 coverage
  gate (context.md rejection, defect 1b).
* :func:`greedy_redactor` is an ORACLE (it reads the ground truth alongside each input to
  know exactly what to redact — no detection logic, no stage-3 dependency): it redacts every
  ``auto_redact`` surface AND every checksum-invalid RODNE_CISLO/ICO/IBAN (``should_flag``
  hard negatives that must reach the review bucket, never be auto-redacted, per §4.1). It
  leaks nothing, retains everything else, preserves every decoy — so it clears leak /
  retention / decoy-survival / coverage cleanly, and MUST fail on the §8.3 flag-survival
  gate alone (context.md rejection round 2, defect D5). A harness that cannot catch an
  over-eager detector auto-redacting a checksum-invalid identifier is exactly the bug §4.1's
  checksum requirement exists to prevent.
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
    (should_flag) — the over-eager behaviour §8.3's flag gate exists to catch. Longest first
    so a shorter surface that is a substring of a longer one never clips it mid-replace."""
    surfaces = {
        p["surface"] for p in gt["pii"]
        if p["auto_redact"] or (p["should_flag"] and p["type"] in _FLAG_TYPES)
    }
    return sorted(surfaces, key=len, reverse=True)


def _substitute(text: str, targets: list[str]) -> str:
    for s in targets:
        text = text.replace(s, _GREEDY_LABEL)
    return text


def _redact_docx_xml_part(blob: bytes, targets: list[str]) -> bytes:
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
    new_text = _substitute(joined, targets)
    if new_text == joined:
        return blob
    nodes[0].text = new_text
    for el in nodes[1:]:
        el.text = ""
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _redact_docx(src: Path, dst: Path, targets: list[str]) -> None:
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        blobs = {i.filename: zin.read(i.filename) for i in infos}

    for name in list(blobs):
        if _DOCX_CONTENT_PART.match(name):
            blobs[name] = _redact_docx_xml_part(blobs[name], targets)
        elif name in _DOCX_METADATA_PART:
            blobs[name] = _substitute(blobs[name].decode("utf-8"), targets).encode("utf-8")

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


def _redact_pdf(src: Path, dst: Path, targets: list[str]) -> None:
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
        # real technique context.md §10 specifies — not a text-substitution hack.
        for page in doc:
            for s in targets:
                for rect in _search_variants(page, s):
                    page.add_redact_annot(rect, text=_GREEDY_LABEL, fill=(1, 1, 1))
            page.apply_redactions()

        for page_no, rect, content in saved_annots:
            new_content = _substitute(content, targets)
            doc[page_no].add_freetext_annot(rect, new_content, fontsize=10)

        for page in doc:
            for widget in page.widgets():
                value = widget.field_value or ""
                new_value = _substitute(value, targets)
                if new_value != value:
                    widget.field_value = new_value
                    widget.update()

        for name in doc.embfile_names():
            text = doc.embfile_get(name).decode("utf-8", "replace")
            new_text = _substitute(text, targets)
            if new_text != text:
                # embfile_upd(buffer_=...) hits a bytes/Buffer mismatch in this PyMuPDF
                # build; delete-and-re-add is the stable path to replace embedded content.
                doc.embfile_del(name)
                doc.embfile_add(name, new_text.encode("utf-8"))

        meta = dict(doc.metadata or {})
        changed = False
        for k, v in list(meta.items()):
            if isinstance(v, str) and v:
                new_v = _substitute(v, targets)
                if new_v != v:
                    meta[k] = new_v
                    changed = True
        if changed:
            doc.set_metadata(meta)

        xmp = doc.get_xml_metadata() or ""
        new_xmp = _substitute(xmp, targets)
        if new_xmp != xmp:
            doc.set_xml_metadata(new_xmp)

        doc.save(str(dst))
    finally:
        doc.close()


def greedy_redactor(src: Path, dst: Path) -> None:
    """Oracle redactor: reads ``<src>.gt.json`` alongside ``src`` and redacts every
    auto_redact surface AND every checksum-invalid RODNE_CISLO/ICO/IBAN. See module
    docstring — must fail the §8.3 flag-survival gate alone."""
    gt_path = src.parent / f"{src.name}.gt.json"
    gt = json.loads(gt_path.read_text("utf-8"))
    targets = _greedy_targets(gt)
    suffix = src.suffix.lower()
    if suffix == ".docx":
        _redact_docx(src, dst, targets)
    elif suffix == ".pdf":
        _redact_pdf(src, dst, targets)
    else:
        raise ValueError(f"unsupported file type: {src.suffix!r} ({src.name})")
