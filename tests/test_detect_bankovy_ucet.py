"""Legacy SK domestic bank account detector (BANKOVY_UCET).

Fixtures are hand-computed from the pinned checksum spec (weighted mod-11,
prefix weights (10,5,8,4,2,1) right-to-left, base weights
(6,3,7,9,10,5,8,4,2,1) right-to-left) -- not imported from corpus/.

  prefix "013389": tail = whole 6-digit string, weights (10,5,8,4,2,1)
      reversed(tail)="983310", reversed(weights)=(1,2,4,8,5,10)
      9*1 + 8*2 + 3*4 + 3*8 + 1*5 + 0*10 = 9+16+12+24+5+0 = 66 -> 66 % 11 == 0 (valid)
  base "1543039117": tail = whole 10-digit string, weights (6,3,7,9,10,5,8,4,2,1)
      reversed(tail)="7119303451", reversed(weights)=(1,2,4,8,5,10,9,7,3,6)
      7*1+1*2+1*4+9*8+3*5+0*10+3*9+4*7+5*3+1*6 = 7+2+4+72+15+0+27+28+15+6 = 176
      -> 176 % 11 == 0 (valid)
  base "1543039118" (last digit bumped 7->8): last term becomes 8*1 instead of 7*1
      -> sum = 177 -> 177 % 11 == 1 (invalid)
  IBAN "SK24 1100 0000 0026 1234 5678": mod-97 hand check -- rearranged
      "11000000002612345678" + "SK24" -> digits "...282024"; stepwise mod-97
      of 11000000002612345678282024 ends at remainder 1 (valid).
"""
from detect.core import detect


def _by_type(candidates, type_):
    return [c for c in candidates if c.type == type_]


def test_valid_account_in_sentence_one_bankovy_ucet_auto_true_no_inner_double_emit():
    account = "013389-1543039117/1100"
    base = "1543039117"
    text = f"Prosím uhraďte sumu na účet {account} do konca mesiaca."
    candidates = detect(text)

    hits = _by_type(candidates, "BANKOVY_UCET")
    assert len(hits) == 1
    c = hits[0]
    assert c.auto is True
    start = text.index(account)
    assert (c.start, c.end) == (start, start + len(account))
    assert c.surface == account

    # the 10-digit base is a sub-span that bare DIC (and slashless RC shape) would
    # otherwise claim -- the full-span account must suppress it, no double-emit
    assert all(x.surface != base for x in candidates)
    assert all(
        not (x.start >= c.start and x.end <= c.end)
        for x in candidates
        if x.type in ("DIC", "RODNE_CISLO")
    )


def test_checksum_broken_base_bankovy_ucet_auto_false():
    account = "013389-1543039118/1100"  # base's last digit broken: 7 -> 8
    text = f"Prosím uhraďte sumu na účet {account} do konca mesiaca."
    candidates = detect(text)

    hits = _by_type(candidates, "BANKOVY_UCET")
    assert len(hits) == 1
    assert hits[0].auto is False
    assert hits[0].surface == account


def test_order_number_decoy_not_matched():
    text = "Obj. č. 123/2019 bola vybavená expresne."
    assert _by_type(detect(text), "BANKOVY_UCET") == []


def test_invoice_number_decoy_not_matched():
    text = "Faktúra č. 2021045 bola uhradená v plnej výške."
    assert _by_type(detect(text), "BANKOVY_UCET") == []


def test_sk_iban_in_same_text_still_iban_never_bankovy_ucet():
    account = "013389-1543039117/1100"
    iban = "SK24 1100 0000 0026 1234 5678"
    text = f"IBAN: {iban} (pôvodný účet {account}) pre úhradu faktúry."
    candidates = detect(text)

    iban_hits = _by_type(candidates, "IBAN")
    assert len(iban_hits) == 1
    assert iban_hits[0].surface == iban
    assert iban_hits[0].auto is True

    ucet_hits = _by_type(candidates, "BANKOVY_UCET")
    assert [c.surface for c in ucet_hits] == [account]
