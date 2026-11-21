"""§8.1 leak test — the killer test (context.md §8).

Against the UNREDACTED corpus (equivalent to a no-op redactor), every auto_redact surface
must be reported as a leak, and should_flag / decoy surfaces must NOT be — they may
legitimately remain. This is the exact bug class §8.1 targets: text still extractable.

Matching (``eval.leak.surface_present``) excludes a match ONLY when its exact span falls
entirely inside a KNOWN decoy surface's exact span (context.md rejection round 7) — found by
literal substring search, never guessed from adjacent character class. A prior version
(round 6) tried a lowercase-continuation character-class rule and was rejected: it is not
decidable lexically whether a lowercase continuation is a real morphological suffix or a
genuine leak glued to ordinary prose by DOCX's separator-less reconstruction (context.md
§10) — "Novák"+"nadobúda" (a real word) is indistinguishable from "Novák"+"ovcov" (a real
declension) by character class alone. With no decoy list, matching is a plain, maximally
paranoid substring check — the safe default (context.md §6: recall over precision).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from corpus.generate import generate
from eval.extract import ExtractResult, extract
from eval.leak import find_leaks, surface_present


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=11, formats=["docx", "pdf"])
    return out


def _text_docs(corpus: Path):
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["text_layer"]:
            yield gt


def test_unredacted_corpus_leaks_every_auto_surface(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        leaks = find_leaks(gt, res)
        leaked = {lk.surface for lk in leaks}
        expected = {p["surface"] for p in gt["pii"] if p["auto_redact"]}
        assert expected, f"{gt['source_file']}: corpus doc has no auto-redact PII?"
        assert expected <= leaked, (
            f"{gt['source_file']}: auto surfaces not reported as leaks: {expected - leaked}"
        )


def test_should_flag_and_decoy_are_never_reported_as_leaks(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        leaked = {lk.surface for lk in find_leaks(gt, res)}
        auto = {p["surface"] for p in gt["pii"] if p["auto_redact"]}
        non_leak = {
            p["surface"] for p in gt["pii"] if not p["auto_redact"]
        } - auto  # a string that is also auto elsewhere is still a real leak
        assert not (leaked & non_leak), (
            f"{gt['source_file']}: non-leak surfaces reported: {leaked & non_leak}"
        )


def test_each_leak_names_a_physical_surface(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        for lk in find_leaks(gt, res):
            assert lk.found_in, f"{lk.surface!r} leak names no surface"
            assert set(lk.found_in) <= set(res.by_surface), lk.found_in


# --------------------------------------------------------------------------- surface_present
def test_with_no_decoy_list_matching_is_plain_paranoid_substring():
    # No decoy knowledge given -> maximally paranoid: "Kováč" embedded in the real Slovak
    # word "Kováčska" (blacksmith's) still counts as present. This is the CORRECT default —
    # exclusion only ever happens with explicit, exact decoy knowledge (see next test).
    assert surface_present("Neďaleko je Kováčska dielňa.", "Kováč")


def test_surface_inside_a_known_decoys_exact_span_is_not_present():
    # "Kováč" falls entirely inside the exact span of the recorded decoy "Kováčska dielňa" —
    # excluded only because that decoy is explicitly named, not guessed from character class.
    assert not surface_present(
        "Neďaleko je Kováčska dielňa.", "Kováč", decoy_surfaces=["Kováčska dielňa"]
    )


def test_surface_outside_any_known_decoy_span_is_still_present():
    # Same glued text, but "Kováč" here is NOT part of the named decoy — a different,
    # unrelated decoy is given, so the match must still count.
    assert surface_present(
        "Neďaleko je Kováčska dielňa.", "Kováč", decoy_surfaces=["Iný text (nie PII)"]
    )


def test_surface_glued_to_a_capitalised_word_is_still_present():
    # DOCX paragraph/run reconstruction has no separator (context.md §10): a name glued
    # directly to the next (capitalised) word with no space is still a genuine leak.
    assert surface_present("...Horváthová Zmluva o prevode...", "Horváthová")


def test_surface_glued_to_digits_is_still_present():
    assert surface_present("Rodné číslo účastníka865527/9776 je uvedené vyššie.", "865527/9776")


def test_surface_glued_to_punctuation_is_still_present():
    assert surface_present("(chybné)81837624IBAN (chybný)", "81837624")


def test_surface_at_clean_word_boundaries_is_present():
    assert surface_present("Zmluvu podpísal Ján Novák dňa 1.1.2024.", "Novák")


def test_surface_not_found_at_all_is_absent():
    assert not surface_present("Tento text neobsahuje žiadne mená.", "Novák")


def test_surface_inside_a_declined_form_is_still_present_without_decoy_knowledge():
    # "Šimko" is a literal substring of "Šimková" (a different, gender-inflected form of the
    # SAME surname family) — with no decoy list, this stays paranoid and counts as present.
    # (find_leaks itself only ever passes DECOY surfaces here, never other auto_redact
    # surfaces, so this scenario doesn't actually arise in practice — but the primitive
    # itself must not silently exclude anything it wasn't explicitly told to.)
    assert surface_present("Manželka je pani Šimková.", "Šimko")


# --------------------------------------------------------------------------- round 7: the
# lowercase-continuation character-class rule (round 6) is REJECTED — undecidable lexically.
# A GT surface glued to a lowercase word by DOCX's separator-less run reconstruction (§10) is
# indistinguishable, by character class alone, from a real morphological suffix continuing
# the same word: "Novák"+"nadobúda" (a real Slovak word, "acquires") looks identical to
# "Novák"+"ovcov" (a real declension). This is the split-run failure mode the whole project
# exists to catch — a permanent test pins it so it can never silently regress again.
def test_surface_glued_to_a_lowercase_word_with_no_separator_is_still_present():
    text = "zmluvu uzavrel Jan Novaknadobuda platnost"
    assert surface_present(text, "Jan Novak")


def test_find_leaks_catches_surface_glued_to_lowercase_word():
    gt = {
        "source_file": "x.docx",
        "must_be_refused": False,
        "pii": [{
            "surface": "Jan Novak", "type": "MENO", "auto_redact": True,
            "should_flag": False, "location": {"surface_part": "body"},
        }],
    }
    res = ExtractResult(
        full_text="zmluvu uzavrel Jan Novaknadobuda platnost",
        by_surface={"body": "zmluvu uzavrel Jan Novaknadobuda platnost"},
    )
    leaks = find_leaks(gt, res)
    assert leaks, "a GT surface glued to a lowercase word with no separator must be a leak"
    assert leaks[0].surface == "Jan Novak"


def test_find_leaks_excludes_target_inside_a_recorded_decoys_span():
    # End-to-end proof that find_leaks itself (not just surface_present) uses decoy spans
    # from the SAME document's ground truth: "Kováč" survives only inside the recorded decoy
    # "Kováčska dielňa" and must not be reported as a leak.
    gt = {
        "source_file": "x.docx",
        "must_be_refused": False,
        "pii": [
            {"surface": "Kováč", "type": "MENO", "auto_redact": True,
             "should_flag": False, "location": {"surface_part": "body"}},
            {"surface": "Kováčska dielňa", "type": "CAPITALISED_COMMON",
             "auto_redact": False, "should_flag": False,
             "location": {"surface_part": "body"}},
        ],
    }
    res = ExtractResult(
        full_text="Neďaleko je Kováčska dielňa.",
        by_surface={"body": "Neďaleko je Kováčska dielňa."},
    )
    assert find_leaks(gt, res) == []


def test_surface_present_equal_span_decoy_never_suppresses():
    # round 8: exclusion was keyed on SURFACE STRING equality tolerance (d0<=start and
    # end<=d1 allows d0==start and d1==end), so a decoy span EQUAL to the target span was
    # wrongly treated as "entirely inside". Only a STRICTLY LONGER decoy span that fully
    # covers the target may exclude a match — equal spans must never suppress.
    assert surface_present("Jan Novak", "Jan Novak", decoy_surfaces=["Jan Novak"])


def test_find_leaks_not_suppressed_by_a_decoy_surface_equal_to_the_auto_redact_surface():
    # context.md rejection round 8: a decoy entry whose surface EQUALS an auto_redact surface
    # must not blind the leak gate to it — recall governs (module docstring). The bug: exact
    # containment allowed d0==start and d1==end, so an equal-length decoy suppressed the leak
    # completely.
    gt = {
        "source_file": "x.docx",
        "must_be_refused": False,
        "pii": [
            {"surface": "Jan Novak", "type": "MENO", "auto_redact": True,
             "should_flag": False, "location": {"surface_part": "body"}},
            {"surface": "Jan Novak", "type": "CAPITALISED_COMMON",
             "auto_redact": False, "should_flag": False,
             "location": {"surface_part": "body"}},
        ],
    }
    res = ExtractResult(
        full_text="zmluvu uzavrel Jan Novak dna",
        by_surface={"body": "zmluvu uzavrel Jan Novak dna"},
    )
    leaks = find_leaks(gt, res)
    assert leaks, "a decoy surface equal to an auto_redact surface must not suppress the leak"
    assert leaks[0].surface == "Jan Novak"


def test_find_leaks_still_catches_target_that_merely_precedes_a_decoy():
    # A genuine leak of "Kováč" (clean word boundary) elsewhere in the SAME document, with
    # the decoy also present, must still be caught — the decoy only protects ITS OWN span.
    gt = {
        "source_file": "x.docx",
        "must_be_refused": False,
        "pii": [
            {"surface": "Kováč", "type": "MENO", "auto_redact": True,
             "should_flag": False, "location": {"surface_part": "body"}},
            {"surface": "Kováčska dielňa", "type": "CAPITALISED_COMMON",
             "auto_redact": False, "should_flag": False,
             "location": {"surface_part": "body"}},
        ],
    }
    res = ExtractResult(
        full_text="Pán Kováč tu pracoval. Neďaleko je Kováčska dielňa.",
        by_surface={"body": "Pán Kováč tu pracoval. Neďaleko je Kováčska dielňa."},
    )
    leaks = find_leaks(gt, res)
    assert len(leaks) == 1
    assert leaks[0].surface == "Kováč"
