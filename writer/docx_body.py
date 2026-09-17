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
part-type asymmetry (see _redact_notes_part) but every note is an ordinary <w:p> once located,
so the SAME core is reused again. W3 does NOT scrub the comment w:author attribute — that is
W4 metadata scope. Labels are type-only ("[MENO]"); per-entity numbering ("[MENO_1]") is W5.
The input file is never modified — output is a new file.

W4b (context.md §10) scrubs document METADATA that carries PII: docProps/core.xml properties
(dc:creator, cp:lastModifiedBy, ...), docProps/app.xml's Company/Manager free-text fields, and
the comment w:author/w:initials attributes deferred from W3 (see _redact_notes_part). These are
BLANKED UNCONDITIONALLY BY POSITION — detect() never runs over metadata, since an author or
manager name is PII regardless of whether it matches a detector pattern, and the original value
is never preserved (see _scrub_metadata).
"""
from __future__ import annotations

import re
import urllib.parse
import zipfile
from copy import deepcopy

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from lxml import etree

from detect.config import DetectConfig
from detect.core import detect_with_failures
from writer.decisions import RedactionDecisions
from writer.errors import UnreadableDocumentError
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


def _strip_notes_tracked_changes(part) -> None:
    """Accept all tracked revisions in a footnotes/endnotes/comments OPC part, honouring the SAME
    element-vs-blob asymmetry as _redact_notes_part: a CommentsPart exposes a live ``.element``
    that re-serialises into ``.blob`` (mutate it in place); generic footnote/endnote Parts are
    blob-backed with no ``.element`` (parse, strip, reassign ``._blob``)."""
    if hasattr(part, "element") and part.element is not None:
        _strip_tracked_changes(part.element)  # live tree; mutate in place
        return
    tree = parse_xml(part._blob)
    _strip_tracked_changes(tree)
    part._blob = etree.tostring(tree, encoding="UTF-8", standalone=True)


# The <w:r> children that CONTRIBUTE CHARACTERS to run.text, and therefore to the offsets
# detect() is given. python-docx renders w:t as its text, w:tab as "\t", and w:br / w:cr as
# "\n"; w:noBreakHyphen and w:softHyphen render as their characters. All of them must be
# dropped when a run is rebuilt, or their text is duplicated into every fragment.
_TEXT_BEARING = frozenset({
    qn("w:t"), qn("w:tab"), qn("w:br"), qn("w:cr"),
    qn("w:noBreakHyphen"), qn("w:softHyphen"), qn("w:delText"),
})
# Split a fragment so tabs and line breaks can be re-emitted as the elements they were.
_TEXT_SPLIT_RE = re.compile(r"([\t\n])")


def _rebuild_run(run, fragments: list[tuple[str, str]]) -> None:
    """Replace a single <w:r> with one new <w:r> per fragment, cloning the original run's
    formatting onto each. ``fragments`` is an ordered list of ('t', text) surviving-text and
    ('l', label) replacement pieces. An empty list means the whole run was covered -> remove.
    """
    r_elem = run._r
    parent = r_elem.getparent()
    idx = parent.index(r_elem)

    for offset, (_kind, value) in enumerate(fragments):
        clone = deepcopy(r_elem)  # carries a copy of <w:rPr> so formatting is preserved
        # EVERY text-bearing child is removed, not just the first <w:t> rewritten. See
        # _TEXT_BEARING: a run can hold several, python-docx never emits one that does, and
        # the old code copied the extras into every fragment with their ORIGINAL TEXT.
        for child in list(clone):
            if child.tag in _TEXT_BEARING:
                clone.remove(child)
        # The fragment's own text is then re-emitted STRUCTURALLY: run.text renders <w:tab/>
        # as "\t" and <w:br/> as "\n", and those characters are inside the offsets detect()
        # was given, so writing them back as literal characters inside a <w:t> would silently
        # turn a line break into a space. Splitting them back out keeps the document looking
        # like itself.
        for piece in _TEXT_SPLIT_RE.split(value):
            if piece == "":
                continue
            if piece == "\t":
                clone.append(clone.makeelement(qn("w:tab"), {}))
            elif piece == "\n":
                clone.append(clone.makeelement(qn("w:br"), {}))
            else:
                t = clone.makeelement(qn("w:t"), {})
                t.text = piece
                # Preserve leading/trailing whitespace in the fragment (labels have none, but
                # a surviving boundary fragment like ' súhlasí' does).
                t.set(_XML_SPACE, "preserve")
                clone.append(t)
        parent.insert(idx + offset, clone)

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
) -> None:
    """Redact auto PII in one paragraph and record report-capture side-effects tagged with
    ``location`` (one of the fixed vocabulary strings, matching GT surface_part). The default is
    ``"body"``, the safe fallback for an un-tagged call — every real caller now passes
    ``location`` explicitly, including ``_redact_cells`` for body table cells."""
    # Every run in the paragraph, nested ones included -- NOT paragraph.runs, which is a
    # direct-child view and silently omits anything inside a <w:hyperlink> or a <w:sdt>.
    runs = [Run(r, paragraph) for r in _paragraph_runs(paragraph._p)]
    if not runs:
        return

    # Reconstruct paragraph text and remember which run owns each character offset.
    run_start: list[int] = []
    owner: list[int] = []
    pieces: list[str] = []
    pos = 0
    for ri, r in enumerate(runs):
        run_start.append(pos)
        text = r.text
        pieces.append(text)
        owner.extend([ri] * len(text))
        pos += len(text)
    recon = "".join(pieces)

    # ONE detect() over the post-strip reconstructed text; both captures below read this same
    # result the redaction path uses — never a second detect() over a different tree state.
    detected, failures = detect_with_failures(recon, known_entities, config)
    for f in failures:
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
        else:
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
        labelmap.record_occurrence(
            label_at[c.start], location, c.surface,
            snippet=make_snippet(recon, c.start, c.end),
            checksum=c.checksum,
        )

    # Build, per touched run, the ordered surviving-text / label fragments, then rewrite it.
    for ri, r in enumerate(runs):
        rs = run_start[ri]
        re = rs + len(r.text)
        touched = any(covered[i] or i in label_at for i in range(rs, re))
        if not touched:
            continue  # leave the run — and its exact XML — completely alone

        fragments: list[tuple[str, str]] = []
        buf = ""
        for i in range(rs, re):
            if i in label_at:
                if buf:
                    fragments.append(("t", buf))
                    buf = ""
                fragments.append(("l", label_at[i]))
            if not covered[i]:
                buf += recon[i]
        if buf:
            fragments.append(("t", buf))

        _rebuild_run(r, fragments)


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


def _redact_notes_part(
    part, known_entities, labelmap, location: str = "footnote",
    decisions: RedactionDecisions | None = None,
    config: DetectConfig | None = None,
) -> None:
    """Redact every <w:p> in a footnotes/endnotes/comments OPC part, honouring the part-type
    asymmetry python-docx exposes on reopen (verified by probe):

    * comments.xml maps to a registered CommentsPart (an XmlPart): its ``.element`` is a live
      tree and its ``.blob`` RE-SERIALIZES from that tree, so a ``._blob`` reassignment would be
      silently discarded. The tree is mutated IN PLACE and doc.save() picks it up.
    * footnotes.xml / endnotes.xml have no registered class and come back as generic blob-backed
      Parts with no ``.element``. Their bytes are parsed, the parsed tree is mutated, and the
      serialized result is written back to ``._blob`` (generic ``Part.blob`` returns ``_blob``,
      so doc.save() persists it).

    Branch on element-vs-blob, never on part name or note id. Each <w:p> — including the
    separator / continuationSeparator entries that carry no <w:t> — is wrapped as a Paragraph so
    ``.runs`` exposes the inner runs, then pushed through the same _redact_paragraph core; an
    empty separator paragraph no-ops (detect() over "" yields nothing)."""
    if hasattr(part, "element") and part.element is not None:
        tree = part.element  # live tree; mutate in place
        for p_elem in tree.findall(".//" + qn("w:p")):
            _redact_paragraph(Paragraph(p_elem, part), known_entities, labelmap, location, decisions=decisions, config=config)
        return

    tree = parse_xml(part._blob)
    for p_elem in tree.findall(".//" + qn("w:p")):
        _redact_paragraph(Paragraph(p_elem, part), known_entities, labelmap, location,
                          decisions=decisions, config=config)
    # Mirror python-docx's own part serialization (UTF-8, standalone declaration).
    part._blob = etree.tostring(tree, encoding="UTF-8", standalone=True)


_APP_XML_PII_TAGS = ("Company", "Manager")


def _scrub_metadata(doc) -> None:
    """W4b (context.md §10): blank the three PII-bearing metadata locations, by position —
    never via detect(), never preserving the original value.

    * docProps/core.xml: exposed through python-docx's ``doc.core_properties`` (each is a
      settable str property backed by a ZeroOrOne element); the API write persists through
      doc.save(). created/modified/revision are dates/ints, not PII, and are left alone.
    * docProps/app.xml: python-docx has no API for this part — it comes back as a generic
      blob-backed Part. Company/Manager are located with a targeted regex on the decoded
      blob so every unrelated tag (HeadingPairs, TitlesOfParts, vt: vectors, the <?xml?>
      declaration) is byte-preserved; only a NON-EMPTY <Tag>...</Tag> is rewritten, so an
      already-empty <Tag/>/<Tag></Tag> is left as-is rather than needlessly touched.
    * word/comments.xml <w:comment w:author=...>: deferred from W3's _redact_notes_part.
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
        xml = part._blob.decode("utf-8")
        for tag in _APP_XML_PII_TAGS:
            xml = re.sub(rf"<{tag}>.+?</{tag}>", f"<{tag}></{tag}>", xml, flags=re.DOTALL)
        part._blob = xml.encode("utf-8")
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
_TARGET_PUNCT_RE = re.compile(r"[/\\_+:?=&#]+")


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
    for probe in (target, _TARGET_PUNCT_RE.sub(" ", target).replace("-", " ")):
        for c in detect_with_failures(probe, known_entities, config)[0]:
            if c.type not in _TARGET_IGNORED_TYPES:
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
            root = etree.fromstring(data)
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


