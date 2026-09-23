"""API + servidor web. Ejecutar con:  py run.py   (o  uvicorn backend.main:app )"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import page_translate
from . import translate as mt
from .audio_pipeline import AudioPipeline
from .capture import Capture
from .config import Settings, MODELS_DIR, PROFILE_DIR
from .ingest import ingest
from .interp_pipeline import InterpreterPipeline
from .pipeline import Pipeline
from .selection_pipeline import SelectionPipeline

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Traductor de transcripciones en vivo")
# La extension de Chrome hace POST desde la pagina de la clase (otro origen).
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

settings = Settings.load()
capture = Capture(
    attach_mode=settings.attach_mode,
    cdp_url=settings.cdp_url,
    profile_dir=str(PROFILE_DIR),
)

_clients: set[WebSocket] = set()


async def broadcast(message: dict) -> None:
    dead = []
    for ws in list(_clients):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


pipeline = Pipeline(capture, settings, broadcast)
audio_pipeline = AudioPipeline(settings, broadcast)
selection_pipeline = SelectionPipeline(settings, broadcast)
interp_pipeline = InterpreterPipeline(settings, broadcast)


@app.on_event("startup")
async def _startup() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    # Instala cualquier modelo .argosmodel que el usuario haya dejado en models/
    await asyncio.to_thread(mt.sync_local_models, MODELS_DIR)


@app.on_event("shutdown")
async def _shutdown() -> None:
    with contextlib.suppress(Exception):
        await pipeline.stop()
    with contextlib.suppress(Exception):
        await audio_pipeline.stop()
    with contextlib.suppress(Exception):
        await selection_pipeline.stop()
    with contextlib.suppress(Exception):
        await interp_pipeline.stop()
    with contextlib.suppress(Exception):
        await capture.stop()


# ----------------------------- API REST -----------------------------

@app.get("/api/state")
async def get_state():
    public_settings = {k: v for k, v in settings.__dict__.items() if k != "anthropic_api_key"}
    return {
        "settings": public_settings,
        "pipeline": pipeline.snapshot(),
        "audio_pipeline": audio_pipeline.snapshot(),
        "languages": mt.installed_languages(),
        "pairs": mt.installed_pairs(),
        "can_translate": mt.can_translate(settings.from_code, settings.to_code),
        "can_translate_audio": mt.can_translate(settings.audio_from_code, settings.audio_to_code),
        "can_translate_page": mt.can_translate(settings.page_from_code, settings.page_to_code),
        "selection_pipeline": selection_pipeline.snapshot(),
        "can_translate_selection": mt.can_translate(settings.sel_from_code, settings.sel_to_code),
        "interp_pipeline": interp_pipeline.snapshot(),
        "can_translate_interp": mt.can_translate(settings.interp_from_code, settings.interp_to_code),
        "has_anthropic_key": bool(settings.anthropic_api_key),
        "ingest": {"age": round(ingest.age(), 1), "chars": len(ingest.text),
                   "source_url": ingest.source_url},
    }


# ------------------- Ingesta desde la extension de Chrome -------------------

@app.post("/api/ingest")
async def api_ingest(payload: dict):
    ingest.push((payload or {}).get("text", ""), (payload or {}).get("url", ""))
    return {"ok": True}


@app.get("/api/ingest/config")
async def api_ingest_config():
    """La extension consulta aqui que selector CSS usar (vacio = automatico)."""
    return {"selector": settings.selector, "poll_ms": int(max(0.3, settings.poll_interval) * 1000)}


@app.post("/api/settings")
async def update_settings(payload: dict):
    allowed = {
        "attach_mode", "cdp_url", "target_url", "selector",
        "poll_interval", "idle_flush", "from_code", "to_code",
        "audio_from_code", "audio_to_code", "whisper_model",
        "page_from_code", "page_to_code",
        "sel_from_code", "sel_to_code",
        "interp_from_code", "interp_to_code", "interp_whisper_model",
        "interp_trigger", "anthropic_api_key",
    }
    payload = {k: v for k, v in (payload or {}).items() if k in allowed}
    if payload.get("attach_mode") not in (None, "launch", "cdp", "extension"):
        payload.pop("attach_mode")
    settings.update(**payload)
    # Reflejar en Capture (surte efecto al reconectar / al proximo ensure_page).
    capture.attach_mode = settings.attach_mode
    capture.cdp_url = settings.cdp_url
    public_settings = {k: v for k, v in settings.__dict__.items() if k != "anthropic_api_key"}
    return {"ok": True, "settings": public_settings, "has_anthropic_key": bool(settings.anthropic_api_key)}


@app.get("/api/tabs")
async def list_tabs():
    try:
        return {"ok": True, "tabs": await capture.list_pages()}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc),
                     "hint": "En modo 'launch' se abrira un Chromium propio. "
                             "En modo 'cdp' arranca Chrome con --remote-debugging-port=9222."},
        )


@app.post("/api/open")
async def open_url(payload: dict):
    url = (payload or {}).get("url") or settings.target_url
    if not url:
        return JSONResponse(status_code=400, content={"ok": False, "error": "falta url"})
    try:
        await capture.open(url)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.post("/api/attach")
async def attach(payload: dict):
    url = (payload or {}).get("url") or settings.target_url
    try:
        ok = await capture.attach(url)
        return {"ok": ok, "error": None if ok else "no se encontro una pestana con esa URL"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.post("/api/pick")
async def pick():
    try:
        await capture.ensure_page(settings.target_url)
        sel = await capture.pick_element()
        if sel:
            settings.update(selector=sel)
        return {"ok": True, "selector": sel}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.get("/api/preview")
async def preview():
    """Lee el contenedor ahora mismo, sin traducir. Util para ajustar el selector."""
    if settings.attach_mode == "extension":
        fresh = ingest.age() < 8
        return {
            "ok": True, "found": fresh and bool(ingest.text),
            "text": ingest.text,
            "usedSelector": "(extension)",
            "error": None if fresh else "sin datos recientes de la extension",
        }
    try:
        await capture.ensure_page(settings.target_url)
        res = await capture.read_transcript(settings.selector)
        return {"ok": True, **res}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.post("/api/start")
async def start():
    if not mt.can_translate(settings.from_code, settings.to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False,
                     "error": f"falta el modelo de idioma {settings.from_code}->{settings.to_code}. "
                              f"Instalalo desde 'Idiomas' o con: py -m argostranslate ..."},
        )
    await pipeline.start()
    return {"ok": True}


@app.post("/api/stop")
async def stop():
    await pipeline.stop()
    return {"ok": True}


# --------------------------- Pipeline de audio ---------------------------

@app.post("/api/audio/start")
async def audio_start():
    if not mt.can_translate(settings.audio_from_code, settings.audio_to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False,
                     "error": f"falta el modelo de idioma {settings.audio_from_code}->{settings.audio_to_code}. "
                              f"Instalalo desde 'Idiomas'"},
        )
    await audio_pipeline.start()
    return {"ok": True}


@app.post("/api/audio/stop")
async def audio_stop():
    await audio_pipeline.stop()
    return {"ok": True}


@app.post("/api/audio/chunk")
async def audio_chunk(request: Request):
    data = await request.body()
    await audio_pipeline.ingest_chunk(data)
    return {"ok": True}


@app.post("/api/audio/clear")
async def audio_clear():
    await audio_pipeline.clear()
    return {"ok": True}


# --------------------------- Pipeline Intérprete ---------------------------

@app.post("/api/interp/start")
async def interp_start():
    if not mt.can_translate(settings.interp_from_code, settings.interp_to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False,
                     "error": f"falta el modelo de idioma {settings.interp_from_code}->{settings.interp_to_code}. "
                              f"Instalalo desde 'Idiomas'"},
        )
    await interp_pipeline.start()
    return {"ok": True}


@app.post("/api/interp/stop")
async def interp_stop():
    await interp_pipeline.stop()
    return {"ok": True}


@app.post("/api/interp/chunk")
async def interp_chunk(request: Request):
    data = await request.body()
    await interp_pipeline.ingest_chunk(data)
    return {"ok": True}


@app.post("/api/interp/clear")
async def interp_clear():
    await interp_pipeline.clear()
    return {"ok": True}


@app.post("/api/interp/suggest")
async def interp_suggest():
    return await interp_pipeline.suggest_manual()


# ----------------------------- Pagina (CAMBRIDGE) -----------------------------

@app.post("/api/page/translate")
async def page_translate_endpoint(payload: dict):
    html = (payload or {}).get("html") or ""
    url = (payload or {}).get("url") or ""
    from_code = (payload or {}).get("from_code") or settings.page_from_code
    to_code = (payload or {}).get("to_code") or settings.page_to_code
    if not html:
        return JSONResponse(status_code=400, content={"ok": False, "error": "falta html"})
    if not mt.can_translate(from_code, to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"falta el modelo de idioma {from_code}->{to_code}"},
        )
    try:
        translated = await asyncio.to_thread(page_translate.translate_page, html, url, from_code, to_code)
        return {"ok": True, "html": translated}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


# ------------------------- Selector (traducir seleccion) -------------------------

@app.post("/api/selection/start")
async def selection_start():
    if not mt.can_translate(settings.sel_from_code, settings.sel_to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False,
                     "error": f"falta el modelo de idioma {settings.sel_from_code}->{settings.sel_to_code}"},
        )
    await selection_pipeline.start()
    return {"ok": True}


@app.post("/api/selection/stop")
async def selection_stop():
    await selection_pipeline.stop()
    return {"ok": True}


@app.post("/api/selection/clear")
async def selection_clear():
    await selection_pipeline.clear()
    return {"ok": True}


@app.post("/api/selection/ingest")
async def selection_ingest(payload: dict):
    await selection_pipeline.ingest((payload or {}).get("text", ""))
    return {"ok": True}


@app.post("/api/selection/manual")
async def selection_manual(payload: dict):
    text = (payload or {}).get("text", "")
    if not mt.can_translate(settings.sel_from_code, settings.sel_to_code):
        return JSONResponse(
            status_code=400,
            content={"ok": False,
                     "error": f"falta el modelo de idioma {settings.sel_from_code}->{settings.sel_to_code}"},
        )
    await selection_pipeline.ingest_manual(text)
    return {"ok": True}


# ------------------------- Gestion de idiomas -------------------------

@app.get("/api/languages")
async def languages():
    return {"installed": mt.installed_languages(), "pairs": mt.installed_pairs()}


@app.post("/api/languages/sync-local")
async def languages_sync_local():
    added = await asyncio.to_thread(mt.sync_local_models, MODELS_DIR)
    return {"ok": True, "processed": added, "pairs": mt.installed_pairs()}


@app.get("/api/languages/available")
async def languages_available():
    try:
        return {"ok": True, "available": await asyncio.to_thread(mt.available_from_index)}
    except Exception as exc:
        return JSONResponse(status_code=500,
                            content={"ok": False, "error": f"requiere internet: {exc}"})


@app.post("/api/languages/install")
async def languages_install(payload: dict):
    fc, tc = (payload or {}).get("from_code"), (payload or {}).get("to_code")
    if not fc or not tc:
        return JSONResponse(status_code=400, content={"ok": False, "error": "faltan codigos"})
    try:
        msg = await asyncio.to_thread(mt.install_from_index, fc, tc)
        return {"ok": True, "message": msg, "pairs": mt.installed_pairs()}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


# ----------------------------- WebSocket -----------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        # Enviar estado inicial + historial
        await ws.send_json({"type": "snapshot", **pipeline.snapshot()})
        await ws.send_json({"type": "audio_snapshot", **audio_pipeline.snapshot()})
        await ws.send_json({"type": "selection_snapshot", **selection_pipeline.snapshot()})
        await ws.send_json({"type": "interp_snapshot", **interp_pipeline.snapshot()})
        while True:
            await ws.receive_text()  # no esperamos mensajes; mantiene viva la conexion
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


# --------------------------- Frontend estatico ---------------------------

@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND)), name="static")
