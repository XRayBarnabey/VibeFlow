"""Percussion sound design for the Pulse style.

Four kits, synthesised from scratch, with clearly different character:
    analog   : deep 808 kick, hand clap, metallic hats
    techno   : punchy 909 kick, tight snare/clap, crisp hats
    acoustic : beater kick, snare body, natural hats
    lofi     : dark filtered drums, saturated
"""

from __future__ import annotations

import numpy as np
from scipy import signal

SAMPLE_RATE = 48000

KIT_LABELS = {
    "analog": "Analog 808",
    "techno": "Techno 909",
    "acoustic": "Acoustique",
    "lofi": "Lo-fi",
    "trap": "Trap 808",
    "organic": "Organique",
    "industrial": "Industriel",
}


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _env(n: int, decay: float, attack: float = 0.0015) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    return ((1.0 - np.exp(-t / max(attack, 1e-5))) * np.exp(-t * decay)).astype(np.float32)


def _filter(x: np.ndarray, kind: str, freq, order: int = 2) -> np.ndarray:
    nyq = SAMPLE_RATE / 2.0
    if isinstance(freq, (tuple, list)):
        freqs = [min(max(f / nyq, 0.001), 0.995) for f in freq]
        sos = signal.butter(order, freqs, kind, output="sos")
    else:
        sos = signal.butter(order, min(max(freq / nyq, 0.001), 0.995), kind, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def render_kick(kit: str = "analog") -> np.ndarray:
    if kit == "techno":
        length, f0, f1, decay, click, drive, lowpass = 0.55, 70.0, 44.0, 8.5, 0.12, 2.2, 6500
    elif kit == "acoustic":
        length, f0, f1, decay, click, drive, lowpass = 0.65, 82.0, 50.0, 9.0, 0.24, 1.5, 5200
    elif kit == "lofi":
        length, f0, f1, decay, click, drive, lowpass = 1.0, 50.0, 34.0, 4.4, 0.03, 2.5, 2100
    elif kit == "trap":
        length, f0, f1, decay, click, drive, lowpass = 1.45, 46.0, 30.0, 3.0, 0.05, 2.8, 3000
    elif kit == "organic":
        length, f0, f1, decay, click, drive, lowpass = 0.62, 76.0, 48.0, 10.0, 0.18, 1.3, 4600
    elif kit == "industrial":
        length, f0, f1, decay, click, drive, lowpass = 0.52, 92.0, 50.0, 10.0, 0.20, 3.0, 7200
    else:
        length, f0, f1, decay, click, drive, lowpass = 1.15, 54.0, 35.0, 3.8, 0.02, 1.3, 3800

    n = int(length * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = f1 + (f0 - f1) * np.exp(-t * 24.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * _env(n, decay, attack=0.003)
    if kit in {"acoustic", "organic"}:
        body += 0.30 * np.sin(2 * np.pi * 155.0 * t) * _env(n, 20.0, attack=0.002)

    transient = _noise(n, 43) * _env(n, 220.0, attack=0.0008) * click
    transient = _filter(transient, "high", 1400.0)
    kick = np.tanh((body + transient) * drive) / np.tanh(drive)
    if kit in {"acoustic", "organic"}:
        beater = _noise(n, 44) * _env(n, 120.0, attack=0.0005) * 0.10
        kick += _filter(beater, "band", (900.0, 4200.0))
    if kit == "industrial":
        metal = _filter(_noise(n, 45), "band", (1800.0, 7000.0)) * _env(n, 30.0) * 0.12
        kick += metal
    kick = _filter(kick, "low", lowpass)
    return kick.astype(np.float32)


def render_clap(kit: str = "analog") -> np.ndarray:
    if kit == "techno":
        bursts, burst_decay, band, tail, snare = (0.0, 0.008, 0.016), 70.0, (1400.0, 5200.0), 20.0, 0.10
    elif kit == "acoustic":
        bursts, burst_decay, band, tail, snare = (0.0, 0.006, 0.013), 55.0, (700.0, 5200.0), 13.0, 0.45
    elif kit == "lofi":
        bursts, burst_decay, band, tail, snare = (0.0, 0.014, 0.030), 38.0, (600.0, 3000.0), 8.0, 0.15
    elif kit == "trap":
        bursts, burst_decay, band, tail, snare = (0.0, 0.007, 0.014), 95.0, (1600.0, 6200.0), 26.0, 0.0
    elif kit == "organic":
        bursts, burst_decay, band, tail, snare = (0.0, 0.008, 0.018), 48.0, (650.0, 4300.0), 12.0, 0.55
    elif kit == "industrial":
        bursts, burst_decay, band, tail, snare = (0.0, 0.005, 0.011, 0.020), 90.0, (1800.0, 7000.0), 24.0, 0.0
    else:
        bursts, burst_decay, band, tail, snare = (0.0, 0.011, 0.023), 50.0, (900.0, 3600.0), 11.0, 0.0

    length = 0.6 if kit in {"acoustic", "organic"} else 0.4
    n = int(length * SAMPLE_RATE)
    noise = _filter(_noise(n, 51), "band", band) * 0.9
    out = np.zeros(n, dtype=np.float32)
    for i, offset in enumerate(bursts):
        start = int(offset * SAMPLE_RATE)
        decay = burst_decay if i < len(bursts) - 1 else tail
        segment = _env(n - start, decay, attack=0.0006)
        out[start:] += noise[start:] * segment
    if snare:
        t = np.arange(n) / SAMPLE_RATE
        body = np.sin(2 * np.pi * 185.0 * t) * _env(n, 22.0, attack=0.002) * snare
        out += body
    if kit in {"techno", "trap", "industrial"}:
        out = np.tanh(out * 1.8) * 0.7
    if kit == "lofi":
        out = _filter(out, "low", 3200.0)
    return (out * 0.65).astype(np.float32)


def render_hat(kit: str = "analog", open_hat: bool = False) -> np.ndarray:
    if kit == "techno":
        length = 0.35 if open_hat else 0.07
        decay = 11.0 if open_hat else 70.0
        cutoff = 9000.0
        metallic = 0.0
    elif kit == "acoustic":
        length = 0.45 if open_hat else 0.09
        decay = 9.0 if open_hat else 45.0
        cutoff = 6500.0
        metallic = 0.25
    elif kit == "lofi":
        length = 0.30 if open_hat else 0.09
        decay = 10.0 if open_hat else 38.0
        cutoff = 6000.0
        metallic = 0.0
    elif kit == "trap":
        length = 0.20 if open_hat else 0.055
        decay = 18.0 if open_hat else 95.0
        cutoff = 10000.0
        metallic = 0.0
    elif kit == "organic":
        length = 0.34 if open_hat else 0.10
        decay = 10.0 if open_hat else 35.0
        cutoff = 6200.0
        metallic = 0.35
    elif kit == "industrial":
        length = 0.38 if open_hat else 0.08
        decay = 12.0 if open_hat else 40.0
        cutoff = 7800.0
        metallic = 0.9
    else:
        length = 0.42 if open_hat else 0.08
        decay = 10.0 if open_hat else 55.0
        cutoff = 7600.0
        metallic = 0.85

    n = int(length * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    noise = _noise(n, 73)
    source = _filter(noise, "high", cutoff) * (1.0 - metallic)
    if metallic > 0:
        metal = np.zeros(n, dtype=np.float32)
        for ratio in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
            metal += np.sign(np.sin(2 * np.pi * ratio * t))
        metal = _filter(metal / 6.0, "high", 7000.0)
        source += metal * metallic
    env = _env(n, decay, attack=0.0004)
    hat = source * env
    if kit == "lofi":
        hat = _filter(hat, "low", 8000.0)
    return (hat * 0.5).astype(np.float32)


def render_impact(kit: str = "analog") -> np.ndarray:
    if kit == "techno":
        length, f0, f1, decay, drive = 1.0, 95.0, 42.0, 4.5, 2.0
    elif kit == "acoustic":
        length, f0, f1, decay, drive = 1.3, 120.0, 55.0, 3.5, 1.4
    elif kit == "lofi":
        length, f0, f1, decay, drive = 2.2, 55.0, 28.0, 2.2, 2.0
    elif kit == "trap":
        length, f0, f1, decay, drive = 1.8, 60.0, 30.0, 2.6, 2.4
    elif kit == "organic":
        length, f0, f1, decay, drive = 1.4, 110.0, 50.0, 3.4, 1.3
    elif kit == "industrial":
        length, f0, f1, decay, drive = 0.9, 105.0, 40.0, 5.0, 3.0
    else:
        length, f0, f1, decay, drive = 1.6, 70.0, 27.0, 2.6, 1.2

    n = int(length * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = f1 + (f0 - f1) * np.exp(-t * 7.0)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * _env(n, decay, attack=0.004)
    noise = _filter(_noise(n, 61), "band", (180.0, 2400.0)) * _env(n, 10.0, attack=0.002) * 0.25
    impact = np.tanh((body + noise) * drive) / np.tanh(drive)
    if kit == "lofi":
        impact = _filter(impact, "low", 1800.0)
    return impact.astype(np.float32)
