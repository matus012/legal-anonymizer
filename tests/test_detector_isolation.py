"""CRASH SAFETY (CONTRACTS_v11.md Amendment 11): nothing a detector can raise reaches the GUI.

WHY THIS FILE EXISTS
--------------------------------------------------------------------------------------
A desktop application that raises out of a redaction is worse than one that misses a
surface. The lawyer gets a traceback instead of a document and has no way to tell whether
the file on disk is clean, partly redacted, or untouched — and the one thing they will not
do is assume the worst.

This is not a hypothetical class of bug. It has already happened in this repo: widening a
separator let a TAB into an IBAN, the mod-97 check does ``int(c, 36)``, and ``int`` raises
``ValueError`` on a tab. It reached a shipped code path and was found only because
``eval/mutation_gate.py`` happened to call ``detect()`` over 2 559 mutated surfaces. Every
checksum and validator in ``detect/`` parses characters out of arbitrary document text —
and arbitrary document text is precisely what a law office has.

TWO KINDS OF TEST HERE
--------------------------------------------------------------------------------------
1. FUZZ — feed ``detect()`` text built from control characters, lone surrogates, mixed
   scripts, format characters and the digit-like characters of other scripts, and assert
   that it returns. These reach the validators through the real dispatch, which is the path
   that matters; testing a private helper in isolation would not prove the app is safe.
2. ISOLATION — monkeypatch a detector into raising and assert that the OTHER detectors'
   results survive, that the failure is REPORTED rather than swallowed, and that it is
   attributed to the detector by name. "The tool did not crash" is not sufficient: a
   silently-skipped detector is an invisible recall hole, which is the failure mode this
   whole project is built to prevent.
"""
import random
import string

import pytest

from detect import core
from detect.core import Candidate, DetectorFailure, detect, detect_with_failures

# ------------------------------------------------------------------ fuzz alphabets
# Deliberately nasty, and every entry is something a real document can contain. Control
# characters come out of a corrupt DOCX; format characters out of a bank portal and Word's
# optional hyphen; other-script digits out of a document typed on a non-Latin layout; the
# surrogate range out of a mis-decoded byte stream.
CONTROL = "".join(chr(c) for c in range(0x00, 0x20)) + "\x7f"
FORMAT = "​‌‍‎‏⁠﻿­"
SPACES = " \t\n\r      　"
DIGITS_OTHER = "٠١٢٣٤٥٦٧٨٩" "০১২৩৪৫৬৭৮৯" "０１２３４５６７８９" "⁰¹²³⁴⁵⁶⁷⁸⁹" "ⅠⅡⅢⅣⅩ"
SCRIPTS = "абвгдежзийклмнопрстуфхцчшщ" "αβγδεζηθικλμνξοπρστυφχψω" "日本語中文한국어" "עברית" "العربية"
SLOVAK = "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ"
ASCII = string.printable

ALPHABET = CONTROL + FORMAT + SPACES + DIGITS_OTHER + SCRIPTS + SLOVAK + ASCII

# Seeds that look like real PII, so the fuzzer hits the CHECKSUM paths rather than bouncing
# off the shape regexes. A fuzz run that never reaches int(c, 36) proves nothing about it.
SEEDS = [
    "Rodné číslo: 850315/0018",
    "IČO 47123456 DIČ 1234567890",
    "IBAN SK68 0720 0002 8919 8742 6353",
    "Účet 19-8742635307/0200",
    "IČ DPH SK1234567890",
    "BIC FYCWSKZC",
    "Telefón +421 905 123 456",
    "e-mail jan.novak@advokat.sk",
    "VIN TMBJF25L1BB123456",
    "EČV BA123AB",
    "LV č. 1234, parc. č. 567/8",
    "Oddiel: Sro, Vložka č. 12345/V",
    "12Cb/345/2025",
    "Kúpna cena 12 345,67 €",
    "Dátum: 01. 01. 1980",
    "JUDr. Ján Novák, trvale bytom Hlavná 25, 040 01 Košice",
]

_SEED = 20260917


def _corrupt(rng: random.Random, text: str) -> str:
    """Apply a random handful of edits: insert, replace, delete, duplicate."""
    chars = list(text)
    for _ in range(rng.randrange(1, 8)):
        if not chars:
            break
        op = rng.randrange(4)
        at = rng.randrange(len(chars))
        if op == 0:
            chars.insert(at, rng.choice(ALPHABET))
        elif op == 1:
            chars[at] = rng.choice(ALPHABET)
        elif op == 2:
            del chars[at]
        else:
            chars.insert(at, chars[at])
    return "".join(chars)


@pytest.mark.parametrize("seed_text", SEEDS)
def test_detect_never_raises_on_corrupted_pii(seed_text):
    """200 corruptions of each PII-shaped seed. Every call must RETURN."""
    rng = random.Random(f"{_SEED}:{seed_text}")
    for trial in range(200):
        text = _corrupt(rng, seed_text)
        try:
            detect(text)
        except Exception as exc:  # noqa: BLE001 -- the assertion IS "this never happens"
            pytest.fail(
                f"detect() raised {type(exc).__name__}: {exc}\n"
                f"  trial {trial}, seed {_SEED!r}\n  input {text!r}"
            )


