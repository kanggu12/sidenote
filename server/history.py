"""The answers, kept: a reload of the panel, a restart of the server and the next day all find them again.

One SQLite file in the log folder, one row an answer with its follow-ups, its code check and the small picture of its
screen. It cannot grow for ever: rows older than SIDENOTE_HISTORY_DAYS go, and past SIDENOTE_HISTORY_MB the oldest go
first. The panel's setting history_keep stops the keeping, and its Clear the history empties the file.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("sidenote.history")
MAX_ROWS = 200   # what one request returns at most


class History:
    def __init__(self, path, days: float = 90.0, max_mb: float = 200.0):
        self.days, self.max_bytes = days, int(max_mb * 1024 * 1024)
        self._lock = threading.Lock()
        self._db = None
        if not path:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA secure_delete=ON")           # what Clear removes does not stay readable in free pages
            self._db.execute(f"PRAGMA journal_size_limit={8 * 1024 * 1024}")   # and the WAL does not stay large
            self._db.execute("CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL,"
                             " kind TEXT NOT NULL, words TEXT NOT NULL, data TEXT NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_ts ON answers (ts)")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_day ON answers (day, ts)")     # the contents' two filters
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_kind ON answers (kind, ts)")
            self._db.commit()
        except (sqlite3.Error, OSError) as exc:   # an answer is never lost to this: the panel only has less to look back on
            log.warning("no history (%s)", exc)
            self._db = None

    @staticmethod
    def _words(data: dict) -> str:
        """What a search looks in: the answer, what was heard, the follow-ups, lower-cased."""
        parts = [data.get("text") or "", data.get("transcript") or ""]
        for turn in data.get("turns") or ():
            parts += [turn.get("q") or "", turn.get("text") or ""]
        return "\n".join(parts).lower()

    def add(self, seq: int, ts: float, kind: str, data: dict) -> None:
        if self._db is None:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        data = {**data, "id": seq, "ts": ts, "kind": kind}
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO answers (id, ts, day, kind, words, data) VALUES (?, ?, ?, ?, ?, ?)",
                             (seq, ts, day, kind, self._words(data), json.dumps(data, ensure_ascii=False)))
            self._db.commit()
        self.prune()

    def update(self, seq: int, **fields) -> None:
        """Something that came after the answer: its code check (`check`), its review (`verify`), one more follow-up (`turn`), a follow-up's check (`turn_check`)."""
        if self._db is None:
            return
        with self._lock:
            row = self._db.execute("SELECT data FROM answers WHERE id = ?", (seq,)).fetchone()
            if row is None:
                return
            data = json.loads(row[0])
            turn = fields.pop("turn", None)
            turn_check = fields.pop("turn_check", None)   # (the follow-up's id, its code check)
            data.update(fields)
            if turn is not None:
                data["turns"] = [*data.get("turns", []), turn]
            if turn_check is not None:
                for t in data.get("turns", []):
                    if t.get("id") == turn_check[0]:
                        t["check"] = turn_check[1]
            self._db.execute("UPDATE answers SET words = ?, data = ? WHERE id = ?",
                             (self._words(data), json.dumps(data, ensure_ascii=False), seq))
            self._db.commit()

    def days_list(self) -> list:
        """[{"day", "n", "first", "last"}], the newest first; first and last are the times of that day's first and last answers."""
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute("SELECT day, COUNT(*), MIN(ts), MAX(ts) FROM answers GROUP BY day ORDER BY day DESC").fetchall()
        return [{"day": d, "n": n, "first": a, "last": b} for d, n, a, b in rows]

    def query(self, day: str = "", q: str = "", kind: str = "", limit: int = 60) -> list:
        """The answers asked for, the newest first: of one day, of one kind, holding every word of `q`."""
        if self._db is None:
            return []
        where, args = [], []
        if day:
            where.append("day = ?"); args.append(day)
        if kind:
            where.append("kind = ?"); args.append(kind)
        for word in q.lower().split():
            # the word as written, % and _ included
            where.append("words LIKE ? ESCAPE '\\'")
            args.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        sql = "SELECT data FROM answers" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, max(1, min(limit, MAX_ROWS)))).fetchall()
        return [json.loads(r[0]) for r in rows]

    def prune(self, now: float | None = None) -> int:
        """Rows past the age, then the oldest until the total fits. Returns how many went."""
        if self._db is None:
            return 0
        now = time.time() if now is None else now
        gone = 0
        with self._lock:
            if self.days > 0:
                gone += self._db.execute("DELETE FROM answers WHERE ts < ?", (now - self.days * 86400,)).rowcount
            # What the rows take on disk, in bytes. LENGTH counted characters, and Korean text is three bytes each: a
            # 5 MB cap held 16 MB. Pages in use, read after each batch instead of summing every row.
            used = lambda: (self._db.execute("PRAGMA page_count").fetchone()[0]  # noqa: E731
                            - self._db.execute("PRAGMA freelist_count").fetchone()[0]) * self._db.execute("PRAGMA page_size").fetchone()[0]
            while self.max_bytes > 0 and used() > self.max_bytes:
                n = self._db.execute("DELETE FROM answers WHERE id IN (SELECT id FROM answers ORDER BY ts LIMIT 8)").rowcount
                if not n:
                    break
                gone += n
            self._db.commit()
        return gone

    def clear(self) -> None:
        if self._db is None:
            return
        with self._lock:
            self._db.execute("DELETE FROM answers")
            self._db.commit()
            self._db.execute("VACUUM")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # the deleted rows stood on in the WAL until then
