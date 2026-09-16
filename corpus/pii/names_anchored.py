"""Anchored-name PII surfaces (CONTRACTS_v11.md §9, C1 round): the four anchors
``detect/name_anchors.py`` claims — title, role, field-label, bare-name.

Each ``make_*`` returns ``(placed, PiiSpec)``. ``placed`` is the text a template embeds in
a document (it CARRIES the anchor: the title, the role word, the label, or the surrounding
sentence); ``PiiSpec.surface`` is the ground-truth redaction target, which is the anchored
VALUE ONLY — the detector never puts the anchor inside the span, because a title, a role
word and a field label are not PII and redacting them destroys readable text for no privacy
gain. Ground truth that included the anchor would fail the leak gate against a correct
redactor.

Every variant the detector claims has a generator here, drawn by ``rng.choice`` so a
generated corpus exercises all of them (contract §9: a variant with no generator is a
variant with no end-to-end leak-gate proof) — all sixteen titles plus the stacked and
trailing forms, all twenty-four role words in nominative AND oblique form with each
connector, and all ten field labels with their four value types.

Buckets follow the detector: the three anchored generators are AUTO (``auto_redact=True``,
``should_flag=False``); the bare-name generator is the REVIEW bucket
(``auto_redact=False``, ``should_flag=True``) — the one v1.1 class that still exercises
``FLAG_SURVIVAL_MIN`` after the A1 change (contract §7).

``STATNA_PRISLUSNOST`` is emitted by ``make_field_statna_prislusnost``; it must be present
in ``detect/core.py``'s ``_TYPE_PRECEDENCE`` before the integration round wires either side
in, or detect()'s post-condition 4 rejects it.

``PiiSpec`` does not yet carry a ``checksum`` field (CONTRACTS_v11.md §7 adds it in a later
round) — every ``make_*`` below carries the TODO marker instead of passing the kwarg. None
of these types has a checksum, so the value will be ``"n/a"`` for all of them.
"""
from __future__ import annotations

import random

from corpus.groundtruth import PiiSpec

NBSP = " "

_FIRST = ("Ján", "Peter", "Mária", "Eva", "Jozef", "Milan", "Zuzana", "Lukáš")
_LAST = ("Novák", "Kováč", "Horák", "Malý", "Sedlák", "Šimko", "Baláž", "Krajčí")

# All sixteen titles the detector anchors on, including the two-part "Ing. arch.".
_TITLES = (
    "JUDr.", "Ing.", "Ing. arch.", "Mgr.", "Bc.", "MUDr.", "PhDr.", "RNDr.",
    "Dr.", "prof.", "doc.", "PaedDr.", "ThDr.", "MVDr.", "PhD.", "CSc.",
)
_STACKED = ("JUDr. Ing.", "prof. JUDr.", "doc. Ing. arch.", "Mgr. PhDr.")
_TRAILING = ("PhD.", "CSc.")

# Every role word, nominative AND one oblique form each — the detector matches the role
# stem plus a short ending, so a corpus that only ever seeded nominatives would prove
# nothing about the inflected occurrences that dominate real documents.
_ROLES = (
    "predávajúci", "predávajúceho", "kupujúci", "kupujúcim", "žalobca", "žalobcu",
    "žalovaný", "žalovaného", "navrhovateľ", "navrhovateľa", "odporca", "odporcu",
    "splnomocniteľ", "splnomocniteľa", "splnomocnenec", "splnomocnenca",
    "konateľ", "konateľa", "veriteľ", "veriteľa", "dlžník", "dlžníka",
    "nájomca", "nájomcu", "prenajímateľ", "prenajímateľa", "dedič", "dediča",
    "poručiteľ", "poručiteľa", "darca", "darcu", "obdarovaný", "obdarovaného",
    "záložca", "záložcu", "záložný veriteľ", "záložného veriteľa",
    "oprávnený", "oprávneného", "povinný", "povinného", "účastník", "účastníka",
    "svedok", "svedka", "zástupca", "zástupcu",
)
_CONNECTORS = ("", ":", " v zastúpení", ", v zastúpení")

_MENO_LABELS = ("Meno a priezvisko:", "Meno:", "Priezvisko:", "Zastúpený:")
_ADRESA_LABELS = ("Trvale bytom:", "Bydlisko:", "Adresa:", "Sídlo:")
_ORGS = ("Alfa Beta s.r.o.", "Stavby Východ a.s.", "Tatra Servis spol. s r.o.")
_STREETS = ("Hlavná", "Štúrova", "Slovenská", "Nová", "Košická")
_OBCE = ("Košice", "Žilina", "Prešov", "Poprad", "Bratislava")
_PSC = ("040 01", "811 09", "917 01", "058 01")
_STATY = ("slovenská", "SR", "česká", "Slovenská republika")

