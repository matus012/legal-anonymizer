"""RedactionDecisions + LabelMap snippet/grouping extensions (Phase 6).

Hand-built candidates only — tests never import corpus/ or eval/.
"""
from types import SimpleNamespace

from writer.decisions import RedactionDecisions
from writer.labelmap import LabelMap, make_snippet


def _cand(type_, surface, start=0, end=None, auto=True):
    return SimpleNamespace(
        type=type_, surface=surface, start=start,
        end=(end if end is not None else start + len(surface)), auto=auto,
    )


def test_decisions_defaults_are_empty_and_frozen():
    d = RedactionDecisions()
    assert d.extra_terms == ()
    assert d.suppress_groups == frozenset()
    assert d.force_groups == frozenset()
    try:
        d.extra_terms = ("x",)
        assert False, "must be frozen"
    except Exception:
        pass


def test_group_key_for_matches_group_key():
    lm = LabelMap(["Ján Novák"])
    c = _cand("MENO", "Nováka")
    assert lm.group_key_for(c.type, c.surface) == lm.group_key(c)
    c2 = _cand("DIC", "1234567890")
    assert lm.group_key_for("DIC", "1234567890") == lm.group_key(c2)


def test_groups_inverts_the_cache():
    lm = LabelMap(None)
    c = _cand("DIC", "1234567890")
    label = lm.label_for(c)
    assert lm.groups() == {label: ("DIC", lm.group_key(c))}


def test_record_occurrence_keeps_first_snippet_only():
    lm = LabelMap(None)
    lm.record_occurrence("[DIC_1]", "body", "123", snippet="first ctx")
    lm.record_occurrence("[DIC_1]", "header", "123", snippet="second ctx")
    assert lm.contexts["[DIC_1]"] == "first ctx"
    assert lm.occurrences["[DIC_1]"] == [("body", "123"), ("header", "123")]  # shape UNCHANGED


def test_record_low_confidence_snippets_stay_aligned():
    lm = LabelMap(None)
    lm.record_low_confidence("body", "RODNE_CISLO", "835112/0009", snippet="ctx a")
    lm.record_low_confidence("page_2", "ICO", "12345678")  # no snippet -> "" placeholder
    assert lm.low_confidence == [("body", "RODNE_CISLO", "835112/0009"), ("page_2", "ICO", "12345678")]
    assert lm.lc_contexts == ["ctx a", ""]


def test_make_snippet_windows_and_collapses_whitespace():
    text = "aaaa    bbbb  NEEDLE\n\ncccc dddd"
    s = make_snippet(text, text.index("NEEDLE"), text.index("NEEDLE") + 6, radius=6)
    assert "NEEDLE" in s
    assert "\n" not in s and "  " not in s
