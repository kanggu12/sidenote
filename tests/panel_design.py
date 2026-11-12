"""What the panel looks like, measured: the control column at every size, its one material, the ribbon, and an answer drawn from its own words.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_design.py
    ONLY="material,drawn" ...                    # only the groups named
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

Taste cannot be checked; what a design promises can. The contents' card measured another colour from the others for weeks because the rules that were to make it glass lost
to older ones of higher specificity, and no check looked at the result. Here every card's colour is read back off a screenshot, at each window size. The matrix
goes through every width and height with the column full, with the capture program gone and with the agent off, and looks for what overflows, what is cut and what has gone
that was promised to stay. An answer is drawn from its shape: no word may be lost in the drawing, over every sample and over the bench's 491 real answers where they are at hand.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, contrast, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support


def group_stylesheet():
    if not T.group("the stylesheet"):
        return
    css = (h.PANEL / "index.html").read_text(encoding="utf-8")
    # The whole class of failure behind the wrong colour: a later rule written html[...] loses to an earlier :root[...] of the same selector, in silence
    check("no Classic rule is written so that it loses to an older one: html[data-skin] is one class weaker than :root[data-skin]", 'html[data-skin="classic"]' not in css,
          css.count('html[data-skin="classic"]'))


def group_material(br, s):
    if not T.group("one material down the column"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", "답", "풀이", ago=900 - i) for i in range(8)]
    for theme, tolerance in (("dark", 14), ("light", 5)):
        for w, hh in ((1280, 720), (1440, 900), (1440, 1300), (1920, 1040), (2560, 1400)):
            p = Page(br, s, rows, w=w, h=hh, theme=theme)
            p.send({"type": "transcript", "text": "들리는 말", "lang": "ko"})
            # Taller than the window the column drifts with the page: each card is measured in the window, scrolled to where it is
            # seen, over the window's own light (body::before is fixed to the window: a picture of the whole page stretches its fall
            # from the bar's light to the foot's dark over the page, and a card far down read darker than it looks)
            p.js("() => { stick = false; window.scrollTo(0, 0); }")
            p.wait(250)
            cards = p.js("""() => [...document.querySelectorAll('.rail .card')].filter((c) => c.offsetParent).map((c) => { const b = c.getBoundingClientRect(), s = getComputedStyle(c);
                return { name: c.className, x: b.x, y: b.y + scrollY, w: b.width, h: b.height, bg: s.backgroundImage.slice(0, 60) + s.backgroundColor, blur: s.backdropFilter, line: s.borderBottomColor }; })""")
            if w == 1920:
                same = len({(c["bg"], c["blur"], c["line"]) for c in cards}) == 1
                check(f"{theme}: every card is made of the same glass", same, [(c["name"], c["bg"][:30], c["blur"]) for c in cards])
            # A strip of bare glass inside the left edge of each card: above its first words and within its padding
            colours = []
            for i, c in enumerate(cards):
                p.js("(y) => { stick = false; window.scrollTo(0, y); return scrollY; }", max(0, int(c["y"]) - 90))
                p.wait(120)
                # where the card stands in the window now: a drifting column moves with the page only until its foot is in view
                y = int(p.js("(i) => [...document.querySelectorAll('.rail .card')].filter((c) => c.offsetParent)[i].getBoundingClientRect().y", i))
                colours += h.pixels(br, p.page.screenshot(), [[int(c["x"]) + 3, y + 40, int(c["x"]) + 12, y + int(c["h"]) - 14]])
            spread = max(max(col[i] for col in colours) - min(col[i] for col in colours) for i in range(3))
            check(f"{theme} {w}x{hh}: the cards measure the same colour, within {tolerance} of 255", spread <= tolerance, [[round(v) for v in c] for c in colours])
            hue = max(abs(col[2] - col[1]) for col in colours)
            check(f"{theme} {w}x{hh}: and graphite, not tinted", hue <= 10, [[round(v) for v in c] for c in colours])
            p.close()


FULL, OFF, AGENT_OFF = "full", "capture gone", "agent off"


def group_matrix(br, s):
    if not T.group("the column at every size"):
        return
    # two of the newest starred: their rows' stars are measured with the rest of the column, at every size
    rows = [row(200 + i, "mcq", f"이것은 꽤 길게 쓴 문제의 물음입니다 {i}" * 2, "답", "풀이", ago=1800 - i * 40, thumb=h.thumb(960, 540), region=[.2, .2, .6, .8],
                starred=i in (26, 29)) for i in range(30)]
    list_rows = {}
    for w in (1100, 1280, 1440, 1920, 2560):
        for hh in (620, 700, 768, 860, 950, 1040, 1200, 1440):
            for state in ((FULL,) if (w, hh) not in ((1440, 900), (1280, 720), (1920, 1040)) else (FULL, OFF, AGENT_OFF)):
                p = Page(br, s, rows, w=w, h=hh, settle=450)
                if state == OFF:
                    p.send({**h.CAPTURE, "now": p.js("() => Date.now() / 1000"), "clients": 0})
                if state == AGENT_OFF:
                    eng = json.loads(json.dumps(h.ENGINES))
                    eng["agent"].update(mode="off", effective="off", ok=True)
                    p.send({"type": "status", "engines": eng})
                p.wait(200)
                m = p.js("""() => {
                    const rail = document.querySelector('.rail'), b = rail.getBoundingClientRect(), bad = [];
                    for (const card of rail.querySelectorAll('.card')) {
                      if (!card.offsetParent) continue;
                      const c = card.getBoundingClientRect();
                      for (const e of card.querySelectorAll('button, input, .pill, .switch, dd, .stat, .h, .h-star, .h-tab, time, h2')) {
                        if (!e.offsetParent && !(e instanceof SVGElement && e.getClientRects().length)) continue;   // a mark has no offsetParent
                        const r = e.getBoundingClientRect();
                        if (r.width && (r.right > c.right + 0.5 || r.left < c.left - 0.5)) bad.push(e.tagName + '.' + (e.className.baseVal ?? e.className) + ' ' + Math.round(r.right - c.right));
                      }
                    }
                    // the two starred rows' stars are there to be measured, so the list above cannot pass for want of them
                    const stars = document.querySelectorAll('#history .h-star').length;
                    if (stars !== 2) bad.push(`the starred rows' stars: ${stars} of 2`);
                    const rights = [...rail.querySelectorAll('.switch, .src-top .btn, #hist-export, #roi-draw')].filter((e) => e.offsetParent).map((e) => Math.round(e.getBoundingClientRect().right));
                    const list = document.getElementById('history'), lb = list.getBoundingClientRect();
                    const seen = [...list.querySelectorAll('.h')].filter((x) => { const r = x.getBoundingClientRect(); return r.bottom <= lb.bottom + 1 && r.top >= lb.top - 1; }).length;
                    const clip = [...rail.querySelectorAll('.src-top .pill, .src-name, .agent-who .mail')].filter((e) => e.offsetParent && e.scrollWidth > e.clientWidth + 1).map((e) => e.className);
                    return { side: document.documentElement.scrollWidth - document.documentElement.clientWidth, foot: b.bottom, cut: rail.style.overflow, bad, rights, seen,
                             clip, one: matchMedia('(max-width: 1000px)').matches,
                             model: !!document.querySelector('#st-agent .model')?.offsetParent, usage: !!document.querySelector('#usage-local .stat')?.offsetParent && !!document.querySelector('#usage-agent .stat')?.offsetParent,
                             who: !!document.querySelector('.agent-who')?.offsetParent, pills: [...rail.querySelectorAll('.src-top .pill')].filter((e) => e.offsetParent).length,
                             groups: [...rail.querySelectorAll('.rail-col')].filter((c) => getComputedStyle(c).display !== 'contents').length || 1 };
                }""")
                name = f"{w}x{hh} {state}"
                check(f"{name}: the page does not scroll sideways", m["side"] <= 0, m["side"])
                check(f"{name}: nothing stands outside its card", not m["bad"], m["bad"][:4])
                if not m["one"]:
                    check(f"{name}: the column's foot is inside the window, nothing cut", m["foot"] <= hh + .5 and not m["cut"], f'{m["foot"]} {m["cut"]}')
                    # one right edge for each group of cards: two side by side on a wide window (index.html, .rail-col)
                    edges = sorted(m["rights"])
                    runs = [[edges[0]]] if edges else []
                    for x in edges[1:]:
                        (runs[-1].append(x) if x - runs[-1][-1] <= 1 else runs.append([x]))
                    check(f"{name}: the keys stand on one right edge in each group", len(runs) <= m["groups"], m["rights"])
                    check(f"{name}: a state or a name is not cut", not m["clip"], m["clip"])
                    check(f"{name}: at least a row of the contents", m["seen"] >= 1, m["seen"])
                    if hh >= 768:
                        check(f"{name}: two rows of the contents from 768 up", m["seen"] >= 2, m["seen"])
                    if hh >= 700 and state != AGENT_OFF:
                        check(f"{name}: the agent's model is still there from 700 up", m["model"] and m["who"], m)
                    if hh >= 860:
                        check(f"{name}: the averages are still there from 860 up", m["usage"], m["usage"])
                    if state == FULL:
                        list_rows.setdefault(w, []).append((hh, m["seen"]))
                check(f"{name}: the page threw nothing", not p.errors, p.errors[:2])
                p.close()
    for w, seen in list_rows.items():
        check(f"{w} wide: a taller window never shows fewer rows by more than one", all(b[1] >= a[1] - 1 for a, b in zip(seen, seen[1:])), seen)
    # Left alone, the column holds still: with "less motion" on, a zero-length transition on everything made what the fit measured the old value, and it flipped between two
    # layouts every quarter of a second for as long as the page was open
    still = """() => { const r = document.querySelector('.rail'); return [Math.round(r.getBoundingClientRect().height), r.className, document.documentElement.style.getPropertyValue('--shot-h'), document.getElementById('history').style.maxHeight].join('|'); }"""
    for reduced in (True, False):
        for hh in (700, 860, 950, 1200):
            p = Page(br, s, rows, w=1920, h=hh, settle=900, reduced=reduced)
            seen = set()
            for _ in range(10):
                seen.add(p.js(still))
                p.wait(110)
            check(f"{hh} high, {'less motion' if reduced else 'motion'}: the column holds still", len(seen) == 1, seen)
            p.close()


def group_engines(br, s):
    """This PC's model and the agent told apart: a card each, each with its own figures and its own answers as bars."""
    if not T.group("the two engines"):
        return
    p = Page(br, s, [row(950 + i, "essay", f"문제 {i}", "답", "풀이", ago=100 - i) for i in range(3)], w=1920, h=1500)
    read = """(id) => { const c = document.getElementById(id); return { stats: [...c.querySelectorAll('.stat b')].map((b) => b.textContent), bars: c.querySelectorAll('.bars .bar').length, sub: c.querySelector('.usage-sub')?.textContent, gpu: !!c.querySelector('#gpu-viz'), who: !!c.querySelector('.agent-who'), err: c.querySelector('.usage-err')?.textContent, switch: !!c.querySelector('.switch'), key: c.querySelector('.key.wait')?.textContent }; }"""
    local, agent = p.js(read, "card-local"), p.js(read, "card-agent")
    check("this PC's model has its card, its own figures and its GPU", local["stats"] == ["15건", "12.4초", "2.1초", "96.3"] and local["gpu"] and not local["who"], local)
    check("the agent has its card, its own figures and its account", agent["stats"] == ["3건", "41.7초", "22.8초", "71.2"] and agent["who"] and not agent["gpu"], agent)
    check("each answer of each is a bar", local["bars"] == 15 and agent["bars"] == 3, (local["bars"], agent["bars"]))
    check("what a bar's two parts are is said", local["key"] == "TTFT" and agent["key"] == "TTFT", local["key"])
    check("what it cost is the agent's; this PC's costs nothing", "$0.43" in agent["sub"] and "$" not in local["sub"] and "비용 없음" in local["sub"], (local["sub"], agent["sub"]))
    # Nothing in the column folds now (everything shows), so the cost is said once, on the small print's line: the copy
    # beside the count, for when that line had gone on a short window, went with the folding
    tiles = p.js("() => { const c = document.getElementById('card-agent'); return [c.querySelectorAll('.stat .k.also').length, (c.innerText.match(/\\$0\\.43/g) || []).length]; }")
    check("...said once, on the small print's line", tiles == [0, 1], tiles)
    words = p.js("() => document.querySelector('#gpu-viz')?.textContent || ''")
    check("the GPU's gauges do not say the model's state a third time", "모델 대기" not in words and "모델 올라감" not in words, words)
    p.send({"type": "usage", "answers": 1, "engines": {"local": {"answers": 0}, "agent": {"answers": 1, "tokens_in": 98123456, "tokens_out": 12345678, "cost_usd": 12345.6789, "elapsed_p50": 512.5, "first_token_avg": 123.4, "tps_avg": 1234.5, "recent": []}}})
    p.wait(100)
    huge = p.js("""() => { const c = document.getElementById('card-agent').getBoundingClientRect(), sub = document.querySelector('#card-agent .usage-sub'); const inked = (e) => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect(); }; return { text: sub.textContent, over: [...document.querySelectorAll('#card-agent .stat, #card-agent .usage-sub span')].filter((e) => e.getBoundingClientRect().right > c.right - 1 || e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent), intoNext: [...document.querySelectorAll('#card-agent .stat')].filter((e) => [...e.children].some((x) => inked(x).right > e.getBoundingClientRect().right + .5)).map((e) => e.textContent), lines: sub.getClientRects().length, h: sub.getBoundingClientRect().height }; }""")
    check("huge figures stay on their line, shortened, with no overflow", "98.1M" in huge["text"] and "$12.3k" in huge["text"] and not huge["over"] and not huge["intoNext"] and huge["h"] < 32, huge)
    p.send(h.USAGE)
    p.wait(80)
    check("an error is said on the card of the engine it happened on", agent["err"] and not local["err"], (local["err"], agent["err"]))
    colours = p.js("""() => ['card-local', 'card-agent'].map((id) => getComputedStyle(document.querySelector('#' + id + ' .bar')).backgroundColor)""")
    check("the two are told apart by colour too", colours[0] != colours[1], colours)
    drawn = p.js("""() => ({ meter: getComputedStyle(document.querySelector('#gpu-viz .meter i')).backgroundColor, bar: getComputedStyle(document.querySelector('#card-local .bar')).backgroundColor, steps: getComputedStyle(document.querySelector('#card-agent .steps3 i.on')).backgroundColor, agentBar: getComputedStyle(document.querySelector('#card-agent .bar')).backgroundColor })""")
    check("all that draws an engine's figures is in its colour", drawn["meter"] == drawn["bar"] and drawn["steps"] == drawn["agentBar"], drawn)
    wait = p.js("""() => { const b = document.querySelector('#card-agent .bar > b'), bar = b.parentElement; return [b.style.height, bar.title]; }""")
    check("a bar's lower part is the wait for the first token, and its tooltip gives the figures", wait[0] == "60%" and "TTFT 18" in wait[1] and "TPS" in wait[1], wait)
    eng = {"type": "usage", "answers": 0, "engines": {"local": {"answers": 0}, "agent": {"answers": 2, "recent": []}}}
    p.send(eng)
    p.wait(100)
    empty = p.js("() => document.querySelector('#usage-local').textContent")
    check("an engine with nothing today says so, in its own card", "이 PC의 모델" in empty and "아직" in empty, empty)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_readable(br, s):
    if not T.group("what can be read and pressed"):
        return
    rows = [row(300 + i, "algorithm", f"문제 {i}", "답", "- **이름**: 설명\n- **둘째**: 설명\n\n1. **단계**: 설명\n2. **다음**: 설명\n\n시간 O(N), 공간 O(1)\n", ago=90000 if i == 0 else 100 - i,
                starred=i == 2) for i in range(4)]
    words = {".src-name": "a source's name", ".fact dt": "a fact's name", ".fact dd": "a fact", ".stat b": "a figure", ".stat .k": "what a figure is", ".h .ht": "a row of the contents",
             ".h time": "a row's time", ".h-tab": "a day's tab", ".h-n": "a day's count", "#hist-count": "the contents' count", ".md .v-t": "a part's name", ".md .v-b": "a part's words",
             ".v-tick": "the scale's classes", ".combo-val": "a filter's words"}
    for theme in ("dark", "light"):
        p = Page(br, s, rows, w=1920, h=1300, theme=theme)
        p.js("() => { unfolded.add(303); renderEntry(items.get(303)); }")
        p.wait(200)
        seen = {}
        for at in ("foot", "top"):
            if at == "top":
                p.js("() => { stick = false; window.scrollTo(0, 0); }")
                p.wait(250)
            png = p.page.screenshot()
            for sel in words:
                if sel in seen:
                    continue
                got = p.js("""(sel) => { const e = [...document.querySelectorAll(sel)].find((x) => { const r = x.getBoundingClientRect(); return x.offsetParent && r.width > 4 && r.top > 0 && r.bottom < innerHeight; });
                    if (!e) return null; const r = e.getBoundingClientRect(), c = getComputedStyle(e).color.match(/[\\d.]+/g).map(Number);
                    return { box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)], colour: c }; }""", sel)
                if got is not None:
                    seen[sel] = (got, png)
        for sel, what in words.items():
            if sel not in seen:
                check(f"{theme}: {what} is there to read ({sel})", False)
                continue
            got, png = seen[sel]
            bg = h.background_of(br, png, got["box"])
            ratio = contrast(got["colour"], bg)
            check(f"{theme}: {what} reads at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f} {got['colour']} on {bg}")
        small = p.js("""() => [...document.querySelectorAll('.rail button, .rail .switch, .rail input, .actions .btn')].filter((e) => { const r = e.getBoundingClientRect(); return e.offsetParent && (r.height < 24 || r.width < 24); })
                        .filter((e) => !e.closest('#history')).map((e) => e.id || e.className)""")
        check(f"{theme}: what is pressed in the column is 24 px or more", not small, small)
        # A star's yellow alone is 1.5:1 on the light sheet: its outline is the ink of the words beside it, which read at 4.5:1 above
        ink = p.js("""() => { const s = document.querySelector('#history .h-star'), k = document.querySelector('.entry [data-star][aria-pressed="true"]');
            return s && k ? [getComputedStyle(s).stroke, getComputedStyle(s.parentElement).color, getComputedStyle(k.querySelector('svg')).stroke, getComputedStyle(k).color] : null; }""")
        check(f"{theme}: a star's outline is the ink of the words beside it, on its row and on its key", bool(ink) and ink[0] == ink[1] and ink[2] == ink[3], ink)
        check(f"{theme}: the page threw nothing", not p.errors, p.errors[:2])
        p.close()


