# Red-team findings, round 6 — THE PDF CONTAINER

> ## STATUS, end of the daytime run 2026-09-17: **TEN OF ELEVEN CLOSED, SAME DAY**
>
> | finding | state |
> |---|---|
> | R6-01 outlines · R6-02 link targets · R6-05 hidden layer · R6-06 CropBox · R6-09 degenerate rect · R6-10 silent report | **FIXED** |
> | R6-03 catalogue · R6-03b short needle on `pdf_objects` · R6-04 `/AF` attachment · R6-04b its gate verdict · R6-07 page XMP · R6-07b its gate verdict | **FIXED** |
> | **R6-08** shared Form XObject residue | **OPEN**, marker intact |
>
> The prose below is the round AS WRITTEN, before any fix — it is the record of what was true
> when it was found, and the "suggested fix" sections are what was proposed, not always what
> landed. Two places where the fix DIVERGED from the proposal, both deliberately:
>
> * **R6-03b.** The round proposed taking `pdf_objects` out of `_OPAQUE_SURFACES`. Measured, that
>   turns the gate RED on a correctly redacted corpus document: `'1100'` occurs inside a CID
>   font's `/W` widths array. So the opaque premise IS true for the font machinery and false only
>   for the dictionary-VALUE part. Shipped instead: a match inside a PDF **string literal** or hex
>   string counts at any length, scoped to `pdf_objects`. Corpus effect: none.
> * **R6-04b / R6-07b.** As filed, both required the gate to COUNT the needle in the OUTPUT —
>   satisfiable only while the finding is open. Once the writer deletes the attachment there is
>   nothing left to count, and `counted=()` means "clean" and "blind" alike, which is the one
>   conflation these sub-findings exist to prevent. Both now grade the INPUT.
>
> One ordering bug was found while fixing: `rehide()` must run BEFORE the catalogue scrub, because
> `unhide()` nulls `/OCProperties` and the optional-content group whose NAME is the client's was
> therefore unreachable at exactly the moment the scrub went looking for it.

*Transcribed to disk by the orchestrator: the round's harness forbids subagents writing report
files. Every number below is reproduced by `tests/test_redteam_round6.py`, which IS on disk and
is the authority if the two ever disagree.*

**Target: the objects PyMuPDF writes into the output file and a reader renders from it.**

Rounds 1–5 attacked the DOCX package (1, 2, 4, 5) and the PDF **text layer** (3).
`writer/pdf_body.py` is 612 lines against `writer/docx_body.py`'s 1536, and its entire non-page
scrub is nine lines:

```python
def _scrub_document_surfaces(doc):
    doc.set_metadata({})
    doc.del_xml_metadata()
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
```

Three surfaces. A PDF document catalogue has about a dozen more, every one of which a court, the
cadastre or opposing counsel routinely populates. Round 6 attacks the catalogue, optional
content, the CropBox, associated files, the structure tree, and the residue a save leaves behind.

---

## 1. RESULT

**28 attacks attempted. 10 found a real defect.** Three further xfails are *gate verdicts* on
findings already filed (R6-03b, R6-04b, R6-07b), following round 5's R5-02b precedent.

```
pytest tests/test_redteam_round6.py -q   ->  26 passed, 13 xfailed
pytest tests/ -q                         ->  1673 passed, 8 skipped, 25 xfailed, 0 failed
```

The 26 passing tests are CONTROLS of three kinds: **reachability** (the needle is provably on the
expected surface of the unredacted fixture), **contrast** (the identical PII in the plane the
writer DOES cover is redacted in the same run, so the finding is attributable to the missing
traversal), and **did-not-reproduce** (eleven attacks that HELD, kept as passing tests so nobody
re-runs them and a regression turns the suite red instead of becoming a round-7 finding).

Every fixture carries a long needle (`Maria Kovacova`, 14 chars), a medium one (`855612/7788`)
**and two short ones** (`04001`, a Slovak PSČ; `1100`, a bank code). Deliberate: round 5's single
most valuable lesson was that a fixture with only long needles would have graded R5-02 as "the
gate catches it" and sent the fix in the wrong direction. It paid off twice here.

**Expectations for all 28 attacks were written and frozen before the first probe ran** (§4 records
where they were wrong).

---

## 2. FINDINGS, RANKED BY SEVERITY

