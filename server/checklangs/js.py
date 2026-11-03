"""JavaScript and TypeScript (the runner strips TypeScript's types): the harness that calls the answer's
function on each example, on a new `Solution` for each as a judge makes one, and the harness that builds the
class a problem asks for and calls it as the statement's own example does. A tree or a linked list is built
from the level-order list the statement writes."""
from __future__ import annotations

import json
import re

from .common import CASE_MARK, MAX_CASES, _closing, _mask, _split_params


# ---------- JavaScript and TypeScript (the runner strips TypeScript's types) ----------

# LeetCode's judge provides these classes and writes a tree or a list as the level-order list the statement
# shows (`root = [3,9,20,null,null,15,7]`, `head = [1,2,3]`), so an answer written there uses them without
# defining them. They go in before the answer, which may build nodes while it loads, and as a property of the
# global object rather than as a declaration: an answer that declares a class of that name itself declares it in
# its own module, which shadows this one for all of the answer's code and for the harness, so the one that runs
# is still the answer's, where a second declaration of the name would not even parse. TypeScript's class is
# this same object once its types are stripped, so one definition serves both languages.
JS_NODE_CLASSES = {
    "tree": """globalThis.%(cls)s = function %(cls)s(val, left, right) {
  this.val = val === undefined ? 0 : val;
  this.left = left === undefined ? null : left;
  this.right = right === undefined ? null : right;
};
""",
    "list": """globalThis.%(cls)s = function %(cls)s(val, next) {
  this.val = val === undefined ? 0 : val;
  this.next = next === undefined ? null : next;
};
""",
}


