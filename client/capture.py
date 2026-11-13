"""Windows capture client for sidenote.

Runs on Windows (native Python, NOT inside WSL; WSL can't see the Windows
screen/audio). Captures the screen + system audio (WASAPI loopback) and streams
them to the WSL analysis server over a WebSocket.

Started by `./sidenote capture` it runs without a window: a notification area icon opens the panel and ends it,
as does `./sidenote capture-stop`. With `--console` (or run by hand as below) it is a foreground console program
that Ctrl+C stops. It installs nothing resident and adds no startup entry.

Run:
    python capture.py --server ws://127.0.0.1:8777/ingest
    python capture.py --server ws://127.0.0.1:8777/ingest --no-audio
    python capture.py --list-monitors
(Normally started by `./sidenote capture` in WSL, which passes the right --server.)
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import queue
import re
import secrets
import socket
import sys
import threading
import time
import warnings

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter
import websocket  # websocket-client (sync)

# mss and soundcard are imported lazily inside the capture loops so this module
# stays importable (for --help, --list-monitors, and off-Windows tests) on a box
# that only has the pure-Python deps.


# ---------- the words it shows: its console lines, the tray menu, the notification ----------
# Written in English; KO holds the Korean for each, character for character (tests/i18n_check.py holds every t() to it). The lines
# of measurements alone (a frame's size, what the looks cost) stay in English, numbers for a report as the server's log is; a line
# that also says why (the sound dropped, and by whom) is translated with the rest. The language is English unless SIDENOTE_LANG
# says ko (./sidenote passes on the one it was given, from .env or the environment). The system's language is not read: a
# Korean Windows gave a capture in Korean beside a guide in English and a launcher that follows its terminal's locale.
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
# The capture's logo beside this file: Sidenote's own wordmark and "capture" after it (scratch/panel-tools/make_capture_logo.py),
# which the tray's menu and the shortcut's windows show at their top
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")

KO = {
    "The server asked this program to quit (./sidenote capture-stop)": "서버가 종료를 요청했습니다 (./sidenote capture-stop)",
    "Another capture program now feeds this server ({by}): this one stops": "다른 캡처 프로그램이 이제 이 서버에 보냅니다 ({by}): 이쪽은 멈춥니다",
    "New code was deployed: restarting at a quiet moment (./sidenote up)": "새 코드가 배포되어 한가할 때 다시 시작합니다 (./sidenote up)",
    "A restart at a quiet moment was asked for: not taken by this program (--no-auto-update)": "한가할 때 다시 시작하라는 요청은 받지 않음 (--no-auto-update)",
    "The server asked this program to restart (./sidenote capture-restart)": "서버가 다시 시작을 요청했습니다 (./sidenote capture-restart)",
    # the same two under the desktop app, which has no ./sidenote to name
    "The server asked this program to quit": "서버가 종료를 요청했습니다",
    "The server asked this program to restart": "서버가 다시 시작을 요청했습니다",
    "Not connected to the server, so nothing can be sent (--once)": "서버에 연결되지 않아 보낼 수 없습니다 (--once)",
    "Not taking the screen until the server is connected": "서버에 연결될 때까지 화면을 받지 않습니다",
    "Connected to the server again": "서버에 다시 연결됐습니다",
    "Screen capture is off in the panel, so nothing was sent (--once)": "화면 캡처가 패널에서 꺼져 있어 보내지 않았습니다 (--once)",
    "Could not load the sound library, going on without sound: {error}": "소리 라이브러리를 읽지 못해 소리 없이 계속합니다: {error}",
    "Not taking sound until the server is connected": "서버에 연결될 때까지 소리를 받지 않습니다",
    "Cannot read the new capture.py, going on with the code running now ({why})": "새 capture.py를 읽을 수 없어 지금 코드로 계속합니다 ({why})",
    "Waiting for the screen and the server to be quiet, to restart into the new code.": "새 코드로 다시 시작하려고 화면과 서버가 쉬기를 기다립니다.",
    "Restarting into the new capture.py.": "새 capture.py로 다시 시작합니다.",
    "A menu action failed ({error})": "메뉴 동작이 실패했습니다 ({error})",
    "Could not show the tray menu (exit code {code}, {n} in a row)": "트레이 메뉴를 띄우지 못했습니다 (종료 코드 {code}, 연속 {n}번)",
    "Using the Windows menu from now on": "이제 Windows 기본 메뉴를 씁니다",
    "Could not show the tray menu, using the Windows menu ({error})": "트레이 메뉴를 띄우지 못해 Windows 기본 메뉴를 씁니다 ({error})",
    "No tray icon ({error}). To install it: ./sidenote setup-capture": "트레이 아이콘을 쓰지 않습니다 ({error}). 설치하려면: ./sidenote setup-capture",
    "The Sidenote server is off. Run ./sidenote up in the server's terminal.": "Sidenote 서버가 꺼져 있습니다. 서버 터미널에서 ./sidenote up을 실행하세요.",
    "Quit from the tray.": "트레이에서 끝냈습니다.",
    "Quit from the panel": "패널에서 끝냈습니다",
    "Restarting from the panel": "패널에서 다시 시작합니다",
    "Stopping the server this start brought up too (./sidenote down)": "이번 시작이 켠 서버도 멈춥니다 (./sidenote down)",
    "Could not stop the server: {error}. ./sidenote down stops it": "서버를 멈추지 못했습니다: {error}. ./sidenote down으로 멈추세요",
    "Restarting from the tray.": "트레이에서 다시 시작합니다.",
    "Sidenote was opened again: opening the panel": "Sidenote를 다시 열어 패널을 엽니다",
    "Could not show the tray icon ({error})": "트레이 아이콘을 띄우지 못했습니다 ({error})",
    "Could not make the tray icon ({error}); going on without it": "트레이 아이콘을 만들지 못했습니다 ({error}); 그대로 계속합니다",
    "To end it: Quit in the tray icon, or ./sidenote capture-stop in the server's terminal.":
        "끝내려면 트레이 아이콘의 끝내기, 또는 서버 터미널에서 ./sidenote capture-stop.",
    "To end it: ./sidenote capture-stop in the server's terminal.": "끝내려면 서버 터미널에서 ./sidenote capture-stop.",
    # under the desktop app: its Quit ends the app, and there is no console for Ctrl+C nor ./sidenote to run
    "To end it: Quit Sidenote in the tray icon.": "끝내려면 트레이 아이콘의 Sidenote 끝내기.",
    "To end it: Quit Sidenote on the panel's Capture connection.": "끝내려면 패널의 캡처 연결에서 Sidenote 끝내기.",
    "The tray icon opens the panel and switches the screen and the sound on and off.": "트레이 아이콘에서 패널을 열고 화면과 소리를 켜고 끌 수 있습니다.",
    "Could not start again: {error}": "다시 시작하지 못했습니다: {error}",
    # a second start for a server that has its capture program already (OneCapture)
    "Another capture program is already running for this server, so this one ends.":
        "이 서버로 보내는 캡처 프로그램이 이미 실행 중이어서 이 프로그램은 끝납니다.",
    "To end the one that runs: Quit in its tray icon, or ./sidenote capture-stop in the server's terminal.":
        "실행 중인 프로그램을 끝내려면 그 트레이 아이콘의 끝내기, 또는 서버 터미널에서 ./sidenote capture-stop.",
    # Skip windows: the tray's state line while one is on screen, and what the console says of it (never which window)
    "Skipped window": "창 건너뜀",
    "A window to skip is on screen: no screen is sent while it is": "건너뛸 창이 화면에 보여 그동안 화면을 보내지 않습니다",
    "The window to skip is no longer on screen: capturing the screen again": "건너뛸 창이 더는 보이지 않아 다시 화면을 받습니다",
    "Skip windows changed: capturing the screen again": "건너뛸 창 설정이 바뀌어 다시 화면을 받습니다",
    "Reading another monitor: capturing the screen again": "다른 모니터를 읽어 다시 화면을 받습니다",
    "A window to skip is on screen, so nothing was sent (--once)": "건너뛸 창이 화면에 보여 보내지 않았습니다 (--once)",
    "The windows cannot be read here ({why}), so no window is skipped": "여기서는 창을 읽을 수 없어 건너뛰는 창이 없습니다 ({why})",
    "The windows behind the one in front cannot be listed here ({why}), so only that one is skipped": "여기서는 맨 앞 창 뒤의 창을 읽을 수 없어 맨 앞 창만 건너뜁니다 ({why})",
    # why the windows cannot be read, in those two lines (FrontWindow.why): a system's error stays as the system says it
    "no list of windows": "창 목록 없음",
    "no word from the window manager": "창 관리자가 알려 주지 않음",
    # the tray menu
    "Open the panel": "패널 열기",
    "Screen capture": "화면 캡처",
    "Sound capture": "소리 캡처",
    "Capture connection": "캡처 연결",
    "Restart capture": "캡처 다시 시작",
    "Quit": "끝내기",
    "Quit Sidenote": "Sidenote 끝내기",
    "Sidenote is not running. Start the Sidenote app again.": "Sidenote가 실행 중이 아닙니다. Sidenote 앱을 다시 켜세요.",
    "Not connected (./sidenote up)": "서버에 연결되지 않음 (./sidenote up)",
    "Not connected": "서버에 연결되지 않음",
    "Capturing: {what}": "캡처 중: {what}",
    "Screen": "화면",
    "Sound": "소리",
    "nothing": "없음",
    # the console's lines of what it does (the lines of measurements alone, frame sizes and what the looks cost, stay in
    # English, numbers for a report, as the server's log)
    "connected to {url}": "{url}에 연결됨",
    "cannot reach the server ({error}); retrying": "서버에 닿지 않아 다시 시도합니다 ({error})",
    "screen capture on (from the panel)": "화면 캡처 켬 (패널에서)",
    "screen capture off (from the panel)": "화면 캡처 끔 (패널에서)",
    "sound capture on (from the panel)": "소리 캡처 켬 (패널에서)",
    "sound capture off (from the panel)": "소리 캡처 끔 (패널에서)",
    "Join scrolled screens on (from the panel)": "스크롤 이어 붙이기 켬 (패널에서)",
    "Join scrolled screens off (from the panel)": "스크롤 이어 붙이기 끔 (패널에서)",
    "monitor {n} (from the panel)": "모니터 {n}번 (패널에서)",
    "all monitors (from the panel)": "모든 모니터 (패널에서)",
    "following the changing screen on (from the panel)": "바뀐 화면 따라가기 켬 (패널에서)",
    "following the changing screen off (from the panel)": "바뀐 화면 따라가기 끔 (패널에서)",
    "{n} word(s) for windows to skip (from the panel)": "건너뛸 창 낱말 {n}개 (패널에서)",
    "available monitors (pass the index to --monitor):": "모니터 목록 (--monitor에 번호를 넘김):",
    "0 = all monitors combined (virtual screen): {box}": "0 = 모든 모니터를 합친 한 화면 (가상 화면): {box}",
    "{i} = {w}x{h} at ({x},{y})": "{i} = {w}x{h}, 위치 ({x},{y})",
    "default is 1 (primary). 0 captures every monitor as one wide image.": "기본은 1(주 모니터). 0은 모든 모니터를 넓은 한 장으로 받습니다.",
    "monitor {asked} not found; {n} attached. Using 1.": "모니터 {asked}번이 없습니다. 연결된 {n}개 중 1번을 씁니다.",
    "./sidenote capture --list-monitors shows them.": "./sidenote capture --list-monitors로 볼 수 있습니다.",
    "Monitor in Solver settings lists them.": "풀이 설정의 모니터에서 볼 수 있습니다.",
    "scroll-stitch": "스크롤 이어 붙이기",
    "single-shot": "한 장씩",
    "capturing monitor {i}: {w}x{h} ({mode})": "모니터 {i}번 캡처: {w}x{h} ({mode})",
    "capturing all monitors: {w}x{h} ({mode})": "모든 모니터 캡처: {w}x{h} ({mode})",
    "the monitors changed {before} -> {after}; reading them again": "모니터가 바뀌어 다시 읽습니다: {before} -> {after}",
    # following the changing screen: a move says the two monitors' numbers and never what either shows
    "a new screen came to rest on monitor {to}: reading it instead of monitor {at}": "모니터 {to}번에 새 화면이 멈춰 {at}번 대신 읽습니다",
    "following is off: back to monitor {n}": "따라가기를 꺼서 다시 모니터 {n}번을 읽습니다",
    "the capture failed: back to monitor {n}": "캡처가 실패해 다시 모니터 {n}번을 읽습니다",
    "{mode} mode": "{mode} 모드",
    "screen capture works again": "화면 캡처가 다시 됩니다",
    "the panel is on this screen ({n} window(s)); its area is painted over before sending": "패널이 이 화면에 있습니다 (창 {n}개). 보내기 전에 그 자리를 칠해 가립니다",
    "the screen was scrolled ({n} rows): joining it into one problem": "화면이 스크롤됐습니다 ({n}줄): 한 문제로 이어 붙입니다",
    "back to single screens": "다시 한 장씩 보냅니다",
    "one screen sent (--once)": "화면 한 장을 보냈습니다 (--once)",
    "the screen has not changed for {n} looks: looking every {s} s until it does": "화면이 {n}번 그대로여서 바뀔 때까지 {s}초마다 봅니다",
    "the screen changed: looking at every poll again": "화면이 바뀌어 다시 매번 봅니다",
    "the screen is locked, a UAC prompt is up or the screen saver is on (desktop {desk}): Windows lets no program capture it; capture resumes when it is back":
        "화면이 잠겼거나 UAC 창 또는 화면 보호기가 떠 있습니다 (데스크톱 {desk}). Windows는 어떤 프로그램도 이 화면을 캡처하지 못하게 하며, 돌아오면 캡처를 이어 갑니다",
    "could not capture the screen ({error}); retrying every 2 s": "화면을 캡처하지 못했습니다 ({error}). 2초마다 다시 시도합니다",
    "capturing loopback: {device}": "루프백 캡처: {device}",
    "the default speaker changed; switching to it": "기본 스피커가 바뀌어 그쪽으로 옮깁니다",
    "could not record from the sound device ({error}); retrying every 3 s": "소리 장치에서 녹음하지 못했습니다 ({error}). 3초마다 다시 시도합니다",
    "no loopback input on this Mac: install BlackHole (brew install blackhole-2ch), make a Multi-Output Device of the speakers "
    "and BlackHole the output, or name an input with --audio-device":
        "이 Mac에 루프백 입력이 없습니다: BlackHole을 설치하고 (brew install blackhole-2ch) 스피커와 BlackHole로 다중 출력 기기를 "
        "만들어 출력으로 고르거나, --audio-device로 입력을 지정하세요",
    # the sound lost: by the device, with how far behind this program was then (_gap_line), or on the way out
    "the sound device dropped sound {n} time(s) in the last {sec} s; this program fell {late} s behind reading it (the device "
    "holds {held} s; the longest step between two reads took {step} s)":
        "소리 장치가 지난 {sec}초 동안 소리를 {n}번 놓쳤고, 이 프로그램이 {late}초 늦게 읽었습니다 (장치가 {held}초를 담음, "
        "두 읽기 사이 가장 긴 작업 {step}초)",
    "the sound device dropped sound {n} time(s) in the last {sec} s; this program was at most {late} s behind reading it (the "
    "device holds {held} s), so it was not lost by reading late":
        "소리 장치가 지난 {sec}초 동안 소리를 {n}번 놓쳤지만, 이 프로그램은 많아야 {late}초 늦었으므로 늦게 읽어 잃은 소리는 "
        "아닙니다 (장치가 {held}초를 담음)",
    "{n} second(s) of sound was dropped on the way out in the last {sec} s (the server or the network fell behind)":
        "지난 {sec}초 동안 보내는 길에 소리 {n}초를 버렸습니다 (서버나 네트워크가 뒤처짐)",
    "could not open the log file {path}: {error}": "로그 파일을 열지 못했습니다 {path}: {error}",
    "no word from the server yet; starting with screen and sound on": "아직 서버의 말이 없어 화면과 소리를 켠 채로 시작합니다",
    "capturing.": "캡처 중.",
    "Ctrl+C to stop.": "멈추려면 Ctrl+C.",
    "stopping...": "멈추는 중...",
    "starting again...": "다시 시작하는 중...",
}


def t(text: str, **values) -> str:
    """`text` in LANG, its {placeholders} filled from `values` (the values themselves are not read for placeholders)."""
    out = KO.get(text, text) if LANG == "ko" else text
    if not values:
        return out
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), out)


# --- high-pass change signature (kept in sync with server/gate.py) ---
SIG_SIZE = (160, 120)
SIG_BLUR = 2


def gray_plane(img: Image.Image) -> Image.Image:
    """The frame as one grey plane. Every reading below starts from this, and a grey image is handed
    straight back, so a poll that takes both readings converts the screen once instead of twice
    (measured on a 3840x2160 screen, scratch/smoke/poll_cost.py: 24.2 ms for the two readings as
    they were, 20.9 ms off one grey plane, 12.9 ms when the row profile is not wanted at all)."""
    return img if img.mode == "L" else img.convert("L")


def signature(img: Image.Image) -> np.ndarray:
    """Background-invariant edge/ink map, as an int16 array for fast MAD."""
    g = gray_plane(img).resize(SIG_SIZE, Image.BILINEAR)
    hp = ImageChops.difference(g, g.filter(ImageFilter.BoxBlur(SIG_BLUR)))
    return np.frombuffer(hp.tobytes(), dtype=np.uint8).astype(np.int16)


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference between two signatures (0 = identical)."""
    return float(np.mean(np.abs(a - b)))


# A problem longer than the screen is read by scrolling, and what arrives then is the same problem
# again, cut differently: not a new one. Joining it needs the stitcher, which compares whole frames
# and is too heavy to leave running on a 4K screen, so a cheap reading decides when to start it.
#
# That reading is one number per row of the screen, per vertical band: each row of a band is summed
# with fixed weights, so the number says what is *in* the row, not how bright it is. Brightness alone
# is not enough: lines of text are evenly spaced, so a page of them has the same brightness profile
# after a scroll of a whole number of lines (measured: an eight-line scroll looked identical). The
# bands are read apart because a coding-test page scrolls one pane while the editor beside it stays
# put, and over the whole screen that half dilutes the match away.
SCROLL_ROWS = 240        # rows read: a 900 point screen reads at about 4 points a row
SCROLL_BANDS = 8         # vertical bands, read apart
SCROLL_COLS = 64         # columns summed into each row's number, per band
SCROLL_MIN = 3           # rows; smaller moves are a caret or a blinking cursor
SCROLL_MAX = 170         # about two thirds of the screen: a jump larger than that leaves too little
                         # overlap to tell a scroll from a new screen (a page-down of a full screen)
SCROLL_GAIN = 0.55       # a band's shifted match must beat its unshifted one by this much
SCROLL_BANDS_AGREE = 2   # bands that must find the same shift before it counts as a scroll
SCROLL_RANGE_MIN = 48    # rows from the first that changed to the last, in a band that scrolled: a fifth of the screen
AUTO_STITCH_IDLE = 12    # polls without a scroll before single screens come back (~4 s at 3 fps)
# Fixed weights (a seed, so every run reads a screen the same way).
SCROLL_WEIGHTS = np.random.default_rng(20261027).normal(size=SCROLL_COLS).astype(np.float32)


def scroll_profile(img: Image.Image) -> np.ndarray:
    """What is in every row of the screen, per vertical band: (SCROLL_ROWS, SCROLL_BANDS) float32, as read. Each band's
    brightness is taken out by scroll_shift, over the rows that changed: taken out here over all of them, a bar that
    stays put moved with every change of the page under it, and no longer read as staying put."""
    small = gray_plane(img).resize((SCROLL_BANDS * SCROLL_COLS, SCROLL_ROWS), Image.BILINEAR)
    a = np.asarray(small, dtype=np.float32).reshape(SCROLL_ROWS, SCROLL_BANDS, SCROLL_COLS)
    return (a * SCROLL_WEIGHTS).sum(axis=2)


def scroll_shift(prev: np.ndarray, cur: np.ndarray) -> int:
    """How far the screen's content moved between two row profiles, in profile rows (positive: the
    content moved up, so the page was scrolled down). 0 when this is not the same content moved."""
    shift, agree, _ = scroll_votes(prev, cur)
    return shift if agree >= SCROLL_BANDS_AGREE else 0


def scroll_votes(prev: np.ndarray, cur: np.ndarray) -> tuple[int, int, int]:
    """scroll_shift's reading in full: (the shift the most bands found, how many found it, how many bands changed enough
    to say). Two polls apart two bands agreeing is a scroll; following compares looks seconds apart, where it asks more
    of them (content_moved)."""
    if prev is None or cur is None or prev.shape != cur.shape:
        return 0, 0, 0
    if not np.any(prev != cur):
        return 0, 0, 0
    votes: dict[int, int] = {}
    judged = 0   # bands whose rows changed enough to say whether they moved
    for band in range(prev.shape[1]):
        a, b = prev[:, band], cur[:, band]
        # Only the rows that changed are compared: a bar that stays put above or below what scrolls (the site's own
        # header, the browser's tabs) was shifted along with the page here and spoiled the match, so the problem pane
        # of a coding test site scrolling under its header read as no scroll at all (the right shift found at 0.90 of
        # the unshifted error, against SCROLL_GAIN 0.55). The rows from the first that changed to the
        # last are the part that moves.
        changed = np.flatnonzero(np.abs(a - b) > 0.5)
        # Too few rows changed to be a pane that scrolled: a static band, or a widget, a cursor, a clock. A short run
        # of rows is easily matched by a shift of itself (lines of text repeat), and the whole column it used to be
        # compared over kept that from voting.
        if changed.size == 0 or changed[-1] - changed[0] + 1 < SCROLL_RANGE_MIN:
            continue
        a, b = a[changed[0]:changed[-1] + 1], b[changed[0]:changed[-1] + 1]
        a, b = a - a.mean(), b - b.mean()   # a band that only changed brightness has not moved
        base = float(np.mean(np.abs(a - b)))
        if base < 0.5:
            continue
        judged += 1
        best, best_k = base, 0
        for d in range(SCROLL_MIN, min(SCROLL_MAX, len(a) * 2 // 3) + 1):   # a third of the rows left to compare
            for k in (d, -d):
                m = float(np.mean(np.abs(a[k:] - b[:-k]))) if k > 0 else float(np.mean(np.abs(a[:k] - b[-k:])))
                if m < best:
                    best, best_k = m, k
        if best_k and best <= base * SCROLL_GAIN:
            votes[best_k] = votes.get(best_k, 0) + 1
    if not votes:
        return 0, 0, judged
    # Bands a row or two apart found the same scroll: count them together.
    best_k, best_votes = 0, 0
    for k in votes:
        near = sum(n for j, n in votes.items() if abs(j - k) <= 2)
        if near > best_votes or (near == best_votes and abs(k) < abs(best_k)):
            best_k, best_votes = k, near
    return best_k, best_votes, judged


class SendGate:
    """Decide when to send a frame: fire on a *changed and settled* screen.

    Pure state machine (no I/O), so the send decision can be unit-tested without
    a real screen. "Settled" = the last few polls barely differ (not mid-scroll/
    typing); "changed" = it differs enough from what was last sent. A reconnect
    calls resend() so the current screen is pushed again even if it is unchanged.
    """

    def __init__(self, threshold: float, settle: float, stable_polls: int):
        self.threshold = threshold
        self.settle = settle
        self.stable_polls = stable_polls
        self.last_poll_sig: np.ndarray | None = None
        self.last_sent_sig: np.ndarray | None = None
        self.stable = 0

    def resend(self) -> None:
        """Forget what was last sent so the next settled frame is sent again."""
        self.last_sent_sig = None

    def should_send(self, sig: np.ndarray) -> bool:
        if self.last_poll_sig is not None and distance(sig, self.last_poll_sig) <= self.settle:
            self.stable += 1
        else:
            self.stable = 0
        self.last_poll_sig = sig

        changed = self.last_sent_sig is None or distance(sig, self.last_sent_sig) >= self.threshold
        if changed and self.stable >= self.stable_polls:
            self.last_sent_sig = sig
            return True
        return False


# Width the stitched problem is sent at: shrunk from full resolution, its text stays
# larger than on the 1600-wide screenshot, and the server cuts it into tiles.
PAGE_MAX_W = 1000


# The send decision used to look at the screen through a 1600-wide copy, whatever was sent, because the
# thresholds were set on one. Both things that read it shrink it again straight away and much further
# (signature to 160x120, scroll_profile to 512x240), so the copy was 52 ms of the 61 ms it took to reach
# those two numbers on a 4K screen, three times a second, for an image nobody looked at. They read the
# frame as it was grabbed now. Two resamplings in a row are not one, so the numbers moved a little; the
# decisions did not. scratch/smoke/gate_filter.py measures both on real 4K screens, on this machine:
# the same send decision on all 102 pairs, the same scroll found on all 12, and 60.9 ms down to 20.3 ms,
# which is a poll's share of a core going from 18.3% to 6.1%.


def _fit(img: Image.Image, max_w: int) -> Image.Image:
    if img.width <= max_w:
        return img
    return img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)


def _png_b64(img: Image.Image) -> str:
    # Fast compression: a 4K screen takes a fraction of the time at level 6, and the frame only
    # travels to this PC's own server.
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return base64.b64encode(buf.getvalue()).decode()


def set_dpi_aware() -> None:
    """Window positions in physical pixels, the same ones the screen grab has (Windows only)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def input_desktop() -> str | None:
    """Name of the desktop that takes input now: "Default" normally, "Winlogon" on the lock or UAC
    screen, "Screen-saver" under a screen saver. Windows lets no program grab the screen off "Default".
    None off Windows or when it cannot be read."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    h = user32.OpenInputDesktop(0, False, 0x0100)   # DESKTOP_SWITCHDESKTOP, as measured; the name needs no other right
    if not h:
        return None
    try:
        buf, n = ctypes.create_unicode_buffer(256), wintypes.DWORD()
        if not user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(n)):   # UOI_NAME
            return None
        return buf.value
    finally:
        user32.CloseDesktop(h)


