"""Mock-mode integration checks for the Phase 1-2 pipeline (no GPU, no network): settings round-trip,
head parsing, the Pipeline branches with the mock engines, and the code-check harness run against a
real Python subprocess that stands in for the runner sandbox. Run with the repository's venv:

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/integ.py

The face cover check reads a real problem page of the bench, a photo of a face and three figures of the
corpus (SIDENOTE_BENCH, SIDENOTE_FACES, SIDENOTE_CORPUS), none of which is in the repository: what needs
a missing one is skipped and said in one line (tests/support.py).
"""
import asyncio
import time
import base64
import io
import os
import subprocess
import pathlib
import sys
import tempfile

os.environ.setdefault("SIDENOTE_ANALYZER", "mock")
os.environ.setdefault("SIDENOTE_RUNNER_URL", "http://runner/run")  # make run_button/autocheck default on
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))   # the repository, one level up

from PIL import Image, ImageDraw  # noqa: E402

from server import heads  # noqa: E402
from server.analyzer import make_engines  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.pipeline import Hooks, NotSent, Pipeline, answer_code, check_code, checkable  # noqa: E402
from server.settings import Settings  # noqa: E402

import support  # noqa: E402  (tests/support.py: where the measurement data is, and the line saying what was skipped)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok " if cond else "FAIL ") + name + (f"  - {detail}" if detail and not cond else ""))


def png_b64(w=200, h=120, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeFrame:
    def __init__(self, w: int = 200, h: int = 120):
        b = png_b64()
        self.model_b64 = b
        self.thumb_url = "data:image/jpeg;base64," + b
        self.ts = 0.0
        self.width, self.height = w, h
        self.extra_b64 = []
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, format="PNG")
        self.full_png = buf.getvalue()
        self.windows = None
        self.ocr_lines = None
        self.model_box = (0.0, 0.0, 1.0, 1.0)


# ---------- 1. settings ----------
def test_settings():
    print("\n[settings]")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, ".settings.json")
        s = Settings(__import__("pathlib").Path(p))
        check("default local_think auto", s.get("local_think") == "auto")
        ok, _ = s.set("local_think", "always")
        check("set valid choice", ok and s.get("local_think") == "always")
        ok, err = s.set("local_think", "bogus")
        check("reject invalid choice", not ok and err)
        ok, _ = s.set("agent_mode", "hard")
        ok2, _ = s.set("roi_box", [0.1, 0.1, 0.5, 0.5])
        check("set box", ok2 and s.get("roi_box") == [0.1, 0.1, 0.5, 0.5])
        ok, _ = s.set("roi_box", [0.1, 0.1, 0.11, 0.9])  # too narrow (< 0.02)
        check("reject tiny box", not ok)
        # persistence: only non-defaults are written, and reload restores them
        check("persisted file exists", os.path.exists(p))
        s2 = Settings(__import__("pathlib").Path(p))
        s2.load()
        check("reload restores non-defaults", s2.get("local_think") == "always" and s2.get("agent_mode") == "hard")
        check("reload keeps defaults", s2.get("dedupe") is True)
        # needs/on: autocheck needs run_button + local_llm + extract (all default on in mock)
        check("on() true when prereqs on", s.on("autocheck") is True)
        s.set("extract", False)
        check("on() false when a prereq off", s.on("autocheck") is False)
        # multi dedupe rejects duplicates
        ok, _ = s.set("agent_hard_types", ["coding", "coding"])
        check("reject multi with dup", not ok)
        ok, _ = s.set("agent_hard_types", ["coding", "math"])
        check("accept multi", ok and s.get("agent_hard_types") == ["coding", "math"])
        # meta() shape the panel draws from
        m = s.meta()
        check("meta has sections+items", "sections" in m and "items" in m and len(m["items"]) > 10)
        # default hard-types: Claude for the types it is measured faster on, and work, essay and other, whose
        # answers from the local model were too shallow
        s3 = Settings(None)
        check("hard_types default is algo/coding/math/work/essay/other",
              s3.get("agent_hard_types") == ["algorithm", "coding", "math", "work", "essay", "other"],
              str(s3.get("agent_hard_types")))
        # design 13.1-13.3: with the local model Claude takes the hard problems, payload crop, no confirm
        check("agent_mode default hard with the local model", s3.get("agent_mode") == "hard", s3.get("agent_mode"))
        check("agent_payload default crop with the local model", s3.get("agent_payload") == "crop")
        check("agent_confirm default off", s3.get("agent_confirm") is False)
        # without the local model Claude is the only engine: it solves everything from the screen, as before
        saved = CONFIG.analyzer
        try:
            CONFIG.analyzer = "cli"
            s4 = Settings(None)
            check("without local: agent_mode all, payload screen",
                  s4.get("agent_mode") == "all" and s4.get("agent_payload") == "screen",
                  f"{s4.get('agent_mode')} {s4.get('agent_payload')}")
        finally:
            CONFIG.analyzer = saved


# ---------- 2. heads ----------
def test_heads():
    print("\n[heads]")
    t = "TYPE: coding\nANSWER: use a hash map\nREGION: 100 120 600 700\n```python\nx=1\n```"
    kind, ans = heads.head_of(t)
    check("head_of type", kind == "coding", kind)
    check("head_of answer", "hash map" in ans, ans)
    box = heads.parse_region(t, 1000)  # 100/1000=0.1, pulled in 0.01 at each edge -> 0.11
    check("parse_region scaled + inset", box is not None and abs(box[0] - 0.11) < 1e-6, str(box))
    # within maps a box given in fractions of `outer` into screen coords (no clamp; region_box clamps)
    check("within maps into outer", heads.within((0.1, 0.1, 0.5, 0.5), (0.0, 0.0, 0.5, 1.0)) == (0.05, 0.1, 0.25, 0.5))
    # a TYPE inside a code block is not a head
    check("none head on yaml", heads.head_of("```\ntype: none\n```")[0] in ("none", "", "other") or True)


# ---------- 3. pipeline branches ----------
def make_pipeline():
    engines = make_engines(CONFIG)  # MockLocal + MockAnalyzer
    noop = lambda *a, **k: _async_none()
    hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                  confirm=_aconfirm_yes, agent_failed=_anoop)
    return Pipeline(engines, hooks), engines


async def _async_none():
    return None


async def _anoop(*a, **k):
    return None


async def _aconfirm_yes(*a, **k):
    return True


async def _delta(t):
    pass


async def test_pipeline():
    print("\n[pipeline]")
    from server.settings import SETTINGS
    # a spoken problem with nothing on screen, answered at once by the mock local
    pipe, eng = make_pipeline()
    SETTINGS.values["agent_mode"] = "off"
    out = await pipe.solve(1, None, "프로세스랑 스레드 차이 설명해줘", True, _delta)
    check("voice solved locally", out.engine == "local" and "프로세스" in out.text, out.text[:40])

    # a coding screen: mock local routes it deep; claude off -> local thinking pass
    frame = FakeFrame()
    SETTINGS.values["agent_mode"] = "off"
    out = await pipe.solve(2, frame, "", False, _delta)
    check("screen solved locally (deep)", out.engine == "local", out.engine)
    check("local outcome has region", out.region is not None, str(out.region))
    check("stages mark think", out.stages.get("think") is True, str(out.stages))

    # claude hard mode: the algorithm screen is handed to the mock Claude
    pipe2, eng2 = make_pipeline()
    SETTINGS.values["agent_mode"] = "hard"
    SETTINGS.values["agent_hard_types"] = ["algorithm", "coding", "math"]
    out = await pipe2.solve(3, FakeFrame(), "", False, _delta)
    check("hard mode routes algorithm to Claude", out.engine == "agent", out.engine)
    check("claude sent ledger present", any(x.get("to") == "agent" for x in out.sent), str(out.sent))

    # the crop payload needs no extra local pass; the text payload writes the problem out first
    SETTINGS.values["agent_payload"] = "crop"
    eng2.local.calls.clear()
    out = await pipe2.solve(31, FakeFrame(), "", False, _delta)
    what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
    check("crop payload: the problem part only, no extract pass",
          what.startswith("문제 부분 화면") and not any(c[0] == "extract" for c in eng2.local.calls), f"{what} {eng2.local.calls}")
    SETTINGS.values["agent_payload"] = "text"
    eng2.local.calls.clear()
    out = await pipe2.solve(32, FakeFrame(), "", False, _delta)
    what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
    check("text payload: written out first, text only",
          what.startswith("문제 글") and any(c[0] == "extract" for c in eng2.local.calls), f"{what} {eng2.local.calls}")
    SETTINGS.values["agent_payload"] = "crop"

    # claude all mode
    SETTINGS.values["agent_mode"] = "all"
    out = await pipe2.solve(4, FakeFrame(), "", False, _delta)
    check("all mode routes to Claude", out.engine == "agent", out.engine)

    # Claude declining the screen: it answers with words instead of the format, and no answer comes. With "This
    # PC's model answers when the agent declines" on (the default) the model on this PC solves the same screen,
    # what went out is still on the card, and the card is cleared first.
    from server.analyzer import AnalysisResult
    pipeR, engR = make_pipeline()
    staged = []

    async def _astage(seq, name, detail, restart=False):
        staged.append({"stage": name, "restart": restart})

    pipeR.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_astage,
                        confirm=_aconfirm_yes, agent_failed=_anoop)
    REFUSAL = "이 화면의 내용에는 답을 드리기 어렵습니다."

    async def _refuse(images, text, on_delta):
        await on_delta(REFUSAL)                    # it streams into the card before it is read
        return AnalysisResult(text=REFUSAL, usage=None, cost_usd=None, model="mock")

    engR.agent.run = _refuse
    SETTINGS.values["agent_mode"] = "all"
    out = await pipeR.solve(41, FakeFrame(), "", False, _delta)
    check("a refusal from Claude is answered by this PC's model instead",
          out.engine == "local" and REFUSAL not in out.text, f"{out.engine} {out.text[:40]}")
    check("and what did go to Claude is still on the card",
          any(x.get("to") == "agent" for x in out.sent), str(out.sent))
    check("and the card is told to throw away what Claude wrote",
          any(s["restart"] for s in staged), str(staged))
    check("and the refusal is on record", out.stages.get("agent_declined") is True, str(out.stages))

    # Off: the agent's reply is the card as it came, and this PC's model is not asked
    asked_local = []
    real_deep = engR.local.deep

    async def _deep_seen(*a, **k):
        asked_local.append(1)
        return await real_deep(*a, **k)
    engR.local.deep = _deep_seen
    SETTINGS.values["local_on_decline"] = False
    out = await pipeR.solve(43, FakeFrame(), "", False, _delta)
    check("with the switch off, a refusal is the card as it came, and this PC's model is not asked",
          out.engine == "agent" and REFUSAL in out.text and not asked_local and out.stages.get("agent_declined"),
          f"{out.engine} {out.text[:40]} {asked_local}")
    check("...and what went to Claude is on the card", any(x.get("to") == "agent" for x in out.sent), str(out.sent))
    SETTINGS.values.pop("local_on_decline", None)

    # On, but this PC's model fails on it: the problem still ends with the agent's reply, not an error
    async def _deep_fails(*a, **k):
        raise RuntimeError("the local model stopped")
    engR.local.deep = _deep_fails
    staged.clear()
    out = await pipeR.solve(44, FakeFrame(), "", False, _delta)
    check("this PC's model failing after a refusal leaves the agent's reply on the card",
          out.engine == "agent" and REFUSAL in out.text and out.stages.get("local_failed"), f"{out.engine} {out.stages}")
    check("...and the card is cleared of the local model's start first", any(s["restart"] for s in staged), str(staged))

    # On, and this PC's model writes nothing: the agent's words are the card
    async def _deep_empty(*a, **k):
        return AnalysisResult(text="", usage=None, cost_usd=None, model="mock")
    engR.local.deep = _deep_empty
    out = await pipeR.solve(45, FakeFrame(), "", False, _delta)
    check("this PC's model writing nothing after a refusal leaves the agent's reply", out.engine == "agent"
          and REFUSAL in out.text, f"{out.engine} {out.text[:40]}")
    engR.local.deep = real_deep

    # Off, and the agent said nothing at all: the card says so instead of standing empty
    async def _silent(images, text, on_delta):
        return AnalysisResult(text="", usage=None, cost_usd=None, model="mock")
    engR.agent.run = _silent
    SETTINGS.values["local_on_decline"] = False
    out = await pipeR.solve(46, FakeFrame(), "", False, _delta)
    check("an empty reply with the switch off says the agent gave no answer", out.engine == "agent"
          and out.text.strip() != "", repr(out.text[:60]))
    SETTINGS.values.pop("local_on_decline", None)

    # The agent alone (no model on this PC): its refusal is the card as it came
    engR.agent.run = _refuse
    pipeA = Pipeline(engR, Hooks(local_ok=lambda: False, agent_ok=lambda: True, notice=_anoop, stage=_astage,
                                  confirm=_aconfirm_yes, agent_failed=_anoop))
    out = await pipeA.solve(47, FakeFrame(), "", False, _delta)
    check("with no model on this PC, a refusal is the card as it came", out.engine == "agent" and REFUSAL in out.text,
          f"{out.engine} {out.text[:40]}")

    # an answer in the format is still Claude's: nothing above may hand a real answer to the local model
    pipeK, engK = make_pipeline()
    SETTINGS.values["agent_mode"] = "all"
    out = await pipeK.solve(42, FakeFrame(), "", False, _delta)
    check("an answer with a head stays Claude's", out.engine == "agent", out.engine)

    # confirm declined -> NotSent
    from server.pipeline import NotSent
    pipe3, _ = make_pipeline()
    pipe3.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                        confirm=_aconfirm_no, agent_failed=_anoop)
    SETTINGS.values["agent_mode"] = "all"
    SETTINGS.values["agent_confirm"] = True
    # with local on, a declined send falls back to the local thinking pass (not NotSent)
    out = await pipe3.solve(5, FakeFrame(), "", False, _delta)
    check("declined send falls back to local", out.engine == "local" and out.stages.get("not_sent"), str(out.stages))
    SETTINGS.values["agent_confirm"] = False
    SETTINGS.values["agent_mode"] = "off"


async def _aconfirm_no(*a, **k):
    return False


async def test_claude_brake():
    """The brake on asking Claude about nothing, over and over (server/pipeline.py: Spend).

    Seen in real use: 93 Claude turns in 21 minutes, every one of them 'nothing to
    solve', $3.61. Each one was reasonable on its own, so the test is about the row."""
    print("\n[claude brake]")
    from server.settings import SETTINGS
    from server.pipeline import NotSent
    pipe, _ = make_pipeline()
    said = []
    pipe.hooks = pipe.hooks.__class__(local_ok=lambda: False, agent_ok=lambda: True,
                                      notice=lambda t: _collect(said, t), stage=_anoop,
                                      confirm=_aconfirm_yes, agent_failed=_anoop)
    SETTINGS.values["agent_mode"] = "all"
    n = CONFIG.agent_empty_streak
    for _ in range(n - 1):
        pipe.spend.note(0.04, True)
    check(f"up to {n - 1} empty answers in a row, screens still go", pipe.spend.blocked() == "", pipe.spend.blocked()[:40])
    out = await pipe.solve(90, FakeFrame(), "", False, _delta)
    check("Claude still answers", out.engine == "agent", out.engine)

    for _ in range(n):
        pipe.spend.note(0.0, True)
    check(f"{n} empty answers in a row stop it", pipe.spend.blocked() != "", "(not blocked)")
    stopped = False
    try:
        await pipe.solve(91, FakeFrame(), "", False, _delta)
    except NotSent:
        stopped = True
    check("with Claude the only engine, nothing is sent", stopped, "sent anyway")
    check("the panel is told why it stopped", any("자동 전송 멈춤" in t for t in said), str(said)[:80])

    # Reanalyze goes through while the brake is on, without lifting it for everything else
    out = await pipe.solve(92, FakeFrame(), "", False, _delta, by_user=True)
    check("Reanalyze goes through the brake", out.engine == "agent", out.engine)
    check("and the automatic sends stay stopped all the same", pipe.spend.blocked() != "", "(not blocked)")

    pipe.spend.asked()      # a question or a drawn region
    check("a question asked lifts the brake", pipe.spend.blocked() == "", pipe.spend.blocked()[:40])
    out = await pipe.solve(93, FakeFrame(), "", False, _delta)
    check("once it is lifted, screens go again", out.engine == "agent", out.engine)

    # the hourly ceiling, counted from what each answer cost
    pipe.spend.asked()
    for _ in range(int(CONFIG.agent_hourly_usd / 0.05) + 1):
        pipe.spend.note(0.05, False)
    check("reaching the hourly ceiling stops it", "한도" in pipe.spend.blocked(), pipe.spend.blocked()[:40])
    out = await pipe.solve(94, FakeFrame(), "", False, _delta, by_user=True)
    check("at the ceiling, what is asked for by hand still goes", out.engine == "agent", out.engine)
    check("and the ceiling itself stays after that ask", "한도" in pipe.spend.blocked(), pipe.spend.blocked()[:40])
    pipe.spend.spent.clear()
    pipe.spend.asked()
    SETTINGS.values["agent_mode"] = "off"


async def _collect(bucket, text):
    bucket.append(text)


async def test_claude_knobs():
    """The model, the effort and the hourly ceiling are settings now, so the panel can move them
    without a restart (server/agents.py: claude_args reads them)."""
    print("\n[claude knobs]")
    from server.settings import SETTINGS
    from server.agents import claude_args
    from server.config import CONFIG
    was = (SETTINGS.get("agent_model_name"), SETTINGS.get("agent_effort"))
    SETTINGS.values["agent_model_name"] = ""
    SETTINGS.values["agent_effort"] = ""
    args = claude_args(CONFIG)
    check("nothing chosen: the CLI picks for itself", "--model" not in args and "--effort" not in args, " ".join(args[-4:]))
    # a family, not a version: the CLI takes `opus` as the newest Opus, so a new release needs no change here
    ok, err = SETTINGS.set("agent_model_name", "opus")
    check("a model can be chosen (a family name, which follows the newest release)", ok, err)
    ok, err = SETTINGS.set("agent_effort", "high")
    check("the effort can be chosen", ok, err)
    args = claude_args(CONFIG)
    check("what was chosen goes on the next CLI command",
          args[args.index("--model") + 1] == "opus" and args[args.index("--effort") + 1] == "high",
          " ".join(args[-4:]))
    # a version chosen before the list named families comes back as its family, so it follows the next release
    import json as _json, tempfile as _tmp
    from server.settings import Settings
    with _tmp.TemporaryDirectory() as d:
        f = __import__("pathlib").Path(d) / "s.json"
        f.write_text(_json.dumps({"claude_model_name": "claude-opus-5-5", "claude_mode": "all"}))
        old = Settings(f)
        old.load()
        check("an older settings file's version name and claude_ keys are read under the new names",
              old.get("agent_model_name") == "opus" and old.get("agent_mode") == "all",
              str((old.get("agent_model_name"), old.get("agent_mode"))))
    bad, _ = SETTINGS.set("agent_model_name", "gpt-made-up")
    check("a model not on the list is refused", not bad, "accepted")
    pipe, _ = make_pipeline()
    SETTINGS.values["agent_hourly_usd"] = 1.0
    for _ in range(21):
        pipe.spend.note(0.05, False)
    check("the spend ceiling is read from the settings too", "한도" in pipe.spend.blocked(), pipe.spend.blocked()[:40])
    SETTINGS.values["agent_hourly_usd"] = 0.0
    check("with no ceiling set it never stops", pipe.spend.blocked() == "", pipe.spend.blocked()[:40])
    SETTINGS.values["agent_hourly_usd"] = CONFIG.agent_hourly_usd
    SETTINGS.values["agent_model_name"], SETTINGS.values["agent_effort"] = was


# ---------- 4. code check harness ----------
RUNNER_ESM = __import__("re").compile(r"^\s*(import\s|import\{|export\s)", __import__("re").M)   # docker/runner.py


def runner_stub(lang, code, stdin):
    """Stand in for the runner sandbox with its own commands and flags (docker/runner.py LANGS: python3 -I -S,
    node with an ES module run as main.mjs, gcc -std=c11, g++ -std=c++23), shaping the reply like the real runner
    (server/app.py runner_exec / docker/runner.py)."""
    src, build, argv = {"python": ("main.py", None, ["python3", "-I", "-S", "main.py"]),
                        "javascript": ("main.js", None, ["node", "--max-old-space-size=512", "main.js"]),
                        "c": ("main.c", ["gcc", "-O2", "-std=c11", "-o", "a.out", "main.c", "-lm"], ["./a.out"]),
                        "cpp": ("main.cpp", ["g++", "-O2", "-std=c++23", "-o", "a.out", "main.cpp"], ["./a.out"]),
                        "bash": ("main.sh", None, ["bash", "main.sh"])}[lang]
    if lang == "javascript" and RUNNER_ESM.search(code):
        src, argv = "main.mjs", argv[:-1] + ["main.mjs"]
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, src), "w", encoding="utf-8") as f:
            f.write(code)
        if build:
            b = subprocess.run(build, cwd=d, capture_output=True, text=True, timeout=120)
            if b.returncode != 0 and lang == "cpp":   # the runner's C++17 try (docker/runner.py COMPILE_AGAIN)
                again = subprocess.run([x.replace("c++23", "c++17") for x in build], cwd=d, capture_output=True, text=True,
                                       timeout=120)
                b = again if again.returncode == 0 else b
            if b.returncode != 0:
                return {"ok": False, "stage": "compile", "exit": b.returncode, "stdout": b.stdout, "stderr": b.stderr}
        try:
            p = subprocess.run(argv, cwd=d, input=stdin.encode("utf-8"), capture_output=True, timeout=15)
            return {"ok": p.returncode == 0, "exit": p.returncode, "stdout": p.stdout.decode("utf-8", "replace"),
                    "stderr": p.stderr.decode("utf-8", "replace"), "stage": "run"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "timed_out": True, "stage": "run", "exit": -9, "stdout": "", "stderr": ""}


async def _run(lang, code, stdin):
    if isinstance(stdin, list):   # the runner's batch: compiled once, run on each input
        runs = [runner_stub(lang, code, x) for x in stdin]
        bad = next((r for r in runs if r.get("stage") == "compile"), None)
        return bad or {**runs[-1], "ok": all(r.get("ok") for r in runs), "runs": runs}
    return runner_stub(lang, code, stdin)


async def test_check():
    print("\n[code check]")
    from server.settings import SETTINGS
    SETTINGS.values["agent_mode"] = "off"
    SETTINGS.values["autocheck"] = True
    SETTINGS.values["run_button"] = True
    SETTINGS.values["extract"] = True
    SETTINGS.values["local_llm"] = True
    pipe, eng = make_pipeline()
    frame = FakeFrame()

    # a correct two_sum (matches MockLocal.cases) -> examples pass
    class Out:
        text = "TYPE: coding\nANSWER: hash map\n```python\ndef two_sum(nums, target):\n    seen={}\n    for i,n in enumerate(nums):\n        if target-n in seen: return [seen[target-n], i]\n        seen[n]=i\n```"
        crop_box = None
    res = await check_code(pipe, frame, Out(), _run)
    check("correct code passes all examples", res and res.get("passed") == res.get("total") and res.get("total") >= 2, str(res))

    # a wrong two_sum -> a failure is reported with the failing case
    class BadOut:
        text = "TYPE: coding\nANSWER: wrong\n```python\ndef two_sum(nums, target):\n    return [0, 0]\n```"
        crop_box = None
    res = await check_code(pipe, frame, BadOut(), _run)
    check("wrong code reports a failure", res and res.get("passed", 0) < res.get("total", 0) and res.get("fails"), str(res))

    # design 7: one retry with the failing example; the fixed code is checked on the same examples
    from server.pipeline import retry_request
    question, label = retry_request(res)
    check("retry request names the failing example", "[예제 실패]" in question and "[2, 7, 11, 15]" in question
          and label.startswith("예제가 맞지 않아 다시 풂"), question[:120])
    cases = res.get("cases")
    eng.local.calls.clear()

    class Fixed:
        text = "TYPE: followup\nANSWER: 고침\n```python\ndef two_sum(nums, target):\n    seen={}\n    for i,n in enumerate(nums):\n        if target-n in seen: return [seen[target-n], i]\n        seen[n]=i\n```"
        crop_box = None
    res2 = await check_code(pipe, frame, Fixed(), _run, cases=cases, any_type=True)
    check("retry: checked on the same examples, not read again",
          res2 and res2.get("passed") == res2.get("total") == len(cases["cases"]) and not any(c[0] == "cases" for c in eng.local.calls),
          f"{res2} {eng.local.calls}")
    check("retry head (followup) is not checked without any_type", checkable(pipe, frame, Fixed()) is None)

    # a non-coding answer is not checkable
    class Prose:
        text = "TYPE: essay\nANSWER: ...\nsome prose"
        crop_box = None
    check("prose is not checkable", checkable(pipe, frame, Prose()) is None)


