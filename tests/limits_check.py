"""What real use asked for after design note 88, each as a check (design note 89): why analyses stopped and what the
agent was paid for, readable from the log; this PC's model, switched off, answering for the agent at its limit; the
thinking pass's last sentence on the card; code run on made-up inputs when a problem shows no examples; and the paths
real use had never run (Codex's reset times and missing prices, the API agent's stop reasons,
a status code inside a request id, the chart's runner token).

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/limits_check.py
"""
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))   # the repository, one level up

from PIL import Image  # noqa: E402

from server import report  # noqa: E402
from server.agents import AnthropicApiAgent, CodexAgent, read_claude_turn  # noqa: E402
from server.analyzer import (FastResult, GpuPace, LocalLlmAnalyzer, LocalServerError, _json_or_empty, error_hint,  # noqa: E402
                             make_engines)
from server.checklangs.go import _go_value  # noqa: E402
from server.checklangs.java import _drop_public  # noqa: E402
from server.checklangs.python import _py_decl  # noqa: E402
from server.codecheck import _same, run_cases  # noqa: E402
from server.heads import head_of  # noqa: E402
from server.history import History  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.pipeline import Hooks, Outcome, Pipeline, Spend, check_code, limit_until, thought_line  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

PASS, FAIL = [], []
ROOT = Path(__file__).resolve().parent.parent


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


async def _none(*a, **k):
    return None


async def _yes(*a, **k):
    return True


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), "white").save(buf, "PNG")
    return buf.getvalue()


PNG = _png()


class Frame:
    """A screen as prepare_frame makes one (a blank one: what is on it is the mock models' to say)."""

    def __init__(self):
        self.full_png = PNG
        self.model_b64 = base64.b64encode(PNG).decode()
        self.thumb_url = "data:image/png;base64," + self.model_b64
        self.extra_b64, self.windows, self.ocr_lines, self.sig = [], None, None, b""
        self.width, self.height, self.ts = 1920, 1080, 0.0


def make_pipeline(notices, agent_ok=lambda: True):
    engines = make_engines(CONFIG)   # MockLocal and the mock agent

    async def notice(text):
        notices.append(text)
    hooks = Hooks(local_ok=lambda: True, agent_ok=agent_ok, notice=notice, stage=lambda *a, **k: _none(),
                  confirm=_yes, agent_failed=_none)
    return Pipeline(engines, hooks), engines


