"""TDD spec for detect/addresses.py (CONTRACTS_v11.md §8, B1 round): the six Slovak
address-block types — PSC, ADRESA, SUPISNE_CISLO, CISLO_BYTU, VCHOD, POSCHODIE.

Fixtures are hand-built literal strings, never derived from corpus/pii/* (the dev-only
fixture generator) or from data/. tests/ must NOT import corpus/.

Governing rule (context.md §6): recall over precision. Every candidate from this module
is auto=True, checksum="n/a" — there is no review-bucket path for these types.

NBSP is written as the "\\u00a0" escape, never as a literal byte, so the fixture encoding
survives any editor round-trip. This file is saved UTF-8 with real Slovak diacritics.
"""
from __future__ import annotations

from detect.addresses import detect_addresses
from detect.config import DEFAULT

NBSP = " "

ADDRESS_TYPES = (
    "PSC",
    "ADRESA",
    "SUPISNE_CISLO",
    "CISLO_BYTU",
    "VCHOD",
    "POSCHODIE",
)


def _detect(text: str):
    return detect_addresses(text, DEFAULT)


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


def _assert_hit(text: str, type_: str, surface: str):
    cands = _detect(text)
    hits = _find(cands, type_, surface)
    assert len(hits) == 1, (text, cands)
    c = hits[0]
    assert c.auto is True
    assert c.checksum == "n/a"
    assert text[c.start : c.end] == surface
    return c


# --------------------------------------------------------------------------- PSC
def test_psc_spaced_with_anchor():
    _assert_hit("Adresa: PSČ 040 01, doručovacia adresa klienta.", "PSC", "040 01")


def test_psc_spaced_with_anchor_nbsp():
    surface = f"040{NBSP}01"
    _assert_hit(f"PSČ {surface} je platné.", "PSC", surface)


def test_psc_spaced_followed_by_obec():
    _assert_hit("Adresa: Hlavná 1, 040 01 Košice.", "PSC", "040 01")


def test_psc_spaced_followed_by_obec_nbsp():
    surface = f"040{NBSP}01"
    _assert_hit(f"Adresa: Hlavná 1, {surface} Košice.", "PSC", surface)


def test_psc_contiguous_with_anchor():
    _assert_hit("PSC: 04001 uvedené v zmluve.", "PSC", "04001")


def test_psc_contiguous_preceded_by_comma_and_obec():
    _assert_hit("Adresa: Hlavná 1, 04001 Košice.", "PSC", "04001")


def test_psc_contiguous_no_context_not_matched():
    text = "Dokument má celkovo 04001 strán v archíve."
    cands = _detect(text)
    assert not any(c.type == "PSC" for c in cands), cands


# --------------------------------------------------------------------------- ADRESA
def test_adresa_keyword_ulica():
    _assert_hit("Sídlo spoločnosti je na ul. Hlavná 12.", "ADRESA", "ul. Hlavná 12")


def test_adresa_keyword_namestie():
    _assert_hit(
        "Kancelária sa nachádza na nám. Slobody 3.", "ADRESA", "nám. Slobody 3"
    )


def test_adresa_keyword_trieda():
    _assert_hit(
        "Prevádzka na trieda Slobody 45.", "ADRESA", "trieda Slobody 45"
    )


def test_adresa_keyword_cesta():
    _assert_hit("Objekt na cesta Košická 8.", "ADRESA", "cesta Košická 8")


def test_adresa_keyword_sidlisko():
    _assert_hit(
        "Byt sa nachádza na sídlisko Sever 22.", "ADRESA", "sídlisko Sever 22"
    )


def test_adresa_keyword_with_orient_number():
    _assert_hit(
        "Bydlisko na ul. Štúrova 12/A je zapísané.", "ADRESA", "ul. Štúrova 12/A"
    )


def test_adresa_keywordless_bytom_anchor():
    _assert_hit(
        "Ján Novák, trvale bytom Hlavná 12/A, je žalovaný.",
        "ADRESA",
        "Hlavná 12/A",
    )


def test_adresa_keywordless_sidlo_anchor():
    _assert_hit(
        "Spoločnosť so sídlom Slovenská 7 v Prešove.", "ADRESA", "Slovenská 7"
    )


def test_adresa_keywordless_adresa_anchor():
    _assert_hit("Na adrese Nová 3 sa nachádza sklad.", "ADRESA", "Nová 3")


def test_adresa_swallow_extension_full_span():
    text = "Ján Novák, trvale bytom Hlavná 12/A, 040 01 Košice, narodený..."
    surface = "Hlavná 12/A, 040 01 Košice"
    c = _assert_hit(text, "ADRESA", surface)
    assert text[c.start : c.end] == surface


