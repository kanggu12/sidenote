"""The cloud agents the server hands a problem to: a coding agent's own CLI signed in on this PC, or a vendor's API.

Most screens are solved by this PC's local model (analyzer.LocalLlmAnalyzer); the hard ones, and every one while the
local model is off, go to one cloud agent, chosen with SIDENOTE_AGENT:

  claude-code    Anthropic's Claude Code CLI with this PC's login (~/.claude, `./sidenote login`). The default.
  codex          OpenAI's Codex CLI with this PC's login (~/.codex, `codex login`).
  anthropic-api  the Anthropic Messages API with ANTHROPIC_API_KEY.
  off            no cloud agent: the local model answers everything.

Every agent takes the same request, the pictures (base64 PNG, the screen or crop first, then page tiles), the text and
a callback for the answer's pieces as they come, and gives back an AnalysisResult. The pipeline (server/pipeline.py)
decides which problems an agent gets and what it may be shown; nothing here knows about screens or settings beyond
the agent's own model and effort.

An agent here is a helper, not a session of the user's: none of the user's own settings, hooks, plugins, rules or
MCP servers are loaded, no tools are offered beyond a web search where it is asked for, and nothing is saved as a
session to resume.
"""
from __future__ import annotations

import asyncio      # each CLI is a child process read line by line
import base64       # the pictures arrive base64 and Codex takes them as files
import json         # both CLIs speak JSON lines
import logging      # what each agent started and how it ended
import os           # the API key's presence, and the home the CLIs keep their logins in
import re           # the plan's tier in its login, and the usage address's times
import signal       # a cancelled CLI is stopped with everything it started (kill_group)
import subprocess   # the start options each CLI gets, and taskkill on Windows
import sys          # Windows starts its CLIs with no console window
import tempfile     # a working folder of its own for each Codex run, removed after it
import time         # the limit on one turn's whole length
import urllib.request   # what is left of the plan's limits (read_plan_usage)
from datetime import datetime
from pathlib import Path

from . import forksafe                                      # every child process is started through its guard
from .config import AGENT_LABELS as LABELS, agent_label as label   # the names the panel shows, kept beside the config
from .analyzer import (INDEPENDENCE_NOTE, SYSTEM_PROMPT, AnalysisResult, OnDelta, build_user_text, in_answer_language,
                       estimate_cost, image_blocks)
from .i18n import t
from .settings import SETTINGS                              # the model and effort the panel may change while running

log = logging.getLogger("sidenote.agents")

# Each CLI starts in a group of its own, so a cancelled turn stops all of it: npm's codex.js passes SIGKILL on to
# nothing, and its native binary went on with the turn, and the usage, after the cancel. On Windows it starts with no
# console window: the app is a windowed program, and every console child it starts would otherwise open one.
SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}


def kill_group(proc) -> None:
    """Stops a CLI and every process it started; one that has ended already is no error."""
    if proc is None or proc.returncode is not None:
        return
    pid = proc.pid
    # Only a child's own pid is signalled as a group: killpg(0) is this server's own group, and killpg(1) every process
    if isinstance(pid, int) and pid > 1:
        try:
            if sys.platform == "win32":    # the whole tree, as Windows has no process groups to signal
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(pid, signal.SIGKILL)   # its session is its own (SPAWN), so the group is the CLI's
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()                    # and the process itself, if the group was gone already
    except (OSError, ProcessLookupError):
        pass

# What the panel says to run when the agent is not signed in: the launcher's command, or in the desktop app the CLI's
# own sign-in in any terminal (the app's server reads the same login folder).
LOGIN_HINTS = {"claude-code": "./sidenote login", "codex": "./sidenote login codex",
               "anthropic-api": "ANTHROPIC_API_KEY in .env", "mock": ""}
DESKTOP_LOGIN_HINTS = {"claude-code": "claude", "codex": "codex login", "anthropic-api": "ANTHROPIC_API_KEY", "mock": ""}


def login_hint(cfg) -> str:
    return (DESKTOP_LOGIN_HINTS if cfg.desktop else LOGIN_HINTS).get(cfg.agent, "")


def chosen(cfg) -> tuple[str, str]:
    """The model and the effort the agent is asked for, as (model, effort); empty means the agent's own default.

    The panel's choice comes first (agent_model_name, agent_effort, which start from SIDENOTE_AGENT_MODEL and
    SIDENOTE_AGENT_EFFORT). Left empty, a CLI picks for itself, and the Anthropic API agent, which has no default of
    its own to fall back on, takes SIDENOTE_MODEL and SIDENOTE_EFFORT. The panel's agent card shows what this returns."""
    model = SETTINGS.get("agent_model_name") if "agent_model_name" in SETTINGS.defs else cfg.agent_model
    effort = SETTINGS.get("agent_effort") if "agent_effort" in SETTINGS.defs else cfg.agent_effort
    if cfg.agent == "anthropic-api":
        model, effort = model or cfg.model, effort or cfg.effort    # the API needs a model named in every request
    return model or "", effort or ""


def home() -> Path:
    """The home the CLIs keep their logins under (the container mounts the PC's ~/.claude and ~/.codex there)."""
    # HOME in the container (/root) and on Linux and macOS; on a Windows host, where HOME is usually unset, the user's
    # profile folder, which Path.home() reads from USERPROFILE
    return Path(os.environ.get("HOME") or Path.home())


# ----------------------------------------------------------------------------------------------------------------------
# Claude Code (Anthropic), through its CLI and this PC's Claude Code login

