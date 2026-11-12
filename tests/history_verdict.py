"""Answers marked right or wrong in the server's history (server/history.py): a history.sqlite from 0.1.0 and one from before
the verdicts gaining the column with their rows kept, a verdict given, changed and taken off, kept by a row written again and
through a delete and a put back, refused for an answer the file does not hold; over the panel's socket, a mark from one panel
heard by a second, refused ids and malformed messages, the event each mark writes and what ./sidenote report makes of them.

    .venv/bin/python tests/history_verdict.py
"""
import io
import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path

# The server's environment, set before it is imported: stand-in engines, no speech, no runner, a log folder of its own
LOGS = tempfile.mkdtemp(prefix="sidenote-verdict-")
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_LOG_DIR=LOGS,
                  SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_AGENT="mock")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server.history import History  # noqa: E402

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}   # the panel's own page, which /panel takes
NO_JUDGE = "no verdicts here"   # what judge() below gives for a history that cannot mark an answer: the checks fail, the suite goes on

# The table server/history.py made in 0.1.0 (no star, nothing deleted), and the one it made from 0.6.0 until the verdicts
SCHEMA_010 = "CREATE TABLE answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, words TEXT NOT NULL, data TEXT NOT NULL)"
SCHEMA_090 = ("CREATE TABLE answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, words TEXT NOT NULL,"
              " data TEXT NOT NULL, starred INTEGER NOT NULL DEFAULT 0, deleted REAL)")


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:400]}" if detail and not ok else ""))


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


def answer(i: int, kind: str = "coding", engine: str = "local", trigger: str = "screen") -> dict:
    """What the server keeps of one answer (keep_answer in server/app.py), less its time."""
    return {"trigger": trigger, "transcript": "", "text": f"TYPE: {kind}\nANSWER: 답 {i}\n\n풀이 {i}", "model": f"{engine}-model",
            "engine": engine, "sent": [], "stages": {}, "usage": {}, "cost_usd": None, "elapsed": 1.0, "first_token": None,
            "region": None, "region_shown": False, "thumb": None}


def verdict_of(row) -> object:
    """An answer's verdict as the history gives it: "right", "wrong" or None, and something else when it says none at all."""
    return row.get("verdict", "not said") if isinstance(row, dict) else "no answer"


def marks(h: History) -> dict:
    """Each answer's verdict, by its id, as /history gives them."""
    return {r["id"]: verdict_of(r) for r in h.query(limit=200)}


def judge(h: History, seq, verdict):
    """History.judge: what the mark's event says of the answer, or None when refused."""
    return h.judge(seq, verdict) if hasattr(h, "judge") else NO_JUDGE


def old_file(schema: str, rows: int) -> Path:
    """A history.sqlite as an older server left it: its table, and `rows` answers written as that server wrote them."""
    path = Path(tempfile.mkdtemp(prefix="sidenote-verdict-old-")) / "history.sqlite"
    db = sqlite3.connect(str(path))
    db.execute(schema)
    now = time.time()
    for i in range(1, rows + 1):
        data = {**answer(i), "id": i, "ts": now - i * 60, "kind": "coding"}
        db.execute("INSERT INTO answers (id, ts, day, kind, words, data) VALUES (?, ?, ?, ?, ?, ?)",
                   (i, now - i * 60, time.strftime("%Y-%m-%d", time.localtime(now - i * 60)), "coding", data["text"].lower(),
                    json.dumps(data, ensure_ascii=False)))
    db.commit()
    db.close()
    return path


def columns(path: Path) -> list:
    return [r[1] for r in sqlite3.connect(str(path)).execute("PRAGMA table_info(answers)")]


print("\n[a history file from before the verdicts]")
for name, schema in (("0.1.0", SCHEMA_010), ("0.9.0", SCHEMA_090)):
    path = old_file(schema, 3)
    SAID.lines.clear()
    h = History(path)
    cols = columns(path)
    check(f"a file from {name} gains the verdict column when it opens", cols.count("verdict") == 1, cols)
    check(f"...its rows kept, none of them judged", marks(h) == {1: None, 2: None, 3: None}
          and h.query()[2]["text"].endswith("풀이 3"), marks(h))
    check(f"...and the log says it once", sum("right or wrong" in x for x in SAID.lines) == 1, SAID.lines)
    SAID.lines.clear()
    h = History(path)   # opened again, as the next start does: the column is there, nothing is added twice
    check(f"opened again ({name}), the column is not added twice and nothing is said",
          columns(path).count("verdict") == 1 and not any("right or wrong" in x for x in SAID.lines), [columns(path), SAID.lines])
    check(f"the old rows can be judged ({name})", judge(h, 2, "wrong") is not None and marks(h) == {1: None, 2: "wrong", 3: None},
          marks(h))
fresh = Path(tempfile.mkdtemp(prefix="sidenote-verdict-new-")) / "history.sqlite"
SAID.lines.clear()
History(fresh)
check("a new file has the column from the start, and says nothing of it", "verdict" in columns(fresh)
      and not any("right or wrong" in x for x in SAID.lines), [columns(fresh), SAID.lines])

