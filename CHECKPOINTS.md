# CHECKPOINTS.md — one paragraph per phase boundary, with the gate numbers

Written after Phase A, C and E per the sprint brief. Numbers here are ones the
orchestrator re-ran itself; a number from a subagent report is never recorded here.

---

## Sprint baseline — 2026-09-16, HEAD 6b956d8
Re-verified before any v1.1 change was made. Suite: **358 passed, 8 skipped, 0 failed**.
Dual leak gate: **PASS** — 60 docx + 60 pdf redacted, text_layer=0, scrub=0, other=0,
Class A (OBEC/KATASTER/ORG) excluded as genuinely undetectable in v1. One pre-existing
fragility was fixed before starting: eval/leak_gate.py hard-crashed when any file
without a .gt.json sat in the corpus directory, which six stray *_anon.* outputs from an
earlier live GUI test were doing. The gate now skips GT-less files and prints their
names, so it degrades to reduced-but-visible coverage instead of a traceback.

## Phase A + B closed — 2026-09-16

**What changed.** A1 demoted the checksum from a filter to a tag: `Candidate` and every
ground-truth entry now carry `checksum: "valid"|"invalid"|"n/a"`, and a shape-matched
RČ/IČO/IBAN/legacy-account is auto-redacted *whatever* its checksum says, with
`DetectConfig(strict_checksums=True)` restoring the v1 review-bucket behaviour. A2 fixed the
one defect the office actually reported: the pre-1954 nine-digit rodné číslo. B added sixteen
deterministic types across three new modules (addresses, identity documents, bank/office
references), and `detect()` gained generalised overlap resolution because composite types like
ADRESA now routinely nest and cross other spans — and both writers slice output by character
offsets, so an unresolved overlap corrupts the document rather than merely mislabelling it.

**Gate numbers, all re-run by the orchestrator, none taken from a subagent report.**
Detect-side suite **273 passed**. R0 regression suite **20 passed**. Dual leak gate after
wiring every new detector and regenerating the corpus: **70 docx + 70 pdf, text_layer=0,
scrub=0** — no real leak. The gate's `other` count is not yet zero: the red-team round's new
deep surfaces (`raw_bytes`, `pdf_objects`, `xml_attributes`) report six KOD_BANKY matches which
I investigated individually and confirmed are FALSE POSITIVES — the GT surface is the four
characters `0200` and every hit is inside a font panose/signature hex blob, with the body text
verifiably clean. That is a measurement problem, not a redaction problem, and it is being fixed
where it belongs (an attributability rule on opaque surfaces) rather than by excluding the type.

**Ground truth moved with the policy**, which matters more than it sounds: 363 checksum-invalid
surfaces moved out of the review class into the auto class, so per-type recall now *scores*
them. Had the corpus not moved, the gates would have kept rewarding the tool for leaving them
alone.

**Three defects were found by the process rather than by testing the happy path.**
(1) My own contract told the implementer to delete the BANKOVY_UCET containment suppressor;
that would have made `strict_checksums` a silent no-op for every legacy account number. The
round refused, I re-verified it independently, and the contract was retracted — Amendment 2.
(2) FAX and VODICSKY_PREUKAZ were losing their report labels to TELEFON and CISLO_OP on
exact-span ties; anchor-required types now outrank shape-only ones. Nothing leaked either way,
but a report that mislabels what it removed is not checkable against the document.
(3) The digit/letter boundary defect: `\b` does not sit between a digit and a letter, so
`\b\d{8}\b` never matched `43235222IBAN`. Every numeric identifier was invisible whenever it
abutted a letter with no space — which is exactly what a PDF text layer produces where two
layout cells meet. Worse, on one real corpus string the IBAN went undetected while the widened
RČ pattern claimed a fragment of it, so the report would have named a rodné číslo that does not
exist while the real IBAN leaked. Fixed with `(?<!\d)`/`(?!\d)` guards.

