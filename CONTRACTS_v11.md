# CONTRACTS_v11.md — frozen interfaces for the v1.1 hardening sprint

Written by the orchestrator BEFORE any v1.1 implementation round. Every subagent builds
against this file. **If an implementation needs a contract here to change, it STOPS and
reports — it never changes the contract unilaterally.** Contract changes are made by the
orchestrator and re-frozen here with a dated line in `## Change log`.

Governing rule (unchanged, context.md §6): **recall over precision**. Leak test = zero,
non-negotiable. Every ambiguous decision resolves toward over-detection.

---

## 1. `detect.core.Candidate` — NEW SHAPE

```python
@dataclass(frozen=True)
class Candidate:
    type: str
    surface: str
    start: int
    end: int
    auto: bool
    checksum: str = "n/a"      # NEW in v1.1 — "valid" | "invalid" | "n/a"
```

* The new field is LAST and has a default, so every existing construction
  `Candidate(type=..., surface=..., start=..., end=..., auto=...)` keeps working unchanged.
* `checksum` is a **tag, not a filter** (v1.1 policy A1). Allowed values are exactly the
  three strings above. A detector whose type has no checksum emits `"n/a"`.
* `checksum` NEVER participates in span resolution, precedence, grouping or label minting.
  It is carried through to the report and the GUI review column only.

## 2. `detect.config.DetectConfig` — NEW MODULE

```python
# detect/config.py
@dataclass(frozen=True)
class DetectConfig:
    strict_checksums: bool = False   # A1: True restores v1 behaviour (checksum-invalid -> review)
    redact_all_dates: bool = False   # B: True redacts every DATUM, not only DOB

DEFAULT = DetectConfig()
```

`detect/config.py` imports NOTHING from the project. `detect/` still never imports
`corpus/` or `eval/`.

## 3. `detect.core.detect` — NEW SIGNATURE

```python
def detect(text: str,
           known_entities: list[str] | None = None,
           config: DetectConfig | None = None) -> list[Candidate]:
```

`config=None` means `DEFAULT`. Positional call sites `detect(text, known)` are unchanged.

**Post-conditions (asserted at the end of `detect`, all of them):**
1. sorted by `(start, end)`
2. no two candidates share an exact span
3. **no two candidates overlap AT ALL** (new in v1.1 — see §5)
4. every emitted `c.type` is in `KNOWN_TYPES` (§4)
5. every `c.checksum` in `{"valid", "invalid", "n/a"}`

## 4. Type registry — `detect/core.py`

`_TYPE_PRECEDENCE` is the single ordered tuple. **Most specific / strongest claim first.**
Frozen order for v1.1:

```python
_TYPE_PRECEDENCE = (
    # checksum- or structure-bearing identifiers (strongest claims)
    "RODNE_CISLO", "IBAN", "BANKOVY_UCET", "BIC", "IC_DPH", "ICO", "DIC",
    "VIN", "ECV", "CISLO_PASU", "CISLO_OP", "VODICSKY_PREUKAZ",
    # registry / court refs
    "SPISOVA_ZNACKA", "ORSR_VLOZKA", "LV", "PARCELA",
    # contact
    "EMAIL", "TELEFON", "URL",
    # address block: the composite ADRESA outranks its own parts
    "ADRESA", "PSC", "SUPISNE_CISLO", "CISLO_BYTU", "VCHOD", "POSCHODIE",
    # entities
    "ORG", "OBEC", "KATASTER", "MENO",
    # weakest
    "DATUM", "SUMA",
)
KNOWN_TYPES = frozenset(_TYPE_PRECEDENCE)
```

**Rank lookup MUST NOT KeyError at runtime.** Use
`_TYPE_RANK.get(t, len(_TYPE_PRECEDENCE))` — an unregistered type ranks last instead of
crashing a shipped app. Coverage is enforced instead by post-condition 4 above plus a unit
test asserting every type name any detector module can emit is in `_TYPE_PRECEDENCE`.
Adding a type = add it to this tuple AND to this document.

## 5. Overlap resolution — `detect/core.py` (NEW, correctness-critical)

v1 only resolved EXACT-span collisions plus one hand-written BANKOVY_UCET containment rule.
v1.1 adds many composite types (ADRESA contains PSC, OBEC, SUPISNE_CISLO; a role-anchored
MENO run can abut an ADRESA), so partial and nested overlaps are now routine. Both writers
slice by offsets, so **overlapping spans corrupt output** — resolution is mandatory.

