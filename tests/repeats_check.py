"""A problem seen again is not solved again (server/repeats.py, design note 88), and an agent at its usage limit rests
until it says it comes back (pipeline.limit_until, Spend.limited).

In real use a knight-move problem was solved three times in nine minutes and a multiplication twice: scrolled or come
back to, the problem stood somewhere else on the screen, and the change watch only knew that the old box had changed.
In the same quarter of an hour Claude Code was asked 15 times after it had said "You've hit your weekly limit".

The screens here are drawn at 4K with real text and brought to 1600 wide as the server brings them, so a scroll lands
the words between the pixels of the smaller picture as it does in use.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/repeats_check.py
"""
import asyncio
import base64
import io
import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))   # the repository, one level up

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from server import repeats as R  # noqa: E402
from server.analyzer import FastResult, make_engines  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.pipeline import Hooks, Pipeline, Repeat, limit_until  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def font(size: int):
    """A real typeface where there is one (DejaVu on Linux), else Pillow's own at that size."""
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


FONT = font(30)
TOP, LINE, LINES = 300, 64, 14        # where the statement starts on the 4K screen, its line pitch, its lines


def page(seed: int, lines: int = LINES) -> Image.Image:
    """A 4K coding-test screen: the statement in words on the left, a dark editor on the right (the layout that made
    two unrelated screens look alike before the detail filter)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (3840, 2160), (246, 246, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([2000, 0, 3840, 2160], fill=(30, 33, 40))              # the editor
    d.rectangle([0, 0, 3840, 120], fill=(222, 225, 230))               # the browser's bar, the same on every screen
    d.text((60, 40), "programmers  |  coding test practice", fill=(60, 60, 60), font=FONT)
    for i in range(lines):
        words = " ".join("".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(2, 9)))
                         for _ in range(rnd.randint(6, 11)))
        d.text((120, TOP + i * LINE), words, fill=(25, 25, 25), font=FONT)
    for i in range(20):                                                 # some code in the editor
        d.text((2100, 200 + i * 56), f"line_{i} = solve({i}, k)", fill=(200, 210, 220), font=FONT)
    return img


def sibling(seed: int, change: dict | None = None) -> Image.Image:
    """A problem whose every line ends in a two-digit figure; `change` gives some lines another figure, or (None) other words."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (3840, 2160), (246, 246, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([2000, 0, 3840, 2160], fill=(30, 33, 40))
    d.rectangle([0, 0, 3840, 120], fill=(222, 225, 230))
    for i in range(LINES):
        words = " ".join("".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(2, 8))) for _ in range(rnd.randint(6, 9)))
        figure = rnd.randint(20, 39)                       # never 11, 41 or 77: a change is always a change
        if change and i in change:
            if change[i] is None:
                words, figure = "which one of the following values is the largest here", 7
            else:
                figure = change[i]
        d.text((120, TOP + i * LINE), f"{words} {figure}", fill=(25, 25, 25), font=FONT)
    return img


def scrolled(img: Image.Image, dy: int) -> Image.Image:
    """The page scrolled down by dy pixels: the words move up under a browser bar that stays where it is."""
    out = img.copy()
    body = img.crop((0, 120 + dy, 3840, 2160))
    out.paste(Image.new("RGB", (3840, 2040), (246, 246, 246)), (0, 120))
    out.paste(body, (0, 120))
    out.paste(img.crop((2000, 120, 3840, 2160)), (2000, 120))           # the editor is a pane of its own: it stays
    return out


def shot(img: Image.Image) -> str:
    """What the pipeline gets from a screen: brought to 1600 wide (max_image_width), a base64 PNG."""
    small = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def box(dy: int = 0, wider: float = 0.0, lines: int = LINES) -> tuple:
    """The statement's box in screen fractions, as the first pass would give it, scrolled by dy and drawn wider."""
    x0, x1 = 80 / 3840 - wider, 1950 / 3840 + wider
    y0, y1 = (TOP - 30 - dy) / 2160 - wider, (TOP + lines * LINE + 10 - dy) / 2160 + wider
    return (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))


VIEW = (0.0, 0.0, 1.0, 1.0)


