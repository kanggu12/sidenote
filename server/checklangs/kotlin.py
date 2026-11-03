"""Kotlin: the answer's function, and a main beside it that calls it on each example with the values the
example holds, made into the types it declares."""
from __future__ import annotations

import re

from .common import IDENT, CASE_MARK, MAX_CASES, _closing, _definitions, _finite, _mask, _owner, _split_top


# ---------- Kotlin ----------

KOTLIN_MAIN = """
fun _snStr(s: String): String {
    val b = StringBuilder("\\"")
    for (c in s) {
        when {
            c == '"' || c == '\\\\' -> b.append('\\\\').append(c)
            c.code < 0x20 -> b.append(String.format("\\\\u%%04x", c.code))
            else -> b.append(c)
        }
    }
    return b.append('"').toString()
}

fun _snJson(v: Any?): String = when (v) {
    null -> "null"
    is String -> _snStr(v)
    is Char -> _snStr(v.toString())
    is Boolean -> v.toString()
    is Double -> if (v.isFinite()) v.toString() else "null"
    is Float -> if (v.isFinite()) v.toDouble().toString() else "null"
    is Number -> v.toString()
    is IntArray -> v.joinToString(",", "[", "]")
    is LongArray -> v.joinToString(",", "[", "]")
    is ShortArray -> v.joinToString(",", "[", "]")
    is ByteArray -> v.joinToString(",", "[", "]")
    is BooleanArray -> v.joinToString(",", "[", "]")
    is DoubleArray -> v.joinToString(",", "[", "]") { _snJson(it) }
    is FloatArray -> v.joinToString(",", "[", "]") { _snJson(it) }
    is CharArray -> v.joinToString(",", "[", "]") { _snJson(it) }
    is Array<*> -> v.joinToString(",", "[", "]") { _snJson(it) }
    is Iterable<*> -> v.joinToString(",", "[", "]") { _snJson(it) }
%(json)s    else -> _snStr(v.toString())
}

val _snReal: java.io.PrintStream = System.out
val _snNull = java.io.PrintStream(java.io.OutputStream.nullOutputStream())

fun _snOut(s: String) { _snReal.println("\\n%(mark)s" + s); _snReal.flush() }
%(nodes)s
fun main() {
%(body)s
}
"""


KOTLIN_ARRAYS = {"IntArray": ("intArrayOf", "Int"), "LongArray": ("longArrayOf", "Long"),
                 "DoubleArray": ("doubleArrayOf", "Double"), "FloatArray": ("floatArrayOf", "Float"),
                 "BooleanArray": ("booleanArrayOf", "Boolean"), "CharArray": ("charArrayOf", "Char"),
                 "ShortArray": ("shortArrayOf", "Short"), "ByteArray": ("byteArrayOf", "Byte")}


KOTLIN_SCALARS = {"Int", "Long", "Double", "Float", "Boolean", "Char", "String", "Short", "Byte"}


KOTLIN_MAKE = {"Array": "arrayOf", "List": "listOf", "Collection": "listOf", "MutableList": "mutableListOf",
               "ArrayList": "arrayListOf"}


KOTLIN_LIST_OF = re.compile(r"(%s)<(.+)>" % "|".join(KOTLIN_MAKE))


def _kotlin_type(t: str) -> str:
    """A Kotlin type as written here, `?` kept: Array<Int?> and Array<Int> are different types."""
    t = re.sub(r"\bkotlin\.(collections\.)?", "", t)
    return re.sub(r"\s*([<>,?])\s*", r"\1", " ".join(t.split()))


