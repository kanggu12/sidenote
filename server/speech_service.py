"""The speech service: the speech model (faster-whisper, with its voice detector) as a program of its own, which the server
asks over HTTP (server/transcriber.py, RemoteTranscriber; SIDENOTE_SPEECH_URL).

Why apart from the server: the decoder runs native threads in the process that holds it, and a fork from that process
while they ran once wedged the server for 95 minutes (server/forksafe.py, which the server then needed around every
decode and every start of an agent's CLI). Its two models take about 1.8 GB, and loading another one (the panel's
Speech model) took the server's CPU while answers were being written. Here it has its own process, its own memory and
CPU limits, and starts again on its own; the server keeps all it does with what was heard (the utterances, the
questions, the answers), and this keeps nothing.

    python -m uvicorn server.speech_service:app --host 0.0.0.0 --port 8779

One client, the server. No sign-in: it answers only on the services' own network (compose's speechnet, internal, which the
server alone shares, and no port on the host; the chart's NetworkPolicy lets the server alone in), as the local model's
server does, and it loads only the models the panel offers. Nothing heard is written to its log: what it hears is the
room's speech.

    GET  /health                     the model in use, the one asked for (`wanted`), the one loading, and the last
                                     failure to load (`error`, about `failed`)
    POST /load        {"model", "restore", "defer"}  ask for that model: "" for SIDENOTE_WHISPER_MODEL, else one the
                                     panel offers (config.py, SPEECH_MODELS). 200 with the health when it is in use
                                     already, else 202: it is fetched the first time and loaded beside the one in use,
                                     which goes on hearing, and the client follows it in /health. A later ask takes the
                                     place of one not loaded yet. "restore": a client's model back in a service found
                                     without one, taken only while none is in use, loading or asked for. "defer": the
                                     server's start, taken only while no other model is loading or asked for. Both
                                     otherwise answer the health as it is. Every answer says the model asked (`asked`)
    POST /segments?sr=16000          the speech spans of 16-bit mono PCM in the body: {"spans": [[start, end], ...]}
    POST /transcribe?sr=16000&live=0 the words of 16-bit mono PCM in the body: {"text", "last_language", "language"}
    PUT  /language    {"value"}      "auto", "ko" or "en"; a new choice starts the session's vote over
    PUT  /hints       {"hint", "extra"}  the built-in term lists (or none) and the person's Extra terms

/segments and /transcribe answer 409 while no model is loaded (a service that started again): the server loads its
own again and asks once more.
"""
from __future__ import annotations

import logging
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import CONFIG, SPEECH_MODELS
from .transcriber import NullTranscriber, give_back_memory, make_transcriber
from .version import VERSION

# Its log, as the server's (server/app.py): the models loaded and why one could not be, at INFO; never a word heard, which
# no line here or in the model's code (server/transcriber.py) writes above DEBUG
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
for _noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):   # a model's download logs every request at INFO
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("sidenote.speech")
app = FastAPI(title="sidenote-speech", docs_url=None, redoc_url=None, openapi_url=None)

# One decode at a time, as the server's one speech loop asks for them: the model's own threads are its CPU limit
_DECODE = threading.Lock()
# What there is and what is asked for, read and changed together (never held while waiting on _DECODE: taken after it)
_STATE_LOCK = threading.Lock()
_STATE: dict = {"tr": NullTranscriber(), "wanted": "", "loading": "", "error": "", "failed": ""}
# One loader: the model asked for last is the one loaded and put in use, one load at a time. A request only says what is
# wanted and answers at once; a load held in a request for minutes (a first download) outlived the client's wait, and
# several requests waiting on each other's loads took locks that were hard to follow
_WAKE = threading.Event()
MAX_BODY = 16000 * 2 * 60   # a minute of 16 kHz 16-bit sound: the server sends a sentence, or the live line's window


def _model():
    return _STATE["tr"]


def _status() -> dict:
    with _STATE_LOCK:
        return _status_now()


def _status_now() -> dict:
    """The health, under _STATE_LOCK."""
    tr = _STATE["tr"]
    return {"ok": True, "service": "speech", "version": VERSION, "available": bool(getattr(tr, "available", False)),
            "model": getattr(tr, "model_name", ""), "live_model": getattr(tr, "live_name", ""),
            "language": getattr(tr, "language", None), "wanted": _STATE["wanted"], "loading": _STATE["loading"],
            "error": _STATE["error"], "failed": _STATE["failed"]}


async def _pcm(request: Request) -> bytes:
    """The sound in the body, refused past a minute: no sentence is that long, and the body is read whole."""
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "more than a minute of sound")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "more than a minute of sound")
    return body


def _loaded():
    """The model in use, or 409 when there is none: the server then loads its own again."""
    tr = _model()
    if not getattr(tr, "available", False):
        raise HTTPException(409, "no speech model is loaded")
    return tr


@app.get("/health")
def health() -> dict:
    return _status()


def _offered(name: str) -> bool:
    """A model this service loads: the panel's, and the one the environment names (a folder too, for no internet). Any
    name was fetched and loaded, and written whole to the log: from the model's site, into the models' volume."""
    return name in SPEECH_MODELS or name == CONFIG.whisper_model


