"""W5a (context.md §10): per-entity consistent, document-global redaction labels.

Hand-built Candidate objects + known_entities lists ONLY — no docx, no corpus/, no eval/.
These pin the grouping contract of writer.labelmap.LabelMap:

  * the SAME entity (across declensions) shares one number,
  * DIFFERENT entities get different numbers,
  * numeric/other types group by whitespace-stripped casefolded surface,
  * NBSP (U+00A0) is stripped exactly like an ASCII space so spaced/glued/NBSP variants
    of one identifier share a label.

RED-vs-GREEN: a naive per-call incrementer (no grouping) mints _1 then _2 for a single
group, so R1/R3/R4 FAIL against it; only the grouping implementation makes them pass.
"""
from __future__ import annotations

from detect.core import Candidate
from writer.labelmap import LabelMap, normalize


def _c(type_: str, surface: str) -> Candidate:
    return Candidate(type=type_, surface=surface, start=0, end=len(surface), auto=True)


def test_r1_meno_same_entity_shares_number() -> None:
    """R1: one entity, two declensions -> the same [MENO_1]."""
    lm = LabelMap(["Ján Novák"])
    assert lm.label_for(_c("MENO", "Novák")) == "[MENO_1]"
    assert lm.label_for(_c("MENO", "Nováka")) == "[MENO_1]"


def test_r2_meno_two_entities_get_distinct_numbers() -> None:
    """R2: two entities (sharing only the first name) -> distinct numbers by surname."""
    lm = LabelMap(["Ján Novák", "Ján Horák"])
    assert lm.label_for(_c("MENO", "Novák")) == "[MENO_1]"
    assert lm.label_for(_c("MENO", "Horák")) == "[MENO_2]"


def test_r3_numeric_same_surface_shares_number() -> None:
    """R3: identical RODNE_CISLO surface -> the same [RODNE_CISLO_1]."""
    lm = LabelMap([])
    assert lm.label_for(_c("RODNE_CISLO", "850101/1234")) == "[RODNE_CISLO_1]"
    assert lm.label_for(_c("RODNE_CISLO", "850101/1234")) == "[RODNE_CISLO_1]"


def test_r4_nbsp_and_space_normalize_together() -> None:
    """R4: '0911 402 917' and '0911\\u00a0402\\u00a0917' are one group (NBSP stripped)."""
    lm = LabelMap([])
    a = lm.label_for(_c("TELEFON", "0911 402 917"))
    b = lm.label_for(_c("TELEFON", "0911 402 917"))
    assert a == b == "[TELEFON_1]"


def test_r5_numeric_distinct_surfaces_get_distinct_numbers() -> None:
    """R5: two different RODNE_CISLO surfaces -> _1 then _2."""
    lm = LabelMap([])
    assert lm.label_for(_c("RODNE_CISLO", "850101/1234")) == "[RODNE_CISLO_1]"
    assert lm.label_for(_c("RODNE_CISLO", "900202/5678")) == "[RODNE_CISLO_2]"


def test_normalize_strips_all_whitespace_including_nbsp() -> None:
    assert normalize("0911 402 917") == "0911402917"
    assert normalize("0911 402 917") == "0911402917"
    assert normalize("  A B\tC\n") == "abc"


def test_counters_are_independent_per_type() -> None:
    lm = LabelMap([])
    assert lm.label_for(_c("RODNE_CISLO", "850101/1234")) == "[RODNE_CISLO_1]"
    assert lm.label_for(_c("TELEFON", "0911 402 917")) == "[TELEFON_1]"
    assert lm.label_for(_c("RODNE_CISLO", "900202/5678")) == "[RODNE_CISLO_2]"


def test_meno_unknown_entity_falls_back_to_surface_group() -> None:
    """Defensive fallback: a MENO matching NO known entity groups by normalized surface, so
    an identical surface repeats one label while a distinct surface gets a fresh number."""
    lm = LabelMap(["Ján Novák"])  # neither surface below stems to Novák
    assert lm.label_for(_c("MENO", "Kováč")) == "[MENO_1]"
    assert lm.label_for(_c("MENO", "Kováč")) == "[MENO_1]"
    assert lm.label_for(_c("MENO", "Molnár")) == "[MENO_2]"