### R6-04 · SEVERITY 1, THE WORST IN THE ROUND — an `/AF` associated file ships unredacted, and **no surface of `eval/extract.py` can see it at all**

`/Names /EmbeddedFiles` is one of *two* ways a PDF carries an attachment. The other is `/AF` — an
**associated file**, PDF 2.0 §14.13, the mechanism PDF/A-3 is built on. It is how an e-invoice
carries its XML, how a hybrid cadastre export carries its source data, and what Acrobat writes
when the attachment is associated with the document rather than a page.

`doc.embfile_names()` lists the **name tree only**. A file reached by `/AF` is not in it, so the
delete loop never runs, and `garbage=4` keeps it because it is reachable.

**Reproduction**: a PDF with a `.docx` attached via `/AF`, whose `word/document.xml` reads
`Kupujuci: Maria Kovacova, rodne cislo 855612/7788, PSC 04001, kod banky 1100`.

```
AssertionError: embedded client document shipped unredacted:
    ['Maria Kovacova', '855612/7788', '04001', '1100']
```

Three controls pass: the `/AF → /EF /F → stream → unzip` walk a reader's attachment pane performs
recovers all four needles from the INPUT **and from the OUTPUT**; `embfile_names() == []`, so the
writer never looks; and the gate cannot see it.

**Surface**: *none*. Measured on input and output:

```
'Maria Kovacova'   surfaces=() counted=() set_aside=()
'855612/7788'      surfaces=() counted=() set_aside=()
'04001'            surfaces=() counted=() set_aside=()
'1100'             surfaces=() counted=() set_aside=()
attachment still readable from OUTPUT: 1
```

**Does the leak gate see it?** **No — and not because of a threshold.** The `attachments` surface
reads `embfile_get` over `embfile_names()`, which is empty. `raw_bytes` inflates the PDF stream
and gets the ZIP's bytes — whose `word/document.xml` member is *itself* DEFLATED, so no decoding
of those bytes contains a word of it. Filed separately as **R6-04b**: the gate reports
`counted=()` for a fourteen-character name.

Note the asymmetry with round 5: `eval/extract.py` learned to read a nested `.docx` **for DOCX
altChunks** (`_alt_chunk_text` unzips one level, with a comment saying why). The PDF attachment
path never got that treatment, and `/AF` never got a writer pass at all. **This is R5-02 through a
different door, and round 5 predicted it in its own §7.**

**Severity**: LEAK, gate-blind, on a plane the reviewer does not open either.

**Suggested fix, both halves:** (1) `writer/pdf_body.py` stops enumerating attachments through
`embfile_names()` — walk `/AF` at catalogue and page level plus every `/Filespec` reachable from
`/Annots`, and delete the `/EF` streams and specs. Deleting is already the module's policy for
attachments, so this is consistency, not a new decision. (2) `eval/extract.py`'s `attachments`
surface must enumerate `/AF` as well as the name tree AND read one level into a ZIP payload,
exactly as `_alt_chunk_text` already does. **Without (2), fix (1) is ungated.**

*If the writer half lands alone, `test_r6_04_associated_files_are_removed` XPASSes while
`test_r6_04b_...` stays xfail. Both are strict, so that split is the signal the fix is half-done.*

### R6-05 · SEVERITY 1 — text inside an OFF optional-content group is never seen by the writer

`eval/extract.py` carries `_pdf_unhide()` with a docstring explaining that MuPDF's structured-text
device honours optional-content visibility, so text on an OFF layer "is returned by nothing" — and
drops `/OCProperties` before reading. **`writer/pdf_body.py` has no such call.**

```
AssertionError: hidden-layer text shipped unredacted: ['Maria Kovacova', '855612/7788']
```

The mechanism control measures both sides in one assertion:

```
writer's view  (page.get_text): 'Predavajuci: Jan Novak, obcan SR, bytom Kosice.\n'
extractor's view:               text_layer contains 'Maria Kovacova'
```

**Surface**: `text_layer` — the strictest there is. **Gate**: `counted=('text_layer','raw_bytes')`
→ **FAIL, no discount.** The gate would catch this the day a layered PDF entered the corpus;
`data/synthetic` has 0 of 71.

**Severity**: LEAK. Layered PDFs come out of CAD/GIS exports (ZBGIS cadastral maps), stamping
tools, and any watermark-layer workflow.

