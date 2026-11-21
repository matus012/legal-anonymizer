"""v1.1 Phase F: the review page's "Rozšírené nastavenia" panel and the two features it
gates (anonymised output filenames, source-filename leak warning).

Offscreen, same style as tests/test_gui_e2e.py — QT_QPA_PLATFORM is set BEFORE any
QApplication import, and the app is driven through its real widgets. Pure-logic assertions
(naming, manifest text, leak detection) live in tests/test_gui_model.py; this file only
tests what genuinely needs a widget.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import docx as _docx
import pytest
from PySide6.QtWidgets import QApplication

from gui.app import MainWindow


def _mk_docx(tmp_path, name, text):
    p = tmp_path / name
    d = _docx.Document()
    d.add_paragraph(text)
    d.save(str(p))
    return str(p)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp):
    w = MainWindow()
    w.blocking = True          # run scan/export synchronously on the test thread
    return w


# ---------------------------------------------------------------- the panel itself
def test_advanced_panel_is_collapsed_and_all_off(win):
    """Six non-technical lawyers (context.md §2): an option they did not ask for must not be
    the first thing they see, and must never be on without them turning it on."""
    assert win.advanced_box.isHidden(), "advanced options must start collapsed"
    assert not win.chk_strict.isChecked()
    assert not win.chk_all_dates.isChecked()
    assert not win.chk_anon_names.isChecked()
    cfg = win.detect_config()
    assert cfg.strict_checksums is False and cfg.redact_all_dates is False


def test_advanced_panel_opens_on_toggle(win):
    win.advanced_btn.setChecked(True)
    assert not win.advanced_box.isHidden()
    win.advanced_btn.setChecked(False)
    assert win.advanced_box.isHidden()


def test_each_checkbox_has_a_slovak_explanation(win):
    assert win.chk_strict.text() == "Prísna kontrola kontrolných súčtov"
    assert win.chk_all_dates.text() == "Anonymizovať všetky dátumy"
    assert win.chk_anon_names.text() == "Anonymizovať názvy súborov"
    helps = [win.adv_help_strict, win.adv_help_dates, win.adv_help_names]
    assert all(h.text().strip() for h in helps), "each option needs its one-line explanation"
    assert len({h.text() for h in helps}) == 3, "three options, three different explanations"
    assert all(h.parent() is win.advanced_box for h in helps), "explanations live in the panel"


# ---------------------------------------------------------------- config -> review table
def test_toggling_strict_checksums_rescans_and_moves_the_row(win, tmp_path):
    """The core invariant of the GUI design spec: the review table can NEVER disagree with
    what export will do. strict_checksums changes which bucket the checksum-invalid rodné
    číslo lands in, so flipping it must rebuild the table, not leave a stale one."""
    src = _mk_docx(tmp_path, "zmluva.docx", "Jan Novak, rodne cislo 835112/0009.")
    win.add_files([src])
    win.start_scan(blocking=True)
    rc = next(r for r in win.scans[src].rows if r.type == "RODNE_CISLO")
    assert rc.bucket == "auto"                       # v1.1 default policy A1

    win.chk_strict.setChecked(True)                  # must trigger the re-scan itself
    assert win.detect_config().strict_checksums is True
    rc2 = next(r for r in win.scans[src].rows if r.type == "RODNE_CISLO")
    assert rc2.bucket == "review", "table still built under the OLD config"


def test_export_uses_the_same_config_as_the_scan(win, tmp_path, monkeypatch):
    """Whatever config produced the review table must reach export_file, or the invariant is
    broken at the only moment that matters."""
    seen = []
    import gui.app as app_mod
    real = app_mod.export_file

    def spy(src, known, decisions, config=None, **kw):
        seen.append(config)
        return real(src, known, decisions, config, **kw)

    monkeypatch.setattr(app_mod, "export_file", spy)
    src = _mk_docx(tmp_path, "zmluva.docx", "Jan Novak, rodne cislo 835112/0009.")
    win.add_files([src])
    win.chk_all_dates.setChecked(True)
    win.start_scan(blocking=True)
    win.start_export(blocking=True)
    assert seen and all(c is not None and c.redact_all_dates for c in seen)


# ---------------------------------------------------------------- anonymised output names
def test_anonymize_output_names_renames_and_writes_manifest(win, tmp_path):
    a = _mk_docx(tmp_path, "Novak_kupna_zmluva.docx", "Jan Novak, DIC 2023456789.")
    b = _mk_docx(tmp_path, "Kovacova_zaloba.docx", "Eva Kovacova, DIC 2023456789.")
    win.add_files([a, b])
    win.chk_anon_names.setChecked(True)
    win.start_scan(blocking=True)
    win.start_export(blocking=True)

    assert (tmp_path / "doc_001_anon.docx").exists()
    assert (tmp_path / "doc_002_anon.docx").exists()
    assert not (tmp_path / "Novak_kupna_zmluva_anon.docx").exists()
    report = (tmp_path / "doc_001_anon_docx_report.txt").read_text(encoding="utf-8")
    assert "MANIFEST" in report
    # the manifest maps the WHOLE batch, so one report answers "which file is doc_002?"
    assert "doc_001_anon.docx | Novak_kupna_zmluva.docx" in report
    assert "doc_002_anon.docx | Kovacova_zaloba.docx" in report


def test_flag_off_keeps_todays_output_names(win, tmp_path):
    src = _mk_docx(tmp_path, "Novak_kupna_zmluva.docx", "Jan Novak, DIC 2023456789.")
    win.add_files([src])
    win.start_scan(blocking=True)
    win.start_export(blocking=True)
    assert (tmp_path / "Novak_kupna_zmluva_anon.docx").exists()
    report = (tmp_path / "Novak_kupna_zmluva_anon_docx_report.txt").read_text(encoding="utf-8")
    assert "MANIFEST" not in report


# ---------------------------------------------------------------- filename leak warning
def test_review_page_warns_when_the_filename_leaks(win, tmp_path):
    src = _mk_docx(tmp_path, "Novak_zmluva.docx", "Jan Novak, DIC 2023456789.")
    win.add_files([src])
    win.known_edit.setPlainText("Jan Novak")
    win.start_scan(blocking=True)
    assert not win.fname_warn.isHidden()
    assert "Novak" in win.fname_warn.text()
    assert win.sidebar.item(0).text().startswith("⚠")


def test_no_warning_for_a_clean_filename(win, tmp_path):
    src = _mk_docx(tmp_path, "zmluva_2024.docx", "Jan Novak, DIC 2023456789.")
    win.add_files([src])
    win.known_edit.setPlainText("Jan Novak")
    win.start_scan(blocking=True)
    assert win.fname_warn.isHidden()
    assert not win.sidebar.item(0).text().startswith("⚠")