def pictures():
    print("\n[a problem seen again, by its picture]")
    first, other = page(1), page(2)
    rec = R.Recent()
    rec.add(41, shot(first), VIEW, box(), "algorithm")
    for dy in (37, 121, 300):
        # A box starts under the browser's bar: at 300 px the first lines have gone under it and it starts at the words
        where = box(dy)
        where = (where[0], max(where[1], 130 / 2160), where[2], where[3])
        got = rec.match(shot(scrolled(first, dy)), VIEW, where, "algorithm")
        check(f"scrolled {dy} px, it is found as the problem answered before", got is not None and got[0] == 41, str(got))
    got = rec.match(shot(first), VIEW, box(wider=0.03), "algorithm")
    check("a box drawn wider the second time still meets the first", got is not None and got[0] == 41, str(got))
    # The next problem of a template differs in a number or a line: the bands alone called these the same at 0.99
    for seed in (1, 5, 9):
        base_pic = sibling(seed)
        near = R.Recent()
        near.add(7, shot(base_pic), VIEW, box(), "algorithm")
        check(f"seed {seed}: the same screen again is the same problem", near.match(shot(base_pic), VIEW, box(), "algorithm") is not None)
        for dy in (37, 121):
            got = near.match(shot(scrolled(base_pic, dy)), VIEW, box(dy), "algorithm")
            check(f"seed {seed}: scrolled {dy} px it is still the same problem", got is not None, str(got))
        for name, change in (("one number", {5: "77"}), ("three numbers", {2: "11", 6: "11", 9: "11"}), ("the question line", {13: None}), ("another figure", {9: "41"})):
            got = near.match(shot(sibling(seed, change)), VIEW, box(), "algorithm")
            check(f"seed {seed}: {name} changed is a new problem", got is None, str(got))
            got = near.match(shot(scrolled(sibling(seed, change), 37)), VIEW, box(37), "algorithm")
            check(f"seed {seed}: {name} changed and scrolled is a new problem", got is None, str(got))
    frame = shot(other)       # outside the clock: drawing and encoding the picture here is no part of a look, and on a busy runner it was most of it
    t = time.time()
    got = rec.match(frame, VIEW, box(), "algorithm")
    took = time.time() - t
    print(f"  a look at a new problem: {took:.2f} s")
    check("another problem in the same layout, under the same browser bar, is a new problem", got is None, str(got))
    check("looking costs well under a second on a 4K screen", took < 1.0, f"{took:.2f} s")
    check("coding and algorithm count as one kind (the first pass calls the same problem either)",
          rec.match(shot(first), VIEW, box(), "coding") is not None)
    check("what the first pass calls it is no test: the same picture read as another kind is the same problem",
          (rec.match(shot(first), VIEW, box(), "other") or (0,))[0] == 41)
    words = "정수 배열 nums 가 주어질 때 합이 target 인 두 수의 인덱스를 돌려주세요. 길이는 2 이상 10000 이하이고 답은 하나뿐입니다. " * 2
    rec.add_words(41, words)
    check("the same words read again, a little differently, are the same problem",
          (rec.match_words(words.replace("돌려주세요", "반환하세요").replace("하나뿐", "하나")) or (0,))[0] == 41)
    check("the same template with other numbers is a new problem", rec.match_words(words.replace("10000", "500")) is None)
    # Two problems that hardly differ in their letters are two problems
    base = "다음 값을 계산한 결과로 알맞은 것을 고르세요. 각 항은 차례대로 더하거나 빼며 괄호는 없습니다. 답은 정수입니다. "
    for name, x, y in (("an operator", base + "128 + 57 + 12 - 9", base + "128 - 57 - 12 + 9"),
                       ("a comparison", base + "nums[i] < nums[j]", base + "nums[i] > nums[j]"),
                       ("a negation", base + "옳은 것은 무엇인가", base + "옳지 않은 것은 무엇인가"),
                       ("minimum and maximum", base + "the minimum number of coins", base + "the maximum number of coins"),
                       ("the order of the numbers", base + "choose 3 of 10", base + "choose 10 of 3"),
                       ("one number of ten", base + "1 2 3 4 5 6 7 8 9 10", base + "1 2 3 4 5 6 7 8 9 11"),
                       ("another question on one passage", base + "what is the main idea", base + "what is the tone")):
        check(f"{name} that differs makes a new problem", R.same_words(x, y) == 0.0, str(R.same_words(x, y)))
    check("words too short to tell by say nothing", R.same_words("두 수의 합", "두 수의 합") == 0.0)
    check("other words are a new problem", rec.match_words("문자열 s 를 받아 가장 긴 회문 부분 문자열을 돌려주세요. 길이는 2 이상 10000 이하입니다. 답이 여럿이면 아무거나 돌려줍니다. " * 2) is None)
    check("a one-line box decides nothing (too little to tell by), so it is solved as before",
          R.Recent().match(shot(first), VIEW, box(lines=1), "algorithm") is None
          and (lambda r: (r.add(1, shot(first), VIEW, box(lines=1), "algorithm"), r)[1])(R.Recent())
          .match(shot(first), VIEW, box(lines=1), "algorithm") is None)
    late = time.time() + R.TTL + 1
    check("a problem answered longer ago than the memory lasts is new again",
          rec.match(shot(first), VIEW, box(), "algorithm", now=late) is None)
    keep = R.Recent()
    for card in range(1, R.KEEP + 2):
        keep.add(card, shot(page(100 + card)), VIEW, box(), "algorithm")
    check(f"only the last {R.KEEP} problems are kept", [s.card for s in keep.items] == list(range(2, R.KEEP + 2)),
          str([s.card for s in keep.items]))