**Suggested fix**: the writer must see exactly what the extractor sees. One shared helper, called
from both. **A writer that reads a different document from the one the gate grades is how R6-05
and R6-06 both exist.**

### R6-06 · SEVERITY 1 — text outside the CropBox is never seen by the writer

The other half of `_pdf_unhide`. Acrobat's **Crop Pages** changes only the `/CropBox`: the
cropped-away band — a letterhead, a court stamp, a margin note with the fee-earner and the client
— is still fully present and is restored by resetting one number in any PDF editor.

```
AssertionError: text outside the CropBox shipped unredacted: ['Maria Kovacova', '855612/7788']
```

**Surface**: `text_layer`. **Gate**: FAIL, no discount.

**Severity**: LEAK, and worse than R6-05 on realism: *"crop out the letterhead before you send it"*
is an ordinary paralegal action, and it is exactly the action this tool exists to supersede. A
lawyer who crops the client band and then runs the anonymizer gets a file containing both the
original band and a report saying the document was redacted.

### R6-08 · SEVERITY 1 — the PRE-REDACTION content stream stays in the output when a Form XObject is shared between pages

The brief asked for revision residue. It is not in the input's prior revisions (§3 — that holds).
It is created by **this tool's own save**. When a Form XObject is referenced by more than one page,
`apply_redactions()` writes a redacted COPY and repoints the pages at it — and
`doc.save(garbage=4, deflate=True)` does **not** collect the original:

```
=== R6-08 residue xref 7 ===
  stream: b'BT /Helv 11 Tf 72 700 Td (Hlavicka: Maria Kovacova, rc 855612/7788) Tj ET\n'
  page0 : /XObject<</Fm1 8 0 R>>          <- the pages point at the REDACTED copy, xref 8
```

That is what `qpdf --qdf`, `mutool clean -d` or three lines of PyMuPDF return. Two controls bound
it: the rendered page really IS redacted on both pages (**the reviewer sees a clean document**),
and a SINGLE-page document leaves no residue — so this is about object reuse, not about redaction
being broken.

**Surface**: `raw_bytes` only; `deflate=True` means a plain byte grep finds nothing.
**Gate**: `counted=('raw_bytes',)` → FAIL.

**Severity**: LEAK, and the most insidious after R6-04 because everything visible says success.
A shared Form XObject is what stamping tools, overlay tools (`pdftk multistamp`, `qpdf --overlay`),
LaTeX and e-signature visualisers emit — and what `doc.bake()` itself constructs out of annotation
appearance streams.

**Suggested fix**: `garbage=4` is not enough — save with `garbage=4, clean=True` and then **assert
it worked**: re-open the output and fail if any stream body still contains a redacted surface.
That assertion is cheap, it is the only check here that cannot be fooled by a mechanism nobody
anticipated, and it belongs in the writer, not only in the gate.

### R6-01 · SEVERITY 1 — `/Outlines`: bookmark titles are never scrubbed

Nothing in `writer/` calls `get_toc`/`set_toc`. In a filing the bookmarks ARE the section
headings: *"Kúpna zmluva — Mária Kováčová"*, *"Príloha 3 — rodné číslo 855612/7788"*.

**Surface**: `outline` — a named TEXT surface.
**Gate**: `counted=('outline','pdf_objects','raw_bytes')`, `set_aside=()` → **FAIL, no discount.**
The gate has simply never been handed a PDF with an outline: 0 of 71 corpus PDFs have one.

**Severity**: LEAK, and the **highest-frequency** in the round — every PDF a court or the cadastre
issues has an outline.

**Suggested fix**: `doc.set_toc([])`. Deleting the outline is a navigation loss, not a content
loss, and it is the same trade the module already makes for attachments. Rewriting the titles
through `detect()` would be better and is a bigger job; deleting is the honest one-liner.

### R6-02 · SEVERITY 1 — a link annotation's `/URI` survives `doc.bake()`

`bake()` flattens what has an APPEARANCE; a Link annotation's payload is its ACTION, and MuPDF
excludes Link annotations from `page.annots()` in the first place.

**Surface**: `links` — a TEXT surface. **Gate**: FAIL, no discount.

Note the exact parallel: round 5 confirmed `_scrub_rel_targets` sweeps **every** `.rels` part, so
a `mailto:` hyperlink in a DOCX IS removed. **The PDF spelling of the identical leak is not.** The
two formats give opposite answers to the same question — which is also what
`eval/cross_format_gate.py` exists to notice and does not.

