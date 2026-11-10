// Documento offscreen: aquí sí hay DOM/getUserMedia (el service worker no los
// tiene). Captura el audio de la pestaña, lo sigue reproduciendo para que el
// usuario no se quede sin sonido, y manda clips cortos y autocontenidos
// (webm/opus) al backend para transcribir + traducir.
//
// En el canal "interpcap" (Intérprete - Captura) pide además el vídeo de la
// pestaña y, si el interruptor "Enviar captura a Claude" está activo, sube un
// fotograma JPEG cada ~5 s cuando la pantalla cambia (o al momento si se
// pulsa "Capturar ahora"). Funciona aunque la pestaña no esté visible.

const CLIP_MS = 3000;

let stream = null;      // stream completo (audio y, en interpcap, vídeo)
let audioStream = null; // solo la pista de audio: lo que se graba y se oye
let recorder = null;
let cycleTimer = null;
let apiBase = "http://localhost:8000";
let channel = "audio";
let audioEl = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "offscreen:start") start(msg.streamId, msg.api, msg.channel, !!msg.video);
  if (msg && msg.type === "offscreen:stop") stop();
});

async function start(streamId, api, ch, withVideo) {
  apiBase = api || apiBase;
  channel = ["audio", "interp", "interpcap"].includes(ch) ? ch : "audio";
  const constraints = {
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  };
  if (withVideo) {
    constraints.video = {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
        maxWidth: 1920,
        maxHeight: 1080,
        maxFrameRate: 5, // solo se necesitan fotogramas sueltos
      },
    };
  }
  stream = await navigator.mediaDevices.getUserMedia(constraints);
  audioStream = withVideo ? new MediaStream(stream.getAudioTracks()) : stream;

  // Reproducir el audio capturado para que el usuario lo siga oyendo.
  audioEl = new Audio();
  audioEl.srcObject = audioStream;
  audioEl.play().catch(() => {});

  recordOnce();
  if (withVideo) startFrames(new MediaStream(stream.getVideoTracks()));
}

function recordOnce() {
  if (!stream) return;
  const chunks = [];
  recorder = new MediaRecorder(audioStream, { mimeType: "audio/webm;codecs=opus" });
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  recorder.onstop = async () => {
    if (chunks.length) {
      const blob = new Blob(chunks, { type: "audio/webm" });
      const buf = await blob.arrayBuffer();
      fetch(`${apiBase}/api/${channel}/chunk`, {
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

// ------------------------- capturas (solo interpcap) -------------------------

const FRAME_EVERY_MS = 5000; // como mucho una captura cada 5 s
const CHECK_EVERY_MS = 1000; // consulta del interruptor / "Capturar ahora"
const MAX_SIDE = 1568;       // lado máximo que Claude usa sin recortar
const JPEG_QUALITY = 0.75;
const CHANGE_THRESHOLD = 3;  // diferencia media (0-255) para considerar que la pantalla cambió

let videoEl = null;
let frameTimer = null;
let lastFrameAt = 0;
let lastThumb = null;
let frameBusy = false;

function startFrames(videoStream) {
  videoEl = document.createElement("video");
  videoEl.muted = true;
  videoEl.playsInline = true;
  videoEl.srcObject = videoStream;
  videoEl.play().catch(() => {});
  lastFrameAt = 0;
  lastThumb = null;
  frameTimer = setInterval(frameTick, CHECK_EVERY_MS);
}

function stopFrames() {
  if (frameTimer) clearInterval(frameTimer);
  frameTimer = null;
  if (videoEl) {
    videoEl.pause();
    videoEl.srcObject = null;
    videoEl = null;
  }
  lastThumb = null;
}

async function frameTick() {
  if (frameBusy || !videoEl || !videoEl.videoWidth) return;
  frameBusy = true;
  try {
    // Con el interruptor apagado no se toma ni se sube ninguna imagen.
    const cfg = await fetch(`${apiBase}/api/interpcap/config`).then((r) => r.json());
    if (!cfg || !cfg.send_image) { lastThumb = null; return; }
    const due = Date.now() - lastFrameAt >= FRAME_EVERY_MS;
    if (!cfg.force && !due) return;

    const thumb = grayThumb();
    const changed = !lastThumb || meanDiff(thumb, lastThumb) > CHANGE_THRESHOLD;
    lastFrameAt = Date.now();
    if (!cfg.force && !changed) return;

    const blob = await grabJpeg();
    if (!blob) return;
    lastThumb = thumb;
    await fetch(`${apiBase}/api/interpcap/frame`, {
      method: "POST",
      headers: { "Content-Type": "image/jpeg" },
      body: await blob.arrayBuffer(),
    });
  } catch (e) {
    // backend no disponible o fotograma no listo: se reintenta en el siguiente tick
  } finally {
    frameBusy = false;
  }
}

function grabJpeg() {
  const w = videoEl.videoWidth, h = videoEl.videoHeight;
  const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  canvas.getContext("2d").drawImage(videoEl, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
}

// Miniatura en gris de 32x18 para detectar si la pantalla cambió.
function grayThumb() {
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 18;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(videoEl, 0, 0, 32, 18);
  const d = ctx.getImageData(0, 0, 32, 18).data;
  const out = new Uint8Array(32 * 18);
  for (let i = 0; i < out.length; i++) {
    out[i] = (d[i * 4] * 0.299 + d[i * 4 + 1] * 0.587 + d[i * 4 + 2] * 0.114) | 0;
  }
  return out;
}

function meanDiff(a, b) {
  let sum = 0;
  for (let i = 0; i < a.length; i++) sum += Math.abs(a[i] - b[i]);
  return sum / a.length;
}

// -----------------------------------------------------------------------------

function stop() {
  if (cycleTimer) clearTimeout(cycleTimer);
  cycleTimer = null;
  if (recorder && recorder.state !== "inactive") {
    recorder.onstop = null;
    recorder.stop();
  }
  recorder = null;
  stopFrames();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  audioStream = null;
  if (audioEl) {
    audioEl.pause();
    audioEl.srcObject = null;
    audioEl = null;
  }
}
