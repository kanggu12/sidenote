"""The desktop shortcut's start window reading the launcher's output as it is written (client/launch.pyw: run, reader,
latest_line), on the system it runs on, with no window: the desktop workflow runs this on Windows, macOS and Linux, and
tests/run.sh with the server's suites. Windows reads through a handle of its own made by CreateFileW, which nothing else
here reaches; POSIX reads at an offset (pread).

    .venv/bin/python tests/start_output.py

A program of this Python stands in for the launcher, printing numbered lines, through run() itself (CREATE_NO_WINDOW on
Windows, a TemporaryFile, the reader's handle), while latest_line() is read over and over as the window reads it on its
timer: once at a pace a start prints at, once as fast as lines can be written and read, where reads and writes interleave.
Reading through the launcher's own position put its lines over each other there ("step 2292 of the start,step 2339 ...",
a second handle to the same open file planted on Windows), which the order check below catches.
"""
import importlib.machinery
import importlib.util
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail != "" and not ok else ""), flush=True)


# launch.pyw as a module: definitions only, its window starts under __main__ alone, and it imports tkinter only when drawing
loader = importlib.machinery.SourceFileLoader("launch_under_check", str(ROOT / "client" / "launch.pyw"))
spec = importlib.util.spec_from_loader("launch_under_check", loader)
L = importlib.util.module_from_spec(spec)
loader.exec_module(L)
LINE = "step {:02d} of the start, a line long enough to be read whole: " + "x" * 40
WHOLE = re.compile(r"step (\d{2,4}) of the start, a line long enough to be read whole: x{40}")


def run_together(s: str, n: int) -> bool:
    """Not the start of one of the n lines. A line read as it is being written may stop short, as a terminal shows it (a
    progress line has no end of line yet), but it is one line's beginning. A line cut inside its number leaves the
    number's first digits ("step 1" of "step 10 ..."): held against line 1 alone, that read was taken for two lines
    run together, and the suite failed once on a runner for it."""
    cut = re.fullmatch(r"step (\d*)", s)                    # cut in the number, or right after it
    if cut:
        return not any(f"{i:02d}".startswith(cut.group(1)) for i in range(n))
    m = re.match(r"step (\d+)", s)                          # past the number: the line that number names
    return not LINE.format(int(m.group(1))).startswith(s) if m else not "step ".startswith(s)


def start(n: int, pause: float, poll: float) -> None:
    """One start of n lines, `pause` apart, read every `poll` seconds while it runs."""
    child = [sys.executable, "-c",
             "import time\n"
             f"for i in range({n}):\n"
             f"    print({LINE!r}.format(i), flush=True)\n"
             f"    time.sleep({pause})\n"]
    kinds, names, done = [], [], {}
    real = L.reader

    def noting(out):                                         # the same reader, what it gave and its file's name noted
        names.append(out.name)
        got = real(out)
        kinds.append(type(got).__name__)
        return got

    L.reader = noting
    try:
        t = threading.Thread(target=lambda: done.update(zip(("rc", "tail"), L.run(child))))
        t.start()
        seen = []
        while t.is_alive():
            line = L.latest_line()
            if line and (not seen or seen[-1] != line):
                seen.append(line)
            time.sleep(poll)
        t.join()
    finally:
        L.reader = real
    own = "BufferedReader" if sys.platform == "win32" else "int"   # a handle of its own on Windows, the descriptor for pread
    check(f"the reader is the system's own way ({own})", kinds == [own], kinds)
    nums = [int(m.group(1)) for m in map(WHOLE.fullmatch, seen) if m]
    check("the line read follows the lines printed, as they come", len(nums) >= 5 and nums == sorted(nums), (len(nums), nums[:10]))

    check("...each one line, never two run together", not any(run_together(s, n) for s in seen),
          [s for s in seen if run_together(s, n)][:2])
    lines = [x for x in L.decode(done.get("tail", b"")).splitlines() if x.strip()]
    whole = lines[1:] if len(lines) < n else lines            # run() hands back the last 64 KB, which may start inside a line
    want = [LINE.format(i) for i in range(n)]
    check("the launcher's output arrives whole and in order: the reads moved nothing it writes by",
          done.get("rc") == 0 and len(whole) > 0 and whole == want[-len(whole):],
          (done.get("rc"), len(whole), [x for x in whole if x not in want][:2]))
    check("after the start nothing is read", L.latest_line() == "")
    if sys.platform == "win32":                               # POSIX's temporary file has no name to look for
        time.sleep(0.3)
        check("the temporary file is gone with its handles", names and not os.path.exists(names[0]), names)


print("\n[what counts as one line's beginning]")
cuts = ["", "st", "step ", "step 1", "step 10", "step 10 of the st", LINE.format(7), "step 29", "step 299"]
check("a line cut anywhere, inside its number too, is one line's beginning",
      not [s for s in cuts if run_together(s, 3000)], [s for s in cuts if run_together(s, 3000)])
joined = ["step 01 of the start,step 02 of", LINE.format(3) + "step 04", "step 4", "step 400", "tep 01", "step x"]
check("two lines run together, a line begun in its middle and a number no line has are not",
      all(run_together(s, 40) for s in joined), [s for s in joined if not run_together(s, 40)])

print(f"\n[a start at a start's pace, {sys.platform}]")
start(40, 0.05, 0.02)
print("\n[lines as fast as they come, read as fast]")
start(3000, 0.0, 0.0)
print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
