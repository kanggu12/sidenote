"""C++: the answer as written, and after it a printer and a main that call its function on each example with
the values the example holds, made into the types the function declares. A tree or a linked list node is built
from the level-order list the statement writes, with the class the declaration names."""
from __future__ import annotations

import re

from .common import (
    CASE_MARK, MAX_CASES, _c_escapes, _closing, _definitions, _finite, _leetcode_form, _mask, _return_type,
    _split_top
)


# ---------- C++ ----------

# The answer's code comes first, as written, and after it a printer and a main that use only std:: names (a
# global of the answer's named count or y1 would clash with `using namespace std`, <bits/stdc++.h> or <cmath>),
# never `endl` or `int` (an answer may #define them, and the printer's own includes are made with those set
# aside). Code with no #include at all, or a `class Solution` (LeetCode's form), is written for a judge that adds
# every header and `using namespace std`, so it gets those first. While the answer runs, what it prints itself goes
# to /dev/null (see HARNESS).
CPP_JUDGE_HEAD = "#include <bits/stdc++.h>\nusing namespace std;\n"


CPP_PRINT = r"""
#pragma push_macro("int")
#pragma push_macro("endl")
#undef int
#undef endl
#include <cstdio>
#include <fcntl.h>
#include <iomanip>
#include <iostream>
#include <string>
#include <type_traits>
#include <unistd.h>
#include <vector>
#pragma pop_macro("endl")
#pragma pop_macro("int")
namespace sn_check {
struct Mute {
  int saved;
  std::ios_base::fmtflags flags;
  std::streamsize precision, width;
  char fill;
  Mute() : flags(std::cout.flags()), precision(std::cout.precision()), width(std::cout.width()), fill(std::cout.fill()) {
    std::cout.flush(); std::fflush(stdout);
    saved = ::dup(1);
    int null = ::open("/dev/null", O_WRONLY);
    if (null >= 0) { ::dup2(null, 1); ::close(null); }
  }
  ~Mute() {
    std::cout.flush(); std::fflush(stdout);
    if (saved >= 0) { ::dup2(saved, 1); ::close(saved); }
    std::cout.clear(); std::cout.flags(flags); std::cout.precision(precision); std::cout.width(width); std::cout.fill(fill);
  }
};
template <class F> auto muted(F f) -> decltype(f()) { Mute m; return f(); }
inline void p(const std::string& s) {
  std::cout << '"';
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') std::cout << '\\' << c;
    else if (c < 0x20) { char b[8]; std::snprintf(b, sizeof b, "\\u%04x", (unsigned)c); std::cout << b; }
    else std::cout << c;
  }
  std::cout << '"';
}
inline void p(const char* s) { p(std::string(s)); }
inline void p(char c) { p(std::string(1, c)); }
inline void p(bool b) { std::cout << (b ? "true" : "false"); }
inline void p(double v) { if (v == v && v - v == 0) std::cout << std::setprecision(17) << v; else std::cout << "null"; }
inline void p(float v) { p((double)v); }
inline void p(long double v) { p((double)v); }
template <class T> typename std::enable_if<std::is_integral<T>::value>::type p(T v) { std::cout << +v; }
template <class T> void p(const std::vector<T>& v) {
  std::cout << '[';
  for (std::size_t i = 0; i < v.size(); ++i) { if (i) std::cout << ','; p((T)v[i]); }
  std::cout << ']';
}
}  // namespace sn_check
"""


CPP_INTS = {"int", "long", "long long", "long int", "long long int", "short", "unsigned", "unsigned int",
            "unsigned long", "unsigned long long", "size_t", "int64_t", "int32_t", "uint64_t", "uint32_t"}


# A pointer to a node class: the only pointer the check fills, from the level-order list a statement writes.
CPP_NODE = re.compile(r"\b(TreeNode|ListNode|Node)\s*\*")


# What comes after the parameter list where a function is defined and not called: its body, past the qualifiers
# a member function may carry.
CPP_BODY_OPENS = r"\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?\{"