# This tool's own panel. What it shows is the answer to the screen behind it, so a screen with it on is a
# screen answering itself: its area is painted over before anything is sent, and the title that finds it is
# read here and never leaves (window_rects). The page is titled "Sidenote Panel", so the browser window
# showing it starts with that, and matching only the start keeps an editor or a file manager opened on this
# folder ("sidenote - Visual Studio Code") out of it, which an older rule did paint over. The Korean word
# the page used to be titled with is still matched, for a tab left open from before.
OWN_TITLE = re.compile(r"^sidenote\s*(panel|패널)(\s*[-—|·]|\s+and\s+\d+\s+more\b|\s+및\s|\s*$)", re.I)


def window_rects(mon: dict, limit: int = 40) -> tuple[list, list] | None:
    """(visible top-level windows over the captured area, front to back, as fractions of it
    ([x0, y0, x1, y1]); which of them are this tool's own panel, as indexes into that list). The server clips a
    problem crop to the window that holds it, so a neighbouring window never comes along. Only the rectangles
    leave this program (no titles). None off Windows and macOS, or when the list cannot be read."""
    if sys.platform == "darwin":
        return _rects_mac(mon, limit)
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    left, top, width, height = mon["left"], mon["top"], mon["width"], mon["height"]
    rect, cloaked, cls, out = wintypes.RECT(), ctypes.c_int(0), ctypes.create_unicode_buffer(64), []
    title, mine = ctypes.create_unicode_buffer(160), []
    GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = -20, 0x20, 0x80

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if len(out) >= limit:
            return False
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or not user32.GetWindowTextLengthW(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW):
            return True   # click-through overlays and tool windows hold no problem and cover others
        if user32.GetClassNameW(hwnd, cls, len(cls)) and cls.value in ("Progman", "WorkerW"):
            return True   # the desktop, never a window of its own (Windows 11 makes it a tool window as well)
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return True   # on another virtual desktop, or a suspended app
        # The visible frame (without the invisible resize border); the plain window rect as a fallback.
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
        x0, y0 = max(0.0, (rect.left - left) / width), max(0.0, (rect.top - top) / height)
        x1, y1 = min(1.0, (rect.right - left) / width), min(1.0, (rect.bottom - top) / height)
        if (x1 - x0) * (y1 - y0) >= 0.01:   # on this screen, and not a sliver
            user32.GetWindowTextW(hwnd, title, len(title))
            if OWN_TITLE.match(title.value.strip()):
                mine.append(len(out))
            out.append([round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)])
        return True

    try:
        user32.EnumWindows(visit, 0)   # top of the z-order first
    except Exception:
        return None
    return out, mine


def _rects_mac(mon: dict, limit: int = 40) -> tuple[list, list] | None:
    """window_rects on macOS, from the same list Skip windows reads (_windows_mac)."""
    try:
        shown = _windows_mac(limit=128)
    except Exception:
        return None
    left, top, width, height = mon["left"], mon["top"], mon["width"], mon["height"]
    out, mine = [], []
    for title, _program, (wx0, wy0, wx1, wy1), _covers in shown:
        if len(out) >= limit:
            break
        x0, y0 = max(0.0, (wx0 - left) / width), max(0.0, (wy0 - top) / height)
        x1, y1 = min(1.0, (wx1 - left) / width), min(1.0, (wy1 - top) / height)
        if x1 > x0 and y1 > y0 and (x1 - x0) * (y1 - y0) >= 0.01:   # on this screen, and not a sliver
            if OWN_TITLE.match(title.strip()):
                mine.append(len(out))
            out.append([round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)])
    return out, mine


def _name_own(img: Image.Image, box: tuple) -> None:
    """The name, with its highlighter stroke, in the middle of the painted area. Any font will do, and if none loads the grey stays plain."""
    x0, y0, x1, y1 = box
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arialbd.ttf", max(14, (x1 - x0) // 14))
        draw = ImageDraw.Draw(img)
        l, t, r, b = draw.textbbox((0, 0), "sidenote", font=font)
        stroke = 2 + max(2, (b - t) // 6)                    # the highlighter under the word, and its gap
        if r - l + 8 > x1 - x0 or b - t + stroke + 8 > y1 - y0:
            return                                           # no room: ink outside the area would fall on the other windows in the image
        x, y = x0 + (x1 - x0 - (r - l)) // 2, y0 + (y1 - y0 - (b - t)) // 2
        draw.rectangle([x, y + (b - t) + 2, x + (r - l), y + (b - t) + 2 + max(2, (b - t) // 6)], fill=(200, 165, 50))
        draw.text((x - l, y - t), "sidenote", font=font, fill=(150, 150, 150))
    except Exception:
        pass


def hide_own(img: Image.Image, rects: list, mine: list) -> Image.Image:
    """The screen with this tool's own panel painted over. `rects` are the windows front to back as fractions
    of the image and `mine` says which of them are the panel: its area goes grey, and then every window in
    front of it is pasted back from the original, so a window over the panel keeps what it showed."""
    if not mine:
        return img
    out, w, h = img.copy(), img.width, img.height

    def box(r):
        return (max(0, int(r[0] * w)), max(0, int(r[1] * h)), min(w, int(r[2] * w)), min(h, int(r[3] * h)))

    for k in mine:
        x0, y0, x1, y1 = box(rects[k])
        if x1 > x0 and y1 > y0:
            out.paste((34, 34, 34), (x0, y0, x1, y1))
            _name_own(out, (x0, y0, x1, y1))    # says what the grey is: on the panel's own picture it read as a black window
            for front in rects[:k]:
                fx0, fy0, fx1, fy1 = box(front)
                if fx1 > fx0 and fy1 > fy0:
                    out.paste(img.crop((fx0, fy0, fx1, fy1)), (fx0, fy0))
    return out


# ---------- Skip windows: the windows on screen, and whether no screen may go out while one of them is there ----------
# While a window with one of the panel's words (Solver settings > Screen > Skip windows) in its title or in its program's
# name is in front, or shows on the screen being captured in any part, the screen loop grabs and sends nothing: a password
# manager or a private browser window is not sent, whichever window has the focus. One minimized, on another desktop or
# wholly covered by the windows above it shows nothing and stops nothing. The words come in the server's control message;
# this copy of the server's default list (server/settings.py, SKIP_WINDOWS) holds until they do, and with an older server
# that sends none. What is read of the windows stays in this program: it goes neither to the server nor into the log, which
# says only that a skip started and ended, and caps says only whether the windows could be read (skip_limit).
SKIP_WINDOWS = ["1Password", "Bitwarden", "KeePass", "KeePassXC", "LastPass", "Dashlane", "Keeper", "Enpass",
                "NordPass", "Proton Pass", "InPrivate", "Incognito", "Private Browsing", "시크릿", "사생활 보호"]
SKIP_REOPEN_SEC = 30.0   # how often a connection to the X server that could not be opened is tried again


def skip_words(words) -> list:
    """The words as they are matched: trimmed, the empty ones dropped, and casefolded, so the match ignores case."""
    return [w.strip().casefold() for w in words if isinstance(w, str) and w.strip()]


def skip_match(front, words) -> bool:
    """Whether a window, (title, program), has one of the words (from skip_words) in its title or in its program's name.
    A window nothing is known of is no match, and neither is this tool's own panel, whatever window its tab sits in: it
    is what the person looks at while the screen is read, and a word there would stop the capture for as long as it is open."""
    if not front or not words or OWN_TITLE.match((front[0] or "").strip()):
        return False
    title, program = (front[0] or "").casefold(), (front[1] or "").casefold()   # the same case as the words
    return any(w in title or w in program for w in words)


def rect_shows(rect, above) -> bool:
    """Whether any part of `rect` (x0, y0, x1, y1) is left once the rectangles in `above` are taken off it."""
    left = [rect]                                         # what still shows: at most four more for each rectangle over it
    for ax0, ay0, ax1, ay1 in above:
        pieces = []
        for x0, y0, x1, y1 in left:
            if ax0 >= x1 or ax1 <= x0 or ay0 >= y1 or ay1 <= y0:
                pieces.append((x0, y0, x1, y1))           # not touched by this one
                continue
            if y0 < ay0:
                pieces.append((x0, y0, x1, ay0))          # the band above it
            if ay1 < y1:
                pieces.append((x0, ay1, x1, y1))          # the band below it
            if x0 < ax0:
                pieces.append((x0, max(y0, ay0), ax0, min(y1, ay1)))   # beside it on the left, within its height
            if ax1 < x1:
                pieces.append((ax1, max(y0, ay0), x1, min(y1, ay1)))   # and on the right
        if not pieces:
            return False                                  # nothing left: wholly covered
        left = pieces
    return True


def skip_visible(stack, words, mon: dict) -> bool:
    """Whether a window that has one of the words shows on the monitor `mon`. `stack` is the windows on the desktop, front
    to back: (title, program, (x0, y0, x1, y1), the rectangle it covers others with). A window off this monitor is not in
    what is sent; one with no covering rectangle (an overlay) shows through and hides nothing below it."""
    bounds = (mon["left"], mon["top"], mon["left"] + mon["width"], mon["top"] + mon["height"])
    above = []
    for title, program, rect, covers in stack:
        if skip_match((title, program), words):
            box = (max(rect[0], bounds[0]), max(rect[1], bounds[1]), min(rect[2], bounds[2]), min(rect[3], bounds[3]))
            if box[0] < box[2] and box[1] < box[3] and rect_shows(box, above):
                return True
        if covers:
            above.append(covers)
    return False


def skip_now(front, words, mon: dict) -> bool:
    """Whether no screen may go out now: the window in front counts wherever it is, as it always did, then what shows.
    Where the windows cannot be listed the one in front is all there is to go by (front.limit says so)."""
    if skip_match(front.read(), words):
        return True
    stack = front.stack()
    return bool(stack) and skip_visible(stack, words, mon)


def _program_win32(hwnd, user32, kernel32) -> str:
    """The file name of the program a window belongs to, such as "Bitwarden.exe"; "" when its process cannot be opened."""
    import ctypes
    import ntpath   # a Windows path, whatever this runs on: the suites run it on Linux with Windows stood in for
    from ctypes import wintypes

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))   # the process the window belongs to
    kernel32.OpenProcess.restype = wintypes.HANDLE
    process = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION: its name, no more
    program = ""
    if process:
        try:
            path, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(wintypes.HANDLE(process), 0, path, ctypes.byref(size)):
                program = ntpath.basename(path.value)        # the file's name, its folder left out
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(process))
    return program


def _front_win32() -> tuple | None:
    """The window in front on Windows: (its title, its program's file name, such as "Bitwarden.exe"). The name is ""
    when the process cannot be opened for it; None when no window is in front at all."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND      # a handle, not the 32-bit int ctypes would assume
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None                                        # the lock screen, or a moment between two windows
    n = min(max(0, user32.GetWindowTextLengthW(wintypes.HWND(hwnd))), 2047)   # its title's length, capped
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), title, n + 1)
    return title.value, _program_win32(hwnd, user32, kernel32)


def _stack_win32(limit: int = 128) -> list:
    """The windows on the desktop, front to back, as skip_visible takes them, from the same list and by the same rules as
    window_rects: not minimized, not on another virtual desktop, not the desktop itself, with a title (the many helper
    windows a program keeps have none, and a hidden one must not stop the capture for good). A tool window or a
    click-through overlay is left out both ways: it holds no window to skip, and may be see-through. The taskbar has no
    title and only covers. Raises when the list cannot be read."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32, dwm = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    rect, cloaked, cls, out = wintypes.RECT(), ctypes.c_int(0), ctypes.create_unicode_buffer(64), []
    GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = -20, 0x20, 0x80
    programs: dict = {}                                    # one process's name asked once a look, for all of its windows
    title = ctypes.create_unicode_buffer(512)

    # WINFUNCTYPE is Windows' own; the suites run this on Linux with the calls stood in for
    @getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if len(out) >= limit:
            return False
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetClassNameW(hwnd, cls, len(cls)) and cls.value in ("Progman", "WorkerW"):
            return True
        taskbar = cls.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
        if not taskbar and (not user32.GetWindowTextLengthW(hwnd)
                            or user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)):
            return True
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return True
        # The visible frame, without the invisible resize border that would show past a window over it; the plain rect as a fallback
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
        box = (rect.left, rect.top, rect.right, rect.bottom)
        if taskbar:
            out.append(("", "", box, box))
            return True
        user32.GetWindowTextW(hwnd, title, len(title))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if pid.value not in programs:
            programs[pid.value] = _program_win32(hwnd, user32, kernel32)
        out.append((title.value, programs[pid.value], box, box))
        return True

    user32.EnumWindows(visit, 0)                           # top of the z-order first
    return out


def _windows_mac(limit: int = 128) -> list:
    """The windows on the screen on macOS, front to back, as skip_visible takes them: (title, program, (x0, y0, x1, y1),
    the same rectangle), from the window server's own list, in the points mss gives the monitors in. Only those of the
    normal layer: the menu bar, the Dock, menus and the status items sit above it and hold no window to skip, and a
    minimized window or one on another Space is not on the list at all. The program is the app's name ("Bitwarden"); the
    title is there once Screen Recording is allowed, as it has to be for the screen itself. Raises when the list cannot
    be read."""
    import Quartz

    listed = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    if listed is None:
        raise RuntimeError(t("no list of windows"))   # said as why in the log's line, in its language
    out = []
    for w in listed:
        if len(out) >= limit:
            break
        if w.get(Quartz.kCGWindowLayer, 0) != 0 or not w.get(Quartz.kCGWindowAlpha, 1):
            continue                                       # above the normal windows, or drawn wholly see-through
        b = w.get(Quartz.kCGWindowBounds) or {}
        x, y, width, height = (float(b.get(k, 0)) for k in ("X", "Y", "Width", "Height"))
        if width < 2 or height < 2:
            continue                                       # a program's hidden helper, a point on the screen
        box = (x, y, x + width, y + height)
        out.append((str(w.get(Quartz.kCGWindowName) or ""), str(w.get(Quartz.kCGWindowOwnerName) or ""), box, box))
    return out


def _front_mac() -> tuple | None:
    """The window in front on macOS, (title, program): the first of the normal windows, which the app in front keeps
    over the others; None when there is none (the desktop alone)."""
    shown = _windows_mac(limit=1)
    return (shown[0][0], shown[0][1]) if shown else None


class _X11Front:
    """The windows on an X11 desktop, read through libX11 with ctypes on a connection of its own (mss reaches X11 for the
    screen the same way): the root window's _NET_ACTIVE_WINDOW, which the window manager keeps, and each window's _NET_WM_NAME
    (else WM_NAME) for its title and its WM_CLASS for its program ("keepassxc KeePassXC"); and for what shows, the root's
    _NET_CLIENT_LIST_STACKING with each window's place on the root."""

    ANY, WINDOW = 0, 33                       # AnyPropertyType, and XA_WINDOW, the type _NET_ACTIVE_WINDOW holds
    ALL_DESKTOPS = 0xFFFFFFFF                 # what _NET_WM_DESKTOP holds for a window on every desktop

    def __init__(self, lib=None):
        import ctypes
        import ctypes.util

        c = self.c = ctypes
        if lib is None:                       # the library itself; the suites hand in a stand-in
            lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.x = lib
        # The calls' shapes: pointers and XIDs are 64 bits wide here, which ctypes would otherwise cut to an int
        lib.XOpenDisplay.restype, lib.XOpenDisplay.argtypes = c.c_void_p, [c.c_char_p]
        lib.XDefaultRootWindow.restype, lib.XDefaultRootWindow.argtypes = c.c_ulong, [c.c_void_p]
        lib.XInternAtom.restype, lib.XInternAtom.argtypes = c.c_ulong, [c.c_void_p, c.c_char_p, c.c_int]
        lib.XGetWindowProperty.restype = c.c_int
        lib.XGetWindowProperty.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int, c.c_ulong,
                                           c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_ulong),
                                           c.POINTER(c.c_ulong), c.POINTER(c.c_void_p)]
        lib.XGetGeometry.restype = c.c_int
        lib.XGetGeometry.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_int),
                                     c.POINTER(c.c_uint), c.POINTER(c.c_uint), c.POINTER(c.c_uint), c.POINTER(c.c_uint)]
        lib.XTranslateCoordinates.restype = c.c_int
        lib.XTranslateCoordinates.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_int, c.c_int, c.POINTER(c.c_int),
                                              c.POINTER(c.c_int), c.POINTER(c.c_ulong)]
        lib.XFree.argtypes = [c.c_void_p]
        lib.XSync.argtypes = [c.c_void_p, c.c_int]
        lib.XSetErrorHandler.restype = c.c_void_p   # the handler it replaced, as an address
        self.display = lib.XOpenDisplay(None)     # the one $DISPLAY names
        if not self.display:
            raise OSError("no X11 display")
        self.root = lib.XDefaultRootWindow(self.display)
        self.atoms = {name: lib.XInternAtom(self.display, name.encode(), False)
                      for name in ("_NET_ACTIVE_WINDOW", "_NET_WM_NAME", "WM_NAME", "WM_CLASS", "_NET_CLIENT_LIST_STACKING",
                                   "_NET_CURRENT_DESKTOP", "_NET_WM_DESKTOP", "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN",
                                   "_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS")}
        self.HANDLER = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)   # int handler(Display *, XErrorEvent *)
        self.handler = self.HANDLER(self._on_error)   # held here: ctypes lets go of a callback nothing holds
        self.handler_at = c.cast(self.handler, c.c_void_p).value
        self.before = None                        # the handler this one stands in front of while it reads
        self.failed = False                       # an error came back on this connection during this read
        self.says_front = True                    # the window manager keeps _NET_ACTIVE_WINDOW (known after a read)

    def _on_error(self, display, event) -> int:
        """Xlib's error handler while this reads. Xlib's own ends the whole program on an error, and the window in front
        can close between reading which it is and reading its title (BadWindow): such an error on this connection is
        noted and the read comes to nothing. One on another connection goes to the handler that was there before."""
        if display == self.display:
            self.failed = True
            return 0
        return self.before(display, event) if self.before else 0

    def _prop(self, win: int, name: str) -> tuple:
        """(type, format, bytes) of a property of a window; type 0 when it has none or it could not be read."""
        c = self.c
        kind, fmt, n, after, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong(), c.c_void_p()
        status = self.x.XGetWindowProperty(self.display, win, self.atoms[name], 0, 1024, False, self.ANY, c.byref(kind),
                                           c.byref(fmt), c.byref(n), c.byref(after), c.byref(data))
        if status != 0:
            return 0, 0, b""
        if not data.value:
            return kind.value, fmt.value, b""     # there, and empty: a list with no window in it says something too
        try:
            unit = {8: 1, 16: c.sizeof(c.c_short), 32: c.sizeof(c.c_long)}.get(fmt.value, 0)   # 32-bit items as longs
            return kind.value, fmt.value, c.string_at(data.value, n.value * unit)
        finally:
            self.x.XFree(data)                    # Xlib's copy of it

    def _longs(self, raw: bytes) -> list:
        """A format-32 property's items: Xlib hands them over as longs, whatever the width of a long here."""
        size = self.c.sizeof(self.c.c_long)
        return [int.from_bytes(raw[i:i + size], sys.byteorder) for i in range(0, len(raw) - size + 1, size)]

    def _numbers(self, win: int, name: str) -> list | None:
        """A format-32 property's items; None when the window has no such property."""
        kind, fmt, raw = self._prop(win, name)
        return self._longs(raw) if kind and fmt == 32 else None

    def _text(self, win: int, name: str) -> str:
        """A property that holds text. _NET_WM_NAME is UTF-8; WM_NAME and WM_CLASS are Latin-1, or UTF-8 from a program
        that wrote them so."""
        kind, fmt, raw = self._prop(win, name)
        if fmt != 8 or not raw:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def _name(self, win: int) -> tuple:
        """(title, program) of one window."""
        title = self._text(win, "_NET_WM_NAME") or self._text(win, "WM_NAME")
        return title, " ".join(part for part in self._text(win, "WM_CLASS").split("\0") if part)   # instance, class

    def _guarded(self, read):
        """`read()` with this reader's errors its own, as _on_error says, and the handler before it back in force after."""
        c, x = self.c, self.x
        prev = x.XSetErrorHandler(self.handler)   # its errors are this reader's while it reads
        self.before = self.HANDLER(prev) if prev and prev != self.handler_at else None
        self.failed = False
        try:
            return read()
        finally:
            now = x.XSetErrorHandler(c.c_void_p(prev) if prev else None)   # the handler before goes back
            if now and now != self.handler_at:    # another took its place meanwhile (a library starting up): it stays
                x.XSetErrorHandler(c.c_void_p(now))

    def read(self) -> tuple | None:
        """(title, program) of the window in front; None when none is, or when it closed as it was read."""
        def go():
            kind, fmt, raw = self._prop(self.root, "_NET_ACTIVE_WINDOW")
            self.says_front = kind != 0           # a window manager with no such thing never says which, and that is told apart
            ids = self._longs(raw) if kind == self.WINDOW and fmt == 32 else []
            if not ids or not ids[0]:
                return None                       # nothing in front, or no window manager that says which
            got = self._name(ids[0])
            self.x.XSync(self.display, False)     # an error still on its way comes in now, to this reader's handler
            return None if self.failed else got
        return self._guarded(go)

    def _place(self, win: int) -> tuple | None:
        """(x0, y0, x1, y1) of a window's own area on the root, without any shadow its toolkit draws inside it (GTK's), and
        with that the rectangle it covers others with, its window manager's frame added. None when it cannot be read."""
        c, x = self.c, self.x
        root, at_x, at_y = c.c_ulong(), c.c_int(), c.c_int()
        w, h, border, depth = c.c_uint(), c.c_uint(), c.c_uint(), c.c_uint()
        if not x.XGetGeometry(self.display, win, c.byref(root), c.byref(at_x), c.byref(at_y), c.byref(w), c.byref(h),
                              c.byref(border), c.byref(depth)):
            return None
        # A window manager's frame is the window's parent, so the place on the root is asked for and not read from above
        child = c.c_ulong()
        if not x.XTranslateCoordinates(self.display, win, self.root, 0, 0, c.byref(at_x), c.byref(at_y), c.byref(child)):
            return None
        box = [at_x.value, at_y.value, at_x.value + w.value, at_y.value + h.value]
        # Each is left, right, top, bottom. A shadow inside the window is see-through, and would show past a window over it for good
        gtk = self._numbers(win, "_GTK_FRAME_EXTENTS")
        if gtk and len(gtk) == 4:
            box = [box[0] + gtk[0], box[1] + gtk[2], box[2] - gtk[1], box[3] - gtk[3]]
        frame = self._numbers(win, "_NET_FRAME_EXTENTS")
        covers = box
        if frame and len(frame) == 4:
            covers = [box[0] - frame[0], box[1] - frame[2], box[2] + frame[1], box[3] + frame[3]]
        return tuple(box), tuple(covers)

    def stack(self) -> list | None:
        """The windows on the desktop, front to back, as skip_visible takes them, with those minimized or on another desktop
        left out. None when the window manager does not keep the list. One that closes as it is read is left out."""
        def go():
            kind, fmt, raw = self._prop(self.root, "_NET_CLIENT_LIST_STACKING")
            if not kind or fmt != 32:
                return None
            desktop = self._numbers(self.root, "_NET_CURRENT_DESKTOP")
            hidden = self.atoms["_NET_WM_STATE_HIDDEN"]
            out = []
            for win in reversed(self._longs(raw)):   # it is kept bottom first
                self.failed = False
                if hidden in (self._numbers(win, "_NET_WM_STATE") or ()):
                    continue
                on = self._numbers(win, "_NET_WM_DESKTOP")
                if on and desktop and on[0] not in (desktop[0], self.ALL_DESKTOPS):
                    continue
                place = self._place(win)
                name = self._name(win)
                self.x.XSync(self.display, False)    # an error still on its way comes in now, to this reader's handler
                if place and not self.failed:
                    out.append((name[0], name[1], place[0], place[1]))
            return out
        return self._guarded(go)


