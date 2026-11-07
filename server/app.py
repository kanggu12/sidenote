"""sidenote analysis server (runs in WSL).

Two WebSocket endpoints:
  /ingest  <- capture client pushes {frame|audio} messages
  /panel   -> browser panel receives {analysis_start|delta|analysis_done|...}
              and may send {pause|resume} control messages.

A single background worker consumes the latest screenshot, decides via the change
detector whether it is a new screen, optionally transcribes buffered audio, and
streams an agent answer out to every connected panel. One analysis runs at a time;
if a clearly different screen appears mid-analysis, the in-flight call is cancelled
and restarted on the new screen.

Screenshot decoding, thumbnailing and (when enabled) OCR all run in a thread
executor, so the event loop never blocks on them.

Run: ./sidenote up (the image's entrypoint starts uvicorn server.app:app inside the container).
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import http.client
import io
import ipaddress
import functools
import hmac
import pathlib
import json
import logging
import os
import re
try:
    import resource  # the core-dump limit the CLIs inherit (Linux and macOS; a Windows host has no core dumps to stop)
except ImportError:
    resource = None
import signal
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image

from . import faces, forksafe, history as answers_log, i18n, models, repeats, telemetry, watchdog
from . import agents
from .analyzer import (LOCAL_SEEN, LoadStopped, busy_model, error_hint, error_words, local_models, local_status,
                       main_model, make_engines)
from .codecheck import CHECKED, RUNNER_MARK, args_lines
from .config import CONFIG, agent_label, agent_name
from .detector import make_detector
from .gate import distance, signature
from .heads import head_of
from .i18n import t
from .ocr_gate import make_ocr
from .pipeline import (CONFIRM_TIMEOUT, GpuBusy, Hooks, NoSolver, NotSent, Pipeline, Repeat, answer_code, check_code, shown_box, checkable,
                       followup_engine,
                       followup, retry_request)
from .settings import SETTINGS
from .transcriber import NullTranscriber, UtteranceTracker, make_transcriber
from .updates import RELEASES
from .version import VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("sidenote.app")
# The model download logs every HTTP request at INFO; keep the server log about the server.
for _noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

PANEL_DIR = Path(__file__).resolve().parent.parent / "panel"

# Tasks nobody waits for (a follow-up the panel asked for, a code run). Two reasons for the set:
# asyncio only holds a weak reference to a running task, so an unreferenced one can be collected
# while it waits, and whatever it raises would otherwise be lost (the exception surfaces when the
# task object is collected, which may be never).
BACKGROUND: set = set()


def spawn(coro, name: str = ""):
    task = asyncio.create_task(coro, name=name or getattr(coro, "__name__", "task"))
    BACKGROUND.add(task)
    task.add_done_callback(_background_done)
    return task


def _background_done(task) -> None:
    BACKGROUND.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background task %s failed: %s: %s", task.get_name(), type(exc).__name__, exc,
                  exc_info=exc)

# Who may talk to the server. The panel shows your screen and what was heard, and has no login: any
# web page open in the browser could otherwise open ws://127.0.0.1:8777/panel (browsers allow
# cross-site WebSockets), or reach the server under its own domain pointed at 127.0.0.1 (DNS
# rebinding). So the Host must be this machine, and a browser's WebSocket must come from the panel.
LOCAL_HOSTS = ["127.0.0.1", "localhost"]


def same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True   # not a browser (the capture program, curl): a web page cannot open these
    try:
        u = urlsplit(origin)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and u.netloc.lower() == (ws.headers.get("host") or "").lower()


def route_gateways(route_file: str = "/proc/net/route") -> set[ipaddress.IPv4Address]:
    """The gateway of this container's default route, from its routing table: the bridge Docker's proxy connects
    from when something comes in through the published port (any other route's gateway is not trusted)."""
    try:
        with open(route_file, encoding="ascii") as f:
            rows = [ln.split() for ln in f.readlines()[1:]]
    except OSError:
        return set()
    found = set()
    for row in rows:
        try:
            dest, gw, mask = (ipaddress.IPv4Address(struct.pack("<I", int(row[k], 16))) for k in (1, 2, 7))
        except (IndexError, ValueError, struct.error):
            continue
        if int(gw) and not int(dest) and not int(mask):
            found.add(gw)
    return found


class PeerGuard:
    """Pure ASGI middleware: only the published port and this container itself reach the server. The browser and
    the capture program come in through the published port, so from the gateway of the network the default route
    goes through; any other peer is another container, above all the code runner: the example check runs code a
    model wrote from what is on the screen, and that code could otherwise open /panel or /ingest the way the
    capture program does (no Origin header, any Host it likes) and change settings or answer a confirmation.
    Nothing is looked up by name (a lookup of the runner, the first way, made every request wait out a slow
    resolver and let everything through until it answered). A peer that is not an address (an in-process test
    client) passes."""

    def __init__(self, app, route_file: str = "/proc/net/route", trust_gateway: bool | None = None):
        self.app = app
        self.route_file = route_file
        # SIDENOTE_TRUST_GATEWAY off (the Helm chart): loopback alone, as kubectl port-forward arrives
        self.trust_gateway = CONFIG.trust_gateway if trust_gateway is None else trust_gateway
        self.gateways = route_gateways(route_file) if self.trust_gateway else set()

    def allowed(self, peer) -> bool:
        if peer.version == 6 and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        if peer.is_loopback or peer in self.gateways:
            return True
        if not self.trust_gateway:
            return False
        self.gateways = route_gateways(self.route_file)   # the networks may have changed since
        return peer in self.gateways

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        try:
            peer = ipaddress.ip_address((scope.get("client") or ("",))[0])
        except ValueError:
            return await self.app(scope, receive, send)
        if self.allowed(peer):
            return await self.app(scope, receive, send)
        telemetry.event("refused", path=str(scope.get("path"))[:120], origin=f"peer {peer}")
        if scope["type"] == "websocket":
            await receive()   # the handshake's websocket.connect, then the refusal (an HTTP 403)
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": b"forbidden"})


# Every HTTP answer: scripts, styles, fonts and connections only from this server (the panel's
# libraries are served from vendor/, fetched and checksum-verified when the image is built), no
# framing, no sniffing, no referrer, no camera or microphone. Inline styles stay allowed: KaTeX
# draws formulas with them (answer HTML cannot carry style attributes: DOMPurify drops them).
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), display-capture=(), usb=(), payment=()"),
    (b"cache-control", b"no-cache"),   # after an update the browser asks again instead of mixing old files
]


class SecurityHeaders:
    """Pure ASGI middleware (BaseHTTPMiddleware would buffer and does not see WebSockets anyway)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"] + SECURITY_HEADERS
            await send(message)

        await self.app(scope, receive, send_with_headers)


@dataclass
class Frame:
    model_b64: str          # possibly downscaled PNG, base64 (sent to the model + OCR)
    thumb_url: str          # small JPEG data URL (shown in the panel)
    sig: bytes              # high-pass change-detection signature
    ts: float
    width: int
    height: int
    ocr_text: str = ""      # on-screen text (filled in the executor when OCR is on)
    # Where the text detector found lines on this screen, in screen fractions, filled the first time
    # a crop of this frame needs them (pipeline.text_lines). Kept here so several crops of one screen
    # pay for the detector once.
    ocr_lines: list | None = None
    # Scroll-stitched page (client --stitch): the full unrolled problem, cut into tiles
    # sent to the model after the screen itself; extra_sig fingerprints that content.
    extra_b64: list[str] = field(default_factory=list)
    extra_sig: bytes | None = None
    # The screen as it arrived (up to the capture program's --max-width, the monitor's own size by
    # default): problem crops are cut from this, not from the downscaled model image.
    full_png: bytes = b""
    # Visible top-level windows, front to back, in screen fractions (from the capture program): a
    # crop is clipped to the window holding the problem.
    windows: list | None = None
    # The part of the screen the model image shows (the OCR crop, SIDENOTE_CROP); the whole screen
    # by default. Boxes the model gives are fractions of this.
    model_box: tuple = (0.0, 0.0, 1.0, 1.0)
    # How many faces were painted over on this screen and its pages before anything was made from them (faces.py).
    faces: int = 0


@dataclass
class AppState:
    latest_frame: Frame | None = None
    last_analyze_ts: float = 0.0
    paused: bool = False
    audio_buffer: bytearray = field(default_factory=bytearray)
    audio_sr: int = 16000
    panel_clients: set[WebSocket] = field(default_factory=set)
    analysis_seq: int = 0
    analyses_done: int = 0
    transcript: str = ""          # latest rolling transcript (continuous transcription loop)
    transcript_ts: float = 0.0
    # Total audio bytes ever received. The rolling buffer stops growing once it hits its
    # window, so its length can't tell the transcriber that new audio arrived; this can.
    audio_total: int = 0
    last_audio_ts: float = 0.0
    # Problems spoken aloud: finished utterances {start, end (abs samples), text, ts}, and
    # a flag telling the analysis worker a new one arrived.
    utterances: list = field(default_factory=list)
    voice_pending: bool = False
    voice_waiting: bool = False   # speech without a question word: analyze once the speaker pauses
    # The spoken problem being read right now asked something, and how many analyses it has started.
    # `voice_asked` is set by a question word in an utterance and kept for the rest of that unbroken
    # group, so the sentences that follow it extend the same problem; `voice_runs` bounds how many
    # versions of one group are analysed (CONFIG.speech_group_tries). A pause longer than
    # speech_group_gap starts a new group and clears both.
    voice_asked: bool = False
    voice_runs: int = 0
    force_analyze: bool = False   # panel asked to re-run on the current screen
    # Pause, screen off, sound off: the analysis worker drops the analysis already running when the
    # reason applies to it (screen off: one that carries a screen; sound off: a spoken problem).
    stop_reasons: set = field(default_factory=set)
    cancel_reason: str | None = None   # why the analysis being cancelled right now was cancelled
    screen_epoch: int = 0         # +1 on every screen-off: a screen still being prepared then is dropped
    followups: dict = field(default_factory=dict)   # running follow-up task -> {"image", "reason"}
    runner_ok: bool = False       # the code runner answered its last health check
    runs_active: int = 0          # code runs waiting on the runner right now
    analyses_running: int = 0     # analyses started and not yet ended (activity(): the server is in use)
    # Set (and replaced) when an analysis begins or ends: what reads with this PC's model only between analyses waits on
    # it (between_analyses)
    analysis_turn: asyncio.Event = field(default_factory=asyncio.Event)
    last_followup_ts: float = 0.0 # when the last follow-up (a question, a retry, a continuation) was answered
    # The last real (not TYPE: none) analysis and the follow-ups asked about it, so a
    # user's "why?" is answered against the same problem.
    last_result: dict | None = None
    thread: list = field(default_factory=list)
    supersede_streak: int = 0     # analyses cancelled by screen changes in a row
    gpu_loading: asyncio.Task | None = None   # the panel's Load onto the GPU, while it runs
    repeat_said: int = 0          # the answer the panel was last told is being seen again (said once per answer)
    # Automatic answers that found nothing to solve, in a row. Past CONFIG.quiet_after the watching
    # goes quiet: a small screen change then waits CONFIG.quiet_sec instead of the usual interval.
    # Anything found, a question, Reanalyze or a drawn region puts it back to 0.
    empty_run: int = 0
    # When the frame now on screen first turned up as a new one that could not be started yet,
    # so a screen that never comes to rest is still analyzed after CONFIG.settle_max_sec.
    settle_since: float = 0.0
    # The two engines: the local model (its server answers and has the model; what is on the GPU) and
    # The agent (signed in; a rejected token flips it off). While neither can answer, screen and voice
    # changes don't start analyses (they would only fail); the panel says why, and an explicit
    # re-analyze or question still tries.
    local: dict = field(default_factory=lambda: {"ok": False, "method": "local"})
    agent: dict = field(default_factory=lambda: {"ok": False, "method": ""})
    # What the agent's CLI said it ran on, which is the only way to know when it chooses for itself
    # (SIDENOTE_CLAUDE_MODEL empty). Shown on the panel's agent card.
    agent_model: str = ""
    agent_cli: dict = field(default_factory=dict)   # what the CLI really runs on (agents.probe_cli)
    agent_cli_asked: int = 0                        # which asking that answer belongs to
    account_seen: str | None = None                 # the agent's account the panel was last told of (engine_watch)
    kept_said: int = -1                             # the analysis a screen change was last let pass for (analysis_kept, once each)
    quota: dict | None = None                       # what is left of the agent's plan, last read (agents.read_plan_usage), for the panel only
    quota_at: float = 0.0                           # when it was last asked for
    quota_busy: bool = False                        # one read at a time (refresh_quota)
    quota_task: asyncio.Task | None = None          # the read a panel's opening or the watcher started, held so it is not collected
    quota_gen: int = 0                              # one more at each change of account: a read begun before it is not shown
    confirms: dict = field(default_factory=dict)   # confirm-before-send id -> (Future(bool), the message shown)
    confirm_open: dict = field(default_factory=dict)   # analysis id -> when its confirm began waiting on the panel
    confirm_held: dict = field(default_factory=dict)   # analysis id -> seconds its confirms have waited, all told
    screen_seq: int = 0                             # the screen or spoken analysis running (run_analysis), for its age
    check_task: asyncio.Task | None = None         # the automatic check of the last code answer
    # The verify mode's check of the last local answer by the agent, and what it sends (a screen, speech).
    verify_task: asyncio.Task | None = None
    verify_carries: dict = field(default_factory=dict)
    retry_task: asyncio.Task | None = None         # the one retry after a failed example (a follow-up task)
    # The continuation of the last answer from a problem scrolled together (a follow-up task too). A slot of its own:
    # sharing the retry's, each overwrote the other while it ran, and the one overwritten went on with nothing left to
    # stop it, a newer analysis included. cancel_retry() stops both.
    cont_task: asyncio.Task | None = None
    # The last analysis of a screen that was started (its id), whatever came of it. A problem scrolled together
    # continues the last answer only while that answer is this one: a newer one started means a move on to
    # another screen, even when it was stopped before it answered (app.continuation).
    screen_started: int = 0
    # A spoken problem whose answer a screen change stopped: its words, asked once more after that screen ("" when
    # there is none). `voice_retake_mark` is screen_started at that moment and `voice_retake_at` the time: the retake
    # waits for the next screen analysis to start, since the screen comes first, but not for ever.
    voice_retake: str = ""
    voice_retake_mark: int = 0
    voice_retake_at: float = 0.0
    # Capture clients on /ingest, shown in the panel so a missing one is obvious.
    captures: int = 0
    capture_info: str = ""
    # What the panel switched on/off. Sent to the capture client (it stops grabbing the screen
    # or closes the sound device) and enforced here too: data for a switched-off source is dropped.
    screen_on: bool = True
    audio_on: bool = True
    capture_caps: dict = field(default_factory=dict)   # what the client can do: screen, audio, device
    ingest_ws: set = field(default_factory=set)
    # When the screen last changed (stamp_frame): a frame that moved only what keeps moving beside it (a video call
    # in a corner) does not count, so the settle sees the screen come to rest. `last_seen_ts` is any frame at all.
    last_frame_ts: float = 0.0
    # The change before that one. The gap between the two says whether the screen is being driven or
    # whether this is the first thing to happen on it in a while (CONFIG.busy_gap).
    prev_frame_ts: float = 0.0
    last_seen_ts: float = 0.0     # the last frame the capture program sent, whatever it changed
    last_audio_ts: float = 0.0
    capture_note_ts: float = 0.0  # throttles the capture-status broadcasts
    # Bumped whenever heard speech is thrown away (sound switched off, pause, resume): a speech
    # pass still transcribing in the executor drops what it finds instead of bringing it back.
    speech_epoch: int = 0
    # The running analysis has written its first words: a newer spoken problem then waits for its answer instead of
    # stopping it (analysis_worker). Set by its first delta, cleared when the next one starts.
    analysis_wrote: bool = False
    # Where in the sound the last spoken problem that got an answer ended: the next one reads what came after it
    # (after_the_answer), and does not answer it again. A place, not its words: the same words said again later are asked again.
    voice_answered_to: int = 0
    voice_retake_to: int = 0      # the same for the spoken problem waiting to be asked again (voice_retake)
    # When a spoken problem began waiting behind an analysis (0: none is). Age is counted from here while it waits, so what
    # was said does not age out behind a long answer and leave nothing to ask (recent_group).
    voice_held_at: float = 0.0
    last_closed: str = ""         # the words of the last sentence that ended or was noted (note_the_card)
    # The answers a problem seen again can point back to, by id, without their screens (remember_answer)
    answers: dict = field(default_factory=dict)
    # Failed analyses in a row and when automatic analysis may try again (a usage limit or a
    # broken CLI must not re-run every min_interval, piling error cards over the answers).
    error_streak: int = 0
    retry_after: float = 0.0

    def reset_speech(self) -> None:
        """Forget what was heard: audio, utterances, the live transcript, a voice problem waiting."""
        self.audio_buffer.clear()
        self.utterances.clear()
        self.voice_pending = self.voice_waiting = self.voice_asked = False
        self.voice_runs = 0
        self.voice_retake = ""        # a spoken problem waiting to be asked again is speech heard too
        self.voice_answered_to = 0
        self.voice_held_at = 0.0
        self.last_closed = ""
        self.transcript = ""
        self.speech_epoch += 1

    def push_audio(self, pcm: bytes, sr: int) -> None:
        self.audio_sr = sr
        self.audio_total += len(pcm)
        self.last_audio_ts = time.time()
        self.audio_buffer += pcm
        # Keep enough history to hold a whole spoken problem, not just the live window.
        max_bytes = int(sr * max(CONFIG.audio_history_sec, CONFIG.transcript_window_sec)) * 2  # int16 mono
        overflow = len(self.audio_buffer) - max_bytes
        if overflow > 0:
            del self.audio_buffer[:overflow]

    def window_pcm(self) -> bytes:
        """The live-transcript window: the most recent transcript_window_sec of audio."""
        return bytes(self.audio_buffer[-int(self.audio_sr * CONFIG.transcript_window_sec) * 2:])

    def recent_group(self) -> list:
        """The spoken problem in progress: the latest run of utterances whose pauses are
        shorter than speech_group_gap (one problem read in several sentences), within
        speech_context_sec. A longer pause means a new problem, so earlier ones drop out. While a spoken problem waits for
        its turn the age is counted up to when it began to wait: what is waiting has not been read yet."""
        cutoff = (self.voice_held_at or time.time()) - CONFIG.speech_context_sec
        self.utterances = [u for u in self.utterances if u["ts"] >= cutoff]
        group: list = []
        for u in reversed(self.utterances):
            if group and (group[-1]["start"] - u["end"]) / self.audio_sr > CONFIG.speech_group_gap:
                break
            group.append(u)
        return group[::-1]

    def recent_speech(self) -> str:
        """The words of the spoken problem in progress (recent_group)."""
        return " ".join(u["text"] for u in self.recent_group())


STATE = AppState()
# Analysis ids grow across restarts too (milliseconds at start, then +1): a panel left open while
# the server restarts (./sidenote restart or up) would otherwise get id 1 again and overwrite its oldest entry.
STATE.analysis_seq = int(time.time() * 1000)

# The panel's switches and pause outlive a server restart: a screen switched off for privacy must
# not come back on by itself when the server is restarted. Kept beside the logs.
SWITCHES_FILE = Path(telemetry.LOG_DIR) / ".switches.json" if telemetry.LOG_DIR else None


def load_switches() -> None:
    if not SWITCHES_FILE or not SWITCHES_FILE.is_file():
        return
    try:
        d = json.loads(SWITCHES_FILE.read_text(encoding="utf-8"))
        STATE.screen_on = d.get("screen_on") is not False
        STATE.audio_on = d.get("audio_on") is not False
        STATE.paused = d.get("paused") is True
        log.info("switches restored: screen %s, sound %s, paused %s", STATE.screen_on, STATE.audio_on, STATE.paused)
    except Exception as exc:
        log.warning("switches not restored (%s)", exc)


def save_switches() -> None:
    if not SWITCHES_FILE:
        return
    try:
        tmp = SWITCHES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"screen_on": STATE.screen_on, "audio_on": STATE.audio_on, "paused": STATE.paused}),
                       encoding="utf-8")
        os.replace(tmp, SWITCHES_FILE)
    except OSError as exc:
        log.warning("switches not saved (%s)", exc)


# Problem-region crop tuning: pad the text box by this fraction of the image, and
# only crop when the padded text region is a worthwhile sub-rectangle: smaller
# than CROP_MAX_AREA (otherwise there's nothing to trim) but not below CROP_MIN_AREA
# (a tiny text island on a mostly-graphical screen is left whole, to be safe).
CROP_PAD_FRAC = 0.04
CROP_MAX_AREA = 0.92
CROP_MIN_AREA = 0.40
# Aggressive mode: a text block counts as "the problem" only if it holds at least
# this fraction of all the on-screen text, so a clearly dominant block is isolated
# but two comparable blocks (e.g. problem + an equally large editor) are left alone.
CROP_DOMINANCE = 0.60


def _pad_clamp(x0, y0, x1, y1, w, h):
    x0, y0 = max(0, int(x0 - w * CROP_PAD_FRAC)), max(0, int(y0 - h * CROP_PAD_FRAC))
    x1, y1 = min(w, int(x1 + w * CROP_PAD_FRAC)), min(h, int(y1 + h * CROP_PAD_FRAC))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def crop_region(boxes, w: int, h: int):
    """Union of ALL OCR text boxes, padded and clamped (margin trim). None if not worth it."""
    if not boxes:
        return None
    box = _pad_clamp(min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes), w, h)
    if box is None:
        return None
    frac = ((box[2] - box[0]) * (box[3] - box[1])) / float(w * h)
    if frac >= CROP_MAX_AREA or frac < CROP_MIN_AREA:
        return None
    return box


def _cluster_boxes(boxes, gap_x: float, gap_y: float):
    """Group boxes into spatial blocks: two boxes join when their gap is within
    (gap_x, gap_y). Simple union-find over the (small) box list."""
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def gap(a0, a1, b0, b1):
        if a1 < b0:
            return b0 - a1
        if b1 < a0:
            return a0 - b1
        return 0.0

    for i in range(n):
        for j in range(i + 1, n):
            if (gap(boxes[i][0], boxes[i][2], boxes[j][0], boxes[j][2]) <= gap_x and
                    gap(boxes[i][1], boxes[i][3], boxes[j][1], boxes[j][3]) <= gap_y):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])
    return list(groups.values())


def dominant_region(boxes, w: int, h: int):
    """Isolate the dominant text block: cluster the boxes, and if one block holds the
    bulk of the text (CROP_DOMINANCE) while others are separate, return its padded
    bbox. Returns None when no block clearly dominates (caller falls back to margin trim)."""
    if len(boxes) < 4:
        return None
    heights = sorted(b[3] - b[1] for b in boxes)
    hmed = heights[len(heights) // 2] or 1.0
    clusters = _cluster_boxes(boxes, gap_x=2.5 * hmed, gap_y=1.5 * hmed)
    if len(clusters) < 2:
        return None  # one block -> nothing to exclude; let margin trim handle it

    def text_area(cl):
        return sum((b[2] - b[0]) * (b[3] - b[1]) for b in cl)

    total = sum(text_area(c) for c in clusters)
    dom = max(clusters, key=text_area)
    if total <= 0 or text_area(dom) / total < CROP_DOMINANCE or len(dom) < 3:
        return None
    box = _pad_clamp(min(b[0] for b in dom), min(b[1] for b in dom),
                     max(b[2] for b in dom), max(b[3] for b in dom), w, h)
    if box is None:
        return None
    if ((box[2] - box[0]) * (box[3] - box[1])) / float(w * h) >= CROP_MAX_AREA:
        return None  # already fills the screen -> nothing isolated
    return box


# A stitched page can be many screens tall; a model shrinks any image whose long edge is
# over its limit (1568px on older models, 2576px on current ones), which would blur the
# text. So tall pages go out as tiles under the smaller limit, overlapping a little so a
# line cut at a boundary is whole in one of them.
TILE_H = 1500
TILE_OVERLAP = 40


def tile_image(img: Image.Image, max_w: int) -> list[Image.Image]:
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
    tiles, y = [], 0
    while True:
        tiles.append(img.crop((0, y, img.width, min(img.height, y + TILE_H))))
        if y + TILE_H >= img.height:
            return tiles
        y += TILE_H - TILE_OVERLAP


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def prepare_frame(png_bytes: bytes, max_w: int, ocr, crop_mode: str = "off",
                  extra_pngs: list[bytes] | None = None) -> Frame:
    """Decode, cap width, OCR + (optional) crop, thumbnail, hash. Runs in a thread.

    crop_mode: "off" | "auto" (margin trim) | "aggressive" (isolate the dominant block,
    falling back to margin trim when no block clearly dominates)."""
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    img = img.convert("RGB")
    w, h = img.size
    # Faces are covered first, so the thumbnail, the change signature, the model's image and every crop are made
    # from the covered screen (faces.py: for people's portrait rights). The screen as it arrived is kept for
    # the crops; it is written again, quickly rather than small, only when something was covered on it.
    covered = _cover_faces(img)
    if covered:
        png_bytes = _png_bytes(img)
    fitted = img
    if w > max_w:
        fitted = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    # Change detection sees the WHOLE screen (a crop must not blind it), at the model's width: its
    # thresholds were set on screens of that size.
    sig = signature(fitted)

    model_img = fitted
    model_box = (0.0, 0.0, 1.0, 1.0)

    ocr_text = ""
    if ocr is not None:
        try:
            ocr_text, boxes = ocr.run(model_img)
            if crop_mode != "off":
                box = None
                if crop_mode == "aggressive":
                    box = dominant_region(boxes, model_img.width, model_img.height)
                if box is None:
                    box = crop_region(boxes, model_img.width, model_img.height)
                if box:
                    model_img = model_img.crop(box)
                    model_box = (box[0] / fitted.width, box[1] / fitted.height,
                                 box[2] / fitted.width, box[3] / fitted.height)
        except Exception as exc:  # pragma: no cover
            log.warning("OCR/crop failed: %s", exc)

    buf = io.BytesIO()
    # Compression 1: the same pixels in half the time (75 to 36 ms at 4K), and most frames are never analysed
    model_img.save(buf, format="PNG", compress_level=1)
    model_b64 = base64.b64encode(buf.getvalue()).decode()

    # The thumbnail is the whole screen, so the problem box and a box drawn on it are screen fractions.
    tw = 360
    if fitted.width > tw:
        thumb_img = fitted.resize((tw, int(fitted.height * tw / fitted.width)), Image.LANCZOS)
    else:
        thumb_img = fitted
    tbuf = io.BytesIO()
    thumb_img.save(tbuf, format="JPEG", quality=70)
    thumb_url = "data:image/jpeg;base64," + base64.b64encode(tbuf.getvalue()).decode()

    extra_b64: list[str] = []
    extra_sig = None
    for raw in extra_pngs or ():
        page = Image.open(io.BytesIO(raw))
        page.load()
        page = page.convert("RGB")
        covered += _cover_faces(page)            # a scrolled page of the problem is a screen too
        if extra_sig is None:
            extra_sig = signature(page)
        extra_b64 += [_png_b64(t) for t in tile_image(page, max_w)]

    return Frame(model_b64=model_b64, thumb_url=thumb_url, sig=sig,
                 ts=time.time(), width=w, height=h, ocr_text=ocr_text,
                 extra_b64=extra_b64, extra_sig=extra_sig, full_png=png_bytes, model_box=model_box, faces=covered)


def _cover_faces(img) -> int:
    """Paint over the faces on `img` in place when Cover faces is on; how many there were. A finder that fails leaves
    the screen as it is and says so in the log (faces.py), since a screen not read at all is worse."""
    if not SETTINGS.on("face_mask"):
        return 0
    try:
        found = faces.find(img)
    except Exception as exc:   # pragma: no cover - a broken model file, an onnxruntime that fails at run time
        log.warning("face finder failed on a screen (%s); it goes on uncovered", exc)
        return 0
    if found:
        faces.cover(img, found)
    return len(found)


def _png_bytes(img) -> bytes:
    """`img` as PNG at the fastest compression: it stays in this process for the crops, so its size matters less than
    the 0.1 to 0.3 s a full compression of a 4K screen takes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def window_list(raw) -> list | None:
    """The capture program's window rectangles (fractions, front to back), checked."""
    if not isinstance(raw, list):
        return None
    out = []
    for r in raw[:40]:
        if (isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r)
                and 0 <= r[0] < r[2] <= 1 and 0 <= r[1] < r[3] <= 1):
            out.append(tuple(float(v) for v in r))
    return out


