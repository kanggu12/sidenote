"""Write panel/code-docs.json: what the panel shows when the pointer rests on a built-in or library function in a code
block of an answer, the way an editor shows a hover (panel/app.js, docTips).

    docker run --rm -i -v "$PWD/runner/code-docs-ko.json:/ko.json:ro" sidenote-runner:local \
        python3 - /ko.json < runner/make_code_docs.py > panel/code-docs.json.new \
        && mv panel/code-docs.json.new panel/code-docs.json

Run in the code runner's image, so the Python entries are that Python's own (the one an answer's code runs on when
`Run` is pressed): each signature from inspect.signature and each text the first paragraph of the object's own
docstring. C++, Java, JavaScript and Go have no runtime here to read docs from; their entries are the most used
functions and types of a coding test, each a signature and one line of what it does, as their references
(cppreference, the Java SE API, MDN, pkg.go.dev) describe them.

Every entry also says in Korean what it does ("ko"), what goes in ("in") and what comes out ("out"), from
runner/code-docs-ko.json, written from the same references: the English line alone was one more thing to translate
before it said anything. The script stops, writing nothing, when an entry it writes has no Korean.

The file is a dict per language: "names" for what is looked up by its full name (a built-in, `module.attr`,
`std::sort`, `Arrays.sort`), "methods" for what is called on a value (`.append(`, `.push_back(`), whose type the panel
cannot know, so one entry stands for the common case.
"""
import inspect
import json
import sys

# --- Python: the built-ins and the standard library a coding test reaches for -----------------------------------
PY_BUILTINS = ["abs", "all", "any", "bin", "bool", "chr", "dict", "divmod", "enumerate", "filter", "float", "format",
               "frozenset", "hash", "hex", "input", "int", "isinstance", "iter", "len", "list", "map", "max", "min",
               "next", "oct", "open", "ord", "pow", "print", "range", "reversed", "round", "set", "sorted", "str",
               "sum", "tuple", "type", "zip", "id", "callable", "getattr", "setattr", "hasattr", "slice", "super",
               "object", "complex", "bytes", "repr", "vars", "dir"]
PY_MODULES = {
    "collections": ["deque", "Counter", "defaultdict", "OrderedDict", "namedtuple"],
    "heapq": ["heappush", "heappop", "heapify", "heappushpop", "heapreplace", "nlargest", "nsmallest", "merge"],
    "bisect": ["bisect_left", "bisect_right", "bisect", "insort", "insort_left", "insort_right"],
    "itertools": ["permutations", "combinations", "combinations_with_replacement", "product", "accumulate", "chain",
                  "groupby", "islice", "count", "cycle", "repeat", "pairwise", "zip_longest", "starmap"],
    "functools": ["lru_cache", "cache", "reduce", "cmp_to_key", "partial"],
    "math": ["gcd", "lcm", "sqrt", "isqrt", "ceil", "floor", "comb", "perm", "factorial", "log", "log2", "log10", "pow",
             "exp", "fabs", "hypot", "prod", "dist", "inf", "pi", "e"],
    "sys": ["setrecursionlimit", "maxsize", "stdin", "stdout", "exit"],
    "re": ["match", "search", "findall", "finditer", "sub", "split", "fullmatch", "compile"],
    "string": ["ascii_lowercase", "ascii_uppercase", "ascii_letters", "digits", "punctuation"],
    "random": ["randint", "random", "choice", "shuffle", "sample"],
    "copy": ["copy", "deepcopy"],
    "operator": ["itemgetter", "attrgetter"],
}
# Methods called on a value: which type's to show (the value's own type is unknown to the panel; the common one).
PY_METHODS = {
    "list": ["append", "extend", "insert", "pop", "remove", "index", "count", "sort", "reverse", "copy", "clear"],
    "dict": ["get", "items", "keys", "values", "setdefault", "update", "popitem"],
    "set": ["add", "discard", "union", "intersection", "difference", "issubset", "issuperset"],
    "str": ["split", "join", "strip", "lstrip", "rstrip", "replace", "find", "rfind", "startswith", "endswith",
            "lower", "upper", "isdigit", "isalpha", "isalnum", "isspace", "zfill", "format", "splitlines", "partition",
            "rjust", "ljust", "center", "title", "swapcase", "encode"],
    "collections.deque": ["appendleft", "popleft", "extendleft", "rotate"],
    "collections.Counter": ["most_common", "elements", "subtract", "total"],
}


