"""The code runner's client: the runner is a service of its own (runner/runner.py, compose's runner, the chart's runner
Deployment) with no network, reached over its Unix socket under compose (`unix:///sock/runner.sock`) and over HTTP with
its token in a cluster (`http://<release>-runner:8000/run`). Plain blocking calls, which the server makes from an
executor; what a run means for the panels (app.py, run_code) stays in the server.
"""
from __future__ import annotations

import http.client
import json
import socket
from urllib.parse import urlsplit

from .config import CONFIG


def run_wait_seconds(runs: int = 1) -> float:
    """How long the server waits for one request: the runner may first finish the run before it (up to 15 s),
    then compile (at most 20 s, whatever the timeout, and twice when a C++ or Go compile is tried again) and run it on
    each input (the timeout each, and up to 3 s to clean up after it), plus a margin."""
    t = max(1.0, min(CONFIG.runner_timeout, 30.0))
    return 15 + 2 * 20 + (t + 3) * runs + 10


class _UnixConnection(http.client.HTTPConnection):
    """HTTP over the runner's Unix socket (its URL `unix:///sock/runner.sock`): the runner has no network."""

    def __init__(self, path: str, timeout: float):
        super().__init__("runner", timeout=timeout)
        self.unix_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_path)


def _runner_call(url: str, path: str, payload: dict | None, timeout: float) -> dict:
    """GET (no payload) or POST JSON to the runner's `path` and return its JSON answer: over its Unix socket, or
    over HTTP for a runner reached by address (`http://host:port/run`). Runs in an executor."""
    u = urlsplit(url)
    conn = (_UnixConnection(u.path, timeout) if u.scheme == "unix"
            else http.client.HTTPConnection(u.hostname or "", u.port or 80, timeout=timeout))
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if CONFIG.runner_token:   # a runner over TCP takes only requests that carry its token
            headers["Authorization"] = f"Bearer {CONFIG.runner_token}"
        conn.request("POST" if payload is not None else "GET", path, body=body, headers=headers)
        r = conn.getresponse()
        text = r.read().decode()
        if r.status != 200:
            raise OSError(f"the code runner answered HTTP {r.status}")
        return json.loads(text)
    finally:
        conn.close()


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    """POST a run to the runner and return its JSON answer. Runs in an executor."""
    return _runner_call(url, "/run" if url.startswith("unix:") else urlsplit(url).path or "/run", payload, timeout)


def _get_ok(url: str) -> bool:
    try:
        return bool(_runner_call(url, "/health", None, 1.5).get("ok"))
    except Exception:
        return False
