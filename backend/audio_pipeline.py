"""Pipeline de audio: recibe clips cortos de la pestana capturada por la
extension -> los transcribe (faster-whisper, offline) -> los traduce
(Argos Translate) -> los emite por WebSocket.

Cada clip que llega de la extension es un archivo webm/opus autocontenido
de pocos segundos (la extension corta y reinicia su MediaRecorder), asi que
se puede transcribir de forma independiente sin reensamblar nada.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

from . import audio_stt
from . import translate as mt

log = logging.getLogger(__name__)

# Si el reconocimiento de voz no da abasto, se descartan los clips mas viejos
# en vez de acumular retraso creciente entre el audio y la traduccion.
_MAX_QUEUE = 3


class AudioPipeline:
    def __init__(self, settings, broadcast: Callable[[dict], Awaitable[None]]):
        self.settings = settings
        self.broadcast = broadcast
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._task: asyncio.Task | None = None
        self._running = False
        self.history: list[dict] = []
        self.last_status = "detenido"

    @property
    def running(self) -> bool:
        return self._running

    def snapshot(self) -> dict:
        return {
            "running": self._running,
            "status": self.last_status,
            "history": self.history[-500:],
        }

    async def start(self) -> None:
        if self._running:
            return
        self.history.clear()
        self._running = True
        self.last_status = "esperando audio de la pestana…"
        self._task = asyncio.create_task(self._worker())
        await self.broadcast({"type": "audio_status", "status": self.last_status, "running": True})

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        while not self._queue.empty():
            self._queue.get_nowait()
        self.last_status = "detenido"
        await self.broadcast({"type": "audio_status", "status": self.last_status, "running": False})

    async def clear(self) -> None:
        self.history.clear()
        await self.broadcast({"type": "audio_snapshot", **self.snapshot()})

    async def ingest_chunk(self, data: bytes) -> None:
        if not self._running or not data:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        await self._queue.put(data)

    async def _worker(self) -> None:
        s = self.settings
        while self._running:
            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                original = await asyncio.to_thread(self._transcribe, data, s.whisper_model, s.audio_from_code)
            except Exception as exc:
                # Un clip suelto puede llegar corrupto o vacio (p.ej. si el usuario
                # adelanta/pausa el video justo en ese instante); no es un fallo real
                # del pipeline, asi que se descarta sin mostrar un estado de error.
                log.warning("clip de audio descartado (no se pudo transcribir): %s", exc)
                continue
            if not original:
                continue
            translated = await asyncio.to_thread(
                mt.translate_text, original, s.audio_from_code, s.audio_to_code
            )
            item = {"original": original, "translated": translated, "ts": time.time()}
            self.history.append(item)
            self.last_status = "transcribiendo"
            await self.broadcast({"type": "audio_segment", **item})

    @staticmethod
    def _transcribe(data: bytes, model_size: str, language: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            return audio_stt.transcribe(path, model_size, language)
        finally:
            Path(path).unlink(missing_ok=True)
