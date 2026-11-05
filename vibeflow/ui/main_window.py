"""VibeFlow main window: import, analyse, compose, play, export."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_TAGLINE, __version__
from ..core.analysis import FlightEvent
from ..core.project import Project, ProgressFn
from ..core.rhythm import (
    ACCENT_LABELS,
    MANUAL_SOUND_LABELS,
    STYLE_LABELS,
    ManualAccent,
    RhythmPlan,
    manual_accent_hits,
)
from ..core.synth import completion_melody, render_plan, write_wav
from ..core.drums import KIT_LABELS
from ..backend.acestep_backend import ACEStepBackend, BackendError
from ..media.ffmpeg import FFmpegNotFound, find_ffmpeg
from . import theme
from .widgets.combo import ArrowComboBox
from .widgets.control_panel import ControlPanel
from .widgets.analysis_panel import AnalysisPanel
from .widgets.event_panel import EventPanel
from .widgets.timeline import Timeline, format_time
from .widgets.video_panel import VideoPanel
from .workers import TaskRunner

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
GYRO_EXTENSIONS = {".gcsv", ".csv", ".txt", ".log"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_TAGLINE}")
        self.resize(1500, 940)
        self.setMinimumSize(1120, 720)
        self.setAcceptDrops(True)

        self.project = Project()
        self.backend = ACEStepBackend()
        self.tasks = TaskRunner(self, max_threads=2)
        self._generation_token = 0
        self._analysis_token = 0
        self._busy = False
        self._pending_regenerate = False
        self._pending_seek: float | None = None
        self._pending_play = False
        self._last_dir = str(Path.home())
        self._manual_sync = False
        self._sync_inflight = False
        self._source_loading = False
        self._backend_operation: str | None = None
        self._ai_busy = False
        self._backend_start_time: float | None = None
        self._backend_error: str | None = None
        self._server_eta_text = ""
        self._progress_started: float | None = None
        self._manual_mode = False
        self._manual_dirty = False
        self._manual_shortcuts: list[QShortcut] = []
        self._selected_manual_index: int | None = None
        self._move_shortcuts: list[QShortcut] = []
        self._delete_manual_shortcut: QShortcut | None = None
        self._current_source_path: Path | None = None
        self._original_source: Path | None = None
        self._original_pending_seek: int | None = None
        self._manual_sound_source: str | None = None
        self._manual_pending_play = False
        self._notify_loaded = True
        self._tray_icon: QSystemTrayIcon | None = None
        self._notify_source: str | None = None
        self._ffmpeg_ok = True
        try:
            find_ffmpeg()
        except FFmpegNotFound as exc:
            self._ffmpeg_ok = False
            self._ffmpeg_error = str(exc)

        self._build_ui()
        self._restore_theme()
        self._build_player()
        self._build_shortcuts()
        self._build_timers()
        self._update_actions()
        self.controls.set_style(self.project.style)
        self.controls.set_sound(self.project.sound)
        self.controls.set_ai_settings(
            self.project.ai_server, self.project.ai_prompt, self.project.ai_mix_accents
        )
        self.video_panel.manualModeToggled.connect(self._toggle_manual_mode)
        self.video_panel.originalAudioToggled.connect(self._toggle_original_audio)
        self.controls.manualTrackAdded.connect(self._add_manual_track)
        self.controls.manualTrackRemoved.connect(self._remove_manual_track)
        self.controls.manualTrackSoundChanged.connect(
            self._on_manual_track_sound_changed
        )
        self.controls.manualTrackKeyChanged.connect(self._on_manual_track_key_changed)
        self.controls.manualTrackColorChanged.connect(
            self._on_manual_track_color_changed
        )
        self.controls.manualTrackEnabledChanged.connect(
            self._on_manual_track_enabled_changed
        )
        self.controls.manualTrackNameChanged.connect(
            self._on_manual_track_name_changed
        )
        self.controls.manualMoveSettingsChanged.connect(
            self._on_manual_move_settings_changed
        )
        self.controls.manualDeleteSelectedRequested.connect(
            self._delete_selected_manual
        )
        self.controls.manualUndoRequested.connect(self._undo_manual_accent)
        self.controls.manualClearRequested.connect(self._clear_manual_accents)
        self.controls.manualCaptureStarted.connect(self._begin_key_capture)
        self.controls.manualCaptureFinished.connect(self._end_key_capture)
        self._manual_preview = QSoundEffect(self)
        self._manual_preview.setVolume(0.85)
        self._manual_preview.statusChanged.connect(self._on_manual_preview_status)
        self._notify_sound = QSoundEffect(self)
        self._notify_sound.setVolume(0.90)
        self._notify_sound.statusChanged.connect(self._on_notify_sound_status)
        self._sync_manual_controls()
        self._rebuild_manual_shortcuts()
        self._refresh_manual_markers()
        self._refresh_backend_ui()

        if not self._ffmpeg_ok:
            self.status_message(self._ffmpeg_error, "error")

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.ui_settings = QSettings("VibeFlow", "VibeFlow")
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 8)
        body_layout.setSpacing(8)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setChildrenCollapsible(False)

        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.setHandleWidth(8)
        self.left_splitter.setChildrenCollapsible(False)
        self.video_panel = VideoPanel()
        self.video_panel.setMinimumHeight(260)
        self.timeline = Timeline()
        self.timeline.setMinimumHeight(140)
        self.left_splitter.addWidget(self.video_panel)
        self.left_splitter.addWidget(self.timeline)
        self.left_splitter.setStretchFactor(0, 4)
        self.left_splitter.setStretchFactor(1, 1)
        self.left_splitter.setSizes([620, 200])
        self.main_splitter.addWidget(self.left_splitter)

        right = QWidget()
        right.setMinimumWidth(460)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.controls = ControlPanel()
        self.analysis_panel = AnalysisPanel()
        self.event_panel = EventPanel()
        self.tabs.addTab(self.controls, "Musique")
        self.tabs.addTab(self.analysis_panel, "Analyse")
        self.tabs.addTab(self.event_panel, "Événements")
        right_layout.addWidget(self.tabs)
        self.main_splitter.addWidget(right)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.main_splitter.setSizes([920, 560])
        body_layout.addWidget(self.main_splitter, 1)
        layout.addWidget(body, 1)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.status_label = QLabel("Prêt.")
        self.status_label.setObjectName("StatusLabel")
        status.addWidget(self.status_label, 1)
        self.progress_step = QLabel("")
        self.progress_step.setObjectName("Hint")
        self.progress_step.setMaximumWidth(320)
        self.progress_step.hide()
        status.addPermanentWidget(self.progress_step)
        self.progress_eta = QLabel("")
        self.progress_eta.setObjectName("Hint")
        self.progress_eta.setFixedWidth(74)
        self.progress_eta.hide()
        status.addPermanentWidget(self.progress_eta)
        self.progress_percent = QLabel("")
        self.progress_percent.setObjectName("Hint")
        self.progress_percent.setFixedWidth(42)
        self.progress_percent.hide()
        status.addPermanentWidget(self.progress_percent)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(150)
        self.progress.hide()
        status.addPermanentWidget(self.progress)
        self.format_label = QLabel("48 kHz · stéréo")
        self.format_label.setObjectName("Hint")
        status.addPermanentWidget(self.format_label)
        self.setStatusBar(status)

        self.event_table = self.event_panel.table
        self.event_count = self.event_panel.count
        self.enable_all = self.event_panel.enable_all

        self._restore_layout()

        self.controls.sensitivityChanged.connect(self._on_sensitivity)
        self.controls.sensitivityCommitted.connect(lambda _v: self._schedule_regeneration())
        self.controls.styleChanged.connect(self._on_style_changed)
        self.controls.soundChanged.connect(self._on_sound_changed)
        self.controls.aiGenerateRequested.connect(self._generate_ai)
        self.controls.serverToggleRequested.connect(self._toggle_backend)
        self.controls.regenerateRequested.connect(self._regenerate)
        self.analysis_panel.offsetChanged.connect(self._on_offset_changed)
        self.analysis_panel.autoSyncRequested.connect(self._auto_sync)
        self.analysis_panel.backendInstallRequested.connect(self._install_backend)
        self.analysis_panel.backendStartRequested.connect(self._start_backend)
        self.analysis_panel.backendStopRequested.connect(self._stop_backend)
        self.analysis_panel.backendLogsRequested.connect(self._show_backend_logs)
        self.event_panel.eventToggled.connect(self._on_event_toggled)
        self.event_panel.eventActivated.connect(self._on_event_activated)
        self.event_panel.enableAllRequested.connect(self._enable_all_events)
        self.timeline.seekRequested.connect(self.seek)
        self.timeline.eventSelected.connect(self._on_event_selected)
        self.timeline.manualAccentSelected.connect(self._on_manual_accent_selected)
        self.video_panel.playToggled.connect(self.toggle_play)
        self.video_panel.seekRequested.connect(self.seek)
        self.video_panel.frameStepRequested.connect(self._step_frame)
        self.video_panel.volumeChanged.connect(self._on_volume)
        self.video_panel.sourceSelected.connect(self._switch_source)

    def _restore_layout(self) -> None:
        try:
            version = int(self.ui_settings.value("ui/layout_version", 1))
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            # Reset the historical narrow right panel once.
            return
        for key, splitter in (("ui/main_splitter", self.main_splitter),
                              ("ui/left_splitter", self.left_splitter)):
            sizes = self.ui_settings.value(key)
            if not sizes:
                continue
            try:
                if isinstance(sizes, str):
                    sizes = [int(part) for part in sizes.split(",") if part]
                else:
                    sizes = [int(part) for part in sizes]
                if len(sizes) == splitter.count() and all(size > 0 for size in sizes):
                    splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass

    def _restore_theme(self) -> None:
        mode = self.ui_settings.value("ui/theme", "dark")
        self._apply_ui_theme(mode if mode in {"dark", "light"} else "dark")

    def _change_zoom(self, index: int) -> None:
        percent = self.zoom_combo.itemData(index)
        if percent is None:
            return
        try:
            current = int(round(float(self.ui_settings.value("ui/scale", 1.0)) * 100))
        except (TypeError, ValueError):
            current = 100
        if percent == current:
            return
        self.ui_settings.setValue("ui/scale", percent / 100.0)
        answer = QMessageBox.question(
            self,
            "Zoom de l'interface",
            f"Le zoom sera appliqué au redémarrage de VibeFlow ({percent} %).\n\n"
            "Redémarrer maintenant ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QProcess.startDetached(sys.executable, ["-m", "vibeflow"])
            QApplication.quit()
        else:
            self.status_message(
                f"Zoom {percent} % enregistré — redémarrez VibeFlow pour l'appliquer."
            )

    def _toggle_theme(self) -> None:
        mode = "light" if not theme.is_light() else "dark"
        self._apply_ui_theme(mode)
        self.ui_settings.setValue("ui/theme", mode)

    def _apply_ui_theme(self, mode: str) -> None:
        theme.apply_theme(QApplication.instance(), mode)
        self.theme_button.setText("Sombre" if mode == "light" else "Clair")
        self._update_wordmark()
        if hasattr(self, "_last_status"):
            self.status_message(*self._last_status)
        if hasattr(self, "event_table") and self.project.analysis is not None:
            self._refresh_events()
        if hasattr(self, "timeline"):
            self.timeline.refresh_theme()
        if hasattr(self, "video_panel"):
            self.video_panel.empty.update()
        self._refresh_backend_ui()

    def _update_wordmark(self) -> None:
        text_color = theme.COLORS["text"]
        accent = theme.COLORS["accent"]
        self.wordmark.setText(
            f'<span style="color:{text_color}; font-size:17px; font-weight:600; '
            'letter-spacing:1px;">Vibe</span>'
            f'<span style="color:{accent}; font-size:17px; font-weight:600; '
            'letter-spacing:1px;">Flow</span>'
        )

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(56)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 14, 0)
        row.setSpacing(10)

        self.wordmark = QLabel()
        self.wordmark.setFixedWidth(100)
        self._update_wordmark()
        row.addWidget(self.wordmark)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedHeight(22)
        separator.setObjectName("HeaderSeparator")
        row.addWidget(separator)

        self.project_label = QLabel("Nouveau projet")
        self.project_label.setObjectName("Hint")
        row.addWidget(self.project_label)
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setObjectName("Hint")
        row.addWidget(self.version_label)
        row.addStretch(1)

        zoom_label = QLabel("Zoom")
        zoom_label.setObjectName("Hint")
        row.addWidget(zoom_label)
        self.zoom_combo = ArrowComboBox()
        self.zoom_combo.setFixedWidth(76)
        for percent in (100, 110, 120, 130, 150):
            self.zoom_combo.addItem(f"{percent} %", percent)
        try:
            current_zoom = int(round(float(self.ui_settings.value("ui/scale", 1.0)) * 100))
        except (TypeError, ValueError):
            current_zoom = 100
        zoom_index = self.zoom_combo.findData(current_zoom)
        self.zoom_combo.setCurrentIndex(zoom_index if zoom_index >= 0 else 0)
        self.zoom_combo.currentIndexChanged.connect(self._change_zoom)
        row.addWidget(self.zoom_combo)

        self.theme_button = QPushButton("Clair")
        self.theme_button.setObjectName("Ghost")
        self.theme_button.setToolTip("Basculer entre thème sombre et thème clair")
        self.theme_button.clicked.connect(self._toggle_theme)
        row.addWidget(self.theme_button)

        self.btn_open = QPushButton("Ouvrir ▾")
        self.btn_open.setObjectName("Ghost")
        open_menu = QMenu(self)
        video_action = open_menu.addAction("Vidéo FPV…")
        video_action.setShortcut(QKeySequence("Ctrl+O"))
        video_action.triggered.connect(self.open_video_dialog)
        gyro_action = open_menu.addAction("Données gyro…")
        gyro_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        gyro_action.triggered.connect(self.open_gyro_dialog)
        open_menu.addSeparator()
        project_action = open_menu.addAction("Ouvrir un projet…")
        project_action.triggered.connect(self.open_project_dialog)
        save_action = open_menu.addAction("Enregistrer le projet…")
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_project_dialog)
        self.btn_open.setMenu(open_menu)
        row.addWidget(self.btn_open)

        self.btn_export = QPushButton("Exporter ▾")
        self.btn_export.setObjectName("Primary")
        export_menu = QMenu(self)
        self.action_export_wav = export_menu.addAction("Piste musicale (WAV)…")
        self.action_export_wav.triggered.connect(self.export_wav_dialog)
        self.action_export_mp4 = export_menu.addAction("Vidéo avec musique (MP4)…")
        self.action_export_mp4.triggered.connect(self.export_video_dialog)
        self.btn_export.setMenu(export_menu)
        row.addWidget(self.btn_export)
        return header

    def _build_player(self) -> None:
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_panel.video)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.errorOccurred.connect(self._on_player_error)

        self.original_audio_output = QAudioOutput(self)
        self.original_audio_output.setVolume(0.35)
        self.original_player = QMediaPlayer(self)
        self.original_player.setAudioOutput(self.original_audio_output)
        self.original_player.mediaStatusChanged.connect(self._on_original_status)

    def _build_shortcuts(self) -> None:
        self._global_shortcuts: list[QShortcut] = []
        self._global_shortcuts.append(
            QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_play)
        )
        self._nudge_back = QShortcut(
            QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self._nudge(-5.0)
        )
        self._nudge_forward = QShortcut(
            QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self._nudge(5.0)
        )
        self._global_shortcuts += [self._nudge_back, self._nudge_forward]
        self._nudge_shortcuts = [self._nudge_back, self._nudge_forward]
        for sequence, slot in (
            ("Ctrl+O", self.open_video_dialog),
            ("Ctrl+Shift+O", self.open_gyro_dialog),
            ("Ctrl+S", self.save_project_dialog),
            ("Ctrl+E", self.export_video_dialog),
            ("Ctrl+R", self._regenerate),
            ("Home", lambda: self.seek(0.0)),
            ("Escape", self.player.pause),
        ):
            self._global_shortcuts.append(QShortcut(QKeySequence(sequence), self, activated=slot))

    # ------------------------------------------------------- manual accents
    def _rebuild_manual_shortcuts(self) -> None:
        for shortcut in self._manual_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._manual_shortcuts.clear()
        for lane, track in enumerate(self.project.manual_tracks):
            key = (track.key or "").strip()
            if not key:
                continue
            sequence = QKeySequence(key)
            if sequence.isEmpty():
                continue
            shortcut = QShortcut(
                sequence,
                self,
                activated=lambda lane=lane: self._place_manual_accent(lane),
            )
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.setEnabled(self._manual_mode)
            self._manual_shortcuts.append(shortcut)
        self._rebuild_move_shortcuts()

    def _rebuild_move_shortcuts(self) -> None:
        for shortcut in self._move_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._move_shortcuts.clear()
        for key, direction in (
            (self.project.manual_move_left_key, -1),
            (self.project.manual_move_right_key, 1),
        ):
            key = (key or "").strip()
            if not key:
                continue
            shortcut = QShortcut(
                QKeySequence(key),
                self,
                activated=lambda direction=direction: self._move_selected_manual(
                    direction
                ),
            )
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.setEnabled(self._selected_manual_index is not None)
            self._move_shortcuts.append(shortcut)
        if self._delete_manual_shortcut is None:
            self._delete_manual_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_Delete),
                self,
                activated=self._delete_selected_manual,
            )
            self._delete_manual_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._delete_manual_shortcut.setEnabled(
            self._selected_manual_index is not None
        )

    def _sync_manual_controls(self) -> None:
        self.controls.set_manual_state(
            self.project.manual_tracks,
            self.project.manual_move_left_key,
            self.project.manual_move_right_key,
            self.project.manual_move_step_ms,
        )
        self.controls.set_manual_count(len(self.project.manual_accents))
        self._update_manual_selection_label()

    def _begin_key_capture(self) -> None:
        for shortcut in self._manual_shortcuts:
            shortcut.setEnabled(False)
        for shortcut in self._move_shortcuts:
            shortcut.setEnabled(False)
        if self._delete_manual_shortcut is not None:
            self._delete_manual_shortcut.setEnabled(False)
        for shortcut in self._global_shortcuts:
            shortcut.setEnabled(False)

    def _end_key_capture(self) -> None:
        for shortcut in self._global_shortcuts:
            shortcut.setEnabled(True)
        for shortcut in self._nudge_shortcuts:
            shortcut.setEnabled(not self._manual_mode)
        for shortcut in self._manual_shortcuts:
            shortcut.setEnabled(self._manual_mode)
        for shortcut in self._move_shortcuts:
            shortcut.setEnabled(self._selected_manual_index is not None)
        if self._delete_manual_shortcut is not None:
            self._delete_manual_shortcut.setEnabled(
                self._selected_manual_index is not None
            )

    def _refresh_manual_markers(self) -> None:
        self.timeline.set_manual_tracks(self.project.manual_tracks)
        self.timeline.set_manual_accents(self.project.manual_accents)
        self.timeline.set_selected_manual(self._selected_manual_index)
        self.controls.set_manual_count(len(self.project.manual_accents))
        self._update_manual_selection_label()

    def _update_manual_selection_label(self) -> None:
        index = self._selected_manual_index
        if index is None or not (0 <= index < len(self.project.manual_accents)):
            self.controls.set_manual_selection("Aucun marqueur sélectionné")
            return
        marker = self.project.manual_accents[index]
        track = (
            self.project.manual_tracks[marker.lane]
            if 0 <= marker.lane < len(self.project.manual_tracks)
            else None
        )
        name = track.name if track else "Piste supprimée"
        self.controls.set_manual_selection(
            f"Sélection : {name} · {format_time(marker.time, decimals=True)}"
        )

    def _set_manual_selection(self, index: int | None) -> None:
        if index is not None and not (0 <= index < len(self.project.manual_accents)):
            index = None
        self._selected_manual_index = index
        self.timeline.set_selected_manual(index)
        for shortcut in self._move_shortcuts:
            shortcut.setEnabled(index is not None)
        if self._delete_manual_shortcut is not None:
            self._delete_manual_shortcut.setEnabled(index is not None)
        self._update_manual_selection_label()

    def _on_manual_accent_selected(self, index: int) -> None:
        self._set_manual_selection(index)
        if 0 <= index < len(self.project.manual_accents):
            marker = self.project.manual_accents[index]
            left = QKeySequence(self.project.manual_move_left_key).toString()
            right = QKeySequence(self.project.manual_move_right_key).toString()
            self.status_message(
                f"Marqueur sélectionné — {format_time(marker.time, decimals=True)} "
                f"(Suppr pour supprimer, {left}/{right} pour décaler)."
            )

    def _toggle_manual_mode(self, active: bool) -> None:
        self._manual_mode = bool(active)
        for shortcut in self._manual_shortcuts:
            shortcut.setEnabled(self._manual_mode)
        for shortcut in self._nudge_shortcuts:
            shortcut.setEnabled(not self._manual_mode)
        self.video_panel.manual_button.setText(
            "● Marquer" if self._manual_mode else "Marquer"
        )
        if self._manual_mode:
            if not self.project.manual_tracks:
                self.status_message(
                    "Ajoutez d'abord une piste dans la carte Accents manuels.",
                    "warning",
                )
            else:
                self.status_message(
                    "Mode manuel actif — touches des pistes pour poser, "
                    "Espace pour lire/pause."
                )
        elif self._manual_dirty:
            self._manual_dirty = False
            self.status_message(
                "Marqueurs manuels modifiés — cliquez sur Régénérer la préécoute."
            )
        else:
            self.status_message("Mode manuel désactivé.")

    def _manual_position(self) -> float:
        duration = self.project.manual_duration()
        position = max(0.0, self.player.position() / 1000.0)
        if duration > 0:
            position = min(position, max(0.0, duration - 0.01))
        return position

    def _text_input_focused(self) -> bool:
        widget = QApplication.focusWidget()
        if widget is None:
            return False
        return widget.metaObject().className() in {
            "QLineEdit",
            "QPlainTextEdit",
            "QKeySequenceEdit",
            "QSpinBox",
            "QDoubleSpinBox",
            "QComboBox",
            "QSlider",
        }

    def _place_manual_accent(self, lane: int) -> None:
        if not self._manual_mode or self._text_input_focused():
            return
        if self.project.video is None:
            self.status_message("Importez d'abord une vidéo.", "warning")
            return
        if not (0 <= lane < len(self.project.manual_tracks)):
            return
        time = self._manual_position()
        marker = self.project.add_manual_accent(time, lane)
        if marker is None:
            return
        self._manual_dirty = True
        self._refresh_manual_markers()
        self._set_manual_selection(self.project.manual_accents.index(marker))
        self._play_manual_preview(lane)
        track = self.project.manual_tracks[lane]
        sound = MANUAL_SOUND_LABELS.get(track.sound, track.sound)
        self.status_message(
            f"Marqueur {track.name} · {sound} — "
            f"{format_time(marker.time, decimals=True)}"
        )

    def _undo_manual_accent(self) -> None:
        marker = self.project.pop_manual_accent()
        if marker is None:
            self.status_message("Aucun marqueur manuel à annuler.", "warning")
            return
        self._manual_dirty = True
        self._set_manual_selection(None)
        self._refresh_manual_markers()
        self.status_message("Dernier marqueur manuel supprimé.")

    def _delete_selected_manual(self) -> None:
        if self._text_input_focused():
            return
        index = self._selected_manual_index
        marker = (
            self.project.remove_manual_accent_at(index)
            if index is not None
            else None
        )
        if marker is None:
            self.status_message("Sélectionnez d'abord un marqueur.", "warning")
            return
        self._manual_dirty = True
        self._set_manual_selection(None)
        self._refresh_manual_markers()
        self.status_message("Marqueur sélectionné supprimé.")

    def _clear_manual_accents(self) -> None:
        if not self.project.manual_accents:
            self.status_message("Aucun marqueur manuel.", "warning")
            return
        count = len(self.project.manual_accents)
        self.project.clear_manual_accents()
        self._manual_dirty = True
        self._set_manual_selection(None)
        self._refresh_manual_markers()
        self.status_message(f"{count} marqueur(s) manuel(s) supprimé(s).")

    def _move_selected_manual(self, direction: int) -> None:
        if self._text_input_focused():
            return
        index = self._selected_manual_index
        if index is None:
            return
        step = self.project.manual_move_step_ms / 1000.0
        new_index = self.project.move_manual_accent(index, direction * step)
        if new_index is None:
            return
        marker = self.project.manual_accents[new_index]
        self._manual_dirty = True
        self._set_manual_selection(new_index)
        self._refresh_manual_markers()
        self.status_message(
            f"Marqueur décalé — {format_time(marker.time, decimals=True)}"
        )

    # ------------------------------------------------------ manual tracks
    def _add_manual_track(self) -> None:
        track = self.project.add_manual_track()
        self._sync_manual_controls()
        self._rebuild_manual_shortcuts()
        self._refresh_manual_markers()
        self.status_message(
            f"Piste « {track.name} » ajoutée — assignez-lui une touche."
        )

    def _remove_manual_track(self, lane: int) -> None:
        if not (0 <= lane < len(self.project.manual_tracks)):
            return
        track = self.project.manual_tracks[lane]
        count = sum(1 for marker in self.project.manual_accents if marker.lane == lane)
        if count:
            answer = QMessageBox.question(
                self,
                "Supprimer la piste",
                f"Supprimer la piste « {track.name} » et ses {count} marqueur(s) ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.project.remove_manual_track(lane)
        self._manual_dirty = True
        self._set_manual_selection(None)
        self._sync_manual_controls()
        self._rebuild_manual_shortcuts()
        self._refresh_manual_markers()
        self.status_message(f"Piste « {track.name} » supprimée.")

    def _on_manual_track_sound_changed(self, lane: int, sound: str) -> None:
        self.project.set_manual_track_sound(lane, sound)
        self._manual_dirty = True
        self._manual_sound_source = None
        label = MANUAL_SOUND_LABELS.get(sound, sound)
        self.status_message(
            f"Piste {lane + 1} → {label} (régénérer pour appliquer au mix)."
        )

    def _on_manual_track_key_changed(self, lane: int, key: str) -> None:
        if not (0 <= lane < len(self.project.manual_tracks)):
            return
        key = (key or "").strip()
        if key:
            sequence = QKeySequence(key)
            if sequence.isEmpty():
                key = ""
        if key:
            for other_lane, other in enumerate(self.project.manual_tracks):
                if other_lane == lane:
                    continue
                if QKeySequence(other.key) == QKeySequence(key):
                    self.status_message(
                        f"Touche déjà utilisée par « {other.name} ».",
                        "warning",
                    )
                    self._sync_manual_controls()
                    return
            if key in {
                self.project.manual_move_left_key,
                self.project.manual_move_right_key,
            }:
                self.status_message(
                    "Cette touche est réservée au déplacement des marqueurs.",
                    "warning",
                )
                self._sync_manual_controls()
                return
        self.project.set_manual_track_key(lane, key)
        self._rebuild_manual_shortcuts()
        label = QKeySequence(key).toString() if key else "aucune"
        self.status_message(f"Piste {lane + 1} → touche {label}.")

    def _on_manual_track_color_changed(self, lane: int, color: str) -> None:
        self.project.set_manual_track_color(lane, color)
        self._refresh_manual_markers()
        self.status_message(f"Couleur de la piste {lane + 1} mise à jour.")

    def _on_manual_track_enabled_changed(self, lane: int, enabled: bool) -> None:
        self.project.set_manual_track_enabled(lane, enabled)
        self._manual_dirty = True
        self._refresh_manual_markers()
        state = "activée" if enabled else "coupée"
        self.status_message(
            f"Piste {lane + 1} {state} (régénérer pour appliquer au mix)."
        )

    def _on_manual_track_name_changed(self, lane: int, name: str) -> None:
        if 0 <= lane < len(self.project.manual_tracks):
            self.project.set_manual_track_name(lane, name)
            self._update_manual_selection_label()

    def _on_manual_move_settings_changed(
        self, left_key: str, right_key: str, step_ms: int
    ) -> None:
        left_key = left_key or "Shift+Left"
        right_key = right_key or "Shift+Right"
        used = {track.key for track in self.project.manual_tracks if track.key}
        if left_key in used or right_key in used:
            self.status_message(
                "Ces touches sont déjà utilisées par une piste de marqueurs.",
                "warning",
            )
            self._sync_manual_controls()
            return
        self.project.manual_move_left_key = left_key
        self.project.manual_move_right_key = right_key
        self.project.manual_move_step_ms = max(1, min(10000, int(step_ms)))
        self._rebuild_move_shortcuts()
        self.status_message(
            f"Déplacement : {self.project.manual_move_left_key} / "
            f"{self.project.manual_move_right_key} · "
            f"{self.project.manual_move_step_ms} ms."
        )

    def _manual_preview_path(self, lane: int) -> str:
        track = self.project.manual_tracks[lane]
        if not track.enabled:
            raise RuntimeError("Piste coupée")
        instrument = track.sound
        signature = (
            f"{instrument}|{lane}|{self.project.style}|{self.project.sound}|"
            f"{self.project.sound.kit}"
        )
        hit = manual_accent_hits(
            [ManualAccent(0.05, lane)], self.project.manual_tracks, 2.6
        )[0]
        plan = RhythmPlan(
            bpm=120.0,
            beat_offset=0.0,
            duration=2.6,
            sections=[],
            hits=[hit],
            style=self.project.style,
            sound=self.project.sound,
        )
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]
        path = self.project.work_dir / "manual" / f"{digest}.wav"
        if not path.exists():
            write_wav(path, render_plan(plan))
        return str(path)

    def _play_manual_preview(self, lane: int) -> None:
        try:
            path = self._manual_preview_path(lane)
        except Exception:
            return
        if path != self._manual_sound_source:
            self._manual_sound_source = path
            self._manual_pending_play = True
            self._manual_preview.setSource(QUrl.fromLocalFile(path))
            if self._manual_preview.status() == QSoundEffect.Status.Ready:
                self._manual_pending_play = False
                self._manual_preview.play()
            return
        self._manual_preview.stop()
        self._manual_preview.play()

    def _on_manual_preview_status(self) -> None:
        if (
            self._manual_preview.status() == QSoundEffect.Status.Ready
            and self._manual_pending_play
        ):
            self._manual_pending_play = False
            self._manual_preview.play()

    # ---------------------------------------------------------- notification
    def _notify_done(self, title: str, message: str) -> None:
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                if self._tray_icon is None:
                    self._tray_icon = QSystemTrayIcon(self.windowIcon(), self)
                    self._tray_icon.setToolTip(APP_NAME)
                self._tray_icon.show()
                self._tray_icon.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    9000,
                )
                QTimer.singleShot(10000, self._tray_icon.hide)
        except Exception:
            pass
        QApplication.alert(self, 5000)
        self._play_notify_sound()

    def _play_notify_sound(self) -> None:
        try:
            directory = self.project.work_dir / "notify"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "acestep_done.wav"
            if not path.exists():
                write_wav(path, completion_melody())
            url = str(path)
            if url != self._notify_source:
                self._notify_source = url
                self._notify_loaded = False
                self._notify_sound.setSource(QUrl.fromLocalFile(url))
                if self._notify_sound.status() == QSoundEffect.Status.Ready:
                    self._notify_loaded = True
                    self._notify_sound.play()
                return
            self._notify_sound.stop()
            self._notify_sound.play()
        except Exception:
            pass

    def _on_notify_sound_status(self) -> None:
        if (
            self._notify_sound.status() == QSoundEffect.Status.Ready
            and not self._notify_loaded
        ):
            self._notify_loaded = True
            self._notify_sound.play()

    # ------------------------------------------------------------- timers
    def _build_timers(self) -> None:
        self.playhead_timer = QTimer(self)
        self.playhead_timer.setInterval(33)
        self.playhead_timer.timeout.connect(self._tick_playhead)
        self.playhead_timer.start()

        self.regenerate_timer = QTimer(self)
        self.regenerate_timer.setSingleShot(True)
        self.regenerate_timer.setInterval(380)
        self.regenerate_timer.timeout.connect(self._regenerate)

        self.server_eta_timer = QTimer(self)
        self.server_eta_timer.setInterval(1000)
        self.server_eta_timer.timeout.connect(self._update_server_eta)

    # ----------------------------------------------------------------- import
    def open_video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer une vidéo FPV",
            self._last_dir,
            "Vidéos (*.mp4 *.mov *.m4v *.mkv *.avi *.webm);;Tous les fichiers (*.*)",
        )
        if path:
            self._last_dir = str(Path(path).parent)
            self.load_video(Path(path))

    def open_gyro_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer les données gyroscopiques",
            self._last_dir,
            "Journaux gyro (*.gcsv *.csv *.txt *.log);;Tous les fichiers (*.*)",
        )
        if path:
            self._last_dir = str(Path(path).parent)
            self.load_gyro(Path(path))

    def load_video(self, path: Path) -> None:
        if not path.exists():
            self._error("Fichier introuvable", str(path))
            return
        try:
            info = self.project.load_video(path)
        except Exception as exc:  # noqa: BLE001
            self._error("Impossible d'importer la vidéo", str(exc))
            return

        self.video_panel.show_video(True)
        self.video_panel.set_duration(info.duration)
        self._load_source(path, position=0.0, play=False)
        self.project_label.setText(path.name)
        self.setWindowTitle(f"{APP_NAME} — {path.name}")
        self.analysis_panel.set_info("Vidéo", f"{info.resolution_label()} · {info.fps:.2f} fps")
        self.analysis_panel.set_info("Durée", format_time(info.duration))

        warnings = list(info.warnings)
        self.analysis_panel.set_warnings(warnings)
        self.status_message(
            f"Vidéo chargée — {info.resolution_label()} · {format_time(info.duration)}"
        )
        self._update_source_buttons()
        self._refresh_manual_markers()

        sidecar = self._find_sidecar(path)
        if sidecar and self.project.gyro is None:
            self.load_gyro(sidecar)
        elif self.project.gyro is not None:
            self._analysis_and_sync()
        self._update_actions()

    def load_gyro(self, path: Path) -> None:
        if not path.exists():
            self._error("Fichier introuvable", str(path))
            return
        try:
            track = self.project.load_gyro(path)
        except Exception as exc:  # noqa: BLE001
            self._error("Données gyroscopiques illisibles", str(exc))
            return

        self.analysis_panel.set_info("Gyroscope", path.name)
        self.analysis_panel.set_info("Fréquence", f"{track.raw_rate_hz:.0f} Hz natif · grille {track.sample_rate:.0f} Hz")
        if not self.project.video:
            self.analysis_panel.set_info("Durée", format_time(track.duration))
        warnings = [*track.warnings]
        if self.project.video and abs(track.duration - self.project.video.duration) > 1.5:
            warnings.append(
                f"Durée gyro ({track.duration:.1f} s) et vidéo "
                f"({self.project.video.duration:.1f} s) différentes."
            )
        self.analysis_panel.set_warnings(warnings)
        self.status_message(
            f"Gyroscope chargé — {track.n_samples} échantillons · {track.duration:.1f} s"
        )
        self._update_source_buttons()
        self._analysis_and_sync()

    def _find_sidecar(self, video: Path) -> Path | None:
        for suffix in (".gcsv", ".csv", ".txt"):
            candidate = video.with_suffix(suffix)
            if candidate.exists() and candidate != video:
                return candidate
        return None

    # ---------------------------------------------------------------- analyse
    def _analysis_and_sync(self) -> None:
        if self.project.gyro is None:
            return
        token = self._analysis_token + 1
        self._analysis_token = token
        self._set_busy(True, "Analyse du pilotage…")

        def job(progress: ProgressFn):
            return self.project.run_analysis(progress)

        self.tasks.start(
            job,
            on_finished=lambda result: self._on_analysis_done(result, token),
            on_failed=self._on_task_failed,
            on_progress=self._on_progress,
        )

    def _on_analysis_done(self, analysis, token: int) -> None:
        if token != self._analysis_token:
            return
        self._set_busy(False)
        self.status_message(
            f"Analyse terminée — {len(analysis.events)} figures détectées "
            f"(seuil de sensibilité inclus)"
        )
        self.timeline.set_data(
            analysis,
            self.project.plan,
            self.project.visible_events(),
            offset=self.project.offset,
        )
        self._refresh_events()
        if self.project.video is not None:
            self._auto_sync(auto=True)
        self._update_actions()

    def _auto_sync(self, auto: bool = False) -> None:
        if not self.project.video or not self.project.gyro or self._busy or self._sync_inflight:
            return
        self._sync_inflight = True
        self.analysis_panel.set_sync_status("Estimation du décalage en cours…")
        token = self._analysis_token

        def job(progress: ProgressFn):
            return self.project.suggested_offset()

        self.tasks.start(
            job,
            on_finished=lambda estimate: self._on_sync_estimate(estimate, token, auto),
            on_failed=lambda message: self._on_sync_failed(message, auto),
        )

    def _on_sync_estimate(self, estimate, token: int, auto: bool) -> None:
        self._sync_inflight = False
        if estimate is None:
            self.analysis_panel.set_sync_status("Synchronisation manuelle : aucun repère automatique.")
            self._resume_after_sync(auto)
            return
        confidence = int(round(estimate.confidence * 100))
        if not estimate.is_reliable:
            message = (
                f"Corrélation visuelle insuffisante ({confidence} %). "
                "Ajustez le décalage manuellement."
            )
            self.analysis_panel.set_sync_status(message, "warning")
            if auto:
                self.status_message(
                    "Synchronisation automatique non concluante — ajustez le décalage.", "warning"
                )
            self._resume_after_sync(auto)
            return
        message = (
            f"{estimate.method.replace('-', ' ')} · confiance {confidence} % · "
            f"décalage proposé {estimate.offset:+.3f} s"
        )
        if estimate.note:
            message += f"\n{estimate.note}"
        applied = False
        if (not auto or not self._manual_sync) and abs(estimate.offset) <= 8:
            self.project.offset = round(estimate.offset, 3)
            self.analysis_panel.set_offset(self.project.offset)
            self.timeline.set_data(
                self.project.analysis,
                self.project.plan,
                self.project.visible_events(),
                offset=self.project.offset,
            )
            applied = True
            message = "Décalage appliqué. " + message
            self.status_message(
                f"Synchronisation : décalage {self.project.offset:+.3f} s (confiance {confidence} %)"
            )
        self.analysis_panel.set_sync_status(message, "success")
        self._resume_after_sync(auto or applied)

    def _resume_after_sync(self, auto: bool) -> None:
        if self._pending_regenerate:
            self._pending_regenerate = False
            QTimer.singleShot(20, self._regenerate)
            return
        self.controls.set_preview_dirty(True)
        self.status_message(
            "Analyse et synchronisation prêtes — cliquez sur Régénérer la préécoute."
        )

    def _on_sync_failed(self, message: str, auto: bool) -> None:
        self._sync_inflight = False
        self.analysis_panel.set_sync_status(
            f"Corrélation impossible ({message}). Ajustez le décalage manuellement.", "warning"
        )
        self._resume_after_sync(auto)

    # ------------------------------------------------------------- pre-listen
    def _regenerate(self) -> None:
        self.regenerate_timer.stop()
        if self._busy or self._sync_inflight:
            self._pending_regenerate = True
            return
        if not self.project.analysis or not self.project.video:
            self.status_message(
                "Importez une vidéo et lancez l'analyse avant de générer.",
                "warning",
            )
            return
        if not self._ffmpeg_ok:
            self._error("FFmpeg manquant", self._ffmpeg_error)
            return
        self.project.sensitivity = self.controls.sensitivity.value() / 100.0
        self.controls.set_preview_dirty(False)
        token = self._generation_token + 1
        self._generation_token = token
        self._pending_regenerate = False
        self._set_busy(True, "Génération de la préécoute…")

        sensitivity = self.project.sensitivity

        def job(progress: ProgressFn):
            return self.project.generate(sensitivity, progress, build_preview=True)

        self.tasks.start(
            job,
            on_finished=lambda plan: self._on_generated(plan, token),
            on_failed=lambda message: self._on_generation_failed(message, token),
            on_progress=self._on_progress,
        )

    def _on_generated(self, plan, token: int) -> None:
        if token != self._generation_token:
            return
        self._set_busy(False)
        if self._pending_seek is not None:
            position = self._pending_seek
        else:
            position = max(0.0, self.player.position() / 1000.0)
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self._pending_play:
            playing = True
        if self.project.preview_path:
            self._load_source(self.project.preview_path, position=position, play=playing)
        self.controls.set_plan(plan, len(self.project.visible_events()))
        self.timeline.set_plan(plan)
        self.timeline.set_data(
            self.project.analysis,
            plan,
            self.project.visible_events(),
            offset=self.project.offset,
        )
        self._refresh_manual_markers()
        self._update_source_buttons()
        self.format_label.setText("48 kHz · stéréo · AAC 192 kb/s")
        timbre = (
            KIT_LABELS.get(plan.sound.kit, plan.sound.kit)
            if plan.style == "pulse"
            else ACCENT_LABELS.get(plan.sound.accent, plan.sound.accent)
        )
        self.status_message(
            f"Préécoute prête — {STYLE_LABELS.get(plan.style, plan.style)} · "
            f"{timbre} · {plan.bpm:.1f} BPM · {len(plan.hits)} frappes"
        )
        if self._pending_regenerate:
            self._pending_regenerate = False
            QTimer.singleShot(50, self._regenerate)

    def _on_generation_failed(self, message: str, token: int) -> None:
        if token != self._generation_token:
            return
        self._set_busy(False)
        self.controls.set_preview_dirty(True)
        self._error("Échec de la génération", message)

    def _on_progress(self, message: str, progress: float) -> None:
        self.status_message(message)
        self.progress_step.setText(message)
        self.progress_step.setToolTip(message)
        self.progress_step.show()
        self.progress_eta.show()
        self.progress_percent.show()
        if self._progress_started is not None and 0.02 < progress < 0.99:
            elapsed = time.monotonic() - self._progress_started
            remaining = max(0.0, elapsed * (1.0 - progress) / progress)
            if remaining >= 90:
                eta = f"~{int(remaining // 60)} min"
            elif remaining >= 1:
                eta = f"~{int(remaining)} s"
            else:
                eta = "finalisation"
        elif progress >= 0.99:
            eta = "finalisation"
        else:
            eta = "…"
        self.progress_eta.setText(eta)
        if progress > 0.01:
            clamped = max(0.0, min(1.0, progress))
            self.progress_percent.setText(f"{int(round(clamped * 100))} %")
            self.progress.setRange(0, 100)
            self.progress.setValue(int(clamped * 100))
        else:
            self.progress_percent.setText("…")
            self.progress.setRange(0, 0)
        if self._backend_operation:
            self.analysis_panel.set_backend_status(message, "hint")

    def _schedule_regeneration(self) -> None:
        self.regenerate_timer.stop()
        if self.project.analysis and self.project.video:
            self.controls.set_preview_dirty(True)
            self.status_message(
                "Préécoute à régénérer — cliquez sur Régénérer la préécoute."
            )

    def _on_style_changed(self, style: str) -> None:
        self.project.style = style
        self.status_message(
            f"Style {STYLE_LABELS.get(style, style)} — recalcul de la préécoute…"
        )
        self._schedule_regeneration()

    def _on_sound_changed(self) -> None:
        self.project.sound = self.controls.sound()
        self.status_message("Personnalisation du son — recalcul de la préécoute…")
        self._schedule_regeneration()

    def _update_source_buttons(self) -> None:
        available = {
            key: path.exists() for key, path in self.project.source_previews.items()
        }
        current = self.project.music_source
        if current not in available or not available.get(current):
            current = next((key for key in ("local", "hybrid", "ai") if available.get(key)), current)
        self.video_panel.set_source_state(available, current)

    def _switch_source(self, source: str) -> None:
        if source == self.project.music_source:
            return
        preview = self.project.set_music_source(source)
        if preview is None:
            self._update_source_buttons()
            return
        position = (
            self._pending_seek
            if self._pending_seek is not None
            else max(0.0, self.player.position() / 1000.0)
        )
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._load_source(preview, position=position, play=playing)
        labels = {
            "local": "VibeFlow (moteur local)",
            "ai": "ACE-Step seul",
            "hybrid": "Hybride (ACE-Step + rythme VibeFlow)",
        }
        self.status_message(f"Source musicale : {labels.get(source, source)}", "success")
        self._update_source_buttons()

    # ------------------------------------------------------------- backend
    def _refresh_backend_ui(self) -> None:
        path = self.backend.detect()
        managed = self.backend.managed_installed
        process_alive = (
            self.backend.process is not None and self.backend.process.poll() is None
        )
        healthy = self.backend.health(timeout=0.4)
        running = process_alive or healthy
        external = running and self.backend.process is None and not managed
        starting = self._backend_operation == "start" or (process_alive and not healthy)

        if self._backend_error:
            state = "error"
            text = "Erreur du serveur"
            eta = ""
            action = "Démarrer"
            enabled = not self._busy
            level = "error"
            status = self._backend_error.splitlines()[0]
        elif starting:
            state = "starting"
            text = "Démarrage du serveur…"
            eta = self._server_eta_text
            action = "Démarrer"
            enabled = False
            level = "warning"
            status = "Démarrage du serveur…"
        elif running:
            state = "working" if self._ai_busy else "ready"
            text = f"En ligne · {self.backend.url()}"
            if external:
                text += " · externe"
            eta = ""
            action = "Arrêter"
            enabled = not external and not self._busy
            level = "success"
            status = text
            self.project.ai_server = self.backend.url()
            self.controls.ai_server.setText(self.backend.url())
        elif path:
            state = "off"
            text = "Serveur arrêté"
            eta = ""
            action = "Démarrer"
            enabled = not self._busy
            level = "hint"
            status = "Prêt à démarrer"
            if not managed:
                status += " · installation externe détectée"
        else:
            state = "off"
            text = "Non installé"
            eta = ""
            action = "Installer"
            enabled = not self._busy
            level = "warning"
            status = "Non installé · téléchargement 2,4 Go"

        self.controls.set_server_state(
            state, text, eta=eta, action=action, enabled=enabled
        )
        self.analysis_panel.set_backend(
            status=status,
            level=level,
            path=str(path) if path else "",
            installed=bool(path),
            managed=managed,
            running=running,
            busy=self._busy,
            external=external,
        )

    def _update_server_eta(self) -> None:
        if self._backend_start_time is None:
            return
        elapsed = int(time.monotonic() - self._backend_start_time)
        remaining = max(0, 90 - elapsed)
        if remaining:
            self._server_eta_text = f"{elapsed} s · ~{remaining} s"
        else:
            self._server_eta_text = f"{elapsed} s · chargement…"
        self.controls.set_server_state(
            "starting",
            "Démarrage du serveur…",
            eta=self._server_eta_text,
            action="Démarrer",
            enabled=False,
        )

    def _toggle_backend(self) -> None:
        if self._busy:
            return
        if self.backend.is_running():
            self._stop_backend()
        elif self.backend.is_installed():
            self._start_backend()
        else:
            self._install_backend()

    def _install_backend(self) -> None:
        if self._busy:
            return
        if self.backend.managed_installed:
            self.status_message("Le moteur ACE-Step VibeFlow est déjà installé.", "success")
            return
        import shutil

        check_path = self.backend.root if self.backend.root.exists() else self.backend.root.parent
        try:
            free_gb = shutil.disk_usage(check_path).free / 1024**3
        except OSError:
            free_gb = 0.0
        answer = QMessageBox.question(
            self,
            "Installer le moteur ACE-Step",
            "VibeFlow va télécharger sa propre copie d'ACE-Step 1.5.\n\n"
            "• archive : ~2,4 Go\n"
            "• extraction : ~10 Go\n"
            "• modèles : copiés depuis une installation existante si possible\n\n"
            f"Espace libre : {free_gb:.1f} Go\n\nContinuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._backend_operation = "install"
        self._set_busy(True, "Installation du moteur ACE-Step…")
        self.progress.setRange(0, 100)
        self._refresh_backend_ui()

        def job(progress: ProgressFn):
            return self.backend.install(progress)

        self.tasks.start(
            job,
            on_finished=self._on_backend_installed,
            on_failed=self._on_backend_failed,
            on_progress=self._on_progress,
        )

    def _on_backend_installed(self, path) -> None:
        self._backend_operation = None
        self._set_busy(False)
        self._refresh_backend_ui()
        self.status_message(f"Moteur ACE-Step installé — {path}", "success")
        answer = QMessageBox.question(
            self,
            "Moteur installé",
            "ACE-Step est installé dans VibeFlow.\nDémarrer le serveur maintenant ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_backend()

    def _start_backend(self) -> None:
        if self._busy:
            return
        if not self.backend.is_installed():
            self.status_message("ACE-Step n'est pas installé.", "warning")
            self._install_backend()
            return
        self._backend_operation = "start"
        self._backend_error = None
        self._backend_start_time = time.monotonic()
        self._server_eta_text = "0 s · ~90 s"
        self.server_eta_timer.start()
        self._set_busy(True, "Démarrage du moteur ACE-Step…")
        self._refresh_backend_ui()

        def job(progress: ProgressFn):
            return self.backend.start(progress)

        self.tasks.start(
            job,
            on_finished=self._on_backend_started,
            on_failed=self._on_backend_failed,
            on_progress=self._on_progress,
        )

    def _on_backend_started(self, url: str) -> None:
        self._backend_operation = None
        self._backend_start_time = None
        self._backend_error = None
        self.server_eta_timer.stop()
        self._set_busy(False)
        self.project.ai_server = url
        self.controls.ai_server.setText(url)
        self._refresh_backend_ui()
        self.status_message(f"Moteur ACE-Step en ligne — {url}", "success")

    def _stop_backend(self) -> None:
        if self.backend.process is None and not self.backend.health():
            self.status_message("Aucun serveur ACE-Step à arrêter.", "warning")
            return
        if self._busy:
            return
        self._backend_operation = "stop"
        self._backend_error = None
        self._backend_start_time = None
        self.server_eta_timer.stop()
        self._set_busy(True, "Arrêt du moteur ACE-Step…")
        self._refresh_backend_ui()

        def job(progress: ProgressFn):
            self.backend.stop()
            return True

        self.tasks.start(
            job,
            on_finished=lambda _r: self._on_backend_stopped(),
            on_failed=self._on_backend_failed,
            on_progress=self._on_progress,
        )

    def _on_backend_stopped(self) -> None:
        self._backend_operation = None
        self._backend_error = None
        self._set_busy(False)
        self._refresh_backend_ui()
        self.status_message("Moteur ACE-Step arrêté.")

    def _on_backend_failed(self, message: str) -> None:
        self._backend_operation = None
        self._backend_start_time = None
        self._backend_error = message
        self.server_eta_timer.stop()
        self._set_busy(False)
        self._refresh_backend_ui()
        self.status_message(message.splitlines()[0], "error")
        self._error("Moteur ACE-Step", message[:3000])

    def _show_backend_logs(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Journaux ACE-Step")
        dialog.resize(900, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas'; font-size: 11px; "
            f"background: {theme.COLORS['bg']}; color: {theme.COLORS['text']};"
        )
        text.setPlainText(self.backend.logs(300))
        layout.addWidget(text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        refresh = QPushButton("Rafraîchir")
        close = QPushButton("Fermer")
        refresh.clicked.connect(lambda: text.setPlainText(self.backend.logs(300)))
        close.clicked.connect(dialog.accept)
        row.addWidget(refresh)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    def _sync_ai_settings(self) -> None:
        settings = self.controls.ai_settings()
        self.project.ai_server = settings["server"]
        self.project.ai_prompt = settings["prompt"]
        self.project.ai_mix_accents = settings["mix_accents"]

    def _generate_ai(self) -> None:
        if self._busy:
            self.status_message("Une opération est déjà en cours.", "warning")
            return
        if self.project.video is None:
            self.status_message("Importez d'abord une vidéo.", "warning")
            return
        if not self._ffmpeg_ok:
            self._error("FFmpeg manquant", self._ffmpeg_error)
            return
        self._sync_ai_settings()
        token = self._generation_token + 1
        self._generation_token = token
        self._ai_busy = True
        self._set_busy(True, "Génération ACE-Step…")
        self.controls.set_ai_busy(True)
        self.controls.set_ai_status("Connexion au serveur ACE-Step…")

        def job(progress: ProgressFn):
            return self.project.generate_ai(progress)

        self.tasks.start(
            job,
            on_finished=lambda result: self._on_ai_done(result, token),
            on_failed=lambda message: self._on_ai_failed(message, token),
            on_progress=self._on_progress,
        )

    def _on_ai_done(self, result, token: int) -> None:
        if token != self._generation_token:
            return
        self._ai_busy = False
        self._set_busy(False)
        self.controls.set_ai_busy(False)
        if self.project.preview_path:
            position = (
                self._pending_seek
                if self._pending_seek is not None
                else max(0.0, self.player.position() / 1000.0)
            )
            playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            self._load_source(self.project.preview_path, position=position, play=playing)
        bpm = ""
        if result.tracks:
            meta = result.tracks[0].metadata or {}
            if meta.get("bpm"):
                bpm = f" · {int(meta['bpm'])} BPM"
        mode = (
            "Hybride : nappe ACE-Step + rythme VibeFlow"
            if self.project.ai_mix_accents
            else "ACE-Step seul"
        )
        details = ""
        if self.project.video and self.project.plan:
            details = (
                f" · envoyé : {self.project.video.duration:.0f} s · "
                f"{self.project.plan.bpm:.0f} BPM · A minor · "
                f"{len(self.project.plan.sections)} sections"
            )
        self.controls.set_ai_status(
            f"{mode}{bpm}{details}", "success"
        )
        self.status_message(f"Musique prête — {mode}{bpm}")
        self._update_source_buttons()
        self._update_actions()
        self._notify_done(
            "VibeFlow — piste ACE-Step prête",
            f"{mode}{bpm} — génération terminée.",
        )

    def _on_ai_failed(self, message: str, token: int) -> None:
        if token != self._generation_token:
            return
        self._ai_busy = False
        self._set_busy(False)
        self.controls.set_ai_busy(False)
        self.controls.set_ai_status(message, "error")
        self._error("Génération ACE-Step impossible", message)

    def _on_sensitivity(self, value: float) -> None:
        self.project.sensitivity = value
        self._refresh_events()
        self.timeline.set_events(self.project.visible_events())
        self.timeline.set_data(
            self.project.analysis,
            self.project.plan,
            self.project.visible_events(),
            offset=self.project.offset,
        )
        self.status_message(f"Sensibilité {int(round(value * 100))} % — recalcul de la préécoute…")
        if not self.controls.sensitivity.isSliderDown():
            self._schedule_regeneration()

    def _on_offset_changed(self, value: float) -> None:
        self._manual_sync = True
        self.project.offset = value
        self.timeline.set_data(
            self.project.analysis,
            self.project.plan,
            self.project.visible_events(),
            offset=value,
        )
        self._schedule_regeneration()

    def _on_event_toggled(self, index: int, enabled: bool) -> None:
        self.project.set_event_enabled(index, enabled)
        self._refresh_events()
        self.timeline.set_events(self.project.visible_events())
        self._schedule_regeneration()

    def _on_event_selected(self, index: int) -> None:
        self.event_table.select_event(index)
        self.timeline.set_selected(index)

    def _on_event_activated(self, index: int) -> None:
        event = next((e for e in self.project.candidates() if e.index == index), None)
        if event:
            self.seek(event.t_peak + self.project.offset)
            self.timeline.set_selected(index)

    def _enable_all_events(self) -> None:
        self.project.disabled_events.clear()
        self._refresh_events()
        self.timeline.set_events(self.project.visible_events())
        self._schedule_regeneration()

    def _refresh_events(self) -> None:
        candidates = self.project.candidates()
        self.event_table.populate(candidates)
        enabled = sum(1 for event in candidates if event.enabled)
        self.event_count.setText(
            f"{enabled}" if enabled == len(candidates) else f"{enabled} / {len(candidates)}"
        )
        self.controls.set_plan(self.project.plan, enabled)

    # ------------------------------------------------------------------ player
    def _load_source(self, path: Path, position: float = 0.0, play: bool = False) -> None:
        self._pending_seek = position
        self._pending_play = play
        self._source_loading = True
        self._current_source_path = Path(path)
        self.original_player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def _original_audio_active(self) -> bool:
        return bool(
            self.video_panel.audio_button.isChecked()
            and self.project.video is not None
            and self._current_source_path is not None
            and Path(self.project.video.path).resolve()
            != self._current_source_path.resolve()
        )

    def _toggle_original_audio(self, enabled: bool) -> None:
        if not enabled:
            self.original_player.stop()
            self._original_source = None
            self.status_message("Audio vidéo désactivé.")
            return
        if self.project.video is None:
            self.status_message("Importez d'abord une vidéo.", "warning")
            return
        self._sync_original_audio()
        self.status_message("Audio vidéo activé (volume réduit).")

    def _sync_original_audio(self) -> None:
        if not self._original_audio_active():
            self.original_player.stop()
            self._original_source = None
            return
        video_path = Path(self.project.video.path)
        target = int(max(0, self.player.position()))
        if self._original_source != video_path:
            self._original_source = video_path
            self._original_pending_seek = target
            self.original_player.setSource(QUrl.fromLocalFile(str(video_path)))
            return
        if abs(self.original_player.position() - target) > 180:
            self.original_player.setPosition(target)
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.original_player.play()
        else:
            self.original_player.pause()

    def _on_original_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status not in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            return
        if self._original_pending_seek is not None:
            self.original_player.setPosition(self._original_pending_seek)
            self._original_pending_seek = None
        if self._original_audio_active() and self.player.playbackState() == (
            QMediaPlayer.PlaybackState.PlayingState
        ):
            self.original_player.play()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._source_loading = False
            if self._pending_seek is not None:
                self.player.setPosition(int(max(0.0, self._pending_seek) * 1000))
                self._pending_seek = None
            if self._pending_play:
                self._pending_play = False
                self.player.play()
            self._sync_original_audio()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._source_loading = False

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.video_panel.set_playing(state == QMediaPlayer.PlaybackState.PlayingState)
        self._update_actions()
        self._sync_original_audio()

    def _on_player_error(self, error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self.status_message(f"Lecture impossible : {message}", "error")

    def _tick_playhead(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            position = self.player.position() / 1000.0
            self.timeline.set_position(position)
            self.video_panel.set_position(position)
            if self._original_audio_active():
                if abs(self.original_player.position() - self.player.position()) > 300:
                    self.original_player.setPosition(self.player.position())
        elif self.player.position() >= 0:
            position = self.player.position() / 1000.0
            self.timeline.set_position(position)
            self.video_panel.set_position(position)

    def toggle_play(self) -> None:
        if not self.project.video:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._pending_play = False
            self.player.pause()
        elif self.player.mediaStatus() in (
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.LoadingMedia,
        ) or self._source_loading:
            self._pending_play = True
        else:
            self.player.play()

    def seek(self, seconds: float) -> None:
        if not self.project.video:
            return
        seconds = max(0.0, min(seconds, self.project.video.duration))
        if self.player.mediaStatus() in (
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.LoadingMedia,
        ):
            self._pending_seek = seconds
        else:
            self.player.setPosition(int(seconds * 1000))
            if self.original_player.source().isValid():
                self.original_player.setPosition(int(seconds * 1000))
        self.timeline.set_position(seconds)
        self.video_panel.set_position(seconds)

    def _nudge(self, delta: float) -> None:
        self.seek(self.player.position() / 1000.0 + delta)

    def _step_frame(self, direction: int) -> None:
        if not self.project.video:
            return
        self.player.pause()
        step = 1.0 / (self.project.video.fps or 30.0)
        self.seek(self.player.position() / 1000.0 + direction * step)

    def _on_volume(self, value: int) -> None:
        self.audio_output.setVolume(max(0.0, min(1.0, value / 100.0)))

    # ------------------------------------------------------------------ state
    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = busy
        self.controls.set_busy(busy)
        self.controls.set_ai_busy(busy)
        self.progress.setVisible(busy)
        if busy:
            self._progress_started = time.monotonic()
            self.progress.setRange(0, 0)
            self.progress_step.setText(message or "Traitement…")
            self.progress_step.setToolTip(message or "")
            self.progress_step.show()
            self.progress_eta.setText("…")
            self.progress_eta.show()
            self.progress_percent.setText("…")
            self.progress_percent.show()
        else:
            self._progress_started = None
            self.progress.setRange(0, 100)
            self.progress_step.hide()
            self.progress_eta.hide()
            self.progress_percent.hide()
        if message:
            self.status_message(message)
        self._update_actions()
        if hasattr(self, "analysis_panel"):
            self._refresh_backend_ui()

    def status_message(self, message: str, level: str = "info") -> None:
        self._last_status = (message, level)
        color = {
            "info": theme.COLORS["text_dim"],
            "error": theme.COLORS["danger"],
            "warning": theme.COLORS["warning"],
            "success": theme.COLORS["success"],
        }.get(level, theme.COLORS["text_dim"])
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(message)

    def _update_actions(self) -> None:
        has_video = self.project.video is not None
        has_audio = self.project.active_audio_path() is not None
        self.btn_export.setEnabled(has_video)
        self.action_export_wav.setEnabled(has_audio)
        self.action_export_mp4.setEnabled(has_audio)
        self.controls.generate_button.setEnabled(
            self.project.analysis is not None and not self._busy
        )
    def _on_task_failed(self, message: str) -> None:
        self._set_busy(False)
        self._error("Erreur de traitement", message)

    def _error(self, title: str, message: str) -> None:
        self.status_message(message, "error")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()

    # ----------------------------------------------------------------- export
    def save_project_dialog(self) -> None:
        if not self.project.video:
            self.status_message("Aucun projet à enregistrer.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le projet", self._default_name(".vibeflow"), "Projet VibeFlow (*.vibeflow)"
        )
        if not path:
            return
        self._sync_ai_settings()
        try:
            self.project.save(path)
            self.status_message(f"Projet enregistré — {Path(path).name}", "success")
        except Exception as exc:  # noqa: BLE001
            self._error("Enregistrement impossible", str(exc))

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", self._last_dir, "Projet VibeFlow (*.vibeflow)"
        )
        if not path:
            return
        self._load_project(Path(path))

    def _load_project(self, path: Path) -> None:
        if self._busy:
            self.status_message("Une opération est en cours.", "warning")
            return
        try:
            self.project.load(path, run_analysis=False)
        except Exception as exc:  # noqa: BLE001
            self._error("Ouverture impossible", str(exc))
            return
        self._manual_sync = abs(self.project.offset) > 1e-6
        self.controls.set_sensitivity(self.project.sensitivity)
        self.controls.set_style(self.project.style)
        self.controls.set_sound(self.project.sound)
        self.controls.set_ai_settings(
            self.project.ai_server, self.project.ai_prompt, self.project.ai_mix_accents
        )
        self.video_panel.manual_button.blockSignals(True)
        self.video_panel.manual_button.setChecked(False)
        self.video_panel.manual_button.blockSignals(False)
        self._manual_mode = False
        self.video_panel.manual_button.setText("Marquer")
        self._set_manual_selection(None)
        for shortcut in self._manual_shortcuts:
            shortcut.setEnabled(False)
        for shortcut in self._nudge_shortcuts:
            shortcut.setEnabled(True)
        self._sync_manual_controls()
        self._rebuild_manual_shortcuts()
        self._refresh_manual_markers()
        self.analysis_panel.set_offset(self.project.offset)
        if self.project.video:
            info = self.project.video
            self.video_panel.show_video(True)
            self.video_panel.set_duration(info.duration)
            self._load_source(info.path, 0.0)
            self.project_label.setText(info.path.name)
            self.analysis_panel.set_info("Vidéo", f"{info.resolution_label()} · {info.fps:.2f} fps")
            self.analysis_panel.set_info("Durée", format_time(info.duration))
        if self.project.gyro:
            self.analysis_panel.set_info("Gyroscope", self.project.gyro.source.name if self.project.gyro.source else "—")
            self.analysis_panel.set_info(
                "Fréquence",
                f"{self.project.gyro.raw_rate_hz:.0f} Hz natif · grille {self.project.gyro.sample_rate:.0f} Hz",
            )
        self.timeline.set_data(None, None, [], offset=self.project.offset)
        self._refresh_events()
        self.status_message(f"Projet chargé — {path.name}", "success")
        if self.project.gyro is not None:
            self._analysis_and_sync()
        elif self.project.video is not None:
            self.controls.set_preview_dirty(True)
            self.status_message(
                "Projet chargé — cliquez sur Régénérer la préécoute.", "success"
            )

    def export_wav_dialog(self) -> None:
        if self.project.active_audio_path() is None:
            self.status_message("Générez d'abord la préécoute.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la musique", self._default_name("_musique.wav"), "Audio WAV (*.wav)"
        )
        if not path:
            return
        try:
            self.project.export_wav(path)
            self.status_message(f"Musique exportée — {Path(path).name}", "success")
            self._show_export_result(Path(path))
        except Exception as exc:  # noqa: BLE001
            self._error("Export impossible", str(exc))

    def export_video_dialog(self) -> None:
        if self.project.active_audio_path() is None:
            self.status_message("Générez d'abord la préécoute.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la vidéo", self._default_name("_VibeFlow.mp4"), "Vidéo MP4 (*.mp4)"
        )
        if not path:
            return
        include_original = False
        if self.project.video and self.project.video.has_audio:
            answer = QMessageBox.question(
                self,
                "Audio d'origine",
                "Conserver l'audio d'origine de la caméra en fond sonore ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            include_original = answer == QMessageBox.StandardButton.Yes
        self._set_busy(True, "Export de la vidéo…")

        def job(progress: ProgressFn):
            return self.project.export_video(
                path, include_original_audio=include_original, progress=progress
            )

        self.tasks.start(
            job,
            on_finished=lambda result: self._on_export_done(result),
            on_failed=self._on_export_failed,
            on_progress=self._on_progress,
        )

    def _on_export_done(self, result) -> None:
        self._set_busy(False)
        self.status_message(f"Vidéo exportée — {Path(result).name}", "success")
        self._show_export_result(Path(result))

    def _show_export_result(self, path: Path) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Export terminé")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Export terminé :\n{path}")
        label.setWordWrap(True)
        layout.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        open_file = QPushButton("Ouvrir le fichier")
        open_file.setObjectName("Primary")
        open_folder = QPushButton("Ouvrir l'emplacement")
        close = QPushButton("Fermer")
        open_file.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        )
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        )
        close.clicked.connect(dialog.accept)
        row.addWidget(open_file)
        row.addWidget(open_folder)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    def _on_export_failed(self, message: str) -> None:
        self._set_busy(False)
        self._error("Échec de l'export", message)

    def _default_name(self, suffix: str) -> str:
        if self.project.video:
            return str(self.project.video.path.with_name(self.project.video.path.stem + suffix))
        return str(Path(self._last_dir) / f"VibeFlow{suffix}")

    # ------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if not urls:
            return
        video = next((p for p in urls if p.suffix.lower() in VIDEO_EXTENSIONS), None)
        gyro = next((p for p in urls if p.suffix.lower() in GYRO_EXTENSIONS), None)
        project = next((p for p in urls if p.suffix.lower() == ".vibeflow"), None)
        if project:
            self._load_project(project)
            return
        if video:
            self.load_video(video)
        if gyro:
            self.load_gyro(gyro)
        elif video and self.project.gyro is None:
            sidecar = self._find_sidecar(video)
            if sidecar:
                self.load_gyro(sidecar)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self.ui_settings.setValue("ui/main_splitter", self.main_splitter.sizes())
        self.ui_settings.setValue("ui/left_splitter", self.left_splitter.sizes())
        self.ui_settings.setValue("ui/layout_version", 2)
        if self.backend.process is not None:
            try:
                self.backend.stop()
            except Exception:
                pass
        self.playhead_timer.stop()
        self.player.stop()
        self.original_player.stop()
        self.player.setSource(QUrl())
        self.tasks.wait(2000)
        super().closeEvent(event)