Pipeline order in `detect()`:

1. collect all candidates from all detector modules
2. `_resolve_flag_survival`  (exact span; unchanged semantics)
3. `_resolve_type_precedence` (exact span; unchanged semantics)
4. `_resolve_containment`  — NEW, generalised over ALL types
5. `_resolve_partial_overlaps` — NEW
6. sort + assert post-conditions §3

**`_resolve_containment`** — for candidates A, B with B strictly inside A
(`A.start <= B.start and B.end <= A.end` and the spans differ):
* If `B.auto and not A.auto` → **promote A to `auto=True`** (a wider span covers strictly
  more text; never lose a redaction to a suppression — recall over precision).
* Then drop B. The outer always wins the span.
* ~~`BANKOVY_UCET` containment is now just an instance of this rule; the bespoke
  `_suppress_identifiers_inside_bankovy_ucet` is deleted.~~ **THIS CLAUSE WAS WRONG — see
  AMENDMENT 2 below. The bespoke suppressor is KEPT and runs BEFORE containment.**
* `_suppress_urls_inside_emails` likewise becomes an instance of this rule (EMAIL contains
  URL). Delete the bespoke function only if its tests stay green.

### AMENDMENT 2 — why `_suppress_identifiers_inside_bankovy_ucet` survives

The original §5 told the implementer to delete the bespoke BANKOVY_UCET suppressor because
generalised containment subsumes it. **That was a contract error**, caught by the Phase A
round and independently re-verified by the orchestrator. It contradicts §6:

* text `"...na účet 013389-1543039118/1100 do..."` with `strict_checksums=True`
* the account's base fails its mod-11, so per §6 the account is `auto=False` ("invalid")
* the inner 10-digit base `1543039118` independently matches the bare-DIC shape, `auto=True`,
  and is a STRICT sub-span
* generalised containment's PROMOTION rule then promotes the account back to `auto=True`

Net effect: `strict_checksums=True` would become a **silent no-op for every legacy domestic
account number** — it could never route one to review, which is the entire purpose of the
strict escape hatch. Verified directly: pure `_resolve_containment` on that pair returns
`[("BANKOVY_UCET", auto=True)]`.

Resolution: the bespoke suppressor is KEPT and runs BEFORE `_resolve_containment`, so the
inner DIC is gone before promotion can see it. Under the DEFAULT config both orderings agree
(the account is `auto=True` either way), so this only bites in strict mode.

`_suppress_urls_inside_emails` WAS correctly deleted: EMAIL and URL are both unconditionally
`auto=True`, so the promotion rule never fires and general containment reproduces it exactly.

**General lesson for the rest of this sprint:** a promotion rule that widens `auto` is safe
for RECALL but is not safe for a deliberate SUPPRESSION. Any future rule that can flip
`auto=False` to `auto=True` must be checked against every path that sets `auto=False` on
purpose.

**`_resolve_partial_overlaps`** — crossing spans, neither containing the other. Sort
survivors by `(start, -(end - start), _TYPE_RANK)` and sweep greedily keeping
non-overlapping ones. When a candidate is dropped and it was `auto=True` while the kept
candidate is `auto=False`, **promote the kept one to `auto=True`** before dropping.

## 6. `auto` and `checksum` — the A1 policy

| condition | `auto` (default config) | `auto` (`strict_checksums=True`) | `checksum` |
|---|---|---|---|
| shape-valid + checksum passes | `True` | `True` | `"valid"` |
| shape-valid + checksum fails | **`True`** (v1.1 change) | `False` | `"invalid"` |
| shape-valid, type has no checksum | `True` | `True` | `"n/a"` |
| shape-invalid | no Candidate | no Candidate | — |

Types carrying a checksum: `RODNE_CISLO` (mod-11, 10-digit form ONLY — see §6a), `ICO`
(weighted mod-11), `IBAN` (mod-97), `BANKOVY_UCET` (weighted mod-11 on prefix and base).
Types with no checksum (always `"n/a"`): everything else, including `DIC` and `IC_DPH`.

**Near-miss review routing for checksum-failing identifiers is REMOVED.** Those surfaces
are now auto-bucket, pre-ticked, redacted. The review bucket in v1.1 is for Phase C's
bare-name heuristic and for `strict_checksums=True`.

