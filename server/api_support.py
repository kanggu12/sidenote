"""What the API's routes share (docs/API.md; the routes themselves are in app.py, create_app): the answer that refuses
a request (another site's page, a body that is not JSON), the body read with its cap, one reader's stream of the events
the panels are sent, the replies a panel's message sends back to the one who asked, and the backup's download. Nothing
here reads the server's state: it is the API's own plumbing, which a route of another service would use the same way.
"""
from __future__ import annotations

import asyncio
import collections
import json
import math
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import maintenance, telemetry
from .guards import origin_ok
from .i18n import t

# What one request's body or one panel's message may hold. The largest the server takes is a code run (MAX_RUN_CODE
# characters of code and MAX_RUN_STDIN of input: some hundred KB as JSON). A body was read whole before any check, so a
# program could send gigabytes into the server's memory; a panel's message of 64 MB (what a socket takes, for a 4K
# screen) was parsed on the loop that serves everyone, for seconds, and the watchdog ends a server whose loop stops.
MAX_BODY = 2 * 1024 * 1024


class EventStream:
    """One reader of /api/v1/events: the messages the panels are sent, in order. A reader that falls MAX behind loses the
    oldest, and its next batch starts with how many (a `lagged` message), so it knows to read the state again."""

    MAX = 2000

    def __init__(self):
        self.items: collections.deque = collections.deque()
        self.lost = 0                  # dropped since the last batch was taken
        self.ready = asyncio.Event()   # set when something is waiting to be taken

    def put(self, message: dict) -> None:
        if len(self.items) >= self.MAX:
            self.items.popleft()
            self.lost += 1
        self.items.append(message)
        self.ready.set()

    async def take(self, timeout: float) -> list:
        """What came since the last take, after waiting up to `timeout` s for something; [] when nothing came."""
        if not self.items:
            self.ready.clear()         # no await between the look and this: put() runs on the same loop
            try:
                await asyncio.wait_for(self.ready.wait(), timeout)
            except asyncio.TimeoutError:
                return []
        out = list(self.items)
        self.items.clear()
        if self.lost:
            out.insert(0, {"type": "lagged", "lost": self.lost})
            self.lost = 0
        return out



def api_error(status: int, text: str, headers: dict | None = None, **more) -> JSONResponse:
    return JSONResponse({"ok": False, "error": text, **more}, status_code=status, headers=headers)


def api_refused(request: Request, write: bool) -> JSONResponse | None:
    """None when the request may go on. A browser says where a request comes from (Origin), and one from another site's
    page is refused, as the panel's socket refuses it; a program sends none. What changes something takes a JSON body
    only: another site's page cannot send one without asking first (a preflight, which this server never answers),
    and a plain form post sends none."""
    origin = request.headers.get("origin")
    if origin and not origin_ok(origin, request.headers.get("host")):   # none, or empty: not a browser, as same_origin
        telemetry.event("refused", path=request.url.path[:120], origin=origin[:120])
        # in the panel's language, as every error's words (docs/API.md): the Maintenance sheet shows the error it is given
        return api_error(403, t("not allowed from another site's page"))
    if write and request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return api_error(415, t("send JSON (Content-Type: application/json), {} when there is nothing to send"))
    return None


def _not_json(token: str):
    """json.loads takes NaN and Infinity, which are not JSON: refused (api_body)."""
    raise ValueError(f"{token} is not JSON")


def _finite(value) -> bool:
    """Whether every number in `value` is finite: 1e999 reads as infinity, which no answer can carry back (allow_nan=False)."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


def too_large() -> JSONResponse:
    """The 413 of a body over MAX_BODY, with the connection closed after it: left open, uvicorn went on reading the rest
    of the body and dropping it, for as long as the sender went on sending (an endless body in pieces, for ever)."""
    return api_error(413, t("the body is over {mb} MB", mb=MAX_BODY // (1024 * 1024)), headers={"connection": "close"})


async def api_body(request: Request) -> dict | JSONResponse:
    """A write's JSON object ({} for an empty body), or the error that answers it. What JSON allows and nothing past it:
    NaN, Infinity and a number too large for a float were taken, and answering them ended in a 500; a lone surrogate
    ("\ud800") was taken too, and a setting holding one could not be saved or sent, so every answer showing it was a 500
    and an event holding one ended every events stream. A body over MAX_BODY is a 413, refused as it comes in."""
    declared = request.headers.get("content-length", "")
    # ASCII digits only: "²" is a digit to isdigit() and no number to int(), which made a 500 of it
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY:   # refused before any of it is read
        return too_large()
    pieces, size = [], 0
    async for piece in request.stream():   # a piece at a time: a body that goes on past the cap is never held whole
        size += len(piece)
        if size > MAX_BODY:
            return too_large()
        pieces.append(piece)
    raw = b"".join(pieces)
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw, parse_constant=_not_json)
    except (ValueError, RecursionError):   # nested past what Python reads (a thousand levels) is no body either
        return api_error(400, t("the body is not JSON"))
    if not isinstance(data, dict):
        return api_error(400, t("the body is a JSON object"))
    try:
        if not _finite(data):
            return api_error(400, t("a number in the body is too large"))
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except RecursionError:   # read, but nested deeper than the checks walk (some 450 levels): no route takes such a body
        return api_error(400, t("the body is nested too deeply"))
    except UnicodeEncodeError:
        return api_error(400, t("the body holds text that is not valid Unicode"))
    return data


class BackupResponse(StreamingResponse):
    """A backup's archive sent a block at a time (maintenance.stream_backup), and removed with its folder however the
    response ends: sent whole, cut after a block, or cut before the first. The generator's own finally runs only once it
    has started, and a connection gone before the first block (a tab closed while the backup was made, a program's
    timeout) never starts it: the archive, the whole history in it, stayed in the data folder until the next start."""

    def __init__(self, archive: Path, headers: dict):
        super().__init__(maintenance.stream_backup(archive), media_type="application/gzip", headers=headers)
        self.archive = archive

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:   # gone already after a whole send (the generator's finally), so a second removal finds nothing
            maintenance.remove_backup(self.archive)


class Replies:
    """What a command sends back to the one who asked (panel_command's `reply`), kept for the API's answer."""

    def __init__(self):
        self.messages: list = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    def notices(self) -> list:
        return [{"level": m.get("level"), "text": m.get("text")} for m in self.messages if m.get("type") == "notice"]

    def refusal(self) -> str | None:
        """The words of a notice that says it was not done (a warning or a failure), or None."""
        return next((m.get("text") for m in self.messages if m.get("type") == "notice" and m.get("level") in ("warn", "bad")),
                    None)

    def first(self, kind: str) -> dict | None:
        return next((m for m in self.messages if m.get("type") == kind), None)


def sse(n: int, message: dict) -> str:
    """One message as a Server-Sent Event: its number, then the message as one line of JSON. Text that cannot be written as
    UTF-8 (a lone surrogate) goes escaped, as JSON allows, and not as the end of the stream it broke."""
    try:
        line = json.dumps(message, ensure_ascii=False)
        line.encode("utf-8")
    except UnicodeEncodeError:
        line = json.dumps(message)
    return f"id: {n}\ndata: {line}\n\n"