**Still open and honest about it:** five anchor-required types miss when a document is typed
without diacritics (measured, QUESTIONS.md Q7); ORG, OBEC, KATASTER and ULICA still score 0%
because their detectors are the next round; and NAZOV_BANKY — a genuine gap the Vyhláška
482/2011 mapping exposed — is registered but not yet built.

## Phase C + E closed — 2026-09-16

**Gate numbers, all re-run by the orchestrator.** Full suite **889 passed, 8 skipped, 0
failed**. Dual leak gate **PASS** — 70 docx + 70 pdf, `text_layer=0 scrub=0 other=0` — and
this time with OBEC and KATASTER *gated* rather than excluded, so the gazetteer, the largest
single addition of the sprint, is actually measured. Demo: 41 auto + 2 review (docx), 38 + 2
(pdf), zero leaks in either output against 23 PII needles.

**Phase C** landed the title/role/field-label anchors, the bare-name review heuristic,
known-entity expansion and the gazetteer (2842 obce, 12000 ulice, 3416 katastrálne územia,
481 given names, 1169 surnames — all CC0/CC-BY/MIT, provenance in LICENSES.md).

**Phase E was where a gate turned out to have quietly stopped working.** Policy A1 moved
checksum-invalid identifiers into the auto bucket, which emptied `should_flag` — so
`FLAG_SURVIVAL_MIN` passed vacuously and, worse, no baseline could trip it any more. A gate
that cannot fail is not a gate. It now guards the population the shipped detector genuinely
routes to review: a bare name with no anchor confirming it, 141 across the corpus. Notably,
**no baseline vector was re-pinned** — all nine matrix tests pass against the existing pins,
because the pins were always written for the intended behaviour and it was the measurement
that had drifted. That is stronger evidence than a re-pin would have been.

**Three defects surfaced in this stretch, each invisible to the gates that existed.** Our own
oracle baseline was leaking 62 real PII strings through PDF revision residue while reporting
itself clean — a leaky oracle miscalibrates every gate derived from it. Every DOCX output was
shipping `docProps/thumbnail.jpeg`, a rendered picture of the un-redacted first page, which
is pixels and therefore something no text extractor could ever have caught. And a corpus
ground-truth bug of mine had `DocxBuilder.header/footer` overwriting earlier text while still
recording it, so GT claimed 30 surfaces that were not in the files — inflating recall for
precisely the types that had vanished.

**Two leaks came from anchor fragility**, and both were found outside the corpus: an NBSP and
then a line break sitting between the words of a multi-word anchor. In each case the PDF
leaked while the DOCX of the same document was clean. Both are on the red-team attack list,
which is the argument for finishing that list rather than trusting the green gate.

**What is NOT closed:** Phase D needs three consecutive clean rounds and has had one; the
missing-diacritics gap (QUESTIONS.md Q7) is measured and still open; per-type precision,
mutation robustness, cross-format consistency and perf are not yet gates; ORG and NAZOV_BANKY
have no detectors.

## Session close — 2026-09-16

**Final gate numbers, every one re-run by the orchestrator.** Full suite **1142 passed, 8
skipped, 0 failed**. Dual leak gate **PASS** — 70 docx + 70 pdf, `text_layer=0 scrub=0
other=0`, and for the first time **with no type exclusions at all**. Demo: 41 auto + 2 review
(docx), 40 + 1 (pdf), zero leaks against 25 PII needles. A third gate now exists and **fails
on purpose**: `python -m eval.mutation_gate` measures detection robustness under 11 text
mutations and exits non-zero while any is below 0.95.

**The exclusion list is the finding worth carrying forward.** `CLASS_A_TYPES` began as "types
v1 genuinely cannot detect". OBEC and KATASTER left when the gazetteer shipped. ORG left
tonight — and had been detectable, partially, since the Phase C round, because
`detect/name_anchors.py` emits ORG from the `Obchodné meno:` field label while the contract's
ownership table listed that module as MENO-only and the gate's own comment said ORG stayed
excluded "until its detector exists". An exclusion outlived its reason by several rounds and
nothing noticed, because an excluded type produces no failures. The gate now prints its real
exclusion set rather than a fixed string, so stale text cannot hide one again.

