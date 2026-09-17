"""v1.1 NORMALIZATION LAYER WITH AN OFFSET MAP (CONTRACTS_v11.md Amendment 9).

Every detector in ``detect/`` runs over a NORMALIZED copy of the document text; every
candidate it produces is then cut on ORIGINAL offsets. This module is the one place that
knows how to do both.

--------------------------------------------------------------------------------------
WHY THIS EXISTS AND WHY IT IS NOT JUST ANOTHER str.replace
--------------------------------------------------------------------------------------
v1.1 already normalized ONE character: U+00A0 NBSP became an ordinary space in
``detect.core.detect``. That trick was safe for exactly one reason -- it is 1 character for
1 character, so EVERY OFFSET IS PRESERVED and the candidates' start/end still index the
original string, which is what both writers slice by.

The mutation gate (``eval/mutation_gate.py``) then measured what the same pipeline does to
characters that are NOT 1:1, and the answer was the worst numbers in the project:

    zero_width   0.070      soft_hyphen  0.070      line_break_mid 0.119
    cyrillic     0.356      nfd          0.675

A zero-width space DELETED from the text shifts every later offset, so the NBSP trick cannot
be extended to it -- a redaction cut at a shifted offset does not merely mislabel the
document, it CORRUPTS it, removing the wrong characters. That is why these five classes sat
open while NBSP was closed in one line: not because they are rarer or less dangerous, but
because fixing them requires an offset MAP rather than an offset-preserving substitution.

None of these are exotic. U+00AD is Word's own optional hyphen and PyMuPDF renders a PDF
hyphen as one. Bank portals inject U+200B into long account numbers and a lawyer pastes the
number straight into a filing. macOS hands back NFD, so a .docx round-tripped on a Mac has
"c"+U+030C where the regex expects U+010D. A PDF text layer wraps every page, so a line
break lands inside an anchor phrase on every document. THE PIPELINE MEETS THESE TODAY.

--------------------------------------------------------------------------------------
THE CONTRACT
--------------------------------------------------------------------------------------
``normalize(text) -> Normalized(text=norm, starts=..., ends=...)`` where, for every index
``i`` into ``norm``:

    starts[i]  = index into the ORIGINAL text where the source of norm[i] begins
    ends[i]    = index into the ORIGINAL text one past where the source of norm[i] ends

A detector match on ``norm[a:b]`` therefore maps back to the original slice
``text[starts[a] : ends[b - 1]]``, which is what ``span()`` returns. The map is built so
that this slice always COVERS every original character that contributed to the match --
including the invisible ones deleted on the way in. A zero-width space sitting inside an
IBAN is therefore inside the redacted span and is destroyed with it, which is the only
correct answer: leaving it behind would leave a fragment of the original token in the file.

INVARIANTS (asserted in tests/test_normalize.py, property-tested in
tests/test_normalize_property.py):
  * ``len(starts) == len(ends) == len(norm)``
  * ``starts`` is non-decreasing; ``ends`` is non-decreasing; ``starts[i] < ends[i]``
  * the map is MONOTONE, so two non-overlapping norm spans map to two non-overlapping
    original spans -- the property ``detect()``'s post-conditions depend on
  * ``normalize(t).text`` is idempotent: normalizing it again changes nothing

--------------------------------------------------------------------------------------
WHAT IS NORMALIZED, AND WHAT DELIBERATELY IS NOT
--------------------------------------------------------------------------------------
DONE HERE:
  1. FORMAT CHARACTERS (Unicode category Cf) are DELETED. That is one rule covering
     U+200B/C/D, U+FEFF, U+00AD, U+2060, and the bidi marks U+200E/U+200F -- rather than a
     hand-kept list that the next attack is not on.
  2. HOMOGLYPHS: Cyrillic and Greek lookalikes fold to their Latin twin, 1:1.
  3. WHITESPACE: every run of whitespace collapses to ONE character -- a single space, or a
     single '\n' when the run contained a line break. So one tab, one NBSP, five spaces and a
     CRLF all arrive at a detector in exactly one of two spellings.
  4. COMPATIBILITY FORMS: per-character NFKC, which folds fullwidth digits, superscript
     digits, ligatures and the like onto their plain forms.
  5. NFD -> NFC: a combining mark that composes with the preceding character is composed
     into it, so "c"+U+030C becomes U+010D and the existing regexes match it.

DELIBERATELY NOT DONE HERE:
  * CASE IS NOT FOLDED. Several detectors use CAPITALISATION AS EVIDENCE -- ``detect/orgs.py``
    keys on capitalized tokens next to a legal-form suffix, and the bare-name heuristic in
    ``detect/name_anchors.py`` does the same. Case-folding the text globally would not make
    those detectors case-insensitive, it would DESTROY their only signal and turn every
    capitalized-token rule into a match-everything rule. The all_caps / lowercase mutation
    classes are fixed instead by making each ANCHOR pattern case-insensitive at its own site,
    where the distinction between "an anchor word" and "evidence" is visible. Recorded in
    QUESTIONS.md as Q11.
  * DIACRITICS ARE NOT STRIPPED. Folding "č" to "c" here would require every pattern in
    ``detect/`` that spells a Slovak word to be rewritten, and would silently widen every one
    of them. The no_diacritics class is handled per detector, by folding the ANCHOR TEST (the
    pattern ``detect/datetime_amounts.py`` already uses for its birth anchors), never the
    surface.

THE LINE BOUNDARY SURVIVES, AND THAT IS THE ONE THING THIS MODULE REFUSES TO DECIDE.
Collapsing a line break to a space was tried first, on the reasoning that a wrapped PDF text
layer puts a break inside an anchor phrase on every page and that recall beats precision
(context.md 6). It broke two detectors at once, in opposite directions:

  * detect/name_anchors.py pairs Capitalized tokens separated by HORIZONTAL whitespace into a
    first-name/surname guess. With wraps turned into spaces, the last word of one line and the
    first word of the next became a name: measured on a two-line fixture it emitted the
    auto=True MENO surface "Novak\nRodne" -- a party's surname welded to the label beginning
    the following line, which would have been redacted along with it. An over-redaction that
    eats the document around it is not a free recall win.
  * the same module's field-label pattern uses [\n\r\t] as the TERMINATOR of a label's value.
    With no line breaks left in the text it had no terminator, and a label value ran on to the
    end of the page.

So normalization makes the SPELLING of whitespace uniform and stops there. Whether a detector
may see through a line break stays that detector's decision, spelled \s where a value should
tolerate a wrap and [^\S\n\r] where a word-level heuristic must not cross one. The narrow
case that genuinely needs the break GONE -- a renderer breaking one long identifier across two
lines -- is handled by a SECOND view (join_wrapped=True) whose candidates are MERGED with the
first view's, so the plain reading is never lost. See _is_identifier_run.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------- homoglyphs
# Cyrillic and Greek characters that are VISUALLY IDENTICAL (or near enough that no reviewer
# will ever spot the difference) to a Latin letter, mapped to that letter. Every entry is
# 1 character for 1 character.
#
# Only true confusables are listed, and -- see _fold_indices below -- they are folded ONLY
# INSIDE A TOKEN THAT IS ALREADY PARTLY LATIN.
#
# The list alone was not enough, and this comment used to claim it was. Folding per character
# and unconditionally turns a genuinely Cyrillic word into mixed-script wreckage:
# "Ковальчук" came out as "Koвaльчyк", matching nothing and readable as neither language.
# Slovakia has handled Ukrainian clients by the thousand since 2022, so a filing carrying a
# name in Cyrillic is ordinary, and the consequence was a LEAK -- the lawyer typed the party's
# name into the known-entities box exactly as the document spelled it, and it did not match,
# because the document text had been mangled underneath it. Found by red-team round 3 (A10),
# which read this comment and checked whether the code did what it said.
#
# The attack this defends against is a Latin word with a Cyrillic letter SMUGGLED INTO IT.
# That attack requires the rest of the token to be Latin, which is exactly the test now
# applied -- so the defence is unchanged and the collateral damage is gone.
_HOMOGLYPH_PAIRS = (
    # Cyrillic lowercase -> Latin
    ("а", "a"), ("е", "e"), ("о", "o"), ("р", "p"), ("с", "c"), ("у", "y"), ("х", "x"),
    ("і", "i"), ("ј", "j"), ("ѕ", "s"), ("һ", "h"), ("ԁ", "d"), ("ԛ", "q"), ("ԝ", "w"),
    ("ӏ", "l"), ("ν", "v"),
    # Cyrillic uppercase -> Latin
    ("А", "A"), ("В", "B"), ("Е", "E"), ("К", "K"), ("М", "M"), ("Н", "H"), ("О", "O"),
    ("Р", "P"), ("С", "C"), ("Т", "T"), ("У", "Y"), ("Х", "X"), ("І", "I"), ("Ј", "J"),
    ("Ѕ", "S"), ("Ԍ", "G"),
    # Greek lowercase -> Latin
    ("α", "a"), ("ο", "o"), ("ρ", "p"), ("κ", "k"), ("χ", "x"), ("ι", "i"), ("υ", "u"),
    # Greek uppercase -> Latin
    ("Α", "A"), ("Β", "B"), ("Ε", "E"), ("Ζ", "Z"), ("Η", "H"), ("Ι", "I"), ("Κ", "K"),
    ("Μ", "M"), ("Ν", "N"), ("Ο", "O"), ("Ρ", "P"), ("Τ", "T"), ("Υ", "Y"), ("Χ", "X"),
)
_HOMOGLYPHS = {ord(src): dst for src, dst in _HOMOGLYPH_PAIRS}

# Hyphen-like punctuation that means ASCII '-'. See the module docstring on nb_hyphen: Word's
# Ctrl+Shift+hyphen is U+2011, and per-character NFKC folds it to U+2010, not to '-'.
# Unconditional, unlike the script confusables -- a dash is punctuation, so there is no
# "genuinely Cyrillic" case to protect. 1:1, so offsets are untouched. The en and em dashes are
# deliberately absent: they are range punctuation in ordinary prose, not hyphens.
_HYPHENS = {
    0x2010: "-",   # HYPHEN
    0x2011: "-",   # NON-BREAKING HYPHEN
    0x2012: "-",   # FIGURE DASH
    0x2043: "-",   # HYPHEN BULLET
    0x2212: "-",   # MINUS SIGN
    0xFE63: "-",   # SMALL HYPHEN-MINUS
    0xFF0D: "-",   # FULLWIDTH HYPHEN-MINUS
}


# A character is "interesting" when normalization might change it. The fast path below
# returns the input untouched when none is present, which is the common case for a short
# DOCX paragraph. The class is deliberately WIDER than the transformations -- a false
# "interesting" costs one pass over the string, a false "boring" would skip a needed fix.
_INTERESTING_RE = re.compile(
    r"[\t\n\r]"                       # non-space whitespace
    r"|\s\s"                          # a whitespace RUN (double space, space+nbsp, ...)
    r"|[^\x20-\x7eÀ-ſ]"     # anything outside ASCII-printable + Latin-1/Ext-A
)

# A maximal run of whitespace, and the test for whether one crossed a line.
_WS_RUN_RE = re.compile(r"\s+")
_LINEBREAK_RE = re.compile(r"[\n\r\u2028\u2029]")


@dataclass(frozen=True)
class Normalized:
    """Normalized text plus the two arrays that map it back to the original.

    ``starts``/``ends`` are indexed by position in ``text`` (the NORMALIZED string) and hold
    indices into the ORIGINAL string. ``original`` is kept so ``span()`` can slice it without
    the caller having to carry it separately and risk pairing a map with the wrong text.
    """

    text: str
    original: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    @property
    def unchanged(self) -> bool:
        return self.text is self.original

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open span in the normalized text to a half-open span in the original.

        The returned span COVERS every original character that produced ``text[start:end]``,
        including format characters that were deleted inside it. An empty normalized span
        cannot be mapped meaningfully and is rejected -- ``detect()`` never produces one, and
        an empty span reaching a writer would be a silent no-op redaction.
        """
        if end <= start:
            raise ValueError(f"empty normalized span [{start}, {end})")
        if self.unchanged:
            return start, end
        return self.starts[start], self.ends[end - 1]

    def surface(self, start: int, end: int) -> str:
        """The ORIGINAL characters behind a normalized span, exactly as the document holds
        them. This is what the report shows and what ``writer/pdf_body.py`` searches for, so
        it must be the document's real bytes -- never the normalized stand-ins."""
        a, b = self.span(start, end)
        return self.original[a:b]


