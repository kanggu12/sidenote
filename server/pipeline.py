"""One problem, from the screen or from speech, to an answer, through the stages the panel switches.

1. The image the local model looks at: the whole screen (downscaled), or only the box the user drew.
2. The local fast pass answers at once, or says the problem needs reasoning (with where it is).
3. A problem that needs reasoning goes to the agent in the `hard` mode when its type is ticked (and
   always in the `all` mode), else to the local thinking pass, which also gets the problem cropped at
   the screen's own resolution.
4. The agent gets only the problem: the crop, the problem written out as text, or (if chosen) the whole
   screen. A spoken problem goes as the question part of what was heard, written out locally.
5. Code answers can be checked against the problem's examples in the runner sandbox.
6. In the `verify` mode the local model solves everything, and afterwards the agent gets each problem (as in
   4) with the local answer and says whether it holds.

What leaves the PC on the way (search queries, page reads, the agent's payload) is listed in
Outcome.sent; the server shows it on the card and in events.jsonl.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import pathlib
import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from . import repeats, telemetry
from .analyzer import (CROP_REQUEST, DEEP_TYPES, LIMIT_RE, NO_QUESTION, LoadStopped, build_user_text, error_hint, error_words,
                       speech_request, text_request, verify_request)
from .codecheck import CHECKED, answer_code, other_language, run_cases
from .config import CONFIG, agent_name
from .heads import TALL_BOX, head_of, head_start, parse_region, region_box, within
from .i18n import t
from .settings import SETTINGS

log = logging.getLogger("sidenote.pipeline")

# Margin around the problem box when cropping (left, top, right, bottom): the model's boxes run a little
# tight, most of all on the left, where they often start at the code or the body and leave out the
# problem's first column (3 runs of the 23 known-answer screens: 6% on every side held the
# whole problem 61 of 69 times, 15% on the left 65, as many as 15% on every side at two thirds of the
# area). A cut-off line is worse than a bit of background; the window edge still bounds the cut.
CROP_PAD = (0.15, 0.06, 0.06, 0.06)
CROP_MAX_SIDE = 1600          # a crop is sent at the screen's own resolution up to this long side
WHOLE_SCREEN = 0.8            # a problem box this large is not a place on the screen (located)
HALVES_AT = 3200              # a screen this long or longer can go to the thinking pass in halves
ONE_WINDOW = 0.8              # nor one that other windows show more than the rest of
CONFIRM_TIMEOUT = 120.0       # "confirm before sending": no answer in this long means do not send
# What an agent turn cut short is counted at before any whole turn has said its price: about what a turn that
# finds nothing costs (93 such turns cost $3.61), so the ceiling errs on the side of stopping.
CUT_SHORT_USD = 0.04
EDITOR_WAIT = 8.0             # the editor's language is asked for this long at most before the agent goes on


class NoSolver(RuntimeError):
    """Neither the local model nor the agent can take the problem (switched off, not signed in, down)."""


class GpuBusy(TimeoutError):
    """Neither the local model nor the one it uses while the GPU is held started on a screen within the first-token
    deadline: the GPU is taken by something else. Nothing went to the agent (where the problem is was never read).
    A TimeoutError still, for whatever reads it as one; the worker tells it apart to stay quiet (app.py)."""


class Repeat(Exception):
    """The problem on this screen is one answered lately, seen again (scrolled, moved, come back to): it is not solved
    a second time unless asked to (Reanalyze). `card` is the earlier answer's id, `box` where the problem
    is now (the change watch moves there), `score` the match's (repeats.same_picture)."""

    def __init__(self, card: int, box, score: float):
        super().__init__(f"the problem of answer #{card}, seen again")
        self.card, self.box, self.score = card, box, score


class NotSent(Exception):
    """Nothing went to the agent: the user chose not to send it (confirm before sending), or what would go
    could hold more than the problem (it could not be placed, or what was written out from the whole
    screen holds numbers shaped like personal data), and the local model takes it instead. The message is
    the reason as a clause ("could not find where the problem is"), empty when it is the user's choice."""


class NothingAsked(NotSent):
    """What was heard holds no question to pick out: nothing goes to the agent, and there is nothing to solve."""


@dataclass
class Hooks:
    """What the pipeline needs from the server."""
    local_ok: Callable[[], bool]
    agent_ok: Callable[[], bool]
    notice: Callable[[str], Awaitable[None]]                 # a short note on the panel
    # (analysis id, stage, detail, restart=): the card's status line. `restart` throws away what has
    # been written into the card so far, for when another engine starts the answer over.
    stage: Callable[..., Awaitable[None]]
    confirm: Callable[[int, dict], Awaitable[bool]]           # (analysis id, preview) -> send?
    agent_failed: Callable[[Exception], Awaitable[None]]     # an error from the agent (sign-in state)
    # a note that says something was not done (failed, held back, not sent), which the panel draws as a warning;
    # `notice` takes it when this is not given
    warn: Callable[[str], Awaitable[None]] | None = None


@dataclass
class Outcome:
    text: str
    model: str | None
    usage: dict | None
    cost_usd: float | None
    engine: str                     # "local" | "agent"
    region: tuple | None = None     # the problem on screen, pulled in (duplicate detection, thumbnail)
    crop_box: tuple | None = None   # the problem as the model gave it (crops: the code check, follow-ups)
    region_placed: bool = False     # the box really places the problem, so the panel may draw it
    shown: tuple | None = None      # what a crop of it takes, grown to the writing it lands in: what the panel draws
    # What the local model read the problem from when no crop was placed: the fast pass's box cut as given, or
    # "halves". Only for what stays on this PC (the code check's examples, the problem text).
    local_view: tuple | str | None = None
    # The model's own box as it gave it (the fast pass's REGION, not pulled in), placed or not: what the agent's words are
    # read from when it places nothing on a large screen (box_first), for the verify mode as for the answer itself.
    # Only the fast pass's: a pass that thinks or answers directly writes its REGION y first at times (solve), and a
    # box that places nothing is not checked against any window, so the direct pass's leaves it None.
    seen: tuple | None = None
    sent: list = field(default_factory=list)    # [{"to": "search"|"page"|"agent", "what": str}]
    stages: dict = field(default_factory=dict)  # which stages ran, for the card
    # The problem as it went to the agent in words (the problem text, or the question part of what was heard), when
    # it went that way: a follow-up that sends no image carries it again (followup).
    words: str = ""


# ---------- images ----------

def _fit(img: Image.Image, max_side: int) -> Image.Image:
    if max(img.size) <= max_side:
        return img
    k = max_side / max(img.size)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _meet(a, b) -> tuple:
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _shown(box, windows, i) -> float:
    """How much of `box` window i shows: its part of the box less what the windows in front of it
    cover (exact, over the grid their edges make)."""
    part = _meet(box, windows[i])
    if _area(part) <= 0:
        return 0.0
    front = [f for f in windows[:i] if _area(_meet(part, f)) > 0]
    if not front:
        return _area(part)
    xs = sorted({part[0], part[2], *(min(max(v, part[0]), part[2]) for f in front for v in (f[0], f[2]))})
    ys = sorted({part[1], part[3], *(min(max(v, part[1]), part[3]) for f in front for v in (f[1], f[3]))})
    seen = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if not any(f[0] <= cx <= f[2] and f[1] <= cy <= f[3] for f in front):
                seen += (x1 - x0) * (y1 - y0)
    return seen


def window_of(box, windows) -> int | None:
    """The window (its index in `windows`, front to back) that shows most of `box`. The model's box can
    run over the next window by half its width (measured on desktops with several windows), so the
    window is the one that shows the most of it, not one that holds a set share. The list never holds the
    desktop or the taskbar (the capture program leaves them out), so a window over the whole screen is a
    full-screen program. None without windows or when no window shows any of the box (the wallpaper)."""
    best, most = None, 0.0
    for i in range(len(windows or ())):
        seen = _shown(box, windows, i)
        if seen > most + 1e-12:   # a tie goes to the window in front
            best, most = i, seen
    return best


def clip_to_window(box, windows, inner=None) -> tuple:
    """Clip a box to the window that shows most of it, so a neighbouring window never comes along.
    `windows`: top-level window rectangles in screen fractions, front to back (from the capture
    program). `inner`: the box to pick the window by, when `box` is that box with a margin (a wide
    margin could otherwise fall mostly in the next window). Windows in front of that one may still
    cover part of the cut: in_front() gives those parts, and crop_image blanks them."""
    i = window_of(inner or box, windows) if windows else None
    return box if i is None else _meet(box, windows[i])


def in_front(cut, windows, inner=None) -> list:
    """The parts of `cut` that windows in front of its window cover (screen fractions)."""
    if not windows:
        return []
    i = window_of(inner or cut, windows)
    return [r for r in (_meet(cut, f) for f in windows[:i or 0]) if _area(r) > 0]


def placed_region(region, view, windows=None) -> bool:
    """Whether the model's box really places the problem: it sits on a window and is not the whole
    screen (`located`). The box is kept either way, since the change detector would otherwise watch
    the whole screen and answer the same thing again, but only a placed one is drawn on the panel:
    a box over empty wallpaper under the words "the highlighted part is what was taken for the problem" says the problem
    is somewhere it is not. Seen once: a knight problem answered rightly from its text with
    the box on the desktop beside the window it came from."""
    if not region:
        return False
    return located(within(region, view), windows) is not None


def box_aspect(frame, view) -> float:
    """The height over the width of the picture a REGION line was written on, `view` of the screen (heads.TALL_BOX); 0 with
    no screen to go by."""
    w, h = (view[2] - view[0]) * getattr(frame, "width", 0), (view[3] - view[1]) * getattr(frame, "height", 0)
    return h / w if w > 0 and h > 0 else 0.0


# A box written y first that TALL_BOX cannot tell by its shape: up to twice as tall as wide. Read as written, a strip of a
# wide problem stands on end, and its left and right edges run down through the lines of text; turned, they lie in the
# margins. So such a box is turned when the edges of the turned one cross less than UPRIGHT_CUT as much writing, counted
# against the writing inside each. On the first passes kept from earlier runs of the known-answer set, 19 boxes stood
# between once and twice as tall as wide: this turned 4 of them, each from 3 to 18 per cent of its problem to 71 to 100,
# and none of the boxes that held their problem (a coding site's pane down the left is that shape too).
UPRIGHT_CUT = 0.6


def _side_cut(edges, box) -> float | None:
    """How much writing a box's left and right edges cross, over how much is inside it, on an edge map of the picture.
    None for a box with a side on the picture's own edge, where nothing can be crossed: a pane down the left of the
    screen, turned, runs from edge to edge and would look as if it cut through nothing."""
    w, h = edges.size
    x0, y0, x1, y1 = (int(round(v * s)) for v, s in zip(box, (w, h, w, h)))
    if x0 < 2 or x1 > w - 3:
        return None
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 + 2 or y1 <= y0 + 2:
        return None
    inside = ImageStat.Stat(edges.crop((x0, y0, x1, y1))).mean[0] + 1e-6
    side = sum(ImageStat.Stat(edges.crop((x - 1, y0, x + 2, y1))).mean[0] for x in (max(1, x0), x1)) / 2
    return side / inside


def on_end(box, aspect: float) -> bool:
    """Whether a box (fractions of the picture it was written on, `aspect` its height over its width) stands between once
    and twice as tall as wide: the shape upright looks at."""
    return bool(box) and bool(aspect) and 1.0 < (box[3] - box[1]) * aspect / max(1e-9, box[2] - box[0]) <= TALL_BOX


def upright(frame, view, box, aspect: float = 0.0):
    """`box` (fractions of `view` of the screen) turned, when it was written y first in a shape TALL_BOX lets through.
    `frame` is the screen the server holds (its PNG as it arrived, server/app.py Frame), or a picture. Runs in a thread:
    a 4K screen is read and its edges found in about 0.15 s."""
    if box is None or frame is None or not on_end(box, aspect):
        return box
    x0, y0, x1, y1 = box
    turned = (y0, x0, y1, x1)
    try:
        if hasattr(frame, "crop"):
            pic = frame
        elif getattr(frame, "full_png", b""):
            pic = Image.open(io.BytesIO(frame.full_png))
        else:
            return box
        W, H = pic.size
        pic = pic.crop((int(view[0] * W), int(view[1] * H), int(view[2] * W), int(view[3] * H)))
        edges = pic.convert("L").filter(ImageFilter.FIND_EDGES)
        # FIND_EDGES leaves the picture's own brightness in its outermost pixels, a bright line down a box that starts at the
        # picture's left edge: those go
        ImageDraw.Draw(edges).rectangle((0, 0, edges.width - 1, edges.height - 1), outline=0)
        as_written, other = _side_cut(edges, box), _side_cut(edges, turned)
        if as_written is None or other is None:   # nothing to tell them apart by
            return box
        return turned if other < UPRIGHT_CUT * as_written else box
    except Exception:   # a picture that cannot be read leaves the box as written
        return box


def located(box, windows=None) -> tuple | None:
    """The problem box, or None when it does not place the problem: (nearly) the whole screen (measured:
    a 4K screen whose text the model could not read, two problems side by side, a task next to a
    terminal), mostly over the wallpaper, or split between windows (on desktops with several windows the
    model's box ran a third to a half of its width into the next window, at times the wrong one). A crop
    of such a box would be the screen again, or the wrong window. Without one the thinking pass reads the
    screen, and the agent gets the problem written out, or nothing (NotSent) when it cannot be or the text
    holds numbers shaped like personal data."""
    if _area(box) >= WHOLE_SCREEN:
        return None
    if windows:
        i = window_of(box, windows)
        if i is None or _shown(box, windows, i) < 0.5 * _area(box):   # mostly wallpaper
            return None
        others = sum(_shown(box, windows, j) for j in range(len(windows)) if j != i)
        if others > (1 - ONE_WINDOW) * _area(box):   # the wallpaper and the taskbar strip are no window
            return None
    return box


# Growing the model's box out to the edges of what it sits in, so the crop holds the whole problem.
#
# Measured on the 102 crops that four runs of the known-answer set recorded, replaying the boxes the
# model really drew (scratch/smoke/roi_snap.py). The box with its margin alone holds all of the
# problem on 95 of them and keeps as little as 36 per cent of one. Growing it the way below takes
# that to 99 of 102 with the worst at 63 per cent, and costs nothing anywhere else: no crop loses a
# single pixel of detail, and the largest crop is the same size it was before.
#
# What makes it free is the guard. A crop is shrunk to CROP_MAX_SIDE before it is sent, so a crop
# that carries more of the screen can make the problem's own letters smaller in the picture the agent
# is given, which is a worse question, not a better one. Unguarded, this is what growing did: a 4K
# screen whose crop already held the whole problem came back with its text at less than half the
# size, and three screens came back as the whole desktop. So each way of growing is worked out, the
# final crop is compared with the final crop of the box alone, and a growth is taken only when it
# costs no detail at all and does not swallow the screen.
SNAP_GAP = 0.008     # a blank run this deep, as a fraction of the screen, is the edge of the block
SNAP_GROW = 4.0      # and one growth may not add more than this many times the box's own size
SNAP_MAX_AREA = 0.6  # a crop this large is the desktop, not a problem: the whole screen has its own
                     # path out (and its own check for personal data), and must not arrive by growing
SNAP_FRAME = 0.9     # an unbroken stroke across this much of the window is part of its frame, not writing
# Below a box that is read on this PC (the code check's examples, the problem's text), a blank run must be this
# deep to end it. The gutter above is the blank between one block of writing and the next, and between one
# example and the next it is that too: of 170 code-check readings of the bench's coding screens, 2 came from a
# box the model ended above the last example (Baekjoon's example input 2, LeetCode's Example 2), the walk stopped at
# the blank under the one before it, and the check ran on one example fewer (check_read.py). The
# blank between examples there is 0.02 to 0.03 of the screen. Read again from the very boxes those runs recorded, the
# 28 crops this changes gave one example fewer 4 times in 56 readings before and once after, with no example made up
# and none left out (scratch/local-llm-bench/reach_replay.py). Only a crop that stays on this PC goes on this far:
# a crop that leaves it keeps the gutter above and its guard (grow_to_block).
READ_REACH = 0.04


def _longest_runs(a):
    """The longest unbroken run of True along each row of a 2-D boolean array, as one number per row."""
    import numpy as np

    # padded with False on both sides, so every run has a start and an end inside the row
    p = np.zeros((a.shape[0], a.shape[1] + 2), dtype=np.int8)
    p[:, 1:-1] = a
    d = np.diff(p, axis=1)
    # +1 where a run starts and -1 just after it ends; nonzero() lists both row by row, left to right,
    # so the k-th start and the k-th end are the two ends of the same run
    r, s = np.nonzero(d == 1)
    _, e = np.nonzero(d == -1)
    out = np.zeros(a.shape[0], dtype=int)
    np.maximum.at(out, r, e - s)   # a row keeps its longest run; a row with none stays 0
    return out


