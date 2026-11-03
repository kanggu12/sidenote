"""Go: the answer's function, and a main beside it that calls it on each example with the values the example
holds, made into the types it declares. A tree or a linked list is built from the level-order list the statement
writes, as the type its judge declares. A problem that asks for a class is called the same way, on the struct
the answer's own `Constructor` returns."""
from __future__ import annotations

import re

from .common import CASE_MARK, MAX_CASES, _closing, _definitions, _finite, _mask, _split_top


# ---------- Go ----------

# Its imports go right after the package clause (added when the answer has none, as Programmers' Go has none),
# under names of their own so they never clash with the answer's. The result is printed by encoding/json. While
# the answer runs, os.Stdout is /dev/null (see HARNESS).
GO_IMPORTS = 'import (\n\tsn_json "encoding/json"\n\tsn_fmt "fmt"\n\tsn_os "os"\n\tsn_reflect "reflect"\n)\n'


# A nil slice is Go's empty one (`var res []int`, `return nil`), which encoding/json would print as null: every
# slice is printed as a list.
GO_PRINTERS = """
var _snNull, _ = sn_os.OpenFile(sn_os.DevNull, sn_os.O_WRONLY, 0)

func _snOut(s string) { sn_fmt.Println("\\n%(mark)s" + s) }

func _snFix(v sn_reflect.Value) interface{} {
\tswitch v.Kind() {
\tcase sn_reflect.Slice, sn_reflect.Array:
\t\tout := make([]interface{}, v.Len())
\t\tfor i := range out {
\t\t\tout[i] = _snFix(v.Index(i))
\t\t}
\t\treturn out
\tcase sn_reflect.Interface, sn_reflect.Ptr:
\t\tif v.IsNil() {
\t\t\treturn nil
\t\t}
\t\treturn _snFix(v.Elem())
\tcase sn_reflect.Invalid:
\t\treturn nil
\t}
\treturn v.Interface()
}

func _snJson(v interface{}) string {
\tb, err := sn_json.Marshal(_snFix(sn_reflect.ValueOf(v)))
\tif err != nil {
\t\treturn "null"
\t}
\treturn string(b)
}
"""


GO_MAIN = GO_PRINTERS + """
func main() {
%(body)s
}
"""


GO_SCALARS = {"int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64", "float64",
              "float32", "bool", "string", "rune", "byte"}


# ---------- a tree or a linked list as an example writes it ----------

# LeetCode's judge declares these types and writes a tree or a list as the level-order list the statement shows
# (`root = [3,9,20,null,null,15,7]`, `head = [1,2,3]`), so an answer written there uses them without declaring
# them; Go exports a field by its capital, which is why such an answer reads root.Left and head.Next. The fields
# stay in the judge's order, since an answer builds a node by their places too (`&TreeNode{v, l, r}`).
GO_NODE_CLASS = {"tree": "TreeNode", "list": "ListNode"}


GO_NODE_TYPES = {"tree": "type TreeNode struct {\n\tVal   int\n\tLeft  *TreeNode\n\tRight *TreeNode\n}\n",
                 "list": "type ListNode struct {\n\tVal  int\n\tNext *ListNode\n}\n"}


# How far a structure is walked: one the answer grew without end is printed only this far.
# a tree in a circle, or one node shared deep, printed no longer than the runner's reply (MAX_OUTPUT)
GO_NODE_CAP = "\nconst _snCap = 3000\n\n"


