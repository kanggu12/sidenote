"""Does the server notice a stuck event loop, and does it keep fork() away from speech decoding?

    python3 tests/stall_guard.py

Both are answers to a 95-minute hang (main thread inside
create_subprocess_exec, 660 to 800% CPU in faster-whisper's threads, nothing in the log).
No server, no whisper: the watchdog runs in a child process that blocks its own loop on purpose,
and the fork guard is exercised against a thread that holds the native lock.
"""
import asyncio
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
from server import forksafe  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail else ""))


# ---------- the watchdog, in a child process that hangs its own loop ----------
CHILD = '''
import asyncio, sys, time
sys.path.insert(0, {root!r})
from server import watchdog
async def main():
    watchdog.start(asyncio.get_running_loop(), 1, 6, {dump!r})
    await asyncio.sleep(2)          # a few heartbeats first
    time.sleep(60)                  # the loop stops turning here
asyncio.run(main())
'''

with tempfile.TemporaryDirectory() as tmp:
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), dump=tmp)],
                       capture_output=True, text=True, timeout=60)
    took = time.monotonic() - t0
    dump = Path(tmp, "stall.txt")
    text = dump.read_text() if dump.exists() else ""
    # faulthandler ends it itself, so the code is its own 1, not one this program chooses.
    check("a stuck loop is noticed and the process ended", p.returncode == 1, f"exit={p.returncode} {took:.0f}s")
    check("it takes no longer than one more look (under 15 s)", took < 15, f"{took:.1f}s")
    check("every thread's stack is left in stall.txt",
          "Timeout" in text and "Thread 0x" in text and "asyncio" in text, f"{len(text)} bytes")

# A stall that holds the GIL: this is the one the watchdog exists for (uvloop spawns a child with
# the GIL held, which is where the 95 minutes went), and a watcher written in Python cannot run a
# line while it lasts. Only faulthandler's own timer, which is C, can end it.
CHILD_GIL = """
import asyncio, re, sys
sys.path.insert(0, {root!r})
from server import watchdog
async def main():
    watchdog.start(asyncio.get_running_loop(), 0, 4, {dump!r})
    await asyncio.sleep(2)
    re.match(r"(a+)+b", "a" * 60)      # the GIL is held in C for a very long time
asyncio.run(main())
"""
with tempfile.TemporaryDirectory() as tmp:
    t0 = time.monotonic()
    try:
        p = subprocess.run([sys.executable, "-c", CHILD_GIL.format(root=str(ROOT), dump=tmp)],
                           capture_output=True, text=True, timeout=40)
        code, took = p.returncode, time.monotonic() - t0
    except subprocess.TimeoutExpired:
        code, took = None, time.monotonic() - t0
    dump = Path(tmp, "stall.txt")
    text = dump.read_text() if dump.exists() else ""
    check("a stall that holds the GIL is ended too", code == 1, f"exit={code} {took:.0f}s")
    check("and the stacks are left then too", "Timeout" in text and "Thread 0x" in text, f"{len(text)} bytes")

# Slow but alive: the soft watcher writes a warning dump and nothing is ended.
CHILD_WARN = """
import asyncio, sys, time
sys.path.insert(0, {root!r})
from server import watchdog
async def main():
    watchdog.start(asyncio.get_running_loop(), 1, 0, {dump!r})   # warn only, no hard stop
    await asyncio.sleep(1)
    time.sleep(12)
    print("alive")
asyncio.run(main())
"""
with tempfile.TemporaryDirectory() as tmp:
    p = subprocess.run([sys.executable, "-c", CHILD_WARN.format(root=str(ROOT), dump=tmp)],
                       capture_output=True, text=True, timeout=60)
    text = Path(tmp, "stall.txt").read_text() if Path(tmp, "stall.txt").exists() else ""
    check("a loop that is only slow is not ended, only warned about",
          p.returncode == 0 and "alive" in p.stdout and "event loop stalled" in text,
          f"exit={p.returncode} {len(text)} bytes")

# a loop that keeps turning is never touched
CHILD_OK = '''
import asyncio, sys
sys.path.insert(0, {root!r})
from server import watchdog
async def main():
    watchdog.start(asyncio.get_running_loop(), 1, 3, "")
    for _ in range(40):
        await asyncio.sleep(0.1)
    print("alive")
asyncio.run(main())
'''
p = subprocess.run([sys.executable, "-c", CHILD_OK.format(root=str(ROOT))],
                   capture_output=True, text=True, timeout=30)
check("a loop that keeps turning is left alone", p.returncode == 0 and "alive" in p.stdout,
      f"exit={p.returncode} {p.stdout.strip()}")


# ---------- the fork guard ----------
async def guard_waits():
    ticks = [0]

    async def tick():
        while True:
            ticks[0] += 1
            await asyncio.sleep(0.02)

    beat = asyncio.create_task(tick())

    def native():                      # what whisper does to a core
        with forksafe.native_work():
            time.sleep(0.6)

    th = threading.Thread(target=native)
    th.start()
    await asyncio.sleep(0.05)          # let the thread take the lock
    ticks[0] = 0
    t0 = time.monotonic()
    async with forksafe.spawn_guard():
        waited = time.monotonic() - t0
        during = ticks[0]
    th.join()
    beat.cancel()
    return waited, during


waited, during = asyncio.run(guard_waits())
check("no child process is started while speech is being decoded", waited > 0.4, f"waited {waited:.2f}s")
check("the event loop keeps turning while it waits", during > 5, f"{during} ticks")


async def guard_free():
    t0 = time.monotonic()
    async with forksafe.spawn_guard():
        pass
    return time.monotonic() - t0


check("with nothing being decoded it goes through at once", asyncio.run(guard_free()) < 0.2, f"{asyncio.run(guard_free()):.3f}s")

print(f"\n==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)
