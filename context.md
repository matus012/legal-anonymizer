# context.md — Slovak Legal Document Anonymizer

## 1. Purpose

Desktop application for a 6-person Slovak law office. Removes personal and identifying
data from legal documents **entirely on-device**. No cloud, no network calls, no telemetry.

The office currently has no tool. Their alternative is uploading client documents to web
services, which is a confidentiality problem. That is the entire reason this exists.

**Non-goal:** competing with commercial products (e.g. ADMIS Anonymizer). This is a
purpose-built internal tool for one office.

## 2. Users

Six lawyers. Non-technical. Windows laptops.

Design consequences:
- No Python install, no terminal, no config files.
- Single `.exe`, desktop icon, double-click to run.
- If a step needs explaining, the step is wrong.

## 3. Scope

### In scope (v1)
- Input: `.docx` and `.pdf` **with a text layer** (digital-born).
- Irreversible redaction. Text is destroyed in the output, not covered.
- Consistent in-document labels: `[MENO_1]`, `[MENO_2]`, `[RC_1]`, … so the document
  stays readable and parties remain distinguishable.
- **No mapping file is written.** Output cannot be reversed.
- Originals are never modified. Outputs are new files.
- Batch: multiple files selected at once.
- Human review step before export.
- Report file per document listing every redaction.

### Out of scope (v1) — state explicitly to the office
- **OCR / scanned documents.** If a PDF has no text layer, the app refuses it with a
  clear message. It does not silently produce an unredacted file.
- **Signature and stamp (podpis / pečiatka) removal.** These are images. The office asked
  for this; it is deferred to v2. They must be told.
- ML-based NER. Deferred to v2 (see §6).
- Formats other than `.docx` / `.pdf` (no `.rtf`, `.odt`, `.txt`).
- Any network functionality whatsoever.

### Hard constraints
- Fully offline. The app must function with the network adapter disabled.
- Developer never receives, stores, or processes real client documents. All development
  and testing uses a synthetic corpus (§7).

## 4. Data to redact

Source: the office's own list, plus additions.

### 4.1 Deterministic — regex + checksum validation
High precision. Auto-redacted without review.

| Type | Notes |
|---|---|
| Rodné číslo | Format + **mod-11 checksum**. Reject invalid. |
| Dátum narodenia | Multiple SK formats (`1.1.1980`, `01. 01. 1980`, `1980-01-01`) |
| IČO | 8 digits + **weighted checksum** |
| DIČ | 10 digits |
| IČ DPH | `SK` + DIČ |
| IBAN / bankový účet | **mod-97 checksum**; also legacy `123456-1234567890/1100` |
| E-mail | |
| Webová stránka / URL | |
| Číslo LV | `LV č. 1234` |
| Číslo parcely | incl. `parc. č. 123/4`, KN-C / KN-E |
| Číslo vložky ORSR | `Oddiel: Sro, Vložka č. 12345/V` |
| Spisová značka | Court/admin refs; `V-1234/2025`, `Z-567/2025`, `P-89/2025` |
| Suma | Amounts with `€` / `EUR` / `Sk` |
| Telefónne číslo | Not on their list — **add it**, it is obviously PII |

| **v1.1 additions** | below |
| PSČ, adresa, súpisné/orientačné č., č. bytu, vchod, poschodie, ulica, štátna príslušnosť | address / identity block; ADRESA swallows a trailing PSČ + obec |
| Číslo OP / cestovného pasu / vodičského preukazu | 2 letters + 6 / 7 digits; VP is anchor-required |
| EČV, VIN | VIN excludes I/O/Q per ISO 3779 |
| BIC/SWIFT | anchor-required, or country code literally `SK` |
| Názov účtu, číslo klienta, kód banky, fax, názov banky, org, ulica | Vyhláška 482/2011 clause (f), (e), (c), (j) |

