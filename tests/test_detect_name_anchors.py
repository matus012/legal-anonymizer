"""TDD spec for detect/name_anchors.py (CONTRACTS_v11.md §8, C1 round): the four
name anchors — title, role, field-label, bare-name.

Fixtures are hand-built literal strings, never derived from corpus/pii/* or from data/.
tests/ must NOT import corpus/ (CONTRACTS_v11.md §11).

Anchors 1-3 are AUTO (auto=True, pre-ticked). Anchor 4 (bare-name heuristic) is the
REVIEW bucket (auto=False, unticked) — the one v1.1 type that legitimately routes to
review (contract §7), so its false positives cost a reviewer one un-tick and nothing else.

NBSP is written as the "\\u00a0" escape, never as a literal byte, so the fixture encoding
survives an editor round-trip. This file is saved UTF-8 with real Slovak diacritics.
"""
from __future__ import annotations

import pytest

from detect.config import DEFAULT
from detect.name_anchors import detect_name_anchors

NBSP = " "


def _detect(text: str):
    return detect_name_anchors(text, DEFAULT)


def _find(cands, type_: str, surface: str):
    return [c for c in cands if c.type == type_ and c.surface == surface]


def _assert_hit(text: str, type_: str, surface: str, *, auto: bool = True):
    cands = _detect(text)
    hits = _find(cands, type_, surface)
    assert hits, (
        f"expected {type_} {surface!r} in {text!r}; got "
        f"{[(c.type, c.surface, c.auto) for c in cands]}"
    )
    c = hits[0]
    assert text[c.start : c.end] == c.surface, "surface must equal the sliced span"
    assert c.auto is auto, f"{type_} {surface!r}: auto={c.auto}, expected {auto}"
    assert c.checksum == "n/a"
    return c


# ============================================================ 1. TITLE ANCHOR (auto)

TITLES = (
    "JUDr.", "Ing.", "Ing. arch.", "Mgr.", "Bc.", "MUDr.", "PhDr.", "RNDr.",
    "Dr.", "prof.", "doc.", "PaedDr.", "ThDr.", "MVDr.", "PhD.", "CSc.",
)


@pytest.mark.parametrize("title", TITLES)
def test_every_title_anchors_the_following_name(title: str):
    text = f"Zmluvu podpísal {title} Ján Novák dňa 1.1.2025."
    c = _assert_hit(text, "MENO", "Ján Novák")
    # THE TITLE IS NOT PII — it must not be inside the matched span.
    assert title not in text[c.start : c.end]
    assert c.start >= text.index(title) + len(title)


@pytest.mark.parametrize("title", TITLES)
def test_no_title_text_appears_in_any_returned_span(title: str):
    text = f"{title} Mária Kováčová"
    for c in _detect(text):
        assert "." not in c.surface, f"title punctuation leaked into span {c.surface!r}"


def test_stacked_titles():
    c = _assert_hit("JUDr. Ing. Ján Novák", "MENO", "Ján Novák")
    assert "JUDr." not in c.surface and "Ing." not in c.surface


def test_stacked_titles_three_deep():
    _assert_hit("prof. JUDr. Ing. arch. Peter Malý, konateľ", "MENO", "Peter Malý")


def test_trailing_title():
    c = _assert_hit("Posudok vypracoval Ján Novák, PhD. dňa 1.1.2025.", "MENO", "Ján Novák")
    assert "PhD." not in c.surface


def test_trailing_title_csc():
    _assert_hit("K veci sa vyjadril Milan Horák, CSc. dňa 1.1.2025.", "MENO", "Milan Horák")


def test_title_with_three_name_tokens():
    _assert_hit("JUDr. Ján Peter Novák", "MENO", "Ján Peter Novák")


def test_title_with_nbsp_separator():
    _assert_hit(f"JUDr.{NBSP}Ján{NBSP}Novák", "MENO", f"Ján{NBSP}Novák")


def test_title_anchor_is_auto():
    for c in _detect("Mgr. Eva Krátka"):
        if c.surface == "Eva Krátka":
            assert c.auto is True


# ============================================================= 2. ROLE ANCHOR (auto)

# (nominative, one inflected form) for every role word the module claims.
ROLES = (
    ("predávajúci", "predávajúceho"),
    ("kupujúci", "kupujúcim"),
    ("žalobca", "žalobcu"),
    ("žalovaný", "žalovaného"),
    ("navrhovateľ", "navrhovateľa"),
    ("odporca", "odporcu"),
    ("splnomocniteľ", "splnomocniteľa"),
    ("splnomocnenec", "splnomocnenca"),
    ("konateľ", "konateľa"),
    ("veriteľ", "veriteľa"),
    ("dlžník", "dlžníka"),
    ("nájomca", "nájomcu"),
    ("prenajímateľ", "prenajímateľa"),
    ("dedič", "dediča"),
    ("poručiteľ", "poručiteľa"),
    ("darca", "darcu"),
    ("obdarovaný", "obdarovaného"),
    ("záložca", "záložcu"),
    ("záložný veriteľ", "záložného veriteľa"),
    ("oprávnený", "oprávneného"),
    ("povinný", "povinného"),
    ("účastník", "účastníka"),
    ("svedok", "svedka"),
    ("zástupca", "zástupcu"),
)