def first_paragraph(doc: str | None) -> str:
    """The first paragraph of a docstring, as one line, at most 400 characters."""
    if not doc:
        return ""
    para = inspect.cleandoc(doc).split("\n\n")[0]
    text = " ".join(line.strip() for line in para.splitlines())
    return text if len(text) <= 400 else text[:399] + "…"


def py_entry(name: str, obj) -> dict:
    """{"sig": how it is called, "doc": its docstring's first paragraph} for one Python object."""
    try:
        sig = name + str(inspect.signature(obj))
    except (TypeError, ValueError):
        # No signature to read (a constant, or a callable that keeps it in its docstring's first line)
        doc = inspect.getdoc(obj) or ""
        first = doc.splitlines()[0] if doc else ""
        sig = first if first.startswith(name.split(".")[-1] + "(") else name
        if callable(obj) is False:   # a value: say what it is
            sig = f"{name} = {obj!r}"[:120]
    doc = inspect.getdoc(obj) if callable(obj) or inspect.ismodule(obj) else ""
    if not callable(obj):
        doc = f"{type(obj).__name__} constant."
    text = first_paragraph(doc)
    if text.startswith(name.split(".")[-1] + "(") and "\n" in (inspect.getdoc(obj) or ""):
        text = first_paragraph("\n\n".join((inspect.getdoc(obj) or "").split("\n\n")[1:]))   # signature line, then the text
    return {"sig": sig, "doc": text}


def python() -> dict:
    import builtins
    import importlib
    names, methods = {}, {}
    for n in PY_BUILTINS:
        names[n] = py_entry(n, getattr(builtins, n))
    for mod, attrs in PY_MODULES.items():
        m = importlib.import_module(mod)
        for a in attrs:
            if hasattr(m, a):
                names[f"{mod}.{a}"] = py_entry(f"{mod}.{a}", getattr(m, a))
    try:   # in the runner image (LeetCode's judge has it too)
        import sortedcontainers
        for a in ("SortedList", "SortedDict", "SortedSet"):
            names[f"sortedcontainers.{a}"] = py_entry(f"sortedcontainers.{a}", getattr(sortedcontainers, a))
    except ImportError:
        pass
    for owner, attrs in PY_METHODS.items():
        if "." in owner:
            mod, cls = owner.split(".")
            obj = getattr(importlib.import_module(mod), cls)
        else:
            obj = getattr(builtins, owner)
        for a in attrs:
            if a not in methods and hasattr(obj, a):   # the first type listed wins (list over deque for append)
                e = py_entry(f"{owner}.{a}", getattr(obj, a))
                # the method as it is called on a value: no `self`, and no `/` left standing alone after it
                e["sig"] = (e["sig"].replace("(self, /, ", "(").replace("(self, /)", "()")
                            .replace("(self, ", "(").replace("(self)", "()"))
                methods[a] = e
    return {"names": names, "methods": methods, "version": sys.version.split()[0]}


# --- C++, Java, JavaScript, Go: the most used, one line each ------------------------------------------------------
def d(sig: str, doc: str) -> dict:
    return {"sig": sig, "doc": doc}