def test_detect_never_raises_on_pure_noise():
    """Text with no structure at all, drawn straight from the nasty alphabet."""
    rng = random.Random(f"{_SEED}:noise")
    for trial in range(500):
        text = "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 120)))
        try:
            detect(text)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"detect() raised {type(exc).__name__}: {exc} on {text!r} (trial {trial})")


def test_detect_never_raises_with_known_entities_that_are_themselves_nasty():
    """The known-entity list is USER INPUT — typed into the GUI, pasted from a case file — so
    it is exactly as untrustworthy as the document, and it feeds a stemmer and a declension
    matcher rather than a regex."""
    rng = random.Random(f"{_SEED}:known")
    for trial in range(200):
        known = ["".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 12)))
                 for _ in range(rng.randrange(0, 4))]
        text = _corrupt(rng, rng.choice(SEEDS))
        try:
            detect(text, known)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"detect() raised {type(exc).__name__}: {exc}\n"
                f"  known={known!r}\n  text={text!r} (trial {trial})"
            )


def test_the_tab_in_an_iban_case_specifically():
    """The regression that motivated all of the above. int('\\t', 36) raises ValueError."""
    for sep in ("\t", "\n", " ", "​", "\x00"):
        detect(f"IBAN SK68{sep}0720{sep}0002{sep}8919{sep}8742{sep}6353")


# --------------------------------------------------------------------------- isolation
def test_a_raising_detector_does_not_stop_the_others(monkeypatch):
    def boom(text, config=None):
        raise RuntimeError("simulated detector explosion")

    monkeypatch.setattr(core, "detect_gazetteer", boom)
    text = "Rodné číslo: 850315/0018 a IČO 47123456"
    candidates, failures = detect_with_failures(text)

    types = {c.type for c in candidates}
    assert "RODNE_CISLO" in types and "ICO" in types, (
        "one detector failing must not cost the others their results"
    )
    assert any(f.detector == "detect_gazetteer" for f in failures)
    assert any("simulated detector explosion" in f.error for f in failures)


def test_the_failure_names_the_detector_and_the_error():
    """A report that says "a detector failed" without saying WHICH or WHY cannot be acted on."""
    f = DetectorFailure("detect_orgs", "ValueError: invalid literal for int() with base 36")
    assert f.detector == "detect_orgs"
    assert "ValueError" in f.error


def test_plain_detect_still_returns_a_bare_list(monkeypatch):
    """detect()'s v1 signature is frozen (CONTRACTS_v11.md §3). Everything above is additive."""
    def boom(text, config=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(core, "detect_orgs", boom)
    out = detect("IČO 47123456")
    assert isinstance(out, list)
    assert all(isinstance(c, Candidate) for c in out)


def test_a_detector_returning_a_malformed_span_is_dropped_and_attributed(monkeypatch):
    """Validated at the detector, not at the post-conditions. A span of (12, 4) discovered
    after five resolution stages have shuffled the list is a bug report with no author on it."""
    def bad(text, config=None):
        return [Candidate(type="ORG", surface="x", start=999, end=1200, auto=True)]

    monkeypatch.setattr(core, "detect_orgs", bad)
    candidates, failures = detect_with_failures("IČO 47123456")
    assert all(c.type != "ORG" for c in candidates)
    assert any(f.detector == "detect_orgs" and "outside text" in f.error for f in failures)


def test_a_detector_returning_an_unregistered_type_is_dropped_and_attributed(monkeypatch):
    text = "IČO 47123456"
    start, end = text.index("47123456"), len(text)

    def bad(t, config=None):
        # An IN-RANGE span on purpose: _validated checks the span BEFORE the type, so an
        # out-of-range span would be rejected for the wrong reason and this test would pass
        # without ever exercising the registry check.
        return [Candidate(type="NOT_A_REAL_TYPE", surface="47123456", start=start, end=end,
                          auto=True)]

    monkeypatch.setattr(core, "detect_orgs", bad)
    candidates, failures = detect_with_failures(text)
    assert all(c.type != "NOT_A_REAL_TYPE" for c in candidates)
    assert any("unregistered type" in f.error for f in failures)


def test_the_same_failure_is_reported_once_across_both_views(monkeypatch):
    """detect() runs the battery over two normalized views when a wrapped identifier is
    present. The same detector raises the same way on both, and reporting it twice would tell
    the reviewer there were two problems."""
    def boom(text, config=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(core, "detect_orgs", boom)
    text = "BIC FYC\nWSKZC a IČO 47123456"
    _, failures = detect_with_failures(text)
    assert len([f for f in failures if f.detector == "detect_orgs"]) == 1


def test_no_failures_on_ordinary_text():
    """The channel must be quiet when nothing is wrong, or nobody will read it."""
    _, failures = detect_with_failures(
        "JUDr. Ján Novák, rodné číslo 850315/0018, bytom Hlavná 25, 040 01 Košice."
    )
    assert failures == []