v1.1 added, beyond what this table lists explicitly: `PSC`, `ADRESA`, `SUPISNE_CISLO`,
`CISLO_BYTU`, `VCHOD`, `POSCHODIE`, `CISLO_OP`, `CISLO_PASU`, `VODICSKY_PREUKAZ`, `ECV`, `VIN`,
`BIC`, `NAZOV_UCTU`, `CISLO_KLIENTA`, `KOD_BANKY`, `FAX`, `ORG`, `NAZOV_BANKY`, `ULICA`,
`STATNA_PRISLUSNOST`.

**The authoritative type list is Vyhláška MS SR 482/2011 + Inštrukcia 24/2011** (v1.1), not
the office's own list. The clause-by-clause mapping lives in CONTRACTS_v11.md §12 — it is not
duplicated here. Clause (i) — utajované informácie / obchodné tajomstvo — is **declared out of
scope in writing, and permanently**: it is defined by MEANING, not by any surface pattern, so
no regex, checksum, or gazetteer can decide that a sentence discloses a trade secret. A tool
that silently skipped clause (i) while claiming to implement "the vyhláška list" would
misrepresent its own coverage — which is precisely the liability posture §9 forbids.

**Checksum validation is mandatory** — but in v1.1 it is a **TAG, not a FILTER**. v1 routed a
shape-valid, checksum-INVALID identifier to the review bucket. v1.1 auto-redacts it and
records `checksum="invalid"` in the report and the review column. A mistyped IČO is still an
IČO, and leaving it un-redacted because one digit is wrong is the exact failure this tool
exists to prevent. `strict_checksums=True` restores the v1 behaviour for an office that would
rather re-tick a few mistyped numbers. The checksum still earns its keep: it is what stops
every 8-digit number in the document from being *reported* as a validated IČO.

### 4.2 Gazetteer — closed public lists
Finite, downloadable, shipped with the app. Not ML.

- **Obce** (municipalities) — Register adries, MV SR (CC0) — 2 842 entries, SHIPPED in v1.1
- **Katastrálne územia** — ÚGKK SR codelist CL000026 (CC BY 4.0) — 3 416 entries, SHIPPED
- **Ulice** — Register adries (CC0) — 12 000 entries, SHIPPED. Matched ONLY when followed by
  a number or preceded by `ul.` / `ulica` / `nám.` / `trieda` / `cesta`: a bare street name
  collides with too many ordinary Slovak words.
- Given names (481) and surnames (1 169) — MIT / CC0. A surname alone is REVIEW, not auto.

Entries that are also ordinary Slovak words (`Hora`, `Lipa`, `Most`, `Strana`) are held in a
stoplist and demoted to the review bucket unless an address keyword or a PSČ independently
confirms them. Provenance and licence of every list: **LICENSES.md**. Name lists derived from
the Facebook data breach were rejected outright.

Matched with declension tolerance (§5).

### 4.3 Known entities — user-supplied
The lawyer types or pastes the names/addresses of the parties before scanning.

This is the single highest-value input in the whole system. The lawyer **already knows
who the client and the opponent are.** Asking them costs one text box and delivers near
100% recall on the hardest category. Optional, but strongly nudged in the UI.

## 5. The Slovak declension problem

**The most important correctness detail in this project.**

Slovak inflects proper nouns:

```
Novák → Nováka, Novákovi, Novákom, Novákovcov, Nováková, Novákovej
Košice → Košiciach, Košíc, Košiciam
```

A literal string match on `Novák` will miss the majority of its occurrences in a real
legal document. A tool that does this **looks like it works while leaking names.**

Approach:
- Stem the entity (strip known Slovak suffixes).
- Match `stem + any plausible suffix`, case-insensitive, diacritic-aware.
- Accept over-matching. A false positive costs the reviewer two seconds. A false negative
  is a data breach.

This applies to §4.2 (gazetteer) and §4.3 (known entities). It does not apply to §4.1
(numeric identifiers do not inflect).

## 6. Detection engine

Three layers, in order. No ML in v1.

