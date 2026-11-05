#!/usr/bin/env python3
"""sidenote code runner: a small, locked-down execution service.

It runs the code from a solution and returns its real output, so a user can check an answer against the actual
run. Only the sidenote server reaches it, through a Unix socket in a volume the two share (compose service
"runner", which has no network at all; a TCP port instead when RUNNER_SOCKET is not set, for tests). The
container is read-only, has an init process that reaps orphans, and keeps four capabilities, for this process
alone: it starts every compile and every run of an input as a user of its own, one of RUN_UIDS taken in turn
(SETUID, SETGID), hands it its folder (CHOWN) and stops what it leaves (KILL). A run cannot signal or read this
process, reach its socket, or touch the files and processes of the compile or of another input.

Each request, one at a time:
- the code is compiled by its user in its own folder, readable by the users that run it, who cannot change it;
- each input then runs as a user of its own, in a folder of its own, with CPU, memory, file-size and process
  rlimits, no core dump and a wall-clock timeout, its output going to files only this process can open, so a
  program printing without end is stopped at the file-size limit instead of filling the runner;
- afterwards every process of those users is killed, and a helper started as each of them removes everything it
  owns in /work, /tmp, /dev/shm and /dev/mqueue (however deep or unreadable) and its System V shared memory,
  semaphores and message queues. If anything is left after that, the runner takes no more runs and reports
  itself unhealthy until it is restarted.

Over TCP (Kubernetes) the port is open to anything that can reach it, the runs this process starts among them, so
with RUNNER_TOKEN set a /run must carry "Authorization: Bearer <token>" (the server's SIDENOTE_RUNNER_TOKEN). The
token is taken out of this process's environment before any run starts, and the process is not dumpable, so a run
cannot read it. GET /health answers without it: it says only whether the runner is clean and busy.

Request (POST /run, JSON): {"lang", "code", "stdin", "timeout"}. Response (JSON):
{"ok", "stage", "exit", "stdout", "stderr", "stdout_truncated", "stderr_truncated",
 "timed_out", "output_limited", "elapsed"}, or {"ok": false, "busy": true} while another run holds
the runner, or {"ok": false, "error": ...}. With "stdins" (a list) instead of "stdin" the code is compiled
once and run on each input, each by a user of its own: {"ok", "stage": "run", "runs": [one response like the
above per input]}, or the compile's failure as above.
"""
from __future__ import annotations

import ctypes
import hmac       # the token is compared in constant time
import itertools
import json
import os
import re
import resource
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_OUTPUT = 64 * 1024            # bytes returned per stream; the rest is reported as truncated
OUTPUT_FILE_CAP = 8 * 1024 * 1024  # RLIMIT_FSIZE: a run writing more than this is stopped (SIGXFSZ)
COMPILE_FILE_CAP = 64 * 1024 * 1024   # a compiler's files: Go's archive of net/http is over 8 MB (/work holds 256 MB)
HARD_TIMEOUT_CAP = 30.0           # a request can never ask for more wall-clock than this
COMPILE_CAP = 20.0                # a compile's own wall-clock, whatever the run's timeout (Kotlin's takes seconds)
COMPILE_CPU = 40                  # and its CPU seconds: compilers on a JVM use both CPUs (compose: cpus 2)
MEM_BYTES = 512 * 1024 * 1024     # address space for Python, C, C++ and Bash, and the C and C++ compilers
DATA_BYTES = 768 * 1024 * 1024    # writable memory for a JVM or a Go program, which reserve far more address space
MAX_STDINS = 8                    # inputs one request may run the compiled code on
NODE_HEAP_MB = 512                # node reserves ~480 MB of address space just to start: it gets a heap cap instead
NPROC = 64
BUSY_WAIT = 15.0                  # a run waits this long for the one before it, then is told the runner is busy
WORK, TMP = "/work", "/tmp"
WIPED = (WORK, TMP, "/dev/shm", "/dev/mqueue")   # every place a run can write, emptied after it
OUT = "/out"                      # the output files: this process's alone (compose: a tmpfs of mode 0700)
# The users compiles and runs are started as, one after another (the Dockerfile beside this makes them): a request takes
# at most 2 + MAX_STDINS (a compile, the Go repair's second compile, and one per input), so none comes round
# twice in one.
RUN_UIDS = tuple(range(10100, 10132))
NEXT_UID = itertools.cycle(RUN_UIDS)
RUN_LOCK = threading.Lock()
DIRTY = threading.Event()         # set when a run could not be cleaned up after: no more runs until a restart