# In the harness, so the answer's own names cannot be touched: the example's list becomes nodes of the class the
# answer uses, and a node that comes back becomes a list again, so the comparing stays on JSON values. A
# statement that gives a node by its value instead of its list (`root = [3,5,1], p = 5, q = 1`) means the node
# of the tree with that value, as its judge does. A list or a tree that runs in a circle (a cycle question
# builds one, and a circular list is what one of them returns) is walked once round, not forever. Nothing here
# reads a node's type, which it has none of at runtime: the shapes the declaration gave are what says an
# argument is one, and for a result the shape also says which of the two it is, so a node class of the answer's
# own that leaves a field out is still written the way a statement writes it.
JS_NODE_HELPERS = """
  const _snCap = 3000;   // printed no longer than the runner's reply, whatever a circle or a shared node makes
  const _snKind = (shape) => (shape ? (shape[0].startsWith("tree") ? "tree" : "list") : "");
  const _snCls = (shape) => {
    const cls = _snClasses[shape[1]];
    if (!cls) throw new Error("class " + shape[1] + " is not defined");
    return cls;
  };
  const _snTree = (v, shape) => {
    if (!Array.isArray(v) || !v.length || v[0] === null) return null;
    const cls = _snCls(shape);
    const root = new cls(v[0]);
    const q = [root];
    let i = 1;
    while (q.length && i < v.length) {
      const node = q.shift();
      for (const side of ["left", "right"]) {
        if (i >= v.length) break;
        const x = v[i++];
        if (x !== null) {
          const child = new cls(x);
          node[side] = child;
          q.push(child);
        }
      }
    }
    return root;
  };
  const _snChain = (v, shape) => {
    if (!Array.isArray(v)) return null;
    const cls = _snCls(shape);
    let head = null;
    for (let i = v.length - 1; i >= 0; i--) {
      const node = new cls(v[i]);
      node.next = head;
      head = node;
    }
    return head;
  };
  const _snOne = (shape, v) => (_snKind(shape) === "tree" ? _snTree : _snChain)(v, shape);
  const _snBuild = (shape, v) => {
    if (v === null || v === undefined) return null;
    if (shape[0].endsWith("s")) return Array.isArray(v) ? v.map((x) => _snOne(shape, x)) : v;
    return _snOne(shape, v);
  };
  const _snManyLists = (v) => Array.isArray(v) && v.every((x) => Array.isArray(x));
  const _snMade = (shape, v) => (shape[0].endsWith("s") ? _snManyLists(v) : Array.isArray(v));
  const _snFind = (shape, root, value) => {
    if (value === null || value === undefined) return null;   // an example that writes no node at all
    const seen = new Set();
    const q = [root];
    while (q.length) {
      const node = q.shift();
      if (node === null || node === undefined || seen.has(node)) continue;
      seen.add(node);
      if (node.val === value) return node;
      q.push(node.left, node.right, node.next);
    }
    return _snOne(shape, [value]);   // a value the tree does not hold is a node on its own, as its judge makes
  };
  const _snArgs = (shapes, args) => {
    const out = args.slice();
    let root = null;
    args.forEach((a, k) => {
      const shape = k < shapes.length ? shapes[k] : null;
      if (!shape || !_snMade(shape, a)) return;
      out[k] = _snBuild(shape, a);
      if (root === null) root = Array.isArray(out[k]) && out[k].length ? out[k][0] : out[k];
    });
    args.forEach((a, k) => {   // a node the statement gives by its value: the one of the tree that was built
      const shape = k < shapes.length ? shapes[k] : null;
      if (!shape || _snMade(shape, a)) return;
      if (shape[0].endsWith("s") && Array.isArray(a)) {   // the same rule for each element of a list of nodes
        out[k] = a.map((x) => _snFind(shape, root, x));
        return;
      }
      // with no structure built, no node is meant here: a shape of one node can come from a name a data
      // structure the answer carries along uses as its own (a red-black tree's `x.left`), and then the
      // example's own value is what the function wants, while a list of them is only ever a declared type
      if (root !== null) out[k] = _snFind(shape, root, a);
    });
    return out;
  };
  const _snOut = (v, kind = "", depth = 0) => {
    if (v === null || typeof v !== "object" || depth > 8) return v;
    if (Array.isArray(v)) return v.map((x) => _snOut(x, kind, depth + 1));
    if (v instanceof Set || ArrayBuffer.isView(v)) return Array.from(v).map((x) => _snOut(x, "", depth + 1));
    if (v instanceof Map) return Object.fromEntries(Array.from(v, ([k, x]) => [k, _snOut(x, "", depth + 1)]));
    const node = kind === "" && "val" in v;
    if (kind === "tree" || (node && ("left" in v || "right" in v))) {
      // no seen set here: an answer that memoizes its subtrees (every full binary tree of n nodes) hangs the
      // same node in two places, and a judge writes it in both. _snCap is what stops a tree made in a circle
      const out = [];
      const q = [v];
      while (q.length && out.length < _snCap) {
        const at = q.shift();
        if (at === null || at === undefined) {
          out.push(null);
          continue;
        }
        out.push(_snOut(at.val, "", depth + 1));
        q.push(at.left, at.right);
      }
      while (out.length && out[out.length - 1] === null) out.pop();   // as a statement writes a tree
      return out;
    }
    if (kind === "list" || (node && "next" in v)) {
      const out = [];
      const seen = new Set();
      let at = v;
      while (at !== null && at !== undefined && out.length < _snCap && !seen.has(at)) {
        seen.add(at);
        out.push(_snOut(at.val, "", depth + 1));
        at = at.next;
      }
      return out;
    }
    return v;
  };
  const _snSaid = (shape, v) => {
    // as an example writes a node-shaped value: no node at all is the empty list, not nothing
    if (!shape) return v;
    if (v === null || v === undefined) return [];
    if (shape[0].endsWith("s") && Array.isArray(v)) return v.map((x) => (x === null ? [] : x));
    return v;
  };
  const _snResult = (shape, v, expected) => {
    // a node the statement shows as a plain value is that node's value; as a list, the list of the whole node
    if (!shape) return v;
    if (!Array.isArray(expected)) return v === null || v === undefined ? null
      : Array.isArray(v) && v.length ? v[0] : v;
    return _snSaid(shape, v);
  };
  const _snAfter = (shapes, args) => args.map((a, k) => {
    const shape = k < shapes.length ? shapes[k] : null;
    return _snSaid(shape, _snOut(a, _snKind(shape)));
  });
"""


