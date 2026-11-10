"""What is heard, kept: the heard table of history.sqlite (server/history.py), the switch Keep what is heard, what the speech
pass writes into it, /heard, and that a long transcript never pushes an answer out of the size cap.

    .venv/bin/python tests/heard_keep.py

Made-up sentences only. The real _voice_pass runs against a stand-in transcriber that says what each check tells it to.
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The server's environment, set before it is imported: stand-in engines, no speech, no runner, a log folder of its own
LOGS = tempfile.mkdtemp(prefix="sidenote-heard-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_LOG_DIR=LOGS,
                  SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_AGENT="mock")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server.history import HEARD_ROW, HEARD_WORDS, History  # noqa: E402

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}   # the panel's own page, which /panel takes
DAY = 86400.0
SR = 16000


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:300]}" if detail != "" and not ok else ""))


def answer(i: int, text: str = "") -> dict:
    """What the server keeps of one answer (keep_answer in server/app.py), less its time."""
    return {"trigger": "screen", "transcript": "", "text": text or f"TYPE: essay\nANSWER: 답 {i}\n\n풀이 {i}", "model": "m",
            "engine": "local", "sent": [], "stages": {}, "usage": {}, "cost_usd": None, "elapsed": 1.0, "first_token": None,
            "region": None, "region_shown": False, "thumb": None}


def fresh(**kw) -> tuple:
    path = Path(tempfile.mkdtemp(prefix="sidenote-heard-file-")) / "history.sqlite"
    return History(path, **kw), path


def pages_in_use(path: Path) -> int:
    db = sqlite3.connect(str(path))
    used = (db.execute("PRAGMA page_count").fetchone()[0] - db.execute("PRAGMA freelist_count").fetchone()[0]) \
        * db.execute("PRAGMA page_size").fetchone()[0]
    db.close()
    return used


def texts(rows) -> list:
    return [r["text"] for r in rows]


# The time the checks below place lines by, kept an hour or more from midnight: CI's weekly run reached them at 00:00:50
# UTC, the size check's lines 50 minutes back fell on the day before, and its max() had nothing of today's to read. Up to an
# hour off the real time; every check here that places a line by it reads it back by it
_lt = time.localtime()
_into = _lt.tm_hour * 3600 + _lt.tm_min * 60 + _lt.tm_sec          # seconds into the local day
now = time.time() + max(0, 3600 - _into) - max(0, _into - (86400 - 3600))
print("\n[one row a sentence]")
h, f = fresh()
today = time.strftime("%Y-%m-%d", time.localtime(now))
h.add_heard(now - 30, 2.504, "en", "So we drained the node first.")
h.add_heard(now - 20, 1.2, "ko", "노드를 먼저 비웠습니다.")
h.add_heard(now - 10, 0.9, "", "")   # nothing was written down: nothing to keep
lines = h.heard_lines(today)
check("each sentence is a row, in the order it was said", texts(lines) == ["So we drained the node first.", "노드를 먼저 비웠습니다."], lines)
check("...with its time, its length and its language", lines[0]["ts"] == now - 30 and lines[0]["secs"] == 2.5 and lines[0]["lang"] == "en", lines[0])
days = h.heard_days()
check("the days that hold any, with how many and from when to when",
      [(d["day"], d["n"], d["first"], d["last"]) for d in days] == [(today, 2, now - 30, now - 20)], days)
check("anything kept is known without reading it", h.heard_any() is True and fresh()[0].heard_any() is False)
h.add_heard(now - 2 * DAY, 1.0, "en", "An older line.")
check("a line goes under the day it was heard", [d["n"] for d in h.heard_days()] == [2, 1]
      and texts(h.heard_lines(time.strftime("%Y-%m-%d", time.localtime(now - 2 * DAY)))) == ["An older line."], h.heard_days())
check("the answers' own lists know nothing of it", h.days_list() == [] and h.query() == [])
check("a day with nothing is no lines", h.heard_lines("2001-01-01") == [])

print("\n[a file from before the table]")
old = Path(tempfile.mkdtemp(prefix="sidenote-heard-old-")) / "history.sqlite"
db = sqlite3.connect(str(old))
db.execute("CREATE TABLE answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, words TEXT NOT NULL,"
           " data TEXT NOT NULL, starred INTEGER NOT NULL DEFAULT 0)")
data = {**answer(7), "id": 7, "ts": now, "kind": "essay"}
db.execute("INSERT INTO answers (id, ts, day, kind, words, data) VALUES (7, ?, ?, 'essay', 'x', ?)", (now, today, json.dumps(data)))
db.commit()
db.close()
h = History(old)
check("opens with its answers kept, and gains the table", [r["id"] for r in h.query()] == [7] and h.heard_lines(today) == [])
h.add_heard(now, 1.0, "en", "A line in an old file.")
check("...which then keeps lines", texts(h.heard_lines(today)) == ["A line in an old file."])

print("\n[the age limit]")
h, f = fresh(days=3)
h.add_heard(now - 5 * DAY, 1.0, "en", "Past the age.")
h.add_heard(now - 1 * DAY, 1.0, "en", "Within the age.")
keep_day = time.strftime("%Y-%m-%d", time.localtime(now - 1 * DAY))
check("a sentence kept prunes what is past the age, by itself: a sitting of speech alone has no answer to do it",
      len(h.heard_days()) == 1 and texts(h.heard_lines(keep_day)) == ["Within the age."], h.heard_days())
h, f = fresh(days=3)
h.add_heard(now, 1.0, "en", "Heard today.")
h.add(1, now - 5 * DAY, "essay", answer(1))
h.add(2, now, "essay", answer(2))
h.prune(now + 4 * DAY)   # four days on: today's line is past the age now, as the old answer has long been
check("it is pruned with the answers", h.heard_days() == [] and h.query() == [], [h.heard_days(), [r["id"] for r in h.query()]])
h, f = fresh(days=3)
h.add_heard(now - 1 * DAY, 1.0, "en", "Within the age.")
h.prune(now)
check("what is within the age stays through a prune", h.heard_any())
h, f = fresh(days=0)
h.add_heard(now - 400 * DAY, 1.0, "en", "No age limit is set.")
check("no age limit, no pruning by age", h.heard_any())

print("\n[its own size limit]")
LINE = "복제 지연이 커져서 읽기를 주 서버로 옮겼습니다. " * 4
h, f = fresh(heard_mb=0.05)
ts = now - 3000
for i in range(600):
    h.add_heard(ts + i, 2.0, "ko", f"{i} {LINE}")
total = sqlite3.connect(str(f)).execute("SELECT COALESCE(SUM(LENGTH(CAST(words AS BLOB))), 0), COUNT(*) FROM heard").fetchone()
check("past its limit the table stays within it", total[0] * HEARD_WORDS + total[1] * HEARD_ROW <= 0.05 * 1048576 and total[1] > 0, total)
lines = h.heard_lines(today, 100000)
last = max(int(r["text"].split()[0]) for r in lines)
first = min(int(r["text"].split()[0]) for r in lines)
check("...the oldest gone first, the newest kept", last == 599 and first > 0 and first == 600 - len(lines), [first, last, len(lines)])
check("...and what it counts is what is there", h._heard_bytes == total[0] * HEARD_WORDS + total[1] * HEARD_ROW, [h._heard_bytes, total])
h2 = History(f, heard_mb=0.05)   # the next start of the server knows only the file
h2.add_heard(now, 2.0, "ko", f"600 {LINE}")
total = sqlite3.connect(str(f)).execute("SELECT COALESCE(SUM(LENGTH(CAST(words AS BLOB))), 0), COUNT(*) FROM heard").fetchone()
check("...after a restart too", total[0] * HEARD_WORDS + total[1] * HEARD_ROW <= 0.05 * 1048576, total)
h, f = fresh(heard_mb=0.001)
h.add_heard(now, 2.0, "ko", "한 문장이 " * 800)
check("one sentence past the whole limit does not stop the next", (h.add_heard(now + 1, 1.0, "en", "short") or True) and h._heard_bytes >= 0)
for size, line, many in (("short", "네 맞습니다", 3000), ("usual", LINE, 2000), ("long", LINE * 8, 300), ("the longest", LINE * 12, 300)):
    h, f = fresh()
    before = pages_in_use(f)
    for i in range(many):
        h.add_heard(now + i, 2.0, "ko", line)
    grown = pages_in_use(f) - before
    check(f"what it counts is at least what {size} lines take on disk: counted low, a transcript would push answers out",
          h._heard_sum() >= grown, [h._heard_sum(), grown])

print("\n[a long transcript and the answers' cap]")
CAP = 0.2   # MB of answers
body = "복제 지연을 재는 방법을 풀이합니다. " * 120
h, f = fresh(max_mb=CAP, heard_mb=0.5)
for i in range(1, 11):
    h.add(i, now - 100 + i, "essay", answer(i, body))
check("ten answers fit the cap", len(h.query(limit=200)) == 10, len(h.query(limit=200)))
pages = pages_in_use(f)
for i in range(6000):
    h.add_heard(now - 90 + i * 0.001, 2.0, "ko", LINE)
check("the transcript takes more of the file than the answers' whole cap", pages_in_use(f) - pages > CAP * 1048576, pages_in_use(f) - pages)
h.add(11, now - 80, "essay", answer(11, body))   # the next answer is what prunes
check("the next answer pushes none out: a long transcript takes none of their room", len(h.query(limit=200)) == 11,
      [r["id"] for r in h.query(limit=200)])
for i in range(12, 160):
    h.add(i, now - 80 + i, "essay", answer(i, body))
kept = [r["id"] for r in h.query(limit=200)]
heard = h._heard_sum()
check("answers past their own cap still go, the oldest first, with the transcript there", 1 not in kept and 159 in kept,
      kept[-3:])
check("...and those left fit the cap", pages_in_use(f) - heard <= CAP * 1048576 * 1.1, [pages_in_use(f), heard])
check("...while the transcript loses nothing to them", heard == h._heard_bytes and heard > 0.45 * 1048576, heard)
h.star(159, True)
check("a star still counts as it did", [r["id"] for r in h.query(starred=True)] == [159])

print("\n[Clear history]")
h, f = fresh()
h.add(1, now, "essay", answer(1))
h.add_heard(now, 1.0, "en", "A MARKED SENTENCE THAT MUST GO")
h.clear()
check("it clears what was heard with the answers", not h.heard_any() and h.query() == [] and h.heard_days() == [])
stored = b"".join(p.read_bytes() for p in f.parent.iterdir() if p.is_file())
check("...and the words are not left in the file or its WAL", b"A MARKED SENTENCE" not in stored)
h.add_heard(now, 1.0, "en", "After clearing.")
check("...and it keeps lines again, counted from nothing", h.heard_any() and h._heard_bytes == len("After clearing.") * HEARD_WORDS + HEARD_ROW, h._heard_bytes)

print("\n[the switch and the speech pass]")
import server.app as A                     # noqa: E402
from server.settings import SETTINGS       # noqa: E402
from server.transcriber import UtteranceTracker   # noqa: E402

SETTINGS.path = None    # nothing written beside the logs
item = SETTINGS.defs["speech_keep"]
check("Keep what is heard is a switch of the Speech section, off by default", item.kind == "bool" and item.section == "speech" and item.default is False)
help_words = next(i for i in SETTINGS.meta()["items"] if i["key"] == "speech_keep")["help"]
check("its help says it stays on this PC, and for how long", "PC" in help_words and str(int(A.CONFIG.history_days)) in help_words, help_words)


class Stub:
    """A transcriber that hears exactly what a check tells it to: `spans` is where the speech is, in seconds from the start of
    the stream, `said` what each span says."""

    available = True
    last_language = "en"

    def __init__(self):
        self.spans, self.said = [], {}

    def speech_segments(self, tail, sr):
        off = A.STATE.audio_total // 2 - len(tail) // 2   # positions inside the tail, as the pass adds its start back
        return [(int(s * sr) - off, int(e * sr) - off) for s, e in self.spans]

    def transcribe(self, pcm, sr):
        secs = len(pcm) / 2 / sr
        for s, e in self.spans:
            if abs((e - s) - secs) < 0.05:
                return self.said.get(s, "")
        return ""


def fresh_state():
    A.STATE.__init__()
    A.STATE.audio_sr = SR
    A.STATE.push_audio(b"\0\0" * int(SR * 10), SR)
    A.broadcast = lambda msg: asyncio.sleep(0)
    return UtteranceTracker(SR, A.CONFIG.utter_end_silence, A.CONFIG.utter_max_sec)


async def hear(stub, tracker, spans, said, upto):
    stub.spans, stub.said = spans, said
    have = A.STATE.audio_total // 2 / SR
    if upto > have:
        A.STATE.push_audio(b"\0\0" * int(SR * (upto - have)), SR)
    await A._voice_pass(stub, tracker, asyncio.get_running_loop(), True)


def wait_writes():
    """The writes go on the history's own thread: this waits for those made so far."""
    A.HISTORY_WRITES.submit(lambda: None).result(timeout=10)


