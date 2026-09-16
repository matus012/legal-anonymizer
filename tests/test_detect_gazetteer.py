"""Unit tests for detect/gazetteer.py (CONTRACTS_v11.md §8/§12, C3 round).

Hand-built fixture strings only — `tests/` must NOT import `corpus/` (contract §11). The
real bundled data files ARE read, because the point of this module is the bundled data:
a test against a stubbed 3-entry gazetteer would pass while the shipped lists are broken.

Every fixture name below was verified to be present in the bundled JSON before the test was
written (`Košice`, `Michalovce`, `Spišská Nová Ves`, `Bratislava`, `Vinohrady` (kataster,
NOT an obec), `Štúrova`, `Potok` (obec AND stoplisted ordinary word), `Novák`, `Kováč`,
`Ján`).
"""
from __future__ import annotations

import json

import pytest

from detect import gazetteer
from detect.config import DEFAULT
from detect.core import Candidate
from detect.gazetteer import GazetteerDataError, detect_gazetteer


def of_type(text: str, type_: str) -> list[Candidate]:
    return [c for c in detect_gazetteer(text, DEFAULT) if c.type == type_]


def autos(text: str, type_: str) -> list[Candidate]:
    return [c for c in of_type(text, type_) if c.auto]


def surfaces(text: str, type_: str) -> set[str]:
    return {c.surface for c in of_type(text, type_)}


# ------------------------------------------------------------------ OBEC + declension
@pytest.mark.parametrize(
    "form", ["Košice", "Košiciach", "Košíc", "Košiciam"]
)
def test_obec_kosice_every_case(form: str) -> None:
    text = f"Zmluva bola podpísaná v meste {form} dňa 5. marca 2025."
    hits = autos(text, "OBEC")
    assert [c.surface for c in hits] == [form]
    assert text[hits[0].start : hits[0].end] == form
    assert hits[0].checksum == "n/a"


@pytest.mark.parametrize("form", ["Michalovce", "Michalovciach", "Michaloviec"])
def test_obec_michalovce_every_case(form: str) -> None:
    assert form in {c.surface for c in autos(f"okres {form} podľa listu", "OBEC")}


def test_multiword_obec_is_one_span() -> None:
    text = "Nehnuteľnosť sa nachádza v obci Spišská Nová Ves v okrese."
    hits = autos(text, "OBEC")
    assert [c.surface for c in hits] == ["Spišská Nová Ves"]


def test_head_city_names_derived_by_the_builder_match() -> None:
    # The source register lists these ONLY by borough ("Košice-Sever", "Bratislava-Petržalka");
    # the bare head-city names are derived. Assert the bare form works — it is the single most
    # common town name in a Slovak contract.
    for city in ("Bratislava", "Košice"):
        assert city in {c.surface for c in autos(f"trvale bytom, 040 01 {city}", "OBEC")}


def test_lowercase_common_word_is_not_a_place() -> None:
    # gazetteer entries are proper nouns; a lowercase token is never a place hit
    assert of_type("pri potoku a lúke rástla lipa", "OBEC") == []


# ------------------------------------------------------------------------- KATASTER
def test_kataster_matches_and_inflects() -> None:
    # "Vinohrady" is a cadastral area and NOT a municipality — so this asserts the
    # katastralne_uzemia.json index specifically, not an OBEC hit wearing another label.
    text = "v katastrálnom území Vinohrady, okres Bratislava III"
    assert "Vinohrady" in {c.surface for c in autos(text, "KATASTER")}


# ---------------------------------------------------------------------------- ULICA
def test_ulica_auto_with_house_number() -> None:
    hits = autos("Adresa: Štúrova 12, 040 01 Košice", "ULICA")
    assert [c.surface for c in hits] == ["Štúrova"]


def test_ulica_auto_with_keyword_prefix() -> None:
    for prefix in ("ul.", "Ulica", "nám.", "Námestie", "trieda", "cesta"):
        text = f"bydlisko {prefix} Štúrova, Košice"
        assert "Štúrova" in {
            c.surface for c in autos(text, "ULICA")
        }, f"keyword {prefix!r} did not anchor the street"


