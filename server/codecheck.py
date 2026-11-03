"""The example check of a coding answer, by language: which code block runs, the harness that calls its function
on each example (or feeds a program the example's input) in the code runner, and how a result compares with the
expected one. Python, JavaScript, TypeScript, Java, Kotlin, Go and C++ are called as a function; those and C and
Bash are fed standard input. The pipeline reads the examples off the problem and calls run_cases (pipeline.py).

Every harness prints one line per example, {"i": its index, "got": the value as JSON} or {"i", "error"}, after the
mark and on a line of its own (a solution may have printed without a newline), at once (output to a file is
buffered, and a run that dies would take the lines before it along). A function that returns nothing also prints
its arguments as they are after the call ("after"), for a problem solved in place. A type the check does not know
means the code is not run, and the reason is said, rather than run wrong."""
from __future__ import annotations

import decimal
import json
import math
import re
import textwrap

# Each language's own part of the check (checklangs/), and what they share. The names a language's
# module keeps to itself are re-exported here too: this module is the check's one surface.
from .checklangs.common import (
    CASE_MARK, IDENT, MAX_CASES, SIGNALS, _c_escapes, _closing, _definitions, _finite, _inside_a_function,
    _leetcode_form, _mask, _owner, _return_type, _split_params, _split_top
)
from .checklangs.python import _py_decl, _py_mask, design_harness, harness, py_program
from .checklangs.js import _js_decl, design_harness as js_design, js_harness
from .checklangs.cpp import _cpp_decl, _cpp_signature, _cpp_value, cpp_design_harness, cpp_harness
from .checklangs.java import (
    _drop_java_package, _java_definition, _java_signature, _java_value, design_harness as java_design,
    java_harness
)
from .checklangs.kotlin import (
    _kotlin_definition, _kotlin_signature, _kotlin_value, design_harness as kotlin_design, kotlin_harness
)
from .checklangs.go import _go_decl, _go_signature, _go_value, design_harness as go_design, go_harness
from .i18n import t


# Code blocks the check can run, by the fence's language as the panel's run button reads it (its first word; a
# bare fence counts as Python, as it always did here).
FENCE = re.compile(r"^[ \t]*```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)^[ \t]*```[ \t]*$", re.S | re.M)


CHECK_LANGS = {"": "python", "python": "python", "py": "python", "python3": "python",
               "javascript": "javascript", "js": "javascript", "node": "javascript", "mjs": "javascript",
               "typescript": "typescript", "ts": "typescript",
               "cpp": "cpp", "c++": "cpp", "cc": "cpp", "cxx": "cpp", "c": "c",
               "java": "java", "kotlin": "kotlin", "kt": "kotlin", "go": "go", "golang": "go",
               "bash": "bash", "sh": "bash", "shell": "bash"}


LANG_NAME = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "cpp": "C++", "c": "C",
             "java": "Java", "kotlin": "Kotlin", "go": "Go", "bash": "Bash"}


CHECKED = "Python, Java, C++, C, JavaScript, TypeScript, Kotlin, Go, Bash"


# The runner an answer carries for a function problem (analyzer.SYSTEM_PROMPT) reads one argument a line, written the
# way the problem's examples write it, and runs the examples when it reads nothing; its first line is this comment.
# What is typed into the panel's Input is often not laid out that way, and the runner then went wrong without a
# word (a Java runner of a programmers problem failed on every input typed in): a matrix pasted
# over several lines had its first row read alone and printed AA where FBABD was right, a blank line first was read as
# no input and ran the examples instead. So for such a runner the input is laid out as it reads it (args_lines).
# An answer asked for in English (analyzer.ANSWER_IN_ENGLISH) writes that comment in the English it is given there.
RUNNER_MARK = re.compile(r"입력이\s*있으면\s*그\s*값으로|on\s+the\s+input\s+if\s+given", re.I)
# Before a value: a label ("Input:", or the same in Korean) and a name ("nums = "), as LeetCode and programmers write their examples.
_LABEL = re.compile(r"^\s*(?:input|입력)\s*:\s*", re.I)
_NAME = re.compile(r"^[A-Za-z_]\w*\s*=(?!=)\s*")
# What comes after the arguments in a pasted example, and is no argument: the answer and the explanation.
_AFTER = re.compile(r"^\s*(?:output|출력|expected|result|결과|explanation|설명)\s*[:=]", re.I)


def args_lines(text: str) -> str:
    """`text` as a function runner reads it: one value a line. A value is cut at a line end, a tab or a comma that are
    outside brackets and quotes, so a matrix written over several lines is one value and `nums = [2,7], target = 9`
    is two; a line end inside brackets becomes a space. The labels and names before a value are taken off, blank
    values are dropped, and a pasted example stops at its Output or Explanation. A value never holds a comma of its own
    outside brackets or quotes (an array is bracketed, a string quoted), so a comma there always parts two values."""
    values, cur = [], []
    depth, quote, escaped, joined = 0, "", False, False

    def cut() -> None:
        value = "".join(cur).strip()
        cur.clear()
        if value:
            values.append(value)

    for ch in text.replace("\r\n", "\n"):
        if joined and not quote and ch in " \t":     # the indent of a line joined on: one space stands for it all
            continue
        joined = False
        if quote:                                   # inside a string: everything is the string's, to its own quote
            cur.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "[{(":
            depth += 1
            cur.append(ch)
        elif ch in "]})":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif depth == 0 and ch in ",\n\t":          # outside brackets: the end of one value
            cut()
        elif ch == "\n":                             # inside brackets a line end is only a space
            if cur and cur[-1] != " ":
                cur.append(" ")
            joined = True
        else:
            cur.append(ch)
    cut()
    out = []
    for value in values:
        if _AFTER.match(value):                     # the example's answer: the arguments ended before it
            break
        value = _LABEL.sub("", value)
        named = _NAME.match(value)
        if named and named.end() < len(value):      # "nums = [1, 2]": the value alone
            value = value[named.end():]
        out.append(value.strip())
    return "".join(v + "\n" for v in out if v)


# Languages a coding answer may come in that the runner has no toolchain for: said so instead of nothing.
OTHER_LANGS = {"swift": "Swift", "cs": "C#", "csharp": "C#", "c#": "C#", "rust": "Rust", "rs": "Rust",
               "ruby": "Ruby", "rb": "Ruby", "scala": "Scala", "php": "PHP", "r": "R", "dart": "Dart", "lua": "Lua",
               "perl": "Perl", "haskell": "Haskell", "hs": "Haskell", "elixir": "Elixir", "erlang": "Erlang",
               "clojure": "Clojure", "fsharp": "F#", "f#": "F#", "objc": "Objective-C", "objective-c": "Objective-C",
               "vb": "Visual Basic", "vbnet": "Visual Basic", "sql": "SQL", "mysql": "SQL", "plsql": "SQL",
               "postgresql": "SQL", "sqlite": "SQL", "powershell": "PowerShell", "ps1": "PowerShell",
               "zsh": "zsh", "fish": "fish", "julia": "Julia", "matlab": "MATLAB", "fortran": "Fortran",
               "pascal": "Pascal", "groovy": "Groovy", "ocaml": "OCaml", "zig": "Zig", "nim": "Nim"}