1. **Deterministic** (§4.1) — regex + checksum → **auto**, pre-ticked
2. **Gazetteer** (§4.2) — declension-tolerant lookup → **auto**, pre-ticked
3. **Known entities** (§4.3) — declension-tolerant lookup → **auto**, pre-ticked
4. **Low-confidence candidates** → **review**, unticked. In v1.1 this bucket is the
   BARE-NAME heuristic (2-3 capitalised tokens mid-sentence, not stoplisted, with no title,
   role or field-label anchor confirming them) plus a surname-only gazetteer hit. It is NO
   LONGER the checksum-failing identifiers — those are auto-redacted and tagged (§4.1).

### Why no ML in v1
A SlovakBERT NER model adds ~500 MB to the `.exe`, slow CPU inference, and a dependency
that is hard to debug. Its value is finding names the lawyer *forgot to list* — a real but
secondary gain. Layers 1–3 are smaller, faster, fully explainable, and ship sooner.

**v2:** add NER as a *suggestion layer only*. Its hits go into the review bucket, never
auto-redacted. Decide on it after seeing which entities the office actually misses in
real use.

### v1.1 normalization layer (`detect/normalize.py`)
`detect()` no longer runs its detector battery directly over the document text. It runs over a
**normalized view** built by `detect/normalize.py`, and maps every candidate's span back onto
the ORIGINAL text through an index map before returning it. Both writers are unchanged: they
still cut the document at the original offsets `detect()` returns.

What is folded, and why: Unicode format characters (category Cf — zero-width spaces, the soft
hyphen, bidi marks) are deleted outright; Cyrillic and Greek homoglyphs fold to their Latin
lookalike, one-for-one; every run of whitespace collapses to a single character; every
character passes through per-character NFKC (fullwidth digits, ligatures); NFD combining marks
recompose onto the preceding base so "č" arrives as one codepoint regardless of which form the
source file used.

Two things are deliberately **not** folded. **Case** is left alone because several detectors —
the ORG legal-form detector, the bare-name heuristic — use capitalisation as their only
evidence; folding it would not make them case-insensitive, it would turn every
capitalized-token rule into a match-everything rule. **Diacritics** are left alone because
folding "č" to "c" here would silently widen every Slovak-word pattern in `detect/` at once;
diacritic tolerance is handled per anchor site instead; where the difference between "an anchor
word" and "the evidence" is actually visible.

The **line boundary** survives normalization on purpose: a whitespace run that contains a line
break collapses to `\n`, and every other run collapses to a space, instead of everything
collapsing to a space. This was tried the other way first and broke two detectors in opposite
directions: with wraps turned into spaces, the bare-name heuristic began pairing the last word
of one line with the first word of the next (it emitted an auto-redact name spanning a party's
surname and the label that started the following line), and the field-label pattern's
value-terminator regex uses `[\n\r\t]` to know where a label's value ends — with no line breaks
left in the text, a label value ran on to the end of the page.

`detect()` runs the battery over **two** normalized views and merges their candidates. The
second view additionally deletes a line break that falls between two runs of CAPITALS AND
DIGITS ONLY, reassembling an identifier a renderer broke across a line (a wrapped PDF text
layer cutting an IBAN or a BIC mid-token). The restriction to capitals-and-digits is
load-bearing: an earlier version joined any alphanumeric pair across a break, and since a
wrapped line always ends one word and begins another, it welded ordinary words together.

None of this could be done the way the v1.1 NBSP fix was done — a one-line `str.replace`. That
fix is safe only because it is one character for one character: every offset stays valid, and
both writers slice the document at those offsets. Deleting a character (a zero-width space, a
format character) shifts every later offset; applying the same one-line trick to those
characters would not mislabel the document, it would corrupt it — cut the wrong bytes out of
the file. That is why an offset MAP, not a substitution, was needed.

