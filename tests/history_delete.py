"""One answer deleted, and put back (server/history.py, Recently deleted): a history.sqlite from before 0.6.0 gaining the
column with its rows kept, a deleted answer out of every listing and count and whole in Recently deleted, put back with
its star and follow-ups, deleted for good with nothing of it left in the file, gone by itself past its days, the first
to go when the file is over its size; then the same over the panel's socket, seen by a second panel: the last answer
held for Undo, a question about a deleted answer stopped, an answer still being written and one the history never held,
Clear history taking Recently deleted too, and a server that starts knowing what is deleted.

    .venv/bin/python tests/history_delete.py
"""
import asyncio
import base64
import io
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# The server's environment, set before it is imported: stand-in engines, no speech, no runner, no downloads, a log folder
# of its own
LOGS = tempfile.mkdtemp(prefix="sidenote-delete-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_LOG_DIR=LOGS,
                  SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_AGENT="mock",
                  SIDENOTE_LOCAL_PULL="0", SIDENOTE_UPDATE_CHECK="0")
os.environ.pop("SIDENOTE_DELETED_DAYS", None)   # the days Recently deleted holds an answer: the default, which is checked
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server.history import History  # noqa: E402

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}   # the panel's own page, which /panel takes
DAY = 86400.0

# The table and indexes server/history.py made from 0.2.0 to 0.5.2: an answer has its star, and cannot be deleted by itself
OLD_SCHEMA = ["CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL,"
              " kind TEXT NOT NULL, words TEXT NOT NULL, data TEXT NOT NULL, starred INTEGER NOT NULL DEFAULT 0)",
              "CREATE INDEX IF NOT EXISTS answers_ts ON answers (ts)",
              "CREATE INDEX IF NOT EXISTS answers_day ON answers (day, ts)",
              "CREATE INDEX IF NOT EXISTS answers_kind ON answers (kind, ts)",
              "CREATE INDEX IF NOT EXISTS answers_starred ON answers (starred, ts)"]


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:700]}" if detail and not ok else ""))


class Said(logging.Handler):
    """What the history's log says, kept to be read."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


SAID = Said()
logging.getLogger("sidenote.history").addHandler(SAID)
logging.getLogger("sidenote.history").setLevel(logging.INFO)


def answer(i: int, text: str = "", kind: str = "essay") -> dict:
    """What the server keeps of one answer (keep_answer in server/app.py), less its time."""
    return {"trigger": "screen", "transcript": "", "text": text or f"TYPE: {kind}\nANSWER: 답 {i}\n\n풀이 {i}",
            "model": "m", "engine": "local", "sent": [], "stages": {}, "usage": {}, "cost_usd": None, "elapsed": 1.0,
            "first_token": None, "region": None, "region_shown": False, "thumb": None}


def ids(rows) -> list:
    return [r["id"] for r in rows]


def new_file(name: str) -> Path:
    """A history file of its own in a folder of its own, for one group of checks."""
    return Path(tempfile.mkdtemp(prefix=f"sidenote-delete-{name}-")) / "history.sqlite"


def on_disk(path: Path) -> bytes:
    """Every byte the history has on disk: the file and SQLite's log beside it, where a write stands until it is moved over."""
    wal = Path(f"{path}-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def rows_in(path: Path) -> list:
    """(id, deleted) of every row the file holds, shown or not, read past the History's own listings."""
    db = sqlite3.connect(str(path))
    try:
        return db.execute("SELECT id, deleted FROM answers ORDER BY id").fetchall()
    finally:
        db.close()


now = time.time()

print("\n[a history file from before 0.6.0]")
old = new_file("old")
db = sqlite3.connect(str(old))
for sql in OLD_SCHEMA:
    db.execute(sql)
for i in range(1, 4):   # three answers kept by 0.5.2, as its add() wrote them, the second starred
    data = {**answer(i), "id": i, "ts": now - i * 60, "kind": "essay"}
    db.execute("INSERT INTO answers (id, ts, day, kind, words, data, starred) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (i, now - i * 60, time.strftime("%Y-%m-%d", time.localtime(now - i * 60)), "essay",
                data["text"].lower(), json.dumps(data, ensure_ascii=False), 1 if i == 2 else 0))
db.commit()
db.close()
SAID.lines.clear()
h = History(old)
cols = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(answers)")]
check("an old file gains the deleted column when it opens", cols.count("deleted") == 1, cols)
rows = h.query()
check("...with its rows kept as they were, the star too", ids(rows) == [1, 2, 3] and rows[2]["text"].endswith("풀이 3")
      and [r["starred"] for r in rows] == [False, True, False], rows[:1])
check("...and none of them deleted", h.deleted_count() == 0 and h.deleted_list() == [] and h.deleted_ids() == [])
check("the log says it once", sum("can be deleted one by one" in x for x in SAID.lines) == 1, SAID.lines)
indexes = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA index_list(answers)")]
check("Recently deleted has an index", "answers_deleted" in indexes, indexes)
SAID.lines.clear()
h = History(old)   # opened again, as the next start does: the column is there, nothing is added twice
cols = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(answers)")]
check("opened again, the column is not added twice and nothing is said", cols.count("deleted") == 1
      and not any("deleted one by one" in x for x in SAID.lines), [cols, SAID.lines])
check("the old rows can be deleted and put back", h.delete(2) is not None and ids(h.query()) == [1, 3]
      and h.restore(2) is not None and ids(h.query()) == [1, 2, 3])
oldest = new_file("oldest")   # and a file from 0.1.0, which has neither a star nor this: both come in the one opening
db = sqlite3.connect(str(oldest))
db.execute(OLD_SCHEMA[0].replace(", starred INTEGER NOT NULL DEFAULT 0", ""))
db.commit()
db.close()
History(oldest)
cols = [r[1] for r in sqlite3.connect(str(oldest)).execute("PRAGMA table_info(answers)")]
check("a file from before stars gains both columns", cols.count("starred") == 1 and cols.count("deleted") == 1, cols)

print("\n[one answer deleted]")
f = new_file("one")
h = History(f)
for i in range(10, 14):
    h.add(i, now - (14 - i) * 60, "essay", answer(i))
