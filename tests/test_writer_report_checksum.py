"""v1.1 (CONTRACTS_v11.md §1 / §10): the checksum TAG reaching the report and the GUI.

Three things are pinned here, and the FIRST one is the reason the file exists:

  * BYTE-IDENTITY. ``build_report(occurrences, low_confidence)`` — the two-argument call every
    v1 caller makes — must produce the EXACT v1 string. The expected value below is a full
    literal, written out character by character from the v1 layout rules, NOT captured from
    program output: an implementation that appended an empty ``checksum`` column, or a lone
    " | " separator, or shifted the header, would still "look right" in a diff but would break
    every downstream reader. A literal is the only assertion that catches that.
  * The checksum column, appended to BOTH tables, and ONLY when the caller supplies the
    matching side-channel.
  * The LabelMap side-channels themselves: ``occurrences`` / ``low_confidence`` tuple shapes
    stay byte-stable (build_report unpacks them positionally — widening them is the single
    most likely way to break this round), the checksum rides in the NEW parallel channels.

RED at HEAD: ``build_report`` takes exactly two parameters and ``LabelMap`` has no
``checksums`` / ``lc_checksums`` attributes, so every test except the byte-identity pin
raises. The byte-identity pin CANNOT be red at HEAD — it asserts that HEAD's behaviour is
preserved — so it is proven load-bearing by mutation instead (make the column unconditional;
this test is the one that fails).

Hand-built captures only — no corpus import, no disk, no redaction run except the one
end-to-end docx case, whose fixture is built in memory with python-docx.
"""
from __future__ import annotations

import docx as _docx

from detect.config import DetectConfig
from gui.model import scan_file
from writer.docx_body import redact_docx_collect
from writer.labelmap import LabelMap
from writer.report import build_report, report_path_for

# The v1 report layout, transcribed from the rules in writer/report.py, not from its output:
# header block, "[REDACTED]", its column line, one row per label sorted by (TYPE, numeric N),
# a blank line, "[LOW CONFIDENCE / NOT REDACTED]", its column line, capture-order rows.
_V1_EXPECTED = (
    "=== LEGAL ANONYMIZER — REDACTION REPORT ===\n"
    "\n"
    "This report records what the tool CHANGED and what it was UNSURE about.\n"
    "It does NOT certify that the document is clean. A human must review the\n"
    "redacted document before it is shared or filed.\n"
    "\n"
    "[REDACTED]\n"
    "TYPE | label | count | locations\n"
    # Sorted by (TYPE, numeric N) — ICO sorts before MENO.
    "ICO | [ICO_1] | 1 | body\n"
    "MENO | [MENO_1] | 2 | body, header\n"
    "\n"
    "[LOW CONFIDENCE / NOT REDACTED]\n"
    "type | surface | location\n"
    "RODNE_CISLO | 900101/0000 | footnote\n"
)

_OCC = {
    "[MENO_1]": [("body", "Novak"), ("header", "Novak")],
    "[ICO_1]": [("body", "12345678")],
}
_LC = [("footnote", "RODNE_CISLO", "900101/0000")]


def test_build_report_is_byte_identical_without_the_new_params() -> None:
    """The two-argument call reproduces the v1 string EXACTLY — every byte, including the
    column header line, which must NOT grow a checksum column."""
    assert build_report(_OCC, _LC) == _V1_EXPECTED


def test_explicit_none_side_channels_are_also_byte_identical() -> None:
    """Passing the new params as None is the same as omitting them — a caller that always
    forwards its (possibly empty) channels as None must not change the output either."""
    assert build_report(_OCC, _LC, None, None) == _V1_EXPECTED


def test_checksum_column_appended_to_both_tables_when_given() -> None:
    report = build_report(
        _OCC, _LC,
        {"[MENO_1]": "n/a", "[ICO_1]": "invalid"},
        ["valid"],
    )
    # Both column headers grew the column...
    assert "TYPE | label | count | locations | checksum" in report
    assert "type | surface | location | checksum" in report
    # ...and both tables carry the per-row tag.
    assert "ICO | [ICO_1] | 1 | body | invalid" in report
    assert "MENO | [MENO_1] | 2 | body, header | n/a" in report
    assert "RODNE_CISLO | 900101/0000 | footnote | valid" in report


