"""This PC's two models swapping on the GPU at every question, and what stops it (design note 127).

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/gpu_swap.py

On this PC in November every spoken question loaded the 26b, waited out the 45 s a model just loaded gets for its first
token, counted the GPU busy, and put the e4b on the GPU, which pushed the 26b off (one model at a time); after a hold of
30 s the next question loaded the 26b again, cold. 47 spoken questions on 11-10 brought 27 loads, about 17 of 80 minutes.
The hold never grew: the next verdict was measured from when it came, after the retry's own load and wait, not from the
retry. "Load onto the GPU" left the model cold, so the first question after it met the same. Giving the GPU back during
an answer was logged as the agent failing, and the model the person had just stopped loaded again.

Checks, each a thing the server did differently before:
  cold     a first pass on a model just loaded that brings no first token: handed on, the GPU not counted busy, the
           model warm from then on; the next silence counts it busy; the thinking pass the same
  let go   a silence while the GPU was given back is not counted busy, in the first pass and the thinking pass
  hold     the retry after a hold is what the next verdict is measured from: one that came long after the retry
           began still doubles the hold; a verdict with no retry long after the hold starts over
  warm     the panel's Load onto the GPU reads the first pass's instructions once, and the model is warm after it;
           a warm-up that fails leaves it cold
  stopped  a load stopped by Free GPU while the agent's question was being read out ends the analysis as stopped:
           not an agent failure, and not handed to this PC's model to load again
"""
import asyncio
import dataclasses
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-gpu-swap-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="")
os.environ.pop("SIDENOTE_LANG", None)   # the log lines and notes are read in English here
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server.telemetry as telemetry  # noqa: E402

from server.analyzer import GpuPace, LoadStopped, LocalLlmAnalyzer, NoFirstToken  # noqa: E402
from server.config import CONFIG  # noqa: E402

PASS, FAIL = [], []
EVENTS: list = []
telemetry.event = lambda name, **f: EVENTS.append((name, f))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f"  - {str(detail)[:500]}" if detail and not ok else ""))


class Server:
    """Stands in for the model's server under LocalLlmAnalyzer._client: each request streams its first token after
    `first` seconds (None: never), then a short answer; the bodies asked with are kept."""

    def __init__(self, first=0.0):
        self.first = first
        self.bodies: list = []

    def stream(self, method, url, json=None, timeout=None):
        self.bodies.append(json)
        outer = self

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
                await asyncio.sleep(3600 if outer.first is None else outer.first)
                for word in ("TYPE: calc\n", "ANSWER: 2\n"):
                    yield "data: " + dumps({"choices": [{"delta": {"content": word}}]})
                yield "data: [DONE]"
        return Resp()

    async def aclose(self):
        pass


def local_on(server, **limits):
    """A local model on the stand-in server, the model on the GPU already (no load), cold until a test warms it."""
    cfg = dataclasses.replace(CONFIG, **limits) if limits else CONFIG
    local = LocalLlmAnalyzer(cfg)
    local._client = server

    async def ready(model):
        return None
    local._ready = ready
    return local


async def nothing(_text):
    return None


async def first_pass(local, deadline=0.3):
    return await local.fast([], "x", nothing, first_deadline=deadline)


def busy_events():
    return [f for n, f in EVENTS if n == "gpu_busy"]


async def cold():
    print("\n[a model just loaded, silent at first]")
    EVENTS.clear()
    local = local_on(Server(first=None), local_cold_first_token_sec=0.5)
    model = local.model
    began = time.time()
    res = await first_pass(local)
    took = time.time() - began
    check("a first pass on a model just loaded that brings nothing: handed on at the cold limit",
          res.slow and res.text is None and 0.45 < took < 1.5, f"slow={res.slow} took={took:.2f}")
    check("...the GPU not counted busy (no gpu_busy, no hold), so no smaller model is put on the GPU",
          not busy_events() and not local.pace.busy(), [busy_events(), local.pace.busy_until])
    check("...said as a cold model's first silence (local_cold) for the report", any(n == "local_cold" for n, _ in EVENTS), EVENTS)
    check("...and the model warm from then on: its cache holds what the cut let it read", model in local._warm)
    EVENTS.clear()
    res = await first_pass(local)
    check("the next silence, warm, counts the GPU busy as before", res.slow and len(busy_events()) == 1
          and busy_events()[0].get("after") == "first_token" and local.pace.busy(), [busy_events(), local.pace.held])

    print("\n[the thinking pass, the same]")
    EVENTS.clear()
    local = local_on(Server(first=None), local_cold_first_token_sec=0.5)
    try:
        await local.deep([], "x", nothing, think=True, first_deadline=0.3, stall=5)
        exc = None
    except Exception as e:   # noqa: BLE001
        exc = e
    check("a cold thinking pass that brings nothing: given up (NoFirstToken), the GPU not counted busy",
          isinstance(exc, NoFirstToken) and not busy_events() and any(n == "local_cold" for n, _ in EVENTS)
          and local.model in local._warm, [exc, EVENTS])
    EVENTS.clear()
    try:
        await local.deep([], "x", nothing, think=True, first_deadline=0.3, stall=5)
    except NoFirstToken:
        pass
    check("...and its next silence, warm, counts it busy", len(busy_events()) == 1
          and busy_events()[0].get("after") == "think_first_token", busy_events())


