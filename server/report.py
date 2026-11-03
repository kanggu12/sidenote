"""Monitoring from the command line (./sidenote stats | events | report), run inside the image.

  python -m server.report stats [--json]              live numbers from the running server
  python -m server.report events [-n N] [--errors]    the latest events from events.jsonl (--errors: the failures and
                                                      what held work back, the spend brake and a stuck model server)
  python -m server.report report [--days D] [--json]  per-day summary of the event log, and the period's by engine

The event log is SIDENOTE_LOG_DIR/events.jsonl plus its rotated files (events.jsonl.1 ...). It prints in the terminal's
language: SIDENOTE_LANG, else Korean for a Korean locale, else English (i18n.cli_lang).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from . import i18n
from .i18n import t

LOG_DIR = Path(os.environ.get("SIDENOTE_LOG_DIR", "/data/logs"))
PORT = os.environ.get("SIDENOTE_PORT", "8777")


def _events() -> list[dict]:
    """All events, oldest first (rotated files are older: .4 before .3 ... before the live one)."""
    files = sorted(LOG_DIR.glob("events.jsonl.*"), key=lambda f: -int(f.suffix[1:]) if f.suffix[1:].isdigit() else 0)
    files.append(LOG_DIR / "events.jsonl")
    out = []
    for f in files:
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _when(ts: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))


def cmd_stats(args) -> int:
    try:
        snap = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/stats", timeout=5).read())
    except Exception as exc:
        print(t("Cannot reach the server ({why}) · ./sidenote up", why=exc))
        return 1
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    totals, r, c = snap.get("totals", {}), snap.get("recent", {}), snap.get("capture", {})
    up = snap.get("uptime_s", 0)
    print(t("Up {h} h {m} min  analyzer {analyzer}  {agent} {auth}  paused {paused}", h=up // 3600,
            m=up % 3600 // 60, analyzer=snap.get("analyzer"), agent=snap.get("agent_label") or t("Agent"),
            auth=t("signed in") if snap.get("auth", {}).get("ok") else t("sign-in needed"),
            paused=t("yes") if snap.get("paused") else t("no")))
    print(t("Capture programs {n}  screen {screen}  sound {sound}  device {device}", n=c.get("clients", 0),
            screen=t("on") if c.get("screen_on") else t("off"), sound=t("on") if c.get("audio_on") else t("off"),
            device=c.get("caps", {}).get("audio_device") or "-"))
    if c.get("last_frame"):
        print(t("Last screen {when}", when=_when(c["last_frame"])))
    empty = t(" (screens with nothing to solve, apart: {n})", n=totals["empty"]) if totals.get("empty") else ""
    print(t("Answers {answers}{empty}  errors {errors}  tokens in {tin} / out {tout}  cost ${cost}",
            answers=totals.get("answers", 0), empty=empty, errors=totals.get("errors", 0),
            tin=f"{totals.get('tokens_in', 0):,}", tout=f"{totals.get('tokens_out', 0):,}",
            cost=f"{totals.get('cost_usd', 0):.4f}"))
    sec = lambda v: "-" if v is None else t("{v} s", v=v)
    if r.get("n"):
        print(t("Last {n}: response median {p50}, 90% {p90}, median to the first token {first}", n=r["n"],
                p50=sec(r.get("elapsed_p50")), p90=sec(r.get("elapsed_p90")), first=sec(r.get("first_token_p50"))))
    else:
        print(t("Recent responses: none yet"))
    counts = snap.get("counts", {})
    print(t("Counts: {list}", list=", ".join(f"{k} {v}" for k, v in sorted(counts.items()))))
    if snap.get("last_error"):
        e = snap["last_error"]
        print(t("Last error {when} [{hint}] {error}", when=_when(e["ts"]), hint=e.get("hint") or t("other"),
                error=e.get("error", "")[:200]))
    lg = snap.get("logs", {})
    if lg.get("dir"):
        print(t("Log files: {files}, {mb} MB (cap {cap} MB, rotated ones kept for {days} days)", files=lg["files"],
                mb=f"{lg['bytes'] / 1048576:.1f}", cap=f"{lg['cap_bytes'] / 1048576:.0f}",
                days=f"{lg['keep_days']:.0f}"))
    return 0


def _line(e: dict) -> str:
    k = e.get("event", "")
    bits = [_when(e.get("ts", 0)), k]
    # reason, after, of and score say why an analysis was stopped and which answer a problem seen again was (they
    # were in the log and left out here, so `events` read as if no cancel said why); engine and via say who answered
    # and why the agent got it
    for f in ("id", "trigger", "type", "reason", "after", "of", "score", "wait", "until", "elapsed", "first_token",
              "engine", "via", "cost_usd", "hint", "action", "screen", "audio", "sound", "paused", "no_audio", "lang",
              "frames", "ok", "method", "peer", "path", "origin"):
        if e.get(f) is not None:
            bits.append(f"{f}={e[f]}")
    for f in ("answer", "question", "spoken", "sent", "error", "info", "audio_device"):
        if e.get(f):
            bits.append(f"{f}={str(e[f])[:90]!r}")
    return "  ".join(str(b) for b in bits)


# What --errors shows besides the *_error events: the times work was held back rather than failed, which belong in
# the same place when the question is why nothing got solved (the spend brake, a model server that stopped
# answering and was restarted).
HELD = ("agent_brake", "agent_limit", "local_stuck")


def cmd_events(args) -> int:
    ev = _events()
    if args.errors:
        ev = [e for e in ev if e.get("event", "").endswith("_error") or e.get("event") in HELD]
    for e in (ev[-args.n:] if args.n > 0 else []):   # -n 0 shows nothing (ev[-0:] would be all)
        print(_line(e))
    if not ev:
        print(t("No records") if LOG_DIR.is_dir() else t("No log folder: {dir}", dir=LOG_DIR))
    return 0


def cmd_report(args) -> int:
    # Whole calendar days: --days 7 is today and the six days before it, each from midnight.
    now = time.localtime()
    since = time.mktime((now.tm_year, now.tm_mon, now.tm_mday - (args.days - 1), 0, 0, 0, 0, 0, -1))
    days: dict[str, dict] = defaultdict(lambda: {"answers": 0, "empty": 0, "followups": 0, "cancelled": 0, "errors": Counter(),
                                                 "elapsed": [], "first_token": [], "cost": 0.0, "types": Counter()})
    for e in _events():
        if e.get("ts", 0) < since:
            continue
        d = days[time.strftime("%Y-%m-%d", time.localtime(e["ts"]))]
        k = e.get("event")
        if k in ("analysis_done", "followup_done"):
            d["cost"] += e.get("cost_usd") or 0
            if e.get("type") == "none":   # nothing on screen to solve: not an answer, not in the medians
                d["empty"] += 1
                continue
            d["answers" if k == "analysis_done" else "followups"] += 1
            if isinstance(e.get("elapsed"), (int, float)):
                d["elapsed"].append(e["elapsed"])
            if isinstance(e.get("first_token"), (int, float)):
                d["first_token"].append(e["first_token"])
            if e.get("type"):
                d["types"][e["type"]] += 1
        elif k == "verify_done":   # the agent checking a local answer (verify mode): its cost only
            d["cost"] += e.get("cost_usd") or 0
        elif k == "analysis_cancelled":
            d["cancelled"] += 1
        elif k and k.endswith("_error"):
            d["errors"][e.get("hint") or "other"] += 1
    period = _period(since)
    rows = []
    for day in sorted(days):
        d = days[day]
        med = lambda v: round(statistics.median(v), 2) if v else None
        rows.append({"day": day, "answers": d["answers"], "empty": d["empty"], "followups": d["followups"], "cancelled": d["cancelled"],
                     "errors": dict(d["errors"]), "elapsed_median": med(d["elapsed"]),
                     "first_token_median": med(d["first_token"]), "cost_usd": round(d["cost"], 4), "types": dict(d["types"])})
    if args.json:
        print(json.dumps({"days": rows, "period": period}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(t("No records in the last {n} day(s)", n=args.days))
        return 0
    # a time with its unit, as stats writes it (the medians are seconds); 0.0 is a value, not "none"
    sec = lambda v: "-" if v is None else t("{v} s", v=v)
    cols = [("Date", 10, False), ("Answers", 4, True), ("Follow-ups", 4, True), ("Empty screens", 7, True),
            ("Cancelled", 4, True), ("Errors", 4, True), ("Response (median)", 10, True),
            ("First token (median)", 6, True), ("Cost", 9, True)]
    # each heading in the terminal's language, its column as wide as the heading where that is wider
    cols = [(t(name), max(w, _width(t(name))), right) for name, w, right in cols]
    print("  ".join(_pad(name, w, right) for name, w, right in cols) + "  " + t("Types"))
    for r in rows:
        vals = [r["day"], r["answers"], r["followups"], r["empty"], r["cancelled"], sum(r["errors"].values()),
                sec(r["elapsed_median"]), sec(r["first_token_median"]), f"${r['cost_usd']:.4f}"]
        print("  ".join(_pad(v, w, right) for v, (_, w, right) in zip(vals, cols)) + "  "
              + ", ".join(f"{k} {v}" for k, v in sorted(r["types"].items(), key=lambda x: -x[1])))
    _print_period(period)
    return 0


def _pct(values: list, p: float):
    """The value p of the way up the sorted values (nearest rank): p 0.5 the median's place, p 0.9 the slow tail."""
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, max(0, -(-int(p * 100) * len(v) // 100) - 1))], 2)


def _period(since: float) -> dict:
    """The whole period at once, what a day's medians hide: how long each engine took to its first word (the median
    and the slow tenth), what the agent was paid for answers and for screens with nothing to solve, how often the GPU was
    found busy and the local model gave nothing in time, how often its server answered nothing at all and was started
    again (local_stuck), and what the example checks concluded, a check that read examples and left them all out (none
    of them in the problem's text after an example heading) apart from one that found none. Counted by hand once
    to find where real use went slow and where the money went; needed again, so made a report."""
    first: dict[tuple, list] = defaultdict(list)   # (engine, spoken) -> first-token times; named when printed
    cost = {"answers": 0.0, "empty": 0.0, "empty_turns": 0, "headless": 0.0, "headless_turns": 0, "followups": 0.0}
    # the agent's turns that found nothing, by what it was given (empty_sent) and why it got them (empty_via)
    empty_sent: Counter = Counter()
    empty_via: Counter = Counter()
    # why analyses stopped before their answer, and how long the ones a newer screen replaced had run by then: time
    # spent on an answer nobody saw (superseded)
    cancels: Counter = Counter()
    lost: list = []
    # problems seen again and not solved again (design 88): how many, of how many answers, and their scores
    repeats: list = []
    repeat_cards: set = set()
    gpu_busy = timeouts = stuck = stuck_failed = 0
    checks = Counter()
    for e in _events():
        if e.get("ts", 0) < since:
            continue
        k = e.get("event")
        if k == "analysis_done":
            if e.get("type") == "none":
                if e.get("cost_usd"):
                    cost["empty"] += e["cost_usd"]
                    cost["empty_turns"] += 1
                    empty_sent[_shape(e.get("sent"), e.get("trigger"))] += 1
                    empty_via[e.get("via") or "none"] += 1   # "unknown" is a via of its own (kind unread)
                continue
            if not e.get("type"):   # no head: a refusal, or a turn that ran away (923 s and $3.50 once)
                cost["headless"] += e.get("cost_usd") or 0
                cost["headless_turns"] += 1
            else:
                cost["answers"] += e.get("cost_usd") or 0
            if isinstance(e.get("first_token"), (int, float)):
                # "claude": how the agent's answers were recorded while it could only be Claude
                engine = {"agent": 0, "claude": 0, "local": 1}.get(e.get("engine"), 2)
                first[(engine, e.get("trigger") == "voice")].append(e["first_token"])
        elif k == "followup_done":
            cost["followups"] += e.get("cost_usd") or 0
        elif k == "analysis_cancelled":
            # cancels logged by an earlier server have no reason
            cancels[e.get("reason") or "unknown"] += 1
            if e.get("reason") == "superseded" and isinstance(e.get("after"), (int, float)):
                lost.append(e["after"])
        elif k == "analysis_repeat":
            if isinstance(e.get("score"), (int, float)):
                repeats.append(e["score"])
            repeat_cards.add(e.get("of"))
        elif k == "gpu_busy":
            gpu_busy += 1
        elif k == "analysis_error" and e.get("hint") == "timeout":
            timeouts += 1
        elif k == "local_stuck":   # taken off and started again, or found stuck and not taken off
            if e.get("unloaded"):
                stuck += 1
            else:
                stuck_failed += 1
        elif k == "check" and e.get("probe"):   # run on made-up inputs, the problem showing no examples
            # (an error before any input ran has neither count: it is a failed run, not a clean one)
            checks["probe_ran" if e.get("passed") is not None and e.get("passed") == e.get("total")
                   else "probe_failed"] += 1
            checks["no_examples"] += 1
        elif k == "check":
            checks["passed" if e.get("passed") is not None and e.get("passed") == e.get("total") else
                   "failed" if e.get("passed") is not None else "no_examples" if e.get("none") else
                   "skipped" if e.get("skipped") else "error" if e.get("error") else "other"] += 1
            if e.get("none") and e.get("read") and not e.get("kept"):   # read off the screen, then all left out
                checks["left_out"] += 1
    # one line for each engine and way in, in the same order in every language: sorted by the translated words, the
    # Korean put speech before screen. The agent, the local model, then what was not recorded; screens, then speech.
    label = lambda engine, voice: (
        f"{t('Agent') if engine == 0 else t('Local model') if engine == 1 else t('not recorded')}, "
        f"{t('speech') if voice else t('screen')}")
    return {"first_token": {label(*way): {"n": len(v), "p50": _pct(v, .5), "p90": _pct(v, .9)}
                            for way, v in sorted(first.items())},
            "cost_usd": {k: round(v, 4) if isinstance(v, float) else v for k, v in cost.items()},
            "gpu_busy": gpu_busy, "local_timeouts": timeouts, "local_stuck": stuck, "local_stuck_failed": stuck_failed,
            "checks": dict(checks),
            "empty_by_sent": dict(empty_sent.most_common()), "empty_by_via": dict(empty_via.most_common()),
            "cancelled": dict(cancels.most_common()),
            "superseded_after": {"n": len(lost), "p50": _pct(lost, .5), "p90": _pct(lost, .9),
                                 "over_10s": sum(1 for v in lost if v > 10), "total_s": round(sum(lost))},
            "repeats": {"n": len(repeats), "answers": len(repeat_cards - {None}),
                        "min": round(min(repeats), 3) if repeats else None, "p50": _pct(repeats, .5)}}


# What a cancel's reason is called in the report (through t() when printed)
CANCEL_NAMES = {"superseded": "new screen", "voice": "spoken problem", "reanalyze": "reanalyze", "pause": "pause",
                "screen_off": "screen off", "sound_off": "sound off", "local_off": "model off", "repeat": "same problem",
                "gpu_busy": "GPU busy", "not_sent": "not sent", "unknown": "no reason recorded"}
# why the agent was given a problem (pipeline.solve, stages["why"])
VIA_NAMES = {"handoff": "first pass slow", "unknown": "type not read", "slow": "local model slow",
             "kind": "type handed over", "all": "all handed over", "only": "agent only", "none": "not recorded"}


def _shape(sent, trigger) -> str:
    """What the agent was given, in a few kinds, from the payload's own words (pipeline._agent_payload), which are
    Korean or English as the server's language was when they were logged."""
    s = (sent or "").lower()
    if "이어 붙인" in s or "joined problem" in s:
        return t("joined problem")
    if "문제 부분" in s or "영역" in s or "problem area" in s or "region" in s:
        return t("cut-out screen")
    if "문제 글" in s or "problem text" in s:
        return t("written-out text")
    if "화면 전체" in s or "whole screen" in s:
        return t("whole screen")
    if "들은 질문" in s or "heard question" in s or trigger == "voice":
        return t("heard speech")
    return t("not recorded")


def _print_period(period: dict) -> None:
    print("\n  " + t("The whole period"))
    wide = max((_width(way) for way in period["first_token"]), default=0)   # Hangul takes two columns
    for way, f in period["first_token"].items():
        print("  " + t("First token  {way}   answers {n}   median {p50} s   slowest 10% {p90} s", way=_pad(way, wide),
                       n=f"{f['n']:>3}", p50=f["p50"], p90=f["p90"]))
    c = period["cost_usd"]
    print("  " + t("Agent cost  answers ${answers}   follow-ups ${followups}   screens with nothing to solve ${empty} "
                   "(count {empty_n})   answers with no head line ${headless} (count {headless_n})",
                   answers=f"{c['answers']:.2f}", followups=f"{c['followups']:.2f}", empty=f"{c['empty']:.2f}",
                   empty_n=c["empty_turns"], headless=f"{c['headless']:.2f}", headless_n=c["headless_turns"]))
    if period.get("empty_by_sent"):
        via = period.get("empty_by_via") or {}
        print("  " + t("Agent answers with nothing to solve  sent: {sent}   why handed over: {via}",
                       sent=", ".join(f"{k} {v}" for k, v in period["empty_by_sent"].items()),
                       via=", ".join(f"{t(VIA_NAMES[k]) if k in VIA_NAMES else k} {v}" for k, v in via.items())))
    if period.get("cancelled"):
        lost = period["superseded_after"]
        tail = ("   " + t("analyses a new screen replaced: median {p50} s, slowest 10% {p90} s, over 10 s: {over} "
                          "({total} s in all)", p50=lost["p50"], p90=lost["p90"], over=lost["over_10s"],
                          total=lost["total_s"])) if lost["n"] else ""
        print("  " + t("Cancelled  {list}", list=", ".join(f"{t(CANCEL_NAMES[k]) if k in CANCEL_NAMES else k} {v}"
                                                         for k, v in period["cancelled"].items())) + tail)
    rp = period.get("repeats") or {}
    print("  " + t("Same problem not solved again  count {n} (answers: {answers})", n=rp.get("n", 0),
                   answers=rp.get("answers", 0))
          + ("   " + t("lowest score {min}, median {p50}", min=rp["min"], p50=rp["p50"]) if rp.get("n") else ""))
    ch = period["checks"]
    # of the checks with no examples, those that read some and found none of them in the problem's text. Each aside
    # brings its own space: English puts one before a bracket after a number, Korean writes the bracket close to it.
    left = t(" (read but not in the problem's text, left out: {n})", n=ch["left_out"]) if ch.get("left_out") else ""
    failed = (t(" (could not be taken off: {n})", n=period["local_stuck_failed"])
              if period.get("local_stuck_failed") else "")
    print("  " + t("GPU busy: {gpu}   the local model timed out: {timeouts}   stuck and loaded again: {stuck}{failed}   "
                   "example checks: passed {passed}, failed {failed_n}, no examples {none}{left}, not run "
                   "{not_run}", gpu=period["gpu_busy"], timeouts=period["local_timeouts"],
                   stuck=period.get("local_stuck", 0), failed=failed, passed=ch.get("passed", 0),
                   failed_n=ch.get("failed", 0), none=ch.get("no_examples", 0), left=left,
                   not_run=ch.get("skipped", 0) + ch.get("error", 0))
          + ("   " + t("run on made-up inputs {probes} (errors among them {probe_errors})",
                       probes=ch.get("probe_ran", 0) + ch.get("probe_failed", 0), probe_errors=ch.get("probe_failed", 0))
             if ch.get("probe_ran") or ch.get("probe_failed") else ""))


def _width(value) -> int:
    """How many terminal columns a value takes: Hangul takes two."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(value))


def _pad(value, width: int, right: bool = False) -> str:
    """Pad to a terminal width: Hangul takes two columns, so str.rjust() misaligns a Korean header."""
    s = str(value)
    fill = " " * max(0, width - _width(s))
    return fill + s if right else s + fill


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sidenote")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stats"); s.add_argument("--json", action="store_true")
    e = sub.add_parser("events"); e.add_argument("-n", type=int, default=30); e.add_argument("--errors", action="store_true")
    r = sub.add_parser("report"); r.add_argument("--days", type=int, default=7); r.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    i18n.set_lang(i18n.cli_lang())   # a terminal's language, not a panel's
    return {"stats": cmd_stats, "events": cmd_events, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
