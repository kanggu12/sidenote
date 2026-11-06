"""The crop that goes out, checked at the server's own door.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/crop_grow.py

roi_snap.py measures how much of a problem the crop holds, over the boxes four runs recorded. This
asks the smaller question that measurement cannot: that crop_image grows a box only where it is
meant to. The two things it guards both went wrong while the growing was being written, and both
were caught by other checks rather than by one of their own:

  - the halves of a screen came back as the whole screen, because a half has no gutter to stop at
  - the box the code check reads the editor from came back grown, so the check read more than it
    was given

and the third is the one no check had at all: a region drawn by hand is a chosen area and must be
cut as drawn.
"""
import io
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SIDENOTE_ANALYZER", "mock")

from server.pipeline import (CROP_MAX_SIDE, CROP_PAD, SNAP_GROW, block_grown,  # noqa: E402
                             crop_image, halves, shown_box, upright)
from server.settings import SETTINGS  # noqa: E402

ok = bad = 0


def check(name, cond, detail=""):
    global ok, bad
    print(("  ok " if cond else "  FAIL ") + name + ("" if cond else f"  - {detail}"))
    ok += bool(cond)
    bad += not cond


class Frame:
    """A screen with one paragraph of writing on it, in one window, and nothing else."""

    def __init__(self, w=1920, h=1080, windows=None, dark=False):
        page, letters = ((28, 30, 36), (230, 232, 238)) if dark else ((250, 250, 250), (20, 20, 20))
        img = Image.new("RGB", (w, h), page)
        d = ImageDraw.Draw(img)
        # a block of five lines between 0.30 and 0.45 of the height, with a wide blank margin round it
        for i in range(5):
            y = int((0.30 + i * 0.03) * h)
            d.rectangle((int(0.30 * w), y, int(0.60 * w), y + max(2, int(0.012 * h))), fill=letters)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self.full_png = buf.getvalue()
        self.width, self.height = w, h
        self.windows = windows
        self.ocr_lines = None


def size_of(b64: str) -> tuple:
    import base64
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


print("[a box the model placed inside the writing]")
SETTINGS.values.clear()
f = Frame()
inside = (0.40, 0.36, 0.50, 0.40)          # the middle two lines only
plain, box_plain, _ = crop_image(f, inside, CROP_PAD, CROP_MAX_SIDE, True, False)
grown, box_grown, _ = crop_image(f, inside, CROP_PAD, CROP_MAX_SIDE, True, True)
print(f"     as given {tuple(round(v, 3) for v in box_plain)}  grown {tuple(round(v, 3) for v in box_grown)}")
check("the panel draws what the crop takes, not the model's first box", shown_box(f, inside) == box_grown and shown_box(f, inside) != inside, str(shown_box(f, inside)))
check("growing reaches the top of the block the box sits in", box_grown[1] <= 0.31,
      f"top {box_grown[1]:.3f}")
check("and its bottom", box_grown[3] >= 0.42, f"bottom {box_grown[3]:.3f}")
check("and its left edge, which the box was well inside of", box_grown[0] <= 0.31,
      f"left {box_grown[0]:.3f}")
check("growing never shrinks the box it was given",
      box_grown[0] <= inside[0] and box_grown[1] <= inside[1]
      and box_grown[2] >= inside[2] and box_grown[3] >= inside[3])
# the margin alone reaches the same rows here (CROP_PAD is wide), so the thing to compare is the
# area: without growing the crop is the box and its margin, which is the smaller of the two
check("without it, the crop is the box and its margin, which is smaller",
      (box_plain[2] - box_plain[0]) * (box_plain[3] - box_plain[1])
      < (box_grown[2] - box_grown[0]) * (box_grown[3] - box_grown[1]) - 1e-6,
      f"{tuple(round(v, 3) for v in box_plain)} vs {tuple(round(v, 3) for v in box_grown)}")

print("\n[the same paragraph on a dark page]")
# An editor is light letters on a dark page. Reading ink as "darker than the page" marks the
# background itself as ink there, the walk never meets a gutter and runs to the window's edges:
# measured on this very screen, the box grew to 1.5 times its size on a light page and 5.7 on a
# dark one before the page's colour was read as whatever most of the window is.
f_dark = Frame(dark=True)
_, box_dark, _ = crop_image(f_dark, inside, CROP_PAD, CROP_MAX_SIDE, True, True)
print(f"     on a dark page {tuple(round(v, 3) for v in box_dark)}")
check("a dark page grows the same box a light one does",
      all(abs(a - b) < 0.02 for a, b in zip(box_dark, box_grown)),
      f"{tuple(round(v, 3) for v in box_dark)} vs {tuple(round(v, 3) for v in box_grown)}")

