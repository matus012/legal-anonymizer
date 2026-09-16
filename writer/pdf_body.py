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

import re
import unicodedata

import fitz

from detect.config import DetectConfig
from detect.core import detect_with_failures
from detect.normalize import strip_format_chars
from writer.decisions import RedactionDecisions
from writer.labelmap import LabelMap, make_snippet
from writer.report import write_report


class NoTextLayerError(Exception):
    pass


class UnreadableTextLayerError(NoTextLayerError):
    """Some page carries drawn text whose characters cannot be interpreted.

    A SUBCLASS of NoTextLayerError on purpose: every existing caller that already refuses a
    PDF without a text layer refuses this one too, with no change. The distinct type exists so
    the GUI can say something more useful than "this is a scan" -- the file is not a scan, it
    is a PDF whose font carries no /ToUnicode map, and the fix for the lawyer is different.

    Carries ``pages`` (1-based) so the message can name them."""

    def __init__(self, path: str, pages: list[int]) -> None:
        self.pages = list(pages)
        super().__init__(
            f"PDF has text that cannot be decoded on page(s) "
            f"{', '.join(str(p) for p in self.pages)}; refusing rather than writing a file "
            f"whose visible text was never examined: {path}"
        )


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


# A character is UNDECODABLE when it is a CONTROL character (Cc), a private-use codepoint (Co)
# or unassigned (Cn) -- what a font with no /ToUnicode map yields, since the extractor falls
# back to the raw glyph index.
#
# NOT str.isprintable(), which was the first attempt and was badly wrong. isprintable() is
# False for FORMAT characters (Cf) too, and a PDF text layer is full of legitimate ones:
# PyMuPDF renders an ordinary hyphen in an account number as U+00AD SOFT HYPHEN. Measured
# before shipping: every one of the first six corpus PDFs carries 1-5 soft hyphens, inside
# account numbers, LV references and ISO dates -- text the pipeline reads perfectly and
# eval/extract.py already normalises. The first version of this guard would have refused them
# all. A false refusal is not the safe direction here; it is the tool declining ordinary work,
# which ends with the office switching it off.
_UNDECODABLE_CATEGORIES = frozenset({"Cc", "Co", "Cn"})


def _is_undecodable(ch: str) -> bool:
    return unicodedata.category(ch) in _UNDECODABLE_CATEGORIES


# A page's text is USABLE when enough of its non-space characters are printable. A subset font
# with no /ToUnicode map extracts as raw glyph codes -- control characters -- which are neither
# blank nor readable, and that is the exact gap this ratio closes.
#
# The threshold is deliberately loose. A legal page is overwhelmingly letters, digits and
# punctuation, so a genuine page scores near 1.0 and a garbage page near 0.0; anything in
# between is rare enough that erring toward REFUSAL is right. Refusing costs the lawyer a
# conversion step. Accepting costs them an unredacted file they believe is clean.
_READABLE_MIN_RATIO = 0.80
_READABLE_MIN_CHARS = 8


def page_text_is_readable(text: str) -> bool:
    """Can this page's extracted text be interpreted at all? Blank counts as NOT readable."""
    dense = [ch for ch in text if not ch.isspace()]
    if len(dense) < _READABLE_MIN_CHARS:
        return False
    decodable = sum(1 for ch in dense if not _is_undecodable(ch))
    return decodable / len(dense) >= _READABLE_MIN_RATIO


# How many undecodable characters make a page untrustworthy. THREE, not a ratio.
#
# A ratio was tried first and was too lenient for the shape that actually occurs. The real
# case is not a page of pure garbage -- it is a page where MOST text decodes and one field
# does not, because only that field is set in a subset font. The red-team reproduction is
# exactly that: "Predavajuci: Jan Novak" decodes, the rodné číslo beside it is six control
# characters, and the page scores 86% readable. detect() finds the name, misses the number,
# the number stays drawn on the page, and eval/extract.py reads the same control characters
# so the leak gate agrees the output is clean.
#
# Legitimate extracted text contains essentially NO control characters, so a small absolute
# count is both a tight test and a quiet one: it does not fire on ordinary documents, and it
# fires on the one that matters. Three rather than one leaves room for a stray artefact.
_UNDECODABLE_MAX = 3


def page_has_unreadable_text(text: str) -> bool:
    """Is there text here we CANNOT interpret? This is the dangerous state.

    NOT an empty page -- an image has nothing for us to remove, and a document with no
    readable text at all is refused by has_text_layer() instead. This is a page carrying
    DRAWN TEXT whose characters did not map, which a human reads perfectly and detect()
    silently skips.
    """
    undecodable = sum(1 for ch in text if not ch.isspace() and _is_undecodable(ch))
    return undecodable >= _UNDECODABLE_MAX


def has_text_layer(doc: "fitz.Document") -> bool:
    return any(page_text_is_readable(page.get_text("text")) for page in doc)


def unreadable_pages(doc: "fitz.Document") -> list[int]:
    """1-based page numbers carrying text we cannot interpret."""
    return [i for i, page in enumerate(doc, 1)
            if page_has_unreadable_text(page.get_text("text"))]


# Single source of truth for 'which characters have no glyph': the same rule detect() uses to
# see through them. Importing it means the writer can never drift from the detector -- a needle
# stripped by one rule and produced by another is how a surface becomes unlocatable.
_LINE_SPLIT_RE = re.compile(r"[^\S\n]*\n[^\S\n]*")


