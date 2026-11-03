"""Java: the answer's class, and a main beside it that calls its method on each example with the values the
example holds, made into the types the method declares."""
from __future__ import annotations

import re

from .common import (
    CASE_MARK, IDENT, MAX_CASES, _c_escapes, _definitions, _finite, _leetcode_form, _mask, _owner, _return_type,
    _split_top
)


# ---------- Java ----------

# The answer's classes lose a top-level `public` (one file may hold one public class, and here it is the harness's,
# which the runner names the file after and runs). The printer handles boxed numbers, strings, arrays of any depth
# and collections by reflection. While the answer runs, System.out goes nowhere (see HARNESS).
JAVA_MAIN = """
public class SnCheck {
  static String str(String s) {
    StringBuilder b = new StringBuilder("\\"");
    for (char c : s.toCharArray()) {
      if (c == '"' || c == '\\\\') b.append('\\\\').append(c);
      else if (c < 0x20) b.append(String.format("\\\\u%%04x", (int) c));
      else b.append(c);
    }
    return b.append('"').toString();
  }
  static String json(Object v) {
    if (v == null) return "null";
    if (v instanceof String) return str((String) v);
    if (v instanceof Character) return str(String.valueOf(v));
    if (v instanceof Boolean) return v.toString();
    if (v instanceof Double || v instanceof Float) {
      double d = ((Number) v).doubleValue();
      return Double.isNaN(d) || Double.isInfinite(d) ? "null" : Double.toString(d);
    }
    if (v instanceof Number) return v.toString();
%(nodes)s    StringBuilder b = new StringBuilder("[");
    if (v.getClass().isArray()) {
      for (int i = 0; i < java.lang.reflect.Array.getLength(v); i++) {
        if (i > 0) b.append(',');
        b.append(json(java.lang.reflect.Array.get(v, i)));
      }
      return b.append(']').toString();
    }
    if (v instanceof Iterable) {
      boolean first = true;
      for (Object o : (Iterable<?>) v) { if (!first) b.append(','); first = false; b.append(json(o)); }
      return b.append(']').toString();
    }
    return str(v.toString());
  }
  static final java.io.PrintStream REAL = System.out;
  static final java.io.PrintStream NULL = new java.io.PrintStream(java.io.OutputStream.nullOutputStream());
  static void out(String s) { REAL.println("\\n%(mark)s" + s); REAL.flush(); }
%(helpers)s  public static void main(String[] args) {
%(body)s
  }
}
"""


JAVA_BOXED = {"int": "Integer", "long": "Long", "double": "Double", "float": "Float", "boolean": "Boolean",
              "char": "Character", "short": "Short", "byte": "Byte"}


JAVA_SCALARS = set(JAVA_BOXED) | set(JAVA_BOXED.values()) | {"String"}


JAVA_MODIFIERS = r"\b(public|private|protected|static|final|synchronized|abstract|native|strictfp|default)\b"


JAVA_ANNOTATION = r"@\w+(\([^)]*\))?"


JAVA_BODY = r"\s*(?:throws\s+[\w.,\s]+)?\{"   # what comes between a method's parameter list and its body


JAVA_PACKAGE = re.compile(r"^[ \t]*package\s+[\w.]+\s*;", re.M)


# LeetCode's form (_leetcode_form) is written for a judge that imports the standard library itself (as
# CPP_JUDGE_HEAD): it gets the packages an answer uses without saying so. Programmers' judge imports nothing.
JAVA_JUDGE_HEAD = "import java.util.*;\nimport java.util.function.*;\nimport java.util.stream.*;\nimport java.math.*;\n"
# javafx.util.Pair is on LeetCode's Java classpath and an answer written there uses it without importing it;
# this image has no JavaFX, so the class it uses is defined beside the answer, with the methods that class has.
# An import of it is dropped, since a file cannot both import a type and declare one of that name.
JAVA_PAIR = """class Pair<K, V> {
  private final K key;
  private final V value;
  public Pair(K key, V value) {
    this.key = key;
    this.value = value;
  }
  public K getKey() {
    return key;
  }
  public V getValue() {
    return value;
  }
  @Override
  public boolean equals(Object o) {
    if (this == o) return true;
    if (!(o instanceof Pair)) return false;
    Pair<?, ?> p = (Pair<?, ?>) o;
    return java.util.Objects.equals(key, p.key) && java.util.Objects.equals(value, p.value);
  }
  @Override
  public int hashCode() {
    return java.util.Objects.hash(key, value);
  }
  @Override
  public String toString() {
    return key + "=" + value;
  }
}
"""
JAVA_PAIR_IMPORT = re.compile(r"^[ \t]*import\s+javafx\.util\.(?:Pair|\*)\s*;[ \t]*\n?", re.M)


