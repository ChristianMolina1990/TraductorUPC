"""Instala un par de idiomas de Argos desde el indice oficial (requiere internet).

Uso:
    py scripts/install_lang.py en es
    py scripts/install_lang.py            # instala en->es y es->en por defecto
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import translate as mt  # noqa: E402


def main() -> None:
    pairs = []
    if len(sys.argv) >= 3:
        pairs = [(sys.argv[1], sys.argv[2])]
    else:
        pairs = [("en", "es"), ("es", "en")]

    for fc, tc in pairs:
        try:
            print(f"Instalando {fc} -> {tc} ...")
            print("  ", mt.install_from_index(fc, tc))
        except Exception as exc:
            print(f"  fallo: {exc}")

    print("\nPares instalados:")
    for p in mt.installed_pairs():
        print("  ", p["name"], f'({p["from_code"]}->{p["to_code"]})')


if __name__ == "__main__":
    main()