async def broadcast(message: dict) -> None:
    dead = []
    for ws in list(STATE.panel_clients):
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        STATE.panel_clients.discard(ws)


def capture_status() -> dict:
    # `now` is this server's own clock: the panel reads the two stamps below against it instead of
    # against the browser's, which can differ by a minute (the browser is Windows, this is a
    # container) and made "last sound just now" either stick for ever or never appear.
    return {"type": "capture", "clients": STATE.captures, "info": STATE.capture_info, "now": time.time(),
            "last_frame": STATE.last_seen_ts or None, "last_audio": STATE.last_audio_ts or None,
            "screen_on": STATE.screen_on, "audio_on": STATE.audio_on, "caps": STATE.capture_caps,
            # The run of answers that found nothing, and how long a small change waits because of
            # it. The watching slows itself down here, and a tool that quietly stops looking as
            # often without saying so is worse than one that keeps asking: the screen card says it
            # for as long as it holds, the same way the agent card says the spend brake.
            "empty_run": STATE.empty_run,
            "quiet_sec": (CONFIG.quiet_sec if CONFIG.quiet_after > 0 and STATE.empty_run >= CONFIG.quiet_after
                          else 0)}


def control_message() -> str:
    """What the capture program should do: the panel's switches, scroll stitching, the monitor, and the words of Skip
    windows (it reads the windows itself, and their titles never come here)."""
    return json.dumps({"type": "control", "screen": STATE.screen_on, "audio": STATE.audio_on,
                       "stitch": bool(SETTINGS.get("stitch")), "monitor": int(SETTINGS.get("monitor")),
                       "skip_windows": list(SETTINGS.get("skip_windows"))})


async def send_control() -> None:
    for ws in list(STATE.ingest_ws):
        try:
            await ws.send_text(control_message())
        except Exception:
            STATE.ingest_ws.discard(ws)


RUN_LANGS = {"python", "cpp", "c", "javascript", "typescript", "java", "kotlin", "go", "bash"}
RUN_ALIASES = {"py": "python", "python3": "python", "c++": "cpp", "cc": "cpp", "js": "javascript", "node": "javascript",
               "ts": "typescript", "kt": "kotlin", "golang": "go", "sh": "bash", "shell": "bash"}
MAX_RUN_CODE, MAX_RUN_STDIN = 100_000, 20_000
MAX_RUNS = 2    # runs waiting on the runner at once; the runner itself does one at a time
RUN_BUSY = "Another code run is going · run again when it ends"   # through t() where it is said


def run_wait_seconds(runs: int = 1) -> float:
    """How long the server waits for one request: the runner may first finish the run before it (up to 15 s),
    then compile (at most 20 s, whatever the timeout, and twice when a C++ or Go compile is tried again) and run it on
    each input (the timeout each, and up to 3 s to clean up after it), plus a margin."""
    t = max(1.0, min(CONFIG.runner_timeout, 30.0))
    return 15 + 2 * 20 + (t + 3) * runs + 10


class _UnixConnection(http.client.HTTPConnection):
    """HTTP over the runner's Unix socket (its URL `unix:///sock/runner.sock`): the runner has no network."""

    def __init__(self, path: str, timeout: float):
        super().__init__("runner", timeout=timeout)
        self.unix_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_path)


def _runner_call(url: str, path: str, payload: dict | None, timeout: float) -> dict:
    """GET (no payload) or POST JSON to the runner's `path` and return its JSON answer: over its Unix socket, or
    over HTTP for a runner reached by address (`http://host:port/run`). Runs in an executor."""
    u = urlsplit(url)
    conn = (_UnixConnection(u.path, timeout) if u.scheme == "unix"
            else http.client.HTTPConnection(u.hostname or "", u.port or 80, timeout=timeout))
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if CONFIG.runner_token:   # a runner over TCP takes only requests that carry its token
            headers["Authorization"] = f"Bearer {CONFIG.runner_token}"
        conn.request("POST" if payload is not None else "GET", path, body=body, headers=headers)
        r = conn.getresponse()
        text = r.read().decode()
        if r.status != 200:
            raise OSError(f"the code runner answered HTTP {r.status}")
        return json.loads(text)
    finally:
        conn.close()


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    """POST a run to the runner and return its JSON answer. Runs in an executor."""
    return _runner_call(url, "/run" if url.startswith("unix:") else urlsplit(url).path or "/run", payload, timeout)


def _get_ok(url: str) -> bool:
    try:
        return bool(_runner_call(url, "/health", None, 1.5).get("ok"))
    except Exception:
        return False


def run_enabled() -> bool:
    """The panel shows the run button only while the runner is configured, answering and switched on."""
    return bool(CONFIG.runner_url) and STATE.runner_ok and bool(SETTINGS.get("run_button"))


async def check_runner() -> bool:
    """Ask the runner's /health; tell the panels when it went down or came back."""
    ok = False
    if CONFIG.runner_url:
        ok = await asyncio.get_running_loop().run_in_executor(None, _get_ok, CONFIG.runner_url)
    if ok != STATE.runner_ok:
        STATE.runner_ok = ok
        log.info("code runner %s", "answers" if ok else "does not answer")
        telemetry.event("runner", ok=ok)
        await broadcast({"type": "status", "run_enabled": run_enabled()})
    return ok


async def runner_watch() -> None:
    """Check the runner every 3 s until it answers, then every 15 s."""
    if not CONFIG.runner_url:
        return
    while True:
        ok = await check_runner()
        await asyncio.sleep(15 if ok else 3)


async def run_code(seq, lang: str, code: str, stdin: str, reply=None) -> None:
    """Run one solution's code in the isolated runner and send the real output to the panel that
    asked (`reply`), so another open panel never gets it."""
    send = reply or broadcast
    lang = (lang or "").strip().lower()
    lang = RUN_ALIASES.get(lang, lang)

    async def fail(text: str, why: str | None = None) -> None:
        if why:
            telemetry.event("run_error", id=seq, lang=lang or None, reason=why)
        await send({"type": "run_result", "id": seq, "lang": lang, "error": text})

    if not CONFIG.runner_url:
        await fail(t("Code runs are off"))
        return
    if lang not in RUN_LANGS:
        await fail(t("Cannot run this language: {lang} (runs Python, Java, C++, C, JavaScript, TypeScript, Kotlin, "
                     "Go, Bash)", lang=lang or "?"))
        return
    if not code.strip():
        await fail(t("No code to run"))
        return
    if len(code) > MAX_RUN_CODE:
        await fail(t("The code is too long (up to {n} characters)", n=f"{MAX_RUN_CODE:,}"))
        return
    if len(stdin or "") > MAX_RUN_STDIN:
        await fail(t("The input is too long (up to {n} characters)", n=f"{MAX_RUN_STDIN:,}"))
        return
    if STATE.runs_active >= MAX_RUNS:
        await fail(t(RUN_BUSY))
        return
    # A function's runner reads one argument a line, as the examples write them: what was typed is laid out that way
    # (a matrix over several lines, a blank line first, `nums = [2,7], target = 9`), and only for such a runner, since
    # a program that reads the problem's own input takes it as it is
    typed = stdin or ""
    if RUNNER_MARK.search(code) and typed.strip():
        stdin = args_lines(typed)
    STATE.runs_active += 1
    payload = {"lang": lang, "code": code, "stdin": stdin or "", "timeout": CONFIG.runner_timeout}
    loop = asyncio.get_running_loop()
    try:
        await send({"type": "run_started", "id": seq})
        # what went in as well as the code: a run found wrong could not be told from the record
        telemetry.event("run", id=seq, lang=lang, bytes=len(code), stdin_chars=len(stdin or ""),
                        stdin_lines=len((stdin or "").splitlines()), laid_out=(stdin or "") != typed)
        res = await loop.run_in_executor(None, _post_json, CONFIG.runner_url, payload, run_wait_seconds())
        if res.get("busy"):
            await fail(t(RUN_BUSY))
            return
        if res.get("error") and "stage" not in res:   # the runner failed, not the program
            log.warning("runner error: %s", res.get("error"))
            await fail(t("Runner error · run again"), "runner")
            return
        res.update(type="run_result", id=seq, lang=lang)
        await send(res)
        telemetry.event("run_done", id=seq, lang=lang, exit=res.get("exit"),
                        timed_out=res.get("timed_out"), elapsed=res.get("elapsed"))
    except Exception as e:
        why = getattr(e, "reason", e)
        if isinstance(e, TimeoutError) or isinstance(why, TimeoutError):
            await fail(t("No result in time · if it goes on, ./sidenote restart in the server's terminal"), "timeout")
        elif isinstance(e, (urllib.error.URLError, OSError)):
            log.warning("run failed: %s", e)
            await fail(t("Cannot reach the runner · ./sidenote up in the server's terminal"), "unreachable")
            await check_runner()
        else:
            log.warning("run error: %s", e)
            await fail(t("Code run error"), "error")
    finally:
        STATE.runs_active -= 1


async def runner_exec(lang: str, code: str, stdin: str | list) -> dict:
    """Run a program in the runner for the server itself (the automatic check of a code answer):
    the runner's result, or {"error": ...}. Shares the limit on runs waiting at once with the panel. A list of
    inputs is run in one request, compiled once, each run's result under "runs"."""
    if not CONFIG.runner_url or not STATE.runner_ok:
        return {"error": t("The code runner is off")}
    if STATE.runs_active >= MAX_RUNS:
        return {"error": t(RUN_BUSY)}
    STATE.runs_active += 1
    try:
        payload = {"lang": lang, "code": code, "timeout": CONFIG.runner_timeout,
                   **({"stdins": stdin} if isinstance(stdin, list) else {"stdin": stdin or ""})}
        res = await asyncio.get_running_loop().run_in_executor(None, _post_json, CONFIG.runner_url, payload,
                                                                run_wait_seconds(len(stdin) if isinstance(stdin, list) else 1))
        if res.get("busy"):
            return {"error": t(RUN_BUSY)}
        return res
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        STATE.runs_active -= 1


def request_stop(reason: str) -> None:
    """pause / local_off / screen_off / sound_off: ask the analysis worker to drop the analysis already
    running. The worker decides whether the reason applies to that analysis."""
    STATE.stop_reasons.add(reason)


def cancel_followups(reason: str, with_image_only: bool = False) -> None:
    """Stop follow-up answers still running: all of them on pause, the ones sending the old screen
    on screen-off."""
    for task, info in list(STATE.followups.items()):
        if with_image_only and not info.get("image"):
            continue
        info["reason"] = reason
        task.cancel()


def cancel_verify(only: str | None = None) -> None:
    """Stop the verify mode's check: always for a newer analysis or a pause, and on screen-off or
    sound-off only when it sends that (`only`: "image" or "voice")."""
    t = STATE.verify_task
    if t is None or t.done() or (only and not STATE.verify_carries.get(only)):
        return
    STATE.verify_task = None
    t.cancel()


async def set_paused(p: bool) -> None:
    """The panel's pause button. Pause stops the automatic triggers and whatever is answering now (a
    question or Reanalyze asked while paused still runs). Speech heard before or during the pause
    is dropped, never analyzed on resume."""
    STATE.paused = p
    if p:
        request_stop("pause")
        cancel_followups("pause")
        cancel_check()
        cancel_verify()
    STATE.reset_speech()
    await broadcast({"type": "transcript", "text": "", "lang": ""})
    save_switches()
    await broadcast({"type": "status", "paused": STATE.paused})


async def set_capture(screen: bool | None = None, audio: bool | None = None) -> None:
    """Switch screen and/or sound capture on or off (from the panel)."""
    if screen is not None:
        STATE.screen_on = screen
        if not screen:   # a screen grabbed before switching off may not be analyzed afterwards
            STATE.latest_frame = None
            STATE.screen_epoch += 1           # nor one still being prepared at this moment
            request_stop("screen_off")        # an analysis carrying a screen is dropped
            cancel_followups("screen_off", with_image_only=True)   # so is a follow-up sending one
            cancel_check()                    # the code check reads that screen's examples
            cancel_verify("image")            # and the agent's check of an answer, if it sends the screen
            if PIPELINE is not None:          # and the pictures of answered problems (design 88)
                PIPELINE.recent.forget()
            if STATE.last_result:             # and later follow-ups do not send that screen either
                STATE.last_result["frame"] = None
                STATE.last_result.pop("screen", None)         # nor is a later screen of it kept for comparing
                STATE.last_result.pop("problem_text", None)   # nor is what was read off it kept
                STATE.last_result.pop("words", None)          # nor what went to the agent in words
    if audio is not None:
        STATE.audio_on = audio
        if not audio:   # nothing heard before switching off may start an analysis later
            STATE.reset_speech()
            if STATE.last_result:   # nor go out again with a follow-up, when it was a question heard
                STATE.last_result.pop("words", None)
            request_stop("sound_off")         # and a spoken problem being answered is dropped
            cancel_verify("voice")            # as is the agent's check of one
            await broadcast({"type": "transcript", "text": "", "lang": ""})
    save_switches()
    await send_control()
    await note_capture(force=True)


def usage_message() -> dict:
    return {"type": "usage", **telemetry.totals()}


async def note_capture(force: bool = False) -> None:
    """Tell panels about the capture client; on frames/audio at most every 5 s."""
    now = time.time()
    if force or now - STATE.capture_note_ts > 5:
        STATE.capture_note_ts = now
        await broadcast(capture_status())


def usage_fields(result) -> dict:
    u = result.usage or {}
    return {"tokens_in": (u.get("input_tokens") or 0) + (u.get("cache_read") or 0) + (u.get("cache_write") or 0),
            "tokens_out": u.get("output_tokens"), "cost_usd": result.cost_usd, "model": result.model}


ENGINES = None    # analyzer.Engines, set at start
PIPELINE: Pipeline | None = None


def effective_mode() -> str:
    """The the agent mode in effect: off without the agent; `all` when the agent is the only engine left."""
    if ENGINES is None or ENGINES.agent is None or not STATE.agent.get("ok") or SETTINGS.get("agent_mode") == "off":
        return "off"
    if not (ENGINES.local is not None and SETTINGS.on("local_llm") and STATE.local.get("ok")):
        return "all"
    return SETTINGS.get("agent_mode")


def activity() -> dict:
    """Whether the server is being used right now, for a deploy that waits until it is not (./sidenote up): anything
    running (an analysis, a follow-up, a code check, the agent's check, a run of code from the panel) and when the last
    answer came (a real one, or a follow-up). A restart drops what runs and the last answer a follow-up is asked
    about; one restart came while the server was in use, and the same problem was solved
    twice."""
    tasks = [*STATE.followups, STATE.check_task, STATE.verify_task, STATE.retry_task, STATE.cont_task]
    busy = (STATE.analyses_running > 0 or STATE.runs_active > 0
            or any(t is not None and not t.done() for t in tasks))
    last = max((STATE.last_result or {}).get("ts") or 0.0, STATE.last_followup_ts)
    # Someone being listened to: a spoken problem waiting for its speaker to pause, or words heard in the last 15 s.
    # The capture program does not restart into new code then (client/capture.py, server_quiet).
    now = time.time()
    listening = bool(STATE.voice_pending or STATE.voice_waiting
                     or any(now - (u.get("ts") or 0) < 15 for u in STATE.utterances[-3:]))
    return {"busy": busy, "last_answer": last or None, "listening": listening}


def local_busy() -> dict | None:
    """While a busy GPU has the smaller model answering: {"model", "until"} (server/analyzer.py: GpuPace)."""
    local = ENGINES.local if ENGINES is not None else None
    pace = getattr(local, "pace", None)
    if pace is None or not pace.busy():
        return None
    model = local.model
    if model == main_model(CONFIG):
        return None
    return {"model": model, "until": round(pace.busy_until)}


def panel_engines() -> dict:
    """engines_status with who the agent is signed in as: for the panel, and never in /health, /stats or the logs."""
    status = engines_status()
    status["agent"]["account"] = agents.account(CONFIG.agent)
    status["agent"]["quota"] = STATE.quota if CONFIG.agent == "claude-code" else None   # what is left of the plan's limits
    return status


def engines_status() -> dict:
    """What the panel shows about the engines (signals, the connection card, why nothing solves)."""
    return {
        "local": {**STATE.local, "present": ENGINES is not None and ENGINES.local is not None,
                  "on": bool(SETTINGS.get("local_llm")), "busy": local_busy(),
                  "loading": STATE.gpu_loading is not None and not STATE.gpu_loading.done(),
                  # switched off and answering for the agent at its limit: why ("limit", "signin", "brake"), or ""
                  "stand_in": PIPELINE.standing_in() if PIPELINE is not None else "",
                  # whether the card may offer a download of a missing model, and the one under way
                  "pull": pull_allowed(), **({"pulling": dict(PULL)} if PULL else {})},
        "agent": {**STATE.agent, "present": ENGINES is not None and ENGINES.agent is not None,
                  # which agent it is (claude-code, codex, anthropic-api), the name the panel shows for it, and
                  # what to run when it is not signed in
                  "provider": CONFIG.agent, "label": agent_name(),
                  "product": agent_label(CONFIG.agent) if CONFIG.agent not in ("", "off") else "", "login": agents.login_hint(CONFIG),
                  "short": agent_name(),
                  "mode": SETTINGS.get("agent_mode"), "effective": effective_mode(),
                  "payload": SETTINGS.get("agent_payload"),
                  # what it runs on: what the agent said it used, else what it is asked for (the panel's choice,
                  # which the environment starts), and how hard it is told to think, as agents.chosen() asks it
                  "model": STATE.agent_model or STATE.agent_cli.get("model") or agents.chosen(CONFIG)[0],
                  "asked_model": agents.chosen(CONFIG)[0], "effort": agents.chosen(CONFIG)[1] or STATE.agent_cli.get("effort", ""),
                  "effort_own": not agents.chosen(CONFIG)[1] and bool(STATE.agent_cli.get("effort")),   # the CLI's own, as nothing here asks for one
                  "thinking": STATE.agent_cli.get("thinking", ""), "max_tokens": STATE.agent_cli.get("max_tokens"),
                  # The spend brake, as a sentence, while it stops the watching by itself. The card
                  # carries it so the panel can say it for as long as it holds, instead of one
                  # "not sent" card per screen change.
                  "brake": PIPELINE.auto_blocked() if PIPELINE is not None else "",
                  # resting on its plan's limit until then (seconds since the epoch), for the panel's countdown
                  # (a used-up plan only: a two-minute rate limit is not counted down)
                  "limit_until": round(PIPELINE.spend.limit_until)
                  if PIPELINE is not None and PIPELINE.spend.plan_left() else None},
        "search": {"present": bool(CONFIG.search_url) and ENGINES is not None and ENGINES.local is not None,
                   "on": SETTINGS.on("web_search")},
        "ready": PIPELINE.ready() if PIPELINE is not None else False,
    }


async def refresh_quota() -> None:
    """What is left of the agent's plan, read again where Claude Code's /usage reads it (agents.read_plan_usage, in a thread) and sent to the
    panels when it changed. One read at a time; a failed read keeps the last one shown (the panel greys a reading that has grown old, by
    its "at"). A read begun before the account changed is dropped: it would have put the old account's figures under the new name."""
    if CONFIG.agent != "claude-code" or STATE.quota_busy:
        return
    STATE.quota_busy = True
    STATE.quota_at = time.time()
    gen = STATE.quota_gen
    try:
        got = await asyncio.to_thread(agents.read_plan_usage)
    finally:
        STATE.quota_busy = False
    if got is None or gen != STATE.quota_gen:
        return
    changed = {k: v for k, v in got.items() if k != "at"} != {k: v for k, v in (STATE.quota or {}).items() if k != "at"}
    STATE.quota = got
    if changed:
        await broadcast_engines()


