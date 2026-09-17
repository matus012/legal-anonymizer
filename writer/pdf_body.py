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
from detect.normalize import mojibake_is_unrepairable, strip_format_chars
from writer.decisions import RedactionDecisions
# The SAME predicate the DOCX writer uses on a relationship target (R6-02). Round 5 confirmed
# _scrub_rel_targets removes "mailto:jan.novak@advokat.sk" from a .docx; the identical address
# in a PDF link annotation survived, and two formats disagreeing about the same string is a bug
# in itself. Its right home is a format-neutral writer/targets.py -- it is a predicate about a
# URI, and neither format owns it -- but moving it would edit writer/docx_body.py, so it is
# imported from where it lives rather than copied. There is no cycle: docx_body does not import
# this module.
from writer.docx_body import _target_carries_pii
from writer.errors import PasswordProtectedError, UnreadableDocumentError
from writer.labelmap import LabelMap, make_snippet
from writer.pdf_view import (associated_filespecs, embedded_file_streams, rehide,
                             unhide)
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


# A page is SHREDDED when most of its tokens are single characters: the glyph advances did not
# match the text, so every letter became its own word. Thresholds are on the PAGE and require a
# substantial amount of text, because Slovak notarial practice letter-spaces HEADINGS and party
# designations on purpose (razvetrené písmo) and a spaced heading must not cost the document its
# redaction.
_SHRED_MIN_TOKENS = 20
_SHRED_MAX_SINGLE_RATIO = 0.50


def page_is_shredded(text: str) -> bool:
    """Is this page's text layer broken into single characters?

    Measured against the whole corpus before shipping: 0 of 71 PDFs trip it, and the
    letter-spaced attack at every tracking value the red team used does.
    """
    tokens = text.split()
    if len(tokens) < _SHRED_MIN_TOKENS:
        return False
    singles = sum(1 for t in tokens if len(t) == 1 and t.isalnum())
    return singles / len(tokens) > _SHRED_MAX_SINGLE_RATIO


def shredded_pages(doc: "fitz.Document") -> list[int]:
    """1-based page numbers whose text layer is shredded into single characters."""
    return [i for i, page in enumerate(doc, 1) if page_is_shredded(page.get_text("text"))]


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
# PRIVATE USE (Co) is NOT undecodable, and including it was a false-refusal bug (red-team
# round 4, R4-P3). Word's default bullet extracts as U+F0B7, a private-use codepoint, because
# that is how Symbol and Wingdings address their glyphs -- legitimately, in ordinary documents.
# Three bullets were enough to refuse a file, and adding them to every corpus page refused 70
# of 71. A symbol font is not a broken font.
_UNDECODABLE_CATEGORIES = frozenset({"Cc", "Cn"})


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
# ONE is enough, now that private use is excluded. Legitimate extracted text contains no
# control characters at all, so the absolute 3 this used to be was pure slack -- and red-team
# round 4 (R4-I2) walked through it: a subset font that fails on just the two diacritics of a
# Slovak surname produces two undecodable characters, which the old threshold accepted, and
# the name was then undetected, still drawn on the page, and invisible to the leak gate.
_UNDECODABLE_MAX = 1


def page_has_unreadable_text(text: str) -> bool:
    """Is there text here we CANNOT interpret? This is the dangerous state.

    NOT an empty page -- an image has nothing for us to remove, and a document with no
    readable text at all is refused by has_text_layer() instead. This is a page carrying
    DRAWN TEXT whose characters did not map, which a human reads perfectly and detect()
    silently skips.
    """
    undecodable = sum(1 for ch in text if not ch.isspace() and _is_undecodable(ch))
    return undecodable >= _UNDECODABLE_MAX


class ShreddedTextLayerError(NoTextLayerError):
    """A page's text layer is broken into single characters (see page_is_shredded).

    A NoTextLayerError subclass for the same reason as UnreadableTextLayerError: every caller
    that already refuses an unreadable PDF refuses this one unchanged, and the distinct type
    exists only so the GUI can explain which of the two it is, because the remedy differs.

    Carries ``pages`` (1-based)."""

    def __init__(self, path: str, pages: list[int]) -> None:
        self.pages = list(pages)
        super().__init__(
            f"PDF text layer is broken into single characters on page(s) "
            f"{', '.join(str(p) for p in self.pages)}; refusing rather than writing a file "
            f"whose text was never readable: {path}"
        )


