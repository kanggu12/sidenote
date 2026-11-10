"""What client/launch.pyw does when a person types it in a Windows terminal: --setup (the capture packages into Windows
Python and the desktop shortcut) and --remove (the shortcut and its icon taken away again), for a WSL that cannot start
Windows programs.

    .venv/bin/python tests/launch_setup.py [path to launch.pyw]

No Windows: PowerShell and pip are stood in for. In this process the starter's `subprocess` is replaced by a recorder
that answers as PowerShell would; one run of the real file, with --remove, finds a stand-in powershell.exe first on a
PATH of this test's own (never the PATH this was started with, which on WSL holds Windows' own folders).
LOCALAPPDATA and the desktop are temporary folders. Checked: PowerShell's own words reach the person when the shortcut
cannot be made (they were thrown away, and "PowerShell made no file" was all), the start command for a Windows terminal
is printed, an argument error is printed in the terminal it was typed in (not shown in the shortcut's window, which
says to make the shortcut again in WSL), and --remove takes away the shortcut and the icon and nothing else: the
folder only when it is empty, the packages left in place with the command that removes them, nothing at all with
--dry-run, and never a path when LOCALAPPDATA is not set.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
LAUNCH = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "client" / "launch.pyw"
WORK = Path(tempfile.mkdtemp(prefix="sidenote-setup-"))
BIN = WORK / "bin"                           # the only folder on the PATH besides the system's own
BIN.mkdir()
# A PATH of this test's own, before anything is loaded: on WSL the PATH holds Windows' folders, and powershell.exe,
# py.exe and pyw.exe found there would be the real ones
os.environ["PATH"] = f"{BIN}:/usr/bin:/bin"
os.environ.pop("SIDENOTE_LANG", None)
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def load(lang):
    """client/launch.pyw as a module, in a language: it reads SIDENOTE_LANG when it is loaded."""
    os.environ["SIDENOTE_LANG"] = lang
    loader = importlib.machinery.SourceFileLoader(f"launch_setup_{lang}", str(LAUNCH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PowerShell:
    """Stands in for subprocess in the starter: records what it is asked to run and answers as PowerShell would, with
    `stdout` and `stderr` as bytes (or raises `error`). pip, through call(), is recorded and succeeds."""

    def __init__(self, stdout=b"", stderr=b"", error=None):
        self.stdout, self.stderr, self.error = stdout, stderr, error
        self.runs, self.calls = [], []
        self.SubprocessError, self.TimeoutExpired = subprocess.SubprocessError, subprocess.TimeoutExpired
        self.list2cmdline, self.DEVNULL = subprocess.list2cmdline, subprocess.DEVNULL

    def run(self, command, **how):
        self.runs.append((command, how))
        if self.error:
            raise self.error
        out, err = self.stdout, self.stderr
        if how.get("text"):                  # an older starter asked for text: it gets text, as subprocess gives it
            out, err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        return types.SimpleNamespace(returncode=1 if err else 0, stdout=out, stderr=err)

    def call(self, command, **how):
        self.calls.append(command)
        return 0


def said(fn, *args):
    """What fn(*args) printed on stdout and stderr, and what it returned (or the exception it raised, as text). stdout
    is a real text stream over bytes: main() with --dry-run sets its encoding, which a StringIO cannot take."""
    out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = fn(*args)
        except BaseException as exc:         # an older starter without the function, or one that exits
            rc = f"{type(exc).__name__}: {exc}"
    out.flush()
    return rc, out.buffer.getvalue().decode("utf-8"), err.getvalue()


def safe(module, name, *args):
    """module.name(*args), or the error as text: an older starter has no such function, and its checks then fail
    one by one instead of ending the run."""
    try:
        return getattr(module, name)(*args)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def stand_in(name, body="exit 0"):
    """An executable `name` on this test's PATH that runs `body`."""
    path = BIN / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


en, ko = load("en"), load("ko")
args = types.SimpleNamespace(distro="Ubuntu-22.04", repo="/home/you/sidenote", port=8777, wheels=None)
local = WORK / "local"
os.environ["LOCALAPPDATA"] = str(local)

# ---- PowerShell's words when the shortcut cannot be made. The error as PowerShell 5.1 writes it into a pipe: the
# message, where it was in the script, the record's fields, and the errors of the statements after it. In Constrained
# Language Mode (a managed PC) New-Object -ComObject is refused, and every statement that used the shortcut after it
# fails too.
CLM = (b"New-Object : Cannot create type. Only core types are supported in this language mode.\r\n"
       b"At line:1 char:95\r\n"
       b"+ ... ; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($f); $s.T ...\r\n"
       b"+                                        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\r\n"
       b"    + CategoryInfo          : PermissionDenied: (:) [New-Object], PSNotSupportedException\r\n"
       b"    + FullyQualifiedErrorId : CannotCreateComTypeConstrainedLanguage,Microsoft.PowerShell.Commands.NewObjectCommand\r\n"
       b" \r\n"
       b"The property 'TargetPath' cannot be found on this object. Verify that the property exists and can be set.\r\n"
       b"At line:1 char:150\r\n")
