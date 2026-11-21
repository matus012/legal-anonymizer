"""TDD spec for detect/documents.py (v1.1 round B2, CONTRACTS_v11.md §8): CISLO_OP,
CISLO_PASU, VODICSKY_PREUKAZ, ECV, VIN, BIC.

Fixtures are hand-built literal strings -- this file must NOT import corpus/. The module
under test is standalone this round (not yet wired into detect.core.detect()), so tests
call ``detect_documents(text, DEFAULT)`` directly.
"""
from detect.config import DEFAULT
from detect.documents import detect_documents

NBSP = " "


def _find(text, type_):
    return [c for c in detect_documents(text, DEFAULT) if c.type == type_]


def _assert_single(text, type_, surface):
    hits = [c for c in _find(text, type_) if c.surface == surface]
    assert len(hits) == 1, (text, detect_documents(text, DEFAULT))
    c = hits[0]
    assert c.auto is True
    assert c.checksum == "n/a"
    assert text[c.start : c.end] == surface


# --------------------------------------------------------------------------- CISLO_OP
def test_op_anchored_space_detected():
    _assert_single("Občiansky preukaz AB 123456 bol predložený.", "CISLO_OP", "AB 123456")


def test_op_anchored_nbsp_detected():
    surface = f"AB{NBSP}123456"
    _assert_single(f"Doklad totožnosti {surface} overený.", "CISLO_OP", surface)


def test_op_anchored_no_separator_detected():
    _assert_single("OP č. CD654321 priložený k žiadosti.", "CISLO_OP", "CD654321")


def test_op_anchor_variant_c_op_detected():
    _assert_single("Podľa č. OP CD654321 vydaného v Košiciach.", "CISLO_OP", "CD654321")


def test_op_unanchored_standalone_detected():
    _assert_single("V texte sa spomína EF112233 bez ďalšieho označenia.", "CISLO_OP", "EF112233")


def test_op_unanchored_not_standalone_not_detected():
    # preceded by a letter -- part of a longer letter run, not a standalone OP shape
    text = "Kód XEF112233 v systéme."
    assert _find(text, "CISLO_OP") == []


def test_op_seven_digit_run_not_claimed():
    # "AB1234567" is a 7-digit PASU shape, not an OP; guarded by (?!\d)
    assert _find("Doklad AB1234567 predložený.", "CISLO_OP") == []


# --------------------------------------------------------------------------- CISLO_PASU
def test_pasu_anchored_space_detected():
    _assert_single("Cestovný pas AB 1234567 je platný.", "CISLO_PASU", "AB 1234567")


def test_pasu_anchored_nbsp_detected():
    surface = f"AB{NBSP}1234567"
    _assert_single(f"Č. pasu {surface} overené.", "CISLO_PASU", surface)


def test_pasu_unanchored_standalone_detected():
    _assert_single("Uvedené GH7654321 v prílohe.", "CISLO_PASU", "GH7654321")


def test_pasu_seven_digits_not_op():
    text = "Doklad AB1234567 predložený."
    hits = _find(text, "CISLO_PASU")
    assert len(hits) == 1
    assert hits[0].surface == "AB1234567"
    assert _find(text, "CISLO_OP") == []


# --------------------------------------------------------------------------- VODICSKY_PREUKAZ
def test_vp_anchor_full_phrase_detected():
    _assert_single(
        "Vodičský preukaz č. SK1234567 bol odobratý.", "VODICSKY_PREUKAZ", "SK1234567"
    )


def test_vp_anchor_short_form_detected():
    _assert_single("VP č. AB123456 platí do roku 2030.", "VODICSKY_PREUKAZ", "AB123456")


def test_vp_anchor_vodicak_detected():
    _assert_single("Podľa vodičák: XY98765 predloženého.", "VODICSKY_PREUKAZ", "XY98765")


def test_vp_no_anchor_not_detected():
    assert _find("V texte sa spomína SK1234567 bez ďalšieho označenia.", "VODICSKY_PREUKAZ") == []


