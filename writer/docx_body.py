"""W1 (context.md §10): redact auto-detected PII in a DOCX's top-level body paragraphs.

The hard part is not *finding* PII — detect() does that on reconstructed paragraph text —
it is putting the redaction back onto the <w:r> run sequence. Word splits a single logical
surface across arbitrary runs, sometimes MID-TOKEN ('Luc'|'ie Molnáro'|'vej') and sometimes
MID-RUN on both ends ('Zmluva medzi Ján'|'om Novákom dnes'), and each run may carry its own
<w:rPr> formatting. So a detect() span [start,end) over the reconstructed text has to be
mapped back to exact character offsets inside runs, the covered characters removed, a single
type label inserted at the span start, and any boundary run split into fragments that each
keep a clone of the original run's <w:rPr>.

W2 (context.md §10) extends coverage past doc.paragraphs to every OTHER place Word hides a
<w:p>: table cells, header/footer paragraphs, header/footer tables, and VML textboxes (in
the body and in header/footer parts). All of them are ordinary <w:p> once located, so the
SAME run-remap core (_redact_paragraph) is reused verbatim — nothing about the run-splitting
is re-implemented.

W3 (context.md §10) closes the last <w:p> locations, the three note parts Word keeps OUTSIDE
document.xml as separate OPC parts: footnotes.xml, endnotes.xml and comments.xml. They carry a
part-type asymmetry (see _open_tree) but every note is an ordinary <w:p> once located,
so the SAME core is reused again. W3 does NOT scrub the comment w:author attribute — that is
W4 metadata scope. Labels are type-only ("[MENO]"); per-entity numbering ("[MENO_1]") is W5.
The input file is never modified — output is a new file.

W4b (context.md §10) scrubs document METADATA that carries PII: docProps/core.xml properties
(dc:creator, cp:lastModifiedBy, ...), every free-text value in docProps/app.xml, and
the comment w:author/w:initials attributes deferred from W3 (see _scrub_metadata). These are
BLANKED UNCONDITIONALLY BY POSITION — detect() never runs over metadata, since an author or
manager name is PII regardless of whether it matches a detector pattern, and the original value
is never preserved (see _scrub_metadata).
"""
from __future__ import annotations

import os
import posixpath
import re
import unicodedata
import urllib.parse
import zipfile
from copy import deepcopy
from functools import lru_cache
from typing import NamedTuple

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from detect.config import DetectConfig
from detect.core import detect_with_failures
from writer.decisions import RedactionDecisions
from writer.errors import EmbeddedSubDocumentError, UnreadableDocumentError
from writer.labelmap import LabelMap, make_snippet
from writer.report import write_report

# xml:space lives in the reserved XML namespace, which is not in python-docx's nsmap, so it
# cannot go through qn(); set it by its literal Clark-notation name.
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _strip_tracked_changes(root) -> None:
    """W4a (context.md §10): accept ALL Word tracked revisions inside ``root`` (a w:document /
    header / footer / notes tree) BEFORE any redaction runs. The structure is ASYMMETRIC
    (verified against corpus bytes, kupna_zmluva_000.docx):

    * <w:ins ...><w:r><w:t>TEXT</w:t></w:r></w:ins> — accepted INSERTED content: promote the
      ins's children into its parent at the ins's position, then drop the now-empty ins. The
      runs SURVIVE as ordinary body runs and remain subject to the normal redaction passes.
    * <w:del ...><w:r><w:delText>TEXT</w:delText></w:r></w:del> — DELETED content that is still
      PHYSICALLY in the file: remove the whole subtree. Getting these backwards either drops
      accepted text or leaks deleted PII. w:delText only ever lives inside w:del, so once every
      w:del is gone no w:delText remains.

    Every w:del is stripped first (removing its whole subtree), then w:ins is re-found on the
    mutated tree — so content that was inserted-then-deleted (a w:del nested in a w:ins, or an
    ins nested in a del) resolves correctly with no dangling detached-parent inserts. Both lists
    are materialised (findall + list) so the tree is never mutated under a live iterator."""
    # <w:moveFrom> FIRST, and it is a third revision pair the original implementation did not
    # know about (red-team round 4, R4-M4a). Word records a MOVED clause as <w:moveFrom> at the
    # old position -- holding the text in <w:delText>, exactly like a deletion -- and
    # <w:moveTo> at the new one. A clause dragged from one article to another therefore kept
    # its original text verbatim in document.xml: "Kupujúci: Mária Kováčová, rodné číslo
    # 855612/7788", sitting in the file after being "moved away". Same failure the w:del branch
    # exists to prevent, through a door nobody had opened.
    for moved in list(root.findall(".//" + qn("w:moveFrom"))):
        parent = moved.getparent()
        if parent is not None:
            parent.remove(moved)

    for dele in list(root.findall(".//" + qn("w:del"))):
        parent = dele.getparent()
        if parent is not None:
            parent.remove(dele)

    # <w:moveTo> is the accepted half of a move -- its runs SURVIVE, like <w:ins> -- so it is
    # promoted the same way and stays subject to the normal redaction passes.
    for moved in list(root.findall(".//" + qn("w:moveTo"))):
        parent = moved.getparent()
        if parent is None:
            continue
        idx = parent.index(moved)
        for offset, child in enumerate(list(moved)):
            parent.insert(idx + offset, child)
        parent.remove(moved)

    for ins in list(root.findall(".//" + qn("w:ins"))):
        parent = ins.getparent()
        if parent is None:
            continue
        idx = parent.index(ins)
        # Materialise the children: each insert MOVES the child out of ins into parent, so the
        # live child list shrinks as we go; enumerate over the snapshot keeps order + offsets.
        for offset, child in enumerate(list(ins)):
            parent.insert(idx + offset, child)
        parent.remove(ins)

    # The w:author / w:initials that whatever revision bookkeeping the strips above left behind
    # still carries (red-team round 4, R4-M4b) are blanked by _scrub_attributes, which runs
    # straight after this pass over the same trees. It is the same blanket sweep this function
    # used to end with, grown to the rest of the attribute plane (R5-07) -- one sweep rather
    # than two, so the next attribute nobody thought of has one place to be added.


# ------------------------------------------------------------------- THE ATTRIBUTE PLANE
# Word keeps a great deal of free text in ATTRIBUTES, and the only attribute sweep this writer
# had was the two names added for R4-M4b. Measured in ONE document (red-team round 5, R5-07): a
# scanned signature's alt text, a legacy VML stamp's alt text, a bookmark named after the party,
# a content control's alias and tag, a dropdown's selected value AND ITS WHOLE LIST, and a
# legacy w:ffData status text and default value all survived a redaction.
#
# The sharpest shape is a control carrying <w:showingPlcHdr/>: the page displays "Kliknite sem a
# zadajte meno." -- a clean page, and the contrast control confirms the visible plane IS redacted
# -- while the selected client and THE OFFICE'S ENTIRE CLIENT LIST sit in the w:sdtPr attributes
# underneath. All of it lands on ``xml_attributes``, an OPAQUE surface, so the leak gate only
# counts a needle of 7 characters or more: a first name, a four-digit bank code or a five-digit
# PSČ in an alt text is a leak scored CLEAN.
#
# Blanked BY POSITION as a BLANKET SWEEP OVER ATTRIBUTE NAMES rather than an element whitelist.
# That is the R4-M4b argument verbatim and it applies here for the same reason: the whitelist is
# what failed, because it can only ever know the elements somebody has already thought of.
_BLANKET_ATTRS = (
    # Object names and alt text. wp:docPr / pic:cNvPr / a:cNvPr carry @name @descr @title and
    # the legacy VML v:shape / v:image / v:rect carry @alt @title -- all UNPREFIXED, so one
    # attribute name covers every element that has ever carried them.
    "alt", "descr", "title", "name",
    qn("w:lastValue"),                     # w:dropDownList / w:comboBox: the SELECTED entry
    qn("w:displayText"), qn("w:value"),    # w:listItem: the list itself
    qn("w:author"), qn("w:initials"),      # every revision element (R4-M4b)
)

# w:val CANNOT be swept by name: it is WordprocessingML's universal value attribute and carries
# font sizes, style ids and numbering levels, none of which survive being emptied. These are the
# elements whose w:val is free text A PERSON TYPED -- a content control's alias and tag, a legacy
# Developer-tab form field's status bar, help text, default value and list entries, and a smart
# tag's attribute value.
_VAL_TEXT_ELEMENTS = frozenset({
    qn("w:alias"), qn("w:tag"), qn("w:statusText"), qn("w:helpText"),
    qn("w:default"), qn("w:listEntry"), qn("w:attr"),
})


def _scrub_attributes(root) -> None:
    """Blank every attribute under ``root`` that can carry free text, by position."""
    for elem in root.iter():
        for attr in _BLANKET_ATTRS:
            if elem.get(attr) is not None:
                elem.set(attr, "")
        if elem.tag in _VAL_TEXT_ELEMENTS and elem.get(qn("w:val")) is not None:
            elem.set(qn("w:val"), "")
        # <w:ffData><w:name w:val="Klient"/> -- the legacy form field's own name. Scoped to that
        # parent because w:name/@w:val is ALSO a style's display name and a building block's
        # gallery name, and blanking either of those is document damage, not redaction.
        if elem.tag == qn("w:name") and elem.get(qn("w:val")) is not None:
            parent = elem.getparent()
            if parent is not None and parent.tag == qn("w:ffData"):
                elem.set(qn("w:val"), "")
        # A bookmark name is free text the author typed -- "Adresa_Maria_Kovacova" -- EXCEPT in
        # Word's own namespace (_Toc, _Ref, _GoBack, _Hlk), which is what every table-of-contents
        # entry and cross-reference points AT. Renaming one of those breaks the navigation
        # instead of redacting anything: R5-08 is exactly what that costs, it has bitten this
        # project twice, and tests/test_docx_field_codes.py pins the survival list.
        if elem.tag == qn("w:bookmarkStart"):
            value = elem.get(qn("w:name"))
            if value is not None and not value.startswith("_"):
                elem.set(qn("w:name"), "")


