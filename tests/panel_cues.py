"""What the panel hides says so, what it says is said one way, and what cannot work is not asked for (the 0.8.1 review).

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_cues.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

A review of the panel on real answers at six sizes found these, each checked here as it is now:
  hidden   the contents' list held at nine lines showed three of a day's five answers and cut the card under the third, and Solver
           settings left three settings under a pane's edge at 1366x768, with nothing to say more was there: the foot of each
           fades while more is below, and not once its end is in view; a search hit past a row's ellipsis is brought into it
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
           its line on a phone; a long inline command breaks between its words only; an analysis stopped by Free GPU says so.
           Practice switched gives no notice: one in the bar hides the bands there for its seconds (note 122), and the
           menu's On and Off say it
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