Measured effect on mutation-gate robustness (blind arm, threshold 0.95, before → after this
layer landed): `zero_width` 0.070→1.000, `soft_hyphen` 0.070→1.000, `cyrillic_homoglyph`
0.356→1.000, `nfd` 0.675→1.000, `tabs` 0.887→1.000, `double_spaces` 0.813→1.000,
`line_break_mid` 0.119→0.376 (still failing — see redteam/FINDINGS_ROUND2.md R2-1; the
remaining gap is the anchor→value separator, not normalization).

### Detector isolation (CONTRACTS_v11.md Amendment 11)
Every detector module in `detect/core.py`'s battery runs inside its own guard, and its output
is validated at its own source (span inside the text, a registered type, a valid checksum tag).
A detector that raises, or returns something malformed, loses only its own candidates for that
unit; the failure is recorded as a `DetectorFailure` and carried through to the report and the
GUI review screen instead of being swallowed. `detect()`'s five post-conditions — the assertions
that the resolved candidate set is sorted, non-overlapping, and fully typed — are deliberately
**not** guarded the same way. They run after resolution has already combined every detector's
output into the single span set both writers cut the document at; continuing past a violated
post-condition would write a corrupted file, so stopping there is the one safe outcome. Guarding
each detector separately exists so a malformed candidate never reaches that assertion in the
first place — a failure there is attributed to the detector that caused it, not surfaced as an
assertion with no visible origin.

### Recall over precision
This is the governing principle. Every ambiguous design decision resolves toward
over-detection.

## 7. Synthetic test corpus

**Real client documents are never used for development or testing.** Not on the developer's
machine, not in the repo, not ever. This is non-negotiable and is also what keeps the
project free of confidentiality exposure.

Build a generator that produces realistic Slovak legal documents with **fake but plausible
PII**, and records **ground truth**: every PII string, its type, its exact location.

Document types to generate:
- Kúpna zmluva (nehnuteľnosť)
- Návrh na vklad do katastra
- Žaloba
- Výpis z listu vlastníctva
- Splnomocnenie
- Výpis z ORSR

Target: 50–100 documents, `.docx` and `.pdf`.

### Deliberately seeded failure modes
The corpus must contain, on purpose:

- Names in **every declension case**
- Names **split across DOCX runs** (spellcheck / formatting artifacts) — regex on
  `run.text` finds nothing; this is a classic silent failure
- PII in **headers, footers, footnotes, endnotes, tables, textboxes**
- PII in **tracked changes** (`w:ins` / `w:del` — deleted text is still in the file)
- PII in **document metadata** (`docProps/core.xml`, PDF XMP) — the author field is often
  the lawyer's name
- **Checksum-invalid** RČ / IČO / IBAN that look correct (must NOT be auto-redacted)
- The same person written **inconsistently**: `Ján Novák`, `J. Novák`, `Novák`, `p. Novák`
- Amounts and dates in mixed formats

Ground truth is stored alongside each document as JSON.

## 8. Evaluation harness

Runs as `pytest`. The agentic coding loop iterates against this. **Without a machine-readable
definition of "correct", an agent will declare success on code that leaks.**

### 8.1 Leak test — the killer test
The only test that truly matters. Trivial to implement, catches the worst bug class.

```
for each generated document:
    redact it
    extract ALL text from the output:
        - PDF text layer (including under any drawn boxes)
        - PDF metadata, XMP, annotations, form fields, attachments
        - DOCX document.xml, headers, footers, footnotes, comments
        - DOCX core.xml / app.xml metadata
    grep for every ground-truth PII string
    ANY hit → HARD FAIL
```

This instantly catches the single most common redaction bug: **drawing a black rectangle
over text leaves the text extractable underneath.** That is not redaction, it is theatre.

### 8.2 Metrics
- **Per-entity-type recall** — the headline number. Report each type separately so a weak
  detector is visible instead of hidden in an average.
- Precision — tracked, but a secondary concern.
- Formatting integrity — output opens without corruption; layout preserved.

