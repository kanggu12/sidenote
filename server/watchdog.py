"""Notices that the event loop has stopped turning, and says so.

Nothing running on the event loop can report that the event loop is stuck, so this watches from
outside it, in two ways.

The hard one is `faulthandler.dump_traceback_later`: a timer in C, re-armed by a heartbeat on the
loop, which writes every thread's stack and ends the process when the heartbeat stops coming. It
has to be in C, because the stall this was written for holds the GIL. Measured: the
loop sat inside uvloop's own spawn (`uv_spawn` runs with the GIL held) for 95 minutes while
faster-whisper's threads held 660 to 800% CPU, and a watcher written in Python could not have run
a single line in all that time.

The soft one is a plain thread that logs a warning and a dump earlier, while the loop is merely
slow rather than wedged. It needs the GIL, so it is the one that may stay silent.

A server that answers nothing while it holds the CPU is worse than one that is plainly off: the
panel says so and `./sidenote up` undoes it. `docker kill -s USR1 sidenote` writes the same stacks
on demand, without ending anything.
"""
from __future__ import annotations

import asyncio        # the heartbeat task that keeps the timer disarmed
import faulthandler   # the timer and the stack dumps, both in C and both usable without the GIL
import logging        # the soft path says what it found in the usual place
import os             # the stall file's path, size and age
import signal         # SIGUSR1, for a dump on demand from outside the container
import sys            # stderr, as the dump's second destination
import threading      # the soft watcher runs in a thread of its own
import time           # monotonic for the heartbeat, strftime for the dump's header

log = logging.getLogger("sidenote.watchdog")

# The heartbeat task. asyncio keeps only a weak reference to a running task, so a task nothing
# holds can be collected mid-flight; this list is what holds it.
_tasks: list = []
# The stall file, held open for the life of the process: faulthandler writes to this file
# descriptor when its timer fires, and by then nothing in Python gets to run to open it.
_file = None
BEAT_SEC = 1.0        # how often the loop says it is alive
CHECK_SEC = 5.0       # how often the soft thread looks at the heartbeat
DUMP_MAX_BYTES = 1_000_000   # the stall file starts over past this, like every other log here


def _open_dump(dump_dir: str):
    """The stall file, opened once and kept open. None when there is no log folder (a dev run)."""
    if not dump_dir:          # no SIDENOTE_LOG_DIR: the dumps go to stderr alone
        return None
    try:
        path = os.path.join(dump_dir, "stall.txt")
        # Bounded like every other log here: past the cap the file starts over rather than growing.
        if os.path.exists(path) and os.path.getsize(path) > DUMP_MAX_BYTES:
            os.unlink(path)
        # Append, so an earlier dump survives this start; line buffered, so a dump written as the
        # process dies is on disk even though nothing gets to close the file.
        return open(path, "a", buffering=1)
    except OSError as exc:
        # A read-only or missing folder is not worth failing a start over: say so and carry on.
        log.warning("no stall file (%s); stacks go to the container's output", exc)
        return None


def _dump(why: str) -> None:
    """Every thread's stack, to the container's own output and to the stall file.

    This is the soft path, so it runs in Python and may write wherever it likes. The hard path
    (the C timer) can only write to the one file it was armed with."""
    # The container's output first: `./sidenote logs` shows it without opening the log folder.
    print(f"[watchdog] {why}", file=sys.stderr, flush=True)
    for f in (sys.stderr, _file):
        if f is None:       # no stall file (see _open_dump)
            continue
        try:
            # Capped in a run as well as at its start: stalls that repeat in one run grew it without limit
            if f is _file and f.tell() > DUMP_MAX_BYTES:
                f.seek(0)
                f.truncate()
            # A header with the time, so several stalls in one file can be told apart.
            f.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {why} ====\n")
            # all_threads: the interesting one is never the thread asking for the dump.
            faulthandler.dump_traceback(file=f, all_threads=True)
            f.flush()       # the process may be about to be killed from outside
        except Exception:
            # A dump that cannot be written must not take the watchdog down with it.
            pass


