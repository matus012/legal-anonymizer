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