def group_release(br, s):
    """The notice of a newer release, at every width from a phone's to a wide screen's, in both themes and in English and Korean:
    inside its band and the window, on one line wherever the band leaves its words room (a phone's 360 and 390 px do not for the
    English: there the link goes to a second line whole), its words as readable as the other bands', its close key big enough to
    press. English is the longer of the two, and the one the room is measured against."""
    if not T.group("the release notice at every width"):
        return
    upd = {"type": "status", "update": {"version": "0.1.2", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.1.2"}}
    measure = """() => {
      const a = [...document.querySelectorAll('#alerts .alert')].find((x) => x.querySelector('[data-act="update-hide"]'));
      if (!a) return null;
      const r = a.getBoundingClientRect(), msg = a.querySelector('.msg'), key = a.querySelector('[data-act="update-hide"]').getBoundingClientRect();
      const link = a.querySelector('.msg a'), words = document.createRange();
      words.selectNodeContents(msg);
      const boxes = [...words.getClientRects()].filter((x) => x.width > 0);
      const b = msg.querySelector('b').getBoundingClientRect(), c = getComputedStyle(msg.querySelector('b')).color.match(/[\\d.]+/g).map(Number);
      return { band: [r.left, r.top, r.right, r.bottom], lines: new Set(boxes.map((x) => Math.round(x.top))).size,
               out: boxes.some((x) => x.left < r.left - .5 || x.right > r.right + .5) || key.left < r.left || key.right > r.right + .5 || key.top < r.top || key.bottom > r.bottom + .5,
               linkLines: link ? link.getClientRects().length : 0, key: [key.width, key.height], words: [Math.floor(b.left), Math.floor(b.top), Math.ceil(b.right), Math.ceil(b.bottom)], colour: c,
               side: document.documentElement.scrollWidth - document.documentElement.clientWidth, W: innerWidth };
    }"""
    for locale in ("en-US", "ko-KR"):
        for theme in ("dark", "light"):
            for w in (360, 390, 414, 600, 768, 1000, 1001, 1280, 1440, 1920, 2560):
                p = Page(br, s, [row(970, "essay", "문제", "답", "풀이")], w=w, h=900, theme=theme, settle=300, locale=locale)
                p.send(upd)
                p.js("() => { stick = false; window.scrollTo(0, 0); placeBands(); }")
                p.wait(250)
                m = p.js(measure)
                name = f"{locale[:2]} {theme} {w}"
                if not m:
                    check(f"{name}: the notice is in the band", False)
                    p.close()
                    continue
                check(f"{name}: inside its band and the window, the page not scrolled sideways",
                      not m["out"] and m["band"][0] >= 0 and m["band"][2] <= m["W"] + .5 and m["side"] <= 0, m)
                check(f"{name}: {'one line' if w >= 414 else 'its link whole, on a line of its own if need be'}",
                      m["linkLines"] == 1 and (m["lines"] == 1 if w >= 414 else m["lines"] <= 2), m)
                check(f"{name}: its close key is 24 px or more", min(m["key"]) >= 24, m["key"])
                bg = h.background_of(br, p.page.screenshot(), m["words"])
                ratio = contrast(m["colour"], bg)
                check(f"{name}: its words read at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f} {m['colour']} on {bg}")
                check(f"{name}: the page threw nothing", not p.errors, p.errors[:2])
                p.close()


def group_motion(br, s):
    if not T.group("less motion"):
        return
    p = Page(br, s, [row(901, "essay", "문제", "답", "풀이")], w=1400, h=900, reduced=True)
    out = p.js("""() => { const bad = []; for (const e of document.querySelectorAll('body, body *')) { const c = getComputedStyle(e); if (c.transitionDuration.split(',').some((d) => parseFloat(d) > 0)) bad.push(e.tagName + '.' + e.className); } return bad.slice(0, 5); }""")
    check("asked for less motion, nothing runs a transition, however short", not out, out)
    p.close()


def group_ribbon(br, s):
    if not T.group("the ribbon"):
        return
    rows = [row(400 + i, "essay", f"문제 {i}", "답", "\n\n".join(f"문단 {j}" * 30 for j in range(10)), ago=900 - i) for i in range(5)]
    p = Page(br, s, rows, w=1600, h=900)
    style = """(sel) => { const e = document.querySelector(sel); if (!e) return null; const c = getComputedStyle(e, '::before'); return { o: +c.opacity, w: parseFloat(c.width), h: parseFloat(c.height), colour: c.backgroundColor, image: c.backgroundImage, clip: c.clipPath, filter: c.filter }; }"""
    on = p.js(style, '#history .h[aria-current="true"]')
    off = p.js(style, '#history .h[aria-current="false"]')
    margin = p.js("() => getComputedStyle(document.documentElement).getPropertyValue('--margin').trim()")
    check("the current row wears the ribbon", on and on["o"] == 1 and on["clip"].startswith("polygon") and on["w"] >= 8 and on["h"] >= 18, on)
    check("...flat: one colour, no sheen and no shadow (no 3D look)", on and on["image"] == "none" and on["filter"] == "none" and on["colour"] not in ("rgba(0, 0, 0, 0)", "transparent"), (on, margin))
    check("the others do not", off and off["o"] == 0, off)
    mark = p.js("() => getComputedStyle(document.querySelector('.card.history')).getPropertyValue('--h-mark').includes('M6.5 3h11v18')")
    check("the contents' mark is a ribbon", mark)
    check("rows keep room for it", p.js("() => parseFloat(getComputedStyle(document.querySelector('#history .h')).paddingLeft)") >= 20)
    # No ribbon in the thread: no bookmark mark on its answers. The contents keep theirs
    p.js("() => { const e = document.querySelector('.entry[data-id=\"402\"]'); window.scrollTo(0, e.offsetTop + 600 + e.closest('#thread').offsetTop); stick = false; }")
    p.wait(350)
    none = p.js("() => [...document.querySelectorAll('#thread .entry')].map((e) => getComputedStyle(e, '::before')).every((c) => c.content === 'none' || c.display === 'none')")
    check("no ribbon in the page", none)
    # Each answer a page: no red line across it, and the desk between one and the next
    pages = p.js("""() => { const all = [...document.querySelectorAll('#thread > .entry')], r = all.map((e) => e.getBoundingClientRect()), reds = [...document.querySelectorAll('.entry .ct')].filter((c) => getComputedStyle(c, '::before').content !== 'none' && getComputedStyle(c, '::before').height === '2px').length;
        const c = getComputedStyle(all[0]), holes = getComputedStyle(all[0], '::after');
        return { gaps: r.slice(1).map((x, i) => Math.round(x.top - r[i].bottom)), reds, sheet: getComputedStyle(document.getElementById('thread')).backgroundColor, ground: c.backgroundColor, rule: c.backgroundImage.startsWith('linear-gradient'), holes: holes.content, edge: c.borderBottomWidth }; }""")
    check("no red line across an answer", pages["reds"] == 0, pages)
    check("each answer is a page of its own, with the desk between it and the next", all(g >= 12 for g in pages["gaps"]) and pages["sheet"] == "rgba(0, 0, 0, 0)" and pages["edge"] != "0px", pages)
    check("...its own ground, its margin rule and its holes", pages["ground"] != "rgba(0, 0, 0, 0)" and pages["rule"] and pages["holes"] != "none", pages)
    # Hovering a row shows where it would go, and takes no room
    width = p.js("() => document.querySelector('#history .h[aria-current=\"false\"]').getBoundingClientRect().height")
    # brought into view first, and the drifting column left to settle: the pointer goes where the row then stands
    p.page.locator('#history .h[aria-current="false"]').first.scroll_into_view_if_needed()
    p.wait(200)
    p.page.locator('#history .h[aria-current="false"]').first.hover()
    p.wait(250)
    hov = p.js(style, '#history .h[aria-current="false"]:hover')
    check("under the pointer a row shows a grey one, where it would go", hov and hov["o"] == 1 and hov["colour"] != on["colour"], hov)
    check("...and does not change its height", p.js("() => document.querySelector('#history .h[aria-current=\"false\"]').getBoundingClientRect().height") == width)
    # A long list scrolled: its day's tab stands at the top, over the rows
    p.page.set_viewport_size({"width": 1600, "height": 780})
    p.wait(350)
    p.close()
    many = [row(500 + i, "essay", f"문제 {i}", "답", "풀이", ago=86400 * (i // 6) + i) for i in range(30)]
    p = Page(br, s, many, w=1600, h=1000)
    moved = p.js("() => { const l = $('history'); l.scrollTop = 150; return l.scrollTop; }")
    p.wait(120)
    tab = p.js("""() => { const l = $('history').getBoundingClientRect(), days = [...document.querySelectorAll('#history .h-day')], s = getComputedStyle(days[0]);
                          return { pos: s.position, top: Math.round(days.filter((d) => d.getBoundingClientRect().top <= l.top + 1).pop()?.getBoundingClientRect().top - l.top), solid: s.backgroundColor, scrolled: $('history').classList.contains('scrolled') }; }""")
    check("scrolled, a day's tab stays at the top of the list", moved > 0 and tab["pos"] == "sticky" and tab["top"] == 0, tab)
    check("...with a ground that hides the rows passing under it", tab["scrolled"] and tab["solid"] not in ("rgba(0, 0, 0, 0)", "transparent"), tab)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


# ---------------------------------------------------------------- an answer drawn from its words
SAMPLES = [
    "1. **첫째**: 설명\n2. **둘째**: 설명\n3. 이름 없는 단계\n",
    "- **GET** (정답): 조회만 합니다\n- **POST** (오답): 새로 만듭니다\n",
    "- **장점**: 빠릅니다\n- **단점**: 메모리를 씁니다\n",
    "- **정렬**을 먼저 하면 빠릅니다\n- **해시**로 찾으면 더 빠릅니다\n",
    "- 그냥 목록\n- **이름**: 설명\n",
    "명시적 Deny -> Allow -> 기본 Deny\n\n평가 순서는 **명시적 Deny → Allow → 기본 Deny**입니다.\n",
    "SYN → SYN-ACK → ACK의 순서로 맺습니다.\n",
    "- 80% → 21ns, 90% → 11ns, 95% → 6ns\n",
    "```\nA -> B -> C\n```\n\n`A -> B -> C` 는 코드입니다.\n",
    "| 항목 | 빠름 | 느림 |\n|---|---|---|\n| 지연 | 1 ms | 90 ms |\n| 비용 | 3 | 7 |\n| 안정 | 맞음 | 틀림 |\n",
    "## 하나\n\n글\n\n## 둘\n\n글\n\n## 셋\n\n글\n\n## 넷\n\n글\n",
    "## (1) 물음\n\n요지: 답\n\n설명: 풀이\n\n## (2) 물음\n\n요지: 답\n",
    "> 인용한 말\n\n주의: 함정이 있습니다\n",
    "1. **겉**\n   - 안쪽 항목\n   - **안쪽 이름**: 설명\n2. **겉 둘**\n   1. 안쪽 번호\n   2. 안쪽 번호\n",
    "1. 첫째\n\n   둘째 문단\n\n2. **느슨한 목록**: 설명\n\n   덧붙인 문단\n",
    "- **코드가 든 이름 `x`**: 설명 `y`\n- **수식 $x^2$**: 설명 $y$\n",
    "시간 복잡도: $O(N \\log N)$, 공간 복잡도: $O(N)$\n",
]


def group_drawn(br, s):
    if not T.group("an answer drawn from its words"):
        return
    p = Page(br, s, [], w=1600, h=1000)
    chain = lambda t: p.js("(t) => vChain(t)", t)   # noqa: E731
    for text, links in (("A → B → C", ["A", "B", "C"]), ("A -> B -> C -> D", ["A", "B", "C", "D"]), ("가 ⇒ 나 => 다", ["가", "나", "다"]), ("A → B", None), ("80% → 21ns, 90% → 11ns, 95% → 6ns", None),
                        (" → ".join("abcdefghij"), None), ("→ → →", None), ("긴 " * 30 + "→ B → C", None), ("", None)):
        check(f"a chain? {text[:28]!r}", chain(text) == links, chain(text))
    cost = lambda t: p.js("(t) => vBigOClass(t)", t)   # noqa: E731
    for text, at in (("1", 0), ("log N", 1), ("\\log n", 1), ("log(n)", 1), ("sqrt(N)", 1.5), ("\\sqrt{n}", 1.5), ("N", 2), ("n", 2), ("N+M", 2), ("V + E", 2), ("2N", 2), ("N/2", 2), ("N log N", 3), ("n\\log n", 3), ("n log(n)", 3), ("(N+M) log N", 3), ("E log V", 3),
                     ("N^2", 4), ("n^{2}", 4), ("N²", 4), ("N*M", 4), ("NM", 4), ("N \\cdot M", 4), ("N^3", 5), ("n³", 5), ("2^N", 6), ("2^{n}", 6), ("N!", 6), ("K^N", 6), ("<b>", None), ("", None), ("무언가", None)):
        check(f"where O({text}) stands", cost(text) == at, cost(text))
    said = lambda a, w: p.js("([a, w]) => vBigOPick(a, a, w)", [a, w])   # noqa: E731
    check("the key line's figure is taken", said("시간 O(N log N), 공간 O(N)", "시간|time") == "N log N")
    check("in English too", said("O(n) time: Time complexity: O(n)", "시간|time") == "n")
    check("two different figures are not guessed between", p.js("() => vBigOPick('', '먼저 시간 O(N^2), 고치면 시간 O(N)', '시간|time')") is None)
    check("the same one twice is that one", p.js("() => vBigOPick('', '시간 O(N) ... 시간 O(N)', '시간|time')") == "N")
    # No word is lost, over every sample
    words = """(texts) => texts.map((t) => {
        const plain = (e) => e.textContent.replace(/[\\s:：\\-–—()→>=⇒]/g, "");
        const host = document.createElement('div'); host.style.cssText = 'position:absolute;left:-9999px;width:900px';
        const md = document.createElement('div'); md.className = 'md'; md.dataset.body = '1'; host.append(md); document.body.append(host);
        renderInto(md, t);
        textStyle(host);       // the table's bar comes here, with its word for what it is: not part of what is compared
        const before = plain(md);
        groupAnswers(host);
        vTerms(md); vStepLeads(md); vFlows(md); vNotes(md); vTables(md);
        const drawn = { terms: md.querySelectorAll('.v-terms').length, steps: md.querySelectorAll(':scope > ol, :scope > .qa > ol').length, flow: md.querySelectorAll('.v-flow').length, bars: md.querySelectorAll('.v-bar').length };
        md.querySelectorAll('.v-flow').forEach((f) => { if (!f.closest('.v-flow-line')) f.remove(); });
        const after = plain(md);
        host.remove();
        return { same: before === after, before, after, drawn };
    })"""
    got = p.js(words, SAMPLES)
    for text, r in zip(SAMPLES, got):
        check(f"no word lost: {text[:34]!r}", r["same"], f"{r['before'][:120]} / {r['after'][:120]}")
    expect = dict(zip(range(len(SAMPLES)), got))
    check("names and their words make cards", expect[1]["drawn"]["terms"] == 1 and expect[2]["drawn"]["terms"] == 1)
    check("bold that opens a sentence is no name", expect[3]["drawn"]["terms"] == 0)
    check("a list with a line that has no name stays a list", expect[4]["drawn"]["terms"] == 0)
    check("a chain in its own line and in bold are drawn", expect[5]["drawn"]["flow"] == 2, expect[5])
    check("a chain written with no spaces inside its links, its particle left out", expect[6]["drawn"]["flow"] == 1)
    check("figures paired by arrows are no chain", expect[7]["drawn"]["flow"] == 0)
    check("code is left alone", expect[8]["drawn"]["flow"] == 0)
    # Drawn through the real path, once, whatever is asked again
    p.answer(601, "algorithm", "물음", "두 포인터, 시간 O(N log N), 공간 O(1)", SAMPLES[0] + "\n## 하나\n\n글\n\n## 둘\n\n글\n\n## 셋\n\n" + SAMPLES[9] + "\n")
    p.wait(250)
    measure = """() => { const e = entryEl(601); return { scale: e.querySelectorAll('.v-bigo').length, pins: [...e.querySelectorAll('.v-pin')].map((x) => [x.className, x.textContent.trim()]), map: e.querySelectorAll('.v-map').length, seg: e.querySelectorAll('.v-seg').length }; }"""
    m = p.js(measure)
    check("an algorithm's answer gets its scale, with the figures it gave", m["scale"] == 1 and ["v-pin time", "시간 O(N log N)"] in m["pins"] and ["v-pin space", "공간 O(1)"] in m["pins"], m)
    check("three parts or more get their strip", m["map"] == 1 and m["seg"] >= 3, m)
    p.js("() => enhance(entryEl(601))")
    p.wait(120)
    check("drawn twice, nothing doubles", p.js(measure) == m, p.js(measure))
    p.js("() => { renderEntry(items.get(601)); }")
    p.wait(250)
    check("redrawn, it comes back the same", p.js(measure) == m, p.js(measure))
    before = p.js("() => window.scrollY")
    p.js("() => { const b = entryEl(601).querySelectorAll('.v-seg')[1]; b.click(); }")
    p.wait(200)
    check("a part of the strip goes to that part", p.js("""() => { const parts = entryEl(601).querySelectorAll('.md > .qa'), r = parts[1].getBoundingClientRect(); return Math.abs(r.top - (document.querySelector('header.bar').getBoundingClientRect().height + 8)) < 60; }""") or before != p.js("() => window.scrollY"))
    # Table marks
    t = p.js("""() => { const e = entryEl(601); const cells = [...e.querySelectorAll('.tablewrap table')].pop(); return { compare: cells.classList.contains('v-compare'), yes: e.querySelectorAll('td.v-yes').length, no: e.querySelectorAll('td.v-no').length, right: e.querySelectorAll('tr.v-right').length }; }""")
    check("a comparison's columns are told apart, its verdicts marked, and no row of it taken for the answer", t["compare"] and t["yes"] == 1 and t["no"] == 1 and t["right"] == 0, t)
    p.answer(602, "work", "", "표", "| 번호 | 지연 | 값 |\n|---|---|---|\n| 1 | 10 ms | -1 |\n| 2 | 20 ms | 2 |\n| 3 | 40 ms | 3 |\n| 4 | 80 ms | 4 |\n")
    p.wait(250)
    bars = p.js("""() => [...entryEl(602).querySelectorAll('tbody tr')].map((r) => [...r.cells].map((c) => c.style.getPropertyValue('--bar')))""")
    check("figures get bars by their share of the largest", [r[1] for r in bars] == ["0.125", "0.25", "0.5", "1"], bars)
    check("numbers that count the rows off get none, nor a column with a negative", all(r[0] == "" and r[2] == "" for r in bars), bars)
    # "Which is NOT correct?": the answer's row is marked, the true statements are not (each "맞음" was green, ④ was not)
    mcq = "| 보기 | 판단 | 이유 |\n|---|---|---|\n| ① | 맞음 | 가 |\n| ② | 맞음 | 나 |\n| ③ | 맞음 | 다 |\n| ④ | 틀림 | 라 |\n"
    p.answer(691, "mcq", "옳지 않은 것은?", "④", mcq)
    p.answer(692, "work", "", "표", mcq)
    p.wait(250)
    rows = p.js("""() => [691, 692].map((i) => [...entryEl(i).querySelectorAll('tbody tr')].map((r) => r.classList.contains('v-right')))""")
    check("a multiple-choice answer marks the row it names, not each one that says 맞음", rows[0] == [False, False, False, True], rows[0])
    check("...and the same table in an answer that names no choice marks none", rows[1] == [False] * 4, rows[1])
    # Only a table of the choices, and only an answer that names its choices: "4번" and a list of two mark theirs; the
    # answers to two questions mark none (row ① was marked in both tables), nor do a table of steps or of nodes (step 3
    # and node B were marked for ③ and ②). Each read as it comes, while it is the newest and drawn whole
    steps = "| 단계 | 상태 |\n|---|---|\n| 1 | 시작 |\n| 2 | 비교 |\n| 3 | 교환 |\n| 4 | 끝 |\n"
    nodes = "| 노드 | 차수 |\n|---|---|\n| A | 2 |\n| B | 3 |\n| C | 1 |\n| D | 2 |\n"
    marked = {}
    for i, asked, key, body in ((693, "옳지 않은 것은?", "4번", mcq), (694, "옳은 것을 모두 고르면?", "③, ④", mcq),
                                (695, "", "1) ③  2) ②", mcq + "\n" + mcq), (696, "", "③", steps), (697, "", "②", nodes)):
        p.answer(i, "mcq", asked, key, body)
        p.wait(250)
        marked[i] = p.js("(i) => [...entryEl(i).querySelectorAll('tbody tr')].map((r) => r.classList.contains('v-right'))", i)
    check("\"4번\" marks row ④, and \"③, ④\" marks both",
          marked[693] == [False, False, False, True] and marked[694] == [False, False, True, True], marked)
    check("...the answers to two questions mark no row, nor does a table of steps or of nodes",
          marked[695] == [False] * 8 and marked[696] == [False] * 4 and marked[697] == [False] * 4, marked)
    p.answer(603, "essay", "", "1) 첫째 답 2) 둘째 답", "## (1) 물음\n\n글\n\n## (2) 물음\n\n글\n")
    p.wait(250)
    tiles = p.js("() => [...entryEl(603).querySelectorAll('.ans-list > li.v-tile')].length")
    check("several answers in one key line are tiles that go to their parts", tiles == 2, tiles)
    p.answer(604, "work", "", "커넥션 풀 → 슬로우 쿼리 → 락", "풀이")
    p.wait(150)
    check("a key line that is all a chain is drawn under it", p.js("() => entryEl(604).querySelectorAll('.answer-text .v-flow > span').length") == 3)
    # A chain in bold in a list item that stands in its own paragraph (a list with blank lines between its items) is drawn
    # once and whole: the item read whole drew a second chain, cut where a link has a space ("Deny → Allow → 기본")
    p.answer(698, "work", "", "정책 확인", "1. **역할 확인**: 먼저 쓰는 역할을 봅니다.\n\n2. **버킷 정책 확인**: 평가 순서는 "
             "**명시적 Deny → Allow → 기본 Deny** 입니다.\n\n3. **엔드포인트 확인**: 그 정책도 봅니다.\n")
    p.wait(250)
    flows = p.js("() => [...entryEl(698).querySelectorAll('.md .v-flow')].map((f) => [...f.querySelectorAll(':scope > span')].map((x) => x.textContent.trim()))")
    check("a chain in a list item's own paragraph is drawn once, whole", flows == [["명시적 Deny", "Allow", "기본 Deny"]], flows)
    # Starting numbers
    p.answer(605, "work", "", "답", "3. 셋째부터\n4. 넷째\n")
    p.wait(150)
    check("a list that starts at 3 counts from 3", p.js("() => getComputedStyle(entryEl(605).querySelector('.md > ol')).counterReset").endswith(" 2"), p.js("() => getComputedStyle(entryEl(605).querySelector('.md > ol')).counterReset"))
    # While it is written the steps are a ladder already, by the stylesheet, and nothing else is drawn: the end of a stream does not rearrange the page more than it must
    p.answer(606, "work", "", "답", "1. **첫째**: 설명\n2. **둘째**: 설명\n\n- **이름**: 설명\n- **둘째 이름**: 설명\n", final=False)
    p.wait(250)
    live = p.js("""() => { const e = entryEl(606), ol = e.querySelector('.md > ol'); return { ladder: ol ? getComputedStyle(ol.children[0], '::before').content : '', cards: e.querySelectorAll('.v-terms').length }; }""")
    check("while it is written the steps are a ladder and no cards are drawn yet", live["ladder"] not in ("", "none") and live["cards"] == 0, live)
    check("the page threw nothing", not p.errors, p.errors[:3])
    p.close()
    # The bench's real answers, where they are at hand
    try:
        files = sorted(support.bench("out-depth").rglob("*.md"))
    except support.Missing:
        files = []
    if not files:
        print("skipped 1 group for want of data: the bench's answers (SIDENOTE_BENCH/out-depth)")
        return
    p = Page(br, s, [], w=1600, h=1000)
    texts = []
    for f in files:
        t = f.read_text(encoding="utf-8", errors="ignore")
        if len(t) >= 60:
            texts.append(re.sub(r"^(TYPE|ANSWER|ASKED|REGION):.*$", "", t, flags=re.M))
    res = []
    for i in range(0, len(texts), 60):
        res += p.js(words, texts[i:i + 60])
    lost = [(i, r["before"][:60], r["after"][:60]) for i, r in enumerate(res) if not r["same"]]
    check(f"over {len(res)} real answers no word is lost", not lost, lost[:3])
    has = sum(1 for r in res if any(r["drawn"].values()))
    check(f"and most of them come out drawn: {has} of {len(res)}", has / max(1, len(res)) >= .5, has)
    check("the page threw nothing over them", not p.errors, p.errors[:3])
    p.close()


# What Practice, the keyboard shortcuts and Export to Anki add, measured where each opens: inside the window, its words whole, no key over
# another, and its words readable on what they stand on
STUDY_MEASURE = """(sel) => {
  const W = innerWidth, H = innerHeight, out = { missing: [], outside: [], cut: [], over: [] };
  const box = document.querySelector(sel);
  if (!box || !box.getClientRects().length) { out.missing.push(sel); return out; }
  const b = box.getBoundingClientRect();
  if (b.left < -0.5 || b.right > W + 0.5 || b.top < -0.5 || b.bottom > H + 0.5) out.outside.push(`${sel} ${Math.round(b.left)},${Math.round(b.top)} ${Math.round(b.right)},${Math.round(b.bottom)}`);
  const keys = [...box.querySelectorAll('button, kbd, .hint-n, .lbl')].filter((e) => e.getClientRects().length);
  for (const e of keys) {
    const r = e.getBoundingClientRect();
    if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible') out.cut.push(e.textContent.trim());
    if (r.left < b.left - 0.5 || r.right > b.right + 0.5) out.outside.push(`${e.textContent.trim()} out of ${sel}`);
  }
  for (let i = 0; i < keys.length; i++) for (let j = i + 1; j < keys.length; j++) {
    const a = keys[i].getBoundingClientRect(), c = keys[j].getBoundingClientRect();
    if (keys[i].contains(keys[j]) || keys[j].contains(keys[i])) continue;
    if (Math.min(a.right, c.right) - Math.max(a.left, c.left) > 0.5 && Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top) > 0.5) out.over.push(`${keys[i].textContent.trim()} / ${keys[j].textContent.trim()}`);
  }
  return out;
}"""
STUDY_CARD = ("## 핵심\n\n첫 부분입니다.\n\n## 코드\n\n```python\nprint(1)\n```\n\n## 복잡도\n\n셋째 부분입니다.\n")


def group_study(br, s):
    """The gear menu with Practice and Keyboard shortcuts in it, an answer Practice keeps back, the keys' sheet and Export's menu."""
    if not T.group("practice, the keys' sheet and Export's menu at every width"):
        return
    rows = [row(980 + i, "essay", f"물음 {i}", "답", "풀이", ago=600 - i * 60) for i in range(3)]
    for theme in ("dark", "light"):
        for w, hh in ((360, 740), (390, 844), (768, 1024), (1001, 800), (1280, 720), (1440, 900), (1920, 1080), (2560, 1440)):
            p = Page(br, s, rows, w=w, h=hh, theme=theme, settle=300)
            name = f"{theme} {w}x{hh}"
            p.js("() => setPractice(true)")
            p.answer(990, "algorithm", "두 수의 합이 목표값이 되는 두 원소의 인덱스를 구하시오", "사전 한 번 훑기", STUDY_CARD)
            p.wait(250)
            p.js("() => { showHint(items.get(990)); stick = false; entryEl(990).scrollIntoView({ block: 'start' }); }")
            p.wait(250)
            seen = {"the answer kept back": p.js(STUDY_MEASURE, ".entry[data-id='990'] .row.practice")}
            p.js("() => document.getElementById('more').click()")
            p.wait(200)
            seen["the menu"] = p.js(STUDY_MEASURE, "#menu")
            p.js("() => document.getElementById('more').click()")
            p.js("() => openKeys()")
            p.wait(200)
            seen["the keys' sheet"] = p.js(STUDY_MEASURE, "#keys")
            rows_ok = p.js("() => [...document.querySelectorAll('#keys .set')].every((r) => { const l = r.querySelector('.lbl').getBoundingClientRect(), k = r.querySelector('kbd').getBoundingClientRect(); return l.right <= k.left + 0.5 && Math.abs((l.top + l.bottom) / 2 - (k.top + k.bottom) / 2) < 4; })")
            p.js("() => closeKeys()")
            p.js("() => { const k = document.getElementById('hist-export'); k.scrollIntoView({ block: 'nearest' }); k.click(); }")
            p.wait(200)
            seen["Export's menu"] = p.js(STUDY_MEASURE, "#export-menu")
            clear = p.js("() => { const m = document.getElementById('export-menu').getBoundingClientRect(), k = document.getElementById('hist-export').getBoundingClientRect(); return Math.min(m.right, k.right) - Math.max(m.left, k.left) <= 0 || Math.min(m.bottom, k.bottom) - Math.max(m.top, k.top) <= 0; }")
            for what, m in seen.items():
                check(f"{name}: {what} is drawn, inside the window, its words whole, no key over another", not any(m.values()), m)
            check(f"{name}: in the keys' sheet each key stands beside its words, on their line", rows_ok)
            check(f"{name}: Export's menu leaves its key in view", clear)
            check(f"{name}: the page does not scroll sideways", p.js("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0)
            check(f"{name}: the page threw nothing", not p.errors, p.errors[:2])
            p.close()
    # Their words read at 4.5:1 or better on what they stand on, in both themes
    words = {".row.practice .hint-n": "how many hints", ".row.practice .btn span": "a Practice key's word", "#keys .set .lbl": "what a key does",
             "#keys kbd.cmd": "a key", "#keys .set .help": "a key's note", "#export-menu .item": "an export choice", "#practice-seg button": "Practice's choice"}
    for theme in ("dark", "light"):
        p = Page(br, s, rows, w=1440, h=900, theme=theme, settle=300)
        p.js("() => setPractice(true)")
        p.answer(990, "algorithm", "물음", "답", STUDY_CARD)
        p.wait(250)
        p.js("() => { stick = false; entryEl(990).scrollIntoView({ block: 'start' }); }")
        p.wait(200)
        opens = {".row.practice": "() => {}", "#keys": "() => openKeys()", "#export-menu": "() => { closeKeys(); const k = document.getElementById('hist-export'); k.scrollIntoView({ block: 'nearest' }); k.click(); }",
                 "#practice-seg": "() => { exportMenu(false); document.getElementById('more').click(); }"}
        for scope, act in opens.items():
            p.js(act)
            p.wait(250)
            png = p.page.screenshot()
            for sel, what in words.items():
                if not sel.startswith(scope):
                    continue
                got = p.js("""(sel) => { const e = [...document.querySelectorAll(sel)].find((x) => x.getClientRects().length); if (!e) return null; const r = e.getBoundingClientRect();
                    return { box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)], colour: getComputedStyle(e).color.match(/[\\d.]+/g).map(Number) }; }""", sel)
                if got is None:
                    check(f"{theme}: {what} is there to read ({sel})", False)
                    continue
                ratio = contrast(got["colour"], h.background_of(br, png, got["box"]))
                check(f"{theme}: {what} reads at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f}")
        check(f"{theme}: the page threw nothing", not p.errors, p.errors[:2])
        p.close()


def group_skip(br, s):
    """Skip windows: its box of words in the settings sheet, and the screen card while a window to skip is in front, in both
    themes from 360 to 2560 px wide: inside the sheet and the card, every word in view, nothing cut, read at 4.5:1."""
    if not T.group("skip windows: the box of words and the screen card"):
        return
    msg = support.settings_message()
    words = msg["values"]["skip_windows"]
    for theme in ("dark", "light"):
        for w, hh in ((360, 740), (390, 844), (768, 1024), (1000, 800), (1280, 720), (1920, 1080), (2560, 1440)):
            name = f"{theme} {w}x{hh}"
            p = Page(br, s, [], w=w, h=hh, theme=theme, settle=300)
            p.send(msg)
            p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='screen']\").click(); }")
            p.wait(250)
            box = p.js("""() => { const b = document.querySelector('#settings textarea[data-set=skip_windows]'); if (!b) return null;
                b.scrollIntoView({ block: 'nearest' });
                const r = b.getBoundingClientRect(), sheet = document.getElementById('settings').getBoundingClientRect(),
                      pane = document.querySelector('#settings .set-pane').getBoundingClientRect(), row = b.closest('.set').getBoundingClientRect();
                return { inside: r.left >= pane.left - .5 && r.right <= pane.right + .5 && r.left >= sheet.left && r.right <= sheet.right,
                         row: r.left >= row.left - .5 && r.right <= row.right + .5, all: b.scrollHeight <= b.clientHeight + 1, value: b.value,
                         side: document.documentElement.scrollWidth - document.documentElement.clientWidth, h: Math.round(r.height),
                         box: [Math.floor(r.left + 12), Math.floor(r.top + 6), Math.ceil(r.right - 12), Math.ceil(r.bottom - 6)],
                         ink: getComputedStyle(b).color.match(/[\\d.]+/g).map(Number) }; }""")
            if box is None:
                check(f"{name}: the box of words is there", False)
                p.close()
                continue
            check(f"{name}: the box of words stands inside the sheet, its pane and its row", box["inside"] and box["row"], box)
            check(f"{name}: ...with every word of the default list in view, none scrolled away inside it",
                  box["all"] and box["value"] == ", ".join(words), box)
            check(f"{name}: ...and the page does not scroll sideways", box["side"] <= 0, box["side"])
            ratio = contrast(box["ink"], h.background_of(br, p.page.screenshot(), box["box"]))
            check(f"{name}: ...its words read at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f}")
            # The screen card while a window to skip is in front
            p.js("() => closeSettings()")
            p.send({**h.CAPTURE, "now": p.js("() => Date.now() / 1000"), "last_frame": p.js("() => Date.now() / 1000") - 8,
                    "caps": {**h.CAPTURE["caps"], "skipping": True}})
            p.wait(250)
            pill = p.js("""() => { const e = document.getElementById('pill-screen'); e.scrollIntoView({ block: 'center' });
                const r = e.getBoundingClientRect(), card = e.closest('.card').getBoundingClientRect();
                return { text: e.textContent, state: e.dataset.state, cut: e.scrollWidth > e.clientWidth + 1, inside: r.left >= card.left && r.right <= card.right,
                         box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)], ink: getComputedStyle(e).color.match(/[\\d.]+/g).map(Number),
                         note: document.querySelector('#st-screen .src-note')?.textContent || '', signal: document.getElementById('sig-screen').dataset.state }; }""")
            p.wait(150)
            check(f"{name}: the screen card says 'Skipped window' in the warn tone, the top bar's signal too",
                  pill["text"] == "창 건너뜀" and pill["state"] == "warn" and pill["signal"] == "warn", pill)
            check(f"{name}: ...whole, inside its card", not pill["cut"] and pill["inside"], pill)
            ratio = contrast(pill["ink"], h.background_of(br, p.page.screenshot(), pill["box"]))
            check(f"{name}: ...read at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f} {pill}")
            if w == 1920:
                check(f"{theme}: the card's note says nothing is sent and where the words are, without naming a window",
                      pill["note"] == "화면에 보이는 동안 화면을 보내지 않음 · 풀이 설정의 '건너뛸 창'", pill["note"])
            check(f"{name}: the page threw nothing", not p.errors, p.errors[:2])
            p.close()
    # The card's other states come first: the screen switched off, and no capture program, say so over a skip
    p = Page(br, s, [], w=1920, h=1080, settle=300)
    now = p.js("() => Date.now() / 1000")
    got = []
    for more in ({"screen_on": False}, {"clients": 0}, {}):
        p.send({**h.CAPTURE, "now": now, "caps": {**h.CAPTURE["caps"], "skipping": True}, **more})
        p.wait(120)
        got.append(p.js("() => [document.getElementById('pill-screen').textContent, document.getElementById('pill-screen').dataset.state]"))
    check("the screen switched off and no capture program are said over a skip; the skip otherwise",
          got == [["꺼 둠", "off"], ["프로그램 연결 안 됨", "idle"], ["창 건너뜀", "warn"]], got)
    p.send({**h.CAPTURE, "now": now, "caps": {**h.CAPTURE["caps"], "skipping": False}})
    p.wait(120)
    check("...and once the window is gone the card is receiving again", p.js("() => document.getElementById('pill-screen').textContent") == "받는 중")
    # Where the windows cannot be read the list is not doing all it says: said in the same caution, screens still going out
    got = []
    for limit in ("none", "front", ""):
        p.send({**h.CAPTURE, "now": now, "last_frame": now - 8, "caps": {**h.CAPTURE["caps"], "skip_limit": limit}})
        p.wait(120)
        got.append(p.js("""() => { const e = document.getElementById('pill-screen'), n = document.querySelector('#st-screen .src-note');
            return [e.textContent, e.dataset.state, e.scrollWidth <= e.clientWidth + 1, n ? n.textContent : '']; }"""))
    check("no way to read the windows: the card warns, whole, and says what to do",
          got[0] == ["창 못 건너뜀", "warn", True, "이 데스크톱은 열린 창을 알려 주지 않음 · 비공개 창을 띄울 때는 화면 끄기"], got[0])
    check("only the window in front to go by: the same caution, told apart",
          got[1] == ["맨 앞 창만", "warn", True, "이 데스크톱은 맨 앞 창 뒤의 창을 알려 주지 않음 · 비공개 창을 띄울 때는 화면 끄기"], got[1])
    check("...and with nothing to say the card is receiving", got[2][:2] == ["받는 중", "ok"] or got[2][0] == "받는 중", got[2])
    p.send({**h.CAPTURE, "now": now, "caps": {**h.CAPTURE["caps"], "skip_limit": "none", "skipping": True}})
    p.wait(120)
    check("a skip going on is said over it: nothing is going out then", p.js("() => document.getElementById('pill-screen').textContent") == "창 건너뜀")
    p.close()
    # In English, as the other pages are given it: the same words, and no Korean
    p = Page(br, s, [], w=1920, h=1080, settle=300, locale="en-US")
    p.send({**h.CAPTURE, "now": now, "caps": {**h.CAPTURE["caps"], "skipping": True}})
    p.wait(150)
    en = p.js("() => [document.getElementById('pill-screen').textContent, document.querySelector('#st-screen .src-note')?.textContent]")
    p.send({**h.CAPTURE, "now": now, "caps": {**h.CAPTURE["caps"], "skip_limit": "none"}})
    p.wait(150)
    limit_en = p.js("() => [document.getElementById('pill-screen').textContent, document.querySelector('#st-screen .src-note')?.textContent]")
    check("...and where the windows cannot be read, in English too", limit_en == ["Windows not skipped", "This desktop does not say which windows are open · Turn the screen off while a private window shows"], limit_en)
    check("in English the card reads 'Skipped window', and where the words are", en == ["Skipped window", "No screen is sent while it shows · Skip windows in Solver settings"], en)
    p.close()


HEARD_KEPT = {"days": [{"day": "2026-11-04", "n": 30, "first": 1793800000, "last": 1793803000}, {"day": "2026-11-03", "n": 2, "first": 1793700000, "last": 1793700100}], "day": "2026-11-04",
              "lines": [{"ts": 1793800000 + i * 75, "secs": 3.0, "lang": "ko", "text": t} for i, t in enumerate(
                  ["So we drained the node first and waited for the pods to move to the other two workers.", "커널을 올리고 다시 부팅한 다음에 노드를 돌려놓았습니다.", "GTID가 뭔가요?"] * 10)]}


def group_heard(br, s):
    """What the spoken side adds, in both themes from 360 to 2560 px wide: the note under a sentence and the key on What is heard,
    the sheet of what was kept, and Extra terms and the speech model in the Speech section."""
    if not T.group("what is heard: the note, the key, the sheet and the Speech section"):
        return
    s.heard = HEARD_KEPT
    msg = support.settings_message()
    msg["values"]["speech_keep"] = True
    for theme in ("dark", "light"):
        for w, hh in ((360, 740), (390, 844), (768, 1024), (1000, 800), (1280, 720), (1920, 1080), (2560, 1440)):
            name = f"{theme} {w}x{hh}"
            p = Page(br, s, [], w=w, h=hh, theme=theme, settle=300)
            p.send(msg)
            p.send({"type": "transcript", "text": "노드를 먼저 비웠습니다. GTID가 뭐?", "lang": "ko"})
            p.send({"type": "utterance", "text": "GTID가 뭐?", "lang": "ko", "why": "short"})
            p.wait(200)
            card = p.js("""() => { const c = document.getElementById('hear'); c.scrollIntoView({ block: 'center' });
                const r = c.getBoundingClientRect(), k = document.getElementById('hear-kept').getBoundingClientRect(), st = document.getElementById('hear-state').getBoundingClientRect(),
                      b = document.getElementById('hear-text'), n = b.querySelector('.why'), nb = n?.getBoundingClientRect(), tb = b.getBoundingClientRect();
                const inside = (x, o) => x.left >= o.left - .5 && x.right <= o.right + .5;
                return { key: inside(k, r) && k.width >= 24 && k.height >= 24, beside: st.right <= k.left + .5 || st.bottom <= k.top + .5, note: !!n && inside(nb, tb) && nb.bottom <= tb.bottom + 1 && nb.top >= tb.top - 1,
                         noteBox: nb ? [Math.floor(nb.left), Math.floor(nb.top), Math.ceil(nb.right), Math.ceil(nb.bottom)] : [0, 0, 1, 1], ink: n ? getComputedStyle(n).color.match(/[\\d.]+/g).map(Number) : [0, 0, 0],
                         side: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }""")
            p.wait(150)
            check(f"{name}: the key to what is kept stands inside the card, beside the card's state, large enough to press", card["key"] and card["beside"], card)
            check(f"{name}: the note under a sentence is in view inside the card's words", card["note"], card)
            ratio = contrast(card["ink"], h.background_of(br, p.page.screenshot(), card["noteBox"]))
            check(f"{name}: ...and reads at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f}")
            p.js("() => openHeard()")
            p.wait(300)
            m = p.js(STUDY_MEASURE, "#heard")
            check(f"{name}: the sheet is drawn, inside the window, its words whole, no key over another", not any(m.values()), m)
            rows = p.js("""() => { const out = { n: 0, off: [], cut: [], scroll: 0 }; const list = document.getElementById('heard-lines'), lb = list.getBoundingClientRect();
                out.scroll = list.scrollHeight > list.clientHeight ? 1 : 0;
                for (const l of [...list.children].slice(0, 12)) { const t = l.querySelector('time').getBoundingClientRect(), w = l.querySelector('span').getBoundingClientRect(); out.n++;
                  if (t.right > w.left + .5 || Math.abs(t.left - lb.left) > 1) out.off.push(l.textContent.slice(0, 20));
                  if (w.right > lb.right + .5 || l.scrollWidth > l.clientWidth + 1) out.cut.push(l.textContent.slice(0, 20)); }
                return out; }""")
            check(f"{name}: a row's time stands beside its words, on one edge, nothing past the sheet", rows["n"] == 12 and not rows["off"] and not rows["cut"], rows)
            words = p.js("""() => { const pick = (sel) => { const e = document.querySelector(sel), r = e.getBoundingClientRect(); return { box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)], ink: getComputedStyle(e).color.match(/[\\d.]+/g).map(Number) }; };
                return { '#heard .lede': pick('#heard .lede'), '.heard-line time': pick('.heard-line time'), '.heard-line span': pick('.heard-line span'), '#heard-copy span': pick('#heard-copy span') }; }""")
            png = p.page.screenshot()
            for sel, got in words.items():
                ratio = contrast(got["ink"], h.background_of(br, png, got["box"]))
                check(f"{name}: {sel} reads at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f}")
            check(f"{name}: the page does not scroll sideways under it", p.js("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0)
            p.js("() => closeHeard()")
            p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='speech']\").click(); }")
            p.wait(250)
            box = p.js("""() => { const b = document.querySelector('#settings textarea[data-set=speech_terms]'); if (!b) return null; b.scrollIntoView({ block: 'nearest' });
                const r = b.getBoundingClientRect(), pane = document.querySelector('#settings .set-pane').getBoundingClientRect(), keys = [...document.querySelectorAll('#settings button[data-set=whisper_model]')].map((x) => x.getBoundingClientRect());
                return { inside: r.left >= pane.left - .5 && r.right <= pane.right + .5, keys: keys.length === 3 && keys.every((k) => k.left >= pane.left - .5 && k.right <= pane.right + .5), side: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }""")
            check(f"{name}: Extra terms and the speech model stand inside the sheet", box and box["inside"] and box["keys"] and box["side"] <= 0, box)
            check(f"{name}: the page threw nothing", not p.errors, p.errors[:2])
            p.close()
    s.heard = {"days": [], "day": "", "lines": []}


def group_shots(br, s):
    """The screens to look at, kept with the run: what no measure says, a person can see from CI's artifact without checking the commit out."""
    if not T.group("screens to look at"):
        return
    drawn = ("## 핵심 아이디어\n\n- **시간 O(N)**: 원소마다 한 번 봅니다\n- **공간 O(1)**: 값 두 개만 듭니다\n\n## 순서\n\n1. **입력을 읽습니다**: 줄 단위로 읽습니다\n2. **두 상태를 갱신합니다**: 동시에 대입합니다\n"
             "3. **답을 냅니다**: 마지막 값입니다\n\n요청 -> 캐시 확인 -> 응답\n\n## 비교\n\n| 항목 | 해시 | 정렬 |\n|---|---|---|\n| 시간 | 12 ms | 90 ms |\n| 메모리 | 40 MB | 8 MB |\n| 안정성 | 맞음 | 틀림 |\n")
    rows = [row(700 + i, "algorithm", f"문제 {i}: 버섯을 번호 순서대로 골라 먹을 때의 최댓값", "두 상태 DP, 시간 O(N), 공간 O(1)", drawn, ago=4000 - i * 300, thumb=h.thumb(960, 540), region=[.2, .2, .6, .8]) for i in range(5)]
    for theme in ("dark", "light"):
        for w, hh in ((1920, 1040), (1440, 900)):
            p = Page(br, s, rows, w=w, h=hh, theme=theme, settle=900)
            p.js("() => window.scrollTo(0, 0)")
            p.wait(300)
            path = p.shot(f"design_{theme}_{w}x{hh}")
            check(f"{theme} {w}x{hh}: a screen kept for looking at", path.stat().st_size > 20000, path.stat().st_size)
            p.close()


def group_place(br, s):
    """An answer that ends while it is read above its end: its scale, its strip of parts and its boxed sections come in above
    the words read, and moved them down by 144 px at once (172 on a narrow window)."""
    if not T.group("the place read, kept as an answer ends"):
        return
    text = (Path(__file__).resolve().parent / "data" / "answers" / "code_prog_peak.md").read_text(encoding="utf-8")
    words = "회의마다 시작 시각에"
    find = """(s) => { const tw = document.createTreeWalker(document.getElementById('thread'), NodeFilter.SHOW_TEXT);
      for (let n = tw.nextNode(); n; n = tw.nextNode()) if (n.nodeValue.includes(s)) {
        const r = document.createRange(); r.selectNodeContents(n); return Math.round(r.getBoundingClientRect().top); }
      return null; }"""
    for w in (1280, 700):
        p = Page(br, s, [row(980 + i, "essay", f"문제 {i}", "답", "풀이", ago=100 - i) for i in range(3)], w=w, h=900)
        p.send({"type": "analysis_start", "id": 990, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "",
                "pages": 0, "trigger": "screen", "roi": None})
        cut = int(len(text) * .8)
        for c in range(0, cut, 30):        # written as it comes, followed at its end
            p.send({"type": "delta", "id": 990, "text": text[c:min(c + 30, cut)]})
            p.wait(15)
        p.wait(300)
        p.page.mouse.move(w // 3, 400)     # then read further up, by hand
        p.page.mouse.wheel(0, p.js(find, words) - 300)
        p.wait(500)
        for c in range(cut, len(text), 30):
            p.send({"type": "delta", "id": 990, "text": text[c:c + 30]})
            p.wait(15)
        p.wait(300)
        before = p.js(find, words)
        p.done(990, text)
        p.wait(1200)
        after = p.js(find, words)
        check(f"{w}: the words read stay where they are as the answer ends ({before} -> {after} px)",
              before is not None and after is not None and 200 <= before <= 400 and abs(after - before) <= 4, (before, after))
        p.close()


def main() -> int:
    support.need_vendor(h.PANEL)
    group_stylesheet()
    s = Stand("design")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_material, group_motion, group_ribbon, group_engines, group_drawn, group_readable, group_skip, group_heard, group_release, group_matrix, group_study, group_place, group_shots):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
