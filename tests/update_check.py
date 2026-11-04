"""The check for a newer release (server/updates.py), against a stand-in for GitHub's API and never GitHub itself: a
newer release, the same, an older one, a pre-release, a draft, a reply that is not JSON, one that never comes and
GitHub's rate limit; the request as it goes out (its User-Agent, no token, the ETag) and no retry before the next day's;
a release page outside this repository refused; "Check for new versions" and SIDENOTE_UPDATE_CHECK=0 each stopping the
request entirely, and mock mode making none unless asked; the notice reaching a panel that connects later.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/update_check.py

The waits of a minute and a day are made a fraction of a second here (updates.FIRST_SEC, EVERY_SEC), and the
request's timeout too; what they are in the code is checked as written.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []
TMP = Path(tempfile.mkdtemp(prefix="sidenote-update-"))   # the logs of every server run here, removed at the end
LATEST = "/repos/kanggu12/sidenote/releases/latest"   # the path GitHub's API has the latest release at
NOTES = "https://github.com/kanggu12/sidenote/releases/tag/"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)


# ---------- the stand-in for GitHub, on this machine ----------
REPLY: dict = {}            # what it answers now (set by each case)
SEEN: list = []             # every request it got: when, the path, the method and the headers


class GitHub(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append({"at": time.monotonic(), "path": self.path, "method": "GET",
                     "headers": {k.lower(): v for k, v in self.headers.items()}})
        if REPLY.get("sleep"):                       # a reply that does not come in time
            time.sleep(REPLY["sleep"])
        status, headers, body = REPLY.get("status", 200), dict(REPLY.get("headers") or {}), REPLY.get("body", b"")
        etag = headers.get("ETag")
        if etag and self.headers.get("If-None-Match") == etag:   # the release asked about again, unchanged
            status, body = 304, b""
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:                              # the client gave up waiting: nothing to send it
            pass

    def do_POST(self):                               # the check only ever asks; anything else is counted and refused
        SEEN.append({"at": time.monotonic(), "path": self.path, "method": "POST", "headers": dict(self.headers)})
        self.send_response(405)
        self.end_headers()

    def log_message(self, *args):
        pass


stand = ThreadingHTTPServer(("127.0.0.1", 0), GitHub)
threading.Thread(target=stand.serve_forever, daemon=True).start()
STAND_URL = f"http://127.0.0.1:{stand.server_address[1]}{LATEST}"

# The server's code reads these when it is imported: mock engines, no speech, and the check pointed at the stand-in from
# the start, so that a request this suite did not mean to make reaches it and is counted, not GitHub
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_SEARCH_URL="",
                  SIDENOTE_AGENT="mock", SIDENOTE_LOG_DIR=str(TMP / "logs"),
                  SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_UPDATE_URL=STAND_URL)
os.environ.pop("SIDENOTE_UPDATE_CHECK", None)     # its default, which in mock mode is off

from server import updates as U  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.version import VERSION  # noqa: E402

major, minor, patch = (int(x) for x in VERSION.split("-")[0].split("+")[0].split("."))
NEWER = f"{major}.{minor}.{patch + 2}"
OLDER = f"{major}.{minor}.{patch - 1}" if patch else f"{major}.{minor - 1}.9" if minor else f"{major - 1}.9.9"


def release(tag, url=None, draft=False, prerelease=False, etag=None, **more) -> dict:
    """What the stand-in answers for the latest release: GitHub's own fields, as many as the check reads and a few more."""
    body = {"url": f"https://api.github.com{LATEST}", "html_url": url if url is not None else NOTES + tag, "tag_name": tag,
            "name": tag, "draft": draft, "prerelease": prerelease,
            "body": "notes " * 200, "assets": [], **more}
    headers = {"Content-Type": "application/json; charset=utf-8", **({"ETag": etag} if etag else {})}
    return {"status": 200, "headers": headers, "body": json.dumps(body).encode()}


def fresh() -> None:
    """The check as it is when the server starts: nothing found, no ETag, never asked."""
    U.RELEASES.found, U.RELEASES.etag, U.RELEASES.asked_at, U.RELEASES.asked, U.RELEASES.last = None, "", 0.0, 0, ""


def ask(reply: dict) -> str:
    """One check against the stand-in answering `reply`; what it came to."""
    REPLY.clear()
    REPLY.update(reply)
    return asyncio.run(U.RELEASES.check())


print("\n[versions]")
check(f"server/version.py's VERSION is MAJOR.MINOR.PATCH ({VERSION})", U.parse(VERSION) is not None and not U.parse(VERSION)[3])
chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1",
         "1.0.0", "1.0.1", "1.1.0", "2.0.0", "10.0.0"]