def analysis_age(seq: int, since: float) -> float:
    """How long analysis `seq`, begun at `since`, has been at work: its time less what it waited on its confirm. One waiting for
    Send now counts as new: the prompt is the old screen's, and a screen that moved on meanwhile takes over, as before supersede_keep_sec."""
    if seq in STATE.confirm_open:
        return 0.0
    return max(0.0, time.time() - since - STATE.confirm_held.get(seq, 0.0))


def supersede_now(stitched: bool, moved_on: bool, streak: int, age: float) -> bool:
    """Whether a new frame stops the analysis running. The whole of a scrolled problem always does. A screen that has moved on does
    while the running analysis is young (supersede_keep_sec) and the streak of such stops is short (supersede_limit). One that has run
    longer is in its long pass and is let finish, the newest screen looked at once it has."""
    return stitched or (moved_on and streak < CONFIG.supersede_limit and age < CONFIG.supersede_keep_sec)


async def broadcast_engines() -> None:
    await broadcast({"type": "status", "engines": panel_engines()})


async def report_error(seq: int, exc: Exception, kind: str = "analysis", **fields) -> None:
    """An analysis failed: show it on its card with the kind of failure (the panel turns
    'auth' / 'limit' / 'timeout' / 'nosolver' into what to do), mark the agent's sign-in as broken on
    'auth', and hold automatic analysis back for a while (longer on a usage limit, growing with each
    failure)."""
    timed_out = isinstance(exc, (asyncio.TimeoutError, TimeoutError))
    engine = getattr(exc, "engine", None)
    limit = CONFIG.cli_timeout if engine == "agent" else CONFIG.local_timeout
    text = f"{type(exc).__name__}: {str(exc) or ('no answer within %.0f s' % limit if timed_out else '')}"
    hint = "nosolver" if isinstance(exc, NoSolver) else "timeout" if timed_out else error_hint(str(exc))
    telemetry.event(f"{kind}_error", id=seq, hint=hint, engine=engine, error=text[:400], **fields)
    await broadcast({"type": "error", "id": seq, "text": text, "hint": hint})
    # The local model running out of time says the GPU is busy as plainly as a slow answer does, and
    # nothing is measured when a request is given up on: without this the next screen goes to the same
    # model and times out again.
    local = ENGINES.local if ENGINES is not None else None
    if timed_out and engine != "agent" and local is not None and getattr(local, "pace", None) is not None:
        was = local.pace.busy()
        local.pace.timed_out(local.model)
        if not was:
            log.info("local LLM timed out: counting the GPU as busy, %s answers for now",
                     busy_model(CONFIG, main_model(CONFIG)) or "the smaller model")
            await broadcast_engines()
    if hint == "auth" and engine == "agent" and STATE.agent.get("ok"):
        STATE.agent = {**STATE.agent, "ok": False, "rejected": True}
        await broadcast_engines()
    if kind == "analysis":
        STATE.error_streak += 1
        wait = 60.0 if hint == "limit" else min(60.0, 5.0 * 2 ** (STATE.error_streak - 1))
        STATE.retry_after = time.time() + wait
        if wait >= 20:
            await broadcast({"type": "notice", "level": "warn",
                             "text": t("Errors in a row: automatic analysis rests {s} s · Reanalyze solves at once",
                                       s=f"{wait:.0f}")})


async def note_success(engine: str = "", model: str = "") -> None:
    STATE.error_streak, STATE.retry_after = 0, 0.0
    said = False
    if engine == "agent" and not STATE.agent.get("ok"):   # signed in after all (e.g. a transient rejection)
        STATE.agent = {**STATE.agent, "ok": True, "rejected": False}
        said = True
    if engine == "agent" and model and model != STATE.agent_model:
        STATE.agent_model = model
        said = True
    if said:
        await broadcast_engines()


async def agent_failed(exc: Exception) -> None:
    """The agent failed inside an analysis that went on locally: still note a rejected sign-in."""
    telemetry.event("agent_error", hint=error_hint(str(exc)), error=str(exc)[:300])
    if error_hint(str(exc)) == "auth" and STATE.agent.get("ok"):
        STATE.agent = {**STATE.agent, "ok": False, "rejected": True}
        await broadcast_engines()


# What the GPU is doing, for the chart on the panel's local model row: the llm container, which has the GPU, writes one
# line of nvidia-smi every two seconds to a volume this one reads (compose.yaml). With no such file (a host install,
# where nothing writes it) the GPU's own tools are asked (server/hardware.py); with neither, no chart.
GPU_STAT = os.environ.get("SIDENOTE_GPU_STAT", "/gpu/now.csv")


def read_gpu() -> dict | None:
    """{"used", "total" (MiB), "util" (%), "temp" (C), "power" (W)}, or None when there is no fresh reading."""
    try:
        if time.time() - os.path.getmtime(GPU_STAT) > 10:    # the container stopped writing: no old figures shown as now
            return None
        with open(GPU_STAT, encoding="ascii") as f:
            used, total, util, temp, power = [p.strip() for p in f.readline().split(",")][:5]
        if float(total) <= 0:                                # half a line, or a card that reports nothing: no percentage to draw
            return None
        return {"used": int(float(used)), "total": int(float(total)), "util": int(float(util)), "temp": int(float(temp)),
                "power": round(float(power)) if power.replace(".", "").isdigit() else None}
    except FileNotFoundError:
        from . import hardware
        with forksafe.native_work():   # nvidia-smi is a child process: never started while speech is decoded (forksafe.py)
            return hardware.usage()
    except (OSError, ValueError):
        return None


_HOST_GPU: list = []   # this machine's GPU memory as found once (server/hardware.py), for a host install


def gpu_memory_gb() -> float | None:
    """The GPU memory the local model has, in GB: SIDENOTE_LOCAL_VRAM_GB when set, else the llm container's readings,
    else this machine's largest NVIDIA or AMD GPU, or a Mac's Apple silicon (a host install). None when none of them says."""
    if CONFIG.local_vram_gb:
        return CONFIG.local_vram_gb
    reading = read_gpu()
    if reading and reading.get("total"):
        return round(reading["total"] * 1048576 / 1e9, 1)
    if not _HOST_GPU:
        from . import hardware
        with forksafe.native_work():   # its tools are child processes, kept away from a decode as every spawn is
            gpu = hardware.best(hardware.detect())
        _HOST_GPU.append(gpu.memory_gb if gpu else 0.0)   # 0: looked, and there is none the local model can use
    return _HOST_GPU[0]


# What a restart must not lose: the problems answered lately, so one still on the screen is not solved again, and the screen last looked at, so
# an unchanged one does not load the model for nothing (each of six restarts did, 88 s the first time). As fresh as RESTART_KEEP_SEC.
RESTART_KEEP_SEC = 600.0


def keep_for_restart(detector) -> None:
    if not telemetry.LOG_DIR or PIPELINE is None:
        return
    enc = lambda sig: base64.b64encode(sig).decode() if isinstance(sig, (bytes, bytearray)) else None   # noqa: E731
    try:
        PIPELINE.recent.save(pathlib.Path(telemetry.LOG_DIR) / ".restart.npz",
                             {"at": time.time(), "sig": enc(detector.last_sig), "extra_sig": enc(detector.last_extra_sig)})
    except Exception as exc:   # a convenience: closing down goes on
        log.debug("nothing kept for the restart (%s)", exc)


def take_up_after_restart(detector) -> None:
    if not telemetry.LOG_DIR or PIPELINE is None:
        return
    kept = PIPELINE.recent.load(pathlib.Path(telemetry.LOG_DIR) / ".restart.npz")
    if time.time() - float(kept.get("at") or 0) < RESTART_KEEP_SEC:
        try:
            detector.last_sig = base64.b64decode(kept["sig"]) if kept.get("sig") else None
            detector.last_extra_sig = base64.b64decode(kept["extra_sig"]) if kept.get("extra_sig") else None
        except ValueError:     # as if nothing had been kept
            detector.last_sig = detector.last_extra_sig = None
    if kept:
        log.info("after a restart: %d problem(s) remembered, the last screen %s", len(PIPELINE.recent.items), "known" if detector.last_sig else "not known")


async def learn_agent_cli() -> None:
    """Find out what the agent's CLI runs on, for its card: at the start, and when the panel changes its model or effort."""
    if CONFIG.analyzer == "mock":
        return
    STATE.agent_cli_asked += 1
    asked = STATE.agent_cli_asked
    found = await asyncio.to_thread(agents.probe_cli, CONFIG)
    if asked != STATE.agent_cli_asked:   # asked again meanwhile (the panel changed the model again): that answer is the one that counts
        return
    STATE.agent_cli = found
    await broadcast_engines()


async def gpu_watch() -> None:
    """While a panel is open, the GPU's reading every two seconds. Nothing otherwise, except that readings
    stopping is said once, or the panel would go on showing the last figures as if they were now."""
    had = False
    while True:
        await asyncio.sleep(2)
        try:
            if STATE.panel_clients:
                reading = await asyncio.to_thread(read_gpu)
                if reading:
                    await broadcast({"type": "gpu", **reading})
                elif had:
                    await broadcast({"type": "gpu", "none": True})
                had = bool(reading)
        except Exception:                                    # a figure on a panel never ends anything
            log.debug("no GPU reading", exc_info=True)


async def check_agent() -> dict:
    """Whether the cloud agent can answer: its CLI signed in, or its API key set (agents.auth_status)."""
    return await agents.auth_status(CONFIG, ENGINES.agent if ENGINES is not None else None)


async def check_local() -> dict:
    """The local server, its models (the panel's model choices) and what is on the GPU now."""
    if ENGINES is None or ENGINES.local is None:
        return {"ok": False, "method": "local", "off": True}
    if CONFIG.analyzer == "mock":
        return {"ok": True, "method": "local", "model": ENGINES.local.model, "loaded": await ENGINES.local.loaded()}
    ids = await local_models(CONFIG)
    if ids is not None:
        LOCAL_SEEN["pulled"] = ids
    LOCAL_SEEN["vram_gb"] = await asyncio.to_thread(gpu_memory_gb)
    if ids:
        # the labels in English, put in the panel's language whenever they are sent (Settings.options)
        SETTINGS.set_options("local_model", [("auto", "Auto (fits the GPU)")] + [(m, m) for m in ids])
        SETTINGS.set_options("local_busy_model", [("", "Don't switch"), ("auto", "Auto (a smaller model)")] + [(m, m) for m in ids])
    st = await local_status(CONFIG)
    st["loaded"] = await ENGINES.local.loaded() if st.get("ok") else None
    return st


# The model download the panel asks for (the Download key on the local model's card, when the model is missing): the
# local server's own pull, its progress passed on to every panel, then the tuned copy the model's profile names, as
# compose.yaml's llm-pull makes it. Only where SIDENOTE_LOCAL_PULL allows it and the local server is Ollama.
PULL: dict = {}     # the download under way, as the panels are told it: {"model", "status", "completed", "total"}


def pull_allowed() -> bool:
    return (CONFIG.local_pull and ENGINES is not None and ENGINES.local is not None
            and getattr(ENGINES.local, "native", None) is not False)


async def pull_model(name: str) -> None:
    """Download `name` (one of the profiles' names) through the local server, one download at a time."""
    known = {n for p in models.PROFILES for n in (p.name, p.pull) if n}
    if not pull_allowed() or name not in known or PULL:
        return
    import httpx2
    profile = models.profile_for(name)
    root = re.sub(r"/v1/?$", "", CONFIG.local_url.rstrip("/"))
    PULL.update(model=name, status="pulling", completed=0, total=0)
    await broadcast({"type": "llm_pull", **PULL})
    told = time.monotonic()
    try:
        async with httpx2.AsyncClient(timeout=httpx2.Timeout(30.0, read=None)) as client:
            async with client.stream("POST", f"{root}/api/pull", json={"model": profile.pull, "stream": True}) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    step = json.loads(line)
                    if step.get("error"):
                        raise RuntimeError(step["error"])
                    if step.get("total"):
                        PULL.update(completed=step.get("completed") or 0, total=step["total"])
                    if time.monotonic() - told >= 0.5:     # twice a second is enough for a bar
                        told = time.monotonic()
                        await broadcast({"type": "llm_pull", **PULL})
            if profile.tuned and name == profile.tuned:   # the copy with the larger batch (server/models.py)
                PULL.update(status="tuning")
                await broadcast({"type": "llm_pull", **PULL})
                made = await client.post(f"{root}/api/create", timeout=600, json={
                    "model": profile.tuned, "from": profile.pull, "parameters": profile.params, "stream": False})
                made.raise_for_status()
        PULL.update(status="done")
        telemetry.event("llm_pull", model=name, ok=True)
    except Exception as exc:                  # the panel says it failed and why; nothing else depends on it
        PULL.update(status="failed", error=str(exc)[:200])
        telemetry.event("llm_pull", model=name, ok=False, error=str(exc)[:200])
        log.warning("model download %s failed: %s", name, exc)
    finally:
        await broadcast({"type": "llm_pull", **PULL})
        PULL.clear()
        STATE.local = await check_local()
        await broadcast_engines()


# The local server starts beside this one (compose starts them together), and this server's first look at it comes
# before it listens. Looked at again only 20 s later, it read as not responding all that while: in the panel, and in
# the last words of `./sidenote up`, on every start of the stack. So until it first answers it is looked at this often,
# for this many looks: a minute is well over what it takes, and after that it is down, or was never there.
STARTING_EVERY = 2.0
STARTING_LOOKS = 30


async def look_at_local() -> None:
    """The local server's state read again, and the panels told when it has changed."""
    before = (STATE.local.get("ok"), STATE.local.get("missing"), (STATE.local.get("loaded") or {}).get("model"))
    STATE.local = await check_local()
    if before != (STATE.local.get("ok"), STATE.local.get("missing"), (STATE.local.get("loaded") or {}).get("model")):
        log.info("local engine: %s", STATE.local)
        await broadcast_engines()
        await broadcast({"type": "settings", "values": {}, "options": {k: SETTINGS.options(k) for k in ("local_model", "local_busy_model")}})


async def engine_watch() -> None:
    """Every 10 s: release the GPU after the idle time set in the panel; every 20 s: look at the local
    server again (it may still be starting, or a model was pulled), and while the agent's CLI is not
    signed in, look at its login again, so signing in on the PC (./sidenote login, /login in any the agent
    Code session, or codex login) needs no server restart. A login the agent turned down counts again
    only once its login file changes (a new sign-in)."""
    for _ in range(STARTING_LOOKS):
        # "missing" answered (it lists its models), and "off" has no local server to wait for
        if STATE.local.get("ok") or STATE.local.get("missing") or STATE.local.get("off"):
            break
        await asyncio.sleep(STARTING_EVERY)
        await look_at_local()
    cred = agents.login_file(CONFIG.agent)   # ~/.claude/.credentials.json, ~/.codex/auth.json; None for an API key

    def changed_at():
        try:
            return cred.stat().st_mtime if cred is not None else None
        except OSError:
            return None

    seen = changed_at()
    tick = 0
    busy = None
    braked = False      # whether the agent's card is currently saying the spend brake holds
    stood = ""          # why this PC's model, switched off, stands in for the agent ("" for not)
    resting = ""        # until when the agent rests on its plan's limit, as the panel says it ("" for not)
    # The last use of the model (local.last_used) that the idle release below has already answered. One release per
    # stretch of this server leaving the model alone: the runtime is shared (a test server, a benchmark, anything else
    # speaking to the same Ollama), and while another client keeps using the model it stays listed as loaded. The
    # status check then saw it again every 20 s and this released it again, and each release unloaded it from under
    # that client once its request was over, so its next one waited for a reload: in 14 minutes,
    # 40 releases, and 15 loads of the model for 47 requests of a client at another address.
    released = None
    while True:
        await asyncio.sleep(10)
        tick += 1
        local = ENGINES.local if ENGINES is not None else None
        # The smaller model took over, the hold ended, or it was made longer: the panel shows until when, and a hold
        # doubled while it ran was left showing its old end for up to ten minutes
        if local_busy() != busy:
            busy = local_busy()
            await broadcast_engines()
        # What is left of the plan's limits, every minute and a half while a panel is open. Nothing is asked with no
        # panel to show it; a panel that opens asks at once (the panel socket)
        # The read runs as a task of its own: awaited here, a slow address (up to its 8 s timeout) held up everything below for that turn
        if STATE.panel_clients and time.time() - STATE.quota_at >= 90 and not STATE.quota_busy:
            STATE.quota_task = asyncio.create_task(refresh_quota())
        # Signing in as another account on the PC: the card says who, within ten seconds, with no restart
        if STATE.panel_clients:
            who = agents.account(CONFIG.agent).get("email")
            if who != STATE.account_seen:
                if STATE.account_seen is not None:
                    # Another account: the meters were the last one's. They go at once and are read again at the next turn (quota_at 0), and
                    # a read already under way is dropped (quota_gen)
                    STATE.quota, STATE.quota_at, STATE.quota_gen = None, 0.0, STATE.quota_gen + 1
                    await broadcast_engines()
                STATE.account_seen = who
        # The brake comes and goes on a clock of its own, so nothing else would tell the card that
        # it has lifted. Ten seconds late on a five-minute pause is close enough to read as live.
        if PIPELINE is not None and bool(PIPELINE.auto_blocked()) != braked:
            braked = not braked
            await broadcast_engines()
        # This PC's model, switched off, standing in for the agent (Pipeline.standing_in): the panel is told when it
        # starts and when it ends, and at the end the model goes off the GPU again, as it was left (the idle
        # release may be set to never, and a model kept loaded for an agent's week-long limit is not what was chosen)
        # the agent's rest on its limit began or ended: the agent card's countdown comes and goes with it
        rest = PIPELINE.spend.plan_left() if PIPELINE is not None else ""
        if rest != resting:
            resting = rest
            await broadcast_engines()
        why = PIPELINE.standing_in() if PIPELINE is not None else ""
        # The end waits for the work in hand: taking the model off now cut a load or an answer it was giving;
        # the next tick looks again
        if not why and stood and activity()["busy"]:
            why = stood
        if why != stood:
            was, stood = stood, why
            telemetry.event("local_stand_in", reason=why or None, ended=was if not why else None)
            await broadcast_engines()
            if why and not was:
                said = {"limit": "The agent is at its usage limit: until {until}, the local model, switched off, "
                                 "solves instead",
                        "signin": "The agent is signed out: until it signs in again, the local model, switched off, "
                                  "solves instead",
                        "brake": "The agent reached its hourly cost limit: meanwhile the local model, switched off, "
                                 "solves instead"}.get(why, "{why}: the local model, switched off, solves instead")
                await notice(t(said, agent=agent_name(), until=PIPELINE.spend.limit_left(), why=why))
            elif not why and local is not None and not SETTINGS.get("local_llm"):
                if await local.unload():
                    telemetry.event("gpu_release", reason="stand_in_over")
                STATE.local = await check_local()
                await broadcast_engines()
        idle = SETTINGS.get("gpu_idle_min")
        # A model already on the GPU when this server started has no last use here, and the release below never came for it:
        # after a restart it held the GPU memory until the runtime's own 30 minutes. The clock starts now.
        if local is not None and not getattr(local, "last_used", 1) and STATE.local.get("loaded"):
            local.last_used = time.time()
        if (local is not None and idle >= 0 and local.last_used and local.last_used != released
                and STATE.local.get("loaded") and not STATE.local["loaded"].get("unknown")
                and time.time() - local.last_used >= idle * 60):
            if await local.unload():
                released = local.last_used   # done for this idle stretch; the next use of the model starts another
                log.info("local model unloaded after %s min idle", idle)
                telemetry.event("gpu_release", reason="idle", minutes=idle)
                STATE.local = {**STATE.local, "loaded": None}
                await broadcast_engines()
        if tick % 2:
            continue
        await look_at_local()
        now = changed_at()
        if now != seen and PIPELINE is not None:   # a new sign-in, perhaps another plan: it does not go on resting on the old one's limit
            PIPELINE.spend.signed_in()
            # and the warm Claude session started under the old login would go on answering as that account
            if ENGINES is not None and hasattr(ENGINES.agent, "reset_session"):
                ENGINES.agent.reset_session()
        # Signed in and left alone, nothing to ask. A new Codex login is asked about: an API key bills by the turn and a
        # ChatGPT plan does not, which the hourly ceiling goes by.
        if ((STATE.agent.get("ok") and (now == seen or CONFIG.agent != "codex")) or CONFIG.agent not in ("claude-code", "codex")
                or (STATE.agent.get("rejected") and now == seen)):
            seen = now if STATE.agent.get("ok") else seen
            continue
        seen = now
        st = await check_agent()
        if st.get("ok"):
            STATE.agent = st
            log.info("%s sign-in: %s", agent_label(CONFIG.agent), st)
            telemetry.event("auth", ok=True, method=st.get("method"), recheck=True)
            await broadcast_engines()


async def transcribe_current(transcriber, loop) -> str:
    """On-demand transcription of the rolling buffer (used when the continuous loop is off)."""
    if not getattr(transcriber, "available", False) or not STATE.audio_buffer:
        return ""
    try:
        return await loop.run_in_executor(None, transcriber.transcribe, STATE.window_pcm(), STATE.audio_sr)
    except Exception as exc:
        log.warning("transcription failed: %s", exc)
        return ""


VAD_TAIL_SEC = 20  # recent audio the VAD looks at each pass (covers the gap between passes)

# Words that mark speech as a question or a task to solve (ko/en). A problem read aloud
# almost always has one, so it is analyzed the moment the sentence ends; a lecture or chat
# mostly doesn't, so it waits for a pause of speech_group_gap instead of firing an
# analysis on every sentence. The Korean "how many" counted only with a space after it, and asking to be told was
# not a question: "What is the latest Docker Engine version. Tell me down to the patch version." waited out the whole
# gap (7.8 s after the question, in a rehearsal). Telling is asked for, not offered: "I will
# tell you" is still the speaker going on, and so is having written or explained something: a task word counts in the
# form that asks for the task. An English question word or task counts at the start of a clause: in the middle of one
# it is mostly the speaker going on ("that is why", "we had to write", ", which was"). What misses this still goes,
# once the speaker pauses (voice_waiting), so being strict here costs a few seconds and never a question. A sentence too
# short to go at the pause (speech_min_chars) has only this test, so "정답은 뭘까", said with no question mark, is read here.
# What a problem is written with ("값을 구하는 함수") counts unless its sentence ends in the past: that is somebody saying
# what they did ("출력하는 부분을 고쳤습니다"). KO_PAST is that ending, up to the end of the sentence.
KO_PAST = r"[^.!?…]*[았었였했짰갔왔봤됐줬썼쳤렸졌섰났샀](?:습니다|어요|죠|어|다)\s*(?:[.…]|$)"
QUESTION_RE = re.compile(
    r"\?|무엇(?!보다)|어떻게(?!든)|왜(?!냐)|어느(?!\s?(?:날|새|덧|정도))|몇(?!몇)|인가요|일까요|입니까|습니까|나요|(?<!그러니)까요|뭘까|"
    r"맞나(?=\s*(?:[.!…]|$))|"
    rf"하시오|(?<!안녕)(?<!참고)(?<!수고)(?<!고생)(?<!구독)하세요|쓰시오|구하(?:시오|세요|라|는(?!{KO_PAST}))|구해\s?(?:줘|주세요|주시|주실|보세요|봐)|고르(?:시오|세요|라)|"
    r"골라\s?(?:줘|주세요|주시|주실|보세요|봐)|말씀해\s?(?:주세요|주시|주실|보세요|봐)|주시겠|주실래|뭔가요|뭐예요|뭐에요|뭔지|뭐야|뭐지|뭐죠|뭐냐(?!면)|"
    r"알려\s?(?:줘|주세요|주실|줄래|주라)|가르쳐\s?(?:줘|주세요|주실|줄래)|"
    r"(?:설명|작성|구현|계산)해\s?(?:줘|주세요|주시|주실|보세요|봐|라)|"
    rf"(?:반환|출력)하(?:시오|세요|라|는(?!{KO_PAST}))|"
    r"찾(?:으시오|으세요|아\s?(?:줘|주세요|주시|주실|보세요|봐|라))|맞으면|틀리면|옳은|옳지|아닌 것|"
    r"\b(?:true or false|which of (?:the|these|those|following))\b|"
    # the start of a clause, past the words a speaker opens with
    r"(?:^|[.!?;:…]\s+|,\s+)(?:(?:so|and|but|okay|ok|now|then|well|sorry|hey|um|uh|alright|also|next|please)[,\s]+)*(?:"
    # asking, and not "what we did was", "what happened was", "how it works"
    r"(?:what|how|why)(?:'s|\s+(?:is|are|was|were|do|does|did|can|could|would|should|will|many|much|to|about|if))\b|"
    r"what\s+(?!happened|we\b|i\b|they\b|he\b|she\b|it\b|you\b)\w+(?:\s+\w+){0,2}?\s+(?:is|are|does|do|did|can|could|should|would|will|has|have)\b|"
    # asking for a task, and asking politely
    r"(?:explain|describe|write|implement|find|calculate|compute|determine|choose|select|return|compare|define|"
    r"tell me|show me)\b|(?:can|could|would) you\b|"
    # a task whose word also names a thing ("List comprehensions were slow", "Name resolution failed"): with what it asks for
    r"name\s+(?:an?|the|one|two|three|four|five|some|\d+)\b|solve\s+(?:this|the|these|for)\b|give\s+(?:me|an?|one|two|three|some|\d+)\b|"
    r"list\s+(?:the|all|some|every|one|two|three|four|five|\d+)\b|list\s+\w+\s*(?:[.!…]|$))|"
    # after a comma "which" goes on with the sentence, so only at the start of one
    r"(?:^|[.!?;:…]\s+)which\s+\w+", re.I)