**Suggested fix**: after `bake()`, walk `page.get_links()` and either delete them or run their
`uri`/`file`/`nameddest` through the same decision the DOCX writer already makes for a
relationship target. Reuse that decision; do not write a second one.

### R6-03 · SEVERITY 1 — the document catalogue is never scrubbed: named destinations, page labels, JavaScript, OCG names, the structure tree

One root cause — the scrub knows three keys and the catalogue has a dozen — and five
reproductions, filed as one finding for the same reason round 5 filed R5-07 as one.

| # | construct | what carries the PII | who writes it |
|---|---|---|---|
| 1 | `/Dests` | the destination **name** — `Kovacova_Maria_zmluva` | Word "Insert bookmark" → PDF export |
| 2 | `/PageLabels` `/P` | the label prefix — `Kovacova-Maria-` | batch numbering / Bates stamping |
| 3 | `/OpenAction` `/JS` | a string literal in the script | forms, DMS exports |
| 4 | `/OCProperties` OCG `/Name` | the layer name — `Vrstva klienta Peter Horvath` | CAD/GIS, stamping tools |
| 5 | `/StructTreeRoot` `/Alt`, `/ActualText`, `/T` | what a screen reader **speaks** | any tagged/PDF/UA document |

(5) deserves its own sentence. `/Alt` on a `/Figure` is the alternative text for a scanned
signature or a stamp, and the natural thing to write there is *"Podpis Márie Kováčovej"*. It is
read aloud and invisible on the page. Slovak public-administration documents are required to be
accessible, so tagged PDFs are not exotic here.

**Surface**: `pdf_objects` — **OPAQUE**. Measured:

```
'Kovacova_Maria_zmluva'  counted=('pdf_objects','raw_bytes')   -> GATE FAIL
'Kovacova-Maria-'        counted=('pdf_objects','raw_bytes')   -> GATE FAIL
'Peter Horvath'          counted=('pdf_objects','raw_bytes')   -> GATE FAIL
'04001'                  set_aside=('pdf_objects','raw_bytes') -> GATE CLEAN
'1100'                   set_aside=('pdf_objects','raw_bytes') -> GATE CLEAN
```

**R6-03b**, its own xfail: a Slovak PSČ and a bank code — **both auto-redact types** — discounted
as structural noise on a plane that holds nothing but document metadata. `_OPAQUE_SURFACES`'s
premise is that these surfaces cannot hold document text and a short match is a font table or an
xref offset. `pdf_objects` is `doc.xref_object()` — **the source of every dictionary in the file**,
which is where a PDF keeps its titles, labels, names and alt text. That premise is false for
`pdf_objects` in the same way round 5 showed it was false for `binary_parts`.

**Suggested fix**: a `_scrub_catalogue(doc)` blanking by POSITION — `/Dests` and the `/Names
/Dests` tree, `/PageLabels`, `/OpenAction`, `/AA`, `/Names /JavaScript`, OCG `/Name`, and
`/StructTreeRoot` `/Alt` `/ActualText` `/T` `/E` — the same discipline `_scrub_extra_parts` applies
to `customXml`. Enumerating "the keys we thought of" is what produced this finding. **And R6-03b
needs its own fix**: either `pdf_objects` leaves `_OPAQUE_SURFACES`, or the attributability rule
gets a carve-out for a match inside a PDF *string literal* `(...)` or hex string `<...>`, which is
a value and not an offset.

### R6-07 · SEVERITY 1 — a page-level `/Metadata` XMP stream is never deleted

`del_xml_metadata()` removes the **catalogue's** `/Metadata`. A `/Metadata` on a *page* (or an
XObject, or an embedded file) is a different object and survives. Contrast control passes: the
document-level XMP carrying the same string IS deleted in the same run.

**Surface**: `raw_bytes` **only** — the `xmp` surface is `get_xml_metadata()`, catalogue-only, and
`pdf_objects` returns dictionary source, not stream bodies.

```
'Maria Kovacova'  counted=('raw_bytes',)   set_aside=()             -> GATE FAIL
'04001'           counted=()               set_aside=('raw_bytes',) -> GATE CLEAN
```

**R6-07b**: the PSČ survives in `<dc:title>PSC 04001</dc:title>` — plain XML text in a packet a
reader displays — and the gate calls the document clean.

