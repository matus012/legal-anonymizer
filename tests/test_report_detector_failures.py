"""The detector-failure channel, end to end: LabelMap -> report -> GUI scan.

The unit tests in tests/test_detector_isolation.py prove detect() does not raise. That is
only half of the requirement. The other half is that a failure is not SILENT — a detector
that produced nothing because it crashed is indistinguishable, in every other artefact this
tool emits, from a detector that produced nothing because there was nothing to find. This
file asserts the difference reaches the two places a human actually looks: the report file
and the review screen.
"""
import glob
import os
import tempfile

import pytest

from detect import core
from writer.labelmap import LabelMap
from writer.report import build_report, report_path_for


# --------------------------------------------------------------------------- LabelMap
def test_repeated_identical_failures_collapse_to_one_row_with_a_count():
    """A detector that chokes on one character shape chokes on it in every paragraph that
    contains it. Four hundred identical rows would bury the one line that matters."""
    lm = LabelMap([])
    for location in ("body", "table_cell", "header", "footnote"):
        lm.record_detector_failure("detect_iban", location, "ValueError: base 36")

    assert len(lm.detector_failures) == 1
    detector, location, error = lm.detector_failures[0]
    assert detector == "detect_iban"
    assert location.startswith("body"), "the FIRST location is where a reviewer starts looking"
    assert "+3 more" in location, "the scale must not be lost to the de-duplication"
    assert error == "ValueError: base 36"


def test_different_errors_from_the_same_detector_stay_separate():
    lm = LabelMap([])
    lm.record_detector_failure("detect_iban", "body", "ValueError: base 36")
    lm.record_detector_failure("detect_iban", "header", "IndexError: out of range")
    assert len(lm.detector_failures) == 2


def test_a_clean_pass_records_nothing():
    assert LabelMap([]).detector_failures == []


# --------------------------------------------------------------------------- report
def test_the_report_is_byte_identical_when_there_are_no_failures():
    """Same discipline as the v1.1 checksum side-channels, for the same reason: no existing
    report, test or diff may shift by a byte because a new feature exists."""
    base = build_report({}, [])
    assert build_report({}, [], None, None, None) == base
    assert build_report({}, [], None, None, []) == base


def test_the_warning_block_precedes_the_redaction_table():
    """Order is the message. A reader who has already accepted the REDACTED table as the
    complete story will not revise that on a footnote."""
    out = build_report({}, [], None, None, [("detect_iban", "page_3", "ValueError: base 36")])
    assert out.index("DETECTOR FAILURES") < out.index("[REDACTED]")


def test_the_warning_names_the_detector_the_location_and_the_error():
    out = build_report({}, [], None, None, [("detect_iban", "page_3", "ValueError: base 36")])
    assert "detect_iban" in out
    assert "page_3" in out
    assert "ValueError: base 36" in out


def test_the_warning_says_the_document_may_be_under_redacted():
    """The consequence, not just the event. "detect_iban failed" means nothing to a lawyer;
    "this document may still contain account numbers" means everything."""
    out = build_report({}, [], None, None, [("detect_iban", "page_3", "boom")])
    assert "UNDER-REDACTED" in out
    assert "was NOT removed" in out


# --------------------------------------------------------------------------- end to end
def _a_corpus_docx():
    hits = sorted(glob.glob(os.path.join("data", "synthetic", "kupna_zmluva_0*.docx")))
    if not hits:
        pytest.skip("corpus not generated; see status.txt for the regenerate command")
    return hits[0]


def test_a_raising_detector_produces_a_report_warning_not_a_traceback(monkeypatch):
    from writer.docx_body import redact_docx_body

    def boom(text, config=None):
        raise RuntimeError("simulated detector explosion")

    monkeypatch.setattr(core, "detect_gazetteer", boom)
    src = _a_corpus_docx()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.docx")
        redact_docx_body(src, out, known_entities=["Novák"])   # must NOT raise
        report = open(report_path_for(out), encoding="utf-8").read()

    assert "DETECTOR FAILURES" in report
    assert "detect_gazetteer" in report
    assert "simulated detector explosion" in report
    # ... and the OTHER detectors still did their job. A crash-safe tool that quietly stops
    # redacting is worse than one that crashes, because nothing says it happened.
    assert "[RODNE_CISLO_1]" in report


def test_the_gui_scan_carries_the_failures_to_the_review_screen(monkeypatch):
    from gui.model import scan_file

    def boom(text, config=None):
        raise RuntimeError("simulated detector explosion")

    monkeypatch.setattr(core, "detect_gazetteer", boom)
    scan = scan_file(_a_corpus_docx(), ["Novák"])

    assert scan.error is None, "a detector failure must not look like a failed scan"
    assert scan.rows, "the other detectors' rows must still reach the table"
    assert any(d == "detect_gazetteer" for d, _loc, _err in scan.detector_failures)


def test_a_clean_gui_scan_reports_no_failures():
    from gui.model import scan_file

    scan = scan_file(_a_corpus_docx(), ["Novák"])
    assert scan.detector_failures == (), (
        "a warning that appears on every clean document is a warning nobody reads"
    )
