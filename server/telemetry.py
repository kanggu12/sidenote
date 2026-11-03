"""Logs and monitoring for the server, all bounded on disk.

Files in SIDENOTE_LOG_DIR (in the container /data/logs, on the host
~/.local/state/sidenote/logs):
  server.log     the server's own log lines (also on stdout -> `./sidenote logs`)
  events.jsonl   one JSON object per line: analysis start / first token / done / cancelled /
                 error, follow-ups, capture client connect / disconnect, sign-in, start/stop.
                 `./sidenote events` and `./sidenote report` read it.
  capture.log    the capture program's output, written by `./sidenote capture`

Every file rotates by size (SIDENOTE_LOG_MAX_MB per file, SIDENOTE_LOG_FILES kept) and files
older than SIDENOTE_LOG_DAYS are deleted (at start and every 6 hours), so the folder never grows
without bound, even if the server is left unused for weeks. That goes for the live files too, not
only the rotated ones, judged by when each was last written: a tool not used for that long would
otherwise keep its lines for good, and what it writes down includes what it heard. A file still
written now and then keeps its older lines until it rotates.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from collections import Counter, deque
from pathlib import Path

from .config import env_float, env_int

log = logging.getLogger("sidenote.telemetry")

LOG_DIR = os.environ.get("SIDENOTE_LOG_DIR", "")
# Floors, not just defaults: RotatingFileHandler never rotates when either value is 0, so
# SIDENOTE_LOG_FILES=0 or SIDENOTE_LOG_MAX_MB=0 would let a file grow without bound.
MAX_BYTES = max(64 * 1024, int(env_float("SIDENOTE_LOG_MAX_MB", 5) * 1024 * 1024))
BACKUPS = max(1, env_int("SIDENOTE_LOG_FILES", 4))      # rotated files kept besides the live one
KEEP_DAYS = env_float("SIDENOTE_LOG_DAYS", 14)
STARTED = time.time()

LIVE = ("server.log", "events.jsonl", "capture.log")   # the files written to, not the .1 .2 copies

_events = logging.getLogger("sidenote.events")
_events.propagate = False


def setup() -> Path | None:
    """Attach size-rotating file handlers for server.log and events.jsonl. No log dir (a dev
    run without SIDENOTE_LOG_DIR) or an unwritable one: stdout only."""
    if not LOG_DIR:
        return None
    d = Path(LOG_DIR)
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        log.warning("log dir %s not writable (%s): logging to stdout only", d, exc)
        return None
    stale(d, LIVE)   # before the handlers open them
    server = logging.handlers.RotatingFileHandler(d / "server.log", maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    server.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(server)
    events = logging.handlers.RotatingFileHandler(d / "events.jsonl", maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    events.setFormatter(logging.Formatter("%(message)s"))
    _events.addHandler(events)
    _events.setLevel(logging.INFO)
    prune(d)
    log.info("logs in %s (%.0f MB x %d files each, kept %.0f days after their last line)",
             d, MAX_BYTES / 1048576, BACKUPS + 1, KEEP_DAYS)
    return d


def stale(d: Path, names) -> int:
    """Delete live log files nothing has written to for KEEP_DAYS: every line in them is older
    than that. Only called where the file is not open (setup, and capture.log from prune), because
    deleting an open file leaves its handler writing to something no one can read."""
    cutoff = time.time() - KEEP_DAYS * 86400
    gone = 0
    for name in names:
        f = d / name
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                gone += 1
        except OSError:
            pass
    if gone:
        log.info("removed %d log file(s) nothing had written to for %.0f days", gone, KEEP_DAYS)
    return gone


def prune(d: Path | None = None) -> int:
    """Delete log files older than KEEP_DAYS: the rotated copies, and capture.log when the capture
    program has not run for that long. Returns how many were removed."""
    d = d or (Path(LOG_DIR) if LOG_DIR else None)
    if not d or not d.is_dir():
        return 0
    removed = stale(d, ("capture.log",))   # the server's own two are open here; setup handles them
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in d.iterdir():
        # rotated: server.log.1, events.jsonl.3, capture.log.2 (never the live files)
        try:   # the stat too: a rotation can take the file away between the listing and here
            if f.is_file() and f.suffix.lstrip(".").isdigit() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("pruned %d log files older than %.0f days", removed, KEEP_DAYS)
    return removed


def disk_usage() -> dict:
    d = Path(LOG_DIR) if LOG_DIR else None
    if not d or not d.is_dir():
        return {"dir": None}
    # The kept answers have their own limit (history_mb) and are no log: counted, they read as logs over their cap
    files = [f for f in d.iterdir() if f.is_file() and not f.name.startswith((".", "history.sqlite"))]
    return {"dir": str(d), "files": len(files), "bytes": sum(f.stat().st_size for f in files),
            "cap_bytes": 3 * MAX_BYTES * (BACKUPS + 1), "keep_days": KEEP_DAYS}


# ---- in-memory stats for /stats (the last RECENT analyses) ----
RECENT = 300
_recent: deque = deque(maxlen=RECENT)
counts: Counter = Counter()
last_error: dict | None = None
_totals = {"answers": 0, "empty": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}   # since the server started


def event(kind: str, **fields) -> None:
    """Record one event: to events.jsonl (if file logging is on) and to the counters."""
    global last_error
    rec = {"ts": round(time.time(), 3), "event": kind, **{k: v for k, v in fields.items() if v is not None}}
    counts[kind] += 1
    _note_today(rec)
    if kind in ("analysis_done", "followup_done"):
        if fields.get("type") == "none":   # nothing to solve on screen: it cost tokens but is no answer
            _totals["empty"] += 1
        else:
            _recent.append(rec)
            _totals["answers"] += 1
        _totals["tokens_in"] += fields.get("tokens_in") or 0
        _totals["tokens_out"] += fields.get("tokens_out") or 0
        _totals["cost_usd"] += fields.get("cost_usd") or 0.0
    elif kind == "verify_done":   # The agent checking a local answer: it costs tokens but is no answer of its own
        _totals["tokens_in"] += fields.get("tokens_in") or 0
        _totals["tokens_out"] += fields.get("tokens_out") or 0
        _totals["cost_usd"] += fields.get("cost_usd") or 0.0
    elif kind in ("analysis_error", "followup_error"):
        counts[f"error_{fields.get('hint') or 'other'}"] += 1
        last_error = rec
        _recent.append(rec)
    if _events.handlers:
        try:
            _events.info(json.dumps(rec, ensure_ascii=False))
        except Exception:   # a log write must never break an analysis
            pass


# Today's answers, for the panel's two engine cards: what this PC's model and the agent have each done, told apart. Read back from the event log when the server starts,
# so a restart does not empty the cards. Answers of other days fall out as they are asked for.
_today: list[dict] = []
_TODAY_KEEP = 3000
_TODAY_FIELDS = ("ts", "event", "engine", "elapsed", "first_token", "tokens_in", "tokens_out", "cost_usd", "type", "id")


def _midnight(now: float | None = None) -> float:
    """Where the figures on the panel's cards start: the last 24 hours (older answers stand in when there are none, engines_today). From midnight they would stand empty at 00:01 for someone working through it, and they did."""
    return (now if now is not None else time.time()) - 86400


