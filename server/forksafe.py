"""Keeps fork() away from the threads that decode speech.

Measured: the server stopped answering anything for 95 minutes. Its main thread
sat inside asyncio's create_subprocess_exec (starting the Claude Code CLI), the `claude` child it had
started before was left defunct, and the container held 660 to 800% CPU the whole time, in
faster-whisper's own threads. Starting a child process forks the whole server, and a fork from a
process whose other threads are inside a native parallel region can leave the child waiting on a
lock that no thread holds in it any more; the parent then waits for that child to exec, forever.

So the two never happen together: the transcriber holds this lock while it decodes, and every
subprocess spawn waits for it. The waiting is a poll on the event loop (see spawn_guard), so the
loop keeps turning while a decode finishes, about 2 s for a `small` model on one utterance.
"""
from __future__ import annotations

import asyncio      # the sleep between two tries at the lock
import threading    # the lock itself, which a worker thread holds while it decodes

# One lock for the whole process. A threading.Lock, not an asyncio.Lock: the holder is a worker
# thread (the decode runs in an executor), and an asyncio lock may only be touched from the loop.
_native = threading.Lock()

# How long to wait between two tries while a decode holds the lock. 20 ms is far below how long a
# decode takes (seconds), so the extra wait before a spawn is noise; and far above the cost of one
# wake-up, so polling through a whole decode costs about a hundred of them.
POLL_SEC = 0.02


def native_work() -> threading.Lock:
    """Hold this around native CPU-bound work: `with forksafe.native_work(): ...`.

    The lock itself is returned rather than a wrapper, so `with` does the releasing, including
    when the decode raises."""
    return _native


class spawn_guard:
    """`async with forksafe.spawn_guard():` around starting a child process.

    The wait is a poll on the event loop, not a blocking acquire in a worker thread: a thread
    already inside `acquire` cannot be cancelled, so a cancelled analysis (a newer screen
    supersedes one every few seconds) would leave the lock taken by a thread nobody is waiting on
    any more, and from then on every decode and every spawn would wait on it for good."""

    def __init__(self) -> None:
        # Whether this instance is the one holding the lock. Without it, a guard cancelled before
        # it ever took the lock would release a lock held by somebody else on its way out.
        self._held = False

    async def __aenter__(self) -> "spawn_guard":
        # acquire(False) never blocks: it takes the lock now or says no, so the loop stays free.
        while not _native.acquire(False):
            # A cancel can only land here, on the sleep, never between taking the lock and the
            # line below that records it.
            await asyncio.sleep(POLL_SEC)
        self._held = True
        return self

    async def __aexit__(self, *exc) -> bool:
        # __aexit__ runs even when the body raised, so this is where the lock always goes back.
        if self._held:
            self._held = False
            _native.release()
        # False: whatever the body raised goes on to the caller. This guard is about the lock, not
        # about swallowing a failed spawn.
        return False