# A block that may be a solution: one with a function, or a program that reads input. Which one runs is decided
# with the examples (_pick): the one that defines the function they call, or the longest that reads input.
_JS_SOLUTION = re.compile(r"\bfunction\b|=>|\bclass\b|\bprocess\.stdin\b|\breadFileSync\b|\breadline\b")


SOLUTION_MARK = {
    "python": re.compile(r"^\s*def \w+\s*\(|\binput\s*\(|\bstdin\b", re.M),
    "javascript": _JS_SOLUTION,
    "typescript": _JS_SOLUTION,
    "cpp": re.compile(r"\b(?!(?:if|for|while|switch|catch|return)\b)\w+\s*\([^;{}()]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{", re.A),
    "c": re.compile(r"\b(?!(?:if|for|while|switch|return)\b)\w+\s*\([^;{}()]*\)\s*\{", re.A),
    "java": re.compile(r"\bclass\s+\w+|\b(?:public|private|protected|static)\s+[\w<>\[\],\s]+\s\w+\s*\(", re.A),
    "kotlin": re.compile(r"\bfun\s+\w+\s*\(", re.A),
    "go": re.compile(r"\bfunc\s+\w+\s*\(", re.A),
    "bash": re.compile(r"\S"),
}


_JS_INPUT = re.compile(r"\bprocess\.stdin\b|\breadFileSync\b|\breadline\b")


READS_INPUT = {
    "python": re.compile(r"\binput\s*\(|\bstdin\b|\bopen\s*\(\s*0\b"),
    "javascript": _JS_INPUT,
    "typescript": _JS_INPUT,
    "cpp": re.compile(r"\bmain\s*\(", re.A),
    "c": re.compile(r"\bmain\s*\(", re.A),
    "java": re.compile(r"\bSystem\.in\b|\bScanner\b|\bBufferedReader\b|\bStreamTokenizer\b"),
    "kotlin": re.compile(r"\breadLine\s*\(|\breadln\s*\(|\bSystem\.`?in`?|\bBufferedReader\b|\bScanner\b"),
    "go": re.compile(r"\bos\.Stdin\b|\bfmt\.Scan|\bbufio\.NewReader\b|\bbufio\.NewScanner\b"),
    "bash": re.compile(r"\bread\b|\bcat\b|\bawk\b|\bsed\b|\bgrep\b|\bsort\b|\buniq\b|\bwc\b|\bhead\b|\btail\b|\bcut\b"
                       r"|\btr\b|/dev/stdin|\bmapfile\b|\breadarray\b|\bxargs\b"),
}


# A shell block that runs another language's program (`python3 main.py`, `cat in.txt | cargo run`) shows how to
# use the solution; it is not one.
BASH_INVOCATION = re.compile(r"(?:^|[|;&]\s*)(?:\$\s+)?(?:(?:sudo|time)\s+)*(?:python3?|pypy3?|node|deno|bun|ts-node|tsc|"
                             r"java|javac|kotlinc?|go|gcc|g\+\+|clang\+?\+?|cc|cargo|rustc|swiftc?|dotnet|mono|ruby|"
                             r"php|perl|scala|ghc|\./[\w.-]+)(?=\s|$)", re.M)


def code_blocks(text: str) -> list[tuple[str, str]]:
    """The answer's code blocks in a language the runner has, as (runner language, code), in order (dedented: a
    fence inside a list keeps the list's indent), without a shell block that only runs another program."""
    blocks = [(CHECK_LANGS[label.lower()], textwrap.dedent(block)) for label, block in FENCE.findall(text or "")
              if label.lower() in CHECK_LANGS]
    return [(lang, code) for lang, code in blocks if not (lang == "bash" and BASH_INVOCATION.search(code))]


def answer_code(text: str) -> tuple[str, str] | None:
    """A solution in an answer, as (runner language, code): the longest block in a language the runner has that
    defines a function or reads input. The block that runs is chosen with the examples (_pick)."""
    found = [(lang, code) for lang, code in code_blocks(text) if SOLUTION_MARK[lang].search(code)]
    return max(found, key=lambda b: len(b[1])) if found else None


def other_language(text: str) -> str | None:
    """The language of an answer whose code is in one the runner has no toolchain for (Swift, C#, SQL...), when
    nothing in it is a solution the runner can run."""
    if answer_code(text):
        return None
    labels = [label.lower() for label, _ in FENCE.findall(text or "")]
    return next((OTHER_LANGS[label] for label in labels if label in OTHER_LANGS), None)


def _defines(lang: str, code: str, function: str) -> bool:
    n = re.escape(function)
    if lang == "python":
        return re.search(rf"^\s*def\s+{n}\s*\(", code, re.M) is not None
    if lang in ("javascript", "typescript"):   # a function, an arrow, a method (with TypeScript's annotations)
        return re.search(rf"\bfunction\s+{n}\s*[<(]|\b{n}\s*(?::[^=\n]+)?=\s*(?:async\s+)?(?:function\b|[^\n;]*=>)"
                         rf"|^\s*(?:(?:public|private|protected|static|async)\s+)*{n}\s*(?:<[^>]*>)?\s*\([^)]*\)"
                         rf"\s*(?::\s*[^{{=;]+)?\{{", code, re.M) is not None
    if lang in ("cpp", "java"):   # a definition, fillable or not (a TreeNode* parameter is said, not missed)
        masked = _mask(code)
        tail = r"\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:throws\s+[\w.,\s]+)?\{"
        return any(_return_type(masked, name, before).strip() and not re.search(r"[=()]|\b(return|new|else)\b",
                                                                                _return_type(masked, name, before))
                   for name, _, before in _definitions(masked, function, r"", tail))
    if lang == "kotlin":
        return re.search(rf"\bfun\s+(?:<[^>]*>\s*)?{n}\s*\(", _mask(code)) is not None
    if lang == "go":
        return re.search(rf"^func\s+{n}\s*\(", _mask(code), re.M) is not None
    if lang == "c":
        return re.search(rf"\b{n}\s*\([^;{{}}()]*\)\s*\{{", _mask(code)) is not None
    return False


