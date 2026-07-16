"""TDD spec for detect/ round 1: the five checksum/format-bearing identifier types
(context.md §4.1, §6). Fixtures are hand-built literal strings — never derived from
data/ or from the corpus generator (corpus/pii/* is a dev-only fixture generator and
must not be imported here or by detect/ itself).

Checksum-valid literals below were computed independently from the spec's algorithm
description (mod-11 / weighted-mod-11 / mod-97), not by calling corpus.pii.*.

Central rule under test:
    shape valid + checksum valid   -> Candidate(auto=True)
    shape valid + checksum invalid -> Candidate(auto=False)   (still detected, review bucket)
    shape invalid                  -> no Candidate

DIC and IC_DPH carry NO documented checksum (context.md §4.1: "10 digits" / "SK + DIČ"
only; corpus/pii/dic.py has no is_valid at all). For those two types the rule collapses to:
    shape valid   -> Candidate(auto=True)
    shape invalid -> no Candidate
There is no checksum-broken/auto=False case for DIC or IC_DPH — confirmed with the user
before writing this file.
"""
from detect import detect


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


# --------------------------------------------------------------------------- RODNE_CISLO
def test_rc_valid_detected_auto_true():
    # 850315/0018: digits 8503150018 % 11 == 0 (independently verified)
    text = "Narodil sa 850315/0018 v Košiciach."
    hits = _find(detect(text), "RODNE_CISLO", "850315/0018")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_rc_checksum_broken_shape_intact_detected_auto_false():
    # break the last digit of the valid RC above: 0018 -> 0019 (still RC-shaped, fails mod11)
    text = "Narodil sa 850315/0019 v Košiciach."
    hits = _find(detect(text), "RODNE_CISLO", "850315/0019")
    assert len(hits) == 1
    assert hits[0].auto is False


def test_rc_shape_broken_not_detected():
    # only 9 digits after the slash-split (6+3) — not RC-shaped
    text = "Kód 850315/001 nie je rodné číslo."
    assert _find(detect(text), "RODNE_CISLO", "850315/001") == []
    assert not any(c.type == "RODNE_CISLO" for c in detect(text))


def test_rc_offsets_correct_against_surrounding_text():
    text = "Narodil sa 850315/0018 v Košiciach."
    hits = _find(detect(text), "RODNE_CISLO", "850315/0018")
    assert len(hits) == 1
    c = hits[0]
    assert text[c.start : c.end] == "850315/0018"
    assert c.start == text.index("850315/0018")
    assert c.end == c.start + len("850315/0018")


# --------------------------------------------------------------------------- ICO
def test_ico_valid_detected_auto_true():
    # 12345679: weighted checksum over 1234567 with weights 8..2 -> check digit 9 (verified)
    text = "IČO: 12345679, sídlo Bratislava."
    hits = _find(detect(text), "ICO", "12345679")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_ico_checksum_broken_shape_intact_detected_auto_false():
    # last digit flipped: 12345679 -> 12345670 (still 8 digits, fails weighted checksum)
    text = "IČO: 12345670, sídlo Bratislava."
    hits = _find(detect(text), "ICO", "12345670")
    assert len(hits) == 1
    assert hits[0].auto is False


def test_ico_shape_broken_not_detected():
    text = "IČO: 1234567, sídlo Bratislava."  # only 7 digits
    assert not any(c.type == "ICO" for c in detect(text))


def test_ico_offsets_correct_against_surrounding_text():
    text = "IČO: 12345679, sídlo Bratislava."
    hits = _find(detect(text), "ICO", "12345679")
    c = hits[0]
    assert text[c.start : c.end] == "12345679"
    assert c.start == text.index("12345679")


