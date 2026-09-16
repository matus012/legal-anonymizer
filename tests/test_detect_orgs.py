"""TDD spec for detect/orgs.py (v1.1 round B3, CONTRACTS_v11.md §8/§12): ORG and
NAZOV_BANKY.

ORG is the LAST Class A exclusion in eval/leak_gate.py — a type excluded from the gate is a
type the gate never tests, so every claim this module makes has to be nailed down here
first. NAZOV_BANKY is the genuine gap found by the Vyhláška MS SR 482/2011 mapping
(CONTRACTS_v11.md §12, clause (f): the NAME of the bank or foreign-bank branch).

Fixtures are hand-built literal strings — this file must NOT import corpus/ (contract §11).
The module is standalone this round (not yet wired into detect.core.detect()), so the tests
call ``detect_orgs(text, DEFAULT)`` directly.
"""
from detect.config import DEFAULT
from detect.core import KNOWN_TYPES
from detect.orgs import detect_orgs

NBSP = " "


def _find(text, type_):
    return [c for c in detect_orgs(text, DEFAULT) if c.type == type_]


def _assert_exact(text, type_, surface):
    """Exactly one candidate of ``type_`` whose span is EXACTLY ``surface``."""
    hits = [c for c in _find(text, type_) if c.surface == surface]
    assert len(hits) == 1, (text, detect_orgs(text, DEFAULT))
    c = hits[0]
    assert c.auto is True
    assert c.checksum == "n/a"
    assert text[c.start : c.end] == surface
    assert c.type in KNOWN_TYPES


def _assert_covers(text, type_, needle):
    """At least one candidate of ``type_`` whose span CONTAINS ``needle`` — used where the
    detector legitimately claims more than the needle (a trailing legal-form suffix, the
    ``pobočka zahraničnej banky`` tail)."""
    start = text.index(needle)
    end = start + len(needle)
    hits = [c for c in _find(text, type_) if c.start <= start and end <= c.end]
    assert hits, (needle, detect_orgs(text, DEFAULT))
    for c in hits:
        assert c.auto is True
        assert c.checksum == "n/a"
        assert text[c.start : c.end] == c.surface
        assert c.type in KNOWN_TYPES


def _assert_none(text, type_):
    assert _find(text, type_) == [], (text, detect_orgs(text, DEFAULT))


# ================================================================== ORG — legal-form suffix
# The suffix is the reliable signal and is PART OF THE SPAN (it is part of the company's
# name as written). One test per suffix in the contract list.
def test_org_sro_detected():
    _assert_exact("Zmluvu uzavrela Alfa Beta s.r.o. so sídlom v Košiciach.", "ORG",
                  "Alfa Beta s.r.o.")


def test_org_spol_s_ro_detected():
    _assert_exact("Dodávateľom je Tatra Servis spol. s r.o. podľa zmluvy.", "ORG",
                  "Tatra Servis spol. s r.o.")


def test_org_as_detected():
    _assert_exact("Objednávku potvrdila Stavby Východ a.s. dňa 3. marca 2024.", "ORG",
                  "Stavby Východ a.s.")


def test_org_run_swallows_a_preceding_capitalised_word():
    """PINNED over-capture. The run is "up to four capitalised tokens before the suffix", so
    an unrelated capitalised word directly in front of the company name is swallowed:
    "Objednávateľ Stavby Východ a.s." is claimed whole. Per ADDENDUM 1 R2 company data is
    public and ambiguity resolves toward REDACT, so this is the intended direction — it
    over-redacts one word of running text and can never leak the name. The test exists so the
    behaviour is a recorded decision rather than a surprise in a review list."""
    _assert_exact("Objednávateľ Stavby Východ a.s. potvrdil objednávku.", "ORG",
                  "Objednávateľ Stavby Východ a.s.")


def test_org_akciova_spolocnost_detected():
    _assert_exact("Veriteľom je Slovenské Elektrárne akciová spoločnosť podľa výpisu.",
                  "ORG", "Slovenské Elektrárne akciová spoločnosť")


def test_org_ks_detected():
    _assert_exact("Spoločníkom je Gama Invest k.s. so sídlom v Nitre.", "ORG",
                  "Gama Invest k.s.")


def test_org_vos_detected():
    _assert_exact("Účastníkom je Delta Trade v.o.s. zapísaná v registri.", "ORG",
                  "Delta Trade v.o.s.")


def test_org_no_detected():
    _assert_exact("Prijímateľom je Pomoc Deťom n.o. podľa darovacej zmluvy.", "ORG",
                  "Pomoc Deťom n.o.")


