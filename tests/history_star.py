"""Starred answers in the server's history (server/history.py): a history.sqlite from 0.1.0 gaining its star with its rows
kept, a star set and taken off over the panel's socket and seen by a second panel, a refused id, the starred answers
alone from /history, the pruning that keeps them past the age limit and outside the size cap, and Clear history.

    .venv/bin/python tests/history_star.py
"""
import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

# The server's environment, set before it is imported: stand-in engines, no speech, no runner, a log folder of its own
LOGS = tempfile.mkdtemp(prefix="sidenote-star-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_LOG_DIR=LOGS,
                  SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_AGENT="mock")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server.history import History  # noqa: E402

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}   # the panel's own page, which /panel takes
DAY = 86400.0

# The table and indexes server/history.py made in 0.1.0, before an answer had a star
OLD_SCHEMA = ["CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL,"
              " kind TEXT NOT NULL, words TEXT NOT NULL, data TEXT NOT NULL)",
              "CREATE INDEX IF NOT EXISTS answers_ts ON answers (ts)",
              "CREATE INDEX IF NOT EXISTS answers_day ON answers (day, ts)",
              "CREATE INDEX IF NOT EXISTS answers_kind ON answers (kind, ts)"]


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


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


def rest_bytes(path: Path) -> int:
    """The pages the answers that are not starred take, as the cap counts them: the pages in use less the starred bytes."""
    db = sqlite3.connect(str(path))
    used = (db.execute("PRAGMA page_count").fetchone()[0] - db.execute("PRAGMA freelist_count").fetchone()[0]) \
        * db.execute("PRAGMA page_size").fetchone()[0]
    starred = db.execute("SELECT COALESCE(SUM(LENGTH(CAST(data AS BLOB)) + LENGTH(CAST(words AS BLOB))), 0) FROM answers"
                         " WHERE starred = 1").fetchone()[0]
    db.close()
    return used - starred


print("\n[a history file from 0.1.0]")
old = Path(tempfile.mkdtemp(prefix="sidenote-star-old-")) / "history.sqlite"
db = sqlite3.connect(str(old))
for sql in OLD_SCHEMA:
    db.execute(sql)
now = time.time()
for i in range(1, 4):   # three answers kept by 0.1.0, as its add() wrote them
    data = {**answer(i), "id": i, "ts": now - i * 60, "kind": "essay"}
    db.execute("INSERT INTO answers (id, ts, day, kind, words, data) VALUES (?, ?, ?, ?, ?, ?)",
               (i, now - i * 60, time.strftime("%Y-%m-%d", time.localtime(now - i * 60)), "essay",
                data["text"].lower(), json.dumps(data, ensure_ascii=False)))
db.commit()
db.close()
SAID.lines.clear()
h = History(old)
cols = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(answers)")]
check("an old file gains the starred column when it opens", cols.count("starred") == 1, cols)
rows = h.query()
check("...with its rows kept, as they were", ids(rows) == [1, 2, 3] and rows[2]["text"].endswith("풀이 3"), ids(rows))
check("...and none of them starred", [r["starred"] for r in rows] == [False, False, False], rows[:1])
check("the log says it once", sum("gained their star" in x for x in SAID.lines) == 1, SAID.lines)
indexes = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA index_list(answers)")]
check("the Starred choice has an index", "answers_starred" in indexes, indexes)
SAID.lines.clear()
h = History(old)   # opened again, as the next start does: the column is there, nothing is added twice
cols = [r[1] for r in sqlite3.connect(str(old)).execute("PRAGMA table_info(answers)")]
check("opened again, the column is not added twice and nothing is said", cols.count("starred") == 1
      and not any("gained" in x for x in SAID.lines), [cols, SAID.lines])
check("the old rows can be starred", h.star(2, True) and ids(h.query(starred=True)) == [2])

print("\n[starring]")
f = Path(tempfile.mkdtemp(prefix="sidenote-star-new-")) / "history.sqlite"
h = History(f)
for i in range(10, 14):
    h.add(i, now - (14 - i) * 60, "essay", answer(i))
check("an answer is starred", h.star(11, True) is True)
check("...and only it comes back when the starred are asked for", ids(h.query(starred=True)) == [11], ids(h.query(starred=True)))
check("each answer says whether it is starred", {r["id"]: r["starred"] for r in h.query()} == {13: False, 12: False, 11: True, 10: False})
check("the starred answers are counted", h.starred_count() == 1, h.starred_count())
check("the star filter goes with the others: a kind and a word", ids(h.query(kind="essay", q="답 11", starred=True)) == [11]
      and ids(h.query(kind="mcq", starred=True)) == [])
