"""Phase 5 P2 (context.md): PDF BODY-text redaction -- glyph destruction + label draw.

The killer assertion here is GLYPH DESTRUCTION: a drawn black box over text is redaction
theatre (the glyphs stay in the content stream and any extractor recovers them), so every
test that matters reopens the OUTPUT and asserts get_text("text") no longer contains the
secret. Drawing the label is checked separately -- passing the label test while failing the
destruction test is exactly the failure mode this file exists to catch.

Fixtures are hand-built in-test with fitz (NO corpus import), matching the P1 test file.
"""
from __future__ import annotations

import fitz

from writer.pdf_body import (
    NoTextLayerError,
    RedactionIncompleteError,
    _collect_page_redactions,
    redact_pdf,
)

# A syntactically valid Slovak rodné číslo (divisible-by-11 checksum) so detect() marks it
# auto=True rather than routing it to the review bucket.
RC = "835112/0008"
NAME = "Novák"


def _body_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"Predavajuci: {NAME}", fontname="helv", fontsize=11)
    page.insert_text((72, 130), f"Rodne cislo: {RC}", fontname="helv", fontsize=11)
    page.insert_text((72, 160), "Filler text bez osobnych udajov.", fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def _empty_pdf(path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()


def _widget_pdf(path) -> None:
    """A page carrying the name in a FORM-FIELD WIDGET, not just page content.

    apply_redactions() alone operates on page content and does not reach widget text (both
    the rendered appearance and field_value survive it untouched) -- also insert_text a plain
    body copy so detect() has a text-layer surface to find and trigger redaction at all."""
    doc = fitz.open()
    page = doc.new_page()
    widget = fitz.Widget()
    widget.field_name = "party"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = NAME
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    page.insert_text((72, 150), f"Predavajuci {NAME}", fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def _out_text(path) -> str:
    doc = fitz.open(str(path))
    text = "".join(page.get_text("text") for page in doc)
    doc.close()
    return text


def test_glyphs_are_destroyed_not_merely_covered(tmp_path):
    """THE killer assertion: the secret must be gone from the extracted text layer."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    text = _out_text(out)
    assert NAME not in text
    assert RC not in text


def test_labels_are_drawn_over_the_redacted_spans(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    text = _out_text(out)
    assert "[MENO]" in text
    assert "[RODNE_CISLO]" in text


def test_input_file_is_not_modified(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)
    before = src.read_bytes()

    redact_pdf(str(src), str(out), known_entities=[NAME])

    assert src.read_bytes() == before


def test_unlocatable_surface_raises_redaction_incomplete(tmp_path, monkeypatch):
    """A detected auto surface that search_for cannot locate must NOT be silently dropped."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    original = fitz.Page.search_for

    def blind_to_name(self, needle, *args, **kwargs):
        if needle == NAME:
            return []
        return original(self, needle, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "search_for", blind_to_name)

    try:
        redact_pdf(str(src), str(out), known_entities=[NAME])
        assert False, "expected RedactionIncompleteError"
    except RedactionIncompleteError as e:
        assert NAME in e.surfaces


def test_unlocatable_surface_still_redacts_the_rest(tmp_path, monkeypatch):
    """Raising must not mean skipping the work: the locatable spans are still destroyed."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    original = fitz.Page.search_for

    def blind_to_name(self, needle, *args, **kwargs):
        if needle == NAME:
            return []
        return original(self, needle, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "search_for", blind_to_name)

    try:
        redact_pdf(str(src), str(out), known_entities=[NAME])
    except RedactionIncompleteError:
        pass

    assert out.exists()
    assert RC not in _out_text(out)


def test_widget_text_is_destroyed_not_left_in_field_value(tmp_path):
    """Corpus PDFs carry body PII inside form-field widgets, not just page content.

    PyMuPDF's apply_redactions() alone does not reach widget text: both the visible
    appearance (picked up by get_text) and the underlying field_value survive it. This is
    the widget-only leak -- a generic text redaction test does not exercise this path."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _widget_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    assert NAME not in _out_text(out)

    doc = fitz.open(str(out))
    for page in doc:
        for widget in page.widgets():
            assert NAME not in (widget.field_value or "")
    doc.close()


def test_no_text_layer_still_refuses(tmp_path):
    """P1 regression guard: P2 must not have loosened the scanned-PDF refusal."""
    src = tmp_path / "empty.pdf"
    out = tmp_path / "empty_out.pdf"
    _empty_pdf(src)

    try:
        redact_pdf(str(src), str(out))
        assert False, "expected NoTextLayerError"
    except NoTextLayerError as e:
        assert str(src) in str(e)

    assert not out.exists()


class _FakeRect:
    """search_for return stand-in -- _collect_page_redactions only appends these, never
    inspects them, so an empty marker class is sufficient."""


class _StubPage:
    """Duck-typed fitz.Page stand-in exposing only .get_text/.search_for, the two methods
    _collect_page_redactions uses.

    Reproduces the U+00AD SOFT HYPHEN corpus bug without a rendered PDF fixture: no available
    fitz font preserves U+00AD as a distinct glyph through insert_text/get_text (Base-14 "helv"
    collapses it to a literal '-'; PyMuPDF's bundled non-Base-14 fonts either drop it or cannot
    encode it), so a real PDF cannot carry U+00AD on-page text for this test to exercise -- the
    stub carries it directly in the string search_for matches against.
    """

    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, kind: str) -> str:
        assert kind == "text"
        return self._text

    def search_for(self, needle: str) -> list:
        # Mimics fitz: matches only the literal on-page glyph string.
        return [_FakeRect()] if needle in self._text else []


# The corpus renders some identifiers with U+00AD SOFT HYPHEN as the separator instead of '-'.
_SH = chr(0xAD)
_SOFT_HYPHEN_TEXT = f"datum 1953{_SH}11{_SH}27 , znacka V{_SH}237/2023 ."


def test_collect_normalizes_soft_hyphen_for_detect_and_locates_raw_glyphs():
    """detect() only recognizes DATUM/SPISOVA_ZNACKA with '-' as the separator, but the page
    glyphs carry U+00AD. Both must still be found and correctly labelled from one page string
    that mixes the two."""
    page = _StubPage(_SOFT_HYPHEN_TEXT)

    pairs, skipped = _collect_page_redactions(page, None)

    labels = [lbl for _rect, lbl in pairs]
    assert "[DATUM]" in labels
    assert "[SPISOVA_ZNACKA]" in labels
    assert skipped == []


def test_collect_pre_fix_would_skip_soft_hyphen_surfaces():
    """RED-proving discriminator against the pre-fix implementation.

    Verified directly (detect() fed the raw U+00AD text, no normalization): it emits ZERO
    candidates, because the DATUM/SPISOVA_ZNACKA regexes require '-', not U+00AD -- so
    pre-fix pairs == [] AND skipped == [] (nothing is ever detected to locate or skip in the
    first place). This asserts the post-fix truth, which is therefore false pre-fix for that
    reason (len(pairs) == 0) and true post-fix (len(pairs) >= 2, nothing skipped).
    """
    page = _StubPage(_SOFT_HYPHEN_TEXT)

    pairs, skipped = _collect_page_redactions(page, None)

    assert len(pairs) >= 2 and skipped == []