def claude_args(cfg, web: bool = False) -> list[str]:
    # The CLI signs in with this PC's Claude Code login (~/.claude), but it is a helper here, not a
    # session of the user's: none of their settings, hooks, plugins, MCP servers, skills or commands
    # are loaded, no tools are offered, and nothing is saved as a resumable session.
    # `web`: the web search alone, for a question about the present (a current version). Without it Claude wrote
    # Bash curl calls out as text and then "Python 3.15.0 (if it came out as planned). Could not check in real time"; with it
    # the same question came back as 3.15.2, the release of that week, in 21 s. Allowed up front
    # (--allowedTools): with --permission-prompts none a tool that asks first is refused.
    args = [
        cfg.agent_bin or "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--permission-prompts", "none",
        "--tools", "WebSearch" if web else "",  # inline image needs no tools; dropping schemas is faster + focused
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
    ]
    # The panel can change these while the server runs (the agent's section of the settings); the environment is
    # what they start from.
    model, effort = chosen(cfg)
    if model:
        args += ["--model", model]
    # A question about the present is a fact to look up, not a problem to think through: at the CLI's own effort the
    # searched answers took 31 to 35 s to their first word, at `low` 17 to 23 s, as right.
    if web:
        args += ["--effort", "low", "--allowedTools", "WebSearch"]
    elif effort:
        args += ["--effort", effort]
    return args


def probe_cli(cfg) -> dict:
    """What Claude Code will really run on, for the panel: {"model", "effort", "thinking", "max_tokens"}, or {} when that cannot be
    learned. Nothing it prints names the effort it uses when none is asked for, so its own first request is read: the CLI is started
    exactly as for an answer (claude_args) with its API address on a listener here, which keeps those four fields of the body, never
    looks at the headers, and answers an error. So nothing leaves this PC and nothing is spent: 0.4 s (measured: medium on
    claude-opus-5-5, where the CLI's settings.json said low, which --setting-sources "" leaves unread)."""
    import http.server
    import subprocess
    import threading
    if cfg.agent != "claude-code":
        return {}
    seen: dict = {}
    got = threading.Event()

    class Listener(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            try:
                sent = json.loads(body)
                seen.update(model=sent.get("model") or "", effort=(sent.get("output_config") or {}).get("effort") or "",
                            thinking=(sent.get("thinking") or {}).get("type") or "", max_tokens=sent.get("max_tokens"))
                got.set()
            except ValueError:
                pass
            self.send_response(400)      # the CLI's retries end sooner on a refusal than on a dropped connection
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"type":"error","error":{"type":"invalid_request_error","message":"probe"}}')

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_):       # nothing of it in the logs
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Listener)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = None
    try:
        with forksafe.native_work():     # every spawn waits for speech being decoded: a fork during that can hang the server (forksafe.py)
            proc = subprocess.Popen(claude_args(cfg), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    **SPAWN,
                                    env={**os.environ, "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}"})
        proc.stdin.write(b'{"type":"user","message":{"role":"user","content":[{"type":"text","text":"probe"}]}}\n')
        proc.stdin.flush()
        got.wait(20)
    except OSError as exc:               # no CLI here: the card says it does not know
        log.debug("no probe of the CLI: %s", exc)
    finally:
        if proc is not None:
            kill_group(proc)
            proc.wait()
        server.shutdown()
        server.server_close()
    return dict(seen)


async def read_claude_turn(stdout, on_delta: OnDelta, timeout: float, budget: float | None = None):
    """Parse one turn from a stream-json stdout: stream text_deltas, stop at `result`.

    Returns (text, usage|None, cost|None, is_error, model). usage is None if the stream ended
    before a result (process died). On an error result the text is the CLI's message
    (e.g. a sign-in problem), so callers raise it instead of showing it as an answer. `model` is
    what the CLI says it ran on, which is the only way to know when it picks for itself."""
    acc: list[str] = []
    used = ""
    end = time.time() + budget if budget else None
    while True:
        # Two limits: this one is for a stream that has gone quiet, the other for a turn that keeps
        # talking and never finishes. One Claude turn ran 923 seconds and 130,000 tokens
        # with the worker and the session lock held the whole time, because only the first was there.
        wait = timeout if end is None else max(1.0, min(timeout, end - time.time()))
        if end is not None and time.time() >= end:
            raise asyncio.TimeoutError(f"the answer did not end within {budget:.0f} s")
        raw = await asyncio.wait_for(stdout.readline(), timeout=wait)
        if not raw:
            return "".join(acc), None, None, True, used  # EOF before result
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        etype = ev.get("type")
        if etype == "system" and isinstance(ev.get("model"), str):
            used = ev["model"]            # the init event names the model this turn runs on
        if etype == "stream_event":
            se = ev.get("event", {})
            if se.get("type") == "message_start":
                m = (se.get("message") or {}).get("model")
                if isinstance(m, str):
                    used = m
                if acc and acc[-1] != "\n\n":   # a message after a web search: the head has to start on its own line
                    acc.append("\n\n")
                    await on_delta("\n\n")
            if se.get("type") == "content_block_delta" and se.get("delta", {}).get("type") == "text_delta":
                txt = se["delta"].get("text", "")
                acc.append(txt)
                await on_delta(txt)
        elif etype == "result":
            u = ev.get("usage", {}) or {}
            usage = {
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0),
            }
            if ev.get("is_error"):
                msg = ev.get("result") if isinstance(ev.get("result"), str) else ""
                return (msg or "".join(acc)).strip(), usage, ev.get("total_cost_usd"), True, used
            return "".join(acc), usage, ev.get("total_cost_usd"), False, used


