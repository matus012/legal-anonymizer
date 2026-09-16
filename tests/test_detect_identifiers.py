"""TDD spec for detect/ round 1: the five checksum/format-bearing identifier types
(context.md §4.1, §6). Fixtures are hand-built literal strings — never derived from
data/ or from the corpus generator (corpus/pii/* is a dev-only fixture generator and
must not be imported here or by detect/ itself).

Checksum-valid literals below were computed independently from the spec's algorithm
description (mod-11 / weighted-mod-11 / mod-97), not by calling corpus.pii.*.

Central rule under test — REWRITTEN for v1.1 (CONTRACTS_v11.md §6, policy A1: the checksum
is a TAG, not a filter). Every checksum case below is asserted as a PAIR, default config and
DetectConfig(strict_checksums=True):

    shape valid + checksum valid   -> auto=True,  checksum="valid"   (both configs)
    shape valid + checksum invalid -> auto=True,  checksum="invalid" (DEFAULT — v1.1 change)
                                      auto=False, checksum="invalid" (strict_checksums=True,
                                                                      v1 behaviour restored)
    shape invalid                  -> no Candidate                   (both configs)

The v1 assertions (auto=False under the default config) were the OLD contract; they are
converted, not deleted, so the strict half of each pair still pins the v1 semantics.

DIC and IC_DPH carry NO documented checksum (context.md §4.1: "10 digits" / "SK + DIČ"
only; corpus/pii/dic.py has no is_valid at all). For those two types the rule collapses to:
    shape valid   -> Candidate(auto=True, checksum="n/a")
    shape invalid -> no Candidate
There is no checksum-broken/auto=False case for DIC or IC_DPH — confirmed with the user
before writing this file.
"""
from detect import detect
from detect.config import DetectConfig

STRICT = DetectConfig(strict_checksums=True)


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


# --------------------------------------------------------------------------- RODNE_CISLO
def test_rc_valid_detected_auto_true():
    # 850315/0018: digits 8503150018 % 11 == 0 (independently verified)
    text = "Narodil sa 850315/0018 v Košiciach."
    hits = _find(detect(text), "RODNE_CISLO", "850315/0018")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_rc_checksum_broken_shape_intact_detected_auto_tagged_invalid():
    # break the last digit of the valid RC above: 0018 -> 0019 (still RC-shaped, fails mod11)
    text = "Narodil sa 850315/0019 v Košiciach."
    hits = _find(detect(text), "RODNE_CISLO", "850315/0019")
    assert len(hits) == 1
    assert hits[0].auto is True  # v1.1: redacted anyway, recall over precision
    assert hits[0].checksum == "invalid"


def test_rc_checksum_broken_strict_checksums_restores_review_bucket():
    text = "Narodil sa 850315/0019 v Košiciach."
    hits = _find(detect(text, None, STRICT), "RODNE_CISLO", "850315/0019")
    assert len(hits) == 1
    assert hits[0].auto is False  # v1 behaviour, restored exactly
    assert hits[0].checksum == "invalid"


def test_rc_nine_digit_form_is_a_valid_shape_not_a_broken_one():
    # v1 treated 6+3 as shape-broken. CONTRACTS_v11.md §6a: that is the pre-1954 form —
    # a real rodné číslo that simply HAS no checksum. See tests/test_detect_rc_shapes.py
    # for the full §6a clause coverage.
    text = "Kód 850315/001 je staré rodné číslo."
    hits = _find(detect(text), "RODNE_CISLO", "850315/001")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert hits[0].checksum == "n/a"


def test_rc_shape_broken_not_detected():
    # month 34 has no plausible +0/+20/+50/+70 offset -> not RC-shaped at either length
    for surface in ("853415/0010", "853415/001"):
        text = f"Kód {surface} nie je rodné číslo."
        assert _find(detect(text), "RODNE_CISLO", surface) == []
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