# What only sounds like a question, taken out before QUESTION_RE reads what was said. A speaker telling a story asks
# nobody anything with these (question_kind). What a pattern cannot tell, the first pass is told to judge
# (analyzer.SPEECH_RULE). One sentence at a time, its punctuation kept:
SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*")
# A question the speaker reports: "somebody asked, could we ...?", "다들 왜 그러냐고 물어보셨어요". "I'm asking", "I was wondering",
# "if someone asked you", "a frequently asked question" and "물어봐도 될까요" are the speaker's own, and stay.
REPORTED_RE = re.compile(
    r"\b(?:(?<!frequently )(?<!commonly )(?<!often )asked(?!\s+(?:you|question))|kept asking|(?:was|were) asking|would ask|"
    r"(?<!i'm )(?<!am )asking (?:whether|if|why|what|how)|wondered|(?<!i )(?:was|were) wondering)\b|"
    r"\b(?:said|says|saying|goes|went|(?:was|were|is|are|am)\s+like|(?:he|she|they|i)['’](?:s|re|m)\s+like)\s*,?\s*[\"“']?"
    r"(?:what|why|how|is|are|was|were|do|does|did|can|could|should|would)\b|"
    r"냐고(?!\s?묻는다면)|느냐며|냐면서|지\s*(?:계속|자꾸|다들|막)?\s*(?:물어보셨|물어보시길래|물어봤|물어보더|물었|묻더|묻길래)", re.I)
# A stock phrase that is the whole sentence ("guess what?"), and the speaker asking what they did themselves: the
# answer is the next sentence of the story. "So what is the difference?" is neither, and stays.
RHETORICAL_RE = re.compile(
    r"^\W*(?:(?:so|and|but|then|well|okay|ok)[,\s]+)*(?:guess what|you know what|(?:you )?(?:know|see) what i mean|so what|what(?: then)?|"
    r"then what|what happened(?:\s+\w+){0,3}|(?:what|why|how|where|when)\s+did\s+(?:we|i)\b[^.?!…]*|"
    r"sorry|pardon|really|seriously|excuse me|is it|are you sure|you sure)\s*\?\W*$", re.I)
# A tag at the end of a clause, with its question mark, or the whole of a sentence ("Is that right?", "Okay?": a check on the
# room, with nothing in it to answer, and it still goes at the pause). "Is it right to retry?" and "What is correct?" ask with the
# same word, so without a comma before it a tag counts only in a clause that does not open as a question does.
TAG_WORDS = (r"right|you know|okay|ok|yeah|correct|huh|eh|got it|agreed|you see|make sense|makes sense|"
             r"does that make sense|is that right|is that correct|"
             r"(?:is|are|was|were|do|does|did|wo|ca|could|should|would|has|have)n['’]?t\s+(?:it|that|they|we|you|he|she)")
TAG_COMMA_RE = re.compile(rf"(?:^|[,;]\s*)(?:{TAG_WORDS})\s*\?\W*$", re.I)
TAG_BARE_RE = re.compile(rf"\s+(?:{TAG_WORDS})\s*\?\W*$", re.I)
OPENS_ASKING_RE = re.compile(r"^\W*(?:(?:so|and|but|okay|ok|now|then|well)[,\s]+)*(?:is|are|was|were|do|does|did|can|could|"
                             r"should|would|will|has|have|what|how|why|which|who|where|when)\b", re.I)
# Korean asks for agreement in the ending of the verb ("그렇죠?", "맞죠?", "알죠?", "서버가 죽었죠?"), with no question word in the
# sentence: "뭐가 있죠?" does ask. A lecturer's check on the room counts the same.
KO_AGREE_RE = re.compile(r"(?:죠|지요|잖아요|잖아|거든요|지)\s*\?\W*$")
KO_ASKING_RE = re.compile(r"뭐|뭔|뭘|무엇|무슨|어떻게|어떡|어떤|왜|어느|몇|얼마|언제|어디|어딜|누가|누구|누굴")
KO_CHECK_RE = re.compile(r"(?:아시겠|알겠|이해되|이해가 되|이해되셨)\w*\s*\?\W*$")
# "그게 뭐냐면", "왜냐면": the speaker about to say it
KO_ABOUT_TO_RE = re.compile(r"(?:뭐|왜|어떻게|무엇|어디|누가)[^.?!…]{0,20}?냐면")


def asked_part(text: str) -> str:
    """What was said, without what only sounds like a question: reported questions, the speaker's own rhetorical ones,
    and tags at the end of a clause. What is left of a sentence stays."""
    kept = []
    for sentence in SENTENCE_RE.findall(text):
        sentence = sentence.strip()
        if REPORTED_RE.search(sentence) or RHETORICAL_RE.search(sentence):
            continue
        sentence = KO_ABOUT_TO_RE.sub(" ", sentence)
        if TAG_COMMA_RE.search(sentence):
            sentence = TAG_COMMA_RE.sub(".", sentence)
        elif not OPENS_ASKING_RE.search(sentence) and TAG_BARE_RE.search(sentence):
            sentence = TAG_BARE_RE.sub(".", sentence)
        if KO_CHECK_RE.search(sentence) or (KO_AGREE_RE.search(sentence) and not KO_ASKING_RE.search(sentence)):
            sentence = sentence.rstrip(" ?") + "."
        kept.append(sentence)
    return " ".join(kept)


# The first option of a problem read aloud: what follows it belongs with the question read a sentence earlier. Not "보기에는",
# "1.5배", "첫 번째로", "A, which" or "Option one was", which are somebody going on, and "one" and "하나" only with their next.
OPTIONS_RE = re.compile(
    r"^\W*(?:일\s?번|1\s?번|1\s?[.)]\s|첫\s?번째\s?(?:보기|는|,)|첫째\s?(?:보기|,)|보기\s?(?:[,:.]|\d|일|하나)|①|[가ㄱ]\s?[.)]\s|"
    r"a\s?[.,):]\s(?!which\b|that\b)|(?:option|choice|answer)\s*(?:a|1|one)\b(?!\s+(?:was|would|will))|"
    r"one\s?[,.:]\s.*\btwo\b|하나\s?[,.:]\s.*둘)", re.I)


# A question that leans on what came before it: "and when does it fail?", "그건 왜 그래요?"
LEANS_ON_RE = re.compile(r"\b(?:it|its|that|this|those|these|they|them)\b|그것|그건|그게|그걸|이건|이게|이걸|저건", re.I)


def after_the_answer(group: list, answered_to: int) -> str:
    """What the next run reads of this run of speech: what came after the place the last answer reached (answered_to). Given the
    words before it as well, even marked as answered, the model answered them again, 3 stories of 4 (note 106). What means nothing
    alone goes with what it belongs to, as one problem: the options of a quiz, and a question that leans on the one before it. ""
    when nothing came after."""
    after = [u for u in group if u["end"] > answered_to]
    words = " ".join(u["text"] for u in after)
    if len(after) < len(group) and (OPTIONS_RE.match(words) or (LEANS_ON_RE.search(words) and looks_like_question(words))):
        return " ".join(u["text"] for u in group)
    return words


def question_kind(text: str) -> str:
    """"asked": it asks or sets a task. "told": it only sounds as if it does, in what asked_part takes out. "": neither."""
    if not QUESTION_RE.search(text):
        return ""
    return "asked" if QUESTION_RE.search(asked_part(text)) else "told"


def looks_like_question(text: str) -> bool:
    return question_kind(text) == "asked"


async def note_the_card(tracker: UtteranceTracker, lang: str) -> None:
    """A span that ended with no words of its own, too short to write down or written as nothing. The live pass has written
    the same sound all the same (the VAD measures a span anew each pass: a "그렇군요." of 0.87 s alone was cut as shorter than
    utter_min_sec on the way), so it can stand on the card, where it would look heard and ignored.
    The card's last sentence says so, when it is short, nothing is being said after it, and it is not a sentence that ended
    already: a cough after a question leaves the question alone. The two passes write the same sound apart, so the
    comparison allows for a word or two."""
    if not SETTINGS.on("voice_auto") or tracker.start is not None:
        return
    said = SENTENCE_RE.findall(STATE.transcript.strip())
    line = said[-1].strip() if said else ""
    if not line or len(line) >= CONFIG.speech_min_chars:
        return
    # As much of the end of the last sentence as the line is long, and a little: that sentence can be two minutes of speech
    if SequenceMatcher(None, line.lower(), STATE.last_closed.lower()[-len(line) - 4:]).ratio() >= 0.6:
        return
    STATE.last_closed = line   # once: the next cough finds it said
    await broadcast({"type": "utterance", "text": line, "lang": lang, "why": "short"})


async def _voice_pass(transcriber, tracker: UtteranceTracker, loop, fresh: bool) -> None:
    """Find utterance boundaries in the recent audio; when one closes, transcribe the
    whole utterance and, if it is more than a short remark, queue it for analysis."""
    sr = STATE.audio_sr
    epoch = STATE.speech_epoch    # sound off or pause meanwhile: what this pass finds is dropped
    buf = bytes(STATE.audio_buffer)
    total = STATE.audio_total // 2                      # samples received so far
    buf_start = total - len(buf) // 2
    if fresh:
        tail = buf[-int(sr * VAD_TAIL_SEC) * 2:]
        spans = await loop.run_in_executor(None, transcriber.speech_segments, tail, sr)
        if STATE.speech_epoch != epoch:
            return
        off = total - len(tail) // 2
        done = tracker.update([(off + s, off + e) for s, e in spans], total)
    elif time.time() - STATE.last_audio_ts > CONFIG.utter_end_silence + 1.0:
        done = [u for u in [tracker.flush()] if u]      # the audio stopped arriving
    else:
        done = []
    for utt in done:
        s, e = max(utt[0], buf_start), utt[1]
        if e - s < sr // 10:     # already out of the buffer (or a blip): nothing left to transcribe
            continue
        if (e - s) / sr < CONFIG.utter_min_sec:
            # The VAD found a blip, not speech. Whisper does not come back empty-handed from one: it
            # writes a sentence, in English, and a long one at that (CONFIG.utter_min_sec has the
            # numbers). Dropping it here also keeps the transcription off the PC's CPU.
            await note_the_card(tracker, getattr(transcriber, "last_language", ""))
            continue
        pcm = buf[(s - buf_start) * 2:(e - buf_start) * 2]
        text = (await loop.run_in_executor(None, transcriber.transcribe, pcm, sr)).strip()
        if STATE.speech_epoch != epoch:
            return
        # What was said is kept in memory and shown on the panel; the log keeps its shape only.
        # SIDENOTE_LOG_SPEECH=full writes the words too, for working out why one was taken as a
        # problem, and =off writes no line at all.
        if CONFIG.log_speech == "full":
            log.info("utterance %.1fs: %r", (e - s) / sr, text[:80])
        elif CONFIG.log_speech != "off":
            log.info("utterance %.1fs: %d chars (%s)", (e - s) / sr, len(text),
                     getattr(transcriber, "last_language", "") or "?")
        lang = getattr(transcriber, "last_language", "")
        keep_heard(text, (e - s) / sr, lang)   # with the switch on, whatever comes of it below
        if text:
            STATE.last_closed = text
        else:
            await note_the_card(tracker, lang)
        # Listening only to keep what is heard (Keep what is heard on, Solve spoken problems off): nothing is queued
        if not SETTINGS.on("voice_auto"):
            continue
        # A closed sentence that looks like a question is taken from a few characters ("GTID가 뭔가요?"); a remark needs more
        asked = looks_like_question(text)
        need = CONFIG.speech_question_chars if asked else CONFIG.speech_min_chars
        if text and len(text) < need:
            # The panel's live words have shown it: left unsaid, it would look heard and ignored
            await broadcast({"type": "utterance", "text": text, "lang": lang, "why": "short"})
        if len(text) >= need:
            # A pause longer than speech_group_gap ends the spoken problem that was being read, so
            # whether an earlier sentence asked something says nothing about this one.
            if STATE.utterances and (s - STATE.utterances[-1]["end"]) / sr > CONFIG.speech_group_gap:
                STATE.voice_asked, STATE.voice_runs = False, 0
            STATE.utterances.append({"start": s, "end": e, "text": text, "ts": time.time()})
            del STATE.utterances[:-200]   # recent_speech trims by age, but only when something asks it
            # The question word has to be in what was just said, or in an earlier sentence of the
            # same unbroken group. A problem read in several sentences asks once and the sentences
            # after it extend it. It used to be looked for in the whole of recent_speech(), which
            # holds up to speech_context_sec (two minutes) of what was heard, so one "why" in a video's
            # dialogue made every sentence for the next two minutes queue a problem of its own: 43 of
            # them in one hour, against two answers worth reading.
            if asked:
                STATE.voice_asked = True
            # And a group may only start so many analyses. A video's dialogue is one unbroken group
            # that runs for minutes, so the group alone is no bound; a problem read aloud is a few
            # sentences, and whatever is still being read is analysed whole anyway once the speaker
            # stops (voice_waiting, below), so what this cuts is only the versions in between.
            if STATE.voice_asked and STATE.voice_runs < CONFIG.speech_group_tries:
                STATE.voice_runs += 1
                STATE.voice_pending, STATE.voice_waiting = True, False
                log.info("voice problem queued (question words, %d of %d in this one)",
                         STATE.voice_runs, CONFIG.speech_group_tries)
            else:
                STATE.voice_waiting = True
            await broadcast({"type": "utterance", "text": text, "lang": lang})
    # Speech with no question word: analyze it once the speaker has paused long enough to
    # have finished (nothing open, no new utterance for speech_group_gap).
    if (STATE.voice_waiting and tracker.start is None and STATE.utterances
            and time.time() - STATE.utterances[-1]["ts"] >= CONFIG.speech_group_gap):
        STATE.voice_pending, STATE.voice_waiting = True, False
        log.info("voice problem queued (the speaker paused)")


async def transcription_worker(app: FastAPI) -> None:
    """Background speech loop, every transcribe_interval s (skipped while paused):
    - live: transcribe the last transcript_window_sec for the panel bar, so analysis
      never blocks on transcription;
    - voice problems: cut the audio into utterances and queue each finished one for
      analysis, so a problem read aloud is solved even if the screen never changes."""
    if not getattr(app.state.transcriber, "available", False) or CONFIG.transcribe_interval <= 0:
        return
    loop = asyncio.get_running_loop()
    tracker, tracker_epoch = None, STATE.speech_epoch
    last_key = None
    log.info("transcription worker started (every %.1fs, voice problems %s)",
             CONFIG.transcribe_interval, "on" if SETTINGS.on("voice_auto") else "off")
    pass_time = 0.0
    while True:
        # Fixed cadence: a pass that took t seconds shortens the next wait by t.
        await asyncio.sleep(max(0.2, CONFIG.transcribe_interval - pass_time))
        pass_time = 0.0
        if STATE.paused or not STATE.audio_buffer:
            continue
        # Read each pass: a speech model chosen in the panel takes over here, and the utterance being cut goes on
        transcriber = app.state.transcriber
        key = (STATE.audio_total, getattr(transcriber, "language", None))
        fresh = key != last_key                         # new audio or a language switch
        last_key = key
        t0 = time.time()
        # Spoken problems can be switched on and off in the panel: off, no utterances are cut (the live
        # transcript goes on), and switching back on starts from what is heard from then on. Keep what is heard
        # cuts them too, for its own use.
        voice = (SETTINGS.on("voice_auto") or SETTINGS.get("speech_keep")) and hasattr(transcriber, "speech_segments")
        if not voice:
            tracker = None
        try:
            if voice:
                if tracker is None or tracker_epoch != STATE.speech_epoch:   # speech thrown away: start over
                    tracker = UtteranceTracker(STATE.audio_sr, CONFIG.utter_end_silence, CONFIG.utter_max_sec)
                    tracker_epoch = STATE.speech_epoch
                await _voice_pass(transcriber, tracker, loop, fresh)
            if fresh:
                epoch = STATE.speech_epoch
                window = STATE.window_pcm()
                # Writing the live window down is what this loop spends itself on, and on a room
                # where nobody is speaking it spends it for nothing: transcript_window_sec of
                # silence costs 2.30 s of CPU every transcribe_interval and comes back "" (measured
                # with `small`, int8, four threads). The VAD answers "is anyone speaking"
                # over the same audio in 0.016 s, which is 140 times less, so it decides whether
                # there is anything to write down. The server held 1.5 cores for as long as it was
                # left running, on a locked screen, which is also the CPU the capture program was
                # losing its sound to.
                heard = True
                if hasattr(transcriber, "speech_segments"):
                    heard = bool(await loop.run_in_executor(None, transcriber.speech_segments,
                                                            window, STATE.audio_sr))
                # What only shows on the panel may not hold up the utterances beside it in this loop (transcribe_live)
                read = getattr(transcriber, "transcribe_live", transcriber.transcribe)
                text = (await loop.run_in_executor(None, read, window, STATE.audio_sr)) if heard else ""
                # Silence clears it too: a sentence heard minutes ago must not ride along with
                # every later screen analysis as "recent audio".
                if STATE.speech_epoch == epoch and text != STATE.transcript:
                    STATE.transcript = text
                    STATE.transcript_ts = time.time()
                    await broadcast({"type": "transcript", "text": text,
                                     "lang": getattr(transcriber, "last_language", ""),
                                     "waiting": STATE.voice_waiting, "pending": STATE.voice_pending})
        except Exception as exc:
            log.warning("speech pass failed: %s", exc)
        finally:
            pass_time = time.time() - t0


def user_asked() -> None:
    """Something was asked for by hand, so every brake that only holds back the automatic watching
    comes off. There are two of them and they are easy to let drift apart: the agent's row of empty
    turns and its hourly ceiling (server/pipeline.py Spend) and the quiet watching after a run of
    answers that found nothing. Both are about the tool asking by itself; a question, Reanalyze or a
    drawn region is not that."""
    STATE.empty_run = 0        # look properly at the next screen, at the usual interval
    STATE.settle_since = 0.0
    if PIPELINE is not None:
        PIPELINE.spend.asked()


# What the continuation asks the engine that wrote the answer, with the problem scrolled together as its images.
CONTINUE_QUESTION = (
    "[이어 보기] 앞의 풀이는 이 문제가 화면에 보이던 부분만 보고 쓴 것입니다. 지금 이미지는 스크롤해서 이어 붙인 문제 "
    "전체입니다. 앞의 풀이와 견주어 새로 보이는 조건, 제약, 입출력 예, 하위 문제를 찾고, 그것을 반영해 풀이를 보강하세요. "
    "답이 바뀌면 바뀐 답을 먼저 쓰고 무엇 때문에 바뀌었는지 밝히세요. 새로 보이는 것이 답과 풀이를 바꾸지 않으면 "
    "'보강할 것 없음:' 뒤에 이유 한 줄만 쓰세요. 이어 붙인 것이 앞의 문제와 다른 문제면 '다른 문제입니다.' 라고 쓴 뒤 그 "
    "문제를 처음부터 푸세요.")
CONTINUE_LABEL = "Solution filled out from the scrolled problem"   # the panel's words for it, through t()


