"""Sidenote on one PC without Docker (desktop/app.py): the server's environment on the host, the data folder on each
system, the capped log files, the port check, the watch that starts a stopped child again and stops when the capture
program is quit, the `python -c` the Windows app stands in for, and the whole start and stop on a spare port with
stand-in models.

    .venv/bin/python tests/desktop_check.py
"""
import http.server
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


from desktop import app  # noqa: E402

print("[the server's environment on the host]")
env = app.server_env({"PATH": "/bin"}, Path("/data/sn"), 8800)
check("the model is this PC's Ollama, which the panel may pull into; search and code runs are off; loopback only",
      env["SIDENOTE_LOCAL_URL"] == "http://127.0.0.1:11434/v1" and env["SIDENOTE_LOCAL_PULL"] == "1"
      and env["SIDENOTE_DESKTOP"] == "1"
      and env["SIDENOTE_SEARCH_URL"] == ""
      and env["SIDENOTE_RUNNER_URL"] == "" and env["SIDENOTE_TRUST_GATEWAY"] == "0", env)
check("the logs and the speech model go in the data folder, and the port is the one asked for",
      env["SIDENOTE_LOG_DIR"] == str(Path("/data/sn/logs")) and env["HF_HOME"] == str(Path("/data/sn/hf"))
      and env["SIDENOTE_PORT"] == "8800" and env["PATH"] == "/bin", env)
mine = app.server_env({"SIDENOTE_LOCAL_URL": "http://10.0.0.5:8000/v1", "SIDENOTE_SEARCH_URL": "http://searx/search"},
                      Path("/d"), 8777)
check("a setting already in the environment wins over the default",
      mine["SIDENOTE_LOCAL_URL"] == "http://10.0.0.5:8000/v1" and mine["SIDENOTE_SEARCH_URL"] == "http://searx/search")
with tempfile.TemporaryDirectory() as bins:
    def tool(name):
        f = Path(bins) / (name + (".exe" if sys.platform == "win32" else ""))
        f.write_text("")
        f.chmod(0o755)
    check("no agent CLI on the PATH: the agent is left to the server's default",
          "SIDENOTE_AGENT" not in app.server_env({"PATH": bins}, Path("/d"), 1))
    tool("codex")
    check("Codex alone: the agent is Codex", app.server_env({"PATH": bins}, Path("/d"), 1).get("SIDENOTE_AGENT") == "codex")
    tool("claude")
    check("Claude Code and Codex both: Claude Code", app.server_env({"PATH": bins}, Path("/d"), 1).get("SIDENOTE_AGENT")
          == "claude-code")
    check("...and SIDENOTE_AGENT, when set, wins", app.server_env({"PATH": bins, "SIDENOTE_AGENT": "off"}, Path("/d"), 1)
          ["SIDENOTE_AGENT"] == "off")
check("the speech decoder's threads follow SIDENOTE_WHISPER_THREADS",
      app.server_env({"SIDENOTE_WHISPER_THREADS": "2"}, Path("/d"), 1)["OMP_NUM_THREADS"] == "2")

from types import SimpleNamespace  # noqa: E402
from server import agents  # noqa: E402
hints = [agents.login_hint(SimpleNamespace(agent=a, desktop=d)) for a, d in
         (("claude-code", True), ("codex", True), ("claude-code", False))]
check("the panel's sign-in direction is the CLI's own in the app, the launcher's otherwise",
      hints == ["claude", "codex login", "./sidenote login"], hints)

with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"LANG": "ko_KR.UTF-8"}, clear=True):
    ko = app.t("The Sidenote server did not start. The end of its log:")
with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"LANG": "ko_KR.UTF-8", "SIDENOTE_LANG": "en"},
                                                                   clear=True):
    en = app.t("The Sidenote server did not start. The end of its log:")
check("the app's message boxes follow the system's language, and SIDENOTE_LANG wins", ko.startswith("Sidenote 서버를")
      and en.startswith("The Sidenote server"), (ko, en))
check("every message box the app can show has its Korean", all(
    app.KO.get(m) for m in ("Another program is using the port Sidenote needs ({port}). Close that program, then start "
                            "Sidenote again.", "Sidenote's server keeps stopping. The end of its log:",
                            "Ollama keeps stopping. The end of its log:",
                            "The capture program keeps stopping. The end of its log:")))

