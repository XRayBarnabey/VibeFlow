from __future__ import annotations

import numpy as np
import pytest

from vibeflow.core.analysis import (
    analyse,
    filter_by_sensitivity,
    score_threshold,
)
from vibeflow.core.gyro import load_gyro

from .test_gyro import flight_rates, make_gcsv


@pytest.fixture
def analysis(tmp_path):
    path = tmp_path / "flight.gcsv"
    path.write_text(make_gcsv(flight_rates()), encoding="utf-8")
    return analyse(load_gyro(path))


def test_detects_main_figures(analysis):
    kinds = {e.kind for e in analysis.events}
    assert "roll360" in kinds
    assert "inversion" in kinds
    peaks = np.array([e.t_peak for e in analysis.events if e.kind == "roll360"])
    assert len(peaks) == 1
    assert peaks[0] == pytest.approx(10.35, abs=0.1)


def test_ignores_small_correction(analysis):
    near_correction = [
        e
        for e in analysis.events
        if abs(e.t_peak - 20.15) < 0.3
        and e.kind not in {"accel", "brake", "flow"}
    ]
    assert near_correction == []
    assert all(
        abs(e.t_peak - 20.15) > 0.3
        for e in filter_by_sensitivity(analysis.events, 0.0)
    )


def test_sensitivity_filters_progressively(analysis):
    low = filter_by_sensitivity(analysis.events, 0.0)
    high = filter_by_sensitivity(analysis.events, 1.0)
    assert len(high) >= len(low)
    assert score_threshold(0.0) > score_threshold(1.0)
    assert all(e.score >= score_threshold(1.0) for e in high)
    assert any(e.kind == "roll360" for e in low)


def test_disabled_events_are_excluded(analysis):
    event = analysis.events[0]
    event.enabled = False
    assert event not in filter_by_sensitivity(analysis.events, 1.0)


def test_activity_matches_duration(analysis):
    assert len(analysis.activity) == len(analysis.track.t)
    assert analysis.activity.max() > 200


def test_axis_mapping():
    from vibeflow.core.analysis import _classify_episode

    assert _classify_episode(0, 360, 0) == "roll360"
    assert _classify_episode(0, 180, 0) == "inversion"
    assert _classify_episode(1, 300, 0) == "flip"
    assert _classify_episode(2, 400, 0) == "spin"
    assert _classify_episode(0, 300, 120) == "combo"