def test_ico_checksum_broken_shape_intact_detected_auto_tagged_invalid():
    # last digit flipped: 12345679 -> 12345670 (still 8 digits, fails weighted checksum)
    text = "IČO: 12345670, sídlo Bratislava."
    hits = _find(detect(text), "ICO", "12345670")
    assert len(hits) == 1
    assert hits[0].auto is True  # a mistyped IČO is still an IČO
    assert hits[0].checksum == "invalid"


def test_ico_checksum_broken_strict_checksums_restores_review_bucket():
    text = "IČO: 12345670, sídlo Bratislava."
    hits = _find(detect(text, None, STRICT), "ICO", "12345670")
    assert len(hits) == 1
    assert hits[0].auto is False
    assert hits[0].checksum == "invalid"


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


def test_iban_checksum_broken_shape_intact_detected_auto_tagged_invalid():
    # check digits flipped 94 -> 95, keeps SK + 22 digits shape, fails mod97
    text = "Účet: SK9502000000000000000001, splatnosť do 30 dní."
    hits = _find(detect(text), "IBAN", "SK9502000000000000000001")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert hits[0].checksum == "invalid"


def test_iban_checksum_broken_strict_checksums_restores_review_bucket():
    text = "Účet: SK9502000000000000000001, splatnosť do 30 dní."
    hits = _find(detect(text, None, STRICT), "IBAN", "SK9502000000000000000001")
    assert len(hits) == 1
    assert hits[0].auto is False
    assert hits[0].checksum == "invalid"


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


def test_iban_legacy_domestic_form_checksum_broken_detected_auto_tagged_invalid():
    # break the base's last digit: 1234567805 -> 1234567806 (still shaped, fails weighted mod11)
    text = "Bankové spojenie: 123406-1234567806/1100."
    hits = _find(detect(text), "BANKOVY_UCET", "123406-1234567806/1100")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert hits[0].checksum == "invalid"


def test_iban_legacy_domestic_form_checksum_broken_strict_restores_review_bucket():
    text = "Bankové spojenie: 123406-1234567806/1100."
    hits = _find(detect(text, None, STRICT), "BANKOVY_UCET", "123406-1234567806/1100")
    assert len(hits) == 1
    assert hits[0].auto is False
    assert hits[0].checksum == "invalid"


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


# --------------------------------------- A SLASHLESS RUN NEEDS AN RČ ANCHOR (v1.1 §6a)
# v1 rule: "a rodné číslo is ALWAYS written with a slash, so a bare 10-digit run is a DIČ."
# CONTRACTS_v11.md §6a narrows that: the separator-less form IS a rodné číslo, but ONLY when
# an RČ context anchor (r.č. / rč / rodné číslo / rodného čísla / nar.) stands within 40
# characters before it. WITHOUT an anchor the v1 rule holds unchanged and the run stays a
# DIČ — matching every bare 10-digit run would claim every such number in every document.
# The v1 intent (a bare run must never end up un-redacted) is preserved under both branches:
# unanchored it is an auto=True DIČ, anchored it is an auto=True RODNE_CISLO.
def test_slashless_10digit_mod11_invalid_with_anchor_is_rc_and_still_auto():
    # 8503150019: RC-shaped, mod11 != 0. The anchor "Rodné číslo" arms the contiguous form.
    text = "Rodné číslo 8503150019 uvedené v žiadosti."
    start = text.index("8503150019")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, start + 10)]
    assert len(cands) == 1
    assert cands[0].type == "RODNE_CISLO"
    assert cands[0].auto is True  # checksum-invalid, but redacted anyway (§6)
    assert cands[0].checksum == "invalid"
    # strict routes it to review; it must NOT silently fall back to being an auto DIČ
    strict = [c for c in detect(text, None, STRICT) if (c.start, c.end) == (start, start + 10)]
    assert len(strict) == 1
    assert strict[0].type == "RODNE_CISLO"
    assert strict[0].auto is False