@app.post("/load")
def load(body: dict):
    """The model named (the panel's choice), or the environment's, asked for. In use already (a server that started again
    asks for the one it had): its health at once. Otherwise the loader fetches and loads it beside the one in use, which
    goes on hearing, and the answer is 202: the client follows the load in /health. One that cannot be had leaves the one
    in use, and /health says why (`failed`, `error`)."""
    name = str(body.get("model") or "")
    if len(name) > 200 or (name and not _offered(name)):
        log.warning("refused to load a model this service does not offer (%s)", name[:60])
        raise HTTPException(400, "not a speech model this service offers")
    model = name or CONFIG.whisper_model
    with _STATE_LOCK:
        tr = _STATE["tr"]
        inuse = bool(getattr(tr, "available", False))
        wanted, loading = _STATE["wanted"], _STATE["loading"]
        # another model asked for and not in use yet (a failed ask is no longer one): the panel's choice, loading
        other = (loading and loading != model) or (wanted and wanted not in (model, _STATE["failed"])
                                                   and not (inuse and wanted == getattr(tr, "model_name", "")))
        # A client's model back in a service found without one (it started again): never in the place of a model in use
        # or one asked for, whose load the client's own once took over and dropped. The server's start defers the same
        # way to a choice made while it waited for the service, which its saved model took the place of
        if (body.get("restore") and (inuse or loading or (wanted and wanted not in (model, _STATE["failed"])))) \
                or (body.get("defer") and other):
            return {**_status_now(), "asked": model}
        if inuse and getattr(tr, "model_name", "") == model and not loading:
            _STATE["wanted"] = model   # the one in use: nothing to load, and an earlier ask not loaded yet is dropped
            return {**_status_now(), "asked": model}
        _STATE["wanted"] = model
        if _STATE["failed"] == model:   # asked again: tried again
            _STATE["failed"] = _STATE["error"] = ""
        state = {**_status_now(), "asked": model}
    _WAKE.set()
    return JSONResponse(state, status_code=202)


def _loader() -> None:
    """The loads, one at a time, of the model asked for last. One asked for while another loads is loaded after it, and the
    earlier one is dropped unless it is still the one asked for."""
    while True:
        _WAKE.wait()
        _WAKE.clear()
        while _load_wanted():
            pass


def _load_wanted() -> bool:
    """One load of the model asked for, when it is not in use already and has not failed: True when one was tried."""
    with _STATE_LOCK:
        model, tr = _STATE["wanted"], _STATE["tr"]
        if (not model or model == _STATE["failed"]
                or (getattr(tr, "available", False) and getattr(tr, "model_name", "") == model)):
            _STATE["loading"] = ""
            return False
        _STATE["loading"], _STATE["error"], _STATE["failed"] = model, "", ""
    why, new = "", None
    try:
        # strict: why a model did not load is its own error (no internet and not in the volume, no room), where the
        # stand-in said "faster-whisper missing, or speech off" for all of them. `reuse`: what the one in use holds
        # under the same name is shared, not loaded twice
        new = make_transcriber(CONFIG, model, reuse=tr, strict=True)
        if not getattr(new, "available", False):   # SIDENOTE_AUDIO=0 or SIDENOTE_TRANSCRIBER=null in this service's settings
            why = f"{model} did not load: speech is off here (SIDENOTE_AUDIO, SIDENOTE_TRANSCRIBER)"
    except Exception as exc:
        why = str(exc)[:200] or type(exc).__name__
    del tr
    swapped = False
    if why:
        with _STATE_LOCK:
            _STATE["loading"], _STATE["error"], _STATE["failed"] = "", why, model
    else:
        with _DECODE:   # a decode running ends first; then the state, briefly (_STATE_LOCK is taken after _DECODE, never before)
            with _STATE_LOCK:
                _STATE["loading"] = ""
                if _STATE["wanted"] == model:   # still the one asked for: in use from now on
                    _STATE["tr"], swapped = new, True
    new = None
    if why:
        log.error("speech model %s did not load (%s)", model, why)
    elif swapped:
        log.info("speech model ready (%s)", model)
    # the memory of the model replaced (or of the one dropped) given back now, and again in a moment for a decode that
    # still held it
    give_back_memory()
    threading.Thread(target=give_back_memory, args=(5.0,), daemon=True).start()
    return True


threading.Thread(target=_loader, name="speech-loader", daemon=True).start()


@app.post("/segments")
async def segments(request: Request, sr: int = 16000) -> dict:
    pcm = await _pcm(request)
    tr = _loaded()

    def work():
        with _DECODE:
            return tr.speech_segments(pcm, sr)
    return {"spans": [[int(s), int(e)] for s, e in await run_in_threadpool(work)]}


@app.post("/transcribe")
async def transcribe(request: Request, sr: int = 16000, live: int = 0) -> dict:
    pcm = await _pcm(request)
    tr = _loaded()

    def work():
        with _DECODE:
            return tr.transcribe(pcm, sr, live=bool(live))
    text = await run_in_threadpool(work)
    return {"text": text, "last_language": getattr(tr, "last_language", ""), "language": getattr(tr, "language", None)}


@app.put("/language")
def language(body: dict) -> dict:
    tr = _model()
    if getattr(tr, "available", False):
        with _DECODE:
            tr.language = str(body.get("value") or "auto")
    return {"language": getattr(tr, "language", None)}


@app.put("/hints")
def hints(body: dict) -> dict:
    tr = _model()
    if getattr(tr, "available", False):
        extra = body.get("extra")
        with _DECODE:
            tr.set_hints(body.get("hint"), extra if isinstance(extra, list) else ())
    return {"ok": True}
