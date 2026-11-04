"""Whether a newer release of Sidenote is out, from GitHub's latest release.

The server asks a minute after it starts and then once a day (ReleaseCheck.run): one GET of the repository's latest
release, with no token and with Sidenote's version in its User-Agent, and nothing else. The reply's tag is compared with
this code's version (server/version.py) as semantic versions, and a draft or a pre-release never counts. A newer
release goes to every panel as the status's `update` ({version, url}), which the panel shows as one line in its band.

No request is made with SIDENOTE_UPDATE_CHECK=0, with "Check for new versions" off in Solver settings, or in mock mode
(every suite and CI) unless SIDENOTE_UPDATE_CHECK=1 asks for it. A request that fails (no network, a timeout, GitHub's
rate limit, a reply that is not a release) is not tried again before the next day's.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from . import telemetry
from .config import CONFIG
from .version import VERSION

log = logging.getLogger("sidenote.updates")

REPO = "kanggu12/sidenote"
# A release's page is taken from the reply only when it is one of this repository's: the panel opens it from a link
NOTES_PREFIX = f"https://github.com/{REPO}/releases/"
FIRST_SEC = 60.0          # a minute after the start: the start itself is not slowed, and a restart asks once
EVERY_SEC = 24 * 3600.0   # then once a day, whatever came of the last request
TIMEOUT_SEC = 10.0        # for the connection and for each read; the whole request is given a few seconds more
MAX_BYTES = 2 << 20       # a release's reply, notes and file list included, is tens of KB: past this it is not one
# Who asks, as GitHub's API wants every request to say: the program and its version, and where it comes from
USER_AGENT = f"Sidenote/{VERSION} (+https://github.com/{REPO})"

# A semantic version as semver.org writes it, after an optional "v": MAJOR.MINOR.PATCH, a pre-release after "-" and
# build metadata after "+". ASCII digits only ([0-9], not \d, which takes other scripts' digits too).
_ID = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                    rf"(?:-({_ID}(?:\.{_ID})*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
# What may follow NOTES_PREFIX in a link: path segments of plain characters (no query, fragment, quote, space or %)
LINK_TAIL = re.compile(r"[A-Za-z0-9._~+-]+(?:/[A-Za-z0-9._~+-]+)*")
# What the log says of a check that found nothing to tell
SAID = {"same": "nothing newer than {version}", "unchanged": "no change since the last reply",
        "skipped": "the latest is a draft or a pre-release, which does not count"}


def parse(tag) -> tuple | None:
    """A tag ("v1.2.3", "1.2.3-rc.1") as (major, minor, patch, its pre-release identifiers), or None when it is not a
    semantic version. Build metadata ("+abc") is read and dropped: it does not order versions."""
    if not isinstance(tag, str) or len(tag) > 128:
        return None
    m = SEMVER.fullmatch(tag.strip())
    if not m:
        return None
    # a numeric identifier is a number (2 comes before 10), any other is a word
    pre = tuple(int(x) if x.isdigit() else x for x in m.group(4).split(".")) if m.group(4) else ()
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), pre


def order(version: tuple) -> tuple:
    """A parsed version as a key that sorts the way semver.org says versions take precedence."""
    major, minor, patch, pre = version
    # among pre-release identifiers numbers come before words, numbers by value and words letter by letter; with the
    # same identifiers as far as both go, the shorter comes first, as tuples compare
    ids = tuple((0, x, "") if isinstance(x, int) else (1, 0, x) for x in pre)
    # a release comes after all of its pre-releases: 1.0.0-rc.1 before 1.0.0
    return major, minor, patch, 0 if pre else 1, ids


def newer(tag, than: str = VERSION) -> bool:
    """Whether `tag` names a later version than `than`, this code's own unless another is given."""
    a, b = parse(tag), parse(than)
    return a is not None and b is not None and order(a) > order(b)


