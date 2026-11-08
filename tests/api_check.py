"""The API (/api/v1, docs/API.md): what the panel does, for a program. Every message the panel sends has a route, listed in
the index and on docs/API.md, and runs there as it runs from the panel: the same replies, the same messages to a panel
that is open. The reads give what the panel is shown; an answer is followed from its screen to its follow-up, its star
and the cleared history; a page of another site, a write that is not JSON and a Host not of this PC are refused; and the
events stream what the panels are sent, read from a real server on a port of its own, with the page's own examples run
against it.

    .venv/bin/python tests/api_check.py
"""
import asyncio
import base64
import http.client
import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# The server's environment, set before it is imported: stand-in engines, no speech, no runner, no downloads, a log folder
# of its own, and its words in English (tests/run.sh sets Korean for the suites that read them; these hold their own)
LOGS = tempfile.mkdtemp(prefix="sidenote-api-")
ENV = dict(SIDENOTE_ANALYZER="mock", SIDENOTE_AGENT="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
           SIDENOTE_LOG_DIR=LOGS, SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="",
           SIDENOTE_LOCAL_PULL="0", SIDENOTE_UPDATE_CHECK="0")
os.environ.update(ENV)
os.environ.pop("SIDENOTE_LANG", None)
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server import i18n  # noqa: E402
from server.i18n import t  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

SETTINGS.path = None    # nothing written beside the logs
PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}   # the panel's own page
DOC = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:600]}" if detail and not ok else ""))