def _kotlin_definition(code: str, function: str, arity: int | None = None) \
        -> tuple[str, list[str], set, int, str, list[str]] | None:
    """(return type, parameter types, the vararg ones' positions, where the name is, the masked source, parameter
    names) of the function `function`, None when it is not found or not fillable; with `arity`, the overload that
    takes that many. A block body without a return type returns Unit; an expression body's type is not written
    ("?"). A vararg parameter's type is the array it arrives as."""
    masked = _mask(code)
    private = None
    for name, params, _ in _definitions(masked, function, r"\bfun\s+(?:<[^>]*>\s*)?",
                                        r"\s*(?::\s*[^={\n]+?)?\s*[={]"):
        parts = _split_top(params)
        if arity is not None and len(parts) != arity:
            continue
        tail = re.match(r"\s*(?::\s*([^={\n]+?))?\s*([={])", masked[_closing(masked, masked.find("(", name), "(", ")"):], re.A)
        ret = _kotlin_type(tail.group(1)) if tail.group(1) else ("Unit" if tail.group(2) == "{" else "?")
        types, varargs, names = [], set(), []
        for k, part in enumerate(parts):
            pm = re.fullmatch(r"(vararg\s+)?(?:val\s+|var\s+)?([A-Za-z_]\w*)\s*:\s*(.+?)(?:\s*=.*)?", part.strip(), re.A | re.S)
            if not pm:
                return None
            t = _kotlin_type(pm.group(3))
            if pm.group(1):
                varargs.add(k)
                t = f"{t}Array" if t + "Array" in KOTLIN_ARRAYS else f"Array<{t}>"
            types.append(t)
            names.append(pm.group(2))
        decl = (ret, types, varargs, name, masked, names)
        if arity is None or not re.search(r"\bprivate\b", masked[masked.rfind("\n", 0, name) + 1:name]):
            return decl
        private = private or decl   # a private helper of the same arity: called only when there is nothing else
    return private


def _kotlin_signature(code: str, function: str, arity: int | None = None) -> tuple[str, list[str]] | None:
    d = _kotlin_definition(code, function, arity)
    return (d[0], d[1]) if d else None


def _kotlin_str(s: str) -> str:
    out = []
    for ch in s:
        if ch in '"\\$':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _kotlin_value(t: str, v) -> str | None:
    """A Kotlin expression of type `t` for the JSON value `v`, None when the type is not one the check knows."""
    if t.endswith("?"):
        return "null" if v is None else _kotlin_value(t[:-1], v)
    if t in KOTLIN_ARRAYS:
        make, elem = KOTLIN_ARRAYS[t]
        if not isinstance(v, list):
            return None
        items = [_kotlin_value(elem, x) for x in v]
        return None if None in items else f"{make}({', '.join(items)})"
    m = KOTLIN_LIST_OF.fullmatch(t)
    if m:
        kind, inner = m.groups()
        if not isinstance(v, list):
            return None
        items = [_kotlin_value(inner, x) for x in v]
        return None if None in items else f"{KOTLIN_MAKE[kind]}<{inner}>({', '.join(items)})"
    if t in ("Int", "Short", "Byte"):
        limit = {"Int": 2 ** 31, "Short": 2 ** 15, "Byte": 2 ** 7}[t]
        ok = isinstance(v, int) and not isinstance(v, bool) and -limit <= v < limit
        return (str(v) if t == "Int" else f"({v}).to{t}()") if ok else None
    if t == "Long":
        return f"{v}L" if isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2 ** 63 else None
    if t in ("Double", "Float"):
        f = _finite(v)
        return None if f is None else repr(f) + ("f" if t == "Float" else "")
    if t == "Boolean":
        return ("true" if v else "false") if isinstance(v, bool) else None
    if t == "Char":
        if not (isinstance(v, str) and len(v) == 1 and 0x20 <= ord(v) <= 0xFFFF):
            return None
        return "'\\''" if v == "'" else "'\\\\'" if v == "\\" else f"'{v}'"
    if t == "String":
        return _kotlin_str(v) if isinstance(v, str) else None
    return None


def _kotlin_known(t: str) -> bool:
    t = t.rstrip("?")
    if t in KOTLIN_ARRAYS or t in KOTLIN_SCALARS:
        return True
    m = KOTLIN_LIST_OF.fullmatch(t)
    return bool(m) and _kotlin_known(m.group(2))


# ---------- a tree or a linked list as an example writes it ----------

