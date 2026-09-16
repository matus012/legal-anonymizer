# Red-team findings — leak-detection surfaces (v1.1 hardening)

**Target:** `eval/extract.py`, the extractor behind the §8.1 killer leak test.

**Premise under attack:** the leak test greps every ground-truth PII string in every surface of
the redacted output. It is only as good as the extractor — a surface the extractor cannot read
is a surface the gate has never once been asked about, and a leak hiding there greps **clean**.

**Result: 29 findings.** The pre-change extractor was blind to **16 of 34** DOCX surfaces and
**13 of 23** PDF surfaces probed. Every one is now read. Two things it still cannot see, plus a
measurement-driven limit on what a match *means*, are recorded under KNOWN BLIND SPOTS.

Evidence lives in `tests/test_extract_hidden_surfaces.py`. Every finding has a hand-built
fixture (no `corpus/` import, CONTRACTS_v11 §11) hiding a unique marker in exactly that surface,
asserted **twice**: found by the current extractor (GREEN) and **not** found by
`_legacy_docx_surfaces` / `_legacy_pdf_surfaces`, verbatim copies of the pre-change algorithm
kept in that file (RED). Without the second assertion a fixture proves nothing about the gap it
claims to close.

Severity: **HIGH** = PII recoverable from a shipped output by ordinary means · **MEDIUM** =
recoverable with effort · **LOW** = metadata / structural only.

---

## 1. The attribute gap — CONFIRMED REAL, then closed

`_extract_docx` read text through lxml's `itertext()`, which walks **text nodes only**. Every
XML **attribute value** in the package was invisible. Proved before fixing: a `.docx` whose only
occurrence of a name is `<wp:docPr descr="Podpis: …">` returned **no** surface containing it.

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| D-01 | Image alt text — `wp:docPr/@descr` | **HIGH** | `xml_attributes` |
| D-02 | Image title — `wp:docPr/@title` | **HIGH** | `xml_attributes` |
| D-03 | Tracked insertion author — `w:ins/@w:author` | **HIGH** | `xml_attributes` |
| D-04 | Tracked deletion author — `w:del/@w:author` | **HIGH** | `xml_attributes` |
| D-05 | Comment author — `w:comment/@w:author` | **HIGH** | `xml_attributes` |
| D-06 | Comment initials — `@w:initials` | MEDIUM | `xml_attributes` |

A law-office document carries the *reviewing lawyer's* name in D-03/D-04/D-05 on every tracked
change and comment. The writer strips tracked-change *text*; authorship is a different surface
and was never graded.

## 2. DOCX — separate OPC parts nobody opened

**The writer copies unknown parts through byte-for-byte** — verified: redacting
`data/synthetic/kupna_zmluva_000.docx` produced an output whose part list is identical to the
input's, `customXml/item1.xml` included.

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| D-07 | SmartArt / `word/diagrams/*.xml` | **HIGH** | `other_xml_parts` |
| D-08 | Charts / `word/charts/*.xml` (titles, labels, cached values) | **HIGH** | `other_xml_parts` |
| D-09 | Content-control data store — `customXml/item*.xml` | **HIGH** | `other_xml_parts` |
| D-10 | Glossary / building blocks — `word/glossary/document.xml` | MEDIUM | `other_xml_parts` |
| D-11 | Tracked-change author list — `word/people.xml` | MEDIUM | `xml_attributes` |
| D-12 | Document variables — `w:docVar/@w:val` in `word/settings.xml` | MEDIUM | `xml_attributes` |

`customXml/item1.xml` is present in **every** corpus DOCX today (python-docx template).

## 3. DOCX — relationship targets (display text redacted, target not)

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| D-13 | `mailto:` hyperlink target in `word/_rels/document.xml.rels` | **HIGH** | `rels_targets`, `xml_attributes` |
| D-14 | Same in a header/footer rels part | **HIGH** | `rels_targets` |
| D-15 | `attachedTemplate` target — a `C:\Users\<name>\…` profile path | MEDIUM | `rels_targets` |

The fixture asserts both halves at once: `[MENO_1]` in `document_xml` **and** the name in
`rels_targets`. A redactor that rewrites run text and leaves the relationship would have graded
as a clean redaction.

## 4. DOCX — binary parts

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| D-16 | `word/embeddings/*` (OLE storage, UTF-16LE strings) | **HIGH** | `binary_parts` |
| D-17 | Names of binary parts (thumbnail, media) | LOW | `binary_parts` |
| D-18 | Image EXIF/XMP strings | MEDIUM | `binary_parts` |

## 5. DOCX — surfaces claimed covered, now actually proved

Claimed coverage is not coverage. All were reachable; none had a fixture.