class Panel:
    """Reads every message one panel's socket gets, in a thread."""

    def __init__(self, ws):
        self.ws, self.msgs = ws, []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.msgs.append(json.loads(self.ws.receive_text()))
        except Exception:
            pass

    def wait(self, pred, timeout=10, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in self.msgs[after:]:
                if pred(m):
                    return m
            time.sleep(0.05)
        return None


def png_b64(seed=0):
    """A screen with a few dark bars standing for lines of text (the change detector reads edges)."""
    im = Image.new("RGB", (640, 400), "white")
    d = ImageDraw.Draw(im)
    for r in range(6):
        d.rectangle([40, 40 + r * 40 + seed, 40 + 300 + (r * 37 + seed) % 200, 52 + r * 40 + seed], fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


print("[the routes and the panel's messages]")
src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
body = src[src.index("    async def panel_command("):src.index('    @app.websocket("/panel")')]
handled = set(re.findall(r'kind == "([a-z_]+)"', body))
for group in re.findall(r"kind in \(([^)]*)\)", body):
    handled |= set(re.findall(r'"([a-z_]+)"', group))
check("PANEL_COMMANDS is what panel_command takes, no more and no fewer", handled == set(A.PANEL_COMMANDS),
      sorted(handled ^ set(A.PANEL_COMMANDS)))
js = (ROOT / "panel" / "app.js").read_text(encoding="utf-8")
sent = set()
for call in re.findall(r"send\(\{\s*type:\s*([^,}]+)", js):   # send({ type: "x" ... }) and send({ type: p ? "a" : "b" })
    sent |= set(re.findall(r'"([a-z_]+)"', call))
sent |= set(re.findall(r'sock\.send\(JSON\.stringify\(\{\s*type:\s*"([a-z_]+)"', js))
check("the panel sends none but these", len(sent) >= 15 and sent <= set(A.PANEL_COMMANDS),
      f"{len(sent)} found, not taken: {sorted(sent - set(A.PANEL_COMMANDS))}")

with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
    index = c.get("/api/v1").json()
    routes = {(r["method"], r["path"]) for r in index["routes"]}
    check("GET /api/v1 lists the routes, with the API's version and the server's",
          index["ok"] is True and index["api"] == 1 and index["version"] == A.VERSION and len(routes) >= 30, index)
    check("every one of the panel's messages has a route", set(index["commands"]) == set(A.PANEL_COMMANDS),
          sorted(set(A.PANEL_COMMANDS) - set(index["commands"])))
    missing = sorted(f"{m} {p}" for m, p in routes if f"`{m} {p}`" not in DOC)
    check("docs/API.md names every route", not missing, missing)
    in_doc = set(re.findall(r"`(GET|POST|PUT|PATCH|DELETE) (/api/v1[^` ]*)`", DOC))
    check("...and no route the server does not have", in_doc and in_doc <= routes, sorted(in_doc - routes))
    named = set(re.findall(r"^\| ((?:`[a-z_]+`(?:, )?)+) \|", DOC[DOC.index("## The panel's messages"):], re.M))
    in_table = {k for row in named for k in re.findall(r"`([a-z_]+)`", row)}
    check("...and the page's table of the panel's messages has each of them", set(A.PANEL_COMMANDS) <= in_table,
          sorted(set(A.PANEL_COMMANDS) - in_table))
    messages = DOC[DOC.index("## The panel's messages"):DOC.index("## Versions")]
    for kind, route in index["commands"].items():
        method, path = route.split(" ", 1)
        row = next((ln for ln in messages.splitlines() if ln.startswith("| ") and f"`{kind}`" in ln.split("|")[1]), "")
        if f"`{method} {path}`" not in row:
            check(f"the page's table gives {kind} its route", False, f"{route} not in {row!r}")
            break
    else:
        check("the page's table gives each message the route the server runs it at", True)

    print("\n[reading]")
    st = c.get("/api/v1/status").json()
    check("status: what a panel is shown as it opens",
          st["ok"] and st["status"]["type"] == "status" and st["status"]["version"] == A.VERSION
          and st["settings"]["values"] == SETTINGS.snapshot() and st["capture"]["type"] == "capture"
          and st["usage"]["type"] == "usage" and st["confirms"] == [] and st["live"] == [] and "busy" in st["activity"],
          sorted(st))
    s1 = c.get("/api/v1/settings").json()
    check("settings: every value, and the sheet's words for each", s1["values"] == SETTINGS.snapshot()
          and {i["key"] for i in s1["meta"]["items"]} == set(SETTINGS.defs), sorted(s1))
    one = c.get("/api/v1/settings/history_keep").json()
    check("one setting: its value and its meta", one["value"] == SETTINGS.get("history_keep")
          and one["meta"]["key"] == "history_keep" and one["meta"]["kind"] == "bool", one)
    r = c.get("/api/v1/settings/no_such_thing")
    check("a setting that is not one is a 404 that says where they are", r.status_code == 404
          and "GET /api/v1/settings" in r.json()["error"], r.json())
    check("answers: none yet", c.get("/api/v1/answers").json() == {"ok": True, "answers": []})
    r = c.get("/api/v1/answers/4242")
    check("an answer not kept is a 404", r.status_code == 404 and r.json()["ok"] is False, r.json())
    r = c.get("/api/v1/answers/not-a-number")
    check("an id that is not a number is a 400 in the API's own shape", r.status_code == 400
          and r.json()["ok"] is False and "seq" in r.json()["error"], r.json())
    d = c.get("/api/v1/days").json()
    check("days: none, nothing starred, nothing heard", d == {"ok": True, "days": [], "starred": 0, "heard": False}, d)
    h = c.get("/api/v1/heard").json()
    check("heard: no day and no line", h == {"ok": True, "days": [], "day": "", "lines": []}, h)
    stats = c.get("/api/v1/stats").json()
    check("stats: what ./sidenote stats shows", stats["ok"] and "analyzer" in stats and "capture" in stats, sorted(stats))
    sc = c.get("/api/v1/screen").json()
    check("screen: none came, and it says so in the panel's words",
          sc == {"ok": True, "url": None, "ts": None, "live": False, "text": t("No screen received")}, sc)
    check("confirms: none waiting", c.get("/api/v1/confirms").json() == {"ok": True, "confirms": []})

    print("\n[changing, as the panel changes it]")
    with c.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as ws:
        p = Panel(ws)
        p.wait(lambda m: m.get("type") == "usage")
        n = len(p.msgs)
        r = c.post("/api/v1/pause", json={})
        check("pause: paused, and an open panel is told", r.json() == {"ok": True, "paused": True}
              and p.wait(lambda m: m.get("type") == "status" and m.get("paused") is True, after=n) is not None, r.json())
        n = len(p.msgs)
        r = c.post("/api/v1/resume", json={})
        check("resume: going on, and the panel is told", r.json() == {"ok": True, "paused": False}
              and p.wait(lambda m: m.get("type") == "status" and m.get("paused") is False, after=n) is not None)
        r = c.post("/api/v1/pause", content=b"", headers={"content-type": "application/json"})
        check("an empty JSON body is taken as {}", r.status_code == 200 and A.STATE.paused is True, r.json())
        c.post("/api/v1/resume", json={})
        n = len(p.msgs)
        r = c.put("/api/v1/settings/history_keep", json={"value": False})
        check("a setting changed: its value now, and the panel's sheet is sent again",
              r.json() == {"ok": True, "key": "history_keep", "value": False} and SETTINGS.get("history_keep") is False
              and p.wait(lambda m: m.get("type") == "settings" and m["values"].get("history_keep") is False, after=n)
              is not None, r.json())
        c.put("/api/v1/settings/history_keep", json={"value": True})
        r = c.put("/api/v1/settings/agent_mode", json={"value": "bogus"})
        check("a value outside its options is refused with the panel's words, and nothing changes",
              r.status_code == 400 and r.json()["value"] == SETTINGS.get("agent_mode") and r.json()["error"], r.json())
        r = c.put("/api/v1/settings/agent_mode", json={"val": "all"})
        check("a body without value is a 400 that says what to send", r.status_code == 400 and '"value"' in r.json()["error"])
        SETTINGS.set("history_keep", False)
        r = c.post("/api/v1/settings/reset", json={})
        check("reset: back to the defaults", r.status_code == 200 and SETTINGS.get("history_keep") is True
              and r.json()["values"] == SETTINGS.snapshot(), r.json())
        r = c.put("/api/v1/capture", json={"screen": False})
        check("capture: the screen switched off, the sound left as it was", r.json()["screen"] is False
              and r.json()["audio"] is True and A.STATE.screen_on is False, r.json())
        r = c.put("/api/v1/capture", json={"screen": True, "audio": False})
        check("...both at once", A.STATE.screen_on is True and A.STATE.audio_on is False, r.json())
        c.put("/api/v1/capture", json={"audio": True})
        for bad in ({}, {"screen": "yes"}, {"screen": True, "audio": 1}):
            r = c.put("/api/v1/capture", json=bad)
            if r.status_code != 400:
                check(f"capture refuses {bad}", False, r.json())
                break
        else:
            check("capture refuses a body with no switch, or one that is not true or false", True)
        n = len(p.msgs)
        r = c.post("/api/v1/gpu/load", json={})
        check("load to GPU: started, and the engines' status says it is on",
              r.status_code == 202 and p.wait(lambda m: m.get("type") == "status"
                                               and ((m.get("engines") or {}).get("local") or {}).get("loaded"), after=n),
              r.json())
        r = c.post("/api/v1/gpu/load/cancel", json={})
        check("stopping a load that has ended says it is loaded already",
              r.json()["ok"] and r.json()["notices"] == [{"level": "info", "text": t("Already loaded")}], r.json())
        r = c.post("/api/v1/gpu/release", json={})
        check("free GPU: taken off, in the panel's words", r.json() == {"ok": True, "notices": [
              {"level": "done", "text": t("Taken off the GPU · loaded again for the next problem")}]}, r.json())
        SETTINGS.set("local_llm", False)
        r = c.post("/api/v1/gpu/load", json={})
        check("with the local model off, a load is refused (409), in the panel's words", r.status_code == 409
              and r.json()["error"] == t("The local model is off: nothing to load onto the GPU"), r.json())
        SETTINGS.set("local_llm", SETTINGS.defs["local_llm"].default)
        r = c.post("/api/v1/models/pull", json={"model": "no-such-model"})
        check("a download of a model not offered is a 400 with the models offered", r.status_code == 400
              and "sidenote-gemma4:26b" in r.json()["models"], r.json())
        r = c.post("/api/v1/models/pull", json={"model": "sidenote-gemma4:26b"})
        check("with downloads off (SIDENOTE_LOCAL_PULL=0) it is a 409 that says so", r.status_code == 409
              and "SIDENOTE_LOCAL_PULL" in r.json()["error"], r.json())
        pulled = []

        async def fake_pull(name):
            pulled.append(name)
        real_allowed, real_pull = A.pull_allowed, A.pull_model
        A.pull_allowed, A.pull_model = (lambda: True), fake_pull
        try:
            r = c.post("/api/v1/models/pull", json={"model": "sidenote-gemma4:e4b"})
            time.sleep(0.2)
            check("with downloads on, it starts the panel's download of that model (202)",
                  r.status_code == 202 and pulled == ["sidenote-gemma4:e4b"], [r.json(), pulled])
        finally:
            A.pull_allowed, A.pull_model = real_allowed, real_pull
        r = c.put("/api/v1/language/panel", json={"lang": "ko"})
        check("the panel's language: Korean words from here on, and the panel's sheet is sent in them",
              r.json() == {"ok": True, "lang": "ko"} and i18n.LANG == "ko"
              and p.wait(lambda m: m.get("type") == "settings" and m["meta"]["items"][0]["label"]
                         == SETTINGS.meta()["items"][0]["label"], after=n) is not None, r.json())
        c.put("/api/v1/language/panel", json={"lang": "en"})
        check("...and back", i18n.LANG == "en")
        r = c.put("/api/v1/language/panel", json={"lang": "fr"})
        check("a language not offered is a 400", r.status_code == 400, r.json())
        fixed, was = i18n._fixed, i18n.LANG
        i18n._fixed = i18n.LANG = "ko"   # as SIDENOTE_LANG=ko leaves them when the server starts
        try:
            r = c.put("/api/v1/language/panel", json={"lang": "en"})
            check("with SIDENOTE_LANG holding another it is a 409 that says so, and the words stay",
                  r.status_code == 409 and "SIDENOTE_LANG" in r.json()["error"] and r.json()["lang"] == "ko"
                  and i18n.LANG == "ko", r.json())
            r = c.put("/api/v1/language/panel", json={"lang": "ko"})
            check("...and asked for the one it holds, it is that", r.json() == {"ok": True, "lang": "ko"}, r.json())
        finally:
            i18n._fixed, i18n.LANG = fixed, was
        tr = A.app.state.transcriber
        r = c.put("/api/v1/language/speech", json={"lang": "ko"})
        check("the speech language with nothing writing speech down is a 409", r.status_code == 409, r.json())
        tr.language = "auto"   # as a transcriber that writes speech down has it
        try:
            n = len(p.msgs)
            r = c.put("/api/v1/language/speech", json={"lang": "ko"})
            check("...and with one, it is set, and the panel is told",
                  r.json() == {"ok": True, "lang": "ko"} and p.wait(lambda m: m.get("type") == "status"
                                                                     and m.get("lang") == "ko", after=n) is not None, r.json())
            r = c.put("/api/v1/language/speech", json={"lang": "de"})
            check("...a language it does not write is a 400", r.status_code == 400)
        finally:
            del tr.language
        r = c.post("/api/v1/capture/restart", json={})
        check("restart capture: no capture program connected, none asked", r.json() == {"ok": True, "asked": 0}, r.json())
        r = c.post("/api/v1/capture/quit", json={})
        check("quit capture: the same", r.json() == {"ok": True, "asked": 0}, r.json())
        r = c.post("/api/v1/commands", json={"type": "thumb"})
        check("commands: a message of the panel's, with what it sends back",
              r.json()["ok"] and r.json()["replies"][0]["type"] == "thumb", r.json())
        r = c.post("/api/v1/commands", json={"type": "drop_tables"})
        check("...a type that is none of the panel's messages is a 400 listing them", r.status_code == 400
              and set(r.json()["types"]) == set(A.PANEL_COMMANDS), r.json())

        print("\n[the panel's socket, after the move]")
        ws.send_text("[1, 2]")                         # an array where an object belongs
        ws.send_text('"pause"')                        # and a string
        n = len(p.msgs)
        ws.send_text(json.dumps({"type": "pause"}))
        check("a message that is not an object leaves the socket open, and the next one runs",
              p.wait(lambda m: m.get("type") == "status" and m.get("paused") is True, after=n) is not None)
        n = len(p.msgs)
        ws.send_text(json.dumps({"type": "resume"}))
        check("...as the panel's pause key runs", p.wait(lambda m: m.get("type") == "status" and m.get("paused") is False,
                                                         after=n) is not None)
        n = len(p.msgs)
        ws.send_text(json.dumps({"type": "thumb"}))
        from_panel = p.wait(lambda m: m.get("type") == "thumb", after=n)
        check("the same message from the panel and from the API gives the same reply",
              from_panel is not None and {k: v for k, v in from_panel.items() if k != "type"}
              == {k: v for k, v in c.get("/api/v1/screen").json().items() if k != "ok"}, from_panel)

        print("\n[an answer, through the API]")
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_confirm=False, history_keep=True)
        A.STATE.local, A.STATE.agent = {"ok": True}, {"ok": True}
        with c.websocket_connect("ws://127.0.0.1:8777/ingest", headers=ORIGIN) as cap:
            cap.send_text(json.dumps({"type": "hello", "info": "capture/test", "screen": True, "audio": False,
                                      "no_audio": True, "monitor": 1, "flags": {}}))
            n = len(p.msgs)
            cap.send_text(json.dumps({"type": "frame", "data": png_b64()}))
            done = p.wait(lambda m: m.get("type") == "analysis_done", timeout=30, after=n)
            check("a screen from the capture program is answered", done is not None, [m.get("type") for m in p.msgs[n:]][-8:])
            seq = done["id"] if done else -1
            time.sleep(0.3)   # the history's own thread keeps it
            got = c.get(f"/api/v1/answers/{seq}").json()
            check("the answer is kept, and GET /api/v1/answers/{id} gives it whole",
                  got["ok"] and got["answer"]["id"] == seq and got["answer"]["text"] == done["text"]
                  and got["answer"]["starred"] is False, got)
            listed = c.get("/api/v1/answers").json()["answers"]
            check("...and the list has it", [a["id"] for a in listed] == [seq], [a["id"] for a in listed])
            days = c.get("/api/v1/days").json()["days"]
            check("...under the day it was answered", [x["day"] for x in days]
                  == [time.strftime("%Y-%m-%d", time.localtime(got["answer"]["ts"]))], days)
            sc = c.get("/api/v1/screen").json()
            check("the screen now: its picture, when it came, and that screens are coming",
                  sc["url"].startswith("data:image/jpeg;base64,") and sc["live"] is True and sc["ts"], sc)
            n = len(p.msgs)
            r = c.put(f"/api/v1/answers/{seq}/star", json={"starred": True})
            check("star: starred, how many are now, and the panel is told",
                  r.json() == {"ok": True, "id": seq, "starred": True, "count": 1}
                  and p.wait(lambda m: m.get("type") == "star" and m.get("id") == seq, after=n) is not None, r.json())
            check("...and the list of starred ones has it",
                  [a["id"] for a in c.get("/api/v1/answers", params={"starred": "true"}).json()["answers"]] == [seq])
            r = c.put("/api/v1/answers/424242/star", json={"starred": True})
            check("a star on an answer not kept is a 409 in the panel's words", r.status_code == 409
                  and r.json()["error"] == t("Not starred: this answer is not in the saved history"), r.json())
            r = c.put(f"/api/v1/answers/{seq}/star", json={"starred": "yes"})
            check("...and a star that is not true or false is a 400", r.status_code == 400)
            n = len(p.msgs)
            ws.send_text(json.dumps({"type": "run", "id": seq, "lang": "python", "code": "print(1)", "stdin": ""}))
            panel_run = p.wait(lambda m: m.get("type") == "run_result", after=n)
            r = c.post(f"/api/v1/answers/{seq}/run", json={"lang": "python", "code": "print(1)"})
            check("run: with code runs off, the panel's reply and the API's are the same (422)", r.status_code == 422
                  and panel_run is not None and r.json()["error"] == panel_run["error"] == t("Code runs are off"),
                  [r.json(), panel_run])
            r = c.post(f"/api/v1/answers/{seq}/run", json={"lang": "python"})
            check("...and a run without code is a 400", r.status_code == 400)
            n = len(p.msgs)
            ws.send_text(json.dumps({"type": "problem_text", "id": seq}))
            panel_pt = p.wait(lambda m: m.get("type") == "problem_text", timeout=20, after=n)
            r = c.post(f"/api/v1/answers/{seq}/problem", json={})
            same = panel_pt is not None and (r.json().get("text") == panel_pt.get("text") if "text" in panel_pt
                                             else r.json().get("error") == panel_pt.get("error"))
            check("problem text: the panel's reply and the API's are the same", same, [r.json(), panel_pt])
            r = c.post("/api/v1/answers/1/problem", json={})
            check("...and for an answer other than the latest it is a 409 in the panel's words", r.status_code == 409
                  and r.json()["error"] == t("Only for the latest problem on the screen"), r.json())
            n = len(p.msgs)
            r = c.post("/api/v1/ask", json={"text": "why this way?"})
            start = p.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") == "ask", timeout=20, after=n)
            fin = start and p.wait(lambda m: m.get("type") in ("analysis_done", "error", "analysis_cancelled")
                                   and m.get("id") == start["id"], timeout=30, after=n)
            check("ask: started (202), answered about that answer, as the panel's question box does",
                  r.status_code == 202 and start is not None and start.get("about") == seq
                  and start.get("transcript") == "why this way?" and fin is not None and fin["type"] == "analysis_done",
                  [r.json(), start, fin and fin.get("type")])
            time.sleep(0.3)
            turns = c.get(f"/api/v1/answers/{seq}").json()["answer"].get("turns") or []
            check("...and the follow-up is kept with the answer", [x.get("q") for x in turns] == ["why this way?"], turns)
            r = c.post("/api/v1/ask", json={"text": "  "})
            check("...an empty question is a 400", r.status_code == 400)
            n = len(p.msgs)
            r = c.post("/api/v1/reanalyze", json={})
            again = p.wait(lambda m: m.get("type") == "analysis_start" and m.get("trigger") != "ask", timeout=20, after=n)
            check("reanalyze: started (202), and the same screen is answered again", r.status_code == 202
                  and again is not None, [r.json(), [m.get("type") for m in p.msgs[n:]][-6:]])
            p.wait(lambda m: m.get("type") in ("analysis_done", "analysis_cancelled", "error") and again
                   and m.get("id") == again["id"], timeout=30, after=n)
            n = len(p.msgs)
            r = c.request("DELETE", "/api/v1/answers", json={})
            check("clear history: cleared, in the panel's words, and every panel is told",
                  r.json() == {"ok": True, "notices": [{"level": "done", "text": t("Cleared, the saved history too")}]}
                  and p.wait(lambda m: m.get("type") == "history_cleared", after=n) is not None, r.json())
            check("...and nothing is kept", c.get("/api/v1/answers").json()["answers"] == []
                  and c.get("/api/v1/days").json()["starred"] == 0)

        print("\n[a problem waiting for a yes or no]")

        async def waiting(cid):
            fut = asyncio.get_running_loop().create_future()
            A.STATE.confirms[cid] = (fut, {"type": "agent_confirm", "id": 77, "cid": cid, "kind": "screen",
                                           "timeout": 120, "ts": time.time() - 30})
            return fut

        async def outcome(fut):
            return fut.done() and fut.result()
        fut = c.portal.call(waiting, "c-1")
        waits = c.get("/api/v1/confirms").json()["confirms"]
        check("confirms: the one waiting, with the seconds it has left", len(waits) == 1 and waits[0]["cid"] == "c-1"
              and 85 <= waits[0]["timeout"] <= 90.5, waits)
        check("...and the status has it too", [m["cid"] for m in c.get("/api/v1/status").json()["confirms"]] == ["c-1"])
        r = c.post("/api/v1/confirms/c-1", json={"send": "yes"})
        check("an answer that is not true or false is a 400, and it still waits", r.status_code == 400
              and not fut.done())
        r = c.post("/api/v1/confirms/c-1", json={"send": True})
        check("send: the problem goes to the agent, as the card's Send", r.json() == {"ok": True, "cid": "c-1", "send": True}
              and c.portal.call(outcome, fut) is True, r.json())
        r = c.post("/api/v1/confirms/c-1", json={"send": False})
        check("...and once answered, it is no longer waiting (404)", r.status_code == 404, r.json())
        A.STATE.confirms.pop("c-1", None)

    print("\n[refused]")
    writes = [(r["method"], r["path"]) for r in index["routes"] if r["method"] != "GET"]
    concrete = [(m, p.replace("{key}", "history_keep").replace("{seq}", "1").replace("{cid}", "c-9")) for m, p in writes]
    not_json = [(m, p, c.request(m, p).status_code) for m, p in concrete]
    check("every route that changes something refuses a request that is not JSON (415)",
          all(code == 415 for _, _, code in not_json), [x for x in not_json if x[2] != 415])
    form = c.post("/api/v1/pause", content=b"a=1", headers={"content-type": "application/x-www-form-urlencoded"})
    check("...a plain form post among them, and nothing changes", form.status_code == 415 and A.STATE.paused is False)
    foreign = {"origin": "https://elsewhere.example"}
    reads = [r["path"] for r in index["routes"] if r["method"] == "GET" and "{" not in r["path"]]
    check("every read refuses another site's page (403)",
          all(c.get(path, headers=foreign).status_code == 403 for path in reads))
    r = c.post("/api/v1/pause", json={}, headers=foreign)
    check("...and so does every change, JSON and all", r.status_code == 403 and A.STATE.paused is False
          and all(c.request(m, p, json={}, headers=foreign).status_code == 403 for m, p in concrete))
    r = c.post("/api/v1/pause", json={}, headers={"origin": "null"})
    check("a page that hides where it is from (Origin: null) is refused", r.status_code == 403 and A.STATE.paused is False)
    r = c.post("/api/v1/pause", json={}, headers=ORIGIN)
    check("the panel's own page is let through", r.status_code == 200 and A.STATE.paused is True)
    c.post("/api/v1/resume", json={})
    r = c.get("/api/v1/status", headers={"host": "elsewhere.example"})
    check("a Host that is not this PC's (a name pointed at it) is refused", r.status_code == 400)
    r = c.get("/api/v1/pause")
    check("a route asked with another method says which it takes (405)", r.status_code == 405
          and r.json()["methods"] == ["POST"], r.json())
    r = c.get("/api/v1/nothing/here")
    check("an address that is no route is a 404 in the API's shape, not the panel's page", r.status_code == 404
          and r.json()["ok"] is False and "GET /api/v1" in r.json()["error"], r.text[:200])
    r = c.post("/api/v1/ask", content=b"{not json", headers={"content-type": "application/json"})
    check("a body that is not JSON is a 400", r.status_code == 400 and r.json()["error"] == "the body is not JSON")
    r = c.post("/api/v1/ask", content=b"[1]", headers={"content-type": "application/json"})
    check("...and one that is not an object", r.status_code == 400 and "object" in r.json()["error"])
    stop = c.post("/server/stop")
    check("the desktop app's stop is not part of the API, and still asks its token", stop.status_code == 403)

print("\n[the events' reader]")


async def lag():
    s = A.EventStream()
    for i in range(A.EventStream.MAX + 5):
        s.put({"type": "delta", "n": i})
    first = await s.take(1)
    s.put({"type": "notice"})
    second = await s.take(1)
    empty = await s.take(0.1)
    return first, second, empty
first, second, empty = asyncio.run(lag())
check("a reader 5 behind its limit loses the 5 oldest, and is told so first",
      first[0] == {"type": "lagged", "lost": 5} and first[1]["n"] == 5 and len(first) == A.EventStream.MAX + 1, first[:2])
check("...and the next batch has no such line", second == [{"type": "notice"}])
check("...nothing that came: an empty batch after the wait", empty == [])


print("\n[events, from a server on a port of its own]")
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()
logs = tempfile.mkdtemp(prefix="sidenote-api-server-")
env = {**os.environ, **ENV, "SIDENOTE_LOG_DIR": logs, "SIDENOTE_PORT": str(PORT), "SIDENOTE_TRUST_GATEWAY": "0"}
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(PORT),
                           "--no-access-log"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if body is not None else {}),
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def open_events():
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=25)
    conn.request("GET", "/api/v1/events")
    return conn, conn.getresponse()


