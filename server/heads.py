"""The head lines every answer starts with (`TYPE:`, `ANSWER:`, `REGION:`), read the same way by the
server, the pipeline and the panel (panel/app.js has the JavaScript twin of head_start)."""
from __future__ import annotations

import json
import re

HEAD_LINE = re.compile(r"[^\S\n]*TYPE:[^\S\n]*[a-zA-Z_]+")
HEAD_RE = re.compile(r"[^\S\n]*TYPE:[^\S\n]*([a-zA-Z_]+)[^\n]*(?:\n[^\S\n]*ANSWER:[^\S\n]*([^\n]*))?")
# the panel's twin of this lives in panel/app.js (splitHead)


def head_start(text: str) -> int | None:
    """Where the head (the `TYPE:` line) starts: the first line, or after a short preamble the model
    sometimes adds although the prompt forbids it (at most three lines). A `TYPE:` after a code
    block, or further down, is content (YAML `type: none`, code), not the head: None then."""
    off = seen = 0
    for line in text.split("\n"):
        if line.strip():
            if line.lstrip().startswith("```"):
                return None
            if HEAD_LINE.match(line):
                return off
            seen += 1
            if seen >= 4:
                return None
        off += len(line) + 1
    return None


ASKED_RE = re.compile(r"^[^\S\n]*ASKED:[^\S\n]*([^\n]*)", re.M)


def asked_of(text: str) -> str:
    """The `ASKED:` line: what a problem that is not in Korean asks, in one Korean line. "" when there is
    none, which is what a Korean problem gives."""
    i = head_start(text)
    head = "\n".join((text[i:] if i is not None else text.lstrip()).split("\n")[:6])
    m = ASKED_RE.search(head)
    return (m.group(1).strip()[:200] if m else "")


def head_of(text: str) -> tuple[str, str]:
    """(type, answer line) of a result."""
    i = head_start(text)
    m = HEAD_RE.match(text, i) if i is not None else None
    return (m.group(1).lower(), (m.group(2) or "").strip()[:120]) if m else ("", "")


# The kinds a head names: the ones solved (settings.SOLVE_TYPES), a follow-up's and nothing to solve. Only a block naming one
# of these is a head written as JSON; any other JSON at the top of an answer is the answer's own.
HEAD_KINDS = ("mcq", "short", "essay", "coding", "algorithm", "work", "math", "diagram", "other", "followup", "none")
# A fenced block that opens the answer and holds one JSON object, the fence's language json or none
JSON_HEAD_RE = re.compile(r"\s*```[^\S\n]*(?:json)?[^\S\n]*\n[^\S\n]*(\{.*?\})[^\S\n]*\n[^\S\n]*```[^\S\n]*(?:\n|\Z)",
                          re.S | re.I)


