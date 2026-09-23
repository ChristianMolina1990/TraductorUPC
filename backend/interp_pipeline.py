"""Pipeline del modo 'Intérprete'.

Reutiliza exactamente la misma captura de audio que el modo Audio (la
extensión manda clips cortos de la pestaña elegida) y el mismo STT/MT
offline (faster-whisper + Argos Translate). La diferencia es que, además,
le pide a la API de Claude una sugerencia de qué responder en inglés — la
única parte de este modo que necesita API key e internet.
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
from . import claude_client
from . import translate as mt

log = logging.getLogger(__name__)

_MAX_QUEUE = 3
_CONTEXT_LINES = 8
_OWN_CONTEXT_LINES = 4
_KINDS = ("start", "reply", "complement", "question")


class InterpreterPipeline:
    def __init__(self, settings, broadcast: Callable[[dict], Awaitable[None]]):
        self.settings = settings
        self.broadcast = broadcast
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._task: asyncio.Task | None = None
        self._running = False
        self.history: list[dict] = []       # transcripcion: original + traducido
        self.suggestions: list[dict] = []   # sugerencias: ingles + traducida
        self.last_status = "detenido"
        # En modo "auto" no se sugiere tras cada clip de 3s (interrumpiria a
        # mitad de frase); se espera a que un clip salga en silencio, senal de
        # que el interlocutor hizo una pausa tras lo ultimo transcrito.
        self._pending_suggestion = False

    @property
    def running(self) -> bool:
        return self._running

    def snapshot(self) -> dict:
        return {
            "running": self._running,
            "status": self.last_status,
            "history": self.history[-200:],
            "suggestions": self.suggestions[-200:],
        }

    async def start(self) -> None:
        if self._running:
            return
        self.history.clear()
        self.suggestions.clear()
        self._pending_suggestion = False
        self._running = True
        self.last_status = "esperando audio de la pestaña…"
        self._task = asyncio.create_task(self._worker())
        await self.broadcast({"type": "interp_status", "status": self.last_status, "running": True})

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
        await self.broadcast({"type": "interp_status", "status": self.last_status, "running": False})

    async def clear(self) -> None:
        self.history.clear()
        self.suggestions.clear()
        self._pending_suggestion = False
        await self.broadcast({"type": "interp_snapshot", **self.snapshot()})

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
                original = await asyncio.to_thread(
                    self._transcribe, data, s.interp_whisper_model, s.interp_from_code
                )
            except Exception as exc:
                log.warning("clip de audio descartado (no se pudo transcribir): %s", exc)
                continue

            if original:
                translated = await asyncio.to_thread(
                    mt.translate_text, original, s.interp_from_code, s.interp_to_code
                )
                item = {"original": original, "translated": translated, "ts": time.time()}
                self.history.append(item)
                self._pending_suggestion = True
                self.last_status = "transcribiendo"
                await self.broadcast({"type": "interp_segment", **item})
            elif s.interp_trigger == "auto" and self._pending_suggestion:
                # Clip en silencio tras haber transcrito algo: el interlocutor
                # acaba de hacer una pausa, es el momento de sugerir.
                self._pending_suggestion = False
                await self._generate_suggestion()

    async def _generate_suggestion(self) -> None:
        """Sugerencia automatica (modo auto) tras una pausa del interlocutor."""
        if not self.settings.anthropic_api_key:
            self.last_status = "falta la API key de Claude (configúrala en ⚙ Configuración)"
            await self.broadcast({"type": "interp_status", "status": self.last_status, "running": True})
            return
        try:
            await self._suggest("reply")
        except Exception as exc:
            log.warning("no se pudo generar sugerencia: %s", exc)
            self.last_status = f"error de Claude: {exc}"
            await self.broadcast({"type": "interp_status", "status": self.last_status, "running": True})

    async def suggest_manual(self, kind: str = "reply") -> dict:
        """Genera bajo demanda una sugerencia a partir de lo ya transcrito.

        kind: "start" (iniciar la conversacion con los temas), "reply"
        (sugerir respuesta), "complement" (complementar la ultima respuesta
        sugerida) o "question" (preguntar al interlocutor)."""
        if kind not in _KINDS:
            return {"ok": False, "error": f"tipo de sugerencia desconocido: {kind}"}
        if kind == "start" and not self.settings.interp_topics.strip():
            return {"ok": False, "error": "escribe primero los temas a tratar para iniciar la conversación"}
        if not self.history and (kind == "complement" or not self.settings.interp_topics.strip()):
            return {"ok": False, "error": "todavía no hay nada transcrito (o escribe los temas a tratar)"}
        if kind == "complement" and not self.suggestions:
            return {"ok": False, "error": "primero pide una respuesta para poder complementarla"}
        if not self.settings.anthropic_api_key:
            return {"ok": False, "error": "falta la API key de Claude (configúrala en ⚙ Configuración)"}
        try:
            await self._suggest(kind)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def _suggest(self, kind: str) -> None:
        s = self.settings
        if kind == "start":
            # Apertura: solo cuentan los temas, no lo transcrito ni lo sugerido antes.
            recent, own = [], []
        else:
            recent = [h["original"] for h in self.history[-_CONTEXT_LINES:]]
            own = [h["suggestion_en"] for h in self.suggestions[-_OWN_CONTEXT_LINES:]]
        result = await asyncio.to_thread(
            claude_client.suggest_reply, s.anthropic_api_key, recent, kind, own, s.interp_topics
        )
        suggestion_en = result["reply"]
        if not suggestion_en:
            return
        suggestion_es = await asyncio.to_thread(mt.translate_text, suggestion_en, "en", s.interp_to_code)
        item = {
            "kind": kind,
            "suggestion_en": suggestion_en,
            "suggestion_es": suggestion_es,
            "pronunciation": result["pronunciation"],
            "ts": time.time(),
        }
        self.suggestions.append(item)
        self._pending_suggestion = False
        if self._running:
            self.last_status = "transcribiendo"
        await self.broadcast({"type": "interp_suggestion", **item})

    @staticmethod
    def _transcribe(data: bytes, model_size: str, language: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            return audio_stt.transcribe(path, model_size, language)
        finally:
            Path(path).unlink(missing_ok=True)
