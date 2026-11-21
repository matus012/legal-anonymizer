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
  6. CP1250-AS-WINANSI MOJIBAKE is folded back, 1:1, but ONLY IN A UNIT THAT SHOWS EVIDENCE
     of the failure -- a Slovak contract may legitimately name "Citroën" or "Malmö". See
     _build_mojibake_tables and has_mojibake_evidence for the table's derivation and the
     measurement behind the evidence threshold.

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


# ------------------------------------------------------------------- cp1250-as-WinAnsi fold
# THE CLASSIC CENTRAL-EUROPEAN ENCODING FAILURE, folded back (red-team round 4, R4-I3).
#
# A cp1250 (Central European) text layer drawn with /WinAnsiEncoding is re-read byte for byte
# as cp1252: "č" (0xE8) arrives as "è", "ď" (0xEF) as "ï", "ň" (0xF2) as "ò", "ĺ" (0xE5) as
# "å", "ľ" (0xBE) as "¾", "Ľ" (0xBC) as "¼". "á í é ó ú ý š ž" are IDENTICAL in both code
# pages and come through untouched, which is what makes the damage partial and nearly
# invisible -- most of the page reads perfectly, and NEITHER PDF refusal fires: every
# replacement is a letter or a punctuation sign (never Cc/Cn), so page_has_unreadable_text is
# False, and the token structure is unchanged, so page_is_shredded is False. The source is
# ordinary: legacy Slovak court, land-registry and DMS systems, older Ghostscript paths and
# RTF->PDF converters.
#
# WHY IT BELONGS HERE. The confusion is ONE CHARACTER FOR ONE CHARACTER, so the repair is
# OFFSET-PRESERVING -- which is the property that decides where it can live. Both writers CUT
# THE DOCUMENT at detector offsets, so a repair that changed lengths would corrupt files
# rather than mislabel them. Offset-preserving means it is a fold, exactly like the Cyrillic
# homoglyph fold above: detection runs over the repaired view, each hit maps back to ORIGINAL
# offsets through the map this module already builds, and the writer redacts the original
# mojibake surface -- which is what the reader actually sees on the page.
#
# THE TABLE IS DERIVED, NOT TYPED. Hand-typing 50 accented characters into this file is how a
# table acquires a typo nobody can see. It is built by running each character through the two
# codecs, which is the same construction corpus/mutations.py uses for the attack -- reached
# independently, because detect/ may not import from corpus/ (tests/test_detect_registry.py
# enforces that) and because a table shared with the attack would grade itself.


def _build_mojibake_tables() -> tuple[dict[int, str], frozenset[str], frozenset[str]]:
    """Derive (inverse fold, ambiguous images, evidence characters) from the codecs.

    ``forward`` is what the failure does: character -> single cp1250 byte -> cp1252 reading.
    The five bytes 0x81/0x8D/0x8F/0x90/0x9D are UNDEFINED in WinAnsi, and a decoder yields
    U+FFFD for all of them -- so "Ť", "ť" and "Ź" all arrive as the SAME character and the
    inverse is genuinely ambiguous there. Those images are excluded from the fold (guessing
    which letter a lost byte was is not a repair) and returned separately, because a PDF page
    that contains one is a page whose repair CANNOT be completed -- see
    writer/pdf_body.MojibakeTextLayerError.

    EVIDENCE is narrower than the fold on purpose: only the images of the letters that are
    SLOVAK. Those are the characters whose presence in a Slovak document is the signature of
    this failure rather than an ordinary foreign word. The rest of the table (Polish, Romanian,
    Hungarian and Turkish letters, and the bare spacing diacritics) images onto characters that
    occur legitimately -- "m³", "£", "¿", "1ª" -- and including them would have made "m³" the
    evidence that a page is mis-decoded. Measured: the narrow set is worth nothing in
    sensitivity (0.9707 of changed corpus units either way) and removes every one of those
    false-evidence shapes.
    """
    forward: dict[str, str] = {}
    for code in range(0x20, 0x2500):
        ch = chr(code)
        try:
            raw = ch.encode("cp1250")
        except UnicodeEncodeError:
            continue
        if len(raw) != 1:
            continue
        try:
            seen = raw.decode("cp1252")
        except UnicodeDecodeError:
            seen = "�"
        if seen != ch:
            forward[ch] = seen

    seen_count: dict[str, int] = {}
    for image in forward.values():
        seen_count[image] = seen_count.get(image, 0) + 1

    inverse = {ord(image): src for src, image in forward.items() if seen_count[image] == 1}
    collapsed = frozenset(im for im, n in seen_count.items() if n > 1)
    evidence = frozenset(
        forward[ch] for ch in _SLOVAK_LETTERS if ch in forward and forward[ch] not in collapsed
    )
    # The bullet is in the AMBIGUOUS set but NOT in the EVIDENCE set. It is what a PDF reader
    # shows for a lost byte, so it says "this repair cannot be finished" -- but it is also an
    # ordinary character in an ordinary document, so it must never be the thing that says "this
    # document is mis-decoded" in the first place.
    return inverse, collapsed | _SUBSTITUTE_GLYPHS, evidence | collapsed