def test_org_oz_detected():
    _assert_exact("Členom je Zelená Krajina o.z. registrované na MV SR.", "ORG",
                  "Zelená Krajina o.z.")


def test_org_druzstvo_detected():
    _assert_exact("Predávajúcim je Poľnohospodárske družstvo podľa zmluvy.", "ORG",
                  "Poľnohospodárske družstvo")


def test_org_statny_podnik_detected():
    _assert_exact("Správcom je Lesy SR štátny podnik podľa osobitného predpisu.", "ORG",
                  "Lesy SR štátny podnik")


def test_org_sp_detected():
    _assert_exact("Správcom je Vodohospodárska Výstavba š.p. podľa zákona.", "ORG",
                  "Vodohospodárska Výstavba š.p.")


def test_org_jsa_detected():
    _assert_exact("Investorom je Omega Capital j.s.a. so sídlom v Bratislave.", "ORG",
                  "Omega Capital j.s.a.")


# ---------------------------------------------------------------------- ORG spacing variants
def test_org_sro_spaced_variant_detected():
    _assert_exact("Zhotoviteľom je Alfa Beta s. r. o. podľa zmluvy.", "ORG",
                  "Alfa Beta s. r. o.")


def test_org_sro_no_final_dot_detected():
    _assert_exact("Zhotoviteľom je Alfa Beta s.r.o podľa zmluvy.", "ORG",
                  "Alfa Beta s.r.o")


def test_org_comma_before_suffix_detected():
    _assert_exact("Zhotoviteľom je Alfa Beta, s. r. o. podľa zmluvy.", "ORG",
                  "Alfa Beta, s. r. o.")


def test_org_lowercase_connector_inside_the_name_detected():
    """"Kováč a Partneri s.r.o." — a run of strictly capitalised tokens stops at the "a" and
    would claim only "Partneri s.r.o.", leaving the leading words of the company name
    un-redacted."""
    _assert_exact("Zhotoviteľom je Kováč a Partneri s.r.o. podľa zmluvy.", "ORG",
                  "Kováč a Partneri s.r.o.")


def test_org_ampersand_connector_inside_the_name_detected():
    _assert_exact("Zhotoviteľom je Mladý & Syn s.r.o. podľa zmluvy.", "ORG",
                  "Mladý & Syn s.r.o.")


def test_org_nbsp_between_name_and_suffix_detected():
    surface = f"Alfa Beta{NBSP}s.r.o."
    _assert_exact(f"Zhotoviteľom je {surface} podľa zmluvy.", "ORG", surface)


def test_org_nbsp_inside_suffix_detected():
    surface = f"Alfa Beta s.{NBSP}r.{NBSP}o."
    _assert_exact(f"Zhotoviteľom je {surface} podľa zmluvy.", "ORG", surface)


def test_org_line_break_inside_multiword_suffix_detected():
    """The detect/office_refs.py ``_AWS`` lesson: a PDF wraps mid-anchor and the entity
    LEAKS. Any multi-word suffix must survive a line break between its words."""
    surface = "Tatra Servis spol. s\nr.o."
    _assert_exact(f"Dodávateľom je {surface} podľa zmluvy.", "ORG", surface)


def test_org_line_break_inside_akciova_spolocnost_detected():
    surface = "Slovenské Elektrárne akciová\nspoločnosť"
    _assert_exact(f"Veriteľom je {surface} podľa výpisu.", "ORG", surface)


def test_org_line_break_between_name_and_suffix_detected():
    surface = "Alfa Beta\ns.r.o."
    _assert_exact(f"Zhotoviteľom je {surface} podľa zmluvy.", "ORG", surface)


# ------------------------------------------------------------------------ ORG field label
def test_org_field_label_to_end_of_line_detected():
    _assert_covers("Obchodné meno: Alfa Beta s.r.o.\nIČO: 12345678", "ORG",
                   "Alfa Beta s.r.o.")


def test_org_field_label_value_without_suffix_detected():
    """The label alone carries the type — a value with no legal-form suffix must still be
    claimed, or ``Obchodné meno:`` would only ever confirm what the suffix rule already
    found."""
    _assert_exact("Obchodné meno: Kováč a Partneri\nIČO: 12345678", "ORG",
                  "Kováč a Partneri")


def test_org_field_label_stops_at_double_space_cell_boundary():
    _assert_exact("Obchodné meno: Kováč a Partneri  IČO: 12345678", "ORG",
                  "Kováč a Partneri")


def test_org_field_label_stops_at_tab():
    _assert_exact("Obchodné meno: Kováč a Partneri\tIČO: 12345678", "ORG",
                  "Kováč a Partneri")