CPP = {
    "names": {
        "std::sort": d("void sort(RandomIt first, RandomIt last[, Compare comp])", "Sorts [first, last) in non-descending order (by comp if given). Not stable. O(N log N)."),
        "std::stable_sort": d("void stable_sort(RandomIt first, RandomIt last[, Compare comp])", "Sorts [first, last) keeping the order of equal elements. O(N log N) with extra memory."),
        "std::reverse": d("void reverse(BidirIt first, BidirIt last)", "Reverses the order of the elements in [first, last)."),
        "std::lower_bound": d("ForwardIt lower_bound(ForwardIt first, ForwardIt last, const T& value[, Compare comp])", "First position in the sorted range whose element is not less than value. O(log N)."),
        "std::upper_bound": d("ForwardIt upper_bound(ForwardIt first, ForwardIt last, const T& value[, Compare comp])", "First position in the sorted range whose element is greater than value. O(log N)."),
        "std::binary_search": d("bool binary_search(ForwardIt first, ForwardIt last, const T& value)", "Whether value is in the sorted range. O(log N)."),
        "std::max": d("const T& max(const T& a, const T& b) / T max(initializer_list<T>)", "The greater of the values given."),
        "std::min": d("const T& min(const T& a, const T& b) / T min(initializer_list<T>)", "The smaller of the values given."),
        "std::swap": d("void swap(T& a, T& b)", "Exchanges the values of a and b."),
        "std::accumulate": d("T accumulate(InputIt first, InputIt last, T init[, BinaryOp op])", "Folds [first, last) into init with + (or op). In <numeric>; the type of init decides the sum's type."),
        "std::max_element": d("ForwardIt max_element(ForwardIt first, ForwardIt last[, Compare comp])", "Iterator to the greatest element of [first, last) (the first of equal ones)."),
        "std::min_element": d("ForwardIt min_element(ForwardIt first, ForwardIt last[, Compare comp])", "Iterator to the smallest element of [first, last) (the first of equal ones)."),
        "std::unique": d("ForwardIt unique(ForwardIt first, ForwardIt last)", "Removes consecutive duplicates by moving the kept ones to the front; returns the new end (erase after it)."),
        "std::fill": d("void fill(ForwardIt first, ForwardIt last, const T& value)", "Assigns value to every element of [first, last)."),
        "std::count": d("difference_type count(InputIt first, InputIt last, const T& value)", "How many elements of [first, last) equal value."),
        "std::find": d("InputIt find(InputIt first, InputIt last, const T& value)", "First element equal to value, or last if none."),
        "std::next_permutation": d("bool next_permutation(BidirIt first, BidirIt last)", "Rearranges into the next lexicographic permutation; false (and sorted) after the last one."),
        "std::gcd": d("constexpr M gcd(M m, N n)", "Greatest common divisor of |m| and |n| (C++17, <numeric>)."),
        "std::abs": d("int abs(int n) / double abs(double x)", "Absolute value."),
        "std::to_string": d("string to_string(int value) (and other number types)", "The decimal text of a number."),
        "std::stoi": d("int stoi(const string& str, size_t* pos = nullptr, int base = 10)", "Parses an int from the start of str; throws invalid_argument or out_of_range."),
        "std::getline": d("istream& getline(istream& in, string& str[, char delim])", "Reads characters into str up to the newline (or delim), which is consumed and not stored."),
        "std::vector": d("template<class T> class vector", "Dynamic array: O(1) random access, amortized O(1) push_back at the end."),
        "std::unordered_map": d("template<class Key, class T> class unordered_map", "Hash table from keys to values: average O(1) lookup, insert and erase; no order."),
        "std::map": d("template<class Key, class T> class map", "Balanced tree from keys to values, ordered by key: O(log N) lookup, insert and erase."),
        "std::unordered_set": d("template<class Key> class unordered_set", "Hash set of unique keys: average O(1) insert, erase and count."),
        "std::set": d("template<class Key> class set", "Ordered set of unique keys (balanced tree): O(log N) insert, erase, find, lower_bound."),
        "std::priority_queue": d("template<class T, class Container = vector<T>, class Compare = less<T>> class priority_queue", "Heap: top() is the greatest element by default; push and pop are O(log N). greater<T> makes it a min-heap."),
        "std::queue": d("template<class T> class queue", "FIFO adapter: push at the back, front() and pop() at the front."),
        "std::stack": d("template<class T> class stack", "LIFO adapter: push, top() and pop() at the same end."),
        "std::deque": d("template<class T> class deque", "Double-ended queue: O(1) push and pop at both ends, random access."),
        "std::pair": d("template<class T1, class T2> struct pair", "Two values, .first and .second; compared lexicographically."),
        "std::string": d("class string", "A sequence of chars: size(), substr(), find(), += and comparison."),
        "std::cin": d("istream cin", "Standard input stream; >> skips whitespace and reads one value."),
        "std::cout": d("ostream cout", "Standard output stream; << writes a value. Prefer '\\n' over endl, which flushes."),
    },
    "methods": {
        "push_back": d("void push_back(const T& value)", "Appends value at the end (vector, deque, string). Amortized O(1)."),
        "emplace_back": d("T& emplace_back(Args&&... args)", "Constructs an element in place at the end from args."),
        "pop_back": d("void pop_back()", "Removes the last element (undefined on an empty container)."),
        "size": d("size_type size() const", "Number of elements (unsigned: size() - 1 on an empty container wraps around)."),
        "empty": d("bool empty() const", "Whether the container has no elements."),
        "begin": d("iterator begin()", "Iterator to the first element."),
        "end": d("iterator end()", "Iterator past the last element."),
        "back": d("T& back()", "The last element."),
        "front": d("T& front()", "The first element."),
        "insert": d("insert(value) / insert(pos, value)", "Adds an element (into a set or map: only when the key is not there yet)."),
        "erase": d("erase(key) / erase(iterator)", "Removes the element(s) with that key, or at that position."),
        "count": d("size_type count(const Key& key) const", "How many elements have that key (0 or 1 in a set or map)."),
        "find": d("iterator find(const Key& key) / size_t find(const string& s)", "Iterator to the key, or end() when absent; on a string, the position or npos."),
        "substr": d("string substr(size_t pos = 0, size_t count = npos) const", "A copy of count chars starting at pos."),
        "push": d("void push(const T& value)", "Adds value (queue: at the back, stack: on top, priority_queue: into the heap)."),
        "pop": d("void pop()", "Removes the front (queue), the top (stack) or the greatest (priority_queue); returns nothing."),
        "top": d("const T& top() const", "The top element (stack) or the greatest one (priority_queue)."),
        "resize": d("void resize(size_type count[, const T& value])", "Changes the size, filling new elements with value."),
        "reserve": d("void reserve(size_type new_cap)", "Allocates room for new_cap elements so pushes do not reallocate."),
        "clear": d("void clear()", "Removes every element."),
        "length": d("size_t length() const", "Number of chars in the string (same as size())."),
    },
}
CPP["names"].update({k[5:]: v for k, v in list(CPP["names"].items())})   # with `using namespace std;` too