def claude_error(text: str, code: int | None = None) -> RuntimeError:
    # No result line means the CLI died (a sign-in problem comes back as an error result instead),
    # so this must not read like a login error: that would stop all automatic analysis.
    return RuntimeError(f"claude CLI: {text[:400]}" if text else
                        "claude CLI ended without an answer" + (f" (exit code {code})" if code is not None else ""))


async def claude_auth_status(cfg) -> dict:
    """Is the claude CLI signed in? `claude auth status --json` reads local state only, so a
    wrong or expired token still counts as signed in here; that shows when an analysis fails."""
    try:
        async with forksafe.spawn_guard():
            proc = await asyncio.create_subprocess_exec(
                cfg.agent_bin or "claude", "auth", "status", "--json",
                **SPAWN, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 30)
        finally:
            if proc.returncode is None:   # timed out or cancelled: it would sit there for good,
                kill_group(proc)          # and this runs every 20 s while signed out
        d = json.loads(out or b"{}")
        return {"ok": bool(d.get("loggedIn")), "method": str(d.get("authMethod") or ""), "plan": str(d.get("subscriptionType") or "")}
    except FileNotFoundError as exc:      # no CLI on this PC: the agent is optional, and the panel says how to get it
        return {"ok": False, "method": "", "installed": False, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:
        return {"ok": False, "method": "", "error": f"{type(exc).__name__}: {exc}"}


def claude_message(images, text: str, independent: bool) -> bytes:
    body = in_answer_language(SYSTEM_PROMPT) + "\n\n" + text
    if independent:
        body = INDEPENDENCE_NOTE + body
    msg = {
        "type": "user",
        "message": {
            "role": "user",
            "content": image_blocks(images) + [{"type": "text", "text": body}],
        },
    }
    return (json.dumps(msg) + "\n").encode()


class ClaudeCodeSession:
    """One long-lived `claude -p` process reused across turns (warm cache, no respawn)."""

    sent = 0   # requests written to the CLI (ClaudeCodeAgent.sent); a class default, so every instance starts at 0

    def __init__(self, cfg):
        self.cfg = cfg
        self._proc: asyncio.subprocess.Process | None = None
        self._turns = 0
        # The CLI reports total_cost_usd as a running total for the whole process (measured:
        # 0.039 -> 0.061 -> 0.083 for three identical turns); each turn's cost is the difference.
        self._cost_so_far = 0.0
        self._lock = asyncio.Lock()
        self._retire = False     # retire() was asked while a turn was being written

    async def _start(self) -> None:
        # The guard waits for speech decoding to finish: starting a child forks this whole
        # process, and a fork from inside a native parallel region hung the server for 95
        # minutes (server/forksafe.py).
        async with forksafe.spawn_guard():
            self._proc = await asyncio.create_subprocess_exec(
                *claude_args(self.cfg),
                **SPAWN, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=4 * 1024 * 1024,
            )
        self._turns = 0
        self._cost_so_far = 0.0
        log.info("cli session started (pid=%s)", self._proc.pid)

    def _kill(self) -> None:
        p, self._proc = self._proc, None
        self._turns = 0
        self._cost_so_far = 0.0
        if p and p.returncode is None:
            kill_group(p)

    def retire(self) -> None:
        """End this process for the next turn to start a new one (the model or the effort changed). A turn being
        written finishes first: killed at once, it ended as "claude CLI ended without an answer", and the setting
        promises the change from the next problem on."""
        if self._lock.locked():
            self._retire = True      # run() ends it once the turn in hand is over
        else:
            self._kill()

    async def run(self, images, text: str, on_delta: OnDelta) -> AnalysisResult:
        async with self._lock:
            try:
                return await self._turn(images, text, on_delta)
            finally:
                if self._retire:   # a change asked for while this turn was being written
                    self._retire = False
                    self._kill()

    async def _turn(self, images, text: str, on_delta: OnDelta) -> AnalysisResult:
        if self._proc is None or self._proc.returncode is not None or self._turns >= self.cfg.cli_session_turns:
            self._kill()
            await self._start()
        proc = self._proc
        try:
            proc.stdin.write(claude_message(images, text, independent=True))
            self.sent += 1   # the request is out: from here a cancel still costs it (Pipeline counts it, Spend.cut_short)
            await asyncio.wait_for(proc.stdin.drain(), self.cfg.cli_timeout)   # a CLI that stops reading: a timeout
            out, usage, cost, is_error, used = await read_claude_turn(proc.stdout, on_delta, self.cfg.cli_timeout,
                                                                self.cfg.cli_turn_budget)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            self._kill()
            raise
        except Exception:
            self._kill()
            raise
        # The CLI reports what the whole process has cost so far, so a turn's own cost is the difference from the
        # last one, for a turn that ended in an error as for one that did not: the error's raw total counted every
        # earlier turn of the session again against the hour's ceiling.
        if cost is not None:
            cost, self._cost_so_far = round(max(0.0, cost - self._cost_so_far), 6), cost
        if usage is None or is_error:
            code = proc.returncode
            self._kill()
            # usage None: the stream ended before a result, and `out` is only a partial answer
            exc = claude_error(out if usage is not None else "", code)
            exc.cost_usd = cost        # a turn that ended in an error was still paid for
            raise exc
        self._turns += 1
        return AnalysisResult(text=out, usage=usage, cost_usd=cost,
                              model=used or self.cfg.agent_model or "claude-code")

    async def aclose(self) -> None:
        self._kill()


class ClaudeCodeAgent:
    """Shell out to the local `claude` CLI (Claude Code), reusing its auth. No API key.

    `reset_session()` ends the warm process, so the next problem starts one with whatever model and
    effort are set now (the panel can change both while this runs). An answer being written when it is
    called is finished first, by the old process (ClaudeCodeSession.retire)."""

    name = "claude-code"
    label = "Claude Code"
    region_scale = 100
    _fresh_sent = 0   # requests written by processes of their own, outside the warm session

    def __init__(self, cfg):
        self.cfg = cfg
        self._session = ClaudeCodeSession(cfg) if cfg.cli_session else None

    @property
    def sent(self) -> int:
        """How many requests have gone out, in the warm session and in processes of their own: a turn cancelled before
        its request was written (still waiting for the session or the spawn guard) cost nothing."""
        return self._fresh_sent + (self._session.sent if self._session is not None else 0)

    def reset_session(self) -> None:
        if self._session is not None:
            self._session.retire()

    async def run(self, images, text: str, on_delta: OnDelta, web: bool = False) -> AnalysisResult:
        """`web`: the web search allowed (cli_args), in a process of its own: the warm session was started without
        tools, and the tools a process has are fixed when it starts."""
        if self._session is not None and not web:
            return await self._session.run(images, text, on_delta)
        return await self._fresh(images, text, on_delta, web=web)

    async def analyze(self, image_b64: str | None, transcript: str, on_delta: OnDelta, extra=(),
                      voice: bool = False, followup: dict | None = None) -> AnalysisResult:
        images = [b for b in (image_b64, *extra) if b]
        return await self.run(images, build_user_text(transcript, len(extra), voice, bool(image_b64), followup), on_delta)

    async def _fresh(self, images, text: str, on_delta: OnDelta, web: bool = False) -> AnalysisResult:
        async with forksafe.spawn_guard():   # see _start
            proc = await asyncio.create_subprocess_exec(
                *claude_args(self.cfg, web=web),
                **SPAWN, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=4 * 1024 * 1024,
            )
        try:
            proc.stdin.write(claude_message(images, text, independent=False))
            self._fresh_sent += 1   # out, and paid for from here on
            await asyncio.wait_for(proc.stdin.drain(), self.cfg.cli_timeout)
            proc.stdin.close()
            out, usage, cost, is_error, used = await read_claude_turn(proc.stdout, on_delta, self.cfg.cli_timeout,
                                                                self.cfg.cli_turn_budget)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            kill_group(proc)
            raise
        finally:
            if proc.returncode is None:
                kill_group(proc)
        if usage is None or is_error:
            exc = claude_error(out if usage is not None else "", proc.returncode)
            exc.cost_usd = cost        # an error result is paid for, as the warm session's says
            raise exc
        return AnalysisResult(text=out, usage=usage, cost_usd=cost,
                              model=used or self.cfg.agent_model or "claude-code")

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.aclose()


class AnthropicApiAgent:
    """Anthropic API backend with vision + streaming (needs ANTHROPIC_API_KEY)."""

    name = "anthropic-api"
    label = "Anthropic API"
    region_scale = 100
    sent = 0   # requests sent (Pipeline counts a cancelled one only when it went out); a class default, from 0

    def __init__(self, cfg):
        import anthropic  # lazy: only needed in API mode

        self.cfg = cfg
        # A stream gone quiet waits cli_timeout, not the SDK's 10 minutes, and one retry, not two: with the defaults a
        # stalled stream held the worker for up to half an hour. The whole turn is bounded in run().
        self._client = anthropic.AsyncAnthropic(timeout=anthropic.Timeout(cfg.cli_timeout, connect=10.0), max_retries=1)
        self._resolved: dict[str, str] = {}   # each family name's newest model, looked up once a run

    async def model(self) -> str:
        """The model to ask (chosen(): the panel's choice, else SIDENOTE_MODEL): a full name as written, or for a family
        name (opus, sonnet, haiku) the newest model of that family the API lists, by its release date rather than its
        place in the list, so a new release is used without a change here. Each family is looked up once a run; a
        lookup that fails falls back to the newest of the family the price table knows."""
        want = chosen(self.cfg)[0]
        if want not in ("opus", "sonnet", "haiku"):
            return want
        if want not in self._resolved:
            name = ""
            try:
                page = await self._client.models.list(limit=100)
                found = [m for m in page.data if want in m.id]
                # newest first by release date; models without one keep the list's own order behind those with one
                found.sort(key=lambda m: str(getattr(m, "created_at", "") or ""), reverse=True)
                name = found[0].id if found else ""
            except Exception as exc:
                log.warning("the API's model list is out of reach (%s): the price table's newest %s is used", exc, want)
            if not name:
                from .analyzer import PRICES
                name = next(n for n in PRICES if want in n)
            self._resolved[want] = name
            log.info("Anthropic API: %s is %s", want, name)
        return self._resolved[want]

    def request_options(self) -> dict:
        """The effort part of a request: the chosen effort, or nothing, which leaves the model's own default."""
        effort = chosen(self.cfg)[1]
        return {"output_config": {"effort": effort}} if effort else {}

    # Thinking cannot be turned off on the current models and its tokens count against max_tokens: at a high effort
    # the 8,000 of SIDENOTE_MAX_TOKENS could run out inside the answer. A stream has no request timeout to keep under,
    # so it is given room.
    STREAM_MAX_TOKENS = 64000

    async def run(self, images, text: str, on_delta: OnDelta, web: bool = False) -> AnalysisResult:
        # `web` is the CLI's (ClaudeCodeAgent.run); this one answers from the request as it is
        content = image_blocks(images) + [{"type": "text", "text": text}]
        acc: list[str] = []
        model = await self.model()

        async def turn():
            self.sent += 1   # the request goes out with the stream's opening
            async with self._client.messages.stream(
                model=model,
                max_tokens=max(self.cfg.max_tokens, self.STREAM_MAX_TOKENS),
                system=in_answer_language(SYSTEM_PROMPT),
                messages=[{"role": "user", "content": content}],
                **self.request_options(),            # the panel's effort, when one is chosen
            ) as stream:
                async for chunk in stream.text_stream:
                    acc.append(chunk)
                    await on_delta(chunk)
                return await stream.get_final_message()

        # the same bound on a whole turn as the CLI agents have (cli_turn_budget)
        final = await asyncio.wait_for(turn(), self.cfg.cli_turn_budget) if self.cfg.cli_turn_budget else await turn()

        u = final.usage
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0),
            "output_tokens": getattr(u, "output_tokens", 0),
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        cost = estimate_cost(model, usage)
        out = "".join(acc)
        stop = getattr(final, "stop_reason", None)
        if stop == "refusal":
            # The safety classifiers declined (HTTP 200): an error, so this PC's model answers and the brake's row of
            # empty answers is not grown by it; paid for all the same
            details = getattr(final, "stop_details", None)
            exc = RuntimeError(f"Anthropic API: the request was declined ({getattr(details, 'category', None) or 'refusal'})")
            exc.cost_usd = cost
            raise exc
        if stop == "max_tokens":
            log.warning("Anthropic API: the answer reached max_tokens (%d output tokens) and was cut",
                        usage["output_tokens"])
            out += "\n\n" + t("(cut at the length limit)")
        return AnalysisResult(text=out, usage=usage, cost_usd=cost, model=model)

    async def analyze(self, image_b64: str | None, transcript: str, on_delta: OnDelta, extra=(),
                      voice: bool = False, followup: dict | None = None) -> AnalysisResult:
        images = [b for b in (image_b64, *extra) if b]
        return await self.run(images, build_user_text(transcript, len(extra), voice, bool(image_b64), followup), on_delta)

    async def aclose(self) -> None:
        pass


