"""Red-team round 2 — TEXT MUTATIONS that attack the DETECTORS (not the extractor).

Round 1 (``redteam/FINDINGS.md``) attacked ``eval/extract.py``: the surfaces the leak gate
can *read*. This module attacks the other half of the same premise — whether a surface
written in a slightly unusual way is still *found*. A detector that only matches the one
spelling the corpus generator happens to author is a detector that passes every gate in
this repo and leaks on the first real document.

Two mutations from this list were tried by hand before the module existed and **both were
real leaks**, which is why the rest are being run systematically:

* an NBSP between the words of a multi-word anchor  -> anchor missed -> client number leaked
* a line break between the words of an anchor       -> same, leaked in a corpus PDF

Both are fixed (``detect/core.py`` NBSP normalization; ``detect/office_refs.py`` ``_AWS``).

--------------------------------------------------------------------------------------
THE HOMOMORPHISM REQUIREMENT (read before adding a mutation)
--------------------------------------------------------------------------------------
Every mutation here must satisfy, for a ground-truth surface ``s`` occurring in document
text ``t``::

    s in t   =>   mutate(s) in mutate(t)

Without it the harness stops asking "is the mutated surface still found?" and starts asking
"is a string that is no longer in the document still found?", whose answer is always no —
a harness artefact indistinguishable from a detector defect. The mutations below are
therefore all either CHARACTER-LOCAL (a 1:1 or 1:n rewrite of one character, independent of
its neighbours) or TOKEN-LOCAL and START-ANCHORED (a deterministic edit of each maximal
alphanumeric run, measured from the run's first character).

Token-local start-anchored mutations still break the property in one case: when the GT
surface is a STRICT SUFFIX of a longer token in the document (``1234567890`` inside
``SK1234567890``). That is not fixable inside the mutation — it is a property of the pair —
so ``eval/mutation_gate.py`` re-checks containment per (surface, mutation) pair at run time
and EXCLUDES the pairs that fail, counting and printing them. A number the harness cannot
ask for is never recorded as a miss.

--------------------------------------------------------------------------------------
Each mutation is a pure ``def mutate_<name>(text: str) -> str`` and is registered in
``MUTATIONS``. Nothing here imports ``detect/`` or ``eval/``; it is pure text in, text out.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

# --------------------------------------------------------------------------- characters
NBSP = " "         # non-breaking space
ZWSP = "​"         # zero-width space
ZWJ = "‍"          # zero-width joiner
SHY = "­"          # soft hyphen / optional hyphen

# A maximal run of Unicode letters/digits (underscore excluded). This is the "token" every
# token-local mutation below edits. Slovak diacritics are letters, so they are inside a run;
# a space, a slash, a dash, a dot or a colon ends one.
_RUN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _edit_runs(text: str, edit: Callable[[str], str]) -> str:
    """Apply ``edit`` to every maximal alphanumeric run. Token-local by construction."""
    return _RUN_RE.sub(lambda m: edit(m.group(0)), text)


# --------------------------------------------------------------------------- 1. nbsp
def mutate_nbsp(text: str) -> str:
    """Every ASCII space becomes U+00A0 NON-BREAKING SPACE.

    Real-world source: Slovak typography. The rule that a one-letter preposition, an
    abbreviation ("č.", "ul.", "r. č.") or a number+unit pair must not be split across a line
    is implemented in Word, in LaTeX and in every Slovak house style by typing an NBSP, and
    Word's autocorrect inserts them unasked. A PDF text layer produces them constantly where
    the renderer justified a line. This is the mutation that already produced one live leak:
    the demo contract's PDF rendered "Číslo klienta:" with an NBSP inside the phrase, the
    anchor did not match, and KL-99321 survived into the redacted PDF.
    """
    return text.replace(" ", NBSP)


# --------------------------------------------------------------------------- 2. zero_width
def mutate_zero_width(text: str) -> str:
    """Insert U+200B (and, in runs of 6+, U+200D) inside every alphanumeric run.

    Real-world source: copy-paste. Bank portals, e-government sites and webmail insert
    zero-width spaces as soft line-break opportunities inside long unbreakable strings —
    an IBAN, an account number, a case reference — and a lawyer pasting "the number from the
    bank's website" into a filing pastes them too. They are invisible in Word and in every
    PDF viewer, so nobody can see that the document contains them. U+200D additionally
    survives most "clean up formatting" passes because it is a joiner, not a space.

    Token-local and start-anchored: ZWSP after the run's 2nd character, ZWJ after its 4th.
    """

    def edit(run: str) -> str:
        if len(run) < 4:
            return run
        if len(run) < 6:
            return run[:2] + ZWSP + run[2:]
        return run[:2] + ZWSP + run[2:4] + ZWJ + run[4:]

    return _edit_runs(text, edit)


# --------------------------------------------------------------------------- 3. soft_hyphen
def mutate_soft_hyphen(text: str) -> str:
    """Insert U+00AD SOFT HYPHEN inside every alphanumeric run of 4+ characters.

    Real-world source: Word's automatic hyphenation and the manual "optional hyphen"
    (Ctrl+-) that typists use to control where a long word may break. The character renders
    as nothing unless the break actually happens, so a document full of them looks perfectly
    ordinary. ``eval/extract.py`` already knows PyMuPDF renders a hyphen as U+00AD in a PDF
    text layer (``corpus/groundtruth.py`` records the override), so this is not hypothetical
    for this project — it is a character the pipeline already meets.

    Token-local and start-anchored: SHY after the run's 3rd character.
    """

    def edit(run: str) -> str:
        return run if len(run) < 4 else run[:3] + SHY + run[3:]

    return _edit_runs(text, edit)


# --------------------------------------------------------------------------- 4. tabs
def mutate_tabs(text: str) -> str:
    """Every ASCII space becomes a TAB.

    Real-world source: tab-delimited layout. Older Slovak legal templates (and anything that
    began life in WordPerfect or a plain-text form) align a field label against its value
    with tabs rather than a table: "Meno a priezvisko:\\tJán Novák". A DOCX table flattened
    to text, and a PDF text layer with column gaps, both yield tabs in the same positions.
    This is the worst case of that — every separator is a tab — and it is deliberately the
    worst case, because it asks one precise question: which separators does a detector spell
    ``[ NBSP]`` (dies) and which does it spell ``\\s`` (survives)?
    """
    return text.replace(" ", "\t")


# --------------------------------------------------------------------------- 5. double_spaces
def mutate_double_spaces(text: str) -> str:
    """Every ASCII space is doubled.

    Real-world source: manual alignment. Documents typed by people who align columns with
    the space bar, documents converted from fixed-width text, and PDF text layers where the
    extractor inserts a space per unit of horizontal gap all produce runs of spaces. It
    matters here because several detectors treat "2+ spaces" as a COLUMN BOUNDARY that
    TERMINATES a value (``detect/office_refs.py`` NAZOV_UCTU, ``detect/name_anchors.py``
    field labels) — so doubling the spaces inside a value truncates it, and doubling the
    space inside a two-word anchor may break the anchor.
    """
    return text.replace(" ", "  ")


# --------------------------------------------------------------------------- 6. line_break_mid
def mutate_line_break_mid(text: str) -> str:
    """A newline between every pair of words AND inside every alphanumeric run of 6+.

    Real-world source: line wrapping. This is the second mutation that already produced a
    live leak: corpus PDF ``zmluva_v11_034.pdf`` wrapped as "... BIC FYCWSKZC . Cislo" +
    newline + "klienta: 2019-7785", the two-word anchor "číslo klienta" did not match, and
    the client number leaked into the redacted text layer while the DOCX of the same document
    was clean. The mid-run half simulates the other thing a renderer does at a line end —
    breaking a long unbreakable token — and what a DOCX does when a run boundary falls inside
    an identifier.

    Deliberately the worst case (a break at EVERY opportunity, not one), because the question
    is binary: does a break anywhere inside an anchor or an entity destroy the match?
    """

    def edit(run: str) -> str:
        return run if len(run) < 6 else run[:3] + "\n" + run[3:]

    return _edit_runs(text.replace(" ", "\n"), edit)


# --------------------------------------------------------------------------- 7. all_caps
def mutate_all_caps(text: str) -> str:
    """The whole document uppercased.

    Real-world source: form letters, court headers, scanned-and-OCR'd documents set in caps,
    and the Slovak habit of setting party designations in caps ("PREDÁVAJÚCI:", "KUPUJÚCI:").
    A whole document in caps is rarer than a section in caps, but the section is the same
    test and the document is the strictly harder one.

    NOTE FOR THE READER OF THE NUMBER: this mutation DESTROYS the evidence the bare-name
    heuristic legitimately depends on (a Capitalized token in running lowercase prose). A
    loss on the bare-name population is INHERENT, not a defect. A loss on an ANCHORED
    population — a name after "Meno a priezvisko:" or after a role word — is not: the anchor
    still identifies the value, so the detector could still find it.
    """
    return text.upper()


# --------------------------------------------------------------------------- 8. lowercase
def mutate_lowercase(text: str) -> str:
    """The whole document lowercased.

    Real-world source: text typed in a hurry, chat/e-mail-style submissions, and — the one
    that matters for a legal tool — text that has been through a normalisation step
    (a search index, a case-insensitive database column, an OCR post-processor) and comes
    back lowercased. Same caveat as ``all_caps``: capitalisation-dependent heuristics lose
    evidence that genuinely was there, anchor-dependent detectors do not.
    """
    return text.lower()


# --------------------------------------------------------------------------- 9. no_diacritics
_DIACRITIC_EXCEPTIONS = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D"})


def mutate_no_diacritics(text: str) -> str:
    """Slovak diacritics stripped: á->a, č->c, š->s, ž->z, ô->o, ä->a, ľ->l, ď->d, ť->t, ...

    Real-world source: the single most common real deformation of Slovak text. Documents
    typed on a non-Slovak keyboard layout, imported from systems with a Latin-1 or ASCII
    field, produced by older court IT, or deliberately de-accented to survive a legacy
    interface. ``QUESTIONS.md`` Q7 already measured five anchor-required types losing their
    anchor to this and left it OPEN for this round.

    Implemented as NFD + drop every combining mark + NFC, which is exactly what a de-accenting
    converter does, plus the handful of Latin letters whose diacritic is not a combining mark.
    """
    decomposed = unicodedata.normalize("NFD", text.translate(_DIACRITIC_EXCEPTIONS))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", stripped)


# --------------------------------------------------------------------------- 10. cyrillic
_HOMOGLYPHS = str.maketrans(
    {
        "a": "а", "o": "о", "e": "е",
        "c": "с", "p": "р", "x": "х",
        "A": "А", "O": "О", "E": "Е",
        "C": "С", "P": "Р", "X": "Х",
    }
)


def mutate_cyrillic_homoglyph(text: str) -> str:
    """Latin a/o/e/c/p/x (both cases) swapped for the Cyrillic lookalikes а/о/е/с/р/х.

    Real-world source: mixed-script paste. A document assembled from parts typed on a
    Cyrillic-capable layout, a name transliterated by someone with a Russian/Ukrainian/Serbian
    keyboard, an OCR engine with a Cyrillic language model, or a deliberate filter-evasion.
    Slovakia has a large Ukrainian-speaking population and cross-border filings are ordinary,
    so a Cyrillic "о" inside an otherwise-Latin Slovak surname is not an exotic attack, it is
    a Tuesday. The characters are visually identical, so the document looks perfectly normal
    and no reviewer will ever spot it.

    JUDGEMENT CALL: the brief lists the lowercase set only. The uppercase homoglyphs are
    included because they are produced by exactly the same causes and because the ALL-CAPS
    population (court headers, party designations) is where an uppercase swap would land.
    """
    return text.translate(_HOMOGLYPHS)


# --------------------------------------------------------------------------- 11. nfd
def mutate_nfd(text: str) -> str:
    """Unicode NFD (canonical DECOMPOSITION) instead of NFC.

    Real-world source: macOS. HFS+/APFS and several macOS text paths hand back decomposed
    Unicode, so a .docx produced or round-tripped on a Mac can carry "č" as ``c`` + U+030C
    rather than as U+010D. The two are canonically equivalent and render identically —
    Word, Acrobat and the human eye cannot tell them apart — but they are DIFFERENT BYTES and
    therefore different to every regex character class, every ``str`` comparison and every
    dict lookup in ``detect/``. Some PDF text extractors and some XML toolchains do the same.

    Unlike ``no_diacritics``, this mutation destroys NO information at all: the text is
    byte-for-byte recoverable with one call to ``unicodedata.normalize("NFC", ...)``. Any
    detection loss here is therefore a pure DEFECT with a one-line fix and no trade-off.
    """
    return unicodedata.normalize("NFD", text)


# =========================================================================================
# RED-TEAM ROUND 3 ADDITIONS (redteam/FINDINGS_ROUND3.md)
# -----------------------------------------------------------------------------------------
# Round 2's eleven mutations are all either INVISIBLE characters (nbsp, zero_width,
# soft_hyphen, nfd, cyrillic_homoglyph) or WHITESPACE/CASE rewrites applied to the WHOLE
# document (tabs, double_spaces, line_break_mid, all_caps, lowercase, no_diacritics). The four
# below attack three shapes none of those can reach, and every one of them satisfies the
# HOMOMORPHISM REQUIREMENT documented at the top of this module:
#
#   * mutate_nb_hyphen / mutate_narrow_nbsp are CHARACTER-LOCAL 1:1 rewrites, the same class
#     as mutate_nbsp, so the property holds unconditionally.
#   * mutate_surname_caps / mutate_letterspaced are TOKEN-LOCAL and START-ANCHORED: each
#     maximal alphanumeric run is rewritten by a function of that run alone, measured from its
#     first character, exactly as mutate_zero_width and mutate_soft_hyphen are. They inherit
#     the same documented caveat (a GT surface that is a strict suffix of a longer document
#     token) and the same remedy: eval/mutation_gate.py re-checks containment per pair and
#     EXCLUDES the pairs it cannot ask about, counting them.
# =========================================================================================

NBHY = "‑"     # NON-BREAKING HYPHEN
NNBSP = " "    # NARROW NO-BREAK SPACE


# --------------------------------------------------------------------------- 12. nb_hyphen
def mutate_nb_hyphen(text: str) -> str:
    """Every ASCII hyphen-minus becomes U+2011 NON-BREAKING HYPHEN.

    Real-world source: Ctrl+Shift+hyphen in Word, which exists for precisely one purpose —
    stopping a reference from breaking at a line end. A Slovak filing is full of tokens nobody
    wants broken: a spisová značka ``V-1234/2025``, an EČV ``BA-123AB``, a client number
    ``KL-99321``, a legacy account ``123456-1234567890/1100``, a double surname
    ``Kováč-Nagy``. Slovak house styles and the ministry's own templates call for the
    non-breaking form in exactly those places, and LibreOffice/Word autocorrect will also
    insert one. It renders IDENTICALLY to a hyphen — no reviewer can see the difference.

    This is NOT covered by the existing normalization layer, and that is the point of adding
    it: ``detect/normalize.py`` runs per-character NFKC, and NFKC(U+2011) is U+2010 HYPHEN,
    which is still not the ASCII ``-`` every pattern in ``detect/`` spells. The fold fires,
    changes the character, and lands one codepoint short.

    Character-local, 1:1, offset-preserving — the same shape as ``mutate_nbsp``.
    """
    return text.replace("-", NBHY)


# ------------------------------------------------------------------------ 13. narrow_nbsp
def mutate_narrow_nbsp(text: str) -> str:
    """Every ASCII space becomes U+202F NARROW NO-BREAK SPACE.

    Real-world source: continental typography. U+202F is the correct space between a number
    and its unit and inside grouped digits ("1 234,56 €"), and Word/LibreOffice autocorrect
    inserts it; it also arrives from any document that passed through a French or Swiss
    locale, and from several PDF text extractors that map a thin justification space onto it.

    This one is included as a POSITIVE CONTROL, in the sense round 2 used ``nbsp``: U+202F is
    Unicode category Zs and ``str.isspace()`` is True for it, so ``detect/normalize.py``'s
    whitespace-run collapse should absorb it exactly as it absorbs U+00A0. A number below
    1.000 here would mean the whitespace collapse is narrower than it claims to be; 1.000
    means the harness is measuring the layer and not something else. A mutation whose answer
    is predictable is worth its runtime precisely because it can falsify the instrument.

    Character-local, 1:1.
    """
    return text.replace(" ", NNBSP)


# ----------------------------------------------------------------------- 14. surname_caps
def mutate_surname_caps(text: str) -> str:
    """Every Capitalized alphabetic run of 4+ characters is UPPERCASED. The document as a
    whole stays MIXED-CASE.

    Real-world source: the continental legal convention of setting the surname in capitals to
    mark which of two names is the family name — "Ján NOVÁK", "JUDr. Mária KOVÁČOVÁ". It is
    used throughout ORSR extracts, notarial deeds, court headers and identity documents, and
    a Slovak law office meets it daily.

    WHY THIS IS NOT A DUPLICATE OF ``all_caps``, and this is the whole reason it exists:
    ``all_caps`` uppercases the ENTIRE unit, which makes ``detect/identifiers.py``'s
    ``document_is_single_case`` return True and switches ``detect/name_anchors.py`` to its
    RELAXED (case-insensitive) regex set. A document that is mixed-case overall but writes
    SOME tokens in capitals keeps the STRICT set, whose ``_CAP`` token class is literally
    ``[A-ZÁÄČ…][a-záäč…]+`` — an uppercase letter followed by LOWERCASE ones. So the very
    population ``all_caps`` rescues by relaxing, this mutation leaves unrescued. Round 2's
    all-caps arm could not have found this shape; it is structurally invisible to it.

    HONEST LIMIT OF THE AGGREGATE NUMBER. The predicate is a function of one token, because
    it has to be (see the homomorphism note above), so it uppercases ordinary Capitalized
    words too — "Zmluva", "Košice", "Predávajúci". The aggregate robustness therefore measures
    the deformation CLASS "some tokens are in capitals in a mixed-case document", not the
    narrow "only the surname is". The attributable evidence for the narrow claim is the hand
    discriminator in redteam/FINDINGS_ROUND3.md A5, not this number.

    Token-local and start-anchored: the rewrite of a run depends only on that run.
    """

    def edit(run: str) -> str:
        if len(run) < 4 or not run[0].isupper():
            return run
        return run.upper() if run[1:].islower() else run

    return _edit_runs(text, edit)


# ----------------------------------------------------------------------- 15. letterspaced
def mutate_letterspaced(text: str) -> str:
    """A single space is inserted BETWEEN every pair of characters of each 4+ character run:
    ``Novák`` -> ``N o v á k``.

    Real-world source: two of them, and the second is the one that matters.

    1. Letter-spacing (``razvetrené písmo``) is a live Slovak typographic convention for
       headings and for party designations in notarial deeds, and Word implements it as
       CHARACTER SPACING, which several PDF text extractors then render as real spaces.
    2. More importantly, it is what a PDF text layer ACTUALLY HANDS THIS PIPELINE when the
       producer positions text per glyph and the advances do not match the font's own metrics
       — a legal DMS export, a PDF/A converter, an OCR-to-PDF pipeline, or any document with
       tracking applied. Measured in redteam/FINDINGS_ROUND3.md C1: at 1.3x tracking PyMuPDF's
       ``get_text()`` returns ``P re d a v a ju ci: Ja n N o va k``, ``detect()`` finds
       nothing, the writer redacts nothing, and — because ``eval/extract.py`` reads the same
       mangled string — the leak gate greps CLEAN on a completely unredacted document.

    This mutation is the corpus-wide measurement of that damage. Round 2 explicitly recorded
    "DOCX only; no PDF arm" as judgement call 1, with the cost stated as "a PDF-only
    normalization defect is invisible to this gate". This is that defect, expressed as a text
    mutation so the existing DOCX-unit harness can put a number on it.

    NOTE ON THE SEPARATOR: a plain space, not a zero-width or invisible character. The round-2
    invisible-character classes are all Unicode category Cf and are DELETED outright by
    ``detect/normalize.py``; a real space is not, and must not be — deleting spaces would
    weld every pair of words in every document. So this is a genuinely different question from
    ``zero_width``, not a restatement of it.

    Token-local and start-anchored.
    """

    def edit(run: str) -> str:
        return run if len(run) < 4 else " ".join(run)

    return _edit_runs(text, edit)


# --------------------------------------------------------------------------- round 4
# The cp1250 -> cp1252 confusion table, built once. A character that encodes to a single byte
# in cp1250 is re-read as cp1252 (WinAnsi); a character that does not is left alone. Every
# entry is therefore 1 character for 1 character, which makes this the same CHARACTER-LOCAL
# class as mutate_nbsp and the homomorphism property holds unconditionally.
def _build_cp1250_as_winansi() -> dict[int, str]:
    table: dict[int, str] = {}
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
            # 0x81/0x8D/0x8F/0x90/0x9D are UNDEFINED in WinAnsi. A reader that meets one has
            # nothing to show for it; U+FFFD is what a decoder produces and keeps the rewrite
            # 1:1. Choosing to leave the character alone instead would UNDER-state the damage.
            seen = "�"
        if seen != ch:
            table[code] = seen
    return table


_CP1250_AS_WINANSI = _build_cp1250_as_winansi()


def mutate_mojibake_cp1250(text: str) -> str:
    """Re-read every character as if cp1250 bytes had been drawn with ``/WinAnsiEncoding``.

    THE CLASSIC CENTRAL-EUROPEAN ENCODING FAILURE, and — unlike the round-2 and round-3
    classes — one that arrives through a door the two new PDF refusals do not watch:

    * ``č`` (0xE8 in cp1250) is ``è`` in cp1252, ``ď`` (0xEF) is ``ï``, ``ň`` (0xF2) is ``ò``,
      ``ĺ`` (0xE5) is ``å``, ``ľ`` (0xBE) is ``¾``, ``Ľ`` (0xBC) is ``¼``, ``ř`` (0xF8) is
      ``ø``. ``á í é ó ú ý ô š ž`` are IDENTICAL in both code pages and come through untouched,
      which is what makes the damage partial and invisible: most of the page reads perfectly.
    * every replacement is a LETTER (Unicode ``Ll``/``Lu``) or a punctuation sign, never a
      control character, so ``writer/pdf_body.page_has_unreadable_text`` is False;
    * the token structure is unchanged, so ``page_is_shredded`` is False.

    So a PDF deformed this way is ACCEPTED, and ``eval/extract.py`` reads the same deformed
    text the detector does — the same double-blind R3-C1 and R3-C4 describe, reached by a
    third route. Red-team round 4, finding R4-I3.

    Real-world source: legacy Slovak court, land-registry and DMS systems, older Ghostscript
    paths and RTF->PDF converters that write a WinAnsi ``/Encoding`` over Central-European
    bytes. A Slovak law office receives PDFs from all of them.

    Character-local and 1:1 -- the homomorphism requirement holds unconditionally.
    """
    return text.translate(_CP1250_AS_WINANSI)


# --------------------------------------------------------------------------- registry
MUTATIONS: dict[str, Callable[[str], str]] = {
    "nbsp": mutate_nbsp,
    "zero_width": mutate_zero_width,
    "soft_hyphen": mutate_soft_hyphen,
    "tabs": mutate_tabs,
    "double_spaces": mutate_double_spaces,
    "line_break_mid": mutate_line_break_mid,
    "all_caps": mutate_all_caps,
    "lowercase": mutate_lowercase,
    "no_diacritics": mutate_no_diacritics,
    "cyrillic_homoglyph": mutate_cyrillic_homoglyph,
    "nfd": mutate_nfd,
    # red-team round 3
    "nb_hyphen": mutate_nb_hyphen,
    "narrow_nbsp": mutate_narrow_nbsp,
    "surname_caps": mutate_surname_caps,
    "letterspaced": mutate_letterspaced,
    # red-team round 4
    "mojibake_cp1250": mutate_mojibake_cp1250,
}

# Mutations whose loss on a CAPITALISATION-dependent population is inherent rather than a
# defect (see mutate_all_caps / mutate_lowercase). Recorded as data so the gate can ANNOTATE
# a cell — never to exempt one from the threshold. A gate that excuses its own failures is
# not a gate.
CASE_DESTROYING = frozenset({"all_caps", "lowercase"})