def _cpp_type(t: str) -> str:
    """A parameter's value type as written here: no std::, const or &, no spaces around < > , or *."""
    t = re.sub(r"\bstd::", "", t)
    t = re.sub(r"\b(const|volatile)\b", " ", t).replace("&", " ")
    return re.sub(r"\s*\*\s*", "*", re.sub(r"\s*([<>,])\s*", r"\1", " ".join(t.split())))


def _cpp_std(t: str) -> str:
    """A type as the harness writes it: std:: before the library's names, so it holds without `using namespace std`."""
    return re.sub(r"\bstring\b", "std::string", re.sub(r"\bvector<", "std::vector<", t))


def _cpp_params(params: str) -> list[tuple[str, str]] | None:
    """(value type, name) of each parameter in a C++ parameter list, None for one the check cannot fill (a pointer
    to anything but a node class, an array, no name)."""
    found = []
    for part in _split_top(params):
        part = part.split("=")[0].strip()
        m = re.fullmatch(r"(.*[\s&>*])(\w+)", part, re.A)
        if not m or "[" in part or "*" in part and not CPP_NODE.search(part):
            return None
        found.append((_cpp_type(m.group(1)), m.group(2)))
    return found


def _cpp_decl(code: str, function: str, arity: int | None = None) -> tuple[str, list[str], list[str]] | None:
    """(return type, parameter types, parameter names) of `function` in C++ code, None when it is not found or not
    fillable. With `arity`, the definition that takes that many arguments (a helper overload may come first)."""
    masked = _mask(code)
    picked = []
    for name, params, before in _definitions(masked, function, r"", CPP_BODY_OPENS):
        ret = re.sub(r"\b(static|inline|virtual|constexpr|explicit|friend)\b", " ", _return_type(masked, name, before))
        if not ret.strip() or re.search(r"[=()]|\breturn\b", ret):   # a call, not a definition
            continue
        found = _cpp_params(params)
        if arity is not None and (found is None or len(found) != arity):
            continue
        decl = (_cpp_type(ret), [t for t, _ in found], [n for _, n in found]) if found is not None else None
        if arity is None:
            return decl
        picked.append((_cpp_private(masked, name), decl))
    return next((d for private, d in picked if not private), picked[0][1] if picked else None)


def _cpp_private(masked: str, pos: int) -> bool:
    """Whether the class member at `pos` is private: the last access label before it in its class's own body, or
    the class's default (a class's members are private, a struct's public)."""
    depth = masked.count("{", 0, pos) - masked.count("}", 0, pos)
    if depth != 1:
        return False
    level, k = 0, pos - 1
    while k >= 0 and not (masked[k] == "{" and level == 0):
        level += (masked[k] == "}") - (masked[k] == "{")
        k -= 1
    if k < 0:
        return False
    header = masked[max(masked.rfind("}", 0, k), masked.rfind(";", 0, k)) + 1:k]
    kinds = re.findall(r"\b(class|struct)\b", header)
    access = "private" if kinds and kinds[-1] == "class" else "public"
    level = 0
    for m in re.finditer(r"[{}]|\b(public|private|protected)\s*:", masked[k + 1:pos]):
        if m.group(0) in "{}":
            level += 1 if m.group(0) == "{" else -1
        elif level == 0:
            access = m.group(1)
    return access == "private"


def _cpp_signature(code: str, function: str, arity: int | None = None) -> tuple[str, list[str]] | None:
    """(return type, parameter types) of `function` in C++ code, None when it is not found or not fillable."""
    d = _cpp_decl(code, function, arity)
    return (d[0], d[1]) if d else None


def _cpp_value(t: str, v) -> str | None:
    """A C++ expression of type `t` for the JSON value `v`, None when the type is not one the check knows."""
    if t.startswith("vector<") and t.endswith(">"):
        inner = t[7:-1]
        if not isinstance(v, list):
            return None
        items = [_cpp_value(inner, x) for x in v]
        return None if None in items else f"{_cpp_std(t)}{{{', '.join(items)}}}"
    if t == "bool":
        return ("true" if v else "false") if isinstance(v, bool) else None
    if t in CPP_INTS:
        return f"({t})({v}LL)" if isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2 ** 63 else None
    if t in ("double", "float", "long double"):
        f = _finite(v)
        return f"({t})({f!r})" if f is not None else None
    if t == "string":
        return f'std::string("{_c_escapes(v)}")' if isinstance(v, str) else None
    if t == "char":
        return ("'\\''" if v == "'" else "'\\\\'" if v == "\\" else f"'{v}'") \
            if isinstance(v, str) and len(v) == 1 and 0x20 <= ord(v) < 0x7f else None
    return None


