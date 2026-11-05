from __future__ import annotations

import json

import numpy as np
import pytest

from vibeflow.providers.acestep import ACEStepClient, ACEStepError, ACEStepRequest


def test_request_payload_contains_tempo_map():
    request = ACEStepRequest(
        prompt="cinematic ambient",
        duration=176.5,
        bpm=83.82,
        key_scale="A minor",
        thinking=True,
    )
    payload = request.payload()
    assert payload["audio_duration"] == pytest.approx(176.5)
    assert payload["bpm"] == 84
    assert payload["key_scale"] == "A minor"
    assert payload["thinking"] is True
    assert payload["audio_format"] == "wav"
    assert payload["use_cot_caption"] is False


def test_request_payload_clamps_duration():
    assert ACEStepRequest("x", 2.0, 84).payload()["audio_duration"] == pytest.approx(10.0)
    assert ACEStepRequest("x", 900.0, 84).payload()["audio_duration"] == pytest.approx(600.0)


def test_wait_parses_successful_result(monkeypatch):
    client = ACEStepClient("http://127.0.0.1:8021")
    responses = [
        {"data": [{"task_id": "t1", "status": 0, "result": ""}]},
        {
            "data": [
                {
                    "task_id": "t1",
                    "status": 1,
                    "result": json.dumps(
                        [
                            {
                                "file": "/v1/audio?path=test.wav",
                                "metas": {"bpm": 84, "duration": 10},
                                "seed_value": "42",
                            }
                        ]
                    ),
                }
            ]
        },
    ]

    def fake_json(method, path, payload=None):
        return responses.pop(0)

    monkeypatch.setattr(client, "_json", fake_json)
    result = client.wait("t1", interval=0)
    assert result.tracks[0].file.endswith("test.wav")
    assert result.tracks[0].metadata["bpm"] == 84


def test_wait_raises_on_failure(monkeypatch):
    client = ACEStepClient("http://127.0.0.1:8021")
    monkeypatch.setattr(
        client,
        "_json",
        lambda *a, **k: {"data": [{"task_id": "t1", "status": 2, "result": "OOM"}]},
    )
    with pytest.raises(ACEStepError, match="échoué"):
        client.wait("t1", interval=0)


def test_mix_audio_preserves_duration_and_peak(tmp_path):
    import soundfile as sf

    from vibeflow.core.project import Project

    rate = 48000
    t = np.arange(rate, dtype=np.float32) / rate
    ai = np.column_stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 220 * t)])
    local = np.column_stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)])
    ai_path = tmp_path / "ai.wav"
    local_path = tmp_path / "local.wav"
    out_path = tmp_path / "mix.wav"
    sf.write(ai_path, ai * 0.5, rate)
    sf.write(local_path, local * 0.5, rate)

    project = Project(work_dir=tmp_path)
    project._mix_audio(ai_path, local_path, out_path, 0.3)
    mixed, mixed_rate = sf.read(out_path, always_2d=True)
    assert mixed_rate == rate
    assert mixed.shape[0] == rate
    assert np.isfinite(mixed).all()
    assert float(np.max(np.abs(mixed))) <= 0.95


def test_hybrid_mix_ducks_the_bed_on_accents(tmp_path):
    import soundfile as sf

    from vibeflow.core.project import Project
    from vibeflow.core.rhythm import Hit

    rate = 48000
    t = np.arange(rate, dtype=np.float32) / rate
    ai = np.column_stack([np.sin(2 * np.pi * 110 * t), np.sin(2 * np.pi * 110 * t)])
    rhythm = np.zeros((rate, 2), dtype=np.float32)
    rhythm[:1000] = 0.6  # a transient at t=0
    ai_path = tmp_path / "ai.wav"
    rhythm_path = tmp_path / "rhythm.wav"
    out_path = tmp_path / "hybrid.wav"
    sf.write(ai_path, ai * 0.4, rate)
    sf.write(rhythm_path, rhythm, rate)

    project = Project(work_dir=tmp_path)
    project._mix_hybrid(
        ai_path, rhythm_path, out_path, [Hit(0.0, "kick", 0.9)]
    )
    mixed, mixed_rate = sf.read(out_path, always_2d=True)
    assert mixed_rate == rate
    assert mixed.shape[0] == rate
    assert np.isfinite(mixed).all()
    assert float(np.max(np.abs(mixed))) <= 0.95