# Where each language writes the name of a function it defines. The names found this way are checked against
# _defines, so a call or a type that looks like one does not count.
DEFINED_NAMES = {
    "python": re.compile(r"^[ \t]*def[ \t]+(\w+)[ \t]*\(", re.M),
    "javascript": re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
                             r"(?::[^=\n]+)?=\s*(?:async\s+)?(?:function\b|[^\n;]*=>)|"
                             r"^[ \t]*(?:(?:public|private|protected|static|async)\s+)*([A-Za-z_$][\w$]*)\s*\([^)]*\)"
                             r"\s*(?::\s*[^{=;]+)?\{", re.M),
    "cpp": re.compile(r"\b([A-Za-z_]\w*)\s*\([^;{}()]*\)\s*(?:const\s*)?\{", re.A),
    "java": re.compile(r"\b([A-Za-z_$][\w$]*)\s*\([^;{}()]*\)\s*(?:throws\s+[\w.,\s]+)?\{", re.A),
    "kotlin": re.compile(r"\bfun\s+(?:<[^>]*>\s*)?([A-Za-z_]\w*)\s*\(", re.A),
    "go": re.compile(r"^func\s+([A-Za-z_]\w*)\s*\(", re.M | re.A),
}


DEFINED_NAMES["typescript"] = DEFINED_NAMES["javascript"]


NOT_THE_ANSWER = {"main", "Main", "solve", "print", "input", "if", "for", "while", "switch", "catch", "return"}


def _arities(args) -> set:
    """How many arguments an example stands for: the length of its list, and one when that list may be the lone
    argument itself (_arguments decides that from the declaration, which is not known here yet). Named arguments
    (a dict, how a LeetCode statement writes its input: "a = 1, b = 20") are as many as they name, never one
    lone argument (_arguments never takes a dict as one): counted as one, an answer that named its function
    itself was refused whenever the problem had two arguments or more (21 of 46 recent problems)."""
    if isinstance(args, dict):
        return {len(args)}
    return {len(args), 1} if isinstance(args, list) else {1}


def _answer_function(text: str, arities: set) -> str | None:
    """The function an answer defines, when the one the examples name is nowhere in it: the problem's own name may
    be only in the editor, which the crop sent to the model leaves out, and the model then writes a likely name
    instead (`solution` for a LeetCode problem). The name is taken only when the answer defines exactly one that
    takes as many arguments as an example stands for, so nothing is guessed."""
    found = []
    for lang, code in code_blocks(text):
        if lang not in DEFINED_NAMES:
            continue
        masked = _mask(code)
        names = {n for m in DEFINED_NAMES[lang].finditer(masked) for n in m.groups() if n
                 if not (lang == "python" and _inside_a_function(masked, m.start()))}
        for name in sorted(names - NOT_THE_ANSWER):
            if not _defines(lang, code, name):
                continue
            decl = _declaration(lang, code, name)   # without an arity, to see how many it really takes
            if decl is None or decl["names"] is None or len(decl["names"]) in arities:
                found.append(name)
    return found[0] if len(set(found)) == 1 else None


def _pick(text: str, function: str | None) -> tuple[str, str] | None:
    """The block to run on the examples: the last that defines `function` (examples called as a function), or the
    last of the programs that read input, not counting one under half the length of the longest (a fast-input line
    beside the program). The last, since an answer that shows an approach it drops shows it before its own."""
    blocks = code_blocks(text)
    if function:
        found = [b for b in blocks if _defines(b[0], b[1], function)]
    else:
        found = [b for b in blocks if READS_INPUT[b[0]].search(b[1])]
        found = [b for b in found if len(b[1]) * 2 >= max(len(f[1]) for f in found)] if found else []
    return found[-1] if found else None


def _function_name(name) -> str | None:
    """The function the examples call, as the model wrote it ("solution", "solution()", "Solution.twoSum")."""
    name = re.sub(r"\(.*\)\s*$", "", str(name or "")).strip().split(".")[-1].strip()
    return name if IDENT.fullmatch(name) else None


HARNESSES = {"python": harness, "javascript": js_harness, "typescript": js_harness, "cpp": cpp_harness,
             "java": java_harness, "kotlin": kotlin_harness, "go": go_harness}


# ---------- results ----------

def _same(got, expected, tol: float = 0.0) -> bool:
    """Two JSON values alike: true is not 1, while 3 and 3.0 are the same number, and whole numbers compare exactly.
    An expected number with a fraction is a double's, shown rounded as a judge shows it: a result within half its
    last place counts, and within at most 1e-5 (0.73278 for 0.7327777..., 0.333333 for 1/3, 2.0 for 1.9999999999999998,
    but not 0.333 for 1/3: a statement that shows three places asks for the rounded value). With `tol`, the error
    the problem itself says it allows, every number counts within that, absolute or relative."""
    if isinstance(got, bool) or isinstance(expected, bool):
        return isinstance(got, bool) and isinstance(expected, bool) and got == expected
    # A number that came off the screen in quotes is made a number before this, where the problem writes it bare
    # (pipeline._expected_as_shown): here "94" is text, and an answer that returns 94 for it is wrong.
    # the error a problem allows is for its real-valued answer; a whole number beside it still compares exactly
    if tol and isinstance(got, (int, float)) and isinstance(expected, (int, float)) \
            and (isinstance(got, float) or isinstance(expected, float)):
        g, e = _finite(got), _finite(expected)
        return g is not None and e is not None and abs(g - e) <= tol * max(1.0, abs(e))
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        if isinstance(expected, float) or isinstance(got, float):   # a double: within the judge's error
            g, e = _finite(got), _finite(expected)
            if g is None or e is None:
                return got == expected
            if not isinstance(expected, float):   # a whole number expected: a double off by more than 1e-5 is wrong,
                return abs(decimal.Decimal(g) - expected) <= decimal.Decimal("1e-5")   # counted on the double's exact value
            if isinstance(got, int) and e.is_integer():   # the error below is for fractions: off by 10 is off by 10
                return abs(decimal.Decimal(got) - decimal.Decimal(e)) <= decimal.Decimal("1e-5")
            places = -decimal.Decimal(repr(e)).as_tuple().exponent
            return abs(g - e) <= min(1e-5, 0.5 * 10.0 ** -places) + 1e-12 or math.isclose(g, e, rel_tol=1e-12)
        return got == expected
    if isinstance(got, list) and isinstance(expected, list):
        return len(got) == len(expected) and all(_same(a, b, tol) for a, b in zip(got, expected))
    for chars, text in ((got, expected), (expected, got)):   # characters as a list or as one string (["c","b","a"], "cba")
        if isinstance(chars, list) and isinstance(text, str) and all(isinstance(c, str) and len(c) == 1 for c in chars):
            return "".join(chars) == text
    if isinstance(got, dict) and isinstance(expected, dict):
        return got.keys() == expected.keys() and all(_same(got[k], expected[k], tol) for k in got)
    return type(got) is type(expected) and got == expected


