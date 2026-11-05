from __future__ import annotations

import numpy as np
import pytest

from vibeflow.core.gyro import load_gyro
from vibeflow.core.project import Project
from vibeflow.core.rhythm import ManualAccent, SoundSettings
from vibeflow.media.ffmpeg import find_ffmpeg, probe_audio_duration, probe_video, run_hidden

from .test_gyro import flight_rates, make_gcsv


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    directory = tmp_path_factory.mktemp("media")
    path = directory / "sample.mp4"
    ffmpeg = find_ffmpeg()
    result = run_hidden(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=16",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=16",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return path


@pytest.fixture(scope="module")
def sample_gyro(tmp_path_factory):
    directory = tmp_path_factory.mktemp("gyro")
    path = directory / "flight.gcsv"
    path.write_text(make_gcsv(flight_rates(duration=16.0)), encoding="utf-8")
    return path


def test_probe_video(sample_video):
    info = probe_video(sample_video)
    assert info.width == 640 and info.height == 360
    assert info.fps == pytest.approx(30.0, abs=0.1)
    assert info.has_audio
    assert info.duration == pytest.approx(16.0, abs=0.2)


def test_full_pipeline(sample_video, sample_gyro, tmp_path):
    project = Project(work_dir=tmp_path / "work")
    project.load_video(sample_video)
    track = project.load_gyro(sample_gyro)
    assert track.duration == pytest.approx(16.0, abs=0.05)

    analysis = project.run_analysis()
    assert analysis.events

    project.manual_accents = [
        ManualAccent(time=2.0, lane=0),
        ManualAccent(time=5.5, lane=2),
    ]
    for track, sound in zip(
        project.manual_tracks, ("impact", "kick", "marimba", "hat")
    ):
        track.sound = sound
    plan = project.generate(0.4)
    assert plan.hits
    manual = [hit for hit in plan.hits if hit.manual]
    assert [(round(hit.time, 2), hit.instrument) for hit in manual] == [
        (2.0, "impact"),
        (5.5, "marimba"),
    ]
    assert project.audio_path and project.audio_path.exists()
    assert probe_audio_duration(project.audio_path) == pytest.approx(16.0, abs=1.2)

    preview = probe_video(project.preview_path)
    assert preview.has_audio
    assert preview.duration == pytest.approx(16.0, abs=0.4)

    exported = project.export_wav(tmp_path / "master.wav")
    assert exported.exists() and exported.stat().st_size > 100_000

    video_export = project.export_video(tmp_path / "flight_music.mp4")
    info = probe_video(video_export)
    assert info.has_audio
    assert info.video_codec == "h264"

    mixed_export = project.export_video(
        tmp_path / "flight_mixed.mp4", include_original_audio=True
    )
    assert probe_audio_duration(mixed_export) == pytest.approx(16.0, abs=0.6)

    # Sensitivity regeneration must stay fast and coherent.
    project.generate(0.9, build_preview=False)
    assert project.audio_path.exists()


def test_offset_shifts_accents(sample_video, sample_gyro, tmp_path):
    project = Project(work_dir=tmp_path / "work_offset")
    project.load_video(sample_video)
    project.load_gyro(sample_gyro)
    project.run_analysis()
    project.style = "pulse"
    project.offset = 0.0
    base = project.generate(0.4, build_preview=False)
    base_impacts = sorted(h.time for h in base.hits if h.instrument == "impact" and h.time < 14.0)
    project.offset = 0.35
    shifted = project.generate(0.4, build_preview=False)
    shifted_impacts = sorted(h.time for h in shifted.hits if h.instrument == "impact" and h.time < 14.0)
    assert base_impacts and len(base_impacts) == len(shifted_impacts)
    diffs = [b - a for a, b in zip(shifted_impacts, base_impacts)]
    assert all(abs(diff + 0.35) < 1e-6 for diff in diffs)


def test_disabled_event_updates_plan(sample_video, sample_gyro, tmp_path):
    project = Project(work_dir=tmp_path / "work2")
    project.load_video(sample_video)
    project.load_gyro(sample_gyro)
    project.run_analysis()
    events = project.visible_events()
    assert events
    project.set_event_enabled(events[0].index, False)
    assert all(e.index != events[0].index for e in project.visible_events())
    # The event remains listed as a candidate so it can be re-enabled.
    assert any(e.index == events[0].index for e in project.candidates())
    project.set_event_enabled(events[0].index, True)
    assert any(e.index == events[0].index for e in project.visible_events())


def test_manual_track_operations():
    project = Project()
    assert len(project.manual_tracks) == 4
    track = project.add_manual_track()
    assert len(project.manual_tracks) == 5
    assert track.key == ""
    project.set_manual_track_enabled(4, False)
    assert project.manual_tracks[4].enabled is False
    project.set_manual_track_sound(4, "marimba")
    assert project.manual_tracks[4].sound == "marimba"

    project.manual_accents = [
        ManualAccent(time=1.0, lane=0),
        ManualAccent(time=2.0, lane=4),
    ]
    assert project.add_manual_accent(3.0, 99) is None
    project.remove_manual_track(0)
    assert len(project.manual_tracks) == 4
    assert [(a.time, a.lane) for a in project.manual_accents] == [(2.0, 3)]

    index = project.move_manual_accent(0, 0.25)
    assert index == 0
    assert project.manual_accents[0].time == pytest.approx(2.25)
    assert project.remove_manual_accent_at(0) is not None
    assert project.manual_accents == []


def test_project_roundtrip(sample_video, sample_gyro, tmp_path):
    project = Project(work_dir=tmp_path / "work3")
    project.load_video(sample_video)
    project.load_gyro(sample_gyro)
    project.offset = -0.35
    project.sensitivity = 0.7
    project.sound = SoundSettings(accent="piano", density=0.4, brightness=0.35, kit="techno")
    project.disabled_events = {2, 5}
    project.manual_accents = [
        ManualAccent(time=1.25, lane=0),
        ManualAccent(time=7.50, lane=2),
    ]
    for track, sound, key in zip(
        project.manual_tracks,
        ("impact", "kick", "marimba", "hat"),
        ("W", "S", "A", "D"),
    ):
        track.sound = sound
        track.key = key
    project.manual_move_step_ms = 120
    project.manual_move_left_key = "Alt+Left"
    project.manual_move_right_key = "Alt+Right"
    path = project.save(tmp_path / "flight.vibeflow")
    assert path.exists()

    restored = Project(work_dir=tmp_path / "work4")
    restored.load(path)
    assert restored.offset == pytest.approx(-0.35)
    assert restored.sensitivity == pytest.approx(0.7)
    assert restored.sound.accent == "piano"
    assert restored.sound.density == pytest.approx(0.4)
    assert restored.sound.kit == "techno"
    assert restored.disabled_events == {2, 5}
    assert [(round(a.time, 2), a.lane) for a in restored.manual_accents] == [
        (1.25, 0),
        (7.50, 2),
    ]
    assert [track.sound for track in restored.manual_tracks[:4]] == [
        "impact",
        "kick",
        "marimba",
        "hat",
    ]
    assert [track.key for track in restored.manual_tracks[:4]] == [
        "W",
        "S",
        "A",
        "D",
    ]
    assert restored.manual_move_step_ms == 120
    assert restored.manual_move_left_key == "Alt+Left"
    assert restored.manual_move_right_key == "Alt+Right"
    assert restored.analysis is not None
