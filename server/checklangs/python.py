"""Python: the program a solution fed standard input runs as, and the harness that calls its function on
each example. A LeetCode answer gets the names its judge provides, and a tree or a linked list is built from the
level-order list the statement writes."""
from __future__ import annotations

import json
import re

from .common import CASE_MARK, MAX_CASES, _closing, _leetcode_form, _split_params


# ---------- Python ----------

# A Python program fed standard input runs as its own compiled unit, so a `from __future__` line still comes
# first, with exit() and quit() defined, which a runner that still starts Python with -S (no site module) leaves out.
PY_PROGRAM = """import sys as _s
_ns = {"__name__": "__main__", "exit": _s.exit, "quit": _s.exit}
exec(compile(_CODE, "main.py", "exec"), _ns)
"""


# The answer runs as a module (its `if __name__ == "__main__":` part does not run, so it does not wait for input),
# and its function is called, on a new `Solution` for each example as a judge makes one (LeetCode's form), with
# what it prints itself thrown away (a long table of its own would push the results past the runner's limit).
# LeetCode's form gets the names its judge provides without an import (typing's, collections', heapq's...; never
# one that would hide a builtin); any other answer runs as plain Python, its missing import an error as at its judge.
PY_JUDGE_PRELUDE = """from typing import *
import collections, heapq, bisect, itertools, functools, math, string, operator, re, random, sys, copy, datetime
try:
    import sortedcontainers   # the one package LeetCode has that the standard library does not
except ImportError:
    sortedcontainers = None
import builtins as _b
_mods = [_m for _m in (collections, heapq, bisect, itertools, functools, math, string, operator, random, copy,
                       sortedcontainers) if _m is not None]
# a module's own name is never taken by a function of that name (bisect.bisect would hide the bisect module,
# and random.random the random module: an answer calling bisect.bisect_left then fails)
_keep = {_m.__name__ for _m in _mods} | {"re", "sys", "datetime", "typing", "builtins"}
for _m in _mods:
    for _k in dir(_m):
        if not _k.startswith("_") and not hasattr(_b, _k) and _k not in _keep:
            globals()[_k] = getattr(_m, _k)
del _m, _k, _b, _mods, _keep
"""


# ---------- a tree or a linked list as an example writes it ----------

# LeetCode's judge provides these classes and writes a tree or a list as the level-order list the statement
# shows (`root = [3,9,20,null,null,15,7]`, `head = [1,2,3]`), so an answer written there uses them without
# defining them. They go in before the answer, which may define its own and override them.
PY_NODE_CLASSES = """
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next
"""


