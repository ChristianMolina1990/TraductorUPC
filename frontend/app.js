const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let settings = {};
let langs = [];

// ---------------------------- estado / websocket ----------------------------

function setStatus(text, kind) {
  $("status").textContent = text;
  const dot = $("dot");
  dot.className = "dot" + (kind ? " " + kind : "");
}

function fmtTime(ts) {
  const d = new Date((ts || Date.now() / 1000) * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function addLine(col, text, ts, fresh) {
  const div = document.createElement("div");
  div.className = "line" + (fresh ? " fresh" : "");
  div.innerHTML = `<span class="t">${fmtTime(ts)}</span>`;
  div.appendChild(document.createTextNode(text));
  col.appendChild(div);
  col.scrollTop = col.scrollHeight;
}

let ws;
function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "snapshot") {
      $("colOriginal").innerHTML = "";
      $("colTranslated").innerHTML = "";
      (m.history || []).forEach((h) => {
        addLine($("colOriginal"), h.original, h.ts, false);
        addLine($("colTranslated"), h.translated, h.ts, false);
      });
      $("interim").textContent = m.interim || "";
      applyRunning(m.running);
      if (m.status) setStatus(m.status, m.running ? "on" : null);
    } else if (m.type === "segment") {
      addLine($("colOriginal"), m.original, m.ts, true);
      addLine($("colTranslated"), m.translated, m.ts, true);
    } else if (m.type === "interim") {
      $("interim").textContent = m.text || "";
    } else if (m.type === "status") {
      const kind = m.status.startsWith("error") ? "err" : m.status.startsWith("aviso") || m.status.startsWith("no se") ? "warn" : m.running ? "on" : null;
      setStatus(m.status, kind);
      applyRunning(m.running);
    } else if (m.type === "audio_snapshot") {
      $("audioColOriginal").innerHTML = "";
      $("audioColTranslated").innerHTML = "";
      (m.history || []).forEach((h) => {
        addLine($("audioColOriginal"), h.original, h.ts, false);
        addLine($("audioColTranslated"), h.translated, h.ts, false);
      });
      applyAudioRunning(m.running);
      if (m.status) setAudioStatus(m.status, m.running ? "on" : null);
    } else if (m.type === "audio_segment") {
      addLine($("audioColOriginal"), m.original, m.ts, true);
      addLine($("audioColTranslated"), m.translated, m.ts, true);
    } else if (m.type === "audio_status") {
      const kind = m.status.startsWith("error") ? "err" : m.running ? "on" : null;
      setAudioStatus(m.status, kind);
      applyAudioRunning(m.running);
    } else if (m.type === "selection_snapshot") {
      $("selColOriginal").innerHTML = "";
      $("selColTranslated").innerHTML = "";
      (m.history || []).forEach((h) => {
        addLine($("selColOriginal"), h.original, h.ts, false);
        addLine($("selColTranslated"), h.translated, h.ts, false);
      });
      applySelRunning(m.running);
      if (m.status) setSelStatus(m.status, m.running ? "on" : null);
    } else if (m.type === "selection_segment") {
      addLine($("selColOriginal"), m.original, m.ts, true);
      addLine($("selColTranslated"), m.translated, m.ts, true);
    } else if (m.type === "selection_status") {
      const kind = m.status.startsWith("error") ? "err" : m.running ? "on" : null;
      setSelStatus(m.status, kind);
      applySelRunning(m.running);
    }
  };
  ws.onclose = () => { setStatus("desconectado — reintentando…", "err"); setTimeout(connectWS, 1500); };
}

function applyRunning(running) {
  $("btnStart").disabled = !!running;
  $("btnStop").disabled = !running;
}

// ---------------------------- configuración ----------------------------

function fillLangSelect(sel, value) {
  sel.innerHTML = "";
  langs.forEach((l) => {
    const o = document.createElement("option");
    o.value = l.code; o.textContent = `${l.name} (${l.code})`;
    sel.appendChild(o);
  });
  if (value) sel.value = value;
}