### 6a. RODNE_CISLO — the A2 shape rules

* **10-digit form** `YYMMDD/XXXX` — mod-11 checksum applies (`"valid"` / `"invalid"`).
* **9-digit form** `YYMMDD/XXX` — issued before 1954, **has no checksum at all**. Always
  `checksum="n/a"`, always `auto=True`. Applying mod-11 to it is the A2 bug being fixed.
* Separators accepted between the date part and the tail: `/`, a space, an NBSP (U+00A0),
  or NOTHING (contiguous digits).
* Internal whitespace (space or NBSP) inside either digit group is accepted and is part of
  the matched surface.
* **AMENDMENT 5 — both the contiguous AND the space/NBSP-separated forms require an RČ
  context anchor. Only the SLASH form is self-identifying.** A space-separated 6+4 digit run is
  the same shape as a phone number: the demo contract's `Fax: 055 123 4567` parsed as
  `055 12` + separator + `3 4567`, passed the month/day shape check (month 51 → 51−50 = 1,
  day 23) and was auto-redacted and REPORTED as a rodné číslo, beating FAX and TELEFON to the
  span. Nothing leaked — it was redacted either way — but a report that calls a fax number a
  birth number cannot be checked against the document, which is the report's entire purpose.
* The anchor window is **symmetric**: 40 characters before OR after. Slovak places the label
  on either side ("rodné číslo 850315/001" and "850315/001 je rodné číslo" are both ordinary).
* Anchors: `r.č.`, `rč`, `rodné číslo`, `rodného čísla`, `nar.`, `narodený`, `narodená`,
  `narodil`, `dátum narodenia`, `dát. nar.` — matched diacritic-folded.
* The original clause, still true for the contiguous form:: `r.č.`, `rč`, `rodné číslo`, `rodného čísla`,
  `nar.` (case-insensitive, diacritic-tolerant). Without that anchor a bare 9/10-digit run
  stays owned by DIC (v1 behaviour, unchanged) — matching it unconditionally would claim
  every 10-digit number in every document.
* Month-offset shape check (`+0/+20/+50/+70`) and day range `1..31` apply to both lengths.

## 7. Ground truth — `corpus/groundtruth.py`

`PiiSpec` gains `checksum: str = "n/a"` mirroring §1, and the recorder writes it as a
`"checksum"` key on every pii entry. The three-state decision becomes:

* valid identifier / real name → `auto_redact=True,  should_flag=False, checksum="valid"|"n/a"`
* **checksum-invalid but PII-shaped → `auto_redact=True, should_flag=False, checksum="invalid"`**
  (v1.1 change: was `auto_redact=False, should_flag=True`)
* innocuous decoy number → `auto_redact=False, should_flag=False, checksum="n/a"`

Consequence for `eval/`: the `should_flag` class becomes EMPTY for identifier types, so
`FLAG_SURVIVAL_MIN` passes vacuously for them. It is NOT deleted — it still guards any type
that legitimately routes to review (Phase C bare names). Checksum-invalid surfaces move into
the `auto` class, so **per-type recall now includes them** and a detector that skipped them
will FAIL recall. That is the intended gate.

## 8. Detector module layout — who owns which file

Each new detector lives in its OWN module so parallel rounds never conflict. `detect/core.py`
imports them all and calls them in `detect()`; the orchestrator writes that dispatch.

| module | types |
|---|---|
| `detect/identifiers.py` (existing) | RODNE_CISLO ICO DIC IC_DPH IBAN BANKOVY_UCET EMAIL URL TELEFON |
| `detect/registry_refs.py` (existing) | LV PARCELA ORSR_VLOZKA SPISOVA_ZNACKA |
| `detect/datetime_amounts.py` (existing) | DATUM SUMA |
| `detect/addresses.py` **(new, B1)** | PSC ADRESA SUPISNE_CISLO CISLO_BYTU VCHOD POSCHODIE |
| `detect/documents.py` **(new, B2)** | CISLO_OP CISLO_PASU VODICSKY_PREUKAZ ECV VIN BIC |
| `detect/orgs.py` **(new, B3)** | ORG |
| `detect/name_anchors.py` **(new, C1)** | MENO (title / role / field-label / bare-name anchors) |
| `detect/gazetteer.py` **(new, C3)** | OBEC KATASTER |