# --------------------------------------------------------------------------- DIC (shape-only)
def test_dic_valid_shape_detected_auto_true():
    text = "DIČ 1234567890 je uvedené v zmluve."
    hits = _find(detect(text), "DIC", "1234567890")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_dic_shape_broken_not_detected():
    text = "DIČ 123456789 je uvedené v zmluve."  # 9 digits
    assert not any(c.type == "DIC" for c in detect(text))
    text2 = "DIČ 12345678901 je uvedené v zmluve."  # 11 digits
    assert not any(c.type == "DIC" for c in detect(text2))


def test_dic_offsets_correct_against_surrounding_text():
    text = "DIČ 1234567890 je uvedené v zmluve."
    hits = _find(detect(text), "DIC", "1234567890")
    c = hits[0]
    assert text[c.start : c.end] == "1234567890"
    assert c.start == text.index("1234567890")


# --------------------------------------------------------------------------- IC_DPH (shape-only)
def test_ic_dph_valid_shape_detected_auto_true():
    text = "IČ DPH: SK1234567890, platca DPH."
    hits = _find(detect(text), "IC_DPH", "SK1234567890")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_ic_dph_shape_broken_not_detected():
    text = "IČ DPH: SK123456789, platca DPH."  # only 9 digits after SK
    assert not any(c.type == "IC_DPH" for c in detect(text))


def test_ic_dph_offsets_correct_against_surrounding_text():
    text = "IČ DPH: SK1234567890, platca DPH."
    hits = _find(detect(text), "IC_DPH", "SK1234567890")
    c = hits[0]
    assert text[c.start : c.end] == "SK1234567890"
    assert c.start == text.index("SK1234567890")


def test_ic_dph_precedence_over_bare_dic_same_digits():
    # "SK" + 10 digits must be claimed by IC_DPH only; the bare-DIC detector must not
    # also fire on the same 10 digits (no double-claim of one span across these two types).
    text = "IČ DPH: SK1234567890, platca DPH."
    cands = detect(text)
    assert _find(cands, "IC_DPH", "SK1234567890") != []
    assert _find(cands, "DIC", "1234567890") == []


# --------------------------------------------------------------------------- IBAN
def test_iban_valid_detected_auto_true():
    # SK94 0200 0000 0000 0000 0001 — mod97 verified independently (residue == 1)
    text = "Účet: SK9402000000000000000001, splatnosť do 30 dní."
    hits = _find(detect(text), "IBAN", "SK9402000000000000000001")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_iban_checksum_broken_shape_intact_detected_auto_false():
    # check digits flipped 94 -> 95, keeps SK + 22 digits shape, fails mod97
    text = "Účet: SK9502000000000000000001, splatnosť do 30 dní."
    hits = _find(detect(text), "IBAN", "SK9502000000000000000001")
    assert len(hits) == 1
    assert hits[0].auto is False


def test_iban_shape_broken_not_detected():
    text = "Účet: SK940200000000000000001, koniec."  # 21 digits after SK, not 22
    assert not any(c.type == "IBAN" for c in detect(text))


def test_iban_offsets_correct_against_surrounding_text():
    text = "Účet: SK9402000000000000000001, splatnosť do 30 dní."
    hits = _find(detect(text), "IBAN", "SK9402000000000000000001")
    c = hits[0]
    assert text[c.start : c.end] == "SK9402000000000000000001"
    assert c.start == text.index("SK9402000000000000000001")


def test_iban_legacy_domestic_form_valid_detected_auto_true():
    # 123406-1234567805/1100: prefix weighted-mod11 and base weighted-mod11 both
    # independently verified to sum to 0 mod 11.
    text = "Bankové spojenie: 123406-1234567805/1100."
    hits = _find(detect(text), "BANKOVY_UCET", "123406-1234567805/1100")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_iban_legacy_domestic_form_checksum_broken_detected_auto_false():
    # break the base's last digit: 1234567805 -> 1234567806 (still shaped, fails weighted mod11)
    text = "Bankové spojenie: 123406-1234567806/1100."
    hits = _find(detect(text), "BANKOVY_UCET", "123406-1234567806/1100")
    assert len(hits) == 1
    assert hits[0].auto is False


