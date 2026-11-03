"""Starts the capture program from the desktop shortcut, with no console window at any point.

The shortcut that `./sidenote shortcut` makes runs this file with pyw.exe, the Python launcher that opens no console,
and this file runs `./sidenote capture --up` in WSL through wsl.exe, which gets no console window either. That
starts the server when it is down and then the capture program, so its tray icon is the one thing that appears.
The shortcut used to run wsl.exe itself: wsl.exe opens a console window for the launcher, which came up on every
start, and that window was the only place a failure was shown. A failure is shown here instead, in a small Windows
message box with the last lines the launcher printed.

    pyw -3 launch.pyw --distro Ubuntu-22.04 --repo /home/you/sidenote [-- capture options]
    py -3 launch.pyw --dry-run ...    (does everything, but prints the box instead of showing it: for tests)

While it waits, a small window beside the notification area says what the start is at (a start that shows nothing
gives no way to tell whether it is starting): the server, then the capture program, then that the tray icon is there.
It closes by itself, takes no focus, and has no taskbar button. Without tkinter the start goes on as it did, with
nothing shown.

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

# The words of the message boxes, in English unless SIDENOTE_LANG says en or ko, or else the user's display language is
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
    "Could not start the Sidenote capture": "Sidenote 캡처를 시작하지 못했습니다",
    "The Sidenote capture is starting": "Sidenote 캡처를 시작하는 중입니다",
    "The capture started from the shortcut is still getting ready. The first start, and the first after an update, can "
    "take a few minutes to build the server image. The tray icon appears in the notification area when it is done.\n\n"
    "If it takes too long, check with ./sidenote status in the server's terminal.":
        "바로가기로 시작한 캡처가 아직 준비 중입니다. 서버를 처음 켜거나 업데이트한 뒤에는 서버 이미지를 "
        "만드느라 몇 분 걸릴 수 있습니다. 끝나면 알림 영역에 트레이 아이콘이 나타납니다.\n\n"
        "너무 오래 걸리면 서버 터미널에서 ./sidenote status 로 확인하세요.",
    "It ended without printing anything (exit code {rc}).": "아무것도 출력하지 않고 끝났습니다 (종료 코드 {rc}).",
    "The whole output shows with this command in the server's terminal:": "전체 출력은 서버 터미널에서 이 명령으로 볼 수 있습니다:",
    "Could not read the shortcut's arguments: {error}": "바로가기의 인자를 읽지 못했습니다: {error}",
    "Make the shortcut again with ./sidenote shortcut on the server.": "서버에서 ./sidenote shortcut 으로 바로가기를 다시 만드세요.",
    "Could not run wsl.exe ({path}): {error}": "wsl.exe를 실행하지 못했습니다 ({path}): {error}",
    "Check that WSL is installed.": "WSL이 설치돼 있는지 확인하세요.",
    "The shortcut's starter failed: {error}": "바로가기 실행기에서 오류가 났습니다: {error}",
}


def t(text: str, **values) -> str:
    """`text` in LANG, its {placeholders} filled from `values` (the values themselves are not read for placeholders)."""
    out = KO.get(text, text) if LANG == "ko" else text
    if not values:
        return out
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), out)


# The two message boxes this can show, and what they say at the top.
FAILED = t("Could not start the Sidenote capture")
BUSY = t("The Sidenote capture is starting")
BUSY_TEXT = t("The capture started from the shortcut is still getting ready. The first start, and the first after an update, can "
              "take a few minutes to build the server image. The tray icon appears in the notification area when it is done.\n\n"
              "If it takes too long, check with ./sidenote status in the server's terminal.")

# MessageBoxW flags: one OK button, the icon, and in front of other windows. The box may come minutes after the
# double click (the first start builds the server image), when another window has the focus and Windows would
# otherwise leave it behind that window with only a blinking taskbar button to say it is there.
MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000

LINES = 15            # the last lines a box shows: the reason is at the end, and a box taller than the screen hides it
WIDTH = 160           # characters per line before it is cut short: a long line widens the whole box
TAIL_BYTES = 65536    # how much of the end of the output is read: far more than LINES lines, at any build's length
ERROR_ALREADY_EXISTS = 183   # what GetLastError says after CreateMutexW opened a mutex someone else had made

# What a terminal acts on and a message box would print as junk: colour and cursor codes (ESC [ ... a final byte),
# a window title (ESC ] ... ending with BEL or ESC \, and never past the end of its line), and every other escape:
# ESC, any intermediate bytes, one final byte (`tput sgr0` writes ESC ( B before its ESC [ m). Then the remaining
# control characters, C1 ones included. Tab and newline are handled apart.
ESCAPES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b\n]*(?:\x07|\x1b\\)?|[ -/]*[0-~])")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


# What the small window says, always in English. The three steps stand in a row; the line under them says what is going on now.
STEPS = ("Server", "Capture", "Ready")
SAY_WSL = "Checking the server"
SAY_SERVER = "Starting the server. The first time takes a few minutes"
SAY_CAPTURE = "Starting the capture program"
SAY_DONE = "Running. Quit it from the tray icon"
SERVER_SLOW = 4.0     # seconds with no answer from the server before it is taken to be starting, not just being asked
DONE_HOLD = 2600      # milliseconds the last word stays, long enough to read
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


class Starting:
    """The small window, for as long as the start takes. On the main thread, where tkinter has to run; the launcher
    waits on another. Made like the panel's right column: a little see-through, a lit top edge, and the name
    over a stroke of the yellow highlighter."""

    BG, EDGE, INK, MUTED, TRACK, PEN, MARK, RED = ("#2b2c31", "#6a6c73", "#f1f1f2", "#c4c5c9", "#44464d", "#f1f1f2", "#f2c744", "#d92b2b")

    def __init__(self, tk):
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()                                    # nothing on screen until it is placed
        self.scale = self.root.winfo_fpixels("1i") / 96.0       # 1.0 at 100%, 2.0 at 200%: this PC runs 4K screens
        self.width, self.height = self.px(392), self.px(118)
        self.root.overrideredirect(True)                        # no title bar, so no focus taken from the window in use
        self.root.attributes("-topmost", True)                  # over the other windows, as a notification is
        self.root.configure(bg=self.BG)
        work = self.work_area()                                 # the screen less the taskbar
        self.root.geometry(f"{self.width}x{self.height}+{work[2] - self.width - self.px(16)}+{work[3] - self.height - self.px(16)}")
        self.c = tk.Canvas(self.root, width=self.width, height=self.height, bg=self.BG, highlightthickness=1, highlightbackground=self.EDGE, bd=0)
        self.c.pack()
        self.c.bind("<Button-1>", lambda _e: self.root.withdraw())   # in the way: a click hides it, the start goes on
        self.font = "Segoe UI"                                  # this window is in English; on every Windows
        self.step, self.say, self.finished, self.started = 0, SAY_WSL, False, time.monotonic()
        self.phase = 0.0                                        # where the moving part of the bar is, 0 to 1
        self.root.update_idletasks()
        self.dress()
        self.root.deiconify()
        self.draw()

    def px(self, n: float) -> int:
        return round(n * self.scale)

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
        """Windows only, each an extra: no taskbar button and no focus on a click, and Windows 11's rounded corners."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            corner = ctypes.c_int(3)                             # DWMWCP_ROUNDSMALL: this design is nearly square
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))   # DWMWA_WINDOW_CORNER_PREFERENCE
            # No acrylic: it paints over what Tk draws, which carries no alpha, and the window showed its tint with no words on it.
            # Plainly a little see-through instead.
            self.root.attributes("-alpha", 0.97)
        except Exception:
            pass

    def show(self, step: int, say: str, finished: bool) -> None:
        self.step, self.say, self.finished = step, say, finished

    def draw(self) -> None:
        """One frame: the wordmark and seconds, the three steps, the bar, the line of what is going on."""
        c, p = self.c, self.px
        c.delete("all")
        left, right = p(18), self.width - p(18)
        c.create_line(0, 1, self.width, 1, fill="#8a8c93")       # the lit top edge of the glass
        title = c.create_text(left, p(21), anchor="w", text="sidenote", fill=self.INK, font=(self.font, 12, "bold"))
        x0, _, x1, y1 = c.bbox(title)
        c.create_polygon(x0 - p(1), y1 - p(4), x1 + p(3), y1 - p(5), x1 + p(1), y1 - p(1), x0 - p(3), y1, fill=self.MARK, outline="")   # the stroke, under the name
        c.tag_raise(title)
        c.create_text(x1 + p(10), p(22), anchor="w", text="capture", fill=self.MUTED, font=(self.font, 9))
        if not self.finished:                                   # the seconds move even when nothing else does: it is alive
            c.create_text(right, p(22), anchor="e", text=f"{int(time.monotonic() - self.started)}s", fill=self.MUTED, font=(self.font, 9))
        # the bar: three equal parts, done ones filled, the current one with a light moving along it
        gap, top, height = p(6), p(42), p(4)
        part = (right - left - 2 * gap) / 3
        for i in range(3):
            x0 = left + i * (part + gap)
            done = i < self.step or self.finished
            c.create_rectangle(x0, top, x0 + part, top + height, fill=self.MARK if done else self.TRACK, outline="")
            if i == self.step and not self.finished:
                width = part * 0.4
                x = x0 + (part + width) * self.phase - width
                c.create_rectangle(max(x0, x), top, min(x0 + part, x + width), top + height, fill=self.PEN, outline="")
            c.create_text(x0, top + p(16), anchor="w", text=STEPS[i], fill=self.INK if i <= self.step else self.MUTED, font=(self.font, 8))
        c.create_text(left, p(94), anchor="w", text=self.say, width=right - left, fill=self.INK, font=(self.font, 9))
        self.phase = (self.phase + 0.012) % 1.0
        self.root.after(33, self.draw)                          # 30 frames a second, for a few seconds or minutes

    def close_after(self, ms: int) -> None:
        self.root.after(ms, self.root.destroy)


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
        else:                                                    # failed: the box says why, straight away
            window.root.destroy()

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


