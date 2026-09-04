// Se inyecta en cada página (y cada iframe). Lee el panel de subtítulos y manda
// el texto al service worker, que lo reenvía al Traductor local.

(() => {
  let selector = "";        // CSS forzado desde la app; "" = autodetección
  let intervalMs = 1000;
  let timer = null;

  function isVisible(el) {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return (
      r.width > 4 && r.height > 4 &&
      s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0"
    );
  }

  const KNOWN = [
    '[data-testid*="caption" i]', '[data-testid*="transcript" i]',
    '[class*="caption" i]', '[class*="transcript" i]', '[class*="subtitle" i]',
    '[class*="closed-caption" i]', '[class*="cc-text" i]',
    '[id*="transcript" i]', '[id*="caption" i]',
    '[aria-live="polite"]', '[aria-live="assertive"]', '[role="log"]',
  ];

  function readText() {
    if (selector) {
      const el = document.querySelector(selector);
      return el ? el.innerText : "";
    }
    let bestText = "", bestLen = 0;
    const seen = new Set();
    for (const k of KNOWN) {
      let nodes;
      try { nodes = document.querySelectorAll(k); } catch (e) { continue; }
      for (const el of nodes) {
        if (seen.has(el) || !isVisible(el)) continue;
        seen.add(el);
        const t = (el.innerText || "").trim();
        if (t.length > bestLen && t.length > 8 && /\s/.test(t)) {
          bestText = el.innerText; bestLen = t.length;
        }
      }
    }
    return bestText;
  }

  function tick() {
    const text = (readText() || "").trim();
    if (text.length > 4) {
      try {
        chrome.runtime.sendMessage({ type: "ingest", text, url: location.href });
      } catch (e) { /* worker dormido: se reintenta al siguiente tick */ }
    }
  }

  function loadConfig() {
    try {
      chrome.runtime.sendMessage({ type: "config" }, (r) => {
        if (r && typeof r.selector === "string") selector = r.selector;
        if (r && r.poll_ms) intervalMs = Math.max(400, r.poll_ms);
        if (timer) clearInterval(timer);
        timer = setInterval(tick, intervalMs);
      });
    } catch (e) {
      if (!timer) timer = setInterval(tick, intervalMs);
    }
  }

  loadConfig();
  setInterval(loadConfig, 5000);

  // Puente con la página del Traductor (localhost:8000) para el modo Audio:
  // la página no puede llamar a chrome.tabs / chrome.tabCapture directamente,
  // así que pasa por este content script hasta el service worker.
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.__traductor !== true) return;
    chrome.runtime.sendMessage({ type: data.type, tabId: data.tabId }, (resp) => {
      window.postMessage({ __traductorResponse: true, requestId: data.requestId, payload: resp }, "*");
    });
  });
  window.postMessage({ __traductorReady: true }, "*");

  // Responde al service worker cuando el modo CAMBRIDGE (espejo de página
  // traducida) pide el HTML actual de esta pestaña.
  //
  // Muchas apps modernas (como CambridgeOne) usan Shadow DOM para encapsular
  // sus componentes: outerHTML NO incluye ese contenido. Element.getHTML()
  // (Chrome 124+) sí puede serializarlo si le pasamos los shadow roots
  // abiertos explícitamente (los cerrados son inaccesibles por diseño de la
  // plataforma web, no hay forma de leerlos).
  function collectOpenShadowRoots(root, acc) {
    const all = root.querySelectorAll ? root.querySelectorAll("*") : [];
    for (const el of all) {
      if (el.shadowRoot) {
        acc.push(el.shadowRoot);
        collectOpenShadowRoots(el.shadowRoot, acc);
      }
    }
  }

  function serializeDocument() {
    if (typeof document.documentElement.getHTML !== "function") {
      return document.documentElement.outerHTML;
    }
    try {
      const roots = [];
      collectOpenShadowRoots(document.documentElement, roots);
      const inner = document.documentElement.getHTML({ serializableShadowRoots: true, shadowRoots: roots });
      const attrs = Array.from(document.documentElement.attributes)
        .map((a) => `${a.name}="${String(a.value).replace(/"/g, "&quot;")}"`)
        .join(" ");
      return `<html ${attrs}>${inner}</html>`;
    } catch (e) {
      return document.documentElement.outerHTML;
    }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "getHTML") {
      sendResponse({
        html: serializeDocument(),
        url: location.href,
        title: document.title,
      });
      return false;
    }
    return false;
  });

  // Modo Selector: mientras esta activo en esta pestaña, cada seleccion de
  // texto (raton o teclado) se manda al service worker para traducir.
  // Debounced para no disparar en cada micro-cambio mientras se arrastra.
  //
  // getSelection().toString() NO cruza limites de Shadow DOM (se corta ahi,
  // perdiendo parrafos en apps como CambridgeOne). getComposedRanges() si lo
  // hace si se le pasan los shadow roots abiertos.
  function composedSelectionText(sel) {
    if (typeof sel.getComposedRanges !== "function") return (sel.toString() || "").trim();
    try {
      const roots = [];
      collectOpenShadowRoots(document.documentElement, roots);
      const ranges = sel.getComposedRanges({ shadowRoots: roots });
      if (ranges && ranges.length) {
        const parts = ranges.map((sr) => {
          const r = new Range();
          r.setStart(sr.startContainer, sr.startOffset);
          r.setEnd(sr.endContainer, sr.endOffset);
          return r.toString();
        });
        const joined = parts.join(" ").trim();
        if (joined) return joined;
      }
    } catch (e) {}
    return (sel.toString() || "").trim();
  }

  let selWatching = false;
  let selLastSent = "";
  let selTimer = null;

  document.addEventListener("selectionchange", () => {
    if (!selWatching) return;
    if (selTimer) clearTimeout(selTimer);
    selTimer = setTimeout(() => {
      const sel = window.getSelection ? window.getSelection() : null;
      const text = sel ? composedSelectionText(sel) : "";
      if (text && text !== selLastSent) {
        selLastSent = text;
        try {
          chrome.runtime.sendMessage({ type: "selection", text, url: location.href });
        } catch (e) {}
      }
    }, 400);
  });

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "watchSelection") {
      selWatching = !!msg.watch;
      if (!selWatching) selLastSent = "";
      sendResponse({ ok: true }); // el llamador espera respuesta; sin esto Chrome
      return false;                // cierra el puerto con "message port closed…"
    }
    return false;
  });
})();
