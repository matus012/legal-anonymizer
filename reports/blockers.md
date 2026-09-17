# Blockers

## 2026-09-16 — transient RedactionIncompleteError on a few zmluva_v11 PDFs (NOT a ULICA bug)

**Status:** not currently reproducible; recorded for the record, not blocking.

While regenerating the corpus for the ULICA coverage task, `writer.pdf_body.redact_pdf`
intermittently raised `RedactionIncompleteError` on 0–4 of the 10 `zmluva_v11` PDFs (never
DOCX), always citing the SAME class of surface: an enormous multi-hundred-character
`NAZOV_UCTU` candidate whose regex ("value runs to the end of the line") had not terminated
where expected. Confirmed NOT caused by the ULICA generator or template addition: disabling
the new ULICA block and regenerating still reproduced the failure on `zmluva_v11_034.pdf` in
isolation. Also confirmed NOT stably reproducible: two clean re-runs of the full 140-file
redaction immediately afterward completed with 0 failures. The corpus itself is
byte-identical across regenerations (checked via SHA-256), so the instability is in the
redaction/detection run, not the generator.

Best explanation: this session ran concurrently with other agents actively editing
`detect/core.py` and `detect/normalize.py` (per the task brief). The intermittent failures
are consistent with occasionally reading those files mid-edit rather than a deterministic
defect in `detect/office_refs.py`'s `NAZOV_UCTU` regex or `corpus/pdf_builder.py`'s page-text
reconstruction — though that regex (`([^\n\t]+?)(?=...|\n|$)` relying on a literal `\n` to
bound "end of line") IS structurally fragile against however MuPDF's `page.get_text()`
groups lines, and is worth a deliberate look if this recurs. Not fixed here: out of this
task's scope (ULICA corpus coverage only; `detect/office_refs.py` is not ULICA's owner and
was not touched).

**If this recurs:** reproduce with `python -m corpus.generate --n 70 --out data/synthetic
--seed 42 --formats docx,pdf` then loop `writer.pdf_body.redact_pdf` over every
`zmluva_v11*.pdf` in it; capture the failing surface's text and check whether
`detect.office_refs._NAZOV_UCTU_RE`'s lazy `[^\n\t]+?` group is matching across what
`page.get_text()` treats as one physical line with no `\n` in it.


### RESOLVED 2026-09-16, later the same night — cause identified, it was mine

**It was not a heisenbug and it was not `detect/office_refs.py`.** The diagnosis in the entry
above was right about the mechanism and right to record it: a `NAZOV_UCTU` value regex that
bounds itself on a literal `\n` had lost its terminator, so the value ran on and produced a
multi-hundred-character surface that `page.search_for` could never locate.

What removed the `\n` was the normalization layer I was building in `detect/normalize.py`
while that round ran. An intermediate version of it collapsed EVERY whitespace run to a single
SPACE, line breaks included. That is what "reading those files mid-edit" actually meant: the
files were not corrupt, they were briefly *correct code implementing a wrong decision*.

The same choice broke `detect/name_anchors.py` in the opposite direction — with wraps turned
into spaces its bare-name heuristic began pairing the last word of one line with the first word
of the next, and it emitted the auto-redact `MENO` surface `Novák\nRodne`. Two detectors, two
opposite failures, one cause. The layer now collapses a whitespace run that CROSSED A LINE to a
single `\n` and every other run to a single space, so the line boundary survives normalization
and a detector that bounds a value on `\n` still has its bound. Recorded as CONTRACTS_v11.md
Amendment 9 and in `detect/normalize.py`'s docstring.

**Verified, not assumed:** `writer.pdf_body.redact_pdf` run over all 71 PDFs in
`data/synthetic/` on the current code raises `RedactionIncompleteError` **zero** times. The one
failure is `scan_image_only_000.pdf` raising `NoTextLayerError`, which is the fixture doing its
job — refusing an image-only PDF rather than returning a false-clean copy.

**The structural fragility the entry above flagged is still real and is NOT fixed.** A value
pattern that relies on a literal `\n` to mean "end of line" depends on how `page.get_text()`
happens to group lines, and it survived this time only because the normalization layer was
changed to preserve line breaks. Left as a known sharp edge, now documented rather than
discovered twice.

---

## 2026-09-17 · red-team round 3 · `tests/test_mutations.py` forbids `corpus/mutations.py` from growing

**Task blocked:** adding the four round-3 mutations (`nb_hyphen`, `narrow_nbsp`,
`surname_caps`, `letterspaced`) to `corpus/mutations.py` — the explicit deliverable of the
round-3 brief, which says "ADD new mutations; do not modify or delete existing ones".

**What is blocked:** the mutations are added, registered, homomorphism-checked and measured
(`python -m eval.mutation_gate` runs them, instrument self-check OK, four new columns), but
`python -m pytest tests/test_mutations.py` now reports **5 failures**:

```
FAILED tests/test_mutations.py::test_registry_holds_every_required_mutation
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[letterspaced]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[narrow_nbsp]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[nb_hyphen]
FAILED tests/test_mutations.py::test_every_mutation_is_registered_under_its_own_function[surname_caps]
```

Both have the same root cause: the test pins the registry to round 2's exact eleven.