async function loadState() {
  const s = await api("/api/state");
  settings = s.settings;
  langs = s.languages || [];
  $("attachMode").value = settings.attach_mode || "launch";
  $("targetUrl").value = settings.target_url || "";
  $("selector").value = settings.selector || "";
  $("pollInterval").value = settings.poll_interval;
  $("idleFlush").value = settings.idle_flush;
  fillLangSelect($("fromCode"), settings.from_code);
  fillLangSelect($("toCode"), settings.to_code);
  $("toLabel").textContent = settings.to_code;
  applyMode();
  applyRunning(s.pipeline.running);
  if (!s.can_translate) {
    setStatus(`falta modelo ${settings.from_code}→${settings.to_code} · abre “Idiomas…”`, "warn");
  }
  renderPairs(s.pairs || []);

  fillLangSelect($("audioFromCode"), settings.audio_from_code);
  fillLangSelect($("audioToCode"), settings.audio_to_code);
  $("audioToLabel").textContent = settings.audio_to_code;
  $("whisperModel").value = settings.whisper_model || "base";

  fillLangSelect($("pageFromCode"), settings.page_from_code);
  fillLangSelect($("pageToCode"), settings.page_to_code);
  if (!s.can_translate_page) {
    setPageStatus(`falta modelo ${settings.page_from_code}→${settings.page_to_code} · abre “Idiomas…”`, "warn");
  }
  applyAudioRunning(s.audio_pipeline.running);
  if (s.audio_pipeline.status) setAudioStatus(s.audio_pipeline.status, s.audio_pipeline.running ? "on" : null);
  if (!s.can_translate_audio) {
    setAudioStatus(`falta modelo ${settings.audio_from_code}→${settings.audio_to_code} · abre “Idiomas…”`, "warn");
  }

  fillLangSelect($("selFromCode"), settings.sel_from_code);
  fillLangSelect($("selToCode"), settings.sel_to_code);
  $("selToLabel").textContent = settings.sel_to_code;
  applySelRunning(s.selection_pipeline.running);
  if (s.selection_pipeline.status) setSelStatus(s.selection_pipeline.status, s.selection_pipeline.running ? "on" : null);
  if (!s.can_translate_selection) {
    setSelStatus(`falta modelo ${settings.sel_from_code}→${settings.sel_to_code} · abre “Idiomas…”`, "warn");
  }
}

function collectSettings() {
  return {
    attach_mode: $("attachMode").value,
    target_url: $("targetUrl").value.trim(),
    selector: $("selector").value.trim(),
    poll_interval: parseFloat($("pollInterval").value) || 1.0,
    idle_flush: parseFloat($("idleFlush").value) || 2.0,
    from_code: $("fromCode").value,
    to_code: $("toCode").value,
  };
}
const saveSettings = () => postJSON("/api/settings", collectSettings());

function applyMode() {
  const mode = $("attachMode").value;
  document.querySelectorAll("[data-mode]").forEach((el) => {
    el.style.display = el.getAttribute("data-mode") === mode ? "" : "none";
  });
  // "Elegir en la página" solo funciona con navegador controlado por Playwright.
  $("btnPick").disabled = mode === "extension";
}

async function pollExtStatus() {
  if ($("attachMode").value !== "extension") return;
  try {
    const s = await api("/api/state");
    const g = s.ingest || {};
    const el = $("extStatus");
    if (g.chars > 0 && g.age < 8) {
      el.textContent = `✓ señal recibida (${g.chars} caracteres, hace ${g.age}s)`;
      el.classList.add("ok");
    } else {
      el.textContent = "esperando señal de la extensión… (¿pestaña de la clase abierta y recargada?)";
      el.classList.remove("ok");
    }
  } catch (e) {}
}
setInterval(pollExtStatus, 2000);

// ---------------------------- eventos UI ----------------------------

$("btnConfig").onclick = () => $("config").classList.toggle("open");

["attachMode", "targetUrl", "selector", "pollInterval", "idleFlush", "fromCode", "toCode"].forEach((id) => {
  $(id).addEventListener("change", async () => {
    applyMode();
    await saveSettings();
    $("toLabel").textContent = $("toCode").value;
  });
});

