"""The Maintenance sheet's server side (server/maintenance.py, docs/API.md): the checks worked out from the facts, the
events and the server's log read from their ends, the local server's models put together, and a backup that is the
file ./sidenote backup writes; then the routes, as a program and the panel call them.

    .venv/bin/python tests/maintenance_check.py

Checked:
  checks   each part's state and words from made-up facts: the capture program off by where the server runs, another
           release, a screen that does not come, speech off or failed, the local model off, missing or not answering,
           the agent signed out or at its limit, the disk nearly full, the GPU full, errors of the last day
  log      the newest events first across a rotated file, the failures alone, a limit, a time before which none come,
           a cut line skipped; the server log's last lines in their order
  models   Ollama's list and what is on the GPU put together, the models in use marked, the offered ones not there after
  backup   the archive's names and kinds (plain files only, sidenote-backup.txt first line), the history copied whole
           with Recently deleted left out and nothing of it left in the file, one file with no -wal, the settings as
           they were; a link in place of the settings refused; nothing to back up said
  routes   /api/v1/check, /report, /log, /log/server, /models (503 with no Ollama), DELETE /models/x (404), POST /backup (the file,
           with what it holds in its headers, its folder gone after it is sent); another site's page refused, a write
           that is not JSON refused
"""
import io
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

LOGS = tempfile.mkdtemp(prefix="sidenote-maint-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_AGENT="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=LOGS, SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="",
                  SIDENOTE_LOCAL_PULL="0", SIDENOTE_UPDATE_CHECK="0")
os.environ.pop("SIDENOTE_LANG", None)   # the checks' words are read in English here
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server import maintenance as M  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:500]}" if detail != "" and not ok else ""))


def by_id(rows):
    return {r["id"]: r for r in rows}


# A server where everything stands well, as maintenance_facts in server/app.py gathers it
GOOD = {
    "version": "0.9.1", "update": None, "where": "container",
    "capture": {"clients": 1, "who": {"host": "DESKTOP-7Q2KD", "system": "Windows 11", "version": "0.9.1"},
                "screen_on": True, "audio_on": True, "frame_age": 2.0},
    "speech": {"enabled": True, "available": True, "failed": False, "model": "large-v3-turbo", "live": "small"},
    "local": {"present": True, "on": True, "ok": True, "model": "sidenote-gemma4:26b", "loaded": {"model": "x"}, "pull": True},
    "agent": {"present": True, "mode": "hard", "ok": True, "installed": True, "label": "Claude", "model": "claude-opus-5-5"},
    "search": {"present": True, "on": True}, "runner": True,
    "disk": {"free": 120 * 1024 ** 3, "history": 12 * 1024 ** 2, "history_cap": 200.0},
    "gpu": {"used": 16200, "total": 23028, "util": 41}, "errors_day": 0,
}


def facts(**changes):
    """GOOD with some parts changed: a part given as a dict replaces that part's keys it names"""
    out = json.loads(json.dumps(GOOD))
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


print("[the checks]")
rows = M.checks(GOOD)
check("every part is checked, in the setup guide's order", [r["id"] for r in rows] == ["server", "capture", "screen", "speech", "local",
      "agent", "search", "runner", "disk", "gpu", "errors"], [r["id"] for r in rows])
check("...and a server where everything stands well is all ok", all(r["state"] == "ok" for r in rows), [(r["id"], r["state"]) for r in rows])
check("...each saying what it found: the program's PC, the speech models, the disk and the history", "DESKTOP-7Q2KD" in by_id(rows)["capture"]["said"]
      and "large-v3-turbo" in by_id(rows)["speech"]["said"] and "small" in by_id(rows)["speech"]["said"]
      and "120.0 GB free" in by_id(rows)["disk"]["said"] and "history 12 of 200 MB" in by_id(rows)["disk"]["said"], [r["said"] for r in rows])
off = by_id(M.checks(facts(capture={"clients": 0})))
check("no capture program: a fault, started in the server's terminal where the server is a container",
      off["capture"]["state"] == "bad" and off["capture"]["cmd"] == "./sidenote capture" and off["screen"]["state"] == "idle", off["capture"])
