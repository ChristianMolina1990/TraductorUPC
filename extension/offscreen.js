// Documento offscreen: aquí sí hay DOM/getUserMedia (el service worker no los
// tiene). Captura el audio de la pestaña, lo sigue reproduciendo para que el
// usuario no se quede sin sonido, y manda clips cortos y autocontenidos
// (webm/opus) al backend para transcribir + traducir.

const CLIP_MS = 3000;

let stream = null;
let recorder = null;
let cycleTimer = null;
let apiBase = "http://localhost:8000";
let audioEl = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "offscreen:start") start(msg.streamId, msg.api);
  if (msg && msg.type === "offscreen:stop") stop();
});

async function start(streamId, api) {
  apiBase = api || apiBase;
  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // Reproducir el audio capturado para que el usuario lo siga oyendo.
  audioEl = new Audio();
  audioEl.srcObject = stream;
  audioEl.play().catch(() => {});

  recordOnce();
}

function recordOnce() {
  if (!stream) return;
  const chunks = [];
  recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  recorder.onstop = async () => {
    if (chunks.length) {
      const blob = new Blob(chunks, { type: "audio/webm" });
      const buf = await blob.arrayBuffer();
      fetch(apiBase + "/api/audio/chunk", {
        method: "POST",
        headers: { "Content-Type": "audio/webm" },
        body: buf,
      }).catch(() => {});
    }
    recordOnce(); // encadenar el siguiente clip mientras stream siga vivo
  };
  // Un salto/pausa brusca en el video puede cortar momentáneamente la pista de
  // audio; en vez de dejar el pipeline colgado, se descarta ese clip y se
  // sigue con el siguiente.
  recorder.onerror = () => recordOnce();
  recorder.start();
  cycleTimer = setTimeout(() => {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, CLIP_MS);
}

function stop() {
  if (cycleTimer) clearTimeout(cycleTimer);
  cycleTimer = null;
  if (recorder && recorder.state !== "inactive") {
    recorder.onstop = null;
    recorder.stop();
  }
  recorder = null;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (audioEl) {
    audioEl.pause();
    audioEl.srcObject = null;
    audioEl = null;
  }
}