$("btnOpen").onclick = async () => {
  await saveSettings();
  setStatus("abriendo…");
  const r = await postJSON("/api/open", { url: $("targetUrl").value.trim() });
  setStatus(r.ok ? "página abierta — inicia sesión si hace falta" : (r.error || "error"), r.ok ? null : "err");
};

$("btnTabs").onclick = async () => {
  setStatus("listando pestañas…");
  const r = await api("/api/tabs");
  const sel = $("tabs");
  if (!r.ok) { setStatus(r.error || "no se pudo listar (¿Chrome con :9222?)", "err"); return; }
  sel.innerHTML = '<option value="">— elegir pestaña —</option>';
  r.tabs.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.url;
    o.textContent = (t.title || t.url).slice(0, 90);
    sel.appendChild(o);
  });
  setStatus(`${r.tabs.length} pestañas`);
};

$("btnAttach").onclick = async () => {
  const url = $("tabs").value;
  if (!url) { setStatus("elige una pestaña primero", "warn"); return; }
  $("targetUrl").value = url;
  await saveSettings();
  const r = await postJSON("/api/attach", { url });
  setStatus(r.ok ? "✓ enganchado a la pestaña" : (r.error || "no se pudo enganchar"), r.ok ? null : "err");
};

$("btnPick").onclick = async () => {
  await saveSettings();
  setStatus("haz clic en el panel de subtítulos dentro del navegador de captura…", "warn");
  const r = await postJSON("/api/pick", {});
  if (r.ok && r.selector) {
    $("selector").value = r.selector;
    await saveSettings();
    setStatus("selector fijado: " + r.selector);
  } else {
    setStatus(r.error || "no se eligió ningún elemento", "warn");
  }
};

$("btnPreview").onclick = async () => {
  await saveSettings();
  const r = await api("/api/preview");
  const box = $("preview");
  box.classList.remove("hidden");
  if (!r.ok) { box.textContent = "error: " + r.error; return; }
  box.textContent =
    `selector usado: ${r.usedSelector || "(ninguno)"}\nencontrado: ${r.found}\n\n` +
    (r.text || "(sin texto)").slice(0, 1200);
};

$("btnStart").onclick = async () => {
  await saveSettings();
  const r = await postJSON("/api/start", {});
  if (!r.ok) setStatus(r.error || "no se pudo iniciar", "err");
};
$("btnStop").onclick = () => postJSON("/api/stop", {});

// ---------------------------- diálogo de idiomas ----------------------------

function renderPairs(pairs) {
  const ul = $("pairList");
  ul.innerHTML = pairs.length ? "" : '<li class="muted">— ninguno instalado —</li>';
  pairs.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${p.name}</span><span class="muted">${p.from_code}→${p.to_code}</span>`;
    ul.appendChild(li);
  });
}

$("btnLangs").onclick = () => $("langModal").classList.remove("hidden");
$("btnCloseLangs").onclick = () => $("langModal").classList.add("hidden");

$("btnSyncLocal").onclick = async () => {
  const r = await postJSON("/api/languages/sync-local", {});
  renderPairs(r.pairs || []);
  await loadState();
  alert("Procesado:\n" + (r.processed || []).join("\n") || "(sin archivos .argosmodel en models/)");
};

$("btnLoadIndex").onclick = async () => {
  const ul = $("availList");
  ul.innerHTML = '<li class="muted">cargando…</li>';
  const r = await api("/api/languages/available");
  if (!r.ok) { ul.innerHTML = `<li class="muted">${r.error}</li>`; return; }
  ul.innerHTML = "";
  r.available.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${p.from_name} → ${p.to_name}</span>`;
    const b = document.createElement("button");
    b.className = "ghost"; b.textContent = "Instalar";
    b.onclick = async () => {
      b.disabled = true; b.textContent = "instalando…";
      const res = await postJSON("/api/languages/install", { from_code: p.from_code, to_code: p.to_code });
      b.textContent = res.ok ? "✓ instalado" : "error";
      if (res.ok) { renderPairs(res.pairs || []); await loadState(); }
    };
    li.appendChild(b);
    ul.appendChild(li);
  });
};

