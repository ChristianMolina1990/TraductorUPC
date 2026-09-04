"""Traduce lo que el usuario selecciona (con el raton/teclado) en una pestana
elegida. El content script de la extension detecta la seleccion y hace POST
aqui; se traduce al vuelo y se emite por WebSocket.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from . import translate as mt


class SelectionPipeline:
    def __init__(self, settings, broadcast: Callable[[dict], Awaitable[None]]):
        self.settings = settings
        self.broadcast = broadcast
        self._watching = False
        self.history: list[dict] = []
        self.last_status = "detenido"

    @property
    def watching(self) -> bool:
        return self._watching

    def snapshot(self) -> dict:
        return {
            "running": self._watching,
            "status": self.last_status,
            "history": self.history[-200:],
        }

    async def start(self) -> None:
        self._watching = True
        self.last_status = "esperando selección en la pestaña…"
        await self.broadcast({"type": "selection_status", "status": self.last_status, "running": True})

    async def stop(self) -> None:
        self._watching = False
        self.last_status = "detenido"
        await self.broadcast({"type": "selection_status", "status": self.last_status, "running": False})

    async def clear(self) -> None:
        self.history.clear()
        await self.broadcast({"type": "selection_snapshot", **self.snapshot()})

    async def ingest(self, text: str) -> None:
        text = (text or "").strip()
        if not self._watching or not text:
            return
        self.last_status = "traducido"
        await self._translate_and_emit(text)

    async def ingest_manual(self, text: str) -> None:
        """Traduce texto pegado a mano (respaldo para contenido que la
        extension no puede leer, p.ej. Shadow DOM cerrado). No depende de
        que "Iniciar" este activo ni de ninguna pestana."""
        text = (text or "").strip()
        if not text:
            return
        await self._translate_and_emit(text)

    async def _translate_and_emit(self, text: str) -> None:
        s = self.settings
        translated = await asyncio.to_thread(mt.translate_text, text, s.sel_from_code, s.sel_to_code)
        item = {"original": text, "translated": translated, "ts": time.time()}
        self.history.append(item)
        await self.broadcast({"type": "selection_segment", **item})