# Which <w:r> children CONTRIBUTE CHARACTERS to run.text -- and therefore to the offsets
# detect() is given -- ASKED OF python-docx ITSELF rather than hand-maintained.
#
# The hand-written set disagreed with CT_R.text in BOTH directions at once (red-team round 5,
# R5-09), because it was written from the docstring's DESCRIPTION of run.text and never checked
# against the library:
#
#   * w:ptab -- Word's Alignment Tab, what puts the page number at the right margin of a header
#     and the leader dots in a TOC line -- renders as "\t" and was NOT in the set, so it was
#     cloned into EVERY fragment and its tab was separately re-emitted as a plain <w:tab/>;
#   * w:softHyphen renders as "" and WAS in the set, so it was stripped from every clone and
#     never re-emitted: silently deleted;
#   * w:noBreakHyphen renders as "-" and came back as a literal hyphen-minus inside a <w:t>,
#     i.e. a non-breaking hyphen downgraded to a breaking one.
#
# The probe asks the question the library answers: a <w:r> holding exactly one child of this tag
# either renders characters through CT_R.text or it does not. That is CT_R.text's own xpath,
# evaluated by CT_R.text, so a python-docx upgrade that adds an inner-content element is picked
# up instead of silently corrupting documents (tests/test_redteam_round5.py pins the derived
# answer against the xpath in the installed library's source).
#
# The child is given text, so a w:t is judged by what it renders and not by happening to be
# empty. w:delText -- which the old hand-written set carried -- is NOT selected by CT_R.text and
# so is not text-bearing; it can only live inside a w:del, and _strip_tracked_changes removes
# every w:del subtree before any of this runs.
_PROBE_RUN = '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'


@lru_cache(maxsize=None)
def _is_text_bearing(tag: str) -> bool:
    run = parse_xml(_PROBE_RUN)
    child = run.makeelement(tag, {})
    child.text = "X"
    run.append(child)
    return run.text != ""


def _run_spans(r_elem, start: int) -> list[tuple[object, int, str]]:
    """Every child of ``r_elem`` as (child, first character offset, what it renders).

    A child that contributes NO characters -- w:rPr, w:softHyphen, w:drawing, w:fldChar,
    w:instrText -- gets an empty rendering at the position it sits in. That is what lets
    _rebuild_run put it back exactly ONCE, where it was, instead of copying it into every
    fragment (which is what duplicated w:ptab) or dropping it (which is what deleted
    w:softHyphen)."""
    spans = []
    pos = start
    for child in r_elem:
        rendered = str(child) if _is_text_bearing(child.tag) else ""
        spans.append((child, pos, rendered))
        pos += len(rendered)
    return spans


