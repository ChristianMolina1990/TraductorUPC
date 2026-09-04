"""Traduce una pagina HTML completa, nodo de texto por nodo de texto,
conservando la estructura y el estilo original (para "espejar" una pestana
pero con las palabras en otro idioma).

Cachea las traducciones ya vistas: la mayor parte de una pagina (menus,
botones, cabeceras...) no cambia entre una lectura y la siguiente, solo el
contenido en vivo, asi que no hace falta retraducirla cada vez.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment

from . import translate as mt

_SKIP_TAGS = {"script", "style", "noscript"}
_cache: dict[tuple[str, str, str], str] = {}
_CACHE_MAX = 20000


def _translate_cached(text: str, from_code: str, to_code: str) -> str:
    key = (from_code, to_code, text)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    out = mt.translate_text(text, from_code, to_code)
    if len(_cache) < _CACHE_MAX:
        _cache[key] = out
    return out


def _parse(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def translate_page(html: str, url: str, from_code: str, to_code: str) -> str:
    soup = _parse(html)

    for tag in soup.find_all(_SKIP_TAGS):
        tag.decompose()

    # <template shadowrootmode="..."> es Shadow DOM declarativo: el navegador
    # lo convierte en contenido real y visible al parsear el HTML. Un
    # <template> normal es inerte (solo se usa si algun script lo clona), asi
    # que ese si se descarta.
    for tag in soup.find_all("template"):
        if not tag.get("shadowrootmode"):
            tag.decompose()

    for node in soup.find_all(string=True):
        if isinstance(node, Comment):
            continue
        if node.parent is None or node.parent.name in _SKIP_TAGS:
            continue
        text = str(node)
        if not text.strip():
            continue
        translated = _translate_cached(text.strip(), from_code, to_code)
        node.replace_with(translated)

    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        if soup.html:
            soup.html.insert(0, head)
    if url and not head.find("base"):
        head.insert(0, soup.new_tag("base", href=url))

    return str(soup)