async def test_check_langs():
    print("\n[code check in other languages]")
    from server.settings import SETTINGS
    SETTINGS.values.update(agent_mode="off", autocheck=True, run_button=True, extract=True, local_llm=True)
    pipe, eng = make_pipeline()
    frame = FakeFrame()

    def answer(lang, code, kind="coding"):
        return type("O", (), {"text": f"TYPE: {kind}\nANSWER: x\n```{lang}\n{code}\n```", "crop_box": None})()

    two_sum = {"function": "two_sum", "cases": [{"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
                                                {"args": [[3, 2, 4], 6], "expected": [1, 2]}]}
    cpp_ok = ("#include <string>\n#include <vector>\n\nusing namespace std;\n\n"
              "vector<int> two_sum(vector<int> nums, int target) {\n"
              "    for (int i = 0; i < (int)nums.size(); i++)\n"
              "        for (int j = i + 1; j < (int)nums.size(); j++)\n"
              "            if (nums[i] + nums[j] == target) return {i, j};\n    return {};\n}")
    res = await check_code(pipe, frame, answer("cpp", cpp_ok), _run, cases=two_sum)
    check("C++ (Programmers form): correct code passes", res and res.get("passed") == res.get("total") == 2
          and res.get("lang") == "cpp", str(res))
    res = await check_code(pipe, frame, answer("cpp", cpp_ok.replace("return {i, j};", "return {0, 0};")), _run,
                           cases=two_sum)
    check("C++: wrong code reports the failing example", res and res.get("passed") == 0 and res["fails"]
          and res["fails"][0]["got"] == [0, 0], str(res))
    leet = ("class Solution {\npublic:\n    vector<int> two_sum(vector<int>& nums, int target) {\n"
            "        unordered_map<int, int> seen;\n        for (int i = 0; i < (int)nums.size(); i++) {\n"
            "            if (seen.count(target - nums[i])) return {seen[target - nums[i]], i};\n"
            "            seen[nums[i]] = i;\n        }\n        return {};\n    }\n};\n"
            "int main() { Solution s; vector<int> v{1, 2}; s.two_sum(v, 3); return 0; }")
    res = await check_code(pipe, frame, answer("cpp", leet), _run, cases=two_sum)
    check("C++ class Solution with references and its own main: passes", res and res.get("passed") == 2, str(res))
    ptr = "#include <stdlib.h>\nint* two_sum(int nums[], size_t nums_len, int target) {\n    return 0;\n}"
    res = await check_code(pipe, frame, answer("cpp", ptr), _run, cases=two_sum)
    check("C++ with a pointer parameter: not run, and said why", res and "skipped" in res, str(res))
    res = await check_code(pipe, frame, answer("c", ptr), _run, cases=two_sum)
    check("C with a function to fill: not run, and said why", res and "skipped" in res, str(res))
    types = {"function": "f", "cases": [{"args": ["abc", "x", 2.5, [[1, 2], [3]], True], "expected": ["abc\"\n", "x", "y"]},
                                         {"args": ["", "q", 0.5, [], False], "expected": ["\"\n"]}]}
    cpp_types = ("vector<string> f(const string& s, char c, double d, vector<vector<int>> g, bool b) {\n"
                 "    vector<string> out{s + \"\\\"\\n\"};\n"
                 "    if (b && c == 'x' && d > 2 && g.size() == 2 && g[1][0] == 3) { out.push_back(string(1, c)); out.push_back(\"y\"); }\n"
                 "    return out;\n}")
    res = await check_code(pipe, frame, answer("cpp", cpp_types), _run, cases=types)
    check("C++ strings, chars, doubles, nested vectors, bools, and quotes and newlines in a result",
          res and res.get("passed") == 2, str(res))
    js_ok = ("function two_sum(nums, target) {\n  const seen = new Map();\n  for (let i = 0; i < nums.length; i++) {\n"
             "    if (seen.has(target - nums[i])) return [seen.get(target - nums[i]), i];\n    seen.set(nums[i], i);\n  }\n}")
    res = await check_code(pipe, frame, answer("javascript", js_ok), _run, cases=two_sum)
    check("JavaScript: correct code passes", res and res.get("passed") == 2 and res.get("lang") == "javascript", str(res))
    res = await check_code(pipe, frame, answer("js", js_ok.replace("return [seen.get(target - nums[i]), i];", "return [9];")),
                           _run, cases=two_sum)
    check("JavaScript: wrong code reports the failing example", res and res.get("passed") == 0
          and res["fails"][0]["got"] == [9], str(res))
    stdin = {"stdin": [{"input": "1 2\n", "output": "3"}, {"input": "5 7\n", "output": "12"}]}
    programs = {"cpp": "#include <iostream>\nint main() { long long a, b; std::cin >> a >> b; std::cout << a + b << std::endl; }",
                "c": "#include <stdio.h>\nint main(void) { long long a, b; scanf(\"%lld %lld\", &a, &b); printf(\"%lld\\n\", a + b); return 0; }",
                "javascript": "const [a, b] = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\nconsole.log(a + b);",
                "python": "a, b = map(int, input().split())\nprint(a + b)"}
    for lang, code in programs.items():
        res = await check_code(pipe, frame, answer(lang, code), _run, cases=stdin)
        check(f"standard input in {lang}: passes", res and res.get("how") == "stdin" and res.get("passed") == 2, str(res))
    stop = ("import os\ndef two_sum(nums, target):\n    if target == 6:\n        os._exit(3)\n    return [0, 1]")
    res = await check_code(pipe, frame, answer("python", stop), _run,
                           cases={"function": "two_sum", "cases": two_sum["cases"] + [{"args": [[1, 2], 3], "expected": [0, 1]}]})
    check("a run that stops partway: the examples after it count as failures", res and res.get("total") == 3
          and res.get("passed") == 1 and len(res["fails"]) == 2, str(res))
    broken = cpp_ok.replace("return {};", "return {}")
    res = await check_code(pipe, frame, answer("cpp", broken), _run, cases=two_sum)
    check("C++ that does not compile: said so", res and res.get("error", "").startswith("컴파일 오류"), str(res))
    snippet = "TYPE: coding\nANSWER: x\n```python\nprint([1, 2])\n```\n```cpp\n" + cpp_ok + "\n```"
    found = answer_code(snippet)
    check("the solution block, not a snippet before it", found and found[0] == "cpp", str(found))

    # answers whose code the check once ran or read wrong
    def text(*blocks):
        return "TYPE: algorithm\nANSWER: x\n" + "".join(f"```{lang}\n{code}\n```\n설명\n" for lang, code in blocks)

    async def run_text(t, cases):
        return await check_code(pipe, frame, type("O", (), {"text": t, "crop_box": None})(), _run, cases=cases)

    fast_io = "import sys\ninput = sys.stdin.readline"
    res = await run_text(text(("python", fast_io), ("python", fast_io + "\na, b = map(int, input().split())\nprint(a + b)")), stdin)
    check("a fast-input snippet before the full program: the program runs", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("python", fast_io), ("python", "def solution(a, b):\n    return a + b")),
                         {"function": "solution", "cases": [{"args": [1, 2], "expected": 3}]})
    check("a snippet before the function: the function runs", res and res.get("passed") == 1, str(res))
    three = {"function": "two_sum", "cases": two_sum["cases"] + [{"args": [[3, 3], 6], "expected": [0, 1]}]}
    res = await run_text(text(("python", "def two_sum(nums, target):\n    print('dbg', end=' ')\n"
                                         "    seen = {}\n    for i, n in enumerate(nums):\n"
                                         "        if target - n in seen: return [seen[target - n], i]\n        seen[n] = i")), three)
    check("output without a newline before a result does not shift the results", res and res.get("passed") == 3, str(res))
    res = await run_text(text(("cpp", cpp_ok.replace("    for (int i", "    cout << \"dbg \";\n    for (int i")
                                                .replace("#include <vector>", "#include <vector>\n#include <iostream>"))), three)
    check("C++ printing without a newline: results stay with their examples", res and res.get("passed") == 3, str(res))
    head = "#include <string>\n#include <vector>\n\nusing namespace std;\n\n"
    for name, code, cases in [
            ("a global named count", head + "int count = 0;\nint f(vector<int> v) {\n    for (int x : v) if (x > 0) count++;\n    return count;\n}",
             {"function": "f", "cases": [{"args": [[1, -2, 3]], "expected": 2}]}),
            ("globals left and right", head + "int left, right;\nint f(vector<int> v) {\n    left = 0; right = v.size();\n    return right - left;\n}",
             {"function": "f", "cases": [{"args": [[1, 2, 3]], "expected": 3}]}),
            ("a global y1", head + "int y1;\nint f(int n) {\n    y1 = n;\n    return y1;\n}", {"function": "f", "cases": [{"args": [3], "expected": 3}]}),
            ("a comment line above the function", head + "// 두 수의 합을 찾는 완전 탐색\n" + cpp_ok.split("using namespace std;\n\n")[1], two_sum),
            ("std:: names and an #include right above", "#include <vector>\nstd::vector<int> two_sum(std::vector<int> nums, int target) {\n"
             "    for (int i = 0; i < (int)nums.size(); i++)\n        for (int j = i + 1; j < (int)nums.size(); j++)\n"
             "            if (nums[i] + nums[j] == target) return {i, j};\n    return {};\n}", two_sum),
            ("#define int long long with signed main", "#include <bits/stdc++.h>\nusing namespace std;\n#define int long long\n"
             + cpp_ok.split("using namespace std;\n\n")[1] + "\nsigned main() { vector<int> v{1, 2}; two_sum(v, 3); return 0; }", two_sum),
            ("its own int32_t main", cpp_ok + "\nint32_t main() { return 0; }", two_sum),
            ("#define endl", "#include <bits/stdc++.h>\nusing namespace std;\n#define endl '\\n'\n" + cpp_ok.split("using namespace std;\n\n")[1], two_sum)]:
        res = await run_text(text(("cpp", code)), cases)
        check(f"C++ with {name}: checked and passes", res and res.get("passed") == res.get("total") == len(cases["cases"]), str(res))
    res = await run_text(text(("cpp", head + "int f(double x) {\n    return 1;\n}")), {"function": "f", "cases": [{"args": [10 ** 400], "expected": 1}]})
    check("a number too large for a double: not run, no exception", res and "skipped" in res, str(res))
    crash = cpp_ok.replace("    for (int i", "    if (target == 6) { volatile int* p = nullptr; *p = 1; }\n    for (int i")
    res = await run_text(text(("cpp", crash)), two_sum)
    check("C++ crashing on the second example: the first counts, the second says why",
          res and res.get("passed") == 1 and "segmentation fault" in str(res["fails"][0]["got"]), str(res))
    res = await run_text(text(("cpp", cpp_ok.replace("return {};", "undefined_thing(); return {};"))), two_sum)
    check("a compile error names the error line", res and "error:" in res.get("error", ""), str(res))
    res = await run_text(text(("cpp", head + "bool f(int n) {\n    return n % 2 == 0;\n}")),
                         {"function": "f", "cases": [{"args": [4], "expected": 1}, {"args": [4], "expected": True}]})
    check("true is not 1", res and res.get("passed") == 1, str(res))
    res = await run_text(text(("cpp", cpp_ok)), {"function": "two_sum()", "cases": two_sum["cases"]})
    check("a function name written with parentheses", res and res.get("passed") == 2, str(res))
    res = await run_text("TYPE: coding\nANSWER: x\n```python title=sol.py\ndef two_sum(nums, target):\n    return [0, 1]\n```\n", two_sum)
    check("a fence with more after the language", res and res.get("total") == 2, str(res))
    res = await run_text(text(("python", "def f(s):\n    return s + '\\u2028'")), {"function": "f", "cases": [{"args": ["a"], "expected": "a\u2028"}]})
    check("a line separator inside a result", res and res.get("passed") == 1, str(res))
    res = await run_text(text(("python", "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)\nexit(0)")), stdin)
    check("exit() in a Python program (the runner has no site module)", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("javascript", "var reverseString = function(s) {\n  s.reverse();\n};")),
                         {"function": "reverseString", "cases": [{"args": [["a", "b"]], "expected": ["b", "a"]}]})
    check("a function that changes its argument in place: checked on the changed argument",
          res and res.get("passed") == 1, str(res))
    res = await run_text(text(("javascript", "export function two_sum(nums, target) {\n  return target === 9 ? [0, 1] : [1, 2];\n}")), two_sum)
    check("a JavaScript ES module", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("cpp", "#include <iostream>\nint main() { int a, b; std::cin >> a >> b; std::cout << a + b; }")),
                         {"stdin": [{"input": "1 2", "output": "3"}]})
    check("C++ standard input without a final newline", res and res.get("passed") == 1, str(res))
    res = await run_text(text(("cpp", head + "int f(int n) {\n    return n;\n}")), stdin)
    check("standard input examples and a C++ function without main: not run, and said why", res and "skipped" in res, str(res))
    res = await run_text(text(("cpp", head + "double f(int a, int b) {\n    return (double)a / b;\n}")),
                         {"function": "f", "cases": [{"args": [1, 3], "expected": 0.333333}, {"args": [1, 3], "expected": 0.34}]})
    check("a fraction shown rounded passes, one off by more does not", res and res.get("passed") == 1, str(res))
    res = await run_text(text(("cpp", head + "#include <sstream>\nvector<vector<string>> f(vector<string> lines) {\n"
                                     "    vector<vector<string>> out;\n    for (auto& l : lines) { stringstream ss(l); string w; vector<string> r;"
                                     " while (ss >> w) r.push_back(w); out.push_back(r); }\n    return out;\n}")),
                         {"function": "f", "cases": [{"args": [["a b", "c"]], "expected": [["a", "b"], ["c"]]}]})
    check("a vector of vectors of strings as the result", res and res.get("passed") == 1, str(res))

    # more answers it once ran or read wrong
    add = {"function": "solution", "cases": [{"args": [1, 2], "expected": 3}, {"args": [5, 7], "expected": 12}]}
    res = await run_text(text(("python", "def solution(a, b):\n    total = a + b")), add)
    check("a Python function that forgets to return fails, not hidden", res and res.get("passed") == 0, str(res))
    res = await run_text(text(("javascript", "const solution = (a, b) => { a + b; };")), add)
    check("a JavaScript arrow that forgets to return fails", res and res.get("passed") == 0, str(res))
    res = await run_text(text(("python", "def solution(n):\n    return (n + 1) / 1")),
                         {"function": "solution", "cases": [{"args": [1000000], "expected": 1000000}]})
    check("a whole number off by one is not within a tolerance", res and res.get("passed") == 0, str(res))
    res = await run_text(text(("cpp", head + "#define int long long\nint f(int a, int b) {\n    return a + b;\n}")),
                         {"function": "f", "cases": [{"args": [1, 2], "expected": 3}]})
    check("C++ with Programmers' includes and #define int long long, no main", res and res.get("passed") == 1, str(res))
    res = await run_text(text(("python", "def solution(a, b):\n    raise ValueError('bad input ' + str(a))")), add)
    check("a Python error is named by its last line", res and res["fails"][0]["got"] == "ValueError: bad input 1", str(res))
    res = await run_text(text(("javascript", "function solution(a, b) {\n  if (a === 5) throw new Error('boom ' + a);\n  return a + b;\n}")), add)
    check("a JavaScript error inside a call is that example's result", res and res.get("passed") == 1
          and res["fails"][0]["got"] == "boom 5", str(res))
    res = await run_text(text(("cpp", "#include <iostream>\n#include <cstdlib>\nint main() { int a, b; std::cin >> a >> b; std::cout << a + b << std::endl; std::abort(); }")),
                         {"stdin": [{"input": "1 2", "output": "3"}]})
    check("a program that prints and then dies: the result says why", res and res.get("passed") == 0
          and "abort" in res["fails"][0]["got"], str(res))
    res = await run_text(text(("python", "from __future__ import annotations\na, b = map(int, input().split())\nprint(a + b)")), stdin)
    check("a Python program starting with from __future__", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("python", "from __future__ import annotations\ndef solution(a: int, b: int) -> int:\n    return a + b")), add)
    check("a Python function under from __future__", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("python", "def solution(a, b):\n    # 틀린 접근: 곱한다\n    return a * b"),
                              ("python", "def solution(a, b):\n    return a + b")), add)
    check("the last block defining the function runs (an approach shown first and dropped)", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("javascript", "class Solution {\n  solution(a, b) { return a + b; }\n}")), add)
    check("a JavaScript class Solution method", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("javascript", "class Solution {\n  solution = (a, b) => a + b;\n}")), add)
    check("a JavaScript class field holding an arrow", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("javascript", "class Solution {\n  static solution(a, b) { return a + b; }\n}")), add)
    check("a JavaScript static method", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("javascript", "const one = () => 1;\nconst solution = (a, b = one()) => a + b;")), add)
    check("a JavaScript arrow with a default that calls something", res and res.get("passed") == 2, str(res))
    res = await run_text(text(("python", "from sys import stdin\na, b = map(int, stdin.readline().split())\nprint(a + b)")), stdin)
    check("from sys import stdin", res and res.get("passed") == 2, str(res))
    listed = "TYPE: algorithm\nANSWER: x\n1. 풀이 코드:\n   ```python\n   def solution(a, b):\n       return a + b\n   ```\n"
    res = await run_text(listed, add)
    check("a fence indented inside a list", res and res.get("passed") == 2, str(res))


class FakeResp:
    def __init__(self, code, data):
        self.status_code, self._data = code, data

    def json(self):
        return self._data


class FakeOllama:
    """Ollama's native API as LocalLlmAnalyzer uses it: /api/ps and /api/generate (load, unload)."""

    def __init__(self, ps=None):
        self.ps = ps or []        # what /api/ps lists
        self.posts = []

    async def get(self, url, timeout=None):
        return FakeResp(200, {"models": self.ps}) if url.endswith("/api/ps") else FakeResp(404, {})

    async def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        return FakeResp(200, {})


async def test_verify():
    print("\n[verify mode]")
    from server.pipeline import NotSent
    from server.settings import SETTINGS
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="verify", agent_payload="crop", agent_confirm=False)
    out = await pipe.solve(41, FakeFrame(), "", False, _delta)
    check("verify mode: the local model solves (no Claude in solve)", out.engine == "local", out.engine)
    check("verifying() applies to a local answer", pipe.verifying(out))
    seen = {}

    def claude_says(reply):
        async def run(images, text, on_delta):
            seen.update(images=len(images), text=text)
            return type("R", (), {"text": reply, "model": "mock-claude", "usage": {"input_tokens": 10, "output_tokens": 3},
                                  "cost_usd": 0.001})()
        return run

    sent = []

    async def on_send(items):
        sent[:] = items
    eng.agent.run = claude_says("TYPE: verify\nANSWER: OK")
    res = await pipe.verify(41, FakeFrame(), "", False, out, on_send=on_send)
    check("verdict ok", res["verdict"] == "ok", str(res))
    check("payload is the crop, and the answer goes without its REGION line",
          seen["images"] == 1 and "[확인할 풀이]" in seen["text"] and "REGION:" not in seen["text"].split("[확인할 풀이]")[1],
          seen.get("text", "")[-200:])
    check("what was sent is listed", sent and sent[0]["to"] == "agent" and sent[0]["what"].startswith("문제 부분 화면"),
          str(sent))
    eng.agent.run = claude_says("TYPE: verify\nANSWER: O(n log n) 로 정렬 후 스윕\n경계 처리가 틀렸습니다.\n```python\npass\n```")
    res = await pipe.verify(41, FakeFrame(), "", False, out)
    check("verdict fix", res["verdict"] == "fix", res["verdict"])
    eng.agent.run = claude_says("이 요청에는 답하지 않겠습니다.")
    res = await pipe.verify(41, FakeFrame(), "", False, out)
    check("a reply in neither form is 'other' (shown as it is)", res["verdict"] == "other", res["verdict"])
    # a spoken problem goes as the question text only
    out_v = await pipe.solve(42, None, "프로세스랑 스레드 차이 설명해줘", True, _delta)
    eng.agent.run = claude_says("TYPE: verify\nANSWER: OK")
    res = await pipe.verify(42, None, "프로세스랑 스레드 차이 설명해줘", True, out_v, on_send=on_send)
    check("voice: question text only", seen["images"] == 0 and sent[0]["what"].startswith("들은 질문"), str(sent))
    # confirm before sending, declined: NotSent
    pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                       confirm=_aconfirm_no, agent_failed=_anoop)
    SETTINGS.values["agent_confirm"] = True
    try:
        await pipe.verify(41, FakeFrame(), "", False, out)
        check("confirm declined: not sent", False, "no NotSent")
    except NotSent:
        check("confirm declined: not sent", True)
    SETTINGS.values.update(agent_confirm=False, agent_mode="off")
    check("verifying() off in another mode", not pipe.verifying(out))


async def test_pipeline_fixes():
    """Faults of the pipeline, each as a check that failed before its fix."""
    print("\n[the verdict, the send record, a follow-up's confirm, the retry, a failed extraction]")
    from server.pipeline import NotSent, followup, verdict_of
    from server.settings import SETTINGS
    # 6: the verdict is read like the panel reads heads
    for text, want in [("TYPE: verify\n\nANSWER: OK", "ok"), ("TYPE: verify\nANSWER: **OK**", "ok"),
                       ("TYPE: verify\nANSWER: `OK`.", "ok"), ("확인했습니다.\nTYPE: verify\nANSWER: OK", "ok"),
                       ("TYPE: verify\nANSWER: 3", "fix"), ("이 요청에는 답하지 않겠습니다.", "other")]:
        check(f"verdict {text[:28]!r} -> {want}", verdict_of(text) == want, verdict_of(text))
    # 3: what goes out is on record before Claude is called, so a cancel afterwards keeps it
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="verify", agent_payload="crop", agent_confirm=False)
    out = await pipe.solve(51, FakeFrame(), "", False, _delta)
    order = []

    async def boom(images, text, on_delta):
        order.append("run")
        raise asyncio.CancelledError()

    async def on_send(items):
        order.append(("sent", items[0]["to"]))
    eng.agent.run = boom
    try:
        await pipe.verify(51, FakeFrame(), "", False, out, on_send=on_send)
    except asyncio.CancelledError:
        pass
    check("verify: sent is recorded before the call", order[:2] == [("sent", "agent"), "run"], str(order))
    # 2: a follow-up to Claude asks first when confirm before sending is on
    pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                       confirm=_aconfirm_no, agent_failed=_anoop)
    SETTINGS.values.update(agent_confirm=True, agent_mode="hard")
    last = {"frame": FakeFrame(), "crop_box": (0.1, 0.1, 0.6, 0.6), "engine": "agent", "text": "TYPE: coding\nANSWER: x"}
    try:
        await followup(pipe, last, "왜요?", last["text"], _delta, seq=52)
        check("follow-up to Claude: declined confirm is not sent", False, "sent without asking")
    except NotSent:
        check("follow-up to Claude: declined confirm is not sent", True)
    SETTINGS.values.update(agent_confirm=False, agent_mode="off")

    # 1, 4: the retry's conditions and the problem text's error reply, in the server module itself
    os.environ.setdefault("SIDENOTE_AUDIO", "0")
    import server.app as app_mod
    started = []

    async def fake_followup(app, question, retry=None):
        started.append(retry["label"])

    async def fake_check(*a, **k):
        return {"passed": 1, "total": 2, "how": "function", "fails": [{"input": [1], "expected": 2, "got": 3}],
                "cases": {"function": "f", "cases": []}}

    async def quiet(msg):
        pass
    saved = (app_mod.run_followup, app_mod.check_code, app_mod.broadcast)
    app_mod.run_followup, app_mod.check_code, app_mod.broadcast = fake_followup, fake_check, quiet
    try:
        SETTINGS.values.update(autocheck=True, run_button=True, extract=True, local_llm=True)
        for paused, frame_kept, auto, want in [(False, True, True, 1), (True, True, True, 0),
                                               (False, False, True, 0), (False, True, False, 0)]:
            started.clear()
            app_mod.STATE.paused = paused
            app_mod.STATE.last_result = {"id": 61, "frame": FakeFrame() if frame_kept else None}
            SETTINGS.values["autocheck"] = auto
            await app_mod.run_check(None, 61, FakeFrame(), None)
            if app_mod.STATE.retry_task is not None:
                await app_mod.STATE.retry_task
                app_mod.STATE.retry_task = None
            check(f"retry {'starts' if want else 'skipped'} (paused={paused}, screen kept={frame_kept}, autocheck={auto})",
                  len(started) == want, str(started))
        app_mod.STATE.paused = False
        SETTINGS.values["autocheck"] = True

        # 4: an extraction that fails still answers the panel
        class Boom:
            def _local(self):
                return object()

            async def problem_text(self, frame, box):
                raise RuntimeError("local LLM: HTTP 500")
        saved_pipe, app_mod.PIPELINE = app_mod.PIPELINE, Boom()
        app_mod.STATE.last_result = {"id": 62, "frame": FakeFrame(), "crop_box": None}
        reply = await app_mod.problem_text(62)
        check("problem text: a failed extraction still answers", reply.get("type") == "problem_text" and reply.get("error"),
              str(reply))
        app_mod.PIPELINE = saved_pipe
    finally:
        app_mod.run_followup, app_mod.check_code, app_mod.broadcast = saved
        app_mod.STATE.last_result = None


def test_window_clip():
    print("\n[window clipping]")
    from server.pipeline import crop_image
    from server.settings import SETTINGS
    frame = FakeFrame()
    frame.windows = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0)]   # two windows side by side
    box = (0.10, 0.10, 0.45, 0.60)                                 # the problem in the left one
    SETTINGS.values["roi_windows"] = True
    _, cut, _ = crop_image(frame, box)
    check("clipped at the window edge", abs(cut[2] - 0.5) < 1e-9, str(cut))
    SETTINGS.values["roi_windows"] = False
    _, cut, _ = crop_image(frame, box)
    check("switch off: margin runs into the next window", cut[2] > 0.5, str(cut))
    SETTINGS.values["roi_windows"] = True
    frame.windows = [(0.3, 0.0, 1.0, 1.0), (0.0, 0.0, 0.3, 1.0)]   # a narrow problem at the left of its window
    _, cut, _ = crop_image(frame, (0.31, 0.2, 0.37, 0.4))
    check("a wide left margin still picks the problem's window", abs(cut[0] - 0.3) < 1e-9, str(cut))

    from server.pipeline import Pipeline, clip_to_window, in_front, located
    side = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0)]
    got = clip_to_window((0.3, 0.1, 0.8, 0.5), side)
    check("a box over two windows goes to the one showing more of it", got == (0.5, 0.1, 0.8, 0.5), str(got))
    stack = [(0.4, 0.0, 1.0, 0.95), (0.0, 0.0, 1.0, 0.95)]   # a window in front of the right part of a maximized one
    got = clip_to_window((0.1, 0.1, 0.6, 0.5), stack)
    check("what a window in front covers does not count for the one behind", got == (0.1, 0.1, 0.6, 0.5)
          and in_front(got, stack) == [(0.4, 0.1, 0.6, 0.5)], f"{got} {in_front(got, stack)}")
    check("a box of the whole screen places nothing", located((0.0, 0.0, 1.0, 1.0)) is None
          and located((0.01, 0.01, 0.99, 0.99), side) is None)
    check("a box split between windows places nothing", located((0.3, 0.1, 0.7, 0.5), side) is None)
    check("a box in one window is kept", located((0.55, 0.1, 0.9, 0.5), side) == (0.55, 0.1, 0.9, 0.5)
          and located((0.3, 0.1, 0.7, 0.5)) == (0.3, 0.1, 0.7, 0.5))
    check("the fast pass's box goes through the same test",
          Pipeline._box("TYPE: coding\nREGION: 300 100 700 500\n", 1000, (0.0, 0.0, 1.0, 1.0), side) is None
          and Pipeline._box("TYPE: coding\nREGION: 550 100 900 500\n", 1000, (0.0, 0.0, 1.0, 1.0), side) is not None)
    # a messenger in front of the problem's window: its part of the crop is painted over, pixel for pixel
    red = io.BytesIO()
    Image.new("RGB", (200, 120), (255, 0, 0)).save(red, format="PNG")
    frame.full_png = red.getvalue()
    frame.windows = [(0.0, 0.3, 0.4, 1.0), (0.2, 0.0, 1.0, 1.0)]
    b64, cut, size = crop_image(frame, (0.45, 0.2, 0.9, 0.6))
    piece = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    ox, oy = int(cut[2] * 200) - piece.width, int(cut[3] * 120) - piece.height   # where the piece starts on the screen
    inside = [piece.getpixel((x - ox, y - oy)) for x in range(ox, int(0.4 * 200)) for y in range(int(0.3 * 120), int(cut[3] * 120))]
    outside = [piece.getpixel((x - ox, y - oy)) for x in range(int(0.4 * 200), int(cut[2] * 200)) for y in range(oy, int(cut[3] * 120))]
    check("the messenger's part of the crop is painted over", inside and all(p == (128, 128, 128) for p in inside),
          f"{cut} {set(inside)}")
    check("the rest of the crop is the screen", outside and all(p == (255, 0, 0) for p in outside), str(set(outside)))



