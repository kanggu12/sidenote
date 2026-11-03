"""What the suites share: the repository's root, the folder they write to, the server's interpreter, the settings
message the panel suites feed the page, and where the measurement data is.

The measurement data stays out of the repository, for its size and for what it holds: screenshots of other people's
sites, the answers the models wrote for them, and a photo of a face. A check that reads it finds it where the variables
below say. When a file of it is not there, the group of checks that needs it is skipped rather than failed, and the
suite prints one line saying how many groups it skipped and why (skip_line). Every other check runs as it does with
the data present.

  SIDENOTE_BENCH     the local model bench: real screenshots, and the answers the models wrote (out-depth/)
                     default: <repo>/scratch/local-llm-bench
  SIDENOTE_CORPUS    the public problem corpus, whose drawn figures the face cover must leave alone
                     default: <repo>/scratch/corpus-data
  SIDENOTE_FACES     the photos of faces the face cover is checked with
                     default: <repo>/scratch/smoke/fixtures/faces
  SIDENOTE_TEST_OUT  where the suites write screenshots, copies of the panel and the settings message
                     default: a new temporary folder (tests/run.sh sets one for the whole run)
  PY                 an interpreter with the server's packages, for what a panel suite asks of the server's own code
                     default: <repo>/.venv/bin/python if there is one, else the interpreter running the suite

Only the standard library is used here: the panel suites run in an interpreter that may hold Playwright alone.
"""
from __future__ import annotations

import contextlib   # group(): a block of checks that stops at missing data without stopping the suite
import json         # the settings message is JSON, as the server sends it, and so is docker/vendor.json
import os           # the variables above
import shutil       # a fresh copy of the panel to serve
import subprocess   # the settings message is written by the server's own code, in the server's interpreter
import sys          # the interpreter running the suite, and the exit when the panel's libraries are missing
import tempfile     # the output folder when SIDENOTE_TEST_OUT names none
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # the repository: this file is in tests/, one level down
# The panel speaks the browser's language (panel/i18n.js), and the panel suites read its Korean words: every page they open asks
# for Korean. tests/panel_lang.py opens the English one.
LOCALE = "ko-KR"


def _folder(var: str, default: Path) -> Path:
    """The folder a variable names, or its default when the variable is unset or empty."""
    return Path(os.environ.get(var) or default)


BENCH = _folder("SIDENOTE_BENCH", ROOT / "scratch" / "local-llm-bench")
CORPUS = _folder("SIDENOTE_CORPUS", ROOT / "scratch" / "corpus-data")
FACES = _folder("SIDENOTE_FACES", ROOT / "scratch" / "smoke" / "fixtures" / "faces")

_out: Path | None = None    # the output folder, made on first use so a suite that writes nothing leaves nothing


def out(*parts: str) -> Path:
    """A path in the output folder (SIDENOTE_TEST_OUT, else a new temporary folder for this suite)."""
    global _out
    if _out is None:
        _out = Path(os.environ.get("SIDENOTE_TEST_OUT") or tempfile.mkdtemp(prefix="sidenote-tests-"))
        _out.mkdir(parents=True, exist_ok=True)     # a folder named by the variable may not exist yet
    return _out.joinpath(*parts)


# ---------- the measurement data ----------

class Missing(Exception):
    """A file of the measurement data is not there: the group of checks that needs it is skipped, not failed."""

    def __init__(self, var: str, base: Path, rel: str):
        super().__init__(f"{var} has no {rel}")
        self.var, self.base, self.rel = var, base, rel

    def why(self) -> str:
        """What is missing, said the short way: the whole folder when it is not there, else the one file."""
        if not self.base.is_dir():
            return f"{self.var}={self.base} is not there"
        return f"{self.var}={self.base} has no {self.rel}"


def _data(var: str, base: Path, rel: str) -> Path:
    """`base / rel` when it exists, else Missing (which group() and the suites' group runners turn into a skip)."""
    path = base / rel
    if not path.exists():
        raise Missing(var, base, rel)
    return path


def bench(rel: str) -> Path:
    """A file of the local model bench (SIDENOTE_BENCH), by its path inside it."""
    return _data("SIDENOTE_BENCH", BENCH, rel)


def corpus(rel: str) -> Path:
    """A file of the public problem corpus (SIDENOTE_CORPUS), by its path inside it."""
    return _data("SIDENOTE_CORPUS", CORPUS, rel)


def faces(rel: str) -> Path:
    """A photo of a face (SIDENOTE_FACES), by its name."""
    return _data("SIDENOTE_FACES", FACES, rel)


SKIPPED: list = []   # (the group of checks, the Missing that stopped it), in the order they were skipped


def skip(name: str, missing: Missing) -> None:
    """Note a group of checks as skipped for want of measurement data."""
    SKIPPED.append((name, missing))