# In the harness, after the answer has run: the example's list becomes nodes of the class the answer uses, and a
# node that comes back becomes a list again, so the comparing stays on JSON values. A list that runs in a circle
# (what a cycle question builds) is followed only once round.
# In the harness, after the answer has run: the example's list becomes nodes of the class the answer uses, and
# a node that comes back becomes a list again, so the comparing stays on JSON values. A statement that gives a
# node by its value instead of its list (`root = [3,5,1], p = 5, q = 1`) means the node of the tree with that
# value, as its judge does. A list or a tree that runs in a circle is walked once round, not forever.
PY_NODE_HELPERS = """
_SN_CAP = 3000   # a tree in a circle, or one node shared deep, printed no longer than the runner's reply
def _sn_cls(names):
    for _n in names:
        _c = _ns.get(_n)
        if isinstance(_c, type):
            return _c
    return None
def _sn_names(shape):
    return (shape[1], "TreeNode" if shape[0].startswith("tree") else "ListNode")
def _sn_tree(v, names):
    cls = _sn_cls(names)
    if cls is None:
        raise RuntimeError("class %s is not defined" % names[0])
    if not isinstance(v, list) or not v or v[0] is None:
        return None
    root = cls(v[0])
    q, i = [root], 1
    while q and i < len(v):
        node = q.pop(0)
        for side in ("left", "right"):
            if i >= len(v):
                break
            x, i = v[i], i + 1
            if x is not None:
                child = cls(x)
                setattr(node, side, child)
                q.append(child)
    return root
def _sn_chain(v, names):
    cls = _sn_cls(names)
    if cls is None:
        raise RuntimeError("class %s is not defined" % names[0])
    if not isinstance(v, list):
        return None
    head = None
    for x in reversed(v):
        head = cls(x, head)
    return head
def _sn_one(shape, v):
    return (_sn_tree if shape[0].startswith("tree") else _sn_chain)(v, _sn_names(shape))
def _sn_build(shape, v):
    if v is None:
        return None
    if shape[0].endswith("s"):   # a list of them (List[ListNode])
        return [_sn_one(shape, x) for x in v] if isinstance(v, list) else v
    return _sn_one(shape, v)
def _sn_many_lists(v):
    return isinstance(v, list) and all(isinstance(x, list) for x in v)
def _sn_one_of(shape, root, value):
    # a node a statement names by its value: the one of the built structure with that value, or, where the
    # structure does not hold it (LeetCode 1644 states p = 10 for a tree without it), a node of its own
    got = _sn_find(root, value)
    return got if got is not None else _sn_one(shape, [value])
def _sn_find(root, value):
    seen, q = set(), [root]
    while q:
        node = q.pop(0)
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if getattr(node, "val", None) == value:
            return node
        for side in ("left", "right", "next"):
            q.append(getattr(node, side, None))
    return None
def _sn_made(shape, v):
    # whether this argument's example is the node's own list (or lists), rather than the value of a node in
    # the tree the first argument builds (`root = [3,5,1], p = 5`)
    return _sn_many_lists(v) if shape[0].endswith("s") else isinstance(v, list)
def _sn_args(shapes, args):
    out, root = list(args), None
    for k, a in enumerate(args):
        shape = shapes[k] if k < len(shapes) else None
        if shape and _sn_made(shape, a):
            out[k] = _sn_build(shape, a)
            if root is None:
                root = out[k][0] if isinstance(out[k], list) and out[k] else out[k]
    for k, a in enumerate(args):   # a node the statement gives by its value: the one of the tree that was built
        shape = shapes[k] if k < len(shapes) else None
        if shape and not _sn_made(shape, a):
            out[k] = [_sn_one_of(shape, root, x) for x in a] if shape[0].endswith("s") and isinstance(a, list) \
                else _sn_one_of(shape, root, a)
    return out
def _sn_out(v, depth=0):
    if v is None or isinstance(v, (bool, int, float, str)) or depth > 8:
        return v
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_sn_out(x, depth + 1) for x in v]
    if isinstance(v, dict):
        return {k: _sn_out(x, depth + 1) for k, x in v.items()}
    if not hasattr(v, "val"):
        return v
    if hasattr(v, "left") or hasattr(v, "right"):
        # no set of what has been seen here: an answer that memoizes its subtrees hangs the same node in two
        # places and a judge writes it in both. _SN_CAP is what stops a tree made in a circle
        out, q = [], [v]
        while q and len(out) < _SN_CAP:
            node = q.pop(0)
            if node is None:
                out.append(None)
                continue
            out.append(_sn_out(getattr(node, "val", None), depth + 1))
            q.append(getattr(node, "left", None))
            q.append(getattr(node, "right", None))
        while out and out[-1] is None:
            out.pop()
        return out
    if hasattr(v, "next"):
        out, seen, node = [], set(), v
        while node is not None and len(out) < _SN_CAP and id(node) not in seen:
            seen.add(id(node))
            out.append(_sn_out(getattr(node, "val", None), depth + 1))
            node = getattr(node, "next", None)
        return out
    return v
def _sn_said(shape, v):
    # as an example writes a node-shaped value: no node at all is the empty list, not nothing
    if shape is None:
        return v
    if v is None:
        return []
    if shape[0].endswith("s") and isinstance(v, list):
        return [[] if x is None else x for x in v]
    return v
def _sn_result(shape, v, expected):
    # a node the statement shows as a plain value is that node's value; as a list, the list of the whole node
    if shape is None:
        return v
    if not isinstance(expected, list):
        return None if v is None else (v[0] if isinstance(v, list) and v else v)
    return _sn_said(shape, v)
def _sn_after(args):
    return [_sn_said(_SHAPES[_k] if _k < len(_SHAPES) else None, _sn_out(_a)) for _k, _a in enumerate(args)]
"""