def the_log():
    print("\n[why analyses stopped and what the agent was paid for, from the log]")
    with tempfile.TemporaryDirectory() as d:
        now = time.time()
        rows = [
            {"event": "analysis_cancelled", "trigger": "screen", "reason": "superseded", "after": 1.2},
            {"event": "analysis_cancelled", "trigger": "screen", "reason": "superseded", "after": 14.0},
            {"event": "analysis_cancelled", "trigger": "screen"},                 # as older logs wrote them
            {"event": "analysis_repeat", "of": 41, "score": 0.81},
            {"event": "analysis_repeat", "of": 41, "score": 0.74},
            {"event": "analysis_done", "type": "none", "cost_usd": 0.05, "sent": "이어 붙인 문제 2장", "via": "handoff",
             "trigger": "screen"},
            {"event": "analysis_done", "type": "none", "cost_usd": 0.06, "sent": "문제 부분 화면 1600x900",
             "via": "kind", "trigger": "screen"},
            {"event": "analysis_done", "type": "none", "cost_usd": 0.04, "sent": "문제 글 300자", "via": "unknown",
             "trigger": "screen"},
            {"event": "analysis_done", "type": "none", "cost_usd": 0.04, "trigger": "voice"},   # from before via
            {"event": "check", "probe": True, "passed": 2, "total": 3},
            {"event": "check", "probe": True, "error": "컴파일 오류"},
        ]
        with open(os.path.join(d, "events.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"ts": now, **r}, ensure_ascii=False) + "\n")
        saved = report.LOG_DIR
        report.LOG_DIR = Path(d)
        try:
            p = report._period(now - 60)
            line = report._line({"ts": now, **rows[1], "id": 7})
        finally:
            report.LOG_DIR = saved
    check("events prints a cancel's reason and how long it had run", "reason=superseded" in line and "after=14.0" in line,
          line)
    check("report counts the cancels by reason, the old ones as unrecorded",
          p["cancelled"] == {"superseded": 2, "unknown": 1}, str(p["cancelled"]))
    check("...and how long the ones a newer screen replaced had run", p["superseded_after"]["over_10s"] == 1
          and p["superseded_after"]["total_s"] == 15, str(p["superseded_after"]))
    check("report counts the problems seen again, of how many answers, and the lowest score",
          p["repeats"] == {"n": 2, "answers": 1, "min": 0.74, "p50": 0.74}, str(p["repeats"]))
    check("the agent's turns that found nothing, by what it was given and why it got them",
          p["empty_by_sent"] == {"이어 붙인 문제": 1, "잘라 낸 화면": 1, "옮겨 적은 글": 1, "들은 말": 1}
          and p["empty_by_via"] == {"handoff": 1, "kind": 1, "unknown": 1, "none": 1},
          f"{p['empty_by_sent']} {p['empty_by_via']}")
    check("a run on made-up inputs is counted as a check without examples, apart",
          p["checks"].get("probe_failed") == 2 and p["checks"].get("no_examples") == 2 and not p["checks"].get("probe_ran"),
          str(p["checks"]))


def the_thought():
    print("\n[the thinking pass's last finished sentence, for the card]")
    t = thought_line("The knight moves in L shapes. We need **BFS** over the board.\nSo we start at")
    check("the last finished sentence, without its markdown, not the one being written",
          t == "We need BFS over the board.", repr(t))
    check("a tail with no finished sentence is shown as it is", thought_line("start the count") == "start the count")
    long = thought_line("A" * 400 + ".")
    check("cut at THOUGHT_LINE with an ellipsis", len(long) <= 160 and long.endswith("…"), str(len(long)))
    check("nothing for nothing", thought_line("") == "" and thought_line("  \n ") == "")


async def standing_in():
    print("\n[this PC's model, switched off, answers for the agent while it cannot]")
    saved = dict(SETTINGS.values)
    notices = []
    signed = {"ok": True}
    try:
        SETTINGS.values.update(local_llm=False, local_fallback=True, agent_mode="hard", agent_payload="crop",
                               agent_confirm=False, dedupe=False, roi=True, agent_hourly_usd=2.0)
        pipe, eng = make_pipeline(notices, agent_ok=lambda: signed["ok"])
        asked = []
        real = eng.agent.run

        async def agent_run(images, text, on_delta, web=False):
            asked.append(text)
            return await real(images, text, on_delta)
        eng.agent.run = agent_run

        async def fast(*a, **k):
            return FastResult(text=None, head="TYPE: algorithm\nROUTE: deep\nREGION: 20 120 500 560\n",
                              type="algorithm", route="deep")
        eng.local.fast = fast
        check("with the agent there, the switched-off model stays off", pipe._local() is None and not pipe.standing_in())
        pipe.spend.limited("claude CLI: You've hit your weekly limit · resets in 1 hour")
        check("at the agent's limit it stands in", pipe.standing_in() == "limit" and pipe._local() is eng.local)
        check("...and the settings that need it count as on (the thinking pass's own)",
              SETTINGS.on("local_llm") and not SETTINGS.get("local_llm"))
        out = await pipe.solve(61, Frame(), "", False, _none)
        check("...and the answer is its own, the agent not asked", out.engine == "local" and not asked,
              f"{out.engine} asked={len(asked)}")
        check("nothing for the panel's brake card to say: something answers", pipe.auto_blocked() == "",
              pipe.auto_blocked())
        SETTINGS.values["local_fallback"] = False
        check("with local_fallback off it does not stand in", pipe._local() is None)
        check("...and the agent's card says what would have it answer", "대신 풀기" in pipe.auto_blocked(),
              pipe.auto_blocked())
        SETTINGS.values["local_fallback"] = True
        pipe.spend.limit_until, pipe.spend.limit_kind = 0.0, ""
        signed["ok"] = False
        check("with the agent's sign-in gone it stands in", pipe.standing_in() == "signin")
        signed["ok"] = True
        pipe.spend.cool_until = time.time() + 300      # the cool-down: answers in a row that found nothing
        pipe.spend.ran = 5
        check("the cool-down after empty answers does not load it (the screens hold nothing)",
              pipe.standing_in() == "" and pipe._local() is None, pipe.standing_in())
        pipe.spend.cool_until = 0.0
        pipe.spend.spent.append((time.time(), 5.0))    # the hour's cost at the ceiling
        check("at the hourly cost ceiling it stands in", pipe.standing_in() == "brake")
        escalated = []

        async def fast_seen(*a, **k):
            escalated.append(k.get("escalate_all"))
            return await fast(*a, **k)
        eng.local.fast = fast_seen
        out = await pipe.solve(62, Frame(), "", False, _none)
        check("...the watching's screen is its own", out.engine == "local" and not asked, f"{out.engine} {len(asked)}")
        check("...and its first pass is not told to hand every problem on (easy ones stay fast)",
              escalated == [False], str(escalated))
        out = await pipe.solve(63, Frame(), "", False, _none, by_user=True)
        check("...and Reanalyze still goes to the agent, whatever the kind", out.engine == "agent" and len(asked) == 1,
              f"{out.engine} {len(asked)}")
        pipe.spend.spent.clear()
        pipe.spend.limited("HTTP 429 Too Many Requests")
        check("a two-minute rate limit does not load it", pipe.standing_in() == "" and pipe.spend.limit_left() != "",
              pipe.standing_in())
        pipe.spend.limit_until, pipe.spend.limit_kind = 0.0, ""
        # The usage limit met inside an analysis with this PC's model off: the rest is armed by the agent's own path,
        # and the model stands in for this problem too (nothing read the error there before)
        async def at_limit(images, text, on_delta, web=False):
            asked.append(text)
            raise RuntimeError("claude CLI: You've hit your weekly limit · resets Nov 3, 3am (Asia/Seoul)")
        eng.agent.run = at_limit
        eng.local.fast = fast
        before = len(asked)

        async def solved(seq):   # the card's error, not the suite's: a check that fails says so and the rest run
            try:
                return await pipe.solve(seq, Frame(), "", False, _none)
            except Exception as exc:
                return type("Failed", (), {"engine": f"error: {exc}"[:80]})()
        out = await solved(64)
        check("with the model off, the limit met in an analysis rests the agent and the model answers that one",
              out.engine == "local" and len(asked) == before + 1 and pipe.standing_in() == "limit"
              and pipe.spend.limit_kind == "plan", f"{out.engine} {pipe.standing_in()!r}")
        check("...and the card still says what went out to the agent",
              any(x.get("to") == "agent" for x in getattr(out, "sent", ())), str(getattr(out, "sent", None)))
        out = await solved(65)
        check("...and the next is not sent to it", out.engine == "local" and len(asked) == before + 1,
              f"{out.engine} asked={len(asked) - before}")
        SETTINGS.values["agent_mode"] = "off"
        pipe.spend.limit_until = time.time() + 3600
        check("with the agent switched off as well, nothing stands in", pipe._local() is None)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


def spend_and_errors():
    print("\n[what an agent that gives no prices is charged, and errors that cost nothing]")
    s = Spend(CONFIG)
    s.priced = False
    for _ in range(60):
        s.cut_short()
        s.failed(RuntimeError("codex CLI: stream disconnected"))
    check("Codex's cancelled and failed turns are not counted at a made-up price", s.hour_usd() == 0.0,
          str(s.hour_usd()))
    s.spent.append((time.time(), 50.0))
    check("...and its hour never trips the ceiling", "비용" not in s.blocked(), s.blocked())
    p = Spend(CONFIG)
    p.failed(RuntimeError("Error code: 401 - invalid x-api-key"))
    p.failed(RuntimeError("Error code: 429 - rate_limit_error"))
    check("an error refused before any work (a sign-in, a rate) costs nothing", p.hour_usd() == 0.0, str(p.hour_usd()))
    p.failed(RuntimeError("Error code: 500 - internal"))
    check("...an error after the request went out still counts", p.hour_usd() > 0)
    check("a 500 whose request id holds 401 is not a rejected sign-in",
          error_hint("Error code: 500 - {'request_id': 'req_011CV4013xyz'}") == "", "")
    check("...a 401 is", error_hint("Error code: 401 - {'type': 'authentication_error'}") == "auth"
          and error_hint("unexpected status 401 Unauthorized") == "auth")
    check("...and a 529 or 429 is a limit", error_hint("Error code: 529 - overloaded") == "limit"
          and error_hint("last status: 429 Too Many Requests") == "limit")
    check("Claude Code's own words for its limit are a limit (no price for that turn, the panel's guidance)",
          error_hint("claude CLI: You've hit your weekly limit · resets Nov 3, 3am (Asia/Seoul)") == "limit")
    r = Spend(CONFIG)
    r.limited("You've hit your weekly limit · resets in 3 days")
    until = r.limit_until
    r.limited("HTTP 429 Too Many Requests")
    check("a 429 from a request in flight does not shorten a plan's rest", r.limit_until == until
          and r.limit_kind == "plan", f"{r.limit_kind}")
    check("a number that holds 429 is no rate limit", limit_until("turn cost 0.429 usd", time.time()) is None)
    now = time.mktime((2026, 11, 1, 10, 0, 0, 0, 0, -1))
    when = lambda t: time.strftime("%m-%d %H:%M", time.localtime(limit_until(t, now)))  # noqa: E731
    check("Codex's 'try again at 12:26 PM' rests until then", when(
        "You’ve hit your usage limit. Upgrade to Pro (https://x) or try again at 12:26 PM.") == "11-01 12:26")
    check("...a time gone by today is tomorrow's", when("You’ve hit your usage limit. try again at 9:05 AM.")
          == "11-02 09:05")
    check("...and 'at Nov 4th, 2026 11:13 AM' until that day", when(
        "You’ve hit your usage limit. ... try again at Nov 4th, 2026 11:13 AM.") == "11-04 11:13")
    check("the API's credit balance too low rests an hour", when(
        "Error code: 400 - Your credit balance is too low to access the Anthropic API") == "11-01 11:00")


async def made_up_inputs():
    print("\n[code run on made-up inputs when the problem shows no examples]")
    py = shutil.which("python3") or sys.executable

    async def run(lang, code, stdin):   # the runner, as a Python process here
        if isinstance(stdin, list):
            runs = []
            for x in stdin:
                p = subprocess.run([py, "-I", "-c", code], input=x, capture_output=True, text=True, timeout=20)
                runs.append({"stdout": p.stdout, "stderr": p.stderr, "exit": p.returncode, "ok": p.returncode == 0})
            return {"runs": runs}
        p = subprocess.run([py, "-I", "-c", code], input=stdin, capture_output=True, text=True, timeout=20)
        return {"stdout": p.stdout, "stderr": p.stderr, "exit": p.returncode}
    good = "TYPE: algorithm\nANSWER: 합\n```python\ndef solution(a, b):\n    return a + b\n```"
    bad = "TYPE: algorithm\nANSWER: 합\n```python\ndef solution(a, b):\n    return a / b\n```"
    made = {"function": "solution", "cases": [{"args": [1, 2]}, {"args": [0, 0]}, {"args": [5, 5]}], "probe": True}
    res = await run_cases(good, made, run)
    check("a function that ends on every input passes, with nothing judged", res and res.get("probe")
          and res["passed"] == 3 and res["total"] == 3 and not res["fails"], str(res))
    res = await run_cases(bad, made, run)
    check("...one that raises on an input fails there, and says what it raised", res and res["passed"] == 2
          and "ZeroDivisionError" in str(res["fails"]), str(res))
    prog = "TYPE: algorithm\nANSWER: 합\n```python\na, b = map(int, input().split())\nprint(a + b)\n```"
    res = await run_cases(prog, {"stdin": [{"input": "1 2"}, {"input": "3"}], "probe": True}, run)
    check("a program fed made-up input: what it printed is shown, a crash is a failure",
          res and res["passed"] == 1 and res["outputs"][0]["got"] == "3", str(res))
    saved = dict(SETTINGS.values)
    notices = []
    try:
        SETTINGS.values.update(local_llm=True, autocheck=True)
        pipe, eng = make_pipeline(notices)

        async def nothing(images=(), problem=""):
            return {}
        eng.local.cases = nothing
        eng.local.made = {"function": "solution", "cases": [{"args": [1, 2]}, {"args": [2, 0]}]}
        reading = {}
        out = Outcome(text=bad, model="m", usage=None, cost_usd=0.0, engine="local")
        res = await check_code(pipe, Frame(), out, run, note=reading)
        check("check_code runs the made-up inputs when the problem has none", res and res.get("probe")
              and res["passed"] == 1 and reading.get("probes") == 2, f"{res} {reading}")
        check("...and gives no examples for a retry to be checked against", res is not None and "cases" not in res)
        eng.local.made = {"function": "solution", "cases": [{"args": [1, 2]}]}
        broken = Outcome(text=good.replace("return a + b", "return a +"), model="m", usage=None, cost_usd=0.0,
                         engine="local")
        res = await check_code(pipe, Frame(), broken, run, note={})
        check("an error on made-up inputs says it came from them", res and res.get("probe") and (
            res.get("error") or res.get("fails")), str(res))
        eng.local.made = {"function": "other_name", "cases": [{"args": [1, 2, 3, 4]}]}
        res = await check_code(pipe, Frame(), out, run, note={})
        check("made-up inputs that fit no function of the answer: no check, not a reason about examples", res is None,
              str(res))
        eng.local.made = {}
        res = await check_code(pipe, Frame(), out, run, note={})
        check("with no inputs made either, nothing is run", res is None, str(res))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def api_stop_reasons():
    print("\n[the API agent reads why its answer stopped]")

    class Final:
        def __init__(self, stop, category=None):
            self.stop_reason = stop
            self.stop_details = type("D", (), {"category": category})() if category else None
            self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()

    class Stream:
        def __init__(self, final, chunks):
            self.final, self.chunks = final, chunks

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                for c in self.chunks:
                    yield c
            return gen()

        async def get_final_message(self):
            return self.final

    asked = {}

    def agent_for(final, chunks):
        a = AnthropicApiAgent.__new__(AnthropicApiAgent)
        a.cfg, a._resolved = CONFIG, {}

        async def model():   # a model the price table knows, so what a turn cost can be worked out
            return "claude-opus-5-5"
        a.model = model

        def stream(**kw):
            asked.update(kw)
            return Stream(final, chunks)
        a._client = type("C", (), {"messages": type("M", (), {"stream": staticmethod(stream)})()})()
        return a
    a = agent_for(Final("end_turn"), ["TYPE: short\n", "ANSWER: 4"])
    res = await a.run([], "2+2", _none)
    check("an answer that ended is returned as it came", res.text == "TYPE: short\nANSWER: 4", res.text)
    check("a stream is given room for thinking and answer (not the 8,000 of SIDENOTE_MAX_TOKENS)",
          asked.get("max_tokens", 0) >= 64000, str(asked.get("max_tokens")))
    a = agent_for(Final("max_tokens"), ["TYPE: short\n", "ANSWER: 4 and"])
    res = await a.run([], "2+2", _none)
    check("an answer cut at max_tokens says so", res.text.endswith("(길이 한도에서 잘림)"), res.text)
    a = agent_for(Final("refusal", "cyber"), [])
    try:
        await a.run([], "x", _none)
        raised = None
    except RuntimeError as exc:
        raised = exc
    check("a refusal is an error (this PC's model then answers), paid for all the same",
          raised is not None and "cyber" in str(raised) and getattr(raised, "cost_usd", None) is not None, repr(raised))


async def model_layer():
    print("\n[the model, agent and check layer: odd inputs and failures]")
    check("ordinary words are no login failure", error_hint("analog input device failed") == ""
          and error_hint("the dialog in the catalog") == "" and error_hint("Please log in") == "auth")
    check("a whole number off by 10 is wrong, however large", not _same(12345678901244, 12345678901234.0)
          and _same(3, 3.0) and _same(0.1 + 0.2, 0.3))
    check("a comma in a Python default does not split the parameter",
          [p[0] for p in _py_decl('def f(sep=",", n=1):\n    return 1\n', "f")[0]] == ["sep", "n"])
    check("a Java class loses its public whatever the order of its modifiers",
          _drop_public("final public class Solution {}\npublic final class B {}") == "final class Solution {}\nfinal class B {}")
    check("a Go value outside its type cannot be filled, and says so", _go_value("int32", 3000000000) is None
          and _go_value("uint", -1) is None and _go_value("uint8", 255) == "255" and _go_value("int", -5) == "-5")

    async def no_run(*a):
        raise AssertionError("nothing can be judged, so nothing runs")
    res = await run_cases("TYPE: coding\n```python\nprint(input())\n```", {"stdin": [{"input": "3"}]}, no_run)
    check("a program's example with no output is no example", res is None, str(res))

    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()

    async def ready(*a, **k):
        return None
    local._ready = ready

    async def broken(body, on_delta):
        raise LocalServerError("local LLM: HTTP 500: boom")
    local._stream = broken
    res = await local.fast(["x"], "q", _none)
    check("a model server answering 500 hands the screen on, no error card", res.text is None, str(res.text))
    replies = [("Understood.\n\n\n\n", None, [], {"finish": "stop", "thought": ""})]

    async def once_then_broken(body, on_delta):
        if not replies:
            raise LocalServerError("local LLM: HTTP 500: boom")
        out = replies.pop()
        await on_delta(out[0])
        return out
    local._stream = once_then_broken
    res = await local.fast(["x"], "q", _none)
    check("...and so does the second asking for the TYPE line", res.text is None, str(res.text))
    rounds = [("the body", None, [], {"finish": "stop", "thought": ""}),
              ("TYPE: essay\nANSWER: x\n", None, [{"id": "1", "name": "web_search", "arguments": "{}"}],
               {"finish": "tool_calls", "thought": ""})]

    async def searched(body, on_delta):
        return rounds.pop()
    local._stream, local._tools = searched, (lambda: [{"type": "function"}])

    async def found(name, args):
        return "{}"
    local.web = type("W", (), {"call": staticmethod(found)})()
    text, *_ = await local._run([], False, _none, lambda: False, [])
    check("head lines written before a search stay in the result", head_of(text)[0] == "essay" and "the body" in text, text)
    made = {}

    async def plain(*a, **k):
        return made["out"]
    local._plain = plain
    made["out"] = '{"cases": ["x", {"args": [1]}], "stdin": 5}'
    d = await local._read_cases("p", (), "t", "problem", 10)
    check("a malformed reading keeps only what has the form", d["cases"] == [{"args": [1]}] and d["stdin"] == [], str(d))

    class Lines:
        def __init__(self, lines):
            self.lines = [json.dumps(x).encode() + b"\n" for x in lines]

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""
    event = lambda e: {"type": "stream_event", "event": e}  # noqa: E731
    text_of = lambda t: event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}})  # noqa: E731
    out, *_ = await read_claude_turn(Lines([event({"type": "message_start", "message": {}}), text_of("찾아보겠습니다."),
                                            event({"type": "message_start", "message": {}}),
                                            text_of("TYPE: essay\nANSWER: 1\n")]), _none, 5)
    check("a message after a web search starts its head on a line of its own", head_of(out)[0] == "essay", repr(out))
    pace = GpuPace(CONFIG)
    pace.rates["m"] = [100.0] * 5
    pace.hold, pace.hold_max, slow = 0.0, 0.0, []
    for _ in range(pace.RELEARN_AFTER + 1):
        pace.busy_until = time.time() - 1          # the hold has just run out, and it is tried again
        slow.append(pace.record("m", 500, 50.0))
    check("a model slow at every try has that rate taken as its usual one, in the end, and is no longer held",
          slow[0] is True and slow[-1] is False and set(pace.rates["m"]) == {10.0} and not pace.busy(), f"{slow} {pace.rates}")
    check("a tool call's unparsable arguments do not go back in the conversation",
          _json_or_empty("{bad") == "{}" and _json_or_empty('{"a": 1}') == '{"a": 1}' and _json_or_empty(None) == "{}")
    codex = CodexAgent(CONFIG)
    spend = Spend(CONFIG)
    spend.agent = codex
    check("Codex signed in with ChatGPT has no prices, and with an API key it has", not spend.priced
          and setattr(codex, "reports_cost", True) is None and spend.priced)
    node = shutil.which("node")
    if node:
        js = "TYPE: coding\n```javascript\nfunction f(n) { return BigInt(n) + 2n ** 53n + 1n; }\n```"

        async def run(lang, code, stdin):
            p = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
            return {"stdout": p.stdout, "stderr": p.stderr, "exit": p.returncode}
        res = await run_cases(js, {"function": "f", "cases": [{"args": [0], "expected": 9007199254740993}]}, run)
        check("a JavaScript BigInt is judged as the number it is", res and res["passed"] == 1, str(res))
        js = "TYPE: coding\n```javascript\nasync function f(n) { return n + 1; }\n```"
        res = await run_cases(js, {"function": "f", "cases": [{"args": [1], "expected": 2}, {"args": [2], "expected": 3}]}, run)
        check("an async JavaScript answer is judged by what it resolves to", res and res["passed"] == 2, str(res))


