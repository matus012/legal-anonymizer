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

from writer.labelmap import LabelMap
from writer.pdf_body import (
    NoTextLayerError,
    RedactionIncompleteError,
    _collect_page_redactions,
    redact_pdf,
)
from writer.report import report_path_for

# A syntactically valid Slovak rodné číslo (divisible-by-11 checksum) so detect() marks it
# auto=True rather than routing it to the review bucket.
RC = "835112/0008"
# SHAPE-valid but CHECKSUM-invalid (one digit off RC): detect() still returns it as a
# RODNE_CISLO Candidate, but with auto=False -- the low-confidence / reviewer bucket.
# Probed, not assumed: detect("Rodne cislo: 835112/0009", None) -> auto False.
RC_LOWCONF = "835112/0009"
NAME = "Novák"
# Second party for the cross-page numbering fixture. Both surnames are Latin-1 encodable, so
# the Base-14 "helv" font renders them as distinct glyphs that search_for can re-locate.
NAME_B = "Horák"


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


def _two_party_pdf(path) -> None:
    """TWO pages, party A on page 1, party B AND party A again on page 2.

    This is the fixture that can tell a per-page labeller from a document-global one: a
    LabelMap rebuilt per page would restart its counter and re-mint A as [MENO_1] on page 1
    and B as [MENO_1] on page 2, collapsing two distinct parties into one label."""
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), f"Predavajuci: {NAME}", fontname="helv", fontsize=11)
    p2 = doc.new_page()
    p2.insert_text((72, 100), f"Kupujuci: {NAME_B}", fontname="helv", fontsize=11)
    p2.insert_text((72, 130), f"Svedok: {NAME}", fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def _low_conf_pdf(path) -> None:
    """A page whose only PII-shaped surface is the CHECKSUM-INVALID rodne cislo (auto=False).

    Also carries an auto=True name so the page is not a degenerate no-redaction case."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"Predavajuci: {NAME}", fontname="helv", fontsize=11)
    page.insert_text((72, 130), f"Rodne cislo: {RC_LOWCONF}", fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def _report_text(out) -> str:
    """Read the report the pass wrote NEXT TO ``out`` -- path derived, never passed."""
    with open(report_path_for(str(out)), encoding="utf-8") as fh:
        return fh.read()


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
    assert "[MENO_1]" in text
    assert "[RODNE_CISLO_1]" in text


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

    pairs, skipped = _collect_page_redactions(page, None, LabelMap(None), "page_1")

    labels = [lbl for _rect, lbl in pairs]
    assert "[DATUM_1]" in labels
    assert "[SPISOVA_ZNACKA_1]" in labels
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

    pairs, skipped = _collect_page_redactions(page, None, LabelMap(None), "page_1")

    assert len(pairs) >= 2 and skipped == []


# --- P4: LabelMap numbering + the per-document report -------------------------------------


def test_report_file_is_written_next_to_the_output(tmp_path):
    """The pass must emit <out stem>_report.txt beside the redacted PDF, with the REDACTED row
    for the name: TYPE, label, count and the page location the occurrence was captured at."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    assert (tmp_path / "out_report.txt").exists()
    report = _report_text(out)
    assert "MENO | [MENO_1] | 1 | page_1" in report


def test_label_numbering_is_document_global_across_pages(tmp_path):
    """Numbering is a DOCUMENT-global property, not a per-page one.

    Party A appears on both pages and must carry the SAME number on both; party B, first seen
    on page 2, must get the NEXT number rather than reusing A's. The report then shows A once
    with count 2 spanning both pages, and B with count 1 -- counts are PER CANDIDATE, so a
    name that search_for located via several rects still contributes exactly one occurrence."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _two_party_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME, NAME_B])

    doc = fitz.open(str(out))
    page_texts = [page.get_text("text") for page in doc]
    doc.close()

    assert NAME not in page_texts[0] and NAME not in page_texts[1]
    assert NAME_B not in page_texts[1]
    # Party A: same label on BOTH pages. Party B: a distinct, later number.
    assert "[MENO_1]" in page_texts[0]
    assert "[MENO_1]" in page_texts[1]
    assert "[MENO_2]" in page_texts[1]
    assert "[MENO_2]" not in page_texts[0]

    report = _report_text(out)
    assert "MENO | [MENO_1] | 2 | page_1, page_2" in report
    assert "MENO | [MENO_2] | 1 | page_2" in report


def test_low_confidence_surface_is_left_intact_and_reported(tmp_path):
    """auto=False spans are the reviewer's bucket: NOT redacted (still in the text layer),
    but recorded in the report's LOW CONFIDENCE section so the reviewer knows to look."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _low_conf_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    text = _out_text(out)
    assert RC_LOWCONF in text  # left intact BY DESIGN -- never silently redacted
    assert NAME not in text    # ...while the auto span on the same page still went

    report = _report_text(out)
    lowconf_section = report.split("[LOW CONFIDENCE / NOT REDACTED]", 1)[1]
    assert f"RODNE_CISLO | {RC_LOWCONF} | page_1" in lowconf_section


def test_report_does_not_leak_the_redacted_surface(tmp_path):
    """The report is a record of WHAT was removed and WHERE -- label, count, locations. If it
    echoed the surface it would be a plaintext copy of the PII sitting next to the redacted
    file, undoing the redaction for anyone who reads the directory."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _body_pdf(src)

    redact_pdf(str(src), str(out), known_entities=[NAME])

    report = _report_text(out)
    assert NAME not in report
    assert RC not in report