check("...on your PC for a cluster, and by starting the app again under the app",
      by_id(M.checks(facts(where="cluster", capture={"clients": 0})))["capture"]["cmd"] == ""
      and "your PC" in by_id(M.checks(facts(where="cluster", capture={"clients": 0})))["capture"]["fix"]
      and "Quit Sidenote" in by_id(M.checks(facts(where="desktop", capture={"clients": 0})))["capture"]["fix"])
other = by_id(M.checks(facts(capture={"who": {"host": "PC", "version": "0.8.0"}})))
check("a program of another release: a warning naming both, and to restart it", other["capture"]["state"] == "warn"
      and "0.8.0" in other["capture"]["said"] and "0.9.1" in other["capture"]["said"] and "Restart" in other["capture"]["fix"], other["capture"])
# A program sends a screen when a change settles, and none while nothing changes: a still screen is no fault
still = by_id(M.checks(facts(capture={"frame_age": 400.0, "connected_for": 3600.0})))["screen"]
check("a still screen, its last one minutes ago: fine, said in minutes", still["state"] == "ok" and still["said"] == "Last screen 6 min ago", still)
check("...or hours", by_id(M.checks(facts(capture={"frame_age": 9000.0, "connected_for": 99999.0})))["screen"]["said"] == "Last screen 2 h ago")
none = by_id(M.checks(facts(capture={"frame_age": None, "connected_for": 120.0})))["screen"]
check("a program connected for minutes that has sent no screen: a warning, with what to look at", none["state"] == "warn"
      and none["said"] == "No screen since it connected" and "monitor" in none["fix"], none)
check("...nor one since it connected, the last from an earlier program", by_id(M.checks(facts(capture={"frame_age": 500.0,
      "connected_for": 90.0})))["screen"]["state"] == "warn")
check("...one connected a moment ago is waiting for its first", by_id(M.checks(facts(capture={"frame_age": None,
      "connected_for": 10.0})))["screen"]["state"] == "idle")
skipping = by_id(M.checks(facts(capture={"frame_age": None, "connected_for": 600.0, "skipping": True})))["screen"]
check("a window of Skip windows on screen, so no screen comes: waiting, said, no fault", skipping["state"] == "idle"
      and skipping["said"] == "A window of Skip windows is on screen", skipping)
check("the screen switched off is no fault", by_id(M.checks(facts(capture={"screen_on": False})))["screen"]["state"] == "off")
sp = by_id(M.checks(facts(speech={"enabled": False})))
check("speech off on the server: off, with the variable that turns it on", sp["speech"]["state"] == "off" and "SIDENOTE_AUDIO=1" in sp["speech"]["fix"], sp["speech"])
check("...or with no transcriber, the one that gives it one", "SIDENOTE_TRANSCRIBER=auto" in by_id(M.checks(facts(speech={"enabled": False, "transcriber": "null"})))["speech"]["fix"])
failed = by_id(M.checks(facts(speech={"available": False, "failed": True})))
check("a speech model that did not load: a fault, and a key to the log", failed["speech"]["state"] == "bad" and failed["speech"]["go"] == "log", failed["speech"])
check("...one still loading is not", by_id(M.checks(facts(speech={"available": False})))["speech"]["state"] == "idle")
missing = by_id(M.checks(facts(local={"missing": True, "want": "sidenote-gemma4:26b"})))
check("the local model not downloaded: a fault, downloaded in Models where the panel may", missing["local"]["state"] == "bad"
      and missing["local"]["go"] == "models" and "26b" in missing["local"]["said"], missing["local"])
check("...in the server's terminal where it may not", by_id(M.checks(facts(local={"missing": True, "pull": False})))["local"]["cmd"] == "./sidenote llm pull")
both = by_id(M.checks(facts(local={"missing": True, "want": ["sidenote-gemma4:26b", "gemma4:e4b"]})))["local"]
check("...the models it wants, a list, said as words", both["said"] == "sidenote-gemma4:26b, gemma4:e4b not downloaded", both["said"])
nocap = by_id(M.checks(facts(disk={"free": 120 * 1024 ** 3, "history": 3 * 1024 ** 2, "history_cap": 0})))["disk"]
check("a history with no limit (0): its size alone", nocap["said"].endswith("history 3 MB"), nocap["said"])
down = by_id(M.checks(facts(local={"ok": False})))
check("a local server that does not answer: a fault, with ./sidenote up", down["local"]["state"] == "bad" and down["local"]["cmd"] == "./sidenote up", down["local"])
check("the local model switched off, or not in this server: off, no fault", by_id(M.checks(facts(local={"on": False})))["local"]["state"] == "off"
      and by_id(M.checks(facts(local={"present": False})))["local"]["state"] == "off")
