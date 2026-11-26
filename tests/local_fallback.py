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
  gpu       the GPU under this PC's model failing (every load ended in HTTP 500, "uncorrectable ECC error"):
            the agent answers every problem, the one that found it included, from what it would get with no local
            model; the model is not tried again meanwhile; a reading out that fails sends the problem as with no local
            model; when the agent fails too the analysis says both, without trying the broken model again
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

from server.analyzer import AnalysisResult, FastResult, LocalLlmAnalyzer, LocalServerError, NoFirstToken, make_engines  # noqa: E402
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

        print("\n[a follow-up about the agent's answer the agent cannot answer]")
        # The follow-up goes to the engine that wrote the answer; when that is the agent and it fails or declines, this PC's
        # model answers it, as it answers a problem (either engine alive answers)
        # a spoken problem: no screen goes with it. `words` is the question cut out of what was heard, as it went to the
        # agent; `heard` the whole run of speech, the room's, which stays on this PC
        HEARD = "네 반갑습니다 그럼 시작할게요 데이터베이스 이중화는 어떻게 하나요? 옆자리 사람 말소리"
        about = {**last, "engine": "agent", "frame": None, "crop_box": None, "words": "데이터베이스 이중화는 어떻게 하나요?",
                 "heard": HEARD, "voice": True}
        for name, how in (("a usage limit", RuntimeError("claude CLI: You've hit your weekly limit · resets Nov 26, 10am")),
                          ("no answer in time", asyncio.TimeoutError()),
                          ("its CLI ending", RuntimeError("claude: exited 1: connect ECONNREFUSED"))):
            pipe, eng, said = make_pipeline()
            pipe.spend.signed_in()   # the limit of the case before rests in .spend.json: each case starts with the agent up
            asked = []

            async def answers(image_b64, transcript, on_delta, extra=(), voice=False, followup=None, first_deadline=None,
                              stall=None):
                asked.append(followup)
                return AnalysisResult(text="TYPE: followup\nANSWER: 이 PC의 답\n", model="mock")
            eng.local.analyze = answers

            async def fails(images, text, on_delta, web=False, _exc=how):
                raise _exc
            eng.agent.run = fails
            try:
                out = await followup(pipe, about, "왜요?", "ctx", _none, seq=306)
                raised = None
            except Exception as exc:
                out, raised = None, exc
            check(f"the agent failing on it ({name}): this PC's model answers, once",
                  raised is None and out is not None and out.engine == "local" and len(asked) == 1, [raised, out and out.engine, len(asked)])
            if name != "no answer in time":
                continue
            check("...with what was heard, which stays on this PC", bool(asked) and asked[0].get("problem") == HEARD, asked[:1])
            check("...and the card says the agent failed and why, as a problem's does",
                  out is not None and out.stages.get("agent_failed") is True and out.stages.get("agent_error") == t("no answer in time"),
                  out and out.stages)
        # a sign-in rejected on a follow-up marks the agent signed out, as on a problem
        pipe, eng, said = make_pipeline()
        pipe.spend.signed_in()
        eng.local.analyze = answers

        async def rejected(images, text, on_delta, web=False):
            raise RuntimeError("claude: Invalid API key · Please run /login")
        eng.agent.run = rejected
        await followup(pipe, about, "왜요?", "ctx", _none, seq=310)
        check("...a sign-in rejected on it is told to the server, as on a problem", len(said["agent_failed"]) == 1, said["agent_failed"])
        # The room's speech never goes to the agent: this PC's model failing on a follow-up about a spoken problem it
        # answered, the agent gets the question cut out of what was heard, as the problem went, and no more
        pipe, eng, said = make_pipeline()
        pipe.spend.signed_in()
        sent_text = []

        async def local_fails(image_b64, transcript, on_delta, extra=(), voice=False, followup=None, first_deadline=None, stall=None):
            raise NoFirstToken("local LLM: the first pass brought nothing in 6 s")
        eng.local.analyze = local_fails

        async def agent_reads(images, text, on_delta, web=False):
            sent_text.append(text)
            return AnalysisResult(text="TYPE: followup\nANSWER: 에이전트 답\n", model="mock")
        eng.agent.run = agent_reads
        out = await followup(pipe, {**about, "engine": "local"}, "왜요?", "ctx", _none, seq=311)
        check("a follow-up the agent takes over carries the question cut out of what was heard, never the room's speech",
              out.engine == "agent" and sent_text and "옆자리 사람 말소리" not in sent_text[0] and about["words"] in sent_text[0],
              sent_text[:1])
        pipe, eng, said = make_pipeline()
        pipe.spend.signed_in()
        asked = []
        eng.local.analyze = answers

        async def declines(images, text, on_delta, web=False):
            return AnalysisResult(text="죄송하지만 이 질문에는 답하지 않겠습니다.", model="mock")
        eng.agent.run = declines
        SETTINGS.values["local_on_decline"] = True
        out = await followup(pipe, about, "왜요?", "ctx", _none, seq=307)
        check("the agent declining it: this PC's model answers, and the card says the agent declined",
              out.engine == "local" and out.stages.get("agent_declined") is True and len(asked) == 1, [out.engine, out.stages])
        SETTINGS.values["local_on_decline"] = False
        asked.clear()
        out = await followup(pipe, about, "왜요?", "ctx", _none, seq=308)
        check("...and with 'answers when the agent declines' off, the agent's reply stands", out.engine == "agent" and not asked,
              [out.engine, len(asked)])
        SETTINGS.values["local_on_decline"] = True
        # this PC's model failing after the agent declined: the agent's reply is the card, not an error
        eng.local.analyze = local_fails
        out = await followup(pipe, about, "왜요?", "ctx", _none, seq=312)
        check("...and when this PC's model then fails, the agent's reply stands, with both told on the card",
              out.engine == "agent" and "답하지 않겠습니다" in out.text and out.stages.get("agent_declined") is True
              and out.stages.get("local_failed") is True, [out.engine, out.stages])
        # the agent failing and this PC's model failing too: both said, as for a problem
        eng.agent.run = fails
        try:
            await followup(pipe, about, "왜요?", "ctx", _none, seq=313)
            raised = None
        except Exception as exc:
            raised = exc
        check("...and the agent failing with this PC's model failing too says both", isinstance(raised, RuntimeError)
              and str(raised).startswith(t("Neither could answer: the local model ({local}), the agent ({agent_why})",
                                             local="", agent_why="", agent="")[:12]), raised)
        eng.local.analyze = answers
        # a spoken problem this PC's model answered: its follow-up goes to this PC's model with the question heard, as
        # nothing of a screen goes with it
        asked.clear()
        out = await followup(pipe, {**about, "engine": "local"}, "왜요?", "ctx", _none, seq=309)
        check("a follow-up about a spoken problem this PC's model answered carries what was heard",
              out.engine == "local" and asked and asked[0].get("problem") == HEARD, asked[:1])
        asked.clear()
        out = await followup(pipe, {**about, "engine": "local", "frame": FakeFrame()}, "왜요?", "ctx", _none, seq=314)
        check("...with the screen on as well", out.engine == "local" and asked and asked[0].get("problem") == HEARD, asked[:1])
        pipe.spend.signed_in()

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