def test_adresa_swallow_extension_nbsp_psc():
    psc = f"040{NBSP}01"
    text = f"trvale bytom Hlavná 12/A,{NBSP}{psc} Košice."
    surface = f"Hlavná 12/A,{NBSP}{psc} Košice"
    _assert_hit(text, "ADRESA", surface)


def test_adresa_diacritics_street_and_obec():
    text = "trvale bytom Ľubochňa 5, 034 91 Žilina."
    surface = "Ľubochňa 5, 034 91 Žilina"
    _assert_hit(text, "ADRESA", surface)


def test_adresa_no_anchor_no_keyword_not_matched():
    for text in ("Článok 5 tejto zmluvy.", "Zákon 40/1964 Zb.", "strana 12 dokumentu"):
        cands = _detect(text)
        assert not any(c.type == "ADRESA" for c in cands), (text, cands)


# --------------------------------------------------------------------------- SUPISNE_CISLO
def test_supisne_cislo_full_phrase():
    _assert_hit(
        "Nehnuteľnosť so súpisné číslo 123 je vo vlastníctve.",
        "SUPISNE_CISLO",
        "súpisné číslo 123",
    )


def test_supisne_cislo_abbrev_sup_c():
    _assert_hit("Dom evidovaný súp. č. 123.", "SUPISNE_CISLO", "súp. č. 123")


def test_supisne_cislo_abbrev_s_c():
    _assert_hit("Stavba s. č. 45 v obci.", "SUPISNE_CISLO", "s. č. 45")


def test_supisne_cislo_orientacne_full():
    _assert_hit(
        "Vchod má orientačné číslo 4.", "SUPISNE_CISLO", "orientačné číslo 4"
    )


def test_supisne_cislo_orientacne_abbrev():
    _assert_hit("Budova or. č. 4 na ulici.", "SUPISNE_CISLO", "or. č. 4")


def test_supisne_cislo_combined():
    _assert_hit(
        "Dom má súpisné/orientačné číslo 123/4.",
        "SUPISNE_CISLO",
        "súpisné/orientačné číslo 123/4",
    )


# --------------------------------------------------------------------------- CISLO_BYTU
def test_cislo_bytu_byt_c():
    _assert_hit("Predmetom je byt č. 12 v dome.", "CISLO_BYTU", "byt č. 12")


def test_cislo_bytu_cislo_bytu():
    _assert_hit(
        "Vlastník má číslo bytu 12 zapísané.", "CISLO_BYTU", "číslo bytu 12"
    )


def test_cislo_bytu_b_c():
    _assert_hit("Byt označený b. č. 12.", "CISLO_BYTU", "b. č. 12")


def test_cislo_bytu_byt_cislo():
    _assert_hit("Ide o byt číslo 12 na treťom podlaží.", "CISLO_BYTU", "byt číslo 12")


# --------------------------------------------------------------------------- VCHOD
def test_vchod_number():
    _assert_hit("Vstup je cez vchod 3 z ulice.", "VCHOD", "vchod 3")


def test_vchod_c_number():
    _assert_hit("Byt sa nachádza vo vchod č. 3.", "VCHOD", "vchod č. 3")


def test_vchod_letter():
    _assert_hit("Vchod A je bezbariérový.", "VCHOD", "Vchod A")


def test_vchod_colon_letter():
    _assert_hit("Označenie: vchod: B na fasáde.", "VCHOD", "vchod: B")


# --------------------------------------------------------------------------- POSCHODIE
def test_poschodie_prefix_number():
    _assert_hit("Byt sa nachádza na 3. poschodie budovy.", "POSCHODIE", "3. poschodie")


def test_poschodie_keyword_number():
    _assert_hit("Kancelária je na poschodie 3.", "POSCHODIE", "poschodie 3")


def test_poschodie_keyword_colon_number():
    _assert_hit("Umiestnenie: poschodie: 3 v pláne.", "POSCHODIE", "poschodie: 3")


def test_poschodie_prizemie():
    _assert_hit("Recepcia je na prízemie budovy.", "POSCHODIE", "prízemie")


def test_poschodie_na_locative():
    _assert_hit(
        "Byt sa nachádza na 2. poschodí bytového domu.",
        "POSCHODIE",
        "na 2. poschodí",
    )


# --------------------------------------------------------------------------- ALL AUTO
def test_all_candidates_auto_true_and_n_a_checksum():
    text = (
        "trvale bytom Hlavná 12/A, 040 01 Košice, byt č. 12, vchod A, 3. poschodie, "
        "súp. č. 123."
    )
    cands = _detect(text)
    addr_cands = [c for c in cands if c.type in ADDRESS_TYPES]
    assert addr_cands, cands
    assert all(c.auto is True and c.checksum == "n/a" for c in addr_cands)
