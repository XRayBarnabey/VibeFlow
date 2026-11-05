from __future__ import annotations

import numpy as np
import pytest

from vibeflow.core.gyro import load_gyro


def make_gcsv(
    rates_deg: np.ndarray,
    fs: float = 1000.0,
    tscale: float = 0.001,
    gscale: float | None = None,
    extra_meta: dict[str, str] | None = None,
) -> str:
    """Build a valid GCSV string; rates are given in deg/s."""
    if gscale is None:
        gscale = np.radians(1.0) / 0.001  # 1 raw unit = 1 deg/s
    header = ["GYROFLOW IMU LOG", "version,1.3", "id,vibeflow_test", "orientation,YxZ"]
    for key, value in (extra_meta or {}).items():
        header.append(f"{key},{value}")
    header.append(f"tscale,{tscale}")
    header.append(f"gscale,{gscale:.10f}")
    header.append("t,gx,gy,gz")
    lines = list(header)
    for i, (gx, gy, gz) in enumerate(rates_deg):
        raw = np.radians([gx, gy, gz]) / gscale
        lines.append(f"{i},{raw[0]:.4f},{raw[1]:.4f},{raw[2]:.4f}")
    return "\n".join(lines) + "\n"


def flight_rates(duration: float = 40.0, fs: float = 1000.0) -> np.ndarray:
    n = int(duration * fs)
    t = np.arange(n) / fs
    rates = np.zeros((n, 3))
    # 360° roll in 0.7 s.
    _add_rotation(rates, t, start=10.0, duration_s=0.7, axis=0, angle_deg=360.0)
    # Small pilot correction (36°) that must not be a headline event.
    _add_rotation(rates, t, start=20.0, duration_s=0.3, axis=1, angle_deg=36.0)
    # 180° inversion at 30 s.
    _add_rotation(rates, t, start=30.0, duration_s=0.5, axis=0, angle_deg=180.0)
    return rates


def _add_rotation(rates, t, start, duration_s, axis, angle_deg):
    mask = (t >= start) & (t < start + duration_s)
    local = t[mask] - start
    peak = angle_deg * np.pi / (2 * duration_s)
    rates[mask, axis] += peak * np.sin(np.pi * local / duration_s)


@pytest.fixture
def gcsv_path(tmp_path):
    path = tmp_path / "flight.gcsv"
    path.write_text(make_gcsv(flight_rates()), encoding="utf-8")
    return path


def test_gcsv_sample_rate_from_timestamps(gcsv_path):
    track = load_gyro(gcsv_path)
    assert track.source == gcsv_path
    assert 399 < track.sample_rate <= 400
    assert abs(track.duration - 40.0) < 0.01
    assert track.unit == "rad/s"
    assert not track.warnings


def test_gcsv_preserves_rotation_amplitude(gcsv_path):
    track = load_gyro(gcsv_path)
    roll = np.degrees(track.rates[:, 0])
    assert roll.max() == pytest.approx(360 * np.pi / (2 * 0.7), rel=0.03)


def test_irregular_timestamps_are_reported(tmp_path):
    rates = flight_rates(duration=5.0, fs=200.0)
    text = make_gcsv(rates, fs=200.0, tscale=0.005)
    path = tmp_path / "irregular.gcsv"
    # Drop a chunk to create a logging gap.
    lines = text.splitlines()
    text = "\n".join(lines[:300] + lines[600:])
    path.write_text(text, encoding="utf-8")
    track = load_gyro(path)
    assert track.gap_count >= 1
    assert any("interruption" in w for w in track.warnings)


def test_generic_csv_degrees_per_second(tmp_path):
    path = tmp_path / "generic.csv"
    fs = 500.0
    n = 5000
    rows = ["time,gyro_x,gyro_y,gyro_z"]
    for i in range(n):
        value = 120.0 if 1000 < i < 1200 else 0.0
        rows.append(f"{i / fs:.6f},{value},0,0")
    path.write_text("\n".join(rows), encoding="utf-8")
    track = load_gyro(path)
    assert track.unit == "rad/s"
    assert np.degrees(np.max(track.rates[:, 0])) == pytest.approx(120.0, rel=0.02)


def test_generic_csv_millisecond_timestamps(tmp_path):
    path = tmp_path / "ms.csv"
    rows = ["t,gx,gy,gz"]
    for i in range(2000):
        rows.append(f"{i * 2},10,0,0")  # 500 Hz expressed in ms
    path.write_text("\n".join(rows), encoding="utf-8")
    track = load_gyro(path)
    assert track.duration == pytest.approx(3.998, abs=0.01)
    assert 490 < track.raw_rate_hz < 510


def test_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("hello\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gyro(path)