# ---------- a tree or a linked list as an example writes it ----------

# LeetCode's judge provides these classes and writes a tree or a list as the level-order list the statement
# shows (`root = [3,9,20,null,null,15,7]`, `head = [1,2,3]`), so an answer written there uses them without
# defining them (its own copy is usually there as a comment, which is no definition). They go in beside the
# answer, at the file level, since the method they belong to names them from outside the harness's own class.
JAVA_NODE_CLASSES = {
    "TreeNode": """
class TreeNode {
  int val;
  TreeNode left;
  TreeNode right;
  TreeNode() {}
  TreeNode(int val) { this.val = val; }
  TreeNode(int val, TreeNode left, TreeNode right) { this.val = val; this.left = left; this.right = right; }
}
""",
    "ListNode": """
class ListNode {
  int val;
  ListNode next;
  ListNode() {}
  ListNode(int val) { this.val = val; }
  ListNode(int val, ListNode next) { this.val = val; this.next = next; }
}
""",
}


# In the harness, beside the answer: the example's list becomes nodes of the class the declaration names, and a
# node that comes back becomes a list again, so the comparing stays on JSON values. The fields and the
# constructors are reached by reflection, so a class the answer defines itself is filled like the one added here,
# whatever it keeps private and whichever constructors it has. A statement that gives a node by its value instead
# of its list (`root = [3,5,1], p = 5`) means the node of the tree with that value, as its judge does. A list or a
# tree that runs in a circle is walked once round, not forever.
# SN_CAP: a tree in a circle, or one node shared deep, printed no longer than the runner's reply (MAX_OUTPUT)
JAVA_NODE_HELPERS = """  static final int SN_CAP = 3000;
  static final String[] SN_SIDES = {"left", "right"};
  static final String[] SN_REACH = {"left", "right", "next"};
  static java.lang.reflect.Field snField(Object o, String name) {
    for (Class<?> k = o == null ? null : o.getClass(); k != null; k = k.getSuperclass()) {
      try {
        java.lang.reflect.Field f = k.getDeclaredField(name);
        f.setAccessible(true);
        return f;
      } catch (NoSuchFieldException e) {   // the field may be the superclass's, or there may be none of that name
        continue;
      }
    }
    return null;
  }
  static Object snGet(Object o, String name) {
    java.lang.reflect.Field f = snField(o, name);
    try {
      return f == null ? null : f.get(o);
    } catch (IllegalAccessException e) {
      return null;
    }
  }
  static void snSet(Object o, String name, Object v) throws Exception {
    java.lang.reflect.Field f = snField(o, name);
    if (f == null) throw new RuntimeException("no field " + name + " in " + o.getClass().getName());
    f.set(o, v);
  }
  static boolean snNode(Object v) {
    return snField(v, "val") != null
        && (snField(v, "left") != null || snField(v, "right") != null || snField(v, "next") != null);
  }
  static boolean snEq(Object a, Object b) {   // a node's own value and the example's may be boxed differently
    if (a instanceof Number && b instanceof Number) return ((Number) a).doubleValue() == ((Number) b).doubleValue();
    return a == null ? b == null : a.equals(b);
  }
  static boolean snTakes(Class<?>[] p, Object v) {
    if (!(p[0].isPrimitive() || p[0].isInstance(v))) return false;
    for (int i = 1; i < p.length; i++) if (p[i].isPrimitive()) return false;   // the children, left out as null
    return true;
  }
  static Object snNew(Class<?> c, Object v) throws Exception {
    java.lang.reflect.Constructor<?> empty = null, one = null;
    for (java.lang.reflect.Constructor<?> k : c.getDeclaredConstructors()) {
      Class<?>[] p = k.getParameterTypes();
      if (p.length == 0) empty = k;
      else if (one == null && snTakes(p, v)) one = k;
    }
    Object node;
    if (empty != null) {
      empty.setAccessible(true);
      node = empty.newInstance();
    } else if (one != null) {
      one.setAccessible(true);
      Object[] a = new Object[one.getParameterCount()];
      a[0] = v;
      node = one.newInstance(a);
    } else {
      throw new RuntimeException("no constructor of " + c.getName() + " takes a value");
    }
    if (v != null) snSet(node, "val", v);   // an example's list may write a null where a node holds no value
    return node;
  }
  static Object snTree(Class<?> c, Object[] v) throws Exception {
    if (v.length == 0 || v[0] == null) return null;
    java.util.ArrayList<Object> q = new java.util.ArrayList<Object>();
    q.add(snNew(c, v[0]));
    int at = 1;
    for (int i = 0; i < q.size() && at < v.length; i++) {
      for (String side : SN_SIDES) {
        if (at >= v.length) break;
        Object x = v[at++];
        if (x == null) continue;   // a missing child, whose own children the example does not write at all
        Object child = snNew(c, x);
        snSet(q.get(i), side, child);
        q.add(child);
      }
    }
    return q.get(0);
  }
  static Object snChain(Class<?> c, Object[] v) throws Exception {
    Object head = null;
    for (int i = v.length - 1; i >= 0; i--) {
      Object node = snNew(c, v[i]);
      snSet(node, "next", head);
      head = node;
    }
    return head;
  }
  static Object snFind(Object root, Object v) throws Exception {
    java.util.ArrayList<Object> q = new java.util.ArrayList<Object>();
    java.util.IdentityHashMap<Object, Boolean> seen = new java.util.IdentityHashMap<Object, Boolean>();
    q.add(root);
    for (int i = 0; i < q.size(); i++) {
      Object node = q.get(i);
      if (node == null || seen.put(node, Boolean.TRUE) != null) continue;
      if (snEq(snGet(node, "val"), v)) return node;
      for (String side : SN_REACH) q.add(snGet(node, side));
    }
    // a statement may name a value the structure does not hold (LeetCode 1644 states p = 10 for a tree
    // without it): its judge hands the answer a node of that value all the same
    return root == null ? null : snNew(root.getClass(), v);
  }
  static String snJson(Object v) {
    java.util.ArrayList<Object> out = new java.util.ArrayList<Object>();
    java.util.IdentityHashMap<Object, Boolean> seen = new java.util.IdentityHashMap<Object, Boolean>();
    // a tree keeps no record of what it has seen: an answer that memoizes its subtrees hangs the same node in
    // two places and a judge writes it in both. SN_CAP is what stops a tree made in a circle
    if (snField(v, "left") != null || snField(v, "right") != null) {
      java.util.ArrayList<Object> q = new java.util.ArrayList<Object>();
      q.add(v);
      for (int i = 0; i < q.size() && out.size() < SN_CAP; i++) {
        Object node = q.get(i);
        if (node == null) {
          out.add(null);
          continue;
        }
        out.add(snGet(node, "val"));
        q.add(snGet(node, "left"));
        q.add(snGet(node, "right"));
      }
      while (!out.isEmpty() && out.get(out.size() - 1) == null) out.remove(out.size() - 1);
    } else {
      for (Object node = v; node != null && out.size() < SN_CAP && seen.put(node, Boolean.TRUE) == null;
           node = snGet(node, "next")) out.add(snGet(node, "val"));
    }
    return json(out);
  }
  static java.util.List<Object> snList(Object v) {
    java.util.ArrayList<Object> out = new java.util.ArrayList<Object>();
    if (v.getClass().isArray()) {
      for (int i = 0; i < java.lang.reflect.Array.getLength(v); i++) out.add(java.lang.reflect.Array.get(v, i));
    } else if (v instanceof Iterable) {
      for (Object x : (Iterable<?>) v) out.add(x);
    } else {
      out.add(v);
    }
    return out;
  }
  static String snSaid(Object v) {   // as an example writes a node: no node at all is the empty list, not nothing
    return v == null ? "[]" : json(v);
  }
  static String snSaidMany(Object v) {
    if (v == null) return "[]";
    StringBuilder b = new StringBuilder("[");
    for (Object x : snList(v)) {
      if (b.length() > 1) b.append(',');
      b.append(snSaid(x));
    }
    return b.append(']').toString();
  }
  static String snPlain(Object v) {   // a node the statement shows as that node's own value, not as its list
    return v == null ? "null" : snNode(v) ? json(snGet(v, "val")) : json(v);
  }
"""


