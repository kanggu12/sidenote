"""This PC's model not answering, and the agent taking the problem over (design note 117). On a GPU another program held,
a thinking pass's prompt was read at a tenth of the usual rate, a request the runtime had been told to drop kept the
next one waiting behind it for minutes, and the problem ended in an error after local_timeout with the agent on.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/local_fallback.py

Checks, each a thing the server did differently before:
  deadline  the thinking pass, when the agent can take the problem, is given up when no token of any kind comes by
            local_think_first_token_sec (a cold model by local_cold_first_token_sec), and when its stream goes silent
            for local_stuck_sec; the GPU is counted busy unless another request of this server was streaming; a pass
            that starts in time, and one with no deadline, run as before
  handover  a thinking pass that fails (no first token, a silent stream, its server failing) hands the problem to the
            agent, which answers it on the same card, cleared of what the local model wrote, with a note saying so
  limits    not when the agent is off, braked, held back from the problem (not sent) or has had it already; when the
            agent fails too, the card says both failed; the verify mode's direct pass does the same
"""
import asyncio
import base64
import dataclasses
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-local-fallback-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="")
os.environ.pop("SIDENOTE_LANG", None)   # the notes are read in English here
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import server.telemetry as telemetry  # noqa: E402
import httpx2  # noqa: E402

from server.analyzer import FastResult, LocalLlmAnalyzer, LocalServerError, NoFirstToken, make_engines  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.i18n import t  # noqa: E402
from server.pipeline import Hooks, NotSent, Pipeline, Speed  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

PASS, FAIL = [], []
EVENTS: list = []
telemetry.event = lambda name, **f: EVENTS.append((name, f))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f"  - {str(detail)[:500]}" if detail and not ok else ""))


# ---------------------------------------------------------------------------------------------------------------------
# The thinking pass against a model's server that is slow to start, silent, or answers

class Server:
    """Stands in for the model's server under LocalLlmAnalyzer._client: one stream per request, its first token after
    `first` seconds (None: never), then `then` seconds of silence (a stream gone quiet), then the answer. Each
    request's read timeout is kept, and a gap longer than it ends the stream as httpx does (ReadTimeout)."""

    def __init__(self, first=0.0, then=0.0):
        self.first, self.then = first, then
        self.timeouts: list = []   # the timeout each stream was asked with (None: the client's own)
        self.cancelled = 0         # streams left before their end (the analyzer gave them up)

    def stream(self, method, url, json=None, timeout=None):
        self.timeouts.append(timeout)
        outer = self
        read = timeout.read if timeout is not None else None

        class Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aread(self):
                return b""

            async def aiter_lines(self):
                dumps = __import__("json").dumps

                async def gap(secs):   # a wait with nothing streamed, ended as httpx ends one past the read timeout
                    if read is not None and secs > read:
                        await asyncio.sleep(read)
                        raise httpx2.ReadTimeout("read timed out")
                    await asyncio.sleep(secs)
                try:
                    if outer.first is None:
                        await gap(3600)
                    await gap(outer.first)
                    yield "data: " + dumps({"choices": [{"delta": {"reasoning": "생각"}}]})
                    await gap(outer.then)
                    for word in ("TYPE: calc\n", "ANSWER: 2\n"):
                        yield "data: " + dumps({"choices": [{"delta": {"content": word}}]})
                    yield "data: [DONE]"
                except asyncio.CancelledError:
                    outer.cancelled += 1
                    raise
        return Resp()

    async def aclose(self):
        pass


def local_on(server, **limits):
    cfg = dataclasses.replace(CONFIG, **limits) if limits else CONFIG
    local = LocalLlmAnalyzer(cfg)
    local._client = server

    async def ready(model):   # the model is on the GPU: nothing to load
        return None
    local._ready = ready
    return local


async def deep_once(local, **kw):
    out = []

    async def keep(t):
        out.append(t)
    began = time.time()
    try:
        res = await local.deep([], "x", keep, think=True, **kw)
        return res.text, time.time() - began, None
    except Exception as exc:
        return "".join(out), time.time() - began, exc


