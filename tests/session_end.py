"""Whoever starts the server stops it: a start that brought the server up (./sidenote capture --up, the desktop
shortcut) hands the capture program its checkout (--stop-server-on-quit), and the person's Quit from the tray then ends
the server too, through that checkout's ./sidenote down. Nothing else ends it. Checked here:

- what Quit may run: its own checkout's ./sidenote down and nothing else, from a value of the shape the launcher makes
  (a WSL path on Windows, run in a login shell as the shortcut runs the launcher; the folder elsewhere); another
  checkout, or anything else, runs nothing;
- which ends stop the server: the person's Quit alone, never one the program was asked for (./sidenote capture-stop or
  down, another capture program taking over), a restart of its own, or an end under the desktop app;
- the tray says it: "Quit Sidenote" where Quit ends the server too, "Quit" where it does not;
- the capture program itself (a real server on a free port, a private Xvfb display, stand-ins for its screen grabber
  and its tray library, and a checkout whose ./sidenote only writes down that it ran): Quit pressed in the tray ends it
  with 0 and runs ./sidenote down; asked to quit through the server, taken over by another capture program, or quit
  where no checkout was handed to it, it runs nothing.

    .venv/bin/python tests/session_end.py
"""
import ctypes.util
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
os.environ["SIDENOTE_LANG"] = "en"           # the menu's English words, before the program is loaded
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail != "" and not ok else ""), flush=True)


spec = importlib.util.spec_from_file_location("capture_session", ROOT / "client" / "capture.py")
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)
WORK = Path(tempfile.mkdtemp(prefix="sidenote-session-"))


