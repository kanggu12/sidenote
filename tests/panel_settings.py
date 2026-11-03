"""The settings sheet: what its controls look like, and whether the dropdowns belong to the panel.

    .venv-panel/bin/python tests/panel_settings.py [--shots]

Seeds the real settings message (written straight out of server/settings.py into the output folder,
so the fixture is the server's own output: tests/support.py), opens the sheet, and reports every
control in it: what kind it is, its box, and the colours it is actually drawn with. A native
`<select>` is drawn by the operating system, so it ignores the panel's own surfaces and opens a list
in the system's font: this is what says whether any are left.

With --shots it also writes settings-*.png into shots/ of the output folder (SIDENOTE_TEST_OUT).
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the output folder, the settings message, a fresh copy of the panel

HERE = Path(__file__).resolve().parent     # tests/
ROOT = HERE.parent                         # the repository
STATIC = support.out("panelstatic")        # the copy of panel/ that is served
OUT = support.out("shots")                 # the screenshots, with --shots
SHOTS = "--shots" in sys.argv
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(': ' + detail) if detail else ''}")


def main():
    from playwright.sync_api import sync_playwright
    msg = support.settings_message()           # written by the server's own code, in the server's interpreter (PY)
    OUT.mkdir(parents=True, exist_ok=True)
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1500, "height": 950}, locale=support.LOCALE)
        # The panel keeps trying to reconnect, and every failure redraws the sheet, which would pull
        # an open dropdown out from under the click this is about. A socket that never finishes
        # connecting leaves the page alone without pretending anything is connected.
        pg.add_init_script("window.WebSocket = function () { this.close = function () {}; "
                           "this.send = function () {}; this.readyState = 0; };")
        pg.goto(url)
        pg.wait_for_timeout(400)
        # the controls are disabled while there is no live connection, and a disabled control says
        # nothing about how it looks when it can be used: tell the page the socket is up, the way
        # the real one does, before the sheet is drawn
        pg.evaluate("() => { wsState = 'up'; }")
        pg.evaluate("(m) => window.handle(m)", msg)
        pg.evaluate("() => document.getElementById('open-settings').click()")
        pg.wait_for_timeout(500)

        # every section, not only the one the sheet opens on: the dropdowns are spread across them
        secs = pg.evaluate("""() => [...document.querySelectorAll('#settings .set-tab')].map(t => t.dataset.sec)""")
        seen = []
        for sec in secs:
            pg.evaluate("(s) => document.querySelector(`#settings [data-sec=\"${s}\"]`).click()", sec)
            pg.wait_for_timeout(120)
            seen += [dict(r, sec=sec) for r in pg.evaluate("""() => [...document.querySelectorAll('#settings select, #settings .combo')]
                .map(e => ({tag: e.tagName.toLowerCase(), key: e.dataset.combo || e.dataset.set || '',
                            n: e.querySelectorAll('li, option').length}))""")]
        print("  dropdowns across the sheet:")
        for r in seen:
            print(f"     {r['sec']:<9} {r['key']:<20} {r['tag']:<7} {r['n']} rows")
        check("none of them is a native dropdown", not [r for r in seen if r["tag"] == "select"],
              ", ".join(r["key"] for r in seen if r["tag"] == "select"))
        # back to the section the sheet opens on, and to the one with the longest list for the shot
        longest = max(seen, key=lambda r: r["n"]) if seen else None
        pg.evaluate("(s) => document.querySelector(`#settings [data-sec=\"${s}\"]`).click()",
                    longest["sec"] if longest else secs[0])
        pg.wait_for_timeout(150)

        rows = pg.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('#settings select, #settings .seg, #settings input, #settings .combo')) {
              const r = el.getBoundingClientRect();
              const cs = getComputedStyle(el);
              out.push({tag: el.tagName.toLowerCase(), cls: el.className?.toString?.().slice(0, 24) || '',
                        key: el.dataset?.set || el.closest('.set-row')?.querySelector('[data-set]')?.dataset?.set || '',
                        w: Math.round(r.width), h: Math.round(r.height),
                        bg: cs.backgroundColor, color: cs.color, border: cs.borderTopWidth + ' ' + cs.borderTopColor,
                        radius: cs.borderTopLeftRadius, font: cs.fontFamily.split(',')[0]});
            }
            return out;
        }""")
        kinds = {}
        for r in rows:
            kinds[r["tag"]] = kinds.get(r["tag"], 0) + 1
        print("  controls in the sheet:", ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items())))
        for r in rows:
            if r["tag"] == "select" or "combo" in r["cls"]:
                print(f"     {r['key']:<20} {r['tag']}.{r['cls']:<10} {r['w']}x{r['h']}  bg {r['bg']}  "
                      f"radius {r['radius']}  font {r['font']}")
        check("no control in the sheet is a native dropdown",
              not [r for r in rows if r["tag"] == "select"],
              f"{len([r for r in rows if r['tag'] == 'select'])} left")

        print("\n[the dropdown opens, moves and picks without a mouse]")
        key = longest["key"] if longest else None
        sel = f"#settings [data-combo='{key}'] .combo-btn"
        aria = pg.evaluate("""(s) => { const b = document.querySelector(s);
            return {role: b.getAttribute('role'), pop: b.getAttribute('aria-haspopup'),
                    controls: b.getAttribute('aria-controls'), exp: b.getAttribute('aria-expanded'),
                    list: document.getElementById(b.getAttribute('aria-controls'))?.getAttribute('role')}; }""", sel)
        check("it says what it is", aria["role"] == "combobox" and aria["pop"] == "listbox"
              and aria["list"] == "listbox", json.dumps(aria, ensure_ascii=False))
        pg.focus(sel)
        pg.keyboard.press("ArrowDown")
        pg.wait_for_timeout(120)
        st = pg.evaluate("""(s) => { const b = document.querySelector(s);
            const l = document.getElementById(b.getAttribute('aria-controls'));
            const on = l.querySelector('li.on');
            return {exp: b.getAttribute('aria-expanded'), hidden: l.hidden,
                    active: b.getAttribute('aria-activedescendant'), onId: on && on.id,
                    onSelected: on && on.getAttribute('aria-selected')}; }""", sel)
        check("a down arrow opens it on the choice it is already on",
              st["exp"] == "true" and not st["hidden"] and st["onSelected"] == "true", json.dumps(st))
        check("and says which row the keyboard is on", st["active"] and st["active"] == st["onId"],
              json.dumps(st))
        pg.keyboard.press("ArrowDown")
        pg.wait_for_timeout(80)
        moved = pg.evaluate("""(s) => { const b = document.querySelector(s);
            const l = document.getElementById(b.getAttribute('aria-controls'));
            return [...l.querySelectorAll('li')].findIndex(o => o.classList.contains('on')); }""", sel)
        check("a second one moves down the list", moved == 1, str(moved))
        # what it would send, caught before it goes anywhere: there is no server behind this
        pg.evaluate("() => { window.__picked = null; window.__setSetting = setSetting; "
                    "setSetting = (k, v) => { window.__picked = [k, v]; }; }")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(120)
        picked = pg.evaluate("() => window.__picked")
        after = pg.evaluate("(s) => document.querySelector(s).getAttribute('aria-expanded')", sel)
        check("enter picks the row it is on and shuts the list",
              picked and picked[0] == key and after == "false", json.dumps(picked, ensure_ascii=False))
        focus = pg.evaluate("(s) => document.activeElement === document.querySelector(s)", sel)
        check("and the keyboard goes back to the control", focus)
        pg.evaluate("() => { setSetting = window.__setSetting; }")
        pg.keyboard.press("ArrowDown")
        pg.wait_for_timeout(100)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        esc = pg.evaluate("(s) => ({exp: document.querySelector(s).getAttribute('aria-expanded'), "
                          "sheet: !document.getElementById('settings-overlay').hidden})", sel)
        check("escape shuts the list and leaves the sheet open",
              esc["exp"] == "false" and esc["sheet"], json.dumps(esc))
        # a redraw while one is open must never leave the page holding a node that is no longer in it
        pg.evaluate("(s) => document.querySelector(s).click()", sel)
        pg.wait_for_timeout(80)
        pg.evaluate("() => renderSettings()")
        pg.wait_for_timeout(80)
        redraw = pg.evaluate("""() => {
            if (!comboOpen) return {open: false, live: true, same: true};
            return {open: true,
                    // both ends of it have to still be part of the page
                    live: document.contains(comboOpen.btn) && document.contains(comboOpen.list),
                    same: comboOpen.btn === document.querySelector('#settings .combo-btn[aria-expanded=\"true\"]')}; }""")
        check("nothing is left pointing at a row the redraw threw away",
              redraw["live"] and redraw["same"], json.dumps(redraw))
        pg.evaluate("() => comboClose(false)")

        print("\n[a list near the bottom of a scrolling pane is not cut off]")
        # the settings pane scrolls, and a scroller clips what sticks out of it: a dropdown low in
        # the pane is exactly where that would show
        low = pg.evaluate("""() => {
            const pane = document.querySelector('#settings .set-pane');
            const combos = [...document.querySelectorAll('#settings .combo-btn:not([disabled])')];
            if (!pane || !combos.length) return null;
            // straight to the bottom, not scrollIntoView: a smooth scroll lands after the click
            // below and the page closes any open list when the pane moves
            pane.scrollTop = pane.scrollHeight;
            const last = combos[combos.length - 1];
            return {key: last.closest('.combo').dataset.combo}; }""")
        print(f"     the lowest usable dropdown in the pane: {low}")
        if low:
            pg.wait_for_timeout(350)
            pg.evaluate("""() => { const c = [...document.querySelectorAll('#settings .combo-btn:not([disabled])')];
                c[c.length - 1].click(); }""")
            pg.wait_for_timeout(200)
            cut = pg.evaluate("""() => {
                const l = document.querySelector('.combo-list:not([hidden])');
                if (!l) return {open: false};
                const pane = document.querySelector('#settings .set-pane');
                const r = l.getBoundingClientRect(), p = pane.getBoundingClientRect();
                // what the pane actually lets through, and what the window does
                return {open: true, listTop: Math.round(r.top), listBottom: Math.round(r.bottom),
                        paneTop: Math.round(p.top), paneBottom: Math.round(p.bottom),
                        win: window.innerHeight,
                        cutByPane: Math.round(Math.max(0, r.bottom - p.bottom) + Math.max(0, p.top - r.top)),
                        cutByWindow: Math.round(Math.max(0, r.bottom - window.innerHeight) + Math.max(0, -r.top)),
                        up: l.classList.contains('up')}; }""")
            print("     " + json.dumps(cut, ensure_ascii=False))
            check("the pane does not cut it", cut.get("open") and cut.get("cutByPane") == 0,
                  f"{cut.get('cutByPane')} px outside the pane")
            check("nor does the window", cut.get("open") and cut.get("cutByWindow") == 0,
                  f"{cut.get('cutByWindow')} px outside the window")
            # escape closes the list wherever the keyboard is, and leaves the sheet open
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(120)
            still = pg.evaluate("""() => ({list: !!document.querySelector('.combo-list:not([hidden])'),
                sheet: !document.getElementById('settings-overlay').hidden})""")
            check("escape there closes the list, not the sheet",
                  not still["list"] and still["sheet"], json.dumps(still))

        print("\n[the panel's own scrolling does not shut the list]")
        # the panel scrolls itself while it works: it follows a streaming answer, keeps the heard
        # words on their last line, brings a new screenshot into view. None of that moves the sheet.
        own = pg.evaluate("""() => {
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            if (!b) return null;
            b.click();
            const before = !!document.querySelector('.combo-list:not([hidden])');
            window.scrollTo(0, 0);                                   // the page behind the sheet
            const hear = document.getElementById('hear-text');
            if (hear) { hear.scrollTop = hear.scrollHeight; hear.dispatchEvent(new Event('scroll', {bubbles: true})); }
            dispatchEvent(new Event('scroll'));
            return {before, after: !!document.querySelector('.combo-list:not([hidden])')}; }""")
        pg.wait_for_timeout(150)
        still = pg.evaluate("() => !!document.querySelector('.combo-list:not([hidden])')")
        print(f"     {json.dumps(own, ensure_ascii=False)} still open: {still}")
        check("a scroll that does not move the control leaves the list alone",
              bool(own and own["before"] and own["after"] and still), json.dumps(own, ensure_ascii=False))
        # and one that does move it still closes it. A short window, so the pane has to scroll at all.
        pg.set_viewport_size({"width": 1500, "height": 560})
        pg.wait_for_timeout(250)
        moved_shut = pg.evaluate("""() => {
            comboClose(false);
            const pane = document.querySelector('#settings .set-pane');
            if (!pane) return {no: 'pane'};
            pane.scrollTop = 0;
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            b.click();
            if (!document.querySelector('.combo-list:not([hidden])')) return {no: 'open'};
            const before = b.getBoundingClientRect().top;
            pane.scrollTop = Math.min(80, pane.scrollHeight - pane.clientHeight);
            pane.dispatchEvent(new Event('scroll', {bubbles: true}));
            const after = b.getBoundingClientRect().top;
            return {room: Math.round(pane.scrollHeight - pane.clientHeight),
                    moved: Math.round(before - after), shut: !document.querySelector('.combo-list:not([hidden])')}; }""")
        print(f"     {json.dumps(moved_shut, ensure_ascii=False)}")
        check("a scroll that moves it still closes the list",
              bool(moved_shut.get("moved")) and moved_shut.get("shut") is True,
              json.dumps(moved_shut, ensure_ascii=False))
        pg.set_viewport_size({"width": 1500, "height": 950})
        pg.wait_for_timeout(250)

        print("\n[a redraw of the sheet keeps the list on the same row and choice]")
        again = pg.evaluate("""() => {
            comboClose(false);
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            b.click();
            if (!document.querySelector('.combo-list:not([hidden])')) return {open: false, was: -3, now: -4};
            const l0 = document.querySelector('.combo-list:not([hidden])');
            const was = [...l0.querySelectorAll('li')].findIndex(o => o.classList.contains('on'));
            renderSettings();                                        // what a status message does
            const l1 = document.querySelector('.combo-list:not([hidden])');
            const now = l1 ? [...l1.querySelectorAll('li')].findIndex(o => o.classList.contains('on')) : -2;
            const btn = document.querySelector('#settings .combo-btn[aria-expanded="true"]');
            return {open: !!l1, was, now, key: btn && btn.dataset.set}; }""")
        print(f"     {json.dumps(again, ensure_ascii=False)}")
        check("it is open again after the redraw, on the same choice",
              bool(again["open"]) and again["was"] == again["now"],
              json.dumps(again, ensure_ascii=False))
        pg.evaluate("() => comboClose(false)")

        print("\n[the keys the list uses do not reach the page behind it]")
        keys = pg.evaluate("""() => {
            comboClose(false);
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            b.focus();
            window.__seen = [];
            const spy = (e) => { window.__seen.push(e.key); };
            document.addEventListener('keydown', spy);
            window.__spy = spy;
            return true; }""")
        pg.keyboard.press("ArrowDown")      # opens
        pg.keyboard.press("ArrowDown")      # moves
        pg.keyboard.press("Home")
        pg.wait_for_timeout(120)
        seen = pg.evaluate("() => { document.removeEventListener('keydown', window.__spy); return window.__seen; }")
        print(f"     keys that reached the document: {seen}")
        check("none of them reaches the document's own handler", seen == [], str(seen))
        pg.evaluate("() => comboClose(false)")

        print("\n[a list too tall for its room scrolls inside itself]")
        # the room is the pane's, so a short window makes even a six-row list scroll
        tall = pg.evaluate("""() => {
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            if (!b) return null;
            b.click();
            const l = document.querySelector('.combo-list:not([hidden])');
            if (!l) return null;
            l.style.maxHeight = '60px';                       // force it, whatever the window is
            const before = l.scrollTop;
            l.scrollTop = 40;
            l.dispatchEvent(new Event('scroll', {bubbles: true}));
            return {scrolls: l.scrollHeight > l.clientHeight + 1, moved: l.scrollTop > before,
                    open: !l.hidden && !!document.querySelector('.combo-list:not([hidden])')}; }""")
        pg.wait_for_timeout(120)
        after = pg.evaluate("() => !!document.querySelector('.combo-list:not([hidden])')")
        print(f"     {json.dumps(tall, ensure_ascii=False)} still open: {after}")
        check("scrolling the list does not close it", bool(tall and tall["scrolls"] and after),
              json.dumps(tall, ensure_ascii=False))
        pg.evaluate("() => comboClose(false)")

        print("\n[the controls in the sheet are one family]")
        fam = pg.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('#settings .combo-btn, #settings .seg button, #settings .switch, #settings .btn')) {
              const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
              out.push({what: el.className.split(' ')[0] || el.tagName.toLowerCase(),
                        h: Math.round(r.height), radius: cs.borderTopLeftRadius, font: cs.fontSize,
                        border: cs.borderTopColor});
            }
            return out; }""")
        by = {}
        for f in fam:
            by.setdefault(f["what"], []).append(f)
        for k, v in by.items():
            hs = sorted({x["h"] for x in v}); rs = sorted({x["radius"] for x in v}); fs = sorted({x["font"] for x in v})
            print(f"     {k:<10} x{len(v):<3} height {hs}  radius {rs}  font {fs}")
        # the row of choices and the dropdown sit next to each other down the same column
        seg = [f for f in fam if f["what"] == "button"]
        combo = [f for f in fam if f["what"] == "combo-btn"]
        if seg and combo:
            check("a dropdown is the same box as a row of choices",
                  {x["h"] for x in seg} == {x["h"] for x in combo}
                  and {x["radius"] for x in seg} == {x["radius"] for x in combo},
                  f"{seg[0]['h']}/{seg[0]['radius']} vs {combo[0]['h']}/{combo[0]['radius']}")

        print("\n[the other things that drop down]")
        # the bar's own menu, which is the other list that opens over the page
        pg.evaluate("() => { comboClose(false); const o = document.getElementById('settings-overlay'); "
                    "if (o && !o.hidden) document.getElementById('settings-close')?.click(); }")
        pg.wait_for_timeout(200)
        menu = pg.evaluate("""() => { const b = document.getElementById('menu-btn') ||
                document.querySelector('[aria-controls=\"menu\"], .bar .btn.icon:last-of-type');
            if (b) b.click();
            const m = document.getElementById('menu') || document.querySelector('.menu');
            if (!m) return null;
            const cs = getComputedStyle(m);
            return {open: !m.hidden, radius: cs.borderTopLeftRadius, bg: cs.backgroundColor,
                    blur: cs.backdropFilter, shadow: cs.boxShadow.slice(0, 28)}; }""")
        print(f"     ⋯ menu: {json.dumps(menu, ensure_ascii=False)}")
        combo = pg.evaluate("""() => { const l = document.querySelector('.combo-list');
            if (!l) return null; const cs = getComputedStyle(l);
            return {radius: cs.borderTopLeftRadius, bg: cs.backgroundColor, blur: cs.backdropFilter,
                    shadow: cs.boxShadow.slice(0, 28)}; }""")
        print(f"     dropdown: {json.dumps(combo, ensure_ascii=False)}")
        if menu and combo:
            # what is read is opaque: a list of words with the page showing through is the one
            # thing the glass is not for
            check("the menu and the dropdown are made of the same surface",
                  menu["bg"] == combo["bg"] and menu["blur"] == combo["blur"] and menu["radius"] == combo["radius"],
                  f"{menu['bg']}/{menu['blur']} vs {combo['bg']}/{combo['blur']}")
            check("and it has a surface of its own", combo["bg"] != "rgba(0, 0, 0, 0)", combo["bg"])
        print("\n[a narrow window]")
        # the sheet stacks its tabs above the pane below 760 px; the dropdown has to stay inside it
        pg.set_viewport_size({"width": 420, "height": 820})
        pg.wait_for_timeout(250)
        if not pg.evaluate("() => !document.getElementById('settings-overlay').hidden"):
            pg.evaluate("() => document.getElementById('open-settings').click()")
            pg.wait_for_timeout(250)
        narrow = pg.evaluate("""() => {
            const b = document.querySelector('#settings .combo-btn:not([disabled])');
            if (!b) return null;
            b.click();
            const l = document.querySelector('.combo-list:not([hidden])');
            if (!l) return {open: false};
            const r = l.getBoundingClientRect();
            return {open: true, left: Math.round(r.left), right: Math.round(r.right),
                    win: window.innerWidth, over: Math.round(Math.max(0, -r.left) + Math.max(0, r.right - window.innerWidth))}; }""")
        print(f"     {json.dumps(narrow, ensure_ascii=False)}")
        check("the list stays inside a 420 px window", bool(narrow and narrow.get("open") and narrow.get("over") == 0),
              json.dumps(narrow, ensure_ascii=False))
        pg.evaluate("() => comboClose(false)")
        pg.set_viewport_size({"width": 1500, "height": 950})
        pg.wait_for_timeout(200)

        if SHOTS:
            # the menu check above closed the sheet to get at the bar: open it again, on the section
            # with the longest list, which is the one worth photographing
            pg.keyboard.press("Escape")
            pg.evaluate("() => document.getElementById('open-settings').click()")
            pg.wait_for_timeout(300)
            if longest:
                pg.evaluate("(s) => document.querySelector(`#settings [data-sec=\"${s}\"]`).click()", longest["sec"])
                pg.wait_for_timeout(200)
            # the checks above leave a list open and the pane scrolled: put both back. Not with
            # Escape, which closes the whole sheet when no list is open, and then there is nothing
            # left to photograph.
            pg.evaluate("""() => { comboClose(false);
                const p = document.querySelector('#settings .set-pane');
                if (p) p.scrollTop = 0; }""")
            pg.wait_for_timeout(250)
            vis = pg.evaluate("""() => { const o = document.getElementById('settings-overlay');
                const s = document.getElementById('settings');
                return {overlay: o && !o.hidden, h: s ? Math.round(s.getBoundingClientRect().height) : 0}; }""")
            print(f"     sheet open: {vis}")
            el = pg.query_selector("#settings")
            if el and vis.get("overlay"):
                el.screenshot(path=str(OUT / "settings.png"), timeout=8000)
                print(f"  shot: {OUT / 'settings.png'}")
            # with one dropdown open, which is the part the system used to draw
            # a disabled control cannot be opened: take the first one that is not
            opener = pg.query_selector(f"#settings [data-combo='{longest['key']}'] .combo-btn") if longest \
                else pg.query_selector("#settings .combo-btn:not([disabled])")
            if opener:
                opener.click()
                pg.wait_for_timeout(300)
                state = pg.evaluate("""() => { const b = document.querySelector('#settings .combo-btn[aria-expanded=\"true\"]');
                    const l = document.querySelector('.combo-list:not([hidden])');
                    return {open: !!b, list: l ? l.getBoundingClientRect().height : null,
                            n: l ? l.querySelectorAll('li').length : 0}; }""")
                more = ", %d rows, %.0f px tall" % (state["n"], state["list"] or 0) if state["open"] else ""
                print("  the list is " + ("open" if state["open"] else "shut") + more)
                pg.screenshot(path=str(OUT / "settings-open.png"))
                print(f"  shot: {OUT / 'settings-open.png'}")
        br.close()
    srv.shutdown()
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    sys.exit(1 if FAIL else 0)


main()
