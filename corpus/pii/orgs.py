"""Corpus PII generators for v1.1 round B3 (CONTRACTS_v11.md §9): the two types owned by
``detect/orgs.py`` — ORG (a company name, identified by its legal-form suffix) and
NAZOV_BANKY (the name of a bank or foreign-bank branch, Vyhláška MS SR 482/2011 clause (f)).

Each ``make_<type>(rng)`` returns ``(placed, PiiSpec)``. ``placed`` is the text a template
embeds in a document; ``PiiSpec.surface`` is the ground-truth redaction target.

Where the two differ and why:
* the legal-form-suffix form is SELF-IDENTIFYING (the suffix is the signal and is part of the
  name as written), so ``placed == surface`` and the suffix is INSIDE the ground truth;
* the field-label form carries the anchor in ``placed`` only — ``Obchodné meno:`` is a label,
  not PII, and ground truth that included it would fail the leak gate against a correct
  redactor (the same rule ``corpus/pii/names_anchored.py`` follows);
* the office form ("Advokátska kancelária Kováč") keeps the anchor INSIDE the surface,
  because there the anchor phrase is part of the organisation's name. This mirrors
  ``corpus/templates/_common.py``, which already seeds exactly that shape as an ORG.

EVERY VARIANT ``detect/orgs.py`` CLAIMS HAS A GENERATOR HERE (contract §9: a variant with no
generator is a variant with no end-to-end leak-gate proof) — all twelve legal-form suffixes,
the tight / spaced / no-final-dot / NBSP spellings of the dotted ones, the comma and NBSP
separators before the suffix, all three field labels, all four office anchors, the closed bank
list with and without a trailing legal-form suffix, the ``banka`` / ``banky`` anchored form
and the ``pobočka zahraničnej banky`` form.

ONE VARIANT IS DELIBERATELY NOT GENERATED: a LINE BREAK inside a multi-word suffix or bank
name. The detector must tolerate it (``detect/orgs.py`` writes every multi-word construct with
``\\s+``, the ``detect/office_refs.py::_AWS`` rule) but it is a RENDERING artefact — a PDF
wrapping a line — not something a document author writes. Authoring a newline into a ground
truth surface would put a string in the GT that no extractor returns verbatim, and the leak
gate would grep for text that is not there. The line-break variants are proved in
``tests/test_detect_orgs.py`` instead.

Ground-truth surfaces are all ≥3 characters: ``corpus/groundtruth.py`` now REJECTS anything
shorter, because a 2-character surface is not gradeable by substring search.

Neither type carries a checksum, so every occurrence is
``auto_redact=True, should_flag=False, checksum="n/a"``.
"""
from __future__ import annotations

import random

from corpus.groundtruth import PiiSpec

NBSP = " "

# Arbitrary company names — the name itself carries no signal; the legal-form suffix does.
_ORG_NAMES = (
    "Alfa Beta",
    "Stavby Východ",
    "Tatra Servis",
    "Gama Invest",
    "Delta Trade",
    "Omega Capital",
    "Zelená Krajina",
    "Pomoc Deťom",
    "Vodohospodárska Výstavba",
    "Slovenské Elektrárne",
    "Kováč a Partneri",
)

# The dotted legal-form abbreviations, as letter tuples so every spacing variant can be
# rendered from one source.
_DOTTED_SUFFIXES = ("sro", "as", "ks", "vos", "no", "oz", "jsa", "šp")
# The spelled-out ones. "spol. s r.o." is rendered separately because its middle word is a
# bare "s".
_WORD_SUFFIXES = (
    "akciová spoločnosť",
    "štátny podnik",
    "družstvo",
    "spoločnosť s ručením obmedzeným",
)

_ORG_LABELS = ("Obchodné meno:", "Obchodná firma:", "Názov spoločnosti:")
_OFFICE_ANCHORS = (
    "Advokátska kancelária",
    "Notársky úrad",
    "Exekútorský úrad",
    "Znalecký ústav",
)
_OFFICE_NAMES = ("Kováč", "Novák", "Horváth", "Šimko a Partneri")

# The closed list of banks / foreign-bank branches, mirroring detect/orgs.py::_BANKS. Kept as
# a corpus-side copy on purpose: a generator that imported the detector's own list would prove
# only that the module agrees with itself.
_BANKS = (
    "Slovenská sporiteľňa",
    "Všeobecná úverová banka",
    "VÚB banka",
    "Tatra banka",
    "Československá obchodná banka",
    "ČSOB",
    "Poštová banka",
    "Prima banka",
    "365.bank",
    "mBank",
    "UniCredit Bank",
    "Raiffeisen",
    "OTP Banka",
    "Fio banka",
    "J&T Banka",
    "Oberbank",
    "Citibank",
    "ING Bank",
    "Komerční banka",
    "Privatbanka",
)
# Banks NOT on the closed list — these exist to exercise the ``banka`` / ``banky`` anchored
# path, which is what covers a bank the list has not heard of.
_UNLISTED_BANKS = ("Považská", "Gemerská", "Hornonitrianska", "Podtatranská")
_BANK_WORDS = ("banka", "banky", "banke")