check("an id the file does not hold is refused", h.star(999, True) is False and h.starred_count() == 1)
h.add(11, now - 3 * 60, "essay", answer(11, "TYPE: essay\nANSWER: 고친 답\n\n다시 쓴 풀이"))   # the same row written again
check("a row written again keeps its star", ids(h.query(starred=True)) == [11] and h.query(starred=True)[0]["text"].endswith("다시 쓴 풀이"))
check("an answer is unstarred", h.star(11, False) is True and h.query(starred=True) == [] and h.starred_count() == 0)
check("no file, no star", History(None).star(1, True) is False and History(None).starred_count() == 0)

print("\n[pruning past the age limit]")
f = Path(tempfile.mkdtemp(prefix="sidenote-star-age-")) / "history.sqlite"
h = History(f, days=0, max_mb=0)   # no age limit while the rows are written: each add prunes, and they are old already
h.add(20, now - 200 * DAY, "essay", answer(20))   # older than 90 days, starred below
h.add(21, now - 120 * DAY, "essay", answer(21))   # older than 90 days
h.add(22, now - 1 * DAY, "essay", answer(22))     # yesterday's
h.star(20, True)
h.days = 90                                       # and now the 90 days of SIDENOTE_HISTORY_DAYS
gone = h.prune(now)
check("past 90 days the unstarred answer goes and the starred one stays", ids(h.query()) == [22, 20] and gone == 1,
      [ids(h.query()), gone])
h.star(20, False)
h.prune(now)
check("unstarred, the old answer goes at the next pruning", ids(h.query()) == [22], ids(h.query()))

print("\n[pruning for the size cap]")
f = Path(tempfile.mkdtemp(prefix="sidenote-star-size-")) / "history.sqlite"
CAP = 0.3   # MB: about fifteen answers of 20 KB
h = History(f, days=0, max_mb=CAP)
body = "x" * 20000
for i in range(30, 36):   # the six oldest, two of them starred
    h.add(i, now - (100 - i) * 60, "essay", answer(i, body + str(i)))
h.star(30, True)
h.star(32, True)
for i in range(36, 70):   # and many more, past the cap
    h.add(i, now - (100 - i) * 60, "essay", answer(i, body + str(i)))
kept = ids(h.query(limit=200))
check("the starred answers are kept, the oldest of all", 30 in kept and 32 in kept, kept[-6:])
check("the oldest of the rest went first", 31 not in kept and 33 not in kept and 69 in kept and 68 in kept, kept[-6:])
check("what is not starred fits the cap", rest_bytes(f) <= CAP * 1048576, rest_bytes(f))
check("and holds more than half of it: the starred ones take none of its room", rest_bytes(f) > CAP * 1048576 / 2, rest_bytes(f))
SAID.lines.clear()
f = Path(tempfile.mkdtemp(prefix="sidenote-star-over-")) / "history.sqlite"
h = History(f, days=0, max_mb=CAP)   # a cap the starred answers alone go past: ten of 40 KB each (text and words)
for i in range(80, 90):
    h.add(i, now - (200 - i) * 60, "essay", answer(i, body + str(i)))
    h.star(i, True)
small = "y" * 4000   # and the answers after them, many and small, as most are
for i in range(100, 150):
    h.add(i, now - (200 - i) * 60, "essay", answer(i, small + str(i)))
kept = ids(h.query(limit=200))
check("starred answers alone over the cap are all kept", all(i in kept for i in range(80, 90)), kept)
check("...the newest answers keep the whole cap, the oldest of them gone", 149 in kept and 100 not in kept
      and rest_bytes(f) <= CAP * 1048576 and rest_bytes(f) > CAP * 1048576 / 2, [kept[:3], rest_bytes(f)])
warned = [x for x in SAID.lines if "starred answers alone" in x]
check("the log says so once, not at every answer kept", len(warned) == 1, SAID.lines)
for i in range(80, 89):   # unstarred, they count toward the cap again, as the oldest of the rest
    h.star(i, False)
h.add(150, now - 3, "essay", answer(150, small))
kept = ids(h.query(limit=200))
check("unstarred, the old answers count again and go first, until the rest fits",
      not any(i in kept for i in range(80, 88)) and 89 in kept and 150 in kept and rest_bytes(f) <= CAP * 1048576,
      [kept[-4:], rest_bytes(f)])
SAID.lines.clear()
for i in range(160, 170):   # starred past the cap once more
    h.add(i, now - 2, "essay", answer(i, body + str(i)))
    h.star(i, True)
