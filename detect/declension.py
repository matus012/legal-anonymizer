"""Slovak declension-matching engine (context.md §5) as a PURE unit.

The single most important correctness component in the project. Slovak inflects proper
nouns heavily (Novak -> Novaka, Novakovi, Novakovcov, Novakova, Novakovej; Kosice ->
Kosic, Kosiciam), so a literal string match misses the majority of a name's occurrences
in a real legal document -- a tool that "looks like it works while leaking names".

Governing rule: RECALL over precision. A false positive costs a reviewer two seconds; a
false negative is a data breach. Everything ambiguous resolves toward over-detection
(context.md §6). The ONE hard precision line is the discriminator: a possessive declension
of a surname (``Kovacovej``) IS the person and must match; the occupational/demonym
ADJECTIVE built from the same surname (``Kovacskej``) is a different word and must not.
The mechanism: the case ending strips to leave the bare stem for the possessive, while the
-sk-/-ck-/-v- derivational infix survives on the adjective, so the two stems differ.

Pure unit: text-in, spans-out. No file I/O, no docx/pdf, no ground truth. This module MUST
NOT import corpus/ or eval/ -- the closed suffix inventory below is reimplemented straight
from Slovak grammar, not read from any table.

Design notes
------------
* ``fold_length`` folds vowel LENGTH only. The rhythmic law shortens long vowels in oblique
  cases (Kosice -> Kosic), so folding length lets the stems meet. Folding the makcen/hacek
  consonants (c s z d t n l) or ae/o would instead collapse distinct letters and cause mass
  over-match, so those are preserved.
* The suffix inventory is CLOSED and contains only nominal case endings (masc/fem personal
  + place, incl. family plural, the -ov toponym class, and the -ovce toponym class). It
  deliberately excludes every adjectival/derivational ending (-sky -ska -skej -cky -cka -vy
  -vej -ik -ika) -- that exclusion is exactly what makes the discriminator work. All endings
  are pure ASCII because they are matched AFTER length-folding.
* Stem floor: stripping never leaves fewer than 3 characters, so short names stay whole.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- fold_length
# Fold Slovak vowel LENGTH only. Long vowels -> their short counterparts; the syllabic
# long consonants l-acute / r-acute -> plain l / r. Everything else -- including the
# makcen/hacek consonants and ae (a-umlaut) / o (o-circumflex), which are NOT length marks
# -- is preserved untouched.
_LENGTH_MAP = str.maketrans(
    {
        "á": "a",  # a-acute
        "é": "e",  # e-acute
        "í": "i",  # i-acute
        "ó": "o",  # o-acute
        "ú": "u",  # u-acute
        "ý": "y",  # y-acute
        "ĺ": "l",  # l-acute
        "ŕ": "r",  # r-acute
    }
)


def fold_length(s: str) -> str:
    return s.translate(_LENGTH_MAP)


# ------------------------------------------------------------------------------- stem
# CLOSED inventory of Slovak nominal case endings, expressed on the length-folded string.
# Grouped by the declension class each ending serves; every entry is a genuine case ending,
# never an adjectival/derivational one.
_SUFFIXES: frozenset[str] = frozenset(
    {
        # bare stem-vowel endings (masc/fem hard stems, place nouns)
        "a", "e", "i", "o", "u", "y",
        # short consonantal endings
        "om",  # masc instrumental (Novakom, Zvolenom)
        "ou",  # fem/place instrumental (Bratislavou, Levocou)
        "ov",  # -ov toponym stem marker (Presov, Ruzinov)
        # masc animate + fem personal endings (the -ov- possessive block)
        "ovi",   # masc dat/loc (Novakovi)
        "ova",   # fem nom  (Novakova) / -ov toponym gen (Presova)
        "ovu",   # fem acc  (Novakovu)
        "ove",   # -ov toponym loc (Presove, Ruzinove)
        "ovej",  # fem gen/dat/loc (Novakovej)
        "ovou",  # fem instrumental (Novakovou)
        "ovom",  # -ov toponym instrumental (Presovom, Ruzinovom)
        # family plural (surnames): Novakovci / Novakovcov
        "ovci",
        "ovcov",
        # -e/-ice place plural (Kosice class): Kosiciam, Kosiciach, Kosicami
        "iam", "iach", "ami",
        # -ovce toponym class (Michalovce): Michaloviec, Michalovciam, ...
        "ovce", "oviec", "ovciam", "ovciach", "ovcami",
    }
)

# Longest-first: an oblique ending must win over any shorter tail it contains, e.g. strip
# "ovej" from "novakovej" (-> novak) rather than the trailing "j"/"ej"; strip "ova" from
# "novakova" (-> novak) rather than "a" (-> novakov).
_SUFFIXES_BY_LEN: tuple[str, ...] = tuple(
    sorted(_SUFFIXES, key=len, reverse=True)
)

_STEM_FLOOR = 3


def stem(word: str) -> str:
    """casefold -> fold_length -> strip the longest matching case ending (floor-guarded)."""
    w = fold_length(word.casefold())
    for suf in _SUFFIXES_BY_LEN:
        if w.endswith(suf) and len(w) - len(suf) >= _STEM_FLOOR:
            return w[: len(w) - len(suf)]
    return w


# ---------------------------------------------------------------------------- match_entity
# Punctuation stripped from token edges (honorific dots, brackets, quotes, dashes, slashes).
# Written with \u escapes so the source stays ASCII-clean (no mojibake literals).
_EDGE_PUNCT = (
    ".,;:!?()[]{}<>\"'/\\|*_-"
    "…"                      # ellipsis
    "„“”"          # low/left/right double quotes
    "‚‘’"          # low/left/right single quotes
    "«»‹›"    # guillemets
    "–—−"          # en/em dash, minus
    "·§"                # middle dot, section sign
)

# A token is a maximal run of non-whitespace. \s already covers U+00A0 in a Unicode (str)
# pattern, but it is named explicitly per the spec so the NBSP split is unmistakable.
_TOKEN_RE = re.compile(r"[^\s ]+")


def _tokens(text: str):
    """Yield (core, start, end) for each whitespace-delimited token with edge punctuation
    stripped, offsets tracked against the ORIGINAL string."""
    for m in _TOKEN_RE.finditer(text):
        raw = m.group()
        lead = len(raw) - len(raw.lstrip(_EDGE_PUNCT))
        core = raw[lead:].rstrip(_EDGE_PUNCT)
        if not core:
            continue
        start = m.start() + lead
        yield core, start, start + len(core)


def _entity_stems(entity: str) -> set[str]:
    return {stem(core) for core, _s, _e in _tokens(entity)}


def match_entity(text: str, entity: str) -> list[tuple[int, int]]:
    """Emit a (start, end) char span for every ``text`` token whose stem equals the stem of
    any constituent word of ``entity``. Case-insensitive and diacritic(length)-aware via
    ``stem``. Per-token spans; adjacent-span merging is a downstream (writer) concern."""
    targets = _entity_stems(entity)
    targets.discard("")
    if not targets:
        return []
    return [
        (start, end)
        for core, start, end in _tokens(text)
        if stem(core) in targets
    ]
