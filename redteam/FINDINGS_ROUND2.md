# Red-team findings, round 2 — the DETECTORS

**Target:** `detect/*` — whether a PII surface written in a slightly unusual way is still
**found**. Round 1 (`redteam/FINDINGS.md`) attacked `eval/extract.py`, the surfaces the leak
gate can *read*. This round attacks the other half of the same premise.

**Premise under attack:** every gate in this repo grades the detectors against text authored
by `corpus/templates/*.py`, which writes ONE spelling of each surface. A detector that only
matches that spelling passes the whole suite, passes the dual leak gate at zero, and leaks on
the first real document that was typed on a different keyboard, wrapped at a different column,
or pasted from a bank's website.

**Result: 11 mutations run, 1 CLEAN, 10 DEFECT, 0 INHERENT.**

| # | mutation | blind | known | verdict |
|---|----------|------:|------:|---------|
| 1 | `nbsp` | **1.000** | **1.000** | **CLEAN** |
| 2 | `zero_width` | 0.070 | 0.182 | DEFECT |
| 3 | `soft_hyphen` | 0.070 | 0.213 | DEFECT |
| 4 | `tabs` | 0.745 | 0.757 | DEFECT |
| 5 | `double_spaces` | 0.779 | 0.777 | DEFECT |
| 6 | `line_break_mid` | 0.113 | 0.123 | DEFECT |
| 7 | `all_caps` | 0.446 | 0.590 | DEFECT |
| 8 | `lowercase` | 0.391 | 0.536 | DEFECT |
| 9 | `no_diacritics` | 0.759 | 0.812 | DEFECT |
| 10 | `cyrillic_homoglyph` | 0.355 | 0.418 | DEFECT |
| 11 | `nfd` | 0.677 | 0.720 | DEFECT |

Gate threshold **0.95**. `python -m eval.mutation_gate` → **exit 1**, 20 of 22 mutation-arms
below threshold, 240 flagged cells (blind) / 238 (known), 0 `detect()` exceptions.

Orchestrator's prior expectations, stated before the run so they could be falsified:
`no_diacritics` / `cyrillic_homoglyph` / `zero_width` DEFECT — **confirmed**. `nbsp` CLEAN —
**confirmed**. **`line_break_mid` CLEAN — FALSE. This is the most valuable result of the round.**

---

## 0. How the number was produced, and how it was proved before it was read

**The unit is the unit production uses.** `writer/docx_body.py` calls `detect()` ONCE PER
`<w:p>` — body paragraphs, table cells, header/footer paragraphs, VML textboxes, and the
footnotes / endnotes / comments OPC parts. `eval/mutation_gate.py` rebuilds exactly those
units, accepting tracked revisions first. Measuring over `eval.extract`'s whole-document
concatenation would grade a string the writers never see — QUESTIONS.md Q8 records what
happens when those two are confused.

70 DOCX → 3 730 units → **2 559 gradeable `auto_redact` surfaces**. 199 surfaces are excluded
up front as never reaching `detect()` (metadata, blanked by POSITION; and
`tracked_change_del`, removed before detection). Grading those would score the metadata
scrubber as a detector failure.

Clean auto-recall: **0.935** blind / **0.943** known.

**Coverage predicate: leak-faithful UNION coverage.** A surface counts as detected when EVERY
CHARACTER is inside SOME `auto=True` candidate — not inside one candidate. Both writers
replace each span independently, so a name split into two adjacent candidates is still
completely removed. Verified before adopting: on clean text union and single-candidate
coverage disagree on **zero** of 2 559 surfaces, so the change cannot flatter the baseline.

**Two arms, because one number would hide the finding.** `blind` = `detect(unit, [])`,
isolating the pattern/anchor/gazetteer detectors. `known` = with the user's entity list,
production-faithful. The gate fails if EITHER arm is below threshold.

**Instrument proof (G0), run before any number is read.** `instrument_self_check()` runs the
IDENTITY mutation first and requires robustness exactly 1.000 in every cell of both arms, 0
exclusions, 0 exceptions, `paired == gradeable`. It is the only mutation whose answer is known
a priori, so it is the only thing that separates a detector defect from a harness bug. On
failure the gate exits 2 and prints nothing else.

