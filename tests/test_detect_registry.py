"""TDD spec for detect/ round 2c: LV, PARCELA, ORSR_VLOZKA, SPISOVA_ZNACKA
(context.md §4.1) — the four Slovak registry-reference types.

Fixtures are hand-built literal strings, never derived from data/ or from the corpus
generator (corpus/pii/* is a dev-only fixture generator and must not be imported here
or by detect/ itself).

All four types are shape-only: no checksum exists for any of them, so every match is
Candidate(auto=True). There is no review-bucket path for these types.

NBSP is written as the "\\u00a0" escape below, never as a literal byte, so the fixture
encoding survives any editor round-trip. Slovak quotes („ U+201E, “ U+201C) and
diacritics are hand-typed literal characters; this file is saved UTF-8.
"""
from detect import detect

NBSP = "\u00a0"

REGISTRY_TYPES = ("LV", "PARCELA", "ORSR_VLOZKA", "SPISOVA_ZNACKA")


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


def _assert_single_hit(text, type_, surface):
    hits = _find(detect(text), type_, surface)
    assert len(hits) == 1, (text, detect(text))
    c = hits[0]
    assert c.auto is True
    assert text[c.start : c.end] == surface
    assert c.start == text.index(surface)


# --------------------------------------------------------------------------- LV
def test_lv_plain_space_detected():
    _assert_single_hit(
        "Nehnuteľnosť je zapísaná na LV č. 1234 v katastri nehnuteľností.",
        "LV",
        "LV č. 1234",
    )


def test_lv_nbsp_detected():
    surface = f"LV č.{NBSP}1234"
    _assert_single_hit(
        f"Nehnuteľnosť je zapísaná na {surface} v katastri nehnuteľností.",
        "LV",
        surface,
    )


def test_lv_single_digit_detected():
    _assert_single_hit("Pozemok evidovaný na LV č. 7 v obci Sady.", "LV", "LV č. 7")


# --------------------------------------------------------------------------- PARCELA
def test_parcela_plain_space_detected():
    _assert_single_hit(
        "Ide o pozemok parc. č. 123 v katastrálnom území mesta.",
        "PARCELA",
        "parc. č. 123",
    )


def test_parcela_plain_nbsp_detected():
    surface = f"parc. č.{NBSP}123"
    _assert_single_hit(
        f"Ide o pozemok {surface} v katastrálnom území mesta.", "PARCELA", surface
    )


def test_parcela_sub_space_detected():
    _assert_single_hit(
        "Predmetom prevodu je parc. č. 123/4 o výmere 500 m2.",
        "PARCELA",
        "parc. č. 123/4",
    )


def test_parcela_sub_nbsp_detected():
    surface = f"parc. č.{NBSP}123/4"
    _assert_single_hit(
        f"Predmetom prevodu je {surface} o výmere 500 m2.", "PARCELA", surface
    )


def test_parcela_kn_c_space_detected():
    _assert_single_hit(
        "Prevádza sa parcela registra „C“ KN č. 456/7 v celosti.",
        "PARCELA",
        "parcela registra „C“ KN č. 456/7",
    )


def test_parcela_kn_c_nbsp_detected():
    surface = f"parcela registra „C“ KN č.{NBSP}456/7"
    _assert_single_hit(f"Prevádza sa {surface} v celosti.", "PARCELA", surface)


def test_parcela_kn_e_space_detected():
    _assert_single_hit(
        "Prevádza sa parcela registra „E“ KN č. 89/12 v celosti.",
        "PARCELA",
        "parcela registra „E“ KN č. 89/12",
    )


def test_parcela_kn_e_nbsp_detected():
    surface = f"parcela registra „E“ KN č.{NBSP}89/12"
    _assert_single_hit(f"Prevádza sa {surface} v celosti.", "PARCELA", surface)


# --------------------------------------------------------------------------- ORSR_VLOZKA
def test_orsr_sro_space_detected():
    _assert_single_hit(
        "Spoločnosť zapísaná v obchodnom registri, Oddiel: Sro, Vložka č. 1234/B v plnom rozsahu.",
        "ORSR_VLOZKA",
        "Oddiel: Sro, Vložka č. 1234/B",
    )


def test_orsr_sro_nbsp_detected():
    surface = f"Oddiel: Sro, Vložka č.{NBSP}1234/B"
    _assert_single_hit(
        f"Spoločnosť zapísaná v obchodnom registri, {surface} v plnom rozsahu.",
        "ORSR_VLOZKA",
        surface,
    )


def test_orsr_ps_three_digit_space_detected():
    _assert_single_hit(
        "Družstvo vedené v registri, Oddiel: Pš, Vložka č. 321/V podľa výpisu.",
        "ORSR_VLOZKA",
        "Oddiel: Pš, Vložka č. 321/V",
    )


def test_orsr_ps_nbsp_detected():
    surface = f"Oddiel: Pš, Vložka č.{NBSP}321/V"
    _assert_single_hit(
        f"Družstvo vedené v registri, {surface} podľa výpisu.", "ORSR_VLOZKA", surface
    )


def test_orsr_sa_five_digit_vlozka_detected():
    _assert_single_hit(
        "Akciová spoločnosť zapísaná ako Oddiel: Sa, Vložka č. 12345/Z ku dňu vydania.",
        "ORSR_VLOZKA",
        "Oddiel: Sa, Vložka č. 12345/Z",
    )


def test_orsr_dr_suffix_t_detected():
    _assert_single_hit(
        "V registri evidované pod Oddiel: Dr, Vložka č. 987/T naďalej.",
        "ORSR_VLOZKA",
        "Oddiel: Dr, Vložka č. 987/T",
    )


