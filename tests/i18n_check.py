"""The server's words in English or Korean: English with no language set, the panel's language once a panel says it
(ui_lang), Korean words that are the old ones from server/locale/ko.json, a level on every notice, ./sidenote report
in the terminal's language (its help and errors, and those of stats and events, too), Monitor's help, and the line
that asks the models for an English answer only in English.

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
                                                                                        "No capture program connected",
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
        check("every notice carries a level", all(m.get("level") in ("info", "done", "warn", "bad")
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
# Monitor's help names its option as the other helps name theirs ("Auto: ...", "Off: ..."): "All monitors takes them" read
# as a plural with a singular verb
help_of = lambda: {i["key"]: i["help"] for i in SETTINGS.meta()["items"]}["monitor"]  # noqa: E731
i18n.set_lang("ko")
ko_help = help_of()
i18n.set_lang("en")
check("Monitor's help in English names All monitors as its option, and the Korean is as it was",
      help_of().startswith("All monitors: every monitor in one picture, so a problem on any of them is seen.")
      and ko_help == "모든 모니터는 한 장으로 받아 어느 모니터의 문제든 봄. Windows에서는 패널 창을 가린 뒤 보냄", [help_of(), ko_help])

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
example = "`Explain the differences between HTTP/1.1 and HTTP/2` 대신 `HTTP/2 multiplexes requests"
check("...and the example of an answer's point beside a title is English in both, where it stayed Korean",
      example in en_system and example in agent_text and "HTTP/1.1과" not in en_system + agent_text
      and "HTTP/1.1과" in ko_system, [s[s.find("HTTP/1.1"):][:60] for s in (en_system, agent_text)])
check("every rule the English answer replaces is still in the prompts (an edit there must update ENGLISH_RULES)",
      all(analyzer.LOCAL_SYSTEM_PROMPT.count(old) == 1 for old, _ in analyzer.ENGLISH_RULES)
      and all(analyzer.SYSTEM_PROMPT.count(old) == 1 for old, _ in analyzer.ENGLISH_RULES[:-1]),
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
      and "풀 것 없음 $0.10 (2번)" in ko, ko[-400:])   # agent answers with nothing to solve, screens or spoken (report.py)
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
# The command line itself: argparse's usage line, headings, -h's help and errors, and the options' own help, were English
# whatever the terminal's language
ARGPARSE_EN = re.compile(r"usage:|options:|show this help|error:|argument |invalid|required|expected one")
helps = {cmd: report(cmd, "--help", LANG="ko_KR.UTF-8") for cmd in ("report", "events", "stats")}
check("report, events and stats --help in Korean: argparse's words and the options' own",
      all(f"사용법: sidenote {cmd}" in said and "옵션:" in said and "이 도움말을 보이고 끝냄" in said
          and not ARGPARSE_EN.search(said) for cmd, said in helps.items())
      and "오늘을 포함한 날수 (7)" in helps["report"] and "최근 몇 개 (30)" in helps["events"] and "JSON으로 출력" in helps["stats"],
      helps)
check("...and what the commands are, under the program's own --help", all(w in report("--help", LANG="ko_KR.UTF-8")
      for w in ("사용법: sidenote", "명령:", "실행 중인 서버의 지금 수치", "로그 폴더의 최근 이벤트", "하루씩, 그리고 기간 전체의 요약")),
      report("--help", LANG="ko_KR.UTF-8"))
en_help = report("report", "--help", LANG="en_US.UTF-8")
check("...in English for an English terminal", "usage: sidenote report" in en_help and "how many days, today included (7)" in en_help
      and not HANGUL.search(en_help), en_help)
said = {"days": report("report", "--days", "x", LANG="ko_KR.UTF-8"), "none": report(LANG="ko_KR.UTF-8"),
        "which": report("reprot", LANG="ko_KR.UTF-8"), "more": report("events", "--json", LANG="ko_KR.UTF-8")}
check("an error in Korean: the program and the argument named, what is wrong said",
      "sidenote report: 오류: 인자 --days: 1 이상의 정수가 아님: x" in said["days"]
      and "sidenote: 오류: 빠진 인자: {stats,events,report}" in said["none"]
      and "인자 {stats,events,report}: 고를 수 없는 값: 'reprot'" in said["which"]
      and "알 수 없는 인자: --json" in said["more"] and not any(ARGPARSE_EN.search(s) for s in said.values()), said)
check("...and in English for an English terminal", "sidenote report: error: argument --days: not a whole number from 1: x"
      in report("report", "--days", "x", LANG="en_US.UTF-8"), report("report", "--days", "x", LANG="en_US.UTF-8"))


print("\n[the settings' help says the server's own limits]")
# Keep answers and Keep what is heard say how long and how much the server keeps, as it is set (docs/README.md): a help
# line once said 90 days and 200 MB with SIDENOTE_HISTORY_DAYS=30 set
probe = ("from server.settings import SETTINGS; import json; m = {i['key']: i['help'] for i in SETTINGS.meta()['items']}; "
         "print(json.dumps([m['history_keep'], m['speech_keep']], ensure_ascii=False))")
with tempfile.TemporaryDirectory() as data:
    env = {**os.environ, "SIDENOTE_LANG": "ko", "SIDENOTE_DATA": data, "SIDENOTE_HISTORY_DAYS": "30", "SIDENOTE_HISTORY_MB": "50",
           "SIDENOTE_HEARD_MB": "5"}
    kept = json.loads(subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True).stdout or "[\"\", \"\"]")
check("Keep answers and Keep what is heard give the days and megabytes set, not fixed ones",
      "30일" in kept[0] and "50 MB" in kept[0] and "30일" in kept[1] and "5 MB" in kept[1], kept)

print("\n[the capture program's words]")
# Every t() of client/capture.py has its Korean, and every Korean there is said somewhere: its console lines were said in English
# under SIDENOTE_LANG=ko, though the program and the guide said they were translated. Read from the source:
# the program imports mss and soundcard only where they are used, but its words are what is checked here
cap_src = (ROOT / "client" / "capture.py").read_text(encoding="utf-8")
cap_tree = ast.parse(cap_src)
said = set()
for node in ast.walk(cap_tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            said.add(arg.value)
ko_table = next(ast.literal_eval(n.value) for n in cap_tree.body
                if isinstance(n, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "KO" for x in n.targets))
check("every word the capture program says through t() has its Korean", not (said - set(ko_table)), sorted(said - set(ko_table))[:8])
check("...and every Korean in its table is said somewhere", not (set(ko_table) - said), sorted(set(ko_table) - said)[:8])
check("...each with the same {places} as its English", all(set(re.findall(r"\{(\w+)\}", k)) == set(re.findall(r"\{(\w+)\}", v))
                                                          for k, v in ko_table.items()),
      [k for k, v in ko_table.items() if set(re.findall(r"\{(\w+)\}", k)) != set(re.findall(r"\{(\w+)\}", v))][:5])
plain = [ln.strip() for ln in cap_src.splitlines() if re.search(r'print\(\s*f?"\[(conn|control|screen|audio|main)\] [a-z]', ln)
         and not re.search(r"(?<![\w.])t\(", ln) and not re.search(r"looks in|sent frame|second\(s\) of sound", ln)]   # t( on its own, not print('s
check("...and no line of what it does is printed past t(), only the measurements", not plain, plain[:5])

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
