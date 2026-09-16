"""Phase 6 Task 4: gui.model — pure scan/decisions/export logic, no Qt.

Hand-built fixtures via the same helpers as tests/test_writer_decisions.py and
tests/test_writer_decisions_pdf.py — tests never import corpus/ or eval/.
"""
import os

import docx as _docx
import fitz

from detect.config import DetectConfig
from gui.model import (
    FileScan,
    ReviewRow,
    build_decisions,
    export_file,
    filename_leak_hits,
    out_path_for,
    scan_file,
)


def _mk_docx(tmp_path, text):
    p = tmp_path / "in.docx"
    d = _docx.Document()
    d.add_paragraph(text)
    d.save(str(p))
    return str(p)


def _docx_text(path):
    return "\n".join(par.text for par in _docx.Document(path).paragraphs)


def _mk_pdf(tmp_path, text):
    p = tmp_path / "in.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(p))
    doc.close()
    return str(p)


def _pdf_text(path):
    doc = fitz.open(path)
    t = "\n".join(pg.get_text("text") for pg in doc)
    doc.close()
    return t


def test_out_path_for_appends_anon(tmp_path):
    assert out_path_for(r"C:\x\zmluva.docx").endswith("zmluva_anon.docx")
    assert out_path_for(r"C:\x\zaloba.pdf").endswith("zaloba_anon.pdf")


def test_scan_docx_builds_grouped_rows(tmp_path):
    src = _mk_docx(tmp_path, "Jan Novak a Novakovi patri DIC 2023456789. rodne cislo 835112/0009.")
    # strict_checksums=True is what routes the checksum-invalid RC to the review bucket in
    # v1.1 (CONTRACTS_v11.md §6) — the two-bucket grouping this test is ABOUT.
    scan = scan_file(src, ["Jan Novak"], config=DetectConfig(strict_checksums=True))
    assert scan.error is None
    auto = [r for r in scan.rows if r.bucket == "auto"]
    review = [r for r in scan.rows if r.bucket == "review"]
    meno = next(r for r in auto if r.type == "MENO")
    # v1: detect.known_entities emitted one MENO per matched TOKEN, so "Jan Novak a
    # Novakovi" gave three occurrences. v1.1's name detectors emit the WHOLE name as one
    # wider span ("Jan Novak"), and core's containment resolver drops the narrower token
    # candidates inside it -- deliberately, because the writers slice by character offsets
    # and overlapping spans corrupt the output. So the same text is now TWO occurrences:
    # "Jan Novak" + "Novakovi". The REDACTION is unchanged; the wider span covers strictly
    # more text.
    #
    # What this test is really about is the GROUPING, so that is what it now asserts:
    # however many occurrences there are, they collapse into ONE row bound to entity 0 (the
    # declension matcher recognises "Novakovi" as the same party). A review screen grouped
    # by occurrence instead of by entity is the fatigue trap context.md 9 warns about.
    assert meno.count == 2
    assert meno.group == ("MENO", ("entity", 0))
    assert len([r for r in auto if r.type == "MENO"]) == 1, "one row per party, not per hit"
    assert meno.locations == ("body",)
    assert any(r.type == "DIC" for r in auto)
    assert any(r.type == "RODNE_CISLO" for r in review)
    assert all(r.snippet for r in scan.rows)    # every row carries context
    assert next(r for r in review if r.type == "RODNE_CISLO").checksum == "invalid"


def test_scan_default_config_puts_the_invalid_rc_in_the_auto_bucket(tmp_path):
    """v1.1 policy A1 sibling: under the DEFAULT config the same RC is pre-ticked (auto) and
    the review bucket is empty — the reviewer un-ticks instead of ticking."""
    src = _mk_docx(tmp_path, "Jan Novak a Novakovi patri DIC 2023456789. rodne cislo 835112/0009.")
    scan = scan_file(src, ["Jan Novak"])
    assert scan.error is None
    rc = next(r for r in scan.rows if r.type == "RODNE_CISLO")
    assert rc.bucket == "auto"
    assert rc.checksum == "invalid"
    assert [r for r in scan.rows if r.bucket == "review"] == []


def test_scan_leaves_no_temp_files(tmp_path):
    src = _mk_docx(tmp_path, "DIC 2023456789")
    scan_file(src, None)
    assert list(tmp_path.iterdir()) == [tmp_path / "in.docx"]  # nothing new beside the source


def test_scan_pdf_without_text_layer_reports_error(tmp_path):
    p = tmp_path / "scan.pdf"
    doc = fitz.open(); doc.new_page(); doc.save(str(p)); doc.close()
    scan = scan_file(str(p), None)
    assert scan.error is not None and scan.rows == []