# OPC parts that carry PII and that nothing used to touch (red-team round 4, R4-M1/M2/M3).
# eval/extract.py already READS all three, so a leak here was gated -- it was simply never
# scrubbed. Blanked BY POSITION, like docProps/core.xml: a template variable named ClientName
# or a comment author's e-mail address is personal data whether or not it matches a detector
# pattern, and the original value is never preserved.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
_CUSTOM_PROPS = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
_VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"


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

    # 0) W4a: accept ALL tracked revisions FIRST, before any _redact_paragraph call. Deleted
    #    text is then physically gone (it must never reach detect() as a redaction candidate);
    #    inserted text, once unwrapped, is ordinary body text that the passes below still redact
    #    (so an insertion carrying PII is caught by the existing W1-W3 code — no special-casing).
    #    Covers the document element, every section header/footer element, and each note part
    #    (same discovery + blob-vs-element asymmetry as the W3 pass below).
    _strip_tracked_changes(doc.element)
    for section in doc.sections:
        for hf in (section.header, section.footer):
            _strip_tracked_changes(hf._element)
    for rel in doc.part.rels.values():
        rt = rel.reltype
        if rt.endswith("footnotes") or rt.endswith("endnotes") or rt.endswith("comments"):
            _strip_notes_tracked_changes(rel.target_part)

    # ONE descendant walk per part, replacing the four direct-child walks this used to do
    # (body paragraphs, body tables' cells, header/footer paragraphs and tables, textboxes).
    # Each <w:p> is visited exactly once and tags itself by where it sits, so a nested table,
    # a content control and a table inside a textbox are all covered without a special case
    # for each -- and adding one more container shape needs no new traversal at all.
    roots = [(doc.element.body, doc, "body")]
    for section in doc.sections:
        roots.append((section.header._element, section.header, "header"))
        roots.append((section.footer._element, section.footer, "footer"))

    for root, parent, default_location in roots:
        for p_elem in _all_paragraph_elements(root):
            _redact_paragraph(
                Paragraph(p_elem, parent),
                known_entities,
                labelmap,
                _paragraph_location(p_elem, default_location),
                decisions=decisions,
                config=config,
            )

    # 5) footnotes / endnotes / comments — each a SEPARATE OPC part, not in document.xml (W3).
    #    The location tag follows the note part type.
    _NOTE_LOCATIONS = (("footnotes", "footnote"), ("endnotes", "endnote"), ("comments", "comment"))
    for rel in doc.part.rels.values():
        rt = rel.reltype
        loc = next((location for suffix, location in _NOTE_LOCATIONS if rt.endswith(suffix)), None)
        if loc is not None:
            _redact_notes_part(rel.target_part, known_entities, labelmap, loc, decisions=decisions, config=config)

    # 6) W4b: blank PII-bearing metadata (core.xml properties, app.xml Company/Manager, and
    #    the comment w:author/w:initials deferred from W3) LAST, unconditionally by position.
    _scrub_metadata(doc)

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
    _drop_thumbnail(out_path)
    # Hyperlink destinations live in .rels, which no paragraph pass can reach.
    _scrub_rel_targets(out_path, known_entities, config)
    # settings.xml / custom.xml / people.xml: parts no paragraph pass reaches.
    _scrub_extra_parts(out_path)

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