class FrontWindow:
    """The windows on the desktop, read the way this system allows. read() gives the one in front, (title, program), or None
    when nothing can be said now; stack() the ones that may show, or None where they cannot be listed. `limit` says what
    that leaves, for the panel: "" all of it, "front" only the window in front counts, "none" no window can be skipped.
    `why` says the same for the log. A read that broke says so and is tried again at the next look: it may not switch
    this off for the rest of the run."""

    def __init__(self):
        self.x11, self.opened, self.fixed = None, 0.0, ""   # fixed: what no later look can change (a Wayland session)
        self.broke, self.unlisted = "", ""        # why the last read failed, and why the last list did
        if sys.platform in ("win32", "darwin"):
            return                                # read afresh on each look, with no connection to keep
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            self.fixed = "Wayland"                # a Wayland session tells other programs nothing of its windows
            return
        self._open()

    def _open(self) -> bool:
        """The connection to the X server, tried now and then: no display yet at this program's start is not for ever."""
        if self.x11 is not None:
            return True
        now = time.monotonic()
        if self.opened and now - self.opened < SKIP_REOPEN_SEC:
            return False
        self.opened = now
        try:
            self.x11 = _X11Front()
            self.broke = ""
            return True
        except Exception as exc:                  # no libX11, or no display to open
            self.broke = f"{type(exc).__name__}: {exc}"
            return False

    def read(self) -> tuple | None:
        if self.fixed:
            return None
        try:
            if sys.platform == "win32":
                got = _front_win32()
            elif sys.platform == "darwin":
                got = _front_mac()
            else:
                got = self.x11.read() if self._open() else None
                if self.x11 is None:
                    return None                   # broke stays as _open left it
            self.broke = ""
            return got
        except Exception as exc:                  # counted as no window known, said (screen_loop), and read again at the next look
            self.broke = f"{type(exc).__name__}: {exc}"
            return None

    def stack(self) -> list | None:
        if self.fixed:
            return None
        try:
            if sys.platform == "win32":
                got = _stack_win32()
            elif sys.platform == "darwin":
                got = _windows_mac()
            else:
                got = self.x11.stack() if self.x11 is not None else None
            self.unlisted = "" if got is not None else t("no list of windows")   # said in the log's line, in its language
            return got
        except Exception as exc:
            self.unlisted = f"{type(exc).__name__}: {exc}"
            return None

    @property
    def limit(self) -> str:
        if self.fixed or (self.unlisted and (self.broke or self.x11 is None and sys.platform not in ("win32", "darwin"))):
            return "none"
        if self.unlisted and self.x11 is not None and not self.x11.says_front:
            return "none"                         # no list, and no word of which is in front either: a window manager with neither
        return "front" if self.unlisted else ""

    @property
    def why(self) -> str:
        if self.fixed:
            return self.fixed
        if not self.limit:
            return ""
        if self.broke:
            return self.broke                     # the system's own error, as it says it
        return t("no word from the window manager") if self.limit == "none" else self.unlisted


def _vstack(top: Image.Image, bottom: Image.Image) -> Image.Image:
    w = max(top.width, bottom.width)
    out = Image.new("RGB", (w, top.height + bottom.height), (255, 255, 255))
    out.paste(top, (0, 0))
    out.paste(bottom, (0, top.height))
    return out


class ScrollStitcher:
    """Assemble a long, scrolled problem into one "page": the current screen plus the
    full unrolled content of the panel being scrolled.

    Coding-test sites are split-pane: only the problem panel scrolls while the header,
    footer and code editor stay put, so the frame as a whole is never a clean vertical
    shift. Each frame pair is therefore cut into 40px vertical bands; bands whose content
    moved by a common dy mark the scrolling panel's columns, and per-row checks bound its
    rows (sticky header/footer excluded). The first detections are unioned, then the
    region is locked and only it is tracked: the viewport position inside the unrolled
    content is followed, so scrolling back over known content adds nothing and only
    newly revealed rows are appended (or prepended). When the screen settles, feed()
    returns (current_frame, [unrolled_content]) once, or (frame, []) if nothing was
    scrolled. Pure PIL/numpy, so it is unit-testable without a real screen.
    """

    BAND = 4            # grid columns per band (~40px at 1600 wide)
    LOCK_AFTER = 2      # scroll detections unioned before the region is locked
    EPS = 0.02          # prefer the smallest shift among near-equal matches (mismatch units)
    MATCH_MAX = 0.35    # edge mismatch above which a shift is not the same content moved
    EDGE_PAD = 16       # flat grid columns kept beyond the last moving one, per side: lines
                        # longer than any seen while locking must not be cut off later

    def __init__(self, stable_polls: int, settle: float = 0.3, threshold: float = 0.5,
                 fine_max: float = 8.0, static_max: float = 3.0, max_content_px: int = 24000,
                 page_stable_polls: int = 6):
        self.stable_polls = stable_polls
        # Once something was scrolled, wait longer before sending (~2 s at 3 fps): a short
        # pause between wheel flicks or while reading must not ship a half-scrolled page.
        self.page_stable_polls = page_stable_polls
        self.settle = settle              # full-frame signature MAD below which it is "still"
        self.threshold = threshold        # signature MAD that makes a settled screen worth re-sending
        self.fine_max = fine_max          # full-res MAD under which a pixel shift is a real match
        self.static_max = static_max      # full-res MAD under which the panel did not move
        self.max_content_px = max_content_px
        self.reset()

    def reset(self) -> None:
        self.prev = self.prev_g = self.prev_sig = None
        self.region: tuple[int, int, int, int] | None = None  # scrolling panel (x0, y0, x1, y1)
        self.pending: list = []           # frames buffered while the region is tentative
        self.cands: list = []             # regions from those detections (unioned at lock)
        self.content: Image.Image | None = None  # unrolled panel content
        self.view_top = 0                 # viewport top inside `content`, px
        self.stable = 0
        self.emitted = False
        self.emit_sig = None

    def joining(self) -> bool:
        """Whether a scrolled problem is being joined: frames held while the scrolling part is not yet sure, or a page
        grown by a scroll and not yet sent. Following holds the reading while it is (screen_loop)."""
        return bool(self.pending) or (self.region is not None and not self.emitted)

    # --- matching primitives ---
    @staticmethod
    def _gray(img: Image.Image) -> np.ndarray:
        """The same grey plane as an int16 array, which is what the matching below works on."""
        return np.asarray(gray_plane(img), dtype=np.int16)

    @staticmethod
    def _cells(shape) -> tuple[int, int]:
        """Coarse grid cell (gx, gy) in px: about 160 x 400 cells at any capture size."""
        return max(4, shape[1] // 160), max(1, shape[0] // 400)

    @staticmethod
    def _grid(g: np.ndarray, gx: int, gy: int) -> np.ndarray:
        """Box-mean downsample for fast, alias-tolerant coarse matching."""
        hg, wg = g.shape[0] // gy, g.shape[1] // gx
        return g[:hg * gy, :wg * gx].reshape(hg, gy, wg, gx).mean(axis=(1, 3))

    @staticmethod
    def _shifted(a: np.ndarray, b: np.ndarray, d: int):
        """(prev, cur) row views aligned for a scroll of d px: cur row y == prev row y+d."""
        h = a.shape[0]
        return (a[d:], b[:h - d]) if d > 0 else (a[:h + d], b[-d:])

    @staticmethod
    def _energy(g: np.ndarray) -> np.ndarray:
        """Edge energy |dx|+|dy|. Text lights up and blank areas are 0, so empty space can
        neither fake a match nor drown one: a sparse page still aligns on its text."""
        e = np.zeros_like(g)
        e[:, :-1] += np.abs(np.diff(g, axis=1))
        e[:-1, :] += np.abs(np.diff(g, axis=0))
        return e

    @staticmethod
    def _mismatch(x: np.ndarray, y: np.ndarray, axis=None):
        """Normalized edge mismatch sum|x-y| / sum(x+y): 0 identical, ~1 unrelated. Sticky
        rows that no shift explains only add their share, instead of swamping the score."""
        return np.abs(x - y).sum(axis=axis) / ((x + y).sum(axis=axis) + 1e-6)

    def _refine(self, EA: np.ndarray, EB: np.ndarray, c: int, gy: int):
        """Exact pixel shift near the coarse estimate c on full-res edge energy:
        (d, mismatch) or (None, None)."""
        best = (None, None)
        for d in range(c - gy - 1, c + gy + 2):
            if d == 0 or abs(d) >= EA.shape[0] - 8:
                continue
            pa, pb = self._shifted(EA, EB, d)
            s = float(self._mismatch(pa[:, ::2], pb[:, ::2]))
            if best[1] is None or s < best[1]:
                best = (d, s)
        return best

    def _band_search(self, a: np.ndarray, b: np.ndarray):
        """a, b: (rows, bands, cols) edge-energy grids. Per band: best vertical shift a->b
        in grid rows (+ = scrolled down, content moved up), its mismatch, and the
        unshifted mismatch."""
        hg = a.shape[0]
        stat = self._mismatch(a, b, axis=(0, 2))
        best = stat.copy()
        best_dy = np.zeros(stat.shape, dtype=int)
        for dy in range(1, int(hg * 0.9)):
            ov = hg - dy
            down = self._mismatch(a[dy:], b[:ov], axis=(0, 2))
            m = down < best - self.EPS
            best[m], best_dy[m] = down[m], dy
            up = self._mismatch(a[:ov], b[dy:], axis=(0, 2))
            m = up < best - self.EPS
            best[m], best_dy[m] = up[m], -dy
        return best_dy, best, stat

    def _detect_region(self, ga: np.ndarray, gb: np.ndarray):
        """Find the scrolling panel between two full frames. Returns (x0,y0,x1,y1) or None.

        Coarse: a per-band shift search on box-mean edge-energy grids nominates the scroll
        dy. Fine: the exact pixel shift is fixed on full-res edge energy, and every
        grid-wide column and every pixel row is then checked at that shift to bound the
        panel."""
        H, W = ga.shape
        gx, gy = self._cells(ga.shape)
        ea, eb = self._energy(ga), self._energy(gb)
        a, b = self._grid(ea, gx, gy), self._grid(eb, gx, gy)
        hg, wg = a.shape
        nb = wg // self.BAND
        if nb < 2 or hg < 10:
            return None
        dy, best, stat = self._band_search(a[:, :nb * self.BAND].reshape(hg, nb, self.BAND),
                                           b[:, :nb * self.BAND].reshape(hg, nb, self.BAND))
        cand = (dy != 0) & (best < stat * 0.6) & (best <= self.MATCH_MAX)
        if cand.sum() < 2:
            return None
        vals, counts = np.unique(dy[cand], return_counts=True)
        dyc = int(vals[np.argmax(counts)])
        bands = np.where(cand & (np.abs(dy - dyc) <= 1))[0]
        if len(bands) < 2:                       # one stray band is noise, not a panel
            return None
        cols = np.concatenate([np.arange(i * self.BAND * gx, (i + 1) * self.BAND * gx) for i in bands])
        EA, EB = ea[:, cols], eb[:, cols]
        d, s = self._refine(EA, EB, dyc * gy, gy)
        if d is None or s > self.MATCH_MAX or s > 0.6 * float(self._mismatch(EA[::2, ::2], EB[::2, ::2])):
            return None

        # Rows first, over the agreeing bands' span. Every panel row in the overlap is an
        # exact shifted copy (blank rows included), and the row just past the panel is
        # not, so the run of shift-consistent rows holding the matched rows is the panel's
        # overlap exactly; the |d| freshly revealed rows lie beyond its leading edge. Sticky
        # header/footer rows (inside the panel or not) fall outside the run.
        bx0, bx1 = int(bands.min()) * self.BAND * gx, (int(bands.max()) + 1) * self.BAND * gx
        A, B = ga[:, bx0:bx1:2], gb[:, bx0:bx1:2]
        stat_r = np.abs(A - B).mean(axis=1)
        sh_r = np.full(H, np.inf)
        pa, pb = self._shifted(A, B, d)
        if d > 0:
            sh_r[:H - d] = np.abs(pa - pb).mean(axis=1)
        else:
            sh_r[-d:] = np.abs(pa - pb).mean(axis=1)
        matched = np.where((sh_r + 1.0 < stat_r) & (sh_r <= self.fine_max * 1.5))[0]
        if len(matched) < 10:
            return None
        tol = max(2.0, 3.0 * float(np.median(sh_r[matched])))
        run = self._best_run(sh_r <= tol, matched)
        if run is None:
            return None
        s, e = run
        r0, r1 = (s, min(H - 1, e + d)) if d > 0 else (max(0, s + d), e)

        # Then columns (gx wide), judged only on the panel's rows: those that moved by
        # exactly d. Keep the run of moving-or-flat columns holding the most moving ones,
        # trimmed to them plus a little flat margin.
        n = W // gx
        ra, rb = ga[r0:r1 + 1, :n * gx], gb[r0:r1 + 1, :n * gx]
        pa, pb = self._shifted(ra, rb, d)
        sh = np.abs(pa[::2] - pb[::2]).reshape(-1, n, gx).mean(axis=(0, 2))
        st = np.abs(ra[::2] - rb[::2]).reshape(-1, n, gx).mean(axis=(0, 2))
        flat = rb[::2].reshape(-1, n, gx).std(axis=(0, 2)) < 2.0
        moving = (sh <= self.fine_max) & (sh < st * 0.5) & ~flat
        if moving.sum() < 2:
            return None
        run = self._best_run(moving | flat, np.where(moving)[0])
        mv = np.where(moving[run[0]:run[1] + 1])[0] + run[0]
        c0 = max(run[0], int(mv.min()) - self.EDGE_PAD)
        c1 = min(run[1] + 1, int(mv.max()) + 1 + self.EDGE_PAD)
        x0, x1 = c0 * gx, (W if c1 >= n else c1 * gx)
        if x1 - x0 < 80 or r1 + 1 - r0 < 60:
            return None
        return (x0, r0, x1, r1 + 1)

    @staticmethod
    def _best_run(mask: np.ndarray, members: np.ndarray):
        """The run of True in mask holding the most of `members`: (start, end) inclusive."""
        inside = np.zeros(len(mask), dtype=bool)
        inside[members] = True
        best, i = None, 0
        while i < len(mask):
            if not mask[i]:
                i += 1
                continue
            s = i
            while i < len(mask) and mask[i]:
                i += 1
            k = int(inside[s:i].sum())
            if k and (best is None or k > best[2]):
                best = (s, i - 1, k)
        return None if best is None else (best[0], best[1])

    def _region_dy(self, ga: np.ndarray, gb: np.ndarray):
        """Pixel shift of the locked panel between two frames: >0 scrolled down,
        <0 up, 0 still, None if it no longer aligns (a different page)."""
        x0, y0, x1, y1 = self.region
        A, B = ga[y0:y1, x0:x1], gb[y0:y1, x0:x1]
        st = float(np.abs(A[::2, ::2] - B[::2, ::2]).mean())
        EA, EB = self._energy(A), self._energy(B)
        gx, gy = self._cells(ga.shape)
        dy, best, stat = self._band_search(self._grid(EA, gx, gy)[:, None, :],
                                           self._grid(EB, gx, gy)[:, None, :])
        if dy[0] != 0 and best[0] < stat[0] * 0.6 and best[0] <= self.MATCH_MAX:
            d, s = self._refine(EA, EB, int(dy[0]) * gy, gy)
            if d is not None and s <= self.MATCH_MAX and s < 0.6 * float(self._mismatch(EA[::2, ::2], EB[::2, ::2])):
                return d
        return 0 if st <= self.static_max else None

    # --- page assembly ---
    def _apply_scroll(self, img: Image.Image, dy: int) -> None:
        x0, y0, x1, y1 = self.region
        rh = y1 - y0
        self.view_top += dy
        if dy > 0:
            reveal = min(self.view_top + rh - self.content.height, rh)
            if reveal > 0 and self.content.height + reveal <= self.max_content_px:
                self.content = _vstack(self.content, img.crop((x0, y1 - reveal, x1, y1)))
        elif self.view_top < 0:
            reveal = min(-self.view_top, rh)
            if self.content.height + reveal <= self.max_content_px:
                self.content = _vstack(img.crop((x0, y0, x1, y0 + reveal)), self.content)
            self.view_top = 0

    def _lock(self) -> None:
        self.region = (min(c[0] for c in self.cands), min(c[1] for c in self.cands),
                       max(c[2] for c in self.cands), max(c[3] for c in self.cands))
        self.content = self.pending[0][0].crop(self.region)
        self.view_top = 0
        for (_, ga), (fb, gb) in zip(self.pending, self.pending[1:]):  # replay buffered scrolls
            dy = self._region_dy(ga, gb)
            if dy:
                self._apply_scroll(fb, dy)
        self.pending, self.cands = [], []

    def _grown(self) -> bool:
        return self.content is not None and self.content.height > (self.region[3] - self.region[1]) * 1.05

    def _settle(self, img: Image.Image, sig: np.ndarray):
        if distance(sig, self.prev_sig) > self.settle:   # whole screen still moving (e.g. typing)
            self.stable = 0
            return None
        self.stable += 1
        if self.stable < (self.page_stable_polls if self.region is not None else self.stable_polls):
            return None
        if self.emitted and distance(sig, self.emit_sig) < self.threshold:
            return None                                  # this state was already sent
        self.emitted, self.emit_sig = True, sig
        return (img, [self.content] if self._grown() else [])

    def _step_locked(self, img: Image.Image, g: np.ndarray, sig: np.ndarray):
        dy = self._region_dy(self.prev_g, g)
        if dy is None:                                   # panel no longer aligns: a new page
            out = (self.prev, [self.content]) if (self._grown() and not self.emitted) else None
            self.reset()
            return out
        if dy:
            self._apply_scroll(img, dy)
            self.stable, self.emitted = 0, False
            return None
        return self._settle(img, sig)

    def feed(self, img: Image.Image, gl: Image.Image | None = None):
        """Feed one captured frame. Returns (frame, [content...]) to send, or None. `gl` is the frame
        already in grey, which the poll loop has when it hands a frame over: both readings below start
        from it, so a stitched frame is converted once at full resolution instead of twice."""
        gl = gl if gl is not None else gray_plane(img)
        g, sig = self._gray(gl), signature(gl)
        out = None
        if self.prev is not None:
            if self.region is not None:
                out = self._step_locked(img, g, sig)
            else:
                det = self._detect_region(self.prev_g, g)
                if det is not None:                      # a scroll: buffer until the region is sure
                    if not self.pending:
                        self.pending.append((self.prev, self.prev_g))
                    self.pending.append((img, g))
                    self.cands.append(det)
                    self.stable, self.emitted = 0, False
                    if len(self.cands) >= self.LOCK_AFTER:
                        self._lock()
                elif self.pending:                       # scrolled briefly, then paused: lock now
                    self._lock()
                    out = self._step_locked(img, g, sig)
                else:
                    out = self._settle(img, sig)
        self.prev, self.prev_g, self.prev_sig = img, g, sig
        return out


# This program's run: a random word it keeps while it runs, and through a restart of its own (the next one starts with
# this environment), said in its hello. By it the server tells this program's own earlier connection (one a sleep left
# open there) from another capture program's (take_over in server/app.py).
RUN = os.environ.get("SIDENOTE_CAPTURE_RUN", "")
if not re.fullmatch(r"[0-9a-f]{16}", RUN):
    RUN = secrets.token_hex(8)
os.environ["SIDENOTE_CAPTURE_RUN"] = RUN


class Sender:
    """Thread-safe WebSocket sender with lazy reconnect. Also carries what the panel asked
    for (screen / sound capture on or off, `wants`) and what this client can do (`caps`)."""

    def __init__(self, url: str):
        self.url = url
        self._ws: websocket.WebSocket | None = None
        self._lock = threading.Lock()
        # Bumped on each *re*connect (and on a first connect that follows failed tries) so capture
        # loops know to re-send their current state to the freshly-restarted server.
        self.epoch = 0
        self._connected_once = False
        # What the panel asked for: the switches, scroll stitching and the monitor (the latter two start
        # from this program's options and follow the panel's settings after that), following the changing screen (off
        # until the server says on: an older one never does), and the words of Skip windows, the server's default list
        # until the server says its own.
        self.wants = {"screen": True, "audio": True, "stitch": False, "monitor": 1, "monitor_follow": False,
                      "skip_windows": skip_words(SKIP_WINDOWS)}
        self.caps: dict = {"screen": True}
        self.who: dict = {}       # what the hello says of this program (who_am_i): none for a stand-in sender
        self._down = False        # the server is unreachable: said once, not on every retry
        self._last_try = 0.0
        self.told = threading.Event()   # the server's switches arrived (sent on every connect)
        # `./sidenote capture-stop` asks through the server rather than killing this process, so it
        # ends itself and takes its tray icon with it (a killed program leaves the icon behind).
        self.quit_asked = False
        self.taken_over = False      # that quit was for another capture program, which feeds the server now
        self.quit_by_person = False  # Quit pressed in the tray: the one end that also ends a server this start brought up
        self.restart_asked = False   # the tray's Restart, ./sidenote capture-restart, or a deploy's (Updater)
        self.restart_pending = False # a deploy asked for one at a quiet moment (Updater)
        self.auto_update = True      # a deploy's restart is taken (Updater): main() sets it off for --no-auto-update and --once
        self.last_frame_ts = 0.0     # when a screen last went out: a restart waits for the screen to rest

    @property
    def connected(self) -> bool:
        """A socket to the server is open right now."""
        return self._ws is not None

    def set_caps(self, **caps) -> None:
        """Tell the server what this client can do (e.g. whether a sound device opened)."""
        self.caps.update(caps)
        self.send({"type": "caps", **self.caps})

    def _ensure(self) -> websocket.WebSocket:
        if self._ws is None:
            ws = websocket.create_connection(self.url, max_size=None, timeout=5)
            ws.settimeout(None)   # the timeout is for connecting; a read waits as long as it takes
            # A peer gone without a word (a PC waking from sleep, a stalled WSL) would otherwise leave this socket
            # "connected" on a still screen, with nothing sent to find out. An extra: without it, it works as before.
            try:
                ws.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "SIO_KEEPALIVE_VALS"):   # Windows waits two hours by default: 30 s, then every 10 s
                    ws.sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
            except Exception:
                pass
            try:
                # What this client is, which the panel shows and the log keeps. The name carries the
                # platform rather than assuming one: the server takes any program that speaks this
                # protocol, and the Windows parts of this one (the window list, the display metrics,
                # the notification icon) are extras it does without elsewhere.
                # `who`: the PC, its system, this release, how it was started and what its Quit ends (who_am_i), for
                # the panel's Capture connection. Said in every hello, a reconnect's too: the server keeps it with the
                # connection, not with the program
                ws.send(json.dumps({"type": "hello", "info": f"capture/{sys.platform}", "run": RUN,
                                    **({"who": self.who} if self.who else {}), **self.caps}))
            except Exception:
                ws.close()
                raise
            self._ws = ws
            self.caps.pop("flags", None)   # this start's options count once, not again on every reconnect
            threading.Thread(target=self._drain, args=(ws,), daemon=True).start()
            if self._connected_once or self._down:
                self.epoch += 1  # a reconnect, or a first connect after failed tries -> loops re-send
            self._connected_once = True
            self._down = False
            print("[conn] " + t("connected to {url}", url=self.url))
        return self._ws

    def _note_down(self, exc: Exception) -> None:
        if not self._down:
            print("[conn] " + t("cannot reach the server ({error}); retrying", error=exc))
            self._down = True

    def keepalive(self) -> None:
        """Reconnect even when nothing is being sent (switches off, a still screen): after a server
        restart the panel could otherwise not reach this program, and it would look switched off."""
        with self._lock:
            if self._ws is not None or self.quit_asked or time.time() - self._last_try < 2.0:
                return   # (asked to quit: never connect again, as send says)
            self._last_try = time.time()
            try:
                self._ensure()
            except Exception as exc:
                self._note_down(exc)

    def _drain(self, ws: websocket.WebSocket) -> None:
        """Keep reading the socket. websocket-client answers the server's keepalive pings
        only inside recv(), and uvicorn drops a client that never answers them after
        ping interval + timeout (~40s), which would also reset a scroll being stitched.
        A message it cannot act on is let go and the reading goes on. When the reading ends (the server closed, a frame
        the library would not take), mark the socket dead so the next send reconnects, and close it."""
        try:
            while True:
                raw = ws.recv()
                try:
                    self._on_message(raw)
                except Exception:   # a message it cannot act on is let go: the reading goes on, and with it the pings
                    pass
        except Exception:
            pass
        with self._lock:
            if self._ws is ws:
                self._ws = None
        # Nothing reads this socket any more, and nothing answers the server's pings on it: closed, so the server is not
        # left holding a connection that looks open. Outside the lock: a close waits a moment for the server's reply.
        try:
            ws.close()
            ws.shutdown()   # close() returns at once, the socket left open, when a close was sent already: shut either way
        except Exception:
            pass

    def _on_message(self, raw) -> None:
        """What the panel asked for: {"type": "control", "screen": bool, "audio": bool, "stitch": bool,
        "monitor": int, "monitor_follow": bool, "skip_windows": [str]}."""
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if not isinstance(msg, dict):   # JSON but no object (a list, a number, a string): no message this program knows
            return
        app = os.environ.get("SIDENOTE_SUPERVISED") == "1"   # under the desktop app, which has no ./sidenote to name
        if msg.get("type") == "quit":
            if msg.get("reason") == "taken_over":   # another capture program connected to this server: it feeds it now
                by = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(msg.get("by") or "?"))[:80]   # its words, no terminal codes
                print("[control] " + t("Another capture program now feeds this server ({by}): this one stops", by=by))
                self.taken_over = True
            elif msg.get("reason") == "panel":     # Quit on the panel's Capture connection
                print("[control] " + t("Quit from the panel"))
            else:   # ./sidenote capture-stop or down; under the app, the app ending (or the API)
                print("[control] " + (t("The server asked this program to quit") if app
                                      else t("The server asked this program to quit (./sidenote capture-stop)")))
            self.quit_asked = True
            return
        if msg.get("type") == "restart":
            if self.taken_over:   # another program feeds the server: a copy of this one would take it back
                return
            if msg.get("quiet"):           # a deploy with new code for this program: at a quiet moment (Updater)
                if not getattr(self, "auto_update", True):   # --no-auto-update: no Updater runs to take it, so it is not
                    # waited for; the code running now goes on until a restart is asked for (the tray's Restart capture).
                    # Said as asked for, not as a deploy: the API asks for one too, and the desktop app passes the switch
                    print("[control] " + t("A restart at a quiet moment was asked for: not taken by this program (--no-auto-update)"))
                    return
                print("[control] " + t("New code was deployed: restarting at a quiet moment (./sidenote up)"))
                self.restart_pending = True
            else:   # the panel's Capture connection, or ./sidenote capture-restart: the tray's Restart, asked from elsewhere
                print("[control] " + (t("Restarting from the panel") if msg.get("reason") == "panel"
                                      else t("The server asked this program to restart") if app
                                      else t("The server asked this program to restart (./sidenote capture-restart)")))
                self.restart_asked = self.quit_asked = True
            return
        if msg.get("type") != "control":
            return
        for k in ("screen", "audio"):
            if isinstance(msg.get(k), bool) and msg[k] != self.wants[k]:
                self.wants[k] = msg[k]
                said = {("screen", True): t("screen capture on (from the panel)"), ("screen", False): t("screen capture off (from the panel)"),
                        ("audio", True): t("sound capture on (from the panel)"), ("audio", False): t("sound capture off (from the panel)")}
                print("[control] " + said[(k, msg[k])])
        if isinstance(msg.get("stitch"), bool) and msg["stitch"] != self.wants["stitch"]:
            self.wants["stitch"] = msg["stitch"]
            # by the panel's own name for the switch, as its Korean has always said it
            print("[control] " + (t("Join scrolled screens on (from the panel)") if msg["stitch"] else t("Join scrolled screens off (from the panel)")))
        m = msg.get("monitor")
        if isinstance(m, int) and not isinstance(m, bool) and m >= 0 and m != self.wants["monitor"]:
            self.wants["monitor"] = m
            # 0 is All monitors, said by its name as the panel's Monitor says it, never as a monitor of that number
            print("[control] " + (t("all monitors (from the panel)") if m == 0 else t("monitor {n} (from the panel)", n=m)))
        follow = msg.get("monitor_follow")    # absent from an older server's message: it stays off
        if isinstance(follow, bool) and follow != self.wants.get("monitor_follow", False):
            self.wants["monitor_follow"] = follow
            print("[control] " + (t("following the changing screen on (from the panel)") if follow
                                  else t("following the changing screen off (from the panel)")))
        words = msg.get("skip_windows")       # absent from an older server's message: the list held stays
        if (isinstance(words, list) and all(isinstance(w, str) for w in words)
                and skip_words(words) != self.wants.get("skip_windows")):
            self.wants["skip_windows"] = skip_words(words)
            # how many, not which: the log says nothing of what is skipped
            print("[control] " + t("{n} word(s) for windows to skip (from the panel)", n=len(self.wants["skip_windows"])))
        self.told.set()

    def send(self, message: dict) -> None:
        if message.get("type") == "frame":
            self.last_frame_ts = time.time()
        text = json.dumps(message)   # made outside the lock: a sound frame is 64 KB of base64 to encode
        with self._lock:
            if self._ws is None and self.quit_asked:
                # Asked to quit: no connecting again on the way out, where another capture program may feed the
                # server now (take_over in server/app.py) and a connection from this one would take it back.
                return
            try:
                self._ensure().send(text)
            except Exception as exc:
                self._note_down(exc)
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None


