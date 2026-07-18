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
"""
from __future__ import annotations

from copy import deepcopy

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from detect.core import detect

# xml:space lives in the reserved XML namespace, which is not in python-docx's nsmap, so it
# cannot go through qn(); set it by its literal Clark-notation name.
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


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
        t = clone.find(qn("w:t"))
        if t is None:
            t = clone.makeelement(qn("w:t"), {})
            clone.append(t)
        t.text = value
        # Preserve any leading/trailing whitespace in the fragment (labels have none, but a
        # surviving boundary fragment like ' súhlasí' does).
        t.set(_XML_SPACE, "preserve")
        parent.insert(idx + offset, clone)

    parent.remove(r_elem)


def _redact_paragraph(paragraph, known_entities) -> None:
    runs = list(paragraph.runs)
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

    cands = [c for c in detect(recon, known_entities) if c.auto]
    if not cands:
        return

    covered = [False] * len(recon)
    label_at: dict[int, str] = {}
    for c in cands:
        for i in range(c.start, c.end):
            covered[i] = True
        # detect() guarantees non-overlapping spans, so one label per start is unambiguous;
        # setdefault keeps this robust if two spans ever shared a start.
        label_at.setdefault(c.start, f"[{c.type}]")

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


def _redact_cells(table, known_entities) -> None:
    """Redact every cell paragraph in ``table``. A merged cell makes several (row, col)
    positions return the SAME <w:tc> element; dedup by tc identity so a shared paragraph is
    processed exactly once (reprocessing is otherwise wasted work and re-runs detect on
    already-labelled text)."""
    seen: set[int] = set()
    for row in table.rows:
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            for paragraph in cell.paragraphs:
                _redact_paragraph(paragraph, known_entities)


def _redact_textboxes(element, parent, known_entities) -> None:
    """Redact every <w:p> nested in any <w:txbxContent> under ``element`` (a document body
    or a header/footer part element). VML textboxes are unreachable through python-docx's
    paragraph APIs, so each inner <w:p> is wrapped as a Paragraph — whose .runs then expose
    the inner runs — and pushed through the same remap. ``parent`` is only a proxy handle;
    the remap operates on the run elements directly, so its exact value is not load-bearing."""
    for txbx in element.findall(".//" + qn("w:txbxContent")):
        for p_elem in txbx.findall(qn("w:p")):
            _redact_paragraph(Paragraph(p_elem, parent), known_entities)


def _redact_notes_part(part, known_entities) -> None:
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
            _redact_paragraph(Paragraph(p_elem, part), known_entities)
        return

    tree = parse_xml(part._blob)
    for p_elem in tree.findall(".//" + qn("w:p")):
        _redact_paragraph(Paragraph(p_elem, part), known_entities)
    # Mirror python-docx's own part serialization (UTF-8, standalone declaration).
    part._blob = etree.tostring(tree, encoding="UTF-8", standalone=True)


def redact_docx_body(
    in_path: str, out_path: str, known_entities: list[str] | None = None
) -> None:
    """Open ``in_path``, redact auto-detected PII across every <w:p> location W2 covers —
    body paragraphs, table cells, header/footer paragraphs, header/footer tables and VML
    textboxes (body + header/footer parts) — and save the result to a NEW file ``out_path``.
    ``in_path`` is never modified."""
    doc = Document(in_path)

    # 1) top-level body paragraphs (W1).
    for paragraph in doc.paragraphs:
        _redact_paragraph(paragraph, known_entities)

    # 2) body tables' cells.
    for table in doc.tables:
        _redact_cells(table, known_entities)

    # 3) header/footer paragraphs + their tables, across every section.
    for section in doc.sections:
        for hf in (section.header, section.footer):
            for paragraph in hf.paragraphs:
                _redact_paragraph(paragraph, known_entities)
            for table in hf.tables:
                _redact_cells(table, known_entities)

    # 4) VML textboxes anywhere: body part, then every header/footer part.
    _redact_textboxes(doc.element.body, doc, known_entities)
    for section in doc.sections:
        for hf in (section.header, section.footer):
            _redact_textboxes(hf._element, hf, known_entities)

    # 5) footnotes / endnotes / comments — each a SEPARATE OPC part, not in document.xml (W3).
    for rel in doc.part.rels.values():
        rt = rel.reltype
        if rt.endswith("footnotes") or rt.endswith("endnotes") or rt.endswith("comments"):
            _redact_notes_part(rel.target_part, known_entities)

    doc.save(out_path)
