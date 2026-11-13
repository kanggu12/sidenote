"""Deleting an answer in the panel: the delete key on an answer's head, what pressing it sends and what the server's word
draws on every panel, the notice with Undo (and z), messages still on their way about a deleted answer, a card the history
never held, the Recently deleted sheet (Restore, Delete for good, Empty), Clear history taking it all, an answer deleted while
the connection was down, and how the key, the notice and the sheet look in a wide, a narrow and a low window.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_delete.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

The page is a copy of panel/ over the stand-in server of panel_harness.py: its /history and /history/deleted give the rows
the checks set, and its socket is the checks' own, through which they speak as the server would (server/app.py, answer_delete).
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
DAY = 86400
HANGUL = re.compile(r"[가-힣]")

# The page's own state, read off it: what the notebook shows, what the contents list, what went out, the notice
SHOWN = "() => [...document.querySelectorAll('#thread > .entry')].filter((e) => !e.hidden).map((e) => idOf(e.dataset.id))"
LISTED = "() => [...document.querySelectorAll('#history .h')].map((b) => idOf(b.dataset.id))"
SENT = "() => (window.__sent || []).filter((m) => m && /^(answer_|deleted_)/.test(m.type))"
TOAST = """() => { const el = $('toast');
  return { show: el.classList.contains('show'), text: el.querySelector('.msg')?.textContent.replace(/\\s+/g, ' ').trim() || '',
           key: el.querySelector('.btn')?.textContent.trim() || '', undo: el.dataset.undo ?? null }; }"""
# One answer's delete key: there, last of its head's keys, its word and its tooltip
KEY = """(id) => { const e = entryEl(id), k = e?.querySelector(':scope > .row.head [data-delete]');
  const tools = k?.closest('.tools');
  return { key: !!k, last: !!k && tools.lastElementChild === k, word: k?.textContent.trim() || '', title: k?.title || '',
           err: !!k?.closest('.errtop') }; }"""
MENU = "() => ({ hidden: $('open-deleted').hidden, word: $('open-deleted').firstElementChild.textContent.trim(), n: $('deleted-n').textContent })"
SHEET = """() => ({ open: !$('deleted-overlay').hidden, lede: $('deleted-lede').textContent,
  rows: [...document.querySelectorAll('#deleted-list .del-row')].map((li) => ({ id: idOf(li.dataset.id),
    kind: li.querySelector('.del-kind').textContent,
    name: (() => { const c = li.querySelector('.del-name').cloneNode(true); c.querySelectorAll('.sr-only').forEach((x) => x.remove()); return c.textContent.trim(); })(),
    star: !!li.querySelector('.h-star'), when: li.querySelector('.del-when').textContent,
    keys: [...li.querySelectorAll('button')].map((b) => b.textContent.trim()) })),
  listHidden: $('deleted-list').hidden, none: $('deleted-none').hidden ? '' : $('deleted-none').textContent,
  foot: !$('deleted-foot').hidden, focus: document.activeElement?.id || document.activeElement?.dataset?.restore && 'restore:' + document.activeElement.dataset.restore
    || document.activeElement?.dataset?.purge && 'purge:' + document.activeElement.dataset.purge || document.activeElement?.tagName })"""


def gone_row(i: int, ago: float = 60.0, days: float = 7, **more) -> dict:
    """An answer as /history/deleted gives it: when it was deleted, and when it goes by itself (None with no days)."""
    r = row(i, **more)
    at = time.time() - ago
    return {**r, "deleted": at, "until": at + days * DAY if days else None}


def deleted(p: Page, i, kept=True, n=1, can_ask=True, days=7) -> None:
    """The server's word that answer i was deleted, as every panel gets it. The stand-in's history first, as the server's
    is: the panel reads its days and Recently deleted's count again after the word, and a stand-in still holding the answer
    said none was deleted (the menu's key went, as a slow read made it now and then)."""
    now = p.js("() => serverNow()")
    stand = p.stand
    gone = [r for r in stand.rows if r["id"] == i]
    stand.rows = [r for r in stand.rows if r["id"] != i]
    if kept and gone and not any(r["id"] == i for r in stand.deleted):
        stand.deleted = [{**gone[0], "deleted": time.time(), "until": time.time() + days * DAY if days else None}] + stand.deleted
    p.send({"type": "answer_deleted", "id": i, "kept": kept, "until": now + days * DAY if kept and days else None, "n": n, "can_ask": can_ask})
    p.wait(150)


def restored(p: Page, i, answer, n=0, can_ask=True) -> None:
    """The server's word that answer i was put back, with the answer as the history keeps it (None for one it never held).
    The stand-in's history first, as above."""
    stand = p.stand
    stand.deleted = [r for r in stand.deleted if r["id"] != i]
    if answer is not None and not any(r["id"] == i for r in stand.rows):
        stand.rows = stand.rows + [{k: v for k, v in answer.items() if k not in ("deleted", "until")}]
    p.send({"type": "answer_restored", "id": i, "answer": answer, "n": n, "can_ask": can_ask})
    p.wait(200)


def clear_sent(p: Page) -> None:
    p.js("() => { window.__sent = []; }")


def hide_toast(p: Page) -> None:
    p.js("() => { $('toast').classList.remove('show'); }")


def press(p: Page, i) -> None:
    """A click on answer i's delete key."""
    p.page.locator(f'.entry[data-id="{i}"] [data-delete]').first.click()
    p.wait(80)


def open_sheet(p: Page) -> None:
    """Recently deleted, from the menu, as a person opens it."""
    p.page.click("#more")
    p.wait(100)
    p.page.click("#open-deleted")
    p.wait(250)


def group_key(br, s):
    if not T.group("the delete key"):
        return
    rows = [row(100 + i, ["essay", "mcq", "work", "coding"][i], f"문제 {i}", "답", "풀이", ago=600 - i * 30) for i in range(4)]
    p = Page(br, s, rows)
    k = p.js(KEY, 103)
    check("a finished answer has a delete key, the last of its head's keys", k["key"] and k["last"] and k["word"] == "삭제", k)
    check("...whose tooltip says it stays seven days in Recently deleted, to put back", k["title"] == "삭제 · 최근 삭제에 7일 남아 되살릴 수 있음", k["title"])
    p.answer(200, "essay", "새 문제", "답", "풀이", final=False)
    p.wait(150)
    check("an answer still being written has none", not p.js(KEY, 200)["key"], p.js(KEY, 200))
    p.done(200, "TYPE: essay\nANSWER: 답\nASKED: 새 문제\n\n풀이")
    p.wait(150)
    check("...and has one once it is finished", p.js(KEY, 200)["key"], p.js(KEY, 200))
    p.send({"type": "error", "id": 300, "text": "boom", "hint": ""})
    p.wait(150)
    k = p.js(KEY, 300)
    check("an error has one too, on its title's line, saying it only leaves the page", k["key"] and k["err"] and k["title"] == "화면에서 지우기", k)
    p.answer(310, "essay", "멈출 문제", "답", "반쯤", final=False)
    p.send({"type": "analysis_cancelled", "id": 310, "reason": "pause"})
    p.wait(150)
    k = p.js(KEY, 310)
    check("and one stopped part way, which the history does not keep either", k["key"] and k["title"] == "화면에서 지우기", k)
    clear_sent(p)
    press(p, 102)
    got = p.js(SENT)
    check("a press asks the server to delete it, by its id", got == [{"type": "answer_delete", "id": 102}], got)
    check("...and the card stays until the server says it is deleted", 102 in p.js(SHOWN), p.js(SHOWN))
    press(p, 102)
    check("pressed again before the server answered, nothing more goes", len(p.js(SENT)) == 1, p.js(SENT))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_gone(br, s):
    if not T.group("deleted, and Undo"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", f"답{i}", "풀이", ago=600 - i * 30) for i in range(4)]
    p = Page(br, s, rows)
    clear_sent(p)
    press(p, 102)
    deleted(p, 102, n=1)
    check("the server's word takes the card from the notebook, the others in their order", p.js(SHOWN) == [100, 101, 103], p.js(SHOWN))
    check("...and from the contents", p.js(LISTED) == [103, 101, 100], p.js(LISTED))
    tt = p.js(TOAST)
    check("the panel it was pressed in says so: Recently deleted keeps it seven days, with Undo",
          tt["show"] and "삭제함" in tt["text"] and "최근 삭제에 7일 보관" in tt["text"] and tt["key"] == "되돌리기", tt)
    m = p.js(MENU)
    check("the menu's Recently deleted is there, with how many it holds", not m["hidden"] and m["word"] == "최근 삭제" and m["n"] == "1", m)
    p.page.click("#toast")
    p.wait(100)
    check("Undo asks the server to put it back", p.js(SENT)[-1] == {"type": "answer_restore", "id": 102}, p.js(SENT))
    check("...and the notice goes", not p.js(TOAST)["show"], p.js(TOAST))
    restored(p, 102, rows[2], n=0)
    check("put back, it is where it was, between the answers before and after it", p.js(SHOWN) == [100, 101, 102, 103], p.js(SHOWN))
    check("...listed again, and flashing as a card gone to does", 102 in p.js(LISTED) and p.js("() => entryEl(102).classList.contains('flash')"),
          [p.js(LISTED), p.js("() => entryEl(102).className")])
    check("...with its answer as it was", "답2" in p.js("() => entryEl(102).querySelector('.answer-text').textContent"))
    check("Recently deleted holds none now: its key in the menu goes", p.js(MENU)["hidden"], p.js(MENU))
    hide_toast(p)
    deleted(p, 101, n=1)
    check("deleted from another panel, the card goes here too", 101 not in p.js(SHOWN), p.js(SHOWN))
    check("...with no notice here: Undo is the other panel's", not p.js(TOAST)["show"], p.js(TOAST))
    # The keyboard: the delete key pressed with Enter, the focus on to the next card's key, and z for Undo
    clear_sent(p)
    p.js("() => entryEl(100).querySelector('[data-delete]').focus()")
    p.page.keyboard.press("Enter")
    p.wait(80)
    check("Enter on the delete key asks the same", p.js(SENT) == [{"type": "answer_delete", "id": 100}], p.js(SENT))
    deleted(p, 100, n=2)
    focus = p.js("() => { const k = document.activeElement; return k?.dataset?.delete != null ? idOf(k.dataset.delete) : k?.tagName; }")
    check("as the card goes the keyboard goes to the same key of the card now in its place", focus == 102, focus)
    held = p.js("""() => { const e = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
                           document.activeElement.dispatchEvent(e); return e.defaultPrevented; }""")
    check("Enter held down does not go on to delete that one", held, held)
    p.page.keyboard.press("z")
    p.wait(100)
    check("z is Undo while the notice offers it", p.js(SENT)[-1] == {"type": "answer_restore", "id": 100}, p.js(SENT))
    restored(p, 100, rows[0], n=1)
    check("...and the answer is back first in the notebook", p.js(SHOWN)[:1] == [100], p.js(SHOWN))
    back = p.js("""() => { const k = document.activeElement, r = entryEl(100)?.getBoundingClientRect();
      return { key: k?.dataset?.delete != null ? idOf(k.dataset.delete) : k?.tagName, seen: !!r && r.top >= -1 && r.top < innerHeight }; }""")
    check("...the keyboard on its own Delete key, not the next card's, and the answer in view", back == {"key": 100, "seen": True}, back)
    p.js("() => document.activeElement.blur()")
    p.page.keyboard.press("z")
    p.wait(100)
    tt = p.js(TOAST)
    check("z with no Undo offered says there is nothing to undo, and sends nothing", tt["text"] == "되돌릴 것 없음" and p.js(SENT)[-1]["type"] == "answer_restore", tt)
    check("the keys' sheet lists z", "z" in p.js("() => [...document.querySelectorAll('#keys kbd')].map((k) => k.textContent)"))
    press(p, 103)
    deleted(p, 103, n=2)
    check("(a notice offers Undo)", p.js(TOAST)["undo"] == "103", p.js(TOAST))
    open_sheet(p)
    check("Recently deleted opened takes the notice away: its Restore does the same, and the notice stood over its title",
          not p.js(TOAST)["show"] and p.js(TOAST)["undo"] is None, p.js(TOAST))
    p.page.keyboard.press("Escape")
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    s.deleted = []                 # the stand-in's Recently deleted as the next group finds it, as the other groups leave it


def group_last(br, s):
    if not T.group("the last answer"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", "답", "풀이", ago=600 - i * 30) for i in range(3)]
    p = Page(br, s, rows)
    p.answer(200, "essay", "마지막 문제", "답", "풀이")
    p.wait(150)
    asks = "() => document.querySelectorAll('.row.asks:not(.practice)').length"
    check("(the last answer has the keys that ask more)", p.js(asks) == 1, p.js(asks))
    p.send({"type": "analysis_start", "id": 201, "trigger": "ask", "about": 200, "transcript": "왜 그런가", "ts": time.time()},
           {"type": "delta", "id": 201, "text": "TYPE: followup\nANSWER: 이유\n\n쓰는 중"})
    p.wait(150)
    check("(a question about it is being answered)", p.js("() => entryEl(200).querySelectorAll('[data-turn]').length") == 1)
    press(p, 200)
    deleted(p, 200, n=1, can_ask=False)
    check("the last answer deleted: its card goes, with the question under it", p.js(SHOWN) == [100, 101, 102], p.js(SHOWN))
    check("...the question box has nothing to ask about, and no answer offers the keys that ask more",
          p.js("() => $('ask').disabled") and p.js(asks) == 0, [p.js("() => $('ask').disabled"), p.js(asks)])
    n_items = p.js("() => items.size")
    p.send({"type": "delta", "id": 201, "text": " 더"}, {"type": "analysis_done", "id": 201, "text": "TYPE: followup\nANSWER: 이유\n\n끝", "usage": {}})
    p.send({"type": "analysis_start", "id": 202, "trigger": "retry", "about": 200, "transcript": "", "ts": time.time()})
    p.send({"type": "error", "id": 200, "text": "late", "hint": ""})
    p.wait(150)
    check("messages still on their way about it draw no card: the question's end, a retry, an error",
          p.js("() => items.size") == n_items and p.js(SHOWN) == [100, 101, 102], [p.js("() => [...items.keys()]"), p.js(SHOWN)])
    p.page.click("#toast")
    p.wait(80)
    back = {**row(200, "essay", "마지막 문제", "답", "풀이"), "turns": [{"id": 201, "q": "왜 그런가", "text": "TYPE: followup\nANSWER: 이유\n\n끝"}]}
    restored(p, 200, back, n=0, can_ask=True)
    check("Undo: it is the last answer again, with the question answered under it",
          p.js(SHOWN)[-1] == 200 and p.js("() => entryEl(200).querySelectorAll('[data-turn]').length") == 1, p.js(SHOWN))
    check("...and the question box asks about it again, with the keys that ask more",
          not p.js("() => $('ask').disabled") and p.js(asks) == 1, [p.js("() => $('ask').disabled"), p.js(asks)])
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_unkept(br, s):
    if not T.group("a card the history never held"):
        return
    p = Page(br, s, [row(100, "essay", "문제", "답", "풀이", ago=300)])
    p.send({"type": "error", "id": 300, "text": "boom", "hint": ""})
    p.wait(150)
    clear_sent(p)
    press(p, 300)
    check("an error's delete key asks the server too", p.js(SENT) == [{"type": "answer_delete", "id": 300}], p.js(SENT))
    deleted(p, 300, kept=False, n=0)
    tt = p.js(TOAST)
    check("...gone, said to have left the page only, with Undo", 300 not in p.js(SHOWN) and "화면에서 지움" in tt["text"] and tt["key"] == "되돌리기", tt)
    check("...and Recently deleted, which never held it, still has no key in the menu", p.js(MENU)["hidden"], p.js(MENU))
    p.page.click("#toast")
    p.wait(80)
    restored(p, 300, None, n=0)
    check("Undo brings back the card this page showed, its message and all",
          300 in p.js(SHOWN) and "boom" in p.js("() => entryEl(300).textContent"), p.js(SHOWN))
    # A stand-in for an earlier problem, under which a follow-up was answered: this page's alone
    p.send({"type": "analysis_start", "id": 400, "trigger": "ask", "about": 999, "transcript": "앞 문제는", "ts": time.time()})
    p.done(400, "TYPE: followup\nANSWER: 그것\n\n풀이")
    p.wait(150)
    stand_in = p.js("() => thread.find((id) => typeof id === 'string')")
    check("(a follow-up about a problem this page never had stands under a stand-in)", stand_in == "p400", stand_in)
    clear_sent(p)
    p.page.locator('.entry[data-id="p400"] [data-delete]').click()
    p.wait(100)
    check("the stand-in's delete key sends nothing: it goes from this page alone",
          p.js(SENT) == [] and "p400" not in p.js(SHOWN) and "화면에서 지움" in p.js(TOAST)["text"], [p.js(SENT), p.js(SHOWN)])
    p.page.click("#toast")
    p.wait(150)
    check("...and Undo puts it back, its follow-up under it", "p400" in p.js(SHOWN)
          and p.js("() => entryEl('p400').querySelectorAll('[data-turn]').length") == 1, p.js(SHOWN))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_sheet(br, s):
    if not T.group("Recently deleted"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", "답", "풀이", ago=900 - i * 30) for i in range(2)]
    s.deleted = [gone_row(500, ago=60, kind="mcq", asked="지운 객관식", key="③"),
                 gone_row(501, ago=3 * DAY, kind="coding", asked="", key="", body="첫 문장이 이름이 됨. 다음 문장", starred=True),
                 gone_row(502, ago=6.5 * DAY, kind="work", asked="오래된 것")]
    p = Page(br, s, rows)
    p.page.click("#more")
    p.wait(100)
    m = p.js(MENU)
    check("the menu offers Recently deleted with how many it holds, read when the page opens", not m["hidden"] and m["n"] == "3", m)
    p.page.click("#open-deleted")
    p.wait(250)
    sh = p.js(SHEET)
    check("it opens a sheet, the menu closed, the keyboard on its close key", sh["open"] and p.js("() => $('menu').hidden") and sh["focus"] == "deleted-close", sh)
    check("...saying how long a deleted answer stays", sh["lede"] == "삭제한 답은 7일 뒤 완전히 삭제됨 · 메뉴의 기록 지우기로도 지워짐", sh["lede"])
    check("...a row each, the latest deleted first, each named as the contents name it",
          [(r["id"], r["kind"], r["name"]) for r in sh["rows"]] == [(500, "선다형", "지운 객관식"), (501, "코딩", "첫 문장이 이름이 됨."), (502, "실무", "오래된 것")],
          [(r["id"], r["kind"], r["name"]) for r in sh["rows"]])
    check("...with when each goes for good", [r["when"].split(" · ")[-1] for r in sh["rows"]] == ["7일 뒤 완전히 삭제", "4일 뒤 완전히 삭제", "하루 안에 완전히 삭제"],
          [r["when"] for r in sh["rows"]])
    check("...a starred one with its star, and every one with Restore and Delete for good",
          [r["star"] for r in sh["rows"]] == [False, True, False] and all(r["keys"] == ["되살리기", "완전히 삭제"] for r in sh["rows"]), sh["rows"])
    clear_sent(p)
    p.page.locator('#deleted-list [data-restore="500"]').click()
    p.wait(80)
    check("Restore asks the server to put it back", p.js(SENT) == [{"type": "answer_restore", "id": 500}], p.js(SENT))
    back = s.deleted.pop(0)
    s.rows = s.rows + [{k: v for k, v in back.items() if k not in ("deleted", "until")}]
    restored(p, 500, s.rows[-1], n=2)
    p.wait(200)
    sh = p.js(SHEET)
    check("put back: its row goes from the sheet, and the keyboard goes to the same key of the row in its place",
          [r["id"] for r in sh["rows"]] == [501, 502] and sh["focus"] == "restore:501", [sh["rows"], sh["focus"]])
    check("...the answer is in the notebook, and the notice offers the way to it",
          500 in p.js(SHOWN) and p.js(TOAST)["text"] == "되살림" and p.js(TOAST)["key"] == "답으로", [p.js(SHOWN), p.js(TOAST)])
    p.page.click("#toast")
    p.wait(300)
    check("...which closes the sheet and goes there", p.js("() => $('deleted-overlay').hidden") and p.js("() => viewId") == 500,
          [p.js("() => $('deleted-overlay').hidden"), p.js("() => viewId")])
    open_sheet(p)
    # Delete for good asks twice, as Clear history does, and a double click is not the second press
    clear_sent(p)
    purge = p.page.locator('#deleted-list [data-purge="502"]')
    purge.click()
    p.wait(50)
    armed = p.js("() => { const b = document.querySelector('[data-purge=\"502\"]'); return [b.textContent.trim(), b.classList.contains('on')]; }")
    check("Delete for good asks first: its words and colour change, nothing goes", armed == ["한 번 더 누르면 삭제", True] and p.js(SENT) == [], [armed, p.js(SENT)])
    tone = p.js("""() => { const i = document.createElement('i'); i.style.color = 'var(--warn)'; document.body.append(i); const w = getComputedStyle(i).color; i.remove();
      return [getComputedStyle(document.querySelector('[data-purge="502"]')).color, w]; }""")
    check("...in the colour Clear history takes when it asks", tone[0] == tone[1], tone)
    purge.click()
    p.wait(50)
    check("...the second half of a double click is not the second press", p.js(SENT) == [], p.js(SENT))
    p.wait(700)
    purge.click()
    p.wait(80)
    check("...the second press deletes it for good", p.js(SENT) == [{"type": "answer_purge", "id": 502}], p.js(SENT))
    s.deleted = [r for r in s.deleted if r["id"] != 502]
    p.send({"type": "deleted_cleared", "id": 502, "gone": 1, "n": 1})
    p.wait(250)
    check("...and its row goes", [r["id"] for r in p.js(SHEET)["rows"]] == [501], p.js(SHEET)["rows"])
    clear_sent(p)
    p.page.click("#deleted-empty")
    p.wait(50)
    check("Empty asks first too", p.js("() => $('deleted-empty').textContent.trim()") == "한 번 더 누르면 비움" and p.js(SENT) == [])
    p.wait(700)
    p.page.click("#deleted-empty")
    p.wait(80)
    check("...and empties it on the second press", p.js(SENT) == [{"type": "deleted_clear"}], p.js(SENT))
    s.deleted = []
    p.send({"type": "deleted_cleared", "id": None, "gone": 1, "n": 0})
    p.wait(250)
    sh = p.js(SHEET)
    check("emptied: the sheet says nothing is deleted, and has nothing to empty", sh["listHidden"] and sh["none"] == "삭제한 답 없음" and not sh["foot"], sh)
    # While it is open the page's letters do nothing behind it; the keyboard stays in it; Escape closes it
    view = p.js("() => viewId")
    p.page.keyboard.press("j")
    p.wait(100)
    check("j does nothing behind the sheet", p.js("() => viewId") == view and sh["open"])
    for _ in range(4):
        p.page.keyboard.press("Tab")
    inside = p.js("() => $('deleted').contains(document.activeElement)")
    check("the keyboard stays inside the sheet", inside, p.js("() => document.activeElement?.id || document.activeElement?.tagName"))
    p.page.keyboard.press("Escape")
    p.wait(150)
    check("Escape closes it, the keyboard back on the gear it was opened from",
          p.js("() => $('deleted-overlay').hidden") and p.js("() => document.activeElement?.id") == "more", p.js("() => document.activeElement?.id"))
    check("Recently deleted empty and closed: its key leaves the menu", p.js(MENU)["hidden"], p.js(MENU))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # With no days set an answer stays until emptied, and the words say so
    s.deleted_days = 0
    s.deleted = [gone_row(600, ago=40 * DAY, days=0, asked="오래 둔 것")]
    p = Page(br, s, rows)
    check("with no days set the delete key says it stays until emptied",
          p.js(KEY, 101)["title"] == "삭제 · 비울 때까지 최근 삭제에 남아 되살릴 수 있음", p.js(KEY, 101)["title"])
    open_sheet(p)
    sh = p.js(SHEET)
    check("...and so do the sheet and its row", sh["lede"].startswith("삭제한 답은 비울 때까지 남음") and sh["rows"][0]["when"].endswith("비울 때까지 보관"),
          [sh["lede"], sh["rows"]])
    p.page.mouse.click(5, 300)   # the veil, beside the sheet
    p.wait(150)
    check("a press on the veil closes it", p.js("() => $('deleted-overlay').hidden"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    s.deleted_days, s.deleted = 7, []


def group_practice(br, s):
    if not T.group("Practice"):
        return
    # An answer Practice keeps back is named by its question alone in Recently deleted, as in the contents: never its answer line
    s.deleted = [gone_row(700, asked="", key="정답은 42", body="풀이")]
    p = Page(br, s, [row(100, ago=300)])
    p.js("() => { practiceSince = Date.now() - 1000; practiceCards.set('700', 0); }")
    open_sheet(p)
    name = p.js(SHEET)["rows"][0]["name"]
    check("an answer Practice keeps back shows no answer line in Recently deleted", "42" not in name and name == "연습으로 가린 답", name)
    p.close()
    s.deleted = []


def group_clear(br, s):
    if not T.group("Clear history"):
        return
    rows = [row(100 + i, ago=600 - i * 30) for i in range(3)]
    s.deleted = [gone_row(800)]
    p = Page(br, s, rows)
    press(p, 101)
    deleted(p, 101, n=2)
    check("(the notice offers Undo)", p.js(TOAST)["undo"] == "101", p.js(TOAST))
    p.js("() => { clearArmed = Date.now() - 1000; document.getElementById('clear').click(); }")   # its second press, a second after the first
    p.wait(250)
    check("Clear history takes Recently deleted too: its key leaves the menu", p.js(MENU)["hidden"], p.js(MENU))
    check("...and the Undo still offered goes, as nothing is left to put back", not p.js(TOAST)["show"] or p.js(TOAST)["undo"] is None, p.js(TOAST))
    p.close()
    s.deleted = []


def group_away(br, s):
    if not T.group("deleted while away"):
        return
    rows = [row(100 + i, ago=600 - i * 30) for i in range(4)]
    p = Page(br, s, rows)
    check("(four answers shown)", p.js(SHOWN) == [100, 101, 102, 103], p.js(SHOWN))
    # Deleted from another panel while this page's connection was down: the server holds it in Recently deleted
    s.deleted = [{**gone_row(101), **{k: v for k, v in rows[1].items()}, "deleted": time.time() - 5, "until": time.time() + 7 * DAY}]
    s.rows = [r for r in rows if r["id"] != 101]
    p.drop()
    p.wait(2200)   # the page tries again after 1.5 s, and reads the history when it is back
    check("an answer deleted while the connection was down goes when it comes back", p.js(SHOWN) == [100, 102, 103], p.js(SHOWN))
    check("...quietly: Undo was the other panel's", not p.js(TOAST)["show"] or "삭제" not in p.js(TOAST)["text"], p.js(TOAST))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    s.deleted = []


def lum_contrast(p: Page, sel: str, bg_sel: str) -> float:
    """The contrast of an element's text against the sheet behind it, from their computed colours."""
    return p.js("""([a, b]) => {
      const rgb = (c) => { const m = c.match(/[\\d.]+/g).map(Number); return c.startsWith('color(') ? m.slice(0, 3).map((x) => x * 255) : m.slice(0, 3); };
      const lum = (c) => { const v = rgb(c).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
      const fg = getComputedStyle(document.querySelector(a)).color, bg = getComputedStyle(document.querySelector(b)).backgroundColor;
      const [x, y] = [lum(fg), lum(bg)].sort((m, n) => n - m);
      return (x + 0.05) / (y + 0.05); }""", [sel, bg_sel])


def group_look(br, s):
    if not T.group("how it looks"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", "답", "풀이", ago=900 - i * 30) for i in range(3)]
    many = [gone_row(900 + i, ago=60 + i * 600, kind=["mcq", "coding", "work", "essay"][i % 4], asked=f"지운 문제 {i} " + "긴 이름 " * (i % 3))
            for i in range(30)]
    for theme in ("dark", "light"):
        s.deleted = many
        p = Page(br, s, rows, w=1600, h=1000, theme=theme)
        k = p.js("""() => { const k = entryEl(102).querySelector('[data-delete]'), c = entryEl(102).querySelector('[data-copy-item]');
          const a = k.getBoundingClientRect(), b = c.getBoundingClientRect(); return [a.width, a.height, a.left - b.right]; }""")
        check(f"{theme}: the delete key is a key of the head's size, a little apart from Copy all", k[0] == 28 and k[1] == 28 and 8 <= k[2] <= 14, k)
        p.page.hover('.entry[data-id="102"] [data-delete]')
        p.wait(150)
        hover = p.js("() => [getComputedStyle(entryEl(102).querySelector('[data-delete]')).color, getComputedStyle(document.body).getPropertyValue('--bad').trim()]")
        bad = p.js("(c) => { const i = document.createElement('i'); i.style.color = c; document.body.append(i); const v = getComputedStyle(i).color; i.remove(); return v; }", hover[1])
        check(f"{theme}: under the pointer it takes the colour of what breaks", hover[0] == bad, [hover, bad])
        p.page.mouse.move(5, 5)
        open_sheet(p)
        box = p.js("() => { const r = $('deleted').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom, innerWidth, innerHeight]; }")
        check(f"{theme}: the sheet stands in the window", box[0] >= 0 and box[1] <= box[4] and box[3] <= box[5], box)
        lay = p.js("""() => { const li = document.querySelector('#deleted-list .del-row'), n = li.querySelector('.del-text').getBoundingClientRect(),
          k = li.querySelector('.del-keys').getBoundingClientRect(); return [k.left >= n.right, Math.abs((k.top + k.bottom) / 2 - (n.top + li.querySelector('.del-when').getBoundingClientRect().bottom) / 2) < 8]; }""")
        check(f"{theme}: a row's keys stand at the right of its words, level with them", lay == [True, True], lay)
        scroll = p.js("() => { const l = $('deleted-list'); return [l.scrollHeight > l.clientHeight, getComputedStyle(l).overflowY]; }")
        check(f"{theme}: thirty rows scroll inside the sheet, which stays in the window", scroll == [True, "auto"], scroll)
        for sel, what in (('#deleted-list .del-row:nth-child(1) .del-kind', "a kind"), ('#deleted-list .del-row:nth-child(2) .del-kind', "another kind"),
                          ('#deleted-list .del-row:nth-child(3) .del-kind', "a third kind"), ('#deleted-list .del-name', "the name"),
                          ('#deleted-list .del-when', "when it goes"), ('#deleted-list [data-restore]', "Restore"),
                          ('#deleted-list [data-purge]', "Delete for good"), ('#deleted-lede', "the words under the title")):
            c = lum_contrast(p, sel, "#deleted")
            check(f"{theme}: {what} reads at 4.5:1 or more on the sheet ({c:.2f})", c >= 4.5, c)
        m = p.js("""() => { $('deleted-overlay').hidden = true; toggleMenu(true); const it = $('open-deleted').getBoundingClientRect(),
          n = $('deleted-n').getBoundingClientRect(); const r = [n.right <= it.right && n.left > it.left + 40, getComputedStyle($('open-deleted'), '::before').maskImage || getComputedStyle($('open-deleted'), '::before').webkitMaskImage];
          toggleMenu(false); return r; }""")
        check(f"{theme}: the menu's key has its count at its right, and a mark of its own", m[0] and "url(" in str(m[1]), m)
        check(f"{theme}: the page threw nothing", not p.errors, p.errors[:2])
        p.close()
    # A narrow window: the keys go under the words, and nothing runs past the window's edge
    s.deleted = many[:3]
    p = Page(br, s, rows, w=390, h=820)
    open_sheet(p)
    lay = p.js("""() => { const li = document.querySelector('#deleted-list .del-row'); const n = li.querySelector('.del-when').getBoundingClientRect(),
      k = li.querySelector('.del-keys').getBoundingClientRect(), r = $('deleted').getBoundingClientRect();
      return [k.top >= n.bottom - 1, r.right <= innerWidth, document.documentElement.scrollWidth <= innerWidth]; }""")
    check("390 px: a row's keys go under its words, the sheet in the window, nothing sideways", lay == [True, True, True], lay)
    p.page.keyboard.press("Escape")
    p.wait(100)
    press(p, 101)
    deleted(p, 101, n=4)
    tb = p.js("() => { const r = $('toast').getBoundingClientRect(); return [r.left >= 0, r.right <= innerWidth, r.top >= 0]; }")
    check("390 px: the notice with Undo stands in the window", tb == [True, True, True], tb)
    p.close()
    # A low window (a laptop at 200 %): the sheet's close key in view as it opens, and the list scrolled to Empty
    s.deleted = many
    p = Page(br, s, rows, w=1280, h=500)
    open_sheet(p)
    low = p.js("""() => { const c = $('deleted-close').getBoundingClientRect(); $('deleted-empty').scrollIntoView({ block: 'nearest' });
      const e = $('deleted-empty').getBoundingClientRect(); return [c.top >= 0 && c.bottom <= innerHeight, e.top >= 0 && e.bottom <= innerHeight]; }""")
    check("500 px high: the close key in view as it opens, and Empty reached", low == [True, True], low)
    p.close()
    s.deleted = []


def group_english(br, s):
    if not T.group("English"):
        return
    s.deleted = [gone_row(950, asked="a deleted question", key="B")]
    p = Page(br, s, [row(100, "essay", "a question", "A", "working", ago=300)], locale="en-US")
    k = p.js(KEY, 100)
    check("English: the delete key and its tooltip", k["word"] == "Delete" and k["title"] == "Delete · it stays 7 days in Recently deleted, to put back", k)
    press(p, 100)
    deleted(p, 100, n=2)
    tt = p.js(TOAST)
    check("English: the notice and its Undo", "Deleted" in tt["text"] and "in Recently deleted for 7 days" in tt["text"] and tt["key"] == "Undo", tt)
    open_sheet(p)
    sh = p.js(SHEET)
    words = [sh["lede"], *(r["when"] for r in sh["rows"]), *(x for r in sh["rows"] for x in r["keys"]),
             p.js("() => $('deleted-title').textContent"), p.js("() => $('deleted-empty').textContent.trim()")]
    check("English: the sheet's words, with no Hangul", not any(HANGUL.search(w) for w in words) and "Empty" in words and "Restore" in words, words)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    s.deleted = []


def main() -> int:
    support.need_vendor(h.PANEL)
    s = Stand("delete")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_key, group_gone, group_last, group_unkept, group_sheet, group_practice, group_clear, group_away, group_look, group_english):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
