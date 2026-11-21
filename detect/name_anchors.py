"""v1.1 detection engine, layer 1 (CONTRACTS_v11.md §8, C1 round): the four Slovak
NAME ANCHORS — title, role, field-label, bare-name. Text-in, spans-out. No file I/O,
no docx/pdf, no ground truth, no import of corpus/ or eval/.

A missed name is a client's identity in a document that gets filed publicly, and v1 has
no ML (context.md §6 "why no ML in v1"), so recall on names has to come from CONTEXT: the
words a Slovak legal document puts NEXT TO a name. That is what an anchor is. Three of the
four anchors are strong enough to auto-redact; the fourth is a deliberately wide guess that
lands in the unticked review bucket, where a false positive costs a reviewer nothing.

| anchor | fires on | bucket |
|---|---|---|
| 1 title       | ``JUDr.`` / ``Ing. arch.`` / ``prof.`` … + 1-3 Capitalized tokens | auto |
| 2 role        | ``predávajúci`` / ``žalobca`` / … (inflected) + 1-3 Capitalized tokens | auto |
| 3 field label | ``Meno a priezvisko:`` / ``Trvale bytom:`` / … + the rest of the line | auto |
| 4 bare name   | 2-3 Capitalized tokens, not sentence-initial, not stoplisted | REVIEW |

**The anchor word is never inside the emitted span.** Redacting ``JUDr.``, ``predávajúci``
or ``Meno a priezvisko:`` destroys readable text for zero privacy gain — the title, the
role and the label are not PII, only the value after them is. Every pattern therefore
captures the value in a group and the candidate is built from that group's offsets.

Anchor 3 is TYPED BY LABEL, not blindly MENO: ``Trvale bytom:`` introduces an address and
``Obchodné meno:`` an organisation, so emitting MENO for them would mis-file the surface
under the wrong label prefix in the report and in the writer's label map.

``STATNA_PRISLUSNOST`` (from ``Štátna príslušnosť:``) is **not yet in the §4 type registry**
— it is emitted anyway per the governing rule and reported to the orchestrator, which owns
``_TYPE_PRECEDENCE``. Until it is added, detect()'s post-condition 4 would reject it, which
is precisely why this module is not self-wired: `detect/core.py` dispatch is a separate
round.

Stoplists: only the small, hand-written legal/calendar vocabulary below lives here. The
**obce and surname gazetteer stoplists live elsewhere** (``detect/gazetteer_data/*.json``,
applied by ``detect/gazetteer.py``, the C3 round) and are NOT loaded here — this module
imports nothing but ``re``, ``detect.config`` and ``detect.declension``.

Slovak text mixes a normal space with U+00A0 NBSP anywhere a space can appear (Slovak
typography puts an NBSP after ``č.`` and after titles), so every separator below accepts
either. Capitalized tokens are spelled out with explicit Slovak letter classes — a bare
``[A-Z]``/``[a-z]`` would silently drop ``Šimko``, ``Ľubica``, ``Kováčová``.

This module never resolves overlaps against OTHER detector modules (that is core's job,
contract §5). It does resolve ONE overlap internally: a review-bucket bare-name candidate
that overlaps an auto anchored candidate is dropped, because core's `_resolve_flag_survival`
would otherwise let the auto=False verdict win the exact span and silently DOWNGRADE a
title-anchored name into the unticked bucket — a leak dressed up as a resolution rule.
"""
from __future__ import annotations

import re

from .config import DetectConfig
from .core import Candidate
from .declension import fold_length, stem
from .identifiers import ascii_fold, diacritic_pattern, document_is_single_case