# What the two harnesses below share: the write the prologue kept for the results, the muting of what the answer
# prints while it runs (a long table of its own would push the results past the runner's limit), the values JSON
# has no form of its own for, and the node helpers.
JS_HARNESS_HEAD = """
  const _w = globalThis.__snWrite;
  const _mute = () => {
    const saved = [console.log, console.info, console.debug, process.stdout.write];
    console.log = console.info = console.debug = () => {};
    process.stdout.write = () => true;
    return () => { [console.log, console.info, console.debug, process.stdout.write] = saved; };
  };
  const _plain = (k, v) => ArrayBuffer.isView(v) || v instanceof Set ? Array.from(v)
    : v instanceof Map ? Object.fromEntries(v) : typeof v === "bigint" ? "@@SNBIG" + v + "@@" : v;
  // A BigInt as the number it is: through Number(), 9007199254740993n came out ...992 and a right answer failed
  const _snJson = (rec) => JSON.stringify(rec, _plain).replace(/"@@SNBIG(-?\\d+)@@"/g, "$1");
""" + JS_NODE_HELPERS


# A method, a class field holding a function or a static method of `Solution` (a new one for each example, as a
# judge makes), or the function; what the answer prints itself while it runs is thrown away (see HARNESS).
JS_HARNESS = """
;(async () => {
  const _cases = JSON.parse(%(cases)s);
  const _shapes = %(shapes)s;
  const _result = %(result)s;
  const _snClasses = %(classes)s;
""" + JS_HARNESS_HEAD + """
  const _make = () => {
    if (typeof Solution === "function") {
      if (typeof Solution.%(fn)s === "function") return (...a) => Solution.%(fn)s(...a);
      const o = new Solution();
      if (typeof o.%(fn)s === "function") return (...a) => o.%(fn)s(...a);
    }
    return %(fn)s;
  };
  for (let i = 0; i < _cases.length; i++) {
    const _c = _cases[i];
    let line;
    const unmute = _mute();
    try {
      const args = _shapes.length ? _snArgs(_shapes, _c.args || []) : _c.args || [];
      const got = await _make()(...args);   // an async answer is judged by what it resolves to, not by its promise
      const rec = {i, got: _snResult(_result, _snOut(got === undefined ? null : got, _snKind(_result)), _c.expected)};
      if (got === undefined || got === null) rec.after = _snAfter(_shapes, args);   // it may have changed an argument
      line = _snJson(rec);
    } catch (e) {
      line = JSON.stringify({i, error: String((e && e.message) || e).slice(0, 200)});
    } finally {
      unmute();
    }
    _w("\\n%(mark)s" + line + "\\n");
  }
})();
"""


# A problem that asks for a class (LRUCache, MinStack): the calls the statement states, in order, on one object,
# the first of them the constructor. `new` builds either of the forms a LeetCode answer is written in, a class
# declaration and the older constructor function with its methods on the prototype, and a method is taken off
# the object itself, so one inherited from a class the answer extends is called as well. A call that raises
# stops the rest: what the object holds after it is no longer the problem's, and the check says which call it was.
JS_DESIGN = """
;(() => {
  const _calls = JSON.parse(%(calls)s);
  const _snClasses = %(classes)s;
""" + JS_HARNESS_HEAD + """
  const _cls = typeof %(cls)s === "undefined" ? null : %(cls)s;
  let _obj = null;
  for (let i = 0; i < _calls.length; i++) {
    const _c = _calls[i];
    let line, stopped = false;
    const unmute = _mute();
    try {
      if (_cls === null) throw new Error("class %(cls)s is not defined");
      const shapes = _c.shapes || [];   // a tree or a list the statement writes as a level-order list, here too
      const args = shapes.some((s) => s) ? _snArgs(shapes, _c.args || []) : _c.args || [];
      if (_obj === null) {
        _obj = new _cls(...args);
        line = JSON.stringify({i, got: null});   // what a constructor gives back is no result
      } else if (typeof _obj[_c.call] !== "function") {
        throw new Error("method " + _c.call + " is not defined");
      } else {
        const got = _obj[_c.call](...args);
        const out = _snOut(got === undefined ? null : got, _snKind(_c.result));
        line = _snJson({i, got: _snResult(_c.result, out, _c.expected)});
      }
    } catch (e) {
      line = JSON.stringify({i, error: String((e && e.message) || e).slice(0, 200)});
      stopped = true;
    } finally {
      unmute();
    }
    _w("\\n%(mark)s" + line + "\\n");
    if (stopped) break;
  }
})();
"""