signed = by_id(M.checks(facts(agent={"ok": False, "login": "claude login"})))
check("the agent signed out: a warning with the command that signs it in", signed["agent"]["state"] == "warn" and signed["agent"]["cmd"] == "claude login", signed["agent"])
limit = by_id(M.checks(facts(agent={"limit_until": time.time() + 3600})))
check("...at its plan's limit: a warning saying until when", limit["agent"]["state"] == "warn" and "until" in limit["agent"]["said"], limit["agent"])
check("...not installed, or switched off: no fault", by_id(M.checks(facts(agent={"ok": False, "installed": False})))["agent"]["state"] == "off"
      and by_id(M.checks(facts(agent={"mode": "off"})))["agent"]["state"] == "off")
full = by_id(M.checks(facts(disk={"free": 0.5 * 1024 ** 3})))
check("under 1 GB free: a fault; under 5 GB a warning", full["disk"]["state"] == "bad"
      and by_id(M.checks(facts(disk={"free": 3 * 1024 ** 3})))["disk"]["state"] == "warn", full["disk"])
check("the GPU nearly full: a warning; no reading: unknown", by_id(M.checks(facts(gpu={"used": 22900, "total": 23028})))["gpu"]["state"] == "warn"
      and by_id(M.checks(facts(gpu=None)))["gpu"]["state"] == "idle")
errs = by_id(M.checks(facts(errors_day=3)))
check("errors in the last day: a warning counting them, and a key to the log", errs["errors"]["state"] == "warn" and "3" in errs["errors"]["said"]
      and errs["errors"]["go"] == "log", errs["errors"])
newer = by_id(M.checks(facts(update={"version": "0.10.0"})))
check("a newer release: the server's check says so", newer["server"]["state"] == "warn" and "0.10.0" in newer["server"]["said"], newer["server"])

print("\n[the log, from its end]")
logs = Path(tempfile.mkdtemp(prefix="sidenote-maint-log-"))
now = time.time()
old_lines = [json.dumps({"ts": now - 7200 + i, "event": "analysis_done" if i % 3 else "analysis_error", "id": i}) for i in range(40)]
(logs / "events.jsonl.1").write_text("\n".join(old_lines) + "\n", encoding="utf-8")
new_lines = [json.dumps({"ts": now - 100 + i, "event": "agent_error" if i == 5 else "analysis_done", "id": 1000 + i}) for i in range(30)]
(logs / "events.jsonl").write_text("\n".join(new_lines[:15]) + "\n{\"ts\": 1, \"event\": cut\n" + "\n".join(new_lines[15:]) + "\n", encoding="utf-8")
got = M.recent_events(logs, limit=50)
check("the newest event first, across the rotated file into the older one", got[0]["id"] == 1029 and got[29]["id"] == 1000
      and got[30]["id"] == 39 and len(got) == 50, [e["id"] for e in got[:3]] + [e["id"] for e in got[28:32]])
check("...a line cut by a crash left out", all(isinstance(e.get("id"), int) for e in got))
errors = M.recent_events(logs, errors=True, limit=100)
check("the failures alone: the *_error events, newest first", [e["event"] for e in errors][:2] == ["agent_error", "analysis_error"]
      and all(M.is_error(e) for e in errors) and len(errors) == 1 + 14, [e["event"] for e in errors][:4])
check("...and none before a time asked for", M.recent_events(logs, errors=True, since=now - 3600) == [errors[0]])
check("a limit holds, and at most 1000 are given", len(M.recent_events(logs, limit=5)) == 5 and len(M.recent_events(logs, limit=99999)) == 70)
big = "\n".join(f"2026 INFO line {i}" for i in range(5000))
(logs / "server.log").write_text(big + "\n", encoding="utf-8")
tail = M.log_tail(logs, 3)
check("the server's log: its last lines, in their order", tail == ["2026 INFO line 4997", "2026 INFO line 4998", "2026 INFO line 4999"], tail)
check("...at most 2000", len(M.log_tail(logs, 99999)) == 2000)

