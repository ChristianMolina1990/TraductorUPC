// Service worker: reenvía el texto al backend local. No está sujeto al CSP de
// la página, por eso el fetch va aquí y no en el content script.

const API = "http://localhost:8000";

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
  return false;
});
