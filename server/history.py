"""The answers, kept: a reload of the panel, a restart of the server and the next day all find them again.

One SQLite file in the log folder, one row an answer with its follow-ups, its code check and the small picture of its
screen. It cannot grow for ever: rows older than SIDENOTE_HISTORY_DAYS go, and past SIDENOTE_HISTORY_MB the oldest go
first. A starred answer (the star key on its head) is not one of them: it stays until it is unstarred, and the size
cap counts the rest. The panel's setting history_keep stops the keeping, and its Clear the history empties the file,
starred answers included.

One answer can be deleted by itself (the delete key on its head). It is not gone at once: its row is marked with the
time it was deleted and leaves every listing, and Recently deleted in the panel's contents holds it for
SIDENOTE_DELETED_DAYS, where it can be put back as it was, star, verdict and follow-ups included, or deleted for good.
Past those days it goes by itself, and when the file is over its size what was deleted goes before any answer still
shown. Clear the history takes these too, at once.

An answer can be marked right or wrong (the Right and Wrong keys on its head): its row holds the verdict, "right" or
"wrong", or nothing while it is not judged. It changes nothing of how long the answer is kept; ./sidenote report
counts the verdicts from the event each one writes.

What was heard, with Keep what is heard on, is a table of its own in the same file: one row a closed sentence, with its
time, its length and its language. It goes with the answers by age, and has a size limit of its own
(SIDENOTE_HEARD_MB) that the answers' cap does not count, so a long transcript never pushes an answer out.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("sidenote.history")
MAX_ROWS = 200   # what one request returns at most
MAX_HEARD = 20000   # the lines of one day one request returns at most: its newest
VERDICTS = ("right", "wrong")   # what an answer can be marked; no mark is NULL in the file and None here


def _verdict(value) -> str | None:
    """A row's verdict as it is given out: "right", "wrong" or None. A file from elsewhere (./sidenote restore) could hold any
    text in the column, which the panel would put in its keys' state."""
    return value if value in VERDICTS else None


def _text(value) -> str | None:
    """A field of what was kept of an answer, for the verdict's event: text as it is, anything else (a file from elsewhere) none."""
    return value if isinstance(value, str) else None