JAVA = {
    "names": {
        "Arrays.sort": d("static void sort(int[] a) / sort(T[] a, Comparator<? super T> c)", "Sorts the array in ascending order (primitives: dual-pivot quicksort; objects: stable merge sort)."),
        "Arrays.fill": d("static void fill(int[] a, int val)", "Assigns val to every element of the array."),
        "Arrays.asList": d("static <T> List<T> asList(T... a)", "A fixed-size list backed by the array."),
        "Arrays.toString": d("static String toString(int[] a)", "The array as text, like [1, 2, 3]."),
        "Arrays.stream": d("static IntStream stream(int[] array)", "A stream over the array."),
        "Collections.sort": d("static <T> void sort(List<T> list[, Comparator<? super T> c])", "Sorts the list in place (stable)."),
        "Collections.reverse": d("static void reverse(List<?> list)", "Reverses the list in place."),
        "Collections.max": d("static <T> T max(Collection<? extends T> coll)", "The greatest element."),
        "Collections.min": d("static <T> T min(Collection<? extends T> coll)", "The smallest element."),
        "Math.max": d("static int max(int a, int b)", "The greater of two values."),
        "Math.min": d("static int min(int a, int b)", "The smaller of two values."),
        "Math.abs": d("static int abs(int a)", "Absolute value (Math.abs(Integer.MIN_VALUE) stays negative)."),
        "Math.pow": d("static double pow(double a, double b)", "a raised to b, as a double."),
        "Math.sqrt": d("static double sqrt(double a)", "Square root, as a double."),
        "Integer.parseInt": d("static int parseInt(String s)", "Parses a decimal int; NumberFormatException when it is not one."),
        "Integer.MAX_VALUE": d("static final int MAX_VALUE = 2147483647", "The largest int (2^31 - 1)."),
        "Integer.MIN_VALUE": d("static final int MIN_VALUE = -2147483648", "The smallest int (-2^31)."),
        "String.valueOf": d("static String valueOf(Object obj)", "The text of a value."),
        "System.out.println": d("void println(Object x)", "Writes x and a line break to standard output."),
        "ArrayList": d("class ArrayList<E> implements List<E>", "Resizable array list: O(1) get(i), amortized O(1) add at the end."),
        "HashMap": d("class HashMap<K, V> implements Map<K, V>", "Hash table map: average O(1) get, put and containsKey; no order."),
        "HashSet": d("class HashSet<E> implements Set<E>", "Hash set: average O(1) add, remove and contains."),
        "TreeMap": d("class TreeMap<K, V> implements NavigableMap<K, V>", "Red-black tree map ordered by key: O(log N); floorKey, ceilingKey."),
        "TreeSet": d("class TreeSet<E> implements NavigableSet<E>", "Ordered set (red-black tree): O(log N); floor, ceiling, first, last."),
        "PriorityQueue": d("class PriorityQueue<E>", "Binary heap, smallest first by default (pass Comparator.reverseOrder() for largest); offer and poll O(log N)."),
        "ArrayDeque": d("class ArrayDeque<E> implements Deque<E>", "Resizable double-ended queue: use as a stack (push/pop) or a queue (offer/poll)."),
        "LinkedList": d("class LinkedList<E> implements List<E>, Deque<E>", "Doubly linked list; O(1) at both ends, O(N) get(i)."),
        "StringBuilder": d("class StringBuilder", "Mutable text: append is amortized O(1); toString() at the end."),
        "Scanner": d("class Scanner", "Reads tokens from input (nextInt, next, nextLine); slow for large input (use BufferedReader)."),
        "BufferedReader": d("class BufferedReader", "Buffered text input; readLine() returns a line or null at the end."),
    },
    "methods": {
        "add": d("boolean add(E e)", "Adds e (list: at the end; set: only when absent, returning whether it was added)."),
        "get": d("E get(int index) / V get(Object key)", "The element at index (list) or the value for key, or null (map)."),
        "put": d("V put(K key, V value)", "Maps key to value; returns the previous value or null."),
        "getOrDefault": d("V getOrDefault(Object key, V defaultValue)", "The value for key, or defaultValue when absent."),
        "containsKey": d("boolean containsKey(Object key)", "Whether the map has key."),
        "contains": d("boolean contains(Object o)", "Whether the collection has o."),
        "size": d("int size()", "Number of elements."),
        "isEmpty": d("boolean isEmpty()", "Whether there are no elements."),
        "remove": d("E remove(int index) / boolean remove(Object o)", "Removes by position (list, int argument) or by value (careful with Integer lists)."),
        "offer": d("boolean offer(E e)", "Adds e to the queue."),
        "poll": d("E poll()", "Removes and returns the head of the queue, or null when empty."),
        "peek": d("E peek()", "The head of the queue without removing it, or null when empty."),
        "push": d("void push(E e)", "Pushes e onto the stack (the deque's front)."),
        "pop": d("E pop()", "Removes and returns the top of the stack."),
        "charAt": d("char charAt(int index)", "The char at index."),
        "length": d("int length()", "Number of chars."),
        "substring": d("String substring(int beginIndex[, int endIndex])", "The chars from beginIndex up to endIndex (exclusive)."),
        "append": d("StringBuilder append(Object obj)", "Appends the text of obj."),
        "toCharArray": d("char[] toCharArray()", "The string's chars as a new array."),
        "equals": d("boolean equals(Object o)", "Value equality (== compares references for objects such as String)."),
        "merge": d("V merge(K key, V value, BiFunction remapping)", "Puts value, or combines it with the existing one (counting: map.merge(k, 1, Integer::sum))."),
    },
}