class MojibakeTextLayerError(NoTextLayerError):
    """A page's text layer is a cp1250 (Central European) text drawn with /WinAnsiEncoding,
    and the mis-decoding cannot be undone on this page.

    A NoTextLayerError subclass for the same reason as the two above: every caller that
    already refuses a PDF whose text cannot be read refuses this one unchanged, and the
    distinct type exists so the GUI can say which of the three it is, because the remedy
    differs. Here the remedy is to re-export the PDF from the system that produced it, or to
    print it to a new PDF from a viewer that has the font.

    WHY THIS IS NOT COVERED BY THE OTHER TWO. Every character the failure produces is a letter
    or a punctuation sign, never a control character, so page_has_unreadable_text is False;
    and the token structure is untouched, so page_is_shredded is False. The page is ACCEPTED by
    both, reads almost perfectly to a human, and detect() silently fails to match the Slovak
    words it contains. Red-team round 4, R4-I3.

    WHY A REFUSAL AND NOT A REPAIR. Most of this damage IS repaired, offset-preservingly, by
    detect/normalize.py. This error is raised only for the part that cannot be: the WinAnsi
    code page leaves five bytes undefined, so "Ť", "ť" and "Ź" all arrive as one and the same
    U+FFFD, and "ť" is one of the commonest letters in Slovak. Picking one of the three would
    be inventing document text, and the letter it replaced can sit inside a party's surname.

    Carries ``pages`` (1-based)."""

    def __init__(self, path: str, pages: list[int]) -> None:
        self.pages = list(pages)
        super().__init__(
            f"PDF text layer was written in the Central European code page and drawn as "
            f"Western European on page(s) "
            f"{', '.join(str(p) for p in self.pages)}; the Slovak letters lost there cannot "
            f"be restored, so NO FILE WAS WRITTEN -- re-export or re-print the PDF and try "
            f"again: {path}"
        )


def page_is_unrepairable_mojibake(text: str) -> bool:
    """Does this page show the cp1250-as-WinAnsi signature AND contain a character whose
    repair would be a guess?

    Both halves are required, and the second is what keeps this quiet. U+FFFD on its own is
    not evidence of anything in particular -- a decoder emits it for any byte it could not
    place. It is only when the page ALSO carries the mojibake signature that the U+FFFD has a
    known cause and a known, unrecoverable, meaning.

    Measured before shipping, in the direction that has already gone wrong on this module
    once (an isprintable() guard that would have refused 70 of 71 corpus PDFs): over all 72
    corpus PDFs plus the demo -- 82 pages -- the evidence half fires ZERO times, so this
    refuses NOTHING in the corpus. The count of evidence characters on those pages is itself
    zero, not merely the count of firings."""
    return mojibake_is_unrepairable(text)


def mojibake_pages(doc: "fitz.Document") -> list[int]:
    """1-based page numbers whose mis-decoded text layer cannot be repaired."""
    return [i for i, page in enumerate(doc, 1)
            if page_is_unrepairable_mojibake(page.get_text("text"))]


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