check("versions are ordered as semver.org orders them (numbers by value, pre-releases before their release)",
      all(U.newer(b, a) and not U.newer(a, b) for a, b in zip(chain, chain[1:])),
      [(a, b) for a, b in zip(chain, chain[1:]) if not U.newer(b, a)])
check("a leading v, and build metadata, which does not order versions", U.parse("v1.2.3") == (1, 2, 3, ())
      and not U.newer("1.2.3+build.5", "1.2.3") and not U.newer("v1.2.3", "1.2.3"))
check("what is not a version is not newer than anything", not any(U.newer(x) for x in
      ("", "latest", "v1.2", "1.2.3.4", "01.2.3", "v1.2.3-", "１.２.３", None, 12, "v" + "9" * 200)))
check("the waits are a minute after the start and then a day, the timeout short",
      U.FIRST_SEC == 60 and U.EVERY_SEC == 24 * 3600 and 0 < U.TIMEOUT_SEC <= 15, (U.FIRST_SEC, U.EVERY_SEC, U.TIMEOUT_SEC))
check("by default it asks GitHub's API for this repository's latest release",
      "https://api.github.com/repos/kanggu12/sidenote/releases/latest" in (ROOT / "server" / "config.py").read_text(encoding="utf-8"))

# A server that sends a byte now and then passes every read's timeout: the whole request has a limit of its own. Here the
# request stands in as a thread that takes longer than that limit, then fails with nobody waiting for it
real_fetch, reports = U.fetch, []


def slow_fetch(*_):
    time.sleep(U.TIMEOUT_SEC + 5 + 1.5)
    raise OSError("the connection dropped after the check gave up on it")


async def gives_up() -> tuple:
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, ctx: reports.append(ctx.get("message")))   # what asyncio would print
    began = time.monotonic()
    outcome = await U.RELEASES.check()
    took = time.monotonic() - began
    await asyncio.sleep(2.0)                         # the thread ends in here, and its error has nowhere to go
    import gc
    gc.collect()                                     # asyncio reports an error nobody read when the future is collected
    await asyncio.sleep(0)
    return outcome, took


U.fetch = slow_fetch
fresh()
got, took = asyncio.run(gives_up())
U.fetch = real_fetch
check("a reply that never ends is given up on at the whole request's limit", got == "timeout" and took < U.TIMEOUT_SEC + 5 + 0.8,
      (got, round(took, 2)))
check("...and the request given up on ends in its thread with nothing reported", not reports, reports)

print("\n[a reply from the stand-in]")
CONFIG.update_check = "1"                           # this server may ask: as SIDENOTE_UPDATE_CHECK=1 says
U.TIMEOUT_SEC = 0.6                                 # a reply that does not come is given up on quickly here
fresh()
SEEN.clear()
got = ask(release("v" + NEWER, etag='"r1"'))
check("a newer release is found, with its page", got == "newer" and U.RELEASES.found == {"version": NEWER, "url": NOTES + "v" + NEWER},
      (got, U.RELEASES.found))
req = SEEN[-1] if SEEN else {"headers": {}}
check("one GET of the latest release", len(SEEN) == 1 and req["method"] == "GET" and req["path"] == LATEST, SEEN[-1:])
check("its User-Agent names Sidenote and its version", req["headers"].get("user-agent") == f"Sidenote/{VERSION} (+https://github.com/kanggu12/sidenote)",
      req["headers"].get("user-agent"))
check("it carries no token and no cookie", not {"authorization", "cookie"} & set(req["headers"]), sorted(req["headers"]))
got = ask(release("v" + NEWER, etag='"r1"'))
check("asked again it sends the ETag, and a 304 keeps what was found",
      got == "unchanged" and SEEN[-1]["headers"].get("if-none-match") == '"r1"' and U.RELEASES.found == {"version": NEWER, "url": NOTES + "v" + NEWER},
      (got, SEEN[-1]["headers"].get("if-none-match"), U.RELEASES.found))
got = ask(release("v" + VERSION))
check("the same version as this one: nothing newer, and what was found goes", got == "same" and U.RELEASES.found is None, (got, U.RELEASES.found))
got = ask(release("v" + OLDER))
check("an older release: nothing newer", got == "same" and U.RELEASES.found is None, (got, U.RELEASES.found))
known = {"version": NEWER, "url": NOTES + "v" + NEWER}
for name, reply in (("a pre-release by its flag", release(f"v{major + 1}.0.0", prerelease=True)),
                    ("a pre-release by its tag", release(f"v{major + 1}.0.0-rc.1")),
                    ("a draft", release(f"v{major + 1}.0.0", draft=True))):
    U.RELEASES.found = dict(known)
    got = ask(reply)
    check(f"{name} never counts, and leaves what was known as it was", got == "skipped" and U.RELEASES.found == known, (got, U.RELEASES.found))