def _emit_chars(src, text: str) -> list:
    """Re-emit surviving characters AS THE ELEMENT THEY CAME FROM.

    A child that renders its own text (a w:t) is cloned with the surviving text substituted, so
    its attributes survive. A child that renders a FIXED string (w:tab, w:br, w:cr, w:ptab,
    w:noBreakHyphen) is cloned as itself, with its own attributes -- a w:ptab keeps its
    alignment and leader, and a non-breaking hyphen comes back non-breaking."""
    if str(src) == (src.text or ""):
        clone = deepcopy(src)
        clone.text = text
        # Preserve leading/trailing whitespace in the fragment (labels have none, but a
        # surviving boundary fragment like ' súhlasí' does).
        clone.set(_XML_SPACE, "preserve")
        return [clone]
    return [deepcopy(src) for _ in range(len(text) // len(str(src)))]


def _rebuild_run(r_elem, items: list[tuple]) -> None:
    """Replace a single <w:r> with one new <w:r> per fragment, cloning the original run's
    formatting onto each. ``items`` is the ordered emission stream _redact_paragraph built:

        ('c', char, source child)  a surviving character, and which child rendered it
        ('l', label)               a replacement label, which starts a new fragment
        ('e', child)               a child that renders no characters, put back exactly once

    A fragment with nothing in it is not emitted, so a wholly covered run disappears."""
    parent = r_elem.getparent()
    idx = parent.index(r_elem)

    fragments: list[list[tuple]] = [[]]
    for item in items:
        if item[0] == "l":
            fragments.append([item])
            fragments.append([])
        else:
            fragments[-1].append(item)

    offset = 0
    for frag in fragments:
        if not frag:
            continue
        clone = deepcopy(r_elem)  # carries a copy of <w:rPr> so formatting is preserved
        for child in list(clone):
            if child.tag != qn("w:rPr"):
                clone.remove(child)
        src, buf = None, ""
        for item in frag:
            if item[0] == "c" and item[2] is src:
                buf += item[1]
                continue
            if src is not None:
                clone.extend(_emit_chars(src, buf))
            src, buf = (item[2], item[1]) if item[0] == "c" else (None, "")
            if item[0] == "e":
                clone.append(deepcopy(item[1]))
            elif item[0] == "l":
                label = clone.makeelement(qn("w:t"), {})
                label.text = item[1]
                label.set(_XML_SPACE, "preserve")
                clone.append(label)
        if src is not None:
            clone.extend(_emit_chars(src, buf))
        parent.insert(idx + offset, clone)
        offset += 1

    parent.remove(r_elem)


# ------------------------------------------------------------------ WHOLE-TREE TRAVERSAL
# Every <w:p> under a root, in document order, INCLUDING the ones python-docx's direct-child
# views cannot reach: inside a nested table, inside a content control (<w:sdt>), inside a
# textbox, inside a table inside a textbox.
#
# A <w:p> cannot contain another <w:p> in WordprocessingML (a table is a SIBLING of the
# paragraphs around it, never a child of one), so a descendant walk visits each exactly once
# and no paragraph is processed twice. Merged table cells share ONE <w:tc> in the XML, so they
# also arrive exactly once -- the identity de-duplication the old per-cell walk needed is not
# needed here, because the duplication it guarded against was an artefact of row.cells minting
# a proxy per grid position.
def _all_paragraph_elements(root):
    return root.findall(".//" + qn("w:p"))


# Where a paragraph actually sits, for the report's location tag. Checked innermost-first: a
# table inside a textbox is a TEXTBOX, because that is the thing a reviewer needs to go and
# look at.
_LOCATION_ANCESTORS = ((qn("w:txbxContent"), "textbox"), (qn("w:tbl"), "table_cell"))


# <mc:AlternateContent> is how Word serialises EVERY textbox, shape and WordArt drawn since
# 2007: the modern DrawingML rendering in <mc:Choice> and a legacy VML rendering of the SAME
# content in <mc:Fallback>. Both copies carry their own <w:txbxContent><w:p>, so the same
# sentence is in the file twice and both copies MUST be redacted -- scrubbing one branch ships
# a document that reads clean in whichever Word branch you happen to open it in and leaks in
# the other. The paragraph walk reaches both, which is what makes that safe.
#
# Exactly one of the two is ever DISPLAYED, though, so recording both would tell the reviewer
# a name appears twice on a page where it appears once (red-team round 4, R4-T1). The Fallback
# copy is therefore still redacted and simply not reported; document order puts Choice first,
# so the occurrence that IS recorded is the one the reader sees.
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _is_alternate_fallback(p_elem) -> bool:
    node = p_elem.getparent()
    while node is not None:
        if node.tag == _MC_FALLBACK:
            return True
        node = node.getparent()
    return False


def _paragraph_location(p_elem, default: str) -> str:
    node = p_elem.getparent()
    while node is not None:
        for tag, location in _LOCATION_ANCESTORS:
            if node.tag == tag:
                return location
        node = node.getparent()
    return default


def _paragraph_runs(p_elem):
    """Every <w:r> inside this paragraph, in document order, including runs nested inside
    <w:hyperlink>, <w:sdt>, <w:smartTag> and <w:fldSimple>.

    Paragraph.runs returns only DIRECT children, so a hyperlinked e-mail address was not even
    part of the text detect() was given -- it could not be found, let alone removed. Word
    auto-hyperlinks every address and URL as you type.
    """
    own = []
    for r in p_elem.findall(".//" + qn("w:r")):
        # Keep only runs whose nearest ancestor <w:p> is THIS paragraph. A descendant search
        # also reaches runs inside a NESTED <w:p> -- a textbox anchored in this paragraph --
        # and welding that text onto this paragraph's is document corruption, not extra
        # coverage: measured, "Predávajúci: Ján Novák" plus an anchored textbox reading
        # "Kupujúci: Mária Kováčová" produced MENO('Ján NovákKupujúci') and deleted the other
        # party's role label out of the textbox (red-team round 4, R4-T9).
        #
        # Nothing is lost by skipping them. The nested <w:p> is itself visited by the
        # paragraph walk in _redact_docx, where its runs are redacted in their own context and
        # tagged with their own location.
        node = r.getparent()
        while node is not None and node.tag != qn("w:p"):
            node = node.getparent()
        if node is p_elem:
            own.append(r)
    return own


def _redact_paragraph(
    paragraph, known_entities, labelmap, location: str = "body",
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
    record: bool = True,
) -> None:
    """Redact auto PII in one paragraph and record report-capture side-effects tagged with
    ``location`` (one of the fixed vocabulary strings, matching GT surface_part). The default is
    ``"body"``, the safe fallback for an un-tagged call — every real caller now passes
    ``location`` explicitly, including ``_redact_cells`` for body table cells.

    ``record=False`` redacts exactly as usual but files nothing in the report: it is for a
    paragraph that is a SECOND COPY of content the document displays once (see
    _is_alternate_fallback). It never affects what is removed — only what is counted."""
    # Every run in the paragraph, nested ones included -- NOT paragraph.runs, which is a
    # direct-child view and silently omits anything inside a <w:hyperlink> or a <w:sdt>.
    run_elems = _paragraph_runs(paragraph._p)
    if not run_elems:
        return

    # Reconstruct paragraph text, remembering for every character WHICH CHILD OF WHICH RUN
    # rendered it. That mapping is what lets the rebuild put a w:ptab / w:br / w:noBreakHyphen
    # back as the element it was rather than as a character in a <w:t> (R5-09). The joined
    # renderings are CT_R.text by construction: _run_spans renders exactly the children
    # CT_R.text selects, in document order.
    spans_by_run = []
    pieces: list[str] = []
    pos = 0
    for r_elem in run_elems:
        spans = _run_spans(r_elem, pos)
        spans_by_run.append(spans)
        text = "".join(rendered for _child, _a, rendered in spans)
        pieces.append(text)
        pos += len(text)
    recon = "".join(pieces)

    # ONE detect() over the post-strip reconstructed text; both captures below read this same
    # result the redaction path uses — never a second detect() over a different tree state.
    detected, failures = detect_with_failures(recon, known_entities, config)
    for f in failures if record else ():
        # A detector that raised produced NO candidates for THIS paragraph, so whatever it
        # would have found is still in the document. Nothing else in the report shows that:
        # the missing rows look exactly like 'there was nothing here'.
        labelmap.record_detector_failure(f.detector, location, f.error)

    # Decision-aware keep/skip: default (decisions None) is exactly the old auto/non-auto
    # split. A suppressed auto group is left intact and recorded to the report's
    # NOT-REDACTED section — the human decision leaves an honest trace. A forced
    # low-confidence group flows through the normal label/redact path.
    keep = []
    for c in detected:
        redact = c.auto
        if decisions is not None:
            key = (c.type, labelmap.group_key(c))
            if c.auto and key in decisions.suppress_groups:
                redact = False
            elif not c.auto and key in decisions.force_groups:
                redact = True
        if redact:
            keep.append(c)
        elif record:
            labelmap.record_low_confidence(
                location, c.type, c.surface,
                snippet=make_snippet(recon, c.start, c.end),
                checksum=c.checksum,
            )
    cands = keep
    if not cands:
        return

    covered = [False] * len(recon)
    label_at: dict[int, str] = {}
    for c in cands:
        for i in range(c.start, c.end):
            covered[i] = True
        # detect() guarantees non-overlapping spans, so one label per start is unambiguous.
        # The explicit "not in" guard (NOT setdefault) is load-bearing: setdefault would
        # eagerly evaluate labelmap.label_for(c) even when c.start is already present, and
        # label_for mints/caches a number on first sighting — so an already-present start
        # would spuriously bump the per-type counter. Guarding keeps numbering exact.
        if c.start not in label_at:
            label_at[c.start] = labelmap.label_for(c)
        # Redaction capture: record EVERY kept occurrence (all spans, incl. repeats of an
        # already-numbered label). Non-overlapping distinct starts mean label_at[c.start] is
        # this candidate's own label; recording here does not touch counters or the cache.
        if record:
            labelmap.record_occurrence(
                label_at[c.start], location, c.surface,
                snippet=make_snippet(recon, c.start, c.end),
                checksum=c.checksum,
            )

    # Build, per touched run, the ordered emission stream, then rewrite it.
    for r_elem, spans in zip(run_elems, spans_by_run):
        items: list[tuple] = []
        touched = False
        for child, a, rendered in spans:
            if not rendered:
                items.append(("e", child))
                continue
            for k, ch in enumerate(rendered):
                i = a + k
                if i in label_at:
                    items.append(("l", label_at[i]))
                    touched = True
                if covered[i]:
                    touched = True
                else:
                    items.append(("c", ch, child))
        if not touched:
            continue  # leave the run — and its exact XML — completely alone

        _rebuild_run(r_elem, items)


def _redact_cells(
    table, known_entities, labelmap, location: str = "table_cell",
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
) -> None:
    """Redact every cell paragraph in ``table``. A merged cell makes several (row, col)
    positions return the SAME <w:tc> element; dedup by tc identity so a shared paragraph is
    processed exactly once (reprocessing is otherwise wasted work and re-runs detect on
    already-labelled text).

    Key the set on the <w:tc> ELEMENT (``cell._tc``) itself, NOT ``id(cell._tc)``. row.cells
    mints a fresh _Cell proxy per row, and each row's proxies are GC'd before the next row's
    are allocated; CPython then reuses the freed address, so a later distinct cell's proxy can
    collide with an earlier cell's id() and be silently skipped (leaking its PII). The lxml
    element is stable for the table's lifetime and hashes/compares by identity, and a genuine
    horizontal span yields the SAME element object from every spanned cell access (python-docx
    _Row.cells builds one _Cell per <w:tc> and yields it grid_span times) — so merged cells
    still collapse to one, while distinct cells never alias. Holding the elements in the set
    also keeps them alive, so no address recycling can occur mid-table."""
    seen: set = set()
    for row in table.rows:
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.add(cell._tc)
            for paragraph in cell.paragraphs:
                _redact_paragraph(paragraph, known_entities, labelmap, location, decisions=decisions, config=config)


def _redact_textboxes(
    element, parent, known_entities, labelmap, location: str = "textbox",
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
) -> None:
    """Redact every <w:p> nested in any <w:txbxContent> under ``element`` (a document body
    or a header/footer part element). VML textboxes are unreachable through python-docx's
    paragraph APIs, so each inner <w:p> is wrapped as a Paragraph — whose .runs then expose
    the inner runs — and pushed through the same remap. ``parent`` is only a proxy handle;
    the remap operates on the run elements directly, so its exact value is not load-bearing."""
    for txbx in element.findall(".//" + qn("w:txbxContent")):
        for p_elem in txbx.findall(qn("w:p")):
            _redact_paragraph(Paragraph(p_elem, parent), known_entities, labelmap, location, decisions=decisions, config=config)


# ------------------------------------------------------------- THE TREES A DOCUMENT HAS
# ONE enumeration of the trees this document holds, iterated by EVERY pass. It replaces four
# separate enumerations -- _strip_tracked_changes's, the field-code loop's, the paragraph walk's
# ``roots``, and the note-part loop -- that each knew a DIFFERENT subset of the document. That
# divergence, not any one missing call, is what shipped the first-page header unredacted while
# the default header in the same file was clean (R5-01), left the note parts' field codes
# unscrubbed while the same field codes in the body were scrubbed (R5-04), and left
# word/glossary/document.xml touched by no pass at all (R5-03). A container added here once is
# now covered by every pass; there is no longer a place to add a fifth divergent loop.
class _Tree(NamedTuple):
    """One XML tree the passes run over.

    ``element``   root to walk: w:document, w:hdr/w:ftr, w:footnotes/w:endnotes/w:comments or
                  w:glossaryDocument.
    ``parent``    what ``Paragraph()`` is anchored to, so ``paragraph.part`` resolves.
    ``location``  default report location for the paragraphs in it.
    ``part``      blob-backed part to re-serialise into once the passes are done, or None for a
                  live tree that ``doc.save()`` already picks up (see ``_open_tree``).
    """
    element: object
    parent: object
    location: str
    part: object | None


def _open_tree(part, location: str) -> _Tree:
    """A note or glossary OPC part as a ``_Tree``, honouring the part-type asymmetry python-docx
    exposes on reopen (verified by probe):

    * comments.xml maps to a registered CommentsPart (an XmlPart): its ``.element`` is a live
      tree and its ``.blob`` RE-SERIALIZES from that tree, so a ``._blob`` reassignment would be
      silently discarded. The tree is mutated IN PLACE and doc.save() picks it up.
    * footnotes.xml, endnotes.xml and word/glossary/document.xml have no registered class and
      come back as generic blob-backed Parts with no ``.element``. Their bytes are parsed HERE,
      every pass mutates that one parsed tree, and ``_close_tree`` writes the result back to
      ``._blob`` (generic ``Part.blob`` returns ``_blob``, so doc.save() persists it).

    Branch on element-vs-blob, never on part name or note id -- and parse ONCE for all passes
    rather than once per pass, so two passes can never disagree about a part's bytes.
    """
    if getattr(part, "element", None) is not None:
        return _Tree(part.element, part, location, None)
    return _Tree(parse_xml(part._blob), part, location, part)


def _close_tree(tree: _Tree) -> None:
    """Serialise a blob-backed tree back into its part, mirroring python-docx's own part
    serialization (UTF-8, standalone declaration). A no-op for a live tree."""
    if tree.part is not None:
        tree.part._blob = etree.tostring(tree.element, encoding="UTF-8", standalone=True)


# python-docx's Section exposes SIX header/footer parts, not the two this used to visit. Word
# builds EVERY law-office letterhead out of the first-page pair (w:titlePg, "Different first
# page"), which is exactly where the firm name, IČO, fee-earner and client/matter line sit --
# and header2.xml / header3.xml / footer2.xml were the parts no pass ever opened (R5-01).
#
# The report location stays "header"/"footer": that is the physical OPC surface eval/extract.py
# grades and the GT ``surface_part`` vocabulary names, and WHICH page a header prints on is not
# a distinction a reviewer can act on differently.
_HDRFTR_PROPERTIES = (
    ("header", "header"), ("footer", "footer"),
    ("first_page_header", "header"), ("first_page_footer", "footer"),
    ("even_page_header", "header"), ("even_page_footer", "footer"),
)

# Relationship-type suffix -> report location, for the OPC parts that hold <w:p> outside
# document.xml. ``glossaryDocument`` is a Word TEMPLATE's building-block store: "save selection
# to the cover page gallery" on a real filing puts a real client in there permanently, and it
# then rides into every future document made from that template.
#
# "glossary" is a NEW location string, deliberately distinct from "body" -- a reviewer needs to
# know the hit is in the TEMPLATE, not on the page. Checked before adding it: nothing validates
# the writer's location strings against a vocabulary. They are free text through
# LabelMap.record_occurrence into the report's ``locations`` column. eval/extract.py's
# _GT_PART_TO_SURFACE and eval/cross_format_gate.py's DOCX_ONLY_PARTS are the two fixed
# vocabularies, and both are GROUND-TRUTH ``surface_part`` maps consulted only for corpus
# fixtures the generator builds -- neither is ever handed a writer location, and no corpus
# document has a glossary part.
_PART_LOCATIONS = (
    ("footnotes", "footnote"), ("endnotes", "endnote"), ("comments", "comment"),
    ("glossaryDocument", "glossary"),
)


def _document_trees(doc) -> list[_Tree]:
    """Every tree in ``doc``, in the fixed order the passes traverse it. That order IS the label
    numbering (LabelMap groups in first-seen order), so it is body, then each section's
    header/footer parts, then the note parts, then the glossary.

    DE-DUPLICATED BY PART IDENTITY, which enumerating more trees makes load-bearing. A header
    that ``is_linked_to_previous`` has no definition of its own: python-docx resolves it to an
    earlier section's part, so a three-section document sharing one letterhead would hand the
    same element to the passes three times and the report would say a name occurs three times on
    the one page it occurs on. Skipping linked header/footers also stops python-docx's
    ``_element`` accessor from MINTING an empty header part for a document that has none (its
    _get_or_add_definition ADDS a definition when there is no prior section to inherit from).
    """
    trees = [_Tree(doc.element, doc, "body", None)]
    seen = {id(doc.element)}

    for section in doc.sections:
        for prop, location in _HDRFTR_PROPERTIES:
            hdrftr = getattr(section, prop)
            if hdrftr.is_linked_to_previous:
                continue  # inherits an earlier section's part, which is visited on its own
            element = hdrftr._element
            if id(element) in seen:
                continue
            seen.add(id(element))
            # Header/footer parts are element-backed (HeaderPart/FooterPart are XmlParts), so
            # doc.save() re-serialises them from the live tree -- no write-back needed.
            trees.append(_Tree(element, hdrftr, location, None))

    for rel in doc.part.rels.values():
        location = next((loc for suffix, loc in _PART_LOCATIONS
                         if rel.reltype.endswith(suffix)), None)
        if location is None or id(rel.target_part) in seen:
            continue
        seen.add(id(rel.target_part))
        trees.append(_open_tree(rel.target_part, location))

    return trees


# ---------------------------------------------------------------- w:altChunk (R5-02)
# An altChunk is a placeholder for a whole EXTERNAL DOCUMENT stored as its own package part,
# which Word splices onto the page on open. Nothing in this writer can read it: the paragraph
# walk looks for w:p and an altChunk contains none, only a relationship id. See
# writer/errors.py::EmbeddedSubDocumentError for why the answer is a refusal rather than a
# best-effort redaction or a silent deletion of the part.
_ALT_CHUNK = qn("w:altChunk")
_AFCHUNK_RELTYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk"
)


def _alt_chunk_parts(path: str, trees: list[_Tree]) -> list[str]:
    """Every embedded sub-document in this package, named by part, in package order.

    Both planes are checked, because either one alone misses a real case:

    * the PACKAGE plane -- every ``.rels`` part in the zip, for a relationship of type
      ``aFChunk``. This is what actually carries the bytes, and it finds a chunk referenced
      from a header, the glossary or a part this writer does not enumerate, plus an orphan
      chunk part left behind by an editor (still text shipping in the output);
    * the DOCUMENT plane -- a ``w:altChunk`` element in any tree, which catches one whose
      relationship is missing or malformed. There is no content to redact in that case, but
      the document is still one this writer provably cannot process.
    """
    parts: list[str] = []
    with zipfile.ZipFile(path) as zin:
        for name in zin.namelist():
            if not name.endswith(".rels"):
                continue
            base = posixpath.dirname(posixpath.dirname(name))
            try:
                rels_root = etree.fromstring(zin.read(name))
            except etree.XMLSyntaxError as exc:
                # A .rels python-docx never had to follow (an orphan) can still be malformed,
                # and skipping it would mean not knowing whether it names an altChunk. R4-X3's
                # contract is that such a file is refused BY NAME, not raised as an lxml message.
                raise UnreadableDocumentError(path, f"{name}: {exc}") from exc
            for el in rels_root:
                if el.get("Type") != _AFCHUNK_RELTYPE:
                    continue
                target = el.get("Target", "")
                parts.append(
                    target.lstrip("/") if target.startswith("/")
                    else posixpath.normpath(posixpath.join(base, target))
                )
    if not parts and any(t.element.find(f".//{_ALT_CHUNK}") is not None for t in trees):
        parts.append("<w:altChunk with no resolvable relationship>")
    return parts


# ------------------------------------------------------------ docProps/app.xml (R5-05/06/10)
# The extended-properties part (ECMA-376 Part 1 §15.2.12.1). Its scrub used to be a two-item tag
# list -- ("Company", "Manager") -- applied as a REGEX over the raw bytes, and that was wrong
# three ways at once (red-team round 5):
#
#   R5-05  Word populates <TitlesOfParts> with THE TEXT OF EVERY HEADING IN THE DOCUMENT -- that
#          is how the properties pane and Explorer's preview show an outline -- so a contract
#          whose Article I reads "Kúpna zmluva – Mária Kováčová" shipped that string in its
#          metadata. <HyperlinkBase> is the office's own share path, which on a Windows domain
#          carries an account name. Neither is Company or Manager, and app_xml is a NAMED,
#          non-opaque surface: the leak gate counts every one of them with no discount.
#   R5-06  <ep:Company> and <Company> are the SAME ELEMENT in XML and different strings to a
#          regex. This was the only scrub in the writer that parsed XML with a regular
#          expression; every other branch uses Clark names and is prefix-safe.
#   R5-10  ``.decode("utf-8")`` with no guard turned a windows-1250 app.xml -- valid XML, simply
#          not UTF-8, which is what an RTF->DOCX converter or a legacy Central-European court
#          system emits -- into a raw UnicodeDecodeError where context.md §3 promises a named
#          refusal. Parsing the BYTES honours the declaration's encoding, so the part is now
#          read correctly and redacted. Deliberately NOT papered over with
#          ``decode("utf-8", "replace")``: that would silently mojibake the part and write the
#          result back, which is round 4's cp1250 finding in reverse.
#
# So: parse with lxml, match on EXPANDED names, and blank every free-text value BY POSITION --
# the same choice _scrub_extra_parts makes for customXml, for the same reason. This is an
# application's private bookkeeping part that no reviewer reads, so blanking a value that was
# not PII costs nothing at all, while enumerating the tags that might be PII is precisely the
# enumeration that just failed.
#
# CHECKED BEFORE BLANKING BY POSITION -- nothing downstream reads a VALUE out of this part:
# eval/extract.py takes it as one RAW TEXT HAYSTACK (S_APP = raw("docProps/app.xml"));
# eval/baselines.py only substitutes into it when building the greedy oracle's own inputs; and
# corpus/docx_builder.py writes <Company> into GENERATED SOURCES, never reads an output.
#
# WHAT IS KEPT is what Word VALIDATES rather than reads: the numeric and boolean bookkeeping.
# Blanking one of those leaves an empty string where the schema wants an xsd:int, which is a
# corrupt-file dialog rather than a redaction. The list is the round's, plus the other
# INTEGER-VALUED elements of the same schema (TotalTime and CharactersWithSpaces are in every
# app.xml Word writes; the presentation counters ride along for the same reason) -- an element
# whose schema type is an integer cannot carry a Slovak name, so keeping it costs no recall.
_EXTENDED_PROPS_NS = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
)
_VT_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
_APP_XML_KEEP = frozenset({
    "Pages", "Words", "Characters", "CharactersWithSpaces", "Lines", "Paragraphs", "TotalTime",
    "Slides", "Notes", "HiddenSlides", "MMClips", "DocSecurity", "ScaleCrop", "LinksUpToDate",
    "SharedDoc", "HyperlinksChanged", "AppVersion", "Application", "Template",
})
# The vt: variant types that hold a NUMBER, A BOOLEAN OR A TIMESTAMP rather than text. vt:lpstr,
# vt:lpwstr and vt:bstr are text and are blanked -- that is every heading in <TitlesOfParts>.
_APP_XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_VT_NON_TEXT = frozenset({
    "i1", "i2", "i4", "i8", "int", "ui1", "ui2", "ui4", "ui8", "uint",
    "r4", "r8", "decimal", "cy", "bool", "date", "filetime", "empty", "null", "clsid", "error",
})