def last_lines(text: str) -> tuple[list[str], bool]:
    """The lines a terminal would end up showing, as plain text: the last LINES that are not empty, and whether
    there were more than that."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):          # wsl.exe ends its lines with \r\n, Linux with \n
        line = raw.rstrip("\r").rsplit("\r", 1)[-1]            # a line redrawn with \r (a count) as it last read
        line = CONTROLS.sub("", ESCAPES.sub("", line))           # colour codes and titles out, then stray controls
        line = line.expandtabs(4).strip()                       # a box lays text out itself: no indent to keep
        if line:                                                 # blank lines only make the box taller
            lines.append(line if len(line) <= WIDTH else line[:WIDTH - 1] + "…")
    return lines[-LINES:], len(lines) > LINES


def failure_text(output: bytes, rc: int, repo: str) -> str:
    """What the failure box says: the end of what the launcher printed, and where to see all of it when the box
    holds only the end."""
    lines, more = last_lines(decode(output))
    text = "\n".join(lines) if lines else t("It ended without printing anything (exit code {rc}).", rc=rc)
    if more:   # the start of the output did not fit; the same command in a terminal prints all of it
        text += "\n\n" + t("The whole output shows with this command in the server's terminal:") + f"\ncd {shlex.quote(repo)} && ./sidenote capture --up"
    return text


def show(title: str, text: str, icon: int, dry_run: bool) -> None:
    """A native message box (MessageBoxW, through ctypes: no package needed), or with --dry-run the same box written
    out on stdout for a test to read."""
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