JAVA_CLASS_DECL = r"\b(?:class|interface|enum|record)\s+%s\b"


def _java_type(t: str) -> str:
    t = re.sub(JAVA_ANNOTATION, " ", t)
    t = re.sub(r"\bfinal\b", " ", t)
    t = re.sub(r"\bjava\.(util|lang)\.", "", t)
    t = re.sub(r"\s*([<>,\[\]])\s*", r"\1", " ".join(t.split()))
    return t.replace("...", "[]")


def _java_params(parts: list[str]) -> tuple[list[str], list[str]] | None:
    """(the types, the names) of a parameter list already split at its commas, None when one of them cannot be
    read."""
    types, names = [], []
    for part in parts:
        pm = re.fullmatch(r"(.*?)\s*(\.\.\.)?\s*([A-Za-z_$][\w$]*)", _java_type(part).replace("[]", "[] ").strip(), re.A)
        if not pm:
            return None
        types.append(_java_type(pm.group(1) + ("[]" if pm.group(2) else "")))
        names.append(pm.group(3))
    return types, names


def _java_return(masked: str, name: int, before: str) -> str:
    """What the declaration whose name is at `name` says it gives back, "" where what comes before the name is no
    type at all, as a constructor's line carries its modifiers alone."""
    return _java_type(re.sub(JAVA_MODIFIERS, " ", re.sub(JAVA_ANNOTATION, " ", _return_type(masked, name, before))))


