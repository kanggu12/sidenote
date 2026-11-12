"""What the panel's Maintenance sheet shows and does, and the API with it (docs/API.md): the checks of how each part
stands with what to do about it, the latest events and lines of the server's log, the local server's models, and a
backup of the history and the settings.

The checks are worked out here from facts the server already holds (app.py gathers them), so the panel and a program
asking the API read the same words. The log is read from the end of its files, so a long events.jsonl costs a request
no more than its last lines. A backup is the file `./sidenote backup` writes, so `./sidenote restore` takes either; a
restore replaces the history under a server that holds it open, so it stays the launcher's (it stops the server for
the swap), and the sheet says how.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

from .i18n import t

# What a check's state is: as the cards colour theirs (panel/index.html, data-state)
OK, WARN, BAD, OFF, IDLE = "ok", "warn", "bad", "off", "idle"
FREE_WARN_GB = 5.0    # free space on the data folder under this: a warning (a speech model is 1.6 GB, the history up to 0.2)
FREE_BAD_GB = 1.0     # under this: a fault (a model download or the history's next writes can fail)
FRAME_STALE_SEC = 60  # a connected program whose screen has not come for this long while it is on: something holds it
# The events that say something failed or was held back, as `./sidenote events --errors` picks them (server/report.py)
HELD = ("agent_brake", "agent_limit", "local_stuck")
MAX_EVENTS = 1000     # what one request returns at most
MAX_LOG_LINES = 2000  # the same for the server's log
BLOCK = 64 * 1024     # how much of a file a backwards read takes at a time


def _ago(age: float) -> str:
    """When the last screen came, in seconds, minutes or hours as fits"""
    if age < 120:
        return t("Last screen {s} s ago", s=int(age))
    if age < 7200:
        return t("Last screen {m} min ago", m=int(age // 60))
    return t("Last screen {h} h ago", h=int(age // 3600))


def _check(cid: str, name: str, state: str, said: str, fix: str = "", cmd: str = "", go: str = "") -> dict:
    """One row of the list: what it is about, how it stands, what is known, what to do and a command for it; `go` names a
    section of the sheet the fix is in (the panel draws a key to it)."""
    return {"id": cid, "name": name, "state": state, "said": said, "fix": fix, "cmd": cmd, "go": go}


def _gb(n_bytes: float) -> str:
    """A size in GB with one decimal, as the cards write memory"""
    return f"{n_bytes / 1024 ** 3:.1f}"


def _mb(n_bytes: float) -> str:
    """A size in MB without decimals, for the history's file"""
    return f"{n_bytes / 1024 ** 2:.0f}"


