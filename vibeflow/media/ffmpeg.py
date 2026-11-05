"""FFmpeg helpers: binary discovery, probing, muxing and export."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class FFmpegNotFound(RuntimeError):
    pass


def _candidates(name: str) -> list[str]:
    exe = f"{name}.exe" if sys.platform == "win32" else name
    paths = [shutil.which(name) or ""]
    if sys.platform == "win32":
        paths += [
            str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / exe),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / exe),
            rf"C:\ffmpeg\bin\{exe}",
        ]
    return [p for p in paths if p]


def find_ffmpeg() -> str:
    for candidate in _candidates("ffmpeg"):
        if candidate and Path(candidate).exists():
            return candidate
    raise FFmpegNotFound(
        "FFmpeg est introuvable. Installez FFmpeg et ajoutez-le au PATH, "
        "puis relancez VibeFlow."
    )


def find_ffprobe() -> str:
    # ffprobe usually ships next to ffmpeg.
    ffmpeg = find_ffmpeg()
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if sibling.exists():
        return str(sibling)
    for candidate in _candidates("ffprobe"):
        if candidate and Path(candidate).exists():
            return candidate
    raise FFmpegNotFound("ffprobe est introuvable (il accompagne normalement FFmpeg).")


def run_hidden(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NO_WINDOW,
        timeout=timeout,
    )


def popen_hidden(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NO_WINDOW,
    )


@dataclass
class VideoInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str = ""
    audio_codec: str | None = None
    has_audio: bool = False
    rotation: int = 0
    creation_time: str | None = None
    bitrate: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return int(round(self.duration * self.fps)) if self.fps else 0

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 16 / 9

    def resolution_label(self) -> str:
        if self.height >= 2000:
            label = "4K"
        elif self.height >= 1400:
            label = "2.7K"
        elif self.height >= 1000:
            label = "1440p"
        elif self.height >= 700:
            label = "1080p"
        else:
            label = f"{self.height}p"
        return f"{label} · {self.width}×{self.height}"


def probe_video(path: str | Path) -> VideoInfo:
    path = Path(path)
    ffprobe = find_ffprobe()
    result = run_hidden(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Impossible de lire la vidéo : {result.stderr.decode(errors='replace')[-400:]}")
    data = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("Le fichier ne contient aucune piste vidéo.")

    fps = 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = video.get(key, "0/0")
        try:
            num, den = value.split("/")
            if float(den) != 0:
                fps = float(num) / float(den)
                if fps > 1:
                    break
        except (ValueError, ZeroDivisionError):
            continue
    if fps <= 0:
        fps = 30.0

    rotation = 0
    for side_data in video.get("side_data_list", []) or []:
        if "rotation" in side_data:
            try:
                rotation = int(float(side_data["rotation"]))
            except (TypeError, ValueError):
                pass
    try:
        rotation = int(video.get("tags", {}).get("rotate", rotation))
    except (TypeError, ValueError):
        pass
    rotation %= 360

    duration = 0.0
    for source in (video.get("duration"), data.get("format", {}).get("duration")):
        try:
            duration = float(source)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    if duration <= 0:
        raise RuntimeError("Durée vidéo inconnue : fichier corrompu ou non pris en charge.")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if rotation in (90, 270):
        width, height = height, width

    warnings: list[str] = []
    if fps and abs(fps - round(fps)) > 0.01 and abs(fps * 1001 / 1000 - round(fps)) > 0.01:
        warnings.append(f"Cadence vidéo variable ou inhabituelle ({fps:.2f} fps).")
    if duration < 1.0:
        warnings.append("Vidéo très courte.")

    format_tags = data.get("format", {}).get("tags", {})
    creation = format_tags.get("creation_time") or video.get("tags", {}).get("creation_time")

    return VideoInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video.get("codec_name", ""),
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        rotation=rotation,
        creation_time=creation,
        bitrate=int(float(data.get("format", {}).get("bit_rate") or 0)),
        warnings=warnings,
    )


def probe_audio_duration(path: str | Path) -> float:
    ffprobe = find_ffprobe()
    result = run_hidden(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        timeout=30,
    )
    try:
        return float(result.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def mux_preview(video: Path, audio: Path, output: Path, *, bitrate: str = "192k") -> Path:
    """Stream-copy the video and attach the generated track.

    Copying the video stream keeps the operation fast even for 4K footage and
    guarantees that video and audio share the same container timestamps, which
    is what makes QMediaPlayer playback perfectly synced.
    """
    ffmpeg = find_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]
    result = run_hidden(args, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            "Échec de la préparation de la préécoute : "
            + result.stderr.decode(errors="replace")[-500:]
        )
    return output


def export_audio(video: Path, audio: Path, output: Path, *, include_original: bool = False,
                 original_gain: float = 0.12) -> Path:
    """Export a video with the generated music (optionally blended with camera audio)."""
    ffmpeg = find_ffmpeg()
    info = probe_video(video)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-i", str(audio)]
    if include_original and info.has_audio:
        args += [
            "-filter_complex",
            f"[0:a]volume={original_gain}[orig];[1:a]volume=1.0[music];"
            f"[orig][music]amix=inputs=2:duration=longest:dropout_transition=0[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
        ]
    else:
        args += ["-map", "0:v:0", "-map", "1:a:0"]
    args += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]
    result = run_hidden(args, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(
            "Échec de l'export vidéo : " + result.stderr.decode(errors="replace")[-500:]
        )
    return output