def _ink_runs(ink, rows: slice, cols: slice, across: int, down: int) -> tuple:
    """(which rows have ink in them within the box's columns, which columns have ink within the box's
    rows), from the ink of the box's own window (`across` x `down` pixels of the grey plane). A row
    counts when a few of its pixels are ink: one letter is enough, and a row of nothing is what the walk
    below stops at.

    A stroke that runs unbroken across nearly the whole window is the window's frame, not writing, and
    is left out of the test across it: a row of the box's band that is such a line (a toolbar's lower
    edge, a rule the width of the page) does not count for the columns, and a column that runs down
    nearly the whole window (a pane divider, a scrollbar's track) does not count for the rows. One such
    row in the band otherwise puts ink in every column, the walk sideways runs to both edges of the
    window, the guard turns down a growth that wide, and the crop is left as the box was: measured on a
    4K screen where the model's box touched the browser's toolbar, the problem's code line was cut off
    at 87 per cent this way. Only the test across the stroke ignores it. A table's rules still carry the
    walk from one row of the table to the next, which is the same direction the rule runs."""
    import numpy as np

    band = ink[rows, :]
    flat = _longest_runs(band) >= SNAP_FRAME * max(1, across)
    # all the band's rows being frame leaves no writing to read sideways: no ink, so no growth that way
    col_ink = band[~flat].mean(axis=0) > 0.004 if (~flat).any() else np.zeros(ink.shape[1], dtype=bool)
    tall = ink[:, cols]
    upright = _longest_runs(tall.T) >= SNAP_FRAME * max(1, down)
    row_ink = tall[:, ~upright].mean(axis=1) > 0.004 if (~upright).any() else np.zeros(ink.shape[0], dtype=bool)
    return row_ink, col_ink


def _push(ink, start: int, step: int, limit: int, blank: int) -> tuple:
    """Walk out from `start` while there is still ink, and stop at a run of `blank` without any.

    Gives back (the last row or column that had ink in it, whether a blank run is what stopped it).
    The second half matters: a walk that ran into the window's edge or the growth cap instead did
    not find where the writing ends, it only ran out of room, and that is the screen the text
    detector exists for."""
    i, last = start, start
    while 0 <= i < len(ink) and (i < limit if step > 0 else i > limit):
        run = ink[i:i + blank] if step > 0 else ink[max(0, i - blank):i]
        if not run.size or not run.any():
            return last, True
        if ink[i]:
            last = i
        i += step
    return last, False


def snapped(img, box, window=None, gap: float = SNAP_GAP, grow: float = SNAP_GROW,
            down: float | None = None) -> tuple:
    """(`box` pushed out to the edges of the block of content it sits in, whether that edge was found).

    The model draws its box by eye and often lands inside a paragraph: the margin around it picks up
    whatever it reaches and the rest of the problem is cut away, which is a worse question asked for
    the same money. The page itself says where the block ends, in the blank gutters around it, so the
    box is walked outward on each side while the rows or columns it meets still have ink. It cannot
    leave its window, cannot grow past `grow` times its own size, and only ever grows, so a box
    pointing somewhere wrong cannot make the crop worse than it already was.

    The second half of what comes back says whether every side ran into blank space. A side that
    stopped because it reached the window or the growth cap did not find the end of the writing, and
    a box that ends that way is the one the text detector is for.

    `down`, when given, is how deep a blank run has to be to stop the walk below the box (the other
    three sides keep `gap`): READ_REACH, for a crop that is read on this PC.
    """
    import numpy as np

    x0, y0, x1, y1 = box
    wx0, wy0, wx1, wy1 = window or (0.0, 0.0, 1.0, 1.0)
    # read at about a thousand pixels wide: enough to see where the text stops, and a fraction of
    # the work of reading the screen as it came in
    k = min(1.0, 1000 / max(1, img.width))
    small = img.convert("L").resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.BILINEAR)
    g = np.asarray(small, dtype=np.float32)
    h, w = g.shape
    cols = slice(max(0, int(x0 * w)), max(1, int(x1 * w)))
    rows = slice(max(0, int(y0 * h)), max(1, int(y1 * h)))
    if rows.stop <= rows.start or cols.stop <= cols.start:
        return box, False
    # The colour the block is written on, read over a band around the box and inside its window.
    # Not over the box alone, which can be more letters than page, and then the middle value is the
    # letters. Not over the whole screen either: with no window known, a dark desktop behind a light
    # document makes the document's own background count as ink, the walk never meets a gutter and
    # runs to its limit. Half the box's size on each side is still the same surface.
    ex, ey = (x1 - x0) * 0.5, (y1 - y0) * 0.5
    br = slice(max(0, int(max(wy0, y0 - ey) * h)), max(1, int(min(wy1, y1 + ey) * h)))
    bc = slice(max(0, int(max(wx0, x0 - ex) * w)), max(1, int(min(wx1, x1 + ex) * w)))
    page = float(np.median(g[br, bc])) if br.stop > br.start and bc.stop > bc.start \
        else float(np.median(g[rows, cols]))
    # Ink is whatever differs from the page either way, not only what is darker than it. An editor is
    # usually dark with light letters, and reading only "darker than the page" there marks the background
    # itself as ink and the walk never finds a gutter: measured on one paragraph in a window, a light page
    # snapped the box to 1.5 times its size and the same paragraph on a dark page to 5.7, the whole window.
    ink = np.abs(g - page) > 12
    # Only the box's own window is read. The walk cannot leave it anyway, and another window's background
    # is a different colour that would otherwise read as one long stroke of ink across this window's rows.
    wr = slice(max(0, int(wy0 * h)), max(1, math.ceil(wy1 * h)))
    wc = slice(max(0, int(wx0 * w)), max(1, math.ceil(wx1 * w)))
    mine = np.zeros_like(ink)
    mine[wr, wc] = True
    ink &= mine
    row_ink, col_ink = _ink_runs(ink, rows, cols, wc.stop - wc.start, wr.stop - wr.start)
    gy, gx = max(2, int(gap * h)), max(2, int(gap * w))
    gd = max(2, int((down or gap) * h))   # below the box: a deeper blank run when one is asked for
    gh, gw = (y1 - y0) * grow, (x1 - x0) * grow
    # each side: no further than the window, no further than the growth allows, no further than ink
    t0, s0 = _push(row_ink, int(y0 * h), -1, int(max(wy0, y0 - gh) * h), gy)
    t1, s1 = _push(row_ink, int(y1 * h), 1, int(min(wy1, y1 + gh) * h), gd)
    t2, s2 = _push(col_ink, int(x0 * w), -1, int(max(wx0, x0 - gw) * w), gx)
    t3, s3 = _push(col_ink, int(x1 * w), 1, int(min(wx1, x1 + gw) * w), gx)
    ny0 = max(wy0, y0 - gh, t0 / h)
    ny1 = min(wy1, y1 + gh, t1 / h)
    nx0 = max(wx0, x0 - gw, t2 / w)
    nx1 = min(wx1, x1 + gw, t3 / w)
    # all four sides have to have met a gutter for the block to have been found rather than run out of
    return ((min(nx0, x0), min(ny0, y0), max(nx1, x1), max(ny1, y1)), s0 and s1 and s2 and s3)