Every new module exposes exactly one public entry point:

```python
def detect_<name>(text: str, config: DetectConfig) -> list[Candidate]: ...
```

It imports only `re`, `detect.core.Candidate`, `detect.config.DetectConfig` and (where
needed) `detect.declension`. **Never** `corpus/` or `eval/`.

## 9. Corpus PII generators — who owns which file

Same rule: one new file per round, wired into templates by a single later integration round.

```python
# corpus/pii/<name>.py
def make_<type>(rng) -> tuple[str, PiiSpec]: ...   # (surface as authored, its ground truth)
```

`corpus/templates/*.py` are NOT touched by B/C rounds. The integration round adds one new
document type, `corpus/templates/zmluva_v11.py`, that seeds every new type into real
`.docx`/`.pdf` so the leak gate covers them.

## 10. Writer + GUI threading

* `redact_docx_body(in_path, out_path, known_entities=None, decisions=None, config=None)`
* `redact_docx_collect(...)` / `redact_pdf(...)` / `redact_pdf_collect(...)` — same new
  trailing `config=None` parameter, threaded straight into `detect()`.
* `LabelMap.record_occurrence(label, location, surface, snippet="", checksum="n/a")` and
  `record_low_confidence(location, type, surface, snippet="", checksum="n/a")` — new
  trailing keyword. `LabelMap.occurrences` / `.low_confidence` tuple shapes STAY BYTE-STABLE
  (`build_report` unpacks them); the checksum goes in NEW parallel side-channels
  `LabelMap.checksums: dict[str, str]` (label -> checksum) and
  `LabelMap.lc_checksums: list[str]` (index-aligned with `low_confidence`), exactly as
  `contexts` / `lc_contexts` already do.
* `writer/report.py`: `build_report(occurrences, low_confidence, checksums=None, lc_checksums=None)`
  — new optional params. When given, a `checksum` column is appended to BOTH tables. When
  omitted the output is BYTE-IDENTICAL to v1 (existing report tests must stay green).
* `gui/model.ReviewRow` gains `checksum: str = "n/a"`.
* Report filename collision fix (Phase F) changes the report path to carry the SOURCE
  extension: `<stem>_docx_report.txt` / `<stem>_pdf_report.txt`.

## 11. Non-negotiables for every round

* `tests/` must NOT import `corpus/`. Unit tests use HAND-BUILT fixtures.
* Prove RED before GREEN: every new test must be shown failing against the pre-change code.
* No round commits, pushes, or regenerates the corpus. The orchestrator does all three.
* A round that finds a claim in this file to be FALSE reports it and STOPS.

---

## 12. Authoritative type list — Vyhláška MS SR 482/2011 (ADDENDUM 1, R1)

The binding Slovak list of data subject to anonymisation in court decisions, as published by
the Ministry of Justice
(https://www.justice.gov.sk/faq/ktore-udaje-v-rozhodnutiach-podliehaju-anonymizacii/,
implementing Vyhláška MS SR 482/2011 + Inštrukcia 24/2011). Fetched and mapped 2026-09-16.
This is now the authority for "is the type list complete?", replacing the office's own list.

| Vyhláška clause | our type(s) | status |
|---|---|---|
| a) rodné číslo | `RODNE_CISLO` | covered |
| b) číslo OP / cestovného dokladu / iného dokladu totožnosti | `CISLO_OP`, `CISLO_PASU`, `VODICSKY_PREUKAZ` | covered |
| c) bydlisko | `ADRESA`, `ULICA`, `PSC`, `OBEC`, `SUPISNE_CISLO`, `CISLO_BYTU`, `VCHOD`, `POSCHODIE` | covered |
| d) dátum narodenia | `DATUM` (DOB-anchored; see §2 `redact_all_dates`) | covered |
| e) telefónne číslo, faxové číslo, e-mailová adresa | `TELEFON`, `FAX`, `EMAIL` | covered |
| f) **názov** a kód banky alebo pobočky zahraničnej banky | **`NAZOV_BANKY`**, `KOD_BANKY` | `NAZOV_BANKY` was a GAP — added by this amendment |
| f) číslo bankového účtu, názov účtu, IBAN, číslo klienta | `BANKOVY_UCET`, `NAZOV_UCTU`, `IBAN`, `CISLO_KLIENTA` | covered |
| g) označenie katastrálneho územia | `KATASTER` | covered |
| h) číslo listu vlastníctva | `LV` | covered |
| i) utajované informácie a obchodné tajomstvo | — | **DECLARED OUT OF SCOPE**, see below |
| j) meno a priezvisko fyzickej osoby | `MENO` | covered |
| k) mená zákonných zástupcov a opatrovníkov | `MENO` | covered |

