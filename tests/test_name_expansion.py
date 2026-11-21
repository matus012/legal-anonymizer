"""TDD spec for detect/expansion.py (C1 round): known-entity expansion.

``expand_person`` / ``expand_address`` widen the lawyer's typed known-entity list into
every written form the same person/address appears in, BEFORE the list reaches
``detect_known_entities``. Pure functions, no Candidate emission.

tests/ must NOT import corpus/ (CONTRACTS_v11.md §11) — every fixture is a literal here.

THE DISCRIMINATOR (context.md §5, detect/declension.py's module docstring) is exercised
at the bottom of this file: a possessive declension of a surname IS the person and must
match; the occupational/demonym ADJECTIVE built from the same surname is a different word
and must NOT. detect/name_anchors.py does not touch that path (it is surface/anchor based,
not stem based), so it is proven here, on the expansion path, which is the one that feeds
the stemmer.
"""
from __future__ import annotations

import pytest

from detect.declension import match_entity, stem
from detect.expansion import expand_address, expand_person

NBSP = " "


# ================================================================== expand_person

def test_input_is_first_and_result_is_deduplicated():
    out = expand_person("Ján Novák")
    assert out[0] == "Ján Novák"
    assert len(out) == len(set(out))


@pytest.mark.parametrize(
    "variant",
    ["Nováková", "J. Novák", "Novák J.", "Jan Novak", "p. Novák"],
)
def test_expand_person_generates_the_required_variants(variant: str):
    assert variant in expand_person("Ján Novák"), sorted(expand_person("Ján Novák"))


def test_expand_person_generates_pan_and_pani_forms():
    out = expand_person("Ján Novák")
    assert "pán Novák" in out
    assert "pani Nováková" in out or "pani Novák" in out


def test_female_surname_form_of_adjectival_surname_uses_a_not_ova():
    out = expand_person("Peter Veselý")
    assert "Veselá" in out, sorted(out)


def test_female_surname_form_of_a_ending_surname():
    out = expand_person("Peter Svoboda")
    assert "Svobodová" in out, sorted(out)


def test_declension_stems_are_included_for_every_token():
    out = expand_person("Ján Novák")
    assert stem("Novák") in out
    assert stem("Ján") in out


def test_diacritic_stripped_variant_of_a_carons_name():
    out = expand_person("Mária Kováčová")
    assert "Maria Kovacova" in out, sorted(out)


def test_initials_require_two_tokens():
    out = expand_person("Novák")
    assert out[0] == "Novák"
    assert not any(". " in v and v.startswith("N.") for v in out)


def test_three_token_name_uses_first_and_last_for_initials():
    out = expand_person("Ján Peter Novák")
    assert "J. Novák" in out
    assert "Novák J." in out


def test_nbsp_separated_input_is_tokenised():
    out = expand_person(f"Ján{NBSP}Novák")
    assert "Nováková" in out
    assert "J. Novák" in out


@pytest.mark.parametrize(
    "junk",
    ["", "   ", ".", "...", ",.;", "-", "a", "X" * 4000, NBSP, "\n\t"],
)
def test_expand_person_is_total_on_junk(junk: str):
    out = expand_person(junk)
    assert isinstance(out, list)
    assert all(isinstance(v, str) for v in out)


# ================================================================= expand_address

def test_expand_address_splits_into_street_obec_and_psc():
    out = expand_address("Hlavná 12, 040 01 Košice")
    assert "Hlavná 12, 040 01 Košice" in out          # the full address
    assert any(v.startswith("Hlavná") for v in out)   # the street
    assert "040 01" in out                            # the PSČ
    assert "Košice" in out                            # the obec


def test_expand_address_bare_street_name_is_emitted():
    out = expand_address("Štúrova 3, 811 09 Bratislava")
    assert "Štúrova" in out, sorted(out)


def test_expand_address_contiguous_psc():
    out = expand_address("Nová 8, 04001 Košice")
    assert "04001" in out
    assert "Košice" in out


def test_expand_address_nbsp_psc():
    out = expand_address(f"Nová 8, 040{NBSP}01 Košice")
    assert any(v.replace(NBSP, " ") == "040 01" for v in out), sorted(out)


def test_expand_address_result_is_deduplicated_and_input_first():
    addr = "Hlavná 12, 040 01 Košice"
    out = expand_address(addr)
    assert out[0] == addr
    assert len(out) == len(set(out))


@pytest.mark.parametrize(
    "junk",
    ["", "   ", ",,,", "12", "Košice", "X" * 4000, NBSP, "\n\t", "040 01"],
)
def test_expand_address_is_total_on_junk(junk: str):
    out = expand_address(junk)
    assert isinstance(out, list)
    assert all(isinstance(v, str) for v in out)


# ============================================================= THE DISCRIMINATOR

def test_stemmer_discriminator_holds_at_the_stem_level():
    """Baseline: the possessive collapses to the bare stem, the adjective does not."""
    assert stem("Kováčovej") == stem("Kováč")
    assert stem("Kováčskej") != stem("Kováč")


def test_expansion_matches_the_possessive_declension_of_the_surname():
    variants = expand_person("Ján Kováč")
    text = "Dokument obsahuje Kováčovej podpis"
    assert any(match_entity(text, v) for v in variants), (
        "possessive declension of the surname MUST match — it is the person"
    )


def test_expansion_does_not_match_the_occupational_adjective():
    variants = expand_person("Ján Kováč")
    text = "Dokument obsahuje Kováčskej dielne"
    hits = [(v, match_entity(text, v)) for v in variants if match_entity(text, v)]
    assert not hits, (
        f"adjectival derivation must NOT match the surname; matched via {hits!r}"
    )


def test_expansion_does_not_widen_the_stemmer_suffix_inventory():
    """No expansion variant may be an adjectival form that would re-introduce the
    excluded endings through the back door."""
    variants = expand_person("Ján Kováč")
    for bad in ("Kováčsky", "Kováčska", "Kováčskej", "Kováčskeho"):
        assert bad not in variants