print("\n[marking]")
f = Path(tempfile.mkdtemp(prefix="sidenote-verdict-mark-")) / "history.sqlite"
h = History(f)
now = time.time()
h.add(10, now - 300, "coding", answer(10))
h.add(11, now - 200, "mcq", answer(11, "mcq", "agent", "voice"))
h.add(12, now - 100, "essay", answer(12, "essay"))
facts = judge(h, 11, "right")
check("an answer is marked right, and the mark gives what its event says of it: engine, model, type, how it came",
      facts == {"engine": "agent", "model": "agent-model", "type": "mcq", "trigger": "voice"}, facts)
check("...each answer says its verdict, the others none", marks(h) == {12: None, 11: "right", 10: None}, marks(h))
check("...and so does the answer read by its id", verdict_of(h.get(11)) == "right" and verdict_of(h.get(10)) is None)
check("marked wrong, it changes", judge(h, 11, "wrong") is not None and verdict_of(h.get(11)) == "wrong")
check("taken off (None), it has none", judge(h, 11, None) is not None and verdict_of(h.get(11)) is None)
check("a verdict that is not right or wrong is refused, and changes nothing", judge(h, 10, "right") is not None
      and judge(h, 10, "maybe") is None and judge(h, 10, "") is None and verdict_of(h.get(10)) == "right")
check("an id the file does not hold is refused", judge(h, 999, "right") is None)
check("...and an id past what SQLite holds is refused, not an error", judge(h, 2**70, "right") is None)
h.add(10, now - 300, "coding", {**answer(10), "text": "TYPE: coding\nANSWER: 고친 답\n\n다시 쓴 풀이"})   # the same row written again
check("a row written again keeps its verdict", verdict_of(h.get(10)) == "right" and h.get(10)["text"].endswith("다시 쓴 풀이"))
check("no file, no verdict", judge(History(None), 1, "right") is None)

print("\n[a deleted answer, and put back]")
judge(h, 12, "wrong")
h.delete(12)   # to Recently deleted, marked wrong
check("a deleted answer's verdict is not changed", judge(h, 12, "right") is None and judge(h, 12, None) is None)
held = {r["id"]: verdict_of(r) for r in h.deleted_list()}
check("Recently deleted gives it with its verdict", held == {12: "wrong"} and verdict_of(h.deleted_get(12)) == "wrong", held)
back = h.restore(12)
check("put back, it has the verdict it had", verdict_of(back) == "wrong" and marks(h)[12] == "wrong", back)

print("\n[a file from elsewhere]")
db = sqlite3.connect(str(f))
try:   # what ./sidenote restore could bring: anything in the column
    db.execute("UPDATE answers SET verdict = ? WHERE id = 10", ('"><img src=x onerror=alert(1)>',))
    db.execute("UPDATE answers SET verdict = 1 WHERE id = 11")
    db.commit()
    junk = True
except sqlite3.Error:   # a file with no such column: the check below fails
    junk = False
db.close()
check("a verdict column holding anything but right or wrong is given out as none", junk and marks(h)[10] is None
      and marks(h)[11] is None and verdict_of(h.get(10)) is None, marks(h))
h.clear()
check("Clear history takes the verdicts with the answers", h.query() == [] and judge(h, 10, "right") is None)

print("\n[the panel's socket]")
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server import report  # noqa: E402
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


def told(i, v):
    return lambda m: m.get("type") == "verdict" and m.get("id") == i and "verdict" in m and m["verdict"] == v


def events() -> list:
    """The verdict events written to the server's events.jsonl, oldest first."""
    path = Path(LOGS) / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [e for e in map(json.loads, lines) if e.get("event") == "verdict"]


