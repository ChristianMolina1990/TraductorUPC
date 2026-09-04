"""Motor de traduccion offline basado en Argos Translate (CTranslate2).

Una vez instalados los paquetes de idioma (.argosmodel), la traduccion
funciona 100% sin internet. Los paquetes se pueden instalar de tres formas:

  1. Colocando archivos .argosmodel en la carpeta models/  -> sync_local_models()
  2. Desde el indice oficial (requiere internet una sola vez) -> install_from_index()
  3. Manualmente con `argospm install translate-en_es`

El indice online solo se usa si el usuario lo pide explicitamente.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import argostranslate.package as package
import argostranslate.translate as translate

_lock = threading.Lock()


def installed_languages() -> list[dict]:
    langs = translate.get_installed_languages()
    return [{"code": l.code, "name": l.name} for l in langs]


def installed_pairs() -> list[dict]:
    pairs = []
    for pkg in package.get_installed_packages():
        pairs.append(
            {
                "from_code": pkg.from_code,
                "to_code": pkg.to_code,
                "name": f"{pkg.from_name} -> {pkg.to_name}",
            }
        )
    return pairs


def can_translate(from_code: str, to_code: str) -> bool:
    if from_code == to_code:
        return True
    langs = {l.code: l for l in translate.get_installed_languages()}
    src, dst = langs.get(from_code), langs.get(to_code)
    if src is None or dst is None:
        return False
    # Comprobacion real: tiene que existir una ruta de traduccion instalada
    # (directa o por pivote). get_translation devuelve None si no la hay.
    try:
        return src.get_translation(dst) is not None
    except Exception:
        return False


def translate_text(text: str, from_code: str, to_code: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if from_code == to_code:
        return text
    if not can_translate(from_code, to_code):
        return f"[falta el modelo {from_code}->{to_code}; instalalo en 'Idiomas...']"
    with _lock:
        try:
            return translate.translate(text, from_code, to_code)
        except Exception as exc:  # nunca romper el pipeline por un fallo de MT
            return f"[error de traduccion: {exc}]"


def sync_local_models(models_dir: Path) -> list[str]:
    """Instala cualquier .argosmodel presente en models/ que aun no este instalado."""
    installed = {
        (p.from_code, p.to_code) for p in package.get_installed_packages()
    }
    added: list[str] = []
    for f in sorted(Path(models_dir).glob("*.argosmodel")):
        try:
            # install_from_path es idempotente en la practica; comprobamos por nombre.
            package.install_from_path(str(f))
            added.append(f.name)
        except Exception as exc:
            added.append(f"{f.name} (fallo: {exc})")
    return added


# --- Operaciones que requieren internet (opcionales, bajo peticion del usuario) ---

def available_from_index() -> list[dict]:
    package.update_package_index()
    out = []
    for p in package.get_available_packages():
        out.append(
            {
                "from_code": p.from_code,
                "to_code": p.to_code,
                "from_name": p.from_name,
                "to_name": p.to_name,
            }
        )
    return out


def install_from_index(from_code: str, to_code: str) -> str:
    package.update_package_index()
    match: Optional[object] = None
    for p in package.get_available_packages():
        if p.from_code == from_code and p.to_code == to_code:
            match = p
            break
    if match is None:
        raise ValueError(f"No existe el paquete {from_code}->{to_code} en el indice")
    downloaded = match.download()  # descarga a la cache local
    package.install_from_path(str(downloaded))
    return f"instalado {from_code}->{to_code}"
