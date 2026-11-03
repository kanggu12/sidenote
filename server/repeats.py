"""Telling a problem seen again from a new one, by its picture.

The screen's own duplicate check (the change detector watching the last answer's box) only knows whether that part
of the screen changed. Scrolled, moved, or come back to after another screen, the same problem stands somewhere else,
the first pass reads it as a problem again, and it is solved again: a knight-move problem three times in
nine minutes and a multiplication twice, each time with a thinking pass of 20 to 60 seconds.

This keeps small grey pictures of the problems answered lately and looks for them in the box the first pass gives a
new screen, wherever they sit in it, by normalized cross-correlation (the same measure template matching uses). The
picture is matched in horizontal bands, apart, so a code editor typed in beside or under the statement does not hide
it: the problem is the same when most of its bands are found, at offsets that agree with one another. It is matched
both ways (the stored picture in the new box, and the new box's picture in the stored one with its margin), so a box
drawn wider or narrower the second time still meets the first.
"""
from __future__ import annotations

import base64          # the screen arrives as a base64 PNG
import difflib         # how close two readings of a problem's words are
import io              # decoded in memory
import json            # what is kept over a restart, beside its pictures
import os              # the kept file replaced whole
import re              # a problem's words and numbers
import time            # when each problem was answered, so old ones are forgotten
from dataclasses import dataclass

import numpy as np     # the correlation, by FFT
from PIL import Image  # the crops

# The width the screen is brought to before anything is compared: the same for every screen, so a problem keeps its
# size in pixels from one screen to the next. 1200 keeps a 4K screen's 16 px text at about 5 px, enough for the lines
# and the words to correlate, and makes a box's search a few tens of milliseconds (calibration: docs/ARCHITECTURE.md,
# design note 88).
WORK_WIDTH = 1600
BAND_PX = 24           # about how tall a band is: a box is cut into its height / BAND_PX bands, 3 to 8
MIN_BANDS = 3          # with fewer bands that hold anything, nothing is decided (and the problem is solved as before)
MATCH = 0.70           # a band is found where its correlation reaches this (calibrated, note 88)
AGREE_PX = 4           # how far apart (in work pixels) two found bands may be from where the picture puts them
MARGIN = 0.12          # how much is kept around a stored box, so the new box can be looked for in it as well
FLAT = 4.0             # a band whose detail varies less than this (out of 255) is blank: it counts neither way
BLUR = 9               # the side (work pixels) of the box blur whose difference keeps only the detail
KEEP = 6               # problems remembered
WHOLE_LATEST = 1       # of them, how many are also looked for over the whole screen, on every new problem: the one seen again after a window is
                       # dragged is nearly always the last, and a look may cost no more than a second on a slower machine than this one
# Bands are too coarse to see one digit: a problem with one number changed scored 0.999. So once the
# bands agree the picture is compared piece by piece at that place. A scroll that lands the text between pixels blurs
# every piece about alike, and a changed glyph falls away from the rest, so a piece is judged against the picture's
# median, with the room that blur itself takes (calibration on 4K renders drawn at 1600: note 93).
TILE_W, TILE_H = 36, 24   # work pixels: about three digits wide at a 4K screen's text
TILE_SLACK = 2            # how far a piece may sit from the place the bands found, in work pixels
TILE_DETAIL = 8.0         # a piece whose detail varies less than this holds no glyph to compare
TILE_BLUR = 1.25          # how many times the median's own loss a piece may lose on top of it
TILE_MEDIAN = 0.6         # the median piece must reach this, whatever the others do. Measured on 29 real screens: different problems
                          # that passed the bands had 0.06 to 0.43 where the text differs, the same problem moved or re-encoded 0.85 to 1.0
TILE_ROOM = 0.015         # and this much, for the noise of a picture that is otherwise identical
TTL = 30 * 60.0        # seconds a problem is remembered