NBSP = " "
# v1.1 SEPARATOR WIDENING (red-team round 2, finding R2-1). This class used to be exactly
# a space or an NBSP. That accepted the one spelling the corpus generator writes and
# rejected every other way the same text reaches us: a TAB (a form-style DOCX table cell is
# tab-aligned), TWO SPACES (column padding), or a LINE BREAK (a PDF text layer wraps on
# every page). Measured over 2559 corpus surfaces, a line break in these positions took
# overall detection robustness to 0.113 and CISLO_KLIENTA to 0.000 -- the very type whose
# anchor was widened after it leaked a client number out of a wrapped PDF. That earlier fix
# widened the separator BETWEEN THE WORDS OF AN ANCHOR and not the one between an anchor
# and its VALUE, so a wrap one word later leaked the same number again.
#
# The class below is horizontal whitespace only -- space, NBSP, tab -- with line breaks
# still EXCLUDED, because a separator INSIDE a surface must not join two lines into one
# phone number. Anchor-to-value separators are widened to full whitespace separately.
_SEP = '[^\\S\\n\\r]'

# Capitalized token, per spec: an uppercase Slovak letter followed by lowercase Slovak
# letters. Never a bare [A-Z].
_UP = "A-ZÁÄČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ"
_LO = "a-záäčďéíľĺňóôŕšťúýž"
_CAP = rf"[{_UP}][{_LO}]+"
# CASE (round-2 red-team, R2-5): naively making the anchored NAME group case-insensitive
# regressed real mixed-case documents -- with case no longer marking where the value run
# ENDS (there is no separator-based terminator here, only the token-count cap), a greedy
# run swallows the lowercase ANCHOR WORD sitting right next to it: "vypracoval Ján Novák,
# PhD." matched "vypracoval Ján Novák" as the name, because "vypracoval" now also qualifies
# as a token. So case-insensitivity is gated behind `document_is_single_case`: a genuinely
# all-caps/all-lowercase unit (what the mutation produces) has no capitalisation signal left
# to lose either way, so relaxing there is free; an ordinary mixed-case document keeps the
# exact original, strict (case-sensitive) behaviour, so this never regresses a real document.
# Two full regex sets are precompiled at import time -- STRICT (`_CAP`) and RELAXED
# (`_CAP_CI`) -- and `_anchored` below picks the set once per unit.
_CAP_CI = rf"(?i:[{_UP}][{_LO}]+)"

# SURNAME-CAPS CONVENTION (mutation gate, surname_caps arm): continental legal drafting sets
# a party's SURNAME in full capitals inside an otherwise mixed-case document -- "Ján NOVÁK",
# "NOVÁK Ján", "JUDr. Mária KOVÁČOVÁ". This is a SEPARATE token class from `_CAP`, not a
# relaxation of it, because it is admitted UNCONDITIONALLY (STRICT set, not gated behind
# `document_is_single_case`/`_CAP_CI` the way the whole-document all-caps/all-lowercase
# relaxation is): the document as a whole stays mixed-case here, so the CI relaxation's
# precondition never fires, yet the convention still needs recognising. Widening `_CAP`
# itself to accept caps would swallow real ALL-CAPS HEADINGS ("ZMLUVA", "ČLÁNOK I") into the
# anchored title/role run; keeping it as a separate alternative and relying on `_trim_run`'s
# stoplist (which matches after casefold, so "ZMLUVA"/"zmluva" hit the same stopword either
# way) to cut the run at the first heading/legal-vocabulary token is what keeps that safe.
_CAPS = rf"[{_UP}]{{2,}}"  # all-caps Slovak token, 2+ letters (the caps-SURNAME convention)
_NAME_TOK = rf"(?:{_CAP}|{_CAPS})"
_NAME_SEQ = rf"{_NAME_TOK}(?:{_SEP}{_NAME_TOK}){{0,2}}"
_NAME_SEQ_CI = rf"{_CAP_CI}(?:{_SEP}{_CAP_CI}){{0,2}}"
_TOKEN_RE = re.compile(rf"[^ {NBSP}]+")


