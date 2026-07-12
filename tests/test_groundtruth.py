"""Generation-time invariants for corpus.groundtruth.Recorder (context.md rejection round 8).

A decoy surface that EQUALS a real (auto_redact or should_flag) surface in the same document
is a corpus-generation defect, not a valid fixture: eval.leak's exclusion is keyed on exact
span containment, so an equal-length decoy silently suppresses every occurrence of that
string, blinding the leak gate to a real leak (see eval/leak.py, tests/test_leak.py). This
must be a hard failure at generation time, never a silent pass into a written ground-truth
file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from corpus.groundtruth import PiiSpec, Recorder


def _recorder_with(*specs: PiiSpec) -> Recorder:
    rec = Recorder("x.docx", "zaloba", 1)
    for spec in specs:
        rec.record(spec, part="body")
    return rec


def test_decoy_surface_equal_to_auto_redact_surface_is_a_hard_failure(tmp_path: Path):
    rec = _recorder_with(
        PiiSpec(surface="Jan Novak", type="MENO", auto_redact=True, should_flag=False),
        PiiSpec(surface="Jan Novak", type="CAPITALISED_COMMON", auto_redact=False, should_flag=False),
    )
    with pytest.raises(ValueError, match="Jan Novak"):
        rec.write(tmp_path / "x.docx.gt.json")


def test_decoy_surface_equal_to_should_flag_surface_is_a_hard_failure(tmp_path: Path):
    rec = _recorder_with(
        PiiSpec(surface="123456/7890", type="RODNE_CISLO", auto_redact=False, should_flag=True),
        PiiSpec(surface="123456/7890", type="INVOICE_NO", auto_redact=False, should_flag=False),
    )
    with pytest.raises(ValueError, match="123456/7890"):
        rec.write(tmp_path / "x.docx.gt.json")


def test_no_collision_writes_successfully(tmp_path: Path):
    rec = _recorder_with(
        PiiSpec(surface="Jan Novak", type="MENO", auto_redact=True, should_flag=False),
        PiiSpec(surface="Kováčska dielňa", type="CAPITALISED_COMMON", auto_redact=False, should_flag=False),
    )
    out = tmp_path / "x.docx.gt.json"
    rec.write(out)
    assert out.exists()


def test_decoy_that_merely_contains_an_auto_redact_surface_as_a_substring_is_not_flagged(tmp_path: Path):
    # The Kováč / "Kováčska dielňa" case (context.md rejection round 7) is intentional and
    # must remain allowed: the assertion is EQUALITY only, never substring containment.
    rec = _recorder_with(
        PiiSpec(surface="Kováč", type="MENO", auto_redact=True, should_flag=False),
        PiiSpec(surface="Kováčska dielňa", type="CAPITALISED_COMMON", auto_redact=False, should_flag=False),
    )
    out = tmp_path / "x.docx.gt.json"
    rec.write(out)
    assert out.exists()