# The problem read out as words, for the agent: a second way to know it, when the picture has nothing to go on (the first
# pass on a busy GPU gave no box) or the screen scrolled far. Read twice the words differ a little, and a problem of
# the same template differs in its numbers, so the words have to be close and the numbers the same.
WORDS_MIN = 40         # characters: shorter says too little to tell a problem by
WORDS_SAME = 0.85      # how much of the words have to match (difflib's ratio, spaces and marks left out)
WORDS_RUN = 6          # characters: a longer run that differs is another sentence, not a misreading ("main idea" and "tone")
# Words that turn a problem into its opposite while hardly changing its letters. Each has to appear as often in both.
TURNS = ("않", "아닌", "틀린", "옳", "최소", "최대", "최솟", "최댓", "작은", "큰", "많은", "적은", "이상", "이하", "초과", "미만", "없", "오름", "내림",
         "not", "except", "false", "true", "incorrect", "correct", "minimum", "maximum", "smallest", "largest", "least", "most",
         "ascending", "descending", "increasing", "decreasing", "greater", "less")
# An operator between two operands: a list's dash or a bold mark has nothing on its left in the same line
_OPERATORS = re.compile(r"(?<=[\w)\]])[ \t]*([-+*/%^=<>≤≥≠×÷]+)[ \t]*(?=[\w(\[-])")


def same_words(a: str, b: str) -> float:
    """How close two readings of a problem are, 0 when anything says they are two problems: too short to tell, other
    numbers or the same numbers in another order, other operators, a word that turns the question round, or a run of
    text that differs. Calling a new problem the same loses its answer, while calling the same one new only solves
    it again, so all of these refuse ("128 + 57" and "128 - 57", "<" and ">",
    "옳은 것은" and "옳지 않은 것은" had all passed at over 0.96)."""
    a, b = a or "", b or ""
    flat = lambda t: re.sub(r"[\W_]+", "", t).lower()  # noqa: E731
    x, y = flat(a), flat(b)
    if min(len(x), len(y)) < WORDS_MIN:
        return 0.0
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):         # every number, in order
        return 0.0
    if _OPERATORS.findall(a) != _OPERATORS.findall(b):         # every operator, in order
        return 0.0
    if any(x.count(w) != y.count(w) for w in TURNS):           # the words are lower-cased in x and y
        return 0.0
    match = difflib.SequenceMatcher(None, x, y, autojunk=False)
    # The cheap bounds first: this is quadratic in the length, seconds at some thousands of characters
    if match.real_quick_ratio() < WORDS_SAME or match.quick_ratio() < WORDS_SAME:
        return 0.0
    # Word by word, for what differs: letter by letter "mainidea" and "tone" share enough letters to leave no long run
    wa, wb = re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())
    words = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    for tag, i1, i2, j1, j2 in words.get_opcodes():
        if tag == "equal":
            continue
        u, v = "".join(wa[i1:i2]), "".join(wb[j1:j2])
        kept = sum(m.size for m in difflib.SequenceMatcher(None, u, v, autojunk=False).get_matching_blocks())
        if max(len(u), len(v)) - kept >= WORDS_RUN:    # "하나뿐입니다" and "하나입니다" keep most of their letters; "main idea" and "tone" do not
            return 0.0
    return match.ratio()


def _detail(img: np.ndarray, k: int = BLUR) -> np.ndarray:
    """The image less its k by k box blur: the strokes of the text and the lines, without the large light and dark
    areas. Without this the correlation measured the layout (a white window beside a dark one) more than the words,
    and two unrelated screens of the same layout matched at 0.95 (calibration, note 88)."""
    pad = k // 2
    p = np.pad(img, pad, mode="edge")
    c = np.pad(p, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    h, w = img.shape
    blur = (c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]) / (k * k)
    return img - blur


def screen_image(model_b64: str) -> np.ndarray:
    """The screen as the model saw it, grey, at WORK_WIDTH wide, its detail only (_detail), as float32."""
    img = Image.open(io.BytesIO(base64.b64decode(model_b64))).convert("L")
    if img.width != WORK_WIDTH:
        img = img.resize((WORK_WIDTH, max(1, round(img.height * WORK_WIDTH / img.width))), Image.BILINEAR)
    return _detail(np.asarray(img, dtype=np.float32))


def _pixels(box, view, shape, margin: float = 0.0) -> tuple[int, int, int, int]:
    """A box in screen fractions as pixel bounds in an image of the view (the part of the screen it shows), with
    `margin` of the box's own size added on every side, clamped to the image."""
    vx0, vy0, vx1, vy1 = view
    vw, vh = max(1e-6, vx1 - vx0), max(1e-6, vy1 - vy0)
    x0, y0, x1, y1 = ((box[0] - vx0) / vw, (box[1] - vy0) / vh, (box[2] - vx0) / vw, (box[3] - vy0) / vh)
    mx, my = (x1 - x0) * margin, (y1 - y0) * margin
    h, w = shape
    return (max(0, int((x0 - mx) * w)), max(0, int((y0 - my) * h)),
            min(w, int(round((x1 + mx) * w))), min(h, int(round((y1 + my) * h))))