// ---------------------------- vista Audio ----------------------------

function setAudioStatus(text, kind) {
  $("audioStatus").textContent = text;
  $("audioDot").className = "dot" + (kind ? " " + kind : "");
}

function applyAudioRunning(running) {
  $("btnAudioStop").disabled = !running;
}

// Puente con la extensión de Chrome: la página no puede llamar a chrome.tabs /
// chrome.tabCapture directamente, así que pasa mensajes por content.js.
let _extReqId = 0;
const _extPending = new Map();
let _extReady = false;

window.addEventListener("message", (event) => {
  if (event.source !== window || !event.data) return;
  if (event.data.__traductorReady) _extReady = true;
  if (event.data.__traductorResponse) {
    const cb = _extPending.get(event.data.requestId);
    if (cb) { _extPending.delete(event.data.requestId); cb(event.data.payload); }
  }
});

function extCall(type, extra) {
  return new Promise((resolve) => {
    const requestId = ++_extReqId;
    _extPending.set(requestId, resolve);
    window.postMessage(Object.assign({ __traductor: true, type, requestId }, extra || {}), "*");
    setTimeout(() => {
      if (_extPending.has(requestId)) { _extPending.delete(requestId); resolve(null); }
    }, 4000);
  });
}

async function saveAudioSettings() {
  return postJSON("/api/settings", {
    audio_from_code: $("audioFromCode").value,
    audio_to_code: $("audioToCode").value,
    whisper_model: $("whisperModel").value,
  });
}

["audioFromCode", "audioToCode", "whisperModel"].forEach((id) => {
  $(id).addEventListener("change", async () => {
    await saveAudioSettings();
    $("audioToLabel").textContent = $("audioToCode").value;
  });
});

async function pollCaptureStatus() {
  const extStatus = $("extAudioStatus");
  const r = await extCall("captureStatus");
  if (!r) {
    extStatus.textContent = "no se detectó la extensión — instálala/recárgala (ver extension/README.md) y recarga esta página";
    extStatus.classList.remove("ok");
    return;
  }
  if (r.capturing) {
    extStatus.textContent = `✓ capturando: ${(r.tabTitle || "").slice(0, 80)}`;
    extStatus.classList.add("ok");
  } else {
    extStatus.textContent = "✓ extensión detectada — ve a la pestaña con el audio y haz clic en su icono para empezar";
    extStatus.classList.add("ok");
  }
  applyAudioRunning(r.capturing);
}
setInterval(pollCaptureStatus, 2000);

function renderAudioTabList(tabs, capturingTabId) {
  const ul = $("audioTabList");
  if (!tabs.length) { ul.innerHTML = '<li class="muted">— no hay pestañas abiertas —</li>'; return; }
  ul.innerHTML = "";
  tabs.forEach((t) => {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = ((t.audible ? "🔊 " : "") + (t.title || t.url)).slice(0, 90);
    li.appendChild(label);
    if (t.id === capturingTabId) {
      const tag = document.createElement("span");
      tag.className = "muted";
      tag.textContent = "● capturando";
      li.appendChild(tag);
    } else {
      const b = document.createElement("button");
      b.className = "ghost";
      b.textContent = "Ir a esta pestaña";
      b.onclick = async () => {
        b.disabled = true;
        const r = await extCall("focusTab", { tabId: t.id });
        b.disabled = false;
        if (!r || !r.ok) return;
        setAudioStatus("pestaña activada — haz clic en el icono de la extensión para capturarla");
      };
      li.appendChild(b);
    }
    ul.appendChild(li);
  });
}

$("btnAudioTabs").onclick = async () => {
  setAudioStatus("listando pestañas…");
  const [tabsRes, statusRes] = await Promise.all([extCall("listTabs"), extCall("captureStatus")]);
  if (!tabsRes || !tabsRes.ok) {
    setAudioStatus("no se pudo listar pestañas (¿extensión instalada/recargada?)", "err");
    return;
  }
  renderAudioTabList(tabsRes.tabs, statusRes && statusRes.tabId);
  setAudioStatus(`${tabsRes.tabs.length} pestañas`);
};

