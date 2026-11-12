"""Several clients of one server, as one shared by more than its person would have: capture programs from more than
one place, and more panels than one person opens. A real server on a free port (mock engines, a log folder of its
own), clients by websocket-client as a capture program connects, and client/capture.py's own Sender:

- a capture program that connects while another feeds the server takes over: the one before is asked to quit, with
  the reason and the newer one's name (without the terminal codes it was sent with); what it still sends as it ends
  is not taken (its card, its tray's switch); the server counts one, its card says what the newer one can do, and the
  panels are told (docs/README.md: one capture program feeds a server; the PC's own lock keeps a second off that PC,
  this meets one from another PC or account);
- one that does not end itself is closed when TAKEN_OVER_SEC (10 s) have passed, and not before;
- a program's own earlier connection (the same run: one a PC's sleep left open on the server) is closed at once, with
  no quit and no word to the panels;
- what takes nothing over: a --once run (its hello says so), a connection that never says hello, and one taken over
  before its late hello came;
- the real Sender, once asked to quit, never connects again, even with its connection gone and sound still to send
  (connecting, it would take the server back from the newer one);
- the Sender taken over takes no restart after it (a copy of it would take the server back);
- the capture program itself (on a private Xvfb display, no tray, no sound): a real --once run beside it sends its
  screen and ends, leaving it running and the drawn region in place; taken over, it ends with its own exit code (77,
  on which the desktop app starts its own again) and says why;
- 40 panels opening at once: 32 get in (MAX_PANELS), the rest are refused at the handshake, and one closing lets a
  next one in;
- the server's own caps, with the server started as docker/entrypoint.sh starts it: 8 capture connections at once
  (MAX_INGEST) and the 9th refused at its handshake; a panel's message over 2 MB (MAX_BODY) closed with 1009, never
  parsed; 512 connections held open by a program and the next request answered 503 at once, with uvicorn's warning
  written once for many; the desktop app's server started with the same cap.

    .venv/bin/python tests/many_clients.py
"""
import ctypes.util
import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import websocket
from websocket import ABNF

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail != "" and not ok else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
LOGS = tempfile.mkdtemp(prefix="sidenote-clients-")
# The server's environment as tests/stalled_panel.py gives it: stand-in engines, nothing reached outside this PC
ENV = {**{k: v for k, v in os.environ.items() if k not in ("SIDENOTE_LANG", "SIDENOTE_CAPTURE_RUN")},
       "SIDENOTE_ANALYZER": "mock", "SIDENOTE_AGENT": "mock", "SIDENOTE_TRANSCRIBER": "null", "SIDENOTE_RUNNER_URL": "",
       "SIDENOTE_LOG_DIR": LOGS, "SIDENOTE_SEARCH_URL": "", "SIDENOTE_LOCAL_PULL": "0", "SIDENOTE_UPDATE_CHECK": "0",
       "SIDENOTE_PORT": str(PORT), "SIDENOTE_STALL_WARN_SEC": "0", "SIDENOTE_STALL_EXIT_SEC": "0",
       "PYTHONDONTWRITEBYTECODE": "1"}
WS = f"ws://127.0.0.1:{PORT}"
# A stand-in for mss, the capture program's screen grabber (its own requirement, which the server's environment here
# lacks), with mss's own shapes: monitors (0 is all of them), and a grab with its size and BGRA bytes. One plain
# 640x480 screen: what is checked is how the programs meet the server, not the grabbing.
MSS_STAND_IN = '''class MSS:
    monitors = [{"left": 0, "top": 0, "width": 640, "height": 480}, {"left": 0, "top": 0, "width": 640, "height": 480}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, monitor):
        class Shot:
            size = (monitor["width"], monitor["height"])
            bgra = bytes((60, 60, 60, 255)) * (monitor["width"] * monitor["height"])
        return Shot()


mss = MSS
'''


def entry_args() -> list:
    """uvicorn's arguments as docker/entrypoint.sh gives them (its `set -- uvicorn ...` line), for this PC and this port:
    the server here runs as the container's does, with its caps."""
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8").replace("\\\n", " ")
    line = next(x for x in text.splitlines() if x.startswith("set -- uvicorn "))
    line = line.replace('"${SIDENOTE_HOST:-0.0.0.0}"', "127.0.0.1").replace('"${SIDENOTE_PORT:-8777}"', str(PORT))
    return shlex.split(line)[3:]   # after "set -- uvicorn"