# LeetCode's judge provides these classes and writes a tree or a list as the level-order list the statement
# shows (`root = [3,9,20,null,null,15,7]`, `head = [1,2,3]`), so an answer written there uses them without
# defining them. `val` is a keyword in Kotlin, which is why the field is in backticks. One of these goes in
# only where the answer declares no class of that name, since a name declared twice is an error in Kotlin.
KOTLIN_NODE_CLASSES = {"tree": """class TreeNode(var `val`: Int) {
    var left: TreeNode? = null
    var right: TreeNode? = null
}""", "list": """class ListNode(var `val`: Int) {
    var next: ListNode? = null
}"""}


# What the helpers set and read on a node, so a class of the answer's own that is missing one of them is a
# class the program written here would not compile against.
KOTLIN_NODE_FIELDS = {"tree": (r"var\s+left\b", r"var\s+right\b"), "list": (r"var\s+next\b",)}


# _snCap: a tree in a circle, or one node shared deep, printed no longer than the runner's reply (MAX_OUTPUT)
KOTLIN_NODE_SHARED = """const val _snCap = 3000

fun _snMany(v: Any?, one: (Any?) -> String): String {
    val xs = when (v) {
        is Array<*> -> v.toList()
        is Iterable<*> -> v.toList()
        else -> return "[]"
    }
    return xs.joinToString(",", "[", "]") { one(it) }
}"""


# Beside the answer: the example's list becomes nodes of the class the answer uses, and a node that comes back
# becomes a list again, so the comparing stays on JSON values. A statement that gives a node by its value
# instead of its list (`root = [3,5,1], p = 5`) means the node of the tree with that value, as its judge does.
# A tree or a list that runs in a circle (what a cycle question builds) is walked once round, not forever, and
# the queue is an ArrayList read by index, which holds the nulls a java.util.ArrayDeque refuses.
KOTLIN_NODE_HELPERS = {"tree": """fun _snTree(v: Array<Int?>): %(cls)s? {
    if (v.isEmpty() || v[0] == null) return null
    val root = %(cls)s(v[0]!!)
    val q = ArrayList<%(cls)s>()
    q.add(root)
    var k = 0
    var i = 1
    while (k < q.size && i < v.size) {
        val node = q[k]
        k++
        for (side in 0..1) {
            if (i >= v.size) break
            val x = v[i]
            i++
            if (x != null) {
                val child = %(cls)s(x)
                if (side == 0) node.left = child else node.right = child
                q.add(child)
            }
        }
    }
    return root
}

fun _snTreeFind(root: %(cls)s?, value: Int): %(cls)s? {
    val seen = java.util.IdentityHashMap<%(cls)s, Boolean>()
    val q = ArrayList<%(cls)s>()
    if (root != null) q.add(root)
    var k = 0
    while (k < q.size) {
        val node = q[k]
        k++
        if (seen.put(node, true) != null) continue
        if (node.`val` == value) return node
        node.left?.let { q.add(it) }
        node.right?.let { q.add(it) }
    }
    // a statement may name a value the structure does not hold (LeetCode 1644 states p = 10 for a tree
    // without it): its judge hands the answer a node of that value all the same
    return if (root == null) null else %(cls)s(value)
}

fun _snTreeJson(v: Any?): String {
    // no record of what has been seen here: an answer that memoizes its subtrees hangs the same node in two
    // places and a judge writes it in both. _snCap is what stops a tree made in a circle
    val root = v as? %(cls)s ?: return "[]"
    val out = ArrayList<String>()
    val q = ArrayList<%(cls)s?>()
    q.add(root)
    var k = 0
    while (k < q.size && out.size < _snCap) {
        val node = q[k]
        k++
        if (node == null) {
            out.add("null")
            continue
        }
        out.add(node.`val`.toString())
        q.add(node.left)
        q.add(node.right)
    }
    while (out.isNotEmpty() && out.last() == "null") out.removeAt(out.size - 1)
    return out.joinToString(",", "[", "]")
}

fun _snTreeVal(v: Any?): String = (v as? %(cls)s)?.`val`?.toString() ?: "null\"""",
                       "list": """fun _snChain(v: IntArray): %(cls)s? {
    var head: %(cls)s? = null
    for (k in v.indices.reversed()) {
        val node = %(cls)s(v[k])
        node.next = head
        head = node
    }
    return head
}

fun _snListFind(head: %(cls)s?, value: Int): %(cls)s? {
    val seen = java.util.IdentityHashMap<%(cls)s, Boolean>()
    var at = head
    while (at != null && seen.put(at, true) == null) {
        if (at.`val` == value) return at
        at = at.next
    }
    return if (head == null) null else %(cls)s(value)   // as above
}

fun _snListJson(v: Any?): String {
    val out = ArrayList<String>()
    val seen = java.util.IdentityHashMap<%(cls)s, Boolean>()
    var at = v as? %(cls)s
    while (at != null && out.size < _snCap && seen.put(at, true) == null) {
        out.add(at.`val`.toString())
        at = at.next
    }
    return out.joinToString(",", "[", "]")
}

fun _snListVal(v: Any?): String = (v as? %(cls)s)?.`val`?.toString() ?: "null\""""}