def _locate(page, needle: str) -> tuple[list, bool]:
    """Find every rectangle on ``page`` covering ``needle``. Returns ``(rects, complete)``.

    ``page.search_for`` is byte-exact and CANNOT match a needle that contains a line break or
    an invisible character, because neither has a glyph on the page. Before the v1.1
    normalization layer that never came up: detect()'s regexes refused to span a line break, so
    no candidate surface ever contained one. That refusal is exactly what the mutation gate
    condemned -- line_break_mid measured 0.119, and a wrapped PDF text layer had already leaked
    a client number -- so detect() now joins wrapped lines and sees through invisible
    characters. The surfaces it returns are byte-faithful to the document, which means they can
    now legitimately contain a '\\n' or a U+200B, and a single search_for on the whole surface
    will find nothing.

    Falling back matters because of what the alternative is: an unlocatable auto=True surface
    raises RedactionIncompleteError, so without this the detection improvement would turn
    silent misses into loud REFUSALS TO WRITE THE FILE. Three attempts, narrowest first:

      1. the surface exactly as the document holds it;
      2. the surface with format characters (category Cf) removed -- they have no glyph, so a
         zero-width space inside an account number is simply not part of what was drawn;
      3. the surface SPLIT AT ITS LINE BREAKS, each piece located on its own line.

    Step 3 is split at NEWLINES ONLY, never at every space. Splitting a surface into its
    whitespace-separated tokens would put "01" or "25" on the page as a search needle and
    redact every unrelated occurrence of it; splitting at the wrap point yields two substrings
    that are each a genuine contiguous run of the original surface.

    ``complete`` is False when some piece could not be found, so the caller still records the
    surface as skipped and the anti-theatre invariant still fires -- a partially located
    surface must never be reported as fully redacted."""
    rects = page.search_for(needle)
    if rects:
        return rects, True

    flat = strip_format_chars(needle)
    if flat != needle and flat.strip():
        rects = page.search_for(flat)
        if rects:
            return rects, True

    pieces = [p for p in (piece.strip() for piece in _LINE_SPLIT_RE.split(flat)) if p]
    if len(pieces) < 2:
        return [], False

    found: list = []
    complete = True
    for piece in pieces:
        piece_rects = page.search_for(piece)
        if piece_rects:
            found.extend(piece_rects)
        else:
            complete = False
    return found, complete


def _collect_page_redactions(
    page,
    known_entities: list[str] | None,
    labelmap,
    location: str,
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
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
    detected, failures = detect_with_failures(norm, known_entities, config)
    for f in failures:
        # See writer/docx_body.py: a detector that raised leaves its share of this page
        # unredacted, and the absence of its rows is indistinguishable from a clean page.
        labelmap.record_detector_failure(f.detector, location, f.error)
    for cand in detected:
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
                checksum=cand.checksum,
            )
            continue
        needle = raw[cand.start : cand.end]  # on-page glyphs; cand.surface is normalized
        rects, complete = _locate(page, needle)
        if not rects:
            skipped.append(needle)
            continue
        if not complete:
            # Some of the surface WAS located and will be destroyed, but not all of it. That is
            # the worst possible state to report as success, so it is recorded as skipped too:
            # the caller raises RedactionIncompleteError and the reviewer is told which surface
            # to check by hand, rather than receiving a file that looks finished.
            skipped.append(needle)
        label = labelmap.label_for(cand)
        # ONE occurrence per CANDIDATE, recorded before the rect loop: search_for can return
        # several rects for a single span (a wrapped line, a repeated glyph run), and counting
        # per rect would inflate the report's count past the number of spans actually detected.
        labelmap.record_occurrence(
            label, location, cand.surface,
            snippet=make_snippet(norm, cand.start, cand.end),
            checksum=cand.checksum,
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
    config: DetectConfig | None = None,
) -> LabelMap:
    # Reviewer's free-text "redact this too" terms join known_entities BEFORE the LabelMap is
    # built, so extras get real declension-grouped [MENO_N] labels like any GT name.
    if decisions is not None and decisions.extra_terms:
        extras = [t.strip() for t in decisions.extra_terms if t.strip()]
        known_entities = list(known_entities or []) + extras

    doc = fitz.open(in_path)
    # R3-C4: a page whose text we cannot decode is MORE dangerous than a page with none. The
    # glyphs are drawn and a human reads them; detect() sees control characters and removes
    # nothing; and eval/extract.py reads the same control characters, so the leak gate agrees
    # the output is clean. Refuse instead.
    bad_pages = unreadable_pages(doc)
    if bad_pages:
        doc.close()
        raise UnreadableTextLayerError(in_path, bad_pages)

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
            page, known_entities, labelmap, location, decisions=decisions, config=config
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
    write_report(out_path, labelmap.occurrences, labelmap.low_confidence,
                 labelmap.checksums, labelmap.lc_checksums,
                 labelmap.detector_failures)

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
    config: DetectConfig | None = None,
) -> str:
    """Public writer entry — unchanged contract (returns out_path; raises on incomplete).
    ``config=None`` means detect()'s DEFAULT DetectConfig — pre-v1.1 call sites unchanged."""
    _redact_pdf(in_path, out_path, known_entities, decisions, config)
    return out_path


def redact_pdf_collect(
    in_path: str,
    out_path: str,
    known_entities: list[str] | None = None,
    *,
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
) -> "LabelMap":
    """Same redaction, returns the LabelMap (GUI scan harvest). Still raises
    RedactionIncompleteError after writing output+report, exactly like redact_pdf."""
    return _redact_pdf(in_path, out_path, known_entities, decisions, config)