def checks(f: dict) -> list[dict]:
    """The checks, in the order the parts are set up (the setup guide's): the server, the capture program, the screen,
    speech, this PC's model, the agent, web search, the code runner, the disk, the GPU and the errors of the last day.
    `f` holds the facts (app.py, maintenance_facts); each key it lacks is a part this server does not say anything of."""
    out = []
    # The server itself: its release, and a newer one when the release check found it
    newer = (f.get("update") or {}).get("version")
    out.append(_check("server", t("Sidenote server"), WARN if newer else OK,
                      t("Version {v}", v=f.get("version", "")) + (" · " + t("{v} is out", v=newer) if newer else ""),
                      t("Update with git pull and ./sidenote up, or the release's app") if newer else ""))
    # The capture program: connected, and of the server's release; how to start one depends on where the server runs
    cap = f.get("capture") or {}
    where = f.get("where", "")
    if not cap.get("clients"):
        start = {"desktop": (t("Quit Sidenote and start it again"), ""),
                 "cluster": (t("Start it on your PC: Capture connection in the menu gives the way"), "")}.get(
                     where, (t("Run it in the server's terminal"), "./sidenote capture"))
        out.append(_check("capture", t("Capture program"), BAD, t("Not connected"), start[0], start[1]))
    else:
        who = cap.get("who") or {}
        pc = " · ".join(x for x in (who.get("host"), who.get("system")) if x)
        theirs, ours = who.get("version") or "", f.get("version", "")
        if theirs and ours and theirs != ours:   # another release: it may not speak what this server does
            out.append(_check("capture", t("Capture program"), WARN, t("Release {theirs}, the server's is {ours}", theirs=theirs, ours=ours)
                              + (f" · {pc}" if pc else ""), t("Restart it to run the server's code")))
        else:
            out.append(_check("capture", t("Capture program"), OK, (pc + " · " if pc else "") + t("Connected")))
    # The screen: switched off on purpose is no fault, nor is a window of Skip windows on screen (no screen comes then, on
    # purpose), nor a still screen: the program sends a screen when a change settles, and none while nothing changes. A
    # program connected for a minute that has sent none since it connected is: its first settled screen comes in seconds.
    if not cap.get("screen_on", True):
        out.append(_check("screen", t("Screen capture"), OFF, t("Switched off"), t("Turn it on in the capture card")))
    elif cap.get("clients"):
        age, up = cap.get("frame_age"), cap.get("connected_for")
        none_since = age is None or (up is not None and age > up)    # no screen since this program connected
        if cap.get("skipping"):
            out.append(_check("screen", t("Screen capture"), IDLE, t("A window of Skip windows is on screen")))
        elif none_since and (up is None or up > FRAME_STALE_SEC):
            out.append(_check("screen", t("Screen capture"), WARN, t("No screen since it connected"),
                              t("Check the monitor chosen in Capture connection")))
        elif none_since:
            out.append(_check("screen", t("Screen capture"), IDLE, t("No screen yet")))
        else:
            out.append(_check("screen", t("Screen capture"), OK, _ago(age)))
    else:
        out.append(_check("screen", t("Screen capture"), IDLE, t("Waits for the capture program")))
    # Speech: off on the server, a model that did not load, or the models that write it down
    sp = f.get("speech") or {}
    if not sp.get("enabled", True):
        # off by SIDENOTE_AUDIO=0, or by no transcriber at all (SIDENOTE_TRANSCRIBER=null): the variable that turns it on
        on = "SIDENOTE_TRANSCRIBER=auto" if sp.get("transcriber") == "null" else "SIDENOTE_AUDIO=1"
        out.append(_check("speech", t("Speech recognition"), OFF, t("Off on the server"), t("Start the server with {cmd}", cmd=on)))
    elif not sp.get("available"):
        out.append(_check("speech", t("Speech recognition"), BAD if sp.get("failed") else IDLE,
                          t("The speech model did not load") if sp.get("failed") else t("Loading the speech model"),
                          t("See the server's log in Log") if sp.get("failed") else "", go="log" if sp.get("failed") else ""))
    else:
        live = sp.get("live") or ""
        models = sp.get("model", "") + (" · " + t("live words: {m}", m=live) if live and live != sp.get("model") else "")
        out.append(_check("speech", t("Speech recognition"), OK if cap.get("audio_on", True) else OFF,
                          models if cap.get("audio_on", True) else t("Sound capture off") + " · " + models))
    # This PC's model: switched off, not in this server, not answering, not downloaded, or ready (loaded or not)
    loc = f.get("local") or {}
    if not loc.get("present"):
        out.append(_check("local", t("Local model"), OFF, t("Not in this server"), t("Start the server with {cmd}", cmd="SIDENOTE_ANALYZER=local")))
    elif not loc.get("on"):
        out.append(_check("local", t("Local model"), OFF, t("Switched off"), t("Turn it on in Solver settings")))
    elif loc.get("missing"):
        want = loc.get("want") or loc.get("model") or ""
        want = ", ".join(str(w) for w in want) if isinstance(want, (list, tuple)) else str(want)   # models.wanted() gives a list
        out.append(_check("local", t("Local model"), BAD, t("{model} not downloaded", model=want),
                          t("Download it in Models") if loc.get("pull") else t("Run {cmd} in the server's terminal", cmd="./sidenote llm pull"),
                          "" if loc.get("pull") else "./sidenote llm pull", "models" if loc.get("pull") else ""))
    elif not loc.get("ok"):
        out.append(_check("local", t("Local model"), BAD, t("The local LLM server does not answer"),
                          t("Run {cmd} in the server's terminal", cmd="./sidenote up"), "./sidenote up"))
    else:
        loaded = loc.get("loaded")
        out.append(_check("local", t("Local model"), OK, (loc.get("model") or "") + " · "
                          + (t("on the GPU") if loaded else t("loaded with the next problem"))))
    # The agent: not in this server, switched off, signed out, at its plan's limit, or ready
    ag = f.get("agent") or {}
    name = ag.get("label") or t("Agent")
    if not ag.get("present"):
        out.append(_check("agent", name, OFF, t("Not in this server")))
    elif ag.get("mode") == "off":
        out.append(_check("agent", name, OFF, t("Switched off"), t("Turn it on in Solver settings")))
    elif not ag.get("ok") and ag.get("installed") is False:
        out.append(_check("agent", name, OFF, t("Not installed on this PC")))
    elif not ag.get("ok"):
        login = ag.get("login") or ""
        out.append(_check("agent", name, WARN, t("Not signed in"), t("Sign in from the server's terminal") if login else "", login))
    elif ag.get("limit_until"):
        until = time.strftime("%H:%M", time.localtime(ag["limit_until"]))
        out.append(_check("agent", name, WARN, t("At its plan's limit until {when}", when=until)))
    else:
        out.append(_check("agent", name, OK, ag.get("model") or t("Signed in")))
    # Web search and the code runner: there or not; what each is for is in their settings
    se = f.get("search") or {}
    out.append(_check("search", t("Web search"), OK if se.get("present") and se.get("on") else OFF,
                      t("Switched on") if se.get("present") and se.get("on") else t("Switched off") if se.get("present") else t("No search server")))
    out.append(_check("runner", t("Code runner"), OK if f.get("runner") else OFF, t("Ready") if f.get("runner") else t("No code runner")))
    # The disk the data folder is on: its free space, and the history's file against its limit
    disk = f.get("disk") or {}
    if disk.get("free") is not None:
        free = disk["free"] / 1024 ** 3
        state = BAD if free < FREE_BAD_GB else WARN if free < FREE_WARN_GB else OK
        said = t("{free} GB free", free=_gb(disk["free"]))
        if disk.get("history") is not None:
            cap_mb = disk.get("history_cap") or 0                       # 0: no limit
            said += " · " + (t("history {mb} of {cap} MB", mb=_mb(disk["history"]), cap=f"{cap_mb:g}") if cap_mb
                             else t("history {mb} MB", mb=_mb(disk["history"])))
        out.append(_check("disk", t("Disk"), state, said, t("Free some space on the data folder's disk") if state != OK else ""))
    # The GPU: what is in use of it, when there is a reading. Its name is the same word in every language, so not t()
    gpu = f.get("gpu")
    if gpu:
        share = gpu["used"] / gpu["total"] if gpu.get("total") else 0
        out.append(_check("gpu", "GPU", WARN if share > 0.97 else OK,
                          t("{used} of {total} GB in use", used=f"{gpu['used'] / 1024:.1f}", total=f"{gpu['total'] / 1024:.1f}")
                          + (f" · {gpu['util']}%" if gpu.get("util") is not None else ""),
                          t("Free GPU in the local model's card, or close what else uses it") if share > 0.97 else ""))
    else:
        out.append(_check("gpu", "GPU", IDLE, t("No reading")))
    # What failed in the last day, from the events: a key to the Log section, where they are
    errors = f.get("errors_day")
    if errors is not None:
        out.append(_check("errors", t("Errors"), WARN if errors else OK,
                          t("{n} in the last 24 h", n=errors) if errors else t("None in the last 24 h"),
                          t("See them in Log") if errors else "", go="log" if errors else ""))
    return out