# Every letter of the Slovak alphabet that carries a diacritic. Written out rather than
# derived, because "which letters are Slovak" is a fact about the language, not about Unicode.
_SLOVAK_LETTERS = "ÁáÄäČčĎďÉéÍíĹĺĽľŇňÓóÔôŔŕŠšŤťÚúÝýŽž"

# WHAT A READER SHOWS FOR A BYTE WINANSI DOES NOT DEFINE. Five cp1250 bytes -- 0x81, 0x8D,
# 0x8F, 0x90, 0x9D -- have no WinAnsi character, and two of them are the Slovak "Ť" and "ť".
# There is no single answer to what appears in their place, so BOTH answers this project
# actually meets are listed:
#
#   * U+FFFD, what Python's cp1252 codec yields, and therefore what corpus/mutations.py writes
#     when it models the failure on text;
#   * U+2022 BULLET, what a PDF reader yields -- PDF 32000-1 Annex D.2 specifies the bullet as
#     the character shown for every code WinAnsiEncoding leaves undefined, and PyMuPDF follows
#     it. MEASURED, not assumed: a hand-built PDF carrying "príslušnosť" in cp1250 bytes with
#     /WinAnsiEncoding extracts as "príslušnos•". Keying the refusal on U+FFFD alone would
#     have made it dead code on the one path it exists for.
#
# A bullet is of course an ordinary character, which is why mojibake_is_unrepairable requires
# BOTH the mojibake signature AND the bullet to sit INSIDE A WORD. A list bullet is followed by
# a space; a destroyed letter is not. Measured over every corpus PDF: zero refusals.
_SUBSTITUTE_GLYPHS = frozenset({"�", "•"})

_MOJIBAKE_INVERSE, MOJIBAKE_AMBIGUOUS, _MOJIBAKE_EVIDENCE = _build_mojibake_tables()


def _has_letter_neighbour(text: str, i: int) -> bool:
    """Is ``text[i]`` immediately beside a letter -- i.e. inside a word rather than standing on
    its own? The one test that separates "è" in a mis-decoded Slovak word from "à" standing
    alone as a French preposition, and a destroyed letter from a list bullet."""
    return (i > 0 and unicodedata.category(text[i - 1]).startswith("L")) or (
        i + 1 < len(text) and unicodedata.category(text[i + 1]).startswith("L")
    )


