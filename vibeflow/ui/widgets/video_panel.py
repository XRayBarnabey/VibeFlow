"""Video surface, empty state and transport controls."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from .timeline import format_time


class PlayButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Play")
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._playing = False

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.COLORS["text"]))
        if self._playing:
            painter.drawRoundedRect(QRectF(11, 10, 4.5, 14), 1.4, 1.4)
            painter.drawRoundedRect(QRectF(19, 10, 4.5, 14), 1.4, 1.4)
        else:
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(13, 9.5),
                        QPointF(24.5, 17),
                        QPointF(13, 24.5),
                    ]
                )
            )
        painter.end()


class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        light = theme.is_light()
        rect = self.rect()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor("#F7F9FB" if light else "#0C1013"))
        gradient.setColorAt(1.0, QColor("#EEF2F6" if light else "#10151A"))
        painter.fillRect(rect, gradient)

        # Subtle technical grid.
        grid = QColor(0, 0, 0, 10) if light else QColor(255, 255, 255, 7)
        painter.setPen(QPen(grid, 1))
        step = 42
        for x in range(0, rect.width(), step):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), step):
            painter.drawLine(0, y, rect.width(), y)

        cx, cy = rect.width() / 2, rect.height() / 2
        painter.setPen(QPen(QColor("#C7D2DE" if light else "#2B3643"), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - 30, cy - 66, 60, 60))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.COLORS["accent"]))
        painter.drawPolygon(
            [
                QPointF(cx - 5, cy - 52),
                QPointF(cx + 13, cy - 36),
                QPointF(cx - 5, cy - 20),
            ]
        )

        painter.setPen(QColor(theme.COLORS["text"]))
        font = QFont(self.font().family(), 20)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(0, cy + 6, rect.width(), 30), Qt.AlignmentFlag.AlignCenter, "VibeFlow")

        painter.setPen(QColor(theme.COLORS["text_dim"]))
        painter.setFont(QFont(self.font().family(), 9))
        painter.drawText(
            QRectF(0, cy + 38, rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "Déposez une vidéo FPV et son journal gyroscopique pour commencer",
        )
        painter.setPen(QColor(theme.COLORS["text_faint"]))
        painter.setFont(QFont(self.font().family(), 8))
        painter.drawText(
            QRectF(0, cy + 58, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            "MP4 · MOV · MKV      GCSV · CSV",
        )
        painter.end()


class VideoPanel(QFrame):
    playToggled = Signal()
    seekRequested = Signal(float)
    frameStepRequested = Signal(int)
    volumeChanged = Signal(int)
    sourceSelected = Signal(str)
    manualModeToggled = Signal(bool)
    originalAudioToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.empty = EmptyState()
        self.video = QVideoWidget()
        self.video.setStyleSheet("background-color: #07090B;")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.video)
        layout.addWidget(self.stack, 1)

        transport = QFrame()
        transport.setObjectName("Transport")
        transport.setFixedHeight(46)
        row = QHBoxLayout(transport)
        row.setContentsMargins(10, 4, 12, 4)
        row.setSpacing(4)

        self.back_button = self._transport_button("−5 s", "Reculer de 5 secondes")
        self.prev_frame = self._transport_button("◀|", "Image précédente")
        self.play_button = PlayButton()
        self.play_button.setToolTip("Lecture / pause (Espace)")
        self.next_frame = self._transport_button("|▶", "Image suivante")
        self.forward_button = self._transport_button("+5 s", "Avancer de 5 secondes")

        self.time_label = QLabel("00:00.000")
        self.time_label.setObjectName("Timecode")
        self.total_label = QLabel("/ 00:00.000")
        self.total_label.setObjectName("TimecodeDim")

        row.addWidget(self.back_button)
        row.addWidget(self.prev_frame)
        row.addWidget(self.play_button)
        row.addWidget(self.next_frame)
        row.addWidget(self.forward_button)
        row.addSpacing(12)
        row.addWidget(self.time_label)
        row.addWidget(self.total_label)
        row.addSpacing(14)

        self.source_buttons: dict[str, QPushButton] = {}
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        for key, label in (
            ("local", "VibeFlow"),
            ("ai", "ACE-Step"),
            ("hybrid", "Hybride"),
        ):
            button = QPushButton(label)
            button.setObjectName("SourceToggle")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(24)
            button.setMinimumWidth({"local": 72, "ai": 68, "hybrid": 62}[key])
            button.setToolTip(
                {
                    "local": "Préécoute du moteur local VibeFlow",
                    "ai": "Nappe ACE-Step seule",
                    "hybrid": "Nappe ACE-Step + rythme VibeFlow",
                }[key]
            )
            button.clicked.connect(lambda _checked, k=key: self.sourceSelected.emit(k))
            self.source_group.addButton(button)
            self.source_buttons[key] = button
            row.addWidget(button)
        self.manual_button = QPushButton("Marquer")
        self.manual_button.setObjectName("SourceToggle")
        self.manual_button.setCheckable(True)
        self.manual_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_button.setFixedHeight(24)
        self.manual_button.setMinimumWidth(66)
        self.manual_button.setToolTip(
            "Mode accents manuels : les flèches placent un marqueur à la position "
            "courante. Les touches et sons se configurent dans le panneau Musique."
        )
        self.manual_button.toggled.connect(self.manualModeToggled.emit)
        row.addWidget(self.manual_button)
        self.audio_button = QPushButton("Audio vidéo")
        self.audio_button.setObjectName("SourceToggle")
        self.audio_button.setCheckable(True)
        self.audio_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audio_button.setFixedHeight(24)
        self.audio_button.setMinimumWidth(84)
        self.audio_button.setToolTip(
            "Ajouter le son d'origine de la vidéo à la musique (pour se repérer)."
        )
        self.audio_button.toggled.connect(self.originalAudioToggled.emit)
        row.addWidget(self.audio_button)
        row.addStretch(1)

        volume_icon = QLabel("VOL")
        volume_icon.setObjectName("Hint")
        volume_icon.setStyleSheet("font-size: 9px; letter-spacing: 1px;")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(92)
        self.volume.setToolTip("Volume")
        row.addWidget(volume_icon)
        row.addWidget(self.volume)
        layout.addWidget(transport)

        self.play_button.clicked.connect(self.playToggled.emit)
        self.volume.valueChanged.connect(self.volumeChanged.emit)
        self.back_button.clicked.connect(lambda: self._seek_relative(-5.0))
        self.forward_button.clicked.connect(lambda: self._seek_relative(5.0))
        self.prev_frame.clicked.connect(lambda: self.frameStepRequested.emit(-1))
        self.next_frame.clicked.connect(lambda: self.frameStepRequested.emit(1))

        self._duration = 0.0
        self._position = 0.0
        self.set_source_state({}, "local")

    def _transport_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("Transport")
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_source_state(self, available: dict[str, bool], current: str) -> None:
        for key, button in self.source_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == current and available.get(key, False))
            button.setEnabled(available.get(key, False))
            button.blockSignals(False)

    def _seek_relative(self, delta: float) -> None:
        target = min(max(self._position + delta, 0.0), max(self._duration, 0.0))
        self.seekRequested.emit(target)

    def show_video(self, visible: bool) -> None:
        self.stack.setCurrentWidget(self.video if visible else self.empty)

    def set_duration(self, duration: float) -> None:
        self._duration = max(0.0, duration)
        self.total_label.setText(f"/ {format_time(self._duration, decimals=True)}")

    def set_position(self, seconds: float) -> None:
        self._position = max(0.0, seconds)
        self.time_label.setText(format_time(self._position, decimals=True))

    def set_playing(self, playing: bool) -> None:
        self.play_button.set_playing(bool(playing))

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.play_button,
            self.back_button,
            self.forward_button,
            self.prev_frame,
            self.next_frame,
        ):
            widget.setEnabled(enabled)