def _key(v) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def _unordered(v, deep: bool = False):
    """A list put in one fixed order, so two answers that differ only in the order of its elements compare the
    same: for a problem whose statement says the answer may come in any order (LeetCode's "in any order"). Only
    the list itself, not what is inside its elements: Permutations also says "in any order", and there the order
    inside each element is the answer, so an answer that sorts each permutation must fail. With `deep`, every
    list at every depth, which is only used to say on the card that a result holds the expected values in
    another order. A number read within the problem's own tolerance may sort to another place, so the compare in
    order comes first."""
    if isinstance(v, list):
        return sorted((_unordered(x, deep) if deep else x for x in v), key=_key)
    return v


def _tolerance(cases: dict) -> float:
    """The error the problem says it allows, 0 when it says none. A number that is no tolerance (0, or one large
    enough to let anything pass) counts as none."""
    t = cases.get("tolerance")
    ok = isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < float(t) <= 0.1
    return float(t) if ok else 0.0


# An expected output with a number of more places than a double holds (Baekjoon 1008's
# 0.33333333333333333333333333333333) is a judge's that allows an error, as such a problem says (10^-9 there).
LONG_FRACTION = re.compile(r"-?\d+\.\d{16,}")


NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _same_output(a: str, b: str, error: float = 0.0, any_order: bool = False) -> bool:
    """A program's output against the expected one, line ends and the last newline aside; with `error`, number
    against number within that absolute or relative error (a judge's for a problem that allows one); with
    `any_order`, its lines in any order (a problem whose statement says the order of the output does not
    matter)."""
    norm = lambda s: "\n".join(line.rstrip() for line in (s or "").strip().splitlines())  # noqa: E731
    if norm(a) == norm(b):
        return True
    if any_order:
        lines, want_lines = sorted(norm(a).splitlines()), sorted(norm(b).splitlines())
        if len(lines) == len(want_lines) and all(_same_output(x, y, error) for x, y in zip(lines, want_lines)):
            return True
    if not error:
        return False
    got, want = norm(a).split(), norm(b).split()
    if len(got) != len(want):
        return False
    for g, w in zip(got, want):
        if g == w:
            continue
        if not (NUMBER.fullmatch(g) and NUMBER.fullmatch(w)):
            return False
        x, y = float(g), float(w)
        if not abs(x - y) <= error * max(1.0, abs(y)):
            return False
    return True


def _failure_note(res: dict) -> str:
    """Why a run gave no result: its time limit, the compiler's first error, the program's error (the last line
    naming one: Python's traceback ends with it, Node's and Java's come before their stack), an uncaught C++
    exception, or the signal that stopped it."""
    if res.get("timed_out"):
        return t("Timed out")
    # a run whose output did not fit: the result line itself came back cut, so there is nothing to read
    if res.get("output_limited") or res.get("stdout_truncated"):
        return t("The output is too long to read the result")
    lines = [ln.strip() for ln in (res.get("stderr") or "").split("\n") if ln.strip()]
    if res.get("stage") == "compile":   # gcc, javac, kotlinc and ts_strip say "error:"; Go names the line alone
        for ln in lines:
            if re.search(r"\berror:|^error\b|: error\b", ln, re.I):
                return ln[:200]
        first = next((ln for ln in lines if not ln.startswith("#")), None)
        if first:
            return first[:200]
    for ln in reversed(lines):
        if re.match(r"(?:Exception in thread \"[^\"]*\"\s+)?[\w.$]*(Error|Exception)\b", ln) or ln.startswith("panic:"):
            return ln[:200]
    for ln in lines:
        if ln.startswith("what():"):
            return ("terminate: " + ln[len("what():"):].strip())[:200]
    code = res.get("exit")
    if isinstance(code, int) and code < 0:
        return f"{SIGNALS.get(-code, 'signal')} (signal {-code})"
    lines = [ln for ln in lines if not ln.startswith("Node.js") and not set(ln) <= set("|^~ ")]
    return lines[-1][:200] if lines else t("Exit code {code}", code=code)


PY_TYPES = {"int", "float", "str", "bool", "list", "dict", "set", "tuple", "frozenset", "bytes", "complex", "object",
            "None", "List", "Dict", "Set", "Tuple", "FrozenSet", "Optional", "Union", "Any", "Sequence", "Iterable",
            "Mapping", "Deque", "DefaultDict", "Counter", "typing", "collections"}


JS_TYPES = {"number", "string", "boolean", "bigint", "integer", "character", "object", "Object", "Array",
            "ReadonlyArray", "any", "unknown", "null", "undefined", "void", "Number", "String", "Boolean", "Record",
            "Map", "Set", "readonly"}


# A parameter used as a node of a shape no harness builds: an n-ary tree's children, a graph's neighbours, a
# random pointer. A tree or a linked list is found from the declaration instead (_node_shape).
NODE_USE = r"\b%s\s*\??\.\s*(?:left|right|next|prev|val|children|neighbors|random|child)\b"




NODE_NAME = re.compile(r"\b(TreeNode|ListNode|Node)\b")


_REACH = r"\s*(?:\?\s*\.|->|\.)\s*"       # root.left, root->left, root?.left
TREE_USE = r"\b%s" + _REACH + r"(?:left|right)\b(?!\s*\()"


LIST_USE = r"\b%s" + _REACH + r"next\b(?!\s*\()"


NARY_USE = r"\b%s" + _REACH + r"children\b(?!\s*\()"


# The names a judge hands a node, for an answer that declares no types at all: `leafSimilar(root1, root2)`
# writes nothing about them and reads `.left` only inside a helper of its own.
NODE_PARAM = {"root", "root1", "root2", "rootA", "rootB", "subRoot", "head", "head1", "head2", "headA", "headB",
              "l1", "l2", "list1", "list2", "node", "tree", "original", "cloned", "target"}
NODE_MANY = re.compile(r"(?:List|Sequence|Iterable|ArrayList|vector|Array|Vec|Seq)\s*[\[<]|\[\s*\]|\.\.\.")


def _node_shape(type_text: str, name: str | None, masked: str) -> list | None:
    """["tree" or "list" (or "trees"/"lists" for a list of them), the class it names] when a parameter or a
    result is a tree or a linked list node, from the type it declares (`Optional[TreeNode]`,
    `List[ListNode]`) or, where it declares none, from how the code uses it (`root.left`, `head.next`). None
    when it is neither, or when it is a node this cannot build from a level-order list: an n-ary tree
    (`children`), or LeetCode's `Node`, which is the name of several shapes there (a list with a random
    pointer, a circular list), unless the answer defines that class itself."""
    named = NODE_NAME.search(type_text or "")
    cls = named.group(1) if named else None
    many = "s" if cls and NODE_MANY.search(type_text or "") else ""
    if name and re.search(NARY_USE % re.escape(name), masked):
        return None
    if cls == "Node" and not re.search(r"^[ \t]*class\s+Node\b", masked, re.M):
        return None
    if cls in ("TreeNode", "ListNode"):
        return ["tree" + many if cls == "TreeNode" else "list" + many, cls]
    tree = bool(name) and re.search(TREE_USE % re.escape(name), masked) is not None
    chain = bool(name) and re.search(LIST_USE % re.escape(name), masked) is not None
    if cls == "Node":
        return ["tree" + many, cls] if tree else ["list" + many, cls] if chain else None
    if cls or (type_text or "").strip():
        return None   # a type is declared and it is no node class: whatever a name of that spelling is used for
    if not (tree or chain) and name in NODE_PARAM:
        # nothing is declared (plain JavaScript, Python without hints) and this is a name a judge hands a node:
        # how any name is used then, since the answer may pass it to a helper and never write `root.left` itself
        tree = re.search(TREE_USE % r"\w+", masked) is not None
        chain = re.search(LIST_USE % r"\w+", masked) is not None
    return ["tree", "TreeNode"] if tree else ["list", "ListNode"] if chain else None