def notes_link(url) -> str:
    """The release's page from the reply when it is under this repository's releases, else "" (the notice is then
    shown without its link). After the prefix only plain path segments: no "..", query, fragment, quote or space."""
    if not isinstance(url, str) or not url.startswith(NOTES_PREFIX) or len(url) > 300:
        return ""
    tail = url[len(NOTES_PREFIX):]
    # "." and ".." are segments a browser resolves, which would take the link out of the releases
    if not LINK_TAIL.fullmatch(tail) or any(part in (".", "..") for part in tail.split("/")):
        return ""
    return url


def allowed() -> bool:
    """Whether this server may ask at all: never with SIDENOTE_UPDATE_CHECK=0, always with 1, and with it unset in every
    mode but mock (the suites and CI run in mock mode, and none of them may reach GitHub)."""
    return CONFIG.update_check == "1" or (CONFIG.update_check == "" and CONFIG.analyzer != "mock")


def fetch(url: str, etag: str = "", timeout: float = TIMEOUT_SEC) -> tuple[int, bytes, str, dict]:
    """GET `url` once, in a thread (it blocks): (HTTP status, body, ETag, headers). A reply with an error status comes
    back as its status with no body; no reply at all raises OSError (urllib.error.URLError, TimeoutError)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if etag:
        headers["If-None-Match"] = etag   # the reply before: an unchanged release comes back as 304, with no body
    request = urllib.request.Request(url, headers=headers)   # no Authorization: the request carries no token
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            # one byte past the cap, so a reply over it is told from one that fills it exactly
            return reply.status, reply.read(MAX_BYTES + 1), reply.headers.get("ETag") or "", dict(reply.headers)
    except urllib.error.HTTPError as err:
        # 304 (no change), 403 and 429 (the rate limit), 404 (no release yet) and the rest: a status, and its headers
        with err:
            return err.code, b"", "", dict(err.headers or {})


def _settled(future: asyncio.Future) -> None:
    """The end of a request nobody waits for any more (a timeout, the server closing down): its error, if it had one,
    is read here, so asyncio does not report it as never retrieved."""
    if not future.cancelled():
        future.exception()


class ReleaseCheck:
    """The newer release known, if any, and the loop that asks for it: one for the server (RELEASES)."""

    def __init__(self) -> None:
        self.found: dict | None = None   # a newer release: {"version": "0.1.2", "url": its page, or ""}
        self.etag = ""                   # the last reply's ETag: the next request asks whether anything changed
        self.asked_at = 0.0              # when the last request went out (time.monotonic(); 0: none yet)
        self.asked = 0                   # requests made since the start
        self.last = ""                   # what the last one came to: "newer", "same", "unchanged", or why it failed
        self.wake: asyncio.Event | None = None   # set when the panel's switch changes (poke): the loop looks again

    def allowed(self) -> bool:
        """Whether this server may ask at all (allowed() above), read again each time."""
        return allowed()

    def poke(self) -> None:
        """The panel's switch changed: the loop decides again now, not at the end of its wait."""
        if self.wake is not None:
            self.wake.set()

    async def rest(self, seconds: float | None) -> None:
        """Until `seconds` pass (None: no end) or poke() wakes the loop. With asyncio.wait and not wait_for: before
        Python 3.12, wait_for drops a cancellation that comes as what it waits for ends, and the loop then ran on after
        it was cancelled. check() waits for its request the same way."""
        woken = asyncio.ensure_future(self.wake.wait())
        try:
            await asyncio.wait({woken}, timeout=seconds)
        finally:
            woken.cancel()              # the wait for the switch, when the time ran out first or the loop was cancelled

    async def check(self) -> str:
        """One request for the latest release. `found` follows what it says, and stays as it was when it says nothing
        new (a draft, a pre-release, no change) or fails. Returns what it came to."""
        self.asked_at, self.asked = time.monotonic(), self.asked + 1
        url = CONFIG.update_url
        where = urlsplit(url).hostname or "?"
        if urlsplit(url).scheme not in ("https", "http"):   # a file: or ftp: address would be read as well as asked
            outcome, status = "not a web address", 0
        else:
            asking = asyncio.ensure_future(asyncio.to_thread(fetch, url, self.etag, TIMEOUT_SEC))
            asking.add_done_callback(_settled)   # a request given up on still ends in its thread, and quietly
            # The thread's own timeouts cover the connection and each read; this covers the name lookup and the whole
            # reply, so a server that sends a byte a second cannot hold the check for minutes
            try:
                done, _ = await asyncio.wait({asking}, timeout=TIMEOUT_SEC + 5)
            except asyncio.CancelledError:
                asking.cancel()   # the server closing down: the thread ends by itself, and nothing waits on it
                raise
            try:
                if not done:
                    raise TimeoutError
                status, body, etag, headers = asking.result()
            except TimeoutError:
                outcome, status = "timeout", 0
            except OSError as exc:   # no network, no name, refused, reset: urllib.error.URLError is an OSError
                why = getattr(exc, "reason", exc)
                # a connection that timed out comes wrapped in URLError: still a timeout
                outcome, status = ("timeout" if isinstance(why, TimeoutError) else f"no connection ({why})"), 0
            except http.client.HTTPException as exc:   # a reply cut off or not HTTP at all
                outcome, status = f"a broken reply ({type(exc).__name__})", 0
            else:
                outcome = self.take(status, body, etag, headers)
        telemetry.event("outbound", to=where, what="release check", status=status or None, result=outcome)
        self.last = outcome
        if outcome == "newer":
            log.info("release check: Sidenote %s is out (this is %s)%s", self.found["version"], VERSION,
                     "" if self.found["url"] else "; its page is not under this repository's releases, and is left out")
        elif outcome in SAID:
            log.info("release check: %s", SAID[outcome].format(version=VERSION))
        else:
            log.warning("release check failed (%s); the next one is in a day", outcome)
        return outcome

    def take(self, status: int, body: bytes, etag: str, headers: dict) -> str:
        """What a reply comes to, and `found` and `etag` set from it."""
        if status == 304:
            return "unchanged"
        if status in (403, 429):
            # GitHub's limit for requests with no token is 60 an hour for an address: 403 with no requests left, or 429
            left = {k.lower(): v for k, v in headers.items()}.get("x-ratelimit-remaining")
            return "rate limited" if status == 429 or left == "0" else f"HTTP {status}"
        if status != 200:
            return f"HTTP {status}"
        if len(body) > MAX_BYTES:
            return "not a release (too long)"
        try:
            reply = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):   # the last: arrays nested past the parser's depth
            return "not a release (not JSON)"
        version = parse(reply.get("tag_name")) if isinstance(reply, dict) else None
        if version is None:
            return "not a release (no version in its tag)"
        self.etag = etag   # a reply that was read: the next request asks whether it changed
        # A draft, or a pre-release by its flag or by its tag, never counts: what was known stays. The latest release
        # GitHub gives is neither, so this is the second of two guards
        if reply.get("draft") or reply.get("prerelease") or version[3]:
            return "skipped"
        if not newer(reply.get("tag_name")):
            self.found = None   # this version or an older one is the latest: nothing to tell
            return "same"
        # the version as digits again, not the tag as it came: of the reply only numbers and a checked link go on
        self.found = {"version": "%d.%d.%d" % version[:3], "url": notes_link(reply.get("html_url"))}
        return "newer"

    async def run(self, enabled: Callable[[], bool], publish: Callable[[], Awaitable[None]]) -> None:
        """Ask a minute after the start, then once a day, while this server may ask and `enabled` (the panel's switch)
        says so; `publish` tells the panels when what is known changes. Switched off, it waits for the switch to come
        on, and asks then unless it asked within the day."""
        self.wake = asyncio.Event()   # made here, in the loop that waits on it (a test may start the server twice)
        await asyncio.sleep(FIRST_SEC)
        while True:
            self.wake.clear()          # a change from here on is seen by the wait below
            if not (self.allowed() and enabled()):
                await self.rest(None)   # off: no request, until the switch comes on again
                continue
            due = self.asked_at + EVERY_SEC - time.monotonic() if self.asked_at else 0.0
            if due > 0:                 # asked within the day: the next request waits for the day to end
                await self.rest(due)
                continue
            before = self.found
            try:
                await self.check()
            except Exception:           # a bug here must not end the loop: the next day's request is still made
                log.exception("release check failed")
            if self.found != before:
                await publish()


RELEASES = ReleaseCheck()
