"""The server and the capture program through what real use has done to them: restarts in the middle of a problem, a reading mistaken for a busy GPU, a plan's limit outliving a new
sign-in, and a tray menu whose program has gone.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/server_scenarios.py

In mock mode: no GPU, no network, no agent login. Each of these came from the logs of real use, and fails on 999ddc8.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

LOGS = tempfile.mkdtemp(prefix="sidenote-scenarios-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_LOG_DIR=LOGS, SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK, BAD = [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {str(got)[:300]}" if got != "" and not cond else ""), flush=True)


import numpy as np  # noqa: E402

from server import agents, forksafe, pipeline, repeats, telemetry  # noqa: E402
from server.detector import make_detector  # noqa: E402

# ---------------------------------------------------------------- what the server remembers over a restart
print("[a restart]")
pic, ctx = np.full((40, 60), 120, np.uint8), np.full((60, 90), 130, np.uint8)
path = Path(LOGS) / ".restart.npz"
rec = repeats.Recent()
rec.items.append(repeats.Seen(101, pic, ctx, time.time() - 60))
rec.items.append(repeats.Seen(102, pic + 1, ctx + 1, time.time() - 10))
rec.add_words(103, "버섯을 번호 순서대로 골라 먹을 때")
rec.save(path, {"at": time.time(), "sig": "abc"})
check("what is remembered is written whole", path.exists() and not Path(f"{path}.tmp.npz").exists())
again = repeats.Recent()
extra = again.load(path)
check("the next start takes it up", [s.card for s in again.items] == [101, 102] and again.words[0][0] == 103 and extra.get("sig") == "abc", (again.items, extra))
check("...its pictures as they were", np.array_equal(again.items[0].picture, pic) and np.array_equal(again.items[1].context, ctx + 1))
check("...and the file goes: it holds pieces of a screen", not path.exists())
check("no file is no memory, and no failure", repeats.Recent().load(path) == {})
path.write_bytes(b"not an archive")
none = repeats.Recent()
check("a broken file is no memory either", none.load(path) == {} and not none.items and not path.exists())
old = repeats.Recent(ttl=30)
old.items.append(repeats.Seen(104, pic, ctx, time.time() - 10))
old.save(path)
late = repeats.Recent(ttl=5)
late.load(path)
check("what has outlived its time stays forgotten", not late.items, late.items)
rec2 = repeats.Recent()
rec2.items.append(repeats.Seen(105, pic, ctx, time.time()))
rec2.forget()
rec2.save(path)
check("what was forgotten (the screen switched off) is not brought back", not repeats.Recent().load(path) and not repeats.Recent().items)

from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
# A screen change stops a young analysis, not one in its long pass (in the logs, of 16 stopped after 30 s or more, 9 were followed by
# screens with nothing to solve); the whole of a scrolled problem always does, and a streak of stops lets the next one finish
check("a screen change stops an analysis a few seconds in", A.supersede_now(False, True, 0, 3.0))
check("...not one in its long pass", not A.supersede_now(False, True, 0, A.CONFIG.supersede_keep_sec + 1))
check("...the whole of a scrolled problem stops even a long one", A.supersede_now(True, False, 0, 90.0))
check("...a screen that keeps changing stops none after the streak", not A.supersede_now(False, True, A.CONFIG.supersede_limit, 1.0))
check("...and nothing that has not moved stops anything", not A.supersede_now(False, False, 0, 1.0))
check("the loop asks it and says when it let one finish", "supersede_now(stitched, moved_on" in (ROOT / "server" / "app.py").read_text(encoding="utf-8")
      and '"analysis_kept"' in (ROOT / "server" / "app.py").read_text(encoding="utf-8"))
# The wait on Send is no work of the analysis: a prompt left alone while the screen moved on gave way to the new screen before
# supersede_keep_sec, and must still (the age once counted from the start, the wait included)
_now = time.time()
A.STATE.confirm_open, A.STATE.confirm_held = {41: _now - 30}, {}
check("an analysis waiting for Send counts as new, however long it has waited", A.analysis_age(41, _now - 60) == 0.0)
A.STATE.confirm_open, A.STATE.confirm_held = {}, {41: 50.0}
_age = A.analysis_age(41, _now - 60)
check("...and once sent, its age leaves out the wait", 9.0 <= _age <= 11.0 and A.supersede_now(False, True, 0, _age), _age)
check("...while one that worked as long is let finish", not A.supersede_now(False, True, 0, A.analysis_age(42, _now - 60)))
A.STATE.confirm_open, A.STATE.confirm_held = {}, {}
check("the loop weighs that age, and counts as kept only what the streak limit would not have kept anyway",
      "age = analysis_age(STATE.screen_seq, STATE.last_analyze_ts)" in (ROOT / "server" / "app.py").read_text(encoding="utf-8")
      and "STATE.supersede_streak < CONFIG.supersede_limit\n                    and STATE.kept_said" in (ROOT / "server" / "app.py").read_text(encoding="utf-8"))


class Frame(types.SimpleNamespace):
    pass


sig_now, sig_other = bytes(range(64)) * 2, bytes(reversed(range(64))) * 2
with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    det = A.app.state.detector
    det.last_sig = sig_now
    A.PIPELINE.recent.items.append(repeats.Seen(201, pic, ctx, time.time()))
kept = Path(LOGS) / ".restart.npz"
check("closing down keeps what a restart must not lose", kept.exists())
with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    det = A.app.state.detector
    check("starting again knows the screen it last looked at", det.last_sig == sig_now, det.last_sig and det.last_sig[:8])
    check("...and the problem answered", any(s.card == 201 for s in A.PIPELINE.recent.items))
    check("...an unchanged screen is not new, a changed one is", det.is_new(Frame(sig=sig_now, extra_sig=None)) is False or det.mode != "signature")
    check("...and the file is gone", not kept.exists())
    A.PIPELINE.recent.items.clear()
    det.last_sig = None
# Older than a restart's worth: no screen to go by, the first frame is looked at as ever
rec3 = repeats.Recent()
rec3.save(kept, {"at": time.time() - A.RESTART_KEEP_SEC - 5, "sig": "QUJD"})
with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    check("a screen kept too long ago is not trusted", A.app.state.detector.last_sig is None, A.app.state.detector.last_sig)
    A.PIPELINE.recent.items.clear()
for f in (kept,):
    try:
        f.unlink()
    except OSError:
        pass

# ---------------------------------------------------------------- a new sign-in, and the rest on a limit
print("[a plan's limit]")
sp = pipeline.Spend(A.CONFIG)
sp.load(Path(LOGS) / ".spend-test.json")
sp.limited("claude CLI: You've hit your weekly limit · resets in 30 hours")
check("the limit rests the agent", sp.limit_left() != "")
fresh = pipeline.Spend(A.CONFIG)
fresh.load(Path(LOGS) / ".spend-test.json")
check("...over a restart too", fresh.limit_left() != "")
fresh.signed_in()
check("a new sign-in ends the rest", fresh.limit_left() == "")
third = pipeline.Spend(A.CONFIG)
third.load(Path(LOGS) / ".spend-test.json")
check("...for good", third.limit_left() == "")
third.signed_in()
check("a sign-in with no rest on changes nothing", third.limit_left() == "" and third.limit_until == 0.0)
src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
check("the engine watch calls it when the login file changes", re.search(r"now != seen and PIPELINE is not None:.*\n\s+PIPELINE\.spend\.signed_in\(\)", src) is not None)

# ---------------------------------------------------------------- a reading is no measure of the GPU
print("[a busy GPU]")
from server import analyzer  # noqa: E402

local = analyzer.LocalLLM(A.CONFIG) if hasattr(analyzer, "LocalLLM") else next(v(A.CONFIG) for k, v in vars(analyzer).items() if isinstance(v, type) and hasattr(v, "_pace") and hasattr(v, "_plain"))
paced = []
local._pace = lambda model, tokens, seconds: paced.append((model, tokens, seconds))


class Stream:
    status_code = 200
    def __init__(self, lines): self.lines = lines
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def aiter_lines(self):
        for line in self.lines:
            await asyncio.sleep(0)
            yield line
    async def aread(self): return b""


def sse():
    chunk = lambda text: "data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]})   # noqa: E731
    return [chunk("hello "), chunk("world"), "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 12}}), "data: [DONE]"]


class Client:
    def stream(self, *a, **k): return Stream(sse())
    async def aclose(self): pass


async def gpu_case():
    local._client = Client()

    async def drop(_):
        pass
    await local._stream(local._body([{"role": "user", "content": "x"}], False, None), drop)
    answered = list(paced)
    paced.clear()
    await local._plain("읽기", (), "옮겨 적으세요", 100)
    return answered, list(paced)


try:
    answered, read = asyncio.run(gpu_case())
    check("an answer's generation is measured", len(answered) == 1, answered)
    check("a reading's is not: it once mistook the GPU for busy and swapped the model twice", read == [], read)
except Exception as exc:   # the fake's shape against the real client's: said, rather than passed
    check(f"the stream ran against the stand-in ({type(exc).__name__}: {exc})", False)

# ---------------------------------------------------------------- spawning the agent's CLI for its card
print("[probing the CLI]")
held = []


class Proc:
    stdin = types.SimpleNamespace(write=lambda *_: None, flush=lambda: None)
    def kill(self): pass
    def wait(self): pass


def fake_popen(*a, **k):
    held.append(forksafe.native_work().locked())
    return Proc()


real, orig_event, orig_agent = subprocess.Popen, threading.Event, A.CONFIG.agent
subprocess.Popen = fake_popen


class Quick(orig_event):                 # no request comes to the listener: its wait ends at once, not after 20 s
    def wait(self, timeout=None):
        return super().wait(0.01)


threading.Event = Quick
A.CONFIG.agent = "claude-code"           # the probe is for that agent alone
try:
    agents.probe_cli(A.CONFIG)
finally:
    subprocess.Popen, threading.Event, A.CONFIG.agent = real, orig_event, orig_agent
check("a spawn for the probe waits out speech being decoded, as every other spawn does", held == [True], held)


async def late_probe():
    answers = {"first": {"model": "old"}, "second": {"model": "new"}}
    gates = {"first": threading.Event(), "second": threading.Event()}
    order = iter(("first", "second"))

    def probe(_):
        name = next(order)
        gates[name].wait(2)
        return answers[name]
    was = agents.probe_cli, A.CONFIG.analyzer
    agents.probe_cli = probe
    A.CONFIG.analyzer = "local"
    try:
        one = asyncio.create_task(A.learn_agent_cli())
        await asyncio.sleep(0.05)
        two = asyncio.create_task(A.learn_agent_cli())
        await asyncio.sleep(0.05)
        gates["second"].set()
        await two
        gates["first"].set()
        await one
        return dict(A.STATE.agent_cli)
    finally:
        agents.probe_cli, A.CONFIG.analyzer = was


check("a late answer about the old choice does not overwrite the new one", asyncio.run(late_probe()).get("model") == "new")

# ---------------------------------------------------------------- what is said on the panel about speed
print("[the averages]")
telemetry._recent.clear()
telemetry.event("analysis_done", id=1, type="short", engine="local", elapsed=10.0, first_token=2.0, tokens_out=800)
check("this PC's model: tokens over the time after the first", abs(telemetry.totals()["tps_avg"] - 100.0) < .01, telemetry.totals()["tps_avg"])
telemetry._recent.clear()
telemetry.event("analysis_done", id=2, type="short", engine="agent", elapsed=37.0, first_token=18.0, tokens_out=2980)
check("the agent, which thinks before it shows a word: over the whole answer (it came to 155 tokens/s)", abs(telemetry.totals()["tps_avg"] - 80.5) < .1, telemetry.totals()["tps_avg"])
telemetry._recent.clear()
telemetry.event("analysis_done", id=3, type="short", engine="local", elapsed=2.0, first_token=2.0, tokens_out=5)
check("no time after the first token gives no figure rather than a wild one", telemetry.totals()["tps_avg"] is None, telemetry.totals()["tps_avg"])
telemetry._recent.clear()

telemetry._today.clear()
telemetry.event("analysis_done", id=11, type="short", engine="local", elapsed=10.0, first_token=2.0, tokens_in=100, tokens_out=800)
telemetry.event("analysis_done", id=12, type="short", engine="local", elapsed=20.0, first_token=4.0, tokens_in=100, tokens_out=1600)
telemetry.event("analysis_done", id=13, type="none", engine="local", elapsed=1.0, first_token=.5, tokens_in=50, tokens_out=3)
telemetry.event("analysis_done", id=14, type="essay", engine="agent", elapsed=40.0, first_token=20.0, tokens_in=9000, tokens_out=2000, cost_usd=.12)
telemetry.event("verify_done", id=15, tokens_in=1000, tokens_out=100, cost_usd=.01)
telemetry.event("analysis_error", id=16, engine="agent", hint="timeout", error="x")
day = telemetry.totals()["engines"]
check("this PC's model and the agent are told apart", day["local"]["answers"] == 2 and day["agent"]["answers"] == 1, day)
check("...a look that found nothing is no answer of either", day["local"]["tokens_out"] == 2400, day["local"])
check("...each with its own speed", abs(day["local"]["tps_avg"] - 100.0) < .01 and abs(day["agent"]["tps_avg"] - 50.0) < .01, (day["local"]["tps_avg"], day["agent"]["tps_avg"]))
check("...its own TTFT", day["local"]["first_token_avg"] == 3.0 and day["agent"]["first_token_avg"] == 20.0, day)
check("...and its own cost, what the agent's check of a local answer cost included", day["agent"]["cost_usd"] == .13 and day["local"]["cost_usd"] == 0, day)
check("an error counts on the engine it happened on", day["agent"]["errors"] == 1 and day["local"]["errors"] == 0, day)
check("each answer is there to draw, with its parts", [r["elapsed"] for r in day["local"]["recent"]] == [10.0, 20.0] and day["local"]["recent"][0]["first_token"] == 2.0 and day["local"]["recent"][0]["tps"] == 100.0, day["local"]["recent"])
events = Path(LOGS) / "today-events.jsonl"
now = time.time()
events.write_text("not json\n" + "\n".join(json.dumps(r) for r in (
    {"ts": now - 86400 * 2, "event": "analysis_done", "type": "short", "engine": "local", "elapsed": 9.0, "first_token": 1.0, "tokens_out": 90},
    {"ts": now - 5, "event": "analysis_done", "type": "short", "engine": "local", "elapsed": 9.0, "first_token": 1.0, "tokens_out": 800},
    {"ts": now - 4, "event": "analysis_done", "type": "none", "engine": "local", "elapsed": 1.0, "first_token": 1.0, "tokens_out": 3},
    {"ts": now - 3, "event": "followup_done", "engine": "agent", "elapsed": 5.0, "first_token": 2.0, "tokens_out": 100},
    {"ts": now - 2, "event": "capture_connect"})) + "\n")
telemetry.take_up_today(events)
day = telemetry.engines_today()
midnight_passed = time.localtime(now - 5).tm_mday != time.localtime(now).tm_mday
if not midnight_passed:
    check("a restart reads the last 24 hours' answers back from the log, and no older ones", day["local"]["answers"] == 1 and day["agent"]["answers"] == 1 and day["local"]["tokens_out"] == 800, day)
# A log that rotated this morning: the start of the day is in the file before it
rotated = Path(f"{events}.1")
rotated.write_text(json.dumps({"ts": now - 6, "event": "analysis_done", "type": "short", "engine": "local", "elapsed": 9.0, "first_token": 1.0, "tokens_out": 50}) + "\n")
telemetry.take_up_today(events)
if not midnight_passed:
    check("...and from the file before it, when the log rotated today", telemetry.engines_today()["local"]["answers"] == 2, telemetry.engines_today()["local"]["answers"])
rotated.unlink()
telemetry.take_up_today(Path(LOGS) / "no-such-file")
check("no log is no failure, and leaves what it has", isinstance(telemetry.engines_today(), dict))
telemetry.take_up_today(events)
later = telemetry.engines_today(now + 86400 * 2)["local"]
check("two days on, with none in the last day, the card shows the last answers it gave, said as such", later["answers"] >= 1 and later["window"] == "recent", later)
check("...and within the day they are the day's", telemetry.engines_today()["local"]["window"] == "24h")
telemetry._today.clear()
telemetry._note_today({"ts": now - 20 * 3600, "event": "analysis_done", "type": "short", "engine": "local", "elapsed": 9.0, "first_token": 1.0, "tokens_out": 50})
check("an answer of twenty hours ago still counts: the cards do not stand empty from midnight", telemetry.engines_today()["local"]["answers"] == 1)
telemetry._today.clear()
# Who is signed in, read from the newest of Claude Code's own copies of its config: a sign-in as another account shows within seconds
from server import agents  # noqa: E402
backups = Path(LOGS) / "claude-backups"
backups.mkdir(exist_ok=True)
(backups / ".claude.json.backup.1000").write_text(json.dumps({"oauthAccount": {"emailAddress": "old@example.com"}}))
agents._BACKUPS = str(backups)
agents._newest.update(name=None, email=None)
check("the account is read from the newest copy of the CLI's config", agents.account("claude-code").get("email") == "old@example.com")
(backups / ".claude.json.backup.2000").write_text(json.dumps({"oauthAccount": {"emailAddress": "new@example.com"}}))
check("...and a new sign-in is seen at once, with no restart", agents.account("claude-code").get("email") == "new@example.com")
(backups / ".claude.json.backup.3000").write_text("{not json")
check("...a copy that cannot be read keeps what was known", agents.account("claude-code").get("email") == "new@example.com")
# Signed out: the newest copy names no account, and the name ./sidenote up wrote at the last start is not shown as signed in
(Path(LOGS) / "account-file.json").write_text(json.dumps({"email": "start@example.com"}))
agents._ACCOUNT_FILE = str(Path(LOGS) / "account-file.json")
(backups / ".claude.json.backup.4000").write_text(json.dumps({"numStartups": 3}))
check("...and a copy that names no account is a sign-out, not the last start's name", agents.account("claude-code") == {}, agents.account("claude-code"))
agents._BACKUPS = str(Path(LOGS) / "no-such-folder")
agents._newest.update(name=None, email=None)
check("...and with no copies the panel falls back to what ./sidenote up wrote, or nothing", isinstance(agents.account("claude-code"), dict))
check("the panel's box says whether it is what the crop took", 'bool(result.shown)' in (ROOT / "server" / "app.py").read_text(encoding="utf-8"))
# What is left of the plan: read where Claude Code's /usage reads it, with the CLI's own login. Shaped as the real answer was
import datetime as _dt  # noqa: E402
import http.server  # noqa: E402
import threading  # noqa: E402
plan_body = {"five_hour": None, "seven_day": {"utilization": 4.0, "resets_at": "2026-11-09T18:00:00.476266+00:00", "limit_dollars": None},
             "limits": [{"kind": "weekly_all", "group": "weekly", "percent": 4, "severity": "normal", "resets_at": "2026-11-09T17:59:59.827817+00:00", "scope": None, "is_active": True},
                        {"kind": "weekly_scoped", "group": "weekly", "percent": 0, "severity": "normal", "resets_at": "2026-11-09T18:00:00+00:00",
                         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}, "is_active": False}]}
got = agents.plan_usage(plan_body)
week_end = _dt.datetime(2026, 11, 9, 18, 0, 0, 476266, tzinfo=_dt.timezone.utc).timestamp()
check("the plan's usage: no session running is none used, the week as its share, a model's week not in use left out",
      got["session"] is None and got["week"]["used"] == 4.0 and got["models"] == [] and abs(got["week"]["resets"] - week_end) < 1, got)
got = agents.plan_usage({**plan_body, "five_hour": {"utilization": 37, "resets_at": "2026-11-03T08:00:00Z"}, "limits": [{**plan_body["limits"][1], "percent": 12, "is_active": True}]})
check("...a session in use, its time written with a Z, and a model's own week once it counts",
      got["session"]["used"] == 37.0 and got["session"]["resets"] == _dt.datetime(2026, 11, 3, 8, tzinfo=_dt.timezone.utc).timestamp() and got["models"][0]["name"] == "Fable", got)
check("...and an answer it does not know breaks nothing", agents.plan_usage({}) == {"session": None, "week": None, "models": []})
heard = []


class _Usage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        heard.append(self.headers.get("Authorization"))
        out = json.dumps(plan_body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


usage_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Usage)
threading.Thread(target=usage_srv.serve_forever, daemon=True).start()
agents.USAGE_URL = f"http://127.0.0.1:{usage_srv.server_address[1]}/api/oauth/usage"
home_was = os.environ.get("HOME")
fake_home = Path(LOGS) / "fake-home"
(fake_home / ".claude").mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(fake_home)
cred = fake_home / ".claude" / ".credentials.json"
cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-test", "expiresAt": (time.time() + 3600) * 1000, "subscriptionType": "max", "rateLimitTier": "default_claude_max_20x"}}))
q = agents.read_plan_usage()
check("the server reads what is left with the CLI's own login", q is not None and q["week"]["used"] == 4.0 and heard == ["Bearer tok-test"], q)
check("...and names the plan from that login, Max 20x, not the name a check gave before a new sign-in", agents._claude_plan() == "Max 20x")
cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-old", "expiresAt": (time.time() - 60) * 1000, "subscriptionType": "pro"}}))
check("a token run out is not used: the CLI refreshes it, the server never does", agents.read_plan_usage() is None and len(heard) == 1)
check("...and a Pro login is called Pro", agents._claude_plan() == "Pro")
usage_srv.shutdown()
os.environ["HOME"] = home_was or "/root"
app_src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
check("a panel that opens asks for the plan's meters at once, and the watcher asks in a task of its own (a slow address held it up)",
      app_src.count("STATE.quota_task = asyncio.create_task(refresh_quota())") == 2 and "await refresh_quota()" not in app_src)
# A read begun before the account changed is dropped: it would put the old account's figures under the new name
_was_agent, _was_read = A.CONFIG.agent, agents.read_plan_usage
A.CONFIG.agent = "claude-code"
_said = []
async def _no_panels():
    _said.append(1)
_was_bc = A.broadcast_engines
A.broadcast_engines = _no_panels
def _read_then_switch():
    A.STATE.quota_gen += 1          # the watcher saw another account while this read was out
    return {"session": {"used": 95.0, "resets": None}, "week": None, "models": [], "at": 1}
agents.read_plan_usage = _read_then_switch
A.STATE.quota, A.STATE.quota_busy = None, False
asyncio.run(A.refresh_quota())
check("a reading begun before the account changed is not shown", A.STATE.quota is None and not _said, A.STATE.quota)
agents.read_plan_usage = lambda: {"session": {"used": 12.0, "resets": None}, "week": None, "models": [], "at": 2}
asyncio.run(A.refresh_quota())
check("...one begun after it is", (A.STATE.quota or {}).get("session", {}).get("used") == 12.0 and _said, A.STATE.quota)
check("an account change empties the meters and has them read again at once",
      "STATE.quota, STATE.quota_at, STATE.quota_gen = None, 0.0, STATE.quota_gen + 1" in app_src)
agents.read_plan_usage, A.CONFIG.agent, A.broadcast_engines = _was_read, _was_agent, _was_bc
A.STATE.quota = None

# ---------------------------------------------------------------- an example's heading
print("[example headings]")
RE = pipeline.EXAMPLES_HEAD_RE
for text, want in (("입력 예 1\n3", True), ("출력 예 2\n3", True), ("예시 1\n", True), ("예시 입력\n", True), ("예제 입력 1\n", True), ("예제 3\n", True), ("입출력 예\n", True), ("Sample 1\n", True), ("Sample Input\n", True),
                   ("Input 1\n", True), ("Example 2:\n", True), ("테스트 케이스\n", True), ("예: 3\n", True),
                   ("예를 들어 aabbaccc는", False), ("입력은 N입니다", False), ("입력\n첫째 줄", False), ("출력\n답", False), ("예시를 들면", False), ("Input format", False), ("sample size", False)):
    check(f"{text[:14]!r} {'opens' if want else 'does not open'} an example section", bool(RE.search(text)) is want)
got = pipeline.seen_cases({"stdin": [{"input": "3\n1 2 3"}]}, "문제 설명\n입력 예 1\n3\n1 2 3\n출력 예 1\n6")
check("an example under a numbered heading is kept", len(got["stdin"]) == 1 and not got["unseen"], got)
got = pipeline.seen_cases({"stdin": [{"input": "8"}]}, "버섯이 8개 있습니다. 먹을 때마다 키가 바뀝니다.")
check("a number of the statement with no example heading is still left out", not got["stdin"] and got["unseen"] == 1, got)
src = (ROOT / "server" / "pipeline.py").read_text(encoding="utf-8")
check("what is left out is logged on one line, whatever its line breaks", 'repr(w)' in src)

# ---------------------------------------------------------------- the tray menu
print("[the tray menu]")
spec = importlib.util.spec_from_file_location("capture_under_test", sys.argv[1] if len(sys.argv) > 1 else ROOT / "client" / "capture.py")
stub_modules = {}
for name in ("pystray", "mss", "PIL.ImageGrab"):
    pass
sys.modules.setdefault("pystray", types.SimpleNamespace())
cap = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(cap)
except Exception as exc:
    check(f"the capture program loads ({type(exc).__name__}: {exc})", False)
    cap = None
if cap is not None:
    compile(cap.TRAY_MENU, "TRAY_MENU", "exec")
    menu = cap.TRAY_MENU
    check("the menu watches for its program ending", "parent = kernel32.OpenProcess" in menu and "WaitForSingleObject(parent, 0) == 0" in menu)
    check("...and one Windows kept from the front stays while the pointer is on it", "waited > 1.5 and not over" in menu)

    class Item:
        def __init__(self, text, checked=None, default=False):
            self.text, self.checked, self.enabled, self.visible, self.default = text, checked, True, True, default
            self.pressed = 0
        def __call__(self, icon):
            self.pressed += 1

    class FakeProc:
        def __init__(self, code): self.code, self.pid = code, 4242
        def wait(self, timeout=None): return self.code
        def poll(self): return self.code
        def kill(self): pass

    class Windll:
        class user32:
            GetCursorPos = staticmethod(lambda p: 1)
            SetForegroundWindow = staticmethod(lambda h: 1)
            AllowSetForegroundWindow = staticmethod(lambda p: 1)

    import ctypes
    switch = Item("소리 듣기", checked=True)
    plain = Item("끝내기")
    icon = types.SimpleNamespace(menu=types.SimpleNamespace(items=[switch, plain]), _hwnd=0, _on_notify=lambda w, l: natives.append(l))
    natives = []
    icon._message_handlers = {1024: icon._on_notify}
    made = []
    real_popen, had_windll = cap.subprocess.Popen if hasattr(cap, "subprocess") else subprocess.Popen, getattr(ctypes, "windll", None)
    ctypes.windll = Windll
    next_code = [100]

    def popen(*a, **k):
        p = FakeProc(next_code[0])
        made.append(a[0][-1])
        return p
    subprocess.Popen = popen
    subprocess.CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        check("it takes over the right click", cap.own_tray_menu(icon))
        click = icon._message_handlers[1024]

        def right(code):
            next_code[0] = code
            click(0, 0x0205)
            time.sleep(0.15)
        right(100)
        check("a switch pressed as drawn is pressed", switch.pressed == 1, switch.pressed)
        check("the menu is told which program it belongs to", json.loads(made[-1]).get("parent") == os.getpid(), made[-1][:120])
        # Changed elsewhere while the menu stood open: drawn checked, and already unchecked by the time of the press
        real_item_checked = switch.checked

        class Racing(FakeProc):
            def wait(self, timeout=None):
                switch.checked = not real_item_checked
                return 100
        subprocess.Popen = lambda *a, **k: Racing(100)
        before = switch.pressed
        click(0, 0x0205)
        time.sleep(0.15)
        check("a switch changed from the panel while the menu was open is not flipped back", switch.pressed == before, switch.pressed)
        switch.checked = real_item_checked
        subprocess.Popen = popen
        right(101)
        check("a plain row is pressed", plain.pressed == 1)
        right(0)
        check("closed without a press, nothing happens", switch.pressed == before and plain.pressed == 1)
        right(1)
        natives.clear()
        click(0, 0x0205)
        time.sleep(0.15)
        check("one failure to draw it keeps the menu: it may have been killed from outside", natives == [], natives)
        right(1)
        natives.clear()
        click(0, 0x0205)
        check("two in a row fall back to Windows' own", natives == [0x0205], natives)
    finally:
        subprocess.Popen = real
        if had_windll is None:
            del ctypes.windll
        else:
            ctypes.windll = had_windll

print(f"\n==== {len(OK)} passed, {len(BAD)} failed ====")
for b in BAD:
    print(f"  FAIL {b}")
sys.exit(1 if BAD else 0)