| ID | Surface | Verdict |
|----|---------|---------|
| D-19 | `docProps/custom.xml` | **was** covered — but no corpus file ever contained one, so it had never been exercised. Fixture added. |
| D-20 | Headers/footers: first-page, even, default, **and a second section's** | covered — glob is over the whole namelist, not `sectPr` references. Fixture: 4 headers / 3 footers. |
| D-21 | Footnotes, endnotes, comment bodies | covered; fixtures added. |
| D-22 | VML textbox (`v:textbox/w:txbxContent`) | covered; fixture added. |
| D-23 | DrawingML textbox (`wps:txbx/w:txbxContent`) | covered; fixture added. |
| D-24 | Hidden text (`w:vanish`), white-on-white text | covered — **reported, not skipped**. A redactor that only *hides* text has redacted nothing. |
| D-25 | Field codes (`w:instrText`, e.g. `HYPERLINK "mailto:…"`) | covered; fixture added. |

## 6. PDF — surfaces the extractor could not see

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| P-01 | Outline / bookmarks (`doc.get_toc()`) | **HIGH** | `outline` |
| P-02 | Link annotation URI actions (`page.get_links()`) | **HIGH** | `links` |
| P-03 | Annotation **author** (`/T`) and subject (`/Subj`) | **HIGH** | `annotations` |
| P-04 | Form field **names** and labels (`rodne_cislo_novak`) | **HIGH** | `form_fields` |
| P-05 | Attachment filename and description | MEDIUM | `attachments` |
| P-06 | Custom `/Info` keys — `doc.metadata` returns a FIXED key set and drops these | MEDIUM | `pdf_objects` |
| P-07 | Catalogue entries / named destinations | LOW | `pdf_objects` |
| P-08 | Optional-content group (layer) **names** | MEDIUM | `pdf_objects` |

`page.annots()` never yields Link annotations, so P-02 was unreachable by every accessor the
extractor used. P-03 matters most in practice: Acrobat stamps the commenting lawyer's Windows
account name into `/T` on every sticky note.

## 7. PDF — text `get_text()` silently drops (both HIGH)

Two mechanisms hide text from MuPDF's text device while leaving it trivially recoverable in any
viewer. Both extracted as **nothing at all** — leaks the gate scored as clean.

| ID | Surface | Proof | Covered now |
|----|---------|-------|-------------|
| P-09 | Text outside the **CropBox** | drawn at y=760, CropBox set to 700 — `get_text()` returned nothing, and `flags=~TEXT_MEDIABOX_CLIP` did **not** help | `_pdf_unhide()` widens every CropBox to its MediaBox, in memory |
| P-10 | Text in an optional-content group defaulting **OFF** | inserted with `oc=ocg, on=False` | `_pdf_unhide()` drops `/OCProperties` from the catalogue |

Alternatives tried and **failed**, recorded so nobody re-tries them: `set_layer(-1, on=[…])`
does not change `get_text()` output, and `set_layer_ui_config(i, action=0)` only *toggles*, so
it would hide an ON layer as often as it reveals an OFF one.

## 8. PDF — highest-severity vector: incremental-save residue

| ID | Surface | Sev | Covered now |
|----|---------|-----|-------------|
| P-11 | Prior revision's objects after an **incremental** save | **HIGH** | `raw_bytes`, `pdf_objects` |

Measured, not assumed (marker `RTINC01NOVAK`):

| case | save | bytes | marker in raw file? | legacy extractor | current |
|------|------|-------|---------------------|------------------|---------|
| A | original, unredacted | 925 | yes | sees it | sees it |
| B | redacted, `incremental=True` | 1930 | **yes** | **reports CLEAN** | `raw_bytes`, `pdf_objects` |
| C | redacted, `garbage=4, deflate=True` | 934 | no | clean | clean |
| D | B re-saved `garbage=4` | 934 | no | clean | clean |
| E | B re-saved with **no** flags | 1607 | **yes** | **reports CLEAN** | `raw_bytes`, `pdf_objects` |

**The writer's flags are sound, and this is the proof rather than the flag's word for it.**
`writer/pdf_body.py` saves with `garbage=4, deflate=True`; row C shows that genuinely rewrites
the file, row D shows it even launders an input that already carried revision history. Row E is
the control that makes C evidence rather than tautology.

### P-11b — row E was already live inside the harness. HIGH. **FIXED.**

`eval/baselines.py` ended `_redact_pdf` with `doc.save(str(dst))` — no garbage collection.
`greedy_redactor`, the **oracle** baseline the harness scores itself against, leaked **62** PII
strings recoverable from raw bytes on the n=10/seed=23 corpus: 20 MENO, 10 IČO, 10 DIČ, 10 full
IBANs, 10 phone numbers — e.g. `SK74 1100 4983 8673 1604 6759`, `Jozefa Kučeru`. All long, all
attributable.

