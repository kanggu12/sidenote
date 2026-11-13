"""The Maintenance sheet (app.js, openMaint; the server's /api/v1/check, /report, /log, /log/server, /models and /backup).

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_maint.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

Checked: the gear menu opens it on its Checks with the keyboard on Close, Escape closes it and gives the keyboard back; the
log named apart from the answers kept; the checks drawn as the server words them, a pill a state, a fix with its command and
Copy, and a key to where the fix is done, its words saying where: a section of the sheet, a section of Solver settings, the
Capture connection or a switch on the page, each pressed (none for a place the panel does not know); no checks at all said;
the Report's period asked of the server, its answers, marks by engine, source and type, first tokens, spend with the parts
that make it up, the reasons analyses stopped in the server's words and the local model's troubles, the days the latest
first, a period with none said; the Log's failures and everything (each asked of the server as such), the newest first, a
failure in the bad colour, the server's log with a key that copies it; the Models with their marks, Remove asking twice
before it sends model_delete, the answer said and the list read again, Download sending llm_pull and the bar of a download
under way, also for a page opened while one runs, as the status or the list says it, and none left once it failed; a backup
asked of the server and saved under the name it gives, with what it holds said, and the way to put one back for where the
server runs; an answer the server could not give said in the warning colour, readable in both themes; the arrows between
the tabs; and at a phone's width nothing wider than the page, a command's words whole.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
SHOWN = "() => document.getElementById('maint-overlay')?.hidden === false"
NOW = time.time()
CHECKS = [
    {"id": "server", "name": "Sidenote 서버", "state": "ok", "said": "버전 0.9.1", "fix": "", "cmd": "", "go": ""},
    {"id": "capture", "name": "캡처 프로그램", "state": "bad", "said": "연결 안 됨", "fix": "서버 터미널에서 실행", "cmd": "./sidenote capture", "go": ""},
    {"id": "speech", "name": "음성 인식", "state": "off", "said": "서버에서 꺼짐", "fix": "", "cmd": "", "go": ""},
    {"id": "errors", "name": "오류", "state": "warn", "said": "최근 24시간에 2건", "fix": "로그에서 보기", "cmd": "", "go": "log"},
]
# fixes done outside the sheet, one of each kind of place the server names (go), and one the panel does not know
GOES = [
    {"id": "monitor", "name": "화면 캡처", "state": "warn", "said": "연결 뒤 화면 없음", "fix": "고른 모니터 확인", "cmd": "", "go": "settings:capture"},
    {"id": "agent", "name": "Claude Code", "state": "off", "said": "꺼 둠", "fix": "풀이 설정에서 켜기", "cmd": "", "go": "settings:agent"},
    {"id": "capture", "name": "캡처 프로그램", "state": "bad", "said": "연결 안 됨", "fix": "내 PC에서 시작", "cmd": "", "go": "connection"},
    {"id": "screen", "name": "화면 캡처", "state": "off", "said": "꺼 둠", "fix": "캡처 카드에서 켜기", "cmd": "", "go": "switch:sw-screen"},
    {"id": "later", "name": "다른 것", "state": "warn", "said": "확인 필요", "fix": "다른 곳에서", "cmd": "", "go": "elsewhere:somewhere"},
]
# what the keys of GOES say, and where each leaves the keyboard or what it opens
GO_KEYS = "() => Object.fromEntries([...document.querySelectorAll('#maint-body .maint-check')].map((r) => [r.dataset.check, r.querySelector('[data-maint-go]')?.textContent ?? null]))"
WHERE = """() => ({ maint: document.getElementById('maint-overlay').hidden === false, settings: document.getElementById('settings-overlay').hidden === false,
  capture: document.getElementById('capture-overlay').hidden === false, tab: document.querySelector('#settings-body .set-tab[aria-selected="true"]')?.dataset.sec || '',
  focus: document.activeElement?.id || '' })"""
EVENTS = [{"ts": NOW - 10, "event": "agent_error", "id": 7, "error": "the plan's limit"},
          {"ts": NOW - 20, "event": "analysis_done", "id": 6, "engine": "local", "elapsed": 3.2}]
LINES = [f"2026 INFO sidenote.app line {i}" for i in range(5)]
MODELS = {"ok": True, "download": True, "pulling": None, "models": [
    {"name": "sidenote-gemma4:26b", "size": 18_000_000_000, "params": "26B", "quant": "Q4_K_M", "family": "gemma4", "loaded": True,
     "in_use": True, "present": True},
    {"name": "gemma4:e2b", "size": 4_600_000_000, "loaded": False, "in_use": False, "present": True},
    {"name": "sidenote-gemma4:e4b", "size_gb": 6.6, "present": False, "in_use": False, "loaded": False}]}
# two days of a report as server/report.py's report_data gives them: one with marks and a median, one with neither
REPORT = {"ok": True, "days": [
    {"day": "2026-01-01", "answers": 6, "empty": 1, "followups": 2, "cancelled": 1, "errors": {"timeout": 1}, "elapsed_median": 5.25,
     "first_token_median": 1.5, "cost_usd": 0.3, "types": {"code": 4}, "judged": 6, "right": 4},
    {"day": "2026-01-02", "answers": 4, "empty": 0, "followups": 0, "cancelled": 2, "errors": {}, "elapsed_median": None,
     "first_token_median": None, "cost_usd": 0.0, "types": {}, "judged": 0, "right": 0}],
    "period": {"first_token": {"에이전트, 화면": {"n": 6, "p50": 1.5, "p90": 3.0}},
               "first_token_by": [{"engine": "agent", "trigger": "screen", "n": 6, "p50": 1.5, "p90": 3.0},
                                  {"engine": "local", "trigger": "voice", "n": 2, "p50": 0.8, "p90": 1.25}],
               "cost_usd": {"answers": 0.25, "followups": 0.05, "empty": 0.0, "empty_turns": 0, "headless": 0.0, "headless_turns": 0},
               "gpu_busy": 2, "local_timeouts": 0, "local_stuck": 1, "cancelled": {"superseded": 2, "pause": 1},
               "verdicts": {"judged": 6, "right": 4, "by_engine": {"agent": {"judged": 4, "right": 3}, "local": {"judged": 2, "right": 1}},
                            "by_trigger": {"screen": {"judged": 6, "right": 4}}, "by_type": {"coding": {"judged": 6, "right": 4}}}},
    "names": {"cancelled": {"superseded": "새 화면", "pause": "일시정지"}}}


def stand_api(s: Stand) -> None:
    s.api = {"GET /api/v1/check": (200, {"ok": True, "checks": CHECKS}, {}),
             "GET /api/v1/log": (200, {"ok": True, "events": EVENTS}, {}),
             "GET /api/v1/log/server": (200, {"ok": True, "lines": LINES}, {}),
             "GET /api/v1/models": (200, MODELS, {}),
             "GET /api/v1/report": (200, REPORT, {}),
             "POST /api/v1/backup": (200, b"\x1f\x8b fake archive bytes", {
                 "content-type": "application/gzip", "content-disposition": 'attachment; filename="sidenote-backup-20260102-030405.tar.gz"',
                 "x-sidenote-held": "history.sqlite .settings.json sidenote-backup.txt", "x-sidenote-left-out": "2"})}
    s.api_asked.clear()


def opened(p) -> None:
    """Opened as a person opens it: the gear, then its item"""
    p.page.click("#more")
    p.wait(150)
    if p.js("() => !!document.getElementById('open-maint')"):   # an older panel has none: its checks fail on what is not there
        p.page.click("#open-maint")
    p.page.wait_for_timeout(200)


def tab(p, sec: str) -> None:
    p.js(f"() => document.querySelector('#maint-body [data-maint-sec=\"{sec}\"]')?.click()")
    p.page.wait_for_timeout(300)


def group_open(br, s) -> None:
    if not T.group("the way in and out"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    got = p.js("""() => ({ shown: document.getElementById('maint-overlay')?.hidden === false, focus: document.activeElement?.id,
      tabs: [...document.querySelectorAll('#maint-body [data-maint-sec]')].map((t) => [t.dataset.maintSec, t.getAttribute('aria-selected')]),
      item: document.getElementById('open-maint')?.textContent })""")
    check("the gear menu's Maintenance opens it on its Checks, the keyboard on Close", got["shown"] and got["focus"] == "maint-close"
          and got["tabs"][0] == ["check", "true"] and [t[0] for t in got["tabs"]] == ["check", "report", "log", "models", "backup"]
          and got["item"] == "관리", got)
    # every item of the gear menu has its mark: one with none had the mark's square drawn filled in
    marks = p.js("""() => [...document.querySelectorAll('.menu .item')].filter((b) => !b.hidden).map((b) => [b.id,
      getComputedStyle(b, '::before').getPropertyValue('--m').trim() !== '' || getComputedStyle(b, '::before').maskImage !== 'none'])""")
    check("every item of the gear menu has its own mark, Maintenance's among them", marks and all(m for _, m in marks), marks)
    # 기록 is the answers kept (Clear history, a backup's history): the server's log is 로그 in its tab and the sheet's line
    words = p.js("""() => ({ tab: document.querySelector('#maint-body [data-maint-sec="log"]')?.textContent || '',
      lede: document.querySelector('#maint .lede')?.textContent || '', clear: document.getElementById('clear')?.textContent || '' })""")
    check("the log is 로그 in its tab and the sheet's line, 기록 left to the answers kept", words["tab"] == "로그"
          and words["lede"] == "점검, 보고서, 로그, 모델, 백업" and "기록" in words["clear"], words)
    p.page.keyboard.press("Escape")
    p.wait(150)
    check("Escape closes it and gives the keyboard back to the gear", not p.js(SHOWN) and p.js("() => document.activeElement.id") == "more",
          p.js("() => document.activeElement.id"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_checks(br, s) -> None:
    if not T.group("the checks"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-check').length > 0", timeout=4000)
    rows = p.js("""() => [...document.querySelectorAll('#maint-body .maint-check')].map((r) => ({ id: r.dataset.check,
      name: r.querySelector('.lbl').textContent, state: r.dataset.state, colour: r.querySelector('.pill').dataset.state, pill: r.querySelector('.pill').textContent,
      said: r.querySelector('.help').textContent, copy: r.querySelector('[data-copy]')?.dataset.copy || '',
      go: r.querySelector('[data-maint-go]')?.dataset.maintGo || '', key: r.querySelector('[data-maint-go]')?.textContent || '' }))""")
    check("a row a part, as the server words it, a pill a state", [r["id"] for r in rows] == ["server", "capture", "speech", "errors"]
          and [r["state"] for r in rows] == ["ok", "bad", "off", "warn"] and [r["pill"] for r in rows] == ["정상", "고칠 것", "꺼 둠", "확인 필요"]
          and rows[1]["said"] == "연결 안 됨", rows)
    check("...switched off on purpose in grey, as a card at rest: no fault", rows[2]["colour"] == "idle", rows[2])
    check("...a fix with its command and the key that copies it", rows[1]["copy"] == "./sidenote capture", rows[1])
    check("...and a key to the section the fix is in, named by it", rows[3]["go"] == "log" and rows[3]["key"] == "로그 열기", rows[3])
    p.js("() => document.querySelector('#maint-body [data-maint-go=\"log\"]').click()")
    p.page.wait_for_timeout(400)
    check("which opens it", p.js("() => document.querySelector('#maint-body [data-maint-sec=\"log\"]').getAttribute('aria-selected')") == "true")
    asked = [a[1] for a in s.api_asked if a[0] == "GET"]
    check("each section read from the server as it is shown", asked[:1] == ["/api/v1/check"] and "/api/v1/log" in asked
          and "/api/v1/log/server" in asked, asked)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # a server that lists no checks at all: said, where nothing under Check again read as a list on its way
    s.api["GET /api/v1/check"] = (200, {"ok": True, "checks": []}, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    p.page.wait_for_function("() => !!document.querySelector('#maint-body .maint-tools .when')", timeout=4000)   # read: its time is said
    said = p.js("() => [...document.querySelectorAll('#maint-body .set-pane > :not(.maint-tools)')].map((e) => [e.className, e.textContent])")
    check("no checks at all: said under Check again", said == [["cap", "점검할 것 없음"]], said)
    p.close()


def group_goes(br, s) -> None:
    """A fix done outside the sheet: its key says where it goes, and goes there, the sheet closed (one sheet at a time)."""
    if not T.group("a fix done elsewhere"):
        return
    stand_api(s)
    s.api["GET /api/v1/check"] = (200, {"ok": True, "checks": GOES}, {})

    def fresh():
        """Maintenance on its Checks, over a page that has the server's settings (their sections' names)"""
        p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
        p.send(support.settings_message())
        opened(p)
        p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-check').length > 0", timeout=4000)
        return p

    p = fresh()
    keys = p.js(GO_KEYS)
    capture = p.js("() => settingsMeta.sections.find(([s]) => s === 'capture')[1]")   # the Capture section's name, as its tab has it
    check("each key says where it goes: a section of Solver settings by its tab's name, the agent's by the agent's",
          keys.get("monitor") == f"풀이 설정의 {capture} 열기" and keys.get("agent") == "풀이 설정의 Claude 열기", keys)
    check("...the Capture connection, and a switch on the page by what it turns on", keys.get("capture") == "캡처 연결 열기"
          and keys.get("screen") == "화면 캡처 스위치로 이동", keys)
    check("...and a place the panel does not know has no key", keys.get("later") is None, keys)
    p.js("() => document.querySelector('#maint-body [data-check=\"monitor\"] [data-maint-go]')?.click()")   # none on an older panel: its checks fail on what is not there
    p.wait(300)
    got = p.js(WHERE)
    check("pressed: Solver settings opens on that section, the sheet closed", got["settings"] and not got["maint"] and got["tab"] == "capture", got)
    p.page.keyboard.press("Escape")
    p.wait(150)
    check("...and closed, the keyboard is back on the gear the sheet was opened from", p.js(WHERE)["focus"] == "more", p.js(WHERE))
    errors = list(p.errors)                                   # what each page threw, said once at the end
    p.close()
    p = fresh()
    p.js("() => document.querySelector('#maint-body [data-check=\"capture\"] [data-maint-go]')?.click()")
    p.wait(300)
    got = p.js(WHERE)
    check("the Capture connection's key opens it, the sheet closed", got["capture"] and not got["maint"], got)
    errors += p.errors
    p.close()
    p = fresh()
    p.js("() => document.querySelector('#maint-body [data-check=\"screen\"] [data-maint-go]')?.click()")
    p.wait(300)
    got = p.js(WHERE)
    check("a switch's key closes the sheet and puts the keyboard on that switch", not (got["maint"] or got["settings"] or got["capture"])
          and got["focus"] == "sw-screen", got)
    errors += p.errors
    check("the pages threw nothing", not errors, errors[:2])
    p.close()


def group_log(br, s) -> None:
    if not T.group("the log"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "log")
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-events li').length > 0", timeout=4000)
    got = p.js("""() => ({ ev: [...document.querySelectorAll('#maint-body .maint-events li')].map((li) => [li.querySelector('.ev').textContent,
        li.querySelector('.ev').classList.contains('err'), li.querySelector('.kv').textContent]),
      pressed: [...document.querySelectorAll('#maint-body [data-maint-failures]')].map((b) => [b.textContent, b.getAttribute('aria-pressed')]),
      log: document.querySelector('#maint-body pre.maint-log')?.textContent || '',
      copy: document.querySelector('#maint-body .maint-tools [data-copy]')?.dataset.copy || '' })""")
    check("the failures first, asked of the server as such", ("GET", "/api/v1/log", "limit=200&errors=1") in [a[:3] for a in s.api_asked]
          and got["pressed"] == [["실패만", "true"], ["전체", "false"]], [s.api_asked, got["pressed"]])
    check("the events as the server gives them, newest first, a failure in the bad colour", got["ev"][0][0] == "agent_error" and got["ev"][0][1]
          and not got["ev"][1][1] and "error=the plan's limit" in got["ev"][0][2], got["ev"])
    check("the server's log as it is written, and a key that copies it whole", got["log"] == "\n".join(LINES) and got["copy"] == "\n".join(LINES),
          got["log"][:80])
    p.js("() => document.querySelector('#maint-body [data-maint-failures=\"0\"]').click()")
    p.page.wait_for_timeout(400)
    check("Everything asks for every event", ("GET", "/api/v1/log", "limit=200") in [a[:3] for a in s.api_asked], s.api_asked)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_report(br, s) -> None:
    if not T.group("the report"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "report")
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-sum').length > 0", timeout=4000)
    got = p.js("""() => ({ rows: Object.fromEntries([...document.querySelectorAll('#maint-body .maint-sum')].map((r) => [r.dataset.sum,
        [r.querySelector('.lbl').textContent, r.querySelector('.num')?.textContent ?? '', r.querySelector('.help')?.innerText || '']])),
      days: [...document.querySelectorAll('#maint-body table.maint-days tbody tr')].map((tr) => [...tr.children].map((c) => c.textContent)),
      head: [...document.querySelectorAll('#maint-body table.maint-days thead th')].map((c) => c.textContent),
      pressed: [...document.querySelectorAll('#maint-body [data-maint-days]')].map((b) => [b.textContent, b.getAttribute('aria-pressed')]),
      agent: AG(), coding: TYPE_LABEL.coding, d1: fmtDay(new Date('2026-01-01T12:00:00').getTime()), d2: fmtDay(new Date('2026-01-02T12:00:00').getTime()) })""")
    r = got["rows"]
    check("the period asked of the server, seven days unless another is picked", ("GET", "/api/v1/report", "days=7") in [a[:3] for a in s.api_asked]
          and got["pressed"] == [["오늘", "false"], ["7일", "true"], ["30일", "false"]], [s.api_asked[-3:], got["pressed"]])
    check("the period's answers, and what else came: follow-ups, nothing to solve, cancels, errors",
          r.get("answers") == ["이 기간의 답", "10", "추가 질문 2 · 풀 것 없음 1 · 취소 3 · 오류 1"], r.get("answers"))
    check("the marks: right of judged with the share, then by engine, by source and by type",
          r.get("verdicts") == ["맞음/채점", "4/6(67%)", f"{got['agent']} 3/4(75%) · 이 PC의 모델 1/2(50%)\n화면 4/6(67%)\n{got['coding']} 4/6(67%)"]
          and got["coding"] != "coding",
          r.get("verdicts"))
    check("the first token of each engine and way in, its median and slow tenth",
          r.get("first") == ["첫 토큰", "", f"{got['agent']}, 화면: 중앙값 1.5초 · 느린 10% 3초 · 답 6개\n이 PC의 모델, 음성: 중앙값 0.8초 · 느린 10% 1.3초 · 답 2개"],
          r.get("first"))
    # each amount held to the word before it by a no-break space, so a narrow line never starts with one
    check("the spend, all of it, and what the answers, follow-ups and empty screens took of it",
          r.get("cost") == [f"{got['agent']} 비용", "$0.30", "답\u00a0$0.25 · 추가 질문\u00a0$0.050 · 풀 것 없음\u00a0$0"], r.get("cost"))
    check("why analyses stopped, in the server's words for each reason", r.get("cancelled") == ["답 전에 멈춤", "3", "새 화면 2 · 일시정지 1"],
          r.get("cancelled"))
    check("the local model's troubles, only those there were", r.get("local") == ["이 PC의 모델", "", "GPU 바쁨 2 · 멈춰서 다시 띄움 1"],
          r.get("local"))
    check("the days the latest first: answers, right of judged, the median, the spend", got["head"] == ["날짜", "답", "맞음", "응답", "비용"]
          and got["days"] == [[got["d2"], "4", "-", "-", "$0"], [got["d1"], "6", "4/6", "5.3초", "$0.30"]], [got["head"], got["days"]])
    p.js("() => document.querySelector('#maint-body [data-maint-days=\"30\"]').click()")
    p.page.wait_for_timeout(400)
    check("another period asks for it", ("GET", "/api/v1/report", "days=30") in [a[:3] for a in s.api_asked]
          and p.js("() => document.querySelector('#maint-body [data-maint-days=\"30\"]').getAttribute('aria-pressed')") == "true",
          s.api_asked[-2:])
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # a period with nothing in it, and one with answers none of which was marked
    s.api["GET /api/v1/report"] = (200, {"ok": True, "days": [], "period": {}, "names": {}}, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "report")
    p.page.wait_for_function("() => !!document.querySelector('#maint-body .set-pane .cap')", timeout=4000)
    check("a period with no records says so", p.js("() => document.querySelector('#maint-body .set-pane .cap').textContent") == "이 기간 기록 없음")
    p.close()
    unmarked = {**REPORT, "period": {**REPORT["period"], "verdicts": {"judged": 0, "right": 0, "by_engine": {}, "by_trigger": {}, "by_type": {}}}}
    s.api["GET /api/v1/report"] = (200, unmarked, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "report")
    p.page.wait_for_function("() => !!document.querySelector('#maint-body [data-sum=\"verdicts\"]')", timeout=4000)
    said = p.js("() => [...document.querySelectorAll('#maint-body [data-sum=\"verdicts\"] :is(.num, .help)')].map((e) => e.textContent)")
    check("...and with no answer marked, the way to mark one", said == ["-", "답 카드의 맞음·틀림으로 채점"], said)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # the agent paid for answers with no head line too (a refusal, a turn that ran away): the line names them, so its parts
    # make up the total, $0.25 + $0.05 + $0 + $0.05 of $0.35
    headless = {**REPORT, "days": [{**REPORT["days"][0], "cost_usd": 0.35}, REPORT["days"][1]],
                "period": {**REPORT["period"], "cost_usd": {**REPORT["period"]["cost_usd"], "headless": 0.05, "headless_turns": 1}}}
    s.api["GET /api/v1/report"] = (200, headless, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "report")
    p.page.wait_for_function("() => !!document.querySelector('#maint-body [data-sum=\"cost\"]')", timeout=4000)
    said = p.js("() => [...document.querySelectorAll('#maint-body [data-sum=\"cost\"] :is(.num, .help)')].map((e) => e.textContent)")
    check("the spend's parts add up to it: the answers with no head line named with the rest", said == ["$0.35", "답\u00a0$0.25 · 추가 질문\u00a0$0.050 · 풀 것 없음\u00a0$0 · 머리줄 없는 답\u00a0$0.050"], said)
    p.close()
    # English writes a day longer than Korean ("Fri, Nov 13" against "11.13(금)"): the days' table at a phone's width in it
    s.api["GET /api/v1/report"] = (200, {**REPORT, "days": [{**d, "day": f"2026-11-1{i}", "cost_usd": 0.534} for i, d in enumerate(REPORT["days"] * 3)]}, {})
    for width in (390, 360):
        p = Page(br, s, [row(1)], w=width, h=844, settle=500, locale="en-US", query="?lang=en")
        opened(p)
        tab(p, "report")
        p.page.wait_for_function("() => !!document.querySelector('#maint-body table.maint-days')", timeout=4000)
        # inside the pane's content box, where its words end (its right padding keeps the scroll bar's room), and nothing to scroll sideways
        wide = p.js("""() => { const pane = document.querySelector('#maint-body .set-pane'), box = pane.getBoundingClientRect();
          const edge = box.right - parseFloat(getComputedStyle(pane).paddingRight) - (pane.offsetWidth - pane.clientWidth);
          return { sideways: pane.scrollWidth - pane.clientWidth, out: [...document.querySelectorAll('#maint-body table.maint-days :is(th, td)')]
            .filter((e) => e.getBoundingClientRect().right > edge + 0.5).map((e) => e.textContent).slice(0, 4) }; }""")
        check(f"in English at {width} px the days' table stays inside the pane", wide["sideways"] <= 0 and not wide["out"], wide)
        p.close()


def group_models(br, s) -> None:
    if not T.group("the models"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "models")
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-model').length > 0", timeout=4000)
    rows = p.js("""() => [...document.querySelectorAll('#maint-body .maint-model')].map((r) => ({ name: r.querySelector('.name').textContent,
      marks: [...r.querySelectorAll('.marks .pill')].map((x) => x.textContent), help: r.querySelector('.help').textContent,
      key: r.querySelector('.ctl button')?.textContent || '' }))""")
    check("each model with its marks, its size and what it is", rows[0]["marks"] == ["쓰는 중", "GPU에 올라감"] and "16.8GB" in rows[0]["help"]
          and "Q4_K_M" in rows[0]["help"] and rows[1]["marks"] == [] and rows[0]["key"] == "지우기", rows)
    check("...the offered one not there with Download", rows[2]["key"] == "받기" and "받지 않음" in rows[2]["help"] and "6.6GB" in rows[2]["help"], rows[2])
    p.js("() => { window.__sent.length = 0; }")
    key = "#maint-body [data-maint-remove='gemma4:e2b']"
    p.page.click(key)
    p.wait(100)
    first = p.js("() => [window.__sent.filter((m) => m.type === 'model_delete').length, document.querySelector(\"#maint-body [data-maint-remove='gemma4:e2b']\").textContent]")
    p.wait(700)   # the confirming press is taken once its question could have been read (twoPress)
    p.page.click(key)
    p.wait(150)
    sent = p.js("() => window.__sent.filter((m) => m.type === 'model_delete')")
    check("Remove asks twice: the first press says so and sends nothing, the second sends model_delete",
          first == [0, "한 번 더 누르면 지움"] and sent == [{"type": "model_delete", "model": "gemma4:e2b"}], [first, sent])
    before = len([a for a in s.api_asked if a[1] == "/api/v1/models"])
    p.send({"type": "model_delete", "model": "gemma4:e2b", "ok": True})
    p.wait(400)
    after = len([a for a in s.api_asked if a[1] == "/api/v1/models"])
    check("...its answer said, and the list read again", "gemma4:e2b 지움" in p.js("() => document.getElementById('toast').textContent")
          and after == before + 1, [p.js("() => document.getElementById('toast').textContent"), before, after])
    p.js("() => { window.__sent.length = 0; document.querySelector(\"#maint-body [data-maint-pull='sidenote-gemma4:e4b']\").click(); }")
    check("Download sends llm_pull for it", p.js("() => window.__sent.filter((m) => m.type === 'llm_pull')") == [{"type": "llm_pull", "model": "sidenote-gemma4:e4b"}])
    p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "pulling", "completed": 30, "total": 100})
    p.wait(200)
    bar = p.js("() => [...document.querySelectorAll('#maint-body .maint-model')].pop().querySelector('.ctl').textContent")
    check("...and a download under way shows how far it is", bar == "받는 중 30%", bar)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # the local server not answering: said, as the server words it
    s.api["GET /api/v1/models"] = (503, {"ok": False, "error": "the local model server does not answer, or it is not Ollama"}, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "models")
    p.page.wait_for_timeout(300)
    said = p.js("() => document.querySelector('#maint-body .set-pane .cap.warn')?.textContent || ''")
    check("a list the server could not give: said", "does not answer" in said, said)
    p.close()


ROW_E4B = """() => { const r = [...document.querySelectorAll('#maint-body .maint-model')].find((x) => x.querySelector('.name').textContent === 'sidenote-gemma4:e4b');
  return { pill: r?.querySelector('[data-maint-pulling]')?.textContent || '', key: r?.querySelector('[data-maint-pull]')?.textContent || '',
           others: [...document.querySelectorAll('#maint-body [data-maint-pull]')].map((b) => b.disabled) }; }"""
UNDER_WAY = {"model": "sidenote-gemma4:e4b", "status": "pulling", "completed": 4, "total": 10}


def group_pulled_before(br, s) -> None:
    """A page opened while a download runs: the server says it in its status and in the list, before any progress comes (and
    none comes for minutes while a downloaded model is made ready)"""
    if not T.group("a download under way before the page opened"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send({"type": "status", "engines": {**h.ENGINES, "local": {**h.ENGINES["local"], "pulling": dict(UNDER_WAY)}}})
    opened(p)
    tab(p, "models")
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-model').length > 0", timeout=4000)
    got = p.js(ROW_E4B)
    check("said in the status alone: the model's pill shows how far it is, and no Download", got["pill"] == "받는 중 40%" and not got["key"], got)
    p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "failed", "error": "no space left"})
    p.page.wait_for_function("() => !!document.querySelector('#maint-body [data-maint-pull]')", timeout=4000)
    got = p.js(ROW_E4B)
    check("...failed: Download again, nothing left of it as under way", got["key"] == "받기" and not got["pill"] and got["others"] == [False], got)
    p.close()
    s.api["GET /api/v1/models"] = (200, {**MODELS, "pulling": dict(UNDER_WAY)}, {})
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    tab(p, "models")
    p.page.wait_for_function("() => document.querySelectorAll('#maint-body .maint-model').length > 0", timeout=4000)
    got = p.js(ROW_E4B)
    check("said in the list alone: the same", got["pill"] == "받는 중 40%" and not got["key"], got)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_unanswered(br, s) -> None:
    """What the server could not give, in the warning colour (as a setting's reason is), not a note's grey, readable in both
    themes"""
    if not T.group("an answer the server could not give"):
        return
    stand_api(s)
    for key in [k for k in s.api if k.startswith("GET ")]:
        s.api[key] = (500, {"ok": False, "error": "database is locked"}, {})
    for theme in ("light", "dark"):
        p = Page(br, s, [row(1)], w=1440, h=900, settle=500, theme=theme)
        opened(p)
        p.page.wait_for_function("() => !!document.querySelector('#maint-body .cap.warn')", timeout=4000)
        got = p.js("""() => { const said = document.querySelector('#maint-body .cap.warn'), pane = document.querySelector('#maint-body .set-pane');
          const probe = (css) => { const e = document.createElement('p'); e.className = css[0]; e.style.color = css[1]; pane.append(e);
            const c = getComputedStyle(e).color; e.remove(); return c; };
          const r = said.getBoundingClientRect();
          return { text: said.textContent, colour: getComputedStyle(said).color, warn: probe(['', 'var(--warn)']), note: probe(['cap', '']),
                   box: [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.right), Math.ceil(r.bottom)],
                   rgb: getComputedStyle(said).color.match(/[\\d.]+/g).map(Number) }; }""")
        ratio = h.contrast(got["rgb"], h.background_of(br, p.page.screenshot(), got["box"]))
        check(f"{theme}: the server's words, in the warning colour where a note is grey", got["text"] == "database is locked"
              and got["colour"] == got["warn"] and got["colour"] != got["note"], got)
        check(f"{theme}: ...read at 4.5:1 or better", ratio >= 4.5, f"{ratio:.2f}")
        check(f"{theme}: the page threw nothing", not p.errors, p.errors[:2])
        p.close()


def group_pulling(br, s) -> None:
    if not T.group("a download's progress"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "pulling", "completed": 1, "total": 10})
    opened(p)
    tab(p, "models")
    p.page.wait_for_function("() => !!document.querySelector('#maint-body [data-maint-remove]')", timeout=4000)
    p.js("() => document.querySelector('#maint-body [data-maint-remove=\"gemma4:e2b\"]').focus()")
    p.page.keyboard.press("Enter")                                # pressed once: armed, asking for a second press
    p.wait(100)
    before = p.js("() => { const b = document.querySelector('#maint-body [data-maint-remove=\"gemma4:e2b\"]'); window.__rm = b; return !!b.dataset.armed; }")
    for done in (3, 5, 7):                                         # the progress, as the server sends it twice a second
        p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "pulling", "completed": done, "total": 10})
        p.wait(120)
    got = p.js("""() => { const b = document.querySelector('#maint-body [data-maint-remove="gemma4:e2b"]');
      return { same: b === window.__rm, armed: !!b?.dataset.armed, focus: document.activeElement === b,
               pill: document.querySelector('#maint-body [data-maint-pulling]')?.textContent || '' }; }""")
    check("a download's progress: its words change where they are", got["pill"] == "받는 중 70%", got)
    check("...while a Remove pressed once stays armed, the keyboard on it", before and got["same"] and got["armed"] and got["focus"], [before, got])
    p.wait(600)                                                    # past the pause that tells a second press from a double click
    p.page.keyboard.press("Enter")                                 # the second press removes it
    p.wait(150)
    check("...so its second press sends model_delete", {"type": "model_delete", "model": "gemma4:e2b"} in p.js("() => window.__sent"),
          p.js("() => window.__sent.slice(-3)"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_backup(br, s) -> None:
    if not T.group("a backup"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send({"type": "status", "where": "container"})
    opened(p)
    tab(p, "backup")
    with p.page.expect_download(timeout=5000) as dl:
        p.page.click("#maint-body [data-maint='backup']")
    name = dl.value.suggested_filename
    p.wait(300)
    said = p.js("() => document.querySelector('#maint-body .set .cap')?.textContent || ''")
    check("Download asks the server for it, as JSON, and saves it under the name the server gives",
          name == "sidenote-backup-20260102-030405.tar.gz" and ("POST", "/api/v1/backup", "", "{}") in s.api_asked, [name, s.api_asked[-1:]])
    check("...saying what it holds and what was left out", "history.sqlite, .settings.json, sidenote-backup.txt" in said and "2" in said, said)
    cmd = p.js("() => document.querySelector('#maint-body [data-copy]')?.dataset.copy || ''")
    check("putting one back: the launcher's restore in the server's terminal, with Copy", cmd.startswith("./sidenote restore "), cmd)
    p.send({"type": "status", "where": "desktop"})
    p.wait(100)
    p.js("() => renderMaint()")
    p.wait(100)
    text = p.js("() => document.querySelector('#maint-body .set-pane').textContent")
    check("...and under the app, its data folder, with no command", "데이터 폴더" in text and not p.js("() => !!document.querySelector('#maint-body [data-copy]')"), text[-120:])
    s.api["POST /api/v1/backup"] = (409, {"ok": False, "error": "Nothing to back up yet: no history and no settings"}, {})
    p.page.click("#maint-body [data-maint='backup']")
    p.wait(400)
    check("a backup the server could not make: said", "Nothing to back up" in p.js("() => document.querySelector('#maint-body .cap.warn')?.textContent || ''"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_keys_and_phone(br, s) -> None:
    if not T.group("the keyboard and a phone's width"):
        return
    stand_api(s)
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    opened(p)
    p.js("() => document.querySelector('#maint-body [data-maint-sec=\"check\"]').focus()")
    p.page.keyboard.press("ArrowDown")
    p.wait(200)
    p.page.keyboard.press("ArrowDown")
    p.wait(200)
    check("the arrows go from tab to tab, the keyboard with them", p.js("() => document.activeElement?.dataset.maintSec") == "log"
          and p.js("() => document.querySelector('#maint-body [data-maint-sec=\"log\"]').getAttribute('aria-selected')") == "true")
    p.close()
    p = Page(br, s, [row(1)], w=390, h=844, settle=500)
    p.send({"type": "status", "where": "container"})
    opened(p)
    for sec in ("check", "report", "log", "models", "backup"):
        tab(p, sec)
        wide = p.js("""() => { const sheet = document.getElementById('maint').getBoundingClientRect();
          return { side: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                   out: [...document.querySelectorAll('#maint-body *')].filter((e) => { const r = e.getBoundingClientRect();
                     return r.width && (r.right > sheet.right + 1 || r.left < sheet.left - 1); }).map((e) => e.className || e.tagName).slice(0, 4) }; }""")
        check(f"at 390 px, {sec}: nothing wider than the sheet or the page", wide["side"] <= 0 and not wide["out"], wide)
        cut = p.js(h.CUT_PIECES, "#maint-body")
        check(f"...{sec}: a command's words whole, the line broken between them", not cut, cut)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("maint")
        group_open(br, s)
        group_checks(br, s)
        group_goes(br, s)
        group_report(br, s)
        group_log(br, s)
        group_models(br, s)
        group_pulling(br, s)
        group_pulled_before(br, s)
        group_backup(br, s)
        group_unanswered(br, s)
        group_keys_and_phone(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