def _files(log_dir: Path, name: str) -> list[Path]:
    """`name` and its rotated files, newest first: name, name.1, name.2 ... (telemetry and the log rotate so)"""
    rotated = sorted((p for p in log_dir.glob(name + ".*") if p.suffix[1:].isdigit()), key=lambda p: int(p.suffix[1:]))
    return [p for p in [log_dir / name, *rotated] if p.is_file()]


def _lines_backwards(path: Path):
    """The lines of a file from its last to its first, read a block at a time from the end, as text"""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        rest = b""                       # the start of a line cut by the block before it
        while end > 0:
            start = max(0, end - BLOCK)
            fh.seek(start)
            chunk = fh.read(end - start) + rest
            end = start
            parts = chunk.split(b"\n")
            rest = parts[0]               # the first piece may be the end of a line in the next block back
            for raw in reversed(parts[1:]):
                if raw.strip():
                    yield raw.decode("utf-8", errors="replace")
        if rest.strip():
            yield rest.decode("utf-8", errors="replace")


def is_error(e: dict) -> bool:
    """A failure, or work held back: what `./sidenote events --errors` shows"""
    name = str(e.get("event", ""))
    return name.endswith("_error") or name in HELD


def recent_events(log_dir: Path, errors: bool = False, limit: int = 200, since: float = 0.0) -> list[dict]:
    """The latest events, newest first: all of them or only the failures, at most `limit`, none before `since`. Read
    from the end of events.jsonl, then of its rotated files, until enough are found."""
    limit = max(0, min(int(limit), MAX_EVENTS))
    out = []
    for path in _files(log_dir, "events.jsonl"):
        for line in _lines_backwards(path):
            if len(out) >= limit:
                return out
            try:
                e = json.loads(line)
            except ValueError:            # a line cut by a crash: not an event
                continue
            if not isinstance(e, dict):
                continue
            if since and e.get("ts", 0) < since:
                return out                # older ones follow, all before `since`
            if errors and not is_error(e):
                continue
            out.append(e)
    return out