def kept_all() -> list:
    """Every line kept, oldest first, whatever day each fell on: the server writes them at its own time, and read by
    today's date alone a run over midnight lost the ones just before it."""
    wait_writes()
    return [r for d in reversed(A.HISTORY.heard_days()) for r in A.HISTORY.heard_lines(d["day"], 1000)]


def kept_now() -> list:
    return texts(kept_all())


async def speech_pass():
    A.HISTORY.clear()
    stub, tracker = Stub(), fresh_state()
    SETTINGS.values["speech_keep"] = False
    await hear(stub, tracker, [(2.0, 5.0)], {2.0: "What does a write ahead log do?"}, 10.0)
    check("switched off, nothing is kept", kept_now() == [])
    check("...and speech goes on as ever", A.STATE.voice_pending is True)

    stub, tracker = Stub(), fresh_state()
    SETTINGS.values["speech_keep"] = True
    await hear(stub, tracker, [(2.0, 4.5)], {2.0: "So that took about two hours."}, 10.0)
    await hear(stub, tracker, [(11.0, 12.0)], {11.0: "Okay."}, 16.0)
    kept = kept_now()
    check("switched on, every closed sentence is kept, a remark too short to solve as well",
          kept == ["So that took about two hours.", "Okay."], kept)
    rows = kept_all()
    check("...with its time, its length and its language", rows[0]["secs"] == 2.5 and rows[0]["lang"] == "en" and abs(rows[0]["ts"] - time.time()) < 30, rows[0])
    await hear(stub, tracker, [(17.0, 17.3)], {17.0: "A blip the VAD found."}, 22.0)
    check("a blip that is not transcribed is not kept", len(kept_now()) == 2, kept_now())
    await hear(stub, tracker, [(23.0, 25.0)], {23.0: ""}, 30.0)
    check("nor is a sentence that came back empty", len(kept_now()) == 2, kept_now())

    # thrown away while it was being written down: sound off, pause
    stub, tracker = Stub(), fresh_state()
    A.HISTORY.clear()
    plain = stub.transcribe

    def off_meanwhile(pcm, sr):
        A.STATE.speech_epoch += 1
        return plain(pcm, sr)
    stub.transcribe = off_meanwhile
    await hear(stub, tracker, [(2.0, 4.5)], {2.0: "Said while the sound was switched off."}, 10.0)
    check("a sentence dropped with the sound switch is not kept", kept_now() == [], kept_now())

    # kept with Solve spoken problems off: the sentences are still cut, and nothing is queued
    stub, tracker = Stub(), fresh_state()
    SETTINGS.values["voice_auto"] = False
    await hear(stub, tracker, [(2.0, 4.5)], {2.0: "What does a write ahead log do?"}, 10.0)
    check("with Solve spoken problems off it is kept", kept_now() == ["What does a write ahead log do?"], kept_now())
    check("...and nothing is queued, and nothing joins a problem", A.STATE.voice_pending is False and A.STATE.voice_waiting is False and A.STATE.utterances == [])
    SETTINGS.values["voice_auto"] = True