def _node_type(code: str, names) -> str | None:
    """"node" (in the panel's language) when the code treats a parameter as a node of a shape the harness cannot
    build (its children, its neighbours, its random pointer), else None. The node class being defined or described is not the signal: an
    answer writes its own `class Node` for a segment tree while its arguments are plain lists, and a node the
    harness can build is found from the declaration instead (_node_shape)."""
    masked = _mask(code)
    if any(n and re.search(NODE_USE % re.escape(n), masked) for n in names or ()):
        return t("node")
    return None


def _foreign_type(texts, known: set) -> str | None:
    """The first type named in the declarations' type texts that is neither a builtin one nor a container of them
    (a TreeNode, a ListNode: an example's level-order list is not one), None for none."""
    for text in texts:
        for t in re.findall(r"[A-Za-z_$][\w$]*", text or ""):
            if t not in known:
                return t
    return None


# The languages whose harness builds a tree or a linked list from the level-order list an example writes. For
# any other, a node is still a type the check cannot fill, and it says so instead of running it wrong.
NODE_LANGS = {"python", "javascript", "typescript", "cpp", "java", "kotlin", "go"}


def _shapes(lang: str, types, names, ret, masked: str) -> tuple[list | None, list | None]:
    """The shapes of a declaration's parameters and of its result: a tree or a linked list the harness can build
    from an example's list (_node_shape), None where it is an ordinary value or the language has no harness for
    one yet."""
    if lang not in NODE_LANGS:
        return None, None
    shapes = None if names is None else [_node_shape(t, n, masked) for t, n in
                                         zip(list(types or ()) + [""] * len(names), names)]
    return shapes, _node_shape(ret or "", None, masked)


def _declaration(lang: str, code: str, function: str, arity: int | None = None) -> dict | None:
    """What the declaration of `function` says: "names" of its parameters (None when any number goes, a name "" when
    it has none), "kind" of its result ("void" when it says it returns nothing, "value" when it says what it
    returns, None when it does not say), and "foreign": a type the check cannot make from an example, or None.
    None when it is not found."""
    if lang == "python":
        d = _py_decl(code, function)
        if d is None:
            return None
        params, ret, doc = d
        doc_types, doc_ret = doc
        said = ret if ret is not None else doc_ret   # or what its docstring says
        kind = "void" if said == "None" else "value" if said is not None else None
        # the type a parameter declares, or the one its docstring gives it (LeetCode's Python 2 template)
        told = [a or doc_types.get(n, "") for n, a, _ in params or ()]
        types = told + [ret or "", *doc_types.values()]
        names = [n for n, _, _ in params] if params is not None else None
        shapes, result = _shapes(lang, told, names, ret or doc_ret, _py_mask(code))
        # a type the shapes do take care of is not a type the check cannot fill
        rest = [t for t in types if not NODE_NAME.search(t or "")] if any(shapes or ()) or result else types
        return {"names": names, "required": sum(not o for _, _, o in params) if params is not None else None,
                "kind": kind, "shapes": shapes, "result": result,
                "foreign": _foreign_type(rest, PY_TYPES)
                or (None if any(shapes or ()) or result else _node_type(code, names))}
    if lang in ("javascript", "typescript"):
        d = _js_decl(code, function)
        if d is None:
            return None
        params, ret, doc = d
        doc_ret = re.search(r"@returns?\s*\{([^}]*)\}", doc)
        said = ret if ret is not None else doc_ret.group(1).strip() if doc_ret else None
        kind = None if said is None else "void" if said in ("void", "undefined") else "value"
        types = [t for _, t, _ in params or []] + [ret or ""] + re.findall(r"@(?:param|returns?)\s*\{([^}]*)\}", doc)
        names = [n for n, _, _ in params] if params is not None else None
        # the JSDoc type of a parameter that declares none (`@param {TreeNode} root`), as plain JavaScript has
        jsdoc = {n: t for t, n in re.findall(r"@param\s*\{([^}]*)\}\s*(\w+)", doc)}
        told = [t or jsdoc.get(n, "") for n, t, _ in params or ()]
        shapes, result = _shapes(lang, told, names, ret or (doc_ret.group(1) if doc_ret else ""), _mask(code))
        rest = [t for t in types if not NODE_NAME.search(t or "")] if any(shapes or ()) or result else types
        return {"names": names, "required": sum(not o for _, _, o in params) if params is not None else None,
                "kind": kind, "shapes": shapes, "result": result,
                "foreign": _foreign_type(rest, JS_TYPES)
                or (None if any(shapes or ()) or result else _node_type(code, names))}
    if lang == "cpp":
        d = _cpp_decl(code, function, arity)
        if d is None:
            return None
        shapes, result = _shapes(lang, d[1], d[2], d[0], _mask(code))
        return {"names": d[2], "kind": "void" if d[0] == "void" else "value",
                "shapes": shapes, "result": result, "foreign": None}
    if lang == "java":
        d = _java_definition(_drop_java_package(code), function, arity)
        if d is None:
            return None
        shapes, result = _shapes(lang, d[1], d[2], d[0], _mask(code))
        return {"names": d[2], "kind": "void" if d[0] == "void" else "value",
                "shapes": shapes, "result": result, "foreign": None}
    if lang == "kotlin":
        d = _kotlin_definition(code, function, arity)
        if d is None:
            return None
        shapes, result = _shapes(lang, d[1], d[5], d[0], _mask(code))
        return {"names": d[5], "kind": "void" if d[0] == "Unit" else None if d[0] == "?" else "value",
                "shapes": shapes, "result": result, "foreign": None}
    if lang == "go":
        d = _go_decl(code, function, arity)
        if d is None:
            return None
        shapes, result = _shapes(lang, d[1], d[2], d[0], _mask(code))
        return {"names": d[2], "kind": "void" if d[0] == "" else "value",
                "shapes": shapes, "result": result, "foreign": None}
    return None


def _lone(args, names: list, required: int) -> bool:
    """Whether an example for a function of one argument (more only with defaults) is that argument itself, not
    the list of its arguments: a value that is no such list (a string, a number, a flat list of its elements)."""
    return required <= 1 and not (isinstance(args, list) and max(required, 1) <= len(args) <= len(names))