# ----------------------------------------------------------------------------------------------------------------------
# Codex (OpenAI), through its CLI and this PC's Codex login

def codex_args(cfg, workdir: str, pictures: list, web: bool = False) -> list[str]:
    """`codex exec` for one answer: its events as JSON lines on stdout, the request on stdin, the pictures as files.

    As with Claude Code it is a helper, not the user's session: their config and rules are not loaded (the login still
    comes from CODEX_HOME), nothing is kept as a session, and the sandbox is read-only with no approval asked, so a
    shell command it tried could change nothing and would not wait for anyone. `web` is not passed on: exec takes no
    search switch, and a question about the present is answered from what the model knows."""
    args = [cfg.agent_bin or "codex", "exec",
            "--json",                          # every event as one JSON line, the answer's text among them
            "--ephemeral",                     # no session files kept
            "--skip-git-repo-check",           # its working folder is an empty temporary one
            "--ignore-user-config",            # the user's own ~/.codex/config.toml is theirs, not this helper's
            "--ignore-rules",                  # nor their execpolicy rules
            "--sandbox", "read-only",          # nothing it might run can write anywhere
            "--color", "never",
            "--cd", workdir,
            "-c", 'approval_policy="never"']   # never stop to ask: there is nobody to answer
    model, effort = chosen(cfg)                # the panel's choice, else Codex's own
    if model:
        args += ["--model", model]
    if effort:
        args += ["-c", f'model_reasoning_effort="{effort}"']
    for path in pictures:
        args += ["--image", str(path)]        # in order: the screen or crop first, then page tiles
    args.append("-")                          # the request itself comes on stdin
    return args


