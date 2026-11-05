"""Rhythmic pre-listen: build a coherent musical plan from flight events.

The output is a list of :class:`Hit` objects (instrument, exact time, velocity,
note). Rendering is delegated to :mod:`vibeflow.core.synth`, which keeps the
composition logic testable and exportable to MIDI later.

Musical rules
-------------
* A tempo is chosen so that the detected figures naturally land on the groove.
* The arrangement follows the flight energy (intro / build / groove / peak /
  break), so density evolves with the piloting instead of being constant.
* Every significant figure produces an accent at its *exact* peak timestamp:
  that is what makes the pre-listen feel written for the flight.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

import numpy as np

from .analysis import FlightEvent
from .dsp import smooth

# A minor, i - VI - III - VII. MIDI notes for the sub bass.
BASS_PROGRESSION = (33, 29, 36, 31)
BASS_VELOCITY = 0.62

# Root, pad voicing, arpeggio voicing. A minor / Fmaj7 / Cmaj7 / G6.
AMBIENT_CHORDS = (
    (33, (57, 60, 64, 67), (69, 72, 76, 79)),
    (29, (53, 57, 60, 64), (65, 69, 72, 76)),
    (36, (52, 55, 59, 64), (67, 71, 74, 79)),
    (31, (55, 59, 62, 64), (67, 71, 74, 79)),
)

STYLE_LABELS = {
    "evasion": "Évasion de l'esprit",
    "pulse": "Pulse rythmique",
}

ACCENT_LABELS = {
    "guitar": "Guitare",
    "piano": "Piano",
    "bell": "Cloche",
    "marimba": "Marimba",
    "strings": "Cordes",
    "synth": "Synthé",
}


@dataclass(frozen=True)
class SoundSettings:
    """Per-project sound design, applied to the arrangement and the render."""

    accent: str = "guitar"
    density: float = 0.65
    brightness: float = 0.60
    reverb: float = 0.55
    low_end: float = 0.50
    kit: str = "analog"

INSTRUMENT_GAIN = {
    "kick": 0.92,
    "sub": 0.55,
    "hat": 0.20,
    "openhat": 0.18,
    "clap": 0.34,
    "impact": 0.78,
    "crash": 0.30,
    "riser": 0.22,
    "stab": 0.20,
    "pad": 0.16,
}

FIGURE_KINDS = {
    "roll",
    "inversion",
    "roll360",
    "multirotation",
    "pitch",
    "flip",
    "multiflip",
    "yaw",
    "spin",
    "combo",
}


MANUAL_LANE_LABELS = ("Haut", "Bas", "Gauche", "Droite")
MANUAL_LANE_SYMBOLS = ("↑", "↓", "←", "→")
MANUAL_DEFAULT_KEYS = ("Up", "Down", "Left", "Right")
MANUAL_DEFAULT_SOUNDS = ("impact", "kick", "clap", "hat")
MANUAL_COLORS = (
    "#7FA7C9",
    "#E0B15C",
    "#D97A7A",
    "#6FBF8B",
    "#B48EAD",
    "#5FA8D3",
    "#D3A15F",
    "#8FBF6F",
)
MANUAL_LANE_NOTES = (72, 57, 64, 67)
MANUAL_LANE_PANS = (0.0, 0.0, -0.28, 0.28)
MANUAL_SOUND_LABELS = {
    "kick": "Kick",
    "clap": "Clap",
    "hat": "Charleston",
    "openhat": "Open hat",
    "impact": "Impact",
    "boom": "Boom",
    "crash": "Crash",
    "tick": "Tick",
    "bell": "Cloche",
    "guitar": "Guitare",
    "piano": "Piano",
    "marimba": "Marimba",
    "strings": "Cordes",
    "synth": "Synthé",
}
MANUAL_MELODIC = {"bell", "guitar", "piano", "marimba", "strings", "synth"}


def default_manual_tracks() -> list["ManualTrack"]:
    return [
        ManualTrack(
            name=MANUAL_LANE_LABELS[index],
            key=MANUAL_DEFAULT_KEYS[index],
            color=MANUAL_COLORS[index],
            sound=MANUAL_DEFAULT_SOUNDS[index],
        )
        for index in range(4)
    ]


@dataclass
class ManualTrack:
    """A user-defined marker track: key, colour, sound and mute state."""

    name: str = "Piste"
    key: str = ""
    color: str = MANUAL_COLORS[0]
    sound: str = "kick"
    enabled: bool = True


@dataclass
class ManualAccent:
    """A marker placed by the user at a precise video timestamp."""

    time: float
    lane: int


@dataclass(frozen=True)
class Hit:
    time: float
    instrument: str
    velocity: float = 0.7
    note: float | None = None
    duration: float = 0.4
    pan: float = 0.0
    manual: bool = False


@dataclass
class Section:
    start: float
    end: float
    energy: float
    name: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class RhythmPlan:
    bpm: float
    beat_offset: float
    duration: float
    sections: list[Section] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    used_events: list[int] = field(default_factory=list)
    sensitivity: float = 0.5
    style: str = "evasion"
    sound: SoundSettings = field(default_factory=SoundSettings)

    @property
    def beat_period(self) -> float:
        return 60.0 / self.bpm

    def beats(self) -> np.ndarray:
        if self.duration <= 0:
            return np.zeros(0)
        count = int(np.ceil((self.duration - self.beat_offset) / self.beat_period)) + 1
        return self.beat_offset + np.arange(max(0, count)) * self.beat_period


# ---------------------------------------------------------------------------
# Tempo & structure
# ---------------------------------------------------------------------------


def estimate_tempo(events: Iterable[FlightEvent], duration: float) -> tuple[float, float]:
    """Return (bpm, offset) maximising event/grid alignment with a musical prior."""
    events = [e for e in events if e.kind != "flow"]
    if len(events) < 4 or duration <= 4.0:
        return 120.0, 0.0

    weights = np.array([max(0.15, e.importance) for e in events])
    times = np.array([e.t_peak for e in events])
    order = np.argsort(weights)[::-1][: min(60, len(events))]
    times = times[order]
    weights = weights[order]

    best = (-1e9, 120.0, 0.0)
    sigmas = 0.055
    candidates = np.arange(88, 169, 1.0)
    for bpm in candidates:
        period = 60.0 / bpm
        phases = np.arange(0.0, period, period / 24.0)
        # Cents distance of every event to the nearest beat for each phase.
        delta = (times[None, :] - phases[:, None]) % period
        delta = np.minimum(delta, period - delta)
        alignment = np.exp(-0.5 * (delta / sigmas) ** 2)
        phase_score = (alignment * weights[None, :]).sum(axis=1)
        best_phase_index = int(np.argmax(phase_score))
        prior = np.exp(-0.5 * ((bpm - 126.0) / 24.0) ** 2)
        score = float(phase_score[best_phase_index]) * (0.72 + 0.38 * prior)
        if score > best[0]:
            best = (score, float(bpm), float(phases[best_phase_index]))

    bpm, offset = best[1], best[2]
    # Fold the offset into the first bar for a clean downbeat.
    beat = 60.0 / bpm
    offset = offset % (4 * beat)
    return bpm, offset


def build_sections(
    activity: np.ndarray,
    activity_t: np.ndarray,
    duration: float,
    beat_period: float,
    events: Iterable[FlightEvent] | None = None,
) -> list[Section]:
    if duration <= 0:
        return []
    block = max(4 * beat_period, 2.0)
    n_blocks = max(1, int(np.ceil(duration / block)))
    grid_t = np.arange(n_blocks) * block + block / 2.0
    if activity.size and activity_t.size:
        energy = np.interp(grid_t, activity_t, activity, left=0.0, right=0.0)
    else:
        energy = np.zeros(n_blocks)

    # A short but violent figure must count as intensity: blend the block mean
    # with its high percentile instead of averaging the movement away.
    block_energy = np.zeros(n_blocks)
    if activity.size and activity_t.size:
        step = max(0.02, min(0.1, block / 20.0))
        for i in range(n_blocks):
            t0 = i * block
            t1 = min(duration, (i + 1) * block)
            if t1 <= t0:
                continue
            samples = np.arange(t0, t1, step)
            segment = np.interp(samples, activity_t, activity, left=0.0, right=0.0)
            block_energy[i] = 0.4 * float(np.mean(segment)) + 0.6 * float(
                np.percentile(segment, 88)
            )

    reference = float(np.percentile(block_energy, 90)) if block_energy.size else 1.0
    reference = max(reference, 1e-6)
    energy_norm = np.clip(block_energy / reference, 0.0, 1.0)
    if energy_norm.size >= 3:
        # Debounce the energy contour so the arrangement does not flicker
        # between sections every two seconds.
        padded = np.pad(energy_norm, 1, mode="edge")
        energy_norm = np.median(
            np.stack([padded[:-2], padded[1:-1], padded[2:]]), axis=0
        )

    accent_bonus = np.zeros(n_blocks)
    for event in events or []:
        if event.kind == "flow":
            continue
        index = int(np.clip(event.t_peak / block, 0, n_blocks - 1))
        accent_bonus[index] = min(0.5, accent_bonus[index] + 0.18 + 0.25 * event.importance)
    energy_norm = np.clip(energy_norm + accent_bonus, 0.0, 1.0)

    # A musical section lasts several bars: smooth the contour once more after
    # adding event accents so one figure cannot flip the whole arrangement.
    if energy_norm.size >= 5:
        kernel = np.hanning(5)
        kernel /= kernel.sum()
        padded = np.pad(energy_norm, 2, mode="edge")
        energy_norm = np.clip(np.convolve(padded, kernel, mode="same")[2:-2], 0.0, 1.0)

    names: list[str] = []
    for i in range(n_blocks):
        around = energy_norm[max(0, i - 1) : i + 2]
        level = float(energy_norm[i])
        previous = float(energy_norm[i - 1]) if i > 0 else level
        following = float(energy_norm[i + 1]) if i + 1 < n_blocks else level
        slope = following - previous
        if i * block < min(6.0, duration * 0.12) and level < 0.6:
            name = "intro"
        elif level < 0.22 and float(np.max(around)) < 0.3:
            name = "break"
        elif level > 0.72:
            name = "peak"
        elif slope > 0.18 and level < 0.9:
            name = "build"
        else:
            name = "groove"
        names.append(name)

    # Despike isolated labels, then merge identical neighbours.
    for i in range(1, len(names) - 1):
        if names[i] != names[i - 1] and names[i - 1] == names[i + 1]:
            names[i] = names[i - 1]

    sections: list[Section] = []
    for i, name in enumerate(names):
        start = i * block
        end = min(duration, (i + 1) * block)
        level = float(energy_norm[i])
        if sections and sections[-1].name == name:
            sections[-1].end = end
            sections[-1].energy = max(sections[-1].energy, level)
        else:
            sections.append(Section(start=start, end=end, energy=level, name=name))
    return _stabilise_sections(sections, block, max_sections=14)


def _stabilise_sections(
    sections: list[Section], block: float, *, max_sections: int = 14
) -> list[Section]:
    """Avoid two-second section flapping; keep the arrangement readable."""
    minimum = {"build": 2, "intro": 2}
    sections = [
        Section(s.start, s.end, s.energy, s.name) for s in sections
    ]

    def too_short(section: Section) -> bool:
        return section.duration < minimum.get(section.name, 4) * block - 1e-6

    guard = 0
    while len(sections) > 1 and guard < 200:
        guard += 1
        short = next(
            (i for i, section in enumerate(sections) if too_short(section)), None
        )
        if short is None:
            break
        if len(sections) == 1:
            break
        index = short
        current = sections[index]
        has_prev = index > 0
        has_next = index + 1 < len(sections)
        if current.name == "build" and has_next:
            target = index + 1
        elif not has_prev:
            target = index + 1
        elif not has_next:
            target = index - 1
        else:
            previous = sections[index - 1]
            following = sections[index + 1]
            target = (
                index - 1
                if abs(previous.energy - current.energy) <= abs(following.energy - current.energy)
                else index + 1
            )
        neighbour = sections[target]
        if target > index:
            merged = Section(
                current.start,
                neighbour.end,
                (current.energy * current.duration + neighbour.energy * neighbour.duration)
                / max(current.duration + neighbour.duration, 1e-6),
                neighbour.name,
            )
        else:
            merged = Section(
                neighbour.start,
                current.end,
                (current.energy * current.duration + neighbour.energy * neighbour.duration)
                / max(current.duration + neighbour.duration, 1e-6),
                neighbour.name,
            )
        low, high = sorted((index, target))
        sections[low : high + 1] = [merged]

    # Coalesce identical neighbours created by the merge.
    coalesced: list[Section] = []
    for section in sections:
        if coalesced and coalesced[-1].name == section.name:
            coalesced[-1].end = section.end
            coalesced[-1].energy = max(coalesced[-1].energy, section.energy)
        else:
            coalesced.append(section)

    # Last resort: cap the number of sections by merging the shortest ones.
    guard = 0
    while len(coalesced) > max_sections and guard < 200:
        guard += 1
        index = min(range(len(coalesced)), key=lambda i: coalesced[i].duration)
        current = coalesced[index]
        if index == 0:
            target = 1
        elif index == len(coalesced) - 1:
            target = index - 1
        else:
            target = (
                index - 1
                if abs(coalesced[index - 1].energy - current.energy)
                <= abs(coalesced[index + 1].energy - current.energy)
                else index + 1
            )
        neighbour = coalesced[target]
        if target > index:
            merged = Section(current.start, neighbour.end, neighbour.energy, neighbour.name)
        else:
            merged = Section(neighbour.start, current.end, neighbour.energy, neighbour.name)
        low, high = sorted((index, target))
        coalesced[low : high + 1] = [merged]
        merged_list: list[Section] = []
        for section in coalesced:
            if merged_list and merged_list[-1].name == section.name:
                merged_list[-1].end = section.end
                merged_list[-1].energy = max(merged_list[-1].energy, section.energy)
            else:
                merged_list.append(section)
        coalesced = merged_list
    return coalesced


# ---------------------------------------------------------------------------
# Groove generation
# ---------------------------------------------------------------------------


def _section_at(sections: list[Section], t: float) -> Section | None:
    for section in sections:
        if section.start <= t < section.end:
            return section
    return sections[-1] if sections else None


def _energy_at(sections: list[Section], t: float) -> float:
    section = _section_at(sections, t)
    return section.energy if section else 0.4


def _bar_pattern(bar_index: int, energy: float, name: str) -> dict[str, list[float]]:
    """Return beat offsets (in beats) for each instrument for one bar."""
    rng = np.random.default_rng(1000 + bar_index)
    pattern: dict[str, list[float]] = {"kick": [], "clap": [], "hat": [], "openhat": [], "sub": []}

    if name == "intro":
        pattern["kick"] = [0.0, 2.0] if bar_index % 2 else [0.0]
        pattern["hat"] = [1.0, 3.0]
        pattern["sub"] = [0.0]
    elif name == "break":
        pattern["kick"] = [0.0] if bar_index % 2 == 0 else []
        pattern["hat"] = [2.0, 3.5]
    elif name == "build":
        pattern["kick"] = [0.0, 1.0, 2.0, 3.0]
        pattern["clap"] = [1.0, 3.0] if energy > 0.35 else []
        pattern["hat"] = [0.5, 1.5, 2.5, 3.5]
        pattern["sub"] = [0.0, 1.5, 2.0, 3.5]
    elif name == "peak":
        pattern["kick"] = [0.0, 1.0, 2.0, 3.0]
        if rng.random() < 0.55:
            pattern["kick"].append([1.75, 2.75, 3.5][bar_index % 3])
        pattern["clap"] = [1.0, 3.0]
        pattern["hat"] = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
        pattern["openhat"] = [0.5, 1.5, 2.5, 3.5]
        pattern["sub"] = [0.0, 0.75, 1.5, 2.0, 2.75, 3.5]
    else:  # groove
        pattern["kick"] = [0.0, 1.0, 2.0, 3.0] if energy > 0.45 else [0.0, 2.0]
        pattern["clap"] = [1.0, 3.0] if energy > 0.4 else []
        pattern["hat"] = [0.5, 1.5, 2.5, 3.5]
        pattern["sub"] = [0.0, 1.5, 2.0, 3.5] if energy > 0.35 else [0.0, 2.0]

    return pattern


def _dedupe_hits(hits: list[Hit], threshold_s: float = 0.035) -> list[Hit]:
    hits.sort(key=lambda h: (h.time, h.instrument))
    result: list[Hit] = []
    last_time: dict[str, float] = {}
    for hit in hits:
        # Chord strums intentionally contain notes a few milliseconds apart.
        threshold = 0.004 if hit.instrument in {"guitar", "piano"} else threshold_s
        previous = last_time.get(hit.instrument)
        if previous is not None and hit.time - previous < threshold:
            continue
        if previous is None or hit.time > previous:
            last_time[hit.instrument] = hit.time
        result.append(hit)
    return result


def _ambient_bpm(detected: float) -> float:
    """Fold the detected tempo into a calm, cinematic range."""
    if detected <= 0:
        return 84.0
    return float(np.clip(detected * 0.66, 78.0, 92.0))


def _chord_for_time(t: float, beat: float, beat_offset: float):
    bar = int(max(0.0, (t - beat_offset)) // max(4 * beat, 1e-6))
    return AMBIENT_CHORDS[(bar // 4) % len(AMBIENT_CHORDS)]


def _select_accents(events: Iterable[FlightEvent]) -> list[FlightEvent]:
    candidates = sorted(events, key=lambda e: e.importance, reverse=True)
    kept: list[FlightEvent] = []
    for event in candidates:
        if event.kind == "flow":
            continue
        if any(abs(event.t_peak - other.t_peak) < 0.09 and other.kind != "flow" for other in kept):
            continue
        if len([o for o in kept if abs(o.t_peak - event.t_peak) < 0.45]) >= 3:
            continue
        kept.append(event)
    return sorted(kept, key=lambda e: e.t_peak)


def _pulse_hits(
    kept: list[FlightEvent],
    sections: list[Section],
    duration: float,
    beat: float,
    beat_offset: float,
    sound: SoundSettings,
) -> tuple[list[Hit], list[int]]:
    hits: list[Hit] = []
    bar_count = int(np.ceil((duration - beat_offset) / (4 * beat)))
    for bar in range(max(0, bar_count)):
        bar_start = beat_offset + bar * 4 * beat
        if bar_start >= duration:
            break
        section = _section_at(sections, bar_start + 2 * beat)
        energy = _energy_at(sections, bar_start + 2 * beat)
        name = section.name if section else "groove"
        pattern = _bar_pattern(bar, energy, name)
        root = BASS_PROGRESSION[bar % len(BASS_PROGRESSION)]

        for offset in pattern["kick"]:
            t = bar_start + offset * beat
            if 0 <= t < duration:
                velocity = 0.92 if offset == 0.0 else 0.72
                hits.append(Hit(t, "kick", velocity))
        for offset in pattern["clap"]:
            t = bar_start + offset * beat
            if 0 <= t < duration:
                hits.append(Hit(t, "clap", 0.55 + 0.3 * energy, pan=0.06))
        for i, offset in enumerate(pattern["hat"]):
            t = bar_start + offset * beat
            if 0 <= t < duration:
                velocity = 0.28 + 0.4 * energy
                pan = -0.28 if i % 2 else 0.28
                hits.append(Hit(t, "hat", velocity, pan=pan))
        for offset in pattern["openhat"]:
            t = bar_start + offset * beat
            if 0 <= t < duration:
                hits.append(Hit(t, "openhat", 0.3 + 0.2 * energy, pan=-0.15))
        for offset in pattern["sub"]:
            t = bar_start + offset * beat
            if 0 <= t < duration:
                note = root if offset == 0.0 else root + (12 if bar % 4 == 3 else 0)
                hits.append(
                    Hit(t, "sub", BASS_VELOCITY, note=float(note), duration=beat * 0.55)
                )

    used = [event.index for event in kept]
    for event in kept:
        t = float(np.clip(event.t_peak, 0.0, max(0.0, duration - 0.05)))
        importance = event.importance
        if event.kind == "switch":
            hits.append(Hit(t, "clap", 0.55 + 0.35 * event.score, pan=-0.12))
            hits.append(Hit(t, "hat", 0.45, pan=0.3))
            continue
        if event.kind in {"accel", "brake"}:
            for k in range(3):
                offset = 0.045 * (3 - k)
                if t - offset > 0:
                    hits.append(Hit(t - offset, "hat", 0.22 + 0.1 * k, pan=-0.35 + 0.2 * k))
            if event.kind == "accel":
                hits.append(Hit(t, "kick", 0.5 + 0.3 * event.score))
            continue

        accent = 0.55 + 0.45 * importance
        hits.append(Hit(t, "kick", accent))
        if importance >= 0.42:
            hits.append(Hit(t, "impact", 0.45 + 0.5 * importance))
        if event.kind in {"multirotation", "multiflip", "combo"} and event.score > 0.6:
            hits.append(Hit(t, "crash", 0.35 + 0.25 * event.score, pan=0.1))
        if event.kind == "spin":
            hits.append(Hit(t, "openhat", 0.4, pan=-0.2))

    for previous, following in zip(sections, sections[1:]):
        if following.energy - previous.energy > 0.3 and following.start > 1.0:
            hits.append(
                Hit(following.start - beat, "riser", 0.45, duration=beat * 0.9, pan=0.0)
            )
        if following.name == "break" and previous.name in {"peak", "groove"}:
            hits.append(Hit(following.start, "crash", 0.25, pan=-0.15))

    if duration > 2.0 and sections:
        last_figure = max(
            (h for h in hits if h.instrument == "kick"), key=lambda h: h.time, default=None
        )
        hits.append(Hit(duration - 1.2, "impact", 0.55))
        if last_figure and last_figure.time > duration - 3.0:
            hits.append(Hit(duration - 0.8, "crash", 0.3))

    for section in sections:
        if section.name in {"intro", "break"}:
            for offset in (0.0, 4.0):
                t = section.start + offset * beat
                if t < section.end and t < duration:
                    for note in (57, 60, 64):
                        hits.append(
                            Hit(
                                t,
                                "pad",
                                0.22,
                                note=float(note),
                                duration=min(4 * beat, section.end - t),
                            )
                        )
    return hits, used


def _strum(
    hits: list[Hit],
    t: float,
    notes: tuple[int, ...] | list[int],
    instrument: str,
    velocity: float,
    duration: float,
) -> None:
    """A short chord strum; guitar strings are spread like a real plectrum."""
    spread = 0.020 if instrument == "guitar" else 0.008
    for i, note in enumerate(notes):
        hits.append(
            Hit(
                t + spread * i,
                instrument,
                velocity * (1.0 - 0.10 * i),
                note=float(note),
                duration=duration,
                pan=-0.30 + 0.20 * i,
            )
        )


def _accent_chord(
    hits: list[Hit],
    t: float,
    notes,
    accent: str,
    velocity: float,
    duration: float,
) -> bool:
    if accent == "guitar":
        _strum(hits, t, notes, "guitar", velocity, duration)
    elif accent == "piano":
        _strum(hits, t, notes, "piano", velocity, duration * 0.9)
    elif accent == "marimba":
        _strum(hits, t, notes, "marimba", velocity, duration * 0.8)
    elif accent == "strings":
        _strum(hits, t, notes, "strings", velocity * 0.85, duration)
    elif accent == "synth":
        _strum(hits, t, notes, "synth", velocity * 0.9, duration * 0.75)
    else:
        return False
    return True


def _evasion_hits(
    kept: list[FlightEvent],
    sections: list[Section],
    duration: float,
    beat: float,
    beat_offset: float,
    sound: SoundSettings,
) -> tuple[list[Hit], list[int]]:
    """Ambient / cinematic arrangement: space, pads, arpeggios, tonal accents."""
    hits: list[Hit] = []
    used: list[int] = []
    density = float(np.clip(sound.density, 0.0, 1.2))
    bar_len = 4 * beat
    bar_count = max(0, int(np.ceil((duration - beat_offset) / bar_len)))

    for bar in range(bar_count):
        bar_start = beat_offset + bar * bar_len
        if bar_start >= duration:
            break
        section = _section_at(sections, bar_start + 2 * beat)
        name = section.name if section else "groove"
        energy = _energy_at(sections, bar_start + 2 * beat)
        root, pad_notes, arp_notes = AMBIENT_CHORDS[(bar // 4) % len(AMBIENT_CHORDS)]

        if bar % 4 == 0:
            chord_duration = max(beat, min(4 * bar_len + beat, duration - bar_start))
            for i, note in enumerate(pad_notes):
                hits.append(
                    Hit(
                        bar_start,
                        "pad_warm",
                        0.30 + 0.22 * energy,
                        note=float(note),
                        duration=chord_duration,
                        pan=-0.42 + 0.28 * i,
                    )
                )
            hits.append(
                Hit(
                    bar_start,
                    "drone",
                    0.34 + 0.15 * energy,
                    note=float(root),
                    duration=chord_duration,
                )
            )

        pattern = (0, 2, 1, 3, 2, 0, 1, 2) if bar % 2 else (0, 1, 2, 3, 2, 1, 3, 2)
        for step in range(8):
            t = bar_start + step * beat * 0.5
            if t >= duration:
                break
            if name in {"intro", "break"} and step % 4 != 0:
                continue
            if density < 0.5 and step % 2 == 1:
                continue
            if energy < 0.32 and step % 2 == 1:
                continue
            note = arp_notes[pattern[step] % len(arp_notes)]
            velocity = (0.13 + 0.20 * energy + (0.05 if step % 2 == 0 else 0.0)) * (
                0.65 + 0.55 * density
            )
            hits.append(
                Hit(
                    t,
                    "arp",
                    velocity,
                    note=float(note),
                    duration=beat * 0.95,
                    pan=-0.32 if step % 2 else 0.32,
                )
            )

        if name not in {"intro", "break"}:
            hits.append(Hit(bar_start, "softkick", 0.42 + 0.18 * energy))
            if energy > 0.48 and density >= 0.40 and bar_start + 2 * beat < duration:
                hits.append(Hit(bar_start + 2 * beat, "softkick", 0.34 + 0.16 * energy))
            if energy > 0.72 and density >= 0.70 and bar_start + 3.5 * beat < duration:
                hits.append(Hit(bar_start + 3.5 * beat, "softkick", 0.28 + 0.12 * energy))
        if name not in {"intro", "break"} and energy > 0.22 and density >= 0.30:
            tick_steps = (
                (1, 3, 5, 7) if (name == "peak" and density >= 0.80) else (3, 7)
            )
            for step in tick_steps:
                t = bar_start + step * beat * 0.5
                if t >= duration:
                    continue
                hits.append(
                    Hit(t, "tick", 0.10 + 0.10 * energy, pan=0.45 if step % 4 == 1 else -0.45)
                )
        if name == "peak" and bar % 4 == 0:
            hits.append(Hit(bar_start, "sub", 0.28, note=float(root + 12), duration=beat * 1.6))

    for event in kept:
        t = float(np.clip(event.t_peak, 0.0, max(0.0, duration - 0.05)))
        _, chord_notes, arp_notes = _chord_for_time(t, beat, beat_offset)
        note = float(arp_notes[(event.axis + 1 + event.index) % len(arp_notes)])
        used.append(event.index)
        importance = event.importance

        if event.kind == "switch":
            for k in range(3):
                tt = t - 0.07 * (3 - k)
                if tt >= 0:
                    hits.append(Hit(tt, "tick", 0.18 + 0.05 * k, pan=-0.3 + 0.15 * k))
            if not _accent_chord(
                hits, t, chord_notes[1:3], sound.accent, 0.22 + 0.16 * event.score, 1.6
            ):
                hits.append(
                    Hit(t, "bell", 0.18 + 0.18 * event.score, note=note, duration=1.4, pan=0.12)
                )
            continue
        if event.kind in {"accel", "brake"}:
            hits.append(Hit(max(0.0, t - 1.0), "swell", 0.30, duration=1.0, pan=-0.1))
            if event.kind == "accel":
                if sound.accent != "bell":
                    hits.append(
                        Hit(
                            t,
                            sound.accent,
                            0.20,
                            note=float(chord_notes[0]),
                            duration=1.8,
                            pan=0.25,
                        )
                    )
                else:
                    hits.append(Hit(t, "tick", 0.22, pan=0.3))
            continue

        if not _accent_chord(
            hits, t, chord_notes, sound.accent, 0.30 + 0.34 * importance, 2.8
        ):
            hits.append(
                Hit(
                    t,
                    "bell",
                    0.22 + 0.30 * importance,
                    note=note,
                    duration=1.6,
                    pan=0.15 if event.axis == 0 else -0.15,
                )
            )
        if importance >= 0.45 or event.kind in {
            "flip",
            "roll360",
            "inversion",
            "combo",
            "multirotation",
            "spin",
        }:
            hits.append(Hit(t, "boom", 0.40 + 0.40 * importance))
        if event.score >= 0.82 and sound.brightness > 0.55:
            hits.append(Hit(t, "shimmer", 0.10 + 0.12 * event.score))

    for previous, following in zip(sections, sections[1:]):
        if following.energy - previous.energy > 0.22 and following.start > 1.5:
            hits.append(Hit(max(0.0, following.start - 1.8), "swell", 0.32, duration=1.8))
        if previous.energy - following.energy > 0.30 and following.start > 1.0:
            hits.append(Hit(following.start, "boom", 0.30))

    if duration > 3.0:
        end = max(0.0, duration - 2.8)
        hits.append(Hit(end, "boom", 0.40))
        for i, note in enumerate(AMBIENT_CHORDS[0][1]):
            hits.append(
                Hit(
                    max(0.0, end - 0.6),
                    "pad_warm",
                    0.30,
                    note=float(note),
                    duration=max(1.0, duration - (end - 0.6)),
                    pan=-0.3 + 0.2 * i,
                )
            )
    return hits, sorted(set(used))


def manual_accent_hits(
    accents: Iterable[ManualAccent],
    tracks: Iterable[ManualTrack] | None,
    duration: float,
) -> list[Hit]:
    """Turn user markers into hits, skipping muted tracks."""
    track_list = list(tracks or [])
    hits: list[Hit] = []
    for accent in accents:
        lane = int(accent.lane)
        if lane < 0 or lane >= len(track_list):
            continue
        track = track_list[lane]
        if not track.enabled:
            continue
        instrument = track.sound
        if instrument not in MANUAL_SOUND_LABELS:
            instrument = "kick"
        time = float(np.clip(accent.time, 0.0, max(0.0, duration - 0.01)))
        note_index = lane % len(MANUAL_LANE_NOTES)
        if instrument in MANUAL_MELODIC:
            hits.append(
                Hit(
                    time,
                    instrument,
                    0.50,
                    note=float(MANUAL_LANE_NOTES[note_index]),
                    duration=1.8,
                    pan=MANUAL_LANE_PANS[note_index],
                    manual=True,
                )
            )
        else:
            hits.append(
                Hit(
                    time,
                    instrument,
                    0.78 if instrument in {"kick", "impact"} else 0.58,
                    pan=MANUAL_LANE_PANS[note_index] * 0.6,
                    manual=True,
                )
            )
    return hits


def build_plan(
    events: Iterable[FlightEvent],
    *,
    duration: float,
    activity: np.ndarray,
    activity_t: np.ndarray,
    sensitivity: float = 0.5,
    bpm: float | None = None,
    beat_offset: float | None = None,
    offset: float = 0.0,
    style: str = "evasion",
    sound: SoundSettings | None = None,
    manual_accents: Iterable[ManualAccent] | None = None,
    manual_tracks: Iterable[ManualTrack] | None = None,
) -> RhythmPlan:
    if style not in STYLE_LABELS:
        style = "evasion"
    sound = sound or SoundSettings()
    events = [
        replace(
            event,
            t_start=event.t_start + offset,
            t_peak=event.t_peak + offset,
            t_end=event.t_end + offset,
        )
        for event in events
    ]
    detected_bpm, detected_offset = estimate_tempo(events, duration)
    if bpm is None:
        bpm = _ambient_bpm(detected_bpm) if style == "evasion" else detected_bpm
    if beat_offset is None:
        beat_offset = 0.0 if style == "evasion" else detected_offset
    assert bpm is not None and beat_offset is not None

    beat = 60.0 / bpm
    sections = build_sections(activity, activity_t + offset, duration, beat, events)
    kept = _select_accents(events)
    if style == "evasion":
        hits, used = _evasion_hits(kept, sections, duration, beat, beat_offset, sound)
    else:
        hits, used = _pulse_hits(kept, sections, duration, beat, beat_offset, sound)

    hits = _dedupe_hits(hits)
    # Manual markers are authoritative: add them after de-duplication so a
    # user-placed accent is never swallowed by an automatic hit.
    hits.extend(manual_accent_hits(manual_accents or [], manual_tracks, duration))
    hits.sort(key=lambda h: h.time)
    return RhythmPlan(
        bpm=float(bpm),
        beat_offset=float(beat_offset),
        duration=float(duration),
        sections=sections,
        hits=hits,
        used_events=sorted(set(used)),
        sensitivity=sensitivity,
        style=style,
        sound=sound,
    )


def plan_summary(plan: RhythmPlan) -> dict:
    counts: dict[str, int] = {}
    for hit in plan.hits:
        counts[hit.instrument] = counts.get(hit.instrument, 0) + 1
    accents = counts.get("boom", 0) + counts.get("impact", 0)
    return {
        "bpm": round(plan.bpm, 1),
        "style": plan.style,
        "hits": len(plan.hits),
        "accents": accents,
        "sections": len(plan.sections),
        "by_instrument": counts,
    }