def _wrapped_run_indices(text: str) -> set[int]:
    """Delete a whitespace run that CONTAINS A LINE BREAK and is flanked by alphanumerics.

    This is the pre-pass behind ``detect()``'s SECOND normalized view. It exists for one
    shape, and only that shape: a renderer breaking a long unbreakable token across a line.
    ``FYCWSKZC`` arrives from a wrapped PDF text layer as ``FYC\\nWSKZC``, and no amount of
    separator-widening inside a regex helps, because the two halves are not separated — the
    token is CUT. Collapsing the run to a single space (what ``normalize`` does) turns the cut
    into ``FYC WSKZC``, which is still not a BIC.

    WHY THIS IS A SEPARATE VIEW RATHER THAN PART OF normalize()
    ``normalize`` is lossless in the sense that matters: it folds characters that are
    equivalent to what the document means. Deleting a separator is NOT that — it asserts that
    two tokens are one token, which is a GUESS. So it is run as an ADDITIONAL pass whose
    candidates are merged with the base pass's, never as a replacement: the base reading is
    always still available, and the joined reading can only ADD detections. Recall over
    precision (context.md §6), with the base pass as the floor rather than the ceiling.

    WHY ONLY A LINE BREAK, AND NOT EVERY WHITESPACE
    Because only a line break carries the evidence. A renderer wraps; a human types a space.
    ``4712 3456`` and ``2020 2021`` are the same shape, and there is nothing in either to say
    which is one number and which is two — joining on a plain space would make ``\\d{8}``
    match "v rokoch 2020 2021" and auto-redact a date range out of every contract that
    mentions one. (This project has already had to fix "Strana 3 z 12" being auto-redacted as
    an address; over-redaction is not free.) A line break in the same position is a layout
    artefact of one token far more often than it is two numbers that happen to straddle a
    wrap, so the evidence is on the side of joining. Recorded in QUESTIONS.md as Q12: the
    remaining gap — a TAB or an NBSP inside a token — is measured by the ``split_token``
    mutation class rather than assumed away.

    Returns the set of ORIGINAL indices belonging to such a run, so ``normalize`` can delete
    exactly those characters and keep one offset map rather than two.
    """
    out: set[int] = set()
    for m in _WRAPPED_TOKEN_RE.finditer(text):
        if _is_identifier_run(m.group(1)) and _is_identifier_run(m.group(3)):
            out.update(range(m.start(2), m.end(2)))
    return out