def checkout(name: str, script: bool = True, runnable: bool = True, client: bool = True, program: bool = False) -> Path:
    """A folder shaped as a Sidenote checkout, whose ./sidenote only writes its arguments to ran.txt beside it. With
    `program`, its client/ is this repository's own, so the capture program run from it has it for its checkout."""
    folder = WORK / name
    (folder / "client").mkdir(parents=True)
    if program:
        shutil.copytree(ROOT / "client", folder / "client", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        (folder / "server").mkdir()   # where a checkout keeps its release, which the program says in its hello (code_version)
        shutil.copy(ROOT / "server" / "version.py", folder / "server" / "version.py")
    elif client:
        (folder / "client" / "capture.py").write_text("", encoding="utf-8")
    if script:
        launcher = folder / "sidenote"
        launcher.write_text(f'#!/bin/sh\necho "$@" >> "{folder}/ran.txt"\n', encoding="utf-8")
        if runnable:
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return folder


def ran(folder: Path, limit: float = 0.0) -> str:
    """What the checkout's ./sidenote was run with, waiting up to `limit` seconds for it."""
    end = time.monotonic() + limit
    while True:
        text = (folder / "ran.txt").read_text(encoding="utf-8").strip() if (folder / "ran.txt").exists() else ""
        if text or time.monotonic() >= end:
            return text
        time.sleep(0.1)


print("\n[what it says of itself]")
# The system in a few words, as Windows tells it by its build (Windows 11 still says release 10) and a server by its kind
real_version = getattr(sys, "getwindowsversion", None)
said = []
try:
    for build, kind in ((26300, 1), (19045, 1), (20348, 3), (26100, 2)):
        sys.getwindowsversion = lambda build=build, kind=kind: types.SimpleNamespace(build=build, product_type=kind)
        said.append(cap.system_name("win32"))
finally:
    if real_version is None:
        del sys.getwindowsversion
    else:
        sys.getwindowsversion = real_version
check("Windows by its build, and a Windows Server as one", said == ["Windows 11", "Windows 10", "Windows Server", "Windows Server"], said)
import platform as _platform  # noqa: E402   (pc_name reads it when called)
was_node = _platform.node
try:
    _platform.node = lambda: "Studio-Mac.local"
    mac_name = cap.pc_name()
finally:
    _platform.node = was_node
check("a Mac's name without the network's .local", mac_name == "Studio-Mac", mac_name)

print("\n[what Quit may run]")
OWN = r"\\wsl.localhost\Ubuntu-22.04\home\me\side note"   # the checkout a program on Windows runs from, as WSL shows it
LOGIN = ["bash", "-lc", cap.QUIT_SCRIPT, "sidenote-quit"]
wsl = cap.server_down_command(OWN, "win32", own=OWN)
check("its own checkout's WSL path: wsl.exe runs ./sidenote down there in a login shell, the path an argument of it",
      wsl == ["wsl.exe", "-d", "Ubuntu-22.04", "--exec", *LOGIN, "/home/me/side note"]
      and cap.QUIT_SCRIPT == 'cd -- "$1" || exit; exec ./sidenote down', wsl)
check("...the older wsl$ name, a closing backslash and the distro's name in another case are the same checkout",
      all(cap.server_down_command(v, "win32", own=OWN) == wsl for v in
          ("\\\\wsl$\\Ubuntu-22.04\\home\\me\\side note", OWN + "\\", r"\\wsl.localhost\ubuntu-22.04\home\me\side note")))
odd = ["", r"C:\Users\me\sidenote", r"\\server\share\sidenote", r"\\wsl.localhost\Ubuntu", r"\\wsl.localhost\Ub untu\x",
       "\\\\wsl.localhost\\Ubuntu\\a\nb", '\\\\wsl.localhost\\Ubuntu\\a"b', "-c", "calc.exe",
       r"\\wsl.localhost\Ubuntu-22.04\home\me\other", r"\\wsl.localhost\Debian\home\me\side note",
       r"\\wsl.localhost\Ubuntu-22.04\home\me\Side note"]
check("anything else runs nothing on Windows: another checkout or distro (a forged line), a path in another case, "
      "another share, a Windows folder, a control character, an option",
      all(cap.server_down_command(v, "win32", own=OWN) is None for v in odd),
      [v for v in odd if cap.server_down_command(v, "win32", own=OWN)])
here = checkout("here")
check("a checkout folder elsewhere: its own ./sidenote down", cap.server_down_command(str(here), "linux", own=str(here))
      == [str(here / "sidenote"), "down"], cap.server_down_command(str(here), "linux", own=str(here)))
not_one = [str(checkout("no-script", script=False)), str(checkout("not-runnable", runnable=False)),
           str(checkout("no-client", client=False)), "relative/path", str(here) + "\n", str(WORK)]
check("...and a folder that is no checkout (no launcher, one that cannot run, no capture program beside it) runs nothing",
      all(cap.server_down_command(v, "linux", own=v) is None for v in not_one),
      [v for v in not_one if cap.server_down_command(v, "linux", own=v)])
check("...nor a checkout other than the program's own", cap.server_down_command(str(here), "linux") is None
      and cap.own_checkout() == str(ROOT), cap.own_checkout())

print("\n[which ends stop the server]")


def ends(**flags) -> bool:
    return cap.session_ends_server(types.SimpleNamespace(**flags))


check("the person's Quit from the tray", ends(quit_by_person=True))
check("...and not one asked of the program (capture-stop, down), nor a restart, nor a take-over",
      not ends(quit_by_person=False) and not ends(quit_by_person=True, restart_asked=True)
      and not ends(quit_by_person=True, taken_over=True))
os.environ["SIDENOTE_SUPERVISED"] = "1"
check("...nor under the desktop app, which ends its own server", not ends(quit_by_person=True))
del os.environ["SIDENOTE_SUPERVISED"]
check("nothing is started without a command", cap.stop_server(None) is False)
started = checkout("started")
check("the command starts on its own, and runs", cap.stop_server([str(started / "sidenote"), "down"]) is True
      and ran(started, 5) == "down", ran(started))

print("\n[the tray says it]")


class Item:
    def __init__(self, text, action=None, checked=None, enabled=True, default=False):
        self.text, self.action = text, action


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = [i for i in items if isinstance(i, Item)]


class Icon:
    def __init__(self, name, image, title, menu):
        self.menu = menu

    def run(self):
        threading.Event().wait()

    def update_menu(self):
        pass

    def stop(self):
        pass


sys.modules["pystray"] = types.SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=Item)
cap.tray_image = lambda: None


class Sender:
    wants = {"screen": True, "audio": True}
    caps = {"screen": True}
    connected = True

    def send(self, msg):
        pass

    def set_caps(self, **caps):
        pass


def quit_item(handed: str):
    sender, stop = Sender(), threading.Event()
    icon = cap.start_tray(sender, stop, types.SimpleNamespace(server="ws://127.0.0.1:8777/ingest", no_audio=False,
                                                              stop_server_on_quit=handed))
    item = next(i for i in icon.menu.items if getattr(i, "sidenote_mark", None) == "quit")
    return item, sender, stop, icon


item, sender, stop, icon = quit_item(str(ROOT))   # its own checkout: pressed here, nothing is run (main does that)
check('after a start that brought the server up the item says "Quit Sidenote"', item.text == "Quit Sidenote", item.text)
item.action(icon, item)
check("...and pressing it marks the person's Quit, and ends the program",
      getattr(sender, "quit_by_person", False) is True and stop.is_set())
