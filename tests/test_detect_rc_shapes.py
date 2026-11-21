"""TDD spec for CONTRACTS_v11.md §6a — the RODNE_CISLO shape rules (v1.1 bug A2).

One test per clause of §6a. Fixtures are hand-built literal strings; corpus/ is never
imported here (CONTRACTS_v11.md §11).

Pinned checksum arithmetic (computed from the spec, not from corpus/pii):
    8503150018 % 11 == 0   -> 10-digit form, checksum "valid"
    8503150019 % 11 == 8   -> 10-digit form, checksum "invalid"
    850315001              -> 9-digit pre-1954 form, NO checksum exists at all

The §6a clauses under test:
  1. 10-digit YYMMDD/XXXX      -> mod-11 applies, checksum "valid" / "invalid"
  2. 9-digit  YYMMDD/XXX       -> NO checksum, always checksum="n/a", always auto=True
  3. separators: '/', space, NBSP (U+00A0), or nothing
  4. internal space/NBSP inside either digit group is accepted AND part of the surface
  5. the separator-less (contiguous) form matches ONLY with an RC context anchor
     (r.č. / rč / rodné číslo / rodného čísla / nar.) within 40 chars before it;
     without an anchor a bare digit run stays owned by DIC exactly as in v1
  6. month-offset (+0/+20/+50/+70) and day 1..31 shape checks apply to BOTH lengths
"""
from detect.config import DetectConfig
from detect.core import detect

NBSP = " "
STRICT = DetectConfig(strict_checksums=True)


def _rc(text, config=None):
    return [c for c in detect(text, None, config) if c.type == "RODNE_CISLO"]


def _only(text, config=None):
    hits = _rc(text, config)
    assert len(hits) == 1, (text, detect(text, None, config))
    return hits[0]


# ------------------------------------------------------------------ 10-digit, slash
def test_10digit_slash_valid_checksum():
    c = _only("Narodil sa 850315/0018 v Košiciach.")
    assert c.surface == "850315/0018"
    assert c.auto is True
    assert c.checksum == "valid"


def test_10digit_slash_invalid_checksum_default_auto_true_tagged_invalid():
    c = _only("Narodil sa 850315/0019 v Košiciach.")
    assert c.surface == "850315/0019"
    assert c.auto is True
    assert c.checksum == "invalid"


def test_10digit_slash_invalid_checksum_strict_auto_false_still_tagged():
    c = _only("Narodil sa 850315/0019 v Košiciach.", STRICT)
    assert c.auto is False
    assert c.checksum == "invalid"


def test_10digit_nbsp_separator():
    c = _only(f"Narodil sa 850315{NBSP}0018 v Košiciach.")
    assert c.surface == f"850315{NBSP}0018"
    assert c.auto is True
    assert c.checksum == "valid"


def test_10digit_space_separator():
    c = _only("Narodil sa 850315 0018 v Košiciach.")
    assert c.surface == "850315 0018"
    assert c.checksum == "valid"


# ------------------------------------------------------------------- 9-digit (no checksum)
def test_9digit_slash_detected_no_checksum():
    c = _only("Kód 850315/001 je staré rodné číslo.")
    assert c.surface == "850315/001"
    assert c.auto is True
    assert c.checksum == "n/a"


def test_9digit_space_separator():
    c = _only("Kód 850315 001 je staré rodné číslo.")
    assert c.surface == "850315 001"
    assert c.auto is True
    assert c.checksum == "n/a"


def test_9digit_nbsp_separator():
    c = _only(f"Kód 850315{NBSP}001 je staré rodné číslo.")
    assert c.surface == f"850315{NBSP}001"
    assert c.auto is True
    assert c.checksum == "n/a"


def test_9digit_never_tagged_invalid_whatever_the_digits():
    # mod-11 must never be applied to the 9-digit form: every tail is legitimate.
    for tail in ("000", "001", "002", "123", "999"):
        c = _only(f"r.č. 850315/{tail}")
        assert c.checksum == "n/a", tail
        assert c.auto is True, tail


def test_9digit_strict_checksums_still_auto_true():
    # strict_checksums only gates types that HAVE a checksum; the 9-digit RC has none.
    c = _only("Kód 850315/001 je staré rodné číslo.", STRICT)
    assert c.auto is True
    assert c.checksum == "n/a"


