"""Sidenote on one PC without Docker (desktop/app.py): the server's environment on the host, the data folder on each
system, the capped log files, the port check, the watch that starts a stopped child again and stops when the capture
program is quit, the `python -c` the Windows app stands in for, and the whole start and stop on a spare port with
stand-in models.

    .venv/bin/python tests/desktop_check.py
"""
import io
import os
import signal
import subprocess
import sys
import tempfile
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
    finder = os.pathsep.join(["/usr/bin", "/bin"])
    with mock.patch.object(app, "FROZEN", True):
        mac_path = app.server_env({"PATH": finder}, Path("/d"), 1)["PATH"].split(os.pathsep)
        again = app.server_env({"PATH": os.pathsep.join(mac_path)}, Path("/d"), 1)["PATH"].split(os.pathsep)
    check("...the app opened from the Finder finds Homebrew's and the agents' commands",
          mac_path[:2] == ["/usr/bin", "/bin"] and "/opt/homebrew/bin" in mac_path
          and str(Path.home() / ".local" / "bin") in mac_path, mac_path)
    check("...without adding them twice", again == mac_path, again)
    check("...and run from a checkout, in a terminal, it keeps the terminal's PATH as it is",
          app.server_env({"PATH": finder}, Path("/d"), 1)["PATH"] == finder)

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
