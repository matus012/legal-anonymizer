"""One QThread running a list of callables in order; per-job results/errors via signal.
Keeps scan/export off the UI thread (context.md §2: the app must never look frozen)."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class BatchWorker(QThread):
    job_done = Signal(int, object)   # (index, result | Exception)
    all_done = Signal()

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self._jobs = list(jobs)

    def run(self):
        for i, job in enumerate(self._jobs):
            try:
                self.job_done.emit(i, job())
            except Exception as e:  # per-file isolation: one failure never kills the batch
                self.job_done.emit(i, e)
        self.all_done.emit()