def _scrub_app_xml(part) -> None:
    """Blank every free-text value in a docProps/app.xml part, by position."""
    root = etree.fromstring(part._blob)
    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue  # a comment or a processing instruction holds no property value
        name = etree.QName(elem).localname
        if elem.tag.startswith(_VT_NS):
            if name in _VT_NON_TEXT:
                continue
        elif name in _APP_XML_KEEP:
            continue
        # ``.strip()``: a whitespace-only text node is the file's own INDENTATION between
        # elements, not a value. Blanking it would reflow the part for nothing.
        if elem.text and elem.text.strip():
            elem.text = ""
    # The declaration is written out rather than left to lxml, which spells it with SINGLE
    # quotes. Word, python-docx and every other part of the package use the double-quoted form,
    # and tests/test_writer_docx_metadata.py pins these exact bytes -- a metadata scrub has no
    # business changing the shape of the XML declaration it re-serialises.
    part._blob = _APP_XML_DECLARATION + etree.tostring(root, encoding="UTF-8",
                                                       xml_declaration=False)


def _scrub_metadata(doc, path: str) -> None:
    """W4b (context.md §10): blank the three PII-bearing metadata locations, by position —
    never via detect(), never preserving the original value.

    * docProps/core.xml: exposed through python-docx's ``doc.core_properties`` (each is a
      settable str property backed by a ZeroOrOne element); the API write persists through
      doc.save(). created/modified/revision are dates/ints, not PII, and are left alone.
    * docProps/app.xml: python-docx has no API for this part — it comes back as a generic
      blob-backed Part, so its BYTES are parsed here and every free-text value is blanked by
      position (see _scrub_app_xml). A part that will not parse at all is refused BY NAME,
      like a malformed .rels part, rather than raised as a library message: this runs BEFORE
      doc.save(), so "nothing was written" is true by construction.
    * word/comments.xml <w:comment w:author=...>: deferred from W3's paragraph pass.
      Same element-vs-blob asymmetry applies — a CommentsPart's .blob RE-SERIALIZES from its
      live .element, so the attribute is mutated ON THE ELEMENT, never via a ._blob reassign
      (which would be silently discarded on save). w:id/w:date are not PII and are untouched.
    """
    cp = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "category", "comments"):
        setattr(cp, attr, "")

    for part in doc.part.package.iter_parts():
        if str(part.partname) != "/docProps/app.xml":
            continue
        try:
            _scrub_app_xml(part)
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise UnreadableDocumentError(path, f"docProps/app.xml: {exc}") from exc
        break

    for rel in doc.part.rels.values():
        if not rel.reltype.endswith("comments"):
            continue
        part = rel.target_part
        if not hasattr(part, "element") or part.element is None:
            continue
        for comment in part.element.findall(".//" + qn("w:comment")):
            if comment.get(qn("w:author")) is not None:
                comment.set(qn("w:author"), "")
            if comment.get(qn("w:initials")) is not None:
                comment.set(qn("w:initials"), "")