@pytest.mark.parametrize("nominative,inflected", ROLES)
def test_role_nominative_anchors_the_name(nominative: str, inflected: str):
    c = _assert_hit(f"{nominative} Ján Novák prehlasuje", "MENO", "Ján Novák")
    assert nominative.split()[0] not in c.surface


@pytest.mark.parametrize("nominative,inflected", ROLES)
def test_role_inflected_form_anchors_the_name(nominative: str, inflected: str):
    _assert_hit(f"v mene {inflected} Mária Kováčová koná", "MENO", "Mária Kováčová")


def test_role_is_case_insensitive():
    _assert_hit("PREDÁVAJÚCI Ján Novák", "MENO", "Ján Novák")
    _assert_hit("Kupujúci Ján Novák", "MENO", "Ján Novák")


def test_role_with_colon():
    c = _assert_hit("Predávajúci: Ján Novák", "MENO", "Ján Novák")
    assert ":" not in c.surface


def test_role_with_v_zastupeni():
    _assert_hit("kupujúci v zastúpení Ján Novák", "MENO", "Ján Novák")


def test_role_with_comma_v_zastupeni():
    _assert_hit("kupujúci, v zastúpení Ján Novák", "MENO", "Ján Novák")


def test_role_with_nbsp():
    _assert_hit(f"žalobca{NBSP}Ján{NBSP}Novák", "MENO", f"Ján{NBSP}Novák")


def test_role_anchor_is_auto():
    c = _assert_hit("dlžník Peter Malý", "MENO", "Peter Malý")
    assert c.auto is True


# ======================================================= 3. FIELD-LABEL ANCHOR (auto)

FIELD_LABELS = (
    ("Meno a priezvisko:", "Ján Novák", "MENO"),
    ("Meno:", "Ján", "MENO"),
    ("Priezvisko:", "Novák", "MENO"),
    ("Zastúpený:", "Mária Kováčová", "MENO"),
    ("Trvale bytom:", "Hlavná 12, 040 01 Košice", "ADRESA"),
    ("Bydlisko:", "Štúrova 3, Žilina", "ADRESA"),
    ("Adresa:", "Nová 8, Poprad", "ADRESA"),
    ("Sídlo:", "Slovenská 1, Prešov", "ADRESA"),
    ("Obchodné meno:", "Alfa Beta s.r.o.", "ORG"),
    ("Štátna príslušnosť:", "slovenská", "STATNA_PRISLUSNOST"),
)


@pytest.mark.parametrize("label,value,type_", FIELD_LABELS)
def test_field_label_value_type_mapping(label: str, value: str, type_: str):
    c = _assert_hit(f"{label} {value}\nĎalší riadok", type_, value)
    assert label not in c.surface, "the label must NOT be part of the span"


@pytest.mark.parametrize("label,value,type_", FIELD_LABELS)
def test_field_label_value_stops_at_end_of_string(label: str, value: str, type_: str):
    _assert_hit(f"{label} {value}", type_, value)


def test_field_value_stops_at_tab():
    _assert_hit("Meno a priezvisko:\tJán Novák\tRodné číslo", "MENO", "Ján Novák")


def test_field_value_stops_at_two_spaces():
    _assert_hit("Adresa: Hlavná 12    Kontakt", "ADRESA", "Hlavná 12")


def test_field_value_with_nbsp_after_label():
    _assert_hit(f"Meno:{NBSP}Ján", "MENO", "Ján")


def test_field_label_longest_wins_no_duplicate_priezvisko_match():
    cands = _detect("Meno a priezvisko: Ján Novák")
    menos = [c for c in cands if c.type == "MENO"]
    assert len(menos) == 1, [(c.type, c.surface) for c in menos]


def test_field_labels_are_auto():
    for label, value, type_ in FIELD_LABELS:
        c = _assert_hit(f"{label} {value}", type_, value)
        assert c.auto is True


# ================================================== 4. BARE-NAME HEURISTIC (review)

def test_bare_name_fires_mid_sentence_and_is_review():
    c = _assert_hit(
        "Dnes sa dostavil Jozef Sedlák a predložil doklad.",
        "MENO",
        "Jozef Sedlák",
        auto=False,
    )
    assert c.auto is False


def test_bare_name_three_tokens():
    _assert_hit(
        "Prítomný bol Jozef Peter Sedlák podľa zoznamu.",
        "MENO",
        "Jozef Peter Sedlák",
        auto=False,
    )


def test_bare_name_does_not_fire_at_start_of_text():
    assert not _find(_detect("Jozef Sedlák prišiel."), "MENO", "Jozef Sedlák")


