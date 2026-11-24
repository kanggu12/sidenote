"""The speech service: the speech model (faster-whisper, with its voice detector) as a program of its own, which the server
asks over HTTP (server/transcriber.py, RemoteTranscriber; SIDENOTE_SPEECH_URL).

Why apart from the server: the decoder runs native threads in the process that holds it, and a fork from that process
while they ran once wedged the server for 95 minutes (server/forksafe.py, which the server then needed around every
decode and every start of an agent's CLI). Its two models take about 1.8 GB, and loading another one (the panel's
Speech model) took the server's CPU while answers were being written. Here it has its own process, its own memory and
CPU limits, and starts again on its own; the server keeps all it does with what was heard (the utterances, the
questions, the answers), and this keeps nothing.

    python -m uvicorn server.speech_service:app --host 0.0.0.0 --port 8779

One client, the server. No sign-in: it answers only on the services' own network (compose's default network, no port
on the host; the chart's NetworkPolicy lets the server alone in), as the local model's server does. Nothing heard is
written to its log: what it hears is the room's speech.

    GET  /health                     the model in use, the one loading, the last failure to load
    POST /load        {"model"}      load that model (fetched the first time) beside the one in use, then use it;
                                     "" for SIDENOTE_WHISPER_MODEL. 409 when a later one was asked for meanwhile
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
from starlette.concurrency import run_in_threadpool

from .config import CONFIG
from .transcriber import NullTranscriber, make_transcriber
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
# One load at a time: a choice made while another loads waits for it, and only the latest asked for is taken
_LOAD = threading.Lock()
_STATE: dict = {"tr": NullTranscriber(), "wanted": None, "loading": "", "error": ""}
MAX_BODY = 16000 * 2 * 60   # a minute of 16 kHz 16-bit sound: the server sends a sentence, or the live line's window


def _model():
    return _STATE["tr"]


def _status() -> dict:
    tr = _model()
    return {"ok": True, "service": "speech", "version": VERSION, "available": bool(getattr(tr, "available", False)),
            "model": getattr(tr, "model_name", ""), "live_model": getattr(tr, "live_name", ""),
            "language": getattr(tr, "language", None), "loading": _STATE["loading"], "error": _STATE["error"]}


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


@app.post("/load")
def load(body: dict) -> dict:
    """The model named (the panel's choice), or the environment's: fetched the first time, loaded beside the one in use,
    which goes on hearing until this one is ready. One that cannot be had leaves the one in use, and says why. The same
    model again (a server that started again asks for the one it had) is answered at once."""
    model = str(body.get("model") or "") or CONFIG.whisper_model
    _STATE["wanted"] = model
    with _LOAD:
        if _STATE["wanted"] != model:   # a later choice came while this one waited its turn: that one settles it
            raise HTTPException(409, "a later model was asked for")
        tr = _model()
        if getattr(tr, "available", False) and getattr(tr, "model_name", "") == model:
            return _status()
        _STATE["loading"], _STATE["error"] = model, ""
        try:
            new = make_transcriber(CONFIG, model)
        except Exception as exc:
            _STATE["loading"], _STATE["error"] = "", str(exc)[:200]
            log.error("speech model %s did not load (%s)", model, exc)
            raise HTTPException(500, _STATE["error"])
        _STATE["loading"] = ""
        if not getattr(new, "available", False):
            _STATE["error"] = f"{model} did not load (faster-whisper missing, or speech off: SIDENOTE_AUDIO, SIDENOTE_TRANSCRIBER)"
            raise HTTPException(500, _STATE["error"])
        if _STATE["wanted"] != model:   # another asked for while it loaded: dropped, the one in use stays
            raise HTTPException(409, "a later model was asked for")
        with _DECODE:
            _STATE["tr"] = new
        log.info("speech model ready (%s)", getattr(new, "model_name", model))
        return _status()


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