def _grabber():
    """mss's screen grabber class: mss.MSS from 10.x on (where mss.mss is deprecated and slated
    for removal), mss.mss on older releases."""
    import mss  # lazy: imported only where a screen is actually grabbed

    return getattr(mss, "MSS", None) or mss.mss


# count, width, height, and where the virtual screen starts: two monitors of the same size swapped
# leave the first three alone and move the origin.
DISPLAY_METRICS = (80, 78, 79, 76, 77)


def display_signature() -> tuple:
    """How many monitors there are and how big the whole desktop is, asked of Windows directly.
    mss reads its monitor list once per grabber, so one plugged in or unplugged while this runs
    went unnoticed until the program was restarted (and the panel kept offering the old list)."""
    if sys.platform != "win32":
        return ()
    try:
        import ctypes
        get = ctypes.windll.user32.GetSystemMetrics
        return tuple(int(get(m)) for m in DISPLAY_METRICS)
    except Exception:
        return ()


def list_monitors() -> None:
    """Print the monitors mss sees, so the user knows what --monitor index to pass."""
    with _grabber()() as sct:
        mons = sct.monitors
        print(t("available monitors (pass the index to --monitor):"))
        print("  " + t("0 = all monitors combined (virtual screen): {box}", box=mons[0]))
        for i, m in enumerate(mons[1:], start=1):
            print("  " + t("{i} = {w}x{h} at ({x},{y})", i=i, w=m["width"], h=m["height"], x=m["left"], y=m["top"]))
    print("\n" + t("default is 1 (primary). 0 captures every monitor as one wide image."))


# ---------- Following the changing screen (Solver settings > Capture > Follow the changing screen) ----------
# The panel's Monitor picks one monitor, and a problem that comes up on another is never read. With this switch on
# (off by default: most people set one monitor and keep it) the other monitors are looked at too, now and then, and
# never sent; the reading moves to the one where a new screen came to rest (another page, the next problem, the next
# slide), and comes back to the chosen one the same way once a new screen rests there. A look at another monitor is a
# grab of it, as a look at the one read is, so they are few.
FOLLOW_LOOK_SEC = 1.5      # how often each monitor not read is looked at
# A new screen, on the signature the send gate reads (the server's in server/gate.py), as follow_reading takes it.
# Measured on the bench's screens at 1920x1080 and 3840x2160 (docs/DECISIONS.md, note 130): another site 0.21 to 7.5
# apart, the next problem on the same site 0.17 to 1.31 (about 0.9 in the middle), the next slide 0.84 to 3.15. The
# server's mark of a new problem (SIDENOTE_CHANGE_THRESHOLD, 0.5) is the line here too.
FOLLOW_NEW = 0.5
# A notification in a corner changes about as much (up to 0.87), in a box of a few rows: 14% of the signature's rows at
# the most changed by 0.5, three chat lines 16%, five lines typed 12%; the next problem on the same site 34% in the
# middle, the next slide 30% and more. A new screen reaches a fifth of them at the least.
FOLLOW_ROWS = 0.2
# A chat that takes a message moves its pane up by that message, which is a large change over most rows (1.2 to 5.6 over
# the screen, on 70% to 95% of the rows). The row profiles say it moved: the bands the pane covers find the same shift.
# Between two looks seconds apart, unrelated screens line up in a band or two by chance (two agreeing, scroll_shift's
# mark, read 37% of the bench's pairs of different sites as moved), but not in most of the bands that changed: 5 of 8 at
# the most. A chat's pane lined up in two thirds of them or more in 71 of 72, at three sizes; a move nobody made costs
# more than one missed, so that is the line, under the three quarters a chat drawn for the checks missed with two
# messages at once (5 of 7).
FOLLOW_MOVED = 2 / 3
FOLLOW_STILL_LOOKS = 2     # looks in a row at rest, after a change, before what rests there counts
FOLLOW_HOLD_SEC = 10.0     # after a move, the least time on the monitor moved to: no back and forth between busy screens


def content_moved(before_prof, after_prof) -> bool:
    """Whether the screen after is the one before moved up or down (a pane scrolled, a chat that took a message): at
    least two bands, and FOLLOW_MOVED of those that changed, found one shift (scroll_votes)."""
    _, agree, judged = scroll_votes(before_prof, after_prof)
    return agree >= SCROLL_BANDS_AGREE and agree >= FOLLOW_MOVED * judged


def new_screen(before, after, before_prof, after_prof) -> bool:
    """Whether `after` is a new screen against `before`, from their signatures and their row profiles (scroll_profile):
    changed by FOLLOW_NEW over the whole screen and by as much over FOLLOW_ROWS of its rows, and not the same content
    moved (content_moved)."""
    diff = np.abs(after - before)                                # cell by cell, as distance() takes it
    if float(diff.mean()) < FOLLOW_NEW:                          # too little over the whole screen
        return False
    rows = diff.reshape(SIG_SIZE[1], SIG_SIZE[0]).mean(axis=1)   # each row of the signature, its own change
    if float(np.mean(rows >= FOLLOW_NEW)) < FOLLOW_ROWS:         # a box of a few rows: a notification, chat lines
        return False
    return not content_moved(before_prof, after_prof)            # what was there, moved, is no new screen


class ScreenFollow:
    """Which monitor to read while following the changing screen. Pure (no screens and no clock of its own): fed each
    monitor's looks, its signature and row profile with the time of the look, and asked which monitor to read, so the
    rules are checked without monitors (tests/monitor_follow.py).

    Each monitor keeps the screen it last rested on. A look further than `still` from the look before is a change under
    way; once FOLLOW_STILL_LOOKS looks in a row come no further than that from the one before, the change is over, and
    it brought a new screen when what rests now is one against what rested before (new_screen). A video never rests, so
    it never brings one. The reading moves to the monitor where the newest such screen came to rest since the last move,
    unless the monitor being read rested on a new screen of its own after that change began, and FOLLOW_HOLD_SEC after
    the last move at the earliest, unless the monitor being read could not be looked at (a window of Skip windows shows
    there): nothing is read there to stay for. With the switch off, one monitor, or all of them read as one picture (0),
    it reads the chosen one, and a change of any of those takes it back there at once."""

    def __init__(self, still: float, looks: int | None = None, hold: float | None = None):
        self.still = still            # signature MAD between two looks at or under which a screen is at rest
        # looks in a row at rest that end a change, and the least time between two moves: the module's, read now
        self.looks = FOLLOW_STILL_LOOKS if looks is None else looks
        self.hold = FOLLOW_HOLD_SEC if hold is None else hold
        self.on, self.chosen, self.count = False, 1, 0   # the switch, the monitor chosen in the panel, how many
        self.reading = 1              # the monitor read now
        self.seen: dict = {}          # monitor -> what its looks have shown (look)
        self.moved = float("-inf")    # when the reading last moved, or was held where it is (stay)

    def setup(self, on: bool, chosen: int, count: int) -> None:
        """The switch, the monitor chosen in the panel and how many there are. A change of any of them reads the chosen
        monitor again at once and starts the watching afresh."""
        if (on, chosen, count) != (self.on, self.chosen, self.count):
            self.on, self.chosen, self.count = on, chosen, count
            self.reset()

    def reset(self) -> None:
        """The chosen monitor read again, and nothing seen of any (the monitors read again, a grab that failed)."""
        self.reading, self.seen, self.moved = self.chosen, {}, float("-inf")

    @property
    def active(self) -> bool:
        """Whether there is anywhere to move: switched on, with two monitors or more, one of them chosen."""
        return self.on and self.chosen != 0 and self.count >= 2

    @property
    def following(self) -> int | None:
        """The monitor read when it is not the chosen one, else None: what the server is told (caps, following)."""
        return self.reading if self.reading != self.chosen else None

    def look(self, monitor: int, sig, prof, now: float) -> None:
        """One look at `monitor`: its signature and row profile at `now`. None for both when it could not be looked at
        (a window of Skip windows shows there, a grab that failed): no move goes there then, and its next look starts it
        afresh. The monitor being read is fed None while a window of Skip windows shows there, and is then no place to
        hold the reading at (pick)."""
        if sig is None:
            self.seen.pop(monitor, None)          # what it showed before says nothing of what it shows after
            return
        m = self.seen.get(monitor)
        if m is None:                             # its first look: what it shows is what it rests on
            self.seen[monitor] = {"rest": sig, "rest_prof": prof, "last": sig, "still": self.looks,
                                  "began": None, "new": None, "new_began": None}
            return
        if distance(sig, m["last"]) > self.still:  # moving: a change under way, from the screen it rested on
            m["still"] = 0
            if m["began"] is None:
                m["began"] = now
        else:
            m["still"] += 1
        m["last"] = sig
        if m["still"] >= self.looks:              # at rest
            if m["began"] is not None:            # the end of a change: a new screen, or the old one back
                if new_screen(m["rest"], sig, m["rest_prof"], prof):
                    m["new"], m["new_began"] = now, m["began"]
                m["began"] = None
            # what rests now is what the next change is measured from: steps too small to be a change add up to none
            m["rest"], m["rest_prof"] = sig, prof

    def stay(self, now: float) -> None:
        """Hold the reading where it is, as a move to it would: a scrolled problem is being joined on it. What came to
        rest elsewhere until now is let go, and the hold runs from now."""
        self.moved = now

    def pick(self, now: float) -> int:
        """The monitor to read now, moved where a new screen came to rest (the class says when)."""
        if not self.active:
            self.reading = self.chosen
            return self.reading
        read = self.seen.get(self.reading)        # None while the monitor read could not be looked at (look)
        if now - self.moved < self.hold and read is not None:   # moved a moment ago, to a monitor that can be read
            return self.reading
        best = None
        for k, m in self.seen.items():
            if k == self.reading or m["new"] is None or m["new"] <= self.moved:
                continue                          # nothing new there since the last move
            if m["began"] is not None or m["still"] < self.looks:
                continue                          # changing again: moved to once it rests
            if read is not None and read["new"] is not None and read["new"] >= m["new_began"]:
                continue                          # a new screen rested on the one read since that change began
            if best is None or m["new"] > self.seen[best]["new"]:
                best = k                          # the newest screen to come to rest
        if best is not None:
            self.reading, self.moved = best, now
        return self.reading


# What following reads of a grab is a copy of it a whole number of times smaller, about this many pixels on its longer
# side: the signature (160x120) and the row profile (240 rows) it is read for need no more, and taken from the grabbed
# bytes by striding, it skips turning a 4K screen into an image at full size, which is most of what a look costs after
# the grab (docs/DECISIONS.md, note 130).
FOLLOW_SIDE = 1280


def follow_reading(shot, found) -> tuple:
    """(signature, row profile) of a grab (mss's, or one made up), as following reads every monitor, the one read too,
    so that their looks compare: shrunk by whole steps to about FOLLOW_SIDE, this tool's panel painted over (`found`,
    from window_rects) so that its answers are no new screen."""
    w, h = shot.size
    step = max(1, round(max(w, h) / FOLLOW_SIDE))           # every step-th pixel of every step-th row
    raw = getattr(shot, "raw", None)                       # mss keeps the bytes it grabbed: read in place, not copied
    grabbed = np.frombuffer(raw if raw is not None else shot.bgra, dtype=np.uint8).reshape(h, w, 4)
    img = Image.fromarray(np.ascontiguousarray(grabbed[::step, ::step, 2::-1]))   # BGRA to RGB, the small copy only
    if found is not None and found[1]:
        img = hide_own(img, found[0], found[1])            # its rectangles are fractions, so they fit any size
    grey = gray_plane(img)                                 # one grey plane for both readings
    return signature(grey), scroll_profile(grey)


def watch_look(sct, mon: dict, front, words) -> tuple:
    """A look at a monitor that is not read, for following: (signature, row profile), read as follow_reading reads every
    monitor. (None, None) while a window of Skip windows shows there, which no grab may take, or when the grab fails."""
    if words and skip_now(front, words, mon):     # nothing of a monitor that shows one is grabbed, as of the one read
        return None, None
    try:
        shot = sct.grab(mon)
    except Exception:                             # a monitor going away: the next look at the monitors says so
        return None, None
    if words and skip_now(front, words, mon):     # one came up while it was grabbed: the grab is let go unread
        return None, None
    return follow_reading(shot, window_rects(mon))   # this tool's own panel on that monitor, painted over


DOWN_POLL = 2.0   # how often to look while there is no server to send to

# Looking at the screen is not free. Measured on this PC's 3840x2160 screen, one look that sends
# nothing costs 174 ms: 112 ms to grab it, 25 ms to turn the grabbed buffer into an image, 35 ms for
# the two readings the send gate makes of it, 1 ms for the window list. Three of those a second is
# a third of a processor core, and the running program agrees (7.0 s of processor time in 20 s).
# It costs that whether the screen holds a new problem or the same desktop as ten minutes ago, and
# the server's log says it is nearly always the latter: of 1,014 screens it was asked about in one
# day, 1,001 held nothing to solve. So a screen that has stopped moving is looked at less often.
# "Stopped moving" is what the send gate counts as settled: each look differs from the one before by
# no more than --settle (0.3). The first look that moves more than that brings the full rate straight
# back; a screen that changes in smaller steps stays at the slow rate, and is still sent there once it
# is --threshold (0.1) away from the screen last sent (measured on the real SendGate: five frames went
# out while the loop stayed slowed).
# The numbers are set so that someone at the keyboard hardly notices it: half a minute with no look
# that moves more than the settle threshold, and even then the next look is half a second away, not a
# second. It halves what the program costs while the screen is being read rather than worked on.
STILL_POLLS = 90      # settled looks in a row before slowing down (30 s at 3 fps)
STILL_PERIOD = 0.5    # seconds between looks while they stay settled
LOOK_REPORT_SEC = 300.0   # how often what the looking costs is written to the log


