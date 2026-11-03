"""./sidenote up asks what CI said of the commit before it deploys (ci_state, ci_gate): each case a repository state and an answer from `gh`.

    .venv/bin/python tests/ci_gate.py

Runs the script's own functions (cut out of ./sidenote) in a throwaway git repository, with a stand-in gh on the PATH that answers from a file, one line per asking.
"""
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
src = (ROOT / "sidenote").read_text(encoding="utf-8")
state = re.search(r"^ci_state\(\) \{.*?^\}\n", src, re.S | re.M)
gate = re.search(r"^ci_gate\(\) \{.*?^\}\n", src, re.S | re.M)
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


check("the functions are there", state is not None and gate is not None)
work = Path(tempfile.mkdtemp(prefix="sidenote-ci-gate-"))
repo, bin_dir = work / "repo", work / "bin"
repo.mkdir()
bin_dir.mkdir()
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
subprocess.run("git init -q . && echo a > f && git add f && git commit -qm a", shell=True, cwd=repo, env=ENV, check=True)
answers = work / "answers"
fake = bin_dir / "gh"
fake.write_text(f'#!/bin/bash\nf={answers}\nhead -1 "$f"\nsed -i 1d "$f" 2>/dev/null\nexit 0\n')
fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
# The launcher's output helpers, and L, its message in one of two languages (English here)
PRELUDE = ('set -euo pipefail\nok() { echo "OK $*"; }\nwarn() { echo "WARN $*"; }\ndie() { echo "DIE $*"; exit 1; }\nD=; N=\n'
           "L() { printf '%s' \"$1\"; }\n")


def run(lines, path=None, **env):
    answers.write_text("".join(f"{a}\n" for a in lines))
    script = PRELUDE + state.group(0) + gate.group(0) + "ci_gate\necho PASSED\n"
    e = {**ENV, "PATH": f"{bin_dir}:{os.environ['PATH']}" if path is None else path, "CI_WAIT_EVERY": "0", "CI_WAIT_LIMIT": "3", **env}
    r = subprocess.run(["bash", "-c", script], cwd=repo, env=e, capture_output=True, text=True, timeout=30)
    return r.stdout + r.stderr, r.returncode


out, rc = run(["success"])
check("a commit CI passed goes up, and says so", rc == 0 and "OK" in out and "PASSED" in out, out)
out, rc = run(["failure"])
check("a commit CI failed does not", rc == 1 and "DIE" in out and "PASSED" not in out, out)
out, rc = run(["failure"], UP_NO_CI="1")
check("...unless asked", rc == 0 and "PASSED" in out, out)
for bad in ("cancelled", "timed_out", "startup_failure"):
    out, rc = run([bad])
    check(f"nor does one {bad}", rc == 1, out)
out, rc = run(["running"])
check("one still being checked goes up, and says so", rc == 0 and "WARN" in out and "PASSED" in out, out)
out, rc = run(["running", "running", "success"], UP_WHEN_GREEN="1")
check("--when-green waits for the answer", rc == 0 and "OK" in out and "PASSED" in out, out)
out, rc = run(["running", "failure"], UP_WHEN_GREEN="1")
check("...and a failure then keeps it down", rc == 1 and "DIE" in out, out)
out, rc = run(["running"] * 30, UP_WHEN_GREEN="1")
check("...and does not wait for ever", rc == 1 and "DIE" in out, out)
out, rc = run([""])
check("no run for this commit (not pushed): it goes up", rc == 0 and "PASSED" in out, out)
out, rc = run([""], UP_WHEN_GREEN="1", CI_WAIT_LIMIT="0")
check("...but --when-green will not, not knowing", rc == 1 and "DIE" in out, out)
nogh = work / "nogh"
nogh.mkdir()
for tool in ("git", "grep", "head", "sed", "bash"):
    found = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
    (nogh / tool).symlink_to(found)
out, rc = run([], path=str(nogh))
check("a PC with no gh is no obstacle, and it says it does not know", rc == 0 and "PASSED" in out and "DIE" not in out and "WARN" in out, out)
(repo / "f").write_text("changed\n")
out, rc = run(["success"])
check("uncommitted work is what is going up, not the commit: it goes, and says CI has not seen it", rc == 0 and "WARN" in out and "PASSED" in out, out)
out, rc = run(["failure"])
check("changes on top of a commit CI failed do not go up by themselves", rc == 1 and "DIE" in out and "PASSED" not in out, out)
out, rc = run(["failure"], UP_NO_CI="1")
check("...unless asked", rc == 0 and "PASSED" in out, out)
(repo / "f").write_text("a\n")
print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)