**Pairing.** Every mutation is character-local or token-local-and-start-anchored, so
`s in t` implies `mutate(s) in mutate(t)`. The gate re-checks containment per pair at run
time; a failing pair is excluded from BOTH numerator and denominator and counted. Measured
exclusions across all 11 mutations × 2 arms: **0**.

**The positive control.** `nbsp` rewrites EVERY SPACE IN EVERY DOCUMENT — the most invasive
whitespace change in the set — and scores 1.000 on all 36 types in both arms. A harness that
was merely destructive could not produce that row.

---

## 1. Why there are no INHERENT verdicts

The brief's own hedge named the expected inherent case: *"`all_caps` destroys the
capitalisation the bare-name heuristic legitimately depends on"*. True of the heuristic,
FALSE of the number being gated: `_bare_names` emits `auto=False`, and this gate grades the
`auto_redact` class by AUTO coverage.

**Measured, not argued** — clean baseline re-run with `_bare_names` stubbed to `[]`:

| bare-name heuristic | clean auto-recall | auto hits |
|---|---|---|
| ON | 0.9347 | 2392 / 2559 |
| OFF | 0.9336 | 2389 / 2559 |

**3 surfaces, 0.13 %.** The inherent mechanism can account for at most 0.13 % of a drop from
1.000 to 0.446. It does not explain the number.

The discriminator — same sentence, same mutation, same evidence:

```
"Meno a priezvisko: Ján Novák"   -> MENO('Ján Novák', auto=True)
"MENO A PRIEZVISKO: JÁN NOVÁK"   -> MENO('JÁN NOVÁK', auto=True)     <-- SURVIVES
"predávajúci Ján Novák"          -> MENO('Ján Novák', auto=True)
"PREDÁVAJÚCI JÁN NOVÁK"          -> NOTHING                          <-- DIES
"JUDr. Ján Novák"                -> MENO('Ján Novák', auto=True)
"JUDR. JÁN NOVÁK"                -> NOTHING                          <-- DIES
```

Same document, same anchor word, same name — one detector finds it and two do not. Defect.

---

## 2. The defects, ranked

### R2-1 · `line_break_mid` — 0.113 / 0.123 — SEVERITY 1. THE PRIOR EXPECTATION WAS WRONG.

Expected CLEAN, because `_AWS = r"\s+"` in `detect/office_refs.py` was written precisely for
it after a corpus PDF leaked a client number. It is not clean.

**Decomposition**, each half run separately over the same 2 559 surfaces (blind):

| half | overall | what it is |
|---|---:|---|
| newline between words only | **0.745** | the PDF line wrap |
| newline inside long runs only | **0.254** | a wrap inside an unbreakable token |
| both (the shipped mutation) | **0.113** | |

The between-words half scores **0.745 — identical to `tabs`**, and that identity IS the
finding: `_AWS` fixed the separator BETWEEN THE WORDS OF AN ANCHOR and nothing else. Every
other separator in `detect/` is still `[ \xa0]` or a literal space — it accepts a space and an
NBSP and rejects a tab, a newline, or two spaces.

**It still bites the very type the fix was written for.** `CISLO_KLIENTA` = 0.000:

```
"Číslo klienta: KL-99321"      -> CISLO_KLIENTA('KL-99321', auto=True)
"Číslo klienta:\nKL-99321"     -> NOTHING            # wrap after the colon
"Číslo klienta:\tKL-99321"     -> NOTHING            # tab-aligned DOCX table cell
```

The anchor-INTERNAL separator is `\s+` (fixed); the **anchor→value** separator is still
`[ \xa0]*`. A wrap one word later than the one measured in `zmluva_v11_034.pdf` leaks the same
client number again.

Same shape: `FAX` 0.000, `KOD_BANKY` 0.000, `NAZOV_UCTU` 0.600, `TELEFON` 0.457, `DATUM`
0.000, `SUMA` 0.243, `IBAN` 0.000, `LV`/`PARCELA`/`ORSR_VLOZKA` 0.000, `EMAIL` 0.086,
`ADRESA` 0.000, `MENO` 0.104.

