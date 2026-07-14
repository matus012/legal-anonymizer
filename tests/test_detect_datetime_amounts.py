"""TDD spec for detect/ round 2b: DATUM, SUMA (context.md §4.1).

Fixtures are hand-built literal strings, never derived from data/ or from the corpus
generator (corpus/pii/* is a dev-only fixture generator and must not be imported here
or by detect/ itself). Shapes were read from corpus/pii/dates.py, corpus/pii/amounts.py,
and corpus/templates/_common.py (canonical GT type labels) to stay faithful to what the
generator actually emits, but every fixture below is typed out independently.

Both types are shape-only: no checksum exists for either, so every match is
Candidate(auto=True). There is no review-bucket path for these two types.
"""
from detect import detect

NBSP = chr(0xA0)


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


def _overlapping(candidates, start, end):
    return [c for c in candidates if c.start >= start and c.end <= end]


# --------------------------------------------------------------------------- DATUM
def test_datum_dotted_no_leading_zero_detected():
    text = "Zmluva bola podpísaná 1.1.1980 v Bratislave."
    hits = _find(detect(text), "DATUM", "1.1.1980")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_dotted_two_digit_day_month_detected():
    text = "Narodil sa 25.12.1999 minulý rok."
    hits = _find(detect(text), "DATUM", "25.12.1999")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_spaced_plain_space_detected():
    text = "Dátum: 01. 01. 1980 bol stanovený."
    hits = _find(detect(text), "DATUM", "01. 01. 1980")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_spaced_nbsp_detected():
    surface = f"01.{NBSP}01.{NBSP}1980"
    text = f"Dátum: {surface} bol stanovený."
    hits = _find(detect(text), "DATUM", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_iso_detected():
    text = "Platnosť od 1980-01-01 do konca roka."
    hits = _find(detect(text), "DATUM", "1980-01-01")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_words_plain_space_detected():
    text = "Narodený 1. januára 1980 v meste."
    hits = _find(detect(text), "DATUM", "1. januára 1980")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_words_nbsp_detected():
    surface = f"1.{NBSP}januára{NBSP}1980"
    text = f"Narodený {surface} v meste."
    hits = _find(detect(text), "DATUM", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_datum_all_twelve_month_words_detected():
    months = (
        "januára", "februára", "marca", "apríla", "mája", "júna",
        "júla", "augusta", "septembra", "októbra", "novembra", "decembra",
    )
    for month in months:
        surface = f"5. {month} 2010"
        text = f"Dňa {surface} sa konalo."
        hits = _find(detect(text), "DATUM", surface)
        assert len(hits) == 1, (month, detect(text))


def test_datum_offsets_correct_against_surrounding_text():
    text = "Platnosť od 1980-01-01 do konca roka."
    hits = _find(detect(text), "DATUM", "1980-01-01")
    c = hits[0]
    assert text[c.start : c.end] == "1980-01-01"
    assert c.start == text.index("1980-01-01")


# --------------------------------------------------------------------------- SUMA
def test_suma_eur_symbol_plain_space_detected():
    text = "Kúpna cena je 12 345,67 € podľa zmluvy."
    hits = _find(detect(text), "SUMA", "12 345,67 €")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_eur_symbol_nbsp_detected():
    surface = f"12{NBSP}345,67{NBSP}€"
    text = f"Kúpna cena je {surface} podľa zmluvy."
    hits = _find(detect(text), "SUMA", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_eur_word_plain_space_detected():
    text = "Kúpna cena je 12 345,67 EUR podľa zmluvy."
    hits = _find(detect(text), "SUMA", "12 345,67 EUR")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_eur_word_nbsp_detected():
    surface = f"12{NBSP}345,67{NBSP}EUR"
    text = f"Kúpna cena je {surface} podľa zmluvy."
    hits = _find(detect(text), "SUMA", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_dash_cents_plain_space_detected():
    text = "Kúpna cena je 12 345,- € podľa zmluvy."
    hits = _find(detect(text), "SUMA", "12 345,- €")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_dash_cents_nbsp_detected():
    surface = f"12{NBSP}345,-{NBSP}€"
    text = f"Kúpna cena je {surface} podľa zmluvy."
    hits = _find(detect(text), "SUMA", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_sk_legacy_plain_space_detected():
    text = "Historická hodnota 28 500 000 Sk v zmluve."
    hits = _find(detect(text), "SUMA", "28 500 000 Sk")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_sk_legacy_nbsp_detected():
    surface = f"28{NBSP}500{NBSP}000{NBSP}Sk"
    text = f"Historická hodnota {surface} v zmluve."
    hits = _find(detect(text), "SUMA", surface)
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_sub_thousand_no_grouping_separator_detected():
    text = "Doplatok vo výške 567,89 € je splatný."
    hits = _find(detect(text), "SUMA", "567,89 €")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_sk_legacy_seven_digit_detected():
    text = "Pôvodná cena 1 234 567 Sk podľa evidencie."
    hits = _find(detect(text), "SUMA", "1 234 567 Sk")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_suma_offsets_correct_against_surrounding_text():
    text = "Kúpna cena je 12 345,67 € podľa zmluvy."
    hits = _find(detect(text), "SUMA", "12 345,67 €")
    c = hits[0]
    assert text[c.start : c.end] == "12 345,67 €"
    assert c.start == text.index("12 345,67 €")


# ------------------------------------------------------------------------- NEGATIVES
def test_decoy_surfaces_yield_no_datum_or_suma_candidates():
    decoys = [
        "Faktúra č. 2024017",
        "Strana 3 z 12",
        "Obj. č. 123/2024",
        "čl. 12 ods. 3",
        "bod 4.2",
        "14:35 hod.",
    ]
    for text in decoys:
        cands = detect(text)
        assert not any(c.type in ("DATUM", "SUMA") for c in cands), (text, cands)


def test_bare_grouped_number_without_currency_yields_no_suma():
    text = "Súčet položiek: 12 345,67 spolu."
    assert not any(c.type == "SUMA" for c in detect(text))


# ------------------------------------------------------- COLLISION: DATUM/SUMA vs identifiers
def test_datum_iso_span_not_claimed_by_ico_dic_or_rc():
    text = "Platnosť od 1980-01-01 do konca roka."
    cands = detect(text)
    start = text.index("1980-01-01")
    end = start + len("1980-01-01")
    overlapping = _overlapping(cands, start, end)
    assert len(overlapping) == 1
    assert overlapping[0].type == "DATUM"


def test_datum_spaced_span_not_claimed_by_telefon_or_iban():
    text = "Dátum: 01. 01. 1980 bol stanovený."
    cands = detect(text)
    start = text.index("01. 01. 1980")
    end = start + len("01. 01. 1980")
    overlapping = _overlapping(cands, start, end)
    assert len(overlapping) == 1
    assert overlapping[0].type == "DATUM"


def test_suma_sk_legacy_span_not_claimed_by_ico_dic_or_rc():
    text = "Historická hodnota 28 500 000 Sk v zmluve."
    cands = detect(text)
    start = text.index("28 500 000 Sk")
    end = start + len("28 500 000 Sk")
    overlapping = _overlapping(cands, start, end)
    assert len(overlapping) == 1
    assert overlapping[0].type == "SUMA"


def test_suma_eur_symbol_span_not_claimed_by_telefon_or_iban():
    text = "Kúpna cena je 12 345,67 € podľa zmluvy."
    cands = detect(text)
    start = text.index("12 345,67 €")
    end = start + len("12 345,67 €")
    overlapping = _overlapping(cands, start, end)
    assert len(overlapping) == 1
    assert overlapping[0].type == "SUMA"


def test_valid_rc_yields_no_datum_or_suma():
    text = "Narodil sa 850315/0018 v Košiciach."
    cands = detect(text)
    assert not any(c.type in ("DATUM", "SUMA") for c in cands)


def test_valid_ico_yields_no_datum_or_suma():
    text = "IČO spoločnosti je 47123456 podľa výpisu."
    cands = detect(text)
    assert not any(c.type in ("DATUM", "SUMA") for c in cands)


def test_valid_dic_yields_no_datum_or_suma():
    text = "DIČ je 1234567890 podľa výpisu."
    cands = detect(text)
    assert not any(c.type in ("DATUM", "SUMA") for c in cands)


def test_valid_iban_yields_no_datum_or_suma():
    text = "Účet SK6807200002891987426353 je aktívny."
    cands = detect(text)
    assert not any(c.type in ("DATUM", "SUMA") for c in cands)


def test_valid_telefon_yields_no_datum_or_suma():
    text = "Volajte na +421 905 123 456 kedykoľvek."
    cands = detect(text)
    assert not any(c.type in ("DATUM", "SUMA") for c in cands)
