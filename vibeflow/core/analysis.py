"""Flight analysis: turn raw gyro rates into scored, classified events.

The gyroscope measures the *actual* body rotation of the aircraft, not stick
inputs. Detection therefore works on angular displacement (integral of rate),
peak rate, angular acceleration and the monotonicity of the rotation, which
separates a committed trick from a small pilot correction.

All thresholds are expressed in physical units (deg, deg/s, deg/s²) so the
engine behaves identically whatever the logging rate of the camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .dsp import lowpass, smooth
from .gyro import GyroTrack

AXIS_NAMES = ("roll", "pitch", "yaw")
AXIS_LABELS = ("Roll", "Pitch", "Yaw")

KIND_LABELS = {
    "roll": "Tonneau",
    "inversion": "Inversion",
    "roll360": "Tonneau 360°",
    "multirotation": "Rotations multiples",
    "pitch": "Bascule",
    "flip": "Flip",
    "multiflip": "Flips multiples",
    "yaw": "Rotation lacet",
    "spin": "Spin",
    "combo": "Figure combinée",
    "switch": "Changement de direction",
    "accel": "Accélération",
    "brake": "Décélération",
    "flow": "Séquence fluide",
}

KIND_COLORS = {
    "roll": "#5FA8D3",
    "inversion": "#8E7CC3",
    "roll360": "#4C8BF5",
    "multirotation": "#3D6FD6",
    "pitch": "#6FBF8B",
    "flip": "#3FA06A",
    "multiflip": "#2E7D52",
    "yaw": "#D3A15F",
    "spin": "#C08A3E",
    "combo": "#C77DFF",
    "switch": "#D97A7A",
    "accel": "#E0B15C",
    "brake": "#B08968",
    "flow": "#6C7A89",
}

_KIND_IMPORTANCE = {
    "multirotation": 1.00,
    "multiflip": 1.00,
    "combo": 0.98,
    "roll360": 0.92,
    "flip": 0.90,
    "inversion": 0.86,
    "spin": 0.84,
    "roll": 0.78,
    "pitch": 0.72,
    "yaw": 0.66,
    "switch": 0.60,
    "accel": 0.48,
    "brake": 0.40,
    "flow": 0.30,
}


@dataclass
class FlightEvent:
    """A musically relevant moment of the flight."""

    index: int
    kind: str
    axis: int
    t_start: float
    t_peak: float
    t_end: float
    angle_deg: float
    peak_rate_dps: float
    peak_accel_dps2: float
    score: float
    monotonicity: float
    enabled: bool = True
    manual: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.t_end - self.t_start)

    @property
    def label(self) -> str:
        base = KIND_LABELS.get(self.kind, self.kind)
        if self.kind in {"combo", "flow", "switch", "accel", "brake"}:
            return base
        return f"{base} {AXIS_LABELS[self.axis].lower()}"

    @property
    def color(self) -> str:
        return KIND_COLORS.get(self.kind, "#8899AA")

    @property
    def importance(self) -> float:
        return _KIND_IMPORTANCE.get(self.kind, 0.5) * (0.55 + 0.45 * self.score)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "axis": self.axis,
            "t_start": round(self.t_start, 4),
            "t_peak": round(self.t_peak, 4),
            "t_end": round(self.t_end, 4),
            "angle_deg": round(self.angle_deg, 1),
            "peak_rate_dps": round(self.peak_rate_dps, 1),
            "peak_accel_dps2": round(self.peak_accel_dps2, 1),
            "score": round(self.score, 3),
            "enabled": self.enabled,
        }


@dataclass
class AnalysisConfig:
    min_episode_rate: float = 55.0  # deg/s, below = pilot correction
    min_episode_angle: float = 65.0  # deg
    max_episode_duration: float = 3.0
    min_monotonicity: float = 0.5
    gap_merge_s: float = 0.12
    smooth_hz: float = 24.0
    switch_rate: float = 85.0
    switch_angle: float = 110.0
    accel_threshold: float = 900.0  # deg/s²
    flow_rate: float = 230.0
    flow_min_duration: float = 0.9


@dataclass
class FlightAnalysis:
    track: GyroTrack
    config: AnalysisConfig
    events: list[FlightEvent] = field(default_factory=list)
    activity: np.ndarray = field(default_factory=lambda: np.zeros(0))
    activity_t: np.ndarray = field(default_factory=lambda: np.zeros(0))
    rates_deg: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    accel_deg: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    angles_deg: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))

    @property
    def duration(self) -> float:
        return self.track.duration

    def visible(self, sensitivity: float) -> list[FlightEvent]:
        return filter_by_sensitivity(self.events, sensitivity)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _segments(mask: np.ndarray, merge_gap: int = 0) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    flags = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(flags.astype(np.int8)))
    segments = [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]
    if merge_gap <= 0 or len(segments) < 2:
        return segments
    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= merge_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _classify_episode(axis: int, angle: float, secondary_angle: float) -> str:
    magnitude = abs(angle)
    if secondary_angle > 90.0 and magnitude > 100.0:
        return "combo"
    if axis == 0:
        if magnitude >= 420:
            return "multirotation"
        if magnitude >= 250:
            return "roll360"
        if 145 <= magnitude < 250:
            return "inversion"
        return "roll"
    if axis == 1:
        if magnitude >= 420:
            return "multiflip"
        if magnitude >= 250:
            return "flip"
        return "pitch"
    if magnitude >= 300:
        return "spin"
    return "yaw"


def _base_score(
    angle: float,
    peak_rate: float,
    peak_accel: float,
    duration: float,
    monotonicity: float,
) -> float:
    amp = min(abs(angle) / 380.0, 1.0)
    rate = min(peak_rate / 720.0, 1.0)
    accel = min(peak_accel / 4200.0, 1.0)
    dur = min(duration / 1.1, 1.0)
    score = (
        0.38 * amp
        + 0.27 * rate
        + 0.13 * accel
        + 0.10 * dur
        + 0.12 * max(0.0, min(monotonicity, 1.0))
    )
    return float(max(0.0, min(1.0, score)))


def analyse(track: GyroTrack, config: AnalysisConfig | None = None) -> FlightAnalysis:
    config = config or AnalysisConfig()
    fs = track.sample_rate
    rates_deg = np.degrees(track.rates)
    filtered = np.column_stack(
        [lowpass(rates_deg[:, i], fs, config.smooth_hz) for i in range(3)]
    )
    accel = np.gradient(filtered, axis=0) * fs
    accel = np.column_stack([lowpass(accel[:, i], fs, 18.0) for i in range(3)])

    dt = 1.0 / fs
    speed = np.linalg.norm(filtered, axis=1)
    activity = smooth(speed, fs, 0.08)

    episodes: list[dict] = []
    cum = np.cumsum(filtered * dt, axis=0)
    cum_abs = np.cumsum(np.abs(filtered) * dt, axis=0)
    merge_gap = int(config.gap_merge_s * fs)

    for axis in range(3):
        mask = np.abs(filtered[:, axis]) > config.min_episode_rate
        for start, end in _segments(mask, merge_gap):
            if end - start < int(0.10 * fs):
                continue
            duration = (end - start) / fs
            if duration > config.max_episode_duration:
                continue
            window = filtered[start:end, axis]
            integral = float(np.sum(window) * dt)
            absolute = float(np.sum(np.abs(window)) * dt)
            if abs(integral) < config.min_episode_angle:
                continue
            monotonicity = abs(integral) / max(absolute, 1e-9)
            if monotonicity < config.min_monotonicity:
                continue
            peak_rate = float(np.max(np.abs(window)))
            peak_index = start + int(np.argmax(np.abs(window)))
            peak_accel = float(np.max(np.abs(accel[start:end, axis])))
            episodes.append(
                {
                    "start": start,
                    "end": end,
                    "axis": axis,
                    "angle": integral,
                    "peak_rate": peak_rate,
                    "peak_index": peak_index,
                    "peak_accel": peak_accel,
                    "monotonicity": monotonicity,
                }
            )

    # Merge concurrent episodes on different axes into combo figures.
    episodes.sort(key=lambda e: e["start"])
    merged: list[dict] = []
    consumed = [False] * len(episodes)
    for i, first in enumerate(episodes):
        if consumed[i]:
            continue
        group = [first]
        consumed[i] = True
        changed = True
        while changed:
            changed = False
            for j, other in enumerate(episodes):
                if consumed[j]:
                    continue
                for member in group:
                    overlap = min(member["end"], other["end"]) - max(member["start"], other["start"])
                    shorter = min(member["end"] - member["start"], other["end"] - other["start"])
                    if shorter > 0 and overlap / shorter > 0.45 and member["axis"] != other["axis"]:
                        group.append(other)
                        consumed[j] = True
                        changed = True
                        break
        if len({m["axis"] for m in group}) > 1:
            axes = [m["axis"] for m in group]
            dominant = max(group, key=lambda m: abs(m["angle"]) * (0.6 + 0.4 * m["monotonicity"]))
            secondary = max(
                (m for m in group if m["axis"] != dominant["axis"]),
                key=lambda m: abs(m["angle"]),
                default=None,
            )
            combined = dict(dominant)
            combined["start"] = min(m["start"] for m in group)
            combined["end"] = max(m["end"] for m in group)
            combined["angle"] = sum(m["angle"] for m in group if m["axis"] == dominant["axis"])
            combined["secondary_angle"] = abs(secondary["angle"]) if secondary else 0.0
            merged.append(combined)
        else:
            first = dict(first)
            first["secondary_angle"] = 0.0
            merged.append(first)

    events: list[FlightEvent] = []

    def add_event(
        kind: str,
        axis: int,
        start: float,
        peak: float,
        end: float,
        angle: float,
        peak_rate: float,
        peak_accel: float,
        monotonicity: float,
    ) -> None:
        score = _base_score(angle, peak_rate, peak_accel, end - start, monotonicity)
        events.append(
            FlightEvent(
                index=0,
                kind=kind,
                axis=axis,
                t_start=float(start),
                t_peak=float(peak),
                t_end=float(end),
                angle_deg=float(angle),
                peak_rate_dps=float(peak_rate),
                peak_accel_dps2=float(peak_accel),
                score=score,
                monotonicity=float(monotonicity),
            )
        )

    episode_windows = []
    for ep in merged:
        start = ep["start"] / fs
        end = ep["end"] / fs
        peak = ep["peak_index"] / fs
        kind = _classify_episode(ep["axis"], ep["angle"], ep.get("secondary_angle", 0.0))
        add_event(
            kind,
            ep["axis"],
            start,
            peak,
            end,
            ep["angle"],
            ep["peak_rate"],
            ep["peak_accel"],
            ep["monotonicity"],
        )
        episode_windows.append((start, end))

    def covered(t: float, margin: float = 0.02) -> bool:
        return any(start - margin <= t <= end + margin for start, end in episode_windows)

    # --- Direction changes -------------------------------------------------
    if fs > 10:
        slow = np.column_stack([lowpass(rates_deg[:, i], fs, 6.0) for i in range(3)])
        for axis in range(3):
            sign = np.sign(slow[:, axis])
            crossings = np.flatnonzero(np.diff(sign) != 0)
            last_time = -10.0
            for c in crossings:
                if sign[c] == 0:
                    continue
                t_cross = c / fs
                if t_cross - last_time < 0.45:
                    continue
                search = int(0.6 * fs)
                before = slow[max(0, c - search) : c, axis]
                after = slow[c : min(len(slow), c + search), axis]
                if before.size == 0 or after.size == 0:
                    continue
                peak_before = float(np.max(np.abs(before)))
                peak_after = float(np.max(np.abs(after)))
                if peak_before < config.switch_rate or peak_after < config.switch_rate:
                    continue
                swing = peak_before + peak_after
                if swing < config.switch_angle:
                    continue
                if covered(t_cross, 0.08):
                    continue
                add_event(
                    "switch",
                    axis,
                    t_cross - 0.25,
                    t_cross,
                    t_cross + 0.25,
                    swing,
                    max(peak_before, peak_after),
                    0.0,
                    0.8,
                )
                last_time = t_cross

    # --- Angular acceleration bursts --------------------------------------
    from scipy.signal import find_peaks

    accel_mag = np.max(np.abs(accel), axis=1)
    peaks, props = find_peaks(
        accel_mag,
        height=config.accel_threshold,
        distance=max(1, int(0.35 * fs)),
        prominence=config.accel_threshold * 0.5,
    )
    for idx in peaks:
        t_peak = idx / fs
        if covered(t_peak, 0.15):
            continue
        axis = int(np.argmax(np.abs(accel[idx])))
        rate_here = float(filtered[idx, axis])
        rate_before = float(filtered[max(0, idx - int(0.12 * fs)), axis])
        kind = "accel" if abs(rate_here) >= abs(rate_before) else "brake"
        magnitude = float(accel_mag[idx])
        score = min(0.62, 0.22 + magnitude / 6000.0)
        events.append(
            FlightEvent(
                index=0,
                kind=kind,
                axis=axis,
                t_start=max(0.0, t_peak - 0.18),
                t_peak=t_peak,
                t_end=min(track.duration, t_peak + 0.18),
                angle_deg=abs(rate_here) * 0.2,
                peak_rate_dps=abs(rate_here),
                peak_accel_dps2=magnitude,
                score=score,
                monotonicity=0.5,
            )
        )

    # --- Sustained flow ----------------------------------------------------
    flow_mask = activity > config.flow_rate
    for start, end in _segments(flow_mask, int(0.25 * fs)):
        duration = (end - start) / fs
        if duration < config.flow_min_duration:
            continue
        t_start, t_end = start / fs, end / fs
        overlap = sum(
            max(0.0, min(t_end, e_end) - max(t_start, e_start))
            for e_start, e_end in episode_windows
        )
        if overlap / max(duration, 1e-6) > 0.55:
            continue
        segment = activity[start:end]
        t_peak = (start + int(np.argmax(segment))) / fs
        strength = float(np.mean(segment))
        score = min(0.55, 0.2 + strength / 900.0)
        events.append(
            FlightEvent(
                index=0,
                kind="flow",
                axis=int(np.argmax(np.max(np.abs(filtered[start:end]), axis=0))),
                t_start=t_start,
                t_peak=t_peak,
                t_end=t_end,
                angle_deg=float(np.sum(np.abs(filtered[start:end]).max(axis=1)) / fs),
                peak_rate_dps=float(np.max(segment)),
                peak_accel_dps2=float(np.max(accel_mag[start:end])),
                score=score,
                monotonicity=0.6,
            )
        )

    events = _suppress_duplicates(events)

    # Repetition penalty: a trick repeated identically is a little less striking.
    for i, event in enumerate(events):
        recent = [
            other
            for other in events[:i]
            if other.kind == event.kind
            and other.axis == event.axis
            and event.t_peak - other.t_peak < 9.0
            and event.t_peak >= other.t_peak
        ]
        if recent:
            event.score = float(max(0.0, event.score * (1.0 - min(0.18, 0.045 * len(recent)))))

    events.sort(key=lambda e: e.t_peak)
    for i, event in enumerate(events):
        event.index = i

    return FlightAnalysis(
        track=track,
        config=config,
        events=events,
        activity=activity,
        activity_t=track.t,
        rates_deg=filtered,
        accel_deg=accel,
        angles_deg=np.column_stack(
            [np.cumsum(filtered[:, i]) * dt - np.mean(np.cumsum(filtered[:, i]) * dt) for i in range(3)]
        ),
    )


def _suppress_duplicates(events: list[FlightEvent]) -> list[FlightEvent]:
    """Keep the strongest event when two detections peak within 120 ms."""
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e.t_peak)
    kept: list[FlightEvent] = []
    for event in ordered:
        duplicate = False
        for existing in reversed(kept[-6:]):
            if event.t_peak - existing.t_peak > 0.12:
                break
            if existing.kind == "flow" or event.kind == "flow":
                if abs(existing.t_peak - event.t_peak) < 1.5:
                    duplicate = True
                    break
                continue
            duplicate = True
            if event.score > existing.score and event.kind != "switch":
                kept.remove(existing)
                duplicate = False
            break
        if not duplicate:
            kept.append(event)
    return kept


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------


def score_threshold(sensitivity: float) -> float:
    """Sensitivity 0 = only spectacular moves, 1 = subtle moves."""
    s = float(np.clip(sensitivity, 0.0, 1.0))
    return 0.84 - 0.49 * s


def angle_threshold(sensitivity: float) -> float:
    s = float(np.clip(sensitivity, 0.0, 1.0))
    return 265.0 - 195.0 * s


def filter_by_sensitivity(
    events: Iterable[FlightEvent], sensitivity: float
) -> list[FlightEvent]:
    score_min = score_threshold(sensitivity)
    angle_min = angle_threshold(sensitivity)
    visible: list[FlightEvent] = []
    for event in events:
        if not event.enabled:
            continue
        if event.kind in {"flow", "accel", "brake", "switch"}:
            if event.score < score_min:
                continue
        else:
            if event.score < score_min or abs(event.angle_deg) < angle_min:
                continue
        visible.append(event)
    return visible


def sensitivity_curve(sensitivity: float) -> dict[str, float]:
    return {
        "score": score_threshold(sensitivity),
        "angle": angle_threshold(sensitivity),
    }
