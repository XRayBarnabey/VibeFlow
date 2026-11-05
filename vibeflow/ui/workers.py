"""Background jobs so heavy processing never freezes the interface."""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, float)


class Worker(QRunnable):
    """Run ``fn(progress)`` in a pool thread and report through signals."""

    def __init__(self, fn: Callable[[Callable[[str, float], None]], object], parent=None):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    def _emit_progress(self, message: str, fraction: float) -> None:
        try:
            self.signals.progress.emit(message, fraction)
        except RuntimeError:
            pass  # window closed while the job was still running

    def run(self) -> None:
        try:
            result = self.fn(self._emit_progress)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            traceback.print_exc()
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                pass
        else:
            try:
                self.signals.finished.emit(result)
            except RuntimeError:
                pass


class TaskRunner(QObject):
    """Thin helper that keeps references to running workers."""

    def __init__(self, parent=None, max_threads: int = 2):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._workers: list[Worker] = []
        self._signals: list[WorkerSignals] = []

    def _release(self, worker: Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if worker.signals in self._signals:
            self._signals.remove(worker.signals)

    def start(
        self,
        fn: Callable[[Callable[[str, float], None]], object],
        *,
        on_finished=None,
        on_failed=None,
        on_progress=None,
    ) -> Worker:
        worker = Worker(fn)
        # Give the signals a real QObject parent: otherwise PySide may garbage
        # collect them while a long generation is still emitting progress.
        worker.signals.setParent(self)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        if on_failed:
            worker.signals.failed.connect(on_failed)
        if on_progress:
            worker.signals.progress.connect(on_progress)
        self._workers.append(worker)
        self._signals.append(worker.signals)
        worker.signals.finished.connect(lambda _r, w=worker: self._release(w))
        worker.signals.failed.connect(lambda _e, w=worker: self._release(w))
        self.pool.start(worker)
        return worker

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self.pool.waitForDone(timeout_ms)