### 8.3 Acceptance gates
- Leak test: **zero** leaks. Non-negotiable.
- Deterministic types (§4.1): 100% recall on the corpus.
- Gazetteer + known entities: ≥98% recall including all declension cases.
- Every output file opens cleanly in Word / Acrobat.

## 9. Application flow

1. **Launch** — double-click desktop icon.
2. **Input** — drag and drop, or file picker. Multiple files.
3. **Known entities** (optional) — one text box: "Names, addresses of the parties." Skippable,
   but prominently nudged.
4. **Scan** — engine runs, results split into two buckets.
5. **Review screen** — single list:
   - Columns: `TYPE | text | context snippet | location | count`
   - **Grouped by entity, not by occurrence.** `Novák` found 47× is **one row**, not 47.
     Per-occurrence review is a fatigue trap: the reviewer starts blind-approving and the
     review becomes worse than useless.
   - Auto bucket: pre-ticked.
   - Review bucket: unticked, requires a decision.
   - Free-text field: "redact this too" for anything missed.
6. **Export** — writes `<name>_anon.docx` / `<name>_anon.pdf` and `<name>_report.txt`.
7. **Final screen** — states plainly: *review the output before sending it anywhere.*

### The report file
Per document:
- Every redaction: type, label assigned, occurrence count, locations.
- A **"low confidence / NOT redacted"** section — anything the engine nearly flagged. This
  is what makes human review effective rather than decorative.

### Liability posture
The tool **never claims a document is clean.** It produces a *report of what it changed and
what it was unsure about.* The human review step is structural, not a disclaimer nobody
reads. This is the entire reason the developer is not the obvious blame target when
something is missed.

## 10. Technical implementation notes

### DOCX
- `python-docx` is insufficient alone — **text splits across `<w:r>` runs**. Must:
  1. Reconstruct paragraph-level text
  2. Match spans on the reconstructed text
  3. Map spans back onto the underlying runs
  Skipping this produces a tool that appears to work and randomly misses hits.
- Must process: body, tables, headers, footers, footnotes, endnotes, comments, textboxes.
- **Strip tracked changes** (`w:ins`, `w:del`) — deleted text persists in the XML.
- **Scrub `docProps/core.xml`** (author, last modified by, company).
- **Delete `docProps/thumbnail.jpeg`** (v1.1). It is a RENDERED PICTURE of page 1. python-docx
  ships one in its default template and unknown parts are copied through byte-for-byte, so
  every output carried an image of the un-redacted first page. It is pixels, so no text
  extractor can see it and no leak test could ever have caught it — it has to be deleted, not
  graded.

### Leak vectors the v1.1 red team found (redteam/FINDINGS.md)
The killer leak test is only as good as the extractor behind it: a surface the extractor
cannot read is a surface the gate has never been asked about, and a leak hiding there greps
clean. The pre-v1.1 extractor was blind to **16 of 34 DOCX surfaces and 13 of 23 PDF surfaces**
probed. The ones worth remembering:

- **XML ATTRIBUTE values** were invisible everywhere — `lxml`'s `itertext()` walks text nodes
  only. That hid image alt text (`wp:docPr/@descr`), and the `w:author` / `w:initials` on every
  tracked change and comment, which in a law office is the reviewing lawyer's own name.
- **Separate OPC parts nobody opened**: SmartArt, charts, `customXml/item*.xml` (present in
  every file python-docx writes), glossary, `word/people.xml`, `word/embeddings/*`.
- **Relationship targets**: a `mailto:` hyperlink target leaks a name and an address even when
  the display text has been redacted.
- **PDF incremental saves** keep the PRIOR revision's objects in the file. `writer/pdf_body.py`
  saves with `garbage=4, deflate=True`, which genuinely rewrites — this was PROVEN rather than
  trusted, against a control saved without the flags. `eval/baselines.py` did NOT have the
  flags, so the harness's own oracle was leaking 62 real PII strings while reporting clean.