def _cpp_printable(t: str) -> bool:
    """A type the harness can print as JSON."""
    if t.startswith("vector<") and t.endswith(">"):
        return _cpp_printable(t[7:-1])
    return t in CPP_INTS or t in ("bool", "char", "double", "float", "long double", "string")


# ---------- a tree or a linked list as an example writes it ----------

# The helpers the generated program builds and prints nodes with, after CPP_PRINT so that its p() is in scope.
# They are written only where a node is in play, so a program without one stays as it was. The walking keeps
# the pointers it has seen, since a list or a tree that runs in a circle (a cycle question builds one) is
# walked once round and not forever.
CPP_NODE_HELPERS = r"""
namespace sn_check {
// One place of the level-order list an example writes (`[3,9,20,null,null,15,7]`): `here` is false for a null,
// which is a missing child, and the children of a missing node are not written at all.
struct Cell {
  bool here;
  long long v;
};
// a tree in a circle, or one node shared deep, printed no longer than the runner's reply (MAX_OUTPUT)
const std::size_t cap = 3000;
struct Seen {
  std::vector<const void*> slot;
  Seen() : slot(1u << 16, nullptr) {}
  bool add(const void* p) {   // false when this pointer came round again
    std::size_t mask = slot.size() - 1, h = ((std::size_t)p >> 3) & mask;
    while (slot[h] != nullptr) {
      if (slot[h] == p) return false;
      h = (h + 1) & mask;
    }
    slot[h] = p;
    return true;
  }
};
template <class T> T& ref();   // declared and never called, to read the type of a member off
// Which way of making a node is tried first. Tags rather than an argument of another number type, since the
// answer may `#define int long long` and leave two signatures the same.
struct Second {};
struct First : Second {};
// A node of the class the declaration names: made with the value, as LeetCode's own definition takes it, or
// made empty and then given its value, which is all an answer that defines the class itself may allow.
template <class T> auto one(long long x, First) -> decltype(new T(ref<T>().val)) {
  return new T((decltype(ref<T>().val))x);
}
template <class T> T* one(long long x, Second) {
  T* made = new T();
  made->val = (decltype(made->val))x;
  return made;
}
template <class T> T* tree(const std::vector<Cell>& v) {
  if (v.empty() || !v[0].here) return nullptr;
  std::vector<T*> row;
  row.push_back(one<T>(v[0].v, First{}));
  std::size_t at = 1;
  for (std::size_t k = 0; k < row.size() && at < v.size(); ++k) {
    for (std::size_t side = 0; side < 2 && at < v.size(); ++side) {
      Cell c = v[at++];
      if (!c.here) continue;
      T* child = one<T>(c.v, First{});
      if (side == 0) row[k]->left = child;
      else row[k]->right = child;
      row.push_back(child);
    }
  }
  return row[0];
}
template <class T> T* chain(const std::vector<Cell>& v) {
  T* head = nullptr;
  for (std::size_t k = v.size(); k > 0; --k) {
    if (!v[k - 1].here) continue;
    T* made = one<T>(v[k - 1].v, First{});
    made->next = head;
    head = made;
  }
  return head;
}
// The node of a built structure whose value a statement gives in place of its list (`root = [3,5,1], p = 5`),
// as its judge means it.
template <class T> T* find_tree(T* root, long long value) {
  Seen seen;
  std::vector<T*> row;
  if (root != nullptr) row.push_back(root);
  for (std::size_t k = 0; k < row.size() && k < cap; ++k) {
    T* at = row[k];
    if (!seen.add(at)) continue;
    if ((long long)at->val == value) return at;
    if (at->left != nullptr) row.push_back(at->left);
    if (at->right != nullptr) row.push_back(at->right);
  }
  // a statement may name a value the structure does not hold (LeetCode 1644 states p = 10 for a tree without
  // it): its judge hands the answer a node of that value all the same
  return root == nullptr ? nullptr : one<T>(value, First{});
}
template <class T> T* find_list(T* head, long long value) {
  Seen seen;
  for (std::size_t k = 0; head != nullptr && k < cap && seen.add(head); ++k) {
    if ((long long)head->val == value) return head;
    head = head->next;
  }
  return one<T>(value, First{});   // as above: a value the list does not hold is a node of its own
}
// A node as a statement writes it: a tree in level order with the trailing nulls dropped, a list as its
// values, no node at all as the empty list, and a node shown by its value as that value.
template <class T> void p_tree(T* root) {
  // nothing is kept of what has been seen: an answer that memoizes its subtrees hangs the same node in two
  // places and a judge writes it in both. cap is what stops a tree made in a circle
  std::vector<T*> row;
  row.push_back(root);
  for (std::size_t k = 0; k < row.size() && row.size() < cap; ++k) {
    if (row[k] == nullptr) {
      continue;
    }
    row.push_back(row[k]->left);
    row.push_back(row[k]->right);
  }
  while (!row.empty() && row.back() == nullptr) row.pop_back();
  std::cout << '[';
  for (std::size_t k = 0; k < row.size(); ++k) {
    if (k) std::cout << ',';
    if (row[k] == nullptr) std::cout << "null";
    else p(row[k]->val);
  }
  std::cout << ']';
}
template <class T> void p_list(T* head) {
  Seen seen;
  std::cout << '[';
  for (std::size_t k = 0; head != nullptr && k < cap && seen.add(head); ++k) {
    if (k) std::cout << ',';
    p(head->val);
    head = head->next;
  }
  std::cout << ']';
}
template <class T> void p_val(T* at) {
  if (at == nullptr) std::cout << "null";
  else p(at->val);
}
template <class T> void p_trees(const std::vector<T*>& v) {
  std::cout << '[';
  for (std::size_t k = 0; k < v.size(); ++k) {
    if (k) std::cout << ',';
    p_tree(v[k]);
  }
  std::cout << ']';
}
template <class T> void p_lists(const std::vector<T*>& v) {
  std::cout << '[';
  for (std::size_t k = 0; k < v.size(); ++k) {
    if (k) std::cout << ',';
    p_list(v[k]);
  }
  std::cout << ']';
}
}  // namespace sn_check
"""


