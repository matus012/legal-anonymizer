# Red-team findings, round 3 — SHAPES THE CORPUS CANNOT CONTAIN

**Target:** the two halves round 1 and round 2 did not attack.

* Round 1 (`redteam/FINDINGS.md`) attacked `eval/extract.py` — which SURFACES the leak gate can read.
* Round 2 (`redteam/FINDINGS_ROUND2.md`) attacked `detect/*` — whether an unusually SPELLED
  surface is still found. Its eleven mutations are character-local or token-local rewrites of
  the text a paragraph already holds.

Round 3 attacks a third thing neither could reach: **the shape of the CONTAINER**. Every number
in this project is measured on documents built by `corpus/docx_builder.py` (python-docx: one
`<w:t>` per `<w:r>`, no hyperlinks, no content controls, no nested tables) and
`corpus/pdf_builder.py` (PyMuPDF `insert_text`: one show-text operator per line). A defect that
only fires on a container shape the generator cannot emit is invisible to the leak gate, to the
mutation gate, to the cross-format gate and to every test in `tests/` — not because the gates
are weak, but because **the population they run over does not contain the shape**. A real
`.docx` saved out of Word contains four of those shapes on its first page.

Plus the shapes a Slovak name actually has, which the name anchors' `[A-Z][a-z]+` token class
cannot spell.

---

## 0. EXPECTATIONS, WRITTEN BEFORE ANY ATTACK WAS RUN

Round 2's most valuable result was an expectation that turned out wrong, so the same discipline
applies. This table was written and saved **before** the first probe executed; RESULT sections
were appended afterwards and nothing in the "expectation" column was edited.