# A line break between two maximal alphanumeric runs. The right-hand run sits in a LOOKAHEAD
# so it is not consumed and can be the left-hand run of the next match -- otherwise "A\nB\nC"
# would see only the first break. \w would include '_', which is not a wrapped glyph.
_WRAPPED_TOKEN_RE = re.compile(
    r"(?<![^\W_])([^\W_]+)([^\S\n]*\n[^\S\n]*)(?=([^\W_]+)(?![^\W_]))"
)


def _is_identifier_run(run: str) -> bool:
    """Does ``run`` look like part of a broken IDENTIFIER rather than an ordinary word?

    The test is "contains no lowercase letter". Every identifier a renderer can break across a
    line -- IBAN, BIC, VIN, ECV, spisova znacka, account number -- is written in capitals and
    digits. An ordinary Slovak word is not.

    This test exists because the first version of the join had no test at all and fused ANY
    alphanumeric pair. Every wrapped line in a PDF ends one word and begins another, so that
    version welded them together: measured on a two-line fixture it produced the MENO surface
    "Novak\nRodne" -- the party's surname joined to the label of the next line -- which would
    have eaten the first word of the following line every time a name fell at a line end. An
    over-join is not a free recall win; it eats the document around the redaction.

    The cost of the restriction is recorded rather than hidden: a wrap inside a MIXED-CASE
    token is not rejoined, so the line_break_mid mutation cannot reach 1.000 on the types whose
    surfaces contain lowercase. That is measured by eval/mutation_gate.py every run.
    """
    return bool(run) and not any(ch.islower() for ch in run)


