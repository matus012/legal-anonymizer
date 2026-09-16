"""TDD spec for detect/office_refs.py (v1.1 round B2, CONTRACTS_v11.md §8): NAZOV_UCTU,
CISLO_KLIENTA, KOD_BANKY, FAX -- the Vyhláška MS SR 482/2011 / Inštrukcia 24/2011 bank and
office reference types.

Fixtures are hand-built literal strings -- this file must NOT import corpus/. The module
under test is standalone this round (not yet wired into detect.core.detect()), so tests
call ``detect_office_refs(text, DEFAULT)`` directly.
"""
from detect.config import DEFAULT
from detect.office_refs import _detect_kod_banky, detect_office_refs

NBSP = " "


def _find(text, type_):
    return [c for c in detect_office_refs(text, DEFAULT) if c.type == type_]


def _assert_single(text, type_, surface):
    hits = [c for c in _find(text, type_) if c.surface == surface]
    assert len(hits) == 1, (text, detect_office_refs(text, DEFAULT))
    c = hits[0]
    assert c.auto is True
    assert c.checksum == "n/a"
    assert text[c.start : c.end] == surface


# --------------------------------------------------------------------------- NAZOV_UCTU
def test_nazov_uctu_colon_to_end_of_line_detected():
    _assert_single("Názov účtu: Ján Novák\nÚčet vedený od roku 2020.", "NAZOV_UCTU", "Ján Novák")


def test_nazov_uctu_majitel_uctu_detected():
    _assert_single(
        "Majiteľ účtu Jana Kováčová\nÚčet vedený od roku 2021.",
        "NAZOV_UCTU",
        "Jana Kováčová",
    )


def test_nazov_uctu_vlastnik_uctu_detected():
    _assert_single("Vlastník účtu: Firma XYZ s.r.o.", "NAZOV_UCTU", "Firma XYZ s.r.o.")


def test_nazov_uctu_stops_at_double_space_cell_boundary():
    text = "Názov účtu: Peter Malý  Číslo účtu: 123456"
    _assert_single(text, "NAZOV_UCTU", "Peter Malý")


def test_nazov_uctu_stops_at_tab():
    text = "Názov účtu: Eva Horváthová\tIBAN: SK1234567890123456789012"
    _assert_single(text, "NAZOV_UCTU", "Eva Horváthová")


# --------------------------------------------------------------------------- CISLO_KLIENTA
def test_cislo_klienta_plain_detected():
    _assert_single("Číslo klienta: 445566 je evidované.", "CISLO_KLIENTA", "445566")


def test_cislo_klienta_klientske_cislo_detected():
    _assert_single("Klientske číslo 2024-0091 pridelené.", "CISLO_KLIENTA", "2024-0091")


def test_cislo_klienta_zakaznicke_cislo_detected():
    _assert_single("Zákaznícke číslo: ZK/998877 v systéme.", "CISLO_KLIENTA", "ZK/998877")


def test_cislo_klienta_short_form_detected():
    _assert_single("Podľa č. klienta 778899 evidovaného v banke.", "CISLO_KLIENTA", "778899")


# --------------------------------------------------------------------------- KOD_BANKY
def test_kod_banky_label_detected():
    _assert_single("Kód banky: 1100 podľa výpisu.", "KOD_BANKY", "1100")


def test_kod_banky_label_nbsp_detected():
    surface = "0900"
    text = f"Kód banky{NBSP}{surface} uvedený v zmluve."
    _assert_single(text, "KOD_BANKY", surface)


def test_kod_banky_legacy_account_tail_detected():
    _assert_single(
        "Účet 123456-1234567890/1100 je aktívny.", "KOD_BANKY", "1100"
    )


def test_kod_banky_bare_year_not_detected():
    assert _find("Zmluva bola uzavretá v roku 2025.", "KOD_BANKY") == []


def test_kod_banky_bare_four_digits_no_anchor_not_detected():
    assert _find("Suma predstavuje 2025 EUR.", "KOD_BANKY") == []


def test_kod_banky_allowlist_filters_unknown_code():
    text = "Kód banky: 9999 podľa výpisu."
    all_hits = _detect_kod_banky(text)
    assert len(all_hits) == 1
    filtered = _detect_kod_banky(text, bank_codes=frozenset({"1100", "0900"}))
    assert filtered == []


def test_kod_banky_allowlist_accepts_known_code():
    text = "Kód banky: 1100 podľa výpisu."
    filtered = _detect_kod_banky(text, bank_codes=frozenset({"1100", "0900"}))
    assert len(filtered) == 1
    assert filtered[0].surface == "1100"


# --------------------------------------------------------------------------- FAX
def test_fax_international_plus_detected():
    _assert_single("Fax: +421 55 123 4567 je k dispozícii.", "FAX", "+421 55 123 4567")


def test_fax_domestic_leading_zero_detected():
    _assert_single("Fax 0554567890 uvedený v hlavičke.", "FAX", "0554567890")


def test_fax_faxove_cislo_detected():
    _assert_single("Faxové číslo: 00421551234567 na dokumente.", "FAX", "00421551234567")


def test_fax_c_form_detected():
    _assert_single("Fax č. 055-123-4567 v kontaktoch.", "FAX", "055-123-4567")


def test_fax_no_anchor_not_detected():
    assert _find("Telefón +421 55 123 4567 dostupný.", "FAX") == []


# ------------------------------------------------------------------------- COMBINED
def test_all_four_types_detected_together():
    text = (
        "Názov účtu: Jozef Malík\nČíslo klienta: 334455\n"
        "Kód banky: 0200\nFax: 0554443322 kontakt."
    )
    types = {c.type for c in detect_office_refs(text, DEFAULT)}
    assert types == {"NAZOV_UCTU", "CISLO_KLIENTA", "KOD_BANKY", "FAX"}