def _kotlin_one_arg(parts: list[str] | None) -> bool:
    """Whether a primary constructor of these parameters can be called with one value, as a node class's is."""
    return bool(parts) and all("=" in p for p in parts[1:])


def _kotlin_node_class(code: str, masked: str, kind: str, cls: str) -> str | None:
    """The node class to put beside the answer: LeetCode's own, or "" where the answer declares that class
    itself. None where neither can be done, which is better said than run wrong: a class of the answer's own
    that takes no single value or keeps none of the fields the helpers set, one declared inside another class
    (where the name here would be another type), or LeetCode's `Node`, which only its answer declares."""
    found = list(re.finditer(r"\bclass\s+" + re.escape(cls) + r"\b", masked))
    if not found:
        return KOTLIN_NODE_CLASSES[kind] if cls in ("TreeNode", "ListNode") else None
    top = [m for m in found if masked.count("{", 0, m.start()) == masked.count("}", 0, m.start())]
    if not top:
        return None
    at, params = top[0].end(), None
    for opening, closing in (("<", ">"), ("(", ")")):
        at += len(masked[at:]) - len(masked[at:].lstrip())
        if masked[at:at + 1] == opening:
            end = _closing(masked, at, opening, closing)
            if end < 0:
                return None
            if opening == "(":
                params = _split_top(masked[at + 1:end - 1], "([{<", ")]}>")
            at = end
    body = re.match(r"\s*(?::[^{\n]*)?\s*\{", masked[at:])
    end = _closing(masked, at + body.end() - 1, "{", "}") if body else at
    text = code[top[0].start():end if end > 0 else len(code)]
    ready = _kotlin_one_arg(params) and "`val`" in text \
        and all(re.search(f, text) for f in KOTLIN_NODE_FIELDS[kind])
    return "" if ready else None


def _kotlin_nodes(code: str, masked: str, shapes: list, result: list | None) -> tuple[str, dict] | None:
    """(what goes beside the answer for the trees and the lists in play, the class each kind of node is made
    of), ("", {}) where there are none. None where one of them cannot be built: two classes of one kind, whose
    helpers would take the same names, or a class the answer's own declaration rules out."""
    kinds: dict = {}
    for shape in list(shapes) + [result]:
        if shape:
            kind = "tree" if shape[0].startswith("tree") else "list"
            if kinds.setdefault(kind, shape[1]) != shape[1]:
                return None
    if not kinds:
        # a class the answer only builds (`TreeNode(1)` from a plain array) is the judge's to declare too; its
        # helpers are not written, so an answer whose own class of that name differs still compiles
        only = [KOTLIN_NODE_CLASSES[k] for k, c in (("tree", "TreeNode"), ("list", "ListNode"))
                if re.search(r"\b%s\b" % c, masked) and not re.search(r"\bclass\s+%s\b" % c, masked)]
        return ("\n" + "\n\n".join(only) + "\n" if only else ""), {}
    out = [KOTLIN_NODE_SHARED]
    for kind, cls in sorted(kinds.items()):
        node = _kotlin_node_class(code, masked, kind, cls)
        if node is None:
            return None
        out += [node, KOTLIN_NODE_HELPERS[kind] % {"cls": cls}]
    return "\n" + "\n\n".join(part for part in out if part) + "\n", kinds


