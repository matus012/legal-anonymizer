"""TDD spec for detect/ round 2a: EMAIL, URL, TELEFON (context.md §4.1).

Fixtures are hand-built literal strings, never derived from data/ or from the corpus
generator (corpus/pii/* is a dev-only fixture generator and must not be imported here
or by detect/ itself). Shapes were read from corpus/pii/email.py, corpus/pii/url.py,
and corpus/pii/phone.py to stay faithful to what the generator actually emits, but
every fixture below is typed out independently.

All three types are shape-only: no checksum exists for any of them, so every match is
Candidate(auto=True). There is no review-bucket path for these three types.
"""
from detect import detect

NBSP = " "


def _find(candidates, type_, surface):
    return [c for c in candidates if c.type == type_ and c.surface == surface]


# --------------------------------------------------------------------------- EMAIL
def test_email_from_name_style_detected():
    text = "Kontakt: jan.novak@gmail.com pre viac informácií."
    hits = _find(detect(text), "EMAIL", "jan.novak@gmail.com")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_email_random_local_style_detected():
    text = "E-mail: qwertzuiop@azet.sk je platný."
    hits = _find(detect(text), "EMAIL", "qwertzuiop@azet.sk")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_email_offsets_correct_against_surrounding_text():
    text = "Kontakt: jan.novak@gmail.com pre viac informácií."
    hits = _find(detect(text), "EMAIL", "jan.novak@gmail.com")
    c = hits[0]
    assert text[c.start : c.end] == "jan.novak@gmail.com"
    assert c.start == text.index("jan.novak@gmail.com")


# --------------------------------------------------------------------------- URL
def test_url_bare_www_style_detected():
    text = "Viac na www.priklad.sk podľa zmluvy."
    hits = _find(detect(text), "URL", "www.priklad.sk")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_https_www_style_detected():
    text = "Viac na https://www.priklad.com podľa zmluvy."
    hits = _find(detect(text), "URL", "https://www.priklad.com")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_http_style_detected():
    text = "Viac na http://priklad.eu podľa zmluvy."
    hits = _find(detect(text), "URL", "http://priklad.eu")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_no_scheme_style_detected():
    text = "Viac na obchodnyweb.sk podľa zmluvy."
    hits = _find(detect(text), "URL", "obchodnyweb.sk")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_no_scheme_eu_detected():
    text = "Viac na firma.eu podľa zmluvy."
    hits = _find(detect(text), "URL", "firma.eu")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_no_scheme_com_detected():
    text = "Viac na stranka.com podľa zmluvy."
    hits = _find(detect(text), "URL", "stranka.com")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_url_offsets_correct_against_surrounding_text():
    text = "Viac na https://www.priklad.com podľa zmluvy."
    hits = _find(detect(text), "URL", "https://www.priklad.com")
    c = hits[0]
    assert text[c.start : c.end] == "https://www.priklad.com"
    assert c.start == text.index("https://www.priklad.com")


# --------------------------------------------------------------------------- TELEFON
def test_telefon_mobile_intl_nbsp_detected():
    text = f"Volajte na +421{NBSP}905{NBSP}123{NBSP}456 kedykoľvek."
    hits = _find(detect(text), "TELEFON", f"+421{NBSP}905{NBSP}123{NBSP}456")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_mobile_intl_space_detected():
    text = "Volajte na +421 905 123 456 kedykoľvek."
    hits = _find(detect(text), "TELEFON", "+421 905 123 456")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_mobile_local_nbsp_detected():
    text = f"Volajte na 0905{NBSP}123{NBSP}456 kedykoľvek."
    hits = _find(detect(text), "TELEFON", f"0905{NBSP}123{NBSP}456")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_mobile_local_space_detected():
    text = "Volajte na 0905 123 456 kedykoľvek."
    hits = _find(detect(text), "TELEFON", "0905 123 456")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_landline_intl_nbsp_detected():
    text = f"Volajte na +421{NBSP}2{NBSP}1234{NBSP}5678 kedykoľvek."
    hits = _find(detect(text), "TELEFON", f"+421{NBSP}2{NBSP}1234{NBSP}5678")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_landline_intl_space_detected():
    text = "Volajte na +421 2 1234 5678 kedykoľvek."
    hits = _find(detect(text), "TELEFON", "+421 2 1234 5678")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_landline_local_nbsp_detected():
    real_nbsp = chr(0xA0)
    text = f"Volajte na 02/160{real_nbsp}946{real_nbsp}679 kedykoľvek."
    hits = _find(detect(text), "TELEFON", f"02/160{real_nbsp}946{real_nbsp}679")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_landline_local_space_detected():
    text = "Volajte na 041/699 564 470 kedykoľvek."
    hits = _find(detect(text), "TELEFON", "041/699 564 470")
    assert len(hits) == 1
    assert hits[0].auto is True


def test_telefon_offsets_correct_against_surrounding_text():
    text = "Volajte na +421 905 123 456 kedykoľvek."
    hits = _find(detect(text), "TELEFON", "+421 905 123 456")
    c = hits[0]
    assert text[c.start : c.end] == "+421 905 123 456"
    assert c.start == text.index("+421 905 123 456")


# ------------------------------------------------------------------------- NEGATIVES
def test_bare_ten_digit_run_yields_no_telefon():
    text = "Číslo záznamu 0903123456 v evidencii."
    assert not any(c.type == "TELEFON" for c in detect(text))


def test_valid_rc_with_slash_yields_no_telefon():
    text = "Narodil sa 850315/0018 v Košiciach."
    assert not any(c.type == "TELEFON" for c in detect(text))


def test_valid_rc_without_slash_yields_no_telefon():
    text = "Rodné číslo 8503150018 uvedené v žiadosti."
    assert not any(c.type == "TELEFON" for c in detect(text))


def test_email_surface_yields_exactly_one_candidate_no_url_inside():
    text = "Kontakt: jan.novak@gmail.com pre viac informácií."
    cands = detect(text)
    start = text.index("jan.novak@gmail.com")
    end = start + len("jan.novak@gmail.com")
    overlapping = [c for c in cands if c.start >= start and c.end <= end]
    assert len(overlapping) == 1
    assert overlapping[0].type == "EMAIL"
    assert overlapping[0].surface == "jan.novak@gmail.com"


def test_filename_mentions_yield_no_url_candidates():
    text = "Priloha priloha.txt a subor dokument.pdf v spise."
    cands = detect(text)
    assert not any(c.type == "URL" for c in cands), cands


def test_bare_filenames_yield_no_url_candidates():
    for text in ("zmluva.docx", "vypis.pdf", "data.json", "obrazok.png"):
        cands = detect(text)
        assert not any(c.type == "URL" for c in cands), (text, cands)


def test_decoy_surfaces_yield_no_contact_candidates():
    decoys = [
        "Faktúra č. 2024017",
        "Obj. č. 123/2024",
        "čl. 12 ods. 3",
        "bod 4.2",
        "Strana 3 z 12",
        "14:35 hod.",
    ]
    for text in decoys:
        cands = detect(text)
        assert not any(c.type in ("EMAIL", "URL", "TELEFON") for c in cands), (text, cands)