```python
assert set(MUTATIONS) == {          # tests/test_mutations.py:65 — EQUALITY, not superset
    "nbsp", "zero_width", "soft_hyphen", "tabs", "double_spaces", "line_break_mid",
    "all_caps", "lowercase", "no_diacritics", "cyrillic_homoglyph", "nfd",
}

@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_mutation_is_registered_under_its_own_function(name):
    assert MUTATIONS[name] is globals()[f"mutate_{name}"]   # line 74 — globals() of the TEST
                                                            # module, fed by an EXPLICIT
                                                            # eleven-name import list at :27
```

The second one is the subtler of the two: it looks like a general invariant ("every registered
mutation is bound to its own function") but it is actually a check that the test module's own
explicit import list matches the registry, so it fails with `KeyError` for any mutation the test
file does not already import by name.

**What was tried:** nothing was changed in `tests/`. The round-3 brief forbids touching any
existing file in `tests/`, and the standing rule forbids editing an existing test to make
something pass. Reverting the mutations was rejected — they are the deliverable, and three of
the four are the corpus-scale measurement behind findings R3-A5, R3-A6 and R3-C1
(`surname_caps` 0.649, `nb_hyphen` 0.941, `letterspaced` 0.113, all below the 0.95 gate).

**What is needed (one decision, not mine to take):** a two-line change to
`tests/test_mutations.py` by whoever owns it.

1. line 65: `==` → `<=` on the brief's eleven — i.e. assert *the required set is PRESENT*, not
   that nothing was ever added. The invariant the test names ("a mutation silently missing from
   MUTATIONS is a column the gate never prints and an attack nobody ran") is a SUPERSET
   invariant; the equality is stricter than the thing it documents.
2. line 74: resolve through the module rather than the test's globals —
   `getattr(corpus.mutations, f"mutate_{name}")` — so the invariant holds for every mutation
   instead of for the eleven the test happens to import.

**State: OPEN.** Everything else in the round is unaffected and was completed:
`tests/test_redteam_round3.py` is green (6 passed / 21 xfailed / 0 xpassed), the mutation gate
runs all fifteen mutations with its instrument self-check passing, and the rest of the suite is
1361 passed / 8 skipped, with these five the only red in the tree.

**This is itself a round-3 finding** (recorded as R3-F1 in `redteam/FINDINGS_ROUND3.md`): a test
whose stated purpose is "make sure nobody drops an attack" is implemented as an equality that
makes the module append-only in name and frozen in fact. Every future red-team round hits it.

## 2026-09-17 — `corpus/templates/_common.py:143` mislabels an anchored katastrálne-územie
## occurrence as OBEC (found while fixing the KATASTER/OBEC precedence bug)

**Status: OPEN, not fixed here.** `corpus/templates/_common.py` is outside this task's file
ownership (owned files: `detect/gazetteer.py`, `detect/core.py` §`_TYPE_PRECEDENCE`,
`eval/run.py`, `eval/metrics.py`, and tests) — reporting per the brief's own instruction
("If one needs changing, report it instead").

**What was asked:** make `detect/gazetteer.py` label a place as KATASTER instead of OBEC
when the surface is preceded by an explicit katastrálne-územie anchor ("katastrálne územie",
"k. ú.", "kat. územie", "KÚ", inflected forms), while an unanchored collision keeps reading
as OBEC — the Amendment-3 pattern (anchored beats unanchored), settled in the gazetteer
because `_TYPE_PRECEDENCE` has no access to the anchor. Implemented exactly that (see
`detect/gazetteer.py`, "OBEC/KATASTER label precedence"), and it does the right thing on
every case checked by hand.

**What it exposed:** `seed_docx_failure_modes` (`corpus/templates/_common.py:143`) writes a
textbox literally reading `"Nehnuteľnosť v k. ú. "` followed by a place — but tags that
`PiiSpec` `"OBEC"`, not `"KATASTER"`. The text says katastrálne územie; the ground truth says
OBEC. This is a *different* thing from the cross-document ambiguity the task brief already
flagged (the same surface, e.g. "Michalovciach", legitimately being OBEC in one document and
KATASTER in another, which the anchor is exactly built to disambiguate) — this is one single
occurrence, in one document, where the anchor text and the ground-truth type disagree with
each other. Confirmed by direct inspection: `kupna_zmluva_000.docx.gt.json` records
`{"surface": "Michalovciach", "type": "OBEC", ...}` for the ONLY occurrence of that word in
the document, and that occurrence's only context (both places it's extracted from) is
`"Nehnuteľnosť v k. ú. Michalovciach"`.

**Effect on the numbers reported for this task:** every doc that calls
`seed_docx_failure_modes` contributes one such mislabeled occurrence. The fix correctly
relabels it KATASTER (it IS anchored), so it now counts as an unbacked KATASTER candidate and
a lost OBEC "backed" hit under `eval/precision_report.py`'s ground-truth-overlap definition —
which is why OBEC's measured precision in the fix's own report went DOWN (44.9% -> 28.5%)
instead of up as expected going in. KATASTER's number is genuinely fixed and moved the right
way (0.0% -> 31.8%, candidates 8 -> 88) for the reason predicted; OBEC's number is depressed
by this one template bug riding along on the same corpus. The dual leak gate is unaffected
(`eval.leak_gate` still `VERDICT: PASS`, 0 leaks) because both labels redact the same span
either way — this is a report-label accuracy issue, not a redaction issue.

**Fix, for whoever owns `corpus/templates/_common.py`:** either change line 143's PiiSpec
type from `"OBEC"` to `"KATASTER"` (the text already says katastrálne územie), or change the
anchor text so it no longer reads as one. One-line change either way.