# --------------------------------------------------------------------------- STOPLIST
# Hand-written, module-local (see the docstring: the gazetteer stoplists are elsewhere).
# Entries are matched after casefold + fold_length, so only the base spelling is needed;
# common inflections are listed where the stemmer would not reach them.
_STOPWORDS_RAW = (
    # months (nominative + genitive, the form a date actually uses)
    "január", "januára", "február", "februára", "marec", "marca", "apríl", "apríla",
    "máj", "mája", "jún", "júna", "júl", "júla", "august", "augusta",
    "september", "septembra", "október", "októbra", "november", "novembra",
    "december", "decembra",
    # weekdays
    "pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa",
    "pondelka", "utorka", "stredu", "štvrtka", "piatka", "sobotu", "nedeľu",
    # document / legal vocabulary
    "zmluva", "zmluvy", "zmluve", "zmluvu", "zmluvné", "zmluvných", "zmluvná",
    "kúpna", "kúpnej", "darovacia", "darovacej", "nájomná", "nájomnej",
    "strany", "strán", "strana", "stranou",
    "článok", "článku", "odsek", "odseku", "bod", "bodu", "oddiel", "vložka",
    "príloha", "prílohy", "preambula", "ustanovenia", "záverečné", "úvodné",
    "predmet", "predmetu", "účel", "cena", "kúpna cena",
    "list", "listu", "vlastníctva", "vlastníctvo",
    "okresný", "okresného", "krajský", "krajského", "najvyšší", "súd", "súdu", "súde",
    "slovenská", "slovenskej", "slovenská republika", "republika", "republiky",
    "obchodný", "obchodného", "register", "registra", "registri",
    "kataster", "katastrálny", "katastrálne", "územie", "územia",
    "ministerstvo", "úrad", "úradu", "notársky", "notárka", "notár",
    "splnomocnenie", "návrh", "vklad", "vkladu", "rozhodnutie", "uznesenie", "žiadosť",
    "identifikačné", "číslo", "dátum", "podpis", "podpisy", "evidencia",
    "roku", "rok", "dňa", "deň",
    # field-label words — these introduce a value, they are never the value
    "meno", "priezvisko", "trvale", "trvalé", "bytom", "bydlisko", "adresa",
    "sídlo", "sídlom", "zastúpený", "zastúpená", "obchodné", "štátna", "príslušnosť",
)
_STOPWORDS: frozenset[str] = frozenset(fold_length(w.casefold()) for w in _STOPWORDS_RAW)
_STOPSTEMS: frozenset[str] = frozenset(stem(w) for w in _STOPWORDS_RAW if " " not in w)


def _is_stopword(token: str) -> bool:
    folded = fold_length(token.casefold())
    return folded in _STOPWORDS or stem(token) in _STOPSTEMS


# ------------------------------------------------------------------------ 1. TITLES
# Longest-first so that the "Dr" alternative never wins inside "PaedDr."; the (?<!\w)
# guard makes that structural rather than incidental. "arch" is listed as its own token
# so the two-part title "Ing. arch." is just a stacked run.
_TITLE_WORDS = (
    "PaedDr", "PhDr", "RNDr", "MUDr", "MVDr", "ThDr", "JUDr",
    "PhD", "CSc", "Ing", "Mgr", "arch", "prof", "doc", "Bc", "Dr",
)
_TITLE_TOKEN = rf"(?<!\w)(?:{'|'.join(_TITLE_WORDS)})\."
# A run of stacked titles ("prof. JUDr. Ing. arch. "), trailing separator optional so the
# sloppy "JUDr.Ján" form still anchors.
_TITLE_RUN = rf"(?:{_TITLE_TOKEN}{_SEP}*)+"

def _title_leading_re(name_seq: str) -> re.Pattern[str]:
    return re.compile(rf"{_TITLE_RUN}({name_seq})")


def _title_trailing_re(name_seq: str) -> re.Pattern[str]:
    # Trailing academic degree: "Ján Novák, PhD." — the name precedes the title.
    return re.compile(rf"({name_seq}){_SEP}*,?{_SEP}*{_TITLE_TOKEN}")