def _kotlin_node_fits(t: str, shape: list) -> bool:
    """Whether the type `t` a declaration names is the shape's node class, or a list of them."""
    t = t.rstrip("?")
    if not shape[0].endswith("s"):
        return t == shape[1]
    m = KOTLIN_LIST_OF.fullmatch(t)
    return bool(m) and m.group(2).rstrip("?") == shape[1]


def _kotlin_node_given(shape: list, v) -> bool:
    """Whether this argument's example is the node's own level-order list (or one list for each node), rather
    than the value of a node of the structure another argument builds (`root = [3,5,1], p = 5`)."""
    if shape[0].endswith("s"):
        return isinstance(v, list) and all(isinstance(x, list) for x in v)
    return isinstance(v, list)


def _kotlin_node_value(t: str, v, shape: list) -> str | None:
    """A Kotlin expression of the type `t` the declaration names for the node (or the nodes) an example writes
    as a level-order list, None when that list holds anything but the values a node of these classes takes."""
    if not shape[0].endswith("s"):
        build = "_snTree" if shape[0].startswith("tree") else "_snChain"
        # a tree's list carries the nulls a missing child is written as, a linked list's carries none
        made = _kotlin_value("Array<Int?>" if build == "_snTree" else "IntArray", v)
        return None if made is None else f"{build}({made})" + ("" if t.endswith("?") else "!!")
    m = KOTLIN_LIST_OF.fullmatch(t.rstrip("?"))
    if not m or not isinstance(v, list):
        return None
    items = [_kotlin_node_value(m.group(2), x, [shape[0][:-1], shape[1]]) for x in v]
    return None if None in items else f"{KOTLIN_MAKE[m.group(1)]}<{m.group(2)}>({', '.join(items)})"


def _kotlin_node_find(t: str, v, shape: list, root: str) -> str | None:
    """A Kotlin expression for the node a statement gives by its value: the one of the structure `root` whose
    value is that, as its judge takes it. None when the example is no value a node of it holds."""
    if not shape[0].endswith("s"):
        find = "_snTreeFind" if shape[0].startswith("tree") else "_snListFind"
        made = _kotlin_value("Int", v)
        return None if made is None else f"{find}({root}, {made})" + ("" if t.endswith("?") else "!!")
    m = KOTLIN_LIST_OF.fullmatch(t.rstrip("?"))
    if not m or not isinstance(v, list):
        return None
    items = [_kotlin_node_find(m.group(2), x, [shape[0][:-1], shape[1]], root) for x in v]
    return None if None in items else f"{KOTLIN_MAKE[m.group(1)]}<{m.group(2)}>({', '.join(items)})"


def _kotlin_said(shape: list | None, name: str) -> str:
    """The Kotlin expression that prints a value as an example writes it: a node as its level-order list, and no
    node at all as the empty list; anything else as the JSON the judge compares."""
    if not shape:
        return f"_snJson({name})"
    one = "_snTreeJson" if shape[0].startswith("tree") else "_snListJson"
    return f"_snMany({name}, ::{one})" if shape[0].endswith("s") else f"{one}({name})"


def _kotlin_got(result: list | None, expected) -> str:
    """The Kotlin expression that prints what the function returned: a node the statement shows as a plain
    value, not as a list, as that node's own value, which is what its judge compares."""
    if result and not result[0].endswith("s") and not isinstance(expected, list):
        return ("_snTreeVal" if result[0].startswith("tree") else "_snListVal") + "(_r)"
    return _kotlin_said(result, "_r")


