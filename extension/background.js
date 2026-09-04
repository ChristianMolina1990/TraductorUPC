// Service worker: reenvía el texto al backend local. No está sujeto al CSP de
// la página, por eso el fetch va aquí y no en el content script.
//
// Modo Audio: chrome.tabCapture exige que la captura se dispare con un gesto
// real del usuario SOBRE la pestaña a capturar (activeTab). Por eso no se
// puede arrancar desde la página del Traductor con un simple clic en su UI:
// hay que ir a la pestaña con el audio y hacer clic en el icono de la
// extensión. Un segundo clic (en la misma pestaña) la detiene.

const API = "http://localhost:8000";

let capturingTabId = null;
let capturingTabTitle = "";

async function ensureOffscreen() {
  const has = await chrome.offscreen.hasDocument();
  if (!has) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Capturar y transcribir el audio de la pestaña elegida",
    });
  }
}

async function setBadge(tabId, capturing) {
  await chrome.action.setBadgeText({ tabId, text: capturing ? "●" : "" });
  await chrome.action.setBadgeBackgroundColor({ tabId, color: "#e53e3e" });
}

async function startAudioCapture(tab) {
  if (capturingTabId) await stopAudioCapture();
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  await ensureOffscreen();
  await chrome.runtime.sendMessage({ type: "offscreen:start", streamId, api: API });
  capturingTabId = tab.id;
  capturingTabTitle = tab.title || tab.url || "";
  await setBadge(tab.id, true);
  await fetch(API + "/api/audio/start", { method: "POST" }).catch(() => {});
  return { ok: true };
}

async function stopAudioCapture() {
  if (!capturingTabId) return { ok: true };
  const tabId = capturingTabId;
  capturingTabId = null;
  capturingTabTitle = "";
  try {
    await chrome.runtime.sendMessage({ type: "offscreen:stop" });
  } catch (e) {}
  await chrome.offscreen.closeDocument().catch(() => {});
  await setBadge(tabId, false).catch(() => {});
  await fetch(API + "/api/audio/stop", { method: "POST" }).catch(() => {});
  return { ok: true };
}

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !/^https?:/.test(tab.url || "")) return;
  if (capturingTabId === tab.id) {
    await stopAudioCapture();
  } else {
    await startAudioCapture(tab);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "ingest") {
    fetch(API + "/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: msg.text, url: msg.url }),
    }).catch(() => {});
    return false;
  }
  if (msg && msg.type === "config") {
    fetch(API + "/api/ingest/config")
      .then((r) => r.json())
      .then((j) => sendResponse(j))
      .catch(() => sendResponse({ selector: "", poll_ms: 1000 }));
    return true; // respuesta asíncrona
  }
  if (msg && msg.type === "captureStatus") {
    sendResponse({ ok: true, capturing: !!capturingTabId, tabId: capturingTabId, tabTitle: capturingTabTitle });
    return false;
  }
  if (msg && msg.type === "stopAudioCapture") {
    stopAudioCapture().then(sendResponse);
    return true;
  }
  if (msg && msg.type === "listTabs") {
    chrome.tabs
      .query({})
      .then((tabs) => {
        const list = tabs
          .filter((t) => /^https?:/.test(t.url || ""))
          .map((t) => ({ id: t.id, title: t.title, url: t.url, audible: !!t.audible }))
          .sort((a, b) => (b.audible ? 1 : 0) - (a.audible ? 1 : 0));
        sendResponse({ ok: true, tabs: list });
      })
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  if (msg && msg.type === "getPageHTML") {
    // Se intenta primero el documento principal (frameId 0); si esa pestana
    // no tiene ahi el content script (p.ej. no se ha refrescado todavia tras
    // recargar la extension), se reintenta sin fijar frame por si responde
    // alguno de los iframes internos.
    chrome.tabs.sendMessage(msg.tabId, { type: "getHTML" }, { frameId: 0 }, (resp) => {
      if (!chrome.runtime.lastError && resp) {
        sendResponse({ ok: true, html: resp.html, url: resp.url, title: resp.title });
        return;
      }
      chrome.tabs.sendMessage(msg.tabId, { type: "getHTML" }, (resp2) => {
        if (chrome.runtime.lastError || !resp2) {
          sendResponse({ ok: false, error: (chrome.runtime.lastError && chrome.runtime.lastError.message) || "sin respuesta" });
          return;
        }
        sendResponse({ ok: true, html: resp2.html, url: resp2.url, title: resp2.title });
      });
    });
    return true;
  }
  if (msg && msg.type === "selection") {
    fetch(API + "/api/selection/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: msg.text }),
    }).catch(() => {});
    return false;
  }
  if (msg && msg.type === "startSelectionWatch") {
    chrome.tabs.sendMessage(msg.tabId, { type: "watchSelection", watch: true }, () => {
      sendResponse({ ok: !chrome.runtime.lastError, error: chrome.runtime.lastError && chrome.runtime.lastError.message });
    });
    return true;
  }
  if (msg && msg.type === "stopSelectionWatch") {
    chrome.tabs.sendMessage(msg.tabId, { type: "watchSelection", watch: false }, () => {
      sendResponse({ ok: true });
    });
    return true;
  }
  if (msg && msg.type === "focusTab") {
    chrome.tabs
      .get(msg.tabId)
      .then((t) => chrome.tabs.update(t.id, { active: true }).then(() => chrome.windows.update(t.windowId, { focused: true })))
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === capturingTabId) stopAudioCapture();
});