def test_iban_legacy_domestic_form_shape_broken_not_detected():
    text = "Bankové spojenie: 123406-1234567805-1100."  # no slash before bank code
    assert not any(c.type in ("IBAN", "BANKOVY_UCET") for c in detect(text))


# ------------------------------------------------------------ adjacency / disambiguation
def test_dic_and_ico_adjacent_both_detected_no_cross_contamination():
    # a 10-digit DIC directly followed by an 8-digit ICO, space-separated
    text = "DIČ 1234567890 IČO 12345679 v jednej vete."
    cands = detect(text)
    assert _find(cands, "DIC", "1234567890") != []
    assert _find(cands, "ICO", "12345679") != []


def test_bare_eight_digit_run_on_is_not_detected_as_ico():
    # an 11-digit run (e.g. a glued house/parcel number) contains an 8-digit substring
    # but is not a standalone 8-digit token; the ICO detector must not carve a match out
    # of the middle of a longer digit run.
    text = "Parcela č. 12345678901 v katastri."
    assert not any(c.type == "ICO" for c in detect(text))


# ------------------------------------------------------ FLAG-SURVIVAL PRECEDENCE RULE
# A slashless, checksum-invalid RČ is a bare 10-digit run and is therefore ALSO shaped
# like a DIC. The RC detector correctly flags it auto=False (review); the DIC detector,
# blind to RC semantics, would flag the identical span auto=True (auto-redact) — an
# auto=True verdict must never survive when another detector calls the same span a
# checksum failure, or the review-bucket routing is silently defeated.
def test_slashless_checksum_invalid_rc_wins_over_dic_auto_true():
    # 8503150019: RC-shaped (month 03, day 15), fails mod11 (verified independently)
    text = "Rodné číslo 8503150019 uvedené v žiadosti."
    cands = [c for c in detect(text) if (c.start, c.end) == (text.index("8503150019"), text.index("8503150019") + 10)]
    assert len(cands) == 1
    assert cands[0].type == "RODNE_CISLO"
    assert cands[0].auto is False
    assert not any(c.auto is True for c in cands)


def test_slashless_checksum_valid_rc_not_regressed():
    # 8503150018: RC-shaped, divisible by 11 (verified independently)
    text = "Rodné číslo 8503150018 uvedené v žiadosti."
    hits = _find(detect(text), "RODNE_CISLO", "8503150018")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_genuine_dic_not_rc_shaped_still_auto_true():
    # digits[2:4] == "34" -> no plausible RC month offset, so this is DIC-only, not RC
    text = "Zmluvná strana má DIČ 1234567890 podľa výpisu."
    hits = _find(detect(text), "DIC", "1234567890")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert not any(c.type == "RODNE_CISLO" for c in detect(text))


# ------------------------------------------------------ TYPE PRECEDENCE (exact-span collision)
# A slashless, checksum-VALID RC is a bare 10-digit run, so both RC and DIC detectors
# agree auto=True on the identical span. Flag-survival precedence does not fire here
# (no disagreement) -- type precedence must still collapse the span to one candidate.
def test_slashless_checksum_valid_rc_single_candidate_no_dic_duplicate():
    text = "Rodné číslo 8503150018 uvedené v žiadosti."
    start = text.index("8503150018")
    end = start + len("8503150018")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, end)]
    assert len(cands) == 1
    assert cands[0].type == "RODNE_CISLO"
    assert cands[0].auto is True
    assert _find(detect(text), "DIC", "8503150018") == []


def test_detect_never_returns_two_candidates_on_identical_span():
    text = (
        "Rodné číslo 8503150018, IČO 12345679, IČ DPH SK1234567890, "
        "DIČ 1234567890, IBAN SK9402000000000000000001."
    )
    cands = detect(text)
    spans = [(c.start, c.end) for c in cands]
    assert len(set(spans)) == len(spans)