print("[the data folder on each system]")
# the home folder as the patched environment gives it, so the expectation is worked out the same way on every system
for platform, environ, want in (
        ("win32", {"LOCALAPPDATA": r"C:\Users\a\AppData\Local"}, lambda: Path(r"C:\Users\a\AppData\Local") / "Sidenote"),
        ("linux", {"XDG_DATA_HOME": "/home/a/.data"}, lambda: Path("/home/a/.data") / "sidenote"),
        # Path.home() reads HOME, or USERPROFILE on Windows (where this runs in CI too)
        ("linux", {"HOME": "/home/a", "USERPROFILE": "/home/a"}, lambda: Path.home() / ".local" / "share" / "sidenote"),
        ("darwin", {"HOME": "/Users/a", "USERPROFILE": "/Users/a"},
         lambda: Path.home() / "Library" / "Application Support" / "Sidenote"),
        ("linux", {"SIDENOTE_DATA_DIR": "/srv/sidenote"}, lambda: Path("/srv/sidenote"))):
    with mock.patch.object(sys, "platform", platform), mock.patch.dict(os.environ, environ, clear=True):
        got, expected = app.data_dir(), want()
    check(f"{platform} with {sorted(environ)}: {expected}", got == expected, got)

print("[the capped log files]")
with tempfile.TemporaryDirectory() as d:
    log = app.CappedLog(Path(d) / "x.log", cap=100)
    for i in range(30):
        log.write(f"line {i:02d}\n".encode())
    log.close()
    files = sorted(p.name for p in Path(d).iterdir())
    total = sum(p.stat().st_size for p in Path(d).iterdir())
    check("a full file becomes .1 and a new one starts: two files at most", files == ["x.log", "x.log.1"], files)
    check("...so what is kept stays within twice the cap", total <= 2 * 100 + 8, total)
    check("...and the newest line is in the live file",
          (Path(d) / "x.log").read_text().rstrip().endswith("line 29"), (Path(d) / "x.log").read_text())

print("[the port check]")
import socket  # noqa: E402
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    s.listen()
    busy = s.getsockname()[1]
    check("a port something listens on is not free", not app.port_free(busy))
free = app.free_port()
check("a port nothing listens on is free", app.port_free(free))

print("[the watch over the children]")


class Fake:
    """A child whose exit codes come from a list: None while it runs."""

    def __init__(self, name, codes):
        self.name, self.codes, self.started = name, list(codes), []
        self.log = mock.Mock(path=Path("/nonexistent"))
        self.ended = None

    def exited(self):
        if self.ended is None and self.codes:
            self.ended = self.codes.pop(0)
        return self.ended

    def start(self, *extra):
        self.started.append(extra)
        self.ended = None

    def given_up(self):
        return len(self.started) >= 3


log = mock.Mock()
with mock.patch.object(app.time, "sleep", lambda s: None), mock.patch.object(app, "tell", lambda *a, **k: None), \
        mock.patch.object(app, "say", lambda *a, **k: None):
    server, cap = Fake("server", [None, -9, None, None]), Fake("capture", [None, None, app.CAPTURE_RESTART, None, 0])
    code = app.watch(server, cap, None, log)
    check("a server that stops is started again", server.started == [()], server.started)
    check("a capture program that asks for a restart is started again, as resumed", cap.started == [("--resumed",)],
          cap.started)
    check("...and quitting it ends the watch with 0", code == 0, code)
    server, cap = Fake("server", [1, 1, 1, 1, 1]), Fake("capture", [None] * 9)
    check("a server that keeps stopping is given up on, with 1", app.watch(server, cap, None, log) == 1)
    server = Fake("server", [None, None, None])
    crash = Fake("capture", [None, 3, None, 3, None, 3, None, 3])
    check("so is a capture program that keeps failing", app.watch(server, crash, None, log) == 1)

print("[the capture program's side of it]")
sys.path.insert(0, str(ROOT / "client"))
import capture  # noqa: E402
check("the capture program asks for a restart with the exit code this program waits for",
      capture.SUPERVISED_RESTART == app.CAPTURE_RESTART, (capture.SUPERVISED_RESTART, app.CAPTURE_RESTART))
