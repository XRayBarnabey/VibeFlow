"""Analysis, synchronization and pre-listen controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.drums import KIT_LABELS
from ...core.rhythm import (
    ACCENT_LABELS,
    MANUAL_SOUND_LABELS,
    RhythmPlan,
    SoundSettings,
)
from .. import theme
from .combo import ArrowComboBox
from .server_status import ServerDot


class ShortcutEdit(QKeySequenceEdit):
    """Key-sequence editor that releases global shortcuts while capturing."""

    captureStarted = Signal()
    captureFinished = Signal()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.captureStarted.emit()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.captureFinished.emit()


class ControlPanel(QScrollArea):
    sensitivityChanged = Signal(float)
    sensitivityCommitted = Signal(float)
    regenerateRequested = Signal()
    styleChanged = Signal(str)
    soundChanged = Signal()
    aiGenerateRequested = Signal()
    serverToggleRequested = Signal()
    manualSoundChanged = Signal(int, str)
    manualKeyChanged = Signal(int, str)
    manualUndoRequested = Signal()
    manualClearRequested = Signal()
    manualCaptureStarted = Signal()
    manualCaptureFinished = Signal()
    manualTrackAdded = Signal()
    manualTrackRemoved = Signal(int)
    manualTrackSoundChanged = Signal(int, str)
    manualTrackKeyChanged = Signal(int, str)
    manualTrackColorChanged = Signal(int, str)
    manualTrackEnabledChanged = Signal(int, bool)
    manualTrackNameChanged = Signal(int, str)
    manualMoveSettingsChanged = Signal(str, str, int)
    manualDeleteSelectedRequested = Signal()

    PROMPT_PRESETS = (
        (
            "Évasion cinématique",
            "cinematic ambient, felt piano, warm pads, soft sub bass, no drums, "
            "no vocals, spacious reverb, emotional, slow build, instrumental",
        ),
        (
            "Techno mélodique",
            "melodic progressive techno, 127 BPM, A minor, 4/4, deep rolling "
            "bassline, tight kick, atmospheric pads, hypnotic, instrumental",
        ),
        (
            "Deep / dub techno",
            "deep dub techno, 122 BPM, A minor, 4/4, warm sub bass, soft kick, "
            "sparse percussion, dub chords, tape delay, atmospheric, instrumental",
        ),
        (
            "Piano ambient",
            "intimate ambient piano, felt piano, soft strings, warm analog pads, "
            "no drums, slow, emotional, spacious reverb, instrumental",
        ),
        (
            "Liquid drum & bass",
            "liquid drum and bass, 174 BPM, A minor, rolling breakbeat, deep "
            "sub bass, lush pads, atmospheric, instrumental",
        ),
        (
            "Trailer orchestral",
            "cinematic trailer music, orchestral strings, low brass, hybrid "
            "percussion, tension and release, epic, instrumental",
        ),
        (
            "Lo-fi downtempo",
            "lo-fi downtempo, 84 BPM, warm Rhodes, dusty drums, vinyl texture, "
            "mellow, intimate, instrumental",
        ),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 3, 6, 0)
        root.setSpacing(10)

        # --- Pre-listen ----------------------------------------------------
        card, layout = self._card("PRÉÉCOUTE RYTHMIQUE")
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        style_row.addWidget(QLabel("Style"))
        self.style_combo = ArrowComboBox()
        self.style_combo.addItem("Évasion de l'esprit", "evasion")
        self.style_combo.addItem("Pulse rythmique", "pulse")
        self.style_combo.setToolTip(
            "Évasion : ambiant cinématique, lent et aérien.\n"
            "Pulse : rythmique club, plus dense et percussif."
        )
        style_row.addWidget(self.style_combo, 1)
        layout.addLayout(style_row)
        self.style_hint = QLabel("")
        self.style_hint.setObjectName("Hint")
        self.style_hint.setWordWrap(True)
        layout.addWidget(self.style_hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.sensitivity_value = QLabel("50 %")
        self.sensitivity_value.setObjectName("Value")
        self.sensitivity_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(QLabel("Sensibilité"))
        row.addStretch(1)
        row.addWidget(self.sensitivity_value)
        layout.addLayout(row)

        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity.setToolTip(
            "Faible : figures spectaculaires uniquement\nÉlevé : mouvements plus subtils"
        )
        layout.addWidget(self.sensitivity)

        legend = QHBoxLayout()
        low = QLabel("Faible")
        high = QLabel("Élevé")
        low.setObjectName("Hint")
        high.setObjectName("Hint")
        legend.addWidget(low)
        legend.addStretch(1)
        legend.addWidget(high)
        layout.addLayout(legend)

        self.generate_button = QPushButton("Régénérer la préécoute")
        self.generate_button.setObjectName("Primary")
        self.generate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.generate_button)

        self.plan_stats = QLabel("—")
        self.plan_stats.setObjectName("Hint")
        self.plan_stats.setWordWrap(True)
        layout.addWidget(self.plan_stats)
        root.addWidget(card)

        # --- ACE-Step ------------------------------------------------------
        card, layout = self._card("GÉNÉRATION IA — ACE-STEP")
        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        server_row.addWidget(QLabel("Serveur"))
        self.ai_server = QLineEdit("http://127.0.0.1:8021")
        self.ai_server.setPlaceholderText("http://127.0.0.1:8021")
        self.ai_server.setToolTip("Adresse du serveur ACE-Step local.")
        server_row.addWidget(self.ai_server, 1)
        layout.addLayout(server_row)

        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        self.server_dot = ServerDot()
        self.server_state_label = QLabel("Serveur arrêté")
        self.server_state_label.setObjectName("Hint")
        self.server_eta = QLabel("")
        self.server_eta.setObjectName("Hint")
        state_row.addWidget(self.server_dot)
        state_row.addWidget(self.server_state_label, 1)
        state_row.addWidget(self.server_eta)
        layout.addLayout(state_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("Préréglage"))
        self.preset_combo = ArrowComboBox()
        for label, prompt in self.PROMPT_PRESETS:
            self.preset_combo.addItem(label, prompt)
        self.preset_combo.setToolTip("Remplit le prompt avec un style prêt à l'emploi.")
        preset_row.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_row)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(8)
        prompt_row.addWidget(QLabel("Prompt"))
        self.ai_prompt = QPlainTextEdit()
        self.ai_prompt.setPlaceholderText("cinematic ambient, felt piano, no drums…")
        self.ai_prompt.setFixedHeight(54)
        self.ai_prompt.setTabChangesFocus(True)
        prompt_row.addWidget(self.ai_prompt, 1)
        layout.addLayout(prompt_row)

        self.ai_mix = QCheckBox("Rythme VibeFlow prioritaire (ACE-Step sans batterie)")
        self.ai_mix.setToolTip(
            "ACE-Step fournit les nappes, basses et harmonies. VibeFlow ajoute "
            "les kicks/impacts exactement sur les figures, avec ducking de la nappe."
        )
        layout.addWidget(self.ai_mix)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.ai_button = QPushButton("Générer avec ACE-Step")
        self.ai_button.setObjectName("Primary")
        self.ai_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.server_button = QPushButton("Démarrer")
        self.server_button.setCursor(Qt.CursorShape.PointingHandCursor)
        button_row.addWidget(self.ai_button, 3)
        button_row.addWidget(self.server_button, 2)
        layout.addLayout(button_row)

        self.ai_status = QLabel("Serveur ACE-Step local")
        self.ai_status.setObjectName("Hint")
        self.ai_status.setWordWrap(True)
        layout.addWidget(self.ai_status)
        self.ai_button.clicked.connect(self.aiGenerateRequested.emit)
        self.server_button.clicked.connect(self.serverToggleRequested.emit)
        root.addWidget(card)

        # --- Personalization ----------------------------------------------
        card, layout = self._card("PERSONNALISATION VIBEFLOW")
        hint = QLabel("Moteur local uniquement — n'affecte pas la piste ACE-Step.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.kit_widget = QWidget()
        kit_row = QHBoxLayout(self.kit_widget)
        kit_row.setContentsMargins(0, 0, 0, 0)
        kit_row.setSpacing(8)
        kit_row.addWidget(QLabel("Kit batterie"))
        self.kit_combo = ArrowComboBox()
        for key, label in KIT_LABELS.items():
            self.kit_combo.addItem(label, key)
        self.kit_combo.setToolTip(
            "Timbre des kicks, caisses claires et charlestons du style Pulse."
        )
        kit_row.addWidget(self.kit_combo, 1)
        layout.addWidget(self.kit_widget)

        self.accent_widget = QWidget()
        accent_row = QHBoxLayout(self.accent_widget)
        accent_row.setContentsMargins(0, 0, 0, 0)
        accent_row.setSpacing(8)
        accent_row.addWidget(QLabel("Accents"))
        self.accent_combo = ArrowComboBox()
        for key, label in ACCENT_LABELS.items():
            self.accent_combo.addItem(label, key)
        self.accent_combo.setToolTip("Instrument joué sur chaque figure détectée.")
        accent_row.addWidget(self.accent_combo, 1)
        layout.addWidget(self.accent_widget)

        self.density_slider, self.density_value = self._add_slider(
            layout, "Densité", 65
        )
        self.brightness_slider, self.brightness_value = self._add_slider(
            layout, "Brillance", 60
        )
        self.reverb_slider, self.reverb_value = self._add_slider(
            layout, "Réverbération", 55
        )
        self.low_slider, self.low_value = self._add_slider(layout, "Graves", 50)
        root.addWidget(card)

        # --- Manual accents -----------------------------------------------
        card, layout = self._card("ACCENTS MANUELS")
        hint = QLabel(
            "Active « Marquer » dans le lecteur, puis appuie sur la touche "
            "d'une piste pour poser un marqueur à la position courante. "
            "Chaque piste a sa touche, sa couleur, son son et peut être coupée."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.manual_rows_widget = QWidget()
        self.manual_rows_layout = QVBoxLayout(self.manual_rows_widget)
        self.manual_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_rows_layout.setSpacing(4)
        layout.addWidget(self.manual_rows_widget)

        track_bar = QHBoxLayout()
        track_bar.setSpacing(6)
        self.manual_add = QPushButton("＋ Piste")
        self.manual_add.setObjectName("Ghost")
        self.manual_add.setToolTip("Ajouter une piste de marqueurs.")
        track_bar.addWidget(self.manual_add)
        track_bar.addStretch(1)
        self.manual_count = QLabel("0 marqueur")
        self.manual_count.setObjectName("Hint")
        track_bar.addWidget(self.manual_count)
        layout.addLayout(track_bar)

        self.manual_selection = QLabel("Aucun marqueur sélectionné")
        self.manual_selection.setObjectName("Hint")
        self.manual_selection.setWordWrap(True)
        layout.addWidget(self.manual_selection)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.manual_delete = QPushButton("Supprimer")
        self.manual_delete.setObjectName("Ghost")
        self.manual_delete.setToolTip(
            "Supprimer le marqueur sélectionné (touche Suppr)."
        )
        self.manual_undo = QPushButton("Annuler")
        self.manual_undo.setObjectName("Ghost")
        self.manual_undo.setToolTip("Supprimer le dernier marqueur manuel.")
        self.manual_clear = QPushButton("Tout effacer")
        self.manual_clear.setObjectName("Ghost")
        self.manual_clear.setToolTip("Supprimer tous les marqueurs manuels.")
        action_row.addWidget(self.manual_delete)
        action_row.addWidget(self.manual_undo)
        action_row.addWidget(self.manual_clear)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        move_row = QHBoxLayout()
        move_row.setSpacing(6)
        move_row.addWidget(QLabel("Déplacer"))
        self.manual_move_left = ShortcutEdit(QKeySequence("Shift+Left"))
        self.manual_move_left.setMaximumSequenceLength(1)
        self.manual_move_left.setFixedWidth(88)
        self.manual_move_left.setToolTip("Touche pour décaler à gauche.")
        self.manual_move_right = ShortcutEdit(QKeySequence("Shift+Right"))
        self.manual_move_right.setMaximumSequenceLength(1)
        self.manual_move_right.setFixedWidth(88)
        self.manual_move_right.setToolTip("Touche pour décaler à droite.")
        self.manual_move_step = QSpinBox()
        self.manual_move_step.setRange(1, 10000)
        self.manual_move_step.setValue(50)
        self.manual_move_step.setSuffix(" ms")
        self.manual_move_step.setFixedWidth(86)
        self.manual_move_step.setToolTip("Pas de déplacement du marqueur.")
        move_row.addWidget(self.manual_move_left)
        move_row.addWidget(self.manual_move_right)
        move_row.addWidget(self.manual_move_step)
        move_row.addStretch(1)
        layout.addLayout(move_row)
        root.addWidget(card)
        root.addStretch(1)

        self.sensitivity.valueChanged.connect(self._on_slider)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.accent_combo.currentIndexChanged.connect(lambda _i: self.soundChanged.emit())
        self.kit_combo.currentIndexChanged.connect(lambda _i: self.soundChanged.emit())
        self.sensitivity.sliderReleased.connect(
            lambda: self.sensitivityCommitted.emit(self.sensitivity.value() / 100.0)
        )
        self.generate_button.clicked.connect(self.regenerateRequested.emit)
        self.manual_add.clicked.connect(self.manualTrackAdded.emit)
        self.manual_delete.clicked.connect(self.manualDeleteSelectedRequested.emit)
        self.manual_undo.clicked.connect(self.manualUndoRequested.emit)
        self.manual_clear.clicked.connect(self.manualClearRequested.emit)
        self.manual_move_left.captureStarted.connect(self.manualCaptureStarted.emit)
        self.manual_move_left.captureFinished.connect(self.manualCaptureFinished.emit)
        self.manual_move_right.captureStarted.connect(self.manualCaptureStarted.emit)
        self.manual_move_right.captureFinished.connect(self.manualCaptureFinished.emit)
        self.manual_move_left.editingFinished.connect(self._emit_manual_move_settings)
        self.manual_move_right.editingFinished.connect(self._emit_manual_move_settings)
        self.manual_move_step.valueChanged.connect(
            lambda _value: self._emit_manual_move_settings()
        )

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

    def _add_slider(self, layout: QVBoxLayout, label: str, value: int):
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel(label))
        row.addStretch(1)
        badge = QLabel(f"{value} %")
        badge.setObjectName("Value")
        row.addWidget(badge)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        layout.addWidget(slider)
        slider.valueChanged.connect(
            lambda current, badge=badge: self._on_sound_value(current, badge)
        )
        return slider, badge

    def _on_sound_value(self, value: int, badge: QLabel) -> None:
        badge.setText(f"{value} %")
        self.soundChanged.emit()

    def sound(self) -> SoundSettings:
        return SoundSettings(
            accent=self.accent_combo.currentData() or "guitar",
            density=self.density_slider.value() / 100.0,
            brightness=self.brightness_slider.value() / 100.0,
            reverb=self.reverb_slider.value() / 100.0,
            low_end=self.low_slider.value() / 100.0,
            kit=self.kit_combo.currentData() or "analog",
        )

    def set_sound(self, sound: SoundSettings) -> None:
        widgets = (
            self.kit_combo,
            self.accent_combo,
            self.density_slider,
            self.brightness_slider,
            self.reverb_slider,
            self.low_slider,
        )
        for widget in widgets:
            widget.blockSignals(True)
        kit_index = self.kit_combo.findData(sound.kit)
        self.kit_combo.setCurrentIndex(kit_index if kit_index >= 0 else 0)
        index = self.accent_combo.findData(sound.accent)
        self.accent_combo.setCurrentIndex(index if index >= 0 else 0)
        self.density_slider.setValue(int(round(sound.density * 100)))
        self.brightness_slider.setValue(int(round(sound.brightness * 100)))
        self.reverb_slider.setValue(int(round(sound.reverb * 100)))
        self.low_slider.setValue(int(round(sound.low_end * 100)))
        for widget in widgets:
            widget.blockSignals(False)
        self.density_value.setText(f"{self.density_slider.value()} %")
        self.brightness_value.setText(f"{self.brightness_slider.value()} %")
        self.reverb_value.setText(f"{self.reverb_slider.value()} %")
        self.low_value.setText(f"{self.low_slider.value()} %")

    def accent_label(self) -> str:
        return ACCENT_LABELS.get(self.accent_combo.currentData() or "guitar", "Guitare")

    def _clear_manual_rows(self) -> None:
        while self.manual_rows_layout.count():
            item = self.manual_rows_layout.takeAt(0)
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.deleteLater()
                layout.deleteLater()
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _color_style(self, color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; "
            f"border: 1px solid {theme.COLORS['border']}; border-radius: 4px; }}"
        )

    def set_manual_state(self, tracks, left_key: str, right_key: str, step_ms: int) -> None:
        self._clear_manual_rows()
        if not tracks:
            empty = QLabel("Aucune piste — cliquez sur « ＋ Piste ».")
            empty.setObjectName("Hint")
            self.manual_rows_layout.addWidget(empty)
        for lane, track in enumerate(tracks):
            row = QHBoxLayout()
            row.setSpacing(4)

            color_button = QPushButton()
            color_button.setFixedSize(16, 16)
            color_button.setCursor(Qt.CursorShape.PointingHandCursor)
            color_button.setToolTip("Changer la couleur de la piste.")
            color_button.setStyleSheet(self._color_style(track.color))
            color_button.setProperty("track_color", track.color)
            color_button.clicked.connect(
                lambda _checked=False, lane=lane, button=color_button: (
                    self._choose_manual_color(lane, button)
                )
            )
            row.addWidget(color_button)

            enabled = QCheckBox()
            enabled.setChecked(bool(track.enabled))
            enabled.setToolTip("Activer ou couper cette piste dans le mix.")
            enabled.toggled.connect(
                lambda checked, lane=lane: self.manualTrackEnabledChanged.emit(
                    lane, bool(checked)
                )
            )
            row.addWidget(enabled)

            name = QLineEdit(track.name)
            name.setFixedWidth(82)
            name.setMaxLength(16)
            name.setToolTip("Nom de la piste.")
            name.editingFinished.connect(
                lambda lane=lane, edit=name: self.manualTrackNameChanged.emit(
                    lane, edit.text().strip() or f"Piste {lane + 1}"
                )
            )
            row.addWidget(name)

            sound_combo = ArrowComboBox()
            for key, label in MANUAL_SOUND_LABELS.items():
                sound_combo.addItem(label, key)
            sound_index = sound_combo.findData(track.sound)
            sound_combo.setCurrentIndex(sound_index if sound_index >= 0 else 0)
            sound_combo.setToolTip("Son joué par les marqueurs de cette piste.")
            sound_combo.currentIndexChanged.connect(
                lambda _index, lane=lane, combo=sound_combo: (
                    self.manualTrackSoundChanged.emit(
                        lane, combo.currentData() or "kick"
                    )
                )
            )
            row.addWidget(sound_combo, 1)

            key_edit = ShortcutEdit(
                QKeySequence(track.key) if track.key else QKeySequence()
            )
            key_edit.setMaximumSequenceLength(1)
            key_edit.setFixedWidth(72)
            key_edit.setToolTip("Touche qui place un marqueur sur cette piste.")
            key_edit.captureStarted.connect(self.manualCaptureStarted.emit)
            key_edit.captureFinished.connect(self.manualCaptureFinished.emit)
            key_edit.editingFinished.connect(
                lambda lane=lane, edit=key_edit: self.manualTrackKeyChanged.emit(
                    lane,
                    edit.keySequence().toString(
                        QKeySequence.SequenceFormat.NativeText
                    ),
                )
            )
            row.addWidget(key_edit)

            remove = QPushButton("×")
            remove.setObjectName("Ghost")
            remove.setFixedWidth(20)
            remove.setToolTip("Supprimer cette piste et ses marqueurs.")
            remove.clicked.connect(
                lambda _checked=False, lane=lane: self.manualTrackRemoved.emit(lane)
            )
            row.addWidget(remove)
            self.manual_rows_layout.addLayout(row)

        for edit, value in (
            (self.manual_move_left, left_key),
            (self.manual_move_right, right_key),
        ):
            edit.blockSignals(True)
            edit.setKeySequence(QKeySequence(value))
            edit.blockSignals(False)
        self.manual_move_step.blockSignals(True)
        self.manual_move_step.setValue(max(1, min(10000, int(step_ms))))
        self.manual_move_step.blockSignals(False)

    def _choose_manual_color(self, lane: int, button: QPushButton) -> None:
        from PySide6.QtGui import QColor

        current = str(button.property("track_color") or "#7FA7C9")
        color = QColorDialog.getColor(QColor(current), self, "Couleur de la piste")
        if not color.isValid():
            return
        value = color.name()
        button.setStyleSheet(self._color_style(value))
        button.setProperty("track_color", value)
        self.manualTrackColorChanged.emit(lane, value)

    def _emit_manual_move_settings(self) -> None:
        self.manualMoveSettingsChanged.emit(
            self.manual_move_left.keySequence().toString(
                QKeySequence.SequenceFormat.NativeText
            ),
            self.manual_move_right.keySequence().toString(
                QKeySequence.SequenceFormat.NativeText
            ),
            self.manual_move_step.value(),
        )

    def set_manual_selection(self, text: str) -> None:
        self.manual_selection.setText(text)

    def set_manual_count(self, count: int) -> None:
        self.manual_count.setText(f"{count} marqueur{'s' if count != 1 else ''}")

    def set_preview_dirty(self, dirty: bool) -> None:
        self.generate_button.setText(
            "● Régénérer la préécoute" if dirty else "Régénérer la préécoute"
        )

    def ai_settings(self) -> dict:
        return {
            "server": self.ai_server.text().strip() or "http://127.0.0.1:8021",
            "prompt": self.ai_prompt.toPlainText().strip(),
            "mix_accents": self.ai_mix.isChecked(),
        }

    def set_ai_settings(self, server: str, prompt: str, mix_accents: bool) -> None:
        self.ai_server.setText(server)
        self.ai_prompt.setPlainText(prompt)
        self.ai_prompt.setToolTip(prompt)
        self.ai_mix.setChecked(bool(mix_accents))

    def _on_preset_changed(self, index: int) -> None:
        prompt = self.preset_combo.itemData(index)
        if prompt:
            self.ai_prompt.setPlainText(prompt)
            self.ai_prompt.setToolTip(prompt)

    def set_server_state(
        self,
        state: str,
        text: str,
        *,
        eta: str = "",
        action: str = "Démarrer",
        enabled: bool = True,
    ) -> None:
        self.server_dot.set_state(state)
        self.server_state_label.setText(text)
        self.server_eta.setText(eta)
        self.server_eta.setVisible(bool(eta))
        self.server_button.setText(action)
        self.server_button.setEnabled(enabled)

    def set_ai_status(self, text: str, level: str = "hint") -> None:
        self.ai_status.setObjectName(
            {"hint": "Hint", "success": "Success", "warning": "Warning", "error": "Error"}.get(
                level, "Hint"
            )
        )
        self.ai_status.setText(text)
        self.ai_status.style().unpolish(self.ai_status)
        self.ai_status.style().polish(self.ai_status)

    def set_ai_busy(self, busy: bool) -> None:
        self.ai_button.setEnabled(not busy)
        self.ai_button.setText("Génération en cours…" if busy else "Générer avec ACE-Step")

    def _on_slider(self, value: int) -> None:
        self.sensitivity_value.setText(f"{value} %")
        self.sensitivityChanged.emit(value / 100.0)

    def _on_style_changed(self, index: int) -> None:
        style = self.style_combo.itemData(index) or "evasion"
        self._apply_style_hint(style)
        self.styleChanged.emit(style)

    def _apply_style_hint(self, style: str) -> None:
        self.style_hint.setText(
            "Ambiant cinématique : pads, arpèges et accords pincés, tempo posé."
            if style == "evasion"
            else "Rythmique club : kick four-on-floor, hats et impacts percussifs."
        )
        if hasattr(self, "kit_widget"):
            self.kit_widget.setVisible(style == "pulse")
            self.accent_widget.setVisible(style == "evasion")

    def set_style(self, style: str) -> None:
        index = self.style_combo.findData(style)
        if index < 0:
            index = 0
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(index)
        self.style_combo.blockSignals(False)
        self._apply_style_hint(style)

    # ------------------------------------------------------------------ state
    def set_sensitivity(self, value: float) -> None:
        self.sensitivity.blockSignals(True)
        self.sensitivity.setValue(int(round(value * 100)))
        self.sensitivity_value.setText(f"{int(round(value * 100))} %")
        self.sensitivity.blockSignals(False)

    def set_plan(self, plan: RhythmPlan | None, event_count: int) -> None:
        if plan is None:
            self.plan_stats.setText("Aucune préécoute générée.")
            return
        instruments = {}
        for hit in plan.hits:
            instruments[hit.instrument] = instruments.get(hit.instrument, 0) + 1
        parts = [f"{plan.bpm:.1f} BPM", f"{event_count} accents"]
        if plan.style == "evasion":
            order = (
                ("arp", "arpèges"),
                ("guitar", "guitare"),
                ("piano", "piano"),
                ("bell", "cloches"),
                ("softkick", "kicks"),
                ("pad_warm", "nappes"),
                ("boom", "impacts"),
            )
        else:
            order = (
                ("kick", "kicks"),
                ("sub", "basses"),
                ("hat", "hats"),
                ("clap", "claps"),
                ("impact", "impacts"),
            )
        details = " · ".join(
            f"{label} {instruments[name]}" for name, label in order if instruments.get(name)
        )
        self.plan_stats.setText(f"{'  ·  '.join(parts)}\n{details}")

    def set_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled(not busy)
        self.generate_button.setText("Génération…" if busy else "Régénérer la préécoute")
        self.sensitivity.setEnabled(not busy)