def test_orsr_suffix_n_detected():
    _assert_single_hit(
        "Zápis znie Oddiel: Sro, Vložka č. 4567/N podľa registra.",
        "ORSR_VLOZKA",
        "Oddiel: Sro, Vložka č. 4567/N",
    )


# --------------------------------------------------------------------------- SPISOVA_ZNACKA
def test_sz_cadastral_v_detected():
    _assert_single_hit(
        "Vklad povolený pod V-1234/2025 správou katastra.",
        "SPISOVA_ZNACKA",
        "V-1234/2025",
    )


def test_sz_cadastral_x_detected():
    _assert_single_hit(
        "Konanie vedené pod X-99/2024 na okresnom úrade.",
        "SPISOVA_ZNACKA",
        "X-99/2024",
    )


def test_sz_cadastral_r_detected():
    _assert_single_hit(
        "Oprava zapísaná pod R-5/2023 v evidencii.", "SPISOVA_ZNACKA", "R-5/2023"
    )


def test_sz_court_cb_full_span_detected():
    # C-eats-Cb regression: the whole 12Cb/345/2025 span must survive, never 12C+b.
    text = "Konanie vedené pod sp. zn. 12Cb/345/2025 na okresnom súde."
    _assert_single_hit(text, "SPISOVA_ZNACKA", "12Cb/345/2025")
    sz = [c for c in detect(text) if c.type == "SPISOVA_ZNACKA"]
    assert [c.surface for c in sz] == ["12Cb/345/2025"]


def test_sz_court_ro_detected():
    _assert_single_hit(
        "Rozkazné konanie 34Ro/1/2024 bolo zastavené.", "SPISOVA_ZNACKA", "34Ro/1/2024"
    )


def test_sz_court_er_detected():
    _assert_single_hit(
        "Exekučné konanie 21Er/890/2023 naďalej prebieha.",
        "SPISOVA_ZNACKA",
        "21Er/890/2023",
    )


def test_sz_court_c_detected():
    _assert_single_hit(
        "Občianskoprávny spor 12C/345/2025 bol odročený.",
        "SPISOVA_ZNACKA",
        "12C/345/2025",
    )


def test_sz_court_t_detected():
    _assert_single_hit(
        "Trestná vec 9T/22/2024 je v štádiu dokazovania.", "SPISOVA_ZNACKA", "9T/22/2024"
    )


def test_sz_court_d_detected():
    _assert_single_hit(
        "Dedičské konanie 15D/8/2025 bolo ukončené.", "SPISOVA_ZNACKA", "15D/8/2025"
    )


def test_sz_court_single_digit_prefix_detected():
    _assert_single_hit(
        "Vec vedená pod 5C/12/2024 na súde prvej inštancie.",
        "SPISOVA_ZNACKA",
        "5C/12/2024",
    )


# ------------------------------------------------------------------------- NEGATIVES
def test_decoys_yield_zero_candidates():
    decoys = [
        "Faktúra č. 2024017",
        "Strana 3 z 12",
        "Obj. č. 123/2024",
        "čl. 12 ods. 3",
        "bod 4.2",
        "14:35 hod.",
    ]
    for text in decoys:
        cands = detect(text)
        assert not any(c.type in REGISTRY_TYPES for c in cands), (text, cands)
        assert cands == [], (text, cands)


def test_bare_slash_number_yields_no_registry_candidates():
    for text in (
        "Podanie evidované pod 123/2024 v spise.",
        "Zapísané pod 1234/2025 bez ďalšieho označenia.",
    ):
        cands = detect(text)
        assert not any(c.type in REGISTRY_TYPES for c in cands), (text, cands)


def test_lv_five_digit_run_not_partially_claimed():
    text = "Nehnuteľnosť je zapísaná na LV č. 12345 v katastri."
    cands = detect(text)
    assert not any(c.type == "LV" for c in cands), cands
    # no candidate of any type may end mid-run inside the "12345" digit run
    run_start = text.index("12345")
    run_end = run_start + 5
    assert not any(run_start < c.end < run_end for c in cands), cands


def test_all_registry_candidates_auto_true():
    text = (
        "Na LV č. 1234 je zapísaná parc. č. 567/8 a parcela registra „C“ KN č. 90/1. "
        "Zápis: Oddiel: Sro, Vložka č. 4321/B. Konania V-22/2025 a 3Cb/45/2024 trvajú."
    )
    regs = [c for c in detect(text) if c.type in REGISTRY_TYPES]
    assert len(regs) == 6, regs
    assert all(c.auto is True for c in regs)


# ------------------------------------------------------------------- ENCODING PARITY
def test_pattern_encoding_parity():
    from detect.registry_refs import (
        _LV_RE,
        _ORSR_VLOZKA_RE,
        _PARCELA_RE,
        _SPISOVA_ZNACKA_RE,
    )

    for pat in (_LV_RE, _PARCELA_RE, _ORSR_VLOZKA_RE):
        assert NBSP in pat.pattern, pat.pattern
        assert "č" in pat.pattern, pat.pattern
    assert "„" in _PARCELA_RE.pattern
    assert "“" in _PARCELA_RE.pattern
    assert "ž" in _ORSR_VLOZKA_RE.pattern
    assert "š" in _ORSR_VLOZKA_RE.pattern
    # SPISOVA_ZNACKA has no SP position and no diacritics — pure ASCII by design
    assert _SPISOVA_ZNACKA_RE.pattern.isascii()
