"""Generate a synthetic demo clip + gyro log to exercise VibeFlow end to end."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from vibeflow.media.ffmpeg import find_ffmpeg, run_hidden

VIDEO_FILTER = (
    "testsrc2=size=1280x720:rate=30:duration={duration},"
    "drawbox=x='mod(t*220,w)':y='h/2-40':w=80:h=80:color=#7FA7C9@0.7:t=fill"
)


def _add_rotation(rates: np.ndarray, fs: float, start: float, duration: float, axis: int, angle: float) -> None:
    t = np.arange(len(rates)) / fs
    mask = (t >= start) & (t < start + duration)
    local = t[mask] - start
    peak = angle * math.pi / (2 * duration)
    rates[mask, axis] += peak * np.sin(math.pi * local / duration)


def build_gyro(duration: float, fs: float = 1000.0) -> np.ndarray:
    rates = np.zeros((int(duration * fs), 3))
    rng = np.random.default_rng(42)
    rates += rng.normal(0, 8.0, rates.shape)  # measured noise in deg/s
    moves = [
        (2.0, 0.6, 0, 360),
        (4.2, 0.5, 0, 180),
        (6.4, 0.7, 1, 330),
        (9.1, 0.45, 0, 200),
        (11.0, 0.8, 0, 540),
        (13.4, 0.55, 1, 360),
        (15.6, 0.9, 2, 420),
        (18.0, 0.6, 0, 250),
    ]
    for start, length, axis, angle in moves:
        _add_rotation(rates, fs, start, length, axis, angle)
    return rates


def write_gcsv(path: Path, rates_deg: np.ndarray, fs: float) -> None:
    gscale = math.radians(1.0) / 0.001
    lines = [
        "GYROFLOW IMU LOG",
        "version,1.3",
        "id,vibeflow_demo",
        "orientation,YxZ",
        "vendor,VibeFlow",
        "tscale,0.001",
        f"gscale,{gscale:.10f}",
        "t,gx,gy,gz",
    ]
    for i, (gx, gy, gz) in enumerate(rates_deg):
        raw = np.radians([gx, gy, gz]) / gscale
        lines.append(f"{i},{raw[0]:.3f},{raw[1]:.3f},{raw[2]:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="demo")
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args()

    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / "demo_flight.mp4"
    gyro = directory / "demo_flight.gcsv"

    ffmpeg = find_ffmpeg()
    result = run_hidden(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            VIDEO_FILTER.format(duration=args.duration),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ],
        timeout=300,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode(errors="replace"))

    write_gcsv(gyro, build_gyro(args.duration), 1000.0)
    print(f"Video: {video}\nGyro : {gyro}")


if __name__ == "__main__":
    main()
