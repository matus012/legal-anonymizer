"""TDD spec for corpus/pii/ulica.py (CONTRACTS_v11.md §12 ADDENDUM 1 R3; task: give ULICA
real corpus coverage — redteam/FINDINGS_ROUND2.md finding C-2 recorded ZERO ground-truth
ULICA occurrences anywhere in the 70-document corpus).

This file exercises the GENERATOR against the REAL detector (``detect.gazetteer`` /
``detect.core.detect``) rather than hand-built fixtures, because the whole point of this
module is proving every shape it authors is one the detector can actually see — a generator
that drifts from the detector's real rule would silently re-create the C-2 gap under a
different name. ``tests/`` importing ``corpus/`` is the established pattern for this exact
purpose elsewhere in the suite (``tests/test_generate_smoke.py``, which also runs generators
against real output).
"""
from __future__ import annotations

import random

import pytest

from corpus.groundtruth import PiiSpec
from corpus.pii import ulica
from detect.config import DEFAULT
from detect.core import KNOWN_TYPES, detect
from detect.gazetteer import detect_gazetteer

_MAKERS = (
    ulica.make_ulica_ul,
    ulica.make_ulica_keyword,
    ulica.make_ulica_housenum,
    ulica.make_ulica_declined,
)


# --------------------------------------------------------------------------- real data
def test_real_streets_are_nonempty_and_real():
    pool = ulica._real_streets()
    assert len(pool) > 100
    # every entry really is in the bundled gazetteer file the detector itself reads
    import json

    with open(ulica._ULICE_PATH, encoding="utf-8") as fh:
        gazetteer = set(json.load(fh))
    assert set(pool) <= gazetteer


def test_real_streets_excludes_stoplisted_and_multiword():
    pool = ulica._real_streets()
    assert "Nová" not in pool  # stoplisted (context.md §4.2 / detect/gazetteer.py stoplist)
    assert all(" " not in s for s in pool)


def test_real_streets_deterministic_pick():
    a = ulica._pick_street(random.Random(5))
    b = ulica._pick_street(random.Random(5))
    assert a == b


# --------------------------------------------------------------------------- shape contract
@pytest.mark.parametrize("maker", _MAKERS)
def test_maker_returns_placed_and_spec_with_surface_inside(maker):
    rng = random.Random(1)
    placed, spec = maker(rng)
    assert isinstance(spec, PiiSpec)
    assert spec.type == "ULICA"
    assert spec.auto_redact is True
    assert spec.should_flag is False
    assert spec.checksum == "n/a"
    assert spec.surface in placed
    assert len(spec.surface) >= 3  # corpus.groundtruth._validate's gradeability floor


def test_make_all_covers_every_shape():
    rng = random.Random(2)
    results = ulica.make_all(rng)
    assert len(results) == 4
    for placed, spec in results:
        assert spec.surface in placed
        assert spec.type == "ULICA"


# --------------------------------------------------------------------------- detector proof
# Every KNOWN detected shape must actually be found by the real detector at the exact
# surface — this is the guarantee that closes redteam C-2 (a generator with no end-to-end
# proof is a generator that only LOOKS like coverage).
def test_ul_prefix_is_detected():
    rng = random.Random(3)
    placed, spec = ulica.make_ulica_ul(rng)
    cands = detect_gazetteer(placed, DEFAULT)
    hits = [c for c in cands if c.type == "ULICA" and c.surface == spec.surface]
    assert len(hits) == 1, (placed, cands)
    assert hits[0].auto is True


def test_keyword_prefix_is_detected_for_every_keyword():
    # Exercise every one of the five non-"ul." keywords directly (contract §12 / task shape
    # b), not just whatever rng.choice happens to land on once.
    for keyword in ulica._KEYWORDS_NON_UL:
        street = ulica._pick_street(random.Random(11))
        text = f"{keyword} {street}"
        cands = detect_gazetteer(text, DEFAULT)
        hits = [c for c in cands if c.type == "ULICA" and c.surface == street]
        assert len(hits) == 1, (keyword, text, cands)


def test_housenum_is_detected():
    rng = random.Random(4)
    placed, spec = ulica.make_ulica_housenum(rng)
    cands = detect_gazetteer(placed, DEFAULT)
    hits = [c for c in cands if c.type == "ULICA" and c.surface == spec.surface]
    assert len(hits) == 1, (placed, cands)


def test_bare_street_with_no_anchor_is_not_detected():
    """Sanity check on the rule itself (task step 1): an unanchored street name must be
    DROPPED, not just demoted — matches CONTRACTS_v11.md §12 / ADDENDUM 1 R3 and
    ``detect/gazetteer.py::_street_hits`` exactly as read."""
    street = ulica._pick_street(random.Random(6))
    text = f"Videli sme {street} zďaleka."
    cands = detect_gazetteer(text, DEFAULT)
    assert not any(c.type == "ULICA" for c in cands), cands


# --------------------------------------------------------------------------- the hard case
def test_declined_form_is_now_DETECTED():
    """This test was written to FAIL the day the gap closed, and that is what happened.

    It used to assert the opposite -- that ``make_ulica_declined`` is deliberately seeded even
    though the detector misses it -- with the note that "a future fix to the declension engine's
    suffix inventory is NOTICED here rather than the gap silently persisting forever". It did
    its job, so it is inverted rather than deleted: the same fixture now pins the FIX.

    The fix is NOT in the declension engine's suffix inventory, which is what the old note
    expected. That inventory still excludes the plain adjectival "-ej" on purpose -- the
    exclusion is what keeps a possessive form of a SURNAME ("Kováčovej", which IS the person)
    apart from an adjective derived from it. Widening it would have broken names to fix
    streets. Instead ``detect/gazetteer.py`` GENERATES the declined forms of the street names
    it already knows and indexes those, so nothing about the stemmer changed.
    """
    placed, spec = ulica.make_ulica_declined(random.Random(0))
    assert spec.surface == "Hlavnej"
    cands = detect(placed)
    assert any(c.type == "ULICA" and c.surface == spec.surface for c in cands), cands


def test_the_surname_stemmer_was_not_widened_to_achieve_it():
    """The constraint the fix had to respect. If these two stems ever collapse, the street fix
    has been paid for with the surname/adjective discriminator -- which is the one thing
    detect/declension.py's closed suffix inventory exists to protect."""
    from detect.declension import stem

    assert stem("Kováčovej") == stem("Kováč"), "a possessive surname form must still match"
    assert stem("Kováčskej") != stem("Kováč"), "an adjective from the surname must NOT match"


def test_declined_form_surface_is_gradeable_length():
    _, spec = ulica.make_ulica_declined(random.Random(0))
    assert len(spec.surface.strip()) >= 3


# --------------------------------------------------------------------------- registry sanity
def test_ulica_is_a_known_type():
    assert "ULICA" in KNOWN_TYPES