async def worker_cuts_for_the_switch():
    """The loop's own pass: with Solve spoken problems off it cuts sentences only while the switch is on."""
    A.HISTORY.clear()
    stub = Stub()
    fresh_state()
    SETTINGS.values["voice_auto"] = False
    SETTINGS.values["speech_keep"] = False
    was = A.CONFIG.transcribe_interval
    A.CONFIG.transcribe_interval = 0.2
    app = __import__("types").SimpleNamespace(state=__import__("types").SimpleNamespace(transcriber=stub))
    stub.spans, stub.said = [(2.0, 4.5)], {2.0: "Heard with nothing asking for it."}
    task = asyncio.create_task(A.transcription_worker(app))
    for _ in range(6):
        A.STATE.push_audio(b"\0\0" * int(SR * 0.2), SR)
        await asyncio.sleep(0.22)
    check("both off, the loop keeps nothing", kept_now() == [], kept_now())
    # Turned on as the panel turns it on (apply_setting), the loop cuts from that moment: the sentence said before it, still in
    # the buffer (2.0-4.5 s), is not kept (it was), and one begun at once after it is (a tracker made on the loop's next pass
    # and started from that pass would drop it)
    await A.apply_setting(app, "speech_keep", True)
    t0 = A.STATE.audio_total // 2 / SR
    stub.spans = [(2.0, 4.5), (t0 + 0.1, t0 + 1.3)]
    stub.said = {2.0: "Said before the switch.", t0 + 0.1: "Heard with nothing asking for it."}
    for _ in range(18):   # 3.6 s: the sentence, then the 1.5 s of quiet that closes it
        A.STATE.push_audio(b"\0\0" * int(SR * 0.2), SR)
        await asyncio.sleep(0.22)
    check("the switch alone sets the loop cutting sentences, from the moment it is turned on",
          kept_now() == ["Heard with nothing asking for it."], kept_now())
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    A.CONFIG.transcribe_interval = was
    SETTINGS.values["voice_auto"] = True
    SETTINGS.values["speech_keep"] = False


