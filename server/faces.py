"""Faces on the screen are painted over before anything reads it.

This is for the sake of people's portrait rights: a video call beside the problem, a
video, a photo in an article or a profile picture shows somebody's likeness, and a screen goes to this PC's model, to
the cloud agent when it answers and into the panel's thumbnail. So the faces on every screen that comes in are found and covered in prepare_frame, before the change
detector, the models, the crops and the thumbnail are made from it.

The finder is YuNet (OpenCV Zoo, MIT license in assets/LICENSE.yunet), 232 KB of ONNX run by onnxruntime, which the
image has already for speech. Its input is fixed at 640 x 640, so a screen is read twice over: once whole, fitted into
640, which finds a face from about a fiftieth of the screen's long side up (a video call, a video, a photo), and once
in overlapping tiles, closer, for the smaller ones (a thumbnail, a profile picture): four quarters on a screen up to
2560 wide, nine on a larger one, whose faces are as many pixels but a smaller part of it (a 4K screen at 150%).

A finder trained on photos takes a drawn circle for a face now and then: a graph's node, a lamp on a grid, a chess
piece. On the problem pictures of the public corpus it boxed one on 116 of 2,279 at the score used here, where covering
it would hide part of the problem. A face in a photo or a video has skin's colour over most of its middle, many shades
and soft contrast; a drawn node has flat fills and black digits on them. So a box is kept only when its middle passes
all three (photo_like): then 3 pictures of the 2,279 keep a box (each a node with a pale fill), and of the faces
pasted onto screens 116 of 117 are still covered. A face in a black-and-white photo fails the skin test and stays uncovered, the price of leaving the
problem's figures alone.

The session runs on the calling thread alone (one intra-op thread, no spinning). A pool of native threads beside it is
what a fork for a child process must not land in (forksafe: the server stopped for 95 minutes over such a fork), and
one thread is quick enough here. Measured numbers are in the design notes (docs/ARCHITECTURE.md, 85).
"""
from __future__ import annotations

import logging      # a finder that cannot load says so once and the screens go on uncovered
import threading    # one session for the whole server, loaded on first use from whichever thread gets there
from pathlib import Path

import numpy as np                 # the image as numbers in, the boxes decoded out
from PIL import Image, ImageDraw   # the screen is a PIL image in prepare_frame; the cover is drawn on it

log = logging.getLogger("sidenote.faces")

MODEL = Path(__file__).resolve().parent / "assets" / "face_detection_yunet_2023mar.onnx"
SIDE = 640            # the model's fixed input: a square this many pixels on a side
SCORE = 0.6           # a face from this confidence up (measured: design note 84)
NMS_IOU = 0.3         # two boxes overlapping this much are the same face (OpenCV's FaceDetectorYN uses 0.3)
OVERLAP = 0.2         # how far the tiles reach into each other, so a face on a seam is whole in one of them
GRID_AT = 2600        # a screen with a longer side than this is read in 3 x 3 tiles, a smaller one in 2 x 2
# The face's box grown to the head, as fractions of its own width and height: the finder boxes the face from brow to
# chin, and hair, ears and the jaw's line are the likeness too.
GROW = (0.25, 0.45, 0.25, 0.2)
FILL = (128, 128, 128)   # the grey that other windows in front of a crop are painted with (pipeline.crop_image)
# What the middle of a found face must show to be taken for one (photo_like, design note 85): this share of its pixels
# in skin's chroma (YCbCr Cb 77 to 127 and Cr 133 to 173, the range of Chai and Ngan, 1999), and this many distinct
# colours at 16 levels a channel.
SKIN_MIN = 0.3
SHADES_MIN = 30
LUMA_SD_MAX = 70      # and no harder contrast than this (the spread of its brightness): black digits on a pale fill

_session = None                  # loaded on first use
_failed = False                  # a finder that could not load is not tried again on every screen
_lock = threading.Lock()         # the load, and the runs: onnxruntime may run a session from two threads, but
                                 # two screens at once would only queue on the one thread each has


def _load():
    """The onnxruntime session, loaded once; None when it cannot be (no model file, no onnxruntime)."""
    global _session, _failed
    if _session is None and not _failed:
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1                                   # the calling thread does the work
            so.inter_op_num_threads = 1                                   # and no second pool for the graph either
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            so.log_severity_level = 3                                     # its warnings about GPUs it has not got
            _session = ort.InferenceSession(str(MODEL), so, providers=["CPUExecutionProvider"])
        except Exception as exc:   # pragma: no cover - an image without the model or onnxruntime
            _failed = True
            log.warning("face finder unavailable (%s): screens are not covered", exc)
    return _session


