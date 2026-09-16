# QUESTIONS.md — open questions and the default the orchestrator chose

Sprint rule: never block on a question. Every entry here records the question, the
default chosen so work could continue, and how to reverse it if the owner disagrees.

---

## Q1 — Does `strict_checksums` belong in the GUI at all?
**Default chosen:** yes, but collapsed under "Advanced" and OFF.
**Why:** A1 makes checksum-failing identifiers auto-redact. That is right for a law
office (recall over precision), but it removes the only lever a user had to stop the
tool eating a mistyped number. Keeping the v1 behaviour reachable costs one checkbox.
**To reverse:** delete the toggle from the GUI advanced panel; the config field stays.

## Q2 — Are stray redaction outputs in data/synthetic safe to delete?
**Default chosen:** moved, not deleted, to the session scratchpad.
**Why:** six *_anon.* files from an earlier live GUI test were crashing eval.leak_gate
on a missing .gt.json. data/ is gitignored and seed-regenerable, so deleting was
probably safe — but "probably" is not a reason to delete someone else output.
**To reverse:** they are in the scratchpad dir named in status.txt.

## Q3 — ADRESA swallowing PSC and OBEC: one candidate or three?
**Default chosen:** ONE composite ADRESA candidate that covers the whole
`Hlavná 12/A, 040 01 Košice` span; the inner PSC/OBEC candidates are dropped by the
core overlap resolver.
**Why:** the writers slice output by character offsets, so overlapping spans corrupt
the document. One wide span redacts strictly more text than three narrow ones, which
is the recall-over-precision direction. Cost: the report shows [ADRESA_1] rather than
naming the town separately.
**To reverse:** rank PSC/OBEC above ADRESA in CONTRACTS_v11.md §4 and emit the parts.

## Q4 — Unanchored CISLO_OP / CISLO_PASU: match or require an anchor?
**Default chosen:** match unanchored, provided the shape is standalone and
word-boundaried on both ends.
**Why:** recall over precision. `AB123456` standing alone in a Slovak legal document is
overwhelmingly an ID number.
**To reverse:** make both anchor-required, like VODICSKY_PREUKAZ already is.

## Q5 — BIC without an anchor
**Default chosen:** a deliberate PRECISION exception — BIC is emitted only with an
anchor (BIC/SWIFT) or when the country-code position is literally `SK`.
**Why:** a bare 8-letter uppercase run is also an ordinary ALL-CAPS Slovak word, and
the red-team phase deliberately feeds the tool ALL-CAPS documents. Unanchored BIC would
turn every capitalised word in such a document into a redaction.
**This is the one place in v1.1 where precision beats recall, and it is recorded here
because that is a deviation from the governing rule.**
**To reverse:** drop the anchor requirement and accept the ALL-CAPS behaviour.

## Q6 — FAX vs TELEFON on the same digits
**Default chosen:** FAX outranks TELEFON in the precedence tuple.
**Why:** both are auto-redacted, so nothing leaks either way; the choice decides only which
label the report shows. A report that says [FAX_1] where the document says "fax:" is
checkable by the reviewer; one that says [TELEFON_3] is not.
**To reverse:** swap the two entries in detect/core.py _TYPE_PRECEDENCE.

## Q7 — Anchors written without diacritics
**Status: OPEN, handed to the red-team phase rather than patched ad hoc.**
Slovak legal documents are frequently typed without diacritics. Every anchor-required type
(KOD_BANKY, NAZOV_UCTU, CISLO_KLIENTA, FAX, VODICSKY_PREUKAZ, the address anchors, the role
and field-label name anchors) currently matches its anchor WITH diacritics. "kod banky 1100"
therefore does not match while "kód banky 1100" does. RODNE_CISLO is the exception — its
anchor matching is already diacritic-folded.
**Why not patched here:** it is one systematic defect across ~10 modules, not ten separate
bugs. Patching each regex by hand would be error-prone and unreviewable. The fix is one
shared diacritic-folding anchor helper applied uniformly, which is red-team scope because
the red team is already building the missing-diacritics mutation that proves it.
**Measured, not assumed.** Probing each anchor-required type with and without diacritics:
| type | with diacritics | without |
|---|---|---|
| KOD_BANKY | detected | **MISSED** |
| NAZOV_UCTU | detected | **MISSED** |
| CISLO_KLIENTA | detected | **MISSED** |
| FAX | detected | **MISSED** |
| ADRESA (`so sídlom`) | detected | **MISSED** |
| ADRESA (`trvale bytom`) | detected | detected |
| RODNE_CISLO | detected | detected (already folded) |
| CISLO_PASU | detected | detected |

Five types silently lose their anchor when a document is typed without diacritics.
**Severity: HIGH for recall.** Recorded here so it cannot be lost.

(Separately checked and NOT a defect: `VODICSKY_PREUKAZ` appeared to "miss" but is in fact
detected and redacted — it was losing the exact-span tie to `CISLO_OP`/`CISLO_PASU`, i.e. a
label difference, not a leak. Fixed by ranking the anchor-required type first.)

## Q8 — the digit/letter boundary defect (FOUND AND FIXED, recorded because it was a live leak)
**Status: FIXED.** Recorded because it is the kind of defect that silently comes back.
`\b` sits between a word char and a non-word char. A digit and a letter are BOTH word chars,
so `\b\d{8}\b` does **not** match the eight digits in `43235222IBAN`. Every numeric identifier
(IČO, DIČ, IČ DPH, IBAN) was therefore invisible whenever it abutted a letter with no space —
which is exactly what a PDF text layer produces where two layout cells meet, and what a DOCX
table produces when cell text is reconstructed without separators.