def _java_definition(code: str, function: str, arity: int | None = None) \
        -> tuple[str, list[str], list[str], int, str] | None:
    """(return type, parameter types, parameter names, where the name is, the masked source) of the method
    `function`, None when it is not found or not fillable; with `arity`, the overload that takes that many."""
    masked = _mask(code)
    private = None
    for name, params, before in _definitions(masked, function, r"", JAVA_BODY):
        ret = _java_return(masked, name, before)
        if not ret or ret.startswith("<") or re.search(r"[=()]|\b(new|return|else)\b", ret):   # generic, or a call
            continue
        parts = _split_top(params)
        if arity is not None and len(parts) != arity:
            continue
        read = _java_params(parts)
        if read is None:
            return None
        decl = (ret, read[0], read[1], name, masked)
        if arity is None or not re.search(r"\bprivate\b", before):
            return decl
        private = private or decl   # a private helper of the same arity: called only when there is nothing else
    return private


def _java_signature(code: str, function: str, arity: int | None = None) -> tuple[str, list[str]] | None:
    """(return type, parameter types) of the method `function`, None when it is not found or not fillable."""
    d = _java_definition(code, function, arity)
    return (d[0], d[1]) if d else None


def _drop_public(code: str) -> str:
    """A class's `public` taken off, wherever the line has it among its modifiers (`final public class`, an indented
    one): a public class would have to be in a file of its name, and the file is the harness's."""
    return re.sub(r"^([ \t]*(?:(?:final|abstract|strictfp)\s+)*)public\s+((?:(?:final|abstract|strictfp)\s+)*"
                  r"(?:class|interface|enum|record)\s)", r"\1\2", code, flags=re.M)


def _drop_java_package(code: str) -> str:
    """Java source without its package declaration, found where comments and strings are blanked out (a line of a
    text block that reads like one stays); a package line would put SnCheck where `java SnCheck` does not look."""
    m = JAVA_PACKAGE.search(_mask(code))
    return code[:m.start()] + code[m.end():] if m else code


def _java_in_class(code: str) -> str:
    """A method given without its class (an excerpt of the answer) put into `class Solution`, after the imports."""
    lines, masked = code.split("\n"), _mask(code).split("\n")
    k = 0
    while k < len(lines) and re.match(r"\s*(?:$|import\s)", masked[k]):   # blank, a comment, an import
        k += 1
    return "\n".join(lines[:k] + ["class Solution {"] + lines[k:] + ["}"])


def _java_str(s: str) -> str:
    """A Java string literal, with octal escapes for control characters and never \\u (Java turns those into
    characters before it reads the source, so an escaped newline would end the literal)."""
    return '"' + _c_escapes(s) + '"'