**Red-team round 2 falsified an orchestrator expectation, which was its most valuable
output.** I predicted `line_break_mid` would be clean — I had widened the anchor separator
after a wrapped PDF leaked a client number. It measured 0.113, and `CISLO_KLIENTA`, the exact
type that fix was written for, was at 0.000: I had widened the gap *between the words of an
anchor* and not the gap between the *anchor and its value*, so a wrap one word later leaked
the same number again. Fixed. The same gate then caught a crash I introduced while fixing it
— a widened separator let a tab into an IBAN, and the mod-97 checksum does `int(c, 36)`,
which raises on a tab. An exception in a shipped desktop app is strictly worse than a missed
detection, and the gate refused to print a number for that column rather than a misleading
one.

**Eight mutation classes remain open**, each with a measured number and a named fix. The two
largest need an offset-mapped normalization in `detect()` rather than a regex widening: the
NBSP fix was safe *because* it is one character for one character and preserves the offsets
both writers slice by, and deleting a zero-width character is not. The sharpest single case in
the round is a Cyrillic homoglyph in an email address, which is not missed but **silently
truncated** — the tool redacts `.novak@advokat.sk` and leaves `jan` standing beside it.

**What this session did not finish:** Phase D wants three consecutive clean rounds and got two
non-clean ones; per-type precision, cross-format consistency and perf are not gates; ULICA has
a detector and no corpus coverage; `dist\Anonymizer` was not rebuilt.


=========================================================================
DAYTIME RUN — 2026-09-17. THE CORPUS SWAP (Q14), before / after
=========================================================================

corpus/generate.py derived a PER-FORMAT seed, so the .docx and .pdf of one index were two
unrelated documents: the corpus was 140 different documents named as though it were 70 in two
formats, and every cross-format claim made against such a pair was meaningless. The generator
now authors a content PLAN once per (doc_type, index) and renders it to each format.

THE CONTROL THAT MAKES THESE NUMBERS READABLE. Every gate below was re-run on the OLD corpus
with TODAY'S detect/ and writer/ before the swap, so the only variable between the two columns
is the CORPUS. Without that control, today's detector work (surname_caps, the mojibake fold,
the KATASTER anchor, the street/place collision fix) would be indistinguishable from corpus
drift and the two would be credited to each other.

  PAIRING PROPERTY                        before          after
  ---------------------------------------------------------------------
  one-sided GT surfaces, unexplained      5285            0
  surfaces common to both formats         136             3039
  kupna_zmluva_000 (docx / pdf / common)  46 / 40 / 3     46 / 42 / 41

  GATE                                    before          after
  ---------------------------------------------------------------------
  dual leak gate                          PASS, 0 leaks   PASS, 0 leaks
  cross-format consistency                PASS            PASS
  demo (end to end)                       PASSED          PASSED
  mutation: wrap_at_space                 0.971           0.971
  mutation: surname_caps                  0.994           0.994
  mutation: no_diacritics                 0.996           0.996
  mutation: lowercase                     0.968           0.968
  mutation: all_caps                      0.961           0.964   (up)
  mutation: letterspaced                  0.113 FAIL      0.120 FAIL
  mutation: cyrillic_homoglyph            0.976           0.975   (DOWN)
  mutation: mojibake_cp1250               0.996           0.994   (DOWN)
  mutation: break_in_token (report-only)  0.469           0.464   (DOWN)
  precision ULICA                         92.2% (47/51)   100%  (48/48)   (up)
  precision ECV                           95.2% (20/21)   100%  (20/20)   (up)
  precision KATASTER                      31.8% (28/88)   35.8% (38/106)  (up)
  precision ADRESA                        100%            100%
  precision MENO                          99.1% (1480/1494) 98.9% (1480/1496)  (DOWN)
  precision OBEC                          28.5% (77/270)  24.0% (64/267)  (DOWN)
  precision ORG                           100%  (20/20)   95.2% (20/21)   (DOWN)