def _note_today(rec: dict) -> None:
    kind = rec.get("event")
    if kind in ("analysis_done", "followup_done") and rec.get("type") != "none":
        pass
    elif kind == "verify_done":                  # the agent checking a local answer: its tokens and cost, no answer of its own
        rec = {**rec, "engine": "agent"}
    elif kind in ("analysis_error", "followup_error"):
        pass
    else:
        return
    _today.append({k: rec[k] for k in _TODAY_FIELDS if k in rec})
    del _today[:-_TODAY_KEEP]


def take_up_today(path: Path | None = None) -> None:
    """Read today's answers back from the event log's tail: a restart keeps the day's figures."""
    path = path or (Path(LOG_DIR) / "events.jsonl" if LOG_DIR else None)
    if path is None:
        return
    since = _midnight()
    lines: list[str] = []
    # The file before it first: a log that rotated this morning holds the start of the day
    for one in (Path(f"{path}.1"), Path(path)):
        try:
            with open(one, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 4_000_000))   # a day's worth by far, and no more whatever the file has grown to
                lines += f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
    _today.clear()
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:          # the first line of the tail is cut, and one broken line is no reason to lose the rest
            continue
        if isinstance(rec, dict):
            _note_today(rec)


def _rate(r: dict) -> float | None:
    """Tokens a second of one answer, from its first token to its end: the wait before the first is the TTFT's to say. Not the agent's: it thinks before the first word it shows, and
    those tokens are counted in tokens_out, so over the time after the first word it came to 155 tokens/s. Its rate is over the whole answer."""
    tokens, elapsed, first = r.get("tokens_out"), r.get("elapsed"), r.get("first_token")
    if not (isinstance(tokens, (int, float)) and tokens > 0 and isinstance(elapsed, (int, float)) and isinstance(first, (int, float))):
        return None
    spent = elapsed if r.get("engine") == "agent" else elapsed - first
    return tokens / spent if spent >= 0.2 else None     # less says more about the clock than about the model


