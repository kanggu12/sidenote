"""The Mac app opened as the Finder opens it, on a Mac with no Sidenote running (the desktop workflow's macOS runner):
LaunchServices starts it, and the environment it gets is the system's, plus what `open --env` adds here: a data folder
and a port of its own, and a browser that writes down each address it is given.

  - the server, the capture program and its menu bar icon come up, and the panel is opened once;
  - on CI only: the agent's CLI is found in a folder that only the login shell's start-up files put on PATH, as an
    installer's line in ~/.zprofile does (the files are put back afterwards);
  - opened again while it runs, the app starts no second copy, and the panel is opened again;
  - a quit sent the way the system sends one (as at log out) ends the app and all it started.

    python tests/mac_app_open.py dist/Sidenote.app
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BUNDLE_ID = "io.github.kanggu12.sidenote"
LOGIN_FILES = (".zprofile", ".bash_profile")   # what zsh and bash read as login shells
# A stand-in for Claude Code's CLI, signed in: before an answer, all the server asks of it is whether it is
STAND_IN_CLAUDE = """#!/bin/sh
if [ "$1" = auth ] && [ "$2" = status ]; then
  printf '{"loggedIn": true, "authMethod": "stand-in"}\\n'
fi
"""
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def wait_for(ready, timeout, every=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if ready():
            return True
        time.sleep(every)
    return bool(ready())


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def health(port):
    """The server's /health, or None."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return json.loads(r.read() or b"{}")
    except (OSError, ValueError):
        return None


def on_login_path(home, folder):
    """`folder` put on PATH by the login shell's start-up files alone. Returns what the files held, to put back."""
    kept = {}
    for name in LOGIN_FILES:
        f = home / name
        kept[f] = f.read_bytes() if f.exists() else None
        with open(f, "a", encoding="utf-8") as out:
            out.write(f'\nexport PATH="{folder}:$PATH"\n')
    return kept


def put_back(kept):
    for f, held in kept.items():
        if held is None:
            f.unlink(missing_ok=True)
        else:
            f.write_bytes(held)


def running(app):
    """The processes started from this bundle's executable: pid and command line."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    mark = f"{app}/Contents/MacOS/"
    return [(int(line.split(None, 1)[0]), line.split(None, 1)[1]) for line in out.splitlines()
            if mark in line and len(line.split(None, 1)) == 2]


def text(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def main(argv):
    app = Path(argv[0]).resolve()
    if sys.platform != "darwin" or not (app / "Contents" / "Info.plist").is_file():
        print("usage, on a Mac: python tests/mac_app_open.py path/to/Sidenote.app")
        return 2
    if running(app):
        print(f"{app} is running already; quit it first")
        return 2
    with tempfile.TemporaryDirectory(prefix="sidenote-open-") as d:
        d = Path(d)
        opened = d / "opened.txt"
        browser = d / "browser.sh"          # Python's webbrowser runs $BROWSER with the address
        browser.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{opened}"\n', encoding="utf-8")
        browser.chmod(0o755)
        data, port = d / "data", free_port()
        logs = data / "logs"
        env = {"SIDENOTE_DATA_DIR": str(data), "SIDENOTE_PORT": str(port), "BROWSER": str(browser)}
        # the app opens the panel's address without its last slash, the menu bar icon with it
        lines = lambda: [line.rstrip("/") for line in text(opened).split()]   # noqa: E731
        url = f"http://127.0.0.1:{port}"
        # On CI only, as it changes the login shell's start-up files: a CLI on no PATH but the login shell's
        kept, on_ci = {}, os.environ.get("GITHUB_ACTIONS") == "true"
        if on_ci:
            folder = d / "login-bin"
            folder.mkdir()
            (folder / "claude").write_text(STAND_IN_CLAUDE, encoding="utf-8")
            (folder / "claude").chmod(0o755)
            kept = on_login_path(Path.home(), folder)
        try:
            print("[opened as the Finder opens it]")
            subprocess.run(["open", *[a for k, v in env.items() for a in ("--env", f"{k}={v}")], str(app)],
                           check=True, timeout=60)
            check("the server comes up", wait_for(lambda: health(port) is not None, 240), text(logs / "app.log"))
            check("...and the capture program, its menu bar icon about to run",
                  wait_for(lambda: "[main] capturing" in text(logs / "capture.log"), 60), text(logs / "capture.log")[-800:])
            check("the panel is opened once", wait_for(lambda: len(lines()) >= 1, 30) and lines() == [url],
                  str(lines()))
            if on_ci:
                signed = (health(port) or {}).get("auth") or {}
                check("the agent's CLI, on the login shell's PATH alone, is found and asked whether it is signed in",
                      signed.get("ok") is True and signed.get("method") == "stand-in", str(signed))
            else:
                print("  skipped off CI: the agent's CLI on the login shell's PATH (it changes ~/.zprofile)")
            time.sleep(3)                    # the icon's loop running, to take what comes next
            first = sorted(pid for pid, _ in running(app))

            print("[opened again while it runs]")
            subprocess.run(["open", str(app)], check=True, timeout=60)
            check("the panel is opened again", wait_for(lambda: len(lines()) >= 2, 30) and lines() == [url, url],
                  f"{lines()}; capture.log: {text(logs / 'capture.log')[-600:]}")
            time.sleep(2)
            check("...and no second copy starts", sorted(pid for pid, _ in running(app)) == first,
                  f"{first} then {running(app)}")

            print("[quit as the system quits it]")
            ready = "speech model ready" in text(logs / "server.log")
            print(f"  the speech model is {'loaded' if ready else 'still downloading or loading'} as the quit comes")
            asked = time.monotonic()
            done = subprocess.run(["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'],
                                  capture_output=True, text=True, timeout=60)
            ended = wait_for(lambda: not running(app), 60)
            took = time.monotonic() - asked
            print(f"  everything it started ended {took:.1f} s after the quit")
            check("the quit is taken", done.returncode == 0, done.stderr)
            check("...and ends the app with everything it started, within 15 s", ended and took < 15,
                  f"left after {took:.0f} s: {running(app)}")
            said = text(logs / "app.log")
            check("...the way Quit in its menu does", "the capture program was quit; stopping" in said
                  and said.rstrip().endswith("stopped"), said[-600:])
            server = text(logs / "server.log")
            check("...with the server's own close-down run", "asked to close down by the app" in server, server[-600:])
        finally:
            put_back(kept)
            for pid, _ in running(app):      # nothing left behind on the runner, whatever failed
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            if FAIL:
                for name in ("app.log", "capture.log", "server-console.log"):
                    print(f"---- {name}\n{text(logs / name)[-2000:]}")
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
