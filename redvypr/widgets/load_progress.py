"""
Progress dialog for slow actions with a callback ``progress(text, done, total)``, e.g. loading
an item library (redvypr.metadata_sources.load_item_library(progress=...)).

    with LoadProgress(window, 'Loading hf_sensor') as progress:
        redvypr.load_item_library(path, progress=progress)

The dialog appears after ``delay`` seconds only (fast actions show nothing), shows the text and a
bar (``total`` 0: busy, no bar), keeps the window responsive and has a Cancel button: the callback
then raises :class:`redvypr.metadata_sources.LoadCancelled`, which aborts the action (loading
reads everything first and changes nothing before it is complete).
"""

import time

from PyQt6 import QtCore, QtWidgets

from redvypr.metadata_sources import LoadCancelled


class LoadProgress:
    """Callback ``progress(text, done=0, total=0)`` with a progress dialog (context manager)."""

    def __init__(self, parent=None, title: str = 'Loading', delay: float = 0.3, interval: float = 0.05):
        self.delay = delay
        self.interval = interval
        self.start = time.monotonic()
        self._last = 0.0
        self._text = None
        self.dialog = QtWidgets.QProgressDialog('', 'Cancel', 0, 0, parent)
        self.dialog.setWindowTitle(title)
        self.dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.dialog.setMinimumWidth(460)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setMinimumDuration(2 ** 30)      # shown by the callback after the delay
        self.dialog.hide()
        self.shown = False

    @property
    def elapsed(self) -> float:
        """Seconds since the start."""
        return time.monotonic() - self.start

    def __call__(self, text: str, done: int = 0, total: int = 0):
        now = time.monotonic()
        changed = text != self._text
        if not changed and now - self._last < self.interval and not (total and done >= total):
            return
        self._last = now
        self._text = text
        if not self.shown:
            if now - self.start < self.delay:
                return
            self.dialog.show()
            self.shown = True
        self.dialog.setLabelText(text + (f'  ({done} / {total})' if total else ''))
        self.dialog.setMaximum(max(total, 0))
        self.dialog.setValue(min(done, total) if total else 0)
        QtWidgets.QApplication.processEvents()
        if self.dialog.wasCanceled():
            raise LoadCancelled()

    def close(self):
        self.dialog.hide()
        self.dialog.deleteLater()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