ENTRY = entry_args()
LIMIT = int(ENTRY[ENTRY.index("--limit-concurrency") + 1])   # the container's cap on connections


def status() -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v1/status", timeout=10) as r:
        return json.loads(r.read())["capture"]


def region():
    """The region drawn in the panel, as the settings hold it."""
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v1/settings", timeout=10) as r:
        return json.loads(r.read())["values"].get("roi_box")


def start() -> subprocess.Popen:
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", *ENTRY], cwd=ROOT, env=ENV,
                           stdout=open(os.path.join(LOGS, "uvicorn.out"), "w"), stderr=subprocess.STDOUT)
    for _ in range(150):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    break
        except OSError:
            pass
        time.sleep(0.2)
    return srv


def listen(ws, into: list) -> None:
    """Every message a panel is sent, kept, until its socket closes."""
    def go():
        try:
            while True:
                into.append(json.loads(ws.recv()))
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def capture(name: str, run: str, **caps):
    """A capture program's connection as client/capture.py opens one: its hello first, then the panel's switches back."""
    ws = websocket.create_connection(f"{WS}/ingest", timeout=15)
    ws.send(json.dumps({"type": "hello", "info": name, "run": run, "screen": True, **caps}))
    return ws, json.loads(ws.recv())


def next_frame(ws, limit: float):
    """What the server sends this connection next: ("text", message), ("close", code), ("gone", None) for a connection
    ended with no close, or ("none", None) when nothing came in `limit` seconds."""
    ws.settimeout(limit)
    try:
        while True:
            op, frame = ws.recv_data_frame(True)
            if op == ABNF.OPCODE_TEXT:
                return "text", json.loads(frame.data)
            if op == ABNF.OPCODE_CLOSE:
                return "close", int.from_bytes(frame.data[:2], "big") if len(frame.data) >= 2 else None
            # a ping: read on
    except websocket.WebSocketTimeoutException:
        return "none", None
    except (websocket.WebSocketConnectionClosedException, OSError):
        return "gone", None


def close_code(ws, limit: float):
    """The code the server closes this socket with, reading past what it sends first; None when it is not closed."""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        kind, value = next_frame(ws, max(0.1, end - time.monotonic()))
        if kind == "close":
            return value
        if kind in ("gone", "none"):
            return None if kind == "none" else "gone"
    return None