_TITLE_LEADING_RE = _title_leading_re(_NAME_SEQ)
_TITLE_LEADING_RE_CI = _title_leading_re(_NAME_SEQ_CI)
_TITLE_TRAILING_RE = _title_trailing_re(_NAME_SEQ)
_TITLE_TRAILING_RE_CI = _title_trailing_re(_NAME_SEQ_CI)


# -------------------------------------------------------------------------- 2. ROLES
# Each entry is the INVARIANT PREFIX of a role word plus up to three lowercase letters of
# case ending, so the oblique forms a real document actually uses (predávajúceho,
# žalobcu, kupujúcim, svedka — note the -o- of "svedok" drops) match as well as the
# nominative. Matching only the nominative would miss most real occurrences.
#
# The ending is capped at THREE letters on purpose: four would let "povinn" swallow
# "povinnosti" and "sved" swallow "svedectvo", turning an obligations clause into a
# name anchor. Every genuine ending in the list below is <= 3 letters.
_ROLE_MULTIWORD = (("záložn", "veriteľ"),)  # "záložný veriteľ" / "záložného veriteľa"
_ROLE_STEMS = (
    "prenajímateľ", "splnomocniteľ", "splnomocnen", "navrhovateľ", "obdarovan",
    "predávajúc", "poručiteľ", "oprávnen", "účastník", "zástupc", "kupujúc",
    "žalovan", "konateľ", "veriteľ", "nájomc", "záložc", "žalobc", "odporc",
    "povinn", "dlžník", "dedič", "darc", "sved",
)
_END = rf"[{_LO}]{{0,3}}"
# DIACRITICS (round-2 red-team, R2-2): a role stem is anchor vocabulary, not evidence, so it
# folds via `diacritic_pattern` (technique A -- the anchor sits directly in the primary
# match, so the pattern widens rather than any text being folded; offsets still come off the
# original string untouched).
_ROLE_ALT = "|".join(
    [rf"{diacritic_pattern(a)}{_END}{_SEP}+{diacritic_pattern(b)}{_END}" for a, b in _ROLE_MULTIWORD]
    + [rf"{diacritic_pattern(s)}{_END}" for s in _ROLE_STEMS]
)
# The role word is case-insensitive (documents write "PREDÁVAJÚCI", "Predávajúci",
# "predávajúci"), but the NAME group must stay case-SENSITIVE — a global re.IGNORECASE
# would make [A-Z…] match lowercase words and the Capitalized-token rule would evaporate.
def _role_re(name_seq: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<!\w)(?i:{_ROLE_ALT})(?!\w)"
        rf"{_SEP}*[:,]?{_SEP}*"
        rf"(?:(?i:v){_SEP}+(?i:zastúpení|zastupeni){_SEP}*[:,]?{_SEP}*)?"
        rf"({name_seq})"
    )


_ROLE_RE = _role_re(_NAME_SEQ)
_ROLE_RE_CI = _role_re(_NAME_SEQ_CI)


