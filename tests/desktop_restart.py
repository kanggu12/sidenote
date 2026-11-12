"""The desktop app's watch over its children (desktop/app.py) counts only the ends nobody asked for: a capture program
restarted from its tray (or after a deploy) ends with CAPTURE_RESTART, and five of those within ten minutes ended the
whole app with "The capture program keeps stopping", the server and Ollama with it.

    .venv/bin/python tests/desktop_restart.py [path to the checkout]

Real child processes, each a short Python program standing in for the server or the capture program: no server, no
capture, no window. The watch's one-second pauses are skipped. Every process started here is ended here, by the
handle the app keeps of it.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop import app  # noqa: E402

PASS, FAIL = [], []
WORK = Path(tempfile.mkdtemp(prefix="sidenote-restart-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def capture_child(codes, asked_code):
    """A capture program whose runs end with `codes` in turn (the last one for every run after), counting its runs in
    a file; made as the app makes it, the code of its own restarts given when `asked_code` is."""
    counter = WORK / f"runs-{len(list(WORK.iterdir()))}"
    script = ("import pathlib, sys\n"
              f"p = pathlib.Path({str(counter)!r}); n = int(p.read_text()) if p.exists() else 0; p.write_text(str(n + 1))\n"
              f"codes = {codes!r}; sys.exit(codes[min(n, len(codes) - 1)])\n")
    log = app.CappedLog(WORK / f"capture-{counter.name}.log")
    how = {"asked_code": asked_code} if asked_code is not None else {}
    try:
        child = app.Child("capture", [sys.executable, "-c", script], dict(os.environ), log, **how)
    except TypeError as exc:   # an app before asked_code: the check below fails, and says so
        print(f"  (Child takes no asked_code: {exc})")
        child = app.Child("capture", [sys.executable, "-c", script], dict(os.environ), log)
    return child, counter


def runs(counter):
    return int(counter.read_text()) if counter.exists() else 0


server = app.Child("server", [sys.executable, "-c", "import time; time.sleep(120)"], dict(os.environ),
                   app.CappedLog(WORK / "server.log"))
log = app.CappedLog(WORK / "app.log")
try:
    server.start()
    with mock.patch.object(app.time, "sleep", lambda s: None), mock.patch.object(app, "tell", lambda *a, **k: None), \
            mock.patch.object(app, "say", lambda *a, **k: None):
        # 1. Seven restarts asked for in a row, then a quit: the watch ends well, and none of them counted
        asked, counter = capture_child([app.CAPTURE_RESTART] * 7 + [0], app.CAPTURE_RESTART)
        asked.start()
        code = app.watch(server, asked, None, log)
        check("seven restarts asked for in a row are no reason to give up: the quit after them ends the watch with 0",
              code == 0 and runs(counter) == 8, f"watch {code} after {runs(counter)} runs")
        check("...and only the first start is counted toward giving up", len(asked.starts) == 1, f"{len(asked.starts)} counted")

        # 2. A program that keeps failing is still given up on, after RESTARTS[0] starts
        crash, counter = capture_child([3], app.CAPTURE_RESTART)
        crash.start()
        code = app.watch(server, crash, None, log)
        check(f"a capture program that keeps failing is given up on after {app.RESTARTS[0]} starts",
              code == 1 and runs(counter) == app.RESTARTS[0], f"watch {code} after {runs(counter)} runs")

        # 3. Restarts asked for between failures do not bring the end closer: four of each, then a quit
        mixed, counter = capture_child([app.CAPTURE_RESTART, 3] * 4 + [0], app.CAPTURE_RESTART)
        mixed.start()
        code = app.watch(server, mixed, None, log)
        check("four failures with restarts asked for between them: not given up, the quit ends it with 0",
              code == 0 and runs(counter) == 9, f"watch {code} after {runs(counter)} runs")

    # 4. A capture program another one took over from (CAPTURE_TAKEN_OVER, 77): started again to take the app's server
    # back, where an end with 0 would have ended the app and the server the other one feeds; the quit after it ends it
    said = []
    with mock.patch.object(app.time, "sleep", lambda s: None), mock.patch.object(app, "tell", lambda *a, **k: None), \
            mock.patch.object(app, "say", lambda text, *a, **k: said.append(text)):
        taken, counter = capture_child([app.CAPTURE_TAKEN_OVER, 0], app.CAPTURE_RESTART)
        taken.start()
        code = app.watch(server, taken, None, log)
        check("a capture program another one took over from is started again, and the app goes on until a quit",
              code == 0 and runs(counter) == 2, f"watch {code} after {runs(counter)} runs")
        check("...and the log says why", any("gave way to another capture program" in s for s in said), said)
finally:
    for child in (server,):
        if child.proc is not None and child.proc.poll() is None:   # the one long-lived process started here
            child.proc.kill()
            child.proc.wait(10)

print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