# The example's list becomes nodes before the call, and a node that comes back becomes a list again, so the
# comparing stays on JSON values. A statement that gives a node by its value instead of its own list
# (`root = [3,5,1], p = 5`) means the node of the structure with that value, as its judge does. A structure that
# runs in a circle (what a cycle question builds) is walked once round, not forever.
GO_NODE_HELPERS = {"tree": """func _snTree(v []interface{}) *TreeNode {
\tif len(v) == 0 || v[0] == nil {
\t\treturn nil
\t}
\troot := &TreeNode{Val: v[0].(int)}
\tq, i := []*TreeNode{root}, 1
\tfor len(q) > 0 && i < len(v) {
\t\tnode := q[0]
\t\tq = q[1:]
\t\tfor side := 0; side < 2 && i < len(v); side++ {
\t\t\tx := v[i]
\t\t\ti++
\t\t\tif x == nil {
\t\t\t\tcontinue
\t\t\t}
\t\t\tchild := &TreeNode{Val: x.(int)}
\t\t\tif side == 0 {
\t\t\t\tnode.Left = child
\t\t\t} else {
\t\t\t\tnode.Right = child
\t\t\t}
\t\t\tq = append(q, child)
\t\t}
\t}
\treturn root
}

func _snTreeFind(root *TreeNode, val int) *TreeNode {
\tseen, q := map[*TreeNode]bool{}, []*TreeNode{root}
\tfor len(q) > 0 {
\t\tnode := q[0]
\t\tq = q[1:]
\t\tif node == nil || seen[node] {
\t\t\tcontinue
\t\t}
\t\tseen[node] = true
\t\tif node.Val == val {
\t\t\treturn node
\t\t}
\t\tq = append(q, node.Left, node.Right)
\t}
\t// a statement may name a value the structure does not hold (LeetCode 1644 states p = 10 for a tree
\t// without it): its judge hands the answer a node of that value all the same
\treturn &TreeNode{Val: val}
}

func _snTreeOut(root *TreeNode) interface{} {
\t// no map of what has been seen here: an answer that memoizes its subtrees hangs the same node in two
\t// places and a judge writes it in both. _snCap is what stops a tree made in a circle
\tout, q := []interface{}{}, []*TreeNode{root}
\tfor len(q) > 0 && len(out) < _snCap {
\t\tnode := q[0]
\t\tq = q[1:]
\t\tif node == nil {
\t\t\tout = append(out, nil)
\t\t\tcontinue
\t\t}
\t\tout = append(out, node.Val)
\t\tq = append(q, node.Left, node.Right)
\t}
\tfor len(out) > 0 && out[len(out)-1] == nil {   // a statement writes no null at the end of a level order
\t\tout = out[:len(out)-1]
\t}
\treturn out
}

func _snTreesOut(nodes []*TreeNode) interface{} {
\tout := []interface{}{}
\tfor _, node := range nodes {
\t\tout = append(out, _snTreeOut(node))
\t}
\treturn out
}

func _snTreeVal(node *TreeNode) interface{} {
\tif node == nil {
\t\treturn nil
\t}
\treturn node.Val
}
""", "list": """func _snList(v []interface{}) *ListNode {
\tdummy := &ListNode{}
\tnode := dummy
\tfor _, x := range v {
\t\tnode.Next = &ListNode{Val: x.(int)}
\t\tnode = node.Next
\t}
\treturn dummy.Next
}

func _snListFind(head *ListNode, val int) *ListNode {
\tseen := map[*ListNode]bool{}
\tfor node := head; node != nil && !seen[node]; node = node.Next {
\t\tseen[node] = true
\t\tif node.Val == val {
\t\t\treturn node
\t\t}
\t}
\treturn &ListNode{Val: val}   // as above: a value the list does not hold is a node of its own
}

func _snListOut(head *ListNode) interface{} {
\tout, seen := []interface{}{}, map[*ListNode]bool{}
\tfor node := head; node != nil && len(out) < _snCap && !seen[node]; node = node.Next {
\t\tseen[node] = true
\t\tout = append(out, node.Val)
\t}
\treturn out
}

func _snListsOut(nodes []*ListNode) interface{} {
\tout := []interface{}{}
\tfor _, node := range nodes {
\t\tout = append(out, _snListOut(node))
\t}
\treturn out
}

func _snListVal(node *ListNode) interface{} {
\tif node == nil {
\t\treturn nil
\t}
\treturn node.Val
}
"""}


def _go_signature(code: str, function: str, arity: int | None = None) -> tuple[str, list[str]] | None:
    """(result type, parameter types) of the function `function` (not a method), None when it is not found, has
    several results, or a parameter list it cannot read."""
    d = _go_decl(code, function, arity)
    return (d[0], d[1]) if d else None


def _go_decl(code: str, function: str, arity: int | None = None,
             head: str = r"(?m)^func\s+") -> tuple[str, list[str], list[str]] | None:
    """(result type, parameter types, parameter names) of the function `function`; Go has no overloads, so `arity`
    only rules it out. With `head`, what comes before the name is that instead of `func` alone, which is how a
    method of one type is read (GO_METHOD_HEAD)."""
    masked = _mask(code)
    m = None
    for name, params, _ in _definitions(masked, function, head, r"[^{\n]*\{"):
        result = re.match(r"([^{\n]*)\{", masked[_closing(masked, masked.find("(", name), "(", ")"):])
        m = (params, result.group(1))
        break
    if m is None:
        return None
    ret = " ".join(m[1].split())
    if ret.startswith("("):
        inner = ret[1:-1].strip()
        if "," in inner:
            return None
        ret = inner.split()[-1] if inner else ""
    names, types = [], []
    for part in _split_top(m[0], "[", "]"):
        bits = part.split(None, 1)
        if not bits:
            continue
        names.append(bits[0])
        if len(bits) == 2:   # `a, b int`: the names before take this type too
            t = "".join(bits[1].split())
            types.extend([t] * (len(names) - len(types)))
    if len(types) != len(names) or arity is not None and len(names) != arity:
        return None
    return ret, types, names