# ------------------------------------------------------------------- 3. FIELD LABELS
# The value runs to the END OF THE LINE or the end of the table cell — a tab, or a run of
# 2+ spaces (how a DOCX/PDF text layer renders a column gap). Typed by label: emitting
# MENO for "Trvale bytom:" would file an address under a person's label.
_LABEL_TYPES: dict[str, str] = {
    "meno a priezvisko:": "MENO",
    "meno:": "MENO",
    "priezvisko:": "MENO",
    "zastúpený:": "MENO",
    "trvale bytom:": "ADRESA",
    "bydlisko:": "ADRESA",
    "adresa:": "ADRESA",
    "sídlo:": "ADRESA",
    "obchodné meno:": "ORG",
    "štátna príslušnosť:": "STATNA_PRISLUSNOST",
}
# Longest first: "Meno a priezvisko:" must win over the "priezvisko:" it contains, or the
# same value would be emitted twice (finditer resumes after the longer match instead).
# DIACRITICS: the label text itself is anchor vocabulary (folded via diacritic_pattern,
# technique A); the dict lookup below therefore keys on `ascii_fold`, which folds case AND
# diacritics together, rather than the exact literal the old `.casefold()` lookup required.
#
# STATNA_PRISLUSNOST (line_break_mid, break-BETWEEN-words case) is the one two-word label
# here ("štátna príslušnosť:") -- every other label is either one word or already has its
# word-boundary right where the anchor ends. `diacritic_pattern` calls `re.escape` on
# every character it doesn't fold, which turns the literal space between "štátna" and
# "príslušnosť:" into an escaped literal space -- a PDF wrap at that exact space (measured
# at 0.000 robustness) killed the whole anchor. Widened to `\s` for this ONE label only,
# built by hand instead of through the generic `diacritic_pattern(lbl)` path the other
# labels keep; every other label's internal spacing is untouched (out of scope here).
_STATNA_LABEL_RE = rf"{diacritic_pattern('štátna')}\s{diacritic_pattern('príslušnosť:')}"
_LABEL_ALT = "|".join(
    _STATNA_LABEL_RE if lbl == "štátna príslušnosť:" else diacritic_pattern(lbl)
    for lbl in sorted(_LABEL_TYPES, key=len, reverse=True)
)
_LABEL_TYPES_ASCII: dict[str, str] = {ascii_fold(k): v for k, v in _LABEL_TYPES.items()}
_LABEL_RE = re.compile(
    # The gap between label and value may be padding tabs in a table row, so tabs are
    # skipped HERE while still terminating the value below — a leading tab is layout, a
    # trailing one is the cell boundary.
    rf"(?<!\w)((?i:{_LABEL_ALT}))[ {NBSP}\t]*"
    rf"([^\n\r\t]+?)(?=[\n\r\t]|{_SEP}{{2}}|$)"
)


# -------------------------------------------------------------- 4. BARE-NAME (review)
# Uses `_NAME_TOK` (STRICT + caps-SURNAME alternative) so "Ján NOVÁK" / "NOVÁK Ján" anchor
# without a title or role nearby. But a run whose tokens are ALL caps is a HEADING ("KÚPNA
# ZMLUVA", "ČLÁNOK I", "V MENE SLOVENSKEJ REPUBLIKY"), not a name in this convention -- the
# convention is specifically MIXED: one Capitalized given-name token plus one all-caps
# surname token. That all-caps rejection is applied in `_bare_names` below via
# `str.isupper()`, not here, because the check needs the full matched text.
_BARE_RE = re.compile(rf"{_NAME_TOK}(?:{_SEP}{_NAME_TOK}){{1,2}}")
_SENTENCE_ENDERS = ".!?"


def _at_sentence_start(text: str, pos: int) -> bool:
    """True when ``pos`` is the first token of the text, or is preceded (across spaces
    only) by a sentence terminator or a line break."""
    i = pos - 1
    while i >= 0 and text[i] in f" {NBSP}\t":
        i -= 1
    if i < 0:
        return True
    return text[i] in _SENTENCE_ENDERS or text[i] in "\n\r"


# ------------------------------------------------------------------------- assembly
def _cand(type_: str, text: str, start: int, end: int, auto: bool) -> Candidate:
    return Candidate(
        type=type_, surface=text[start:end], start=start, end=end, auto=auto,
        checksum="n/a",
    )


def _trim_run(text: str, start: int, end: int) -> int | None:
    """Truncate an ANCHORED name run at its first stoplist token, returning the new end
    (or None when the run starts with one). ``predávajúci, Trvale bytom: …`` would
    otherwise hand "Trvale" to the role anchor as a person's name and auto-redact a field
    label out of the document."""
    cut = None
    for m in _TOKEN_RE.finditer(text[start:end]):
        if _is_stopword(m.group()):
            cut = start + m.start()
            break
    if cut is None:
        return end
    trimmed = text[start:cut].rstrip(f" {NBSP}")
    return start + len(trimmed) if trimmed else None