async def run_followup(app: FastAPI, question: str, retry: dict | None = None, cont: dict | None = None) -> None:
    """Answer a user's follow-up about the last analysis (same screen, its answer and
    earlier follow-ups as context), by the engine that wrote that answer. Runs as its own task: a
    screen change does not cancel a question the user asked.

    `retry`: the automatic retry after a failed example ({"label": what the panel shows as the
    question, "cases": the examples the first check used}); its code is checked again on them. Unlike
    a user's question, a newer analysis stops it (cancel_retry).
    `cont`: the continuation ({"label", "frame": the screen carrying the problem scrolled together}): the answer
    filled out from the whole problem, under the same card. Started by the watching, like the retry: the brake
    holds for it and a newer analysis stops it."""
    last = STATE.last_result
    if not last:
        await broadcast({"type": "notice", "level": "warn", "text": t("No problem analyzed yet to ask about")})
        return
    # Nobody asked for the retry: it is the example check's own, so the agent's brake holds for it, but only when it
    # goes to the agent. One about an answer this PC's model wrote goes to that model and costs the agent nothing; it
    # was skipped all the same, with a notice about the agent.
    agent = PIPELINE._agent() if PIPELINE is not None else None
    if (retry or cont) and agent is not None and followup_engine(PIPELINE, last) is agent:
        why = PIPELINE.spend.blocked()
        if why:
            await PIPELINE.say_brake(why)
            return
    STATE.analysis_seq += 1
    if not retry and not cont:
        user_asked()                # a question comes from a person: no brake, and the rows start over
    seq, frame, start = STATE.analysis_seq, last["frame"], time.time()
    context = last["text"] + "".join(f"\n\n[앞선 추가 질문] {q}\n[답] {a}" for q, a in STATE.thread[-3:])
    task = asyncio.current_task()
    STATE.followups[task] = {"image": frame is not None, "reason": None}
    first: list[float] = []

    async def on_delta(text: str) -> None:
        if not first:
            first.append(time.time())
        await broadcast({"type": "delta", "id": seq, "text": text})

    try:
        # `about`: the analysis this question is answered against, so the panel files it under that
        # entry (not under whatever is newest: an error, or the next problem still streaming).
        await broadcast({"type": "analysis_start", "id": seq, "ts": start, "thumb": None,
                         "transcript": (retry or cont)["label"] if (retry or cont) else question, "pages": 0,
                         "trigger": "retry" if retry else "continue" if cont else "ask", "about": last.get("id")})
        telemetry.event("followup_start", id=seq, question=question[:200], retry=bool(retry) or None)
        result = await followup(PIPELINE, last, question, context, on_delta, seq=seq,
                                pages=cont["frame"] if cont else None)
    except asyncio.CancelledError:   # pause, or the screen it sends was switched off
        reason = (STATE.followups.get(task) or {}).get("reason") or "superseded"
        telemetry.event("followup_cancelled", id=seq, reason=reason, after=round(time.time() - start, 2))
        await broadcast({"type": "analysis_cancelled", "id": seq, "reason": reason})
        raise
    except NotSent:   # confirm before sending, declined
        telemetry.event("followup_not_sent", id=seq)
        await broadcast({"type": "analysis_cancelled", "id": seq, "reason": "not_sent"})
        return
    except Exception as exc:
        log.exception("follow-up #%d failed", seq)
        await report_error(seq, exc, "followup", elapsed=round(time.time() - start, 2))
        return
    finally:
        STATE.followups.pop(task, None)
    note_sent(seq, result.sent)
    telemetry.event("followup_done", id=seq, engine=result.engine, answer=head_of(result.text)[1],
                    elapsed=round(time.time() - start, 2), first_token=round(first[0] - start, 2) if first else None,
                    **usage_fields(result))
    keep_later(last.get("id"), turn={
        "id": seq, "q": (retry or cont)["label"] if (retry or cont) else question, "text": result.text,
        "retry": bool(retry or cont), "kind": "retry" if retry else "continue" if cont else "ask", "model": result.model,
        "engine": result.engine, "sent": result.sent, "usage": result.usage, "cost_usd": result.cost_usd,
        "elapsed": round(time.time() - start, 2)})
    await broadcast(usage_message())
    await note_success(result.engine, result.model)
    STATE.last_followup_ts = time.time()
    if STATE.last_result is last:      # a newer problem started meanwhile: keep its thread clean
        STATE.thread.append((question, result.text))
    STATE.analyses_done += 1
    await broadcast({"type": "analysis_done", "id": seq, "text": result.text, "usage": result.usage,
                     "cost_usd": result.cost_usd, "model": result.model, "engine": result.engine,
                     "sent": result.sent, "elapsed": round(time.time() - start, 2)})
    if retry and STATE.last_result is last and frame is not None:   # the fixed code, on the same examples
        result.crop_box, result.local_view = last.get("crop_box"), last.get("local_view")
        # Back on the list of follow-ups for as long as the code runs, so the pause stops it as it stops the first
        # check; it had left that list with the answer and ran on through a pause.
        STATE.followups[task] = {"image": False, "reason": None}
        await broadcast({"type": "check", "id": seq, "running": True})
        try:
            res = await check_code(PIPELINE, frame, result, runner_exec, cases=retry.get("cases"), any_type=True)
        except asyncio.CancelledError:
            # stopped by a newer analysis or the pause: the card is told, as run_check tells it, or its
            # "running" line stays for good
            await broadcast({"type": "check", "id": seq, "cancelled": True})
            raise
        except Exception as exc:
            log.warning("code check of retry #%d failed: %s", seq, exc)
            res = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        finally:
            STATE.followups.pop(task, None)
        if res is None:   # the examples were there: say why the fixed code was not run on them
            res = {"error": t("The rewritten answer has no code to run ({langs})", langs=CHECKED)
                   if answer_code(result.text) is None
                   else t("Not run: Check the examples or the local model is off")
                   if checkable(PIPELINE, frame, result, any_type=True) is None
                   else t("Not run: these examples do not fit the rewritten code")}
        res = {k: v for k, v in res.items() if k != "cases"}
        telemetry.event("check", id=seq, retry=True, **{k: v for k, v in res.items() if k not in ("fails", "rows")})
        await broadcast({"type": "check", "id": seq, **res})
        keep_later(last.get("id"), turn_check=(seq, res))   # or a reload shows the first check failing and not that the retry passed
    if cont and STATE.last_result is last and frame is not None:
        await check_continuation(app, seq, task, last, cont["frame"], result)


async def check_continuation(app: FastAPI, seq: int, task, last: dict, pages, result) -> None:
    """Run the code a continuation ends with (its own when it wrote one, else the answer's) on the examples of the
    whole problem, `pages` (the screen with the problem scrolled together), and put the result under the
    continuation. The continuation reads examples the first check could not see, and its "the new examples come out
    right" was the model's word: 'String Compression' scrolled to its table of five, and the continuation said the three new
    ones came out right from working them by hand (in a rehearsal). A failure gets the one retry a failed
    first check gets. Nothing is said when there is no code the runner can run: the first check said that already."""
    text = result.text if answer_code(result.text) is not None else last["text"]
    # the whole stitched problem, as the continuation read it, not the first screen's crop
    code = replace(result, text=text, crop_box=None, local_view=None)
    found = checkable(PIPELINE, pages, code, any_type=True)
    if not found or not found[0]:
        return
    # The pause stops it, as it stops the first check, and so does screen-off: it reads that screen's examples, and the
    # first check stops for that (marked as sending no screen, it read on after screen-off)
    STATE.followups[task] = {"image": True, "reason": None}
    await broadcast({"type": "check", "id": seq, "running": True})
    reading: dict = {}   # how its reading went (check_code), for the record
    try:
        res = await check_code(PIPELINE, pages, code, runner_exec, any_type=True, note=reading,
                               gap=lambda read: between_analyses(read, f"code check of continuation #{seq}"))
    except asyncio.CancelledError:   # a newer answer or the pause: the card is told, or "running" stays for good
        await broadcast({"type": "check", "id": seq, "cancelled": True})
        raise
    except Exception as exc:
        log.warning("code check of continuation #%d failed: %s", seq, exc)
        res = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        STATE.followups.pop(task, None)
    res = res or {"none": True}
    cases = res.pop("cases", None)
    telemetry.event("check", id=seq, cont=True, **reading, **{k: v for k, v in res.items() if k not in ("fails", "rows")})
    await broadcast({"type": "check", "id": seq, **res})
    keep_later(last.get("id"), turn_check=(seq, res))
    # (inputs made up for a problem with no examples are no grounds for a retry, as in run_check)
    if (res.get("fails") and not res.get("probe") and not STATE.paused and SETTINGS.on("autocheck")
            and STATE.last_result is last and last.get("frame") is not None):
        question, label = retry_request(res)
        stop_followup(STATE.retry_task)   # an older retry is about fewer examples
        STATE.retry_task = asyncio.create_task(run_followup(app, question, retry={"label": label, "cases": cases}))


def note_sent(seq: int, sent: list) -> None:
    """What left the PC for one answer (search queries, page reads, an agent payload): in events.jsonl
    (the card shows the same list)."""
    for item in sent or ():
        telemetry.event("outbound", id=seq, to=item.get("to"), what=str(item.get("what"))[:200])


async def confirm_send(seq: int, preview: dict) -> bool:
    """"Confirm before sending": show the payload on the panel and wait for Send / Do not send.
    No panel open, or no answer in CONFIRM_TIMEOUT: not sent."""
    if not STATE.panel_clients:
        await broadcast({"type": "notice", "level": "warn",
                         "text": t("Confirm before sending is on and no panel is open: not sent to the agent",
                                   agent=agent_name())})
        return False
    cid = f"c{seq}"
    fut = asyncio.get_running_loop().create_future()
    msg = {"type": "agent_confirm", "id": seq, "cid": cid, **preview, "timeout": CONFIRM_TIMEOUT, "ts": time.time()}
    STATE.confirms[cid] = (fut, msg)
    STATE.confirm_open[seq] = time.time()   # the wait on the panel is no work of the analysis (analysis_age)
    await broadcast(msg)
    try:
        return bool(await asyncio.wait_for(fut, CONFIRM_TIMEOUT))
    except asyncio.TimeoutError:
        return False
    finally:
        STATE.confirms.pop(cid, None)
        began = STATE.confirm_open.pop(seq, None)
        if began is not None:
            STATE.confirm_held[seq] = STATE.confirm_held.get(seq, 0.0) + time.time() - began
        await broadcast({"type": "agent_confirm_done", "id": seq, "cid": cid})


def analysis_turn() -> None:
    """An analysis began or ended: what waits for its turn (between_analyses) looks again."""
    turn, STATE.analysis_turn = STATE.analysis_turn, asyncio.Event()
    turn.set()


async def between_analyses(make, what: str):
    """`make()`, one read with the local model, awaited only while no analysis runs: an analysis that begins stops it
    (its request to the model goes), and it starts over once none runs. The example check of an answer goes on into
    the next analysis, since most find nothing and stopping it there said it was stopped "for the next problem" when
    none came, but it went on as requests of its own to the same model: once it read
    its examples for 84 s on a busy GPU, and the first passes of the next two screens waited behind it, gave up at
    6 s, and were taken up again 15 and 30 s later. Only the model's reads go through this (check_code's `gap`): a
    run on the code runner it cut would go on there all the same, and be sent again. A newer answer still stops the
    check for good (cancel_check). `what` names it in the log."""
    while True:
        while STATE.analyses_running:            # an analysis has the model: wait for it to end
            await STATE.analysis_turn.wait()
        turn = STATE.analysis_turn               # the next analysis to begin sets this one
        work = asyncio.ensure_future(make())
        began = asyncio.ensure_future(turn.wait())
        try:
            await asyncio.wait({work, began}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:           # stopped from outside (a newer answer, the pause): both go
            work.cancel()
            began.cancel()
            raise
        began.cancel()
        if work.done():                          # done first, or at the same moment: its result stands
            return work.result()
        work.cancel()                            # an analysis began: the request goes, and the work waits
        await asyncio.gather(work, return_exceptions=True)
        log.info("%s gave way to an analysis; it goes on when that is done", what)


async def run_check(app: FastAPI, seq: int, frame, outcome) -> None:
    """After a coding answer: run its code on the problem's examples and put the result on the card.
    It reads with the local model only between analyses (between_analyses), and a newer answer cancels
    it. When an example fails, the engine that wrote the answer gets one retry with the failing examples
    (design section 7), as a follow-up under the same card, and its code is checked on the same examples."""
    await broadcast({"type": "check", "id": seq, "running": True})
    # How the reading went (check_code): with "none" alone the record could not tell a screen with no examples from
    # examples read and then left out, and of nine checks in real use six ended with none
    reading: dict = {}
    try:
        res = await check_code(PIPELINE, frame, outcome, runner_exec, note=reading,
                               gap=lambda read: between_analyses(read, f"code check #{seq}"))
    except asyncio.CancelledError:
        await broadcast({"type": "check", "id": seq, "cancelled": True})
        raise
    except Exception as exc:
        log.warning("code check #%d failed: %s", seq, exc)
        res = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    if res is None:
        res = {"none": True}   # no examples to run
    cases = res.pop("cases", None)
    telemetry.event("check", id=seq, **reading, **{k: v for k, v in res.items() if k not in ("fails", "rows")})
    await broadcast({"type": "check", "id": seq, **res})
    keep_later(seq, check=res)
    last = STATE.last_result
    # Not while paused, not with the check switched off since, and not once the screen went off (the
    # retry would carry what was read off it).
    # inputs made up for a problem with no examples (res["probe"]) are no grounds for a retry: the input may be wrong
    if (res.get("fails") and not res.get("probe") and not STATE.paused and SETTINGS.on("autocheck") and last
            and last.get("id") == seq
            and last.get("frame") is not None):
        question, label = retry_request(res)
        stop_followup(STATE.retry_task)   # an older retry still running is about an older answer
        STATE.retry_task = asyncio.create_task(run_followup(app, question, retry={"label": label, "cases": cases}))


async def reply_later(reply, work) -> None:
    """Answer one panel's request when it is done, without holding up that panel's other messages."""
    try:
        await reply(await work)
    except Exception as exc:   # the panel went away meanwhile
        log.warning("panel request failed: %s", exc)


async def problem_text(card_id) -> dict:
    """The panel's Problem text: the last problem written out by the local model, kept so another click does
    not run it again. Only for the last problem, whose screen the server still holds (as for follow-up
    questions); switching the screen off drops both."""
    last = STATE.last_result
    if not last or last.get("id") != card_id or last.get("frame") is None:
        return {"type": "problem_text", "id": card_id, "error": t("Only for the latest problem on the screen")}
    if "problem_text" not in last:
        if PIPELINE is None or PIPELINE._local() is None or not SETTINGS.on("extract"):
            return {"type": "problem_text", "id": card_id,
                    "error": t("The local model or 'Write out the problem text' is off")}
        try:
            text = await PIPELINE.problem_text(last["frame"], last.get("crop_box"), last.get("local_view"))
        except Exception as exc:   # the panel waits on this answer: say what went wrong instead of nothing
            log.warning("problem text #%s failed: %s", card_id, exc)
            return {"type": "problem_text", "id": card_id,
                    "error": t("Writing out failed ({why})", why=error_words(str(exc)))}
        if STATE.last_result is not last or last.get("frame") is None:   # a newer problem, or the screen went off
            return {"type": "problem_text", "id": card_id, "error": t("The screen changed or went off meanwhile")}
        last["problem_text"] = text
        telemetry.event("problem_text", id=card_id, chars=len(text))
    if not last["problem_text"]:
        return {"type": "problem_text", "id": card_id, "error": t("No problem found on the screen")}
    return {"type": "problem_text", "id": card_id, "text": last["problem_text"]}


async def run_verify(seq: int, frame, transcript: str, voice: bool, outcome, by_user: bool = False) -> None:
    """The verify mode: the agent checks a local answer, and the verdict goes on its card (cancel_verify
    says when it stops early)."""
    why = "" if by_user else PIPELINE.spend.blocked()   # the hour's ceiling holds for checks too
    if why:
        await PIPELINE.say_brake(why)
        return
    await broadcast({"type": "verify", "id": seq, "running": True})

    async def on_send(items: list) -> None:   # on record as it leaves: a cancel later does not erase it
        note_sent(seq, items)
        await broadcast({"type": "verify", "id": seq, "running": True, "sent": items})

    try:
        res = await PIPELINE.verify(seq, frame, transcript, voice, outcome, on_send=on_send)
    except asyncio.CancelledError:
        await broadcast({"type": "verify", "id": seq, "cancelled": True})
        raise
    except NotSent as why:
        res = {"not_sent": True, "why": str(why) or None}
    except Exception as exc:
        log.warning("verify #%d failed: %s", seq, exc)
        await agent_failed(exc)
        res = {"error": error_hint(str(exc)) or type(exc).__name__}
    u = res.get("usage") or {}
    telemetry.event("verify_done", id=seq, verdict=res.get("verdict"), error=res.get("error"),
                    not_sent=res.get("not_sent"), model=res.get("model"), cost_usd=res.get("cost_usd"),
                    tokens_in=(u.get("input_tokens") or 0) + (u.get("cache_read") or 0) + (u.get("cache_write") or 0) or None,
                    tokens_out=u.get("output_tokens"))
    await broadcast({"type": "verify", "id": seq, **res})
    keep_later(seq, verify=res)     # the agent's corrected answer is gone after a reload otherwise
    await broadcast(usage_message())


async def load_local(local) -> None:
    """The panel's Load onto the GPU: load the model, then show where it is. Counted as a use, so the idle release does not
    take it straight back off (engine_watch)."""
    t = time.time()
    try:
        await local.load()
        # A load the server refused (out of memory: HTTP 500) is only logged where it runs, so what is on the GPU is what says
        if await local.loaded() is None:
            raise RuntimeError("the model is not on the GPU after the load")
    except LoadStopped:        # stopped on purpose (paused, switched off, given back): no fault of the GPU's to report
        log.info("GPU load from the panel stopped")
        STATE.gpu_loading = None
        await broadcast_engines()
        await broadcast({"type": "notice", "level": "info", "text": i18n.t("Loading onto the GPU stopped")})
        return
    except Exception as exc:   # the load failed: said, not raised
        log.warning("GPU load from the panel failed: %s", exc)
        STATE.gpu_loading = None
        await broadcast_engines()
        await broadcast({"type": "notice", "level": "bad",
                         "text": i18n.t("Loading onto the GPU failed · the GPU is short of memory or another program "
                                        "is using it")})
        return
    if hasattr(local, "last_used"):
        local.last_used = time.time()   # the idle clock starts from now, not from the last answer
    telemetry.event("gpu_load", seconds=round(time.time() - t, 1))
    STATE.gpu_loading = None
    STATE.local = await check_local()
    await broadcast_engines()
    await broadcast({"type": "notice", "level": "done",
                     "text": i18n.t("Loaded onto the GPU ({s} s) · solves at once", s=f"{time.time() - t:.0f}")})


def cancel_check() -> None:
    t, STATE.check_task = STATE.check_task, None
    if t is not None and not t.done():
        t.cancel()


# The answers kept for looking back (server/history.py)
HISTORY = answers_log.History(pathlib.Path(telemetry.LOG_DIR) / "history.sqlite" if telemetry.LOG_DIR else None,
                              CONFIG.history_days, CONFIG.history_mb, CONFIG.heard_mb)


# One thread takes the writes, in order, and nobody waits on them. Awaited, each was a place a cancel could land: a
# follow-up cancelled inside its write never said it finished and stayed "analyzing", and an answer cancelled inside
# its write lost its code check and its review. One thread also keeps a row's add before its updates.
HISTORY_WRITES = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="history")


def _history_write(what: str, seq, call, *args, **kwargs) -> None:
    """Run one history write on its thread. Never what stops an answer."""
    def work() -> None:
        try:
            call(*args, **kwargs)
        except Exception as exc:
            log.warning("analysis #%s: %s (%s)", seq, what, exc)
    HISTORY_WRITES.submit(work)


def keep_answer(seq: int, kind: str, data: dict) -> None:
    """One answer into the history, when the history is kept."""
    if SETTINGS.get("history_keep"):
        _history_write("not kept in the history", seq, HISTORY.add, seq, data.pop("ts"), kind, data)


def keep_heard(text: str, secs: float, lang: str) -> None:
    """One closed sentence into the history, when what is heard is kept (Keep what is heard). Nothing else stops for it."""
    if not text or not SETTINGS.get("speech_keep"):
        return

    def work() -> None:
        try:
            HISTORY.add_heard(time.time(), secs, lang, text)
        except Exception as exc:
            log.warning("what was heard not kept (%s)", exc)
    HISTORY_WRITES.submit(work)


def keep_later(seq, **fields) -> None:
    """What came after an answer, on its row: its code check, a follow-up, its review."""
    if seq is not None and SETTINGS.get("history_keep"):
        _history_write("history not updated", seq, HISTORY.update, seq, **fields)


def clear_history() -> bool:
    """Clear the kept answers; whether it worked, for the panel to say."""
    try:
        HISTORY.clear()
        return True
    except Exception as exc:
        log.warning("history not cleared (%s)", exc)
        return False


def star_answer(seq: int, on: bool) -> tuple[bool, int]:
    """Star or unstar a kept answer: whether the history holds it, and how many are starred now."""
    try:
        return HISTORY.star(seq, on), HISTORY.starred_count()
    except Exception as exc:   # a file that cannot be written is said to the panel as an answer it does not hold
        log.warning("analysis #%s: the star was not kept (%s)", seq, exc)
        return False, 0


PICTURES: set = set()   # the tasks keeping answers' pictures, held so that none is collected while it runs


def keep_picture(seq: int, frame, box, kind: str, epoch: int) -> None:
    """Keep an answer's picture, to know its problem when it is seen again (design 88). A convenience: failing costs
    no answer, and a screen switched off meanwhile takes the pictures with it."""
    async def work() -> None:
        try:
            await asyncio.to_thread(PIPELINE.recent.add, seq, frame.model_b64,
                                    getattr(frame, "model_box", (0.0, 0.0, 1.0, 1.0)), box, kind)
        except Exception as exc:
            log.warning("analysis #%d: its picture was not kept (%s)", seq, exc)
        if STATE.screen_epoch != epoch:
            PIPELINE.recent.forget()
    task = asyncio.create_task(work())
    PICTURES.add(task)
    task.add_done_callback(PICTURES.discard)


def remember_answer(last: dict) -> None:
    """The answers a problem seen again can point back to (repeats.KEEP of them), without their screens: the panel
    says "already solved" about that answer, so a question after it is about that answer, not the newest."""
    STATE.answers[last["id"]] = {**last, "frame": None}
    while len(STATE.answers) > repeats.KEEP:
        STATE.answers.pop(next(iter(STATE.answers)))


def remembered(result, frame, seq: int, voice: bool = False) -> dict:
    """What is kept of the last answer for follow-ups, the code check and Problem text: its text, the screen it came
    from (None once that screen is off), its engine and box. `words` is the problem as it went to the agent in
    words, which a follow-up that sends no image carries again (pipeline.followup); read off a screen that is
    gone it is not kept, as nothing else read off that screen is. `voice`: the answer was to a problem heard, which
    a problem scrolled together never continues (the screen beside it was only context)."""
    return {"text": result.text, "frame": frame, "id": seq, "engine": result.engine, "crop_box": result.crop_box,
            "local_view": result.local_view, "ts": time.time(), "voice": bool(voice),
            "words": getattr(result, "words", "") if frame is not None or voice else ""}


def stop_followup(t) -> None:
    """Stop one follow-up task the watching started (a retry, a continuation) if it still runs, as superseded."""
    if t is not None and not t.done():
        if t in STATE.followups:          # what its card is told when it stops
            STATE.followups[t]["reason"] = "superseded"
        t.cancel()


def cancel_retry() -> None:
    """Stop the automatic retry after a failed example and the continuation from a problem scrolled together: a
    newer answer replaced their problem (pause and screen-off stop them as the follow-ups they are)."""
    t, u = STATE.retry_task, STATE.cont_task
    STATE.retry_task = STATE.cont_task = None
    stop_followup(t)
    stop_followup(u)


def stamp_frame(changed: bool, now: float | None = None) -> None:
    """A frame came. Any frame is the screen card's "last screen"; only one that changed the screen anywhere but where
    something keeps moving (ChangeDetector.observe) restarts the settle's wait for the screen to rest. A video call
    beside a still problem sent a frame each second, so the screen never rested and every analysis waited
    settle_max_sec (8 s) before it started, on a rehearsed call."""
    now = time.time() if now is None else now
    STATE.last_seen_ts = now
    if changed:
        STATE.prev_frame_ts = STATE.last_frame_ts   # how long the screen was calm before this change
        STATE.last_frame_ts = now


def note_left(detector, frame) -> None:
    """Mark the last answer as left behind when `frame`, a single screen, has moved on from that answer's screen.

    The capture program joins a scrolled problem from the screen it had just before the scroll, and sends no single
    screen while it joins one (client/capture.py, screen_loop), so a problem scrolled together after such a frame is
    a scroll of whatever came next, not of the answered problem. The answer's screen is the one it was
    written from, or the last one a continuation of it was filled out from (`screen`): when a join ends the capture
    program sends the screen it ended on once more, which is that one. Checked as frames come (the ingest path) and
    once more when an answer is remembered, for a screen that moved on while it was being written."""
    last = STATE.last_result
    if frame is None or not last or last.get("left") or last.get("frame") is None or frame.extra_b64:
        return
    ref = last.get("screen") or last["frame"]
    if frame is not ref and detector.moved_on(ref, frame):   # inside the answered problem's box when one is watched
        last["left"] = True


def continuation(frame) -> str:
    """What a problem the capture program scrolled together (`frame`) is to the last answer: "continue" (fill that
    answer out from it, under its card), "same" (these pages were continued from already: nothing new) or "" (solve
    it as a problem of its own)."""
    last = STATE.last_result
    if not (CONFIG.continue_window_sec > 0 and frame.extra_b64 and last and last.get("frame") is not None
            and time.time() - last.get("ts", 0.0) <= CONFIG.continue_window_sec):
        return ""
    # The answer has to be about this screen, and the pages have to be its own. It went by the clock alone, so a
    # new problem whose first analysis the scroll stopped went in as the last answer's continuation, under that
    # answer's card, and so did one scrolled after a question heard. So: an answer to a screen
    # (not to a problem heard), the last screen analysis started (none newer was started on another screen), and no
    # screen since it that moved on from it (note_left).
    if last.get("voice") or last.get("id") != STATE.screen_started or last.get("left"):
        return ""
    # A drawn region keeps everything outside it on this PC: the analysis then reads the region and leaves stitched
    # pages out (Pipeline._look), and the continuation sent the whole stitched pane.
    if SETTINGS.get("roi_box"):
        return ""
    # The capture program sends its joined page again with every screen it settles on while the join lasts, so
    # scrolling back up brought the same pages and a second continuation with them. Compared
    # the way the change detector compares stitched pages.
    seen = last.get("cont_sig")
    if seen is not None and frame.extra_sig is not None and distance(frame.extra_sig, seen) < CONFIG.change_threshold:
        return "same"
    # Nobody asked for it, so the agent's spend brake holds for it, and run_followup would stop there with the frame
    # already marked as handled: the scrolled problem was dropped, where an analysis under the brake is answered by
    # this PC's model. Asked here, before anything is marked, it is solved as usual instead.
    agent = PIPELINE._agent() if PIPELINE is not None else None
    if agent is not None and followup_engine(PIPELINE, last) is agent and PIPELINE.spend.blocked():
        return ""
    return "continue"