async def test_crop_placement():
    print("\n[crop placement]")
    from server.pipeline import NotSent, crop_image, located
    from server.settings import SETTINGS
    # the capture program lists no desktop and no taskbar: what no window covers is the wallpaper
    check("a box running onto the wallpaper is kept",
          located((0.3, 0.2, 0.75, 0.5), [(0.0, 0.0, 0.6, 0.9556)]) == (0.3, 0.2, 0.75, 0.5))
    check("a box reaching the taskbar is kept",
          located((0.1, 0.85, 0.5, 1.0), [(0.0, 0.0, 1.0, 0.9556)]) == (0.1, 0.85, 0.5, 1.0))
    check("a box mostly on the wallpaper places nothing", located((0.25, 0.2, 0.9, 0.5), [(0.0, 0.0, 0.3, 0.9556)]) is None)
    # a window over the whole screen is a full-screen program (an F11 browser, a game), not the desktop
    full = (0.0, 0.0, 1.0, 1.0)
    check("a box in a full-screen program is kept", located((0.2, 0.2, 0.5, 0.5), [full]) == (0.2, 0.2, 0.5, 0.5))
    check("...also with a window in front of it",
          located((0.1, 0.2, 0.4, 0.6), [(0.6, 0.1, 0.9, 0.5), full]) == (0.1, 0.2, 0.4, 0.6))
    # a box the user drew is cut as drawn, whatever windows it covers
    frame = FakeFrame()
    red = io.BytesIO()
    Image.new("RGB", (200, 120), (255, 0, 0)).save(red, format="PNG")
    frame.full_png = red.getvalue()
    frame.windows = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0)]
    SETTINGS.values.update(roi_windows=True, roi_box=[0.3, 0.1, 0.8, 0.6])
    try:
        b64, cut, _ = crop_image(frame, (0.3, 0.1, 0.8, 0.6), 0.0)
        colours = set(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB").getdata())
        check("a drawn box is cut as drawn", cut == (0.3, 0.1, 0.8, 0.6) and colours == {(255, 0, 0)}, f"{cut} {colours}")
    finally:
        SETTINGS.values["roi_box"] = None
    # a window edge between two pixels: the next window's column stays out
    img = Image.new("RGB", (200, 120), (255, 0, 0))
    ImageDraw.Draw(img).rectangle((0, 0, 100, 119), fill=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    frame.full_png = buf.getvalue()
    frame.windows = [(0.0, 0.0, 0.5033, 1.0), (0.5033, 0.0, 1.0, 1.0)]
    b64, cut, _ = crop_image(frame, (0.6, 0.2, 0.9, 0.6))
    colours = set(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB").getdata())
    check("no column of the next window at the crop's edge", (0, 0, 255) not in colours, f"{cut} {colours}")

    # a box split between windows: Claude gets the problem written out, the duplicate check keeps the box
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="hard", agent_hard_types=["algorithm", "coding", "math"], agent_payload="crop")
    frame = FakeFrame()
    frame.windows = [(0.0, 0.0, 0.35, 1.0), (0.35, 0.0, 1.0, 1.0)]   # the mock's box (0.1 to 0.6) runs over both
    try:
        out = await pipe.solve(41, frame, "", False, _delta)
        what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
        check("split box: no crop, the problem as text", out.engine == "agent" and what.startswith("문제 글")
              and out.crop_box is None, f"{out.engine} {what} {out.crop_box}")
        check("split box: the duplicate check still has the box", out.region is not None, str(out.region))
        # ...but a box the windows do not agree with is not drawn on the panel: it would point at
        # wallpaper under the words "the highlighted part is where the problem was read".
        check("split box: the panel is not told to draw it", out.region_placed is False, str(out.region_placed))
        # ...and when the problem is not written out either, the local model takes it: the screen stays here
        notes = []

        async def note(t):
            notes.append(t)

        async def nothing(images=(), speech=""):
            return ""
        pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=note, stage=_anoop,
                           confirm=_aconfirm_yes, agent_failed=_anoop)
        eng.local.extract = nothing
        out = await pipe.solve(42, frame, "", False, _delta)
        check("not placed, not written out: the local model solves it", out.engine == "local" and out.stages.get("not_sent")
              and not any(x.get("to") == "agent" for x in out.sent), f"{out.engine} {out.sent}")
        check("...and the panel says why", any("문제 위치 못 찾음" in n for n in notes), str(notes))

        # written out from the whole screen with a number shaped like personal data (a messenger beside it): kept here
        async def with_rrn(images=(), speech=""):
            return "다음 배열의 최댓값을 구하시오. [3, 9, 4]\n김민지 주민번호 900101-1234567"
        eng.local.extract = with_rrn
        notes.clear()
        out = await pipe.solve(43, frame, "", False, _delta)
        check("personal data in the text from the whole screen: not sent, the local model solves",
              out.engine == "local" and out.stages.get("not_sent") and not any(x.get("to") == "agent" for x in out.sent),
              f"{out.engine} {out.sent}")
        check("...and the panel says why", any("주민번호" in n and "안 보냄" in n for n in notes), str(notes))
        SETTINGS.values["agent_mode"] = "verify"
        try:
            await pipe.verify(44, frame, "", False, out)
            check("verify: the same text is not sent either, with the reason", False, "sent")
        except NotSent as why:
            check("verify: the same text is not sent either, with the reason", "주민번호" in str(why), str(why))
        # the text of a crop is the problem's own window: the check is for the whole screen only
        SETTINGS.values.update(agent_mode="hard", agent_payload="text")
        out = await pipe.solve(45, FakeFrame(), "", False, _delta)   # no windows: the mock's box is cut
        what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
        check("text from a crop goes as it is", out.engine == "agent" and what.startswith("문제 글"), f"{out.engine} {what}")
        extracted = []

        async def counted(images=(), speech=""):
            extracted.append(1)
            return ""
        eng.local.extract = counted
        out = await pipe.solve(46, frame, "", False, _delta)
        check("text payload, nothing placed, nothing written out: one pass over the screen, not two",
              len(extracted) == 1 and out.engine == "local", f"{len(extracted)} {out.engine}")
    finally:
        SETTINGS.values.update(agent_mode="off", agent_payload="crop")

    from server.pipeline import personal_data
    shaped = ["900101-1234567", "주민번호 900101-1234567입니다", "900101 1234567", "900101 - 1234567", "010-9876-5432",
              "내 번호 010-1234-5678이야", "01098765432", "01098765432로 연락", "010 2345 6789", "010 - 1234 - 5678",
              "(010) 1234-5678", "(010)1234-5678", "010–1234–5678", "010－1234－5678", "+82 10 1234 5678", "+82-10-1234-5678",
              "02-123-4567", "02 1234 5678로 전화", "(02)123-4567", "02)123-4567", "(031)123-4567", "회사 031-123-4567로 전화",
              "4111-1111-1111-1111", "4111111111111111이에요", "2221-0000-0000-0009", "3782-822463-10005", "110-482-905117",
              "계좌 3333-01-1234567로 보내줘", "1002-337-215908", "123456-78-901234", "352-1234-5678-93"]
    plain = ["2026-10-25", "2026–10–25", "1.27.3", "172.16.4.21", "[1, 2, 1, 2, 3]", "978-89-1234-567-8", "cart-7d9f8b6c5d-x2kqp",
             "4111-1111-1111-1112", "5000 6000 7000 8000", "3000 4000 4500 4500", "3\n1200 3400\n5600 7800\n9100 2300",
             "09:00-10:30", "1 ≤ n ≤ 200,000", "2026-10-25-01", "2026-10-25 13:45", "1588-1234", "100-200-300-400",
             's = "0110101101"', "01011011010", '["119", "97674223", "1195524421"]', "1729843200000", "1705312345678",
             "0.9477089424570057", "8.3611277540470", "123456 1234567", "*/15 9-17 * * 1-5"]
    wrong = [t for t in shaped if not personal_data(t)] + [t for t in plain if personal_data(t)]
    check(f"numbers shaped like personal data ({len(shaped)}) told from others ({len(plain)})", not wrong, str(wrong))


async def test_editor_note():
    print("\n[the code editor's language goes along with a crop that leaves the editor out]")
    # The model keeps its problem box off the code editor, and Claude is given the crop and nothing else that
    # names a language: sent the problem part of ten screens with C++, Java, Kotlin, Go and JavaScript templates,
    # it answered in Python on every one (scratch/local-llm-bench/editor_crop.py). So the model on this PC, which
    # has the whole screen, names the language, and that one word goes along.
    from server import pipeline as pl
    from server.settings import SETTINGS
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="hard", agent_hard_types=["algorithm", "coding", "math"], agent_payload="crop")
    try:
        eng.local.editor = "C++"
        out = await pipe.solve(61, FakeFrame(), "", False, _delta)   # the mock reads every screen as an algorithm
        sent = eng.agent.calls[-1]["text"] if eng.agent.calls else ""
        what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
        check("a crop's request names the language", out.engine == "agent" and "C++" in sent and "그 언어로" in sent,
              f"{out.engine} {sent!r}")
        check("...and the card lists it with what went out", what.endswith("코드 언어 C++"), what)
        SETTINGS.values["agent_payload"] = "text"
        await pipe.solve(62, FakeFrame(), "", False, _delta)
        sent = eng.agent.calls[-1]["text"]
        check("the problem as text names it too, ahead of the problem so it is not read as part of it",
              "C++" in sent and "[문제]" in sent and sent.index("C++") < sent.index("[문제]"), sent[:240])
        # the whole screen shows Claude the editor itself
        SETTINGS.values["agent_payload"] = "screen"
        asked = sum(1 for c in eng.local.calls if c[0] == "editor")
        await pipe.solve(63, FakeFrame(), "", False, _delta)
        check("the whole screen goes without the question", sum(1 for c in eng.local.calls if c[0] == "editor") == asked)
        SETTINGS.values["agent_payload"] = "crop"
        eng.local.editor = ""
        await pipe.solve(64, FakeFrame(), "", False, _delta)
        check("no language named, no sentence", "그 언어로" not in eng.agent.calls[-1]["text"], eng.agent.calls[-1]["text"])
        check("a problem that is not code is not asked about",
              await pipe._editor_note(eng.local, ["x"], "essay") == ("", "")
              and await pipe._editor_note(eng.local, ["x"], "") == ("", ""))

        async def slow(images):
            await asyncio.sleep(5)
            return "Java"
        eng.local.editor_language = slow
        saved, pl.EDITOR_WAIT = pl.EDITOR_WAIT, 0.2
        began = time.perf_counter()
        try:
            out = await pipe.solve(65, FakeFrame(), "", False, _delta)
        finally:
            pl.EDITOR_WAIT = saved
        took = time.perf_counter() - began
        check("a reader that does not answer in time holds the answer up no longer than the bound",
              out.engine == "agent" and "Java" not in eng.agent.calls[-1]["text"] and took < 2.0, f"{out.engine} {took:.1f}s")

        async def broken(images):
            raise RuntimeError("the reader fell over")
        eng.local.editor_language = broken
        out = await pipe.solve(66, FakeFrame(), "", False, _delta)
        check("a reader that fails does not stop the answer", out.engine == "agent", out.engine)
    finally:
        SETTINGS.values.update(agent_mode="off", agent_payload="crop")
    # what the reader's answer may be, word by word: only a language becomes one
    from server.analyzer import LocalLlmAnalyzer
    reader = LocalLlmAnalyzer(CONFIG)
    said = {"C++": "C++", "Python 3": "Python", "`Java`": "Java", "Kotlin입니다": "Kotlin", "javascript": "JavaScript",
            "없음": "", "": "", "The editor is empty": "", "Go.": "Go"}
    got = {}
    for word in said:
        async def answer(system, images, text, max_tokens, word=word):
            return word
        reader._plain = answer
        got[word] = await reader.editor_language(["x"])
    check("the reader's word is a language or nothing", got == said, str({k: v for k, v in got.items() if said[k] != v}))
    await reader.aclose()


async def test_server_fixes():
    """Faults of the server, each a check that failed before its fix."""
    print("\n[server: retries, switches, the hour's ceiling and boxes while an analysis runs]")
    import dataclasses
    import json
    import types
    import server.app as app_mod
    from server.analyzer import AnalysisResult, FastResult, LocalLlmAnalyzer, MOCK_ALGO
    from server.agents import ClaudeCodeAgent
    from server.detector import make_detector
    from server.pipeline import followup
    from server.settings import SETTINGS

    class Panel:
        """A panel socket that keeps what the server broadcasts."""

        def __init__(self):
            self.msgs = []

        async def send_text(self, t):
            self.msgs.append(json.loads(t))

    st = app_mod.STATE
    saved_globals = (app_mod.ENGINES, app_mod.PIPELINE, app_mod.runner_exec)
    saved_state = (st.last_result, st.retry_task, st.voice_pending, st.voice_waiting, list(st.utterances), st.paused)
    saved_settings = dict(SETTINGS.values)
    panel = Panel()
    st.panel_clients.add(panel)
    try:
        # 1. The automatic retry's own code check, stopped by a newer analysis or by the pause, says so on its
        #    card. It ran after the retry had left the list of follow-ups, so the pause never reached it, and a
        #    newer analysis stopped it without the closing message: the card kept "running" for good.
        eng = make_engines(CONFIG)
        hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=app_mod.notice, stage=app_mod.stage,
                      confirm=app_mod.confirm_send, agent_failed=app_mod.agent_failed)
        app_mod.ENGINES, app_mod.PIPELINE = eng, Pipeline(eng, hooks)
        SETTINGS.values.update(local_llm=True, autocheck=True, run_button=True, extract=True, agent_mode="off")

        async def rewritten(image_b64, transcript, on_delta, extra=(), voice=False, followup=None):
            return AnalysisResult(text=MOCK_ALGO, model="mock-local")   # the retry's answer, with code in it
        plain_analyze, eng.local.analyze = eng.local.analyze, rewritten

        async def slow_runner(lang, code, stdin):
            await asyncio.sleep(3)                                       # the runner busy with the fixed code
            return {"stdout": "", "exit": 0}
        app_mod.runner_exec = slow_runner
        two_sum = {"function": "two_sum", "cases": [{"args": [[2, 7, 11, 15], 9], "expected": [0, 1]}]}
        for how in ("a newer analysis", "the pause"):
            panel.msgs.clear()
            st.last_result = {"text": MOCK_ALGO, "frame": FakeFrame(), "id": 100, "engine": "local",
                              "crop_box": None, "local_view": None}
            task = st.retry_task = asyncio.create_task(app_mod.run_followup(
                None, "[예제 실패] ...", retry={"label": "예제가 맞지 않아 다시 풉니다", "cases": two_sum}))
            rid = None
            for _ in range(200):                                         # until the retry's check is running
                await asyncio.sleep(0.02)
                rid = next((m["id"] for m in panel.msgs if m.get("type") == "check" and m.get("running")), None)
                if rid is not None:
                    break
            if how == "a newer analysis":
                app_mod.cancel_retry()               # what run_analysis does first
            else:
                app_mod.cancel_followups("pause")    # what the pause button does
            try:
                await asyncio.wait_for(asyncio.shield(task), 1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            stopped = task.done()
            if not stopped:
                task.cancel()
            mine = [m for m in panel.msgs if m.get("type") == "check" and m.get("id") == rid]
            check(f"the retry's code check stopped by {how} ends, and its card says so",
                  rid is not None and stopped and bool(mine) and mine[-1].get("cancelled") is True,
                  f"stopped={stopped} {mine}")
        st.retry_task = None
        app_mod.runner_exec = saved_globals[2]
        eng.local.analyze = plain_analyze        # the mock's own, which records the call checked below

        # 8. The retry of an answer this PC's model wrote is not held back by Claude's brake: it goes to the
        #    model that wrote the answer, and costs Claude nothing.
        panel.msgs.clear()
        eng.local.calls.clear()
        st.last_result = {"text": MOCK_ALGO, "frame": None, "id": 7, "engine": "local", "crop_box": None,
                          "local_view": None}
        app_mod.PIPELINE.spend.cool_until, app_mod.PIPELINE.spend.ran = time.time() + 300, 6
        SETTINGS.values.update(agent_mode="hard")
        await app_mod.run_followup(None, "[예제 실패] ...", retry={"label": "다시 풉니다", "cases": {}})
        check("the retry of a local answer goes to the local model even while Claude's brake holds",
              any(c[0] == "analyze" for c in eng.local.calls)
              and not any("에 자동 전송 멈춤" in (m.get("text") or "") for m in panel.msgs),
              f"{[c[0] for c in eng.local.calls]} {[m.get('text') for m in panel.msgs if m.get('type') == 'notice']}")
        app_mod.PIPELINE.spend.cool_until = 0.0

        # 2. Claude switched off after an analysis began: the engine was read once, at the start, and the
        #    first pass alone takes seconds, so the problem went to Claude anyway.
        pipe, eng2 = make_pipeline()
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               agent_hard_types=["algorithm", "coding", "math"])
        real_fast = eng2.local.fast

        async def slow_fast(*a, **k):
            await asyncio.sleep(0.4)                       # the first pass reading the screen
            return await real_fast(*a, **k)
        eng2.local.fast = slow_fast

        async def switch_off():
            await asyncio.sleep(0.15)
            SETTINGS.values["agent_mode"] = "off"         # what apply_setting stores
        before = len(eng2.agent.calls)
        flip = asyncio.create_task(switch_off())
        out = await pipe.solve(71, FakeFrame(), "", False, _delta)
        await flip
        check("Claude switched off during the first pass: the problem does not go to it",
              len(eng2.agent.calls) == before and out.engine == "local",
              f"{len(eng2.agent.calls) - before} call(s), answered by {out.engine}")
        # ...and the verify mode's check, switched off while the send waited to be confirmed
        eng2.local.fast = real_fast
        SETTINGS.values.update(agent_mode="verify", agent_confirm=False)
        answer = await pipe.solve(72, FakeFrame(), "", False, _delta)

        async def confirm_after_off(seq, preview):
            SETTINGS.values["agent_mode"] = "off"
            return True
        pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                           confirm=confirm_after_off, agent_failed=_anoop)
        SETTINGS.values.update(agent_confirm=True)
        before = len(eng2.agent.calls)
        try:
            await pipe.verify(72, FakeFrame(), "", False, answer)
            refused = False
        except NotSent:
            refused = True
        check("...nor does the verify mode's check of an answer, switched off before it went",
              refused and len(eng2.agent.calls) == before, f"refused={refused} {len(eng2.agent.calls) - before}")
        SETTINGS.values.update(agent_confirm=False)

        # 7. A Claude turn cut short by a newer screen still counts toward the hour's ceiling: its request was
        #    paid for, and with two cancels allowed in a row the ceiling saw one turn in three.
        pipe, eng3 = make_pipeline()
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop",
                               agent_hard_types=["algorithm", "coding", "math"])

        async def billed(images, text, on_delta):
            await on_delta("TYPE: algorithm\n")
            await asyncio.sleep(1.0)
            return AnalysisResult(text="TYPE: algorithm\nANSWER: x\n", cost_usd=0.08, model="m")
        eng3.agent.run = billed
        for i in range(2):
            t = asyncio.create_task(pipe.solve(80 + i, FakeFrame(), "", False, _delta))
            await asyncio.sleep(0.4)
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        check("Claude turns cut short by a newer screen count toward the hour's ceiling",
              len(pipe.spend.spent) == 2 and pipe.spend.hour_usd() > 0, f"{list(pipe.spend.spent)}")

        # 9. A follow-up to Claude about an answer it wrote from the problem as text carries that text again:
        #    with no image and no problem, Claude was asked about an answer to a problem it is not shown.
        pipe, eng4 = make_pipeline()
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="text",
                               agent_hard_types=["algorithm", "coding", "math"])
        f = FakeFrame()
        out = await pipe.solve(90, f, "", False, _delta)
        words = getattr(out, "words", "")
        check("an answer Claude wrote from the problem as text keeps that text", "nums 와 target" in words, repr(words))
        last = app_mod.remembered(out, f, 90) if hasattr(app_mod, "remembered") else {
            "frame": f, "crop_box": out.crop_box, "engine": out.engine, "text": out.text}
        await followup(pipe, last, "[예제 실패] 앞 풀이의 코드를 다시 쓰세요.", last["text"], _delta, seq=91)
        sent = eng4.agent.calls[-1]
        check("...and a follow-up to Claude about it sends that text with the question",
              not sent["images"] and "nums 와 target" in sent["text"], sent["text"][:200])

        # 6. The box the panel draws is the box it is told is placed. After the thinking pass the region was the
        #    first pass's box but whether it is placed was the thinking pass's own REGION, so a box over the
        #    wallpaper was drawn and a placed one was not.
        pipe, eng5 = make_pipeline()
        SETTINGS.values.update(local_llm=True, agent_mode="off", roi=True, roi_windows=True, roi_box=None,
                               local_think="auto")
        fr = FakeFrame()
        fr.windows = [(0.0, 0.0, 0.5, 1.0)]                 # one window on the left; the right half is wallpaper

        def fast_with(region):
            async def fast(images, text, on_delta, **k):
                return FastResult(text=None, head=f"TYPE: algorithm\nROUTE: deep\nANSWER: x\nREGION: {region}\n",
                                  type="algorithm", route="deep")
            return fast

        def deep_with(region):
            async def deep(images, text, on_delta, prior=None, think=True, on_thought=None):
                return AnalysisResult(text="TYPE: algorithm\nANSWER: x\n" + (f"REGION: {region}\n" if region else "")
                                      + "본문", model="m")
            return deep
        eng5.local.fast, eng5.local.deep = fast_with("600 100 950 600"), deep_with("50 100 450 600")
        out = await pipe.solve(92, fr, "", False, _delta)
        check("a first-pass box over the wallpaper is not drawn after the thinking pass",
              out.region is not None and out.region_placed is False, f"{out.region} {out.region_placed}")
        eng5.local.fast, eng5.local.deep = fast_with("50 100 450 600"), deep_with("")
        out = await pipe.solve(93, fr, "", False, _delta)
        check("a placed first-pass box is drawn although the thinking pass wrote no REGION",
              out.region is not None and out.region_placed is True, f"{out.region} {out.region_placed}")

        # 5. "TYPE: none" means the same with or without its newline. Without one the first pass came back with
        #    no type at all, and solve() takes "no type" and "none" for different things.
        reader = LocalLlmAnalyzer(CONFIG)

        async def ready(model):
            return None
        reader._ready = ready
        kinds = []
        for reply in ("TYPE: none", "TYPE: none\n"):
            async def run(messages, think, feed, shown, trace, reply=reply):
                for part in (reply[:4], reply[4:]):
                    await feed(part)
                return reply, None, "m", {"finish": "stop", "thought": ""}
            reader._run = run
            kinds.append((await reader.fast(["x"], "screen", _delta, want_region=False)).type)
        check("TYPE: none reads the same with or without its newline", kinds == ["none", "none"], str(kinds))
        # ...and a drawn region with nothing in it says so for either
        said = []
        for kind in ("", "none"):
            pipe, eng6 = make_pipeline()
            notes = []

            async def note(t, notes=notes):
                notes.append(t)
            pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=note, stage=_anoop,
                               confirm=_aconfirm_yes, agent_failed=_anoop)

            async def nothing(*a, kind=kind, **k):
                return FastResult(text="TYPE: none\n", head="TYPE: none\n", type=kind, route="")
            eng6.local.fast = nothing
            SETTINGS.values.update(local_llm=True, agent_mode="off", roi_box=[0.1, 0.1, 0.6, 0.6], local_think="auto")
            await pipe.solve(94, FakeFrame(), "", False, _delta)
            said.append(any("그린 영역 안에" in n for n in notes))
        SETTINGS.values["roi_box"] = None
        check("a drawn region with nothing in it says so whichever way the first pass wrote none", said == [True, True],
              str(said))

        # 10. On Python 3.10, which the image runs, the builtin TimeoutError raised for a load that takes too long
        #     is not asyncio.TimeoutError: it escaped the first pass as an error card instead of the screen being
        #     handed on.
        async def no_load(model):
            raise TimeoutError("local LLM: the model did not load within 180 s")
        reader._ready = no_load
        try:
            handed = (await reader.fast(["x"], "screen", _delta)).text is None
        except BaseException as exc:   # noqa: BLE001 - what escaped is the finding
            handed = f"{type(exc).__name__}: {exc}"
        await reader.aclose()
        check("a model load that takes too long hands the screen on instead of ending in an error", handed is True,
              str(handed))

        # 4a. A warm-session turn that ends in an error counts at its own cost, not at the session's running total.
        fake = str(pathlib.Path(__file__).resolve().parent / "fake_claude.py")
        cfg = dataclasses.replace(CONFIG, agent_bin=fake, cli_session=True, cli_timeout=10, cli_turn_budget=30,
                                  cli_session_turns=8)
        os.environ["FAKE_MODE"] = "error2"
        cli = ClaudeCodeAgent(cfg)
        first = await cli.run([], "first", _delta)
        try:
            await cli.run([], "second", _delta)
            failed = "no error"
        except Exception as exc:   # noqa: BLE001
            failed = getattr(exc, "cost_usd", None)
        await cli.aclose()
        check("a Claude turn that ends in an error counts at what that turn cost", first.cost_usd == 0.05 and failed == 0.05,
              f"{first.cost_usd} {failed}")
        # 4b. A model or effort change made while Claude writes an answer waits for that answer
        os.environ["FAKE_MODE"] = "slow"
        cli = ClaudeCodeAgent(cfg)
        writing = asyncio.create_task(cli.run([], "a problem", _delta))
        await asyncio.sleep(0.8)
        cli.reset_session()
        try:
            kept = (await writing).text
        except Exception as exc:   # noqa: BLE001
            kept = f"{type(exc).__name__}: {exc}"
        retired = cli._session._proc is None
        await cli.aclose()
        os.environ.pop("FAKE_MODE", None)
        check("changing Claude's model or effort lets the answer being written finish, then starts over",
              "ANSWER" in kept and retired, f"{kept!r} retired={retired}")

        # 3. Spoken problems switched off: one already queued is dropped, not answered afterwards.
        app = types.SimpleNamespace(state=types.SimpleNamespace(
            transcriber=types.SimpleNamespace(available=False), detector=make_detector(CONFIG, None)))
        st.local = {"ok": True}
        SETTINGS.values.update(local_llm=True, agent_mode="off", voice_auto=True)
        st.utterances = [{"start": 0, "end": 16000, "text": "해시맵이 뭔지 설명해 줘?", "ts": time.time()}]
        st.voice_pending = True
        await app_mod.apply_setting(app, "voice_auto", False)
        check("switching spoken problems off drops the one already queued", st.voice_pending is False,
              str(st.voice_pending))
        st.voice_pending = True                               # and one set some other way is not started either
        panel.msgs.clear()
        worker = asyncio.create_task(app_mod.analysis_worker(app))
        await asyncio.sleep(1.2)
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        started = [m for m in panel.msgs if m.get("type") == "analysis_start" and m.get("trigger") == "voice"]
        check("...and the worker starts no spoken problem while they are off", not started, str(started))

        # 11. The code editor's language is asked only once something is sure to go, and not for the verify
        #     mode's check, whose answer already shows the language.
        pipe, eng7 = make_pipeline()
        eng7.local.editor = "C++"
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="text", agent_confirm=False,
                               agent_hard_types=["algorithm", "coding", "math"], voice_auto=False)

        async def with_rrn(images=(), speech=""):
            return "다음 배열의 최댓값을 구하시오. [3, 9, 4]\n김민지 주민번호 900101-1234567"
        eng7.local.extract = with_rrn
        split = FakeFrame()
        split.windows = [(0.0, 0.0, 0.35, 1.0), (0.35, 0.0, 1.0, 1.0)]   # the mock's box runs over both
        await pipe.solve(95, split, "", False, _delta)
        check("a problem refused before it goes does not ask the editor's language first",
              not any(c[0] == "editor" for c in eng7.local.calls), str([c[0] for c in eng7.local.calls]))
        SETTINGS.values.update(agent_mode="verify", agent_payload="crop")
        answer = await pipe.solve(96, FakeFrame(), "", False, _delta)
        eng7.local.calls.clear()
        await pipe.verify(96, FakeFrame(), "", False, answer)
        check("the verify mode's check does not ask it either", not any(c[0] == "editor" for c in eng7.local.calls),
              str([c[0] for c in eng7.local.calls]))

        # 12. A setting the server refuses is sent back as it is stored, so the panel shows the value in force.
        panel.msgs.clear()
        ok, _err = await app_mod.apply_setting(app, "agent_hourly_usd", "not a number")
        back = [m for m in panel.msgs if m.get("type") == "settings" and "agent_hourly_usd" in m.get("values", {})]
        check("a refused setting is sent back as stored", not ok and bool(back)
              and back[-1]["values"]["agent_hourly_usd"] == SETTINGS.get("agent_hourly_usd"), str(back))
    finally:
        st.panel_clients.discard(panel)
        app_mod.ENGINES, app_mod.PIPELINE, app_mod.runner_exec = saved_globals
        (st.last_result, st.retry_task, st.voice_pending, st.voice_waiting, st.utterances, st.paused) = saved_state
        SETTINGS.values.clear()
        SETTINGS.values.update(saved_settings)
        os.environ.pop("FAKE_MODE", None)


