from __future__ import annotations

from pathlib import Path

from vibeflow.core.project import Project


def test_switch_between_music_sources(tmp_path):
    project = Project(work_dir=tmp_path)
    previews = {}
    for source in ("local", "ai", "hybrid"):
        audio = tmp_path / f"{source}.wav"
        audio.write_bytes(b"audio")
        preview = tmp_path / f"preview_{source}.mp4"
        preview.write_bytes(b"preview")
        project.source_paths[source] = audio
        project.source_previews[source] = preview
        previews[source] = preview

    assert project.set_music_source("ai") == previews["ai"]
    assert project.music_source == "ai"
    assert project.active_audio_path() == tmp_path / "ai.wav"

    assert project.set_music_source("hybrid") == previews["hybrid"]
    assert project.active_audio_path() == tmp_path / "hybrid.wav"

    assert project.set_music_source("missing") is None
    assert project.music_source == "hybrid"