| # | attack | real-world source | expectation stated in advance |
|---|--------|-------------------|-------------------------------|
| A1 | hyphenated double surname — `Kováč-Nagy`, `Nováková-Kováčová` | Slovak naming law lets a married woman carry both surnames joined by a hyphen. Southern Slovakia (Komárno, Dunajská Streda) is full of Slovak–Hungarian double surnames. | DEFECT. `_CAP` is `[A-Z][a-z]+` and `_SEP` is horizontal whitespace, so `-` ends the token. Expect the role/title anchor to cover `Ján Kováč` and leave `-Nagy` standing: a PARTIAL redaction, worse than a miss because the report claims the name was redacted. Field-label form expected CLEAN (its value runs to end of line). |
| A2 | apostrophe surname — `O'Brien`, `D'Angelo` | Cross-border commercial filings; Irish/Italian/French counterparties in a purchase contract. | DEFECT, total miss. `[A-Z][a-z]+` cannot start at `O` (needs a lowercase immediately), so the anchor fails to match AT ALL at the value position — no candidate of any bucket. |
| A3 | lowercase nobiliary particle — `de la Cruz`, `van der Berg` | Dutch/Spanish/Belgian counterparties; ordinary in an ORSR extract of a foreign-owned s.r.o. | DEFECT, partial: only the first capitalised token taken. |
| A4 | stacked titles — `prof. JUDr. Ing. Ján Novák, PhD., LL.M.` | Every splnomocnenie and court-filing header in Slovakia. | **CLEAN.** `_TITLE_RUN` is `(?:TITLE\.\s*)+` — a stacked run by construction — and `_TITLE_TRAILING_RE` handles the post-nominal. Stated as CLEAN precisely so it can be falsified. |
| A5 | surname in CAPS inside an otherwise mixed-case document — `Ján NOVÁK` | The continental convention for marking the surname: ORSR extracts, notarial deeds, court headers. **Round 2's `all_caps` structurally could not find this** — it makes the whole unit single-case, which trips `document_is_single_case` and switches the anchors to their RELAXED regex set. A mixed-case document keeps the STRICT set. | DEFECT. Expect `predávajúci Ján NOVÁK` → `MENO("Ján")`, `NOVÁK` left standing. |
| A6 | U+2011 NON-BREAKING HYPHEN inside an identifier — `V‑1234/2025`, `KL‑99321`, `BA‑123AB` | Ctrl+Shift+hyphen in Word. It exists for exactly this: keeping a case number or a plate from breaking at a line end. Slovak house styles mandate it. | DEFECT. `normalize._compat` is per-character NFKC and NFKC(U+2011) is U+2010 HYPHEN, **not** ASCII `-`: the fold runs, changes the character, and still does not produce what the patterns spell. |
| A7 | spisová značka shapes the corpus does not author — `II. ÚS 45/2024`, `1Cdo/12/2023`, `sp. zn. 2 C 45/2019` | The Constitutional Court numbers every case with a Roman senate numeral. Supreme Court agendas are three letters (`Cdo`, `Obdo`, `Tdo`, `Sžk`). Space-separated is the older but still-used district-court form. | DEFECT. `_SPISOVA_ZNACKA_RE` is `\d{1,2}(?:Cb|Ro|Er|C|T|D)/\d{1,3}/\d{4}` plus cadastral `[VZPXR]-…`. None of the three can match. |
| A8 | name as a numbered list label — `1. Ján Novák` | A žaloba with several plaintiffs, a splnomocnenie listing attorneys, any party enumeration. | DEFECT **and worse than a plain miss**: `_at_sentence_start` walks back over spaces, sees the `.` of `1.`, and the bare-name heuristic skips the name. Not redacted AND not in the review bucket — it never appears in the report, so the reviewer cannot notice. |
| A9 | name inside Slovak typographic quotes — `„Ján Novák“` | `(ďalej len „Novák“)` is in the definitions clause of essentially every Slovak contract. | Uncertain. Expect the role anchor to fail (the quote sits between separator and value) but the bare-name heuristic to fire (auto=False → review): a defined-term alias dropping from auto to review. |
| A10 | a genuinely Cyrillic name — `Олександр Ковальчук` | Ukrainian clients. Slovak offices have handled them by the thousand since 2022; a residence permit or a power of attorney carries the name in Cyrillic. | DEFECT of a kind not yet recorded here: `normalize._HOMOGLYPHS` folds unconditionally, so a fully-Cyrillic word comes out MIXED-SCRIPT (`Ковальчук` → only `К` folded). `detect/normalize.py`'s own docstring claims the map avoids corrupting genuinely Cyrillic text; the implementation does not avoid it. Expect the user's own known-entity string, typed in Cyrillic, to fail against the folded document text. |
| A11 | known-entity list vs document, normalized asymmetrically | The lawyer pastes the party's name out of the source document into the known-entities box — or types it on their own keyboard while the document came from elsewhere. | DEFECT. `detect()` normalizes the TEXT and never the `known_entities` list. Round 2's `known` arm mutated both sides, hiding this by construction. Expect a document-side-only deformation to be rescued and a **list-side-only** deformation to be lost. |
| B1 | a `<w:r>` containing more than one `<w:t>` | Word emits this constantly: a Shift+Enter (`<w:br/>`) inside a formatting run, a `<w:tab/>`, a `<w:noBreakHyphen/>`, and `<w:lastRenderedPageBreak/>`, which Word inserts mid-run on every save. python-docx emits exactly one `<w:t>` per run, so **no corpus document can contain this shape**. | DEFECT, SEVERITY 1. `writer/docx_body._rebuild_run` does `clone = deepcopy(r_elem)` then `clone.find(qn("w:t"))` — the FIRST `w:t` only. Every other `w:t` is deep-copied into every fragment clone with its ORIGINAL TEXT INTACT. Expect the PII to survive **and be duplicated once per fragment**, with the `<w:br/>`/`<w:tab/>` duplicated too. |
| B2 | display text inside `<w:hyperlink>` | Word auto-hyperlinks every e-mail address and URL the moment you type one and press space. The corpus never contains one. | DEFECT. `Paragraph.runs` is `self._p.r_lst` = **direct `w:r` children only**; a run inside `<w:hyperlink>` is not one, so it is neither detected nor redacted and is not even in the text `detect()` sees. Expect a full EMAIL leak into `document.xml`, and expect the leak GATE to catch it (round 1 made `document_xml` a read surface) — so corpus blindness, not gate blindness. |
| B3 | a table nested inside a table cell | Any DOCX converted from HTML (court-portal export, saved e-mail) is nested tables; Word users also nest a party block inside a form table. | DEFECT. `_redact_cells` iterates `cell.paragraphs` (direct `w:p` children of `w:tc`); `doc.tables` is top-level only. |
| B4 | a paragraph inside `<w:sdt>` (content control) | Every Word TEMPLATE with fill-in fields. A law office runs on templates. | DEFECT, same mechanism as B2: `doc.paragraphs` is direct `w:p` children of `w:body`. |
| B5 | a paragraph nested deeper than a direct child of `<w:txbxContent>` (a table in a textbox) | A signature block drawn as a textbox containing a two-column table. | DEFECT — `_redact_textboxes` uses `txbx.findall(qn("w:p"))`, direct children only, while the rest of the module uses `.//`. |
| C1 | PDF with one show-text operator per glyph | Legal DMS exports, PDF/A converters, InDesign with manual kerning, every OCR-to-PDF pipeline (Tesseract/ABBYY place text per word or per glyph). | DEFECT, and the worst kind: expect `get_text()` to return glyphs separated by spaces, so (a) `detect()` never sees the name and it is never redacted, AND (b) `eval/extract.py` reports the same spaced string, so the ground-truth needle does not grep — **the leak gate scores an entirely unredacted document CLEAN**. Round 1's blind spots are surfaces the extractor cannot READ; this is one it reads and MANGLES. |
| C2 | rotated page (`/Rotate 90`) | Scanned-then-corrected filings, landscape annexes, land-registry maps. | CLEAN expected — `search_for` and `add_redact_annot` both work in unrotated page space and MuPDF reconciles it. Stated so it can be falsified. |
| C3 | two-column page layout | Rare in Slovak contracts, ordinary in a journal reprint attached as an annex. | Uncertain. Expect `get_text("text")` to keep the columns separate; the risk is an anchor and its value landing in different blocks. |
| D1-D3 | three new mutations in `corpus/mutations.py`: `nb_hyphen`, `narrow_nbsp`, `surname_caps` | see each docstring | `nb_hyphen` DEFECT (A6); `narrow_nbsp` CLEAN (U+202F is `\s`, absorbed by the whitespace-run collapse — the mechanism that made `nbsp` 1.000); `surname_caps` DEFECT (A5). |

RESULTS FOLLOW. Nothing above this line was edited after the first probe ran.

---

## 1. RESULT

**25 attacks attempted. 14 found a real defect. 4 expectations falsified outright and 2 more
were falsified in part.**

Every reproduction below is one command. The whole set is locked in
`tests/test_redteam_round3.py`:

```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -rxX
# today: 6 passed, 21 xfailed, 0 xpassed
```

The tests assert **the property that should hold**, and the ones that do not hold yet carry
`xfail`. A red-team test that asserted the bug would be green now and RED the day somebody
fixed it. The 6 passing tests are **controls**: the same fixture builder, the shape the corpus
DOES contain, redacting cleanly. Without them a leak here would be indistinguishable from a
fixture that is simply malformed.

### The premise, measured rather than asserted

Census over all 70 corpus `.docx`, every `word/*.xml` part:

| shape | occurrences in the corpus |
|---|---|
| a `<w:r>` with more than one `<w:t>` | **0** (0 of 70 documents) |
| `<w:hyperlink>` | **0** |
| a `<w:tbl>` inside a `<w:tc>` | **0** |
| `<w:sdt>` | **0** |
| `<w:br/>` / `<w:tab/>` / `<w:lastRenderedPageBreak/>` inside a run | **0** / **0** / **0** |

