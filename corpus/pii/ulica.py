"""Corpus PII generator for ULICA (CONTRACTS_v11.md §12 ADDENDUM 1 R3;
redteam/FINDINGS_ROUND2.md finding C-2): the street-name gazetteer type owned by
``detect/gazetteer.py``'s ``_street_hits`` / ``_street_anchored``.

Zero ground-truth ULICA occurrences existed anywhere in the 70-document corpus before this
round (C-2: "an excluded type is an UNTESTED type ... less visibly"). This module closes the
gap the same way ``corpus/pii/addresses.py`` and ``corpus/pii/orgs.py`` closed theirs for
their own types: one generator per detector-claimed shape, wired into a template by a later
step in this same round.

THE DETECTOR RULE, verified by READING ``detect/gazetteer.py`` (not assumed from the
contract's prose — the task instruction is explicit that the CODE is the truth here):

    a gazetteer street name is emitted as ULICA only when
      * it is preceded, within 25 chars, by one of the keyword anchors
        ``ul. / ulica / nám. / námestie / trieda / cesta`` (``_STREET_KEYWORD_RE``,
        case-insensitive), OR
      * — single-word entries only — it is followed immediately by a house number
        (``_HOUSENUM_AFTER_RE``). A multi-word entry with no keyword is dropped even when a
        number follows (see ``_street_hits``'s "the longer entry exists ... but nothing
        anchors it here" branch).
    A bare, unanchored street name is DROPPED entirely, never demoted to review
    (``_street_hits`` simply does not append a candidate). This matches
    CONTRACTS_v11.md §12 / ADDENDUM 1 R3 exactly — no discrepancy between the contract and
    the code was found for this rule.

Real street names are read straight from the bundled ``detect/gazetteer_data/ulice.json``
(Register adries, CC0) — the SAME file the detector loads via
``detect.gazetteer._load_names`` — filtered the same way ``detect.gazetteer._capitalized``
filters tokens (>=3 chars, initial capital, a lowercase letter after it) and against the
bundled stoplist, so every surface here is a real Slovak street name the detector can
actually see matched unconditionally (not one of the 79 stoplist-collision words, whose
number-after anchor alone is not strong enough — ``_street_anchored(..., stoplisted=True)``).
This module does not import ``detect/`` itself (no module in ``corpus/pii/`` does); it reads
the identical data file directly, so there is exactly one gazetteer on disk to keep in sync.

``make_ulica_*(rng)`` all return ``(placed, PiiSpec)`` like every other generator in this
package: ``placed`` is the text a template embeds; ``PiiSpec.surface`` is EXACTLY the span
``_street_hits`` emits — the street name only. Neither the keyword prefix nor a trailing
house number is ever part of the matched span (confirmed by reading ``_street_hits``:
the appended ``Candidate`` spans only the name's own tokens).

``make_ulica_declined`` is the DELIBERATE HARD CASE the task asks for even though the
detector is expected to miss it: report the miss, don't omit the fixture. The ULICA walk
matches by ``detect.declension.stem``, whose case-ending inventory is CLOSED and
deliberately excludes plain adjectival endings (a bare ``-ej`` off a nominative ``-á``) to
keep the surname-adjective discriminator intact (see ``detect/declension.py``'s module
docstring: only ``-ovej``, the POSSESSIVE-adjective ending, is in the inventory). A
plain-adjective street name such as ``Hlavná`` inflects to ``Hlavnej`` in the genitive /
dative / locative, and ``stem("Hlavnej") != stem("Hlavná")`` — so no candidate is ever
produced for it, anchored or not. This is the exact same documented sub-gap
``detect/gazetteer.py`` already records for multi-word OBEC/KATASTER entries with an
adjectival modifier (the "KNOWN SUB-GAP" in its module docstring), now instantiated for
ULICA. ``Hlavná`` is chosen specifically because it is a PLAIN adjective, not a possessive
``-ova`` form like ``Štúrova`` (whose ``-ovej`` declension the stemmer DOES catch) — so the
miss is genuine Slovak grammar, not a fixture mistake. The anchor keyword is declined too
(``ulici``, not ``ulica``), so neither anchor path can fire either.

Every occurrence here is shape-only, no checksum:
``auto_redact=True, should_flag=False, checksum="n/a"``.
"""
from __future__ import annotations

