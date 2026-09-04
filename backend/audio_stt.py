"""Reconocimiento de voz offline (faster-whisper / CTranslate2).

El modelo se descarga una vez desde Hugging Face la primera vez que se usa
(requiere internet esa vez) y luego queda cacheado en disco: funciona sin
red igual que los modelos de Argos Translate.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

_lock = threading.Lock()
_model = None
_model_size: Optional[str] = None


def _pick_device() -> tuple[str, str]:
    """GPU si hay una NVIDIA disponible (mucho mas rapido); si no, CPU con int8."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _get_model(model_size: str):
    global _model, _model_size
    with _lock:
        if _model is None or _model_size != model_size:
            from faster_whisper import WhisperModel

            device, compute_type = _pick_device()
            cpu_threads = min(os.cpu_count() or 4, 8) if device == "cpu" else 0
            _model = WhisperModel(
                model_size, device=device, compute_type=compute_type, cpu_threads=cpu_threads
            )
            _model_size = model_size
        return _model


def transcribe(audio_path: str, model_size: str, language: Optional[str] = None) -> str:
    """Transcribe un archivo de audio corto y devuelve el texto reconocido."""
    model = _get_model(model_size)
    segments, _info = model.transcribe(
        audio_path,
        language=language or None,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()