async def test_local_zoom():
    """What the local thinking pass reads when no crop is placed (a 4K screen at 150% read at
    1600 px had `*/15` read as `*`). It stays on this PC, so a box over several windows is cut as it is, and a
    large screen goes in halves; Claude's crop is unchanged."""
    print("\n[local thinking pass: zoom when nothing is placed]")
    from server.analyzer import FastResult
    from server.settings import SETTINGS
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="off", roi=True, roi_windows=True, roi_box=None, local_think="auto")
    got = {}
    deep0 = eng.local.deep

    async def deep(images, text, on_delta, prior=None, think=True, on_thought=None):
        got.update(images=list(images), text=text)
        return await deep0(images, text, on_delta, prior=prior, think=think)
    eng.local.deep = deep

    def colours(b64):
        return set(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB").getdata())

    def screen(w, h):
        img = Image.new("RGB", (w, h), (255, 0, 0))
        ImageDraw.Draw(img).rectangle((int(w * 0.35), 0, w - 1, h - 1), fill=(0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        f = FakeFrame()
        f.full_png, f.width, f.height = buf.getvalue(), w, h
        f.windows = [(0.0, 0.0, 0.35, 1.0), (0.35, 0.0, 1.0, 1.0)]
        return f
    # the mock's box (0.1 to 0.6) runs over both windows: no crop for Claude, the box as it is for the thinking pass
    out = await pipe.solve(71, screen(200, 120), "", False, _delta)
    two = len(got.get("images", ())) == 2
    check("box over two windows: the thinking pass gets it as it is (both windows, nothing painted over)",
          two and colours(got["images"][1]) == {(255, 0, 0), (0, 0, 255)},
          f"{len(got.get('images', ()))} {colours(got['images'][1]) if two else ''}")
    check("...and nothing is placed for what goes out", out.crop_box is None, str(out.crop_box))

    async def whole(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
        return FastResult(text=None, head="TYPE: algorithm\nROUTE: deep\nANSWER: 목업\nREGION: 0 0 1000 1000\n",
                          type="algorithm", route="deep")
    eng.local.fast = whole
    got.clear()
    await pipe.solve(72, screen(3840, 2160), "", False, _delta)
    imgs = got.get("images", [])
    sizes = [Image.open(io.BytesIO(base64.b64decode(b))).size for b in imgs[1:]]
    check("4K, whole-screen box: the screen and its two halves", len(imgs) == 3 and "두 절반" in got.get("text", ""),
          f"{len(imgs)} images")
    check("...each half up to 1600 px, left then right", len(sizes) == 2 and all(max(s) <= 1600 for s in sizes)
          and {(255, 0, 0), (0, 0, 255)} <= colours(imgs[1]) and colours(imgs[2]) == {(0, 0, 255)}, str(sizes))
    check("...2160 px square each, so the halves overlap by 480 px at no cost in sharpness",
          sizes == [(1600, 1600), (1600, 1600)], str(sizes))

    def region(r):
        async def fast(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
            return FastResult(text=None, head=f"TYPE: algorithm\nROUTE: deep\nANSWER: 목업\nREGION: {r}\n",
                              type="algorithm", route="deep")
        return fast
    # the box a 4K screen at 100% got (its top half, over two windows): its crop would keep 0.42 of the
    # resolution, the halves 0.74
    eng.local.fast = region("0 0 1000 500")
    got.clear()
    await pipe.solve(75, screen(3840, 2160), "", False, _delta)
    check("4K, a box over two windows too large to read from its crop: the halves", len(got.get("images", ())) == 3,
          str(len(got.get("images", ()))))
    eng.local.fast = region("300 100 400 300")   # small, over two windows: its own crop is the sharper one
    got.clear()
    await pipe.solve(76, screen(3840, 2160), "", False, _delta)
    two = len(got.get("images", ())) == 2
    check("4K, a small box over two windows: its crop", two and {(255, 0, 0), (0, 0, 255)} <= colours(got["images"][1]),
          str(len(got.get("images", ()))))
    eng.local.fast = whole
    got.clear()
    await pipe.solve(73, screen(1920, 1080), "", False, _delta)
    check("1920 px, whole-screen box: the screen alone", len(got.get("images", ())) == 1 and "[확대]" not in got.get("text", ""),
          str(len(got.get("images", ()))))
    tall = screen(1440, 3840)
    got.clear()
    await pipe.solve(74, tall, "", False, _delta)
    sizes = [Image.open(io.BytesIO(base64.b64decode(b))).size for b in got.get("images", [])[1:]]
    check("a tall screen: no halves (its screen image keeps its whole width)", len(got.get("images", ())) != 3,
          str(sizes))
    got.clear()
    await pipe.solve(81, screen(3200, 3200), "", False, _delta)
    check("a square screen: no halves (they would be no sharper than the screen)", len(got.get("images", ())) != 3,
          str(len(got.get("images", ()))))
    # the model saw a part of the screen (SIDENOTE_CROP): halves of the screen would not be halves of its image
    narrowed = screen(3840, 2160)
    narrowed.model_box = (0.0, 0.0, 0.5, 1.0)

    async def no_box(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
        return FastResult(text=None, head="TYPE: algorithm\nROUTE: deep\nANSWER: 목업\n", type="algorithm", route="deep")
    eng.local.fast = no_box
    got.clear()
    await pipe.solve(77, narrowed, "", False, _delta)
    check("model image narrowed: no halves", len(got.get("images", ())) != 3, str(len(got.get("images", ()))))
    # a frame without its size (an older caller) still solves when the box is placed
    eng.local.fast = region("400 100 900 400")
    bare = screen(200, 120)
    del bare.width, bare.height
    got.clear()
    try:
        await pipe.solve(78, bare, "", False, _delta)
        check("a frame without width and height: the placed box is cut", len(got.get("images", ())) == 2,
              str(len(got.get("images", ()))))
    except AttributeError as exc:
        check("a frame without width and height: the placed box is cut", False, str(exc))

    # what may go out later is cut from the fast pass's box, not from the thinking pass's REGION (the thinking
    # pass writes it y first at times, or for the wrong image, and that can place another window)
    async def deep_elsewhere(images, text, on_delta, prior=None, think=True, on_thought=None):
        got.update(images=list(images), text=text)
        return type("R", (), {"text": "TYPE: algorithm\nANSWER: x\nREGION: 50 100 300 900\n풀이", "model": "m (think)",
                              "usage": None, "searches": []})()
    eng.local.deep = deep_elsewhere
    eng.local.fast = region("400 100 900 400")   # placed in the right window
    out = await pipe.solve(79, screen(200, 120), "", False, _delta)
    check("crop_box: the fast pass's placed box, not the thinking pass's REGION in the other window",
          out.crop_box is not None and out.crop_box[0] >= 0.35, str(out.crop_box))
    check("a placed box is drawn on the panel", out.region_placed is True, str(out.region_placed))
    eng.local.fast = region("100 100 600 700")   # over both windows: placed nowhere
    out = await pipe.solve(80, screen(200, 120), "", False, _delta)
    check("...and nothing when the fast pass placed nothing, whatever the thinking pass wrote", out.crop_box is None,
          str(out.crop_box))
    check("...the duplicate check watches the fast pass's box", out.region is not None and out.region[0] < 0.2
          and out.region[2] > 0.5, str(out.region))
    check("...and the local readers get the box the thinking pass read", out.local_view is not None
          and abs(out.local_view[0] - 0.1) < 1e-6, str(out.local_view))
    read = []

    async def cases(images=(), problem=""):
        read.append(images)
        return {}
    eng.local.cases = cases
    from server.pipeline import check_code
    out.text = "TYPE: coding\nANSWER: x\n```python\ndef f(x):\n    return x\n```"
    SETTINGS.values.update(autocheck=True)

    async def run(*a):
        return {}
    await check_code(pipe, screen(200, 120), out, run)
    got_size = Image.open(io.BytesIO(base64.b64decode(read[0][0]))).size if read and read[0] else None
    check("the code check reads that box, not the whole screen", got_size is not None and got_size[0] < 200,
          str(got_size))
    eng.local.fast = no_box   # the fast pass gave no box: what goes out never comes from the thinking pass's REGION
    out = await pipe.solve(82, screen(200, 120), "", False, _delta)
    check("no box from the fast pass: nothing goes out by the thinking pass's REGION", out.crop_box is None,
          str(out.crop_box))
    eng.local.deep = deep
    SETTINGS.values.update(agent_mode="off")


async def test_asked_again_halves():
    """Asked again on a screen the first look found nothing on, the screen is read once more in halves.

    The fast pass is the only pass a screen gets when it says there is nothing to solve, and it is
    given one shrunk image of the whole screen. That is how a problem in a narrow window beside a
    full editor is missed: `roi_tall_2160` of section 11 is read as empty on 3 runs of 3 from the
    screen and on 0 of 3 from its halves. The second look costs about three times the first, so it
    is only for a screen asked about by hand: 1,001 of 1,014 screens in a day's log held nothing.
    """
    print("\n[asked again: a second look in halves]")
    from server.analyzer import FastResult
    from server.settings import SETTINGS
    pipe, eng = make_pipeline()
    SETTINGS.values.update(agent_mode="off", roi=True, roi_windows=True, roi_box=None, local_think="auto")
    seen: list = []

    async def nothing(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
        """Empty the first time it is asked, and the problem once it is given more than one image:
        the mock stands in for a model that cannot read the narrow window in a shrunk screen."""
        seen.append(len(images))
        if len(images) == 1:
            return FastResult(text="", head="TYPE: none\n", type="", route="")
        return FastResult(text="42", head="TYPE: calc\nANSWER: 42\nREGION: 100 100 300 300\n",
                          type="calc", route="fast")
    eng.local.fast = nothing

    big = FakeFrame(3840, 2160)        # wide enough that halves keep more of the screen (halves_help)
    small = FakeFrame(1280, 800)       # halves gain nothing here, so there is nothing to look at twice

    seen.clear()
    out = await pipe.solve(120, big, "", False, _delta)
    check("the watching takes the first answer and does not pay for a second look",
          seen == [1] and not out.stages.get("halves"), f"{seen} stages={out.stages}")

    seen.clear()
    out = await pipe.solve(121, big, "", False, _delta, by_user=True)
    check("asked again, a screen with nothing on it is read once more in halves",
          len(seen) == 2 and seen[1] > 1, str(seen))
    check("...and the problem the halves show is the answer", "42" in (out.text or ""), f"{out.text!r}")
    check("...and the card is told the halves were looked at", bool(out.stages.get("halves")), str(out.stages))

    seen.clear()
    await pipe.solve(122, small, "", False, _delta, by_user=True)
    check("a screen whose halves would gain nothing is not read twice", seen == [1], str(seen))

    seen.clear()
    SETTINGS.values.update(roi_box=[0.1, 0.1, 0.5, 0.5])
    await pipe.solve(123, big, "", False, _delta, by_user=True)
    check("a drawn region is not read in halves either", seen == [1], str(seen))
    SETTINGS.values.update(roi_box=None)

    seen.clear()
    eng.local.fast = lambda *a, **k: _answered()
    SETTINGS.values.update(agent_mode="off")


async def _answered():
    from server.analyzer import FastResult
    return FastResult(text="x", head="TYPE: calc\nANSWER: x\n", type="calc", route="fast")


async def test_local_engine():
    print("\n[local engine]")
    from server.analyzer import LocalLlmAnalyzer
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    # the llamacpp runner's sizes leave out most of the model: no size is shown rather than a wrong one
    local._client = FakeOllama([{"name": "sidenote-gemma4:26b", "size": 1456304290, "size_vram": 1456304290,
                                 "runner": "llamacpp"}])
    got = await local.loaded()
    check("llamacpp runner: loaded model without a size", got == {"model": "sidenote-gemma4:26b", "vram_gb": None}, str(got))
    local._client = FakeOllama([{"name": "m", "size": 5_000_000_000, "size_vram": 5_000_000_000}])
    got = await local.loaded()
    check("other runner: size from size_vram", got == {"model": "m", "vram_gb": 5.0}, str(got))


class StuckOllama:
    """The model's server as LocalLlmAnalyzer talks to it (/api/ps, a load, the streamed chat, a one-token request,
    keep_alive 0). `stuck`: its runner answers nothing until the model has been taken off this many times (True is
    once), and the one-token request gets nothing meanwhile either; `slow`: a runtime that is only slow, its first token
    after this many seconds; `probe` "silent": the one-token request gets no slot however healthy the runtime (both are
    held by this server's requests); `after_unload`: what the waiting request gets once let go ("answer": the new runner
    answers it, as Ollama did on a runner frozen with SIGSTOP; "error": it ends in a 500); `unload_delay`: how long
    keep_alive 0 takes to answer; `ps`: what /api/ps lists; `stream_for`: how long the answer streams after its first
    token, as a thinking pass does for minutes. A request whose runner is taken off while it streams breaks off."""

    def __init__(self, stuck=0, slow=0.0, after_unload="answer", probe="auto", unload_delay=0.0,
                 ps=("sidenote-gemma4:26b",), stream_for=0.0):
        import httpx2
        self.httpx2 = httpx2
        self.stuck, self.slow, self.after_unload = int(stuck), slow, after_unload
        self.probe, self.unload_delay, self.ps, self.stream_for = probe, unload_delay, ps, stream_for
        self.let_go = asyncio.Event()          # set at each unload, for the requests waiting on it
        self.probes, self.unloads, self.streams = [], [], 0

    def stuck_now(self):
        return len(self.unloads) < self.stuck

    async def get(self, url, timeout=None):   # /api/ps
        return FakeResp(200, {"models": [{"name": n} for n in self.ps]})

    async def post(self, url, json=None, timeout=None):
        if json.get("keep_alive") == 0:        # taken off: the frozen runner is ended and another started
            self.unloads.append(json["model"])
            self.let_go.set()
            await asyncio.sleep(self.unload_delay)
            return FakeResp(200, {"done_reason": "unload"})
        if "messages" not in json:              # a load
            return FakeResp(200, {})
        self.probes.append(time.time())        # the one-token request
        if self.probe == "silent" or self.stuck_now():
            await asyncio.sleep(timeout)        # nothing comes: the client's own limit ends it
            raise self.httpx2.ReadTimeout("")
        return FakeResp(200, {"choices": [{"message": {"content": "2"}}]})

    def stream(self, method, url, json=None):
        outer = self

        class Resp:
            status_code = 200

            async def __aenter__(self):
                outer.streams += 1
                if outer.stuck_now():
                    while outer.stuck_now():     # nothing until the model is taken off (often enough)
                        outer.let_go.clear()
                        await outer.let_go.wait()
                    if outer.after_unload == "error":
                        self.status_code = 500
                elif outer.slow:
                    await asyncio.sleep(outer.slow)
                return self

            async def __aexit__(self, *a):
                return False

            async def aread(self):
                return b'{"error":"llama runner process has terminated"}'

            async def aiter_lines(self):
                dumps = __import__("json").dumps
                gone = len(outer.unloads)
                yield "data: " + dumps({"choices": [{"delta": {"reasoning": "생각"}}]})   # thinking, from the first token
                end = time.time() + outer.stream_for
                while time.time() < end:
                    await asyncio.sleep(0.05)
                    if len(outer.unloads) > gone:   # its runner was taken off under it
                        raise outer.httpx2.RemoteProtocolError("peer closed connection")
                    yield "data: " + dumps({"choices": [{"delta": {"reasoning": "."}}]})
                for word in ("TYPE: calc\n", "ANSWER: 2\n"):
                    yield "data: " + dumps({"choices": [{"delta": {"content": word}}]})
                yield "data: [DONE]"
        return Resp()

    async def aclose(self):
        pass


async def test_stuck_runtime():
    print("\n[a model's server that answers nothing is taken off and answers again]")
    # A thinking pass once stopped inside an image's encoding and the runtime answered nothing more, not
    # even a one-line request, until the model was taken off; every request waited out local_timeout (180 s) and ended
    # in an error. Measured on a frozen runner (scratch/local-llm-bench/stuck_probe.py): keep_alive 0 makes Ollama end
    # it, start another and hand that one the waiting request.
    import dataclasses
    import server.telemetry as telemetry
    from server.analyzer import LocalLlmAnalyzer
    # (only the limits this server has: the same check run on a server without the stuck check waits until its bound)
    cfg = dataclasses.replace(CONFIG, **{k: 0.3 for k in ("local_stuck_sec", "local_probe_sec") if hasattr(CONFIG, k)})
    events = []
    plain = telemetry.event
    telemetry.event = lambda name, **f: events.append((name, f))
    try:
        async def ask(fake, other=None):
            local = LocalLlmAnalyzer(cfg)
            await local._client.aclose()
            local._client = fake
            if other is not None:                # another request of this server streaming meanwhile
                local._heard = 0.0
                other(local)
            out = []

            async def keep(t):
                out.append(t)
            t = time.time()
            try:   # bounded: a server without the check waits on the stuck request for good
                text, _, _, _ = await asyncio.wait_for(
                    local._stream(local._body([{"role": "user", "content": "x"}], False, None), keep), 5)
            except asyncio.TimeoutError:
                text = ""
            except Exception as exc:   # a failure is that check's, not the end of the others
                text = f"<{type(exc).__name__}>"
            return text, time.time() - t, local

        fake = StuckOllama(stuck=True)
        text, took, local = await ask(fake)
        check("stuck: the model is taken off once", fake.unloads == ["sidenote-gemma4:26b"], str(fake.unloads))
        check("...after the wait and one unanswered one-token request", len(fake.probes) == 1 and 0.55 < took < 2.0,
              f"{fake.probes} {took:.2f}")
        check("...and the request that waited is answered by the new runner", text == "TYPE: calc\nANSWER: 2\n", text)
        check("...on record as local_stuck", any(n == "local_stuck" and f.get("unloaded") for n, f in events), str(events))

        fake = StuckOllama(slow=1.0)
        events.clear()
        text, took, _ = await ask(fake)
        check("slow, not stuck: the one-token request is answered and nothing is taken off",
              fake.probes and not fake.unloads and text.endswith("ANSWER: 2\n"), f"{fake.probes} {fake.unloads}")
        check("...and the request is not sent again", fake.streams == 1, str(fake.streams))
        check("...and nothing on record", not any(n == "local_stuck" for n, _ in events), str(events))

        fake = StuckOllama(slow=1.0)

        def streaming(local):   # tokens keep coming for another request of this server: no one-token request at all
            async def beat():
                while True:
                    local._heard = time.time()
                    await asyncio.sleep(0.05)
            local._beat = asyncio.ensure_future(beat())
        text, took, local = await ask(fake, other=streaming)
        local._beat.cancel()
        check("waiting behind another request that streams: no one-token request", not fake.probes, str(fake.probes))

        fake = StuckOllama(stuck=True, after_unload="error")
        text, took, _ = await ask(fake)
        check("taken off and then failed with nothing streamed: sent once more, to the new runner",
              fake.streams == 2 and text.endswith("ANSWER: 2\n") and fake.unloads, f"{fake.streams} {text!r}")

        fake = StuckOllama()
        text, took, _ = await ask(fake)
        check("a runtime that answers: no one-token request, nothing taken off",
              not fake.probes and not fake.unloads and took < 0.3, f"{fake.probes} {took:.2f}")

        # two requests waiting on one stuck runner: one check, one unload, both answered
        fake = StuckOllama(stuck=True)
        local = LocalLlmAnalyzer(cfg)
        await local._client.aclose()
        local._client = fake

        async def drop(_):
            pass
        try:
            both = await asyncio.wait_for(asyncio.gather(
                *(local._stream(local._body([{"role": "user", "content": str(i)}], False, None), drop)
                  for i in range(2))), 5)
        except asyncio.TimeoutError:
            both = [("",)] * 2
        check("two requests on one stuck runner: one unload, both answered",
              fake.unloads == ["sidenote-gemma4:26b"] and all(b[0].endswith("ANSWER: 2\n") for b in both),
              f"{fake.unloads} {[b[0] for b in both]}")

        # Each of these failed before its fix:
        # 1. the first token came while the one-token request waited without a slot: the model stays
        fake = StuckOllama(slow=0.45, probe="silent", stream_for=0.6)
        text, took, _ = await ask(fake)
        check("its first token came while the one-token request waited for a slot: nothing is taken off",
              fake.probes and not fake.unloads and text.endswith("ANSWER: 2\n"), f"{fake.probes} {fake.unloads} {text!r}")
        # 2. taken off by the check, then let go on purpose (the panel's release) while the request waited on the new
        #    runner: the request that fails by that is not sent again, which would load the model back
        fake = StuckOllama(stuck=2, after_unload="error")
        local = LocalLlmAnalyzer(cfg)
        await local._client.aclose()
        local._client = fake
        run = asyncio.ensure_future(local._stream(local._body([{"role": "user", "content": "x"}], False, None), drop))
        for _ in range(100):
            if fake.unloads:
                break
            await asyncio.sleep(0.02)
        await local.unload("sidenote-gemma4:26b")   # the panel's release gives the GPU back
        try:
            await asyncio.wait_for(run, 5)
            outcome = "answered"
        except Exception as exc:
            outcome = type(exc).__name__
        check("let go on purpose after the check took the model off: the request that failed is not sent again",
              outcome == "LocalServerError" and fake.streams == 1, f"{outcome} {fake.streams} {fake.unloads}")
        # 3. the request failed as its runner ended, before keep_alive 0 was answered: sent again all the same
        fake = StuckOllama(stuck=True, after_unload="error", unload_delay=0.5)
        text, took, _ = await ask(fake)
        check("failed before the unload was answered: sent again, to the new runner",
              fake.streams == 2 and text.endswith("ANSWER: 2\n"), f"{fake.streams} {text!r}")
        # 4. the model not on the GPU (being loaded): no one-token request, nothing taken off
        fake = StuckOllama(slow=0.9, probe="silent", ps=())
        text, took, _ = await ask(fake)
        check("a model being loaded is not stuck: no one-token request, nothing taken off",
              not fake.probes and not fake.unloads and text.endswith("ANSWER: 2\n"), f"{fake.probes} {fake.unloads}")
        # 5. stuck again on the runner that took the request over: taken off again, then answered
        fake = StuckOllama(stuck=2)
        text, took, _ = await ask(fake)
        check("stuck again on the new runner: taken off a second time, then answered",
              len(fake.unloads) == 2 and text.endswith("ANSWER: 2\n"), f"{fake.unloads} {text!r} {took:.2f}")
        # but not without end: one that never comes back is taken off twice, then left to local_timeout as before (with
        # limits much shorter than the defaults a runtime only slow to start was taken off four times running)
        fake = StuckOllama(stuck=5)
        text, took, _ = await ask(fake)
        check("a request's watch takes the model off twice at most", len(fake.unloads) == 2 and text == "",
              f"{fake.unloads} {text!r}")
    finally:
        telemetry.event = plain


async def _record(into: list, model):
    into.append(model)
    return True


async def test_gpu_pace():
    print("\n[busy GPU switch]")
    import time
    from pathlib import Path
    from server.analyzer import GpuPace, LocalLlmAnalyzer
    from server.settings import SETTINGS
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".pace.json"
        pace = GpuPace(CONFIG, path)
        check("short answers are not measured", pace.record("big", 50, 0.1) is False and not pace.rates)
        check("a burst is not measured", pace.record("big", 400, 0.2) is False and not pace.rates)
        for r in (1730, 1500, 1600):                          # 150 to 173 tokens/s, the free GPU
            pace.record("big", r, 10.0)
        check("a normal answer is not busy", pace.record("big", 1400, 10.0) is False and not pace.busy())
        check("4.6 times slower is busy", pace.record("big", 375, 10.0) is True and pace.busy(), str(pace.last))
        check("a slow rate does not lower the usual one", pace.usual("big") == 160.0, str(pace.rates))
        check("usual rates kept across restarts", GpuPace(CONFIG, path).usual("big") == 160.0, path.read_text())
        pace.rates["big"] = [150.0, 160.0, 900.0]             # one odd figure does not set the bar
        check("one odd rate does not make every answer slow", pace.record("big", 1400, 10.0) is False)
    # A busy spell that goes on (a video call): each retry right after a hold finds the GPU busy again
    pace = GpuPace(CONFIG, None)
    base, top = CONFIG.local_busy_hold_sec, max(CONFIG.local_busy_hold_sec, CONFIG.local_busy_hold_max_sec)
    pace.timed_out("big")
    first = pace.held
    pace.timed_out("big")                                     # another request on the slow model, in the hold
    during = pace.held
    holds = []
    for _ in range(8):
        pace.busy_until = time.time() - 5                     # the hold ran out 5 s ago, the big model tried again
        pace.timed_out("big")
        holds.append(pace.held)
    check("the first busy verdict holds for the base time", first == base, f"{first} vs {base}")
    check("a verdict during the hold keeps its length", during == base, str(during))
    check("each retry that finds the GPU still busy doubles the hold, up to the longest",
          holds[:4] == [base * 2, base * 4, base * 8, base * 16] and holds[-1] == top and max(holds) == top, str(holds))
    pace.busy_until = time.time() - pace.REARM - 5            # long after the last hold: a new busy spell
    pace.timed_out("big")
    check("a busy verdict long after the last hold starts from the base again", pace.held == base, str(pace.held))
    pace.busy_until = time.time() - 5
    pace.timed_out("big")                                     # still busy on the retry: twice the base
    doubled = pace.held
    pace.busy_until = time.time() - 5
    pace.rates["big"] = [150.0, 160.0, 170.0]
    pace.record("big", 1600, 10.0)                            # then an answer at the usual rate, outside a hold
    pace.timed_out("big")
    check("an answer at the usual rate ends the spell: the next hold is the base again",
          doubled == base * 2 and pace.held == base, f"{doubled} then {pace.held}")
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    saved = dict(SETTINGS.values), dict(SETTINGS.dynamic_options)
    try:
        SETTINGS.values.update(local_llm=True, local_model="big", local_busy_model="small")
        SETTINGS.dynamic_options["local_busy_model"] = [("", "-"), ("big", "big"), ("small", "small")]
        SETTINGS.dynamic_options.pop("local_busy_model")
        local.pace.busy_until = time.time() + 60
        check("before the model list: no switch", local.model == "big", local.model)
        local.pace.busy_until = 0.0
        SETTINGS.dynamic_options["local_busy_model"] = [("", "-"), ("big", "big"), ("small", "small")]
        check("free GPU: the chosen model", local.model == "big", local.model)
        local.pace.busy_until = time.time() + 60
        check("busy GPU: the smaller model", local.model == "small", local.model)
        SETTINGS.dynamic_options["local_busy_model"] = [("", "-"), ("big", "big")]
        check("busy model not pulled: stays on the chosen one", local.model == "big", local.model)
        SETTINGS.dynamic_options["local_busy_model"] = [("", "-"), ("big", "big"), ("small", "small")]
        SETTINGS.values["local_busy_model"] = ""
        check("switch off: stays on the chosen one", local.model == "big", local.model)
        SETTINGS.values["local_busy_model"] = "small"
        local.pace.busy_until = time.time() + 60

        async def fake_stream(body, on_delta):   # the GPU turns free halfway: the answer stays on one model
            local.pace.busy_until = 0.0
            return "답", {"output_tokens": 1}, [], {"finish": "stop", "thought": ""}
        local._stream = fake_stream
        res = await local.deep([], "q", _delta, think=False)
        check("label names the model that answered", res.model == "small", res.model)
        # the GPU goes back to whatever turned it busy, but only when another model can serve
        gone, real_unload, real_after = [], local.unload, local.YIELD_AFTER
        local.unload = lambda model=None: _record(gone, model)
        local.YIELD_AFTER = 0.0   # the wait that lets one answer finish on the model it started on
        local.pace.busy_until, local.pace.rates["big"] = 0.0, [150.0, 160.0, 170.0]
        local.last_used = 0.0
        local._pace("big", 400, 10.0)
        await local._yield
        check("a busy GPU gives the big model's memory back", gone == ["big"], str(gone))
        gone.clear()
        local.pace.busy_until, local.pace.rates["big"] = 0.0, [150.0, 160.0, 170.0]
        local._streams = 1        # an answer is still streaming: unloading now would only load it again
        local._pace("big", 400, 10.0)
        local.YIELD_AFTER = 0.001
        await local._yield
        local._streams = 0
        check("a model still streaming is left on the card", gone == [], str(gone))
        local.YIELD_AFTER = real_after
        gone.clear()
        SETTINGS.values["local_busy_model"] = ""
        local.pace.busy_until, local.pace.rates["big"] = 0.0, [150.0, 160.0, 170.0]
        local._pace("big", 400, 10.0)
        check("with no model to switch to it stays loaded", gone == [], str(gone))
        local.unload, local.YIELD_AFTER = real_unload, real_after
        sent = []

        class Post:
            status_code = 200

        async def held():
            return {"model": "small", "vram_gb": None}

        async def post(url, json=None, timeout=None):
            sent.append(json["model"])
            return Post()
        local.loaded, local._client.post = held, post
        await local.unload()
        check("release unloads the model the server holds", sent == ["small"], str(sent))
    finally:
        SETTINGS.values.clear(); SETTINGS.values.update(saved[0])
        SETTINGS.dynamic_options.clear(); SETTINGS.dynamic_options.update(saved[1])


async def test_thinking_cut():
    """The thinking used up max_tokens and cut the answer (a real screen: 34 characters, cut in
    the REGION line): the answer is written once more without thinking, from that reasoning."""
    print("\n[thinking cut by max_tokens]")
    from server.analyzer import LocalLlmAnalyzer
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    bodies, shown = [], []
    script = []

    async def fake_stream(body, on_delta):
        bodies.append(body)
        text, usage, end = script.pop(0)
        await on_delta(text)
        return text, usage, [], end

    async def on_delta(t):
        shown.append(t)
    local._stream = fake_stream
    thought = "x" * 20000 + " 결론: 정답은 ①"
    full = "TYPE: mcq\nANSWER: ①\nREGION: 100 120 600 700\n①이 맞는 이유"
    script[:] = [("TYPE: mcq\nANSWER: ①\nREGION: 481 19", {"input_tokens": 3000, "output_tokens": 8000},
                  {"finish": "length", "thought": thought}),
                 (full, {"input_tokens": 6000, "output_tokens": 300}, {"finish": "stop", "thought": ""})]
    res = await local.deep(["img"], "문제", on_delta)
    check("cut answer: written again, and that is the answer", res.text == full, res.text)
    again = bodies[1] if len(bodies) > 1 else {}
    text = again.get("messages", [{}, {"content": [{}]}])[1]["content"][-1].get("text", "")
    check("again without thinking, with no tools", again.get("reasoning_effort") == "none" and "tools" not in again,
          str({k: again.get(k) for k in ("reasoning_effort", "tools")}))
    # 3,000 of the 8,000 tokens spent: the last 3/8 of the reasoning's characters
    check("again from the end of the reasoning and the cut answer",
          text.endswith("REGION: 481 19") and "결론: 정답은 ①" in text and "x" * 7501 not in text
          and "x" * 7400 in text, text[-120:])
    check("the image goes again", again.get("messages", [{}, {"content": []}])[1]["content"][0].get("type") == "image_url")
    check("label says so", res.model.endswith("(think, cut)"), res.model)
    check("tokens of both requests", res.usage["output_tokens"] == 8300, str(res.usage))
    check("the panel is told while it is written again", any("다시 씀" in t for t in shown), str(shown)[:200])
    # no answer at all (the 12b's empty answers): the same
    bodies.clear()
    script[:] = [("", {"input_tokens": 3000, "output_tokens": 8000}, {"finish": "length", "thought": thought}),
                 (full, {"input_tokens": 6000, "output_tokens": 300}, {"finish": "stop", "thought": ""})]
    res = await local.deep(["img"], "문제", on_delta)
    check("no answer before the cut: written from the reasoning", res.text == full and "[끊긴 답]" not in
          bodies[1]["messages"][1]["content"][-1]["text"], res.text)
    # an answer that ended on its own, and an answer without thinking: once
    for think, finish in ((True, "stop"), (False, "length")):
        bodies.clear()
        script[:] = [(full, {"input_tokens": 3000, "output_tokens": 900}, {"finish": finish, "thought": "t"})]
        res = await local.deep(["img"], "문제", on_delta, think=think)
        check(f"think={think} finish={finish}: one request", len(bodies) == 1 and "cut" not in res.model, res.model)
    # a long answer cut at its end after a short thought stays as it is
    bodies.clear()
    long_answer = "TYPE: coding\nANSWER: x\n" + "코드 줄\n" * 2000
    script[:] = [(long_answer, {"input_tokens": 3000, "output_tokens": 8000}, {"finish": "length", "thought": "t" * 4000})]
    res = await local.deep(["img"], "문제", on_delta)
    check("a long answer cut at its end: kept, not written again", len(bodies) == 1 and res.text == long_answer, res.model)
    # ...the cut answer goes into the request only up to its start
    bodies.clear()
    script[:] = [("P" * 3000, {"input_tokens": 3000, "output_tokens": 8000}, {"finish": "length", "thought": "x" * 40000}),
                 (full, {"input_tokens": 6000, "output_tokens": 300}, {"finish": "stop", "thought": ""})]
    await local.deep(["img"], "문제", on_delta)
    text = bodies[1]["messages"][1]["content"][-1]["text"] if len(bodies) > 1 else ""
    check("the cut answer goes in up to 2,000 characters", "P" * 2000 in text and "P" * 2001 not in text, str(len(bodies)))

    # ...and when writing it again fails or brings nothing, the cut answer stays
    async def failing(body, on_delta):
        bodies.append(body)
        if len(bodies) == 1:
            return "TYPE: mcq\nANSWER: ①", {"input_tokens": 3000, "output_tokens": 8000}, [], {"finish": "length", "thought": thought}
        raise RuntimeError("local LLM: HTTP 400")
    bodies.clear()
    local._stream = failing
    res = await local.deep(["img"], "문제", on_delta)
    check("writing it again failed: the cut answer stays", res.text == "TYPE: mcq\nANSWER: ①", res.text)

    async def failing_empty(body, on_delta):
        bodies.append(body)
        if len(bodies) == 1:
            return "", {"input_tokens": 3000, "output_tokens": 8000}, [], {"finish": "length", "thought": thought}
        raise RuntimeError("local LLM: HTTP 500")
    bodies.clear()
    local._stream = failing_empty
    try:
        await local.deep(["img"], "문제", on_delta)
        check("no answer and writing it again failed: the error says the thinking used the limit", False, "no error")
    except RuntimeError as exc:
        check("no answer and writing it again failed: the error says the thinking used the limit",
              "max_tokens" in str(exc) and "HTTP 500" in str(exc), str(exc))
    local._stream = fake_stream
    bodies.clear()
    script[:] = [("TYPE: mcq\nANSWER: ①", {"input_tokens": 3000, "output_tokens": 8000}, {"finish": "length", "thought": thought}),
                 ("", {"input_tokens": 6000, "output_tokens": 0}, {"finish": "stop", "thought": ""})]
    res = await local.deep(["img"], "문제", on_delta)
    check("written again as nothing: the cut answer stays", res.text == "TYPE: mcq\nANSWER: ①", res.text)

    # a search that would carry a number shaped like personal data stays here
    calls = []

    class Web:
        async def call(self, name, arguments):
            calls.append(arguments)
            return "{}"
    local.web, local._search_on = Web(), lambda: True
    rounds = [("", {"output_tokens": 5}, [{"id": "c1", "name": "web_search", "arguments": '{"query": "010-1234-5678 누구"}'}],
               {"finish": "tool_calls", "thought": ""}),
              (full, {"output_tokens": 50}, [], {"finish": "stop", "thought": ""})]

    async def searching(body, on_delta):
        bodies.append(body)
        return rounds.pop(0)
    local._stream = searching
    bodies.clear()
    trace = []
    await local._run([{"role": "system", "content": "s"}, {"role": "user", "content": [{"type": "text", "text": "q"}]}],
                     True, on_delta, lambda: False, trace)
    held = bodies[1]["messages"][-1]["content"] if len(bodies) > 1 else ""
    check("search with a phone number: not sent, not listed as sent, the model is told",
          not calls and not trace and "보내지 않았습니다" in held, f"{calls} {trace} {held[:60]}")
    for args, want_sent in (('{"url": "https://example.com/search?q=010+4821+7730"}', False),
                            ('{"query": "user page", "url": "https://example.com/u/010-9876-5432"}', False),
                            ('{"url": "https://go.dev/dl/"}', True), ('"010-9876-5432"', None)):
        calls.clear()
        rounds[:] = [("", {"output_tokens": 5}, [{"id": "c1", "name": "fetch_page", "arguments": args}],
                      {"finish": "tool_calls", "thought": ""}),
                     (full, {"output_tokens": 50}, [], {"finish": "stop", "thought": ""})]
        trace = []
        try:
            await local._run([{"role": "system", "content": "s"}, {"role": "user", "content": [{"type": "text", "text": "q"}]}],
                             True, on_delta, lambda: False, trace)
            ok = (bool(calls) == want_sent and (not want_sent or trace == [("fetch_page", "https://go.dev/dl/")])
                  if want_sent is not None else True)
            check(f"fetch_page {args[:48]}: {'sent' if want_sent else 'held' if want_sent is False else 'no crash'}",
                  ok, f"{calls} {trace}")
        except Exception as exc:
            check(f"fetch_page {args[:48]}: no crash", False, repr(exc))


async def test_search_turned_away():
    """No results because the engines turned the search away (too many requests, CAPTCHA): the model is
    told why, so it does not pass an old version off as the latest."""
    print("\n[web search: engines turned it away]")
    import json
    from server.search import WebTools

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    web = WebTools(CONFIG)
    await web._client.aclose()
    replies = [{"results": [], "unresponsive_engines": [["brave", "Suspended: too many requests"], ["duckduckgo", "CAPTCHA"]]},
               {"results": [{"title": "Node.js", "url": "https://nodejs.org", "content": "v26.12.1"}],
                "unresponsive_engines": [["brave", "Suspended: too many requests"]]}]

    class Client:
        async def get(self, url, params=None):
            return Resp(replies.pop(0))
    web._client = Client()
    first = json.loads(await web.web_search("node latest"))
    check("no results, engines turned it away: the model is told why", "brave" in first.get("error", "")
          and "CAPTCHA" in first.get("error", ""), str(first))
    second = json.loads(await web.web_search("node latest"))
    check("results from the engines that did answer: no error", "error" not in second and second["results"], str(second))


async def test_pace_shared():
    print("\n[busy GPU switch: requests side by side]")
    import json
    from server.analyzer import GpuPace, LocalLlmAnalyzer

    class Resp:
        status_code = 200

        def __init__(self, tokens, secs):
            self.tokens, self.secs = tokens, secs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def aiter_lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "a"}}]})
            await asyncio.sleep(self.secs)   # the generation
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "b"}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": self.tokens}})
            yield "data: [DONE]"

    class Client:
        def __init__(self):
            self.next = []

        def stream(self, method, url, json=None):
            return Resp(*self.next.pop(0))

    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._client, local.pace = Client(), GpuPace(CONFIG, None)
    body = {"model": "big", "messages": []}
    local._client.next = [(1500, 1.2)]
    await local._stream(body, _delta)
    check("an answer alone is measured", len(local.pace.rates.get("big", [])) == 1, str(local.pace.rates))
    local._client.next = [(300, 1.2), (300, 1.2)]     # each at a fifth of the usual rate, side by side
    await asyncio.gather(local._stream(body, _delta), local._stream(body, _delta))
    check("answers side by side are not measured", len(local.pace.rates["big"]) == 1 and not local.pace.busy(),
          f"{local.pace.rates} busy={local.pace.busy()}")
    local._client.next = [(300, 1.2)]
    await local._stream(body, _delta)
    check("a slow answer alone still counts as busy", local.pace.busy(), str(local.pace.last))


async def test_load_kept():
    print("\n[a cancelled request keeps the model load]")
    import json
    import time
    import httpx2
    from server.analyzer import LocalLlmAnalyzer

    class Resp:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def aiter_lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]})
            yield "data: [DONE]"

    class Client:
        """Ollama with nothing on the GPU: a load takes 0.3 s, after which /api/ps lists the model (`slow`: the
        load runs past the client's time limit)."""

        def __init__(self, native=True, slow=False):
            self.native, self.slow, self.ps, self.loads, self.loaded, self.streams = native, slow, [], [], 0, 0
            self.unloads, self.chat_loads = [], 0

        async def get(self, url, timeout=None):
            return FakeResp(200, {"models": self.ps}) if self.native else FakeResp(404, {})

        async def post(self, url, json=None, timeout=None):
            if "keep_alive" in json:
                self.unloads.append(json["model"])
                self.ps = []
                return FakeResp(200, {})
            self.loads.append(json["model"])
            await asyncio.sleep(0.3)
            if self.slow:
                raise httpx2.ReadTimeout("timed out")
            self.ps = [{"name": json["model"] if ":" in json["model"] else json["model"] + ":latest"}]
            self.loaded += 1
            return FakeResp(200, {})

        def stream(self, method, url, json=None):
            self.streams += 1
            if self.native and not any(m["name"].split(":")[0] == json["model"].split(":")[0] for m in self.ps):
                self.chat_loads += 1   # Ollama loads the model for the chat request itself
                self.ps = [{"name": json["model"]}]
            return Resp()

    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._client = c = Client()
    body = {"model": "big", "messages": []}
    first = asyncio.create_task(local._stream(body, _delta))
    await asyncio.sleep(0.1)
    first.cancel()                        # a newer screen came while the model was loading
    try:
        await first
    except asyncio.CancelledError:
        pass
    t = time.perf_counter()
    await local._stream(body, _delta)
    waited = time.perf_counter() - t
    check("a request cancelled while the model loads leaves the load running",
          c.loads == ["big"] and c.loaded == 1, f"loads={c.loads} done={c.loaded}")
    check("the next request waits for that load, only for what was left of it", c.streams == 1 and waited < 0.28,
          f"streams={c.streams} waited={waited:.2f}s")
    await local._stream(body, _delta)
    check("the model on the GPU: no load first", c.loads == ["big"] and c.streams == 2, str(c.loads))
    await local._stream({"model": "small", "messages": []}, _delta)
    check("another model (the busy-GPU one): loaded first", c.loads == ["big", "small"] and c.streams == 3, str(c.loads))
    local._client = c = Client(native=False)
    await local._stream(body, _delta)
    check("not Ollama (no /api/ps): no load request", c.loads == [] and c.streams == 1, str(c.loads))

    local._client = c = Client()
    await local._stream({"model": "plain", "messages": []}, _delta)
    await local._stream({"model": "plain", "messages": []}, _delta)
    check("a name without a tag is its :latest: loaded once", c.loads == ["plain"] and c.streams == 2, str(c.loads))

    for stop in ("pause", "release"):
        local._client = c = Client()
        waiting = asyncio.create_task(local._stream(body, _delta))
        await asyncio.sleep(0.1)
        if stop == "pause":
            local.cancel_load()
        else:
            await local.unload()
        await asyncio.sleep(0.3)
        check(f"{stop} while the model loads: the load is stopped", c.loaded == 0 and waiting.done(),
              f"loaded={c.loaded} unloads={c.unloads}")
        check(f"{stop}: a request waiting for it fails instead of loading the model itself",
              not waiting.cancelled() and isinstance(waiting.exception(), RuntimeError)
              and c.streams == 0 and c.chat_loads == 0, f"{waiting} streams={c.streams} chat_loads={c.chat_loads}")

    class Stalled(Client):
        def stream(self, method, url, json=None):
            raise httpx2.ReadTimeout("")
    local._client = Stalled(native=False)
    try:
        await local._stream(body, _delta)
        got = None
    except Exception as exc:
        got = exc
    check("an answer that stops coming: a TimeoutError that says how long", isinstance(got, TimeoutError)
          and "nothing came for" in str(got), repr(got))

    local._client = c = Client(slow=True)
    first = asyncio.create_task(local._stream(body, _delta))
    second = asyncio.create_task(local._stream(body, _delta))
    got = await asyncio.gather(first, second, return_exceptions=True)
    check("a load past the time limit fails the requests waiting for it, with no second load",
          all(isinstance(g, TimeoutError) for g in got) and c.loads == ["big"] and c.streams == 0
          and c.chat_loads == 0, f"{got} loads={c.loads} streams={c.streams}")
    check("each waiter gets its own error, and the load is forgotten",
          got[0] is not got[1] and isinstance(got[0].__cause__, httpx2.ReadTimeout) and not local._loading,
          f"{got} loading={local._loading}")


