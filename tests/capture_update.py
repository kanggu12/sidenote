"""A deploy brings the capture program onto its new code: the program says which code it runs (code_mark, in its
hello), ./sidenote up asks for a restart when it deployed another (capture_follow), and the program restarts at a quiet
moment (Updater), or at once when asked by ./sidenote capture-restart.

    .venv/bin/python tests/capture_update.py

No Windows: a copy of a file stands for capture.py, the server's /health is a small HTTP server, the clock is passed in.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import types
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT / "client"))
os.environ["SIDENOTE_LANG"] = "ko"           # the program's words as they were: one check reads them in Korean
import capture  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


d = tempfile.mkdtemp()
src = Path(d, "capture.py")
src.write_text("x = 1\n", encoding="utf-8")
check("the code's mark is its file's sha256, 12 digits",
      capture.code_mark(str(src)) == hashlib.sha256(src.read_bytes()).hexdigest()[:12] and capture.code_mark("/nope") == "")

# the server's word
s = capture.Sender.__new__(capture.Sender)
s.wants = {"screen": True, "audio": True, "stitch": False, "monitor": 1}
s.told = threading.Event()
s.quit_asked = s.restart_asked = s.restart_pending = s.taken_over = False   # what _on_message reads of the real Sender
s._on_message(json.dumps({"type": "restart", "quiet": True}))
check("a deploy's restart waits for a quiet moment", s.restart_pending and not s.quit_asked and not s.restart_asked)
s._on_message(json.dumps({"type": "restart"}))
check("capture-restart restarts at once (the loop ends with a restart)", s.quit_asked and s.restart_asked)

# --no-auto-update (the desktop app starts it so): no Updater runs to take a deploy's restart, and the program said it would
# restart at a quiet moment all the same, and never did
check("a program takes a deploy's restart unless told otherwise", getattr(capture.Sender("ws://127.0.0.1:1/ingest"), "auto_update", None)
      is True)
s = capture.Sender.__new__(capture.Sender)
s.wants = {"screen": True, "audio": True, "stitch": False, "monitor": 1}
s.told = threading.Event()
s.quit_asked = s.restart_asked = s.restart_pending = s.taken_over = False
s.auto_update = False                        # what main() sets for --no-auto-update and --once
said = io.StringIO()
with redirect_stdout(said):
    s._on_message(json.dumps({"type": "restart", "quiet": True}))
check("under --no-auto-update a restart at a quiet moment is not waited for, and said as asked for, not as a deploy",
      not s.restart_pending and not s.quit_asked and not s.restart_asked
      and capture.t("A restart at a quiet moment was asked for: not taken by this program (--no-auto-update)") in said.getvalue()
      and "New code was deployed" not in said.getvalue(), said.getvalue())
with redirect_stdout(io.StringIO()):
    s._on_message(json.dumps({"type": "restart"}))
check("...while a restart asked for at once (capture-restart, the tray's, the panel's) still restarts it", s.quit_asked and s.restart_asked)

# the quiet moment
quiet = {"value": True}
real_quiet = capture.server_quiet
capture.server_quiet = lambda url, now: quiet["value"]
sender = types.SimpleNamespace(last_frame_ts=0.0, restart_pending=False)
u = capture.Updater(str(src), "ws://127.0.0.1:8777/ingest", quiet=20, every=5)
check("nothing asked: no restart", not u.due(sender, 100.0))
sender.restart_pending = True
sender.last_frame_ts = 95.0
moving = u.due(sender, 100.0)
quiet["value"] = False
busy = u.due(sender, 200.0)
quiet["value"] = True
ok_now = u.due(sender, 300.0)
check("asked: not while the screen moves or the server is busy, then it restarts", not moving and not busy and ok_now,
      f"{moving} {busy} {ok_now}")
src.write_text("def broken(:\n", encoding="utf-8")
u2 = capture.Updater(str(src), "ws://127.0.0.1:8777/ingest", quiet=20, every=5)
sender = types.SimpleNamespace(last_frame_ts=0.0, restart_pending=True)
check("a new file that does not compile is not restarted into, and the request is dropped",
      not u2.due(sender, 100.0) and not sender.restart_pending and "읽을 수 없어" in u2.said, u2.said)
capture.LANG = "en"                          # the same, from a program started in English
u3 = capture.Updater(str(src), "ws://127.0.0.1:8777/ingest", quiet=20, every=5)
sender = types.SimpleNamespace(last_frame_ts=0.0, restart_pending=True)
check("...said in English by a program started in English",
      not u3.due(sender, 100.0) and u3.said.startswith("Cannot read the new capture.py") and not re.search("[가-힣]", u3.said), u3.said)
capture.LANG = "ko"
capture.server_quiet = real_quiet

# server_quiet reads /health
answer = {}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/"
now = 1_000_000.0
cases = [({"capture": {"now": now}, "activity": {"busy": False, "listening": False, "last_answer": now - 600}}, True),
         ({"capture": {"now": now}, "activity": {"busy": True}}, False),
         ({"capture": {"now": now}, "activity": {"listening": True}}, False),
         ({"capture": {"now": now}, "activity": {"last_answer": now - 30}}, False),
         ({"capture": {"now": now}}, True)]
got = []
for a, want in cases:
    answer.clear()
    answer.update(a)
    got.append(capture.server_quiet(url, now) == want)
check("server_quiet reads the server's activity (busy, listening, an answer in the last minute)", all(got), str(got))
check("a server that does not answer is quiet", capture.server_quiet("http://127.0.0.1:9/", now))
srv.shutdown()

# ./sidenote up's side: capture_follow asks for the quiet restart only when the code differs
src_sh = (ROOT / "sidenote").read_text(encoding="utf-8")
fn = re.search(r"^capture_follow\(\) \{.*?^\}\n", src_sh, re.S | re.M).group(0)
mine = hashlib.sha256((ROOT / "client" / "capture.py").read_bytes()).hexdigest()[:12]


def follow(code, clients=1):
    health = json.dumps({"capture": {"clients": clients, "caps": ({"code": code} if code is not None else {})}})
    asked = Path(tempfile.mkdtemp(), "curl.txt")
    script = (f"cd {ROOT}\nURL=http://x\nD=''; N=''\n"
              f"health() {{ printf '%s' '{health}'; }}\n"
              "json() { python3 -c \"import json,sys; d=json.load(sys.stdin); print($1)\"; }\n"
              f"clients() {{ echo {clients}; }}\n"
              "ok() { echo \"OK $*\"; }\nwarn() { echo \"WARN $*\"; }\n"
              "L() { printf '%s' \"$1\"; }\n"                     # the launcher's message helper, in English
              f"curl() {{ echo \"$*\" >> {asked}; }}\n" + fn + "capture_follow\n")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
    return out + (("CURL " + asked.read_text()) if asked.exists() else "")


same, other, old, none = follow(mine), follow("0123456789ab"), follow(None), follow("0123456789ab", clients=0)
check("up: the same code asks nothing; other code asks for the quiet restart; old code is told about; no client nothing",
      same.strip() == "" and "restart?quiet=1" in other and "OK" in other and "WARN" in old and none.strip() == "",
      f"{same!r} {other!r} {old!r} {none!r}")
print(f"==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