CPP_SHOW = {"tree": "p_tree", "list": "p_list", "trees": "p_trees", "lists": "p_lists"}


def _cpp_defines(masked: str, cls: str) -> bool:
    """Whether the answer defines the node class itself, so that it is not defined twice. LeetCode's answers
    carry its definition in a comment, which the masking blanks: a commented one has not defined it."""
    return re.search(r"\b(?:struct|class)\s+" + re.escape(cls) + r"\b[^;{]*\{", masked) is not None


def _cpp_node_class(shape: str, cls: str) -> str | None:
    """LeetCode's own definition of the class a shape names, which its judge provides and an answer written
    there uses without defining. None for a class only the answer itself can define: its `Node` is the name of
    several shapes there."""
    if cls not in ("TreeNode", "ListNode"):
        return None
    if shape.startswith("tree"):
        return (f"struct {cls} {{\n  int val;\n  {cls} *left;\n  {cls} *right;\n"
                f"  {cls}() : val(0), left(nullptr), right(nullptr) {{}}\n"
                f"  {cls}(int x) : val(x), left(nullptr), right(nullptr) {{}}\n"
                f"  {cls}(int x, {cls} *left, {cls} *right) : val(x), left(left), right(right) {{}}\n}};\n")
    return (f"struct {cls} {{\n  int val;\n  {cls} *next;\n"
            f"  {cls}() : val(0), next(nullptr) {{}}\n"
            f"  {cls}(int x) : val(x), next(nullptr) {{}}\n"
            f"  {cls}(int x, {cls} *next) : val(x), next(next) {{}}\n}};\n")


