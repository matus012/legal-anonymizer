"""Address-block PII surfaces (CONTRACTS_v11.md §9, B1 round): PSC, ADRESA,
SUPISNE_CISLO, CISLO_BYTU, VCHOD, POSCHODIE — the six types ``detect/addresses.py``
claims to match.

Each ``make_<type>`` returns ``(surface, PiiSpec)`` for one authored occurrence, drawing
its surface shape from ``rng.choice`` over every variant the detector matches, so repeated
calls across a generated corpus exercise every variant the detector claims (contract §9:
"a variant with no generator is a variant with no end-to-end proof"). All six types are
shape-only with no checksum, so every emitted spec is ``auto_redact=True,
should_flag=False``.

Real Slovak street-name stems and obce (not invented placeholders) are used throughout so
the leak gate exercises the detector against text that could appear in an actual document.

``PiiSpec`` does not yet carry a ``checksum`` field (CONTRACTS_v11.md §7 adds it in a later
round) — every ``make_<type>`` below carries the TODO marker instead of passing the kwarg.
"""
from __future__ import annotations

import random

from corpus.groundtruth import PiiSpec

NBSP = " "

_STREETS = ("Hlavná", "Štúrova", "Slovenská", "Nová", "Košická", "Zelená", "Ľubochňa")
_KEYWORD_PREFIXES = ("ul.", "ulica", "nám.", "námestie", "trieda", "cesta", "sídlisko")
_BARE_ANCHORS = (
    "trvale bytom",
    "trvalé bydlisko",
    "bytom",
    "bydlisko",
    "so sídlom",
    "sídlo",
    "miesto podnikania",
    "na adrese",
    "adresa",
)
_OBCE = ("Košice", "Žilina", "Prešov", "Poprad", "Bratislava", "Trenčín")
_PSC_PAIRS = (("040", "01"), ("811", "09"), ("917", "01"), ("034", "91"))


def _sp(rng: random.Random) -> str:
    return NBSP if rng.random() < 0.5 else " "


def _house_number(rng: random.Random) -> str:
    n = str(rng.randint(1, 999))
    if rng.random() < 0.5:
        return n
    orient = rng.choice(("A", "B", str(rng.randint(1, 40))))
    return f"{n}/{orient}"


def make_psc(rng: random.Random) -> tuple[str, PiiSpec]:
    """PSC — spaced ("040 01") or contiguous ("04001"), with the anchor or obec context
    the detector requires (context.md §6: never generate the bare, context-free run the
    detector must NOT match).

    The detector never consumes the anchor keyword or the trailing obec token into the
    matched span (they are context checks only, contract §8), so the returned ``placed``
    snippet (what a template would embed in a document) carries that context, while
    ``PiiSpec.surface`` — the ground-truth redaction target — is the digit-only span the
    detector actually emits.
    """
    psc3, psc2 = rng.choice(_PSC_PAIRS)
    obec = rng.choice(_OBCE)
    variant = rng.choice(("spaced_anchor", "spaced_obec", "contig_anchor", "contig_obec"))
    if variant == "spaced_anchor":
        digits = f"{psc3}{_sp(rng)}{psc2}"
        placed = f"PSČ{_sp(rng)}{digits}"
    elif variant == "spaced_obec":
        digits = f"{psc3}{_sp(rng)}{psc2}"
        placed = f"{digits} {obec}"
    elif variant == "contig_anchor":
        digits = f"{psc3}{psc2}"
        placed = f"PSČ:{_sp(rng)}{digits}"
    else:
        digits = f"{psc3}{psc2}"
        placed = f", {digits} {obec}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=digits, type="PSC", auto_redact=True, should_flag=False)


