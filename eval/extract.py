"""Exhaustive text extraction from a redacted output file (context.md §8.1, step 1).

This is the crux of the whole harness. A leak can hide in any surface a document format
offers, and an incomplete extractor turns the killer leak test into a false green: it greps
for a PII string in text it never pulled out, finds nothing, and reports "clean". So this
module reaches *every* surface §8.1 names, and its own grader (tests/test_extract.py) proves
it by finding every ground-truth surface in the unredacted corpus.

Two kinds of surface, two extraction strategies:

* **Content** (DOCX ``document.xml`` / headers / footers / notes / comments): concatenate
  run texts with NO separator, so a name split across ``<w:r>`` runs reconstructs
  (context.md §10). Inserting any separator would hide the classic split-run leak.
* **Metadata** (DOCX ``docProps/*.xml``): keep the raw decoded XML, so a leak in an element
  *or an attribute* is still caught.

The one PyMuPDF quirk (§7): its ``TextWriter`` subsetting extracts a drawn hyphen-minus as
U+00AD (soft hyphen), which real Word/Acrobat PDFs do not contain. Ground truth records the
authored U+002D, so we repair ``\xad -> -`` on the PDF text layer (the haystack) here. NBSP
is genuine Slovak typography and is never touched.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz
from lxml import etree

# ---------------------------------------------------------------- physical surfaces
# DOCX
S_DOCUMENT = "document_xml"   # body, tables, textboxes, tracked changes — all live here
S_HEADER = "header"
S_FOOTER = "footer"
S_FOOTNOTES = "footnotes"
S_ENDNOTES = "endnotes"
S_COMMENTS = "comments"
S_CORE = "core_xml"
S_APP = "app_xml"
S_CUSTOM = "custom_xml"
# PDF
S_TEXT_LAYER = "text_layer"
S_ANNOTATIONS = "annotations"
S_FORM_FIELDS = "form_fields"
S_ATTACHMENTS = "attachments"
S_INFO = "info_metadata"
S_XMP = "xmp"

# Ground-truth ``surface_part`` -> physical extractor surface. Several DOCX GT parts are
# co-located in document.xml (they are one OPC part), so they map to the same surface: the
# extractor reports where a leak physically lives, not the logical role it plays.
_GT_PART_TO_SURFACE = {
    "docx": {
        "body": S_DOCUMENT,
        "table_cell": S_DOCUMENT,
        "textbox": S_DOCUMENT,
        "tracked_change_ins": S_DOCUMENT,
        "tracked_change_del": S_DOCUMENT,
        "header": S_HEADER,
        "footer": S_FOOTER,
        "footnote": S_FOOTNOTES,
        "endnote": S_ENDNOTES,
        "comment": S_COMMENTS,
        "metadata_core": S_CORE,
        "metadata_app": S_APP,
    },
    "pdf": {
        "body": S_TEXT_LAYER,
        "annotation": S_ANNOTATIONS,
        "form_field": S_FORM_FIELDS,
        "attachment": S_ATTACHMENTS,
        "metadata": S_INFO,
        "xmp": S_XMP,
    },
}


def surface_for_gt_part(fmt: str, part: str) -> str:
    """Map a ground-truth ``surface_part`` to the physical surface the extractor exposes."""
    try:
        return _GT_PART_TO_SURFACE[fmt][part]
    except KeyError as exc:
        raise KeyError(f"no physical surface for gt part {part!r} in format {fmt!r}") from exc


@dataclass
class ExtractResult:
    """Everything extractable from one file.

    ``full_text`` is the union of all surfaces (a quick haystack for the leak grep);
    ``by_surface`` maps physical surface -> its text, so a leak report can name *where*.
    """
    full_text: str
    by_surface: dict[str, str]


# ---------------------------------------------------------------- DOCX
def _itertext(root: etree._Element) -> str:
    # No separator: a surface split across runs must reconstruct (context.md §10).
    return "".join(root.itertext())


def _extract_docx(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        def content(name: str) -> str:
            return _itertext(etree.fromstring(z.read(name))) if name in names else ""

        def raw(name: str) -> str:
            return z.read(name).decode("utf-8") if name in names else ""

        def content_glob(pattern: str) -> str:
            return "".join(content(n) for n in names if re.search(pattern, n))

        return {
            S_DOCUMENT: content("word/document.xml"),
            S_HEADER: content_glob(r"header\d*\.xml"),
            S_FOOTER: content_glob(r"footer\d*\.xml"),
            S_FOOTNOTES: content("word/footnotes.xml"),
            S_ENDNOTES: content("word/endnotes.xml"),
            S_COMMENTS: content("word/comments.xml"),
            S_CORE: raw("docProps/core.xml"),
            S_APP: raw("docProps/app.xml"),
            S_CUSTOM: raw("docProps/custom.xml"),
        }


# ---------------------------------------------------------------- PDF
def _extract_pdf(path: Path) -> dict[str, str]:
    doc = fitz.open(path)
    try:
        # \xad -> - repairs PyMuPDF's hyphen subsetting artifact on the haystack only (§7).
        text_layer = "\n".join(p.get_text() for p in doc).replace("\xad", "-")
        annotations = " ".join(
            (a.info.get("content") or "") for p in doc for a in p.annots()
        )
        form_fields = " ".join(
            (w.field_value or "") for p in doc for w in p.widgets()
        )
        attachments = " ".join(
            doc.embfile_get(n).decode("utf-8", "replace") for n in doc.embfile_names()
        )
        info = " ".join(str(v) for v in (doc.metadata or {}).values())
        xmp = doc.get_xml_metadata() or ""
    finally:
        doc.close()
    return {
        S_TEXT_LAYER: text_layer,
        S_ANNOTATIONS: annotations,
        S_FORM_FIELDS: form_fields,
        S_ATTACHMENTS: attachments,
        S_INFO: info,
        S_XMP: xmp,
    }


def extract(path: Path | str) -> ExtractResult:
    """Extract every surface's text from a ``.docx`` or ``.pdf`` file.

    Raises on a file that cannot be opened/parsed — that *is* the formatting-integrity
    failure §8.2 wants surfaced, not swallowed.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        by_surface = _extract_docx(path)
    elif suffix == ".pdf":
        by_surface = _extract_pdf(path)
    else:
        raise ValueError(f"unsupported file type: {path.suffix!r} ({path.name})")
    full_text = "\n".join(by_surface.values())
    return ExtractResult(full_text=full_text, by_surface=by_surface)
