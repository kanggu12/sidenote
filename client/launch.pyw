"""Starts the capture program from the desktop shortcut, with no console window at any point.

The shortcut that `./sidenote shortcut` makes runs this file with pyw.exe, the Python launcher that opens no console,
and this file runs `./sidenote capture --up` in WSL through wsl.exe, which gets no console window either. That
starts the server when it is down and then the capture program, so its tray icon is the one thing that appears.
The shortcut used to run wsl.exe itself: wsl.exe opens a console window for the launcher, which came up on every
start, and that window was the only place a failure was shown. A failure is shown here instead, with the last lines the
launcher printed, in a window made as the tray icon's menu is (Windows' own message box where tkinter is missing).

    pyw -3 launch.pyw --distro Ubuntu-22.04 --repo /home/you/sidenote [-- capture options]
    py -3 launch.pyw --setup --distro Ubuntu-22.04 --repo /home/you/sidenote
    py -3 launch.pyw --remove         (takes away the desktop shortcut and the icon that --setup made)
    py -3 launch.pyw --dry-run ...    (does everything, but prints what it would show instead: for tests)

On a WSL that cannot start Windows programs ([interop] enabled=false in /etc/wsl.conf, or no Windows drive mounted) the
launcher brings the server up and hands the capture program's start back here, and this starts it with its own Windows
Python: starting a Windows program from Windows asks nothing of WSL's interop, so the setting can stay as the user made
it. --setup, run once in a Windows terminal, does there what `./sidenote setup-capture` and `./sidenote shortcut` do from
WSL: the capture packages into this Python, and the desktop shortcut. --remove takes the shortcut and its icon away
again, as `./sidenote uninstall` does where WSL can start Windows programs, and prints the command that takes the
packages out. Both are typed by a person, so what is wrong with their arguments is printed in the terminal, not shown
in a window.

A capture program that already runs for the server is not started a second time (it holds a guard for as long as it
runs: OneCapture in capture.py, looked for here by capture_alive). The panel opens instead, as a second click on a
running app's shortcut shows that app.

While it waits, a small window beside the notification area says what the start is at (a start that shows nothing
gives no way to tell whether it is starting): the server, then the capture program, then that the tray icon is there.
It closes by itself, takes no focus, and has no taskbar button. Without tkinter the start goes on as it did, with
nothing shown. Both windows speak the language of the boxes.

Nothing here stays running: it waits for the launcher, which returns once the capture program is up, and ends.
Started from the shortcut it writes no file of its own and adds nothing to Windows (the temporary file for the output
deletes itself); --setup adds the packages, the shortcut and its icon, as the launcher's own commands do, and --remove
takes the shortcut and the icon away.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser

# A console program started with this flag gets a console of its own that has no window. Without it, a console
# program started from a windowless one (pythonw.exe here) is given a new console window, the very thing to avoid.
# The Windows programs the launcher starts in turn get windowless consoles from WSL itself (measured:
# cmd.exe started from bash with no terminal had its own conhost.exe, and GetConsoleWindow() answered 0 there).
CREATE_NO_WINDOW = 0x08000000

# What runs in WSL, in a login shell: bash -l reads ~/.profile, where the folder of Claude Code joins the PATH, as
# in a terminal. wsl.exe's plain `--` form runs `bash -c` without it (measured: no `claude` there), so the old
# shortcut's `up` built the server image for compose.yaml's default Claude Code version, not for this PC's own.
# The checkout is $1 and the capture options follow it; "$@" hands them on as the words they are, and wsl.exe's
# --exec passes each argument as it was given (measured: spaces, quotes, Korean and backslashes all arrived whole),
# where the `--` form hands a shell the raw command line to read again.
# `cd ... || exit`: a checkout that moved fails with the folder named, and not with a launcher missing elsewhere.
# --from-windows: this starter can start the capture program itself, when WSL cannot start Windows programs (launch)
SCRIPT = 'cd -- "$1" || exit; shift; exec ./sidenote capture --up --from-windows "$@"'
NAME = "sidenote-shortcut"   # $0 of that shell: what bash puts in front of its own error messages

# The words of the windows and the message boxes, in English unless SIDENOTE_LANG says ko, as the capture program's are:
# the system's language is not read. KO holds the Korean for each English text, character for character.
def ui_lang() -> str:
    fixed = os.environ.get("SIDENOTE_LANG", "").strip().lower()
    return fixed if fixed in ("en", "ko") else "en"


LANG = ui_lang()


def code_version() -> str:
    """This code's release, from server/version.py, the one place it is kept: beside the name, as the panel has it beside
    its own. The desktop app carries the server package; a checkout has the file beside this folder. "" when neither is
    there."""
    try:
        from server.version import VERSION as found   # the desktop app: the server is in the same bundle
        return found
    except Exception:
        pass
    # a checkout has the server's file beside this folder; the release's zip has it beside this file
    for where in (("..", "server", "version.py"), ("version.py",)):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), *where), encoding="utf-8") as f:
                m = re.search(r'^VERSION = "([0-9][0-9.]*)"', f.read(), re.M)
            if m:
                return m.group(1)
        except OSError:
            pass
    return ""


VERSION = code_version()

KO = {
    "Capture did not start": "캡처를 시작하지 못함",
    "Capture still starting": "캡처 시작 중",
    "The start from the shortcut is still getting ready · the first start, and the first after an update, builds the "
    "server image for a few minutes · the tray icon comes when it is done\n\n"
    "Taking too long: ./sidenote status in the server's terminal":
        "바로가기로 시작한 캡처가 아직 준비 중 · 처음과 업데이트 뒤에는 서버 이미지를 만드느라 몇 분 걸림 · "
        "끝나면 트레이 아이콘이 나타남\n\n"
        "너무 오래 걸리면: 서버 터미널에서 ./sidenote status",
    "It ended without printing anything (exit code {rc}).": "아무것도 출력하지 않고 끝났습니다 (종료 코드 {rc}).",
    "The capture program did not connect to the server. In a Windows terminal this shows why:":
        "캡처 프로그램이 서버에 연결되지 않았습니다. Windows 터미널에서 이 명령으로 이유를 볼 수 있습니다:",
    "The whole output shows with this command in the server's terminal:": "전체 출력은 서버 터미널에서 이 명령으로 볼 수 있습니다:",
    "The capture packages are not in this Windows Python ({missing}). In a Windows terminal this installs them:":
        "이 Windows Python에 캡처 패키지가 없습니다 ({missing}). Windows 터미널에서 이 명령으로 설치할 수 있습니다:",
    "Installing the capture packages into this Python ({python})": "이 Python에 캡처 패키지를 설치합니다 ({python})",
    "The packages did not install (pip ended with {rc}). The lines above say why.":
        "패키지를 설치하지 못했습니다 (pip 종료 코드 {rc}). 위 출력에 이유가 있습니다.",
    "Sidenote: start screen and sound capture (quit from the tray icon)": "Sidenote: 화면과 소리 캡처 시작 (끄기는 트레이 아이콘에서)",
    "Desktop shortcut made: {name}": "바탕화면에 바로가기를 만들었습니다: {name}",
    "Could not make the desktop shortcut: {error}": "바탕화면 바로가기를 만들지 못했습니다: {error}",
    "PowerShell made no file": "PowerShell이 파일을 만들지 않았습니다",
    "A double click starts the server and the capture with no window, and a tray icon appears in the notification area.":
        "두 번 클릭하면 창 없이 서버와 캡처가 함께 시작되고, 알림 영역에 트레이 아이콘이 나타납니다.",
    "Could not read the shortcut's arguments: {error}": "바로가기의 인자를 읽지 못했습니다: {error}",
    "Make the shortcut again with ./sidenote shortcut in the WSL terminal.": "WSL 터미널에서 ./sidenote shortcut으로 바로가기를 다시 만드세요.",
    "Could not run wsl.exe ({path}): {error}": "wsl.exe를 실행하지 못했습니다 ({path}): {error}",
    "Check that WSL is installed.": "WSL이 설치돼 있는지 확인하세요.",
    "The shortcut's starter failed: {error}": "바로가기 실행기에서 오류가 났습니다: {error}",
    "Could not read the arguments: {error}": "인자를 읽지 못했습니다: {error}",
    "Usage:": "사용법:",
    "To start the capture from a Windows terminal, without the shortcut:": "바로가기 없이 Windows 터미널에서 캡처를 시작하는 명령:",
    "Shortcut removed: {name}": "바로가기를 지웠습니다: {name}",
    "Shortcut still there: {name}": "바로가기가 남아 있습니다: {name}",
    "No shortcut on the desktop to remove.": "바탕화면에 지울 바로가기가 없습니다.",
    "Could not remove the shortcut: {error}": "바로가기를 지우지 못했습니다: {error}",
    "Icon removed: {path}": "아이콘을 지웠습니다: {path}",
    "Could not remove the icon: {error}": "아이콘을 지우지 못했습니다: {error}",
    "Folder removed: {path}": "폴더를 지웠습니다: {path}",
    "Folder kept, other files are in it: {path}": "다른 파일이 있어 폴더는 남겼습니다: {path}",
    "The capture packages that --setup installed into this Python stay. This removes them:":
        "--setup이 이 Python에 설치한 캡처 패키지는 남아 있습니다. 이 명령으로 지웁니다:",
    "Server": "서버",
    "Capture": "캡처",
    "Ready": "완료",
    "Starting": "시작 중",
    "Running": "실행 중",
    "{n}s": "{n}초",
    "Close": "닫기",
}


def t(text: str, **values) -> str:
    """`text` in LANG, its {placeholders} filled from `values` (the values themselves are not read for placeholders)."""
    out = KO.get(text, text) if LANG == "ko" else text
    if not values:
        return out
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), out)


# What the two notes this can show say at the top, as the panel says it: a short phrase. The window's own name stands
# above it, so the name is not said again.
FAILED = t("Capture did not start")
BUSY = t("Capture still starting")
BUSY_TEXT = t("The start from the shortcut is still getting ready · the first start, and the first after an update, builds the "
              "server image for a few minutes · the tray icon comes when it is done\n\n"
              "Taking too long: ./sidenote status in the server's terminal")

# MessageBoxW flags: one OK button, the icon, and in front of other windows. The box may come minutes after the
# double click (the first start builds the server image), when another window has the focus and Windows would
# otherwise leave it behind that window with only a blinking taskbar button to say it is there.
MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000

LINES = 15            # the last lines a box shows: the reason is at the end, and a box taller than the screen hides it
WIDTH = 160           # characters per line in Windows' own box before it is cut short: a long line widens the whole box
LONGEST = 2000        # the start's window wraps its lines, so there only a run of junk is cut: the reason is at a line's end
TAIL_BYTES = 65536    # how much of the end of the output is read: far more than LINES lines, at any build's length
ERROR_ALREADY_EXISTS = 183   # what GetLastError says after CreateMutexW opened a mutex someone else had made
SYNCHRONIZE = 0x00100000     # the least a mutex is opened with: enough to learn that someone holds it

# What a terminal acts on and a message box would print as junk: colour and cursor codes (ESC [ ... a final byte),
# a window title (ESC ] ... ending with BEL or ESC \, and never past the end of its line), and every other escape:
# ESC, any intermediate bytes, one final byte (`tput sgr0` writes ESC ( B before its ESC [ m). Then the remaining
# control characters, C1 ones included. Tab and newline are handled apart.
ESCAPES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b\n]*(?:\x07|\x1b\\)?|[ -/]*[0-~])")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


# What the small window says, in the language of the boxes: the three steps' names under their marks, and the state in
# its pill. Nothing more: the step lit says what goes on
STEPS = (t("Server"), t("Capture"), t("Ready"))
FAILED_AT: list = [None]   # where a start failed, for the note that says so: the step and the time each step took
DONE_HOLD = 2600      # milliseconds the last word stays, long enough to read
NOTE_HOLD = 12000     # milliseconds a note (a start already going) stays unless closed: a failure stays until closed
NOTICE_LINES = 16     # the lines a failure shows at once; the rest is a scroll away, with the end in view
HEALTH_URL = "http://127.0.0.1:{port}/health"   # the panel's own address: Windows reaches it through WSL's forwarding


def stage(server_up: bool, finished: bool) -> int:
    """Which of the three steps the start is at (0 to 2), from what can be seen from here."""
    if finished:
        return 2
    return 1 if server_up else 0


def capture_clients(port: int) -> int:
    """How many capture programs the server has connected, or -1 when it does not answer. No proxy, as server_answers."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(HEALTH_URL.format(port=port), timeout=2) as reply:
            return int(json.loads(reply.read())["capture"]["clients"])
    except (OSError, ValueError, KeyError, TypeError):
        return -1


