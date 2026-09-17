# Red-team findings, round 4 — THE NEW CODE, AND THE NEW REFUSALS

**Target: the seven fixes that landed in the three hours before this round started, plus the
DOCX package parts no round has attacked.**

Rounds 1–3 attacked, in order, the EXTRACTOR (which surfaces the gate can read), the DETECTORS
(whether an oddly spelled surface is found) and the CONTAINER (which shapes the corpus cannot
hold). Round 3's findings were fixed tonight. A fix is the least-tested code in a repo by
construction: it was written against the one fixture that proved the bug, and that fixture was
written by somebody who already knew the answer.

Round 4 attacks four things:

1. **The rewritten DOCX traversal.** One `.//w:p` walk per part replaced four direct-child
   walks. A descendant walk reaches shapes the old one could not — including shapes that
   contain *the same paragraph twice*.
2. **The two new PDF refusals, as a FALSE-REFUSAL surface.** `ShreddedTextLayerError` and
   `UnreadableTextLayerError` are the first code in this project that can decline to do the
   work. A wrongly refused ordinary document is a defect class: a tool that refuses real work
   gets switched off, and then nothing is redacted at all.
3. **Whether the round-3 fixes are COMPLETE.** A page-level threshold admits every attack that
   stays under it. `page_is_shredded`'s own comment names the bypass out loud.
4. **The DOCX package parts outside `word/document.xml`** — `settings.xml`, `customXml/*`,
   `docProps/custom.xml`, `people.xml`, and the revision-authorship elements
   `_strip_tracked_changes` does not know about. `eval/extract.py` READS all of them (round 1
   added `other_xml_parts` / `xml_attributes` / `custom_xml`). Nothing in `writer/` WRITES
   them. That asymmetry has never been exercised, because the corpus generator emits none of
   these shapes.

---

## 0. EXPECTATIONS, WRITTEN BEFORE ANY ATTACK WAS RUN

This table was written and saved before the first probe executed, and nothing in the
"expectation stated in advance" column has been edited since. RESULT sections were appended
below it.

### Group T — the rewritten `writer/docx_body.py` traversal

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| T1 | `<mc:AlternateContent>` holding a textbox TWICE — `<mc:Choice>` with the DrawingML copy and `<mc:Fallback>` with the VML copy, each with its own `<w:txbxContent><w:p>` carrying the same text | What Word emits for **every** textbox, shape and WordArt drawn since Word 2007. Not an edge case; the normal serialisation of a signature-block textbox. | DEFECT, but a REPORT defect, not a leak. `.//w:p` finds both copies so both get redacted (the old direct-child walk found neither). They are two distinct elements with the same text, so `detect()` runs twice and `record_occurrence` fires twice — the report claims **2 occurrences of a name that appears once on the page**. |
| T2 | a two-section document whose second section's header is LINKED to the first | Every Slovak filing with a landscape annex or continued page numbering has ≥2 sections, and Word links the header by default. | DEFECT, same class as T1 by a different mechanism: `roots` appends `section.header._element` once per section and python-docx resolves a linked header to the SAME element. Expect double-counted occurrences, no corruption. |
| T3 | `<w:sdt>` wrapping a whole `<w:tbl>` | Every Word template with a repeating-section or table-shaped content control. | **CLEAN expected.** Stated as clean so it can be falsified: if this fails, the traversal rewrite is broken at its core. |
| T4 | `<w:fldSimple w:instr=' HYPERLINK "mailto:jan.novak@advokat.sk" '>` with display text | RTF→DOCX conversion, Word 97-era documents and several DMS exports write hyperlinks as FIELDS rather than `<w:hyperlink r:id>`. | DEFECT, PII SURVIVES. `_paragraph_runs` now reaches the display run, but the destination is in the `w:instr` **attribute**, which no pass reads and `_scrub_rel_targets` never sees because there is no relationship. |
| T5 | the `fldChar`/`instrText` form: `<w:instrText> HYPERLINK "mailto:…" </w:instrText>` | Same source; the more common of the two field spellings. | DEFECT, PII SURVIVES, WORSE than T4: `w:instrText` is not in `_TEXT_BEARING` and `Run.text` does not render it, so it is not in the text `detect()` sees and it lands in `document_xml`, a STRICT text surface. |
| T6 | `<w:smartTag>` wrapping a name | Word 2003-era smart tags, still in long-lived templates. Round 3 suspected the fix covers it and could not confirm. | **CLEAN expected** — `.//w:r` reaches it. Run as the confirmation round 3 could not do. |
| T7 | a run inside `<w:hyperlink>` whose text is ENTIRELY covered by one redaction, so `fragments` is empty and `_rebuild_run` removes the run | `Predávajúci: <hyperlink>jan.novak@advokat.sk</hyperlink>` — Word auto-hyperlinks the address as you type and the whole run is the PII. | Uncertain, and the one I most expect to corrupt. Expect either (a) the `[EMAIL_1]` label is lost entirely, so the reviewer cannot see what was removed, or (b) an empty `<w:hyperlink/>` Word reports as needing repair. |
| T8 | a `<w:sdt>` with `<w:dataBinding w:xpath=…>` whose value is CACHED in `customXml/item1.xml` | Every Word form built on the Developer tab with an XML part; every document from a document-assembly system (HotDocs, Contract Express, a DMS macro). | DEFECT, and the nastiest shape in the round if it holds: the on-page run IS redacted so the output looks clean, and Word **re-populates the content control from the custom XML part on open**, so the name comes BACK on screen in the redacted document. |