- **PDF text `get_text()` silently drops**: text outside the CropBox, and text in an
  optional-content layer whose default state is OFF. Both are trivially visible in any viewer.
- **PDF bookmarks, link URIs, annotation authors, and form field NAMES** (a field named
  `rodne_cislo_novak` leaks even when empty).

**Anchor fragility is its own leak class.** Anchor-required types are matched by a Slovak
phrase, and any whitespace variation inside that phrase breaks it. An NBSP between the words,
and a line break between them, each caused a real leak in a PDF while the DOCX of the same
document was clean. `detect()` now normalizes NBSP (1:1, so offsets survive) and anchor phrases
separate their words with `\s+`. **Missing diacritics remain an open gap** — see QUESTIONS.md Q7.

### Leak vectors closed since this section was first written

- **`docProps/thumbnail.jpeg`.** python-docx ships a rendered picture of page 1 inside its own
  default template, and the writer copies unknown OPC parts through byte-for-byte, so every
  output carried an image of the un-redacted first page. It is PIXELS — no text extractor can
  read it, so no leak-test gate could ever have caught it, no matter how thorough the extractor
  became. It is now deleted by the writer rather than graded by anything. See KNOWN BLIND SPOT
  B-2 in `redteam/FINDINGS.md`.
- **The eval oracle itself was leaking.** `eval/baselines.py` saved its PDFs with no garbage
  collection (`doc.save(str(dst))`), so `greedy_redactor` — the baseline every gate is
  calibrated against — leaked 62 real PII strings through incremental-save revision residue
  while reporting itself clean. A leaky oracle miscalibrates every gate derived from it; this
  is worse than a leaky writer. Fixed to `doc.save(str(dst), garbage=4, deflate=True)`.
- **Invisible characters (Unicode category Cf) and NFD inside identifiers.** A zero-width space
  a bank portal injects into a long account number, or an NFD-composed diacritic from a
  Mac-authored `.docx`, defeated every detector that spelled the identifier's shape literally.
  Closed by the normalization layer above, not by a per-detector patch.
- **A wrapped PDF text layer breaking a multi-word anchor.** A line break landing between the
  words of an anchor phrase (e.g. inside "Číslo klienta") leaked a client number from a corpus
  PDF. (The original note added "while the DOCX of the same document stayed clean". That half
  was **not evidence and has been removed**: `corpus/generate.py` gives each FORMAT its own
  seed, so the `.docx` and `.pdf` at the same index are DIFFERENT DOCUMENTS — verified, 46 vs
  40 ground-truth surfaces with 3 in common. The leak was real and independently reproduced;
  the comparison was not. See QUESTIONS.md Q14.)
- **Every separator inside a value, and inside an anchor phrase.** The wrap fix above was
  applied first to the gap between an anchor and its VALUE, and the gaps *between the anchor's
  own words* stayed narrow — so a wrap one word later leaked the same number again. Then the
  same thing a third time, one level deeper: several anchors were built by passing the whole
  phrase through `diacritic_pattern()`, whose `re.escape` turns the internal space into a
  literal `\ ` that no separator widening can reach. Three rounds of the same bug in three
  places is the argument for measuring a mutation class rather than reasoning about a fix.
- **A `<w:r>` holding more than one text-bearing child.** `_rebuild_run` rewrote the FIRST
  `<w:t>` and deep-copied the rest into every fragment with their original text, so PII was
  **duplicated** beside the label claiming to have removed it. Word emits multi-child runs on
  every save (`<w:lastRenderedPageBreak/>`); python-docx never does, so no corpus document
  could contain the shape and no gate could see it.
- **Four DOCX locations that were never visited at all**: a run inside `<w:hyperlink>` (Word
  auto-hyperlinks every address you type), a paragraph in a nested table, a paragraph inside
  `<w:sdt>` (every Word template with fill-in fields), and a table inside a textbox. All four
  are direct-child views in python-docx, and all four are shapes python-docx cannot emit —
  measured, 0 of 70 corpus documents contain one.