# ------------------------------------------------------- internal whitespace in the groups
def test_internal_space_in_date_group_is_part_of_surface():
    c = _only("Narodil sa 850 315/0018 v Košiciach.")
    assert c.surface == "850 315/0018"
    assert c.checksum == "valid"


def test_internal_space_in_tail_group_is_part_of_surface():
    c = _only("Narodil sa 850315/00 18 v Košiciach.")
    assert c.surface == "850315/00 18"
    assert c.checksum == "valid"


def test_internal_nbsp_in_tail_group_is_part_of_surface():
    c = _only(f"Narodil sa 850315/00{NBSP}18 v Košiciach.")
    assert c.surface == f"850315/00{NBSP}18"
    assert c.checksum == "valid"


# ------------------------------------------------------------- contiguous form + anchors
def test_contiguous_10digit_with_dotted_anchor():
    c = _only("r.č. 8503150018 uvedené v žiadosti.")
    assert c.surface == "8503150018"
    assert c.auto is True
    assert c.checksum == "valid"


def test_contiguous_10digit_with_bare_rc_anchor():
    c = _only("rč 8503150018 uvedené v žiadosti.")
    assert c.surface == "8503150018"
    assert c.checksum == "valid"


def test_contiguous_10digit_with_spelled_anchor():
    c = _only("Rodné číslo 8503150018 uvedené v žiadosti.")
    assert c.surface == "8503150018"
    assert c.checksum == "valid"


def test_contiguous_10digit_with_genitive_spelled_anchor():
    c = _only("Podľa rodného čísla 8503150018 v žiadosti.")
    assert c.surface == "8503150018"


def test_contiguous_10digit_with_nar_anchor():
    c = _only("nar. 8503150018 v Košiciach.")
    assert c.surface == "8503150018"


def test_contiguous_9digit_with_anchor():
    c = _only("r.č. 850315001 v žiadosti.")
    assert c.surface == "850315001"
    assert c.auto is True
    assert c.checksum == "n/a"


def test_contiguous_invalid_checksum_anchored_default_auto_true_strict_false():
    default = _only("r.č. 8503150019 v žiadosti.")
    assert default.auto is True
    assert default.checksum == "invalid"
    strict = _only("r.č. 8503150019 v žiadosti.", STRICT)
    assert strict.auto is False
    assert strict.checksum == "invalid"


def test_anchor_beyond_40_chars_does_not_arm_the_contiguous_form():
    prefix = "rodné číslo" + "x" * 45 + " "
    text = prefix + "8503150018 v žiadosti."
    assert _rc(text) == []


# --------------------------------------------- no anchor -> bare digit run stays a DIC (v1)
def test_contiguous_10digit_without_anchor_is_dic_not_rc():
    text = "Ďalšie údaje: 2805200615"
    start = text.index("2805200615")
    cands = [c for c in detect(text) if (c.start, c.end) == (start, start + 10)]
    assert len(cands) == 1
    assert cands[0].type == "DIC"
    assert cands[0].auto is True
    assert _rc(text) == []


def test_contiguous_9digit_without_anchor_not_detected_at_all():
    text = "Kód 850315001 je v spise."
    assert _rc(text) == []
    assert not any(c.type == "DIC" for c in detect(text))  # DIC needs exactly 10 digits


# ------------------------------------------------------------------- shape checks (both lengths)
def test_impossible_month_rejected_10digit():
    assert _rc("r.č. 853415/0010") == []  # month 34 -> no plausible +0/+20/+50/+70 offset


def test_impossible_month_rejected_9digit():
    assert _rc("r.č. 853415/001") == []


def test_impossible_day_rejected_9digit():
    assert _rc("r.č. 850332/001") == []  # day 32


def test_female_plus_50_month_offset_accepted_9digit():
    c = _only("r.č. 855315/001")  # month 53 -> 53-50 = 3
    assert c.checksum == "n/a"


def test_post_2004_plus_70_month_offset_accepted_9digit():
    c = _only("r.č. 857315/001")  # month 73 -> 73-70 = 3
    assert c.checksum == "n/a"


# ------------------------------------------------------------------- offsets stay exact
def test_offsets_index_back_into_the_source_text():
    text = f"Narodil sa 850315/00{NBSP}18 v Košiciach."
    c = _only(text)
    assert text[c.start : c.end] == c.surface