def _sp(rng: random.Random) -> str:
    """A normal space or an NBSP — Slovak typography writes both, and a PDF text layer
    produces NBSPs constantly."""
    return NBSP if rng.random() < 0.5 else " "


def _dotted(rng: random.Random, letters: str) -> str:
    """One dotted abbreviation in one of its four real spellings: ``s.r.o.`` (tight),
    ``s. r. o.`` (spaced), ``s.r.o`` (no final dot), ``s. r. o.`` (NBSP)."""
    style = rng.choice(("tight", "spaced", "nodot", "nbsp"))
    if style == "tight":
        return ".".join(letters) + "."
    if style == "spaced":
        return ". ".join(letters) + "."
    if style == "nodot":
        return ".".join(letters)
    return f".{NBSP}".join(letters) + "."


def _legal_form(rng: random.Random) -> str:
    kind = rng.choice(("dotted", "word", "spol"))
    if kind == "dotted":
        return _dotted(rng, rng.choice(_DOTTED_SUFFIXES))
    if kind == "word":
        return rng.choice(_WORD_SUFFIXES)
    return f"spol.{_sp(rng)}s{_sp(rng)}{_dotted(rng, 'ro')}"


def _suffix_sep(rng: random.Random) -> str:
    """The separator between the company name and its legal form: a space, an NBSP, or a
    comma plus either ("Alfa Beta, s. r. o." is ordinary Slovak typography)."""
    return rng.choice((" ", NBSP, f",{_sp(rng)}"))


def _company(rng: random.Random) -> str:
    return f"{rng.choice(_ORG_NAMES)}{_suffix_sep(rng)}{_legal_form(rng)}"


# ---------------------------------------------------------------------------------- ORG
def make_org(rng: random.Random) -> tuple[str, PiiSpec]:
    """One ORG occurrence in one of the three forms the detector claims.

    * ``suffix`` — the self-identifying legal-form suffix; the surface IS the placed text.
    * ``label``  — ``Obchodné meno: <value>``; the label is in ``placed`` only.
    * ``office`` — ``Advokátska kancelária Kováč``; the anchor is part of the NAME, so it is
      inside the surface. This is the shape ``corpus/templates/_common.py`` already seeds.
    """
    form = rng.choice(("suffix", "suffix", "label", "office"))
    if form == "label":
        value = _company(rng) if rng.random() < 0.5 else rng.choice(_ORG_NAMES)
        placed = f"{rng.choice(_ORG_LABELS)}{_sp(rng)}{value}"
        surface = value
    elif form == "office":
        surface = f"{rng.choice(_OFFICE_ANCHORS)} {rng.choice(_OFFICE_NAMES)}"
        placed = surface
    else:
        surface = _company(rng)
        placed = surface
    return placed, PiiSpec(
        surface=surface, type="ORG", auto_redact=True, should_flag=False, checksum="n/a"
    )


# -------------------------------------------------------------------------- NAZOV_BANKY
def make_nazov_banky(rng: random.Random) -> tuple[str, PiiSpec]:
    """One NAZOV_BANKY occurrence in one of the three forms the detector claims.

    * ``listed``   — a bank from the closed list, with or without a trailing legal form.
    * ``anchored`` — a bank NOT on the list, reached through the ``banka`` / ``banky``
      anchor; the anchor word is part of the name ("Považská banka"), so it is in the
      surface.
    * ``pobocka``  — a foreign-bank branch, ``<name>, pobočka zahraničnej banky``. The
      generic phrase is NOT in the surface: the detector claims the capitalised run, and the
      phrase itself names no institution.
    """
    form = rng.choice(("listed", "listed", "anchored", "pobocka"))
    if form == "anchored":
        surface = f"{rng.choice(_UNLISTED_BANKS)}{_sp(rng)}{rng.choice(_BANK_WORDS)}"
        placed = surface
    elif form == "pobocka":
        surface = rng.choice(_BANKS)
        placed = f"{surface},{_sp(rng)}pobočka zahraničnej banky"
    else:
        surface = rng.choice(_BANKS)
        placed = (
            f"{surface}{_suffix_sep(rng)}{_dotted(rng, 'as')}"
            if rng.random() < 0.5
            else surface
        )
    return placed, PiiSpec(
        surface=surface,
        type="NAZOV_BANKY",
        auto_redact=True,
        should_flag=False,
        checksum="n/a",
    )


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    """One of each generator. The per-call ``rng.choice`` over forms and spellings is what
    spreads every claimed variant across a generated corpus."""
    return [
        make_org(rng),
        make_nazov_banky(rng),
    ]
