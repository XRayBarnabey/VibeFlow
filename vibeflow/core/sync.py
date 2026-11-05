"""Video / gyro synchronization.

The camera does not necessarily timestamp its IMU log on the same clock as the
recording, so VibeFlow estimates the delay by correlating the visual motion
energy of the footage with the angular speed measured by the gyroscope. The
result is always presented as an editable offset: automatic sync is a proposal,
never a silent decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..media.ffmpeg import find_ffmpeg, popen_hidden, probe_video
from .dsp import lowpass, smooth
from .gyro import GyroTrack

MOTION_FPS = 10.0
MOTION_WIDTH = 128
MOTION_HEIGHT = 72


@dataclass
class SyncEstimate:
    offset: float
    confidence: float
    correlation: float
    method: str
    fps: float = MOTION_FPS
    candidates: np.ndarray = field(default_factory=lambda: np.zeros(0))
    scores: np.ndarray = field(default_factory=lambda: np.zeros(0))
    note: str = ""

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= 0.45 and self.correlation >= 0.25


def video_motion_energy(
    path: str | Path,
    fps: float = MOTION_FPS,
    width: int = MOTION_WIDTH,
    height: int = MOTION_HEIGHT,
    max_seconds: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (times, normalised frame-difference energy) for a video."""
    ffmpeg = find_ffmpeg()
    args = [
        ffmpeg,
        "-v",
        "error",
        "-hwaccel",
        "auto",
        "-i",
        str(path),
    ]
    if max_seconds:
        args += ["-t", f"{max_seconds:.3f}"]
    args += [
        "-vf",
        f"fps={fps},scale={width}:{height}:flags=fast_bilinear,format=gray",
        "-an",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    process = popen_hidden(args)
    assert process.stdout is not None
    raw = process.stdout.read()
    stderr = process.stderr.read() if process.stderr else b""
    process.wait()
    if process.returncode != 0 and not raw:
        raise RuntimeError(
            "Extraction du mouvement vidéo impossible : "
            + stderr.decode(errors="replace")[-300:]
        )

    frame_size = width * height
    count = len(raw) // frame_size
    if count < 4:
        raise RuntimeError("Vidéo trop courte pour estimer la synchronisation.")
    frames = np.frombuffer(raw[: count * frame_size], dtype=np.uint8).reshape(count, frame_size)
    frames = frames.astype(np.float32) / 255.0
    diff = np.mean(np.abs(np.diff(frames, axis=0)), axis=1)
    energy = np.concatenate(([0.0], diff))
    energy = smooth(energy, fps, 0.12)
    peak = float(np.percentile(energy, 97)) if energy.size else 0.0
    if peak > 1e-6:
        energy = energy / peak
    times = np.arange(count) / fps
    return times, energy


def estimate_offset_from_signals(
    gyro_t: np.ndarray,
    gyro_speed: np.ndarray,
    video_t: np.ndarray,
    video_energy: np.ndarray,
    *,
    max_offset: float = 10.0,
    fps: float = MOTION_FPS,
    step: float | None = None,
) -> SyncEstimate:
    """Correlate two signals to find ``video_time = gyro_time + offset``."""
    if gyro_t.size < 8 or video_t.size < 8:
        return SyncEstimate(0.0, 0.0, 0.0, "insufficient-data")

    step = step or 1.0 / fps
    offsets = np.arange(-max_offset, max_offset + step * 0.5, step)
    # Trim the video grid so both signals overlap for the whole search.
    valid = (video_t >= max(0.0, -offsets.min())) & (video_t <= video_t[-1] - max(0.0, offsets.max()))
    # Simpler: evaluate correlation on the intersection for each candidate and
    # require at least 60 % of the shorter signal to overlap.
    scores = np.full(offsets.shape, -1.0, dtype=np.float64)

    v = video_energy - np.mean(video_energy)
    v_std = float(np.std(v)) or 1e-9
    v = v / v_std

    for i, offset in enumerate(offsets):
        sample_times = video_t - offset
        inside = (sample_times >= gyro_t[0]) & (sample_times <= gyro_t[-1])
        if inside.sum() < max(8, int(0.35 * len(video_t))):
            continue
        g = np.interp(sample_times[inside], gyro_t, gyro_speed)
        if np.std(g) < 1e-9:
            continue
        g = (g - np.mean(g)) / np.std(g)
        scores[i] = float(np.mean(g * v[inside]))

    if np.all(scores < -0.5):
        return SyncEstimate(0.0, 0.0, 0.0, "no-overlap", fps, offsets, scores)

    best_index = int(np.argmax(scores))
    best_score = float(scores[best_index])
    valid_scores = scores[scores > -0.5]
    median = float(np.median(valid_scores)) if valid_scores.size else 0.0
    spread = float(np.std(valid_scores)) if valid_scores.size else 1.0
    z_score = (best_score - median) / max(spread, 1e-6)
    confidence = float(np.clip((z_score - 1.5) / 4.0, 0.0, 1.0))
    if best_score < 0.22:
        confidence *= 0.25

    return SyncEstimate(
        offset=float(offsets[best_index]),
        confidence=confidence,
        correlation=best_score,
        method="motion-correlation",
        fps=fps,
        candidates=offsets,
        scores=scores,
    )


def estimate_offset(
    video_path: str | Path,
    track: GyroTrack,
    *,
    max_offset: float = 10.0,
    max_seconds: float | None = 60.0,
) -> SyncEstimate:
    video_t, video_energy = video_motion_energy(video_path, max_seconds=max_seconds)
    speed = np.degrees(np.linalg.norm(track.rates, axis=1))
    speed = lowpass(speed, track.sample_rate, 5.0)
    estimate = estimate_offset_from_signals(
        track.t, speed, video_t, video_energy, max_offset=max_offset
    )
    estimate.note = (
        "Décalage estimé par corrélation mouvement vidéo / vitesse angulaire. "
        "Ajustez si nécessaire avec le champ de décalage."
    )
    return estimate


def estimate_offset_from_metadata(video_path: str | Path, track: GyroTrack) -> SyncEstimate | None:
    """Fallback using container creation time and the GCSV UNIX timestamp."""
    stamp = track.metadata.get("timestamp")
    if not stamp:
        return None
    try:
        start = float(stamp)
    except ValueError:
        return None
    try:
        info = probe_video(video_path)
    except RuntimeError:
        return None
    if not info.creation_time:
        return None
    try:
        created = datetime.fromisoformat(info.creation_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    offset = created.timestamp() - start
    if abs(offset) > 3600:
        return None
    return SyncEstimate(
        offset=offset,
        confidence=0.3,
        correlation=0.0,
        method="metadata-clock",
        note="Décalage déduit des métadonnées (horloges caméra/gyro). À vérifier visuellement.",
    )