Worse than a miss: on `IBAN (chybný)SK22 1111 7955 0033 3133 5578Účet` the IBAN was not matched
at all and the widened RODNE_CISLO pattern claimed the fragment `22 1111 7955` instead — so the
report would have named a rodné číslo that does not exist while the real IBAN leaked.

**Fix:** `(?<!\d)` / `(?!\d)` guards instead of `\b`. Still refuses to split a longer digit run;
no longer suppressed by an adjacent letter. Verified both directions, 170 detect-side tests green.

**Why it was not caught before:** the leak gate redacts through the WRITERS, which reconstruct
text per paragraph and per table cell, so the glued form never arose there. It only appeared
when detection was run over `eval.extract`'s own no-separator concatenation. Two different
strings, two different answers — worth remembering when reading any recall number.

## Q9 — cross-format consistency gate: real corpus pairs vs. a hand-authored fixture
**Default chosen:** `eval/cross_format_gate.py` does NOT run against `data/synthetic`. It
authors its own small matched-pair fixture corpus (6 pairs) directly from
`corpus.docx_builder`/`corpus.pdf_builder`/`corpus.pii.*`, with literal PII content computed
once and placed identically into both builders.
**Why:** `corpus/generate.py::_emit` derives a DIFFERENT RNG seed per format
(`seed*1000 + i*10 + f_idx`), so `kupna_zmluva_000.docx` and `kupna_zmluva_000.pdf` are not the
same logical document today — verified: 53 vs 49 GT rows, almost no surface overlap. Even
re-deriving one shared seed would not fix it: `corpus.docx_builder.DocxBuilder` consumes the
SAME `random.Random` instance for its split-run decision as the template uses for content, so
the two builders' draw counts diverge as soon as the first PiiSpec is placed. This is a
`corpus/` defect, out of scope for this eval/tests-only round (task rules: read `corpus/`
only). Reported to the orchestrator in the same-session final message.
**To reverse:** once `corpus/generate.py` derives one seed per logical document AND
`DocxBuilder`'s internal RNG is decoupled from the template's content RNG (two independent
`random.Random` instances), replace `eval/cross_format_gate.py`'s `_author_pair`/`_content`
with a loader over `data/synthetic/*.docx` / `*.pdf` pairs by shared index, keeping
`judge_pair` (the actual comparison logic) unchanged — it already takes GT dicts + extracted
text and does not care where they came from.

## Q10 — perf report memory instrument: tracemalloc instead of psutil
**Default chosen:** `eval/perf_report.py` measures peak memory with `tracemalloc` (stdlib),
labelled explicitly as Python-heap only, not process RSS.
**Why:** `psutil` is not installed in `.venv` and is not in `requirements.txt`; adding a new
dependency is out of scope for an eval-only round. `tracemalloc` needs no install and the
report says plainly what it does NOT capture (native allocations in `lxml`/`python-docx`'s
zip writer/PyMuPDF).
**To reverse:** add `psutil` to `requirements.txt`, then swap `_measure()` to poll
`psutil.Process().memory_info().rss` (e.g. from a background thread while the redaction call
runs) for a true peak-RSS number.


## Q11 — the normalization layer does NOT fold case
**Default chosen:** `detect/normalize.py` normalizes format characters, homoglyphs,
whitespace runs, NFKC compatibility forms and NFD→NFC. It does **not** case-fold.
**Why:** case-folding the text globally would not make the detectors case-insensitive — it
would destroy the only signal several of them have. `detect/orgs.py` keys on a CAPITALIZED
token beside a legal-form suffix and the bare-name heuristic in `detect/name_anchors.py`
does the same; on lower-cased text those rules stop being "find a name" and become "match
everything". The `all_caps` / `lowercase` classes are being fixed per anchor site instead,
where the difference between "an anchor word" (case carries nothing) and "evidence" (case is
the whole claim) is visible in the code.
**To reverse:** add a `casefold` step to `normalize()` and delete the capitalisation
requirement from `detect/orgs.py` and `name_anchors.py`'s `_CAP`, replacing it with some
other evidence — there is currently none, which is the point.

## Q12 — a wrap is rejoined only inside a run of CAPITALS AND DIGITS
**Default chosen:** `detect()`'s second view (`normalize(text, join_wrapped=True)`) deletes a
line break between two alphanumeric runs only when NEITHER run contains a lowercase letter.
A wrap inside a mixed-case or lowercase token is left as a line break, and a whitespace
character that is not a line break (a TAB, an NBSP, a space) inside a token is never deleted
at all.
**Why:** joining on any alphanumeric pair fuses the last word of every wrapped line with the
first word of the next. Measured on a two-line fixture it produced the auto=True MENO surface
`Novák\nRodne` — a party's surname welded to the label starting the following line — which
would have redacted that label every time a name fell at a line end. Restricting to
capitals-and-digits keeps the identifiers a renderer can break (IBAN, BIC, VIN, EČV, spisová
značka, account numbers) and excludes ordinary Slovak words. Deleting a plain SPACE between
digits was rejected for the same reason in the other direction: `\d{8}` would then match
"v rokoch 2020 2021" and auto-redact a date range out of every contract that mentions one.
**Cost, and where it is visible:** the `line_break_mid` class cannot reach 1.000 on types
whose surfaces contain lowercase. That is not hidden — `eval/mutation_gate.py` grades it
against the same 0.95 threshold every run.
**To reverse:** relax `detect/normalize.py:_is_identifier_run` (drop the lowercase test to
join any alphanumeric pair, or extend `_WRAPPED_TOKEN_RE` to whitespace runs without a line
break) and then re-measure per-type PRECISION — that is the number this choice is trading.