**Suggested fix**: sweep every `/Metadata` key in the file, and widen `extract.py`'s `xmp` surface
the same way so the fix is gated on a TEXT surface instead of on `raw_bytes`.

### R6-09 · FALSE REFUSAL — a degenerate rectangle crashes the writer with a bare `ValueError`

`writer/errors.py`'s own docstring is the specification this violates: library messages "written
for a developer" are the problem the module exists to fix.

`page.insert_textbox` raises on an EMPTY rect before it can return anything, and `search_for` can
return one — a tagged span whose `/ActualText` is longer than the glyph run it covers, which is
what PDF/UA tagging writes for a ligature (`ﬁ` → `fi`), an abbreviation, or a hyphen-split word.
MuPDF distributes the replacement characters over the glyph advances and the surplus ones get
zero-width boxes:

```
rawdict: ('r',(130.4,530.4,135.9,545.1)) ('i',(130.4,530.4,130.4,545.1))   <- width 0.000
Failed: writer raised a bare ValueError: text box must be finite and not empty
```

Two controls isolate it: `_collect_page_redactions` really does yield
`Rect(130.355, 530.417, 130.355, 545.091)`, `is_empty=True`, paired with a label and with
`skipped == []`; and a zero-**height** rect draws fine while a zero-**width** rect raises, so the
crash is `_draw_label`'s and reproduces in two lines with no fixture.

Measured consequences: no output and no report on disk (that part is right), but
`gui.model.scan_file` does **not** catch it:

```
B32 scan_file RAISED: ValueError text box must be finite and not empty
```

A Slovak lawyer gets "text box must be finite and not empty" and a document silently skipped.

**Severity**: FALSE REFUSAL — the class the brief ranks as "how the office turns the tool off", on
an entirely ordinary document.

**Suggested fix**: drop empty rects in `_collect_page_redactions` but **RECORD THEM AS SKIPPED**,
so the anti-theatre invariant still fires, and guard `_draw_label` against `rect.is_empty`. **Do
NOT widen the rect to make it drawable** — that redacts glyphs nobody detected.

### R6-10 · WRONG LABEL — the report never mentions an `auto=True` surface that `search_for` could not locate

The module's own words: *"the report is written BEFORE the incomplete-redaction raise,
deliberately. A partial output is precisely the file whose record a reviewer needs."* The record
that gets written has **no row for the surfaces still in the document**: a candidate whose
`search_for` returns nothing hits `continue` before `record_occurrence`, and
`record_low_confidence` is on the other branch.

```
skipped:        ['Maria Kovacova', '855612/7788']
occurrences:    {}
low_confidence: []
```

The report that lands next to the output has an empty `[REDACTED]` table and `(none)` under low
confidence. **That does not read as "partial". It reads as a document in which nothing was found.**

`writer/docx_body.py` has no equivalent path, so this is PDF-only. `gui/model.export_file` deletes
both files on `RedactionIncompleteError`, which mitigates the GUI path — but `redact_pdf` is the
public API, it is what `eval/leak_gate.py` calls, and it writes the report to disk.

**Severity**: WRONG LABEL, at the top of that band — the label is not merely wrong, it is inverted.

**Suggested fix**: a third section in `build_report`, above the other two, with the same "THIS
DOCUMENT MAY BE UNDER-REDACTED" framing `_FAILURE_HEADER` already uses for detector failures.

---

## 3. WHAT DID NOT REPRODUCE

Each is a PASSING test, kept so a regression turns the suite red instead of becoming a round-7
finding.