async def _none(*a, **k):
    return None


async def _yes(*a, **k):
    return True


class Screen:
    """A screen as prepare_frame makes one (the fields the pipeline reads)."""

    def __init__(self, img: Image.Image):
        self.model_b64 = shot(img)
        self.full_png = base64.b64decode(self.model_b64)
        self.thumb_url = "data:image/png;base64," + self.model_b64
        self.ts, self.width, self.height = 0.0, 3840, 2160
        self.extra_b64, self.windows, self.ocr_lines, self.sig = [], None, None, b""
        self.model_box = VIEW
        self.faces = 0


def make_pipeline(notices):
    engines = make_engines(CONFIG)   # MockLocal and the mock agent

    async def notice(text):
        notices.append(text)
    hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=notice, stage=lambda *a, **k: _none(),
                  confirm=_yes, agent_failed=_none)
    return Pipeline(engines, hooks), engines


async def in_the_pipeline():
    print("\n[in the pipeline: before anything is spent on it]")
    saved = dict(SETTINGS.values)
    notices = []
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               dedupe=True, roi=True)
        pipe, eng = make_pipeline(notices)
        b = box()
        # the first pass: a hard problem, its box on the local model's 0-1000 grid (MockLocal's region_scale)
        head = "TYPE: algorithm\nROUTE: deep\nREGION: " + " ".join(str(round(v * 1000)) for v in b) + "\n"

        async def deep(*a, **k):
            return FastResult(text=None, head=head, type="algorithm", route="deep")
        eng.local.fast = deep
        asked = []
        real_run = eng.agent.run

        async def agent_run(images, text, on_delta, web=False):
            asked.append(text)
            return await real_run(images, text, on_delta)
        eng.agent.run = agent_run
        first = Screen(page(1))
        pipe.recent.add(41, first.model_b64, VIEW, b, "algorithm")       # as app.py keeps an answer's picture
        try:
            await pipe.solve(42, Screen(scrolled(page(1), 121)), "", False, _none)
            raised = None
        except Repeat as again:
            raised = again
        check("the problem of answer #41, scrolled, ends as a repeat before the agent is asked",
              raised is not None and raised.card == 41 and not asked, f"{raised!r} asked={len(asked)}")
        out = await pipe.solve(43, Screen(scrolled(page(1), 121)), "", False, _none, by_user=True)
        check("Reanalyze solves it all the same", out is not None and len(asked) == 1, f"asked={len(asked)}")
        paged = Screen(scrolled(page(1), 121))
        paged.extra_b64 = [shot(page(1))]          # the problem scrolled together: pages beside the screen
        before = len(asked)
        out = await pipe.solve(46, paged, "", False, _none)
        check("with pages scrolled together it is solved (they hold what was not seen before)",
              out is not None and len(asked) == before + 1, f"asked={len(asked) - before}")
        SETTINGS.values["dedupe"] = False
        out = await pipe.solve(44, Screen(page(1)), "", False, _none)
        check("with Do not solve the same problem again off, it is solved", out is not None and len(asked) == 3)
        SETTINGS.values["dedupe"] = True
        out = await pipe.solve(45, Screen(page(2)), "", False, _none)
        check("another problem is solved", out is not None and len(asked) == 4)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def seen_again_by_words():
    print("\n[a problem with no box to go on, known by the words that would go to the agent]")
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="text", agent_confirm=False, dedupe=True,
                               extract=True)
        pipe, eng = make_pipeline([])

        async def no_box(*a, **k):      # as the small model on a busy GPU once read it: a kind, no REGION
            return FastResult(text=None, head="TYPE: other\n", type="other", route="", slow=False)
        eng.local.fast = no_box
        words = "1. 스케줄러는 어떻게 노드를 고르나요? 2. 컨테이너가 죽으면 무엇이 재시작되나요? 3. ConfigMap 을 바꾸면 무엇이 일어나나요? 4. 파드를 지우면 어떻게 되나요?"

        async def extract(images=(), speech=""):
            return words
        eng.local.extract = extract
        asked = []
        real_run = eng.agent.run

        async def agent_run(images, text, on_delta, web=False):
            asked.append(text)
            return await real_run(images, text, on_delta)
        eng.agent.run = agent_run
        out = await pipe.solve(71, Screen(page(6)), "", False, _none)
        # what the worker does once the card is done (app._run_analysis, beside its picture): the words it went out in come
        # back on the Outcome and are kept then, so a card cancelled before its end stands for nothing
        check("the words a problem went out in come back with its answer", out.words == words, out.words)
        pipe.recent.add_words(71, out.words)
        try:
            await pipe.solve(72, Screen(page(7)), "", False, _none)
            raised = None
        except Repeat as again:
            raised = again
        check("the second reading of the same words ends as a repeat of the first, the agent asked once",
              raised is not None and raised.card == 71 and len(asked) == 1, f"{raised!r} asked={len(asked)}")
        await pipe.solve(73, Screen(page(7)), "", False, _none, by_user=True)
        check("Reanalyze sends it all the same", len(asked) == 2, f"asked={len(asked)}")
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def usage_limit():
    print("\n[an agent at its usage limit rests until it comes back]")
    now = time.mktime((2026, 11, 1, 6, 1, 23, 0, 0, -1))
    said = {
        "claude CLI: You've hit your weekly limit · resets Nov 3, 3am (Asia/Seoul)": "11-03 03:00",
        "You've hit your usage limit. Try again in 2 hours 13 minutes.": "11-01 08:14",
        "Limit reached, resets 5pm": "11-01 17:00",
        "You've hit your session limit · resets 4am": "11-02 04:00",      # an hour gone by today: tomorrow's
        "HTTP 429 Too Many Requests": "11-01 06:03",                       # a rate limit: two minutes
    }
    for text, want in said.items():
        got = limit_until(text, now)
        check(f"{text[:44]!r} rests until {want}", got is not None and time.strftime("%m-%d %H:%M",
              time.localtime(got)) == want, str(got and time.strftime("%m-%d %H:%M", time.localtime(got))))
    check("any other error is not a limit", limit_until("All connection attempts failed", now) is None)
    saved = dict(SETTINGS.values)
    notices = []
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               dedupe=True, roi=True)
        pipe, eng = make_pipeline(notices)

        async def deep(*a, **k):
            return FastResult(text=None, head="TYPE: algorithm\nROUTE: deep\nREGION: 20 120 500 560\n",
                              type="algorithm", route="deep")
        eng.local.fast = deep
        calls = []

        async def limited(images, text, on_delta, web=False):
            calls.append(1)
            raise RuntimeError("claude CLI: You've hit your weekly limit · resets Nov 3, 3am (Asia/Seoul)")
        eng.agent.run = limited
        out = await pipe.solve(51, Screen(page(3)), "", False, _none)
        check("the limit's answer comes from this PC's model", out is not None and out.engine == "local", out and out.engine)
        check("the panel is told until when", any("사용 한도" in n for n in notices), str(notices))
        await pipe.solve(52, Screen(page(4)), "", False, _none)
        await pipe.solve(53, Screen(page(5)), "", False, _none, by_user=True)
        check("the next problems, asked for or not, do not go to it while it rests", len(calls) == 1, f"calls={len(calls)}")
        check("the agent is out of the engines meanwhile", pipe._agent() is None)
        SETTINGS.values.update(local_llm=False, local_fallback=False)
        check("with this PC's model off (and not standing in), the panel's card says why nothing is solved",
              "사용 한도" in pipe.auto_blocked(), pipe.auto_blocked())
        SETTINGS.values["local_fallback"] = True
        check("...standing in for the agent (design 89), the switched-off model answers, and the card says nothing",
              pipe.standing_in() == "limit" and pipe._local() is eng.local and pipe.auto_blocked() == "",
              pipe.auto_blocked())
        SETTINGS.values["local_llm"] = True
        pipe.spend.limit_until = time.time() - 1                         # the time it gave has come
        check("when its time comes it is asked again", pipe._agent() is eng.agent)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


def main():
    pictures()
    asyncio.run(in_the_pipeline())
    asyncio.run(seen_again_by_words())
    asyncio.run(usage_limit())
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
