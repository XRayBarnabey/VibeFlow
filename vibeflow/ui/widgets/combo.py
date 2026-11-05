"""Combo box with a visible chevron (Qt stylesheets hide the native arrow)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox

from .. import theme


class ArrowComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(theme.COLORS["text_dim"]), 1.4))
        x = self.width() - 15.0
        y = self.height() / 2.0 - 2.0
        painter.drawLine(QPointF(x, y), QPointF(x + 4.0, y + 4.0))
        painter.drawLine(QPointF(x + 4.0, y + 4.0), QPointF(x + 8.0, y))
        painter.end()
