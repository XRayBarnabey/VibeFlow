"""Standalone ACE-Step backend manager for VibeFlow.

VibeFlow downloads the official portable ACE-Step package once, extracts it in
its own application-data folder, then starts/stops the REST server as a child
process. The ACE Music desktop app is not required.

The server keeps its own embedded Python/PyTorch/CUDA environment; VibeFlow only
sets the Windows UTF-8 variables and writes a dedicated .env (2B Turbo + LM
0.6B + PyTorch backend, suitable for 8 GB GPUs).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

Progress = Callable[[str, float], None]

ARCHIVE_URL = "https://files.acemusic.ai/acemusic/win/ACE-Step-1.5.7z"
ARCHIVE_SIZE = 2_403_883_448
DEFAULT_PORT = 8021
REQUIRED_FREE_BYTES = 22 * 1024**3  # archive + extracted code + models margin

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class BackendError(RuntimeError):
    pass


def _noop(message: str, fraction: float = 0.0) -> None:
    pass


class ACEStepBackend:
    def __init__(self, root: Path | None = None, port: int = DEFAULT_PORT):
        # Do not use the LOCALAPPDATA environment variable directly: the
        # Microsoft Store Python redirects it to a per-package LocalCache,
        # which would hide the backend from the normal filesystem.
        override = os.environ.get("VIBEFLOW_DATA_DIR", "").strip()
        base = Path(override) if override else Path.home() / "VibeFlow"
        self.root = Path(root) if root else base / "ace-step"
        self.install_dir = self.root / "ACE-Step-1.5"
        self.archive = self.root / "ACE-Step-1.5.7z"
        self.port = port
        self.process: subprocess.Popen | None = None
        self.external = False
        self.log_path = self.root / "server.log"
        self.error_log_path = self.root / "server.error.log"

    # ------------------------------------------------------------- discovery
    def _valid(self, path: Path | None) -> bool:
        if path is None:
            return False
        return (
            (path / "python_embeded" / "python.exe").exists()
            and (path / "acestep" / "api_server.py").exists()
        )

    @property
    def managed_installed(self) -> bool:
        return self._valid(self.install_dir)

    def external_candidates(self) -> list[Path]:
        appdata = Path.home() / "AppData" / "Roaming"
        local = Path.home() / "AppData" / "Local"
        return [
            appdata / "acestep-app" / "downloads" / "ACE-Step-1.5",
            Path(r"C:\ACE-Step-1.5"),
            Path.home() / "ACE-Step-1.5",
            local / "Programs" / "ACE-Step-1.5",
        ]

    def detect(self) -> Path | None:
        if self.managed_installed:
            return self.install_dir
        for candidate in self.external_candidates():
            if self._valid(candidate):
                return candidate
        return None

    def is_installed(self) -> bool:
        return self.detect() is not None

    # ------------------------------------------------------------- lifecycle
    def _health_url(self, port: int | None = None) -> str:
        return f"http://127.0.0.1:{port or self.port}/health"

    def health(self, port: int | None = None, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(self._health_url(port), timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("data", {}).get("status") == "ok")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def _port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def choose_port(self) -> int:
        for port in (self.port, 8022, 8023, 8024):
            if self.health(port) or self._port_free(port):
                return port
        raise BackendError("Aucun port libre entre 8021 et 8024.")

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        return self.health()

    # --------------------------------------------------------------- install
    def install(self, progress: Progress = _noop) -> Path:
        import py7zr  # local import: only needed for installation

        self.root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if free < REQUIRED_FREE_BYTES:
            raise BackendError(
                "Espace disque insuffisant : "
                f"{free / 1024**3:.1f} Go libres, 22 Go recommandés."
            )

        if not self.archive.exists() or self.archive.stat().st_size < ARCHIVE_SIZE * 0.98:
            self._download(progress)
        else:
            progress("Archive ACE-Step déjà téléchargée.", 0.72)

        progress("Extraction de l'archive ACE-Step (plusieurs minutes)…", 0.74)
        extract_dir = self.root / "extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with py7zr.SevenZipFile(self.archive, mode="r") as archive:
                archive.extractall(path=extract_dir)
        except Exception as exc:  # noqa: BLE001
            raise BackendError(f"Extraction ACE-Step impossible : {exc}") from exc

        root = self._find_extracted_root(extract_dir)
        if root is None:
            raise BackendError(
                "L'archive ACE-Step ne contient pas python_embeded/acestep."
            )
        if self.install_dir.exists():
            shutil.rmtree(self.install_dir, ignore_errors=True)
        progress("Installation des fichiers ACE-Step…", 0.9)
        shutil.move(str(root), str(self.install_dir))
        self._write_config()
        self._reuse_models(progress)

        try:
            self.archive.unlink()
        except OSError:
            pass
        shutil.rmtree(extract_dir, ignore_errors=True)
        progress("Moteur ACE-Step installé.", 1.0)
        return self.install_dir

    def _download(self, progress: Progress) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        part = Path(str(self.archive) + ".part")
        if part.exists() and part.stat().st_size >= ARCHIVE_SIZE * 0.98:
            if self.archive.exists():
                self.archive.unlink()
            part.replace(self.archive)
            progress("Archive ACE-Step déjà téléchargée.", 0.72)
            return self.archive
        existing = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "VibeFlow/0.4"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(ARCHIVE_URL, headers=headers)
        progress(
            "Téléchargement d'ACE-Step (2,4 Go)…",
            0.02,
        )
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BackendError(f"Téléchargement ACE-Step impossible : {exc}") from exc

        mode = "ab" if existing and getattr(response, "status", 200) == 206 else "wb"
        if mode == "wb":
            existing = 0
        total = ARCHIVE_SIZE
        length = response.headers.get("Content-Length")
        if length:
            try:
                total = int(length) + existing
            except ValueError:
                pass
        downloaded = existing
        last_report = 0.0
        try:
            with open(part, mode) as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_report > 0.4:
                        last_report = now
                        fraction = 0.02 + 0.70 * min(downloaded / max(total, 1), 1.0)
                        progress(
                            f"Téléchargement ACE-Step… {downloaded / 1024**3:.2f} Go",
                            fraction,
                        )
        finally:
            response.close()

        if downloaded < ARCHIVE_SIZE * 0.98:
            raise BackendError(
                "Téléchargement incomplet. Relancez l'installation pour reprendre."
            )
        if self.archive.exists():
            self.archive.unlink()
        part.replace(self.archive)
        progress("Téléchargement terminé.", 0.72)
        return self.archive

    def _find_extracted_root(self, extract_dir: Path) -> Path | None:
        if self._valid(extract_dir):
            return extract_dir
        for child in extract_dir.iterdir():
            if child.is_dir() and self._valid(child):
                return child
        return None

    def _write_config(self) -> None:
        env_path = self.install_dir / ".env"
        values = {
            "ACESTEP_CONFIG_PATH": "acestep-v15-turbo",
            "ACESTEP_LM_MODEL_PATH": "acestep-5Hz-lm-0.6B",
            "ACESTEP_LM_BACKEND": "pt",
            "ACESTEP_INIT_LLM": "auto",
            "ACESTEP_DEVICE": "auto",
        }
        lines = ["# Généré par VibeFlow — backend ACE-Step local"]
        lines += [f"{key}={value}" for key, value in values.items()]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _reuse_models(self, progress: Progress) -> None:
        """Avoid a 7 GB model download when another ACE-Step install exists."""
        if not self.managed_installed:
            return
        source = None
        for candidate in self.external_candidates():
            if self._valid(candidate) and (candidate / "checkpoints").exists():
                source = candidate
                break
        if source is None:
            return
        target = self.install_dir / "checkpoints"
        target.mkdir(parents=True, exist_ok=True)
        names = (
            "acestep-v15-turbo",
            "acestep-5Hz-lm-0.6B",
            "Qwen3-Embedding-0.6B",
            "vae",
        )
        for name in names:
            src = source / "checkpoints" / name
            dst = target / name
            if src.exists() and not dst.exists():
                progress(f"Copie du modèle {name}…", 0.92)
                shutil.copytree(src, dst, dirs_exist_ok=True)

    # ----------------------------------------------------------------- start
    def start(self, progress: Progress = _noop, timeout: float = 900.0) -> str:
        install = self.detect()
        if install is None:
            raise BackendError("ACE-Step n'est pas installé.")
        if self.is_running():
            progress("Serveur ACE-Step déjà en ligne.", 1.0)
            self.external = self.process is None
            return self.url()

        port = self.choose_port()
        self.port = port
        python = install / "python_embeded" / "python.exe"
        script = install / "acestep" / "api_server.py"
        self.root.mkdir(parents=True, exist_ok=True)
        out_handle = open(self.log_path, "ab")
        err_handle = open(self.error_log_path, "ab")
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        progress(
            "Démarrage d'ACE-Step (chargement du modèle, téléchargement possible)…",
            0.05,
        )
        try:
            self.process = subprocess.Popen(
                [str(python), str(script), "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(install),
                env=environment,
                stdout=out_handle,
                stderr=err_handle,
                creationflags=CREATE_NO_WINDOW,
            )
        finally:
            out_handle.close()
            err_handle.close()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise BackendError(
                    "Le serveur ACE-Step s'est arrêté au démarrage.\n\n"
                    + self.logs(20)
                )
            if self.health(port, timeout=1.0):
                self.external = False
                progress("Serveur ACE-Step prêt.", 1.0)
                return self.url()
            elapsed = int(time.monotonic() - (deadline - timeout))
            progress(
                f"Chargement d'ACE-Step… ({elapsed} s)",
                min(0.9, 0.1 + elapsed / max(timeout, 1.0)),
            )
            time.sleep(1.5)
        raise BackendError("Délai dépassé au démarrage d'ACE-Step.\n\n" + self.logs(20))

    def stop(self) -> None:
        if self.process is None:
            self._stop_orphan()
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None
        self.external = False

    def _stop_orphan(self) -> None:
        """Stop a server left running by a previous VibeFlow session."""
        if not self.health():
            return
        try:
            import psutil
        except ImportError:
            return
        for connection in psutil.net_connections(kind="inet"):
            if connection.status != psutil.CONN_LISTEN:
                continue
            if not connection.laddr or connection.laddr.port != self.port:
                continue
            if not connection.pid:
                continue
            try:
                process = psutil.Process(connection.pid)
                command = " ".join(process.cmdline())
                if "ACE-Step" not in command or "api_server.py" not in command:
                    continue
                process.terminate()
                try:
                    process.wait(timeout=15)
                except psutil.TimeoutExpired:
                    process.kill()
            except (psutil.Error, OSError):
                continue

    # ------------------------------------------------------------------ logs
    def logs(self, lines: int = 120) -> str:
        chunks: list[str] = []
        for path in (self.error_log_path, self.log_path):
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
                    chunks.extend(content[-lines:])
                except OSError:
                    pass
        return "\n".join(chunks[-lines:]) if chunks else "Aucun journal disponible."