# Before the answer: what it prints while it loads is thrown away too (a long output of its own pushed the results
# past the runner's limit), the real write kept for the results.
JS_PROLOGUE = ("globalThis.__snWrite = process.stdout.write.bind(process.stdout); "
               "console.log = console.info = console.debug = () => {}; process.stdout.write = () => true;\n")


JS_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def _js_nodes(shapes: list | None, result: list | None, code: str = "") -> tuple[str, str] | None:
    """(the definitions of the node classes the examples are built with, the table the harness looks them up in),
    None when a shape is one this cannot build: a class that would have to be a tree and a list at once, a kind
    of node that is neither, or a name that is no identifier to begin with."""
    kinds = {}
    for shape in list(shapes or ()) + [result]:
        if not shape:
            continue
        if len(shape) != 2 or shape[0] not in ("tree", "trees", "list", "lists") \
                or not JS_IDENT.fullmatch(shape[1] or ""):
            return None
        kind = "tree" if shape[0].startswith("tree") else "list"
        if kinds.setdefault(shape[1], kind) != kind:
            return None
    # a class the answer only builds (`new TreeNode(...)` from a plain array) is the judge's to provide too
    for cls, kind in (("TreeNode", "tree"), ("ListNode", "list")):
        if cls not in kinds and re.search(r"\b%s\b" % cls, code):
            kinds[cls] = kind
    text = "".join(JS_NODE_CLASSES[kind] % {"cls": cls} for cls, kind in kinds.items())
    # the class the answer declares itself, which shadows the one above, or that one
    table = ", ".join(f'{json.dumps(cls)}: typeof {cls} === "undefined" ? null : {cls}' for cls in kinds)
    return text, "{" + table + "}"


def js_harness(code: str, function: str, cases: list, shapes: list | None = None,
               result: list | None = None) -> str | None:
    """The answer with a harness after it that calls `function` on each example, None when a shape the
    declaration gave is not one the examples can be made into."""
    nodes = _js_nodes(shapes, result, code)
    if nodes is None:
        return None
    classes, table = nodes
    return JS_PROLOGUE + classes + code + JS_HARNESS % {
        "cases": json.dumps(json.dumps(cases[:MAX_CASES], ensure_ascii=False)), "fn": function, "mark": CASE_MARK,
        "shapes": json.dumps(shapes or []), "result": json.dumps(result), "classes": table}


def _js_class_body(code: str, cls: str) -> str | None:
    """The part of an answer that is the class `cls`, so what its own constructor declares is not read off a
    helper class beside it. None when the class is no declaration but the older constructor function, whose
    methods hang on its prototype outside of it."""
    masked = _mask(code)
    m = re.search(r"\bclass\s+%s\b" % re.escape(cls), masked)
    if not m:
        return None
    brace = masked.find("{", m.end())
    end = _closing(masked, brace, "{", "}") if brace >= 0 else -1
    return code[m.start():end] if end > 0 else code


def _js_ctor(code: str, cls: str) -> dict | None:
    """What the constructor declares about its arguments, read as a method's declaration is: the `constructor`
    of the class, or the function of the class's own name in the older form. Its caller reads a method by the
    name the statement calls it, and the constructor by Python's name for it, which stands for none here."""
    from ..codecheck import _declaration   # here: that module imports this one
    # either language name takes the same path there: the runner strips TypeScript's types and runs JavaScript
    body = _js_class_body(code, cls)
    return _declaration("typescript", body, "constructor") if body is not None \
        else _declaration("typescript", code, cls)


