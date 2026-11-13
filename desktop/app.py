"""Sidenote as one program on one PC, with no Docker: the server, the capture program and the panel, started and
watched together. The Windows app runs this; so does `python -m desktop` from a checkout.

    Sidenote.exe                  start everything and open the panel (when it is already running: open the panel)
    Sidenote.exe --no-browser     the same, without opening the panel
    Sidenote.exe --no-capture     the server and the panel only
    Sidenote.exe --check          start the server with stand-in models on a free port, check that it answers, stop
    python -m desktop [...]       the same from a checkout, with the packages of server/requirements.txt

The server runs as a child process and is started again when it stops (its stall watchdog ends it on purpose). The
capture program runs as a child process too, on the systems it supports; quitting it from its tray icon stops
everything. When nothing answers on Ollama's port and Ollama is installed, it is started as a child as well, with
the settings compose.yaml gives it, and stopped at the end so the GPU memory is free again. The logs are in the
data folder's logs/: the server's own (server.log, events.jsonl), and next to them, capped in size, what each child
printed (server-console.log, capture.log, ollama.log) and what this program did (app.log). The data folder:

    Windows   %LOCALAPPDATA%\\Sidenote
    macOS     ~/Library/Application Support/Sidenote
    Linux     $XDG_DATA_HOME/sidenote, or ~/.local/share/sidenote

What differs from the Docker setup (compose.yaml), as server_env() sets it; a SIDENOTE_* variable already set wins:
- the local model is this PC's Ollama, or any OpenAI-compatible server named in SIDENOTE_LOCAL_URL, and the panel
  offers to download the model that fits the GPU when there is none;
- the cloud agent is the CLI this PC has (Claude Code, else Codex) unless SIDENOTE_AGENT names one;
- web search for the local model is off: it goes through the SearXNG container (SIDENOTE_SEARCH_URL names another);
- code checks are off: code a model wrote runs only in the code runner's sandbox, which is a container.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
# The checkout, or the folder the executable keeps its files in: server/, panel/ and client/ are found from here.
ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
PORT = 8777
# The capture program's exit code when it asks to be started again (a restart from its tray icon or from the panel)
# while SIDENOTE_SUPERVISED is set: this program starts it, rather than it starting a copy of itself.
CAPTURE_RESTART = 75
# The capture program's exit code when another capture program connected to the app's server and took it over
# (client/capture.py, CAPTURE_TAKEN_OVER). The server listens on this PC alone, so the other one is a program of another
# account here pointed at this port: the app's own is started again and takes its server back.
CAPTURE_TAKEN_OVER = 77
LOG_CAP = 5 * 1024 * 1024          # bytes a log file reaches before it is rotated; one older file is kept
RESTARTS = (5, 600)                # a child started this many times within this many seconds is given up on
# A console program started from a windowless one gets a console window of its own unless this flag is given.
CREATE_NO_WINDOW = 0x08000000

# Ollama as compose.yaml runs it (its comments say why each one is set), for the Ollama this program starts itself.
OLLAMA_ENV = {
    "OLLAMA_CONTEXT_LENGTH": "16384",
    "OLLAMA_KEEP_ALIVE": "30m",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_NUM_PARALLEL": "2",
    "LLAMA_ARG_CACHE_IDLE_SLOTS": "false",
    "LLAMA_ARG_IMAGE_MAX_TOKENS": "1120",
    "OLLAMA_NOPRUNE": "1",
}


def data_dir() -> Path:
    """Where the logs, the settings, the kept answers and the speech model go (SIDENOTE_DATA_DIR overrides it)."""
    if os.environ.get("SIDENOTE_DATA_DIR"):
        return Path(os.environ["SIDENOTE_DATA_DIR"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Sidenote"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Sidenote"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "sidenote"


def server_env(base: dict, data: Path, port: int) -> dict:
    """The server's environment on the host: `base` with the defaults below added where it has none."""
    env = dict(base)
    if FROZEN:
        widen_path(env)                 # before the agent is looked for on it, below
    defaults = {
        "SIDENOTE_HOST": "127.0.0.1",
        "SIDENOTE_PORT": str(port),
        "SIDENOTE_LOG_DIR": str(data / "logs"),
        "HF_HOME": str(data / "hf"),                       # the speech model, downloaded at its first use
        "SIDENOTE_LOCAL_URL": "http://127.0.0.1:11434/v1",
        "SIDENOTE_LOCAL_PULL": "1",                         # the panel offers the model that fits the GPU
        "SIDENOTE_DESKTOP": "1",                            # the panel's directions name the app, not ./sidenote
        "SIDENOTE_SEARCH_URL": "",                          # no SearXNG on the host
        "SIDENOTE_RUNNER_URL": "",                          # no sandbox for model-written code on the host
        "SIDENOTE_TRUST_GATEWAY": "0",                      # no Docker port proxy in front: loopback only
        # the speech decoder's threads, capped as compose.yaml caps them
        "OMP_NUM_THREADS": base.get("SIDENOTE_WHISPER_THREADS", "4"),
        # the children print Korean and English; a Windows console's own code page would fail on either
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    # The cloud agent: the one SIDENOTE_AGENT names, else the CLI this PC has, Claude Code first. The server's own
    # default is Claude Code, so a PC with Codex alone would otherwise start with an agent it cannot run.
    # Not over an analyzer mode that names its agent (cli: Claude Code; api and claude: the Anthropic API; mock): the CLI
    # found was set over it, and a PC set to the API ran Claude Code
    if not env.get("SIDENOTE_AGENT") and not env.get("SIDENOTE_CLAUDE") and analyzer_of(env) not in ("cli", "api", "claude", "mock"):
        found = agent_found(env.get("PATH"))
        if found:
            env["SIDENOTE_AGENT"] = found
    # The CLI by its full path: on Windows an npm-installed one is claude.cmd or codex.cmd, which shutil.which finds and a
    # bare name started by the server does not (CreateProcess adds .exe alone), so the panel said "Not installed". The
    # agent by its name as the server reads it (agent_of), and a path already given, under either of its names, is kept.
    cli = AGENT_CLIS.get(agent_of(env))
    if cli and not (env.get("SIDENOTE_AGENT_BIN") or "").strip() and not (env.get("SIDENOTE_CLAUDE_BIN") or "").strip():
        full = shutil.which(cli, path=env.get("PATH"))
        if full:
            env["SIDENOTE_AGENT_BIN"] = full
    return env


AGENT_CLIS = {"claude-code": "claude", "codex": "codex"}   # each CLI agent's command

# Where the agents' installers and the usual version managers put their commands, for a login shell that gives no answer
AGENT_FOLDERS = (".local/bin", ".claude/local", ".npm-global/bin", ".bun/bin", ".volta/bin", ".cargo/bin", ".nix-profile/bin")


def login_path(env: dict) -> str:
    """The PATH of the person's own login shell, or "". The Finder and a desktop's menu start a program with a short PATH
    that lacks the folders the person's shell adds, so Claude Code, Codex and the node an npm install of them runs on
    would look absent. Asked once, with a time limit, in a session of its own, so an interactive shell cannot take a
    terminal or stop this program, and into a file, so a job its start-up files leave running cannot hold the answer."""
    shell = env.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")
    mark = "__sidenote_path__"          # what a shell's own greeting cannot be taken for
    try:
        with tempfile.TemporaryFile() as out:
            proc = subprocess.Popen([shell, "-ilc", f'printf "%s%s" "{mark}" "$PATH"'], env=dict(env),
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:   # a start-up file that never ends: the shell and what it started go
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                return ""
            out.seek(0)
            got = out.read().decode("utf-8", "replace")
    except (OSError, ValueError):           # no such shell
        return ""
    return got.rpartition(mark)[2].strip() if mark in got else ""


def widen_path(env: dict) -> str:
    """Add to env's PATH, after what it holds, the login shell's folders and the usual folders of the agents' installers,
    Homebrew's among them, that exist. Windows gives a double-click the whole PATH, and a terminal has the shell's
    already, so the shell is not asked there. Returns the new PATH."""
    if sys.platform == "win32":
        return env.get("PATH", "")
    home = Path(env.get("HOME") or Path.home())
    have = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
    in_terminal = bool(sys.stdin and sys.stdin.isatty())
    more = (([] if in_terminal else login_path(env).split(os.pathsep)) + [str(home / f) for f in AGENT_FOLDERS]
            + ["/opt/homebrew/bin", "/usr/local/bin"])
    for p in more:
        if p and p not in have and os.path.isdir(p):
            have.append(p)
    env["PATH"] = os.pathsep.join(have)
    return env["PATH"]


def agent_found(path: str | None) -> str:
    """The agent whose CLI is on this PATH: "claude-code", "codex", or "" for neither (the server then uses its
    default, and the panel says how to sign in)."""
    for name, agent in (("claude", "claude-code"), ("codex", "codex")):
        if shutil.which(name, path=path):
            return agent
    return ""


def role_cmd(*args: str) -> list[str]:
    """The command line that runs this program again in another role (--serve, --capture)."""
    if FROZEN:
        return [sys.executable, *args]
    return [sys.executable, "-m", "desktop", *args]


class CappedLog:
    """Text appended to `path` until the file reaches `cap` bytes; it then becomes `path`.1 (replacing the older
    one) and a new file starts, so a child that prints for weeks holds at most twice the cap on disk."""

    def __init__(self, path: Path, cap: int = LOG_CAP):
        self.path, self.cap = path, cap
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.f = open(path, "ab")

    def write(self, data: bytes) -> None:
        with self.lock:
            if self.f.closed:
                return
            self.f.write(data)
            self.f.flush()
            if self.f.tell() < self.cap:
                return
            self.f.close()
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
                self.f = open(self.path, "ab")
            except OSError:              # the older file is open elsewhere (an editor on Windows): start over
                self.f = open(self.path, "wb")

    def close(self) -> None:
        with self.lock:
            self.f.close()


def ui_lang() -> str:
    """The language of the app's own message boxes, by the rule the capture program follows (and is handed on to it):
    SIDENOTE_LANG when it names one, else English. The system's language is not read: a Korean Windows or Mac gave an
    app and a capture in Korean beside a guide and a launcher in English."""
    fixed = os.environ.get("SIDENOTE_LANG", "").strip().lower()
    return fixed if fixed in ("en", "ko") else "en"


# The message boxes in Korean, keyed by their English (the logs stay English)
KO = {
    "Another program is using the port Sidenote needs ({port}). Close that program, then start Sidenote again.":
        "다른 프로그램이 Sidenote가 쓰는 포트({port})를 쓰고 있습니다. 그 프로그램을 끈 뒤 Sidenote를 다시 켜세요.",
    "The Sidenote server did not start. The end of its log:": "Sidenote 서버를 시작하지 못했습니다. 로그 마지막 부분:",
    "Sidenote's server keeps stopping. The end of its log:": "Sidenote 서버가 계속 꺼집니다. 로그 마지막 부분:",
    "Ollama keeps stopping. The end of its log:": "Ollama가 계속 꺼집니다. 로그 마지막 부분:",
    "The capture program keeps stopping. The end of its log:": "캡처 프로그램이 계속 꺼집니다. 로그 마지막 부분:",
    "The logs are in {folder}. Start Sidenote again; if it happens again, open an issue with them.":
        "로그는 {folder}에 있습니다. Sidenote를 다시 켜 보고, 또 그러면 로그를 붙여 이슈를 열어 주세요.",
    "Sidenote goes on without starting Ollama: the local model answers only once Ollama runs.":
        "Sidenote는 Ollama를 켜지 않고 계속 실행됩니다. 이 PC의 모델은 Ollama가 켜져 있어야 답합니다.",
}


def t(text: str, **values) -> str:
    out = KO.get(text, text) if ui_lang() == "ko" else text
    return out.format(**values) if values else out


def say(text: str, log: CappedLog | None = None) -> None:
    """A line of this program's own, to its log and, when it has one, to its console."""
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + text
    if log is not None:
        log.write((line + "\n").encode("utf-8", "replace"))
    if sys.stdout is not None:
        print(line, flush=True)


def tell(text: str, log: CappedLog | None = None) -> None:
    """A problem the person has to know about. The Windows app has no console, so it is shown in a message box."""
    say(text, log)
    if sys.platform == "win32" and FROZEN:
        import ctypes
        MB_ICONWARNING, MB_TOPMOST = 0x30, 0x40000
        ctypes.windll.user32.MessageBoxW(None, text, "Sidenote", MB_ICONWARNING | MB_TOPMOST)
    elif sys.platform == "darwin" and FROZEN:
        # the Mac app has no console either: the system's own alert, the text passed as an argument, not as script
        script = 'on run argv\ndisplay alert "Sidenote" message (item 1 of argv) as warning\nend run'
        try:
            subprocess.run(["osascript", "-e", script, text], timeout=600, capture_output=True)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _windows_job():
    """A Windows job object that ends every process in it when this program ends, however it ends (Task Manager
    included): the server, the capture program, Ollama and what they started (the agent's CLI, Ollama's model
    runner) do not outlive it. None elsewhere, or when it cannot be made."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                      "OtherOperationCount", "ReadTransferCount",
                                                      "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x2000, 9
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                            ctypes.sizeof(info)):
        return None
    return lambda proc: kernel32.AssignProcessToJobObject(job, int(proc._handle))


_JOIN_JOB = None   # set by run(): puts a new child into the job above


# Linux only: prctl(PR_SET_PDEATHSIG) makes a child get SIGTERM when this program ends in any way, so a server is not
# left running with no supervisor after a crash or a kill -9 (the next start would find it up and only open the panel).
# The function is looked up here, before any fork: the child then makes one call and loads nothing.
try:
    import ctypes
    _PRCTL = ctypes.CDLL(None, use_errno=True).prctl if sys.platform.startswith("linux") else None
except (OSError, AttributeError):
    _PRCTL = None


def _die_with_parent() -> None:
    _PRCTL(1, signal.SIGTERM)            # 1: PR_SET_PDEATHSIG


def guard(argv: list[str], every: float = 1.0) -> int:
    """Run a program of another make (Ollama) as this program's child on a system with no PR_SET_PDEATHSIG, and end it
    once the app that started this guard is gone, as _end_with_parent ends the app's own roles. SIGTERM, as the app's
    stop sends it, ends the program too. Returns its exit code."""
    parent = int(os.environ.get("SIDENOTE_APP_PARENT") or os.getppid())
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL)

    def end(*_) -> None:
        if proc.poll() is None:
            proc.terminate()

    signal.signal(signal.SIGTERM, end)
    while proc.poll() is None:
        if os.getppid() != parent:
            end()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            break
        time.sleep(every)
    return proc.wait()


def _end_with_parent(every: float = 1.0) -> None:
    """macOS has no PR_SET_PDEATHSIG, so a child of the app looks at its parent once a second and ends itself the way
    SIGTERM ends it once the app is gone (force-quit, or killed): the next start would otherwise find the old server up
    and only open the panel, with a capture program nobody watches. SIDENOTE_APP_PARENT says which parent it had."""
    parent = int(os.environ.get("SIDENOTE_APP_PARENT") or os.getppid())

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(every)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch, name="end-with-parent", daemon=True).start()


class Child:
    """One child process, its output written to a CappedLog. `starts` keeps when it was started, so one that keeps
    stopping can be given up on instead of started for ever."""

    def __init__(self, name: str, cmd: list[str], env: dict, log: CappedLog, asked_code: int | None = None):
        self.name, self.cmd, self.env, self.log = name, cmd, env, log
        self.proc: subprocess.Popen | None = None
        self.starts: list[float] = []
        # The exit code with which the child asks to be started again (the capture program's CAPTURE_RESTART), if any
        self.asked_code = asked_code

    def start(self, *extra: str) -> None:
        """Starts it, with `extra` after its command. A start after an end the child asked for (asked_code: the
        capture program's tray Restart, or its restart after a deploy) is left out of `starts`: it says nothing about a
        child that keeps stopping, and five of them within ten minutes ended the whole app as if it did."""
        asked = self.asked_code is not None and self.proc is not None and self.proc.poll() == self.asked_code
        # A group of its own: Ctrl+C in this program's terminal reaches this program alone, which then stops each
        # child in order, instead of every child getting it at once.
        if sys.platform == "win32":
            group = {"creationflags": CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            group = {"start_new_session": True}
        if _PRCTL is not None:           # Linux: the child is told to stop when this program dies, a kill -9 included
            group["preexec_fn"] = _die_with_parent
        # elsewhere one of this program's own roles looks for that itself (_end_with_parent), told who its parent is
        env = {**self.env, "SIDENOTE_APP_PARENT": str(os.getpid())}
        self.proc = subprocess.Popen([*self.cmd, *extra], cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group)
        if _JOIN_JOB is not None:
            _JOIN_JOB(self.proc)
        if not asked:   # what given_up counts: the starts after ends that were not asked for
            self.starts.append(time.monotonic())
        threading.Thread(target=self._pump, args=(self.proc,), name=f"{self.name}-log", daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in iter(proc.stdout.readline, b""):
            self.log.write(line)

    def exited(self) -> int | None:
        """The exit code once it has ended; None while it runs (or before it was started)."""
        if self.proc is None:
            return None
        return self.proc.poll()

    def given_up(self) -> bool:
        count, within = RESTARTS
        now = time.monotonic()
        return sum(1 for t in self.starts if now - t < within) >= count

    def stop(self, timeout: float = 10, ask=None) -> bool:
        """Ends it; True when it ended by itself. `ask` asks it to close down first (the server's /server/stop), and
        only one that has not ended within `timeout` is killed."""
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return True
        if ask is not None and ask():
            try:
                proc.wait(timeout)       # its own shutdown runs: what the next start needs is kept, server_stop logged
                return True
            except subprocess.TimeoutExpired:
                pass                     # it did not close down in time: killed below, as one never asked
        if sys.platform == "win32":
            # Windows has no SIGTERM, and ending one process leaves its own children running (Ollama's model
            # runner holding the GPU memory, an agent's CLI): the whole tree goes.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        else:
            proc.terminate()             # SIGTERM: uvicorn and Ollama shut down cleanly on it
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
        return False


def ask_server_to_stop(port: int, token: str) -> bool:
    """Asks the server on this port to close down by itself, with the token it was started with; True when it said
    it will. Windows has no SIGTERM: without this the server was killed and its shutdown never ran."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"http://127.0.0.1:{port}/server/stop", data=b"", method="POST",
                                     headers={"X-Sidenote-Stop": token})
    try:
        with opener.open(request, timeout=3) as r:
            return r.status == 202
    except OSError:                      # not answering, or the token refused: it is stopped the other way
        return False


def health(port: int, timeout: float = 1.5) -> dict | None:
    """The server's /health on this port, or None when nothing (or something that is not Sidenote) answers."""
    # No proxy: a manual proxy on Windows is not bypassed for 127.0.0.1, and every check would fail through it.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            body = json.loads(r.read() or b"{}")
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("ok") is True and "analyzer" in body else None


def port_free(port: int) -> bool:
    """Nothing listens on the port. Asked by connecting, not by binding: a bind also fails for the connections a
    server that just stopped left behind (TIME_WAIT), which the next server's own bind passes."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return False
    except OSError:
        return True


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(ready, timeout: float, every: float = 0.5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if ready():
            return True
        time.sleep(every)
    return bool(ready())


def tail(path: Path, lines: int = 12) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def capture_supported() -> tuple[bool, str]:
    """Whether the capture program runs here, and a line to say about it ("" for nothing). It grabs the screen with
    mss, which reads Windows', macOS' and X11's screens, and the speaker sound with soundcard (WASAPI, Core Audio,
    PulseAudio)."""
    if sys.platform == "win32":
        return True, ""
    if sys.platform == "darwin":
        # macOS asks for Screen Recording at the first capture, and plays the speakers to no program: a loopback
        # input such as BlackHole is what the capture program listens to (client/capture.py, mac_loopback)
        return True, ("macOS asks once for Screen Recording for Sidenote: allow it in System Settings, then quit "
                      "Sidenote from its menu bar icon and open it again. For the speaker sound, install a loopback "
                      "input such as BlackHole and send the sound to it.")
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        if os.environ.get("WAYLAND_DISPLAY"):
            return True, ("This is a Wayland session: the screen is read through X11 (XWayland), which may show only "
                          "X11 windows. Log in to an X11 session if the panel shows a blank screen.")
        return True, ""
    return False, ("No screen to capture here (the capture program reads Windows', macOS' and X11's screens): the server and "
                   "the panel start, and another PC can send screens to them (docs/capture-client.md).")


def ollama_binary(path: str | None = None) -> str | None:
    """Ollama's command: on `path` (the server's PATH, widened for an app opened from the Finder, where Homebrew's is
    missing), else where Ollama's own installers put it."""
    found = shutil.which("ollama", path=path)
    if found:
        return found
    if sys.platform == "win32":          # where Ollama's installer puts it, when its folder is not on PATH
        guess = Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "Ollama" / "ollama.exe"
        if guess.is_file():
            return str(guess)
    if sys.platform == "darwin":         # Ollama for Mac is an app; its command is inside it until it links one
        guess = Path("/Applications/Ollama.app/Contents/Resources/ollama")
        if guess.is_file():
            return str(guess)
    return None


def analyzer_of(env: dict) -> str:
    """SIDENOTE_ANALYZER read as the server reads it (server/config.py): spaces round it dropped, and a value it does not
    know taken as local. Compared as typed, " local" or "Local" kept the app from starting Ollama for a server that ran
    the local model."""
    value = (env.get("SIDENOTE_ANALYZER") or "").strip().lower() or "local"
    return value if value in ("local", "agent", "cli", "api", "claude", "mock") else "local"


def agent_of(env: dict) -> str:
    """The cloud agent the server runs, read as it reads it (server/config.py): SIDENOTE_AGENT, else SIDENOTE_CLAUDE (its
    earlier name), else the one the analyzer mode names; spaces round it dropped and in any case, its other names taken
    for it (claude, cli and claude-cli are Claude Code, api the Anthropic API), and a name it does not know as Claude
    Code. Compared as typed, those names found no CLI, and on Windows the server could not start claude.cmd."""
    value = ((env.get("SIDENOTE_AGENT") or "").strip() or (env.get("SIDENOTE_CLAUDE") or "").strip()).lower()
    if not value:   # the agent the analyzer mode names: "cli" was Claude Code alone, "api" and "claude" the API
        value = {"cli": "claude-code", "api": "anthropic-api", "claude": "anthropic-api",
                 "mock": "mock"}.get(analyzer_of(env), "claude-code")
    value = {"cli": "claude-code", "api": "anthropic-api", "claude": "claude-code",
             "claude-cli": "claude-code"}.get(value, value)   # the other names, SIDENOTE_CLAUDE's own among them
    return value if value in ("claude-code", "codex", "anthropic-api", "off", "mock") else "claude-code"


def ollama_needed(env: dict) -> bool:
    """True when the local model is meant to be this PC's Ollama on its own port and nothing answers there."""
    url = env.get("SIDENOTE_LOCAL_URL", "")
    if analyzer_of(env) != "local" or not url.startswith(("http://127.0.0.1:11434", "http://localhost:11434")):
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:11434/api/version", timeout=1.5):
            return False
    except OSError:
        return True


def only_one(data: Path):
    """The lock that makes this the one copy of the app running on this PC: an open file the system releases when the
    process ends, however it ends. None when another copy holds it (its server may still be starting)."""
    data.mkdir(parents=True, exist_ok=True)
    f = open(data / "app.lock", "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


STAYS_UP = 5   # seconds a copy's server answers, with no capture program connected, before that copy is taken to run
PANEL_WAIT = 8   # seconds a copy that was starting has to bring its own panel up, before this start opens one


def panel_comes(port: int) -> bool:
    """A panel connects to the server on this port within PANEL_WAIT seconds."""
    end = time.monotonic() + PANEL_WAIT
    while time.monotonic() < end:
        if ((health(port) or {}).get("panel_clients") or 0) > 0:
            return True
        time.sleep(0.25)
    return False


def other_copy(data: Path, port: int, url: str, no_browser: bool, log: CappedLog):
    """Another copy of the app holds the lock. Its panel is opened once its server answers, and then:

    - with a capture program connected, that copy runs, and this start was only for the panel;
    - with none, it may be starting, or closing down (the app opened again right after a quit, its server still
      answering for a second or so). One closing down lets go of the lock once it has ended, and this copy takes it, to
      start in its place: waiting for a server alone, it once did nothing at all after a quit. A server that answers
      for STAYS_UP seconds belongs to a copy that runs (with no capture program, or one restarting).

    A copy whose server does not answer yet at the first look is starting, and opens its own panel once it is up: one
    from here as well put two panels up when the app was started twice within its first seconds. So after such a
    copy's start the panel is opened here only when none connects (that copy started with --no-browser).

    Returns (the lock, or None when this copy is not to start; whether the panel was opened)."""
    say("Sidenote is already running, starting or closing down; waiting for it", log)
    opened, up_since, end = False, None, time.monotonic() + 300
    starting = health(port) is None
    while True:
        lock = only_one(data)
        if lock is not None:
            return lock, opened
        answer = health(port)
        if answer is not None:
            if not opened and not no_browser:
                if not (starting and panel_comes(port)):
                    webbrowser.open(url)
                opened = True     # a panel is up either way, and it connects to whichever copy serves the port
            up_since = up_since or time.monotonic()
            if (answer.get("capture") or {}).get("clients") or time.monotonic() - up_since >= STAYS_UP:
                return None, opened
        else:
            up_since = None
        if time.monotonic() > end:
            say("the other copy neither came up nor ended within 5 minutes; not starting", log)
            return None, opened
        time.sleep(0.25)


def _stop_on_signals() -> None:
    """SIGTERM and SIGHUP (a closed terminal, a service manager) end this program the way Ctrl+C does: through the
    cleanup in run(), which stops the children. Their default would end it at once and leave them running."""
    if sys.platform == "win32":
        return
    import signal

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)


def run(args) -> int:
    """Start the server, Ollama when it is needed and the capture program, open the panel, and watch them."""
    global _JOIN_JOB
    _JOIN_JOB = _windows_job()
    _stop_on_signals()
    data = data_dir()
    logs = data / "logs"
    log = CappedLog(logs / "app.log")
    port = args.port
    url = f"http://127.0.0.1:{port}"
    lock = only_one(data)
    if lock is None:                     # another copy of the app: running, starting or closing down
        try:
            lock, opened = other_copy(data, port, url, args.no_browser, log)
        except KeyboardInterrupt:        # stopped while it waited (SIGTERM, Ctrl+C): nothing of its own to stop yet
            log.close()
            return 0
        if lock is None:
            log.close()
            return 0
        say("the other copy has ended; starting in its place", log)
        if opened:
            args.no_browser = True       # the panel opened on that copy connects to this one's server by itself
    elif health(port):                   # a Sidenote server that no copy of the app started (Docker's): its panel
        say("a Sidenote server the app did not start answers on this port (Docker's?): "
            + ("" if args.no_browser else "opened its panel, ") + "no capture program started", log)
        if not args.no_browser:
            webbrowser.open(url)
        log.close()
        return 0
    if not port_free(port):
        tell(t("Another program is using the port Sidenote needs ({port}). Close that program, then start Sidenote again.",
               port=port), log)
        log.close()
        return 1
    env = server_env(os.environ, data, port)
    # The server alone gets the token that lets this program ask it to close down (ask_server_to_stop)
    token = secrets.token_urlsafe(24)
    # The server writes server.log itself; what it prints also covers what comes before that file is open (an
    # import that fails) and uvicorn's own lines.
    server = Child("server", role_cmd("--serve", "--port", str(port)), {**env, "SIDENOTE_STOP_TOKEN": token},
                   CappedLog(logs / "server-console.log"))
    ollama: Child | None = None
    capture: Child | None = None
    try:
        needed = ollama_needed(env)
        binary = ollama_binary(env.get("PATH")) if needed else None
        if not needed and analyzer_of(env) == "local" \
                and env.get("SIDENOTE_LOCAL_URL", "").startswith(("http://127.0.0.1:11434", "http://localhost:11434")):
            # Ollama's own installer starts it at sign-in, with its defaults: a shorter context and images cut to fewer
            # tokens than OLLAMA_ENV gives, which blurs small code text. The tuned model brings its context along.
            say("Ollama was already running, with its own settings; quit it before starting Sidenote to have Sidenote's", log)
        if binary:
            # Linux ends it with this program (PR_SET_PDEATHSIG) and Windows with the job; elsewhere a guard of this
            # program's own runs it and ends it once this program is gone
            command = [binary, "serve"] if _PRCTL is not None or sys.platform == "win32" \
                else role_cmd("--guard", binary, "serve")
            ollama = Child("ollama", command, {**env, **{k: env.get(k, v) for k, v in OLLAMA_ENV.items()}},
                           CappedLog(logs / "ollama.log"))
            ollama.start()
            say(f"started Ollama ({binary})", log)
        server.start()
        say(f"starting the server on {url}", log)
        if not wait_for(lambda: health(port) is not None or server.exited() is not None, timeout=180) \
                or health(port) is None:
            tell(t("The Sidenote server did not start. The end of its log:") + "\n\n" + tail(server.log.path) + "\n\n"
                 + t("The logs are in {folder}. Start Sidenote again; if it happens again, open an issue with them.",
                     folder=logs), log)
            return 1
        say("the server is up", log)
        supported, why = capture_supported()
        if supported and not args.no_capture:
            capture = Child("capture", role_cmd("--capture", "--server", f"ws://127.0.0.1:{port}/ingest",
                                                "--no-auto-update"),
                            # its tray speaks the language this program's messages do: on macOS from the Finder
                            # there is no locale for it to read
                            {**env, "SIDENOTE_SUPERVISED": "1", "SIDENOTE_LANG": env.get("SIDENOTE_LANG") or ui_lang(),
                             # one run through all its starts: a start after one whose connection the server still
                             # holds is the same program to the server, and takes its place without a word
                             "SIDENOTE_CAPTURE_RUN": secrets.token_hex(8)},
                            CappedLog(logs / "capture.log"),
                            asked_code=CAPTURE_RESTART)   # its own restarts (tray Restart) are not failures
            capture.start()
        if why and not args.no_capture:
            say(why, log)
        if not args.no_browser:
            webbrowser.open(url)
        return watch(server, capture, ollama, log)
    except KeyboardInterrupt:
        return 0
    finally:
        if capture is not None and capture.exited() is None:
            ask_capture_to_quit(port)
            if not wait_for(lambda: capture.exited() is not None, timeout=5):
                capture.stop()
        server.stop(ask=lambda: ask_server_to_stop(port, token))
        if ollama is not None:
            ollama.stop()
        say("stopped", log)
        log.close()


def watch(server: Child, capture: Child | None, ollama: Child | None, log: CappedLog) -> int:
    """Start again what stops, until the capture program is quit (or this program is stopped)."""
    folder = server.log.path.parent
    while True:
        time.sleep(1)
        for child in (server, ollama):
            if child is None or child.exited() is None:
                continue
            if child is ollama and not ollama_needed(ollama.env):
                # something else answers on Ollama's port now (Ollama's own tray app, often, at sign-in): it serves the
                # model, so this one is not started again, and nothing else stops for it
                say("Ollama answers on its own now; Sidenote no longer starts it", log)
                ollama = None
                continue
            if child.given_up():
                if child is ollama:      # the local model is one engine: the server, the panel and the agent go on
                    tell(t("Ollama keeps stopping. The end of its log:") + "\n\n" + tail(child.log.path) + "\n\n"
                         + t("Sidenote goes on without starting Ollama: the local model answers only once Ollama runs."), log)
                    ollama = None
                    continue
                tell(t("Sidenote's server keeps stopping. The end of its log:") + "\n\n" + tail(child.log.path) + "\n\n"
                     + t("The logs are in {folder}. Start Sidenote again; if it happens again, open an issue with them.",
                         folder=folder), log)
                return 1
            say(f"the {child.name} stopped (exit {child.exited()}); starting it again", log)
            child.start()
        if capture is None or capture.exited() is None:
            continue
        code = capture.exited()
        if code == 0:                    # quit from its tray icon, or from the panel
            say("the capture program was quit; stopping", log)
            return 0
        asked = code == CAPTURE_RESTART  # a restart the person asked for: no sign of a program that keeps stopping
        if not asked and capture.given_up():
            tell(t("The capture program keeps stopping. The end of its log:") + "\n\n" + tail(capture.log.path) + "\n\n"
                 + t("The logs are in {folder}. Start Sidenote again; if it happens again, open an issue with them.",
                     folder=folder), log)
            return 1
        why = ("asked for a restart" if asked else "gave way to another capture program that connected to this server"
               if code == CAPTURE_TAKEN_OVER else f"stopped (exit {code})")
        say(f"the capture program {why}; starting it again", log)
        capture.start("--resumed")   # (one it asked for is not counted toward giving up: Child.start, asked_code)


def ask_capture_to_quit(port: int) -> None:
    """The capture program ends itself when the server asks, which also takes its icon out of the notification area
    (a killed one leaves the icon behind until the mouse passes over it)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(urllib.request.Request(f"http://127.0.0.1:{port}/capture/quit", data=b"", method="POST"), timeout=3)
    except OSError:
        pass


def serve(port: int) -> int:
    """The server itself, as docker/entrypoint.sh starts it in the image, ended as soon as its own close-down is done.

    uvicorn.run would close its loop with asyncio.run, which first waits for every job still on the loop's threads:
    the agent's CLI being asked what it runs on (up to 20 s), a screen being read, speech being decoded, the speech
    model being downloaded (minutes on a slow line). Python then waits again, for the download's own threads. None of
    that is kept once the server closes down, and this program gives its server 10 s before it ends it the hard way:
    a quit took 10.7 s on CI's Mac, and one during the first download 11.1 s here. So the loop is run here. Once the
    close-down has run, what it left running is cancelled as asyncio.run cancels it, so that its own clean-up runs (an
    answer being written ends its agent's CLI and deletes the screens it was given); then, once the answers' writer is
    done, nothing else is waited for. A download cut off this way is made again at the next start."""
    import asyncio

    import uvicorn

    from server import app as server
    # 64 MiB per message: a 4K frame of a photo-like screen is over uvicorn's default 16 MiB (docker/entrypoint.sh).
    # A close-down waits 5 s at most for open connections: a panel's socket that stopped reading held it for good, and
    # the close-down that keeps the remembered problems (.restart.npz) never ran (docker/entrypoint.sh says the same).
    # At most 512 connections at once, one more request answered 503 (docker/entrypoint.sh says why).
    config = uvicorn.Config(server.app, host=os.environ.get("SIDENOTE_HOST", "127.0.0.1"), port=port,
                            access_log=False, ws_max_size=64 * 1024 * 1024, timeout_graceful_shutdown=5,
                            limit_concurrency=512)
    if hasattr(config, "get_loop_factory"):      # the loop uvicorn.run would use (uvloop where it is there)
        loop = (config.get_loop_factory() or asyncio.new_event_loop)()
    else:                                        # an older uvicorn names it through the event loop policy
        config.setup_event_loop()
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # uvicorn closes down on SIGTERM as on Ctrl+C, then sends the signal again to the handler that was there before it ran,
    # to end the process the way that signal would have. The default there ended it at once, before the clean-up below: an
    # answer's agent CLI went on writing, and its screens stayed in the temporary folder. The app sends SIGTERM when asking
    # did not work (Child.stop), and so does the system when the app dies (PR_SET_PDEATHSIG, _end_with_parent on macOS).
    signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        loop.run_until_complete(uvicorn.Server(config).serve())
    except KeyboardInterrupt:                    # uvicorn raises again the Ctrl+C its close-down was asked with
        pass
    # Left running, an answer's task would leave its agent's CLI writing on, and spending, for an answer nobody sees.
    # Up to 3 s for those clean-ups.
    left = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in left:
        task.cancel()
    if left:
        loop.run_until_complete(asyncio.wait(left, timeout=3))
    server.HISTORY_WRITES.shutdown(wait=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def capture(argv: list[str]) -> int:
    """The capture program, run as its own script (client/capture.py) with these arguments."""
    import runpy
    script = ROOT / "client" / "capture.py"
    sys.argv = [str(script), *argv]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def python_c(code: str, argv: list[str]) -> int:
    """`python -c CODE ARGS` for the executable, which has no interpreter of its own to start: the capture program
    shows its tray menu by running a script that way with sys.executable."""
    sys.argv = ["-c", *argv]
    exec(compile(code, "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
    return 0


# What the server and the capture program import, checked by --check: in the Windows app, a package the build left
# out shows up here rather than at the first screen.
SERVER_PACKAGES = ("fastapi", "uvicorn", "websockets", "httpx2", "anthropic", "numpy", "PIL", "onnxruntime",
                   "faster_whisper")
CAPTURE_PACKAGES = ("mss", "soundcard", "pystray", "websocket")


def check() -> int:
    """Start the server with stand-in models on a free port, fetch its health and its panel, and stop it; then
    import what the capture program and the speech recognizer need. Exit 0 when all of it worked."""
    problems = []
    for name in SERVER_PACKAGES:
        try:
            importlib.import_module(name)
        except Exception as exc:         # a missing DLL is an OSError, a missing package an ImportError
            problems.append(f"import {name}: {exc}")
    # The capture program's packages, where it is part of the app. Imported on Windows; elsewhere only looked up,
    # since importing them there connects to the X display and the sound server, which a build machine lacks.
    if (ROOT / "client" / "capture.py").is_file() and (FROZEN or sys.platform == "win32"):
        for name in CAPTURE_PACKAGES:
            try:
                found = importlib.import_module(name) if sys.platform == "win32" else importlib.util.find_spec(name)
                if found is None:
                    problems.append(f"{name}: not in the app")
            except Exception as exc:
                problems.append(f"import {name}: {exc}")
    # the panel's libraries: part of the built app (desktop/build.py will not build without them); from a checkout they
    # are fetched separately, and a check without them only says so
    if not (ROOT / "panel" / "vendor").is_dir():
        missing = f"no panel libraries in {ROOT / 'panel' / 'vendor'} (python docker/fetch_vendor.py docker/vendor.json panel/vendor)"
        if FROZEN:
            problems.append(missing)
        else:
            print("note:", missing)
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="sidenote-check-") as d:
        env = server_env(os.environ, Path(d), port)
        token = secrets.token_urlsafe(24)
        env.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_STOP_TOKEN=token)
        log = CappedLog(Path(d) / "server.log")
        server = Child("server", role_cmd("--serve", "--port", str(port)), env, log)
        server.start()
        up = wait_for(lambda: health(port) is not None or server.exited() is not None, timeout=120) and health(port)
        page = ""
        if up:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(f"http://127.0.0.1:{port}/", timeout=10) as r:
                    page = r.read().decode("utf-8", "replace")
            except OSError as exc:
                problems.append(f"GET /: {exc}")
        else:
            problems.append("the server did not answer /health:\n" + tail(Path(d) / "server.log", 30))
        if up and "<html" not in page.lower():
            problems.append("GET / did not return the panel")
        # closed down as the app closes it: on Windows this is the one run of that path before a release
        if not server.stop(ask=lambda: ask_server_to_stop(port, token)) and up:
            problems.append("the server did not close down when asked (/server/stop):\n" + tail(Path(d) / "server.log", 20))
        log.close()
    report = [f"FAIL {p}" for p in problems] + ["ok" if not problems else f"{len(problems)} problem(s)"]
    print("\n".join(report))
    # The Windows app has no console to print to: SIDENOTE_CHECK_LOG names a file for the same lines (desktop/build.py)
    if os.environ.get("SIDENOTE_CHECK_LOG"):
        Path(os.environ["SIDENOTE_CHECK_LOG"]).write_text("\n".join(report) + "\n", encoding="utf-8")
    return 1 if problems else 0


def port_setting(env: dict) -> int:
    """SIDENOTE_PORT read as the server reads a number (server/config.py, env_int): spaces round it dropped, "8778.0" as
    8778, and what is not a port's number (a word, 0, 70000) as 8777. Read with int() alone, a word there ended the app
    in a traceback before it had a log, and the Windows app, which has no console, ended without a word."""
    raw = (env.get("SIDENOTE_PORT") or "").strip()
    try:
        port = int(float(raw)) if raw else PORT
    except (ValueError, OverflowError):   # a word, or "inf"
        return PORT
    return port if 0 < port < 65536 else PORT


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # The Windows app is built with no console, so it starts with no stdout or stderr at all.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if FROZEN and argv[:1] == ["-c"] and len(argv) > 1:
        return python_c(argv[1], argv[2:])
    # the server and the capture program, started by the app on a system with no PR_SET_PDEATHSIG: ended with it
    if argv[:1] in (["--capture"], ["--serve"]) and os.environ.get("SIDENOTE_APP_PARENT") and _PRCTL is None \
            and sys.platform != "win32":
        _end_with_parent()
    if argv[:1] == ["--guard"] and len(argv) > 1:   # another program, ended with the app (guard)
        return guard(argv[1:])
    if argv[:1] == ["--capture"]:        # everything after it is the capture program's own (client/capture.py --help)
        return capture(argv[1:])
    ap = argparse.ArgumentParser(prog="sidenote", description="Start Sidenote on this PC: the server, the capture "
                                 "program and the panel, without Docker.")
    port = port_setting(os.environ)       # the default, which SIDENOTE_PORT moves
    ap.add_argument("--port", type=int, default=port,
                    help=f"the server's port on 127.0.0.1 (default {port}: SIDENOTE_PORT when it names one, else {PORT})")
    ap.add_argument("--no-browser", action="store_true", help="do not open the panel")
    ap.add_argument("--no-capture", action="store_true", help="do not start the capture program")
    ap.add_argument("--check", action="store_true",
                    help="start the server with stand-in models on a free port, check that it answers, and stop")
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.serve:
        return serve(args.port)
    if args.check:
        return check()
    return run(args)
