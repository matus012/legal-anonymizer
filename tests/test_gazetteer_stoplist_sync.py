"""The stoplist ARTIFACT must equal its SOURCE constant.

`detect/gazetteer_data/stoplist.json` is the file that runs. `tools/build_gazetteer.py`'s
`COMMON_WORD_STOPLIST` is the file that gets READ — it is where the reasoning lives, where
Amendment 17 was written down, and what anybody edits when they want to change behaviour.
Nothing compared the two, and on 2026-09-17 they had silently drifted apart:

    committed stoplist.json : "Štvrtok", "Nedeľa"      (with diacritics)
    COMMON_WORD_STOPLIST    : "Stvrtok", "Stvrtok", "Nedela"   (without, and duplicated)

That is not cosmetic. `detect/declension.py::stem` casefolds and folds vowel LENGTH but does
NOT strip diacritics, so `stem("Stvrtok") != stem("Štvrtok")` and only the diacritic spelling
stoplists the actual Slovak word. Regenerating the artifact from its own source therefore UNDID
Amendment 17 for Thursday — the amendment that exists because every KATASTER candidate in the
corpus was "Pondelok" and the tool was auto-redacting Monday out of contracts. It was found by
regenerating and measuring, not by reading.

This test is the comparison nobody was doing.
"""
from __future__ import annotations

import json
import pathlib

from detect.declension import stem
from tools.build_gazetteer import COMMON_WORD_STOPLIST

ARTIFACT = pathlib.Path("detect/gazetteer_data/stoplist.json")


def test_the_artifact_equals_its_source_constant() -> None:
    shipped = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert sorted(shipped) == sorted(COMMON_WORD_STOPLIST), (
        "detect/gazetteer_data/stoplist.json has drifted from "
        "tools/build_gazetteer.py::COMMON_WORD_STOPLIST. Regenerate the artifact — but check "
        "FIRST which side is right: on 2026-09-17 the ARTIFACT was the correct one and "
        "regenerating silently removed two entries."
    )


def test_the_weekday_names_are_stoplisted_in_their_real_slovak_spelling() -> None:
    """The specific trap. A weekday spelled without its diacritics does not stoplist the word
    a Slovak document contains, because stem() does not strip diacritics."""
    shipped = set(json.loads(ARTIFACT.read_text(encoding="utf-8")))
    for word in ("Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota", "Nedeľa"):
        assert word in shipped, f"{word!r} is not stoplisted in its real spelling"

    # And the reason it has to be the real spelling, asserted rather than described:
    assert stem("Stvrtok") != stem("Štvrtok"), (
        "stem() now folds diacritics; if that is intentional, this whole class of drift "
        "becomes harmless and this test should be revisited"
    )


def test_bod_is_stoplisted() -> None:
    """"Bod 7." is how every numbered Slovak filing writes a numbered point, and "Bod" is a
    real municipality. Of 26 legal-structure words checked against detect(), it was the only
    one that auto-redacted on its own."""
    shipped = set(json.loads(ARTIFACT.read_text(encoding="utf-8")))
    assert "Bod" in shipped
