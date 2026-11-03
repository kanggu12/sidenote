"""Change detector: decides whether a frame is a *new* screen worth analyzing.

Combines a pixel signature (background-invariant, layout-sensitive, cheap) with
optional OCR text comparison (content-sensitive). Modes:

  signature : pixel signature only (no OCR).
  ocr       : OCR text only.
  hybrid    : fire when EITHER pixel OR text changed (OCR consulted only when the
              pixel signature looks unchanged, the ambiguous case, so OCR stays cheap).
  auto      : hybrid when an OCR engine is available, else signature.

State (last analyzed signature/text) is updated via commit(), called when an
analysis actually completes, so a cancelled analysis does not suppress a retry.

Once an answer says where its problem is on screen (its REGION line, set_region()),
a frame counts as new only if that region changed: typing in an editor beside the
problem, a video or another window in use no longer re-runs the same problem, while
a small change inside the problem (the next question on the same template) does.
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from difflib import SequenceMatcher

import numpy as np

from .gate import SIG_SIZE, distance, region_distance

# What is moving on the screen right now is left out of every comparison below, for as long as it keeps moving: a
# video call in a corner, an animation, a clock. With a still problem beside a video, each frame the capture
# program sent counted as a new screen (the whole-screen distance is a mean over every cell, and a moving video
# alone passes the threshold), so the same problem was solved again and again (three times in two
# minutes, once with its agent turn cut off by the next frame). A cell is moving when its edge value changed by
# more than LIVE_STEP in at least LIVE_MIN of the last LIVE_STEPS steps from frame to frame. It was "in each of
# the last two", and a person in a call moves now and then rather than at every frame: on a rehearsed call beside
# an exam page that mask held 21 to 236 of the call's cells, the distance from the screen being
# analyzed wandered up to 0.52, and the analysis was cut off with its agent turn under way; counted over the last
# four steps it stays under 0.26, while a problem that appears (one step of change) is never left out (2.4).
# Only while frames keep coming: once the screen has been still for LIVE_FRESH seconds nothing is moving, so a
# scroll that has stopped is compared in full and counts as the change it is.
LIVE_STEP = 12
LIVE_STEPS = 4
LIVE_MIN = 2
LIVE_FRESH = 3.0


LIVE_MARGIN = 2   # cells round the moving ones also left out of "the screen being driven" (observe)


def grown(mask, n: int):
    """`mask` (a bool array, or None) with every cell within `n` cells of a marked one marked too."""
    if mask is None or n <= 0:
        return mask
    g = mask
    for _ in range(n):
        h = g.copy()
        h[1:, :] |= g[:-1, :]
        h[:-1, :] |= g[1:, :]
        h[:, 1:] |= g[:, :-1]
        h[:, :-1] |= g[:, 1:]
        g = h
    return g


def masked_distance(a: bytes, b: bytes, live, region=None) -> float:
    """distance() or region_distance(), leaving out the cells in `live` (a bool array the signature's shape, or None
    for nothing left out). With nothing left out the result is exactly theirs."""
    if live is None or not live.any():
        return region_distance(a, b, region) if region is not None else distance(a, b)
    if not a or not b or len(a) != len(b):
        return 255.0
    w, h = SIG_SIZE
    d = np.abs(np.frombuffer(a, np.uint8).astype(np.int16) - np.frombuffer(b, np.uint8).astype(np.int16)).reshape(h, w)
    keep = ~live
    if region is not None:   # the same cells region_distance reads
        c0, r0 = min(w - 1, int(region[0] * w)), min(h - 1, int(region[1] * h))
        c1, r1 = max(c0 + 1, min(w, -int(-region[2] * w))), max(r0 + 1, min(h, -int(-region[3] * h)))
        d, keep = d[r0:r1, c0:c1], keep[r0:r1, c0:c1]
    n = int(keep.sum())
    return float(d[keep].sum()) / n if n else 0.0   # all of it moving: nothing still to compare, so no change

log = logging.getLogger("sidenote.detector")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def text_distance(a: str, b: str) -> float:
    """1 - similarity ratio of two normalized strings (0 = identical)."""
    a, b = _norm(a), _norm(b)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    return 1.0 - SequenceMatcher(None, a, b).ratio()


class ChangeDetector:
    def __init__(self, cfg, ocr=None):
        self.cfg = cfg
        self.ocr = ocr if (ocr and getattr(ocr, "available", False)) else None
        self.last_sig: bytes | None = None
        self.last_text: str | None = None
        self.last_extra_sig: bytes | None = None  # last analyzed scroll-stitched content
        self.region: tuple[float, float, float, float] | None = None  # answered problem, fractions
        self._prev: np.ndarray | None = None       # the last frame's signature, as numbers
        self._prev_sig: bytes = b""                # and as it came, for the distance functions
        self._steps: deque = deque(maxlen=LIVE_STEPS)   # the cells that moved, step by step, the latest last
        self._live: np.ndarray | None = None       # the cells that moved in at least LIVE_MIN of those steps
        self._seen_at = 0.0                        # when the last frame came
        mode = cfg.gate
        if mode == "auto":
            mode = "hybrid" if self.ocr else "signature"
        if mode in ("ocr", "hybrid") and self.ocr is None:
            mode = "signature"
        self.mode = mode
        log.info("change detector mode=%s", self.mode)

    def _text(self, frame) -> str:
        # OCR text is precomputed in the ingest executor (app.prepare_frame),
        # so reading it here never blocks the event loop.
        return getattr(frame, "ocr_text", "") or ""

    def observe(self, frame, now: float | None = None) -> bool:
        """Every frame the capture program sends, as it comes: which cells are moving right now. Returns whether the
        frame changed from the one before it anywhere but in the cells that were moving already: the screen being
        driven (app.stamp_frame), where a video beside a still screen is not. Without that the video's frames kept
        the screen from ever coming to rest, and each analysis waited the longest settle (8 s) before it started."""
        now = time.time() if now is None else now
        sig = getattr(frame, "sig", b"") or b""
        cur = np.frombuffer(sig, np.uint8).astype(np.int16) if sig else None
        changed = True
        if cur is not None and self._prev is not None and cur.shape == self._prev.shape:
            # against the cells moving before this frame, so a change that starts with it is never left out
            # Outside the moving cells and two cells round them: a video's face wanders a little beyond the cells it
            # moved in, and over those it read as the screen being driven (0.08 to 0.30 a frame; 0.01 to 0.08 with
            # the margin), while a line typed into an editor changes 0.19 to 0.23
            changed = masked_distance(sig, self._prev_sig, grown(self.live(now), LIVE_MARGIN)) >= self.cfg.driven_threshold
            self._steps.append((np.abs(cur - self._prev) > LIVE_STEP).reshape(SIG_SIZE[1], SIG_SIZE[0]))
            moved = np.sum(np.stack(self._steps), axis=0)       # how many of the last steps each cell moved in
            self._live = moved >= LIVE_MIN if len(self._steps) >= LIVE_MIN else None
        else:
            self._steps.clear()
            self._live = None
        self._prev, self._prev_sig = cur, sig
        self._seen_at = now
        return changed

    def live(self, now: float | None = None):
        """The cells moving right now, or None: none, or the screen has been still for LIVE_FRESH seconds."""
        now = time.time() if now is None else now
        return self._live if self._live is not None and now - self._seen_at <= LIVE_FRESH else None

    def is_new(self, frame) -> bool:
        extra = getattr(frame, "extra_sig", None)
        if extra is not None and (self.last_extra_sig is None
                                  or distance(extra, self.last_extra_sig) >= self.cfg.change_threshold):
            return True  # a newly scrolled-together problem is always worth a look
        # The OCR modes (opt-in) keep their own text comparison; the region applies to the
        # default pixel gate.
        live = self.live()
        if self.mode == "signature" and self.region is not None and self.last_sig is not None:
            return masked_distance(frame.sig, self.last_sig, live, self.region) >= self.cfg.region_threshold
        pixel_changed = (
            self.last_sig is None or masked_distance(frame.sig, self.last_sig, live) >= self.cfg.change_threshold
        )
        if self.mode == "signature":
            return pixel_changed
        if self.mode == "hybrid" and pixel_changed:
            return True  # clear visual change; no need to OCR
        text = self._text(frame)
        return self.last_text is None or text_distance(text, self.last_text) >= self.cfg.text_threshold

    def jumped(self, frame) -> float:
        """How far this screen is from the one analyzed last, over the whole screen.

        is_new() answers yes or no and, once a problem's region is known, looks only inside it. This
        is the raw distance and always the whole screen, because what it is for is the opposite
        question: while the watching has gone quiet after a run of empty answers, has the screen
        changed wholesale (another window, another page) rather than a little? Nothing analyzed yet
        counts as the largest possible change, so the first screen is never held back."""
        if self.last_sig is None:
            return 255.0
        return masked_distance(frame.sig, self.last_sig, self.live())

    def set_region(self, region: tuple[float, float, float, float] | None) -> None:
        """Where the problem answered last is on screen (None: unknown or no problem)."""
        self.region = region

    def moved_on(self, analyzing, frame) -> bool:
        """Has the screen moved on from the frame being analyzed? Inside the answered problem's
        region when one is known: a video or another window in use beside the problem is no
        reason to throw away an answer in progress."""
        live = self.live()
        if self.mode == "signature" and self.region is not None:
            return masked_distance(frame.sig, analyzing.sig, live, self.region) >= self.cfg.region_threshold
        return masked_distance(frame.sig, analyzing.sig, live) >= self.cfg.change_threshold

    def commit(self, frame) -> None:
        self.last_sig = frame.sig
        if getattr(frame, "extra_sig", None) is not None:
            self.last_extra_sig = frame.extra_sig
        if self.mode != "signature":
            self.last_text = self._text(frame)


def make_detector(cfg, ocr):
    return ChangeDetector(cfg, ocr)