def watch_region(detector, answer_region) -> None:
    """What the duplicate check watches: the answered problem (when on), else the box the user drew,
    else the whole screen."""
    manual = SETTINGS.get("roi_box")
    if SETTINGS.get("dedupe") and answer_region is not None:
        detector.set_region(answer_region)
    else:
        detector.set_region(tuple(manual) if manual else None)


async def notice(text: str, level: str = "info") -> None:
    """A short note on the panel, drawn as a band is. `level`: "done" when what was asked for went through, "warn" when
    it was not done (refused, held back, not sent), "bad" when something broke (failed), "info" for the rest."""
    await broadcast({"type": "notice", "level": level, "text": text})


async def stage(seq: int, name: str, detail: str, restart: bool = False, thought: str = "") -> None:
    """Which stage an analysis is in (the card's status line: thinking, the agent, writing out, confirm).

    `restart` says the answer is being started over by another engine, so whatever has been written
    into the card goes: without it the local model's answer appears under the refusal the agent just
    streamed, until the finished answer replaces the lot."""
    await broadcast({"type": "stage", "id": seq, "stage": name, "detail": detail,
                     **({"restart": True} if restart else {}),
                     # the thinking pass's last line (pipeline.thought_line), shown under the status while it thinks
                     **({"thought": thought} if thought else {})})


def update_status() -> dict | None:
    """The newer release the panels are told of (server/updates.py): none while this server may not ask, or while the
    panel's "Check for new versions" is off, whatever an earlier check found."""
    return RELEASES.found if RELEASES.allowed() and SETTINGS.get("update_check") else None


async def publish_update() -> None:
    """Every panel told what is known of a newer release now; a panel that connects later gets it with its status."""
    await broadcast({"type": "status", "update": update_status()})