def _java_value(t: str, v) -> str | None:
    """A Java expression of type `t` for the JSON value `v`, None when the type is not one the check knows."""
    if t.endswith("[]"):
        inner = t[:-2]
        if not isinstance(v, list):
            return None
        items = [_java_value(inner, x) for x in v]
        return None if None in items else f"new {t}{{{', '.join(items)}}}"
    m = re.fullmatch(r"(List|ArrayList|LinkedList|Collection)<(.+)>", t)
    if m:
        kind, inner = m.groups()
        if not isinstance(v, list) or inner in JAVA_BOXED:
            return None
        items = [_java_value(inner, x) for x in v]
        made = "LinkedList" if kind == "LinkedList" else "ArrayList"
        return None if None in items else \
            f"new java.util.{made}<{inner}>(java.util.Arrays.<{inner}>asList({', '.join(items)}))"
    base = {b: p for p, b in JAVA_BOXED.items()}.get(t, t)
    if base in ("int", "short", "byte"):
        limit = {"int": 2 ** 31, "short": 2 ** 15, "byte": 2 ** 7}[base]
        ok = isinstance(v, int) and not isinstance(v, bool) and -limit <= v < limit
        return (str(v) if base == "int" else f"({base}){v}") if ok else None
    if base == "long":
        return f"{v}L" if isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2 ** 63 else None
    if base in ("double", "float"):
        f = _finite(v)
        return None if f is None else repr(f) + ("f" if base == "float" else "")
    if base == "boolean":
        return ("true" if v else "false") if isinstance(v, bool) else None
    if base == "char":
        if not (isinstance(v, str) and len(v) == 1 and 0x20 <= ord(v) <= 0xFFFF):
            return None
        return "'\\''" if v == "'" else "'\\\\'" if v == "\\" else f"'{v}'"
    if t == "String":
        return _java_str(v) if isinstance(v, str) else None
    return None


def _java_known(t: str) -> bool:
    if t.endswith("[]"):
        return _java_known(t[:-2])
    m = re.fullmatch(r"(?:List|ArrayList|LinkedList|Collection)<(.+)>", t)
    return _java_known(m.group(1)) if m else t in JAVA_SCALARS


def _java_boxed(v) -> str | None:
    """A Java expression for one value of the level-order list an example writes, as an Object whatever the node's
    own field holds, None for a value the check cannot write."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        if -2 ** 31 <= v < 2 ** 31:
            return str(v)
        return f"{v}L" if -2 ** 63 <= v < 2 ** 63 else None
    if isinstance(v, float):
        f = _finite(v)
        return None if f is None else repr(f)
    if isinstance(v, str):
        return _java_str(v)
    return None


def _java_node(t: str, shape: list | None) -> tuple[str, str, str] | None:
    """(the node class, how the declaration holds it, the helper that builds one) for a parameter or a result of
    a node shape: "" for one node, "[]" for an array of them, else the collection the declaration names. None
    when the declared type is another class, as it is where the shape was read off how the code uses a name and
    not off the type (`PolyNode poly1` used as `poly1.next`): such an argument is filled as it was before."""
    if not shape:
        return None
    cls, build = shape[1], "snTree" if shape[0].startswith("tree") else "snChain"
    if t == cls:
        return cls, "", build
    if t == cls + "[]":
        return cls, "[]", build
    m = re.fullmatch(r"(List|ArrayList|LinkedList|Collection)<(.+)>", t)
    return (cls, m.group(1), build) if m and m.group(2) == cls else None


JAVA_NODE_SHAPE = {"TreeNode": "tree", "ListNode": "list"}


def _java_shape(t: str) -> list | None:
    """The shape of a declared type that names one of the node classes a judge provides, read as the function
    path reads the shapes of a declaration (codecheck._node_shape). It is what a constructor's arguments and its
    class's methods go by where nothing was read for them: in Java a parameter always says its type, and no
    declaration of a method named `__init__` carries the constructor's."""
    m = re.fullmatch(r"(?:List|ArrayList|LinkedList|Collection)<(.+)>", t)
    cls = m.group(1) if m else t[:-2] if t.endswith("[]") else t
    kind = JAVA_NODE_SHAPE.get(cls)
    return None if kind is None else [kind + ("s" if cls != t else ""), cls]


def _java_declares(masked: str, name: str) -> str:
    """Where masked Java source declares a class `name`: "top" at the file level, "nested" inside another class
    (which the harness's own code cannot name), "" when it declares none of that name at all."""
    where = ""
    for m in re.finditer(JAVA_CLASS_DECL % re.escape(name), masked):
        if masked.count("{", 0, m.start()) == masked.count("}", 0, m.start()):
            return "top"
        where = "nested"
    return where


def _java_node_classes(nodes: list, masked: str) -> str | None:
    """The node classes to define beside the answer: LeetCode's own for each class the answer uses without
    defining it, and nothing for one it defines itself. None when the answer's own is nested in another class,
    which the harness cannot name from outside, or when it defines none and no definition here carries that
    name."""
    out, wanted = [], list(dict.fromkeys(n[0] for n in nodes))
    for cls in wanted:
        where = _java_declares(masked, cls)
        if where == "top":
            continue
        if where or cls not in JAVA_NODE_CLASSES:
            return None
        out.append(JAVA_NODE_CLASSES[cls])
    # a class the answer only builds (`new TreeNode(...)` from a plain array) is the judge's to define too; one
    # it declares itself, or declares nested, is left alone, since nothing here has to name it
    for cls in JAVA_NODE_CLASSES:
        if cls not in wanted and re.search(r"\b%s\b" % cls, masked) and not _java_declares(masked, cls):
            out.append(JAVA_NODE_CLASSES[cls])
    return "".join(out)


