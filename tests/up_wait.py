"""./sidenote up waits while the server is in use (in_use, wait_idle): each case is a /health answer.

    .venv/bin/python tests/up_wait.py

Runs the script's own in_use function (cut out of ./sidenote) with `health` answering from a file.
"""
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
src = (ROOT / "sidenote").read_text(encoding="utf-8")
fn = re.search(r"^in_use\(\) \{.*?^\}\n", src, re.S | re.M)
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def in_use(health) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(json.dumps(health) if health is not None else "")
    script = (f"health() {{ [ -s {f.name} ] && cat {f.name}; }}\n" if health is not None
              else "health() { return 7; }\n") + fn.group(0) + "in_use\n"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()


now = time.time()
base = {"paused": False, "capture": {"clients": 1, "now": now, "last_frame": now - 3600},
        "activity": {"busy": False, "last_answer": None}}
check("the function is there", fn is not None)
check("nothing running, no answer, screen still for an hour: idle", in_use(base) == "")
check("an analysis running: in use", in_use({**base, "activity": {"busy": True, "last_answer": None}}) == "yes")
check("an answer 3 minutes ago: in use", in_use({**base, "activity": {"busy": False, "last_answer": now - 180}}) == "yes")
check("an answer 20 minutes ago: idle", in_use({**base, "activity": {"busy": False, "last_answer": now - 1200}}) == "")
check("the screen changing a minute ago, watched: in use",
      in_use({**base, "capture": {**base["capture"], "last_frame": now - 60}}) == "yes")
check("the screen changing but paused: idle",
      in_use({**base, "paused": True, "capture": {**base["capture"], "last_frame": now - 60}}) == "")
check("the screen changing with no capture program: idle",
      in_use({**base, "capture": {**base["capture"], "clients": 0, "last_frame": now - 60}}) == "")
check("paused but a follow-up running: in use", in_use({**base, "paused": True, "activity": {"busy": True}}) == "yes")
check("an older server with no activity field, watched and changing: in use",
      in_use({"paused": False, "capture": {"clients": 1, "now": now, "last_frame": now - 30}}) == "yes")
check("no answer from the server: idle (nothing to wait for)", in_use(None) == "")
print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
