"""The screen as the analyses take it, made from what the capture program sent: the faces on it covered first (faces.py),
then the model's image (cut into pages for a tall one), the panel's thumbnail, the change signature (gate.py), and the
problem's region from the text the detector found. Every screen goes through prepare_frame, on a worker thread: nothing
here waits on the network or the server's state (app.py keeps that), so it is the screen's own module.
"""
from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass, field

from PIL import Image

from . import faces
from .gate import signature
from .settings import SETTINGS

# the server's log, as these lines were written in it before they had a module of their own
log = logging.getLogger("sidenote.app")

# Problem-region crop tuning: pad the text box by this fraction of the image, and
# only crop when the padded text region is a worthwhile sub-rectangle: smaller
# than CROP_MAX_AREA (otherwise there's nothing to trim) but not below CROP_MIN_AREA
# (a tiny text island on a mostly-graphical screen is left whole, to be safe).
CROP_PAD_FRAC = 0.04
CROP_MAX_AREA = 0.92
CROP_MIN_AREA = 0.40
# Aggressive mode: a text block counts as "the problem" only if it holds at least
# this fraction of all the on-screen text, so a clearly dominant block is isolated
# but two comparable blocks (e.g. problem + an equally large editor) are left alone.
CROP_DOMINANCE = 0.60


@dataclass
class Frame:
    model_b64: str          # possibly downscaled PNG, base64 (sent to the model + OCR)
    thumb_url: str          # small JPEG data URL (shown in the panel)
    sig: bytes              # high-pass change-detection signature
    ts: float
    width: int
    height: int
    ocr_text: str = ""      # on-screen text (filled in the executor when OCR is on)
    # Where the text detector found lines on this screen, in screen fractions, filled the first time
    # a crop of this frame needs them (pipeline.text_lines). Kept here so several crops of one screen
    # pay for the detector once.
    ocr_lines: list | None = None
    # Scroll-stitched page (client --stitch): the full unrolled problem, cut into tiles
    # sent to the model after the screen itself; extra_sig fingerprints that content.
    extra_b64: list[str] = field(default_factory=list)
    extra_sig: bytes | None = None
    # The screen as it arrived (up to the capture program's --max-width, the monitor's own size by
    # default): problem crops are cut from this, not from the downscaled model image.
    full_png: bytes = b""
    # Visible top-level windows, front to back, in screen fractions (from the capture program): a
    # crop is clipped to the window holding the problem.
    windows: list | None = None
    # The part of the screen the model image shows (the OCR crop, SIDENOTE_CROP); the whole screen
    # by default. Boxes the model gives are fractions of this.
    model_box: tuple = (0.0, 0.0, 1.0, 1.0)
    # How many faces were painted over on this screen and its pages before anything was made from them (faces.py).
    faces: int = 0




def _pad_clamp(x0, y0, x1, y1, w, h):
    x0, y0 = max(0, int(x0 - w * CROP_PAD_FRAC)), max(0, int(y0 - h * CROP_PAD_FRAC))
    x1, y1 = min(w, int(x1 + w * CROP_PAD_FRAC)), min(h, int(y1 + h * CROP_PAD_FRAC))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def crop_region(boxes, w: int, h: int):
    """Union of ALL OCR text boxes, padded and clamped (margin trim). None if not worth it."""
    if not boxes:
        return None
    box = _pad_clamp(min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes), w, h)
    if box is None:
        return None
    frac = ((box[2] - box[0]) * (box[3] - box[1])) / float(w * h)
    if frac >= CROP_MAX_AREA or frac < CROP_MIN_AREA:
        return None
    return box


def _cluster_boxes(boxes, gap_x: float, gap_y: float):
    """Group boxes into spatial blocks: two boxes join when their gap is within
    (gap_x, gap_y). Simple union-find over the (small) box list."""
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def gap(a0, a1, b0, b1):
        if a1 < b0:
            return b0 - a1
        if b1 < a0:
            return a0 - b1
        return 0.0

    for i in range(n):
        for j in range(i + 1, n):
            if (gap(boxes[i][0], boxes[i][2], boxes[j][0], boxes[j][2]) <= gap_x and
                    gap(boxes[i][1], boxes[i][3], boxes[j][1], boxes[j][3]) <= gap_y):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(boxes[i])
    return list(groups.values())