# ---------------------------------------------------------------------------------------------------------------------
# The GPU under this PC's model failing: the model's server answers, and every load of the model fails on the GPU

# What the model's server answered to every load and request, word for word (the server's log), on a GPU whose
# memory had given an error it could not correct, and its driver asked for a reset
ECC_BODY = ('{"error":{"message":"llama-server process has terminated: CUDA error\\nCUDA error: uncorrectable ECC error '
            'encountered: CUDA error\\nCUDA error: uncorrectable ECC error encountered","type":"api_error","param":null,'
            '"code":null}}')


class Broken:
    """The model's server on that GPU, under LocalLlmAnalyzer._client: nothing loaded (/api/ps), and every load
    (/api/generate) and every request (/chat/completions) answered 500 with ECC_BODY. Counts the loads and requests."""

    def __init__(self):
        self.loads, self.requests = 0, 0

    async def get(self, url, timeout=None):
        class Ps:
            status_code = 200

            def json(self):
                return {"models": []}
        return Ps()

    async def post(self, url, json=None, timeout=None):
        self.loads += 1

        class Failed:
            status_code = 500
            text = ECC_BODY
        return Failed()

    def stream(self, method, url, json=None, timeout=None):
        outer = self

        class Failed:
            status_code = 500

            async def __aenter__(self):
                outer.requests += 1
                return self

            async def __aexit__(self, *exc):
                return False

            async def aread(self):
                return ECC_BODY.encode()

            async def aiter_lines(self):
                return
                yield
        return Failed()

    async def aclose(self):
        pass


def broken_pipeline():
    """make_pipeline with this PC's model the real analyzer on a Broken server, and the app's part played here: told of a
    fault (on_fault), the model is not usable (local_ok), as app.local_fault_seen makes it."""
    pipe, eng, said = make_pipeline()
    srv, usable = Broken(), {"ok": True}
    local = LocalLlmAnalyzer(CONFIG)
    local._client = srv
    local.on_fault = lambda fault: usable.update(ok=False, fault=fault)
    eng.local = pipe.engines.local = local
    pipe.hooks.local_ok = lambda: usable["ok"]
    return pipe, eng, said, srv, usable