SIX NUMBERS MOVED DOWN. Each was investigated before this was committed, as the brief requires,
and each was verified by the orchestrator rather than accepted from the agent that made the
change. NONE is a leak; the leak gate is 0 on the new corpus.

  cyrillic_homoglyph, mojibake, break_in_token — all three are VALUE-MIX effects. The corpus
  contains the same defect populations; the refactor changed WHICH random values are drawn into
  them. mojibake's five extra lost surfaces are newly-drawn ORG and ULICA values; break_in_token
  picks its break offset from the surface value itself, so it is pure value mix.

  MENO 99.1% -> 98.9% is exactly TWO more unbacked candidates. Every unbacked MENO candidate in
  both corpora has the same shape: a place name that is also a Slovak surname ("Michalovciach")
  claimed as MENO. Two documents newly draw Michalovce.

  OBEC 28.5% -> 24.0% is NOT a detection defect and the number is not measuring what it looks
  like it measures. Verified directly against ground truth: the SAME surface is ground-truthed
  as BOTH types in different documents --

      'Košiciach'     GT {OBEC: 20, KATASTER: 48}
      'Levoči'        GT {KATASTER: 43, OBEC: 27}
      'Michaloviec'   GT {KATASTER: 50}   (detect() says OBEC)

  -- because a Slovak cadastral area is usually named after its obec. An UNANCHORED place
  defaults to OBEC, so OBEC collects every place the ground truth happens to call KATASTER. The
  anchored-KATASTER fix landed today closes this only where an anchor is present. Both types
  are auto-redacted, so this is a label split, not a leak. OBEC has 70 GT surfaces against 267
  candidates; KATASTER has 282 GT surfaces against 106 candidates; the TOTAL place population
  is roughly right and the split is not.

  ORG 100% -> 95.2% is ONE candidate, and it is a genuine type collision worth recording:

      detect('Účet vedený v ČSOB, a. s.')  ->  [('ORG', 'ČSOB, a. s.')]
      corpus ground truth for that bank    ->  {'NAZOV_BANKY'} on the bare 'ČSOB'

  ORG keys on the legal-form suffix ("a. s.", "s.r.o.") because a company name is otherwise
  arbitrary; NAZOV_BANKY is a closed list. "Tatra banka, a. s." resolves correctly because
  "banka" is in the list, but "ČSOB" is an acronym without it, so once the legal form is
  attached ORG wins the span. Redacted either way; the label is wrong. Recorded, not fixed.

WHAT THE REBUILT CORPUS FOUND ON ITS FIRST RUN, which is the argument for doing this at all: a
street named after a municipality ("na Polom 453") produced NO ULICA candidate and only a
review-bucket OBEC, so nothing auto-redacted it and the street survived into BOTH outputs of the
same document. The old corpus drew "Paulenova" in that slot, which the -ova suffix rule catches,
so the leak gate was green BY LUCK OF THE DRAW. Fixed in the street walk with an enumerator
guard and a date guard, both measured load-bearing. The leak appeared in the .docx AND the .pdf
of the same document — precisely the property Q14 wanted back.

ALSO REGENERATED: data/holdout with its manifest, using its own recorded command
(--n 60 --seed 1337). AND A MISTAKE CAUGHT WHILE DOING IT: the generator does not clean its
output directory, so regenerating over the old holdout left 192 STALE FILES from an earlier
6-document-type generator, and the first manifest I wrote covered all 434 — baking drift into
the very file whose job is to DETECT drift. Removed the orphans, re-manifested at 242 files,
acceptance tests green. data/synthetic was checked for the same and was clean.