def test_one_sided_side_channel_only_touches_its_own_table() -> None:
    """Supplying only ``checksums`` must not put a column on the low-confidence table (and
    vice versa) — the two channels are independent."""
    only_occ = build_report(_OCC, _LC, {"[ICO_1]": "invalid"}, None)
    assert "TYPE | label | count | locations | checksum" in only_occ
    assert "type | surface | location\n" in only_occ  # low-conf header UNCHANGED
    assert "RODNE_CISLO | 900101/0000 | footnote\n" in only_occ

    only_lc = build_report(_OCC, _LC, None, ["invalid"])
    assert "TYPE | label | count | locations\n" in only_lc  # redacted header UNCHANGED
    assert "type | surface | location | checksum" in only_lc


def test_missing_label_in_the_channel_reads_na_not_raises() -> None:
    """A report must never be the thing that crashes a redaction pass."""
    report = build_report(_OCC, _LC, {"[ICO_1]": "invalid"}, [])
    assert "MENO | [MENO_1] | 2 | body, header | n/a" in report
    assert "RODNE_CISLO | 900101/0000 | footnote | n/a" in report


def test_labelmap_tuple_shapes_stay_byte_stable_while_channels_fill() -> None:
    """THE regression this round is most likely to cause: the checksum must NOT widen the two
    tuples build_report unpacks positionally."""
    lm = LabelMap(None)
    lm.record_occurrence("[ICO_1]", "body", "12345670", snippet="ctx", checksum="invalid")
    lm.record_occurrence("[ICO_1]", "header", "12345670", checksum="valid")
    lm.record_low_confidence("footnote", "RODNE_CISLO", "900101/0000", snippet="c", checksum="invalid")
    lm.record_low_confidence("body", "ICO", "12345678")  # default keyword

    assert lm.occurrences["[ICO_1]"] == [("body", "12345670"), ("header", "12345670")]
    assert lm.low_confidence == [
        ("footnote", "RODNE_CISLO", "900101/0000"),
        ("body", "ICO", "12345678"),
    ]
    # First-seen wins for a label's checksum, exactly as for its context snippet.
    assert lm.checksums == {"[ICO_1]": "invalid"}
    assert lm.lc_checksums == ["invalid", "n/a"]
    assert lm.lc_contexts == ["c", ""]  # still index-aligned alongside it


def test_default_config_keyword_is_still_n_a() -> None:
    lm = LabelMap(None)
    lm.record_occurrence("[MENO_1]", "body", "Novak")
    assert lm.checksums["[MENO_1]"] == "n/a"


# --- end to end: the tag survives the writer into the written report and into the GUI row ---

def _mk_docx(tmp_path, text):
    p = tmp_path / "in.docx"
    d = _docx.Document()
    d.add_paragraph(text)
    d.save(str(p))
    return str(p)


def test_docx_report_carries_the_checksum_tag(tmp_path) -> None:
    """835112/0009 is RC-shaped with a FAILING checksum. Under the DEFAULT v1.1 config it is
    auto-redacted (policy A1: checksum is a tag, not a filter) and its report row says so."""
    src = _mk_docx(tmp_path, "rodne cislo: 835112/0009")
    out = str(tmp_path / "out.docx")
    lm = redact_docx_collect(src, out, known_entities=None)

    assert lm.checksums["[RODNE_CISLO_1]"] == "invalid"
    report = open(report_path_for(out), encoding="utf-8").read()
    assert "TYPE | label | count | locations | checksum" in report
    assert "RODNE_CISLO | [RODNE_CISLO_1] | 1 | body | invalid" in report


def test_review_row_carries_the_checksum_in_both_buckets(tmp_path) -> None:
    src = _mk_docx(tmp_path, "rodne cislo: 835112/0009")

    auto_row = next(r for r in scan_file(src, None).rows if r.type == "RODNE_CISLO")
    assert auto_row.bucket == "auto" and auto_row.checksum == "invalid"

    strict = scan_file(src, None, config=DetectConfig(strict_checksums=True))
    review_row = next(r for r in strict.rows if r.type == "RODNE_CISLO")
    assert review_row.bucket == "review" and review_row.checksum == "invalid"