$("btnAudioStop").onclick = async () => {
  await extCall("stopAudioCapture");
  await postJSON("/api/audio/stop", {});
};

$("btnAudioClear").onclick = async () => {
  $("audioColOriginal").innerHTML = "";
  $("audioColTranslated").innerHTML = "";
  await postJSON("/api/audio/clear", {});
};

// ---------------------------- vista CAMBRIDGE (espejo de página) ----------------------------

function setPageStatus(text, kind) {
  $("pageStatus").textContent = text;
  $("pageDot").className = "dot" + (kind ? " " + kind : "");
}

async function saveCambridgeSettings() {
  return postJSON("/api/settings", {
    page_from_code: $("pageFromCode").value,
    page_to_code: $("pageToCode").value,
  });
}

["pageFromCode", "pageToCode"].forEach((id) => {
  $(id).addEventListener("change", saveCambridgeSettings);
});

$("btnPageTabs").onclick = async () => {
  setPageStatus("listando pestañas…");
  const r = await extCall("listTabs");
  const sel = $("pageTabs");
  const extStatus = $("extPageStatus");
  if (!r || !r.ok) {
    setPageStatus("no se pudo listar pestañas", "err");
    extStatus.textContent = "no se detectó la extensión — instálala/recárgala (ver extension/README.md) y recarga esta página";
    extStatus.classList.remove("ok");
    return;
  }
  extStatus.textContent = "✓ extensión detectada";
  extStatus.classList.add("ok");
  sel.innerHTML = '<option value="">— elegir pestaña —</option>';
  r.tabs.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.id;
    o.textContent = ((t.audible ? "🔊 " : "") + (t.title || t.url)).slice(0, 90);
    sel.appendChild(o);
  });
  setPageStatus(`${r.tabs.length} pestañas`);
};

let _pageTimer = null;
let _pageLastHtml = "";

async function pageFetchAndRender(tabId) {
  const r = await extCall("getPageHTML", { tabId: parseInt(tabId, 10) });
  if (!r) {
    setPageStatus("la extensión no respondió — recárgala y refresca esta página", "err");
    return;
  }
  if (!r.ok) {
    setPageStatus("no se pudo leer la pestaña: " + (r.error || "desconocido") + " — recarga la extensión y esa pestaña", "err");
    return;
  }
  if (!r.html) {
    setPageStatus("la pestaña no devolvió HTML — recarga esa pestaña e inténtalo de nuevo", "warn");
    return;
  }
  if (r.html === _pageLastHtml) return; // sin cambios: no retraducir de balde
  _pageLastHtml = r.html;
  setPageStatus("traduciendo página…");
  const res = await postJSON("/api/page/translate", {
    html: r.html,
    url: r.url,
    from_code: $("pageFromCode").value,
    to_code: $("pageToCode").value,
  });
  if (!res.ok) {
    setPageStatus(res.error || "no se pudo traducir", "err");
    return;
  }
  $("pageFrame").srcdoc = res.html;
  setPageStatus(`traducido — ${(r.title || "").slice(0, 60)}`, "on");
}

$("btnPageStart").onclick = async () => {
  const tabId = $("pageTabs").value;
  if (!tabId) { setPageStatus("elige una pestaña primero", "warn"); return; }
  await saveCambridgeSettings();
  _pageLastHtml = "";
  $("btnPageStart").disabled = true;
  $("btnPageStop").disabled = false;
  await pageFetchAndRender(tabId);
  _pageTimer = setInterval(() => pageFetchAndRender(tabId), 4000);
};

$("btnPageStop").onclick = () => {
  if (_pageTimer) clearInterval(_pageTimer);
  _pageTimer = null;
  $("btnPageStart").disabled = false;
  $("btnPageStop").disabled = true;
  setPageStatus("detenido");
};

// ---------------------------- vista Selector ----------------------------

function setSelStatus(text, kind) {
  $("selStatus").textContent = text;
  $("selDot").className = "dot" + (kind ? " " + kind : "");
}