plain, _, _, _ = quit_item("")
check('where Quit leaves the server it says "Quit"', plain.text == "Quit", plain.text)

print("\n[the capture program itself, on a private X display]")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
LOGS = tempfile.mkdtemp(prefix="sidenote-session-logs-")
ENV = {**{k: v for k, v in os.environ.items() if k not in ("SIDENOTE_LANG", "SIDENOTE_CAPTURE_RUN")},
       "SIDENOTE_ANALYZER": "mock", "SIDENOTE_AGENT": "mock", "SIDENOTE_TRANSCRIBER": "null", "SIDENOTE_RUNNER_URL": "",
       "SIDENOTE_LOG_DIR": LOGS, "SIDENOTE_SEARCH_URL": "", "SIDENOTE_LOCAL_PULL": "0", "SIDENOTE_UPDATE_CHECK": "0",
       "SIDENOTE_PORT": str(PORT), "SIDENOTE_STALL_WARN_SEC": "0", "SIDENOTE_STALL_EXIT_SEC": "0",
       "PYTHONDONTWRITEBYTECODE": "1"}
# The screen grabber and the tray library stood in for, with their own shapes: one plain screen (as tests/many_clients.py
# has it), and a tray whose icon presses the menu item STAND_IN_PRESS names once the program is connected
STAND_INS = {
    "mss.py": '''class MSS:
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
''',
    "pystray.py": '''import os
import threading
import time


class MenuItem:
    def __init__(self, text, action=None, checked=None, enabled=True, default=False):
        self.text, self.action = text, action


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = [i for i in items if isinstance(i, MenuItem)]


class Icon:
    def __init__(self, name, image, title, menu):
        self.menu, self.done = menu, threading.Event()

    def run(self):
        press = os.environ.get("STAND_IN_PRESS", "")
        if press:      # the person, a few seconds after the start (the test checks the program connected first)
            def later():
                time.sleep(float(os.environ.get("STAND_IN_AFTER", "6")))
                for item in self.menu.items:
                    if item.text == press:
                        print("[stand-in tray] pressed " + press, flush=True)
                        item.action(self, item)
                        return
                print("[stand-in tray] no item says " + press, flush=True)
            threading.Thread(target=later, daemon=True).start()
        self.done.wait()

    def update_menu(self):
        pass

    def stop(self):
        self.done.set()
''',
}


def status() -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v1/status", timeout=10) as r:
        return json.loads(r.read())["capture"]


def wait_for(what, limit: float) -> bool:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            if what():
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def xvfb():
    """A private Xvfb display (never the user's screen), its number and its process; None without Xvfb or libX11."""
    if not shutil.which("Xvfb") or not ctypes.util.find_library("X11"):
        return None
    read, write = os.pipe()
    proc = subprocess.Popen(["Xvfb", "-displayfd", str(write), "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                            pass_fds=(write,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write)
    try:
        number = os.read(read, 16).decode().strip()
    finally:
        os.close(read)
    if not number:
        proc.kill()
        proc.wait()
        return None
    return number, proc


srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(PORT),
                        "--no-access-log", "--timeout-graceful-shutdown", "5"], cwd=ROOT, env=ENV,
                       stdout=open(os.path.join(LOGS, "uvicorn.out"), "w"), stderr=subprocess.STDOUT)