print("\n[a region drawn by hand is a chosen area]")
SETTINGS.values.update(roi_box=list(inside))
drawn, box_drawn, _ = crop_image(f, inside, CROP_PAD, CROP_MAX_SIDE, True, True)
check("a drawn region is cut as drawn even with growing asked for",
      abs(box_drawn[1] - inside[1]) < 0.02 and abs(box_drawn[3] - inside[3]) < 0.02,
      f"{tuple(round(v, 3) for v in box_drawn)}")
SETTINGS.values.clear()

print("\n[the halves of a screen are halves]")
big = Frame(3840, 2160)
parts = halves(big)
sizes = [size_of(p) for p in parts]
print(f"     {sizes}")
check("each half is a half and not the screen", all(s[0] == s[1] for s in sizes), str(sizes))
check("there are two of them", len(parts) == 2)

print("\n[the text detector's blocks are held to the same limits as the ink walk]")
# The detector reads the whole screen and knows nothing of windows, so a line of text that runs
# across a window edge would otherwise pull the neighbour's window into the crop. Pure geometry:
# no engine is needed, only boxes of the shape it returns.
# The box has to cover enough of the block for the block to count at all, or this checks nothing:
# the first version of it used a box too small and the growth never happened, so "stops at the
# window" passed without the window ever being reached.
box = (0.35, 0.40, 0.65, 0.46)
win = (0.30, 0.0, 0.70, 1.0)
over = [[0.10, 0.40, 0.90, 0.46]]          # one line of text running right across the window edge
free_grow = block_grown(box, over)
held = block_grown(box, over, win)
print(f"     no window given {tuple(round(v, 3) for v in free_grow)}   "
      f"within the window {tuple(round(v, 3) for v in held)}")
check("the block really does grow the box when no window is given",
      free_grow[0] < box[0] - 0.05 and free_grow[2] > box[2] + 0.05,
      f"{tuple(round(v, 3) for v in free_grow)}")
check("a block that runs past the window stops at the window",
      held[0] >= win[0] - 1e-9 and held[2] <= win[2] + 1e-9, f"{tuple(round(v, 3) for v in held)}")
check("...and the box it was given is still inside what comes back",
      held[0] <= box[0] and held[1] <= box[1] and held[2] >= box[2] and held[3] >= box[3])
far = [[0.0, 0.0, 1.0, 1.0]]               # one block covering everything
capped = block_grown(box, far, None)
check("a block many times the box does not grow it past the cap",
      capped[2] - capped[0] <= (box[2] - box[0]) * (1 + 2 * SNAP_GROW) + 1e-9,
      f"{tuple(round(v, 3) for v in capped)}")
check("a box the detector found nothing near is unchanged",
      block_grown(box, [[0.01, 0.90, 0.05, 0.95]], win) == box,
      str(block_grown(box, [[0.01, 0.90, 0.05, 0.95]], win)))

print("\n[growing cannot turn a crop into the whole screen]")
blank = Frame()                                     # writing everywhere: nothing stops the walk
d = ImageDraw.Draw(Image.new("RGB", (1, 1)))        # noqa: F841 - keeps the import honest
img = Image.new("RGB", (1920, 1080), (250, 250, 250))
dd = ImageDraw.Draw(img)
for i in range(60):
    dd.rectangle((10, i * 18, 1910, i * 18 + 10), fill=(20, 20, 20))
buf = io.BytesIO()
img.save(buf, format="PNG")
blank.full_png = buf.getvalue()
_, box_full, _ = crop_image(blank, (0.45, 0.45, 0.55, 0.55), CROP_PAD, CROP_MAX_SIDE, True, True)
area = (box_full[2] - box_full[0]) * (box_full[3] - box_full[1])
check("a screen with no gutter anywhere does not become the crop", area <= 0.61, f"area {area:.2f}")

print("\n[a line across the whole window is its frame, not writing]")
# A toolbar's lower edge in the box's rows put ink in every column: the walk sideways ran to both
# edges of the window, the guard turned a growth that wide down, and the crop stayed the box. On a 4K
# screen whose problem sat just under the browser's toolbar, the code line was cut off at 87 per cent
# this way (roi_side_2160). The left margin alone reaches the paragraph's left edge here, so the
# right edge, which only growing reaches, is the one that says whether the walk found the paragraph.