def screen_loop(sender: Sender, stop: threading.Event, args) -> None:
    period = 1.0 / args.fps
    gate = SendGate(args.threshold, args.settle, args.stable_polls)
    stitcher = None
    my_epoch = sender.epoch
    failing = False   # the grab is failing: said once, and said again when it works
    told_monitors = None

    def send_image(img: Image.Image, tag: str, mon: dict, extras=()) -> None:
        msg = {"type": "frame", "data": _png_b64(img)}
        if extras:
            msg["extra"] = [_png_b64(e) for e in extras]  # unrolled scroll content
        found = window_rects(mon)
        if found is not None:
            msg["windows"] = found[0]
        sender.send(msg)
        more = f" + scrolled page {extras[0].width}x{extras[0].height}" if extras else ""
        print(f"[{tag}] sent frame ({img.width}x{img.height}){more}")

    said_down = False     # "waiting for the server" is said once, not on every poll
    hidden_said = False   # the panel being on screen is said once, not on every frame
    front = None          # the windows on the desktop (FrontWindow), opened at the first look that has words to skip
    said_why = ""         # why the windows cannot be read here, said once for each reason
    told_limit = ""       # what the server was last told of that (caps, skip_limit)
    skipping = False      # a window of Skip windows is on screen: nothing is grabbed or sent while it is
    skipped_by = None     # the words a skip was last made by: a skip that ends as they change was ended by them, not by the window
    skipped_on = None     # the monitor a skip was last made on: one that ends as following moves the reading was ended by the move
    slowed = False        # looking less often because the screen stopped changing: said on each flip
    looks: list[float] = []            # how long each look took, for the cost line below
    look_t0 = look_cpu0 = 0.0          # start of the window those looks are counted over
    # Joining a scrolled problem by itself: what the screen held last, how long since it last moved.
    prev_prof = last_full = prev_full = None
    auto_stitch, auto_idle, last_scroll = False, 0, 0
    auto_off = args.no_auto_stitch
    # Following the changing screen: which monitor to read (ScreenFollow), when the others are looked at next, and what
    # the server was last told of it (caps, following: None while the chosen monitor is read)
    follow = ScreenFollow(args.threshold)   # at rest: two looks no further apart than a screen not worth sending again
    next_watch = 0.0
    told_following = None
    told_sees = None          # whether the window list could be read, as last told (caps follow_ok)

    def start_over() -> None:   # the current screen goes out again on the next poll
        nonlocal prev_prof, prev_full, last_full, last_scroll
        gate.resend()
        if stitcher:
            stitcher.reset()
        # What was read off the old screen says nothing about the new one: a frame from another
        # monitor fed to the stitcher only raises (it reshapes to the first frame's size).
        prev_prof = prev_full = last_full = None
        last_scroll = 0

    def follow_watch(sct, shot, found, words, held: bool) -> None:
        """Following the changing screen: every FOLLOW_LOOK_SEC the monitor read and each of the others (watch_look) are
        looked at, read the same way, and the reading moves where a new screen came to rest (ScreenFollow). The monitor
        read is looked at through this poll's grab (`shot`, its panel `found`), or not at all (None) while a window of
        Skip windows shows there: the others are looked at all the same, so that a new screen that comes to rest on one of
        them, the chosen monitor too, takes the reading away from it. `held`: a scrolled problem being joined there holds
        the reading."""
        nonlocal next_watch, reading, monitor, told_following
        now = time.time()
        if not follow.active or now < next_watch:
            return
        next_watch = now + FOLLOW_LOOK_SEC
        follow.look(reading, *(follow_reading(shot, found) if shot is not None else (None, None)), now)
        for k in range(1, len(sct.monitors)):
            if k != reading:
                follow.look(k, *watch_look(sct, sct.monitors[k], front, words), now)
        if held:
            follow.stay(now)
        if follow.pick(now) != reading:   # one line for each move, which says monitors and nothing they show
            print("[screen] " + t("a new screen came to rest on monitor {to}: reading it instead of monitor {at}",
                                  to=follow.reading, at=reading))
            reading, monitor = follow.reading, sct.monitors[follow.reading]
            start_over()   # its screen goes out as soon as it is at rest, as a screen chosen in the panel
        if follow.following != told_following:
            told_following = follow.following
            sender.set_caps(following=told_following)

    reading = monitor = None   # the monitor read now, and its place: set at each start of the block below
    while not stop.is_set():
        try:
            with _grabber()() as sct:
                asked = sender.wants["monitor"]
                index = asked if 0 <= asked < len(sct.monitors) else 1
                if index != asked:
                    print("[screen] " + t("monitor {asked} not found; {n} attached. Using 1.", asked=asked, n=len(sct.monitors) - 1))
                    # the desktop app has no ./sidenote to run, and its panel lists the monitors where one is chosen
                    print("         " + (t("Monitor in Solver settings lists them.") if os.environ.get("SIDENOTE_SUPERVISED") == "1"
                                          else t("./sidenote capture --list-monitors shows them.")))
                monitor = sct.monitors[index]
                sizes = [[m["width"], m["height"]] for m in sct.monitors[1:]]
                # Following looks at monitors this tool's panel may be on, and paints the panel over first so that its
                # answers are no new screen; where the window list cannot be read (off Windows and macOS) the panel
                # cannot be found, and an answer written there would take the reading to it. So no following there, and
                # the panel is told so (follow_ok) to grey its switch out with the reason.
                sees_windows = window_rects(monitor) is not None
                if sizes != told_monitors or sees_windows != told_sees:   # the panel lists them to choose from
                    sender.set_caps(monitors=sizes, monitor=index, follow_ok=sees_windows)
                    told_monitors, told_sees = sizes, sees_windows
                if not failing:
                    mode = t("scroll-stitch") if sender.wants["stitch"] else t("single-shot")
                    print("[screen] " + (t("capturing all monitors: {w}x{h} ({mode})", w=monitor["width"], h=monitor["height"], mode=mode)
                                         if index == 0 else   # All monitors, by its name: mss's monitor 0 is no monitor of that number
                                         t("capturing monitor {i}: {w}x{h} ({mode})", i=index, w=monitor["width"], h=monitor["height"], mode=mode)))
                screens = display_signature()
                # Each start of this block reads the chosen monitor: another one chosen in the panel, the monitors read
                # again or a grab that failed leave nothing of what following had seen
                follow.setup(bool(sender.wants.get("monitor_follow")) and not args.once and sees_windows, index, len(sct.monitors) - 1)
                follow.reset()
                reading = index   # the monitor read now: the chosen one, until following moves it
                while not stop.is_set():
                    t0 = time.time()
                    sender.keepalive()
                    if sender.wants["monitor"] != asked:   # another monitor chosen in the panel
                        start_over()
                        break
                    now_screens = display_signature()
                    if now_screens != screens:   # a monitor plugged in, unplugged or resized
                        print("[screen] " + t("the monitors changed {before} -> {after}; reading them again", before=screens, after=now_screens))
                        start_over()
                        break
                    # Following the changing screen, switched in the panel (never for --once, which sends one screen):
                    # off, it reads the chosen monitor, and one it had moved to is left at once
                    follow.setup(bool(sender.wants.get("monitor_follow")) and not args.once and sees_windows, index,
                                 len(sct.monitors) - 1)
                    if follow.reading != reading:
                        print("[screen] " + t("following is off: back to monitor {n}", n=follow.reading))
                        reading, monitor = follow.reading, sct.monitors[follow.reading]
                        start_over()
                    if follow.following != told_following:   # which monitor is read, for the panel's card
                        told_following = follow.following
                        sender.set_caps(following=told_following)
                    # The panel's own switch, which is not the same as the one this loop turns on by
                    # itself when the screen scrolls: without `not auto_stitch` here, the stitcher
                    # started below was thrown away on the very next poll and never joined anything.
                    if sender.wants["stitch"] != (stitcher is not None) and not auto_stitch:
                        stitcher = ScrollStitcher(args.stable_polls, settle=args.settle) if sender.wants["stitch"] else None
                        print("[screen] " + t("{mode} mode", mode=t("scroll-stitch") if stitcher else t("single-shot")))
                        start_over()
                    if sender.wants["stitch"] and auto_stitch:   # the panel took it over: it is no longer ours
                        auto_stitch = False
                    if not sender.connected:
                        # No server: a grab here is a 4K screenshot encoded to PNG and thrown away,
                        # three times a second, on the PC this tool is supposed to leave alone.
                        if args.once:
                            print("[screen] " + t("Not connected to the server, so nothing can be sent (--once)"))
                            stop.set()
                            break
                        if not said_down:
                            print("[screen] " + t("Not taking the screen until the server is connected"))
                            said_down = True
                        stop.wait(DOWN_POLL)
                        continue
                    if said_down:
                        print("[screen] " + t("Connected to the server again"))
                        said_down = False
                    if not sender.wants["screen"]:     # switched off in the panel: no grabbing at all
                        if args.once:                  # one screen was asked for and none can be taken
                            print("[screen] " + t("Screen capture is off in the panel, so nothing was sent (--once)"))
                            stop.set()
                            break
                        start_over()                   # back on -> the current screen goes out again
                        stop.wait(0.5)
                        continue
                    if sender.epoch != my_epoch:
                        start_over()  # reconnected: re-send the current screen
                        my_epoch = sender.epoch
                    # Skip windows: while a window the panel's words name is in front or shows on this monitor, the screen is
                    # neither grabbed nor sent. The change detection keeps what it last saw, so coming back to the same
                    # problem is not a new screen. Only that a skip started and ended is said, never which window.
                    words = sender.wants.get("skip_windows")
                    skip, limit = False, ""
                    if words:
                        front = front or FrontWindow()   # opened only once there is something to look for
                        skip = skip_now(front, words, monitor)
                        limit = front.limit
                        if front.why != said_why:        # Wayland, no X11 display, a read that broke: said once for each
                            said_why = front.why
                            if said_why:
                                print("[screen] " + (t("The windows behind the one in front cannot be listed here ({why}), "
                                                       "so only that one is skipped", why=said_why) if limit == "front" else
                                                     t("The windows cannot be read here ({why}), so no window is skipped", why=said_why)))
                    if limit != told_limit:        # what the panel's card says of it: no word of what is on screen
                        told_limit = limit
                        sender.set_caps(skip_limit=limit)
                    if skip != skipping:           # a skip starts or ends: the panel's card and the tray say so
                        skipping = skip
                        print("[screen] " + (t("A window to skip is on screen: no screen is sent while it is") if skip else
                                             # the panel's words changed (emptied, or none names it now): the window may be
                                             # on screen still, so that is not what is said
                                             t("Skip windows changed: capturing the screen again") if words != skipped_by else
                                             # the reading moved to another monitor: the window may still show where it was
                                             t("Reading another monitor: capturing the screen again") if monitor != skipped_on else
                                             t("The window to skip is no longer on screen: capturing the screen again")))
                        sender.set_caps(skipping=skip)
                    if skip:
                        skipped_by = words         # the words it is skipped by, for the line when it ends
                        skipped_on = dict(monitor) # and the monitor by its place and size (a block started again has new ones)
                        if args.once:              # the one screen asked for may not be sent
                            print("[screen] " + t("A window to skip is on screen, so nothing was sent (--once)"))
                            stop.set()
                            break
                        # Nothing of this monitor is grabbed, but following goes on looking at the others, so a reading it
                        # moved here leaves for a new screen that comes to rest elsewhere, on the chosen monitor too. No
                        # join holds it: nothing is joined while nothing is grabbed.
                        follow_watch(sct, None, None, words, False)
                        stop.wait(period)          # looked at again on the next poll: capture goes on once it is gone
                        continue
                    shot = sct.grab(monitor)
                    # One brought up while the screen was being grabbed (a 4K grab takes a tenth of a second): this grab
                    # is dropped, and the next look starts the skip
                    if words and skip_now(front, words, monitor):
                        continue
                    if failing:
                        print("[screen] " + t("screen capture works again"))
                        failing = False
                    full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    # Before anything else: this tool's own panel is painted over, so the screen cannot be
                    # answered from the answer already on it, and a change there does not count as a new screen
                    found = window_rects(monitor)
                    if found is not None and found[1]:
                        full = hide_own(full, found[0], found[1])
                        if not hidden_said:
                            print("[screen] " + t("the panel is on this screen ({n} window(s)); its area is painted over before sending", n=len(found[1])))
                            hidden_said = True

                    # A problem read by scrolling arrives as several screens of the same thing. The
                    # reading below says when that is happening, and the stitcher is started by itself
                    # to join them, from the screen before the scroll so nothing scrolled past is lost.
                    #
                    # One grey plane for this poll: the scroll reading, the change signature and (while
                    # joining) the stitcher all read the screen through it, so a look converts it once.
                    look = gray_plane(full)
                    # With the automatic join switched off for the whole run nothing reads the row
                    # profile, and taking it anyway is most of what a look costs after the grab.
                    prof = None if auto_off else scroll_profile(look)
                    # Not across a slow wait: `slowed` still holds the last wait's decision here, so
                    # this skips the look that follows one. Rows that moved a whole second apart are
                    # not a scroll anyone can line up, and reading them as one would start a join
                    # from the wrong screen. The rate is already back to normal for the next look.
                    scrolled = 0 if (auto_off or slowed) else scroll_shift(prev_prof, prof)
                    prev_prof = prof
                    # Two polls in a row, in the same direction: one is as likely to be a line typed in
                    # an editor or a window dragged (both read as a shift of a few rows), and joining
                    # those sends the editor instead of the problem.
                    going = scrolled and last_scroll and (scrolled > 0) == (last_scroll > 0)
                    last_scroll = scrolled
                    if going and stitcher is None and not sender.wants["stitch"] and not args.once:
                        stitcher = ScrollStitcher(args.stable_polls, settle=args.settle)
                        auto_stitch, auto_idle = True, 0
                        print("[screen] " + t("the screen was scrolled ({n} rows): joining it into one problem", n=scrolled))
                        # The poll before this one holds what has just scrolled past; the last screen
                        # sent is the fallback. A frame of another size is from another monitor and
                        # would only raise inside the stitcher.
                        for earlier in (prev_full, last_full):
                            if earlier is not None and earlier.size == full.size:
                                stitcher.feed(earlier)
                                break
                    elif auto_stitch:
                        # The join is kept through a pause to read: dropping it after a few
                        # seconds meant the next scroll started a page from halfway down the problem.
                        # It ends when the screen has been still and unscrolled long enough that the
                        # person at the PC has moved on.
                        auto_idle = 0 if scrolled else auto_idle + 1
                        if auto_idle >= AUTO_STITCH_IDLE:
                            stitcher, auto_stitch = None, False
                            print("[screen] " + t("back to single screens"))
                            start_over()

                    if stitcher is not None:
                        # Stitch at full resolution: browsers scroll by whole physical pixels, so
                        # frames there are exact shifts; after a 4K->1600 downscale they are not
                        # (measured: the stitch fails on the downscaled frames). Shrink only for sending.
                        page = stitcher.feed(full, look)
                        if page is not None:
                            send_image(_fit(page[0], args.max_width), "stitch", monitor, [_fit(c, PAGE_MAX_W) for c in page[1]])
                            last_full = full
                            if args.once:      # asked for one screen: this is it, joined or not
                                print("[screen] " + t("one screen sent (--once)"))
                                stop.set()
                                break
                    else:
                        # The screen goes out as it is (up to --max-width): the server cuts the problem
                        # out of it at this resolution.
                        if gate.should_send(signature(look)):
                            send_image(_fit(full, args.max_width), "screen", monitor)
                            last_full = full
                            if args.once:      # one screen asked for: it is on its way, nothing stays running
                                print("[screen] " + t("one screen sent (--once)"))
                                stop.set()
                                break

                    prev_full = full   # the poll before the next one, for a join that starts then

                    # Following the changing screen (follow_watch): the monitor read through this poll's grab, its panel
                    # found above, and the others now and then. A scrolled problem being joined, by its own join or the
                    # panel's, holds the reading.
                    follow_watch(sct, shot, found, words, auto_stitch or (stitcher is not None and stitcher.joining()))

                    # What the looking costs, written to the log now and then. The loop is this
                    # program's whole expense and from the server's side it is invisible, so it is
                    # measured where it happens instead of from a probe beside it.
                    now = time.time()
                    looks.append((now - t0) * 1000)
                    if not look_t0:                       # first look: start the window here
                        look_t0, look_cpu0 = now, time.process_time()
                    elif now - look_t0 >= LOOK_REPORT_SEC:
                        mid = sorted(looks)[len(looks) // 2]
                        wall = now - look_t0
                        cpu = time.process_time() - look_cpu0
                        print(f"[screen] {len(looks)} looks in {wall:.0f} s, {mid:.0f} ms each (median); "
                              f"this program used {100 * cpu / wall:.0f}% of one core")
                        looks, look_t0, look_cpu0 = [], now, time.process_time()

                    # When to look again. `gate.stable` counts the settled looks in a row (each within
                    # --settle of the one before); the first look that moves more resets it, so the full
                    # rate comes back by itself and nothing has to decide when to wake up. Never while a
                    # scrolled problem is being joined: that needs every frame to line the pieces up.
                    slow = stitcher is None and gate.stable >= STILL_POLLS
                    if slow != slowed:
                        slowed = slow
                        print("[screen] " + (t("the screen has not changed for {n} looks: looking every {s} s until it does", n=STILL_POLLS, s=f"{STILL_PERIOD:g}")
                                             if slow else t("the screen changed: looking at every poll again")))
                    wait = max(period, STILL_PERIOD) if slow else period
                    dt = time.time() - t0
                    if dt < wait:
                        stop.wait(wait - dt)
        except Exception as exc:
            # A locked screen, a UAC prompt or a display change makes the grab fail. Retry with a
            # fresh grabber (monitors re-read): a loop that ended here would leave the capture
            # program running with no screen until restarted.
            if not failing:
                desk = input_desktop()
                if desk and desk != "Default":
                    print("[screen] " + t("the screen is locked, a UAC prompt is up or the screen saver is on (desktop {desk}): Windows lets "
                                          "no program capture it; capture resumes when it is back", desk=repr(desk)))
                else:
                    print("[screen] " + t("could not capture the screen ({error}); retrying every 2 s", error=f"{type(exc).__name__}: {exc}"))
                failing = True
            # Following had moved the reading off the chosen monitor: the next start of the block reads the chosen one
            # again and keeps nothing it had seen, which is said as a move is, in the log and to the panel (caps)
            if follow.following is not None:
                print("[screen] " + t("the capture failed: back to monitor {n}", n=follow.chosen))
                follow.reset()   # as that start does: said once, however many starts fail after it
            if follow.following != told_following:
                told_following = follow.following
                sender.set_caps(following=told_following)
            start_over()
            stop.wait(2.0)


SPEAKER_CHECK_SEC = 5.0   # how often the default speaker is checked while recording
# The sound device's own buffer, in seconds. soundcard asks WASAPI for one device period (about 10 ms) unless told,
# so the sound had to be read within that, and at times it was not: soundcard's "data discontinuity in recording",
# five at once as the 4K screen came back after the screen saver. Reads are a second long either
# way, so a larger buffer adds no delay; a second is what Microsoft's own capture sample asks for. (With half a
# second: 3 drops in the first minute after a start, none in the hour after with 18 frames of the 4K screen.)
# A second was not enough on a busy day: 44 of those warnings that day, up to 19 in one minute, every
# cluster of them at a moment this program was also encoding 4K screenshots and the GPU was answering. The read
# itself asks for a second of sound, so the only thing a larger device buffer changes is how far behind this
# program may fall before the device gives up holding sound for it. Two seconds and not more because WASAPI
# has its own ceiling on a shared-mode buffer and a recorder that will not open is worse than a dropped second.
AUDIO_BUFFER_SEC = 2.0
AUDIO_READ_SEC = 1.0       # sound taken from the device per read, and so the size of one chunk sent
AUDIO_GAP_NOTE_SEC = 60.0  # dropped sound is counted and said at most this often, not two lines each time
AUDIO_QUEUE_SEC = 8.0      # how much sound may wait to be sent before the oldest second of it is dropped


class _AudioGaps:
    """Counts soundcard's "data discontinuity in recording" warnings (sound the device dropped before it was
    read) instead of letting each one print two lines; other warnings print as before."""

    def __init__(self):
        self.count = 0
        self.lock = threading.Lock()
        self._show = warnings.showwarning
        warnings.filterwarnings("always", message="data discontinuity in recording")
        warnings.showwarning = self._showwarning

    def _showwarning(self, message, category, filename, lineno, file=None, line=None):
        if "data discontinuity in recording" in str(message):
            with self.lock:
                self.count += 1
            return
        self._show(message, category, filename, lineno, file, line)

    def take(self) -> int:
        with self.lock:
            n, self.count = self.count, 0
        return n


def audio_sender(sender: Sender, pending: "queue.Queue", stop: threading.Event) -> None:
    """Sends the sound the device thread read. The device has to be read on time or it drops what it recorded
    meanwhile, and a send waits for the socket and for the screen thread, which holds the same lock while it
    sends a frame: so nothing but this thread writes sound to the socket."""
    while not stop.is_set():
        try:
            sr, pcm = pending.get(timeout=0.5)
        except queue.Empty:
            continue
        sender.send({"type": "audio", "sr": sr, "data": base64.b64encode(pcm).decode()})


def audio_offer(pending: "queue.Queue", item: tuple) -> bool:
    """Puts one read on the queue, dropping the oldest second when the sender has fallen that far behind (the
    transcriber wants the sound that just played, not a backlog). True when nothing had to be dropped."""
    try:
        pending.put_nowait(item)
        return True
    except queue.Full:
        try:
            pending.get_nowait()
        except queue.Empty:
            pass
        try:
            pending.put_nowait(item)
        except queue.Full:
            pass
        return False


def _gap_line(n: int, late: float, step: float) -> str:
    """The line for the sound the device dropped in the last minute, with how far behind this program was then.

    soundcard's "data discontinuity in recording" is WASAPI saying that a packet does not follow on from the one
    before it: sound is missing, and nothing in it says who lost it. This line used to say "(this program fell
    behind reading it)" every time. Measured (scratch/audio_probe/): a recorder with this program's
    settings and nothing else to do, never more than 60 ms behind its 2 s buffer, got one all the same, with the
    device position jumping 40 ms ahead. So the claim is made only when this program measured itself behind.

    `late` is how far behind the device it was at worst (see audio_loop), `step` the longest stretch of its own
    work between two reads. Sound is lost by reading late only when the device's buffer fills, and a read takes
    at most AUDIO_READ_SEC of what is waiting before it returns, so a reader that lost sound that way comes back
    at least AUDIO_BUFFER_SEC - AUDIO_READ_SEC behind: under that, the sound went missing on Windows' side.

    Said in the program's language, the numbers as they are: what it says is why the sound went missing."""
    said = {"n": n, "sec": f"{AUDIO_GAP_NOTE_SEC:.0f}", "held": f"{AUDIO_BUFFER_SEC:g}"}   # in both of the lines below
    if late >= AUDIO_BUFFER_SEC - AUDIO_READ_SEC:   # far enough behind for the buffer to have filled
        return "[audio] " + t("the sound device dropped sound {n} time(s) in the last {sec} s; this program fell {late} s "
                              "behind reading it (the device holds {held} s; the longest step between two reads took {step} s)",
                              late=f"{late:.1f}", step=f"{step:.2f}", **said)
    # The buffer cannot have filled: the device, or the Windows audio engine, lost it before it was read.
    return "[audio] " + t("the sound device dropped sound {n} time(s) in the last {sec} s; this program was at most {late} s "
                          "behind reading it (the device holds {held} s), so it was not lost by reading late",
                          late=f"{late:.2f}", **said)


def _rise(lags: list) -> tuple:
    """The lowest of these lags (oldest first) and the most any of them rose above the lowest before it."""
    lo, rise = lags[0], 0.0
    for lag in lags:
        lo = min(lo, lag)            # a fall is not counted (see audio_loop)
        rise = max(rise, lag - lo)   # a rise is how far behind this program fell
    return lo, rise


def audio_loop(sender: Sender, stop: threading.Event, args) -> None:
    try:
        import soundcard as sc
    except Exception as exc:   # with the thread gone, the panel went on showing sound as on
        print("[audio] " + t("Could not load the sound library, going on without sound: {error}", error=exc))
        sender.set_caps(audio=False, audio_device="")
        return

    sr = 16000
    failing = False   # the device is missing or broke: said once, retried every 3 s
    gaps, noted = _AudioGaps(), time.time()
    # How far behind the device this program was in the minute being counted: the lowest its lag (below) has been
    # since the count began, the most it has risen above that, and the longest stretch of this loop's own work
    # between two reads.
    window = {"lo": 0.0, "late": 0.0, "step": 0.0}

    def say_gaps() -> None:
        """Says what the device dropped since this was last said, if anything, and starts the next count."""
        nonlocal noted
        noted = time.time()
        if n := gaps.take():
            print(_gap_line(n, window["late"], window["step"]))

    # How many chunks may wait to go out, counted in reads: one queued item is AUDIO_READ_SEC of
    # sound whatever the device's own buffer holds, and dividing by that buffer instead tied the
    # queue's depth to a number that has nothing to do with it.
    pending: queue.Queue = queue.Queue(maxsize=max(2, int(AUDIO_QUEUE_SEC / AUDIO_READ_SEC)))
    behind = 0        # reads dropped because the sending fell behind, said with the device's own drops
    threading.Thread(target=audio_sender, args=(sender, pending, stop), daemon=True).start()
    said_down = False  # "waiting for the server" is said once, not every two seconds
    while not stop.is_set():
        # Switched off in the panel, or nowhere to send it. The screen loop has always stopped
        # grabbing when there is no server; this one kept the sound device open and recorded into a
        # queue that was then thrown away, so a program left running after the server went down sat
        # there recording the speakers for nothing.
        if not sender.wants["audio"] or not sender.connected:
            while True:   # sound recorded before it stopped does not go out when it starts again
                try:
                    pending.get_nowait()
                except queue.Empty:
                    break
            if not sender.connected and not said_down:
                print("[audio] " + t("Not taking sound until the server is connected"))
                said_down = True
            sender.keepalive()
            stop.wait(DOWN_POLL if not sender.connected else 0.5)
            continue
        if said_down:
            print("[audio] " + t("Connected to the server again"))
            said_down = False
        try:
            # Looked up at every open, so headphones plugged in or a device that came back are
            # picked up. Loopback of the default speaker = whatever you hear.
            device = args.audio_device or (mac_loopback(sc) if sys.platform == "darwin" else "")
            speaker = None if device else str(sc.default_speaker().name)
            mic = sc.get_microphone(device or speaker, include_loopback=True)
            # The device is open only while sound capture is on: a recorder left open but unread
            # would hand back the sound from while it was off. channels=2 then downmix: WASAPI
            # loopback records garbage in mono.
            with mic.recorder(samplerate=sr, channels=2, blocksize=int(sr * AUDIO_BUFFER_SEC)) as rec:
                checked, recording = time.time(), False
                # The lag: the time since the device opened, less the sound read in that time. The device records
                # in real time and a read hands over what it has recorded, so this is how much sound waits in the
                # device each time a read comes back, plus whatever the device lost, which never comes back to be
                # read. Its rise above the lowest it had been before, in the minute, is how far behind this program
                # fell, read from the outside: it takes in a slow read, the work between reads and a thread kept
                # waiting. A fall is not counted: for a speaker nothing plays on, soundcard makes up silence by the
                # clock, and the sound that follows it can overlap it (this PC's recordings in
                # scratch/audio_probe/: the lag fell 30 to 90 ms each of the four times it did that, and rose by
                # 2 ms at most in any of the ten minutes).
                opened, frames, last = time.perf_counter(), 0, None
                recent: list = []   # the last few lags, which the next minute's count starts from
                while not stop.is_set() and sender.wants["audio"] and sender.connected:
                    if last is not None:   # this loop's own work since the last read came back
                        window["step"] = max(window["step"], time.perf_counter() - last)
                    data = rec.record(numframes=int(sr * AUDIO_READ_SEC))  # float32 (frames, 2)
                    last = time.perf_counter()
                    frames += len(data)
                    lag = (last - opened) - frames / sr
                    recent = (recent + [lag])[-3:]
                    if frames == len(data):   # the first read on this device: the count of its lag starts here
                        window.update(lo=lag, late=0.0, step=0.0)
                    window["lo"] = min(window["lo"], lag)                        # the lowest it has been
                    window["late"] = max(window["late"], lag - window["lo"])     # the most it rose above that
                    if time.time() - noted >= AUDIO_GAP_NOTE_SEC:
                        say_gaps()
                        if behind:   # in the program's language, as the line before it: it says who fell behind
                            print("[audio] " + t("{n} second(s) of sound was dropped on the way out in the last {sec} s "
                                                 "(the server or the network fell behind)",
                                                 n=behind, sec=f"{AUDIO_GAP_NOTE_SEC:.0f}"))
                            behind = 0
                        # The next minute starts from the last three reads, not from this one alone: a read that
                        # comes back late returns the oldest sound first, and the packet the device flagged after its
                        # loss is reached a read or two later, which can be in the next minute.
                        lo, late = _rise(recent)
                        window.update(lo=lo, late=late, step=0.0)
                    if not recording:   # only a device that really records counts as working
                        recording = True
                        if failing or sender.caps.get("audio") is not True or sender.caps.get("audio_device") != str(mic.name):
                            print("[audio] " + t("capturing loopback: {device}", device=mic.name))
                            sender.set_caps(audio=True, audio_device=str(mic.name))
                        failing = False
                    mono = data.mean(axis=1) if data.ndim == 2 else data
                    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                    behind += not audio_offer(pending, (sr, pcm))
                    if speaker is not None and time.time() - checked >= SPEAKER_CHECK_SEC:
                        checked = time.time()
                        if str(sc.default_speaker().name) != speaker:
                            print("[audio] " + t("the default speaker changed; switching to it"))
                            break
                # Sound switched off, the server gone or another speaker: what the device dropped since the last
                # line is said now, with the lag it was measured against. Left for later, it was said only once
                # sound was back, next to a lag measured on another stretch of recording.
                say_gaps()
        except Exception as exc:
            say_gaps()   # the same for a device that broke: its count belongs to the lag measured until now
            # Unplugged, disabled, or no speaker at all: the panel shows the sound device as not
            # open (caps), and capture picks up again once a device is there.
            if not failing:
                print("[audio] " + t("could not record from the sound device ({error}); retrying every 3 s", error=exc))
                sender.set_caps(audio=False, audio_device="")
                failing = True
            stop.wait(3.0)


# On macOS the sound library records inputs only, none of the speakers' sound. A loopback driver makes an input of it
# (BlackHole, free): the sound reaches it when the output is a Multi-Output Device of the speakers and BlackHole (Audio
# MIDI Setup). Asked again every 3 s, so one installed while this runs is picked up.
MAC_LOOPBACK = ("blackhole", "loopback", "soundflower")


def mac_loopback(sc) -> str:
    for m in sc.all_microphones():
        if any(w in str(m.name).lower() for w in MAC_LOOPBACK):
            return str(m.name)
    # said inside the line of a device that could not record, in the program's language as that line is
    raise RuntimeError(t("no loopback input on this Mac: install BlackHole (brew install blackhole-2ch), make a Multi-Output "
                         "Device of the speakers and BlackHole the output, or name an input with --audio-device"))


LOG_MAX_BYTES = 4_000_000   # one file, kept small enough to open: the launcher rotates it at start


class _Tee:
    """Writes to the log file, and to the console when there is one.

    The file has a limit: a windowless program runs for days, and the launcher only rotates the log
    when it starts one. Over the limit, the newest half is kept and the rest dropped."""

    def __init__(self, path, also):
        self.path = path
        try:
            if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
                _trim_log(path)
        except Exception:
            pass
        self.file = open(path, "a", encoding="utf-8", buffering=1)
        self.also = also
        self.written = 0

    def write(self, text: str) -> int:
        try:
            self.written += len(text)
            if self.written > 100_000:      # checked now and then, not on every line
                self.written = 0
                if os.path.getsize(self.path) > LOG_MAX_BYTES:
                    self.file.close()
                    _trim_log(self.path)
                    self.file = open(self.path, "a", encoding="utf-8", buffering=1)
            if text.strip():
                self.file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}" if not text.startswith("\r") else text)
            else:
                self.file.write(text)
        except Exception:
            pass
        if self.also is not None:
            try:
                self.also.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        for f in (self.file, self.also):
            try:
                if f is not None:
                    f.flush()
            except Exception:
                pass