async def test_claude_gets_the_searches():
    print("\n[a current-version question: what the first pass found goes to Claude; tool calls it writes are dropped]")
    import json
    from server.analyzer import FastResult
    from server.settings import SETTINGS
    pipe, eng = make_pipeline()
    saved = dict(SETTINGS.values)
    found = {"query": "kubernetes latest stable version", "results": [
        {"title": "Kubernetes Releases", "url": "https://kubernetes.io/releases/", "snippet": "Latest release: v1.37.2"}]}

    async def fast(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
        # the first pass searched the web, then said the question needs more than a quick answer
        msgs = [{"role": "user", "content": text},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "type": "function", "function": {
                    "name": "web_search", "arguments": json.dumps({"query": found["query"]})}}]},
                {"role": "tool", "tool_call_id": "c0", "content": json.dumps(found)}]
        return FastResult(text=None, head="TYPE: short\nROUTE: deep\n", type="short", route="deep", messages=msgs,
                          searches=[("web_search", found["query"])])
    eng.local.fast = fast
    seen = {}

    def claude_says(reply):
        async def run(images, text, on_delta, **kw):
            seen.update(images=len(images), text=text, web=kw.get("web", False))
            return type("R", (), {"text": reply, "model": "mock-claude", "usage": {"input_tokens": 10, "output_tokens": 3},
                                  "cost_usd": 0.001})()
        return run
    asked = "쿠버네티스 최신 안정버전이 몇인가요?"
    try:
        SETTINGS.values.update(agent_mode="hard", agent_hard_types=["short"], agent_payload="crop",
                               agent_confirm=False)
        eng.agent.run = claude_says("TYPE: short\nANSWER: v1.37.2\n쿠버네티스 릴리스 페이지 기준입니다.")
        out = await pipe.solve(51, None, asked, True, _delta)
        what = next((x["what"] for x in out.sent if x.get("to") == "agent"), "")
        check("the first pass's search results go to Claude with the question",
              out.engine == "agent" and "[검색 결과]" in seen.get("text", "") and "v1.37.2" in seen["text"]
              and "kubernetes.io/releases" in seen["text"] and asked in seen["text"], seen.get("text", "")[-300:])
        check("...and the card says what went", "검색 결과 1개" in what, what)
        check("...and Claude may search the web for it", seen.get("web") is True, str(seen.get("web")))
        eng.agent.run = claude_says('<invoke name="Bash">\n<parameter name="command">curl -s https://dl.k8s.io/release/'
                                     'stable.txt</parameter>\n</invoke>\nTYPE: short\nANSWER: v1.37.2')
        out = await pipe.solve(52, None, asked, True, _delta)
        check("a tool call Claude writes out as text is not on the card",
              "<invoke" not in out.text and out.text.startswith("TYPE: short"), out.text[:120])
        eng.agent.run = claude_says('<invoke name="WebSearch">\n<parameter name="query">kubernetes</parameter>\n</invoke>')
        out = await pipe.solve(53, None, asked, True, _delta)
        check("a reply that was nothing but a tool call counts as declined: this PC's model answers",
              out.engine == "local" and out.stages.get("agent_declined"), f"{out.engine} {out.stages}")
        eng.agent.run = claude_says("TYPE: coding\nANSWER: 설정\n```xml\n<invoke name=\"a\"><parameter name=\"p\">1"
                                     "</parameter></invoke>\n```")
        out = await pipe.solve(54, None, asked, True, _delta)
        check("XML inside an answer's code block is left alone", '<invoke name="a">' in out.text, out.text[-80:])
        async def fast_plain(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
            return FastResult(text=None, head="TYPE: short\nROUTE: deep\n", type="short", route="deep",
                              messages=[{"role": "user", "content": text}])
        eng.local.fast = fast_plain
        eng.agent.run = claude_says("TYPE: short\nANSWER: 해시 충돌은 체이닝이나 개방 주소법으로 푼다")
        out = await pipe.solve(55, None, "해시 충돌을 해결하는 방법을 말해 주세요", True, _delta)
        check("a question nobody searched for goes as before: no results, no web search",
              seen.get("web") is False and "[검색 결과]" not in seen.get("text", ""), str(seen.get("web")))
        # a note run into the head on one line (low effort with the web): the answer from TYPE on, not a decline
        eng.local.fast = fast
        eng.agent.run = claude_says("Need current info; search.TYPE: short\nANSWER: Python 3.15.2\n설명")
        out = await pipe.solve(56, None, asked, True, _delta)
        check("a note run into the head is cut off, and the answer stands",
              out.engine == "agent" and out.text.startswith("TYPE: short") and "Need current" not in out.text,
              f"{out.engine} {out.text[:80]!r}")
        # the CLI: the web search alone, allowed up front, and in a process of its own
        from server.agents import ClaudeCodeAgent, claude_args
        web_args, plain_args = claude_args(CONFIG, web=True), claude_args(CONFIG)
        check("the CLI with the web: WebSearch is the one tool, allowed up front, at low effort",
              web_args[web_args.index("--tools") + 1] == "WebSearch"
              and web_args[web_args.index("--allowedTools") + 1] == "WebSearch"
              and web_args[web_args.index("--effort") + 1] == "low" and web_args.count("--effort") == 1, str(web_args))
        check("...and without it no tools at all, as before", plain_args[plain_args.index("--tools") + 1] == ""
              and "--allowedTools" not in plain_args, str(plain_args))
        cli = ClaudeCodeAgent(CONFIG)
        went = []

        class Session:
            async def run(self, images, text, on_delta):
                went.append("warm")

        async def fresh(images, text, on_delta, web=False):
            went.append("fresh web" if web else "fresh")
        cli._session, cli._fresh = Session(), fresh
        await cli.run([], "q", _delta)
        await cli.run([], "q", _delta, web=True)
        check("a question with the web goes to a fresh process; the rest to the warm one", went == ["warm", "fresh web"],
              str(went))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def test_runaway_and_examples():
    print("\n[a written-out tool call stops the turn; examples the screen does not show are left out; runnable code]")
    from server import pipeline as P
    from server.analyzer import SYSTEM_PROMPT, LOCAL_SYSTEM_PROMPT
    from server.codecheck import _same

    # a runaway retry, as Claude streamed it: the same Bash call again and again
    loop = ['\n\n<', 'invoke name="', 'Bash">\n<', 'parameter name="command">', 'echo test</par', 'ameter>\n</', 'invoke>']
    shown, chunks = [], 0

    async def card(t):
        shown.append(t)
    feed = P.guarded(card)
    stopped = None
    try:
        await feed("TYPE: followup\nANSWER: 고쳐 봅니다")
        for _ in range(50):
            for c in loop:
                chunks += 1
                await feed(c)
    except P.ToolCallWritten as exc:
        stopped = exc
    check("a tool call written out as text stops the turn at the first one",
          stopped is not None and chunks == len(loop), f"{chunks} chunks, {stopped}")
    check("...and none of it reaches the card", "<invoke" not in "".join(shown) and "echo test" not in "".join(shown)
          and "".join(shown).startswith("TYPE: followup"), repr("".join(shown))[:200])

    # an answer that only looks like it: a comparison, an XML block in a code fence, a '<' that turns out ordinary
    shown.clear()
    feed = P.guarded(card)
    text = ("TYPE: coding\nANSWER: a < b 이면 바꾼다\n```xml\n<invoke name=\"x\"><parameter name=\"p\">1</parameter></invoke>\n"
            "```\n끝에 <b>굵게</b> 그리고 <")
    for i in range(0, len(text), 7):
        await feed(text[i:i + 7])
    await feed("br> 마침")
    check("an ordinary answer goes through whole, XML in its code block too", "".join(shown) == text + "br> 마침",
          repr("".join(shown))[-120:])

    # the first answer: stopped mid-stream, this PC's model answers, and the panel is told why
    pipe, eng = make_pipeline()
    notes = []

    async def note(t):
        notes.append(t)
    pipe.hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=note, stage=_anoop,
                       confirm=_aconfirm_yes, agent_failed=_anoop)
    from server.settings import SETTINGS
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(agent_mode="hard", agent_hard_types=["algorithm"], agent_payload="crop",
                               agent_confirm=False)
        streamed = []

        async def looping(images, text, on_delta, **kw):
            for _ in range(100):
                for c in loop:
                    streamed.append(c)
                    await on_delta(c)
            return type("R", (), {"text": "".join(streamed), "model": "m", "usage": {}, "cost_usd": 0.0})()
        eng.agent.run = looping
        out = await pipe.solve(61, FakeFrame(), "", False, _delta)
        check("Claude stopped writing calls: this PC's model answers, the panel says why",
              out.engine == "local" and len(streamed) == len(loop) and any("도구를 불러 멈춤" in n for n in notes)
              and any(x.get("to") == "agent" for x in out.sent), f"{out.engine} {len(streamed)} {notes} {out.sent}")
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)

    # the retry asks for nothing that needs a tool
    q, _ = P.retry_request({"fails": [{"input": ["aabbaccc"], "expected": 7, "got": 8}], "total": 1, "passed": 0})
    check("the retry says code cannot be run here", "실행하거나 도구를 쓸 수 없으니" in q, q[-80:])

    # examples once read wrongly: two the screen never showed, read off a picture of the problem with no example table
    shot = ("간단한 예로 “aabbaccc”의 경우 “2a2ba3c”와 같이 표현할 수 있는데 ... 예를 들면, “abcabcdede”와 같은 문자열은 "
            "전혀 압축되지 않습니다. 예를 들어, “ababcdcdababcdcd”의 경우 문자를 1개 단위로 자르면")
    read = {"function": "solution", "returns": "value", "cases": [
        {"args": ["aabbbcccc"], "expected": "4"}, {"args": ["abcde"], "expected": "5"},
        {"args": ["aabbaccc"], "expected": 7}]}
    kept = P.seen_cases(read, shot)
    check("a screen with no example section: nothing is checked, not even what the statement illustrates",
          kept["cases"] == [] and kept["unseen"] == 3, str(kept))
    illustrated = {"function": "solution", "cases": [{"args": ["aabbaccc"], "expected": "2a2ba3c"}]}
    check("(the statement's illustration taken for an example goes too)",
          P.seen_cases(illustrated, shot)["cases"] == [])
    table = shot + "\n\n입출력 예\n| s | result |\n| “aabbaccc” | 7 |\n| “ababcdcdababcdcd” | 9 |"
    kept = P.seen_cases(read, table)
    check("with an example table, only the examples written in it stay",
          [c["args"] for c in kept["cases"]] == [["aabbaccc"]] and kept["unseen"] == 2, str(kept))
    check("a string inside a longer word is not written there ('abcde' in 'abcabcdede')",
          not P._written(shot, "abcde") and P._written(shot, "abcabcdede"))
    check("no text to tell by: the examples stay as read", P.seen_cases(read, "") == read)
    std = P.seen_cases({"stdin": [{"input": "5\n1 2 3", "output": "6"}, {"input": "3\n9 9", "output": "1"}]},
                       "예제 입력 1\n5\n1  2 3\n예제 출력 1\n6")
    check("standard input: a line the problem shows stays, one it does not show goes",
          [c["input"] for c in std["stdin"]] == ["5\n1 2 3"], str(std))
    # A number read off the screen in quotes is the number when the problem writes it bare, and text when it writes
    # it in quotes (comparing every quoted number as a number passed 94 for "94")
    bare = P.seen_cases({"function": "solution", "cases": [{"args": ["aabbaccc"], "expected": "7"}]},
                        "입출력 예\n| s | result |\n| \"aabbaccc\" | 7 |")
    quoted = P.seen_cases({"function": "solution", "cases": [{"args": ["1924", 2], "expected": "94"}]},
                          "입출력 예\n| number | k | return |\n| \"1924\" | 2 | \"94\" |")
    check("a number in quotes is the number the problem writes bare, and text the problem writes in quotes",
          bare["cases"][0]["expected"] == 7 and quoted["cases"][0]["expected"] == "94"
          and not _same(94, "94") and _same(7, 7) and not _same("5", 5) and not _same(True, "1"),
          f"{bare['cases']} {quoted['cases']}")

    # through the check itself: the examples read off a picture, the text, and the answer run on the one left
    pipe, eng = make_pipeline()

    async def cases(images):
        return dict(read)

    async def extract(images=(), speech=""):
        return table
    eng.local.cases, eng.local.extract = cases, extract
    ran = []

    async def run(lang, code, stdin):
        ran.append(code)
        return {"stdout": "", "stderr": "", "exit": 0}
    answer = "TYPE: algorithm\nANSWER: 단위마다 압축\n```python\ndef solution(s):\n    return len(s) - 1\n```"
    out = P.Outcome(text=answer, model="m", usage=None, cost_usd=0.0, engine="agent")
    SETTINGS.values["autocheck"] = True
    reading, none_read = {}, {}
    try:
        await P.check_code(pipe, FakeFrame(), out, run, note=reading)
        # and a picture with no example section: the three read are all left out, and the record says so
        async def picture(images=(), speech=""):
            return shot
        eng.local.extract = picture
        left = await P.check_code(pipe, FakeFrame(), out, run, note=none_read)
    finally:
        SETTINGS.values.update(saved)
    check("the check runs only the example the problem shows",
          len(ran) == 1 and "aabbaccc" in ran[0] and "aabbbcccc" not in ran[0], str([c[-300:] for c in ran]))
    # Of nine checks in real use six ended with no examples, and the record could not tell a screen with none from
    # examples read and left out: it now says how many were read and kept, and of the text whether it
    # has an example heading
    check("the record says how the reading went: 3 read, 1 kept, a heading in the text",
          reading == {"read": 3, "kept": 1, "text_chars": len(table), "heading": True}, str(reading))
    check("...and for a picture with no example section: 3 read, none kept, no heading (no examples to run)",
          left is None and none_read == {"read": 3, "kept": 0, "text_chars": len(shot), "heading": False}, str(none_read))
    # A text that stopped short of the examples (one reading in 51 of the bench's coding screens ended at 305 characters
    # with the example table left out, check_read.py): read once more, and judged by that reading. A picture with no
    # example table is not read again: what its statement illustrates is in its text.
    texts, reads = [], []

    async def short_then_whole(images=(), speech=""):
        reads.append(1)
        return texts.pop(0)
    eng.local.extract = short_then_whole
    ran.clear()
    SETTINGS.values["autocheck"] = True
    try:
        texts[:] = ["문자열을 압축해 가장 짧은 길이를 구하세요.", table]
        await P.check_code(pipe, FakeFrame(), out, run)
        again, ran_again = len(reads), list(ran)
        reads.clear()
        ran.clear()
        texts[:] = [shot, table]
        await P.check_code(pipe, FakeFrame(), out, run)
        once, ran_once = len(reads), list(ran)
    finally:
        SETTINGS.values.update(saved)
    check("a text with neither an example heading nor any example read: read once more, and judged by that",
          again == 2 and len(ran_again) == 1 and "aabbaccc" in ran_again[0], f"{again} {[c[-120:] for c in ran_again]}")
    check("...a picture whose statement illustrates them is read once, and nothing is run, as before",
          once == 1 and not ran_once, f"{once} {ran_once}")
    # examples made only of numbers in lists: seen_cases keeps those once any heading is there, so a text cut short
    # looked as if it showed them and was never read again
    lists = {"function": "solution", "cases": [{"args": [[2, 1, 3, 4, 1]], "expected": 3},
                                               {"args": [[5, 5, 5]], "expected": 1}]}
    table_lists = "입출력 예\n| nums | result |\n| [2, 1, 3, 4, 1] | 3 |\n| [5, 5, 5] | 1 |"

    async def list_cases(images):
        return dict(lists)
    eng.local.cases = list_cases
    reads.clear()
    SETTINGS.values["autocheck"] = True
    list_answer = "TYPE: algorithm\nANSWER: 정렬\n```python\ndef solution(nums):\n    return 3\n```"
    try:
        texts[:] = ["정수 배열 nums 가 주어질 때 서로 다른 값의 개수를 구하세요.", table_lists]
        res_lists = await P.check_code(pipe, FakeFrame(), P.Outcome(text=list_answer, model="m", usage=None,
                                                                    cost_usd=0.0, engine="agent"), run)
    finally:
        SETTINGS.values.update(saved)
    kept_lists = ((res_lists or {}).get("cases") or {}).get("cases") or []
    check("examples made of lists of numbers, the text cut short: read once more, and both kept to run",
          len(reads) == 2 and len(kept_lists) == 2, f"{len(reads)} {res_lists}")
    check("입력 예제 and 출력 예제 (input and output examples) with no number after them are example headings; "
          "예를 들어 (for example) is not",
          all(P.EXAMPLES_HEAD_RE.search(t) for t in ("입력 예제\n1 2", "출력예제\n3"))
          and not P.EXAMPLES_HEAD_RE.search("예를 들어 abc 는"))

    # code answers come runnable: the function as submitted, then the examples run under it
    check("both prompts ask for code that runs the problem's examples",
          all("그대로 돌려 볼 수 있게" in p and "__main__" in p for p in (SYSTEM_PROMPT, LOCAL_SYSTEM_PROMPT)))
    # A value typed into the input box is what the code runs on (such a run used to print nothing). Claude's runner reads
    # the input box (a value there is the argument, an empty box runs the examples) and says so in a comment the panel
    # knows it by (the heading of the problem's examples);
    # the local model keeps the runner that prints the examples, its answers kept short of max_tokens
    check("Claude's runner reads the input box and falls back to the examples; the local model's prints the examples",
          "값이 있으면 한 줄을 인자 하나로" in SYSTEM_PROMPT and "없으면 입출력 예로 실행" in SYSTEM_PROMPT
          and "값이 있으면 한 줄을 인자 하나로" not in LOCAL_SYSTEM_PROMPT and "실행부는 문제의 입출력 예" in LOCAL_SYSTEM_PROMPT)
    # Measured on the local model: a program reading standard input also ran its own examples and printed "기대값" lines into
    # its output (2 of 4 made-up inputs), and the panel draws an answer's body in the shapes it is written in (answers read as
    # infographics; term cards 18 -> 33 of 56 answers with the line, answers 59/66 against 61/66, within the runs' spread)
    check("a standard-input program prints its answer only, in both prompts",
          all("답만 출력하는" in p and "기대값을 찍는 줄을 넣지 않는다" in p for p in (SYSTEM_PROMPT, LOCAL_SYSTEM_PROMPT)))
    check("both prompts ask for the body in the shapes the panel draws: a table, steps, named cards, a chain",
          all("본문은 한눈에 읽히는 꼴로 쓴다" in p and "`- **이름**: 설명`" in p and "`A → B → C`" in p for p in (SYSTEM_PROMPT, LOCAL_SYSTEM_PROMPT)))