def _anchored(text: str) -> list[Candidate]:
    # CASE: pick the STRICT (case-sensitive) or RELAXED (case-insensitive) regex set once
    # per unit. Relaxing is safe here even though the value has no separator-based right
    # boundary of its own, because `_trim_run` below already scans the WHOLE captured run
    # (not just its leading token) and cuts at the first stoplisted word -- so a relaxed
    # run that swallows a following anchor word ("PREDÁVAJÚCI JÁN NOVÁK TRVALE BYTOM..." in
    # a genuinely all-caps party block) is truncated at "TRVALE" before "TRVALE BYTOM" is
    # lost to the ADRESA detector. This is verified by
    # `test_role_all_caps_document_stops_at_address_anchor` in tests/test_detect_name_anchors.py.
    relaxed = document_is_single_case(text)
    regexes = (
        (_TITLE_LEADING_RE_CI, _TITLE_TRAILING_RE_CI, _ROLE_RE_CI)
        if relaxed
        else (_TITLE_LEADING_RE, _TITLE_TRAILING_RE, _ROLE_RE)
    )
    out: list[Candidate] = []
    for regex in regexes:
        for m in regex.finditer(text):
            end = _trim_run(text, m.start(1), m.end(1))
            if end is not None:
                out.append(_cand("MENO", text, m.start(1), end, auto=True))
    for m in _LABEL_RE.finditer(text):
        # The dict key is authored with a single plain space between a label's words, but
        # the STATNA_PRISLUSNOST anchor above can now match with a line break (or a run of
        # any whitespace) there instead -- collapse whatever whitespace the match actually
        # contains down to one space before the lookup, so a wrapped label still resolves
        # to its type instead of raising a KeyError.
        type_ = _LABEL_TYPES_ASCII[ascii_fold(re.sub(r"\s+", " ", m.group(1)))]
        value = m.group(2).rstrip(f" {NBSP}")
        if value:
            out.append(_cand(type_, text, m.start(2), m.start(2) + len(value), auto=True))
    return out


def _bare_names(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for m in _BARE_RE.finditer(text):
        if m.group().isupper():
            # Entirely caps = a heading ("KÚPNA ZMLUVA", "ČLÁNOK I", "V MENE SLOVENSKEJ
            # REPUBLIKY"), not the caps-SURNAME convention -- that convention is always
            # MIXED (a Capitalized token next to an all-caps one). `str.isupper()` is True
            # iff every cased character in the string is uppercase AND at least one cased
            # character exists, which is exactly "no lowercase signal anywhere in this
            # run" -- verified against "Ján NOVÁK" (mixed, False), "NOVÁK Ján" (mixed,
            # False) and "KÚPNA ZMLUVA" (all caps, True).
            continue
        if _at_sentence_start(text, m.start()):
            continue
        if any(_is_stopword(t.group()) for t in _TOKEN_RE.finditer(m.group())):
            continue
        out.append(_cand("MENO", text, m.start(), m.end(), auto=False))
    return out


def detect_name_anchors(text: str, config: DetectConfig) -> list[Candidate]:
    """Four name anchors (CONTRACTS_v11.md §8). ``config`` is accepted for interface
    uniformity across detector modules; neither v1.1 toggle (``strict_checksums``,
    ``redact_all_dates``) affects name anchoring — these types carry no checksum and are
    not dates — so it is deliberately unused here rather than given an invented meaning."""
    anchored = _anchored(text)
    auto_spans = [(c.start, c.end) for c in anchored]
    review = [
        c
        for c in _bare_names(text)
        if not any(c.start < e and s < c.end for s, e in auto_spans)
    ]
    seen: set[tuple[str, int, int]] = set()
    out: list[Candidate] = []
    for c in sorted(anchored + review, key=lambda c: (c.start, c.end)):
        key = (c.type, c.start, c.end)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
