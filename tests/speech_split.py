"""The speech model as a service of its own (server/speech_service.py) and the server's client for it (RemoteTranscriber in
server/transcriber.py), over real HTTP on this PC with a stand-in model in the service: what the server's speech loop asks
of it, the loads (the same model again, a later choice while one loads, one that cannot be had), a service that started
again with no model, one that is gone, what it refuses, and that nothing heard is written to its log.

    .venv/bin/python tests/speech_split.py
"""
import logging
import os
import socket
import sys
import threading
import time
import types
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_AUDIO="1", SIDENOTE_TRANSCRIBER="auto", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_SEARCH_URL="")
os.environ.pop("SIDENOTE_SPEECH_URL", None)
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

import httpx2   # noqa: E402
import uvicorn  # noqa: E402

from server import speech_service as S    # noqa: E402
from server import transcriber as tr      # noqa: E402

PASS, FAIL = [], []
PCM = b"\0\0" * 16000   # a second of 16 kHz 16-bit sound: what it says is the stand-in's
HEARD = "데이터베이스 이중화는 어떻게 하나요"   # what the stand-in hears: never to be found in the service's log


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:300]}" if detail != "" and not ok else ""), flush=True)


class Stand:
    """The model a load makes in the service: what each decode was given, and what the server set on it."""
    available = True

    def __init__(self, model: str):
        self.model_name = model
        self.live_name = "small"
        self._language = "auto"
        self.last_language = ""
        self.hints = None
        self.decoded = []

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value

    def set_hints(self, hint, extra=()) -> None:
        self.hints = (hint, list(extra))

    def speech_segments(self, pcm: bytes, sr: int):
        return [(0, len(pcm) // 2)]

    def transcribe(self, pcm: bytes, sr: int, live: bool = False) -> str:
        self.decoded.append((len(pcm), sr, live))
        self.last_language = "ko"
        logging.getLogger("sidenote.transcriber").info("decoded %d bytes", len(pcm))   # as the real one logs: sizes only
        return HEARD + (" (live)" if live else "")


MADE = []


def maker(cfg, model=""):
    """make_transcriber in the service: a stand-in, slow for "slow", and none to be had for "broken"."""
    MADE.append(model)
    if model == "broken":
        raise OSError("no such model on the model's site")
    if model == "slow":
        time.sleep(1.0)
    return Stand(model or cfg.whisper_model)


S.make_transcriber = maker


class Logged(logging.Handler):
    """Every line the service's process logs while this runs."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LOGGED = Logged()
logging.getLogger().addHandler(LOGGED)
logging.getLogger().setLevel(logging.DEBUG)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int):
    """The service on this port, in a thread, as uvicorn runs it in its container."""
    server = uvicorn.Server(uvicorn.Config(S.app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until = time.monotonic() + 10
    while not server.started and time.monotonic() < until:
        time.sleep(0.05)
    return server, thread


def main() -> int:
    port = free_port()
    server, thread = serve(port)
    url = f"http://127.0.0.1:{port}"
    print("\n[the server's client against the service]")
    remote = tr.RemoteTranscriber(url, "small")
    check("a client loads its model in the service and says which one runs", remote.model_name == "small"
          and remote.live_name == "small" and MADE == ["small"], (remote.model_name, MADE))
    check("...the speech spans of what it is sent", remote.speech_segments(PCM, 16000) == [(0, 16000)])
    whole, live = remote.transcribe(PCM, 16000), remote.transcribe_live(PCM, 16000)
    model = S._STATE["tr"]
    check("...and its words, a sentence's and the live line's, with the language they were read in",
          whole == HEARD and live == HEARD + " (live)" and remote.last_language == "ko"
          and [d[2] for d in model.decoded] == [False, True] and model.decoded[0][:2] == (len(PCM), 16000), (whole, live, model.decoded))
    remote.language = "en"
    remote.set_hints({"ko": ["갱 스케줄링"]}, ["GTID"])
    check("the language and the terms the server sets reach the model", model.language == "en" and remote.language == "en"
          and model.hints == ({"ko": ["갱 스케줄링"]}, ["GTID"]), (model.language, model.hints))
    again = tr.RemoteTranscriber(url, "small")
    check("the model in use asked for again (a server that started again) is answered at once, with no load",
          MADE == ["small"] and again.model_name == "small", MADE)

    print("\n[loads]")
    said = {}

    def load_slow():
        try:
            tr.RemoteTranscriber(url, "slow")
            said["slow"] = "loaded"
        except RuntimeError as exc:
            said["slow"] = str(exc)
    first = threading.Thread(target=load_slow)
    first.start()
    time.sleep(0.2)                           # the slow one is loading
    later = tr.RemoteTranscriber(url, "medium")
    first.join(10)
    check("a choice made while another loads is the one that stays, and the earlier load is dropped",
          S._STATE["tr"].model_name == "medium" and later.model_name == "medium" and "later" in said.get("slow", ""), said)
    try:
        tr.RemoteTranscriber(url, "broken")
        refused = ""
    except RuntimeError as exc:
        refused = str(exc)
    status = httpx2.get(f"{url}/health", trust_env=False).json()
    check("one that cannot be had says why, and leaves the one in use", "no such model" in refused
          and S._STATE["tr"].model_name == "medium" and "no such model" in status.get("error", ""), (refused, status))
    check("its health says the service, its release and the model in use", status.get("service") == "speech"
          and status.get("model") == "medium" and status.get("available") is True and status.get("version"), status)

    print("\n[a service that started again, and one that is gone]")
    later.language = "ko"
    later.set_hints(None, ["Kafka"])
    S._STATE.update(tr=tr.NullTranscriber(), wanted=None)   # a service started again: no model
    made_before = len(MADE)
    spans = later.speech_segments(PCM, 16000)
    model = S._STATE["tr"]
    check("a service with no model gets the client's again, and answers the call", spans == [(0, 16000)]
          and MADE[made_before:] == ["medium"], (spans, MADE[made_before:]))
    check("...with the language and the terms it had been given", getattr(model, "language", "") == "ko"
          and getattr(model, "hints", None) == (None, ["Kafka"]), (getattr(model, "language", ""), getattr(model, "hints", None)))
    big = httpx2.post(f"{url}/transcribe", params={"sr": 16000}, content=b"\0" * (S.MAX_BODY + 2), trust_env=False)
    check("more than a minute of sound is refused", big.status_code == 413, big.status_code)
    check("nothing heard is written to the log, here or by the model's own lines",
          not any(HEARD in line for line in LOGGED.lines), [line for line in LOGGED.lines if HEARD in line][:2])
    server.should_exit = True
    thread.join(10)
    began = time.monotonic()
    gone = (later.speech_segments(PCM, 16000), later.transcribe(PCM, 16000))
    check("a service that is gone hears nothing for that call, with no error to the speech loop, and at once",
          gone == ([], "") and time.monotonic() - began < 5, gone)
    tr.REACH_WAIT = 1.0
    began = time.monotonic()
    try:
        tr.RemoteTranscriber(url, "small")
        reached = "loaded"
    except RuntimeError as exc:
        reached = str(exc)
    check("a first load waits a little for a service still starting, then says it does not answer",
          "does not answer" in reached and 0.9 < time.monotonic() - began < 8, (reached, round(time.monotonic() - began, 1)))

    print("\n[which model the server makes]")
    cfg = types.SimpleNamespace(audio_enabled=True, transcriber="auto", speech_url=url, whisper_model="small")
    off = types.SimpleNamespace(audio_enabled=False, transcriber="auto", speech_url=url, whisper_model="small")
    check("with a speech service named, speech off on the server asks nothing of it",
          isinstance(tr.make_transcriber(off, "small"), tr.NullTranscriber))
    port2 = free_port()
    server2, thread2 = serve(port2)
    cfg.speech_url = f"http://127.0.0.1:{port2}"
    made = tr.make_transcriber(cfg, "small")
    check("...and on, the model is the service's", isinstance(made, tr.RemoteTranscriber) and made.model_name == "small", type(made))
    server2.should_exit = True
    thread2.join(10)

    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
