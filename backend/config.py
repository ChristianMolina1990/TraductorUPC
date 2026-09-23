"""Configuracion persistente de la aplicacion.

Se guarda en config.json en la raiz del proyecto. Todos los campos tienen
valores por defecto razonables para el caso "clase en ingles -> espanol".
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
PROFILE_DIR = ROOT / ".chrome-profile"
MODELS_DIR = ROOT / "models"

_lock = threading.Lock()


@dataclass
class Settings:
    # --- Captura del navegador ---
    # "launch" = la app abre su propio Chromium (recomendado).
    # "cdp"    = la app se engancha a un Chrome ya abierto con --remote-debugging-port.
    attach_mode: str = "launch"
    cdp_url: str = "http://localhost:9222"

    # URL de la clase / pagina a la que se debe enganchar.
    target_url: str = ""

    # Selector CSS del contenedor de la transcripcion en vivo.
    # Vacio = deteccion automatica (busca contenedores tipo "caption/transcript").
    selector: str = ""

    # Cada cuantos segundos se relee el DOM.
    poll_interval: float = 1.0

    # Segundos sin cambios tras los cuales una frase incompleta se da por cerrada.
    idle_flush: float = 2.0

    # --- Traduccion ---
    from_code: str = "en"
    to_code: str = "es"

    # --- Audio (pestana capturada por la extension) ---
    audio_from_code: str = "en"
    audio_to_code: str = "es"
    whisper_model: str = "base"

    # --- Pagina (espejo de una pestana traducida en vivo) ---
    page_from_code: str = "en"
    page_to_code: str = "es"

    # --- Selector (traduce lo que el usuario seleccione en una pestana) ---
    # Nombrado "sel_" para no chocar con el campo "selector" (CSS) de arriba.
    sel_from_code: str = "en"
    sel_to_code: str = "es"

    # --- Interprete (transcribe + traduce + sugiere que responder) ---
    # La transcripcion y la traduccion siguen siendo offline (igual que Audio);
    # solo la sugerencia de respuesta llama a la API de Claude (Anthropic).
    interp_from_code: str = "en"
    interp_to_code: str = "es"
    interp_whisper_model: str = "base"
    interp_trigger: str = "auto"  # "auto" = sugiere tras cada frase | "manual" = con boton
    # Temas que el usuario quiere tratar; orientan las sugerencias de Claude.
    interp_topics: str = ""
    anthropic_api_key: str = ""

    def save(self) -> None:
        with _lock:
            CONFIG_PATH.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
            )

    @classmethod
    def load(cls) -> "Settings":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception:
                pass
        return cls()

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if key in self.__dataclass_fields__ and value is not None:  # type: ignore[attr-defined]
                setattr(self, key, value)
        self.save()
