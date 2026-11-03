"""The cloud agents beyond Claude Code: Codex through its CLI (against tests/fake_codex.py), the choice of agent
read from the environment as before and now, the newest model of a family, and what the panel is told.

    .venv/bin/python tests/codex_agent.py
"""
import asyncio
import base64
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent   # tests/, where the stand-in for the codex CLI is
ROOT = HERE.parent                       # the repository
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SIDENOTE_ANALYZER", "mock")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def png() -> str:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def config(**env) -> dict:
    """How server/config.py reads the agent for an environment: in a process of its own, since the defaults are read
    when the module is imported."""
    code = ("import json; from server.config import CONFIG, agent_name; "
            "print(json.dumps({'agent': CONFIG.agent, 'analyzer': CONFIG.analyzer, 'model': CONFIG.agent_model, "
            "'effort': CONFIG.agent_effort, 'name': agent_name()}))")
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SIDENOTE_")}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**clean, **env}, capture_output=True, text=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


async def main():
    from server.agents import CodexAgent, codex_args, codex_auth_status, make_agent, LOGIN_HINTS
    from server.analyzer import error_hint
    from server.config import CONFIG
    from server.settings import SETTINGS
    SETTINGS.path = None
    fake = str(HERE / "fake_codex.py")
    cfg = dataclasses.replace(CONFIG, agent="codex", agent_bin=fake, agent_model="", agent_effort="",
                              cli_timeout=20, cli_turn_budget=60)

    print("\n[codex: the command]")
    SETTINGS.values.update(agent_model_name="", agent_effort="")
    args = codex_args(cfg, "/tmp/work", [Path("/tmp/work/picture-1.png"), Path("/tmp/work/picture-2.png")])
    joined = " ".join(args)
    check("exec, JSON events, nothing kept, outside a repo, the user's config and rules left out",
          args[1] == "exec" and all(a in args for a in ("--json", "--ephemeral", "--skip-git-repo-check",
                                                          "--ignore-user-config", "--ignore-rules")), joined)
    check("a read-only sandbox, and never stops to ask", "--sandbox read-only" in joined and 'approval_policy="never"' in joined,
          joined)
    check("the pictures in order, the request on stdin", args[-1] == "-" and
          [args[i + 1] for i, a in enumerate(args) if a == "--image"] == ["/tmp/work/picture-1.png", "/tmp/work/picture-2.png"],
          joined)
    check("no model or effort when none is chosen: Codex's own default", "--model" not in args and "model_reasoning_effort" not in joined, joined)
    SETTINGS.values.update(agent_model_name="gpt-5.5-codex", agent_effort="high")
    args = codex_args(cfg, "/tmp/work", [])
    check("a chosen model and effort go on the command", args[args.index("--model") + 1] == "gpt-5.5-codex"
          and 'model_reasoning_effort="high"' in " ".join(args), " ".join(args))
    SETTINGS.values.update(agent_model_name="", agent_effort="")

    print("\n[codex: an answer]")
    log = Path(tempfile.mkdtemp()) / "fake.json"
    os.environ["FAKE_CODEX_LOG"] = str(log)
    pieces = []

    async def on_delta(t):
        pieces.append(t)
    os.environ["FAKE_CODEX_MODE"] = "stream"
    agent = CodexAgent(cfg)
    res = await agent.run([png(), png()], "[문제] 두 수의 합", on_delta)
    seen = json.loads(log.read_text())
    check("the answer streams in pieces and adds up to the whole", len(pieces) == 3 and "".join(pieces) == res.text
          and res.text.startswith("TYPE: algorithm"), repr(pieces))
    check("the usage: the cached input apart from the rest, the reasoning kept",
          res.usage == {"input_tokens": 3000, "output_tokens": 120, "cache_read": 6000, "cache_write": 0, "reasoning_tokens": 40},
          str(res.usage))
    check("no price for a Codex login: the cost stays unknown", res.cost_usd is None, str(res.cost_usd))
    check("the request carries the system prompt and the problem", seen["request"].endswith("[문제] 두 수의 합")
          and "TYPE:" in seen["request"], seen["request"][:60])
    work = seen["args"][seen["args"].index("--cd") + 1]
    check("both pictures went as PNG files, in a folder of the run's own that is gone after it",
          seen["images"] == [True, True] and work.startswith(tempfile.gettempdir()) and not Path(work).exists(),
          f"{seen['images']} {work}")
    pieces.clear()
    os.environ["FAKE_CODEX_MODE"] = "whole"
    res = await agent.run([], "q", on_delta)
    check("an answer sent whole at its end arrives whole", pieces == [res.text] and "본문입니다" in res.text, repr(pieces))
    pieces.clear()
    os.environ["FAKE_CODEX_MODE"] = "two"
    res = await agent.run([], "q", on_delta)
    check("a second message comes as a paragraph of its own", res.text.endswith("본문입니다.\n\n덧붙임.") and "".join(pieces) == res.text,
          repr(res.text[-30:]))

    print("\n[codex: failures]")
    os.environ["FAKE_CODEX_MODE"] = "fail"
    try:
        await agent.run([], "q", on_delta)
        check("a failed turn raises", False)
    except RuntimeError as exc:
        check("a failed turn raises with its own words, read as a sign-in problem",
              "401" in str(exc) and error_hint(str(exc)) == "auth", str(exc))
    os.environ["FAKE_CODEX_MODE"] = "die"
    try:
        await agent.run([], "q", on_delta)
        check("a CLI that dies raises", False)
    except RuntimeError as exc:
        check("a CLI that dies says what it wrote on stderr (Not logged in)", "Not logged in" in str(exc)
              and error_hint(str(exc)) == "auth", str(exc))

    print("\n[codex: sign-in]")
    os.environ["FAKE_CODEX_MODE"] = "stream"
    st = await codex_auth_status(cfg)
    check("signed in with ChatGPT", st == {"ok": True, "method": "chatgpt"}, str(st))
    os.environ["FAKE_CODEX_MODE"] = "noauth"
    st = await codex_auth_status(cfg)
    check("signed out", st.get("ok") is False, str(st))
    a = make_agent(cfg)
    check("SIDENOTE_AGENT=codex makes the Codex agent, named and signed in by its own command",
          isinstance(a, CodexAgent) and a.label == "Codex" and LOGIN_HINTS["codex"] == "./sidenote login codex")

    print("\n[the agent chosen by the environment]")
    for env, want in (({}, ("claude-code", "local")),
                      ({"SIDENOTE_AGENT": "codex"}, ("codex", "local")),
                      ({"SIDENOTE_AGENT": " Codex "}, ("codex", "local")),
                      ({"SIDENOTE_CLAUDE": "cli"}, ("claude-code", "local")),
                      ({"SIDENOTE_CLAUDE": "api"}, ("anthropic-api", "local")),
                      ({"SIDENOTE_CLAUDE": "off"}, ("off", "local")),
                      ({"SIDENOTE_ANALYZER": "cli"}, ("claude-code", "agent")),
                      ({"SIDENOTE_ANALYZER": "claude"}, ("anthropic-api", "agent")),
                      ({"SIDENOTE_ANALYZER": "agent", "SIDENOTE_AGENT": "codex"}, ("codex", "agent")),
                      ({"SIDENOTE_AGENT": "gemini"}, ("claude-code", "local"))):
        got = config(**env)
        check(f"{env or 'nothing set'} -> {want[0]}, {want[1]}", (got["agent"], got["analyzer"]) == want, str(got))
    got = config(SIDENOTE_CLAUDE_MODEL="claude-opus-5-5", SIDENOTE_CLAUDE_EFFORT="high")
    check("the earlier SIDENOTE_CLAUDE_MODEL and _EFFORT still count", got["model"] == "claude-opus-5-5" and got["effort"] == "high", str(got))
    got = config(SIDENOTE_AGENT="codex", SIDENOTE_FAST="1")
    check("the fast profile gives Codex a low effort and leaves its model alone", got["model"] == "" and got["effort"] == "low", str(got))
    got = config(SIDENOTE_FAST="1")
    check("...and Claude Code the newest Sonnet", got["model"] == "sonnet", str(got))
    check("the panel's sentences say the agent, whichever it is, in the language set",
          config(SIDENOTE_AGENT="codex", SIDENOTE_LANG="ko")["name"] == "에이전트"
          and config(SIDENOTE_LANG="ko")["name"] == "에이전트"
          and config(SIDENOTE_AGENT="off", SIDENOTE_LANG="ko")["name"] == "에이전트"
          and config(SIDENOTE_AGENT="codex")["name"] == "Agent")

    print("\n[the newest model of a family]")
    from server.agents import AnthropicApiAgent, chosen
    from server.analyzer import price_of, PRICES
    from server.settings import SETTINGS

    class Models:
        """A stand-in for client.models: the ids with their release dates, in the order given (not newest first)."""
        def __init__(self, models, fail=False):
            self.models, self.fail, self.calls = models, fail, 0

        async def list(self, limit=100):
            self.calls += 1
            if self.fail:
                raise RuntimeError("no network")
            return type("Page", (), {"data": [type("M", (), {"id": i, "created_at": t})() for i, t in self.models]})()
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(agent_model_name="", agent_effort="")     # nothing chosen in the panel
        api = AnthropicApiAgent.__new__(AnthropicApiAgent)
        api.cfg = dataclasses.replace(CONFIG, agent="anthropic-api", model="opus", effort="medium")
        api._resolved = {}
        listed = Models([("claude-opus-5-5", "2026-08-01T00:00:00Z"), ("claude-sonnet-6-0", "2027-01-10T00:00:00Z"),
                         ("claude-opus-6-0", "2027-01-10T00:00:00Z")])
        api._client = type("C", (), {"models": listed})()
        check("`opus` is the newest Opus by its release date, not by its place in the list",
              await api.model() == "claude-opus-6-0", str(api._resolved))
        await api.model()
        check("...looked up once a run", listed.calls == 1, str(listed.calls))
        SETTINGS.values["agent_model_name"] = "sonnet"
        check("the family chosen in the panel wins over SIDENOTE_MODEL, looked up on its own",
              await api.model() == "claude-sonnet-6-0" and listed.calls == 2, str(api._resolved))
        SETTINGS.values["agent_model_name"] = ""
        check("nothing chosen in the panel: SIDENOTE_EFFORT is the effort sent", api.request_options() == {"output_config": {"effort": "medium"}},
              str(api.request_options()))
        SETTINGS.values["agent_effort"] = "xhigh"
        check("the effort chosen in the panel is the one sent", api.request_options() == {"output_config": {"effort": "xhigh"}},
              str(api.request_options()))
        api.cfg = dataclasses.replace(api.cfg, effort="")
        SETTINGS.values["agent_effort"] = ""
        check("no effort anywhere: none is sent, so the model's own default holds", api.request_options() == {})
        api._resolved = {}
        api._client = type("C", (), {"models": Models([], fail=True)})()
        check("with the list out of reach, the newest Opus the price table knows", await api.model() == next(n for n in PRICES if "opus" in n),
              str(api._resolved))
        api.cfg = dataclasses.replace(api.cfg, model="claude-sonnet-5-5")
        check("a full name is kept as it is", await api.model() == "claude-sonnet-5-5")
        check("a newer release than the table is priced as its family's newest", price_of("claude-opus-6-0") == PRICES["claude-opus-5-5"]
              and price_of("claude-haiku-7") == PRICES["claude-haiku-5-5"] and price_of("gpt-5") is None)
        # chosen(): what every agent is asked for, and what the panel's agent card shows
        cli = dataclasses.replace(CONFIG, agent="claude-code", model="opus", effort="medium")
        SETTINGS.values.update(agent_model_name="", agent_effort="")
        check("a CLI with nothing chosen picks for itself (SIDENOTE_MODEL is the API's)", chosen(cli) == ("", ""), str(chosen(cli)))
        SETTINGS.values.update(agent_model_name="haiku", agent_effort="high")
        check("...and takes the panel's choice when there is one", chosen(cli) == ("haiku", "high"), str(chosen(cli)))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)

    print("\n[the speed kept on disk before the agent was general]")
    from server.pipeline import Speed
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / ".speed.json"
        f.write_text(json.dumps({"claude": [3.0, 4.0, 5.0], "think": [60.0]}))
        sp = Speed(f)
        check("its 'claude' times are the agent's", sp.usual("agent") == 4.0 and sp.usual("think") == 60.0, str(sp.times))

    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    return 1 if FAIL else 0


sys.exit(asyncio.run(main()))