for platform, environ, runs in (("win32", {}, True), ("linux", {"DISPLAY": ":0"}, True),
                                ("linux", {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}, True),
                                ("linux", {}, False), ("darwin", {}, True)):
    with mock.patch.object(sys, "platform", platform), mock.patch.dict(os.environ, environ, clear=True):
        ok_here, note = app.capture_supported()
    check(f"capture on {platform} with {sorted(environ)}: {'started' if runs else 'not started, and why'}",
          ok_here == runs and (runs or bool(note)) and (("WAYLAND_DISPLAY" in environ) == ("Wayland" in note)),
          (ok_here, note))

with mock.patch.object(sys, "platform", "darwin"):
    check("on macOS the app says where Screen Recording is allowed and what plays the speaker sound to it",
          all(w in app.capture_supported()[1] for w in ("Screen Recording", "BlackHole")), app.capture_supported())

print("[the PATH of an app opened from the Finder or a desktop's menu]")
with tempfile.TemporaryDirectory() as d:
    home, shell_dir = Path(d) / "home", Path(d) / "from-the-shell"
    (home / ".local" / "bin").mkdir(parents=True)
    shell_dir.mkdir()
    short = os.pathsep.join(["/usr/bin", "/bin"])
    not_a_tty = io.StringIO()
    with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(app, "FROZEN", True), \
            mock.patch.object(sys, "stdin", not_a_tty), mock.patch.object(app, "login_path", return_value=str(shell_dir)):
        got = app.server_env({"PATH": short, "HOME": str(home)}, Path("/d"), 1)["PATH"].split(os.pathsep)
        again = app.widen_path({"PATH": os.pathsep.join(got), "HOME": str(home)}).split(os.pathsep)
    check("the login shell's folders and the agents' installers' come after the short PATH, those that exist",
          got[:2] == ["/usr/bin", "/bin"] and str(shell_dir) in got and str(home / ".local" / "bin") in got
          and str(home / ".npm-global" / "bin") not in got, got)
    check("...without adding a folder twice", again == got, again)
    tty = mock.Mock()
    tty.isatty.return_value = True
    with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(sys, "stdin", tty), \
            mock.patch.object(app, "login_path", side_effect=AssertionError("asked")):
        app.widen_path({"PATH": short, "HOME": str(home)})
    check("...and in a terminal the shell is not asked: the PATH is its already", True)
    with mock.patch.object(sys, "platform", "win32"):
        check("...and on Windows a double-click has the whole PATH, left as it is",
              app.widen_path({"PATH": short, "HOME": str(home)}) == short)
    check("run from a checkout, the server's PATH is the one given",
          app.server_env({"PATH": short, "HOME": str(home)}, Path("/d"), 1)["PATH"] == short)
    if os.name != "nt":
        talky = Path(d) / "talky-shell"
        talky.write_text('#!/bin/sh\necho "welcome back"\nPATH=/from/rc:$PATH\neval "$2"\n')
        talky.chmod(0o755)
        check("the login shell's PATH is read past what its start-up files print",
              app.login_path({"SHELL": str(talky), "PATH": "/usr/bin:/bin", "HOME": str(home)}) == "/from/rc:/usr/bin:/bin",
              app.login_path({"SHELL": str(talky), "PATH": "/usr/bin:/bin", "HOME": str(home)}))
        slow = Path(d) / "slow-shell"
        slow.write_text("#!/bin/sh\nsleep 30\n")
        slow.chmod(0o755)
        t0 = time.time()
        check("...and a shell that never answers costs 5 s at most, and gives nothing",
              app.login_path({"SHELL": str(slow), "PATH": "/usr/bin:/bin", "HOME": str(home)}) == ""
              and time.time() - t0 < 8, round(time.time() - t0, 1))

print("[a child of the app once the app is gone, where no PR_SET_PDEATHSIG ends it (macOS)]")