def _java_made(node: tuple, v) -> bool:
    """Whether an example gives this argument as the node's own level-order list (or one list per node), rather
    than as the value of a node in the structure the arguments build (`root = [3,5,1], p = 5`)."""
    if not isinstance(v, list):
        return False
    return all(isinstance(x, list) for x in v) if node[1] else True


def _java_hold(node: tuple, items: list[str]) -> str:
    """One expression of the declared type for the nodes built for it: the node itself, an array of them, or the
    collection the declaration names."""
    cls, container = node[0], node[1]
    if not container:
        return items[0]
    if container == "[]":
        return f"new {cls}[]{{{', '.join(items)}}}"
    made = "LinkedList" if container == "LinkedList" else "ArrayList"
    return f"new java.util.{made}<{cls}>(java.util.Arrays.<{cls}>asList({', '.join(items)}))"


def _java_one(node: tuple, v) -> str | None:
    """The expression that builds one node structure from the level-order list an example writes."""
    items = [_java_boxed(x) for x in v] if isinstance(v, list) else [None]
    if None in items:
        return None
    return f"({node[0]}) {node[2]}({node[0]}.class, new Object[]{{{', '.join(items)}}})"


def _java_build(node: tuple, v) -> str | None:
    """A Java expression for an argument an example gives as the node's own list (or one list per node)."""
    items = [_java_one(node, x) for x in v] if node[1] else [_java_one(node, v)]
    return None if None in items else _java_hold(node, items)


def _java_search(node: tuple, v, root: str) -> str | None:
    """A Java expression for an argument an example gives by a node's value: the node of the structure already
    built that holds it, as its judge does."""
    values = [_java_boxed(x) for x in v] if node[1] and isinstance(v, list) else [_java_boxed(v)]
    if None in values:
        return None
    return _java_hold(node, [f"({node[0]}) snFind({root}, {x})" for x in values])


def _java_root(node: tuple, k: int) -> str:
    """The structure a node given by its value is looked for in: the argument itself, or the first of the nodes
    its declaration holds."""
    if not node[1]:
        return f"_a{k}"
    if node[1] == "[]":
        return f"(_a{k}.length == 0 ? null : _a{k}[0])"
    return f"(_a{k}.isEmpty() ? null : _a{k}.iterator().next())"


def _java_arguments(params: list[str], nodes: list, args: list) -> str | None:
    """The declarations `_a0`, `_a1`... of one call's arguments, from the values the example holds, None when one
    of them cannot be made into the type its parameter declares."""
    made = [bool(nodes[k]) and _java_made(nodes[k], a) for k, a in enumerate(args)]
    # the arguments an example gives as a list are built first, so one it gives by a node's value can be
    # looked for in them whichever order the parameters come in
    order = [k for k in range(len(params)) if not nodes[k] or made[k]] \
        + [k for k in range(len(params)) if nodes[k] and not made[k]]
    root = next((_java_root(nodes[k], k) for k in range(len(params)) if made[k]), "null")
    values = {}
    for k in order:
        values[k] = _java_value(params[k], args[k]) if not nodes[k] \
            else _java_build(nodes[k], args[k]) if made[k] else _java_search(nodes[k], args[k], root)
    if None in values.values():
        return None
    return " ".join(f"{params[k]} _a{k} = {values[k]};" for k in order)


def _java_after(k: int, node: tuple | None) -> str:
    """What the harness prints for an argument after a call that returned nothing, a node of it as an example
    writes one."""
    if node is None:
        return f"json(_a{k})"
    return f"snSaid(_a{k})" if not node[1] else f"snSaidMany(_a{k})"


def _java_shown(node: tuple | None, expected) -> str:
    """What the harness prints for the result: the JSON its judge compares. A node the statement shows as a plain
    value (the example's expected is no list) is that node's own value."""
    if node is None:
        return "json(_r)"
    if not node[1]:
        return "snSaid(_r)" if isinstance(expected, list) else "snPlain(_r)"
    return "snSaidMany(_r)"


