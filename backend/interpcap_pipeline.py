"""Pipeline del modo 'Intérprete - Captura'.

Es el Intérprete (audio -> transcripción -> traducción -> sugerencias de
Claude) más una captura de la pestaña que se adjunta a cada petición a
Claude, para que entienda también lo que se ve en pantalla.

- Comparte, solo lectura, la configuración del Intérprete (idiomas, modelo de
  voz, modo manual/auto y temas a tratar).
- Lo único propio es el interruptor `interpcap_send_image`. Desactivado:
  no se guarda ni se envía ninguna imagen (petición solo de texto).
- La extensión sube un fotograma cada ~5 s si la pantalla cambió (o al
  pulsar "Capturar ahora"); aquí solo se guarda el último.
"""

from __future__ import annotations

import time

from .interp_pipeline import InterpreterPipeline

# Una captura JPEG reducida ocupa ~100-300 KB; esto solo evita cargas absurdas.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class InterpCapturePipeline(InterpreterPipeline):
    def __init__(self, settings, broadcast):
        super().__init__(settings, broadcast, channel="interpcap")
        self.image: bytes | None = None
        self.image_ts: float = 0.0
        # "Capturar ahora": la extensión lo lee en su siguiente consulta.
        self.force_capture = False

    # ------------------------------ estado ------------------------------

    @property
    def send_image(self) -> bool:
        return bool(self.settings.interpcap_send_image)

    def snapshot(self) -> dict:
        return {
            **super().snapshot(),
            "send_image": self.send_image,
            "image_ts": self.image_ts if self.image else 0,
        }

    async def start(self) -> None:
        if self._running:
            return
        # Una sesión nueva no debe arrastrar la captura de la anterior.
        self.image, self.image_ts = None, 0.0
        await super().start()
        await self._broadcast_frame()

    # ------------------------------ capturas ------------------------------

    async def ingest_frame(self, data: bytes) -> bool:
        """Guarda la última captura. Se ignora si el interruptor está apagado."""
        self.force_capture = False
        if not self.send_image or not data or len(data) > MAX_IMAGE_BYTES:
            return False
        self.image, self.image_ts = data, time.time()
        await self._broadcast_frame()
        return True

    async def clear_image(self) -> None:
        self.image, self.image_ts = None, 0.0
        self.force_capture = False
        await self._broadcast_frame()

    def request_capture(self) -> dict:
        if not self.send_image:
            return {"ok": False, "error": "activa primero «Enviar captura a Claude»"}
        if not self._running:
            return {"ok": False, "error": "no se está capturando ninguna pestaña"}
        self.force_capture = True
        return {"ok": True}

    async def _broadcast_frame(self) -> None:
        await self.broadcast({
            "type": "interpcap_frame",
            "image_ts": self.image_ts if self.image else 0,
            "send_image": self.send_image,
        })

    def _current_image(self) -> bytes | None:
        # Doble barrera: aunque hubiera una imagen guardada, con el interruptor
        # apagado nunca se envía.
        return self.image if self.send_image else None

    # ------------------- ganchos del InterpreterPipeline -------------------

    def _has_visual_context(self) -> bool:
        return self._current_image() is not None

    def _no_context_error(self) -> str:
        if self.send_image:
            return ("escribe los temas a tratar o espera a la primera captura "
                    "de la pestaña para iniciar la conversación")
        return ("escribe primero los temas a tratar (o activa «Enviar captura a Claude») "
                "para iniciar la conversación")

    def _suggest_extra(self) -> dict:
        return {"image": self._current_image(), "capture_mode": True}

    def _suggestion_meta(self, extra: dict) -> dict:
        return {"with_image": extra.get("image") is not None}