asyncio.run(speech_pass())
asyncio.run(worker_cuts_for_the_switch())

print("\n[who can read the file]")
if hasattr(os, "getuid"):
    was_umask = os.umask(0o022)                 # the usual one, under which a file comes out readable by everybody
    folder = Path(tempfile.mkdtemp(prefix="sidenote-heard-mode-")) / "made" / "here"
    path = folder / "history.sqlite"
    h = History(path)
    h.add_heard(time.time(), 1.0, "ko", "다른 사람의 말입니다.")
    mode = lambda p: Path(p).stat().st_mode & 0o777   # noqa: E731
    check("a folder the server makes is its user's alone", mode(folder) == 0o700, oct(mode(folder)))
    check("the file and the two beside it are its user's alone",
          [mode(f"{path}{end}") for end in ("", "-wal", "-shm")] == [0o600] * 3,
          [oct(mode(f"{path}{end}")) for end in ("", "-wal", "-shm")])
    old = Path(tempfile.mkdtemp(prefix="sidenote-heard-old-"))
    os.chmod(old, 0o755)
    earlier = sqlite3.connect(old / "history.sqlite")
    earlier.execute("PRAGMA journal_mode=WAL")
    earlier.execute("CREATE TABLE t (x)")
    earlier.commit()
    os.chmod(old / "history.sqlite", 0o644)
    os.chmod(old / "history.sqlite-wal", 0o644)
    os.chmod(old / "history.sqlite-shm", 0o644)
    h2 = History(old / "history.sqlite")
    check("a file left readable by an earlier version is closed at the open, with the two beside it",
          [mode(old / f"history.sqlite{end}") for end in ("", "-wal", "-shm")] == [0o600] * 3,
          [oct(mode(old / f"history.sqlite{end}")) for end in ("", "-wal", "-shm")])
    check("...and a folder already there keeps its mode: another program may read its logs", mode(old) == 0o755, oct(mode(old)))
    earlier.close()
    theirs = Path(tempfile.mkdtemp(prefix="sidenote-heard-theirs-")) / "history.sqlite"
    real_getuid = os.getuid
    os.getuid = lambda: real_getuid() + 1       # this server runs as another user than the file's
    try:
        History(theirs)
        check("a file of another user is left as it is", mode(theirs) == 0o644, oct(mode(theirs)))
    finally:
        os.getuid = real_getuid
    logs = Path(tempfile.mkdtemp(prefix="sidenote-heard-logs-")) / "made"
    run = subprocess.run([sys.executable, "-c", "from server import telemetry; telemetry.setup()"], cwd=ROOT,
                         env={**os.environ, "SIDENOTE_LOG_DIR": str(logs), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=60)
    check("the log folder the server makes at its start is its user's alone", logs.is_dir() and mode(logs) == 0o700,
          (run.returncode, run.stderr[-200:], oct(mode(logs)) if logs.exists() else None))
    os.umask(was_umask)

print("\n[/heard and the panel's socket]")
from starlette.testclient import TestClient  # noqa: E402

# A server that runs for a few hours at a time, with nothing new kept: what is past its age goes at the start all the same
A.HISTORY.clear()
A.HISTORY.add_heard(time.time() - A.CONFIG.history_days * DAY - 3600, 1.0, "ko", "기한이 지난 말입니다.")
check("past its age and still kept, with nothing written since", A.HISTORY.heard_any())
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    A.HISTORY_WRITES.submit(lambda: None).result(timeout=10)   # whatever the start handed the history's thread has gone before this
    for _ in range(100):                                       # the start's task may not have run yet
        if not A.HISTORY.heard_any():
            break
        time.sleep(0.05)
    check("the server's start clears what is past its age", not A.HISTORY.heard_any())
    A.HISTORY.clear()
    got = client.get("/heard").json()
    check("/heard with nothing kept", got == {"days": [], "day": "", "lines": []}, got)
    check("/history/days says nothing is kept", client.get("/history/days").json().get("heard") is False)
    yesterday = time.strftime("%Y-%m-%d", time.localtime(now - DAY))
    A.HISTORY.add_heard(now - DAY, 1.5, "ko", "어제 들린 말입니다.")
    A.HISTORY.add_heard(now - 5, 2.0, "en", "Heard a moment ago.")
    got = client.get("/heard").json()
    check("/heard gives the newest day by default, in order, with every day listed",
          got["day"] == today and texts(got["lines"]) == ["Heard a moment ago."] and [d["day"] for d in got["days"]] == [today, yesterday], got)
    got = client.get("/heard", params={"day": yesterday}).json()
    check("/heard?day= gives that day", got["day"] == yesterday and texts(got["lines"]) == ["어제 들린 말입니다."], got)
    got = client.get("/heard", params={"day": "not-a-day' OR 1=1 --"}).json()
    check("a day it does not hold is the newest one", got["day"] == today, got)
    check("/history/days says something is kept", client.get("/history/days").json().get("heard") is True)
    # the same guard as every other request: only this PC's own name reaches it
    check("a request for another Host is refused", client.get("/heard", headers={"host": "evil.test"}).status_code == 400)
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"type": "history_clear"}))
        for _ in range(200):
            if json.loads(ws.receive_text()).get("type") == "notice":
                break
    check("Clear history over the socket clears it", client.get("/heard").json()["lines"] == [] and client.get("/history/days").json().get("heard") is False)

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
