from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from vibeflow.core.analysis import analyse  # noqa: E402
from vibeflow.core.gyro import load_gyro  # noqa: E402
from vibeflow.core.rhythm import build_plan  # noqa: E402

from .test_gyro import flight_rates, make_gcsv  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ui")
    path = directory / "flight.gcsv"
    path.write_text(make_gcsv(flight_rates(duration=20.0)), encoding="utf-8")
    return analyse(load_gyro(path))


def test_main_window_builds(qapp, analysis):
    from vibeflow.ui.main_window import MainWindow

    window = MainWindow()
    assert window.timeline.minimumHeight() >= 140
    assert window.tabs.count() == 3
    assert len(window.video_panel.source_buttons) == 3
    assert window.controls.preset_combo.count() >= 5
    assert window.event_table.rowCount() == 0
    assert len(window.project.manual_tracks) == 4
    assert window.controls.manual_move_step.value() == 50
    window._toggle_manual_mode(True)
    assert all(shortcut.isEnabled() for shortcut in window._manual_shortcuts)
    assert not window._nudge_shortcuts[0].isEnabled()
    window._toggle_manual_mode(False)
    assert window._nudge_shortcuts[0].isEnabled()
    window.close()


def test_timeline_paints_data(qapp, analysis):
    from vibeflow.ui.widgets.timeline import Timeline

    events = analysis.events
    plan = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
    )
    timeline = Timeline()
    timeline.resize(1100, 200)
    timeline.set_data(analysis, plan, events, offset=0.0)
    pixmap = timeline.grab()
    assert not pixmap.isNull()
    assert timeline.current_view()[1] == pytest.approx(analysis.duration)
    timeline.close()


def test_preview_is_not_generated_automatically(qapp, analysis):
    from types import SimpleNamespace

    from vibeflow.ui.main_window import MainWindow

    window = MainWindow()
    window.project.analysis = analysis
    window.project.video = SimpleNamespace(duration=analysis.duration, path=None)
    token = window._generation_token
    window._schedule_regeneration()
    assert window._generation_token == token
    assert window.controls.generate_button.text().startswith("●")
    window.close()


def test_original_audio_only_when_preview_is_loaded(qapp):
    from pathlib import Path
    from types import SimpleNamespace

    from vibeflow.ui.main_window import MainWindow

    window = MainWindow()
    window.project.video = SimpleNamespace(duration=10.0, path="S:/media/flight.mp4")
    window.video_panel.audio_button.setChecked(True)
    window._current_source_path = Path("S:/cache/preview.mp4")
    assert window._original_audio_active()
    window._current_source_path = Path("S:/media/flight.mp4")
    assert not window._original_audio_active()
    window.close()


def test_event_table_lists_disabled_events(qapp):
    from vibeflow.core.analysis import FlightEvent
    from vibeflow.ui.widgets.event_table import EventTable

    table = EventTable()
    event = FlightEvent(
        index=3,
        kind="flip",
        axis=1,
        t_start=1.0,
        t_peak=1.2,
        t_end=1.6,
        angle_deg=360,
        peak_rate_dps=600,
        peak_accel_dps2=2000,
        score=0.9,
        monotonicity=0.9,
        enabled=False,
    )
    table.populate([event])
    assert table.rowCount() == 1
    assert table.item(0, 0).checkState().name == "Unchecked"
    table.close()