# A JVM reserves far more address space than it uses, like node: it gets a heap cap and the limit on writable
# memory instead of the address-space limit, a serial collector, two CPUs' worth of threads (the container's
# `cpus: 2` is a quota: the JVM, like Go, sees all of the host's CPUs and would start threads for each, against
# NPROC), a large stack for deep recursion, and no perf data files.
JVM = ["java", "-Xmx256m", "-Xss64m", "-XX:+UseSerialGC", "-XX:CICompilerCount=2", "-XX:ActiveProcessorCount=2",
       "-XX:MaxDirectMemorySize=64m", "-XX:-UsePerfData"]
LANGS = {
    # lang: (source filename, compile argv or None, run argv, the run's memory limit, the compile's): "as" the
    # address space, "data" writable memory (a runtime that reserves far more address space than it uses), None
    # the runtime's own (node's heap cap; a compiler on a JVM or Go's, under the container's 1 GB)
    # The run names the compiled program by its folder's path ({b}): it runs in a folder of its own.
    "python":     ("main.py",   None, ["python3", "-I", "{b}/main.py"], "as", "as"),
    # --require: the names LeetCode's judge has ready for an answer (a heap, a deque, lodash), as getters, so a
    # run that asks for none pays nothing (runner/js_globals.js)
    "javascript": ("main.js",   None, ["node", f"--max-old-space-size={NODE_HEAP_MB}", "--require",
                                       "/app/js_globals.js", "{b}/main.js"], None, None),
    "typescript": ("main.ts",   ["node", "/app/ts_strip.js", "main.ts", "main.js"],
                   ["node", f"--max-old-space-size={NODE_HEAP_MB}", "--require", "/app/js_globals.js",
                    "{b}/main.js"], None, None),
    "c":          ("main.c",    ["gcc", "-O2", "-std=c11", "-o", "a.out", "main.c", "-lm"], ["{b}/a.out"], "as", "as"),
    "cpp":        ("main.cpp",  ["g++", "-O2", "-std=c++23", "-o", "a.out", "main.cpp"], ["{b}/a.out"], "as", "as"),
    "java":       ("Main.java", ["javac", "-J-Xmx384m", "-J-XX:+UseSerialGC", "-J-XX:ActiveProcessorCount=2",
                                 "-J-XX:-UsePerfData", "-encoding", "UTF-8", "Main.java"],
                   [*JVM, "-cp", "{b}", "Main"], "data", None),
    "kotlin":     ("main.kt",   ["kotlinc", "main.kt", "-include-runtime", "-nowarn", "-d", "main.jar"],
                   [*JVM, "-jar", "{b}/main.jar"], "data", None),
    "go":         ("main.go",   ["go", "build", "-gcflags=-e", "-o", "a.out", "main.go"], ["{b}/a.out"], "data", None),
    "bash":       ("main.sh",   None, ["bash", "{b}/main.sh"], "as", "as"),
}
# C++ is compiled as C++23 (LeetCode's), and code that does not compile so is tried as C++17 (Programmers'): from
# C++20 <string> brings std::count along, so a global `count` beside `using namespace std` stops compiling. When
# both fail, the C++23 errors are the ones returned.
COMPILE_AGAIN = {"cpp": ["g++", "-O2", "-std=c++17", "-o", "a.out", "main.cpp"]}
# Go names every package it uses in an import block. An answer written on a judge's page, or read off a screen
# whose editor holds the block out of sight, often has none ("undefined: sort"), so a Go compile that failed is
# tried once more with the standard packages the compiler itself named. Only those: Go refuses a package that is
# imported and not used, and the compiler's own message is the one thing that knows which are missing.
# Only a bare name: "undefined: strings.Joinn" is a member the answer spelled wrong in a package it already
# imports, and compiling again with that package named twice cannot work.
GO_UNDEFINED = re.compile(r"undefined: (\w+)\b(?![ \t]*\.)")   # not past the line: the next error starts "./main.go"
GO_PACKAGE = {n: n for n in ("sort", "strings", "strconv", "math", "fmt", "os", "bufio", "bytes", "errors",
                             "slices", "maps", "reflect", "unicode", "time", "regexp", "io", "cmp", "sync",
                             "iter")}
GO_PACKAGE.update({"heap": "container/heap", "list": "container/list", "ring": "container/ring",
                   "bits": "math/bits", "rand": "math/rand", "big": "math/big", "cmplx": "math/cmplx",
                   "utf8": "unicode/utf8", "atomic": "sync/atomic", "json": "encoding/json",
                   "binary": "encoding/binary", "hex": "encoding/hex", "base64": "encoding/base64",
                   "sha256": "crypto/sha256", "md5": "crypto/md5", "sortutil": "sort"})
