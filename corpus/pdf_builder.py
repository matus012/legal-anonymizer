"""PDF assembly with the seeded PDF failure modes (context.md §7, §8, §10).

Text is drawn with an embedded Unicode font so Slovak diacritics survive extraction (base-14
fonts drop them). PII is seeded into the text layer, freetext annotations, form-field widgets,
document metadata, XMP, and an embedded attachment — every surface §8.1 says to extract.

**Ground truth equals what is extractable.** Whitespace is written faithfully: a normal space
is drawn as a real positional gap (extracts as U+0020), an authored NBSP is drawn as a glyph
(extracts as U+00A0) — exactly as real Slovak legal PDFs mix them. Each PII is written as an
atomic unit so it never wraps across a line. The one unavoidable artifact is that PyMuPDF's
font subsetting maps a hyphen-minus glyph to U+00AD (detected per font at runtime); ground
truth records that, so the future leak test greps for the string that is really in the file.

A separate :meth:`build_image_only` produces a no-text-layer scan the app must *refuse* (§3).
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz

from .groundtruth import PiiSpec, Recorder

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_PAGE = fitz.paper_rect("a4")
_MARGIN = 56.0
_LEADING = 15.0
_RIGHT = _PAGE.width - _MARGIN
_BOTTOM = _PAGE.height - _MARGIN


def _find_font() -> str:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("no Unicode TTF found; Slovak diacritics require an embedded font")


class PdfBuilder:
    def __init__(self, recorder: Recorder, image_only: bool = False):
        self.rec = recorder
        self.font_path = _find_font()
        self.font = fitz.Font(fontfile=self.font_path)
        self.image_only = image_only
        self.doc = fitz.open()
        self._hyphen_out = self._detect_char("a-a")
        self._author: PiiSpec | None = None
        self._xmp_creator: PiiSpec | None = None
        self._new_page()

    # ------------------------------------------------------------------ round-trip probe
    def _detect_char(self, probe: str) -> str:
        """Write ``probe`` and read back the middle char — captures PyMuPDF's glyph→Unicode
        remap for this font (e.g. hyphen-minus → U+00AD) so ground truth can mirror it."""
        d = fitz.open()
        p = d.new_page()
        tw = fitz.TextWriter(p.rect)
        tw.append((50, 50), probe, font=self.font, fontsize=11)
        tw.write_text(p)
        out = d[0].get_text().strip()
        d.close()
        return out[1:2] if len(out) >= 2 else probe[1:2]

    def _extractable(self, text: str) -> str:
        """The form of ``text`` as it will extract from the drawn text layer."""
        return text.replace("-", self._hyphen_out)

    # ------------------------------------------------------------------ page flow
    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=_PAGE.width, height=_PAGE.height)
        self.tw = fitz.TextWriter(self.page.rect)
        self.y = _MARGIN
        self.x = _MARGIN

    def _flush(self) -> None:
        self.tw.write_text(self.page)

    @property
    def page_no(self) -> int:
        return self.doc.page_count

    def _newline(self) -> None:
        self.y += _LEADING
        self.x = _MARGIN
        if self.y + _LEADING > _BOTTOM:
            self._flush()
            self._new_page()

    def _unit_width(self, text: str, size: float) -> float:
        subs = text.split(" ")
        space_w = self.font.text_length(" ", size)
        return sum(self.font.text_length(s, size) for s in subs) + space_w * (len(subs) - 1)

    def _place_unit(self, text: str, size: float) -> int:
        """Place one non-breaking unit on the current line; internal normal spaces become real
        positional gaps (extract as U+0020); NBSP chars stay inside sub-tokens (extract as
        U+00A0). Returns the page it landed on."""
        space_w = self.font.text_length(" ", size)
        w = self._unit_width(text, size)
        if self.x != _MARGIN and self.x + space_w + w > _RIGHT:
            self._newline()
        elif self.x != _MARGIN:
            self.x += space_w  # gap between units → normal space
        page = self.page_no
        baseline = self.y + size
        for i, sub in enumerate(text.split(" ")):
            if i:
                self.x += space_w
            if sub:
                self.tw.append((self.x, baseline), sub, font=self.font, fontsize=size)
                self.x += self.font.text_length(sub, size)
        return page

    def _flow(self, items: list, record_part: str, size: float = 11.0) -> None:
        self.x = _MARGIN
        for it in items:
            if isinstance(it, str):
                for word in it.split(" "):
                    if word:
                        self._place_unit(word, size)
            else:
                page = self._place_unit(it.surface, size)
                self.rec.record(it, part=record_part, detail={"page": page},
                                surface=self._extractable(it.surface))
        self._newline()

    # ------------------------------------------------------------------ content
    def heading(self, text: str) -> None:
        self._flow([text], "body", size=15.0)
        self.y += 4

    def paragraph(self, items: list) -> None:
        self._flow(items, "body")
        self.y += 4

    def table(self, rows: list[list[list]]) -> None:
        for row in rows:
            flat: list = []
            for c, cell in enumerate(row):
                if c:
                    flat.append("    ")
                flat.extend(cell)
            self._flow(flat, "body")

    # ------------------------------------------------------------------ annotations
    def annotation(self, items: list) -> None:
        page = self.page_no
        text = "".join(it if isinstance(it, str) else it.surface for it in items)
        rect = fitz.Rect(_MARGIN, self.y, _RIGHT, self.y + 40)
        self.page.add_freetext_annot(rect, text, fontsize=10)
        self.y += 46
        for it in items:
            if isinstance(it, PiiSpec):  # /Contents stores the exact string — no remap
                self.rec.record(it, part="annotation", detail={"page": page})

    # ------------------------------------------------------------------ form field
    def form_field(self, name: str, spec: PiiSpec) -> None:
        page = self.page_no
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = spec.surface
        w.rect = fitz.Rect(_MARGIN, self.y, _MARGIN + 240, self.y + 20)
        self.page.add_widget(w)
        self.y += 26
        self.rec.record(spec, part="form_field", detail={"field": name, "page": page})

    # ------------------------------------------------------------------ attachment
    def attachment(self, filename: str, items: list) -> None:
        text = "".join(it if isinstance(it, str) else it.surface for it in items)
        self.doc.embfile_add(filename, text.encode("utf-8"))
        for it in items:
            if isinstance(it, PiiSpec):
                self.rec.record(it, part="attachment", detail={"file": filename})

    # ------------------------------------------------------------------ metadata / xmp
    def set_metadata(self, author_spec: PiiSpec, xmp_creator_spec: PiiSpec) -> None:
        self._author = author_spec
        self._xmp_creator = xmp_creator_spec
        self.rec.record(author_spec, part="metadata", detail={"field": "author"})
        self.rec.record(xmp_creator_spec, part="xmp", detail={"field": "dc:creator"})

    def _apply_metadata(self) -> None:
        if self._author is not None:
            self.doc.set_metadata({"author": self._author.surface, "title": self.rec.doc_type})
        if self._xmp_creator is not None:
            self.doc.set_xml_metadata(_xmp_packet(self._xmp_creator.surface))

    # ------------------------------------------------------------------ save
    def save(self, path: Path) -> None:
        self._flush()
        self._apply_metadata()
        if self.image_only:
            self.rec.text_layer = False
            self.rec.must_be_refused = True
            img_doc = fitz.open()
            for pg in self.doc:
                pix = pg.get_pixmap(dpi=150)
                ipg = img_doc.new_page(width=pix.width, height=pix.height)
                ipg.insert_image(ipg.rect, pixmap=pix)
            img_doc.save(str(path), garbage=4, deflate=True)
            img_doc.close()
        else:
            self.doc.save(str(path), garbage=4, deflate=True)
        self.doc.close()


def _xmp_packet(creator: str) -> str:
    from xml.sax.saxutils import escape

    return (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator><rdf:Seq><rdf:li>{escape(creator)}</rdf:li></rdf:Seq></dc:creator>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    )
