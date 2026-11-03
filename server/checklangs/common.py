"""What the harnesses of every language share: where a name is defined in source, how to read past
comments and literals, and the marks a run's output carries. Each language's own harness is beside this
(checklangs/python.py and so on); what they are for is in server/codecheck.py."""
from __future__ import annotations

import math
import re


CASE_MARK = "@@CASE"


MAX_CASES = 8   # at most the runner's MAX_STDINS (docker/runner.py): a program's examples go in one request


IDENT = re.compile(r"[A-Za-z_]\w*", re.A)


SIGNALS = {6: "abort", 8: "arithmetic error", 9: "killed", 11: "segmentation fault", 24: "CPU time limit",
           25: "output limit"}


def _inside_a_function(masked: str, pos: int) -> bool:
    """Whether what is at `pos` in Python source sits in another function's body (a comparator written inside
    the answer is not the answer): the block it is in opens with `def`, not with `class` or nothing."""
    line = masked.rfind("\n", 0, pos) + 1
    text = masked[line:masked.find("\n", line) if masked.find("\n", line) >= 0 else len(masked)]
    indent = len(text) - len(text.lstrip())
    if not indent:
        return False
    for before in reversed(masked[:line].split("\n")):
        if not before.strip():
            continue
        if len(before) - len(before.lstrip()) < indent:
            return before.lstrip().startswith(("def ", "async def "))
    return False


def _mask(code: str) -> str:
    """C-family source with its comments and string, char and raw-string literals blanked out (lines and positions
    kept), so a name in a comment or a string is not taken for code, and brackets in them do not count."""
    out, i, n = [], 0, len(code)
    while i < n:
        if code.startswith("//", i):
            j = code.find("\n", i)
            j = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif code.startswith('"""', i):
            j = code.find('"""', i + 3)
            j = n if j < 0 else j + 3
        elif code[i] == "`":   # Go's raw string (a JavaScript template literal too)
            j = code.find("`", i + 1)
            j = n if j < 0 else j + 1
        elif code[i] in "\"'":
            j = i + 1
            while j < n and code[j] not in (code[i], "\n"):
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            out.append(code[i])
            i += 1
            continue
        out.append(re.sub(r"[^\n]", " ", code[i:j]))
        i = j
    return "".join(out)


def _closing(text: str, start: int, opening: str, closing: str) -> int:
    """The index just past the bracket that closes the one at `start`, or -1."""
    depth = 0
    for k in range(start, len(text)):
        depth += (text[k] == opening) - (text[k] == closing)
        if depth == 0:
            return k + 1
    return -1


def _definitions(masked: str, function: str, head: str, tail: str):
    """Where `function` is defined in masked source: (position of its name, its parameter list, the text before the
    name on its line) for each place where `head` comes right before the name and `tail` right after the parameter
    list's closing parenthesis (as a body opens). Found from the name's own occurrences, so a long answer costs no
    more than reading it."""
    for m in re.finditer(head + r"\b" + re.escape(function) + r"\s*\(", masked, re.A):
        name = masked.rfind(function, m.start(), m.end())
        end = _closing(masked, m.end() - 1, "(", ")")
        if end < 0 or not re.match(tail, masked[end:end + 300], re.A | re.S):
            continue
        line = masked.rfind("\n", 0, name) + 1
        yield name, masked[m.end():end - 1], masked[line:name]


DECL_KEYWORD = re.compile(r"\b(class|struct|object|interface|enum|record|fun)\b(?:\s+([A-Za-z_$][\w$]*))?")


def _owner(masked: str, pos: int) -> str | None:
    """The top-level class whose body holds what is at `pos` as its own member, "" for something at the top level
    itself (a Kotlin function), None for anything else (inside a nested class or a function). The class is the one
    declared last before the brace that opens that body, after the top-level statement before it: a class without
    a body before it (Kotlin's `data class P(val a: Int)`) does not own the next one's."""
    depth = masked.count("{", 0, pos) - masked.count("}", 0, pos)
    if depth == 0:
        return ""
    if depth != 1:
        return None
    level, k = 0, pos - 1
    while k >= 0 and not (masked[k] == "{" and level == 0):
        level += (masked[k] == "}") - (masked[k] == "{")
        k -= 1
    if k < 0:
        return None
    header = masked[max(masked.rfind("}", 0, k), masked.rfind(";", 0, k)) + 1:k]
    found = list(DECL_KEYWORD.finditer(header))
    if not found or found[-1].group(1) == "fun" or not found[-1].group(2):   # a function's body, not a class's
        return None
    return found[-1].group(2)


def _split_top(params: str, opening: str = "<", closing: str = ">") -> list[str]:
    """A parameter list split at its top-level commas (none inside <...> or the given brackets)."""
    parts, depth, cur = [], 0, ""
    for ch in params:
        depth += (ch in opening) - (ch in closing)
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def _return_type(masked: str, name: int, before: str) -> str:
    """The text naming a function's return type: what comes before its name on its line, after any `{`, `}`, `;` or
    access label there, or the line above when the name opens its line (`vector<int>` on a line of its own)."""
    before = re.sub(r"\b(public|private|protected|internal)\s*:", " ", before)
    before = re.split(r"[{};]", before)[-1]
    if not before.strip():
        lines = [ln for ln in masked[:masked.rfind("\n", 0, name)].split("\n")[-3:] if ln.strip()]
        before = re.split(r"[{};]", lines[-1])[-1] if lines else ""
    return before


def _c_escapes(s: str, octal_controls: bool = True) -> str:
    """The inside of a C-family string literal: quotes and backslashes escaped, newlines as \\n, other control
    characters in octal (a hex escape would run on into the next digits), the rest as it is (UTF-8 source)."""
    out = []
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\%03o" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _finite(v) -> float | None:
    """A JSON number as a finite float, None for anything else (a bool, a string, a number too large for one)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def _leetcode_form(code: str, function: str) -> bool:
    """A LeetCode answer: the problem's own function written as a method, of `class Solution` or of the class a
    design problem asks for (`class Codec`, `class LRUCache`). Programmers' and Codility's function is
    `solution`, and their judges add nothing."""
    return function != "solution" and (
        re.search(r"^\s*(?:(?:public|final|abstract|static)\s+)*(?:class|struct)\s+Solution\b", code, re.M)
        or re.search(r"^[ \t]+(?:async\s+)?def\s+" + re.escape(function) + r"\s*\(", code, re.M)) is not None


def _split_params(text: str) -> list[str]:
    """A parameter list split at its top-level commas (inside no bracket of any kind; the `>` of `=>` is none)."""
    parts, depth, cur = [], 0, []
    for k, ch in enumerate(text):
        depth += (ch in "([{<") - (ch in ")]}" or ch == ">" and text[k - 1:k] != "=")
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur)
    return parts + [tail] if tail.strip() or parts else parts