def _cpp_classes(masked: str, shapes: list, result: list | None) -> str | None:
    """The node classes the generated program defines before the answer: the ones the shapes name and the answer
    does not define, each once. None when one of them is a class only the answer can define."""
    want: dict = {}
    for shape in [s for s in shapes if s] + ([result] if result else []):
        want.setdefault(shape[1], shape[0])
    out = ""
    for cls, kind in want.items():
        if _cpp_defines(masked, cls):
            continue
        text = _cpp_node_class(kind, cls)
        if text is None:
            return None
        out += text
    # a class the answer only builds (`new TreeNode(...)` from a plain array) is the judge's to define too
    for cls, kind in (("TreeNode", "tree"), ("ListNode", "list")):
        if cls not in want and re.search(r"\b%s\b" % cls, masked) and not _cpp_defines(masked, cls):
            out += _cpp_node_class(kind, cls)
    return out


def _cpp_whole(v) -> str | None:
    """A node's value as a C++ literal, None for anything a node's `val` does not hold."""
    return f"{v}LL" if isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2 ** 63 else None


def _cpp_cells(v) -> str | None:
    """The level-order list an example writes, as the cells a builder takes, None when it is no such list."""
    if not isinstance(v, list):
        return None
    out = []
    for x in v:
        value = "0LL" if x is None else _cpp_whole(x)
        if value is None:
            return None
        out.append(("{false, " if x is None else "{true, ") + value + "}")
    return "{" + ", ".join(out) + "}"


def _cpp_node_ok(shape: list, t: str) -> bool:
    """Whether the type a node parameter or result declares is the pointer the builder makes."""
    return t == (f"vector<{shape[1]}*>" if shape[0].endswith("s") else f"{shape[1]}*")


def _cpp_made(shape: list, v) -> bool:
    """Whether this example gives the node its own level-order list (or lists), rather than the value of a node
    of the structure another argument builds."""
    return all(isinstance(x, list) for x in v) if shape[0].endswith("s") and isinstance(v, list) \
        else isinstance(v, list)


def _cpp_build(shape: list, v) -> str | None:
    """A C++ expression for the node (or the nodes) an example's level-order list writes."""
    build = "tree" if shape[0].startswith("tree") else "chain"
    made = [_cpp_cells(x) for x in v] if shape[0].endswith("s") else [_cpp_cells(v)]
    if None in made:
        return None
    calls = [f"sn_check::{build}<{shape[1]}>({cells})" for cells in made]
    return f"std::vector<{shape[1]}*>{{{', '.join(calls)}}}" if shape[0].endswith("s") else calls[0]


def _cpp_found(shape: list, v, root: tuple | None) -> str | None:
    """A C++ expression for the node (or the nodes) a statement gives by value, looked up in the structure the
    example built first. None when its class is not the one that structure is of."""
    cls = shape[1]
    many = shape[0].endswith("s")
    if root is None:   # nothing was built, so there is no node of that value, as the Python harness has none
        return f"std::vector<{cls}*>{{}}" if many else f"({cls}*)nullptr"
    built, name = root
    if built[1] != cls or many and not isinstance(v, list):
        return None
    find = "find_tree" if built[0].startswith("tree") else "find_list"
    at = f"({name}.empty() ? nullptr : {name}[0])" if built[0].endswith("s") else name
    values = [_cpp_whole(x) for x in v] if many else [_cpp_whole(v)]
    if None in values:
        return None
    calls = [f"sn_check::{find}<{cls}>({at}, {value})" for value in values]
    return f"std::vector<{cls}*>{{{', '.join(calls)}}}" if many else calls[0]


