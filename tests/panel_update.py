"""The version and a newer release in the panel: the version at the foot of the gear menu; the notice as one line in the
band, with its link to the release's page in a new tab; a link outside the repository's releases left out, and a version
that is not three numbers not shown; the close key hiding it for that version in this browser, and a newer one shown
again, with the browser's storage refused too; the switch off hiding it at once; the switch with nothing to do when the
environment turned the check off, saying why; the notice in English.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_update.py

How the notice fits the band at every width in both themes is measured by panel_design.py and panel_layout.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
PAGE = "https://github.com/kanggu12/sidenote/releases/tag/v0.1.2"
UPDATE = {"type": "status", "version": "0.1.0", "update": {"version": "0.1.2", "url": PAGE}}
HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")
# The notice's band as the page drew it: its words, its link and its key, or None when there is none
BAND = """() => {
  const a = [...document.querySelectorAll('#alerts .alert')].find((x) => x.querySelector('[data-act="update-hide"]'));
  if (!a) return null;
  const l = a.querySelector('.msg a'), k = a.querySelector('[data-act="update-hide"]');
  return { kind: a.className, words: a.querySelector('.msg').textContent.trim(), bold: a.querySelector('.msg b')?.textContent,
           link: l && { href: l.getAttribute('href'), text: l.textContent, target: l.target, rel: l.rel }, key: k && { title: k.title, aria: k.getAttribute('aria-label'), version: k.dataset.version },
           last: a === [...document.querySelectorAll('#alerts .alert')].pop() };
}"""
ROWS = [row(1, "essay", "물음", "답", "풀이")]


def group_menu(br, s):
    if not T.group("the version in the menu"):
        return
    p = Page(br, s, ROWS, w=1440, h=900, settle=300)
    p.js("() => document.getElementById('more').click()")
    p.wait(200)
    check("before the server says its version the menu shows none", p.js("() => document.getElementById('menu-about').hidden"))
    p.send({"type": "status", "version": "0.1.0"})
    p.wait(150)
    got = p.js("""() => { const m = document.getElementById('menu').getBoundingClientRect(), v = document.getElementById('menu-ver');
        const left = (el) => { const t = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim()); const r = document.createRange(); r.selectNodeContents(t); return Math.round(r.getBoundingClientRect().left - m.left); };
        return { shown: !document.getElementById('menu-about').hidden && !!v.offsetParent, text: v.textContent, at: left(v), items: [...document.querySelectorAll('#menu .item')].filter((el) => el.offsetParent).map(left),
                 last: document.getElementById('menu').lastElementChild.id, inside: v.getBoundingClientRect().bottom <= m.bottom }; }""")
    check("then its foot says it: '버전 0.1.0'", got["shown"] and got["text"] == "버전 0.1.0" and got["last"] == "menu-about" and got["inside"], got)
    # the items drawn: one that is hidden (What was heard, with nothing kept) has no column to be on
    check("...its words on the items' words' column", {got["at"]} == set(got["items"]), got)
    p.send({"type": "status", "version": "<img src=x onerror=alert(1)>"})
    p.wait(100)
    check("a version that is not one is not shown, nor drawn as markup", p.js("() => document.getElementById('menu-about').hidden && !document.querySelector('#menu img')"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_band(br, s):
    if not T.group("the notice in the band"):
        return
    p = Page(br, s, ROWS, w=1440, h=900, settle=300)
    check("no notice before the server finds a release", p.js(BAND) is None)
    p.send(UPDATE)
    p.wait(150)
    b = p.js(BAND)
    check("a newer release is one line in the band: 'Sidenote 0.1.2 출시'", b and b["bold"] == "Sidenote 0.1.2 출시" and b["words"] == "Sidenote 0.1.2 출시 릴리스 노트"
          and "info" in b["kind"], b)
    check("...with a link to its release notes, in a new tab, with nothing of this page going with it",
          b and b["link"] == {"href": PAGE, "text": "릴리스 노트", "target": "_blank", "rel": "noopener noreferrer"}, b and b["link"])
    check("...and a close key that says what it does", b and b["key"] == {"title": "이 버전 알림 숨기기", "aria": "이 버전 알림 숨기기", "version": "0.1.2"}, b and b["key"])
    p.send({"type": "status", "paused": True})
    p.wait(120)
    b = p.js(BAND)
    check("with another band up it comes last: only worth knowing", b and b["last"], b)
    p.send({"type": "status", "paused": False})
    for name, url in (("another site", "https://evil.example.com/kanggu12/sidenote/releases/tag/v0.1.2"),
                      ("another repository", "https://github.com/kanggu12/sidenote-fork/releases/tag/v0.1.2"),
                      ("a path out of the releases", "https://github.com/kanggu12/sidenote/releases/../../x"),
                      ("a script", "javascript:alert(1)")):
        p.send({"type": "status", "update": {"version": "0.1.2", "url": url}})
        p.wait(80)
        b = p.js(BAND)
        check(f"a link to {name} is left out, the notice kept", b and b["link"] is None and b["bold"] == "Sidenote 0.1.2 출시", b)
    p.send({"type": "status", "update": {"version": "0.1.2\"><img src=x onerror=alert(1)>", "url": PAGE}})
    p.wait(80)
    check("a version that is not three numbers is not shown, nor drawn as markup", p.js(BAND) is None and not p.js("() => !!document.querySelector('#alerts img')"))
    p.send(UPDATE)
    p.drop()
    p.wait(150)
    check("not while the server is away", p.js(BAND) is None and "서버" in p.js("() => document.getElementById('alerts').textContent"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_hide(br, s):
    if not T.group("closing it, for that version"):
        return
    p = Page(br, s, ROWS, w=1440, h=900, settle=300)
    p.send(UPDATE)
    p.wait(150)
    p.page.locator('#alerts [data-act="update-hide"]').click()
    p.wait(150)
    check("the close key hides it", p.js(BAND) is None)
    check("...and this browser keeps the version it was closed for", p.js("() => localStorage.getItem('sidenote-update-hidden')") == "0.1.2")
    p.page.reload(wait_until="load")
    p.wait(150)
    p.open_messages()
    p.send(UPDATE)
    p.wait(200)
    check("opened again, the same version stays hidden", p.js(BAND) is None)
    p.send({"type": "status", "update": {"version": "0.1.3", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.1.3"}})
    p.wait(150)
    b = p.js(BAND)
    check("a newer one than that is shown again", b and b["bold"] == "Sidenote 0.1.3 출시", b)
    # The browser refusing its storage (a setting, a private window): the key still closes it, for the page's life
    p.js("() => Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('denied', 'SecurityError'); } })")
    p.send({"type": "status", "update": {"version": "0.1.4", "url": "https://github.com/kanggu12/sidenote/releases/tag/v0.1.4"}})
    p.wait(150)
    shown = p.js(BAND) is not None
    p.page.locator('#alerts [data-act="update-hide"]').click()
    p.wait(150)
    check("with the browser's storage refused, it is shown and the key still closes it", shown and p.js(BAND) is None)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_switch(br, s):
    if not T.group("the switch"):
        return
    msg = h.support.settings_message()
    p = Page(br, s, ROWS, w=1440, h=900, settle=300)
    p.send(msg)
    p.send({"type": "settings", "values": {"update_check": True}})
    p.send(UPDATE)
    p.wait(150)
    shown = p.js(BAND) is not None
    p.send({"type": "settings", "values": {"update_check": False}})
    p.wait(120)
    check("the switch off hides the notice at once", shown and p.js(BAND) is None)
    p.send({"type": "settings", "values": {"update_check": True}})
    p.wait(120)
    check("...and on again shows it", p.js(BAND) is not None)
    row_of = """() => { const s = document.querySelector('[data-set="update_check"]'); if (!s) return null; const r = s.closest('.set');
        return { label: r.querySelector('.lbl').textContent, off: r.getAttribute('aria-disabled'), disabled: s.disabled, why: r.querySelector('.help .warn')?.textContent || '' }; }"""
    p.js("() => { document.getElementById('more').click(); document.getElementById('open-settings').click(); }")
    p.wait(250)
    on = p.js(row_of)
    check("'새 버전 확인' is a switch in the first section, there to be used", on and on["label"] == "새 버전 확인" and on["off"] == "false" and not on["disabled"], on)
    p.send({"type": "status", "update_check": False})
    p.wait(200)
    off = p.js(row_of)
    check("with the check turned off by the environment, it has nothing to do and says why",
          off and off["off"] == "true" and off["disabled"] and off["why"] == "새 버전 확인 꺼짐 (SIDENOTE_UPDATE_CHECK)", off)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_english(br, s):
    if not T.group("in English"):
        return
    p = Page(br, s, ROWS, w=1440, h=900, settle=300, locale="en-US")
    p.send(UPDATE)
    p.wait(150)
    b = p.js(BAND)
    check("the notice in English: 'Sidenote 0.1.2 is out', 'Release notes'", b and b["words"] == "Sidenote 0.1.2 is out Release notes"
          and b["key"]["title"] == "Hide for this version", b)
    p.js("() => document.getElementById('more').click()")
    p.wait(150)
    words = p.js("() => document.getElementById('menu-ver').textContent")
    check("...the menu's 'Version 0.1.0'", words == "Version 0.1.0", words)
    seen = p.js("""() => [...document.querySelectorAll('#alerts .alert, #menu-about')].map((e) => e.textContent + ' ' + [...e.querySelectorAll('[title], [aria-label]')].map((x) => x.title + x.getAttribute('aria-label')).join(' ')).join(' ')""")
    check("...with no Hangul in it", not HANGUL.search(seen), seen)
    p.close()


def main() -> int:
    h.support.need_vendor(h.PANEL)
    s = Stand("update")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_menu, group_band, group_hide, group_switch, group_english):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