GO_PACKAGE_CLAUSE = re.compile(r"^[ \t]*package[ \t]+\w+[^\n]*\n", re.M)
# Compiler settings by environment: kotlinc's JVM, and Go's caches in the build folder (HOME is that folder).
# GOMAXPROCS=2: Go also sees all of the host's CPUs, and `go build` with a thread pool for each hit NPROC.
COMPILE_ENV = {"kotlin": {"JAVA_OPTS": "-Xmx512m -XX:+UseSerialGC -XX:ActiveProcessorCount=2 -XX:-UsePerfData"},
               "go": {"GOCACHE": "{cwd}/.gocache", "GOPATH": "{cwd}/.gopath", "GOFLAGS": "-buildvcs=false",
                      "GOMAXPROCS": "2", "GOTOOLCHAIN": "local"}}
GO_CACHE_SEED = "/opt/gocache"   # the standard packages compiled when the image was made (the Dockerfile beside this)
# A Go program's runtime does not start under the address-space limit (it died in rt0_go): it gets Go's own
# memory target, and the limit on writable memory as the hard one.
RUN_ENV = {"go": {"GOMEMLIMIT": "256MiB", "GOMAXPROCS": "2"}}
ESM = re.compile(r"^\s*(import\s|import\{|export\s)", re.M)
JAVA_PACKAGE = re.compile(r"^[ \t]*package\s+[\w$]+(?:\s*\.\s*[\w$]+)*\s*;", re.M)   # `package a . b ;` is one too
# main as Java takes it, its modifiers in any order (`static public void main`)
JAVA_MAIN = re.compile(r"\b(?:(?:public|protected|final|synchronized|strictfp)\s+)*static\s+"
                       r"(?:(?:public|protected|final|synchronized|strictfp)\s+)*void\s+main\s*\(")
JAVA_DECL = re.compile(r"\b((?:(?:public|final|abstract|sealed|non-sealed|strictfp|static)\s+)*)"
                       r"(?:class|record|enum|interface)\s+([A-Za-z_$][\w$]*)")


def _go_imports(code: str, stderr: str) -> str | None:
    """The Go source with an import block for the standard packages the compiler says are undefined, or None
    when it named none of them. A second import declaration is allowed, so the block goes after the package
    clause and nothing else is touched (the harness's own aliased imports stay). The clause is found on source
    whose comments and literals are blanked, since an answer that keeps an earlier try in a block comment has
    the word there too, and the block would land inside the comment."""
    want = sorted({GO_PACKAGE[n] for n in set(GO_UNDEFINED.findall(stderr)) if n in GO_PACKAGE})
    masked = _java_mask(code)   # Go's comments and literals are the same shapes, and its raw string too
    # one it already imports under its own name is not what is missing. The path has to be read off the source
    # (masking blanks the string an import is written as) and on a line of its own: the harness's own imports
    # are aliased (`sn_fmt "fmt"`), so the answer's bare fmt is still undefined and still has to be added.
    want = [p for p in want if not re.search(r'^[ \t]*(?:import[ \t]+)?"%s"[ \t]*$' % re.escape(p), code, re.M)]
    if not want:
        return None
    block = "import (\n" + "".join('\t"%s"\n' % p for p in want) + ")\n"
    m = GO_PACKAGE_CLAUSE.search(masked)
    return code[:m.end()] + block + code[m.end():] if m else block + code


def _java_mask(code: str) -> str:
    """Java source with its comments and string and char literals blanked out (lines kept), so a class or main
    named in a comment or a string is not taken for one."""
    out, i, n = [], 0, len(code)
    blank = lambda t: re.sub(r"[^\n]", " ", t)  # noqa: E731
    while i < n:
        if code.startswith("//", i):
            j = code.find("\n", i)
            j = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif code.startswith('"""', i):
            j = code.find('"""', i + 3)
            j = n if j < 0 else j + 3
        elif code[i] == "`":   # Go's raw string, which Java does not have
            j = code.find("`", i + 1)
            j = n if j < 0 else j + 1
        elif code[i] in "\"'":
            j = i + 1
            while j < n and code[j] not in (code[i], "\n"):
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            out.append(code[i])
            i += 1
            continue
        out.append(blank(code[i:j]))
        i = j
    return "".join(out)


def _drop_package(code: str) -> str:
    """Java source without its package declaration, found where comments and strings are blanked out (a line of a
    text block that reads like one stays)."""
    m = JAVA_PACKAGE.search(_java_mask(code))
    return code[:m.start()] + code[m.end():] if m else code