@functools.lru_cache(maxsize=1)
def panel_build() -> str:
    """What the panel's own files add up to. A panel that reconnects to a server built from other
    files has an older page in front of it, and nothing said so: the answers already on it are kept
    in the page, so it asks to be reloaded rather than reloading itself."""
    import hashlib
    here = pathlib.Path(__file__).resolve().parent.parent / "panel"
    h = hashlib.sha256()
    # the translation tables in panel/i18n/ too: a change to one alone is a new panel as well
    files = [p for p in here.glob("*") if p.is_file()] + list((here / "i18n").glob("*.js"))
    for path in sorted(files, key=lambda p: p.relative_to(here).as_posix()):
        h.update(path.relative_to(here).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


async def apply_setting(app: FastAPI, key: str, value) -> tuple[bool, str]:
    """A setting changed in the panel: store it, then do what it needs now."""
    # An unknown key (a panel newer or older than this server) is refused by SETTINGS.set below; reading its old value
    # first raised KeyError, which ended that panel's socket.
    old = SETTINGS.get(key) if key in SETTINGS.defs else None
    ok, err = SETTINGS.set(key, value)
    if not ok:
        # The panel shows a change before the server has it, so a refused one stayed on its control while the
        # old value held: the stored value goes back to every panel.
        if key in SETTINGS.defs:
            await broadcast({"type": "settings", "values": {key: SETTINGS.get(key)}})
        return False, err
    if key in ("stitch", "monitor", "skip_windows"):   # what the capture program does itself: it is told at once
        # A drawn region is a fraction of one screen: on another monitor, or on a screen stitched out of
        # all of them, it points somewhere else entirely. So it goes when the screen it was drawn on does.
        if key == "monitor" and old != value and SETTINGS.get("roi_box"):
            SETTINGS.set("roi_box", None)
            watch_region(app.state.detector, None)
            await broadcast({"type": "settings", "values": {"roi_box": None}})
            await broadcast({"type": "notice", "level": "info",
                             "text": t("The monitor changed: region cleared · sees the whole screen")})
        await send_control()
    elif key == "run_button":
        await broadcast({"type": "status", "run_enabled": run_enabled()})
    elif key in ("whisper_hint", "speech_terms"):
        speech_hints(app.state.transcriber)
    elif key == "whisper_model" and old != value:
        app.state.speech_model_task = asyncio.create_task(change_speech_model(app, old, value))
    elif key in ("agent_model_name", "agent_effort") and ENGINES is not None and ENGINES.agent is not None:
        reset = getattr(ENGINES.agent, "reset_session", None)
        if reset:
            reset()      # the warm process holds the old model: the next problem starts a new one
        STATE.agent_model = ""   # the card shows the new choice until an answer says which model it ran on
        app.state.cli_task.cancel()   # what it found out is about the old choice
        app.state.cli_task = asyncio.create_task(learn_agent_cli())
    elif key == "update_check":
        RELEASES.poke()           # on: the check asks now unless it asked within the day; off: no request from here on
        await publish_update()    # off hides a release already found, and on shows it again
    elif key == "speech_lang":
        tr = app.state.transcriber
        if hasattr(tr, "language"):
            tr.language = value      # the worker re-transcribes the buffer in it
            await broadcast({"type": "status", "lang": value})
    elif key == "voice_auto":
        if not value:
            # A spoken problem queued before the switch was answered after it, and in the hard mode could go to
            # the agent: what was heard and not yet asked is dropped with the switch.
            STATE.voice_pending = STATE.voice_waiting = STATE.voice_asked = False
            STATE.voice_retake = ""   # and so is a spoken problem waiting to be asked again
        await broadcast({"type": "status", "voice": bool(value) and getattr(app.state.transcriber, "available", False)})
    elif key in ("dedupe", "roi_box"):
        watch_region(app.state.detector, None)
        if key == "roi_box" and value:   # a box was drawn: solve what is in it now
            STATE.force_analyze = True
            user_asked()
    elif key == "local_model" and ENGINES is not None and ENGINES.local is not None and old != value:
        await ENGINES.local.unload(None if old in ("", "auto") else old)   # the next problem loads the new one; two at once would not fit
        STATE.local = await check_local()
    elif key == "local_llm" and not value and ENGINES is not None and ENGINES.local is not None:
        cancel_check()                 # it would load the model again, and so would these
        cancel_verify()
        request_stop("local_off")
        cancel_followups("local_off")
        if await ENGINES.local.unload():   # switched off: give the GPU back now
            telemetry.event("gpu_release", reason="switched_off")
        STATE.local = await check_local()
    await broadcast({"type": "settings", "values": {key: SETTINGS.get(key)}})
    await broadcast_engines()
    return True, ""


def speech_hints(tr) -> None:
    """What the speech model is given before the audio, as the settings say: the built-in lists unless Technical term
    hints is off, with the person's Extra terms in front of them. Also when it is off: those words were typed on purpose."""
    if hasattr(tr, "set_hints"):
        tr.set_hints(CONFIG.whisper_hint if SETTINGS.get("whisper_hint") else None, SETTINGS.get("speech_terms"))


def ready_speech(tr) -> None:
    """A speech model that has loaded, set up as the settings say."""
    speech_hints(tr)
    # The language is a setting, so a saved one applies to the decoder as well as to the sheet
    if hasattr(tr, "language"):
        tr.language = SETTINGS.get("speech_lang")


async def own_thread(fn, *args):
    """fn(*args) on a thread of its own, for the speech model: its first load downloads it (about 460 MB for `small`),
    and nothing cuts that short. asyncio.to_thread's threads are waited for before the server's loop closes, so a
    close-down asked for during that download waited for all of it. This thread is a daemon, which nothing waits for
    (the desktop app's server role then ends without waiting for the download's own threads: desktop/app.py serve).
    Awaiting it is cancelled as anything else is."""
    loop = asyncio.get_running_loop()
    done = loop.create_future()

    def settle(result, error) -> None:
        if done.done():                  # cancelled while it ran: the server is closing down, or the choice changed
            return
        if error is not None:
            done.set_exception(error)
        else:
            done.set_result(result)

    def work() -> None:
        try:
            result, error = fn(*args), None
        except BaseException as exc:     # handed to the one awaiting it, as asyncio.to_thread hands it
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:             # the loop is closed: the server ended while this ran
            pass

    threading.Thread(target=work, name=getattr(fn, "__name__", "work"), daemon=True).start()
    return await done


async def change_speech_model(app: FastAPI, old: str, model: str) -> None:
    """The speech model chosen in the panel. It loads beside the one in use, which goes on hearing until it is ready. A
    model not downloaded yet is fetched here, as the first start fetches `small`, and one that cannot be had leaves the
    old one in use and the choice back on it: kept, it would leave the next start of the server with no speech at all."""
    await notice(t("Loading the speech model {model}: the first time it is downloaded", model=model))
    try:
        tr = await own_thread(make_transcriber, CONFIG, model)
        failed = "" if getattr(tr, "available", False) else "unavailable"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        tr, failed = None, str(exc)[:120]
    if SETTINGS.get("whisper_model") != model:   # another choice since: that one's own load settles it
        return
    if failed:
        log.warning("the speech model %s did not load (%s); %s stays", model, failed, old)
        SETTINGS.set("whisper_model", old)
        await broadcast({"type": "settings", "values": {"whisper_model": old}})
        await notice(t("The speech model {model} did not load: {old} stays", model=model, old=old), "bad")
        return
    ready_speech(tr)
    app.state.transcriber = tr   # the worker reads it at its next pass (transcription_worker)
    # A server that had no speech until now has no worker either
    if getattr(app.state, "transcribe_worker", None) is None or app.state.transcribe_worker.done():
        app.state.transcribe_worker = asyncio.create_task(transcription_worker(app))
    log.info("speech model ready (%s)", model)
    await broadcast({"type": "status", "audio": True, "lang": getattr(tr, "language", None), "voice": SETTINGS.on("voice_auto")})
    await notice(t("The speech model {model} is ready", model=model), "done")


async def load_speech(app: FastAPI) -> None:
    """The speech model, loaded after the server is up, then its worker started and the panels told that speech is
    there. A model that cannot load leaves the server without speech, and says so in the log and on the panel. One
    chosen in the panel that cannot be had any more gives way to the one the environment names."""
    model = SETTINGS.get("whisper_model")
    try:
        try:
            tr = await own_thread(make_transcriber, CONFIG, model)
        except Exception:   # the environment's own model failing is the case below; a panel's choice has that one to fall back on
            if model == CONFIG.whisper_model:
                raise
            tr = NullTranscriber()
        if model != CONFIG.whisper_model and CONFIG.audio_enabled and CONFIG.transcriber != "null" and not getattr(tr, "available", False):
            log.warning("the speech model %s did not load; going back to %s", model, CONFIG.whisper_model)
            SETTINGS.set("whisper_model", CONFIG.whisper_model)
            await broadcast({"type": "settings", "values": {"whisper_model": CONFIG.whisper_model}})
            model = CONFIG.whisper_model
            tr = await own_thread(make_transcriber, CONFIG, model)
    except asyncio.CancelledError:
        raise
    except Exception as exc:   # SIDENOTE_TRANSCRIBER=faster-whisper raises on purpose when it cannot load
        log.error("the speech model did not load (%s); the server goes on without speech", exc)
        await notice(t("The speech model did not load: questions read aloud are not heard ({why})", why=str(exc)[:120]),
                     "bad")
        return
    # Another model chosen in the panel while this one loaded, and already taken over: that one stays. Not yet: this one hears
    # until it does, and is what is left when that one cannot be had
    if SETTINGS.get("whisper_model") != model and getattr(app.state.transcriber, "available", False):
        return
    ready_speech(tr)
    app.state.transcriber = tr
    # A choice in the panel that loaded first has its worker running, and that worker reads this model at its next pass. A
    # second one would cut every sentence twice, and nothing would hold it to cancel at shutdown.
    if getattr(app.state, "transcribe_worker", None) is None or app.state.transcribe_worker.done():
        app.state.transcribe_worker = asyncio.create_task(transcription_worker(app))
    if getattr(tr, "available", False):
        log.info("speech model ready (%s)", model)
        await broadcast({"type": "status", "audio": True, "lang": getattr(tr, "language", None),
                         "voice": SETTINGS.on("voice_auto")})


async def analysis_worker(app: FastAPI) -> None:
    detector = app.state.detector
    loop = asyncio.get_running_loop()

    inflight: asyncio.Task | None = None
    inflight_frame: Frame | None = None
    inflight_voice = False   # the running analysis is a spoken problem, not a screen
    inflight_speech = ""     # its words, so a screen that stops it can have it asked again
    inflight_retake = False  # it is that second asking, which a screen change ends for good
    inflight_upto = 0        # where in the sound its words end

    async def run_analysis(frame: Frame | None, seq: int, voice: str = "", manual: bool = False, upto: int = 0) -> None:
        """_run_analysis, counted while it runs: a deploy waits for the server to be idle (activity())."""
        STATE.analyses_running += 1
        STATE.screen_seq = seq   # whose age a screen change weighs (analysis_age): a follow-up takes an id of its own meanwhile
        STATE.analysis_wrote = False   # nothing on the card yet: a newer spoken problem may still replace this one
        analysis_turn()   # a code check reading with this PC's model gives way (between_analyses)
        try:
            try:
                await _run_analysis(frame, seq, voice, manual, upto)
            except Exception as exc:   # past its own handling: the card still ends, and the worker goes on
                log.exception("analysis #%d failed after solving", seq)
                await report_error(seq, exc, "analysis", trigger="voice" if voice else "screen", elapsed=0)
        finally:
            STATE.analyses_running -= 1
            STATE.confirm_held.pop(seq, None)
            analysis_turn()   # and goes on when none runs

    async def _run_analysis(frame: Frame | None, seq: int, voice: str = "", manual: bool = False, upto: int = 0) -> None:
        """Solve the screen (if any) with the speech that goes with it. `voice` is a problem spoken
        aloud: then it is the problem itself, not side context. `manual`: the user asked for this
        one (Reanalyze), so neither brake on automatic sending applies to it. `upto`: where in the sound the
        words of `voice` end, which the next spoken problem starts from once these have their answer."""
        start = time.time()
        trigger = "voice" if voice else "screen"
        first: list[float] = []
        epoch = STATE.screen_epoch   # a screen-off from here on means this frame may not be used afterwards
        # The last answer's example check, its the agent check and its retry or continuation are about that answer, and
        # an analysis that starts has not replaced it yet: most automatic ones find nothing (a screen changing while
        # someone works on it), and stopping them here made every code answer say its check was stopped "for the next
        # problem" when none came. They stop below, when a new answer takes its place.
        # The one exception is a retry or continuation on this PC's model: it holds the GPU this analysis needs.
        if (STATE.retry_task is not None or STATE.cont_task is not None) and PIPELINE is not None \
                and STATE.last_result and followup_engine(PIPELINE, STATE.last_result) is PIPELINE._local():
            cancel_retry()
        if frame is not None and not voice:
            STATE.screen_started = seq   # the screen being looked at now, for continuation()

        async def on_delta(text: str) -> None:
            if not first:
                first.append(time.time())
                STATE.analysis_wrote = True
                # The question has its answer coming: what is said from here on does not extend it, and asks for itself
                if voice:
                    STATE.voice_asked = False
            await broadcast({"type": "delta", "id": seq, "text": text})

        try:
            if voice:
                transcript = voice
            elif CONFIG.transcribe_interval > 0:
                # Continuous loop keeps these fresh: whole utterances first, live window as fallback.
                transcript = STATE.recent_speech() or STATE.transcript.strip()
            else:
                transcript = await transcribe_current(app.state.transcriber, loop)
            await broadcast(
                {"type": "analysis_start", "id": seq, "ts": frame.ts if frame else start,
                 "thumb": frame.thumb_url if frame else None, "transcript": transcript,
                 "pages": len(frame.extra_b64) if frame else 0, "trigger": trigger,
                 "roi": SETTINGS.get("roi_box") if frame is not None else None}
            )
            log.info("analysis #%d start (%s%s)", seq, trigger, ", with screen" if frame is not None else "")
            # What was said goes into the event record only when the words are wanted there
            # (SIDENOTE_LOG_SPEECH): events.jsonl lives as long as every other log here, and it
            # hears whatever is near the microphone, not only the user.
            spoken = (voice[:200] or None) if CONFIG.log_speech == "full" else (len(voice) or None)
            telemetry.event("analysis_start", id=seq, trigger=trigger, pages=len(frame.extra_b64) if frame else 0,
                            screen=frame is not None, spoken=spoken, mode=effective_mode(),
                            **({"faces": frame.faces} if frame is not None and frame.faces else {}))
            if frame is not None and frame.faces:   # what was painted over before any model saw the screen (faces.py)
                log.info("analysis #%d: %d face(s) on the screen covered before it was read", seq, frame.faces)
            # A screen is judged on what it shows. The room's sound goes to the panel and to the voice
            # path, which answers what was asked aloud, but it is not handed to the screen's analysis:
            # measured with a coding problem on screen and a video playing, the same screen was read as a
            # problem 3 times out of 3 alone and as nothing to solve 3 times out of 3 with the video's
            # speech attached, prompt rule or not.
            result = await PIPELINE.solve(seq, frame, voice, bool(voice), on_delta, by_user=manual)
            if frame is not None and result.region and result.region_placed:   # before the answer counts as done: a cancel here loses nothing
                result.shown = await asyncio.to_thread(shown_box, frame, result.region)
        except asyncio.CancelledError:
            # pause / screen_off / sound_off keep a half-written answer on the panel with a note;
            # reanalyze / voice / superseded mean a newer analysis replaces it.
            reason, STATE.cancel_reason = STATE.cancel_reason or "superseded", None
            telemetry.event("analysis_cancelled", id=seq, trigger=trigger, reason=reason,
                            after=round(time.time() - start, 2))
            await broadcast({"type": "analysis_cancelled", "id": seq, "reason": reason})
            raise
        except GpuBusy as exc:
            # Something else has the GPU, so neither model could even read the screen. The watching's own look leaves
            # no card in the thread for it: while a GPU job runs with the capture on, every screen change
            # put up "stopped, the answer was too late". It backs off as an error does and says it once per busy
            # stretch; Reanalyze and a spoken problem still get their card, since someone is waiting on those.
            if manual or voice:
                log.warning("analysis #%d: %s", seq, exc)
                await report_error(seq, exc, "analysis", trigger=trigger, elapsed=round(time.time() - start, 2))
                return
            STATE.supersede_streak = 0
            STATE.error_streak += 1
            wait = min(60.0, 15.0 * 2 ** (STATE.error_streak - 1))   # 15 s, 30 s, then a minute
            STATE.retry_after = time.time() + wait
            telemetry.event("analysis_gpu_busy", id=seq, trigger=trigger, wait=wait)
            await broadcast({"type": "analysis_cancelled", "id": seq, "reason": "gpu_busy"})
            if STATE.error_streak == 1:
                await broadcast({"type": "notice", "level": "warn",
                                 "text": t("The GPU is slow and could not read the screen · looks less often until "
                                           "it is free")})
            return
        except Repeat as again:
            # The problem of an answer above, seen again (design 88): the screen is handled, the change watch moves to
            # where the problem is now, and the card being started goes as a superseded one would. The panel is told
            # once per answer, with what to press to have it solved again.
            STATE.supersede_streak = 0
            if frame is not None:
                detector.commit(frame)
                if again.box is not None:   # known by its words alone: where it is stays unknown, the watch as it was
                    watch_region(detector, again.box)
            telemetry.event("analysis_repeat", id=seq, trigger=trigger, of=again.card, score=round(again.score, 3))
            # The problem on the screen is that answer's now: a question is about it, and a problem scrolled together
            # continues it (screen_started), with this screen, where the problem stands now, to read it from
            was = STATE.answers.get(again.card)
            # A screen switched off in the moment before this may not come back through here: the next question would send it
            if was is not None and frame is not None and STATE.screen_epoch == epoch and (STATE.last_result or {}).get("id") != again.card:
                cancel_check()
                cancel_verify()
                cancel_retry()
                STATE.last_result = {**was, "frame": frame, "crop_box": again.box or was.get("crop_box"), "local_view": None}
                STATE.thread = []
            if frame is not None:
                STATE.screen_started = again.card
            await broadcast({"type": "analysis_cancelled", "id": seq, "reason": "repeat", "of": again.card})
            if STATE.repeat_said != again.card:
                STATE.repeat_said = again.card
                # `of`: the panel's toast leads to that answer when pressed
                await broadcast({"type": "notice", "of": again.card, "level": "info",
                                 "text": t("Already solved, not solved again · Reanalyze to solve it again")})
            return
        except NotSent:   # The agent alone, and the user chose not to send it
            STATE.supersede_streak = 0
            if frame is not None and not voice:
                detector.commit(frame)
            telemetry.event("analysis_not_sent", id=seq, trigger=trigger)
            await broadcast({"type": "analysis_cancelled", "id": seq, "reason": "not_sent"})
            return
        except Exception as exc:
            log.exception("analysis #%d failed", seq)
            STATE.supersede_streak = 0
            if frame is not None and not voice:
                detector.commit(frame)   # not retried by itself (a limit would re-run it forever): R retries
            await report_error(seq, exc, "analysis", trigger=trigger, elapsed=round(time.time() - start, 2))
            return
        STATE.supersede_streak = 0
        await note_success(result.engine, result.model)
        kind, answer = head_of(result.text)
        is_none = kind == "none"
        if voice and not is_none:
            STATE.voice_answered_to = max(STATE.voice_answered_to, upto)   # what the next one need not read
        elif voice:
            # Nothing to solve in it: the card says so under what was heard, so a sentence on the panel is not left unexplained
            await broadcast({"type": "utterance", "text": voice, "lang": getattr(app.state.transcriber, "last_language", ""),
                             "why": "told" if question_kind(voice) == "told" else "none"})
        # A run of answers that all found nothing means the screen is someone working rather than a
        # problem waiting to be read, and the worker then watches quietly (CONFIG.quiet_after). Only
        # what the tool asked by itself counts: Reanalyze asks for a proper look, which
        # ends the run below whatever it comes back with.
        quiet_before = CONFIG.quiet_after > 0 and STATE.empty_run >= CONFIG.quiet_after
        STATE.empty_run = STATE.empty_run + 1 if (is_none and not manual) else 0
        if quiet_before != (CONFIG.quiet_after > 0 and STATE.empty_run >= CONFIG.quiet_after):
            await note_capture(force=True)   # the screen card says it the moment it changes
        region = None
        # A spoken remark with nothing to solve leaves the screen as it was: the problem on it (if
        # any) is still analyzed, instead of being marked done by an answer that was about speech.
        if frame is not None and not (voice and is_none):
            detector.commit(frame)
            if not voice:   # a screen answer says where its problem is; watch only that part
                region = None if is_none else result.region
                watch_region(detector, region)
        if not is_none:
            # A new answer replaces the last one: what was still checking or filling out the old one stops now
            cancel_check()
            cancel_verify()
            cancel_retry()
            # what follow-ups refer to, and which engine answers them
            STATE.last_result = remembered(result, frame if STATE.screen_epoch == epoch else None, seq, bool(voice))
            # its picture, to know the problem when it is seen again (design 88); a spoken one has none
            seen_box = result.seen or result.region
            if (frame is not None and not voice and seen_box is not None and PIPELINE is not None
                    and STATE.screen_epoch == epoch):
                # On a task of its own: awaited here it was a place a cancel could land after the answer was done, and
                # the card then never finished
                keep_picture(seq, frame, seen_box, kind, epoch)
            remember_answer(STATE.last_result)
            STATE.repeat_said = 0     # a new answer: coming back to an earlier one is news again, and is said
            STATE.thread = []
            note_left(detector, STATE.latest_frame)   # the screen may have moved on while this was being written
        note_sent(seq, result.sent)
        STATE.analyses_done += 1
        await broadcast(
            {
                "type": "analysis_done",
                "id": seq,
                # A panel that reconnected mid-answer never saw its start, and draws the card from this
                "thumb": frame.thumb_url if frame is not None and STATE.screen_epoch == epoch else None,
                "text": result.text,
                "usage": result.usage,
                "cost_usd": result.cost_usd,
                "model": result.model,
                "engine": result.engine,
                "sent": result.sent,          # what left the PC for this answer
                "stages": result.stages,
                "elapsed": round(time.time() - start, 2),
                "first_token": round(first[0] - start, 2) if first else None,
                # The box is watched for changes either way; it is only drawn when it really places the
                # problem (on a window, not the whole screen), so the panel never points at empty wallpaper. What is drawn
                # is what the crop takes, not the model's first guess at it
                "region": list(result.shown or region) if region and result.region_placed else None,
                "region_shown": bool(result.shown),   # what the crop took, not the model's first guess
            }
        )
        telemetry.event("analysis_done", id=seq, trigger=trigger, type=kind, answer=answer or None,
                        engine=result.engine, elapsed=round(time.time() - start, 2),
                        first_token=round(first[0] - start, 2) if first else None,
                        region=[round(v, 3) for v in region] if region else None,
                        # what went to the agent and why it was given this one: the report breaks the agent's
                        # "nothing to solve" turns down by these (in one day's use they were stitched pages and crops)
                        sent=next((x.get("what") for x in result.sent or () if x.get("to") == "agent"), None),
                        via=(result.stages or {}).get("why"), **usage_fields(result))
        if not is_none:
            keep_answer(seq, kind, {
                "ts": frame.ts if frame else start, "trigger": trigger, "transcript": voice or "", "text": result.text,
                "model": result.model, "engine": result.engine, "sent": result.sent, "stages": result.stages,
                "usage": result.usage, "cost_usd": result.cost_usd, "elapsed": round(time.time() - start, 2),
                "first_token": round(first[0] - start, 2) if first else None,
                "region": list(result.shown or region) if region and result.region_placed else None,
                "region_shown": bool(result.shown),   # what the crop took, not the model's first guess
                "thumb": frame.thumb_url if frame is not None and STATE.screen_epoch == epoch else None})
        await broadcast(usage_message())
        log.info("analysis #%d done by %s (%d chars, %.2fs, region %s)", seq, result.engine, len(result.text),
                 time.time() - start, "none" if region is None else "%.2f %.2f %.2f %.2f" % region)
        if frame is not None and STATE.screen_epoch != epoch:   # switched off while this was finishing
            return
        if not is_none and checkable(PIPELINE, frame, result):
            STATE.check_task = asyncio.create_task(run_check(app, seq, frame, result))
        if PIPELINE.verifying(result):
            STATE.verify_carries = {"image": frame is not None and (not voice or SETTINGS.get("agent_payload") == "screen"),
                                    "voice": bool(voice)}
            STATE.verify_task = asyncio.create_task(run_verify(seq, frame, transcript, bool(voice), result,
                                                               by_user=manual))

    log.info("analysis worker started")
    while True:
        await asyncio.sleep(0.1)

        if inflight and inflight.done():
            inflight = None
            inflight_frame = None
            inflight_voice = False
            inflight_speech, inflight_retake = "", False

        # Paused, screen off, sound off: stop what runs now if the reason applies to it (instead of
        # letting a late answer appear). Screen off spares a spoken problem with no screen in it;
        # sound off spares a screen analysis.
        if STATE.stop_reasons:
            reasons, STATE.stop_reasons = STATE.stop_reasons, set()
            why = ("pause" if "pause" in reasons
                   else "local_off" if "local_off" in reasons
                   else "screen_off" if "screen_off" in reasons and inflight_frame is not None
                   else "sound_off" if "sound_off" in reasons and inflight_voice
                   else None)
            if why and inflight and not inflight.done():
                STATE.cancel_reason = why
                inflight.cancel()
                try:
                    await inflight
                except asyncio.CancelledError:
                    pass
                inflight = None
                inflight_frame = None
                inflight_voice = False
                inflight_speech, inflight_retake = "", False
            # A model load the stopped analysis left running would take the GPU anyway. Stopped after the
            # analysis, which would otherwise go on and start a load of its own.
            if "pause" in reasons and ENGINES is not None and ENGINES.local is not None:
                ENGINES.local.cancel_load()

        # The user asked to run it again on what is on screen now (bypasses the "same
        # screen" dedup), or on the spoken problem if there is no screen. This runs while
        # paused too: pause stops the automatic triggers, not an explicit request.
        if STATE.force_analyze:
            STATE.force_analyze = False
            voice = "" if STATE.latest_frame is not None else STATE.recent_speech()
            if STATE.latest_frame is None and not voice:
                await broadcast({"type": "notice", "level": "warn",
                                 "text": t("No screen or speech to reanalyze") if STATE.screen_on
                                 else t("Screen capture is off: no screen to reanalyze")})
                continue
            if inflight and not inflight.done():
                STATE.cancel_reason = "reanalyze"
                inflight.cancel()
                try:
                    await inflight
                except asyncio.CancelledError:
                    pass
            STATE.last_analyze_ts = time.time()
            STATE.analysis_seq += 1
            inflight_frame, inflight_voice = STATE.latest_frame, bool(voice)
            inflight_speech, inflight_retake = voice, False
            inflight_upto = STATE.utterances[-1]["end"] if voice and STATE.utterances else 0
            inflight = asyncio.create_task(run_analysis(inflight_frame, STATE.analysis_seq, voice=voice,
                                                        manual=True, upto=inflight_upto))
            continue

        # A problem spoken aloud starts an analysis right away, with the current screen if
        # there is one. It supersedes an earlier spoken problem, because each new utterance extends
        # it, but never an analysis of the screen: what the microphone hears is usually whatever the
        # PC is playing, and anything long enough that the speaker then pauses is queued as a problem
        # (above), so sound from a video was stopping the screen work that was being waited for.
        # The screen comes first, and the flag is left standing so the spoken problem starts as soon
        # as the screen answer is written, rather than being dropped.
        if STATE.voice_pending and not PIPELINE.ready():
            STATE.voice_pending = False   # nothing can answer: it would only fail; the panel says why
        if STATE.voice_pending and not SETTINGS.on("voice_auto"):
            STATE.voice_pending = False   # spoken problems are switched off, however this one got queued
        screen_busy = bool(inflight and not inflight.done() and not inflight_voice)
        # The spoken problem that runs has written its first words: its answer is let finish, and the flag stays up, so
        # the newest words start as soon as it is done. One waits: what is said in the same run of speech joins it, and after
        # a pause a newer problem takes its place. Stopped here, a speaker who went on talking dropped the answers being
        # written, 7 to 81 s after they started. With nothing written yet the problem is still being read, and the longer
        # version replaces it below.
        writing = bool(inflight and not inflight.done() and STATE.analysis_wrote)
        # Held back for any of these, its words stop aging until its turn (recent_group); no flag, nothing is held for it
        if not STATE.voice_pending:
            STATE.voice_held_at = 0.0
        elif STATE.paused or screen_busy or writing or time.time() < STATE.retry_after:
            STATE.voice_held_at = STATE.voice_held_at or time.time()
        if STATE.voice_pending and not STATE.paused and not screen_busy and not writing and time.time() >= STATE.retry_after:
            STATE.voice_pending = False
            # Read first, with the age still held: nothing to ask leaves whatever runs alone, and starts nothing. An empty
            # voice would start a screen analysis from here, past the checks a screen goes through below.
            group = STATE.recent_group()
            STATE.voice_held_at = 0.0
            if STATE.voice_retake and STATE.voice_retake in " ".join(u["text"] for u in group):
                STATE.voice_retake = ""   # the same problem read on: this run carries the stopped one's words
            # What the last answer was about is not asked again: this run is what came after it. Nothing after it: nothing to do
            speech = after_the_answer(group, STATE.voice_answered_to)
            if not speech:
                continue
            if inflight and not inflight.done():   # only ever an earlier spoken problem (screen_busy above)
                STATE.cancel_reason = "voice"
                inflight.cancel()
                try:
                    await inflight
                except asyncio.CancelledError:
                    pass
            STATE.last_analyze_ts = time.time()
            STATE.analysis_seq += 1
            inflight_frame, inflight_voice = STATE.latest_frame, True
            inflight_speech, inflight_retake = speech, False
            inflight_upto = group[-1]["end"]
            inflight = asyncio.create_task(run_analysis(inflight_frame, STATE.analysis_seq, voice=speech, upto=inflight_upto))
            continue

        # A spoken problem a screen change stopped (below, where a screen takes over) is asked once more. It was
        # dropped: its flag is cleared when its run starts and the screen's analysis does not carry speech, so a
        # question really asked aloud went unanswered whenever the screen moved to another window meanwhile.
        # Once only, so the PC's own sound cannot keep itself going against a changing screen. The screen
        # comes first, as above: the retake waits until the screen's analysis has started and finished (an analysis
        # running holds it), or until that screen has nothing new to analyze, or for as long as a new screen can be
        # kept waiting for rest and the interval, so a screen held back for some other reason cannot hold it for ever.
        if STATE.voice_retake and (not PIPELINE.ready() or not SETTINGS.on("voice_auto")):
            STATE.voice_retake = ""       # nothing can answer it, or spoken problems were switched off
        if (STATE.voice_retake and not STATE.paused and not (inflight and not inflight.done())
                and time.time() >= STATE.retry_after):
            shown = STATE.latest_frame
            behind = (shown is not None and STATE.screen_started == STATE.voice_retake_mark
                      and time.time() - STATE.voice_retake_at
                      < max(CONFIG.settle_max_sec, CONFIG.settle_busy) + CONFIG.min_analyze_interval
                      and detector.is_new(shown))
            if not behind:
                speech, STATE.voice_retake = STATE.voice_retake, ""
                STATE.last_analyze_ts = time.time()
                STATE.analysis_seq += 1
                inflight_frame, inflight_voice = shown, True
                inflight_speech, inflight_retake = speech, True
                inflight_upto = STATE.voice_retake_to
                log.info("analysis #%d: the spoken problem a screen change stopped is asked again", STATE.analysis_seq)
                inflight = asyncio.create_task(run_analysis(inflight_frame, STATE.analysis_seq, voice=speech, upto=inflight_upto))
                continue

        frame = STATE.latest_frame
        if frame is None or STATE.paused or not PIPELINE.ready():
            continue

        # The agent is the one engine and its spend brake holds, so this analysis could only come back
        # "not sent". It used to be started anyway, and every refusal left a card saying so: six of
        # them in seventeen seconds on a screen that keeps changing (measured).
        # The toast says it once a minute and the agent card says it for as long as it holds.
        # The frame is left where it is, so whatever is on screen is solved when the brake lifts.
        if brake := PIPELINE.auto_blocked():
            await PIPELINE.say_brake(brake)
            continue

        # An analysis is already running: interrupt it only if a clearly different
        # screen has appeared (the in-flight answer is now stale), or the whole scrolled
        # problem arrived while a single screen of it was being analyzed; otherwise wait.
        # A screen that keeps changing (another window in use beside the problem) would
        # cancel every analysis before it finished (measured: 79 starts, 0 answers in
        # 6 minutes), so after supersede_limit cancellations in a row the current one runs
        # to the end.
        if inflight and not inflight.done():
            # A spoken problem used to hold the screen off until its answer was written. Most of what
            # is heard is the PC's own sound, so that handed the wait to whatever was playing; a
            # screen that has clearly moved on now takes over from it on the same terms as any other
            # screen, streak limit included, so a problem really read aloud still gets its answer.
            stitched = bool(inflight_frame is not None and frame.extra_b64 and not inflight_frame.extra_b64)
            moved_on = bool(inflight_frame is not None and frame is not inflight_frame and detector.moved_on(inflight_frame, frame))
            age = analysis_age(STATE.screen_seq, STATE.last_analyze_ts)
            # Measured, once an analysis: what keeping long ones gives (supersede_keep_sec). Only those this rule kept: one the streak limit
            # would have kept anyway is not counted
            if (moved_on and not stitched and age >= CONFIG.supersede_keep_sec and STATE.supersede_streak < CONFIG.supersede_limit
                    and STATE.kept_said != STATE.screen_seq):
                STATE.kept_said = STATE.screen_seq
                telemetry.event("analysis_kept", id=STATE.screen_seq, after=round(age, 1))
            if supersede_now(stitched, moved_on, STATE.supersede_streak, age):
                STATE.supersede_streak += 1
                STATE.cancel_reason = "superseded"
                inflight.cancel()
                heard = STATE.speech_epoch   # sound off or pause during the wait below: those words are gone
                try:
                    await inflight
                except asyncio.CancelledError:
                    pass
                # A spoken problem stopped here is asked again after this screen (the retake above), once
                if inflight_voice and inflight_speech and not inflight_retake and STATE.speech_epoch == heard:
                    STATE.voice_retake, STATE.voice_retake_at, STATE.voice_retake_to = inflight_speech, time.time(), inflight_upto
                    STATE.voice_retake_mark = STATE.screen_started
                inflight = None
                inflight_frame = None
                inflight_voice = False   # whatever it was, it is not running any more
                inflight_speech, inflight_retake = "", False
            continue

        # Nothing running: start an analysis if this frame is new and the interval passed
        # (and no run of errors is being waited out).
        if time.time() < STATE.retry_after or not detector.is_new(frame):
            STATE.settle_since = 0.0        # nothing is waiting for the screen to come to rest
            continue
        # The screen has to have come to rest. A screen still being driven is not the one an answer
        # is wanted about, and asking about it anyway is what filled the day with analyses the
        # next frame cancelled (CONFIG.settle_sec). The frame waiting here is replaced by each new
        # one, so what finally goes is the screen that was stopped on. A screen that never comes to
        # rest (a video in a corner, a progress bar) would otherwise be watched and never asked
        # about, so a frame that has waited settle_max_sec goes as it stands.
        if STATE.settle_since == 0.0:
            STATE.settle_since = time.time()
        # How long it has to rest depends on what came before it. Frames following one another
        # closely are a screen being driven, and the pause between two of them is not a stop
        # to read; a frame arriving after a calm stretch is, so that one goes at the short
        # settle. Without this split the short settle was used for both and half of what started was
        # cancelled by the next frame within two seconds (CONFIG.settle_busy).
        busy = STATE.prev_frame_ts > 0 and STATE.last_frame_ts - STATE.prev_frame_ts < CONFIG.busy_gap
        need = max(CONFIG.settle_sec, CONFIG.settle_busy) if busy else CONFIG.settle_sec
        if (CONFIG.settle_sec > 0 and time.time() - STATE.last_frame_ts < need
                and (CONFIG.settle_max_sec <= 0 or time.time() - STATE.settle_since < CONFIG.settle_max_sec)):
            continue
        # How long since the last analysis is enough, unless the watching has gone quiet: a run of
        # empty answers means the screen is somebody working, and a small change on it waits
        # quiet_sec. A wholesale change, meaning another window, another page or the next problem on
        # the same template, is never held back, whatever the run.
        wait = CONFIG.min_analyze_interval
        if (CONFIG.quiet_after > 0 and STATE.empty_run >= CONFIG.quiet_after
                and detector.jumped(frame) < CONFIG.change_threshold * CONFIG.quiet_jump_ratio):
            wait = max(wait, CONFIG.quiet_sec)
        if time.time() - STATE.last_analyze_ts < wait:
            continue
        STATE.settle_since = 0.0
        STATE.last_analyze_ts = time.time()
        # A problem the capture program scrolled together shortly after its answer: it is being read on, so the
        # answer is filled out from the whole of it under the same card instead of solved again as a new one. Like
        # the retry it is the watching's own (a newer answer stops it) and it never holds the screen back. Which
        # scrolled problems are that answer's, and which are not, is continuation()'s.
        cont = continuation(frame)
        if cont:
            detector.commit(frame)                    # this scrolled-together problem is handled, now or before
            STATE.last_result["screen"] = frame       # the answered problem's screen now (note_left)
            if cont == "continue":
                stop_followup(STATE.cont_task)        # one still filling it out from fewer pages
                STATE.last_result["cont_sig"] = frame.extra_sig   # what it was filled out from
                STATE.cont_task = asyncio.create_task(run_followup(app, CONTINUE_QUESTION,
                                                                   cont={"label": t(CONTINUE_LABEL), "frame": frame}))
            continue
        STATE.analysis_seq += 1
        inflight_frame, inflight_voice = frame, False
        inflight_speech, inflight_retake = "", False
        inflight = asyncio.create_task(run_analysis(frame, STATE.analysis_seq))


def no_core_dumps() -> None:
    """Make the core-dump limit 1 for this process and every CLI it starts, as compose's `ulimits: core: 1` does.

    On WSL a crash's core goes to a helper that writes it into the Windows temp folder (hundreds of MB for one Node
    crash), and exactly 1 is the limit that makes the kernel skip it. A pod has no ulimits field, so a cluster on WSL
    (or any node) gets the same limit from here. Lowering a limit needs no privilege."""
    if resource is None:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
        # the soft limit to 1, the hard one left as it is (a hard limit of 0 cannot be raised to 1, and needs nothing)
        if soft != 1 and (hard == resource.RLIM_INFINITY or hard >= 1):
            resource.setrlimit(resource.RLIMIT_CORE, (1, hard))
    except (ValueError, OSError) as exc:
        log.warning("the core-dump limit could not be set (%s)", exc)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        telemetry.setup()
        no_core_dumps()
        # A plain thread, started before anything can block the loop: see server/watchdog.py.
        stop_watchdog = watchdog.start(asyncio.get_running_loop(), CONFIG.stall_warn_sec,
                                       CONFIG.stall_exit_sec, telemetry.LOG_DIR)
        load_switches()
        global ENGINES, PIPELINE
        SETTINGS.load()
        ENGINES = make_engines(CONFIG)
        if ENGINES.local is not None:
            async def on_tool(name: str, arguments: str) -> None:
                # Web search sends words from the screen to search engines: say so on the panel, every time.
                try:
                    args = json.loads(arguments or "{}")
                except ValueError:
                    args = {}
                what = str(args.get("query") or args.get("url") or "")[:160]
                telemetry.event("web", tool=name, arg=what)
                await broadcast({"type": "notice", "level": "info",
                                 "text": t("Web search: {what}" if name == "web_search" else "Reading a page: {what}",
                                           what=what)})

            ENGINES.local.on_tool = on_tool
        PIPELINE = Pipeline(ENGINES, Hooks(local_ok=lambda: bool(STATE.local.get("ok")),
                                           agent_ok=lambda: bool(STATE.agent.get("ok")),
                                           notice=notice, warn=lambda text: notice(text, "warn"),
                                           stage=stage, confirm=confirm_send,
                                           agent_failed=agent_failed))
        STATE.local, STATE.agent = await check_local(), await check_agent()
        log.info("local engine: %s; the agent: %s", STATE.local, STATE.agent)
        telemetry.event("auth", ok=STATE.agent.get("ok"), method=STATE.agent.get("method"),
                        local=STATE.local.get("ok"), local_model=STATE.local.get("model"))
        # The speech model loads once the server is up (load_speech): a first start downloads it (about 460 MB for
        # `small`), and the panel and the screen's answers need not wait for that. Until then there is no speech.
        app.state.transcriber = NullTranscriber()
        app.state.ocr = make_ocr(CONFIG)
        app.state.detector = make_detector(CONFIG, app.state.ocr)
        watch_region(app.state.detector, None)
        take_up_after_restart(app.state.detector)
        telemetry.take_up_today()
        def worker_ended(task: asyncio.Task) -> None:   # the worker is the panel's whole automatic half: it does not stay down
            if task.cancelled() or task.exception() is None:
                return
            log.error("the analysis worker stopped: %r; starting it again", task.exception())
            app.state.worker = asyncio.create_task(analysis_worker(app))
            app.state.worker.add_done_callback(worker_ended)
        app.state.worker = asyncio.create_task(analysis_worker(app))
        app.state.worker.add_done_callback(worker_ended)
        app.state.transcribe_worker = None
        app.state.speech_model_task = None
        app.state.speech_task = asyncio.create_task(load_speech(app))
        crop_on = CONFIG.crop != "off" and app.state.ocr is not None
        audio_on = getattr(app.state.transcriber, "available", False)
        log.info(
            "ready on %s:%d  analyzer=%s agent=%s gate=%s audio=%s crop=%s",
            CONFIG.host, CONFIG.port, CONFIG.analyzer, CONFIG.agent, app.state.detector.mode,
            ("continuous" if (audio_on and CONFIG.transcribe_interval > 0) else "on") if audio_on else "off",
            CONFIG.crop if crop_on else "off",
        )
        telemetry.event("server_start", analyzer=CONFIG.analyzer, agent=CONFIG.agent, gate=app.state.detector.mode,
                        audio=bool(audio_on), local_model=main_model(CONFIG) if ENGINES.local else None,
                        agent_model=CONFIG.agent_model or None, mode=effective_mode(),
                        screen=STATE.screen_on, sound=STATE.audio_on, paused=STATE.paused)

        async def prune_loop() -> None:   # age-based retention at the start and while the server stays up
            # At the start too: a server run for a few hours at a time, with nothing new being kept, would otherwise never
            # come to this, and what was heard would stay past its age
            while True:
                try:     # a full disk is when this matters most: one failure does not end it for good
                    telemetry.prune()
                    await asyncio.get_running_loop().run_in_executor(HISTORY_WRITES, HISTORY.prune)
                except Exception:
                    log.exception("pruning failed; trying again in six hours")
                await asyncio.sleep(6 * 3600)

        app.state.prune_task = asyncio.create_task(prune_loop())
        app.state.auth_task = asyncio.create_task(engine_watch())
        app.state.gpu_task = asyncio.create_task(gpu_watch())
        app.state.cli_task = asyncio.create_task(learn_agent_cli())
        app.state.runner_task = asyncio.create_task(runner_watch())
        # whether a newer release is out: a minute from now, then once a day, while the switch and the environment let it
        app.state.update_task = asyncio.create_task(RELEASES.run(lambda: bool(SETTINGS.get("update_check")),
                                                                 publish_update))
        try:
            yield
        finally:
            stop_watchdog()     # closing down is not a stall: the armed timer would end it mid-way
            telemetry.event("server_stop", analyses=STATE.analyses_done)
            keep_for_restart(app.state.detector)
            app.state.update_task.cancel()
            app.state.prune_task.cancel()
            app.state.gpu_task.cancel()
            app.state.cli_task.cancel()
            if STATE.gpu_loading is not None:
                STATE.gpu_loading.cancel()
            app.state.auth_task.cancel()
            app.state.runner_task.cancel()
            app.state.worker.cancel()
            app.state.speech_task.cancel()
            if app.state.speech_model_task is not None:
                app.state.speech_model_task.cancel()
            if app.state.transcribe_worker is not None:
                app.state.transcribe_worker.cancel()
            cancel_check()
            cancel_verify()
            for engine in (ENGINES.local, ENGINES.agent):
                aclose = getattr(engine, "aclose", None)
                if aclose:
                    try:
                        await aclose()
                    except Exception:
                        pass

    app = FastAPI(title="sidenote", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    app.add_middleware(PeerGuard)   # added last, so it runs first

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "version": VERSION,       # which release this server's code is (server/version.py)
                "build": panel_build(),   # which panel this server serves (./sidenote version)
                "analyzer": CONFIG.analyzer,
                "agent": CONFIG.agent,
                "agent_label": agent_label(CONFIG.agent),
                # the models actually in use: SIDENOTE_MODEL only applies to the Anthropic API agent
                "local_model": main_model(CONFIG) if ENGINES.local is not None else None,
                "agent_model": (CONFIG.model if CONFIG.agent == "anthropic-api" else "mock" if CONFIG.agent == "mock"
                                else None if CONFIG.agent == "off"
                                else CONFIG.agent_model or f"{agent_label(CONFIG.agent)} (its own default)"),
                "engines": engines_status(),
                "gate": app.state.detector.mode,
                "crop": CONFIG.crop if (CONFIG.crop != "off" and app.state.ocr is not None) else False,
                "audio": getattr(app.state.transcriber, "available", False),
                "transcribe": "continuous" if (getattr(app.state.transcriber, "available", False) and CONFIG.transcribe_interval > 0) else "on-demand",
                "speech_lang": getattr(app.state.transcriber, "language", None),
                "paused": STATE.paused,
                "auth": STATE.agent,
                "run_enabled": run_enabled(),
                "runner": {"configured": bool(CONFIG.runner_url), "ok": STATE.runner_ok},
                "capture": {k: v for k, v in capture_status().items() if k != "type"},
                "panel_clients": len(STATE.panel_clients),
                "analyses_done": STATE.analyses_done,
                "activity": activity(),
            }
        )

    @app.post("/capture/restart")
    async def capture_restart(request: Request, quiet: bool = False) -> JSONResponse:
        """The capture program restarts itself, as from its tray's Restart, into the capture.py on disk now: at once
        (`./sidenote capture-restart`), or with `quiet` at a moment when the screen rests and nothing runs here
        (`./sidenote up`, when it deployed code other than what the program runs: client/capture.py, Updater)."""
        return await ask_captures(request, "restart", "/capture/restart", {"quiet": True} if quiet else {})

    @app.post("/capture/quit")
    async def capture_quit(request: Request) -> JSONResponse:
        """`./sidenote capture-stop` asks the capture program to end itself instead of killing it,
        so it takes its tray icon with it: a killed program leaves the icon in the notification
        area until something hovers over it. Reachable from this PC only, like everything here."""
        # A page open in the browser can post here across sites (a plain form post needs no
        # permission); `./sidenote capture-stop` sends no Origin at all. So an Origin that is not
        # this server's own is refused, as the panel's socket already is.
        return await ask_captures(request, "quit", "/capture/quit")

    @app.post("/server/stop")
    async def server_stop(request: Request) -> JSONResponse:
        """The desktop app closes the server down through here: Windows has no SIGTERM, and `taskkill /F` skipped the
        shutdown, so nothing was kept for the next start (the screen still showing was solved again) and the logs had no
        server_stop. Only with the token the app gave this server when it started it (SIDENOTE_STOP_TOKEN): a page in
        the browser cannot add the header without a preflight this server never answers, and knows no token."""
        token = os.environ.get("SIDENOTE_STOP_TOKEN", "")
        given = request.headers.get("x-sidenote-stop", "")
        if not token or not hmac.compare_digest(given.encode(), token.encode()):
            telemetry.event("refused", path="/server/stop")
            return JSONResponse({"error": "not allowed"}, status_code=403)
        log.info("asked to close down by the app")
        # once this reply is out: uvicorn takes it as Ctrl+C and runs the shutdown (the lifespan's finally)
        asyncio.get_running_loop().call_later(0.2, signal.raise_signal, signal.SIGINT)
        return JSONResponse({"stopping": True}, status_code=202)

    async def ask_captures(request: Request, what: str, path: str, extra: dict | None = None) -> JSONResponse:
        """Send every capture program connected `{"type": what, **extra}`, for a request from this PC."""
        origin = request.headers.get("origin")
        if origin and not any(origin == f"http://{h}:{CONFIG.port}" or origin == f"http://{h}"
                              for h in LOCAL_HOSTS):
            telemetry.event("refused", path=path, origin=origin[:120])
            return JSONResponse({"error": "not allowed"}, status_code=403)
        asked = 0
        for ws in list(STATE.ingest_ws):
            try:
                await ws.send_text(json.dumps({"type": what, **(extra or {})}))
                asked += 1
            except Exception:
                STATE.ingest_ws.discard(ws)
        log.info("asked %d capture program(s) to %s", asked, "end" if what == "quit" else what)
        return JSONResponse({"asked": asked})

    @app.get("/history")
    async def history_rows(day: str = "", q: str = "", kind: str = "", limit: int = 60, starred: bool = False):
        """The answers kept, the newest first (server/history.py), for the panel's contents; starred=1 for the starred only."""
        rows = await asyncio.to_thread(HISTORY.query, day, q[:200], kind, limit, starred)
        return JSONResponse({"answers": rows})

    @app.get("/heard")
    async def heard_rows(day: str = ""):
        """What was heard and kept (Keep what is heard): the days that hold any, the newest first, and the lines of one
        of them, by default the newest, in the order they were said."""
        days = await asyncio.to_thread(HISTORY.heard_days)
        day = day if any(d["day"] == day for d in days) else (days[0]["day"] if days else "")
        lines = await asyncio.to_thread(HISTORY.heard_lines, day) if day else []
        return JSONResponse({"days": days, "day": day, "lines": lines})

    @app.get("/history/days")
    async def history_days():
        # the days that have answers, how many answers are starred (the contents' Starred choice), and whether anything
        # heard is kept (the keys to it)
        return JSONResponse({"days": await asyncio.to_thread(HISTORY.days_list),
                             "starred": await asyncio.to_thread(HISTORY.starred_count),
                             "heard": await asyncio.to_thread(HISTORY.heard_any)})

    @app.get("/stats")
    async def stats() -> JSONResponse:
        """Monitoring snapshot (./sidenote stats): counters, recent latency and cost, the last
        error, sign-in, capture client, log folder size."""
        snap = telemetry.snapshot()
        snap.update({
            "analyzer": CONFIG.analyzer, "agent": CONFIG.agent, "agent_label": agent_name(), "paused": STATE.paused,
            "auth": STATE.agent, "engines": engines_status(),
            "settings": {k: v for k, v in SETTINGS.snapshot().items() if v != SETTINGS.defs[k].default},
            "capture": {k: v for k, v in capture_status().items() if k != "type"},
            "panels": len(STATE.panel_clients), "analyses_done": STATE.analyses_done,
            "watching_region": list(app.state.detector.region) if app.state.detector.region else None,
        })
        return JSONResponse(snap)


    @app.websocket("/ingest")
    async def ingest(ws: WebSocket) -> None:
        if not same_origin(ws):
            telemetry.event("refused", path="/ingest", origin=str(ws.headers.get("origin"))[:120])
            await ws.close(code=1008)
            return
        await ws.accept()
        peer = ws.client.host if ws.client else "?"
        log.info("ingest client connected: %s", peer)
        loop = asyncio.get_running_loop()
        STATE.captures += 1
        STATE.ingest_ws.add(ws)
        counts = {"frame": 0, "audio": 0}
        telemetry.event("capture_connect", peer=peer)

        async def handle(raw: str) -> None:
            try:  # one bad message is skipped, not allowed to drop the client's connection
                # A frame's message is megabytes of base64: parsed here it stalls every panel and stream for its length
                data = json.loads(raw) if len(raw) < 65536 else await loop.run_in_executor(None, json.loads, raw)
                kind = data.get("type")
                if kind == "frame" and not STATE.screen_on:
                    return   # switched off in the panel (an older client may still send)
                if kind == "audio" and not STATE.audio_on:
                    return
                if kind == "frame":
                    epoch = STATE.screen_epoch
                    ocr = getattr(app.state, "ocr", None)
                    def prepare():    # the decoding too, off the event loop
                        png = base64.b64decode(data["data"])
                        extra = [base64.b64decode(x) for x in data.get("extra") or ()]
                        return prepare_frame(png, CONFIG.max_image_width, ocr, CONFIG.crop, extra)
                    prepared = await loop.run_in_executor(None, prepare)
                    prepared.windows = window_list(data.get("windows"))
                    if not STATE.screen_on or STATE.screen_epoch != epoch:
                        return   # switched off while this screen was being prepared: never analyze it
                    STATE.latest_frame = prepared
                    # what on it is moving right now (a video beside it), and whether anything else changed
                    changed = app.state.detector.observe(prepared)
                    note_left(app.state.detector, prepared)     # whether the screen moved on from the last answer's screen
                    stamp_frame(changed)
                    counts["frame"] += 1
                    await note_capture()
                elif kind == "audio":
                    STATE.push_audio(base64.b64decode(data["data"]), int(data.get("sr", 16000)))
                    STATE.last_audio_ts = time.time()
                    counts["audio"] += 1
                    await note_capture()
                elif kind == "capture_set":
                    # The capture program's own tray switches: the same as the panel's, so every panel is told
                    # (capture_status) and the program gets them back as control. Ignored before, the tray's
                    # switch changed only the program's copy and the next control message undid it.
                    await set_capture(screen=data["screen"] if isinstance(data.get("screen"), bool) else None,
                                      audio=data["audio"] if isinstance(data.get("audio"), bool) else None)
                elif kind in ("hello", "caps"):
                    if kind == "hello":
                        log.info("ingest hello: %s", data.get("info"))
                        STATE.capture_info = str(data.get("info") or "")
                        # A capture program starting is a new sitting: a region drawn in the last one is about a
                        # screen that is gone, and left set it hid every problem outside it (seen twice).
                        # Only the hello of a start carries the options it was started with (`flags`, empty or not;
                        # client/capture.py drops them after its first connect), so a reconnect after a server
                        # restart or a dropped connection keeps the region, as design 56 promises.
                        if "flags" in data and SETTINGS.get("roi_box"):
                            await apply_setting(app, "roi_box", None)
                            await notice(t("Capture started anew: region cleared · sees the whole screen"))
                    # "code": which capture.py it runs (./sidenote up compares it with the file it deployed);
                    # "skipping": a window of Skip windows is on screen, so no screen comes (never which window);
                    # "skip_limit": what that switch can do on this desktop (the panel's card says so)
                    caps = {k: data[k] for k in ("screen", "audio", "audio_device", "monitor", "no_audio",
                                                 "monitors", "code", "skipping", "skip_limit") if k in data}
                    if "skipping" in caps:
                        caps["skipping"] = caps["skipping"] is True   # a yes or a no, whatever a client sends
                    if "skip_limit" in caps and caps["skip_limit"] not in ("none", "front"):
                        caps["skip_limit"] = ""                       # one of two words, so nothing else can reach the panel
                    if caps:
                        STATE.capture_caps = {**STATE.capture_caps, **caps}
                    if isinstance(data.get("monitors"), list):   # the panel offers these
                        mons = [m for m in data["monitors"] if isinstance(m, list) and len(m) == 2][:8]
                        # labels in English, with their numbers beside them: put in the panel's language when sent
                        SETTINGS.set_options("monitor", [(0, "All monitors")]
                                             + [(i, ("Monitor {i} ({w}x{h})", {"i": i, "w": w, "h": h}))
                                                for i, (w, h) in enumerate(mons, start=1)])
                        await broadcast({"type": "settings", "values": {}, "options": {"monitor": SETTINGS.options("monitor")}})
                    # Options the capture program was started with win over the panel's last choice.
                    for k, v in (data.get("flags") or {}).items():
                        if k in ("monitor", "stitch") and SETTINGS.get(k) != v:
                            ok, _ = SETTINGS.set(k, v)
                            if ok:
                                await broadcast({"type": "settings", "values": {k: v}})
                    telemetry.event("capture_" + kind, info=STATE.capture_info[:200], **caps)
                    await note_capture(force=True)
            except Exception:
                log.exception("ingest: skipped a bad message")

        try:
            # The client says hello (with the options it was started with) first; the switches go
            # out after that, so they already include those options.
            try:
                await handle(await asyncio.wait_for(ws.receive_text(), 3.0))
            except asyncio.TimeoutError:
                pass
            await ws.send_text(control_message())   # the client starts in the state the panel wants
            await note_capture(force=True)
            while True:
                await handle(await ws.receive_text())
        except WebSocketDisconnect as exc:
            if exc.code == 1009:   # a message over uvicorn's --ws-max-size (docker/entrypoint.sh): it is lost
                log.warning("ingest client disconnected: %s sent a message larger than the server takes (1009)", peer)
            else:
                log.info("ingest client disconnected: %s (code %s)", peer, exc.code)
        except Exception:
            log.exception("ingest error")
        finally:
            STATE.captures -= 1
            STATE.ingest_ws.discard(ws)
            if not STATE.captures:
                STATE.capture_caps = {}
            telemetry.event("capture_disconnect", peer=peer, frames=counts["frame"], audio_chunks=counts["audio"])
            await note_capture(force=True)

    @app.websocket("/panel")
    async def panel(ws: WebSocket) -> None:
        if not same_origin(ws):
            telemetry.event("refused", path="/panel", origin=str(ws.headers.get("origin"))[:120])
            await ws.close(code=1008)
            return
        await ws.accept()
        STATE.panel_clients.add(ws)
        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "text": "connected",
                    "analyzer": CONFIG.analyzer,
                    "gate": app.state.detector.mode,
                    "paused": STATE.paused,
                    "lang": getattr(app.state.transcriber, "language", None),
                    "audio": getattr(app.state.transcriber, "available", False),
                    "voice": SETTINGS.on("voice_auto") and getattr(app.state.transcriber, "available", False),
                    "crop": CONFIG.crop if (CONFIG.crop != "off" and app.state.ocr is not None) else False,
                    "can_ask": STATE.last_result is not None,   # a reloaded panel can still ask follow-ups
                    "run_enabled": run_enabled(),                # show the "run this solution" button
                    "runner": bool(CONFIG.runner_url),           # the run button and the check can be switched on
                    "engines": panel_engines(),
                    "build": panel_build(),   # a panel left open on an older build says so
                    "desktop": CONFIG.desktop,   # the desktop app's server: directions name the app, not ./sidenote
                    "version": VERSION,          # shown in the gear menu
                    "update_check": RELEASES.allowed(),   # false: SIDENOTE_UPDATE_CHECK=0 (or mock mode) leaves the switch nothing to do
                    "update": update_status(),   # a newer release found before this panel opened, or None
                }
            )
        )
        await ws.send_text(json.dumps({"type": "settings", "meta": SETTINGS.meta(), "values": SETTINGS.snapshot()}))
        await ws.send_text(json.dumps(capture_status()))
        await ws.send_text(json.dumps(usage_message()))
        # The plan's meters at once, not at the watcher's next turn: a panel opened after a restart stood without them for ten seconds and more
        if time.time() - STATE.quota_at >= 90:
            STATE.quota_task = asyncio.create_task(refresh_quota())
        for fut, msg in list(STATE.confirms.values()):   # a confirm still waiting shows on a panel opened now
            if not fut.done():
                # With the time it has left, not the time it started with: a panel opened 100 s into
                # a 120 s wait would otherwise count 120 down and then watch the card vanish.
                left = max(0.0, round(msg["timeout"] - (time.time() - msg["ts"]), 1))
                await ws.send_text(json.dumps({**msg, "timeout": left, "ts": time.time()}))

        async def reply(m: dict) -> None:   # to this panel only (a code run's result)
            try:
                await ws.send_text(json.dumps(m))
            except Exception:
                pass
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                kind = data.get("type")
                if kind in ("pause", "resume", "reanalyze", "ask", "set_lang", "capture_set"):
                    telemetry.event("control", action=kind, lang=data.get("lang") if kind == "set_lang" else None,
                                    screen=data.get("screen"), audio=data.get("audio"))
                if kind == "capture_set":
                    await set_capture(screen=data["screen"] if isinstance(data.get("screen"), bool) else None,
                                      audio=data["audio"] if isinstance(data.get("audio"), bool) else None)
                    continue
                if kind in ("pause", "resume"):
                    await set_paused(kind == "pause")
                    continue
                elif kind == "reanalyze":
                    STATE.force_analyze = True
                    user_asked()                 # Reanalyze is pressed by hand: no brake
                    continue
                elif kind == "ask":
                    question = str(data.get("text") or "").strip()[:2000]
                    if question:
                        spawn(run_followup(app, question), "followup")
                    continue
                elif kind == "problem_text":   # Problem text: the last problem as text, to copy (this panel only)
                    spawn(reply_later(reply, problem_text(data.get("id"))), "problem_text")
                    continue
                elif kind == "run":
                    rid = data.get("id")
                    if rid is None:
                        continue
                    spawn(run_code(rid, str(data.get("lang") or ""), str(data.get("code") or ""),
                                   str(data.get("stdin") or ""), reply=reply), "run")
                    continue
                elif kind == "setting":
                    key = str(data.get("key") or "")
                    ok, err = await apply_setting(app, key, data.get("value"))
                    if not ok:
                        await reply({"type": "notice", "level": "warn", "text": err})
                    continue
                elif kind == "agent_confirm_reply":
                    fut, _ = STATE.confirms.get(str(data.get("cid") or ""), (None, None))
                    if fut is not None and not fut.done():
                        fut.set_result(bool(data.get("send")))
                        telemetry.event("agent_confirm", send=bool(data.get("send")))
                    continue
                elif kind == "thumb":   # a screen to draw the box on, and how old it is
                    # The switch being on does not mean a screen is coming: the capture program may have
                    # ended hours ago and its last screen is still here. It is still worth drawing on (the
                    # box is kept in screen fractions for the next screen), so it is sent with its age and
                    # whether anything is sending now, and the panel says which it is showing.
                    frame = STATE.latest_frame if STATE.screen_on else None
                    await reply({"type": "thumb", "url": frame.thumb_url if frame else None,
                                 "ts": STATE.last_seen_ts if frame else None,
                                 "live": bool(frame and STATE.captures and STATE.screen_on),
                                 "text": None if frame else (t("Screen capture is off") if not STATE.screen_on
                                                             else t("No screen received")
                                                             if not STATE.captures else t("No screen received"))})
                    continue
                elif kind == "gpu_release":
                    local = ENGINES.local if ENGINES is not None else None
                    if local is None:
                        continue
                    done = await local.unload()
                    telemetry.event("gpu_release", reason="panel", ok=done)
                    STATE.local = await check_local()
                    # The runtime still lists it for a moment after saying yes: taken at its word the button stayed for
                    # the next look, 20 s on, and was pressed again
                    if done:
                        STATE.local = {**STATE.local, "loaded": None}
                    await broadcast_engines()
                    await reply({"type": "notice", "level": "done" if done else "bad",
                                 "text": t("Taken off the GPU · loaded again for the next problem")
                                 if done else t("Taking it off the GPU failed")})
                    continue
                elif kind == "history_clear":   # Clear the history: what is kept goes too
                    cleared = await asyncio.get_running_loop().run_in_executor(HISTORY_WRITES, clear_history)
                    # Nothing held still points at the answers that went: the same problem seen again is solved, not "above"
                    if PIPELINE is not None:
                        PIPELINE.recent.forget()
                    STATE.answers.clear()
                    STATE.repeat_said = 0
                    telemetry.event("history_clear", ok=cleared)
                    await reply({"type": "notice", "level": "done" if cleared else "bad",
                                 "text": t("Cleared, the saved history too") if cleared
                                 else t("Clearing the saved history failed")})
                    continue
                elif kind == "star":   # the star key on an answer's head: kept past the history's limits
                    seq, on = data.get("id"), data.get("starred")
                    # an answer's id is a number (a follow-up's parent drawn by the panel alone is not), the star a yes or no
                    if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(on, bool):
                        continue
                    # On the history's own thread, after the write that keeps the answer: a star pressed as it ends is not lost
                    held, count = await asyncio.get_running_loop().run_in_executor(HISTORY_WRITES, star_answer, seq, on)
                    if not held:   # refused: this panel is told why, and no panel changes
                        await reply({"type": "notice", "level": "warn", "text":
                                     t("Not unstarred: this answer is not in the saved history") if not on
                                     else t("Not starred: Keep answers is off, so this answer was not saved")
                                     if not SETTINGS.get("history_keep")
                                     else t("Not starred: this answer is not in the saved history")})
                        continue
                    telemetry.event("star", id=seq, starred=on)
                    # every panel shows it, with how many are starred for the contents' Starred choice
                    await broadcast({"type": "star", "id": seq, "starred": on, "n": count})
                    continue
                elif kind == "gpu_load":   # Load onto the GPU: the model on the GPU now, not at the next problem
                    local = ENGINES.local if ENGINES is not None else None
                    if local is None or not SETTINGS.on("local_llm"):
                        await reply({"type": "notice", "level": "warn",
                                     "text": t("The local model is off: nothing to load onto the GPU")})
                        continue
                    if STATE.gpu_loading is None or STATE.gpu_loading.done():
                        STATE.gpu_loading = asyncio.create_task(load_local(local))   # a load takes seconds: this socket keeps reading
                        await broadcast_engines()              # the panel's button says it is loading, and offers to stop
                    continue
                elif kind == "gpu_load_cancel":   # changed their mind while it loads: stop, and give the GPU back
                    task, STATE.gpu_loading = STATE.gpu_loading, None
                    live = task is not None and not task.done()
                    if live:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    local = ENGINES.local if ENGINES is not None else None
                    # The press came too late, or from a second panel: the load had ended, and taking the model off now would
                    # cut an answer being written. And a problem may be waiting on this same load: only the panel's wait stops.
                    waited_on = live and activity()["busy"]
                    if live and not waited_on and local is not None:
                        await local.unload()
                    STATE.local = await check_local()
                    if live and not waited_on:
                        STATE.local = {**STATE.local, "loaded": None}   # what the server says on the way down is not yet true
                    await broadcast_engines()
                    await reply({"type": "notice", "level": "info",
                                 "text": t("Loading onto the GPU stopped") if live and not waited_on else
                                 t("A problem is waiting on it: still loading") if waited_on else
                                 t("Already loaded")})
                    continue
                elif kind == "settings_reset":
                    back = [(k, i.default) for k, i in SETTINGS.defs.items() if SETTINGS.get(k) != i.default]
                    done = 0
                    for k, v in back:          # one at a time: each has its own work to do
                        ok, _ = await apply_setting(app, k, v)
                        done += bool(ok)       # a default outside the live options (a model that is
                    left = len(back) - done    # no longer there) is refused, and is not counted
                    await broadcast({"type": "notice", "level": "warn" if left else "done" if back else "info", "text":
                                     t("Already all defaults") if not back else
                                     t("Settings back to default: {n}", n=done)
                                     + (t(", failed: {n}", n=left) if left else "")})
                    continue
                elif kind == "llm_pull":
                    # the local model's card offered a download (engines.local.pull): one at a time, of a known model
                    if pull_allowed() and not PULL:
                        spawn(pull_model(str(data.get("model") or "")), "llm pull")   # held, as every background task is
                    continue
                elif kind == "ui_lang":
                    # The panel's own language, said once it connects: the server's words follow the last panel to
                    # say one, and a change sends every panel the messages that carry them again (the settings' words,
                    # the engines' cards)
                    if i18n.set_lang(str(data.get("lang") or "")):
                        log.info("panel language -> %s", i18n.LANG)
                        await broadcast({"type": "settings", "meta": SETTINGS.meta(), "values": SETTINGS.snapshot()})
                        await broadcast_engines()
                    continue
                elif kind == "set_lang":
                    tr = app.state.transcriber
                    lang = data.get("lang")
                    if lang not in ("auto", "ko", "en") or not hasattr(tr, "language"):
                        continue
                    tr.language = lang     # the worker re-transcribes the buffer in it
                    log.info("speech language -> %s", lang)
                    await broadcast({"type": "status", "lang": lang})
                    continue
                else:
                    continue
        except WebSocketDisconnect:
            pass
        except Exception:   # a message the loop could not handle ends this panel's socket: it reconnects, and the log says why
            log.exception("a panel's connection ended on an error")
        finally:
            STATE.panel_clients.discard(ws)

    # The panel and its files (index.html, app.js, theme.js, fonts.css, new.css, vendor/), after the routes above.
    app.mount("/", StaticFiles(directory=PANEL_DIR, html=True), name="panel")
    return app


app = create_app()