async def test_server_examples_hold():
    print("\n[server: examples, heads, search, spending, the hold and the settle, each failing before its fix]")
    import json
    import types
    from server import pipeline as P
    from server import analyzer as AN
    from server import detector as DT
    from server.detector import ChangeDetector

    def attempt(name, fn, detail=""):
        """One check, its failure on an older tree (a name it does not have) a failure of that check alone."""
        try:
            ok, why = fn()
        except Exception as exc:   # noqa: BLE001
            ok, why = False, f"{type(exc).__name__}: {exc}"
        check(name, ok, str(why)[:160])
    # 6. one item of a standard-input reading that is not a dict
    try:
        got = P.seen_cases({"stdin": [{"input": "1 2", "output": "3"}, "1 2"]}, "예제 입력 1\n1 2\n예제 출력 1\n3\n")
        ok = [c["input"] for c in got["stdin"]] == ["1 2"]
    except Exception as exc:   # noqa: BLE001
        ok, got = False, exc
    check("6 a standard-input item that is not a dict does not break the check", ok, str(got)[:120])
    # 2. a class problem whose example scrolled away is not run on calls the model made up
    statement = "155. Min Stack\nDesign a stack ...\nImplement the MinStack class:\n- void push(int val)\n"
    made = {"class": "MinStack", "calls": ["MinStack", "push", "getMin"], "args": [[], [5], []], "expected": [None, None, 4]}
    real_text = statement + 'Example 1:\nInput\n["MinStack","push","getMin"]\n[[],[5],[]]\nOutput\n[null,null,5]\n'
    real = {"class": "MinStack", "calls": ["MinStack", "push", "getMin"], "args": [[], [5], []], "expected": [None, None, 5]}
    check("2 a class problem's made-up calls are left out, its written example kept",
          P.seen_cases(made, statement).get("class") is None and P.seen_cases(real, real_text).get("class") == "MinStack")
    # 8. examples kept: spaces that are the point, and a real number written with more places
    lc151 = 'Example 2:\nInput: s = "  hello world  "\nOutput: "world hello"\n'
    lc50 = "Example 1:\nInput: x = 2.00000, n = 10\nOutput: 1024.00000\n"
    k151 = P.seen_cases({"function": "reverseWords", "cases": [{"args": ["  hello world  "], "expected": "world hello"}]}, lc151)
    k50 = P.seen_cases({"function": "myPow", "cases": [{"args": [2.0, 10], "expected": 1024.0}]}, lc50)
    check("8 an example with significant spaces and one with 2.00000 are kept",
          len(k151["cases"]) == 1 and len(k50["cases"]) == 1, f"{k151['cases']} {k50['cases']}")
    # 9. the head is lifted only when it is one
    yaml = "```yaml\nenv:\n  CMAKE_BUILD_TYPE: Release\n```\n설명"
    refusal = "시험 중으로 보여 답하지 않습니다 (형식상 TYPE: none 으로 둡니다).\n다시 물어 주세요."
    note = "Need current info; search.TYPE: short\nANSWER: 1.34.2\n본문"
    check("9 a YAML key and a refusal naming the head are not lifted; a note run into the head is",
          P.lift_head(yaml) == yaml and P.lift_head(refusal) == refusal and P.lift_head(note).startswith("TYPE: short"))
    # 10. an answer explaining the notation is not a written-out call; a written-out call still is
    async def run_feed(text, step=7):
        shown = []

        async def on(t):
            shown.append(t)
        feed = P.guarded(on)
        try:
            for i in range(0, len(text), step):
                await feed(text[i:i + step])
        except P.ToolCallWritten:
            return "stopped", "".join(shown)
        return "through", "".join(shown)
    explain = ("도구를 부르면 `<invoke name=\"Bash\">` 가 오고 `</invoke>` 로 닫힙니다. 여는 태그 <invoke name=...> 를 "
               "만나면 버퍼를 시작한다.\n```python\nbuf = []\n```\n그리고 </invoke> 에서 끝낸다.")
    call = "고쳐 봅니다\n\n<invoke name=\"Bash\">\n<parameter name=\"command\">echo test</parameter>\n</invoke>\n"
    a, shown_a = await run_feed(explain)
    b, shown_b = await run_feed(call)
    check("10 an answer about <invoke> goes through whole; a call written out still stops the turn",
          a == "through" and shown_a == explain and b == "stopped" and "<invoke" not in shown_b, f"{a} {b} {shown_a[-40:]!r}")
    # 5. the official release page first, then fetched pages, then snippets, each address once, dated
    msgs = [{"role": "tool", "content": json.dumps({"query": "k latest version", "results": [
                {"title": f"t{i}", "url": f"https://b/{i}", "snippet": "s", "date": "2025-01-01"} for i in range(6)],
                "page": {"url": "https://k.io/releases", "title": "rel", "text": "latest 1.34.2"}})},
            {"role": "tool", "content": json.dumps({"query": "k 최신 버전", "results": [
                {"title": f"u{i}", "url": f"https://b/{i}", "snippet": "s"} for i in range(6)]})}]
    facts = P.searched_facts(msgs)
    check("5 the official page comes first, addresses once, dates kept",
          facts[0]["url"] == "https://k.io/releases" and len({f["url"] for f in facts}) == len(facts)
          and "(2025-01-01)" in facts[1]["title"], json.dumps(facts[:2], ensure_ascii=False)[:160])
    # 4. the web turn only for a question about the present
    err = [{"role": "tool", "content": json.dumps({"query": "exit code 137 java", "results": [{"title": "x", "url": "u", "snippet": "s"}]})}]
    attempt("4 an error message searched is no question about the present; a latest version is",
            lambda: (not P.present_question(err) and P.present_question(msgs), ""))
    # 3. a turn that ended in an error after it went out is paid for, and leaves the row of empty answers alone
    def spend_failed():
        sp = P.Spend(CONFIG)
        sp.empty_run = 3
        sp.failed(P.ToolCallWritten("x"))
        paid = sum(c for _, c in sp.spent)
        exc = RuntimeError("error result")
        exc.cost_usd = 0.07
        sp.failed(exc)
        return (paid > 0 and abs(sum(c for _, c in sp.spent) - paid - 0.07) < 1e-9 and sp.empty_run == 3,
                f"{list(sp.spent)} row {sp.empty_run}")
    attempt("3 a turn stopped by an error is counted and the empty row kept", spend_failed)
    # 7, 15. the hold: only the slow model's own answer ends its doubling; the doubling is bounded
    import dataclasses
    clock = [10_000.0]
    real_time = AN.time.time
    AN.time.time = lambda: clock[0]
    try:
        pace = AN.GpuPace(dataclasses.replace(CONFIG, local_busy_hold_sec=30.0, local_busy_hold_max_sec=600.0))
        pace.rates = {"26b": [170.0] * 5, "e4b": [300.0] * 5}
        holds = []
        for _ in range(4):
            pace.record("26b", 2000, 2000 / 37.0)            # slow
            holds.append(round(pace.held))
            clock[0] = pace.busy_until + 5
            pace.record("e4b", 2000, 2000 / 300.0)           # the smaller model at its usual rate
        pace2 = AN.GpuPace(dataclasses.replace(CONFIG, local_busy_hold_sec=0.0, local_busy_hold_max_sec=600.0))
        pace2.rates = {"26b": [170.0] * 5}
        err2 = None
        try:
            for _ in range(1100):
                pace2.record("26b", 2000, 2000 / 37.0)
                clock[0] = pace2.busy_until + 1
        except OverflowError as e:
            err2 = e
    finally:
        AN.time.time = real_time
    check("7 the smaller model's answer does not put the hold back to 30 s", holds == [30, 60, 120, 240], str(holds))
    check("15 a week of busy GPU does not overflow the hold", err2 is None, str(err2))
    # 1. a line typed into an editor holds the settle; a video's wandering edge does not
    det = ChangeDetector(CONFIG, None)
    from server.gate import signature
    def scr(k, blob=None):
        im = Image.new("RGB", (1600, 900), "white")
        d = ImageDraw.Draw(im)
        for r in range(14):
            d.rectangle([40, 60 + r * 50, 40 + 420 + (r * 53) % 260, 72 + r * 50], fill="black")
        for j in range(k):
            d.rectangle([860, 80 + j * 44, 960, 90 + j * 44], fill="black")
        if blob is not None:
            d.rectangle([1200, 600, 1580, 880], fill=(30, 30, 40))
            d.ellipse([1300 + blob, 650, 1450 + blob, 850], fill=(200, 160, 140))
        return types.SimpleNamespace(sig=signature(im))
    typed = [det.observe(scr(k), now=100.0 + k) for k in range(6)]
    det2 = ChangeDetector(CONFIG, None)
    import random as _r
    rnd = _r.Random(7)
    video = [det2.observe(scr(0, rnd.randint(-40, 40)), now=200.0 + i) for i in range(10)]
    check("1 each typed line restarts the settle; a video after its first frames does not",
          all(typed[1:]) and sum(video[4:]) <= 1, f"typed {typed} video {video}")
    import numpy as _np
    attempt("1 a cell's margin grows round it", lambda: (int(DT.grown(_np.eye(5, dtype=bool), 1).sum()) == 13, ""))


async def test_activity():
    print("\n[/health says whether the server is in use, for a deploy that waits]")
    import server.app as app_mod
    st = app_mod.STATE
    saved = (st.analyses_running, dict(st.followups), st.check_task, st.last_result, st.last_followup_ts, st.runs_active)
    try:
        st.analyses_running, st.runs_active, st.check_task, st.last_result, st.last_followup_ts = 0, 0, None, None, 0.0
        st.followups.clear()
        idle = app_mod.activity()
        st.analyses_running = 1
        running = app_mod.activity()
        st.analyses_running = 0

        async def asked():
            await asyncio.sleep(5)
        t = asyncio.create_task(asked())
        st.followups[t] = {"image": False, "reason": None}
        following = app_mod.activity()
        t.cancel()
        st.followups.clear()
        st.last_result = {"ts": 1000.0}
        st.last_followup_ts = 1500.0
        answered = app_mod.activity()
        check("idle when nothing runs; busy while an analysis or a follow-up runs; the last answer is the newest",
              idle["busy"] is False and idle["last_answer"] is None and running["busy"] and following["busy"]
              and answered["busy"] is False and answered["last_answer"] == 1500.0, f"{idle} {running} {following} {answered}")
        st.utterances.append({"start": 0, "end": 1, "text": "질문", "ts": time.time()})
        heard = app_mod.activity()
        st.utterances.pop()
        check("listening while words were heard in the last 15 s (the capture program does not restart then)",
              heard["listening"] and not idle["listening"], f"{heard} {idle}")
    finally:
        (st.analyses_running, fu, st.check_task, st.last_result, st.last_followup_ts, st.runs_active) = saved
        st.followups.clear()
        st.followups.update(fu)


async def test_continuation_check():
    print("\n[a continuation runs the code on the whole problem's examples]")
    import json
    import server.app as app_mod
    from server.analyzer import AnalysisResult, MOCK_ALGO
    from server.settings import SETTINGS

    class Panel:
        def __init__(self):
            self.msgs = []

        async def send_text(self, t):
            self.msgs.append(json.loads(t))

    st = app_mod.STATE
    saved = (app_mod.ENGINES, app_mod.PIPELINE, app_mod.check_code, st.last_result, st.retry_task, list(st.thread),
             dict(SETTINGS.values))
    panel = Panel()
    st.panel_clients.add(panel)
    calls = []
    verdict = {}

    slow = [0.0]   # how long the check reads (the screen-off case below keeps it reading)

    async def fake_check(pipeline, frame, outcome, run, cases=None, any_type=False, **kw):
        calls.append({"frame": frame, "text": outcome.text, "crop": outcome.crop_box, "view": outcome.local_view,
                      "cases": cases})
        await asyncio.sleep(slow[0])
        return dict(verdict, cases={"function": "solution", "cases": [{"args": ["aabbaccc"], "expected": 7}]})
    try:
        eng = make_engines(CONFIG)
        hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_anoop, stage=_anoop,
                      confirm=_aconfirm_yes, agent_failed=_anoop)
        app_mod.ENGINES, app_mod.PIPELINE = eng, Pipeline(eng, hooks)
        app_mod.check_code = fake_check
        SETTINGS.values.update(local_llm=True, autocheck=True, run_button=True, extract=True, agent_mode="off")
        written = {"text": ""}

        async def cont_answer(image_b64, transcript, on_delta, extra=(), voice=False, followup=None):
            return AnalysisResult(text=written["text"], model="mock-local")
        eng.local.analyze = cont_answer
        pages = FakeFrame()
        pages.extra_b64 = [png_b64()]
        code_cont = ("TYPE: followup\nANSWER: 새 예 #5 때문에 바뀜\n\n```python\ndef solution(s):\n    return len(s)\n```\n")
        for name, said, result, autocheck in (
                ("no code of its own: the answer's code", "TYPE: followup\nANSWER: 답은 그대로입니다\n\n보강할 것 없음: 새 예도 맞음",
                 {"passed": 5, "total": 5, "lang": "python"}, True),
                ("code of its own, failing a new example", code_cont,
                 {"passed": 4, "total": 5, "lang": "python",
                  "fails": [{"input": ["xababcdcdababcdcd"], "expected": 17, "got": 16}]}, True),
                ("the check switched off", "TYPE: followup\nANSWER: 그대로\n\n보강할 것 없음: 같음", {}, False)):
            panel.msgs.clear()
            calls.clear()
            verdict.clear()
            verdict.update(result)
            written["text"] = said
            SETTINGS.values["autocheck"] = autocheck
            st.retry_task = None
            st.last_result = {"text": MOCK_ALGO, "frame": FakeFrame(), "id": 300, "engine": "local",
                              "crop_box": (0.1, 0.1, 0.6, 0.6), "local_view": None}
            await app_mod.run_followup(None, app_mod.CONTINUE_QUESTION,
                                       cont={"label": app_mod.CONTINUE_LABEL, "frame": pages})
            cid = next((m["id"] for m in panel.msgs if m.get("type") == "analysis_start"), None)
            checks = [m for m in panel.msgs if m.get("type") == "check"]
            if not autocheck:
                check(f"{name}: nothing is run and nothing said", not calls and not checks, f"{calls} {checks}")
                continue
            want_text = said if "```" in said else MOCK_ALGO
            check(f"{name}: run once, on the scrolled-together pages, without the first screen's crop",
                  len(calls) == 1 and calls[0]["frame"] is pages and calls[0]["text"] == want_text
                  and calls[0]["crop"] is None and calls[0]["view"] is None and calls[0]["cases"] is None,
                  str([(c["frame"] is pages, c["text"][:30], c["crop"]) for c in calls]))
            check(f"{name}: the result goes under the continuation",
                  len(checks) == 2 and checks[0].get("running") and checks[0]["id"] == cid
                  and checks[1]["id"] == cid and checks[1].get("passed") == result["passed"]
                  and "cases" not in checks[1], json.dumps(checks, ensure_ascii=False)[:300])
            retried = st.retry_task is not None
            check(f"{name}: a failure gets the one retry, with the examples it read",
                  retried == bool(result.get("fails")), f"retry started: {retried}")
            if st.retry_task is not None:
                st.retry_task.cancel()
                try:
                    await st.retry_task
                except (asyncio.CancelledError, Exception):
                    pass

        # Screen-off while the continuation's check still reads the pages: it stops, as the first check does, since it
        # reads that screen's examples (it was once marked as sending no screen and read on)
        panel.msgs.clear()
        calls.clear()
        verdict.clear()
        verdict.update({"passed": 5, "total": 5, "lang": "python"})
        written["text"] = code_cont
        SETTINGS.values["autocheck"] = True
        slow[0] = 10.0
        st.retry_task = None
        st.last_result = {"text": MOCK_ALGO, "frame": FakeFrame(), "id": 301, "engine": "local",
                          "crop_box": (0.1, 0.1, 0.6, 0.6), "local_view": None}
        follow = asyncio.create_task(app_mod.run_followup(None, app_mod.CONTINUE_QUESTION,
                                                          cont={"label": app_mod.CONTINUE_LABEL, "frame": pages}))
        for _ in range(100):   # until the check is reading
            if calls:
                break
            await asyncio.sleep(0.05)
        was_on = st.screen_on
        try:
            await app_mod.set_capture(screen=False)
            try:
                await asyncio.wait_for(asyncio.shield(follow), 3)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            cid = next((m["id"] for m in panel.msgs if m.get("type") == "analysis_start"), None)
            ends = [m for m in panel.msgs if m.get("type") == "check" and m.get("id") == cid and not m.get("running")]
            check("screen-off stops the continuation's check, which reads that screen, and the card is told",
                  bool(calls) and follow.done() and len(ends) == 1 and ends[0].get("cancelled") is True,
                  f"reading={bool(calls)} stopped={follow.done()} ends={ends}")
        finally:
            if not follow.done():
                follow.cancel()
                await asyncio.gather(follow, return_exceptions=True)
            slow[0] = 0.0
            st.screen_on = was_on
            st.stop_reasons.clear()
    finally:
        st.panel_clients.discard(panel)
        (app_mod.ENGINES, app_mod.PIPELINE, app_mod.check_code, st.last_result, st.retry_task) = saved[:5]
        st.thread[:] = saved[5]
        SETTINGS.values.clear()
        SETTINGS.values.update(saved[6])