def java_harness(code: str, function: str, cases: list, shapes: list | None = None, result: list | None = None) -> str | None:
    """The answer's Java with a SnCheck class whose main calls `function` on each example, None when its
    declaration cannot be filled from the examples (see cpp_harness). A parameter or a result that is a tree or a
    linked list is built from the level-order list the example writes, and printed as one again."""
    code = _drop_java_package(code)
    arity = len(cases[0].get("args") or []) if cases and isinstance(cases[0].get("args"), list) else None
    found = _java_definition(code, function, arity)
    if found is not None and _owner(found[4], found[3]) == "":   # a method outside any class
        code = _java_in_class(code)
        found = _java_definition(code, function, arity)
    if found is None:
        return None
    ret, params, _, name, masked = found
    void = ret == "void"
    shapes = list(shapes or []) + [None] * len(params)
    nodes = [_java_node(t, shapes[k]) for k, t in enumerate(params)]
    kept = _java_node(ret, result)
    if not (_java_known(ret) or kept or void and all(_java_known(t) or nodes[k] for k, t in enumerate(params))):
        return None
    classes = _java_node_classes([n for n in nodes + [kept] if n], masked)
    if classes is None:
        return None
    owner = _owner(masked, name)   # the class that holds the method itself, not a helper class beside it
    if not owner:
        return None
    line = masked[masked.rfind("\n", 0, name) + 1:name]
    target = f"{owner}." if re.search(r"\bstatic\b", line) else f"new {owner}()."
    body = []
    for i, c in enumerate(cases[:MAX_CASES]):
        args = c.get("args") or []
        if not isinstance(args, list) or len(args) != len(params):
            return None
        decl = _java_arguments(params, nodes, args)
        if decl is None:
            return None
        call = f"{target}{function}({', '.join(f'_a{k}' for k in range(len(params)))})"
        if void:
            after = ' + "," + '.join(_java_after(k, nodes[k]) for k in range(len(params))) or '""'
            line = (f'System.setOut(NULL); try {{ {call}; }} finally {{ System.setOut(REAL); }} '
                    f'out("{{\\"i\\":{i},\\"got\\":null,\\"after\\":[" + {after} + "]}}");')
        else:
            line = (f'Object _r; System.setOut(NULL); try {{ _r = {call}; }} finally {{ System.setOut(REAL); }} '
                    f'out("{{\\"i\\":{i},\\"got\\":" + {_java_shown(kept, c.get("expected"))} + "}}");')
        body.append(f'    try {{ {decl} {line} }}\n'
                    f'    catch (Throwable _e) {{ out("{{\\"i\\":{i},\\"error\\":" + str(String.valueOf(_e)) + "}}"); }}')
    code = _drop_public(code)
    pair = ""
    seen = _mask(code)
    if re.search(r"\bPair\s*[<(]", seen) and not _java_declares(seen, "Pair"):
        code, pair = JAVA_PAIR_IMPORT.sub("", code), JAVA_PAIR
    if _leetcode_form(code, function):
        code = JAVA_JUDGE_HEAD + code
    helpers = JAVA_NODE_HELPERS if any(nodes) or kept else ""
    return code + "\n" + pair + classes + JAVA_MAIN % {
        "mark": CASE_MARK, "body": "\n".join(body), "helpers": helpers,
        "nodes": "    if (snNode(v)) return snJson(v);\n" if helpers else ""}


# ---------- a class a problem asks for ----------

def _java_constructor(code: str, cls: str, arity: int) -> tuple[str, list[str], list[str]] | None:
    """("void", parameter types, parameter names) of the constructor of `cls` that takes `arity` arguments: a
    constructor gives nothing back, which is what the statement's third list writes for the call that builds the
    object. A class that declares no constructor is built by the one it is given, which takes nothing. None when
    the class declares constructors and none of them takes that many, when the one that does cannot be called
    from outside, or when a parameter cannot be read."""
    masked = _mask(code)
    declared = False
    for name, params, before in _definitions(masked, cls, r"", JAVA_BODY):
        # a method whose own name is the class's but that gives something back is no constructor, and the
        # `new Cls(...) {` of an anonymous class sits inside a method, which owns no member of the class
        if _owner(masked, name) != cls or _java_return(masked, name, before):
            continue
        declared = True
        parts = _split_top(params)
        if len(parts) != arity or re.search(r"\bprivate\b", before):
            continue
        read = _java_params(parts)
        return None if read is None else ("void", read[0], read[1])
    return None if declared or arity else ("void", [], [])