def _arguments(args, names: list | None, required: int | None = None, lone: bool = False):
    """An example's arguments as a list in the parameters' order, None when they cannot be: given by name (LeetCode
    shows `nums = [2,7,11,15], target = 9`; one key under another name for a function of one argument), or the lone
    argument itself (`lone`: decided over all the examples, so a one-element `[0]` beside a flat `[3,0,1]` is
    wrapped too). Parameters with a default may be left out."""
    if names is None:
        return args if isinstance(args, list) else None
    required = len(names) if required is None else required
    if lone:
        return [args]
    if isinstance(args, dict):
        if "" not in names and set(args) <= set(names) and set(names[:required]) <= set(args):
            k = max((names.index(key) for key in args), default=-1) + 1
            return [args[n] for n in names[:k]] if set(names[:k]) <= set(args) else None
        if required <= 1 and len(args) == 1:
            return [next(iter(args.values()))]
        return [args] if required <= 1 and len(args) <= 1 else None
    return args if isinstance(args, list) and required <= len(args) <= len(names) else None


def _as_list(v):
    """A value written as a string that holds a list ("[1,2,null]"), as that list. A tree's level-order list is
    written that way now and then, and a node is never a string, so only a node's is read again."""
    if isinstance(v, str):
        try:
            got = json.loads(v)
        except ValueError:
            return v
        return got if isinstance(got, list) else v
    return v


def _node_values(shapes, result, examples: list) -> list:
    """The examples with a node's arguments and expected value read as lists where they came as strings."""
    if not any(shapes or ()) and not result:
        return examples
    out = []
    for c in examples:
        args = list(c.get("args") or [])
        for k, shape in enumerate(shapes or ()):
            if shape and k < len(args):
                args[k] = _as_list(args[k])
        out.append({**c, "args": args, **({"expected": _as_list(c["expected"])} if result else {})})
    return out


def _target(d: dict, args) -> tuple[object, bool] | None:
    """(the first list argument after a call that returned nothing, whether the call changed it), None when there is
    none: what LeetCode's "do not return anything, modify nums in-place" judges, always the first."""
    if d.get("got") is not None or not isinstance(d.get("after"), list) or not isinstance(args, list):
        return None
    k = next((k for k, a in enumerate(args) if isinstance(a, list)), None)
    if k is None or k >= len(d["after"]):
        return None
    return d["after"][k], not _same(d["after"][k], args[k])


SAID_KIND = {"value": "value", "in_place": "void"}   # what the problem's own "returns" means for the judging


def _in_place(d: dict, args, expected, kind: str | None, function: str, mutates: bool = False,
              said: bool = False, tol: float = 0.0) -> tuple[bool, object]:
    """A function that returned nothing but left its first list argument at the expected value: (whether it did,
    that argument as it was left, or None when it is not judged by one: the card and the retry show it). One
    that says it returns a value has failed, as has Programmers' `solution` (its answer is what it returns).
    One that does not say must have changed the argument, here or in another example (`mutates`), so a function
    that only forgot its return is not taken for one."""
    found = _target(d, args)
    if found is None or expected is None:
        return False, None
    # Programmers judges what `solution` returns, even a void one, unless this problem says to fix the argument
    if kind == "value" or function == "solution" and not said:
        return False, None
    after, changed = found
    return _same(after, expected, tol) and (kind == "void" or changed or mutates), after


def _rule(cases: dict, said: str | None, tol: float = 0.0) -> dict:
    """{"rule": what was judged by something other than an exact match}, for the card; {} when nothing was. The
    user sees why an answer passed or failed: the words the problem itself used, and the error in effect (the
    one it allows, or the one an example with more places than a double holds implies)."""
    bits = ([t("any order")] if cases.get("order") == "any" else []) \
        + ([t("in place")] if said == "void" else []) \
        + ([t("tolerance {tol}", tol=f"{tol:g}")] if tol else [])
    return {"rule": ", ".join(bits)} if bits else {}


MAX_CALLS = 20   # a problem that asks for a class states this many calls at most (LRUCache's example: 11)
# the languages whose harness calls a class the problem asks for
DESIGNS = {"python": design_harness, "javascript": js_design, "typescript": js_design, "cpp": cpp_design_harness,
           "java": java_design, "kotlin": kotlin_design, "go": go_design}
CLASS_DEFINED = r"\b(?:class|struct|type|interface)\s+%s\b|\b%s\s*=\s*(?:class\b|function\b)"


def _calls(cases: dict) -> list | None:
    """The calls a problem that asks for a class states, as [{"call": name, "args": [...], "expected": value}]:
    from the three lists its statement writes, the calls, each call's arguments and what each returned. None
    when they do not line up, which means they were not read off the problem."""
    names, args, expected = cases.get("calls"), cases.get("args"), cases.get("expected")
    if not all(isinstance(x, list) and x for x in (names, args, expected)):
        return None
    if not len(names) == len(args) == len(expected) or not all(isinstance(n, str) and n.strip() for n in names):
        return None
    # a call that takes nothing is written as an empty list, and on some problems as null
    return [{"call": n.strip(), "args": a if isinstance(a, list) else [] if a is None else [a], "expected": e}
            for n, a, e in zip(names, args, expected)][:MAX_CALLS]


def _class_body(lang: str, code: str, name: str) -> str:
    """The part of an answer that is the class `name`. A method read by its name alone may be a helper class's
    instead: LeetCode's own 707 answer writes `class Node` with an `__init__` of its own after the list class.
    Go is given back whole, since its methods are written beside the type, not inside it."""
    if lang == "python":
        m = re.search(r"^class\s+%s\b" % re.escape(name), _py_mask(code), re.M)
        if not m:
            return code
        head = code.find("\n", m.end())   # from the line after its own, or ^ would match the head's own colon
        if head < 0:
            return code[m.start():]
        after = re.search(r"^\S", code[head + 1:], re.M)
        return code[m.start():head + 1 + (after.start() if after else len(code) - head - 1)]
    if lang == "go":
        return code
    masked = _mask(code)   # the brace languages: from its declaration to the brace that closes its body
    m = re.search(r"\b(?:class|struct)\s+%s\b" % re.escape(name), masked)
    if not m:
        return code
    opening = masked.find("{", m.end())
    if opening < 0:
        return code
    end = _closing(masked, opening, "{", "}")
    return code[m.start():end if end > 0 else len(code)]


def _defines_class(lang: str, code: str, name: str) -> bool:
    n = re.escape(name)
    return re.search(CLASS_DEFINED % (n, n), _py_mask(code) if lang == "python" else _mask(code)) is not None


