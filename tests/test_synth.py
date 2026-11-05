from __future__ import annotations

import numpy as np

from vibeflow.core.rhythm import Hit, RhythmPlan, Section
from vibeflow.core.synth import SAMPLE_RATE, render_plan, write_wav


def make_plan(duration=6.0):
    hits = []
    for i in range(int(duration / 0.5)):
        t = i * 0.5
        hits.append(Hit(t, "kick", 0.9))
        if i % 2 == 0:
            hits.append(Hit(t, "clap", 0.6))
        hits.append(Hit(t + 0.25, "hat", 0.35, pan=0.2))
        hits.append(Hit(t, "sub", 0.5, note=33, duration=0.4))
    hits.append(Hit(2.0, "impact", 0.9))
    hits.append(Hit(3.0, "crash", 0.4))
    hits.append(Hit(4.0, "riser", 0.4, duration=0.5))
    hits.append(Hit(1.0, "pad", 0.25, note=57, duration=2.0))
    return RhythmPlan(
        bpm=120,
        beat_offset=0.0,
        duration=duration,
        sections=[Section(0, duration, 0.6, "groove")],
        hits=hits,
    )


def test_render_shape_and_levels(tmp_path):
    plan = make_plan()
    audio = render_plan(plan)
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert audio.shape[0] >= int(plan.duration * SAMPLE_RATE)
    assert np.isfinite(audio).all()
    assert np.max(np.abs(audio)) <= 1.0
    assert np.max(np.abs(audio)) > 0.05

    path = write_wav(tmp_path / "out.wav", audio)
    import soundfile as sf

    data, rate = sf.read(str(path))
    assert rate == SAMPLE_RATE
    assert data.shape == audio.shape


def test_render_is_deterministic():
    plan = make_plan(2.0)
    first = render_plan(plan)
    second = render_plan(plan)
    assert np.array_equal(first, second)


def test_drum_kit_changes_the_render():
    from dataclasses import replace

    from vibeflow.core.rhythm import SoundSettings

    plan = make_plan(4.0)
    analog = render_plan(replace(plan, sound=SoundSettings(kit="analog")))
    techno = render_plan(replace(plan, sound=SoundSettings(kit="techno")))
    acoustic = render_plan(replace(plan, sound=SoundSettings(kit="acoustic")))
    assert not np.array_equal(analog, techno)
    assert not np.array_equal(analog, acoustic)


def test_new_accent_timbres_render():
    for instrument in ("marimba", "strings", "synth"):
        hits = [
            Hit(i * 0.35, instrument, 0.55, note=60 + i, duration=1.2)
            for i in range(4)
        ]
        plan = RhythmPlan(
            bpm=110,
            beat_offset=0.0,
            duration=2.0,
            sections=[Section(0, 2.0, 0.6, "groove")],
            hits=hits,
        )
        audio = render_plan(plan)
        assert audio.shape[1] == 2
        assert np.isfinite(audio).all(), instrument
        peak = float(np.max(np.abs(audio)))
        assert 0.01 < peak <= 1.0, instrument


def test_completion_melody_is_audible_and_bounded():
    from vibeflow.core.synth import completion_melody

    audio = completion_melody()
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert np.isfinite(audio).all()
    peak = float(np.max(np.abs(audio)))
    assert 0.05 < peak <= 0.85


def test_ambient_guitar_render_does_not_clip():
    from vibeflow.core.rhythm import SoundSettings

    hits = [
        Hit(i * 4.0 + j * 0.02, "guitar", 0.85, note=note, duration=2.8)
        for i in range(3)
        for j, note in enumerate((57, 60, 64, 67))
    ]
    hits += [Hit(i * 4.0, "boom", 0.8) for i in range(3)]
    hits += [Hit(i * 4.0, "pad_warm", 0.5, note=57, duration=4.0) for i in range(3)]
    plan = RhythmPlan(
        bpm=84,
        beat_offset=0.0,
        duration=10.0,
        sections=[Section(0, 10, 0.6, "groove")],
        hits=hits,
        style="evasion",
        sound=SoundSettings(),
    )
    audio = render_plan(plan)
    assert np.isfinite(audio).all()
    assert float(np.max(np.abs(audio))) <= 0.95