def test_build_decisions_from_checkbox_state(tmp_path):
    src = _mk_docx(tmp_path, "Jan Novak, DIC 2023456789, rodne cislo 835112/0009.")
    # Needs BOTH buckets populated: strict_checksums=True keeps the RC low-confidence.
    scan = scan_file(src, ["Jan Novak"], config=DetectConfig(strict_checksums=True))
    dic = next(r for r in scan.rows if r.type == "DIC")
    rc = next(r for r in scan.rows if r.type == "RODNE_CISLO")
    checked = {r.group: (r.bucket == "auto") for r in scan.rows}
    checked[dic.group] = False    # human unticks the DIC
    checked[rc.group] = True      # human ticks the low-confidence RC
    d = build_decisions(scan.rows, checked, extra_terms=("Karol Vlk",))
    assert dic.group in d.suppress_groups
    assert rc.group in d.force_groups
    assert d.extra_terms == ("Karol Vlk",)
    meno = next(r for r in scan.rows if r.type == "MENO")
    assert meno.group not in d.suppress_groups


def test_export_writes_anon_and_report(tmp_path):
    src = _mk_docx(tmp_path, "Jan Novak, DIC 2023456789.")
    scan = scan_file(src, ["Jan Novak"])
    checked = {r.group: (r.bucket == "auto") for r in scan.rows}
    out, report = export_file(src, ["Jan Novak"], build_decisions(scan.rows, checked, ()))
    # v1.1 Phase F: the report name carries the source format.
    assert out.endswith("in_anon.docx") and report.endswith("in_anon_docx_report.txt")
    txt = "\n".join(p.text for p in _docx.Document(out).paragraphs)
    assert "Novak" not in txt and "2023456789" not in txt


def test_export_cleans_up_partial_output_on_incomplete(tmp_path, monkeypatch):
    """RedactionIncompleteError fires AFTER the PDF writer saved output+report; export_file
    must delete both so no partially redacted file survives next to the source."""
    import gui.model as model
    from writer.pdf_body import RedactionIncompleteError

    src = str(tmp_path / "doc.pdf")
    open(src, "w").close()  # placeholder; _collect is stubbed below

    def fake_collect(src_, out, known, decisions, config=None):
        # Mirrors the real _collect signature (v1.1 adds the trailing config) and the real
        # report path rule, so the cleanup path under test is exercised against the paths
        # export_file actually computes.
        open(out, "w").close()
        open(model.report_path_for(out), "w").close()
        raise RedactionIncompleteError(["needle"])

    monkeypatch.setattr(model, "_collect", fake_collect)
    try:
        model.export_file(src, None, model.RedactionDecisions())
        assert False, "must re-raise"
    except RedactionIncompleteError:
        pass
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "doc.pdf"]
    assert leftovers == [], f"partial files left behind: {leftovers}"


# ---------------------------------------------------------------- v1.1 Phase F: output naming
def _mk_named_docx(tmp_path, name, text):
    p = tmp_path / name
    d = _docx.Document()
    d.add_paragraph(text)
    d.save(str(p))
    return str(p)


def test_out_path_for_anonymized_is_indexed(tmp_path):
    """anonymize_names=True replaces the whole stem, keeping the extension and the directory —
    the source stem (which carries the client's name) must not survive into the output name."""
    src = os.path.join("C:", os.sep, "x", "Novak_kupna_zmluva.docx")
    out = out_path_for(src, index=1, anonymize_names=True)
    assert os.path.basename(out) == "doc_001_anon.docx"
    assert os.path.dirname(out) == os.path.dirname(src)
    assert "Novak" not in out
    assert os.path.basename(out_path_for(src, index=12, anonymize_names=True)) == "doc_012_anon.docx"


def test_out_path_for_flag_off_is_unchanged(tmp_path):
    """Byte-identical to today whenever the flag is off, even with an index supplied."""
    src = r"C:\x\Novak_kupna_zmluva.docx"
    assert out_path_for(src) == out_path_for(src, index=3, anonymize_names=False)
    assert out_path_for(src).endswith("Novak_kupna_zmluva_anon.docx")