def _is_degenerate(rect) -> bool:
    """Does ``rect`` cover no glyph -- zero width or zero height (R6-09)?

    ``getattr`` rather than ``rect.is_empty`` because _collect_page_redactions takes its page by
    DUCK TYPE (it needs only .get_text and .search_for), which makes the rects that page returns
    duck-typed too: the existing soft-hyphen unit test hands it a marker object with no
    geometry. A stand-in with no is_empty is not a degenerate rect; every real fitz.Rect has it.
    """
    return bool(getattr(rect, "is_empty", False))


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
        # R6-09: search_for can return a DEGENERATE rect -- zero width, ``is_empty`` True. A
        # tagged (PDF/UA) document writes /ActualText for a ligature, an abbreviation or a
        # hyphen-split word, and when the replacement text is longer than the glyph run it
        # covers, MuPDF distributes it over the glyph advances and the surplus characters get
        # zero-width boxes. Measured: Rect(130.355, 530.417, 130.355, 545.091).
        #
        # Such a rect destroys nothing (add_redact_annot covers no glyph) and crashes
        # insert_textbox with "text box must be finite and not empty" -- so before this the
        # lawyer got a bare ValueError, no output and no report on an ORDINARY accessible PDF.
        # The rect is DROPPED, never widened: widening it to something drawable would redact
        # glyphs nobody detected. Dropping it makes the surface partly (or wholly) unredacted,
        # which is exactly what ``skipped`` means, so it goes through the same bookkeeping and
        # the anti-theatre invariant still fires.
        drawable = [r for r in rects if not _is_degenerate(r)]
        if len(drawable) != len(rects):
            complete = False
        rects = drawable
        if not rects:
            skipped.append(needle)
            # R6-10: this ``continue`` is why the report used to read as "nothing was found"
            # for a document that is under-redacted -- record_occurrence is below it and
            # record_low_confidence is on the other branch, so a detected-but-unlocatable
            # surface reached NEITHER.
            labelmap.record_unlocated(location, cand.type, cand.surface)
            continue
        if not complete:
            labelmap.record_unlocated(location, cand.type, cand.surface)
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
    property). Falls back to insert_text at the top-left if even the floor size will not fit.

    An EMPTY rect draws nothing and returns (R6-09). _collect_page_redactions already drops
    degenerate rects, so this guard exists for the next caller: insert_textbox raises
    ValueError on a zero-width rect, and that ValueError reached the lawyer as PyMuPDF's
    "text box must be finite and not empty" with no output and no report. There is nothing to
    label here in any case -- a zero-width box covers no glyph, so nothing was destroyed."""
    if rect.is_empty:
        return
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
    # R6-01: /Outlines. A court or cadastre PDF's bookmarks ARE its section headings --
    # "Kupna zmluva - Maria Kovacova", "Rodne cislo 855612/7788" -- and nothing here called
    # get_toc/set_toc, so they shipped verbatim on ``outline``, a named TEXT surface the leak
    # gate counts with no discount.
    #
    # WHY DELETING BEATS REWRITING THE TITLES THROUGH detect(). A rewrite has to be right about
    # every title or it ships one: the titles are not page text, so a miss is invisible to the
    # per-page loop that just destroyed the same name on the page, and there is no moment at
    # which a reviewer sees a bookmark. It would also have to rebuild the outline TREE (set_toc
    # takes [level, title, page] rows) from titles it rewrote, so a detector failure on one row
    # would corrupt the nesting of the rest. Deleting is unconditional and cannot half-succeed.
    #
    # THE COST, HONESTLY: the reader's bookmark pane goes empty. On a 200-page cadastre file
    # that is a real loss of navigation -- but it is a NAVIGATION loss, not a content loss:
    # every heading a bookmark points at is still on its page, where the reader can search for
    # it. This module already makes exactly that trade for embedded attachments above.
    doc.set_toc([])
    _scrub_associated_files(doc)
    _scrub_metadata_streams(doc)
    _scrub_catalogue(doc)


def _scrub_associated_files(doc: "fitz.Document") -> None:
    """Delete every ASSOCIATED FILE -- the attachments ``embfile_names()`` does not list (R6-04).

    The loop above enumerates the /Names /EmbeddedFiles name tree. An associated file (PDF 2.0
    §14.13, what PDF/A-3 is built on and what a hybrid cadastre export or an e-invoice uses)
    hangs off /AF instead, is in no name tree, and is kept by garbage=4 because it is reachable.
    A .docx attached that way shipped with the client's name, rodne cislo, PSC and bank code in
    it while the page was correctly redacted and the report said the document was processed.

    DELETING is not a new decision -- it is the policy this module already applies to every
    attachment three lines above. Both halves go: the /EF stream BODIES are emptied (so the
    payload cannot come back even from an object dump) and the file spec is reduced to its type,
    which takes the file NAME and /Desc with it -- a description reading "Priloha ku spisu Maria
    Kovacova" is PII in its own right.

    The walk itself is ``writer.pdf_view.associated_filespecs``, shared with ``eval/extract.py``:
    a writer that enumerates attachments differently from the grader is how R6-04 stayed
    invisible to every surface at once."""
    for filespec in associated_filespecs(doc):
        for stream in embedded_file_streams(doc, filespec):
            doc.update_object(stream, "<<>>")
            doc.update_stream(stream, b"", new=True)
        doc.update_object(filespec, "<< /Type /Filespec >>")
    doc.xref_set_key(doc.pdf_catalog(), "AF", "null")
    for page in doc:
        doc.xref_set_key(page.xref, "AF", "null")


def _scrub_metadata_streams(doc: "fitz.Document") -> None:
    """Empty EVERY /Metadata XMP packet in the file, not only the catalogue's (R6-07).

    ``del_xml_metadata()`` clears the catalogue's /Metadata. A /Metadata on a PAGE, on an
    XObject or on an embedded file stream is a different object and survived it verbatim --
    a full XMP packet with dc:creator and dc:title, which any reader displays.

    By POSITION: every object in the xref is asked for the key, rather than the writer
    enumerating the levels it happened to think of. That is the discipline the round asked for,
    and it is what makes the XObject and embedded-file levels (§7, suspected but unconfirmed)
    closed by the same four lines as the page level."""
    for xref in range(1, doc.xref_length()):
        try:
            kind, value = doc.xref_get_key(xref, "Metadata")
        except Exception:  # noqa: BLE001 -- a free or malformed object owns no keys
            continue
        if kind == "null":
            continue
        if kind == "xref":
            packet = int(value.split()[0])
            doc.update_object(packet, "<<>>")
            doc.update_stream(packet, b"", new=True)
        doc.xref_set_key(xref, "Metadata", "null")


# The catalogue keys that are NAVIGATION or SCRIPTING and are deleted whole. Each is a door
# onto the same kind of payload -- a name, a label, a script -- and none of them is document
# content: deleting costs the reader a jump target, exactly the trade /Outlines and the
# attachments already make, and unlike a rewrite it cannot half-succeed.
#
# /Names goes ENTIRELY, not just its /Dests and /JavaScript sub-trees (§7's two unconfirmed
# doors). What is left in it -- /AP, /Pages, /Templates, /IDS, /URLS, /Renditions,
# /EmbeddedFiles -- is navigation and scripting too, and /EmbeddedFiles has already been
# emptied above.
_CATALOGUE_DOORS = ("Dests", "PageLabels", "OpenAction", "AA", "Names", "Collection")
_PAGE_DOORS = ("AA",)


def _string_spans(source: str) -> list[tuple[int, int]]:
    """(start, end) of the CONTENT of every PDF string in one object's source.

    Both spellings, because Acrobat writes either: a literal ``(Podpis Marie Kovacovej)`` --
    with nesting and backslash escapes, so this is a scanner and not a regex -- and a hex
    string ``<FEFF0050...>``, which is how anything with a diacritic is stored. ``<<`` and
    ``>>`` are dictionary delimiters and are never strings.

    An unbalanced ``(`` means the source is not something this can rewrite safely, so the scan
    STOPS there and leaves the remainder alone: a half-blanked object is a corrupt object, and
    a corrupt output is worse than the surface it would have cleared."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                if source[j] == "\\":
                    j += 2
                    continue
                depth += 1 if source[j] == "(" else -1 if source[j] == ")" else 0
                j += 1
            if depth:
                break
            spans.append((i + 1, j - 1))
            i = j
            continue
        if ch == "<" and source[i + 1 : i + 2] != "<":
            j = source.find(">", i + 1)
            if j != -1 and all(c in "0123456789abcdefABCDEF \t\r\n" for c in source[i + 1 : j]):
                spans.append((i + 1, j))
                i = j + 1
                continue
        i += 1
    return spans


def _blank_strings(doc: "fitz.Document", xref: int) -> None:
    """Empty every string VALUE in this object's dictionary, whatever key it sits under."""
    source = doc.xref_object(xref, compressed=False) or ""
    spans = _string_spans(source)
    if not spans:
        return
    out, pos = [], 0
    for start, end in spans:
        out.append(source[pos:start])
        pos = end
    out.append(source[pos:])
    doc.update_object(xref, "".join(out))


def _reachable(doc: "fitz.Document", roots: list[int]) -> set[int]:
    seen: set[int] = set()
    stack = list(roots)
    while stack:
        xref = stack.pop()
        if xref in seen or not 0 < xref < doc.xref_length():
            continue
        seen.add(xref)
        try:
            stack.extend(int(x) for x in re.findall(r"(\d+) 0 R",
                                                    doc.xref_object(xref, compressed=False) or ""))
        except Exception:  # noqa: BLE001 -- a free object has no source to walk
            continue
    return seen


def _scrub_catalogue(doc: "fitz.Document") -> None:
    """Clear the document catalogue plane (R6-03): named destinations, page labels,
    JavaScript, optional-content group names, and the structure tree.

    Five mechanisms, one root cause: ``_scrub_document_surfaces`` knew three keys and a PDF
    catalogue has about a dozen. Measured survivors were a destination NAME
    (``Kovacova_Maria_zmluva``, what Word's "Insert bookmark" exports), a page-label prefix
    (``Kovacova-Maria-``, what Bates stamping writes), a string literal inside /OpenAction
    JavaScript, an OCG /Name (``Vrstva klienta Peter Horvath``), and a structure element's
    /Alt -- **what a screen reader speaks over a scanned signature**, invisible on the page, in
    documents Slovak public administration is required to make accessible.

    TWO POLICIES, because the five constructs are not alike:

      * the navigation and scripting doors in ``_CATALOGUE_DOORS`` (and /AA on each page) are
        DELETED whole, like /Outlines;
      * everything else still reachable from the catalogue is blanked BY POSITION -- every
        string value in every object, whatever key holds it. Enumerating "the keys we thought
        of" is what produced this finding, so /OCProperties and /StructTreeRoot are not
        enumerated either: they are simply objects on the catalogue plane, and so is the next
        construct nobody has thought of.

    THE PAGE TREE IS EXCLUDED, and that boundary is load-bearing rather than cosmetic. Page
    content is the plane the redaction loop owns, and the objects under it include font
    dictionaries whose /Registry and /Ordering strings are how a CID font maps glyphs --
    blanking those would turn the output's own text into garbage. /StructTreeRoot reaches back
    into the page tree through each element's /Pg, so without the exclusion this walk arrives
    there by the back door.

    Runs AFTER rehide(), so the /OCProperties it walks is the one that will be saved rather
    than the null the reading view leaves behind."""
    catalogue = doc.pdf_catalog()
    for page in doc:
        for key in _PAGE_DOORS:
            doc.xref_set_key(page.xref, key, "null")
    kind, value = doc.xref_get_key(catalogue, "Pages")
    pages = _reachable(doc, [int(value.split()[0])] if kind == "xref" else [])
    for key in _CATALOGUE_DOORS:
        if doc.xref_get_key(catalogue, key)[0] != "null":
            doc.xref_set_key(catalogue, key, "null")
    plane = (_reachable(doc, [catalogue]) - pages) | {catalogue}
    for xref in sorted(plane):
        if doc.xref_is_stream(xref):
            # A stream's BODY is not rewritable through update_object, and the two stream
            # planes that carry text of their own are already handled: /Metadata packets are
            # emptied above and embedded files are deleted with their file spec.
            continue
        _blank_strings(doc, xref)


# The link-dictionary keys eval/extract.py reads into its ``links`` surface. Deciding on
# EXACTLY the strings the gate grades is the point: anything else is the writer and the gate
# disagreeing about what a link contains, which is how R6-02 happened in the first place.
_LINK_TEXT_KEYS = ("uri", "file", "nameddest", "name")


def _scrub_link_targets(doc: "fitz.Document", known_entities: list[str] | None,
                       config: DetectConfig | None) -> None:
    """Delete every link annotation whose TARGET carries personal data (R6-02).

    doc.bake() flattens what has an APPEARANCE; a Link annotation's payload is its ACTION, and
    an action has no appearance stream, so "mailto:jan.novak@advokat.sk" -- a name and an
    address -- survived the bake untouched on the ``links`` surface. The identical mailto: in a
    .docx IS removed (writer/docx_body._scrub_rel_targets, red-team round 5), so this was the
    two formats disagreeing about the same string.

    The DECISION is the DOCX writer's _target_carries_pii, imported rather than rewritten: a
    second predicate would drift, and the round-4 measurement behind that one (30 real Slovak
    legal links, three of which a blanket rule destroyed) is not worth re-earning.

    The ACTION differs from the DOCX spelling on purpose. A Word hyperlink's display text is
    document content whose relationship must keep resolving, so there the target is REPLACED by
    a placeholder. A PDF link annotation is invisible geometry laid over text that is already
    on the page: deleting it removes the action and changes nothing a reader sees, while a
    placeholder URL would leave a live link to a dead host. It also covers the kinds for which
    no placeholder is even well-formed (/Launch and /GoToR carry a FILE, not a URL).

    Runs after the redaction loop, on the baked document, so it sees every link that will
    actually be saved."""
    for page in doc:
        for link in page.get_links():
            targets = [str(link[k]) for k in _LINK_TEXT_KEYS if link.get(k)]
            if any(_target_carries_pii(t, list(known_entities or []), config) for t in targets):
                page.delete_link(link)


def _open_pdf(in_path: str) -> "fitz.Document":
    """Open a PDF, converting anything PyMuPDF can raise into a named refusal.

    Measured (red-team round 4, R4-X3): a truncated file raised FileDataError, and a
    password-protected one raised "ValueError: document closed or encrypted" from the first
    method call rather than from the open. The Slovak land registry issues password-protected
    PDFs, so that one is ordinary -- and its remedy is entirely within the lawyer's reach
    (open it, enter the password, save an unprotected copy), which is why it gets its own type
    and its own sentence rather than being folded into "damaged".
    """
    try:
        doc = fitz.open(in_path)
    except Exception as exc:  # noqa: BLE001
        raise UnreadableDocumentError(in_path, f"{type(exc).__name__}: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise PasswordProtectedError(in_path)
    return doc


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

    doc = _open_pdf(in_path)
    # R6-05 / R6-06: READ THE SAME DOCUMENT THE GATE GRADES. Everything below -- the refusal
    # checks, detect(), search_for -- goes through page.get_text(), and MuPDF's text device
    # clips to the CropBox and honours optional-content visibility. So text on an OFF layer
    # (an attorney's "Poznamky" layer) and text cropped away by Acrobat's Crop Pages tool
    # ("crop out the letterhead before you send it" is an ordinary paralegal action) were
    # returned by NOTHING here, while eval/extract.py -- which has widened the box and dropped
    # /OCProperties since v1.1 -- read them on ``text_layer`` and would have failed the gate
    # with no discount. One helper, called from both, is the only arrangement in which the
    # writer cannot drift from the grader again.
    #
    # rehide() puts the boxes and the layer configuration back immediately before the save, so
    # the output is the lawyer's document with the PII destroyed -- not an un-cropped one with
    # the firm's internal layers switched on.
    view = unhide(doc)
    # R3-C4: a page whose text we cannot decode is MORE dangerous than a page with none. The
    # glyphs are drawn and a human reads them; detect() sees control characters and removes
    # nothing; and eval/extract.py reads the same control characters, so the leak gate agrees
    # the output is clean. Refuse instead.
    # R3-C1: a shredded text layer is the same danger as an undecodable one, arriving by a
    # different route -- detect() reads "P re d a v a ju ci" and finds nothing, and so does
    # eval/extract.py, so the leak gate calls the unredacted result clean.
    shredded = shredded_pages(doc)
    if shredded:
        doc.close()
        raise ShreddedTextLayerError(in_path, shredded)

    bad_pages = unreadable_pages(doc)
    if bad_pages:
        doc.close()
        raise UnreadableTextLayerError(in_path, bad_pages)

    # R4-I3: a cp1250 text layer drawn as WinAnsi passes both checks above -- every character
    # it produces is a letter or a punctuation sign, and the tokens are intact. Most of it is
    # folded back by detect/normalize.py, offset-preservingly, so this refuses only the pages
    # where the fold cannot finish: the WinAnsi-undefined bytes collapse "Ť"/"ť"/"Ź" onto a
    # single U+FFFD, and "ť" inside a surname is then unreadable to us and to the reviewer
    # alike. Half-redacting such a page is exactly the silent failure this project refuses.
    mangled = mojibake_pages(doc)
    if mangled:
        doc.close()
        raise MojibakeTextLayerError(in_path, mangled)

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

    _scrub_link_targets(doc, known_entities, config)
    # rehide BEFORE the doc-level scrub, not after (R6-03). unhide() sets /OCProperties to
    # null so MuPDF's text device emits an OFF layer's text; the catalogue scrub has to walk
    # the /OCProperties that will actually be SAVED, or the optional-content group whose name
    # is "Vrstva klienta Peter Horvath" is unreachable at exactly the moment we go looking for
    # it -- and rehide would then put it back, unscrubbed, after the scrub had finished.
    rehide(doc, view)
    _scrub_document_surfaces(doc)

    doc.save(out_path, garbage=4, deflate=True)
    doc.close()

    # P4: the report is written BEFORE the incomplete-redaction raise, deliberately. A partial
    # output is precisely the file whose record a reviewer needs; writing the report after the
    # raise would leave the worst case as the one case with no record at all.
    write_report(out_path, labelmap.occurrences, labelmap.low_confidence,
                 labelmap.checksums, labelmap.lc_checksums,
                 labelmap.detector_failures, labelmap.unlocated)

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