```
.venv/Scripts/python.exe - <<'PY'
import glob, zipfile
from lxml import etree
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
n=0
for f in sorted(glob.glob('data/synthetic/*.docx')):
    with zipfile.ZipFile(f) as z:
        for p in [x for x in z.namelist() if x.startswith('word/') and x.endswith('.xml')]:
            root=etree.fromstring(z.read(p))
            n+=sum(1 for r in root.iter(W+'r') if len(r.findall(W+'t'))>1)
print('runs with >1 <w:t> in the whole corpus:', n)
PY
```

**Every defect in section 2 is invisible to every gate in this repo, and the reason is the
population, not the gate.** For B1–B5 the leak gate would catch each one instantly — the
surviving PII lands in `document_xml`, a STRICT text surface under round 1's rule. It has
simply never been given a document that contains the shape. C1 is the exception and is worse:
there the gate would report CLEAN.

---

## 2. FINDINGS, RANKED BY SEVERITY

Severity order is the brief's: **PII survives** > **document corrupted / token partially
redacted** > **wrong label in the report** > over-redaction (which this project accepts;
recall over precision).

---

### R3-C1 · SEVERITY 1, AND THE WORST IN THE ROUND — a PDF whose text is placed per glyph is not redacted, AND THE LEAK GATE SCORES IT CLEAN

Every other finding here is a leak the gate would catch if the corpus carried the shape. This
one is a leak the gate **reports as clean**.

`corpus/pdf_builder.py` draws with `page.insert_text()`, one show-text operator per line, with
the font's own advances. A PDF from a legal DMS, a PDF/A converter, a layout engine with
tracking applied, or any OCR-to-PDF pipeline places text glyph by glyph with advances that do
NOT match the font metrics. MuPDF then inserts word breaks where it sees a gap.

Measured sweep, one `Tj` per glyph, advance scaled by `tracking`:

| tracking | `get_text("text")` | `detect()` auto candidates | leak-gate needles found |
|---:|---|---:|---|
| 0.85 | `Predavajuci: Jan Novak` | 2 | — (redacted correctly) |
| 1.00 | `Predavajuci: Jan Novak` | 2 | — |
| 1.15 | `Predavajuci: Jan Novak` | 2 | — |
| **1.30** | `P re d a v a ju ci: Ja n N o va k` | **0** | **none — GATE SAYS CLEAN** |
| **1.50** | `P r e d a v a ju c i: J a n N o v a k` | **0** | **none — GATE SAYS CLEAN** |
| **1.80** | `P r e d a v a j u c i : J a n N o v a k` | **0** | **none — GATE SAYS CLEAN** |

At 1.3 and above: `detect()` returns nothing, `writer/pdf_body.py` redacts nothing, the name
and the rodné číslo are still drawn on the page and perfectly legible — and because
`eval/extract.py` reads the same mangled string from the same `get_text()`, the ground-truth
needle `Jan Novak` is not present on ANY surface, so the §8.1 leak grep passes.

`raw_bytes` does not save it either: each glyph is its own `(J) Tj`, so the needle never
appears contiguously in the file.

**Why normalization cannot reach this.** `detect/normalize.py` collapses a whitespace RUN to
one character; it does not DELETE a space, and must not — deleting spaces would weld every
pair of words in every document. The `join_wrapped` second view deletes only a **line break**,
and only between two runs of CAPITALS AND DIGITS (`_is_identifier_run`). An intra-word space is
outside both mechanisms by construction.

**Corpus-wide size of the damage.** Added as the `letterspaced` mutation
(`corpus/mutations.py`): blind robustness **0.113**, macro **0.127**, with 35 of the 38 types below
the gate and most at 0.000 — IBAN, IČO, DIČ, IČ DPH, EMAIL, ADRESA, LV, PARCELA and MENO. Round 2 recorded
as its judgement call 1 "DOCX only; no PDF arm… cost: a PDF-only normalization defect is
invisible to this gate". **This is that defect, and it is the largest number in the project.**