def _read(default):
    """A read of the file that fails (locked past its wait, a disk error, a damaged page) gives what an empty store gives,
    and says so in the log at most once a minute: the panel opens with less to look back on and an API read answers,
    where the error ended both (a panel that never opened, a 500 in plain text). `default`: the value, or a type to
    call for a fresh one (list)."""
    def wrap(fn):
        @functools.wraps(fn)
        def read(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except sqlite3.Error as exc:
                try:
                    # a write the read began (Recently deleted's expiry) is not left open; under the lock, as every write
                    # is made and committed under it: outside it, it took back another thread's write half way
                    with self._lock:
                        self._db.rollback()
                except sqlite3.Error:
                    pass
                now = time.monotonic()
                if now - self._read_said > 60:   # a file that stays locked would say it on every look
                    self._read_said = now
                    log.warning("history: a read failed (%s): shown as empty for now", exc)
                return default() if isinstance(default, type) else default
        return read
    return wrap
# What a row of the heard table is counted at: its time, length, day and language, its rowid and its entry in the index,
# about 70 bytes, and its words twice. Rows fill a page in the order they come, and a page takes what fits: sentences of
# 3 KB left a fifth of each page unused (measured), and of a little over 2 KB they would leave half. Counted high on purpose,
# since the answers' cap takes this off the file's pages (prune): counted low, a long transcript would push answers out by
# the difference, and counted high they only get a little more room.
HEARD_ROW = 96
HEARD_WORDS = 2


def _private(path) -> None:
    """The file and SQLite's two beside it readable by this user alone: they hold the answers and, with Keep what is heard on,
    what other people said. Only a file this user owns: another's mode is not this server's to change. SQLite gives the -wal
    and -shm it makes later the mode of the database, so this done at the open holds. No uid (Windows): the folder's ACL decides."""
    if not hasattr(os, "getuid"):
        return
    for name in (str(path), f"{path}-wal", f"{path}-shm"):
        try:
            if os.stat(name).st_uid == os.getuid():
                os.chmod(name, 0o600)
        except OSError:   # not there (yet), or a file system with no modes: the history goes on all the same
            pass


class History:
    def __init__(self, path, days: float = 90.0, max_mb: float = 200.0, heard_mb: float = 20.0, deleted_days: float = 7.0):
        self.days, self.max_bytes = days, int(max_mb * 1024 * 1024)
        self.deleted_days = deleted_days   # how long a deleted answer can still be put back; 0 for until it is emptied by hand
        self.heard_max = int(heard_mb * 1024 * 1024)
        self._heard_bytes: int | None = None   # what the heard table takes (heard_bytes), None until it has been summed
        self._lock = threading.Lock()
        self._db = None
        self._over = False   # the starred answers alone are over the size cap, and the log has said so
        self._read_said = 0.0   # when the log last said a read failed (_read)
        if not path:
            return
        try:
            Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)   # a folder made here is this user's alone
            self._db = sqlite3.connect(str(path), check_same_thread=False)
            _private(path)                                        # before anything is written, and so before any -wal is made
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA secure_delete=ON")           # what Clear removes does not stay readable in free pages
            self._db.execute(f"PRAGMA journal_size_limit={8 * 1024 * 1024}")   # and the WAL does not stay large
            self._db.execute("CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL,"
                             " kind TEXT NOT NULL, words TEXT NOT NULL, data TEXT NOT NULL,"
                             " starred INTEGER NOT NULL DEFAULT 0, deleted REAL, verdict TEXT)")
            # A file from 0.1.0 has no star: it gains the column once, here, and its rows stay as they were, unstarred
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(answers)")}
            if "starred" not in columns:
                self._db.execute("ALTER TABLE answers ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
                log.info("history: the answers gained their star (a file from before stars)")
            # And a file from before 0.6.0 has no Recently deleted: the column comes the same way, empty, so no answer of
            # it is deleted. It holds when the answer was deleted (a time), and nothing for an answer that was not
            if "deleted" not in columns:
                self._db.execute("ALTER TABLE answers ADD COLUMN deleted REAL")
                log.info("history: the answers can be deleted one by one (a file from before Recently deleted)")
            # And a file from before Right and Wrong has no verdict: the column comes the same way, empty, so none of its
            # answers is judged. It holds "right" or "wrong", and nothing for an answer not judged
            if "verdict" not in columns:
                self._db.execute("ALTER TABLE answers ADD COLUMN verdict TEXT")
                log.info("history: the answers can be marked right or wrong (a file from before verdicts)")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_ts ON answers (ts)")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_day ON answers (day, ts)")     # the contents' two filters
            # ...and the same for the answers shown, which every read of the days asks for (deleted IS NULL): with the
            # index above alone the days read each row as well, 0.7 ms then 9 ms on a 99 MB file, and every open panel
            # reads them again after each delete and put back (measured; 0.9 ms with this one)
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_day_shown ON answers (day, ts) WHERE deleted IS NULL")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_kind ON answers (kind, ts)")
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_starred ON answers (starred, ts)")   # and the Starred choice
            # Recently deleted, the latest first: an index of the deleted rows alone, which are few
            self._db.execute("CREATE INDEX IF NOT EXISTS answers_deleted ON answers (deleted) WHERE deleted IS NOT NULL")
            self._db.execute("CREATE TABLE IF NOT EXISTS heard (id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL,"
                             " secs REAL NOT NULL, lang TEXT NOT NULL, words TEXT NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS heard_day ON heard (day, ts)")   # one day's lines, and the days
            self._db.commit()
            _private(path)                                        # a -wal and -shm left by an older server's mode, now they are open
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
            # A row written again keeps its star and its verdict: REPLACE deletes the old row first, and would take them with
            # it. And it stays deleted if it was: written again it would otherwise come back into the listings by itself
            self._db.execute("INSERT OR REPLACE INTO answers (id, ts, day, kind, words, data, starred, deleted, verdict) VALUES (?, ?, ?, ?,"
                             " ?, ?, COALESCE((SELECT starred FROM answers WHERE id = ?), 0), (SELECT deleted FROM answers WHERE id = ?),"
                             " (SELECT verdict FROM answers WHERE id = ?))",
                             (seq, ts, day, kind, self._words(data), json.dumps(data, ensure_ascii=False), seq, seq, seq))
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

    @_read(False)
    def holds(self, seq: int) -> bool:
        """Whether the file has a row of this id, shown or in Recently deleted."""
        if self._db is None or not -2**63 <= seq < 2**63:
            return False
        with self._lock:
            return self._db.execute("SELECT 1 FROM answers WHERE id = ?", (seq,)).fetchone() is not None

    @_read(None)
    def get(self, seq: int) -> dict | None:
        """One answer as query() gives each, by its id; None when the file holds no answer of that id that is not deleted,
        or there is no file."""
        if self._db is None or not -2**63 <= seq < 2**63:   # an id SQLite cannot hold is none it keeps (it raised, a 500)
            return None
        with self._lock:
            row = self._db.execute("SELECT data, starred, id, verdict FROM answers WHERE id = ? AND deleted IS NULL", (seq,)).fetchone()
        return {**json.loads(row[0]), "starred": bool(row[1]), "verdict": _verdict(row[3]), "id": row[2]} if row else None

    def star(self, seq: int, on: bool) -> bool:
        """Star or unstar one answer. False when the file holds no answer of that id that is not deleted, or there is no file."""
        if self._db is None:
            return False
        with self._lock:
            # not a deleted one: no listing shows it, so no key reaches it, and put back it has the star it had
            done = self._db.execute("UPDATE answers SET starred = ? WHERE id = ? AND deleted IS NULL", (1 if on else 0, seq)).rowcount
            self._db.commit()
        return done == 1

    def judge(self, seq: int, verdict: str | None) -> dict | None:
        """Mark one answer right or wrong ("right", "wrong"), or take its mark off (None). Gives what the verdict's event says
        of the answer: its engine, model, type and how it came (trigger). None when the file holds no answer of that id that
        is not deleted, or there is no file."""
        if self._db is None or not -2**63 <= seq < 2**63 or verdict not in (None, *VERDICTS):
            return None
        with self._lock:
            # not a deleted one, as for the star: no listing shows it, and put back it has the verdict it had
            done = self._db.execute("UPDATE answers SET verdict = ? WHERE id = ? AND deleted IS NULL", (verdict, seq)).rowcount
            self._db.commit()
            row = self._db.execute("SELECT data, kind FROM answers WHERE id = ?", (seq,)).fetchone() if done == 1 else None
        if row is None:
            return None
        try:   # what was kept of it: a row that cannot be read still takes its verdict, and its event says less
            data = json.loads(row[0])
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        return {"engine": _text(data.get("engine")), "model": _text(data.get("model")), "type": _text(row[1]),
                "trigger": _text(data.get("trigger"))}

    @_read(0)
    def starred_count(self) -> int:
        """How many answers are starred, for the contents' Starred choice."""
        if self._db is None:
            return 0
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM answers WHERE starred = 1 AND deleted IS NULL").fetchone()[0]

    @_read(list)
    def days_list(self) -> list:
        """[{"day", "n", "first", "last"}], the newest first; first and last are the times of that day's first and last answers."""
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute("SELECT day, COUNT(*), MIN(ts), MAX(ts) FROM answers WHERE deleted IS NULL"
                                    " GROUP BY day ORDER BY day DESC").fetchall()
        return [{"day": d, "n": n, "first": a, "last": b} for d, n, a, b in rows]

    # ---------- one answer deleted, and put back (Recently deleted) ----------

    def _until(self, at: float) -> float | None:
        """When an answer deleted at `at` goes by itself; None when it stays until it is emptied by hand."""
        return at + self.deleted_days * 86400 if self.deleted_days > 0 else None

    def _expire(self, now: float) -> int:
        """What has had its days in Recently deleted goes, starred or not: its star does not hold a deleted answer, since
        deleting it was asked for after the star was given. Called with the lock held, by everything that reads Recently
        deleted: the next answer kept (prune) can be days away, and until then an answer past its days stood in the list
        with no days left and could still be put back. Returns how many went."""
        if self.deleted_days <= 0:   # kept until emptied by hand
            return 0
        gone = self._db.execute("DELETE FROM answers WHERE deleted IS NOT NULL AND deleted < ?",
                                (now - self.deleted_days * 86400,)).rowcount
        # Committed whether or not anything went: the DELETE began a transaction, and left open after a read that deleted
        # nothing, it held the file's write lock until the next write (a second connection was told the database is locked)
        self._db.commit()
        return gone

    def delete(self, seq: int, now: float | None = None) -> dict | None:
        """Move one answer to Recently deleted: {"deleted": when, "until": when it goes by itself, or None}. None when the
        file holds no answer of that id that is not deleted already, or there is no file."""
        if self._db is None or not -2**63 <= seq < 2**63:
            return None
        now = time.time() if now is None else now
        with self._lock:
            done = self._db.execute("UPDATE answers SET deleted = ? WHERE id = ? AND deleted IS NULL", (now, seq)).rowcount
            self._db.commit()
        return {"deleted": now, "until": self._until(now)} if done == 1 else None

    def restore(self, seq: int, now: float | None = None) -> dict | None:
        """Put one deleted answer back as it was, its star, verdict and follow-ups with it: the answer, as query() gives each.
        None when the file holds no deleted answer of that id (one past its days is gone), or there is no file."""
        if self._db is None or not -2**63 <= seq < 2**63:
            return None
        with self._lock:
            self._expire(time.time() if now is None else now)
            done = self._db.execute("UPDATE answers SET deleted = NULL WHERE id = ? AND deleted IS NOT NULL", (seq,)).rowcount
            self._db.commit()
            row = self._db.execute("SELECT data, starred, id, verdict FROM answers WHERE id = ?", (seq,)).fetchone() if done == 1 else None
        return {**json.loads(row[0]), "starred": bool(row[1]), "verdict": _verdict(row[3]), "id": row[2]} if row else None

    def purge(self, seq: int | None = None) -> list:
        """Delete for good: the one deleted answer of that id, or with no id all of Recently deleted. Returns the ids
        that went, for whoever still holds something of them. Never an answer that is not deleted: that one goes to
        Recently deleted first."""
        if self._db is None or (seq is not None and not -2**63 <= seq < 2**63):
            return []
        with self._lock:
            # read and deleted under the one lock, so the ids given back are the rows that went (RETURNING would say it
            # in one statement, and an older SQLite does not know it)
            if seq is None:
                gone = [row[0] for row in self._db.execute("SELECT id FROM answers WHERE deleted IS NOT NULL")]
                self._db.execute("DELETE FROM answers WHERE deleted IS NOT NULL")
            else:
                gone = [row[0] for row in self._db.execute("SELECT id FROM answers WHERE id = ? AND deleted IS NOT NULL", (seq,))]
                self._db.execute("DELETE FROM answers WHERE id = ? AND deleted IS NOT NULL", (seq,))
            self._db.commit()
            if gone:
                # asked for by hand, so it is gone now: the rows stood on in the WAL until then (as in clear)
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return gone

    @_read(0)
    def deleted_count(self, now: float | None = None) -> int:
        """How many answers Recently deleted holds, for the contents' key of that name."""
        if self._db is None:
            return 0
        with self._lock:
            self._expire(time.time() if now is None else now)
            return self._db.execute("SELECT COUNT(*) FROM answers WHERE deleted IS NOT NULL").fetchone()[0]

    @_read(list)
    def deleted_list(self, limit: int = MAX_ROWS, now: float | None = None) -> list:
        """Recently deleted, the latest deleted first: each answer as query() gives it, with `deleted` (when) and `until`
        (when it goes by itself, or None)."""
        if self._db is None:
            return []
        with self._lock:
            self._expire(time.time() if now is None else now)
            rows = self._db.execute("SELECT data, starred, deleted, id, verdict FROM answers WHERE deleted IS NOT NULL"
                                    " ORDER BY deleted DESC, id DESC LIMIT ?", (max(1, min(limit, MAX_ROWS)),)).fetchall()
        return [{**json.loads(data), "starred": bool(star), "verdict": _verdict(mark), "deleted": at, "until": self._until(at),
                 "id": seq} for data, star, at, seq, mark in rows]

    @_read(None)
    def deleted_get(self, seq: int, now: float | None = None) -> dict | None:
        """One answer of Recently deleted as deleted_list() gives each, by its id; None when it holds none of that id."""
        if self._db is None or not -2**63 <= seq < 2**63:   # an id SQLite cannot hold is none it keeps
            return None
        with self._lock:
            self._expire(time.time() if now is None else now)   # one past its days is gone, as in the list
            row = self._db.execute("SELECT data, starred, deleted, id, verdict FROM answers WHERE id = ? AND deleted IS NOT NULL",
                                   (seq,)).fetchone()
        return {**json.loads(row[0]), "starred": bool(row[1]), "verdict": _verdict(row[4]), "deleted": row[2],
                "until": self._until(row[2]), "id": row[3]} if row else None

    @_read(list)
    def deleted_ids(self, now: float | None = None) -> list:
        """The ids Recently deleted holds: what a server that starts takes as deleted, so that a late word about one of
        them (its code check, a follow-up) is not shown as a new answer."""
        if self._db is None:
            return []
        with self._lock:
            self._expire(time.time() if now is None else now)   # past its days it is no longer held
            return [row[0] for row in self._db.execute("SELECT id FROM answers WHERE deleted IS NOT NULL ORDER BY deleted")]

    @_read(list)
    def query(self, day: str = "", q: str = "", kind: str = "", limit: int = 60, starred: bool = False) -> list:
        """The answers asked for, the newest first: of one day, of one kind, holding every word of `q`, starred only.
        Each says whether it is starred, and its verdict."""
        if self._db is None:
            return []
        where, args = ["deleted IS NULL"], []   # a deleted answer is in Recently deleted (deleted_list) and nowhere else
        if day:
            where.append("day = ?"); args.append(day)
        if kind:
            where.append("kind = ?"); args.append(kind)
        if starred:
            where.append("starred = 1")
        for word in q.lower().split():
            # the word as written, % and _ included
            where.append("words LIKE ? ESCAPE '\\'")
            args.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        sql = "SELECT data, starred, id, verdict FROM answers WHERE " + " AND ".join(where) + " ORDER BY ts DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, max(1, min(limit, MAX_ROWS)))).fetchall()
        # The star, the verdict and the id are the row's own columns, not part of what was kept of the answer: an id is a
        # number. A file from elsewhere (./sidenote restore) could hold any text there, which the panel puts in its keys'
        # attributes
        return [{**json.loads(data), "starred": bool(star), "verdict": _verdict(mark), "id": seq} for data, star, seq, mark in rows]

    # ---------- what was heard (Keep what is heard) ----------

    def add_heard(self, ts: float, secs: float, lang: str, text: str) -> None:
        """One closed sentence: when it was heard, how long it took to say, the language it was written down in."""
        if self._db is None or not text:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        with self._lock:
            self._db.execute("INSERT INTO heard (ts, day, secs, lang, words) VALUES (?, ?, ?, ?, ?)",
                             (ts, day, round(secs, 2), lang or "", text))
            # the sum is kept up as rows come, so a sentence every few seconds does not read the whole table each time
            self._heard_bytes = self._heard_sum() if self._heard_bytes is None else (
                self._heard_bytes + len(text.encode("utf-8")) * HEARD_WORDS + HEARD_ROW)
            self._prune_heard(ts)
            self._db.commit()

    def _heard_sum(self) -> int:
        """What the heard table is counted at, in bytes (HEARD_ROW). Called with the lock held."""
        return self._db.execute("SELECT COALESCE(SUM(LENGTH(CAST(words AS BLOB))), 0) * ? + COUNT(*) * ? FROM heard",
                                (HEARD_WORDS, HEARD_ROW)).fetchone()[0]

    def _prune_heard(self, now: float) -> int:
        """Rows past the age, then the oldest until the table fits its own limit. Called with the lock held."""
        gone = 0
        if self.days > 0:
            # Rows come in order of time, so the first row says whether any is past the age: a look at one row
            first = self._db.execute("SELECT ts FROM heard ORDER BY id LIMIT 1").fetchone()
            if first and first[0] < now - self.days * 86400:
                gone += self._db.execute("DELETE FROM heard WHERE ts < ?", (now - self.days * 86400,)).rowcount
        if gone:
            self._heard_bytes = None
        if self.heard_max > 0:
            if self._heard_bytes is None:
                self._heard_bytes = self._heard_sum()
            while self._heard_bytes > self.heard_max:
                n = self._db.execute("DELETE FROM heard WHERE id IN (SELECT id FROM heard ORDER BY id LIMIT 64)").rowcount
                if not n:   # none is left
                    break
                gone += n
                self._heard_bytes = self._heard_sum()
        return gone

    @_read(False)
    def fresh(self) -> bool:
        """Whether no answer has been kept yet: a new install, as far as this store can tell. False with no store (no data
        folder), where there is nothing to tell it by."""
        if self._db is None:
            return False
        with self._lock:
            return self._db.execute("SELECT 1 FROM answers LIMIT 1").fetchone() is None

    @_read(False)
    def heard_any(self) -> bool:
        """Whether anything heard is kept."""
        if self._db is None:
            return False
        with self._lock:
            return self._db.execute("SELECT 1 FROM heard LIMIT 1").fetchone() is not None

    @_read(list)
    def heard_days(self) -> list:
        """[{"day", "n", "first", "last"}], the newest first: the days that hold what was heard."""
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute("SELECT day, COUNT(*), MIN(ts), MAX(ts) FROM heard GROUP BY day ORDER BY day DESC").fetchall()
        return [{"day": d, "n": n, "first": a, "last": b} for d, n, a, b in rows]

    @_read(list)
    def heard_lines(self, day: str, limit: int = MAX_HEARD) -> list:
        """One day's lines in the order they were said: [{"ts", "secs", "lang", "text"}]; of a longer day its newest."""
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute("SELECT ts, secs, lang, words FROM heard WHERE day = ? ORDER BY ts DESC LIMIT ?",
                                    (day, max(1, min(limit, MAX_HEARD)))).fetchall()
        return [{"ts": ts, "secs": secs, "lang": lang, "text": text} for ts, secs, lang, text in reversed(rows)]

    def prune(self, now: float | None = None) -> int:
        """Rows past the age, then the oldest until the rest fits the cap; never a starred one that is not deleted. A
        deleted answer goes once its days in Recently deleted are over, starred or not, and not by the age before that:
        an answer of 89 days deleted now went the next day, out from under the week it was said to be kept. Returns how
        many went."""
        if self._db is None:
            return 0
        now = time.time() if now is None else now
        gone = 0
        with self._lock:
            if self.days > 0:
                gone += self._db.execute("DELETE FROM answers WHERE ts < ? AND starred = 0 AND deleted IS NULL",
                                         (now - self.days * 86400,)).rowcount
            gone += self._expire(now)   # what has had its days in Recently deleted
            # What the rows take on disk, in bytes. LENGTH counted characters, and Korean text is three bytes each: a
            # 5 MB cap held 16 MB. Pages in use, read after each batch instead of summing every row.
            used = lambda: (self._db.execute("PRAGMA page_count").fetchone()[0]  # noqa: E731
                            - self._db.execute("PRAGMA freelist_count").fetchone()[0]) * self._db.execute("PRAGMA page_size").fetchone()[0]
            # What was heard goes by the same age, and fits its own limit, which is what keeps it from growing for ever
            self._prune_heard(now)
            # The cap counts the answers that are not starred: the bytes the starred ones hold come off the pages in use
            # (summed only once the file is past the cap, which most writes are not), and the oldest of the rest go
            # until the rest fits. A star then never costs the recent answers their room. What was heard comes off the
            # same way, so a long transcript never costs them theirs either: it has its limit, and they have theirs
            starred = 0
            if self.max_bytes > 0 and used() > self.max_bytes:
                starred = self._db.execute("SELECT COALESCE(SUM(LENGTH(CAST(data AS BLOB)) + LENGTH(CAST(words AS BLOB))), 0)"
                                           " FROM answers WHERE starred = 1 AND deleted IS NULL").fetchone()[0]
                heard = self._heard_bytes if self._heard_bytes is not None else self._heard_sum()
                # What was deleted goes first, the longest deleted first: an answer still shown is not pushed out to keep
                # one that was thrown away
                while used() - starred - heard > self.max_bytes:
                    n = self._db.execute("DELETE FROM answers WHERE id IN (SELECT id FROM answers WHERE deleted IS NOT NULL"
                                         " ORDER BY deleted LIMIT 8)").rowcount
                    if not n:   # Recently deleted is empty
                        break
                    gone += n
                while used() - starred - heard > self.max_bytes:
                    n = self._db.execute("DELETE FROM answers WHERE id IN (SELECT id FROM answers WHERE starred = 0"
                                         " ORDER BY ts LIMIT 8)").rowcount
                    if not n:   # none of the rest is left
                        break
                    gone += n
            self._db.commit()
            over = starred > self.max_bytes > 0   # the starred answers alone are past the cap: they stay all the same
            if over and not self._over:            # said once, not at every answer kept while it lasts
                log.warning("history: the starred answers alone take %.1f MB, over the %g MB cap "
                            "(SIDENOTE_HISTORY_MB): they are kept", starred / 1048576, round(self.max_bytes / 1048576, 2))
            self._over = over                      # once they fit again, a later time over the cap is said again
        return gone

    def clear(self) -> None:
        if self._db is None:
            return
        with self._lock:
            self._db.execute("DELETE FROM answers")
            self._db.execute("DELETE FROM heard")
            self._heard_bytes = 0
            self._db.commit()
            self._db.execute("VACUUM")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # the deleted rows stood on in the WAL until then