def health() -> int:
    """/health's status, 503 among them."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def notices(said: list) -> list:
    return [m.get("text") for m in said if m.get("type") == "notice"]


def xvfb():
    """A private Xvfb display (never the user's screen), its number and its process; None where there is no Xvfb or no
    libX11 (as tests/capture_skip.py starts one)."""
    if not shutil.which("Xvfb") or not ctypes.util.find_library("X11"):
        return None
    read, write = os.pipe()
    proc = subprocess.Popen(["Xvfb", "-displayfd", str(write), "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                            pass_fds=(write,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write)
    try:
        number = os.read(read, 16).decode().strip()   # the display Xvfb found free, said once it is up
    finally:
        os.close(read)
    if not number:
        proc.kill()
        proc.wait()
        return None
    return number, proc


def wait_for(what, limit: float = 5.0) -> bool:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if what():
            return True
        time.sleep(0.05)
    return what()


srv = start()
opened = []
try:
    print("\n[a second capture program]")
    panel = websocket.create_connection(f"{WS}/panel", timeout=10)
    opened.append(panel)
    said = []
    listen(panel, said)
    first, told = capture("capture/first", "a" * 16, code="aaaa", skipping=True)
    check("(the first capture program is told the panel's switches)", told.get("type") == "control", told)
    # the newer one's name with a terminal's codes in it: an OSC that sets a window's title, and a bell
    second, told = capture("capture/second\x1b]0;title\x07", "b" * 16, code="bbbb")
    check("(the second is told them too)", told.get("type") == "control", told)
    kind, quit_msg = next_frame(first, 5)
    check("the first is asked to quit, as ./sidenote capture-stop asks, with its reason and the newer one's name",
          kind == "text" and quit_msg.get("type") == "quit" and quit_msg.get("reason") == "taken_over"
          and quit_msg.get("by", "").startswith("capture/second"), (kind, quit_msg))
    check("...the name without the terminal's codes", kind == "text" and not any(c in quit_msg.get("by", "") for c in "\x1b\x07"),
          repr(quit_msg))
    # what a capture program still sends while it ends: its card, and a switch from its tray
    first.send(json.dumps({"type": "caps", "code": "zzzz", "skipping": True}))
    first.send(json.dumps({"type": "capture_set", "audio": False}))
    time.sleep(0.5)
    card = status()
    check("the server counts one capture program, the newer", card["clients"] == 1 and card["info"].startswith("capture/second"), card)
    check("its card says what the newer one can do, not a mix of the two", card["caps"].get("code") == "bbbb" and "skipping" not in card["caps"],
          card["caps"])
    check("what the one before sends as it ends is not taken (its card, its tray's switch)",
          card["audio_on"] is True and card["caps"].get("code") == "bbbb", card)
    check("the panels are told the newer one feeds the server now",
          any("Another capture program connected" in str(n) for n in notices(said)), notices(said))
    first.close()   # it ends itself, as a capture program asked to quit does
    time.sleep(0.5)
    check("the one before ending itself leaves the count at one", status()["clients"] == 1, status())

    print("\n[one that does not end itself]")
    began = time.monotonic()
    third, _ = capture("capture/third", "c" * 16)
    kind, msg = next_frame(second, 5)
    check("(the second is asked to quit)", kind == "text" and msg.get("type") == "quit", (kind, msg))
    kind, code = next_frame(second, 16)   # it reads on, and ends nothing
    waited = time.monotonic() - began
    check("it is closed when 10 s have passed, and not before", kind == "close" and 9.0 <= waited <= 14.0,
          f"{kind} {code} after {waited:.1f} s")
    card = status()
    check("the server counts one, the newest", card["clients"] == 1 and card["info"] == "capture/third", card)

    print("\n[a program's own earlier connection]")
    before = len(notices(said))
    again, told = capture("capture/third", "c" * 16)   # the same run: the program back from a sleep
    check("(the program's new connection is told the switches)", told.get("type") == "control", told)
    kind, code = next_frame(third, 5)
    check("its earlier connection is closed at once, with no quit", kind == "close", (kind, code))
    time.sleep(0.5)
    check("...no word to the panels", len(notices(said)) == before, notices(said)[before:])
    check("...and the server counts one", status()["clients"] == 1, status())

    print("\n[what takes nothing over]")
    once, told = capture("capture/once", "f" * 16, code="ffff", once=True)   # ./sidenote capture --once
    check("(a --once run is told the switches)", told.get("type") == "control", told)
    check("a --once run beside the program that runs asks nothing of it", next_frame(again, 2)[0] == "none")
    card = status()
    check("...leaves the card to it", card["info"] == "capture/third" and card["caps"].get("code") != "ffff", card)
    once.close()
    check("...and when it ends, the program that runs is counted alone", wait_for(lambda: status()["clients"] == 1), status())
    silent = websocket.create_connection(f"{WS}/ingest", timeout=15)   # a socket opened by hand, a probe: no hello
    check("a connection that never says hello takes nothing over", next_frame(again, 4.5)[0] == "none")
    silent.close()
    late = websocket.create_connection(f"{WS}/ingest", timeout=15)     # says hello late, after a newer one
    newest, _ = capture("capture/newest", "9" * 16)
    check("(the one before both is asked to quit)", next_frame(again, 5)[0] == "text")
    check("(and the late one, taken over before its hello)", next_frame(late, 5)[0] == "text")
    late.send(json.dumps({"type": "hello", "info": "capture/late", "run": "8" * 16, "screen": True}))
    check("one taken over before its late hello came takes nothing back", next_frame(newest, 4)[0] == "none")
    card = status()
    check("...the newest feeds the server, counted alone", card["clients"] == 1 and card["info"] == "capture/newest", card)
    again.close()
    late.close()

    print("\n[client/capture.py's own Sender]")
    spec = importlib.util.spec_from_file_location("capture_many", ROOT / "client" / "capture.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    check("its run is 16 hex digits, and the environment keeps it for a restart of its own",
          len(cap.RUN) == 16 and all(c in "0123456789abcdef" for c in cap.RUN) and os.environ.get("SIDENOTE_CAPTURE_RUN") == cap.RUN,
          cap.RUN)
    cap.RUN = "1" * 16
    a = cap.Sender(f"{WS}/ingest")
    a.keepalive()              # connects, as a capture program does at its start
    check("(the Sender connects)", wait_for(lambda: a.connected))
    check("(the connection before it is asked to quit)", next_frame(newest, 5)[0] == "text")
    newest.close()
    cap.RUN = "2" * 16         # another capture program
    b = cap.Sender(f"{WS}/ingest")
    b.keepalive()
    check("the Sender reads the quit", wait_for(lambda: a.quit_asked), a.__dict__.get("quit_asked"))
    a._on_message(json.dumps({"type": "restart"}))   # a restart sent before the quit, come after it
    check("...and takes no restart after it: a copy of it would take the server back", a.taken_over and not a.restart_asked,
          (a.taken_over, a.restart_asked))
    cap.RUN = "1" * 16         # what the first would say again, connecting: its own run
    a._ws.sock.shutdown(socket.SHUT_RDWR)   # its connection gone (the server's close, or the network)
    check("(its connection is gone)", wait_for(lambda: not a.connected))
    a.send({"type": "audio", "sr": 16000, "data": ""})   # sound still to send, as the program ends
    time.sleep(2.1)                                      # keepalive tries again 2 s after its last try
    a.keepalive()
    time.sleep(0.5)
    check("once asked to quit it never connects again: the newer one goes on",
          not a.connected and b.connected and not b.quit_asked and status()["clients"] == 1,
          (a.connected, b.connected, b.quit_asked, status()))
    for sender in (a, b):
        if sender._ws is not None:
            sender._ws.close()

    print("\n[the capture program itself, on a private X display]")
    up = xvfb()
    if up is None:
        print("  (not tried: no Xvfb or no libX11 here)")
    else:
        number, xproc = up
        prog = None   # the capture program, ended below however this section ends
        try:
            check("(no capture program is connected)", wait_for(lambda: status()["clients"] == 0), status())
            run_dir = tempfile.mkdtemp(prefix="sidenote-clients-run-")   # its guard's file, away from the user's
            stand_in = Path(run_dir) / "stand-in"
            stand_in.mkdir()
            (stand_in / "mss.py").write_text(MSS_STAND_IN, encoding="utf-8")
            env = {**{k: v for k, v in os.environ.items() if k != "SIDENOTE_CAPTURE_RUN"}, "DISPLAY": f":{number}",
                   "XDG_RUNTIME_DIR": run_dir, "SIDENOTE_LANG": "en", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(stand_in)}
            prog = subprocess.Popen([sys.executable, "-u", str(ROOT / "client" / "capture.py"), "--server", f"{WS}/ingest",
                                     "--no-audio", "--no-tray", "--no-auto-update"], env=env, cwd=run_dir,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            check("(the capture program connects)", wait_for(lambda: status()["clients"] == 1, 60), status())
            panel.send(json.dumps({"type": "setting", "key": "roi_box", "value": [0.1, 0.1, 0.5, 0.5]}))   # a region drawn
            check("(a region is drawn in the panel)", wait_for(lambda: region() == [0.1, 0.1, 0.5, 0.5]), region())
            once_run = subprocess.run([sys.executable, "-u", str(ROOT / "client" / "capture.py"), "--server", f"{WS}/ingest",
                                       "--once", "--no-tray", "--no-auto-update"], env=env, cwd=run_dir,
                                      capture_output=True, text=True, timeout=90)
            time.sleep(1.0)
            check("a --once run beside it sends its screen and ends (0), and the program that runs goes on",
                  once_run.returncode == 0 and prog.poll() is None and status()["clients"] == 1,
                  f"--once exit {once_run.returncode}, program {prog.poll()}: {once_run.stdout[-400:]}")
            check("...and the region drawn in the panel stays", region() == [0.1, 0.1, 0.5, 0.5], region())
            newer, _ = capture("capture/newer", "e" * 16)
            try:
                rc = prog.wait(30)
            except subprocess.TimeoutExpired:
                prog.kill()
                rc = None
            out = prog.stdout.read()
            check("taken over, it ends itself with its own exit code (77), on which the desktop app starts its own again",
                  rc == 77, f"exit {rc}: {out[-800:]}")
            check("...and says why", "Another capture program now feeds this server (capture/newer): this one stops" in out,
                  out[-800:])
            time.sleep(0.5)
            card = status()
            check("...and the newer one feeds the server alone", card["clients"] == 1 and card["info"] == "capture/newer", card)
            newer.close()
        finally:
            if prog is not None and prog.poll() is None:   # a check that raised before it ended: not left running
                prog.kill()
                prog.wait(10)
            xproc.kill()
            xproc.wait(10)

    print("\n[panels]")
    start, got, lock = threading.Barrier(40), [], threading.Lock()

    def open_panel():
        """One of 40 handshakes let go together: its socket, or the status it was refused with."""
        start.wait()
        try:
            one = websocket.create_connection(f"{WS}/panel", timeout=30)
        except websocket.WebSocketBadStatusException as exc:
            one = getattr(exc, "status_code", None)
        except Exception as exc:
            one = repr(exc)
        with lock:
            got.append(one)

    threads = [threading.Thread(target=open_panel) for _ in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    socks = [g for g in got if isinstance(g, websocket.WebSocket)]
    opened.extend(socks)
    check("40 panels opening at once beside the one open: 31 get in, 32 with it (MAX_PANELS)", len(socks) == 31,
          [g for g in got if not isinstance(g, websocket.WebSocket)])
    check("...and the other 9 are refused at their handshake (403)", [g for g in got if not isinstance(g, websocket.WebSocket)] == [403] * 9,
          [g for g in got if not isinstance(g, websocket.WebSocket)])
    opened.pop().close()
    time.sleep(0.5)
    try:
        opened.append(websocket.create_connection(f"{WS}/panel", timeout=10))
        again_ok = True
    except Exception as exc:
        again_ok = repr(exc)
    check("one closing lets a next one in", again_ok is True, again_ok)

    print("\n[the server's own caps, as the container starts it]")
    for ws in opened[1:]:   # the panels above, closed: the one listening stays
        ws.close()
    del opened[1:]
    time.sleep(0.5)
    caps = []
    try:
        for _ in range(8):                               # MAX_INGEST: no hello, so none takes anything over
            caps.append(websocket.create_connection(f"{WS}/ingest", timeout=15))
    except Exception as exc:                             # one refused early is the failure below, not a traceback
        print(f"  (only {len(caps)} capture connections opened: {exc!r})")
    check("(8 capture connections open)", len(caps) == 8, len(caps))
    try:
        extra = websocket.create_connection(f"{WS}/ingest", timeout=15)
        ninth = "taken"
        extra.close()
    except websocket.WebSocketBadStatusException as exc:
        ninth = getattr(exc, "status_code", None)
    check("8 capture connections at once, the 9th refused at its handshake (403)", ninth == 403, ninth)
    if caps:
        caps.pop().close()

    def next_one():
        """A capture connection opened once a place is free, or what refused it."""
        try:
            caps.append(websocket.create_connection(f"{WS}/ingest", timeout=15))
            return True
        except Exception as exc:
            return repr(exc)
    check("...one closing lets a next one in", wait_for(lambda: next_one() is True, 5), "refused")
    for c in caps:
        c.close()
    big = websocket.create_connection(f"{WS}/panel", timeout=15)
    big.send(json.dumps({"type": "ask", "text": "x" * (2 * 1024 * 1024)}))   # past MAX_BODY: no panel sends this much
    code = close_code(big, 15)
    check("a panel's message over 2 MB is closed with 1009, never parsed", code == 1009, code)
    check("...and the server goes on", health() == 200)
    held = []
    try:
        for _ in range(LIMIT):                           # a program that opens connections and sends nothing on them
            held.append(socket.create_connection(("127.0.0.1", PORT), timeout=10))
    except OSError as exc:                               # out of file descriptors here: the checks below say so
        print(f"  (only {len(held)} connections opened: {exc!r})")
    check(f"({LIMIT} connections held open)", len(held) == LIMIT, len(held))
    time.sleep(0.5)
    refused = [health() for _ in range(5)]
    check(f"{LIMIT} connections held open by a program: the next requests are answered 503 at once", refused == [503] * 5,
          refused)
    for h in held:
        h.close()
    check("...and once they close, the server answers again", wait_for(lambda: health() == 200, 10), health())
    out = Path(LOGS, "uvicorn.out").read_text(encoding="utf-8", errors="replace")
    check("...uvicorn's warning for those refusals written once, not once each", out.count("Exceeded concurrency limit.") == 1,
          out.count("Exceeded concurrency limit."))
    desktop = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    check("the desktop app's server starts with the container's cap on connections",
          re.search(r"limit_concurrency=(\d+)", desktop) is not None
          and int(re.search(r"limit_concurrency=(\d+)", desktop).group(1)) == LIMIT, LIMIT)
finally:
    for ws in opened:
        try:
            ws.close()
        except Exception:
            pass
    srv.terminate()
    try:
        srv.wait(15)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
