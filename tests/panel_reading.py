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


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("reading")
        group_heard_and_summary(br, s)
        group_cards(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
