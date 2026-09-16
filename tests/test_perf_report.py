"""Tests for eval/perf_report.py (Phase E gate 3, REPORT ONLY).

The module's real workload (~300 docx paragraphs, ~500 pdf pages) is deliberately large — it
exists to produce a meaningful wall-time/memory number, not to run in the unit test loop. This
test exercises the SAME code path at a tiny size (monkeypatched constants) so the wiring
(generation -> redaction -> tracemalloc measurement -> cleanup) is proven without the runtime
cost.
"""
from __future__ import annotations

from pathlib import Path

import eval.perf_report as perf_report


def test_run_at_small_scale(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(perf_report, "_SCRATCH", tmp_path)
    monkeypatch.setattr(perf_report, "_DOCX_PARAGRAPHS", 3)
    monkeypatch.setattr(perf_report, "_PDF_TARGET_PAGES", 1)

    assert perf_report.run() == 0
    # Scratch files are cleaned up afterwards — the module promises never to leave large
    # generated fixtures behind, and never to write them into the repo.
    assert list(tmp_path.glob("perf_large*")) == []


def test_measure_reports_a_nonnegative_wall_time_and_peak():
    elapsed, peak_bytes, peak_mib = perf_report._measure("noop", lambda: None)
    assert elapsed >= 0
    assert peak_bytes >= 0
    assert peak_mib == peak_bytes / (1024 * 1024)
