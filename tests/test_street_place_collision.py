"""A STREET NAMED AFTER A MUNICIPALITY was not redacted at all.

Slovak street names and Slovak municipality names overlap heavily: ``Polom`` and ``Banka``
are both, and so are ``Nižná``, ``Staré`` and ``Zálesie``. Those collisions put the name on
``stoplist.json``, and the street walk used to demand an explicit street keyword (``ul.``,
``ulica``, ``nám.``) before it would emit a stoplisted name — a house number after the name,
which anchors any NON-stoplisted street, was thrown away.

So "Vchod do budovy je na Polom 453." produced no ULICA candidate of any kind. The only
survivor was the place walk's ``OBEC(auto=False)``: the REVIEW bucket, unticked, nothing
auto-redacts the span, and the street reaches the exported document. Reproduced on a rebuilt
corpus as a dual-format leak on ``zmluva_v11_069`` (``document_xml`` and ``text_layer``); the
committed ``data/synthetic`` only passes because it happens to draw ``Paulenova``, which the
``-ova`` suffix rule catches. The defect is in ``detect/``, not in the corpus.

THE FIX, and the two things it must not break
---------------------------------------------
A house number after the name is exactly the independent evidence the stoplist exists to
demand — it rules out "Zmluva je krátka". It is re-admitted in the street walk only, behind:

* an ENUMERATOR list, because "Strana 3 z 12" is a page footer and ``Strana``, ``Príloha``
  and ``List`` are all real entries in ``ulice.json``; and
* a DATE SHAPE guard, because CONTRACTS_v11.md Amendment 17 stoplisted the weekday names
  after the tool auto-redacted "Pondelok" out of contracts, and "vo štvrtok 5. mája 2026"
  puts a day number exactly where a house number goes. ``Streda`` stems to ``stred``, which
  IS in ``ulice.json``, so that guard is load-bearing rather than theoretical.

The table below is the whole finding. A single-string test is what let a similar gap through
earlier the same day, so every sentence that was reasoned about is pinned here.
"""
import pytest

from detect.core import detect

# (sentence, substring that must / must not be covered by an AUTO candidate, must_be_auto)
CASES: list[tuple[str, str, bool]] = [
    # ---------------------------------------- THE REPRODUCTIONS: street == municipality
    ("Vchod do budovy je na Polom 453.", "Polom", True),
    ("Býva na Banke 7.", "Banke", True),
    # ---------------------------------------- other stoplisted place-names with a house number
    ("Nižná 14", "Nižná", True),
    ("Staré 9", "Staré", True),
    ("Banka 7/A", "Banka", True),
    # ---------------------------------------- unchanged paths that must stay auto
    ("bytom Sokolovce 21", "Sokolovce", True),   # not stoplisted at all
    ("ul. Strana 3", "Strana", True),            # explicit keyword beats the enumerator list
    # ---------------------------------------- MUST NOT: legal-document enumerators
    ("Strana 3 z 12", "Strana", False),
    ("Príloha 2", "Príloha", False),
    ("List 4", "List", False),
    ("Článok 5", "Článok", False),
    ("Odsek 2", "Odsek", False),
    # ---------------------------------------- MUST NOT: weekday + date (Amendment 17)
    ("Stretnutie sa koná vo štvrtok 5. mája 2026.", "štvrtok", False),
    ("Štvrtok 5. mája 2026 je termín.", "Štvrtok", False),
    ("Streda 12. júna", "Streda", False),
    ("v stredu 12. júna", "stredu", False),
    ("Streda 12. 6. 2026", "Streda", False),
    ("Pondelok 3. augusta", "Pondelok", False),
    # ---------------------------------------- MUST NOT: ordinary word, no number
    ("Zmluva je krátka", "Zmluva", False),
    ("Lipa je strom", "Lipa", False),
]


def _auto_covering(sentence: str, target: str) -> list:
    i = sentence.find(target)
    assert i >= 0, f"test bug: {target!r} not in {sentence!r}"
    j = i + len(target)
    return [c for c in detect(sentence) if c.auto and c.start <= i and c.end >= j]


@pytest.mark.parametrize("sentence,target,must_be_auto", CASES, ids=[c[0] for c in CASES])
def test_street_place_collision(sentence: str, target: str, must_be_auto: bool) -> None:
    auto = _auto_covering(sentence, target)
    if must_be_auto:
        assert auto, (
            f"LEAK: nothing auto-redacts {target!r} in {sentence!r}; "
            f"all candidates = {[(c.type, c.surface, c.auto) for c in detect(sentence)]}"
        )
    else:
        assert not auto, (
            f"false positive: {target!r} in {sentence!r} was auto-redacted as "
            f"{[(c.type, c.surface) for c in auto]}"
        )


@pytest.mark.parametrize("sentence,target", [
    ("Vchod do budovy je na Polom 453.", "Polom"),
    ("Býva na Banke 7.", "Banke"),
])
def test_polom_and_banka_are_the_reproductions(sentence: str, target: str) -> None:
    """Named explicitly: these two sentences are the finding, verbatim.

    The label is asserted as ULICA — a house number is street evidence, and it is what the
    ground truth says. An AUTO ULICA on the span beats the review-bucket OBEC/KATASTER in
    ``core.py``'s ``_resolve_flag_survival``, which runs BEFORE ``_TYPE_PRECEDENCE``, so the
    weak ULICA rank cannot re-demote it.
    """
    auto = _auto_covering(sentence, target)
    assert [c.type for c in auto] == ["ULICA"]
    assert [c.surface for c in auto] == [target]


def test_house_number_is_what_flips_a_weekday_street() -> None:
    """The DATE SHAPE, not the capitalisation, is what blocks the weekday case.

    ``Streda`` -> stem ``stred``, a real ``ulice.json`` entry, stoplisted. With a bare number
    after it, it auto-redacts; with a date after it, it must not. If this test ever passes
    because the guard was replaced by a blanket weekday exclusion, the first assert fails.
    """
    assert [c.type for c in _auto_covering("Streda 12", "Streda")] == ["ULICA"]
    assert not _auto_covering("Streda 12. júna", "Streda")


@pytest.mark.xfail(strict=True, reason=(
    "RESIDUAL, same class, NOT fixed here: 'Zálesie' is a municipality and is stoplisted, but "
    "it has no entry in ulice.json, so the STREET walk never sees it and the house-number "
    "evidence cannot be re-admitted there. Fixing it means loosening the PLACE walk's "
    "_place_anchored, which is where 'Štvrtok'/'Pondelok' live and where CONTRACTS_v11.md "
    "Amendment 17 applies directly — out of scope for this change, recorded so it is not "
    "rediscovered as a surprise."
))
def test_place_only_collision_still_leaks_to_review() -> None:
    assert _auto_covering("Zálesie 3", "Zálesie")


def test_trailing_sentence_period_is_not_a_date() -> None:
    """"na Polom 453." ends a sentence. A dot alone must not read as a date separator."""
    assert _auto_covering("Býva na Polom 453.", "Polom")