def _go_str(s: str) -> str:
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
            out.append("\\x%02x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _go_value(t: str, v) -> str | None:
    """A Go expression of type `t` for the JSON value `v`, None when the type is not one the check knows."""
    if t.startswith("[]"):
        inner = t[2:]
        if not isinstance(v, list) or inner == "byte":
            return None
        items = [_go_value(inner, x) for x in v]
        return None if None in items else f"{t}{{{', '.join(items)}}}"
    if t in ("int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64", "byte"):
        # the type's own range: a value outside it is a compile error, and this is the place to say it cannot be filled
        bits = {"int8": 8, "int16": 16, "int32": 32, "uint8": 8, "byte": 8, "uint16": 16, "uint32": 32}.get(t, 64)
        low, high = (0, 2 ** bits) if t.startswith("uint") or t == "byte" else (-(2 ** (bits - 1)), 2 ** (bits - 1))
        return str(v) if isinstance(v, int) and not isinstance(v, bool) and low <= v < high else None
    if t in ("float64", "float32"):
        f = _finite(v)
        return None if f is None else repr(f)
    if t == "bool":
        return ("true" if v else "false") if isinstance(v, bool) else None
    if t == "string":
        return _go_str(v) if isinstance(v, str) else None
    if t == "rune":
        if not (isinstance(v, str) and len(v) == 1 and ord(v) >= 0x20):
            return None
        return "'\\''" if v == "'" else "'\\\\'" if v == "\\" else f"'{v}'"
    return None


def _go_known(t: str) -> bool:
    if t.startswith("[]"):
        return t != "[]byte" and _go_known(t[2:])
    return t in GO_SCALARS


def _go_result_known(t: str) -> bool:
    return t in ("[]byte", "[]rune") or _go_known(t)


def _go_node_kind(t: str, shape: list | None) -> str | None:
    """The shape a declaration can be filled as: "tree", "list", "trees" or "lists" when `shape` says the
    parameter or the result is a node and the type it declares is a pointer to the class LeetCode's judge
    declares (`*TreeNode`, `[]*ListNode`), None when it is anything else (a node held in a type of the answer's
    own, which no level-order list fills)."""
    if not shape or len(shape) != 2:
        return None
    kind = shape[0]
    base = kind[:-1] if kind.endswith("s") else kind
    cls = GO_NODE_CLASS.get(base)
    if cls is None or shape[1] != cls:
        return None
    return kind if t == ("[]*" if kind.endswith("s") else "*") + cls else None


def _go_node_written(kind: str, v) -> bool:
    """Whether this argument's example is the node's own level-order list (or lists), rather than the value of a
    node in the structure the first argument builds (`root = [3,5,1], p = 5`)."""
    if kind.endswith("s"):
        return isinstance(v, list) and all(isinstance(x, list) for x in v)
    return isinstance(v, list)


def _go_node_list(v) -> str | None:
    """`[]interface{}{...}` for one level-order list, a missing node as nil, None when a value in it is no whole
    number (the Val LeetCode's judge declares is an int)."""
    items = []
    for x in v:
        item = "nil" if x is None else _go_value("int", x)
        if item is None:
            return None
        items.append(item)
    return "[]interface{}{%s}" % ", ".join(items)


def _go_node_value(kind: str, v) -> str | None:
    """The Go expression building the node (or the nodes) an example's level-order list writes."""
    build = "_snTree" if kind.startswith("tree") else "_snList"
    if not kind.endswith("s"):
        inner = _go_node_list(v)
        return None if inner is None else f"{build}({inner})"
    parts = [_go_node_list(x) for x in v]
    if None in parts:
        return None
    return "[]*%s{%s}" % (GO_NODE_CLASS[kind[:-1]], ", ".join(f"{build}({p})" for p in parts))


def _go_node_find(kind: str, root: str, v) -> str | None:
    """The Go expression for a node an example gives by its value: the one of the structure `root` whose value is
    that, one per element for a shape that is a list of them."""
    find = "_snTreeFind" if kind.startswith("tree") else "_snListFind"
    if not kind.endswith("s"):
        value = _go_value("int", v)
        return None if value is None else f"{find}({root}, {value})"
    if not isinstance(v, list):
        return None
    values = [_go_value("int", x) for x in v]
    if None in values:
        return None
    return "[]*%s{%s}" % (GO_NODE_CLASS[kind[:-1]], ", ".join(f"{find}({root}, {x})" for x in values))


def _go_values(params: list, kinds: list, args: list) -> list[str] | None:
    """The Go expressions for one example's arguments, in the parameters' order, None when one of them cannot be
    filled. The structures the example writes are built first, since a node it gives by its value is found in the
    first of them, as its judge does."""
    out, root = [None] * len(args), None
    for k, (kind, a) in enumerate(zip(kinds, args)):
        if kind is None:
            out[k] = _go_value(params[k], a)
        elif a is None:   # an example that writes no structure at all
            out[k] = "nil"
        elif _go_node_written(kind, a):
            out[k] = _go_node_value(kind, a)
            if root is None and not kind.endswith("s") and out[k] is not None:
                root = (f"_a{k}", kind)
    for k, (kind, a) in enumerate(zip(kinds, args)):
        if kind is None or out[k] is not None or _go_node_written(kind, a):
            continue
        base = kind[:-1] if kind.endswith("s") else kind
        if root is None or root[1] != base:   # nothing of that shape was built to find the node in
            return None
        out[k] = _go_node_find(kind, root[0], a)
    return None if None in out else out


def _go_shown(kind: str | None, name: str, plain: bool = False) -> str:
    """A value as a statement writes it: a node as the level-order list of the whole structure, or, with `plain`,
    as the node's own value (what a statement shows for a node it only points at); anything else as it is."""
    if not kind:
        return name
    base = "Tree" if kind.startswith("tree") else "List"
    if plain:
        return f"_sn{base}Val({name})"
    return f"_sn{base}sOut({name})" if kind.endswith("s") else f"_sn{base}Out({name})"


def _go_nodes(code: str, kinds: list) -> str:
    """The node types and the helpers the program needs for the shapes `kinds` holds, "" for none. The type is
    declared only where the answer declares none of its own, since Go takes a name once."""
    masked, out = _mask(code), []
    for kind in ("tree", "list"):
        need = any(k and k.startswith(kind) for k in kinds)
        # the type is also declared where no shape holds it and the answer only builds one (`&TreeNode{...}`
        # from a plain array), since that name is the judge's to declare; the helpers are not, so an answer
        # whose own type of that name has other fields still compiles
        named = re.search(r"\b%s\b" % GO_NODE_CLASS[kind], masked) is not None
        if not (need or named):
            continue
        if not re.search(r"\b%s\s+struct\b" % GO_NODE_CLASS[kind], masked):
            out.append(GO_NODE_TYPES[kind] + "\n")
        if need:
            out.append(GO_NODE_HELPERS[kind])
    return GO_NODE_CAP + "\n".join(out) if out else ""


def _go_result_lines(i: int, ret: str, kind: str | None, call: str, expected, back: str) -> str:
    """The lines of one call that has a result: the call, the answer's own output off hold again (`back`), and the
    result as a statement writes it."""
    if ret in ("byte", "rune"):   # a character: written as one, as a statement shows it
        return f'\t\t_r := string(rune({call}))\n{back}\t\t_snOut(`{{"i":{i},"got":` + _snJson(_r) + "}}")\n'
    if ret in ("[]byte", "[]rune"):   # characters (encoding/json would write []byte as base64)
        return (f'\t\t_c := {call}\n\t\t_r := make([]string, len(_c))\n\t\tfor _k, _x := range _c {{\n'
                f'\t\t\t_r[_k] = string(rune(_x))\n\t\t}}\n{back}\t\t_snOut(`{{"i":{i},"got":` + _snJson(_r) + "}}")\n')
    # a node the statement shows as a plain value (its expected is no list) is printed as that value
    shown = _go_shown(kind, "_r", kind in ("tree", "list") and not isinstance(expected, list))
    return f'\t\t_r := {call}\n{back}\t\t_snOut(`{{"i":{i},"got":` + _snJson({shown}) + "}}")\n'


def _go_program(code: str, nodes: str, main: str) -> str:
    """The answer and the harness as one Go program: package main and the harness's own imports, the node types
    the examples are built with, and the main that calls the answer. A main of the answer's own is renamed, since
    the harness brings the one that runs."""
    code = re.sub(r"^func\s+main\s*\(", "func _snOwnMain(", code, flags=re.M)
    package = re.search(r"^[ \t]*package\s+\w+[ \t]*;?[ \t]*$", _mask(code), re.M)   # a comment after it is blanked
    if package:
        code = code[:package.start()] + "package main\n" + GO_IMPORTS + code[package.end():]
    else:
        code = "package main\n\n" + GO_IMPORTS + "\n" + code
    return code + "\n" + nodes + main


def go_harness(code: str, function: str, cases: list, shapes: list | None = None, result: list | None = None) -> str | None:
    """The answer's Go with a main that calls `function` on each example, None when its declaration cannot be
    filled from the examples (see cpp_harness)."""
    arity = len(cases[0].get("args") or []) if cases and isinstance(cases[0].get("args"), list) else None
    sig = _go_signature(code, function, arity)
    if sig is None:
        return None
    ret, params = sig
    void = ret == ""
    kinds = [_go_node_kind(t, s) for t, s in zip(params, list(shapes or []) + [None] * len(params))]
    res_kind = None if void else _go_node_kind(ret, result)
    if not (void or res_kind or _go_result_known(ret)) or not all(k or _go_known(t) for k, t in zip(kinds, params)):
        return None
    body = []
    for i, c in enumerate(cases[:MAX_CASES]):
        args = c.get("args") or []
        if not isinstance(args, list) or len(args) != len(params):
            return None
        values = _go_values(params, kinds, args)
        if values is None:
            return None
        decl = "".join(f"\t\tvar _a{k} {t} = {v}\n" for k, (t, v) in enumerate(zip(params, values)))
        call = f"{function}({', '.join(f'_a{k}' for k in range(len(params)))})"
        back = "\t\tsn_os.Stdout = _snSaved\n"
        if void:
            after = ", ".join(_go_shown(kinds[k], f"_a{k}") for k in range(len(params)))
            line = (f'\t\t{call}\n{back}\t\t_snOut(`{{"i":{i},"got":null,"after":` + _snJson([]interface{{}}{{{after}}})'
                    f' + "}}")\n')
        else:
            line = _go_result_lines(i, ret, res_kind, call, c.get("expected"), back)
        body.append(f'\tfunc() {{\n\t\t_snSaved := sn_os.Stdout\n\t\tdefer func() {{\n\t\t\tsn_os.Stdout = _snSaved\n'
                    f'\t\t\tif r := recover(); r != nil {{\n'
                    f'\t\t\t\t_snOut(`{{"i":{i},"error":` + _snJson(sn_fmt.Sprint(r)) + "}}")\n\t\t\t}}\n\t\t}}()\n'
                    f'{decl}\t\tsn_os.Stdout = _snNull\n{line}\t}}()')
    nodes = _go_nodes(code, kinds + [res_kind])
    return _go_program(code, nodes, GO_MAIN % {"mark": CASE_MARK, "body": "\n".join(body)})


# ---------- a class the problem asks for ----------

# Go has no classes: the form a judge asks for is a struct and a function beside it that builds one
# (`func Constructor(capacity int) LRUCache`), with the methods on a pointer to it. A statement names the calls
# as the class and its methods in LeetCode's own case ("LRUCache", "put", "get"), which is why a method is
# looked up by its name folded.
GO_CONSTRUCTOR = "Constructor"


GO_METHOD_HEAD = r"(?m)^func\s*\(\s*(?:\w+\s+)?\*?%s\s*\)\s*"


GO_METHODS = GO_METHOD_HEAD + r"([A-Za-z_]\w*)\s*\("


# The object is held in a var of its own, outside main: a call stands in a block of its own, so the names of one
# call's arguments are not the next one's, and a method on a pointer receiver can take the object's address.
# One deferred recover for the whole run, not one for each call: a call that panics prints its own line and the
# calls after it are never made, since what the object holds is no longer the problem's.
GO_DESIGN_MAIN = GO_PRINTERS + """
var _snObj %(held)s

func main() {
\t_snSaved := sn_os.Stdout
\t_snAt := 0
\tdefer func() {
\t\tsn_os.Stdout = _snSaved
\t\tif r := recover(); r != nil {
\t\t\t_snOut(`{"i":` + _snJson(_snAt) + `,"error":` + _snJson(sn_fmt.Sprint(r)) + "}")
\t\t}
\t}()
%(body)s
}
"""


def _go_method_decl(code: str, cls: str, method: str) -> tuple[str, list[str], list[str]] | None:
    """(result type, parameter types, parameter names) of the method `method` of the type `cls`, None when the
    type declares no such method or its declaration cannot be read. The receiver is in the pattern, so a helper
    type of the answer's own with a method of that name (a heap's Push beside a FreqStack's) is not taken."""
    return _go_decl(code, method, head=GO_METHOD_HEAD % re.escape(cls))


def _go_method(names: list, called: str) -> str | None:
    """The method a statement's call names: that name, or the one that differs from it only in its capitals,
    since a Go answer declares `Put` for a statement's `put`. The exported one comes first where a type declares
    both, as a judge's template asks for."""
    if called in names:
        return called
    folded = [n for n in names if n.lower() == called.lower()]
    return folded[0] if folded else None


def _go_design_kind(t: str, shape: list | None) -> str | None:
    """The shape a method's declaration can be filled as, from the shape a call carries (_go_node_kind) or, where
    it carries none, from the type itself: a method of a class is no top-level func, so the check reads no
    declaration for it and says nothing about its arguments, while the type naming the class a judge declares
    (`*TreeNode`, `[]*ListNode`) is the level-order list a statement writes all the same."""
    kind = _go_node_kind(t, shape)
    if kind is not None:
        return kind
    for base, cls in GO_NODE_CLASS.items():
        if t == "*" + cls:
            return base
        if t == "[]*" + cls:
            return base + "s"
    return None


def design_harness(code: str, cls: str, calls: list) -> str | None:
    """The answer's Go with a main that calls the class the problem asks for as its statement's example does: the
    calls in order on one object, the first of them the constructor. None where the harness cannot do it: no
    `Constructor` beside the type, a call the class declares no method for, or a type no example value fills."""
    masked = _mask(code)
    ctor = _go_decl(code, GO_CONSTRUCTOR)
    # what the Constructor returns is the object a judge holds and calls, whatever the statement calls the class
    if ctor is None or not re.fullmatch(r"\*?[A-Za-z_]\w*", ctor[0]):
        return None
    held, base = ctor[0], ctor[0].lstrip("*")
    names = sorted(m.group(1) for m in re.finditer(GO_METHODS % re.escape(base), masked))
    body, seen = [], []
    for i, c in enumerate(calls):
        method = GO_CONSTRUCTOR if i == 0 else _go_method(names, str(c.get("call") or ""))
        d = ctor if i == 0 else _go_method_decl(code, base, method) if method else None
        if d is None:
            return None
        ret, params, declared = d
        args = c.get("args") or []
        # a call that takes nothing is written [] on most problems and [null] on some
        args = [] if args == [None] and not declared else args
        if not isinstance(args, list) or len(args) != len(params):
            return None
        kinds = [_go_design_kind(t, s) for t, s in
                 zip(params, list(c.get("shapes") or []) + [None] * len(params))]
        res_kind = None if i == 0 or ret == "" else _go_design_kind(ret, c.get("result"))
        if not all(k or _go_known(t) for k, t in zip(kinds, params)):
            return None
        if not (i == 0 or ret == "" or res_kind or _go_result_known(ret)):
            return None
        values = _go_values(params, kinds, args)
        if values is None:
            return None
        seen += kinds + [res_kind]
        decl = "".join(f"\t\tvar _a{k} {t} = {v}\n" for k, (t, v) in enumerate(zip(params, values)))
        call = f"{method}({', '.join(f'_a{k}' for k in range(len(params)))})"
        back = "\t\tsn_os.Stdout = _snSaved\n"
        if i == 0:
            line = f'\t\t_snObj = {call}\n{back}\t\t_snOut(`{{"i":0,"got":null}}`)\n'
        elif ret == "":   # a method that returns nothing: what the statement writes for it is null
            line = f'\t\t_snObj.{call}\n{back}\t\t_snOut(`{{"i":{i},"got":null}}`)\n'
        else:
            line = _go_result_lines(i, ret, res_kind, f"_snObj.{call}", c.get("expected"), back)
        body.append(f'\t{{\n\t\t_snAt = {i}\n{decl}\t\tsn_os.Stdout = _snNull\n{line}\t}}')
    return _go_program(code, _go_nodes(code, seen),
                       GO_DESIGN_MAIN % {"mark": CASE_MARK, "held": held, "body": "\n".join(body)})
