"""Local ACE-Step 1.5 API client for VibeFlow.

The server exposes an asynchronous REST API:
    POST /release_task  -> {"data": {"task_id": ...}}
    POST /query_result  -> task status and generated files
    GET  /v1/audio?path=...

Generation runs on the user's GPU; VibeFlow only submits a musical brief and
downloads the result. No cloud key is involved.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Progress = Callable[[str, float], None]


class ACEStepError(RuntimeError):
    pass


@dataclass
class ACEStepRequest:
    prompt: str
    duration: float
    bpm: float
    key_scale: str = "A minor"
    time_signature: str = "4"
    thinking: bool = False
    inference_steps: int = 8
    batch_size: int = 1
    audio_format: str = "wav"
    model: str | None = None

    def payload(self) -> dict:
        body = {
            "prompt": self.prompt,
            "lyrics": "",
            "audio_duration": float(max(10.0, min(self.duration, 600.0))),
            "bpm": int(round(self.bpm)),
            "key_scale": self.key_scale,
            "time_signature": self.time_signature,
            "thinking": bool(self.thinking),
            "inference_steps": int(max(1, min(self.inference_steps, 20))),
            "batch_size": int(max(1, min(self.batch_size, 8))),
            "audio_format": self.audio_format,
            "use_cot_caption": False,
            "use_cot_language": False,
            "vocal_language": "en",
        }
        if self.model:
            body["model"] = self.model
        return body


@dataclass
class ACEStepTrack:
    file: str
    metadata: dict = field(default_factory=dict)
    seed: str = ""


@dataclass
class ACEStepResult:
    task_id: str
    tracks: list[ACEStepTrack]
    raw: dict = field(default_factory=dict)


class ACEStepClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8021",
        *,
        api_key: str = "",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout

    # ------------------------------------------------------------- transport
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self._headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ACEStepError(f"Serveur ACE-Step : HTTP {exc.code} — {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ACEStepError(
                f"ACE-Step est injoignable sur {self.base_url}. "
                "Vérifiez que le serveur local est démarré."
            ) from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ACEStepError("Réponse ACE-Step illisible (JSON invalide).") from exc
        if payload.get("error"):
            raise ACEStepError(str(payload["error"]))
        return payload

    # ------------------------------------------------------------------ API
    def health(self) -> bool:
        try:
            payload = self._json("GET", "/health")
        except ACEStepError:
            return False
        return bool(payload.get("data", {}).get("status") == "ok")

    def models(self) -> list[str]:
        payload = self._json("GET", "/v1/models")
        data = payload.get("data") or {}
        models = data.get("models") if isinstance(data, dict) else data
        names = []
        for item in models or []:
            if isinstance(item, dict):
                names.append(item.get("name") or item.get("id") or "")
            elif isinstance(item, str):
                names.append(item)
        return [name for name in names if name]

    def submit(self, request: ACEStepRequest) -> str:
        payload = self._json("POST", "/release_task", request.payload())
        task_id = (payload.get("data") or {}).get("task_id")
        if not task_id:
            raise ACEStepError("ACE-Step n'a pas renvoyé d'identifiant de tâche.")
        return str(task_id)

    def wait(self, task_id: str, *, progress: Progress | None = None,
             timeout: float = 900.0, interval: float = 2.5) -> ACEStepResult:
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        while time.monotonic() < deadline:
            payload = self._json("POST", "/query_result", {"task_id_list": [task_id]})
            tasks = payload.get("data") or []
            if not tasks:
                raise ACEStepError("Tâche ACE-Step introuvable.")
            task = tasks[0]
            status = int(task.get("status", 0))
            if status == 1:
                raw = task.get("result") or "[]"
                try:
                    tracks = json.loads(raw) if isinstance(raw, str) else raw
                except (ValueError, TypeError) as exc:
                    raise ACEStepError("Résultat ACE-Step illisible.") from exc
                parsed = [
                    ACEStepTrack(
                        file=str(track.get("file", "")),
                        metadata=track.get("metas") or {},
                        seed=str(track.get("seed_value", "")),
                    )
                    for track in tracks
                    if track.get("file")
                ]
                if not parsed:
                    raise ACEStepError("ACE-Step a terminé sans produire de fichier audio.")
                return ACEStepResult(task_id=task_id, tracks=parsed, raw=task)
            if status == 2:
                raise ACEStepError(
                    "La génération ACE-Step a échoué. "
                    + str(task.get("result") or "")[:400]
                )
            if progress:
                elapsed = time.monotonic() - started
                progress(
                    f"ACE-Step génère la musique… ({int(elapsed)} s)",
                    min(0.85, 0.15 + elapsed / max(timeout, 1.0)),
                )
            time.sleep(interval)
        raise ACEStepError("Délai dépassé : ACE-Step n'a pas terminé la génération.")

    def download(self, track: ACEStepTrack, destination: str | Path,
                 *, progress: Progress | None = None) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = track.file
        if not url.startswith("http"):
            url = f"{self.base_url}{url if url.startswith('/') else '/' + url}"
        if progress:
            progress("Téléchargement de la piste ACE-Step…", 0.9)
        try:
            with urllib.request.urlopen(url, timeout=max(self.timeout, 120.0)) as response:
                data = response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise ACEStepError(f"Téléchargement ACE-Step impossible : {exc}") from exc
        destination.write_bytes(data)
        return destination

    def generate(
        self,
        request: ACEStepRequest,
        destination: str | Path,
        *,
        progress: Progress | None = None,
        timeout: float = 900.0,
    ) -> ACEStepResult:
        if progress:
            progress("Connexion à ACE-Step…", 0.05)
        task_id = self.submit(request)
        if progress:
            progress("Tâche ACE-Step envoyée, génération en cours…", 0.12)
        result = self.wait(task_id, progress=progress, timeout=timeout)
        self.download(result.tracks[0], destination, progress=progress)
        return result