JS = {
    "names": {
        "Math.max": d("Math.max(...values)", "The largest of the numbers (-Infinity with none)."),
        "Math.min": d("Math.min(...values)", "The smallest of the numbers (Infinity with none)."),
        "Math.floor": d("Math.floor(x)", "The largest integer <= x."),
        "Math.ceil": d("Math.ceil(x)", "The smallest integer >= x."),
        "Math.abs": d("Math.abs(x)", "Absolute value."),
        "Math.sqrt": d("Math.sqrt(x)", "Square root."),
        "Math.trunc": d("Math.trunc(x)", "x without its fractional part."),
        "parseInt": d("parseInt(string, radix)", "Parses an integer from the start of string; NaN when it starts with none. Give the radix."),
        "Number.parseInt": d("Number.parseInt(string, radix)", "Same as the global parseInt."),
        "Number.MAX_SAFE_INTEGER": d("Number.MAX_SAFE_INTEGER = 2**53 - 1", "The largest integer a Number holds exactly (use BigInt past it)."),
        "Array.from": d("Array.from(arrayLike[, mapFn])", "A new array from an iterable or array-like, mapped by mapFn ({length: n} makes n slots)."),
        "Array.isArray": d("Array.isArray(value)", "Whether value is an array."),
        "Object.keys": d("Object.keys(obj)", "The object's own enumerable property names, as strings."),
        "Object.entries": d("Object.entries(obj)", "The object's own [key, value] pairs."),
        "JSON.stringify": d("JSON.stringify(value)", "The value as JSON text."),
        "JSON.parse": d("JSON.parse(text)", "The value the JSON text describes."),
        "console.log": d("console.log(...data)", "Writes the values to standard output, separated by spaces."),
        "Map": d("new Map([iterable])", "Key-value map keeping insertion order; keys of any type; get, set, has, delete, size."),
        "Set": d("new Set([iterable])", "Set of unique values in insertion order; add, has, delete, size."),
        "BigInt": d("BigInt(value)", "An integer of any size (literal: 123n); not mixed with Number in arithmetic."),
    },
    "methods": {
        "push": d("arr.push(...items)", "Appends items at the end; returns the new length."),
        "pop": d("arr.pop()", "Removes and returns the last element."),
        "shift": d("arr.shift()", "Removes and returns the first element (O(n): use an index for a queue)."),
        "unshift": d("arr.unshift(...items)", "Inserts items at the start (O(n))."),
        "map": d("arr.map(fn)", "A new array of fn(element, index)."),
        "filter": d("arr.filter(fn)", "A new array of the elements fn returns true for."),
        "reduce": d("arr.reduce(fn, initial)", "Folds the array with fn(accumulator, element), starting from initial."),
        "sort": d("arr.sort([compareFn])", "Sorts in place; WITHOUT compareFn numbers sort as strings (use (a, b) => a - b)."),
        "slice": d("arr.slice(start, end)", "A copy of the elements from start up to end (exclusive)."),
        "splice": d("arr.splice(start, deleteCount, ...items)", "Removes and/or inserts in place; returns the removed elements."),
        "indexOf": d("arr.indexOf(value)", "First index of value, or -1."),
        "includes": d("arr.includes(value)", "Whether value is there (NaN-aware)."),
        "join": d("arr.join(separator)", "The elements as text, joined by separator (',' by default)."),
        "split": d("str.split(separator)", "The string cut at each separator, as an array."),
        "forEach": d("arr.forEach(fn)", "Calls fn(element, index) for each element; returns undefined."),
        "fill": d("arr.fill(value, start, end)", "Assigns value in place (new Array(n).fill(0))."),
        "get": d("map.get(key)", "The value for key, or undefined."),
        "set": d("map.set(key, value)", "Maps key to value; returns the map."),
        "has": d("map.has(key) / set.has(value)", "Whether it is there."),
        "add": d("set.add(value)", "Adds value; returns the set."),
        "charCodeAt": d("str.charCodeAt(index)", "The UTF-16 code unit at index."),
        "padStart": d("str.padStart(targetLength, padString)", "The string padded at the start to targetLength."),
    },
}
JS["names"].update({"TypeScript": d("TypeScript", "JavaScript with types; the types are stripped before running.")})

