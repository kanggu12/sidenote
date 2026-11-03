"""Does the capture program notice that a screen was scrolled rather than replaced?

    .venv/bin/python tests/scroll_auto.py

Builds screens with PIL (no Windows, no server) and checks scroll_shift on them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))   # client/ of the repository
import random                             # noqa: E402
from PIL import Image, ImageDraw          # noqa: E402
import capture                            # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))


def page(lines, offset=0, width=1600, height=900, side=True):
    """A problem page scrolled by `offset` lines, with a static pane on the right.

    Each line is drawn from a seed of its own, so no two lines look alike. Lines that repeat every
    few rows (the same words, the same lengths) make a scroll of that many lines match itself: with
    three repeating lines, an eight-line scroll was read as two lines, and a three-line scroll as
    none at all. Real pages hold headings, pictures and paragraphs of different lengths, which is
    what this draws.
    """
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    for i in range(80):
        y = 20 + (i - offset) * 28
        if not (-30 < y < height):
            continue
        rnd = random.Random(1000 + i)
        x = 40
        for _ in range(rnd.randint(2, 7)):     # words of different lengths, like a line of text
            wlen = rnd.randint(30, 150)
            if x + wlen > width // 2:
                break
            d.rectangle([x, y + rnd.randint(0, 4), x + wlen, y + 14], fill=(rnd.randint(0, 90),) * 3)
            x += wlen + rnd.randint(8, 24)
        if i % 9 == 0:                          # a heading or a picture every so often
            d.rectangle([40, y - 6, 40 + rnd.randint(120, 400), y + 20], outline="black", width=2)
    if side:
        d.rectangle([width // 2 + 20, 0, width, height], fill="#1e2430")
        d.text((width // 2 + 60, 40), "static editor pane", fill="#cfd6e4")
    return img


LINES = ["문제 설명 격자의 선로를 놓는다 ", "n x m 크기의 직사각형 격자 ", "입출력 예 와 제한사항 "]

a = capture.scroll_profile(page(LINES, 0))
for lines_moved, expect in ((0, False), (1, True), (3, True), (8, True), (20, True)):
    b = capture.scroll_profile(page(LINES, lines_moved))
    k = capture.scroll_shift(a, b)
    check(f"a scroll of {lines_moved} lines -> {'a continued screen' if expect else 'the same screen'}",
          bool(k) == expect, f"shift={k}")

other = capture.scroll_profile(page(["완전히 다른 화면입니다 ", "메일함 목록 ", "받은 편지 "], 0))
check("another screen is not a continued one", capture.scroll_shift(a, other) == 0,
      f"shift={capture.scroll_shift(a, other)}")

blank = capture.scroll_profile(Image.new("RGB", (1600, 900), "white"))
check("two blank screens: no shift", capture.scroll_shift(blank, blank) == 0)
check("the same screen twice: no shift", capture.scroll_shift(a, a) == 0)

# A site's own header and the browser's bar stay put above the page that scrolls (a coding test site: the problem
# pane scrolls under the header, the editor beside it does not). The profile used to take out each band's brightness
# over all rows, so the bar moved with every change of the page under it, and the shifted match never got good enough:
# the right shift found at 0.90 of the unshifted error, and no scroll read at all.
def under_header(offset):
    img = page(LINES, offset)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1600, 60], fill="#1e2430")                     # the header, which does not scroll
    d.text((24, 20), "코딩테스트 연습 > 문제", fill="#e8ecf2")
    return img


hdr = capture.scroll_profile(under_header(0))
for lines_moved in (1, 3, 8):
    k = capture.scroll_shift(hdr, capture.scroll_profile(under_header(lines_moved)))
    check(f"a scroll of {lines_moved} lines under a header bar that stays put is a continued screen too", bool(k), f"shift={k}")
from PIL import ImageEnhance  # noqa: E402
dim = capture.scroll_profile(ImageEnhance.Brightness(under_header(0)).enhance(0.8))
check("a screen that only changed its brightness is not a scroll", capture.scroll_shift(hdr, dim) == 0, f"shift={capture.scroll_shift(hdr, dim)}")

# Compared over the rows that changed, a short run of them matched a shift of itself: a chat widget 120 px high
# whose lines moved up by one read as a scroll of 5 rows, where the whole column it used to be compared
# over drowned it. A band's changed rows have to span a fifth of the screen.
def widget(offset):
    import random as _r
    img = page(["고정된 본문 한 줄 ", "다른 본문 줄 "], 0)
    box = Image.new("RGB", (1600, 120), "#f4f4f8")
    bd = ImageDraw.Draw(box)
    for i in range(12):
        r = _r.Random(900 + i)
        x = 10
        for _ in range(r.randint(3, 9)):
            w = r.randint(40, 160)
            bd.rectangle([x, i * 20 - offset + 4, x + w, i * 20 - offset + 14], fill=(r.randint(0, 120),) * 3)
            x += w + r.randint(10, 30)
    img.paste(box, (0, 700))
    return img


k = capture.scroll_shift(capture.scroll_profile(widget(0)), capture.scroll_profile(widget(20)))
check("lines moving up inside a small widget are not a scroll of the screen", k == 0, f"shift={k}")

up = capture.scroll_profile(page(LINES, 10))
down = capture.scroll_profile(page(LINES, 4))
k_up, k_down = capture.scroll_shift(a, up), capture.scroll_shift(up, down)
check("a scroll down and a scroll up come out with opposite signs", k_up * k_down < 0, f"{k_up} / {k_down}")



# --- the tray icon's pieces that run anywhere (the icon itself needs Windows) ---
check("the panel's address comes from the ingest address",
      capture.panel_url("ws://127.0.0.1:8777/ingest") == "http://127.0.0.1:8777/",
      capture.panel_url("ws://127.0.0.1:8777/ingest"))
check("another port is kept as it is",
      capture.panel_url("ws://127.0.0.1:9000/ingest") == "http://127.0.0.1:9000/",
      capture.panel_url("ws://127.0.0.1:9000/ingest"))
check("wss becomes https", capture.panel_url("wss://host/ingest") == "https://host/",
      capture.panel_url("wss://host/ingest"))
img = capture.tray_image()
check("the tray picture is 256x256 on a transparent ground", img.size == (256, 256) and img.mode == "RGBA", f"{img.size} {img.mode}")
check("and it is drawn at a small size too", capture.tray_image(16).size == (16, 16))

print(f"\n==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)