### Group P — FALSE REFUSALS (a defect class that did not exist before tonight)

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| P0 | all 71 corpus PDFs through `page_is_shredded` and `page_has_unreadable_text` | the tool's own daily input | CLEAN — the module claims "0 of 71 PDFs trip it". Re-measured as a CONTROL: if a corpus PDF trips it, every number in this group is unattributable. |
| P1 | a **letter-spaced Slovak title page** — `N O T Á R S K A   Z Á P I S N I C A` over a short subtitle, on its own page | *Razvetrené / prestrkávané písmo* is the Slovak convention for the heading of a notarial deed, a court decision and a land-registry decision. `page_is_shredded`'s own docstring names this practice as the thing it must not break. | **FALSE REFUSAL.** `_SHRED_MIN_TOKENS = 20` is not "a substantial amount of text"; a title page reaches 20 tokens with a spaced heading plus one line of prose and the ratio is then far over 0.50. The whole document is refused. This falsifies the module's own stated design intent, in its own comment. |
| P2 | a page that is mostly a **numbered annex table / table of figures** with single-digit cells | `Zoznam príloh`, a court-fee schedule, a payment schedule in a loan agreement. | Uncertain — depends whether digits outnumber words 2:1 after `str.split()`. Stated as uncertain rather than guessed. |
| P3 | an ordinary **bulleted list** whose bullets are Symbol/Wingdings glyphs extracting as U+F0B7 (category `Co`, private use) | Word's default bullet IS the Symbol-font character. Every PDF exported from a Word document with a bulleted list carries one per bullet. | **FALSE REFUSAL.** `_UNDECODABLE_MAX = 3` is an ABSOLUTE count and `Co` is in `_UNDECODABLE_CATEGORIES`. Three bullets on one page refuse the document. The comment defends the absolute count as "it does not fire on ordinary documents" — expect that to be wrong for the most common list in office documents. |
| P4 | a page carrying a **Greek** passage and a page carrying **CJK** | a cross-border contract with a Chinese counterparty; a technical annex. | Uncertain. |