def json_head(text: str) -> str:
    """The answer with a head written as a JSON block in front of it (the e4b's thinking pass did, once in twelve on the
    test PC: ```json {"type": "essay", "answer": ..., "region": null, "asked": ...}```) put back as the head lines every
    reader takes. Read as it came, it had no TYPE line, and the card showed no kind and no answer line, with the block on
    top. Any other text comes back as it is: one with a head already, a block that is not one JSON object, one whose
    `type` is not a kind a head names, or one with no `answer` or `asked` beside it."""
    if not text or head_start(text) is not None:   # a head of its own already: read as it is
        return text
    m = JSON_HEAD_RE.match(text)                     # a fenced object at the very top, or nothing to do
    if not m:
        return text
    try:
        head = json.loads(m.group(1))
    except ValueError:                               # cut short, or not JSON at all: the answer's own block
        return text
    kind = head.get("type") if isinstance(head, dict) else None
    # and a head's own lines beside it: an example the answer opens with may well have a `type` of its own
    if not isinstance(kind, str) or kind.strip().lower() not in HEAD_KINDS or not ({"answer", "asked"} & set(head)):
        return text

    def line(value) -> str:     # one line of a value: a number as written, text with its breaks closed up
        return " ".join(str(value).split()) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""
    lines = [f"TYPE: {kind.strip().lower()}"]          # the head's lines in the order the prompt asks for them
    if line(head.get("answer")):
        lines.append("ANSWER: " + line(head["answer"]))
    box = head.get("region")                           # null for a spoken problem; four numbers where it was seen
    if (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
        lines.append("REGION: " + " ".join(f"{v:g}" for v in box))
    if line(head.get("asked")):
        lines.append("ASKED: " + line(head["asked"]))
    rest = text[m.end():].lstrip("\n")                # the answer under the block, as the model wrote it
    return "\n".join(lines) + ("\n" + rest if rest else "")


_NUM = r"(-?\d+(?:\.\d+)?)"
# Brackets and parentheses are tolerated: local models write "REGION: [52, 96, 592, 278]".
REGION_RE = re.compile(rf"^\s*REGION:\s*[\[(]?\s*{_NUM}[\s,]+{_NUM}[\s,]+{_NUM}[\s,]+{_NUM}", re.M | re.I)


# How many times taller than wide a box may stand before it is taken as written y first. A problem is lines of writing, so its
# box is wide, or not much taller than wide: the tallest whole problem of the known-answer set stands 1.07 times its width, and
# a problem in a pane down the side of the screen about 1.5. The local model, asked for x0 y0 x1 y1, now and then writes y
# first, Gemma's own order, and a wide problem then reads as a strip standing on end somewhere else on the screen. At this
# height no box that held its problem was turned, in five runs of the first pass (docs/DECISIONS.md, note 107).
TALL_BOX = 2.0


def region_box(text: str, scale: float = 100, aspect: float = 0.0) -> tuple[float, float, float, float] | None:
    """The REGION line as fractions of the image. None when missing, malformed, out of range or too small to trust.
    `aspect`: the height over the width of the image it was written on, when that is known, which tells a box written y
    first by its shape (TALL_BOX). With none, the line is read exactly as the model gave it."""
    i = head_start(text)
    head = text[i:] if i is not None else text.lstrip()
    m = REGION_RE.search("\n".join(head.split("\n")[:6]))
    if not m:
        return None
    try:
        vals = [float(v) for v in m.groups()]
    except ValueError:   # the pattern only takes numbers; never let a REGION line lose an answer
        return None
    if any(v < -1 or v > scale * 1.01 for v in vals):
        return None   # not percentages (seen: "21 85 99 150" for a log at the top): don't trust it
    x0, y0, x1, y1 = (min(1.0, max(0.0, v / scale)) for v in vals)
    if aspect and (y1 - y0) * aspect > TALL_BOX * (x1 - x0):
        x0, y0, x1, y1 = y0, x0, y1, x1   # read as written it holds the wrong part of the screen
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:   # a one-line problem is only 2-3% tall
        return None
    return (x0, y0, x1, y1)


def parse_region(text: str, scale: float = 100, aspect: float = 0.0) -> tuple[float, float, float, float] | None:
    """The answer's REGION line (percent of the screen, or the 0-1000 grid at scale=1000) as
    fractions, pulled in a little at every edge: windows are often placed right against the
    problem, and a box that reaches into the neighbour would re-run the problem whenever that window
    scrolls. A change to the problem still shows inside. This is the box duplicate detection
    watches; cropping uses region_box with a margin instead."""
    box = region_box(text, scale, aspect)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    # ~1.5 signature pixels (the high-pass blur spreads a neighbour's edge about that far),
    # but never more than a fifth of the box.
    ix, iy = min(0.01, 0.2 * (x1 - x0)), min(0.01, 0.2 * (y1 - y0))
    return (x0 + ix, y0 + iy, x1 - ix, y1 - iy)


def within(box, outer) -> tuple[float, float, float, float]:
    """A box given in fractions of `outer` (a sub-rectangle of the screen), as fractions of the
    screen: the model saw a crop, the server keeps screen coordinates."""
    ox0, oy0, ox1, oy1 = outer
    w, h = ox1 - ox0, oy1 - oy0
    return (ox0 + box[0] * w, oy0 + box[1] * h, ox0 + box[2] * w, oy0 + box[3] * h)