def codex_usage(u: dict) -> dict:
    """turn.completed's usage in the shape every engine reports (AnalysisResult.usage): OpenAI counts the cached part
    of the input inside input_tokens, so the two are taken apart here."""
    cached = int(u.get("cached_input_tokens") or 0)
    return {"input_tokens": max(0, int(u.get("input_tokens") or 0) - cached),
            "output_tokens": int(u.get("output_tokens") or 0),
            "cache_read": cached,
            "cache_write": 0,
            "reasoning_tokens": int(u.get("reasoning_output_tokens") or 0)}


async def read_codex_turn(stdout, on_delta: OnDelta, timeout: float, budget: float | None = None):
    """One `codex exec --json` run: each agent message passed on as it grows, the usage at its end.

    Returns (text, usage | None, error). usage is None when the run ended without turn.completed: the process died,
    or the turn failed, in which case `error` is what it said. A message is passed on whether the CLI sends it whole
    when it is done (item.completed) or growing as it is written (item.updated): only what is new is sent each time.
    A second message starts on a paragraph of its own."""
    shown: dict[str, str] = {}                 # each agent message by item id, as far as it was passed on
    order: list[str] = []                      # the messages in the order they started
    error = ""
    end = time.time() + budget if budget else None

    def text() -> str:
        return "\n\n".join(shown[k] for k in order)

    while True:
        # the same two limits as Claude Code's (read_claude_turn): a stream gone quiet, and a turn that never ends
        if end is not None and time.time() >= end:
            raise asyncio.TimeoutError(f"the answer did not end within {budget:.0f} s")
        wait = timeout if end is None else max(1.0, min(timeout, end - time.time()))
        raw = await asyncio.wait_for(stdout.readline(), timeout=wait)
        if not raw:
            return text(), None, error         # EOF before turn.completed
        try:
            ev = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue                           # a line that is not an event (a warning) is not the answer
        kind = ev.get("type") if isinstance(ev, dict) else None
        if isinstance(kind, str) and kind.startswith("item."):
            item = ev.get("item") or {}
            if item.get("type") not in ("agent_message", "assistant_message"):
                continue                       # reasoning, a command, a search: not the answer
            key = str(item.get("id") or len(order))
            if key not in shown:
                if order:
                    await on_delta("\n\n")     # a new message under the one before
                order.append(key)
                shown[key] = ""
            new = str(item.get("text") or "")
            old = shown[key]
            if new.startswith(old) and len(new) > len(old):
                await on_delta(new[len(old):])  # only what came since
                shown[key] = new
            elif new and not new.startswith(old):
                shown[key] = new               # rewritten: kept for the result, the panel has the start already
        elif kind == "turn.completed":
            return text(), codex_usage(ev.get("usage") or {}), ""
        elif kind == "turn.failed":
            err = ev.get("error")
            return text(), None, str((err or {}).get("message") if isinstance(err, dict) else err or "the turn failed")
        elif kind == "error":
            error = str(ev.get("message") or ev.get("error") or "")   # a turn.failed may follow


