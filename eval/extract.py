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

RED-TEAM HARDENING (v1.1, ``redteam/FINDINGS.md``)
--------------------------------------------------
Text-node-only extraction was provably blind to a long list of surfaces that a real Word or
Acrobat file carries. Each of the additions below was proved RED first with a hand-built
fixture (``tests/test_extract_hidden_surfaces.py``) that hides a marker in exactly that
surface and shows the previous extractor could not see it:

DOCX
  * **XML ATTRIBUTE values** (``xml_attributes``) — ``lxml``'s ``itertext()`` walks text
    nodes only, so image alt text (``wp:docPr/@descr``, ``@title``), tracked-change and
    comment authorship (``w:ins/@w:author``, ``w:del/@w:author``, ``w:comment/@w:author``,
    ``@w:initials``), ``word/people.xml`` authors and ``w:docVar/@w:val`` were all invisible.
  * **every other XML part** (``other_xml_parts``) — SmartArt (``word/diagrams/*``), charts
    (``word/charts/*``), content-control data stores (``customXml/*``), the glossary
    document, ``word/people.xml``: separate OPC parts that the named surfaces never opened.
  * **relationship targets** (``rels_targets``) — a ``mailto:jan.novak@firma.sk`` hyperlink
    target leaks a name and an address even when the display text reads ``[MENO_1]``;
    ``attachedTemplate`` targets leak a Windows user profile path.
  * **binary parts** (``binary_parts``) — ``word/embeddings/*`` (OLE storages hold strings as
    UTF-16LE), plus image EXIF/XMP. Part NAMES are included so a picture-only surface such as
    ``docProps/thumbnail.jpeg`` at least shows up in a report (its pixels cannot be read —
    see the KNOWN BLIND SPOTS section of ``redteam/FINDINGS.md``).
  * **altChunk sub-documents** (``alt_chunk_parts``, red-team round 5, R5-02) — a
    ``<w:altChunk>`` part is a whole external document (HTML/``.mht``/text/nested ``.docx``)
    that Word splices onto the page on open. It has no ``.xml`` extension, so it used to be
    swept as a binary part, i.e. as an OPAQUE surface the leak gate discounts short needles on
    — which made a five-digit PSČ and a four-digit bank code in RENDERED DOCUMENT TEXT score
    CLEAN. It now has its own TEXT surface, graded with no discount.

PDF
  * **text hidden from ``get_text()``** — MuPDF's structured-text device clips to the
    CropBox and honours optional-content (layer) visibility, so text outside the CropBox and
    text inside an OFF layer extracted as nothing at all while any PDF tool can still recover
    it. ``_pdf_unhide()`` widens every CropBox to its MediaBox and drops ``/OCProperties``
    from the catalogue (in memory only — the file on disk is never written) before reading
    the text layer.
  * **outline / bookmarks** (``outline``) and **link annotations** (``links``) — a
    ``mailto:`` URI action is PII that ``page.annots()`` never yields (MuPDF excludes Link
    annotations from it) and ``get_text()`` never draws.
  * **annotation authorship** — ``annotations`` now also carries ``/T`` (title = author) and
    ``/Subj``, not only ``/Contents``.
  * **form field NAMES** — ``form_fields`` now also carries ``field_name``, ``field_label``,
    button captions and choice lists: a field named ``rodne_cislo_novak`` leaks on its own.
  * **attachment names and descriptions** — ``attachments`` now also carries each embedded
    file's name/description, not only its bytes.
  * **``pdf_objects``** — the source of every indirect object, which catches whatever the
    typed APIs above do not model (custom ``/Info`` keys, named destinations, OCG names,
    JavaScript).
  * **``raw_bytes``** — the decompressed bytes of the whole file, decoded in several
    encodings. This is the backstop for the highest-severity vector in the list: a PDF saved
    INCREMENTALLY keeps the previous revision's objects verbatim, so pre-redaction text stays
    recoverable from the file while every parsed API reports it gone.

All additions are additive: no existing ``by_surface`` key was renamed or removed, and the
existing keys only ever gained text.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import fitz
from lxml import etree

from writer.pdf_view import unhide

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
# DOCX — red-team additions
S_XML_ATTRS = "xml_attributes"      # attribute values of EVERY xml/rels part in the package
S_OTHER_XML = "other_xml_parts"     # text of every xml part no named surface covers
S_RELS = "rels_targets"             # relationship Target values (hyperlinks, templates, ...)
S_BINARY_PARTS = "binary_parts"     # embeddings/media: part names + decoded strings
S_ALT_CHUNKS = "alt_chunk_parts"    # w:altChunk sub-documents — TEXT Word renders on the page
# PDF
S_TEXT_LAYER = "text_layer"
S_ANNOTATIONS = "annotations"
S_FORM_FIELDS = "form_fields"
S_ATTACHMENTS = "attachments"
S_INFO = "info_metadata"
S_XMP = "xmp"
# PDF — red-team additions
S_OUTLINE = "outline"               # bookmarks / table of contents titles
S_LINKS = "links"                   # link annotation targets (URI / file / named dest)
S_PDF_OBJECTS = "pdf_objects"       # source of every indirect object in the xref
S_RAW_BYTES = "raw_bytes"           # decompressed file bytes — catches incremental residue

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


# ---------------------------------------------------------------- byte decoding
# A blob of bytes can hold text in any of these; decoding in all of them removes a whole
# class of "we only looked for UTF-8" blind spots. latin-1 is the lossless byte->char view
# (nothing raises, nothing is dropped) and also reads PDFDocEncoding; cp1250 is the Windows
# Slovak code page; UTF-16 LE/BE cover OLE storages (DOCX embeddings), PDF text strings and
# TrueType name tables.
_DECODINGS = ("utf-8", "utf-16-le", "utf-16-be", "cp1250", "latin-1")
# High-entropy binary (a compressed stream, an image) yields megabytes of junk under the
# byte-preserving codepages while carrying no readable text; decode it only under the codecs
# that reject invalid sequences. The threshold is applied to a 4 KiB sample.
_BINARY_DECODINGS = ("utf-8", "utf-16-le", "utf-16-be")
_TEXTY_BYTES = frozenset(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}
_TEXTY_MIN_RATIO = 0.5
# Guard against a multi-hundred-MB embedded video turning one grep into a memory event. No
# corpus or office document part comes near this; a part larger than the cap still has its
# NAME reported, so it can never be silently dropped (see redteam/FINDINGS.md).
_MAX_BINARY_BYTES = 8 * 1024 * 1024
# A "string" for the raw backstop: a run of at least 4 printable characters (ASCII plus the
# Latin-1/Latin-Extended block that carries every Slovak diacritic). Any PII surface lies
# wholly inside one such run — names, addresses, RČ and IBAN contain no control characters.
_RUN_RE = re.compile(r"[\x20-\x7e\xa0-ɏ]{4,}")


def _is_binary(data: bytes) -> bool:
    sample = data[:4096]
    if not sample:
        return True
    texty = sum(1 for b in sample if b in _TEXTY_BYTES)
    return texty / len(sample) < _TEXTY_MIN_RATIO


def _decode_all(data: bytes, *, decodings: tuple[str, ...] = _DECODINGS) -> str:
    """Every plausible text reading of ``data``, concatenated."""
    if len(data) > _MAX_BINARY_BYTES:
        data = data[:_MAX_BINARY_BYTES]
    return "\n".join(data.decode(enc, "ignore") for enc in decodings)


def _collect_runs(data: bytes, out: dict[str, None], *, decodings: tuple[str, ...] | None = None) -> None:
    """Add every printable run of every decoding of ``data`` to ``out`` (an ordered set).

    Deduplicating runs is what keeps the raw backstop affordable: five decodings of the same
    ASCII bytes produce five identical run lists. It cannot hide a leak — a PII surface is
    either inside some run (kept) or is not in the bytes at all.
    """
    if decodings is None:
        decodings = _BINARY_DECODINGS if _is_binary(data) else _DECODINGS
    if len(data) > _MAX_BINARY_BYTES:
        data = data[:_MAX_BINARY_BYTES]
    for enc in decodings:
        for run in _RUN_RE.findall(data.decode(enc, "ignore")):
            out[run] = None


# ---------------------------------------------------------------- DOCX
def _itertext(root: etree._Element) -> str:
    # No separator: a surface split across runs must reconstruct (context.md §10).
    return "".join(root.itertext())


def _attr_text(root: etree._Element) -> str:
    """Every attribute VALUE in the tree, newline-joined.

    ``itertext()`` walks text nodes only, so without this an image's alt text
    (``wp:docPr/@descr``) or a tracked change's author (``w:ins/@w:author``) is invisible to
    the leak grep. Values are joined with a newline, not concatenated: unlike run text, two
    adjacent attribute values are never two halves of one logical string, and gluing them
    would fabricate substrings that exist in no surface of the document.
    """
    return "\n".join(v for el in root.iter() if isinstance(el.tag, str) for v in el.attrib.values())


_DOCX_NAMED_PARTS = {
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/comments.xml",
    "docProps/core.xml",
    "docProps/app.xml",
    "docProps/custom.xml",
}
_DOCX_HEADER_FOOTER_RE = re.compile(r"(header|footer)\d*\.xml$")
_XML_PART_RE = re.compile(r"\.(xml|rels)$", re.IGNORECASE)


def _is_named_part(name: str) -> bool:
    return name in _DOCX_NAMED_PARTS or bool(_DOCX_HEADER_FOOTER_RE.search(name))


# ---------------------------------------------------------------- w:altChunk (R5-02)
# The surface classification above is BY FILE EXTENSION: anything that is not .xml/.rels is
# swept as ``binary_parts``, which the leak gate treats as OPAQUE — a surface whose premise is
# that it cannot hold document text, so a short needle in it is discounted as structural noise
# (font tables, xref offsets). An altChunk part is the counter-example that breaks the premise:
# it is a whole external document (HTML, .mht, plain text, or a nested .docx) that Word splices
# ONTO THE PAGE when the file is opened, and it is stored as ``word/afchunk.mht`` — no .xml
# extension, therefore opaque, therefore ``04001`` (a Slovak PSČ) and ``1100`` (a bank code)
# leaked there while the gate scored the document CLEAN.
#
# These parts are identified by RELATIONSHIP TYPE, not by extension. Extension is what got this
# wrong in the first place, the reltype is what Word itself keys on, and it reclassifies exactly
# the altChunk parts rather than every ``.txt`` that happens to be in a package.
_AFCHUNK_RELTYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk"
)


def _alt_chunk_names(z: zipfile.ZipFile) -> set[str]:
    """Package part names reached by an ``aFChunk`` relationship from any ``.rels`` part."""
    out: set[str] = set()
    for name in z.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            root = etree.fromstring(z.read(name))
        except etree.XMLSyntaxError:
            continue  # the bytes are still swept by the xml_parts pass below
        base = posixpath.dirname(posixpath.dirname(name))
        for el in root:
            if el.get("Type") != _AFCHUNK_RELTYPE:
                continue
            target = el.get("Target", "")
            out.add(target.lstrip("/") if target.startswith("/")
                    else posixpath.normpath(posixpath.join(base, target)))
    return out


def _alt_chunk_text(data: bytes) -> str:
    """The readable text of one altChunk part, in every plausible encoding.

    A nested ``.docx`` chunk is a ZIP, so its ``document.xml`` is DEFLATED and no decoding of
    the outer bytes can see a word of it; its entries are therefore read out one level. The
    whole decoding is kept rather than printable runs: this is document text, and a needle as
    short as four digits has to be findable in it.
    """
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as inner:
            names = inner.namelist()
            return "\n".join(names + [_decode_all(inner.read(n)) for n in names])
    return _decode_all(data)


def _extract_docx(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        def parse(name: str) -> etree._Element | None:
            """Parse an XML part, or None if it is not well-formed (callers fall back to the
            raw bytes rather than dropping the part — an unparseable part is exactly where
            someone would hide something)."""
            try:
                return etree.fromstring(z.read(name))
            except etree.XMLSyntaxError:
                return None

        def content(name: str) -> str:
            if name not in names:
                return ""
            return _itertext(etree.fromstring(z.read(name)))

        def raw(name: str) -> str:
            return z.read(name).decode("utf-8") if name in names else ""

        def content_glob(pattern: str) -> str:
            return "".join(content(n) for n in names if re.search(pattern, n))

        # altChunk parts are text Word renders on the page, so they leave the opaque sweep and
        # get a surface of their own that the leak gate grades with no discount (R5-02).
        alt_chunks = _alt_chunk_names(z) & set(names)
        xml_parts = [n for n in names if _XML_PART_RE.search(n) and n not in alt_chunks]
        binary_parts = [n for n in names
                        if not _XML_PART_RE.search(n) and n not in alt_chunks]

        attrs: list[str] = []
        others: list[str] = []
        rels: list[str] = []
        for name in xml_parts:
            root = parse(name)
            if root is None:
                # Not well-formed: keep the bytes themselves in the sweep surfaces so the
                # grep still sees whatever is in there.
                blob = z.read(name).decode("utf-8", "replace")
                attrs.append(blob)
                if not _is_named_part(name):
                    others.append(blob)
                continue
            attrs.append(_attr_text(root))
            if not _is_named_part(name):
                others.append(_itertext(root))
            if name.endswith(".rels"):
                rels.extend(
                    el.get("Target", "") for el in root.iter() if el.get("Target") is not None
                )

        # Part names first: a binary whose bytes hold no readable text (a JPEG thumbnail, a
        # signature image) still has to be VISIBLE in a report, never silently skipped.
        binary_runs: dict[str, None] = {}
        for n in binary_parts:
            _collect_runs(z.read(n), binary_runs)
        binaries = ["\n".join(binary_parts), "\n".join(binary_runs)]

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
            S_XML_ATTRS: "\n".join(attrs),
            S_OTHER_XML: "\n".join(others),
            S_RELS: "\n".join(rels),
            S_BINARY_PARTS: "\n".join(binaries),
            S_ALT_CHUNKS: "\n".join(
                sorted(alt_chunks) + [_alt_chunk_text(z.read(n)) for n in sorted(alt_chunks)]
            ),
        }


# ---------------------------------------------------------------- PDF
def _pdf_unhide(doc: fitz.Document) -> None:
    """Make text that MuPDF's text device would skip visible to ``get_text()``.

    The logic moved to ``writer/pdf_view.py`` unchanged (red-team round 6, R6-05/R6-06): the
    WRITER has to read the same document this extractor grades, and the way to guarantee that
    is one definition called from both, not a second copy here. The mutation is in-memory only
    — the extractor never writes the file back, so it discards the restore handle that the
    writer needs.
    """
    unhide(doc)


# A stream whose dictionary says it is an embedded font: its body is glyph outlines, which
# cannot carry document text, and inflating it under the byte-preserving codepages produces
# ~250 KB of junk per file. It is not skipped, though — a TrueType/OpenType ``name`` table
# stores its strings in UTF-16BE, so the font body is still read under the UTF-16 codecs,
# which is the only place a font part can hold anything human-readable.
_FONT_STREAM_MARKERS = (b"/FontFile", b"/Type1C", b"/CIDFontType", b"/TrueType", b"/OpenType")
_FONT_DECODINGS = ("utf-16-be", "utf-16-le")
# PDF strings are written as hex as often as literally — both in object dictionaries
# (``/Author <FEFF004A00E1...>``, how Acrobat stores anything with a diacritic) and inside
# content streams (``[<4b6f6420...>] TJ``). Neither is readable under any byte decoding, so
# every hex string is decoded and scanned in its own right.
_HEX_STRING_RE = re.compile(rb"<([0-9A-Fa-f\s]{4,4096})>")


def _scan_pdf_blob(data: bytes, out: dict[str, None], *, decodings: tuple[str, ...] | None = None) -> None:
    """Collect printable runs from ``data`` AND from every hex string inside it."""
    _collect_runs(data, out, decodings=decodings)
    if decodings is _FONT_DECODINGS:
        return  # glyph outlines: no PDF strings in there, and the regex is not free
    for m in _HEX_STRING_RE.finditer(data):
        hexs = re.sub(rb"\s", b"", m.group(1))
        if len(hexs) % 2:
            continue
        try:
            _collect_runs(bytes.fromhex(hexs.decode("ascii")), out, decodings=_DECODINGS)
        except ValueError:
            continue


def _pdf_raw_text(path: Path) -> str:
    """The file's bytes, plus every stream we can inflate, decoded every plausible way.

    The backstop for anything the parsed APIs cannot reach — above all an INCREMENTAL save,
    which appends a new revision and leaves the previous one's objects (pre-redaction text,
    the old /Info dict) in the file verbatim. ``fitz`` reads only the current xref, so every
    typed API reports that text as gone while it is still sitting in the bytes.

    Compressed stream BODIES are cut out of the file-level pass and scanned separately after
    inflation: their compressed bytes are high-entropy noise that can hold no text, and
    leaving them in makes the file-level pass an order of magnitude more expensive for
    nothing.
    """
    data = path.read_bytes()
    out: dict[str, None] = {}
    outside: list[bytes] = []
    pos = 0
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        outside.append(data[pos:m.start()])
        pos = end
        dict_head = data[max(0, m.start() - 512):m.start()]
        decodings = (
            _FONT_DECODINGS if any(f in dict_head for f in _FONT_STREAM_MARKERS) else None
        )
        body = data[start:end]
        for cand in (body, body.rstrip(b"\r\n")):
            try:
                inflated = zlib.decompress(cand)
            except zlib.error:
                continue
            # A content stream's text is hex INSIDE the compressed stream, so the hex pass
            # has to run on what came out of the inflation, not only on the file bytes.
            _scan_pdf_blob(inflated, out, decodings=decodings)
            break
        else:  # not deflate-compressed: the bytes are the content (or an unknown filter)
            _scan_pdf_blob(body, out, decodings=decodings)
    outside.append(data[pos:])
    _scan_pdf_blob(b"".join(outside), out, decodings=_DECODINGS)
    return "\n".join(out)


def _extract_pdf(path: Path) -> dict[str, str]:
    doc = fitz.open(path)
    try:
        _pdf_unhide(doc)
        # \xad -> - repairs PyMuPDF's hyphen subsetting artifact on the haystack only (§7).
        text_layer = "\n".join(p.get_text() for p in doc).replace("\xad", "-")
        # Annotation AUTHORSHIP is PII too: /T (title) is the author's name, /Subj the
        # subject line. Only /Contents used to be read.
        annotations = " ".join(
            str(a.info.get(k) or "")
            for p in doc
            for a in p.annots()
            for k in ("content", "title", "subject", "name")
        )
        # Field NAMES leak on their own ("rodne_cislo_novak"), as do labels, button
        # captions and the choice lists of dropdowns.
        form_fields = " ".join(
            str(v or "")
            for p in doc
            for w in p.widgets()
            for v in (
                w.field_value,
                w.field_name,
                w.field_label,
                getattr(w, "button_caption", None),
                getattr(w, "choice_values", None),
            )
        )
        attachments = " ".join(
            doc.embfile_get(n).decode("utf-8", "replace") for n in doc.embfile_names()
        )
        # ... and the attachment's own name/description, which live in the file spec, not
        # in its bytes.
        attachments += " " + " ".join(
            f"{n} " + " ".join(str(v) for v in (doc.embfile_info(n) or {}).values())
            for n in doc.embfile_names()
        )
        info = " ".join(str(v) for v in (doc.metadata or {}).values())
        xmp = doc.get_xml_metadata() or ""
        outline = " ".join(str(item[1]) for item in (doc.get_toc(simple=True) or []))
        links = " ".join(
            str(v)
            for p in doc
            for link in p.get_links()
            for k, v in link.items()
            if k in ("uri", "file", "nameddest", "name")
        )
        objects = "\n".join(
            doc.xref_object(x, compressed=False) or "" for x in range(1, doc.xref_length())
        )
    finally:
        doc.close()
    return {
        S_TEXT_LAYER: text_layer,
        S_ANNOTATIONS: annotations,
        S_FORM_FIELDS: form_fields,
        S_ATTACHMENTS: attachments,
        S_INFO: info,
        S_XMP: xmp,
        S_OUTLINE: outline,
        S_LINKS: links,
        S_PDF_OBJECTS: objects,
        S_RAW_BYTES: _pdf_raw_text(path),
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
