"""Captura del texto de la transcripcion desde una pagina web usando Playwright.

Modos:
  - launch: abre un Chromium propio con perfil persistente (el usuario inicia
            sesion una vez en la clase). Recomendado.
  - cdp:    se conecta a un Chrome ya abierto con --remote-debugging-port=9222.

Expone:
  - list_pages(): titulos + URLs de las pestanas abiertas (util para el selector de pestana)
  - attach(url): fija la pagina objetivo por coincidencia de URL
  - open(url):   navega la pagina objetivo a una URL (solo modo launch)
  - read_transcript(): devuelve el texto actual del contenedor de subtitulos
  - pick_element(): activa un selector visual en la pagina y devuelve el CSS elegido
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# JS que extrae el texto de la transcripcion. Si se pasa un selector explicito lo
# usa; si no, puntua contenedores visibles tipicos de subtitulos/transcripcion.
_READ_JS = r"""
(sel) => {
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  if (sel) {
    const el = document.querySelector(sel);
    return { found: !!el, text: el ? el.innerText : '', usedSelector: sel };
  }
  const known = [
    '[data-testid*="caption" i]', '[data-testid*="transcript" i]',
    '[class*="caption" i]', '[class*="transcript" i]', '[class*="subtitle" i]',
    '[class*="closed-caption" i]', '[class*="cc-text" i]', '[id*="transcript" i]',
    '[id*="caption" i]', '[aria-live="polite"]', '[aria-live="assertive"]',
    '[role="log"]'
  ];
  let best = null, bestLen = 0, bestSel = '';
  const seen = new Set();
  for (const k of known) {
    let nodes;
    try { nodes = document.querySelectorAll(k); } catch (e) { continue; }
    for (const el of nodes) {
      if (seen.has(el) || !isVisible(el)) continue;
      seen.add(el);
      const t = (el.innerText || '').trim();
      // preferimos contenedores con varias palabras reales, no botones ni menus
      if (t.length > bestLen && t.length > 8 && /\s/.test(t)) {
        best = el; bestLen = t.length; bestSel = k;
      }
    }
  }
  return best
    ? { found: true, text: best.innerText, usedSelector: bestSel }
    : { found: false, text: '', usedSelector: '' };
}
"""

_PICKER_JS = r"""
() => new Promise((resolve) => {
  const prevCursor = document.body.style.cursor;
  document.body.style.cursor = 'crosshair';
  const hl = document.createElement('div');
  hl.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;border:2px solid #4f9dff;background:rgba(79,157,255,.15)';
  document.body.appendChild(hl);

  function cssPath(el) {
    if (!(el instanceof Element)) return '';
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      let part = el.nodeName.toLowerCase();
      if (el.id) { parts.unshift(part + '#' + CSS.escape(el.id)); break; }
      const cls = (el.className && typeof el.className === 'string')
        ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(c => '.' + CSS.escape(c)).join('')
        : '';
      if (cls) part += cls;
      const parent = el.parentElement;
      if (parent) {
        const sameTag = [...parent.children].filter(c => c.nodeName === el.nodeName);
        if (sameTag.length > 1) part += ':nth-of-type(' + (sameTag.indexOf(el) + 1) + ')';
      }
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }

  function onMove(e) {
    const el = e.target;
    const r = el.getBoundingClientRect();
    hl.style.left = r.left + 'px'; hl.style.top = r.top + 'px';
    hl.style.width = r.width + 'px'; hl.style.height = r.height + 'px';
  }
  function cleanup() {
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    document.body.style.cursor = prevCursor;
    hl.remove();
  }
  function onClick(e) {
    e.preventDefault(); e.stopPropagation();
    const sel = cssPath(e.target);
    cleanup();
    resolve(sel);
  }
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  setTimeout(() => { cleanup(); resolve(''); }, 60000);
})
"""


class Capture:
    def __init__(self, attach_mode: str = "launch", cdp_url: str = "http://localhost:9222",
                 profile_dir: str = ".chrome-profile"):
        self.attach_mode = attach_mode
        self.cdp_url = cdp_url
        self.profile_dir = profile_dir
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._started_mode: Optional[str] = None
        self.page: Optional[Page] = None
        self.used_selector: str = ""

    async def start(self) -> None:
        # Si ya hay una sesion abierta con el mismo modo, no hacer nada.
        if self._pw is not None and self._started_mode == self.attach_mode and self._context:
            return
        # Cambio de modo (o sesion rota): cerrar lo anterior y reconstruir.
        if self._pw is not None:
            await self.stop()

        self._pw = await async_playwright().start()
        if self.attach_mode == "cdp":
            try:
                self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
            except Exception as exc:
                await self.stop()
                raise RuntimeError(
                    f"No se pudo conectar a Chrome en {self.cdp_url}. "
                    "Abre Chrome con start-chrome-debug.bat, o cambia el modo de "
                    f"conexion a 'Navegador propio (Playwright)'. Detalle: {exc}"
                )
            self._context = (self._browser.contexts or [None])[0]
            if self._context is None:
                self._context = await self._browser.new_context()
        else:
            # Perfil persistente: el usuario inicia sesion una sola vez.
            try:
                self._context = await self._pw.chromium.launch_persistent_context(
                    self.profile_dir,
                    headless=False,
                    viewport={"width": 1280, "height": 800},
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception as exc:
                await self.stop()
                raise RuntimeError(
                    "No se pudo abrir el navegador de captura. "
                    "Ejecuta  py -m playwright install chromium  y reintenta. "
                    f"Detalle: {exc}"
                )

        if self._context is None:
            await self.stop()
            raise RuntimeError("No hay contexto de navegador disponible.")

        self._started_mode = self.attach_mode
        if self._context.pages:
            self.page = self._context.pages[0]

    async def stop(self) -> None:
        try:
            if self.attach_mode == "cdp" and self._browser:
                await self._browser.close()
            elif self._context:
                await self._context.close()
        finally:
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
            self._pw = self._browser = self._context = self.page = None
            self._started_mode = None

    def _all_pages(self) -> list[Page]:
        pages: list[Page] = []
        if self.attach_mode == "cdp" and self._browser:
            for ctx in self._browser.contexts:
                pages.extend(ctx.pages)
        elif self._context:
            pages.extend(self._context.pages)
        return pages

    async def list_pages(self) -> list[dict]:
        await self.start()
        out = []
        for p in self._all_pages():
            try:
                title = await p.title()
            except Exception:
                title = ""
            out.append({"url": p.url, "title": title})
        return out

    async def open(self, url: str) -> None:
        """Navega la pagina objetivo a una URL (crea pestana si hace falta)."""
        await self.start()
        if self._context is None:
            raise RuntimeError("No hay navegador de captura disponible.")
        if self.page is None or self.page.is_closed():
            self.page = await self._context.new_page()
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

    async def attach(self, url_substring: str) -> bool:
        """Fija como objetivo la pestana cuya URL contiene el texto dado."""
        await self.start()
        if not url_substring:
            return self.page is not None
        for p in self._all_pages():
            if url_substring in p.url:
                self.page = p
                return True
        return False

    async def ensure_page(self, target_url: str) -> None:
        """Garantiza que hay una pagina objetivo lista."""
        await self.start()
        if self.page and not self.page.is_closed():
            return
        if self.attach_mode == "cdp":
            if not await self.attach(target_url):
                raise RuntimeError(
                    "No se encontro una pestana con esa URL en el Chrome conectado."
                )
        else:
            await self.open(target_url or "about:blank")

    async def read_transcript(self, selector: str = "") -> dict:
        if self.page is None or self.page.is_closed():
            return {"found": False, "text": "", "usedSelector": "", "error": "sin pagina"}
        try:
            res = await self.page.evaluate(_READ_JS, selector or None)
            self.used_selector = res.get("usedSelector", "")
            return res
        except Exception as exc:
            return {"found": False, "text": "", "usedSelector": "", "error": str(exc)}

    async def pick_element(self) -> str:
        if self.page is None or self.page.is_closed():
            raise RuntimeError("No hay pagina objetivo activa.")
        return await self.page.evaluate(_PICKER_JS)
