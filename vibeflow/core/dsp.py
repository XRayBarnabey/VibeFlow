"""Small DSP helpers shared by analysis and synthesis."""

from __future__ import annotations

import numpy as np
from scipy import signal


def _sos_lowpass(fs: float, cutoff: float, order: int = 2):
    nyq = fs / 2.0
    cutoff = min(max(cutoff, 0.05), nyq * 0.98)
    return signal.butter(order, cutoff / nyq, btype="low", output="sos")


def lowpass(x: np.ndarray, fs: float, cutoff: float, order: int = 2) -> np.ndarray:
    """Zero-phase low-pass with edge padding (no transient at the borders)."""
    x = np.asarray(x, dtype=np.float64)
    if x.size < 8:
        return x.copy()
    sos = _sos_lowpass(fs, cutoff, order)
    pad = min(x.size - 1, int(fs / max(cutoff, 0.1) * 2))
    if pad > 3:
        padded = np.pad(x, (pad, pad), mode="reflect")
        filtered = signal.sosfiltfilt(sos, padded)
        return filtered[pad:-pad]
    return signal.sosfiltfilt(sos, x)


def highpass(x: np.ndarray, fs: float, cutoff: float, order: int = 2) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 8:
        return x.copy()
    nyq = fs / 2.0
    cutoff = min(max(cutoff, 0.01), nyq * 0.95)
    sos = signal.butter(order, cutoff / nyq, btype="high", output="sos")
    pad = min(x.size - 1, int(fs / max(cutoff, 0.05) * 2))
    if pad > 3:
        return signal.sosfiltfilt(sos, np.pad(x, (pad, pad), mode="reflect"))[pad:-pad]
    return signal.sosfiltfilt(sos, x)


def smooth(x: np.ndarray, fs: float, window_s: float) -> np.ndarray:
    """Centered moving average, edge handled by reflection."""
    n = max(1, int(round(fs * window_s)))
    if n <= 1 or x.size == 0:
        return x.astype(np.float64, copy=True)
    kernel = np.ones(n, dtype=np.float64) / n
    pad = n // 2
    padded = np.pad(np.asarray(x, dtype=np.float64), (pad, pad), mode="reflect")
    return np.convolve(padded, kernel, mode="same")[pad : pad + x.size]


def resample_to(x: np.ndarray, t_src: np.ndarray, t_dst: np.ndarray) -> np.ndarray:
    return np.interp(t_dst, t_src, x)


def normalize(x: np.ndarray, peak: float = 1.0) -> np.ndarray:
    m = float(np.max(np.abs(x))) if x.size else 0.0
    if m <= 1e-12:
        return np.zeros_like(x)
    return x * (peak / m)


def soft_clip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


def onset_envelope(x: np.ndarray, fs: float, hop_s: float = 0.01) -> tuple[np.ndarray, np.ndarray]:
    """Simple spectral-flux-ish onset strength on a mono signal."""
    hop = max(1, int(fs * hop_s))
    n_frames = max(1, x.size // hop)
    trimmed = x[: n_frames * hop].reshape(n_frames, hop)
    energy = np.sqrt(np.mean(trimmed**2, axis=1) + 1e-12)
    flux = np.maximum(0.0, np.diff(energy, prepend=energy[0]))
    times = np.arange(n_frames) * hop_s
    return flux, times