def design_harness(code: str, cls: str, calls: list) -> str | None:
    """The answer's class, called as the statement's own example calls it: the calls in order on one object, the
    first of them the constructor. A call may carry the "shapes" of its arguments and the "result" of its method,
    as an example's function call does. None when the class cannot be called by its name, when a shape a call
    carries is not one the examples can be made into, or when the constructor declares a type they cannot fill."""
    if not JS_IDENT.fullmatch(cls or "") or not calls:
        return None
    decl = _js_ctor(code, cls)
    if decl and decl["foreign"]:   # as the function path does: say so rather than run it wrong
        return None
    first = dict(calls[0])
    if decl and not any(first.get("shapes") or ()):
        first["shapes"] = decl.get("shapes") or []
        # a constructor that takes nothing: written [] on most problems and [null] on some
        if first.get("args") == [None] and decl.get("names") == []:
            first["args"] = []
    calls = [first] + list(calls[1:])
    # every call's arguments and what each gives back: the node classes the whole run needs are defined once
    shapes = [s for c in calls for s in (c.get("shapes") or [])] + [c.get("result") for c in calls]
    nodes = _js_nodes(shapes, None, code)
    if nodes is None:
        return None
    classes, table = nodes
    return JS_PROLOGUE + classes + code + JS_DESIGN % {
        "calls": json.dumps(json.dumps(calls, ensure_ascii=False)), "cls": cls, "mark": CASE_MARK,
        "classes": table}


JS_KEYWORDS = r"(?:(?:export|default|var|let|const|async|static|public|private|protected|readonly|override)\s+)*"


def _js_decl(code: str, function: str) -> tuple[list | None, str | None, str] | None:
    """([(name, TypeScript type)] of the parameters, None for a rest parameter; TypeScript's return type or None;
    the JSDoc comment right before the definition or "") of `function`: a function, a function or an arrow assigned
    to it, or a method. None when it is not found."""
    masked = _mask(code)
    n = re.escape(function)
    found = []   # (position, the declaration): the last one is the one that runs
    forms = ((rf"\bfunction\s*\*?\s*{n}\s*(?:<[^>]*>)?\s*\(", "{"),
             (rf"\b{n}\s*(?::[^=\n]+)?=\s*(?:async\s+)?function\b\s*\*?\s*[\w$]*\s*(?:<[^>]*>)?\s*\(", "{"),
             (rf"\b{n}\s*(?::[^=\n]+)?=\s*(?:async\s+)?(?:<[^>]*>\s*)?\(", "=>"),
             (rf"^[ \t]*(?:(?:public|private|protected|static|async|readonly|override|get)\s+)*{n}\s*(?:<[^>]*>)?\s*\(", "{"))
    for form, opens in forms:
        for m in re.finditer(form, masked, re.M):
            end = _closing(masked, m.end() - 1, "(", ")")
            tail = re.match(r"\s*(?::\s*([^={]+?))?\s*(=>|\{)", masked[end:], re.S) if end > 0 else None
            if not tail or tail.group(2) != opens:
                continue
            ret = code[end + tail.start(1):end + tail.end(1)].strip() if tail.group(1) else None
            doc = re.search(r"/\*\*((?:(?!\*/).)*)\*/[\s;]*" + JS_KEYWORDS + r"$", code[:m.start()], re.S)
            params = []
            for part in _split_params(code[m.end():end - 1]):
                part = part.strip()
                if not part:   # the comma a parameter list written over several lines ends with
                    continue
                if part.startswith("..."):
                    params = None
                    break
                pm = re.match(r"([\w$]+)(\?)?\s*(?::\s*(.*?))?\s*(=.*)?$", part, re.S)
                params.append((pm.group(1), pm.group(3) or "", bool(pm.group(2) or pm.group(4))) if pm else ("", "", False))
            found.append((m.start(), (params, ret, doc.group(1) if doc else "")))
    for m in re.finditer(rf"\b{n}\s*=\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>", masked):   # one parameter, no parentheses
        doc = re.search(r"/\*\*((?:(?!\*/).)*)\*/[\s;]*" + JS_KEYWORDS + r"$", code[:m.start()], re.S)
        found.append((m.start(), ([(m.group(1), "", False)], None, doc.group(1) if doc else "")))
    return max(found, key=lambda f: f[0])[1] if found else None