def make_adresa(rng: random.Random) -> tuple[str, PiiSpec]:
    """ADRESA — keyword form (self-sufficient), or keyword-less form (needs a preceding
    address anchor, contract §8), either optionally extended with a trailing PSC + obec
    (the swallow extension the detector must produce, contract §4).

    The keyword form needs no external context, so ``placed`` equals the ground-truth
    surface exactly, matching every other type in this module. The keyword-less form
    needs the anchor phrase within 40 chars before it to fire at all, so ``placed``
    carries that anchor while ``PiiSpec.surface`` stays just the address span the
    detector actually emits (the anchor itself is never part of the match).
    """
    street = rng.choice(_STREETS)
    house = _house_number(rng)
    obec = rng.choice(_OBCE)
    psc3, psc2 = rng.choice(_PSC_PAIRS)
    variant = rng.choice(("keyword", "keyword_ext", "bare", "bare_ext"))
    if variant == "keyword":
        surface = f"{rng.choice(_KEYWORD_PREFIXES)} {street} {house}"
        placed = surface
    elif variant == "keyword_ext":
        surface = f"{rng.choice(_KEYWORD_PREFIXES)} {street} {house}, {psc3} {psc2} {obec}"
        placed = surface
    elif variant == "bare":
        surface = f"{street} {house}"
        placed = f"{rng.choice(_BARE_ANCHORS)} {surface}"
    else:
        surface = f"{street} {house}, {psc3}{_sp(rng)}{psc2} {obec}"
        placed = f"{rng.choice(_BARE_ANCHORS)} {surface}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=surface, type="ADRESA", auto_redact=True, should_flag=False)


def make_supisne_cislo(rng: random.Random) -> tuple[str, PiiSpec]:
    num = rng.randint(1, 999)
    variant = rng.choice(
        ("full", "sup_c", "s_c", "orient_full", "or_c", "combined")
    )
    if variant == "full":
        surface = f"súpisné číslo {num}"
    elif variant == "sup_c":
        surface = f"súp. č. {num}"
    elif variant == "s_c":
        surface = f"s. č. {num}"
    elif variant == "orient_full":
        surface = f"orientačné číslo {rng.randint(1, 40)}"
    elif variant == "or_c":
        surface = f"or. č. {rng.randint(1, 40)}"
    else:
        surface = f"súpisné/orientačné číslo {num}/{rng.randint(1, 40)}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return surface, PiiSpec(
        surface=surface, type="SUPISNE_CISLO", auto_redact=True, should_flag=False
    )


def make_cislo_bytu(rng: random.Random) -> tuple[str, PiiSpec]:
    num = rng.randint(1, 200)
    variant = rng.choice(("byt_c", "cislo_bytu", "b_c", "byt_cislo"))
    if variant == "byt_c":
        surface = f"byt č. {num}"
    elif variant == "cislo_bytu":
        surface = f"číslo bytu {num}"
    elif variant == "b_c":
        surface = f"b. č. {num}"
    else:
        surface = f"byt číslo {num}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return surface, PiiSpec(
        surface=surface, type="CISLO_BYTU", auto_redact=True, should_flag=False
    )


def make_vchod(rng: random.Random) -> tuple[str, PiiSpec]:
    variant = rng.choice(("number", "c_number", "letter", "colon_letter"))
    if variant == "number":
        surface = f"vchod {rng.randint(1, 12)}"
    elif variant == "c_number":
        surface = f"vchod č. {rng.randint(1, 12)}"
    elif variant == "letter":
        surface = f"Vchod {rng.choice('ABCD')}"
    else:
        surface = f"vchod: {rng.choice('ABCD')}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return surface, PiiSpec(surface=surface, type="VCHOD", auto_redact=True, should_flag=False)


def make_poschodie(rng: random.Random) -> tuple[str, PiiSpec]:
    variant = rng.choice(("prefix", "keyword", "keyword_colon", "prizemie", "na_locative"))
    if variant == "prefix":
        surface = f"{rng.randint(1, 9)}. poschodie"
    elif variant == "keyword":
        surface = f"poschodie {rng.randint(1, 9)}"
    elif variant == "keyword_colon":
        surface = f"poschodie: {rng.randint(1, 9)}"
    elif variant == "prizemie":
        surface = "prízemie"
    else:
        surface = f"na {rng.randint(1, 9)}. poschodí"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return surface, PiiSpec(
        surface=surface, type="POSCHODIE", auto_redact=True, should_flag=False
    )


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    """One of each of the six address-block types."""
    return [
        make_psc(rng),
        make_adresa(rng),
        make_supisne_cislo(rng),
        make_cislo_bytu(rng),
        make_vchod(rng),
        make_poschodie(rng),
    ]
