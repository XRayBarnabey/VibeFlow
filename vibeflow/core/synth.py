"""Synthesis engine for the VibeFlow rhythmic pre-listen.

Every instrument is synthesised from scratch with NumPy: no sample pack, no
external dependency, deterministic output. The result is a 48 kHz stereo WAV
that is muxed with the video for perfectly synchronised playback.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

import numpy as np
from scipy import signal

from .rhythm import Hit, RhythmPlan, SoundSettings
from . import drums

SAMPLE_RATE = 48000

# Reverb send level per instrument (0 = dry).
REVERB_SEND = {
    "kick": 0.03,
    "sub": 0.0,
    "hat": 0.10,
    "openhat": 0.18,
    "clap": 0.28,
    "impact": 0.38,
    "crash": 0.32,
    "riser": 0.25,
    "stab": 0.22,
    "pad": 0.30,
    "softkick": 0.02,
    "boom": 0.30,
    "bell": 0.46,
    "arp": 0.34,
    "tick": 0.08,
    "shimmer": 0.50,
    "swell": 0.26,
    "drone": 0.05,
    "pad_warm": 0.34,
}


def midi_to_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def _env_exp(n: int, decay: float, attack: float = 0.0015) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    attack_curve = 1.0 - np.exp(-t / max(attack, 1e-5))
    return (attack_curve * np.exp(-t * decay)).astype(np.float32)


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _kick() -> np.ndarray:
    n = int(0.55 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 46.0 + 150.0 * np.exp(-t * 34.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * _env_exp(n, 7.0)
    click = np.random.default_rng(1).standard_normal(n) * _env_exp(n, 380.0) * 0.12
    click = signal.sosfilt(signal.butter(2, 1200 / (SAMPLE_RATE / 2), "high", output="sos"), click)
    return (body + click).astype(np.float32)


def _impact() -> np.ndarray:
    n = int(1.6 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 27.0 + 72.0 * np.exp(-t * 9.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * _env_exp(n, 2.6, attack=0.004)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    noise = signal.sosfilt(
        signal.butter(2, [180 / (SAMPLE_RATE / 2), 2400 / (SAMPLE_RATE / 2)], "band", output="sos"),
        noise,
    )
    noise *= _env_exp(n, 9.0, attack=0.002) * 0.35
    return (body + noise).astype(np.float32)


def _sub(note: float, duration: float) -> np.ndarray:
    freq = midi_to_hz(note)
    n = max(int(duration * SAMPLE_RATE), int(0.08 * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    attack = np.clip(t / 0.012, 0.0, 1.0)
    release = np.clip((duration - t) / 0.06, 0.0, 1.0)
    env = attack * release * (0.75 + 0.25 * np.exp(-t * 3.0))
    phase = 2 * np.pi * freq * t
    wave = np.sin(phase) + 0.22 * np.sin(2 * phase) + 0.08 * np.sin(3 * phase)
    return (wave * env).astype(np.float32)


def _hat(open_hat: bool = False) -> np.ndarray:
    duration = 0.45 if open_hat else 0.085
    n = int(duration * SAMPLE_RATE)
    rng = np.random.default_rng(11 if open_hat else 3)
    noise = rng.standard_normal(n)
    noise = signal.sosfilt(
        signal.butter(2, 6800 / (SAMPLE_RATE / 2), "high", output="sos"), noise
    )
    env = _env_exp(n, 11.0 if open_hat else 52.0, attack=0.0008)
    return (noise * env * 0.55).astype(np.float32)


def _clap() -> np.ndarray:
    n = int(0.4 * SAMPLE_RATE)
    rng = np.random.default_rng(5)
    noise = rng.standard_normal(n)
    noise = signal.sosfilt(
        signal.butter(2, [900 / (SAMPLE_RATE / 2), 4200 / (SAMPLE_RATE / 2)], "band", output="sos"),
        noise,
    )
    body = np.zeros(n, dtype=np.float32)
    for i, (offset, gain) in enumerate(((0.0, 1.0), (0.011, 0.7), (0.023, 0.5))):
        start = int(offset * SAMPLE_RATE)
        seg = _env_exp(n - start, 55.0 if i < 2 else 16.0, attack=0.0005)
        body[start:] += noise[start:] * seg * gain
    return (body * 0.7).astype(np.float32)


def _crash() -> np.ndarray:
    n = int(1.8 * SAMPLE_RATE)
    rng = np.random.default_rng(13)
    noise = rng.standard_normal(n)
    noise = signal.sosfilt(
        signal.butter(2, 3500 / (SAMPLE_RATE / 2), "high", output="sos"), noise
    )
    env = _env_exp(n, 3.2, attack=0.003)
    return (noise * env * 0.5).astype(np.float32)


def _riser(duration: float) -> np.ndarray:
    n = max(int(duration * SAMPLE_RATE), 64)
    rng = np.random.default_rng(17)
    noise = rng.standard_normal(n)
    t = np.arange(n) / n
    cutoff = 400 + 9000 * t**2
    # Time-varying filter approximated in 16 blocks.
    out = np.zeros(n, dtype=np.float32)
    blocks = 16
    size = n // blocks
    for i in range(blocks):
        lo = i * size
        hi = n if i == blocks - 1 else (i + 1) * size
        fc = cutoff[min(lo, n - 1)] / (SAMPLE_RATE / 2)
        sos = signal.butter(2, [max(0.001, fc * 0.6), min(0.99, fc * 1.6)], "band", output="sos")
        out[lo:hi] = signal.sosfilt(sos, noise[lo:hi])
    ramp = np.linspace(0.0, 1.0, n) ** 2
    release = np.clip((n - np.arange(n)) / (0.05 * SAMPLE_RATE), 0.0, 1.0)
    return (out * ramp * release * 0.4).astype(np.float32)


def _stab(notes: tuple[float, ...], duration: float = 0.35) -> np.ndarray:
    n = int(duration * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    wave = np.zeros(n, dtype=np.float32)
    for note in notes:
        freq = midi_to_hz(note)
        wave += np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)
    env = _env_exp(n, 9.0, attack=0.004)
    return (wave / max(len(notes), 1) * env * 0.5).astype(np.float32)


def _pad(note: float, duration: float) -> np.ndarray:
    n = max(int(duration * SAMPLE_RATE), int(0.2 * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    attack = np.clip(t / 0.35, 0.0, 1.0)
    release = np.clip((duration - t) / 0.5, 0.0, 1.0)
    env = attack * release
    detune = 1.0 + 0.0025
    wave = (
        np.sin(2 * np.pi * freq * t)
        + np.sin(2 * np.pi * freq * detune * t + 0.6)
        + 0.3 * np.sin(2 * np.pi * freq * 2 * t)
    )
    lfo = 0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t)
    wave = signal.sosfilt(signal.butter(2, 2200 / (SAMPLE_RATE / 2), "low", output="sos"), wave)
    return (wave * env * lfo * 0.28).astype(np.float32)


def _soft_kick() -> np.ndarray:
    n = int(0.9 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 42.0 + 58.0 * np.exp(-t * 18.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * _env_exp(n, 4.6, attack=0.004)
    thump = np.sin(2 * np.pi * 31.0 * t) * _env_exp(n, 2.8, attack=0.006) * 0.28
    return (body + thump).astype(np.float32)


def _boom() -> np.ndarray:
    n = int(3.0 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 29.0 + 30.0 * np.exp(-t * 3.2)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    body = np.sin(phase) * _env_exp(n, 1.5, attack=0.012)
    sub = np.sin(2 * np.pi * 23.0 * t) * _env_exp(n, 0.9, attack=0.02) * 0.35
    rng = np.random.default_rng(23)
    noise = signal.sosfilt(
        signal.butter(2, 260 / (SAMPLE_RATE / 2), "low", output="sos"),
        rng.standard_normal(n),
    )
    noise *= _env_exp(n, 6.0, attack=0.004) * 0.10
    return (body + sub + noise).astype(np.float32)


def _bell(note: float, duration: float = 1.6) -> np.ndarray:
    length = float(np.clip(duration * 1.4, 0.6, 3.4))
    n = int(length * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    env = _env_exp(n, 1.9, attack=0.0015)
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.48 * np.sin(2 * np.pi * freq * 2.01 * t)
        + 0.26 * np.sin(2 * np.pi * freq * 3.02 * t)
        + 0.14 * np.sin(2 * np.pi * freq * 5.4 * t)
        + 0.07 * np.sin(2 * np.pi * freq * 7.1 * t)
    )
    wave = signal.sosfilt(
        signal.butter(2, 6800 / (SAMPLE_RATE / 2), "low", output="sos"), wave
    )
    return (wave * env * 0.45).astype(np.float32)


def _arp(note: float, duration: float = 0.6) -> np.ndarray:
    length = float(np.clip(duration, 0.25, 1.4))
    n = int(length * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    env = _env_exp(n, 6.5, attack=0.002)
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.35 * np.sin(2 * np.pi * freq * 2.0 * t)
        + 0.18 * np.sin(2 * np.pi * freq * 3.0 * t)
        + 0.10 * np.sin(2 * np.pi * freq * 4.0 * t)
        + 0.06 * np.sin(2 * np.pi * freq * 5.0 * t)
    )
    return (wave * env * 0.55).astype(np.float32)


def _tick() -> np.ndarray:
    n = int(0.11 * SAMPLE_RATE)
    rng = np.random.default_rng(31)
    noise = rng.standard_normal(n)
    noise = signal.sosfilt(
        signal.butter(2, 2600 / (SAMPLE_RATE / 2), "high", output="sos"), noise
    )
    return (noise * _env_exp(n, 95.0, attack=0.0005) * 0.45).astype(np.float32)


def _shimmer() -> np.ndarray:
    n = int(3.6 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    attack = np.clip(t / 0.9, 0.0, 1.0)
    env = attack * np.exp(-t * 1.1)
    wave = np.zeros(n, dtype=np.float32)
    for freq, gain in ((880.0, 1.0), (1046.5, 0.7), (1318.5, 0.55), (1760.0, 0.3)):
        wave += np.sin(2 * np.pi * freq * t + freq * 0.001) * gain
    return (wave * env * 0.10).astype(np.float32)


def _swell(duration: float) -> np.ndarray:
    return _riser(max(0.3, duration))


def _drone(note: float, duration: float) -> np.ndarray:
    n = max(int(duration * SAMPLE_RATE), int(0.5 * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    attack = np.clip(t / 1.6, 0.0, 1.0)
    release = np.clip((duration - t) / 2.2, 0.0, 1.0)
    env = attack * release
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.18 * np.sin(2 * np.pi * freq * 2.0 * t + 0.3)
        + 0.10 * np.sin(2 * np.pi * freq * 0.5 * t)
    )
    wave = signal.sosfilt(
        signal.butter(2, 320 / (SAMPLE_RATE / 2), "low", output="sos"), wave
    )
    return (wave * env * 0.5).astype(np.float32)


def _pad_warm(note: float, duration: float) -> np.ndarray:
    n = max(int(duration * SAMPLE_RATE), int(0.4 * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    attack = np.clip(t / 1.4, 0.0, 1.0)
    release = np.clip((duration - t) / 2.0, 0.0, 1.0)
    env = attack * release
    wave = (
        np.sin(2 * np.pi * freq * t)
        + np.sin(2 * np.pi * freq * 1.0035 * t + 0.7)
        + np.sin(2 * np.pi * freq * 0.9975 * t + 1.4)
        + 0.25 * np.sin(2 * np.pi * freq * 2.0 * t)
    )
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.11 * t)
    wave = signal.sosfilt(
        signal.butter(2, 1900 / (SAMPLE_RATE / 2), "low", output="sos"), wave
    )
    return (wave * env * lfo * 0.16).astype(np.float32)


def _pingpong_delay(x: np.ndarray, delay_s: float = 0.52, feedback: float = 0.34, taps: int = 5) -> np.ndarray:
    """Cheap stereo echo with alternating channels (no IIR cost)."""
    out = x.copy()
    delay = int(delay_s * SAMPLE_RATE)
    if delay <= 0:
        return out
    n = x.shape[0]
    for tap in range(1, taps + 1):
        shift = tap * delay
        if shift >= n:
            break
        gain = feedback ** tap
        if tap % 2:
            out[shift:, 0] += x[: n - shift, 1] * gain
            out[shift:, 1] += x[: n - shift, 0] * gain
        else:
            out[shift:, 0] += x[: n - shift, 0] * gain
            out[shift:, 1] += x[: n - shift, 1] * gain
    return out


def _guitar(note: float, duration: float = 2.6, brightness: float = 0.6) -> np.ndarray:
    """Karplus-Strong style plucked string, generated in fast blocks."""
    freq = midi_to_hz(note)
    period = max(2, int(round(SAMPLE_RATE / freq)))
    length = float(np.clip(duration * 1.4, 0.5, 4.5))
    n = int(length * SAMPLE_RATE)
    rng = np.random.default_rng(int(round(note * 97)) + 17)
    base = rng.standard_normal(period).astype(np.float32)
    cutoff = float(np.clip(900.0 + 5200.0 * brightness, 700.0, SAMPLE_RATE * 0.45))
    sos = signal.butter(2, cutoff / (SAMPLE_RATE / 2), "low", output="sos")
    base = signal.sosfilt(sos, base).astype(np.float32)
    # Anchor the pitch with a quiet sinusoidal component.
    grid = np.arange(period) / SAMPLE_RATE
    base += 0.55 * np.sin(2 * np.pi * freq * grid)
    peak = float(np.max(np.abs(base))) or 1.0
    base /= peak
    decay_per_period = 10 ** (-3.0 / max(freq * length, 1.0))
    out = np.zeros(n, dtype=np.float32)
    position = 0
    gain = 1.0
    buffer = base.copy()
    while position < n:
        size = min(period, n - position)
        out[position : position + size] += buffer[:size] * gain
        buffer = 0.5 * (buffer + np.roll(buffer, 1))
        gain *= decay_per_period
        position += period
    # Plectrum transient.
    pick_n = int(0.009 * SAMPLE_RATE)
    pick = rng.standard_normal(pick_n).astype(np.float32) * np.exp(
        -np.arange(pick_n) / (0.0022 * SAMPLE_RATE)
    )
    out[:pick_n] += pick * 0.12
    attack = int(0.002 * SAMPLE_RATE)
    if attack > 1:
        out[:attack] *= np.linspace(0.0, 1.0, attack, dtype=np.float32)
    release = int(0.25 * SAMPLE_RATE)
    if n > release:
        out[-release:] *= np.linspace(1.0, 0.0, release, dtype=np.float32)
    return (out * 0.45).astype(np.float32)


def _piano(note: float, duration: float = 2.4) -> np.ndarray:
    n = int(float(np.clip(duration, 0.6, 4.0)) * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    attack = np.clip(t / 0.006, 0.0, 1.0)
    env = attack * np.exp(-t * 1.9)
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.45 * np.sin(2 * np.pi * freq * 2.0 * t)
        + 0.18 * np.sin(2 * np.pi * freq * 3.0 * t)
        + 0.07 * np.sin(2 * np.pi * freq * 4.01 * t)
    )
    rng = np.random.default_rng(int(round(note * 31)) + 5)
    hammer = rng.standard_normal(n) * np.exp(-t * 180.0) * 0.06
    wave = signal.sosfilt(
        signal.butter(2, 5200 / (SAMPLE_RATE / 2), "low", output="sos"), wave + hammer
    )
    return (wave * env * 0.32).astype(np.float32)


def _marimba(note: float, duration: float = 1.2) -> np.ndarray:
    n = int(float(np.clip(duration, 0.25, 3.0)) * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    env = _env_exp(n, 7.0, attack=0.0015)
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.35 * np.sin(2 * np.pi * freq * 4.01 * t)
        + 0.12 * np.sin(2 * np.pi * freq * 7.02 * t)
    )
    click = _noise(n, 77) * _env_exp(n, 180.0) * 0.05
    wave = signal.sosfilt(
        signal.butter(2, 5200 / (SAMPLE_RATE / 2), "low", output="sos"), wave + click
    )
    return (wave * env * 0.38).astype(np.float32)


def _synth(note: float, duration: float = 1.2) -> np.ndarray:
    n = int(float(np.clip(duration, 0.25, 3.2)) * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = midi_to_hz(note)
    env = _env_exp(n, 3.2, attack=0.006)
    wave = np.zeros(n, dtype=np.float32)
    for harmonic in range(1, 8):
        wave += np.sin(2 * np.pi * freq * harmonic * t) / harmonic
    wave = signal.sosfilt(
        signal.butter(2, 2800 / (SAMPLE_RATE / 2), "low", output="sos"), wave
    )
    return (wave * env * 0.22).astype(np.float32)


def _reverb_ir(seed: int = 99, duration: float = 1.35) -> np.ndarray:
    """Small stereo impulse response (early reflections + diffuse tail)."""
    n = int(duration * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    rng = np.random.default_rng(seed)
    channels = []
    for channel in range(2):
        noise = rng.standard_normal(n)
        # Diffuse tail: brighter at the start, darker as it decays.
        cutoff = 6800 if duration > 2.0 else 5200
        tail = signal.sosfilt(
            signal.butter(2, cutoff / (SAMPLE_RATE / 2), "low", output="sos"), noise
        )
        envelope = np.exp(-t * (4.4 * 1.35 / duration)) * (1.0 - np.exp(-t * 900.0))
        ir = tail * envelope
        for delay, gain in ((0.011, 0.55), (0.019, 0.4), (0.029, 0.3), (0.041, 0.22)):
            index = int(delay * SAMPLE_RATE) + channel * 37
            if index < n:
                ir[index] += gain
        ir /= np.sqrt(np.sum(ir**2)) + 1e-9
        channels.append(ir.astype(np.float32))
    return np.column_stack(channels)


@lru_cache(maxsize=2)
def _cached_ir(style: str = "pulse") -> np.ndarray:
    return _reverb_ir(duration=2.9 if style == "evasion" else 1.35)


def _convolve_reverb(send: np.ndarray, style: str = "pulse") -> np.ndarray:
    """FFT convolution keeps reverb cost linear-ish even on 10-minute tracks."""
    ir = _cached_ir(style)
    left = signal.fftconvolve(send[:, 0], ir[:, 0])[: send.shape[0]]
    right = signal.fftconvolve(send[:, 1], ir[:, 1])[: send.shape[0]]
    wet = np.column_stack([left, right]).astype(np.float32)
    # Compensate the IR normalisation so the wet bus sits behind the dry mix.
    return wet * (2.3 if style == "evasion" else 1.9)


def render_plan(plan: RhythmPlan, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Render a plan into a stereo float32 array (N, 2)."""
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Rendering only supports {SAMPLE_RATE} Hz for now.")
    n_total = max(1, int(np.ceil(plan.duration * sample_rate)) + sample_rate // 2)
    style = getattr(plan, "style", "pulse")
    sound = getattr(plan, "sound", SoundSettings())
    dry = np.zeros((n_total, 2), dtype=np.float32)
    send = np.zeros((n_total, 2), dtype=np.float32)
    echo = np.zeros((n_total, 2), dtype=np.float32)
    guitar_cache: dict[tuple[int, int, int], np.ndarray] = {}

    kit = sound.kit if sound.kit in drums.KIT_LABELS else "analog"
    kick = drums.render_kick(kit)
    soft_kick = _soft_kick()
    boom = _boom()
    impact = drums.render_impact(kit)
    hat = drums.render_hat(kit, False)
    openhat = drums.render_hat(kit, True)
    clap = drums.render_clap(kit)
    crash = _crash()
    tick = _tick()
    shimmer = _shimmer()

    for hit in plan.hits:
        start = int(round(hit.time * sample_rate))
        if start >= n_total:
            continue
        if hit.instrument == "kick":
            buf = kick
        elif hit.instrument == "softkick":
            buf = soft_kick
        elif hit.instrument == "boom":
            buf = boom
        elif hit.instrument == "impact":
            buf = impact
        elif hit.instrument == "hat":
            buf = hat
        elif hit.instrument == "openhat":
            buf = openhat
        elif hit.instrument == "clap":
            buf = clap
        elif hit.instrument == "crash":
            buf = crash
        elif hit.instrument == "tick":
            buf = tick
        elif hit.instrument == "shimmer":
            buf = shimmer
        elif hit.instrument == "sub" and hit.note is not None:
            buf = _sub(hit.note, hit.duration)
        elif hit.instrument == "pad" and hit.note is not None:
            buf = _pad(hit.note, hit.duration)
        elif hit.instrument == "pad_warm" and hit.note is not None:
            buf = _pad_warm(hit.note, hit.duration)
        elif hit.instrument == "bell" and hit.note is not None:
            buf = _bell(hit.note, hit.duration)
        elif hit.instrument == "guitar" and hit.note is not None:
            key = (
                int(round(hit.note)),
                int(round(hit.duration * 10)),
                int(round(sound.brightness * 10)),
            )
            buf = guitar_cache.get(key)
            if buf is None:
                buf = _guitar(hit.note, hit.duration, sound.brightness)
                guitar_cache[key] = buf
        elif hit.instrument == "piano" and hit.note is not None:
            buf = _piano(hit.note, hit.duration)
        elif hit.instrument == "marimba" and hit.note is not None:
            buf = _marimba(hit.note, hit.duration)
        elif hit.instrument == "strings" and hit.note is not None:
            buf = _pad_warm(hit.note, hit.duration)
        elif hit.instrument == "synth" and hit.note is not None:
            buf = _synth(hit.note, hit.duration)
        elif hit.instrument == "arp" and hit.note is not None:
            buf = _arp(hit.note, hit.duration)
        elif hit.instrument == "drone" and hit.note is not None:
            buf = _drone(hit.note, hit.duration)
        elif hit.instrument == "riser":
            buf = _riser(hit.duration)
        elif hit.instrument == "swell":
            buf = _swell(hit.duration)
        elif hit.instrument == "stab":
            buf = _stab((57, 60, 64))
        else:
            continue

        end = min(n_total, start + len(buf))
        if end <= start:
            continue
        segment = buf[: end - start] * float(np.clip(hit.velocity, 0.0, 1.0))
        pan = float(np.clip(hit.pan, -1.0, 1.0))
        left = np.sqrt((1.0 - pan) * 0.5)
        right = np.sqrt((1.0 + pan) * 0.5)
        gain = {
            "kick": 0.9,
            "softkick": 0.45,
            "boom": 0.50,
            "sub": 0.30,
            "hat": 0.20,
            "openhat": 0.17,
            "clap": 0.34,
            "impact": 0.80,
            "crash": 0.26,
            "riser": 0.22,
            "stab": 0.2,
            "pad": 0.16,
            "pad_warm": 0.18,
            "bell": 0.66,
            "arp": 0.74,
            "tick": 0.55,
            "shimmer": 0.50,
            "swell": 0.22,
            "drone": 0.18,
            "guitar": 0.55,
            "piano": 0.50,
            "marimba": 0.44,
            "strings": 0.30,
            "synth": 0.32,
        }.get(hit.instrument, 0.5)
        if hit.instrument in {"softkick", "boom", "sub", "drone"}:
            gain *= 0.55 + 0.90 * float(np.clip(sound.low_end, 0.0, 1.0))
        dry[start:end, 0] += segment * left * gain
        dry[start:end, 1] += segment * right * gain
        amount = REVERB_SEND.get(hit.instrument, 0.1)
        amount *= 0.40 + 1.10 * float(np.clip(sound.reverb, 0.0, 1.0))
        if amount:
            send[start:end, 0] += segment * left * gain * amount
            send[start:end, 1] += segment * right * gain * amount
        if hit.instrument in {"bell", "arp", "shimmer", "guitar", "piano", "marimba", "strings", "synth"}:
            echo[start:end, 0] += segment * left * gain * 0.8
            echo[start:end, 1] += segment * right * gain * 0.8

    if echo.any():
        send += _pingpong_delay(echo, delay_s=0.52 if style == "evasion" else 0.36)
    wet = _convolve_reverb(send, style)
    wet_gain = (0.55 + 0.95 * float(np.clip(sound.reverb, 0.0, 1.0))) * (
        1.0 if style == "evasion" else 0.9
    )
    mix = dry + wet * wet_gain

    # Global tone control from the customization panel.
    brightness = float(np.clip(sound.brightness, 0.0, 1.0))
    cutoff = 1400.0 + 10500.0 * brightness
    if cutoff < SAMPLE_RATE * 0.45:
        sos = signal.butter(2, cutoff / (SAMPLE_RATE / 2), "low", output="sos")
        mix = signal.sosfilt(sos, mix, axis=0).astype(np.float32)

    # Clean bus for the ambient style: no saturation, just peak management.
    if style == "evasion":
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 0:
            mix *= min(1.0, 0.90 / peak)
    else:
        mix = np.tanh(mix * 1.15) * 0.92
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 0.95:
            mix *= 0.95 / peak

    # Short fade in and a musical fade out.
    fade_in = int(0.03 * sample_rate)
    if mix.shape[0] > fade_in * 2:
        mix[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)[:, None]
        fade_out = int(min(4.0 if style == "evasion" else 2.0, plan.duration * 0.2) * sample_rate)
        if fade_out > 10:
            mix[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)[:, None]
    return mix.astype(np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    import soundfile as sf

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate, subtype="PCM_16")
    return path


def render_to_wav(plan: RhythmPlan, path: str | Path) -> Path:
    return write_wav(path, render_plan(plan))


def completion_melody() -> np.ndarray:
    """Short, soft four-note chime played when a background render finishes."""
    notes = ((69, 0.00), (72, 0.16), (76, 0.32), (81, 0.50))
    total = 2.4
    n_total = int(total * SAMPLE_RATE)
    mix = np.zeros((n_total, 2), dtype=np.float32)
    for index, (note, offset) in enumerate(notes):
        buffer = _bell(float(note), 1.15)
        start = int(offset * SAMPLE_RATE)
        end = min(n_total, start + len(buffer))
        if end <= start:
            continue
        segment = buffer[: end - start] * (0.42 - 0.04 * index)
        pan = (-0.18, 0.10, 0.22, -0.06)[index]
        left = np.sqrt((1.0 - pan) * 0.5)
        right = np.sqrt((1.0 + pan) * 0.5)
        mix[start:end, 0] += segment * left
        mix[start:end, 1] += segment * right
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.85:
        mix *= 0.85 / peak
    return mix