def has_mojibake_evidence(text: str) -> bool:
    """Does ``text`` carry the signature of a cp1250 text layer read as WinAnsi?

    THE TEST IS ONE WORD-INTERNAL EVIDENCE CHARACTER, and the threshold is 1 because it was
    MEASURED rather than guessed. Over the whole clean corpus -- 3 855 detect() units from the
    71 corpus .docx plus the demo, and 82 PDF pages from the 71 corpus .pdf plus the demo --
    the count of evidence characters is ZERO, not merely the count of firings. There is
    nothing for a higher threshold to protect against, and a higher threshold costs recall on
    exactly the short units that matter: a table cell holding nothing but "Ján Kováè" carries
    one. Requiring two DISTINCT tokens was measured too and fired on 0.460 of the mutated
    corpus units against 0.971 for this rule -- half the damage left unrepaired to defend
    against a risk the corpus does not contain.

    WORD-INTERNAL (a letter immediately before or after) is the part that does the work in a
    document the corpus does NOT contain. "à" standing alone is French; "podľa" mis-decoded to
    "pod¾a" is not a word in any language. The neighbour test costs nothing on mutated text --
    almost every mojibaked letter sits inside a word by construction -- and removes the
    standalone symbol readings entirely.

    THE ABBREVIATION POINT IS THE ONE EXCEPTION, and it was measured rather than foreseen.
    Slovak writes a number as "byt č. 151", so the mis-decoded "è" stands between a space and
    a full stop with no letter beside it -- the unit "Byt: byt è. 151" has no other evidence
    in it at all, and CISLO_BYTU sat at robustness 0.750 entirely on that shape. An evidence
    character IMMEDIATELY FOLLOWED BY "." is therefore evidence too. It is a narrow
    widening: "č." is an abbreviation marker on every Slovak filing, while a Slovak legal
    document that ends a sentence with the bare Italian word "è" is not a document this tool
    will ever meet.

    WHAT THIS STILL RISKS, stated rather than hidden: a document whose ONLY foreign content is
    a single word-internal evidence character -- "Renè", "Håkon", "Bjørn" -- is folded as
    though it were mojibake. The cost of that is small and one-sided: the fold is
    offset-preserving, so nothing is mis-cut, the reported surface is still sliced from the
    ORIGINAL text, and detect() normalizes the user's known-entity list through this same fold,
    so a lawyer who types "Renè" still matches a document that spells it "Renè". What changes
    is only which spelling the detectors pattern-match against.
    """
    return any(
        ch in _MOJIBAKE_EVIDENCE
        and (
            _has_letter_neighbour(text, i)
            or (i + 1 < len(text) and text[i + 1] == ".")
        )
        for i, ch in enumerate(text)
    )


def mojibake_is_unrepairable(text: str) -> bool:
    """Mojibake evidence AND at least one character whose repair is a GUESS.

    The five WinAnsi-undefined bytes all decode to U+FFFD, so "Ť", "ť" and "Ź" are the same
    character by the time the text reaches us -- and "ť" is one of the commonest letters in
    Slovak. The information is genuinely gone: the PDF viewer draws nothing for that byte
    either, so the human reader cannot recover it any more than we can. Choosing one of the
    three would be inventing document text, and the character it replaced can be inside a
    surname. So the PDF writer refuses instead; see writer/pdf_body.MojibakeTextLayerError.

    THE SUBSTITUTE MUST SIT INSIDE A WORD. A PDF reader shows U+2022 BULLET for a lost byte
    (see _SUBSTITUTE_GLYPHS), and a bullet is also what a bulleted list is made of. A list
    bullet is followed by a space and preceded by a line break; the one in "príslušnos•" is
    not. Without this the refusal would fire on any mis-decoded page that also has a list on
    it -- and a refusal that fires on ordinary structure is how a tool gets switched off.
    """
    return has_mojibake_evidence(text) and any(
        ch in MOJIBAKE_AMBIGUOUS and _has_letter_neighbour(text, i)
        for i, ch in enumerate(text)
    )


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
    # Decided ONCE for the whole unit, not per character: the encoding of a text layer is a
    # property of the document, not of one letter, and a per-character test has no way to tell
    # "è" in a mis-decoded Slovak page from "è" in a French name. It is also what keeps the
    # fast path below honest -- most mojibake images (U+00C0..U+017F) sit INSIDE
    # _INTERESTING_RE's allowed range, so "Ján Kováè" would otherwise be returned untouched.
    mojibake = has_mojibake_evidence(text)
    if not text or (not joined and not mojibake and not _INTERESTING_RE.search(text)):
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

        # 4. MOJIBAKE, then HOMOGLYPH, then COMPATIBILITY FOLD. The homoglyph map is 1:1;
        # _compat may expand one character into several, each of which maps back to this single
        # original index.
        #
        # The mojibake fold runs FIRST and EXCLUSIVELY: its images are accented Latin letters
        # and two punctuation signs, none of which is a script confusable or a hyphen, so there
        # is nothing for the other two maps to do to a character it claims. Running it before
        # _compat is load-bearing in one place -- per-character NFKC turns "¾" into "3⁄4" and
        # "¼" into "1⁄4", so without this fold a mis-decoded "nehnuteľnosť" reaches the
        # detectors as "nehnute3⁄4nos?" and is not one token any more.
        code = ord(ch)
        if mojibake and code in _MOJIBAKE_INVERSE:
            base = _MOJIBAKE_INVERSE[code]
        else:
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