def _pick_class(text: str, name: str) -> tuple[str, str] | None:
    """The block to run the calls on: the last that defines the class the problem names, or, when none does, the
    last that defines exactly one class of its own (the name on the screen may be only in the editor). A block
    in a language with no harness for a class comes back as (its language, "") so the reason can say so."""
    other = [b for b in code_blocks(text) if b[0] not in DESIGNS and _defines_class(b[0], b[1], name)]
    blocks = [b for b in code_blocks(text) if b[0] in DESIGNS]
    found = [b for b in blocks if _defines_class(b[0], b[1], name)]
    if not found and other:
        return other[-1][0], ""
    if found:
        return found[-1]
    for lang, code in reversed(blocks):
        own = {m.group(1) for m in re.finditer(r"^class\s+([A-Za-z_]\w*)", _py_mask(code), re.M)} \
            if lang == "python" else set()
        if len(own) == 1:
            return lang, code
    return None


async def run_design(text: str, cases: dict, run) -> dict | None:
    """The answer's class on the calls the problem states: passed, total and the first calls that did not give
    what the statement says. None when the problem states none."""
    cls, calls = cases.get("class"), _calls(cases)
    if not (isinstance(cls, str) and cls.strip()):
        return None
    if calls is None:
        return {"skipped": t("The calls of {cls} and their expected values do not pair up", cls=cls.strip())}
    cls = cls.strip().split(".")[-1]
    found = _pick_class(text, cls)
    if found is None:
        other = other_language(text)
        return {"skipped": t("{lang} code cannot be run (runs {langs})", lang=other, langs=CHECKED) if other
                else t("No class {cls} in the answer's code", cls=cls)}
    lang, code = found
    if not code:   # the class is there, in a language whose harness cannot call one yet
        # `ro`: the Korean particle after the language's name as it is said (Python and Kotlin end in a consonant)
        return {"skipped": t("Classes written in {lang} are not run yet (runs {langs})", lang=LANG_NAME[lang],
                             ro="으로" if lang in ("python", "kotlin") else "로",
                             langs=", ".join(dict.fromkeys(LANG_NAME[x] for x in DESIGNS)))}
    name = cls if _defines_class(lang, code, cls) else \
        next(m.group(1) for m in re.finditer(r"^class\s+([A-Za-z_]\w*)", _py_mask(code), re.M))
    # what each method declares about its arguments and its result, so a tree or a list is built here too
    read, body = {}, _class_body(lang, code, name)
    for k, c in enumerate(calls):
        called = "__init__" if k == 0 else c["call"]
        if called not in read:
            read[called] = _declaration(lang, body, called) or {}
        if read[called].get("foreign"):   # as the function path does: say so rather than run it wrong
            return {"skipped": t("The examples' values cannot fill the {lang} class's argument or result type ({type})",
                                 lang=LANG_NAME[lang], type=read[called]["foreign"])}
        c["shapes"] = read[called].get("shapes") or []
        c["result"] = read[called].get("result")
        # a call that takes nothing is written [] on most problems and [null] on some, and no statement writes
        # a null as a value: so one null alone means nothing, unless the declaration says it takes one argument
        if c["args"] == [None] and not read[called].get("names"):
            c["args"] = []
    program = DESIGNS[lang](code, name, calls)
    if program is None:   # as the function path does: the card says it instead of running something else
        return {"skipped": t("The examples' values cannot fill the calls of the {lang} class {name}",
                             lang=LANG_NAME[lang], name=name)}
    res = await run(lang, program, "")
    if res.get("error"):
        return {"error": res["error"]}
    if res.get("stage") == "compile":
        return {"error": t("Compile error: {why}", why=_failure_note(res))}
    got = {}
    for line in (res.get("stdout") or "").split("\n"):
        if line.startswith(CASE_MARK):
            try:
                d = json.loads(line[len(CASE_MARK):])
            except ValueError:
                continue
            if isinstance(d, dict) and isinstance(d.get("i"), int):
                got[d["i"]] = d
    if not got:
        return {"error": _failure_note(res)}
    tol = _tolerance(cases)
    rows = []
    for i, c in enumerate(calls):
        d = got.get(i) or {"error": t("Stopped at an earlier call")}
        shown = f"{c['call']}({', '.join(json.dumps(a, ensure_ascii=False) for a in c['args'])})"
        rows.append({"ok": "got" in d and _same(d["got"], c["expected"], tol), "input": shown,
                     "expected": c["expected"], "got": d.get("got", d.get("error"))})
    fails = [r for r in rows if not r["ok"]]
    return {"passed": len(rows) - len(fails), "total": len(rows), "how": "design", "lang": lang,
            "rows": _shown_rows(rows),
            "fails": [{k: r[k] for k in ("input", "expected", "got")} for r in fails[:2]], **_rule(cases, None, tol)}


def _shown_rows(rows: list) -> list:
    """Each run as the panel lists it: what went in, what was expected, what came out. At most eight, each cut short."""
    cut = lambda v: v[:300] if isinstance(v, str) else v  # noqa: E731
    return [{"ok": bool(r.get("ok")), "input": cut(r.get("input")), "expected": cut(r.get("expected")), "got": cut(r.get("got"))} for r in rows[:8]]