**Clause (i) — utajované informácie a obchodné tajomstvo — is out of scope and must be
stated to the office in writing.** Classified information and trade secrets are defined by
their MEANING, not by any surface pattern: no regex, gazetteer or checksum can decide that a
sentence discloses a trade secret. A tool that silently skipped clause (i) while appearing to
implement "the vyhláška list" would misrepresent its own coverage, which is precisely the
liability posture context.md §9 forbids. The report must not imply clause (i) is handled, and
the human review step is where it is handled.

**Clause (j) carries an exception list** (judges, court officials, notaries, executors,
experts, interpreters, translators, entrepreneurs, legal representatives — their names are
NOT anonymised). v1.1 deliberately does NOT implement that exception: per ADDENDUM 1 R2 every
ambiguity resolves toward REDACT, and distinguishing a judge's name from a party's name
requires role inference this tool does not have. Over-redacting a judge's name costs the
reviewer one un-tick; under-redacting a party's name is a breach.

### Types added by this amendment (append to the §4 tuple in this order)

Insert after `DIC` and before `VIN`:  `KOD_BANKY`
Insert after `URL` (contact block):    `FAX`
Insert in the address block after `ADRESA`: `ULICA`
Insert in the entity block before `ORG`:    `NAZOV_BANKY`, `NAZOV_UCTU`, `CISLO_KLIENTA`

`NAZOV_BANKY` is a CLOSED LIST type (the licensed banks and foreign-bank branches operating
in Slovakia) plus the anchors `banka`, `pobočka zahraničnej banky`, `banky`. Closed-list, so
`auto=True`, `checksum="n/a"`.
`ULICA` is a gazetteer type (Register adries street list, CC0). Per ADDENDUM 1 R3 it is
matched ONLY when followed by a number or preceded by `ul.` / `ulica` / `nám.` / `námestie` /
`trieda` / `cesta` — a bare street name collides with too many common words.

## Change log

* 2026-09-16 — initial freeze (orchestrator), v1.1 sprint Phase A start.
* 2026-09-16 — AMENDMENT 1 (ADDENDUM 1 / R1): §12 added — the vyhláška 482/2011 type
  list is now the completeness authority. Six types added to §4 (KOD_BANKY, FAX, ULICA,
  NAZOV_BANKY, NAZOV_UCTU, CISLO_KLIENTA); NAZOV_BANKY was a genuine gap found by the
  mapping. Clause (i) (trade secrets / classified info) declared out of scope in writing.
* 2026-09-16 — AMENDMENT 2 (§5): the instruction to delete
  `_suppress_identifiers_inside_bankovy_ucet` was WRONG and is retracted. Keeping it is
  required for `strict_checksums=True` to work on legacy account numbers. Found by the Phase A
  round, re-verified by the orchestrator.
* 2026-09-16 — AMENDMENT 3 (§4): `FAX` is placed immediately BEFORE `TELEFON` in the
  precedence tuple, not appended with the other Amendment-1 types. Fax and phone share a digit
  shape and collide on an exact span; FAX is anchor-required and is the stronger, more
  informative claim. Both are auto-redacted either way — this decides only which label the
  reviewer reads.
* 2026-09-16 — AMENDMENT 5 (§6a): the SPACE/NBSP-separated RODNE_CISLO form now requires an RČ
  context anchor, like the contiguous form; only the SLASH form is self-identifying. The
  anchor window became symmetric and the anchor list gained the spelled-out birth forms.
  Found by the demo document, where a fax number was being reported as a rodné číslo.
* 2026-09-16 — AMENDMENT 6 (§8): a gazetteer token must be ≥3 characters, start with a capital
  and contain a lowercase letter. Without it the register matched `VIN` as a street and the
  Roman numerals `I` / `II` (from "Článok I") as cadastral areas — things a legal document
  contains on every page.