def _java_entry(code: str) -> tuple[str, str]:
    """(file name's class, class to run) of Java source: its top-level public class names the file, and runs if it
    has main of its own (not a nested class's); otherwise the first top-level class that has main runs."""
    m = _java_mask(code)
    classes = []   # (name, public, has main), top-level only
    for d in JAVA_DECL.finditer(m):
        if m.count("{", 0, d.start()) - m.count("}", 0, d.start()) != 0:
            continue
        start = m.find("{", d.end())
        depth, end = 0, len(m)
        for k in range(start, len(m)) if start >= 0 else ():
            depth += (m[k] == "{") - (m[k] == "}")
            if depth == 0:
                end = k
                break
        own_main = start >= 0 and any(m.count("{", start, x.start()) - m.count("}", start, x.start()) == 1
                                      for x in JAVA_MAIN.finditer(m, 0, end) if x.start() > start)
        classes.append((d.group(2), "public" in d.group(1).split(), own_main))
    public = next((c for c in classes if c[1]), None)
    name = public[0] if public else "Main"
    runs = public[0] if public and public[2] else next((c[0] for c in classes if c[2]), name)
    return name, runs


def _limits(cpu_seconds: int, memory: str | None, file_cap: int = OUTPUT_FILE_CAP, cwd: str | None = None):
    def apply():
        # The folder is entered here, not through Popen's cwd: that happens while the child is still this
        # process (root without CAP_DAC_OVERRIDE, which cannot enter a folder of the run's own user), while this
        # runs after the user has been taken on.
        if cwd:
            os.chdir(cwd)
        # CPU seconds is a hard ceiling even if wall-clock does not catch a busy loop.
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        if memory == "as":
            resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))
        elif memory == "data":
            resource.setrlimit(resource.RLIMIT_DATA, (DATA_BYTES, DATA_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_cap, file_cap))
        # 1, not 0: WSL hands core dumps to a helper that writes them to Windows, and only a
        # limit of exactly 1 makes the kernel skip a piped core dump.
        resource.setrlimit(resource.RLIMIT_CORE, (1, 1))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (NPROC, NPROC))
        except (ValueError, OSError):
            pass
        os.setsid()   # own process group, so a timeout kills children too
    return apply