up = xvfb()
try:
    check("(the server answers)", wait_for(lambda: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200, 30))
    if up is None:
        print("  (not tried: no Xvfb or no libX11 here)")
    else:
        number, xproc = up
        stand_in = WORK / "stand-in"
        stand_in.mkdir()
        for name, text in STAND_INS.items():
            (stand_in / name).write_text(text, encoding="utf-8")

        def program(folder: Path, hand: bool = True, press: str = "", more: tuple = ()):
            """The capture program of this checkout as the launcher starts it, the checkout handed to it or not, with what the
            stand-in tray presses."""
            run_dir = tempfile.mkdtemp(prefix="sidenote-session-run-")   # its guard's file, away from the user's
            env = {**{k: v for k, v in os.environ.items() if k not in ("SIDENOTE_CAPTURE_RUN", "SIDENOTE_SUPERVISED")},
                   "DISPLAY": f":{number}", "XDG_RUNTIME_DIR": run_dir, "SIDENOTE_LANG": "en",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(stand_in), "STAND_IN_PRESS": press}
            args = [sys.executable, "-u", str(folder / "client" / "capture.py"), "--server", f"ws://127.0.0.1:{PORT}/ingest",
                    "--no-audio", "--no-auto-update", *more] + (["--stop-server-on-quit", str(folder)] if hand else [])
            return subprocess.Popen(args, env=env, cwd=run_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        def ended(proc, limit: float = 30) -> tuple:
            try:
                rc = proc.wait(limit)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = None
            return rc, proc.stdout.read()

        session = checkout("session", program=True)
        prog = program(session, press="Quit Sidenote")
        try:
            check("(the program connects)", wait_for(lambda: status()["clients"] == 1, 5), status())
            rc, out = ended(prog)
        finally:
            if prog.poll() is None:
                prog.kill()
        check("Quit Sidenote pressed in the tray: the program ends with 0", rc == 0, f"exit {rc}: {out[-500:]}")
        check("...and runs its checkout's ./sidenote down", ran(session, 10) == "down", ran(session) or out[-500:])
        check("...saying so in its log", "Stopping the server this start brought up too (./sidenote down)" in out, out[-500:])
        wait_for(lambda: status()["clients"] == 0, 10)

        asked = checkout("asked", program=True)
        prog = program(asked, more=("--started", "terminal"))
        try:
            connected = wait_for(lambda: status()["clients"] == 1, 30)
            # What it says of itself, for the panel's Capture connection: this PC and its system, its checkout's release, how
            # the launcher started it, the address it was given, and that its Quit ends the server its start brought up
            wait_for(lambda: status().get("who"), 5)
            version = re.search(r'^VERSION = "([0-9.]+)"', (ROOT / "server" / "version.py").read_text(encoding="utf-8"), re.M).group(1)
            check("its hello says what it is: its PC and system, its release, how it was started, its address, and what its Quit ends",
                  status().get("who") == {"host": cap.pc_name(), "system": cap.system_name(), "version": version, "started": "terminal",
                                          "server": f"ws://127.0.0.1:{PORT}/ingest", "ends_server": True}, status().get("who"))
            # Following the changing screen has moved nothing at a start: the chosen monitor is read, and said from the hello
            caps = status().get("caps") or {}
            check("...and that it reads the chosen monitor (following: null)", "following" in caps and caps["following"] is None, caps)
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/capture/quit", data=b"", method="POST")
            urllib.request.urlopen(req, timeout=10).close()     # ./sidenote capture-stop, as down asks it first
            rc, out = ended(prog)
        finally:
            if prog.poll() is None:
                prog.kill()
        check("asked to quit through the server (capture-stop, down): it ends with 0 and runs nothing",
              connected and rc == 0 and ran(asked, 3) == "", f"exit {rc}, ran {ran(asked)!r}: {out[-300:]}")
        wait_for(lambda: status()["clients"] == 0, 10)

        taken = checkout("taken", program=True)
        prog = program(taken)
        newer = None
        try:
            connected = wait_for(lambda: status()["clients"] == 1, 30)
            newer = websocket.create_connection(f"ws://127.0.0.1:{PORT}/ingest", timeout=15)
            newer.send(json.dumps({"type": "hello", "info": "capture/newer", "run": "e" * 16, "screen": True}))
            rc, out = ended(prog)
        finally:
            if prog.poll() is None:
                prog.kill()
            if newer is not None:
                newer.close()
        check("taken over by another capture program: it ends with 77 and runs nothing",
              connected and rc == 77 and ran(taken, 3) == "", f"exit {rc}, ran {ran(taken)!r}: {out[-300:]}")
        wait_for(lambda: status()["clients"] == 0, 15)

        plain = checkout("plain", program=True)
        prog = program(plain, hand=False, press="Quit")
        try:
            check("(that program connects too)", wait_for(lambda: status()["clients"] == 1, 5), status())
            wait_for(lambda: status().get("who"), 5)
            got = status().get("who") or {}
            check("...started by hand with no checkout handed: it says so, and that its Quit leaves the server",
                  got.get("started") == "own" and got.get("ends_server") is False, got)
            rc, out = ended(prog)
        finally:
            if prog.poll() is None:
                prog.kill()
        check("Quit pressed where no checkout was handed (the server was up before): it ends with 0 and runs nothing",
              rc == 0 and ran(plain, 3) == "" and "Stopping the server" not in out, f"exit {rc}: {out[-300:]}")
finally:
    if up is not None:   # the private display, however this ended: a check that raised left it running for an hour
        up[1].kill()
        up[1].wait(10)
    srv.terminate()
    try:
        srv.wait(15)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