def _cpp_values(params: list, shapes: list, args: list) -> list | None:
    """[(the parameter's place, its type, the C++ expression)] for an example's arguments, the nodes a statement
    gives by value last, since the structure they are looked up in is declared before them. None when one of
    them cannot be made."""
    built = next((k for k, s in enumerate(shapes) if s and _cpp_made(s, args[k])), None)
    root = None if built is None else (shapes[built], f"_a{built}")
    first, last = [], []
    for k, (t, shape, a) in enumerate(zip(params, shapes, args)):
        if shape is None:
            first.append((k, t, _cpp_value(t, a)))
        elif not _cpp_node_ok(shape, t):
            return None
        elif _cpp_made(shape, a):
            first.append((k, t, _cpp_build(shape, a)))
        else:
            last.append((k, t, _cpp_found(shape, a, root)))
    made = first + last
    return None if any(v is None for _, _, v in made) else made


def _cpp_show(name: str, shape: list | None) -> str:
    """The statement that prints one value as the judge compares it."""
    return f"sn_check::p({name});" if shape is None else f"sn_check::{CPP_SHOW[shape[0]]}<{shape[1]}>({name});"


def _cpp_result(result: list | None, expected) -> str:
    """The statement that prints what the function returned: a node the statement shows as a plain value (its
    expected value is no list) as that value, anything else as the statement writes it."""
    if result is None or result[0].endswith("s") or isinstance(expected, list):
        return _cpp_show("_r", result)
    return f"sn_check::p_val<{result[1]}>(_r);"


def cpp_harness(code: str, function: str, cases: list, shapes: list | None = None, result: list | None = None) -> str | None:
    """The answer's C++ with a main that calls `function` on each example, None when its declaration cannot be
    filled from the examples or its result printed (a type the check does not know, another number of
    arguments). A void function is called for what it does to its arguments. `shapes` and `result` say which of
    them are a tree or a linked list node, and of what class, which the examples write as a level-order list."""
    arity = len(cases[0].get("args") or []) if cases and isinstance(cases[0].get("args"), list) else None
    sig = _cpp_signature(code, function, arity)
    if sig is None:
        return None
    ret, params = sig
    shapes = (list(shapes) + [None] * len(params))[:len(params)] if shapes else [None] * len(params)
    void = ret == "void"
    shown = all(_cpp_printable(t) or s for t, s in zip(params, shapes)) if void \
        else _cpp_printable(ret) or result is not None
    if not shown or result is not None and not _cpp_node_ok(result, ret):
        return None
    masked = _mask(code)
    classes = _cpp_classes(masked, shapes, result)
    if classes is None:
        return None
    owner = "Solution{}." if re.search(r"\b(class|struct)\s+Solution\b", masked) else ""
    body = []
    for i, c in enumerate(cases[:MAX_CASES]):
        args = c.get("args") or []
        if not isinstance(args, list) or len(args) != len(params):
            return None
        values = _cpp_values(params, shapes, args)
        if values is None:
            return None
        decl = " ".join(f"{_cpp_std(t)} _a{k} = {v};" for k, t, v in values)
        call = f"{owner}{function}({', '.join(f'_a{k}' for k in range(len(params)))})"
        if void:
            after = ' std::cout << ","; '.join(_cpp_show(f"_a{k}", s) for k, s in enumerate(shapes))
            line = (f'sn_check::muted([&] {{ {call}; }}); '
                    f'std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"got\\":null,\\"after\\":["; {after} '
                    f'std::cout << "]}}\\n" << std::flush;')
        else:
            line = (f'auto _r = sn_check::muted([&] {{ return {call}; }}); '
                    f'std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"got\\":"; '
                    f'{_cpp_result(result, c.get("expected"))} '
                    f'std::cout << "}}\\n" << std::flush;')
        body.append(f'  try {{ {decl} {line} }}\n'
                    f'  catch (...) {{ std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"error\\":\\"exception\\"}}\\n" '
                    f'<< std::flush; }}')
    # its own main (to try it out) would clash with this one; `signed` survives a `#define int long long`
    code = re.sub(r"\b(int|signed|int32_t|int64_t|long|auto|void)(\s+)main(\s*\()", r"\1\2_sn_own_main\3", code)
    judge = not re.search(r"^\s*#\s*include\b", code, re.M) or _leetcode_form(code, function)
    nodes = CPP_NODE_HELPERS if any(shapes) or result else ""
    return ((CPP_JUDGE_HEAD if judge else "") + classes + code + "\n" + CPP_PRINT + nodes
            + "\nsigned main() {\n" + "\n".join(body) + "\n  return 0;\n}\n")