def _head(path: str) -> tuple[str, bool]:
    """The first MAX_OUTPUT bytes of a file as text, and whether there was more."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_OUTPUT + 1)
    except OSError:
        return "", False
    return data[:MAX_OUTPUT].decode("utf-8", "replace"), len(data) > MAX_OUTPUT


def _spawn(argv, cwd, stdin_data: bytes, timeout: float, cpu_seconds: int, memory: str | None, tag: str,
           uid: int, umask: int, extra_env: dict | None = None, file_cap: int = OUTPUT_FILE_CAP):
    """Run argv as `uid` in cwd, its output going to files in OUT. Returns (exit, stdout, stdout_cut, stderr,
    stderr_cut, timed_out, output filled): whether an output file reached the cap (Python, Node and Java get a
    write error there instead of the signal, and a program may carry on past it). Kills the whole group on
    timeout."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": cwd, "TMPDIR": cwd, "LANG": "C.UTF-8",
           "PYTHONIOENCODING": "utf-8"}
    env.update({k: v.replace("{cwd}", cwd) for k, v in (extra_env or {}).items()})
    out_path, err_path = os.path.join(OUT, f"{tag}.out"), os.path.join(OUT, f"{tag}.err")
    try:
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            p = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                 user=uid, group=uid, extra_groups=[], umask=umask,
                                 preexec_fn=_limits(cpu_seconds, memory, file_cap, cwd))
        timed = False
        try:
            p.communicate(input=stdin_data, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        except BrokenPipeError:   # it exited without reading its input
            p.wait()
        so, so_cut = _head(out_path)
        se, se_cut = _head(err_path)
        full = any(os.path.getsize(f) >= min(file_cap, OUTPUT_FILE_CAP) for f in (out_path, err_path))
        return p.returncode, so, so_cut, se, se_cut, timed, full
    finally:
        for f in (out_path, err_path):
            try:
                os.unlink(f)
            except OSError:
                pass


def _user_procs(me: int, uids=None) -> list[tuple[int, bool]]:
    """(pid, is a zombie) of the processes of `uids` (this process's own uid when None) other than `me` and the
    init process, and other than those started from outside the container (a health check: parent 0, which no
    run's process can have)."""
    want = {str(u).encode() for u in (uids if uids is not None else (os.getuid(),))}
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in (1, me):
            continue
        try:
            with open(f"/proc/{name}/status", "rb") as f:
                fields = dict(ln.split(b":", 1) for ln in f if b":" in ln)
        except OSError:
            continue
        if fields.get(b"Uid", b"").split()[:1] == [] or fields[b"Uid"].split()[0] not in want \
                or fields.get(b"PPid", b"").strip() == b"0":
            continue
        found.append((int(name), fields.get(b"State", b"").strip().startswith(b"Z")))
    return found


def _kill_leftovers(uids=None) -> int:
    """Kill every process a run left behind: every process of the runs' users (or of this process's own, in the
    helper), whatever it did to its process group or its environment. Pass after pass until one finds none alive,
    since a fork bomb forks while it is being killed, and then a moment for the init process to reap them: until
    then they still count against the next run's process limit (a JVM compile right after a fork bomb could not
    start its threads)."""
    me, killed = os.getpid(), 0
    for _ in range(20):
        alive = [pid for pid, zombie in _user_procs(me, uids) if not zombie]
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
        if not alive:
            break
        time.sleep(0.05)
    deadline = time.time() + 2.0
    while _user_procs(me, uids) and time.time() < deadline:
        time.sleep(0.05)
    return killed


def _empty(root: str) -> None:
    """Remove everything in a folder, however deep, long-named or unreadable a run made it: walked by file
    descriptor relative to the folder above (no path longer than a name, no recursion), one folder open at a
    time, going back up through "..". Every entry is looked at once, the names left in a folder carried down
    with it, so a folder that cannot be removed does not cost a new scan of everything beside it."""
    def names_in(fd) -> list:
        try:
            with os.scandir(fd) as it:
                return [e.name for e in it]
        except OSError:
            return []

    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    down = []   # (name, the names still to look at in the folder above) from root to the folder open as fd
    try:
        names = names_in(fd)
        while True:
            enter = None
            while names:
                name = names.pop()
                try:
                    folder = stat.S_ISDIR(os.lstat(name, dir_fd=fd).st_mode)
                except OSError:
                    continue
                try:
                    os.rmdir(name, dir_fd=fd) if folder else os.unlink(name, dir_fd=fd)
                except OSError:
                    if folder:   # not empty, or not this user's: look inside it
                        enter = name
                        break
            if enter is not None:
                try:
                    os.chmod(enter, 0o700, dir_fd=fd)   # a folder (not a link), owned by this user
                    child = os.open(enter, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError:
                    continue   # not this user's: leave it and go on with the rest of this folder
                os.close(fd)
                fd = child
                down.append((enter, names))
                names = names_in(fd)
                continue
            if not down:
                return
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = parent
            name, names = down.pop()
            try:
                os.rmdir(name, dir_fd=fd)
            except OSError:
                pass
    except OSError:
        pass
    finally:
        os.close(fd)


IPC_TABLES = ("shm", "sem", "msg")


def _ipc_ids(uids=None) -> list[tuple[str, int]]:
    """The System V IPC objects of `uids` (this process's own uid when None): (table, id)."""
    want = {str(u) for u in (uids if uids is not None else (os.getuid(),))}
    found = []
    for table in IPC_TABLES:
        try:
            with open(f"/proc/sysvipc/{table}", encoding="ascii") as f:
                head, *rows = [ln.split() for ln in f if ln.strip()]
        except (OSError, ValueError):
            continue
        uid = head.index("uid")
        found += [(table, int(r[1])) for r in rows if len(r) > uid and r[uid] in want]
    return found


def _ipc_clear() -> None:
    """Remove a run's System V shared memory, semaphores and message queues: they are not files, and every run
    shares the container's IPC namespace (a segment one run wrote was read by the next)."""
    libc = ctypes.CDLL(None, use_errno=True)
    remove = {"shm": lambda i: libc.shmctl(i, 0, None), "sem": lambda i: libc.semctl(i, 0, 0),
              "msg": lambda i: libc.msgctl(i, 0, None)}   # IPC_RMID is 0
    for table, ident in _ipc_ids():
        remove[table](ident)


def _wipe() -> None:
    """In the helper, as one of the runs' users: remove what it owns in every place a run can write (it can remove
    nothing else: the folders are sticky, the others' files are not its own) and its System V IPC objects."""
    for root in WIPED:
        _empty(root)
    _ipc_clear()


def _owned_in(root: str, uids) -> bool:
    """Whether any of `uids` still owns something in a folder."""
    try:
        return any(e.stat(follow_symlinks=False).st_uid in uids for e in os.scandir(root))
    except OSError:
        return True   # it cannot be read: not known to be clean


def _owners() -> set:
    """The runs' users that own something left in the places a run can write, or System V IPC objects."""
    found = set()
    for root in WIPED:
        try:
            for e in os.scandir(root):
                uid = e.stat(follow_symlinks=False).st_uid
                if uid in RUN_UIDS:
                    found.add(uid)
        except OSError:
            continue
    for table in IPC_TABLES:
        try:
            with open(f"/proc/sysvipc/{table}", encoding="ascii") as f:
                head, *rows = [ln.split() for ln in f if ln.strip()]
            k = head.index("uid")
            found |= {int(r[k]) for r in rows if len(r) > k and int(r[k]) in RUN_UIDS}
        except (OSError, ValueError):
            continue
    return found


def _helper(uid: int) -> None:
    """Start the cleaning helper (this file with --clean) as `uid`, and wait for it."""
    subprocess.run([sys.executable, "-I", "-S", os.path.abspath(__file__), "--clean"], user=uid, group=uid,
                   extra_groups=[], umask=0o077, env={"PATH": "/usr/bin:/bin"}, cwd="/", timeout=60,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _clean(uids, whole: bool = True) -> bool:
    """Kill every process of the runs' users and start the helper as each user in `uids`; with `whole`, as every
    user that still owns something too. Returns whether those users have nothing left (with `whole`, whether
    anything of any of them is left at all; zombies aside: they are being reaped and run nothing). Between the
    inputs of one request `whole` is false: only the input before is cleaned up, and what the compile made,
    which belongs to a user of its own, stays for the next input.
    A helper per user because this process, root without CAP_FOWNER or CAP_SYS_ADMIN, cannot remove another
    user's file from a sticky folder or its IPC objects; what is left of this process's own (a folder whose chown
    did not finish) it removes itself."""
    try:
        _kill_leftovers(RUN_UIDS)
        for uid in sorted(set(uids) | (_owners() if whole else set())):
            _helper(uid)
        if whole:
            for root in WIPED:
                _empty(root)
        _kill_leftovers(RUN_UIDS)   # in case a helper's own children were left (it starts none)
        look = RUN_UIDS if whole else sorted(set(uids))
        left = [pid for pid, zombie in _user_procs(os.getpid(), look) if not zombie]
        files = [root for root in WIPED if os.path.isdir(root) and _owned_in(root, look)]
        ipc = _ipc_ids(look)
    except Exception as e:   # noqa: BLE001 (any failure here means the runner is not clean)
        print(f"cleanup failed: {type(e).__name__}: {e}", flush=True)
        return False
    if left or files or ipc:
        print(f"cleanup left processes {left[:5]}, files in {files}, IPC {ipc[:5]}", flush=True)
    return not (left or files or ipc)


def _chown_tree(path: str, uid: int) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        os.chown(dirpath, uid, uid, follow_symlinks=False)
        for name in dirnames + filenames:
            os.chown(os.path.join(dirpath, name), uid, uid, follow_symlinks=False)


def _run_locked(lang: str, code: str, stdins: list[str], timeout: float) -> dict:
    """Compile once, then run on each input; the response of the last run, or of a failed compile, with every
    run's under "runs". The compile is its user's in its own folder (umask 022: the runs read and execute what it
    made, and cannot change it); each input runs as the next user, in an empty folder of its own (umask 077), and
    what it left is cleaned up before the next input starts."""
    srcname, compile_argv, run_argv, memory, compile_memory = LANGS[lang]
    if lang == "javascript" and ESM.search(code):   # import/export syntax: run it as an ES module
        srcname, run_argv = "main.mjs", run_argv[:-1] + ["{b}/main.mjs"]
    if lang == "java":   # its package line would put the classes where `java Name` does not look
        code = _drop_package(code)
        name, runs = _java_entry(code)
        srcname, compile_argv = f"{name}.java", compile_argv[:-1] + [f"{name}.java"]
        run_argv = run_argv[:-1] + [runs]
    timeout = max(1.0, min(float(timeout or 10.0), HARD_TIMEOUT_CAP))
    cpu_seconds = int(timeout) + 1
    tag = os.urandom(6).hex()
    build = os.path.join(WORK, f"b-{tag}")
    builder = next(NEXT_UID)
    used = [builder]
    try:
        os.mkdir(build, 0o755)
        with open(os.path.join(build, srcname), "w", encoding="utf-8") as f:
            f.write(code)
        if lang == "go" and os.path.isdir(GO_CACHE_SEED):   # a copy of its own: 32 ms, against 4 s to compile them
            shutil.copytree(GO_CACHE_SEED, os.path.join(build, ".gocache"), symlinks=True)
        _chown_tree(build, builder)
        if compile_argv is not None:
            rc, so, _, se, cut, timed, _ = _spawn(compile_argv, build, b"", COMPILE_CAP, COMPILE_CPU, compile_memory,
                                                   tag + "c", builder, 0o022, COMPILE_ENV.get(lang), COMPILE_FILE_CAP)
            fixed = _go_imports(code, se) if not timed and rc != 0 and lang == "go" else None
            if not timed and rc != 0 and (lang in COMPILE_AGAIN or fixed):
                # the same source with other settings (C++17), or the source with the packages it left out (Go),
                # which needs a folder of its own: this one is the first builder's now, and the runner, with no
                # CAP_DAC_OVERRIDE, cannot write in it
                where, who = build, builder
                if fixed:
                    who = next(NEXT_UID)
                    used.append(who)
                    where = os.path.join(WORK, f"b-{tag}-2")
                    os.mkdir(where, 0o755)
                    with open(os.path.join(where, srcname), "w", encoding="utf-8") as f:
                        f.write(fixed)
                    if os.path.isdir(GO_CACHE_SEED):
                        shutil.copytree(GO_CACHE_SEED, os.path.join(where, ".gocache"), symlinks=True)
                    _chown_tree(where, who)
                again = _spawn(COMPILE_AGAIN.get(lang, compile_argv), where, b"", COMPILE_CAP, COMPILE_CPU,
                               compile_memory, tag + "c2", who, 0o022, COMPILE_ENV.get(lang), COMPILE_FILE_CAP)
                if again[0] == 0 and not again[5]:
                    rc, build = 0, where
            if timed or rc != 0:
                return {"ok": False, "stage": "compile", "exit": rc, "timed_out": timed, "output_limited": False,
                        "stdout": so, "stderr": se, "stderr_truncated": cut, "elapsed": None}
        argv = [a.replace("{b}", build) for a in run_argv]
        runs = []
        for k, stdin in enumerate(stdins):
            if k and not _clean(used[-1:], whole=False):   # the input before left nothing behind
                DIRTY.set()
                return {"ok": False, "error": "the runner could not clean up after a run; restart it"}
            uid = next(NEXT_UID)
            used.append(uid)
            cwd = os.path.join(WORK, f"r-{tag}-{k}")
            os.mkdir(cwd, 0o700)
            os.chown(cwd, uid, uid)
            start = time.time()
            rc, so, so_cut, se, se_cut, timed, full = _spawn(argv, cwd, stdin.encode("utf-8"), timeout, cpu_seconds,
                                                             memory, f"{tag}-{k}", uid, 0o077, RUN_ENV.get(lang))
            elapsed = round(time.time() - start, 3)
            cpu_out = rc == -signal.SIGXCPU          # stopped by the CPU-seconds limit: a timeout too
            limited = rc == -signal.SIGXFSZ or full  # stopped for writing too much output
            timed = timed or cpu_out
            runs.append({"ok": rc == 0 and not timed and not limited, "stage": "run", "exit": rc, "timed_out": timed,
                         "output_limited": limited, "stdout": so, "stdout_truncated": so_cut or limited,
                         "stderr": se, "stderr_truncated": se_cut, "elapsed": elapsed})
        return {**runs[-1], "ok": all(r["ok"] for r in runs), "runs": runs}
    finally:
        if not _clean(used):
            DIRTY.set()


def run(lang: str, code: str, stdin: str, timeout, stdins: list | None = None) -> dict:
    if lang not in LANGS:
        return {"ok": False, "error": f"unsupported language: {lang}"}
    many = stdins is not None
    if many and (not isinstance(stdins, list) or not 1 <= len(stdins) <= MAX_STDINS):
        return {"ok": False, "error": f"stdins: a list of 1 to {MAX_STDINS} inputs"}
    if not RUN_LOCK.acquire(timeout=BUSY_WAIT):
        return {"ok": False, "busy": True, "error": "busy"}
    if DIRTY.is_set():
        RUN_LOCK.release()
        return {"ok": False, "error": "the runner could not clean up after a run; restart it"}
    try:
        res = _run_locked(lang, code, [str(x) for x in stdins] if many else [stdin], timeout)
    finally:
        RUN_LOCK.release()
    if not many:
        res.pop("runs", None)
    return res


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):   # noqa: N802
        if self.path == "/health":
            self._send({"ok": not DIRTY.is_set(), "busy": RUN_LOCK.locked()})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):   # noqa: N802
        if self.path != "/run":
            self._send({"error": "not found"}, 404)
            return
        if TOKEN and not hmac.compare_digest(self.headers.get("Authorization") or "", f"Bearer {TOKEN}"):
            self._send({"ok": False, "error": "this runner takes runs from the sidenote server only"}, 403)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            result = run(str(data.get("lang") or ""), str(data.get("code") or ""),
                         str(data.get("stdin") or ""), data.get("timeout"), data.get("stdins"))
            self._send(result)
        except Exception as e:   # never crash the service on one bad run
            self._send({"ok": False, "error": f"runner error: {e.__class__.__name__}"}, 200)

    def log_message(self, *a):   # quiet
        pass

    def address_string(self) -> str:   # a Unix socket's peer has no address
        return "local"


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _health() -> int:
    """The container's health check: 0 when the runner answers ok on its socket (or port)."""
    path = os.environ.get("RUNNER_SOCKET")
    try:
        s = socket.socket(socket.AF_UNIX) if path else socket.create_connection(
            ("127.0.0.1", int(os.environ.get("RUNNER_PORT", "8000"))), timeout=2)
        s.settimeout(2)
        if path:
            s.connect(path)
        s.sendall(b"GET /health HTTP/1.1\r\nHost: runner\r\nConnection: close\r\n\r\n")
        data = b""
        while chunk := s.recv(4096):
            data += chunk
        return 0 if json.loads(data.split(b"\r\n\r\n", 1)[1]).get("ok") else 1
    except (OSError, ValueError, IndexError):
        return 1


# The token a /run must carry over TCP, read once and taken out of the environment so nothing started later inherits it.
TOKEN = os.environ.pop("RUNNER_TOKEN", "")


def _in_its_container() -> bool:
    """Whether this is the runner's own container, whose root filesystem is read-only (compose `read_only`, the Helm
    chart's readOnlyRootFilesystem): the cleanup empties /work, /tmp, /dev/shm and /dev/mqueue, which anywhere else
    hold other programs' files."""
    try:
        return bool(os.statvfs("/").f_flag & os.ST_RDONLY)
    except OSError:
        return False


def _share_socket(path: str) -> None:
    """Open the socket to the server's group, when the server runs as the PC's user instead of root (compose.yaml's
    RUNNER_SOCKET_GID). The group, not the user: this process has no CAP_DAC_OVERRIDE, so its own health check needs the
    socket to stay root's. A run's user has a group of its own and no other, so it stays out, unless the server's group is
    one of those: then the socket stays closed, as a server without code checks is better than runs that can reach it."""
    try:
        gid = int(os.environ.get("RUNNER_SOCKET_GID") or 0)
    except ValueError:
        gid = 0
    if not gid:   # the server is root too: the file being root's is all it needs
        return
    if gid in RUN_UIDS:
        print(f"RUNNER_SOCKET_GID {gid} is the group of a run's user: the socket stays closed to it", flush=True)
        return
    os.chown(path, -1, gid)   # before the mode: the mode must never give the group to root's group for a moment
    os.chmod(path, 0o660)


def main() -> None:
    if sys.argv[1:] == ["--health"]:
        sys.exit(_health())
    if not _in_its_container():   # never empty a machine's own /tmp: the runner starts only where it is sealed in
        sys.exit("sidenote runner: the root filesystem is writable, so this is not the runner's container; it would "
                 "empty /tmp, /work and /dev/shm after every run, and does not start here")
    if sys.argv[1:] == ["--clean"]:   # the helper, as one of the runs' users
        _kill_leftovers()
        _wipe()
        return
    # Not dumpable: nothing the runs start can read this process's memory or trace it.
    try:
        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)   # PR_SET_DUMPABLE, 0
    except (OSError, AttributeError):
        pass
    for d in (WORK, OUT):
        os.makedirs(d, exist_ok=True)
    os.chmod(OUT, 0o700)
    # Started again (a container restart, a failed liveness probe), the runner may find what a run left before: in
    # Kubernetes the scratch folders, /dev/shm and the pod's IPC objects outlive the process. It cleans up as it does
    # after every run, and takes no runs (reporting itself unhealthy) if anything is still left.
    if not _clean([], whole=True):
        DIRTY.set()
        print("leftovers from an earlier run could not be removed: unhealthy until restarted", flush=True)
    path = os.environ.get("RUNNER_SOCKET")
    if path:   # the server's only way in: a socket only this process and the server's group may open
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        old = os.umask(0o077)
        srv = UnixServer(path, Handler)
        os.umask(old)
        os.chmod(path, 0o600)
        _share_socket(path)
        print(f"sidenote runner on {path}", flush=True)
    else:
        port = int(os.environ.get("RUNNER_PORT", "8000"))
        srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        print(f"sidenote runner on :{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