GO = {
    "names": {
        "len": d("func len(v Type) int", "Length of a string (bytes), slice, array, map or channel."),
        "cap": d("func cap(v Type) int", "Capacity of a slice, array or channel."),
        "append": d("func append(slice []Type, elems ...Type) []Type", "The slice with elems added; may reallocate, so keep the result (s = append(s, x))."),
        "make": d("func make(t Type, size ...IntegerType) Type", "A new slice, map or channel (make([]int, n), make(map[string]int))."),
        "copy": d("func copy(dst, src []Type) int", "Copies min(len(dst), len(src)) elements; returns that number."),
        "delete": d("func delete(m map[Type]Type1, key Type)", "Removes key from the map (no-op when absent)."),
        "min": d("func min(x T, y ...T) T", "The smallest argument (Go 1.21+)."),
        "max": d("func max(x T, y ...T) T", "The largest argument (Go 1.21+)."),
        "fmt.Println": d("func Println(a ...any) (n int, err error)", "Writes the values separated by spaces and a newline."),
        "fmt.Printf": d("func Printf(format string, a ...any) (n int, err error)", "Writes the values formatted by format."),
        "fmt.Scan": d("func Scan(a ...any) (n int, err error)", "Reads space-separated values into the pointers (slow for large input: use bufio)."),
        "fmt.Sprintf": d("func Sprintf(format string, a ...any) string", "The values formatted by format, as a string."),
        "sort.Ints": d("func Ints(x []int)", "Sorts the ints in ascending order."),
        "sort.Strings": d("func Strings(x []string)", "Sorts the strings in ascending order."),
        "sort.Slice": d("func Slice(x any, less func(i, j int) bool)", "Sorts the slice by less (not stable; sort.SliceStable keeps equal order)."),
        "sort.Search": d("func Search(n int, f func(int) bool) int", "Smallest i in [0, n) with f(i) true (f must be false then true), or n."),
        "strings.Split": d("func Split(s, sep string) []string", "s cut at each sep."),
        "strings.Join": d("func Join(elems []string, sep string) string", "The strings joined with sep."),
        "strings.Contains": d("func Contains(s, substr string) bool", "Whether substr is in s."),
        "strings.Fields": d("func Fields(s string) []string", "s cut at runs of whitespace."),
        "strings.Builder": d("type Builder struct", "Builds a string with WriteString / WriteByte; String() at the end."),
        "strconv.Itoa": d("func Itoa(i int) string", "The decimal text of i."),
        "strconv.Atoi": d("func Atoi(s string) (int, error)", "Parses a decimal int."),
        "bufio.NewReader": d("func NewReader(rd io.Reader) *Reader", "Buffered reader (fast input with os.Stdin)."),
        "bufio.NewScanner": d("func NewScanner(r io.Reader) *Scanner", "Reads input token by token or line by line (raise Buffer for long lines)."),
        "math.MaxInt": d("const MaxInt", "The largest int."),
        "math.Abs": d("func Abs(x float64) float64", "Absolute value of a float64."),
        "container/heap": d("package heap", "Heap operations over a type that implements heap.Interface (Len, Less, Swap, Push, Pop)."),
        "heap.Push": d("func Push(h Interface, x any)", "Pushes x onto the heap. O(log n)."),
        "heap.Pop": d("func Pop(h Interface) any", "Removes and returns the minimum (by Less). O(log n)."),
        "heap.Init": d("func Init(h Interface)", "Establishes the heap order. O(n)."),
    },
    "methods": {
        "WriteString": d("func (b *Builder) WriteString(s string) (int, error)", "Appends s."),
        "String": d("func (b *Builder) String() string", "The accumulated string."),
    },
}