def test_org_field_label_nbsp_inside_anchor_detected():
    _assert_exact(f"Obchodné{NBSP}meno: Kováč a Partneri\nIČO: 12345678", "ORG",
                  "Kováč a Partneri")


def test_org_field_label_line_break_inside_anchor_detected():
    _assert_exact("Obchodné\nmeno: Kováč a Partneri\nIČO: 12345678", "ORG",
                  "Kováč a Partneri")


# --------------------------------------------------------------------- ORG anchored office
def test_org_advokatska_kancelaria_detected():
    """``corpus/templates/_common.py`` seeds ``Advokátska kancelária <surname>`` as an ORG
    ground-truth surface — a company name with NO legal-form suffix at all."""
    _assert_exact("Zastúpený Advokátska kancelária Kováč so sídlom v Košiciach.", "ORG",
                  "Advokátska kancelária Kováč")


# ---------------------------------------------------------------------- ORG negative cases
def test_org_sentence_start_capital_is_not_org():
    _assert_none("Zmluva bola uzavretá dňa 1. januára 2024 v Košiciach.", "ORG")


def test_org_court_is_not_org():
    """A court is not a company, and clause (j) of the vyhláška explicitly exempts judges
    and court officials, so its name is not PII under the decree."""
    _assert_none("Vo veci rozhodol Okresný súd Košice I dňa 3. marca 2024.", "ORG")


def test_org_krajsky_sud_is_not_org():
    _assert_none("Odvolanie prejednal Krajský súd v Košiciach.", "ORG")


def test_org_bare_capitalised_word_is_not_org():
    _assert_none("Nehnuteľnosť sa nachádza v obci Bratislava podľa listu vlastníctva.",
                 "ORG")


def test_org_bare_suffix_without_name_is_not_org():
    _assert_none("Ide o s.r.o. podľa Obchodného zákonníka.", "ORG")


# ============================================================================ NAZOV_BANKY
def test_bank_slovenska_sporitelna_detected():
    _assert_covers("Účet je vedený v Slovenská sporiteľňa podľa výpisu.", "NAZOV_BANKY",
                   "Slovenská sporiteľňa")


def test_bank_vseobecna_uverova_banka_detected():
    _assert_covers("Účet je vedený vo Všeobecná úverová banka podľa výpisu.",
                   "NAZOV_BANKY", "Všeobecná úverová banka")


def test_bank_vub_abbreviation_detected():
    _assert_covers("Prevod zadaný cez VÚB dňa 3. marca 2024.", "NAZOV_BANKY", "VÚB")


def test_bank_tatra_banka_detected():
    _assert_covers("Účet vedený v Tatra banka podľa výpisu.", "NAZOV_BANKY", "Tatra banka")


def test_bank_csob_detected():
    _assert_covers("Platba bola poukázaná cez ČSOB dňa 3. marca 2024.", "NAZOV_BANKY",
                   "ČSOB")


def test_bank_postova_banka_detected():
    _assert_covers("Účet vedený v Poštová banka podľa výpisu.", "NAZOV_BANKY",
                   "Poštová banka")


def test_bank_prima_banka_detected():
    _assert_covers("Účet vedený v Prima banka podľa výpisu.", "NAZOV_BANKY", "Prima banka")


def test_bank_365_detected():
    _assert_covers("Účet vedený v 365.bank podľa výpisu.", "NAZOV_BANKY", "365.bank")


def test_bank_mbank_detected():
    _assert_covers("Účet vedený v mBank podľa výpisu.", "NAZOV_BANKY", "mBank")


def test_bank_unicredit_detected():
    _assert_covers("Účet vedený v UniCredit Bank podľa výpisu.", "NAZOV_BANKY",
                   "UniCredit Bank")


def test_bank_raiffeisen_detected():
    _assert_covers("Úver poskytla Raiffeisen dňa 3. marca 2024.", "NAZOV_BANKY",
                   "Raiffeisen")


def test_bank_otp_detected():
    _assert_covers("Účet vedený v OTP Banka podľa výpisu.", "NAZOV_BANKY", "OTP Banka")


def test_bank_fio_detected():
    _assert_covers("Účet vedený vo Fio banka podľa výpisu.", "NAZOV_BANKY", "Fio banka")


def test_bank_jt_detected():
    _assert_covers("Vklad prijala J&T Banka dňa 3. marca 2024.", "NAZOV_BANKY",
                   "J&T Banka")


def test_bank_oberbank_detected():
    _assert_covers("Účet vedený v Oberbank podľa výpisu.", "NAZOV_BANKY", "Oberbank")