def _fold_indices(text: str) -> set[int]:
    """Indices whose homoglyph may be folded: those inside a token that ALREADY CONTAINS A
    LATIN LETTER.

    A Cyrillic letter inside an otherwise-Latin word is an attack (or a mixed-script paste),
    and folding it recovers the real word. A Cyrillic letter inside a word made of Cyrillic
    letters is just Cyrillic, and folding it destroys the word -- see the comment on
    _HOMOGLYPH_PAIRS for the leak that caused.

    "Contains a Latin letter" is the whole test, and it is deliberately that blunt. Every
    confusable has a Latin twin, so a token with no Latin letter at all cannot be a Latin word
    with something smuggled into it; and one Latin letter is enough to say the token was meant
    to be read as Latin.
    """
    out: set[int] = set()
    for m in _TOKEN_RE.finditer(text):
        token = m.group(0)
        has_latin = any("LATIN" in unicodedata.name(ch, "") for ch in token)
        # A DIGIT counts as evidence too, and leaving it out was a regression (red-team round
        # 4, R4-N1). An identifier written in confusable CAPITALS and digits -- an IBAN, an
        # ECV, an OP number -- contains no Latin letter at all, so the Latin-letter test alone
        # folded nothing and the identifier matched nothing: cyrillic_homoglyph fell from
        # 1.000 to 0.973 and every type that moved was an identifier. A Slovak word does not
        # contain digits, so this does not re-open the Cyrillic-name damage the test exists to
        # prevent.
        if has_latin or any(ch.isdigit() for ch in token):
            out.update(range(m.start(), m.end()))
    return out