**Fix** — one edit per module, not one line. Separator constants live in
`detect/addresses.py`, `documents.py`, `office_refs.py`, `name_anchors.py`,
`datetime_amounts.py`, `registry_refs.py`, `identifiers.py`, `gazetteer.py`, `expansion.py`.
Replace the STRUCTURAL separator class `[ \xa0]` with `[^\S\n\r]` (any horizontal whitespace,
tab included) and the ANCHOR-INTERNAL and ANCHOR→VALUE separators with `\s`.
**Do NOT widen value-capture terminators** — `[^\n\t]+?` and the `2+ spaces = column gap` rule
must keep meaning "end of line / end of cell", or `NAZOV_UCTU` will swallow the next column.

Realism: a PDF text layer wraps on every page; a DOCX table cell is tab-aligned in every
form-style template. **This is the deformation the pipeline meets most often.**

### R2-2 · `no_diacritics` — 0.759 / 0.812 — SEVERITY 2. Q7 CONFIRMED AND INCOMPLETE.

QUESTIONS.md Q7 measured five ANCHOR-REQUIRED types and proposed one shared folding helper.
Necessary, **not sufficient** — the damage extends to two populations Q7 does not mention:

| population | types (blind) | Q7 covers it? |
|---|---|---|
| anchor-required | `CISLO_KLIENTA` 0.000, `KOD_BANKY` 0.000, `STATNA_PRISLUSNOST` 0.000, `SUPISNE_CISLO` 0.000, `CISLO_BYTU` 0.000, `VODICSKY_PREUKAZ` 0.100, `POSCHODIE` 0.300, `NAZOV_UCTU` 0.800 | yes |
| **registry references** | `LV` 0.000, `PARCELA` 0.000, `ORSR_VLOZKA` 0.000 | **no** |
| **the gazetteer** | `OBEC` 0.329, `KATASTER` 0.286, `MENO` 0.843 | **no** |

```
"zapísané na LV č. 1234"   -> LV('LV č. 1234', auto=True)
"zapisane na LV c. 1234"   -> NOTHING          # the pattern contains a literal "č."
"obec Košice"              -> OBEC('Košice', auto=True)
"obec Kosice"              -> NOTHING          # stem("Kosice") != stem("Košice")
```

**The realistic user-mismatch arm, which neither gated arm shows.** The `known` arm
de-accents the user's entity list too — optimistic; a lawyer whose DOCUMENT is de-accented
still types "Novák" with the accent:

| document de-accented, user's list … | overall recall | robustness |
|---|---:|---:|
| de-accented too (as gated) | 0.7655 | 0.812 |
| **keeps its diacritics (realistic)** | **0.7382** | **0.783** |

**70 further names missed**, purely because the two spellings cannot meet.

**Fix, three parts:** (1) one shared diacritic-folded anchor matcher — Q7's proposal;
(2) build AND query every gazetteer stem index through a folded key, and fold the
known-entity query the same way; (3) `registry_refs.py`'s literal `č.` accepts `[čc]`.
Part 2 does not weaken the `-sk-/-ck-` discriminator — that is a consonant INFIX, not a
diacritic.

### R2-3 · `tabs` 0.745 / `double_spaces` 0.779 — SEVERITY 3. Same root as R2-1.

`double_spaces` is two mechanisms, one a real design tension:
* **(a) fixed-width separators cannot absorb a second space.** `IBAN` 0.000
  (`SK\d{2}(?: ?\d{4}){5}` — `" ?"` is ONE optional space), `CISLO_BYTU` 0.000,
  `SUPISNE_CISLO` 0.000. Plain defect; the separator should be `+`-quantified.
* **(b) "2+ spaces = a column gap that TERMINATES the value".** Doubling spaces inside a value
  truncates it. Genuine tension — the rule stops a flattened table row letting a value swallow
  the next column. The right fix is to stop INFERRING column boundaries from space runs and
  have `writer/docx_body.py` pass the cell boundary it already knows. A design item.

### R2-4 · `zero_width` 0.070 / `soft_hyphen` 0.070 — SEVERITY 4. Largest damage.

**34 of 36 types below the gate**, including every checksum-bearing identifier.

