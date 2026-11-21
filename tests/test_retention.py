"""§8.3 retention gate (context.md rejection round 3, defect B2) — the empty-file blind spot.

The leak test (`eval.leak`) and recall (`eval.metrics`) only ask whether GT PII surfaces
survive in the output. Neither asks whether the REST of the document survived. A redactor
that emits a valid, empty file scores zero leaks and 100%% recall on every type — there is
nothing left to leak — and both gates report PASS. Retention measures the complementary
question directly: how much of the document's non-PII content is still there.

Unit: unicode word tokens of the ORIGINAL (pre-redaction) text, EXCLUDING any token whose
span overlaps a recorded auto_redact/should_flag PII occurrence (found by exact offset, not
by rewriting the text — see eval/retention.py). Each remaining token must be found in the
REDACTED output's RAW, UNMASKED token multiset — the redacted side is never altered before
counting; a prior version masked it too and was rejected for it (round 3, B2).
"""
from __future__ import annotations

from eval.extract import ExtractResult
from eval.retention import score


def test_full_survival_when_output_equals_original_minus_pii():
    gt = {"pii": [{"surface": "Ján Novák", "auto_redact": True, "should_flag": False}]}
    text = "Ján Novák podpísal zmluvu dnes v Košiciach."
    original = ExtractResult(full_text=text, by_surface={"body": text})
    redacted_text = "[MENO_1] podpísal zmluvu dnes v Košiciach."
    redacted = ExtractResult(full_text=redacted_text, by_surface={"body": redacted_text})
    survived, total = score(gt, original, redacted)
    assert total > 0
    assert survived == total


def test_empty_output_scores_zero_survival():
    gt = {"pii": [{"surface": "Ján Novák", "auto_redact": True, "should_flag": False}]}
    text = "Ján Novák podpísal zmluvu dnes v Košiciach."
    original = ExtractResult(full_text=text, by_surface={"body": text})
    redacted = ExtractResult(full_text="", by_surface={"body": ""})
    survived, total = score(gt, original, redacted)
    assert total > 0
    assert survived == 0


def test_pii_surfaces_are_excluded_from_the_denominator():
    # A doc that is ENTIRELY a PII surface has nothing left to measure.
    gt = {"pii": [{"surface": "Ján Novák", "auto_redact": True, "should_flag": False}]}
    original = ExtractResult(full_text="Ján Novák", by_surface={"body": "Ján Novák"})
    redacted = ExtractResult(full_text="[MENO_1]", by_surface={"body": "[MENO_1]"})
    survived, total = score(gt, original, redacted)
    assert total == 0
    assert survived == 0


def test_partial_destruction_scores_partial_retention():
    gt = {"pii": [{"surface": "Ján Novák", "auto_redact": True, "should_flag": False}]}
    text = "Ján Novák podpísal zmluvu dnes v Košiciach pred notárom."
    original = ExtractResult(full_text=text, by_surface={"body": text})
    # only half the non-PII tokens survive
    redacted_text = "podpísal zmluvu dnes"
    redacted = ExtractResult(full_text=redacted_text, by_surface={"body": redacted_text})
    survived, total = score(gt, original, redacted)
    assert 0 < survived < total


def test_missing_tokens_cannot_hide_behind_one_surviving_duplicate():
    # original has "zmluvu" twice (non-PII); redacted keeps only one occurrence.
    gt = {"pii": []}
    original = ExtractResult(full_text="zmluvu a zmluvu", by_surface={"body": "zmluvu a zmluvu"})
    redacted = ExtractResult(full_text="zmluvu", by_surface={"body": "zmluvu"})
    survived, total = score(gt, original, redacted)
    assert total == 3  # zmluvu, a, zmluvu
    assert survived == 1  # only one "zmluvu" occurrence actually present