def test_bank_citibank_detected():
    _assert_covers("Účet vedený v Citibank podľa výpisu.", "NAZOV_BANKY", "Citibank")


def test_bank_ing_detected():
    _assert_covers("Účet vedený v ING Bank podľa výpisu.", "NAZOV_BANKY", "ING Bank")


def test_bank_komercni_detected():
    _assert_covers("Účet vedený v Komerční banka podľa výpisu.", "NAZOV_BANKY",
                   "Komerční banka")


# -------------------------------------------------------- NAZOV_BANKY with legal-form suffix
def test_bank_with_as_suffix_spans_the_suffix():
    _assert_exact("Účet vedený v Tatra banka, a.s. podľa výpisu.", "NAZOV_BANKY",
                  "Tatra banka, a.s.")


def test_bank_with_spaced_as_suffix_detected():
    _assert_exact("Účet vedený v Slovenská sporiteľňa, a. s. podľa výpisu.",
                  "NAZOV_BANKY", "Slovenská sporiteľňa, a. s.")


def test_bank_name_split_over_a_line_break_detected():
    _assert_covers("Účet vedený v Poštová\nbanka podľa výpisu.", "NAZOV_BANKY",
                   "Poštová\nbanka")


def test_bank_nbsp_inside_name_detected():
    needle = f"Prima{NBSP}banka"
    _assert_covers(f"Účet vedený v {needle} podľa výpisu.", "NAZOV_BANKY", needle)


# ---------------------------------------------------------------- NAZOV_BANKY anchored forms
def test_bank_anchor_banka_after_capitalised_run_detected():
    """A bank not on the closed list is still reachable through the ``banka`` anchor."""
    _assert_covers("Úver poskytla Považská banka podľa zmluvy.", "NAZOV_BANKY",
                   "Považská banka")


def test_bank_anchor_banky_genitive_detected():
    _assert_covers("Prevod z Považská banky bol zrealizovaný.", "NAZOV_BANKY",
                   "Považská banky")


def test_bank_anchor_pobocka_zahranicnej_banky_detected():
    _assert_covers(
        "Účet vedený v Erste Group Bank AG, pobočka zahraničnej banky podľa výpisu.",
        "NAZOV_BANKY", "Erste Group Bank AG")


def test_bank_anchor_pobocka_zahranicnej_banky_line_break_detected():
    _assert_covers(
        "Účet vedený v Erste Group Bank AG, pobočka zahraničnej\nbanky podľa výpisu.",
        "NAZOV_BANKY", "Erste Group Bank AG")


def test_bank_anchor_name_after_the_anchor_word_detected():
    _assert_covers("Pobočka zahraničnej banky Erste Group vedie účet.", "NAZOV_BANKY",
                   "Erste Group")


# --------------------------------------------------------------- NAZOV_BANKY negative cases
def test_kod_banky_label_is_not_a_bank_name():
    """``Kód banky: 1100`` — the capitalised token before the anchor is the LABEL, not a
    bank name. Without the anchor stoplist this emits ``Kód`` as NAZOV_BANKY."""
    _assert_none("Kód banky: 1100 podľa výpisu.", "NAZOV_BANKY")


def test_cislo_banky_label_is_not_a_bank_name():
    _assert_none("Číslo banky: 1100 podľa výpisu.", "NAZOV_BANKY")


def test_bare_anchor_word_is_not_a_bank_name():
    _assert_none("Banka poskytla úver dňa 3. marca 2024.", "NAZOV_BANKY")


def test_court_is_not_a_bank_name():
    _assert_none("Vo veci rozhodol Okresný súd Košice I dňa 3. marca 2024.",
                 "NAZOV_BANKY")


# ==================================================================== module-level invariants
def test_only_registered_types_are_emitted():
    text = (
        "Obchodné meno: Alfa Beta s.r.o.\n"
        "Účet vedený v Tatra banka, a.s.\n"
        "Zastúpený Advokátska kancelária Kováč.\n"
    )
    cands = detect_orgs(text, DEFAULT)
    assert cands, "fixture should produce candidates"
    for c in cands:
        assert c.type in {"ORG", "NAZOV_BANKY"}
        assert c.type in KNOWN_TYPES
        assert c.checksum == "n/a"
        assert c.auto is True
        assert text[c.start : c.end] == c.surface


def test_no_duplicate_spans_within_the_module():
    text = "Obchodné meno: Alfa Beta s.r.o.\n"
    spans = [(c.type, c.start, c.end) for c in detect_orgs(text, DEFAULT)]
    assert len(spans) == len(set(spans))