def the_history():
    print("\n[the answers are kept, within limits, and found again]")
    with tempfile.TemporaryDirectory() as d:
        h = History(Path(d) / "history.sqlite", days=30, max_mb=1)
        now = time.time()
        h.add(1, now - 40 * 86400, "algorithm", {"text": "TYPE: algorithm\\nANSWER: 오래된 답", "trigger": "screen"})
        check("an answer past the age goes", h.query() == [], str(h.query()))
        h.add(2, now - 86400, "coding", {"text": "ANSWER: 해시맵 100% 씁니다", "trigger": "screen", "thumb": "data:x"})
        h.add(3, now, "math", {"text": "ANSWER: 42", "trigger": "voice", "transcript": "곱셈 문제"})
        h.update(3, check={"passed": 1, "total": 1})
        h.update(3, turn={"id": 9, "q": "왜 그런가요", "text": "이유는 이렇습니다"})
        rows = h.query()
        check("the newest first, with what came after it", [r["id"] for r in rows] == [3, 2] and rows[0]["check"]["passed"] == 1
              and rows[0]["turns"][0]["q"] == "왜 그런가요", str(rows)[:200])
        check("found by a word of a follow-up, of what was heard, of the answer", [r["id"] for r in h.query(q="이유는")] == [3]
              and [r["id"] for r in h.query(q="곱셈")] == [3] and [r["id"] for r in h.query(q="해시맵")] == [2])
        check("every word has to be there; % is only a character", h.query(q="해시맵 42") == []
              and [r["id"] for r in h.query(q="100%")] == [2] and h.query(q="%") != rows[:0] and len(h.query(q="1_0")) == 0)
        check("by kind, by day, and the days with their counts", [r["id"] for r in h.query(kind="math")] == [3]
              and len(h.days_list()) == 2 and h.days_list()[0]["n"] == 1
              and [r["id"] for r in h.query(day=h.days_list()[1]["day"])] == [2])
        for i in range(10, 40):
            h.add(i, now + i, "essay", {"text": "x" * 60000})
        total = sum(len(json.dumps(r)) for r in h.query(limit=200))
        check("past the size limit the oldest go first", total <= 1024 * 1024 * 1.05 and not any(r["id"] == 2 for r in h.query(limit=200)),
              str(total))
        again = History(Path(d) / "history.sqlite", days=30, max_mb=1)
        check("a restart finds them", len(again.query(limit=5)) == 5)
        again.clear()
        check("clearing leaves nothing", again.query() == [] and again.days_list() == [])
    check("with no folder it does nothing and fails nothing", History(None).query() == [] and History(None).prune() == 0)