async def deadline():
    print("\n[the thinking pass, when the agent can take the problem]")
    EVENTS.clear()
    srv = Server(first=None)
    local = local_on(srv)
    local._warm.add(local.model)   # it has answered since it was loaded
    text, took, exc = await deep_once(local, first_deadline=0.4, stall=5)
    check("no token by its deadline: given up (NoFirstToken), at the deadline and not after local_timeout",
          isinstance(exc, NoFirstToken) and 0.35 < took < 1.5, f"{exc!r} {took:.2f}")
    check("...its request stopped at the model's server", srv.cancelled == 1, srv.cancelled)
    busy = [f for n, f in EVENTS if n == "gpu_busy"]
    check("...and the GPU counted busy, so the next screens take the smaller model or the agent",
          busy and busy[0].get("after") == "think_first_token" and local.pace.held > 0, [busy, local.pace.held])

    EVENTS.clear()
    local = local_on(Server(first=None))
    local._warm.add(local.model)
    local._streams = 1             # another request of this server streaming as it starts
    text, took, exc = await deep_once(local, first_deadline=0.3)
    check("behind another request of this server: given up all the same, but the GPU is not counted busy",
          isinstance(exc, NoFirstToken) and not any(n == "gpu_busy" for n, _ in EVENTS), [exc, EVENTS])

    local = local_on(Server(first=None), local_cold_first_token_sec=0.9)
    text, took, exc = await deep_once(local, first_deadline=0.3)
    check("a model that has not answered since it was loaded gets local_cold_first_token_sec instead",
          isinstance(exc, NoFirstToken) and 0.85 < took < 2.0, f"{exc!r} {took:.2f}")

    srv = Server(first=0.2)
    local = local_on(srv)
    local._warm.add(local.model)
    text, took, exc = await deep_once(local, first_deadline=0.6)
    check("a first token in time: the pass runs on to its answer", exc is None and text == "TYPE: calc\nANSWER: 2\n",
          [exc, text])
    local = local_on(Server(first=0.2))
    await deep_once(local, first_deadline=0.6)
    check("...and the model counts as warm from then on", local.model in local._warm)

    srv = Server(first=0.05, then=3.0)
    local = local_on(srv)
    local._warm.add(local.model)
    text, took, exc = await deep_once(local, first_deadline=0.6, stall=0.4)
    check("a stream that goes silent for `stall` ends (a TimeoutError naming its wait), not after local_timeout",
          isinstance(exc, TimeoutError) and not isinstance(exc, NoFirstToken) and took < 1.5 and "nothing came" in str(exc),
          f"{exc!r} {took:.2f}")
    check("...the request asked with that read timeout", srv.timeouts and srv.timeouts[0] is not None
          and srv.timeouts[0].read == 0.4, srv.timeouts)

    srv = Server(first=0.5, then=0.5)
    local = local_on(srv)
    text, took, exc = await deep_once(local)
    check("with no deadline (the agent cannot take it) the pass waits as before, on the client's own timeout",
          exc is None and text.endswith("ANSWER: 2\n") and srv.timeouts == [None], [exc, srv.timeouts])


# ---------------------------------------------------------------------------------------------------------------------
# The pipeline: the agent takes over a problem this PC's model could not answer

class FakeFrame:
    """A screen as prepare_frame makes one (the fields the pipeline reads)."""

    def __init__(self, w=200, h=120):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, format="PNG")
        self.full_png = buf.getvalue()
        self.model_b64 = base64.b64encode(self.full_png).decode()
        self.thumb_url = "data:image/png;base64," + self.model_b64
        self.ts, self.width, self.height = 0.0, w, h
        self.extra_b64, self.windows, self.ocr_lines, self.sig = [], None, None, b""
        self.model_box = (0.0, 0.0, 1.0, 1.0)


async def _none(*a, **k):
    return None


def make_pipeline():
    said = {"stages": [], "warn": [], "agent_failed": []}
    engines = make_engines(CONFIG)   # MockLocal and the mock agent

    async def stage(seq, name, detail, restart=False, **_):
        said["stages"].append((name, detail, restart))

    async def warn(text):
        said["warn"].append(text)

    async def agent_failed(exc):
        said["agent_failed"].append(str(exc))
    hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=warn, stage=stage, confirm=_yes,
                  agent_failed=agent_failed, warn=warn)
    pipe = Pipeline(engines, hooks)
    pipe.recent.add_words = lambda *a, **k: None   # the same problem is asked again on purpose
    pipe.speed = Speed(None)
    pipe.speed.times = {"think": [5.0], "agent": [20.0]}   # this PC's model is not slower: the problem stays here
    return pipe, engines, said