def read_events(resp, until, limit=40):
    """(id, message) for each event read, until `until(message)` holds or `limit` events came."""
    got, ev_id, comments = [], None, 0
    while len(got) < limit:
        line = resp.readline().decode("utf-8").rstrip("\n")
        if line.startswith(":"):
            comments += 1
        elif line.startswith("id: "):
            ev_id = int(line[4:])
        elif line.startswith("data: "):
            got.append((ev_id, json.loads(line[6:])))
            if until(got[-1][1]):
                break
    return got


try:
    up = None
    for _ in range(150):
        try:
            up = call("GET", "/health")[1]
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    check("the server answers on its port", up is not None and up["ok"] and up["event_readers"] == 0, up)
    conn, resp = open_events()
    check("events: a stream of Server-Sent Events that no proxy holds back, nor a browser serves from its cache",
          resp.status == 200 and resp.getheader("content-type", "").startswith("text/event-stream")
          and resp.getheader("x-accel-buffering") == "no" and resp.getheader("cache-control") == "no-cache",
          [resp.status, resp.getheaders()])
    opening = read_events(resp, lambda m: m.get("type") == "usage")
    check("...starting with what a panel is told as it opens, in order, numbered from 1",
          [m["type"] for _, m in opening] == ["status", "settings", "capture", "usage"]
          and [i for i, _ in opening] == [1, 2, 3, 4], [(i, m.get("type")) for i, m in opening])
    check("...and the server counts the reader", call("GET", "/health")[1]["event_readers"] == 1)
    code, body = call("POST", "/api/v1/pause", {})
    after = read_events(resp, lambda m: m.get("type") == "status" and m.get("paused") is True)
    check("...then each message as it goes to the panels, numbered on: the pause sent through the API",
          code == 200 and after and after[-1][1] == {"type": "status", "paused": True}
          and [i for i, _ in after] == list(range(5, 5 + len(after))), [code, body, after])
    call("POST", "/api/v1/resume", {})
    read_events(resp, lambda m: m.get("type") == "status" and m.get("paused") is False)
    conn.close()
    gone = None
    for _ in range(60):
        gone = call("GET", "/health")[1]["event_readers"]
        if gone == 0:
            break
        time.sleep(0.25)
    check("a reader that goes away is let go", gone == 0, gone)
    many = [open_events() for _ in range(32)]
    over = call("GET", "/api/v1/events")
    check("a 33rd reader at once is a 429", over[0] == 429 and over[1]["ok"] is False, over)
    for cn, _ in many:
        cn.close()
    for _ in range(60):   # each let go before the examples open one more
        if call("GET", "/health")[1]["event_readers"] == 0:
            break
        time.sleep(0.25)
    # The page's own examples, against this server: every curl line, the address swapped for its port
    ran = []
    for line in re.findall(r"^curl .*$", DOC, re.M):
        argv = shlex.split(line.replace("http://127.0.0.1:8777", BASE))
        if "-N" in argv:   # the stream: read its first lines, then let it go
            argv = [a for a in argv if a != "-N"] + ["--max-time", "3"]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        text = out.stdout
        ok = (text.startswith("id: 1\ndata: ") if "/events" in line else json.loads(text).get("ok") is True)
        ran.append((ok, line[:90], text[:120]))
    check("the page's curl examples run, each answered ok", len(ran) >= 5 and all(ok for ok, _, _ in ran),
          [x for x in ran if not x[0]] or len(ran))
    py = re.search(r"```python\n(.*?)```", DOC, re.S).group(1).replace("http://127.0.0.1:8777", BASE)
    reader = subprocess.Popen([sys.executable, "-c", py], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.5)
    call("PUT", "/api/v1/capture", {"screen": False})
    call("PUT", "/api/v1/capture", {"screen": True})
    time.sleep(0.5)
    still = reader.poll() is None      # reading the stream still, not ended on an error
    reader.terminate()
    out, err = reader.communicate(timeout=10)
    check("the page's Python example reads the stream, its messages and all, without an error",
          still and "Traceback" not in err, err[-400:])
finally:
    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill()

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
if FAIL:
    print("FAILURES:", FAIL)
    sys.exit(1)
