"""W1 (context.md §10): redact auto-detected PII in a DOCX's top-level body paragraphs.

The hard part is not *finding* PII — detect() does that on reconstructed paragraph text —
it is putting the redaction back onto the <w:r> run sequence. Word splits a single logical
surface across arbitrary runs, sometimes MID-TOKEN ('Luc'|'ie Molnáro'|'vej') and sometimes
MID-RUN on both ends ('Zmluva medzi Ján'|'om Novákom dnes'), and each run may carry its own
<w:rPr> formatting. So a detect() span [start,end) over the reconstructed text has to be
mapped back to exact character offsets inside runs, the covered characters removed, a single
type label inserted at the span start, and any boundary run split into fragments that each
keep a clone of the original run's <w:rPr>.

Scope is BODY ONLY (doc.paragraphs): tables, headers/footers, notes, comments and textboxes
are W2/W3 and are intentionally left untouched here. Labels are type-only ("[MENO]"); per
-entity numbering ("[MENO_1]") is W5. The input file is never modified — output is a new file.
"""
from __future__ import annotations

from copy import deepcopy

from docx import Document
from docx.oxml.ns import qn

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


def redact_docx_body(
    in_path: str, out_path: str, known_entities: list[str] | None = None
) -> None:
    """Open ``in_path``, redact auto-detected PII in every top-level body paragraph, and save
    the result to a NEW file ``out_path``. ``in_path`` is never modified."""
    doc = Document(in_path)
    for paragraph in doc.paragraphs:
        _redact_paragraph(paragraph, known_entities)
    doc.save(out_path)
