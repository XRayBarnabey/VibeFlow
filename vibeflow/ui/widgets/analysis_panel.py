"""Synchronization and flight data inspector."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class AnalysisPanel(QScrollArea):
    offsetChanged = Signal(float)
    autoSyncRequested = Signal()
    backendInstallRequested = Signal()
    backendStartRequested = Signal()
    backendStopRequested = Signal()
    backendLogsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 3, 6, 0)
        root.setSpacing(10)
        self.setWidget(content)

        # --- Local backend ------------------------------------------------
        card, layout = self._card("MOTEUR LOCAL ACE-STEP")
        self.backend_status = QLabel("Détection…")
        self.backend_status.setObjectName("Hint")
        self.backend_status.setWordWrap(True)
        layout.addWidget(self.backend_status)

        self.backend_path = QLabel("")
        self.backend_path.setObjectName("Hint")
        self.backend_path.setWordWrap(True)
        self.backend_path.hide()
        layout.addWidget(self.backend_path)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.install_button = QPushButton("Installer")
        self.install_button.setObjectName("Primary")
        self.install_button.setToolTip(
            "Télécharge ACE-Step 1.5 (2,4 Go), l'extrait dans VibeFlow et copie "
            "les modèles déjà présents si possible."
        )
        self.start_button = QPushButton("Démarrer")
        self.stop_button = QPushButton("Arrêter")
        self.logs_button = QPushButton("Journaux")
        self.logs_button.setObjectName("Ghost")
        for button in (
            self.install_button,
            self.start_button,
            self.stop_button,
            self.logs_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        root.addWidget(card)

        self.install_button.clicked.connect(self.backendInstallRequested.emit)
        self.start_button.clicked.connect(self.backendStartRequested.emit)
        self.stop_button.clicked.connect(self.backendStopRequested.emit)
        self.logs_button.clicked.connect(self.backendLogsRequested.emit)

        # --- Sync ----------------------------------------------------------
        card, layout = self._card("SYNCHRONISATION")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Décalage gyro → vidéo"), 0, 0)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-30.0, 30.0)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.05)
        self.offset.setSuffix(" s")
        self.offset.setToolTip("Décalage appliqué aux événements gyroscopiques.")
        grid.addWidget(self.offset, 0, 1)
        self.sync_button = QPushButton("Estimer")
        self.sync_button.setToolTip("Corréler le mouvement vidéo avec le gyroscope")
        grid.addWidget(self.sync_button, 0, 2)
        layout.addLayout(grid)

        self.sync_status = QLabel("Synchronisation manuelle")
        self.sync_status.setObjectName("Hint")
        self.sync_status.setWordWrap(True)
        layout.addWidget(self.sync_status)
        root.addWidget(card)

        # --- Data ----------------------------------------------------------
        card, layout = self._card("DONNÉES DU VOL")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(4)
        self.info_labels: dict[str, QLabel] = {}
        for row, key in enumerate(("Vidéo", "Gyroscope", "Fréquence", "Durée")):
            label = QLabel(key)
            label.setObjectName("Hint")
            value = QLabel("—")
            value.setObjectName("Value")
            value.setWordWrap(True)
            info_grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            info_grid.addWidget(value, row, 1)
            self.info_labels[key] = value
        layout.addLayout(info_grid)

        self.warnings = QLabel("")
        self.warnings.setObjectName("Warning")
        self.warnings.setWordWrap(True)
        self.warnings.hide()
        layout.addWidget(self.warnings)
        root.addWidget(card)

        note = QLabel("La synchronisation se règle au millième de seconde.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)

        self.offset.valueChanged.connect(self.offsetChanged.emit)
        self.sync_button.clicked.connect(self.autoSyncRequested.emit)

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        return card, layout

    def set_offset(self, value: float) -> None:
        self.offset.blockSignals(True)
        self.offset.setValue(value)
        self.offset.blockSignals(False)

    def set_backend(
        self,
        *,
        status: str,
        level: str,
        path: str,
        installed: bool,
        managed: bool,
        running: bool,
        busy: bool,
        external: bool = False,
    ) -> None:
        self.set_backend_status(status, level)
        self.backend_path.setText(path)
        self.backend_path.setVisible(bool(path))
        self.install_button.setVisible(not managed)
        self.install_button.setEnabled(not busy)
        self.start_button.setEnabled(installed and not running and not busy)
        self.stop_button.setEnabled(running and not external and not busy)
        self.logs_button.setEnabled(not busy)

    def set_backend_status(self, text: str, level: str = "hint") -> None:
        self.backend_status.setObjectName(
            {"hint": "Hint", "success": "Success", "warning": "Warning", "error": "Error"}.get(
                level, "Hint"
            )
        )
        self.backend_status.setText(text)
        self.backend_status.style().unpolish(self.backend_status)
        self.backend_status.style().polish(self.backend_status)

    def set_sync_status(self, text: str, level: str = "hint") -> None:
        self.sync_status.setObjectName(
            {"hint": "Hint", "success": "Success", "warning": "Warning", "error": "Error"}.get(
                level, "Hint"
            )
        )
        self.sync_status.setText(text)
        self.sync_status.style().unpolish(self.sync_status)
        self.sync_status.style().polish(self.sync_status)

    def set_info(self, key: str, value: str) -> None:
        if key in self.info_labels:
            self.info_labels[key].setText(value)

    def set_warnings(self, messages: list[str]) -> None:
        if messages:
            self.warnings.setText("⚠  " + "   ·   ".join(messages))
            self.warnings.show()
        else:
            self.warnings.hide()