- **A hyperlink's DESTINATION.** Word keeps it in a `.rels` part, so redacting the display text
  left `mailto:jan.novak@advokat.sk` in the package of a document that read `[EMAIL_1]`.
- **A PDF whose text cannot be decoded, and one whose text is shredded into single
  characters.** Both were accepted and silently produced an unredacted output that the leak gate
  scored **CLEAN** — because `eval/extract.py` reads the same mangled string the detector does,
  so the ground-truth needle is absent from every surface. This is the one failure mode the
  §8.1 gate is structurally unable to catch, and the answer is a REFUSAL (§3), not a better
  grep. Both refusals were tuned against the corpus for zero false refusals.
- **A genuinely Cyrillic name, broken by the tool's own homoglyph folding.** Folding
  confusables per character turned "Ковальчук" into mixed-script wreckage, so the Ukrainian
  client's name the lawyer typed into the known-entities box could not match the document text.
  The module's own docstring claimed this did not happen. Confusables now fold only inside a
  token that already contains a Latin letter.
- **The source filename.** `Novak_kupna_zmluva.docx` leaks a client's name in the attachment
  name no matter how clean its contents are — an email client and every mail server log the
  filename regardless of what the document body says. The GUI now warns when the filename
  itself contains a detected surface.
- **Bundled gazetteer data missing from the frozen build.** `detect/gazetteer_data/*.json` are
  plain data files; PyInstaller's import analysis cannot see them and bundles them only because
  `anonymizer.spec` names them explicitly. If that line is ever dropped or the path changes,
  the frozen app still starts, still scans, still writes a redacted document and a report — and
  silently stops matching every municipality, street, cadastral area, given name and surname in
  the country. No crash, no empty output, just a report that looks ordinary and shorter. Closed
  by `detect/selfcheck.py`, which checks file presence and a floor entry count at startup and
  refuses to scan rather than scan badly.

### PDF
- **PyMuPDF** (`fitz`). Use `add_redact_annot()` + `apply_redactions()`. This genuinely
  destroys glyphs. Anything else leaves extractable text.
- Replacement label is drawn over the redacted area.
- Text cannot reflow — output shows a box with `[MENO_1]`. The office must expect this.
  DOCX reflows properly; PDF does not.
- Scrub metadata, XMP, annotations, form fields, embedded attachments.
- **Reject PDFs with no text layer** with a clear error. Never silently pass them through.

### GUI
- Simple, native-feeling Windows desktop app.
- No terminal, no console window in the built `.exe`.

### Packaging
- PyInstaller → single `.exe` (or a small installer).
- Gazetteers bundled.
- **Must be tested on a clean Windows machine** with no Python installed. "Works on my
  machine" is the default failure mode here.

## 11. Build order

Strictly sequential. Do not skip ahead.

1. **Synthetic corpus generator + ground truth** — everything else is measured against this
2. **Eval harness** — leak test + per-type recall
3. **Detectors** (deterministic → gazetteer → known entities) → iterate until green
4. **DOCX writer** → leak test green
5. **PDF writer** → leak test green
6. **GUI**
7. **PyInstaller build + clean-machine install test**
8. **Field acceptance** — office runs ~10 real documents on *their* machine, reviews the reports

Steps 1–2 are the foundation. An agent given a working eval harness can iterate steps 3–7
effectively. An agent without one cannot.

## 12. Open items

- Confirm to the office: **signatures/stamps not in v1**, **scans not supported in v1**.
- Confirm document volume (docs/week) — informs whether batch performance matters.
- Confirm: does the office already own Acrobat Pro? If so, be honest that its redaction +
  pattern search covers part of this for free.
- Source and license-check the obce / katastrálne územia lists.

## 13. Project value (developer)

Portfolio piece and a plausible bachelor thesis theme: *local-first PII anonymization for
Slovak legal documents* — a genuinely under-served language/domain combination.

**No payment for v1.** Ship it as-is, no warranty, in writing.