def dominant_region(boxes, w: int, h: int):
    """Isolate the dominant text block: cluster the boxes, and if one block holds the
    bulk of the text (CROP_DOMINANCE) while others are separate, return its padded
    bbox. Returns None when no block clearly dominates (caller falls back to margin trim)."""
    if len(boxes) < 4:
        return None
    heights = sorted(b[3] - b[1] for b in boxes)
    hmed = heights[len(heights) // 2] or 1.0
    clusters = _cluster_boxes(boxes, gap_x=2.5 * hmed, gap_y=1.5 * hmed)
    if len(clusters) < 2:
        return None  # one block -> nothing to exclude; let margin trim handle it

    def text_area(cl):
        return sum((b[2] - b[0]) * (b[3] - b[1]) for b in cl)

    total = sum(text_area(c) for c in clusters)
    dom = max(clusters, key=text_area)
    if total <= 0 or text_area(dom) / total < CROP_DOMINANCE or len(dom) < 3:
        return None
    box = _pad_clamp(min(b[0] for b in dom), min(b[1] for b in dom),
                     max(b[2] for b in dom), max(b[3] for b in dom), w, h)
    if box is None:
        return None
    if ((box[2] - box[0]) * (box[3] - box[1])) / float(w * h) >= CROP_MAX_AREA:
        return None  # already fills the screen -> nothing isolated
    return box


# A stitched page can be many screens tall; a model shrinks any image whose long edge is
# over its limit (1568px on older models, 2576px on current ones), which would blur the
# text. So tall pages go out as tiles under the smaller limit, overlapping a little so a
# line cut at a boundary is whole in one of them.
TILE_H = 1500
TILE_OVERLAP = 40


def tile_image(img: Image.Image, max_w: int) -> list[Image.Image]:
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
    tiles, y = [], 0
    while True:
        tiles.append(img.crop((0, y, img.width, min(img.height, y + TILE_H))))
        if y + TILE_H >= img.height:
            return tiles
        y += TILE_H - TILE_OVERLAP


def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def prepare_frame(png_bytes: bytes, max_w: int, ocr, crop_mode: str = "off",
                  extra_pngs: list[bytes] | None = None) -> Frame:
    """Decode, cap width, OCR + (optional) crop, thumbnail, hash. Runs in a thread.

    crop_mode: "off" | "auto" (margin trim) | "aggressive" (isolate the dominant block,
    falling back to margin trim when no block clearly dominates)."""
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    img = img.convert("RGB")
    w, h = img.size
    # Faces are covered first, so the thumbnail, the change signature, the model's image and every crop are made
    # from the covered screen (faces.py: for people's portrait rights). The screen as it arrived is kept for
    # the crops; it is written again, quickly rather than small, only when something was covered on it.
    covered = _cover_faces(img)
    if covered:
        png_bytes = _png_bytes(img)
    fitted = img
    if w > max_w:
        fitted = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    # Change detection sees the WHOLE screen (a crop must not blind it), at the model's width: its
    # thresholds were set on screens of that size.
    sig = signature(fitted)

    model_img = fitted
    model_box = (0.0, 0.0, 1.0, 1.0)

    ocr_text = ""
    if ocr is not None:
        try:
            ocr_text, boxes = ocr.run(model_img)
            if crop_mode != "off":
                box = None
                if crop_mode == "aggressive":
                    box = dominant_region(boxes, model_img.width, model_img.height)
                if box is None:
                    box = crop_region(boxes, model_img.width, model_img.height)
                if box:
                    model_img = model_img.crop(box)
                    model_box = (box[0] / fitted.width, box[1] / fitted.height,
                                 box[2] / fitted.width, box[3] / fitted.height)
        except Exception as exc:  # pragma: no cover
            log.warning("OCR/crop failed: %s", exc)

    buf = io.BytesIO()
    # Compression 1: the same pixels in half the time (75 to 36 ms at 4K), and most frames are never analysed
    model_img.save(buf, format="PNG", compress_level=1)
    model_b64 = base64.b64encode(buf.getvalue()).decode()

    # The thumbnail is the whole screen, so the problem box and a box drawn on it are screen fractions.
    tw = 360
    if fitted.width > tw:
        thumb_img = fitted.resize((tw, int(fitted.height * tw / fitted.width)), Image.LANCZOS)
    else:
        thumb_img = fitted
    tbuf = io.BytesIO()
    thumb_img.save(tbuf, format="JPEG", quality=70)
    thumb_url = "data:image/jpeg;base64," + base64.b64encode(tbuf.getvalue()).decode()

    extra_b64: list[str] = []
    extra_sig = None
    for raw in extra_pngs or ():
        page = Image.open(io.BytesIO(raw))
        page.load()
        page = page.convert("RGB")
        covered += _cover_faces(page)            # a scrolled page of the problem is a screen too
        if extra_sig is None:
            extra_sig = signature(page)
        extra_b64 += [_png_b64(t) for t in tile_image(page, max_w)]

    return Frame(model_b64=model_b64, thumb_url=thumb_url, sig=sig,
                 ts=time.time(), width=w, height=h, ocr_text=ocr_text,
                 extra_b64=extra_b64, extra_sig=extra_sig, full_png=png_bytes, model_box=model_box, faces=covered)


def _cover_faces(img) -> int:
    """Paint over the faces on `img` in place when Cover faces is on; how many there were. A finder that fails leaves
    the screen as it is and says so in the log (faces.py), since a screen not read at all is worse."""
    if not SETTINGS.on("face_mask"):
        return 0
    try:
        found = faces.find(img)
    except Exception as exc:   # pragma: no cover - a broken model file, an onnxruntime that fails at run time
        log.warning("face finder failed on a screen (%s); it goes on uncovered", exc)
        return 0
    if found:
        faces.cover(img, found)
    return len(found)


def _png_bytes(img) -> bytes:
    """`img` as PNG at the fastest compression: it stays in this process for the crops, so its size matters less than
    the 0.1 to 0.3 s a full compression of a 4K screen takes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def window_list(raw) -> list | None:
    """The capture program's window rectangles (fractions, front to back), checked."""
    if not isinstance(raw, list):
        return None
    out = []
    for r in raw[:40]:
        if (isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r)
                and 0 <= r[0] < r[2] <= 1 and 0 <= r[1] < r[3] <= 1):
            out.append(tuple(float(v) for v in r))
    return out