function applySelRunning(running) {
  $("btnSelStart").disabled = !!running;
  $("btnSelStop").disabled = !running;
}

async function saveSelSettings() {
  return postJSON("/api/settings", {
    sel_from_code: $("selFromCode").value,
    sel_to_code: $("selToCode").value,
  });
}

["selFromCode", "selToCode"].forEach((id) => {
  $(id).addEventListener("change", async () => {
    await saveSelSettings();
    $("selToLabel").textContent = $("selToCode").value;
  });
});

$("btnSelTabs").onclick = async () => {
  setSelStatus("listando pestañas…");
  const r = await extCall("listTabs");
  const sel = $("selTabs");
  const extStatus = $("extSelStatus");
  if (!r || !r.ok) {
    setSelStatus("no se pudo listar pestañas", "err");
    extStatus.textContent = "no se detectó la extensión — instálala/recárgala (ver extension/README.md) y recarga esta página";
    extStatus.classList.remove("ok");
    return;
  }
  extStatus.textContent = "✓ extensión detectada";
  extStatus.classList.add("ok");
  sel.innerHTML = '<option value="">— elegir pestaña —</option>';
  r.tabs.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.id;
    o.textContent = (t.title || t.url).slice(0, 90);
    sel.appendChild(o);
  });
  setSelStatus(`${r.tabs.length} pestañas`);
};

let _selWatchingTabId = null;

$("btnSelStart").onclick = async () => {
  const tabId = $("selTabs").value;
  if (!tabId) { setSelStatus("elige una pestaña primero", "warn"); return; }
  await saveSelSettings();
  const r = await extCall("startSelectionWatch", { tabId: parseInt(tabId, 10) });
  if (!r || !r.ok) {
    setSelStatus((r && r.error) || "no se pudo activar en esa pestaña (¿recargaste la extensión y la pestaña?)", "err");
    return;
  }
  _selWatchingTabId = parseInt(tabId, 10);
  const back = await postJSON("/api/selection/start", {});
  if (!back.ok) {
    setSelStatus(back.error || "no se pudo iniciar", "err");
    await extCall("stopSelectionWatch", { tabId: _selWatchingTabId });
    return;
  }
  setSelStatus("selecciona texto en esa pestaña…", "on");
  applySelRunning(true);
};

$("btnSelStop").onclick = async () => {
  if (_selWatchingTabId != null) await extCall("stopSelectionWatch", { tabId: _selWatchingTabId });
  _selWatchingTabId = null;
  await postJSON("/api/selection/stop", {});
};

$("btnSelClear").onclick = async () => {
  $("selColOriginal").innerHTML = "";
  $("selColTranslated").innerHTML = "";
  await postJSON("/api/selection/clear", {});
};

async function sendManualSelection() {
  const input = $("selManualInput");
  const text = input.value.trim();
  if (!text) return;
  const r = await postJSON("/api/selection/manual", { text });
  if (!r.ok) { setSelStatus(r.error || "no se pudo traducir", "err"); return; }
  input.value = "";
}
$("btnSelManual").onclick = sendManualSelection;
$("selManualInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendManualSelection();
});

// ---------------------------- menú Traductor ----------------------------

function showView(name) {
  $("viewTexto").classList.toggle("hidden", name !== "texto");
  $("viewAudio").classList.toggle("hidden", name !== "audio");
  $("viewCambridge").classList.toggle("hidden", name !== "cambridge");
  $("viewSelector").classList.toggle("hidden", name !== "selector");
  $("menuTexto").classList.toggle("active", name === "texto");
  $("menuAudio").classList.toggle("active", name === "audio");
  $("menuCambridge").classList.toggle("active", name === "cambridge");
  $("menuSelector").classList.toggle("active", name === "selector");
}
$("menuTexto").onclick = () => showView("texto");
$("menuAudio").onclick = () => showView("audio");
$("menuCambridge").onclick = () => showView("cambridge");
$("menuSelector").onclick = () => showView("selector");

// ---------------------------- init ----------------------------

loadState().then(connectWS);
pollCaptureStatus();
