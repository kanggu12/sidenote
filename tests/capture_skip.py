"""Skip windows: while the window in front has one of the panel's words in its title or its program's name, the capture
program sends no screen at all, and the words reach it from the server's settings.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/capture_skip.py [path to capture.py]

The window in front is read where the capture program runs, and none of what is read leaves it: Windows' calls and
libX11 are stood in for here, and X11 is also read for real on a private Xvfb display where Xvfb is installed (not on
every CI runner: the line before the tally says when it was not). The screen loop runs on made-up screens, as in
tests/capture_loop.py; the server half runs the real app in process, with the mock engines.
"""
import ctypes
import ctypes.util
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_SEARCH_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-skip-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_LANG="ko")
ROOT = Path(__file__).resolve().parents[1]                     # the repository: this file is in tests/
CAPTURE = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "client" / "capture.py")
spec = importlib.util.spec_from_file_location("cap", CAPTURE)  # the capture program, or an older copy named on the line
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
OK, BAD, NOTES = [], [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""), flush=True)


def words(*ws):
    """The words as the capture program holds them, from the panel's."""
    return cap.skip_words(list(ws))


# ---------------------------------------------------------------- the words and the match
print("[the words and the match]")
BITWARDEN = ("Vault - Bitwarden", "Bitwarden.exe")
check("a word in the title is a match", cap.skip_match(("Sign in - Bitwarden", "chrome.exe"), words("Bitwarden")))
check("a word in the program's name is a match", cap.skip_match(("Vault", "Bitwarden.exe"), words("Bitwarden")))
check("in any case", cap.skip_match(("my BITWARDEN vault", ""), words("bitwarden"))
      and cap.skip_match(("x", "keepassxc KeePassXC"), words("KEEPASSXC")))
check("a part of a word is a match, so words of a language written without spaces are found",
      cap.skip_match(("KB국민은행 - Chrome", "chrome.exe"), words("은행")))
check("a window with none of the words is no match",
      not cap.skip_match(("Problem 1 - Baekjoon - Chrome", "chrome.exe"), words(*cap.SKIP_WINDOWS)))
check("no words, or nothing known of the window, is no match",
      not cap.skip_match(BITWARDEN, []) and not cap.skip_match(None, words("Bitwarden")))
check("the words are trimmed and the empty ones dropped", words("  Bank ", "", "   ", "Mail") == ["bank", "mail"],
      words("  Bank ", "", "   ", "Mail"))
# The windows the default list is for, as they are titled and named on Windows and on Linux
DEFAULT_WINDOWS = [("Passwords - 1Password", "1Password.exe"), ("My vault | Bitwarden", "Bitwarden.exe"),
                   ("Database.kdbx - KeePass", "KeePass.exe"), ("Passwords.kdbx - KeePassXC", "keepassxc KeePassXC"),
                   ("LastPass", "chrome.exe"), ("Dashlane", "Dashlane.exe"), ("Keeper", "Keeper Password Manager.exe"),
                   ("Enpass", "Enpass.exe"), ("NordPass", "NordPass.exe"), ("Proton Pass", "Proton Pass.exe"),
                   ("New InPrivate tab - [InPrivate] - Microsoft Edge", "msedge.exe"),
                   ("New Incognito tab - Google Chrome (Incognito)", "chrome.exe"),
                   ("Mozilla Firefox Private Browsing", "Navigator firefox"),
                   ("새 시크릿 탭 - Chrome", "chrome.exe"), ("Mozilla Firefox 사생활 보호 모드", "Navigator firefox")]
default = words(*cap.SKIP_WINDOWS)
check("the default list skips each password manager and private window it names",
      all(cap.skip_match(w, default) for w in DEFAULT_WINDOWS), [w for w in DEFAULT_WINDOWS if not cap.skip_match(w, default)])
sys.path.insert(0, str(ROOT))
from server.settings import SKIP_WINDOWS as SERVER_DEFAULT  # noqa: E402
check("the capture program's default list is the server's", cap.SKIP_WINDOWS == SERVER_DEFAULT,
      f"{cap.SKIP_WINDOWS} / {SERVER_DEFAULT}")
check("and the program holds it until the server says otherwise",
      cap.Sender("ws://127.0.0.1:1/ingest").wants.get("skip_windows") == default)


# ---------------------------------------------------------------- what shows, from a list of made-up windows
print("\n[what shows]")
SCREEN = {"left": 0, "top": 0, "width": 1000, "height": 800}
VAULT, FULL = ("My vault | Bitwarden", "Bitwarden.exe"), (0, 0, 1000, 800)


def shown(name, rect, covers=True):
    """A window as skip_visible takes it: covering with its own rectangle unless told otherwise."""
    return (name[0], name[1], rect, rect if covers is True else covers)