@contextlib.contextmanager
def group(name: str):
    """A block of checks that needs measurement data: when a file of it is missing, the rest of the block is skipped
    and noted, and the suite goes on after the block. The checks before the file was asked for have run as usual."""
    try:
        yield
    except Missing as missing:
        skip(name, missing)


def skip_line() -> None:
    """The one line about what was skipped, printed before the tally: how many groups, why, and which ones. Nothing
    is printed when nothing was skipped."""
    if not SKIPPED:
        return
    reasons = []                                   # each reason once, however many groups it stopped
    for _, missing in SKIPPED:
        if missing.why() not in reasons:
            reasons.append(missing.why())
    n = len(SKIPPED)
    names = ", ".join(name for name, _ in SKIPPED)
    print(f"skipped {n} group{'' if n == 1 else 's'} of checks that read measurement data not found here "
          f"({'; '.join(reasons)}): {names}")


# ---------- what the panel suites need ----------

def server_python() -> str:
    """The interpreter that has the server's packages: PY when it is set (tests/run.sh sets it), else the repository's
    .venv when there is one, else the interpreter running this suite (CI's one interpreter has everything)."""
    venv = ROOT / ".venv" / "bin" / "python"
    return os.environ.get("PY") or (str(venv) if venv.exists() else sys.executable)


# Written in a process of its own with every SIDENOTE_ variable of this environment left out and only these set,
# so neither the PC's own settings nor a settings file in its log folder changes what the panel is shown: the meta and
# the default values of a server that uses Claude Code (byte for byte the fixture the panel suites were written
# against, which was made the same way). In Korean, as the pages the suites open are (LOCALE).
SETTINGS_ENV = {"SIDENOTE_ANALYZER": "mock", "SIDENOTE_AGENT": "claude-code", "SIDENOTE_LANG": "ko"}
SETTINGS_CODE = ("import json, sys\n"
                 "from server.settings import SETTINGS\n"
                 "msg = {'type': 'settings', 'meta': SETTINGS.meta(), 'values': SETTINGS.snapshot()}\n"
                 "with open(sys.argv[1], 'w', encoding='utf-8') as f:\n"
                 "    f.write(json.dumps(msg, ensure_ascii=False))\n")


def settings_message() -> dict:
    """The settings message server/settings.py makes, as a server sends it to a panel that connects. Written once into
    the output folder, so the suites of one run read the same file; each call gives a fresh copy to change."""
    path = out("settings_msg.json")
    if not path.exists():
        env = {k: v for k, v in os.environ.items() if not k.startswith("SIDENOTE_")}
        env.update(SETTINGS_ENV)
        if os.environ.get("SIDENOTE_LANG"):    # the words in the run's language (tests/run.sh sets Korean)
            env["SIDENOTE_LANG"] = os.environ["SIDENOTE_LANG"]
        made = subprocess.run([server_python(), "-c", SETTINGS_CODE, str(path)], cwd=ROOT, env=env,
                              capture_output=True, text=True)
        if made.returncode != 0:                   # an interpreter without the server's code or packages
            print(f"  the settings message could not be written with {server_python()} (set PY to the server's "
                  f"interpreter):\n{made.stderr[-800:]}")
            sys.exit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def need_vendor(panel: Path) -> None:
    """The panel's libraries and fonts are fetched into panel/vendor/ when the image is built (docker/vendor.json) and
    are not in git: without them the page draws no answer, so a missing one is said once instead of failing every
    check that follows. Another copy of the panel (PANEL_DIR) is only asked to have the folder, since an older one may
    not use every library the current list names."""
    listed = json.loads((ROOT / "docker" / "vendor.json").read_text(encoding="utf-8"))
    if panel.resolve() != (ROOT / "panel").resolve():
        listed = listed[:1] if not (panel / "vendor").is_dir() else []
    missing = [e["path"] for e in listed if not (panel / "vendor" / e["path"]).exists()]
    if missing:
        more = f" and {len(missing) - 1} more" if len(missing) > 1 else ""
        print(f"  {panel / 'vendor'} has no {missing[0]}{more}: python3 docker/fetch_vendor.py docker/vendor.json "
              f"panel/vendor")
        sys.exit(2)


def panel_copy(dest: Path) -> Path:
    """A fresh copy of panel/ at `dest`, with the /health the page asks for, to serve over HTTP: what renders is the
    working tree as it is now, not what the server's image was built from. (The suites did this with rsync, which a
    CI image may not have.)"""
    shutil.rmtree(dest, ignore_errors=True)        # nothing left over from an earlier copy
    shutil.copytree(ROOT / "panel", dest)
    (dest / "health").write_text('{"ok":true}')
    return dest