async def _drain(stream, keep: int = 8192) -> bytes:
    """All of a child's stderr, its last `keep` bytes kept: read alongside stdout, so a chatty stderr never fills its
    pipe and stops the child."""
    buf = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return buf
        buf = (buf + chunk)[-keep:]


def write_pictures(images, folder: str) -> list[Path]:
    """The base64 pictures as PNG files in `folder`, in order (Codex takes pictures as files)."""
    paths = []
    for i, b64 in enumerate(b for b in images if b):
        path = Path(folder) / f"picture-{i + 1}.png"
        path.write_bytes(base64.b64decode(b64))
        paths.append(path)
    return paths


class CodexAgent:
    """Shell out to the `codex` CLI (OpenAI Codex), reusing this PC's Codex login. No API key.

    One process per answer: `codex exec` answers one request and ends, so there is no warm session to keep. The
    pictures go to a temporary folder of the run's own, which is removed when it ends."""

    # Signed in with ChatGPT its turns come with no price (cost_usd None): a plan, not a bill, so the hourly ceiling and
    # the cost of a turn cut short do not apply (pipeline.Spend.priced). Signed in with an API key every turn is billed
    # and the CLI still says no price, so it is worked out from the tokens at USD_PER_MTOK. Set by auth_status.
    reports_cost = False
    # (input, cached input, output) per million tokens: GPT-5.3-Codex on OpenAI's list. A ceiling's figure,
    # not a bill: the model is the CLI's choice, and it may be another.
    USD_PER_MTOK = (1.75, 0.175, 14.0)

    name = "codex"
    label = "Codex"
    region_scale = 100
    sent = 0   # requests written to the CLI (Pipeline counts a cancelled one only when it went out); a class default

    def __init__(self, cfg):
        self.cfg = cfg

    def reset_session(self) -> None:
        """Nothing to end: every answer starts its own process with the model and effort set at that moment."""

    async def run(self, images, text: str, on_delta: OnDelta, web: bool = False) -> AnalysisResult:
        with tempfile.TemporaryDirectory(prefix="sidenote-codex-") as work:
            pictures = write_pictures(images, work)
            async with forksafe.spawn_guard():   # a fork while speech is decoded can hang the server (forksafe.py)
                proc = await asyncio.create_subprocess_exec(
                    *codex_args(self.cfg, work, pictures, web),
                    **SPAWN, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    limit=4 * 1024 * 1024)
            errs = asyncio.create_task(_drain(proc.stderr))
            try:
                proc.stdin.write((in_answer_language(SYSTEM_PROMPT) + "\n\n" + text).encode())
                self.sent += 1   # out, and paid for from here on
                await asyncio.wait_for(proc.stdin.drain(), self.cfg.cli_timeout)
                proc.stdin.close()
                # Codex 0.165 sends its answer whole when it is done (one item.completed, no item.updated), and
                # nothing at all while it thinks: a stream "quiet" for cli_timeout is one still working, so only the
                # turn's own budget bounds it (a long high-effort answer was thrown away at 120 s)
                quiet = max(self.cfg.cli_timeout, self.cfg.cli_turn_budget or 0)
                out, usage, error = await read_codex_turn(proc.stdout, on_delta, quiet, self.cfg.cli_turn_budget)
                try:
                    await asyncio.wait_for(proc.wait(), 10)
                except asyncio.TimeoutError:
                    # the answer is in hand: a process slow to end is killed below, and the answer is not lost to it
                    if usage is None and not error:   # a failed turn's own words (a limit) are what counts
                        raise
                    log.info("codex CLI: the turn is over but the process has not ended in 10 s; it is stopped")
            finally:
                if proc.returncode is None:      # cancelled, timed out or failed: it must not go on in the background
                    kill_group(proc)             # nor the native binary npm's wrapper started
                stderr = await errs if errs.done() else b""
                if not errs.done():
                    errs.cancel()
        if usage is None:
            lines = stderr.decode("utf-8", "replace").strip().splitlines()
            said = error or (lines[-1] if lines else "")       # its own words, else the last line it wrote to stderr
            raise RuntimeError(f"codex CLI: {said[:400]}" if said else
                               "codex CLI ended without an answer" +
                               (f" (exit code {proc.returncode})" if proc.returncode is not None else ""))
        model = chosen(self.cfg)[0]
        cost = None
        if self.reports_cost:
            rate_in, rate_cached, rate_out = self.USD_PER_MTOK
            cost = (usage["input_tokens"] * rate_in + usage["cache_read"] * rate_cached
                    + usage["output_tokens"] * rate_out) / 1_000_000
        return AnalysisResult(text=out, usage=usage, cost_usd=cost, model=model or "codex")

    async def analyze(self, image_b64: str | None, transcript: str, on_delta: OnDelta, extra=(),
                      voice: bool = False, followup: dict | None = None) -> AnalysisResult:
        images = [b for b in (image_b64, *extra) if b]
        return await self.run(images, build_user_text(transcript, len(extra), voice, bool(image_b64), followup), on_delta)

    async def auth_status(self) -> dict:
        st = await codex_auth_status(self.cfg)
        self.reports_cost = st.get("method") == "api-key"
        return st

    async def aclose(self) -> None:
        pass


