"""The Capture connection: the capture program as the server knows it, the ways to start one, and its Restart and Quit.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_capture.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

The capture program was a command in a note: the panel said "./sidenote capture" where none was connected, the same words for a
server in a cluster where that command is not the way, and nothing at all of the program that was connected (which PC, which
release, how it was started, what its Quit ends). Checked here: the sheet opens from the menu, the capture card's foot, the band
and the welcome, and from the tray's item of the same name (?open=capture, once, the address put back); its card in each state
(checking, none, connected, another release, a program that says nothing of itself); the wait for one with its seconds and,
past a minute, where to look, its command with a Copy key that stays while the seconds go on; the ways to start one by where
the server runs (its own PC, a cluster's port-forward, the app), each command with its Copy key and this page's port in it;
the tick when one comes while it is open, and none for one that takes over; Restart and Quit sent to the server, Quit asking
twice and saying under the app that it ends Sidenote; the settings the program carries out, pressed as in Solver settings;
Follow the changing screen right after Monitor here, in the guide's Screen step and in Solver settings, dimmed with why where
it has nowhere to move, the reason set apart from its help, and the screen card naming the monitor it followed to; the
card's foot, its key named for what it opens; and the sheet at a phone's width: its commands broken at their spaces and
before an address's slash, never inside a piece that fits its line, and the links over them tall enough to press. All of it
made up.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
SHOWN = "() => document.getElementById('capture-overlay')?.hidden === false"
WHO = {"host": "DESKTOP-7Q2KD", "system": "Windows 11", "version": "0.8.0", "started": "shortcut",
       "server": "ws://127.0.0.1:8777/ingest", "ends_server": True}
CLUSTER = {"type": "status", "version": "0.8.0", "where": "cluster", "forward": {"namespace": "team-a", "service": "notes-sidenote-server", "port": 8777}}


def server(p, where="container", **more):
    """What a server of this release says of itself as a panel opens: its release and where it runs."""
    p.send({"type": "status", "version": "0.8.0", "where": where, "desktop": where == "desktop", **more})


def program(p, who=None, clients=1, ago=200.0):
    """The capture message: `clients` connected, the one that feeds the server saying `who`, connected `ago` seconds ago."""
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "clients": clients, "caps": h.CAPTURE["caps"] if clients else {}, "now": now, "last_frame": now - 2,
            "last_audio": now - 3, "who": who if clients else None, "since": now - ago if clients else None})
    p.wait(200)


def opened(p) -> None:
    """Opened as a person opens it: the gear, then its item, pressed with the pointer (where the keyboard goes back is checked)."""
    p.page.click("#more")
    p.wait(150)
    if p.js("() => !!document.getElementById('open-capture')"):   # an older panel has none: its checks fail on what is not there
        p.page.click("#open-capture")
    p.wait(300)


def sheet(p) -> dict:
    """What the sheet shows now: its card's name, pill, state and facts; the wait; the tick; its keys; the ways' commands and their
    Copy keys; the fold of another PC's ways; the settings rows."""
    empty = {"name": "", "pill": "", "state": "", "facts": [], "note": "", "link": "", "wait": "", "tick": "", "hint": "", "keys": [], "heads": [],
             "cmds": [], "copies": [], "more": None, "folded": False, "notes": [], "zips": [], "rows": []}
    return {**empty, **(p.js("""() => { const b = document.getElementById('capture-body'); if (!b) return {};
      const st = b.querySelector('.setup-state');
      return { name: st?.querySelector('b')?.textContent || '', pill: st?.querySelector('.pill')?.textContent || '', state: st?.querySelector('.pill')?.dataset.state || '',
        facts: [...b.querySelectorAll('.setup-state .fact')].map((f) => [f.querySelector('dt').textContent, f.querySelector('dd').textContent]),
        note: st?.querySelector('.src-note')?.textContent || '', link: st?.querySelector('.src-note a')?.getAttribute('href') || '',
        wait: b.querySelector('.setup-try .secs')?.textContent || '', tick: b.querySelector('.setup-try.done')?.textContent || '',
        hint: b.querySelector('.setup-note.warn')?.textContent || '',
        keys: [...b.querySelectorAll('[data-cap]')].map((k) => [k.dataset.cap, k.textContent.trim()]),
        heads: [...b.querySelectorAll('.ways-h')].map((x) => x.textContent), cmds: [...b.querySelectorAll('.ways code.cmd')].map((c) => c.textContent),
        copies: [...b.querySelectorAll('.ways [data-copy]')].map((c) => c.dataset.copy), more: b.querySelector('details.ways-more')?.open ?? null,
        folded: !!b.querySelector('details.ways-more'), notes: [...b.querySelectorAll('.setup-note:not(.warn)')].map((n) => n.textContent),
        zips: [...b.querySelectorAll('.ways a')].map((a) => a.getAttribute('href')), rows: [...b.querySelectorAll('.set [data-set]')].map((x) => x.dataset.set) }; }""") or {})}