HARNESS_HEAD = """import json as _j, sys as _s
class _SnNull:
    def write(self, s):
        return len(s)
    def flush(self):
        pass
_real = _s.stdout
_ns = {"__name__": "sidenote_check", "exit": _s.exit, "quit": _s.exit}
if _PRELUDE:
    exec(_PRELUDE, _ns)
_s.stdout = _SnNull()
try:
    exec(compile(_CODE, "solution.py", "exec"), _ns)
finally:
    _s.stdout = _real
""" + PY_NODE_HELPERS

# One example at a time: the function, on a new `Solution` for each as a judge makes one.
HARNESS = HARNESS_HEAD + """
_fn = _FN
_cls = _ns.get("Solution")
for _i, _c in enumerate(_CASES):
    _args = _c.get("args", [])
    _s.stdout = _SnNull()
    try:
        _f = getattr(_cls(), _fn) if isinstance(_cls, type) and hasattr(_cls, _fn) else _ns[_fn]
        _args = _sn_args(_SHAPES, _args) if _SHAPES else _args
        _got = _f(*_args)
        _line = {"i": _i, "got": _j.loads(_j.dumps(_sn_result(_RESULT, _sn_out(_got), _c.get("expected")),
                                                   default=list))}
        if _got is None:   # it may have changed an argument in place
            _line["after"] = _j.loads(_j.dumps(_sn_after(_args), default=list))
    except BaseException as _e:
        _line = {"i": _i, "error": f"{type(_e).__name__}: {_e}"}
    finally:
        _s.stdout = _real
    print("\\n" + \"""" + CASE_MARK + """\" + _j.dumps(_line, default=str, ensure_ascii=False), flush=True)
"""


# A problem that asks for a class (LRUCache, MinStack): the calls the statement states, in order, on one
# object, the first of them the constructor. A call that raises stops the rest: what the object holds after it
# is no longer the problem's, and the check says which call it was.
DESIGN = HARNESS_HEAD + """
_obj = _ns.get(_CLS)
if not isinstance(_obj, type):
    print("\\n" + \"""" + CASE_MARK + """\" + _j.dumps({"i": 0, "error": "class %s is not defined" % _CLS}),
          flush=True)
    _s.exit(0)
_cls, _obj = _obj, None
for _i, _c in enumerate(_CALLS):
    _name, _args = _c["call"], _c.get("args", [])
    _shape, _r = _c.get("shapes") or [], _c.get("result")
    _s.stdout = _SnNull()
    try:
        if any(_shape):   # a tree or a list the statement writes as a level-order list, here too
            _args = _sn_args(_shape, _args)
        if _obj is None:
            _obj = _cls(*_args)
            _line = {"i": _i, "got": None}
        else:
            _f = getattr(_obj, _name)
            _line = {"i": _i, "got": _j.loads(_j.dumps(_sn_result(_r, _sn_out(_f(*_args)), _c.get("expected")),
                                                       default=list))}
    except BaseException as _e:
        _line = {"i": _i, "error": f"{type(_e).__name__}: {_e}"}
    finally:
        _s.stdout = _real
    print("\\n" + \"""" + CASE_MARK + """\" + _j.dumps(_line, default=str, ensure_ascii=False), flush=True)
    if "error" in _line:
        break
"""


def py_program(code: str) -> str:
    return f"_CODE = {code!r}\n" + PY_PROGRAM


def design_harness(code: str, cls: str, calls: list) -> str:
    """The answer's class, called as the statement's own example calls it. A call may carry the "shapes" of its
    arguments and the "result" of the method, as an example's function call does."""
    return (f"_CODE = {code!r}\n_CLS = {cls!r}\n_CALLS = {json.dumps(calls, ensure_ascii=False)!r}\n"
            f"_PRELUDE = {PY_JUDGE_PRELUDE + PY_NODE_CLASSES!r}\n_SHAPES = []\n_RESULT = None\n"
            f"import json as _jc\n_CALLS = _jc.loads(_CALLS)\n" + DESIGN)