async def let_go():
    print("\n[the GPU given back while a pass waited]")
    EVENTS.clear()
    local = local_on(Server(first=None))
    local._warm.add(local.model)

    async def give_back():
        await asyncio.sleep(0.1)
        local._let_go = time.time()   # as unload() marks the model taken off on purpose
    asyncio.ensure_future(give_back())
    res = await first_pass(local)
    check("a first pass silent while the GPU was given back: handed on, not counted busy",
          res.slow and not busy_events() and not local.pace.busy(), [busy_events(), local.pace.busy_until])
    EVENTS.clear()
    local = local_on(Server(first=None))
    local._warm.add(local.model)
    asyncio.ensure_future(give_back())
    try:
        await local.deep([], "x", nothing, think=True, first_deadline=0.3, stall=5)
    except NoFirstToken:
        pass
    check("...and a thinking pass the same", not busy_events() and not local.pace.busy(), busy_events())


def hold():
    print("\n[how long the smaller model holds]")
    cfg = dataclasses.replace(CONFIG, local_busy_hold_sec=30, local_busy_hold_max_sec=600)
    pace = GpuPace(cfg)
    real = time.time
    now = [1000.0]
    time.time = lambda: now[0]
    try:
        pace.timed_out("big")                  # a first verdict: 30 s
        first = pace.held
        now[0] = pace.busy_until + 16          # the hold ran out; a question 16 s later tries the big model again
        pace.trying("big")
        now[0] += 60 + 45 + 20                 # its load, the wait for its first token: the verdict 141 s after the hold
        pace.timed_out("big")
        second = pace.held
        check("a verdict long after a retry that began right after the hold doubles the hold (30 s, then 60 s)",
              first == 30 and second == 60, [first, second])
        now[0] = pace.busy_until + 10
        pace.trying("big")
        pace.trying("big")                     # a second pass on it changes nothing: the first try is the one
        now[0] += 200
        pace.timed_out("big")
        check("...and again (120 s), the first try after each hold being the one measured", pace.held == 120, pace.held)
        now[0] = pace.busy_until + 900         # nothing tried for a quarter of an hour, then a verdict
        pace.timed_out("big")
        check("a verdict with no retry long after the hold starts a new spell at 30 s", pace.held == 30, pace.held)
        pace2 = GpuPace(cfg)
        pace2.timed_out("big")
        now[0] = pace2.busy_until + 5
        pace2.trying("small")                  # another model's pass is no retry of the big one
        now[0] += 400
        pace2.timed_out("big")
        check("...and another model's pass after the hold is no retry of the slow one", pace2.held == 30, pace2.held)
    finally:
        time.time = real


async def warm():
    print("\n[Load onto the GPU]")
    srv = Server(first=0.05)
    local = local_on(srv)
    model = local.model
    await local.load()
    body = srv.bodies[-1] if srv.bodies else {}
    check("the panel's load reads the first pass's instructions once: one token asked for, the same system prompt",
          body.get("max_tokens") == 1 and body.get("messages", [{}])[0].get("content") == local._system(), body and
          {k: body.get(k) for k in ("model", "max_tokens")})
    check("...and the model is warm after it, so the first problem gets the warm deadline", model in local._warm)

    class Broken(Server):
        def stream(self, *a, **k):
            raise RuntimeError("the runtime went away")
    local = local_on(Broken())
    await local.load()
    check("a warm-up that fails leaves the model cold (and the load does not fail for it)", local.model not in local._warm)


async def stopped():
    print("\n[Free GPU while the agent's question is read out]")
    from server.analyzer import FastResult, make_engines
    from server.pipeline import Hooks, Pipeline, Speed
    from server.settings import SETTINGS
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, extract=True, agent_mode="hard", agent_payload="crop", agent_confirm=False)
        said = {"agent_failed": [], "warn": []}
        engines = make_engines(CONFIG)   # the mock local model and the mock agent

        async def quiet(*a, **k):
            return None

        async def warn(text):
            said["warn"].append(text)

        async def agent_failed(exc):
            said["agent_failed"].append(str(exc))

        async def yes(*a, **k):
            return True
        pipe = Pipeline(engines, Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=warn, stage=quiet, confirm=yes,
                                       agent_failed=agent_failed, warn=warn))
        pipe.speed = Speed(None)

        async def slow_first(*a, **k):   # the first pass brought nothing by its deadline: the agent's problem (note 54)
            return FastResult(text=None, head="", type="", route="", slow=True)

        async def stopping(speech=None, **_):   # reading its question out needs this PC's model, whose load Free GPU stops
            raise LoadStopped("local LLM: loading the model was stopped (paused, or the GPU was given back)")
        answered: list = []

        async def deep(*a, **k):        # this PC's own answer, which would load the model again
            answered.append(True)
            raise AssertionError("not asked")
        engines.local.fast, engines.local.extract, engines.local.deep = slow_first, stopping, deep
        try:
            await pipe.solve(71, None, "two plus two, what is it?", True, quiet)
            out = None
        except Exception as exc:   # noqa: BLE001
            out = exc
        check("a spoken question whose model is stopped by Free GPU while its question is read out: the analysis ends "
              "with LoadStopped (the runner says it stopped)", isinstance(out, LoadStopped), repr(out))
        check("...not counted as the agent failing", not said["agent_failed"], said["agent_failed"])
        check("...and not handed to this PC's model, which would load again", not answered, answered)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def main():
    await cold()
    await let_go()
    hold()
    await warm()
    await stopped()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    for name in FAIL:
        print("  FAIL", name)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
