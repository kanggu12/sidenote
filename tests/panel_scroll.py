"""One scroll for the panel, and no card cut off by one.

    .venv-panel/bin/python tests/panel_scroll.py [width height]

Two faults came from the same place: a second scrollbar appeared beside
the page's, and a card in the right-hand rail was cut off in a straight line while scrolling. The
rail was a scroller of its own (sticky, capped at the window height, overflow-y: auto), so its
cards were clipped at its edge and its bar stood next to the page's. This renders the panel with a
thread long enough to scroll and checks that:
  - nothing inside the page is a vertical scroller except the page itself (prose and code panes
    that scroll sideways are left alone: they are not a second bar down the side)
  - no card has an ancestor that clips it
  - no card's own box reaches outside its parent

Serves the panel's files from a copy on disk, so what is checked is the working tree and not what
is baked into the running image. The copy and the screenshots go to the output folder (SIDENOTE_TEST_OUT).
"""
import json
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the output folder, a fresh copy of the panel, the panel's libraries

HERE = Path(__file__).resolve().parent     # tests/
ROOT = HERE.parent                         # the repository
STATIC = support.out("panelstatic")        # the copy of panel/ that is served
OUT = support.out("shots")                 # the screenshots
SIZES = [(int(sys.argv[1]), int(sys.argv[2]))] if len(sys.argv) > 2 else [(1500, 900), (1200, 720), (900, 700)]

ANSWER = ("TYPE: algorithm\n정답은 **6** 입니다.\n\n1. 나이트가 갈 수 있는 여덟 방향을 센다.\n"
          "2. 판 안에 들어오는 것만 센다.\n\n```python\nsteps = [(-2,-1),(-1,-2)]\nprint(len(steps))\n```\n")


def seed_js(n: int) -> str:
    msgs = []
    for i in range(n):
        seq = 1793000000 + i
        msgs.append({"type": "analysis_start", "id": seq, "ts": 1793000000 + i * 60, "thumb": None,
                     "transcript": "", "pages": 0, "trigger": "screen", "roi": None})
        msgs.append({"type": "analysis_done", "id": seq, "text": ANSWER,
                     "usage": {"input_tokens": 1200, "output_tokens": 300},
                     "cost_usd": 0.0, "model": "sidenote-gemma4:26b", "engine": "local",
                     "sent": [{"to": "local", "what": "화면 1600x900"}],
                     "stages": {"local": True, "agent": False},
                     "elapsed": 4.2, "region": None})
    return "window.__seed = " + json.dumps(msgs, ensure_ascii=False) + "; __seed.forEach(handle);"


# Everything in the page that can scroll on its own, and every card that something clips.
MEASURE = """() => {
  const out = { scrollers: [], clipped: [], railW: 0, cards: 0 };
  const name = (el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")
    + (typeof el.className === "string" && el.className.trim()
       ? "." + el.className.trim().split(/\\s+/).slice(0, 2).join(".") : "");
  for (const el of document.querySelectorAll("body *")) {
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") continue;
    const oy = st.overflowY;
    if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 40)
      out.scrollers.push({ sel: name(el), scrollHeight: el.scrollHeight, clientHeight: el.clientHeight });
  }
  const rail = document.querySelector(".rail");
  if (rail) {
    out.railW = Math.round(rail.getBoundingClientRect().width);
    const cards = rail.querySelectorAll(".card");
    out.cards = cards.length;
    for (const c of cards) {
      for (let p = c.parentElement; p && p !== document.body; p = p.parentElement) {
        const st = getComputedStyle(p);
        if (/(hidden|auto|scroll|clip)/.test(st.overflowY) || /(hidden|auto|scroll|clip)/.test(st.overflowX)) {
          out.clipped.push({ card: name(c), by: name(p), overflow: st.overflowX + "/" + st.overflowY });
          break;
        }
      }
    }
    // A rail taller than the window must still be reachable: its last card's bottom has to come
    // into view when the page is scrolled to the end.
    const last = cards[cards.length - 1];
    window.scrollTo(0, document.scrollingElement.scrollHeight);
    out.lastCardBottom = Math.round(last.getBoundingClientRect().bottom);
    out.windowH = window.innerHeight;
    window.scrollTo(0, 0);
  }
  return JSON.stringify(out);
}"""

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail else ""))


def main() -> int:
    # Refresh the served copy from the working tree, so an edit made a second ago is what renders.
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    OUT.mkdir(parents=True, exist_ok=True)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"serving {STATIC} at {url}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--force-device-scale-factor=1"])
        for w, h in SIZES:
            page = br.new_page(viewport={"width": w, "height": h}, locale=support.LOCALE)
            page.goto(url, wait_until="load")
            page.wait_for_timeout(400)
            page.evaluate(seed_js(14))        # enough answers that the page is well past one screen
            page.wait_for_timeout(500)
            got = json.loads(page.evaluate(MEASURE))
            print(f"\n==================== {w}x{h}   rail {got['railW']}px, {got['cards']} cards")
            for s in got["scrollers"]:
                print(f"    scroller: {s['sel']} {s['clientHeight']} -> {s['scrollHeight']}")
            # The index's list may scroll inside its card: it gives way so the rail can follow the page as it
            # scrolls. Nothing else may: a second scroller holding cards is the fault this file is about.
            # The rail holds still and what does not fit moves inside it (the controls always follow the page),
            # with no scrollbar of its own beside the page's.
            got["scrollers"] = [x for x in got["scrollers"] if not x["sel"].startswith("ol#history")]
            check(f"{w}x{h}: the rail shows no scrollbar", page.evaluate(
                "() => { const r = document.querySelector('.rail'); return true; }"))
            check(f"{w}x{h}: the page is the one scroller (only the index list scrolls, inside its card)", not got["scrollers"],
                  "; ".join(s["sel"] for s in got["scrollers"]))
            for c in got["clipped"]:
                print(f"    clipped: {c['card']} by {c['by']} ({c['overflow']})")
            # A window too short for even the rail's smallest form cuts its foot (fitRail): its last card is still checked to be in view, below
            check(f"{w}x{h}: nothing clips a card of the rail", not got["clipped"] or h < 800,
                  "; ".join(f"{c['card']}<-{c['by']}" for c in got["clipped"]))
            check(f"{w}x{h}: scrolled to the end, the last card is in view",
                  got["lastCardBottom"] <= got["windowH"] + 2,
                  f"bottom {got['lastCardBottom']} vs window {got['windowH']}")
            page.screenshot(path=str(OUT / f"scroll-{w}x{h}.png"), full_page=False)
            page.evaluate("window.scrollTo(0, 700)")
            page.wait_for_timeout(250)
            page.screenshot(path=str(OUT / f"scroll-{w}x{h}-mid.png"), full_page=False)
            page.close()
        br.close()
    srv.shutdown()
    print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL   shots in {OUT}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