h.add(170, now - 1, "essay", answer(170, small))
check("once they fit again, a later time over the cap is said again", sum("starred answers alone" in x for x in SAID.lines) == 1,
      SAID.lines)

print("\n[the panel's socket]")
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
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


def star_msg(i, on):
    return lambda m: m.get("type") == "star" and m.get("id") == i and m.get("starred") is on


SEQ = int(time.time() * 1000)
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    check("the server's history is the one in its log folder", A.HISTORY._db is not None)
    for k in range(3):   # three answers, kept as the worker keeps them
        A.HISTORY.add(SEQ + k, now - 60 + k, "essay", answer(k))
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws1, \
            client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws2:
        p1, p2 = Panel(ws1), Panel(ws2)
        p1.wait(lambda m: m.get("type") == "usage")
        p2.wait(lambda m: m.get("type") == "usage")
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws1.send_text(json.dumps({"type": "star", "id": SEQ + 1, "starred": True}))
        a, b = p1.wait(star_msg(SEQ + 1, True), after=n1), p2.wait(star_msg(SEQ + 1, True), after=n2)
        check("a star from one panel reaches it and a second panel", a is not None and b is not None, [p1.msgs[n1:], p2.msgs[n2:]])
        check("...with how many are starred now", b is not None and b.get("n") == 1, b)
        check("...and the history keeps it", ids(A.HISTORY.query(starred=True)) == [SEQ + 1])
        only = client.get("/history", params={"starred": 1}).json()["answers"]
        check("/history?starred=1 gives the starred answers only", ids(only) == [SEQ + 1] and only[0]["starred"] is True, ids(only))
        every = client.get("/history").json()["answers"]
        check("/history gives every answer, each saying whether it is starred",
              {r["id"]: r["starred"] for r in every if r["id"] >= SEQ} == {SEQ: False, SEQ + 1: True, SEQ + 2: False})
        days = client.get("/history/days").json()
        check("/history/days says how many are starred", days.get("starred") == 1 and days.get("days"), days)
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws2.send_text(json.dumps({"type": "star", "id": SEQ + 1, "starred": False}))   # taken off from the other panel
        a, b = p1.wait(star_msg(SEQ + 1, False), after=n1), p2.wait(star_msg(SEQ + 1, False), after=n2)
        check("unstarred from the second panel, both panels hear it", a is not None and b is not None and a.get("n") == 0,
              [p1.msgs[n1:], p2.msgs[n2:]])
        check("...and the history no longer holds it starred", A.HISTORY.query(starred=True) == [])
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws1.send_text(json.dumps({"type": "star", "id": 424242, "starred": True}))   # an id the history does not hold
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("an id the history does not hold is refused, and that panel is told why",
              said is not None and said.get("level") == "warn" and said.get("text") == t("Not starred: this answer is not in the saved history"),
              said)
        time.sleep(0.3)   # time for a broadcast to have come, were there one
        check("...and no panel hears of a star", not any(m.get("type") == "star" for m in p1.msgs[n1:] + p2.msgs[n2:]),
              [p1.msgs[n1:], p2.msgs[n2:]])
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "star", "id": 424242, "starred": False}))
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("...and an unstar of one is said as an unstar",
              said is not None and said.get("text") == t("Not unstarred: this answer is not in the saved history"), said)
        SETTINGS.set("history_keep", False)
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "star", "id": 424243, "starred": True}))
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("with Keep answers off, the refusal says that is why",
              said is not None and said.get("text") == t("Not starred: Keep answers is off, so this answer was not saved"), said)
        SETTINGS.set("history_keep", True)
        n1, n2 = len(p1.msgs), len(p2.msgs)
        for bad in ({"type": "star", "id": str(SEQ), "starred": True}, {"type": "star", "id": SEQ, "starred": "yes"},
                    {"type": "star", "id": True, "starred": True}, {"type": "star", "starred": True}):
            ws1.send_text(json.dumps(bad))
        ws1.send_text(json.dumps({"type": "star", "id": SEQ, "starred": True}))   # and one good message after them
        got = p1.wait(star_msg(SEQ, True), after=n1)
        check("a malformed star message changes nothing and the socket goes on",
              got is not None and [m for m in p1.msgs[n1:] if m.get("type") in ("star", "notice")] == [got], p1.msgs[n1:])
        check("...and the good one after it is kept", ids(A.HISTORY.query(starred=True)) == [SEQ])
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "history_clear"}))   # Clear history: the starred answers go too
        p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("Clear history clears the starred answers too", A.HISTORY.query(starred=True) == [] and A.HISTORY.query() == []
              and client.get("/history/days").json().get("starred") == 0)

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