### Group I — are the round-3 fixes COMPLETE?

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| I1 | letter-space **only the party-name line**, leaving the rest of the page ordinary prose | Exactly what the Slovak convention does: it spaces the HEADING and the PARTY DESIGNATION, not the body. `page_is_shredded`'s own comment says so and then builds the guard so that case passes. | **DEFECT — R3-C1's fix is INCOMPLETE, and the finding I expect to be worst in the round.** The guard is a PAGE-level ratio at 0.50. One spaced line on a page of prose is nowhere near 0.50, so the page is accepted; `detect()` reads `J á n   N o v á k` and finds nothing; the name is drawn on the page; `eval/extract.py` reads the same spaced string, so the leak gate scores the unredacted file CLEAN. |
| I2 | a page where only TWO characters of the rodné číslo are drawn in a subset font with no `/ToUnicode` | R3-C4's own shape, minus one character. | DEFECT. `_UNDECODABLE_MAX = 3` is absolute, so two undecodable characters are accepted, the rodné číslo matches no pattern, and the extractor reads the same mangled string. A threshold set to catch an 11-character field does not catch a 2-character one. |
| I3 | a **mis-decoded** text layer — cp1250 bytes drawn with `/WinAnsiEncoding`, so `Kováč` extracts as `Kováè` | The classic Central-European encoding failure: legacy Slovak court and land-registry systems, old Ghostscript paths, RTF→PDF converters. | DEFECT, and a THIRD route to the double-blind that neither new refusal closes. The mangled letters are `Ll` — decodable, so not unreadable; the tokens are words, so not shredded. The document is accepted, the name is truncated by `_LO` (R3-A12's mechanism), the extractor reads the same mangled text, the gate says clean. |

### Group R — `_scrub_rel_targets`

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| R1 | 30 real Slovak legal/government URLs through `_target_carries_pii` | slov-lex, ORSR, katasterportál, justice.gov.sk, NBS, finančná správa — the links a Slovak contract actually contains | Uncertain, expect at least one FALSE POSITIVE. `_target_carries_pii` accepts a candidate of ANY bucket and the punctuation-opened probe turns a URL path into capitalised bare tokens, the input the bare-name heuristic is loosest on. A destroyed link is invisible to the reviewer by the module's own argument. |
| R2 | a DOUBLE percent-encoded target, `…/klienti/Jan%2520Novak/…` | A link copied through a SharePoint/OneDrive/Outlook Safe-Links redirector is double-encoded. Law offices live in Outlook. | DEFECT, MISS. `unquote` is applied ONCE, yielding `Jan%20Novak`; `%` is not in `_TARGET_PUNCT_RE`, so the name never becomes two words. |
| R3 | `file:///C:/Users/jan.novak/Documents/zmluva.docx` and the UNC form | Word writes an absolute `file://` target for every link to a document on the office share; `attachedTemplate` in `settings.xml.rels` is one. | DEFECT, MISS, for the LOWERCASE spelling only: `.` is not in `_TARGET_PUNCT_RE`, so `jan.novak` survives as one lowercase token and no capitalisation-dependent heuristic fires. Expect the capitalised spelling to be caught (control). |
| R4 | `tel:+421905123456` | `tel:` links in an e-mail signature pasted into a letterhead. | CLEAN expected — the phone detector should read the number. Stated so it can be falsified. |

### Group M — package parts no round has attacked, against `writer/`

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| M1 | `word/settings.xml` `<w:docVars><w:docVar w:name="ClientName" w:val="Ján Novák"/></w:docVars>` | Word document variables are how a template macro carries matter data; `DOCVARIABLE` fields are standard in law-office document assembly. | DEFECT, PII SURVIVES. `_scrub_metadata` touches core.xml, app.xml and comment authors only; `settings.xml` is copied through byte-for-byte. The leak gate CAN see it (`xml_attributes`); it has never been given a document that has one. |
| M2 | `docProps/custom.xml` custom property `Klient` = `Ján Novák` | Every legal DMS (iManage, NetDocuments, Worldox) stamps client/matter into custom document properties; Word's Advanced Properties dialog is used by hand in small offices. | DEFECT, PII SURVIVES, and this one is a NAMED leak surface (`custom_xml`) the writer does not scrub. |
| M3 | `word/people.xml` `<w15:person w15:author="JUDr. Ján Novák">` | Word 2013+ writes it for every document that has ever had a comment. | DEFECT, PII SURVIVES. `_scrub_metadata` blanks `w:comment/@w:author` and nothing else. |
| M4 | `<w:pPrChange w:author>` / `<w:rPrChange>` / `<w:moveFrom>` / `<w:moveTo>` | A negotiated contract exchanged with Track Changes on. `pPrChange`/`rPrChange` come from any formatting change; `moveFrom`/`moveTo` from dragging a clause. | DEFECT. `_strip_tracked_changes` knows exactly two elements, `w:del` and `w:ins`. Expect author attributes to survive on the others, and `w:moveFrom` — which holds the text as it was BEFORE the move, in `w:delText` — to leave deleted text physically in the file, the exact failure the `w:del` branch exists to prevent. |

### Group X — cross-cutting

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| X1 | the SAME letter-spaced content as a DOCX and as a PDF | a lawyer keeps the .docx and files the .pdf | DEFECT, a disagreement rather than a leak-or-not: expect the PDF REFUSED and the DOCX accepted and silently under-redacted. Same text, two opposite verdicts, neither of them "redacted". |
| X2 | inputs chosen to make `detect()` backtrack | a pasted table, a row of dots in a signature line, a long identifier column | Uncertain. Measure wall-clock against input length, look for super-linear growth. |
| X3 | a `.docx` whose `.rels` part is not well-formed XML | a truncated download, a hand-edited package | DEFECT expected: `_scrub_rel_targets` calls `etree.fromstring` with no guard, so a malformed `.rels` raises `XMLSyntaxError` out of `redact_docx_body` — the contract promises a clean refusal, not a stack trace. `eval/extract.py` guards the same call and `writer/` does not, so the inconsistency is visible in the repo. |

RESULTS FOLLOW. Nothing above this line was edited after the first probe ran.

---

## 1. RESULT

**38 attacks attempted. 24 found a real defect. 5 expectations were falsified outright and 2
more in part.** Three of the seven fixes that landed tonight are INCOMPLETE, and one of them
(the `_fold_indices` homoglyph fix) is a measured REGRESSION.

Everything is locked in `tests/test_redteam_round4.py`:

```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round4.py -q
# today: 13 passed, 31 xfailed, 0 xpassed
```

The 13 passing tests are CONTROLS. They exist because two of this round's observations would
otherwise have been unattributable: "the GT needle is on no surface" is produced both by a
correct redaction and by a double-blind, and "the PDF was refused" is produced both by a real
guard firing and by a broken fixture. Each control is the identical fixture with the one
attacked property removed.

Full suite after this round: `python -m pytest tests/ -q` -> **1441 passed, 8 skipped,
41 xfailed, 0 failed** in 156 s. Round 3's blocker R3-F1 was fixed before this round started,
so `corpus/mutations.py` took the round-4 mutation without turning any test red.

---

## 2. FINDINGS, RANKED BY SEVERITY

Severity order is the brief's: PII survives > document corrupted / partial redaction >
ORDINARY DOCUMENT WRONGLY REFUSED > wrong label in the report > over-redaction.

---

### R4-I1 · SEVERITY 1, THE WORST IN THE ROUND — R3-C1's fix is a PAGE-level ratio, so letter-spacing ONE LINE walks straight past it, and the leak gate scores the result CLEAN

`page_is_shredded` is a per-page predicate: at least 20 tokens, more than 50 % of them single
alphanumeric characters. Its own comment explains why the threshold is loose:

> *Thresholds are on the PAGE and require a substantial amount of text, because Slovak
> notarial practice letter-spaces HEADINGS and party designations on purpose (razvetrené
> písmo) and a spaced heading must not cost the document its redaction.*

**A letter-spaced party designation IS the PII.** The guard is built to let through exactly the
case that leaks. One spaced line on a page of ordinary prose is nowhere near 0.50.

Measured, one page of a kúpna zmluva with the party block letter-spaced and nothing else:

```
get_text()  'Predavajuci:  J a n   N o v a k'
            'rodne cislo 8 5 0 1 0 1 / 1 2 3 4'   (+ 6 lines of ordinary prose)
page_is_shredded         : False   -> ACCEPTED
detect()                 : [('OBEC','Kosice',True)]      <-- no MENO, no RODNE_CISLO
output still draws       : 'J a n   N o v a k'           : True
output still draws       : '8 5 0 1 0 1 / 1 2 3 4'       : True
GT needle 'Jan Novak'    : NOT FOUND ON ANY SURFACE      <-- LEAK GATE SAYS CLEAN
GT needle '850101/1234'  : NOT FOUND ON ANY SURFACE      <-- LEAK GATE SAYS CLEAN
```

`raw_bytes` does not save it either: the line is one `Tj` and the bytes on disk are the spaced
string, so the needle is not contiguous anywhere in the file.

**CONTROL** (the identical page, party line not spaced): `[MENO_1]` and `[RODNE_CISLO_1]`,
name and number gone. So the fixture is not simply broken and the pipeline is not simply idle.

This is R3-C1 exactly — the same double-blind, PII drawn on the page, `eval/extract.py` reading
the same mangled string, the §8.1 grep passing — reached by staying under the new threshold.
The fix moved the bar; it did not close the hole.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round4.py -q -k partially_letterspaced -rxX
```

---

### R4-T9 · SEVERITY 1/2 — `_paragraph_runs` is `.//w:r`, so an ANCHORED TEXTBOX's text is WELDED onto the anchoring paragraph's text: the document is damaged, a name can survive, and the report records a surface that exists nowhere in the source

This is a defect the traversal rewrite CREATED. Round 3's B5 said "use `.//`"; the fix used
`.//` in both places, and `_paragraph_runs(p) = p.findall(".//w:r")` now descends into `<w:p>`
elements nested inside the paragraph.

Word anchors every floating textbox and shape to a body paragraph, and that paragraph normally
has prose of its own. Measured:

```
outer paragraph : 'Predávajúci: Ján Novák'
anchored textbox: 'Kupujúci: Mária Kováčová'

recon detect() is given:  'Predávajúci: Ján NovákKupujúci: Mária Kováčová'
detect() returns       :  MENO('Ján NovákKupujúci')   <-- a span ACROSS the join
output document reads  :  'Predávajúci: [MENO_1]: [MENO_2]'
report records surface :  'Ján NovákKupujúci'
```

**The other party's role label has been deleted out of the textbox.** The redacted contract no
longer says which party is the buyer, and the report claims to have redacted a string
(`Ján NovákKupujúci`) that appears in no part of the source document — so a reviewer
reconciling the report against the original finds a redaction of something that never existed.

The boundary case leaks:

```
outer 'Podpísal Ján' + textbox 'Novák, predávajúci'
  -> recon 'Podpísal JánNovák, predávajúci' -> MENO('Novák')
  -> output 'Podpísal Ján[MENO_1], predávajúci'     'Ján' SURVIVES in document_xml
```

**Why no gate sees it.** Census over all 70 corpus `.docx`, every `word/*.xml` part:

| shape | occurrences |
|---|---|
| `<w:p>` containing a nested `<w:p>` | 80 |
| ...of those, an anchor paragraph that ALSO carries its own text | **0** |
| `<mc:AlternateContent>` | **0** |
| `<w:fldSimple>` | **0** |
| `<w:instrText>` | **0** |
| `<w:sdt>` | **0** |

```
.venv/Scripts/python.exe - <<'PY'
import glob, zipfile
from lxml import etree
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
both=0
for f in sorted(glob.glob('data/synthetic/*.docx')):
    with zipfile.ZipFile(f) as z:
        for n in [x for x in z.namelist() if x.startswith('word/') and x.endswith('.xml')]:
            for p in etree.fromstring(z.read(n)).iter(W+'p'):
                if p.findall('.//'+W+'p') and ''.join(
                        t.text or '' for t in p.findall('./'+W+'r/'+W+'t')).strip():
                    both += 1
print('anchor paragraphs that carry their own text:', both)
PY
```

The corpus generator always puts a textbox in an EMPTY anchor paragraph, so the weld is a
no-op for all 80 of them and the defect is invisible to the leak gate, the mutation gate, the
cross-format gate and every test in `tests/`. Again the population, not the gate.

**CONTROL**: the same textbox in an empty anchor paragraph -> `'Predávajúci: [MENO_1]'`, clean.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round4.py -q -k "welded" -rxX
```

---

### R4-T1 · SEVERITY 2 — `<mc:AlternateContent>` holds the same textbox TWICE, both copies are welded into one reconstruction, and the FALLBACK copy is damaged

The same mechanism as T9 arriving through the shape Word emits for **every** textbox, shape and
WordArt drawn since Word 2007: a DrawingML copy in `<mc:Choice>` and a VML copy in
`<mc:Fallback>`, each with its own `<w:txbxContent><w:p>`.

```
input  : both copies read 'Predávajúci: Ján Novák'
output Choice   : <w:t>Predávajúci: </w:t><w:t>[MENO_1]</w:t>
output Fallback : <w:t>: </w:t>          <w:t>[MENO_1]</w:t>     <-- 'Predávajúci' DELETED
```

The Fallback copy is what LibreOffice, older Word and a large number of DOCX converters
actually render. Its label is gone.

**Expectation FALSIFIED in a useful way.** I predicted a double-counted occurrence and no
corruption. The report does record 2 occurrences for one visible name, which is a defect on its
own, but the real damage is the deletion, and I would not have looked for it if the occurrence
count had been the only assertion.

---

### R4-M4a · SEVERITY 1 — a MOVED clause leaves its pre-move text physically in `document.xml`

`_strip_tracked_changes` knows exactly two elements, `w:del` and `w:ins`. Word has six.
`<w:moveFrom>` is the "deleted by a move" half and holds the original text in `<w:delText>` —
which python-docx's `Run.text` does not render, so `detect()` is handed an empty paragraph and
nothing is removed.

```
redacted word/document.xml:
  <w:moveFrom w:id="3" w:author="JUDr. Ján Novák" ...>
    <w:r><w:delText>Kupujúci: Mária Kováčová, rodné číslo 855612/7788</w:delText></w:r>
  </w:moveFrom>
  <w:moveTo  ...><w:r><w:t>Kupujúci: </w:t></w:r><w:r><w:t>[MENO_1]</w:t></w:r></w:moveTo>
```

The moved-TO copy is redacted; the moved-FROM copy keeps the buyer's name and her rodné číslo
verbatim, in a STRICT text surface. This is the precise failure the `w:del` branch was written
to prevent, one element to the left. Dragging a clause in a Word document with Track Changes on
is how a negotiated contract is edited.

---

### R4-T5 / R4-T4 · SEVERITY 1 — a HYPERLINK FIELD's destination is never read by any pass

Word's two field spellings for a hyperlink. Neither goes through `.rels`, so
`_scrub_rel_targets` never sees them; neither is text-bearing, so `detect()` never sees them.

```
T5  <w:instrText> HYPERLINK "mailto:jan.novak@advokat.sk" </w:instrText>
    display run 'Ján Novák'  ->  [MENO_1]          (redacted)
    address     ->  LEAK in document_xml           (a STRICT text surface)

T4  <w:fldSimple w:instr=' HYPERLINK "mailto:jan.novak@advokat.sk" '>
    address     ->  LEAK in xml_attributes
```

T5 is the worse of the two: the page reads `[MENO_1]` and the package still names the party and
carries their address. RTF→DOCX conversion, Word 97-era documents and several DMS and
court-portal exports write hyperlinks this way.

---

### R4-T8 · SEVERITY 1 — a data-bound content control: the page is redacted and WORD PUTS THE NAME BACK

A content control with `<w:dataBinding>` caches its value in `customXml/item1.xml`. The writer
redacts the on-page run and copies the custom XML part through untouched:

```
output document.xml : Predávajúci: [MENO_1]
output customXml/item1.xml : <predavajuci>Ján Novák</predavajuci>
                             <rodneCislo>850101/1234</rodneCislo>     LEAK in other_xml_parts
```

Word re-populates a data-bound control from its store when the file is opened, so the redacted
document shows `[MENO_1]` to the tool and **the party's name to the next person who opens it**.
Every Word form built on the Developer tab and every document-assembly system produces this.

---

### R4-M1 / R4-M2 / R4-M3 · SEVERITY 1 — three package parts the writer never scrubs and the extractor already reads

`_scrub_metadata` handles `docProps/core.xml`, `docProps/app.xml` Company/Manager, and
`w:comment/@w:author`. Everything else in the package is copied through byte-for-byte.

| id | part | what leaks | leak surface |
|---|---|---|---|
| **M1** | `word/settings.xml` `<w:docVars>` | `ClientName` = `Ján Novák`, `ClientRC` = `850101/1234` | `xml_attributes` |
| **M2** | `docProps/custom.xml` | custom property `Klient` = `Ján Novák` | `custom_xml` — a NAMED surface |
| **M3** | `word/people.xml` | `w15:person/@w15:author` = `JUDr. Ján Novák`, `@w15:userId` = `jan.novak@advokat.sk` | `xml_attributes` |

M1 is how a law-office template macro carries the matter data (`DOCVARIABLE` fields). M2 is
what every legal DMS stamps on a document. M3 is written by Word 2013+ into any document that
has ever had a comment. All three are readable by `eval/extract.py` today — they have simply
never been in a document the gate was given.

---

### R4-N1 · SEVERITY 1, AND A REGRESSION IN A FIX THAT LANDED TONIGHT — the R3-A10 homoglyph fix re-opens the homoglyph attack for every identifier

`detect/normalize._fold_indices` now folds a confusable **only inside a token that already
contains a Latin letter**. An identifier is digits plus capitals. Spell its capitals in
Cyrillic and the token has no Latin letter at all, so it is never folded:

```
'Uhradte na ucet SK3112000000198742637541 do 30 dni.'  -> IBAN
'Uhradte na ucet ЅК3112000000198742637541 do 30 dni.'  -> nothing      (S,K -> Ѕ,К)
'Vozidlo ECV BA123AB ...'    -> ECV       ;  'ВА123АВ' -> nothing
'Cislo pasu: EA123456 ...'   -> CISLO_OP  ;  'ЕА123456' -> nothing
normalize('ЅК3112000000198742637541').text == 'ЅК3112000000198742637541'   (unchanged)
```

**Measured at corpus scale by the gate that already exists.** `cyrillic_homoglyph` was
blind 1.000 / known 1.000 in round 3 and is **0.973 / 0.973 today** — with
`PARCELA` 0.486, `SPISOVA_ZNACKA` 0.729, `ORG` 0.800, `ECV` 0.900, `CISLO_PASU` 0.900,
`VCHOD` 0.900. Every row that moved is an identifier type. The round-3 fix is real and its
collateral is real, and this is the number that shows the trade rather than assuming it.

**CONTROL**: `normalize('Коѕice')` still yields `Kosice` — the defence the fix was built to keep
is intact. The hole is specific to tokens with no Latin letter left.

---

### R4-I3 · SEVERITY 1 — a MIS-DECODED text layer is a third route to the double-blind, and neither new refusal watches it

cp1250 bytes drawn with `/WinAnsiEncoding` — the classic Central-European failure. `č`→`è`,
`ď`→`ï`, `ň`→`ò`, `ľ`→`¾`, `Ľ`→`¼`, `ĺ`→`å`; `á í é ó ú ý ô š ž` are identical in both code
pages and come through perfectly, which is what makes it invisible.

Every replacement is a LETTER, so `page_has_unreadable_text` is False. The token structure is
unchanged, so `page_is_shredded` is False. The document is ACCEPTED.

```
page holds : 'Predavajuci: ¼ubomír Ïurèo, bytom Hlavna 25, Kosice'
detect()   : []                                      <-- nothing at all
output     : '¼ubomír Ïurèo' still drawn; [ADRESA_1] and [OBEC_1] beside it
```

**Corpus-scale, added as the `mojibake_cp1250` mutation** (`corpus/mutations.py`, append-only,
character-local 1:1 so the homomorphism requirement holds unconditionally):

`blind 0.843 / known 0.850` — **FAIL**. Per type: `CISLO_BYTU` 0.000, `CISLO_KLIENTA` 0.000,
`LV` 0.000, `ORSR_VLOZKA` 0.000, `PARCELA` 0.000, `STATNA_PRISLUSNOST` 0.000,
`SUPISNE_CISLO` 0.000, `VODICSKY_PREUKAZ` 0.100, `PSC` 0.500, `KATASTER` 0.557, `VCHOD` 0.600,
`OBEC` 0.714. Instrument self-check OK (identity = 1.000 in every cell of both arms,
0 exclusions, 0 exceptions, 0 `detect()` exceptions).

**The positive control that makes 0.843 attributable rather than merely destructive**:
`ADRESA` 0.900 and `ULICA` 0.825 under the same mutation, because street names mostly survive
the code-page confusion. A mutation that was simply shredding the text could not leave two
types near 0.9.

**Two of my own expectations here were FALSIFIED** and are recorded in §4.

---

### R4-P3 · ORDINARY DOCUMENT WRONGLY REFUSED — three bullets refuse 70 of the 71 corpus documents

`_UNDECODABLE_MAX = 3` is an ABSOLUTE count and `Co` (private use) is in
`_UNDECODABLE_CATEGORIES`. Word's default bullet is the Symbol-font character, and a PDF
exported from a Word document carries it as **U+F0B7, category Co**, one per bullet.

```
three Symbol bullets  -> UnreadableTextLayerError    REFUSED
two  Symbol bullets   -> accepted, 'Jan Novak' correctly redacted     (CONTROL)
```

Corpus-scale: add the same three glyphs to every page of each of the 71 corpus PDFs ->
**70 / 71 REFUSED.** (The one survivor is the image-only scan, which is refused anyway.)

```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round4.py -q -k symbol_bullet -rxX
```

The guard's own comment says *"Legitimate extracted text contains essentially NO control
characters, so a small absolute count is both a tight test and a quiet one: it does not fire
on ordinary documents."* It fires on a bulleted list, which is in the obligations clause of
essentially every contract. A Wingdings checkbox (`U+F0A8`) on a Slovak tlačivo does the same
at five checkboxes.

---

### R4-P1 · ORDINARY DOCUMENT WRONGLY REFUSED — a letter-spaced Slovak title page

The other half of I1. `_SHRED_MIN_TOKENS = 20` is described as "a substantial amount of text";
a title page reaches it with a spaced heading and one line of prose.

| page | tokens | singles | ratio | verdict |
|---|---:|---:|---:|---|
| `N O T Á R S K A  Z Á P I S N I C A` + date + N/Nz numbers | 26 | 18 | 0.692 | **REFUSED** |
| `R O Z S U D O K` / `V M E N E S L O V E N S K E J R E P U B L I K Y` + court line | 36 | 33 | 0.917 | **REFUSED** |
| the same title page, heading NOT spaced (CONTROL) | — | — | — | accepted |
| the heading ALONE, 17 tokens | 17 | 17 | 1.000 | accepted (under the min-token guard) |
| a Greek symbol row in a technical annex | 29 | 25 | 0.862 | **REFUSED** |

The refusal is at DOCUMENT level: one title page refuses a 40-page filing whose other 39 pages
are ordinary prose.

**Honest limit, measured rather than assumed.** Adding one letter-spaced heading to every page
of all 71 corpus PDFs refuses **0 / 71** — a full page of prose dilutes the ratio. The false
refusal needs a SHORT page, which is what a title page is. That refines the finding; it does
not weaken it, because a notarial deed and a court decision both open on one.

---

### R4-I2 · SEVERITY 2 — `_UNDECODABLE_MAX` is an absolute 3, so TWO undecodable glyphs hide a name

A PDF whose accented glyphs come from a subset font with no `/ToUnicode` — one undecodable
character per diacritic. A Slovak name needs one or two.

```
page holds : 'Predavajuci: M\x01ria Kov\x02cova, bytom Hlavna 25, Kosice'
undecodable: 2   (< _UNDECODABLE_MAX = 3)  -> ACCEPTED
detect()   : ADRESA, OBEC     <-- no MENO
output     : 'M\x01ria Kov\x02cova' still drawn, next to [ADRESA_1] and [OBEC_1]
GT needle 'Maria Kovacova' : NOT FOUND ON ANY SURFACE  -> GATE SAYS CLEAN
CONTROL (no subset glyphs) : [MENO_1], name gone
```

A threshold tuned to catch R3-C4's eleven-character field does not catch a two-character one.

---

### R4-X2 · SEVERITY 2/3 — `detect()` is QUADRATIC on a single-case column of capitalised tokens, and a three-page one takes 3.2 seconds

An all-caps unit switches `detect/name_anchors._anchored` to the RELAXED case-insensitive
regex set (`document_is_single_case`), and `detect()`'s second `join_wrapped` view welds
every line into one enormous token. Profiling attributes 2.03 s of a 2.43 s call to
`_anchored` itself (the regex scan, not its callees).

Fully realistic fixture — a column of surnames in capitals, one per line, which is what a
land-registry owner list and an all-caps party list look like:

| input | `detect()` | growth |
|---:|---:|---|
| 710 chars | 104 ms | — |
| 1 420 chars | 59 ms | — |
| 2 840 chars | 212 ms | x3.6 |
| 5 680 chars | 814 ms | x3.8 |
| 11 360 chars | **3 186 ms** | x3.9 |

x4 per doubling is quadratic. `normalize()` is linear over the same inputs (17 ms at
22 400 chars), so the cost is in the detectors. `detect()` runs once per PDF PAGE, so one dense
all-caps page stalls the GUI worker for seconds; a synthetic 22 KB unit takes 12 s.

Ordinary all-caps Slovak prose is linear (275 ms at 29 200 chars) and mixed-case prose is
2.8x faster again, so this is not "all-caps is slow" — it is specifically one capitalised token
per line.

---

### R4-R1 · OVER-REDACTION THAT BREAKS THE DOCUMENT — real Slovak legal links are destroyed, and the reviewer cannot see it

30 links a Slovak contract actually contains, through `_target_carries_pii`. **Five would be
replaced by `https://removed.invalid/`. Three of the five are unambiguous false positives:**

| link | why it is scrubbed |
|---|---|
| `https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/2016/18/20180101` | the effective-date path segment `20180101` is read as an **IČO** |
| `https://www.justice.gov.sk/Stranky/Sudy/Zoznam-sudov.aspx` | `Sudy` is read as an **OBEC** (review bucket — and any bucket counts) |
| `https://www.mfsr.sk/sk/dane-cla-ucto/` | `dane cla`, punctuation-opened, is read as a **MENO** |

The other two are defensible rather than wrong: an ORSR search URL carrying a party's name in
its query, and a Google Maps link carrying an address.

The slov-lex one is the statute book. Amendment 15's own text says *"the first version
destroyed every working link in the document, including the statute book"* — the narrowed rule
still destroys it, by a different route. And by the module's own argument the reviewer can
never notice: the display text is unchanged.

**CONTROL**: `.../klienti/Jan%20Novak/...` and `mailto:jan.novak@advokat.sk` are still scrubbed,
so the rule has not been measured into uselessness.

---

### R4-R2 / R4-R3 / R4-R4 · SEVERITY 2 — three PII-bearing targets the scrub misses

| id | target | scrubbed | why |
|---|---|---|---|
| R2 | `https://dms.firma.sk/klienti/Jan%2520Novak/zmluva.pdf` | **no** | `unquote` runs ONCE -> `Jan%20Novak`; `%` is not in `_TARGET_PUNCT_RE` |
| R3 | `file:///C:/Users/jan.novak/Documents/zmluva.docx` | **no** | `.` is not in `_TARGET_PUNCT_RE`, so `jan.novak` stays one lowercase token |
| R3 | `\\fileserver\users\jan.novak\matter\zmluva.docx` | **no** | same |
| R4 | `tel:+421905123456` | **no** | the phone detector wants the spaced spelling |
| — | `file:///C:/Users/Jan.Novak/...` (CONTROL) | yes | capitalised, so a bare-name candidate fires |
| — | `tel:+421 905 123 456` (CONTROL) | yes | spaced |
| — | `https://dms.firma.sk/spisy/850101-1234/zmluva.pdf` | **no** | a DMS path keyed by rodné číslo |

R2's source is a link copied through an Outlook/SharePoint redirector, which is how a law office
shares a file. R4 was stated as CLEAN in advance and is FALSIFIED: a `tel:` link to the client's
mobile survives in the package.

---

### R4-X1 · SEVERITY 2 — the same content is REFUSED as a PDF and silently under-redacted as a DOCX

```
letter-spaced title page as PDF  -> ShreddedTextLayerError, REFUSED
the same lines as DOCX           -> accepted, occurrences = {} (NOTHING redacted),
                                    'J a n   N o v a k' present in document_xml
```

Two opposite verdicts on one document, and neither of them is "redacted". There is no shredded
or unreadable guard anywhere in the DOCX path, so a Word document whose heading or party block
was spaced by typing spaces — which is how a secretary letter-spaces without character spacing —
is processed and under-redacted with no warning at all.

---

### R4-X3 · SEVERITY 3 — a malformed `.rels` raises out of the writer where the contract promises a refusal

```
redact_docx_body(<package with a truncated word/_rels/document.xml.rels>)
  -> lxml.etree.XMLSyntaxError: Couldn't find end of Start Tag oops line 1
```

`_scrub_rel_targets` calls `etree.fromstring` with no guard. `eval/extract.py` guards the same
call, with a comment explaining that *"an unparseable part is exactly where someone would hide
something"*; `writer/` does not. The GUI gets a stack trace instead of the clean refusal §3
promises.

---

## 3. THE MUTATION GATE AFTER THIS ROUND

`python -m eval.mutation_gate` -> exit 1, instrument self-check OK (identity = 1.000 in every
cell of both arms, 0 exclusions, 0 exceptions), 70 docx, 3 810 units, 2 629 gradeable auto
surfaces, 0 `detect()` exceptions.

| mutation | blind | known | verdict | round |
|---|---:|---:|---|---|
| nbsp / tabs / double_spaces / nfd / narrow_nbsp | 1.000 | 1.000 | pass | 2–3 |
| zero_width | 1.000 | 1.000 | pass | 2 |
| soft_hyphen | 1.000 | 1.000 | pass | 2 |
| line_break_mid | 0.466 | 0.472 | FAIL | 2 |
| all_caps | 0.959 | 0.955 | pass | 2 |
| lowercase | 0.967 | 0.963 | pass | 2 |
| no_diacritics | 0.996 | 0.996 | pass | 2 |
| **cyrillic_homoglyph** | **0.973** | **0.973** | pass | 2 — **was 1.000/1.000 in round 3** |
| nb_hyphen | 0.941 | 0.941 | FAIL | 3 |
| surname_caps | 0.649 | 0.784 | FAIL | 3 |
| letterspaced | 0.113 | 0.112 | FAIL | 3 |
| **mojibake_cp1250** | **0.843** | **0.850** | **FAIL** | **4** |

Two rows moved for reasons that are findings in themselves:

* `cyrillic_homoglyph` **1.000 -> 0.973** is R4-N1: tonight's `_fold_indices` fix, measured.
* `line_break_mid` **0.376 -> 0.466** and `zero_width`/`soft_hyphen`/`nfd` **known 0.991 ->
  1.000**: tonight's `known_entities` normalization closed R3-A11 and improved the wrap case.
  Both are real improvements and are recorded here so the regression above is not read as the
  whole story.

---

## 4. EXPECTATIONS THAT WERE WRONG

**T2 (linked header double-processing) — predicted double-counted occurrences, measured a
single occurrence.** The PREMISE is right and is now a passing test: a two-section document
with a linked header gives `sections[0].header._element is sections[1].header._element`, so
`roots` really does walk those paragraphs twice. The CONSEQUENCE does not follow, because the
second pass runs `detect()` over `[MENO_1]` and finds nothing, so `record_occurrence` never
fires. Double-processing here is idempotent. I filed the premise rather than the prediction.

**T1 (AlternateContent) — predicted a report defect, measured DOCUMENT CORRUPTION.** Wrong in
the direction that matters: the two copies are welded, a span crosses the join, and the Fallback
copy loses the word before it. Had I only asserted the occurrence count I would have recorded a
severity-4 finding where there is a severity-2 one.

**T7 (a hyperlink run entirely covered) — predicted a lost label or a broken hyperlink,
measured CLEAN.** `_rebuild_run` inserts the `[EMAIL_1]` fragment inside the `<w:hyperlink>`
and removes the original run; the output is
`<w:hyperlink r:id="rIdX"><w:r><w:t>[EMAIL_1]</w:t></w:r></w:hyperlink>`. The label survives
and the hyperlink is well-formed. Stated as uncertain in advance, resolved as clean.

**R4 (`tel:`) — predicted CLEAN, measured a MISS.** `tel:+421905123456` is not recognised;
`tel:+421 905 123 456` is.

**I3 (mojibake) — predicted a total miss AND a blind gate; measured "sometimes a miss, and the
gate is not blind".** Two separate corrections:

* `Ján Kováè` is still found in full — `detect/gazetteer.py`'s given-name + surname pairing
  recognises `Ján` and carries the mangled surname with it. It takes a name the gazetteer does
  NOT know on both halves (`¼ubomír Ïurèo`) to produce a total miss. Same rescue, same
  precondition, as round 3's A1/A2/A8/A9 — the gazetteer is silently carrying a lot of what
  the anchors are credited with.
* the leak gate is **not** blind here: the needle `Ľubomír Ďurčo` IS found on `raw_bytes`,
  because the cp1250 bytes are still in the content stream and `_decode_all` tries that code
  page. So I3 is a PII-survives defect, **not** a double-blind. I1 is a double-blind; I3 is not.
  Saying it the first way would have sent a fixer to the wrong place.

**P2 (an annex table of single digits) — stated uncertain, resolved CLEAN.** `Zoznam príloh`
with fifteen numbered rows is 0.383, under the threshold. A pure single-digit grid
(0.941) does trip it, but I could not name a Slovak legal page that really looks like that, so
it is recorded as a lower-realism variant rather than as a finding.

---

## 5. WHAT THIS ROUND GOT WRONG ABOUT ITSELF — FIXTURE DEFECTS, NOT PRODUCT DEFECTS

**F-1. My first P1/I1 fixtures were encoded cp1250 and drawn with `/WinAnsiEncoding`** — i.e.
they carried the I3 mojibake deformation on top of the letter-spacing they were supposed to
isolate. `spísaná dňa` came back as `spísaná dòa`. Two attacks in one fixture measure neither.
How I told them apart: the I3 fixture is the one where the mismatch IS the attack; everything
else was re-authored in pure ASCII (diacritic-free Slovak, which is what the corpus PDFs use
anyway) so that exactly one property varies. Every number in groups P, I1, I2, T and X above
comes from the re-authored fixtures.

**F-2. My first occurrence-count probe printed `('[', None)`** — I unpacked `LabelMap.occurrences`
as a list when it is a `dict[label -> [(location, surface)]]`, so "1 occurrence" was the first
character of a label. That is how T1 initially looked like a non-finding. Reading the structure
in `writer/labelmap.py` instead of guessing gave `[MENO_1] -> 2 occurrences` and the surface
`'Ján NovákPredávajúci'`, which is what exposed the weld. A probe that prints the wrong thing
confidently is worse than one that crashes.

**F-3. My first X2 conclusion was "an all-caps document is quadratic", which is false.** Real
all-caps Slovak prose is linear (275 ms at 29 200 chars) and a parcel-number, LV-number, PSČ or
IBAN column is linear too. Sweeping the shape rather than asserting it narrowed the trigger to
one capitalised token per line with no internal space — which is both the true mechanism and a
shape I can name a real document for.

---

## 6. JUDGEMENT CALLS

1. **`mojibake_cp1250` maps the five WinAnsi-undefined bytes (0x81/0x8D/0x8F/0x90/0x9D) to
   U+FFFD rather than leaving the character alone.** U+FFFD is category `So`, so it does NOT
   trip `page_has_unreadable_text` — which is the honest model of what an extractor yields and
   keeps the rewrite 1:1. Leaving them alone would have UNDER-stated the damage. Recorded in
   QUESTIONS.md as Q17 with the reversal.
2. **`mojibake_cp1250` is NOT added to `CASE_DESTROYING`.** That set is for mutations whose
   loss on a capitalisation-dependent population is inherent. This one destroys diacritics, not
   case, and its losses are genuine detector misses.
3. **The corpus-scale false-refusal census is reported for both new guards, and one of the two
   numbers is ZERO.** Adding a letter-spaced heading to every corpus page refuses 0/71; adding
   three bullets refuses 70/71. Reporting only the second would have been the more impressive
   round.
4. **No existing mutation, test, threshold or detector was modified.** `corpus/mutations.py` is
   append-only (one function, one registry line); `tests/test_redteam_round4.py` is new;
   `redteam/FINDINGS_ROUND4.md` and one `QUESTIONS.md` entry are the rest. `detect/`, `writer/`,
   `gui/` and `eval/` are untouched.
5. **R4-T9 and R4-T1 are filed against `writer/docx_body.py`, not against the corpus.**
   Regenerating the corpus with anchor paragraphs that carry text would make the leak gate catch
   the boundary leak, and that is the right long-term move, but the corruption exists whether or
   not anything measures it.

---

## 7. WHAT I SUSPECT AND COULD NOT CONFIRM

* **`_paragraph_location` tags the welded redaction by the OUTER paragraph.** In T9b the cut
  landed inside the textbox and the report says `body`. Every welded case therefore also
  mis-files its location, which is what a reviewer navigates by. I did not separate this into
  its own finding because it is the same defect seen from the report side.
* **`<w:sdt>` wrapping a RUN rather than a paragraph** (`<w:sdtContent>` directly inside
  `<w:p>`) should be covered by `.//w:r`, but a run-level content control with a `w:dataBinding`
  would carry the T8 store defect without the T8 paragraph shape. Not built.
* **`docProps/thumbnail.jpeg` is dropped, but a Word-saved package also carries
  `word/media/*` with EXIF** — a scanned signature image carries the scanner model and
  sometimes a path containing the user name. `binary_parts` reads it; nothing scrubs it. I could
  not build a faithful fixture without a real scanner file.
* **`_scrub_rel_targets` rewrites the whole ZIP with `ZIP_DEFLATED` and
  `etree.tostring(..., standalone=True)`.** Every output I opened round-trips through
  python-docx, but I did not open one in Word, and OPC consumers are sensitive to
  `[Content_Types].xml` ordering and to a re-declared XML preamble. Unverified either way.
* **An ENCRYPTED PDF** (the Slovak land registry issues owner-password PDFs) goes to
  `fitz.open` before any guard. I did not build one; X3 is the DOCX half of the same question
  and it fails, so the PDF half is worth one fixture.
* **The quadratic `_anchored` cost may be a genuine catastrophic backtrack rather than an
  honest O(n²) scan.** The growth I measured is x4 per doubling, which is consistent with a
  quadratic scan over a welded mega-token; I did not isolate the individual regex. If it is
  catastrophic backtracking the exponent is worse than I have recorded, not better.
