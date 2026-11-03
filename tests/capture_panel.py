"""The capture program with this tool's own panel on the screen: its area is painted over, a window in front
of it keeps what it showed, and a change inside it is no longer a new screen.
  python tests/capture_panel.py [path to capture.py]"""
import importlib.util
import sys
from pathlib import Path

from PIL import Image

# the capture program of this repository (this file is in tests/), or an older copy named on the command line
spec = importlib.util.spec_from_file_location(
    "cap", sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "client" / "capture.py"))
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
OK, BAD = [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {got}" if got and not cond else ""))


# The page is titled "Sidenote Panel", so its window starts with that whatever the browser adds. The
# Korean word it used to be titled with is still matched, for a tab left open across the change.
# A window that merely holds the word is somebody's editor or folder and must not be painted over
# ("sidenote - Visual Studio Code" was, under the older rule).
TITLES = [("Sidenote 패널", True), ("Sidenote 패널 - Chrome", True), ("Sidenote 패널 — Mozilla Firefox", True),
          ("Sidenote 패널 and 2 more pages - Microsoft Edge", True),
          ("Sidenote 패널 및 페이지 2개 - Microsoft Edge", True),
          ("Sidenote", False), ("Sidenote - Chrome", False),
          ("sidenote - Visual Studio Code", False), ("capture.py - sidenote - Visual Studio Code", False),
          ("dev@pc: ~/sidenote", False), ("Sidenote.md - Visual Studio Code", False),
          ("sidenote 설계 - Notion", False), ("Sidenote 패널 설계 - Notion", False),
          ("Sidenote Panel", True), ("Sidenote Panel - Chrome", True),
          ("Sidenote Panel and 2 more pages - Microsoft Edge", True),
          ("Sidenote Panels - Chrome", False), ("Sidenote Panel 설계 - Notion", False)]
check("the panel's own title is told from a window that merely holds the word",
      all(bool(cap.OWN_TITLE.match(t)) is want for t, want in TITLES),
      str([t for t, want in TITLES if bool(cap.OWN_TITLE.match(t)) is not want]))

# a screen with a problem on the left, the panel on the right, and a chat window over the panel's corner
screen = Image.new("RGB", (1000, 500), (240, 240, 240))
screen.paste((10, 120, 200), (0, 0, 500, 500))      # the problem window
screen.paste((250, 250, 120), (500, 0, 1000, 500))  # the panel
screen.paste((0, 200, 0), (900, 400, 1000, 500))    # a window over its corner
rects = [[0.9, 0.8, 1.0, 1.0], [0.5, 0.0, 1.0, 1.0], [0.0, 0.0, 0.5, 1.0]]   # front to back
out = cap.hide_own(screen, rects, [1])
check("the problem window is untouched", out.getpixel((250, 250)) == (10, 120, 200), str(out.getpixel((250, 250))))
check("the panel's area is painted over", out.getpixel((700, 250)) != (250, 250, 120), str(out.getpixel((700, 250))))
check("a window in front of the panel keeps what it showed", out.getpixel((950, 450)) == (0, 200, 0),
      str(out.getpixel((950, 450))))
check("nothing is painted when the panel is not on screen", cap.hide_own(screen, rects, []) is screen)
# the gate reads the painted screen, so the panel's own updates are not a new screen. It reads the
# frame as it was grabbed: the 1600-wide copy the loop used to make first is gone (the signature
# shrinks what it is given to 160x120 of its own accord, scratch/smoke/gate_filter.py).
before = cap.signature(out)
screen2 = screen.copy()
screen2.paste((255, 0, 0), (520, 20, 980, 380))   # the panel repainted with a new answer
after = cap.signature(cap.hide_own(screen2, rects, [1]))
check("a new answer on the panel is not a new screen", bool((before == after).all()))
print(f"\n==== {len(OK)} of {len(OK) + len(BAD)} as expected")
if BAD:
    print("FAILURES: " + ", ".join(BAD))
sys.exit(1 if BAD else 0)   # tests/run.sh counts a suite by its exit status