h.star(11, True)
h.update(11, turn={"id": 111, "q": "왜 이렇게 푸나요?", "text": "조건 때문입니다", "kind": "ask"})
gone = h.delete(11, now)
check("an answer is deleted: when, and until when it can be put back", gone == {"deleted": now, "until": now + 7 * DAY}, gone)
check("it leaves the answers listed", ids(h.query()) == [13, 12, 10], ids(h.query()))
check("...the starred ones and their count", h.query(starred=True) == [] and h.starred_count() == 0,
      [ids(h.query(starred=True)), h.starred_count()])
check("...the days' counts", sum(d["n"] for d in h.days_list()) == 3, h.days_list())
check("...a search for its words", h.query(q="답 11") == [] and h.query(q="조건 때문입니다") == [])
check("...and is not given by its id", h.get(11) is None)
held = h.deleted_list(now=now)
check("Recently deleted holds it, whole: its star and its follow-up", ids(held) == [11] and held[0]["starred"] is True
      and [t["q"] for t in held[0].get("turns", [])] == ["왜 이렇게 푸나요?"] and held[0]["text"].endswith("풀이 11"), held)
check("...with when it was deleted and when it goes by itself", held[0]["deleted"] == now and held[0]["until"] == now + 7 * DAY,
      [held[0].get("deleted"), held[0].get("until")])
check("...counted, given by its id, and listed among the deleted ids", h.deleted_count(now=now) == 1
      and (h.deleted_get(11, now=now) or {}).get("id") == 11 and h.deleted_ids(now=now) == [11])
check("an answer that is not deleted is not in Recently deleted", h.deleted_get(12, now=now) is None)
check("deleted twice, the second changes nothing", h.delete(11, now + 5) is None and h.deleted_get(11, now=now)["deleted"] == now)
check("an id the file does not hold is not deleted, nor one SQLite cannot hold", h.delete(999) is None and h.delete(10**30) is None
      and h.deleted_get(10**30) is None and h.restore(10**30) is None and h.purge(10**30) == [])
check("a deleted answer takes no star, and loses none", h.star(11, False) is False and h.star(11, True) is False
      and h.deleted_get(11, now=now)["starred"] is True)
h.add(11, now - 3 * 60, "essay", answer(11, "TYPE: essay\nANSWER: 고친 답\n\n다시 쓴 풀이"))   # the same row written again
again = h.deleted_get(11, now=now)
check("a row written again stays deleted, with its star", ids(h.query()) == [13, 12, 10] and again is not None
      and again["text"].endswith("다시 쓴 풀이") and again["starred"] is True and again["deleted"] == now, again)
h.update(11, check={"ok": True}, turn={"id": 112, "q": "하나 더", "text": "네", "kind": "ask"})
again = h.deleted_get(11, now=now)
check("what comes after the answer still reaches its row: a code check, a follow-up",
      again.get("check") == {"ok": True} and [t["id"] for t in again.get("turns", [])] == [112], again)
back = h.restore(11, now)
check("put back, it is the answer as it was: its star, its follow-up, its check", back is not None and back["id"] == 11
      and back["starred"] is True and [t["id"] for t in back.get("turns", [])] == [112] and back.get("check") == {"ok": True}
      and "deleted" not in back and "until" not in back, back)
check("...listed again in its place, starred, and searched", ids(h.query()) == [13, 12, 11, 10] and ids(h.query(starred=True)) == [11]
      and h.starred_count() == 1 and ids(h.query(q="하나 더")) == [11] and h.get(11)["starred"] is True, ids(h.query()))
check("...and Recently deleted is empty", h.deleted_count() == 0 and h.deleted_list() == [] and h.deleted_ids() == [])
check("put back twice, or never deleted, there is nothing to put back", h.restore(11) is None and h.restore(12) is None
      and h.restore(999) is None)

print("\n[deleted for good]")
MARK = "zq7-purge-mark-91"   # words of one answer alone, to look for in the file's bytes
f = new_file("purge")
h = History(f)
for i in range(20, 24):
    h.add(i, now - (24 - i) * 60, "essay", answer(i, f"TYPE: essay\nANSWER: 답 {i}\n\n{MARK if i == 21 else '풀이'} {i}"))
h.delete(20, now - 30)
h.delete(21, now - 20)
h.delete(22, now - 10)
check("while it is in Recently deleted the file still holds its words", MARK.encode() in on_disk(f))
check("deleted for good: the one asked for goes, and its id is given back", h.purge(21) == [21] and ids(h.deleted_list(now=now)) == [22, 20],
      ids(h.deleted_list(now=now)))
check("...and none of its words is left in the file or the log beside it", MARK.encode() not in on_disk(f), len(on_disk(f)))
check("...it cannot be put back", h.restore(21) is None and h.get(21) is None and h.deleted_get(21) is None)
check("asked again, nothing goes", h.purge(21) == [])
check("an answer still shown is never deleted for good: it goes to Recently deleted first", h.purge(23) == [] and ids(h.query()) == [23],
      ids(h.query()))
MARK2 = "zq7-empty-mark-58"   # the words of one answer that goes with Recently deleted emptied
h.update(20, text=f"TYPE: essay\nANSWER: 답 20\n\n{MARK2}")
check("(an answer in Recently deleted still holds its words in the file)", MARK2.encode() in on_disk(f))
check("with no id, all of Recently deleted goes", sorted(h.purge()) == [20, 22] and h.deleted_count() == 0
      and rows_in(f) == [(23, None)], rows_in(f))
check("...none of their words left in the file or the log beside it", MARK2.encode() not in on_disk(f), len(on_disk(f)))
check("...and again there is nothing to empty", h.purge() == [])

print("\n[its days in Recently deleted]")
f = new_file("days")
h = History(f, days=0, max_mb=0, deleted_days=7)   # no age limit and no size cap: only the days in Recently deleted count
for i in range(30, 34):
    h.add(i, now - 30 * DAY, "essay", answer(i))
h.star(30, True)
h.delete(30, now - 8 * DAY)   # past its seven days, and starred
h.delete(31, now - 6 * DAY)   # a day left
check("an answer past its days is not listed: its star does not hold it", ids(h.deleted_list(now=now)) == [31], ids(h.deleted_list(now=now)))
check("...it is gone from the file, starred or not", rows_in(f) == [(31, now - 6 * DAY), (32, None), (33, None)], rows_in(f))
check("...not counted, not given, and not put back", h.deleted_count(now=now) == 1 and h.deleted_get(30, now=now) is None
      and h.restore(30, now) is None and h.deleted_ids(now=now) == [31])