# ---------- the class a problem asks for ----------

# A constructor names no return type, so it is not found as a method is: what follows its parameter list is the
# initializer list it may carry and then its body.
CPP_CTOR_OPENS = r"\s*(?::[^;{]*)?\{"


def _cpp_class_span(masked: str, cls: str) -> tuple[int, int] | None:
    """(just inside the brace that opens the body of class `cls`, that body's closing brace), None when the code
    declares no such class with a body, or declares it on a base class the judge provides: LeetCode's 284 derives
    its answer from an Iterator its judge defines and the statement says not to write, so there is no building
    the class here."""
    m = re.search(r"\b(?:class|struct)\s+" + re.escape(cls) + r"\b([^;{]*)\{", masked)
    if m is None or _cpp_judge_base(masked, m.group(1)):
        return None
    end = _closing(masked, m.end() - 1, "{", "}")
    return None if end < 0 else (m.end(), end - 1)


def _cpp_judge_base(masked: str, header: str) -> bool:
    """Whether what a class declaration writes between its name and its body names a base class the answer does
    not define, which is one the judge provides."""
    for part in _split_top(header.partition(":")[2]):
        # the base's own name, without the access label before it or the template arguments after it; a
        # qualified one (std::, a namespace's) is the library's and not the answer's to define
        base = re.match(r"[\w:\s]*", re.sub(r"\b(?:public|private|protected|virtual)\b", " ", part)).group(0).strip()
        if base and "::" not in base and not _cpp_defines(masked, base):
            return True
    return False


def _cpp_member(masked: str, span: tuple[int, int], at: int) -> bool:
    """Whether what is at `at` is a member of that class body itself, and not of a class or a function nested in
    it: an answer writes a Trie of its own beside the class the problem asks for, whose methods carry the same
    names (211), and a call written inside a method's body carries one too."""
    start, end = span
    return start <= at < end and masked.count("{", start, at) == masked.count("}", start, at)


def _cpp_ctor(masked: str, span: tuple[int, int], cls: str, arity: int) -> list[tuple[str, str]] | None:
    """[(value type, name)] of the parameters of the constructor that takes `arity` arguments, [] where the class
    writes none of its own and the call passes none (it is built with (), as its implicit constructor takes),
    None where it writes none that takes them, or one the check cannot fill."""
    written = False
    for at, params, _ in _definitions(masked, cls, r"", CPP_CTOR_OPENS):
        if not _cpp_member(masked, span, at):
            continue
        written = True
        found = _cpp_params(params)
        if found is not None and len(found) == arity:
            return found
    return [] if not written and arity == 0 else None


def _cpp_method(masked: str, span: tuple[int, int], name: str, arity: int) -> tuple[str, list] | None:
    """(return type, [(value type, name)] of its parameters) of the method `name` the class writes for `arity`
    arguments, the public one where it writes both, None where it writes none or one the check cannot fill."""
    picked = []
    for at, params, before in _definitions(masked, name, r"", CPP_BODY_OPENS):
        if not _cpp_member(masked, span, at):
            continue
        ret = re.sub(r"\b(static|inline|virtual|constexpr|explicit|friend)\b", " ",
                     _return_type(masked, at, before))
        if not ret.strip() or re.search(r"[=()]|\breturn\b", ret):   # a call, not a definition
            continue
        found = _cpp_params(params)
        if found is None or len(found) != arity:
            continue
        picked.append((_cpp_private(masked, at), (_cpp_type(ret), found)))
    return next((d for private, d in picked if not private), picked[0][1] if picked else None)


def _cpp_node_shape(t: str) -> list | None:
    """The shape of a node a declaration names, as the function path's shapes are written, for a type the check
    reads here itself. LeetCode's `Node` is the name of several shapes there, so it is left to be refused."""
    m = re.fullmatch(r"(?:vector<)?(TreeNode|ListNode)\*>?", t)
    if m is None:
        return None
    many = "s" if t.startswith("vector<") else ""
    return ["tree" + many if m.group(1) == "TreeNode" else "list" + many, m.group(1)]