def test_export_with_anonymized_name_and_manifest(tmp_path):
    src = _mk_named_docx(tmp_path, "Novak_kupna_zmluva.docx", "Jan Novak, DIC 2023456789.")
    scan = scan_file(src, ["Jan Novak"])
    checked = {r.group: (r.bucket == "auto") for r in scan.rows}
    out, report = export_file(
        src, ["Jan Novak"], build_decisions(scan.rows, checked, ()),
        index=1, anonymize_names=True,
        manifest=(("doc_001_anon.docx", "Novak_kupna_zmluva.docx"),))
    assert os.path.basename(out) == "doc_001_anon.docx"
    assert os.path.basename(report) == "doc_001_anon_docx_report.txt"
    txt = open(report, encoding="utf-8").read()
    assert "[MANIFEST" in txt
    assert "doc_001_anon.docx" in txt and "Novak_kupna_zmluva.docx" in txt


def test_export_without_manifest_report_has_no_manifest_section(tmp_path):
    src = _mk_named_docx(tmp_path, "Novak_kupna_zmluva.docx", "Jan Novak, DIC 2023456789.")
    scan = scan_file(src, ["Jan Novak"])
    checked = {r.group: (r.bucket == "auto") for r in scan.rows}
    out, report = export_file(src, ["Jan Novak"], build_decisions(scan.rows, checked, ()))
    assert os.path.basename(out) == "Novak_kupna_zmluva_anon.docx"
    assert "MANIFEST" not in open(report, encoding="utf-8").read()


# ---------------------------------------------------------------- filename-leak warning
def test_filename_leak_hits_matches_folded_token(tmp_path):
    """The filename carries the bare stem `Novak` while the detected surface is the full,
    diacritic-bearing `Ján Novák` — a plain substring test would miss it."""
    rows = [ReviewRow(group=("MENO", ("entity", 0)), type="MENO", text="Ján Novák",
                      snippet="", locations=("body",), count=1, bucket="auto")]
    assert filename_leak_hits(r"C:\x\Novak_kupna_zmluva.docx", rows) == ("Ján Novák",)


def test_filename_leak_hits_empty_when_filename_is_clean(tmp_path):
    rows = [ReviewRow(group=("MENO", ("entity", 0)), type="MENO", text="Ján Novák",
                      snippet="", locations=("body",), count=1, bucket="auto")]
    assert filename_leak_hits(r"C:\x\kupna_zmluva_2024.docx", rows) == ()


def test_scan_flags_a_leaking_source_filename(tmp_path):
    src = _mk_named_docx(tmp_path, "Novak_zmluva.docx", "Jan Novak, DIC 2023456789.")
    assert "Jan Novak" in scan_file(src, ["Jan Novak"]).filename_hits


def test_scan_of_a_clean_filename_has_no_hits(tmp_path):
    src = _mk_named_docx(tmp_path, "zmluva_2024.docx", "Jan Novak, DIC 2023456789.")
    assert scan_file(src, ["Jan Novak"]).filename_hits == ()


def test_redact_all_dates_moves_a_plain_date_between_buckets(tmp_path):
    """The successor to a TRIPWIRE that did its job.

    The GUI round found that `redact_all_dates` was a DEAD FLAG: detect/datetime_amounts.py
    took no config at all and emitted every DATUM with auto=True, so every date in every
    document was auto-redacted while CONTRACTS_v11.md §2 claimed only a date of birth was. It
    refused to ship a checkbox describing behaviour the engine did not have, and left a
    tripwire asserting the broken state so that fixing the engine would force the GUI text to
    be corrected in the same change. The engine is now fixed, the tripwire fired, and this is
    what replaces it.

    A contract date with no birth anchor is DETECTED either way -- the question is only which
    bucket it lands in, and that is what a reviewer sees and decides."""
    src = _mk_named_docx(tmp_path, "zmluva.docx", "Zmluva uzavreta dna 1.3.2024 medzi stranami.")

    default = next(r for r in scan_file(src, None, config=DetectConfig()).rows if r.type == "DATUM")
    assert default.bucket == "review", (
        "a plain contract date must NOT be auto-redacted by default: a contract is a chain of "
        "dates, and destroying all of them leaves a document nobody can use"
    )

    every = next(
        r for r in scan_file(src, None, config=DetectConfig(redact_all_dates=True)).rows
        if r.type == "DATUM"
    )
    assert every.bucket == "auto", "redact_all_dates=True must auto-redact a plain date"


def test_a_date_of_birth_is_auto_redacted_by_default(tmp_path):
    """The other half of the policy, and the half that matters for privacy: a date next to a
    birth anchor identifies a person and is redacted without the reviewer having to notice."""
    src = _mk_named_docx(tmp_path, "zmluva.docx", "Datum narodenia: 15.3.1985, miesto Kosice.")
    datum = next(r for r in scan_file(src, None, config=DetectConfig()).rows if r.type == "DATUM")
    assert datum.bucket == "auto"