for name, reply, want in (
        ("a reply that is not JSON", {"status": 200, "headers": {"Content-Type": "application/json"}, "body": b'{"tag_name": "v9.9.9", '}, "not a release (not JSON)"),
        ("JSON that is not a release", {"status": 200, "body": b'[{"tag_name": "v9.9.9"}]'}, "not a release (no version in its tag)"),
        ("a release whose tag is not a version", release("nightly"), "not a release (no version in its tag)"),
        ("arrays nested past the parser's depth", {"status": 200, "body": b"[" * 200000 + b"]" * 200000}, "not a release (not JSON)"),
        ("GitHub's rate limit (403, none left)", {"status": 403, "headers": {"X-RateLimit-Remaining": "0", "Content-Type": "application/json"},
                                                  "body": b'{"message": "API rate limit exceeded"}'}, "rate limited"),
        ("GitHub's rate limit (429)", {"status": 429, "headers": {"Retry-After": "60"}}, "rate limited"),
        ("no release yet (404)", {"status": 404, "body": b'{"message": "Not Found"}'}, "HTTP 404")):
    U.RELEASES.found = dict(known)
    got = ask(reply)
    check(f"{name}: a failure, and what was known stays", got == want and U.RELEASES.found == known, (got, U.RELEASES.found))
U.RELEASES.found = dict(known)
began = time.monotonic()
got = ask({**release("v" + NEWER), "sleep": 2.5})
took = time.monotonic() - began
check("a reply that does not come: given up on at the timeout, and what was known stays",
      got == "timeout" and took < 2.0 and U.RELEASES.found == known, (got, round(took, 2)))
saved_url = CONFIG.update_url
CONFIG.update_url = "http://127.0.0.1:9" + LATEST   # nothing listens there
got = ask(release("v" + NEWER))
check("no connection at all: a failure, said as one", got.startswith("no connection") or got == "timeout", got)
CONFIG.update_url = "file:///etc/hostname"
got = ask(release("v" + NEWER))
check("an address that is not a web address is not read", got == "not a web address", got)
CONFIG.update_url = saved_url
U.MAX_BYTES, saved_max = 1000, U.MAX_BYTES
got = ask(release("v" + NEWER))
U.MAX_BYTES = saved_max
check("a reply longer than any release is not one", got == "not a release (too long)", got)

print("\n[the release's page]")
for name, url in (("another site", f"https://evil.example.com/kanggu12/sidenote/releases/tag/v{NEWER}"),
                  ("another repository of the same owner", f"https://github.com/kanggu12/sidenote-fork/releases/tag/v{NEWER}"),
                  ("a path that climbs out of the releases", "https://github.com/kanggu12/sidenote/releases/../../other/repo"),
                  ("plain http", f"http://github.com/kanggu12/sidenote/releases/tag/v{NEWER}"),
                  ("a script", "javascript:alert(1)"),
                  ("words that would leave the attribute", f'https://github.com/kanggu12/sidenote/releases/tag/v{NEWER}" onclick="x'),
                  ("a query", f"https://github.com/kanggu12/sidenote/releases/tag/v{NEWER}?next=https://evil.example.com")):
    fresh()
    got = ask(release("v" + NEWER, url=url))
    check(f"{name}: the release is told, its link refused", got == "newer" and U.RELEASES.found == {"version": NEWER, "url": ""}, U.RELEASES.found)
fresh()
ask(release(f"v{NEWER}+build.7"))
check("the version told is its numbers alone, not the tag as it came", U.RELEASES.found and U.RELEASES.found["version"] == NEWER, U.RELEASES.found)

print("\n[when it asks, and when it does not]")
STOPPED: list = []   # whether each loop run here stopped when cancelled, as the server's closing down cancels it


async def stop(task) -> None:
    """Cancel the loop and see that it ends: one that ran on (a cancellation lost) is a failing check, not a hang."""
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=5)
    STOPPED.append(bool(done))


async def run_for(seconds: float, enabled, flip: tuple | None = None) -> list:
    """The loop for a while, with `enabled` as the panel's switch; `flip` = (after, flag dict): the switch turned on then.
    Returns what was published."""
    told = []

    async def publish():
        told.append(U.RELEASES.found)
    task = asyncio.create_task(U.RELEASES.run(enabled, publish))
    if flip:
        await asyncio.sleep(flip[0])
        flip[1]["on"] = True
        U.RELEASES.poke()
        await asyncio.sleep(seconds - flip[0])
    else:
        await asyncio.sleep(seconds)
    await stop(task)
    return told