def alive(pid: int) -> bool:
    """Whether the process runs: one that ended and waits to be reaped (a zombie) does not."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


if os.name != "nt":
    # the app (middle) starts a child that watches for it, says the child's pid, and ends two seconds later
    child_code = ("import os, sys, time; sys.path.insert(0, os.environ['CHECKOUT']); from desktop import app; "
                  "app._end_with_parent(0.2); time.sleep(30)")
    middle_code = ("import os, subprocess, sys, time\n"
                   "child = subprocess.Popen([sys.executable, '-c', os.environ['CHILD_CODE']],\n"
                   "                         env={**os.environ, 'SIDENOTE_APP_PARENT': str(os.getpid())})\n"
                   "print(child.pid, flush=True)\n"
                   "time.sleep(2)\n")
    middle = subprocess.Popen([sys.executable, "-c", middle_code], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, "CHECKOUT": str(ROOT), "CHILD_CODE": child_code})
    pid = int(middle.stdout.readline())
    time.sleep(1.0)
    check("while the app runs its child goes on", alive(pid))
    middle.wait(timeout=10)
    t0 = time.time()
    while alive(pid) and time.time() - t0 < 5:
        time.sleep(0.1)
    check("...and once the app is gone the child ends itself within a second or so", not alive(pid),
          f"still running after {time.time() - t0:.1f} s")
    if alive(pid):
        os.kill(pid, signal.SIGKILL)

print("[Ollama on the widened PATH, and ended with the app where nothing else ends it]")
with tempfile.TemporaryDirectory() as d:
    brew = Path(d) / "opt-homebrew-bin"
    brew.mkdir()
    fake = brew / "ollama"            # as on a Mac: shutil.which adds no .exe once sys.platform says darwin
    fake.write_text("")
    fake.chmod(0o755)
    with mock.patch.object(sys, "platform", "darwin"), mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
        check("the app finds Ollama on the server's PATH, where the Finder's own has no Homebrew",
              app.ollama_binary(str(brew)) == str(fake), app.ollama_binary(str(brew)))

if os.name != "nt":
    # the app (middle) starts a guard over a long sleep, says the sleep's pid once it runs, and ends two seconds later
    guarded_code = ("import os, subprocess, sys, time\n"
                    "sys.path.insert(0, os.environ['CHECKOUT'])\n"
                    "from desktop import app\n"
                    "sys.exit(app.guard([sys.executable, '-c', 'import os, time; print(os.getpid(), flush=True); time.sleep(30)'], every=0.2))\n")
    middle_code = ("import os, subprocess, sys, time\n"
                   "subprocess.Popen([sys.executable, '-c', os.environ['GUARD_CODE']],\n"
                   "                 env={**os.environ, 'SIDENOTE_APP_PARENT': str(os.getpid())})\n"
                   "time.sleep(2)\n")
    middle = subprocess.Popen([sys.executable, "-c", middle_code], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, "CHECKOUT": str(ROOT), "GUARD_CODE": guarded_code})
    guarded = int(middle.stdout.readline())
    time.sleep(1.0)
    check("a program the guard runs goes on while the app runs", alive(guarded))
    middle.wait(timeout=10)
    t0 = time.time()
    while alive(guarded) and time.time() - t0 < 5:
        time.sleep(0.1)
    check("...and ends once the app is gone", not alive(guarded), f"still running after {time.time() - t0:.1f} s")
    if alive(guarded):
        os.kill(guarded, signal.SIGKILL)
    # the app's own stop: SIGTERM to the guard ends the program it runs
    guard = subprocess.Popen([sys.executable, "-c", guarded_code], stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "CHECKOUT": str(ROOT)})
    inner = int(guard.stdout.readline())
    guard.terminate()
    guard.wait(timeout=10)
    t0 = time.time()
    while alive(inner) and time.time() - t0 < 5:
        time.sleep(0.1)
    check("...and with the guard when the app stops it", not alive(inner))
    if alive(inner):
        os.kill(inner, signal.SIGKILL)

print("[the Mac app's language]")
app.mac_language.cache_clear()
listed = mock.Mock(stdout='(\n    "ko-KR",\n    "en-US"\n)\n')
with mock.patch.object(sys, "platform", "darwin"), mock.patch.dict(os.environ, {}, clear=True), \
        mock.patch.object(app.subprocess, "run", return_value=listed):
    check("opened from the Finder, with no locale, it speaks the first of macOS's languages", app.ui_lang() == "ko",
          app.ui_lang())
app.mac_language.cache_clear()
with mock.patch.object(sys, "platform", "darwin"), mock.patch.dict(os.environ, {}, clear=True), \
        mock.patch.object(app.subprocess, "run", side_effect=OSError("no defaults")):
    check("...and English when they cannot be read", app.ui_lang() == "en")
app.mac_language.cache_clear()

print("[python -c, as the Windows app runs it for the tray menu]")
out = io.StringIO()
with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "argv", ["sidenote"]):
    app.python_c("import sys; print(sys.argv[1:], __name__)", ["{\"rows\": []}", "x"])
check("the code runs as __main__ with its arguments in sys.argv", out.getvalue().strip() == "['{\"rows\": []}', 'x'] __main__",
      out.getvalue())
with mock.patch.object(app, "FROZEN", True), mock.patch.object(app, "python_c", lambda code, argv: (code, argv)):
    handed = app.main(["-c", "print(1)", "a"])
check("the built app hands `-c CODE ARGS` to it", handed == ("print(1)", ["a"]), handed)
with mock.patch.object(sys, "stderr", io.StringIO()):
    try:
        app.main(["-c", "print(1)"])
        refused = False
    except SystemExit as exc:
        refused = exc.code == 2
check("...and from a checkout, where python itself runs -c, it is an unknown option", refused)

print("[Ollama is started only when it is meant to be here and is not]")
check("not for the stand-in models", not app.ollama_needed({"SIDENOTE_ANALYZER": "mock",
                                                            "SIDENOTE_LOCAL_URL": "http://127.0.0.1:11434/v1"}))
check("not for a model server somewhere else",
      not app.ollama_needed({"SIDENOTE_LOCAL_URL": "http://10.0.0.5:11434/v1"}))

print("[the whole start and stop, on a spare port with stand-in models]")
if sys.platform == "win32":
    print("  skipped: the start and stop run on Linux and macOS here; CI starts the Windows app with --check")
else:
    port = app.free_port()
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_DATA_DIR=d)
        proc = subprocess.Popen([sys.executable, "-m", "desktop", "--port", str(port), "--no-browser", "--no-capture"],
                                cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app_log_file = Path(d) / "logs" / "app.log"
        seen = lambda: app_log_file.read_text() if app_log_file.is_file() else ""   # noqa: E731
        up = app.wait_for(lambda: app.health(port) is not None, timeout=60)
        check("the server answers on the port", bool(up))
        # the server is killed only after this program has seen it up: a server that dies before that never started
        check("...and the program has seen it up", app.wait_for(lambda: "the server is up" in seen(), timeout=30), seen())
        first = app.health(port) or {}
        check("...as Sidenote, with the stand-in models", first.get("analyzer") == "mock", first)
        servers = subprocess.run(["pgrep", "-f", f"desktop --serve --port {port}"], capture_output=True, text=True).stdout.split()
        check("the server is a child process of its own", len(servers) == 1, servers)
        if servers:
            os.kill(int(servers[0]), signal.SIGKILL)
        time.sleep(2)
        again = app.wait_for(lambda: app.health(port) is not None, timeout=60)
        check("a server that is killed is started again", bool(again))
        # Its stop route takes only the token the app started it with: a page, or anything else on this PC, gets a 403
        refused = []
        for headers in ({}, {"X-Sidenote-Stop": "not-the-token"}):
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(
                    f"http://127.0.0.1:{port}/server/stop", data=b"", method="POST", headers=headers), timeout=5)
                refused.append("accepted")
            except urllib.error.HTTPError as exc:
                refused.append(exc.code)
        check("asked to stop with no token, or the wrong one, the server refuses and runs on",
              refused == [403, 403] and app.health(port) is not None, refused)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
        left = subprocess.run(["pgrep", "-f", f"desktop --serve --port {port}"], capture_output=True, text=True).stdout.split()
        check("SIGTERM stops it and its server: nothing is left running", proc.returncode == 0 and not left,
              f"exit {proc.returncode}, left {left}")
        logs = Path(d) / "logs"
        check("the logs are in the data folder: the server's own, what it printed, and this program's",
              all((logs / n).is_file() for n in ("server.log", "server-console.log", "app.log")),
              sorted(p.name for p in logs.iterdir()) if logs.is_dir() else "no logs folder")
        app_log = (logs / "app.log").read_text() if (logs / "app.log").is_file() else ""
        check("...and app.log says what happened", "the server is up" in app_log and "starting it again" in app_log
              and "stopped" in app_log, app_log)
        # The app asked its server to close down, so the server's own shutdown ran: on Windows it was killed before this
        server_log = (logs / "server.log").read_text() if (logs / "server.log").is_file() else ""
        events = (logs / "events.jsonl").read_text() if (logs / "events.jsonl").is_file() else ""
        check("the server closed down when the app asked, through its own shutdown (server_stop logged)",
              "asked to close down by the app" in server_log and '"server_stop"' in events,
              server_log[-400:] + events[-300:])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(f"http://127.0.0.1:{port}/health", timeout=1)
        check("the port is free again", False)
    except OSError:
        check("the port is free again", True)

def stand_in_server(port: int, clients: int):
    """A Sidenote /health on the port, as another copy's server answers it, with this many capture programs."""
    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "analyzer": "stand-in", "capture": {"clients": clients}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def later(seconds: float, *steps) -> None:
    """Each step run in turn, `seconds` apart, beside what the check does meanwhile."""
    def go():
        for step in steps:
            time.sleep(seconds)
            step()
    threading.Thread(target=go, daemon=True).start()


