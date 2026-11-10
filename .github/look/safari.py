"""The panel's top layers in Safari itself, on the look workflow's macOS runner: Safari's WebDriver drives a copy of the
panel served as the panel suites serve it (tests/panel_harness.py, Stand), its socket the suites' stand-in, loaded first.
At four widths, at the top of the page and scrolled, with no band and with two: a short notice, a long one with its key,
and the gear menu, each measured with tests/panel_layout.py's own count of the boxes whose edges cross it (TOP_CROSS),
and pictures of them as Safari draws them, its blur behind the glass included. look.json holds the counts.

    python .github/look/safari.py <out folder>
"""
import json
import os
import re
import sys
import time
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true":              # it drives Safari's own windows: a runner's only
    sys.exit(".github/look/safari.py drives Safari's windows: it runs on a CI runner only")
ROOT = Path(__file__).resolve().parents[2]                  # the repository: this file is in .github/look/
OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("SIDENOTE_TEST_OUT", str(OUT / "work"))   # where the harness copies the panel to serve it
sys.path.insert(0, str(ROOT / "tests"))
import panel_harness as h  # noqa: E402
from selenium import webdriver  # noqa: E402

CROSS = re.search(r'^TOP_CROSS = r"""(.*?)"""', (ROOT / "tests" / "panel_layout.py").read_text(encoding="utf-8"), re.S | re.M).group(1)
stand = h.Stand("safari")
kinds = ["mcq", "algorithm", "essay", "work", "code", "sql"]
stand.rows = [h.row(200 + i, kinds[i % 6], f"A question asked at some length, number {i} " * 2, "The answer", "The working " * 30,
                    ago=86400 * (i // 7) + 1800 - i * 60) for i in range(30)]
# The suites' stand-in socket, and a dark theme, ahead of the panel's own scripts: a file of the page's own, as its CSP lets in
(stand.static / "look-first.js").write_text(h.SOCKET + "\ntry { localStorage.setItem('sidenote-theme', 'dark'); } catch (e) {}\n",
                                            encoding="utf-8")
page = stand.static / "index.html"
page.write_text(page.read_text(encoding="utf-8").replace("<head>", '<head><script src="look-first.js"></script>', 1), encoding="utf-8")

d = webdriver.Safari()
report = {"safari": d.capabilities.get("browserVersion"), "platform": d.capabilities.get("platformName"), "rows": []}


def js(expr, *args):
    return d.execute_script(expr, *args)


def send(msg):
    js("window.__sock.onmessage({ data: JSON.stringify(arguments[0]) })", msg)


def size(width, height=900):
    """The window made as large as a page `width` wide shows: its frame's own size taken off first."""
    d.set_window_rect(x=0, y=0, width=width + 40, height=height + 120)
    inner = js("return [innerWidth, innerHeight]")
    d.set_window_rect(x=0, y=0, width=width + 40 + (width - inner[0]), height=height + 120 + (height - inner[1]))
    time.sleep(0.4)
    return js("return [innerWidth, innerHeight]")


def status(bands):
    e = json.loads(json.dumps(h.ENGINES))
    e["local"]["ok"] = bands == "none"
    e["agent"]["ok"] = bands != "two"
    send({"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": True,
          "run_enabled": True, "runner": True, "engines": e})


d.get(stand.url)
for _ in range(80):                                         # the panel's socket made, with its handler
    if js("return !!(window.__sock && window.__sock.onmessage)"):
        break
    time.sleep(0.1)
now = js("return Date.now() / 1000")
status("none")
send({**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3})
send(h.USAGE)
send(h.GPU)
time.sleep(1.0)
measure = f"return ({CROSS})(arguments[0])"
for bands in ("none", "two"):
    status(bands)
    time.sleep(0.4)
    for width in (1440, 1100, 900, 760):
        inner = size(width)
        for y in (0, 700):
            js("stick = false; window.scrollTo(0, arguments[0]); placeBands();", y)
            time.sleep(0.5)
            row = {"width": inner[0], "bands": bands, "scrolled": y}
            for label, call in (("short", "toast('Restored', null, 'done')"),
                                ("long", "toast('Deleted · in Recently deleted for 30 days', () => {}, 'done', '', 'Undo')")):
                js(call)
                time.sleep(0.8)                             # the notice in, the signals or the bands faded out of its way
                crossed = js(measure, "#toast")
                box = js("const r = document.getElementById('toast').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect();"
                         "return [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom), r.top >= b.top && r.bottom <= b.bottom]")
                row[label] = {"box": box[:4], "in_bar": box[4], "crossed": crossed}
                d.save_screenshot(str(OUT / f"{label}-{inner[0]}-{bands}-{y}.png"))
                js("clearTimeout(toast.timer); document.getElementById('toast').classList.remove('show');")
                time.sleep(0.4)
            js("toggleMenu(true)")
            time.sleep(0.8)
            row["menu"] = {"crossed": js(measure, "#menu"),
                           "box": js("const r = document.getElementById('menu').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round)")}
            d.save_screenshot(str(OUT / f"menu-{inner[0]}-{bands}-{y}.png"))
            js("toggleMenu(false)")
            time.sleep(0.4)
            report["rows"].append(row)
# What Safari takes of the glass: the blur behind the menu, the notice and the bar, as it computes them
report["backdrop"] = js("""toggleMenu(true); const f = (el, p) => { const cs = getComputedStyle(el, p || null);
    return [cs.backdropFilter || '', cs.webkitBackdropFilter || '']; };
    const out = { menu: f(document.getElementById('menu')), bar: f(document.querySelector('header.bar'), '::before') };
    toggleMenu(false); return out;""")
d.quit()
bad = [r for r in report["rows"] if r["short"]["crossed"] or r["long"]["crossed"] or r["menu"]["crossed"]
       or not r["short"]["in_bar"] or not r["long"]["in_bar"]]
report["states"], report["with_crossings_or_out_of_bar"] = len(report["rows"]), len(bad)
(OUT / "look.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: report[k] for k in ("safari", "platform", "states", "with_crossings_or_out_of_bar", "backdrop")}, ensure_ascii=False))
for r in bad:
    print("  ", r["width"], r["bands"], r["scrolled"], "short", r["short"], "long", r["long"], "menu", r["menu"])
