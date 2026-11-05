from __future__ import annotations

import numpy as np

from vibeflow.core.sync import estimate_offset_from_signals


def _burst_signal(t: np.ndarray, centers: list[float], width: float = 0.25) -> np.ndarray:
    signal = np.zeros_like(t)
    for center in centers:
        signal += np.exp(-0.5 * ((t - center) / width) ** 2)
    return signal


def test_recovers_known_offset():
    fs = 200.0
    gyro_t = np.arange(0, 60, 1 / fs)
    gyro_speed = _burst_signal(gyro_t, [8.0, 14.5, 21.0, 33.0, 41.0, 52.0])
    video_t = np.arange(0, 60, 0.1)
    true_offset = 1.7
    video_energy = np.interp(video_t - true_offset, gyro_t, gyro_speed)
    estimate = estimate_offset_from_signals(
        gyro_t, gyro_speed, video_t, video_energy, max_offset=5.0, fps=10.0
    )
    assert abs(estimate.offset - true_offset) < 0.15
    assert estimate.confidence > 0.3
    assert estimate.is_reliable


def test_zero_offset():
    fs = 100.0
    gyro_t = np.arange(0, 30, 1 / fs)
    gyro_speed = _burst_signal(gyro_t, [3.0, 9.0, 15.0, 22.0])
    video_t = np.arange(0, 30, 0.1)
    video_energy = np.interp(video_t, gyro_t, gyro_speed)
    estimate = estimate_offset_from_signals(
        gyro_t, gyro_speed, video_t, video_energy, max_offset=3.0
    )
    assert abs(estimate.offset) < 0.15


def test_insufficient_data_is_safe():
    estimate = estimate_offset_from_signals(
        np.arange(3), np.arange(3), np.arange(3), np.arange(3)
    )
    assert estimate.offset == 0.0
    assert not estimate.is_reliable