def _read(sess, part: Image.Image, score: float) -> list:
    """The faces in `part` as (x0, y0, x1, y1, score) in its own pixels: fitted into the model's square from its top
    left corner, decoded the way OpenCV's FaceDetectorYN decodes YuNet (the score is the root of the class and the
    object scores; a box is its centre offset and its log size, in units of the stride)."""
    w, h = part.size
    k = SIDE / max(w, h)                                                   # the long side fills the square
    small = part.resize((max(1, round(w * k)), max(1, round(h * k))), Image.BILINEAR)
    canvas = np.zeros((SIDE, SIDE, 3), np.float32)                         # the rest of the square stays black
    pix = np.asarray(small, np.float32)[:, :, ::-1]                        # RGB to BGR, 0 to 255, as it was trained
    canvas[:pix.shape[0], :pix.shape[1]] = pix
    out = dict(zip((o.name for o in sess.get_outputs()), sess.run(None, {"input": canvas.transpose(2, 0, 1)[None]})))
    found = []
    for stride in (8, 16, 32):
        n = SIDE // stride                                                 # cells across the square at this stride
        cls = np.clip(out[f"cls_{stride}"][0, :, 0], 0, 1)
        obj = np.clip(out[f"obj_{stride}"][0, :, 0], 0, 1)
        conf = np.sqrt(cls * obj)
        box = out[f"bbox_{stride}"][0]
        for i in np.nonzero(conf >= score)[0]:
            row, col = divmod(int(i), n)
            cx, cy = (col + box[i, 0]) * stride, (row + box[i, 1]) * stride
            bw, bh = np.exp(box[i, 2]) * stride, np.exp(box[i, 3]) * stride
            found.append(((cx - bw / 2) / k, (cy - bh / 2) / k, (cx + bw / 2) / k, (cy + bh / 2) / k, float(conf[i])))
    return found


def _nms(boxes: list, iou: float = NMS_IOU) -> list:
    """The boxes left when each one overlapping a surer one by `iou` or more is dropped."""
    keep: list = []
    for b in sorted(boxes, key=lambda b: -b[4]):
        if all(_iou(b, k) < iou for k in keep):
            keep.append(b)
    return keep


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / union if union > 0 else 0.0


def tiles(w: int, h: int, overlap: float = OVERLAP) -> list:
    """The tiles a w x h screen is read in besides the whole: n x n of them (GRID_AT), each reaching `overlap` of its
    size into its neighbours."""
    n = 3 if max(w, h) > GRID_AT else 2
    tw, th = w / n, h / n
    ex, ey = tw * overlap, th * overlap
    return [(max(0, round(c * tw - ex)), max(0, round(r * th - ey)), min(w, round((c + 1) * tw + ex)),
             min(h, round((r + 1) * th + ey))) for r in range(n) for c in range(n)]


def photo_like(rgb: Image.Image, box: tuple) -> bool:
    """Whether the middle of `box` (x0, y0, x1, y1 in `rgb`'s pixels) looks like a face in a photo rather than a drawn
    shape: enough of it in skin's colour, enough distinct colours and no harder contrast than a face has (SKIN_MIN,
    SHADES_MIN, LUMA_SD_MAX). The middle leaves out the hair, the ears and the background around the face, which tell
    nothing either way."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    mid = rgb.crop((round(x0 + bw * 0.2), round(y0 + bh * 0.2), round(x1 - bw * 0.2), round(y1 - bh * 0.15)))
    if mid.width < 2 or mid.height < 2:
        return False                                                       # too small to judge: left as it is
    ycc = np.asarray(mid.convert("YCbCr"), np.int16).reshape(-1, 3)
    cb, cr = ycc[:, 1], ycc[:, 2]
    skin = float(((cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 173)).mean())
    shades = len(np.unique(np.asarray(mid, np.uint8).reshape(-1, 3) // 16, axis=0))
    return skin >= SKIN_MIN and shades >= SHADES_MIN and float(ycc[:, 0].std()) <= LUMA_SD_MAX


def find(img: Image.Image, score: float = SCORE) -> list:
    """The faces on `img` as screen fractions (x0, y0, x1, y1, score); [] when there are none or no finder."""
    sess = _load()
    if sess is None:
        return []
    w, h = img.size
    rgb = img.convert("RGB") if img.mode != "RGB" else img
    found = []
    with _lock:
        for x0, y0, x1, y1 in [(0, 0, w, h)] + tiles(w, h):          # the whole screen, then its tiles closer
            part = rgb if (x0, y0, x1, y1) == (0, 0, w, h) else rgb.crop((x0, y0, x1, y1))
            found += [(a + x0, b + y0, c + x0, d + y0, s) for a, b, c, d, s in _read(sess, part, score)]
    # only what looks like a face in a photo: a node of a drawn graph is left alone (photo_like)
    return [(float(a / w), float(b / h), float(c / w), float(d / h), s) for a, b, c, d, s in _nms(found)
            if photo_like(rgb, (a, b, c, d))]


def cover(img: Image.Image, faces: list) -> Image.Image:
    """`img` with every face in `faces` (screen fractions) painted over, out to the head (GROW); drawn on `img` itself."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    for x0, y0, x1, y1, *_ in faces:
        fw, fh = x1 - x0, y1 - y0
        box = (max(0.0, x0 - fw * GROW[0]) * w, max(0.0, y0 - fh * GROW[1]) * h,
               min(1.0, x1 + fw * GROW[2]) * w, min(1.0, y1 + fh * GROW[3]) * h)
        draw.rectangle(box, fill=FILL)
    return img
