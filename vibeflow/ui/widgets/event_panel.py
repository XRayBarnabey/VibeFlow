"""Detected figures panel with its own toolbar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .event_table import EventTable


class EventPanel(QFrame):
    eventToggled = Signal(int, bool)
    eventActivated = Signal(int)
    enableAllRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(12, 0, 8, 6)
        title = QLabel("ÉVÉNEMENTS DÉTECTÉS")
        title.setObjectName("SectionTitle")
        self.count = QLabel("0")
        self.count.setObjectName("Value")
        self.enable_all = QPushButton("Tout activer")
        self.enable_all.setObjectName("Ghost")
        self.enable_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.enable_all.clicked.connect(self.enableAllRequested.emit)
        row.addWidget(title)
        row.addSpacing(5)
        row.addWidget(self.count)
        row.addStretch(1)
        row.addWidget(self.enable_all)
        layout.addLayout(row)

        self.table = EventTable()
        layout.addWidget(self.table, 1)

        self.table.eventToggled.connect(self.eventToggled.emit)
        self.table.eventActivated.connect(self.eventActivated.emit)
