"""MainWindow: 3-page wizard (Input -> Review -> Done) over gui.model's pure logic.

All redaction logic lives in gui.model; this file is mechanical Qt layout + state
plumbing. blocking=True runs jobs synchronously (tests); otherwise BatchWorker keeps
the UI thread free and a progress bar moves per finished file.
"""
from __future__ import annotations

import os
from functools import partial

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from detect.config import DetectConfig
from detect.selfcheck import describe_environment, verify_bundled_data
from gui.model import (
    MSG_DATA_MISSING,
    MSG_DETECTOR_FAILED,
    MSG_FILENAME_LEAK,
    SUPPORTED,
    FileScan,
    build_decisions,
    export_file,
    out_path_for,
    scan_file,
)
from gui.worker import BatchWorker

_TABLE_HEADERS = ["", "Typ", "Text", "Kontext", "Umiestnenie", "Počet"]

_ADV_CLOSED = "▸ Rozšírené nastavenia"
_ADV_OPEN = "▾ Rozšírené nastavenia"
# One line of plain Slovak per option: what it does and what it costs. These users do not
# read a manual (context.md §2) — if the label needs explaining, the explanation ships next
# to it or the option is a liability.
_HELP_STRICT = (
    "Identifikátor s chybným kontrolným súčtom sa nezredaguje automaticky, "
    "ale pôjde na ručné posúdenie."
)
# The contracted meaning is "OFF = iba dátum narodenia, ON = každý dátum". The engine does
# NOT implement that yet — detect/datetime_amounts.py emits every DATUM with auto=True and
# does not take a config at all, so the flag is currently a no-op (reported to the
# orchestrator; the field and its threading are correct and go live the moment the detector
# honours it). Until then the help line says what the tool ACTUALLY does: a GUI that
# describes behaviour the tool does not have is the liability posture context.md §9 forbids.
# The "POZOR" warning that used to be here said the engine ignored this setting. It did --
# detect/datetime_amounts.py took no config and auto-redacted every date. The engine now
# honours the flag, so the warning is gone and the help text describes what actually happens.
_HELP_DATES = (
    "Predvolene sa automaticky rediguje iba dátum narodenia; ostatné dátumy sa nájdu, "
    "ale zostanú na kontrolu. Po zapnutí sa rediguje každý dátum."
)
_HELP_NAMES = (
    "Výstupy sa pomenujú doc_001_anon, doc_002_anon… Pôvodné názvy nájdete "
    "v sekcii MANIFEST v protokole."
)