async def _yes(*a, **k):
    return True


async def mcq_needs_thinking(*a, **k):   # the first pass: a choice question that needs reasoning, not one of the agent's
    return FastResult(text=None, head="TYPE: mcq\nROUTE: deep\n", type="mcq", route="deep")


def failing(exc, asked):
    async def deep(images, text, on_delta, prior=None, think=True, on_thought=None, first_deadline=None, stall=None):
        asked.append({"first_deadline": first_deadline, "stall": stall})
        await on_delta("TYPE: mcq\n")   # it wrote the start of an answer before it stopped
        raise exc
    return deep


async def handover():
    print("\n[the agent takes over what this PC's model could not answer]")
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               agent_hard_types=["algorithm", "coding", "math"])
        for exc in (NoFirstToken("local LLM: the thinking pass brought nothing in 30 s"),
                    TimeoutError("local LLM: nothing came for 60 s"),
                    LocalServerError("local LLM: HTTP 500: llama runner process has terminated")):
            pipe, eng, said = make_pipeline()
            eng.local.fast = mcq_needs_thinking
            asked: list = []
            eng.local.deep = failing(exc, asked)
            EVENTS.clear()
            out = await pipe.solve(91, FakeFrame(), "", False, _none)
            name = type(exc).__name__
            check(f"{name}: the agent answers the problem on its card", out.engine == "agent" and out.text.strip(),
                  [out.engine, out.text[:80]])
            check(f"...{name}: what the local model wrote is cleared from the card first",
                  ("agent", "", True) in said["stages"], said["stages"])
            check(f"...{name}: a note says why", any(w.startswith(t("The local model could not answer ({why}) · the agent "
                                                                   "solves", why="")[:30]) for w in said["warn"]),
                  said["warn"])
            check(f"...{name}: on record as the agent's turn because the local model failed",
                  out.stages.get("why") == "local_failed" and out.stages.get("local_failed") is True
                  and any(n == "local_failed" and f.get("to_agent") for n, f in EVENTS), [out.stages, EVENTS])
        check("the thinking pass was given the deadlines, the agent being able to take the problem",
              asked == [{"first_deadline": CONFIG.local_think_first_token_sec, "stall": CONFIG.local_stuck_sec}], asked)

        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        ok_asked: list = []

        async def answers(images, text, on_delta, prior=None, think=True, on_thought=None, first_deadline=None,
                          stall=None):
            ok_asked.append(first_deadline)
            from server.analyzer import AnalysisResult
            return AnalysisResult(text="TYPE: mcq\nANSWER: ③\n", model="mock-local (think)")
        eng.local.deep = answers
        out = await pipe.solve(92, FakeFrame(), "", False, _none)
        check("a thinking pass that answers is the card, as before", out.engine == "local" and "③" in out.text
              and ok_asked == [CONFIG.local_think_first_token_sec], [out.engine, ok_asked])
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def limits():
    print("\n[when the agent cannot take it]")
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="off", agent_payload="crop", agent_confirm=False,
                               agent_hard_types=["algorithm", "coding", "math"])
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        asked: list = []
        eng.local.deep = failing(TimeoutError("local LLM: nothing came for 180 s"), asked)
        try:
            await pipe.solve(93, FakeFrame(), "", False, _none)
            raised = None
        except Exception as exc:
            raised = exc
        check("the agent off: the local model's error is the card, and its pass had no deadline",
              isinstance(raised, TimeoutError) and asked == [{"first_deadline": None, "stall": None}], [raised, asked])

        SETTINGS.values["agent_mode"] = "hard"
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        asked = []
        eng.local.deep = failing(TimeoutError("local LLM: nothing came for 180 s"), asked)
        pipe.spend.blocked = lambda: "the hourly cost limit"   # the brake holds
        try:
            await pipe.solve(94, FakeFrame(), "", False, _none)
            raised = None
        except Exception as exc:
            raised = exc
        check("the brake holding: the same", isinstance(raised, TimeoutError) and asked[0]["first_deadline"] is None,
              [raised, asked])

        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        eng.local.deep = failing(NoFirstToken("local LLM: the thinking pass brought nothing in 30 s"), [])

        async def held_back(*a, **k):
            raise NotSent("a number shaped like personal data")
        pipe._agent_solve = held_back
        try:
            await pipe.solve(95, FakeFrame(), "", False, _none)
            raised = None
        except Exception as exc:
            raised = exc
        check("the problem held back from the agent (not sent): it stays here, and the local model's error is the card",
              isinstance(raised, NoFirstToken), raised)

        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        eng.local.deep = failing(NoFirstToken("local LLM: the thinking pass brought nothing in 30 s"), [])

        async def agent_down(*a, **k):
            exc = RuntimeError("Claude Code: could not connect")
            exc.sent = [("crop", "problem area")]
            raise exc
        pipe._agent_solve = agent_down
        try:
            await pipe.solve(96, FakeFrame(), "", False, _none)
            raised = None
        except Exception as exc:
            raised = exc
        check("the agent failing too: the card says both could not answer, each in the panel's words for its kind",
              isinstance(raised, RuntimeError) and str(raised) == t(
                  "Neither could answer: the local model ({local}), the agent ({agent_why})",
                  local=t("no answer in time"), agent_why=t("error"))
              and said["agent_failed"] == ["Claude Code: could not connect"], [raised, said["agent_failed"]])
        check("...and the agent's own failure goes where its failures go (sign-in, its limit), as when it fails alone",
              said["agent_failed"] == ["Claude Code: could not connect"], said["agent_failed"])
        check("...and what went to the agent is kept on it", getattr(raised, "sent", None) == [("crop", "problem area")],
              getattr(raised, "sent", None))

        # the agent has had the problem already: it declined, the local model took it over and failed
        pipe, eng, said = make_pipeline()
        SETTINGS.values.update(agent_hard_types=["mcq"], local_on_decline=True)   # the agent's kind now
        eng.local.fast = mcq_needs_thinking
        asked = []
        eng.local.deep = failing(TimeoutError("local LLM: nothing came for 180 s"), asked)

        async def declines(*a, **k):
            from server.pipeline import Outcome
            return Outcome(text="I can't help with that.", model="mock", usage=None, cost_usd=0.0, engine="agent")
        pipe._agent_solve = declines
        out = await pipe.solve(97, FakeFrame(), "", False, _none)
        check("the agent declined first and the local model then failed: the agent's reply is the card, not asked again",
              out.text == "I can't help with that." and asked == [{"first_deadline": None, "stall": None}], [out.text, asked])
        SETTINGS.values.update(agent_hard_types=["algorithm", "coding", "math"], local_on_decline=False)

        # the verify mode's direct pass: no thinking at all, the agent there to check
        SETTINGS.values.update(agent_mode="verify", local_think="never")
        pipe, eng, said = make_pipeline()
        asked = []
        eng.local.deep = failing(LocalServerError("local LLM: HTTP 500"), asked)
        out = await pipe.solve(98, FakeFrame(), "", False, _none)
        check("verify with no thinking: the direct pass failing hands the problem to the agent too",
              out.engine == "agent" and asked[0]["first_deadline"] == CONFIG.local_think_first_token_sec,
              [out.engine, asked])
        SETTINGS.values.update(agent_mode="off")
        pipe, eng, said = make_pipeline()
        asked = []
        eng.local.deep = failing(LocalServerError("local LLM: HTTP 500"), asked)
        try:
            await pipe.solve(99, FakeFrame(), "", False, _none)
            raised = None
        except Exception as exc:
            raised = exc
        check("...and with the agent off, its error stands", isinstance(raised, LocalServerError)
              and asked[0]["first_deadline"] is None, [raised, asked])
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def followups():
    print("\n[a follow-up the local model cannot answer]")
    from server.pipeline import followup
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False)
        last = {"engine": "local", "frame": FakeFrame(), "crop_box": (0.1, 0.1, 0.9, 0.9), "id": 300,
                "text": "TYPE: mcq\nANSWER: ③\n"}

        def failing_analyze(exc, asked):
            async def analyze(image_b64, transcript, on_delta, extra=(), voice=False, followup=None,
                              first_deadline=None, stall=None):
                asked.append({"first_deadline": first_deadline, "stall": stall})
                await on_delta("왜냐하면 ")
                raise exc
            return analyze

        pipe, eng, said = make_pipeline()
        asked: list = []
        eng.local.analyze = failing_analyze(NoFirstToken("local LLM: the first pass brought nothing in 6 s"), asked)
        out = await followup(pipe, last, "why not ②?", "ctx", _none, seq=301)
        check("the agent answers a follow-up the local model could not", out.engine == "agent" and out.text.strip(),
              [out.engine, out.text[:80]])
        check("...the local model given the deadlines first, the agent being able to take it",
              asked == [{"first_deadline": CONFIG.local_think_first_token_sec, "stall": CONFIG.local_stuck_sec}], asked)
        check("...its words cleared and a note said", ("agent", "", True) in said["stages"] and any(
            w.startswith(t("The local model could not answer ({why}) · the agent solves", why="")[:30])
            for w in said["warn"]), [said["stages"], said["warn"]])

        SETTINGS.values["agent_mode"] = "off"
        pipe, eng, said = make_pipeline()
        asked = []
        eng.local.analyze = failing_analyze(TimeoutError("local LLM: nothing came for 180 s"), asked)
        try:
            await followup(pipe, last, "why not ②?", "ctx", _none, seq=302)
            raised = None
        except Exception as exc:
            raised = exc
        check("...not with the agent off: its error stands, and no deadline was given",
              isinstance(raised, TimeoutError) and asked == [{"first_deadline": None, "stall": None}], [raised, asked])

        SETTINGS.values["agent_mode"] = "hard"
        pipe, eng, said = make_pipeline()
        asked = []
        eng.local.analyze = failing_analyze(TimeoutError("local LLM: nothing came for 60 s"), asked)
        pipe.spend.blocked = lambda: "the hourly cost limit"
        try:
            await followup(pipe, last, "the retry", "ctx", _none, seq=303, by_user=False)
            raised = None
        except Exception as exc:
            raised = exc
        check("...nor for the automatic retry while the brake holds (a person's question goes all the same)",
              isinstance(raised, TimeoutError) and asked[0]["first_deadline"] is None, [raised, asked])
        asked.clear()
        out = await followup(pipe, last, "why?", "ctx", _none, seq=304)
        check("...a person's question going to the agent with the brake on, as it always has", out.engine == "agent"
              and asked[0]["first_deadline"] == CONFIG.local_think_first_token_sec, [out.engine, asked])

        pipe, eng, said = make_pipeline()
        eng.local.analyze = failing_analyze(LocalServerError("local LLM: HTTP 500"), [])

        async def agent_down(images, text, on_delta, web=False):
            raise RuntimeError("Claude Code: could not connect")
        eng.agent.run = agent_down
        try:
            await followup(pipe, last, "why not ②?", "ctx", _none, seq=305)
            raised = None
        except Exception as exc:
            raised = exc
        check("...and both failing says so", isinstance(raised, RuntimeError) and str(raised) == t(
            "Neither could answer: the local model ({local}), the agent ({agent_why})", local=t("error"),
            agent_why=t("error")), raised)

        print("\n[the local model's own end to end question, with the agent able to take it]")
        local = local_on(Server(first=None), local_first_token_sec=0.3)
        local._warm.add(local.model)
        began = time.time()
        try:
            await local.analyze(None, "", _none, followup={"question": "q", "context": "c"}, first_deadline=5, stall=5)
            raised = None
        except Exception as exc:
            raised = exc
        check("a first pass with nothing by local_first_token_sec gives the question up (NoFirstToken)",
              isinstance(raised, NoFirstToken) and time.time() - began < 2.0, [raised, time.time() - began])
        local = local_on(Server(first=0.05))
        out = await local.analyze(None, "", _none, followup={"question": "q", "context": "c"}, first_deadline=5, stall=5)
        check("...and one that answers is the answer", out.text.endswith("ANSWER: 2\n"), out.text)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def main():
    await deadline()
    await handover()
    await limits()
    await followups()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


asyncio.run(main())