class _Quiet:
    """A stream whose failures go nowhere. The console can be taken away under this program (the
    terminal is closed, the log file is replaced), and then an ordinary print raises OSError inside
    whichever thread was printing and ends it: the screen or the sound stops with no sign of why."""

    def __init__(self, stream):
        self._s = stream

    def write(self, text: str) -> int:
        try:
            if self._s is not None:
                self._s.write(text)
        except Exception:
            pass
        return len(text)

    def flush(self) -> None:
        try:
            if self._s is not None:
                self._s.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._s is not None and self._s.isatty())
        except Exception:
            return False


def _trim_log(path: str) -> None:
    """Keep the newest half of the file."""
    with open(path, "rb") as f:
        f.seek(-LOG_MAX_BYTES // 2, os.SEEK_END)
        f.readline()                         # start at a line boundary
        tail = f.read()
    with open(path, "wb") as f:
        f.write(b"[log] ... the older half of this file was dropped ...\n")
        f.write(tail)


def _log_to(path: str) -> None:
    """Everything this program prints goes to `path`. With no console at all (pythonw), sys.stdout is
    None, so a print would raise: the file takes its place rather than being added to it."""
    try:
        tee = _Tee(path, sys.stdout)
        sys.stdout = tee
        sys.stderr = _Tee(path, sys.stderr)
    except Exception as exc:
        if sys.stderr is not None:
            print("[main] " + t("could not open the log file {path}: {error}", path=path, error=exc), file=sys.stderr)


# ---------- tray icon ----------
# While this runs there is no window at all, so it is easy to forget and awkward to stop. The icon
# sits in the notification area with the panel one click away, and the right button ends it or
# starts it again. The name is what Windows shows on hover, so it matches the desktop shortcut.
TRAY_TITLE = "Sidenote Capture"


def server_up(url: str, timeout: float = 1.5) -> bool:
    """Does the server answer? Opening the panel without one lands on a browser error
    page that says nothing about this tool or what to do about it."""
    import urllib.request
    try:
        # No proxy: a manual Windows proxy is not bypassed for 127.0.0.1 (the registry's <local>
        # matches dotless names only), and the tray would say the server is off while it is up.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url.rstrip("/") + "/health", timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 400
    except Exception:
        return False


def panel_url(server: str) -> str:
    """The panel's address, from the ingest address the client was given."""
    url = re.sub(r"^ws", "http", server.strip())
    return re.sub(r"/ingest/?$", "/", url) or "http://127.0.0.1:8777/"


# The panel opens its Capture connection sheet at this address (panel/app.js, openCapture): the tray's item of that name
CONNECTION_QUERY = "?open=capture"


def pc_name() -> str:
    """This PC's name, as the system names it on its network: what tells one capture PC from another on the panel's
    Capture connection and in the notice when another one takes over. "" when the system does not say."""
    import platform
    name = platform.node() or os.environ.get("COMPUTERNAME", "")
    # a Mac adds the network's ".local" to its name: the name alone, as its own Sharing settings show it
    return re.sub(r"\.local$", "", name)[:64]


def system_name(platform_name: str = sys.platform) -> str:
    """The system this program runs on, in a few words: "Windows 11", "macOS 15.1", "Linux (X11)". Windows 11 still says
    release 10, so it is told by its build (22000 and later), as Windows itself does."""
    import platform
    if platform_name == "win32":
        try:
            version = sys.getwindowsversion()
            build, server = version.build, version.product_type != 1   # 1: a workstation; 2 and 3: a server
        except Exception:
            build, server = 0, False
        if server:   # Windows Server says release 10 too, and its builds are not the desktop's names
            return "Windows Server"
        return "Windows 11" if build >= 22000 else "Windows 10" if build >= 10240 else "Windows"
    if platform_name == "darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    if platform_name.startswith("linux"):
        session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
        # the session decides what can be read (X11 lists its windows, Wayland lists none): said beside the name
        return {"x11": "Linux (X11)", "wayland": "Linux (Wayland)"}.get(session, "Linux")
    return platform.system() or platform_name


def who_am_i(args) -> dict:
    """What this program says of itself in its hello, for the panel's Capture connection (server/app.py, capture_status):
    the PC and its system, this code's release, how it was started (the app, the desktop shortcut, a terminal's
    ./sidenote capture, or by hand), the server address it was given, and whether its Quit ends that server too (the
    session it brought up, server_down_command, or the app it belongs to)."""
    supervised = os.environ.get("SIDENOTE_SUPERVISED") == "1"
    return {"host": pc_name(), "system": system_name(), "version": VERSION,
            "started": "app" if supervised else (getattr(args, "started", "") or "own"),
            "server": args.server,
            "ends_server": supervised or bool(server_down_command(getattr(args, "stop_server_on_quit", "")))}


# ---------- staying on the code that is deployed ----------
def code_mark(path: str) -> str:
    """This program's code, as the first 12 hex digits of its file's sha256 ("" when it cannot be read). Sent in the
    hello: `./sidenote up` compares it with the file it deployed and asks for a restart when they differ."""
    import hashlib
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return ""


def source_error(path: str) -> str:
    """Why the file on disk would not run ("" when it compiles): a new file is not restarted into otherwise."""
    try:
        with open(path, encoding="utf-8") as f:
            compile(f.read(), path, "exec")
        return ""
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def server_quiet(url: str, now: float) -> bool:
    """Nothing at the server needs this program right now (server/app.py activity()): no analysis or follow-up
    running, nobody being listened to, no answer in the last minute. A server that does not answer, or an older one
    that does not say, counts as quiet: there is nothing a restart could cut short there."""
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # as server_up: no proxy
        with opener.open(url.rstrip("/") + "/health", timeout=3) as r:
            d = json.loads(r.read())
    except Exception:
        return True
    a = d.get("activity") or {}
    srv_now = (d.get("capture") or {}).get("now") or now
    return not a.get("busy") and not a.get("listening") and srv_now - (a.get("last_answer") or 0) > 60


UPDATE_QUIET = 20.0   # no screen sent for this long, and nothing going on at the server: the moment to restart
UPDATE_LOOK = 5.0     # seconds between looks for that moment


class Updater:
    """The restart a deploy asks for ({"type": "restart", "quiet": true}, sent by ./sidenote up when this program's
    code differs from the file it deployed), done the way the tray's Restart does it, at a quiet moment: the screen
    rested for UPDATE_QUIET seconds and the server quiet (server_quiet). After a fix to this file the program went on
    running the old code until it was restarted by hand. The deploy decides, not the file: this
    program runs the checkout's file, and watching it would restart into a change still being made. A file that does
    not compile is not restarted into, and the old code goes on."""

    def __init__(self, path: str, server: str, quiet: float = UPDATE_QUIET, every: float = UPDATE_LOOK):
        self.path, self.url = path, panel_url(server)
        self.quiet, self.every = quiet, every
        self.next_look = 0.0
        self.said = ""                   # the last thing said, not said again

    def _say(self, text: str) -> None:
        if text != self.said:
            print(f"[update] {text}")
            self.said = text

    def due(self, sender, now: float | None = None) -> bool:
        """True when a restart was asked for and the moment for it has come."""
        if not getattr(sender, "restart_pending", False):
            return False
        now = time.time() if now is None else now
        if now < self.next_look:
            return False
        self.next_look = now + self.every
        why = source_error(self.path)
        if why:
            self._say(t("Cannot read the new capture.py, going on with the code running now ({why})", why=why[:160]))
            sender.restart_pending = False
            return False
        if now - getattr(sender, "last_frame_ts", 0.0) < self.quiet or not server_quiet(self.url, now):
            self._say(t("Waiting for the screen and the server to be quiet, to restart into the new code."))
            return False
        self._say(t("Restarting into the new capture.py."))
        return True


# ---- the icon: desktop/build.py draws the app's icon from this block too, so the two stay one ----
INK = (26, 30, 40, 255)        # the panel's own ink
PAPER = (250, 250, 247, 255)
MARK = (232, 200, 64, 255)      # the highlighter
# The wordmark's S (Bricolage Grotesque at weight 800, the logo's), as its one outline on the icon's 64-point grid
S_OUTLINE = (
    (32.18, 49.7), (29.68, 49.59), (28.15, 49.39), (26.73, 49.09), (25.41, 48.69), (24.21, 48.2), (23.12, 47.63),
    (22.13, 46.96), (20.86, 45.81), (20.16, 44.94), (19.58, 44), (19.11, 42.98), (18.75, 41.88), (18.51, 40.73),
    (18.39, 39.52), (18.38, 38.25), (25.88, 36.6), (25.98, 37.7), (26.17, 38.68), (26.47, 39.56), (26.86, 40.33),
    (27.33, 40.99), (28.19, 41.81), (28.87, 42.24), (29.61, 42.58), (30.4, 42.84), (31.68, 43.06), (33.31, 43.08),
    (34.32, 42.95), (35.23, 42.73), (36.26, 42.27), (36.88, 41.84), (37.47, 41.14), (37.64, 40.74), (37.72, 40.32),
    (37.72, 39.81), (37.6, 39.26), (37.22, 38.54), (36.83, 38.12), (36.34, 37.75), (35.44, 37.24), (34.36, 36.8),
    (26.51, 34.38), (24.96, 33.78), (23.53, 33.08), (22.63, 32.55), (21.8, 31.96), (20.71, 30.92), (19.81, 29.7),
    (19.55, 29.25), (19.15, 28.27), (18.88, 27.18), (18.75, 25.99), (18.76, 24.56), (18.96, 23.08), (19.14, 22.39),
    (19.64, 21.08), (19.97, 20.48), (20.78, 19.35), (21.75, 18.36), (22.29, 17.92), (22.87, 17.51), (24.16, 16.79),
    (25.59, 16.2), (26.34, 15.96), (27.94, 15.59), (29.63, 15.37), (31.43, 15.3), (33.33, 15.38), (35.12, 15.63),
    (35.97, 15.82), (37.6, 16.31), (39.12, 16.98), (40.47, 17.79), (41.65, 18.76), (42.65, 19.88), (43.08, 20.5),
    (43.78, 21.85), (44.04, 22.57), (44.23, 23.34), (44.43, 24.97), (44.38, 26.75), (36.98, 27.95), (36.93, 26.54),
    (36.76, 25.59), (36.37, 24.49), (35.78, 23.56), (35.22, 22.97), (34.31, 22.36), (33.21, 21.94), (32.25, 21.76),
    (31.18, 21.7), (29.76, 21.8), (28.87, 22.01), (27.91, 22.44), (27.19, 23.03), (26.83, 23.56), (26.6, 24.15),
    (26.54, 25.06), (26.73, 25.76), (27.14, 26.37), (27.77, 26.89), (28.6, 27.36), (30.41, 28.04), (35.34, 29.48),
    (38.04, 30.36), (40.1, 31.26), (41.98, 32.38), (42.82, 33.05), (43.56, 33.81), (44.21, 34.65), (44.77, 35.58),
    (45, 36.09), (45.35, 37.2), (45.61, 39.1), (45.6, 40.61), (45.52, 41.38), (45.39, 42.12), (44.96, 43.5),
    (44.66, 44.13), (43.91, 45.3), (42.96, 46.33), (42.43, 46.8), (41.86, 47.23), (40.59, 47.98), (39.89, 48.31),
    (38.38, 48.86), (36.76, 49.27), (35.01, 49.55),
)


def tray_image(size: int = 256):
    """The icon: the wordmark's S over a highlighter stroke, on a sheet of paper, as the logo writes the name.

    Drawn four times larger and brought down with a good filter, because Windows asks for 16 and 20 points and a shape
    drawn at that size comes out ragged. The paper keeps the ink readable on a dark taskbar as on a light one."""
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = big / 64.0                                     # the 64-point grid, scaled up
    # Edge to edge: Windows shrinks the whole image to the tray's slot, so what is left blank round the sheet only made it small
    d.rounded_rectangle([0.5 * u, 0.5 * u, 63.5 * u, 63.5 * u], radius=15 * u, fill=PAPER, outline=INK, width=round(4 * u))
    # the stroke leans as the wordmark's does: 12 degrees, behind the lower half of the S
    lean = 0.2126                                      # tan(12 degrees)
    d.polygon([((x + 7 - lean * y) * u, y * u) for x, y in ((9, 34), (55, 34), (55, 49), (9, 49))], fill=MARK)
    d.polygon([(x * u, y * u) for x, y in S_OUTLINE], fill=INK)
    return img.resize((size, size), Image.LANCZOS)
# ---- end of the icon ----


# The tray's right-click menu, drawn in the panel's own look. A program of its own, run for as long as the menu is open:
# Tk in a thread of this one can bring the whole capture down when Python frees it from another thread, and a menu is not worth that. It gets the
# rows and the cursor as JSON and answers in its exit code, 100 + the row pressed, or 0 for none. Anything else means it could not run.
TRAY_MENU = r"""
import base64, ctypes, io, json, sys, time
from ctypes import wintypes
import tkinter as tk
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk

spec = json.loads(sys.argv[1])
rows, (cursor_x, cursor_y) = spec["rows"], spec["at"]
# The panel's dark Classic: its glass, its words, the highlighter, and its switch (green on, the capture's red off) and pills
BG, EDGE, TOP, INK, INK2, MUTED, DIM, HOVER, MARK = ("#26272b", "#4a4c53", "#8a8c93", "#e3e4e5", "#cbccce", "#b0b1b4", "#6f7177",
                                                     "#36373d", "#f2c744")
# The frosted glass, as the start window's (client/launch.pyw, Glass: tests/launch_window.py holds the two together): the
# blur in pixels at 100%, the glass's colour laid over what is behind, how far its colours are brought up again; and the
# face of a key, lighter under the pointer
BLUR, TINT, VIVID = 7, 0.8, 1.6
KEY_FACE, KEY_LIT = 18, 36
OK, LIT, BAD, TRACK_ON, TRACK_OFF, KNOB = "#2eb67d", "#4cc08e", "#ff6b6b", "#1a8a5a", "#4d2528", "#f1f1f3"
WARN = "#ffb066"                                            # the right column's warning in the dark Classic (Skipped window)
# The marks a row can wear, the panel's own: the screen and the sound as on its capture card, the turn as on its Reanalyze key.
# Each row names its mark ("mark"), and the state's row the colour of its pill ("tone"): the words are in either language and are never read
MARKS = ("open", "screen", "sound", "connect", "restart", "quit")
user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
parent = kernel32.OpenProcess(0x00100000, False, int(spec.get("parent") or 0))   # SYNCHRONIZE: to see the capture program end (watch)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)          # the cursor comes in screen pixels, so the window is placed in them
except Exception:
    pass
root = tk.Tk()
root.withdraw()                                             # nothing on screen until it is placed
root.title("sidenote menu")
scale = root.winfo_fpixels("1i") / 96.0                     # 1.0 at 100%, 2.0 at 200%
p = lambda n: round(n * scale)
SANS, HANGUL, MONO = "Segoe UI", "Malgun Gothic", "Consolas"   # Segoe UI has no Korean, and left to itself Windows picks a fallback of its own
WORDS = HANGUL if spec.get("lang") == "ko" else SANS        # the rows' font, for the language they are in
HEAD, SEP, ROW, STATE = p(50), p(11), p(38), p(38)


def tall(row):
    # A row's height: a rule, the state's pill, or an item (a switch the server is not there to keep is an item too, dimmed)
    return SEP if row["sep"] else STATE if not row["enabled"] and row["checked"] is None else ROW


tops, y = [], HEAD + p(4)                                   # where each row starts
for row in rows:
    tops.append(y)
    y += tall(row)
width, height = p(272), y + p(8)


class Monitor(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("whole", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


# Up and to the left of the cursor as a tray menu is, inside the screen it was opened on and off the taskbar
info = Monitor(size=ctypes.sizeof(Monitor))
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(Monitor))
screen = user32.MonitorFromPoint(wintypes.POINT(cursor_x, cursor_y), 2)
left, top, right, bottom = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
if screen and user32.GetMonitorInfoW(screen, ctypes.byref(info)):
    left, top, right, bottom = info.work.left, info.work.top, info.work.right, info.work.bottom
x = max(left, min(cursor_x, right) - width)
y = max(top, min(cursor_y, bottom) - height - p(6))
root.overrideredirect(True)                                 # no title bar
root.attributes("-topmost", True)                           # opaque: its glass is drawn over what is behind it (glass)
root.geometry(f"{width}x{height}+{x}+{y}")


def grab():
    # What the screen shows where the menu is to stand and a little round it, read once before it is shown, on whichever
    # screen it opens (all of them, in the screens' own coordinates): its glass is drawn over it, frosted as the start
    # window's is (client/launch.pyw, Glass.frost). None where the screen cannot be read: the glass is then its own colour
    try:
        from PIL import ImageGrab
        margin = p(BLUR * 3)                                # past three times the blur, what is there no longer counts
        box = (max(whole[0], x - margin), max(whole[1], y - margin), min(whole[2], x + width + margin), min(whole[3], y + height + margin))
        shot = ImageGrab.grab(bbox=box, all_screens=True)
        if shot.size != (box[2] - box[0], box[3] - box[1]):
            return None
        return shot.convert("RGB").filter(ImageFilter.GaussianBlur(p(BLUR))).crop((x - box[0], y - box[1], x - box[0] + width, y - box[1] + height))
    except Exception:
        return None


whole = (left, top, right, bottom)
if screen and user32.GetMonitorInfoW(screen, ctypes.byref(info)):
    whole = (info.whole.left, info.whole.top, info.whole.right, info.whole.bottom)   # the whole screen, the taskbar's part too
behind = grab()
glass = Image.new("RGB", (width, height), BG)
if behind is not None:                                      # tinted 80% with the glass's colour, its colours brought up 1.6 times
    glass = ImageEnhance.Color(Image.blend(behind, Image.new("RGB", behind.size, BG), TINT)).enhance(VIVID)
grain = Image.effect_noise((width, height), 26).convert("RGB")   # a fine grain, as frosted glass has: a pixel a grain
glass = Image.blend(glass, grain, 0.03)
logo = None
try:                                                        # the capture's logo, with where its baseline and its letters start
    with Image.open(spec.get("logo") or "") as found:
        found.load()
        logo = (found.convert("RGBA"), int(found.text.get("baseline", "0")) or round(found.height * 0.7), int(found.text.get("left", "0")))
except Exception:
    pass
c = tk.Canvas(root, width=width, height=height, bg=BG, highlightthickness=0, bd=0)
c.pack()
hover = [None]                                              # the row under the pointer or the keys
started = time.monotonic()
was_front = [False]


def choices():
    return [i for i, row in enumerate(rows) if not row["sep"] and row["enabled"]]


SS = 3                                                      # drawn three times over and brought down: Tk draws its shapes unsmoothed on Windows
TONE = {"on": LIT, "idle": MUTED, "down": BAD, "warn": WARN}   # the state's pill, as the panel's "● 받는 중": its dot and words


def mix(a, b, t):
    # Colour a laid over colour b at strength t
    a, b = [int(a[k:k + 2], 16) for k in (1, 3, 5)], [int(b[k:k + 2], 16) for k in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(u * t + v * (1 - t)) for u, v in zip(a, b))


PILL = {"on": mix(OK, BG, 0.16), "idle": mix(MUTED, BG, 0.1), "down": mix(BAD, BG, 0.14), "warn": mix(WARN, BG, 0.16)}
images = []                                                 # Tk forgets a picture nothing holds on to


def icon(d, kind, x, mid, colour, under):
    # A row's mark on the panel's 24-unit grid, p(17) across, its left edge at x and its middle at mid
    k = p(17) * SS / 24
    ox, oy = x * SS, mid * SS - 12 * k
    at = lambda u, v: (ox + u * k, oy + v * k)
    w = max(1, round(1.7 * k))                              # the panel's stroke, 1.7 of 24

    def line(*pts):
        d.line([at(*q) for q in pts], fill=colour, width=w, joint="curve")
        for q in (pts[0], pts[-1]):                         # round ends, as the panel's
            cx, cy = at(*q)
            d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=colour)

    if kind == "screen":                                    # a screen on its stand
        d.rounded_rectangle([at(2.5, 4), at(21.5, 17)], radius=2 * k, outline=colour, width=w)
        line((9, 20.5), (15, 20.5))
        line((12, 17), (12, 20.5))
    elif kind == "sound":                                   # the sound's bars
        for u, a, b in ((4, 11, 13), (8, 7.5, 16.5), (12, 4.5, 19.5), (16, 8.5, 15.5), (20, 10.5, 13.5)):
            line((u, a), (u, b))
    elif kind == "restart":                                 # the turn of Reanalyze
        d.arc([at(4, 4), at(20, 20)], 0, 315, fill=colour, width=w)
        line((20, 4), (20, 9), (15, 9))
    elif kind == "connect":                                 # a plug, as on the panel's Capture connection (lucide's plug)
        line((9, 2.5), (9, 8))
        line((15, 2.5), (15, 8))
        line((6, 8), (18, 8))
        line((6, 8), (6, 13))
        line((18, 8), (18, 13))
        d.arc([at(6, 9), at(14, 17)], 90, 180, fill=colour, width=w)    # the body's two round corners, radius 4
        d.arc([at(10, 9), at(18, 17)], 0, 90, fill=colour, width=w)
        line((10, 17), (14, 17))
        line((12, 17), (12, 21.5))                          # the lead
    elif kind == "quit":                                    # the power mark
        d.arc([at(3, 4), at(21, 22)], 315, 225, fill=colour, width=w)
        line((12, 2.5), (12, 11))
    elif kind == "open":                                    # a box with the arrow out of its corner
        d.rounded_rectangle([at(3, 6), at(18, 21)], radius=2 * k, outline=colour, width=w)
        d.rectangle([at(10.5, 2), at(22, 13.5)], fill=under)   # the box open where the arrow leaves it
        line((10, 14), (20.5, 3.5))
        line((14.5, 3.5), (20.5, 3.5), (20.5, 9.5))


def switch(d, x1, mid, on, enabled):
    # The panel's switch: green with the knob to the right, or the capture's red with it to the left; dimmed when it cannot be pressed
    h, w = p(18) * SS, p(34) * SS
    x1, mid = x1 * SS, mid * SS
    x0 = x1 - w
    track, rim = (TRACK_ON, mix("#78f0be", TRACK_ON, 0.4)) if on else (TRACK_OFF, mix(BAD, TRACK_OFF, 0.25))
    if not enabled:
        track, rim = mix(track, BG, 0.45), mix(rim, BG, 0.45)
    d.rounded_rectangle([x0, mid - h / 2, x1, mid + h / 2], radius=h / 2, fill=track, outline=rim, width=SS)
    knob = h - 6 * SS
    kx = x1 - 3 * SS - knob if on else x0 + 3 * SS
    d.ellipse([kx, mid - knob / 2, kx + knob, mid + knob / 2], fill=KNOB if enabled else mix(KNOB, BG, 0.5))   # flat, as the panel's


def lamp(d, cx, cy, colour):
    # The panel's status light: a dot of the colour, lighter at its middle, its glow round it
    r, g, b = (int(colour[k:k + 2], 16) for k in (1, 3, 5))
    for radius, alpha in ((p(5), 16), (p(4), 30), (p(3.2), 56)):
        d.ellipse([(cx - radius) * SS, (cy - radius) * SS, (cx + radius) * SS, (cy + radius) * SS], fill=(r, g, b, alpha))
    d.ellipse([(cx - p(2.5)) * SS, (cy - p(2.5)) * SS, (cx + p(2.5)) * SS, (cy + p(2.5)) * SS], fill=colour)
    d.ellipse([(cx - p(1)) * SS, (cy - p(1)) * SS, (cx + p(1)) * SS, (cy + p(1)) * SS], fill=mix("#ffffff", colour, 0.5))


base = []                                                   # the glass three times over with the logo on it, made once: the same for every row


def shapes(title, pills, tag):
    # Everything but the words, smooth: the frosted glass and its edges, the logo, the release's tag, the hairlines, the key,
    # the row under the pointer, the state's pill with its light, the marks and the switches. One picture under the words,
    # drawn again for each row the pointer or the keys come to: what does not change with the row is made once (base), and
    # the picture goes to Tk as it is. Made whole each time and passed as a PNG, a row took 118 ms at 200%
    d_w, d_h = width * SS, height * SS
    S = lambda v: v * SS
    pad = p(14)
    if not base:
        first = glass.resize((d_w, d_h), Image.BICUBIC)
        if logo is not None and title is None:              # the logo, brought down from its own four times
            lx, ly, lw, lh = logo_at
            big = logo[0].resize((round(lw * SS), round(lh * SS)), Image.LANCZOS)
            first.paste(big.convert("RGB"), (round(lx * SS), round(ly * SS)), big.getchannel("A"))
        base.append(first)
    im = base[0].copy()
    d = ImageDraw.Draw(im, "RGBA")                          # a colour with an alpha is laid over the glass
    if title is not None:                                   # no logo: the highlighter under the written name, as on the panel's bar
        x0, _, x1, y1 = title
        d.polygon([(S(x0 - p(1)), S(y1 - p(4))), (S(x1 + p(3)), S(y1 - p(5))), (S(x1 + p(1)), S(y1 - p(1))), (S(x0 - p(3)), S(y1))], fill=MARK)
    if tag is not None:                                     # the release's tag: a fine line round it, square as the panel's
        d.rectangle([S(tag[0]), S(tag[1]), S(tag[2]) - 1, S(tag[3]) - 1], outline=(255, 255, 255, 44), width=SS)
    d.rectangle([0, 0, d_w - 1, d_h - 1], outline=EDGE, width=SS)                 # the glass's edge
    d.line([(SS, SS // 2), (d_w - SS, SS // 2)], fill=TOP, width=SS)             # its lit top
    d.line([(S(pad), S(HEAD)), (S(width - pad), S(HEAD))], fill=(255, 255, 255, 24), width=SS)   # a hairline under the logo
    for i, row in enumerate(rows):
        y0, h = tops[i], tall(row)
        if row["sep"]:
            d.line([(S(pad), S(y0 + h // 2)), (S(width - pad), S(y0 + h // 2))], fill=(255, 255, 255, 24), width=SS)
            continue
        mid, under = y0 + h / 2, BG
        if row["default"]:                                  # the menu's first word, Open the panel: a key, flat, its face lighter under the pointer
            d.rounded_rectangle([S(p(8)), S(y0 + p(3)), S(width - p(8)), S(y0 + h - p(3))], radius=S(p(4)),
                                fill=(255, 255, 255, KEY_LIT if hover[0] == i else KEY_FACE), outline=(255, 255, 255, 46), width=SS)
            under = HOVER
        elif hover[0] == i:                                 # the row under the pointer or the keys, rounded as the panel's
            under = HOVER
            d.rounded_rectangle([S(p(8)), S(y0 + p(2)), S(width - p(8)), S(y0 + h - p(2))], radius=S(p(4)), fill=(255, 255, 255, 22))
        if i in pills:                                      # the state: the panel's pill with its light, dark whatever the glass shows
            t, (_, _, bx1, _) = pills[i]
            d.rounded_rectangle([S(pad), S(mid - p(12)), S(bx1 + p(11)), S(mid + p(12))], radius=S(p(12)), fill=PILL[t])
            lamp(d, pad + p(11), mid, TONE[t])
            continue
        kind = row.get("mark")
        if kind in MARKS:                                   # a switch's mark is lit while it is on, as on the panel's capture card
            colour = INK2 if row["checked"] is None else OK if row["checked"] else MUTED
            icon(d, kind, pad, mid, colour if row["enabled"] else DIM, under)
        if row["checked"] is not None:
            switch(d, width - pad, mid, row["checked"], row["enabled"])
    images[:] = [ImageTk.PhotoImage(im.resize((width, height), Image.LANCZOS), master=root)]   # the menu's own Tk, whatever else runs here
    return images[0]


logo_at = None                                              # where the logo stands: left, top, width, height
fonts = []                                                  # the tag's font, held


def draw():
    global logo_at
    c.delete("all")
    pad = p(14)
    # The words first, where they stand, so the picture under them knows where they are. The logo is in the picture, its
    # letters on the margin and its baseline in the head's middle; with no logo the name is written, as before
    if logo is not None:
        picture, line, start = logo
        lw, lh = picture.width * scale / 4, picture.height * scale / 4
        lx, ly = pad - start * scale / 4, HEAD / 2 + p(4) - line * scale / 4
        logo_at, name, right = (lx, ly, lw, lh), None, lx + lw
        baseline = ly + line * scale / 4
    else:
        title = c.create_text(pad, HEAD // 2, anchor="w", text="sidenote", fill=INK, font=(SANS, 11, "bold"))
        name = c.bbox(title)
        word = c.create_text(name[2] + p(9), HEAD // 2 + p(1), anchor="w", text="capture", fill=INK, font=(SANS, 9))
        right, baseline = c.bbox(word)[2], c.bbox(word)[3] - p(3)
    tag = None
    if spec.get("version"):                                 # the release beside the logo, in the panel's tag, on its baseline
        import tkinter.font
        mono = tkinter.font.Font(root=root, family=MONO, size=8)
        fonts[:] = [mono]                                   # a font nothing holds on to goes, and its words with it
        word = c.create_text(right + p(6), baseline - mono.metrics("ascent"), anchor="nw", text="v" + spec["version"], fill=INK2, font=mono)
        x0, y0, x1, y1 = c.bbox(word)
        tag = (x0 - p(5), y0 - p(2), x1 + p(5), y1 + p(2))
    pills = {}
    for i, row in enumerate(rows):
        if row["sep"]:
            continue
        mid = tops[i] + tall(row) // 2
        if not row["enabled"] and row["checked"] is None:   # the state's words, in its pill's colour
            t = row.get("tone") if row.get("tone") in TONE else "on"
            pills[i] = (t, c.bbox(c.create_text(pad + p(20), mid, anchor="w", text=row["text"], fill=TONE[t], font=(WORDS, 9))))
            continue
        x = pad + p(17) + p(11) if row.get("mark") in MARKS else pad
        c.create_text(x, mid, anchor="w", text=row["text"], fill=INK if row["enabled"] else DIM,
                      font=(WORDS, 10, "bold" if row["default"] else "normal"))
    c.tag_lower(c.create_image(0, 0, anchor="nw", image=shapes(name, pills, tag)))


def row_at(py):
    for i, row in enumerate(rows):
        if tops[i] <= py < tops[i] + tall(row) and i in choices():
            return i
    return None


def on_move(e):
    at = row_at(e.y)
    if at != hover[0]:
        hover[0] = at
        draw()


def clear(_e=None):
    hover[0] = None
    draw()


def finish(code):
    root.destroy()
    sys.exit(code)


def press(_e=None):
    if hover[0] is not None:
        finish(100 + hover[0])


def step(by):
    keys = choices()
    if keys:
        hover[0] = keys[(keys.index(hover[0]) + by) % len(keys)] if hover[0] in keys else keys[0 if by > 0 else -1]
        draw()


# Closed by a click anywhere else, as a menu is: the window in front has changed. And not left open for ever
def watch():
    front = user32.GetForegroundWindow() == hwnd
    was_front[0] = was_front[0] or front
    waited = time.monotonic() - started
    # Windows may refuse the front of the screen, and a pointer already on the menu has not left it: only a pointer elsewhere closes one that never got it
    x, y = root.winfo_pointerxy()
    over = root.winfo_rootx() <= x < root.winfo_rootx() + root.winfo_width() and root.winfo_rooty() <= y < root.winfo_rooty() + root.winfo_height()
    if (not front and (was_front[0] or (waited > 1.5 and not over))) or waited > 60:
        finish(0)
    # The program this menu belongs to has gone, however it went (Quit, a restart to update, a stop from outside): a press here would reach nothing
    if parent and kernel32.WaitForSingleObject(parent, 0) == 0:
        finish(0)
    root.after(120, watch)


c.bind("<Motion>", on_move)
c.bind("<Leave>", clear)
c.bind("<ButtonRelease-1>", lambda e: (on_move(e), press()))
root.bind("<Escape>", lambda _e: finish(0))
root.bind("<Up>", lambda _e: step(-1))
root.bind("<Down>", lambda _e: step(1))
root.bind("<Return>", press)
draw()
root.update_idletasks()
root.attributes("-alpha", 0.0)                              # in from clear, as the start's window comes (fade below)
root.deiconify()
root.update()


def fade(k=0):
    # Clear to opaque over a tenth of a second, quick at first: a menu answers the click at once. Opaque at the end (alpha 1,
    # no longer layered), its glass drawn
    try:
        root.attributes("-alpha", 1 - (1 - (k + 1) / 6) ** 2)
    except Exception:
        return
    if k < 5:
        root.after(16, lambda: fade(k + 1))


fade()
hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
try:
    style = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, style | 0x80)          # WS_EX_TOOLWINDOW: no button on the taskbar
    corner = ctypes.c_int(3)                                # DWMWCP_ROUNDSMALL: this design is nearly square
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
    edge = ctypes.c_uint(int(EDGE[1:3], 16) | int(EDGE[3:5], 16) << 8 | int(EDGE[5:7], 16) << 16)   # DWMWA_BORDER_COLOR, 0x00BBGGRR
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(edge), ctypes.sizeof(edge))
    get = getattr(user32, "GetClassLongPtrW", user32.GetClassLongW)   # a shadow under it, as the start window has (CS_DROPSHADOW)
    put = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
    put(hwnd, -26, get(hwnd, -26) | 0x00020000)
except Exception:
    pass
user32.SetForegroundWindow(hwnd)
root.focus_force()
watch()
root.mainloop()
"""


def marked(item, mark: str | None = None, tone=None):
    """A menu item with what the drawn menu needs besides its words: the mark it wears (one of TRAY_MENU's MARKS), or for
    the state's row the colour of its pill ("on", "idle", "down", "warn"; a function of the item as pystray's values may be)."""
    item.sidenote_mark, item.sidenote_tone = mark, tone
    return item


def tray_rows(menu) -> list:
    """The menu as it stands now, as the drawn menu shows it. pystray's items answer these as properties, and a value may be a function of the item."""
    def now(item, value):
        return value(item) if callable(value) else value
    rows = []
    for item in menu.items:
        if not now(item, getattr(item, "visible", True)):
            continue
        text = now(item, item.text)
        if str(text).startswith("- -"):                     # pystray's separator
            rows.append({"sep": True, "text": "", "enabled": False, "checked": None, "default": False, "mark": None, "tone": None,
                         "item": item})
            continue
        checked = now(item, getattr(item, "checked", None))
        rows.append({"sep": False, "text": str(text), "enabled": bool(now(item, getattr(item, "enabled", True))),
                     "checked": None if checked is None else bool(checked), "default": bool(getattr(item, "default", False)),
                     "mark": getattr(item, "sidenote_mark", None), "tone": now(item, getattr(item, "sidenote_tone", None)),
                     "item": item})
    return rows


def tray_rows_checked(item):
    """Whether a menu item is checked as it stands now."""
    value = getattr(item, "checked", None)
    value = value(item) if callable(value) else value
    return None if value is None else bool(value)


def own_tray_menu(icon) -> bool:
    """Show the drawn menu on a right click rather than Windows' own. Windows' stays behind it: for a Python without tkinter, a pystray that has
    changed, or a menu program that could not run."""
    import subprocess
    handlers, native = getattr(icon, "_message_handlers", None), getattr(icon, "_on_notify", None)
    if not handlers or native is None:
        return False
    keys = [k for k, handler in handlers.items() if handler == native]
    if not keys:
        return False
    # With no console of its own: a window would flash up for every right click
    folder, name = os.path.split(sys.executable)
    quiet = os.path.join(folder, "pythonw.exe")
    python = quiet if os.path.exists(quiet) else sys.executable
    state = {"proc": None, "closed": set(), "broken": False, "failed": 0}

    def wait_for(proc, rows):
        try:
            code = proc.wait(timeout=70)     # the menu closes itself within 60 s: one that has not has hung
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
        if state["proc"] is proc:
            state["proc"] = None
        if proc in state["closed"]:          # a second right click closed it, which is no failure of its own
            state["closed"].discard(proc)
            return
        if code >= 100 and code - 100 < len(rows):
            state["failed"] = 0
            row = rows[code - 100]
            # A switch pressed as it was drawn: changed elsewhere while the menu stood open (the panel), it already is what the press asked for
            if row["checked"] is not None and tray_rows_checked(row["item"]) != row["checked"]:
                return
            try:
                row["item"](icon)
            except Exception as exc:     # as a menu action failing in pystray: said, and the capture goes on
                print("[tray] " + t("A menu action failed ({error})", error=f"{type(exc).__name__}: {exc}"))
        elif code == 0:
            state["failed"] = 0
        else:                            # could not run: Windows' own menu after the second time in a row (one killed from outside is no reason)
            state["failed"] += 1
            print("[tray] " + t("Could not show the tray menu (exit code {code}, {n} in a row)", code=code, n=state["failed"]))
            if state["failed"] >= 2:
                state["broken"] = True
                print("[tray] " + t("Using the Windows menu from now on"))

    def on_notify(wparam, lparam):
        if lparam != 0x0205 or state["broken"]:      # WM_RBUTTONUP: all else, and a menu that cannot run, is pystray's as before
            return native(wparam, lparam)
        try:
            import ctypes
            import json
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            if state["proc"] is not None and state["proc"].poll() is None:
                state["closed"].add(state["proc"])
                state["proc"].kill()                 # a second right click starts over, as Windows' own menu does
            at = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(at))
            rows = tray_rows(icon.menu)
            shown = [{k: r[k] for k in ("sep", "text", "enabled", "checked", "default", "mark", "tone")} for r in rows]
            user32.SetForegroundWindow(icon._hwnd)   # this click is what lets this program hand the front of the screen to the menu
            proc = subprocess.Popen([python, "-c", TRAY_MENU, json.dumps({"rows": shown, "at": [at.x, at.y], "parent": os.getpid(), "lang": LANG,
                                                                          "version": VERSION, "logo": LOGO})],
                                    creationflags=subprocess.CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            user32.AllowSetForegroundWindow(proc.pid)
            state["proc"] = proc
            threading.Thread(target=wait_for, args=(proc, rows), daemon=True).start()
            return 0
        except Exception as exc:
            state["broken"] = True
            print("[tray] " + t("Could not show the tray menu, using the Windows menu ({error})", error=f"{type(exc).__name__}: {exc}"))
            return native(wparam, lparam)

    for key in keys:
        handlers[key] = on_notify
    return True


def dark_menus() -> None:
    """Windows' own menu, for when the drawn one cannot run, in its dark style. An undocumented pair of calls (uxtheme ordinals
    135 and 136, SetPreferredAppMode and FlushMenuThemes) that every dark-menu program uses; without them the menu is simply light."""
    try:
        import ctypes
        theme = ctypes.WinDLL("uxtheme")
        theme[135](2)    # ForceDark
        theme[136]()
    except Exception:    # not Windows, or a Windows before these
        pass


# macOS: the class that answers Sidenote.app being opened again (answer_reopen), and what it calls. The class is made
# once, as AppKit refuses a second class of the same name; one tray per process sets what it calls.
_REOPEN = {"class": None, "answer": None}


def answer_reopen(answer):
    """macOS: Sidenote.app opened again while it runs starts no second copy. The system asks the copy that runs to
    reopen instead, and it asks this program, the one with the AppKit loop and the menu bar icon: the app's first
    process runs no AppKit loop, so to the system this one is the app, for a quit as well (measured on macOS 15). The
    answer is `answer()`, the panel, as a second start gives on Windows and Linux. Returns the delegate for the
    caller to keep, as AppKit holds it weakly; None where there is no AppKit."""
    try:
        import AppKit
        import Foundation
        import objc
    except Exception:
        return None
    _REOPEN["answer"] = answer
    if _REOPEN["class"] is None:
        class SidenoteReopen(Foundation.NSObject):
            # BOOL (NSApplication *, BOOL), spelled out: a BOOL taken for an object would be read as an address
            @objc.typedSelector(b"Z@:@Z")
            def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
                print("[tray] " + t("Sidenote was opened again: opening the panel"))
                # off AppKit's thread: the look at the server waits on it, and the menu would wait with it
                threading.Thread(target=_REOPEN["answer"], name="reopen", daemon=True).start()
                return False   # nothing left for AppKit to do: it has no window of its own to bring back
        _REOPEN["class"] = SidenoteReopen
    delegate = _REOPEN["class"].alloc().init()
    AppKit.NSApplication.sharedApplication().setDelegate_(delegate)
    return delegate


def start_tray(sender, stop: threading.Event, args):
    """The notification area icon, or None where it cannot run (no pystray, no desktop session)."""
    try:
        import pystray
    except Exception as exc:
        print("[tray] " + t("No tray icon ({error}). To install it: ./sidenote setup-capture", error=type(exc).__name__))
        return None

    url = panel_url(args.server)

    def open_panel(icon=None, _item=None):
        import webbrowser
        if not server_up(url):
            # under the desktop app, which runs the server itself, there is no ./sidenote to run
            msg = (t("Sidenote is not running. Start the Sidenote app again.") if os.environ.get("SIDENOTE_SUPERVISED") == "1"
                   else t("The Sidenote server is off. Run ./sidenote up in the server's terminal."))
            print(f"[tray] {msg}")
            try:
                if icon is not None:
                    icon.notify(msg, TRAY_TITLE)   # a browser error page says nothing about this
                    return
            except Exception:
                pass
        webbrowser.open(url)

    def open_connection(icon=None, _item=None):
        """The panel's Capture connection (panel/app.js, openCapture): this program, the PC it runs on, the server it sends to
        and how to start, restart or end it, as the server sees them. As Open the panel when the server is off."""
        import webbrowser
        if not server_up(url):
            open_panel(icon)   # says why there is no panel, and opens nothing more
            return
        webbrowser.open(url + CONNECTION_QUERY)

    def quit_now(icon, _item=None):
        print("[tray] " + t("Quit from the tray."))
        sender.quit_by_person = True   # read at the end of main: a server this start brought up goes with it
        stop.set()
        icon.stop()

    def restart(icon, _item=None):
        print("[tray] " + t("Restarting from the tray."))
        sender.restart_asked = True
        stop.set()
        icon.stop()

    def state_line(_item=None):
        return state_text()

    def taking() -> list:
        """What is being taken now, in the menu's words: the sound only while a device for it is open as well, which caps
        says (audio False: the sound library or the device failed, the panel's card says Device error), the switch on or not."""
        on = []
        if sender.wants.get("screen"):
            on.append(t("Screen"))
        if (sender.wants.get("audio", True) and not args.no_audio            # the panel's key is "audio"
                and getattr(sender, "caps", {}).get("audio") is not False):   # a program that says nothing of it: as before
            on.append(t("Sound"))
        return on

    def skipped() -> bool:
        """A window of Skip windows is on screen, so no screen goes out (the screen loop says so in caps)."""
        return bool(sender.wants.get("screen")) and bool(getattr(sender, "caps", {}).get("skipping"))

    def state_text(_item=None):
        if not sender.connected:
            # started by the desktop app, which starts the server itself: there is no ./sidenote to run
            return t("Not connected") if os.environ.get("SIDENOTE_SUPERVISED") == "1" else t("Not connected (./sidenote up)")
        if skipped():                   # said as the panel's capture card says it, without naming the window
            return t("Skipped window")
        on = taking()
        return t("Capturing: {what}", what=" · ".join(on) if on else t("nothing"))

    def state_tone(_item=None):
        """The colour of the state's pill in the drawn menu, from the state itself: no server, a window skipped, nothing
        taken, or taking."""
        return "down" if not sender.connected else "warn" if skipped() else "on" if taking() else "idle"

    def toggle(which):
        def go(icon=None, _item=None):
            # The same switch as the panel's (`capture_set`): the server keeps the switches, tells the panels and
            # sends them back here as `control`, so all three agree. This used to flip only this program's copy,
            # put "the sound device did not open" in caps (which is what `audio` there means) and send a message
            # the server had no use for: the panel kept showing the old state, and the next control message from
            # anywhere put it back.
            want = not sender.wants.get(which, True)
            sender.wants[which] = want   # at once here too, so the loops stop or start without waiting for the reply
            # Off the tray's thread: a send to a stalled server waits, and the whole menu, Quit included, would wait with it
            threading.Thread(target=sender.send, args=({"type": "capture_set", which: want},), daemon=True).start()
        return go

    # The menu is drawn by Windows, so what can be made good here is what it says and in what order:
    # what it is doing first, the two switches that matter, then the two ways out.
    menu = pystray.Menu(
        marked(pystray.MenuItem(t("Open the panel"), open_panel, default=True), "open"),
        marked(pystray.MenuItem(state_text, None, enabled=False), tone=state_tone),
        pystray.Menu.SEPARATOR,
        # Only while the server is there to keep them: flipped with nobody connected, the switch would be undone
        # by the server's own switches the moment this program connects again.
        marked(pystray.MenuItem(t("Screen capture"), toggle("screen"), checked=lambda _i: bool(sender.wants.get("screen")),
                                enabled=lambda _i: sender.connected), "screen"),
        marked(pystray.MenuItem(t("Sound capture"), toggle("audio"),
                                checked=lambda _i: bool(sender.wants.get("audio")) and not args.no_audio,
                                enabled=lambda _i: sender.connected and not args.no_audio), "sound"),
        pystray.Menu.SEPARATOR,
        # this program as the server sees it, and the way to start, restart or end it: the panel's sheet of that name
        marked(pystray.MenuItem(t("Capture connection"), open_connection), "connect"),
        marked(pystray.MenuItem(t("Restart capture"), restart), "restart"),
        # under the desktop app quitting the capture program ends the whole app (desktop/app.py), and after a start that
        # brought the server up it ends that server too (--stop-server-on-quit): both say so
        marked(pystray.MenuItem(t("Quit Sidenote") if os.environ.get("SIDENOTE_SUPERVISED") == "1"
                                or server_down_command(getattr(args, "stop_server_on_quit", "")) else t("Quit"), quit_now),
               "quit"),
    )
    failed = threading.Event()

    def run_icon() -> None:
        try:
            icon.run()
        except Exception as exc:    # a desktop session that will not have it: the capture goes on
            failed.set()
            print("[tray] " + t("Could not show the tray icon ({error})", error=f"{type(exc).__name__}: {exc}"))
            try:
                icon._mark_ready()   # pystray's own setup thread waits for this and is not a daemon
            except Exception:
                pass

    dark_menus()
    try:
        icon = pystray.Icon("sidenote", tray_image(), TRAY_TITLE, menu)
        own_tray_menu(icon)
    except Exception as exc:
        print("[tray] " + t("Could not make the tray icon ({error}); going on without it", error=f"{type(exc).__name__}: {exc}"))
        return None
    if sys.platform == "darwin":
        # AppKit runs its loop on the main thread only: main() hands that thread to the icon and waits beside it
        icon.sidenote_main = run_icon
        # the app opened again while it runs, by a double-click in the Finder say: the panel, as from the menu
        icon.sidenote_reopen = answer_reopen(lambda: open_panel(icon))
    else:
        thread = threading.Thread(target=run_icon, daemon=True)
        thread.start()
        # Creating the window fails at once when it fails at all, so a short look is enough to know
        # whether to tell the user about an icon that is there.
        failed.wait(0.6)
        if failed.is_set():
            return None
        icon.sidenote_thread = thread   # main() waits for it, so the icon is gone before the process is

    def keep_menu_current() -> None:
        """Windows shows the menu pystray built last, and pystray builds it again only at start, after a click on
        the icon and after a menu action: a switch flipped in the panel, or the server going away, left the state
        line and the check marks saying what was. Built again whenever what they show
        changes; once a second is enough for a menu nobody holds open while it changes."""
        shown = None
        while not stop.is_set():
            # the switches' checks, and the state line: what is taken (a sound device that failed or came back too) and a skip
            now = (sender.connected, bool(sender.wants.get("screen")), bool(sender.wants.get("audio")), tuple(taking()), skipped())
            if now != shown:
                shown = now
                try:
                    if sys.platform == "darwin":   # AppKit's menu is changed on its own thread only
                        from PyObjCTools import AppHelper
                        AppHelper.callAfter(icon.update_menu)
                    else:
                        icon.update_menu()
                except Exception:   # the icon going away as this runs: nothing left to keep current
                    pass
            stop.wait(1.0)

    threading.Thread(target=keep_menu_current, daemon=True).start()
    return icon


# The exit code that asks the desktop app to start this program again (desktop/app.py, CAPTURE_RESTART).
SUPERVISED_RESTART = 75

# ---------- whoever starts the server stops it ----------
# The desktop shortcut starts a session: the server when it is off (./sidenote capture --up), then this program. The
# server is a service of its own, which no client starts or stops; the launcher does, and it hands this program
# --stop-server-on-quit only when it brought the server up for this start. The person's Quit from the tray then ends
# the session as it began, through the launcher's own ./sidenote down in that checkout. A server started on its own
# (./sidenote up) is left running, as is one on another PC or a cluster. Before, Quit ended this program alone, and the
# server the shortcut had started stayed up with its model on the GPU until someone typed ./sidenote down.
# A checkout's WSL path as Windows shows it: \\wsl.localhost\<distro>\<path> (\\wsl$\ on older Windows). The distro's
# name is WSL's own kind of name; the path keeps out what no Windows path holds, and control characters.
WSL_CHECKOUT = re.compile(r'\\\\wsl(?:\.localhost|\$)\\([A-Za-z0-9._-]{1,64})((?:\\[^\\\x00-\x1f"<>|?*]+)+)\\?')


# What runs in WSL on Quit, as client/launch.pyw runs the launcher: a login shell (bash -l reads ~/.profile, where a
# SIDENOTE_PORT, a DOCKER_HOST or the folder of docker may be set), the checkout as its argument and never in the script
QUIT_SCRIPT = 'cd -- "$1" || exit; exec ./sidenote down'


def own_checkout() -> str:
    """The checkout this program runs from: the folder above client/, where its launcher is."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def server_down_command(checkout: str, platform: str = sys.platform, own: str | None = None) -> list | None:
    """The command that stops the server a start brought up: ./sidenote down in this program's own checkout, and nothing
    else. None for any other value. The value comes from the launcher's command line, and the desktop shortcut's starter
    passes the launcher's lines on, which a forged line could fill: so it must name the checkout this program runs from
    (`own`, as WSL shows it on Windows), and what Quit can run is that checkout's ./sidenote down, whatever a line says."""
    if not checkout or any(ord(c) < 32 for c in checkout):
        return None
    own = own_checkout() if own is None else own
    if platform == "win32":   # this checkout in WSL: wsl.exe runs its launcher there, in a login shell
        m, mine = WSL_CHECKOUT.fullmatch(checkout), WSL_CHECKOUT.fullmatch(own)
        # the same checkout: the distro's name in any case (WSL takes it so), the path as it is (Linux tells cases apart);
        # wsl$ and wsl.localhost are one share, and a closing backslash names the same folder
        if not m or not mine or m.group(1).lower() != mine.group(1).lower() or m.group(2) != mine.group(2):
            return None
        # made from where this program runs: the value only says yes, for this checkout
        return ["wsl.exe", "-d", mine.group(1), "--exec", "bash", "-lc", QUIT_SCRIPT, "sidenote-quit",
                mine.group(2).replace("\\", "/")]
    if not os.path.isabs(checkout) or os.path.realpath(checkout) != os.path.realpath(own):
        return None
    script = os.path.join(own, "sidenote")   # made from where this program runs: the value only says yes, for this checkout
    # a Sidenote checkout: its launcher, runnable, beside the capture program it starts
    if not (os.path.isfile(script) and os.access(script, os.X_OK)
            and os.path.isfile(os.path.join(own, "client", "capture.py"))):
        return None
    return [script, "down"]


def session_ends_server(sender) -> bool:
    """Whether this end stops the server too: the person's Quit from the tray, after a start that brought the server up.
    Never for an end this program was asked for (./sidenote capture-stop and down ask through the server, another
    capture program took over), nor for a restart of its own, nor under the desktop app, which ends its own server."""
    return (getattr(sender, "quit_by_person", False) and not getattr(sender, "restart_asked", False)
            and not getattr(sender, "taken_over", False) and os.environ.get("SIDENOTE_SUPERVISED") != "1")


def stop_server(command: list | None) -> bool:
    """Starts the command that stops the server, on its own: this program ends at once after it, and the launcher's
    down asks capture programs to end first, which this one has. No window on Windows, no terminal elsewhere. True when
    it started; when it could not, the log says how to stop the server instead."""
    if not command:
        return False
    import subprocess
    print("[main] " + t("Stopping the server this start brought up too (./sidenote down)"))
    how: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        # its own group and no console window; out of this program's job when Windows lets it, so it outlives this program
        no_window, own_group, breakaway = 0x08000000, 0x00000200, 0x01000000
        try:
            subprocess.Popen(command, creationflags=no_window | own_group | breakaway, **how)
            return True
        except OSError:          # a job that allows no breakaway: started inside it, which ends no sooner than this program
            pass
        how["creationflags"] = no_window | own_group
    else:
        how["start_new_session"] = True   # its own session: this program ending, or its terminal closing, does not end it
    try:
        subprocess.Popen(command, **how)
        return True
    except OSError as exc:
        print("[main] " + t("Could not stop the server: {error}. ./sidenote down stops it", error=exc))
        return False

# ---------- one capture program for a server ----------
# The exit code of a start that found another capture program running for the same server and ended (OneCapture).
# client/launch.pyw reads it: the program it started is not the one that runs, and the one that runs is no failure.
CAPTURE_BUSY = 76
# The exit code of a program that ended because another capture program connected to its server and feeds it now
# (take_over in server/app.py). The desktop app starts its own again on it, to take its server back, where an end with
# 0 (a quit) would have ended the app and the server with it (desktop/app.py, CAPTURE_TAKEN_OVER).
CAPTURE_TAKEN_OVER = 77
ERROR_ALREADY_EXISTS = 183    # what GetLastError says after CreateMutexW opened a mutex another process had made
START_WAIT = 0.5              # seconds a start keeps asking: a starter looking whether one runs holds the guard for a moment
RESUME_WAIT = 5.0             # seconds one that restarted itself keeps asking: the program before it may still be ending


def instance_name(server: str) -> str:
    """The server a capture program sends to, as the short name two programs for one server share: its host and port
    (127.0.0.1 for every name of this PC, the scheme's own port where none is written), hashed, because a mutex's
    name and a file's cannot hold an address as it is written. client/launch.pyw has the same function for the same
    name (tests/capture_single.py holds the two together)."""
    import hashlib
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
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]   # a name, not a secret: 16 digits keep it short