fake = PowerShell(stderr=CLM)
en.subprocess = fake
rc, out, _ = said(en.setup, args, False)
check("a shortcut PowerShell cannot make is said in PowerShell's own words, its first error only",
      rc == 1 and "Could not make the desktop shortcut: New-Object : Cannot create type. Only core types are supported in this language mode." in out
      and "TargetPath" not in out and "At line" not in out, f"rc {rc}: {out!r}")
command = fake.runs[0][0] if fake.runs else []
check("...PowerShell is asked with no profile and no prompt, and with its progress (XML in a pipe) off",
      command[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
      and command[4].startswith("$ProgressPreference = 'SilentlyContinue'; "), str(command[:5]))
check("...and the packages went in before it, into this Python, as pip was asked",
      len(fake.calls) == 1 and fake.calls[0][:5] == [sys.executable, "-m", "pip", "install", "--user"], str(fake.calls))
en.subprocess = PowerShell()                  # nothing on stdout and nothing on stderr
rc, out, _ = said(en.setup, args, False)
check("...a PowerShell that says nothing and makes no file is said as such", rc == 1 and out.rstrip().endswith("PowerShell made no file"), out)
en.subprocess = PowerShell(error=FileNotFoundError(2, "No such file or directory", "powershell.exe"))
rc, out, _ = said(en.setup, args, False)
check("...and one that is not there at all", rc == 1 and "Could not make the desktop shortcut: [Errno 2]" in out, out)

text = safe(en, "first_error", (b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">"
                       b"<Obj S=\"progress\" RefId=\"0\"></Obj></Objs>\r\n").decode() + CLM.decode())
check("progress written as XML is no error, and the location line ends the message", text.startswith("New-Object : Cannot create type")
      and "Objs" not in text and "line:1" not in text, text)
ko_where = "Remove-Item : 'C:\\x' 경로는 존재하지 않으므로 찾을 수 없습니다.\r\n위치 줄:1 문자:1\r\n+ Remove-Item C:\\x\r\n"
check("...in a Korean Windows too, where the location line is in Korean",
      safe(en, "first_error", ko_where) == "Remove-Item : 'C:\\x' 경로는 존재하지 않으므로 찾을 수 없습니다.", safe(en, "first_error", ko_where))
wrapped = "Exception calling \"Save\" with \"0\" argument(s): \"Unable to save shortcut\r\n\"C:\\Users\\you\\Desktop\\Sidenote Capture.lnk\".\"\r\nAt line:1 char:300\r\n"
check("...a message PowerShell wrapped over lines is one line again", safe(en, "first_error", wrapped)
      == "Exception calling \"Save\" with \"0\" argument(s): \"Unable to save shortcut \"C:\\Users\\you\\Desktop\\Sidenote Capture.lnk\".\"",
      safe(en, "first_error", wrapped))
check("...and bytes that are not UTF-8 are read without an error", "?" in safe(en, "console_text", b"\xc0\xfa\xc0\xe5 ok").replace("\ufffd", "?")
      and safe(en, "console_text", "바탕 화면".encode("utf-8")) == "바탕 화면")

# ---- the start command for a Windows terminal, beside the shortcut
pyw = stand_in("pyw.exe")
stand_in("py.exe")
shortcut_path = "C:\\Users\\you\\Desktop\\Sidenote Capture.lnk"
fake = PowerShell(stdout=shortcut_path.encode() + b"\r\n")
en.subprocess = fake
rc, out, _ = said(en.setup, args, False)
typed = f'pyw -3 "{LAUNCH}" --distro Ubuntu-22.04 --repo "/home/you/sidenote" --port 8777'
check("a shortcut made is followed by the command that starts the capture from a Windows terminal",
      rc == 0 and "Desktop shortcut made: Sidenote Capture.lnk" in out
      and "To start the capture from a Windows terminal, without the shortcut:\n  " + typed in out, out)
script = fake.runs[0][0][4] if fake.runs else ""
check("...the shortcut runs pyw.exe by its full path, as Explorer starts it with its own PATH",
      f"$s.TargetPath = '{pyw}'" in script and f"$s.Arguments = '-3 \"{LAUNCH}\"" in script, script[:300])
rc, out, _ = said(en.setup, args, True)
check("...and --dry-run prints it with the rest, running nothing",
      rc == 0 and f"[dry-run] terminal: {typed}" in out and len(fake.runs) == 1, out)
pyw.unlink()
rc, out, _ = said(en.setup, args, True)
windowless = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
check("...without the Python launcher, by this Python's windowless interpreter, in quotes",
      f'[dry-run] terminal: "{windowless}" "{LAUNCH}" --distro' in out, out)
ko.subprocess = PowerShell(stdout=shortcut_path.encode())
rc, out, _ = said(ko.setup, args, False)
check("...in Korean too", rc == 0 and "바로가기 없이 Windows 터미널에서 캡처를 시작하는 명령:" in out, out)

# ---- argument errors, typed in a terminal
for lang, module in (("en", en), ("ko", ko)):
    rc, out, err = said(module.main, ["--setup", "--distro", "Ubuntu-22.04"])
    words = ("Could not read the arguments: the following arguments are required: --repo", "Usage:") if lang == "en" \
        else ("인자를 읽지 못했습니다: the following arguments are required: --repo", "사용법:")
    check(f"--setup with an argument missing prints what is wrong and what to type, in the terminal ({lang})",
          rc == 2 and all(w in err for w in words) and "py -3 launch.pyw --setup --distro NAME --repo PATH" in err
          and "py -3 launch.pyw --remove" in err and "[dry-run] box" not in out and "shortcut" not in err.lower().split("usage")[0],
          f"rc {rc}: out {out!r} err {err!r}")
rc, out, err = said(en.main, ["--setup", "--distro", "Ubuntu-22.04", "--repo", "/home/you/sidenote", "--port", "eighty"])
check("...a value that is not a number too", rc == 2 and "argument --port: invalid int value: 'eighty'" in err and not out, f"rc {rc}: {out!r} {err!r}")
rc, out, err = said(en.main, ["--remove", "--colour"])
check("...and --remove with an unknown argument", rc == 2 and "unrecognized arguments: --colour" in err and "Usage:" in err, f"rc {rc}: {err!r}")
rc, out, err = said(en.main, ["--distro", "Ubuntu-22.04", "--dry-run"])
check("the shortcut's own arguments, which no one typed, still go to its window",
      rc == 2 and "[dry-run] box: warning" in out and "the following arguments are required: --repo" in out and not err, f"rc {rc}: {out!r} {err!r}")

# ---- --remove
folder, icon = local / "Sidenote", local / "Sidenote" / "sidenote.ico"


def setup_made():
    """The icon --setup copied, in the folder it copied it to."""
    folder.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(b"\x00\x00\x01\x00")


setup_made()
fake = PowerShell()
en.subprocess = fake
rc, out, _ = said(lambda: en.remove(True))
check("--remove --dry-run says what it would remove and removes nothing",
      rc == 0 and "[dry-run] remove shortcut: Sidenote Capture.lnk" in out and "[dry-run] remove shortcut: Sidenote 캡처.lnk" in out
      and f"[dry-run] remove icon: {icon}" in out and f"[dry-run] remove folder if empty: {folder}" in out
      and icon.exists() and not fake.runs, f"rc {rc}, icon there {icon.exists()}, PowerShell runs {len(fake.runs)}: {out!r}")
here = LAUNCH.parent
check("...and that the capture packages stay, with the command that takes them out",
      "The capture packages that --setup installed into this Python stay. This removes them:\n"
      f'  py -3 -m pip uninstall -y -r "{here / "requirements.txt"}"' in out, out)

fake = PowerShell(stdout=b"removed 0\r\nremoved 1\r\n")
en.subprocess = fake
rc, out, _ = said(lambda: en.remove(False))
script = fake.runs[0][0][4] if fake.runs else ""
check("--remove takes away the shortcut under each name it has had, and the icon, and the folder left empty",
      rc == 0 and "Shortcut removed: Sidenote Capture.lnk" in out and "Shortcut removed: Sidenote 캡처.lnk" in out
      and f"Icon removed: {icon}" in out and f"Folder removed: {folder}" in out and not folder.exists() and local.exists(),
      f"rc {rc}: {out!r}")
check("...on the desktop Windows names now, each name by itself, and nothing but those",
      "[Environment]::GetFolderPath('Desktop')" in script and "'Sidenote Capture.lnk', 'Sidenote 캡처.lnk'" in script
      and "Remove-Item -LiteralPath $f -Force" in script and "-Recurse" not in script and "*" not in script, script)

setup_made()
kept = folder / "logs" / "history.sqlite"    # the desktop app keeps its own files in the same folder
kept.parent.mkdir()
kept.write_bytes(b"SQLite format 3\x00")
en.subprocess = PowerShell(stdout=b"removed 0\r\n")
rc, out, _ = said(lambda: en.remove(False))
check("...a folder with the desktop app's files in it stays, and they with it, said so",
      rc == 0 and not icon.exists() and kept.exists() and f"Folder kept, other files are in it: {folder}" in out, f"rc {rc}: {out!r}")

en.subprocess = PowerShell(stdout=b"left 0\r\n", stderr=b"Remove-Item : Access to the path is denied.\r\nAt line:1 char:200\r\n")
rc, out, _ = said(lambda: en.remove(False))
check("a shortcut still there after the removal is said, with PowerShell's words, and ends in failure",
      rc == 1 and "Shortcut still there: Sidenote Capture.lnk" in out and "Could not remove the shortcut: Remove-Item : Access to the path is denied." in out,
      f"rc {rc}: {out!r}")
en.subprocess = PowerShell(error=FileNotFoundError(2, "No such file or directory", "powershell.exe"))
setup_made()
rc, out, _ = said(lambda: en.remove(False))
check("...and a PowerShell that does not run, while the icon still goes",
      rc == 1 and "Could not remove the shortcut: [Errno 2]" in out and not icon.exists(), f"rc {rc}: {out!r}")
en.subprocess = PowerShell()
rc, out, _ = said(lambda: en.remove(False))
check("nothing on the desktop to remove is said, and is no failure", rc == 0 and "No shortcut on the desktop to remove." in out, f"rc {rc}: {out!r}")

# Without LOCALAPPDATA no path is made up: a Sidenote\sidenote.ico under the folder this was started from is not touched
elsewhere = WORK / "cwd"
(elsewhere / "Sidenote").mkdir(parents=True)
(elsewhere / "Sidenote" / "sidenote.ico").write_bytes(b"\x00")
os.environ["LOCALAPPDATA"] = ""
before = os.getcwd()
os.chdir(elsewhere)
try:
    en.subprocess = PowerShell(stdout=b"removed 0\r\n")
    rc, out, _ = said(lambda: en.remove(False))
finally:
    os.chdir(before)
    os.environ["LOCALAPPDATA"] = str(local)
check("with LOCALAPPDATA not set no icon is looked for under the current folder",
      rc == 0 and (elsewhere / "Sidenote" / "sidenote.ico").exists() and "Icon" not in out and "Folder" not in out, f"rc {rc}: {out!r}")
(BIN / "py.exe").unlink()
rc, out, _ = said(lambda: en.remove(True))
check("...and without the Python launcher the pip line names this Python",
      f'  "{sys.executable}" -m pip uninstall -y -r "{here / "requirements.txt"}"' in out, out)
rc, out, _ = said(lambda: ko.remove(True))
check("--remove speaks Korean too", "--setup이 이 Python에 설치한 캡처 패키지는 남아 있습니다. 이 명령으로 지웁니다:" in out, out)
kept.unlink()                                # the desktop app's files gone again, for the run below
kept.parent.rmdir()

# ---- the real file, run as a person runs it, with PowerShell stood in for
calls = WORK / "powershell-calls"
stand_in("powershell.exe", f'for a in "$@"; do printf "%s\\n" "$a"; done >> "{calls}"\nprintf "removed 0\\r\\n"')
setup_made()
env = {"PATH": os.environ["PATH"], "LOCALAPPDATA": str(local), "SIDENOTE_LANG": "en", "HOME": str(WORK),
       "SystemRoot": str(WORK / "no-windows"), "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
dry = subprocess.run([sys.executable, str(LAUNCH), "--remove", "--dry-run"], capture_output=True, text=True, timeout=60, env=env)
check("py -3 launch.pyw --remove --dry-run: the lines, nothing run, nothing removed",
      dry.returncode == 0 and "[dry-run] remove shortcut: Sidenote Capture.lnk" in dry.stdout and not calls.exists() and icon.exists(),
      f"rc {dry.returncode}: {dry.stdout!r} {dry.stderr!r}")
done = subprocess.run([sys.executable, str(LAUNCH), "--remove"], capture_output=True, text=True, timeout=60, env=env)
asked = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
check("py -3 launch.pyw --remove: PowerShell asked once, the shortcut and the icon gone, status 0",
      done.returncode == 0 and len(asked) == 4 and asked[:3] == ["-NoProfile", "-NonInteractive", "-Command"]
      and asked[3].startswith("$ProgressPreference = 'SilentlyContinue'; $d = [Environment]::GetFolderPath('Desktop')")
      and "Shortcut removed: Sidenote Capture.lnk" in done.stdout and not icon.exists() and not folder.exists(),
      f"rc {done.returncode}: {done.stdout!r} {done.stderr!r} {asked[:3]}")

print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