print("[another copy holding the lock, as every system reads it (other_copy)]")
with tempfile.TemporaryDirectory() as d:
    data, log = Path(d), app.CappedLog(Path(d) / "app.log")
    port = app.free_port()
    url = f"http://127.0.0.1:{port}"
    held = app.only_one(data)
    check("a second hold of the lock is refused while the first is held", held is not None and app.only_one(data) is None)
    # a copy that runs, its capture program connected: the panel is all a start is for
    srv = stand_in_server(port, clients=1)
    t0 = time.monotonic()
    got, _ = app.other_copy(data, port, url, True, log)
    check("beside a copy that runs with its capture program, a start ends at once", got is None
          and time.monotonic() - t0 < 2, f"{got} after {time.monotonic() - t0:.1f} s")
    srv.shutdown()
    srv.server_close()
    # a copy closing down, its server still answering with no capture program, then gone, then the copy ended
    srv = stand_in_server(port, clients=0)
    later(1.0, lambda: (srv.shutdown(), srv.server_close()), held.close)
    got, _ = app.other_copy(data, port, url, True, log)
    check("beside a copy closing down whose server still answers, a start takes the lock once that copy ends",
          got is not None)
    if got is not None:
        got.close()
    # a copy that runs with no capture program at all: its server answering for STAYS_UP seconds says so
    held = app.only_one(data)
    srv = stand_in_server(port, clients=0)
    was, app.STAYS_UP = app.STAYS_UP, 1
    try:
        got, _ = app.other_copy(data, port, url, True, log)
    finally:
        app.STAYS_UP = was
    check("beside a copy that runs with no capture program, a start ends once its server has stayed up", got is None)
    srv.shutdown()
    srv.server_close()
    held.close()
    log.close()

