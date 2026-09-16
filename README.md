# Slovak Legal Document Anonymizer

Desktop application for a 6-person Slovak law office. Removes personal and identifying data
from legal documents entirely on-device — no cloud, no network calls, no telemetry. Full
background and design rationale: `context.md`. Frozen v1.1 interfaces: `CONTRACTS_v11.md`.

## What it does

- Takes `.docx` and `.pdf` files (digital-born, with a text layer) and produces a redacted
  copy with consistent in-document labels (`[MENO_1]`, `[RODNE_CISLO_1]`, …), never a mapping file, and
  never touching the original.
- Detection runs in three layers: deterministic regex + checksum identifiers, a bundled
  gazetteer (municipalities, streets, cadastral areas, given names, surnames), and
  user-supplied known entities (the lawyer types the parties' names/addresses up front — the
  single highest-recall input in the system). A fourth bucket, low-confidence candidates, goes
  to human review instead of being auto-redacted.
- Produces a report per document listing every redaction, plus a "near miss, not redacted"
  section, so the human review step is checkable against the document rather than a blind
  trust exercise.
- Governing rule: **recall over precision**. Every ambiguous detection decision resolves
  toward redacting, not toward leaving text alone. A false positive costs the reviewer a
  two-second un-tick; a false negative is a data breach.

## What it explicitly does NOT do

- **Scanned documents / images.** The app works on the text layer only. A PDF with no
  extractable text is refused outright, with a clear message — it will not silently hand back
  an unredacted copy dressed up as anonymized.
- **Signatures and stamps (podpis / pečiatka).** These are images, not text; the app cannot
  see them and leaves them in place. Deferred to v2. The office has been told this in writing
  (`office_note.md`).
- **Vyhláška MS SR č. 482/2011 Z. z. clause (i) — utajované informácie a obchodné tajomstvo
  (classified information / trade secrets).** This is the authoritative basis for the type list
  the tool implements (the clause-by-clause mapping is `CONTRACTS_v11.md` §12), and clause (i)
  is declared **permanently out of scope**: it is defined by MEANING, not by any surface
  pattern, so no regex, checksum, or gazetteer can decide that a given sentence discloses a
  trade secret. A tool that quietly skipped this clause while claiming to implement "the
  vyhláška list" would misrepresent its own coverage — the human reviewer is the only thing
  that handles clause (i), on every document.
- ML-based NER (deferred to v2 — see `context.md` §6 for why v1 ships without it).
- Any format other than `.docx` / `.pdf`, and any network functionality whatsoever.

## Install and run

```
uv venv
uv sync            # or: uv pip install -r requirements.txt
.venv\Scripts\python.exe -m gui
```

Fully offline by design — the app must run with the network adapter disabled.

## Build (PyInstaller)

```
.venv\Scripts\python.exe -m PyInstaller anonymizer.spec --noconfirm
```

Produces a one-folder build at `dist/Anonymizer/Anonymizer.exe`.

**WARNING — verify before shipping a build.** `detect/gazetteer_data/*.json` (municipalities,
streets, cadastral areas, given names, surnames, stoplist) are plain data files. PyInstaller's
import analysis cannot see them; they are bundled only because `anonymizer.spec` names them
explicitly. If that line is ever dropped, mistyped, or defeated by a path change, the frozen
app still starts, still scans, still writes a redacted document and a report — and silently
stops matching every place name and personal name in the country. There is no crash and no
empty output, so nothing about running the app tells you this happened. After every build,
confirm by hand that `dist\Anonymizer\detect\gazetteer_data\` exists and holds the `.json`
files (6 at last count: `obce.json`, `ulice.json`, `katastralne_uzemia.json`,
`first_names.json`, `surnames.json`, `stoplist.json`). `detect/selfcheck.py` also checks this
at startup and refuses to scan if the data is missing or suspiciously small — but that is the
app protecting itself at runtime, not a substitute for checking the build.

## Running the gates

All commands below were run against this checkout to confirm they start; see each module's
own output/`--help` for details.

```
.venv\Scripts\python.exe -m eval.leak_gate            # the killer test: greps every redacted
                                                        # output for every ground-truth PII string
                                                        # across every extractable surface. Zero
                                                        # leaks is non-negotiable (context.md §8.1).
.venv\Scripts\python.exe -m eval.mutation_gate         # detection-robustness gate (red team round 2):
                                                        # can a detector still find PII spelled with
                                                        # an NBSP, a line wrap, no diacritics, etc.
.venv\Scripts\python.exe -m eval.cross_format_gate     # same logical document as .docx and .pdf
                                                        # must yield the same hit set. NOTE it authors
                                                        # its own matched fixtures: data/synthetic's
                                                        # same-index .docx/.pdf are NOT the same
                                                        # document (QUESTIONS.md Q14).
.venv\Scripts\python.exe -m eval.precision_report      # per-type precision, REPORT ONLY — this
                                                        # never gates; recall over precision is the
                                                        # governing rule and a low number here can be
                                                        # the policy working as designed.
.venv\Scripts\python.exe -m eval.perf_report           # time/page, and peak PYTHON-HEAP memory
                                                        # via tracemalloc -- NOT process RSS; psutil
                                                        # is not a dependency (QUESTIONS.md Q10).
.venv\Scripts\python.exe -m eval.run --corpus <dir-with-gt-json> --redacted <dir>
                                                        # the general harness (per-entity-type
                                                        # recall, context.md §8.2).
```

As of this writing the leak gate is **not** green: 20 leaks, all `type=ULICA` (10 `.docx` +
10 `.pdf`), and the mutation gate is failing on `line_break_mid` by design (0.376, threshold
0.95) — both are open, known, and tracked in `redteam/FINDINGS_ROUND2.md` and `status.txt`.
Do not take a stale "PASS" claim anywhere in this repo's history at face value; run the gate.

## Regenerating the synthetic corpus

Real client documents are never used for development or testing (`context.md` §7 — this is
non-negotiable). The corpus is synthetic, seed-deterministic, and gitignored:

```
.venv\Scripts\python.exe -m corpus.generate --n 70 --out data\synthetic --seed 42 --formats docx,pdf
```

(`--n 70`, not 60 — there is a seventh document type, `zmluva_v11`, that seeds every v1.1 type.)

## Gazetteer data and licensing

Every list bundled under `detect/gazetteer_data/*.json` is derived from a public source with
its licence recorded in `LICENSES.md`: Register adries obce and ulice (Ministerstvo vnútra SR,
**CC0 1.0**), katastrálne územia (ÚGKK SR codelist CL000026, **CC BY 4.0** — attribution:
*"Contains data from ÚGKK SR, codelist CL000026, licensed under CC BY 4.0."*), given names
(name-day calendar + a names-generator corpus, **MIT** / **CC0 1.0**), and surnames (**CC0
1.0**). Name lists derived from the Facebook data breach were considered and explicitly
rejected — see `LICENSES.md` for the reasoning. Regenerate the derived JSON with:

```
.venv\Scripts\python.exe -m tools.build_gazetteer
```

## Recall over precision

The governing rule for every ambiguous detection decision in this codebase (`context.md` §6).
When a detector cannot be sure whether something is PII, it redacts it or routes it to human
review — it never silently leaves it in the text. Justification: an over-redaction costs the
reviewer a two-second un-tick; an under-redaction is a confidentiality breach for a law office
whose entire reason for using this tool is to avoid exactly that. This is also why the tool
never claims a document is "clean" — it produces a report of what it changed and what it was
unsure about, and the human review step is structural, not a disclaimer nobody reads.