# Types whose shape alone is not evidence in a URL path -- a checksum has to agree. An
# eight-digit run is a date as often as it is an ICO, and a legal citation is full of them.
_TARGET_CHECKSUM_TYPES = frozenset({
    "RODNE_CISLO", "ICO", "DIC", "IC_DPH", "IBAN", "BANKOVY_UCET",
})


def _looks_like_a_date(surface: str) -> bool:
    """Is this digit run a plausible YYYYMMDD date rather than an identifier?

    Needed because a checksum is not the discriminator here: "20180101" -- the effective date
    in a slov-lex citation -- happens to be a checksum-VALID ICO, so requiring a valid checksum
    did not save the link. Legal citations are FULL of effective dates, and an eight-digit run
    in a legal URL path is a date more often than it is a company number.

    Deliberately narrow: exactly eight digits, a year in a range a legal citation uses, and a
    real month and day. A genuine ICO that happens to read as a date is possible and would be
    kept -- but it would have to be in a URL path, which is already the rarer case, and the
    display text and document body are redacted independently of this.
    """
    digits = surface.strip()
    if len(digits) != 8 or not digits.isdigit():
        return False
    year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    return 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31


def _fold_for_match(s: str) -> str:
    """Casefold and strip diacritics, for comparing a candidate against the lawyer's own list.

    A name in a URL path is written the way a filesystem tolerates -- "Jan-Novak" for
    "Ján Novák" -- so an exact comparison would miss precisely the targets this exists for.
    """
    decomposed = unicodedata.normalize("NFKD", s.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


# A hyperlink target is scrubbed when it CONTAINS personal data -- not merely because it is
# itself a URL.
#
# The distinction is load-bearing and the first version missed it. detect() classifies any
# http(s) address as type URL, and URL is an auto-redact type in this project, so "scrub the
# target if detect() finds anything" scrubbed EVERY hyperlink -- including
# https://www.slov-lex.sk/, the Slovak statute book. A tool that breaks every working link in
# a contract gets switched off, and the links it breaks are the ones the reviewer never sees,
# because the visible text is unchanged.
#
# A URL in BODY TEXT is different and is still redacted: the reviewer sees [URL_1] on the page
# and can untick it. A relationship target is invisible, so it gets the narrower rule.
_TARGET_IGNORED_TYPES = frozenset({"URL"})


# URL punctuation, turned into spaces so a name buried in a path becomes a name again.
#
# '.' is DELIBERATELY NOT in this class. Opening it up would dissolve every host name in the
# document ("www.slov-lex.sk" -> "www slov lex sk") and feed the bare-name heuristic exactly
# the input it is loosest on. The lowercase "jan.novak" this omission used to miss (red-team
# round 4, R4-R3) is caught by _account_name_in_a_filesystem_path below, which does not need
# the dot opened and cannot reach an http(s) link at all.
_TARGET_PUNCT_RE = re.compile(r"[/\\_+:?=&#]+")

# tel: is the one URI scheme whose ENTIRE value is, by definition (RFC 3966), a telephone
# number. So a tel: target needs no detector and no guess: if it has a number in it, it is a
# number belonging to whoever the link is for -- normally the client's mobile, pasted into a
# letterhead out of an e-mail signature. The phone detector wants the spaced Slovak spelling
# and did not recognise "tel:+421905123456" (R4-R4, an expectation the round stated as CLEAN
# in advance and then falsified).
_TEL_DIGITS_RE = re.compile(r"\d")

# A dotted DIRECTORY name on a filesystem path -- "jan.novak" in
# file:///C:/Users/jan.novak/... or \\fileserver\users\jan.novak\... -- is the standard
# Windows account spelling, and an account name identifies a person whatever the gazetteer
# thinks of it. detect() finds nothing in the lowercase form (measured: detect("jan novak")
# returns []), so no amount of punctuation-opening was ever going to catch R4-R3.
#
# Confined to file:// and UNC targets ON PURPOSE. Those point at the office's own file server;
# there is no statute book on a UNC share, so this evidence class cannot reach slov-lex,
# justice.gov.sk or any other public link -- which is the failure mode this scrub has now had
# twice. And a share path in a document leaving the office is a link that would not resolve
# for the recipient anyway, so the cost of being wrong is a dead link, not a broken one.
#
# The LAST segment is excluded because it is the file name, and "zmluva.docx" has the same
# shape as "jan.novak".
_ACCOUNT_SEGMENT_RE = re.compile(r"^[^\W\d_]{2,}\.[^\W\d_]{2,}$", re.UNICODE)


def _account_name_in_a_filesystem_path(target: str) -> bool:
    lowered = target.lower()
    if not (lowered.startswith("file:") or target.startswith("\\\\") or target.startswith("//")):
        return False
    segments = re.split(r"[/\\]+", target)
    return any(_ACCOUNT_SEGMENT_RE.match(seg) for seg in segments[:-1])


def _target_carries_pii(target: str, known_entities: list[str], config) -> bool:
    """Does this hyperlink destination contain personal data?

    TWO probes, because one cannot see both shapes:

      * the target AS IT IS -- this is what finds the address in "mailto:jan.novak@x.sk",
        where the e-mail is intact and detect() reads it directly;
      * the target with its PUNCTUATION OPENED UP -- because in
        "https://example.com/klienti/Jan-Novak/zmluva.pdf" the name is not visible to
        detect() at all: the whole string matches as one URL, and overlap resolution then
        suppresses the MENO inside it. Replacing the slashes and dashes with spaces both
        dissolves the URL match and turns "Jan-Novak" back into "Jan Novak".

    A candidate of ANY bucket counts, not only auto. Everywhere else in this tool a
    low-confidence hit goes to a human to decide -- but a relationship target is INVISIBLE on
    the page, so there is no moment at which a reviewer could catch it. The only two options
    are scrub it or ship it, and shipping it means a file that reads [MENO_1] while still
    naming the client in its own package.
    """
    # Percent-decoded FIRST, for both probes. Word stores what it encodes, so "Jan%20Novak"
    # has to read as "Jan Novak" or the scrub misses exactly the names it exists for.
    decoded = urllib.parse.unquote(target)

    # PROBE 0: the two shapes that carry personal data in their STRUCTURE rather than in
    # anything a detector can read off them -- a tel: URI and a Windows account name on a
    # filesystem path. Both are decided by the scheme, so neither can fire on an http(s) link.
    if decoded.lower().startswith("tel:") and _TEL_DIGITS_RE.search(decoded[4:]):
        return True
    if _account_name_in_a_filesystem_path(decoded):
        return True

    # PROBE 1: the target as it is. Almost no guessing here -- an address in a mailto: is an
    # address -- with one exception. A URL match covers only the SCHEME AND HOST, so a digit
    # run in the PATH is still visible to the identifier detectors, and an eight-digit date in
    # a legal citation (slov-lex .../2016/18/20180101) reads as a checksum-valid ICO. That one
    # is excluded here rather than in probe 2, because this is the probe it actually fires in.
    for c in detect_with_failures(decoded, known_entities, config)[0]:
        if c.type in _TARGET_IGNORED_TYPES:
            continue
        if c.type in _TARGET_CHECKSUM_TYPES and _looks_like_a_date(c.surface):
            continue
        return True

    # PROBE 2: the target with its punctuation opened up, which is the only way to see a name
    # buried in a path -- and ALSO the only place in this function that guesses, because a URL
    # path read as prose is a string of Slovak words. Measured over 30 real Slovak legal links
    # (red-team round 4, R4-R1), the unrestricted version destroyed three of them: an
    # eight-digit DATE in a slov-lex citation read as an ICO, "Sudy" in a justice.gov.sk path
    # read as a municipality, and "dane cla" on mfsr.sk read as a personal name.
    #
    # So this probe takes only evidence that cannot be produced by ordinary vocabulary:
    # an e-mail address, a CHECKSUM-VALID identifier, or a name the lawyer typed themself.
    # A gazetteer hit or a bare-name pair is exactly what a path full of Slovak words looks
    # like, and is not enough to destroy somebody's link to the statute book.
    opened = _TARGET_PUNCT_RE.sub(" ", decoded).replace("-", " ")
    known_folded = {_fold_for_match(k) for k in known_entities}
    for c in detect_with_failures(opened, known_entities, config)[0]:
        if c.type in _TARGET_IGNORED_TYPES:
            continue
        if c.type == "EMAIL":
            return True
        if (c.type in _TARGET_CHECKSUM_TYPES
                and c.checksum == "valid"
                and not _looks_like_a_date(c.surface)):
            return True
        if _fold_for_match(c.surface) in known_folded:
            return True
    return False


# A relationship target is EXTERNAL when Word stores it as a URL rather than a part name. Only
# those can carry PII -- an internal target is a path inside the package.
_EXTERNAL = "External"
_SCRUBBED_TARGET = "https://removed.invalid/"


def _scrub_rel_targets(path: str, known_entities: list[str], config) -> int:
    """Replace every external relationship target that contains detectable PII. Returns the
    number replaced.

    Run over the SAVED package, like _drop_thumbnail, because the targets live in .rels parts
    that the paragraph-level passes never touch.

    The whole target is replaced rather than edited. A URL is not prose: cutting the PII out of
    https://example.com/klient/Jan-Novak/zmluva leaves a path that still says which client it
    was, and a mailto: with the local part removed still names the domain. There is nothing in
    a hyperlink destination worth preserving once it is known to carry a party's identity, and
    the display text -- which is what the reader sees -- has already been redacted in place.
    """
    with zipfile.ZipFile(path) as zin:
        items = [(n, zin.read(n)) for n in zin.namelist()]

    replaced = 0
    rewritten = []
    for name, data in items:
        if name.endswith(".rels"):
            # Guarded, like eval/extract.py guards the same call and unlike this function used
            # to (red-team round 4, R4-X3). A .rels part that will not parse is refused BY
            # NAME rather than allowed to raise lxml's "Couldn't find end of Start Tag" out of
            # the writer: the lawyer's actual question is whether a half-redacted file is now
            # on disk, and a library message does not answer it. python-docx rejects most
            # malformed packages at open (_open_docx turns that into the same refusal), so
            # what reaches here is a .rels it copied through without parsing -- which is
            # exactly where something could hide, so it is refused rather than skipped.
            try:
                root = etree.fromstring(data)
            except etree.XMLSyntaxError as exc:
                raise UnreadableDocumentError(
                    path, f"unparseable relationship part {name}: {exc}") from exc
            changed = False
            for rel in root:
                if rel.get("TargetMode") != _EXTERNAL:
                    continue
                target = rel.get("Target") or ""
                if not target:
                    continue
                # unquote first: Word percent-encodes a target, and "Jan%20Novak" must be
                # detectable as "Jan Novak" or the scrub misses exactly the names it is for.
                probe = urllib.parse.unquote(target)
                if _target_carries_pii(probe, known_entities, config):
                    rel.set("Target", _SCRUBBED_TARGET)
                    changed = True
                    replaced += 1
            if changed:
                data = etree.tostring(root, encoding="UTF-8", standalone=True)
        rewritten.append((name, data))

    if replaced:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in rewritten:
                zout.writestr(name, data)
    return replaced


# ------------------------------------------------------------------- FIELD CODES (T4 / T5)
# Word has THREE spellings for a hyperlink and this project only knew one. <w:hyperlink r:id>
# puts the destination in a .rels part, which _scrub_rel_targets covers. The other two are
# FIELD CODES, and they carry the destination inside the field instruction:
#
#   <w:fldSimple w:instr=' HYPERLINK "mailto:jan.novak@advokat.sk" '>   (R4-T4)
#   <w:r><w:instrText> HYPERLINK "mailto:jan.novak@advokat.sk" </w:instrText></w:r>  (R4-T5)
#
# Neither goes through .rels, so _scrub_rel_targets never saw them; and w:instrText is not in
# text-bearing (see _is_text_bearing) and python-docx's Run.text does not render it, so
# detect() never saw it either.
# The page read "[MENO_1]" while document.xml -- a STRICT text surface -- still named the party
# and carried their address. RTF->DOCX conversion, Word 97-era documents and several DMS and
# court-portal exports write hyperlinks this way.
#
# The same code covers a MERGEFIELD or DOCVARIABLE instruction, because the rule is about the
# ARGUMENTS of a field rather than about HYPERLINK: an argument that carries personal data is
# replaced by the same marker a scrubbed relationship target gets.
_FIELD_ARG_RE = re.compile(r'"([^"]*)"|([^\s"]+)')

# WHICH fields are examined at all. A whitelist is normally the wrong instinct on this project
# -- recall over precision, and the M4b fix above deliberately replaced an element whitelist
# with a blanket sweep for exactly that reason. This is the exception, and the argument for it
# is specific rather than general.
#
# WHAT THE BLANKET VERSION DID. The first version of this function ran _target_carries_pii over
# every argument of every field. Measured on the ordinary fields a Slovak filing contains:
#
#   REF _Ref53871234 \h      ->  REF https://removed.invalid/ \h        cross-reference broken
#   PAGEREF _Toc12345678 \h  ->  PAGEREF https://removed.invalid/ \h    TOC entry broken
#   NOTEREF _Ref99887766 \h  ->  NOTEREF https://removed.invalid/ \h    footnote ref broken
#   REF _Ref123456789 \r \h  ->  unchanged
#
# A Word auto-bookmark is "_Ref"/"_Toc" plus EIGHT OR NINE digits. Eight digits is the ICO
# shape, and the v1.1 checksum policy auto-redacts a shape match whatever the checksum says --
# deliberately and correctly, because a mistyped ICO is still an ICO. So the blanket rule broke
# roughly every second cross-reference and every second table-of-contents entry in a real
# document, on a coin flip of the digit count.
#
# THE CATEGORY ERROR, which is the same one that destroyed the slov-lex links twice:
# _target_carries_pii is a predicate about a URI DESTINATION. A bookmark name is not a
# destination. Running a destination predicate over arguments that are not links is what makes
# "a link in a field and the identical link in .rels cannot get two different answers" -- true
# and good for HYPERLINK -- into document damage everywhere else.
#
# WHY THE RECALL COST IS ACCEPTABLE, stated explicitly because it is a real cost. A field
# instruction is reachable only as word/document.xml bytes, which the leak gate already grades
# as a STRICT surface; and the field's displayed RESULT is a separate run that detect() already
# reads on the page. So personal data in an argument of an unlisted field is still gated and
# still visible to a reviewer. The trade is therefore: a gated, visible miss in a field nobody
# has thought of, against CERTAIN damage to the cross-references and table of contents of an
# ordinary filing. The damage wins.
_FIELD_TYPES_WITH_PII_ARGS = frozenset({
    "HYPERLINK", "INCLUDETEXT", "INCLUDEPICTURE", "MERGEFIELD", "DOCPROPERTY", "DOCVARIABLE",
    "AUTHOR", "USERNAME", "USERADDRESS", "FILLIN", "ASK", "SUBJECT", "TITLE", "COMMENTS",
})


# Word's own bookmark namespace: _Toc… (table of contents), _Ref… (cross-reference),
# _GoBack (the resume-reading mark), _Hlk… (an autosave artefact). These are TARGETS INSIDE THE
# DOCUMENT, never destinations, and rewriting one breaks the navigation rather than redacting
# anything. Red-team round 5, R5-08.
_WORD_BOOKMARK_RE = re.compile(r"^_(?:Toc|Ref|GoBack|Hlk)\w*$")


def _scrub_field_instruction(instr: str, known_entities, config) -> str | None:
    """Return ``instr`` with every PII-bearing argument replaced, or None if nothing changed.

    The FIRST token is the field type; it decides whether the field is examined at all (see
    _FIELD_TYPES_WITH_PII_ARGS) and is never itself rewritten. Within a listed field, a token
    starting with a backslash is a formatting switch (``\\* MERGEFORMAT``) and a BARE token
    starting with an underscore is Word's internal bookmark namespace (``_Ref``/``_Toc``);
    neither is a destination, and rewriting either breaks the field rather than redacting it.
    Everything else is judged by the SAME _target_carries_pii used on a relationship target, so
    a link in a HYPERLINK field and the identical link in a .rels part cannot get two different
    answers."""
    first = _FIELD_ARG_RE.search(instr)
    if first is None:
        return None
    keyword = (first.group(1) if first.group(1) is not None else first.group(2)).upper()
    if keyword not in _FIELD_TYPES_WITH_PII_ARGS:
        return None

    state = {"keyword": False, "changed": False}

    def repl(m: re.Match) -> str:
        quoted, bare = m.group(1), m.group(2)
        value = quoted if quoted is not None else bare
        if not state["keyword"]:
            state["keyword"] = True
            return m.group(0)
        # THE TWO EXEMPTIONS ARE NOT SYMMETRIC, and getting that wrong has now cost a round
        # each way.
        #
        # A SWITCH is always written BARE (``\* MERGEFORMAT``). A quoted argument beginning
        # with a backslash is a UNC path -- ``INCLUDETEXT "\\\\fileserver\\users\\jan.novak\\..."``
        # -- which is exactly the kind of destination this function exists to examine. So the
        # backslash test must apply to the BARE token only. Testing the value instead exempted
        # that path; tests/test_docx_field_codes.py's survival list caught it.
        #
        # A BOOKMARK NAME is written BOTH WAYS, and this is red-team round 5, R5-08. ``REF``
        # and ``PAGEREF`` write it bare, and neither is in _FIELD_TYPES_WITH_PII_ARGS -- so
        # the bare spelling never needed the exemption at all. Word writes every TOC entry and
        # every ``\h`` cross-reference as ``HYPERLINK \l "_Toc53871234"``, QUOTED, and
        # HYPERLINK *is* examined. Eight digits is the ICO shape, ten is a rodne cislo shape,
        # so the very cross-references the morning's fix was written to protect were still
        # being rewritten to https://removed.invalid/ on the same coin flip of the digit count.
        # The value is what carries a bookmark name, so the value is what is tested.
        #
        # Matched against Word's ACTUAL bookmark namespace rather than any leading underscore,
        # so an argument that merely happens to start with one is still examined.
        if bare is not None and bare.startswith("\\"):
            return m.group(0)
        if _WORD_BOOKMARK_RE.match(value):
            return m.group(0)
        if not _target_carries_pii(value, known_entities, config):
            return m.group(0)
        state["changed"] = True
        return f'"{_SCRUBBED_TARGET}"' if quoted is not None else _SCRUBBED_TARGET

    out = _FIELD_ARG_RE.sub(repl, instr)
    return out if state["changed"] else None


def _scrub_field_codes(root, known_entities, config) -> None:
    """Scrub PII out of every field instruction under ``root``, in both of Word's spellings."""
    for fld in root.findall(".//" + qn("w:fldSimple")):
        instr = fld.get(qn("w:instr"))
        if instr:
            scrubbed = _scrub_field_instruction(instr, known_entities, config)
            if scrubbed is not None:
                fld.set(qn("w:instr"), scrubbed)

    # Word splits one instruction across several <w:instrText> runs whenever it feels like it
    # ('HYPERLINK "mailto:' in one run and the rest in the next), so the instruction is
    # reassembled before it is read -- a per-element scrub would see half a URL and find
    # nothing in it. The group boundary is <w:fldChar>, which delimits every field, so two
    # fields in one paragraph are never welded into one instruction.
    group: list = []
    groups: list[list] = []
    for elem in root.iter(qn("w:instrText"), qn("w:fldChar")):
        if elem.tag == qn("w:fldChar"):
            if group:
                groups.append(group)
                group = []
        else:
            group.append(elem)
    if group:
        groups.append(group)

    for group in groups:
        joined = "".join(e.text or "" for e in group)
        scrubbed = _scrub_field_instruction(joined, known_entities, config)
        if scrubbed is None:
            continue
        group[0].text = scrubbed
        for e in group[1:]:
            e.text = ""


# ----------------------------------------------------------------- DATA BINDING (R4-T8)
def _strip_data_bindings(root) -> None:
    """Remove every <w:dataBinding> from a content control.

    A data-bound content control does NOT display the text sitting in its <w:sdtContent>: Word
    re-populates it from a customXml part every time the file is opened. So redacting the
    on-page run produced a document that reads "[MENO_1]" to this tool and shows the party's
    name to the next person who opens it (red-team round 4, R4-T8). Every Word form built on
    the Developer tab and every document-assembly system (HotDocs, Contract Express, a DMS
    macro) produces this shape.

    BOTH halves of the fix are applied -- the binding is removed here and the store is blanked
    in _scrub_extra_parts -- rather than the one the finding said would do. Removing the
    binding alone leaves the name in customXml, which eval/extract.py reads as other_xml_parts
    and grades as a leak, correctly: the data is still in the package whatever Word chooses to
    display. Blanking the store alone leaves a live binding pointing at an empty node, so any
    tool that re-binds from a restored store puts the name back. Neither half is sufficient and
    together they are four lines."""
    for binding in root.findall(".//" + qn("w:dataBinding")):
        parent = binding.getparent()
        if parent is not None:
            parent.remove(binding)


# OPC parts that carry PII and that nothing used to touch (red-team round 4, R4-M1/M2/M3).
# eval/extract.py already READS all three, so a leak here was gated -- it was simply never
# scrubbed. Blanked BY POSITION, like docProps/core.xml: a template variable named ClientName
# or a comment author's e-mail address is personal data whether or not it matches a detector
# pattern, and the original value is never preserved.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
_CUSTOM_PROPS = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
_VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
_CUSTOM_XML_ITEM_RE = re.compile(r"^customxml/item\d*\.xml$")


def _scrub_extra_parts(path: str) -> int:
    """Blank PII-bearing values in settings.xml, custom.xml and people.xml of a saved .docx.

    Rewrites the package in place. Returns how many values were blanked. The PARTS are kept
    rather than deleted: removing word/people.xml would dangle its relationship, and Word
    reports a dangling relationship as a corrupt file.
    """
    with zipfile.ZipFile(path) as zin:
        items = [(n, zin.read(n)) for n in zin.namelist()]

    blanked = 0
    rewritten = []
    for name, data in items:
        lowered = name.lower()
        try:
            if lowered == "word/settings.xml":
                root = etree.fromstring(data)
                for var in root.findall(".//" + _W + "docVar"):
                    if var.get(_W + "val"):
                        var.set(_W + "val", "")
                        blanked += 1
                data = etree.tostring(root, encoding="UTF-8", standalone=True)
            elif lowered == "docprops/custom.xml":
                root = etree.fromstring(data)
                for prop in root.findall(_CUSTOM_PROPS + "property"):
                    for value in list(prop):
                        if value.tag.startswith(_VT) and (value.text or "").strip():
                            value.text = ""
                            blanked += 1
                data = etree.tostring(root, encoding="UTF-8", standalone=True)
            elif _CUSTOM_XML_ITEM_RE.match(lowered):
                # The other half of R4-T8: the STORE a data-bound content control reads from.
                # Blanked WHOLESALE -- every text node in the part -- rather than only the node
                # the w:xpath names, for two reasons. The xpath's namespace prefixes are
                # declared in the sdtPr's own scope and Word rewrites them freely, so resolving
                # it correctly is guesswork, and a guess here is a leak. And the part is an
                # application's private data store that no reviewer ever reads, so blanking a
                # value that was not PII costs nothing at all -- the asymmetry this whole tool
                # is built on. itemProps*.xml is NOT matched: it holds the store's GUID and
                # schema refs, and clearing those would orphan the store.
                root = etree.fromstring(data)
                for node in root.iter():
                    if (node.text or "").strip():
                        node.text = ""
                        blanked += 1
                data = etree.tostring(root, encoding="UTF-8", standalone=True)
            elif lowered == "word/people.xml":
                root = etree.fromstring(data)
                for person in root.findall(".//" + _W15 + "person"):
                    if person.get(_W15 + "author"):
                        person.set(_W15 + "author", "")
                        blanked += 1
                    for presence in person.findall(_W15 + "presenceInfo"):
                        if presence.get(_W15 + "userId"):
                            presence.set(_W15 + "userId", "")
                            blanked += 1
                data = etree.tostring(root, encoding="UTF-8", standalone=True)
        except etree.XMLSyntaxError:
            # A malformed part is left exactly as it was rather than crashing the redaction.
            # It is still graded by the leak gate, so a leak here cannot pass unnoticed.
            pass
        rewritten.append((name, data))

    if blanked:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in rewritten:
                zout.writestr(name, data)
    return blanked


def _drop_thumbnail(path: str) -> None:
    """Remove ``docProps/thumbnail.*`` and its relationship from a saved .docx.

    Rewrites the package without the thumbnail part and strips the matching Relationship entry
    from ``_rels/.rels`` (leaving a dangling relationship would make Word report the file as
    corrupt). Every other part is copied through byte-for-byte, so the redacted content itself
    is untouched. A document with no thumbnail is left exactly as it was.
    """
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        thumbs = [n for n in names if n.lower().startswith("docprops/thumbnail")]
        if not thumbs:
            return
        items = [(n, zin.read(n)) for n in names]

    thumb_set = set(thumbs)
    rewritten = []
    for name, data in items:
        if name in thumb_set:
            continue
        if name == "_rels/.rels":
            root = etree.fromstring(data)
            for rel in list(root):
                target = (rel.get("Target") or "").lstrip("/")
                if target.lower().startswith("docprops/thumbnail"):
                    root.remove(rel)
            data = etree.tostring(root, encoding="UTF-8", standalone=True)
        rewritten.append((name, data))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in rewritten:
            zout.writestr(name, data)


def _open_docx(in_path: str):
    """Open a .docx, converting anything the library can raise into a named refusal.

    context.md 3 promises a refusal for a document the tool cannot process, with a message the
    reviewer can act on. Measured before this existed (red-team round 4, R4-X3): a malformed
    .rels part raised lxml's "Couldn't find end of Start Tag broken line 1", and a file that is
    not a ZIP raised PackageNotFoundError. Neither reaches the lawyer as anything but a library
    message, and neither answers the question they actually have -- whether a half-redacted
    file is now sitting on disk.

    Raised HERE, before any output is created, so the answer is always "nothing was written".
    """
    try:
        return Document(in_path)
    except Exception as exc:  # noqa: BLE001 -- python-docx, lxml and zipfile all reach here
        raise UnreadableDocumentError(in_path, f"{type(exc).__name__}: {exc}") from exc


def _redact_docx(
    in_path: str, out_path: str, known_entities: list[str] | None,
    decisions: RedactionDecisions | None,
    config: DetectConfig | None = None,
) -> LabelMap:
    """Open ``in_path``, redact auto-detected PII across every <w:p> location W2 covers —
    body paragraphs, table cells, header/footer paragraphs, header/footer tables and VML
    textboxes (body + header/footer parts) — and save the result to a NEW file ``out_path``.
    ``in_path`` is never modified. Returns the document's LabelMap (Phase 6 scan harvest)."""
    # Phase 6: reviewer-supplied extra terms join known_entities BEFORE anything runs, so they
    # flow through detect()'s declension matching exactly like GT party names.
    if decisions is not None and decisions.extra_terms:
        extras = [t.strip() for t in decisions.extra_terms if t.strip()]
        known_entities = list(known_entities or []) + extras

    doc = _open_docx(in_path)

    # ONE LabelMap for the whole document, built BEFORE the passes: it is threaded through every
    # _redact_paragraph call so a given entity gets the same [TYPE_N] number everywhere (body,
    # tables, headers/footers, textboxes, notes). First-seen group order == the fixed traversal
    # order of the passes below, so the numbering is deterministic (W5a, context.md §10).
    labelmap = LabelMap(known_entities)

    # THE trees this document has — body, all six header/footer parts of every section, the
    # three note parts and the glossary document — enumerated ONCE and iterated by every pass
    # below. See _document_trees: the passes used to enumerate this for themselves, four times,
    # and each of the four knew a different subset (R5-01 / R5-03 / R5-04).
    trees = _document_trees(doc)

    # 0-) R5-02: an embedded sub-document (w:altChunk) is refused BEFORE anything is written, so
    #     the refusal's "nothing was written" is true by construction rather than by cleanup.
    #     Every altChunk, not only the ones that look like they carry PII -- see
    #     EmbeddedSubDocumentError for the argument.
    alt_chunks = _alt_chunk_parts(in_path, trees)
    if alt_chunks:
        raise EmbeddedSubDocumentError(in_path, alt_chunks)

    # 0) W4a: accept ALL tracked revisions FIRST, before any _redact_paragraph call. Deleted
    #    text is then physically gone (it must never reach detect() as a redaction candidate);
    #    inserted text, once unwrapped, is ordinary body text that the passes below still redact
    #    (so an insertion carrying PII is caught by the existing W1-W3 code — no special-casing).
    for tree in trees:
        _strip_tracked_changes(tree.element)
        # ONE attribute sweep per tree, straight after the strip so it also reaches the revision
        # bookkeeping the strip leaves behind. Alt text, bookmark names, content-control aliases,
        # dropdown lists and legacy form-field defaults (R5-07) all live on the attribute plane,
        # which no paragraph pass can see.
        _scrub_attributes(tree.element)

    # 0b) Field instructions and data bindings, for the same reason the tracked-change strip
    #     runs first: both carry PII that is not text detect() can see, and both must be settled
    #     before the paragraph passes rewrite the runs around them.
    for tree in trees:
        _scrub_field_codes(tree.element, known_entities, config)
        _strip_data_bindings(tree.element)

    # ONE descendant walk per tree, replacing the four direct-child walks this used to do
    # (body paragraphs, body tables' cells, header/footer paragraphs and tables, textboxes).
    # Each <w:p> is visited exactly once and tags itself by where it sits, so a nested table,
    # a content control and a table inside a textbox are all covered without a special case
    # for each -- and adding one more container shape needs no new traversal at all.
    #
    # The note parts arrive here too: every <w:p> in them — including the separator /
    # continuationSeparator entries that carry no <w:t> — is wrapped as a Paragraph so ``.runs``
    # exposes the inner runs, and an empty separator paragraph no-ops (detect() over "" yields
    # nothing).
    for tree in trees:
        for p_elem in _all_paragraph_elements(tree.element):
            _redact_paragraph(
                Paragraph(p_elem, tree.parent),
                known_entities,
                labelmap,
                _paragraph_location(p_elem, tree.location),
                decisions=decisions,
                config=config,
                record=not _is_alternate_fallback(p_elem),
            )

    # 5) Blob-backed trees (footnotes, endnotes, glossary) are serialised back into their parts
    #    now that every pass has run over them. Live trees no-op.
    for tree in trees:
        _close_tree(tree)

    # 6) W4b: blank PII-bearing metadata (core.xml properties, every free-text value in
    #    app.xml, and the comment w:author/w:initials deferred from W3) LAST, unconditionally
    #    by position. Still BEFORE doc.save(), so a refusal raised in here leaves no output.
    _scrub_metadata(doc, in_path)

    doc.save(out_path)

    # 6b) v1.1 (red-team finding B-2): DROP docProps/thumbnail.jpeg from the saved package.
    #     That part is a RENDERED PICTURE OF PAGE 1. Word writes one into every document saved
    #     with "Save Thumbnail" on, and python-docx copies unknown parts through byte-for-byte,
    #     so the redacted output shipped a little image of the UN-redacted first page — names,
    #     rodné číslo and all. No text extractor can see it, so the leak test scored it clean
    #     and always would have: it is pixels, not text. It has to be deleted rather than
    #     graded. Done as a post-save ZIP rewrite because python-docx offers no API to remove
    #     an arbitrary package part, and done AFTER doc.save so nothing in the redaction path
    #     depends on it.
    try:
        _drop_thumbnail(out_path)
        # Hyperlink destinations live in .rels, which no paragraph pass can reach.
        _scrub_rel_targets(out_path, known_entities, config)
        # settings.xml / custom.xml / people.xml / customXml: parts no paragraph pass reaches.
        _scrub_extra_parts(out_path)
    except UnreadableDocumentError:
        # These passes run AFTER doc.save, so a refusal raised here would otherwise leave a
        # partially scrubbed file on disk -- and the refusal's own message promises that
        # nothing was written. Deleting the output is what makes that sentence true.
        if os.path.exists(out_path):
            os.remove(out_path)
        raise

    # 7) W5b-2: emit the per-document report NEXT TO out_path (<stem>_report.txt), built from the
    #    LabelMap's capture side-channels (occurrences + low_confidence) the passes above filled.
    #    Purely additive — a separate .txt file that does not touch the redacted .docx bytes; the
    #    path is derived from out_path so the report can never desync from the document it records.
    write_report(out_path, labelmap.occurrences, labelmap.low_confidence,
                 labelmap.checksums, labelmap.lc_checksums,
                 labelmap.detector_failures)

    return labelmap


def redact_docx_body(
    in_path: str, out_path: str, known_entities: list[str] | None = None,
    *, decisions: RedactionDecisions | None = None, config: DetectConfig | None = None,
) -> None:
    """Public writer entry — unchanged contract; decisions default to None (old behaviour).
    ``config=None`` means detect()'s DEFAULT DetectConfig, i.e. byte-identical pre-v1.1 calls."""
    _redact_docx(in_path, out_path, known_entities, decisions, config)


def redact_docx_collect(
    in_path: str, out_path: str, known_entities: list[str] | None = None,
    *, decisions: RedactionDecisions | None = None, config: DetectConfig | None = None,
) -> LabelMap:
    """Same redaction, but returns the document's LabelMap — the GUI's scan harvest."""
    return _redact_docx(in_path, out_path, known_entities, decisions, config)