# --- the Korean: what it does, what goes in, what comes out ---------------------------------------------------------
KO_FIELDS = ("ko", "in", "out")


def add_korean(out: dict, path: str) -> list[str]:
    """Put each entry's Korean into it, from the table at `path` ({language: {"names"|"methods": {key: {ko, in,
    out}}}}). Returns the entries left without it, as "language section key"."""
    with open(path, encoding="utf-8") as f:
        table = json.load(f)
    missing = []
    for lang, docs in out.items():
        if lang == "typescript":      # the very same entries as JavaScript's (one dict), filled with them
            continue
        for section in ("names", "methods"):
            ko = table.get(lang, {}).get(section, {})
            for key, entry in docs.get(section, {}).items():
                k = ko.get(key) or {}
                if not all(k.get(f) for f in KO_FIELDS):
                    missing.append(f"{lang} {section} {key}")
                    continue
                entry.update({f: k[f] for f in KO_FIELDS})
            # Korean for an entry not written here: a Python attribute this Python does not have, or a renamed key
            for key in sorted(set(ko) - set(docs.get(section, {}))):
                print(f"code-docs: Korean for {lang} {section} {key!r} has no entry here", file=sys.stderr)
    return missing


out = {"python": python(), "cpp": CPP, "java": JAVA, "javascript": JS, "go": GO}
out["typescript"] = JS
missing = add_korean(out, sys.argv[1]) if len(sys.argv) > 1 else ["all (no Korean table given)"]
if missing:
    sys.exit(f"code-docs: no Korean for {len(missing)} entries: " + ", ".join(missing[:12]))
json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))