def _kotlin_class_body(masked: str, code: str, cls: str) -> tuple[str, list] | None:
    """(the source of the class `cls`, the types its primary constructor takes), None when it declares none of
    that name. A method is looked for inside it, so a helper class's method of the same name is not taken."""
    m = re.search(r"\bclass\s+" + re.escape(cls) + r"\b", masked)
    if m is None:
        return None
    at = m.end() + len(masked[m.end():]) - len(masked[m.end():].lstrip())
    types = []
    if masked[at:at + 1] == "(":
        end = _closing(masked, at, "(", ")")
        if end < 0:
            return None
        for part in _split_top(code[at + 1:end - 1], "([{<", ")]}>"):
            part = re.sub(r"^\s*(?:@\w+\s+)*(?:val|var)?\s*", "", part)
            if ":" not in part:
                return None
            types.append(_kotlin_type(part.split(":", 1)[1]))
        at = end
    opening = masked.find("{", at)
    if opening < 0:   # a class with no body of its own holds no method to call
        return code[m.start():at], types
    end = _closing(masked, opening, "{", "}")
    return code[m.start():end if end > 0 else len(code)], types


def design_harness(code: str, cls: str, calls: list) -> str | None:
    """The answer's class, built once and called as the statement's own example calls it. None when the class,
    a method of it, or a value an example gives cannot be made here, so the card says so instead."""
    masked = _mask(code)
    found = _kotlin_class_body(masked, code, cls)
    if found is None:
        return None
    body, ctor = found
    if re.search(r"\babstract\s+class\s+" + re.escape(cls) + r"\b", masked):
        return None
    lines, shapes, kinds = [], [], {}
    for i, c in enumerate(calls):
        args = c.get("args") or []
        if i == 0:   # the constructor, whose parameters the class header carries
            if len(args) != len(ctor):
                return None
            values = [_kotlin_value(t, a) for t, a in zip(ctor, args)]
            if None in values:
                return None
            lines.append(f'    _o = {cls}({", ".join(values)})\n'
                         f'    _snOut("{{\\"i\\":0,\\"got\\":null}}")')
            continue
        name = c.get("call") or ""
        if not IDENT.fullmatch(name):
            return None
        decl = _kotlin_definition(body, name, len(args))
        if decl is None:
            return None
        ret, params, varargs, _, _, _ = decl
        if len(args) != len(params) or not all(_kotlin_known(t) for t in params) \
                or ret not in ("Unit", "?") and not _kotlin_known(ret):
            return None
        values = [_kotlin_value(t, a) for t, a in zip(params, args)]
        if None in values:
            return None
        call = f'_o!!.{name}({", ".join(("*" if k in varargs else "") + v for k, v in enumerate(values))})'
        muted = f'System.setOut(_snNull); val _r: Any? = try {{ {call} }} finally {{ System.setOut(_snReal) }}'
        shown = "null" if ret == "Unit" else "if (_r is Unit) \"null\" else _snJson(_r)"
        lines.append(f'    {muted}; _snOut("{{\\"i\\":{i},\\"got\\":" + ({shown}) + "}}")')
    # one call that raises stops the rest: what the object holds after it is no longer the problem's
    guarded = []
    for i, line in enumerate(lines):
        guarded.append(f'    try {{\n{line}\n    }} catch (_e: Throwable) {{\n'
                       f'        _snOut("{{\\"i\\":{i},\\"error\\":" + _snStr(_e.toString()) + "}}")\n'
                       f'        return\n    }}')
    code = re.sub(r"\bfun\s+main\s*\(", "fun _snOwnMain(", code)
    # the object is declared outside the blocks, since each call is guarded on its own
    made = f'    var _o: {cls}? = null\n'
    return code + "\n" + KOTLIN_MAIN % {"mark": CASE_MARK, "body": made + "\n".join(guarded), "nodes": "",
                                        "json": ""}


