"""./sidenote report: the period's numbers by engine, the agent's cost split, the GPU and the example checks.

    .venv/bin/python tests/report_period.py
"""
import io
import json
import os
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
ev += [{"ts": now, "event": "analysis_done", "type": "none", "engine": "agent", "cost_usd": 0.05} for _ in range(4)]
ev += [{"ts": now, "event": "analysis_done", "type": "none", "engine": "local"} for _ in range(3)]
ev += [{"ts": now, "event": "analysis_done", "type": "", "engine": "agent", "first_token": 100.0, "cost_usd": 3.5}]
ev += [{"ts": now, "event": "gpu_busy"}, {"ts": now, "event": "gpu_busy"},
       {"ts": now, "event": "analysis_error", "hint": "timeout"},
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
    report.LOG_DIR = Path(d)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1", "--json"])
    got = json.loads(out.getvalue())
    p = got.get("period") or {}
    ft = p.get("first_token", {})
    check("first words by engine, the median and the slow tenth",
          ft.get("에이전트 화면") == {"n": 5, "p50": 9.0, "p90": 100.0} and ft.get("이 PC 화면") == {"n": 1, "p50": 40.0, "p90": 40.0},
          json.dumps(ft, ensure_ascii=False))
    c = p.get("cost_usd", {})
    check("the agent's cost split: answers, screens with nothing to solve, answers with no head",
          c.get("answers") == 0.4 and c.get("empty") == 0.2 and c.get("empty_turns") == 4
          and c.get("headless") == 3.5 and c.get("headless_turns") == 1, json.dumps(c))
    check("GPU busy, local timeouts and the checks' verdicts",
          p.get("gpu_busy") == 2 and p.get("local_timeouts") == 1
          and p.get("checks") == {"passed": 1, "failed": 1, "no_examples": 2, "left_out": 1, "skipped": 1},
          json.dumps(p.get("checks")))
    check("a model server started again because it answered nothing, apart from one that could not be taken off",
          p.get("local_stuck") == 1 and p.get("local_stuck_failed") == 1, f"{p.get('local_stuck')} {p.get('local_stuck_failed')}")
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1"])
    text = out.getvalue()
    check("the table shows the period too", "기간 전체" in text and "풀 것 없는 화면 $0.20 (4번)" in text, text[-300:])
    check("...the stuck model and the examples left out among those with none",
          "멈춰서 다시 올림 1번(내리지 못함 1)" in text and "예제 없음 2(읽었지만 문제 글에 없어 뺌 1)" in text, text[-300:])
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