def errors_since(log_dir: Path, since: float) -> int:
    """How many failures there were from `since` on (the checks' last day)"""
    return len(recent_events(log_dir, errors=True, limit=MAX_EVENTS, since=since))


def log_tail(log_dir: Path, lines: int = 200) -> list[str]:
    """The last lines of the server's log, oldest first, at most `lines` (its rotated file too when the live one is short)"""
    lines = max(0, min(int(lines), MAX_LOG_LINES))
    out = []
    for path in _files(log_dir, "server.log"):
        for line in _lines_backwards(path):
            if len(out) >= lines:
                return out[::-1]
            out.append(line)
    return out[::-1]


def model_rows(tags: dict, ps: dict, in_use: set, offered: dict) -> list[dict]:
    """The local server's models as the sheet lists them: Ollama's /api/tags and /api/ps put together, each with its size,
    when it was made, what it is, whether it is on the GPU and whether this server uses it; then the models the panel
    offers that are not there, to download. `offered`: {name: its download's size in GB or None}."""
    loaded = {m.get("name") or m.get("model"): m for m in (ps or {}).get("models", []) if isinstance(m, dict)}
    rows, have = [], set()
    for m in (tags or {}).get("models", []):
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model") or ""
        have.add(name)
        details = m.get("details") or {}
        on = loaded.get(name)
        rows.append({"name": name, "size": m.get("size"), "modified": m.get("modified_at"),
                     "family": details.get("family"), "params": details.get("parameter_size"),
                     "quant": details.get("quantization_level"), "loaded": bool(on),
                     "vram": (on or {}).get("size_vram"), "in_use": name in in_use, "present": True})
    # the models the panel would download, each once, after those there
    for name, size in offered.items():
        if name not in have:
            rows.append({"name": name, "size_gb": size, "present": False, "in_use": name in in_use, "loaded": False})
    return rows


# What a backup holds, by the names `./sidenote backup` gives them (the launcher's BACKUP_NAMES): the history, the
# settings, the switches, and what made it
BACKUP_NAMES = ("history.sqlite", ".settings.json", ".switches.json", "sidenote-backup.txt")