import functools
import json
import random
from pathlib import Path

from corpus.groundtruth import PiiSpec

_ULICE_PATH = Path(__file__).resolve().parents[2] / "detect" / "gazetteer_data" / "ulice.json"
_STOPLIST_PATH = (
    Path(__file__).resolve().parents[2] / "detect" / "gazetteer_data" / "stoplist.json"
)

# The five keyword anchors OTHER than "ul." (contract §12 / ADDENDUM 1 R3, task shape b).
_KEYWORDS_NON_UL = ("ulica", "nám.", "námestie", "trieda", "cesta")

# The one deliberately-hard fixture (see module docstring): a PLAIN adjective, not a
# possessive "-ova" street name, so its "-ej" declension is a genuine stemmer miss.
_DECLINED_NOMINATIVE = "Hlavná"
_DECLINED_LOCATIVE = "Hlavnej"


@functools.lru_cache(maxsize=None)
def _real_streets() -> tuple[str, ...]:
    """Single-token, genuinely capitalised, non-stoplisted street names from the SAME
    bundled data file the detector reads — real names, not invented ones, and ones the
    detector's own ``_capitalized`` / stoplist checks let through unconditionally."""
    with open(_ULICE_PATH, encoding="utf-8") as fh:
        names: list[str] = json.load(fh)
    with open(_STOPLIST_PATH, encoding="utf-8") as fh:
        stoplisted = set(json.load(fh))
    out = []
    for name in names:
        if " " in name or len(name) < 3:
            continue
        if not (name[:1].isupper() and any(ch.islower() for ch in name[1:])):
            continue
        if not name.isalpha():
            continue
        if name in stoplisted:
            continue
        out.append(name)
    return tuple(sorted(set(out)))


def _pick_street(rng: random.Random) -> str:
    return rng.choice(_real_streets())


def _house_number(rng: random.Random) -> str:
    n = str(rng.randint(1, 499))
    if rng.random() < 0.5:
        return n
    return f"{n}/{rng.choice(('A', 'B', str(rng.randint(1, 40))))}"


def _spec(street: str) -> PiiSpec:
    return PiiSpec(surface=street, type="ULICA", auto_redact=True, should_flag=False)


# --------------------------------------------------------------------------- "ul." prefix
def make_ulica_ul(rng: random.Random) -> tuple[str, PiiSpec]:
    """Nominative street, the ``ul.`` prefix specifically (task shape a)."""
    street = _pick_street(rng)
    return f"ul. {street}", _spec(street)


# ------------------------------------------------------------------ other keyword prefixes
def make_ulica_keyword(rng: random.Random) -> tuple[str, PiiSpec]:
    """Nominative street with one of the other five keyword anchors (task shape b),
    spread across generated occurrences by ``rng.choice``."""
    street = _pick_street(rng)
    keyword = rng.choice(_KEYWORDS_NON_UL)
    return f"{keyword} {street}", _spec(street)


# --------------------------------------------------------------------------- house number
def make_ulica_housenum(rng: random.Random) -> tuple[str, PiiSpec]:
    """Street immediately followed by a house number, no keyword needed (task shape c) —
    the ``_HOUSENUM_AFTER_RE`` path in ``_street_hits``."""
    street = _pick_street(rng)
    house = _house_number(rng)
    return f"{street} {house}", _spec(street)


# --------------------------------------------------------------------------- declined miss
def make_ulica_declined(rng: random.Random) -> tuple[str, PiiSpec]:
    """Declined (locative) form — the DELIBERATE hard case (task shape d), expected to be
    MISSED by the current detector (see module docstring). Deterministic on purpose: this
    is one specific documented fixture, not a randomly varied one."""
    del rng  # unused: exactly one hand-picked hard fixture, see module docstring
    placed = f"na {_DECLINED_LOCATIVE} ulici"
    return placed, PiiSpec(
        surface=_DECLINED_LOCATIVE, type="ULICA", auto_redact=True, should_flag=False
    )


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    """One of every ULICA shape this module generates."""
    return [
        make_ulica_ul(rng),
        make_ulica_keyword(rng),
        make_ulica_housenum(rng),
        make_ulica_declined(rng),
    ]
