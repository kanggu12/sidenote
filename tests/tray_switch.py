"""The tray's screen and sound switches are the panel's switches: what the capture program sends for them, and
what the server does with it.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/tray_switch.py [path to capture.py]

The tray used to flip only the program's own copy of the switch, writing "the sound
device did not open" into its caps (that is what `audio` means there, and the panel's sound card said so), and
sending a message type the server had no branch for: the panel went on showing the old state, and the next
control message from anywhere put the switch back. The menu also never said so, because pystray builds a
Windows menu again only after a click, and nothing asked it to when the state changed elsewhere.

The client half runs start_tray() against a stand-in pystray (no desktop needed) and presses the menu items;
the server half sends what the client now sends to the real app, in process (mock engines, no network).
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types

# SIDENOTE_LANG=ko: the menu is looked up by its Korean words, which are the words it had before it spoke English too.
# The English menu is checked further down by switching the module's language.
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-tray-switch-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_LANG="ko")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))   # the repository: this file is in tests/
OK, BAD = [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {got}" if got and not cond else ""))


# ---------------------------------------------------------------- the client, with a stand-in pystray
class Item:
    def __init__(self, text, action=None, checked=None, enabled=True, default=False):
        self.text, self.action, self.checked, self.enabled = text, action, checked, enabled

    def is_enabled(self):
        return self.enabled(self) if callable(self.enabled) else bool(self.enabled)


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = [i for i in items if isinstance(i, Item)]


class Icon:
    built = 0                            # how many times the menu was built again (update_menu)

    def __init__(self, name, image, title, menu):
        self.menu = menu

    def run(self):
        threading.Event().wait()         # stands in for the Windows message loop: never returns by itself

    def update_menu(self):
        Icon.built += 1

    def stop(self):
        pass


sys.modules["pystray"] = types.SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=Item)
spec = importlib.util.spec_from_file_location("cap", sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "client/capture.py"))
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
cap.tray_image = lambda: None            # no drawing needed for a menu nobody sees


class Sender:
    """What the tray reads and writes of the real Sender."""

    def __init__(self):
        self.wants = {"screen": True, "audio": True}
        self.caps = {"screen": True, "audio": True}
        self.sent = []
        self.connected = True

    def send(self, msg):
        self.sent.append(msg)

    def set_caps(self, **caps):
        self.caps.update(caps)
        self.sent.append({"type": "caps", **self.caps})


sender, stop = Sender(), threading.Event()
args = types.SimpleNamespace(server="ws://127.0.0.1:8777/ingest", no_audio=False)
icon = cap.start_tray(sender, stop, args)
items = {i.text: i for i in icon.menu.items if isinstance(i.text, str)}
items["소리 캡처"].action(icon, None)
check("the tray's sound switch asks the server, as the panel's does",
      sender.sent == [{"type": "capture_set", "audio": False}], str(sender.sent))
check("...and does not write 'the device did not open' into caps", sender.caps.get("audio") is True, str(sender.caps))
sender.connected = False
check("the switches cannot be flipped with no server to keep them",
      not items["화면 캡처"].is_enabled() and not items["소리 캡처"].is_enabled())
# The drawn right-click menu (client/capture.py, TRAY_MENU): what it is given, and Windows' own menu behind it
compile(cap.TRAY_MENU, "TRAY_MENU", "exec")
rows = cap.tray_rows(icon.menu)
shown = {r["text"]: r for r in rows if not r["sep"]}
check("the drawn menu is given the menu as it stands: nothing to press while there is no server",
      shown["화면 캡처"]["enabled"] is False and shown["끝내기"]["enabled"] is True, str(rows))
check("...and which of its rows are switches", shown["소리 캡처"]["checked"] in (True, False) and shown["끝내기"]["checked"] is None, str(rows))
# Every item has its mark, the panel's own: the tray's right-click menu is drawn in the panel's design
import re  # noqa: E402
marks = eval(re.search(r"^MARKS = (\(.*?\))$", cap.TRAY_MENU, re.M).group(1))
items_shown = [(r["text"], r["mark"]) for r in rows if not r["sep"] and not (not r["enabled"] and r["checked"] is None)]
check("every item of the drawn menu wears a mark of the panel's", items_shown and all(m in marks for _, m in items_shown),
      f"{items_shown} {sorted(marks)}")
# The state's pill takes its colour from the state, not from its words (which are in either language)
state_row = lambda: [r for r in cap.tray_rows(icon.menu) if not r["sep"] and not r["enabled"] and r["checked"] is None][0]   # noqa: E731
tones = [state_row()["tone"]]
sender.connected = True
tones.append(state_row()["tone"])
sender.wants.update(screen=False, audio=False)
tones.append(state_row()["tone"])
sender.wants.update(screen=True, audio=False)
sender.connected = False
check("the state's pill: red with no server, green while taking, grey with nothing taken", tones == ["down", "on", "idle"], str(tones))


def drawn_here(rows_given):
    """The menu runs on Windows only. Where Tk and a virtual display are here (not on CI), it is drawn with Windows' calls stubbed and
    every row under the pointer in turn: a slip in its drawing would otherwise show only as the tray falling back to Windows' plain menu"""
    import shutil
    import subprocess
    if not shutil.which("Xvfb"):
        return None
    try:
        import tkinter  # noqa: F401
        import PIL  # noqa: F401
    except Exception:
        return None
    harness = r"""
import ctypes, json, sys
class Always:
    def __eq__(self, other): return True
class Call:
    def __init__(self, name): self.name, self.restype, self.argtypes = name, None, None
    def __call__(self, *a): return Always() if self.name == "GetForegroundWindow" else 0
class Lib:
    def __getattr__(self, name):
        c = Call(name); setattr(self, name, c); return c
ctypes.windll = type("WinDLL", (), {})()
for lib in ("user32", "kernel32", "shcore", "dwmapi"):
    setattr(ctypes.windll, lib, Lib())
code = sys.stdin.read()
sys.argv = ["menu", sys.argv[1]]
code = code.replace("watch()\nroot.mainloop()", "for at in [None] + choices():\n    hover[0] = at\n    draw()\n    root.update()\nprint(len(c.find_all()), len(images))\nroot.destroy()")
exec(compile(code, "TRAY_MENU", "exec"), {"__name__": "__main__"})
"""
    read, write = os.pipe()
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(write), "-screen", "0", "1100x760x24", "-nolisten", "tcp"], pass_fds=(write,),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write)
    try:
        display = os.read(read, 16).decode().strip()          # the display Xvfb found free, said once it is up
        spec = json.dumps({"rows": [{k: r[k] for k in ("sep", "text", "enabled", "checked", "default", "mark", "tone")} for r in rows_given],
                           "at": [900, 700], "parent": 0, "lang": cap.LANG})
        return subprocess.run([sys.executable, "-c", harness, spec], input=cap.TRAY_MENU, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "DISPLAY": f":{display}"})
    finally:
        os.close(read)
        xvfb.kill()
        xvfb.wait()