class OneCapture:
    """One capture program at a time for a server. Two send every screen and every sound twice, and the launcher
    cannot always see the first: a WSL that cannot start Windows programs cannot read Windows' process list, and a
    program that is connecting again (the server came up a moment ago) is not in the server's count.

    The guard is one the system lets go of when the process ends, however it ends: a named mutex on Windows, a lock
    on an open file elsewhere. Not a file holding a process id, which a crash leaves behind to refuse every start
    after it. Only another program holding the guard refuses a start. Whatever else keeps it from being taken (no
    folder for the file, a file that is another user's, a Windows that makes no mutex) leaves this program running
    unguarded, as it ran before there was a guard: a start refused wrongly is worse than no guard."""

    def __init__(self, server: str):
        self.name = instance_name(server)
        self.handle = None        # Windows: the mutex, for as long as it is held
        self.fd = None            # elsewhere: the open file whose lock is held
        self._close = None        # Windows: CloseHandle, kept from the take for the release

    def lock_path(self) -> str:
        """The file locked off Windows: in the user's own runtime folder (gone at log out) or else the temporary
        folder, named for the user, since that folder is shared, and for the server. It holds nothing and is not
        deleted: taking away a file that a program has locked would let the next start lock a new one beside it."""
        import tempfile
        folder = os.environ.get("XDG_RUNTIME_DIR", "")
        if not os.path.isdir(folder):                         # not set, or set to what is not there
            folder = tempfile.gettempdir()
        return os.path.join(folder, f"sidenote-capture-{os.getuid()}-{self.name}.lock")

    def _try(self):
        """True: the guard is held now. False: another program holds it. None: there is no guard to be had."""
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)     # use_last_error: see below
                kernel32.CreateMutexW.restype = ctypes.c_void_p               # a HANDLE, pointer sized
                kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
                kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
                ctypes.set_last_error(0)                                      # what an earlier call left is not this one's
                # "Local\": this Windows session's own names. No security attributes: the handle is not passed on
                # to a program this one starts (the tray menu, the next one at a restart), which would hold the
                # guard in its place.
                handle = kernel32.CreateMutexW(None, False, f"Local\\Sidenote.Capture.{self.name}")
                # CreateMutexW also succeeds when the mutex is there already, and only GetLastError tells the two
                # apart: ctypes' own copy of it, since anything Python calls in between can overwrite the real one.
                error = ctypes.get_last_error()
            except Exception:     # no ctypes, no kernel32 as expected: no guard
                return None
            if not handle:        # Windows made no mutex and opened none: no guard
                return None
            if error == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)                                  # this handle would keep the name alive
                return False
            self.handle, self._close = handle, kernel32.CloseHandle
            return True
        try:
            import fcntl
            # O_NOFOLLOW: a link put where the file goes is not followed. 0600, and never truncated: it holds nothing.
            fd = os.open(self.lock_path(), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except (ImportError, OSError):   # no folder to make it in, a link in its place, a file this user cannot open
            return None
        try:
            if os.fstat(fd).st_uid != os.getuid():   # another user's file under this name: its lock says nothing here
                os.close(fd)
                return None
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # held by the open file, so the system drops it with the process
        except BlockingIOError:   # the one error that means another program holds the lock
            os.close(fd)
            return False
        except OSError:           # a file system that does not lock: no guard
            os.close(fd)
            return None
        self.fd = fd              # not inheritable (Python opens files that way): a program started here does not hold it
        return True

    def take(self, wait: float = 0.0) -> bool:
        """False when another capture program held the guard for the whole of `wait` seconds; True otherwise, with the
        guard held, or with none to be had."""
        end = time.monotonic() + wait
        while True:
            if self._try() is not False:
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.1)

    def release(self) -> None:
        """Lets the guard go while this program still runs: before it starts the program that takes its place."""
        if self.handle:
            self._close(self.handle)
            self.handle = None
        if self.fd is not None:
            try:
                os.close(self.fd)   # closing the file drops its lock
            except OSError:
                pass
            self.fd = None