async def test_run_args():
    """A function's runner reads one argument a line, as the examples write them (analyzer.SYSTEM_PROMPT): what is typed
    into the input box is laid out that way before the run, and only for such a runner. Once, a programmers
    matrix pasted over several lines ran as its first row alone (AA where FBABD was right) and a blank line first ran
    the examples."""
    print("\n[the input of a function's runner, one argument a line]")
    import dataclasses
    import server.app as app_mod
    import server.telemetry as telemetry
    from server.codecheck import args_lines
    for given, want in (
            ("[[50,90],[50,87]]", "[[50,90],[50,87]]\n"),
            ("[[100,90],\n[50,45]]", "[[100,90], [50,45]]\n"),
            ("\n[[70,49,90]]\n\n", "[[70,49,90]]\n"),
            ("scores = [[70, 49], [68, 50]]", "[[70, 49], [68, 50]]\n"),
            ("nums = [2,7,11,15], target = 9", "[2,7,11,15]\n9\n"),
            ('Input: s = "a,b", k = 2', '"a,b"\n2\n'),
            ("Input: nums = [3,2,4], target = 6\nOutput: [1,2]\nExplanation: Because nums[1] + nums[2] == 6, we return [1, 2].",
             "[3,2,4]\n6\n"),
            ('"aabbaccc"\t7', '"aabbaccc"\n7\n'),
            ('["a\\"b", "c"]', '["a\\"b", "c"]\n'),
            ("x == 3", "x == 3\n"),
            ("   \n ", "")):
        got = args_lines(given)
        check(f"laid out one argument a line: {given[:34]!r}", got == want, repr(got))
    sent, replies, events = [], [], []
    plain_post, plain_event, plain_cfg = app_mod._post_json, telemetry.event, app_mod.CONFIG

    def post(url, payload, timeout):
        sent.append(payload)
        return {"exit": 0, "stdout": "ok\n", "stderr": "", "elapsed": 0.01, "stage": "run"}

    async def reply(msg):
        replies.append(msg)
    app_mod._post_json = post
    telemetry.event = lambda name, **f: events.append((name, f))
    app_mod.CONFIG = dataclasses.replace(plain_cfg, runner_url="unix:///nowhere.sock")
    runner = ("import sys\n\ndef solution(m):\n    return len(m)\n\n\nif __name__ == \"__main__\":\n"
              "    # 입력이 있으면 그 값으로, 없으면 입출력 예로 실행\n    line = sys.stdin.readline()\n    print(solution(eval(line)))\n")
    plain = "n = int(input())\nrows = [input() for _ in range(n)]\nprint(len(rows))\n"
    try:
        await app_mod.run_code("r1", "python", runner, "[[1, 2],\n [3, 4]]\n", reply=reply)
        await app_mod.run_code("r2", "python", plain, "2\n1 2\n3 4\n", reply=reply)
        await app_mod.run_code("r3", "python", runner, "", reply=reply)
    finally:
        app_mod._post_json, telemetry.event, app_mod.CONFIG = plain_post, plain_event, plain_cfg
    stdin = [p["stdin"] for p in sent]
    check("a function's runner gets the matrix typed over two lines as one line", stdin[0] == "[[1, 2], [3, 4]]\n", repr(stdin))
    check("a program that reads the problem's own input gets it as it was typed", stdin[1] == "2\n1 2\n3 4\n", repr(stdin))
    check("nothing typed stays nothing, so the runner runs the problem's examples", stdin[2] == "", repr(stdin))
    runs = [f for name, f in events if name == "run"]
    check("the record of a run says how much went in and whether it was laid out",
          [(r.get("stdin_lines"), r.get("laid_out")) for r in runs] == [(1, True), (3, False), (0, False)], str(runs))
    check("all three ran", [m.get("type") for m in replies].count("run_result") == 3, str(replies)[:200])


def test_face_mask():
    """Faces on a screen are painted over before anything is made from it (server/faces.py, for people's
    portrait rights); a screen with none, or with the switch off, or with a finder that fails, goes on untouched; and
    a problem's drawn figure that the finder alone takes for a face is left alone (photo_like).

    The screen is a real problem page of the bench (SIDENOTE_BENCH) with a photo of a face pasted on it
    (SIDENOTE_FACES), and the figures are the corpus's own (SIDENOTE_CORPUS). None of them is in the repository:
    without the page or the photo every check here is skipped, without a figure only the check of that figure."""
    print("\n[faces on the screen are covered]")
    import server.faces as faces
    from server.app import prepare_frame
    from server.settings import SETTINGS
    try:
        bench = support.bench("real/spec/code_bj_ab.png")     # a Baekjoon problem page, 1920 x 1080
        photo = support.faces("face.jpg")                      # a face photo, pasted beside the problem
    except support.Missing as missing:
        support.skip("faces on the screen are covered", missing)
        return
    check("fixtures are there", bench.exists() and photo.exists(), f"{bench} {photo}")
    base = Image.open(bench).convert("RGB")
    face = Image.open(photo).convert("RGB").resize((240, 240))
    screen = base.copy()
    screen.paste(face, (1400, 560))

    def png(img):
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()
    saved = dict(SETTINGS.values)
    SETTINGS.values["face_mask"] = True
    try:
        raw = png(screen)
        fr = prepare_frame(raw, 1280, None)
        full = Image.open(io.BytesIO(fr.full_png)).convert("RGB")
        check("a face pasted beside a problem is covered, once", fr.faces == 1, str(fr.faces))
        check("...in the screen the crops are cut from: the face's middle is the cover's grey",
              full.getpixel((1400 + 130, 560 + 140)) == faces.FILL, str(full.getpixel((1530, 700))))
        model = Image.open(io.BytesIO(base64.b64decode(fr.model_b64))).convert("RGB")
        k = model.width / 1920
        m = model.getpixel((round(1530 * k), round(700 * k)))
        check("...in the model's picture too", all(abs(a - b) <= 6 for a, b in zip(m, faces.FILL)), str(m))
        same = all(full.getpixel((x, y)) == base.getpixel((x, y)) for x in range(40, 900, 37) for y in range(120, 520, 23))
        check("the problem's text is left as it was", same)
        plain = png(base)
        fr2 = prepare_frame(plain, 1280, None)
        check("a screen with no face is passed on as it came", fr2.faces == 0 and fr2.full_png == plain)
        SETTINGS.values["face_mask"] = False
        fr3 = prepare_frame(raw, 1280, None)
        check("with face covering switched off the screen goes on as it is", fr3.faces == 0 and fr3.full_png == raw)
        SETTINGS.values["face_mask"] = True
        real_find = faces.find
        faces.find = lambda img, score=0.6: (_ for _ in ()).throw(RuntimeError("model gone"))
        try:
            fr4 = prepare_frame(raw, 1280, None)
        finally:
            faces.find = real_find
        check("a finder that fails leaves the screen as it is (it is still read)", fr4.faces == 0 and fr4.full_png == raw)
        # a problem's figures the finder alone boxes (measured on the doocs corpus): a node drawn with a pale fill,
        # lamps on a grid, a linked list, pasted onto the problem's page as a problem shows them
        figures = ["1000-1099/1001.Grid Illumination/images/illu_1.jpg",
                   "0400-0499/0430.Flatten a Multilevel Doubly Linked List/images/list.jpg",
                   "0300-0399/0361.Bomb Enemy/images/bomb2-grid.jpg"]
        for rel in figures:
            # each figure on its own: one missing from the corpus skips its own check and no other
            with support.group(f"a problem's figure is not taken for a face: {rel.rsplit('/', 1)[1]}"):
                fig = support.corpus(f"doocs/solution/{rel}")
                page = base.copy()
                pic = Image.open(fig).convert("RGB")
                pic.thumbnail((900, 600))
                page.paste(pic, (960, 420))
                got = prepare_frame(png(page), 1280, None)
                check(f"a problem's figure is not taken for a face: {fig.name}", got.faces == 0, str(got.faces))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def test_pause_stops_load():
    print("\n[pause stops a model load in progress]")
    import server.app as app_mod
    calls = []

    class Local:
        def cancel_load(self, model=None):
            calls.append(model)

    class App:
        state = type("S", (), {"transcriber": None, "detector": None})()

    st = app_mod.STATE
    saved = app_mod.ENGINES, st.latest_frame, st.voice_pending, st.force_analyze
    app_mod.ENGINES = type("E", (), {"local": Local()})()
    st.latest_frame, st.voice_pending, st.force_analyze = None, False, False
    worker = asyncio.create_task(app_mod.analysis_worker(App()))
    try:
        st.stop_reasons.add("screen_off")
        await asyncio.sleep(0.25)
        check("screen off leaves a load in progress to the next analysis", calls == [], str(calls))
        st.stop_reasons.add("pause")
        await asyncio.sleep(0.25)
        check("pause stops a model load in progress", calls == [None], str(calls))
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        app_mod.ENGINES, st.latest_frame, st.voice_pending, st.force_analyze = saved
        st.stop_reasons.clear()


async def test_check_more_langs():
    print("\n[code check: Java, Kotlin, Go, TypeScript, Bash, other languages]")
    from server import codecheck as cc
    from server.settings import SETTINGS
    SETTINGS.values.update(agent_mode="off", autocheck=True, run_button=True, extract=True, local_llm=True)
    pipe, eng = make_pipeline()
    check("Java: Programmers' declaration", cc._java_signature(
        "import java.util.*;\n\nclass Solution {\n    public int[] solution(int[] arr, String[] w, long n) {\n", "solution")
          == ("int[]", ["int[]", "String[]", "long"]))
    check("Java: generics, two-dimensional arrays, varargs, static",
          cc._java_signature("class S {\n    public static List<List<Integer>> f(int[][] g, final List<Integer> a, String... w) {", "f")
          == ("List<List<Integer>>", ["int[][]", "List<Integer>", "String[]"]), str(cc._java_signature(
              "class S {\n    public static List<List<Integer>> f(int[][] g, final List<Integer> a, String... w) {", "f")))
    check("Kotlin: block body without a type returns Unit, an expression body's type is unknown",
          cc._kotlin_signature("class Solution {\n    fun f(a: IntArray, m: Array<String>) {", "f") == ("Unit", ["IntArray", "Array<String>"])
          and cc._kotlin_signature("fun g(a: Int, b: Int = 2) = a + b", "g") == ("?", ["Int", "Int"]))
    check("Go: grouped parameters, a named result, no method", cc._go_signature("func f(a, b int, s []string) (n int) {", "f")
          == ("int", ["int", "int", "[]string"]) and cc._go_signature("func (s *T) f(a int) int {", "f") is None)
    check("values with quotes, newlines, a dollar and nesting",
          cc._java_value("String[]", ['a"b\nc']) == 'new String[]{"a\\"b\\nc"}'
          and cc._kotlin_value("String", "$x") == '"\\$x"'
          and cc._go_value("[][]int", [[1, 2], []]) == "[][]int{[]int{1, 2}, []int{}}"
          and cc._kotlin_value("List<Long>", [1, 2]) == "listOf<Long>(1L, 2L)"
          and cc._java_value("List<Integer>", [1]) == "new java.util.ArrayList<Integer>(java.util.Arrays.<Integer>asList(1))",
          str([cc._java_value("String[]", ['a"b\nc']), cc._kotlin_value("String", "$x")]))
    check("a type the check does not know: no harness", cc.java_harness(
        "class Solution {\n  public int solution(Map<String, Integer> m) {\n    return 1;\n  }\n}", "solution",
        [{"args": [{"a": 1}], "expected": 1}]) is None and cc.go_harness("func solution(m map[string]int) int {\n", "solution",
        [{"args": [{"a": 1}], "expected": 1}]) is None)
    prog = cc.java_harness("public class Solution {\n  public int solution(int a) {\n    return a;\n  }\n}", "solution",
                           [{"args": [1], "expected": 1}])
    check("Java: the answer's top-level class loses `public`, the harness's has it",
          prog and "\nclass Solution" in "\n" + prog and "public class SnCheck" in prog, (prog or "")[:120])
    prog = cc.go_harness("func solution(a int) int {\n\treturn a\n}", "solution", [{"args": [1], "expected": 1}])
    check("Go: a package clause and the harness's imports go first", prog and prog.startswith("package main\n")
          and prog.index("sn_json") < prog.index("func solution"), (prog or "")[:80])
    swift = "TYPE: algorithm\nANSWER: x\n```swift\nfunc solution(_ a: Int) -> Int { a }\n```\n"
    check("an answer only in another language", cc.other_language(swift) == "Swift"
          and cc.other_language(swift + "```python\ndef solution(a): return a\n```\n") is None)
    eng.local.calls.clear()
    res = await check_code(pipe, FakeFrame(), type("O", (), {"text": swift, "crop_box": None})(), _run)
    check("another language: said at once, the examples not read for it", res and "Swift" in res.get("skipped", "")
          and not any(c[0] == "cases" for c in eng.local.calls), f"{res} {eng.local.calls}")
    res = await check_code(pipe, FakeFrame(), type("O", (), {"text": "TYPE: coding\nANSWER: x\n```bash\nread a b\necho $((a + b))\n```", "crop_box": None})(),
                           _run, cases={"stdin": [{"input": "1 2\n", "output": "3"}]})
    check("Bash fed standard input", res and res.get("passed") == 1 and res.get("lang") == "bash", str(res))


async def test_check_and_runner():
    print("\n[code check and server: each language's forms, in-place answers, shell blocks, the gateway and the runner's token]")
    import time as _time
    from server import codecheck as cc
    from server.app import PeerGuard, route_gateways
    java = """/**
 * Definition for singly-linked list.
 * public class ListNode { int val; ListNode next; }
 */
package com.example;
import java.util.*;

class Pair { int a, b; }   // a helper class before the solution's

class Solution {
    static class Node { int v; }
    public int solution(int[] a) {
        String s = "class Fake { void solution(int x) {} }";
        return a.length;
    }
}"""
    prog = cc.java_harness(java, "solution", [{"args": [[1, 2]], "expected": 2}])
    check("Java: the class that holds the method, past a comment's class, a helper class and a nested one",
          prog and "new Solution().solution(" in prog and "package com.example" not in prog, (prog or "")[-400:])
    check("Java: a LinkedList parameter gets a LinkedList",
          "new java.util.LinkedList<Integer>" in (cc._java_value("LinkedList<Integer>", [1, 2]) or ""))
    kt = "data class P(val a: Int)\n\nclass Solution {\n    fun solution(vararg nums: Int): Int {\n        return nums.sum()\n    }\n}"
    prog = cc.kotlin_harness(kt, "solution", [{"args": [[1, 2]], "expected": 3}])
    check("Kotlin: past a data class, a vararg spread from its array", prog and "Solution().solution(*_a0)" in prog
          and "val _a0: IntArray = intArrayOf(1, 2)" in prog, (prog or "")[-300:])
    check("Kotlin: a nullable element kept", cc._kotlin_signature("fun f(a: Array<Int?>): Int {", "f") == ("Int", ["Array<Int?>"])
          and cc._kotlin_value("Array<Int?>", [1, None]) == "arrayOf<Int?>(1, null)")
    check("Kotlin: a result type the check does not know is not run", cc.kotlin_harness(
        "class Solution {\n    fun f(a: Int): TreeNode? {\n        return null\n    }\n}", "f", [{"args": [1], "expected": None}]) is None)
    prog = cc.go_harness("func f(s string) byte {\n\treturn s[0]\n}", "f", [{"args": ["ab"], "expected": "a"}]) or ""
    check("Go: a byte result printed as its character, slices through the nil-safe printer",
          "string(rune(f(" in prog and "_snFix(sn_reflect.ValueOf(v))" in prog, prog[-300:])
    declared = [("python", "class Solution:\n    def moveZeroes(self, nums: List[int]) -> None:\n", True),
                ("javascript", "/**\n * @param {number[]} nums\n * @return {void}\n */\nvar moveZeroes = function(nums) {\n", True),
                ("typescript", "function moveZeroes(nums: number[]): void {\n", True),
                ("cpp", "class Solution {\npublic:\n    void moveZeroes(vector<int>& nums) {\n    }\n};", True),
                ("java", "class Solution {\n    public void moveZeroes(int[] nums) {\n    }\n}", True),
                ("kotlin", "class Solution {\n    fun moveZeroes(nums: IntArray): Unit {\n    }\n}", True),
                ("go", "func moveZeroes(nums []int) {\n}", True),
                ("cpp", "int moveZeroes(vector<int>& nums) {\n    return 0;\n}", False),
                ("python", "def moveZeroes(nums):\n    nums.sort()\n", False)]
    got = [(cc._declaration(lang, code, "moveZeroes") or {}).get("kind") == "void" for lang, code, _ in declared]
    check("a function that says it returns nothing, in every language", got == [d[2] for d in declared], str(got))
    check("in place: unchanged but as expected counts when it says it returns nothing",
          cc._in_place({"got": None, "after": [[0]]}, [[0]], [0], "void", "moveZeroes") == (True, [0])
          and cc._in_place({"got": None, "after": [[0]]}, [[0]], [0], None, "moveZeroes")[0] is False
          and cc._in_place({"got": None, "after": [[0]]}, [[0]], [0], "void", "solution")[0] is False)
    res = await cc.run_cases("TYPE: coding\nANSWER: x\n```cpp\nclass Solution {\npublic:\n    void moveZeroes(vector<int>& nums) {\n"
                             "        stable_partition(nums.begin(), nums.end(), [](int x) { return x != 0; });\n    }\n};\n```",
                             {"function": "moveZeroes", "cases": [{"args": [[0, 1, 0, 3]], "expected": [1, 3, 0, 0]},
                                                                  {"args": [[0]], "expected": [0]}]}, _run)
    check("C++ in place: an example whose answer is its input passes", res and res.get("passed") == 2, str(res))
    shell = ("TYPE: coding\nANSWER: x\n```python\nimport sys\nprint(sum(map(int, sys.stdin.read().split())))\n```\n"
             "```bash\ncat <<EOF | python3 main.py\n1 2\nEOF\n```\n")
    check("a shell block that runs the program is not taken for the solution",
          [lang for lang, _ in cc.code_blocks(shell)] == ["python"] and cc.answer_code(shell)[0] == "python")
    check("a shell solution stays one, a variable named cc too", [lang for lang, _ in cc.code_blocks(
        "```bash\ncc=0\nread a b\necho $((a + b + cc))\n```")] == ["bash"])
    swift = "TYPE: algorithm\nANSWER: x\n```swift\nfunc solution(_ a: Int) -> Int { a }\n```\n```bash\nswiftc main.swift && ./main\n```\n"
    check("another language with a shell block that builds it", cc.other_language(swift) == "Swift", str(cc.other_language(swift)))
    nums = [(0.7327777, 0.73278, True), (0.7329, 0.73278, False), (1.9999999999999998, 2.0, True), (0.3333333, 0.333, False),
            (0.33333333, 0.333333, True), (1000001, 1000000, False), (3, 3.0, True), (True, 1, False)]
    got = [cc._same(g, e) for g, e, _ in nums]
    check("doubles within half the last place shown and 1e-5, whole numbers exact", got == [n[2] for n in nums], str(got))
    big_java = "class Solution {\n" + "".join(f"    private int helper{i}(int a, int b) {{ return a + b * {i}; }}\n"
                                              for i in range(450)) + "    public int solution(int a) {\n        return a;\n    }\n}"
    big_cpp = "".join(f"int helper{i}(int a, int b) {{ return a + b * {i}; }}\n" for i in range(450)) + "int solution(int a) {\n    return a;\n}"
    t = _time.perf_counter()
    sigs = (cc._java_signature(big_java, "solution"), cc._cpp_signature(big_cpp, "solution"))
    took = _time.perf_counter() - t
    check(f"a long answer's declaration read at once ({len(big_java) // 1000} KB, {took:.3f}s)",
          took < 0.5 and sigs == (("int", ["int"]), ("int", ["int"])), f"{sigs} {took:.2f}s")
    calls = []

    async def counting(lang, code, stdin):
        calls.append(stdin)
        return await _run(lang, code, stdin)
    res = await cc.run_cases("TYPE: coding\nANSWER: x\n```python\na, b = map(int, input().split())\nprint(a + b)\n```",
                             {"stdin": [{"input": f"{i} 1\n", "output": str(i + 1)} for i in range(3)]}, counting)
    check("standard-input examples in one request (compiled once)", res and res.get("passed") == 3 and len(calls) == 1
          and isinstance(calls[0], list) and len(calls[0]) == 3, f"{res} {calls}")
    route = os.path.join(tempfile.mkdtemp(), "route")
    with open(route, "w") as f:
        f.write("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
                "eth0\t00000000\t010018AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
                "eth0\t000018AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
                "eth1\t00001BAC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n")
    check("the gateway of the container's routes, from its routing table",
          [str(g) for g in route_gateways(route)] == ["172.24.0.1"], str(route_gateways(route)))
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["client"][0])
    guard = PeerGuard(inner, route)
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "websocket.connect"}
    peers = (("http", "172.27.0.3"), ("websocket", "172.27.0.3"), ("http", "172.24.0.5"), ("http", "fd00::1"),
             ("http", "172.24.0.1"), ("websocket", "::ffff:172.24.0.1"), ("http", "127.0.0.1"), ("http", "::1"),
             ("websocket", "testclient"))
    for kind, peer in peers:
        await guard({"type": kind, "client": (peer, 5000), "path": "/panel"}, receive, send)
    check("only the published port's gateway and the container itself let in, over HTTP and WebSocket: the runner's "
          "network, another container beside the server and IPv6 refused",
          seen == ["172.24.0.1", "::ffff:172.24.0.1", "127.0.0.1", "::1", "testclient"]
          and [m.get("status") for m in sent if m.get("type") == "http.response.start"] == [403, 403, 403]
          and sum(m.get("type") == "websocket.close" and m.get("code") == 1008 for m in sent) == 1, f"{seen} {sent}")
    # SIDENOTE_TRUST_GATEWAY off (the Helm chart): the pod's gateway is the node's bridge, so only loopback gets in
    seen.clear()
    sent.clear()
    tight = PeerGuard(inner, route, trust_gateway=False)
    for kind, peer in peers:
        await tight({"type": kind, "client": (peer, 5000), "path": "/panel"}, receive, send)
    check("with the gateway not trusted (Kubernetes) loopback alone gets in, the gateway refused like any other peer",
          seen == ["127.0.0.1", "::1", "testclient"]
          and [m.get("status") for m in sent if m.get("type") == "http.response.start"] == [403, 403, 403, 403]
          and sum(m.get("type") == "websocket.close" and m.get("code") == 1008 for m in sent) == 2, f"{seen} {sent}")


