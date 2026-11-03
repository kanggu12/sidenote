"""The pictures in an answer (panel/app.js, drawPictures): ```chart drawn as SVG, ```mermaid drawn by mermaid.

    .venv-panel/bin/python tests/panel_viz.py
    PANEL_DIR=/older/panel .venv-panel/bin/python tests/panel_viz.py   # watch it fail there

Serves a copy of panel/ with the Content-Security-Policy the server sends (read out of server/app.py), so
mermaid is loaded and run under the same rules as in the real panel, behind panel_review.py's stand-in
socket. Needs panel/vendor/mermaid.min.js (docker/fetch_vendor.py docker/vendor.json panel/vendor).

Checks:
  - each kind of chart draws its marks (bars, bars across, groups, stacks, lines, a timetable), with the
    numbers in the table under it and the legend from two series up
  - a spec that cannot be drawn stays the code block it came as, named on its bar, with the reason over it
  - words in a spec and in a diagram stay words: nothing in them runs or becomes an element
  - a flowchart and a sequence diagram are drawn as an image that loads, under the CSP, with no errors
  - a diagram mermaid cannot read stays code, with the reason
  - while the answer is written, a picture's block is a waiting line, not JSON arriving piece by piece
  - a chart is drawn again at a new width; a diagram again in the other theme
  - the readability marks: a bold-only paragraph is .lead, a column of numbers is .num, headings and
    key words take the kind colour, the body is 16px
Writes screenshots to viz/ in the output folder (SIDENOTE_TEST_OUT) to look at. The answer prompt's own chart
examples are read with the server's interpreter (PY). The thread the question box floats over is made of answers
the local model wrote for the bench (SIDENOTE_BENCH): that group is skipped where the bench is missing.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent     # tests/
sys.path.insert(0, str(HERE))              # panel_review and support beside it, when this is imported from elsewhere
import panel_review as pr  # noqa: E402  (the stand-in socket, the messages, check())
import support  # noqa: E402  (the output folder, the server's interpreter, the settings message, the skip line)

ROOT = HERE.parent                         # the repository
PANEL = Path(os.environ.get("PANEL_DIR") or ROOT / "panel")
SHOTS = support.out("viz")
# The policy the server sends with the panel, as written in server/app.py (CSP = ("..." "...")).
CSP = " ".join(re.findall(r'"([^"]*)"', re.search(r"^CSP = \((.*?)\)$", (ROOT / "server" / "app.py").read_text(),
                                                   re.S | re.M).group(1)))
CSP = "".join(re.findall(r'"([^"]*)"', re.search(r"^CSP = \((.*?)\)$", (ROOT / "server" / "app.py").read_text(),
                                                  re.S | re.M).group(1)))
check, PASS, FAIL = pr.check, pr.PASS, pr.FAIL


class WithCsp(SimpleHTTPRequestHandler):
    """The static server, quiet, sending the panel's Content-Security-Policy with every file."""

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def log_message(self, *args):
        pass


HEAD = "TYPE: {kind}\nANSWER: {answer}\nASKED: {asked}\n\n"
FENCE = "```"


def classic_skin(pn):
    return pn.pg.evaluate("() => document.documentElement.dataset.skin === 'classic'")


def answer(kind, body, ans="답", asked="물음"):
    return HEAD.format(kind=kind, answer=ans, asked=asked) + body


def block(lang, src):
    return f"\n{FENCE}{lang}\n{src}\n{FENCE}\n"


BAR = {"type": "bar", "title": "n = 1,000 일 때 비교 횟수", "unit": "회", "x": ["버블", "삽입", "병합", "퀵"],
       "series": [{"name": "비교 횟수", "values": [499500, 250000, 8700, 11000]}], "highlight": "병합"}
ACROSS = {"type": "bar", "title": "리전별 p95 지연", "unit": "ms",
          "x": ["서울 (ap-northeast-2)", "도쿄 (ap-northeast-1)", "버지니아 (us-east-1)", "오리건 (us-west-2)",
                "프랑크푸르트 (eu-central-1)", "싱가포르 (ap-southeast-1)"],
          "series": [{"name": "p95", "values": [12, 38, 182, 141, 236, 71]}]}
GROUPS = {"type": "bar", "title": "캐시 적용 전후", "unit": "ms", "x": ["로그인", "검색", "결제"],
          "series": [{"name": "적용 전", "values": [220, 340, 510]}, {"name": "적용 후", "values": [90, 120, 300]}]}
STACK = {"type": "stack", "title": "요청 시간 구성", "unit": "ms", "x": ["A", "B", "C"],
         "series": [{"name": "DNS", "values": [10, 12, 8]}, {"name": "TLS", "values": [30, 25, 40]},
                    {"name": "서버", "values": [80, 60, 120]}]}