| attack | result | why it holds |
|---|---|---|
| **INPUT saved incrementally, prior revision holds pre-redaction text** | **CLEAN** | the brief's highest-severity candidate. `save(garbage=4)` rebuilds the xref from the page tree and writes only reachable objects. Control asserts the residue IS in the input bytes first. |
| **OUTPUT written incrementally** | **CLEAN** | the output path can never equal the source, and PyMuPDF refuses anyway. |
| **AcroForm `/V` and `/DV`** | **CLEAN** | `/V` is baked into page content; `/DV` goes when `bake()` drops `/AcroForm`. |
| **Widget with `/NeedAppearances true`, no `/AP`** | **CLEAN** | MuPDF synthesizes the appearance; `bake()` flattens it. |
| **XFA packet in `/AcroForm /XFA`** | **CLEAN, *by accident*** | the PDF analogue of `w:altChunk`. It dies because `bake()` deletes `/AcroForm`. **Nothing in `writer/` knows what XFA is** — if `bake()` ever stops removing `/AcroForm`, or a fix for R6-02 reorders the pipeline, this becomes a leak with no test between it and the office. |
| **FileAttachment ANNOTATION carrying a .docx** | **CLEAN** | `bake()` removes the annotation and the stream is collected. **The `/AF` spelling is R6-04 — the two get opposite answers, which is the whole of the difference.** |
| **Digital signature `/Name` `/Reason` `/Location` `/ContactInfo`** | **CLEAN** | goes with `/AcroForm` in `bake()`. Same accidental mechanism as XFA. |
| **Custom `/Info` keys (`/Klient`, `/SpisovaZnacka`)** | **CLEAN** | `set_metadata({})` rebuilds rather than merges. Worth recording: these are invisible to `doc.metadata`, so only `pdf_objects` would ever have caught a regression. |
| **Text annotation `/T`, `/Subj`, `/Contents`** | **CLEAN** | `bake()` flattens and deletes. |
| **Hidden annotation (`/F` Hidden bit, no appearance)** | **CLEAN** | dropped. |
| **FreeText annotation with no `/AP`** | **CLEAN** | appearance synthesized, reaches `text_layer`, redacted normally. |
| **Unapplied `/Subtype /Redact` annotation in the INPUT** | **CLEAN** | `apply_redactions()` applies EVERY redaction annotation on the page, including one that arrived with the file, so the text under the black box is destroyed. |
| **Line art destroyed by `apply_redactions(graphics=1)`** | **CLEAN** | `graphics=1` removes only what is *contained* in the rectangle; a table border is not. Drawing count went 2 → 5, not down. Not filed — a finding without a reproduction is a hypothesis. |

---

## 4. EXPECTATIONS THAT WERE WRONG

Frozen before the first probe and not edited.

* **`/AF` was expected to be a leak the gate would miss for SHORT needles.** It is worse: the gate
  misses it for **every** needle, because the payload is a compressed ZIP member and no surface
  reads one level in. **A fixture with a plain-text attachment would have recorded R6-04 as an
  ordinary gate-visible leak** and sent the fix in the writer-only direction — exactly the mistake
  round 5 made with `altChunk` and recorded in its own §4.
* **XFA was expected to be a leak. It is clean, for a reason that is not a reason.** Nothing
  scrubs XFA; `bake()` happens to orphan it. The same is true of `/DV` and the signature
  dictionary. **Three of the eleven did-not-reproduce results are accidents of one library call**,
  and filing them as "clean" without saying so would have been the most misleading thing here.
* **`/ActualText` was expected to be a leak on `raw_bytes`.** MuPDF *does* surface it through
  `get_text`, so the writer sees the text — and then crashes drawing a label into a zero-width
  box. The attack found a **refusal** defect where a **leak** was predicted.
* **Custom `/Info` keys were expected to leak.** They do not; `set_metadata({})` rebuilds.
* **The shared Form XObject was not on the pre-registered list at all.** It came out of asking
  "what else does `bake()` construct?" while writing up another attack. It is R6-08, and the only
  finding created by the tool's own save rather than carried in from the input.

---

## 5. WHAT THIS ROUND GOT WRONG ABOUT ITSELF — fixture defects, not product defects

* **The first `/AF` fixture carried `/Desc (Priloha ku spisu Maria Kovacova)`.** That string IS in
  `pdf_objects`, so the first measurement read `GATE FAIL` and R6-04 was nearly filed as an
  ordinary gate-visible leak. The name in the file-spec *description* is a different surface from
  the name inside the *attachment*, and conflating them would have hidden the entire finding. The
  shipped fixture has no `/Desc`. **The same unfalsifiable-assertion mistake round 5 caught in its
  own `_ATTR_NEEDLES`.**
* **The first two-page XObject probe reported residue without checking whether the pages still
  referenced it.** They do not. Had they, the finding would have been much larger (the page
  renders it) and the write-up would have said so. One extra probe; it changes what the fix is.
* **The one-page XObject case was run only after the two-page case was written up.** It is clean,
  which is what makes R6-08 a statement about object reuse rather than "PyMuPDF redaction leaves
  residue". Without that boundary control the finding would have been overstated.