```
"IČO: 43235222"          -> ICO('43235222', auto=True)
"IČO: 43​235222"    -> NOTHING
"r.č. 850315/0018"       -> RODNE_CISLO(..., auto=True)
"r.č. 85​0315/0018" -> NOTHING
```

Both characters are Unicode category **Cf (format)** — invisible in Word, in Acrobat, and to
the reviewer.

**The fix is NOT one line, and saying so matters.** "Do what `detect/core.py` does for NBSP"
does not work, and the reason is in that very comment: the NBSP fix is safe BECAUSE it is
1 character for 1 character, so every offset is preserved and both writers can still slice by
them. Deleting a zero-width character is 1→0 and shifts every later offset; replacing it with
a space is 1→1 but `"43 235222"` still does not match `\d{8}`.

The correct fix is an **offset-mapped normalization** in `detect()`: build a stripped copy
plus an `index → original index` array, detect on the stripped copy, map every candidate's
start/end back. ~15 lines, one place, all detectors benefit. The same machinery fixes R2-7.

Realism: bank portals insert U+200B as soft break opportunities inside long unbreakable
strings — an IBAN, an account number — and a lawyer pastes "the number from the bank's
website" straight into a filing. U+00AD is Word's own optional hyphen and automatic
hyphenation. `eval/extract.py` already records that PyMuPDF renders a hyphen as U+00AD in a
PDF text layer, so this is a character **the pipeline already meets today**.

### R2-5 · `all_caps` 0.446 / `lowercase` 0.391 — SEVERITY 5.

Three causes: (1) case-sensitive VALUE classes in the name anchors — the role and title
anchors are `(?i:)` on the ANCHOR WORD and case-SENSITIVE on the VALUE, so `MENO` is 0.014
under both; (2) case-sensitive literals in shape patterns (`JUDr\.`, the court agendas
`Cb|Ro|Er`, `Sk`, the `[A-Z]` classes in IBAN/IC_DPH/VIN/ECV/CISLO_OP/CISLO_PASU, the URL TLD
list); (3) the Amendment-6 gazetteer token guard.

For (3) the evidence the gazetteer actually relies on is the STEM INDEX, which still matches
(`stem("KOŠICE") == stem("Košice")`). Only the precision guard rejects it. A document-level
"is this text predominantly single-case?" test resolves it without re-admitting `VIN`-as-a-
street. **DEFECT with a named precision tension**, not inherent.

### R2-6 · `cyrillic_homoglyph` 0.355 / 0.418 — SEVERITY 6. Rare, trivial, invisible.

```
"predávajúci Pavol Novák" -> MENO('Pavol Novák', auto=True)
"predávajúci Pаvоl Nоvák" -> NOTHING          # U+0430, U+043E
"jan.novak@advokat.sk"    -> EMAIL('jan.novak@advokat.sk', auto=True)
"jаn.novak@advokat.sk"    -> EMAIL('.novak@advokat.sk', auto=True)   # SILENTLY TRUNCATED
```

The EMAIL row is the sharpest: the candidate is not lost, it is **silently shortened**, so the
writer redacts `.novak@advokat.sk` and leaves `jаn` standing next to it in the output.

**Fix, and this one IS offset-safe:** each homoglyph maps to exactly one Latin character, so a
confusable-folding `str.translate` alongside the NBSP replacement is 1:1 and preserves every
offset. Note `NFKC` does **not** do this; it needs an explicit confusables table.

### R2-7 · `nfd` 0.677 / 0.720 — SEVERITY 7. The cleanest defect in the set.

NFC and NFD are **canonically equivalent** — `normalize("NFC", mutated)` restores the original
exactly. No information is destroyed and the two render identically. **Any loss here is a pure
defect with no precision trade-off whatsoever.**

**The positive control that shows what the fix looks like.** `RODNE_CISLO` is **1.000** under
`nfd`, because `detect/identifiers.py::_ascii_fold` runs NFKD + drop-combining on the anchor
window before testing it. That is the architectural lesson of the whole round:

> **Fold for anchor TESTS (a boolean over a window — no offsets involved, fold freely).
> Normalize with an offset map for value MATCHING (offsets are sliced by the writers).**

---

## 3. CLEAN