def chart_token():
    print("\n[the chart's runner token where it is rendered without a cluster]")
    helm = shutil.which("helm")
    if helm is None:   # the CI's server job has none; its chart job renders the chart on its own
        print("  skipped: no helm on PATH")
        return
    chart = str(ROOT / "deploy/helm/sidenote")

    def render(*sets):
        args = [helm, "template", "t", chart]
        for s in sets:
            args += ["--set", s]
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    a, b = render(), render()
    check("with no token given, two renders differ (what runner.token is for)", a != b)
    a, b = render("runner.token=fixed-token"), render("runner.token=fixed-token")
    check("runner.token renders the same token every time", a == b and "Zml4ZWQtdG9rZW4=" in a)
    own = render("runner.existingSecret=mine")
    check("the Secret is kept when the release goes (a reinstall keeps the pods' token)",
          "helm.sh/resource-policy: keep" in a)
    check("a token given rolls both pods when it changes", a.count("checksum/runner-token") == 2
          and a != render("runner.token=other-token"))
    check("a token written as a number renders", "Secret" in render("runner.token=123456"))
    check("runner.existingSecret: the pods read that Secret and the chart makes none",
          own.count('name: "mine"') == 2 and "t-sidenote-runner-token" not in own, str(own.count('name: "mine"')))


def main():
    os.environ.setdefault("SIDENOTE_ANALYZER", "mock")
    the_log()
    the_thought()
    asyncio.run(standing_in())
    spend_and_errors()
    asyncio.run(made_up_inputs())
    asyncio.run(api_stop_reasons())
    asyncio.run(model_layer())
    the_history()
    chart_token()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