# Sentence frames whose lead-in guarantees the bare name is NOT sentence-initial (the
# heuristic deliberately refuses the first token of a sentence).
_BARE_FRAMES = (
    "Dňa uvedeného sa dostavil {name} a preukázal totožnosť.",
    "K veci sa vyjadril {name} osobne pred notárom.",
    "Ako prítomný bol zapísaný {name} podľa prezenčnej listiny.",
)


def _sp(rng: random.Random) -> str:
    return NBSP if rng.random() < 0.5 else " "


def _name(rng: random.Random) -> str:
    """One or two given names plus a surname, separated by a normal space or an NBSP."""
    first = rng.choice(_FIRST)
    last = rng.choice(_LAST)
    if rng.random() < 0.25:
        return f"{first}{_sp(rng)}{rng.choice(_FIRST)}{_sp(rng)}{last}"
    return f"{first}{_sp(rng)}{last}"


def make_title_name(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 1 — a title-anchored name: single, stacked, or trailing degree.

    The title is NEVER part of the ground-truth surface: it is not PII, and a redactor
    that swallowed it would be destroying text the reviewer needs.
    """
    name = _name(rng)
    variant = rng.choice(("single", "stacked", "trailing"))
    if variant == "single":
        placed = f"{rng.choice(_TITLES)}{_sp(rng)}{name}"
    elif variant == "stacked":
        placed = f"{rng.choice(_STACKED)}{_sp(rng)}{name}"
    else:
        # The lead-in is lowercase on purpose: a Capitalized lead-in word would be
        # swallowed into the name run by the trailing-title pattern, and the ground-truth
        # surface would then be narrower than what the detector emits.
        placed = f"zmluvu podpísal {name}, {rng.choice(_TRAILING)}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=name, type="MENO", auto_redact=True, should_flag=False)


def make_role_name(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 2 — a role-anchored name, nominative or oblique, with any connector.

    The role word is context, not PII, so it stays outside the ground-truth surface.
    """
    name = _name(rng)
    placed = f"{rng.choice(_ROLES)}{rng.choice(_CONNECTORS)}{_sp(rng)}{name}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=name, type="MENO", auto_redact=True, should_flag=False)


def make_field_meno(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 3, MENO labels — ``Meno a priezvisko:`` / ``Meno:`` / ``Priezvisko:`` /
    ``Zastúpený:``. The value runs to the end of the line; the label is not part of it."""
    label = rng.choice(_MENO_LABELS)
    value = rng.choice(_LAST) if label == "Priezvisko:" else (
        rng.choice(_FIRST) if label == "Meno:" else _name(rng)
    )
    placed = f"{label}{_sp(rng)}{value}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=value, type="MENO", auto_redact=True, should_flag=False)


def make_field_adresa(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 3, ADRESA labels — ``Trvale bytom:`` / ``Bydlisko:`` / ``Adresa:`` /
    ``Sídlo:``. Typed ADRESA, not MENO: mis-typing it would file an address under a
    person's label prefix in the report."""
    value = (
        f"{rng.choice(_STREETS)} {rng.randint(1, 199)}, "
        f"{rng.choice(_PSC)} {rng.choice(_OBCE)}"
    )
    placed = f"{rng.choice(_ADRESA_LABELS)}{_sp(rng)}{value}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=value, type="ADRESA", auto_redact=True, should_flag=False)


def make_field_org(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 3, ORG label — ``Obchodné meno:``."""
    value = rng.choice(_ORGS)
    placed = f"Obchodné meno:{_sp(rng)}{value}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=value, type="ORG", auto_redact=True, should_flag=False)


def make_field_statna_prislusnost(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 3, STATNA_PRISLUSNOST label — ``Štátna príslušnosť:``.

    This type is NOT in the frozen §4 registry of the original contract freeze; it must be
    registered before detect() may emit it (post-condition 4).
    """
    value = rng.choice(_STATY)
    placed = f"Štátna príslušnosť:{_sp(rng)}{value}"
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(
        surface=value, type="STATNA_PRISLUSNOST", auto_redact=True, should_flag=False
    )


def make_bare_name(rng: random.Random) -> tuple[str, PiiSpec]:
    """Anchor 4 — an UNANCHORED name in a sentence, the review bucket.

    ``auto_redact=False, should_flag=True``: the heuristic is a guess, so it arrives
    unticked and the reviewer decides. This is the class that keeps ``FLAG_SURVIVAL_MIN``
    non-vacuous after the A1 change moved every checksum-invalid identifier into the auto
    class (contract §7). The frame's lead-in keeps the name off a sentence boundary, which
    the heuristic refuses by design.
    """
    name = _name(rng)
    placed = rng.choice(_BARE_FRAMES).format(name=name)
    # TODO(v1.1): checksum="n/a" once PiiSpec carries the field
    return placed, PiiSpec(surface=name, type="MENO", auto_redact=False, should_flag=True)


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    """One of each anchored-name generator."""
    return [
        make_title_name(rng),
        make_role_name(rng),
        make_field_meno(rng),
        make_field_adresa(rng),
        make_field_org(rng),
        make_field_statna_prislusnost(rng),
        make_bare_name(rng),
    ]