check("the one with a day left says when it goes", h.deleted_get(31, now=now)["until"] == now + DAY, h.deleted_get(31, now=now))
h.delete(32, now)
check("the next pruning takes what has had its days, and nothing else", h.prune(now + 2 * DAY) == 1
      and rows_in(f) == [(32, now), (33, None)], rows_in(f))
check("an answer whose days ran out between two looks is not put back", h.restore(32, now + 8 * DAY) is None
      and rows_in(f) == [(33, None)], rows_in(f))
f = new_file("kept")
h = History(f, days=0, max_mb=0, deleted_days=0)   # SIDENOTE_DELETED_DAYS=0: held until emptied by hand
h.add(40, now - 500 * DAY, "essay", answer(40))
gone = h.delete(40, now - 400 * DAY)
check("with no days set a deleted answer has no end", gone == {"deleted": now - 400 * DAY, "until": None}, gone)
check("...it stays through every look and every pruning", h.prune(now) == 0 and ids(h.deleted_list(now=now)) == [40]
      and h.deleted_list(now=now)[0]["until"] is None and h.deleted_count(now=now) == 1)
check("...until it is put back, or emptied by hand", h.purge() == [40] and h.deleted_count(now=now) == 0)
f = new_file("age")
h = History(f, days=90, max_mb=0, deleted_days=7)   # the history's own age, and a week in Recently deleted
h.add(45, now - 89.5 * DAY, "essay", answer(45))
h.add(46, now - 89.5 * DAY, "essay", answer(46))
h.delete(45, now)
check("an answer about to age out, deleted now, is held its whole week: the history's age does not take it first",
      h.prune(now + DAY) == 1 and ids(h.deleted_list(now=now + DAY)) == [45] and h.restore(45, now + DAY) is not None,
      rows_in(f))
check("...while one not deleted ages out as before", h.get(46) is None)

print("\n[the size cap]")
f = new_file("size")
CAP = 0.3   # MB: about nineteen answers of 8 KB (each is kept twice: as it was, and as the words a search looks in)
h = History(f, days=0, max_mb=CAP)
body = "x" * 8000
for i in range(50, 64):   # fourteen answers, well under the cap
    h.add(i, now - (200 - i) * 60, "essay", answer(i, body + str(i)))
h.star(61, True)
for k, i in enumerate(range(54, 64)):   # the ten newest deleted one after the other, one of them starred; the four oldest are still shown
    h.delete(i, now - 1000 + k)
check("under the cap nothing goes", h.deleted_count(now=now) == 10 and ids(h.query()) == [53, 52, 51, 50], ids(h.query()))
i = 100
while h.deleted_count(now=now) == 10 and i < 140:   # more answers, one at a time, until the file is past its cap
    h.add(i, now - (200 - i) * 60, "essay", answer(i, body + str(i)))
    i += 1
left, kept = ids(h.deleted_list(now=now)), ids(h.query(limit=200))
check("past the cap what was deleted goes first, the longest deleted first, its star no reason to keep it",
      left == [63, 62], [left, i])
check("...and no answer still shown goes for it, not even the oldest", kept == [*range(i - 1, 99, -1), 53, 52, 51, 50], kept)
while h.deleted_count(now=now) and i < 180:
    h.add(i, now - (200 - i) * 60, "essay", answer(i, body + str(i)))
    i += 1
kept = ids(h.query(limit=200))
check("the rest of Recently deleted goes before the oldest answer shown", h.deleted_count(now=now) == 0 and 50 in kept, kept[-5:])
while 50 in ids(h.query(limit=200)) and i < 240:
    h.add(i, now - (200 - i) * 60, "essay", answer(i, body + str(i)))
    i += 1
check("...and with Recently deleted empty the oldest shown go, as before", 50 not in ids(h.query(limit=200)) and i < 240, i)

print("\n[a new install, and no file]")
f = new_file("fresh")
h = History(f)
h.add(1, now, "essay", answer(1))
h.delete(1)
check("a store whose only answer is in Recently deleted is not a new install", h.fresh() is False)
none = History(None)
check("no file, nothing to delete or put back", none.delete(1) is None and none.restore(1) is None and none.purge() == []
      and none.purge(1) == [] and none.deleted_count() == 0 and none.deleted_list() == [] and none.deleted_get(1) is None
      and none.deleted_ids() == [])

print("\n[a server that starts]")
start_logs = tempfile.mkdtemp(prefix="sidenote-delete-start-")
hs = History(Path(start_logs) / "history.sqlite")
for i in (7, 8, 9):
    hs.add(i, now - i, "essay", answer(i))
hs.delete(7)
hs.delete(9)
hs.restore(9)
out = subprocess.run([sys.executable, "-c", "import server.app as A; print('CARDS', sorted(A.STATE.deleted_cards.items()))"],
                     cwd=ROOT, env={**os.environ, "SIDENOTE_LOG_DIR": start_logs}, capture_output=True, text=True, timeout=180)
check("it takes what Recently deleted holds as deleted: a problem of one seen again points back to nothing",
      "CARDS [(7, True)]" in out.stdout, [out.stdout[-300:], out.stderr[-300:]])

print("\n[the panel's socket]")
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server import repeats  # noqa: E402
from server.i18n import t  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

SETTINGS.path = None    # nothing written beside the logs