async def run_cases(text: str, cases: dict, run) -> dict | None:
    """The answer's code on the examples, called as a function or fed standard input: passed, total, and the
    first failing examples; {"skipped": why} when its code cannot be run on them; None when there are no examples.

    With cases["probe"] the inputs are ones the local model made up for a problem that shows no examples
    (analyzer.EXTRACT_PROBES) and carry no answers: a run passes when it ends in time with no error, and the result
    says "probe", so the card says what it is and no retry is asked from it (the input may be the wrong one)."""
    probe = bool(cases.get("probe"))
    if cases.get("class"):   # a problem that asks for a class, judged by the calls its statement states
        return await run_design(text, cases, run)
    examples = cases.get("cases")
    function = _function_name(cases.get("function"))
    if isinstance(examples, list) and examples and function:
        examples = [c for c in examples if isinstance(c, dict) and ("expected" in c or probe)][:MAX_CASES]
        if not examples:
            return None
        found = _pick(text, function)
        if found is None:   # the name the examples carry is in no block: the one the answer defines, if it is one
            other_name = _answer_function(text, _arities(examples[0].get("args")))
            if other_name:
                function, found = other_name, _pick(text, other_name)
        if found is None:
            other = other_language(text)
            return {"skipped": t("{lang} code cannot be run (runs {langs})", lang=other, langs=CHECKED) if other
                    else t("No function {name} in the answer's code", name=function)}
        lang, code = found
        build = HARNESSES.get(lang)
        if build is None:
            return {"skipped": t("{lang} code is run only as a program that reads standard input", lang=LANG_NAME[lang])}
        first = examples[0].get("args")
        decl = _declaration(lang, code, function, len(first) if isinstance(first, list) else None) \
            or _declaration(lang, code, function)
        if decl and decl["foreign"]:
            return {"skipped": t("The examples' values cannot fill the {lang} function's argument or result type ({type})",
                                 lang=LANG_NAME[lang], type=decl["foreign"])}
        names = decl["names"] if decl else None
        required = decl.get("required") if decl else None
        required = len(names) if names is not None and required is None else required
        raw = [c.get("args", []) for c in examples]
        lone = names is not None and len(names) >= 1 and any(_lone(a, names, required) and not isinstance(a, dict)
                                                             for a in raw)
        args = [_arguments(a, names, required, lone) for a in raw]
        if any(a is None for a in args):
            return {"skipped": t("The examples' arguments do not fit the parameters of the {lang} function {name}",
                                 lang=LANG_NAME[lang], name=function)}
        examples = [{**c, "args": a} for c, a in zip(examples, args)]
        decl = _declaration(lang, code, function, len(args[0])) or decl
        if decl:   # a level-order list written as a string
            examples = _node_values(decl.get("shapes"), decl.get("result"), examples)
        program = build(code, function, examples, decl.get("shapes") if decl else None,
                        decl.get("result") if decl else None)
        if program is None:
            return {"skipped": t("The examples' values cannot fill the {lang} function's argument or result types",
                                 lang=LANG_NAME[lang])}
        res = await run(lang, program, "")
        if res.get("error"):
            return {"error": res["error"]}
        if res.get("stage") == "compile":
            return {"error": t("Compile error: {why}", why=_failure_note(res))}
        got = {}
        for line in (res.get("stdout") or "").split("\n"):
            if line.startswith(CASE_MARK):
                try:
                    d = json.loads(line[len(CASE_MARK):])
                except ValueError:
                    continue
                if isinstance(d, dict) and isinstance(d.get("i"), int):
                    got[d["i"]] = d
        if not got:
            return {"error": _failure_note(res)}
        # what the code itself declares, and only where it declares nothing, what the problem says
        returns = cases.get("returns")
        said = SAID_KIND.get(returns) if isinstance(returns, str) else None
        kind = (decl["kind"] if decl else None) or said
        tol, any_order = _tolerance(cases), cases.get("order") == "any"
        mutates = any((_target(got[i], c.get("args")) or (None, False))[1] for i, c in enumerate(examples) if i in got)
        rows = []
        for i, c in enumerate(examples):   # an example without its line: the run stopped before it
            d = got.get(i) or {"error": _failure_note(res)}
            if probe:   # no answer to judge by: it ran, or it did not
                rows.append({"ok": "got" in d, "input": c.get("args"), "got": d.get("got", d.get("error"))})
                continue
            ok = "got" in d and (_same(d["got"], c["expected"], tol)
                                 or any_order and _same(_unordered(d["got"]), _unordered(c["expected"]), tol))
            shown = d.get("got", d.get("error"))
            if not ok and "got" in d:
                ok, left = _in_place(d, c.get("args"), c["expected"], kind, function, mutates,
                                     said == "void" and kind == "void", tol)
                shown = left if left is not None else shown
            # a result that is the expected one in another order, on a problem whose statement did not say that
            # order does not count: the card says so, since the answer may still be right
            order_only = not ok and "got" in d and _same(_unordered(d["got"], True), _unordered(c["expected"], True), tol)
            rows.append({"ok": ok, "input": c.get("args"), "expected": c["expected"], "got": shown,
                         **({"order_only": True} if order_only else {})})
        fails = [r for r in rows if not r["ok"]]
        if probe:
            return {"probe": True, "passed": len(rows) - len(fails), "total": len(rows), "how": "function", "lang": lang,
                    "rows": _shown_rows(rows),
                    "fails": [{k: r[k] for k in ("input", "got")} for r in fails[:2]]}
        return {"passed": len(rows) - len(fails), "total": len(rows), "how": "function", "lang": lang,
                "rows": _shown_rows(rows),
                "fails": [{k: r[k] for k in ("input", "expected", "got", "order_only") if k in r} for r in fails[:2]],
                **_rule(cases, said, tol)}
    if isinstance(cases.get("stdin"), list) and cases["stdin"]:
        found = _pick(text, None)
        if found is None:
            other = other_language(text)
            return {"skipped": t("{lang} code cannot be run (runs {langs})", lang=other, langs=CHECKED) if other
                    else t("No program that reads input in the answer's code")}
        lang, code = found
        # (an input with no output has nothing to be judged by: it read as failing, and asked for a retry)
        examples = [c for c in cases["stdin"][:MAX_CASES] if isinstance(c, dict) and ("output" in c or probe)]
        if not examples:
            return None
        # one request for all of them: the runner compiles once (Kotlin's compile alone takes about 3 s); an input
        # ends with a newline, as a judge's input file does (a line read up to "\n" would never end otherwise)
        inputs = [str(c.get("input", "")) for c in examples]
        inputs = [x if not x or x.endswith("\n") else x + "\n" for x in inputs]
        res = await run(lang, py_program(code) if lang == "python" else code, inputs)
        if res.get("error"):
            return {"error": res["error"]}
        if res.get("stage") == "compile":
            return {"error": t("Compile error: {why}", why=_failure_note(res))}
        runs = res.get("runs")
        if not isinstance(runs, list) or len(runs) != len(examples):   # a runner from before batched inputs
            return {"error": t("The runner cannot take the examples in one go · rebuild with ./sidenote up")}
        # the error the problem says it allows; else 1e-9 when an example shows more places than a double holds
        error = _tolerance(cases) or (1e-9 if any(LONG_FRACTION.search(str(c.get("output", ""))) for c in examples)
                                      else 0.0)
        rows = []
        for c, r in zip(examples, runs):
            out = (r.get("stdout") or "").strip()
            failed = r.get("timed_out") or r.get("exit") not in (0, None)
            got = out[:300] if not failed else (f"{out[:300]}\n({_failure_note(r)})" if out else _failure_note(r))
            rows.append({"ok": r.get("ok") and not failed
                         and (probe or _same_output(out, str(c.get("output", "")), error, cases.get("order") == "any")),
                         "input": c.get("input"), "expected": c.get("output"), "got": got})
        fails = [r for r in rows if not r["ok"]]
        if probe:   # what it printed is shown as it is: there is nothing to compare it with
            return {"probe": True, "passed": len(rows) - len(fails), "total": len(rows), "how": "stdin", "lang": lang,
                    "rows": _shown_rows(rows),
                    "fails": [{k: r[k] for k in ("input", "got")} for r in fails[:2]],
                    "outputs": [{"input": r["input"], "got": r["got"]} for r in rows[:3]]}
        return {"passed": len(rows) - len(fails), "total": len(rows), "how": "stdin", "lang": lang,
                "rows": _shown_rows(rows),
                "fails": [{k: r[k] for k in ("input", "expected", "got")} for r in fails[:2]],
                **_rule(cases, None, error)}
    return None
