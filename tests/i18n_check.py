"""The server's words in English or Korean: English with no language set, the panel's language once a panel says it
(ui_lang), Korean words that are the old ones from server/locale/ko.json, a level on every notice, ./sidenote report
in the terminal's language, and the line that asks the models for an English answer only in English.

    .venv/bin/python tests/i18n_check.py

Runs without SIDENOTE_LANG whatever the environment sets (tests/run.sh sets it for the other suites): the language
follows the panel here, and the command-line checks set the locale themselves.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.pop("SIDENOTE_LANG", None)   # read when server.i18n is imported: the language is then the panel's to set
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-i18n-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="", SIDENOTE_AGENT="mock")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server import i18n  # noqa: E402

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
# A language's own name in the speech language's choices, the same in every language, and the words of Skip windows' default list
# for a Korean browser's private window: titles to look for, not words the panel says
ENDONYMS = {"한국어", "시크릿", "사생활 보호"}


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def hangul_in(value, skip=ENDONYMS) -> list:
    """Every string inside `value` (a message) that holds Hangul, but for the endonyms."""
    found = []
    if isinstance(value, str):
        if HANGUL.search(value) and value not in skip:
            found.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            found += hangul_in(v, skip)
    elif isinstance(value, (list, tuple)):
        for v in value:
            found += hangul_in(v, skip)
    return found


def label_of(meta: dict, key: str) -> str:
    return next((i["label"] for i in meta["items"] if i["key"] == key), "")


class Panel:
    """Reads every message a panel socket gets, in a thread."""

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


print("\n[the table]")
table = json.loads((ROOT / "server" / "locale" / "ko.json").read_text(encoding="utf-8"))
# the keys the code asks for: the string literal first argument of every t(...) and i18n.t(...) in server/*.py
asked, by_name = set(), 0
for f in sorted((ROOT / "server").glob("*.py")):
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if not ((isinstance(fn, ast.Name) and fn.id == "t")
                or (isinstance(fn, ast.Attribute) and fn.attr == "t" and getattr(fn.value, "id", "") == "i18n")):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            asked.add(arg.value)
        elif isinstance(arg, ast.IfExp) and isinstance(arg.body, ast.Constant) and isinstance(arg.orelse, ast.Constant):
            asked.update((arg.body.value, arg.orelse.value))
        else:
            by_name += 1   # a constant passed by its name (RUN_BUSY, a dictionary's value): read at the line below
missing = sorted(k for k in asked if k not in table)
check(f"every word the server code asks for has its Korean ({len(asked)} keys, {by_name} more by name)", not missing,
      str(missing[:5]))
place = re.compile(r"\{(\w+)(?:\|[^}]+)?\}")
# a Korean entry may name the agent where the English says "the agent", and a particle the code picks ({ro})
off = [k for k, v in table.items() if set(place.findall(k)) - set(place.findall(v))
       or set(place.findall(v)) - set(place.findall(k)) - {"agent", "ro"}]
check("each Korean entry fills the placeholders its English has", not off, str(off[:5]))
check("no English key holds Hangul, and every Korean entry does", not [k for k in table if HANGUL.search(k)]
      and not [k for k, v in table.items() if not HANGUL.search(v)],
      str([k for k, v in table.items() if not HANGUL.search(v)][:5]))

print("\n[settings, a notice and the cards follow the panel]")
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

check("with no language set the server starts in English", i18n.LANG == "en", i18n.LANG)
SETTINGS.path = None    # nothing written beside the logs
with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    with client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as pws:
        p = Panel(pws)
        first = p.wait(lambda m: m.get("type") == "settings" and "meta" in m)
        status = p.wait(lambda m: m.get("type") == "status" and "engines" in m)
        meta = first["meta"] if first else {"items": [], "sections": []}
        check("the settings sheet comes in English", label_of(meta, "local_llm") == "Local model"
              and label_of(meta, "agent_mode") == "Problems the agent solves", str([i["label"] for i in meta["items"]][:4]))
        check("...with no Korean in its words but the language names", not hangul_in(meta), str(hangul_in(meta)[:3]))
        check("the agent's card says its name in English", status and status["engines"]["agent"]["label"] == "Agent",
              str(status and status["engines"]["agent"].get("label")))

        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "agent_mode", "value": "bogus"}))
        refused = p.wait(lambda m: m.get("type") == "notice", after=n)
        check("a refused setting is said in English, as a warning",
              refused and refused.get("text") == "Not a value for 'Problems the agent solves'"
              and refused.get("level") == "warn", str(refused))
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "thumb"}))
        thumb = p.wait(lambda m: m.get("type") == "thumb", after=n)
        check("the screen card's words come in English", thumb and thumb.get("text") in ("No screen received",
                                                                                        "Screen capture is off"),
              str(thumb))

        # the panel says Korean: everything with server-made words comes again, in Korean
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "ui_lang", "lang": "ko"}))
        again = p.wait(lambda m: m.get("type") == "settings" and "meta" in m, after=n)
        cards = p.wait(lambda m: m.get("type") == "status" and "engines" in m, after=n)
        check("ui_lang ko switches the server to Korean", i18n.LANG == "ko", i18n.LANG)
        check("the settings are sent again, in Korean", again and label_of(again["meta"], "local_llm") == "이 PC의 모델"
              and label_of(again["meta"], "agent_mode") == "에이전트가 푸는 문제"
              and dict(again["meta"]["sections"]).get("solve") == "풀이 엔진", str(again and again["meta"]["sections"]))
        check("the cards are sent again, in Korean", cards and cards["engines"]["agent"]["label"] == "에이전트", str(cards))
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "agent_mode", "value": "bogus"}))
        refused = p.wait(lambda m: m.get("type") == "notice", after=n)
        check("a notice comes in Korean, the old words",
              refused and refused.get("text") == "'에이전트가 푸는 문제'에 쓸 수 없는 값" and refused.get("level") == "warn",
              str(refused))
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "settings_reset"}))
        reset = p.wait(lambda m: m.get("type") == "notice", after=n)
        check("...and one that reports, as info", reset and reset.get("text") == "이미 모두 기본값"
              and reset.get("level") == "info", str(reset))
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "ui_lang", "lang": "ko"}))
        time.sleep(0.5)
        check("the same language said again sends nothing again",
              not [m for m in p.msgs[n:] if m.get("type") == "settings" and "meta" in m], str(p.msgs[n:][:2]))

        # and back: a browser that does not list Korean first
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "ui_lang", "lang": "en-US"}))
        back = p.wait(lambda m: m.get("type") == "settings" and "meta" in m, after=n)
        check("ui_lang en-US switches back to English", i18n.LANG == "en" and back
              and label_of(back["meta"], "local_llm") == "Local model" and not hangul_in(back["meta"]),
              str(back and hangul_in(back["meta"])[:3]))
        n = len(p.msgs)
        pws.send_text(json.dumps({"type": "ui_lang", "lang": "fr"}))
        time.sleep(0.5)
        check("a language with no table is English", i18n.LANG == "en", i18n.LANG)
        check("every notice carries a level", all(m.get("level") in ("warn", "info")
                                                  for m in p.msgs if m.get("type") == "notice"),
              str([m for m in p.msgs if m.get("type") == "notice"]))

print("\n[options filled at runtime]")
saved = dict(SETTINGS.dynamic_options)
SETTINGS.set_options("monitor", [(0, "All monitors"), (1, ("Monitor {i} ({w}x{h})", {"i": 1, "w": 1920, "h": 1080}))])
i18n.set_lang("ko")
ko_monitors = SETTINGS.options("monitor")
i18n.set_lang("en")
en_monitors = SETTINGS.options("monitor")
SETTINGS.dynamic_options.clear()
SETTINGS.dynamic_options.update(saved)
check("the monitors a capture program names are said in the language of the moment",
      ko_monitors == [(0, "모든 모니터"), (1, "1번 (1920x1080)")]
      and en_monitors == [(0, "All monitors"), (1, "Monitor 1 (1920x1080)")], f"{ko_monitors} {en_monitors}")

print("\n[the models' answers]")
from server import agents, analyzer  # noqa: E402
from server.codecheck import RUNNER_MARK  # noqa: E402

i18n.set_lang("en")
local = analyzer.LocalLlmAnalyzer.__new__(analyzer.LocalLlmAnalyzer)
local.web = None   # no web search: the system prompt alone
en_system, en_agent = local._system(), agents.claude_message([], "x", False).decode()
i18n.set_lang("ko")
ko_system, ko_agent = local._system(), agents.claude_message([], "x", False).decode()
i18n.set_lang("en")
KOREAN_RULES = ("한국어로 쓴다", "한국어 한 줄로", "한국어로 옮겨", "한국어로 쓰고")
check("in English the local model is asked for an English answer", en_system.endswith(analyzer.ANSWER_IN_ENGLISH)
      and en_system == analyzer.in_answer_language(analyzer.LOCAL_SYSTEM_PROMPT))
check("...with none of the prompt's rules asking for Korean left in it", not [r for r in KOREAN_RULES if r in en_system],
      [r for r in KOREAN_RULES if r in en_system])
agent_text = json.loads(en_agent)["message"]["content"][-1]["text"]
check("...and so is the agent, with no rule asking for Korean either",
      agent_text.startswith(analyzer.in_answer_language(analyzer.SYSTEM_PROMPT))
      and analyzer.ANSWER_IN_ENGLISH in agent_text and not [r for r in KOREAN_RULES if r in agent_text], agent_text[-200:])
check("every rule the English answer replaces is still in the prompts (an edit there must update ENGLISH_RULES)",
      all(analyzer.LOCAL_SYSTEM_PROMPT.count(old) == 1 for old, _ in analyzer.ENGLISH_RULES)
      and all(analyzer.SYSTEM_PROMPT.count(old) == 1 for old, _ in analyzer.ENGLISH_RULES[:5]),
      [old[:30] for old, _ in analyzer.ENGLISH_RULES if analyzer.LOCAL_SYSTEM_PROMPT.count(old) != 1])
check("in Korean neither is: the measured prompts as they were", ko_system == analyzer.LOCAL_SYSTEM_PROMPT
      and analyzer.ANSWER_IN_ENGLISH not in ko_agent and "Answer language" not in ko_system)
check("the line is one line", analyzer.ANSWER_IN_ENGLISH.strip().count("\n") == 0)
comment = re.search(r"`([^`]+)`", analyzer.ANSWER_IN_ENGLISH)
check("the runner's comment it asks for in English is read as the runner's mark",
      comment is not None and RUNNER_MARK.search("# " + comment.group(1)) is not None
      and RUNNER_MARK.search("# 입력이 있으면 그 값으로, 없으면 입출력 예로 실행") is not None
      and RUNNER_MARK.search("# Runs on the input if given, else on the examples") is not None
      and RUNNER_MARK.search("# read the input") is None, comment and comment.group(1))

print("\n[./sidenote report in the terminal's language]")
logs = tempfile.mkdtemp(prefix="sidenote-i18n-report-")
now = time.time() - 60
events = [{"ts": now, "event": "analysis_done", "type": "algorithm", "engine": "agent", "trigger": "screen",
           "first_token": 5.0, "elapsed": 15.0, "cost_usd": 0.1, "sent": "Problem area 800x600"},
          {"ts": now, "event": "analysis_done", "type": "none", "engine": "agent", "cost_usd": 0.05,
           "sent": "문제 부분 화면 800x600"},
          {"ts": now, "event": "analysis_done", "type": "none", "engine": "agent", "cost_usd": 0.05,
           "sent": "Problem text, 120 characters"},
          {"ts": now, "event": "analysis_cancelled", "reason": "superseded", "after": 3.0}]
Path(logs, "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def report(*args, **env) -> str:
    """`python -m server.report` in a process of its own, with no SIDENOTE_LANG unless given, and the locale given."""
    clean = {k: v for k, v in os.environ.items() if k not in ("SIDENOTE_LANG", "LANG", "LC_ALL", "LC_MESSAGES")}
    out = subprocess.run([sys.executable, "-m", "server.report", *args], cwd=ROOT, capture_output=True, text=True,
                         env={**clean, "SIDENOTE_LOG_DIR": logs, "PYTHONIOENCODING": "utf-8", **env})
    return out.stdout + out.stderr


en = report("report", "--days", "1", LANG="en_US.UTF-8")
ko = report("report", "--days", "1", LANG="ko_KR.UTF-8")
check("report prints English for an English locale", "Date" in en and "The whole period" in en
      and not HANGUL.search(en), en[-400:])
check("...and Korean for a Korean one, the old words", "날짜" in ko and "기간 전체" in ko
      and "풀 것 없는 화면 $0.10 (2번)" in ko, ko[-400:])
check("the payloads logged in either language are counted as one kind",
      json.loads(report("report", "--days", "1", "--json", LANG="en_US.UTF-8"))["period"]["empty_by_sent"]
      == {"cut-out screen": 1, "written-out text": 1})
check("LC_ALL comes before LANG", "Date" in report("report", "--days", "1", LANG="ko_KR.UTF-8", LC_ALL="C.UTF-8")
      and "날짜" in report("report", "--days", "1", LANG="C.UTF-8", LC_MESSAGES="ko_KR.UTF-8"))
check("SIDENOTE_LANG comes before the locale", "날짜" in report("report", "--days", "1", LANG="en_US.UTF-8",
                                                                SIDENOTE_LANG="ko")
      and "Date" in report("report", "--days", "1", LANG="ko_KR.UTF-8", SIDENOTE_LANG="en"))
check("the server it cannot reach is said in the same language",
      "Cannot reach the server" in report("stats", LANG="en_US.UTF-8", SIDENOTE_PORT="9")
      and "서버 연결 실패" in report("stats", LANG="ko_KR.UTF-8", SIDENOTE_PORT="9"))

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