* Three fixtures were rejected during development for being malformed rather than adversarial:
  `Resources` is an indirect object, `Contents` can be an array, and a `Page` handed out by
  `new_page()` goes stale once another page is appended. All three workarounds are in the shipped
  kit so round 7 does not rediscover them.

---

## 6. JUDGEMENT CALLS

* **R6-03 is one finding with five reproductions**, not five findings: one root cause (no
  catalogue policy, only three hard-coded keys) and one fix.
* **R6-03b, R6-04b and R6-07b are sub-findings** — the same defect *graded*. 13 xfails, 10
  findings.
* **R6-05 and R6-06 are filed separately** although one helper closes both: different mechanisms,
  different producers, and merging them would let the first be "fixed" while the CropBox half
  stayed live.
* **R6-09 is a refusal defect, not a crash bug**, because `writer/errors.py` already contains the
  contract it breaks. Same clause as R4-X3 and R5-10, through a third door, and reported as such.
* **No `xfail(strict=False)` anywhere.**

---

## 7. SUSPECTED, NOT CONFIRMED

* **`/Names /JavaScript` and page-level `/AA`** — the `/OpenAction` spelling is measured; the other
  two doors to the same object are not. The R6-03 fix should close all three and its test should
  assert all three.
* **`/Metadata` on an image XObject or an embedded file stream** — R6-07's mechanism at another
  level.
* **`/Collection` (a PDF portfolio)** — very likely R6-04 again.
* **An owner-password-only encrypted input** (the cadastre issues these, and `needs_pass` is False
  for them) — what `save` does with `/Encrypt` was not probed at all.
* **`raw_bytes` cannot see a non-Flate stream.** It tries `zlib.decompress` and nothing else, so an
  `/LZWDecode` or `/RunLengthDecode` metadata stream is invisible to the backstop.
* **The corpus cannot express a single shape attacked in this round.** Measured over all 71 corpus
  PDFs:

  ```
  with /Outlines: 0   with links: 0   with OCGs: 0
  with StructTreeRoot: 0   with /AF: 0   with a shared XObject across pages: 0
  ```

  That test is also this round's **false-refusal measurement**, and it cuts both ways: a guard that
  refuses or rewrites any of these cannot refuse a single corpus document — zero measured
  false-refusal rate — and by the same token the corpus can never demonstrate such a guard is safe.
  `eval/leak_gate.py`'s green verdict on PDFs is currently a statement about what
  `corpus/pdf_builder.py` can draw, not about what a court sends.

---

## 8. THE ROUND'S HEADLINE

**R6-04 (`/AF` associated file)** — and not because it is the biggest leak. R6-01 fires on more
documents; R6-06 fires on a workflow the office already performs by hand.

It is the headline because it is the only finding where **the writer, the extractor, the gate and
the reviewer all fail in the same direction at once.** The name tree is empty, so the writer does
not look. The attachment is a ZIP, so no extractor surface can read a character of it — not
`attachments`, not `raw_bytes`, not `pdf_objects` — and the gate therefore reports `counted=()`
for a fourteen-character name. The page is correctly redacted, so the reviewer sees a clean
document. The report says the document was processed. And a double-click in any reader's
attachment pane opens a Word file with the client's name, rodné číslo, PSČ and bank code in it.

Every other finding is caught by *something*: R6-01, R6-02, R6-05 and R6-06 fail the gate on a text
surface with no discount, and would have been caught long ago if one corpus PDF had a bookmark.
R6-03 and R6-07 fail for long needles and are set aside for short ones — bad, and fixable by moving
one surface out of `_OPAQUE_SURFACES`. R6-08 fails on `raw_bytes`. **R6-04 fails nothing.**

That is the class the brief asks for — *the gate says CLEAN and it is not* — and, exactly as with
round 5's `altChunk`, for a structural reason rather than a threshold that can be nudged. Round 5
predicted this finding in its own §7 and filed it as a suspicion about `oleObject*.bin`. It was
right about the class and wrong about the door.

**The fix must be BOTH HALVES.** If the writer learns about `/AF` and the extractor does not learn
to read one level into a ZIP, the writer is fixed and ungated, and the next way in — a portfolio, a
page-level `/AF`, an attachment relationship nobody has thought of — will be just as invisible.
