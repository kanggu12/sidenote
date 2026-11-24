"""The capture program alone, as its own executable: Sidenote-Capture.exe on Windows, Sidenote-Capture.app on macOS and
Sidenote-Capture on Linux, built by desktop/build.py with its own Python. It is for a PC whose screen and sound go to a
Sidenote server that runs elsewhere (Docker, Kubernetes, another PC): no Python to install there. Its arguments are the
capture program's own (client/capture.py --help), --server first among them.

    Sidenote-Capture --server ws://127.0.0.1:8777/ingest

Two more, for the program and its build: `-c CODE ARGS`, which the capture program runs with sys.executable to show its
tray menu on Windows (an executable has no interpreter of its own to start), and `--check`, which the build runs to fail
when something the program needs was left out.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import runpy
import sys
from pathlib import Path

# Where the bundled files are: PyInstaller's folder in the build, the repository from a checkout
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
# The capture program, carried as a file and run as itself: its own `if __name__ == "__main__"` starts it
SCRIPT = ROOT / "client" / "capture.py"
# What it imports to grab the screen and the sound, show its tray icon and reach the server: checked by --check, with the
# modules each package picks for this system (desktop/build.py names the same for the build). The tray icon's and the
# sound's packages are only looked up off Windows, and not their modules for the system: importing them there connects
# to the X display and the sound server, which a build machine lacks, and looking up a module imports its package first
# (as the app's own --check, desktop/app.py)
PACKAGES = ["mss", "websocket", "numpy", "PIL.Image"]
LOOKED_UP = ["soundcard", "pystray"]
if sys.platform == "win32":
    PACKAGES += ["mss.windows", "soundcard", "soundcard.mediafoundation", "pystray", "pystray._win32", "tkinter"]
    LOOKED_UP = []
elif sys.platform == "darwin":
    PACKAGES += ["mss.darwin", "AppKit", "Quartz"]
else:
    PACKAGES += ["mss.linux"]
# The file of C declarations the speaker sound's library reads for this system as it is imported, beside the package
SOUND_HEADER = {"win32": "mediafoundation.py.h", "darwin": "coreaudio.py.h"}.get(sys.platform, "pulseaudio.py.h")


def menu_imports(source: str) -> str:
    """The import lines of the tray menu's program (TRAY_MENU in client/capture.py, `source`), which the capture program
    runs through the -c door below on Windows: --check runs them, as a right click would. Read as code nowhere else, two
    of its modules were left out of both builds, and the menu never opened from them."""
    import ast
    menus = [node.value.value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TRAY_MENU" for t in node.targets)
             and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    return "\n".join(ast.unparse(node) for menu in menus for node in ast.walk(ast.parse(menu))
                     if isinstance(node, (ast.Import, ast.ImportFrom)))


def python_c(code: str, argv: list[str]) -> int:
    """`python -c CODE ARGS`, as the capture program asks sys.executable for its tray menu's script on Windows."""
    sys.argv = ["-c", *argv]                                   # what that script reads as its arguments
    exec(compile(code, "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
    return 0


def check() -> int:
    """Import what the program needs, then run it with --help, which reads every import at its top and its options and
    ends it: written to SIDENOTE_CHECK_LOG (a windowed build has no console to print to). 0 when all of it worked."""
    log = os.environ.get("SIDENOTE_CHECK_LOG")
    out = open(log, "w", encoding="utf-8") if log else sys.stdout   # the build reads the file, a terminal the lines
    problems = []
    for name in PACKAGES:
        try:
            importlib.import_module(name)
        except Exception as exc:                                  # any failure is a module the build left out or broke
            problems.append(f"{name}: {type(exc).__name__}: {exc}")
    for name in LOOKED_UP:
        try:
            if importlib.util.find_spec(name) is None:
                problems.append(f"{name}: not in the build")
        except Exception as exc:                                  # a parent package that failed to import
            problems.append(f"{name}: {type(exc).__name__}: {exc}")
    # found is not enough for the sound's library: without its declarations it fails at the first sound (desktop/build.py,
    # SOUND), as the Linux app's did
    spec = importlib.util.find_spec("soundcard")
    if spec is None or not spec.origin or not (Path(spec.origin).parent / SOUND_HEADER).is_file():
        problems.append(f"soundcard: {SOUND_HEADER} is not beside it")
    if sys.platform == "win32":
        # the tray menu's program, on Windows the -c door's: its imports run here as a right click runs them
        try:
            exec(compile(menu_imports(SCRIPT.read_text(encoding="utf-8")), "<the tray menu's imports>", "exec"), {})
        except Exception as exc:
            problems.append(f"the tray menu: {type(exc).__name__}: {exc}")
    sys.stdout = sys.stderr = out                                 # the program's help goes to the same place
    try:
        run(["--help"])
    except SystemExit as exc:                                     # argparse ends --help with 0
        if exc.code not in (0, None):
            problems.append(f"capture.py --help ended with {exc.code}")
    except Exception as exc:                                      # an import at its top that is missing
        problems.append(f"capture.py: {type(exc).__name__}: {exc}")
    print("\n".join(problems) if problems else
          f"ok: {len(PACKAGES)} modules imported, {len(LOOKED_UP)} found, {SOUND_HEADER}, and the capture program", file=out)
    out.flush()
    return 1 if problems else 0


def run(argv: list[str]) -> int:
    """The capture program with these arguments, as `python capture.py ARGS` would run it."""
    sys.argv = [str(SCRIPT), *argv]                               # its argparse reads them, and a restart repeats them
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # A windowed build (Windows, macOS) starts with no console: printing would fail where a terminal is not attached
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if argv[:1] == ["-c"] and len(argv) > 1:                      # the tray menu's script (client/capture.py, Windows)
        return python_c(argv[1], argv[2:])
    if argv[:1] == ["--check"]:                                   # the build's own check, before the zip is made
        return check()
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
