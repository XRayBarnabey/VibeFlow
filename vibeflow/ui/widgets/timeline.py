"""Professional timeline: gyro curves, detected figures, beat grid, playhead."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from ...core.analysis import FlightAnalysis, FlightEvent
from ...core.rhythm import ManualAccent, ManualTrack, RhythmPlan
from .. import theme

SECTION_LABELS = {
    "intro": "Intro",
    "build": "Montée",
    "groove": "Groove",
    "peak": "Pic",
    "break": "Rupture",
}


def format_time(seconds: float, decimals: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    if decimals:
        return f"{minutes:02d}:{rest:06.3f}".replace(".", ",")
    return f"{minutes:02d}:{int(rest):02d}"


class Timeline(QWidget):
    seekRequested = Signal(float)
    eventSelected = Signal(int)
    manualAccentSelected = Signal(int)
    viewChanged = Signal(float, float)

    RULER_H = 18
    EVENT_H = 34
    BEAT_H = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analysis: FlightAnalysis | None = None
        self._plan: RhythmPlan | None = None
        self._events: list[FlightEvent] = []
        self._manual: list[ManualAccent] = []
        self._manual_tracks: list[ManualTrack] = []
        self._selected_manual: int | None = None
        self._duration = 0.0
        self._offset = 0.0
        self._position = 0.0
        self._view = (0.0, 1.0)
        self._selected: int | None = None
        self._hover_x: float | None = None
        self._tooltip_index: int | None = None
        self._cache: QPixmap | None = None
        self._cache_size = (0, 0)

    # ------------------------------------------------------------------ data
    def set_data(
        self,
        analysis: FlightAnalysis | None,
        plan: RhythmPlan | None,
        events: list[FlightEvent] | None = None,
        offset: float = 0.0,
    ) -> None:
        self._analysis = analysis
        self._plan = plan
        self._events = events or []
        self._offset = offset
        duration = analysis.duration if analysis else (plan.duration if plan else 0.0)
        if duration > 0:
            previous = self._duration
            self._duration = duration
            if previous <= 0 or abs(duration - previous) > 1.0:
                self._view = (0.0, duration)
            else:
                start, end = self._view
                span = min(end - start, duration)
                start = min(max(0.0, start), max(0.0, duration - span))
                self._view = (start, start + span)
            self.viewChanged.emit(*self._view)
        self._invalidate()

    def set_events(self, events: list[FlightEvent]) -> None:
        self._events = events
        self._invalidate()

    def set_plan(self, plan: RhythmPlan | None) -> None:
        self._plan = plan
        self._invalidate()

    def set_manual_accents(self, accents: list[ManualAccent] | None) -> None:
        self._manual = list(accents or [])
        self._invalidate()

    def set_manual_tracks(self, tracks: list[ManualTrack] | None) -> None:
        self._manual_tracks = list(tracks or [])
        self._update_min_height()
        self._invalidate()

    def set_selected_manual(self, index: int | None) -> None:
        self._selected_manual = index
        self._invalidate()

    def _manual_lane_height(self) -> float:
        if not self._manual_tracks:
            return 0.0
        return float(max(24, min(140, 12 * len(self._manual_tracks) + 6)))

    def _update_min_height(self) -> None:
        self.setMinimumHeight(int(150 + self._manual_lane_height()))

    def set_position(self, seconds: float) -> None:
        self._position = float(seconds)
        self.update()

    def set_selected(self, index: int | None) -> None:
        self._selected = index
        self._invalidate()

    def reset_view(self) -> None:
        if self._duration > 0:
            self._view = (0.0, self._duration)
            self._invalidate()
            self.viewChanged.emit(*self._view)

    def current_view(self) -> tuple[float, float]:
        return self._view

    def refresh_theme(self) -> None:
        self._cache = None
        self.update()

    def _invalidate(self) -> None:
        self._cache = None
        self.update()

    # ---------------------------------------------------------------- mapping
    def _plot_rect(self) -> QRectF:
        return QRectF(8, 8, max(1, self.width() - 16), max(1, self.height() - 16))

    def _x(self, t: float) -> float:
        start, end = self._view
        span = max(end - start, 1e-6)
        left = self._plot_rect().left()
        width = self._plot_rect().width()
        return left + (t - start) / span * width

    def _t(self, x: float) -> float:
        start, end = self._view
        span = max(end - start, 1e-6)
        left = self._plot_rect().left()
        width = max(self._plot_rect().width(), 1)
        return start + (x - left) / width * span

    def _lanes(self) -> tuple[QRectF, QRectF, QRectF, QRectF]:
        rect = self._plot_rect()
        ruler = QRectF(rect.left(), rect.top(), rect.width(), self.RULER_H)
        events = QRectF(rect.left(), ruler.bottom() + 2, rect.width(), self.EVENT_H)
        beats = QRectF(rect.left(), rect.bottom() - self.BEAT_H, rect.width(), self.BEAT_H)
        manual_h = self._manual_lane_height()
        manual = QRectF(
            rect.left(),
            events.bottom() + 2,
            rect.width(),
            manual_h,
        )
        gyro_top = manual.bottom() + 2 if manual_h > 0 else events.bottom() + 4
        gyro = QRectF(
            rect.left(),
            gyro_top,
            rect.width(),
            max(20, beats.top() - gyro_top - 2),
        )
        return ruler, events, manual, gyro

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._cache is None or self._cache_size != (self.width(), self.height()):
            self._cache = self._render_static()
            self._cache_size = (self.width(), self.height())
        painter.drawPixmap(0, 0, self._cache)

        ruler, events_rect, _, _ = self._lanes()
        if self._hover_x is not None and self._duration > 0:
            x = self._hover_x
            painter.setPen(QPen(QColor(*theme.TIMELINE["hover"]), 1))
            painter.drawLine(int(x), int(ruler.bottom()), int(x), int(self._plot_rect().bottom()))
            t = self._t(x)
            label = format_time(t, decimals=True)
            painter.setFont(QFont(self.font().family(), 8))
            metrics = painter.fontMetrics()
            w = metrics.horizontalAdvance(label) + 10
            y = ruler.top() + 1
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.TIMELINE["tooltip_bg"]))
            painter.drawRoundedRect(QRectF(min(x + 6, self.width() - w - 4), y, w, 15), 3, 3)
            painter.setPen(QColor(theme.TIMELINE["tooltip_text"]))
            painter.drawText(QRectF(min(x + 6, self.width() - w - 4), y, w, 15), Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QPen(QColor(*theme.TIMELINE["hover_soft"]), 1))
            painter.drawLine(int(x), int(events_rect.bottom()), int(x), int(self._plot_rect().bottom()))

        if self._duration > 0:
            x = self._x(self._position)
            if self._plot_rect().left() - 1 <= x <= self._plot_rect().right() + 1:
                painter.setPen(QPen(QColor(theme.TIMELINE["playhead"]), 1.2))
                painter.drawLine(int(x), int(ruler.top()), int(x), int(self._plot_rect().bottom()))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.TIMELINE["playhead"]))
                painter.drawPolygon(
                    [
                        QPoint(int(x) - 3, int(ruler.top())),
                        QPoint(int(x) + 3, int(ruler.top())),
                        QPoint(int(x), int(ruler.top()) + 5),
                    ]
                )
        painter.end()

    def _render_static(self) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._plot_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.TIMELINE["bg"]))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QPen(QColor(theme.TIMELINE["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 5, 5)

        ruler, events_rect, manual_rect, gyro = self._lanes()
        self._draw_ruler(painter, ruler)
        self._draw_sections(painter, gyro)
        self._draw_gyro(painter, gyro)
        self._draw_beats(painter, gyro)
        self._draw_events(painter, events_rect)
        self._draw_manual_lane(painter, manual_rect)
        painter.end()
        return pixmap

    def _draw_ruler(self, painter: QPainter, ruler: QRectF) -> None:
        start, end = self._view
        span = max(end - start, 1e-6)
        target_ticks = max(3, int(ruler.width() / 90))
        raw_step = span / target_ticks
        steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
        step = next((s for s in steps if s >= raw_step), steps[-1])
        first = np.ceil(start / step) * step
        painter.setFont(QFont(self.font().family(), 8))
        ticks = np.arange(first, end + step * 0.5, step)
        for tick in ticks:
            x = self._x(tick)
            painter.setPen(QPen(QColor(theme.TIMELINE["ruler_line"]), 1))
            painter.drawLine(int(x), int(ruler.bottom() - 5), int(x), int(ruler.bottom()))
            painter.setPen(QColor(theme.TIMELINE["ruler_text"]))
            painter.drawText(
                QRectF(x + 4, ruler.top(), 82, 13),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                format_time(tick, decimals=step < 1.0),
            )
        painter.setPen(QPen(QColor(theme.TIMELINE["baseline"]), 1))
        painter.drawLine(int(ruler.left()), int(ruler.bottom()), int(ruler.right()), int(ruler.bottom()))

    def _draw_sections(self, painter: QPainter, gyro: QRectF) -> None:
        if not self._plan or not self._plan.sections:
            return
        painter.setFont(QFont(self.font().family(), 7))
        last_label_right = -1e9
        for section in self._plan.sections:
            x0 = max(self._x(section.start), gyro.left())
            x1 = min(self._x(section.end), gyro.right())
            if x1 <= x0:
                continue
            tint = QColor(theme.TIMELINE["section_peak"]) if section.name in {"peak", "groove"} else QColor(theme.TIMELINE["section_alt"])
            tint.setAlpha(110)
            painter.fillRect(QRectF(x0, gyro.top(), x1 - x0, gyro.height()), tint)
            if x1 - x0 >= 72 and x0 >= last_label_right + 10:
                label_color = QColor(theme.TIMELINE["section_label"])
                label_color.setAlpha(200)
                painter.setPen(label_color)
                painter.drawText(
                    QRectF(x0 + 5, gyro.top() + 2, x1 - x0 - 8, 12),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    SECTION_LABELS.get(section.name, section.name).upper(),
                )
                last_label_right = x0 + 5 + painter.fontMetrics().horizontalAdvance(
                    SECTION_LABELS.get(section.name, section.name).upper()
                )
            painter.setPen(QPen(QColor(theme.TIMELINE["section_line"]), 1))
            painter.drawLine(int(x0), int(gyro.top()), int(x0), int(gyro.bottom()))

    def _draw_gyro(self, painter: QPainter, gyro: QRectF) -> None:
        if not self._analysis or gyro.height() < 20:
            painter.setPen(QColor(theme.TIMELINE["hint"]))
            painter.setFont(QFont(self.font().family(), 9))
            painter.drawText(
                gyro,
                Qt.AlignmentFlag.AlignCenter,
                "Importez des données gyroscopiques pour révéler le pilotage",
            )
            return

        lanes = 3
        content = QRectF(gyro.left(), gyro.top() + 13, gyro.width(), max(12, gyro.height() - 13))
        lane_h = content.height() / lanes
        start, end = self._view
        rates = self._analysis.rates_deg
        track_t = self._analysis.track.t
        index0 = int(np.searchsorted(track_t, start))
        index1 = int(np.searchsorted(track_t, end))
        if index1 - index0 < 2:
            return
        segment = np.abs(rates[max(0, index0 - 1) : min(len(track_t), index1 + 1)])
        scale = float(np.percentile(segment, 99.5)) if segment.size else 1.0
        scale = max(scale, 25.0)
        width = max(1, int(gyro.width()))

        for lane in range(lanes):
            top = content.top() + lane * lane_h
            center = top + lane_h / 2
            amplitude = lane_h * 0.42
            color = QColor(theme.AXIS_COLORS[lane])

            painter.setPen(QPen(QColor(theme.TIMELINE["lane_center"]), 1))
            painter.drawLine(int(gyro.left()), int(center), int(gyro.right()), int(center))
            label_color = QColor(theme.TIMELINE["axis_label"])
            label_color.setAlpha(170)
            painter.setPen(label_color)
            painter.setFont(QFont(self.font().family(), 7))
            painter.drawText(
                QRectF(gyro.left() + 5, top + 1, 34, 12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                ("R", "P", "Y")[lane],
            )
            values = rates[max(0, index0 - 1) : min(len(track_t), index1 + 1), lane]
            if values.size < 2:
                continue
            mins, maxs, count = self._columns(values, width)
            xs = np.linspace(self._x(start), self._x(end), count)
            top_curve = [QPoint(int(x), int(center - np.clip(v / scale, -1, 1) * amplitude)) for x, v in zip(xs, maxs)]
            bottom_curve = [QPoint(int(x), int(center - np.clip(v / scale, -1, 1) * amplitude)) for x, v in zip(xs, mins)]
            polygon = top_curve + bottom_curve[::-1]
            fill = QColor(color)
            fill.setAlpha(38)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(polygon)

            path = QPainterPath()
            mid = (mins + maxs) / 2
            for i, (x, v) in enumerate(zip(xs, mid)):
                y = center - float(np.clip(v / scale, -1, 1)) * amplitude
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            line = QColor(color)
            line.setAlpha(215)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(line, 1.1))
            painter.drawPath(path)

    @staticmethod
    def _columns(values: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray, int]:
        n = len(values)
        width = max(1, min(width, n))
        if n <= width * 2:
            return values, values, n
        edges = np.unique(np.linspace(0, n, width + 1).astype(int))
        if len(edges) < 2:
            return values[:1], values[:1], 1
        starts = edges[:-1]
        mins = np.minimum.reduceat(values, starts)
        maxs = np.maximum.reduceat(values, starts)
        return mins, maxs, len(starts)

    def _draw_beats(self, painter: QPainter, gyro: QRectF) -> None:
        if not self._plan:
            return
        y = gyro.bottom()
        painter.setPen(QPen(QColor(theme.TIMELINE["beat_bar"]), 1))
        for beat in self._plan.beats():
            if not (self._view[0] <= beat <= self._view[1]):
                continue
            x = self._x(beat)
            bar_beat = beat / self._plan.beat_period
            is_bar = abs(bar_beat - round(bar_beat)) < 1e-6 and int(round(bar_beat)) % 4 == 0
            painter.setPen(QPen(QColor(theme.TIMELINE["beat_bar"]) if is_bar else QColor(theme.TIMELINE["beat"]), 1))
            painter.drawLine(int(x), int(y + 3), int(x), int(y + (7 if is_bar else 5)))

    def _draw_events(self, painter: QPainter, lane: QRectF) -> None:
        if not self._events:
            return
        for event in self._events:
            t = event.t_peak + self._offset
            if not (self._view[0] - 0.2 <= t <= self._view[1] + 0.2):
                continue
            x = self._x(t)
            color = QColor(event.color)
            selected = event.index == self._selected
            height = 6 + 18 * event.score
            top = lane.bottom() - height
            pen = QPen(color, 2 if not selected else 2.4)
            painter.setPen(pen)
            painter.drawLine(int(x), int(top), int(x), int(lane.bottom() - 1))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color if event.enabled else QColor(70, 80, 92))
            painter.drawEllipse(QRectF(x - 2.4, top - 5, 4.8, 4.8))
            if selected:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(theme.TIMELINE["playhead"]), 1))
                painter.drawEllipse(QRectF(x - 6, top - 8.5, 12, 12))
        painter.setPen(QPen(QColor(theme.TIMELINE["baseline"]), 1))
        painter.drawLine(int(lane.left()), int(lane.bottom()), int(lane.right()), int(lane.bottom()))

    def _manual_row_rects(self, lane: QRectF) -> list[QRectF]:
        count = len(self._manual_tracks)
        if count == 0 or lane.height() <= 0:
            return []
        row_h = lane.height() / count
        return [
            QRectF(lane.left(), lane.top() + index * row_h, lane.width(), row_h)
            for index in range(count)
        ]

    def _manual_marker_at(self, pos) -> int | None:
        _, _, manual_rect, _ = self._lanes()
        rows = self._manual_row_rects(manual_rect)
        if not rows:
            return None
        lane = min(
            len(rows) - 1,
            max(0, int((pos.y() - manual_rect.top()) / max(1.0, manual_rect.height() / len(rows)))),
        )
        best: tuple[float, int] | None = None
        for index, marker in enumerate(self._manual):
            if marker.lane != lane:
                continue
            distance = abs(self._x(marker.time) - pos.x())
            if distance <= 8 and (best is None or distance < best[0]):
                best = (distance, index)
        return best[1] if best else None

    def _draw_manual_lane(self, painter: QPainter, lane: QRectF) -> None:
        if lane.height() <= 0 or not self._manual_tracks:
            return
        painter.setPen(QPen(QColor(theme.TIMELINE["section_line"]), 1))
        painter.setBrush(QColor(theme.TIMELINE["section_alt"]))
        painter.drawRoundedRect(lane, 3, 3)
        rows = self._manual_row_rects(lane)
        for index, (track, row) in enumerate(zip(self._manual_tracks, rows)):
            color = QColor(track.color)
            painter.setPen(QPen(QColor(theme.TIMELINE["lane_center"]), 1))
            painter.drawLine(
                int(lane.left()), int(row.top()), int(lane.right()), int(row.top())
            )
            strip = QColor(color)
            if not track.enabled:
                strip.setAlpha(70)
            painter.fillRect(
                QRectF(lane.left() + 1, row.top() + 1, 3, max(1, row.height() - 2)),
                strip,
            )
            center_y = row.top() + row.height() / 2
            for marker_index, marker in enumerate(self._manual):
                if marker.lane != index:
                    continue
                x = self._x(marker.time)
                if x < lane.left() - 5 or x > lane.right() + 5:
                    continue
                fill = QColor(color)
                if not track.enabled:
                    fill.setAlpha(80)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawEllipse(QRectF(x - 3.5, center_y - 3.5, 7, 7))
                if marker_index == self._selected_manual:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(theme.TIMELINE["playhead"]), 1.4))
                    painter.drawEllipse(QRectF(x - 6.5, center_y - 6.5, 13, 13))

    # ------------------------------------------------------------- interaction
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration <= 0:
            return
        _, events_rect, manual_rect, _ = self._lanes()
        if manual_rect.height() > 0 and manual_rect.contains(event.position()):
            index = self._manual_marker_at(event.position())
            if index is not None:
                self._selected_manual = index
                self._invalidate()
                self.manualAccentSelected.emit(index)
                self.seekRequested.emit(
                    float(
                        np.clip(
                            self._manual[index].time,
                            0,
                            self._duration,
                        )
                    )
                )
                return
            self.seekRequested.emit(
                float(np.clip(self._t(event.position().x()), 0, self._duration))
            )
            return
        if events_rect.top() <= event.position().y() <= events_rect.bottom() + 4:
            nearest = self._nearest_event(event.position().x())
            if nearest is not None:
                self._selected = nearest.index
                self._invalidate()
                self.eventSelected.emit(nearest.index)
                self.seekRequested.emit(float(np.clip(nearest.t_peak + self._offset, 0, self._duration)))
                return
        self.seekRequested.emit(float(np.clip(self._t(event.position().x()), 0, self._duration)))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover_x = event.position().x()
        _, events_rect, _, _ = self._lanes()
        nearest = None
        if events_rect.top() - 6 <= event.position().y() <= events_rect.bottom() + 6:
            nearest = self._nearest_event(event.position().x())
        if nearest is not None and nearest.index != self._tooltip_index:
            self._tooltip_index = nearest.index
            from PySide6.QtWidgets import QToolTip

            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"{nearest.label}\n{format_time(nearest.t_peak + self._offset, decimals=True)}"
                f" · pertinence {nearest.score * 100:.0f} %",
                self,
            )
        elif nearest is None:
            self._tooltip_index = None
        if event.buttons() & Qt.MouseButton.LeftButton and self._duration > 0:
            self.seekRequested.emit(float(np.clip(self._t(event.position().x()), 0, self._duration)))
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()

    def _nearest_event(self, x: float) -> FlightEvent | None:
        best, best_dx = None, 10.0
        for event in self._events:
            dx = abs(self._x(event.t_peak + self._offset) - x)
            if dx < best_dx:
                best, best_dx = event, dx
        return best

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._duration <= 0:
            return
        start, end = self._view
        span = end - start
        cursor_t = self._t(event.position().x())
        factor = 0.82 if event.angleDelta().y() > 0 else 1.22
        new_span = float(np.clip(span * factor, 1.5, self._duration))
        ratio = (cursor_t - start) / max(span, 1e-6)
        new_start = cursor_t - ratio * new_span
        new_start = float(np.clip(new_start, 0.0, max(0.0, self._duration - new_span)))
        self._view = (new_start, new_start + new_span)
        self._invalidate()
        self.viewChanged.emit(*self._view)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.reset_view()