def group_way_in(br, s) -> None:
    if not T.group("the ways in and out"):
        return
    p = Page(br, s, [row(1), row(2)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    server(p)
    program(p, WHO)
    check("not open by itself", not p.js(SHOWN))
    opened(p)
    check("the menu's Capture connection opens it, the keyboard on Close",
          p.js(SHOWN) and p.js("() => document.activeElement?.id") == "capture-close", str(p.js("() => document.activeElement?.id")))
    p.page.keyboard.press("Escape")
    p.wait(200)
    check("Escape closes it, the keyboard back on the gear", not p.js(SHOWN) and p.js("() => document.activeElement?.id") == "more",
          str(p.js("() => document.activeElement?.id")))
    foot = p.js("() => ({ shown: !document.getElementById('cap-prog')?.hidden, key: document.getElementById('cap-open')?.textContent })")
    check("the capture card's foot has the key to it: Manage, with a program connected", foot == {"shown": True, "key": "연결 관리"}, str(foot))
    p.js("() => document.getElementById('cap-open')?.click()")
    p.wait(250)
    check("...and it opens the sheet", p.js(SHOWN))
    p.page.keyboard.press("Escape")
    p.wait(150)
    program(p, clients=0)
    got = p.js("() => ({ key: document.getElementById('cap-open')?.textContent, band: !!document.querySelector('#alerts [data-open-capture]') })")
    check("none connected: the foot's key says Connect, and the band has one too", got == {"key": "연결하기", "band": True}, str(got))
    p.js("() => document.querySelector('#alerts [data-open-capture]')?.click()")
    p.wait(250)
    check("...the band's opens the sheet", p.js(SHOWN))
    p.page.keyboard.press("Escape")
    p.wait(150)
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    # The welcome of an empty notebook: its checklist's capture program step has the key where none is connected
    p = Page(br, s, [], w=1440, h=900, settle=500)
    server(p)
    program(p, clients=0)
    p.js("() => document.querySelector('#welcome [data-open-capture]')?.click()")
    p.wait(250)
    check("the welcome's checklist opens it where none is connected", p.js(SHOWN))
    p.close()
    # The tray's item: ?open=capture opens it once the server has said how things stand, the address put back without it
    p = Page(br, s, [row(1)], w=1440, h=900, settle=300, status=False, query="?open=capture&lang=ko")
    check("not before the server has said how things stand", not p.js(SHOWN))
    p.send({"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": True,
            "run_enabled": True, "runner": True, "engines": h.ENGINES, "version": "0.8.0", "where": "container", "fresh": True}, support.settings_message())
    program(p, WHO)
    p.wait(300)
    got = p.js("() => ({ shown: document.getElementById('capture-overlay')?.hidden === false, guide: document.getElementById('setup-overlay')?.hidden === false, search: location.search })")
    check("the tray's Capture connection (?open=capture) opens the sheet, over the guide a new install would open",
          got["shown"] and not got["guide"], str(got))
    check("...and the address loses it, keeping the rest", got["search"] == "?lang=ko", str(got))
    p.page.reload()
    p.wait(300)
    p.send({"type": "status", "text": "connected", "version": "0.8.0", "where": "container", "engines": h.ENGINES})
    p.wait(300)
    check("...so a reload does not open it again", not p.js(SHOWN))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_none(br, s) -> None:
    """None connected, by where the server runs: the card, the wait, the ways."""
    if not T.group("none connected"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    server(p)
    program(p, clients=0)
    opened(p)
    port = p.js("() => location.port")
    got = sheet(p)
    check("the card says none is connected, and says nothing of how to start one: the ways follow",
          got["name"] == "캡처 프로그램" and got["pill"] == "연결 안 됨" and got["state"] == "idle" and not got["note"], str(got))
    check("...the wait with its seconds", got["wait"] == "0:00", str(got))
    check("on the server's PC first: ./sidenote capture with its Copy key", got["heads"][:1] == ["서버 PC에서"] and got["cmds"][:1] == ["./sidenote capture"]
          and got["copies"][:1] == ["./sidenote capture"], str(got))
    check("...another PC's ways folded under it", got["folded"] and got["more"] is False, str(got))
    p.js("() => { const d = document.querySelector('#capture-body details.ways-more'); d.open = true; d.dispatchEvent(new Event('toggle')); }")
    p.wait(200)
    got = sheet(p)
    check("unfolded: the port forwarded over ssh, the release's capture zip of the server's release, its packages and its start, this page's port in them",
          got["cmds"][1:] == [f"ssh -L {port}:127.0.0.1:{port} 서버 PC", "python3 -m pip install -r requirements.txt", f"python3 capture.py --server ws://127.0.0.1:{port}/ingest"]
          and "https://github.com/kanggu12/sidenote/releases/download/v0.8.0/sidenote-capture-0.8.0.zip" in got["zips"], str(got))
    check("...the placeholder of the forward has no Copy key: what is copied must run as it is",
          not any(c.startswith("ssh ") for c in got["copies"]), str(got["copies"]))
    program(p, clients=0)   # a message from the server: the fold stays as it was opened
    check("...and stays unfolded while the server talks", sheet(p)["more"] is True)
    p.js("() => { capWaitFrom = Date.now() - 61000; }")
    p.wait(1200)
    got = sheet(p)
    check("past a minute: the seconds go on, and where to look for why", got["wait"].startswith("1:0") and "./sidenote capture --console" in got["hint"], str(got))
    key = p.js("() => { const k = document.querySelector('#capture-body .setup-note.warn [data-copy]'); window.__hintKey = k; return k?.dataset.copy || ''; }")
    p.wait(1200)   # the seconds above it go on, drawn again each second
    kept = p.js("() => !!window.__hintKey && window.__hintKey.isConnected")
    check("...its command with the Copy key every command has, left where it is while the seconds go on", key == "./sidenote capture --console" and kept,
          str([key, kept]))
    p.page.keyboard.press("Escape")
    p.wait(150)
    # A server in a cluster: the port-forward this panel came through, the program and its start; no ./sidenote here
    p.send(CLUSTER)
    p.wait(150)
    opened(p)
    got = sheet(p)
    check("in a cluster: the port-forward for its namespace and service to this page's port, the program, its start",
          got["heads"][:1] == ["내 PC에서"] and "서버 PC에서" not in got["heads"] and got["cmds"][0] == f"kubectl --namespace team-a port-forward svc/notes-sidenote-server {port}:8777"
          and got["cmds"][-1] == f"python3 capture.py --server ws://127.0.0.1:{port}/ingest" and "./sidenote capture" not in got["cmds"], str(got))
    check("...each of them with its Copy key", got["copies"] == got["cmds"], str(got))
    foot = p.js("() => document.getElementById('cap-who')?.textContent || ''")
    check("...and the card's foot does not tell a cluster's user to run ./sidenote capture", "./sidenote" not in foot and foot == "내 PC에서 시작", foot)
    p.page.keyboard.press("Escape")
    p.wait(150)
    # The app: it starts its own
    server(p, "desktop")
    opened(p)
    got = sheet(p)
    check("under the app: the app starts it, and no command", not got["cmds"] and any("Sidenote 앱이 서버와 함께 켬" in n for n in got["notes"]), str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    # A browser on Windows: the Python launcher's commands, with no word of a virtual environment
    p = Page(br, s, [row(1)], w=1440, h=900, settle=300, status=False)
    p.page.add_init_script("Object.defineProperty(navigator, 'platform', { get: () => 'Win32' }); try { Object.defineProperty(navigator, 'userAgentData', { get: () => ({ platform: 'Windows' }) }); } catch (e) {}")
    p.page.reload()
    p.page.wait_for_function("() => !!(window.__sock && window.__sock.onmessage)")
    p.open_messages()
    server(p, "cluster", forward=CLUSTER["forward"])
    program(p, clients=0)
    opened(p)
    got = sheet(p)
    check("from a browser on Windows: py -3 for the packages and the start", "py -3 -m pip install -r requirements.txt" in got["cmds"]
          and any(c.startswith("py -3 capture.py --server ") for c in got["cmds"]), str(got["cmds"]))
    p.close()


def group_connected(br, s) -> None:
    if not T.group("a program connected"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    server(p)
    program(p, clients=0)
    opened(p)
    program(p, WHO)
    got = sheet(p)
    check("one comes while it is open: the card says connected, with the tick naming its PC", got["pill"] == "연결됨" and got["state"] == "ok"
          and "DESKTOP-7Q2KD · Windows 11" in got["tick"], str(got))
    facts = dict(got["facts"])
    check("...its PC, its release against the server's, how it was started and what its Quit ends, its address, since when",
          facts.get("PC") == "DESKTOP-7Q2KD · Windows 11" and facts.get("버전") == "v0.8.0 · 서버와 같음"
          and facts.get("시작 방식") == "바탕화면 바로가기 · 트레이의 Sidenote 끝내기는 서버도 끔" and facts.get("주소") == "127.0.0.1:8777"
          and "3분 전" in facts.get("연결 시각", ""), str(facts))
    check("...Restart and Quit the program: the card says what the tray's Quit ends, the key what it ends itself",
          got["keys"] == [["restart", "다시 시작"], ["quit", "프로그램 끝내기"]], str(got))
    check("...the ways to start one folded away, another PC's left under its fold", "서버 PC에서" not in got["heads"] and got["folded"], str(got))
    check("...and the settings the program carries out, drawn as Solver settings draws them", got["rows"][:3] == ["monitor", "stitch", "skip_windows"]
          or {"monitor", "stitch", "skip_windows"} <= set(got["rows"]), str(got["rows"]))
    p.js("() => { window.__sent.length = 0; document.querySelector('#capture-body [data-set=\"stitch\"]')?.click(); }")
    p.wait(200)
    sent = p.js("() => window.__sent.filter((m) => m.type === 'setting')")
    check("...pressed as there: the switch sends the setting", sent == [{"type": "setting", "key": "stitch", "value": True}], str(sent))
    p.js("() => { window.__sent.length = 0; document.querySelector('#capture-body [data-cap=\"restart\"]')?.click(); document.querySelector('#capture-body [data-cap=\"restart\"]')?.click(); }")
    p.wait(150)
    sent = p.js("() => window.__sent.map((m) => m.type)")
    check("Restart asks the server once, however often it is pressed before it answers", sent == ["capture_restart"], str(sent))
    p.js("() => { window.__sent.length = 0; document.querySelector('#capture-body [data-cap=\"quit\"]')?.click(); }")
    p.wait(100)
    armed = p.js("() => ({ sent: window.__sent.map((m) => m.type), words: document.querySelector('#capture-body [data-cap=\"quit\"]')?.textContent })")
    p.wait(700)   # past the wait that keeps a double click from asking and doing at once
    p.js("() => document.querySelector('#capture-body [data-cap=\"quit\"]')?.click()")
    p.wait(150)
    sent = p.js("() => window.__sent.map((m) => m.type)")
    check("Quit asks first, and the second press sends it", armed == {"sent": [], "words": "한 번 더 누르면 끝냄"} and sent == ["capture_quit"], str((armed, sent)))
    # another program takes over while it is open: its card, and no tick (it did not come to one that waited)
    program(p, {**WHO, "host": "LAPTOP-9", "system": "macOS 15.1", "version": "0.7.0", "started": "own", "ends_server": False}, ago=5)
    got = sheet(p)
    facts = dict(got["facts"])
    check("another release, started by hand elsewhere: the card warns, and says where the server's release is",
          got["state"] == "warn" and facts.get("버전") == "v0.7.0 · 서버는 v0.8.0" and facts.get("시작 방식") == "직접 실행 · 끝내도 서버는 그대로"
          and got["link"].endswith("/v0.8.0/sidenote-capture-0.8.0.zip"), str(got))
    check("...a program that took over is not one that came: no tick", not got["tick"], str(got["tick"]))
    program(p, {**WHO, "version": "0.7.0"})
    check("another release started from the server's checkout: restarting it runs the server's code", sheet(p)["note"] == "다시 시작하면 서버의 코드로 실행", sheet(p)["note"])
    program(p, None)
    got = sheet(p)
    check("a program before 0.8.0, which says nothing of itself: connected, its release not known, told as a warning",
          got["pill"] == "연결됨" and got["state"] == "warn" and dict(got["facts"]).get("버전") == "알 수 없음 (0.8.0 이전)", str(got))
    p.page.keyboard.press("Escape")
    p.wait(150)
    # under the app: Quit ends Sidenote, and says so
    server(p, "desktop")
    program(p, {**WHO, "started": "app"})
    opened(p)
    got = sheet(p)
    check("under the app its Quit is Quit Sidenote, and the card says Quit ends the app",
          ["quit", "Sidenote 끝내기"] in got["keys"] and dict(got["facts"]).get("시작 방식") == "Sidenote 앱 · 끝내면 앱도 끝남", str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_keys(br, s) -> None:
    """What the sheet must not lose or must keep: the keyboard on the fold once it is opened, a pressed key back when
    nothing changes, the keyboard on Close when its key goes, the arrival said to a screen reader, and no ways claimed while
    the server is away."""
    if not T.group("the keyboard, the keys and the words for a screen reader"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    server(p)
    program(p, WHO)
    opened(p)
    p.page.focus("#capture-body details.ways-more > summary")
    p.page.keyboard.press("Enter")   # opened from the keyboard, as a person on the keys opens it
    p.wait(2300)                     # two of the once-a-second redraws
    got = p.js("() => ({ open: document.querySelector('#capture-body details.ways-more')?.open, on: document.activeElement?.tagName })")
    check("'From another PC' opened from the keyboard stays open, the keyboard on it, across the redraws", got == {"open": True, "on": "SUMMARY"}, str(got))
    p.js("() => { window.__sent.length = 0; document.querySelector('#capture-body [data-cap=\"restart\"]')?.click(); }")
    p.wait(300)
    held = p.js("() => document.querySelector('#capture-body [data-cap=\"restart\"]')?.getAttribute('aria-disabled')")
    p.wait(4200)   # the server answered nothing that changes the sheet (no program to tell, another one taking over)
    back = p.js("() => document.querySelector('#capture-body [data-cap=\"restart\"]')?.getAttribute('aria-disabled')")
    check("Restart, pressed, waits for the server, and comes back when nothing on the sheet changes", held == "true" and back is None, str((held, back)))
    p.page.focus("#capture-body [data-cap='restart']")
    program(p, clients=0)
    p.wait(300)
    check("the program gone while its key had the keyboard: the keyboard on Close, not on the page under the sheet",
          p.js("() => document.activeElement?.id") == "capture-close", str(p.js("() => document.activeElement?.id || document.activeElement?.tagName")))
    program(p, WHO, ago=1)
    p.wait(300)
    said = p.js("() => document.getElementById('live-note')?.textContent || ''")
    check("one that comes while it is open is said to a screen reader, with its PC", "DESKTOP-7Q2KD" in said and "연결됨" in said, said)
    p.drop()
    p.wait(300)
    got = sheet(p)
    check("the server away: the card says it is checking, and no way to start one is claimed", got["pill"] == "확인 중" and not got["cmds"] and not got["folded"], str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_foot(br, s) -> None:
    """The capture card's foot, where the program is said in a line."""
    if not T.group("the capture card's foot"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=300, status=False)
    check("nothing said before the server has", p.js("() => document.getElementById('cap-prog')?.hidden") is True)
    p.open_messages()
    server(p)
    program(p, clients=0)
    foot = p.js("() => ({ text: document.getElementById('cap-who')?.textContent, state: document.getElementById('cap-prog')?.dataset.state, note: document.querySelector('#st-screen .src-note')?.textContent || '' })")
    check("none connected: how to start one, once, at the foot (not again under the screen's line)",
          foot["text"] == "서버 터미널에서 ./sidenote capture" and foot["state"] == "idle" and not foot["note"], str(foot))
    program(p, WHO)
    foot = p.js("() => ({ text: document.getElementById('cap-who')?.textContent, title: document.getElementById('cap-who')?.title, state: document.getElementById('cap-prog')?.dataset.state })")
    check("connected: its PC and release on the line, its system too in the tooltip",
          foot == {"text": "DESKTOP-7Q2KD · v0.8.0", "title": "DESKTOP-7Q2KD · Windows 11 · v0.8.0", "state": "ok"}, str(foot))
    # its key opens the Capture connection: named for it, not with the gear menu's word for Maintenance (관리)
    words = p.js("() => [document.getElementById('cap-open')?.textContent, document.getElementById('open-maint')?.textContent]")
    check("...and its key says what it opens, in words no other key of the page has", words[0] == "연결 관리" and words[0] != words[1], str(words))
    program(p, {**WHO, "version": "0.7.0"})
    foot = p.js("() => ({ state: document.getElementById('cap-prog')?.dataset.state, warn: document.querySelector('#cap-who .warn')?.textContent })")
    check("...another release in the warning's colour", foot == {"state": "warn", "warn": "v0.7.0"}, str(foot))
    program(p, None)
    foot = p.js("() => ({ text: document.getElementById('cap-who')?.textContent, state: document.getElementById('cap-prog')?.dataset.state })")
    check("a program before 0.8.0: why the foot is amber, in a word", foot == {"text": "연결됨 · 0.8.0 이전 프로그램", "state": "warn"}, str(foot))
    p.drop()
    p.wait(250)
    check("the server gone: nothing said of a program it cannot see", p.js("() => document.getElementById('cap-prog')?.hidden") is True)
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


FOLLOW_ROW = """(where) => { const k = document.querySelector(where + ' [data-set="monitor_follow"]'), r = k?.closest('.set');
  return r ? { dim: r.getAttribute('aria-disabled'), off: !!k.disabled, why: r.querySelector('.warn')?.textContent || '',
               label: r.querySelector('.lbl')?.textContent || '', help: [...r.querySelectorAll('.help')].pop()?.textContent || '' } : null; }"""
TWO = [[0, "모든 모니터"], [1, "1번 (3840x2160)"], [2, "2번 (1440x2560)"]]   # the Monitor row's choices a program of two monitors gives
ONE = [[0, "모든 모니터"], [1, "1번 (1920x1080)"]]


def group_follow(br, s) -> None:
    """Follow the changing screen: its row right after Monitor wherever the program's settings are drawn (this sheet, the
    guide's Screen step, Solver settings' Capture), dimmed with why where it has nowhere to move, pressed as there; and the
    screen card naming the monitor read, and that it was followed there."""
    if not T.group("following the changing screen"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    server(p)
    program(p, WHO)
    p.send({"type": "settings", "values": {}, "options": {"monitor": TWO}})
    opened(p)
    rows = sheet(p)["rows"]
    check("the Capture connection holds it right after Monitor", rows[:4] == ["monitor", "monitor_follow", "stitch", "skip_windows"], str(rows))
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("...two monitors: a switch to press, nothing in its way, in Korean", {k: v for k, v in (got or {}).items() if k != "help"}
          == {"dim": "false", "off": False, "why": "", "label": "바뀐 화면 따라가기"}, str(got))
    p.js("() => { window.__sent.length = 0; document.querySelector('#capture-body [data-set=\"monitor_follow\"]')?.click(); }")
    p.wait(200)
    sent = p.js("() => window.__sent.filter((m) => m.type === 'setting')")
    check("...pressed, it sends the setting", sent == [{"type": "setting", "key": "monitor_follow", "value": True}], str(sent))
    p.send({"type": "settings", "values": {"monitor_follow": True}, "options": {"monitor": ONE}})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("a program of one monitor: dimmed, not pressable, and says why", got and got["dim"] == "true" and got["off"]
          and got["why"] == "모니터가 두 대 이상일 때 씀", str(got))
    # the reason set apart from the help as the panel's facts are, and the help one phrase (no full stop in it) that says it
    # comes back again: run together, "…고른 모니터만 모니터가 두 대 이상일 때 씀" read as one sentence
    said = (got or {}).get("help", "")
    check("...the reason after the help and a dot, the help one phrase that goes and comes back",
          said.endswith(" · 모니터가 두 대 이상일 때 씀") and "." not in said and "돌아오" in said, said)
    p.send({"type": "settings", "values": {"monitor": 0}, "options": {"monitor": TWO}})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("All monitors chosen: dimmed, and says it needs one chosen", got and got["dim"] == "true" and got["why"] == "모니터 하나를 고를 때 씀", str(got))
    p.send({"type": "settings", "values": {"monitor": 1}})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("...one chosen again: pressable again, its value kept", got and got["dim"] == "false" and not got["off"]
          and p.js("() => document.querySelector('#capture-body [data-set=\"monitor_follow\"]')?.getAttribute('aria-checked')") == "true", str(got))
    # A program that cannot read the window list (off Windows and macOS) cannot leave this tool's panel out: it says so,
    # and the sheet open meanwhile greys the switch out with the reason, then frees it when a program that can connects
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "caps": {**h.CAPTURE["caps"], "follow_ok": False}, "now": now, "last_frame": now - 2, "last_audio": now - 3,
            "who": WHO, "since": now - 200})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("a program that cannot follow: dimmed at once, with the reason", got and got["dim"] == "true" and got["off"]
          and got["why"] == "Windows와 macOS에서 씀", str(got))
    p.send({**h.CAPTURE, "caps": {**h.CAPTURE["caps"], "follow_ok": True}, "now": now, "last_frame": now - 2, "last_audio": now - 3,
            "who": WHO, "since": now - 200})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#capture-body")
    check("...one that can: pressable again", got and got["dim"] == "false" and not got["off"], str(got))
    p.page.keyboard.press("Escape")
    p.wait(150)
    p.js("() => { openSetup(2); }")
    p.wait(300)
    rows = p.js("() => [...document.querySelectorAll('#setup-body .set [data-set]')].map((b) => b.dataset.set)")
    check("the setup guide's Screen step holds it right after Monitor", rows[:3] == ["monitor", "monitor_follow", "skip_windows"], str(rows))
    p.send({"type": "settings", "values": {}, "options": {"monitor": ONE}})
    p.wait(250)
    got = p.js(FOLLOW_ROW, "#setup-body")
    check("...dimmed there the same, with the same words", got and got["dim"] == "true" and got["why"] == "모니터가 두 대 이상일 때 씀", str(got))
    p.js("() => closeSetup()")
    p.send({"type": "settings", "values": {}, "options": {"monitor": TWO}})
    p.js("() => { openSettings(); document.querySelector('#settings-body [data-sec=\"capture\"]')?.click(); }")
    p.wait(300)
    rows = p.js("() => [...document.querySelectorAll('#settings-body .set [data-set]')].map((b) => b.dataset.set)")
    check("Solver settings' Capture section has it right after Monitor", "monitor" in rows and rows[rows.index("monitor") + 1:rows.index("monitor") + 2] == ["monitor_follow"],
          str(rows))
    p.js("() => closeSettings()")
    # The screen card: the monitor read, and that it was followed there; the chosen one, as before, once it reads that again
    fact = "() => [...document.querySelectorAll('#st-screen .fact')].map((f) => [f.querySelector('dt').textContent, f.querySelector('dd').textContent])"
    now = p.js("() => Date.now() / 1000")
    caps = {**h.CAPTURE["caps"], "following": 2}
    p.send({**h.CAPTURE, "caps": caps, "now": now, "last_frame": now - 2, "last_audio": now - 3, "who": WHO, "since": now - 200})
    p.wait(250)
    followed = dict(p.js(fact))
    p.send({**h.CAPTURE, "caps": {**caps, "following": None}, "now": now, "last_frame": now - 2, "last_audio": now - 3, "who": WHO, "since": now - 200})
    p.wait(250)
    chosen = dict(p.js(fact))
    check("the screen card names the monitor read and that it followed the screen there, and the chosen one alone once it reads that",
          followed.get("모니터") == "2번 1440x2560 · 따라감" and chosen.get("모니터") == "1번 3840x2160", str((followed, chosen)))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    # In English: the same words the guide names
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500, locale="en-US", query="?lang=en")
    p.send(support.settings_message())
    server(p)
    program(p, WHO)
    p.send({"type": "settings", "values": {}, "options": {"monitor": [[0, "All monitors"], [1, "Monitor 1 (1920x1080)"]]}})
    opened(p)
    got = p.js(FOLLOW_ROW, "#capture-body")
    now = p.js("() => Date.now() / 1000")
    p.send({**h.CAPTURE, "caps": {**h.CAPTURE["caps"], "following": 2}, "now": now, "last_frame": now - 2, "last_audio": now - 3, "who": WHO,
            "since": now - 200})
    p.wait(250)
    card = dict(p.js(fact))
    check("in English: why it is dimmed, and the card's monitor", got and got["why"] == "Used with two monitors or more"
          and card.get("Monitor") == "#2 1440x2560 · following", str((got, card)))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_narrow(br, s) -> None:
    if not T.group("a phone's width"):
        return
    p = Page(br, s, [row(1)], w=360, h=740, settle=500)
    p.send(support.settings_message())
    got = []
    for where, clients in (("container", 0), ("cluster", 0), ("container", 1), ("desktop", 1)):
        if where == "cluster":
            p.send(CLUSTER)
        else:
            server(p, where)
        program(p, WHO if clients else None, clients=clients)
        p.js("() => openCapture()")
        p.js("() => { const d = document.querySelector('#capture-body details.ways-more'); if (d) d.open = true; }")
        p.wait(250)
        got.append(p.js("""(w) => { const c = document.getElementById('capture'), b = document.getElementById('capture-body');
          const out = [...c.querySelectorAll('code.cmd, .btn, .fact dd, .ways .t')].filter((e) => e.offsetParent !== null)
            .filter((e) => { const r = e.getBoundingClientRect(), box = c.getBoundingClientRect(); return r.right > box.right + 1 || r.left < box.left - 1; }).length;
          return { where: w, side: c.scrollWidth - c.clientWidth, page: document.documentElement.scrollWidth - innerWidth, out }; }""", where))
        p.js("() => closeCapture()")
    check("at 360 px nothing runs out of the sheet sideways, in each state", all(x["side"] <= 0 and x["page"] <= 0 and x["out"] == 0 for x in got), str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    # A command broken inside a word that fits its line ("requirements.txt") reads as two commands, and an address or a
    # service broken inside a name ("ws://127.0.0.1:8777/ing|est", "svc/notes-sidenote-|server") as two names: a line breaks
    # at a space, or before an address's slash, and inside a piece only where that piece alone is wider than the line. The
    # links over the commands are keys a finger presses
    for width, hh in ((390, 844), (360, 740)):
        p = Page(br, s, [row(1)], w=width, h=hh, settle=500)
        p.send(support.settings_message())
        for where in ("cluster", "container"):
            if where == "cluster":
                p.send(CLUSTER)
            else:
                server(p, where)
            program(p, clients=0)
            p.js("() => { openCapture(); const d = document.querySelector('#capture-body details.ways-more'); if (d) { d.open = true; d.dispatchEvent(new Event('toggle')); } }")
            p.wait(250)
            cut = p.js(h.CUT_PIECES, "#capture-body .ways")
            check(f"{width} px, {where}: its commands break at their spaces and before an address's slash, a piece cut only where it alone is wider than its line",
                  not cut, str(cut))
            tall = p.js("() => [...document.querySelectorAll('#capture-body .ways .d a')].map((a) => [a.textContent, Math.round(a.getBoundingClientRect().height * 10) / 10])")
            check(f"{width} px, {where}: the links over them 24 px tall at least", tall and all(t >= 24 for _, t in tall), str(tall))
            p.js("() => closeCapture()")
        check(f"{width} px: no page errors", not p.errors, str(p.errors[:2]))
        p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("capture")
        group_way_in(br, s)
        group_none(br, s)
        group_connected(br, s)
        group_keys(br, s)
        group_foot(br, s)
        group_follow(br, s)
        group_narrow(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