def start(loop: asyncio.AbstractEventLoop, warn_after: float, exit_after: float, dump_dir: str = ""):
    """Start the heartbeat and the watchers. 0 turns either step off. Returns a stop() to call
    on a clean shutdown, so the armed timer does not end a server that is merely closing down."""
    global _file
    try:                      # stacks on demand, from outside: docker kill -s USR1 sidenote
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
    except Exception:
        # Not every platform has SIGUSR1 (and a thread that is not the main one cannot register):
        # it is a convenience, not the watchdog itself.
        pass
    # Both steps off: nothing to start, and stop() still has to be callable by the caller.
    if warn_after <= 0 and exit_after <= 0:
        return lambda: None
    if dump_dir:    # a dump from the run before: the server simply vanished, and nothing said why
        try:
            path = os.path.join(dump_dir, "stall.txt")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                log.warning("a stall dump from an earlier run is in %s (%s)", path,
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path))))
        except OSError:
            pass
    _file = _open_dump(dump_dir)
    # The heartbeat, in a list so the loop's task and the watcher thread share one cell.
    beat = [time.monotonic()]
    # Cleared by stop(), which is what lets the watcher thread end on a clean shutdown.
    alive = threading.Event()
    alive.set()

    async def heartbeat() -> None:
        while True:
            if exit_after > 0:
                # Re-armed every beat: it only ever fires when the beats stop. In C, with its own
                # thread, so a loop that is stuck while holding the GIL cannot keep it quiet.
                # It starts a thread each time, and a process at its thread or pid limit cannot:
                # letting that end the heartbeat would leave the last timer armed on a healthy
                # server, which is exactly the thing this must never do.
                try:
                    faulthandler.dump_traceback_later(exit_after, repeat=False, exit=True,
                                                      file=_file or sys.stderr)
                except Exception as exc:
                    faulthandler.cancel_dump_traceback_later()
                    log.warning("could not arm the stall timer (%s); the thread watch still runs", exc)
            # Written after the arming, so the soft watcher never sees a beat the hard timer did
            # not get: both paths agree on when the loop was last alive.
            beat[0] = time.monotonic()
            await asyncio.sleep(BEAT_SEC)   # the only place this task gives the loop back

    _tasks.append(loop.create_task(heartbeat()))   # a task nothing holds can be collected
    # When to speak up. Never sooner than one check interval, or the first look would fire on a
    # heartbeat that is simply younger than the interval.
    first = max(warn_after if warn_after > 0 else exit_after, CHECK_SEC)

    def watch() -> None:
        """The soft path: a warning and a dump while the loop is slow rather than wedged."""
        said = False          # one dump per stall, not one every CHECK_SEC
        while alive.is_set():
            time.sleep(CHECK_SEC)
            late = time.monotonic() - beat[0]   # how long since the loop last said anything
            if late < first:
                said = False  # it is turning again: the next stall gets its own dump
                continue
            if not said:
                said = True
                # The dump first, the log line second: logging takes a lock that a forking thread
                # may hold, and the stacks matter more than the sentence.
                _dump(f"event loop stalled for {late:.0f}s")
                log.critical("the event loop has not turned for %.0fs; thread stacks in stall.txt", late)

    threading.Thread(target=watch, name="stall-watchdog", daemon=True).start()
    log.info("stall watchdog: stacks after %.0fs, exit after %.0fs", warn_after, exit_after)

    def stop() -> None:
        """Called from the lifespan's finally: a shutdown is not a stall."""
        alive.clear()                 # the watcher thread ends after its current sleep
        try:
            # Without this the last armed timer would fire mid-shutdown and kill a server that is
            # merely closing down (a slow aclose is enough to outlast exit_after).
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        for t in _tasks:              # the heartbeat itself
            t.cancel()
        _tasks.clear()                # so a second start() in the same process begins clean

    return stop
