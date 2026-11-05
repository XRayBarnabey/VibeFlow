"""Small colored status dot for the local ACE-Step server."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

STATE_COLORS = {
    "off": "#56616F",
    "starting": "#E0B15C",
    "ready": "#6FBF8B",
    "working": "#6FBF8B",
    "error": "#D97A7A",
}


class ServerDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._state = "off"
        self._blink_on = True
        self._timer = QTimer(self)
        self._timer.setInterval(520)
        self._timer.timeout.connect(self._blink)

    def set_state(self, state: str) -> None:
        self._state = state if state in STATE_COLORS else "off"
        if self._state == "working":
            self._blink_on = True
            self._timer.start()
        else:
            self._timer.stop()
            self._blink_on = True
        self.update()

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(STATE_COLORS[self._state])
        if self._state == "working" and not self._blink_on:
            color.setAlpha(55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(1, 1, 10, 10)
        if self._state in {"ready", "working"}:
            halo = QColor(color)
            halo.setAlpha(45)
            painter.setBrush(halo)
            painter.drawEllipse(0, 0, 12, 12)
        painter.end()