def test_bare_name_does_not_fire_after_full_stop():
    assert not _find(
        _detect("Bolo to tak. Jozef Sedlák prišiel."), "MENO", "Jozef Sedlák"
    )


def test_bare_name_does_not_fire_after_question_or_exclamation():
    assert not _find(_detect("Naozaj? Jozef Sedlák prišiel."), "MENO", "Jozef Sedlák")
    assert not _find(_detect("Pozor! Jozef Sedlák prišiel."), "MENO", "Jozef Sedlák")


def test_bare_name_does_not_fire_after_newline():
    assert not _find(_detect("riadok\nJozef Sedlák prišiel."), "MENO", "Jozef Sedlák")


STOPLIST_PHRASES = (
    "Kúpna Zmluva",
    "Zmluvné Strany",
    "Predmet Zmluvy",
    "List Vlastníctva",
    "Okresný Súd",
    "Slovenská Republika",
    "Obchodný Register",
)


@pytest.mark.parametrize("phrase", STOPLIST_PHRASES)
def test_bare_name_does_not_fire_on_stoplist_phrase(phrase: str):
    text = f"Toto je {phrase} podľa zákona."
    assert not _find(_detect(text), "MENO", phrase), phrase


@pytest.mark.parametrize("month", ("Január", "Februára", "Decembra"))
def test_bare_name_does_not_fire_on_month_names(month: str):
    text = f"Podpísané dňa {month} Roku 2025."
    hits = [c for c in _detect(text) if month in c.surface]
    assert not hits, [(c.type, c.surface) for c in hits]


@pytest.mark.parametrize("day", ("Pondelok", "Streda", "Nedeľa"))
def test_bare_name_does_not_fire_on_weekday_names(day: str):
    text = f"Bolo to v {day} Ráno pred súdom."
    hits = [c for c in _detect(text) if day in c.surface]
    assert not hits, [(c.type, c.surface) for c in hits]


def test_bare_name_nbsp_separated():
    _assert_hit(
        f"Dostavil sa Jozef{NBSP}Sedlák a podpísal.", "MENO", f"Jozef{NBSP}Sedlák",
        auto=False,
    )


def test_every_bare_name_candidate_is_auto_false():
    text = "Dostavili sa Jozef Sedlák a Mária Kováčová podľa zoznamu."
    review = [c for c in _detect(text) if not c.auto]
    assert review, "bare-name heuristic produced nothing"
    assert all(c.type == "MENO" and c.checksum == "n/a" for c in review)


def test_anchored_name_is_not_also_emitted_as_review_on_the_same_span():
    """An auto anchor and the review heuristic on the SAME span would be resolved by
    core's flag-survival rule in favour of auto=False — silently DOWNGRADING a
    title-anchored name to the unticked bucket. The module must not emit that pair."""
    for text in (
        "Zmluvu podpísal JUDr. Ján Novák dňa 1.1.2025.",
        "Za stranu koná predávajúci Ján Novák osobne.",
        "Riadok\nMeno a priezvisko: Ján Novák",
    ):
        cands = _detect(text)
        autos = [(c.start, c.end) for c in cands if c.auto]
        reviews = [(c.start, c.end) for c in cands if not c.auto]
        for rs, re_ in reviews:
            assert not any(
                rs < ae and as_ < re_ for as_, ae in autos
            ), f"review candidate overlaps an auto one in {text!r}"


# ================================================================== module invariants

def test_all_candidates_have_checksum_na_and_slice_correctly():
    text = (
        "JUDr. Ján Novák, predávajúci, Trvale bytom: Hlavná 12, 040 01 Košice\n"
        "Obchodné meno: Alfa s.r.o.\n"
        "Následne sa dostavila Mária Kováčová osobne."
    )
    cands = detect_name_anchors(text, DEFAULT)
    assert cands, "no candidates from a fully populated fixture"
    for c in cands:
        assert c.checksum == "n/a"
        assert text[c.start : c.end] == c.surface
        assert c.type in ("MENO", "ADRESA", "ORG", "STATNA_PRISLUSNOST")


def test_output_is_sorted_and_span_unique():
    text = "Za stranu konal JUDr. Ján Novák a svedok Peter Malý potvrdil."
    cands = detect_name_anchors(text, DEFAULT)
    assert cands == sorted(cands, key=lambda c: (c.start, c.end))
    spans = [(c.type, c.start, c.end) for c in cands]
    assert len(spans) == len(set(spans))


def test_empty_and_junk_input_do_not_raise():
    for text in ("", "   ", "...", "JUDr.", "Meno:", "\n\n", "x" * 5000):
        assert isinstance(detect_name_anchors(text, DEFAULT), list)


def test_module_does_not_import_corpus_or_eval():
    import pathlib

    import detect.name_anchors as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert "import corpus" not in src and "from corpus" not in src
    assert "import eval" not in src and "from eval" not in src