U.FIRST_SEC, U.EVERY_SEC = 0.3, 60.0
REPLY.clear()
REPLY.update(release("v" + NEWER))
for name, env, switch in (("mock mode with SIDENOTE_UPDATE_CHECK unset", "", True),
                          ("SIDENOTE_UPDATE_CHECK=0, the switch on", "0", True),
                          ("the switch off", "1", False)):
    CONFIG.update_check = env
    fresh()
    SEEN.clear()
    asyncio.run(run_for(1.0, lambda s=switch: s))
    check(f"{name}: no request at all", not SEEN and U.RELEASES.asked == 0, len(SEEN))
CONFIG.update_check = "1"
fresh()
SEEN.clear()
told = asyncio.run(run_for(0.15, lambda: True))
early = len(SEEN)
fresh()
SEEN.clear()
told = asyncio.run(run_for(1.0, lambda: True))
check("it asks once the first wait is over, not before", early == 0 and len(SEEN) == 1, (early, len(SEEN)))
check("...and tells the panels what it found", told == [{"version": NEWER, "url": NOTES + "v" + NEWER}], told)
flag = {"on": False}
fresh()
SEEN.clear()
began = time.monotonic()
asyncio.run(run_for(1.2, lambda: flag["on"], flip=(0.6, flag)))
check("the switch turned on asks then, having not asked within the day", len(SEEN) == 1 and SEEN[0]["at"] - began >= 0.55,
      [round(r["at"] - began, 2) for r in SEEN])
U.FIRST_SEC, U.EVERY_SEC = 0.2, 1.5
REPLY.clear()
REPLY.update({"status": 403, "headers": {"X-RateLimit-Remaining": "0"}})
fresh()
SEEN.clear()
asyncio.run(run_for(1.3, lambda: True))
within_day = len(SEEN)
fresh()
SEEN.clear()
asyncio.run(run_for(2.3, lambda: True))
gap = SEEN[1]["at"] - SEEN[0]["at"] if len(SEEN) == 2 else None
check("a failed request is not tried again within the day", within_day == 1, within_day)
check("...and the next day's is made", len(SEEN) == 2 and gap is not None and gap >= 1.4, (len(SEEN), gap))
flag = {"on": True}
fresh()
SEEN.clear()
REPLY.clear()
REPLY.update(release("v" + NEWER))


async def toggle() -> int:
    """Switched off and on again within the day, after it asked: no second request."""
    task = asyncio.create_task(U.RELEASES.run(lambda: flag["on"], lambda: asyncio.sleep(0)))
    await asyncio.sleep(0.5)
    for on in (False, True, False, True):
        flag["on"] = on
        U.RELEASES.poke()
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)
    await stop(task)
    return len(SEEN)
check("the switch turned off and on again within the day asks no more than once", asyncio.run(toggle()) == 1, len(SEEN))
check("each loop stopped when it was cancelled, as at the server's closing down", len(STOPPED) == 9 and all(STOPPED), STOPPED)


async def woken_as_cancelled(steps: int) -> bool:
    """The loop, waiting for the day to end after a request, woken by the switch and cancelled `steps` turns of the
    event loop later: whether it ended. It never ends by itself, so a cancellation lost on the way (asyncio.wait_for
    with a timeout, before Python 3.12, drops one that comes as what it waits for ends) leaves it running."""
    U.FIRST_SEC, U.EVERY_SEC = 0.0, 3600.0
    U.RELEASES.asked_at = time.monotonic()   # asked a moment ago: the next request is a day away
    task = asyncio.create_task(U.RELEASES.run(lambda: True, lambda: asyncio.sleep(0)))
    for _ in range(3):                   # past the first wait, into the wait for the day to end
        await asyncio.sleep(0)
    U.RELEASES.poke()
    for _ in range(steps):
        await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait({task}, timeout=2)
    return task.cancelled()
got = [asyncio.run(woken_as_cancelled(n)) for n in range(6)]
check("a cancellation that comes as the switch wakes the loop still stops it", all(got), got)