for state, connected in (("with the server", True), ("with no server", False)):
    sender.connected = connected
    got = drawn_here(cap.tray_rows(icon.menu))
    if got is None:
        print("  (the drawn menu is not drawn here: no Tk or no Xvfb)")
        break
    check(f"the drawn menu draws, every row under the pointer in turn, {state}", got.returncode == 0 and got.stdout.split()[-1:] == ["1"],
          f"{got.returncode} {got.stdout[-120:]!r} {got.stderr[-600:]}")
sender.connected = False
asked = []
stub = types.SimpleNamespace(menu=icon.menu, _hwnd=0, _on_notify=lambda w, l: asked.append(l))
stub._message_handlers = {1024: stub._on_notify}
check("it takes a right click from pystray", cap.own_tray_menu(stub) and stub._message_handlers[1024] != stub._on_notify)
stub._message_handlers[1024](0, 0x0202)
check("a left click is still pystray's", asked == [0x0202], str(asked))
if sys.platform != "win32":
    stub._message_handlers[1024](0, 0x0205)  # no Windows here: it cannot run, as a Python without tkinter cannot
    check("a right click it cannot serve falls to Windows' own menu", asked == [0x0202, 0x0205], str(asked))
check("an icon with none of that keeps Windows' menu", not cap.own_tray_menu(types.SimpleNamespace(menu=icon.menu)))
before = Icon.built
sender.wants["screen"] = False           # what a control message from the panel does
time.sleep(2.5)
check("the menu is built again when the state it shows changes elsewhere", Icon.built > before,
      f"{before} -> {Icon.built}")
stop.set()