This is worse than a leaky writer: a leaky *oracle* miscalibrates every gate derived from it.
Fixed to `doc.save(str(dst), garbage=4, deflate=True)`. The baseline-discrimination failure it
caused was a **true positive** — it was not re-pinned around.

## 9. PDF — surfaces proved rather than assumed

| ID | Surface | Verdict |
|----|---------|---------|
| P-12 | Rotated text (90°) | already reached — **proved**, not assumed |
| P-13 | Very small font (0.6 pt) | already reached — proved |
| P-14 | White-on-white text | already reached — proved |
| P-15 | Invisible text (`render_mode=3`, the OCR-under-scan trick) | already reached — proved |
| P-16 | Deflate-compressed stream content | `raw_bytes` inflates every stream; fixture writes a marker existing **only** compressed |
| P-17 | Hex strings inside content streams (`[<4b6f…>] TJ`) | **bug found by this round's own fixture, then fixed**: hex decoding ran on file bytes only, so a marker stored as hex *inside a compressed stream* was missed. Every inflated blob is now hex-decoded. |

---

## Measurement: what a match on a deep surface actually means

The §8.1 premise holds for a long needle on a **text** surface. It fails for a **short** needle
on an **opaque** surface (raw bytes, object source, XML attribute values, binary parts), where a
short string occurs by chance in font tables, glyph hex, width arrays and xref offsets.

Six such matches appeared on the corpus, all `KOD_BANKY` — a Slovak bank code is **four digits**.
Three verified by hand:

* `zmluva_v11_006.docx`, needle `0200`, 3 occurrences in `xml_attributes`, every one inside a
  font PANOSE/signature blob (`…00000010 00000000 00020000 00000000 Courier 02000500000000000000…`).
  `"0200" in by_surface["document_xml"]` is **False** — the body was redacted correctly.
* `zmluva_v11_027.pdf`, needle `5200`, 3 occurrences in `raw_bytes`, all inside hex glyph strings
  (`<00310069004D0052005000510069>`).
* `zmluva_v11_069.pdf`, needle `1100`, inside a CIDFont `/W` width array: `… 1099 750 1100 1102 318 …`
  — this one **is** space-delimited, which is why a delimiter rule alone is not enough.

**Chance-collision probability, measured on 40 redacted corpus outputs.** For each surface and
length L, every distinct L-gram over one alphabet was enumerated exactly, so
`P = |distinct L-grams| / alphabet**L` is the probability a *uniformly random* PII surface of
that length collides in that surface of **one** document. `delim` = restricted to L-grams having
at least one occurrence with a non-hex character on both sides.

| surface | class | L=3 | L=4 | L=5 | L=6 | L=7 | L=8 |
|---------|-------|-----|-----|-----|-----|-----|-----|
| `raw_bytes` | digits | 1.00 | 4.2e-01 | 3.7e-02 | 3.3e-03 | 3.4e-04 | 3.4e-05 |
| `raw_bytes` | digits, delim | 8.7e-01 | 1.8e-01 | 5.3e-03 | 1.3e-04 | **5.8e-06** | 6.1e-07 |
| `pdf_objects` | digits, delim | 7.5e-01 | 1.2e-01 | 3.0e-05 | 1.0e-06 | 1.0e-07 | 0 |
| `xml_attributes` | digits, delim | 1.3e-02 | 1.8e-03 | 1.8e-04 | 1.7e-05 | 2.0e-07 | 1.3e-07 |
| `binary_parts` | digits, delim | 0 | 1.0e-04 | 1.0e-05 | 2.0e-06 | 0 | 0 |
| `raw_bytes` | letters, delim | 1.1e-01 | 1.2e-03 | 1.2e-05 | 1.4e-07 | 2.0e-09 | 3.0e-11 |
| every TEXT surface | digits | ≤4.0e-02 | ≤3.3e-03 | ≤2.7e-04 | ≤1.8e-05 | ≤9.0e-07 | 0 |

### The rule (`eval/leak_gate.py`)

On **opaque** surfaces only — `raw_bytes`, `pdf_objects`, `xml_attributes`, `binary_parts` — a
match counts as a leak only if

> the needle is **≥ 7 characters** **and** has at least one occurrence with a **non-hex
> character on both sides**.

Both halves are required, and the table is why:

* **delimiting alone is not enough** — a delimited 4-digit needle still collides in 18% of PDFs
  (`raw_bytes`, 1.8e-01) → ~25 false reds per corpus run. The `/W` width array is a live instance.
* **length alone is not enough** — an undelimited 7-digit needle collides at 3.4e-04/document
  → ~0.05 false reds per run, and shorter needles are far worse.
