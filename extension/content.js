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
})();