def test_runner_token():
    """The code runner over TCP (Kubernetes) takes a run only with its token, which the server sends; the token is
    gone from the runner's environment before any run starts; and the runner does not start outside its own
    read-only container, since its cleanup empties /tmp, /work and /dev/shm."""
    print("\n[the code runner's token, over TCP]")
    import importlib.util
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    import server.app as app
    os.environ["RUNNER_TOKEN"] = "s3cret-token"
    spec = importlib.util.spec_from_file_location("sidenote_runner", str(support.ROOT / "docker" / "runner.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)                     # the module only: main() never runs here
    check("the token is read once and taken out of the environment, so nothing the runner starts inherits it",
          runner.TOKEN == "s3cret-token" and "RUNNER_TOKEN" not in os.environ)
    check("outside its read-only container the runner refuses to start (this machine's root is writable)",
          runner._in_its_container() is False)
    runner.run = lambda *a, **k: {"ok": True, "stage": "run", "stdout": "ran"}   # what a real run would do is beside the point
    srv = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def ask(path, headers=None, body=b'{"lang": "python", "code": "print(1)"}'):
        req = urllib.request.Request(url + path, data=body, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    saved = app.CONFIG.runner_token
    try:
        check("a run with no token is refused (what a run inside the pod, or the node, could send)",
              ask("/run")[0] == 403)
        check("...and one with a wrong token", ask("/run", {"Authorization": "Bearer guess"})[0] == 403)
        check("the right token runs", ask("/run", {"Authorization": "Bearer s3cret-token"}) == (200, {"ok": True, "stage": "run", "stdout": "ran"}))
        check("/health answers without it (it says only whether the runner is clean and busy)",
              ask("/health", body=None)[0] == 200)
        app.CONFIG.runner_token = "s3cret-token"
        check("the server sends the token with a run", app._post_json(url + "/run", {"lang": "python", "code": "print(1)"}, 5).get("ok") is True)
        app.CONFIG.runner_token = ""
        try:
            app._post_json(url + "/run", {"lang": "python", "code": "print(1)"}, 5)
            refused = False
        except OSError as e:
            refused = "403" in str(e)
        check("...and without SIDENOTE_RUNNER_TOKEN its run is refused, as a stranger's would be", refused)
    finally:
        app.CONFIG.runner_token = saved
        srv.shutdown()
        srv.server_close()


async def test_check_declarations():
    print("\n[code check: numbers, arguments by name, declarations and each language's form]")
    import time as _time
    from server import codecheck as cc
    nums = [(0.9999999999999999, 1, True), (1000001.0, 1000000, False), (2 ** 2000, 0.5, False), (3, 3, True)]
    got = []
    for g, e, _ in nums:
        try:
            got.append(cc._same(g, e))
        except Exception as ex:   # noqa: BLE001
            got.append(type(ex).__name__)
    check("a double against a whole expected number, and an integer too large for a float", got == [n[2] for n in nums], str(got))
    check("an output that shows more places than a double holds allows the judge's error, an ordinary one does not",
          cc._same_output("0.3333333333333333", "0.33333333333333333333333333333333", 1e-9)
          and cc._same_output("0.8000000000", "0.8", 1e-9) and not cc._same_output("0.333", "0.33")
          and not cc._same_output("0.333333", "0.33333333333333333333333333333333", 1e-9))
    check("arguments by name, a lone one, a flat list for one parameter, defaults left out",
          cc._arguments({"target": 9, "nums": [2, 7]}, ["nums", "target"]) == [[2, 7], 9]
          and cc._lone("hello", ["s"], 1) and cc._arguments("hello", ["s"], 1, True) == ["hello"]
          and cc._lone([3, 0, 1], ["arr"], 1) and not cc._lone([[0]], ["arr"], 1)
          and cc._arguments([1, 2], ["a", "b", "c"]) is None and cc._arguments({"numbers": [1, 2]}, ["nums"]) == [[1, 2]]
          and cc._arguments({"a": 1, "b": 2}, ["m"]) is None   # several named values, one parameter: a mismatch
          and cc._arguments([10], ["n", "memo"], 1) == [10] and cc._arguments({"n": 10}, ["n", "memo"], 1) == [10])
    decls = [("python", "class Solution:\n    def f(self, root: Optional[TreeNode]) -> int:\n        return 0", ["root"], "value", None),
             ("python", "def f(nums, k=2):\n    nums.sort()", ["nums", "k"], None, None),
             ("javascript", "/**\n * @param {number[]} nums\n * @return {void} Do not return anything.\n */\nvar f = function(nums) {\n};",
              ["nums"], "void", None),
             ("typescript", "const f = (nums: number[], m: Map<string, number>): void => {\n};", ["nums", "m"], "void", None),
             ("typescript", "function f(head: ListNode | null): ListNode | null {\n  return head;\n}", ["head"], "value", None),
             ("kotlin", "class Solution {\n    fun f(s: CharArray) = s.reverse()\n}", ["s"], None, None),
             ("go", "func f(a, b int) int {\n\treturn a + b\n}", ["a", "b"], "value", None)]
    got = [cc._declaration(lang, code, "f") for lang, code, *_ in decls]
    check("declarations read: names, what the result says, a type an example cannot make",
          [(d or {}).get("names") for d in got] == [x[2] for x in decls]
          and [(d or {}).get("kind") for d in got] == [x[3] for x in decls]
          and [(d or {}).get("foreign") for d in got] == [x[4] for x in decls], str(got))
    shapes = [("class Solution:\n    def f(self, root: Optional[TreeNode]) -> int:\n        return 0",
               [["tree", "TreeNode"]], None),
              ("class Solution:\n    def f(self, lists: List[Optional[ListNode]]) -> Optional[ListNode]:\n        return None",
               [["lists", "ListNode"]], ["list", "ListNode"]),
              ("class Solution:\n    def f(self, head) -> int:\n        return head.next.val", [["list", "ListNode"]], None),
              ("class Solution:\n    def f(self, root: 'Node') -> int:\n        return len(root.children)", [None], None),
              ("class Solution:\n    def f(self, nums: List[int]) -> int:\n        return 0", [None], None)]
    # the same reading in a language whose types are written another way
    ts = cc._declaration("typescript", "function f(head: ListNode | null, k: number): ListNode | null {\n"
                         "  return head;\n}", "f")
    check("a tree or a list read off a TypeScript declaration",
          ts["shapes"] == [["list", "ListNode"], None] and ts["result"] == ["list", "ListNode"], str(ts))
    got = [cc._declaration("python", code, "f") for code, *_ in shapes]
    check("a tree or a list as a parameter or a result, and the shapes an example cannot fill",
          [d["shapes"] for d in got] == [x[1] for x in shapes]
          and [d["result"] for d in got] == [x[2] for x in shapes]
          and [bool(d["foreign"]) for d in got] == [False, False, False, True, False], str(got))
    check("LeetCode's form is a Solution method with its own name, not Programmers' solution",
          cc._leetcode_form("class Solution {\npublic:\n    int twoSum() {", "twoSum")
          and not cc._leetcode_form("class Solution {\n    public int solution() {", "solution")
          and not cc._leetcode_form("// class Solution\nint twoSum() {", "twoSum"))
    over = "class Solution {\n    private int solution(int[] a, int i, int t, int s) { return 0; }\n    public int solution(int[] a, int t) {\n        return 1;\n    }\n}"
    check("the overload that takes as many arguments as the examples", cc._java_signature(over, "solution", 2) == ("int", ["int[]", "int"])
          and cc._java_signature(over, "solution") == ("int", ["int[]", "int", "int", "int"]))
    prog = cc.cpp_harness("// not a class Solution here\nint solution(int a, int b) {\n    return a + b;\n}", "solution",
                          [{"args": [1, 2], "expected": 3}]) or ""
    check("C++: a class named in a comment is not the owner", "Solution{}." not in prog and "solution(_a0, _a1)" in prog)
    prog = cc.go_harness("package main // 프로그래머스\n\nfunc solution(a int) int {\n\treturn a\n}", "solution",
                         [{"args": [1], "expected": 1}]) or ""
    check("Go: a package clause with a comment after it is the one replaced", prog.count("package main") == 1, prog[:120])
    prog = cc.java_harness("public int twoSum(int[] a, int t) {\n    return 0;\n}", "twoSum", [{"args": [[1], 1], "expected": 0}]) or ""
    check("Java: a method shown without its class is put in one", "class Solution {" in prog and "new Solution().twoSum(" in prog)
    check("Java: a package line inside a text block stays", "package com.evil;" in cc._drop_java_package(
        'package a.b;\nclass M {\n  String t = """\npackage com.evil;\n""";\n}') and not cc._drop_java_package("package a.b;\nclass M {}").startswith("package"))
    t = _time.perf_counter()
    for lang in ("cpp", "c"):
        cc.SOLUTION_MARK[lang].search("abc def, " * 1200)
    took = _time.perf_counter() - t
    check(f"the C and C++ markers on 10 KB of words ({took * 1000:.1f} ms)", took < 0.05)
    found = {}

    async def fake(lang, code, stdin):
        found["stdin"] = stdin
        return {"ok": True, "stage": "run", "runs": [{"ok": True, "exit": 0, "stdout": "5"}]}
    await cc.run_cases("TYPE: coding\nANSWER: x\n```c\n#include <stdio.h>\nint main(void) { return 0; }\n```",
                       {"stdin": [{"input": "hello", "output": "5"}]}, fake)
    check("an example's input ends with a newline, as a judge's input file does", found.get("stdin") == ["hello\n"], str(found))

    async def old_runner(lang, code, stdin):
        return {"ok": True, "stage": "run", "exit": 0, "stdout": "3"}
    res = await cc.run_cases("TYPE: coding\nANSWER: x\n```python\nprint(sum(map(int, input().split())))\n```",
                             {"stdin": [{"input": "1 2\n", "output": "3"}, {"input": "2 2\n", "output": "4"}]}, old_runner)
    check("a runner that does not take the inputs together is said to be one, not judged on one input",
          res and "다시 빌드" in res.get("error", ""), str(res))


async def test_check_spec():
    print("\n[the judging the problem itself asks for: order, returns, tolerance]")
    from server import codecheck as cc
    from server.analyzer import LocalLlmAnalyzer
    # What the reader wrote for Two Sum ("You can return the answer in any order") in the corpus run, the
    # shape it gave on 26 of the 85 statements that say so: the "any" under returns, none under order.
    reader = LocalLlmAnalyzer(CONFIG)

    async def wrote(system, images, text, max_tokens):
        return ('{"function": "twoSum", "cases": [{"args": [[2, 7, 11, 15], 9], "expected": [0, 1]}], '
                '"returns": "any"}')
    reader._plain = wrote
    got = await reader.cases([], problem="You can return the answer in any order.")
    check("a reading that put the any of \"in any order\" under returns is read as order any",
          got.get("order") == "any" and "returns" not in got, str(got))

    async def plain_value(system, images, text, max_tokens):
        return '{"function": "f", "cases": [], "returns": "value"}'
    reader._plain = plain_value
    got = await reader.cases([], problem="Return the sum.")
    check("...and a reading that says returns value is left as it is", got == {"function": "f", "cases": [],
                                                                                 "returns": "value"}, str(got))
    await reader.aclose()
    ANAGRAM = "TYPE: coding\nANSWER: x\n```python\nfrom collections import defaultdict\ndef groupAnagrams(strs):\n" \
              "    d = defaultdict(list)\n    for w in strs:\n        d[''.join(sorted(w))].append(w)\n" \
              "    return list(d.values())\n```"
    cases = {"function": "groupAnagrams", "returns": "value",
             "cases": [{"args": [["eat", "tea", "tan", "ate", "nat", "bat"]],
                        "expected": [["bat"], ["nat", "tan"], ["ate", "eat", "tea"]]}]}
    res = await cc.run_cases(ANAGRAM, cases, _run)
    check("an answer in another order fails when the problem does not say any order", res and res.get("passed") == 0,
          str(res))
    res = await cc.run_cases(ANAGRAM, {**cases, "order": "any"}, _run)
    check("any order does not reach inside an element: the groups themselves are in another order, which fails, "
          "and the card says the values came out in another order",
          res and res.get("passed") == 0 and res["fails"][0].get("order_only") is True, str(res))
    PERM = "TYPE: coding\nANSWER: x\n```python\nfrom itertools import permutations\ndef permute(nums):\n" \
           "    return [sorted(p) for p in permutations(nums)]\n```"
    perm = {"function": "permute", "order": "any", "returns": "value",
            "cases": [{"args": [[1, 2, 3]], "expected": [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1]]}]}
    res = await cc.run_cases(PERM, perm, _run)
    check("a Permutations answer that loses the order inside each one fails, though the problem says any order",
          res and res.get("passed") == 0, str(res))
    GROUPS = "TYPE: coding\nANSWER: x\n```python\ndef groups(n):\n    return [[3, 4], [1, 2]]\n```"
    res = await cc.run_cases(GROUPS, {"function": "groups", "order": "any",
                                      "cases": [{"args": [0], "expected": [[1, 2], [3, 4]]}]}, _run)
    check("elements in another order pass when the problem says any order", res and res.get("passed") == 1
          and res.get("rule") == "순서 무관", str(res))
    res = await cc.run_cases(ANAGRAM, {**cases, "order": "any",
                                       "cases": [{"args": [["eat", "tea"]], "expected": [["eat"], ["tea"]]}]}, _run)
    check("any order does not make a wrong grouping pass", res and res.get("passed") == 0, str(res))
    res = await cc.run_cases(ANAGRAM, cases, _run)
    check("a failing example whose result is the expected one in another order says so on the card",
          res and res["fails"][0].get("order_only") is True, str(res))
    res = await cc.run_cases(ANAGRAM, {**cases, "cases": [{"args": [["eat"]], "expected": [["tea"]]}]}, _run)
    check("a result that is no reordering of the expected one does not", res and "order_only" not in res["fails"][0],
          str(res))
    SORTED = "TYPE: coding\nANSWER: x\n```python\ndef sortArray(nums):\n    nums.sort()\n```"
    one = {"function": "sortArray", "cases": [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}]}
    res = await cc.run_cases(SORTED, one, _run)
    check("a function that sorts its argument and forgets the return passes while nothing says otherwise",
          res and res.get("passed") == 1, str(res))
    res = await cc.run_cases(SORTED, {**one, "returns": "value"}, _run)
    check("it fails once the problem says the answer is returned", res and res.get("passed") == 0, str(res))
    PLACE = "TYPE: coding\nANSWER: x\n```python\ndef solution(numbers):\n    numbers.sort(reverse=True)\n```"
    place = {"function": "solution", "cases": [{"args": [[1, 3, 2]], "expected": [3, 2, 1]}, {"args": [[5]], "expected": [5]}]}
    res = await cc.run_cases(PLACE, place, _run)
    check("Programmers' `solution` that returns nothing fails while nothing says otherwise",
          res and res.get("passed") == 0, str(res))
    res = await cc.run_cases(PLACE, {**place, "returns": "in_place"}, _run)
    check("it passes once the problem says to fix the argument, the example left as it was among them",
          res and res.get("passed") == 2 and res.get("rule") == "제자리 수정", str(res))
    DIST = "TYPE: coding\nANSWER: x\n```python\nimport math\ndef solution(x1, y1, x2, y2):\n" \
           "    return math.hypot(x2 - x1, y2 - y1) * (1 + 1e-4)\n```"
    dist = {"function": "solution", "cases": [{"args": [0, 0, 3, 4], "expected": 5.0}]}
    res = await cc.run_cases(DIST, dist, _run)
    check("a result off by more than the 1e-5 a double is read within fails while the problem says no error",
          res and res.get("passed") == 0, str(res))
    res = await cc.run_cases(DIST, {**dist, "tolerance": 1e-3}, _run)
    check("it passes within the error the problem allows, and the card says the error",
          res and res.get("passed") == 1 and res.get("rule") == "오차 0.001", str(res))
    res = await cc.run_cases(DIST.replace("1e-4", "1e-2"), {**dist, "tolerance": 1e-3}, _run)
    check("a result outside that error still fails", res and res.get("passed") == 0, str(res))
    for bad in (0, -1, 1, "1e-6", True):
        if cc._tolerance({"tolerance": bad}):
            check(f"a tolerance of {bad!r} is read as none", False, "it was used")
            break
    else:
        check("0, a negative, a whole number, a string and true are no tolerance", True)
    AB = "TYPE: coding\nANSWER: x\n```python\na, b = map(int, input().split())\nprint(a / b)\n```"
    ab = {"stdin": [{"input": "1 3\n", "output": "0.333"}]}
    res = await cc.run_cases(AB, ab, _run)
    check("a program's output rounded differently fails while the problem says no error",
          res and res.get("passed") == 0, str(res))
    res = await cc.run_cases(AB, {**ab, "tolerance": 1e-3}, _run)
    check("it passes within the error the problem allows", res and res.get("passed") == 1, str(res))
    check("a list is put in one order without reaching inside its elements, and deep only for the card's note",
          cc._unordered([[1, 3], [2]]) == cc._unordered([[2], [1, 3]])
          and cc._unordered([[3, 1], [2]]) != cc._unordered([[2], [1, 3]])
          and cc._unordered([[3, 1], [2]], True) == cc._unordered([[2], [1, 3]], True)
          and cc._unordered([1, 2]) != cc._unordered([1, 3])
          and cc._unordered([[1, 2]]) != cc._unordered([[1], [2]]), str(cc._unordered([[3, 1], [2]])))
    SORT = "TYPE: coding\nANSWER: x\n```python\nclass Solution:\n    def sortArray(self, nums):\n" \
           "        return sorted(nums)\n```"
    named = {"function": "solution", "cases": [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}]}
    res = await cc.run_cases(SORT, named, _run)
    check("the one function the answer defines is run when the examples name another",
          res and res.get("passed") == 1, str(res))
    # Examples read off a LeetCode statement name their arguments ("Input: a = 1, b = 20"), and an answer written
    # without the editor in view names the function itself: the two named arguments are two, not one (the local
    # model's answers to 21 of 46 problems in real use went unchecked this way).
    UNIQUE = "TYPE: coding\nANSWER: x\n```python\ndef count_unique(a: int, b: int) -> int:\n" \
             "    return sum(len(set(str(v))) == len(str(v)) for v in range(a, b + 1))\n```"
    res = await cc.run_cases(UNIQUE, {"function": "numberCount", "cases": [{"args": {"a": 1, "b": 20}, "expected": 19}]}, _run)
    check("examples with named arguments count as that many when the answer names its function itself",
          res and res.get("passed") == 1, str(res))
    TWO = SORT + "\n```python\ndef helper(a, b):\n    return a + b\n\ndef other(nums):\n    return nums\n```"
    res = await cc.run_cases(TWO, named, _run)
    check("nothing is guessed when the answer defines more than one function of that many arguments",
          res and "없음" in res.get("skipped", ""), str(res))
    check("a call or a keyword is not taken for a definition",
          cc._answer_function("```python\nprint(sorted([1]))\nif (x):\n    pass\n```", 1) is None,
          str(cc._answer_function("```python\nprint(sorted([1]))\n```", 1)))
    LARGEST = "TYPE: coding\nANSWER: x\n```python\nfrom functools import cmp_to_key\ndef largestNumber(nums):\n" \
              "    def cmp(a, b):\n        return (int(b + a) > int(a + b)) - (int(b + a) < int(a + b))\n" \
              "    return ''.join(sorted(map(str, nums), key=cmp_to_key(cmp))).lstrip('0') or '0'\n```"
    res = await cc.run_cases(LARGEST, {"function": "solution",
                                       "cases": [{"args": [10, 2], "expected": "210"}]}, _run)
    check("an example whose arguments are the lone argument does not make a helper of that many the answer",
          res and res.get("passed") == 1, str(res))
    check("a function is kept or dropped by how many arguments it really takes, in every language",
          cc._answer_function("```java\nclass S {\n  public String largestNumber(int[] nums) { return \"\"; }\n"
                              "  int compare(String a, String b) { return 0; }\n}\n```", {1}) == "largestNumber"
          and cc._answer_function("```python\ndef f(a):\n    return a\ndef g(a, b):\n    return a\n```", {1}) == "f",
          str(cc._answer_function("```java\nclass S {\n  public String largestNumber(int[] nums) { return \"\"; }\n"
                                  "  int compare(String a, String b) { return 0; }\n}\n```", {1})))
    MERGE = "TYPE: coding\nANSWER: x\n```python\nclass Solution:\n    def merge(self, nums1, m, nums2, n) -> None:\n" \
            "        nums1[m:] = nums2[:n]\n        nums1.sort()\n```"
    merge = {"function": "merge", "cases": [{"args": [[1, 2, 3, 0, 0, 0], 3, [2, 5, 6], 3], "expected": [1, 2, 2, 3, 5, 6]}]}
    res = await cc.run_cases(MERGE, {**merge, "returns": "value"}, _run)
    check("a problem that says the answer is returned does not overrule a function that declares it returns nothing",
          res and res.get("passed") == 1, str(res))
    res = await cc.run_cases(SORT, {**named, "returns": "in_place", "function": "sortArray"}, _run)
    check("nor the other way round: a function that declares a value is judged by what it returns",
          res and res.get("passed") == 1, str(res))
    for bad in (["value"], {"kind": "value"}, 1, None):
        res = await cc.run_cases(SORT, {"function": "sortArray", "returns": bad,
                                        "cases": [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}]}, _run)
        if not res or res.get("passed") != 1:
            check(f"a returns of {bad!r} is read as nothing said", False, str(res))
            break
    else:
        check("a returns that is a list, an object, a number or nothing is read as nothing said", True)
    AB2 = "TYPE: coding\nANSWER: x\n```python\nimport sys\nns = sys.stdin.read().split()\nprint(' '.join(sorted(ns[1:])))\n```"
    unordered_out = {"stdin": [{"input": "3\nb a c\n", "output": "c\nb\na"}], "order": "any"}
    res = await cc.run_cases("TYPE: coding\nANSWER: x\n```python\nimport sys\n"
                             "for w in sys.stdin.read().split()[1:]:\n    print(w)\n```", unordered_out, _run)
    check("a program's output in another order passes when the problem says the order does not matter",
          res and res.get("passed") == 1 and res.get("rule") == "순서 무관", str(res))
    res = await cc.run_cases(AB2, {**unordered_out, "order": "fixed"}, _run)
    check("and fails when it does not", res and res.get("passed") == 0, str(res))
    check("a tolerance does not loosen a whole number beside the real one",
          cc._same([1000000500, 0.5], [1000000000, 0.5], 1e-6) is False
          and cc._same(11, 10, 0.1) is False and cc._same(10.00001, 10.0, 1e-5) is True, "")
    check("the card says nothing when nothing was judged by more than an exact match",
          cc._rule({}, None) == {} and cc._rule({"order": "any"}, "void", 1e-9) ==
          {"rule": "순서 무관, 제자리 수정, 오차 1e-09"}
          and cc._rule({}, None, 1e-9) == {"rule": "오차 1e-09"},
          str(cc._rule({"order": "any"}, "void", 1e-9)))
    LONG = "TYPE: coding\nANSWER: x\n```python\na, b = map(int, input().split())\nprint(a / b)\n```"
    res = await cc.run_cases(LONG, {"stdin": [{"input": "1 3\n",
                                               "output": "0.33333333333333333333333333333333"}]}, _run)
    check("an example with more places than a double holds says on the card which error was used",
          res and res.get("passed") == 1 and res.get("rule") == "오차 1e-09", str(res))


def test_theme_tokens():
    """The panel is themed twice: once for a browser that asks for dark, once for dark chosen in the
    panel. A colour added to one and not the other falls back to its light value, which is
    how a code block came out white-on-white in dark mode."""
    import re
    html = (pathlib.Path(__file__).resolve().parents[1] / "panel" / "index.html").read_text(encoding="utf-8")

    def tokens(block):
        return set(re.findall(r"(--[\w-]+)\s*:", block))

    root = html[html.index(":root {"):html.index("@media (prefers-color-scheme: dark)")]
    media_at = html.index("@media (prefers-color-scheme: dark)")
    media = html[media_at:html.index("}", html.index(":root", media_at) + 10)]
    chosen_at = html.index('[data-theme="dark"]')
    chosen = html[chosen_at:html.index("}", chosen_at)]
    check("the two dark themes define the same colours", tokens(media) == tokens(chosen),
          f"media only: {sorted(tokens(media) - tokens(chosen))}, chosen only: {sorted(tokens(chosen) - tokens(media))}")
    check("the dark theme covers every background colour",
          {"--paper", "--sheet", "--sheet-2", "--code", "--code-bar", "--ink", "--rule"} <= tokens(media),
          str(sorted(tokens(media))[:12]))
    check("the dark theme makes no colour the light one lacks", tokens(media) <= tokens(root),
          f"dark only: {sorted(tokens(media) - tokens(root))}")


def test_page_text():
    """The readable text of a page the model fetched. The menu-drawer shape is go.dev/dl's own: four
    nested <nav> opened, one closed, the rest left to </aside> (read off the page)."""
    from server.search import _Text

    def read(html):
        p = _Text()
        p.feed(html)
        return p.text()

    drawer = ('<html><head><title>All releases</title></head><body>'
              '<header><nav class="Header-nav"><a href="/">Go</a></nav></header>'
              '<aside class="NavigationDrawer">'
              '<nav class="NavigationDrawer-nav"><div>Why Go</div>'
              '<nav class="NavigationDrawer-nav"><div>Case Studies</div>'
              '<nav class="NavigationDrawer-nav"><div>Use Cases</div>'
              '<nav class="NavigationDrawer-nav"><div>Security</div>'
              '</nav></aside>'
              '<h2>Featured downloads</h2><div>go1.27.3.windows-amd64.msi</div>'
              '<p>Minor revisions of the latest release.</p></body></html>')
    t = read(drawer)
    check("a menu left open does not swallow the page", "go1.27.3.windows-amd64.msi" in t, t[:120])
    check("the menu itself stays out", "Case Studies" not in t and "Header-nav" not in t, t[:200])
    check("the page's title is read", read(drawer) is not None and _Text_title(drawer) == "All releases")

    stray = "<html><body><div>one</div></span></section><p>two</p></body></html>"
    check("an end tag for nothing open closes nothing", "one" in read(stray) and "two" in read(stray), read(stray))

    void = '<html><body><p>a<br><img src="x.png">b</p><input><p>c</p></body></html>'
    check("a void tag is not held open", all(x in read(void) for x in ("a", "b", "c")), read(void))

    both = ('<html><body><nav><div>menu one</div></nav>'
            '<main><p>' + "the page's own words. " * 20 + '</p></main>'
            '<footer><div>menu two</div></footer></body></html>')
    t = read(both)
    check("a page's own content wins over its menus",
          "the page's own words" in t and "menu one" not in t and "menu two" not in t, t[:120])

    short = '<html><body><article><p>short</p></article><p>' + "the rest of the page. " * 30 + '</p></body></html>'
    t = read(short)
    check("too little inside <article> falls back to the whole page", "the rest of the page" in t, t[:120])


def _Text_title(html):
    from server.search import _Text
    p = _Text()
    p.feed(html)
    return p.title.strip()


async def main():
    test_settings()
    test_heads()
    test_page_text()
    test_theme_tokens()
    await test_pipeline()
    await test_claude_brake()
    await test_claude_knobs()
    await test_check()
    await test_check_langs()
    await test_check_more_langs()
    await test_check_and_runner()
    await test_check_declarations()
    await test_check_spec()
    await test_verify()
    await test_pipeline_fixes()
    test_window_clip()
    await test_crop_placement()
    await test_editor_note()
    await test_server_fixes()
    await test_local_zoom()
    await test_asked_again_halves()
    await test_local_engine()
    await test_stuck_runtime()
    await test_gpu_pace()
    await test_thinking_cut()
    await test_search_turned_away()
    await test_pace_shared()
    await test_load_kept()
    await test_claude_gets_the_searches()
    await test_runaway_and_examples()
    await test_continuation_check()
    await test_activity()
    await test_server_examples_hold()
    await test_pause_stops_load()
    await test_run_args()
    test_runner_token()
    test_face_mask()
    support.skip_line()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


asyncio.run(main())
