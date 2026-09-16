"""Known-entity EXPANSION (context.md §4.3, §5; CONTRACTS_v11.md §8, C1 round).

The lawyer types ``Ján Novák`` and ``Hlavná 12, 040 01 Košice`` into the known-entity box.
The document says ``Nováková``, ``J. Novák``, ``Jan Novak``, ``p. Novákovi``, ``Košiciach``.
``detect.declension.match_entity`` already closes the CASE gap (it stems both sides), but it
cannot close the ORTHOGRAPHIC one: a female surname is a different lexeme, an initial is a
different token, a diacritic-free spelling is a different string. These two pure functions
widen the typed list to cover those, BEFORE it reaches ``detect_known_entities``.

Pure functions, no Candidate emission, no I/O. Stemming is NEVER reimplemented here — every
stem comes from ``detect.declension.stem`` (the single stemmer, context.md §5).

THE DISCRIMINATOR is preserved by construction: this module only ever ADDS whole surface
forms and the stemmer's OWN output to the list. It never adds an adjectival ending to
``declension._SUFFIXES`` and never emits an adjectival derivation (``Kováčsky``,
``Kováčskej``) as a variant, so ``Kováčovej`` (possessive — the person) still matches while
``Kováčskej`` (occupational adjective — a different word) still does not.

Totality: both functions are called on whatever the user typed, including an empty box or a
pasted paragraph, so neither may raise. Junk in, short list out.

KNOWN HAZARD, reported to the orchestrator — ``match_entity`` matches PER TOKEN, so the
initial forms this function must generate (``J. Novák``) contribute a ONE-LETTER token to
the target stem set. For a name like ``Anna Nováková`` that token is ``A``, and the Slovak
conjunction ``a`` stems to the same thing: every ``a`` in the document would match. The fix
belongs where the tokens are consumed, not here (spec requires the initial forms): the
wiring round should drop single-character tokens in ``detect_known_entities``.
"""
from __future__ import annotations

import re
import unicodedata

from .declension import stem

NBSP = " "
_SEP = f"[ {NBSP}]"
_UP = "A-ZÁÄČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ"
_LO = "a-záäčďéíľĺňóôŕšťúýž"
_CAP = rf"[{_UP}][{_LO}]+"
_CAP_SEQ = rf"{_CAP}(?:{_SEP}{_CAP}){{0,2}}"

# Edge punctuation stripped off a typed token (honorific dots, quotes, brackets, dashes).
_EDGE = ".,;:!?()[]{}<>\"'/\\|*_-…„“”‚‘’«»–—"

# PSČ: three digits + two, optionally separated by a space or NBSP, never part of a longer
# digit run.
_PSC_RE = re.compile(rf"(?<!\d)\d{{3}}{_SEP}?\d{{2}}(?!\d)")


def _strip_diacritics(s: str) -> str:
    """Drop every combining mark (NFD) — ``Kováčová`` -> ``Kovacova``. This is NOT
    ``declension.fold_length`` (which folds vowel LENGTH only and deliberately keeps the
    mäkčeň): here the goal is the diacritic-free spelling a document is frequently typed
    in, which is a different job from stemming."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s) if not unicodedata.combining(ch)
    )


def _words(text: str) -> list[str]:
    """Whitespace-split (``\\s`` covers NBSP in a str pattern) with edge punctuation
    stripped; empty leftovers dropped."""
    return [w for w in (t.strip(_EDGE) for t in re.split(r"\s+", text.strip())) if w]


def _female_surname(surname: str) -> str | None:
    """The female form of a Slovak surname, or None when there is not one to make.

    ``Novák`` -> ``Nováková`` (the -ová suffix); ``Veselý`` -> ``Veselá`` (adjectival
    surnames take the adjectival feminine, not -ová — that is the "-á variant" case);
    ``Svoboda`` -> ``Svobodová``. An already-feminine surname is left alone, or the naive
    rule would produce ``Kováčováová``.
    """
    if len(surname) < 3:
        return None
    low = surname.casefold()
    if low.endswith("ová") or low.endswith("á") or low.endswith("a" + "́"):
        return None
    if low.endswith("ý"):
        return surname[:-1] + "á"
    if low.endswith("a"):
        return surname[:-1] + "ová"
    if low.endswith("o"):  # Hlaďo, Kováčiko -> Kováčiková
        return surname[:-1] + "ová"
    return surname + "ová"


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def expand_person(name: str) -> list[str]:
    """Every written form of a typed person name, input first, deduplicated.

    Generates: the female surname form, the declension stem of every constituent token,
    both initial forms (``J. Novák`` / ``Novák J.``), the diacritic-stripped spelling, and
    the ``p.`` / ``pán`` / ``pani`` prefixed forms. Total on junk input.
    """
    raw = name.strip()
    out: list[str] = [raw] if raw else []
    words = _words(raw)
    if not words:
        return _dedup(out)

    surname = words[-1]
    fem = _female_surname(surname)
    if fem is not None:
        out.append(fem)

    out.extend(stem(w) for w in words)
    out.append(_strip_diacritics(" ".join(words)))

    if len(words) >= 2:
        initial = words[0][0]
        out.append(f"{initial}. {surname}")
        out.append(f"{surname} {initial}.")

    for prefix in ("p.", "pán", "pani"):
        out.append(f"{prefix} {surname}")
    if fem is not None:
        out.append(f"pani {fem}")

    return _dedup(out)


def expand_address(address: str) -> list[str]:
    """Split a typed address into its separately-matchable parts, input first.

    Emits the full address, the street segment (``Hlavná 12``) and the bare street name
    (``Hlavná``), the PSČ exactly as typed (spaced, NBSP-separated or contiguous), and the
    obec. Each part is matched independently downstream because a document that writes the
    address across a table cell, a footer and a body sentence never repeats it whole.
    Total on junk input.
    """
    raw = address.strip()
    out: list[str] = [raw] if raw else []
    if not raw:
        return out

    segments = [s.strip() for s in raw.split(",") if s.strip()]

    if segments:
        street_seg = segments[0]
        out.append(street_seg)
        m = re.match(rf"^({_CAP_SEQ})", street_seg)
        if m:
            out.append(m.group(1))

    psc = _PSC_RE.search(raw)
    if psc is not None:
        out.append(psc.group())
        m = re.match(rf"^[,\s]*({_CAP_SEQ})", raw[psc.end() :])
        if m:
            out.append(m.group(1))
    elif len(segments) >= 2:
        # No PSČ typed: the obec is the trailing segment.
        m = re.match(rf"^({_CAP_SEQ})$", segments[-1])
        if m:
            out.append(m.group(1))

    return _dedup(out)
