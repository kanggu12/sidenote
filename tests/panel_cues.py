"""What the panel hides says so, what it says is said one way, and what cannot work is not asked for.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_cues.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

Each of these was found on real answers at six sizes, and is checked here as it is now:
  hidden   the contents' list held at nine lines showed three of a day's five answers and cut the card under the third, and Solver
           settings left three settings under a pane's edge at 1366x768, with nothing to say more was there: the foot of each
           fades while more is below, and not once its end is in view; five bands at 1366x768 stand whole in their box, which
           fades at its foot where they do not fit; a search hit past a row's ellipsis is brought into it
  words    the capture program not connected is said one way (the card, the band, the screen card's pill, the sheet) and started in
           the server's terminal, where ./sidenote is; the notebook is a notebook (노트) everywhere; a local model that is missing
           is not said to be switched off; the agent card's scale is named as its setting is
  steps    the guide's last step names the steps still to do, each a key to it; the sound step does not ask to speak into a
           server that does not listen; one way on the server's PC has no number
  drawn    a switch for what the server was started without is drawn off, grey and not pressable, on the rail and in the guide; the
           chosen chips of a row are told from the others at a glance, a ticked type with its tick
  times    the capture program's connected time reads 03:15 PM like every time in the panel; a day of one answer gives one time,
           not a range from it to itself
  the rest the ask box after a start of the server says what can be asked before why; the update band's close key stays on
           its line on a phone; a long inline command breaks between its words only; an analysis stopped by Free GPU says so,
           Reanalyze in its note presses as the bar's key, and its cut-off code has no Run; a notice never hides a fault's
           band in the bar, standing beside the bands or under the bar; a long notice on a phone shows all its words under
           the bar; on a phone the bands go with the page unless one is a fault; Free GPU is orange only with the memory
           nearly full; inline code in a table cell shows its tint. Practice switched gives no notice: one in the bar hides
           the bands there for its seconds (note 122); the bar says Practice while it is on (panel_study)
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
# How a scroller stands: its class, the fade it is drawn with, and whether its end is in view
EDGE = """(sel) => { const el = document.querySelector(sel); if (!el) return null; const cs = getComputedStyle(el);
  const mask = cs.maskImage || cs.webkitMaskImage || 'none';
  return { more: el.classList.contains('more-below'), mask, scrolls: el.scrollHeight > el.clientHeight + 1,
           atEnd: el.scrollHeight - el.clientHeight - el.scrollTop <= 2 }; }"""


def many(n: int, day_ago: float = 0.0) -> list:
    """`n` answers a few minutes apart, the newest `day_ago` seconds ago."""
    return [row(i, asked=f"질문 {i}번: 노드 스토리지와 네트워크 설정", ago=day_ago + (n - i) * 120) for i in range(1, n + 1)]


def group_hidden(br, s) -> None:
    if not T.group("what does not fit says so"):
        return
    p = Page(br, s, many(14), w=1920, h=1080, settle=600)
    p.wait(300)
    got = p.js(EDGE, "#history")
    check("the contents' list held under its lines: its foot fades while more is below", got and got["scrolls"] and got["more"]
          and "gradient" in got["mask"], got)
    p.js("() => { const l = document.getElementById('history'); l.scrollTop = l.scrollHeight; l.dispatchEvent(new Event('scroll')); }")
    p.wait(150)
    got = p.js(EDGE, "#history")
    check("...and not once its end is in view", got and got["atEnd"] and not got["more"] and got["mask"] == "none", got)
    p.close()
    p = Page(br, s, many(3), w=1920, h=1080, settle=500)
    got = p.js(EDGE, "#history")
    check("a list that shows whole is not faded", got and not got["scrolls"] and not got["more"] and got["mask"] == "none", got)
    p.close()

    # Five bands (the capture program away, a region, a new build, paused, a newer release) have a third of the window: at
    # 1366x768 the fifth stood under the box's foot, with nothing to say so
    def five(p):
        now = p.js("() => Date.now() / 1000")
        p.js("() => { buildAtLoad = 'aaa'; }")
        p.send({"type": "status", "text": "connected", "paused": True, "build": "bbb", "version": "0.10.0", "engines": h.ENGINES,
                "update": {"version": "0.10.1", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.10.1"}},
               {**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3, "clients": 0},
               {"type": "settings", "values": {"roi_box": [0.1, 0.2, 0.6, 0.8]}})
        p.wait(500)
        return p.js("""() => { const a = document.getElementById('alerts'), f = getComputedStyle(a, '::after');
          return { bands: a.querySelectorAll('.alert').length, scrolls: a.scrollHeight > a.clientHeight + 1, more: a.classList.contains('more-below'),
                   fade: f.content !== 'none' && f.backgroundImage.includes('gradient') }; }""")
    p = Page(br, s, many(6), w=1366, h=768, settle=600)
    got = five(p)
    check("five bands at 1366x768 stand whole in their box", got == {"bands": 5, "scrolls": False, "more": False, "fade": False}, got)
    p.close()
    # four bands at 800x600 are 4 px past their box: no fade over the last band for that
    p = Page(br, s, many(6), w=800, h=600, settle=600)
    now = p.js("() => Date.now() / 1000")
    p.js("() => { buildAtLoad = 'aaa'; }")
    p.send({"type": "status", "text": "connected", "paused": True, "build": "bbb", "version": "0.10.0", "engines": h.ENGINES},
           {**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3, "clients": 0},
           {"type": "settings", "values": {"roi_box": [0.1, 0.2, 0.6, 0.8]}})
    p.wait(500)
    got = p.js("""() => { const a = document.getElementById('alerts');
      return { bands: a.querySelectorAll('.alert').length, over: a.scrollHeight - a.clientHeight, more: a.classList.contains('more-below') }; }""")
    check("...and four of them a few pixels past it are not faded for that", got["bands"] == 4 and 0 < got["over"] <= 12 and not got["more"], got)
    p.close()
    p = Page(br, s, many(6), w=1280, h=600, settle=600)
    got = five(p)
    check("...and where they do not, its foot fades while a band is under it", got == {"bands": 5, "scrolls": True, "more": True, "fade": True}, got)
    p.js("() => { const a = document.getElementById('alerts'); a.scrollTop = a.scrollHeight; a.dispatchEvent(new Event('scroll')); }")
    p.wait(150)
    got = p.js("""() => { const a = document.getElementById('alerts');
      return { more: a.classList.contains('more-below'), fade: getComputedStyle(a, '::after').content !== 'none' }; }""")
    check("...and not once the last band is in view", got == {"more": False, "fade": False}, got)
    p.close()

    # Solver settings at 1366x768: a pane longer than its room
    p = Page(br, s, [row(1)], w=1366, h=768, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    p.js("() => document.getElementById('open-settings').click()")
    p.wait(400)
    tabs = p.js("() => [...document.querySelectorAll('#settings-body .set-tab')].map((t) => t.dataset.sec)") or []
    faded, ends = [], []
    for sec in tabs:
        p.js(f"() => document.querySelector('#settings-body .set-tab[data-sec=\"{sec}\"]').click()")
        p.wait(250)
        got = p.js(EDGE, "#settings-body .set-pane:not([hidden])")
        if got and got["scrolls"]:
            faded.append([sec, got["more"]])
            p.js("() => { const el = document.querySelector('#settings-body .set-pane:not([hidden])'); el.scrollTop = el.scrollHeight; }")
            p.wait(150)
            ends.append([sec, p.js(EDGE, "#settings-body .set-pane:not([hidden])")["more"]])
    check("Solver settings at 1366x768: each pane longer than its room fades at its foot", faded and all(m for _, m in faded), [tabs, faded])
    check("...and not once scrolled to its end", ends and not any(m for _, m in ends), ends)
    p.close()

    # a search hit past the row's ellipsis
    long = "노드마다 내부에 작은 노드(VM, 게스트) 두 개를 두는 구조에서 스토리지를 어떻게 나누는가 그리고 NFS 마운트는 어디에"
    p = Page(br, s, [row(1, asked=long), row(2, asked="NFS와 SMB의 차이")], w=1366, h=768, settle=500)
    p.page.fill("#hist-q", "nfs")
    p.wait(500)
    got = p.js("""() => [...document.querySelectorAll('#history .h .ht')].map((ht) => { const m = ht.querySelector('mark'); if (!m) return null;
      return { text: ht.textContent.slice(0, 40), inside: m.getBoundingClientRect().right <= ht.getBoundingClientRect().right + 0.5 }; })""")
    check("a search hit past a row's ellipsis is brought into the row, a few letters before it", got and all(g and g["inside"] for g in got)
          and any(g["text"].startswith("…") for g in got), got)
    p.close()


def group_words(br, s) -> None:
    if not T.group("said one way"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    now = p.js("() => Date.now() / 1000")
    p.send({"type": "status", "version": "0.8.1", "where": "container"})
    p.send({**h.CAPTURE, "clients": 0, "caps": {}, "now": now})
    p.wait(300)
    got = p.js("""() => ({ foot: document.getElementById('cap-who')?.textContent || '', band: document.getElementById('alerts')?.textContent || '',
      pill: document.getElementById('pill-screen')?.textContent || '', sound: document.getElementById('pill-audio')?.textContent || '' })""")
    check("no capture program: the card's foot starts it in the server's terminal, as the sheet does",
          "서버 터미널에서" in got["foot"] and "./sidenote capture" in got["foot"] and "캡처 PC" not in got["foot"], got)
    check("...the band and the cards' pills say it is not connected, not off", "캡처 프로그램 연결 안 됨" in got["band"]
          and got["pill"] == "프로그램 연결 안 됨" and got["sound"] == "프로그램 연결 안 됨" and "꺼짐" not in got["band"] + got["pill"], got)
    p.close()
    # the local model missing: not said to be switched off
    gone = {**h.ENGINES, "local": {**h.ENGINES["local"], "ok": False, "loaded": None, "error": "model not found"},
            "agent": {**h.ENGINES["agent"], "effective": "all"}}
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send({"type": "status", "engines": gone})
    p.wait(300)
    note = p.js("() => document.getElementById('st-agent')?.textContent || ''")
    check("a local model that cannot be used is not said to be switched off", "못 써서" in note and "꺼져" not in note, note)
    off = {**h.ENGINES, "local": {**h.ENGINES["local"], "on": False, "loaded": None}, "agent": {**h.ENGINES["agent"], "effective": "all"}}
    p.send({"type": "status", "engines": off})
    p.wait(300)
    note = p.js("() => document.getElementById('st-agent')?.textContent || ''")
    check("...and one switched off is", "꺼져" in note and "못 써서" not in note, note)
    scale = p.js("() => [...document.querySelectorAll('#st-agent .scale-name, #st-agent dt, #st-agent .k')].map((x) => x.textContent).join('|')")
    whole = p.js("() => document.getElementById('st-agent')?.textContent || ''")
    check("the agent card's scale is named as its setting is (푸는 문제)", "푸는 문제" in whole and "맡기는" not in whole, [scale, whole[:200]])
    p.close()
    p = Page(br, s, [], w=1440, h=900, settle=500)
    pic = p.js("() => [...document.querySelectorAll('#welcome svg text')].map((x) => x.textContent)") or []
    check("the welcome's picture calls the notebook a notebook (노트), as the guide does", "이 노트" in pic and not any("공책" in x for x in pic), pic)
    p.close()


def group_steps(br, s) -> None:
    if not T.group("the guide's steps"):
        return
    p = Page(br, s, [row(1)], w=1366, h=768, settle=500)
    p.send(support.settings_message())
    now = p.js("() => Date.now() / 1000")
    p.send({"type": "status", "version": "0.8.1", "where": "container"})
    p.send({**h.CAPTURE, "clients": 0, "caps": {}, "now": now})
    p.wait(200)
    p.page.click("#more")
    p.wait(150)
    p.page.click("#open-setup")
    p.wait(300)
    p.js("() => document.querySelector('#setup-steps [data-step=\"4\"]').click()")
    p.wait(250)
    got = p.js("""() => { const n = document.querySelector('#setup-body .setup-note.warn');
      return { text: n?.textContent || '', keys: [...(n?.querySelectorAll('[data-setup="step"]') || [])].map((k) => [k.dataset.to, k.textContent]) }; }""")
    check("the last step names the step still to do, as a key: the connection (the screen follows it)",
          [k for k, _ in got["keys"]] == ["0"] and got["keys"][0][1] == "캡처 연결" and "이 단계부터 마치기" in got["text"], got)
    p.js("() => document.querySelector('#setup-body [data-setup=\"step\"]')?.click()")
    p.wait(250)
    check("...which goes to that step", p.js("() => document.querySelector('#setup-steps [aria-selected=\"true\"]')?.dataset.step") == "0")
    # the screen's step done, nothing to solve with: the solving step named
    none = {**h.ENGINES, "local": {**h.ENGINES["local"], "ok": False, "loaded": None}, "agent": {**h.ENGINES["agent"], "ok": False, "mode": "off"},
            "ready": False}
    p.send({"type": "status", "engines": none})
    p.send({**h.CAPTURE, "now": now, "last_frame": now - 1, "last_audio": now - 2})
    p.wait(200)
    p.js("() => document.querySelector('#setup-steps [data-step=\"4\"]').click()")
    p.wait(250)
    keys = p.js("() => [...document.querySelectorAll('#setup-body [data-setup=\"step\"]')].map((k) => k.dataset.to)")
    check("...and with the program connected and nothing to solve with, the solving step", keys == ["1"], keys)
    # one way on the server's PC: no number
    p.js("() => document.querySelector('#setup-steps [data-step=\"0\"]').click()")
    p.send({**h.CAPTURE, "clients": 0, "caps": {}, "now": now})
    p.wait(300)
    got = p.js("() => ({ one: !!document.querySelector('#setup-body .ways.one'), n: [...document.querySelectorAll('#setup-body .ways.one .n')].length })")
    check("one way on the server's PC is a step without a number", got["one"] and got["n"] == 0, got)
    p.close()

    # the server does not listen: the sound step asks no one to speak, and its switches are drawn off
    p = Page(br, s, [row(1)], w=1366, h=768, settle=500)
    p.send(support.settings_message())
    p.send({"type": "status", "audio": False})
    p.wait(200)
    rail = p.js("""() => { const sw = document.getElementById('sw-audio'), src = sw?.closest('.src') || document.getElementById('pill-audio')?.closest('.src');
      return { on: sw?.getAttribute('aria-checked'), disabled: !!sw?.disabled, rest: !!src?.hasAttribute('data-rest'),
               pill: document.getElementById('pill-audio')?.textContent }; }""")
    check("off on the server: the rail's sound switch drawn off and not pressable, the card grey (at rest), not red",
          rail["on"] == "false" and rail["disabled"] and rail["rest"] and rail["pill"] == "서버에서 꺼짐", rail)
    p.page.click("#more")
    p.wait(150)
    p.page.click("#open-setup")
    p.wait(300)
    p.js("() => document.querySelector('#setup-steps [data-step=\"3\"]').click()")
    p.wait(300)
    got = p.js("""() => ({ heard: document.getElementById('setup-heard')?.textContent ?? null,
      voice: document.querySelector('#setup-body [data-set="voice_auto"]')?.getAttribute('aria-checked'),
      dis: !!document.querySelector('#setup-body [data-set="voice_auto"]')?.disabled })""")
    check("...the sound step asks no one to play or say something", got["heard"] is None, got)
    check("...and its spoken-problem switch is drawn off, not pressable", got["voice"] == "false" and got["dis"], got)
    p.send({"type": "status", "audio": True})
    p.wait(300)
    got = p.js("() => ({ heard: document.getElementById('setup-heard')?.textContent ?? null, voice: document.querySelector('#setup-body [data-set=\"voice_auto\"]')?.getAttribute('aria-checked') })")
    check("listening, it asks for a sound and the switch shows the kept choice again", got["heard"] and "영상" in got["heard"]
          and got["voice"] in ("true", "false"), got)
    p.close()


def group_drawn(br, s) -> None:
    if not T.group("on and off at a glance"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    p.js("() => document.getElementById('open-settings').click()")
    p.wait(300)
    p.js("() => document.querySelector('#settings-body .set-tab[data-sec=\"agent\"]')?.click()")
    p.wait(300)
    got = p.js("""() => { const bs = [...document.querySelectorAll('#settings-body .set-pane:not([hidden]) .seg.checks button')];
      const on = bs.find((b) => b.getAttribute('aria-pressed') === 'true'), off = bs.find((b) => b.getAttribute('aria-pressed') !== 'true');
      if (!on || !off) return { n: bs.length };
      return { n: bs.length, tick: getComputedStyle(on, '::before').content, noTick: getComputedStyle(off, '::before').content,
               onColor: getComputedStyle(on).color, offColor: getComputedStyle(off).color }; }""")
    check("a ticked type carries its tick, one not ticked none", got.get("tick") not in (None, "none", "normal") and got.get("noTick") in ("none", "normal"), got)
    check("...and its words are another colour than a type not ticked", got.get("onColor") and got["onColor"] != got.get("offColor"), got)
    p.close()


def group_times(br, s) -> None:
    if not T.group("times"):
        return
    # yesterday at 10:00 and 10:30, and three days before that: the same day for the two whenever this runs (two answers 5 and
    # 10 minutes old fell on two days a minute after midnight)
    noon = datetime.datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
    now = time.time()
    p = Page(br, s, [row(1, ago=now - (noon - datetime.timedelta(days=3)).timestamp()), row(2, ago=now - noon.timestamp()),
                     row(3, ago=now - noon.timestamp() - 1800)], w=1440, h=900, settle=500)
    opts = p.js("() => [...document.querySelectorAll('#hist-day option')].map((o) => o.textContent)")
    one = [o for o in opts if "1개" in o]
    two = [o for o in opts if "2개" in o]
    check("a day of one answer gives one time, not a range to itself", one and all("~" not in o and ("AM" in o or "PM" in o) for o in one), opts)
    check("...and a day of two its range", two and all("~" in o for o in two), opts)
    now = p.js("() => Date.now() / 1000")
    p.send({"type": "status", "version": "0.8.1", "where": "container"})
    p.send({**h.CAPTURE, "now": now, "who": {"host": "DESKTOP-7Q2KD", "system": "Windows 11", "version": "0.8.1", "started": "terminal",
                                             "server": "ws://127.0.0.1:8777/ingest", "ends_server": False}, "since": now - 3 * 3600})
    p.wait(200)
    p.page.click("#more")
    p.wait(150)
    p.page.click("#open-capture")
    p.wait(300)
    facts = p.js("() => [...document.querySelectorAll('#capture-body .setup-state .fact')].map((f) => [f.querySelector('dt').textContent, f.querySelector('dd').textContent])")
    since = [v for k, v in facts if k == "연결 시각"]
    check("the capture program's connected time reads as every time in the panel (03:15 PM)", since and ("AM" in since[0] or "PM" in since[0]), facts)
    p.close()


def group_rest(br, s) -> None:
    if not T.group("the rest"):
        return
    # the ask box after a start of the server, with answers kept from before it
    p = Page(br, s, [row(1), row(2)], w=1920, h=1080, settle=500)
    p.send({"type": "status", "can_ask": False})
    p.wait(250)
    ph = p.js("() => document.getElementById('ask').placeholder")
    check("after a start of the server the ask box says what can be asked first, not a restart as news",
          ph.startswith("다음 답부터 질문 가능") and "재시작" not in ph, ph)
    # an analysis stopped by Free GPU
    p.answer(905, "essay", "멈출 문제", "답", "반쯤", final=False)
    p.send({"type": "analysis_cancelled", "id": 905, "reason": "gpu_released"})
    p.wait(250)
    said = p.js("() => document.querySelector('.entry[data-id=\"905\"] .cap.stopped')?.textContent || ''")
    check("an analysis stopped by Free GPU says so, not just 'stopped'", "GPU를 비워서 멈춤" in said, said)
    # Reanalyze named in that note, and in the paused band, is the key itself: it looked like the bar's and did nothing
    p.send({"type": "status", "paused": True})
    p.wait(300)
    sent = p.js("""async () => { const out = [];
      for (const sel of ['.entry[data-id="905"] .cap.stopped .key-hint', '#alerts .alert .key-hint']) {
        const k = document.querySelector(sel); window.__sent.length = 0; reanalyzedAt = 0;
        k?.click(); out.push(k ? k.tagName + ':' + window.__sent.filter((m) => m.type === 'reanalyze').length : 'none'); }
      return out; }""")
    check("Reanalyze named in a stopped answer's note and in the paused band presses as the bar's key", sent == ["BUTTON:1", "BUTTON:1"], sent)
    p.send({"type": "status", "paused": False})
    # Free GPU is an ordinary key while the GPU has room, in the warning's orange only while its memory is nearly full: always
    # orange beside the green of a model loaded, it read as a warning about nothing
    look = """() => { const k = document.getElementById('gpu-release'), [r, g, b] = getComputedStyle(k).color.match(/\\d+/g).map(Number);
      return { shown: !k.hidden, orange: r - b > 80 && r > 150 }; }"""
    rest = p.js(look)
    p.send({"type": "gpu", "used": 22300, "total": 23028, "util": 41, "temp": 55, "power": 180})
    p.wait(250)
    full = p.js(look)
    p.send(h.GPU)
    p.wait(250)
    check("Free GPU at rest with the memory at 70%: an ordinary key; nearly full: orange", [rest, full] == [{"shown": True, "orange": False}, {"shown": True, "orange": True}],
          [rest, full])
    # A stopped answer's code ends where it was cut off: Copy, and no Run (which failed on its last half line); a whole
    # one keeps its Run
    p.answer(907, "algorithm", "두 수의 합", "3", "풀이\n\n```python\nprint(sum(map(int, input().split())))\n```\n")
    p.answer(908, "algorithm", "세 수의 합", "6", "풀이\n\n```python\nnums = list(map(int, input().split()))\nprint(sum(nu", final=False)
    p.send({"type": "analysis_cancelled", "id": 908, "reason": "gpu_released"})
    p.wait(400)
    got = p.js("""() => Object.fromEntries([907, 908].map((i) => { const e = document.querySelector(`.entry[data-id="${i}"]`);
      return [i, { code: !!e?.querySelector('.md pre > code'), copy: !!e?.querySelector('.md pre .codebar .copy'), run: !!e?.querySelector('.runbox .run') }]; }))""")
    check("a stopped answer's cut-off code has Copy and no Run; a whole one keeps its Run",
          got == {"907": {"code": True, "copy": True, "run": True}, "908": {"code": True, "copy": True, "run": False}}, got)
    p.close()

    # A fault's band in the bar stays in sight while a notice shows: the notice stands beside the bands, in the bar, where
    # its words fit there, and under the bar where they do not
    p = Page(br, s, [row(1)], w=1920, h=1080, settle=500)
    p.drop()
    p.page.wait_for_function("() => !!document.querySelector('#alerts .alert.bad')", timeout=8000)
    where = """() => { const b = document.querySelector('#alerts .alert.bad'), t = document.querySelector('#toast > .alert');
      const bs = getComputedStyle(document.getElementById('alerts')), br = b.getBoundingClientRect(), tr = t.getBoundingClientRect();
      const bar = document.querySelector('.bar').getBoundingClientRect();
      const apart = tr.top >= br.bottom || tr.bottom <= br.top || tr.left >= br.right || tr.right <= br.left;
      return { band: bs.visibility === 'visible' && +bs.opacity > 0.9, apart, inBar: tr.bottom <= bar.bottom + 1,
               toast: document.getElementById('toast').classList.contains('show') }; }"""
    p.js("() => toast('복사됨')")
    p.wait(400)
    seen = p.js(where)
    check("a fault's band in the bar stays in sight while a notice shows, the notice beside it in the bar",
          seen == {"band": True, "apart": True, "inBar": True, "toast": True}, seen)
    p.js("() => toast('긴 알림: ' + '가나다라마바사 '.repeat(14))")
    p.wait(400)
    seen = p.js(where)
    check("...and one too long for the room beside it stands under the bar, the band still in sight",
          seen == {"band": True, "apart": True, "inBar": False, "toast": True}, seen)
    p.close()

    # A long notice to act on, on a phone: under the bar, all its words on the lines they take, where one line in the
    # signals' row cut it to "로컬 모델이 응답하지 않아 에이..." with the rest in a title no finger can rest on
    p = Page(br, s, [row(1)], w=390, h=844, settle=500)
    p.js("() => toast('로컬 모델이 응답하지 않아 에이전트가 대신 풀었음: 다음 문제부터 로컬 모델로 돌아감 (CUDA error: out of memory)', () => {}, 'warn')")
    p.wait(400)
    got = p.js("""() => { const t = document.querySelector('#toast > .alert'), m = t.querySelector('.msg'), r = t.getBoundingClientRect();
      const bar = document.querySelector('.bar').getBoundingClientRect();
      return { whole: m.scrollWidth <= m.clientWidth + 1 && m.scrollHeight <= m.clientHeight + 1, under: r.top >= bar.bottom - 1,
               inside: r.left >= 0 && r.right <= innerWidth, key: !!t.querySelector('.btn') }; }""")
    check("a long notice on a phone stands under the bar with all its words, its key beside them", got == {"whole": True, "under": True, "inside": True,
          "key": True}, got)
    p.close()

    # On a phone the bands go with the page as it scrolls, unless one is a fault: stuck under the bar, the capture program's
    # band took a sixth of the screen while the answers were read
    p = Page(br, s, many(6), w=390, h=844, settle=600)
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3, "clients": 0})
    p.wait(400)
    held = """() => { const a = document.getElementById('alerts'), bar = document.querySelector('.bar').getBoundingClientRect();
      scrollTo(0, 1600); const r = a.getBoundingClientRect();
      return { bands: a.children.length, stuck: r.bottom > bar.bottom + 1, held: getComputedStyle(document.documentElement).getPropertyValue('--alerts-h').trim() }; }"""
    p.js("() => scrollTo(0, 0)")
    p.wait(200)
    got = p.js(held)
    check("a phone scrolled: the capture program's band goes with the page, holding nothing under the bar", got == {"bands": 1, "stuck": False, "held": "0px"},
          got)
    p.drop()
    p.page.wait_for_function("() => !!document.querySelector('#alerts .alert.bad')", timeout=8000)
    p.js("() => scrollTo(0, 0)")
    p.wait(300)
    got = p.js(held)
    check("...and a fault's band stays in sight under the bar", got["stuck"] and got["held"] != "0px", got)
    p.close()

    # On a phone a notice under the bar stays under the bands' strip as the page scrolls back to the top: placed while the
    # strip was scrolled away, the strip came back in under it
    p = Page(br, s, many(6), w=390, h=844, settle=600)
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "now": now, "last_frame": now - 2, "last_audio": now - 3, "clients": 0})
    p.wait(300)
    p.js("() => scrollTo(0, 1600)")
    p.wait(300)
    p.js("() => toast('로컬 모델이 응답하지 않아 에이전트가 대신 풀었음: 다음 문제부터 로컬 모델로 돌아감 (CUDA error: out of memory)', () => {}, 'warn')")
    p.wait(300)
    p.js("() => scrollTo(0, 0)")
    p.wait(500)
    got = p.js("""() => { const t = document.querySelector('#toast > .alert').getBoundingClientRect(), b = document.getElementById('alerts').getBoundingClientRect();
      return { below: document.documentElement.classList.contains('toast-below'), clear: t.top >= b.bottom - 1 || t.bottom <= b.top + 1 }; }""")
    check("a notice under the bar on a phone stays clear of the bands as the page scrolls back to them", got == {"below": True, "clear": True}, got)
    p.close()

    # A wide touch screen: a notice under the bar leaves the bands in the bar drawn, where they faded out for it
    p = Page(br, s, [row(1)], w=1280, h=800, settle=500)
    p.js("""() => { const real = window.matchMedia.bind(window);
      window.matchMedia = (q) => (q.includes('hover: none') ? { matches: true, media: q, addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {} } : real(q)); }""")
    p.send({"type": "status", "paused": True})
    p.wait(300)
    p.js("() => toast('로컬 모델이 응답하지 않아 에이전트가 대신 풀었음: 다음 문제부터 로컬 모델로 돌아감 (CUDA error: out of memory) ' + '가나다 '.repeat(20), () => {}, 'warn')")
    p.wait(400)
    got = p.js("""() => { const a = getComputedStyle(document.getElementById('alerts')), r = document.documentElement.classList;
      return { inBar: r.contains('bands-in-bar'), below: r.contains('toast-below'), drawn: a.visibility === 'visible' && +a.opacity > 0.9 }; }""")
    check("a wide touch screen: a notice under the bar leaves the bands in the bar drawn", got == {"inBar": True, "below": True, "drawn": True}, got)
    p.close()

    # the update band on a phone
    p = Page(br, s, [row(1)], w=390, h=844, settle=500)
    p.send({"type": "status", "version": "0.8.0", "update": {"version": "0.9.0", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.9.0"}})
    p.wait(300)
    got = p.js("""() => { const k = document.querySelector('#alerts [data-act="update-hide"]'), m = k?.closest('.alert')?.querySelector('.msg');
      if (!k || !m) return null; const a = k.getBoundingClientRect(), b = m.getBoundingClientRect();
      return { keyTop: a.top, msgTop: b.top, msgBottom: b.bottom }; }""")
    check("the update band's close key stays on the line of its words on a phone", got and got["keyTop"] < got["msgBottom"], got)
    p.close()

    # Inline code in a table cell shows its tint against the cell: 7 levels off, its air read as spaces in "( sec=krb5p )"
    body = "| 항목 | NFSv4 |\n|---|---|\n| 보안 | Kerberos (`sec=krb5p`) |\n"
    for theme in ("light", "dark"):
        p = Page(br, s, [row(1, body=body)], w=1366, h=768, settle=600)
        p.js(f"() => document.documentElement.setAttribute('data-theme', '{theme}')")
        p.wait(200)
        got = p.js("""() => { const c = [...document.querySelectorAll('.md td code')].find((x) => x.textContent === 'sec=krb5p');
          if (!c) return null; const rgb = (el) => getComputedStyle(el).backgroundColor.match(/[\\d.]+/g).slice(0, 3).map(Number);
          let host = c.closest('td'), b = getComputedStyle(host).backgroundColor;
          while (host && /rgba\\(0, 0, 0, 0\\)|transparent/.test(b)) { host = host.parentElement; b = host ? getComputedStyle(host).backgroundColor : ''; }
          const [x, y] = [rgb(c), rgb(host)]; return Math.max(...x.map((v, i) => Math.abs(v - y[i]))); }""")
        check(f"inline code in a table cell shows its tint against the cell ({theme})", got is not None and got >= 12, got)
        p.close()

    # a long inline command in a table cell
    body = ("| 하는 일 | 명령 |\n|---|---|\n| 클라이언트 마운트 | `mount -t cifs //srv/share /mnt -o user=kim` |\n| 끝 | `umount /mnt` |\n")
    p = Page(br, s, [row(1, body=body)], w=390, h=844, settle=600)
    got = p.js("""() => { const c = [...document.querySelectorAll('.md td code')].find((x) => x.textContent.includes('user=kim'));
      if (!c) return null; const pieces = [...c.querySelectorAll('.w')];
      return { text: c.textContent, pieces: pieces.length, split: pieces.filter((w) => w.getClientRects().length > 1).map((w) => w.textContent),
               lines: new Set([...c.getClientRects()].map((r) => Math.round(r.top))).size }; }""")
    check("a long inline command breaks between its words only, never after the hyphen of '-o'", got and got["text"] == "mount -t cifs //srv/share /mnt -o user=kim"
          and got["pieces"] >= 6 and not got["split"], got)
    p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("cues")
        group_hidden(br, s)
        group_words(br, s)
        group_steps(br, s)
        group_drawn(br, s)
        group_times(br, s)
        group_rest(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    sys.exit(code)