def make_backup(log_dir: Path, version: str) -> tuple[Path, dict]:
    """The history and the settings in one tar.gz, as `./sidenote backup` writes it, made in a folder of its own in the log
    folder: the history copied through SQLite's backup (it is open and written while the server runs), Recently deleted
    left out and the copy rebuilt so nothing of those answers stays in its pages, the settings and switches as they are,
    and sidenote-backup.txt saying what made it and when. Returns the archive's path (the caller removes its folder once
    it is sent) and {"held": [names], "left_out": n}. A link in place of a file is refused, as the launcher refuses it."""
    for name in ("history.sqlite", ".settings.json", ".switches.json"):   # refused before any folder is made
        if (log_dir / name).is_symlink():
            raise ValueError(t("{name} is a link, not a file of Sidenote's: no backup is made", name=name))
    # The folder is this user's alone (mkdtemp makes it 0700), and each file made in it is set 0600: the process's umask is
    # the server's, left as it is (the launcher sets its own in its shell; set here it would hold for every later file)
    stage = Path(tempfile.mkdtemp(prefix=".backup.", dir=log_dir))
    try:
        return _fill_backup(stage, log_dir, version)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)   # a copy that failed halfway leaves no history behind, deleted rows and all
        raise


def _fill_backup(stage: Path, log_dir: Path, version: str) -> tuple[Path, dict]:
    """make_backup's work in its folder, which it takes away when this fails"""
    held, left_out = [], 0
    src = log_dir / "history.sqlite"
    if src.is_file():
        dst = stage / "history.sqlite"
        # read only, so the server's own writes go on; the path as a file: URI, so a "#" or "%" in a folder's name is
        # the name's (in "file:{path}" SQLite read "#" as the end of the path and made an empty database there)
        a = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        b = sqlite3.connect(dst)
        a.backup(b)                                                     # a consistent copy, the -wal's latest in it
        a.close()
        columns = [r[1] for r in b.execute("PRAGMA table_info(answers)")]
        if "deleted" in columns:
            left_out = b.execute("SELECT COUNT(*) FROM answers WHERE deleted IS NOT NULL").fetchone()[0]
            if left_out:
                b.execute("DELETE FROM answers WHERE deleted IS NOT NULL")
                b.commit()
                b.execute("VACUUM")                                     # no page of a deleted answer stays in the copy
        b.execute("PRAGMA journal_mode=DELETE")                         # one file, no -wal beside it
        b.close()
        os.chmod(dst, 0o600)
        held.append("history.sqlite")
    for name in (".settings.json", ".switches.json"):
        if (log_dir / name).is_file():
            (stage / name).write_bytes((log_dir / name).read_bytes())
            os.chmod(stage / name, 0o600)
            held.append(name)
    if not held:
        raise FileNotFoundError(t("Nothing to back up yet: no history and no settings"))
    (stage / "sidenote-backup.txt").write_text(f"sidenote {version} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n",
                                               encoding="utf-8")
    os.chmod(stage / "sidenote-backup.txt", 0o600)
    held.append("sidenote-backup.txt")
    archive = stage / "backup.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in held:
            info = tar.gettarinfo(str(stage / name), arcname=name)     # a plain file under its plain name, nothing else
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with (stage / name).open("rb") as fh:
                tar.addfile(info, fh)
    os.chmod(archive, 0o600)
    for name in held:                                                   # the archive alone is left in the folder
        (stage / name).unlink()
    return archive, {"held": held, "left_out": left_out}


def sweep_backups(log_dir: Path) -> int:
    """The backup folders left in the log folder by a server that stopped while it made or sent one, removed as the
    server starts (none is being made then): the history they may hold, Recently deleted and all, goes. Their number."""
    gone = 0
    for d in log_dir.glob(".backup.*"):
        if d.is_dir() and not d.is_symlink():      # (a .backup.* file is not one of these)
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    return gone


def stream_backup(archive: Path, block: int = BLOCK):
    """The archive's bytes, a block at a time, and the archive gone after the last one, or when the download stops first
    (a cancelled download closes this generator, and its finally runs): nothing of the history stays behind."""
    try:
        with archive.open("rb") as fh:
            while chunk := fh.read(block):
                yield chunk
    finally:
        remove_backup(archive)


def remove_backup(archive: Path) -> None:
    """The archive and its folder, once sent (or when sending failed)"""
    try:
        archive.unlink()
    except FileNotFoundError:
        pass
    try:
        archive.parent.rmdir()
    except OSError:
        pass
