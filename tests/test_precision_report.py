"""Tests for eval/precision_report.py (Phase E gate 1, REPORT ONLY)."""
from __future__ import annotations

from pathlib import Path

from eval.precision_report import TypeTally, _gt_type_spans, _overlaps, main, measure


def test_overlaps():
    assert _overlaps(0, 5, 3, 8)
    assert _overlaps(3, 8, 0, 5)
    assert not _overlaps(0, 5, 5, 10)     # touching, not overlapping
    assert not _overlaps(0, 5, 6, 10)


def test_gt_type_spans_finds_every_occurrence_by_type():
    unit = "IBAN SK31 tu, znova IBAN SK31 tu, a MENO Novak"
    rows = [
        {"type": "IBAN", "surface": "SK31"},
        {"type": "MENO", "surface": "Novak"},
    ]
    spans = _gt_type_spans(unit, rows)
    assert len(spans["IBAN"]) == 2
    assert len(spans["MENO"]) == 1
    for start, end in spans["IBAN"]:
        assert unit[start:end] == "SK31"


def test_type_tally_precision_is_none_with_zero_candidates():
    assert TypeTally().precision is None


def test_type_tally_precision_ratio():
    t = TypeTally(candidates=4, backed=3)
    assert t.precision == 0.75


def test_measure_never_raises_and_reports_skips(tmp_path: Path):
    """No .docx corpus at all: measure() must return cleanly (this module never gates, so it
    must not be the thing that crashes a run)."""
    tallies, skipped, measured = measure(tmp_path)
    assert tallies == {}
    assert skipped == []
    assert measured == 0


def test_main_never_fails_the_build():
    """REPORT ONLY per CONTRACTS_v11.md: this module's main() always exits 0, whatever the
    numbers are — even against the real corpus, where per-type precision is genuinely low
    for OBEC/KATASTER (gazetteer over-matching, documented in context.md §6)."""
    assert main() == 0