print("\n[the models]")
tags = {"models": [{"name": "sidenote-gemma4:26b", "size": 18_000_000_000, "modified_at": "2026-01-02T03:04:05Z",
                    "details": {"family": "gemma4", "parameter_size": "26B", "quantization_level": "Q4_K_M"}},
                   {"name": "gemma4:e2b", "size": 4_600_000_000, "details": {}}]}
ps = {"models": [{"name": "sidenote-gemma4:26b", "size_vram": 16_000_000_000}]}
rows = M.model_rows(tags, ps, {"sidenote-gemma4:26b"}, {"sidenote-gemma4:26b": 18.0, "sidenote-gemma4:e4b": 6.6})
names = [r["name"] for r in rows]
check("Ollama's models with what is on the GPU and what this server uses", rows[0]["loaded"] and rows[0]["in_use"]
      and rows[0]["params"] == "26B" and not rows[1]["loaded"] and not rows[1]["in_use"], rows[:2])
check("...then the offered ones not there, to download, each once", names == ["sidenote-gemma4:26b", "gemma4:e2b", "sidenote-gemma4:e4b"]
      and rows[2]["present"] is False and rows[2]["size_gb"] == 6.6, names)

print("\n[a backup, as ./sidenote backup writes it]")
home = Path(tempfile.mkdtemp(prefix="sidenote-maint-bk-"))
db = sqlite3.connect(home / "history.sqlite")
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE answers (id INTEGER PRIMARY KEY, ts REAL, day TEXT, kind TEXT, words TEXT, data TEXT, starred INTEGER, deleted REAL)")
db.execute("INSERT INTO answers VALUES (1, 1, '2026-01-01', 'essay', 'kept words', '{}', 0, NULL)")
db.execute("INSERT INTO answers VALUES (2, 2, '2026-01-01', 'essay', 'SECRET-DELETED-WORDS', '{}', 0, 5)")
db.commit()                                   # left open, as the server holds it: the copy must still be whole
(home / ".settings.json").write_text('{"local_llm": true}', encoding="utf-8")
mask = os.umask(0o022)
os.umask(mask)                                # what the process's umask is before the backup
archive, made = M.make_backup(home, "0.9.1")
after = os.umask(mask)
check("the backup leaves the process's umask as it was", after == mask, [oct(mask), oct(after)])
check("...its archive this user's alone", (archive.stat().st_mode & 0o777) == 0o600 and (archive.parent.stat().st_mode & 0o777) == 0o700,
      [oct(archive.stat().st_mode & 0o777), oct(archive.parent.stat().st_mode & 0o777)])
with tarfile.open(archive) as tar:
    members = tar.getmembers()
    names = [m.name for m in members]
    first = tar.extractfile("sidenote-backup.txt").read().decode()
    hist = tar.extractfile("history.sqlite").read()
    settings = tar.extractfile(".settings.json").read().decode()
check("the archive holds the launcher's names, plain files only, sidenote-backup.txt among them",
      set(names) == {"history.sqlite", ".settings.json", "sidenote-backup.txt"} and all(m.isfile() for m in members)
      and all("/" not in n for n in names), names)
check("...saying what made it and when", first.startswith("sidenote 0.9.1 ") and first.strip().endswith("Z"), first)
copy = home / "copy.sqlite"
copy.write_bytes(hist)
rows = sqlite3.connect(copy).execute("SELECT id FROM answers").fetchall()
mode = sqlite3.connect(copy).execute("PRAGMA journal_mode").fetchone()[0]
check("the history whole, Recently deleted left out and nothing of it left in the file", rows == [(1,)] and b"SECRET-DELETED-WORDS" not in hist
      and made["left_out"] == 1, [rows, made])