# --------------------------------------------------------------------------- ECV
def test_ecv_no_separator_detected():
    _assert_single("Vozidlo s ECV KE123AB stálo na parkovisku.", "ECV", "KE123AB")


def test_ecv_dash_detected():
    _assert_single("Vozidlo evidované ako KE-123AB.", "ECV", "KE-123AB")


def test_ecv_spaced_detected():
    _assert_single("Značka BA 123 XY bola zaznamenaná.", "ECV", "BA 123 XY")


def test_ecv_space_before_letters_only_detected():
    _assert_single("Auto s tabuľkou KE 123AB prišlo.", "ECV", "KE 123AB")


def test_ecv_nbsp_detected():
    surface = f"KE{NBSP}123{NBSP}AB"
    _assert_single(f"Tabuľka {surface} zaznamenaná kamerou.", "ECV", surface)


# --------------------------------------------------------------------------- VIN
_VIN_BASE = "1HGCM82633A123456"  # 17 chars, digit+letter mix, no I/O/Q


def test_vin_valid_detected():
    assert len(_VIN_BASE) == 17
    _assert_single(f"Vozidlo VIN: {_VIN_BASE} bolo skontrolované.", "VIN", _VIN_BASE)


def test_vin_all_letters_no_digit_not_detected():
    # 17-letter Slovak-looking word (ASCII caps), no digit -> must not be a VIN
    word17 = "NEPRECHADZATELNEX"
    assert len(word17) == 17
    assert not any(c.isdigit() for c in word17)
    hits = _find(f"Text obsahuje {word17} v strede.", "VIN")
    assert hits == []


def test_vin_with_forbidden_letter_i_not_detected():
    # same 17-char shape as _VIN_BASE, but the '8' is swapped for 'I' (excluded letter)
    bad = _VIN_BASE.replace("8", "I", 1)
    assert len(bad) == 17
    hits = _find(f"Kód {bad} zaznamenaný.", "VIN")
    assert hits == []


def test_vin_with_forbidden_letter_o_not_detected():
    bad = _VIN_BASE.replace("8", "O", 1)
    assert len(bad) == 17
    hits = _find(f"Kód {bad} zaznamenaný.", "VIN")
    assert hits == []


def test_vin_with_forbidden_letter_q_not_detected():
    bad = _VIN_BASE.replace("8", "Q", 1)
    assert len(bad) == 17
    hits = _find(f"Kód {bad} zaznamenaný.", "VIN")
    assert hits == []


def test_vin_all_digits_not_detected():
    digits17 = "12345678901234567"
    hits = _find(f"Číslo {digits17} v poznámke.", "VIN")
    assert hits == []


# --------------------------------------------------------------------------- BIC
def test_bic_anchored_detected():
    _assert_single("BIC: TATRSKBX prevodu.", "BIC", "TATRSKBX")


def test_bic_swift_anchor_detected():
    _assert_single("SWIFT kód GIBASKBX je potrebný.", "BIC", "GIBASKBX")


def test_bic_sk_country_position_detected_without_anchor():
    # no BIC/SWIFT anchor at all, but positions 5-6 are "SK"
    _assert_single("Uvedený kód TATRSKBX v platobnom príkaze.", "BIC", "TATRSKBX")


def test_bic_all_caps_slovak_word_not_detected():
    for word in ("ROZHODNUTIE", "SPLNOMOCNENIE"):
        hits = _find(f"Vydané {word} vo veci.", "BIC")
        assert hits == [], (word, hits)


def test_bic_all_caps_non_sk_without_anchor_not_detected():
    # 8-letter all-caps run, positions 5-6 are NOT "SK", no anchor present
    hits = _find("Kód DEUTDEFF v texte bez oznacenia.", "BIC")
    assert hits == []


def test_bic_with_branch_code_anchored_detected():
    _assert_single("BIC: TATRSKBXXXX v prevode.", "BIC", "TATRSKBXXXX")