def test_bare_street_name_is_not_auto() -> None:
    # NEGATIVE: neither a house number after nor an address keyword before.
    text = "Súd konštatoval, že Štúrova argumentácia bola nesprávna."
    assert autos(text, "ULICA") == []


# -------------------------------------------------------------------------- stoplist
def test_stoplisted_place_alone_is_not_auto() -> None:
    text = "Vodný Potok tvorí hranicu pozemku podľa znaleckého posudku."
    assert autos(text, "OBEC") == []


def test_stoplisted_place_with_address_anchor_is_auto() -> None:
    text = "trvale bytom obec Potok, okres Poprad"
    assert "Potok" in {c.surface for c in autos(text, "OBEC")}


def test_stoplisted_place_with_psc_after_is_auto() -> None:
    # no keyword before — the PSČ immediately after is the only anchor here
    text = "Uvedené takto: Potok 059 34, Slovenská republika"
    assert "Potok" in {c.surface for c in autos(text, "OBEC")}


# ------------------------------------------------------------------------------ MENO
def test_surname_only_is_review_bucket() -> None:
    text = "Vo veci vypovedal svedok Novák o priebehu udalostí."
    hits = of_type(text, "MENO")
    assert [(c.surface, c.auto) for c in hits] == [("Novák", False)]


def test_given_name_plus_capitalized_token_is_auto() -> None:
    text = "Podpísal Ján Novák, konateľ spoločnosti."
    hits = [c for c in of_type(text, "MENO") if c.auto]
    assert [c.surface for c in hits] == ["Ján Novák"]


def test_given_name_alone_is_review_bucket() -> None:
    text = "Svedok uviedol, že Ján tam v ten deň nebol."
    hits = of_type(text, "MENO")
    assert [(c.surface, c.auto) for c in hits] == [("Ján", False)]


def test_given_name_not_joined_across_sentence_boundary() -> None:
    text = "Prítomný bol aj Ján. Zmluva bola podpísaná."
    assert [c.surface for c in of_type(text, "MENO")] == ["Ján"]


# -------------------------------------------------------------------- THE DISCRIMINATOR
def test_possessive_declension_of_a_surname_matches() -> None:
    text = "Vo veci pani Kováčovej bolo rozhodnuté."
    assert [c.surface for c in of_type(text, "MENO")] == ["Kováčovej"]


def test_adjectival_form_from_the_same_stem_does_not_match() -> None:
    # stem("Kováčskej") != stem("Kováč") — the closed nominal-suffix inventory in
    # detect/declension.py is what makes this hold. This module reaches the stemmer through
    # the surname index, so it DOES exercise the discriminator path.
    text = "Bývala na Kováčskej ulici v meste."
    assert [c for c in detect_gazetteer(text, DEFAULT) if c.surface == "Kováčskej"] == []


# ------------------------------------------------------ data loading / the silent-zero trap
def test_missing_data_file_raises_named_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gazetteer, "_data_dir", lambda: tmp_path)
    gazetteer._clear_caches()
    with pytest.raises(GazetteerDataError) as exc:
        detect_gazetteer("Košice", DEFAULT)
    assert "obce.json" in str(exc.value)
    gazetteer._clear_caches()


def test_corrupt_data_file_raises_named_error(tmp_path, monkeypatch) -> None:
    (tmp_path / "obce.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(gazetteer, "_data_dir", lambda: tmp_path)
    gazetteer._clear_caches()
    with pytest.raises(GazetteerDataError) as exc:
        detect_gazetteer("Košice", DEFAULT)
    assert "obce.json" in str(exc.value)
    gazetteer._clear_caches()


def test_wrong_shape_data_file_raises_named_error(tmp_path, monkeypatch) -> None:
    (tmp_path / "obce.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    monkeypatch.setattr(gazetteer, "_data_dir", lambda: tmp_path)
    gazetteer._clear_caches()
    with pytest.raises(GazetteerDataError):
        detect_gazetteer("Košice", DEFAULT)
    gazetteer._clear_caches()


def test_indices_are_cached_not_reparsed() -> None:
    detect_gazetteer("Košice", DEFAULT)
    before = gazetteer._index.cache_info()
    detect_gazetteer("Košice", DEFAULT)
    after = gazetteer._index.cache_info()
    assert after.misses == before.misses  # no re-parse on the second page