print("[a start while another copy is closing down: the app opened again right after a quit]")
if sys.platform == "win32":
    print("  skipped: it runs on Linux and macOS here, as the whole start and stop above does")
else:
    port = app.free_port()
    with tempfile.TemporaryDirectory() as d:
        # the copy closing down, as one quit a moment ago is: it still holds the lock, and its server is gone
        held = app.only_one(Path(d))
        env = dict(os.environ, SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_DATA_DIR=d)
        proc = subprocess.Popen([sys.executable, "-m", "desktop", "--port", str(port), "--no-browser", "--no-capture"],
                                cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        app_log_file = Path(d) / "logs" / "app.log"
        seen = lambda: app_log_file.read_text() if app_log_file.is_file() else ""   # noqa: E731
        waits = app.wait_for(lambda: "waiting for it" in seen(), timeout=30)
        time.sleep(1.5)
        check("it waits for that copy, with no server of its own yet", waits and proc.poll() is None
              and app.health(port) is None, seen())
        # one more start, stopped while it waits: it ends as a stopped start does, with nothing of its own to stop
        other = subprocess.Popen([sys.executable, "-m", "desktop", "--port", str(port), "--no-browser", "--no-capture"],
                                 cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        app.wait_for(lambda: seen().count("waiting for it") >= 2, timeout=30)
        other.send_signal(signal.SIGTERM)
        try:
            _, err = other.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            other.kill()
            _, err = other.communicate()
        check("...and one stopped while it waits ends with exit 0, not a traceback", other.returncode == 0 and not err,
              f"exit {other.returncode}: {err.decode(errors='replace')[-300:]}")
        held.close()                     # that copy has ended
        check("...and starts in its place once that copy lets go",
              app.wait_for(lambda: app.health(port) is not None, timeout=60), seen())
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
        check("...and stops as any start does", proc.returncode == 0, f"exit {proc.returncode}")

    def started(port: int, d: str):
        return subprocess.Popen([sys.executable, "-m", "desktop", "--port", str(port), "--no-browser", "--no-capture"],
                                cwd=str(ROOT), env=dict(os.environ, SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null",
                                                        SIDENOTE_DATA_DIR=d),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def ended(proc, timeout=30):
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return proc.returncode

    # Opened again within a second or so of a quit: the copy closing down still holds the lock, and its server still
    # answers, with its capture program gone. Then the server goes, and the copy ends.
    port = app.free_port()
    with tempfile.TemporaryDirectory() as d:
        held = app.only_one(Path(d))
        closing = stand_in_server(port, clients=0)
        proc = started(port, d)
        time.sleep(1.5)
        closing.shutdown()
        closing.server_close()
        time.sleep(0.5)
        held.close()
        up = app.wait_for(lambda: (app.health(port) or {}).get("analyzer") == "mock", timeout=60)
        check("opened again while a copy closes down and its server still answers, it starts in that copy's place",
              bool(up), (Path(d) / "logs" / "app.log").read_text() if (Path(d) / "logs" / "app.log").is_file() else "")
        proc.send_signal(signal.SIGTERM)
        check("...and stops as any start does", ended(proc) == 0, f"exit {proc.returncode}")

    # Opened again while a copy runs, its capture program connected: the panel is all this start is for, at once.
    port = app.free_port()
    with tempfile.TemporaryDirectory() as d:
        held = app.only_one(Path(d))
        running = stand_in_server(port, clients=1)
        asked = time.monotonic()
        proc = started(port, d)
        code = ended(proc, 20)
        took = time.monotonic() - asked
        # and the copy quitting right after starts nothing: this start had ended already
        held.close()
        running.shutdown()
        running.server_close()
        check("opened again while a copy runs with its capture program, it ends at once and starts nothing",
              code == 0 and took < 8 and not app.wait_for(lambda: app.port_free(port) is False, timeout=2),
              f"exit {code} after {took:.1f} s")

print("[the server role ends at once after its close-down, with jobs still running on its threads]")
if sys.platform == "win32":
    print("  skipped: it runs on Linux and macOS here")
else:
  # Asked to close down, as the app asks, and ended with SIGTERM, as it is when asking does not work or the app dies (uvicorn
  # then sends the signal on to the handler that was there before it, and the default one ended the process before its
  # clean-up)
  for how in ("asked", "SIGTERM"):
    port = app.free_port()
    with tempfile.TemporaryDirectory() as d:
        # A job on the loop's threads that nothing cuts short, as the speech model's first download is, itself waiting
        # on threads of its own, which Python waits for before it ends. Started by the server's own speech load, with
        # an answer being written beside it, as the worker starts one: a task no close-down cancels by name, whose own
        # clean-up ends its agent's CLI.
        stand_in = Path(d) / "slow_speech.py"
        stand_in.write_text(
            "import asyncio, concurrent.futures, os, signal, subprocess, sys, time\n"
            "from server import app as server\n"
            "def slow(cfg, model=''):\n"
            "    pool = concurrent.futures.ThreadPoolExecutor(2)\n"
            "    pool.submit(time.sleep, 60).result()\n"
            "server.make_transcriber = slow\n"
            "KEPT = []\n"
            "async def answering():\n"
            "    cli = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
            "    with open(os.environ['CLI_PID'], 'w') as f:\n"
            "        f.write(str(cli.pid))\n"
            "    try:\n"
            "        await asyncio.sleep(3600)\n"
            "    finally:\n"
            "        os.killpg(cli.pid, signal.SIGKILL)\n"
            "load = server.load_speech\n"
            "async def load_speech(app):\n"
            "    KEPT.append(asyncio.get_running_loop().create_task(answering()))\n"
            "    await load(app)\n"
            "server.load_speech = load_speech\n"
            "from desktop.app import main\n"
            "raise SystemExit(main())\n", encoding="utf-8")
        token = "check-token"
        cli_pid = Path(d) / "cli.pid"
        env = dict(os.environ, SIDENOTE_ANALYZER="mock", SIDENOTE_DATA_DIR=d, SIDENOTE_STOP_TOKEN=token,
                   SIDENOTE_LOG_DIR=str(Path(d) / "logs"), PYTHONPATH=str(ROOT), CLI_PID=str(cli_pid))
        proc = subprocess.Popen([sys.executable, str(stand_in), "--serve", "--port", str(port)], cwd=str(ROOT), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        up = app.wait_for(lambda: app.health(port) is not None, timeout=60)
        check(f"{how}: the server comes up with the speech model still loading and an answer being written",
              bool(up) and app.wait_for(lambda: cli_pid.is_file() and cli_pid.read_text().strip(), timeout=30))
        cli = int(cli_pid.read_text()) if cli_pid.is_file() and cli_pid.read_text().strip() else 0
        asked = time.monotonic()
        if how == "asked":
            check("...and closes down when the app asks", app.ask_server_to_stop(port, token))
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        took = time.monotonic() - asked
        check(f"...{how}, it ends within a few seconds with exit 0, waiting for neither", proc.returncode == 0 and took < 5,
              f"exit {proc.returncode} after {took:.1f} s")
        # cancelled as asyncio.run cancels what is left, so its clean-up ran: no CLI writing on for an answer nobody sees
        ended = cli and app.wait_for(lambda: not alive(cli), timeout=5)
        check(f"...{how}, the answer being written is cancelled, its agent's CLI ended by its own clean-up", bool(ended),
              f"CLI {cli} still running" if cli else "no CLI was started")
        if cli and alive(cli):
            os.kill(cli, signal.SIGKILL)

print("[the icon the Windows shortcut wears]")
from PIL import Image, ImageChops  # noqa: E402
from desktop import build as desktop_build  # noqa: E402
with tempfile.TemporaryDirectory() as d:
    # client/sidenote.ico is made from the tray's own drawing. After a change to it:
    #   python -c "from pathlib import Path; from desktop.build import icon; icon(Path('client/sidenote.ico'))"
    # Both closed before the folder goes: Windows cannot delete a file that is still open
    with Image.open(desktop_build.icon(Path(d) / "drawn.ico")) as drawn, Image.open(ROOT / "client" / "sidenote.ico") as kept:
        check("client/sidenote.ico holds every size the app's icon has", sorted(kept.ico.sizes()) == sorted(drawn.ico.sizes()),
              sorted(kept.ico.sizes()))
        # With some room: another build of Pillow may round a pixel of the smoothing differently, and a new drawing is far off
        worst = max((max(hi for _, hi in ImageChops.difference(kept.ico.getimage(s).convert("RGBA"), drawn.ico.getimage(s).convert("RGBA")).getextrema())
                     for s in drawn.ico.sizes() if s in kept.ico.sizes()), default=255)
        check("...and is what the tray's drawing makes now", worst <= 8, f"largest difference in a channel: {worst}")

print("[--check, as CI runs it on the built app]")
done = subprocess.run([sys.executable, "-m", "desktop", "--check"], cwd=str(ROOT), capture_output=True, text=True,
                      timeout=180)
lines = done.stdout.strip().splitlines()
check("it starts the server with stand-in models, gets its panel, and ends with ok",
      done.returncode == 0 and lines[-1:] == ["ok"], done.stdout[-600:] + done.stderr[-600:])

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
