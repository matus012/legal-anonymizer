"""PDF assembly with the seeded PDF failure modes (context.md §7, §8, §10).

Text is drawn with an embedded Unicode font so Slovak diacritics survive extraction (base-14
fonts drop them). PII is seeded into the text layer, freetext annotations, form-field widgets,
document metadata, XMP, and an embedded attachment — every surface §8.1 says to extract.

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


def _find_font() -> str:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("no Unicode TTF found; Slovak diacritics require an embedded font")


def _text_of(items: list) -> str:
    return "".join(it if isinstance(it, str) else it.surface for it in items)


class PdfBuilder:
    def __init__(self, recorder: Recorder, image_only: bool = False):
        self.rec = recorder
        self.font_path = _find_font()
        self.font = fitz.Font(fontfile=self.font_path)
        self.image_only = image_only
        self.doc = fitz.open()
        self._author: PiiSpec | None = None
        self._xmp_creator: PiiSpec | None = None
        self._new_page()

    # ------------------------------------------------------------------ page flow
    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=_PAGE.width, height=_PAGE.height)
        self.tw = fitz.TextWriter(self.page.rect)
        self.y = _MARGIN

    def _flush(self) -> None:
        self.tw.write_text(self.page)

    @property
    def page_no(self) -> int:
        return self.doc.page_count

    def _wrap(self, text: str, size: float) -> list[str]:
        max_w = _PAGE.width - 2 * _MARGIN
        lines: list[str] = []
        for raw in text.split("\n"):
            words, cur = raw.split(" "), ""
            for w in words:
                cand = w if not cur else f"{cur} {w}"
                if self.font.text_length(cand, size) <= max_w:
                    cur = cand
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            lines.append(cur)
        return lines

    def _write(self, text: str, size: float = 11.0, gap_after: float = 4.0) -> None:
        # Place words at computed x-positions (real gaps, no space glyph). PyMuPDF's
        # get_text() renders an embedded space glyph as U+00A0, which would break matching
        # of multi-word surfaces ("Ján Novák"); real gaps extract as normal spaces.
        space_w = self.font.text_length(" ", size)
        for line in self._wrap(text, size):
            if self.y + _LEADING > _PAGE.height - _MARGIN:
                self._flush()
                self._new_page()
            x = _MARGIN
            baseline = self.y + size
            for word in line.split(" "):
                if not word:
                    x += space_w
                    continue
                self.tw.append((x, baseline), word, font=self.font, fontsize=size)
                x += self.font.text_length(word, size) + space_w
            self.y += _LEADING
        self.y += gap_after

    # ------------------------------------------------------------------ content
    def heading(self, text: str) -> None:
        self._write(text, size=15.0, gap_after=8.0)

    def paragraph(self, items: list) -> None:
        page = self.page_no
        self._write(_text_of(items), size=11.0)
        for it in items:
            if isinstance(it, PiiSpec):
                self.rec.record(it, part="body", detail={"page": page})

    def table(self, rows: list[list[list]]) -> None:
        for row in rows:
            page = self.page_no
            self._write("    ".join(_text_of(c) for c in row), size=11.0, gap_after=2.0)
            for cell in row:
                for it in cell:
                    if isinstance(it, PiiSpec):
                        self.rec.record(it, part="body", detail={"page": page})

    # ------------------------------------------------------------------ annotations
    def annotation(self, items: list) -> None:
        page = self.page_no
        rect = fitz.Rect(_MARGIN, self.y, _PAGE.width - _MARGIN, self.y + 40)
        self.page.add_freetext_annot(rect, _text_of(items), fontsize=10)
        self.y += 46
        for it in items:
            if isinstance(it, PiiSpec):
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
        self.doc.embfile_add(filename, _text_of(items).encode("utf-8"))
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
