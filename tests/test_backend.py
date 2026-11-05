from __future__ import annotations

from pathlib import Path

from vibeflow.backend.acestep_backend import ACEStepBackend


def test_detects_managed_installation(tmp_path):
    backend = ACEStepBackend(root=tmp_path)
    assert not backend.managed_installed
    install = tmp_path / "ACE-Step-1.5"
    (install / "python_embeded").mkdir(parents=True)
    (install / "python_embeded" / "python.exe").write_text("")
    (install / "acestep").mkdir()
    (install / "acestep" / "api_server.py").write_text("")
    assert backend.managed_installed
    assert backend.detect() == install


def test_writes_safe_default_config(tmp_path):
    backend = ACEStepBackend(root=tmp_path)
    install = backend.install_dir
    install.mkdir(parents=True)
    backend._write_config()
    content = (install / ".env").read_text(encoding="utf-8")
    assert "ACESTEP_CONFIG_PATH=acestep-v15-turbo" in content
    assert "ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B" in content
    assert "ACESTEP_LM_BACKEND=pt" in content


def test_health_is_false_when_no_server(tmp_path):
    backend = ACEStepBackend(root=tmp_path)
    backend.port = 59999
    assert backend.health(timeout=0.2) is False
