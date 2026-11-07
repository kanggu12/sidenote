"""Reading an answer at a glance: what was heard, the summary, a folded answer, and the engines' cards.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_reading.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

What was heard came as one block of a minute's speech, and a summary of three sentences as one marked block: neither read at
a glance. A folded answer to a spoken question showed its summary alone, with nothing of what was asked, and a summary that
names a topic then reads as if the answer had been cut off. Checked here: what was heard is three sentences a paragraph,
its first lines when it is long and the whole on a press; folded, its end on one line where the answer has no question line
of its own; a summary of several sentences is its first sentence marked and the rest a line each, while "e.g." ends no
sentence; and the local model's and the agent's cards fold to their top line on their name, open at first, and stay
as they were left when the page comes again. The page is a copy of panel/ over the stand-in server of panel_harness.py. All
answers are made up.
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
HEARD = ("We run a few hundred nodes for training. A job is tightly coupled, so it goes as fast as the slowest node. "
         "One node at half speed holds the whole job back. So we check every node before it takes a job. "
         "We also watch it while the job runs, and drain it when it fails. Some faults clear with a reboot. "
         "So how would you find an unhealthy node before it joins a job? And then what?")
SUMMARY = ("Gate every node with health checks before it can take a job, e.g. a periodic check and a prolog right before the "
           "job starts. Watch it while jobs run and drain it on any failure. Requeue the job, then repair from the cheapest step up.")


def voice(i: int, ago: float, asked: str = "", key: str = SUMMARY, kind: str = "work") -> dict:
    """A spoken problem's answer as /history gives it: what was heard, and an ASKED line when the model wrote one."""
    r = row(i, kind, asked, key, "## Steps\n\nFirst check, then drain, then repair.", ago=ago)
    r.update(trigger="voice", transcript=HEARD)
    return r