check("...one file, with no -wal to go with it", mode == "delete", mode)
check("the settings as they were", settings == '{"local_llm": true}')
check("the files copied for it are gone, the archive alone left until it is sent", sorted(p.name for p in archive.parent.iterdir()) == ["backup.tar.gz"])
M.remove_backup(archive)
check("...and once sent, its folder too", not archive.parent.exists())
link = Path(tempfile.mkdtemp(prefix="sidenote-maint-link-"))
(link / ".settings.json").symlink_to(home / ".settings.json")
try:
    M.make_backup(link, "0.9.1")
    refused = ""
except ValueError as exc:
    refused = str(exc)
check("a link in place of the settings: no backup", "link" in refused, refused)
check("...and no folder made for it", not list(link.glob(".backup.*")), [x.name for x in link.glob(".backup.*")])
# A copy that fails halfway takes its folder, and the history it may hold, with it
broken = Path(tempfile.mkdtemp(prefix="sidenote-maint-broken-"))
(broken / ".settings.json").write_text("{}", encoding="utf-8")
real_open = M.tarfile.open
M.tarfile.open = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
try:
    M.make_backup(broken, "0.9.1")
    failed = ""
except OSError as exc:
    failed = str(exc)
M.tarfile.open = real_open
check("a backup that fails halfway: said, and nothing of it left in the log folder", failed == "disk full"
      and not list(broken.glob(".backup.*")), [failed, [x.name for x in broken.glob(".backup.*")]])
# A folder whose name holds "#" or "%" (the desktop app keeps its data under the person's own folder): the history found
odd = Path(tempfile.mkdtemp(prefix="sidenote-maint-#odd%41-"))
db2 = sqlite3.connect(odd / "history.sqlite")
db2.execute("CREATE TABLE answers (id INTEGER PRIMARY KEY, seq INTEGER, day TEXT, type TEXT, text TEXT, meta TEXT, star INTEGER, ts INTEGER)")
db2.execute("INSERT INTO answers VALUES (7, 7, '2026-01-01', 'code', 'kept', '{}', 0, 5)")
db2.commit()
db2.close()
oddarch, _ = M.make_backup(odd, "0.9.1")
with tarfile.open(oddarch) as tar:
    (odd / "copy.sqlite").write_bytes(tar.extractfile("history.sqlite").read())
oddrows = sqlite3.connect(odd / "copy.sqlite").execute("SELECT id FROM answers").fetchall()
check("a data folder whose name holds # and %: its history in the backup, whole", oddrows == [(7,)], oddrows)
M.remove_backup(oddarch)
# Sent in blocks, the archive goes after the last, or when the download stops first
sent_arch, _ = M.make_backup(odd, "0.9.1")
blocks = M.stream_backup(sent_arch, block=64)
next(blocks)
blocks.close()                                            # the download cut short
check("a download stopped after its first block: the archive and its folder gone", not sent_arch.parent.exists(),
      [x.name for x in odd.iterdir()])
# What a stopped server left: swept as the next one starts, a file of the same name kept
left = Path(tempfile.mkdtemp(prefix=".backup.", dir=odd))
(left / "backup.tar.gz").write_bytes(b"x")
(odd / ".backup.sqlite").write_bytes(b"not a folder")
gone = M.sweep_backups(odd)
check("backup folders a stopped server left: swept as the server starts, a file of that name kept", gone == 1 and not left.exists()
      and (odd / ".backup.sqlite").exists(), [gone, [x.name for x in odd.iterdir()]])
try:
    M.make_backup(Path(tempfile.mkdtemp(prefix="sidenote-maint-empty-")), "0.9.1")
    said = ""
except FileNotFoundError as exc:
    said = str(exc)
check("nothing to back up: said", "Nothing to back up" in said, said)

print("\n[the routes]")
sys.path.insert(0, str(ROOT / "tests"))
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