# ---------------------------------------------------------------- the same menu in English
# Which language a program starts in (off Windows: SIDENOTE_LANG, else the locale, else English)
if sys.platform != "win32":
    NAMES = ("SIDENOTE_LANG", "LC_ALL", "LC_MESSAGES", "LANG")
    saved = {k: os.environ.get(k) for k in NAMES}
    picked = []
    for env, want in (({"SIDENOTE_LANG": "en", "LANG": "ko_KR.UTF-8"}, "en"), ({"SIDENOTE_LANG": "ko", "LANG": "en_US.UTF-8"}, "ko"),
                      ({"LANG": "ko_KR.UTF-8"}, "ko"), ({"LANG": "en_US.UTF-8"}, "en"), ({"LANG": "C.UTF-8"}, "en"),
                      ({"LC_ALL": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}, "ko"), ({"LC_MESSAGES": "en_US.UTF-8", "LANG": "ko_KR.UTF-8"}, "en"),
                      ({}, "en")):
        for k in NAMES:
            os.environ.pop(k, None)
        os.environ.update(env)
        picked.append((env, cap.ui_lang(), want))
    for k, v in saved.items():                 # as it was: SIDENOTE_LANG=ko for the server half below
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
    check("the language: SIDENOTE_LANG, else a Korean locale (LC_ALL, LC_MESSAGES, LANG in that order), else English",
          all(got == want for _, got, want in picked), str([p for p in picked if p[1] != p[2]]))
# The language is read once, when the program starts; switched here for a second menu, as a program started in English has it
cap.LANG = "en"
hangul = re.compile("[가-힣]")
sender_en, stop_en = Sender(), threading.Event()
icon_en = cap.start_tray(sender_en, stop_en, args)
words = []
for connected in (True, False):
    sender_en.connected = connected
    words += [r["text"] for r in cap.tray_rows(icon_en.menu) if not r["sep"]]
check("in English the menu holds no Korean, with the server and without", words and not any(hangul.search(w) for w in words), str(words))
rows_en = cap.tray_rows(icon_en.menu)
check("...its rows wear the same marks as in Korean", [r["mark"] for r in rows_en] == [r["mark"] for r in cap.tray_rows(icon.menu)],
      str([(r["text"], r["mark"]) for r in rows_en]))
got = drawn_here(rows_en)
if got is not None:
    check("...and the drawn menu draws it", got.returncode == 0 and got.stdout.split()[-1:] == ["1"],
          f"{got.returncode} {got.stdout[-120:]!r} {got.stderr[-600:]}")
stop_en.set()
cap.LANG = "ko"

# ---------------------------------------------------------------- the server, in process
sys.path.insert(0, ROOT)
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402

with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    with c.websocket_connect("ws://127.0.0.1:8777/ingest") as ws:
        ws.send_text(json.dumps({"type": "hello", "info": "capture/win32", "screen": True, "audio": True,
                                 "no_audio": False, "monitor": 1, "flags": {}}))
        ws.receive_text()                # the switches on connect
        ws.send_text(json.dumps({"type": "capture_set", "audio": False}))
        # Read the server's state first and the socket only when the switch did change: a server that ignores the
        # message sends nothing back, and receive_text() has no timeout to fail on.
        health = {}
        for _ in range(20):
            health = c.get("/health").json()["capture"]
            if health["audio_on"] is False:
                break
            time.sleep(0.1)
        took = health.get("audio_on") is False
        back = json.loads(ws.receive_text()) if took else {}
        check("the server takes the tray's switch: sound capture off", took, str(health))
        check("...sends it back to the program as control", back.get("type") == "control" and back.get("audio") is False,
              str(back))
        check("...and leaves what the program said of its device alone", health.get("caps", {}).get("audio") is True,
              str(health.get("caps")))
        if took:
            ws.send_text(json.dumps({"type": "capture_set", "audio": True}))   # leave it as it was found
            ws.receive_text()

# macOS: AppKit's loop runs on the main thread only, so the icon is handed to main() to run there, not started
ran_on = []
Icon.run = lambda self: ran_on.append(threading.current_thread() is threading.main_thread())
was, sys.platform = sys.platform, "darwin"
try:
    stop_mac = threading.Event()
    mac = cap.start_tray(Sender(), stop_mac, args)
finally:
    sys.platform = was
check("on macOS the tray is not started on a thread of its own", mac is not None and not ran_on
      and getattr(mac, "sidenote_thread", None) is None, str(ran_on))
mac.sidenote_main()
check("...and is run by whoever calls it, main() on the main thread", ran_on == [True], str(ran_on))
stop_mac.set()

print(f"\n==== {len(OK)} passed, {len(BAD)} failed ====")
sys.exit(1 if BAD else 0)
