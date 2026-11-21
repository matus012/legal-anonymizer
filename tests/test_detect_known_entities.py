"""Known-entities layer wired into detect() (context.md §4.3, §6).

Hand-built fixtures ONLY -- this file must not import corpus/. The surface literals below
(canonical name, four renderings, the six male case forms, female forms, family plural, and
the Kovac/Kovacska discriminator) are transcribed from the pinned surface spec, not derived
at runtime. NBSP is written as the \\u00a0 escape so the source stays ASCII-clean.
"""
from detect.config import DetectConfig
from detect.core import detect


# --------------------------------------------------------------------------- helpers
def _meno(text: str, known_entities: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, surface) for every MENO candidate detect() emits."""
    return [
        (c.start, c.end, c.surface)
        for c in detect(text, known_entities)
        if c.type == "MENO"
    ]


def _meno_surfaces(text: str, known_entities: list[str]) -> list[str]:
    return [s for _st, _e, s in _meno(text, known_entities)]


def _meno_covers(text: str, known_entities: list[str], needle: str) -> bool:
    """Is ``needle`` inside SOME MENO span?

    v1 emitted one MENO per matched TOKEN, so a full name produced two candidates and a test
    could assert the bare surname was among the surfaces. v1.1's name detectors emit the WHOLE
    name as a single wider span ("Jan Novak" rather than "Jan" + "Novak"), and detect.core's
    containment resolver then drops the narrower token candidates inside it -- deliberately,
    because the writers slice by character offsets and overlapping spans corrupt the output.

    The REDACTION is identical either way: the wider span covers strictly more text. What
    changed is only how many Candidate objects say so. These tests care that the surname is
    redacted, so they now assert COVERAGE rather than an exact surface list."""
    return any(needle in surface for surface in _meno_surfaces(text, known_entities))


# --------------------------------------------------------------------------- fixtures
CANONICAL = "Ján Novák"  # "Ján Novák"


# --------------------------------------------------------------------------- T1
def test_t1_four_renderings_flag_surname():
    renderings = [
        "Ján Novák",       # canonical
        "J. Novák",             # initial (regular space after dot)
        "Novák",                # bare surname
        "p.\u00a0Novák",        # honorific (literal NBSP after "p.")
    ]
    for t in renderings:
        assert _meno_covers(t, [CANONICAL], "Novák"), (t, _meno_surfaces(t, [CANONICAL]))


# --------------------------------------------------------------------------- T2
def test_t2_six_male_surname_cases():
    # nom gen dat acc loc ins
    cases = ["Novák", "Nováka", "Novákovi", "Nováka",
             "Novákovi", "Novákom"]
    for form in cases:
        assert _meno_covers(form, [CANONICAL], form), (form, _meno_surfaces(form, [CANONICAL]))
    # full dative example: the whole name is covered by MENO span(s)
    assert _meno_covers("Jánovi Novákovi", [CANONICAL], "Novákovi"), _meno_surfaces(
        "Jánovi Novákovi", [CANONICAL]
    )


# --------------------------------------------------------------------------- T3
def test_t3_female_forms():
    entity = "Mária Nováková"  # "Mária Nováková"
    for form in ["Nováková", "Novákovej", "Novákovú",
                 "Novákovou"]:
        surfaces = _meno_surfaces(form, [entity])
        assert form in surfaces, (form, surfaces)


# --------------------------------------------------------------------------- T4
def test_t4_family_plural():
    for form in ["Novákovci", "Novákovcov"]:
        surfaces = _meno_surfaces(form, [CANONICAL])
        assert form in surfaces, (form, surfaces)


# --------------------------------------------------------------------------- T5
def test_t5_discriminator_negative():
    # "Kováčska dielňa" with known entity "Ján Kováč": the -sk- adjective must NOT flag.
    surfaces = _meno_surfaces("Kováčska dielňa", ["Ján Kováč"])
    assert surfaces == [], surfaces


# --------------------------------------------------------------------------- T6
def test_t6_collision_valid_ico_wins():
    # 12345679: checksum-valid ICO (weights 8,7,6,5,4,3,2 -> sum 112, 112%11=2, check 9).
    ico = "12345679"
    cands = detect(ico, [ico])
    span = [c for c in cands if (c.start, c.end) == (0, len(ico))]
    assert len(span) == 1, cands
    assert span[0].type == "ICO", span[0]
    assert span[0].auto is True, span[0]
    assert not any(c.type == "MENO" for c in cands), cands


def test_t6_collision_invalid_ico_flag_survival_drops_meno():
    # 12345670: same shape, checksum-INVALID (check digit should be 9, not 0).
    # The ORIGINAL intent of this test is the COLLISION rule: an ICO span that survives as
    # auto=False must still displace the MENO the known-entity detector would emit on the same
    # digits. Producing an auto=False identifier now requires strict_checksums=True
    # (CONTRACTS_v11.md §6) — that config, not a weakened assertion, is what preserves it.
    ico = "12345670"
    cands = detect(ico, [ico], DetectConfig(strict_checksums=True))
    span = [c for c in cands if (c.start, c.end) == (0, len(ico))]
    assert len(span) == 1, cands
    assert span[0].type == "ICO", span[0]
    assert span[0].auto is False, span[0]          # flagged, survives
    assert span[0].checksum == "invalid", span[0]
    assert not any(c.type == "MENO" for c in cands), cands


def test_t6_default_config_auto_redacts_the_invalid_ico_and_still_drops_meno():
    """v1.1 policy A1 sibling: under the DEFAULT config the SAME surface is auto-redacted and
    merely TAGGED checksum="invalid" — the collision rule is unaffected by the tag."""
    ico = "12345670"
    cands = detect(ico, [ico])
    span = [c for c in cands if (c.start, c.end) == (0, len(ico))]
    assert len(span) == 1, cands
    assert span[0].type == "ICO", span[0]
    assert span[0].auto is True, span[0]           # auto-redacted now, not routed to review
    assert span[0].checksum == "invalid", span[0]
    assert not any(c.type == "MENO" for c in cands), cands


# --------------------------------------------------------------------------- T7
def test_t7_caller_safety_no_second_arg():
    # default None path: no known entities -> no MENO, no crash.
    cands = detect("Novák býva v Košiciach.")
    assert all(c.type != "MENO" for c in cands), cands


# --------------------------------------------------------------------------- T8
def test_t8_multi_entity_dedup():
    # Two entities share the "Novák" token; each occurrence must yield exactly one span.
    spans = [(st, e) for st, e, _s in _meno("Novák Novák",
                                            [CANONICAL, "Novák"])]
    assert len(spans) == len(set(spans)), spans           # no duplicate span
    assert len(spans) == 2, spans                         # one per occurrence
