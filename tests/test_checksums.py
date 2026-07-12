"""TDD spec for the deterministic PII checksum generators (context.md §4.1).

The governing requirement: a *valid* generated identifier must pass its checksum, and a
*deliberately-invalid* one must fail it. Where possible each algorithm is anchored to a
real, published identifier so we catch an algorithm that is wrong-but-self-consistent.
"""
import random

from corpus.pii import rodne_cislo, ico, iban


def rng():
    return random.Random(1234)


# --------------------------------------------------------------------------- rodné číslo
def test_rodne_cislo_valid_passes_mod11():
    r = rng()
    for _ in range(200):
        assert rodne_cislo.is_valid(rodne_cislo.generate(r, valid=True))


def test_rodne_cislo_invalid_fails_mod11():
    r = rng()
    for _ in range(200):
        assert not rodne_cislo.is_valid(rodne_cislo.generate(r, valid=False))


def test_rodne_cislo_invalid_is_still_shaped_like_rc():
    # A checksum-invalid RČ must still LOOK like a RČ (10 digits, plausible date) so the
    # detector is forced to flag it for review rather than ignore it (§6).
    r = rng()
    s = rodne_cislo.generate(r, valid=False)
    assert rodne_cislo.is_rc_shaped(s)


def test_rodne_cislo_female_month_offset():
    r = rng()
    s = rodne_cislo.generate(r, female=True, valid=True)
    digits = "".join(c for c in s if c.isdigit())
    month = int(digits[2:4])
    assert 51 <= month <= 62 or 71 <= month <= 82  # +50 (or +70 post-2004 women)


# --------------------------------------------------------------------------- IČO
def test_ico_known_real_value_validates():
    # Slovak Telekom, a real published IČO — anchors the weighted-checksum algorithm.
    assert ico.is_valid("35763469")


def test_ico_valid_passes():
    r = rng()
    for _ in range(200):
        assert ico.is_valid(ico.generate(r, valid=True))


def test_ico_invalid_fails():
    r = rng()
    for _ in range(200):
        assert not ico.is_valid(ico.generate(r, valid=False))


def test_ico_is_eight_digits():
    r = rng()
    assert len(ico.generate(r, valid=True)) == 8


# --------------------------------------------------------------------------- IBAN
def test_iban_mod97_anchor():
    # Canonical ISO 13616 example — anchors the mod-97 core independent of SK generation.
    assert iban._mod97("GB82WEST12345698765432") == 1


def test_iban_valid_passes():
    r = rng()
    for _ in range(200):
        v = iban.generate(r, valid=True)
        assert iban.is_valid(v), v


def test_iban_invalid_fails():
    r = rng()
    for _ in range(200):
        assert not iban.is_valid(iban.generate(r, valid=False))


def test_iban_is_sk_24_chars():
    r = rng()
    v = iban.generate(r, valid=True).replace(" ", "")
    assert v.startswith("SK") and len(v) == 24


# --------------------------------------------------------------------------- legacy account
def test_legacy_account_valid_passes():
    r = rng()
    for _ in range(100):
        assert iban.is_valid_domestic(iban.generate_domestic(r, valid=True))


def test_legacy_account_invalid_fails():
    r = rng()
    for _ in range(100):
        assert not iban.is_valid_domestic(iban.generate_domestic(r, valid=False))
