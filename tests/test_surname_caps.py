"""TDD spec for the caps-SURNAME convention (mutation gate, `surname_caps` arm,
corpus/mutations.py::mutate_surname_caps): continental legal drafting sets a party's
surname (or, at a heading, a whole title) in full capitals inside an otherwise
mixed-case document -- "Ján NOVÁK", "NOVÁK Ján", "JUDr. Mária KOVÁČOVÁ". This file locks
that `detect_name_anchors` recognises the MIXED shape (one Capitalized token next to one
all-caps token) and rejects the ALL-CAPS shape (a heading, not a name).

tests/ must NOT import corpus/ or eval/ (CONTRACTS_v11.md §11). Fixtures are hand-built
literal strings. Saved UTF-8 with real Slovak diacritics.
"""
from __future__ import annotations

from detect.config import DEFAULT
from detect.name_anchors import detect_name_anchors


def _detect(text: str):
    return detect_name_anchors(text, DEFAULT)


def _menos(text: str):
    return [c for c in _detect(text) if c.type == "MENO"]


def _covers(cands, needle: str) -> bool:
    return any(needle in c.surface for c in cands)


# ============================================================================ POSITIVE

def test_given_name_then_caps_surname_is_a_meno_candidate():
    text = "Zmluvu uzavrel Ján NOVÁK, bytom Košice."
    menos = _menos(text)
    assert _covers(menos, "NOVÁK"), menos


def test_caps_surname_then_given_name_is_a_meno_candidate():
    text = "Zmluvu uzavrel NOVÁK Ján, bytom Košice."
    menos = _menos(text)
    assert _covers(menos, "NOVÁK"), menos


def test_title_anchor_with_caps_surname_is_auto():
    text = "JUDr. Peter KOVÁČ, advokát"
    menos = _menos(text)
    hits = [c for c in menos if "KOVÁČ" in c.surface]
    assert hits, menos
    assert all(c.auto is True for c in hits), hits


def test_role_anchor_with_caps_surname_is_auto():
    text = "Predávajúci: Mária KOVÁČOVÁ"
    menos = _menos(text)
    hits = [c for c in menos if "KOVÁČOVÁ" in c.surface]
    assert hits, menos
    assert all(c.auto is True for c in hits), hits


def test_female_form_title_anchor_with_caps_surname():
    text = "Ing. Zuzana NOVÁKOVÁ"
    menos = _menos(text)
    hits = [c for c in menos if "NOVÁKOVÁ" in c.surface]
    assert hits, menos
    assert all(c.auto is True for c in hits), hits


# ============================================================================ NEGATIVE

def test_all_caps_document_title_heading_is_not_a_name():
    text = "KÚPNA ZMLUVA"
    assert _menos(text) == []


def test_all_caps_article_heading_is_not_a_name():
    text = "ČLÁNOK I"
    assert _menos(text) == []


def test_all_caps_preamble_heading_is_not_a_name():
    text = "V MENE SLOVENSKEJ REPUBLIKY"
    assert _menos(text) == []


def test_all_caps_boilerplate_sentence_is_not_a_name():
    text = "TÁTO ZMLUVA NADOBÚDA PLATNOSŤ DŇOM PODPISU OBOMA ZMLUVNÝMI STRANAMI."
    assert _menos(text) == []


# ==================================================================== REGRESSION PINS

def test_lowercase_role_word_before_mixed_case_name_is_not_swallowed():
    # "vypracoval Ján Novák, PhD." -- the lowercase anchor word "vypracoval" must not
    # become part of the captured name even though the caps-SURNAME alternative widened
    # `_NAME_SEQ`; this document is ordinary mixed-case, so it never reaches the
    # `document_is_single_case` relaxation that could have swallowed it.
    text = "vypracoval Ján Novák, PhD."
    c = _assert_single_hit(text, "Ján Novák")
    assert "vypracoval" not in c.surface


def _assert_single_hit(text: str, surface: str):
    hits = [c for c in _menos(text) if c.surface == surface]
    assert hits, (text, _menos(text))
    return hits[0]