def harness(code: str, function: str, cases: list, shapes: list | None = None, result: list | None = None) -> str:
    prelude = PY_JUDGE_PRELUDE if _leetcode_form(code, function) else ""
    # the classes the examples are built with, unless the answer defines its own: also when nothing declares a
    # node and the answer only builds one (`return TreeNode(...)` with no annotation), since that name is the
    # judge's to provide
    if any(shapes or ()) or result or re.search(r"\b(?:TreeNode|ListNode)\b", code):
        prelude += PY_NODE_CLASSES
    return (f"_CODE = {code!r}\n_FN = {function!r}\n_CASES = {json.dumps(cases[:MAX_CASES], ensure_ascii=False)!r}\n"
            f"_PRELUDE = {prelude!r}\n_SHAPES = {shapes or []!r}\n_RESULT = {result!r}\n"
            f"import json as _jc\n_CASES = _jc.loads(_CASES)\n" + HARNESS)


def _py_mask(code: str) -> str:
    """Python source with its comments and string literals blanked out (lines and positions kept)."""
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c == "#":
            j = code.find("\n", i)
            j = n if j < 0 else j
        elif code.startswith(('"""', "'''"), i):
            j = code.find(code[i:i + 3], i + 3)
            j = n if j < 0 else j + 3
        elif c in "\"'":
            j = i + 1
            while j < n and code[j] not in (c, "\n"):
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            out.append(c)
            i += 1
            continue
        out.append(re.sub(r"[^\n]", " ", code[i:j]))
        i = j
    return "".join(out)


def _py_decl(code: str, function: str) -> tuple[list | None, str | None, tuple] | None:
    """([(name, annotation, has a default)] of the parameters but self, None for *args; the return annotation or
    None; ({parameter: the type its docstring gives}, its :rtype:), as LeetCode's Python 2 template writes
    `:type root: TreeNode`) of the def that runs. None when there is no such def."""
    masked = _py_mask(code)
    found = []
    for m in re.finditer(r"^([ \t]*)def[ \t]+" + re.escape(function) + r"[ \t]*\(", masked, re.M):
        end = _closing(masked, m.end() - 1, "(", ")")
        # the whole span between -> and the : that ends the head, matched on the masked code (a quoted
        # annotation may hold a colon) and read off the real one (where it is masked to spaces)
        tail = re.match(r"\s*(?:->([^:]*))?\s*:", masked[end:], re.S) if end > 0 else None
        if not tail:
            continue
        ret = code[end + tail.start(1):end + tail.end(1)].strip() if tail.group(1) is not None else None
        params = []
        # split where strings are masked (a default of "," is no separator), read off the real source
        spans, at = [], m.end()
        for piece in _split_params(masked[m.end():end - 1]):
            spans.append(code[at:at + len(piece)])
            at += len(piece) + 1
        for part in spans:
            part = part.strip()
            if not part or part in ("/", "*"):
                continue
            if part.startswith("*"):
                params = None
                break
            name, _, rest = part.partition(":")
            params.append((name.split("=")[0].strip(), rest.split("=")[0].strip(), "=" in part))
        if params and params[0][0] in ("self", "cls"):
            params = params[1:]
        # the body starts after the colon that ends the head: from `end` it would start at that colon itself,
        # which the pattern below takes for the first line of the body and leaves nothing
        body = re.match(r".*?(?=^[ \t]{0,%d}\S)" % len(m.group(1)), code[end + tail.end():] + "\nx", re.S | re.M)
        text = body.group(0) if body else ""
        doc = (dict((n, t.strip()) for n, t in re.findall(r":type\s+(\w+):\s*([^\n]+)", text)),
               (re.search(r":rtype:\s*(\S+)", text) or [None, None])[1])
        found.append((m.start(), bool(m.group(1)), params, ret, doc))
    if not found:
        return None
    # Python keeps the last definition: the last method of the last `class Solution`, or the last top-level def
    cls = [c.start() for c in re.finditer(r"^class\s+Solution\b", masked, re.M)]
    methods = [f for f in found if f[1] and cls and f[0] > cls[-1]]
    top = [f for f in found if not f[1]]
    pick = methods[-1] if methods else top[-1] if top else found[-1]
    return pick[2], pick[3], pick[4]