def kotlin_harness(code: str, function: str, cases: list, shapes: list | None = None, result: list | None = None) -> str | None:
    """The answer's Kotlin with a main that calls `function` on each example, None when its declaration cannot be
    filled from the examples (see cpp_harness)."""
    arity = len(cases[0].get("args") or []) if cases and isinstance(cases[0].get("args"), list) else None
    found = _kotlin_definition(code, function, arity)
    if found is None:
        return None
    ret, params, varargs, name, masked, _ = found
    void = ret == "Unit"
    shapes = [shapes[k] if shapes and k < len(shapes) else None for k in range(len(params))]
    if not all(_kotlin_known(t) or s and _kotlin_node_fits(t, s) for t, s in zip(params, shapes)) \
            or ret not in ("Unit", "?") and not (_kotlin_known(ret) or result and _kotlin_node_fits(ret, result)):
        return None
    owner = _owner(masked, name)   # the class that holds the function itself, "" for a top-level one
    if owner is None:
        return None
    nodes = _kotlin_nodes(code, masked, shapes, result)
    if nodes is None:
        return None
    helpers, kinds = nodes
    single = owner and re.search(r"\bobject\s+" + re.escape(owner) + r"\b", masked)   # an object is not made
    target = "" if not owner else f"{owner}." if single else f"{owner}()."
    body = []
    for i, c in enumerate(cases[:MAX_CASES]):
        args = c.get("args") or []
        if not isinstance(args, list) or len(args) != len(params):
            return None
        values, finds = [None] * len(params), []
        for k, (t, a) in enumerate(zip(params, args)):
            if shapes[k] is None:
                values[k] = _kotlin_value(t, a)
            elif _kotlin_node_given(shapes[k], a):
                values[k] = _kotlin_node_value(t, a, shapes[k])
            else:
                finds.append(k)
        made = next((k for k in range(len(params)) if shapes[k] and k not in finds), None)
        for k in finds:   # a node given by its value is looked for in the first structure the example builds
            if made is None:
                return None
            values[k] = _kotlin_node_find(params[k], args[k], shapes[k],
                                          f"_a{made}" + (".firstOrNull()" if shapes[made][0].endswith("s") else ""))
        if None in values:
            return None
        order = [k for k in range(len(params)) if k not in finds] + finds   # the structure first, what is in it after
        decl = "; ".join(f"val _a{k}: {params[k]} = {values[k]}" for k in order)
        call = f"{target}{function}({', '.join(('*' if k in varargs else '') + f'_a{k}' for k in range(len(params)))})"
        after = ' + "," + '.join(_kotlin_said(shapes[k], f"_a{k}") for k in range(len(params))) or '""'
        muted = f'System.setOut(_snNull); val _r: Any? = try {{ {call} }} finally {{ System.setOut(_snReal) }}'
        if void:
            line = f'{muted}; _snOut("{{\\"i\\":{i},\\"got\\":null,\\"after\\":[" + {after} + "]}}")'
        else:   # an expression body that turns out to be Unit (`= s.reverse()`) is a function done in place
            line = (f'{muted}; if (_r is Unit) _snOut("{{\\"i\\":{i},\\"got\\":null,\\"unit\\":true,\\"after\\":[" + {after} + "]}}") '
                    f'else _snOut("{{\\"i\\":{i},\\"got\\":" + {_kotlin_got(result, c.get("expected"))} + "}}")')
        body.append(f'    try {{ {decl}{"; " if decl else ""}{line} }}\n'
                    f'    catch (_e: Throwable) {{ _snOut("{{\\"i\\":{i},\\"error\\":" + _snStr(_e.toString()) + "}}") }}')
    code = re.sub(r"\bfun\s+main\s*\(", "fun _snOwnMain(", code)
    shown = "".join(f"    is {cls} -> _sn{kind.capitalize()}Json(v)\n" for kind, cls in sorted(kinds.items()))
    return code + "\n" + KOTLIN_MAIN % {"mark": CASE_MARK, "body": "\n".join(body), "nodes": helpers, "json": shown}
