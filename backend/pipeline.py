"""Pipeline: leer transcripcion -> detectar lineas nuevas -> segmentar -> traducir -> emitir.

El panel de transcripcion (class.com, Zoom, Meet...) es una lista de intervenciones
con scroll: cada entrada suele ir precedida por las iniciales y el nombre de quien
habla. Estrategia:

  - Se trocea el texto del panel en lineas.
  - Cada linea que NO se haya visto ya y que no parezca un nombre/iniciales de
    hablante se traduce (partida en frases).
  - La ultima linea puede seguir creciendo: queda "interina" hasta que aparece una
    linea mas nueva o pasan `idle_flush` segundos sin cambios.
  - Se recuerda un conjunto acotado de lineas ya emitidas para no repetir.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Awaitable, Callable

from . import translate as mt
from .capture import Capture
from .ingest import ingest

_SENT_SPLIT = re.compile(r"(?<=[\.\?\!:;。？！])\s+")
_WS = re.compile(r"[^\S\r\n]+")
_INITIALS = re.compile(r"^[A-ZÁÉÍÓÚÑÜ]{1,4}\.?$")
_NAME_WORD = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü'’.\-]+$")
_LEAD_PUNCT = re.compile(r"^[\s,;:·\-–—]+")


def _clean_lines(text: str) -> list[str]:
    text = (text or "").replace("\r", "\n")
    lines = []
    for raw in text.split("\n"):
        ln = _WS.sub(" ", raw).strip()
        if ln:
            lines.append(ln)
    return lines


def _norm(line: str) -> str:
    return _WS.sub(" ", line).strip().lower().rstrip(".,;:!?… ")


def _looks_like_speaker(line: str) -> bool:
    """Iniciales ('ML', 'RA.') o nombre propio de 2-5 palabras ('Juan Perez Lopez')."""
    s = line.strip()
    if not s:
        return True
    if _INITIALS.match(s):
        return True
    words = s.split()
    if 2 <= len(words) <= 5 and not re.search(r"[0-9,;:!?¿¡]", s) and s.count(".") <= 1:
        if all(_NAME_WORD.match(w) for w in words):
            return True
    return False


class Segmenter:
    MAX_SEEN = 600

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._order: list[str] = []
        self.pending = ""                 # ultima linea, aun sin finalizar
        self._tail = ""
        self._tail_ts = time.monotonic()

    def _mark(self, key: str) -> None:
        if not key or key in self._seen:
            return
        self._seen.add(key)
        self._order.append(key)
        if len(self._order) > self.MAX_SEEN:
            self._seen.discard(self._order.pop(0))

    def _sentences(self, line: str) -> list[str]:
        line = _LEAD_PUNCT.sub("", line.strip())
        if not line:
            return []
        parts = [_LEAD_PUNCT.sub("", p).strip() for p in _SENT_SPLIT.split(line)]
        parts = [p for p in parts if p]
        return parts or [line]

    def feed(self, panel_text: str) -> list[str]:
        lines = _clean_lines(panel_text)
        if not lines:
            return []
        complete, tail = lines[:-1], lines[-1]

        # En la primera lectura _seen esta vacio, asi que se traduce TODO el panel
        # (el historial ya presente) y luego solo lo que vaya llegando nuevo.
        out = []
        for ln in complete:
            key = _norm(ln)
            if key in self._seen:
                continue
            self._mark(key)
            if _looks_like_speaker(ln):
                continue
            out.extend(self._sentences(ln))

        if _norm(tail) != _norm(self._tail):
            self._tail, self._tail_ts = tail, time.monotonic()
        self.pending = "" if _looks_like_speaker(tail) else tail
        return out

    def flush_pending(self, idle_flush: float) -> list[str]:
        if not self.pending or (time.monotonic() - self._tail_ts) < idle_flush:
            return []
        line, key = self.pending, _norm(self.pending)
        self.pending = ""
        if key in self._seen or _looks_like_speaker(line):
            self._mark(key)
            return []
        self._mark(key)
        return self._sentences(line)


class Pipeline:
    def __init__(self, capture: Capture, settings, broadcast: Callable[[dict], Awaitable[None]]):
        self.capture = capture
        self.settings = settings
        self.broadcast = broadcast
        self._task: asyncio.Task | None = None
        self._running = False
        self.segmenter = Segmenter()
        self.history: list[dict] = []   # [{original, translated, ts}]
        self.last_status = "detenido"

    @property
    def running(self) -> bool:
        return self._running

    def snapshot(self) -> dict:
        return {
            "running": self._running,
            "status": self.last_status,
            "used_selector": self.capture.used_selector,
            "history": self.history[-500:],
            "interim": self.segmenter.pending,
        }

    async def start(self) -> None:
        if self._running:
            return
        self.segmenter = Segmenter()
        self.history.clear()
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.last_status = "detenido"
        await self.broadcast({"type": "status", "status": self.last_status, "running": False})

    async def _emit_segment(self, original: str) -> None:
        translated = await asyncio.to_thread(
            mt.translate_text, original, self.settings.from_code, self.settings.to_code
        )
        item = {"original": original, "translated": translated, "ts": time.time()}
        self.history.append(item)
        await self.broadcast({"type": "segment", **item})

    async def _loop(self) -> None:
        s = self.settings
        ext_mode = getattr(s, "attach_mode", "launch") == "extension"

        if not ext_mode:
            try:
                await self.capture.ensure_page(s.target_url)
            except Exception as exc:
                self.last_status = f"error: {exc}"
                await self.broadcast({"type": "status", "status": self.last_status, "running": False})
                self._running = False
                return

        self.last_status = "esperando datos de la extension" if ext_mode else "capturando"
        await self.broadcast({"type": "status", "status": self.last_status, "running": True})

        misses = 0
        while self._running:
            if ext_mode:
                if ingest.age() > 8:
                    res = {"found": False}
                else:
                    res = {"found": True, "text": ingest.read()}
            else:
                res = await self.capture.read_transcript(s.selector)
            if res.get("error"):
                self.last_status = f"aviso: {res['error']}"
                await self.broadcast({"type": "status", "status": self.last_status, "running": True})
            elif not res.get("found"):
                misses += 1
                if misses in (3, 10, 30):
                    if ext_mode:
                        self.last_status = (
                            "sin datos de la extension: abre la pestana de la clase, "
                            "recargala y comprueba que la extension esta cargada"
                        )
                    else:
                        self.last_status = (
                            "no se encontro el contenedor de subtitulos; "
                            "usa 'Elegir en la pagina' o escribe un selector CSS"
                        )
                    await self.broadcast(
                        {"type": "status", "status": self.last_status, "running": True}
                    )
            else:
                misses = 0
                text = res.get("text", "")
                for sentence in self.segmenter.feed(text):
                    await self._emit_segment(sentence)
                # emitir la linea interina (sin traducir aun) para feedback visual
                await self.broadcast({"type": "interim", "text": self.segmenter.pending})

            for sentence in self.segmenter.flush_pending(s.idle_flush):
                await self._emit_segment(sentence)
                await self.broadcast({"type": "interim", "text": ""})

            await asyncio.sleep(max(0.2, s.poll_interval))