async def codex_auth_status(cfg) -> dict:
    """Is the codex CLI signed in? `codex login status` reads its local state: 0 and "Logged in ..." when it is, 1 and
    "Not logged in" when it is not. Like Claude Code's check, an expired token still counts as signed in here; that
    shows when an answer fails."""
    try:
        async with forksafe.spawn_guard():
            proc = await asyncio.create_subprocess_exec(
                cfg.agent_bin or "codex", "login", "status",
                **SPAWN, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 30)
        finally:
            if proc.returncode is None:   # timed out or cancelled: it would sit there for good
                kill_group(proc)
        said = (out or b"").decode("utf-8", "replace")
        method = "chatgpt" if "ChatGPT" in said else "api-key" if "API key" in said else ""
        return {"ok": proc.returncode == 0 and "Not logged in" not in said, "method": method}
    except FileNotFoundError as exc:      # no CLI on this PC, as for Claude Code above
        return {"ok": False, "method": "", "installed": False, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:
        return {"ok": False, "method": "", "error": f"{type(exc).__name__}: {exc}"}


# ----------------------------------------------------------------------------------------------------------------------
# Choosing one

# The file each CLI keeps its login in: a change to it is a new sign-in, which the server looks at again
# (app.engine_watch) without a restart.
LOGIN_FILES = {"claude-code": (".claude", ".credentials.json"), "codex": (".codex", "auth.json")}


def login_file(provider: str) -> Path | None:
    """Where `provider` keeps its login on this PC, or None for one that has no file (an API key, the mock)."""
    parts = LOGIN_FILES.get(provider)
    return home().joinpath(*parts) if parts else None


_ACCOUNT_FILE = "/data/logs/.account.json"   # what ./sidenote up copies out of ~/.claude.json: that file is not mounted here
# The PC's Claude Code keeps a copy of ~/.claude.json in ~/.claude/backups each time it writes that file, every minute or two while it
# is used, and compose.yaml mounts that folder here read-only. Its newest copy says who is signed in now: the copy ./sidenote up made
# still named the account of the last start after a sign-in as another account. A folder, not the file: Claude Code
# replaces ~/.claude.json rather than writing into it, and a file mounted on its own would have stayed the old one.
_BACKUPS = os.environ.get("SIDENOTE_CLAUDE_BACKUPS", "/host/claude-backups")


def _backups_dir() -> str:
    """Claude Code's copies of its config: mounted at _BACKUPS in the container, or the PC's own folder on a host install
    (the desktop app), where nothing is mounted and the account and the plan meters had nothing to read."""
    if os.path.isdir(_BACKUPS) or "SIDENOTE_CLAUDE_BACKUPS" in os.environ:
        return _BACKUPS
    return str(home() / ".claude" / "backups")
_newest: dict = {"name": None, "email": None}


def _signed_in_email() -> str | None:
    """The address in the newest of Claude Code's own copies of its config; "" when that copy names no account (signed out); None where
    there is no copy to read."""
    try:
        names = [n for n in os.listdir(_backups_dir()) if n.startswith(".claude.json.backup.")]
    except OSError:
        return None
    if not names:
        return None
    newest = max(names, key=lambda n: int(n.rsplit(".", 1)[-1]) if n.rsplit(".", 1)[-1].isdigit() else 0)
    if newest != _newest["name"]:
        try:
            with open(os.path.join(_backups_dir(), newest), encoding="utf-8") as f:
                email = (json.load(f).get("oauthAccount") or {}).get("emailAddress")
        except (OSError, ValueError):
            return _newest["email"]
        _newest.update(name=newest, email=email if isinstance(email, str) and email else "")
    return _newest["email"]


def _claude_plan() -> str | None:
    """The plan of the login Claude Code holds now, from that login itself: "Max 20x", "Pro". The name `claude auth status` gave at the
    last check stood as "Pro" after a sign-in with another account on Max."""
    try:
        with open(login_file("claude-code"), encoding="utf-8") as f:
            oauth = json.load(f).get("claudeAiOauth") or {}
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    kind, tier = str(oauth.get("subscriptionType") or ""), str(oauth.get("rateLimitTier") or "")
    times = re.search(r"max_(\d+)x", tier)
    if kind == "max" and times:
        return f"Max {times.group(1)}x"
    return kind.capitalize() or None


# What is left of the plan's limits, as Claude Code's own /usage shows it, so the panel can show how much usage remains.
# The address the CLI asks, with the login the CLI keeps: read here and never written (the CLI refreshes it), never logged,
# never sent anywhere else. SIDENOTE_USAGE_URL is for the tests' stand-in.
USAGE_URL = os.environ.get("SIDENOTE_USAGE_URL", "https://api.anthropic.com/api/oauth/usage")


def _when(text) -> float | None:
    """An ISO 8601 time with its zone, as the usage address writes it, in epoch seconds; None for anything else. Python 3.10 reads
    only six figures of a second and no "Z", so both are put right first."""
    if not isinstance(text, str) or not text:
        return None
    text = text.replace("Z", "+00:00")
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def plan_usage(body: dict) -> dict:
    """The usage address's answer as the panel shows it: the share of the five-hour session and of the week used, each with when it
    starts again, and a week of one model the plan counts on its own while it is in use. A window not running is None: none of it used."""
    def window(w):
        if not isinstance(w, dict) or not isinstance(w.get("utilization"), (int, float)):
            return None
        return {"used": round(min(100.0, max(0.0, float(w["utilization"]))), 1), "resets": _when(w.get("resets_at"))}
    models = []
    for lim in body.get("limits") or []:
        if not isinstance(lim, dict) or lim.get("kind") != "weekly_scoped" or not isinstance(lim.get("percent"), (int, float)):
            continue
        name = ((lim.get("scope") or {}).get("model") or {}).get("display_name")
        if isinstance(name, str) and name and (lim.get("is_active") or lim["percent"] > 0):
            models.append({"name": name[:24], "used": round(min(100.0, max(0.0, float(lim["percent"]))), 1), "resets": _when(lim.get("resets_at"))})
    return {"session": window(body.get("five_hour")), "week": window(body.get("seven_day")), "models": models[:2]}


def read_plan_usage() -> dict | None:
    """Claude Code's plan usage now, or None: no login, a token run out that the CLI has not refreshed yet, no network. Blocking (a thread)."""
    path = login_file("claude-code")
    try:
        with open(path, encoding="utf-8") as f:
            oauth = json.load(f).get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        if not isinstance(token, str) or not token or (oauth.get("expiresAt") or 0) / 1000 < time.time() + 30:
            return None
        req = urllib.request.Request(USAGE_URL, headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20",
                                                         "User-Agent": "sidenote"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return {**plan_usage(json.load(r)), "at": round(time.time())}
    except Exception:   # anything at all: the card shows nothing rather than an error, and nothing of the login reaches a log
        return None


def account(provider: str) -> dict:
    """Who the agent is signed in as, for the panel: {"email", "plan"}, each only if known. Read from the login's own
    files, never logged. Every failure is just nothing to show."""
    try:
        if provider == "claude-code":
            live = _signed_in_email()
            if live:
                plan = _claude_plan()
                return {"email": live, **({"plan": plan} if plan else {})}
            if live == "":   # the newest copy names no account: signed out, and the name ./sidenote up wrote is not who is signed in
                return {}
            if os.path.exists(_ACCOUNT_FILE):
                with open(_ACCOUNT_FILE, encoding="utf-8") as f:
                    return {k: v for k, v in json.load(f).items() if k in ("email", "plan") and v and isinstance(v, str)}
            # a host install has no copy made by ./sidenote up: the PC's own config names the account
            with open(home() / ".claude.json", encoding="utf-8") as f:
                email = (json.load(f).get("oauthAccount") or {}).get("emailAddress")
            plan = _claude_plan()
            return {k: v for k, v in {"email": email, "plan": plan}.items() if v and isinstance(v, str)}
        if provider == "codex":
            with open(os.path.expanduser("~/.codex/auth.json"), encoding="utf-8") as f:
                token = (json.load(f).get("tokens") or {}).get("id_token") or ""
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            plan = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type")
            return {k: v for k, v in {"email": claims.get("email"), "plan": plan}.items() if v}
        if provider == "anthropic-api":
            return {"plan": "API"}
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return {}


async def auth_status(cfg, agent) -> dict:
    """Whether the agent in use can answer: signed in (a CLI), or a key set (an API)."""
    if agent is None:
        return {"ok": False, "method": "", "off": True}
    if cfg.agent == "mock":
        return {"ok": True, "method": "mock"}
    if cfg.agent == "anthropic-api":
        return {"ok": bool(os.environ.get("ANTHROPIC_API_KEY")), "method": "api-key"}
    if cfg.agent == "codex":
        return await agent.auth_status() if hasattr(agent, "auth_status") else await codex_auth_status(cfg)
    return await claude_auth_status(cfg)


def make_agent(cfg):
    """The cloud agent SIDENOTE_AGENT names, or None when it is off."""
    if cfg.agent == "claude-code":
        return ClaudeCodeAgent(cfg)
    if cfg.agent == "codex":
        return CodexAgent(cfg)
    if cfg.agent == "anthropic-api":
        return AnthropicApiAgent(cfg)
    if cfg.agent == "mock":
        from .analyzer import MockAnalyzer
        return MockAnalyzer()
    return None