LINE = {"type": "line", "title": "n 에 따른 연산 수", "x": [10, 100, 1000, 10000],
        "series": [{"name": "n log n", "values": [33, 664, 9966, 132877]}, {"name": "n", "values": [10, 100, 1000, 10000]}]}
GANTT = {"type": "gantt", "title": "Round Robin (q = 2)", "unit": "ms",
         "tasks": [{"name": "P1", "start": 0, "end": 2}, {"name": "P2", "start": 2, "end": 4},
                   {"name": "P3", "start": 4, "end": 5}, {"name": "P1", "start": 5, "end": 7},
                   {"name": "P2", "start": 7, "end": 8}, {"name": "P1", "start": 8, "end": 9}]}
FLOW = """flowchart LR
  C["클라이언트"] --> LB["로드 밸런서 (L7)"]
  LB --> A["API 서버"]
  A --> DB[("PostgreSQL")]
  A --> R["Redis 캐시"]"""
SEQ = """sequenceDiagram
  participant C as 클라이언트
  participant S as 서버
  C->>S: SYN
  S->>C: SYN-ACK
  C->>S: ACK"""
BAD_FLOW = """flowchart LR
  A[로드 밸런서 (L7)] --> B{{{"""
EVIL_CHART = {"type": "bar", "title": "<img src=x onerror=\"window.__pwned=1\">",
              "x": ["<b>x</b>", "<script>window.__pwned=2</script>"],
              "series": [{"name": "<svg onload=window.__pwned=3>", "values": [1, 2]}]}
EVIL_FLOW = """flowchart LR
  A["<img src=x onerror=window.__pwned=4>"] --> B["<script>window.__pwned=5</script>"]
  click A call alert("x")
  click B "javascript:window.__pwned=6"
"""
J = lambda o: json.dumps(o, ensure_ascii=False)   # noqa: E731

# One answer with every kind of chart, written the way the models write an answer (head lines, headings,
# a bold step line, a table with a number column), and one with the diagrams.
CHARTS = answer("algorithm", "## 비교\n\n**1. 횟수를 센다**\n\n| 알고리즘 | 비교 횟수 | 복잡도 |\n|---|---|---|\n"
                "| 버블 | 499,500 | O(n^2) |\n| 병합 | 8,700 | O(n log n) |\n\n결론은 **병합 정렬**이다."
                + block("chart", J(BAR)) + block("chart", J(ACROSS)) + block("chart", J(GROUPS))
                + block("chart", J(STACK)) + block("chart", J(LINE)) + block("chart", J(GANTT)),
                "병합 정렬, 시간 $O(n \\log n)$", "정렬 알고리즘별 비교 횟수")
DIAGRAMS = answer("diagram", "## 구성\n" + block("mermaid", FLOW) + "\n## 연결\n" + block("mermaid", SEQ),
                  "LB 뒤에 API 서버와 캐시", "웹 서비스 구성을 그리시오")
BROKEN = answer("work", "앞 글." + block("chart", '{"type":"bar","x":["a","b"],"series":[{"values":[1,2,3]}]}')
                + block("chart", "{type: bar}") + block("chart", J({"type": "pie", "x": ["a"], "series": [{"values": [1]}]}))
                + block("mermaid", BAD_FLOW) + "\n뒤 글.", "깨진 그림", "깨진 그림")
EVIL = answer("work", "악성." + block("chart", J(EVIL_CHART)) + block("mermaid", EVIL_FLOW), "악성", "악성")


# Every pair of words in each chart whose boxes overlap (more than a pixel each way): a label drawn over a
# label, which a chart at some width or with some numbers can do without anything else looking wrong.
OVERLAPS = """() => [...document.querySelectorAll('.entry figure.viz-chart svg')].flatMap((svg, k) => {
  const boxes = [...svg.querySelectorAll('text')].map((t) => ({ t: t.textContent, b: t.getBBox() }));
  const out = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].b, c = boxes[j].b;
    if (Math.min(a.x + a.width, c.x + c.width) - Math.max(a.x, c.x) > 1 && Math.min(a.y + a.height, c.y + c.height) - Math.max(a.y, c.y) > 1)
      out.push(`chart ${k + 1}: '${boxes[i].t}' / '${boxes[j].t}'`);
  }
  return out; })"""