CODE, SITE = ("capture.py - Code", "Code.exe"), ("Docs - Chrome", "chrome.exe")
check("a window to skip behind another with the focus, partly showing: no screen",
      cap.skip_visible([shown(CODE, (0, 0, 600, 800)), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("...one pixel of it showing is enough", cap.skip_visible([shown(CODE, (0, 0, 899, 800)), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("wholly under a maximized window: the screen goes on", not cap.skip_visible([shown(CODE, FULL), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("the same size exactly: wholly under it", not cap.skip_visible([shown(CODE, (400, 100, 900, 700)), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("wholly under two windows together, neither covering it alone",
      not cap.skip_visible([shown(CODE, (0, 0, 650, 800)), shown(SITE, (650, 0, 1000, 800)), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("...with a gap of a pixel between them, it shows",
      cap.skip_visible([shown(CODE, (0, 0, 650, 800)), shown(SITE, (651, 0, 1000, 800)), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("a window below it covers nothing of it", cap.skip_visible([shown(VAULT, (400, 100, 900, 700)), shown(CODE, FULL)], default, SCREEN))
check("on another monitor it is not in what is sent",
      not cap.skip_visible([shown(VAULT, (1000, 0, 1500, 600))], default, SCREEN))
check("...and on the monitor that is sent, it is",
      cap.skip_visible([shown(VAULT, (1000, 0, 1500, 600))], default, {"left": 1000, "top": 0, "width": 1920, "height": 1080}))
check("across two monitors, its part on this one counts", cap.skip_visible([shown(VAULT, (900, 0, 1500, 600))], default, SCREEN))
check("what covers it off this monitor leaves its part here showing",
      cap.skip_visible([shown(CODE, (1000, 0, 1500, 600)), shown(VAULT, (900, 0, 1500, 600))], default, SCREEN))
check("an overlay over it hides nothing", cap.skip_visible([shown(CODE, FULL, covers=None), shown(VAULT, (400, 100, 900, 700))], default, SCREEN))
check("a frame counts as covering, past the window's own area",
      not cap.skip_visible([shown(CODE, (10, 30, 990, 790), covers=FULL), shown(VAULT, (0, 0, 1000, 800))], default, SCREEN))
check("no window to skip on the list: the screen goes on", not cap.skip_visible([shown(CODE, FULL), shown(SITE, (0, 0, 10, 10))], default, SCREEN))
check("a window with no area shows nothing", not cap.skip_visible([shown(VAULT, (400, 100, 400, 700))], default, SCREEN))
check("many windows take no time", not cap.skip_visible([shown(CODE, (i, i, i + 500, i + 500)) for i in range(128)] + [shown(CODE, FULL), shown(VAULT, (1, 1, 2, 2))], default, {**SCREEN, "width": 1, "height": 1}))
OWN = [("Sidenote Panel", "chrome.exe"), ("Sidenote Panel - Google Chrome (Incognito)", "chrome.exe"), ("Sidenote 패널 - InPrivate", "msedge.exe")]
check("this tool's own panel is no window to skip, even in a private window of the browser",
      not any(cap.skip_match(own, default) for own in OWN), [own for own in OWN if cap.skip_match(own, default)])
check("...nor with its name among the words", not cap.skip_match(OWN[0], words("sidenote")))
check("...nor on the list", not cap.skip_visible([shown(own, (0, 0, 500, 500)) for own in OWN], default, SCREEN))
check("...and it still covers what is under it", not cap.skip_visible([shown(OWN[0], FULL), shown(VAULT, (0, 0, 500, 500))], default, SCREEN))
check("a page that only names the tool is an ordinary window", cap.skip_match(("Sidenote notes - Incognito", "chrome.exe"), default))


# ---------------------------------------------------------------- Windows, stood in for
print("\n[Windows, stood in for]")


class FakeWindows:
    """user32 and kernel32 as _front_win32 calls them: a window in front with its title, and its process's path."""

    def __init__(self):
        self.hwnd, self.title, self.pid, self.path = 0x1A2B, "", 4321, ""
        self.can_open, self.opened, self.closed, self.asked = True, 0, 0, None
        user32, kernel32 = types.SimpleNamespace(), types.SimpleNamespace()

        def GetForegroundWindow():
            return self.hwnd or None

        def GetWindowTextLengthW(hwnd):
            return len(self.title)

        def GetWindowTextW(hwnd, buf, n):
            buf.value = self.title[:n - 1]
            return len(buf.value)

        def GetWindowThreadProcessId(hwnd, pid):
            pid._obj.value = self.pid
            return 1

        def OpenProcess(access, inherit, pid):
            self.asked = (access, pid)
            if not self.can_open:
                return None
            self.opened += 1
            return 0x99

        def QueryFullProcessImageNameW(process, flags, buf, size):
            buf.value = self.path
            size._obj.value = len(self.path)
            return 1

        def CloseHandle(handle):
            self.closed += 1
            return 1

        for f in (GetForegroundWindow, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId):
            setattr(user32, f.__name__, f)
        for f in (OpenProcess, QueryFullProcessImageNameW, CloseHandle):
            setattr(kernel32, f.__name__, f)
        self.windll = types.SimpleNamespace(user32=user32, kernel32=kernel32)


class FakeDesktop:
    """user32, kernel32 and dwmapi as _stack_win32 calls them: the desktop's windows, top of the z-order first."""
    TOOL, CLICK_THROUGH = 0x80, 0x20

    def __init__(self, windows):
        self.windows = {i + 1: dict(w) for i, w in enumerate(windows)}
        self.opened, self.closed, self.fail = [], 0, False
        self.current = None
        user32, kernel32, dwm = types.SimpleNamespace(), types.SimpleNamespace(), types.SimpleNamespace()

        def of(hwnd):
            return self.windows[getattr(hwnd, "value", hwnd)]

        def EnumWindows(visit, _):
            if self.fail:
                raise OSError("no list today")
            for hwnd in self.windows:
                if not visit(hwnd, 0):
                    break
            return 1

        user32.EnumWindows = EnumWindows
        user32.IsWindowVisible = lambda hwnd: of(hwnd).get("visible", True)
        user32.IsIconic = lambda hwnd: of(hwnd).get("minimized", False)
        user32.GetWindowTextLengthW = lambda hwnd: len(of(hwnd).get("title", ""))
        user32.GetWindowLongW = lambda hwnd, which: of(hwnd).get("style", 0)

        def GetClassNameW(hwnd, buf, n):
            buf.value = of(hwnd).get("cls", "Window")
            return len(buf.value)

        def GetWindowTextW(hwnd, buf, n):
            buf.value = of(hwnd).get("title", "")[:n - 1]
            return len(buf.value)

        def GetWindowThreadProcessId(hwnd, pid):
            pid._obj.value = of(hwnd).get("pid", 1)
            self.current = of(hwnd)
            return 1

        def DwmGetWindowAttribute(hwnd, what, out, size):
            w = of(hwnd)
            if what == 14:
                out._obj.value = 1 if w.get("cloaked") else 0
                return 0
            r = w["rect"]
            out._obj.left, out._obj.top, out._obj.right, out._obj.bottom = r
            return 0

        def OpenProcess(access, inherit, pid):
            self.opened.append(pid)
            return 0x99

        def QueryFullProcessImageNameW(process, flags, buf, size):
            buf.value = "C:\\Apps\\" + self.current.get("exe", "app.exe")
            return 1

        def CloseHandle(handle):
            self.closed += 1
            return 1

        for f in (GetClassNameW, GetWindowTextW, GetWindowThreadProcessId):
            setattr(user32, f.__name__, f)
        for f in (OpenProcess, QueryFullProcessImageNameW, CloseHandle):
            setattr(kernel32, f.__name__, f)
        dwm.DwmGetWindowAttribute = DwmGetWindowAttribute
        self.windll = types.SimpleNamespace(user32=user32, kernel32=kernel32, dwmapi=dwm)


win = FakeWindows()
had = getattr(ctypes, "windll", None)           # none off Windows
ctypes.windll = win.windll                      # what _front_win32 reaches for
try:
    win.title, win.path = "My vault | Bitwarden", r"C:\Program Files\Bitwarden\Bitwarden.exe"
    got = cap._front_win32()
    check("the window in front: its title, and its program's file name without the folder",
          got == ("My vault | Bitwarden", "Bitwarden.exe"), got)
    check("its process is asked only for its name (PROCESS_QUERY_LIMITED_INFORMATION) and closed again",
          win.asked == (0x1000, 4321) and win.opened == win.closed == 1, (win.asked, win.opened, win.closed))
    win.can_open = False
    got = cap._front_win32()
    check("a process that cannot be opened leaves the title to go by", got == ("My vault | Bitwarden", ""), got)
    win.can_open, win.hwnd = True, 0
    check("no window in front (the lock screen) is nothing to go by", cap._front_win32() is None)
    win.hwnd, win.title, win.path = 0x1A2B, "Problem 1 - Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    class _Windows:                             # sys as FrontWindow sees it on Windows
        platform = "win32"

        def __getattr__(self, name):
            return getattr(sys, name)

    real_sys, cap.sys = cap.sys, _Windows()
    try:
        front = cap.FrontWindow()
        got = front.read()
        check("on Windows the window in front is read afresh at each look", got == ("Problem 1 - Chrome", "chrome.exe")
              and not front.why, (got, front.why))
        win.title, win.path = "Vault - Bitwarden", r"C:\Program Files\Bitwarden\Bitwarden.exe"
        check("...so a switch to the password manager is seen at the next look", cap.skip_match(front.read(), default))
        # The desktop's windows, by the same rules as the panel's own list
        desk = FakeDesktop([
            {"title": "Docs - Chrome", "exe": "chrome.exe", "pid": 7, "rect": (0, 0, 600, 800)},
            {"title": "", "exe": "Bitwarden.exe", "pid": 8, "rect": (0, 0, 1000, 800)},                       # a helper with no title
            {"title": "Tray - Bitwarden", "exe": "Bitwarden.exe", "pid": 8, "rect": (0, 0, 50, 50), "style": FakeDesktop.TOOL},
            {"title": "Overlay", "exe": "o.exe", "pid": 9, "rect": (0, 0, 1000, 800), "style": FakeDesktop.CLICK_THROUGH},
            {"title": "Other desktop - KeePass", "exe": "KeePass.exe", "pid": 10, "rect": (0, 0, 1000, 800), "cloaked": True},
            {"title": "Minimized - 1Password", "exe": "1Password.exe", "pid": 11, "rect": (0, 0, 1000, 800), "minimized": True},
            {"title": "Hidden - Dashlane", "exe": "Dashlane.exe", "pid": 12, "rect": (0, 0, 1000, 800), "visible": False},
            {"title": "", "cls": "Shell_TrayWnd", "rect": (0, 760, 1000, 800)},                               # covers, with no title
            {"title": "Another tab", "exe": "chrome.exe", "pid": 7, "rect": (100, 100, 200, 200)},
            {"title": "Program Manager", "cls": "Progman", "exe": "explorer.exe", "pid": 13, "rect": (0, 0, 1000, 800)},
        ])
        ctypes.windll = desk.windll
        got = cap._stack_win32()
        check("the windows that can show, top first; hidden, minimized, on another desktop, untitled, tool, overlay and desktop left out",
              [(w[0], w[1]) for w in got] == [("Docs - Chrome", "chrome.exe"), ("", ""), ("Another tab", "chrome.exe")], got)
        check("...each with its rectangle, on the screen's own pixels", got[0][2] == (0, 0, 600, 800) and got[0][3] == (0, 0, 600, 800), got[0])
        check("...one process asked once, and closed again", desk.opened == [7] and desk.closed == 1, (desk.opened, desk.closed))
        desk.windows[1]["rect"] = (0, 0, 300, 800)
        desk.windows[2].update(title="Vault - Bitwarden", rect=(200, 100, 900, 700))
        front = cap.FrontWindow()
        ctypes.windll.user32.GetForegroundWindow = lambda: None
        check("with Chrome in front and the password manager showing beside it: no screen, from the real list",
              cap.skip_now(front, default, SCREEN) and front.limit == "", front.limit)
        desk.windows[1]["rect"] = FULL
        check("...and with Chrome maximized over it, the screen goes on", not cap.skip_now(front, default, SCREEN))
        desk.fail = True
        check("a list that cannot be read: the window in front is all there is, and that is said",
              not cap.skip_now(front, default, SCREEN) and front.limit == "front" and "no list today" in front.why, (front.limit, front.why))
        desk.fail = False
        cap.skip_now(front, default, SCREEN)
        check("...and read again at the next look", front.limit == "" and front.why == "", (front.limit, front.why))
        ctypes.windll = win.windll
    finally:
        cap.sys = real_sys
finally:
    if had is not None:
        ctypes.windll = had                     # as it was
    else:
        del ctypes.windll


# ---------------------------------------------------------------- X11, stood in for
print("\n[X11, stood in for]")
HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class FakeX11:
    """libX11 as _X11Front calls it: windows with their properties, the root's _NET_ACTIVE_WINDOW, and the error handler
    Xlib calls when a window asked about is not there (BadWindow), before the call fails."""
    DISPLAY, OTHER, ROOT, UTF8, STRING = 0x5000, 0x7000, 0x100, 901, 31

    def __init__(self):
        self.atoms, self.props, self.keep, self.freed, self.taken = {}, {self.ROOT: {}}, [], 0, 0
        self.default_calls = []                 # the handler that was in force before: what reached it
        self.default = HANDLER(lambda display, event: self.default_calls.append(display) or 0)
        self.in_force = ctypes.cast(self.default, ctypes.c_void_p).value
        self.stray = set()                      # windows whose read brings an error from another connection with it
        self.rects = {}                         # where each window is on the root
        lib = self.lib = types.SimpleNamespace()

        def XOpenDisplay(name):
            return self.DISPLAY

        def XDefaultRootWindow(display):
            return self.ROOT

        def XInternAtom(display, name, only_if_exists):
            return self.atoms.setdefault(name.decode(), 300 + len(self.atoms))

        def XGetWindowProperty(display, win, atom, offset, length, delete, kind_asked, kind, fmt, n, after, data):
            if win in self.stray:               # another library's error, come in while this one reads (once)
                self.stray.discard(win)
                HANDLER(self.in_force)(self.OTHER, None)
            if win not in self.props:
                HANDLER(self.in_force)(display, None)   # BadWindow: the handler in force is called
                return 1
            name = next(k for k, v in self.atoms.items() if v == atom)
            got = self.props[win].get(name)
            if got is None:
                kind._obj.value, fmt._obj.value, n._obj.value, after._obj.value, data._obj.value = 0, 0, 0, 0, None
                return 0
            kind_of, format_of, raw, count = got
            buf = ctypes.create_string_buffer(raw, max(1, len(raw)))
            self.keep.append(buf)
            self.taken += 1
            kind._obj.value, fmt._obj.value, n._obj.value, after._obj.value = kind_of, format_of, count, 0
            data._obj.value = ctypes.addressof(buf)
            return 0

        def XFree(p):
            self.freed += 1
            return 1

        def XSync(display, discard):
            return 1

        def XSetErrorHandler(handler):
            before = self.in_force
            if handler is None:
                self.in_force = ctypes.cast(self.default, ctypes.c_void_p).value
            elif isinstance(handler, ctypes.c_void_p):
                self.in_force = handler.value
            else:
                self.in_force = ctypes.cast(handler, ctypes.c_void_p).value
            return before

        def XGetGeometry(display, win, root, x, y, w, h, border, depth):
            if win not in self.rects:
                HANDLER(self.in_force)(display, None)   # BadWindow
                return 0
            x0, y0, x1, y1 = self.rects[win]
            w._obj.value, h._obj.value = x1 - x0, y1 - y0
            return 1

        def XTranslateCoordinates(display, win, to, at_x, at_y, x, y, child):
            if win not in self.rects:
                HANDLER(self.in_force)(display, None)
                return 0
            x._obj.value, y._obj.value = self.rects[win][:2]
            return 1

        for f in (XOpenDisplay, XDefaultRootWindow, XInternAtom, XGetWindowProperty, XFree, XSync, XSetErrorHandler, XGetGeometry,
                  XTranslateCoordinates):
            setattr(lib, f.__name__, f)

    def atom(self, name):
        return self.atoms.setdefault(name, 300 + len(self.atoms))

    def text(self, win, name, value, kind=None, codec="utf-8"):
        raw = value.encode(codec)
        self.props.setdefault(win, {})[name] = (kind or self.STRING, 8, raw, len(raw))

    def active(self, win):
        self.props[self.ROOT]["_NET_ACTIVE_WINDOW"] = (33, 32, win.to_bytes(ctypes.sizeof(ctypes.c_long), sys.byteorder), 1)

    def numbers(self, win, name, values, kind=6):
        """A format-32 property, as Xlib hands it over: longs."""
        raw = b"".join(int(v).to_bytes(ctypes.sizeof(ctypes.c_long), sys.byteorder) for v in values)
        self.props.setdefault(win, {})[name] = (kind, 32, raw, len(values))


x = FakeX11()
reader = cap._X11Front(lib=x.lib)
KEEPASS, BROWSER, GONE, STRAY = 0x400001, 0x400002, 0x4000FF, 0x400003
x.text(KEEPASS, "_NET_WM_NAME", "Passwords.kdbx - KeePassXC", kind=x.UTF8)
x.text(KEEPASS, "WM_NAME", "an older title")
x.text(KEEPASS, "WM_CLASS", "keepassxc\0KeePassXC\0")
x.text(BROWSER, "WM_NAME", "Café - Navigateur", codec="latin-1")   # WM_NAME alone, in Latin-1, as older programs write it
x.text(BROWSER, "WM_CLASS", "Navigator\0firefox\0")
check("no window manager that says which window is in front: nothing to go by", reader.read() is None)
x.active(KEEPASS)
got = reader.read()
check("the window in front: _NET_WM_NAME for its title, WM_CLASS for its program",
      got == ("Passwords.kdbx - KeePassXC", "keepassxc KeePassXC"), got)
check("...so KeePassXC in front is skipped", cap.skip_match(got, default))
x.active(BROWSER)
got = reader.read()
check("a window with no _NET_WM_NAME goes by its WM_NAME, read as Latin-1", got == ("Café - Navigateur", "Navigator firefox"), got)
check("every property read is handed back to Xlib (XFree)", x.freed == x.taken, (x.freed, x.taken))
before = x.in_force
x.active(GONE)                                  # the window in front closed between the two reads
got = reader.read()
check("a window gone as it is read is nothing to go by, and the program goes on", got is None, got)
check("...its error taken by this reader, not by the handler before it (Xlib's own ends the program)",
      x.default_calls == [], x.default_calls)
check("...and the handler before it is back in force after the read", x.in_force == before, (x.in_force, before))
x.props[STRAY] = dict(x.props[KEEPASS])
x.stray.add(STRAY)
x.active(STRAY)
got = reader.read()
check("an error of another connection during a read goes on to the handler that was there before",
      x.default_calls == [FakeX11.OTHER] and got == ("Passwords.kdbx - KeePassXC", "keepassxc KeePassXC"), (x.default_calls, got))
# What shows: the window manager's list, bottom first
x = FakeX11()
reader = cap._X11Front(lib=x.lib)
check("a window manager that keeps no list: there is no list to go by", reader.stack() is None)
reader.read()
check("...and one that does not say which is in front is told from one with nothing in front", reader.says_front is False)
x.active(BROWSER)
x.text(BROWSER, "WM_NAME", "Docs", codec="latin-1")
reader.read()
check("...which does say", reader.says_front is True)
SHUT, AWAY, ALL, THEMED = 0x400010, 0x400011, 0x400012, 0x400013
for w, name in ((KEEPASS, "Vault - KeePassXC"), (SHUT, "Minimized - Bitwarden"), (AWAY, "Other desktop - 1Password"), (ALL, "Pinned"), (THEMED, "Themed")):
    x.text(w, "_NET_WM_NAME", name, kind=x.UTF8)
x.rects.update({BROWSER: (0, 0, 600, 800), KEEPASS: (100, 100, 900, 700), SHUT: (0, 0, 1000, 800), AWAY: (0, 0, 1000, 800), ALL: (5, 5, 50, 50), THEMED: (100, 100, 300, 300)})
x.numbers(x.ROOT, "_NET_CURRENT_DESKTOP", [1])
for w in (BROWSER, KEEPASS, SHUT):
    x.numbers(w, "_NET_WM_DESKTOP", [1])
x.numbers(AWAY, "_NET_WM_DESKTOP", [2])
x.numbers(ALL, "_NET_WM_DESKTOP", [0xFFFFFFFF])
x.numbers(SHUT, "_NET_WM_STATE", [x.atom("_NET_WM_STATE_HIDDEN")], kind=4)
x.numbers(BROWSER, "_NET_FRAME_EXTENTS", [2, 2, 30, 4])     # left, right, top, bottom
x.numbers(THEMED, "_GTK_FRAME_EXTENTS", [10, 20, 30, 40])
x.numbers(x.ROOT, "_NET_CLIENT_LIST_STACKING", [KEEPASS, SHUT, AWAY, THEMED, ALL, GONE, BROWSER], kind=33)
got = reader.stack()
check("top first, with those minimized or on another desktop left out, and one gone as it is read",
      [w[0] for w in got] == ["Docs", "Pinned", "Themed", "Vault - KeePassXC"], got)
check("...its rectangle its own area, and what it covers with its frame too", got[0][2] == (0, 0, 600, 800) and got[0][3] == (-2, -30, 602, 804), got[0])
check("...a toolkit's own shadow is not part of it", got[2][2] == (110, 130, 280, 260), got[2])
check("...so KeePassXC beside the window with the focus stops the screen", cap.skip_visible(got, default, SCREEN))
x.rects[BROWSER] = (0, 0, 1000, 800)
check("...and under it, maximized, it does not", not cap.skip_visible(reader.stack(), default, SCREEN))
check("every property read is handed back here too (XFree)", x.freed == x.taken, (x.freed, x.taken))
check("...and the error of the window gone taken by this reader", x.default_calls == [], x.default_calls)

# A read that broke, and a display that was not there yet: tried again, not given up on for the rest of the run
print("\n[a read that breaks]")
real_x11, tries = cap._X11Front, []


class Flaky:
    """_X11Front, stood in for: raises as long as `broken` says so."""
    broken, says_front = True, True

    def read(self):
        if Flaky.broken:
            raise OSError("the display hiccuped")
        return VAULT

    def stack(self):
        return []


saved_env = {k: os.environ.pop(k, None) for k in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")}
cap._X11Front = lambda: Flaky()
try:
    front = cap.FrontWindow()
    check("a read that breaks counts as nothing known", front.read() is None and "hiccuped" in front.broke, front.broke)
    front.stack()
    Flaky.broken = False
    check("...and the next look reads again: one exception does not switch this off", front.read() == VAULT and front.broke == "", front.broke)
    check("...with nothing left to say", front.why == "" and front.limit == "", (front.why, front.limit))

    def no_display():
        tries.append(1)
        raise OSError("no X11 display")
    cap._X11Front = no_display
    front = cap.FrontWindow()
    front.read(), front.stack()
    check("no display: nothing can be skipped, and that is said", front.limit == "none" and "no X11 display" in front.why, (front.limit, front.why))
    front.read(), front.read()
    check("...the display not asked for at every look", len(tries) == 1, len(tries))
    front.opened -= cap.SKIP_REOPEN_SEC + 1
    cap._X11Front = lambda: Flaky()
    check("...but asked for again after a while, and then read", front.read() == VAULT, front.why)
    front.stack()
    check("...with nothing left to say", front.limit == "" and front.why == "", (front.limit, front.why))

    class Silent(Flaky):
        says_front = False

        def read(self):
            return None

        def stack(self):
            return None
    cap._X11Front = lambda: Silent()
    front = cap.FrontWindow()
    front.read(), front.stack()
    check("a window manager that keeps neither the list nor the window in front: nothing can be skipped, and that is said",
          front.limit == "none" and bool(front.why), (front.limit, front.why))

    class FrontOnly(Silent):
        says_front = True
    cap._X11Front = lambda: FrontOnly()
    front = cap.FrontWindow()
    front.read(), front.stack()
    check("one that says which is in front and keeps no list: that window alone counts, and that is said", front.limit == "front" and bool(front.why), (front.limit, front.why))
finally:
    cap._X11Front = real_x11
    for k, v in saved_env.items():
        if v is not None:
            os.environ[k] = v


# ---------------------------------------------------------------- X11 on a private display
print("\n[X11 on a private display]")


def xvfb():
    """A private Xvfb display, its number, and the process to stop; None where there is no Xvfb or no libX11."""
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


up = xvfb()
if up is None:
    NOTES.append("the X11 reading on a private display was not tried: no Xvfb or no libX11 here")
else:
    number, proc = up
    saved_display = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = f":{number}"
    try:
        c = ctypes
        X = c.CDLL(c.util.find_library("X11"))     # the suite's own connection: it makes the windows and says which is in front
        X.XOpenDisplay.restype, X.XOpenDisplay.argtypes = c.c_void_p, [c.c_char_p]
        X.XDefaultRootWindow.restype, X.XDefaultRootWindow.argtypes = c.c_ulong, [c.c_void_p]
        X.XInternAtom.restype, X.XInternAtom.argtypes = c.c_ulong, [c.c_void_p, c.c_char_p, c.c_int]
        X.XCreateSimpleWindow.restype = c.c_ulong
        X.XCreateSimpleWindow.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_uint, c.c_ulong, c.c_ulong]
        X.XChangeProperty.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_ulong, c.c_int, c.c_int, c.c_void_p, c.c_int]
        X.XDestroyWindow.argtypes = [c.c_void_p, c.c_ulong]
        X.XSync.argtypes = [c.c_void_p, c.c_int]
        d = X.XOpenDisplay(f":{number}".encode())
        root = X.XDefaultRootWindow(d)
        atom = lambda name: X.XInternAtom(d, name.encode(), False)   # noqa: E731

        def window(title_utf8=None, wm_name=None, wm_class=b"", at=(0, 0, 200, 100)):
            w = X.XCreateSimpleWindow(d, root, at[0], at[1], at[2], at[3], 0, 0, 0)
            if title_utf8 is not None:
                raw = title_utf8.encode()
                X.XChangeProperty(d, w, atom("_NET_WM_NAME"), atom("UTF8_STRING"), 8, 0, c.c_char_p(raw), len(raw))
            if wm_name is not None:
                X.XChangeProperty(d, w, 39, 31, 8, 0, c.c_char_p(wm_name), len(wm_name))   # WM_NAME, STRING
            X.XChangeProperty(d, w, 67, 31, 8, 0, c.c_char_p(wm_class), len(wm_class))     # WM_CLASS, STRING
            return w

        def in_front(w):
            data = (c.c_long * 1)(w)
            X.XChangeProperty(d, root, atom("_NET_ACTIVE_WINDOW"), 33, 32, 0, c.cast(data, c.c_void_p), 1)   # XA_WINDOW
            X.XSync(d, False)

        keepass = window("Passwords.kdbx - KeePassXC", b"Passwords.kdbx - KeePassXC", b"keepassxc\0KeePassXC\0")
        editor = window(None, b"capture.py - Visual Studio Code", b"code\0Code\0")
        private = window("New Private Window - Mozilla Firefox Private Browsing", None, b"Navigator\0firefox\0")
        X.XSync(d, False)
        reader = cap._X11Front()                   # libX11 itself, on the display $DISPLAY names
        in_front(keepass)
        got = reader.read()
        check("libX11 on a private display: the window in front, its title and its program",
              got == ("Passwords.kdbx - KeePassXC", "keepassxc KeePassXC"), got)
        in_front(editor)
        got = reader.read()
        check("...a window with WM_NAME alone", got == ("capture.py - Visual Studio Code", "code Code"), got)
        check("...which is not skipped, while KeePassXC and a private window are",
              not cap.skip_match(got, default) and cap.skip_match(("Passwords.kdbx - KeePassXC", "keepassxc KeePassXC"), default))
        in_front(private)
        check("...the private window read from its _NET_WM_NAME is skipped", cap.skip_match(reader.read(), default))
        # What shows, from a list the suite keeps as a window manager would: a real X server's places and properties
        mine = {"left": 0, "top": 0, "width": 640, "height": 480}

        def stacking(*ws):
            data = (c.c_long * len(ws))(*ws)
            X.XChangeProperty(d, root, atom("_NET_CLIENT_LIST_STACKING"), 33, 32, 0, c.cast(data, c.c_void_p), len(ws))
            X.XSync(d, False)

        check("libX11 with no list kept: nothing to go by", reader.stack() is None)
        vault = window("Passwords.kdbx - KeePassXC", None, b"keepassxc\0KeePassXC\0", at=(100, 100, 300, 200))
        cover = window(None, b"Editor", b"code\0Code\0", at=(0, 0, 640, 480))
        side = window(None, b"Side", b"code\0Code\0", at=(0, 0, 200, 480))
        stacking(vault, cover)
        got = reader.stack()
        check("libX11: top first, each at its place on the root",
              [(w[0], w[2]) for w in got] == [("Editor", (0, 0, 640, 480)), ("Passwords.kdbx - KeePassXC", (100, 100, 400, 300))], got)
        check("...wholly under a window, it stops nothing", not cap.skip_visible(got, default, mine))
        stacking(vault, side)
        check("...beside one, with the other in front, it stops the screen", cap.skip_visible(reader.stack(), default, mine))
        closing = window("Closing", None, b"x\0X\0", at=(0, 0, 10, 10))
        stacking(vault, side, closing)
        X.XDestroyWindow(d, closing)
        X.XSync(d, False)
        probe = ("import importlib.util, sys\n"
                 "spec = importlib.util.spec_from_file_location('cap', sys.argv[1]); cap = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(cap)\n"
                 "print([w[0] for w in cap._X11Front().stack()])\n")
        run = subprocess.run([sys.executable, "-c", probe, CAPTURE], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "DISPLAY": f":{number}"})
        check("...one that closed as the list was read is left out, and the program goes on",
              run.returncode == 0 and run.stdout.strip() == "['Side', 'Passwords.kdbx - KeePassXC']",
              f"exit {run.returncode}: {run.stdout[-200:]!r} {run.stderr[-300:]!r}")
        # A window in front that is gone: BadWindow from the X server. Read in a process of its own, so that if Xlib's own
        # handler ended it (as it does without this reader's), this suite would see that and go on
        gone = window("soon gone", None, b"gone\0Gone\0")
        in_front(gone)
        X.XDestroyWindow(d, gone)
        X.XSync(d, False)
        probe = ("import ctypes, ctypes.util, importlib.util, sys\n"
                 "spec = importlib.util.spec_from_file_location('cap', sys.argv[1]); cap = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(cap)\n"
                 "lib = ctypes.CDLL(ctypes.util.find_library('X11')); lib.XSetErrorHandler.restype = ctypes.c_void_p\n"
                 "first = lib.XSetErrorHandler(None); lib.XSetErrorHandler(ctypes.c_void_p(first))\n"
                 "r = cap._X11Front(); print(repr(r.read())); print(repr(r.read()))\n"
                 "after = lib.XSetErrorHandler(None); lib.XSetErrorHandler(ctypes.c_void_p(after)); print(first == after)\n")
        run = subprocess.run([sys.executable, "-c", probe, CAPTURE], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "DISPLAY": f":{number}"})
        check("a window in front that closed as it was read: nothing to go by, twice, and the program goes on",
              run.returncode == 0 and run.stdout.split("\n")[:2] == ["None", "None"],
              f"exit {run.returncode}: {run.stdout[-200:]!r} {run.stderr[-300:]!r}")
        check("...with the error handler before it back in force", run.stdout.split("\n")[2:3] == ["True"], run.stdout[-200:])
    finally:
        if saved_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = saved_display
        proc.kill()                                 # the private display, stopped by its own process
        proc.wait()
# A Wayland session tells other programs nothing of its windows: said, and never read
saved = {k: os.environ.get(k) for k in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")}
os.environ["XDG_SESSION_TYPE"] = "wayland"
front = cap.FrontWindow()
check("in a Wayland session no window is read, and that is said", front.why == "Wayland" and front.read() is None and front.stack() is None
      and front.limit == "none", (front.why, front.limit))
for k, v in saved.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v


# ---------------------------------------------------------------- macOS, stood in for
print("\n[macOS, stood in for]")


class FakeQuartz:
    """The window server's list as Quartz hands it over, front first, keyed by the constants' own names."""
    kCGWindowListOptionOnScreenOnly, kCGWindowListExcludeDesktopElements, kCGNullWindowID = 1, 16, 0
    kCGWindowLayer, kCGWindowAlpha, kCGWindowBounds = "kCGWindowLayer", "kCGWindowAlpha", "kCGWindowBounds"
    kCGWindowName, kCGWindowOwnerName = "kCGWindowName", "kCGWindowOwnerName"

    def __init__(self, windows):
        self.windows, self.asked = windows, []

    def CGWindowListCopyWindowInfo(self, options, relative):
        self.asked.append((options, relative))
        return self.windows


def mac_window(owner, title, x, y, w, h, layer=0, alpha=1.0):
    return {"kCGWindowOwnerName": owner, "kCGWindowName": title, "kCGWindowLayer": layer, "kCGWindowAlpha": alpha,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


class _Mac:                                     # sys as FrontWindow sees it on macOS
    platform = "darwin"

    def __getattr__(self, name):
        return getattr(sys, name)


MAC_SCREEN = {"left": 0, "top": 0, "width": 1512, "height": 982}
quartz = FakeQuartz([
    mac_window("Window Server", "Menubar", 0, 0, 1512, 33, layer=24),
    mac_window("Google Chrome", "Problem 1 - Google Chrome", 0, 33, 900, 900),
    mac_window("Bitwarden", "", 700, 100, 600, 700),          # no title until Screen Recording is allowed
    mac_window("Dock", "Dock", 0, 900, 1512, 82, layer=20),
    mac_window("Notes", "", 10, 10, 1, 1),                     # a helper's point on the screen
    mac_window("Overlay", "Clear", 0, 0, 1512, 982, alpha=0.0),
])
sys.modules["Quartz"] = quartz
real_sys, cap.sys = cap.sys, _Mac()
try:
    default = words(*cap.SKIP_WINDOWS)
    got = cap._windows_mac()
    check("on macOS the windows of the normal layer, front first: the menu bar, the Dock, a point and a see-through one "
          "left out", [(w[0], w[1]) for w in got] == [("Problem 1 - Google Chrome", "Google Chrome"), ("", "Bitwarden")], got)
    check("...each in the points the monitors are given in", got[1][2] == (700.0, 100.0, 1300.0, 800.0) == got[1][3], got)
    check("...from the list of the windows on screen, without the desktop's own", quartz.asked[-1] == (17, 0), quartz.asked)
    front = cap.FrontWindow()
    check("the window in front is the first of them", front.read() == ("Problem 1 - Google Chrome", "Google Chrome"))
    check("...and the password manager showing beside it stops the screen, by its app's name alone",
          cap.skip_now(front, default, MAC_SCREEN) and not front.limit and not front.why, (front.limit, front.why))
    quartz.windows = [w for w in quartz.windows if w["kCGWindowOwnerName"] != "Bitwarden"]
    check("...and once it is closed the screen goes out again", not cap.skip_now(front, default, MAC_SCREEN))
    quartz.windows.insert(1, mac_window("Google Chrome", "Sidenote panel - Google Chrome", 900, 33, 612, 900))
    rects = cap.window_rects(MAC_SCREEN)
    check("the panel's own window is found by its title, as on Windows, as a part of the screen",
          rects is not None and rects[1] == [0] and rects[0][0] == [round(900 / 1512, 4), round(33 / 982, 4), 1.0,
                                                                    round(933 / 982, 4)], rects)
    quartz.windows = None
    broken = cap.FrontWindow()
    check("a list that cannot be read skips nothing, and says so",
          not cap.skip_now(broken, default, MAC_SCREEN) and broken.limit == "none" and "no list of windows" in broken.why,
          (broken.limit, broken.why))
    check("...and the panel's window is then not looked for", cap.window_rects(MAC_SCREEN) is None)
finally:
    cap.sys = real_sys
    del sys.modules["Quartz"]


# ---------------------------------------------------------------- the screen loop
print("\n[the screen loop]")
from PIL import Image, ImageDraw  # noqa: E402


def screen(colour, mark=0):
    """A made-up screen: a block of colour with a few lines of 'text' on it, `mark` moving one of them."""
    img = Image.new("RGB", (800, 450), colour)
    d = ImageDraw.Draw(img)
    for i in range(8):
        d.rectangle([40, 40 + i * 40, 300 + (i * 53 + mark * 97) % 400, 56 + i * 40], fill=(20, 20, 20))
    return img


class FakeGrab:
    def __init__(self, img):
        self.size = img.size
        self.bgra = img.convert("RGBA").tobytes("raw", "BGRA")


class FakeMSS:
    frames: list = []
    pos = 0

    def __init__(self):
        self.monitors = [{"left": 0, "top": 0, "width": 800, "height": 450}, {"left": 0, "top": 0, "width": 800, "height": 450}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def grab(self, mon):
        img = FakeMSS.frames[min(FakeMSS.pos, len(FakeMSS.frames) - 1)]
        FakeMSS.pos += 1
        return FakeGrab(img)


class Front:
    """FrontWindow, stood in for: the window in front is what the suite says it is now (`now`), or what `plan` gives,
    one answer a read and the last for ever after."""
    now, plan, reads, on_screen, limit = ("Problem 1 - Chrome", "chrome.exe"), None, 0, [], ""

    def __init__(self):
        self.why, self.x11 = "", None

    def stack(self):
        return Front.on_screen

    def read(self):
        Front.reads += 1
        if Front.plan is not None:
            return Front.plan[min(Front.reads - 1, len(Front.plan) - 1)]
        return Front.now


class Sender:
    """What the loops read and write of the real Sender, with every message kept."""

    def __init__(self, skip=SERVER_DEFAULT):
        self.wants = {"screen": True, "audio": True, "monitor": 1, "stitch": False, "skip_windows": words(*skip)}
        self.caps, self.sent, self.epoch, self.connected = {}, [], 0, True
        self.lock = threading.Lock()

    def keepalive(self):
        pass

    def set_caps(self, **kw):
        self.caps.update(kw)
        self.send({"type": "caps", **self.caps})

    def send(self, msg):
        with self.lock:
            self.sent.append(msg)

    def of(self, kind):
        with self.lock:
            return [m for m in self.sent if m.get("type") == kind]


def colour_of(msg):
    import base64
    return Image.open(io.BytesIO(base64.b64decode(msg["data"]))).convert("RGB").getpixel((790, 440))


class ByThread:
    """sys.stdout that keeps what a loop's thread prints (its log) apart from this suite's own lines, which the main
    thread prints meanwhile: redirect_stdout is for the whole process, and it took the checks' lines into the log."""

    def __init__(self, real):
        self.real, self.logs = real, {}

    def write(self, text):
        return self.logs.get(threading.get_ident(), self.real).write(text)

    def flush(self):
        self.real.flush()


cap.window_rects = lambda mon, limit=40: ([], [])   # no window list on this machine
cap._grabber = lambda: FakeMSS
real_front, cap.FrontWindow = cap.FrontWindow, Front
STDOUT = sys.stdout = ByThread(sys.stdout)
ARGS = dict(stable_polls=1, settle=0.3, threshold=0.1, fps=50.0, max_width=1600, monitor=None, stitch=None, once=False,
            no_auto_stitch=True, log="")


def start(sender, once=False):
    stop = threading.Event()
    out = io.StringIO()

    def run():
        STDOUT.logs[threading.get_ident()] = out   # this thread's lines are the loop's log
        cap.screen_loop(sender, stop, types.SimpleNamespace(**{**ARGS, "once": once}))
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return stop, thread, out


def until(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


BLUE, GREEN, RED = (30, 90, 200), (40, 160, 80), (200, 40, 40)
FakeMSS.frames, FakeMSS.pos, Front.plan, Front.now = [screen(BLUE)], 0, None, ("Problem 1 - Chrome", "chrome.exe")
s = Sender()
stop, thread, out = start(s)
check("a normal window in front: the screen is sent", until(lambda: len(s.of("frame")) == 1), len(s.of("frame")))
Front.now = BITWARDEN
check("the password manager in front: the program says so (caps)", until(lambda: s.caps.get("skipping") is True), s.caps)
grabs, frames = FakeMSS.pos, len(s.of("frame"))
time.sleep(0.5)                                 # 25 polls at 50 a second
check("...and grabs nothing and sends nothing while it is there", FakeMSS.pos == grabs and len(s.of("frame")) == frames,
      (FakeMSS.pos - grabs, len(s.of("frame")) - frames))
Front.now = ("Problem 1 - Chrome", "chrome.exe")
check("gone from the front: the program says so", until(lambda: s.caps.get("skipping") is False), s.caps)
check("...and looks at the screen again", until(lambda: FakeMSS.pos > grabs + 3), FakeMSS.pos - grabs)
time.sleep(0.3)
check("the same problem come back to is not a new screen: the change detection kept what it saw",
      len(s.of("frame")) == 1, len(s.of("frame")))
FakeMSS.frames = [screen(GREEN, 1)]
check("a new screen after it is sent", until(lambda: len(s.of("frame")) == 2) and colour_of(s.of("frame")[-1]) == GREEN,
      len(s.of("frame")))
Front.now = ("Login | Bitwarden Web Vault", "firefox.exe")
check("a word in the title alone stops it too", until(lambda: s.caps.get("skipping") is True), s.caps)
Front.now = ("Problem 2", "1password.exe")
time.sleep(0.2)
check("...and one in the program's name alone keeps it stopped", s.caps.get("skipping") is True, s.caps)
Front.now = ("Problem 2", "Code.exe")
check("...until neither has one", until(lambda: s.caps.get("skipping") is False), s.caps)
s.wants["skip_windows"] = words("problem")       # what a control message with the panel's own words does
check("the panel's own words are what is matched", until(lambda: s.caps.get("skipping") is True), s.caps)
s.wants["skip_windows"] = []
check("...and with none, nothing is skipped", until(lambda: s.caps.get("skipping") is False), s.caps)
stop.set()
thread.join(timeout=3)
said = out.getvalue()
check("the log says that a skip started and ended", said.count(cap.t("A window to skip is on screen: no screen is sent while it is")) == 3
      and said.count(cap.t("The window to skip is no longer on screen: capturing the screen again")) == 3,
      said[-600:])
check("...and never which window: no title and no program in it",
      not any(w in said for w in ("Bitwarden", "bitwarden", "1password", "Login", "Code.exe", "Problem 2")), said[-600:])
check("...nor in what was sent", not any(any(w in json.dumps(m) for w in ("Bitwarden", "Login", "1password"))
                                         for m in s.sent if m.get("type") != "frame"), [m for m in s.sent if m.get("type") != "frame"])

# A window brought to the front while the screen is being grabbed: that grab is not sent. The screen is red while it
# is in front, and settled, so without the look after the grab it would have gone out.
FakeMSS.frames, FakeMSS.pos, Front.reads = [screen(RED), screen(RED)] + [screen(BLUE)] * 20, 0, 0
Front.plan = [Front.now] * 3 + [BITWARDEN, BITWARDEN] + [("Problem 1 - Chrome", "chrome.exe")]
s = Sender()
stop, thread, out = start(s)
until(lambda: len(s.of("frame")) >= 1)
stop.set()
thread.join(timeout=3)
sent = [colour_of(m) for m in s.of("frame")]
check("a window brought to the front during a grab: that grab is dropped", sent and RED not in sent, sent)
Front.plan = None

# Asked for one screen with a window to skip in front: none is sent, and it says why
FakeMSS.frames, FakeMSS.pos, Front.now = [screen(BLUE)], 0, BITWARDEN
s = Sender()
stop, thread, out = start(s, once=True)
thread.join(timeout=5)
check("--once with a window to skip in front: nothing is sent, the loop ends and says why",
      not thread.is_alive() and not s.of("frame") and cap.t("A window to skip is on screen, so nothing was sent (--once)") in out.getvalue(),
      out.getvalue()[-300:])
# Behind the window with the focus: the loop goes by what shows, not by what is in front alone
Front.now = ("Problem 1 - Chrome", "chrome.exe")
Front.on_screen = [shown(Front.now, (0, 0, 400, 800)), shown(BITWARDEN, (300, 0, 800, 450))]
FakeMSS.frames, FakeMSS.pos = [screen(BLUE)], 0
s = Sender()
stop, thread, out = start(s)
check("a window to skip showing behind the one with the focus: the program says so", until(lambda: s.caps.get("skipping") is True), s.caps)
time.sleep(0.3)
check("...and grabs nothing and sends nothing", FakeMSS.pos == 0 and not s.of("frame"), (FakeMSS.pos, len(s.of("frame"))))
Front.on_screen = [shown(Front.now, (0, 0, 1000, 800)), shown(BITWARDEN, (300, 0, 800, 450))]
check("covered wholly, the screen goes out again", until(lambda: len(s.of("frame")) == 1 and s.caps.get("skipping") is False), s.caps)
FakeMSS.frames = [screen(GREEN, 1), screen(GREEN, 1)]
Front.on_screen = [shown(Front.now, (0, 0, 400, 800)), shown(BITWARDEN, (300, 0, 800, 450))]
stop.set()
thread.join(timeout=3)
check("...and what the program told the server says nothing of the window", not any("Bitwarden" in json.dumps(m) for m in s.sent if m.get("type") != "frame"), s.caps)
check("...and neither does its log", "Bitwarden" not in out.getvalue(), out.getvalue()[-300:])
Front.on_screen = []
# Come to show as the screen was being grabbed, behind the focus: that grab is dropped too. The screen is red until then, and
# settled, so without the look after the grab it would have gone out.
FakeMSS.frames, FakeMSS.pos = [screen(RED), screen(RED)] + [screen(BLUE)] * 40, 0
calls = {"n": 0}


def appears_during_a_grab():
    calls["n"] += 1
    return [shown(Front.now, (0, 0, 400, 800)), shown(BITWARDEN, (300, 0, 800, 450))] if 4 <= calls["n"] <= 7 else []


Front.stack = lambda self: appears_during_a_grab()
s = Sender()
stop, thread, out = start(s)
until(lambda: len(s.of("frame")) >= 1)
stop.set()
thread.join(timeout=3)
Front.stack = lambda self: Front.on_screen
sent = [colour_of(m) for m in s.of("frame")]
check("a window that comes to show during a grab: that grab is dropped", sent and RED not in sent, sent)
# Where the windows cannot be read, nothing is skipped, that is said once, and the server hears what that leaves
cap.FrontWindow = type("Unreadable", (), {"__init__": lambda self: setattr(self, "why", "Wayland"), "read": lambda self: None, "stack": lambda self: None, "limit": "none"})
FakeMSS.frames, FakeMSS.pos = [screen(BLUE)], 0
s = Sender()
stop, thread, out = start(s)
until(lambda: len(s.of("frame")) == 1)
time.sleep(0.2)
stop.set()
thread.join(timeout=3)
check("where the windows cannot be read, the screen is sent and that is said once",
      len(s.of("frame")) == 1 and out.getvalue().count("Wayland") == 1, out.getvalue()[-300:])
check("...and the server is told, for the panel's card", s.caps.get("skip_limit") == "none" and sum(m.get("skip_limit") == "none" for m in s.of("caps")) >= 1, s.caps)
cap.FrontWindow = type("FrontOnly", (), {"__init__": lambda self: setattr(self, "why", "no list of windows"), "read": lambda self: None, "stack": lambda self: None, "limit": "front"})
s = Sender()
stop, thread, out = start(s)
until(lambda: s.caps.get("skip_limit") == "front")
s.wants["skip_windows"] = []
check("with no words there is nothing to look for, and nothing to warn of", until(lambda: s.caps.get("skip_limit") == ""), s.caps)
stop.set()
thread.join(timeout=3)
check("...one that lists only the window in front is told apart in the log", cap.t("The windows behind the one in front cannot be listed here ({why}), so only that one is skipped", why="no list of windows") in out.getvalue(), out.getvalue()[-300:])
# One read that breaks in the real FrontWindow, in the loop: said, and the skip works again at the next look
broken = {"left": 2}


def read_breaks(self):
    if broken["left"]:
        broken["left"] -= 1
        raise OSError("the display hiccuped")
    return BITWARDEN


cap.FrontWindow = real_front
class FakeReader:                               # noqa: E301
    says_front = True
    read = read_breaks

    def stack(self):
        return []


saved_env = {k: os.environ.pop(k, None) for k in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")}
real_x11, cap._X11Front = cap._X11Front, FakeReader
FakeMSS.frames, FakeMSS.pos = [screen(BLUE)], 0
s = Sender()
stop, thread, out = start(s)
check("a read that breaks does not end the skip for the run: the password manager is seen at a later look", until(lambda: s.caps.get("skipping") is True), s.caps)
stop.set()
thread.join(timeout=3)
cap._X11Front = real_x11
for k, v in saved_env.items():
    if v is not None:
        os.environ[k] = v
cap.FrontWindow = Front


# ---------------------------------------------------------------- sound goes on
print("\n[sound goes on]")


class Rec:
    def record(self, numframes):
        time.sleep(0.05)                        # the device's second, shortened
        import numpy as np
        return np.zeros((numframes, 2), dtype="float32")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Mic:
    name = "fake speaker"

    def recorder(self, samplerate, channels, blocksize):
        return Rec()


sys.modules["soundcard"] = types.SimpleNamespace(default_speaker=lambda: Mic(), get_microphone=lambda name, include_loopback: Mic())
FakeMSS.frames, FakeMSS.pos, Front.now = [screen(BLUE)], 0, BITWARDEN
s = Sender()
stop, screen_thread, _ = start(s)
quiet = io.StringIO()


def sound():
    STDOUT.logs[threading.get_ident()] = quiet     # its lines are its log, not this suite's
    cap.audio_loop(s, stop, types.SimpleNamespace(audio_device=None))


sound_thread = threading.Thread(target=sound, daemon=True)
sound_thread.start()
time.sleep(1.2)
stop.set()
for th in (screen_thread, sound_thread):
    th.join(timeout=3)
check("with a window to skip in front, sound is still sent and the screen is not",
      len(s.of("audio")) >= 5 and not s.of("frame") and s.caps.get("skipping") is True, (len(s.of("audio")), len(s.of("frame"))))


# ---------------------------------------------------------------- the control message
print("\n[the control message]")
real = cap.Sender("ws://127.0.0.1:1/ingest")
out = io.StringIO()
with redirect_stdout(out):
    real._on_message(json.dumps({"type": "control", "screen": True, "skip_windows": ["  Bank ", "", "Mail"]}))
check("the server's words are taken from control, as the program matches them", real.wants["skip_windows"] == ["bank", "mail"],
      real.wants["skip_windows"])
check("...and the log says how many, not which", "2 word(s)" in out.getvalue() and "Bank" not in out.getvalue(), out.getvalue())
with redirect_stdout(io.StringIO()):
    real._on_message(json.dumps({"type": "control", "screen": True}))   # an older server: no words in it
check("a control message without them (an older server) leaves the words held", real.wants["skip_windows"] == ["bank", "mail"])
with redirect_stdout(io.StringIO()):
    real._on_message(json.dumps({"type": "control", "skip_windows": "Bank"}))
    real._on_message(json.dumps({"type": "control", "skip_windows": [1, 2]}))
check("...as does a value that is not a list of words", real.wants["skip_windows"] == ["bank", "mail"], real.wants["skip_windows"])
with redirect_stdout(io.StringIO()):
    real._on_message(json.dumps({"type": "control", "skip_windows": []}))
check("an empty list from the panel skips nothing", real.wants["skip_windows"] == [])


# ---------------------------------------------------------------- the tray
print("\n[the tray]")


class Item:
    def __init__(self, text, action=None, checked=None, enabled=True, default=False):
        self.text, self.action, self.checked, self.enabled = text, action, checked, enabled


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = [i for i in items if isinstance(i, Item)]


class Icon:
    def __init__(self, name, image, title, menu):
        self.menu = menu

    def run(self):
        threading.Event().wait()                # stands in for the desktop's message loop: never returns by itself

    def update_menu(self):
        pass

    def stop(self):
        pass


sys.modules["pystray"] = types.SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=Item)
cap.tray_image = lambda: None                   # no drawing needed for a menu nobody sees
s = Sender()
stop = threading.Event()
icon = cap.start_tray(s, stop, types.SimpleNamespace(server="ws://127.0.0.1:8777/ingest", no_audio=False))
state = lambda: next(r for r in cap.tray_rows(icon.menu) if not r["sep"] and not r["enabled"] and r["checked"] is None)   # noqa: E731
row = state()
check("the tray's state line while nothing is skipped", row["text"] == "캡처 중: 화면 · 소리" and row["tone"] == "on", row)
s.caps["skipping"] = True
row = state()
check("...while a window is skipped: 'Skipped window' in the warn tone, without naming it", row["text"] == "창 건너뜀"
      and row["tone"] == "warn", row)
s.wants["screen"] = False
row = state()
check("...the screen switched off says what is taken instead", row["text"] == "캡처 중: 소리" and row["tone"] == "on", row)
s.wants["screen"], s.connected = True, False
row = state()
check("...and no server says that first", row["tone"] == "down", row)
s.connected = True
stop.set()
check("the drawn menu has the warn tone, in the right column's dark warning colour",
      '"warn": WARN' in cap.TRAY_MENU and 'WARN = "#ffb066"' in cap.TRAY_MENU
      and '.rail { --warn: #ffb066;' in (ROOT / "panel" / "index.html").read_text(encoding="utf-8"))
real_lang, cap.LANG = cap.LANG, "en"
check("in English the state line reads 'Skipped window'", cap.t("Skipped window") == "Skipped window")
cap.LANG = real_lang


# ---------------------------------------------------------------- the server
print("\n[the server]")
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server.settings import SETTINGS, Settings  # noqa: E402

ORIGIN = {"origin": "http://127.0.0.1:8777"}


class Reader:
    """Every message a socket gets, read in a thread, so a wait that comes to nothing ends instead of hanging."""

    def __init__(self, ws):
        self.ws, self.msgs = ws, []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.msgs.append(json.loads(self.ws.receive_text()))
        except Exception:
            pass

    def wait(self, pred, timeout=8.0, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in list(self.msgs[after:]):
                if pred(m):
                    return m
            time.sleep(0.05)
        return None


with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    with client.websocket_connect("ws://127.0.0.1:8777/ingest") as ing, \
            client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as pws:
        ing.send_text(json.dumps({"type": "hello", "info": "capture/win32", "screen": True, "audio": True, "no_audio": False,
                                  "monitor": 1, "flags": {}}))
        prog, panel = Reader(ing), Reader(pws)
        first = prog.wait(lambda m: m.get("type") == "control")
        check("the capture program is told the words on connect, the default list to begin with",
              bool(first) and first.get("skip_windows") == SERVER_DEFAULT, first)
        meta = panel.wait(lambda m: m.get("type") == "settings" and "meta" in m)
        item = next((i for i in (meta or {}).get("meta", {}).get("items", []) if i["key"] == "skip_windows"), {})
        check("the panel gets the setting in the Screen section, as free words, in Korean",
              item.get("section") == "screen" and item.get("kind") == "words" and item.get("label") == "건너뛸 창"
              and "Wayland" in item.get("help", "") and "소리" in item.get("help", ""), item)
        n = len(prog.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "skip_windows", "value": ["  Bank ", "", "Mail", "   "]}))
        got = prog.wait(lambda m: m.get("type") == "control" and m.get("skip_windows") != SERVER_DEFAULT, after=n)
        check("a change in the panel reaches the program at once, each word trimmed and the empty ones dropped",
              bool(got) and got.get("skip_windows") == ["Bank", "Mail"], got)
        back = panel.wait(lambda m: m.get("type") == "settings" and "skip_windows" in (m.get("values") or {}) and "meta" not in m)
        check("...and every panel gets the words as they are kept", bool(back) and back["values"]["skip_windows"] == ["Bank", "Mail"], back)
        file = Path(os.environ["SIDENOTE_LOG_DIR"]) / ".settings.json"
        kept = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
        check("...kept in .settings.json like every setting", kept.get("skip_windows") == ["Bank", "Mail"], kept)
        for value, why in ((["w"] * 51, "51 words"), (["x" * 61], "a word of 61 characters"), ("Bank, Mail", "a string"),
                           ([1, "Mail"], "a number among them"), (None, "nothing")):
            n, m = len(prog.msgs), len(panel.msgs)
            pws.send_text(json.dumps({"type": "setting", "key": "skip_windows", "value": value}))
            note = panel.wait(lambda x: x.get("type") == "notice", after=m)
            stored = panel.wait(lambda x: x.get("type") == "settings" and "skip_windows" in (x.get("values") or {}), after=m)
            check(f"refused: {why}, with a notice, the kept words sent back, nothing told the program",
                  bool(note) and note.get("level") == "warn" and bool(stored) and stored["values"]["skip_windows"] == ["Bank", "Mail"]
                  and not [x for x in prog.msgs[n:] if x.get("type") == "control"], (note, stored))
        n, m = len(prog.msgs), len(panel.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "skip_windows", "value": ["x" * 60] * 50}))
        got = prog.wait(lambda x: x.get("type") == "control", after=n)
        taken = (got or {}).get("skip_windows") or []
        check("50 words of 60 characters are taken", len(taken) == 50 and all(len(w) == 60 for w in taken), len(taken))
        n, m = len(prog.msgs), len(panel.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "skip_windows", "value": ["w"] * 51}))
        note = panel.wait(lambda x: x.get("type") == "notice", after=m)
        check("too many words: the notice says the limits", bool(note) and "50" in note.get("text", "") and "60" in note.get("text", ""), note)
        # The program says a skip started: the panel's capture card hears it, and never which window
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "skipping": True}))
        seen = panel.wait(lambda x: x.get("type") == "capture" and (x.get("caps") or {}).get("skipping") is True, after=m)
        check("a skip started reaches the panel's capture card", bool(seen), seen)
        health = client.get("/health").json()["capture"]
        check("...and /health says it, with nothing of the window", health.get("caps", {}).get("skipping") is True, health)
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "skipping": "yes"}))
        seen = panel.wait(lambda x: x.get("type") == "capture" and (x.get("caps") or {}).get("skipping") is False, after=m)
        check("...a value that is not a yes is a no", bool(seen), seen)
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "skip_limit": "none"}))
        seen = panel.wait(lambda x: x.get("type") == "capture" and (x.get("caps") or {}).get("skip_limit") == "none", after=m)
        check("what the windows leave to go by reaches the panel's capture card", bool(seen), seen)
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "skip_limit": "My vault | Bitwarden"}))
        seen = panel.wait(lambda x: x.get("type") == "capture" and (x.get("caps") or {}).get("skip_limit") == "", after=m)
        check("...only as one of its words: anything else that came would be a window's name reaching the panel", bool(seen), seen)
        # Back to the defaults: the program is told the default list
        n = len(prog.msgs)
        pws.send_text(json.dumps({"type": "settings_reset"}))
        got = prog.wait(lambda x: x.get("type") == "control" and x.get("skip_windows") == SERVER_DEFAULT, after=n)
        check("Reset to defaults brings the default list back to the program", bool(got), got)
# A settings file edited by hand: its words trimmed as the panel's are, and one that is not a list of words ignored
path = Path(tempfile.mkdtemp(prefix="sidenote-skip-file-")) / ".settings.json"
path.write_text(json.dumps({"skip_windows": [" Vault ", "", "Bank"]}), encoding="utf-8")
loaded = Settings(path)
loaded.load()
check("a settings file's words are trimmed when it is read", loaded.get("skip_windows") == ["Vault", "Bank"], loaded.get("skip_windows"))
path.write_text(json.dumps({"skip_windows": "Vault"}), encoding="utf-8")
loaded = Settings(path)
loaded.load()
check("...and a value that is not a list of words leaves the default", loaded.get("skip_windows") == SERVER_DEFAULT,
      loaded.get("skip_windows"))

for note in NOTES:
    print(f"  ({note})")
print(f"\n==== {len(OK)} passed, {len(BAD)} failed ====")
sys.exit(1 if BAD else 0)
