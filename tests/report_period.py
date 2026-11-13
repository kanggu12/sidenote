"""./sidenote report: the period's numbers by engine, the agent's cost split, the GPU and the example checks, in one
order whatever the language, and in the terminal's words for them in English and in Korean; the answers marked right
or wrong in the panel, each by its last mark, by engine, by how the problem came and by type, and in the table of days;
no row for a day of the server's own events alone, a period of fewer than one day refused, and no log folder said as
./sidenote events says it.

    .venv/bin/python tests/report_period.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


now = time.time() - 60
ev = []
for i, (eng, ft) in enumerate([("agent", 5.0), ("agent", 7.0), ("agent", 9.0), ("agent", 60.0), ("local", 40.0)]):
    ev.append({"ts": now - i, "event": "analysis_done", "type": "algorithm", "engine": eng, "trigger": "screen",
               "first_token": ft, "elapsed": ft + 10, "cost_usd": 0.1 if eng == "agent" else None})
# spoken questions, the local model's logged first: the lines come out by engine and way in all the same
ev += [{"ts": now, "event": "analysis_done", "type": "short", "engine": eng, "trigger": "voice", "first_token": ft,
        "elapsed": ft + 3} for eng, ft in (("local", 4.0), ("agent", 3.0))]
ev += [{"ts": now, "event": "analysis_done", "type": "none", "engine": "agent", "cost_usd": 0.05} for _ in range(4)]
ev += [{"ts": now, "event": "analysis_done", "type": "none", "engine": "local"} for _ in range(3)]
ev += [{"ts": now, "event": "analysis_done", "type": "", "engine": "agent", "first_token": 100.0, "cost_usd": 3.5}]
ev += [{"ts": now, "event": "gpu_busy"}, {"ts": now, "event": "gpu_busy"},
       {"ts": now, "event": "analysis_error", "hint": "timeout"},
       # the first pass's own limit run out (a load that never finished), counted a timeout too; an agent failure this PC's
       # model then answered, which is no error of an answer; the model's loads and a cold model's first silence
       {"ts": now, "event": "gpu_busy", "after": "timeout"}, {"ts": now, "event": "agent_error"},
       {"ts": now, "event": "model_load", "model": "sidenote-gemma4:26b", "secs": 20.5, "ok": True},
       {"ts": now, "event": "model_load", "model": "sidenote-gemma4:26b", "secs": 180.0, "ok": False},
       {"ts": now, "event": "local_cold", "model": "sidenote-gemma4:26b", "limit": 45},
       {"ts": now, "event": "check", "passed": 3, "total": 3}, {"ts": now, "event": "check", "passed": 0, "total": 4},
       {"ts": now, "event": "check", "none": True}, {"ts": now, "event": "check", "skipped": "x"},
       # examples read off the screen and all left out (none of them in the problem's text), and one stuck model server
       {"ts": now, "event": "check", "none": True, "read": 3, "kept": 0, "heading": False},
       {"ts": now, "event": "local_stuck", "model": "sidenote-gemma4:26b", "waited": 80.2, "unloaded": True},
       {"ts": now, "event": "local_stuck", "model": "sidenote-gemma4:26b", "waited": 81.0, "unloaded": False},
       # the spend brake holding: not an error, but where to look for why nothing was solved
       {"ts": now, "event": "agent_brake", "reason": "six empty answers in a row", "hour_usd": 0.4}]
with tempfile.TemporaryDirectory() as d:
    Path(d, "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
    os.environ["SIDENOTE_LOG_DIR"] = d
    from server import report
    from server.i18n import t
    report.LOG_DIR = Path(d)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1", "--json"])
    got = json.loads(out.getvalue())
    p = got.get("period") or {}
    ft = p.get("first_token", {})
    # the panel's Report and GET /api/v1/report read the same numbers through report_data, from the folder the server names
    report.LOG_DIR = Path(tempfile.mkdtemp(prefix="sidenote-other-"))
    same = json.loads(json.dumps(report.report_data(1, Path(d)), ensure_ascii=False))
    report.LOG_DIR = Path(d)
    check("report_data gives what --json prints, read from the folder it is given", same == got, json.dumps(same, ensure_ascii=False)[:300])
    by = {(f["engine"], f["trigger"]): f for f in p.get("first_token_by", [])}
    check("...and the first tokens with the engine and the way in as keys, for the panel to name",
          by.get(("agent", "screen")) == {"engine": "agent", "trigger": "screen", "n": 5, "p50": 9.0, "p90": 100.0}
          and by.get(("local", "screen"), {}).get("p50") == 40.0, json.dumps(p.get("first_token_by"), ensure_ascii=False))
    check("first tokens by engine, the median and the slow tenth",
          ft.get("에이전트, 화면") == {"n": 5, "p50": 9.0, "p90": 100.0}
          and ft.get("이 PC의 모델, 화면") == {"n": 1, "p50": 40.0, "p90": 40.0}, json.dumps(ft, ensure_ascii=False))
    # sorted by the translated words, Korean once put each engine's speech before its screens
    ways = [f"{t(e)}, {t(w)}" for e in ("Agent", "Local model") for w in ("screen", "speech")]
    check("...in one order: each engine's screens, then its spoken questions", list(ft) == ways,
          json.dumps(list(ft), ensure_ascii=False))
    c = p.get("cost_usd", {})
    check("the agent's cost split: answers, screens with nothing to solve, answers with no head",
          c.get("answers") == 0.4 and c.get("empty") == 0.2 and c.get("empty_turns") == 4
          and c.get("headless") == 3.5 and c.get("headless_turns") == 1, json.dumps(c))
    check("an answer's errors only in the day's Errors: not an agent failure the local model then answered",
          (got.get("days") or [{}])[0].get("errors") == {"timeout": 1}, json.dumps(got.get("days")))
    check("the model's loads, the time they took, and a cold model's first silence",
          p.get("model_loads") == 2 and p.get("model_load_secs") == 200.5 and p.get("local_cold") == 1,
          json.dumps({k: p.get(k) for k in ("model_loads", "model_load_secs", "local_cold")}))
    check("GPU busy, local timeouts (the first pass's own limit among them) and the checks' verdicts",
          p.get("gpu_busy") == 3 and p.get("local_timeouts") == 2
          and p.get("checks") == {"passed": 1, "failed": 1, "no_examples": 2, "left_out": 1, "skipped": 1},
          json.dumps(p.get("checks")))
    check("a model server started again because it answered nothing, apart from one that could not be taken off",
          p.get("local_stuck") == 1 and p.get("local_stuck_failed") == 1, f"{p.get('local_stuck')} {p.get('local_stuck_failed')}")
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1"])
    text = out.getvalue()
    check("the table shows the period too", "기간 전체" in text and "풀 것 없음 $0.20 (4번)" in text, text[-300:])
    check("...the column of what had nothing to solve named for screens and speech both, and the loads said",
          text.splitlines()[0].count("풀 것 없음") == 1 and "빈 화면" not in text
          and "모델 올림 2번(200.5초), 올린 직후 첫 침묵 1번" in text, text[:200] + " ... " + text[-300:])
    check("...the stuck model and the examples left out among those with none",
          "멈춰서 다시 올림 1번(내리지 못함 1)" in text and "예제 없음 2(읽었지만 문제 글에 없어 뺌 1)" in text, text[-300:])
    check("...the first token by one name, the table's seconds with their unit",
          "첫 토큰" in text and "첫글자" not in text and "첫 글자" not in text and re.search(r"\d초 ", text) is not None,
          text[:400])
    # The same in English, as a terminal set to it prints it (its own process: the language is read once, at import)
    en = subprocess.run([sys.executable, "-m", "server.report", "report", "--days", "1"], cwd=ROOT, capture_output=True,
                        text=True, env={**os.environ, "SIDENOTE_LOG_DIR": d, "SIDENOTE_LANG": "en",
                                        "PYTHONIOENCODING": "utf-8"}).stdout
    lines = [line.strip() for line in en.splitlines() if line.strip().startswith("First token  ")]
    check("in English the same order, the first token by its name, and each count said to be answers",
          [line.split("   answers")[0].removeprefix("First token").strip() for line in lines]
          == ["Agent, screen", "Agent, speech", "Local model, screen", "Local model, speech"]
          and "answers   5   median 9.0 s" in en and "First character" not in en, en[-700:])
    day = next((line for line in en.splitlines() if re.match(r"\d{4}-\d\d-\d\d ", line)), "")
    check("...the table's medians in seconds, an aside after a number spaced, and answers with no head line named",
          "First token (median)" in en and re.search(r"\d s  ", day) is not None
          and "no examples 2 (read but not in the problem's text, left out: 1)" in en
          and "stuck and loaded again: 1 (could not be taken off: 1)" in en
          and "answers with no head line $3.50 (count 1)" in en, en[-700:])
    check("...and in English the column is Nothing to solve, and the loads are said",
          "Nothing to solve" in en.splitlines()[0] and "Empty screens" not in en
          and "model loads 2 (200.5 s), first silences after a load 1" in en, en[:200] + " ... " + en[-400:])
    # `./sidenote events --errors`: the failures, and the times work was held back (the spend brake, a stuck model
    # server), not the answers
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["events", "--errors", "-n", "50"])
    lines = out.getvalue().splitlines()
    kinds = [next((w for w in ("analysis_error", "agent_brake", "local_stuck", "analysis_done") if w in l), "") for l in lines]
    check("events --errors lists the errors, the spend brake and the stuck model server, and no answers",
          kinds.count("analysis_error") == 1 and kinds.count("agent_brake") == 1 and kinds.count("local_stuck") == 2
          and "analysis_done" not in kinds, str(kinds))

print("[answers marked right or wrong]")
# Marks as the server writes them (server/app.py, the "verdict" message), today and yesterday. Each answer counts once, by its
# last mark, on the day that mark was given: 101 and 108 changed their minds, 104 was taken off ("none"), 105 is the agent as
# it was logged while it could only be Claude, 106 says nothing of where it came from, and three lines are not marks at all
yesterday = now - 86400
mark = lambda i, v, at, engine=None, kind=None, trigger=None: {  # noqa: E731
    "ts": at, "event": "verdict", "id": i, "verdict": v, **({"engine": engine} if engine else {}),
    **({"type": kind} if kind else {}), **({"trigger": trigger} if trigger else {}), "model": "m"}
marks = [mark(107, "right", yesterday, "local", "coding", "screen"), mark(108, "wrong", yesterday + 1, "agent", "mcq", "screen"),
         mark(109, "wrong", yesterday + 2, "local", "coding", "screen"),
         mark(101, "wrong", now - 50, "local", "coding", "screen"), mark(101, "right", now - 40, "local", "coding", "screen"),
         mark(102, "right", now - 39, "agent", "mcq", "screen"), mark(103, "wrong", now - 38, "agent", "mcq", "voice"),
         mark(104, "right", now - 37, "local", "essay", "voice"), mark(104, "none", now - 36, "local", "essay", "voice"),
         mark(105, "wrong", now - 35, "claude", "algorithm", "screen"), mark(106, "right", now - 34),
         mark(108, "right", now - 33, "agent", "mcq", "screen"),
         {"ts": now - 32, "event": "verdict", "id": "110", "verdict": "right"}, {"ts": now - 31, "event": "verdict", "verdict": "wrong"},
         mark(111, "maybe", now - 30, "local", "coding", "screen"),
         {"ts": now - 29, "event": "analysis_done", "type": "coding", "engine": "local", "trigger": "screen", "elapsed": 3.0}]
day_of = lambda ts: time.strftime("%Y-%m-%d", time.localtime(ts))  # noqa: E731


def cell(head: str, line: str, name: str) -> str:
    """What a row of the table holds under one heading: the word ending where the heading ends, as the table's numbers stand
    right-aligned under theirs. Counted in terminal columns, where Hangul takes two; nothing when no word ends there."""
    end = report._width(head[:head.find(name) + len(name)]) if name in head else 0
    return line[:end].split()[-1] if end and line[:end].strip() and line[end:end + 1] in ("", " ") else ""


with tempfile.TemporaryDirectory() as d:
    Path(d, "events.jsonl").write_text("\n".join(json.dumps(e) for e in marks) + "\n", encoding="utf-8")
    report.LOG_DIR = Path(d)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "2", "--json"])
    got = json.loads(out.getvalue())
    v = (got.get("period") or {}).get("verdicts") or {}
    check("each answer once, by its last mark: 8 judged, 5 right (one taken off, and what is not a mark, left out)",
          v.get("judged") == 8 and v.get("right") == 5, json.dumps(v))
    check("...by engine: the agent (as Claude too), this PC's model, and one that does not say, in that order",
          list((v.get("by_engine") or {}).items()) == [("agent", {"judged": 4, "right": 2}), ("local", {"judged": 3, "right": 2}),
                                                       ("unknown", {"judged": 1, "right": 1})], json.dumps(v.get("by_engine")))
    check("...by how the problem came: the screen, speech, and one that does not say",
          list((v.get("by_trigger") or {}).items()) == [("screen", {"judged": 6, "right": 4}), ("voice", {"judged": 1, "right": 0}),
                                                        ("unknown", {"judged": 1, "right": 1})], json.dumps(v.get("by_trigger")))
    check("...by type, the most judged first",
          list((v.get("by_type") or {}).items()) == [("coding", {"judged": 3, "right": 2}), ("mcq", {"judged": 3, "right": 2}),
                                                     ("algorithm", {"judged": 1, "right": 0}), ("unknown", {"judged": 1, "right": 1})],
          json.dumps(v.get("by_type")))
    days = {r["day"]: (r.get("judged"), r.get("right")) for r in got.get("days") or []}
    check("...and each day the marks given on it: 108 changed today counts today, not yesterday",
          days.get(day_of(yesterday)) == (2, 1) and days.get(day_of(now)) == (6, 4), days)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "2"])
    text = out.getvalue()
    head = text.splitlines()[0]
    rows = {line[:10]: line for line in text.splitlines() if re.match(r"\d{4}-\d\d-\d\d ", line)}
    check("in Korean the table has its column, right/judged on each day, under its heading",
          cell(head, rows.get(day_of(now), ""), "맞음/채점") == "4/6" and cell(head, rows.get(day_of(yesterday), ""), "맞음/채점") == "1/2",
          text[:400])
    check("...and the period says them all, by engine, by where the problem came from and by type",
          "맞음/채점  전체 5/8 (63%)   에이전트 2/4 (50%)   이 PC의 모델 2/3 (67%)   기록 없음 1/1 (100%)" in text
          and "맞음/채점, 출처별  화면 4/6 (67%)   음성 0/1 (0%)   기록 없음 1/1 (100%)" in text
          and "맞음/채점, 유형별  coding 2/3 (67%)   mcq 2/3 (67%)   algorithm 0/1 (0%)   기록 없음 1/1 (100%)" in text, text[-700:])
    en = subprocess.run([sys.executable, "-m", "server.report", "report", "--days", "2"], cwd=ROOT, capture_output=True,
                        text=True, env={**os.environ, "SIDENOTE_LOG_DIR": d, "SIDENOTE_LANG": "en", "PYTHONIOENCODING": "utf-8"}).stdout
    en_rows = {line[:10]: line for line in en.splitlines() if re.match(r"\d{4}-\d\d-\d\d ", line)}
    check("in English the same",
          cell(en.splitlines()[0], en_rows.get(day_of(yesterday), ""), "Right/judged") == "1/2"
          and "Right/judged  all 5/8 (63%)   Agent 2/4 (50%)   Local model 2/3 (67%)   not recorded 1/1 (100%)" in en
          and "Right/judged by source  screen 4/6 (67%)   speech 0/1 (0%)   not recorded 1/1 (100%)" in en
          and "Right/judged by type  coding 2/3 (67%)   mcq 2/3 (67%)   algorithm 0/1 (0%)   not recorded 1/1 (100%)" in en, en[-700:])
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["events", "-n", "50"])
    check("events shows each mark with its verdict, a mark taken off as none",
          "id=101  trigger=screen  type=coding  verdict=right" in out.getvalue()
          and "id=104  trigger=voice  type=essay  verdict=none" in out.getvalue(), out.getvalue()[-600:])
with tempfile.TemporaryDirectory() as d:   # a period with answers and no marks
    Path(d, "events.jsonl").write_text(json.dumps(marks[-1]) + "\n", encoding="utf-8")
    report.LOG_DIR = Path(d)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1"])
    text = out.getvalue()
    day = next((line for line in text.splitlines() if re.match(r"\d{4}-\d\d-\d\d ", line)), "")
    check("none marked: the period says so in a line, and the day's column has a dash",
          "맞음/채점  채점한 답 없음" in text and cell(text.splitlines()[0], day, "맞음/채점") == "-", text)

print("[days with nothing to count, and the command line]")
# A day whose events are only the server's own (it started, a setting changed, a capture program connected) has no row: a
# row of zeros hid "No records", here and in the panel's Report, which reads report_data too
own = [{"ts": now, "event": "server_start", "version": "x"}, {"ts": now, "event": "control", "action": "pause"},
       {"ts": now, "event": "capture_connect", "info": "capture/test"}, {"ts": now - 86400, "event": "server_start"}]
with tempfile.TemporaryDirectory() as d:
    Path(d, "events.jsonl").write_text("\n".join(json.dumps(e) for e in own) + "\n", encoding="utf-8")
    report.LOG_DIR = Path(d)
    check("days of the server's own events alone: no rows, in the panel's Report as in --json",
          report.report_data(7, Path(d))["days"] == [], report.report_data(7, Path(d))["days"])
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "7"])
    check("...and the table says there are no records", out.getvalue().strip() == t("No records in the last {n} day(s)", n=7),
          out.getvalue())
    Path(d, "events.jsonl").write_text("\n".join(json.dumps(e) for e in own + [marks[-1]]) + "\n", encoding="utf-8")
    check("...a day with an answer among them has its row", [r["day"] for r in report.report_data(7, Path(d))["days"]]
          == [day_of(now)], report.report_data(7, Path(d))["days"])
    # No period of none or fewer days: --days 0 and -3 were taken, and said there were no records in the last -3 days
    for days in ("0", "-3"):
        got = subprocess.run([sys.executable, "-m", "server.report", "report", "--days", days], cwd=ROOT, capture_output=True,
                             text=True, env={**os.environ, "SIDENOTE_LOG_DIR": d, "PYTHONIOENCODING": "utf-8"})
        check(f"--days {days} is refused, in the terminal's words, and nothing reported", got.returncode == 2
              and got.stdout == "" and t("not a whole number from {low}: {value}", low=1, value=days) in got.stderr,
              [got.returncode, got.stdout[-200:], got.stderr[-200:]])
    got = subprocess.run([sys.executable, "-m", "server.report", "events", "-n", "-1"], cwd=ROOT, capture_output=True,
                         text=True, env={**os.environ, "SIDENOTE_LOG_DIR": d, "PYTHONIOENCODING": "utf-8"})
    check("...and so is a count of events under 0 (-n 0 shows none)", got.returncode == 2 and got.stdout == ""
          and t("not a whole number from {low}: {value}", low=0, value="-1") in got.stderr, [got.returncode, got.stderr[-200:]])
# With no log folder, report says so as events does: it said there were no records, as if a folder had been read
gone = Path(tempfile.mkdtemp(prefix="sidenote-gone-")) / "logs"
report.LOG_DIR = gone
said = {}
for cmd in ("report", "events"):
    out = io.StringIO()
    with redirect_stdout(out):
        report.main([cmd])
    said[cmd] = out.getvalue().strip()
check("no log folder: report and events say the same, naming the folder",
      said["report"] == said["events"] == t("No log folder: {dir}", dir=gone), said)
print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
