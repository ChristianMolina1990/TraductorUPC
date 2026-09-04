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

// ---------------------------- init ----------------------------

loadState().then(connectWS);
