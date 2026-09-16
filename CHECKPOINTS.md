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