class Panel:
    """Reads every message one panel's socket gets, in a thread."""

    def __init__(self, ws):
        self.ws, self.msgs = ws, []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.msgs.append(json.loads(self.ws.receive_text()))
        except Exception:
            pass

    def wait(self, pred, timeout=10, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in self.msgs[after:]:
                if pred(m):
                    return m
            time.sleep(0.05)
        return None

    def got(self, kinds, after=0) -> list:
        """The messages of these kinds that came since `after`, once there was time for one to come."""
        time.sleep(0.4)
        return [m for m in self.msgs[after:] if m.get("type") in kinds]


def is_(kind, i=None):
    return lambda m: m.get("type") == kind and (i is None or m.get("id") == i)


def until(cond, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end and not cond():
        time.sleep(0.05)
    return bool(cond())


def png_b64(seed=0):
    """A screen with a few dark bars standing for lines of text (the change detector reads edges)."""
    im = Image.new("RGB", (640, 400), "white")
    d = ImageDraw.Draw(im)
    for r in range(6):
        d.rectangle([40, 40 + r * 40 + seed, 40 + 300 + (r * 37 + seed) % 200, 52 + r * 40 + seed], fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def seen(card):
    """A problem answered as `card`, as the server remembers it to know it when it is seen again: a picture and its words."""
    pic = np.zeros((40, 40), dtype=np.uint8)
    A.PIPELINE.recent.items.append(repeats.Seen(card, pic, pic, time.time()))
    A.PIPELINE.recent.add_words(card, f"the problem of answer {card}")
    A.STATE.answers[card] = {"id": card, "text": f"TYPE: essay\nANSWER: {card}", "frame": None}


def remembered(card) -> bool:
    """Whether the server still holds anything of that problem: its picture, its words, or its answer's text."""
    return (any(s.card == card for s in A.PIPELINE.recent.items) or any(w[0] == card for w in A.PIPELINE.recent.words)
            or card in A.STATE.answers)


KINDS = ("answer_deleted", "answer_restored", "deleted_cleared", "notice")
SEQ = int(time.time() * 1000) - 10_000_000   # ids well before any this server gives (it numbers from the time it starts)
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    check("the server holds a deleted answer for seven days unless told otherwise", A.CONFIG.deleted_days == 7
          and A.HISTORY.deleted_days == 7, [A.CONFIG.deleted_days, A.HISTORY.deleted_days])
    for k in range(3):   # three answers, kept as the worker keeps them
        A.HISTORY.add(SEQ + k, now - 60 + k, "essay", answer(k))
    A.HISTORY.star(SEQ + 1, True)
    A.HISTORY.update(SEQ + 1, turn={"id": SEQ + 50, "q": "why this way?", "text": "because", "kind": "ask"})
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws1, \
            client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws2:
        p1, p2 = Panel(ws1), Panel(ws2)
        p1.wait(is_("usage"))
        p2.wait(is_("usage"))

        def tell(ws, **msg):
            """One message from a panel; where each panel's messages stood before it, to read what came after."""
            marks = len(p1.msgs), len(p2.msgs)
            ws.send_text(json.dumps(msg))
            return marks

        n1, n2 = tell(ws1, type="answer_delete", id=SEQ + 1)
        a, b = p1.wait(is_("answer_deleted", SEQ + 1), after=n1), p2.wait(is_("answer_deleted", SEQ + 1), after=n2)
        check("a delete from one panel reaches it and a second panel", a is not None and b is not None, [p1.msgs[n1:], p2.msgs[n2:]])
        check("...saying Recently deleted holds it, until when, and how many it holds now", b is not None and b.get("kept") is True
              and abs((b.get("until") or 0) - (time.time() + 7 * DAY)) < 120 and b.get("n") == 1, b)
        check("...and that there is no answer to ask about (none was the last)", b is not None and b.get("can_ask") is False, b)
        check("the history no longer lists it", A.HISTORY.get(SEQ + 1) is None
              and ids(client.get("/history").json()["answers"]) == [SEQ + 2, SEQ]
              and client.get("/history", params={"starred": 1}).json()["answers"] == [])
        days = client.get("/history/days").json()
        check("/history/days counts it out of the days and the starred, and into Recently deleted, with the days one is held",
              sum(d["n"] for d in days["days"]) == 2 and days["starred"] == 0 and days["deleted"] == 1
              and days["deleted_days"] == A.CONFIG.deleted_days, days)
        held = client.get("/history/deleted").json()
        check("/history/deleted gives it whole, with its star, its follow-up, and when it goes",
              ids(held["answers"]) == [SEQ + 1] and held["days"] == A.CONFIG.deleted_days and held["answers"][0]["starred"] is True
              and [x["q"] for x in held["answers"][0]["turns"]] == ["why this way?"]
              and held["answers"][0]["until"] == (b or {}).get("until"), held)
        brief = client.get("/history/deleted?brief=1").json()["answers"]
        check("...and brief, as the panel's sheet asks, without the thumbnail and the follow-ups it does not show",
              ids(brief) == [SEQ + 1] and "thumb" not in brief[0] and "turns" not in brief[0] and brief[0]["starred"] is True
              and brief[0]["text"] == held["answers"][0]["text"] and brief[0]["until"] == held["answers"][0]["until"], brief)
        check("the server remembers it as deleted", A.STATE.deleted_cards.get(SEQ + 1) is True, A.STATE.deleted_cards)
        n1, n2 = tell(ws2, type="answer_delete", id=SEQ + 1)   # pressed in the other panel too, a moment later
        check("deleted twice, no panel is told again", p1.got(KINDS, n1) == [] and p2.got(KINDS, n2) == [],
              [p1.msgs[n1:], p2.msgs[n2:]])
        n1, n2 = tell(ws2, type="answer_restore", id=SEQ + 1)   # put back from the second panel
        a, b = p1.wait(is_("answer_restored", SEQ + 1), after=n1), p2.wait(is_("answer_restored", SEQ + 1), after=n2)
        check("put back from the second panel, both panels hear it", a is not None and b is not None, [p1.msgs[n1:], p2.msgs[n2:]])
        check("...with the answer as it was, for a panel that did not show it: its star and its follow-up",
              a is not None and (a.get("answer") or {}).get("id") == SEQ + 1 and a["answer"]["starred"] is True
              and [x["q"] for x in a["answer"]["turns"]] == ["why this way?"] and a.get("n") == 0, a)
        check("...and the history lists it again, starred", ids(A.HISTORY.query()) == [SEQ + 2, SEQ + 1, SEQ]
              and ids(A.HISTORY.query(starred=True)) == [SEQ + 1] and SEQ + 1 not in A.STATE.deleted_cards)
        n1, n2 = tell(ws1, type="answer_restore", id=SEQ + 1)
        said = p1.wait(is_("notice"), after=n1)
        check("put back twice, that panel is told there is nothing to put back", said is not None and said.get("level") == "warn"
              and said.get("text") == t("Not put back: Recently deleted does not hold this answer"), said)
        check("...and no panel hears of an answer put back", p1.got(("answer_restored",), n1) == [] and p2.got(KINDS, n2) == [],
              [p1.msgs[n1:], p2.msgs[n2:]])
        n1, n2 = len(p1.msgs), len(p2.msgs)
        for bad in ({"type": "answer_delete", "id": str(SEQ)}, {"type": "answer_delete", "id": True}, {"type": "answer_delete"},
                    {"type": "answer_restore", "id": "x"}, {"type": "answer_purge", "id": None}, {"type": "answer_purge", "id": 1.5}):
            ws1.send_text(json.dumps(bad))
        check("a malformed message changes nothing and says nothing", p1.got(KINDS, n1) == [] and p2.got(KINDS, n2) == []
              and ids(A.HISTORY.query()) == [SEQ + 2, SEQ + 1, SEQ] and A.HISTORY.deleted_count() == 0, p1.msgs[n1:])

        print("\n[an answer still being written, and one the history never held]")
        A.LIVE[SEQ + 2] = {"start": {"type": "analysis_start", "id": SEQ + 2}, "text": "", "stage": None, "at": time.time()}
        n1, n2 = tell(ws1, type="answer_delete", id=SEQ + 2)
        said = p1.wait(is_("notice"), after=n1)
        check("an answer still being written is not deleted, and that panel is told why", said is not None and said.get("level") == "warn"
              and said.get("text") == t("Not deleted: this answer is still being written"), said)
        check("...no panel drops it, and the history keeps it", p1.got(("answer_deleted",), n1) == [] and p2.got(KINDS, n2) == []
              and A.HISTORY.get(SEQ + 2) is not None and SEQ + 2 not in A.STATE.deleted_cards)
        A.LIVE.pop(SEQ + 2, None)
        # A card of an earlier run the history never held (an error's, one written with Keep answers off), still on a panel
        # open across the restart: this server holds nothing of it, and a panel's delete takes it from every panel all the
        # same (a program naming an id no answer had is refused: api_check.py)
        n1, n2 = tell(ws1, type="answer_delete", id=SEQ + 900)
        a, b = p1.wait(is_("answer_deleted", SEQ + 900), after=n1), p2.wait(is_("answer_deleted", SEQ + 900), after=n2)
        check("an answer the history never held is dropped by every panel, and said to be held nowhere",
              a is not None and b is not None and b.get("kept") is False and b.get("until") is None and b.get("n") == 0, [a, b])
        check("...the server remembers that only a panel can put it back", A.STATE.deleted_cards.get(SEQ + 900) is False)
        n1, n2 = tell(ws1, type="answer_restore", id=SEQ + 900)
        a, b = p1.wait(is_("answer_restored", SEQ + 900), after=n1), p2.wait(is_("answer_restored", SEQ + 900), after=n2)
        check("its Undo reaches every panel, with no answer from the history: each puts back the card it showed",
              a is not None and b is not None and b.get("answer") is None and "answer" in b, [a, b])
        n1, n2 = tell(ws1, type="answer_restore", id=SEQ + 900)
        said = p1.wait(is_("notice"), after=n1)
        check("...and once put back, there is nothing more to put back", said is not None
              and said.get("text") == t("Not put back: Recently deleted does not hold this answer")
              and p2.got(KINDS, n2) == [], said)

        print("\n[deleted for good, and Recently deleted emptied]")
        seen(SEQ)       # the server knows this answer's problem when it sees it again
        seen(SEQ + 2)   # and this one's
        n1, n2 = tell(ws1, type="answer_delete", id=SEQ)
        p1.wait(is_("answer_deleted", SEQ), after=n1)
        check("a deleted answer's problem is still known, so it is not solved again by itself", remembered(SEQ))
        n1, n2 = tell(ws1, type="answer_purge", id=SEQ)
        a, b = p1.wait(is_("deleted_cleared", SEQ), after=n1), p2.wait(is_("deleted_cleared", SEQ), after=n2)
        check("deleted for good from one panel, both hear it with how many went and how many are left",
              a is not None and b is not None and b.get("gone") == 1 and b.get("n") == 0, [a, b])
        said = p1.wait(is_("notice"), after=n1)
        check("...the panel that asked is told it is done, the other is not", said is not None and said.get("level") == "done"
              and said.get("text") == t("Deleted for good") and p2.got(("notice",), n2) == [], [said, p2.msgs[n2:]])
        check("...the history holds nothing of it", A.HISTORY.get(SEQ) is None and A.HISTORY.deleted_get(SEQ) is None
              and ids(A.HISTORY.query()) == [SEQ + 2, SEQ + 1])
        check("...nor does the server: its text, its problem's picture and words, its id among the deleted",
              not remembered(SEQ) and SEQ not in A.STATE.deleted_cards and remembered(SEQ + 2), A.STATE.deleted_cards)
        n1, n2 = tell(ws1, type="answer_purge", id=SEQ)
        said = p1.wait(is_("notice"), after=n1)
        check("asked again, that panel is told Recently deleted does not hold it", said is not None and said.get("level") == "warn"
              and said.get("text") == t("Not deleted: Recently deleted does not hold this answer")
              and p2.got(KINDS, n2) == [], said)
        n1, n2 = tell(ws1, type="answer_purge", id=SEQ + 1)   # an answer still shown
        said = p1.wait(is_("notice"), after=n1)
        check("an answer still shown is not deleted for good: it is refused the same way, and kept", said is not None
              and said.get("text") == t("Not deleted: Recently deleted does not hold this answer")
              and A.HISTORY.get(SEQ + 1) is not None and p1.got(("deleted_cleared",), n1) == [], said)
        n1, n2 = tell(ws1, type="answer_restore", id=SEQ)
        said = p1.wait(is_("notice"), after=n1)
        check("...and what was deleted for good cannot be put back", said is not None
              and said.get("text") == t("Not put back: Recently deleted does not hold this answer"), said)
        for i in (SEQ + 1, SEQ + 2):
            n1, n2 = tell(ws1, type="answer_delete", id=i)
            p2.wait(is_("answer_deleted", i), after=n2)
        n1, n2 = tell(ws2, type="deleted_clear")
        a, b = p1.wait(is_("deleted_cleared"), after=n1), p2.wait(is_("deleted_cleared"), after=n2)
        check("Recently deleted emptied from one panel, both hear it: no id, how many went, none left",
              a is not None and b is not None and a.get("id") is None and a.get("gone") == 2 and a.get("n") == 0, [a, b])
        said = p2.wait(is_("notice"), after=n2)
        check("...the panel that asked is told it is emptied", said is not None and said.get("level") == "done"
              and said.get("text") == t("Recently deleted emptied") and p1.got(("notice",), n1) == [], said)
        check("...nothing of them is left in the history or in the server", A.HISTORY.query() == [] and A.HISTORY.deleted_list() == []
              and not remembered(SEQ + 2) and not ({SEQ + 1, SEQ + 2} & set(A.STATE.deleted_cards)), A.STATE.deleted_cards)
        n1, n2 = tell(ws2, type="deleted_clear")
        said = p2.wait(is_("notice"), after=n2)
        check("emptied again, it says there was nothing", said is not None and said.get("level") == "info"
              and said.get("text") == t("Recently deleted is empty"), said)

        print("\n[the last answer]")
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_confirm=False, history_keep=True)
        A.STATE.local, A.STATE.agent = {"ok": True}, {"ok": True}
        with client.websocket_connect("ws://127.0.0.1:8777/ingest", headers=ORIGIN) as cap:
            cap.send_text(json.dumps({"type": "hello", "info": "capture/test", "screen": True, "audio": False,
                                      "no_audio": True, "monitor": 1, "flags": {}}))
            n1 = len(p1.msgs)
            cap.send_text(json.dumps({"type": "frame", "data": png_b64()}))
            done = p1.wait(is_("analysis_done"), timeout=30, after=n1)
            check("a screen from the capture program is answered", done is not None, [m.get("type") for m in p1.msgs[n1:]][-8:])
            seq = done["id"] if done else -1
            until(lambda: A.HISTORY.get(seq) is not None)   # the history's own thread keeps it

            def ask(text):
                """A question about the last answer, from the first panel: its card's start, and how it ended."""
                at = len(p1.msgs)
                ws1.send_text(json.dumps({"type": "ask", "text": text}))
                start = p1.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") == "ask", timeout=20, after=at)
                end = start and p1.wait(lambda m: m.get("type") in ("analysis_done", "error", "analysis_cancelled")
                                        and m.get("id") == start["id"], timeout=30, after=at)
                return start, end

            start, end = ask("why this way?")
            check("a question about it is answered", start is not None and start.get("about") == seq and end is not None
                  and end["type"] == "analysis_done", [start, end and end.get("type")])
            until(lambda: len((A.HISTORY.get(seq) or {}).get("turns") or []) == 1)

            # A question still being answered when its answer is deleted: the stand-in never answers, so it is caught mid-way
            real_followup = A.followup

            async def never(*a, **k):
                await asyncio.Event().wait()
            A.followup = never
            n1 = len(p1.msgs)
            ws1.send_text(json.dumps({"type": "ask", "text": "and after that?"}))
            asked = p1.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") == "ask", timeout=20, after=n1)
            n1, n2 = tell(ws1, type="answer_delete", id=seq)
            a, b = p1.wait(is_("answer_deleted", seq), after=n1), p2.wait(is_("answer_deleted", seq), after=n2)
            A.followup = real_followup
            check("the last answer deleted: every panel is told there is no answer to ask about now",
                  a is not None and b is not None and a.get("kept") is True and a.get("can_ask") is False and b.get("can_ask") is False, [a, b])
            stopped = asked and p2.wait(lambda m: m.get("type") == "analysis_cancelled" and m.get("id") == asked["id"], after=n2)
            check("...the question still being answered about it is stopped, as its answer was deleted",
                  bool(stopped) and stopped.get("reason") == "deleted", [asked, stopped])
            check("...the server has no last answer, and holds this one for Undo with what was asked about it",
                  A.STATE.last_result is None and A.STATE.thread == [] and (A.STATE.deleted_last or {}).get("last", {}).get("id") == seq
                  and [q for q, _ in A.STATE.deleted_last["thread"]] == ["why this way?"], A.STATE.deleted_last and A.STATE.deleted_last["thread"])
            check("...and a panel that opens now is told the same", client.get("/api/v1/status").json()["status"]["can_ask"] is False)
            n1 = len(p1.msgs)
            ws1.send_text(json.dumps({"type": "ask", "text": "still there?"}))
            said = p1.wait(is_("notice"), after=n1)
            check("a question asked meanwhile is told there is nothing to ask about", said is not None
                  and said.get("text") == t("No problem analyzed yet to ask about")
                  and not any(m.get("type") == "analysis_start" for m in p1.msgs[n1:]), said)
            n1, n2 = tell(ws1, type="answer_restore", id=seq)   # Undo
            a, b = p1.wait(is_("answer_restored", seq), after=n1), p2.wait(is_("answer_restored", seq), after=n2)
            check("Undo: it is the last answer again, and every panel is told a question can be asked",
                  a is not None and b is not None and a.get("can_ask") is True and (A.STATE.last_result or {}).get("id") == seq
                  and A.STATE.deleted_last is None, [a, A.STATE.last_result and A.STATE.last_result.get("id")])
            check("...with the follow-up it had, and not the one that was stopped",
                  a is not None and [x["q"] for x in (a.get("answer") or {}).get("turns", [])] == ["why this way?"]
                  and [q for q, _ in A.STATE.thread] == ["why this way?"], [a, A.STATE.thread])
            start, end = ask("so, again?")
            check("...and the next question is about it, with what was asked before", start is not None and start.get("about") == seq
                  and end is not None and end["type"] == "analysis_done" and [q for q, _ in A.STATE.thread] == ["why this way?", "so, again?"],
                  [start, end and end.get("type"), A.STATE.thread])
            until(lambda: len((A.HISTORY.get(seq) or {}).get("turns") or []) == 2)

            # A question whose answer is done and only being sent as its answer is deleted: it ends by itself, and is kept
            # with the deleted answer, so that Undo brings it back too. The end is held open here while the delete lands
            gate = {"in": False, "open": False}
            real_success = A.note_success

            async def slow_success(*a, **k):
                gate["in"] = True
                while not gate["open"]:
                    await asyncio.sleep(0.02)
                await real_success(*a, **k)
            A.note_success = slow_success
            n1 = len(p1.msgs)
            ws1.send_text(json.dumps({"type": "ask", "text": "one more?"}))
            late = p1.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") == "ask", timeout=20, after=n1)
            inside = until(lambda: gate["in"], 20)
            n1, n2 = tell(ws1, type="answer_delete", id=seq)
            a = p1.wait(is_("answer_deleted", seq), after=n1)
            gate["open"] = True
            ended = late and p1.wait(lambda m: m.get("type") in ("analysis_done", "analysis_cancelled", "error")
                                     and m.get("id") == late["id"], timeout=20, after=n1)
            A.note_success = real_success
            check("a question already answered when its answer is deleted is let end", inside and a is not None and bool(ended)
                  and ended["type"] == "analysis_done", [inside, a, ended])
            check("...and is held with the deleted answer, in what the next question carries and in Recently deleted",
                  until(lambda: [q for q, _ in (A.STATE.deleted_last or {}).get("thread", [])][-1:] == ["one more?"]
                        and [x["q"] for x in (A.HISTORY.deleted_get(seq) or {}).get("turns", [])][-1:] == ["one more?"]),
                  [A.STATE.deleted_last and A.STATE.deleted_last["thread"], A.HISTORY.deleted_get(seq)])
            n1, n2 = tell(ws2, type="answer_restore", id=seq)
            a = p1.wait(is_("answer_restored", seq), after=n1)
            check("Undo brings it back with all three", a is not None
                  and [x["q"] for x in (a.get("answer") or {}).get("turns", [])] == ["why this way?", "so, again?", "one more?"]
                  and [q for q, _ in A.STATE.thread] == ["why this way?", "so, again?", "one more?"], [a, A.STATE.thread])

            # Deleted, and then a newer answer: Undo puts the card back, and the newer answer stays the one asked about
            n1, n2 = tell(ws1, type="answer_delete", id=seq)
            p1.wait(is_("answer_deleted", seq), after=n1)
            n1 = len(p1.msgs)
            ws1.send_text(json.dumps({"type": "reanalyze"}))
            again = p1.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") != "ask", timeout=20, after=n1)
            redone = again and p1.wait(is_("analysis_done", again["id"]), timeout=30, after=n1)
            seq2 = again["id"] if again else -2
            check("with its answer deleted, Reanalyze solves the problem on the screen again", bool(redone) and seq2 != seq,
                  [again, [m.get("type") for m in p1.msgs[n1:]][-6:]])
            check("...and the deleted answer is no longer held as the last", A.STATE.deleted_last is None
                  and (A.STATE.last_result or {}).get("id") == seq2)
            until(lambda: A.HISTORY.get(seq2) is not None)
            n1, n2 = tell(ws1, type="answer_restore", id=seq)
            a = p1.wait(is_("answer_restored", seq), after=n1)
            check("put back after a newer answer, the newer one stays the one asked about", a is not None and a.get("can_ask") is True
                  and (a.get("answer") or {}).get("id") == seq and (A.STATE.last_result or {}).get("id") == seq2 and A.STATE.thread == [],
                  [a and a.get("can_ask"), A.STATE.last_result and A.STATE.last_result.get("id"), A.STATE.thread])

            # The last answer held for Undo loses what the last answer loses when the screen or the sound is switched off
            last = A.STATE.last_result
            last.update(problem_text="the problem as it was read off the screen", words="the problem in words", screen=object())
            check("(the last answer holds its screen)", last.get("frame") is not None)
            n1, n2 = tell(ws1, type="answer_delete", id=seq2)
            p1.wait(is_("answer_deleted", seq2), after=n1)
            held = (A.STATE.deleted_last or {}).get("last") or {}
            check("(and is held, screen and all, when deleted)", held.get("id") == seq2 and held.get("frame") is not None)
            ws1.send_text(json.dumps({"type": "capture_set", "screen": False}))
            check("the screen switched off: the answer held for Undo keeps no screen, nor what was read off it",
                  until(lambda: A.STATE.screen_on is False and held.get("frame") is None)
                  and not ({"screen", "problem_text", "words"} & set(held)), sorted(held))
            held["words"] = "a question that was heard"
            ws1.send_text(json.dumps({"type": "capture_set", "audio": False}))
            check("the sound switched off: nor the words that were heard", until(lambda: A.STATE.audio_on is False and "words" not in held),
                  sorted(held))
            n1, n2 = tell(ws1, type="answer_restore", id=seq2)
            a = p1.wait(is_("answer_restored", seq2), after=n1)
            check("...and Undo makes it the last answer as it is now, without them", a is not None and a.get("can_ask") is True
                  and A.STATE.last_result is held and held.get("frame") is None, a)
            ws1.send_text(json.dumps({"type": "capture_set", "screen": True, "audio": True}))
            until(lambda: A.STATE.screen_on and A.STATE.audio_on)

            print("\n[its problem seen again]")
            # The pipeline knows a problem it has answered when the screen shows it again (server/repeats.py), and says
            # whose it is instead of solving it. Here it is made to say so of every next screen, whatever that shows
            again = {"card": seq}
            real_solve = A.PIPELINE.solve

            async def seen_again(*a, **k):
                raise A.Repeat(again["card"], None, 0.9)
            A.PIPELINE.solve = seen_again

            def sight(seed):
                """Another screen from the capture program: how its card ended, the notices said with it, and whether
                anything was answered."""
                at = len(p1.msgs)
                cap.send_text(json.dumps({"type": "frame", "data": png_b64(seed)}))
                end = p1.wait(lambda m: m.get("type") == "analysis_cancelled" and m.get("reason") == "repeat", timeout=30, after=at)
                time.sleep(0.4)   # the notice comes after it
                since = p1.msgs[at:]
                return (end or {}, [(m.get("of"), m.get("text")) for m in since if m.get("type") == "notice"],
                        any(m.get("type") == "analysis_done" for m in since))
            try:
                end, said, solved = sight(9)
                check("an answer's problem seen again points back to its card, and says so once", end.get("of") == seq
                      and said == [(seq, t("Already solved, not solved again · Reanalyze to solve it again"))] and not solved, [end, said])
                check("...and a question is about that answer now", (A.STATE.last_result or {}).get("id") == seq,
                      A.STATE.last_result and A.STATE.last_result.get("id"))
                n1, n2 = tell(ws1, type="answer_delete", id=seq)
                a = p1.wait(is_("answer_deleted", seq), after=n1)
                check("(that answer is deleted, with its problem still on the screen)", a is not None and a.get("can_ask") is False, a)
                end, said, solved = sight(17)
                check("seen again once its answer is deleted, it points back to no card, and is not solved again by itself",
                      end.get("reason") == "repeat" and "of" not in end and not solved, end)
                check("...it says that the answer was deleted, and what solves it again", said == [
                      (None, t("Solved before, and that answer was deleted · Reanalyze to solve it again"))], said)
                check("...no answer is the last for it, and the deleted one is still held for Undo", A.STATE.last_result is None
                      and (A.STATE.deleted_last or {}).get("last", {}).get("id") == seq, A.STATE.deleted_last)
                end, said, solved = sight(23)
                check("...seen once more, it is said no second time", end.get("reason") == "repeat" and "of" not in end and said == [],
                      [end, said])
                n1, n2 = tell(ws1, type="answer_restore", id=seq)
                a = p1.wait(is_("answer_restored", seq), after=n1)
                end, said, solved = sight(31)
                check("put back, its problem seen again points back to its card once more, and says so", a is not None
                      and end.get("of") == seq and said == [(seq, t("Already solved, not solved again · Reanalyze to solve it again"))],
                      [a and a.get("can_ask"), end, said])
                n1, n2 = tell(ws1, type="answer_delete", id=seq)   # the last answer again, deleted and held for Undo
                p1.wait(is_("answer_deleted", seq), after=n1)
                again["card"] = seq2                               # and the screen goes back to the other answer's problem
                end, said, solved = sight(43)
                check("another answer's problem seen meanwhile makes that answer the last, and the deleted one is no longer held as it",
                      end.get("of") == seq2 and (A.STATE.last_result or {}).get("id") == seq2 and A.STATE.deleted_last is None,
                      [end, A.STATE.last_result and A.STATE.last_result.get("id"), A.STATE.deleted_last])
                n1, n2 = tell(ws1, type="answer_restore", id=seq)
                a = p1.wait(is_("answer_restored", seq), after=n1)
                check("...so Undo puts its card back and leaves the question where it is", a is not None and a.get("can_ask") is True
                      and (A.STATE.last_result or {}).get("id") == seq2, [a and a.get("can_ask"), A.STATE.last_result and A.STATE.last_result.get("id")])
            finally:
                A.PIPELINE.solve = real_solve

        print("\n[Clear history]")
        n1, n2 = tell(ws1, type="answer_delete", id=seq)
        p1.wait(is_("answer_deleted", seq), after=n1)
        n1, n2 = tell(ws1, type="answer_delete", id=seq2)
        p1.wait(is_("answer_deleted", seq2), after=n1)
        check("(two answers are in Recently deleted, one of them held for Undo)", A.HISTORY.deleted_count() == 2
              and A.STATE.deleted_last is not None and len(A.STATE.deleted_cards) >= 2)
        n1, n2 = tell(ws1, type="history_clear")
        p1.wait(is_("history_cleared"), after=n1)
        p1.wait(is_("notice"), after=n1)
        days = client.get("/history/days").json()
        check("Clear history takes Recently deleted too, at once", client.get("/history/deleted").json()["answers"] == []
              and days["deleted"] == 0 and days["days"] == [] and rows_in(Path(LOGS) / "history.sqlite") == [], days)
        check("...and what the server held of it: the ids, and the answer held for Undo", A.STATE.deleted_cards == {}
              and A.STATE.deleted_last is None, [A.STATE.deleted_cards, A.STATE.deleted_last])
        n1, n2 = tell(ws1, type="answer_restore", id=seq)
        said = p1.wait(is_("notice"), after=n1)
        check("...so nothing of it is put back", said is not None
              and said.get("text") == t("Not put back: Recently deleted does not hold this answer"), said)

print("\n[the ids remembered as deleted]")
A.STATE.deleted_cards.clear()
for i in range(A.DELETED_CARDS_MAX + 100):
    A.note_deleted(i, True)
check("they are bounded: the oldest go", len(A.STATE.deleted_cards) == A.DELETED_CARDS_MAX and 99 not in A.STATE.deleted_cards
      and 100 in A.STATE.deleted_cards and A.DELETED_CARDS_MAX + 99 in A.STATE.deleted_cards, len(A.STATE.deleted_cards))
A.note_deleted(100, False)   # said again: the newest now, so the next one past the bound takes another
A.note_deleted(A.DELETED_CARDS_MAX + 100, True)
check("one said again counts as the newest, with what is said of it now", A.STATE.deleted_cards.get(100) is False
      and 101 not in A.STATE.deleted_cards and len(A.STATE.deleted_cards) == A.DELETED_CARDS_MAX)
A.STATE.deleted_cards.clear()

print("\n[an answer deleted for good, past the bound of the ids remembered as purged]")
# Its card's id stayed among the ids given out: once more answers than the bound had gone for good after it, a program's
# delete of it was taken (200, every panel told) where it has no answer
A.STATE.cards.clear()
A.STATE.purged.clear()
A.note_card(777001)
A.forget_purged([777001] + list(range(900000, 900000 + A.DELETED_CARDS_MAX + 1)))
check("an answer deleted for good has no answer still, once its id is past the bound of those remembered as purged",
      777001 not in A.STATE.purged and not asyncio.run(A.had_answer(777001)), [777001 in A.STATE.cards, 777001 in A.STATE.purged])
A.STATE.cards.clear()
A.STATE.purged.clear()

print("\n[what the final review found]")
f = new_file("review")
h = History(f)
for i in (1, 2, 3):
    h.add(i, time.time() - (4 - i) * 60, "essay", answer(i))
h.delete(2)
h.deleted_count()                            # a read of Recently deleted, whose expiry deleted nothing
check("a read of Recently deleted leaves no transaction open: the file's write lock is not held after it",
      not h._db.in_transaction, h._db.in_transaction)
# the days' own query (days_list), its plan as SQLite makes it
plan = " ".join(str(r) for r in h._db.execute("EXPLAIN QUERY PLAN SELECT day, COUNT(*), MIN(ts), MAX(ts) FROM answers"
                                                  " WHERE deleted IS NULL GROUP BY day ORDER BY day DESC"))
check("the days of the answers shown are read from an index of their own, not row by row", "answers_day_shown" in plan, plan)
# A file from elsewhere (./sidenote restore) whose kept answer names another id, in words: the id given is the row's own
h._db.execute("UPDATE answers SET data = json_set(data, '$.id', '\"><meta http-equiv=refresh>') WHERE id = 3")
h._db.commit()
check("an answer's id is the row's own number, whatever its kept words say", [r["id"] for r in h.query()] == [3, 1]
      and h.get(3)["id"] == 3, [r["id"] for r in h.query()])
h._db.execute("UPDATE answers SET data = json_set(data, '$.id', 'x') WHERE id = 2")
h._db.commit()
check("...in Recently deleted too, and put back", [r["id"] for r in h.deleted_list()] == [2] and h.deleted_get(2)["id"] == 2
      and h.restore(2)["id"] == 2, [r["id"] for r in h.deleted_list()])

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
