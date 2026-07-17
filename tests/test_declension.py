"""TDD spec for detect/declension.py (context.md §5) — the Slovak declension-matching
engine as a PURE unit.

Governing rule: RECALL over precision. A false positive costs a reviewer two seconds; a
false negative is a data breach. The ONE hard precision line is the discriminator:
possessive declensions of a surname (PII) must match, occupational/demonym ADJECTIVES
derived from the same surname (a different word) must NOT.

Every fixture below is a hand-typed literal. This file does NOT import corpus/ (the corpus
generator is a dev-only fixture factory) nor eval/. The forms were written from Slovak
grammar, not read out of any data file.
"""
from detect.declension import fold_length, match_entity, stem

NBSP = " "

TEMPLATE = "Tu {} tam"  # form sits between two non-matching filler tokens, space-delimited


def _match_form(entity: str, form: str):
    """Return (spans, text, expected_span) for a single-token ``form`` embedded in a sentence."""
    text = TEMPLATE.format(form)
    start = text.index(form)
    return match_entity(text, entity), text, (start, start + len(form))


# ============================================================ fold_length (vowel LENGTH only)
def test_fold_length_folds_long_vowels():
    assert fold_length("áéíóúýĺŕ") == "aeiouylr"


def test_fold_length_preserves_makcen_consonants():
    # c-hacek s-hacek z-hacek d-hacek t-hacek n-hacek l-hacek all stay as-is.
    text = "čšžďťňľ"
    assert fold_length(text) == text


def test_fold_length_preserves_a_umlaut_and_o_circumflex():
    # ae (a-umlaut) and o (o-circumflex) are NOT length marks; they must survive.
    assert fold_length("äô") == "äô"


def test_fold_length_leaves_plain_ascii_untouched():
    assert fold_length("novak") == "novak"


# ================================================================= stem: the discriminator
def test_stem_possessive_declension_equals_bare_surname():
    # Kovacovej (female possessive, a declension of the person) folds to the same stem.
    assert stem("Kováčovej") == stem("Kováč")


def test_stem_occupational_adjective_differs_from_surname():
    # Kovacskej (occupational adjective, a DIFFERENT word) keeps the -sk- infix.
    assert stem("Kováčskej") != stem("Kováč")


def test_stem_encoding_parity_rhythmic_shortening():
    # Rhythmic law: Kosice -> Kosic (gen). Length-folding lets the stems meet.
    assert stem("Košíc") == stem("Košice")


def test_stem_floor_blocks_over_stripping_short_words():
    # Stripping must never leave < 3 chars: "Jan" stays whole.
    assert stem("Ján") == "jan"


# ================================================================= discriminator, end-to-end
def test_discriminator_possessive_matches():
    spans, text, expected = _match_form("Kováč", "Kováčovej")
    assert spans == [expected]


def test_discriminator_occupational_does_not_match():
    text = TEMPLATE.format("Kováčskej")
    assert match_entity(text, "Kováč") == []


# ======================================================================= MUST MATCH tables
MUST_MATCH = {
    "Novák": [
        "Novák", "Nováka", "Novákovi", "Novákom",
        "Novákovci", "Novákovcov",
        "Nováková", "Novákovej", "Novákovú", "Novákovou",
    ],
    "Horváth": [
        "Horváth", "Horvátha", "Horváthovi", "Horváthom",
        "Horváthovci", "Horváthovcov",
        "Horváthová", "Horváthovej",
    ],
    "Košice": [
        "Košice", "Košíc", "Košiciam", "Košiciach", "Košicami",
    ],
    "Levoča": [
        "Levoča", "Levoče", "Levoči", "Levoču", "Levočou",
    ],
    "Bratislava": [
        "Bratislava", "Bratislavy", "Bratislave", "Bratislavu", "Bratislavou",
    ],
}

# "Jan Novak" (full name): first-name declensions must ALSO match.
MUST_MATCH_FULLNAME = {
    "Ján Novák": [
        "Ján", "Jána", "Jánovi", "Jánom",  # first name
        "Novák", "Nováka", "Novákovi", "Novákovci",  # surname still matches
    ],
}


def test_must_match_all_forms_single_entity_word():
    for entity, forms in MUST_MATCH.items():
        for form in forms:
            spans, text, expected = _match_form(entity, form)
            assert spans == [expected], (entity, form, text, spans)


def test_must_match_full_name_including_first_name_cases():
    for entity, forms in MUST_MATCH_FULLNAME.items():
        for form in forms:
            spans, text, expected = _match_form(entity, form)
            assert spans == [expected], (entity, form, text, spans)


# ===================================================================== MUST NOT MATCH tables
# Each entry: (entity, [surfaces that must NOT produce a span]).
MUST_NOT_MATCH = [
    ("Kováč", ["Kováčska", "Kováčskej"]),          # occupational adj
    ("Kučera", ["Kučeravý", "Kučeravej"]),                  # real adjective
    ("Novák", ["Nováčik", "Nováčika"]),                # real noun, palatalised
    ("Horváth", ["Horvátsky", "Horvátskej"]),                    # demonym adj (no 'h')
    ("Hudák", ["Hudácka", "Hudáckej"]),                          # occupational adj
    ("Levoča", ["Levočský"]),                                    # demonym adj
]


def test_must_not_match_single_token_surfaces():
    for entity, surfaces in MUST_NOT_MATCH:
        for surface in surfaces:
            text = TEMPLATE.format(surface)
            assert match_entity(text, entity) == [], (entity, surface, text)


def test_must_not_match_demonym_adjective_phrases():
    # "Kosicky sud", "Kosickeho" — demonym adjective of Kosice, different word.
    for surface in ("Košický súd", "Košického"):
        text = TEMPLATE.format(surface)
        assert match_entity(text, "Košice") == [], (surface, text)


def test_unrelated_capitalised_words_never_match():
    unrelated = ["Kupujúci", "Predávajúci", "Január", "Okresný", "Notársky"]
    for entity in ("Novák", "Košice", "Bratislava"):
        for word in unrelated:
            text = TEMPLATE.format(word)
            assert match_entity(text, entity) == [], (entity, word, text)


# ====================================================================== tokenization details
def test_honorific_nbsp_token_matches_surname_only():
    # "p. Novak" -> the honorific "p." is its own token; only Novak's span is emitted.
    text = f"Bol tam p.{NBSP}Novák dnes."
    spans = match_entity(text, "Novák")
    start = text.index("Novák")
    assert spans == [(start, start + len("Novák"))]
    assert text[spans[0][0] : spans[0][1]] == "Novák"


def test_surrounding_punctuation_is_stripped_from_span():
    text = "Zmluva (Novákovi) platí."
    spans = match_entity(text, "Novák")
    inner = "Novákovi"
    start = text.index(inner)
    assert spans == [(start, start + len(inner))]
    assert text[spans[0][0] : spans[0][1]] == inner


def test_span_offsets_are_exact_against_source_text():
    text = "Rozsudok proti Horváthovi nadobudol právoplatnosť."
    spans = match_entity(text, "Horváth")
    inner = "Horváthovi"
    start = text.index(inner)
    assert spans == [(start, start + len(inner))]
    assert text[spans[0][0] : spans[0][1]] == inner


def test_multiple_occurrences_each_emit_a_span():
    text = "Novák a potom Novákovi a nakoniec Novákom."
    spans = match_entity(text, "Novák")
    assert len(spans) == 3
    for s, e in spans:
        assert stem(text[s:e]) == stem("Novák")


def test_no_match_returns_empty_list():
    text = "Tento text neobsahuje hľadané meno."
    assert match_entity(text, "Novák") == []