async def gpu():
    print("\n[the GPU under this PC's model failing: the agent answers]")
    from server.analyzer import error_hint, gpu_fault, speech_request
    from server.pipeline import BothFailed
    check("that day's answer reads as the GPU's memory failing, a GPU short of memory as no fault",
          gpu_fault(ECC_BODY) == "ecc" and error_hint("local LLM: HTTP 500: " + ECC_BODY) == "gpu"
          and gpu_fault("CUDA error: out of memory") == "" and gpu_fault("HTTP 404: model not found") == "",
          [gpu_fault(ECC_BODY), error_hint(ECC_BODY)])
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False, extract=True,
                               agent_hard_types=["algorithm", "coding", "math"])
        # the analyzer itself: a load that fails on the GPU is said as such, at once, and kept as the model's fault
        pipe, eng, said, srv, usable = broken_pipeline()
        try:
            await eng.local._ready(eng.local.model)
            raised = None
        except Exception as exc:
            raised = exc
        check("a load failing on the GPU raises the server's error at once, not a time limit, and keeps the fault",
              type(raised).__name__ == "LocalServerError" and "ECC" in str(raised) and eng.local.fault
              and eng.local.fault["kind"] == "ecc" and usable["ok"] is False and srv.loads == 1,
              [type(raised).__name__, eng.local.fault, srv.loads])

        # a spoken problem, the agent on: the first pass finds the fault, and the agent answers from what was heard
        heard = "두 수의 합이 target 이 되는 인덱스를 구하는 함수를 짜 주세요"
        pipe, eng, said, srv, usable = broken_pipeline()
        EVENTS.clear()
        out = await pipe.solve(201, None, heard, True, _none)
        sent = eng.agent.calls[-1]["text"] if eng.agent.calls else ""
        check("a spoken problem: the agent answers it, given what was heard as with no local model",
              out.engine == "agent" and sent.startswith(speech_request(heard)) and not said["agent_failed"],
              [out.engine, sent[:120], said["agent_failed"]])
        check("...the broken model tried once, by its first pass, and not asked to read the question out after",
              srv.loads == 1 and srv.requests == 0, [srv.loads, srv.requests])
        check("...on record as the agent's because this PC's model is down", out.stages.get("why") in ("local_down", "unknown"),
              out.stages.get("why"))
        # the next problem: the model is not tried at all, the agent answers it alone
        out = await pipe.solve(202, FakeFrame(), "", False, _none)
        check("the next problem, a screen: the agent answers it alone and the broken model is not tried again",
              out.engine == "agent" and srv.loads == 1 and srv.requests == 0, [out.engine, srv.loads, srv.requests])

        # a screen in the verify mode, where the agent takes no problem by itself: it answers this one
        SETTINGS.values["agent_mode"] = "verify"
        pipe, eng, said, srv, usable = broken_pipeline()
        out = await pipe.solve(203, FakeFrame(), "", False, _none)
        check("the verify mode: the problem that found the fault goes to the agent, which answers it",
              out.engine == "agent" and out.stages.get("why") == "local_down", [out.engine, out.stages.get("why")])
        SETTINGS.values["agent_mode"] = "hard"

        # the agent failing too: both said, and the broken model not tried again for an answer
        pipe, eng, said, srv, usable = broken_pipeline()

        async def down(images, text, on_delta, web=False):
            raise RuntimeError("the agent's network is down")
        eng.agent.run = down
        try:
            await pipe.solve(204, FakeFrame(), "", False, _none)
            ended = None
        except Exception as exc:
            ended = exc
        check("the agent failing too: the analysis ends saying both, the broken model not tried for an answer",
              isinstance(ended, BothFailed) and "network is down" in str(ended)
              and t("the local model cannot be used now") in str(ended) and srv.loads == 1,
              [type(ended).__name__, str(ended)[:160], srv.loads])

        # the agent off: nothing else can answer, and the card says it is the GPU
        SETTINGS.values["agent_mode"] = "off"
        pipe, eng, said, srv, usable = broken_pipeline()
        try:
            await pipe.solve(205, FakeFrame(), "", False, _none)
            ended = None
        except Exception as exc:
            ended = exc
        check("the agent off: the analysis fails, and its hint is the GPU's", ended is not None
              and error_hint(str(ended)) == "gpu", [type(ended).__name__, str(ended)[:160]])
        SETTINGS.values["agent_mode"] = "hard"

        # the first pass fine and only the reading out failing (the GPU failing in between): the agent still answers
        pipe, eng, said = make_pipeline()

        async def no_extract(images=(), speech=""):
            raise LocalServerError("local LLM: HTTP 500: " + ECC_BODY)
        eng.local.extract = no_extract
        SETTINGS.values["agent_mode"] = "all"
        out = await pipe.solve(206, None, heard, True, _none)
        sent = eng.agent.calls[-1]["text"] if eng.agent.calls else ""
        check("a reading out that fails: what was heard goes as with no local model, and the agent answers",
              out.engine == "agent" and sent.startswith(speech_request(heard)) and not said["agent_failed"],
              [out.engine, sent[:120], said["agent_failed"]])
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def reasons():
    print("\n[why the other engine answered, kept with the answer for its card]")
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="all", agent_payload="crop", agent_confirm=False, local_on_decline=True)
        # the agent declines: its own first words are kept, and this PC's model answers
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking

        async def declines(images, text, on_delta, web=False):
            from server.analyzer import AnalysisResult
            return AnalysisResult(text="**죄송하지만** 이 화면의 문제에는 답하지 않겠습니다. 시험 중인 것으로 보입니다.", model="mock")
        eng.agent.run = declines
        out = await pipe.solve(301, FakeFrame(), "", False, _none)
        check("the agent declining: kept as declined, none of its words, and this PC's model answers",
              out.engine == "local" and out.stages.get("agent_declined") is True and "agent_said" not in out.stages
              and not out.stages.get("agent_empty"), [out.engine, out.stages])
        # the agent failing: what failed, not "error" alone
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking

        async def fails(images, text, on_delta, web=False):
            raise RuntimeError("claude: exited 1: connect ECONNREFUSED")
        eng.agent.run = fails
        out = await pipe.solve(302, FakeFrame(), "", False, _none)
        check("the agent failing: what failed is kept, said once, and this PC's model answers", out.engine == "local"
              and out.stages.get("agent_failed") is True and out.stages.get("agent_error") == "claude: exited 1: connect ECONNREFUSED",
              out.stages)
        # the agent's own wait running out (asyncio's TimeoutError, a class of its own on Python 3.10): no answer in time,
        # on the card and in the notice, not "error" or its English words
        for exc in (asyncio.TimeoutError(), asyncio.TimeoutError("the answer did not end within 300 s")):
            pipe, eng, said = make_pipeline()
            pipe.spend.signed_in()
            eng.local.fast = mcq_needs_thinking

            async def waits(images, text, on_delta, web=False, _exc=exc):
                raise _exc
            eng.agent.run = waits
            out = await pipe.solve(305, FakeFrame(), "", False, _none)
            check(f"the agent's wait running out ({str(exc) or 'no words'}): said as no answer in time, on the card and in the notice",
                  out.engine == "local" and out.stages.get("agent_error") == t("no answer in time")
                  and any(t("no answer in time") in w for w in said["warn"]), [out.stages, said["warn"]])
        # the agent resting on its plan's limit: what it would have taken says so on the card, what it would not says nothing
        SETTINGS.values["agent_mode"] = "hard"
        pipe, eng, said = make_pipeline()
        pipe.spend.limit_until, pipe.spend.limit_kind = time.time() + 3600, "plan"
        eng.local.fast = mcq_needs_thinking
        SETTINGS.values["agent_hard_types"] = ["mcq"]
        out = await pipe.solve(306, FakeFrame(), "", False, _none)
        check("the agent resting on its limit: an answer it would have taken says it was not sent, for the limit",
              out.engine == "local" and out.stages.get("not_sent") is True and out.stages.get("not_sent_why") == t("usage limit"),
              out.stages)
        # a rest of two minutes for too many requests is no usage limit, and is not said as one
        pipe, eng, said = make_pipeline()
        pipe.spend.limit_until, pipe.spend.limit_kind = time.time() + 120, "rate"
        eng.local.fast = mcq_needs_thinking
        out = await pipe.solve(315, FakeFrame(), "", False, _none)
        check("...a short rest for too many requests is not said as a usage limit", out.engine == "local"
              and out.stages.get("not_sent_why") != t("usage limit"), out.stages)
        pipe.spend.limit_until, pipe.spend.limit_kind = 0.0, ""
        SETTINGS.values["agent_hard_types"] = ["algorithm"]
        pipe, eng, said = make_pipeline()
        pipe.spend.limit_until = time.time() + 3600
        eng.local.fast = mcq_needs_thinking
        pipe.speed.local_slower = lambda ratio: False
        out = await pipe.solve(307, FakeFrame(), "", False, _none)
        check("...and one it would not have taken (a kind left to this PC's model) says nothing of it",
              out.engine == "local" and not out.stages.get("not_sent"), out.stages)
        pipe.spend.signed_in()
        SETTINGS.values["agent_mode"] = "all"
        # the plan's meters, read fresh, show room while the agent rests on its plan's limit: the rest ends there and then;
        # when the limit comes back after that, the meters do not end the new rest, until another sign-in
        from server.app import plan_has_room
        pipe, eng, said = make_pipeline()
        pipe.spend.signed_in()
        pipe.spend.limited("claude CLI: You've hit your weekly limit")   # no time named: an hour's rest
        resting = bool(pipe.spend.limit_left())
        room = plan_has_room({"session": None, "week": {"used": 10.0, "resets": 0}, "models": []})
        full = plan_has_room({"session": {"used": 3.0}, "week": {"used": 100.0}, "models": []})
        blank = plan_has_room({"session": None, "week": None, "models": []})
        model_full = plan_has_room({"session": None, "week": {"used": 10.0}, "models": [{"name": "Opus", "used": 100.0}]})
        ended = pipe.spend.room_again() and not pipe.spend.limit_left()
        pipe.spend.limited("claude CLI: You've hit your weekly limit")
        held = not pipe.spend.room_again() and bool(pipe.spend.limit_left())
        pipe.spend.signed_in()
        pipe.spend.limited("claude CLI: You've hit your weekly limit")
        believed = pipe.spend.room_again()
        check("meters with room end a rest on the plan's limit; one with a window full or none read does not",
              resting and room and not full and not blank and not model_full and ended, [resting, room, full, blank, model_full, ended])
        check("...and the limit coming back after that is left to its own time, until another sign-in", held and believed,
              [held, believed])
        # the doubt is kept over a restart (.spend.json), and is over with the rest it was about
        with tempfile.TemporaryDirectory() as d:
            spot = Path(d) / ".spend.json"
            pipe, eng, said = make_pipeline()
            pipe.spend.load(spot)
            pipe.spend.limited("claude CLI: You've hit your weekly limit")
            pipe.spend.room_again()
            pipe.spend.limited("claude CLI: You've hit your weekly limit")
            again, eng2, _ = make_pipeline()
            again.spend.load(spot)
            kept = again.spend.meters_doubted and not again.spend.room_again() and bool(again.spend.limit_left())
            again.spend.limit_until = time.time() - 1      # that rest over
            over = again.spend.limit_left() == "" and not again.spend.meters_doubted
        check("...the doubt outlives a restart, and is over with the rest it was about", kept and over, [kept, over])
        pipe.spend.signed_in()
        # servers too busy for now are said as that, not as the plan used up; the hint stays a limit, retried later
        from server.analyzer import error_hint, error_words
        check("an overloaded API (529) is said as overloaded servers, not a usage limit",
              error_words("API Error: 529 {\"type\":\"overloaded_error\"}") == t("servers overloaded")
              and error_hint("API Error: 529 overloaded") == "limit" and error_words("You've hit your weekly limit") == t("usage limit"),
              error_words("API Error: 529 overloaded"))
        # this PC's model failing and the agent answering: what failed, the server's JSON reduced to its message
        SETTINGS.values["agent_mode"] = "hard"
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        eng.local.deep = failing(LocalServerError("local LLM: HTTP 500: " + ECC_BODY), [])
        out = await pipe.solve(303, FakeFrame(), "", False, _none)
        check("this PC's model failing: its kind is kept (the GPU), and the agent answers", out.engine == "agent"
              and out.stages.get("local_failed") is True and out.stages.get("local_error") == t("GPU error"), out.stages)
        # the agent declines, and this PC's model then fails too: the agent's reply stands, with what failed of the model
        SETTINGS.values["agent_mode"] = "all"
        pipe, eng, said = make_pipeline()
        eng.local.fast = mcq_needs_thinking
        eng.agent.run = declines
        eng.local.deep = failing(TimeoutError("no first token"), [])
        out = await pipe.solve(304, FakeFrame(), "", False, _none)
        check("the agent declining and this PC's model failing after it: the agent's reply, with what failed of the model",
              out.engine == "agent" and out.stages.get("agent_declined") is True and out.stages.get("local_failed") is True
              and out.stages.get("local_error") == t("no answer in time"), [out.engine, out.stages])
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def main():
    await deadline()
    await handover()
    await limits()
    await followups()
    await gpu()
    await reasons()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


asyncio.run(main())