def _bands(img: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """The picture cut into horizontal bands (its height / BAND_PX of them, 3 to 8), a little trimmed at the sides
    (a box's edge is where two runs of the first pass differ most), each with its top row; blank bands are left out."""
    h, w = img.shape
    trim = int(w * 0.04)
    n = max(3, min(8, h // BAND_PX))
    out = []
    for k in range(n):
        top, bottom = h * k // n, h * (k + 1) // n
        band = img[top:bottom, trim:w - trim]
        if band.shape[0] >= 8 and band.shape[1] >= 16 and float(band.std()) >= FLAT:
            out.append((top, band))
    return out


class _Search:
    """An image to look for bands in, with what every band's correlation needs from it worked out once: its FFT (at
    a size that fits the tallest and widest band) and the summed-area tables of it and of its square."""

    def __init__(self, image: np.ndarray, bands: list):
        self.image = image
        H, W = image.shape
        self.hmax = max((b.shape[0] for _, b in bands), default=1)
        self.wmax = max((b.shape[1] for _, b in bands), default=1)
        self.shape = (H + self.hmax - 1, W + self.wmax - 1)
        self.f = np.fft.rfft2(image, self.shape)
        self.s = np.pad(image, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        self.s2 = np.pad(image * image, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def ncc_map(self, tmpl: np.ndarray) -> np.ndarray | None:
        """The normalized cross-correlation of `tmpl` at every place it fits (rows by columns of its top-left
        corner); None when it does not fit or holds nothing."""
        H, W = self.image.shape
        h, w = tmpl.shape
        if h > H or w > W:
            return None
        t = tmpl - tmpl.mean()
        tn = float(np.sqrt((t * t).sum()))
        if tn < 1e-6:
            return None
        # the correlation of the zero-mean template with every window, through the FFT
        corr = np.fft.irfft2(self.f * np.fft.rfft2(t[::-1, ::-1], self.shape), self.shape)[h - 1:H, w - 1:W]
        win = lambda a: a[h:, w:] - a[:-h, w:] - a[h:, :-w] + a[:-h, :-w]   # noqa: E731  (each window's sum)
        n = h * w
        var = np.maximum(win(self.s2) - win(self.s) ** 2 / n, 1e-6)      # each window's own spread
        score = corr / (np.sqrt(var) * tn)
        # a flat window (a blank part of the screen) has no spread to divide by: it matches nothing
        score[var < (FLAT ** 2) * n] = 0.0
        return score


def _ncc(image: np.ndarray, tmpl: np.ndarray) -> tuple[float, int, int]:
    """The best normalized cross-correlation of `tmpl` anywhere inside `image`, and where: (score, x, y)."""
    score = _Search(image, [(0, tmpl)]).ncc_map(tmpl)
    if score is None:
        return 0.0, 0, 0
    y, x = divmod(int(np.argmax(score)), score.shape[1])
    return float(score[y, x]), x, y


def same_picture(picture: np.ndarray, search: np.ndarray) -> tuple[bool, float]:
    """Whether `picture` (a problem's box) is found in `search`: every band that holds anything found at MATCH or
    better, all at one place, except that with four or more one may differ (an editor typed in, a cursor). Fewer
    than MIN_BANDS such bands decide nothing. Wrongly calling a new problem the same costs its answer, so this is
    strict: a box that is mostly a window's frame or a taskbar, shared by every screen of a desktop, is told apart
    by the rest of its bands (calibration, note 88).

    The place is put forward by each band's own best match, and then every band is scored near that place (within
    AGREE_PX), not wherever it matches best: a line that repeats (a table's rule, a heading of the same site) can
    score higher somewhere else than where it is. Returns (found, the lowest band score at the place chosen)."""
    bands = _bands(picture)
    if len(bands) < MIN_BANDS:
        return False, 0.0
    need = len(bands) if len(bands) <= 3 else len(bands) - 1
    maps = []
    where = _Search(search, bands)
    unfound = 0
    for top, band in bands:
        m = where.ncc_map(band)
        if m is None:
            return False, 0.0          # the picture is larger than where it is looked for: the other way may fit
        # A band that reaches MATCH nowhere cannot reach it at any one place, so with one too many of those the answer is known. Most
        # looks are at a new problem and end here, after two bands of up to eight: it is what pays for searching the whole screen
        unfound += float(m.max()) < MATCH
        if unfound > len(bands) - need:
            return False, 0.0
        maps.append((top, m))
    places = set()
    for top, m in maps:                # where the picture's top-left would be, by each band's best match
        y, x = divmod(int(np.argmax(m)), m.shape[1])
        places.add((x, y - top))
    best = (0, 0.0)
    place = None
    for ox, oy in places:
        scores = []
        for top, m in maps:
            y0, x0 = max(0, oy + top - AGREE_PX), max(0, ox - AGREE_PX)
            window = m[y0:max(y0, oy + top + AGREE_PX + 1), x0:max(x0, ox + AGREE_PX + 1)]
            scores.append(float(window.max()) if window.size else 0.0)
        hits = sum(1 for v in scores if v >= MATCH)
        low = sorted(scores, reverse=True)[need - 1]     # the score the decision rests on
        if (hits, low) > best:
            best = (hits, low)
            place = (ox, oy)
    if best[0] < need or place is None:
        return False, best[1]
    # The bands were trimmed at the sides, so the picture's own left edge stands that much further left
    return _pieces_agree(picture, search, place[0] - int(picture.shape[1] * 0.04), place[1]), best[1]


def _pieces_agree(picture: np.ndarray, search: np.ndarray, left: int, top: int) -> bool:
    """Whether every piece of `picture` that holds a glyph is found where the picture, placed at (left, top) of
    `search`, puts it. Pieces outside `search` count neither way."""
    H, W = picture.shape
    SH, SW = search.shape
    scores = []
    for y in range(0, H - TILE_H + 1, TILE_H // 2):        # half-overlapping, so a digit is never cut in two everywhere
        for x in range(0, W - TILE_W + 1, TILE_W // 2):
            tile = picture[y:y + TILE_H, x:x + TILE_W]
            if float(tile.std()) < TILE_DETAIL:
                continue
            t = tile - tile.mean()
            tn = float(np.sqrt((t * t).sum()))
            best = None
            for dy in range(-TILE_SLACK, TILE_SLACK + 1):
                for dx in range(-TILE_SLACK, TILE_SLACK + 1):
                    y0, x0 = top + y + dy, left + x + dx
                    if y0 < 0 or x0 < 0 or y0 + TILE_H > SH or x0 + TILE_W > SW:
                        continue
                    w = search[y0:y0 + TILE_H, x0:x0 + TILE_W]
                    w = w - w.mean()
                    wn = float(np.sqrt((w * w).sum()))
                    v = float((t * w).sum()) / (tn * wn) if wn > 1e-6 else 0.0
                    best = v if best is None else max(best, v)
            if best is not None:
                scores.append(best)
    if len(scores) < 4:          # too little in view to say anything: not the same, the safe side
        return False
    median = float(np.median(scores))
    if median < TILE_MEDIAN:     # the glyphs are not the same at all: a loss shared by every piece is no reason to let it pass
        return False
    return min(scores) >= median - TILE_BLUR * (1.0 - median) - TILE_ROOM


@dataclass
class Seen:
    card: int              # the answer's analysis id: what the panel points back to
    picture: np.ndarray    # the box as answered
    context: np.ndarray    # the box with MARGIN around it, to look for a later box in
    ts: float


class Recent:
    """The problems answered lately, as pictures; a new screen's box is looked for among them."""

    def __init__(self, keep: int = KEEP, ttl: float = TTL):
        self.keep, self.ttl = keep, ttl
        self.items: list[Seen] = []
        self.words: list[tuple] = []   # (card, the problem as words, when), as they went to the agent

    def _fresh(self, now: float) -> list[Seen]:
        self.items = [s for s in self.items if now - s.ts < self.ttl][-self.keep:]
        return self.items

    def add(self, card: int, model_b64: str, view, box, kind: str, now: float | None = None) -> None:
        """Remember the problem answered as `card` (of `kind`), at `box` (screen fractions) of the screen `model_b64`
        shows `view` of."""
        img = screen_image(model_b64)
        x0, y0, x1, y1 = _pixels(box, view, img.shape)
        cx0, cy0, cx1, cy1 = _pixels(box, view, img.shape, MARGIN)
        if x1 - x0 < 24 or y1 - y0 < 24:
            return                        # too small to tell anything by
        now = time.time() if now is None else now
        self.items.append(Seen(card, img[y0:y1, x0:x1].copy(), img[cy0:cy1, cx0:cx1].copy(), now))
        self._fresh(now)                  # the oldest go, so no more than `keep` are held

    def match(self, model_b64: str, view, box, kind: str, now: float | None = None) -> tuple[int, float] | None:
        """The card of a problem answered lately that is the one at `box` now, with the score; None for a new one. What
        the first pass calls it is no test: the small model on a busy GPU once called an essay "other", and
        the problem was solved again. A box's picture alone tells them apart: of 1,560 pairs of different problems
        none passes, of whatever kinds (design 88)."""
        now = time.time() if now is None else now
        if not self._fresh(now):
            return None
        img = screen_image(model_b64)
        x0, y0, x1, y1 = _pixels(box, view, img.shape)
        cx0, cy0, cx1, cy1 = _pixels(box, view, img.shape, MARGIN)
        if x1 - x0 < 24 or y1 - y0 < 24:
            return None
        picture, context = img[y0:y1, x0:x1], img[cy0:cy1, cx0:cx1]
        for seen in reversed(self.items):          # the latest first: the one most likely seen again
            ok, score = same_picture(seen.picture, context)
            if not ok:
                ok, score = same_picture(picture, seen.context)
            if ok:
                return seen.card, score
        # The window dragged across the screen, and the model's box landing elsewhere on it, leave neither box inside the other's margin
        # (one problem solved twice, the window a tenth of the screen to the left). So the whole screen is searched too, for the latest.
        for seen in list(reversed(self.items))[:WHOLE_LATEST]:
            ok, score = same_picture(seen.picture, img)
            if ok:
                return seen.card, score
        return None

    def add_words(self, card: int, words: str, now: float | None = None) -> None:
        """Remember the problem of `card` as the words it went out in."""
        now = time.time() if now is None else now
        self.words = [w for w in self.words if now - w[2] < self.ttl][-(self.keep - 1):] + [(card, words, now)]

    def match_words(self, words: str, now: float | None = None) -> tuple[int, float] | None:
        """The card of the problem answered lately that these words are, with how close; None for a new one."""
        now = time.time() if now is None else now
        best = None
        for card, seen, ts in reversed(self.words):
            if now - ts < self.ttl:
                score = same_words(words, seen)
                if score >= WORDS_SAME and (best is None or score > best[1]):
                    best = (card, score)
        return best

    def save(self, path, extra: dict | None = None) -> None:
        """Keep what is remembered for the server's next start: `./sidenote up` restarts it, and the same problem still on
        the screen was solved again, at an agent's price (seen twice). `extra` goes with it (app.keep_for_restart)."""
        seen = self._fresh(time.time())
        arrays = {}
        for i, s in enumerate(seen):
            arrays[f"p{i}"], arrays[f"c{i}"] = s.picture, s.context
        head = {"seen": [{"card": s.card, "ts": s.ts} for s in seen], "words": [list(w) for w in self.words], "extra": extra or {}}
        tmp = f"{path}.tmp.npz"
        np.savez_compressed(tmp, head=np.array(json.dumps(head)), **arrays)
        os.replace(tmp, path)

    def load(self, path) -> dict:
        """Take up what save() kept, what has not outlived `ttl` meanwhile; the file goes, as what it holds is pieces of a screen.
        Its `extra`, or nothing if there is no such file or it cannot be read."""
        try:
            with np.load(path, allow_pickle=False) as z:
                head = json.loads(str(z["head"]))
                now = time.time()
                for i, s in enumerate(head.get("seen", ())):
                    if now - float(s["ts"]) < self.ttl:
                        self.items.append(Seen(int(s["card"]), z[f"p{i}"], z[f"c{i}"], float(s["ts"])))
                self.words = [(int(c), str(w), float(t)) for c, w, t in head.get("words", ()) if now - float(t) < self.ttl]
            return head.get("extra") or {}
        except (OSError, ValueError, KeyError, TypeError):   # none kept, or a broken one: it only costs solving a problem again
            return {}
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def forget(self) -> None:
        self.items.clear()
        self.words.clear()