def group_heard_and_summary(br, s) -> None:
    rows = [voice(1, 4000), voice(2, 3000, asked="노드를 어떻게 걸러 내는지 묻는다"), row(3, ago=2000), row(4, ago=1000),
            voice(5, 10)]
    p = Page(br, s, rows, w=1440, h=1000, theme="light", settle=700, locale="en-US", query="?lang=en")
    p.send(support.settings_message())
    p.wait(500)
    got = p.js("""() => { const e = document.querySelector('.entry[data-id="5"]') || [...document.querySelectorAll('.entry')].pop();
      const box = e.querySelector('.heard-text'), key = e.querySelector('[data-heard-more]');
      const mark = e.querySelector('[data-aval]'), more = [...e.querySelectorAll('.ans-more > span')].map((x) => x.textContent);
      return { paras: box ? box.querySelectorAll('p').length : 0, clamp: box?.classList.contains('clamp'), short: box ? box.clientHeight < box.scrollHeight : null,
               key: !!key, mark: mark?.textContent, more }; }""")
    check("what was heard is three sentences a paragraph", got["paras"] == 3, str(got))
    check("...a long one shows its first lines, with a key for the whole", got["clamp"] and got["short"] and got["key"], str(got))
    check("a summary of several sentences: the first marked, the rest a line each", (got["mark"] or "").startswith("Gate every node")
          and (got["mark"] or "").endswith("starts.") and len(got["more"]) == 2 and got["more"][0].startswith("Watch it"), str(got))
    check("...and e.g. ends no sentence", "e.g. a periodic check" in (got["mark"] or ""), str(got))
    opened = p.js("""() => { const e = [...document.querySelectorAll('.entry')].pop(), key = e.querySelector('[data-heard-more]');
      key.click(); const box = e.querySelector('.heard-text');
      return { open: box.classList.contains('open'), whole: Math.abs(box.clientHeight - box.scrollHeight) < 2, pressed: key.getAttribute('aria-expanded') }; }""")
    check("...and the key shows it whole", opened["open"] and opened["whole"] and opened["pressed"] == "true", str(opened))
    folded = p.js("""() => [...document.querySelectorAll('.entry.folded')].map((e) => {
      const tail = e.querySelector('.heard-tail'), shown = (x) => !!x && getComputedStyle(x).display !== 'none' && x.offsetParent !== null;
      return { tail: shown(tail) ? tail.textContent : null, asked: shown(e.querySelector('[data-asked]')), more: shown(e.querySelector('.ans-more')) }; })""")
    no_q, with_q = (folded[0], folded[1]) if len(folded) >= 2 else ({}, {})
    check("folded, an answer with no question line shows the end of what was heard", no_q.get("tail") == "So how would you find an "
          "unhealthy node before it joins a job? And then what?", str(folded))
    check("...one with its question shows that, and not what was heard", with_q.get("asked") and with_q.get("tail") is None, str(folded))
    check("...and a folded summary is its point alone", not no_q.get("more") and not with_q.get("more"), str(folded))
    short = p.js("""() => { const e = [...document.querySelectorAll('.entry')].find((x) => x.dataset.id === '3') || document.querySelectorAll('.entry')[2];
      return { more: e.querySelectorAll('.ans-more').length }; }""")
    check("a one-line answer stays one line", short["more"] == 0, str(short))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_cards(br, s) -> None:
    p = Page(br, s, [row(1)], w=1440, h=1000, theme="dark", settle=700)
    p.send(support.settings_message())
    p.wait(400)
    start = p.js("""() => ['card-local', 'card-agent'].map((id) => { const c = document.getElementById(id), k = c.querySelector('[data-card-fold]');
      return { shut: c.classList.contains('shut'), key: !!k, pressed: k?.getAttribute('aria-expanded') }; })""")
    check("the local model's and the agent's cards have a fold key, and are open at first",
          all(c["key"] and not c["shut"] and c["pressed"] == "true" for c in start), str(start))
    line = p.js("""() => ['card-local', 'card-agent'].map((id) => { const k = document.getElementById(id).querySelector('[data-card-fold]');
      return { name: k.classList.contains('src-name'), mark: !!k.querySelector('.fold-mark'), role: k.getAttribute('role') }; })""")
    check("...the key is the card's name, with a mark for it", all(k["name"] and k["mark"] and k["role"] == "button" for k in line), str(line))
    p.js("() => document.querySelectorAll('[data-card-fold]').forEach((k) => k.click())")
    p.wait(200)
    shut = p.js("""() => ['card-local', 'card-agent'].map((id) => { const c = document.getElementById(id), seen = (sel) => [...c.querySelectorAll(sel)].some((x) => x.offsetParent !== null);
      return { shut: c.classList.contains('shut'), body: seen('.src-state') || seen('.usage') || seen('.gpu-viz'), top: seen('.src-top'),
               pressed: c.querySelector('[data-card-fold]').getAttribute('aria-expanded') }; })""")
    check("a press folds each to its top line", all(c["shut"] and not c["body"] and c["top"] and c["pressed"] == "false" for c in shut), str(shut))
    p.page.reload()
    p.wait(900)
    kept = p.js("() => ['card-local', 'card-agent'].map((id) => document.getElementById(id).classList.contains('shut'))")
    check("...and they stay folded when the page comes again", kept == [True, True], str(kept))
    p.js("() => document.querySelector('#card-local [data-card-fold]').click()")
    again = p.js("() => ['card-local', 'card-agent'].map((id) => document.getElementById(id).classList.contains('shut'))")
    check("...each on its own key", again == [False, True], str(again))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_edges(br, s) -> None:
    """Reading at its edges: a summary cut inside a **bold** pair showed its marks; Dr. ended a sentence; a
    folded card's tail showed the start of its last sentences and cut off the question at their end; the key for the whole of
    what was heard stood under a text that fit; a text opened whole closed again with any redraw of its entry; Korean heard
    words broke inside a word; the card name's tooltip lost the card's facts after one press."""
    if not T.group("reading at its edges"):
        return
    bold = ("**Yes. The node is drained before the job starts, so a failed check never reaches a running job.** It is "
            "repaired from the cheapest step up.")
    title = ("Dr. Kim checked the nodes on Monday and drained the two that failed, and the jobs moved to the others. Mr. Lee "
             "repaired them the next day.")
    fit300 = ("We run a few hundred nodes for training and a job goes as fast as its slowest node. We check every node before "
              "it takes a job and watch it while the job runs, draining it when it fails. How would you find an unhealthy node "
              "before it joins a job, and what would you do with it then, step by step?")   # over 280 characters, four lines here
    rows = [voice(1, 4000, key=bold), voice(2, 3000, key=title), voice(3, 2000), voice(4, 10)]
    rows[3]["transcript"] = fit300
    p = Page(br, s, rows, w=1440, h=1000, theme="light", settle=700, locale="en-US", query="?lang=en")
    p.send(support.settings_message())
    p.wait(400)
    marks = p.js("""() => [1, 2].map((i) => { const e = document.querySelector(`.entry[data-id="${i}"]`);
      e?.querySelector('[data-fold]')?.getAttribute('aria-expanded') === 'false' && e.querySelector('[data-fold]').click();
      const m = document.querySelector(`.entry[data-id="${i}"] [data-aval]`); return m ? m.textContent : null; })""")
    check("a summary whose point is in a **bold** pair is not cut inside it: no stray marks", marks[0] and "**" not in marks[0], str(marks[0]))
    check("...and Dr. or Mr. ends no sentence", (marks[1] or "").startswith("Dr. Kim checked") and len(marks[1] or "") > 12, str(marks[1]))
    fit = p.js("""() => { const b = document.querySelector('.entry[data-id="4"] .heard-text'), k = document.querySelector('.entry[data-id="4"] [data-heard-more]');
      return { clamp: b?.classList.contains('clamp'), key: k ? !k.hidden : null, wb: b ? getComputedStyle(b).wordBreak : null }; }""")
    check("what was heard that fits in its first lines shows whole, with no key for the rest", fit["clamp"] is False and not fit["key"], str(fit))
    check("...and its words break between words, as the answers' Korean does", fit["wb"] == "keep-all", str(fit))
    p.send({"type": "analysis_start", "id": 5, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": HEARD + " " + HEARD,
            "pages": 0, "trigger": "voice", "roi": None})
    p.done(5, "TYPE: work\nANSWER: 짧은 답\n\n풀이")
    p.wait(400)
    kept = p.js("""() => { const e = document.querySelector('.entry[data-id="5"]'), k = e?.querySelector('[data-heard-more]');
      if (!k || k.hidden) return { key: false }; k.click(); renderEntry(items.get(5));
      const b = document.querySelector('.entry[data-id="5"] .heard-text'); return { key: true, open: b?.classList.contains('open') }; }""")
    check("a text opened whole stays whole when its entry is drawn again", kept == {"key": True, "open": True}, str(kept))
    name = p.js("""() => { const n = document.querySelector('#card-local .src-name'), before = n?.title || ''; n?.click(); const after = n?.title || ''; n?.click();
      return { before, after }; }""")
    check("the card name's tooltip holds the card's facts and what a press does, before a press and after it",
          all(":" in name[k] and "\n" in name[k] for k in ("before", "after")) and name["before"] != name["after"], str(name)[:200])
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    p = Page(br, s, [voice(1, 4000), row(2, ago=3000), row(3, ago=2000), row(4, ago=1000), voice(5, 10)], w=390, h=844, theme="dark",
             settle=700, locale="en-US", query="?lang=en")
    p.send(support.settings_message())
    p.wait(400)
    tail = p.js("""() => [...document.querySelectorAll('.entry.folded .heard-tail')].filter((x) => x.offsetParent !== null).map((x) => {
      const r = x.getBoundingClientRect(), rg = document.createRange(); rg.selectNodeContents(x); const s = rg.getBoundingClientRect();   // where its words end, cut or not
      return { cut: x.scrollWidth > x.clientWidth + 1, endIn: s.right <= r.right + 1 }; })""")
    check("on a phone a folded card's tail keeps the end of what was heard, its start cut where the line runs out",
          bool(tail) and all(x["endIn"] for x in tail) and any(x["cut"] for x in tail), str(tail))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("reading")
        group_heard_and_summary(br, s)
        group_cards(br, s)
        group_edges(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
