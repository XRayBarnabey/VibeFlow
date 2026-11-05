"""Project state and end-to-end pipeline orchestration."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

from ..media.ffmpeg import (
    VideoInfo,
    export_audio,
    mux_preview,
    probe_video,
)
from ..providers.acestep import ACEStepClient, ACEStepRequest
from .analysis import AnalysisConfig, FlightAnalysis, analyse, filter_by_sensitivity
from .gyro import GyroTrack, load_gyro
from .rhythm import (
    MANUAL_COLORS,
    MANUAL_DEFAULT_KEYS,
    MANUAL_DEFAULT_SOUNDS,
    MANUAL_LANE_LABELS,
    ManualAccent,
    ManualTrack,
    RhythmPlan,
    SoundSettings,
    build_plan,
    default_manual_tracks,
    plan_summary,
)
from .synth import render_plan, write_wav
from .sync import SyncEstimate, estimate_offset, estimate_offset_from_metadata

ProgressFn = Callable[[str, float], None]

# Bump when synthesis changes so cached previews are not reused silently.
CACHE_VERSION = 5

DEFAULT_AI_PROMPT = (
    "cinematic ambient, felt piano, warm pads, soft sub bass, no drums, "
    "no vocals, spacious reverb, emotional, slow build, instrumental"
)

DEFAULT_STYLE_BPM = {"evasion": 84.0, "pulse": 127.0}


def _noop(message: str, progress: float = 0.0) -> None:
    pass


@dataclass
class Project:
    work_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "VibeFlow")
    video: VideoInfo | None = None
    gyro: GyroTrack | None = None
    analysis: FlightAnalysis | None = None
    sensitivity: float = 0.5
    offset: float = 0.0
    style: str = "evasion"
    sound: SoundSettings = field(default_factory=SoundSettings)
    ai_server: str = "http://127.0.0.1:8021"
    ai_prompt: str = DEFAULT_AI_PROMPT
    ai_mix_accents: bool = True
    ai_model: str | None = None
    ai_audio_path: Path | None = None
    music_source: str = "local"
    source_paths: dict[str, Path] = field(default_factory=dict)
    source_previews: dict[str, Path] = field(default_factory=dict)
    sync_estimate: SyncEstimate | None = None
    plan: RhythmPlan | None = None
    audio_path: Path | None = None
    preview_path: Path | None = None
    disabled_events: set[int] = field(default_factory=set)
    bpm_override: float | None = None
    analysis_config: AnalysisConfig = field(default_factory=AnalysisConfig)
    manual_accents: list[ManualAccent] = field(default_factory=list)
    manual_tracks: list[ManualTrack] = field(default_factory=default_manual_tracks)
    manual_move_left_key: str = "Shift+Left"
    manual_move_right_key: str = "Shift+Right"
    manual_move_step_ms: int = 50

    # ------------------------------------------------------------------ load
    def load_video(self, path: str | Path) -> VideoInfo:
        info = probe_video(path)
        self.video = info
        self.preview_path = None
        self.ai_audio_path = None
        self.music_source = "local"
        self.source_paths.clear()
        self.source_previews.clear()
        self.manual_accents.clear()
        return info

    def load_gyro(self, path: str | Path) -> GyroTrack:
        track = load_gyro(path)
        self.gyro = track
        self.analysis = None
        self.plan = None
        self.preview_path = None
        self.source_paths.clear()
        self.source_previews.clear()
        return track

    def suggested_offset(self) -> SyncEstimate | None:
        """Estimate sync without modifying the project offset."""
        if not self.video or not self.gyro:
            return None
        metadata = estimate_offset_from_metadata(self.video.path, self.gyro)
        try:
            motion = estimate_offset(self.video.path, self.gyro)
        except Exception as exc:  # extraction can fail on exotic codecs
            if metadata:
                metadata.note += f" (corrélation indisponible : {exc})"
                return metadata
            raise
        if metadata and not motion.is_reliable:
            metadata.note += " Corrélation visuelle peu fiable."
            return metadata
        return motion

    # --------------------------------------------------------------- analyse
    def run_analysis(self, progress: ProgressFn = _noop) -> FlightAnalysis:
        if self.gyro is None:
            raise RuntimeError("Aucune donnée gyroscopique importée.")
        progress("Analyse du pilotage…", 0.2)
        analysis = analyse(self.gyro, self.analysis_config)
        progress("Classification des figures…", 0.8)
        self.analysis = analysis
        self.plan = None
        progress("Analyse terminée.", 1.0)
        return analysis

    def visible_events(self, sensitivity: float | None = None) -> list[FlightEvent]:
        return [event for event in self.candidates(sensitivity) if event.enabled]

    def candidates(self, sensitivity: float | None = None) -> list[FlightEvent]:
        """Events passing the sensitivity threshold, disabled ones included."""
        if self.analysis is None:
            return []
        sensitivity = self.sensitivity if sensitivity is None else sensitivity
        events = filter_by_sensitivity(
            [replace(event, enabled=True) for event in self.analysis.events], sensitivity
        )
        for event in events:
            event.enabled = self.is_event_enabled(event.index)
        return events

    def set_event_enabled(self, index: int, enabled: bool) -> None:
        if enabled:
            self.disabled_events.discard(index)
        else:
            self.disabled_events.add(index)

    def is_event_enabled(self, index: int) -> bool:
        return index not in self.disabled_events

    # -------------------------------------------------------- manual accents
    def manual_duration(self) -> float:
        if self.video is not None:
            return self.video.duration
        if self.analysis is not None:
            return self.analysis.duration
        return 0.0

    def add_manual_accent(self, time: float, lane: int) -> ManualAccent | None:
        lane = int(lane)
        if lane < 0 or lane >= len(self.manual_tracks):
            return None
        limit = self.manual_duration()
        if limit > 0:
            time = min(float(time), max(0.0, limit - 0.01))
        time = max(0.0, float(time))
        # Replacing a marker at nearly the same instant keeps quick taps clean.
        for marker in self.manual_accents:
            if marker.lane == lane and abs(marker.time - time) < 0.035:
                marker.time = time
                return marker
        marker = ManualAccent(time=time, lane=lane)
        self.manual_accents.append(marker)
        self.manual_accents.sort(key=lambda item: item.time)
        return marker

    def pop_manual_accent(self) -> ManualAccent | None:
        if not self.manual_accents:
            return None
        return self.manual_accents.pop()

    def remove_manual_accent_at(self, index: int) -> ManualAccent | None:
        if not (0 <= index < len(self.manual_accents)):
            return None
        return self.manual_accents.pop(index)

    def remove_manual_accent_near(
        self, time: float, tolerance: float = 0.35
    ) -> ManualAccent | None:
        if not self.manual_accents:
            return None
        nearest = min(self.manual_accents, key=lambda item: abs(item.time - time))
        if abs(nearest.time - time) > tolerance:
            return None
        self.manual_accents.remove(nearest)
        return nearest

    def move_manual_accent(self, index: int, delta: float) -> int | None:
        if not (0 <= index < len(self.manual_accents)):
            return None
        marker = self.manual_accents[index]
        limit = self.manual_duration()
        value = marker.time + float(delta)
        if limit > 0:
            value = min(value, max(0.0, limit - 0.01))
        marker.time = max(0.0, value)
        self.manual_accents.sort(key=lambda item: item.time)
        return self.manual_accents.index(marker)

    def clear_manual_accents(self) -> None:
        self.manual_accents.clear()

    # ------------------------------------------------------------ manual tracks
    def add_manual_track(self, name: str | None = None) -> ManualTrack:
        index = len(self.manual_tracks)
        track = ManualTrack(
            name=name or f"Piste {index + 1}",
            key="",
            color=MANUAL_COLORS[index % len(MANUAL_COLORS)],
            sound=MANUAL_DEFAULT_SOUNDS[index % len(MANUAL_DEFAULT_SOUNDS)],
        )
        self.manual_tracks.append(track)
        return track

    def remove_manual_track(self, lane: int) -> bool:
        if not (0 <= lane < len(self.manual_tracks)):
            return False
        self.manual_tracks.pop(lane)
        self.manual_accents = [
            marker
            for marker in self.manual_accents
            if marker.lane != lane
        ]
        for marker in self.manual_accents:
            if marker.lane > lane:
                marker.lane -= 1
        return True

    def set_manual_track_sound(self, lane: int, sound: str) -> None:
        if 0 <= lane < len(self.manual_tracks):
            self.manual_tracks[lane].sound = sound

    def set_manual_track_key(self, lane: int, key: str) -> None:
        if 0 <= lane < len(self.manual_tracks):
            self.manual_tracks[lane].key = key

    def set_manual_track_color(self, lane: int, color: str) -> None:
        if 0 <= lane < len(self.manual_tracks):
            self.manual_tracks[lane].color = color

    def set_manual_track_enabled(self, lane: int, enabled: bool) -> None:
        if 0 <= lane < len(self.manual_tracks):
            self.manual_tracks[lane].enabled = bool(enabled)

    def set_manual_track_name(self, lane: int, name: str) -> None:
        if 0 <= lane < len(self.manual_tracks):
            self.manual_tracks[lane].name = name

    def manual_sounds(self) -> tuple[str, ...]:
        return tuple(track.sound for track in self.manual_tracks)

    def manual_keys(self) -> tuple[str, ...]:
        return tuple(track.key for track in self.manual_tracks)

    # ---------------------------------------------------------------- render
    def _cache_dir(self) -> Path:
        if not self.video:
            raise RuntimeError("Aucune vidéo importée.")
        signature = (
            f"{self.video.path}|{self.video.duration:.3f}|{self.offset:.4f}|"
            f"{self.sensitivity:.4f}|{self.style}|{self.sound}|"
            f"{[(t.name, t.sound, t.enabled) for t in self.manual_tracks]}|"
            f"{[(round(a.time, 3), a.lane) for a in self.manual_accents]}|"
            f"v{CACHE_VERSION}"
        )
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
        directory = self.work_dir / digest
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def generate(
        self,
        sensitivity: float | None = None,
        progress: ProgressFn = _noop,
        *,
        build_preview: bool = True,
    ) -> RhythmPlan:
        if self.video is None:
            raise RuntimeError("Aucune vidéo importée.")
        if self.analysis is None:
            raise RuntimeError("Lancez d'abord l'analyse du pilotage.")
        if sensitivity is not None:
            self.sensitivity = float(np.clip(sensitivity, 0.0, 1.0))

        progress("Sélection des événements…", 0.08)
        events = self.visible_events()
        duration = self.video.duration

        activity_t = self.analysis.activity_t
        activity = self.analysis.activity
        progress("Construction de la grille rythmique…", 0.22)
        plan = build_plan(
            events,
            duration=duration,
            activity=activity,
            activity_t=activity_t,
            sensitivity=self.sensitivity,
            bpm=self.bpm_override,
            beat_offset=None,
            offset=self.offset,
            style=self.style,
            sound=self.sound,
            manual_accents=self.manual_accents,
            manual_tracks=self.manual_tracks,
        )
        progress(f"Composition — {plan.bpm:.1f} BPM, {len(plan.hits)} frappes…", 0.42)

        directory = self._cache_dir()
        audio_path = directory / f"vibeflow_{self.style}_{self.sound.accent}_{int(self.sensitivity * 100):02d}.wav"
        audio = render_plan(plan)
        write_wav(audio_path, audio)
        progress("Rendu audio terminé.", 0.7)

        self.plan = plan
        self.audio_path = audio_path
        self.source_paths["local"] = audio_path
        if build_preview:
            progress("Préparation du lecteur synchronisé…", 0.78)
            self._preview_for_audio(audio_path, "local", progress)
            progress("Préécoute prête.", 1.0)
        else:
            progress("Prise audio prête.", 1.0)
        self.music_source = "local"
        return plan

    # ------------------------------------------------------------- ACE-Step
    def generate_ai(
        self,
        progress: ProgressFn = _noop,
        *,
        prompt: str | None = None,
        server: str | None = None,
        mix_accents: bool | None = None,
        bpm: float | None = None,
        thinking: bool = False,
    ):
        """Generate a music bed with the local ACE-Step server and load it."""
        if self.video is None:
            raise RuntimeError("Aucune vidéo importée.")
        if server:
            self.ai_server = server
        if prompt:
            self.ai_prompt = prompt
        base_prompt = (self.ai_prompt or DEFAULT_AI_PROMPT).strip()
        if mix_accents is None:
            mix_accents = self.ai_mix_accents
        if self.analysis is not None:
            progress("Préparation de la tempo map…", 0.02)
            self.generate(self.sensitivity, build_preview=False)
            target_bpm = bpm or self.plan.bpm
        elif mix_accents:
            raise RuntimeError(
                "Importez le gyroscope et lancez l'analyse pour synchroniser "
                "le rythme VibeFlow."
            )
        else:
            target_bpm = bpm or DEFAULT_STYLE_BPM.get(self.style, 84.0)
        sections = self.plan.sections if self.plan else []
        if mix_accents:
            base_prompt += (
                ", no drums, no percussion, no kick, no clap, no hi-hats, "
                "leave rhythmic space for the flight accents"
            )
        if sections:
            structure = "; ".join(
                f"{s.name} {s.start:.0f}-{s.end:.0f}s" for s in sections
            )
            full_prompt = f"{base_prompt}. Instrumental, no vocals. Structure: {structure}."
        else:
            full_prompt = f"{base_prompt}. Instrumental, no vocals."

        request = ACEStepRequest(
            prompt=full_prompt,
            duration=self.video.duration,
            bpm=target_bpm,
            key_scale="A minor",
            time_signature="4",
            thinking=thinking,
            model=self.ai_model,
        )
        client = ACEStepClient(self.ai_server)
        ai_dir = self.work_dir / "ai"
        ai_dir.mkdir(parents=True, exist_ok=True)
        (ai_dir / "last_request.json").write_text(
            json.dumps(
                {
                    "server": self.ai_server,
                    "payload": request.payload(),
                    "sent_bpm": target_bpm,
                    "sections": len(sections),
                    "rhythm_layer": bool(mix_accents),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        progress(
            f"ACE-Step : {self.video.duration:.0f} s · {target_bpm:.0f} BPM · "
            f"A minor · {len(sections)} sections",
            0.04,
        )
        raw_path = ai_dir / f"acestep_{time.time_ns()}.wav"
        progress("Connexion à ACE-Step…", 0.05)
        result = client.generate(
            request,
            raw_path,
            progress=progress,
            timeout=max(900.0, self.video.duration * 8.0),
        )

        self.source_paths["ai"] = raw_path
        self._preview_for_audio(raw_path, "ai", progress)

        hybrid_available = self.analysis is not None and self.plan is not None
        if hybrid_available:
            rhythm_path, rhythm_hits = self._render_rhythm_layer(progress)
            mixed_path = ai_dir / f"acestep_hybrid_{time.time_ns()}.wav"
            progress("Mixage : nappe ACE-Step + rythme VibeFlow…", 0.94)
            hybrid_path = self._mix_hybrid(
                raw_path, rhythm_path, mixed_path, rhythm_hits
            )
            self.source_paths["hybrid"] = hybrid_path
            self._preview_for_audio(hybrid_path, "hybrid", progress)

        self.ai_audio_path = raw_path
        self.ai_mix_accents = bool(mix_accents)
        self.music_source = "hybrid" if (mix_accents and hybrid_available) else "ai"
        self.preview_path = self.source_previews.get(self.music_source)
        progress("Piste ACE-Step prête.", 1.0)
        return result

    def set_music_source(self, source: str) -> Path | None:
        preview = self.source_previews.get(source)
        if preview is None or not preview.exists():
            return None
        self.music_source = source
        self.preview_path = preview
        return preview

    def _preview_for_audio(
        self, audio_path: Path, source: str = "local", progress: ProgressFn = _noop
    ) -> Path:
        if self.video is None:
            raise RuntimeError("Aucune vidéo importée.")
        directory = self._cache_dir()
        suffix = hashlib.sha1(f"{audio_path.stat().st_mtime_ns}".encode()).hexdigest()[:8]
        preview_path = directory / f"preview_{source}_{suffix}.mp4"
        progress("Préparation du lecteur synchronisé…", 0.96)
        mux_preview(self.video.path, audio_path, preview_path)
        self.source_previews[source] = preview_path
        self.preview_path = preview_path
        keep = {path.resolve() for path in self.source_previews.values()}
        for stale in directory.glob("preview_*.mp4"):
            if stale.resolve() not in keep:
                try:
                    stale.unlink()
                except OSError:
                    pass
        return preview_path

    def _render_rhythm_layer(self, progress: ProgressFn = _noop):
        """Render only the event-driven percussion, without pads/melody."""
        if self.analysis is None:
            raise RuntimeError("Analyse du pilotage requise pour le rythme VibeFlow.")
        if self.plan is None:
            raise RuntimeError("Aucun plan rythmique disponible.")
        progress("Rendu du rythme VibeFlow…", 0.9)
        rhythm_instruments = {
            "kick",
            "softkick",
            "sub",
            "hat",
            "openhat",
            "clap",
            "impact",
            "crash",
            "tick",
            "boom",
            "riser",
            "swell",
        }
        hits = [
            h
            for h in self.plan.hits
            if h.instrument in rhythm_instruments or h.manual
        ]
        subplan = replace(self.plan, hits=hits)
        path = self.work_dir / "ai" / f"rhythm_{time.time_ns()}.wav"
        write_wav(path, render_plan(subplan))
        return path, hits

    def _mix_hybrid(
        self,
        ai_path: Path,
        rhythm_path: Path,
        out_path: Path,
        rhythm_hits,
    ) -> Path:
        """ACE-Step harmonic bed + VibeFlow rhythm, with kick sidechain."""
        import soundfile as sf
        from scipy.signal import butter, sosfilt

        ai, ai_rate = sf.read(str(ai_path), always_2d=True, dtype="float32")
        rhythm, rhythm_rate = sf.read(str(rhythm_path), always_2d=True, dtype="float32")

        def prepare(data: np.ndarray, rate: int) -> np.ndarray:
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if rate != 48000:
                from scipy.signal import resample_poly

                data = resample_poly(data, 48000, rate, axis=0).astype(np.float32)
            return data

        ai = prepare(ai, ai_rate)
        rhythm = prepare(rhythm, rhythm_rate)
        length = max(len(ai), len(rhythm))
        bed = np.zeros((length, 2), dtype=np.float32)
        layer = np.zeros((length, 2), dtype=np.float32)
        bed[: len(ai)] += ai
        layer[: len(rhythm)] += rhythm

        # The local kick/sub owns the low end: clear room in the AI bed.
        highpass = butter(2, 80.0 / (48000 / 2), "high", output="sos")
        bed = sosfilt(highpass, bed, axis=0).astype(np.float32)

        # Duck the bed on every local kick/impact so the figure accents cut through.
        duck = np.ones(length, dtype=np.float32)
        release = int(0.24 * 48000)
        for hit in rhythm_hits:
            if hit.instrument not in {"kick", "softkick", "impact", "boom"}:
                continue
            start = int(hit.time * 48000)
            if start >= length:
                continue
            end = min(length, start + release)
            duck[start:end] = np.minimum(duck[start:end], 0.52)
        smoother = butter(2, 28.0 / (48000 / 2), "low", output="sos")
        duck = sosfilt(smoother, duck).astype(np.float32)
        duck = np.clip(duck, 0.45, 1.0)

        mixed = bed * duck[:, None] * 0.82 + layer * 0.95
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.95:
            mixed *= 0.95 / peak
        sf.write(str(out_path), mixed, 48000, subtype="PCM_16")
        return out_path

    def _mix_audio(
        self,
        ai_path: Path,
        local_path: Path,
        out_path: Path,
        local_gain: float = 0.30,
    ) -> Path:
        import soundfile as sf
        from scipy.signal import resample_poly

        ai, ai_rate = sf.read(str(ai_path), always_2d=True, dtype="float32")
        local, local_rate = sf.read(str(local_path), always_2d=True, dtype="float32")

        def prepare(data: np.ndarray, rate: int) -> np.ndarray:
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if rate != 48000:
                data = resample_poly(data, 48000, rate, axis=0).astype(np.float32)
            return data

        ai = prepare(ai, ai_rate)
        local = prepare(local, local_rate)
        length = max(len(ai), len(local))
        mixed = np.zeros((length, 2), dtype=np.float32)
        mixed[: len(ai)] += ai
        mixed[: len(local)] += local * float(np.clip(local_gain, 0.0, 1.0))
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 0.95:
            mixed *= 0.95 / peak
        sf.write(str(out_path), mixed, 48000, subtype="PCM_16")
        return out_path

    def active_audio_path(self) -> Path | None:
        path = self.source_paths.get(self.music_source)
        if path is not None and path.exists():
            return path
        if (
            self.music_source in {"ai", "hybrid"}
            and self.ai_audio_path is not None
            and self.ai_audio_path.exists()
        ):
            return self.ai_audio_path
        return self.audio_path

    def summary(self) -> dict:
        info = {
            "video": str(self.video.path) if self.video else None,
            "gyro": str(self.gyro.source) if self.gyro else None,
            "offset": round(self.offset, 3),
            "sensitivity": self.sensitivity,
            "style": self.style,
            "accent": self.sound.accent,
            "source": self.music_source,
            "events": len(self.visible_events()),
            "manual_accents": len(self.manual_accents),
        }
        if self.plan:
            info["rhythm"] = plan_summary(self.plan)
        return info

    # ---------------------------------------------------------------- export
    def export_wav(self, destination: str | Path) -> Path:
        audio = self.active_audio_path()
        if audio is None:
            raise RuntimeError("Générez d'abord la préécoute.")
        import shutil

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, destination)
        return destination

    def export_video(
        self,
        destination: str | Path,
        *,
        include_original_audio: bool = False,
        original_gain: float = 0.12,
        progress: ProgressFn = _noop,
    ) -> Path:
        if self.video is None or self.active_audio_path() is None:
            raise RuntimeError("Vidéo ou préécoute manquante.")
        progress("Export de la vidéo avec la musique…", 0.3)
        result = export_audio(
            self.video.path,
            self.active_audio_path(),
            Path(destination),
            include_original=include_original_audio,
            original_gain=original_gain,
        )
        progress("Export terminé.", 1.0)
        return result

    # ------------------------------------------------------------------ save
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        data = {
            "format": "vibeflow-project",
            "version": 1,
            "video": str(self.video.path) if self.video else None,
            "gyro": str(self.gyro.source) if self.gyro else None,
            "offset": self.offset,
            "sensitivity": self.sensitivity,
            "style": self.style,
            "sound": {
                "accent": self.sound.accent,
                "density": self.sound.density,
                "brightness": self.sound.brightness,
                "reverb": self.sound.reverb,
                "low_end": self.sound.low_end,
                "kit": self.sound.kit,
            },
            "ai_server": self.ai_server,
            "ai_prompt": self.ai_prompt,
            "ai_mix_accents": self.ai_mix_accents,
            "ai_model": self.ai_model,
            "bpm_override": self.bpm_override,
            "disabled_events": sorted(self.disabled_events),
            "manual_accents": [
                {"time": round(marker.time, 4), "lane": marker.lane}
                for marker in self.manual_accents
            ],
            "manual_tracks": [
                {
                    "name": track.name,
                    "key": track.key,
                    "color": track.color,
                    "sound": track.sound,
                    "enabled": track.enabled,
                }
                for track in self.manual_tracks
            ],
            "manual_move_left_key": self.manual_move_left_key,
            "manual_move_right_key": self.manual_move_right_key,
            "manual_move_step_ms": self.manual_move_step_ms,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load(
        self, path: str | Path, progress: ProgressFn = _noop, *, run_analysis: bool = True
    ) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != "vibeflow-project":
            raise ValueError("Fichier projet VibeFlow invalide.")
        if data.get("video"):
            progress("Chargement de la vidéo…", 0.15)
            self.load_video(data["video"])
        if data.get("gyro"):
            progress("Chargement du gyroscope…", 0.35)
            self.load_gyro(data["gyro"])
        self.offset = float(data.get("offset", 0.0))
        self.sensitivity = float(data.get("sensitivity", 0.5))
        self.style = data.get("style", "evasion")
        sound_data = data.get("sound") or {}
        self.sound = SoundSettings(
            accent=sound_data.get("accent", "guitar"),
            density=float(sound_data.get("density", 0.65)),
            brightness=float(sound_data.get("brightness", 0.60)),
            reverb=float(sound_data.get("reverb", 0.55)),
            low_end=float(sound_data.get("low_end", 0.50)),
            kit=sound_data.get("kit", "analog"),
        )
        self.bpm_override = data.get("bpm_override")
        self.ai_server = data.get("ai_server", "http://127.0.0.1:8021")
        self.ai_prompt = data.get("ai_prompt", DEFAULT_AI_PROMPT)
        self.ai_mix_accents = bool(data.get("ai_mix_accents", True))
        self.ai_model = data.get("ai_model")
        self.disabled_events = set(int(v) for v in data.get("disabled_events", []))
        track_data = data.get("manual_tracks")
        if isinstance(track_data, list) and track_data:
            tracks: list[ManualTrack] = []
            for index, item in enumerate(track_data):
                if not isinstance(item, dict):
                    continue
                tracks.append(
                    ManualTrack(
                        name=str(item.get("name") or f"Piste {index + 1}"),
                        key=str(item.get("key") or ""),
                        color=str(item.get("color") or MANUAL_COLORS[index % len(MANUAL_COLORS)]),
                        sound=str(
                            item.get("sound")
                            or MANUAL_DEFAULT_SOUNDS[index % len(MANUAL_DEFAULT_SOUNDS)]
                        ),
                        enabled=bool(item.get("enabled", True)),
                    )
                )
            self.manual_tracks = tracks or default_manual_tracks()
        else:
            # Migration from 0.8 projects: fixed four sound/key slots.
            sounds = data.get("manual_sounds") or MANUAL_DEFAULT_SOUNDS
            keys = data.get("manual_keys") or MANUAL_DEFAULT_KEYS
            sounds = (list(sounds) + list(MANUAL_DEFAULT_SOUNDS))[:4]
            keys = (list(keys) + list(MANUAL_DEFAULT_KEYS))[:4]
            self.manual_tracks = [
                ManualTrack(
                    name=MANUAL_LANE_LABELS[index],
                    key=str(keys[index] or MANUAL_DEFAULT_KEYS[index]),
                    color=MANUAL_COLORS[index],
                    sound=str(sounds[index] or MANUAL_DEFAULT_SOUNDS[index]),
                )
                for index in range(4)
            ]
        self.manual_accents = [
            ManualAccent(time=float(item.get("time", 0.0)), lane=int(item.get("lane", 0)))
            for item in data.get("manual_accents", [])
            if isinstance(item, dict)
            and 0 <= int(item.get("lane", 0)) < len(self.manual_tracks)
        ]
        self.manual_move_left_key = str(
            data.get("manual_move_left_key") or "Shift+Left"
        )
        self.manual_move_right_key = str(
            data.get("manual_move_right_key") or "Shift+Right"
        )
        try:
            self.manual_move_step_ms = max(
                1, min(10000, int(data.get("manual_move_step_ms", 50)))
            )
        except (TypeError, ValueError):
            self.manual_move_step_ms = 50
        if self.gyro is not None and run_analysis:
            progress("Analyse du pilotage…", 0.55)
            self.run_analysis(progress=lambda m, p: progress(m, 0.55 + p * 0.4))