def with_lines(across=(), down=(), table=None):
    """The one-paragraph screen with window-wide lines drawn over it: `across` at these heights, `down`
    at these widths. `table`: rows of writing 0.025 apart with a rule close under each, instead."""
    f = Frame()
    img = Image.open(io.BytesIO(f.full_png)).convert("RGB")
    d = ImageDraw.Draw(img)
    for y in across:
        d.rectangle((0, int(y * 1080), 1919, int(y * 1080) + 1), fill=(20, 20, 20))
    for x in down:
        d.rectangle((int(x * 1920), 0, int(x * 1920) + 1, 1079), fill=(20, 20, 20))
    if table:
        # real letters, not bars: a row of solid ink makes the band round a thin box mostly ink, and the
        # page's colour is then read as the letters'. Rows 0.022 apart are further apart than the gutter
        # the walk stops at, and the rule two thirds of the way down each row is what bridges them.
        font = ImageFont.load_default(size=15)
        d.rectangle((0, 0, 1919, 1079), fill=(250, 250, 250))
        for i in range(table):
            y = int((0.30 + i * 0.022) * 1080)
            d.text((int(0.30 * 1920), y), "[1, 2, 1, 2, 3]      2      4      [4, 1, 1, 3, 4, 1]      3      9",
                   fill=(20, 20, 20), font=font)
            d.rectangle((int(0.30 * 1920), y + 19, int(0.60 * 1920), y + 20), fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    f.full_png = buf.getvalue()
    return f


_, box_rule, _ = crop_image(with_lines(across=[0.38]), inside, CROP_PAD, CROP_MAX_SIDE, True, True)
print(f"     a line across {tuple(round(v, 3) for v in box_rule)}")
check("a line across the window in the box's rows does not stop the paragraph being found",
      box_rule[2] >= 0.60, f"right {box_rule[2]:.3f}, the paragraph ends at 0.60")
check("...and the crop does not run to the window's edges either", box_rule[2] <= 0.70,
      f"right {box_rule[2]:.3f}")
_, box_div, _ = crop_image(with_lines(down=[0.45]), inside, CROP_PAD, CROP_MAX_SIDE, True, True)
print(f"     a line down {tuple(round(v, 3) for v in box_div)}")
# Down the box's columns a divider puts ink in every row, the walk up and down runs to its cap, and
# the crop takes in rows of whatever is above and below the paragraph.
check("a divider down the window does not carry the walk past the paragraph",
      box_div[1] >= 0.22 and box_div[3] <= 0.50, f"{tuple(round(v, 3) for v in box_div)}")
# Only the test across a stroke ignores it. A rule the width of a table, close under each of its rows,
# is still ink to the walk down the table, as it was: without it the gaps between the rows are wider
# than the gutter the walk stops at, and the crop would end at the row the box sits on.
_, box_tab, _ = crop_image(with_lines(table=8), (0.32, 0.366, 0.42, 0.40), CROP_PAD, CROP_MAX_SIDE, True, True)
print(f"     a table {tuple(round(v, 3) for v in box_tab)}")
check("the walk down a table with a rule under each row still reaches its last row",
      box_tab[3] >= 0.30 + 7 * 0.022 + 14 / 1080, f"bottom {box_tab[3]:.3f}, the last row ends at 0.467")

# A box written y first, up to twice as tall as wide, is turned when its edges cut through the lines and the turned one's
# do not; a pane of code that really stands that tall is left as it is.
print("\n[a box written y first in a shape TALL_BOX lets through]")
scr = Image.new("RGB", (1920, 1080), "white")
d = ImageDraw.Draw(scr)
for k in range(8):   # a wide problem: eight lines of words across x 0.25 to 0.80, y 0.17 to 0.33
    y = int(0.17 * 1080) + k * 22
    for x in range(int(0.25 * 1920), int(0.80 * 1920), 46):
        d.rectangle((x, y, x + 34, y + 12), fill="black")
for k in range(40):  # a pane of code down the left, x 0.02 to 0.20, y 0.40 to 0.95
    y = int(0.40 * 1080) + k * 14
    d.rectangle((int(0.03 * 1920), y, int(0.03 * 1920) + 40 + (k * 37) % 250, y + 8), fill="black")
aspect = 1080 / 1920
wide = (0.16, 0.24, 0.34, 0.81)   # the problem's box with a margin, 0.24 0.16 0.81 0.34, written in y-first order
check("a wide problem's box written y first comes back turned", upright(scr, (0, 0, 1, 1), wide, aspect) == (0.24, 0.16, 0.81, 0.34),
      upright(scr, (0, 0, 1, 1), wide, aspect))
pane = (0.01, 0.38, 0.22, 0.97)
check("...and the box of a pane that stands that tall stays as it is", upright(scr, (0, 0, 1, 1), pane, aspect) == pane,
      upright(scr, (0, 0, 1, 1), pane, aspect))
check("...as does any box with no picture to look at", upright(None, (0, 0, 1, 1), wide, aspect) == wide)

print(f"\n==== {ok} passed, {bad} failed ====")
sys.exit(1 if bad else 0)
