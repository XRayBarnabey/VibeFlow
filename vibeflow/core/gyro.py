"""Gyroscope import for VibeFlow.

Supported inputs
----------------
* Gyroflow ``.gcsv`` logs (the reference format for FPV cameras).
* Generic CSV / TXT logs with a timestamp column and three gyro columns.
  Column names are matched loosely (``t``, ``time``, ``timestamp`` /
  ``gx``, ``gyro_x``, ``gyroX`` ...).
* Plain whitespace separated logs with 4 numeric columns.

The loader never assumes a sampling rate: the real rate is derived from the
timestamps. Irregular logging, gaps and non monotonic timestamps are reported
through :attr:`GyroTrack.warnings` so the UI can flag them.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

GCSV_MAGIC = ("GYROFLOW IMU LOG", "CAMERA IMU LOG")

# Mapping of common column names to internal names.
_COLUMN_ALIASES = {
    "t": "t",
    "time": "t",
    "timestamp": "t",
    "time_s": "t",
    "time(ms)": "t_ms",
    "time_ms": "t_ms",
    "gyro_x": "gx",
    "gyrox": "gx",
    "gx": "gx",
    "gyro_y": "gy",
    "gyroy": "gy",
    "gy": "gy",
    "gyro_z": "gz",
    "gyroz": "gz",
    "gz": "gz",
}


class GyroFormatError(ValueError):
    """Raised when a gyro log cannot be interpreted."""


@dataclass
class GyroTrack:
    """Uniformly sampled angular rates plus provenance metadata."""

    t: np.ndarray  # seconds, starting at 0
    rates: np.ndarray  # (N, 3) rad/s in roll, pitch, yaw order
    sample_rate: float  # Hz measured from timestamps
    source: Path | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    raw_rate_hz: float = 0.0
    irregular: float = 0.0  # coefficient of variation of sample intervals
    gap_count: int = 0
    unit: str = "rad/s"

    @property
    def duration(self) -> float:
        return float(self.t[-1]) if len(self.t) else 0.0

    @property
    def n_samples(self) -> int:
        return int(self.rates.shape[0])

    def copy_with_rates(self, rates: np.ndarray) -> "GyroTrack":
        return GyroTrack(
            t=self.t.copy(),
            rates=np.asarray(rates, dtype=np.float64),
            sample_rate=self.sample_rate,
            source=self.source,
            metadata=dict(self.metadata),
            warnings=list(self.warnings),
            raw_rate_hz=self.raw_rate_hz,
            irregular=self.irregular,
            gap_count=self.gap_count,
            unit=self.unit,
        )

    def envelope(self, lowpass_hz: float = 12.0) -> np.ndarray:
        """Smoothed magnitude of the angular velocity (deg/s)."""
        from .dsp import lowpass

        speed = np.degrees(np.linalg.norm(self.rates, axis=1))
        return lowpass(speed, self.sample_rate, lowpass_hz)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_float(value: str) -> float:
    return float(value.strip().replace(",", "."))


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _is_gcsv(text: str) -> bool:
    first = text.lstrip().splitlines()[0].strip().upper() if text.strip() else ""
    return any(first.startswith(magic) for magic in GCSV_MAGIC)


def _detect_delimiter(line: str) -> str:
    for delimiter in (",", ";", "\t"):
        if delimiter in line:
            return delimiter
    return ","


def _uniformise(
    t: np.ndarray,
    rates: np.ndarray,
    *,
    source: Path | None,
    metadata: dict[str, str],
    unit: str,
    warnings: list[str],
    max_rate_hz: float = 1000.0,
) -> GyroTrack:
    """Sort samples, remove duplicates and resample on a uniform grid."""
    if len(t) < 8:
        raise GyroFormatError("Le fichier gyroscopique contient trop peu d'échantillons.")

    order = np.argsort(t, kind="stable")
    t = t[order]
    rates = rates[order]

    # Drop duplicated timestamps (last value wins).
    keep = np.ones(len(t), dtype=bool)
    keep[1:] = np.diff(t) > 0
    t = t[keep]
    rates = rates[keep]

    diffs = np.diff(t)
    if len(diffs) < 4:
        raise GyroFormatError("Horodatages gyroscopiques inexploitables.")

    median_dt = float(np.median(diffs))
    if not math.isfinite(median_dt) or median_dt <= 0:
        raise GyroFormatError("Horodatages gyroscopiques non croissants.")
    raw_rate = 1.0 / median_dt
    if raw_rate > max_rate_hz * 1.5:
        # Timestamps likely in microseconds: 1e6 factor.
        if 1e6 / raw_rate <= max_rate_hz * 1.5:
            t = t / 1e6
            median_dt = float(np.median(np.diff(t)))
            raw_rate = 1.0 / median_dt
            warnings.append("Horodatages interprétés en microsecondes.")
        else:
            warnings.append(
                f"Fréquence gyroscopique inhabituelle ({raw_rate:.0f} Hz) : données conservées telles quelles."
            )

    # Uniform grid: 400 Hz by default, never above twice the native rate.
    target_fs = min(400.0, max(100.0, raw_rate))
    duration = float(t[-1] - t[0])
    if duration <= 0:
        raise GyroFormatError("Durée gyroscopique nulle.")
    n = int(round(duration * target_fs)) + 1
    t_uniform = np.linspace(t[0], t[-1], n) - t[0]
    t_rel = t - t[0]

    invalid = np.zeros(t_uniform.shape, dtype=bool)
    uniform = np.empty((t_uniform.size, 3), dtype=np.float64)
    for axis in range(3):
        uniform[:, axis] = np.interp(t_uniform, t_rel, rates[:, axis])
    rates = uniform

    # Gap analysis on the native timeline.
    gap_threshold = median_dt * 6.0
    gaps = np.flatnonzero(diffs > gap_threshold)
    gap_count = int(len(gaps))
    if gap_count:
        warnings.append(
            f"{gap_count} interruption(s) de journalisation détectée(s) "
            f"(jusqu'à {np.max(diffs) * 1000:.0f} ms)."
        )
    # Mark resampled regions covering long gaps as invalid (no invented motion).
    for idx in gaps:
        start = t_rel[idx]
        end = t_rel[idx + 1]
        invalid |= (t_uniform > start) & (t_uniform < end)

    irregular = float(np.std(diffs) / median_dt) if len(diffs) else 0.0
    if irregular > 0.35:
        warnings.append(
            "Cadence gyroscopique irrégulière : les timestamps ont été respectés, "
            "mais la qualité de synchronisation peut varier."
        )

    if unit == "deg/s":
        rates = np.radians(rates)
    elif unit != "rad/s":
        warnings.append(f"Unité gyroscopique inconnue ({unit}); valeurs supposées en rad/s.")

    # Basic sanity check: 30 rad/s ~= 1719 deg/s, beyond any FPV quad.
    peak = float(np.nanmax(np.abs(rates))) if rates.size else 0.0
    if peak > 40.0:
        warnings.append(
            f"Vitesses angulaires extrêmes ({peak:.0f} rad/s) : vérifiez l'échelle (gscale)."
        )

    # Fill invalid samples for downstream processing but keep the marker.
    if invalid.any():
        idx = np.arange(len(t_uniform))
        for axis in range(3):
            rates[invalid, axis] = np.interp(idx[invalid], idx[~invalid], rates[~invalid, axis])
        metadata["invalid_samples"] = str(int(invalid.sum()))

    return GyroTrack(
        t=t_uniform,
        rates=rates,
        sample_rate=target_fs,
        source=source,
        metadata=metadata,
        warnings=warnings,
        raw_rate_hz=raw_rate,
        irregular=irregular,
        gap_count=gap_count,
        unit="rad/s",
    )


def _looks_like_degrees(raw: np.ndarray, declared: str | None) -> bool:
    if declared:
        declared = declared.lower()
        if "deg" in declared or "dps" in declared:
            return True
        if "rad" in declared:
            return False
    return float(np.nanpercentile(np.abs(raw), 99.5)) > 25.0


def load_gcsv(text: str, source: Path | None = None) -> GyroTrack:
    lines = [line for line in text.splitlines()]
    meta: dict[str, str] = {}
    data_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("t,") or stripped.lower().startswith("t;"):
            data_start = i + 1
            break
        if "," in stripped:
            key, _, value = stripped.partition(",")
            meta[key.strip().lower()] = value.strip()

    if data_start is None:
        raise GyroFormatError("En-tête CSV introuvable dans le fichier GCSV.")

    tscale = float(meta.get("tscale", "1") or 1)
    gscale = meta.get("gscale")
    warnings: list[str] = []
    if gscale is None:
        warnings.append("gscale absent : échelle gyroscopique estimée automatiquement.")
    gscale_value = float(gscale) if gscale else None

    rows: list[tuple[float, float, float, float]] = []
    reader = csv.reader(io.StringIO("\n".join(lines[data_start:])), delimiter=_delimiter_for(lines[data_start - 1]))
    for row in reader:
        if len(row) < 4:
            continue
        try:
            rows.append(
                (
                    _parse_float(row[0]) * tscale,
                    _parse_float(row[1]),
                    _parse_float(row[2]),
                    _parse_float(row[3]),
                )
            )
        except ValueError:
            continue
    if not rows:
        raise GyroFormatError("Aucune donnée gyroscopique valide dans le fichier.")

    arr = np.asarray(rows, dtype=np.float64)
    t = arr[:, 0]
    raw = arr[:, 1:4]

    declared_unit = meta.get("gyro_unit") or meta.get("unit")
    if gscale_value is not None:
        raw = raw * gscale_value
        unit = "rad/s"
    else:
        unit = "deg/s" if _looks_like_degrees(raw, declared_unit) else "rad/s"

    meta_clean = {k: v for k, v in meta.items() if k not in {"t", "gx", "gy", "gz"}}
    return _uniformise(
        t,
        raw,
        source=source,
        metadata=meta_clean,
        unit=unit,
        warnings=warnings,
    )


def _delimiter_for(header_line: str) -> str:
    return _detect_delimiter(header_line)


def load_generic(text: str, source: Path | None = None) -> GyroTrack:
    stripped = "\n".join(line for line in text.splitlines() if line.strip())
    if not stripped:
        raise GyroFormatError("Fichier gyroscopique vide.")

    lines = stripped.splitlines()
    # Locate the header row: first line containing at least three known aliases.
    header_index = None
    header_fields: list[str] = []
    for i, line in enumerate(lines[:40]):
        delimiter = _detect_delimiter(line)
        fields = [f.strip().strip('"').lower() for f in line.split(delimiter)]
        known = sum(1 for f in fields if f in _COLUMN_ALIASES)
        if known >= 4:
            header_index = i
            header_fields = fields
            break

    warnings: list[str] = []
    if header_index is None:
        # Whitespace / delimiter separated numeric table without header.
        rows = []
        for line in lines:
            parts = re.split(r"[,\s;]+", line.strip())
            try:
                values = [_parse_float(p) for p in parts if p != ""]
            except ValueError:
                continue
            if len(values) >= 4:
                rows.append(values[:4])
        if len(rows) < 8:
            raise GyroFormatError(
                "Format gyroscopique non reconnu. Utilisez un fichier GCSV ou un CSV "
                "contenant temps + trois axes gyroscopiques."
            )
        arr = np.asarray(rows, dtype=np.float64)
        t = arr[:, 0]
        raw = arr[:, 1:4]
        warnings.append("Fichier sans en-tête : colonnes supposées t, gx, gy, gz.")
        if np.nanmedian(np.abs(np.diff(t))) > 0.5:
            warnings.append("Timestamps possiblement en millisecondes ; conversion appliquée.")
            t = t / 1000.0
        unit = "deg/s" if _looks_like_degrees(raw, None) else "rad/s"
        return _uniformise(t, raw, source=source, metadata={}, unit=unit, warnings=warnings)

    delimiter = _detect_delimiter(lines[header_index])
    rows = []
    for line in lines[header_index + 1 :]:
        parts = [p.strip() for p in line.split(delimiter)]
        if len(parts) < len(header_fields):
            continue
        try:
            rows.append([_parse_float(p) for p in parts[: len(header_fields)]])
        except ValueError:
            continue
    if len(rows) < 8:
        raise GyroFormatError("Aucune donnée exploitable sous l'en-tête CSV.")

    arr = np.asarray(rows, dtype=np.float64)
    mapping = []
    for field in header_fields:
        mapping.append(_COLUMN_ALIASES.get(field))
    if "t" not in mapping or "t_ms" not in mapping:
        if "t" not in mapping and "t_ms" not in mapping:
            raise GyroFormatError("Colonne de temps (t/time/timestamp) introuvable.")
    for axis in ("gx", "gy", "gz"):
        if axis not in mapping:
            raise GyroFormatError(f"Colonne {axis} introuvable dans le fichier gyroscopique.")

    def column(name: str) -> np.ndarray:
        return arr[:, mapping.index(name)]

    if "t" in mapping:
        t = column("t")
    else:
        t = column("t_ms") / 1000.0

    raw = np.column_stack([column("gx"), column("gy"), column("gz")])
    unit = "deg/s" if _looks_like_degrees(raw, None) else "rad/s"
    if np.nanmedian(np.abs(np.diff(t))) > 0.5:
        warnings.append("Timestamps convertis de millisecondes en secondes.")
        t = t / 1000.0

    return _uniformise(
        t,
        raw,
        source=source,
        metadata={"header": delimiter.join(header_fields)},
        unit=unit,
        warnings=warnings,
    )


def load_gyro(path: str | Path) -> GyroTrack:
    """Load a gyro log, auto-detecting GCSV vs generic CSV."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    text = _read_text(path)
    if _is_gcsv(text):
        track = load_gcsv(text, source=path)
    else:
        track = load_generic(text, source=path)
    return track


def gyro_axis_labels(track: GyroTrack) -> tuple[str, str, str]:
    """Human readable axis labels, respecting the GCSV orientation hint."""
    orientation = track.metadata.get("orientation", "").strip()
    if len(orientation) == 3 and all(c.upper() in "XYZ" for c in orientation):
        axes = []
        for char in orientation:
            axes.append({"X": "Roll", "Y": "Pitch", "Z": "Yaw"}[char.upper()])
        return tuple(axes)  # type: ignore[return-value]
    return ("Roll", "Pitch", "Yaw")


def load_gyro_columns(
    path: str | Path, time_column: str, columns: Iterable[str], unit: str = "rad/s"
) -> GyroTrack:
    """Minimal helper used by tests and custom importers."""
    path = Path(path)
    text = _read_text(path)
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            rows.append(
                [
                    float(row[time_column]),
                    float(row[list(columns)[0]]),
                    float(row[list(columns)[1]]),
                    float(row[list(columns)[2]]),
                ]
            )
        except (KeyError, ValueError):
            continue
    arr = np.asarray(rows, dtype=np.float64)
    return _uniformise(
        arr[:, 0],
        arr[:, 1:4],
        source=path,
        metadata={},
        unit=unit,
        warnings=[],
    )