def test_slashless_10digit_mod11_valid_with_anchor_is_rc():
    text = "Rodné číslo 8503150018 uvedené v žiadosti."
    hits = _find(detect(text), "RODNE_CISLO", "8503150018")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert hits[0].checksum == "valid"
    assert _find(detect(text), "DIC", "8503150018") == []


def test_slashless_10digit_without_anchor_is_still_a_dic_not_an_rc():
    text = "Zapísané pod položkou 8503150018 v evidencii."
    hits = _find(detect(text), "DIC", "8503150018")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert hits[0].checksum == "n/a"
    assert not any(c.type == "RODNE_CISLO" for c in detect(text))


def test_genuine_dic_not_rc_shaped_still_auto_true():
    # digits[2:4] == "34" -> no plausible RC month offset, so this is DIC-only, not RC
    text = "Zmluvná strana má DIČ 1234567890 podľa výpisu."
    hits = _find(detect(text), "DIC", "1234567890")
    assert len(hits) == 1
    assert hits[0].auto is True
    assert not any(c.type == "RODNE_CISLO" for c in detect(text))


# ------------------------------------------------------ TYPE PRECEDENCE (exact-span collision)
# An ANCHORED slashless run is claimed by BOTH the RC and the DIC detector on the same exact
# span. Exactly one candidate may survive, and it must be the stronger claim: RODNE_CISLO
# outranks DIC in _TYPE_PRECEDENCE. UNANCHORED there is no RC candidate at all and the lone
# DIC survives — in both cases exactly one auto-redacting candidate on that span.
def test_anchored_slashless_10digit_single_candidate_rc_wins_precedence():
    text = "Rodné číslo 8503150018 uvedené v žiadosti."
    start = text.index("8503150018")
    end = start + len("8503150018")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, end)]
    assert len(cands) == 1
    assert cands[0].type == "RODNE_CISLO"
    assert cands[0].auto is True


def test_unanchored_slashless_10digit_single_dic_candidate_no_rc_duplicate():
    text = "Zapísané pod položkou 8503150018 v žiadosti."
    start = text.index("8503150018")
    end = start + len("8503150018")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, end)]
    assert len(cands) == 1
    assert cands[0].type == "DIC"
    assert cands[0].auto is True
    assert _find(detect(text), "RODNE_CISLO", "8503150018") == []


# ------------------------------------------------------ NEW CONTRACT: slash is mandatory for RC
def test_slashless_10digit_is_dic_auto():
    text = "Ďalšie údaje: 2805200615"
    start = text.index("2805200615")
    end = start + len("2805200615")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, end)]
    assert len(cands) == 1
    assert cands[0].type == "DIC"
    assert cands[0].auto is True


def test_slashed_rc_checksum_tagged_not_gated():
    valid = _find(detect("850315/0018"), "RODNE_CISLO", "850315/0018")
    assert len(valid) == 1
    assert valid[0].auto is True
    assert valid[0].checksum == "valid"
    broken = _find(detect("850315/0019"), "RODNE_CISLO", "850315/0019")
    assert len(broken) == 1
    assert broken[0].auto is True  # v1.1: tag, not filter
    assert broken[0].checksum == "invalid"


def test_slashed_rc_checksum_gated_under_strict_checksums():
    broken = _find(detect("850315/0019", None, STRICT), "RODNE_CISLO", "850315/0019")
    assert len(broken) == 1
    assert broken[0].auto is False
    assert broken[0].checksum == "invalid"


def test_unanchored_slashless_run_not_claimed_as_rc():
    assert not any(c.type == "RODNE_CISLO" for c in detect("2805200615"))


def test_detect_never_returns_two_candidates_on_identical_span():
    text = (
        "Rodné číslo 8503150018, IČO 12345679, IČ DPH SK1234567890, "
        "DIČ 1234567890, IBAN SK9402000000000000000001."
    )
    cands = detect(text)
    spans = [(c.start, c.end) for c in cands]
    assert len(set(spans)) == len(spans)