def server_answers(port: int) -> bool:
    """Whether the server answers. No proxy: a Windows proxy setting would take even this address elsewhere."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(HEALTH_URL.format(port=port), timeout=0.8) as reply:
            return reply.status == 200
    except OSError:     # refused, timed out, or WSL's forwarding not up yet: not yet
        return False


def mix(a: str, b: str, t: float) -> str:
    """Colour a laid over colour b at strength t, as the tray menu mixes its own."""
    a, b = [int(a[k:k + 2], 16) for k in (1, 3, 5)], [int(b[k:k + 2], 16) for k in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(u * t + v * (1 - t)) for u, v in zip(a, b))


# The capture's logo, beside this file: Sidenote's own wordmark as docs/assets/logo-dark.svg has it, and "capture" after
# it in the same face, lighter (scratch/panel-tools/make_capture_logo.py draws it, at four times its size at 100%, with
# where its baseline and its letters' left edge are). The window writes the name where it is missing
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")


class Glass:
    """A small window beside the notification area, in the panel's make and the tray icon's menu's (TRAY_MENU in
    capture.py): frosted glass over what is behind it, the capture's logo with the release beside it, and the panel's
    pill, status light, marks and keys. On the main thread, where tkinter has to run."""

    # The menu's own colours: the glass, its edge and lit top, the words and the quieter words, the rule between its rows
    # (a line where there is no picture), the highlighter, the red of a failure and a row under the pointer; the green
    # of what is done and its lighter light, and the dark sheet a launcher's lines are set on
    BG, EDGE, TOP, INK, INK2, MUTED, TRACK, MARK, BAD, HOVER = ("#26272b", "#4a4c53", "#8a8c93", "#e3e4e5", "#cbccce", "#b0b1b4",
                                                                "#3c3d43", "#f2c744", "#ff6b6b", "#36373d")
    OK, LIT, SUNK = "#2eb67d", "#4cc08e", "#1c1d21"
    # Segoe UI has no Korean, and left to itself Windows picks a fallback of its own; its Semibold, for the figures, is a
    # face of its own to Tk, as it is to Windows
    SANS, SEMI, HANGUL, MONO = "Segoe UI", "Segoe UI Semibold", "Malgun Gothic", "Consolas"
    # The frosted glass (frost): how far what is behind it is blurred (pixels at 100%), the share of the glass's own colour
    # laid over it, and how far its colours are brought up again under that, as the panel's glass saturates what shows
    # through. 0.8 keeps a white desk under it at a grey the quieter words keep 4.5:1 on (tests/launch_window.py measures
    # every word), and leaves a dark one nearly as dark as it is: the desk shows, its windows' shapes and its colours. The
    # glass tinted more read as a grey board with nothing behind it
    BLUR, TINT, VIVID = 7, 0.8, 1.6
    KEY_FACE, KEY_LIT = 18, 36                                  # a key's face over the glass, and under the pointer (alpha of 255)

    def __init__(self, tk, focus: bool):
        self.tk = tk
        self.focus = focus                                      # a note to read and close takes the focus; the start's window does not
        self.root = tk.Tk()
        self.root.withdraw()                                    # nothing on screen until it is placed
        self.scale = self.root.winfo_fpixels("1i") / 96.0       # 1.0 at 100%, 2.0 at 200%: this PC runs 4K screens
        self.words = self.HANGUL if LANG == "ko" else self.SANS  # the font of what it says, for the language it says it in
        # The figures under the steps, as the panel sets its own: Segoe UI's Semibold, or Malgun Gothic's bold, which has no semibold
        self.figure = (self.HANGUL, 10, "bold") if LANG == "ko" else (self.SEMI, 10)
        self.root.overrideredirect(True)                        # no title bar
        self.root.attributes("-topmost", True)                  # over the other windows, as a notification is
        self.root.configure(bg=self.BG)
        self.c = tk.Canvas(self.root, bg=self.BG, highlightthickness=0, bd=0)
        self.photos = []                                        # Tk forgets a picture nothing holds on to
        self.behind = None                                      # the desktop under the window and round it, as grab() took it
        self.inside = None                                      # the window's own part of that picture
        self.frosted = None                                     # that part made frosted glass, once: each picture is drawn on it
        self.picture = None                                     # the last picture as shown, for what is drawn over it each frame
        self.logo_at = None                                     # where the logo is pasted (logo): left, top, width, height
        self.tag = None                                         # the release's tag: its words' box, for the line round it
        self.hwnd = None                                        # Windows: the frame Tk made round the window (dress)
        self.own_style = 0                                      # Windows: the extended style's bits this window keeps (restyle)

    def px(self, n: float) -> int:
        return round(n * self.scale)

    def rgba(self, colour: str, alpha: int) -> tuple:
        """A colour of the palette with an alpha, for laying over the glass."""
        return tuple(int(colour[k:k + 2], 16) for k in (1, 3, 5)) + (alpha,)

    def place(self, width: int, height: int, above: int = 0) -> None:
        """Its size, at the bottom right of the screen over the taskbar (and `above` pixels higher, over another window
        there), and then on screen."""
        self.width, self.height = width, height
        self.c.configure(width=width, height=height)
        self.c.pack()
        work = self.work_area()                                 # the screen less the taskbar
        x, y = work[2] - width - self.px(16), work[3] - height - self.px(16) - above
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.behind = self.grab(x, y, width, height)           # before it is shown: what its glass stands over
        self.root.update_idletasks()
        self.dress()
        self.arrive(x, y)

    def arrive(self, x: int, y: int) -> None:
        """On screen as a notification comes: up from 10 px lower and from clear, over a fifth of a second, slowing as it
        lands. The window is opaque at the end (alpha 1; Tk keeps it a layered window, drawn whole)."""
        rise, steps = self.px(10), 9
        try:
            self.root.attributes("-alpha", 0.0)
            self.restyle()                                       # before it is shown: Tk's alpha took them off
            self.root.geometry(f"+{x}+{y + rise}")
        except Exception:
            pass
        self.root.deiconify()
        self.corners()                                           # on screen now, its shadow come with it

        def go(k: int) -> None:
            ease = 1 - (1 - (k + 1) / steps) ** 3                # quick at first, slowing as it lands
            try:
                self.root.attributes("-alpha", ease)
                self.restyle()                                   # and again after each of Tk's alpha changes
                self.root.geometry(f"+{x}+{round(y + rise * (1 - ease))}")
            except Exception:                                    # gone meanwhile
                return
            if k + 1 < steps:
                self.root.after(22, lambda: go(k + 1))
        go(0)

    def leave(self, then) -> None:
        """Off screen as it came: down 6 px and clear over a sixth of a second, then `then` (the window's end)."""
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        except Exception:
            return then()
        steps = 7

        def go(k: int) -> None:
            ease = ((k + 1) / steps) ** 2
            try:
                self.root.attributes("-alpha", 1 - ease)
                self.restyle()                                   # no taskbar button as it goes either
                self.root.geometry(f"+{x}+{round(y + self.px(6) * ease)}")
            except Exception:
                return
            if k + 1 < steps:
                self.root.after(22, lambda: go(k + 1))
            else:
                then()
        go(0)

    def patch(self, box):
        """A part of the picture drawn again each frame (the part of the bar under way, the pill's light): the picture's own
        pixels there to draw on, and a canvas image showing what is drawn. None without a picture."""
        if self.picture is None:
            return None
        from PIL import ImageTk
        box = tuple(round(v) for v in box)
        base = self.picture.crop(box)
        photo = ImageTk.PhotoImage(base, master=self.root)
        item = self.c.create_image(box[0], box[1], anchor="nw", image=photo)
        return {"box": box, "base": base, "photo": photo, "item": item}

    def repaint(self, patch, painter) -> None:
        """A patch drawn again: painter(picture, draw, S) on its pixels three times over, brought down into its image."""
        from PIL import Image, ImageDraw
        S = 3
        base = patch["base"]
        big = base.resize((base.width * S, base.height * S), Image.BICUBIC)
        painter(big, ImageDraw.Draw(big, "RGBA"), S)
        patch["photo"].paste(big.resize(base.size, Image.LANCZOS))

    def fit(self, text: str, font, width: int) -> str:
        """`text` cut to `width` pixels in `font`, its end marked where it was cut."""
        import tkinter.font
        measure = tkinter.font.Font(root=self.root, font=font)
        if measure.measure(text) <= width:
            return text
        low, high = 0, len(text)                                # the longest start of it that fits with the mark, found by halves
        while low < high:
            mid = (low + high + 1) // 2
            low, high = (mid, high) if measure.measure(text[:mid] + "…") <= width else (low, mid - 1)
        return text[:low] + "…"

    def on_line(self, x: float, baseline: float, text: str, font, fill: str, anchor: str = "w") -> int:
        """Words with their baseline on `baseline`: words of two sizes on one line stand on it together, where centring
        each set the smaller one's foot higher."""
        import tkinter.font
        measure = tkinter.font.Font(root=self.root, font=font)
        self.fonts.append(measure)                              # held: a font nothing holds on to goes
        return self.c.create_text(x, baseline - measure.metrics("ascent"), anchor="n" + anchor, text=text, font=font, fill=fill)

    def grab(self, x: int, y: int, width: int, height: int):
        """What the screen shows where the window is to stand and a little round it, taken before it is shown: the glass is
        drawn over it, blurred and tinted, so the desktop shows through as through frosted glass (frost). The margin is
        what the blur reaches: with none, the window's edges blurred only what was inside them. Taken once: the start's
        window stands a few seconds in a corner over the taskbar. None where the screen cannot be read, and the glass is
        then drawn alone."""
        try:
            from PIL import ImageGrab
            margin = self.px(self.BLUR * 3)                     # past three times the blur, what is there no longer counts
            box = (max(0, x - margin), max(0, y - margin), min(self.root.winfo_screenwidth(), x + width + margin),
                   min(self.root.winfo_screenheight(), y + height + margin))   # on the screen: past it, a grab is black
            shot = ImageGrab.grab(bbox=box)
            if shot.size != (box[2] - box[0], box[3] - box[1]):
                return None
            self.inside = (x - box[0], y - box[1], x - box[0] + width, y - box[1] + height)
            return shot.convert("RGB")
        except Exception:
            return None

    def work_area(self) -> tuple[int, int, int, int]:
        """Left, top, right and bottom of the main screen less its taskbar; the whole screen where that cannot be read."""
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):   # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def dress(self) -> None:
        """Windows only, each an extra, before it is shown: no taskbar button, no focus on a click unless it is to be read
        and closed (restyle keeps both), and a shadow; Windows 11's rounded corners once it is shown (corners)."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()   # the frame Tk made round the window
            WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
            self.hwnd = hwnd
            self.own_style = WS_EX_TOOLWINDOW | (0 if self.focus else WS_EX_NOACTIVATE)
            self.restyle()
            # A shadow under it, as a menu or a notification has: the glass stands off the desktop. The class's style (CS_DROPSHADOW),
            # which this process's one window alone wears, set before the window is first shown: its shadow comes as it does
            get = getattr(user32, "GetClassLongPtrW", user32.GetClassLongW)
            put = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
            put(hwnd, -26, get(hwnd, -26) | 0x00020000)          # GCL_STYLE, CS_DROPSHADOW
            # No acrylic of Windows' own: it paints over what Tk draws, which carries no alpha, and the window showed its tint
            # with no words on it. The frosted glass is drawn instead (frost), and the window is opaque: made see-through, the
            # words went see-through with it and read washed out
        except Exception:
            pass

    def restyle(self) -> None:
        """Windows: the frame's own bits (no taskbar button, no activation) on its extended style again. Tk writes the
        frame's extended style from its own record when its alpha first leaves 1 (arrive), which knows neither: measured on
        a real Windows desktop, the start window gained a taskbar button and a click on it took the focus. Called after
        each of Tk's alpha changes; nothing elsewhere."""
        if not self.hwnd or not self.own_style:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetWindowLongW(self.hwnd, -20, user32.GetWindowLongW(self.hwnd, -20) | self.own_style)   # GWL_EXSTYLE
        except Exception:
            pass

    def corners(self) -> None:
        """Windows 11's small rounded corners and its line round the window in the glass's edge colour, asked once the
        window is on screen: asked before it was first shown, the shadow its class asks for did not come (the tray menu
        asks after, and has it)."""
        if not self.hwnd:
            return
        try:
            import ctypes
            corner = ctypes.c_int(3)                             # DWMWCP_ROUNDSMALL: this design is nearly square
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))   # DWMWA_WINDOW_CORNER_PREFERENCE
            # Windows 11's own line round the window in the glass's edge colour (DWMWA_BORDER_COLOR takes 0x00BBGGRR), not its accent
            r, g, b = (int(self.EDGE[k:k + 2], 16) for k in (1, 3, 5))
            edge = ctypes.c_uint(r | g << 8 | b << 16)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, 34, ctypes.byref(edge), ctypes.sizeof(edge))
        except Exception:
            pass

    def art(self, shapes):
        """The glass and the shapes on it as one picture, drawn three times over and brought down as the tray menu draws its
        own (Tk draws shapes unsmoothed on Windows): frosted over the desktop behind it, the logo, its edge and lit top.
        shapes(draw, S) draws on it, S the times over, and a colour with an alpha is laid over what is there. None without
        Pillow: the window keeps to plain shapes then (it comes with the capture packages, in the same Windows Python the
        shortcut runs)."""
        try:
            from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk
        except Exception:
            return None
        try:
            return self._art(shapes, Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk)
        except Exception:                                       # any slip in the drawing: plain shapes, and the window goes on
            return None

    def _art(self, shapes, Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk):
        S, w, h = 3, self.width, self.height
        W, H = w * S, h * S
        # The body: what is behind the window, frosted (frost); the glass's own colour where the screen could not be read
        glass = self.frost(Image, ImageEnhance, ImageFilter) if self.behind is not None else None
        img = (glass or Image.new("RGB", (w, h), self.BG)).resize((W, H), Image.BICUBIC)
        # A fine grain over it, as frosted glass has and the panel's page has its own: a pixel a grain once brought down
        grain = Image.effect_noise((w, h), 26).resize((W, H), Image.NEAREST).convert("RGB")
        img = Image.blend(img, grain, 0.03)
        d = ImageDraw.Draw(img, "RGBA")                         # a colour with an alpha is laid over the glass, not put in its place
        shapes(d, S)
        logo = self.logo_picture()
        if logo is not None and self.logo_at is not None:       # the logo, brought down from its own four times
            x, y, lw, lh = self.logo_at
            big = logo[0].resize((round(lw * S), round(lh * S)), Image.LANCZOS)
            img.paste(big.convert("RGB"), (round(x * S), round(y * S)), big.getchannel("A"))
        if self.tag is not None:                                # the release's tag: a fine line round it, square as the panel's
            x0, y0, x1, y1 = self.tag
            d.rectangle([S * x0, S * y0, S * x1 - 1, S * y1 - 1], outline=(255, 255, 255, 44), width=S)
        # Its edge, and its top lit as the tray menu's is: the glass's rim catching a light above it. Nothing more: a sheen,
        # streaks of light and a lit side read as decoration, not as glass
        d.rectangle([0, 0, W - 1, H - 1], outline=self.EDGE, width=S)
        d.line([(S, S // 2), (W - S, S // 2)], fill=self.TOP, width=S)
        self.picture = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(self.picture, master=self.root)
        self.photos = self.photos[-3:] + [photo]
        return photo

    def frost(self, Image, ImageEnhance, ImageFilter):
        """What is behind the window as frosted glass: blurred past reading but not past its shapes, the glass's colour laid
        over it (TINT), and its colours brought up again (VIVID). None when it cannot be made."""
        if self.frosted is not None:                            # what is behind it has not changed since: it was taken once
            return self.frosted
        try:
            soft = self.behind.filter(ImageFilter.GaussianBlur(self.px(self.BLUR))).crop(self.inside)
            tinted = Image.blend(soft, Image.new("RGB", soft.size, self.BG), self.TINT)
            self.frosted = ImageEnhance.Color(tinted).enhance(self.VIVID)
            return self.frosted
        except Exception:
            return None

    _logo = None                                                # the logo as read once: (picture, its name's baseline), or False

    @classmethod
    def logo_picture(cls):
        """The logo's picture and where its name's baseline is in it, read once; None where it or Pillow is missing."""
        if cls._logo is None:
            try:
                from PIL import Image
                with Image.open(LOGO) as found:
                    found.load()
                    cls._logo = (found.convert("RGBA"), int(found.text.get("baseline", "0")) or round(found.height * 0.7),
                                 int(found.text.get("left", "0")))
            except Exception:
                cls._logo = False
        return cls._logo or None

    def logo(self, left: int, top: int) -> tuple[int, int]:
        """The logo at (left, top), a quarter of its picture at 100%, and the release beside it in the panel's tag: the code
        face, quiet, in a square of fine line, on the name's baseline. Where the picture is missing, the name and "capture"
        are written instead. Returns the tag's right edge and the baseline."""
        import tkinter.font
        c, p = self.c, self.px
        found = self.logo_picture() if self.art_possible() else None
        small = tkinter.font.Font(root=self.root, family=self.MONO, size=8)
        self.fonts = [small]                                    # a font nothing holds on to goes, and its words with it
        if found is not None:
            picture, line, start = found
            lw, lh = picture.width * self.scale / 4, picture.height * self.scale / 4
            x = left - start * self.scale / 4                    # its letters on the margin; the highlighter starts a little before
            self.logo_at = (x, top, lw, lh)
            baseline, right = top + line * self.scale / 4, x + lw
        else:                                                   # words, as the panel's bar would show them with no fonts
            big = tkinter.font.Font(root=self.root, family=self.SANS, size=12, weight="bold")
            self.fonts.append(big)
            baseline = top + big.metrics("ascent")
            name = c.create_text(left, top, anchor="nw", text="sidenote", fill=self.INK, font=big)
            word = c.create_text(c.bbox(name)[2] + p(8), baseline - small.metrics("ascent") - p(1), anchor="nw", text="capture",
                                 fill=self.INK2, font=(self.SANS, 9))
            right = c.bbox(word)[2]
        if VERSION:                                             # the release, set on the name's baseline
            tag = c.create_text(right + p(6), baseline - small.metrics("ascent"), anchor="nw", text="v" + VERSION,
                                fill=self.INK2, font=small)
            x0, y0, x1, y1 = c.bbox(tag)
            self.tag = (x0 - p(6), y0 - p(3), x1 + p(6), y1 + p(3))
            right = self.tag[2]
        return right, baseline

    def logo_words(self, art) -> None:
        """Where the picture could not be drawn (art is None) but the logo was placed in it: the name and "capture" written
        at its place instead, on its baseline."""
        if art is not None or self.logo_at is None:
            return
        import tkinter.font
        x, y, _, lh = self.logo_at
        found = self.logo_picture()
        baseline = y + found[1] * self.scale / 4 if found else y + lh * 0.6   # the name's line, as the picture has it
        big = tkinter.font.Font(root=self.root, family=self.SANS, size=12, weight="bold")
        self.fonts.append(big)                                  # held, as the other fonts are
        at = x + (found[2] * self.scale / 4 if found else 0)   # where the picture's letters would have started
        name = self.c.create_text(at, baseline - big.metrics("ascent"), anchor="nw", text="sidenote", fill=self.INK,
                                  font=big)
        self.c.create_text(self.c.bbox(name)[2] + self.px(6), baseline - big.metrics("ascent"), anchor="nw", text="capture",
                           fill=self.INK, font=(self.SANS, 12))

    def art_possible(self) -> bool:
        """Whether a picture can be drawn: Pillow is there (the logo is pasted into the picture)."""
        try:
            import PIL  # noqa: F401
            return True
        except Exception:
            return False

    def lamp(self, d, S, cx: float, cy: float, colour: str, size: float = 1.0) -> None:
        """The panel's status light: a dot of the colour, lighter at its middle, its glow round it."""
        p = lambda n: n * self.scale * size
        r, g, b = (int(colour[k:k + 2], 16) for k in (1, 3, 5))
        for radius, alpha in ((p(8), 16), (p(6.5), 30), (p(5.2), 56)):   # the glow, fading outward
            d.ellipse([S * (cx - radius), S * (cy - radius), S * (cx + radius), S * (cy + radius)], fill=(r, g, b, alpha))
        d.ellipse([S * (cx - p(4)), S * (cy - p(4)), S * (cx + p(4)), S * (cy + p(4))], fill=colour)
        light = mix("#ffffff", colour, 0.5)                     # the middle, where the light is
        d.ellipse([S * (cx - p(1.6)), S * (cy - p(1.6)), S * (cx + p(1.6)), S * (cy + p(1.6))], fill=light)

    def pill(self, text: str, colour: str, right: int, middle: int):
        """The panel's pill for a state, its right edge at `right` and its middle at `middle`: the state's words in its
        colour after its status light, on a dark sheet of that colour, whatever the glass shows (the words keep their 4.5:1
        on it). The words are in the canvas; returns the pill's box, for the picture to draw it."""
        p = self.px
        word = self.c.create_text(right - p(11), middle, anchor="e", text=text, fill=colour, font=(self.words, 9))
        x0, _, _, _ = self.c.bbox(word)
        return (x0 - p(21), middle - p(11), right, middle + p(11)), colour

    def draw_pill(self, d, S, pill) -> None:
        (x0, y0, x1, y1), colour = pill
        d.rounded_rectangle([S * x0, S * y0, S * x1, S * y1], radius=S * (y1 - y0) / 2, fill=mix(colour, self.SUNK, 0.16))
        self.lamp(d, S, x0 + self.px(11), (y0 + y1) / 2, colour, size=0.62)

    def bar(self, d, S, left: float, right: float, middle: float, fills: list) -> None:
        """The panel's bar in three parts, one a step, a small gap between them: the track sunk into the glass, dark
        whatever the glass shows, and each part filled from its left as far as fills says (0 to 1) in its colour."""
        h, gap = 6 * self.scale, 3 * self.scale                 # 6 px tall, 3 px between the parts, at 100%
        part = (right - left - 2 * gap) / 3
        for i, (amount, colour) in enumerate(fills):
            x0 = left + i * (part + gap)
            box = [S * x0, S * (middle - h / 2), S * (x0 + part), S * (middle + h / 2)]
            d.rounded_rectangle(box, radius=S * h / 2, fill=(0, 0, 0, 92))   # the track, sunk
            d.line([(box[0] + S * h / 2, box[1] + S // 2), (box[2] - S * h / 2, box[1] + S // 2)], fill=(0, 0, 0, 70), width=S)
            if amount > 0:                                      # the filled part, round at both ends
                end = x0 + max(h, part * min(1.0, amount))
                d.rounded_rectangle([box[0], box[1], S * end, box[3]], radius=S * h / 2, fill=colour)

    def parts(self, left: float, right: float) -> list:
        """The left edge of each of the bar's three parts, for the steps' names under them."""
        gap = 3 * self.scale
        part = (right - left - 2 * gap) / 3
        return [left + i * (part + gap) for i in range(3)]


def clock(seconds: float, tenths: bool = False) -> str:
    """A time read at a glance: 12s (3.1s for a step done), and past a minute 1:05."""
    if seconds < 60:
        return t("{n}s", n=f"{seconds:.1f}" if tenths else int(seconds))
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class Starting(Glass):
    """The window for as long as the start takes: the logo and the release, the state in the panel's pill, and the panel's
    bar in three parts, one a step (the server, the capture program, ready), filling as the start goes: the step under
    way fills quickly at first and then ever more slowly, never past most of its part, and a step done is full. Under
    the bar each part's name, the one under way lit, and the time the start has taken. It takes no focus, and a click
    hides it while the start goes on."""

    W, H, PAD = 360, 124, 18                                    # its size and its margins, at 100%: a notification's width

    def __init__(self, tk):
        super().__init__(tk, focus=False)
        self.c.bind("<Button-1>", lambda _e: self.root.withdraw())   # in the way: a click hides it, the start goes on
        self.step, self.finished, self.started = 0, False, time.monotonic()
        self.since = time.monotonic()                           # when the step under way began
        self.began = [self.started]                             # when each step began, the first at the start
        self.ended = None                                       # when the start was done
        self.fill = 0.0                                         # how far the bar is filled, 0 to 3 (a part a step), as drawn
        self.tick = None                                        # the next frame, asked of Tk: called off when the window goes
        self.drawn = None                                       # the step and end the picture shows
        self.moving = None                                      # the filled part of the step under way, a canvas item
        self.seconds = None                                     # the time taken, a canvas item
        self.detail, self.read_at = None, 0.0                   # the launcher's last line under the bar, and when it was read
        self.place(self.px(self.W), self.px(self.H))
        self.draw()

    def show(self, step: int, finished: bool) -> None:
        now = time.monotonic()
        while len(self.began) <= step:                          # each step reached, and when
            self.began.append(now)
        if step != self.step:
            self.since = now
        if finished and self.ended is None:
            self.ended = now
        self.step, self.finished = step, finished

    def times(self) -> list:
        """The time each step took: a step done its whole time, the one under way so far, one to come None; ready, once
        reached, the whole start's time."""
        now = time.monotonic()
        out = []
        for i in range(3):
            if i == 2:
                out.append((self.ended - self.started) if self.finished and self.ended is not None else None)
            elif i < len(self.began) - 1:
                out.append(self.began[i + 1] - self.began[i])
            elif i == len(self.began) - 1 and not self.finished:
                out.append(now - self.began[i])
            else:
                out.append(None)
        return out

    def goal(self) -> float:
        """How far the bar should be filled, 0 to 3: the steps done, and the one under way quickly at first and then ever
        more slowly, never past most of its part; all of it once the start is done."""
        if self.finished:
            return 3.0
        waited = time.monotonic() - self.since
        return self.step + 0.85 * (1 - 1 / (1 + waited / 6))

    def frame(self) -> None:
        """What changes with the step: the picture with the steps done, the pill and the names, drawn once for each."""
        c, p = self.c, self.px
        c.delete("all")
        left, right = p(self.PAD), self.width - p(self.PAD)
        _, baseline = self.logo(left, p(11))
        # The pill: the panel's green once running, the highlighter while starting. The bar is the panel's green throughout,
        # as its load steps and its download bar are
        pill = self.pill(t("Running") if self.finished else t("Starting"), self.LIT if self.finished else self.MARK, right, baseline - p(5))
        self.middle = p(64)                                     # the bar's middle
        done = 3 if self.finished else self.step                # the parts drawn full in the picture; the one under way moves
        fills = [(1.0, self.rgba(self.OK, 255)) if i < done else (0.0, None) for i in range(3)]
        art = self.backdrop(lambda d, S: (self.draw_pill(d, S, pill), self.bar(d, S, left, right, self.middle, fills)))
        self.logo_words(art)
        line = p(88)                                            # the names and the time on one baseline
        for i, x in enumerate(self.parts(left, right)):         # each part's name under it, the one under way lit
            now = i == self.step and not self.finished
            self.on_line(x, line, STEPS[i], (self.SEMI if LANG != "ko" else self.HANGUL, 8) if now else (self.words, 8),
                         self.INK if now or self.finished else self.INK2)
        self.seconds = self.on_line(right, line, "", self.figure, self.INK2, anchor="e")
        # What goes on in detail: the launcher's last line as it prints it (latest_line), in the code face as a terminal
        # shows it, cut to the window's width
        self.detail = self.on_line(left, p(110), "", (self.MONO, 8), self.INK2)
        self.read_at = 0.0                                      # read again at once
        # The part under way, filled as the start goes on and drawn again each frame (draw): a patch of the picture where
        # there is one, else a plain bar in the canvas. Neither is shown before it has some length: a sliver sat at the
        # corner as a dot
        self.part = (right - left - 6 * self.scale) / 3
        self.bar_patch = self.light_patch = self.moving = None
        if not self.finished:
            x0, edge = self.parts(left, right)[self.step], p(2)
            half = 3 * self.scale
            self.bar_patch = self.patch((x0 - edge, self.middle - half - edge, x0 + self.part + edge, self.middle + half + edge))
            (px0, py0, px1, py1), _ = pill
            lx, ly = px0 + p(11), (py0 + py1) / 2              # the pill's light, whose ring breathes while the start goes on
            self.light_patch = self.patch((lx - p(10), ly - p(10), lx + p(10), ly + p(10)))
            if self.bar_patch is None:
                self.moving = c.create_rectangle(0, 0, 0, 0, fill=self.OK, outline="", state="hidden")
        self.fill = max(self.fill, float(done))                 # a new step starts its part empty
        self.drawn = (self.step, self.finished)

    def backdrop(self, shapes):
        """The picture under the words, at the back of the canvas; the plain edge and track where Pillow is missing."""
        c, p = self.c, self.px
        art = self.art(shapes)
        if art is not None:
            c.create_image(0, 0, anchor="nw", image=art, tags="art")
        else:
            left, right = p(self.PAD), self.width - p(self.PAD)
            c.create_rectangle(0, 0, self.width - 1, self.height - 1, outline=self.EDGE, tags="art")
            h = 3 * self.scale
            for i, x in enumerate(self.parts(left, right)):     # the parts, plainly: done ones filled
                done = i < self.step or self.finished
                part = (right - left - 6 * self.scale) / 3
                c.create_rectangle(x, self.middle - h, x + part, self.middle + h, outline="", tags="art",
                                   fill=self.OK if done else self.TRACK)
        c.tag_lower("art")
        return art

    def draw(self) -> None:
        """One frame: the picture again only when the step has changed; the time and the part under way each time. The
        next frame is asked for whatever happens in this one: a slip that ended it left the window still."""
        try:
            if self.drawn != (self.step, self.finished):
                self.frame()
            c, p = self.c, self.px
            took = (self.ended if self.finished and self.ended is not None else time.monotonic()) - self.started
            c.itemconfigure(self.seconds, text=clock(took, tenths=self.finished))   # the whole start, to a tenth once done
            if self.detail is not None and time.monotonic() - self.read_at > 0.4:   # the launcher's last line, a few times a second
                self.read_at = time.monotonic()
                said = latest_line()
                if said:                                        # kept as it was while the launcher is quiet, or once it is done
                    c.itemconfigure(self.detail, text=self.fit(said, (self.MONO, 8), self.width - 2 * p(self.PAD)))
            self.fill += (self.goal() - self.fill) * 0.08       # it rises to where it should be
            amount = min(1.0, max(0.0, self.fill - self.step))
            now = time.monotonic()
            if self.bar_patch is not None:
                self.repaint(self.bar_patch, lambda img, d, S: self.paint_part(img, S, amount, now))
            if self.light_patch is not None:
                self.repaint(self.light_patch, lambda img, d, S: self.paint_breath(d, S, now))
            if self.moving is not None:                         # no picture: a plain bar
                left, right = p(self.PAD), self.width - p(self.PAD)
                x0, h = self.parts(left, right)[self.step], 3 * self.scale
                if self.part * amount >= 2 * h:                 # shown once it is as long as it is tall
                    c.coords(self.moving, x0, self.middle - h, x0 + self.part * amount, self.middle + h)
                    c.itemconfigure(self.moving, state="normal")
                else:
                    c.itemconfigure(self.moving, state="hidden")
        finally:
            if self.tick is not None:                           # one frame asked for at a time, however draw() was called
                self.root.after_cancel(self.tick)
            self.tick = self.root.after(33, self.draw)          # 30 frames a second, for a few seconds or minutes

    def close(self) -> None:
        """Gone, with its next frame called off: left asked for, it ran on into the note made after it, in a Tcl whose
        window was gone, and Tcl could end the program there."""
        if self.tick is not None:
            self.root.after_cancel(self.tick)
            self.tick = None
        self.root.destroy()

    def close_after(self, ms: int) -> None:
        self.root.after(ms, lambda: self.leave(self.close))     # out as it came in, then gone

    def paint_part(self, img, S: int, amount: float, now: float) -> None:
        """The part under way, as far as it is filled: the panel's green, deeper at its foot and lit at its head, and a light
        running along it again and again, as the panel's loading sweep runs. Round at both ends; nothing before it is as
        long as it is tall."""
        from PIL import Image, ImageDraw, ImageOps
        h, edge = 6 * self.scale, self.px(2)
        width = self.part * amount
        if width < h:
            return
        ww, hh = round(width * S), round(h * S)
        ramp = Image.frombytes("L", (256, 1), bytes(range(256))).resize((ww, hh), Image.BILINEAR)
        fill = ImageOps.colorize(ramp, black=mix("#000000", self.OK, 0.28), white=self.LIT).convert("RGBA")
        band = max(4, round(self.px(30) * S))                   # the running light: 30 px, its middle a quarter white
        run = ((now - self.since) / 1.4) % 1.0
        at = round((run * (width + self.px(30)) - self.px(30)) * S)
        glow = Image.frombytes("L", (band, 1), bytes(round(64 * (1 - abs(2 * i / (band - 1) - 1)) ** 2) for i in range(band)))
        light = Image.new("RGBA", (band, hh), (255, 255, 255, 0))
        light.putalpha(glow.resize((band, hh)))
        start, into = max(0, -at), max(0, at)                   # the part of the light inside the fill
        seen = min(band - start, ww - into)
        if seen > 0:
            fill.alpha_composite(light.crop((start, 0, start + seen, hh)), (into, 0))
        mask = Image.new("L", (ww, hh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, ww - 1, hh - 1], radius=hh / 2, fill=255)
        img.paste(fill.convert("RGB"), (round(edge * S), round(edge * S)), mask)

    def paint_breath(self, d, S: int, now: float) -> None:
        """The pill's light breathing a ring, as the panel's lamps do while something is under way: out from the light and
        fading, once every 1.6 s."""
        run = ((now - self.started) / 1.6) % 1.0
        c = self.px(10)                                         # the light's middle in its patch
        r = self.px(4) + self.px(5) * run
        d.ellipse([S * (c - r), S * (c - r), S * (c + r), S * (c + r)], outline=self.rgba(self.MARK, round(150 * (1 - run))),
                  width=max(1, round(S * 1.4 * self.scale)))


class Notice(Glass):
    """What a box would say, in the start's window and in its make: the logo, the title in the panel's pill (its red for
    what went wrong, its grey before a note), for a start that failed the same bar stopped where it failed (the steps
    done green, the one it failed at red), the end of what the launcher printed on a darker sheet in its own columns, to
    select and copy, and a Close key, flat, a face and a fine line round it. Esc, Enter or Close takes it away; a note
    goes by itself after NOTE_HOLD, and a failure stays until it is closed."""

    def __init__(self, tk, title: str, text: str, failed: bool):
        super().__init__(tk, focus=True)
        import tkinter.font
        p = self.px
        self.tone = self.BAD if failed else self.MUTED          # the panel's red for what went wrong, its grey for a note
        width = p(560 if failed else Starting.W)                # a note as wide as the start's window it stands over
        left, right, pad = p(18), width - p(18), p(12)
        font = (self.MONO, 9) if failed else (self.words, 9)    # the launcher's own lines keep their columns
        measure = tkinter.font.Font(root=self.root, font=font)
        lines = max(1, min(NOTICE_LINES, wrapped(text, measure.measure, right - left - 2 * pad)))
        text_height = lines * measure.metrics("linespace")
        where = FAILED_AT[0] if failed else None                # the step it failed at and the times, as the start's window saw them
        top = p(104) if where else p(52)                        # the sheet, under the bar or under the logo
        well = (top, top + text_height + 2 * pad)
        height = well[1] + p(62)
        # A failure takes the start window's own place, as that window has gone; a note comes from a second click while a start
        # is under way, whose window stands in that place, so the note stands above it
        self.place(width, height, above=0 if failed else p(Starting.H + 12))
        c = self.c
        _, baseline = self.logo(left, p(11))
        pill = self.pill(title, self.tone, right, baseline - p(5))
        key = (right - p(84), height - p(46), right, height - p(16))
        fills = None
        if where:                                               # the bar where it stopped: done parts green, the failed one red
            step, took = where
            fills = [(1.0, self.rgba(self.LIT, 255)) if i < step else (0.6, self.rgba(self.BAD, 255)) if i == step
                     else (0.0, None) for i in range(3)]
            for i, x in enumerate(self.parts(left, right)):
                # the one it failed at in the first ink, the bar's red above it says it: red words fell short of 4.5:1
                c.create_text(x, p(84), anchor="w", text=STEPS[i], font=(self.SEMI if LANG != "ko" else self.HANGUL, 8) if i == step
                              else (self.words, 8), fill=self.INK if i == step else self.INK2)
            total = sum(x for x in took if x is not None)
            c.create_text(right, p(84), anchor="e", text=clock(total, tenths=True), font=self.figure, fill=self.INK2)

        def shapes(d, S, under=False):
            self.draw_pill(d, S, pill)
            if fills:
                self.bar(d, S, left, right, p(64), fills)
            # The sheet: darker than the glass and opaque, a surface to read, its top edge in shadow
            d.rounded_rectangle([S * left, S * well[0], S * right, S * well[1]], radius=S * p(4), fill=self.SUNK)
            d.line([(S * (left + p(4)), S * well[0] + S // 2), (S * (right - p(4)), S * well[0] + S // 2)], fill=(0, 0, 0, 110), width=S)
            # The key: a face a little lighter than the glass, lighter again under the pointer, and a fine line round it
            x0, y0, x1, y1 = key
            d.rounded_rectangle([S * x0, S * y0, S * x1, S * y1], radius=S * p(3),
                                fill=(255, 255, 255, self.KEY_LIT if under else self.KEY_FACE), outline=(255, 255, 255, 46), width=S)

        art = self.art(shapes)
        lit = self.art(lambda d, S: shapes(d, S, True)) if art is not None else None
        self.logo_words(art)
        if art is not None:
            c.create_image(0, 0, anchor="nw", image=art, tags="art")
        else:                                                   # plain: the edge, the sheet and the key, square
            c.create_rectangle(0, 0, width - 1, height - 1, outline=self.EDGE, tags="art")
            c.create_rectangle(left, well[0], right, well[1], outline="", fill=self.SUNK, tags="art")
        c.tag_lower("art")
        body = tk.Text(self.root, wrap="word", bd=0, highlightthickness=0, padx=0, pady=0, bg=self.SUNK, fg=self.INK2,
                       selectbackground=self.HOVER, selectforeground=self.INK, insertwidth=0, cursor="arrow", font=font)
        body.insert("1.0", text)
        body.configure(state="disabled")                        # read and copied, not typed into
        c.create_window(left + pad, well[0] + pad, anchor="nw", window=body, width=right - left - 2 * pad, height=text_height)
        body.see("end")                                         # the reason is at the end
        x0, y0, x1, y1 = key
        # The key's place, drawn plainly when there is no picture; told apart by where the pointer is either way, as the
        # picture's key is no canvas item that a click could land on
        c.create_rectangle(x0, y0, x1, y1, outline=self.EDGE if art is None else "", fill=self.BG if art is None else "",
                           tags="close-box")
        if art is not None:
            c.tag_lower("close-box", "art")
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=t("Close"), fill=self.INK, font=(self.words, 9))
        # Gone once the click or the key has been dealt with: taken away inside the canvas's own handling of the click, the
        # canvas went with it while Tk was still at work on it, and Tcl ended the program (measured on a virtual display)
        close = lambda _e=None: self.root.after_idle(self.root.destroy)
        on_key = lambda e: x0 <= e.x <= x1 and y0 <= e.y <= y1
        under = [False]

        def hover(e) -> None:                                   # the key under the pointer, a little lighter
            now = bool(e) and on_key(e)
            if now != under[0]:
                under[0] = now
                if art is None:
                    c.itemconfigure("close-box", fill=self.HOVER if now else self.BG)
                else:
                    c.itemconfigure("art", image=lit if now else art)
                c.configure(cursor="hand2" if now else "")

        c.bind("<Button-1>", lambda e: close() if on_key(e) else None)
        c.bind("<Motion>", hover)
        c.bind("<Leave>", lambda _e: hover(None))
        for k in ("<Escape>", "<Return>"):
            self.root.bind(k, close)
        if not failed:
            self.root.after(NOTE_HOLD, close)
        self.root.focus_force()


def wrapped(text: str, measure, width: int) -> int:
    """How many lines `text` takes at `width` pixels when wrapped at words as a Text widget wraps it (a word wider than
    the line is broken where it runs out), with `measure` giving a string's width."""
    count = 0
    for paragraph in text.split("\n"):
        count += 1
        line = ""
        for word in paragraph.split(" "):
            trial = f"{line} {word}" if line else word
            if measure(trial) <= width:
                line = trial
                continue
            if line:                                            # the word goes to the next line
                count += 1
            line = word
            while measure(line) > width and len(line) > 1:      # wider than a whole line: broken where it runs out
                low, high = 1, len(line) - 1                    # the longest start of it that fits, found by halves
                while low < high:
                    mid = (low + high + 1) // 2
                    low, high = (mid, high) if measure(line[:mid]) <= width else (low, mid - 1)
                count += 1
                line = line[low:]
    return count


def with_window(work, port: int):
    """Run work() (the launcher, and its wait) under the small window, and return what it returned or raise what it
    raised. The window is a courtesy: if it cannot be made, work() simply runs."""
    try:
        import tkinter
        if sys.platform == "win32":
            import ctypes
            try:   # before any window, for sharp text at 4K
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception:
                pass
        window = Starting(tkinter)
    except Exception:
        return work()

    box: dict = {}                                               # what work() came back with
    up = [False]                                                 # whether the server answers, from the asking thread

    def ask() -> None:                                           # on a thread: an unanswered request takes 0.8 s
        while "done" not in box and not up[0]:
            up[0] = server_answers(port)
            if not up[0]:
                time.sleep(0.7)

    def run_it() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:                             # raised on the main thread, below
            box["error"] = exc
        box["done"] = True

    threading.Thread(target=ask, daemon=True).start()
    threading.Thread(target=run_it, daemon=True).start()

    def watch() -> None:                                         # on tkinter's thread
        if "done" not in box:
            window.show(stage(up[0], False), False)
            window.root.after(150, watch)
        elif "error" not in box and box["value"][0] == 0:        # started: the last word, then it goes
            window.show(stage(True, True), True)
            window.close_after(DONE_HOLD)
        else:                                                    # failed: the note in its place says why, straight away
            FAILED_AT[0] = (window.step, window.times())         # ...and where, as this window saw it
            window.close()

    watch()
    window.root.mainloop()
    if "error" in box:
        raise box["error"]
    return box["value"]


class ArgumentError(Exception):
    """A shortcut whose arguments argparse refuses. Under pyw.exe there is no stderr for argparse's own message, so
    it would end with nothing said at all; this carries the message to a box instead."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str):   # argparse calls this, prints to stderr and exits; raise to show it instead
        raise ArgumentError(message)


def wsl_exe() -> str:
    """wsl.exe by its full path, in the Windows folder rather than wherever the PATH points. A 32-bit Python is shown
    a System32 without wsl.exe (Windows redirects it to SysWOW64); Sysnative is the real one, seen from there."""
    root = os.environ.get("SystemRoot", r"C:\Windows")              # always set on Windows; the default is a guess
    for folder in ("Sysnative", "System32"):                         # Sysnative exists only for a 32-bit program
        path = os.path.join(root, folder, "wsl.exe")
        if os.path.exists(path):
            return path
    return "wsl.exe"                                                 # not found where expected: let Windows look


def decode(data: bytes) -> str:
    """The output as text. The launcher writes UTF-8. wsl.exe writes its own messages (a distribution that is gone,
    a WSL that does not start) in UTF-16 unless WSL_UTF8 is honoured, which older versions of it do not do, and read
    as UTF-8 those come out with a NUL between the letters. Text from Linux never holds a NUL, so one says UTF-16,
    when the whole of it reads as UTF-16 (Korean or English alike). When it does not, output from both sides is
    mixed: read as UTF-8 with the NULs taken out, an English UTF-16 message reads too. Out here, not later: the \r
    of its \r\n, followed by a NUL, would look like a line redrawn and take the line with it."""
    if b"\x00" in data and len(data) % 2 == 0:
        try:
            return data.decode("utf-16-le")             # strict: a byte pair that is not UTF-16 means it is not
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace").replace("\x00", "")   # a cut letter: one replacement mark


def last_lines(text: str, width: int = LONGEST) -> tuple[list[str], bool]:
    """The lines a terminal would end up showing, as plain text: the last LINES that are not empty, each cut at `width`
    characters, and whether there were more than that."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):          # wsl.exe ends its lines with \r\n, Linux with \n
        line = raw.rstrip("\r").rsplit("\r", 1)[-1]            # a line redrawn with \r (a count) as it last read
        line = CONTROLS.sub("", ESCAPES.sub("", line))           # colour codes and titles out, then stray controls
        line = line.expandtabs(4).strip()                       # a box lays text out itself: no indent to keep
        if line:                                                 # blank lines only make the box taller
            lines.append(cut(line, width))
    return lines[-LINES:], len(lines) > LINES


def cut(line: str, width: int) -> str:
    """A line at most `width` characters long, its end marked where it was cut."""
    return line if len(line) <= width else line[:width - 1] + "…"


def failure_text(output: bytes, rc: int, repo: str) -> str:
    """What the failure box says: the end of what the launcher printed, and where to see all of it when the box
    holds only the end."""
    lines, more = last_lines(decode(output))
    text = "\n".join(lines) if lines else t("It ended without printing anything (exit code {rc}).", rc=rc)
    if more:   # the start of the output did not fit; the same command in a terminal prints all of it
        text += "\n\n" + t("The whole output shows with this command in the server's terminal:") + f"\ncd {shlex.quote(repo)} && ./sidenote capture --up"
    return text


def show(title: str, text: str, icon: int, dry_run: bool) -> None:
    """The note in the start's window (Notice), or where tkinter cannot make one a native message box (MessageBoxW,
    through ctypes: no package needed); with --dry-run the same words written out on stdout for a test to read."""
    if dry_run or sys.platform != "win32":
        kind = "warning" if icon == MB_ICONWARNING else "information"
        print(f"[dry-run] box: {kind}")
        print(f"[dry-run] title: {title}")
        print("[dry-run] text:")
        print(text)
        print("[dry-run] end of text")
        return
    import ctypes

    user32 = ctypes.windll.user32
    try:
        # Sharp text on a high-DPI screen: a program that does not say it is DPI aware has its box drawn small
        # and stretched by Windows, which blurs it (this PC runs 4K screens). Per-monitor v2, as capture.py does.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass   # an older Windows without it: the box is blurred, and still says the same thing
    try:
        import tkinter
        Notice(tkinter, title, text, failed=icon == MB_ICONWARNING).root.mainloop()
        return
    except Exception:
        pass   # no tkinter in this Python, or no window to be had: Windows' own box says the same
    text = "\n".join(cut(line, WIDTH) for line in text.split("\n"))   # Windows' box widens for its longest line
    user32.MessageBoxW(None, text, title, MB_OK | icon | MB_SETFOREGROUND | MB_TOPMOST)


class OneStart:
    """One start at a time for this checkout: a named mutex that this process holds while the launcher runs. The
    first start after an update builds the server image for minutes with nothing on screen, and a second double
    click would run a second `capture --up` beside it: two builds, and two capture programs if both get past the
    check that refuses a second one. The second click says that the first is still going instead.
    Windows lets the mutex go when the process ends, however it ends, so a start that crashed blocks nothing."""

    def __init__(self, distro: str, repo: str):
        self.handle = None   # the mutex while it is held
        self.busy = False    # another start of this checkout holds it
        if sys.platform != "win32":
            return           # tests on Linux: one start at a time is a Windows matter
        import ctypes

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)        # use_last_error: see below
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p                   # a HANDLE, pointer sized
        self._kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        self._kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        # Named after the distribution and the checkout, so another copy of sidenote is not held up by this one.
        # "Local\" keeps it to this Windows session; a mutex name cannot hold the backslashes of a path, hence a hash.
        key = hashlib.sha1(f"{distro}\n{repo}".encode("utf-8")).hexdigest()[:16]
        handle = self._kernel32.CreateMutexW(None, False, f"Local\\Sidenote.CaptureShortcut.{key}")
        # CreateMutexW also succeeds when the mutex already exists, and only GetLastError tells the two apart;
        # ctypes' own copy of it, since anything Python calls in between can overwrite the real one.
        if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            self._kernel32.CloseHandle(handle)
            self.busy = True
        else:
            self.handle = handle   # None when no mutex could be made at all: then the start goes on unguarded

    def release(self) -> None:
        """Let the next start in: before a failure box, so a double click while the box is open (once Docker has
        been started, say) tries again instead of being told that a start is still going."""
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


# The launcher's output while it runs, for the start's window to show its last line (latest_line): a way to read the file
# it is written to that is the window's own (reader), and a lock, as the window reads on Tk's thread while run() waits
LIVE: dict = {"read": None, "lock": threading.Lock()}


def reader(out):
    """A way to read the launcher's output file as it is written that moves nothing the launcher writes by: its handle
    and this file share one position, and a read here that moved it put the launcher's next lines over its earlier ones
    (measured: lines lost, "linline"). POSIX reads at an offset (pread), which moves nothing: the file's descriptor;
    Windows opens the file again by its name, a handle with a position of its own, sharing it as TemporaryFile made it
    (read, write and delete, for its delete on close): a file. None where neither can be had: the window shows no line."""
    if hasattr(os, "pread"):
        return out.fileno()
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                           wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        # GENERIC_READ; FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE; OPEN_EXISTING
        handle = create(str(out.name), 0x80000000, 0x7, None, 3, 0, None)
        if not handle or handle == wintypes.HANDLE(-1).value:
            return None
        return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)), "rb")
    except Exception:
        return None


def latest_line() -> str:
    """The last line the launcher has printed so far, as a terminal would show it (last_lines), its own markers left out:
    the start's window shows it under the bar, the detail of what goes on. "" when there is none yet, or no start."""
    with LIVE["lock"]:
        source = LIVE["read"]
        if source is None:
            return ""
        try:
            if isinstance(source, int):                         # POSIX: read at an offset, moving nothing
                size = os.fstat(source).st_size
                data = os.pread(source, 4096, max(0, size - 4096) & ~1)   # the end only; an even offset keeps UTF-16 aligned
            else:                                               # Windows: a handle of its own, its own position
                size = source.seek(0, os.SEEK_END)
                source.seek(max(0, size - 4096) & ~1)
                data = source.read()
        except (OSError, ValueError):                           # closed meanwhile: the start is over
            return ""
    lines = [x for x in last_lines(decode(data), 400)[0] if not x.startswith("SIDENOTE-")]
    return lines[-1] if lines else ""


def run(command: list[str]) -> tuple[int, bytes]:
    """Run the launcher in WSL with no window, and return its status and the end of what it printed.

    The output goes to a temporary file, not a pipe, and this waits for wsl.exe to end, not for the output to end:
    the capture program started at the end of the launcher lives on for the whole session, and if a handle to a
    pipe here reached it on the way, reading that pipe to its end would wait for the session to be over."""
    env = dict(os.environ, WSL_UTF8="1")   # wsl.exe's own messages in UTF-8 rather than UTF-16 (decode() reads both)
    # A SIDENOTE_LANG set on Windows crosses into WSL too (WSLENV names what does), so the launcher's lines in a box are
    # in the language of its title
    if os.environ.get("SIDENOTE_LANG", "").strip().lower() in ("en", "ko"):
        env["WSLENV"] = ":".join(part for part in (env.get("WSLENV", ""), "SIDENOTE_LANG") if part)
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0   # the flag exists on Windows only
    with tempfile.TemporaryFile() as out:  # deleted when closed, by Windows itself even if this process is killed
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=flags, env=env)
        # stdin from NUL: no terminal to read from, so the launcher's "press Enter" on a failure ([ -t 0 ]) is
        # skipped and nothing can wait for a key that no one can press. stderr into the same file, in order.
        own = reader(out)
        with LIVE["lock"]:
            LIVE["read"] = own              # the window reads its last line as it is written (latest_line)
        try:
            rc = proc.wait()                # no time limit: the first start after an update builds for minutes
        finally:
            with LIVE["lock"]:              # the window reads no more: its handle closed under the lock it reads under
                LIVE["read"] = None
                if own is not None and not isinstance(own, int):
                    own.close()
        size = out.seek(0, os.SEEK_END)     # how much was written, from the end of the file
        out.seek(max(0, size - TAIL_BYTES) & ~1)   # the end only; an even offset keeps UTF-16 aligned
        return rc, out.read()


# What the launcher prints last when WSL cannot start Windows programs ([interop] enabled=false, or no Windows drive), for
# this starter to act on (./sidenote, windows_starts): the panel to open, or the capture program to start, tab-separated.
# Before the start it may print two more lines. The language set for Sidenote (SIDENOTE_LANG, in the environment or
# .env): WSLENV carries it to a program WSL starts and nothing carries it to one started here. And the command that
# sets the Windows side up, as the launcher words it: with the wheels folder of a PC without internet (SIDENOTE_WHEELS)
# and the port set now, neither of which this file can know.
OPEN_MARK, START_MARK = "SIDENOTE-OPEN", "SIDENOTE-START"
LANG_MARK, SETUP_MARK = "SIDENOTE-LANG", "SIDENOTE-SETUP"
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP = 0x00000008, 0x00000200   # the program on its own: it outlives this starter
CONNECT_WAIT = 10.0   # seconds a capture program started here is given to connect, as the launcher gives one it starts
CAPTURE_BUSY = 76     # what capture.py ends with when another capture program runs for its server (CAPTURE_BUSY there)


MARK_LINES = 6       # the launcher's last lines a mark is looked for in: it prints its marks last (four at most)


def marked(output: bytes, mark: str) -> list[str] | None:
    """The fields after `mark` on one of the launcher's last lines that starts with it, or None when there is none. Only
    the last few lines, each cut where the launcher ended it (\n), and none holding a control character: a value printed
    on the way (a setting's name in a status, say, which a restored backup could have set) with a carriage return or
    another of the line breaks splitlines() knows read as a line of its own, and SIDENOTE-START names a program to start."""
    lines = [x[:-1] if x.endswith("\r") else x for x in decode(output).split("\n")]
    for line in reversed([x for x in lines if x.strip()][-MARK_LINES:]):
        if line.startswith(mark + "\t") and not CONTROLS.search(line) and not any(c in line for c in "\u2028\u2029"):
            return line.split("\t")[1:]
    return None


def instance_name(server: str) -> str:
    """The short name two capture programs for one server share, made as capture.py makes it (instance_name there;
    tests/capture_single.py holds the two together): the server's host and port, 127.0.0.1 for every name of this PC
    and the scheme's own port where none is written, hashed."""
    from urllib.parse import urlsplit
    text = server.strip()
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        port = parts.port or (443 if parts.scheme in ("wss", "https") else 80)
    except ValueError:            # a port that is no number, a bracket left open: the text itself is the name's source
        host, port = "", 0
    if host in ("localhost", "::1", "0.0.0.0", "::"):   # this PC under its other names: one server, one name
        host = "127.0.0.1"
    key = f"{host}:{port}" if host else text
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def guard_file(name: str) -> str:
    """The file a capture program keeps locked off Windows (OneCapture.lock_path in capture.py): in the user's runtime
    folder or else the temporary one, named for the user and the server. Off Windows this starter runs in tests only,
    and they look for a capture program the way Windows is asked for the mutex."""
    folder = os.environ.get("XDG_RUNTIME_DIR", "")
    if not os.path.isdir(folder):                              # not set, or set to what is not there
        folder = tempfile.gettempdir()
    return os.path.join(folder, f"sidenote-capture-{os.getuid()}-{name}.lock")


def capture_alive(server: str) -> bool:
    """Whether a capture program for `server` runs on this PC: whether the guard it holds while it runs is held
    (OneCapture in capture.py). The launcher could not see one that runs and is not connected just now (the server
    came up a moment ago, and the program connects again within seconds): Windows' process list is out of its reach
    here, and the server counts only what is connected. Anything that keeps the question from being asked is a no: the
    program then started refuses to be the second one itself."""
    name = instance_name(server)
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenMutexW.restype = ctypes.c_void_p             # a HANDLE, pointer sized
            kernel32.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            # Opened, never made: a mutex made here would be one more holder of the name. It opens only while a
            # program holds it, since Windows lets a mutex go with the last handle to it.
            handle = kernel32.OpenMutexW(SYNCHRONIZE, False, f"Local\\Sidenote.Capture.{name}")
        except Exception:         # no ctypes, no kernel32 as expected
            return False
        if not handle:            # no such mutex: no capture program holds one
            return False
        kernel32.CloseHandle(handle)   # held for this moment only: a program starting right now asks again (START_WAIT there)
        return True
    try:
        import fcntl
        fd = os.open(guard_file(name), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))   # opened, never made: no file, no program
    except (ImportError, OSError):
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # taken only when no program holds it
        return False                                     # and let go as the file closes
    except BlockingIOError:       # the one error that means a program holds the lock
        return True
    except OSError:               # a file system that does not lock
        return False
    finally:
        os.close(fd)


def open_panel(url: str, dry_run: bool) -> None:
    """The panel in the browser, as a second click on a running app's shortcut shows that app; with --dry-run its
    address written out for a test to read."""
    if dry_run:
        print("[dry-run] open: " + url)
    else:
        webbrowser.open(url)


def launch(command: list[str], port: int, dry_run: bool, setup_hint: str = "") -> tuple[int, bytes]:
    """The launcher in WSL, and then what it hands back when WSL cannot start Windows programs: the panel to open, or the
    capture program to start from here. Starting a Windows program from Windows asks nothing of WSL's interop, so the
    shortcut works with [interop] enabled=false too, the setting left as the user made it. A program started here is
    waited for as the launcher waits for one it starts; one that does not connect is said, with the command that shows
    why. Returns the status and what to show on a failure, as run does."""
    rc, output = run(command)
    if rc != 0:
        return rc, output
    url = marked(output, OPEN_MARK)
    # A capture program is connected already: the panel, as a second click opens it. Only this PC's panel: what Windows
    # opens is handed to its shell (os.startfile under webbrowser), which runs a program as readily as it opens a page
    if url and re.fullmatch(r"http://(127\.0\.0\.1|localhost):\d{1,5}/?", url[0]):
        open_panel(url[0], dry_run)
        return 0, output
    if url:                                  # anything else is no panel's address: said as a failure, with what was printed
        return 1, output
    start = marked(output, START_MARK)
    if not start:
        return 0, output
    # The program the launcher names is capture.py, and what is started is the capture.py beside this file, the same
    # checkout's: nothing the output names is run. An option in its place ("-c", "-m") had Python run what followed, and a
    # path elsewhere (a share's capture.py) is no program of this checkout
    if start[0].startswith("-") or os.path.basename(start[0].replace("\\", "/")).lower() != "capture.py":
        return 1, output
    start = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture.py"), *start[1:]]
    # The server the launcher handed the program, and its port (SIDENOTE_PORT now), not the shortcut's, which can be
    # older: a shortcut made before the port was changed asked the old port for ten seconds and then said the program
    # had not connected, while it had.
    server = ""
    try:
        server = start[start.index("--server") + 1]
        port = int(server.rsplit(":", 1)[1].split("/")[0])
    except (ValueError, IndexError):
        pass
    panel = f"http://127.0.0.1:{port}"   # as the launcher writes it after SIDENOTE-OPEN
    # One that runs for this server already, connected or not: the panel, and no second program beside it
    if server and capture_alive(server):
        open_panel(panel, dry_run)
        return 0, output
    missing = missing_modules()
    if missing:   # as the launcher says it where it can ask Windows Python itself, with the command that installs them
        hint = marked(output, SETUP_MARK)   # the launcher's own wording of it, when it sent one (an older launcher sends none)
        why = t("The capture packages are not in this Windows Python ({missing}). In a Windows terminal this installs them:",
                missing=", ".join(missing)) + "\n" + (hint[0] if hint and hint[0] else setup_hint)
        return 1, why.encode("utf-8")
    # pyw.exe ran this file, so this is Windows Python's windowless interpreter, the one the launcher would have used
    program = [sys.executable, "-X", "utf8", *start]
    # The language set for Sidenote in WSL, for the program's tray menu and its log: one that is set there wins over
    # Windows' display language, as it does for a program WSL starts itself
    env = dict(os.environ)
    lang = marked(output, LANG_MARK)
    if lang and lang[0] in ("en", "ko"):
        env["SIDENOTE_LANG"] = lang[0]
        if dry_run:
            print("[dry-run] env: SIDENOTE_LANG=" + lang[0])
    if dry_run:
        print("[dry-run] start: " + subprocess.list2cmdline(program))
        return 0, output
    base = capture_clients(port)
    proc = subprocess.Popen(program, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, env=env)
    waited = 0.0
    while waited < CONNECT_WAIT:
        time.sleep(0.5)
        waited += 0.5
        if capture_clients(port) > max(base, 0):
            return 0, output
        if proc.poll() is not None:   # it ended: that is the failure to show
            break
    if proc.poll() is None:   # running, not connected yet: started, as the launcher counts one Windows lists
        return 0, output
    if proc.poll() == CAPTURE_BUSY:   # another one took the guard between the look above and this start: the panel, as there
        open_panel(panel, dry_run)
        return 0, output
    # the same command in a Windows terminal, without its log file, prints why it ends
    try:
        cut = start.index("--log")
        shown = start[:cut] + start[cut + 2:]
    except ValueError:
        shown = start
    why = t("The capture program did not connect to the server. In a Windows terminal this shows why:") + "\n" \
        + subprocess.list2cmdline(["py", "-3", *shown])
    return 1, why.encode("utf-8")


# What capture.py cannot run without, as the launcher checks them (win_packages): pystray only adds the tray icon
CAPTURE_MODULES = ("mss", "soundcard", "numpy", "PIL", "websocket")
SHORTCUT_NAME = "Sidenote Capture.lnk"   # as ./sidenote shortcut names it, so either replaces the other's
OLD_SHORTCUT_NAMES = ("Sidenote 캡처.lnk",)


def setup_command(distro: str, repo: str, port: int) -> str:
    """The command that sets up the Windows side from Windows (main, --setup), for a box to show."""
    here = os.path.abspath(__file__)
    return f'py -3 "{here}" --setup --distro {distro} --repo "{repo}" --port {port}'


def missing_modules() -> list[str]:
    """What capture.py needs that this Windows Python lacks (looked up, not imported: numpy alone takes a second)."""
    return [m for m in CAPTURE_MODULES if importlib.util.find_spec(m) is None]


def ps_quote(text: str) -> str:
    """`text` for inside PowerShell's single quotes, where a quote is written twice."""
    return text.replace("'", "''")


def console_text(data: bytes) -> str:
    """What a Windows console program wrote into a pipe, as text. PowerShell 5.1 writes in the console's code page
    (cp949 on a Korean Windows) and in UTF-8 only where the console was set to it, so UTF-8 is tried first, strictly:
    text in a code page with anything but ASCII in it does not read as UTF-8."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    page = "utf-8"                # off Windows (tests) there is no code page to ask for
    if sys.platform == "win32":
        try:
            import ctypes
            number = ctypes.windll.kernel32.GetConsoleOutputCP()   # 0 with no console: then Windows' own default page
            page = f"cp{number}" if number else "oem"
        except Exception:
            page = "oem"
    try:
        return data.decode(page, errors="replace")
    except LookupError:           # a code page Python has no codec for
        return data.decode("utf-8", errors="replace")


def first_error(text: str) -> str:
    """The first thing PowerShell said went wrong, on one line. It prints an error as its message, then where in the
    script it was ("At line:1 char:95" and lines that start with +), and a script goes on after most errors, so every
    statement after the one that failed adds an error of its own: the first message is the cause. A long message comes
    wrapped over a few lines, which are put back together."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = CONTROLS.sub("", ESCAPES.sub("", raw)).strip()
        if not line or line.startswith(("#< CLIXML", "<Objs ")):   # progress written as XML into a pipe: not an error
            continue
        if line.startswith("+") or re.fullmatch(r"\S+ \S+:\d+ \S+:\d+", line):   # where it was, in any language: the message is over
            break
        lines.append(line)
        if len(lines) == 4:       # a message with no such line after it: its start says enough
            break
    return cut(" ".join(lines), 400)


def powershell(script: str) -> tuple[str, str]:
    """Run `script` in Windows PowerShell with no profile, and return what it printed and the first thing it said went
    wrong ("" when it said nothing). Its errors used to be thrown away, and a PowerShell that may not make COM objects
    (Constrained Language Mode on a managed PC) left only "PowerShell made no file" to go on."""
    # $ProgressPreference: with its output in a pipe, PowerShell 5.1 writes its progress ("Preparing modules for first
    # use") as XML on stderr, which is no error
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "$ProgressPreference = 'SilentlyContinue'; " + script]
    try:
        done = subprocess.run(command, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:   # no PowerShell, or one that hung
        return "", str(exc)
    return console_text(done.stdout or b"").strip(), first_error(console_text(done.stderr or b""))


def terminal_python(windowless: bool) -> str:
    """How a Windows terminal names the Python that runs this file: the Python launcher where there is one (py -3, and
    pyw -3 for no console window), or else this Python's own program, by its full path in quotes."""
    name = "pyw" if windowless else "py"
    if shutil.which(name + ".exe") or shutil.which(name):
        return name + " -3"
    own = os.path.join(os.path.dirname(sys.executable), "pythonw.exe") if windowless else sys.executable
    return f'"{own}"'


def setup(args, dry_run: bool) -> int:
    """What `./sidenote setup-capture` and `./sidenote shortcut` do from WSL, done here in Windows, for a WSL that cannot
    start Windows programs. Run with py -3 in a Windows terminal, so it prints as it goes: the capture packages into this
    Python, from the internet or from --wheels (docs/air-gapped.md), then the desktop shortcut, the same one the launcher
    makes (pyw.exe running this file, with the distribution, the checkout and the port)."""
    def say(text: str) -> None:
        if sys.stdout is not None:   # run by pyw.exe there is nowhere to print, and nothing else to do about it
            print(text, flush=True)

    here = os.path.dirname(os.path.abspath(__file__))
    source = ["--no-index", "--find-links", args.wheels] if args.wheels else []
    pip = [sys.executable, "-m", "pip", "install", "--user", *source, "-r", os.path.join(here, "requirements.txt")]
    say(t("Installing the capture packages into this Python ({python})", python=sys.executable))
    if dry_run:
        say("[dry-run] pip: " + subprocess.list2cmdline(pip))
    else:
        rc = subprocess.call(pip)   # its own output, as it comes: a slow download shows that it is going
        if rc != 0:
            say(t("The packages did not install (pip ended with {rc}). The lines above say why.", rc=rc))
            return 1
    # pyw.exe by its full path, as the launcher writes it: the shortcut runs with Explorer's PATH. Without the Python
    # launcher, this Python's own windowless interpreter, which takes no -3
    pyw = shutil.which("pyw.exe") or shutil.which("pyw")
    target = pyw or os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    started = f'"{os.path.abspath(__file__)}" --distro {args.distro} --repo "{args.repo}" --port {args.port}'
    arguments = ("-3 " if pyw else "") + started
    # The same start typed in a Windows terminal, for whoever keeps no shortcut on the desktop: the shortcut was the
    # one way to start the capture on a WSL that cannot start Windows programs
    typed = f"{terminal_python(windowless=True)} {started}"
    # the icon copied out of WSL, as the launcher copies it: Explorer reads it whenever it draws the shortcut
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Sidenote", "sidenote.ico")
    if dry_run:
        say(f"[dry-run] shortcut: {target} {arguments}")
        say(f"[dry-run] icon: {local}")
        say(f"[dry-run] terminal: {typed}")
        return 0
    icon = os.path.join(here, "sidenote.ico")
    try:
        os.makedirs(os.path.dirname(local), exist_ok=True)
        shutil.copyfile(icon, local)
        icon = local
    except OSError:   # the checkout's own file still serves while WSL runs
        pass
    script = (f"$d = [Environment]::GetFolderPath('Desktop'); $f = Join-Path $d '{ps_quote(SHORTCUT_NAME)}'; "
              "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($f); "
              f"$s.TargetPath = '{ps_quote(target)}'; $s.Arguments = '{ps_quote(arguments)}'; "
              f"$s.Description = '{ps_quote(t('Sidenote: start screen and sound capture (quit from the tray icon)'))}'; "
              f"$s.IconLocation = '{ps_quote(icon)},0'; $s.Save(); "
              + "".join(f"Remove-Item -LiteralPath (Join-Path $d '{ps_quote(old)}') -ErrorAction SilentlyContinue; "
                        for old in OLD_SHORTCUT_NAMES)   # one this command made under an older name
              + "if (Test-Path -LiteralPath $f) { $f }")   # the file, said back only when it is there
    made, error = powershell(script)
    if not made:   # judged by the file alone: PowerShell's own words for why, or that it said nothing
        say(t("Could not make the desktop shortcut: {error}", error=error or t("PowerShell made no file")))
        return 1
    say(t("Desktop shortcut made: {name}", name=SHORTCUT_NAME))
    say(t("A double click starts the server and the capture with no window, and a tray icon appears in the notification area."))
    say(t("To start the capture from a Windows terminal, without the shortcut:"))
    say("  " + typed)
    return 0


def remove(dry_run: bool) -> int:
    """Takes away what --setup made on the Windows side, for a WSL that cannot start Windows programs (from WSL,
    `./sidenote uninstall` does it): the desktop shortcut, under the names it has had, and the icon copied for it. The
    folder the icon was in goes only when nothing else is in it: the desktop app keeps its own files in that folder,
    and nothing but the icon is ever removed from it. The capture packages stay in this Python, which may run other
    programs that use them; the command that takes them out is printed. With --dry-run nothing is removed and what
    would be is printed."""
    def say(text: str) -> None:
        if sys.stdout is not None:   # run by pyw.exe there is nowhere to print, and nothing else to do about it
            print(text, flush=True)

    here = os.path.dirname(os.path.abspath(__file__))
    names = (SHORTCUT_NAME, *OLD_SHORTCUT_NAMES)
    base = os.environ.get("LOCALAPPDATA", "")
    # Without LOCALAPPDATA there is no folder to name: the path would be one under wherever this was started from
    folder = os.path.join(base, "Sidenote") if base else ""
    icon = os.path.join(folder, "sidenote.ico") if folder else ""
    packages = f'{terminal_python(windowless=False)} -m pip uninstall -y -r "{os.path.join(here, "requirements.txt")}"'
    failed = False
    if dry_run:
        for name in names:
            say(f"[dry-run] remove shortcut: {name}")
        if icon:
            say(f"[dry-run] remove icon: {icon}")
            say(f"[dry-run] remove folder if empty: {folder}")
    else:
        # The desktop as Windows names it now (it can be under OneDrive), where --setup made the shortcut. Each name that
        # is there is removed, and what became of it said in ASCII with its place in the list: the names hold Korean,
        # which a pipe from PowerShell 5.1 carries in a code page this would have to guess.
        script = ("$d = [Environment]::GetFolderPath('Desktop'); $i = 0; "
                  "foreach ($n in @(" + ", ".join(f"'{ps_quote(name)}'" for name in names) + ")) { "
                  "$f = Join-Path $d $n; "
                  "if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force; "
                  "if (Test-Path -LiteralPath $f) { \"left $i\" } else { \"removed $i\" } }; $i++ }")
        said, error = powershell(script)
        results = re.findall(r"^(removed|left) (\d+)\s*$", said, re.MULTILINE)
        for what, index in results:
            name = names[int(index)] if int(index) < len(names) else index
            if what == "removed":
                say(t("Shortcut removed: {name}", name=name))
            else:   # there, and still there after the removal
                say(t("Shortcut still there: {name}", name=name))
                failed = True
        if not results and not error:   # it looked and found none
            say(t("No shortcut on the desktop to remove."))
        elif error and (failed or not results):   # PowerShell did not run, stopped before it looked, or could not remove one
            say(t("Could not remove the shortcut: {error}", error=error))
            failed = True
        if icon:
            try:
                os.remove(icon)   # this one file, by its name
                say(t("Icon removed: {path}", path=icon))
            except FileNotFoundError:   # never copied, or removed before
                pass
            except OSError as exc:
                say(t("Could not remove the icon: {error}", error=exc.strerror or exc))
                failed = True
            try:
                os.rmdir(folder)   # an empty folder only: Windows and Linux both refuse one with anything in it
                say(t("Folder removed: {path}", path=folder))
            except OSError:   # something else is in it and stays, or there is no such folder
                if os.path.isdir(folder):
                    say(t("Folder kept, other files are in it: {path}", path=folder))
    say(t("The capture packages that --setup installed into this Python stay. This removes them:"))
    say("  " + packages)
    return 1 if failed else 0


# What a person types in a Windows terminal, shown under an argument error there
USAGE = ("  py -3 launch.pyw --setup --distro NAME --repo PATH [--port N] [--wheels FOLDER]\n"
         "  py -3 launch.pyw --remove")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv   # known before parsing, so even an argument error is printed, not shown
    if dry_run and sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows Python writes a pipe in cp949
    options: list[str] = []
    if "--" in argv:                       # what follows the `--` goes to `./sidenote capture --up` untouched
        cut = argv.index("--")
        argv, options = argv[:cut], argv[cut + 1:]
    parser = Parser(prog="launch.pyw",
                    description="Start the Sidenote capture program from the desktop shortcut, windowless.")
    # --distro and --repo are checked below, not by argparse: --remove needs neither
    parser.add_argument("--distro", default=None, help="the WSL distribution the checkout is in")
    parser.add_argument("--repo", default=None, help="the checkout, as a Linux path")
    parser.add_argument("--wsl", default=None, help="the wsl.exe to run (default: the one in the Windows folder)")
    parser.add_argument("--dry-run", action="store_true", help="print the message box instead of showing it")
    parser.add_argument("--port", type=int, default=8777, help="the server's port, for the small window to ask")
    parser.add_argument("--setup", action="store_true",
                        help="install the capture packages into this Python and make the desktop shortcut (for a WSL "
                             "that cannot start Windows programs); run it with py -3 in a Windows terminal")
    parser.add_argument("--wheels", default=None, help="with --setup: a folder of wheels to install from, offline")
    parser.add_argument("--remove", action="store_true",
                        help="remove the desktop shortcut and the icon that --setup made; run it with py -3 in a Windows terminal")
    # --setup and --remove are typed by a person in a Windows terminal. The window below is the shortcut's: it says the
    # capture did not start and to make the shortcut again in WSL, which is neither what happened nor what to do.
    typed = "--setup" in argv or "--remove" in argv
    try:
        args = parser.parse_args(argv)
        needed = [name for name, value in (("--distro", args.distro), ("--repo", args.repo)) if not value]
        if needed and not args.remove:
            raise ArgumentError("the following arguments are required: " + ", ".join(needed))   # as argparse words it
    except ArgumentError as exc:
        if typed and sys.stderr is not None:   # in the terminal it was typed in, with what to type
            print(t("Could not read the arguments: {error}", error=exc), file=sys.stderr)
            print(t("Usage:") + "\n" + USAGE, file=sys.stderr)
            return 2
        # a shortcut edited by hand, or one made by another version of this file (or pyw.exe, which has no terminal)
        show(FAILED, t("Could not read the shortcut's arguments: {error}", error=exc) + "\n\n"
             + t("Make the shortcut again with ./sidenote shortcut in the WSL terminal."), MB_ICONWARNING, dry_run)
        return 2

    if args.remove:   # before --setup: the two together would make what the same command then takes away
        return remove(dry_run)
    if args.setup:
        return setup(args, dry_run)
    command = [args.wsl or wsl_exe(), "-d", args.distro, "--exec", "bash", "-lc", SCRIPT, NAME, args.repo, *options]
    if dry_run:
        print("[dry-run] run: " + subprocess.list2cmdline(command))
    start = OneStart(args.distro, args.repo)
    if start.busy:   # the user clicked again while the first start is still at work: say so, and leave it be
        show(BUSY, BUSY_TEXT, MB_ICONINFORMATION, dry_run)
        return 0
    try:
        # With --dry-run nothing is shown, as with the boxes
        hint = setup_command(args.distro, args.repo, args.port)
        rc, output = (launch(command, args.port, True, hint) if dry_run
                      else with_window(lambda: launch(command, args.port, False, hint), args.port))
    except OSError as exc:   # no wsl.exe to run: WSL is not installed, or not where Windows keeps it
        start.release()
        show(FAILED, t("Could not run wsl.exe ({path}): {error}", path=command[0], error=exc.strerror or exc) + "\n\n"
             + t("Check that WSL is installed."), MB_ICONWARNING, dry_run)
        return 1
    start.release()
    if dry_run:
        print(f"[dry-run] exit: {rc}")
    if rc == 0:   # started (or the launcher found nothing to do): the tray icon says the rest
        if dry_run:
            print("[dry-run] box: none")
        return 0
    show(FAILED, failure_text(output, rc, args.repo), MB_ICONWARNING, dry_run)
    # The launcher's own status for a test to read; wsl.exe's (0xFFFFFFFF for a distribution that is gone) does not
    # fit an exit code here, and any failure is 1 then.
    return rc if 0 < rc < 256 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:   # a fault in this file: under pyw.exe it would end with no word at all, so say it
        show(FAILED, t("The shortcut's starter failed: {error}", error=f"{type(exc).__name__}: {exc}"), MB_ICONWARNING,
             "--dry-run" in sys.argv)
        sys.exit(1)