SEQ = int(time.time() * 1000)
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    A.HISTORY.add(SEQ, now - 60, "coding", answer(0))
    A.HISTORY.add(SEQ + 1, now - 50, "mcq", answer(1, "mcq", "agent"))
    A.HISTORY.add(SEQ + 2, now - 40, "essay", answer(2, "essay", "local", "voice"))
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws1, \
            client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws2:
        p1, p2 = Panel(ws1), Panel(ws2)
        p1.wait(lambda m: m.get("type") == "usage")
        p2.wait(lambda m: m.get("type") == "usage")
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": SEQ, "verdict": "right"}))
        a, b = p1.wait(told(SEQ, "right"), after=n1), p2.wait(told(SEQ, "right"), after=n2)
        check("a verdict from one panel reaches it and a second panel", a is not None and b is not None, [p1.msgs[n1:], p2.msgs[n2:]])
        check("...and the history keeps it", verdict_of(A.HISTORY.get(SEQ)) == "right")
        rows = {r["id"]: verdict_of(r) for r in client.get("/history").json()["answers"] if r["id"] >= SEQ}
        check("/history gives each answer's verdict", rows == {SEQ: "right", SEQ + 1: None, SEQ + 2: None}, rows)
        ev = events()
        check("the mark writes its event: the answer's id, the verdict, its engine, model, type and how it came",
              len(ev) == 1 and {k: ev[0].get(k) for k in ("id", "verdict", "engine", "model", "type", "trigger")}
              == {"id": SEQ, "verdict": "right", "engine": "local", "model": "local-model", "type": "coding", "trigger": "screen"}, ev)
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws2.send_text(json.dumps({"type": "verdict", "id": SEQ, "verdict": "wrong"}))   # changed from the other panel
        a, b = p1.wait(told(SEQ, "wrong"), after=n1), p2.wait(told(SEQ, "wrong"), after=n2)
        check("changed from the second panel, both panels hear it", a is not None and b is not None
              and verdict_of(A.HISTORY.get(SEQ)) == "wrong", [p1.msgs[n1:], p2.msgs[n2:]])
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": SEQ, "verdict": None}))   # taken off
        a, b = p1.wait(told(SEQ, None), after=n1), p2.wait(told(SEQ, None), after=n2)
        check("taken off (null), both panels hear it, and the history holds none", a is not None and b is not None
              and verdict_of(A.HISTORY.get(SEQ)) is None, [p1.msgs[n1:], p2.msgs[n2:]])
        check("...and its event says none", [e.get("verdict") for e in events()] == ["right", "wrong", "none"], events())
        for i, v in ((SEQ + 1, "right"), (SEQ + 2, "wrong"), (SEQ + 1, "wrong"), (SEQ + 1, "right")):
            n1 = len(p1.msgs)
            ws1.send_text(json.dumps({"type": "verdict", "id": i, "verdict": v}))
            p1.wait(told(i, v), after=n1)
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": 424242, "verdict": "right"}))   # an id the history does not hold
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        time.sleep(0.3)   # time for a broadcast to have come, were there one
        check("an id the history does not hold is refused, that panel is told why, and no panel hears of a verdict",
              said is not None and said.get("level") == "warn" and said.get("text") == t("Not marked: this answer is not in the saved history")
              and not any(m.get("type") == "verdict" for m in p1.msgs[n1:] + p2.msgs[n2:]), [said, p1.msgs[n1:], p2.msgs[n2:]])
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": 424242, "verdict": None}))
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("...a mark taken off one is said as that",
              said is not None and said.get("text") == t("Mark not taken off: this answer is not in the saved history"), said)
        SETTINGS.set("history_keep", False)
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": 424243, "verdict": "wrong"}))
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("...and with Keep answers off, the refusal says that is why",
              said is not None and said.get("text") == t("Not marked: Keep answers is off, so this answer was not saved"), said)
        SETTINGS.set("history_keep", True)
        n1 = len(p1.msgs)
        for bad in ({"type": "verdict", "id": str(SEQ), "verdict": "right"}, {"type": "verdict", "id": True, "verdict": "right"},
                    {"type": "verdict", "id": SEQ, "verdict": "yes"}, {"type": "verdict", "id": SEQ, "verdict": 1},
                    {"type": "verdict", "id": SEQ}, {"type": "verdict", "verdict": "right"}):
            ws1.send_text(json.dumps(bad))
        ws1.send_text(json.dumps({"type": "verdict", "id": SEQ, "verdict": "right"}))   # and one good message after them
        got = p1.wait(told(SEQ, "right"), after=n1)
        check("a malformed verdict message changes nothing (one without a verdict does not take it off) and the socket goes on",
              got is not None and [m for m in p1.msgs[n1:] if m.get("type") in ("verdict", "notice")] == [got], p1.msgs[n1:])
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "answer_delete", "id": SEQ + 2}))
        p1.wait(lambda m: m.get("type") == "answer_deleted" and m.get("id") == SEQ + 2, after=n1)
        n1 = len(p1.msgs)
        ws1.send_text(json.dumps({"type": "verdict", "id": SEQ + 2, "verdict": "right"}))
        said = p1.wait(lambda m: m.get("type") == "notice", after=n1)
        check("a deleted answer's verdict is refused, and it keeps its own", said is not None
              and verdict_of(A.HISTORY.deleted_get(SEQ + 2)) == "wrong", [said, A.HISTORY.deleted_get(SEQ + 2)])
        n1, n2 = len(p1.msgs), len(p2.msgs)
        ws2.send_text(json.dumps({"type": "answer_restore", "id": SEQ + 2}))
        back = p1.wait(lambda m: m.get("type") == "answer_restored" and m.get("id") == SEQ + 2, after=n1)
        check("put back, every panel is given it with its verdict", back is not None and verdict_of(back.get("answer")) == "wrong", back)
    # What ./sidenote report makes of these events: each answer once, by its last mark, the one taken off and put back on counted
    report.LOG_DIR = Path(LOGS)
    out = io.StringIO()
    with redirect_stdout(out):
        report.main(["report", "--days", "1", "--json"])
    v = (json.loads(out.getvalue()).get("period") or {}).get("verdicts") or {}
    check("./sidenote report counts each answer once, by its last mark: two right (local, agent), one wrong (speech)",
          {k: v.get(k) for k in ("judged", "right")} == {"judged": 3, "right": 2}
          and v.get("by_engine") == {"agent": {"judged": 1, "right": 1}, "local": {"judged": 2, "right": 1}}
          and v.get("by_trigger") == {"screen": {"judged": 2, "right": 2}, "voice": {"judged": 1, "right": 0}}, v)

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