def _bold(label: QLabel) -> QLabel:
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anonymizátor právnych dokumentov (v1)")
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        # --- state ---
        self.files: list[str] = []                       # ordered, deduped
        self.scans: dict[str, FileScan] = {}
        self.extra_terms: list[str] = []                 # batch-global
        self.row_states: dict[str, dict[tuple, bool]] = {}
        self.current_src: str | None = None              # file shown in the review table
        self._table_groups: list[tuple] = []             # group per table row
        self._export_results: dict[int, object] = {}     # job index -> (out, report) | Exception
        self._export_srcs: list[str] = []
        self._first_out: str | None = None
        self._worker: BatchWorker | None = None
        # Tests drive the wizard on one thread; the app never sets this.
        self.blocking: bool = False

        # STARTUP SELF-CHECK (detect/selfcheck.py). Runs before any page is built, because
        # its answer decides whether the scan button may ever be enabled. If the bundled
        # gazetteer data did not make it into this build the application would otherwise
        # keep working perfectly and just stop redacting every place name and surname in
        # the country -- with no crash, no dialog, and a report that looks ordinary, only
        # shorter. Refusing to scan is the only honest response to that.
        self.data_problems: list[str] = verify_bundled_data()

        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.pages.addWidget(self._build_input_page())   # 0
        self.pages.addWidget(self._build_review_page())  # 1
        self.pages.addWidget(self._build_done_page())    # 2

        self.progress = QProgressBar()
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        if self.data_problems:
            self._show_data_problems()

    def _show_data_problems(self) -> None:
        """Say it twice, on purpose: a banner that stays on screen and a modal at startup.

        The modal cannot be missed and the banner cannot be dismissed and forgotten. This
        is the one condition where the tool is actively unsafe to trust, so it is the one
        place where being irritating is correct."""
        text = MSG_DATA_MISSING.format(
            problems="\n".join(f"  - {p}" for p in self.data_problems),
            where=describe_environment(),
        )
        self.data_warn.setText(text)
        self.data_warn.show()
        self.scan_btn.setEnabled(False)
        QMessageBox.critical(self, "Chýbajúce údaje", text)

    # ------------------------------------------------------------ page 0: input
    def _build_input_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        # Sits at the very top of the first page the user sees, above everything.
        self.data_warn = QLabel()
        self.data_warn.setWordWrap(True)
        self.data_warn.setStyleSheet(
            "color: #ffffff; background: #a00000; font-weight: bold; padding: 8px;")
        self.data_warn.hide()
        lay.addWidget(self.data_warn)
        lay.addWidget(_bold(QLabel("Vyberte dokumenty na anonymizáciu (.docx, .pdf)")))
        lay.addWidget(QLabel("Súbory sem môžete pretiahnuť myšou."))

        self.add_btn = QPushButton("Pridať súbory…")
        self.add_btn.clicked.connect(self._pick_files)
        lay.addWidget(self.add_btn)

        self.file_list = QListWidget()
        lay.addWidget(self.file_list, 2)

        lay.addWidget(_bold(QLabel(
            "Mená a adresy strán (jedno na riadok) — výrazne zlepší výsledok")))
        lay.addWidget(QLabel("Nepovinné"))
        self.known_edit = QPlainTextEdit()
        lay.addWidget(self.known_edit, 1)

        self.scan_btn = QPushButton("Skenovať")
        self.scan_btn.setEnabled(False)
        self.scan_btn.clicked.connect(lambda: self.start_scan())
        lay.addWidget(self.scan_btn)
        return page

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Pridať súbory", "", "Dokumenty (*.docx *.pdf)")
        if paths:
            self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        for p in paths:
            if os.path.splitext(p)[1].lower() in SUPPORTED and p not in self.files:
                self.files.append(p)
        self.file_list.clear()
        self.file_list.addItems(self.files)
        self.scan_btn.setEnabled(bool(self.files) and not self.data_problems)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() and any(
            u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower() in SUPPORTED
            for u in md.urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([
            u.toLocalFile() for u in event.mimeData().urls()
            if u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower() in SUPPORTED
        ])
        event.acceptProposedAction()

    # ------------------------------------------------------------ page 1: review
    def _build_review_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_bold(QLabel(
            "Skontrolujte nájdené údaje. Zaškrtnuté položky budú v dokumente nahradené.")))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = QListWidget()
        self.sidebar.currentRowChanged.connect(self._on_sidebar_change)
        split.addWidget(self.sidebar)

        right = QWidget()
        rlay = QVBoxLayout(right)
        # Filename-leak warning: shown for the selected file when its own NAME contains a
        # surface the scan found. Sits above the table because it is a fact about the file,
        # not about any one row, and it is actionable with the tool switched off.
        self.fname_warn = QLabel()
        self.fname_warn.setWordWrap(True)
        self.fname_warn.setStyleSheet("color: #8a4b00; font-weight: bold;")
        self.fname_warn.hide()
        rlay.addWidget(self.fname_warn)
        # Detector-failure warning. Sits ABOVE the filename warning and is styled red
        # rather than amber, because it is the only message on this screen that means
        # "the list below may be incomplete" -- every other row and warning is a
        # statement about something the tool DID find.
        self.detector_warn = QLabel()
        self.detector_warn.setWordWrap(True)
        self.detector_warn.setStyleSheet("color: #a00000; font-weight: bold;")
        self.detector_warn.hide()
        rlay.insertWidget(0, self.detector_warn)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        rlay.addWidget(self.error_label)
        self.table = QTableWidget(0, len(_TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(_TABLE_HEADERS)
        self.table.verticalHeader().hide()
        rlay.addWidget(self.table)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)

        extra_row = QHBoxLayout()
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("Redigovať aj toto…")
        extra_row.addWidget(self.extra_edit, 1)
        self.extra_btn = QPushButton("Pridať a preskenovať")
        self.extra_btn.clicked.connect(self._add_extra_term)
        extra_row.addWidget(self.extra_btn)
        lay.addLayout(extra_row)

        lay.addWidget(self._build_advanced())

        self.export_btn = QPushButton("Exportovať všetko")
        self.export_btn.clicked.connect(lambda: self.start_export())
        lay.addWidget(self.export_btn)
        return page

    # ---------------------------------------------------- review page: advanced settings
    def _build_advanced(self) -> QWidget:
        """Collapsed-by-default panel holding the three v1.1 toggles, ALL OFF.

        Collapsed, not merely grouped: an option a non-technical user does not understand and
        did not ask for is a liability the moment it is visible (QUESTIONS.md Q1 keeps
        strict_checksums reachable, not prominent)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)

        self.advanced_btn = QPushButton(_ADV_CLOSED)
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setChecked(False)
        self.advanced_btn.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.advanced_btn)

        self.advanced_box = QWidget()
        self.advanced_box.setVisible(False)
        alay = QVBoxLayout(self.advanced_box)

        self.chk_strict = QCheckBox("Prísna kontrola kontrolných súčtov")
        self.adv_help_strict = QLabel(_HELP_STRICT)
        self.chk_all_dates = QCheckBox("Anonymizovať všetky dátumy")
        self.adv_help_dates = QLabel(_HELP_DATES)
        self.chk_anon_names = QCheckBox("Anonymizovať názvy súborov")
        self.adv_help_names = QLabel(_HELP_NAMES)
        for chk, help_ in ((self.chk_strict, self.adv_help_strict),
                           (self.chk_all_dates, self.adv_help_dates),
                           (self.chk_anon_names, self.adv_help_names)):
            row = QHBoxLayout()
            row.addWidget(chk)
            help_.setWordWrap(True)
            row.addWidget(help_, 1)
            alay.addLayout(row)
        # Only the two DETECTION toggles invalidate the review table; the naming toggle is
        # an export-time decision and changes nothing that was scanned.
        self.chk_strict.toggled.connect(self._on_detect_config_changed)
        self.chk_all_dates.toggled.connect(self._on_detect_config_changed)

        lay.addWidget(self.advanced_box)
        return box

    def _toggle_advanced(self, open_: bool) -> None:
        self.advanced_box.setVisible(open_)
        self.advanced_btn.setText(_ADV_OPEN if open_ else _ADV_CLOSED)

    def detect_config(self) -> DetectConfig:
        """The ONE config object; the same instance semantics feed scan AND export."""
        return DetectConfig(strict_checksums=self.chk_strict.isChecked(),
                            redact_all_dates=self.chk_all_dates.isChecked())

    def _on_detect_config_changed(self, _checked: bool) -> None:
        """A detection toggle invalidates the review table — it was built by a scan under the
        old config. Re-scan immediately (same path, same busy state, as "Pridať a preskenovať"
        already does for an extra term) rather than leaving a table that disagrees with what
        export would do. Nothing to invalidate before the first scan."""
        if self.files and self.scans:
            self.start_scan(self.blocking)

    def _on_sidebar_change(self, row: int):
        if row < 0 or row >= len(self.files):
            return
        src = self.files[row]
        if src == self.current_src:
            return
        self._persist_current()
        self._show_file(src)

    def _persist_current(self) -> None:
        """Save the shown table's checkstates into row_states before leaving the file."""
        if self.current_src is None:
            return
        scan = self.scans.get(self.current_src)
        if scan is None or scan.error is not None:
            return
        self.row_states.setdefault(self.current_src, {}).update(self.current_row_states())

    def current_row_states(self) -> dict[tuple, bool]:
        return {
            group: self.table.item(i, 0).checkState() == Qt.CheckState.Checked
            for i, group in enumerate(self._table_groups)
        }

    def _show_file(self, src: str) -> None:
        self.current_src = src
        scan = self.scans.get(src)
        if scan is None:
            return
        if scan.detector_failures:
            self.detector_warn.setText(MSG_DETECTOR_FAILED.format(
                names=", ".join(dict.fromkeys(d for d, _loc, _err in scan.detector_failures))))
            self.detector_warn.show()
        else:
            self.detector_warn.hide()
        if scan.filename_hits:
            self.fname_warn.setText(MSG_FILENAME_LEAK.format(
                names=", ".join(dict.fromkeys(scan.filename_hits))))
            self.fname_warn.show()
        else:
            self.fname_warn.hide()
        if scan.error is not None:
            self.table.hide()
            self.error_label.setText(scan.error)
            self.error_label.show()
            self._table_groups = []
            self.table.setRowCount(0)
            return
        self.error_label.hide()
        self.table.show()
        rows = sorted(scan.rows,
                      key=lambda r: (0 if r.bucket == "auto" else 1, r.type, r.text))
        states = self.row_states.get(src, {})
        self.table.setRowCount(len(rows))
        self._table_groups = [r.group for r in rows]
        for i, r in enumerate(rows):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if states.get(r.group, r.bucket == "auto")
                              else Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, chk)
            for col, text in enumerate(
                    [r.type, r.text, r.snippet, ", ".join(r.locations), str(r.count)], start=1):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, col, item)
        self.table.resizeColumnsToContents()

    def _add_extra_term(self):
        term = self.extra_edit.text().strip()
        if not term:
            return
        self.extra_terms.append(term)
        self.extra_edit.clear()
        self.start_scan()

    # ------------------------------------------------------------ scan
    def _known(self) -> list[str]:
        return [ln.strip() for ln in self.known_edit.toPlainText().splitlines() if ln.strip()]

    def start_scan(self, blocking: bool = False) -> None:
        if self.data_problems:
            # Belt and braces. The button is disabled, but start_scan is also called
            # directly by tests and could be reached by a future code path; a guard that
            # only lives in the UI layer is a guard that will eventually be bypassed.
            self._show_data_problems()
            return
        self._persist_current()
        known = self._known()
        config = self.detect_config()
        jobs = [partial(scan_file, f, known, tuple(self.extra_terms), config)
                for f in self.files]

        def on_result(i: int, r: object) -> None:
            src = self.files[i]
            if isinstance(r, Exception):
                r = FileScan(src, [], str(r))
            self.scans[src] = r

        self._run_jobs(jobs, blocking, on_result, self._finish_scan)

    def _finish_scan(self) -> None:
        # Defaults auto->True review->False; keep the user's choices for groups that survive.
        for src in self.files:
            scan = self.scans.get(src)
            if scan is None or scan.error is not None:
                self.row_states[src] = {}
                continue
            old = self.row_states.get(src, {})
            self.row_states[src] = {
                r.group: old.get(r.group, r.bucket == "auto") for r in scan.rows}
        self.current_src = None
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        for src in self.files:
            scan = self.scans.get(src)
            # One ⚠ for "this file needs your attention" — a refusal or a leaking filename.
            # Which of the two it is, is on the right-hand pane; the sidebar only has to make
            # the lawyer click the file.
            flagged = scan is not None and (scan.error is not None or bool(scan.filename_hits))
            prefix = "⚠ " if flagged else ""
            self.sidebar.addItem(prefix + os.path.basename(src))
        self.sidebar.blockSignals(False)
        if self.files:
            self.sidebar.setCurrentRow(0)
            self._show_file(self.files[0])
        self.pages.setCurrentIndex(1)

    # ------------------------------------------------------------ export
    def start_export(self, blocking: bool = False) -> None:
        self._persist_current()
        known = self._known()
        self._export_srcs = [
            f for f in self.files
            if f in self.scans and self.scans[f].error is None]
        self._export_results = {}
        # The SAME config that produced the review table — re-reading it here is what keeps
        # the spec's invariant (the review screen can never disagree with the export).
        config = self.detect_config()
        anon = self.chk_anon_names.isChecked()
        # Index is the file's 1-based position in the WHOLE batch, not in the exportable
        # subset: a refused file leaves a gap rather than shifting every later document's
        # number, so doc_003 is the third file in the sidebar no matter what failed.
        indices = {f: self.files.index(f) + 1 for f in self._export_srcs}
        manifest = tuple(
            (os.path.basename(out_path_for(f, indices[f], anon)), os.path.basename(f))
            for f in self._export_srcs
        ) if anon else None
        jobs = []
        for f in self._export_srcs:
            decisions = build_decisions(
                self.scans[f].rows, self.row_states.get(f, {}), tuple(self.extra_terms))
            jobs.append(partial(export_file, f, known, decisions, config,
                                index=indices[f], anonymize_names=anon, manifest=manifest))

        def on_result(i: int, r: object) -> None:
            self._export_results[i] = r

        self._run_jobs(jobs, blocking, on_result, self._finish_export)

    def _finish_export(self) -> None:
        self.done_list.clear()
        self._first_out = None
        results = {src: self._export_results.get(i)
                   for i, src in enumerate(self._export_srcs)}
        for src in self.files:
            scan = self.scans.get(src)
            if scan is not None and scan.error is not None:
                self.done_list.addItem(f"⚠ {os.path.basename(src)}: {scan.error}")
                continue
            r = results.get(src)
            if isinstance(r, tuple):
                out, _report = r
                if self._first_out is None:
                    self._first_out = out
                # With anonymised names the output no longer says which document it is, so
                # the mapping is shown here too — not only in the report's MANIFEST.
                origin = f"   ← {os.path.basename(src)}" if self.chk_anon_names.isChecked() else ""
                self.done_list.addItem(f"✓ {out}{origin}")
            else:
                self.done_list.addItem(f"⚠ {os.path.basename(src)}: {r}")
        self.pages.setCurrentIndex(2)

    # ------------------------------------------------------------ page 2: done
    def _build_done_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_bold(QLabel("Hotovo")))
        self.done_list = QListWidget()
        lay.addWidget(self.done_list, 1)

        self.open_btn = QPushButton("Otvoriť priečinok")
        self.open_btn.clicked.connect(self._open_folder)
        lay.addWidget(self.open_btn)

        warn = _bold(QLabel(
            "Skontrolujte výstupné dokumenty pred odoslaním. Aplikácia negarantuje, "
            "že dokument je čistý — konečná kontrola je na vás."))
        warn.setWordWrap(True)
        lay.addWidget(warn)

        self.new_batch_btn = QPushButton("Nová dávka")
        self.new_batch_btn.clicked.connect(self._reset_batch)
        lay.addWidget(self.new_batch_btn)
        return page

    def _open_folder(self):
        if self._first_out:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._first_out)))

    def _reset_batch(self):
        self.files = []
        self.scans = {}
        self.extra_terms = []
        self.row_states = {}
        self.current_src = None
        self._table_groups = []
        self._export_results = {}
        self._export_srcs = []
        self._first_out = None
        self.file_list.clear()
        self.sidebar.clear()
        self.table.setRowCount(0)
        self.done_list.clear()
        self.extra_edit.clear()
        self.fname_warn.hide()
        # A new batch starts from the documented defaults. A detection toggle left on from a
        # previous batch, hidden inside a collapsed panel, is exactly the silent-state trap
        # the panel is collapsed to avoid. blockSignals: nothing to re-scan, files are gone.
        for chk in (self.chk_strict, self.chk_all_dates, self.chk_anon_names):
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        self.advanced_btn.setChecked(False)
        self.scan_btn.setEnabled(False)
        self.pages.setCurrentIndex(0)

    # ------------------------------------------------------------ job runner
    def _set_busy(self, busy: bool) -> None:
        """Double-click guard: one running worker at a time — a second Skenovať/Exportovať
        click must not spawn a second batch writing the same output paths."""
        for btn in (self.scan_btn, self.export_btn, self.extra_btn, self.add_btn,
                    self.chk_strict, self.chk_all_dates, self.chk_anon_names):
            btn.setEnabled(not busy)
        if not busy:
            self.scan_btn.setEnabled(bool(self.files) and not self.data_problems)

    def _run_jobs(self, jobs, blocking, on_result, on_all_done) -> None:
        if blocking:
            for i, job in enumerate(jobs):
                try:
                    on_result(i, job())
                except Exception as e:
                    on_result(i, e)
            on_all_done()
            return
        if self._worker is not None and self._worker.isRunning():
            return  # a batch is already in flight
        self._set_busy(True)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.show()
        self._worker = BatchWorker(jobs, self)

        def _on_job(i, r):
            on_result(i, r)
            self.progress.setValue(self.progress.value() + 1)

        def _on_done():
            self.progress.hide()
            self._set_busy(False)
            on_all_done()

        self._worker.job_done.connect(_on_job)
        self._worker.all_done.connect(_on_done)
        self._worker.start()
