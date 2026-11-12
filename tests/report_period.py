"""./sidenote report: the period's numbers by engine, the agent's cost split, the GPU and the example checks, in one
order whatever the language, and in the terminal's words for them in English and in Korean.

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
print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