### `nbsp` — 1.000 / 1.000, all 36 types, both arms
The round-1 fix holds under the most invasive whitespace rewrite in the set. Locked by
`test_nbsp_mutation_loses_nothing` over 11 hand-built fixtures.

---

## 4. Things found FALSE or inconsistent in the project's own documents

**C-1 · CONTRACTS_v11.md §12 marks vyhláška clause (f) covered by `NAZOV_BANKY`. There is no
detector.** It appears only in the precedence tuple and the registry test. CHECKPOINTS.md is
honest about it, so this is an inconsistency between two documents — but §12 is the
COMPLETENESS AUTHORITY and its table over-reports its own coverage. Registering a type in the
precedence tuple satisfies post-condition 4; it does not make anything detect it.

**C-2 · `ULICA` has a detector and ZERO corpus coverage.** No `.gt.json` contains a single
`ULICA` entry, so it is graded by no gate, including this one. Round 1 states the principle:
*"an excluded type is an UNTESTED type"*. A type absent from the corpus is excluded just as
effectively and less visibly. Related: fourteen v1.1 types appear in **10 of 70** documents
each (`zmluva_v11` only), so several rows of the matrix move in steps of 0.1 — stated so
nobody reads a 0.700 on those rows as a precise fraction.

**C-3 · CONTRACTS_v11.md §8's "imports only" clause is false for `detect/gazetteer.py`**,
which also imports `functools`, `json`, `os`, `sys`. Benign, but §8 is the clause a future
round would be held to.

**C-4 · CHECKPOINTS.md is stale on the gazetteer.** It says *"ORG, OBEC, KATASTER and ULICA
still score 0%"*. Measured on the current tree: `OBEC` clean auto-recall **1.000** (70/70),
`KATASTER` **1.000** (140/140). Only `ORG` and `ULICA` are still at zero.

**C-5 · Amendment 6 records a guard without its cost.** The `≥3 chars / initial capital /
contains a lowercase letter` rule is why OBEC and KATASTER go to 0.000 under both case
mutations. The amendment records the collisions the guard prevents and not the population it
excludes — "every place name in a single-case document".

---

## 5. Judgement calls made in this round

1. **DOCX only; no PDF arm.** The PDF writer's unit is the page and it applies its own U+00AD
   normalization before `detect()`, so a PDF arm would measure a different pipeline. Cost: a
   PDF-only normalization defect is invisible to this gate.
2. `cyrillic_homoglyph` includes the UPPERCASE homoglyphs, which the brief's list does not.
3. `line_break_mid` is the WORST CASE (a break at every opportunity), not one break — the
   question is binary, and a single random break would answer it with noise. The
   decomposition in R2-1 is what makes the aggregate attributable.
4. `tabs` and `double_spaces` rewrite every space: unrealistic as a whole-document state, but
   the mechanism they isolate is exact.
5. **The gate fails on both arms, and the CASE_DESTROYING mark annotates but never exempts.**
   A gate that excuses its own failures is not a gate.
6. Robustness prints `--`, not 0.000, when clean recall is 0. A zero-denominator ratio is an
   unanswerable question; printing 0.000 would invent a defect.
7. **The overall is surface-weighted and `MENO` is 37 % of it.** A mutation destroying five
   rare types while sparing MENO would still read above 0.95. The gate is the brief's
   (overall), unchanged; the **macro** (unweighted per-type mean) is printed beside it and is
   worse for every mutation except `nbsp` and `all_caps`.
   **Recommendation: gate the macro as well as the overall.**
8. The `known` arm mutates the user's entity list — the optimistic reading, labelled as such;
   the realistic mismatch is measured separately in R2-2 and is worse.

---

## 6. Reproduction

```
python -m eval.mutation_gate            # full table, both arms, exit 1 by design
python -m pytest -q tests/test_mutations.py
```

Files added by this round: `corpus/mutations.py`, `eval/mutation_gate.py`,
`tests/test_mutations.py`, this file. `detect/`, `writer/`, `gui/`, `eval/extract.py`,
`eval/leak.py`, `eval/leak_gate.py` and the corpus are **unmodified by this round** — finding
and proving was the deliverable. No corpus regeneration is needed.