def default_in(**env) -> str:
    """The switch's default in a server started with these variables (a process of its own: they are read at import)."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("SIDENOTE_")}
    e.update(SIDENOTE_LOG_DIR=tempfile.mkdtemp(dir=TMP), SIDENOTE_TRANSCRIBER="null", **env)
    code = "from server.settings import SETTINGS; print(SETTINGS.defs['update_check'].default)"
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True).stdout.strip()


got = [default_in(SIDENOTE_ANALYZER="local"), default_in(SIDENOTE_ANALYZER="local", SIDENOTE_UPDATE_CHECK="0"),
       default_in(SIDENOTE_ANALYZER="mock"), default_in(SIDENOTE_ANALYZER="mock", SIDENOTE_UPDATE_CHECK="1")]
check("\"Check for new versions\" is on by default, off with SIDENOTE_UPDATE_CHECK=0 and in mock mode", got == ["True", "False", "False", "True"], got)

print("\n[the panels]")
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

ORIGIN = {"origin": "http://127.0.0.1:8777"}


class Panel:
    """Reads every message a panel socket gets, in a thread."""

    def __init__(self, ws):
        self.ws, self.msgs = ws, []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.msgs.append(json.loads(self.ws.receive_text()))
        except Exception:
            pass

    def wait(self, pred, timeout=6.0, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in self.msgs[after:]:
                if pred(m):
                    return m
            time.sleep(0.05)
        return None


def first_status(p: Panel) -> dict:
    return p.wait(lambda m: m.get("type") == "status" and "engines" in m) or {}


SETTINGS.path = None                       # nothing written beside the logs
SETTINGS.set("update_check", True)         # on, as it starts wherever the environment lets it
U.FIRST_SEC, U.EVERY_SEC = 0.8, 3600.0
CONFIG.update_check = "1"
fresh()
SEEN.clear()
REPLY.clear()
REPLY.update(release("v" + NEWER, etag='"p1"'))
found = {"version": NEWER, "url": NOTES + "v" + NEWER}
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    health = client.get("/health").json()
    check("/health carries the version", health.get("version") == VERSION, health.get("version"))
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as w1:
        p1 = Panel(w1)
        s1 = first_status(p1)
        check("a panel's status carries the version, that the check may run, and no release yet",
              s1.get("version") == VERSION and s1.get("update_check") is True and s1.get("update") is None, s1 and {k: s1.get(k) for k in ("version", "update_check", "update")})
        told = p1.wait(lambda m: m.get("type") == "status" and m.get("update"))
        check("a panel open when the release is found is told", told and told["update"] == found, told)
        check("...after one request", len(SEEN) == 1, len(SEEN))
        with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as w2:
            p2 = Panel(w2)
            s2 = first_status(p2)
            check("a panel that connects later gets the notice with its status", s2.get("update") == found, s2.get("update"))
            n1, n2 = len(p1.msgs), len(p2.msgs)
            w1.send_text(json.dumps({"type": "setting", "key": "update_check", "value": False}))
            off1 = p1.wait(lambda m: m.get("type") == "status" and "update" in m and m["update"] is None, after=n1)
            off2 = p2.wait(lambda m: m.get("type") == "status" and "update" in m and m["update"] is None, after=n2)
            check("the switch turned off takes the notice off every panel", off1 is not None and off2 is not None, (off1, off2))
            with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as w3:
                s3 = first_status(Panel(w3))
                check("...and a panel that connects then gets none", "update" in s3 and s3["update"] is None, s3.get("update"))
            n1 = len(p1.msgs)
            w1.send_text(json.dumps({"type": "setting", "key": "update_check", "value": True}))
            back = p1.wait(lambda m: m.get("type") == "status" and m.get("update"), after=n1)
            time.sleep(0.4)
            check("turned on again, the release known is shown again, with no second request within the day",
                  back and back["update"] == found and len(SEEN) == 1, (back, len(SEEN)))
        CONFIG.update_check = "0"          # as SIDENOTE_UPDATE_CHECK=0 says
        with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as w4:
            s4 = first_status(Panel(w4))
            check("with SIDENOTE_UPDATE_CHECK=0 a panel is told the check cannot run, and gets no notice",
                  s4.get("update_check") is False and s4.get("update") is None, {k: s4.get(k) for k in ("update_check", "update")})
        CONFIG.update_check = "1"
events = [json.loads(line) for line in (Path(os.environ["SIDENOTE_LOG_DIR"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()
          if '"outbound"' in line]
check("the request is in the log of what left the PC: where to and what", any(e.get("to") == "127.0.0.1" and e.get("what") == "release check"
                                                                              and e.get("result") == "newer" for e in events), events[-2:])
item = next((i for i in SETTINGS.meta()["items"] if i["key"] == "update_check"), None)
check("\"Check for new versions\" is a switch in Solving, beside the searches",
      item and item["kind"] == "bool" and item["section"] == "solve"
      and [i["key"] for i in SETTINGS.meta()["items"] if i["section"] == "solve"][-3:] == ["web_search", "web_fetch", "update_check"], item)

stand.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
