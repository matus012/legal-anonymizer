"""OBEC/KATASTER label precedence (detect/gazetteer.py, ``_kataster_anchored``) — anchor
spelling x place matrix.

A single-string test ("k. ú. Ružinov" -> KATASTER) is what let the FIRST version of this fix
through with "kat. území" (the abbreviated LOCATIVE) unmatched: "kat. územie" (nominative,
matched) and "katastrálnom území" (full-word locative, matched) both worked, so nothing in a
one-anchor test surfaced the missing combination of "abbreviated" x "locative". Only a matrix
over every anchor spelling x every place surfaces a hole like that, so the matrix itself is
the regression test, not just its passing cells.

Places (Michalovciach, Košiciach, Levoči, Trnave — locative-declined surfaces, matching how a
filing actually writes them after "v ...") are chosen because they are declined forms already
present in obce.json AND/OR katastralne_uzemia.json, so a candidate for each is guaranteed to
exist for at least one of the two types before an anchor is even considered.
"""
from __future__ import annotations

from detect.config import DEFAULT
from detect.gazetteer import detect_gazetteer

_ANCHORS = ["k.ú.", "k. ú.", "katastrálnom území", "kat. území", "katastrálne územie", "KÚ"]
_PLACES = ["Michalovciach", "Košiciach", "Levoči", "Trnave"]

# Expected {OBEC, KATASTER} label set for each (anchor, place) pair, once the anchor is
# recognised. Every anchor spelling behaves identically except for Košice/Bratislava, which
# stay OBEC-only under every anchor — see test_kosice_has_no_kataster_entry below for why
# that is correct rather than a suppressed KATASTER hit.
_EXPECTED: dict[str, set[str]] = {
    "Michalovciach": {"KATASTER"},
    "Košiciach": {"OBEC"},
    "Levoči": {"KATASTER"},
    "Trnave": {"KATASTER"},
}


def _labels(anchor: str, place: str) -> set[str]:
    text = f"Byt sa nachádza v {anchor} {place}."
    cands = detect_gazetteer(text, DEFAULT)
    return {
        c.type
        for c in cands
        if c.type in ("OBEC", "KATASTER") and text[c.start : c.end] == place
    }


def test_anchor_x_place_matrix() -> None:
    matrix = {anchor: {place: _labels(anchor, place) for place in _PLACES} for anchor in _ANCHORS}
    for anchor in _ANCHORS:
        for place in _PLACES:
            assert matrix[anchor][place] == _EXPECTED[place], (
                f"anchor={anchor!r} place={place!r}: got {matrix[anchor][place]}, "
                f"expected {_EXPECTED[place]}"
            )


def test_abbreviated_locative_kat_uzemi_is_anchored() -> None:
    """Regression for the specific hole the matrix found: "kat. území" (abbreviated
    adjective + full LOCATIVE noun) did not match before "|kat\\.{_SEP_ANCHOR}*uzemi[ae]?"
    replaced the nominative-only "|kat\\.{_SEP_ANCHOR}*uzemie" alternative."""
    assert _labels("kat. území", "Levoči") == {"KATASTER"}
    assert "OBEC" not in _labels("kat. území", "Levoči")


def test_kosice_has_no_kataster_entry() -> None:
    """Confirm the data, don't assume it: katastralne_uzemia.json (source: CL000026, the
    cadastral-area codelist) has no entry for Košice or Bratislava in ANY form — not bare,
    not a hyphenated borough form either. Unlike obce.json (whose bare "Košice"/"Bratislava"
    come from tools/build_gazetteer.py's ``_with_head_city_names`` deriving a head name out
    of the municipality register's "Košice-*"/"Bratislava-*" rows), the cadastral-area
    codelist's entries for these two cities are the real historic cadastral-area names
    ("Ružinov", "Nivy", ...), not city-prefixed rows, so there is nothing to derive a head
    name FROM. So OBEC is the ONLY register with a matching entry for these two cities, under
    any anchor — that is the data speaking, not a suppression bug."""
    import json
    from pathlib import Path

    data_dir = Path(__file__).resolve().parent.parent / "detect" / "gazetteer_data"
    kataster_names = json.loads((data_dir / "katastralne_uzemia.json").read_text("utf-8"))
    obec_names = json.loads((data_dir / "obce.json").read_text("utf-8"))

    assert "Košice" not in kataster_names
    assert "Bratislava" not in kataster_names
    assert not any(n.startswith("Košice-") for n in kataster_names)
    assert not any(n.startswith("Bratislava-") for n in kataster_names)

    assert "Košice" in obec_names
    assert "Bratislava" in obec_names

    # And detect_gazetteer agrees with the data: no anchor can produce a KATASTER candidate
    # for a city the register does not have.
    for anchor in _ANCHORS:
        assert _labels(anchor, "Košiciach") == {"OBEC"}
