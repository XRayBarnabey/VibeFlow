"""Detected figure list with per-event enable toggles."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...core.analysis import AXIS_LABELS, FlightEvent, KIND_LABELS
from ..theme import COLORS
from .timeline import format_time


class EventTable(QTableWidget):
    eventToggled = Signal(int, bool)
    eventActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["", "TEMPS", "FIGURE", "SCORE"])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 26)
        self.setColumnWidth(1, 76)
        self.setColumnWidth(3, 44)
        self.verticalHeader().setDefaultSectionSize(25)
        self._loading = False
        self.itemChanged.connect(self._on_item_changed)
        self.cellClicked.connect(self._on_cell_clicked)

    def populate(self, events: list[FlightEvent]) -> None:
        self._loading = True
        self.setRowCount(0)
        self.setRowCount(len(events))
        for row, event in enumerate(events):
            check = QTableWidgetItem("")
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.CheckState.Checked if event.enabled else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, event.index)
            self.setItem(row, 0, check)

            time_item = QTableWidgetItem(format_time(event.t_peak, decimals=True))
            time_item.setForeground(QColor(COLORS["text_dim"]))
            time_item.setData(Qt.ItemDataRole.UserRole, event.index)
            self.setItem(row, 1, time_item)

            dot = "● "
            label = f"{dot}{KIND_LABELS.get(event.kind, event.kind)}"
            if event.kind not in {"switch", "accel", "brake", "flow", "combo"}:
                label += f" · {AXIS_LABELS[event.axis].lower()}"
            name_item = QTableWidgetItem(label)
            name_item.setForeground(
                QColor(event.color) if event.enabled else QColor(COLORS["text_faint"])
            )
            name_item.setData(Qt.ItemDataRole.UserRole, event.index)
            name_item.setToolTip(
                f"{event.label}\nAngle {abs(event.angle_deg):.0f}° · "
                f"vitesse crête {event.peak_rate_dps:.0f}°/s\n"
                f"Score de pertinence {event.score * 100:.0f} %"
            )
            self.setItem(row, 2, name_item)

            score_item = QTableWidgetItem(f"{event.score * 100:.0f}")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            score_item.setForeground(QColor(COLORS["accent"] if event.score >= 0.6 else COLORS["text_dim"]))
            score_item.setData(Qt.ItemDataRole.UserRole, event.index)
            self.setItem(row, 3, score_item)
        self._loading = False

    def select_event(self, index: int) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 2)
            if item and item.data(Qt.ItemDataRole.UserRole) == index:
                self.blockSignals(True)
                self.selectRow(row)
                self.blockSignals(False)
                self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
                return

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        self.eventToggled.emit(int(index), item.checkState() == Qt.CheckState.Checked)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        item = self.item(row, 2)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None:
            self.eventActivated.emit(int(index))