**The positive control that makes 0.113 attributable rather than merely destructive:**
`RODNE_CISLO` = **1.000** and `FAX` = **1.000** under the same mutation, because their
separators already accept a space (Amendment 5's space-separated RČ form; `_FAX_SEPCHAR`). A
mutation that was simply shredding the text could not leave two types untouched.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k c1_letterspaced -rxX
.venv/Scripts/python.exe -m eval.mutation_gate    # column 'lettersp'
```

**Real-world source.** Letter-spacing (*razvetrené písmo*) is a live Slovak convention for
headings and party designations in notarial deeds, and Word implements it as character spacing
that extractors render as real spaces. Independently, tracking and per-glyph placement are what
a DMS export, a PDF/A converter and every OCR text layer produce. A scanned-and-OCR'd filing is
out of v1 scope (context.md §3) **only when it has no text layer at all** — an OCR'd PDF that
HAS a text layer is accepted by `has_text_layer()` and processed.

---

### R3-B1 · SEVERITY 1 — a `<w:r>` with two `<w:t>` elements: the PII survives, is DUPLICATED once per fragment, and the layout is damaged

`writer/docx_body._rebuild_run` (lines 102–123):

```python
for offset, (_kind, value) in enumerate(fragments):
    clone = deepcopy(r_elem)            # <-- carries EVERY child of the run
    t = clone.find(qn("w:t"))           # <-- the FIRST <w:t> only
    ...
    t.text = value
```

`Run.text` in python-docx 1.2.0 is
`"".join(str(e) for e in self.xpath("w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab"))`
— so the reconstruction correctly sees a run whose text is spread over several `w:t`. The
REWRITE does not: it overwrites the first `w:t` and deep-copies the others, verbatim, into
every fragment clone.

Input (one paragraph, one run, a Shift+Enter inside it — the ordinary way an address block is
typed):

```xml
<w:r><w:t>Predávajúci: Ján Novák</w:t><w:br/><w:t>Kupujúci: Mária Kováčová</w:t></w:r>
```

Output after `redact_docx_body`:

```xml
<w:r><w:t>Predávajúci: </w:t><w:br/><w:t>Kupujúci: Mária Kováčová</w:t></w:r>
<w:r><w:t>[MENO_1]</w:t>     <w:br/><w:t>Kupujúci: Mária Kováčová</w:t></w:r>
<w:r><w:t>&#10;Kupujúci: </w:t><w:br/><w:t>Kupujúci: Mária Kováčová</w:t></w:r>
<w:r><w:t>[MENO_2]</w:t>     <w:br/><w:t>Kupujúci: Mária Kováčová</w:t></w:r>
```

`Mária Kováčová` appears **four times in the redacted output**, next to the label `[MENO_2]`
that claims she was redacted. Four `<w:br/>` where there was one.

The `<w:tab/>` variant is the sharpest single line in this round — a field label aligned with a
tab, inside one run:

```xml
<w:r><w:t>Meno a priezvisko:</w:t><w:tab/><w:t>Ján Novák</w:t></w:r>
  ->
<w:r><w:t>Meno a priezvisko:&#9;</w:t><w:tab/><w:t>Ján Novák</w:t></w:r>
<w:r><w:t>[MENO_1]</w:t>          <w:tab/><w:t>Ján Novák</w:t></w:r>
```

The document now reads `Meno a priezvisko:→→[MENO_1]→Ján Novák`. The tab is doubled (the
reconstruction's `"\t"` is written into the `w:t` **and** the `<w:tab/>` element survives), and
the name is printed immediately after its own redaction label.

**Every producer of this shape is Word itself:** a Shift+Enter inside a formatting run, a
`<w:tab/>` inside a run, a `<w:noBreakHyphen/>`, and `<w:lastRenderedPageBreak/>`, which Word
writes into the middle of a run on every save. **Zero of the 70 corpus documents contain it**
(measured above) because python-docx emits exactly one `w:t` per run.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k r3_b1 -rxX
```

---

### R3-B2 … R3-B5 · SEVERITY 1 — four whole regions of a real `.docx` that the traversal never visits

All four have the same mechanism: python-docx's `runs` / `paragraphs` / `tables` accessors are
**direct children only**, and `writer/docx_body.py` relies on them (it correctly uses `.//` for
notes parts, so the inconsistency is visible in one file).

| id | shape | why the traversal misses it | who produces it |
|---|---|---|---|
| **B2** | run inside `<w:hyperlink>` | `Paragraph.runs` is `self._p.r_lst` — `./w:r`. The run is not a direct child, so it is not even in the text `detect()` sees. | Word auto-hyperlinks every e-mail address and URL the moment you type one and press space. A law office's letterhead paragraph is one. |
| **B3** | `<w:tbl>` inside a `<w:tc>` | `_redact_cells` walks `cell.paragraphs` (direct `w:p` of `w:tc`); `doc.tables` is top level only. | Any `.docx` converted from HTML — a court-portal export, a saved e-mail — plus hand-nested party blocks. |
| **B4** | `<w:p>` inside `<w:sdt>` | `doc.paragraphs` is direct `w:p` of `w:body`. | Every Word TEMPLATE with fill-in content controls. A law office runs on templates. |
| **B5** | `<w:p>` deeper than a direct child of `<w:txbxContent>` (a table in a textbox) | `_redact_textboxes` uses `txbx.findall(qn("w:p"))`, not `.//`. | A signature block drawn as a textbox containing a two-column table. |

Measured, all four, with `known_entities=["Ján Novák", "Mária Kováčová"]` supplied:

```
B2_hyperlink       LEAK  jan.novak@advokat.sk  in document_xml
B3_nested_table    LEAK  Ján Novák             in document_xml
B4_sdt             LEAK  Ján Novák             in document_xml
B5_textbox_table   LEAK  Ján Novák             in document_xml
B0_control         clean
```

B2 is the one to fix first: it is not a rare shape, it is **what Word does to an e-mail
address without being asked**, and `EMAIL` is vyhláška clause (e).

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k "r3_b2 or r3_b3 or r3_b4 or r3_b5" -rxX
```

---

### R3-A6 · SEVERITY 2 — U+2011 NON-BREAKING HYPHEN: a PARTIAL redaction that prints a label claiming success

`detect/normalize.py` runs per-character NFKC. `NFKC("‑")` is `"‐"` HYPHEN — **not**
ASCII `-`. The fold fires, changes the character, and lands one codepoint short of every
pattern in `detect/`.

```
Číslo klienta: KL‑99321   ->  CISLO_KLIENTA('KL', auto=True)    # <-- the ANCHOR, not the number
Vec vedená pod V‑1234/2025 ->  nothing
Vozidlo EČV BA‑123AB       ->  nothing
123456‑1234567890/1100     ->  DIC('1234567890')                # prefix + bank code survive
```

The first line is the worst shape in this project: the **output document reads**

```
Číslo klienta: [CISLO_KLIENTA_1]‑99321
```

The client number is printed in the redacted file, immediately after a label asserting that the
client number was removed, and the report will list `CISLO_KLIENTA` as redacted. A reviewer
scanning for un-redacted values sees a redaction label and moves on. **A partial redaction that
looks complete is worse than an obvious miss.**

Corpus-wide, added as the `nb_hyphen` mutation: blind **0.941**, known **0.941** — below the
0.95 gate. Per type: `BANKOVY_UCET` 0.000, `SPISOVA_ZNACKA` 0.486, `DATUM` 0.743, `ECV` 0.750,
`SUMA` 0.771.

**Real-world source.** Ctrl+Shift+hyphen in Word. It exists for exactly one purpose: keeping a
reference from breaking at a line end. A Slovak filing is full of tokens nobody wants broken —
`V-1234/2025`, `BA-123AB`, `KL-99321`, `Kováč-Nagy`. It renders identically to a hyphen; no
reviewer can see the difference.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k a6_non_breaking -rxX
.venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'.');from detect.core import detect;print([(c.type,c.surface) for c in detect('Číslo klienta: KL‑99321',[])])"
```

---

### R3-A7 · SEVERITY 2 — `SPISOVA_ZNACKA` matches one Slovak court-reference spelling out of four

`detect/registry_refs.py::_SPISOVA_ZNACKA_RE` accepts `[VZPXR]-\d{1,4}/\d{4}` and
`\d{1,2}(?:Cb|Ro|Er|C|T|D)/\d{1,3}/\d{4}`. Those are precisely the two shapes
`corpus/templates/*.py` authors. Measured, all missed entirely (no candidate of any bucket):

| reference | court | result |
|---|---|---|
| `II. ÚS 45/2024` | Ústavný súd SR — every ÚS case carries a Roman senate numeral | **nothing** |
| `1Cdo/12/2023` | Najvyšší súd — three-letter agenda | **nothing** |
| `5Obdo/7/2022` | Najvyšší súd, obchodné dovolanie | **nothing** |
| `2 C 45/2019` | okresný súd, space-separated form | **nothing** |
| `12Cb/345/2025` | the corpus's own form | found (control) |

A Slovak law office cites a Constitutional Court nález in every ústavná sťažnosť and every
brief that argues a constitutional point. Logged as QUESTIONS.md **Q16** with the default
("this is a defect, not a scope decision") and its reversal.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k a7_spisova -rxX
```

---

### R3-A10 / R3-A11 · SEVERITY 2 — the known-entity layer, "the single highest-value input in the whole system", fails silently on the input the lawyer is most likely to give it

`detect()` normalizes the **document text** and never the **`known_entities` list**. The two
sides then cannot meet, and the flow in which they diverge is the one the UI encourages: the
lawyer **pastes the party's name out of the document being redacted** into the entity box, so
whatever invisible character is in the document is in the list too.

Isolated on a sentence with **no** role word, **no** title, **no** field label and a name in
**no** gazetteer, so the known-entity layer is the only thing that can produce `auto=True`:

| deformation | in the DOCUMENT only | in the LIST only | in BOTH (the paste flow) |
|---|---|---|---|
| `zero_width` | HIT | **MISS** | **MISS** |
| `soft_hyphen` | HIT | **MISS** | **MISS** |
| `cyrillic_homoglyph` | HIT | **MISS** | **MISS** |
| `nfd` / `nb_hyphen` / `narrow_nbsp` / `surname_caps` | HIT | HIT | HIT |

The mechanism is visible in `detect/expansion.py`: every generated variant, including the
stems, carries the invisible character through — `expand_person("Al​essandro
Be​rtolini")` yields the stem `be​rtolin`, which can never match the normalized text.

**This shows up in the gate that already exists, and nobody had read it that way.** In the
current `eval/mutation_gate` run, `zero_width`, `soft_hyphen`, `cyrillic_homoglyph` and `nfd`
are **blind = 1.000, known = 0.991**. The `known` arm mutates the entity list too, so the
residual 0.9 % is exactly the entity list failing where the text no longer does. Before
Amendment 9 the blind arm was broken as well and the 0.991 was invisible underneath it —
**the normalization fix is what created this asymmetry**: previously document and list were
deformed the same way and matched each other; now the document is folded and the list is not.

**R3-A10 is the same defect at its sharpest, and it contradicts the module's own docstring.**
`detect/normalize.py` says the homoglyph map lists "only true confusables … folding it would
corrupt genuinely Cyrillic text — Slovakia has a large Ukrainian-speaking population and a
filing may legitimately contain a Cyrillic name that should be read as Cyrillic." The
implementation folds unconditionally, so it does exactly that:

```
"Олександр Ковальчук"   --normalize-->   "Oлeкcaндp Koвaльчyк"
```

A mangled half-Latin token. Nothing matches it — not the gazetteer, not the anchors, and **not
the user's own known-entity string typed in Cyrillic**:

```
detect("Кupujúci Олександр Ковальчук prehlasuje.", ["Олександр Ковальчук"])  ->  []
```

Ukrainian clients are not a hypothetical for a Slovak law office in 2026; a residence permit,
a power of attorney or a passport copy carries the name in Cyrillic.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k "a10 or a11" -rxX
.venv/Scripts/python.exe -m eval.mutation_gate   # blind 1.000 vs known 0.991 on zero_width/soft_hyphen/cyrillic/nfd
```

---

### R3-A5 · SEVERITY 2 — a surname in CAPITALS inside an otherwise mixed-case document

```
predávajúci Ján Novák   ->  MENO('Ján Novák', auto=True)
predávajúci Ján NOVÁK   ->  MENO('Ján',       auto=True)      <-- 'NOVÁK' SURVIVES
JUDr. Ján NOVÁK         ->  MENO('Ján',       auto=True)      <-- 'NOVÁK' SURVIVES
Meno a priezvisko: Ján NOVÁK -> MENO('Ján NOVÁK', auto=True)  (field label runs to end of line)
```

`_CAP` is `[A-ZÁÄČ…][a-záäč…]+` — an uppercase letter followed by LOWERCASE ones.
`detect/name_anchors.py` relaxes it to a case-insensitive set only when
`document_is_single_case(text)` is True, and that function requires **every** letter in the
unit to be one case. A document that is mixed-case overall but writes the surname in capitals
keeps the STRICT set.

**Round 2's `all_caps` could not have found this.** It uppercases the whole unit, which trips
`document_is_single_case` and switches to the relaxed set — the very population `all_caps`
rescues by relaxing is the one this shape leaves unrescued. It is structurally invisible to
that arm.

Corpus-wide, added as the `surname_caps` mutation: blind **0.649** / known **0.784**, macro
0.912. `MENO` = **0.014** blind (13 of 939 surfaces), `ULICA` 0.000, `OBEC` 0.357, `PSC` 0.600,
`ADRESA` 0.667.

Honest limit of that aggregate, stated in the mutation's own docstring: the predicate has to be
a function of one token (the homomorphism requirement), so it uppercases ordinary Capitalized
words too. The aggregate measures the deformation CLASS; the attributable evidence for the
narrow claim is the four-line discriminator above.

**Real-world source.** The continental convention for marking which name is the family name.
ORSR extracts, notarial deeds, court headers and identity documents all use it.

**Reproduction**
```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round3.py -q -k a5_uppercase -rxX
.venv/Scripts/python.exe -m eval.mutation_gate    # column 'surname_'
```

---

### R3-A12 · SEVERITY 2 — a Latin letter that is not in the Slovak alphabet truncates an anchored name

`_UP`/`_LO` in `detect/name_anchors.py` are spelled out as the Slovak letters only. Any other
Latin letter ends the token:

```
predávajúci Hans Straßer     ->  MENO('Hans Stra')       'ßer'    SURVIVES
predávajúci Ferenc Gyűrke    ->  MENO('Ferenc Gy')       'űrke'   SURVIVES
kupujúci Ion Țăran           ->  MENO('Ion')             'Țăran'  SURVIVES
predávajúci Ladislav Szűcs   ->  MENO('Ladislav Sz')  +  gazetteer MENO('Ladislav Szűcs')  -> covered
```

The anchors are broken in **every** one of those; the gazetteer's given-name + surname pairing
rescues the surface **only when it recognises both halves**. When the given name or the surname
is outside its lists — which is precisely the cross-border case — the rescue does not fire and
a fragment of the surname is left in the document next to its own redaction label.

Hungarian `ő`/`ű` is not exotic here: the Hungarian minority is ~8 % of Slovakia's population
and names like Kőrösi, Bőhm, Szűcs, Tőzsér are ordinary in Komárno and Dunajská Streda land
registries. Polish `ń`/`ł`/`ś`, German `ß` and Austrian counterparties follow the same path.

---

### R3-A3 · SEVERITY 3 — a lowercase nobiliary particle ends the name run

```
kupujúci Juan de la Cruz     ->  MENO('Juan')      'de la Cruz' SURVIVES
svedok Jan van der Berg      ->  MENO('Jan')       'van der Berg' SURVIVES
```

`_NAME_SEQ` is 1–3 CAPITALISED tokens separated by horizontal whitespace, so the run stops at
the first lowercase word. Realism is lower than A12's (Spanish/Dutch/Belgian counterparties in
an ORSR extract of a foreign-owned s.r.o.) and the loss is a surname rather than a fragment,
which is why it ranks below A12 rather than with it.

---

### R3-C4 · SEVERITY 2, LOWER REALISM — a font with a custom `/Differences` encoding and no `/ToUnicode` is a second double-blind

A hand-built PDF whose `/Encoding /Differences` maps codes to glyph names, with no `/ToUnicode`
CMap:

```
has_text_layer()  : True          <-- the app accepts the file, it does not refuse it
get_text()        : 'Predavajuci: Jan Novak\nRodne cislo: \x08\x05\x03\x03\x01\x05/\x03\x03\x01\x08'
detect() auto     : [('MENO', 'Jan Novak')]        <-- RODNE_CISLO is NOT FOUND
leak-gate needles : none on any surface            <-- GATE SAYS CLEAN
raw bytes         : the needle is not there either (stored as octal codes)
```

The rodné číslo is drawn on the page, a human reads it perfectly, it is never redacted, and the
§8.1 grep passes. Same class as C1 and the same consequence. Realism is lower — most modern
producers do write a `/ToUnicode` — but subset fonts without one are still produced by older
pdfTeX, several Ghostscript paths and scanner software, which is exactly the software an older
Slovak court IT estate runs.

---

### R3-D2 · CLEAN, and it is a control, not a filler

`narrow_nbsp` (every space becomes U+202F NARROW NO-BREAK SPACE) scores **1.000 / 1.000** on
all 38 types in both arms, as predicted. U+202F is category Zs and `str.isspace()` is True, so
`detect/normalize.py`'s whitespace-run collapse absorbs it exactly as it absorbs U+00A0. A
number below 1.000 here would have meant the collapse is narrower than it claims. It says the
instrument is measuring the layer and not something else.

---

## 3. THE MUTATION GATE AFTER THIS ROUND

`.venv/Scripts/python.exe -m eval.mutation_gate` → **exit 1**, instrument self-check OK
(identity = 1.000 in every cell of both arms, 0 exclusions, 0 exceptions), 70 docx, 3 810
units, 2 629 gradeable auto surfaces, 0 `detect()` exceptions.

| mutation | blind | known | verdict | round |
|---|---:|---:|---|---|
| nbsp | 1.000 | 1.000 | pass | 2 |
| zero_width | 1.000 | **0.991** | pass | 2 |
| soft_hyphen | 1.000 | **0.991** | pass | 2 |
| tabs | 1.000 | 1.000 | pass | 2 |
| double_spaces | 1.000 | 1.000 | pass | 2 |
| line_break_mid | 0.376 | 0.383 | **FAIL** | 2 |
| all_caps | 0.959 | 0.955 | pass | 2 |
| lowercase | 0.967 | 0.963 | pass | 2 |
| no_diacritics | 0.996 | 0.996 | pass | 2 |
| cyrillic_homoglyph | 1.000 | **0.991** | pass | 2 |
| nfd | 1.000 | **0.991** | pass | 2 |
| **nb_hyphen** | **0.941** | **0.941** | **FAIL** | **3** |
| **narrow_nbsp** | **1.000** | **1.000** | pass (control) | **3** |
| **surname_caps** | **0.649** | **0.784** | **FAIL** | **3** |
| **letterspaced** | **0.113** | **0.112** | **FAIL** | **3** |

Round 2's fixes are real and hold: `zero_width` 0.070→1.000, `soft_hyphen` 0.070→1.000,
`cyrillic_homoglyph` 0.355→1.000, `nfd` 0.677→1.000, `tabs`/`double_spaces` →1.000. Three of
the four bold rows in the `known` column (0.991 where blind is 1.000) are R3-A11 and nothing
else; they are a pass only because the overall is surface-weighted.

**Round 2's recommendation to gate the MACRO as well as the overall is now sharper**:
`surname_caps` reads 0.649 overall and 0.912 macro, while `MENO` — 36 % of the corpus's auto
surfaces — is 0.014. The overall is the number that moves; the per-type row is the number that
means something.

---

## 4. EXPECTATIONS THAT WERE WRONG

The four outright falsifications, and one thing I got wrong twice in a row and had to catch
with a control.

**A1 (hyphenated surname) and A2 (apostrophe surname) — predicted DEFECT, measured CLEAN.**
The prediction about `detect/name_anchors.py` was exactly right — `predávajúci Ján Kováč-Nagy`
yields `MENO('Ján Kováč')` from the anchors and `kupujúci Peter O'Brien` yields `MENO('Peter')`
— but `detect/gazetteer.py`'s given-name + surname pairing independently emits the FULL
surface, `MENO('Ján Kováč-Nagy', auto=True)`, and `detect()` is therefore clean. **The rescue
has a precondition I had not seen: the gazetteer must recognise the pair.** Swapping one
Slovak given name for a foreign one breaks it and the predicted partial redaction appears:
`predávajúci Zsolt Kováč-Nagy` → `-Nagy` survives; `kupujúci Seamus O'Brien` → ` O'Brien`
survives. So the correct finding is not "hyphens break names", it is R3-A12: the anchors are
broken for a whole class of letters and the gazetteer is silently carrying them, which means
the anchors' coverage number is not the anchors'.

**A8 (name as a numbered list label) — predicted the worst kind of miss, measured CLEAN.** I
predicted `_at_sentence_start` would see the `.` of `1.` and suppress the bare-name heuristic,
leaving the name neither redacted nor in the review bucket. The first half is true; the
conclusion is not, because the gazetteer emits `MENO('Ján Novák', auto=True)` regardless of
sentence position. Same rescue, same precondition.

**A9 (name inside Slovak quotes `„Ján Novák“`) — predicted a drop from auto to review,
measured auto=True.** The role anchor does die (`Predávajúci: „Ján Novák“` gives the anchors
only a bare-name `auto=False`), and again the gazetteer carries it.

**C1 — predicted "per-glyph placement mangles `get_text()`", measured "only when the advances
disagree with the font metrics".** At 0.85–1.15 tracking MuPDF reassembles the glyphs perfectly
and everything is detected and redacted. The defect starts at ~1.3. The finding is real and is
the worst in the round, but the mechanism is *advance mismatch*, not *per-glyph placement*, and
saying it the first way would have sent a fixer to the wrong place.

**A11 — predicted "any deformation of the list is lost", measured "only the ones the entity
matcher cannot fold, and only when EVERY token is deformed".** NBSP, tab, newline, double
space, fullwidth and NFD in the list are all handled. And a deformation of only ONE token is
rescued — not by matching, but by `detect()`'s containment PROMOTION rule: the clean token
matches, the bare-name heuristic emits the whole span as `auto=False`, and containment lifts it
to `auto=True`.

---

## 5. THREE THINGS THIS ROUND GOT WRONG ABOUT ITSELF — FIXTURE DEFECTS, NOT PRODUCT DEFECTS

Being wrong out loud, per the brief. Each was caught by a control, and the control is the only
reason it was caught.

**F-1. My first A11 fixture used `Wojciech Szczepański` as a "name in no gazetteer". Its
CONTROL — clean text, clean list — FAILED, reporting `ński` as surviving.** That is not the
known-entity defect I was testing; it is R3-A12 (`ń` is not in `_LO`) contaminating the fixture.
How I told them apart: the control is the discriminator. A fixture whose control fails is
measuring something other than the thing it names, and any "defect" it reports is unattributable.
The needle was replaced with `Alessandro Bertolini` (Slovak-safe letters, in no list) and the
control then passed. **The contaminant was itself worth filing** — it became R3-A12.

**F-2. My second A11 fixture hand-typed the deformation into ONE token
(`"Alessandro Berto​lini"`) and reported a HIT — i.e. no defect.** Re-running with the
canonical `MUTATIONS["zero_width"]` applied to the whole entity gave a MISS. The difference is
the containment promotion rule described above. How I told them apart: I stopped hand-typing the
deformed string and used the module's own mutation function, which is deterministic and applies
to every token — and then read `match_entity()` directly, which returned `[(26, 36)]` (one token)
in the first case and `[]` in the second. The `xfail` test now carries a comment saying why both
tokens must be deformed, and a one-token variant was verified to XPASS.

**F-3. My first C1 fixture used exact font advances and reported no defect at all.** The honest
reading at that moment would have been "C1 CLEAN, expectation falsified". Sweeping the one free
parameter instead — tracking from 0.85 to 1.8 — found the boundary. A single-point probe of a
continuous parameter answers a different question from the one asked.

---

## 6. JUDGEMENT CALLS

1. **`surname_caps` is deliberately NOT added to `CASE_DESTROYING`.** That set exists for
   mutations whose damage to a capitalisation-dependent heuristic is INHERENT because the unit
   has no capitalisation signal left anywhere. `surname_caps` keeps the document mixed-case on
   purpose — that is the entire point of it. Recorded as QUESTIONS.md **Q15** with the one-line
   reversal.
2. **`letterspaced` is measured on the DOCX arm even though the defect it models is a PDF-side
   one.** The mutation gate has no PDF arm (round 2, judgement call 1). Expressing the
   deformation as a text mutation lets the existing, instrument-proved harness put a number on
   it; the PDF-side reproduction is separate (C1) and is what establishes that the shape is
   real. Neither alone would be enough.
3. **No existing mutation, test, threshold or detector was modified.** `corpus/mutations.py`
   is append-only; `tests/test_redteam_round3.py` is new; `redteam/FINDINGS_ROUND3.md` and two
   `QUESTIONS.md` entries are the rest. `detect/`, `writer/`, `gui/` and `eval/` are untouched
   by this round — finding and proving was the deliverable.
4. **`detect/*` was being refactored by another agent during this round.** Every detector
   finding was reproduced TWICE, the second pass after that agent had
   edited `registry_refs.py`, `identifiers.py` and `datetime_amounts.py` (their mtimes moved
   between the two passes). Both passes were byte-identical. No transient import error or unrelated test failure is reported
   here as a finding.
5. **B1–B5 are filed against `writer/docx_body.py`, not against the corpus.** Regenerating the
   corpus with Word-shaped packages would make the leak gate catch them, which is the right
   long-term move, but the defects exist independently of whether anything measures them.

---

## 7. WHAT I SUSPECT AND COULD NOT CONFIRM

* **`<w:smartTag>` and `<w:fldSimple>` wrap runs the same way `<w:hyperlink>` does** (they are
  siblings of `w:r` in the CT_P content model), so B2's mechanism should apply to them
  identically. Not built as a fixture — Word 2003-era `smartTag` is rare in files produced
  today, and `fldSimple` is mostly superseded by the `fldChar` run form, which IS a direct
  child and therefore fine. Worth one fixture each when B2 is fixed, since the fix will
  probably be "walk `.//w:r`" and should be verified to cover them.
* **`docProps/thumbnail.jpeg` (round 1, B-2) combines with B1–B5 into something worse than
  either.** A Word-saved `.docx` carries a rendering of page 1 showing the un-redacted text,
  and every shape above means page 1 was partly un-redacted anyway. I could not measure it: it
  needs a real Word-saved file and this project never handles one.
* **Two-column PDFs (C3) came back clean**, but the fixture was a synthetic two-column page
  with short lines. A real journal reprint with justified columns and hyphenation may still
  interleave blocks in `get_text("text")`. Not confirmed either way.
* **`_resolve_partial_overlaps` promotes an `auto=False` survivor when a dropped candidate was
  `auto=True`, but keeps the SURVIVOR's span.** If the dropped candidate's span extended beyond
  the survivor's, the promotion redacts less text than the dropped candidate claimed. I could
  not construct a case where that leaks (the sweep sorts by start then by longest-first, which
  should make the survivor the wider span), but the invariant is not asserted anywhere and a
  crossing overlap from two different views is a new possibility introduced by Amendment 10.
  One property test over `detect()` would settle it.
* **`has_text_layer()` accepts a page whose text is unreadable garbage** (C4 returned True on
  control characters). A stricter predicate — "the extracted text contains some proportion of
  letters" — would let the app REFUSE the C4 class instead of silently producing an unredacted
  file, which is the behaviour context.md §3 promises for a PDF with no text layer. Not filed
  as a defect because it is a design decision, not a bug.

---

## 8. R3-F1 — A TEST THAT FORBIDS THIS ROUND FROM EXISTING (filed, not worked around)

Adding the four mutations turns **5 existing tests red**, and I did not touch them.

```
FAILED tests/test_mutations.py::test_registry_holds_every_required_mutation
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[letterspaced]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[narrow_nbsp]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[nb_hyphen]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[surname_caps]
```

```python
assert set(MUTATIONS) == {          # tests/test_mutations.py:65 — EQUALITY, not superset
    "nbsp", "zero_width", "soft_hyphen", "tabs", "double_spaces", "line_break_mid",
    "all_caps", "lowercase", "no_diacritics", "cyrillic_homoglyph", "nfd",
}
```

The test's own docstring states a SUPERSET invariant — *"A mutation silently missing from
`MUTATIONS` is a column the gate never prints and an attack nobody ran"* — and then asserts
EQUALITY, which additionally forbids anything from ever being added. The second failure is
subtler and worth naming separately: `test_every_mutation_is_registered_under_its_own_function`
reads like a general invariant but resolves `mutate_<name>` through the **test module's**
`globals()`, which is fed by an explicit eleven-name import list at line 27 — so it `KeyError`s
for any mutation the test file does not already import.

`corpus/mutations.py` is therefore append-only in its docstring and frozen in fact. Every
future red-team round hits this on its first new mutation.

**Not worked around.** The brief forbids touching any existing file in `tests/`, and the
standing rule forbids editing a test to make something pass. Reverting the mutations was
rejected: three of the four are the corpus-scale measurement behind R3-A5, R3-A6 and R3-C1.
Filed in `reports/blockers.md` (2026-09-17, state OPEN) with the two-line fix for whoever owns
that file: `==` → `<=` at line 65, and `getattr(corpus.mutations, f"mutate_{name}")` at line 74.

**Rest of the suite, for the record:**
`python -m pytest tests/ -q` → **1361 passed, 5 failed (all the above), 8 skipped,
21 xfailed** in 142 s. The five failures are the only red in the tree and all five are R3-F1.
`python -m pytest tests/test_redteam_round3.py -q` → **6 passed, 21 xfailed, 0 xpassed**.
`python -m eval.mutation_gate` → exit 1 by design, instrument self-check OK, 0 `detect()`
exceptions, all fifteen mutations measured.