def cpp_design_harness(code: str, cls: str, calls: list) -> str | None:
    """The answer's class, built and then called as the problem's own example calls it: the calls in the order
    the statement states them, on one object, each result printed as the judge compares it. A call that raises
    stops the rest, since what the object holds after it is no longer the problem's. None where a call cannot be
    made from the example's values (a declaration the check cannot fill, a method the class does not write, a
    result it cannot print), so the card says so rather than running it wrong."""
    masked = _mask(code)
    span = _cpp_class_span(masked, cls)
    if span is None or not calls:
        return None

    def read(i: int, c: dict, arity: int):
        """(what the call returns, [(value type, name)] of its parameters) of the member a call names, None when
        the class writes no such one. The call the statement states first is the constructor, whatever it names
        it, and it returns nothing."""
        if i == 0:
            found = _cpp_ctor(masked, span, cls, arity)
            return None if found is None else ("void", found)
        name = str(c.get("call") or "")
        return _cpp_method(masked, span, name, arity) if name.isidentifier() else None

    nodes, body = [], []
    for i, c in enumerate(calls):
        args = list(c.get("args") or [])
        found = read(i, c, len(args))
        if found is None and args == [None]:   # a call that takes nothing, which some statements write as [null]
            args, found = [], read(i, c, 0)
        if found is None:
            return None
        ret, params = found
        types = [t for t, _ in params]
        if len(args) != len(types):
            return None
        shapes = (list(c.get("shapes") or []) + [None] * len(types))[:len(types)]
        if i == 0:   # nothing but this reads a constructor's declaration, so its own node arguments are read here
            shapes = [s or _cpp_node_shape(t) for s, t in zip(shapes, types)]
        result = None if i == 0 else c.get("result")
        void = ret == "void"
        if not void and not (_cpp_node_ok(result, ret) if result else _cpp_printable(ret)):
            return None
        values = _cpp_values(types, shapes, args)
        if values is None:
            return None
        nodes += [s for s in shapes if s] + ([result] if result else [])
        decl = " ".join(f"{_cpp_std(t)} _a{k} = {v};" for k, t, v in values)
        made = ", ".join(f"_a{k}" for k in range(len(types)))
        if i == 0:
            call = f"_sn_obj = sn_check::muted([&] {{ return new {cls}({made}); }});"
        elif void:
            call = f'sn_check::muted([&] {{ _sn_obj->{c["call"]}({made}); }});'
        else:
            call = f'auto _r = sn_check::muted([&] {{ return _sn_obj->{c["call"]}({made}); }});'
        line = f'std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"got\\":null}}\\n" << std::flush;' if void else (
            f'std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"got\\":"; '
            f'{_cpp_result(result, c.get("expected"))} std::cout << "}}\\n" << std::flush;')
        body.append(f'  try {{ {decl} {call} {line} }}\n'
                    f'  catch (...) {{ std::cout << "\\n{CASE_MARK}{{\\"i\\":{i},\\"error\\":\\"exception\\"}}\\n"'
                    f' << std::flush; return 0; }}')
    classes = _cpp_classes(masked, nodes, None)
    if classes is None:
        return None
    # its own main (to try the class out) would clash with this one; `signed` survives a `#define int long long`
    code = re.sub(r"\b(int|signed|int32_t|int64_t|long|auto|void)(\s+)main(\s*\()", r"\1\2_sn_own_main\3", code)
    # the class a problem asks for is written for a judge that adds every header and `using namespace std`, as
    # `class Solution` is on the function path, and gets them even where it includes a header of its own (2102
    # includes __gnu_pbds and still writes `less<T>` unqualified)
    return (CPP_JUDGE_HEAD + classes + code + "\n" + CPP_PRINT
            + (CPP_NODE_HELPERS if nodes else "")
            + f"\nsigned main() {{\n  {cls}* _sn_obj = nullptr;\n" + "\n".join(body) + "\n  return 0;\n}\n")