def _java_method(code: str, cls: str, function: str, arity: int) -> tuple[str, list[str], list[str]] | None:
    """(what it gives back, parameter types, parameter names) of the method `function` of the class `cls` that
    takes `arity` arguments, None when the class declares no such method, when it cannot be called from outside,
    or when one of its types cannot be read. Read off that class alone, since a helper class beside it may
    declare a method of the same name: LeetCode's own 716 answer writes `pop` on its list class as well as on
    the stack the problem asks for."""
    masked = _mask(code)
    for name, params, before in _definitions(masked, function, r"", JAVA_BODY):
        if _owner(masked, name) != cls or re.search(r"\bprivate\b", before):
            continue
        ret = _java_return(masked, name, before)
        if not ret or ret.startswith("<") or re.search(r"[=()]|\b(new|return|else)\b", ret):   # generic, or a call
            continue
        parts = _split_top(params)
        if len(parts) != arity:
            continue
        read = _java_params(parts)
        return None if read is None else (ret, read[0], read[1])
    return None


def _java_declared(code: str, cls: str, call: str, first: bool, args: list) \
        -> tuple[tuple[str, list[str], list[str]], list] | None:
    """(what the declaration of one call of the statement's example says, the arguments as that call takes
    them): the constructor for the first call, else a method of the class itself. A call that takes nothing is
    written [] on most problems and [null] on some, and that [null] is the same call of no arguments."""
    for given in ([args, []] if args == [None] else [args]):
        found = _java_constructor(code, cls, len(given)) if first else _java_method(code, cls, call, len(given))
        if found is not None:
            return found, given
    return None


def design_harness(code: str, cls: str, calls: list) -> str | None:
    """The answer's class with a SnCheck class whose main calls it as the statement's own example does: the calls
    in order on one object, the first of them the constructor, each with the values the example holds made into
    the types its declaration names. A call that raises stops the rest, since what the object holds after it is
    no longer the problem's. None where this cannot be done (a class nested in another, a call whose arguments
    or result are of a type the check cannot make), so the card says so rather than running it wrong. A call may
    carry the "shapes" of its arguments and the "result" of the method, as an example's function call does."""
    code = _drop_java_package(code)
    masked = _mask(code)
    if not calls or _java_declares(masked, cls) != "top":   # nested in another class: no name here reaches it
        return None
    body, kinds = [], []
    for i, c in enumerate(calls):
        if not IDENT.fullmatch(c["call"]):
            return None
        read = _java_declared(code, cls, c["call"], i == 0, c.get("args") or [])
        if read is None:
            return None
        (ret, params, _), args = read
        said = list(c.get("shapes") or []) + [None] * len(params)
        nodes = [_java_node(t, said[k] or _java_shape(t)) for k, t in enumerate(params)]
        kept = _java_node(ret, c.get("result") or _java_shape(ret))
        if not (ret == "void" or _java_known(ret) or kept):
            return None
        decl = _java_arguments(params, nodes, args)
        if decl is None:
            return None
        kinds += nodes + [kept]
        hands = ", ".join(f"_a{k}" for k in range(len(params)))
        call = f"_o = new {cls}({hands})" if i == 0 else f"_o.{c['call']}({hands})"
        if ret == "void":
            line = (f'System.setOut(NULL); try {{ {call}; }} finally {{ System.setOut(REAL); }} '
                    f'out("{{\\"i\\":{i},\\"got\\":null}}");')
        else:
            line = (f'Object _r; System.setOut(NULL); try {{ _r = {call}; }} finally {{ System.setOut(REAL); }} '
                    f'out("{{\\"i\\":{i},\\"got\\":" + {_java_shown(kept, c.get("expected"))} + "}}");')
        body.append(f'    try {{ {decl} {line} }}\n'
                    f'    catch (Throwable _e) {{ out("{{\\"i\\":{i},\\"error\\":" + str(String.valueOf(_e))'
                    f' + "}}"); return; }}')
    classes = _java_node_classes([n for n in kinds if n], masked)
    if classes is None:
        return None
    code = _drop_public(code)
    helpers = JAVA_NODE_HELPERS if any(kinds) else ""
    # the judge's own packages, which _leetcode_form does not look for here: a design answer is the class the
    # problem asks for, with no `class Solution` of its own, and it uses java.util without importing it
    return JAVA_JUDGE_HEAD + code + "\n" + classes + JAVA_MAIN % {
        "mark": CASE_MARK, "helpers": helpers, "body": f"    {cls} _o = null;\n" + "\n".join(body),
        "nodes": "    if (snNode(v)) return snJson(v);\n" if helpers else ""}