def _blocks(lines, gx: float = 0.02, gy: float = 0.03) -> list:
    """The detector's text lines joined into blocks: lines within a gutter of each other are one
    piece of writing, and a block is the rectangle around them. Only where the lines are is used,
    never what the detector thinks they say: the bundled model reads Chinese and English, so on a
    Korean screen its text is noise while its boxes are still on the text.

    The vertical gutter is the one that matters, and it has to be about two lines of text high: a
    heading, a blank line and the question under it are one block to the eye and must be one here.
    Measured over 60 settings of these three numbers on the 102 recorded boxes, every setting with
    gy at 0.03 holds the whole problem on 99 of them and no setting does better; at a line's height
    it is 98, because the blank line between a heading and its question splits them."""
    out: list = []
    for ln in sorted((list(b) for b in lines), key=lambda b: (b[1], b[0])):
        for blk in out:
            if (blk[0] - gx < ln[2] and ln[0] - gx < blk[2]) and (blk[1] - gy < ln[3] and ln[1] - gy < blk[3]):
                blk[0], blk[1] = min(blk[0], ln[0]), min(blk[1], ln[1])
                blk[2], blk[3] = max(blk[2], ln[2]), max(blk[3], ln[3])
                break
        else:
            out.append(list(ln))
    joined = True
    while joined:        # two lines far apart can be bridged by a third read after both of them
        joined = False
        for i in range(len(out)):
            for j in range(len(out) - 1, i, -1):
                a, b = out[i], out[j]
                if (a[0] - gx < b[2] and b[0] - gx < a[2]) and (a[1] - gy < b[3] and b[1] - gy < a[3]):
                    out[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    out.pop(j)
                    joined = True
    return out


def block_grown(box, lines, window=None, hit: float = 0.25, grow: float = SNAP_GROW) -> tuple:
    """`box` grown to every block of text it lands on. A block counts when the box covers at least
    `hit` of it, so a box that merely clips the edge of a sidebar does not drag the sidebar in.

    Held to the same two limits as the ink walk, because the detector reads the whole screen and
    knows nothing of windows: the result stays inside the window the box was placed in, and may not
    add more than `grow` times the box's own size. Without them a line of text that runs across a
    window edge pulls the neighbour in, and the crop goes out holding somebody else's window."""
    x0, y0, x1, y1 = box
    wx0, wy0, wx1, wy1 = window or (0.0, 0.0, 1.0, 1.0)
    lo = (max(wx0, x0 - (x1 - x0) * grow), max(wy0, y0 - (y1 - y0) * grow))
    hi = (min(wx1, x1 + (x1 - x0) * grow), min(wy1, y1 + (y1 - y0) * grow))
    out = list(box)
    for blk in _blocks(lines):
        ox = max(0.0, min(x1, blk[2]) - max(x0, blk[0]))
        oy = max(0.0, min(y1, blk[3]) - max(y0, blk[1]))
        if ox * oy >= hit * max(1e-9, (blk[2] - blk[0]) * (blk[3] - blk[1])):
            out = [min(out[0], blk[0]), min(out[1], blk[1]), max(out[2], blk[2]), max(out[3], blk[3])]
    return (min(x0, max(lo[0], out[0])), min(y0, max(lo[1], out[1])),
            max(x1, min(hi[0], out[2])), max(y1, min(hi[1], out[3])))


def grow_to_block(img, box, window, lines=None, final=lambda b: b, size=None,
                  down: float | None = None) -> tuple:
    """`box` grown to the piece of writing it sits in, by whatever ways of looking are available,
    and only as far as that is free.

    Two ways of finding where the writing ends: walking the ink out to the gutters around it, which
    costs one grey plane of a thousand pixels, and the text detector's own line boxes. Each is judged
    on its own against the crop the box alone would have given (`final` turns a box into that crop),
    and the ones that cost no detail are taken together. The union is checked again, because two free
    growths can add up to one that is not.

    `lines` is something to call, not a list, because the detector costs about a second of CPU and
    is not always installed. It is reached for only when the walk ran out of room on some side
    instead of meeting a gutter, which is the screen that has no gutter a grey plane can see: on
    the 102 recorded boxes that is 18 of them. Its answer is kept on the frame as well, so the two
    or three crops one answer cuts pay for it at most once.

    `down` (READ_REACH) is for a crop that is read on this PC and never sent: once the box has grown,
    its bottom goes on down past blank runs shorter than that, across the columns the crop is cut
    over, as far as the crop's letters stay as large as they were. The guard's cap on the crop's area
    is not asked of it, since that cap is about what leaves this PC.
    """
    w, h = size or img.size

    def detail(b) -> float:
        """How much of its resolution the crop `b` keeps once it is shrunk to go out: 1 is all."""
        return min(1.0, CROP_MAX_SIDE / max(1.0, (b[2] - b[0]) * w, (b[3] - b[1]) * h))

    def free(b) -> bool:
        """A growth is free when the problem's letters come out no smaller than they would have, and
        the crop is still a crop."""
        c = final(b)
        return detail(c) >= detail(plain) - 1e-9 and (c[2] - c[0]) * (c[3] - c[1]) <= SNAP_MAX_AREA

    plain = final(box)
    keep = [tuple(box)]
    ink, found_gutter = snapped(img, box, window)
    if ink != tuple(box) and free(ink):
        keep.append(ink)
    if not found_gutter and lines is not None:        # the ink found no gutter: pay for the detector
        found = lines()
        if found:
            blk = block_grown(box, found, window)
            if blk != tuple(box) and free(blk):
                keep.append(blk)
    if len(keep) == 1:
        res = tuple(box)
    else:
        out = (min(k[0] for k in keep), min(k[1] for k in keep),
               max(k[2] for k in keep), max(k[3] for k in keep))
        res = out if free(out) else max(keep[1:], key=lambda k: (k[2] - k[0]) * (k[3] - k[1]))
    if down:
        c = final(res)
        # walked from the grown box's bottom, over the columns the crop is cut across: a short example line
        # at the left edge of a pane is outside the columns of a box the model drew to its right
        deep = snapped(img, (c[0], c[1], c[2], res[3]), window, down=down)[0][3]
        if deep > res[3]:
            lower = (res[0], res[1], res[2], deep)
            if detail(final(lower)) >= detail(c) - 1e-9:   # its letters come out no smaller than they did
                res = lower
    return res


def padded(box, pad=CROP_PAD) -> tuple:
    """`box` grown by `pad`: one fraction for every side, or (left, top, right, bottom)."""
    x0, y0, x1, y1 = box
    l, t, r, b = (pad,) * 4 if isinstance(pad, (int, float)) else pad
    return (max(0.0, x0 - l), max(0.0, y0 - t), min(1.0, x1 + r), min(1.0, y1 + b))


# The text detector is opt-in, off by default, and not in the image (SIDENOTE_CROP_SNAP=detector,
# server/requirements-ocr.txt). It is here because a screen whose writing has no gutter the grey
# plane can see is a real thing, not because it earns its keep: on the 102 recorded boxes the ink
# walk alone holds the whole problem on 99, and the detector, reached on 18 of them, holds it on
# none more, for about 1.2 s of CPU each time it is reached and some 70 MB in the image. (It took
# 98 to 99 before the walk left a window's frame lines out, and that one crop was such a line.) Its
# answer is kept on the frame, because one answer cuts two or three crops of the same screen.
_detector: list = []
_detector_lock = threading.Lock()


def text_lines(frame, img) -> list | None:
    """Where the lines of text on this frame are, as screen fractions, or None when there is no
    detector or no reason to pay for one. Kept on the frame, so several crops of one screen ask once."""
    if CONFIG.crop_snap != "detector":
        return None
    have = getattr(frame, "ocr_lines", None)
    if have is None:
        from .ocr_gate import OcrTextExtractor
        with _detector_lock:           # crops run in threads: two can reach this together
            if not _detector:
                try:
                    _detector.append(OcrTextExtractor())
                except Exception as exc:   # not installed in this image: the ink walk stands alone
                    log.warning("text detector unavailable (%s); the crop grows by its ink alone", exc)
                    _detector.append(None)
        if _detector[0] is None:
            return None
        w, h = img.size
        try:
            _, boxes = _detector[0].run(img)
            have = [[b[0] / w, b[1] / h, b[2] / w, b[3] / h] for b in boxes]
        except Exception as exc:       # pragma: no cover - engine dependent
            # Written down as "nothing on this screen", not left unset: one answer cuts two or three
            # crops of the same frame, and a second of work that already failed is a second wasted.
            log.warning("text detector failed (%s); the crop grows by its ink alone", exc)
            have = []
        try:
            frame.ocr_lines = have
        except Exception:              # a frame that does not carry the field: ask again next time
            pass
    return have or None


def crop_image(frame, box, pad=CROP_PAD, max_side: int = CROP_MAX_SIDE,
               own_window: bool = True, snap: bool = False, reach: float | None = None) -> tuple[str, tuple, tuple]:
    """Cut `box` (screen fractions) out of the frame at the resolution it arrived in, with a margin,
    inside the window that shows it (unless that is switched off) and inside the box the user drew (if
    any). Parts of other windows in front of that window are painted over. A box the user drew is the
    user's choice of area: it is cut as drawn, whatever windows it covers. `own_window=False` cuts the box
    as it is, over any windows: only for an image that stays on this PC. Returns (PNG base64, the box
    actually cut, its size in pixels). Runs in a thread.

    `snap` grows the box to the piece of writing it lands in first (grow_to_block). It belongs to a
    box the model drew around a problem, which it draws by eye and often lands inside a paragraph.
    It must stay off for a region that already means exactly what it says: the halves of a screen,
    the whole view, and above all the box drawn by hand. `reach` (READ_REACH) lets the
    grown box go on down past the gaps between examples: only for a crop that stays on this PC."""
    img = Image.open(io.BytesIO(frame.full_png))
    img.load()
    img = img.convert("RGB")
    drawn = SETTINGS.get("roi_box")
    windows = getattr(frame, "windows", None) if own_window and SETTINGS.get("roi_windows") and not drawn else None
    # `box` stays the box the model placed from here on. Which window the crop belongs to, and
    # which windows count as in front of it, are both answered by that box and not by the grown
    # one: a grown box that reaches over a neighbour would otherwise pick the neighbour's window,
    # and the crop would come back holding none of what the model pointed at. It is also the box
    # the guard inside grow_to_block measured against, so the crop cut here is the crop it judged.
    area = box
    if snap and not drawn and CONFIG.crop_snap != "off":
        win = None
        if windows:
            i = window_of(box, windows)
            if i is not None:
                win = tuple(windows[i])
        area = grow_to_block(img, box, win, lines=lambda: text_lines(frame, img),
                             final=lambda b: clip_to_window(padded(b, pad), windows, inner=box),
                             size=img.size, down=reach)
    cut = clip_to_window(padded(area, pad), windows, inner=box)
    if drawn:
        cut = (max(cut[0], drawn[0]), max(cut[1], drawn[1]), min(cut[2], drawn[2]), min(cut[3], drawn[3]))
        if cut[2] - cut[0] < 0.01 or cut[3] - cut[1] < 0.01:   # the box is outside what was drawn: use that
            cut = tuple(drawn)
    w, h = img.size
    # rounded inward: a window edge that falls between two pixels never brings in the neighbour's column
    x0, y0 = min(w - 1, math.ceil(cut[0] * w - 1e-6)), min(h - 1, math.ceil(cut[1] * h - 1e-6))
    px = (x0, y0, max(x0 + 1, int(cut[2] * w)), max(y0 + 1, int(cut[3] * h)))
    piece = img.crop(px)
    if windows:
        paint = ImageDraw.Draw(piece)
        for r in in_front(cut, windows, inner=box):   # e.g. a messenger over the problem's window
            paint.rectangle((int(r[0] * w) - px[0], int(r[1] * h) - px[1], math.ceil(r[2] * w) - px[0] - 1,
                             math.ceil(r[3] * h) - px[1] - 1), fill=(128, 128, 128))
    piece = _fit(piece, max_side)
    return _b64(piece), cut, piece.size


def shown_box(frame, box) -> tuple | None:
    """What a crop of `box` takes (crop_image's own answer), for the panel to draw. None when that cannot be told."""
    try:
        return crop_image(frame, box, CROP_PAD, CROP_MAX_SIDE, True, True)[1]
    except Exception:
        log.debug("no crop to show", exc_info=True)
        return None


def sharpness(frame, box) -> float:
    """How much of its resolution a crop of `box` (with its margin) keeps at CROP_MAX_SIDE: 1 = all of it."""
    b = padded(box)
    return min(1.0, CROP_MAX_SIDE / max(1.0, (b[2] - b[0]) * frame.width, (b[3] - b[1]) * frame.height))


def box_first(frame, box) -> bool:
    """Whether the problem is written out from the model's box before the whole screen when the box places nothing:
    on a screen large enough that the model gets its text at under half size (halves_help) and with the box's crop
    keeping at least 1.2 times the whole screen image's resolution, the margin halves_help asks of the halves.
    Measured (scratch/local-llm-bench/span_payload.py, span_sharp.py) with one analysis in mind:
    a coding problem on a 4K screen whose box ran into the next window fell to the local model for 169 s while the agent
    was on. On the 4K desktops of section 11 the whole screen came back with nothing 6 times of 6 at 100 and 125 per
    cent and lost 2 or 3 of 7 key phrases each time at 150 per cent, while a box of that size (a crop at 0.66 of the
    resolution, the screen at 0.42) gave all 7, 9 times of 9. At 1440p and 1080p the whole screen gave the problem
    whole every time, and a box half in another window lost the middle of a statement it ran off or wrote out the
    code in the editor beside the problem, so there it is not read."""
    return (box is not None and halves_help(frame)
            and sharpness(frame, box) >= 1.2 * min(1.0, CONFIG.max_image_width / max(1, frame.width)))


def halves_help(frame) -> bool:
    """A landscape screen 3200 px or wider whose halves keep at least 1.2 times the resolution of the screen image
    the model reads (SIDENOTE_MAX_IMAGE_WIDTH wide). Measured on 16:9 4K only; a square screen gains nothing, and a
    tall one is left alone (its screen image keeps its whole width up to that cap)."""
    w, h = getattr(frame, "width", 0), getattr(frame, "height", 0)
    return (w >= HALVES_AT and w > h
            and halves_sharpness(frame) >= 1.2 * min(1.0, CONFIG.max_image_width / w))


def _half_span(frame) -> float:
    """The share of the long side each half covers: half of it, or as much as the short side when that keeps
    the same sharpness (3840x2160: 2160 px each, overlapping by 480 px, so a line on the seam is whole in one)."""
    long, short = max(frame.width, frame.height), min(frame.width, frame.height)
    return min(1.0, max(0.5, short / long))


def halves_sharpness(frame) -> float:
    """sharpness() for the halves of a large screen (halves())."""
    return min(1.0, CROP_MAX_SIDE / max(_half_span(frame) * max(frame.width, frame.height),
                                        min(frame.width, frame.height)))


def halves(frame) -> list[str]:
    """The two halves of a large screen (left and right, or top and bottom when it stands tall), overlapping
    where that costs nothing (_half_span), each at up to CROP_MAX_SIDE, for the local thinking pass when the
    problem was not placed: a 4K screen read at 1600 px loses its small text (the crontab on the 4K desktop of
    section 11 came out wrong 3 of 4 times at 150% scaling, 4 of 4 at 100%). They stay on this PC. Runs in a
    thread."""
    span = _half_span(frame)
    if frame.height > frame.width:
        parts = ((0.0, 0.0, 1.0, span), (0.0, 1.0 - span, 1.0, 1.0))
    else:
        parts = ((0.0, 0.0, span, 1.0), (1.0 - span, 0.0, 1.0, 1.0))
    return [crop_image(frame, p, 0.0, CROP_MAX_SIDE, False)[0] for p in parts]


def thumb_url(b64png: str, width: int = 360) -> str:
    img = Image.open(io.BytesIO(base64.b64decode(b64png)))
    img = img.convert("RGB")
    if img.width > width:
        img = img.resize((width, max(1, int(img.height * width / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def _in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


# ---------- what may go out ----------

# Numbers shaped like someone's personal data: a resident registration number, a mobile or landline
# number, a card number (a card network's first digits and the Luhn check, its groups split by dashes or
# not at all) and a bank account (three or four groups of digits split by dashes, 10 to 14 in all, one
# of them at least 4 long, not a date). The problem written out from the whole screen can bring them in
# from another window, such as a messenger beside the problem. ASCII classes, so a Korean particle written
# onto a number ("010-1234-5678" with a particle attached) still ends it; digits after a decimal point are a fraction.
_DASH = "-\u2010-\u2015\u2212\uff0d"          # the hyphen, the Unicode dashes, the minus sign, the full-width hyphen
_START = rf"(?<![{_DASH}\w])(?<!\d[.,])"
_END = rf"(?![{_DASH}\w])(?![.,]\d)"
_SEP = rf"(?:[ \t]?[{_DASH}.][ \t]?|[ \t])"     # a dash or a dot, spaces around it or not, or a space
_RRN = re.compile(rf"{_START}\d{{6}}[ \t]?[{_DASH}][ \t]?[1-8]\d{{6}}{_END}", re.ASCII)
_RRN_SPACED = re.compile(rf"{_START}\d\d(\d\d)(\d\d)[ \t][1-8]\d{{6}}{_END}", re.ASCII)   # a birth date first
_MOBILE = re.compile(rf"{_START}(?:\+82{_SEP}?(?:\(0\))?|\(?0)1[016-9]\)?{_SEP}?\d{{3,4}}{_SEP}?\d{{4}}{_END}", re.ASCII)
_LANDLINE = re.compile(rf"{_START}\(?0(?:2|[3-6][1-5])(?:\)[ \t]?|{_SEP})\d{{3,4}}{_SEP}\d{{4}}{_END}", re.ASCII)
_CARD = re.compile(rf"{_START}(?:2[2-7]\d\d|[3-69]\d{{3}})([{_DASH}]?)\d{{4}}\1\d{{4}}\1\d{{4}}{_END}", re.ASCII)
_AMEX = re.compile(rf"{_START}3[47]\d\d([{_DASH}]?)\d{{6}}\1\d{{5}}{_END}", re.ASCII)
_ACCOUNT = re.compile(rf"{_START}\d{{2,6}}(?:[{_DASH}]\d{{2,7}}){{2,3}}{_END}", re.ASCII)
_DATE = re.compile(rf"(?:19|20)\d\d[{_DASH}](?:0[1-9]|1[0-2])[{_DASH}](?:0[1-9]|[12]\d|3[01])(?!\d)", re.ASCII)


def _luhn(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = int(c) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def personal_data(text: str) -> bool:
    """`text` holds a number shaped like someone's personal data (see above). A phone number made of
    0s and 1s only is a bit string; a problem about phone numbers is held back too."""
    if _RRN.search(text) or _LANDLINE.search(text):
        return True
    if any(set(_digits(m.group())) - {"0", "1"} for m in _MOBILE.finditer(text)):
        return True
    if any(1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31 for m in _RRN_SPACED.finditer(text)):
        return True
    if any(_luhn(_digits(m.group())) for p in (_CARD, _AMEX) for m in p.finditer(text)):
        return True
    for m in _ACCOUNT.finditer(text):
        groups = re.split(f"[{_DASH}]", m.group())
        if 10 <= sum(map(len, groups)) <= 14 and max(map(len, groups)) >= 4 and not _DATE.match(m.group()):
            return True
    return False


# ---------- solving ----------

def _searches(trace) -> list:
    return [{"to": "search" if name == "web_search" else "page", "what": arg} for name, arg in trace or ()]


# What the first pass found on the web goes to the agent with the problem. The agent runs here with no tools, and a question
# about a current version reached it as the words alone: on a rehearsed spoken question it declined, wrote
# a Bash call out as text with "cannot confirm" under it, or ran past the scene, while the first pass had already searched.
FACTS_MAX = 8          # search results that go along, at most
FACT_PAGE_CHARS = 1500  # of a page the first pass fetched


def searched_facts(messages) -> list:
    """The results of the web searches and page fetches in a first pass's conversation (FastResult.messages), as
    [{"title", "url", "snippet"}]. Results it never got (an error, nothing found) are left out. Read first are the
    official release pages a version search read for itself (search.py, "page"), then the pages the pass fetched,
    then the search snippets, each address once and with its date: in the order they came, a second search's
    snippets filled the eight places and the official page, the one holding the version asked about, was cut off."""
    pages, fetched, snippets = [], [], []
    for m in messages or ():
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        try:
            data = json.loads(m.get("content") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        page = data.get("page")
        if isinstance(page, dict) and page.get("text") and page.get("url"):   # read from the official source
            pages.append({"title": str(page.get("title") or page["url"])[:200], "url": str(page["url"]),
                          "snippet": re.sub(r"\s+", " ", str(page["text"]))[:FACT_PAGE_CHARS]})
        for it in data.get("results") or ():
            if isinstance(it, dict) and (it.get("snippet") or it.get("title")):
                date = str(it.get("date") or "")[:10]
                snippets.append({"title": str(it.get("title") or "")[:200] + (f" ({date})" if date else ""),
                                 "url": str(it.get("url") or ""), "snippet": str(it.get("snippet") or "")[:400]})
        if data.get("text") and data.get("url"):          # a page it fetched
            fetched.append({"title": str(data.get("title") or data["url"])[:200], "url": str(data["url"]),
                            "snippet": re.sub(r"\s+", " ", str(data["text"]))[:FACT_PAGE_CHARS]})
    out, seen = [], set()
    for f in pages + fetched + snippets:
        if f["url"] and f["url"] in seen:
            continue
        seen.add(f["url"])
        out.append(f)
    return out[:FACTS_MAX]


def facts_note(facts: list, today: str, web: bool = True) -> str:
    """The search results as a block after the problem, with what the agent has and has not got to go on: with `web`
    (a question about the present) it gets the web search with them and nothing else (_agent_solve); without it,
    they are what the first pass looked up on its way (an error message, an option), to use as it sees fit."""
    lines = [f"{i}. {f['title']} - {f['snippet']} ({f['url']})" for i, f in enumerate(facts, 1)]
    if not web:
        return (f"\n\n[검색 결과] 오늘은 {today} 입니다. 아래는 이 PC 가 이 문제를 보며 웹에서 찾은 결과입니다. 답에 "
                "필요하면 참고하세요.\n" + "\n".join(lines))
    return (f"\n\n[검색 결과] 오늘은 {today} 입니다. 아래는 이 PC 가 방금 웹에서 찾은 결과입니다. 지금 시점의 사실(최신 "
            "버전, 릴리스, 가격)을 아래 결과로 답할 수 있으면 그대로 답하고, 결과가 없거나 오래됐거나 서로 맞지 않으면 웹 "
            "검색으로 확인하세요. 쓸 수 있는 도구는 웹 검색 하나이고, 명령 실행은 할 수 없습니다.\n" + "\n".join(lines))


# A question about the present: the latest version or release (search.py's VERSION_Q, the searches it reads an
# official page for), and a price, a rate or the news as of now. Only these send the agent to the web turn (a fresh
# process at low effort with the web search): every other search of the first pass (an error message, an option)
# sent it there too, off the warm session and the effort set on the panel.
PRESENT_Q = re.compile(r"(latest|newest|current|최신|현재)[^\n]{0,40}(version|release|릴리스|버전)"
                       r"|(version|release|릴리스|버전)[^\n]{0,20}(latest|newest|최신)"
                       r"|(오늘|지금|현재|최근|today|now|current)[^\n]{0,30}(가격|환율|시세|뉴스|소식|price|rate|news)", re.I)


def present_question(messages) -> bool:
    """Whether a first pass's searches (FastResult.messages) asked about the present: a query PRESENT_Q reads as one,
    or a result with an official release page read for it."""
    for m in messages or ():
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        try:
            data = json.loads(m.get("content") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and (data.get("page") or PRESENT_Q.search(str(data.get("query") or ""))):
            return True
    return False


# Tool calls the agent writes out as text when it wants a tool and has none (seen: a Bash curl before "cannot confirm"):
# they are no part of an answer, and on the card they read as garbage. Only whole call blocks, and never inside a
# code block: an answer's own XML may well hold a <parameter> tag.
TOOL_MARKUP_RE = re.compile(r"^[^\S\n]*(?:<function_calls>.*?</function_calls>|<invoke\b[^>]*>.*?</invoke>)[^\S\n]*$",
                            re.S | re.I | re.M)
FENCE_RE = re.compile(r"(```.*?(?:```|$))", re.S)


def strip_tool_markup(text: str) -> str:
    """The answer without tool calls written out as text (and the blank lines they leave)."""
    if not text or "<invoke" not in text and "<function_calls" not in text:
        return text
    parts = FENCE_RE.split(text)          # code blocks at the odd places, left as they are
    out = "".join(p if i % 2 else TOOL_MARKUP_RE.sub("", p) for i, p in enumerate(parts))
    return re.sub(r"\n{3,}", "\n\n", out).strip() if out != text else text


class ToolCallWritten(RuntimeError):
    """The agent wrote a tool call out as text: it has no tools here, or not that one. Left alone it went on writing the
    same `echo test` Bash call for 108 s, to the card, until it was paused (a retry)."""


# A call begins a line of its own: `<invoke name=...>` inside a sentence or inline code is an answer explaining the
# notation, which was taken for a call and its turn stopped
TOOL_OPEN_RE = re.compile(r"^[^\S\n]*<(?:invoke\b|function_calls\b)", re.I | re.M)
TOOL_DONE_RE = re.compile(r"</(?:invoke|function_calls)>", re.I)


def _outside_code(text: str) -> str:
    """The text without its code blocks (one still open at the end counts): where written-out calls are looked for."""
    return "".join(part for i, part in enumerate(FENCE_RE.split(text)) if i % 2 == 0)


def _shown_part(whole: str) -> str:
    """What of the text so far may go on the card: no tool call written out, nothing from the start of one still
    being written (an unclosed `<invoke`), and no `<` at the very end that may yet turn into one."""
    parts = FENCE_RE.split(whole)
    out = []
    for i, part in enumerate(parts):
        if i % 2:                                  # a code block: the answer's own, as it is
            out.append(part)
            continue
        part = TOOL_MARKUP_RE.sub("", part)
        opened = TOOL_OPEN_RE.search(part)
        if opened:                                 # a call still being written: nothing from it on
            out.append(part[:opened.start()])
            break
        if i == len(parts) - 1:                    # the end of the text so far
            lt = part.rfind("<")
            if lt >= 0 and ">" not in part[lt:] and len(part) - lt <= len("<function_calls"):
                part = part[:lt]
        out.append(part)
    return "".join(out)


def guarded(on_delta):
    """on_delta for the agent's answer: what it writes goes on to the card, but not a tool call written out as text, and
    a complete one stops the turn (ToolCallWritten; the CLI's process is killed with it), so it cannot go on writing
    the same call again and again."""
    seen, sent = [], [0]                           # everything so far; how much of what may be shown went on

    async def feed(text: str) -> None:
        seen.append(text)
        whole = "".join(seen)
        outside = _outside_code(whole)
        opened = TOOL_OPEN_RE.search(outside)
        # a call is complete with its parameter and its closing tag after the line that opened it
        if (opened and "<parameter" in outside[opened.start():]
                and TOOL_DONE_RE.search(outside, opened.start())):
            raise ToolCallWritten(t("The agent called a tool it cannot use and was stopped", agent=agent_name()))
        shown = _shown_part(whole)
        if len(shown) > sent[0]:
            await on_delta(shown[sent[0]:])
            sent[0] = len(shown)
    return feed


LIFTED_HEAD_RE = re.compile(r"(?<![A-Za-z0-9_])TYPE:[^\S\n]*[a-zA-Z_]+[^\S\n]*\n[^\S\n]*ANSWER:")


THOUGHT_LINE = 160   # characters of the thinking the card shows at most


def thought_line(tail: str) -> str:
    """The last sentence the thinking finished, as one line for the card, cut at THOUGHT_LINE from its start; the
    whole tail when no sentence has finished in it. Not the sentence being written: it changed every 1.5 s, a few
    words at a time, which reads as flicker. Markdown marks and line breaks go; "" for nothing."""
    flat = re.sub(r"[*_`#>]+", "", re.sub(r"\s+", " ", tail or "")).strip()
    if not flat:
        return ""
    ends = [m.end() for m in re.finditer(r"[.!?。](?=\s|$)", flat)]
    if ends:
        flat = flat[ends[-2] if len(ends) > 1 else 0:ends[-1]]
    flat = flat.strip()
    return flat if len(flat) <= THOUGHT_LINE else flat[:THOUGHT_LINE - 1].rstrip() + "…"


def lift_head(text: str) -> str:
    """The answer from its `TYPE:` on, when a note runs into it on the same line ("Need current info; search.TYPE:
    short", the agent at low effort with the web search): head_start finds a head only at the start of a
    line, so the answer read as declined. Only within the first 300 characters and only when there is no head."""
    if not text or head_start(text) is not None:
        return text
    # A word of its own, with its answer line under it, outside a code block: a YAML `CMAKE_BUILD_TYPE: Release` and
    # a refusal saying "(TYPE: none, as a formality)" were lifted, the one cutting a block open, the other turning a
    # refusal into "nothing to solve"
    m = LIFTED_HEAD_RE.search(text, 0, 400)
    if not m or m.start() >= 300 or text.count("```", 0, m.start()) % 2:
        return text
    return text[m.start():]


def _kb(images) -> int:
    return sum(len(b) * 3 // 4 for b in images) // 1024


DEBUG_FRAMES_KEEP = 8   # screens kept by SIDENOTE_DEBUG_FRAMES, oldest dropped (a few MB each)


def _keep_frames(seq: int, shown: str, frame) -> None:
    """Keep the screen behind a "nothing to solve", for working out why. Bounded: these are whole
    screens, and a tool that writes without a limit fills the disk of whoever leaves it on."""
    import base64
    if not os.environ.get("SIDENOTE_LOG_DIR"):   # no log folder (a run with no logs on disk): nowhere to keep them
        return
    out = pathlib.Path(os.environ["SIDENOTE_LOG_DIR"])
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"none_{seq}.png").write_bytes(base64.b64decode(shown))
        if frame is not None:
            (out / f"none_{seq}_frame.png").write_bytes(base64.b64decode(frame.model_b64))
        kept = sorted(out.glob("none_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in kept[DEBUG_FRAMES_KEEP * 2:]:   # two files per analysis
            old.unlink(missing_ok=True)
    except Exception as exc:   # a debugging aid must never be what breaks an answer
        log.warning("could not keep the frame behind an empty answer: %s", exc)


# An agent's own word that its plan's usage is used up, and when it comes back (Claude Code: "You've hit your weekly
# limit · resets Nov 3, 3am (Asia/Seoul)"; Codex 0.165: "You’ve hit your usage limit. ... or try again at 12:26 PM.",
# "... try again at Nov 4th, 2026 11:13 AM." or "... try again later."; the Anthropic API: "Your credit balance is too
# low to access the Anthropic API", a 400 that no waiting mends within the hour either).
# (LIMIT_RE, from analyzer, reads them.) A status code as a number of its own: "turn cost 0.429 usd" rested the agent.
RATE_RE = re.compile(r"rate.?limit(?!er)|too many requests|(?<![\w.])429(?![\w.])", re.I)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}


def limit_until(text: str, now: float) -> float | None:
    """When an agent that said its usage is used up (or that it is rate limited) may be asked again, as a time, or
    None when the error is something else. The time it gives is read in the server's own time zone (the container
    runs in the PC's, compose's TZ); without one, an hour for a used-up plan and two minutes for a rate limit,
    after which one more problem finds out."""
    if not LIMIT_RE.search(text) and not RATE_RE.search(text):
        return None
    local = time.localtime(now)
    # "resets Nov 3, 3am": a date and an hour
    m = re.search(r"resets?\s+(?:on\s+)?([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)",
                  text, re.I)
    if m and m.group(1).lower() in MONTHS:
        hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
        for year in (local.tm_year, local.tm_year + 1):          # a date already past is next year's
            when = time.mktime((year, MONTHS[m.group(1).lower()], int(m.group(2)), hour, int(m.group(4) or 0), 0,
                                0, 0, -1))
            if when > now:
                return when
    # Codex: "try again at Nov 4th, 2026 11:13 AM" (a day further off) or "try again at 12:26 PM" (today, or tomorrow
    # when that time has gone by), in its own process's time zone, which is this container's
    m = re.search(r"try again at\s+(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\s+)?"
                  r"(\d{1,2}):(\d{2})\s*([AP]M)", text, re.I)
    if m:
        hour = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "pm" else 0)
        if m.group(1) and m.group(1).lower() in MONTHS:
            when = time.mktime((int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)), hour, int(m.group(5)),
                                0, 0, 0, -1))
            if when > now:
                return when
        elif not m.group(1):
            when = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, int(m.group(5)), 0, 0, 0, -1))
            return when if when > now else when + 86400
    # "resets 3am": today, or tomorrow when that hour has gone by
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)", text, re.I)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        when = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, int(m.group(2) or 0), 0, 0, 0, -1))
        return when if when > now else when + 86400
    # "try again in 2 hours 13 minutes"
    m = re.search(r"(?:try again|retry|resets?)\s+in\s+(?:(\d+)\s*d\w*)?[\s,]*(?:(\d+)\s*h\w*)?[\s,]*(?:(\d+)\s*m\w*)?",
                  text, re.I)
    if m and any(m.groups()):
        d, h, mi = (int(g or 0) for g in m.groups())
        return now + d * 86400 + h * 3600 + mi * 60
    return now + (3600.0 if LIMIT_RE.search(text) else 120.0)


class Spend:
    """What the agent has cost lately and how many of its answers in a row found nothing.

    Measured with a game on the screen and people talking near the
    microphone: 93 agent turns in 21 minutes, every one of them "nothing to solve", 1.53M input
    tokens, $3.61. Nothing was wrong with any single one of them; the mistake is only visible in
    the row. So the row is what this watches, and what the user asks for always goes."""

    def __init__(self, cfg):
        self.cfg = cfg                # the environment's defaults; the panel's values win below
        self.empty_run = 0            # Agent answers in a row that found nothing
        self.ran = 0                  # how long that row was when it last tripped the brake
        self.cool_until = 0.0         # no automatic sending before this (monotonic-free: time())
        self.spent: deque = deque()   # (when, usd) per answer, oldest first, trimmed to one hour
        # Until when the agent said its plan's usage is used up (or that it is rate limited): it is not asked before
        # then, by the watching or by hand, since it can only fail. Once it was asked 15 times in 17
        # minutes after "You've hit your weekly limit", each time 5 to 20 s before this PC's model began.
        self.limit_until = 0.0
        self.limit_said = ""          # the agent's own words, for the log
        # "plan" (its usage used up: hours or days) or "rate" (too many requests: two minutes). Only a used-up plan has
        # this PC's model stand in and the panel count it down: loading a model of several GB for a two-minute rate
        # limit, under a notice about a usage limit, was the wrong answer to it
        self.limit_kind = ""
        self.path = None              # where the limit and the hour's spend are kept over a restart (load)
        # Whether the agent says what a turn costs. One that never does (Codex signed in with ChatGPT: its answers
        # come with no price) had no answer counted and each cancel or error counted at CUT_SHORT_USD, so 50 cut
        # turns in an hour made $2 and tripped the ceiling on a plan billed by none of them
        self._priced = True
        self.agent = None             # whose reports_cost says it (Pipeline), which its login can change


    def load(self, path) -> None:
        """Keep the limit and the hour's spend in `path`, and take up what it holds: after a restart a plan used up for the
        week was asked again, 5 to 20 s each time, and the hourly ceiling started from nothing."""
        self.path = path
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            # a limit is the agent's that reached it: after a switch to another agent (SIDENOTE_AGENT, or the app finding
            # the other CLI) the new one is asked at once, not after the old one's week is over
            same_agent = saved.get("agent", CONFIG.agent) == CONFIG.agent
            if same_agent and float(saved.get("limit_until", 0)) > time.time():
                self.limit_until, self.limit_said, self.limit_kind = float(saved["limit_until"]), str(saved.get("limit_said", "")), str(saved.get("limit_kind", ""))
            self.spent = deque((float(t), float(c)) for t, c in saved.get("spent", ()) if time.time() - float(t) <= 3600)
        except Exception:   # no file yet, or a broken one: nothing to take up
            pass

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            tmp = self.path.with_suffix(".tmp")      # whole or not at all
            tmp.write_text(json.dumps({"limit_until": self.limit_until, "limit_said": self.limit_said, "limit_kind": self.limit_kind,
                                       "agent": CONFIG.agent, "spent": list(self.spent)}), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:    # a convenience: it costs a repeat after a restart at worst
            log.debug("spend not kept (%s)", exc)

    def limited(self, text: str) -> bool:
        """An agent error: whether it is the plan's limit (then the agent rests until it is over)."""
        until = limit_until(text, time.time())
        if until is None:
            return False
        kind = "plan" if LIMIT_RE.search(text) else "rate"
        if kind == "rate" and self.plan_left():   # a request in flight met a 429: the plan's rest holds, days or not
            return True
        self.limit_until, self.limit_said, self.limit_kind = until, text[:200], kind
        self._save()
        return True

    @property
    def priced(self) -> bool:
        return getattr(self.agent, "reports_cost", True) if self.agent is not None else self._priced

    @priced.setter
    def priced(self, value: bool) -> None:
        self._priced = value

    def plan_left(self) -> str:
        """limit_left() for a used-up plan only (not a rate limit), as the panel says it; empty otherwise."""
        return self.limit_left() if self.limit_kind == "plan" else ""

    def over_ceiling(self) -> bool:
        """The hour's spending has reached the panel's ceiling (an agent that gives prices only)."""
        cap = SETTINGS.get("agent_hourly_usd") if "agent_hourly_usd" in SETTINGS.defs else self.cfg.agent_hourly_usd
        return self.priced and cap > 0 and self.hour_usd() >= cap

    def signed_in(self) -> None:
        """The login file changed (app.engine_watch): another sign-in, perhaps another plan. The rest ends; a limit still
        there says so again on the first try. Kept in .spend.json, the rest outlived restarts with no way to end it but
        the time it named, once a day and a half away."""
        if self.limit_until:
            log.info("agent: a new sign-in; the rest on its limit until %s ends", self.limit_left() or "now")
            self.limit_until, self.limit_said, self.limit_kind = 0.0, "", ""
            self._save()

    def limit_left(self) -> str:
        """While the agent rests on its limit, until when, as the panel says it; empty otherwise."""
        if time.time() >= self.limit_until:
            return ""
        return time.strftime("%m-%d %H:%M", time.localtime(self.limit_until))

    def note(self, cost: float | None, empty: bool) -> None:
        """One agent turn is over. `empty`: it found nothing to solve. `cost`: what it cost, which
        is None for the mock and for a turn whose price never arrived."""
        now = time.time()
        if cost:                                  # 0 and None are both "nothing to count"
            self.spent.append((now, float(cost)))
            self._save()
        # The row either grows by one or starts over: one real answer is enough to clear it.
        self.empty_run = self.empty_run + 1 if empty else 0
        # A streak of 0 turns the brake off entirely (SIDENOTE_CLAUDE_EMPTY_STREAK=0).
        if empty and self.cfg.agent_empty_streak > 0 and self.empty_run >= self.cfg.agent_empty_streak:
            self.cool_until = now + self.cfg.agent_cool_sec
            # `ran` keeps the number for the message; `empty_run` starts over so that one empty
            # answer after the cool-down does not arm the brake again by itself.
            self.ran, self.empty_run = self.empty_run, 0
        self._trim(now)                           # keep the hour's window honest on every note

    def cut_short(self) -> None:
        """A turn stopped before its price arrived: a newer screen, a pause, a cancelled check. The warm session
        is killed with it, so the CLI never says what that turn cost, but its request had been sent and is paid
        for. Not counting it let a screen that keeps changing spend unseen: with two cancels allowed in a row,
        the ceiling saw one turn in three. It counts at the middle of what the last whole
        turns cost, or at CUT_SHORT_USD before there are any; it is neither an empty answer nor a real one, so
        the row of empty answers is left as it is."""
        if not self.priced:
            return
        recent = sorted(c for _, c in list(self.spent)[-10:])
        now = time.time()
        self.spent.append((now, recent[len(recent) // 2] if recent else CUT_SHORT_USD))
        self._save()
        self._trim(now)

    def failed(self, exc: BaseException) -> None:
        """A turn that ended in an error after its request went out: a tool call written out (ToolCallWritten), a turn
        past its budget, an error result. Paid for all the same, and neither an empty answer nor a real one, so the row
        of empty answers is left as it is. They counted as $0, and an error noted as an answer cleared the row."""
        cost = getattr(exc, "cost_usd", None)
        if not cost and error_hint(str(exc)) in ("auth", "limit"):
            return                                # refused before any work: a sign-in, a limit or a rate is not billed
        if not cost:                              # the CLI never said: as a turn cut short
            self.cut_short()
            return
        now = time.time()
        self.spent.append((now, float(cost)))
        self._save()
        self._trim(now)

    def asked(self) -> None:
        """The user asked for something: the row is broken and the brake comes off.

        The hour's spending is deliberately left alone. A question means "answer this one", not
        "forget what the last hour cost"; the ceiling is lifted per request instead, by `by_user`
        in solve()."""
        self.empty_run, self.cool_until = 0, 0.0

    def _trim(self, now: float) -> None:
        """Drop what is older than an hour. The deque is in order, so the front is always oldest."""
        while self.spent and now - self.spent[0][0] > 3600:
            self.spent.popleft()

    def hour_usd(self) -> float:
        """What the last hour has cost. Trims first: this is also called when nothing is running."""
        self._trim(time.time())
        return round(sum(c for _, c in self.spent), 4)

    def blocked(self) -> str:
        """Why the agent should not be asked by itself right now, as a clause, or empty."""
        now = time.time()
        if self.limit_left():
            # which model answers meanwhile is the caller's to say (Pipeline.auto_blocked): with this PC's model off and
            # not standing in, nothing does, and this said it would. A rate limit is not a used-up plan: said as itself
            if self.limit_kind != "plan":
                return t("The agent has had too many requests: not sent for a while, until {until}{who}",
                         agent=agent_name(), until=self.limit_left(), who="")
            return t("The agent's usage limit: not sent until {until}", agent=agent_name(), until=self.limit_left())
        if now < self.cool_until:
            # Round up to the next whole minute, so "1 min" never means "a second or two".
            left = int((self.cool_until - now) / 60) + 1
            return t("Nothing to solve {ran} times in a row: automatic sending to the agent stops for {left} min "
                     "(Reanalyze and questions still go)", ran=self.ran, left=left, agent=agent_name())
        # The panel can move the ceiling while the server runs; the environment is where it starts.
        cap = SETTINGS.get("agent_hourly_usd") if "agent_hourly_usd" in SETTINGS.defs else self.cfg.agent_hourly_usd
        # an agent that gives no prices has nothing for the ceiling to add up (as the setting's help says)
        if self.over_ceiling():    # 0 means the ceiling is turned off
            return t("The agent's cost in the last hour, ${cost}, reached the limit (${cap}): automatic sending stops "
                     "(Reanalyze and questions still go)", cost=f"{self.hour_usd():.2f}", cap=f"{cap:.2f}",
                     agent=agent_name())
        return ""


class Speed:
    """How long each way of answering takes to its first word, from when it is asked: the local thinking pass
    ("think") and the agent ("agent"), the median of the last KEEP of each, in seconds. The rule
    reads it: when the local model would take local_slow_ratio times as long as the agent to start its
    answer, agent answers. Kept in the log folder, so a restart starts from what was measured.

    Before anything is measured, the measured figures: the thinking pass started its answer 17 to 22 s in (the
    median of six runs over the 56 known screens; 30 to 76 s in real use), the agent 3.5 to 12 s
    from the start of the analysis (opus 5.5), the first pass included."""

    KEEP = 15
    DEFAULTS = {"think": 20.0, "agent": 8.0}

    def __init__(self, path=None):
        self.path = path
        self.times: dict[str, list[float]] = {}
        if path is not None:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if "claude" in saved and "agent" not in saved:   # written while the agent was always Claude
                    saved["agent"] = saved.pop("claude")
                self.times = {k: [float(x) for x in v][-self.KEEP:] for k, v in saved.items()
                              if k in self.DEFAULTS and isinstance(v, list)}
            except Exception:   # no file yet, or a broken one: the defaults until something is measured
                pass

    def usual(self, way: str) -> float:
        t = sorted(self.times.get(way) or ())
        return t[len(t) // 2] if t else self.DEFAULTS[way]

    def note(self, way: str, seconds: float) -> None:
        self.times[way] = (self.times.get(way, []) + [round(seconds, 2)])[-self.KEEP:]
        if self.path is None:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.times), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("answer times not saved (%s)", exc)

    def local_slower(self, ratio: float) -> bool:
        """The local thinking pass takes `ratio` times as long as the agent, or longer, to start its answer."""
        return ratio > 0 and self.usual("think") >= ratio * self.usual("agent")

    def timed(self, way: str, on_delta):
        """on_delta that notes how long the first piece of the answer took to come."""
        start = time.monotonic()
        seen = False

        async def wrapped(text: str) -> None:
            nonlocal seen
            if not seen:
                seen = True
                self.note(way, time.monotonic() - start)
            await on_delta(text)
        return wrapped


class Pipeline:
    def __init__(self, engines, hooks: Hooks):
        self.engines = engines
        self.hooks = hooks
        self._roi_empty_said = None
        self.spend = Spend(CONFIG)
        if telemetry.LOG_DIR:
            self.spend.load(pathlib.Path(telemetry.LOG_DIR) / ".spend.json")
        self.spend.agent = engines.agent   # Codex signed in with ChatGPT gives no prices
        self.recent = repeats.Recent()     # the problems answered lately, to tell one seen again (design 88)
        self.speed = Speed(pathlib.Path(telemetry.LOG_DIR) / ".speed.json" if telemetry.LOG_DIR else None)
        self._brake_said = 0.0
        # SETTINGS.on("local_llm") counts the model as on while it stands in for the agent (settings.Settings.stand_in)
        SETTINGS.stand_in = lambda key: self.standing_in() if key == "local_llm" else ""

    # which engines may answer right now
    def _local(self):
        e = self.engines.local
        return e if e is not None and SETTINGS.on("local_llm") and self.hooks.local_ok() else None

    def standing_in(self) -> str:
        """Why the local model, switched off, answers for now, or "": the agent is at its plan's limit ("limit"), its
        sign-in is gone ("signin"), or the spend brake holds ("brake"), and local_fallback is on. The
        rule: at a limit, the answers come from the local model where they can. With the agent
        switched off, or the local model not there or not answering, nothing stands in: both were turned off,
        or there is nothing to stand in with. Reads the switch itself (get), not on(), which asks this."""
        if (SETTINGS.get("local_llm") or not SETTINGS.get("local_fallback") or self.engines.local is None
                or self.engines.agent is None or SETTINGS.get("agent_mode") == "off" or not self.hooks.local_ok()):
            return ""
        if self.spend.plan_left():
            return "limit"
        if not self.hooks.agent_ok():
            return "signin"
        # the hourly cost ceiling, not the cool-down after empty answers in a row: that one means the screens hold
        # nothing (a game, a video), and loading the switched-off model to look at them was what it would have done
        return "brake" if self.spend.over_ceiling() else ""

    def _agent(self):
        e = self.engines.agent
        if e is None or SETTINGS.get("agent_mode") == "off" or not self.hooks.agent_ok():
            return None
        # resting on its plan's limit: asked anyway, a person's own question included, it can only fail
        return None if self.spend.limit_left() else e

    def ready(self) -> bool:
        """Something can answer: automatic analysis waits otherwise (the panel says why)."""
        return self._local() is not None or self._agent() is not None

    def auto_blocked(self) -> str:
        """Why watching the screen by itself can produce nothing right now, as a clause, or empty.

        Only the spend brake with the agent as the one engine ends that way: everything it is asked
        comes back refused, and each refusal used to put its own card on the panel, so
        one brake wrote a card per screen change for its whole five minutes. With the local model
        on there is nothing to say here, because that model answers and the brake only keeps the agent
        out of the one analysis."""
        if self._local() is not None:            # the local model answers: not a wasted analysis
            return ""
        if self.engines.agent is not None and self.spend.limit_left():   # resting on its limit: say until when
            # this PC's model is off (or not answering) and does not stand in: say what would have it answer meanwhile
            # the stand-in covers a used-up plan only (standing_in): during a two-minute rate limit it does nothing
            how = ("" if self.engines.local is None or not self.hooks.local_ok()
                   else t(" · switch the local model on to solve meanwhile") if SETTINGS.get("local_fallback")
                   or not self.spend.plan_left()
                   else t(" · switch the local model (or 'This PC's model stands in at a limit') on to solve meanwhile"))
            return self.spend.blocked() + how
        if self._agent() is None:               # neither engine, which `ready()` already covers
            return ""
        return self.spend.blocked()

    @staticmethod
    async def _look(frame) -> tuple:
        """What the models look at: (the box the user drew or None, the part of the screen the images
        cover, stitched pages, the images)."""
        manual = SETTINGS.get("roi_box") if frame is not None else None
        view = tuple(manual) if manual else getattr(frame, "model_box", (0.0, 0.0, 1.0, 1.0))
        pages = len(frame.extra_b64) if frame is not None and not manual else 0
        if frame is None:
            look = []
        elif manual:
            look = [(await _in_thread(crop_image, frame, view, 0.0, CONFIG.max_image_width))[0]]
        else:
            look = [frame.model_b64, *frame.extra_b64]
        return manual, view, pages, look

    async def solve(self, seq: int, frame, transcript: str, voice: bool, on_delta,
                    by_user: bool = False) -> Outcome:
        """`by_user`: Reanalyze, not the automatic watching. (The `manual` below is something else:
        the region the user drew on the screen.)"""
        local, agent = self._local(), self._agent()
        if local is None and agent is None:
            raise NoSolver("no engine can answer: the local LLM is off or down, and the agent is off or not signed in")
        mode = SETTINGS.get("agent_mode") if agent is not None else "off"
        if agent is not None and local is not None and by_user and self.standing_in():
            # The local model is off and stands in while the cost ceiling holds: what the ceiling lets through (Analyze
            # again) still goes to the agent whatever its kind, as it would with the local model off. Only that: for the
            # watching's own screens "all" made the first pass hand every problem on, and the thinking pass took even
            # the easy ones
            mode = "all"
        manual, view, pages, look = await self._look(frame)
        stages = {"roi": bool(manual), "local": local is not None}

        if local is None:   # The agent alone: what the payload setting allows of the screen or speech
            why = "" if by_user else self.spend.blocked()
            if why:
                await self.say_brake(why)
                raise NotSent(why)
            stages["why"] = "only"          # the agent is the one engine there is
            try:
                return await self._agent_solve(seq, agent, None, frame, look, pages, transcript, voice, None, stages,
                                                on_delta)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # at its limit (_agent_solve armed the rest): this PC's model, switched off, may stand in from now,
                # this problem included; otherwise the error is the card's
                if not getattr(exc, "limit", False) or self._local() is None:
                    raise
                await self.hooks.stage(seq, "local", "", restart=True)
                out = await self.solve(seq, frame, transcript, voice, on_delta, by_user=by_user)
                out.sent = getattr(exc, "sent", []) + out.sent   # the problem went out all the same: the card says so
                out.stages = {**out.stages, "agent_failed": True}
                return out

        think = SETTINGS.get("local_think")
        # A single screen: the fast pass also says where the problem is, for the crops.
        want_region = frame is not None and not voice and not manual and not pages
        windows = getattr(frame, "windows", None) if SETTINGS.get("roi_windows") and not manual else None
        # The local model hears what was said around a screen problem; the agent never does.
        text = build_user_text(transcript, pages, voice, bool(look))
        if think == "never" and mode in ("off", "verify"):   # local only, no thinking at all: one direct pass
            # in verify the agent is there, and takes the problem when this PC's model cannot answer it (note 117)
            can_take = mode == "verify" and (by_user or not self.spend.blocked())
            try:
                res = await local.deep(look, text, on_delta, think=False,
                                       first_deadline=CONFIG.local_think_first_token_sec if can_take else None,
                                       stall=CONFIG.local_stuck_sec if can_take else None)
            except (asyncio.CancelledError, Repeat):
                raise
            except Exception as exc:
                if not can_take:
                    raise
                return await self._agent_after_local(seq, exc, agent, local, frame, look, pages, transcript, voice, None,
                                                     stages, on_delta, None, "", None, False, [], by_user)
            return self._local_outcome(res, view, stages, think=False, windows=windows, aspect=box_aspect(frame, view))

        # When the agent could take this screen, the first pass gets local_first_token_sec for its first token: nothing
        # by then means another program has the GPU, and waiting out the whole first-pass limit cost 45 s each time.
        takes_over = agent is not None and mode in ("hard", "all") and (by_user or not self.spend.blocked())
        f = await local.fast(look, text, on_delta, want_region=want_region,
                             escalate_all=(mode == "all" or think == "always"),
                             first_deadline=CONFIG.local_first_token_sec if takes_over else None)
        # The first pass brought nothing by its deadline (design 54), so the problem is the agent's, whatever its kind.
        handoff = bool(f.slow)
        # What the agent may be given is still what the payload setting allows, and for a single screen with no region
        # drawn the crop and the problem text both start from where the problem is, which nothing has read yet. With
        # no place known the payload became the whole screen written out by the same busy GPU, with no time limit,
        # and a screen holding nothing ended in "could not find where the problem is", a toast and a thinking pass on that GPU.
        # So the first pass is asked once more for the kind and the place, with the same
        # deadline. It runs on the model this PC uses while the GPU is held (local_busy_model): the pass that came
        # back empty counted the GPU busy, and that model reads the next screens for the hold anyway (one that only
        # waited behind this server's own request counted nothing, and the same model is asked again). A screen with
        # nothing on it ends there, as any other does. The whole screen as the payload, stitched pages and a drawn
        # region need no place, and a problem heard is written out from the words alone, so those go on at once.
        if f.slow and want_region and SETTINGS.get("agent_payload") != "screen":
            log.info("analysis #%d: no first token in %.0f s; the first pass is asked once more, by %s", seq,
                     CONFIG.local_first_token_sec, local.model)
            f = await local.fast(look, text, on_delta, want_region=want_region,
                                 escalate_all=(mode == "all" or think == "always"),
                                 first_deadline=CONFIG.local_first_token_sec)
            if f.slow:
                # Nothing could read this screen at all: no place, so nothing may go to the agent, and no answer can come
                # from a GPU that started neither model in time. The card says so instead of waiting on it further.
                raise GpuBusy(f"local LLM: no first token in {CONFIG.local_first_token_sec:.0f} s from either "
                                   "model (the GPU is busy), so where the problem is was not read and nothing went "
                                   "to the agent")
        # Nothing found, and this screen was asked for by hand: look again at the halves
        # before saying there is nothing there. The fast pass is the only pass a screen gets
        # when it says nothing is on it, and it is given one shrunk image of the whole screen, which
        # is how a problem in a narrow window beside a full editor is missed. Measured on the known
        # screens of section 11: `roi_tall_2160` is read as empty on 3 runs of 3 from the screen and
        # on 0 of 3 from its halves. It is not done for the watching, which is most of the work: of
        # 1,014 screens in a day's log 1,001 held nothing, and the second look costs about three
        # times the first (1.2-2.0 s against 4.1 s for the screen and its halves together), so paying it
        # on every quiet screen is the cost this tool spends its time avoiding. Asked for, it is one
        # screen and someone is waiting for it.
        if (by_user and f.text is not None and f.type in ("", "none") and frame is not None
                and not manual and not pages and not voice and halves_help(frame)):
            log.info("analysis #%d: asked again and nothing found; looking at the halves", seq)
            # restart, because the first pass already streamed "TYPE: none" into the card: without
            # it the second answer is written under that line, and the panel reads the first TYPE
            # it sees, so the card stays filed as nothing to solve while the answer arrives.
            await self.hooks.stage(seq, "halves", "screen", restart=True)
            # The halves go in with the note that says what they are and that REGION is written
            # against the first image, the same note the thinking pass sends with them. Without it
            # the box comes back in some half's own coordinates and the panel draws it in the wrong
            # place, the change watch compares the wrong box, and follow-ups crop from it.
            f = await local.fast([look[0], *await _in_thread(halves, frame)],
                                 build_user_text(transcript, pages, voice, True, zoom="halves"),
                                 on_delta, want_region=want_region,
                                 escalate_all=(mode == "all" or think == "always"))
            stages["halves"] = True
        sent = _searches(f.searches)
        if f.text is not None and f.type in ("", "none"):
            # Nothing to solve. What it looked at is written down: a screen that holds a problem and is
            # read as empty is the hardest thing here to tell from a screen that really is empty.
            log.info("analysis #%d: nothing to solve in %d image(s) of %d KB %s, %d chars of request",
                     seq, len(look), sum(len(i) for i in look) // 1365,
                     f"{frame.width}x{frame.height}" if frame is not None else "no screen", len(text))
            if os.environ.get("SIDENOTE_DEBUG_FRAMES") and look:
                _keep_frames(seq, look[0], frame)
                log.info("  looked at: manual=%s view=%s pages=%s images=%d", manual, view, pages, len(look))
        if f.text is not None and f.type in ("", "none") and manual and tuple(manual) != self._roi_empty_said:
            # Nothing to solve inside a drawn region: say which it is, since the region may be left over
            # from another screen and would otherwise quietly swallow every answer. Once per region.
            self._roi_empty_said = tuple(manual)
            await self._warn(t("Nothing to solve in the drawn region · clear the region on the screen card to see "
                               "the whole screen"))
        if f.text is not None:   # answered at once (or nothing to solve)
            aspect = box_aspect(frame, view)
            region = parse_region(f.text, local.region_scale, aspect)
            return Outcome(text=f.text, model=(f.model or local.model) + (f" (web {len(f.searches)})" if f.searches else ""),
                           usage=f.usage, cost_usd=None, engine="local",
                           region=within(region, view) if region else None,
                           region_placed=placed_region(region, view, windows),
                           crop_box=self._box(f.text, local.region_scale, view, windows, aspect),
                           seen=self._seen(f.text, local.region_scale, view, aspect), sent=sent, stages=stages)

        seen = await self._seen_upright(f.head, local.region_scale, view, box_aspect(frame, view), frame)   # the model's box, for the duplicate check
        box = located(seen, windows) if seen else None        # where the problem is, for the crops
        hard = f.type in DEEP_TYPES or f.route != "fast"     # the fast pass's own call (unknown counts as hard)
        # The problem answered a little while ago, seen again: scrolled, moved, or come back to after another screen.
        # The change watch only knows the old box changed, so it was solved again, a thinking pass of 20 to 60 s each
        # time (one problem three times in nine minutes). Its picture is looked for where the first pass
        # puts this one, before anything else is spent on it; Reanalyze always solves (design 88). Not with pages
        # scrolled together: they carry the part of the problem not seen before, which is the continuation's to fill in.
        if (seen is not None and frame is not None and not by_user and not voice and not manual and not pages
                and SETTINGS.get("dedupe")):
            again = await _in_thread(self.recent.match, frame.model_b64, view, seen, f.type)
            if again is not None:
                log.info("analysis #%d: the problem of answer #%d, seen again (score %.2f); not solved again",
                         seq, again[0], again[1])
                raise Repeat(again[0], seen, again[1])
        # No kind at all means the local model could not read the screen even once, which on this machine
        # is what a full GPU looks like (its own pass gives up at 45 s). The agent needs no GPU, so in the
        # hard mode it takes those too; a screen with nothing on it says TYPE: none and never gets here.
        unknown = not f.type
        # Whether the agent put anything on the card before the local model took over: what it wrote
        # has to be cleared, or the local answer is written underneath a refusal while it streams.
        agent_wrote = False
        # The agent's reply when it declined and this PC's model took the problem over: the card if that model
        # cannot answer after all, so the problem still ends with what the agent said
        declined = None
        brake = self.spend.blocked() if agent is not None and not by_user else ""
        if brake:
            await self.say_brake(brake)
            stages["not_sent"] = True
        # The rule: a problem the local model would be local_slow_ratio times as slow to start
        # answering goes to the agent whatever its kind, and so does one while another program has the GPU (the thinking
        # pass would run slow or on the smaller model). The local model answers it only when the agent cannot.
        slow_here = self.speed.local_slower(CONFIG.local_slow_ratio) or local.busy_now()
        # and a first pass that brought nothing in time hands its problem over whatever the second look made of it
        to_agent = agent is not None and not brake and (mode == "all" or (mode == "hard" and (handoff or (hard and (
            unknown or slow_here or f.type in SETTINGS.get("agent_hard_types"))))))
        # Why this engine, in the log: a coding problem was answered by this PC's model in 169 s on a busy GPU
        # while the agent was on, and nothing recorded which of these held (fast pass type and route, the
        # brake, the agent there or not), so it could not be told afterwards.
        log.info("analysis #%d: %s answers (type %s, route %s, hard %s, handoff %s, slow here %s, agent %s, mode %s%s)",
                 seq, "The agent" if to_agent else "the local model", f.type or "-", f.route or "-", hard, handoff,
                 slow_here, "on" if agent is not None else "off", mode, f", brake: {brake}" if brake else "")
        if to_agent:
            # why the agent got this one, for the record (report: what the agent was paid for on a screen it found
            # nothing on): the first pass slow, the kind unread, this PC's model slow, a kind set for the agent, or all
            stages["why"] = ("all" if mode == "all" else "handoff" if handoff else "unknown" if unknown
                             else "slow" if slow_here else "kind")
            try:
                out = await self._agent_solve(seq, agent, local, frame, look, pages, transcript, voice, box,
                                               stages, on_delta, seen=seen, kind=f.type,
                                               facts=searched_facts(f.messages), web=present_question(f.messages),
                                               by_user=by_user)
                # A reply with no head at all is the agent declining rather than answering in the format. Nothing
                # left at all is the same: a reply that was only a tool call written out (strip_tool_markup) answered
                # nothing. With "This PC's model answers when the agent declines" on, the model on this PC, already
                # loaded, solves the same screen; off, the agent's reply is the card as it came. What went out has to
                # be on the card either way, so the agent's record of it is carried over.
                if not head_of(out.text)[0]:
                    stages["agent_declined"] = True
                    sent = sent + out.sent
                    out.sent = sent
                    out.stages = stages = {**out.stages, **stages}   # one record from here on, whichever answer stands
                    if not out.text.strip():
                        out.text = t("The agent gave no answer", agent=agent_name())
                    if not SETTINGS.get("local_on_decline"):
                        log.info("analysis #%d: the agent declined to answer (%d chars); its reply is the card",
                                 seq, len(out.text))
                        telemetry.event("agent_declined", id=seq, chars=len(out.text), type=f.type or "", local=False)
                        return out
                    declined = out
                    agent_wrote = True
                    log.info("analysis #%d: the agent declined to answer (%d chars); the local model answers",
                             seq, len(out.text))
                    telemetry.event("agent_declined", id=seq, chars=len(out.text), type=f.type or "", local=True)
                    await self.hooks.notice(t("The agent did not answer: the local model solves", agent=agent_name()))
                else:
                    out.sent = sent + out.sent
                    return out
            except (asyncio.CancelledError, Repeat, LoadStopped):
                # LoadStopped: the GPU was given back (or the panel paused) while this PC's model was loading for the
                # agent's question, which it reads out of what was heard. No fault of the agent's, and loading the model
                # again for this PC's answer undoes what was just asked for (the e4b was back on the GPU 31 s after Free
                # GPU, logged as an agent failure). The analysis ends, said as stopped (app, run_analysis)
                raise
            except NotSent as why:
                # No question in what was heard, by the model's own reading: nothing to solve, unless it was asked for by hand
                if isinstance(why, NothingAsked) and not by_user:
                    log.info("analysis #%d: no question in what was heard; nothing to solve", seq)
                    # the model that read it out is the one this PC uses now (the smaller one through a busy stretch),
                    # not the first pass's: credited to that, the report gave the 26b answers it never read
                    return Outcome(text="TYPE: none", model=local.model, usage=f.usage, cost_usd=None, engine="local",
                                   sent=sent, stages=stages)
                stages["not_sent"] = True
                # Why nothing went, in the log as well as on the panel: the 169 s answer fell to this
                # PC's model with no record of which it was (no place and no words, numbers like personal data, a
                # confirm not given, the agent switched off meanwhile)
                log.info("analysis #%d: nothing sent to the agent (%s); the local model answers", seq,
                         str(why) or "not confirmed")
                telemetry.event("agent_not_sent", id=seq, reason=str(why)[:120] or "not confirmed", type=f.type or "")
                await self._warn(t("{why} · not sent to the agent, the local model solves", why=why, agent=agent_name())
                                 if str(why) else
                                 t("Not sent to the agent, the local model solves", agent=agent_name()))
            except ToolCallWritten as exc:   # it tried to run something it cannot have here: no error of the agent's
                log.info("analysis #%d: %s; the local model answers", seq, exc)
                stages["agent_failed"] = True
                agent_wrote = True
                sent = sent + getattr(exc, "sent", [])
                await self._warn(t("{why} · the local model solves", why=exc))
            except Exception as exc:   # an error, not an answer: a refusal is handled above
                sent = sent + getattr(exc, "sent", [])   # the problem went out all the same
                stages["agent_failed"] = True
                agent_wrote = True   # it may have written some of an answer before it stopped
                if getattr(exc, "limit", False):
                    pass   # at its limit: _agent_solve has armed the rest and said so; this PC's model answers
                else:
                    await self.hooks.agent_failed(exc)
                    log.warning("The agent failed (%s); the local model answers", exc)
                    await self._warn(t("The agent could not answer ({why}) · the local model solves",
                                       why=error_words(str(exc)), agent=agent_name()))

        # the local thinking pass, with the problem cropped at full resolution beside the screen. What it
        # gets stays on this PC: a box that places nothing is cut as it is, over any windows, unless it covers
        # nearly the whole screen, and a large screen with no box, or with one too large to read from its crop,
        # goes in halves (only when the model saw the whole screen: the halves are halves of the screen).
        images, zoom = list(look), False
        if want_region and SETTINGS.on("roi"):
            large = tuple(view) == (0.0, 0.0, 1.0, 1.0) and halves_help(frame)
            if box is not None:
                crop, _, _ = await _in_thread(crop_image, frame, box, CROP_PAD, CROP_MAX_SIDE, True, True)
                images, zoom = [look[0], crop], True
            elif seen is not None and _area(seen) < WHOLE_SCREEN and (
                    not large or sharpness(frame, seen) >= halves_sharpness(frame)):
                crop, _, _ = await _in_thread(crop_image, frame, seen, CROP_PAD, CROP_MAX_SIDE, False)
                images, zoom = [look[0], crop], True
            elif large:
                images, zoom = [look[0], *await _in_thread(halves, frame)], "halves"
            stages["roi"] = bool(zoom)
        on = think != "never"
        await self.hooks.stage(seq, "think" if on else "local", "", restart=agent_wrote)

        async def thinking(chars: int, tail: str = "") -> None:
            # the card's status line: how far the thinking has got, and its last line, which is something to read in
            # the one long wait with nothing else on the card (30 s to the first word at the median on this PC's
            # screens, 100 s for the slowest tenth)
            await self.hooks.stage(seq, "think", t("Thinking: {n} characters", n=f"{chars:,}"), thought=thought_line(tail))
        # The agent takes the problem over when this PC's model cannot answer it (design note 117): not given up on
        # here while the agent can, it waited minutes on a GPU another program held and ended in an error with the agent
        # on. Not when the agent has had it already (failed or declined), was held back from it (not sent), is off or
        # braked: then the pass waits as before, there being nothing else to answer with.
        can_take = (agent is not None and mode != "off" and not agent_wrote and declined is None
                    and not stages.get("not_sent") and not brake)
        try:
            res = await local.deep(images, build_user_text(transcript, pages, voice, bool(images), zoom=zoom),
                                   self.speed.timed("think", on_delta) if on else on_delta,
                                   prior=f.messages, think=on, on_thought=thinking if on else None,
                                   first_deadline=CONFIG.local_think_first_token_sec if can_take else None,
                                   stall=CONFIG.local_stuck_sec if can_take else None)
        except (asyncio.CancelledError, Repeat):
            raise
        except Exception as exc:
            if can_take:
                return await self._agent_after_local(seq, exc, agent, local, frame, look, pages, transcript, voice, box,
                                                     stages, on_delta, seen, f.type, searched_facts(f.messages),
                                                     present_question(f.messages), sent, by_user)
            if declined is None:
                raise
            # it took over a problem the agent declined and failed: the agent's reply is the card, not an error
            log.warning("analysis #%d: the local model failed after the agent declined (%s); the agent's reply stands",
                        seq, exc)
            stages["local_failed"] = True
            await self._warn(t("The local model could not answer ({why}) · the agent's reply is shown",
                               why=error_words(str(exc)), agent=agent_name()))
            await self.hooks.stage(seq, "agent", "", restart=True)
            declined.stages = stages
            return declined
        if declined is not None and not (res.text or "").strip():
            stages["local_failed"] = True   # it wrote nothing: the agent's words are more than that
            await self.hooks.stage(seq, "agent", "", restart=True)
            declined.stages = stages
            declined.sent = sent + _searches(getattr(res, "searches", None))   # what it searched for went out all the same
            return declined
        out = self._local_outcome(res, view, stages, think=on, windows=windows, aspect=box_aspect(frame, view))
        out.sent = sent + out.sent
        # What may go out later (the verify mode's crop, a follow-up to the agent) is cut from the fast pass's box, as
        # the agent's crop is, and the duplicate check watches that box too. The thinking pass at times writes its
        # REGION y first, Gemma's own order, in a shape TALL_BOX cannot tell, and with a zoom or the halves beside the
        # screen it may write it for another image: either can place the box in another window.
        out.crop_box = box
        out.seen = seen   # and the verify mode reads the agent's words from it as the answer's own path would (box_first)
        if seen is not None:
            out.region = _pull_in(seen)
            # and whether the panel may draw it is decided by that same box: kept from the thinking pass's own
            # REGION, a first-pass box over the wallpaper was drawn and a placed one was not
            out.region_placed = box is not None
        out.local_view = "halves" if zoom == "halves" else (seen if zoom and box is None else None)
        return out

    @staticmethod
    def _seen(text: str, scale: float, view, aspect: float = 0.0) -> tuple | None:
        b = region_box(text, scale, aspect)
        return within(b, view) if b else None

    @staticmethod
    async def _seen_upright(text: str, scale: float, view, aspect: float, frame) -> tuple | None:
        """The fast pass's box as _seen reads it, turned first when the screen shows it was written y first (upright),
        which reads the screen in a thread."""
        b = region_box(text, scale, aspect)
        if b is not None and frame is not None and on_end(b, aspect):
            b = await _in_thread(upright, frame, view, b, aspect)
        return within(b, view) if b else None

    @staticmethod
    def _box(text: str, scale: float, view, windows=None, aspect: float = 0.0) -> tuple | None:
        b = Pipeline._seen(text, scale, view, aspect)
        return located(b, windows) if b else None

    def _local_outcome(self, res, view, stages, think: bool, windows=None, aspect: float = 0.0) -> Outcome:
        scale = self.engines.local.region_scale
        region = parse_region(res.text, scale, aspect)
        stages = {**stages, "think": think}
        return Outcome(text=res.text, model=res.model, usage=res.usage, cost_usd=None, engine="local",
                       region=within(region, view) if region else None,
                       region_placed=placed_region(region, view, windows),
                       crop_box=self._box(res.text, scale, view, windows, aspect),
                       sent=_searches(getattr(res, "searches", None)), stages=stages)

    async def _editor_note(self, local, look, kind: str) -> tuple[str, str]:
        """(a sentence for the agent's request, words for the card) naming the language of the code editor on the
        screen, for a coding answer the agent writes from part of the screen; ("", "") when there is nothing to say.

        The agent is given the crop and nothing else that names a language, and the crop leaves the editor out by
        design: the model keeps its box off it, so that typing in the editor does not read as a new problem. From
        the problem part alone the agent answered a C++ or Java test in Python every time (analyzer.EXTRACT_EDITOR).
        The model on this PC has the whole screen, so it is asked for the one word, and only that word goes out.
        It is bounded: a busy GPU can cost the answer a few seconds, never the answer itself."""
        if local is None or not look or kind not in ("coding", "algorithm"):
            return "", ""
        try:
            lang = await asyncio.wait_for(local.editor_language(look[:1]), EDITOR_WAIT)
        except asyncio.TimeoutError:
            log.info("editor language: no answer in %.0f s, so the agent is not told one", EDITOR_WAIT)
            return "", ""
        except Exception as exc:   # a helper that fails must not stop the answer (cancelling still does)
            log.info("editor language: %s", exc)
            return "", ""
        if not lang:
            return "", ""
        # "editor or code": on a screen with no editor the model names the language of the code shown instead (11
        # of 39 known screens without one: a Python traceback, a Java question), which is the language an answer's
        # code belongs in there too, so the sentence says what was seen without claiming an editor
        return f" 화면의 코드 편집기나 코드는 {lang} 입니다. 답의 코드는 그 언어로 쓰세요.", t(" + code language {lang}", lang=lang)

    async def _agent_payload(self, seq, local, frame, look, pages, transcript, voice, box,
                              kind: str = "", seen=None) -> tuple[list, str, str, str, tuple | None]:
        """(images, request text, what is sent in words, the problem in words, the box they were read from) for
        The agent, by the payload setting. The problem in words is the problem as it goes when it goes as words (the
        problem text, the question part of what was heard), else "": a follow-up that sends no image carries it again.
        The box is the model's own (`seen`) when the words were read from it although it places nothing (box_first),
        else None. `kind`: the problem's TYPE as the fast pass read it, which decides whether the editor's language
        goes along ("" asks nothing)."""
        payload = SETTINGS.get("agent_payload")
        manual = SETTINGS.get("roi_box")
        if voice or frame is None:
            question = transcript
            if local is not None and SETTINGS.on("extract"):   # only the question part of what was heard
                await self.hooks.stage(seq, "extract", "speech")
                question = await local.extract(speech=transcript)
                # Nothing in what was heard reads as the problem. The whole transcript is up to two minutes of the
                # room, and the setting promises only the question part, so it stays here. And when the model said
                # so, it ends here: a thinking pass only wrote a report on somebody's story, and of 60 real questions
                # this reading lost none (docs/DECISIONS.md, note 106). A reading that brought nothing says nothing,
                # and this PC's model answers instead (the screen path already refuses this way).
                if question == NO_QUESTION:
                    raise NothingAsked(t("No question could be told apart in what was heard"))
                if not question:
                    raise NotSent(t("No question could be told apart in what was heard"))
            if voice and payload == "screen" and look:
                return (look[:1], build_user_text(question, 0, True, True),
                        t("Heard question, {n} characters + whole screen", n=len(question)), question, None)
            return [], speech_request(question), t("Heard question, {n} characters", n=len(question)), question, None
        if payload == "screen":
            return (look, build_user_text("", pages, False, True),
                    t("Whole screen") + (t(" + joined problem, {n} pages", n=pages) if pages else ""), "", None)
        # From here on the agent sees part of the screen or none of it, and so not the code editor. Its language is
        # asked for only in the branches that are sure to send: one refused below would spend the question for
        # nothing, a second or more of the GPU before the local model starts on the answer itself.
        if pages:   # a stitched problem: the tiles are the scrolled problem pane itself
            note, said = await self._editor_note(local, look, kind)
            return list(frame.extra_b64), CROP_REQUEST + note, t("Joined problem, {n} pages", n=pages) + said, "", None
        target = box or (tuple(manual) if manual else None)
        extract = local is not None and SETTINGS.on("extract")
        if extract and (payload == "text" or target is None):   # no box: the problem as text, not the whole screen
            await self.hooks.stage(seq, "extract", "screen")
            near = None
            if target:
                reads = [[(await _in_thread(crop_image, frame, target, CROP_PAD, CROP_MAX_SIDE, True,
                                            box is not None))[0]]]
            else:
                # A box that places nothing (it ran into another window) is still where the model saw the problem: on a
                # large screen whose box keeps much more of the resolution than the whole screen (box_first), the words
                # are read from the box, cut as given (read_images, as the thinking pass and the code check read it),
                # and from the whole screen only when that gives nothing. Elsewhere the whole screen, as before. The
                # image stays on this PC, and what is read goes through the same check for numbers shaped like
                # personal data before it leaves.
                near = seen if seen is not None and _area(seen) < WHOLE_SCREEN and box_first(frame, seen) else None
                reads = ([await read_images(frame, None, near)] if near else []) + [look[:1]]
            problem, read_from = "", None
            for src in reads:   # the next one is read only when this one gave nothing
                problem = await local.extract(src)
                if problem:
                    read_from = near if src is reads[0] else None   # the box, when it was the box that gave them
                    break
            if problem and target is None and personal_data(problem):   # read with nothing placed: maybe another window's
                raise NotSent(t("The written-out text holds numbers like resident registration, phone, card or "
                                "account numbers"))
            if problem:
                note, said = await self._editor_note(local, look, kind)
                return ([], text_request(problem, note), t("Problem text, {n} characters", n=len(problem)) + said,
                        problem, read_from)
        if target is not None:
            crop, _, size = await _in_thread(crop_image, frame, target, CROP_PAD, CROP_MAX_SIDE, True,
                                             box is not None)
            note, said = await self._editor_note(local, look, kind)
            return [crop], CROP_REQUEST + note, t("Problem area {w}x{h}", w=size[0], h=size[1]) + said, "", None
        if local is not None:   # the local model can take it: the whole screen never goes out unasked
            raise NotSent(t("Could not find where the problem is"))
        why = t("the local model is off, so the problem was not placed")
        await self.hooks.notice(t("The whole screen goes to the agent ({why}) · draw a region to send only what is in it",
                                  why=why, agent=agent_name()))
        return look, build_user_text("", 0, False, True), t("Whole screen ({why})", why=why), "", None

    def _still_on(self) -> None:
        """NotSent when the agent was switched off after this analysis began. The engine is read once, at the start,
        and the first pass, reading the problem out and a confirm can take from seconds to minutes after that:
        switched off in between, the problem went to the agent anyway."""
        if self._agent() is None:
            raise NotSent(t("The agent was switched off meanwhile", agent=agent_name()))

    async def _confirmed(self, seq, images, text, what, shown: str | None = None) -> None:
        """"Confirm before sending": show the payload and wait for the user's choice (NotSent if not). `shown`: the part
        of the text to preview when not its end (the verify mode's, whose end is this PC's own answer)."""
        if not SETTINGS.on("agent_confirm"):
            return
        preview = {"what": what, "text": (text if shown is None else shown)[-1500:] if not images else "",
                   "thumb": await _in_thread(thumb_url, images[0]) if images else None}
        await self.hooks.stage(seq, "confirm", what)
        if not await self.hooks.confirm(seq, preview):
            raise NotSent()

    async def _agent_after_local(self, seq, exc, agent, local, frame, look, pages, transcript, voice, box, stages,
                                 on_delta, seen, kind, facts, web, sent, by_user) -> Outcome:
        """This PC's model could not answer (`exc`: no first token while the GPU was held, a stream gone silent, its
        server failing): the agent takes the problem, with what the payload setting and the confirm allow, as it takes
        those it is given at once. What the local model wrote before it stopped is cleared from the card. When the
        problem may not go (not sent), or the agent fails too, the card says why: there is nothing else to answer."""
        # a deadline of its own (NoFirstToken, a silent stream) is a timeout whatever its message says
        why = t("no answer in time") if isinstance(exc, TimeoutError) else error_words(str(exc))
        log.warning("analysis #%d: the local model could not answer (%s); the agent takes it", seq, exc)
        telemetry.event("local_failed", id=seq, reason=f"{type(exc).__name__}: {exc}"[:200], to_agent=True)
        stages["local_failed"] = True
        stages["why"] = "local_failed"   # why the agent got this one (report: VIA_NAMES)
        await self._warn(t("The local model could not answer ({why}) · the agent solves", why=why, agent=agent_name()))
        await self.hooks.stage(seq, "agent", "", restart=True)
        try:
            out = await self._agent_solve(seq, agent, local, frame, look, pages, transcript, voice, box, stages,
                                          on_delta, seen=seen, kind=kind, facts=facts, web=web, by_user=by_user)
        except (asyncio.CancelledError, Repeat):
            raise
        except NotSent as held:
            # what the payload setting, personal data or a declined confirm keeps on this PC stays there
            log.info("analysis #%d: not sent to the agent either (%s)", seq, str(held) or "not confirmed")
            telemetry.event("agent_not_sent", id=seq, reason=str(held)[:120] or "not confirmed", type=kind or "")
            raise exc
        except Exception as failed:
            if not getattr(failed, "limit", False):
                await self.hooks.agent_failed(failed)
            log.warning("analysis #%d: the agent failed too (%s)", seq, failed)
            both = RuntimeError(t("Neither could answer: the local model ({local}), the agent ({agent_why})",
                                  local=why, agent_why=error_words(str(failed)), agent=agent_name()))
            both.sent = sent + getattr(failed, "sent", [])   # the problem went out all the same: the card says so
            raise both from failed
        out.sent = sent + out.sent
        out.stages = {**out.stages, **stages}
        return out

    async def _agent_solve(self, seq, agent, local, frame, look, pages, transcript, voice, box, stages,
                            on_delta, seen=None, kind: str = "", facts=None, web: bool = False,
                            by_user: bool = False) -> Outcome:
        """`box`: where the problem is, for the crop; `seen`: the model's box even when it did not place the
        problem, for the duplicate check (which watches the whole screen without one); `kind`: its TYPE;
        `facts`: what the first pass found on the web (searched_facts), which goes along with the problem; `web`:
        it asked about the present (present_question), and the agent gets the web search for it."""
        images, text, what, words, read_from = await self._agent_payload(seq, local, frame, look, pages, transcript,
                                                                          voice, box, kind, seen=seen)
        # only Claude Code is given a web search for the turn: the API agent and Codex have none, and telling them they
        # may search made them say they would
        # The problem as words, seen again: asked of no one for the second time. The picture could say nothing when the
        # first pass on a busy GPU gave no box, as it once did (the same ten questions, 119 s and 93 s of the agent)
        if words and frame is not None and not voice and not by_user and not pages and SETTINGS.get("dedupe"):
            again = await _in_thread(self.recent.match_words, words)   # difflib: seconds on a long problem, not on the event loop
            if again is not None:
                log.info("analysis #%d: the words are those of answer #%d (%.2f); not sent again", seq, again[0], again[1])
                raise Repeat(again[0], seen, again[1])
        web = bool(facts) and web and getattr(agent, "name", "") not in ("anthropic-api", "codex")
        if facts:   # the first pass's results go along; on a question about the present the agent may search too
            text += facts_note(facts, time.strftime("%Y-%m-%d"), web)
            what += (t(" + search results: {n}", n=len(facts))
                     + (t(" (the agent may search the web)", agent=agent_name()) if web else ""))
        self._still_on()                     # making the payload can take seconds: the agent may be off by now
        await self._confirmed(seq, images, text, what)
        self._still_on()                     # and a confirm can wait for minutes
        # and where the words came from when nothing was placed: whether the 4K box route (box_first) is taken in real
        # use is then one search of the log
        log.info("analysis #%d: the agent gets %s (%d KB)%s", seq, what, _kb(images) + len(text.encode()) // 1024,
                 ", written out from the model's box (it places nothing)" if read_from else "")
        await self.hooks.stage(seq, "agent", what)
        try:
            # The web search is opened only for this: everything else keeps the warm process with no tools. A web
            # turn's first word is not timed: a fresh process that searches first is no measure of how fast the agent
            # starts an answer, and eight of them made the local model look as fast.
            sent_before = getattr(agent, "sent", None)
            res = await agent.run(images, text, guarded(on_delta if web else self.speed.timed("agent", on_delta)),
                                   **({"web": True} if web else {}))
        except asyncio.CancelledError:
            # stopped before its price arrived, but paid for once its request went out; an agent that does not count
            # what it sent is taken to have sent it
            if sent_before is None or getattr(agent, "sent", None) != sent_before:
                self.spend.cut_short()
            raise
        except Exception as exc:
            exc.engine = "agent"   # the server tells an agent sign-in problem from a local one by this
            exc.sent = [{"to": "agent", "what": what}]   # it went out all the same: the card's record says so
            self.spend.failed(exc)  # it cost what it cost
            # Its plan used up: it rests until it says it comes back, and the panel hears it once. Here, not in the
            # caller, so it holds whichever path asked: with this PC's model off nothing else read the error, and the
            # agent was asked again after every error's wait
            exc.limit = self.spend.limited(str(exc))
            if exc.limit:
                log.warning("The agent is at its usage limit until %s (%s)", self.spend.limit_left(), exc)
                telemetry.event("agent_limit", id=seq, until=round(self.spend.limit_until),
                                limit=self.spend.limit_kind, error=str(exc)[:160])
                who = t(" · the local model solves meanwhile") if self._local() is not None else ""
                await self._warn(
                    t("The agent's usage limit: not sent until {until}{who}", agent=agent_name(),
                      until=self.spend.limit_left(), who=who)
                    if self.spend.limit_kind == "plan" else
                    t("The agent has had too many requests: not sent for a while, until {until}{who}",
                      agent=agent_name(), until=self.spend.limit_left(), who=who))
            raise
        # with no head left it reads as declined, and this PC's model answers
        text_out = lift_head(strip_tool_markup(res.text))
        self.spend.note(res.cost_usd, head_of(text_out)[0] in ("none", ""))
        # The words it went out in are kept by the worker once the card is done (Outcome.words, beside its picture): kept
        # here, a card cancelled after this point (a pause, a newer screen) still stood for its problem, and the same
        # problem was "already solved" for 30 minutes, pointing at a card with no answer
        target = box or (tuple(SETTINGS.get("roi_box")) if SETTINGS.get("roi_box") and frame is not None else None)
        # What this PC's model reads the problem from afterwards (the code check, Problem text): the box the words were read
        # from on a large screen (box_first), as after the thinking pass, not the whole screen it cannot read
        return Outcome(text=text_out, model=res.model, usage=res.usage, cost_usd=res.cost_usd, engine="agent",
                       region=_pull_in(target or seen) if target or seen else None,
                       region_placed=bool(target), crop_box=target, local_view=read_from,
                       sent=[{"to": "agent", "what": what}], stages={**stages, "agent": True}, words=words)

    async def say_brake(self, why: str) -> None:
        """Said on the panel at most once a minute: the reason does not change while it holds."""
        now = time.time()
        if now - self._brake_said < 60:
            return
        self._brake_said = now
        telemetry.event("agent_brake", reason=why[:120], hour_usd=self.spend.hour_usd(),
                        empty_run=self.spend.ran)   # the row that tripped it, not what is left of it
        log.info("The agent brake: %s", why)
        await self._warn(why + ".")

    async def _warn(self, text: str) -> None:
        """A note on the panel that says something was not done, as a warning (Hooks.warn)."""
        await (self.hooks.warn or self.hooks.notice)(text)

    async def problem_text(self, frame, box, view=None) -> str:
        """The problem written out as text (the panel's Problem text), by the same pass as the text payload:
        from the stitched pages, the crop the answer points at, what the thinking pass read when nothing was
        placed (`view`, Outcome.local_view), or what the model looked at. "" when the local model is off or
        finds no problem."""
        local = self._local()
        if local is None or frame is None:
            return ""
        _, _, pages, look = await self._look(frame)
        if pages:
            images = list(frame.extra_b64)
        else:
            images = await read_images(frame, box, view) or look[:1]
        return await local.extract(images)

    # ---------- the verify mode ----------

    def verifying(self, outcome: Outcome) -> bool:
        """`verify` applies to this answer: the local model answered a problem and the agent can take it."""
        return (SETTINGS.get("agent_mode") == "verify" and outcome.engine == "local" and self._agent() is not None
                and head_of(outcome.text)[0] not in ("none", ""))

    async def verify(self, seq: int, frame, transcript: str, voice: bool, outcome: Outcome, on_send=None) -> dict:
        """The agent gets the problem as the payload setting allows (cut where the answer points) and the
        local answer, and replies that it holds (`ok`) or with a corrected solution (`fix`). A reply in
        neither form, such as a refusal, is `other` and shown as it is. NotSent when the user chose not
        to send it. `on_send(items)` hears what goes out just before it goes, so it is on record even if
        the check is cancelled afterwards."""
        agent, local = self._agent(), self._local()
        _, _, pages, look = await self._look(frame)
        # No `kind`: the answer being checked is in the language its code belongs in already (this PC's model saw
        # the editor), and telling the agent to write code in a language could make a fix of an answer in another one.
        # And the model's own box, placed or not: a 4K screen whose box ran into another window had its words read
        # from the whole screen here, which on those screens comes back empty or garbled (box_first), while the
        # answer's own path read them from the box.
        images, text, what, _, _ = await self._agent_payload(seq, local, frame, look, pages, transcript, voice,
                                                              outcome.crop_box, seen=outcome.seen)
        # The confirm shows the problem as it goes, which on a large screen may have been written out from a box running
        # into another window: the request ends with this PC's own answer, and its end alone hid the words read off
        # the screen behind a long answer
        asked = text
        text = verify_request(text, outcome.text)
        self._still_on()
        await self._confirmed(seq, images, text, what, shown=asked)
        self._still_on()
        log.info("analysis #%d: the agent checks the answer with %s (%d KB)", seq, what,
                 _kb(images) + len(text.encode()) // 1024)
        if on_send is not None:
            await on_send([{"to": "agent", "what": what}])

        async def drop(_):
            pass

        try:
            res = await agent.run(images, text, guarded(drop))
        except asyncio.CancelledError:
            self.spend.cut_short()   # a newer analysis stopped the check after its request was paid for
            raise
        except Exception as exc:
            exc.engine = "agent"
            self.spend.failed(exc)   # paid for all the same
            self.spend.limited(str(exc))   # its plan used up: the agent rests until it comes back
            raise
        # Checking an answer costs what any other turn costs, and it happens for every answer in the
        # verify mode: the hourly ceiling has to see it. It is never "nothing to solve", so it does
        # not count towards the empty row.
        self.spend.note(res.cost_usd, False)
        return {"verdict": verdict_of(res.text), "text": res.text, "model": res.model, "usage": res.usage,
                "cost_usd": res.cost_usd}


def verdict_of(text: str) -> str:
    """The verify reply's verdict: `ok` for `TYPE: verify` with `ANSWER: OK`, `fix` for another answer,
    `other` for a reply without that head. Read like the panel reads heads: a blank line may come
    between TYPE and ANSWER, and markup around OK (`**OK**`, a code span) does not count."""
    i = head_start(text)
    if i is None or head_of(text)[0] != "verify":
        return "other"
    for line in text[i:].split("\n")[1:6]:
        m = re.match(r"\s*ANSWER\s*:\s*(.*)", line)
        if m:
            return "ok" if re.sub(r"[`*_\s.!]", "", m.group(1)).upper() == "OK" else "fix"
        if line.strip():
            break
    return "fix"


def _pull_in(box):
    x0, y0, x1, y1 = box
    ix, iy = min(0.01, 0.2 * (x1 - x0)), min(0.01, 0.2 * (y1 - y0))
    return (x0 + ix, y0 + iy, x1 - ix, y1 - iy)


# ---------- follow-up questions ----------

def followup_engine(pipeline: "Pipeline", last: dict):
    """The engine a follow-up about `last` goes to: the one that wrote that answer, else whichever is on."""
    local, agent = pipeline._local(), pipeline._agent()
    want = last.get("engine") or "local"
    return (agent if want == "agent" else local) or agent or local


async def followup(pipeline: "Pipeline", last: dict, question: str, context: str, on_delta, seq: int = 0,
                   pages=None, by_user: bool = True) -> Outcome:
    """A follow-up goes to the engine that wrote the answer it is about, with the same limits on what
    The agent is given (the crop, or no image at all with the text payload) and the same confirm before
    sending (NotSent when declined). `seq`: the follow-up's own number, for that confirm. `pages`: a frame
    carrying the problem scrolled together (its extra_b64), which goes in place of the answer's own screen:
    the problem as it now reads in full, for the answer to be filled out from (the continuation). `by_user`: a
    question a person asked, which the agent's brake does not hold back (the retry and the continuation are not).
    One this PC's model cannot answer goes to the agent, as a problem does (design note 117)."""
    local, agent = pipeline._local(), pipeline._agent()
    frame, box = last.get("frame"), last.get("crop_box")
    engine = followup_engine(pipeline, last)
    if engine is None:
        raise NoSolver("no engine can answer the follow-up")
    fu = {"question": question, "context": context}
    tiles = list(getattr(pages, "extra_b64", None) or ())
    local_failed = None
    if engine is local:
        shown = pages if tiles else frame   # the scrolled-together problem, when there is one, beside its screen
        can_take = (agent is not None and SETTINGS.get("agent_mode") != "off"
                    and (by_user or not pipeline.spend.blocked()))
        try:
            res = await local.analyze(shown.model_b64 if shown else None, "", on_delta,
                                      extra=shown.extra_b64 if shown else (), followup=fu,
                                      first_deadline=CONFIG.local_think_first_token_sec if can_take else None,
                                      stall=CONFIG.local_stuck_sec if can_take else None)
            return Outcome(text=res.text, model=res.model, usage=res.usage, cost_usd=None, engine="local",
                           sent=_searches(getattr(res, "searches", None)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not can_take:
                raise
            local_failed = exc
            why = t("no answer in time") if isinstance(exc, TimeoutError) else error_words(str(exc))
            log.warning("follow-up #%d: the local model could not answer (%s); the agent takes it", seq, exc)
            telemetry.event("local_failed", id=seq, reason=f"{type(exc).__name__}: {exc}"[:200], to_agent=True,
                            followup=True)
            await pipeline._warn(t("The local model could not answer ({why}) · the agent solves", why=why,
                                   agent=agent_name()))
            await pipeline.hooks.stage(seq, "agent", "", restart=True)   # what it wrote before it stopped goes
    payload, images, what = SETTINGS.get("agent_payload"), [], t("The question and the earlier solution")
    manual = SETTINGS.get("roi_box")
    if tiles:
        # The tiles are the scrolled problem pane itself, and they go to the agent the way a stitched problem goes in
        # the first place (_agent_payload): the problem as it now reads in full, in place of the old crop.
        images, what = tiles, what + t(" + joined problem, {n} pages", n=len(tiles))
    elif frame is not None and payload == "screen" and manual:
        # A drawn region holds for a follow-up as it does for the answer: the whole screen here would
        # send what the drawn region cut out of it, one question later.
        crop, _, size = await _in_thread(crop_image, frame, tuple(manual))
        images, what = [crop], what + t(" + drawn region {w}x{h}", w=size[0], h=size[1])
    elif frame is not None and payload == "screen":
        images, what = [frame.model_b64], what + t(" + whole screen")
    elif frame is not None and payload == "crop" and box is not None:
        crop, _, size = await _in_thread(crop_image, frame, box, CROP_PAD, CROP_MAX_SIDE, True, True)
        images, what = [crop], what + t(" + problem area {w}x{h}", w=size[0], h=size[1])
    if not images and last.get("words"):
        # Nothing of the screen goes with this one, so the problem goes again as the words it first went as:
        # with only the earlier answer and the question, the agent was asked to fix an answer to a problem it was
        # not shown, the warm session being told to treat each turn on its own.
        fu["problem"] = last["words"]
        what += t(" + problem text, {n} characters", n=len(last["words"]))
    text = build_user_text("", followup=fu, has_image=bool(images))
    pipeline._still_on()
    await pipeline._confirmed(seq, images, text, what)
    pipeline._still_on()
    try:
        res = await agent.run(images, text, guarded(on_delta))
    except asyncio.CancelledError:
        pipeline.spend.cut_short()   # paused or superseded after its request was paid for
        raise
    except Exception as exc:
        exc.engine = "agent"
        pipeline.spend.failed(exc)   # paid for all the same
        pipeline.spend.limited(str(exc))   # its plan used up: the agent rests until it comes back
        if local_failed is None:
            raise
        log.warning("follow-up #%d: the agent failed too (%s)", seq, exc)
        why_local = (t("no answer in time") if isinstance(local_failed, TimeoutError)
                     else error_words(str(local_failed)))
        both = RuntimeError(t("Neither could answer: the local model ({local}), the agent ({agent_why})",
                              local=why_local, agent_why=error_words(str(exc)), agent=agent_name()))
        both.engine = "agent"
        raise both from exc
    # This one was asked for by hand, so it never counts as an empty row, but what it cost is part
    # of the hour the ceiling watches.
    pipeline.spend.note(res.cost_usd, False)
    return Outcome(text=lift_head(strip_tool_markup(res.text)), model=res.model, usage=res.usage,
                   cost_usd=res.cost_usd, engine="agent", sent=[{"to": "agent", "what": what}])


# ---------- checking code answers against the problem's examples ----------

async def read_images(frame, box, view=None, reach: float | None = None) -> list | None:
    """What the local model reads a problem from on this PC (the code check's examples, the problem text): the
    crop of the placed box, else what the thinking pass read (`view`: the box cut as given, or "halves"), else
    None (the screen, the caller's choice). `reach` (READ_REACH) lets the placed box's crop go on down to the last
    example: the code check asks for it, the panel's Problem text does not, since a crop carried down past the problem
    picks up the panes under it (a run's output, a test case box) and that text would be shown as the problem."""
    if box:
        return [(await _in_thread(crop_image, frame, box, CROP_PAD, CROP_MAX_SIDE, True, True, reach))[0]]
    if view == "halves":
        return list(await _in_thread(halves, frame))
    if view:
        return [(await _in_thread(crop_image, frame, tuple(view), CROP_PAD, CROP_MAX_SIDE, False))[0]]
    return None


def checkable(pipeline: "Pipeline", frame, outcome: Outcome, any_type: bool = False) -> tuple[str, str] | None:
    """(language, code) to check, when the automatic check applies to this answer (`any_type`: a retry, whose
    head says followup, not coding); ("", language name) for code in a language the runner has no toolchain for,
    which is said instead."""
    if pipeline._local() is None or not SETTINGS.on("autocheck") or frame is None:
        return None
    if not any_type and head_of(outcome.text)[0] not in ("algorithm", "coding"):
        return None
    other = other_language(outcome.text)
    return answer_code(outcome.text) or (("", other) if other else None)


async def check_code(pipeline: "Pipeline", frame, outcome: Outcome, run, cases: dict | None = None,
                     any_type: bool = False, gap=None, note: dict | None = None) -> dict | None:
    """Run a coding answer's code on the problem's examples, in its own language (codecheck.py). `run(lang, code,
    stdin)` sends a program to the runner sandbox. None when there is nothing to check. The examples read off the
    problem come back under "cases", so a retry is checked against the same ones. `gap(read)` awaits each read with
    the local model (a coroutine factory) when the server lets it, between analyses (app.between_analyses); the runs
    on the runner are not put through it, since they do not use the model and a run that was cut would go on in the
    runner all the same. `note`, when given, is told how the reading went, for the record:
    how many examples were read off the screen ("read"), how many of them the problem's text shows ("kept"), and of
    that text its length and whether it has an example heading. A check that ended with no examples did not say
    whether none were on the screen or the ones read were left out, and of nine checks in real use six ended so."""
    found = checkable(pipeline, frame, outcome, any_type)
    if found is None:
        return None
    if not found[0]:   # nothing to read the examples for
        return {"skipped": t("{lang} code cannot be run (runs {langs})", lang=found[1], langs=CHECKED)}
    local = pipeline._local()
    gap = gap or (lambda read: read())   # no server around it (a test, a retry's own check): read at once
    if cases is None:
        # the examples' crop goes on down past the gaps between examples, so a box ended above the last one
        # still has it read (READ_REACH); it is read here and never sent
        images = (await read_images(frame, outcome.crop_box, getattr(outcome, "local_view", None), READ_REACH)
                  or [frame.model_b64, *frame.extra_b64])
        cases = await gap(lambda: local.cases(images))
        if note is not None:
            note["read"] = examples_in(cases)
        if cases.get("cases") or cases.get("stdin") or cases.get("class"):   # only what the problem writes (seen_cases)
            text = await gap(lambda: local.extract(images))
            if missed_examples(cases, text):
                # The text stopped short of the examples (it is read with sampling, and one reading in 51 of the bench's
                # coding screens ended at 305 characters with the example table left out, the next at 418 with it,
                # scratch/local-llm-bench/check_read.py): read once more, and that reading is the one judged by.
                log.info("code check: the problem's text has no example section and none of the %d example(s) read; "
                         "reading it once more", examples_in(cases))
                text = await gap(lambda: local.extract(images)) or text
            cases = seen_cases(cases, text)
            if note is not None:
                note.update(kept=examples_in(cases), text_chars=len(text or ""),
                            heading=bool(text and EXAMPLES_HEAD_RE.search(text)))
            if cases.get("unseen"):   # which ones, so a left-out example can be told from a misread one
                log.info("code check: %d example(s) read off the screen are not in the problem's text; left out: %s",
                         cases["unseen"], "; ".join(repr(w)[:90] for w in (cases.get("left") or ())))   # repr: an input's own line breaks broke the log's lines
    res = await run_cases(outcome.text, cases, run)
    if res is None and not examples_in(cases) and not cases.get("class") and local is not None:
        # No examples to judge by: the code is still run, on a few small inputs this PC's model makes up for the
        # problem (analyzer.EXTRACT_PROBES), to see that it ends in time without an error. What it returns is not
        # judged, so a run that fails says so without asking for a retry (the input made up may be the one at fault).
        images = (await read_images(frame, outcome.crop_box, getattr(outcome, "local_view", None), READ_REACH)
                  or [frame.model_b64, *frame.extra_b64])
        made = await gap(lambda: local.probes(images))
        if (made.get("cases") and made.get("function")) or made.get("stdin"):
            res = await run_cases(outcome.text, {**made, "probe": True}, run)
            if note is not None:
                note["probes"] = len(made.get("cases") or made.get("stdin") or ())
            if res is not None and "skipped" in res:
                # made-up inputs that do not fit the code (another function's name, a program's input for a
                # function): a reason about them read as one about the problem's own examples, so nothing is said
                return None
            if res is not None:
                res["probe"] = True   # an error too says it came from made-up inputs (the card, the report)
                return res        # no "cases": nothing here is for a retry to be checked against
    if res is not None:
        res["cases"] = cases
    return res


def missed_examples(cases: dict, text: str) -> bool:
    """The problem's text read for the cross-check (seen_cases) has no example heading, and nothing of the examples
    read off the same images is written anywhere in it: the reading stopped before the examples, not a screen without
    them. A picture of a problem with no example table still has its statement, and what the statement illustrates
    is in its text (such as "aabbaccc"), so it is not read again for nothing. No text at all keeps the
    examples as read (seen_cases), so it is never missed.

    What counts as written is not seen_cases' rule, which keeps an example made only of numbers inside lists once a
    heading is there at all ("too common to tell anything" as a check of each example), so that over a text with no
    heading every such example looked written and a text cut short was never read again: here a
    string of two characters or more, a line of standard input, or the run of numbers of a list or a line, three or
    more of them in a row, has to be found. A lone number or a short list says nothing either way and does not
    count."""
    if not text or EXAMPLES_HEAD_RE.search(text) or not examples_in(cases):   # judged by as it is (seen_cases)
        return False
    flat = re.sub(r"\s+", " ", text.replace("“", '"').replace("”", '"'))    # spaced and quoted as seen_cases reads it
    numbers = _numbers_of(flat)                                              # the text's numbers, for the lists' runs
    return not any(_shows(flat, numbers, value) for value in _example_values(cases))


def _example_values(cases: dict) -> list:
    """What each example of a reading is made of, to look for in a text: a class problem's name, calls and their
    arguments, a function call's arguments, a standard-input run's input."""
    if cases.get("class"):   # the class, the calls of its example and what they are called with
        return [cases["class"], *(cases.get("calls") or []), *(cases.get("args") or [])]
    runs = cases.get("cases") if isinstance(cases.get("cases"), list) else cases.get("stdin")
    out = []
    for run in runs if isinstance(runs, list) else ():
        if isinstance(run, dict) and "args" in run:   # a function call: each of its arguments
            out.extend(run.get("args") or [])
        elif isinstance(run, dict):                   # a standard-input run: its input as written
            out.append(str(run.get("input", "")))
        else:                                         # read in some other shape: looked for as it is
            out.append(run)
    return out


def _numbers_of(text: str) -> list:
    """The numbers written in a text, in order, as floats."""
    return [float(m.group()) for m in NUMBER_TEXT.finditer(text)]


def _shows(flat: str, numbers: list, value) -> bool:
    """Whether a text (`flat`, its runs of spaces made one; `numbers`, the numbers in it in order) shows something of
    an example's `value` (missed_examples): a string of two characters or more written as a whole word, or one of its
    lines; the numbers of a list, three or more, found one after another among the text's."""
    if isinstance(value, str):
        # each line of it, spaced as the text is: a word, a phrase, or one line of standard input
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in value.splitlines()] or [""]
        if any(len(ln) >= 2 and _written(flat, ln) for ln in lines):   # one character says nothing
            return True
        run = _numbers_of(value)   # a run of standard input: its numbers, in order, however they are spaced
        return len(run) >= 3 and _in_order(run, numbers)
    if isinstance(value, (list, tuple, dict)):
        scalars = _scalars(value)   # opened up, nested lists too
        if any(isinstance(v, str) and _shows(flat, numbers, v) for v in scalars):   # a string inside it
            return True
        # its numbers in order, as a table writes the list ([2, 1, 3] or 2 1 3); three at least, as fewer turn up anywhere
        run = [float(v) for v in scalars if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return len(run) >= 3 and _in_order(run, numbers)
    return False   # a lone number or anything else: says nothing either way


def _in_order(run: list, numbers: list) -> bool:
    """`run` found one after another in `numbers`."""
    n = len(run)
    return any(numbers[i:i + n] == run for i in range(len(numbers) - n + 1))   # each place it could start


def examples_in(cases: dict) -> int:
    """How many examples a reading holds: the calls of a class problem's example, else its function calls or its
    standard-input runs."""
    if not isinstance(cases, dict):
        return 0
    if cases.get("class"):
        return len(cases.get("calls") or ())
    runs = cases.get("cases") if isinstance(cases.get("cases"), list) else cases.get("stdin")
    return len(runs) if isinstance(runs, list) else 0


def _written(text: str, value: str) -> bool:
    """`value` written in `text` as a whole, not inside a longer word ("abcde" is in "abcabcdede", but not written there)."""
    return re.search(r"(?<![0-9A-Za-z가-힣_])" + re.escape(value) + r"(?![0-9A-Za-z가-힣_])", text) is not None


def _number_written(text: str, value) -> bool:
    """The number `value` written in `text` as a number of its own, compared by value: 2.0 is the "2.00000" of
    LeetCode 50's examples, which was looked for as "2.0" and missed."""
    for m in re.finditer(r"(?<![0-9A-Za-z가-힣_.])[-+]?\d+(?:\.\d+)?(?![0-9A-Za-z가-힣_])", text):
        try:
            if abs(float(m.group()) - float(value)) <= 1e-9 * max(1.0, abs(float(value))):
                return True
        except ValueError:
            continue
    return False


NUMBER_TEXT = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _expected_as_shown(case: dict, flat: str) -> dict:
    """An example whose expected value came off the screen as a number in quotes ("7"), as the problem shows it: a
    number where the statement writes it bare (7), text where it writes it in quotes ("94", a problem whose answer is a
    string of digits). It counted a right answer as wrong once, and the fix that read every quoted number as a number
    passed an answer that returned 94 where "94" was asked for."""
    e = case.get("expected")
    if not (isinstance(e, str) and NUMBER_TEXT.fullmatch(e.strip()) and flat):
        return case
    v = e.strip()
    if re.search("[\"']" + re.escape(v) + "[\"']", flat) or not _written(flat, v):
        return case
    return {**case, "expected": int(v) if re.fullmatch(r"[-+]?\d+", v) else float(v)}


def _scalars(value) -> list:
    """The strings and numbers an example's argument is made of (lists and dicts opened up)."""
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _scalars(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _scalars(v)]
    return [value]


# Where a problem's examples are written: "I/O examples" (Programmers), "example input/output" (Baekjoon), "input sample" (SW Expert),
# "input example" and "output example" with no number after them, Example 1 (LeetCode), For example (Codility), Sample Input, Examples
# (Codeforces), "test case", and a bare Korean "Ex:" or "Ex)" that opens one. Not the Korean "for example", "as an example": a statement's
# illustration of what it means, which is how "aabbaccc" -> "2a2ba3c" came to be taken for an example of a function
# that returns 7.
EXAMPLES_HEAD_RE = re.compile(r"입출력\s*예|예제\s*(?:입력|출력|\d)|(?:입력|출력)\s*예(?:시|제|\s*\d)|예시\s*(?:입력|출력|\d)|"
                              r"\bExamples?\b|\bSample\s+(?:Input|Output|Test|\d)|\bInput\s+\d|테스트\s*케이스|(?<![가-힣])예\s*[:)]", re.I)


def seen_cases(cases: dict, text: str) -> dict:
    """The examples read off the screen that are written in the problem's own example section (`text`: the same
    images written out). A screen with no example table on it (a picture of a problem, its examples scrolled away)
    came back with examples of the model's own, "aabbbcccc" -> 4 and "abcde" -> "5", and then with the
    statement's illustration taken for examples ("aabbaccc" -> "2a2ba3c", the compressed string where the problem
    asks for its length): the right answer failed them, one retry ran away, and another rewrote the right answer
    to fit them. So the inputs have to be written after an example heading (EXAMPLES_HEAD_RE), and with
    no such heading in the text nothing is checked. Strings of two characters or more are looked for as whole
    words, and so is a number that stands as an argument of its own (one inside a list is too common to tell
    anything); a line of standard input has to be there, spaces aside. No text at all keeps the examples."""
    if not text or not isinstance(cases, dict):
        return cases
    head = EXAMPLES_HEAD_RE.search(text)
    flat = re.sub(r"\s+", " ", text[head.start():].replace("“", '"').replace("”", '"')) if head else ""
    # A string is looked for with its runs of spaces made one, as the text is: "  hello world  " (LeetCode 151, where
    # the spaces are the point) was looked for as it was and never found
    fold = lambda w: re.sub(r"\s+", " ", w)   # noqa: E731
    if cases.get("class"):
        # A problem that asks for a class: its name and the calls of the example have to be written after the
        # heading. It was not looked at at all, and a Min Stack whose example had scrolled away was run on calls the
        # model made up, the right answer failed one and a retry was asked for.
        names = [str(cases["class"])] + [n for n in (cases.get("calls") or []) if isinstance(n, str)]
        words = [fold(w).strip() for w in names if str(w).strip()]
        words += [fold(v) for a in (cases.get("args") or []) for v in _scalars(a) if isinstance(v, str) and len(v) >= 2]
        missing = [w for w in dict.fromkeys(words) if not (flat and _written(flat, w))]
        if not missing:
            return cases
        return {**cases, "class": None, "unseen": 1, "left": [", ".join(missing)[:80]]}
    if isinstance(cases.get("cases"), list):
        kept, left = [], []
        for case in cases["cases"]:
            args = case.get("args") if isinstance(case, dict) else None
            words = [fold(v) for a in (args if isinstance(args, list) else []) for v in _scalars(a)
                     if isinstance(v, str) and len(v) >= 2]
            numbers = [a for a in (args if isinstance(args, list) else [])
                       if isinstance(a, (int, float)) and not isinstance(a, bool)]
            missing = [w for w in words if not (flat and _written(flat, w))]
            missing += [str(n) for n in numbers if not (flat and _number_written(flat, n))]
            if flat and not missing:
                kept.append(_expected_as_shown(case, flat))
            else:   # for the log: the words it looked for and did not find
                left.append(", ".join(missing)[:80] or "?")
        return {**cases, "cases": kept, "unseen": len(cases["cases"]) - len(kept), "left": left}
    if isinstance(cases.get("stdin"), list):
        kept = [c for c in cases["stdin"] if flat and isinstance(c, dict) and all(
            re.sub(r"\s+", " ", line).strip() in flat for line in str(c.get("input", "")).splitlines() if line.strip())]
        left = [str(c.get("input", "") if isinstance(c, dict) else c)[:80] for c in cases["stdin"] if c not in kept]
        return {**cases, "stdin": kept, "unseen": len(cases["stdin"]) - len(kept), "left": left}
    return cases


def retry_request(res: dict) -> tuple[str, str]:
    """After a failed example: (what the model is asked, what the panel shows). One retry, by the
    engine that wrote the answer, with the failing examples in the request."""
    fails = res.get("fails") or []
    # a problem that asks for a class failed on a call of the statement's own example, not on an input
    call = res.get("how") == "design"
    where = "호출" if call else "입력"
    lines = "\n".join(f"- {where} {f.get('input') if call else json.dumps(f.get('input'), ensure_ascii=False)}:"
                      f" 기대 {json.dumps(f.get('expected'), ensure_ascii=False)},"
                      f" 실제 {json.dumps(f.get('got'), ensure_ascii=False)}" for f in fails)
    question = (f"[예제 실패] 앞 풀이의 코드를 문제의 {'예제 호출' if call else '입출력 예'}로 돌려 보니 "
                f"{res.get('total', 0)}개 중 {res.get('passed', 0)}개만 맞았습니다. 맞지 않은 "
                f"{'호출' if call else '예'}:\n{lines}\n원인을 찾아 고친 뒤, 문제의 예를 모두 통과하는 전체 코드를 "
                f"다시 쓰세요. 여기서는 코드를 실행하거나 도구를 쓸 수 없으니, 맞지 않은 예를 손으로 따라가 원인을 "
                f"찾고 고친 코드를 바로 쓰세요.")
    first = fails[0] if fails else {}
    label = t("An example failed, solving again ({where} {input}: expected {expected}, got {got})",
              where=t("call") if call else t("input"),
              input=first.get("input") if call else json.dumps(first.get("input"), ensure_ascii=False),
              expected=json.dumps(first.get("expected"), ensure_ascii=False),
              got=json.dumps(first.get("got"), ensure_ascii=False))
    return question, label[:300]


