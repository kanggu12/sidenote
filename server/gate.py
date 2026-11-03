"""Screen change detection via a high-pass thumbnail signature.

A plain downscaled-thumbnail difference is dominated by background brightness
(a dark->light theme swing swamps any text change, while two different sparse
pages on the same background look identical). We instead compare a *high-pass*
signature: a small grayscale thumbnail minus its blur, which keeps text/edges
and drops the flat background. The result is background-invariant and sensitive
to content, so the same metric works both on the capture client (decide what to
send) and on the server (dedupe before spending an API call).

Distance is the mean absolute difference (0-255) between two signatures.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter

SIG_SIZE = (160, 120)
SIG_BLUR = 2


def signature(img: Image.Image) -> bytes:
    """High-pass grayscale signature of an image (edge/ink map)."""
    g = img.convert("L").resize(SIG_SIZE, Image.BILINEAR)
    hp = ImageChops.difference(g, g.filter(ImageFilter.BoxBlur(SIG_BLUR)))
    return hp.tobytes()


def distance(a: bytes, b: bytes) -> float:
    """Mean absolute difference between two signatures (0 = identical)."""
    if not a or not b or len(a) != len(b):
        return 255.0
    total = 0
    for x, y in zip(a, b):
        total += x - y if x > y else y - x
    return total / len(a)


def region_distance(a: bytes, b: bytes, region: tuple[float, float, float, float]) -> float:
    """distance() over the part of the screen inside region = (x0, y0, x1, y1), given as
    fractions of the width and height."""
    if not a or not b or len(a) != len(b):
        return 255.0
    w, h = SIG_SIZE
    c0, r0 = min(w - 1, int(region[0] * w)), min(h - 1, int(region[1] * h))
    c1, r1 = max(c0 + 1, min(w, -int(-region[2] * w))), max(r0 + 1, min(h, -int(-region[3] * h)))
    total = 0
    for r in range(r0, r1):
        row = r * w
        for x, y in zip(a[row + c0:row + c1], b[row + c0:row + c1]):
            total += x - y if x > y else y - x
    return total / ((r1 - r0) * (c1 - c0))