def test_metadata_boilerplate_does_not_inflate_retention():
    # Regression: DOCX/PDF metadata is kept as raw XML/dict-dump text by the extractor (so an
    # attribute-embedded leak is still caught, see extract.py) — but that means structural
    # boilerplate (tag/attribute names) is IDENTICAL across any two freshly generated files of
    # the same format, regardless of how much real content survived. A "scorch" run against a
    # real corpus measured 64.8%% DOCX retention on totally blank documents before this was
    # fixed — the metadata tag soup alone was scoring as "surviving content".
    gt = {"pii": []}
    boilerplate = "<coreProperties><dc:creator>python-docx</dc:creator></coreProperties>"
    original = ExtractResult(
        full_text="Toto je skutočný text zmluvy medzi stranami." + boilerplate,
        by_surface={
            "body": "Toto je skutočný text zmluvy medzi stranami.",
            "core_xml": boilerplate,
        },
    )
    redacted = ExtractResult(
        full_text=boilerplate,
        by_surface={"body": "", "core_xml": boilerplate},
    )
    survived, total = score(gt, original, redacted)
    assert survived == 0, "metadata boilerplate token overlap must not count as survival"


def test_glued_pii_token_is_excluded_not_split():
    # DOCX paragraph/run text reconstructs with NO separator (context.md §10), so a PII
    # surface can be glued directly to non-PII text: "...účastníka865527/9776 je...". The
    # combined token "účastníka865527/9776" is dropped from the denominator entirely — not
    # rewritten/split — since it overlaps a PII span and cannot be cleanly attributed as
    # pure non-PII content. Only the clean surrounding words are counted.
    gt = {"pii": [{"surface": "865527/9776", "auto_redact": True, "should_flag": False}]}
    original_text = "Rodné číslo účastníka865527/9776 je uvedené vyššie."
    original = ExtractResult(full_text=original_text, by_surface={"body": original_text})
    redacted_text = "Rodné číslo [REDACTED] je uvedené vyššie."
    redacted = ExtractResult(full_text=redacted_text, by_surface={"body": redacted_text})
    survived, total = score(gt, original, redacted)
    # "Rodné", "číslo", "je", "uvedené", "vyššie" survive; the glued compound is excluded.
    assert total == 5
    assert survived == 5


def test_decoy_glued_to_content_is_ordinary_content_not_excluded():
    # A decoy is not a PII span (it is deliberately excluded from _pii_spans), so a token
    # glued to a decoy is just ordinary content: counted normally, and must be found intact
    # in the (correctly untouched) redacted text — no special-casing needed.
    gt = {"pii": [{"surface": "Strana 5 z 17", "auto_redact": False, "should_flag": False}]}
    text = "Faktúra (nie PII)Strana 5 z 17Ďalšie údaje nasledujú."
    original = ExtractResult(full_text=text, by_surface={"body": text})
    redacted = ExtractResult(full_text=text, by_surface={"body": text})  # decoy untouched
    survived, total = score(gt, original, redacted)
    assert survived == total


def test_flag_span_excluded_like_auto_redact():
    # greedy_redactor over-redacts should_flag items on purpose (that's what the flag gate is
    # for) — retention must not ALSO penalize that, or a redactor could never fail the flag
    # gate "alone". should_flag spans are excluded from the denominator just like auto_redact.
    gt = {"pii": [{"surface": "865527/9776", "auto_redact": False, "should_flag": True}]}
    original_text = "Rodné číslo 865527/9776 je uvedené vyššie."
    original = ExtractResult(full_text=original_text, by_surface={"body": original_text})
    redacted_text = "Rodné číslo [REDACTED] je uvedené vyššie."
    redacted = ExtractResult(full_text=redacted_text, by_surface={"body": redacted_text})
    survived, total = score(gt, original, redacted)
    assert survived == total


def test_redacted_side_is_never_masked_pii_left_in_output_counts_as_present():
    # B2 (round 3 blocker): retention must not delete PII from the redacted side before
    # counting. Construct a case where the ONLY way to get survived == total is if the
    # redacted text is read literally, untouched: a non-PII word directly adjacent to PII
    # that a redactor left completely alone (a no-op on that specific span). If retention
    # masked the redacted side, this would still pass — the real proof is the corpus-level
    # invariants in tests/test_baselines.py (null/greedy ~1.0, scorch/empty_output ~0.0),
    # which only hold when the redacted side is read as-is.
    gt = {"pii": [{"surface": "SK1234567890", "auto_redact": True, "should_flag": False}]}
    text = "Účet SK1234567890 patrí klientovi."
    original = ExtractResult(full_text=text, by_surface={"body": text})
    redacted = ExtractResult(full_text=text, by_surface={"body": text})  # no-op: PII untouched
    survived, total = score(gt, original, redacted)
    assert total == 3  # Účet, patrí, klientovi — SK1234567890 excluded (it's the PII span)
    assert survived == 3