def engines_today(now: float | None = None) -> dict:
    """Today's figures of each engine, and its latest answers for the panel to draw."""
    since = _midnight(now)
    out = {}
    for engine in ("local", "agent"):
        mine = [r for r in _today if r.get("engine") == engine]
        rows = [r for r in mine if float(r.get("ts") or 0) >= since]
        done = [r for r in rows if r.get("event") in ("analysis_done", "followup_done")]
        window = "24h"
        # None in the last day: the last answers it gave, said as such, rather than a card with no figures, so the
        # local model's card shows how it performs too
        if not done:
            older = [r for r in mine if r.get("event") in ("analysis_done", "followup_done")][-20:]
            if older:
                first = float(older[0].get("ts") or 0)
                rows = [r for r in mine if float(r.get("ts") or 0) >= first]
                done, window = older, "recent"
        elapsed = [r["elapsed"] for r in done if isinstance(r.get("elapsed"), (int, float))]
        ttft = [r["first_token"] for r in done if isinstance(r.get("first_token"), (int, float))]
        rates = [v for v in (_rate(r) for r in done) if v is not None]
        errors = [r for r in rows if r.get("event") in ("analysis_error", "followup_error")]
        priced = [r for r in rows if not r.get("event", "").endswith("_error")]
        out[engine] = {"answers": len(done), "window": window, "last": done[-1].get("ts") if done else None,
                       "errors": len(errors), "last_error": errors[-1]["ts"] if errors else None,
                       "tokens_in": sum(r.get("tokens_in") or 0 for r in priced), "tokens_out": sum(r.get("tokens_out") or 0 for r in priced),
                       "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in priced), 4),
                       "elapsed_p50": _pct(elapsed, 50), "first_token_avg": round(sum(ttft) / len(ttft), 1) if ttft else None,
                       "tps_avg": round(sum(rates) / len(rates), 1) if rates else None,
                       "recent": [{"ts": r.get("ts"), "elapsed": r.get("elapsed"), "first_token": r.get("first_token"),
                                   "tps": round(v, 1) if (v := _rate(r)) is not None else None} for r in done[-24:]]}
    return out


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 2)


def totals() -> dict:
    """Usage since the server started, plus recent response times (for the panel)."""
    done = [r for r in _recent if r["event"] in ("analysis_done", "followup_done")]
    elapsed = [r["elapsed"] for r in done if isinstance(r.get("elapsed"), (int, float))]
    ttft = [r["first_token"] for r in done if isinstance(r.get("first_token"), (int, float))]
    errors = sum(v for k, v in counts.items() if k.startswith("error_"))
    rates = [v for v in (_rate(r) for r in done) if v is not None]
    return {**_totals, "cost_usd": round(_totals["cost_usd"], 4), "errors": errors,
            "elapsed_p50": _pct(elapsed, 50), "first_token_p50": _pct(ttft, 50),
            "first_token_avg": round(sum(ttft) / len(ttft), 1) if ttft else None,
            "tps_avg": round(sum(rates) / len(rates), 1) if rates else None,
            "engines": engines_today(),
            "last_error": {k: last_error[k] for k in ("ts", "hint", "error") if k in last_error} if last_error else None}


def snapshot() -> dict:
    done = [r for r in _recent if r["event"] in ("analysis_done", "followup_done")]
    elapsed = [r["elapsed"] for r in done if isinstance(r.get("elapsed"), (int, float))]
    ttft = [r["first_token"] for r in done if isinstance(r.get("first_token"), (int, float))]
    return {
        "uptime_s": round(time.time() - STARTED),
        "counts": dict(counts),
        "totals": totals(),
        "recent": {"n": len(done), "elapsed_p50": _pct(elapsed, 50), "elapsed_p90": _pct(elapsed, 90),
                   "first_token_p50": _pct(ttft, 50), "first_token_p90": _pct(ttft, 90),
                   "cost_usd": round(sum(r.get("cost_usd") or 0 for r in done), 4)},
        "last_error": last_error,
        "logs": disk_usage(),
    }