SETTINGS.path = None
ORIGIN = {"origin": "http://127.0.0.1:8777"}
(Path(LOGS) / "events.jsonl").write_text(json.dumps({"ts": time.time(), "event": "analysis_error", "hint": "timeout"}) + "\n", encoding="utf-8")
(Path(LOGS) / ".settings.json").write_text("{}", encoding="utf-8")
with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    r = c.get("/api/v1/check", headers=ORIGIN)
    ids = [x["id"] for x in r.json().get("checks", [])]
    check("GET /api/v1/check: every part, from this server's own facts", r.status_code == 200 and ids[:2] == ["server", "capture"]
          and by_id(r.json()["checks"])["errors"]["state"] == "warn", [r.status_code, ids])
    r = c.get("/api/v1/log?errors=1&limit=5", headers=ORIGIN)
    check("GET /api/v1/log?errors=1: the failures", r.status_code == 200 and r.json()["events"][0]["event"] == "analysis_error", r.text[:200])
    r = c.get("/api/v1/report?days=2", headers=ORIGIN)
    j = r.json() if r.status_code == 200 else {}
    check("GET /api/v1/report: the days and the period from the server's own events, with the words for why analyses stopped",
          r.status_code == 200 and sum(sum(d["errors"].values()) for d in j.get("days", [])) == 1 and "verdicts" in j.get("period", {})
          and "first_token_by" in j.get("period", {}) and j.get("names", {}).get("cancelled", {}).get("superseded") == "new screen", [r.status_code, j.get("names")])
    r = c.get("/api/v1/report?days=%C2%B2", headers=ORIGIN)
    check("...a number that is no ASCII number (²): the default, not an error", r.status_code == 200, [r.status_code, r.text[:120]])
    r = c.get("/api/v1/log?limit=" + "9" * 5000, headers=ORIGIN)
    check("...nor one of 5000 digits", r.status_code == 200, [r.status_code, r.text[:120]])
    r = c.get("/api/v1/report?days=0", headers=ORIGIN)
    check("...?days=0 counts today, the least it counts", r.status_code == 200 and len(r.json().get("days", [])) == 1, r.text[:200])
    r = c.get("/api/v1/log/server?lines=5", headers=ORIGIN)
    check("GET /api/v1/log/server: the log's last lines", r.status_code == 200 and isinstance(r.json()["lines"], list), r.text[:200])
    r = c.get("/api/v1/models", headers=ORIGIN)
    check("GET /api/v1/models with no Ollama: 503, said", r.status_code == 503 and "Ollama" in r.json().get("error", ""), r.text[:200])
    r = c.request("DELETE", "/api/v1/models/no-such:model", headers={**ORIGIN, "content-type": "application/json"}, content="{}")
    check("DELETE a model with no local server to ask: 503, as /models says it", r.status_code == 503, [r.status_code, r.text[:200]])
    r = c.request("DELETE", "/api/v1/models/hf.co/someone/model:Q4", headers={**ORIGIN, "content-type": "application/json"}, content="{}")
    check("...a name with slashes in it reaches the route, whole", r.status_code == 503 and r.json().get("model") == "hf.co/someone/model:Q4",
          [r.status_code, r.text[:200]])
    r = c.post("/api/v1/backup", headers={**ORIGIN, "content-type": "application/json"}, content="{}")
    got = tarfile.open(fileobj=io.BytesIO(r.content)).getnames() if r.status_code == 200 else []
    check("POST /api/v1/backup: the archive, named for its time, saying what it holds", r.status_code == 200
          and r.headers.get("content-type") == "application/gzip" and "sidenote-backup-" in r.headers.get("content-disposition", "")
          and ".settings.json" in got and "sidenote-backup.txt" in got
          and set(r.headers.get("x-sidenote-held", "").split()) == set(got),
          [r.status_code, r.headers.get("content-disposition"), got])
    check("...its folder gone once sent", not [p for p in Path(LOGS).iterdir() if p.name.startswith(".backup.")],
          [p.name for p in Path(LOGS).iterdir()])
    r = c.post("/api/v1/backup", headers={"origin": "https://example.com", "content-type": "application/json"}, content="{}")
    check("another site's page: refused", r.status_code == 403, r.status_code)
    r = c.post("/api/v1/backup", headers={**ORIGIN, "content-type": "text/plain"}, content="x")
    check("a write that is not JSON: refused", r.status_code == 415, r.status_code)
    r = c.request("DELETE", "/api/v1/models/x", headers={"origin": "https://example.com", "content-type": "application/json"}, content="{}")
    check("...a delete from another site's page too", r.status_code == 403, r.status_code)

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
for name in FAIL:
    print("  FAIL", name)
sys.exit(1 if FAIL else 0)
