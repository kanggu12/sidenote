"""A panel that stops reading: the server's broadcasts, the API writes that send one and the other panels go on, the
silent one is dropped, and the server ends on SIGTERM within its shutdown wait with what it keeps at its end.

    .venv/bin/python tests/stalled_panel.py

A real server on a free port (mock engines, a log folder of its own) and two raw WebSocket clients on /panel: one reads
everything, the other completes the handshake with a small receive buffer and never reads again, as a frozen tab or a
socket half gone does. Writes through the API that resend the settings sheet to every panel (PUT /language/panel) are
timed. Before the fix one such socket held every broadcast for good (server/app.py, PanelOut), and SIGTERM never ended
the server: uvicorn waited on that connection unless told how long to wait (--timeout-graceful-shutdown, which
docker/entrypoint.sh and desktop/app.py pass).
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

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
LOGS = tempfile.mkdtemp(prefix="sidenote-stalled-")
# Without SIDENOTE_LANG (tests/run.sh sets it for the other suites): set, it fixes the panel's language, and the writes
# timed here (the panel's language) would be refused and send nothing to the panels
ENV = {**{k: v for k, v in os.environ.items() if k != "SIDENOTE_LANG"}, "SIDENOTE_ANALYZER": "mock", "SIDENOTE_AGENT": "mock", "SIDENOTE_TRANSCRIBER": "null", "SIDENOTE_RUNNER_URL": "",
       "SIDENOTE_LOG_DIR": LOGS, "SIDENOTE_SEARCH_URL": "", "SIDENOTE_LOCAL_PULL": "0", "SIDENOTE_UPDATE_CHECK": "0",
       "SIDENOTE_PORT": str(PORT), "SIDENOTE_STALL_WARN_SEC": "0", "SIDENOTE_STALL_EXIT_SEC": "0", "PYTHONDONTWRITEBYTECODE": "1"}
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, timeout=30.0):
    """One API request: (status or the error's name, seconds it took, the JSON answer or None)."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, time.time() - t0, json.loads(r.read() or b"null")
    except Exception as exc:
        return type(exc).__name__, time.time() - t0, None


def handshake(sock) -> str:
    """The WebSocket handshake on /panel by hand: what the server answered on its first line."""
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET /panel HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1)
    return head.split(b"\r\n", 1)[0].decode()


def start() -> subprocess.Popen:
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(PORT),
                            "--no-access-log", "--timeout-graceful-shutdown", "5"], cwd=ROOT, env=ENV,
                           stdout=open(os.path.join(LOGS, "uvicorn.out"), "w"), stderr=subprocess.STDOUT)
    for _ in range(150):
        if call("GET", "/health", timeout=2)[0] == 200:
            break
        time.sleep(0.2)
    return srv


srv = start()
reader = stalled = None
try:
    print("\n[a panel that stops reading]")
    reader = socket.create_connection(("127.0.0.1", PORT))
    check("(a reading panel connects)", handshake(reader).endswith("101 Switching Protocols"))
    got = [0]

    def read_all():
        try:
            while True:
                chunk = reader.recv(65536)
                if not chunk:
                    return
                got[0] += len(chunk)
        except OSError:
            pass
    threading.Thread(target=read_all, daemon=True).start()
    stalled = socket.socket()
    stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)   # its buffer fills after a few messages
    stalled.connect(("127.0.0.1", PORT))
    check("(and one that will never read)", handshake(stalled).endswith("101 Switching Protocols"))
    time.sleep(0.5)
    took = []
    for i in range(60):
        status, sec, _ = call("PUT", "/api/v1/language/panel", {"lang": "ko" if i % 2 else "en"})
        took.append((sec, status))
        if sec > 10:   # held by the silent socket (before the fix, for good): the rest would each wait out the request too
            break
    slow = [i for i, (sec, _) in enumerate(took) if sec > 1.0]
    check("every write goes through, each sending the settings sheet to every panel", all(s == 200 for _, s in took),
          [s for _, s in took if s != 200][:3])
    check("...and none of them waits on the silent panel", not slow, [(i, round(took[i][0], 1)) for i in slow])
    before = got[0]
    call("PUT", "/api/v1/language/panel", {"lang": "en"})
    time.sleep(0.5)
    check("the reading panel still gets every broadcast", got[0] > before and got[0] > 256 * 1024, f"{before} -> {got[0]} bytes")
    # Its writer waits on the message it could not send for 5 s (PanelOut.WRITE_SEC), and then closes it
    deadline, panels = time.time() + 9, None
    while time.time() < deadline:
        panels = (call("GET", "/stats")[2] or {}).get("panels")
        if panels == 1:
            break
        time.sleep(0.25)
    check("the silent one is closed within its time, and is no longer a panel the server sends to", panels == 1, panels)
    _, sec, _ = call("POST", "/api/v1/reanalyze", {})
    check("an analysis asked for now starts at once", sec < 1.0, f"{sec:.2f}s")
    print("\n[the server's end]")
    t0 = time.time()
    srv.terminate()
    try:
        srv.wait(15)
        ended = time.time() - t0
    except subprocess.TimeoutExpired:
        srv.kill()
        srv.wait(5)
        ended = None
    check("SIGTERM ends it within its shutdown wait, the silent socket open all the while", ended is not None and ended < 10,
          "killed after 15 s" if ended is None else f"{ended:.1f}s")
    events = Path(LOGS, "events.jsonl").read_text(encoding="utf-8") if Path(LOGS, "events.jsonl").exists() else ""
    said, kept = '"server_stop"' in events, Path(LOGS, ".restart.npz").exists()
    check("...having said it stopped, and kept what a restart takes up", said and kept, f"server_stop {said}, .restart.npz {kept}")
    print("\n[what starts the server waits that long, and no longer]")
    entry = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    desk = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    check("the container's server is started with a shutdown wait", "--timeout-graceful-shutdown" in entry)
    check("and so is the desktop app's", "timeout_graceful_shutdown" in desk)
finally:
    for s in (reader, stalled):
        if s is not None:
            s.close()
    if srv.poll() is None:
        srv.kill()
        srv.wait(5)

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