def hold_main_thread(icon, wait_until_done, stop: threading.Event) -> None:
    """macOS: the tray icon's loop on this thread, the main one, as AppKit needs, and the waiting beside it; returns once
    both are done. The end is handed to the loop through AppKit's own queue: pystray's stop() does nothing until the
    loop has started, and a quit or a restart that came while this program was still starting would be lost, leaving
    an icon over a capture that had ended. An icon that cannot run leaves the waiting to go on alone."""
    def wait_then_end() -> None:
        wait_until_done()
        stop.set()
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(icon.stop)   # run by the loop once it runs, whenever this comes
        except Exception:                    # no loop to end
            pass

    waiter = threading.Thread(target=wait_then_end, name="tray-wait", daemon=True)
    waiter.start()
    icon.sidenote_main()   # returns when the loop is ended, or at once when it could not run
    while waiter.is_alive():
        waiter.join(0.25)


def main() -> None:
    ap = argparse.ArgumentParser(description="sidenote capture client (Windows adds the window list, the display metrics and the notification icon)")
    ap.add_argument("--server", default="ws://127.0.0.1:8777/ingest",   # not localhost: it can resolve to ::1 and time out
                    help="the server's ingest WebSocket (default: ws://127.0.0.1:8777/ingest)")
    ap.add_argument("--fps", type=float, default=3.0, help="screen poll rate")
    ap.add_argument("--monitor", type=int, default=None,
                    help="mss monitor index (1 = primary, 0 = all); also changed in the panel's settings")
    ap.add_argument("--list-monitors", action="store_true", help="list attached monitors and exit")
    ap.add_argument("--max-width", type=int, default=3840,
                    help="wider screens are scaled down to this width before sending (pixels); the server "
                         "scales its own copy for the model and cuts problems out of what arrives")
    # Low on purpose: a one-word change on the same template (~0.13) must reach the server,
    # which measures change inside the answered problem's region and ignores the rest.
    ap.add_argument("--threshold", type=float, default=0.1,
                    help="signature MAD of a settled screen worth sending (the server decides what is new)")
    ap.add_argument("--settle", type=float, default=0.3, help="signature MAD below which the screen is 'still'")
    ap.add_argument("--stable-polls", type=int, default=2, help="polls a screen must stay still before sending")
    ap.add_argument("--stitch", action="store_const", const=True, default=None,
                    help="scroll-stitch mode: assemble a long page from viewports as you scroll, "
                         "then send it whole (for problems taller than one screen). Scroll at a normal pace; "
                         "just don't jump a whole screen height at once. Also switched in the panel's settings.")
    ap.add_argument("--no-audio", action="store_true", help="capture the screen only, no sound")
    ap.add_argument("--resumed", action="store_true", help=argparse.SUPPRESS)   # this program restarting itself
    # How it was started, which the launcher says (./sidenote: shortcut from the desktop shortcut's starter, terminal from a
    # terminal's ./sidenote capture) and the panel's Capture connection shows; by hand it says nothing (who_am_i: own)
    ap.add_argument("--started", choices=("shortcut", "terminal"), default="", help=argparse.SUPPRESS)
    ap.add_argument("--no-tray", action="store_true", help="do not put an icon in the notification area")
    ap.add_argument("--stop-server-on-quit", default="", metavar="CHECKOUT",
                    help="the Sidenote checkout whose ./sidenote down Quit in the tray runs too: the launcher passes it when "
                         "this start brought the server up (./sidenote capture --up). On Windows the checkout's WSL path "
                         r"(\\wsl.localhost\<distro>\...), elsewhere its folder")
    ap.add_argument("--no-auto-update", action="store_true",
                    help="do not restart into new code when a deploy asks (it does, at a quiet moment, by default)")
    ap.add_argument("--no-auto-stitch", action="store_true",
                    help="do not join a problem by itself when the screen is scrolled")
    ap.add_argument("--once", action="store_true",
                    help="send the screen as it is now and exit (no sound, nothing left running)")
    ap.add_argument("--audio-device", default="", help="loopback device name substring (default: default speaker)")
    ap.add_argument("--log", default="",
                    help="append what it prints to this file (it runs with no console window)")
    args = ap.parse_args()

    # Each line out as it is printed. Under the desktop app this goes down a pipe into capture.log, which got it in
    # blocks of 8 KB; and a quit the system sends on macOS (at log out) ends this program inside AppKit, with what was
    # held back never written. No stream at all (pythonw) has nothing to set.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except Exception:
            pass
    # Before anything prints: pythonw gives this program no stdout at all, and a console can go
    # away while it runs (see _Quiet).
    sys.stdout, sys.stderr = _Quiet(sys.stdout), _Quiet(sys.stderr)
    if args.log:
        _log_to(args.log)

    if args.list_monitors:
        list_monitors()
        return

    # One capture program for a server (OneCapture), asked before anything is connected or captured. --once sends one
    # screen beside whatever runs and ends, so it neither takes the guard nor is refused by it. One that restarted
    # itself was started by the program before it, which lets the guard go first and may still be ending: it asks
    # for longer. Under the desktop app (SIDENOTE_SUPERVISED) the guard is taken when it is free and never refuses: the
    # app starts this program again whenever it ends, and an end here would only be the first of a row of them.
    guard = OneCapture(args.server)
    if not args.once and not guard.take(RESUME_WAIT if args.resumed else START_WAIT) \
            and os.environ.get("SIDENOTE_SUPERVISED") != "1":
        print("[main] " + t("Another capture program is already running for this server, so this one ends."))
        print("[main] " + t("To end the one that runs: Quit in its tray icon, or ./sidenote capture-stop in the server's terminal."))
        sys.stdout.flush()
        sys.exit(CAPTURE_BUSY)   # nothing is started yet, so a plain exit: the starter reads the code (client/launch.pyw)

    set_dpi_aware()
    sender = Sender(args.server)
    # Options given on this start win over the panel's last settings (they are the latest choice);
    # the panel can change them again while this runs.
    if args.once:          # one screen and out: no sound, and the panel's switch cannot hold it back
        args.no_audio = True
        # its hello says so: the server takes its screen beside the program that runs and leaves that one feeding it
        sender.caps["once"] = True
    # One that restarted itself (a deploy, the tray's Restart) is the same sitting: its hello carries no options, or the
    # server would clear the drawn region and put the panel's monitor back to what this was first started with.
    flags = {k: v for k, v in (("monitor", args.monitor), ("stitch", args.stitch)) if v is not None and not args.resumed}
    sender.wants.update(flags)
    # `following`: the monitor read while following the changing screen has moved the reading off the chosen one, None
    # until it does; said from the first hello, so a server that knew another one hears that it changed
    sender.caps.update(audio=not args.no_audio, no_audio=args.no_audio, monitor=sender.wants["monitor"], following=None)
    if not args.resumed:
        sender.caps["flags"] = flags
    # which code this is, sent with every hello: ./sidenote up asks for a restart when it deployed other code
    sender.caps["code"] = code_mark(os.path.abspath(__file__))
    # and whether that restart is taken: no Updater runs below for these two, so the request is said and let go
    sender.auto_update = not (args.once or args.no_auto_update)
    sender.who = who_am_i(args)   # and what it is, for the panel's Capture connection
    # Connect and take the panel's switches before grabbing anything: with the screen switched off
    # nothing is captured at all, not even a first frame. No server yet: start as switched on.
    sender.keepalive()
    if not sender.told.wait(3):
        print("[main] " + t("no word from the server yet; starting with screen and sound on"))
    stop = threading.Event()
    threads = [threading.Thread(target=screen_loop, args=(sender, stop, args), daemon=True)]
    if not args.no_audio:
        threads.append(threading.Thread(target=audio_loop, args=(sender, stop, args), daemon=True))

    for worker in threads:
        worker.start()
    tray = None if (args.once or args.no_tray) else start_tray(sender, stop, args)
    # Started without a window (--log, as ./sidenote capture does) there is no console for Ctrl+C to reach.
    # with no tray icon (--no-tray, or no pystray) there is no Quit in it to name. Under the desktop app neither a console
    # nor ./sidenote is there: what it prints goes to capture.log, and its Quit Sidenote ends the app (desktop/app.py)
    if os.environ.get("SIDENOTE_SUPERVISED") == "1":
        how = (t("To end it: Quit Sidenote on the panel's Capture connection.") if tray is None
               else t("To end it: Quit Sidenote in the tray icon."))
    else:
        how = (t("Ctrl+C to stop.") if not args.log else
               t("To end it: ./sidenote capture-stop in the server's terminal.") if tray is None else
               t("To end it: Quit in the tray icon, or ./sidenote capture-stop in the server's terminal."))
    print("[main] " + t("capturing.") + " " + how
          + ("" if tray is None else " " + t("The tray icon opens the panel and switches the screen and the sound on and off.")))
    updater = Updater(os.path.abspath(__file__), args.server) if sender.auto_update else None

    def wait_until_done() -> None:
        while not stop.is_set():   # a loop that is done (--once) ends this too
            if sender.quit_asked:
                break
            if updater is not None and updater.due(sender):
                sender.restart_asked = True
                break
            time.sleep(0.25)

    try:
        if getattr(tray, "sidenote_main", None) is None:
            wait_until_done()
        else:
            hold_main_thread(tray, wait_until_done, stop)
            tray = None            # its loop is over, and the icon is gone with it
    except KeyboardInterrupt:
        print("\n[main] " + t("stopping..."))
    stop.set()
    if tray is not None:
        tray.stop()
        # stop() only posts a message; the icon is taken out of the notification area by the tray
        # library's own thread. Ending the process before that leaves the icon on screen.
        thread = getattr(tray, "sidenote_thread", None)
        if thread is not None:
            thread.join(timeout=2)
    for worker in threads:
        worker.join(timeout=2)
    if getattr(sender, "restart_asked", False) and os.environ.get("SIDENOTE_SUPERVISED") == "1":
        # Started by the desktop app (desktop/app.py), which watches this process and starts the next one itself:
        # this exit code asks it to. A copy started here would be one it does not know of.
        print("[main] " + t("starting again..."))
        sys.stdout.flush()
        os._exit(SUPERVISED_RESTART)
    if session_ends_server(sender):
        stop_server(server_down_command(args.stop_server_on_quit))
    if getattr(sender, "restart_asked", False):
        # The same command line as this one: sys.orig_argv keeps the interpreter's own flags (-X utf8
        # -u, which the launcher relies on), and a list keeps an argument with a space in it whole.
        # Popen, not execv: execv on Windows ends this process and the launcher's cleanup can then
        # kill the new one by name.
        print("[main] " + t("starting again..."))
        import subprocess
        cmd = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
        if "--resumed" not in cmd:
            cmd.append("--resumed")
        # The guard goes before the next one starts: held until this process ends, the next would find it taken and
        # end as a second capture program (it also asks for a few seconds, for a program slow to end: RESUME_WAIT).
        guard.release()
        try:
            subprocess.Popen(cmd, close_fds=True)
        except Exception as exc:
            print("[main] " + t("Could not start again: {error}", error=exc))
    # os._exit, not a plain return: a tray library that could not start leaves a thread of its own
    # waiting on something that will never come, and the interpreter would wait for it for ever.
    sys.stdout.flush()
    os._exit(CAPTURE_TAKEN_OVER if getattr(sender, "taken_over", False) else 0)


if __name__ == "__main__":
    main()
