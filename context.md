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

**Checksum validation is mandatory.** Without it, every 8-digit number in the document
gets destroyed. With it, precision on these types is effectively 100%.

### 4.2 Gazetteer — closed public lists
Finite, downloadable, shipped with the app. Not ML.

- **Obce** (municipalities) — ŠÚ SR / ÚGKK list
- **Katastrálne územia** — ÚGKK list
- Street-name patterns (`ul.`, `Ulica`, `nám.`, `trieda`, …)

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
4. **Low-confidence candidates** — near-miss patterns (e.g. checksum-failing RČ-shaped
   strings, capitalised unknown tokens in name-like positions) → **review**, unticked

### Why no ML in v1
A SlovakBERT NER model adds ~500 MB to the `.exe`, slow CPU inference, and a dependency
that is hard to debug. Its value is finding names the lawyer *forgot to list* — a real but
secondary gain. Layers 1–3 are smaller, faster, fully explainable, and ship sooner.

**v2:** add NER as a *suggestion layer only*. Its hits go into the review bucket, never
auto-redacted. Decide on it after seeing which entities the office actually misses in
real use.

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
