from __future__ import annotations

import numpy as np
import pytest

from vibeflow.core.analysis import analyse, filter_by_sensitivity
from vibeflow.core.gyro import load_gyro
from vibeflow.core.rhythm import (
    ACCENT_LABELS,
    MANUAL_DEFAULT_SOUNDS,
    ManualAccent,
    ManualTrack,
    SoundSettings,
    build_plan,
    estimate_tempo,
    plan_summary,
)

from .test_gyro import flight_rates, make_gcsv


@pytest.fixture
def plan(tmp_path):
    path = tmp_path / "flight.gcsv"
    path.write_text(make_gcsv(flight_rates()), encoding="utf-8")
    analysis = analyse(load_gyro(path))
    events = filter_by_sensitivity(analysis.events, 0.5)
    return analysis, build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="pulse",
    )


def test_tempo_is_musical(plan):
    _, result = plan
    assert 88 <= result.bpm <= 168
    assert 0 <= result.beat_offset < 60 / result.bpm * 4


def test_plan_has_musical_layers(plan):
    _, result = plan
    instruments = {hit.instrument for hit in result.hits}
    assert {"kick", "sub", "hat"} <= instruments
    assert plan_summary(result)["hits"] > 40


def test_accents_are_exactly_on_event_peaks(plan):
    analysis, result = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    impacts = [h.time for h in result.hits if h.instrument == "impact"]
    assert impacts
    figure_peaks = [
        e.t_peak for e in events if e.kind not in {"accel", "brake", "flow", "switch"}
    ]
    for impact in impacts:
        # The final resolve is an intentional composition choice.
        if abs(impact - (result.duration - 1.2)) < 0.01:
            continue
        assert min(abs(impact - t) for t in figure_peaks) < 1e-6


def test_hits_stay_inside_video(plan):
    _, result = plan
    assert all(0 <= hit.time < result.duration for hit in result.hits)
    assert all(hit.velocity <= 1.0 for hit in result.hits)


def test_plan_is_deterministic(plan):
    analysis, first = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    second = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="pulse",
    )
    assert [(h.time, h.instrument) for h in first.hits] == [
        (h.time, h.instrument) for h in second.hits
    ]


def test_evasion_style_is_ambient_and_synced(plan):
    analysis, _ = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    result = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="evasion",
    )
    assert result.style == "evasion"
    assert 78 <= result.bpm <= 92
    instruments = {hit.instrument for hit in result.hits}
    assert {"pad_warm", "arp", "guitar", "boom", "softkick", "drone"} <= instruments
    assert not ({"clap", "hat", "openhat", "impact", "crash", "bell"} & instruments)
    assert all(0 <= hit.time < result.duration for hit in result.hits)

    figure_peaks = [event.t_peak for event in events if event.kind != "flow"]
    strums = [hit.time for hit in result.hits if hit.instrument == "guitar"]
    assert strums
    for strum in strums:
        assert min(abs(strum - peak) for peak in figure_peaks) < 0.11


def test_sound_settings_customise_the_plan(plan):
    analysis, _ = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    common = dict(
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="evasion",
    )
    dense = build_plan(
        events, **common, sound=SoundSettings(accent="guitar", density=0.95)
    )
    sparse = build_plan(
        events, **common, sound=SoundSettings(accent="piano", density=0.2)
    )
    bell = build_plan(events, **common, sound=SoundSettings(accent="bell"))
    assert len(sparse.hits) < len(dense.hits)
    assert "piano" in {hit.instrument for hit in sparse.hits}
    assert "bell" in {hit.instrument for hit in bell.hits}
    assert "guitar" in {hit.instrument for hit in dense.hits}


@pytest.mark.parametrize("accent", sorted(ACCENT_LABELS))
def test_every_accent_timbre_is_used(plan, accent):
    analysis, _ = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    result = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="evasion",
        sound=SoundSettings(accent=accent),
    )
    instruments = {hit.instrument for hit in result.hits}
    expected = "bell" if accent == "bell" else accent
    assert expected in instruments


def test_manual_accents_are_added_at_exact_times(plan):
    analysis, _ = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    accents = [
        ManualAccent(time=1.25, lane=0),
        ManualAccent(time=2.50, lane=2),
        ManualAccent(time=3.75, lane=3),
    ]
    tracks = [
        ManualTrack(name="A", sound="impact"),
        ManualTrack(name="B", sound="kick"),
        ManualTrack(name="C", sound="marimba"),
        ManualTrack(name="D", sound="bell"),
    ]
    result = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        sensitivity=0.5,
        style="evasion",
        manual_accents=accents,
        manual_tracks=tracks,
    )
    manual = [hit for hit in result.hits if hit.manual]
    assert len(manual) == 3
    assert [(hit.time, hit.instrument) for hit in manual] == [
        (1.25, "impact"),
        (2.50, "marimba"),
        (3.75, "bell"),
    ]
    marimba = next(hit for hit in manual if hit.instrument == "marimba")
    assert marimba.note is not None and marimba.duration > 1.0


def test_disabled_manual_track_is_silent(plan):
    analysis, _ = plan
    events = filter_by_sensitivity(analysis.events, 0.5)
    tracks = [ManualTrack(name="A", sound="impact", enabled=False)]
    result = build_plan(
        events,
        duration=analysis.duration,
        activity=analysis.activity,
        activity_t=analysis.activity_t,
        style="evasion",
        manual_accents=[ManualAccent(1.0, 0)],
        manual_tracks=tracks,
    )
    assert not [hit for hit in result.hits if hit.manual]


def test_manual_accents_do_not_need_analysis_events():
    activity = np.ones(10, dtype=np.float32)
    activity_t = np.linspace(0, 4, 10)
    tracks = [
        ManualTrack(name=name, sound=sound)
        for name, sound in zip(("A", "B", "C", "D"), MANUAL_DEFAULT_SOUNDS)
    ]
    result = build_plan(
        [],
        duration=4.0,
        activity=activity,
        activity_t=activity_t,
        style="pulse",
        manual_accents=[ManualAccent(0.5, 1)],
        manual_tracks=tracks,
    )
    manual = [hit for hit in result.hits if hit.manual]
    assert manual and manual[0].instrument == "kick"
    assert manual[0].time == pytest.approx(0.5)


def test_tempo_estimator_recovers_grid():
    from vibeflow.core.analysis import FlightEvent

    bpm = 128.0
    beat = 60 / bpm
    events = [
        FlightEvent(
            index=i,
            kind="flip",
            axis=0,
            t_start=t - 0.2,
            t_peak=t,
            t_end=t + 0.2,
            angle_deg=360,
            peak_rate_dps=500,
            peak_accel_dps2=1000,
            score=0.8,
            monotonicity=0.9,
        )
        for i, t in enumerate([0.0, beat, 2 * beat, 4 * beat, 5 * beat, 8 * beat])
    ]
    estimated, offset = estimate_tempo(events, duration=30.0)
    assert estimated == pytest.approx(128.0, abs=2.0)
    assert abs(offset % beat) < 0.06 or abs((offset % beat) - beat) < 0.06