def prompt_examples():
    """The ```chart examples the answer prompt shows the models (server/analyzer.py, SYSTEM_PROMPT), as the
    models read them: a model copies the shape it is shown, so each has to be a spec the panel draws."""
    import subprocess
    text = subprocess.run([support.server_python(), "-c",   # the server's interpreter (PY), with its packages
                           "from server.analyzer import SYSTEM_PROMPT; print(SYSTEM_PROMPT)"],
                          cwd=ROOT, capture_output=True, text=True, check=True,
                          env={**os.environ, "SIDENOTE_ANALYZER": "mock"}).stdout
    found, i = [], text.find('{"type"')
    while i >= 0:                                   # each object, by matching its braces
        depth = 0
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                found.append(text[i:j + 1])
                break
        i = text.find('{"type"', j + 1)
    return found


def wait_for(pn, js, ms=8000):
    """Poll a condition in the page (mermaid loads 3.5 MB and draws asynchronously)."""
    for _ in range(ms // 100):
        if pn.ev(js):
            return True
        pn.pg.wait_for_timeout(100)
    return False


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(PANEL)                 # the page's libraries, which are fetched rather than kept in git
    if not (PANEL / "vendor" / "mermaid.min.js").exists():
        print("  panel/vendor/mermaid.min.js is missing: python docker/fetch_vendor.py docker/vendor.json panel/vendor")
        return 2
    pr.SETTINGS = support.settings_message()   # what server/settings.py sends a panel that connects
    work = Path(tempfile.mkdtemp(prefix="panel-viz-"))
    static = work / "panel"
    shutil.copytree(PANEL, static)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(WithCsp, directory=str(static)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    SHOTS.mkdir(parents=True, exist_ok=True)
    print(f"checking {PANEL} (served from {static}, with the server's CSP)")
    errors = []

    with sync_playwright() as p:
        br = p.chromium.launch(args=["--no-sandbox"])

        def new(width=1100, theme="light", height=1000):
            pn = pr.Panel(br, url, width, theme, height)
            pn.console = []
            pn.pg.on("console", lambda m: pn.console.append(f"{m.type}: {m.text}"))
            return pn

        def charts():
            pn = new()
            pn.up()
            pn.push(pr.start(1), pr.done(1, CHARTS))
            pn.pg.wait_for_timeout(500)
            figs = pn.ev("() => [...document.querySelectorAll('.entry figure.viz-chart')].map((f) => ({"
                         " marks: f.querySelectorAll('.mark').length, lines: f.querySelectorAll('path.line').length,"
                         " dots: f.querySelectorAll('circle.dot').length, legend: f.querySelectorAll('.viz-legend .key').length,"
                         " rows: f.querySelectorAll('.viz-more tbody tr').length, title: f.querySelector('.viz-title')?.textContent,"
                         " dim: f.querySelectorAll('.mark.dim').length, vals: [...f.querySelectorAll('text.val')].map((t) => t.textContent),"
                         " inside: [...f.querySelectorAll('text.in')].map((t) => t.textContent), w: +f.dataset.w,"
                         " across: f.querySelector('svg')?.dataset.across === '1' }))")
            check("C1 six charts drawn from six ```chart blocks", len(figs) == 6, f"{len(figs)} drawn")
            if len(figs) == 6:
                bar, across, groups, stack, line, gantt = figs
                check("C2 bar: four bars, three grey and the highlighted one in colour, every value written",
                      bar["marks"] == 4 and bar["dim"] == 3 and bar["vals"] == ["499,500회", "250,000회", "8,700회", "11,000회"],
                      json.dumps(bar, ensure_ascii=False))
                check("C3 names too long to sit under their columns turn the bars across, each with its value at the end",
                      across["across"] is True and across["marks"] == 6 and bar["across"] is False
                      and across["vals"] == ["12 ms", "38 ms", "182 ms", "141 ms", "236 ms", "71 ms"],
                      json.dumps(across, ensure_ascii=False))
                check("C4 two series side by side: six bars and a legend of two, no values on grouped bars",
                      groups["marks"] == 6 and groups["legend"] == 2 and not groups["vals"], json.dumps(groups, ensure_ascii=False))
                check("C5 a stack: nine segments, a legend of three, the three totals over the columns",
                      stack["marks"] == 9 and stack["legend"] == 3 and stack["vals"] == ["120 ms", "97 ms", "168 ms"],
                      json.dumps(stack, ensure_ascii=False))
                check("C6 lines: two lines, two end dots, a legend, the ends labelled",
                      line["lines"] == 2 and line["dots"] == 2 and line["legend"] == 2 and len(line["vals"]) == 2,
                      json.dumps(line, ensure_ascii=False))
                check("C7 a timetable: six blocks with their names inside, no legend needed",
                      gantt["marks"] == 6 and gantt["inside"] == ["P1", "P2", "P3", "P1", "P2", "P1"] and gantt["legend"] == 0,
                      json.dumps(gantt, ensure_ascii=False))
                check("C8 every chart has its numbers in a table under it",
                      [f["rows"] for f in figs] == [4, 6, 3, 3, 4, 6], str([f["rows"] for f in figs]))
            # the same block is drawn again at a new width rather than stretched
            w0 = figs[0]["w"] if figs else 0
            pn.pg.set_viewport_size({"width": 560, "height": 1000})
            pn.pg.wait_for_timeout(500)
            w1, room = pn.ev("() => { const f = document.querySelector('.entry figure.viz-chart');"
                             " return [+f.dataset.w, Math.floor(f.querySelector('.viz-plot').clientWidth)]; }")
            over = pn.ev(OVERLAPS)
            check("C10 no two words of a chart overlap (1100 px)", not over, "; ".join(over)[:300])
            check("C9 a narrower window draws the chart again, at the width it has now",
                  w0 and w1 != w0 and abs(w1 - room) < 4, f"{w0} -> {w1}, room {room}")
            pn.pg.set_viewport_size({"width": 1100, "height": 1000})
            pn.pg.wait_for_timeout(400)
            # readability marks
            marks = pn.ev("() => ({ lead: [...document.querySelectorAll('.entry .md p.lead')].map((p) => p.textContent),"
                          " num: [...document.querySelectorAll('.entry .md > .tablewrap td.num')].map((c) => c.textContent),"
                          " notNum: [...document.querySelectorAll('.entry .md > .tablewrap td:not(.num)')].map((c) => c.textContent),"
                          " size: getComputedStyle(document.querySelector('.entry .md p:not(.para-head)')).fontSize,"
                          " h2: getComputedStyle(document.querySelector('.entry .md h2')).color,"
                          " strong: getComputedStyle(document.querySelector('.entry .md p:not(.lead) strong')).color,"
                          " ink: getComputedStyle(document.querySelector('.entry .md p:not(.lead)')).color,"
                          " kind: getComputedStyle(document.querySelector('.entry')).getPropertyValue('--t').trim() })")
            check("R1 a paragraph that is only a bold line is marked .lead", marks["lead"] == ["1. 횟수를 센다"], str(marks["lead"]))
            check("R2 the number column is .num, the name and complexity columns are not",
                  marks["num"] == ["499,500", "8,700"] and "O(n^2)" in marks["notNum"] and "버블" in marks["notNum"],
                  json.dumps(marks, ensure_ascii=False))
            check("R3 the answer body is 16px", marks["size"] == "16px", marks["size"])
            check("R4 headings are in the ink for every kind: a page with each in the red pen was all red",
                  marks["h2"] == marks["ink"], json.dumps(marks, ensure_ascii=False))
            for theme in ("light", "dark"):
                pn.ev("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
                pn.pg.wait_for_timeout(200)
                pn.pg.locator(".entry").last.screenshot(path=str(SHOTS / f"charts-{theme}.png"))
            errors.extend(pn.errors)
            pn.close()

        def broken():
            pn = new()
            pn.up()
            pn.push(pr.start(2), pr.done(2, BROKEN))
            wait_for(pn, "() => document.querySelectorAll('.entry .viz-note').length >= 4")
            got = pn.ev("() => ({ notes: [...document.querySelectorAll('.entry .viz-note')].map((n) => n.textContent),"
                        " codes: [...document.querySelectorAll('.entry pre .codebar .lang')].map((l) => l.textContent),"
                        " figs: document.querySelectorAll('.entry figure.viz').length,"
                        " text: document.querySelector('.entry [data-body]').textContent })")
            check("B1 four blocks that cannot be drawn stay code blocks, named for what they are",
                  [c.split(". ", 1)[-1] for c in got["codes"]] == ["그림 데이터", "그림 데이터", "그림 데이터", "그림(mermaid)"] and got["figs"] == 0,
                  json.dumps(got["codes"], ensure_ascii=False))
            check("B2 each says why over it (count, JSON, kind, mermaid)",
                  len(got["notes"]) == 4 and "값 개수(3)" in got["notes"][0] and "JSON" in got["notes"][1]
                  and "pie" in got["notes"][2] and "그림 문법" in got["notes"][3], json.dumps(got["notes"], ensure_ascii=False))
            check("B3 the text around them is all still there", "앞 글." in got["text"] and "뒤 글." in got["text"])
            errors.extend(pn.errors)
            pn.close()

        def evil():
            pn = new()
            pn.up()
            pn.push(pr.start(3), pr.done(3, EVIL))
            wait_for(pn, "() => document.querySelector('.entry figure.viz-diagram-fig img')"
                         " || document.querySelectorAll('.entry .viz-note').length")
            pn.pg.wait_for_timeout(600)
            got = pn.ev("() => ({ pwned: window.__pwned ?? null,"
                        " injected: document.querySelectorAll('.entry svg img, .entry svg script, .entry svg svg, .entry .viz-legend b, .entry figure b:not(.viz-title > b)').length,"
                        " title: document.querySelector('.entry .viz-title')?.textContent,"
                        " img: !!document.querySelector('.entry figure.viz-diagram-fig img'),"
                        " stray: document.querySelectorAll('body > [id^=dsn-diagram], body > [id^=sn-diagram]').length })")
            check("X1 nothing in a spec or a diagram ran", got["pwned"] is None, str(got["pwned"]))
            check("X2 the chart's words are text: no element came out of them", got["injected"] == 0, str(got["injected"]))
            check("X3 a title with markup in it is shown as the characters it is", "<img src=x" in (got["title"] or ""),
                  str(got["title"]))
            check("X4 the diagram with links and markup in it is shown as an inert image", got["img"], json.dumps(got))
            check("X5 mermaid left nothing behind in the page", got["stray"] == 0, str(got["stray"]))
            errors.extend(pn.errors)
            pn.close()

        def diagrams():
            pn = new(theme="light")
            pn.up()
            pn.push(pr.start(4), pr.done(4, DIAGRAMS))
            ok = wait_for(pn, "() => document.querySelectorAll('.entry figure.viz-diagram-fig img').length === 2"
                              " && [...document.querySelectorAll('.entry figure.viz-diagram-fig img')].every((i) => i.complete && i.naturalWidth > 0)")
            got = pn.ev("() => [...document.querySelectorAll('.entry figure.viz-diagram-fig img')].map((i) => ({ w: i.naturalWidth, h: i.naturalHeight,"
                        " alt: i.alt, src: i.src.length }))")
            check("D1 a flowchart and a sequence diagram are drawn as images that load", ok and len(got) == 2, json.dumps(got, ensure_ascii=False))
            csp = [c for c in pn.console if "Content Security Policy" in c or "Refused" in c]
            check("D2 under the panel's CSP, with no policy refusals", not csp, "; ".join(csp)[:300])
            src0 = pn.ev("() => document.querySelector('.entry figure.viz-diagram-fig img').src")
            pn.pg.locator(".entry").last.screenshot(path=str(SHOTS / "diagrams-light.png"))
            pn.ev("() => document.documentElement.setAttribute('data-theme', 'dark')")
            wait_for(pn, f"() => {{ const i = document.querySelector('.entry figure.viz-diagram-fig img'); return i && i.src !== {json.dumps(src0)} && i.complete; }}")
            src1 = pn.ev("() => document.querySelector('.entry figure.viz-diagram-fig img')?.src")
            check("D3 switching the theme draws the diagrams again in its colours", src1 and src1 != src0)
            pn.pg.wait_for_timeout(300)
            pn.pg.locator(".entry").last.screenshot(path=str(SHOTS / "diagrams-dark.png"))
            more = pn.ev("() => document.querySelector('.entry figure.viz-diagram-fig .viz-more pre')?.textContent")
            check("D4 the diagram's text is kept under it to copy", (more or "").startswith("flowchart LR"), str(more)[:40])
            errors.extend(pn.errors)
            pn.close()

        def streaming():
            pn = new()
            pn.up()
            pn.push(pr.start(5))
            part = CHARTS[: CHARTS.index('"highlight"')]     # cut inside the first chart's JSON, as a stream would be
            pn.push({"type": "delta", "id": 5, "text": part})
            pn.pg.wait_for_timeout(300)
            mid = pn.ev("() => ({ wait: document.querySelectorAll('.entry .viz-wait').length,"
                        " json: [...document.querySelectorAll('.entry pre code')].some((c) => c.textContent.includes('\"type\"')) })")
            check("S1 while the answer is written, the chart block is a waiting line, not its JSON",
                  mid["wait"] == 1 and not mid["json"], json.dumps(mid))
            pn.push(pr.done(5, CHARTS))
            pn.pg.wait_for_timeout(400)
            end = pn.ev("() => ({ wait: document.querySelectorAll('.entry .viz-wait').length, figs: document.querySelectorAll('.entry figure.viz-chart').length })")
            check("S2 once it is done the waiting lines are charts", end["wait"] == 0 and end["figs"] == 6, json.dumps(end))
            errors.extend(pn.errors)
            pn.close()

        def tilde():
            # Claude's answer to a latency question: two ranges in one line were read as one
            # strikethrough, and everything between them came out crossed through.
            text = answer("work", "트레이스 20~50개를 열어 공통으로 긴 span 을 찾고, 위 1~4순위 중 어디인지 본다. "
                                  "지연은 100 ~ 300 ms 이다. 경로 /~user/a 는 그대로. ~~지운 말~~ 은 지운다.", "범위", "범위")
            pn = new()
            pn.up()
            pn.push(pr.start(7), pr.done(7, text))
            pn.pg.wait_for_timeout(300)
            got = pn.ev("() => { const b = document.querySelector('.entry [data-body]');"
                        " return { del: [...b.querySelectorAll('del, s')].map((d) => d.textContent), text: b.textContent }; }")
            check("T1 a range written with a tilde (20~50개, 1~4순위, 100 ~ 300) is not struck through",
                  got["del"] == ["지운 말"] and "20~50개" in got["text"] and "1~4순위" in got["text"] and "100 ~ 300" in got["text"],
                  json.dumps(got, ensure_ascii=False))
            check("T2 a tilde in a path stays as written", "/~user/a" in got["text"], got["text"][:120])
            errors.extend(pn.errors)
            pn.close()

        def prompt():
            examples = prompt_examples()
            pn = new()
            pn.up()
            pn.push(pr.start(8), pr.done(8, answer("math", "예시." + "".join(block("chart", e) for e in examples), "예", "예")))
            pn.pg.wait_for_timeout(400)
            got = pn.ev("() => ({ figs: document.querySelectorAll('.entry figure.viz-chart').length,"
                        " notes: [...document.querySelectorAll('.entry .viz-note')].map((n) => n.textContent) })")
            check("P1 every chart example in the answer prompt is a spec the panel draws (bar and gantt)",
                  len(examples) == 2 and got["figs"] == 2 and not got["notes"], json.dumps({"n": len(examples), **got}, ensure_ascii=False))
            errors.extend(pn.errors)
            pn.close()

        def negative():
            # bars below zero, up the page and along it: their numbers are written past their ends, where the
            # category names would be if no room were kept for them. The lowest value sits on the lowest tick
            # (-40), the one place a bar reaches the edge of the plot: with -30 the check passed without the fix.
            down = {"type": "bar", "title": "전월 대비 변화", "unit": "%", "x": ["A", "B", "C", "D"],
                    "series": [{"name": "변화", "values": [20, -40, 10, -20]}]}
            side = dict(down, x=["가용성 지표 첫째", "응답 시간 지표 둘째", "오류율 지표 셋째", "처리량 지표 넷째", "비용 지표 다섯째", "기타 지표 여섯째"],
                        series=[{"name": "변화", "values": [20, -40, 10, -20, 15, -5]}])
            pn = new()
            pn.up()
            pn.push(pr.start(9), pr.done(9, answer("work", block("chart", J(down)) + block("chart", J(side)), "변화", "변화")))
            pn.pg.wait_for_timeout(400)
            got = pn.ev("() => [...document.querySelectorAll('.entry figure.viz-chart')].map((f) => ({ across: f.querySelector('svg').dataset.across,"
                        " vals: [...f.querySelectorAll('text.val')].map((t) => t.textContent) }))")
            clash = pn.ev(OVERLAPS)
            check("G1 negative bars, up the page and along it, with every number written and nothing overlapping",
                  len(got) == 2 and got[0]["across"] == "0" and got[1]["across"] == "1" and len(got[0]["vals"]) == 4
                  and len(got[1]["vals"]) == 6 and not clash, json.dumps({"got": got, "clash": clash}, ensure_ascii=False))
            errors.extend(pn.errors)
            pn.close()

        def code():
            # Code read as an editor shows it: numbered lines, long lines wrapped and hanging from their
            # indentation, indent guides, and a built-in explained on hover; copying and running take the code as
            # written, without the numbers.
            src = ("from collections import deque\nimport heapq\n\ndef f(xs):\n    q = deque(xs)  # a queue\n"
                   "    h = []\n    for x in q:\n        heapq.heappush(h, x)  " + "# a long comment " * 12 + "\n"
                   "    s = 'len(xs) stays text'\n    return len(h), sorted(h)")
            text = answer("algorithm", block("python", src), "힙", "힙")
            pn = new(width=900)
            pn.up()
            pn.push(pr.start(10), pr.done(10, text))
            pn.pg.wait_for_timeout(700)
            got = pn.ev("""() => { const c = document.querySelector('.entry .md pre > code');
                const lines = c.querySelectorAll('.ln'), no = c.querySelector('.no');
                const long = [...c.querySelectorAll('.tx')].find((t) => t.textContent.includes('heappush'));
                return { lined: c.classList.contains('lined'), lines: lines.length, nums: [...c.querySelectorAll('.no')].map((n) => n.textContent).join(','),
                         select: getComputedStyle(no).userSelect, wide: c.scrollWidth > c.clientWidth + 1,
                         hang: long ? getComputedStyle(long).paddingLeft : null, rows: long ? Math.round(long.getBoundingClientRect().height / parseFloat(getComputedStyle(long).lineHeight)) : 0,
                         docs: [...c.querySelectorAll('.doc')].map((d) => d.textContent),
                         inString: [...c.querySelectorAll('.hljs-string .doc')].length }; }""")
            check("K1 numbered lines, one per line of the code, the numbers not selectable",
                  got["lined"] and got["lines"] == 10 and got["nums"] == "1,2,3,4,5,6,7,8,9,10" and got["select"] == "none", json.dumps(got))
            check("K2 a long line wraps inside the box (no sideways scroll), its rows hanging from its indentation",
                  not got["wide"] and got["rows"] >= 2 and got["hang"] and float(got["hang"][:-2]) > 0, json.dumps(got))
            check("K3 built-ins and imported names are explained, a name inside a string is not",
                  {"deque", "heapq.heappush", "len", "sorted"} <= set(got["docs"]) and got["inString"] == 0, json.dumps(got["docs"]))
            pn.pg.click(".entry .codebar .copy")
            pn.pg.wait_for_timeout(300)
            copied = pn.ev("() => navigator.clipboard.readText()")
            check("K4 copying takes the code as written, without the line numbers", copied == src, repr(copied[:80]))
            pn.pg.hover(".entry .md pre .doc >> nth=0")
            pn.pg.wait_for_timeout(600)
            tip = pn.ev("() => { const t = document.querySelector('.doc-tip'); return t && !t.hidden ? t.textContent : null; }")
            check("K5 the pointer on a built-in brings up its signature and what it does", bool(tip) and "deque" in tip, str(tip)[:120])
            # The box over a built-in explains it: it had the signature and the
            # reference's English line only. Now what it does in Korean, what goes in
            # and what comes out, and the English under them, smaller.
            box = pn.ev("""() => { const t = document.querySelector('.doc-tip'); if (!t || t.hidden) return null;
                const q = (s) => t.querySelector(s), size = (s) => q(s) ? parseFloat(getComputedStyle(q(s)).fontSize) : 0;
                return { ko: q('.doc-ko')?.textContent || '', labels: [...t.querySelectorAll('.doc-io dt')].map((d) => d.textContent),
                         io: [...t.querySelectorAll('.doc-io dd')].map((d) => d.textContent),
                         en: q('.doc-en')?.textContent || '', koSize: size('.doc-ko'), enSize: size('.doc-en'),
                         order: [...t.children].map((c) => c.className) }; }""")
            check("K6 the box says in Korean what it does, with 입력 (input) and 출력 (output), and the English under them, smaller",
                  bool(box) and any("\uac00" <= ch <= "\ud7a3" for ch in box["ko"]) and box["labels"] == ["입력", "출력"]
                  and all(box["io"]) and box["en"] and box["enSize"] < box["koSize"]
                  and box["order"] == ["doc-sig", "doc-ko", "doc-io", "doc-en"], json.dumps(box, ensure_ascii=False)[:300])
            errors.extend(pn.errors)
            pn.close()

        def frame():
            # The frame round the sheets: a page nearer black but not black, a bar that shows an edge only over the
            # thread, and a question box that floats narrower over a thread running on and rests at the thread's
            # width at the end (nothing to scroll, or scrolled to the bottom).
            def lstar(color):
                # CIE L* of an sRGB colour written #rrggbb or rgb(...)
                import re as _re
                m = _re.findall(r"[0-9a-fA-F]{2}", color[1:]) if color.startswith("#") else None
                rgb = [int(x, 16) for x in m] if m else [int(float(x)) for x in _re.findall(r"[\d.]+", color)[:3]]
                lin = [(c / 255 / 12.92) if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
                y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
                return 116 * y ** (1 / 3) - 16 if y > 216 / 24389 else y * 24389 / 27
            measure = """() => { const f = document.getElementById('askform'), r = f.getBoundingClientRect(),
                t = document.getElementById('thread').getBoundingClientRect();
                return { floating: f.classList.contains('floating'), fL: Math.round(r.left), fR: Math.round(r.right),
                         fB: Math.round(r.bottom), tL: Math.round(t.left), tR: Math.round(t.right), win: innerHeight,
                         scrolls: document.scrollingElement.scrollHeight > innerHeight + 1 }; }"""
            edge = """() => { const b = document.querySelector('header.bar');
                return { skin: document.documentElement.dataset.skin, under: b.classList.contains('under'),
                         shadow: getComputedStyle(b.querySelector('.bar-in')).boxShadow, line: getComputedStyle(b).borderBottomColor }; }"""
            pn = new(width=1440, theme="dark", height=900)
            pn.up()
            for i in range(3):
                pn.push(pr.start(30 + i), pr.done(30 + i, pr.bench("exam_lms_essay")))
            pn.pg.wait_for_timeout(700)
            paper = pn.ev("() => getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()")
            # 3: Ribbon's night, the chosen design; "이전" keeps the older 8
            check("F1 the dark page is nearer black than Slack's pane (L* 10.6) and not black: L* 3 to 10",
                  3 <= lstar(paper) <= 10, f"{paper} L*={lstar(paper):.1f}")
            pn.pg.evaluate("() => window.scrollTo(0, 0)")
            pn.pg.wait_for_timeout(400)
            top = pn.ev(edge)
            pn.pg.evaluate("() => window.scrollTo(0, 700)")
            pn.pg.wait_for_timeout(400)
            down = pn.ev(edge)
            clear = lambda c: c.replace(" ", "") in ("rgba(0,0,0,0)", "transparent")
            if top["skin"] == "classic":
                check("F2 the bar has no lower edge at the top of the page and shows one once the thread scrolls under it",
                      not top["under"] and clear(top["line"]) and down["under"] and not clear(down["line"]), f"{top} {down}")
            else:   # New's bar is a floating pill: it lifts further off the page once the thread runs under it
                check("F2 the pill lifts once the thread scrolls under it",
                      not top["under"] and down["under"] and top["shadow"] != down["shadow"], f"{top} {down}")
            pn.pg.evaluate("() => window.scrollTo(0, 500)")
            pn.pg.wait_for_timeout(600)
            mid = pn.ev(measure)
            pn.pg.evaluate("() => window.scrollTo(0, document.scrollingElement.scrollHeight)")
            pn.pg.wait_for_timeout(600)
            end = pn.ev(measure)
            # Floating, it is as wide as the bands over the thread, 16 px in from each side (it was made full width once, and that
            # was rolled back)
            narrower = (mid["fR"] - mid["fL"]) < (mid["tR"] - mid["tL"]) - 16
            as_bands = abs((mid["tR"] - mid["tL"]) - (mid["fR"] - mid["fL"]) - 32) <= 2
            check("F3 while the thread runs on below the window the question box floats: as wide as the bands, centred, above the edge" if classic_skin(pn) else
                  "F3 while the thread runs on below the window the question box floats: narrower, centred, above the edge",
                  mid["floating"] and (as_bands if classic_skin(pn) else narrower)
                  and abs((mid["fL"] - mid["tL"]) - (mid["tR"] - mid["fR"])) <= 2 and mid["win"] - mid["fB"] >= 12, json.dumps(mid))
            check("F4 scrolled to the bottom it rests at the thread's width, edge to edge with the sheet",
                  not end["floating"] and abs(end["fL"] - end["tL"]) <= 1 and abs(end["fR"] - end["tR"]) <= 1, json.dumps(end))
            errors.extend(pn.errors)
            pn.close()
            pn = new(width=1440, theme="light", height=1700)   # one short answer in a tall window: nothing to scroll
            pn.up()
            pn.push(pr.start(40), pr.done(40, pr.bench("calc_mcq_cache")))
            pn.pg.wait_for_timeout(700)
            one = pn.ev(measure)
            check("F5 with nothing to scroll it rests at the thread's width",
                  not one["scrolls"] and not one["floating"] and abs(one["fL"] - one["tL"]) <= 1 and abs(one["fR"] - one["tR"]) <= 1,
                  json.dumps(one))
            errors.extend(pn.errors)
            pn.close()

        def narrow():
            for theme in ("light", "dark"):
                pn = new(width=420, theme=theme)
                pn.up()
                pn.push(pr.start(6), pr.done(6, CHARTS))
                pn.pg.wait_for_timeout(500)
                over = pn.ev("() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
                check(f"N1 at 420px ({theme}) the charts do not push the page sideways", over <= 0, f"{over}px")
                clash = pn.ev(OVERLAPS)
                check(f"N2 at 420px ({theme}) no two words of a chart overlap", not clash, "; ".join(clash)[:300])
                pn.pg.locator(".entry").last.screenshot(path=str(SHOTS / f"charts-420-{theme}.png"))
                errors.extend(pn.errors)
                pn.close()

        for name, fn in (("charts", charts), ("broken", broken), ("evil", evil), ("diagrams", diagrams),
                         ("streaming", streaming), ("tilde", tilde), ("prompt", prompt), ("negative", negative), ("code", code), ("frame", frame),
                         ("narrow", narrow)):
            pr.run(name, fn)
        br.close()
    srv.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    check("no script errors on any page", not errors, "; ".join(errors)[:300])
    support.skip_line()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