# A maximal run of letters/digits. The unit a homoglyph decision is made over: script mixing
# is a property of a WORD, never of a character in isolation.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def strip_format_chars(s: str) -> str:
    """Remove every Unicode format character (category Cf) from ``s``.

    Exported because ``writer/pdf_body.py`` needs the SAME rule: it relocates each candidate by
    searching the page for its surface, and a format character has no glyph, so a surface that
    still contains one can never be found on the page. Two copies of "which characters are
    invisible" in two modules is how a needle gets stripped by one rule and produced by
    another; there is one rule and it lives here.
    """
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf")


def _compat(ch: str) -> str:
    """Per-character NFKC. Returns the character unchanged for everything ordinary; folds
    fullwidth digits, superscript digits, ligatures and other compatibility forms.

    NFKC is applied PER CHARACTER rather than to the whole string on purpose: a whole-string
    normalize() gives no way to attribute each output character to an input character, which
    is the entire point of this module. Composition across characters (the NFD case) is
    handled separately by the combining-mark branch in ``normalize`` below.
    """
    folded = unicodedata.normalize("NFKC", ch)
    return folded if folded else ch


def normalize(text: str, join_wrapped: bool = False) -> Normalized:
    """Normalize ``text`` and build the map back to it.

    ``join_wrapped=True`` additionally DELETES whitespace runs that contain a line break
    and are flanked by alphanumerics, reassembling a token a renderer broke across a line.
    ``detect()`` runs that view as an EXTRA pass and merges its candidates with the base
    pass's -- see _wrapped_run_indices for why it is an extra pass and not the only one.
    """
    joined = _wrapped_run_indices(text) if join_wrapped else frozenset()
    foldable = _fold_indices(text)
    if not text or (not joined and not _INTERESTING_RE.search(text)):
        # Fast path: nothing to do. ``unchanged`` is True and span() is the identity, so no
        # arrays are built and detect() pays nothing for the common paragraph.
        return Normalized(text=text, original=text, starts=(), ends=())

    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []

    # One entry per whitespace RUN, at the run's first index, holding the single character the
    # run collapses to. Indices inside a run are absent, which is how the loop below tells a
    # run's start from its continuation without looking ahead.
    ws_repl = {
        m.start(): ("\n" if _LINEBREAK_RE.search(m.group(0)) else " ")
        for m in _WS_RUN_RE.finditer(text)
    }

    for i, ch in enumerate(text):
        cat = unicodedata.category(ch)

        # 1. FORMAT CHARACTERS -- deleted outright. Nothing is emitted, so the offsets of
        # everything after this point shift; that is precisely what the map exists for.
        if cat == "Cf":
            # Nothing is emitted and NOTHING IS EXTENDED. A deleted character INSIDE a match is
            # already covered, because a span is [starts[first], ends[last]] and the deleted
            # character lies between those two -- so a zero-width space inside an IBAN falls
            # inside the span that redacts the IBAN with no special handling at all.
            #
            # Extending the previous character's end over the deleted one was tried first and
            # was WRONG at the EDGE of a match: it put a trailing invisible character into the
            # SURFACE, and writer/pdf_body.py relocates each candidate by SEARCHING THE PAGE
            # FOR ITS SURFACE -- so a surface carrying a character the page never drew is a
            # surface that cannot be found. Measured: a rodne cislo came back with a trailing
            # newline in its surface and survived only because PyMuPDF happened to tolerate it.
            # Interior coverage needs no help; edge coverage is not wanted.
            continue

        # 2. WHITESPACE -- every run collapses to ONE character. WHICH character depends on
        # whether the run contained a line break, and that distinction is load-bearing.
        #
        # Collapsing a line break to a SPACE was tried first and broke two things at once, in
        # opposite directions. detect/name_anchors.py's bare-name heuristic pairs Capitalized
        # tokens separated by HORIZONTAL space, so turning a wrap into a space made the last
        # word of one line and the first word of the next look like a first name and a surname
        # -- measured, it emitted the auto=True MENO surface "Novak\nRodne", which would have
        # eaten the label of the following line. And its field-label pattern uses [\n\r\t] as
        # the TERMINATOR of a label's value, so a text with no line breaks left in it let a
        # label value run to the end of the page.
        #
        # So the line boundary survives normalization. What a detector does with it stays the
        # detector's decision -- a value-internal separator that should tolerate a wrap says so
        # with \s, and a word-level heuristic that must not cross one says so with [^\S\n\r].
        # Normalization's job is to make the SPELLING of the whitespace uniform (one tab, one
        # NBSP, one run of five spaces and one CRLF all become one character), not to decide
        # which detectors may see through it.
        if ch.isspace():
            if i in joined:
                # A wrap inside an identifier, in the join_wrapped view: deleted outright,
                # exactly as a format character is, so the two halves become one token. A break
                # INTERIOR to a match is covered by the span's own extent; a break at the edge
                # is not, and must not be -- see the Cf branch above.
                continue
            repl = ws_repl.get(i)
            if repl is None:
                # A continuation of a run already emitted: extend that character's source range
                # over this one, so the whole run maps back as a unit.
                if ends:
                    ends[-1] = i + 1
                continue
            out.append(repl)
            starts.append(i)
            ends.append(i + 1)
            continue

        # 3. COMBINING MARK -- try to compose it into the character already emitted (NFD -> NFC).
        # This is the only many-to-one rewrite in the module: two original characters become
        # one normalized character, whose source range covers both.
        if cat.startswith("M") and out:
            composed = unicodedata.normalize("NFC", out[-1] + ch)
            if len(composed) == 1:
                out[-1] = composed
                ends[-1] = i + 1
                continue
            # Does not compose (a stray mark, or a base that has no precomposed form).
            # Fall through and emit it as an ordinary character rather than dropping it.

        # 4. HOMOGLYPH then COMPATIBILITY FOLD. The homoglyph map is 1:1; _compat may expand
        # one character into several, each of which maps back to this single original index.
        code = ord(ch)
        base = _HOMOGLYPHS.get(code, ch) if i in foldable else ch
        base = _HYPHENS.get(code, base)
        folded = _compat(base)
        for piece in folded:
            out.append(piece)
            starts.append(i)
            ends.append(i + 1)

    norm = "".join(out)
    if norm == text:
        # Normalization was a no-op after all (e.g. the only "interesting" character was a
        # lone tab that is already a single space run). Collapse to the identity so callers
        # take the cheap path and surfaces are sliced straight from the original.
        return Normalized(text=text, original=text, starts=(), ends=())
    return Normalized(text=norm, original=text, starts=tuple(starts), ends=tuple(ends))
