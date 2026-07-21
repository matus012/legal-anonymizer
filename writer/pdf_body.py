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

Scope of this round: body text, plus the doc-level surfaces. The Info dictionary, the XMP
packet and embedded file attachments ARE now scrubbed (P3), immediately before the save.
Form-field widget text and annotations are not scrubbed by a separate step -- bake() flattens
them into page content, where the same collect/apply/draw loop destroys them. One Info key is
NOT cleared: doc.metadata['format'], which MuPDF derives from the PDF header version rather
than the Info dictionary; it is a format constant ('PDF 1.7'), never PII.

P4 -- labels and the report. ONE writer.labelmap.LabelMap is built per document and threaded
through every page, so a party numbered [MENO_1] on page 1 is [MENO_1] on page 9 too and a
second party gets [MENO_2] rather than restarting the counter (the DOCX writer does the same
with the same unit). Each page tags its captures with location "page_<n>". After the save,
writer.report.write_report emits <out stem>_report.txt next to the output -- including on the
RedactionIncompleteError path, since a partial output is exactly the case a reviewer needs the
record for. Occurrences are counted PER CANDIDATE, not per rect: one name located by
search_for at three rects is one redacted occurrence, three destroyed boxes.
"""
from __future__ import annotations

import fitz

from detect.core import detect
from writer.decisions import RedactionDecisions
from writer.labelmap import LabelMap, make_snippet
from writer.report import write_report


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


def has_text_layer(doc: "fitz.Document") -> bool:
    return any(page.get_text("text").strip() for page in doc)


def _collect_page_redactions(
    page,
    known_entities: list[str] | None,
    labelmap,
    location: str,
    decisions: RedactionDecisions | None = None,
):
    """Stage 1 of the per-page pass: run detect() on the page text and turn every auto=True
    candidate into (rect, label) pairs via search_for.

    ``labelmap`` is the ONE document-global LabelMap (never per-page: a fresh map per page would
    restart the counter and re-mint two different parties as [MENO_1]) and ``location`` is this
    page's report tag; both are required, so no caller can silently fall back to an unnumbered
    label or an untagged capture.

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
        redact = cand.auto
        if decisions is not None:
            key = (cand.type, labelmap.group_key(cand))
            if cand.auto and key in decisions.suppress_groups:
                redact = False
            elif not cand.auto and key in decisions.force_groups:
                redact = True
        if not redact:
            # Left intact by design (low-confidence, or human-suppressed) but RECORDED, so
            # the report tells the reviewer where to look instead of dropping it silently.
            labelmap.record_low_confidence(
                location, cand.type, cand.surface,
                snippet=make_snippet(norm, cand.start, cand.end),
            )
            continue
        needle = raw[cand.start : cand.end]  # on-page glyphs; cand.surface is normalized
        rects = page.search_for(needle)
        if not rects:
            skipped.append(needle)
            continue
        label = labelmap.label_for(cand)
        # ONE occurrence per CANDIDATE, recorded before the rect loop: search_for can return
        # several rects for a single span (a wrapped line, a repeated glyph run), and counting
        # per rect would inflate the report's count past the number of spans actually detected.
        labelmap.record_occurrence(
            label, location, cand.surface,
            snippet=make_snippet(norm, cand.start, cand.end),
        )
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


def _scrub_document_surfaces(doc: "fitz.Document") -> None:
    """Clear the three DOC-LEVEL surfaces the leak harness reads: Info dictionary, XMP packet,
    and embedded file attachments.

    None of these are reachable by the per-page loop -- apply_redactions() only touches page
    content -- so a document whose body is perfectly redacted still leaks a name sitting in
    /Author. Must run BEFORE doc.save, since that is what writes these surfaces out.

    set_metadata({}) empties every SETTABLE key at once. A partial dict is NOT a merge and is
    not a safe substitute: set_metadata({"format": ""}) was verified to leave an existing
    /Author value fully intact. The one key that survives is doc.metadata['format'], which
    MuPDF derives from the PDF header version rather than the Info dictionary and no API here
    can clear -- it is a format constant ('PDF 1.7'), never PII.

    Attachment names are materialized into a list before deleting: embfile_del() mutates the
    document's embedded-file table, so deleting while iterating it live would skip entries."""
    doc.set_metadata({})
    doc.del_xml_metadata()
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)


def _redact_pdf(
    in_path: str,
    out_path: str,
    known_entities: list[str] | None,
    decisions: RedactionDecisions | None,
) -> LabelMap:
    # Reviewer's free-text "redact this too" terms join known_entities BEFORE the LabelMap is
    # built, so extras get real declension-grouped [MENO_N] labels like any GT name.
    if decisions is not None and decisions.extra_terms:
        extras = [t.strip() for t in decisions.extra_terms if t.strip()]
        known_entities = list(known_entities or []) + extras

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

    # ONE LabelMap for the whole document, built AFTER the refusal check (a refused PDF writes
    # no output, so it must get no report either) and threaded through every page below -- that
    # threading is what makes the [TYPE_N] numbering document-global rather than per-page.
    labelmap = LabelMap(known_entities)

    skipped: list[str] = []
    for i, page in enumerate(doc, start=1):
        location = f"page_{i}"
        pairs, page_skipped = _collect_page_redactions(
            page, known_entities, labelmap, location, decisions=decisions
        )
        skipped.extend(page_skipped)

        for rect, _label in pairs:
            page.add_redact_annot(rect, fill=(0, 0, 0))
        # Apply BEFORE drawing: a label drawn first would be destroyed along with the glyphs.
        page.apply_redactions()
        for rect, label in pairs:
            _draw_label(page, rect, label)

    _scrub_document_surfaces(doc)

    doc.save(out_path, garbage=4, deflate=True)
    doc.close()

    # P4: the report is written BEFORE the incomplete-redaction raise, deliberately. A partial
    # output is precisely the file whose record a reviewer needs; writing the report after the
    # raise would leave the worst case as the one case with no record at all.
    write_report(out_path, labelmap.occurrences, labelmap.low_confidence)

    # Every page was attempted and the (partial) output written -- but the caller must be told,
    # loudly, that this file is not fully redacted.
    if skipped:
        raise RedactionIncompleteError(skipped)

    return labelmap


def redact_pdf(
    in_path: str,
    out_path: str,
    known_entities: list[str] | None = None,
    *,
    decisions: RedactionDecisions | None = None,
) -> str:
    """Public writer entry — unchanged contract (returns out_path; raises on incomplete)."""
    _redact_pdf(in_path, out_path, known_entities, decisions)
    return out_path


def redact_pdf_collect(
    in_path: str,
    out_path: str,
    known_entities: list[str] | None = None,
    *,
    decisions: RedactionDecisions | None = None,
) -> "LabelMap":
    """Same redaction, returns the LabelMap (GUI scan harvest). Still raises
    RedactionIncompleteError after writing output+report, exactly like redact_pdf."""
    return _redact_pdf(in_path, out_path, known_entities, decisions)