* **together at L≥7** → 5.8e-06/document, under 0.001 false reds per corpus run. L=6 delimited
  (1.3e-04, ~5% chance of a false red per run) was rejected: **a gate that goes red by chance
  every twentieth run teaches people to ignore it.**

**No type is excluded, and no text surface is relaxed.** `text_layer`, `document_xml`, headers,
footers, footnotes, endnotes, comments, form fields, annotations, attachments, `core_xml`,
`app_xml`, `custom_xml`, `other_xml_parts`, `rels_targets`, `outline`, `links`, `info_metadata`
and `xmp` stay strict: any match there is a leak, however short the needle. An unknown future
surface defaults to TEXT (strict) — the opaque set is an explicit allow-list.

**Nothing is dropped silently.** Every set-aside match is counted and printed on every run,
zero or not.

---

## KNOWN BLIND SPOTS

### B-1 — Short needles on opaque surfaces (the cost of the rule above)
A needle under 7 characters, or one embedded in a hex run, is graded on **text surfaces only**.

*Asked directly: can a real un-redacted bank code reach the raw bytes and be missed?* **Yes.**
Constructed, not argued —
`test_blind_spot_a_short_needle_hiding_only_in_incremental_residue_is_missed` builds a PDF
containing `Kod banky: 0200`, redacts it, saves **incrementally**, and asserts all three facts:
the extractor **does** see `0200` in `raw_bytes`, the current revision's `text_layer` is clean,
and the rule then sets the match aside. That is a genuine leak this gate reports but does not
fail on. It is tolerable only because a real document also carries such a code on a text
surface, where grading is strict — and it is **not** tolerable for a document whose only copy of
a short identifier is in residue. Mitigation if that is ever unacceptable: type-aware needles
(grade `KOD_BANKY` as part of its enclosing 24-character IBAN), not a lower threshold. The
thresholds are corpus-measured; re-measure if the corpus or the writers change materially.

### B-2 — `docProps/thumbnail.jpeg` is a rendered picture of page 1 and cannot be read
It **is present in every corpus DOCX** and the writer copies it through **byte-identically**
(verified: same SHA-256 in input and output for `kupna_zmluva_000.docx`). In the corpus it is the
python-docx template's blank page — opened and inspected, it carries no PII. But **any** `.docx`
a lawyer saves from Word carries a real rendering of page 1 there, showing the un-redacted names,
and no text extractor can see it. Severity if it occurs: **HIGH**. The extractor reports its
*presence* by name in `binary_parts`; that is all it can do. Fixing this belongs to the writer
(drop or re-render the thumbnail part).

### B-3 — Images generally: signatures, stamps, scans
Out of v1 scope (context.md §3) and un-OCR-able here. A name in a signature image is invisible to
the leak test by construction.

### B-4 — Embedded font glyph outlines
In the `raw_bytes` backstop, streams whose dictionary says `/FontFile`, `/Type1C`,
`/CIDFontType`, `/TrueType` or `/OpenType` are decoded **only** as UTF-16 (what a TrueType `name`
table uses) and are not hex-scanned. Glyph outlines cannot carry document text, and scanning them
under byte-preserving codepages added ~250 KB of noise per file and made the metrics pass ~15×
slower. A name forged into a font's non-`name` table would be missed.

### B-5 — Bytes outside the ZIP central directory (DOCX)
`zipfile.namelist()` reports what the central directory declares; a local-header-only entry
appended by a crafted tool would not be listed. Not a leak-by-bug vector for this writer
(python-docx rewrites the package); the PDF side has its equivalent covered by `raw_bytes`.

### B-6 — Parts larger than 8 MiB
Byte-scanned only up to that cap (`_MAX_BINARY_BYTES`). Their **names** are always reported, so
such a part can never vanish from a report unnoticed.

---

## Cost

Extraction 36 → 86 ms/file; `evaluate()` 160 → 615 ms per PDF. An early version put `raw_bytes`
at 6.4 MB/file and `evaluate()` at 7.6 s/doc; cutting compressed stream bodies out of the
file-level pass, deduplicating printable runs and decoding font bodies only as UTF-16 brought it
to 379 KB with no marker lost (all 57 fixtures still GREEN).

## Handoff — both fixes APPLIED by the orchestrator

1. **`eval/retention.py`** — the six structural sweep surfaces added to `_METADATA_SURFACES`.
   They are near-identical between input and output, so counting them as content diluted
   retention toward 1.0 and blinded the gate that tells redaction from **destruction**: the
   scorch baseline measured 0.2589 where the gate requires ≤0.05. **Applied.**
2. **`eval/baselines.py`** — `doc.save(str(dst), garbage=4, deflate=True)`. See P-11b.
   **Applied.**
