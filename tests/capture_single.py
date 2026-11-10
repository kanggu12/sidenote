"""One capture program at a time for a server: the guard a capture program holds while it runs (OneCapture in
client/capture.py), and the desktop shortcut's starter finding the one that runs (capture_alive in client/launch.pyw).

    .venv/bin/python tests/capture_single.py

Two capture programs for one server send every screen and every sound twice, and nothing stopped the second where the
launcher could not see the first: a WSL that cannot start Windows programs cannot read Windows' process list, and a
program that is connecting again is not in the server's count. Checked here, with no Windows and no screen: the guard is
a lock the system holds for a process and drops with it (the holders here are other processes, one of them killed), a
second start ends with its own exit code and two lines before it connects or captures anything, the starts that must
never be refused are not (a program restarting itself, one under the desktop app, --once, a folder that gives no
lock), and the starter opens the panel where a program holds the guard. The guard's files are in a folder of this
test's own. On Windows the guard is a named mutex, which this does not reach.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
CLIENT = ROOT / "client"
WORK = Path(tempfile.mkdtemp(prefix="sidenote-single-"))
# The guard's files in a folder of this test's own, for this process and every one it starts: never the runtime
# folder of the user who runs this, where a capture program that really runs keeps its own
os.environ["XDG_RUNTIME_DIR"] = str(WORK)
os.environ["SIDENOTE_LANG"] = "en"           # the program's two lines as written; Korean is asked for by name below
os.environ.pop("SIDENOTE_SUPERVISED", None)  # only the check that is about the desktop app sets it
sys.path.insert(0, str(CLIENT))
import capture  # noqa: E402

PASS, FAIL = [], []
STARTED = []                                 # every process started here, ended at the end whatever happened
SERVER = "ws://127.0.0.1:18777/ingest"       # no server is asked: the guard comes before any connection
PAST = 41                                    # the exit code of a start that got past the guard, in MAIN below


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


# A process that takes the guard as a capture program does and holds it until its stdin closes
HOLD = """
import sys
sys.path.insert(0, sys.argv[1])
import capture
guard = capture.OneCapture(sys.argv[2])
print("held" if guard.take() else "refused", flush=True)
sys.stdin.read()
"""
# capture.py's own main() as far as the guard: the first thing it does once the guard has let it by ends the process
# with PAST, so nothing connects and nothing is captured
MAIN = f"""
import os, sys
sys.path.insert(0, sys.argv[1])
import capture
capture.set_dpi_aware = lambda: os._exit({PAST})
sys.argv = ["capture.py", *sys.argv[2:]]
capture.main()
"""


def holder(server=SERVER):
    """A process holding the guard for `server`, once it has said so."""
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(CLIENT), server], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    STARTED.append(proc)
    said = proc.stdout.readline().strip()
    return proc, said


def let_go(proc):
    """The holder ends as a program ends: its input closes and it returns."""
    proc.stdin.close()
    proc.wait(timeout=10)


def start(*options, env=None, limit=30):
    """main() started as a capture program for SERVER with `options`: its exit code, what it printed, the seconds."""
    began = time.monotonic()
    done = subprocess.run([sys.executable, "-c", MAIN, str(CLIENT), "--server", SERVER, *options],
                          capture_output=True, text=True, timeout=limit, env={**os.environ, **(env or {})})
    return done.returncode, done.stdout + done.stderr, time.monotonic() - began


def load_launch():
    """client/launch.pyw as a module (its name ends in .pyw, which import does not read)."""
    loader = importlib.machinery.SourceFileLoader("launch_single", str(CLIENT / "launch.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


try:
    # ---- the name two programs for one server share
    name = capture.instance_name
    check("one server has one name, however this PC is written: 127.0.0.1, localhost, ::1, upper case, a path or none",
          len({name("ws://127.0.0.1:18777/ingest"), name("ws://localhost:18777/ingest"), name("ws://[::1]:18777/ingest"),
               name("WS://LOCALHOST:18777/ingest"), name("ws://127.0.0.1:18777"), name(" ws://127.0.0.1:18777/ingest ")}) == 1)
    check("...another port or another host is another name, and the scheme's own port is the one not written",
          name("ws://127.0.0.1:18777/ingest") != name("ws://127.0.0.1:18778/ingest")
          and name("ws://127.0.0.1:18777/ingest") != name("ws://192.0.2.7:18777/ingest")
          and name("ws://192.0.2.7/ingest") == name("ws://192.0.2.7:80/ingest")
          and name("wss://192.0.2.7/ingest") == name("wss://192.0.2.7:443/ingest"))
    odd = [name("ws://127.0.0.1:port/ingest"), name("not an address"), name("ws://[::1/ingest"), name("")]
    check("...and text that is no address still gives a name: 16 hex digits, never an error",
          all(len(n) == 16 and all(c in "0123456789abcdef" for c in n) for n in odd), str(odd))

    # ---- the lock itself
    guard = capture.OneCapture(SERVER)
    path = Path(guard.lock_path())
    check("the guard's file is in the user's runtime folder, named for the user and the server",
          path.parent == WORK and path.name == f"sidenote-capture-{os.getuid()}-{name(SERVER)}.lock", str(path))
    check("the first one takes the guard", guard.take() is True and path.is_file())
    check("...its file is the user's alone and holds nothing", (path.stat().st_mode & 0o777) == 0o600 and path.stat().st_size == 0,
          oct(path.stat().st_mode))
    second = capture.OneCapture(SERVER)
    began = time.monotonic()
    refused = second.take(0.4)
    waited = time.monotonic() - began
    check("a second one is refused, after asking for as long as it was given", refused is False and 0.35 <= waited < 2.0,
          f"{refused} after {waited:.2f} s")
    other = capture.OneCapture("ws://127.0.0.1:18778/ingest")
    check("...one for another server is not", other.take() is True)
    other.release()
    guard.release()
    check("let go, the guard is the next one's", second.take() is True)
    second.release()

    # ---- held by a process, dropped with it
    proc, said = holder()
    check("a process holds the guard", said == "held", said)
    check("...and another process is refused while it runs", capture.OneCapture(SERVER).take() is False)
    proc.kill()                              # ended with no chance to clean up, as a crash ends a program
    proc.wait(timeout=10)
    after = capture.OneCapture(SERVER)
    check("a holder that was killed leaves nothing behind to refuse the next start: the lock went with the process",
          after.take() is True and path.is_file())
    after.release()

    # ---- no guard to be had is no refusal
    lost = WORK / "no-such-folder"
    os.environ["XDG_RUNTIME_DIR"] = str(lost)   # set to what is not there: the temporary folder serves
    fallback = Path(capture.OneCapture(SERVER).lock_path())
    os.environ["XDG_RUNTIME_DIR"] = str(WORK)
    check("with no runtime folder the file is in the temporary folder", fallback.parent == Path(tempfile.gettempdir()), str(fallback))
    blocked = capture.OneCapture("ws://127.0.0.1:18779/ingest")
    Path(blocked.lock_path()).mkdir()        # a folder where the file goes: it cannot be opened as one
    check("a file that cannot be opened leaves the program running unguarded", blocked._try() is None and blocked.take() is True)
    linked = capture.OneCapture("ws://127.0.0.1:18780/ingest")
    target = WORK / "elsewhere"
    os.symlink(target, linked.lock_path())   # a link put where the file goes
    check("a link in the file's place is not followed: no guard, and nothing made where it points",
          linked._try() is None and linked.take() is True and not target.exists())
    real_fstat = os.fstat
    try:                                     # another user's file under the guard's name, as the file's owner reads
        os.fstat = lambda fd: types.SimpleNamespace(st_uid=os.getuid() + 1)
        foreign = capture.OneCapture("ws://127.0.0.1:18781/ingest")
        got = foreign._try()
    finally:
        os.fstat = real_fstat
    check("another user's file under the name is no guard, and no refusal", got is None and foreign.fd is None, str(got))

    # ---- a capture program started while one runs
    proc, said = holder()
    rc, out, took = start()
    check("a second capture program ends with its own exit code before it connects or captures anything",
          rc == capture.CAPTURE_BUSY == 76, f"exit {rc}: {out!r}")
    check("...saying that one runs already, and how to end that one",
          "Another capture program is already running for this server, so this one ends." in out
          and "Quit in its tray icon, or ./sidenote capture-stop" in out, out)
    rc_ko, out_ko, _ = start(env={"SIDENOTE_LANG": "ko"})
    check("...in Korean too", rc_ko == 76 and "캡처 프로그램이 이미 실행 중" in out_ko and "capture-stop" in out_ko, out_ko)
    rc, out, _ = start("--once")
    check("--once sends one screen beside whatever runs: never refused", rc == PAST, f"exit {rc}: {out!r}")
    rc, out, _ = start(env={"SIDENOTE_SUPERVISED": "1"})
    check("under the desktop app the program is never refused (the app would only start it again)", rc == PAST, f"exit {rc}: {out!r}")
    rc, out, took = start("--resumed")
    check("a program restarting itself asks for seconds, for the one before it to end, and is refused only then",
          rc == 76 and 4.0 <= took < 20.0, f"exit {rc} after {took:.1f} s")
    # the real program, nothing replaced: the same end, by the path the launcher starts it. Without a tray icon and with
    # no display named, so that even a guard that let it by could show nothing on the screen of whoever runs this
    bare = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    done = subprocess.run([sys.executable, "-X", "utf8", "-u", str(CLIENT / "capture.py"), "--server", SERVER, "--no-tray"],
                          capture_output=True, text=True, timeout=30, env=bare)
    check("client/capture.py itself, started as the launcher starts it, ends the same way",
          done.returncode == 76 and "Another capture program is already running" in done.stdout, f"exit {done.returncode}: {done.stdout!r} {done.stderr!r}")
    # the one before it ends a moment after the next one started, as at a restart
    resumed = subprocess.Popen([sys.executable, "-c", MAIN, str(CLIENT), "--server", SERVER, "--resumed"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    STARTED.append(resumed)
    time.sleep(1.0)
    still = resumed.poll()
    let_go(proc)
    rc = resumed.wait(timeout=30)
    check("...and takes the guard once that one has ended: a restart is not refused by the program it replaces",
          still is None and rc == PAST, f"after 1 s: {still}, then exit {rc}")
    rc, out, _ = start()
    check("with none running a start goes on", rc == PAST, f"exit {rc}: {out!r}")

    # ---- the desktop shortcut's starter
    launch = load_launch()
    opened, begun = [], []
    launch.webbrowser = types.SimpleNamespace(open=lambda url: opened.append(url))   # never the real browser
    servers = [SERVER, "ws://localhost:18777/ingest", "wss://192.0.2.7/ingest", "ws://[::1]:18777/ingest", "ws://127.0.0.1:port/x",
               "not an address", ""]
    check("the starter names a server as the capture program does",
          [launch.instance_name(s) for s in servers] == [capture.instance_name(s) for s in servers]
          and launch.CAPTURE_BUSY == capture.CAPTURE_BUSY)
    check("...and looks for the guard where the program keeps it",
          launch.guard_file(name(SERVER)) == capture.OneCapture(SERVER).lock_path())
    quiet = "ws://127.0.0.1:18790/ingest"    # a server no program was ever started for
    check("no capture program, no guard: the starter says none runs, and makes no file by asking",
          launch.capture_alive(quiet) is False and not Path(launch.guard_file(name(quiet))).exists()
          and launch.capture_alive(SERVER) is False)
    proc, said = holder()
    check("a capture program that runs is found by the guard it holds, connected or not", launch.capture_alive(SERVER) is True)
    check("...under this PC's other name too, and not for another server",
          launch.capture_alive("ws://localhost:18777/ingest") is True and launch.capture_alive("ws://127.0.0.1:18778/ingest") is False)

    def launcher_says(*lines):
        """launch() with the launcher's output given: what it printed, its status, what it opened and started."""
        import contextlib
        import io
        output = "\n".join(lines).encode("utf-8") + b"\n"
        launch.run = lambda command: (0, output)
        launch.missing_modules = lambda: []          # the capture packages as installed: this Python need not have them
        del opened[:], begun[:]
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            rc, _ = launch.launch(["wsl.exe"], 8777, True, "the starter's own hint")
        return rc, printed.getvalue()

    start_line = "SIDENOTE-START\t\\\\wsl.localhost\\Some\\repo\\client\\capture.py\t--server\t" + SERVER + "\t--log\tC:\\logs\\capture.log"
    rc, printed = launcher_says("  ok the server is up", start_line)
    check("handed a start while a capture program runs for that server, the starter opens the panel and starts none",
          rc == 0 and "[dry-run] open: http://127.0.0.1:18777" in printed and "[dry-run] start:" not in printed, printed)
    let_go(proc)
    rc, printed = launcher_says("  ok the server is up", start_line)
    check("...and with none running it starts the program", rc == 0 and "[dry-run] start:" in printed and "[dry-run] open:" not in printed, printed)

    # a program that found the guard taken between the starter's look and its own start: its exit code is no failure
    class Ended:
        """A started program that has ended already, with the exit code it was made with."""
        code = 76

        def __init__(self, program, **how):
            begun.append((program, how))

        def poll(self):
            return self.code

    real = subprocess
    launch.subprocess = types.SimpleNamespace(Popen=Ended, DEVNULL=real.DEVNULL, list2cmdline=real.list2cmdline)
    launch.capture_clients = lambda port: 0          # the server, with no capture program connected
    launch.time = types.SimpleNamespace(sleep=lambda seconds: None)
    launch.run = lambda command: (0, (start_line + "\n").encode("utf-8"))
    del opened[:], begun[:]
    rc, shown = launch.launch(["wsl.exe"], 8777, False, "")
    check("a program that ends because another took the guard first is no failure: the panel opens",
          rc == 0 and len(begun) == 1 and opened == ["http://127.0.0.1:18777"], f"{rc} {opened} {shown!r}")
    Ended.code = 1
    del opened[:], begun[:]
    rc, shown = launch.launch(["wsl.exe"], 8777, False, "")
    check("...and one that ends with any other code still is, with the command that shows why",
          rc == 1 and not opened and b"capture.py" in shown, f"{rc} {opened} {shown!r}")
finally:
    for proc in STARTED:                     # by the handles kept here: nothing is looked up by name
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
