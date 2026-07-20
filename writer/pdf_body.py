"""Phase 5 P1+P2 (context.md): PDF text-layer detection, refusal, and BODY-text redaction.

P1 -- refusal. A PDF has no text layer when every page's extracted text is empty: get_text("text")
returns "" for a purely-image page (verified against data/synthetic/scan_image_only_000.pdf).
Redacting such a PDF by text-span matching would be unsafe (nothing to match against), so
redact_pdf() raises NoTextLayerError instead of writing a false-safe copy.

P2 -- body redaction. Two things make this correct rather than theatre:

  * GLYPH DESTRUCTION, not covering. Drawing a filled rectangle over text leaves the glyphs in
    the content stream, where any extractor recovers them verbatim. Only
    page.add_redact_annot(rect) + page.apply_redactions() genuinely removes them. Everything
    else in this module is arranged around getting those two calls right.
  * LOCATION VIA search_for, NOT OFFSETS. detect() returns character offsets into
    get_text("text"), but that string is NOT positionally reversible to glyph bboxes -- it
    inserts line-break characters that rawdict does not -- so an offset->bbox mapping would be
    silently wrong. Instead each candidate SURFACE is re-located with page.search_for(surface),
    which is byte-exact (it matches NBSP U+00A0 needles as they appear in the page).
  * BAKE BEFORE REDACT. Some corpus PDFs carry body PII inside form-field widgets. PyMuPDF
    1.28's apply_redactions() only ever touches page CONTENT, so widget text (both its
    on-page appearance and its field_value) is otherwise unreachable and leaks; doc.bake()
    flattens widgets/annotations into permanent page content first so the same collect/apply
    loop reaches them too.

Ordering constraint that shapes the loop: search_for cannot run AFTER apply_redactions (the
glyphs it would search for are gone), and a label drawn BEFORE apply_redactions would itself be
redacted. So each page runs in three strict stages -- collect (rect, label) pairs, apply
redactions, then draw the labels into the now-blank rects.

Anti-theatre invariant: a candidate that detect() marked auto=True but search_for could not
locate is NOT silently dropped. Those surfaces are accumulated across all pages and, after the
output has been written, raise RedactionIncompleteError -- the caller must never receive a
partially-redacted file believing it complete.

Scope of this round: body text only. Metadata/XMP/annotations/form fields/attachments are NOT
scrubbed here (P3), and no per-document report is written (P4).
"""
from __future__ import annotations

import fitz

from detect.core import detect


class NoTextLayerError(Exception):
    pass


class RedactionIncompleteError(Exception):
    """Raised when at least one auto=True surface could not be located on its page.

    Carries ``surfaces`` (the unlocatable surface strings, in traversal order) so the caller can
    report exactly what was missed. The output file MAY already have been written when this is
    raised -- that file is partially redacted and must not be treated as safe."""

    def __init__(self, surfaces):
        self.surfaces = list(surfaces)
        super().__init__(
            f"{len(self.surfaces)} detected surface(s) could not be located for redaction: "
            f"{self.surfaces}"
        )


def _placeholder_label(cand) -> str:
    """TEMP labeller -- type-only, no per-entity numbering.

    P4 replaces this with writer.labelmap.LabelMap.label_for, which mints document-global
    ``[TYPE_N]`` labels. LabelMap is deliberately NOT wired in this round: numbering is a
    cross-page, cross-location concern and threading it belongs with the report work."""
    return f"[{cand.type}]"


def has_text_layer(doc: "fitz.Document") -> bool:
    return any(page.get_text("text").strip() for page in doc)


def _collect_page_redactions(page, known_entities: list[str] | None):
    """Stage 1 of the per-page pass: run detect() on the page text and turn every auto=True
    candidate into (rect, label) pairs via search_for.

    Some corpus PDFs render deterministic identifiers (dates, spisove znacky) with U+00AD SOFT
    HYPHEN as the separator instead of '-'; detect()'s regexes require '-' and emit nothing on
    the raw text, so the page text is normalized before detect() runs. Each candidate is then
    LOCATED on the raw glyph substring, not cand.surface -- search_for needs the actual on-page
    glyphs, and cand.surface is the normalized '-' form, which returns zero rects on such a page.

    Returns ``(pairs, skipped)`` where ``skipped`` holds the surfaces search_for could not find.
    Split out from redact_pdf so the skip bookkeeping is unit-testable on its own, and takes
    ``page`` by duck type (needs only .get_text and .search_for)."""
    pairs: list[tuple[fitz.Rect, str]] = []
    skipped: list[str] = []

    raw = page.get_text("text")
    norm = raw.replace(chr(0xAD), "-")  # soft hyphen -> hyphen-minus; offset-preserving (1:1)
    for cand in detect(norm, known_entities):
        if not cand.auto:
            continue  # low-confidence -> reviewer's bucket, left intact by design
        needle = raw[cand.start : cand.end]  # on-page glyphs; cand.surface is normalized
        rects = page.search_for(needle)
        if not rects:
            skipped.append(needle)
            continue
        label = _placeholder_label(cand)
        for rect in rects:
            pairs.append((rect, label))

    return pairs, skipped


def _draw_label(page, rect, label: str) -> None:
    """Draw ``label`` white-on-black inside ``rect`` (which apply_redactions has just blanked).

    Text does NOT reflow -- the label occupies exactly the footprint of the removed span, so it
    is shrunk until insert_textbox reports it fits (a negative return means nothing was drawn,
    which would silently lose the label and break the 'reviewer can see WHAT was removed'
    property). Falls back to insert_text at the top-left if even the floor size will not fit."""
    fontsize = max(1.0, min(rect.height, 11.0))
    while fontsize >= 3.0:
        if page.insert_textbox(rect, label, fontsize=fontsize, color=(1, 1, 1), align=0) >= 0:
            return
        fontsize -= 0.5
    page.insert_text(
        (rect.x0, rect.y1), label, fontsize=max(3.0, min(rect.height, 6.0)), color=(1, 1, 1)
    )


def redact_pdf(in_path: str, out_path: str, known_entities: list[str] | None = None) -> str:
    doc = fitz.open(in_path)
    if not has_text_layer(doc):
        doc.close()
        raise NoTextLayerError(
            f"PDF has no text layer (scanned/image-only), cannot redact safely: {in_path}"
        )

    # Corpus PDFs carry body PII inside form-field widgets too. apply_redactions() operates
    # on page CONTENT only and never reaches widget text (both the rendered appearance and
    # field_value survive it), so bake() flattens widgets/annotations into permanent page
    # content BEFORE the collect/apply/draw loop -- that is what makes them reachable at all.
    doc.bake()

    skipped: list[str] = []
    for page in doc:
        pairs, page_skipped = _collect_page_redactions(page, known_entities)
        skipped.extend(page_skipped)

        for rect, _label in pairs:
            page.add_redact_annot(rect, fill=(0, 0, 0))
        # Apply BEFORE drawing: a label drawn first would be destroyed along with the glyphs.
        page.apply_redactions()
        for rect, label in pairs:
            _draw_label(page, rect, label)

    doc.save(out_path, garbage=4, deflate=True)
    doc.close()

    # Every page was attempted and the (partial) output written -- but the caller must be told,
    # loudly, that this file is not fully redacted.
    if skipped:
        raise RedactionIncompleteError(skipped)

    return out_path
