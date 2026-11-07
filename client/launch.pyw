"""Starts the capture program from the desktop shortcut, with no console window at any point.

The shortcut that `./sidenote shortcut` makes runs this file with pyw.exe, the Python launcher that opens no console,
and this file runs `./sidenote capture --up` in WSL through wsl.exe, which gets no console window either. That
starts the server when it is down and then the capture program, so its tray icon is the one thing that appears.
The shortcut used to run wsl.exe itself: wsl.exe opens a console window for the launcher, which came up on every
start, and that window was the only place a failure was shown. A failure is shown here instead, with the last lines the
launcher printed, in a window made as the tray icon's menu is (Windows' own message box where tkinter is missing).

    pyw -3 launch.pyw --distro Ubuntu-22.04 --repo /home/you/sidenote [-- capture options]
    py -3 launch.pyw --dry-run ...    (does everything, but prints what it would show instead: for tests)

While it waits, a small window beside the notification area says what the start is at (a start that shows nothing
gives no way to tell whether it is starting): the server, then the capture program, then that the tray icon is there.
It closes by itself, takes no focus, and has no taskbar button. Without tkinter the start goes on as it did, with
nothing shown. Both windows speak the language of the boxes.

Nothing here stays running: it waits for the launcher, which returns once the capture program is up, and ends.
It writes no file of its own and adds nothing to Windows (the temporary file for the output deletes itself).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

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
SCRIPT = 'cd -- "$1" || exit; shift; exec ./sidenote capture --up "$@"'
NAME = "sidenote-shortcut"   # $0 of that shell: what bash puts in front of its own error messages

# The words of the windows and the message boxes, in English unless SIDENOTE_LANG says en or ko, or else the user's display language is
# Korean (the locale off Windows: the first of LC_ALL, LC_MESSAGES and LANG that is set). KO holds the Korean for each
# English text, character for character.
def ui_lang() -> str:
    fixed = os.environ.get("SIDENOTE_LANG", "").strip().lower()
    if fixed in ("en", "ko"):
        return fixed
    if sys.platform == "win32":
        try:
            import ctypes
            return "ko" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x12 else "en"   # LANG_KOREAN
        except Exception:   # no answer from Windows: the default
            return "en"
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "")
        if value:
            return "ko" if value.lower().startswith("ko") else "en"
    return "en"


LANG = ui_lang()
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
    "The whole output shows with this command in the server's terminal:": "전체 출력은 서버 터미널에서 이 명령으로 볼 수 있습니다:",
    "Could not read the shortcut's arguments: {error}": "바로가기의 인자를 읽지 못했습니다: {error}",
    "Make the shortcut again with ./sidenote shortcut on the server.": "서버에서 ./sidenote shortcut 으로 바로가기를 다시 만드세요.",
    "Could not run wsl.exe ({path}): {error}": "wsl.exe를 실행하지 못했습니다 ({path}): {error}",
    "Check that WSL is installed.": "WSL이 설치돼 있는지 확인하세요.",
    "The shortcut's starter failed: {error}": "바로가기 실행기에서 오류가 났습니다: {error}",
    "Server": "서버",
    "Capture": "캡처",
    "Ready": "완료",
    "Checking the server": "서버 확인 중",
    "Starting the server · the first time takes a few minutes": "서버 시작 중 · 처음엔 몇 분 걸림",
    "Starting the capture program": "캡처 프로그램 시작 중",
    "Running · quit it from the tray icon": "실행 중 · 끝내기는 트레이 아이콘에서",
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

# What a terminal acts on and a message box would print as junk: colour and cursor codes (ESC [ ... a final byte),
# a window title (ESC ] ... ending with BEL or ESC \, and never past the end of its line), and every other escape:
# ESC, any intermediate bytes, one final byte (`tput sgr0` writes ESC ( B before its ESC [ m). Then the remaining
# control characters, C1 ones included. Tab and newline are handled apart.
ESCAPES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b\n]*(?:\x07|\x1b\\)?|[ -/]*[0-~])")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


# What the small window says, in the language of the boxes. The three steps stand in a row; the line under them says
# what is going on now, as the panel says it: a short phrase, with " · " before what it adds.
STEPS = (t("Server"), t("Capture"), t("Ready"))
SAY_WSL = t("Checking the server")
SAY_SERVER = t("Starting the server · the first time takes a few minutes")
SAY_CAPTURE = t("Starting the capture program")
SAY_DONE = t("Running · quit it from the tray icon")
SERVER_SLOW = 4.0     # seconds with no answer from the server before it is taken to be starting, not just being asked
DONE_HOLD = 2600      # milliseconds the last word stays, long enough to read
NOTE_HOLD = 12000     # milliseconds a note (a start already going) stays unless closed: a failure stays until closed
NOTICE_LINES = 16     # the lines a failure shows at once; the rest is a scroll away, with the end in view
HEALTH_URL = "http://127.0.0.1:{port}/health"   # the panel's own address: Windows reaches it through WSL's forwarding


def stage(server_up: bool, waited: float, finished: bool) -> tuple[int, str]:
    """Which step the start is at (an index into STEPS) and what to say, from what can be seen from here."""
    if finished:
        return 2, SAY_DONE
    if server_up:
        return 1, SAY_CAPTURE
    return 0, SAY_SERVER if waited >= SERVER_SLOW else SAY_WSL


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


class Glass:
    """A small window beside the notification area, made as the tray icon's menu is (TRAY_MENU in capture.py): the
    panel's dark Classic glass with a lit top edge, and the name over a stroke of the yellow highlighter. On the main
    thread, where tkinter has to run."""

    # The menu's own colours: the glass, its edge and lit top, the words and the quieter words, the line under the
    # steps, the highlighter, the red of a failure and a row under the pointer; its green for what is done, and the
    # dark of what is sunk into the glass (the groove, the launcher's lines)
    BG, EDGE, TOP, INK, INK2, MUTED, TRACK, MARK, BAD, HOVER = ("#26272b", "#4a4c53", "#8a8c93", "#e3e4e5", "#cbccce", "#b0b1b4",
                                                                "#3c3d43", "#f2c744", "#ff6b6b", "#36373d")
    OK, LIT, SUNK = "#2eb67d", "#4cc08e", "#1c1d21"
    SANS, HANGUL, MONO = "Segoe UI", "Malgun Gothic", "Consolas"   # Segoe UI has no Korean, and left to itself Windows picks a fallback of its own

    def __init__(self, tk, focus: bool):
        self.tk = tk
        self.focus = focus                                      # a note to read and close takes the focus; the start's window does not
        self.root = tk.Tk()
        self.root.withdraw()                                    # nothing on screen until it is placed
        self.scale = self.root.winfo_fpixels("1i") / 96.0       # 1.0 at 100%, 2.0 at 200%: this PC runs 4K screens
        self.words = self.HANGUL if LANG == "ko" else self.SANS  # the font of what it says, for the language it says it in
        self.root.overrideredirect(True)                        # no title bar
        self.root.attributes("-topmost", True)                  # over the other windows, as a notification is
        self.root.configure(bg=self.BG)
        self.c = tk.Canvas(self.root, bg=self.BG, highlightthickness=0, bd=0)
        self.photos = []                                        # Tk forgets a picture nothing holds on to

    def px(self, n: float) -> int:
        return round(n * self.scale)

    def place(self, width: int, height: int, above: int = 0) -> None:
        """Its size, at the bottom right of the screen over the taskbar (and `above` pixels higher, over another window
        there), and then on screen."""
        self.width, self.height = width, height
        self.c.configure(width=width, height=height)
        self.c.pack()
        work = self.work_area()                                 # the screen less the taskbar
        self.root.geometry(f"{width}x{height}+{work[2] - width - self.px(16)}+{work[3] - height - self.px(16) - above}")
        self.root.update_idletasks()
        self.dress()
        self.root.deiconify()

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
        """Windows only, each an extra: no taskbar button, no focus on a click unless it is to be read and closed, and
        Windows 11's rounded corners."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW | (0 if self.focus else WS_EX_NOACTIVATE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            corner = ctypes.c_int(3)                             # DWMWCP_ROUNDSMALL: this design is nearly square
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))   # DWMWA_WINDOW_CORNER_PREFERENCE
            # No acrylic: it paints over what Tk draws, which carries no alpha, and the window showed its tint with no words on it.
            # The glass is drawn instead (art), and the window is a little see-through
            self.root.attributes("-alpha", 0.97)
        except Exception:
            pass

    def art(self, shapes):
        """The glass and the shapes on it as one picture, drawn three times over and brought down as the tray menu draws its
        own (Tk draws shapes unsmoothed on Windows): a little lighter at the top with a soft light at its top left, its edge
        and lit top. shapes(draw, S) draws on it, S the times over. None without Pillow: the window keeps to plain shapes
        then (it comes with the capture packages, in the same Windows Python the shortcut runs)."""
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageTk
        except Exception:
            return None
        try:
            return self._art(shapes, Image, ImageDraw, ImageFilter, ImageTk)
        except Exception:                                       # any slip in the drawing: plain shapes, and the window goes on
            return None

    def _art(self, shapes, Image, ImageDraw, ImageFilter, ImageTk):
        S, w, h = 3, self.width, self.height
        img = Image.new("RGBA", (w * S, h * S))
        d = ImageDraw.Draw(img)
        top, bottom = mix("#ffffff", self.BG, 0.035), mix("#000000", self.BG, 0.09)
        for y in range(h * S):
            d.line([(0, y), (w * S, y)], fill=mix(bottom, top, y / (h * S)))
        pool = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(pool).ellipse([-w * S * 0.25, -h * S * 1.1, w * S * 0.65, h * S * 0.55], fill=(255, 255, 255, 13))
        img.alpha_composite(pool.filter(ImageFilter.GaussianBlur(h * S * 0.22)))
        d = ImageDraw.Draw(img)
        shapes(d, S)
        d.rectangle([0, 0, w * S - 1, h * S - 1], outline=self.EDGE, width=S)
        d.line([(S, S // 2), (w * S - S, S // 2)], fill=self.TOP, width=S)
        photo = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=self.root)
        self.photos = self.photos[-3:] + [photo]
        return photo

    def name(self, left: int, baseline: int) -> tuple:
        """The name and "capture" beside it, on one baseline (set by their middles, the smaller one sat high); returns the
        name's box, for the stroke under it."""
        import tkinter.font
        c, p = self.c, self.px
        big = tkinter.font.Font(root=self.root, family=self.SANS, size=12, weight="bold")
        small = tkinter.font.Font(root=self.root, family=self.SANS, size=9)
        self.fonts = [big, small]                               # a font nothing holds on to goes, and its words with it
        title = c.create_text(left, baseline - big.metrics("ascent"), anchor="nw", text="sidenote", fill=self.INK, font=big)
        box = c.bbox(title)
        c.create_text(box[2] + p(9), baseline - small.metrics("ascent"), anchor="nw", text="capture", fill=self.MUTED, font=small)
        return box

    def stroke(self, d, S, box) -> None:
        """The highlighter's stroke under the name, as on the panel's bar."""
        x0, _, x1, y1 = box
        p = self.px
        d.polygon([(S * (x0 - p(1)), S * (y1 - p(4))), (S * (x1 + p(3)), S * (y1 - p(5))), (S * (x1 + p(1)), S * (y1 - p(1))),
                   (S * (x0 - p(3)), S * y1)], fill=self.MARK)

    def backdrop(self, shapes, box):
        """The picture under the words, at the back of the canvas; the plain edge and stroke where Pillow is missing."""
        c, p = self.c, self.px
        art = self.art(lambda d, S: (self.stroke(d, S, box), shapes(d, S)))
        if art is not None:
            c.create_image(0, 0, anchor="nw", image=art, tags="art")
        else:
            x0, _, x1, y1 = box
            c.create_rectangle(0, 0, self.width - 1, self.height - 1, outline=self.EDGE, tags="art")
            c.create_line(0, 1, self.width, 1, fill=self.TOP, tags="art")
            c.create_polygon(x0 - p(1), y1 - p(4), x1 + p(3), y1 - p(5), x1 + p(1), y1 - p(1), x0 - p(3), y1, fill=self.MARK,
                             outline="", tags="art")
        c.tag_lower("art")
        return art


class Starting(Glass):
    """The window for as long as the start takes: the three steps as pills (done, under way, still to come), a groove
    that rises through each step and is full once the start is done, and what is going on now. It takes no focus, and a
    click hides it while the start goes on."""

    W, H, PAD = 400, 156, 22                                    # its size and its margins, at 100%

    def __init__(self, tk):
        super().__init__(tk, focus=False)
        self.c.bind("<Button-1>", lambda _e: self.root.withdraw())   # in the way: a click hides it, the start goes on
        self.step, self.say, self.finished, self.started = 0, SAY_WSL, False, time.monotonic()
        self.since = time.monotonic()                           # when the step under way began
        self.phase = 0.0                                        # where the moving light is along the filled part, 0 to 1
        self.fill = 0.0                                         # how far the groove is filled, 0 to 1, as drawn
        self.tick = None                                        # the next frame, asked of Tk: called off when the window goes
        self.drawn = None                                       # the step, words and end the picture shows
        self.place(self.px(self.W), self.px(self.H))
        self.draw()

    def show(self, step: int, say: str, finished: bool) -> None:
        if step != self.step:
            self.since = time.monotonic()
        self.step, self.say, self.finished = step, say, finished

    def goal(self) -> float:
        """How far the groove should be: the steps done, and the one under way filling quickly at first and then ever
        more slowly, never past most of its part; all of it once the start is done."""
        if self.finished:
            return 1.0
        waited = time.monotonic() - self.since
        return (self.step + 0.85 * (1 - 1 / (1 + waited / 6))) / 3

    def frame(self) -> None:
        """What changes with the step: the glass, the pills and the words, drawn once for each."""
        c, p = self.c, self.px
        c.delete("all")
        left, right = p(self.PAD), self.width - p(self.PAD)
        box = self.name(left, p(30))
        gap, top, bottom = p(10), p(52), p(80)
        part = (right - left - 2 * gap) / 3
        state = ["done" if i < self.step or self.finished else "now" if i == self.step else "later" for i in range(3)]
        groove = (p(96), p(102))
        self.groove = (left, right, groove)

        def shapes(d, S):
            for i, st in enumerate(state):
                x0 = left + i * (part + gap)
                fill = {"done": mix(self.OK, self.BG, 0.16), "now": mix(self.MARK, self.BG, 0.12), "later": self.SUNK}[st]
                line = {"done": mix(self.OK, self.BG, 0.45), "now": mix(self.MARK, self.BG, 0.7), "later": None}[st]
                d.rounded_rectangle([S * x0, S * top, S * (x0 + part), S * bottom], radius=S * (bottom - top) / 2, fill=fill,
                                    outline=line, width=S)
                if st == "later":                                # sunk: its top edge in shadow, round ends and flat alike
                    r = (bottom - top) / 2
                    d.arc([S * x0, S * top, S * (x0 + 2 * r), S * bottom], 205, 270, fill="#141518", width=S)
                    d.line([(S * (x0 + r), S * top + S / 2), (S * (x0 + part - r), S * top + S / 2)], fill="#141518", width=S)
                    d.arc([S * (x0 + part - 2 * r), S * top, S * (x0 + part), S * bottom], 270, 335, fill="#141518", width=S)
                mid, cx = (top + bottom) / 2, x0 + p(15)
                if st == "done":                                  # a check
                    d.line([(S * (cx - p(4)), S * mid), (S * (cx - p(1)), S * (mid + p(3))), (S * (cx + p(4.5)), S * (mid - p(3.5)))],
                           fill=self.LIT, width=round(S * p(1.8)), joint="curve")
                else:
                    r = p(3.5)
                    d.ellipse([S * (cx - r), S * (mid - r), S * (cx + r), S * (mid + r)],
                              fill=self.MARK if st == "now" else None, outline=None if st == "now" else self.MUTED, width=S)
            d.rounded_rectangle([S * left, S * groove[0], S * right, S * groove[1]], radius=S * 3, fill=self.SUNK)
            if not self.finished:                                # the seconds' pill, level with the name
                d.rounded_rectangle([S * (right - p(48)), S * p(14), S * right, S * p(36)], radius=S * p(11),
                                    fill=mix("#ffffff", self.BG, 0.06))

        if self.backdrop(shapes, box) is None:                  # plain: the same pills and groove, square
            for i, st in enumerate(state):
                x0 = left + i * (part + gap)
                c.create_rectangle(x0, top, x0 + part, bottom, outline={"done": self.OK, "now": self.MARK, "later": self.EDGE}[st],
                                   fill={"done": mix(self.OK, self.BG, 0.16), "now": mix(self.MARK, self.BG, 0.12), "later": self.SUNK}[st])
            c.create_rectangle(left, groove[0], right, groove[1], outline="", fill=self.SUNK)
            for i, st in enumerate(state):                       # the check and the dot, as the picture has them
                mid, cx = (top + bottom) / 2, left + i * (part + gap) + p(15)
                if st == "done":
                    c.create_line(cx - p(4), mid, cx - p(1), mid + p(3), cx + p(4.5), mid - p(3.5), fill=self.LIT, width=p(1.8),
                                  capstyle="round", joinstyle="round")
                else:
                    r = p(3.5)
                    c.create_oval(cx - r, mid - r, cx + r, mid + r, fill=self.MARK if st == "now" else "",
                                  outline="" if st == "now" else self.MUTED)
        for i, st in enumerate(state):
            x0 = left + i * (part + gap)
            c.create_text(x0 + p(26), (top + bottom) / 2, anchor="w", text=STEPS[i],
                          fill={"done": self.LIT, "now": self.INK, "later": self.MUTED}[st],
                          font=(self.words, 9, "bold") if st == "now" else (self.words, 9))
        c.create_text(left, p(126), anchor="w", text=self.say, width=right - left, fill=self.INK2, font=(self.words, 9))
        self.seconds = None if self.finished else c.create_text(right - p(24), p(25), text="", fill=self.MUTED, font=(self.words, 8))
        # the groove's fill, and the light that runs along it while the start is under way, drawn on the picture
        self.bar = c.create_line(0, 0, 0, 0, fill=self.MARK, width=groove[1] - groove[0], capstyle="round", state="hidden")
        self.light = None if self.finished else c.create_line(0, 0, 0, 0, fill=self.INK, width=groove[1] - groove[0], capstyle="round",
                                                             state="hidden")
        self.drawn = (self.step, self.say, self.finished)

    def draw(self) -> None:
        """One frame: the picture again only when the step has changed; the seconds, the fill and the light each time.
        The next frame is asked for whatever happens in this one: a slip that ended it left the window still."""
        try:
            if self.drawn != (self.step, self.say, self.finished):
                self.frame()
            c = self.c
            if self.seconds is not None:                        # the seconds move even when nothing else does: it is alive
                c.itemconfigure(self.seconds, text=t("{n}s", n=int(time.monotonic() - self.started)))
            left, right, (y0, y1) = self.groove
            self.fill += (self.goal() - self.fill) * (0.3 if self.finished else 0.08)   # it rises to where it should be
            mid, end = (y0 + y1) / 2, left + (right - left) * self.fill
            r = (y1 - y0) / 2
            if end - left > 2 * r:                              # shown once it is longer than its round ends
                c.coords(self.bar, left + r, mid, end - r, mid)
                c.itemconfigure(self.bar, state="normal")
            if self.light is not None:                          # a short light running along what is filled
                span = max(0.0, end - left - 2 * r)
                x = left + r + span * self.phase
                if span > 0:
                    c.coords(self.light, max(left + r, x - p_len(span)), mid, x, mid)
                    c.itemconfigure(self.light, state="normal")
            self.phase = (self.phase + 0.02) % 1.0
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
        self.root.after(ms, self.close)


def p_len(span: float) -> float:
    """The moving light's length: a fifth of what is filled, kept between 12 and 60 pixels."""
    return max(12.0, min(60.0, span / 5))


class Notice(Glass):
    """What a box would say, in the start's window: a pill with a red dot and what went wrong, or a quiet one before a
    note, as the tray menu's state pill is; the end of what the launcher printed, sunk into the glass in its own columns,
    to select and copy; and a raised Close key. Esc, Enter or Close takes it away; a note goes by itself after NOTE_HOLD,
    and a failure stays until it is closed."""

    def __init__(self, tk, title: str, text: str, failed: bool):
        super().__init__(tk, focus=True)
        import tkinter.font
        p = self.px
        self.tone = self.BAD if failed else self.MUTED          # the panel's red for what went wrong, its grey for a note
        width = p(560 if failed else 400)
        left, right, pad = p(22), width - p(22), p(12)
        font = (self.MONO, 9) if failed else (self.words, 9)    # the launcher's own lines keep their columns
        measure = tkinter.font.Font(root=self.root, font=font)
        lines = max(1, min(NOTICE_LINES, wrapped(text, measure.measure, right - left - 2 * pad)))
        text_height = lines * measure.metrics("linespace")
        top = p(90)                                             # under the pill
        well = (top, top + text_height + 2 * pad)               # the sunk part that holds the lines
        height = well[1] + p(70)
        # A failure takes the start window's own place, as that window has gone; a note comes from a second click while a start
        # is under way, whose window stands in that place, so the note stands above it
        self.place(width, height, above=0 if failed else p(Starting.H + 12))
        c = self.c
        box = self.name(left, p(30))
        bold = tkinter.font.Font(root=self.root, font=(self.words, 10, "bold"))
        pill_right = min(right, left + p(40) + bold.measure(title))
        key = (right - p(84), height - p(52), right, height - p(20))

        def shapes(d, S, lit=False):
            d.rounded_rectangle([S * left, S * p(48), S * pill_right, S * p(74)], radius=S * p(13), fill=mix(self.tone, self.BG, 0.15))
            r, cx, cy = p(3.5), left + p(15), p(61)
            d.ellipse([S * (cx - r), S * (cy - r), S * (cx + r), S * (cy + r)], fill=self.tone)
            d.rounded_rectangle([S * left, S * well[0], S * right, S * well[1]], radius=S * p(8), fill=self.SUNK)
            d.arc([S * left, S * well[0], S * right, S * (well[0] + p(16))], 200, 340, fill="#131417", width=S)   # its top in shadow
            x0, y0, x1, y1 = key                                 # the key stands up: lit above, shadow below
            d.rounded_rectangle([S * x0, S * (y0 + 1), S * x1, S * (y1 + 1)], radius=S * p(7), fill="#18191c")
            d.rounded_rectangle([S * x0, S * y0, S * x1, S * y1], radius=S * p(7), fill=mix("#ffffff", self.BG, 0.12 if lit else 0.07),
                                outline=mix("#ffffff", self.BG, 0.16), width=S)

        art = self.backdrop(shapes, box)
        lit = self.art(lambda d, S: (self.stroke(d, S, box), shapes(d, S, True))) if art is not None else None
        if art is None:                                         # plain: the pill and the sunk part, square
            c.create_rectangle(left, p(48), pill_right, p(74), outline="", fill=mix(self.tone, self.BG, 0.15))
            c.create_oval(left + p(11.5), p(57.5), left + p(18.5), p(64.5), outline="", fill=self.tone)
            c.create_rectangle(left, well[0], right, well[1], outline="", fill=self.SUNK)
        c.create_text(left + p(27), p(61), anchor="w", text=title, fill=self.INK, font=(self.words, 10, "bold"))
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
            window.show(*stage(up[0], time.monotonic() - window.started, False), False)
            window.root.after(150, watch)
        elif "error" not in box and box["value"][0] == 0:        # started: the last word, then it goes
            window.show(*stage(True, 0, True), True)
            window.close_after(DONE_HOLD)
        else:                                                    # failed: the note in its place says why, straight away
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
        rc = proc.wait()                    # no time limit: the first start after an update builds for minutes
        size = out.seek(0, os.SEEK_END)     # how much was written, from the end of the file
        out.seek(max(0, size - TAIL_BYTES) & ~1)   # the end only; an even offset keeps UTF-16 aligned
        return rc, out.read()


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
    parser.add_argument("--distro", required=True, help="the WSL distribution the checkout is in")
    parser.add_argument("--repo", required=True, help="the checkout, as a Linux path")
    parser.add_argument("--wsl", default=None, help="the wsl.exe to run (default: the one in the Windows folder)")
    parser.add_argument("--dry-run", action="store_true", help="print the message box instead of showing it")
    parser.add_argument("--port", type=int, default=8777, help="the server's port, for the small window to ask")
    try:
        args = parser.parse_args(argv)
    except ArgumentError as exc:   # a shortcut edited by hand, or one made by another version of this file
        show(FAILED, t("Could not read the shortcut's arguments: {error}", error=exc) + "\n\n"
             + t("Make the shortcut again with ./sidenote shortcut on the server."), MB_ICONWARNING, dry_run)
        return 2

    command = [args.wsl or wsl_exe(), "-d", args.distro, "--exec", "bash", "-lc", SCRIPT, NAME, args.repo, *options]
    if dry_run:
        print("[dry-run] run: " + subprocess.list2cmdline(command))
    start = OneStart(args.distro, args.repo)
    if start.busy:   # the user clicked again while the first start is still at work: say so, and leave it be
        show(BUSY, BUSY_TEXT, MB_ICONINFORMATION, dry_run)
        return 0
    try:
        # With --dry-run nothing is shown, as with the boxes
        rc, output = run(command) if dry_run else with_window(lambda: run(command), args.port)
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
