"""Buffer de texto recibido desde la extension de Chrome.

En el modo "extension", un content script lee el panel de subtitulos en la
pestana que el usuario YA tiene abierta y hace POST /api/ingest con el texto.
El pipeline lee de aqui en vez de usar Playwright.
"""

from __future__ import annotations

import time


class Ingest:
    def __init__(self) -> None:
        self.text: str = ""
        self.ts: float = 0.0
        self.source_url: str = ""

    def push(self, text: str, source_url: str = "") -> None:
        text = text or ""
        # Nos quedamos con el texto mas largo si llegan varios frames casi a la vez;
        # si el nuevo es claramente distinto (otro contenido), lo aceptamos igual.
        if text and len(text) < len(self.text) * 0.5 and (time.time() - self.ts) < 1.5:
            return
        self.text = text
        self.ts = time.time()
        if source_url:
            self.source_url = source_url

    def read(self) -> str:
        return self.text

    def age(self) -> float:
        return time.time() - self.ts if self.ts else 1e9


ingest = Ingest()
