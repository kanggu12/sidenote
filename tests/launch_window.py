"""The desktop shortcut's windows (client/launch.pyw): the start's steps, and the note that takes the place of a message
box when a start fails or one is already going.

    .venv/bin/python tests/launch_window.py [path to launch.pyw]

They are made as the tray icon's menu is (TRAY_MENU in client/capture.py), and the two had drifted apart: the start's
window kept older colours, spoke English only beside a menu in Korean, and a failure came in Windows' own message box.
Checked here, with no Windows: the colours are the menu's, every word the windows say has its Korean, the lines a note
takes are counted as a Text widget wraps them, and, where Tk and a virtual display (Xvfb) are at hand, both windows
are drawn in both languages: the start at each step, a failure that keeps its end in view and closes with Esc, Enter
or its key, and a note that goes by itself.
"""
import ast
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))   # the repository: this file is in tests/
LAUNCH = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "client", "launch.pyw")
CAPTURE = os.path.join(ROOT, "client", "capture.py")
PASS, FAIL = [], []


def check(name, cond, got=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {got}" if got and not cond else ""))


def load(lang):
    """client/launch.pyw as a module, in a language: it reads SIDENOTE_LANG when it is loaded."""
    os.environ["SIDENOTE_LANG"] = lang
    loader = importlib.machinery.SourceFileLoader(f"launch_{lang}", LAUNCH)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


en, ko = load("en"), load("ko")

# The menu's colours, read out of TRAY_MENU: the windows wear the same ones, so the two cannot drift apart again
menu = open(CAPTURE, encoding="utf-8").read()
names = re.search(r'^BG, EDGE, TOP, INK, INK2, MUTED, DIM, HOVER, MARK, RULE = \(([^)]*)\)', menu, re.M)
bad = re.search(r'^OK, LIT, BAD, TRACK_ON, TRACK_OFF, KNOB = (.*)$', menu, re.M)
colour = dict(zip(("BG", "EDGE", "TOP", "INK", "INK2", "MUTED", "DIM", "HOVER", "MARK", "RULE"), re.findall(r'"(#[0-9a-f]{6})"', names.group(1))))
colour["BAD"] = re.findall(r'"(#[0-9a-f]{6})"', bad.group(1))[2]
G = en.Glass
mine = {"BG": G.BG, "EDGE": G.EDGE, "TOP": G.TOP, "INK": G.INK, "INK2": G.INK2, "MUTED": G.MUTED, "HOVER": G.HOVER, "MARK": G.MARK,
        "RULE": G.TRACK, "BAD": G.BAD}
check("the windows wear the tray menu's colours, the panel's dark Classic", all(colour[k] == v for k, v in mine.items()),
      str({k: (colour[k], v) for k, v in mine.items() if colour[k] != v}))
check("...and its fonts: Segoe UI, and Malgun Gothic for Korean", (G.SANS, G.HANGUL) == ("Segoe UI", "Malgun Gothic")
      and '"Segoe UI", "Malgun Gothic"' in menu)

# Every word the windows and boxes say has its Korean: each literal handed to t() is a key of KO
tree = ast.parse(open(LAUNCH, encoding="utf-8").read())
said = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "t" and node.args:
        try:
            said.add(ast.literal_eval(node.args[0]))
        except ValueError:
            pass
missing = sorted(text for text in said if text not in ko.KO)
check(f"every one of the {len(said)} texts it says has its Korean", len(said) > 15 and not missing, str(missing[:5]))
hangul = re.compile(r"[가-힣]")
words = lambda m: [*m.STEPS, m.SAY_WSL, m.SAY_SERVER, m.SAY_CAPTURE, m.SAY_DONE, m.FAILED, m.BUSY, m.BUSY_TEXT, m.t("Close"), m.t("{n}s", n=3)]
check("in Korean the start's window and the notes speak Korean", all(hangul.search(w) for w in words(ko)) and ko.t("{n}s", n=3) == "3초",
      str([w for w in words(ko) if not hangul.search(w)]))
check("...and in English no Korean at all", not any(hangul.search(w) for w in words(en)), str([w for w in words(en) if hangul.search(w)]))
check("the notes' titles are short phrases, as the panel's are, with no name the window already wears",
      all(len(w) <= 24 and "Sidenote" not in w for w in (en.FAILED, en.BUSY, ko.FAILED, ko.BUSY)), f"{en.FAILED!r} {ko.FAILED!r}")

# The lines a note takes, counted as a Text widget wraps: at words, and a word wider than the line where it runs out
width_of = len                                       # one unit a character
check("a line that fits is one line", en.wrapped("aaaa bbbb", width_of, 10) == 1)
check("words go to the next line whole", en.wrapped("aaaa bbbb cccc", width_of, 10) == 2)
check("a word wider than a line is broken where it runs out", en.wrapped("x" * 25, width_of, 10) == 3)
check("each line of the text starts a line, an empty one too", en.wrapped("a\n\nb", width_of, 10) == 3)

# Drawn, where Tk and a virtual display are at hand (not on CI)
DRAW = r"""
import gc, importlib.machinery, importlib.util, json, sys, tkinter
loader = importlib.machinery.SourceFileLoader("launch", sys.argv[1])
spec = importlib.util.spec_from_loader("launch", loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)
out = {}
w = m.Starting(tkinter)
for step, say, finished in ((0, m.SAY_WSL, False), (0, m.SAY_SERVER, False), (1, m.SAY_CAPTURE, False), (2, m.SAY_DONE, True)):
    w.show(step, say, finished); w.draw(); w.root.update()
    texts = [w.c.itemcget(i, "text") for i in w.c.find_all() if w.c.type(i) == "text"]
    out.setdefault("start", []).append(texts)
out["start_bg"] = w.c.cget("bg")
w.close()                       # as the start's failure goes: its window closed, and then the note made
del w; gc.collect()
lines = "\n".join(f"line {i}: the launcher said this" for i in range(40))
n = m.Notice(tkinter, m.FAILED, lines, failed=True); n.root.update()
body = [n.root.nametowidget(n.c.itemcget(i, "window")) for i in n.c.find_all() if n.c.type(i) == "window"][0]
out["failed"] = {"title": [n.c.itemcget(i, "text") for i in n.c.find_all() if n.c.type(i) == "text"],
                 "text": body.get("1.0", "end -1c") == lines, "end_seen": body.bbox("end -1c") is not None,
                 "start_seen": body.bbox("1.0") is not None, "height": n.root.winfo_height(), "screen": n.root.winfo_screenheight(),
                 "state": str(body.cget("state")), "dot": [n.tone]}
n.root.event_generate("<Escape>")
try:
    n.root.update(); out["failed"]["closed_by_esc"] = not n.root.winfo_exists()
except tkinter.TclError:
    out["failed"]["closed_by_esc"] = True
del n, body; gc.collect()
n = m.Notice(tkinter, m.FAILED, "the reason", failed=True); n.root.update()
x0, y0, x1, y1 = n.c.coords(n.c.find_withtag("close-box")[0])
n.c.event_generate("<Motion>", x=int((x0 + x1) / 2), y=int((y0 + y1) / 2)); n.c.event_generate("<Button-1>", x=int((x0 + x1) / 2), y=int((y0 + y1) / 2))
try:
    n.root.update(); out["closed_by_key"] = not n.root.winfo_exists()
except tkinter.TclError:
    out["closed_by_key"] = True
del n; gc.collect()
m.NOTE_HOLD = 300
n = m.Notice(tkinter, m.BUSY, m.BUSY_TEXT, failed=False)
out["busy_dot"] = [n.tone]
n.root.after(1500, lambda: (out.__setitem__("note_stayed", True), n.root.destroy()))
n.root.mainloop()
out.setdefault("note_stayed", False)
print(json.dumps(out, ensure_ascii=False))
"""


def drawn(lang):
    read, write = os.pipe()
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(write), "-screen", "0", "1600x1000x24", "-nolisten", "tcp"], pass_fds=(write,),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write)
    try:
        display = os.read(read, 16).decode().strip()          # the display Xvfb found free, said once it is up
        got = subprocess.run([sys.executable, "-c", DRAW, LAUNCH], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "DISPLAY": f":{display}", "SIDENOTE_LANG": lang})
        return got
    finally:
        os.close(read)
        xvfb.kill()
        xvfb.wait()


try:
    import tkinter  # noqa: F401
    have_tk = True
except Exception:
    have_tk = False
if not (have_tk and shutil.which("Xvfb")):
    print("  (the windows are not drawn here: no Tk or no Xvfb)")
else:
    for lang, m in (("en", en), ("ko", ko)):
        got = drawn(lang)
        try:
            out = json.loads(got.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            check(f"the windows draw, in {lang}", False, f"{got.returncode} {got.stderr[-500:]}")
            continue
        steps = out["start"]
        check(f"the start's window draws every step, in {lang}: its steps and what it is doing",
              all(all(s in texts for s in m.STEPS) for texts in steps) and steps[0].count(m.SAY_WSL) == 1
              and steps[3].count(m.SAY_DONE) == 1 and out["start_bg"] == G.BG, json.dumps(steps[0], ensure_ascii=False))
        f = out["failed"]
        check(f"a failure shows its title by a red mark and the launcher's lines, read only, in {lang}",
              m.FAILED in f["title"] and f["dot"] == [G.BAD] and f["text"] and f["state"] == "disabled", json.dumps(f, ensure_ascii=False))
        check(f"...with the end in view and the start a scroll away, in a window shorter than the screen, in {lang}",
              f["end_seen"] and not f["start_seen"] and f["height"] < f["screen"], json.dumps(f, ensure_ascii=False))
        check(f"...and Esc or its Close key takes it away, in {lang}", f["closed_by_esc"] and out["closed_by_key"], json.dumps(out, ensure_ascii=False)[:300])
        check(f"a note wears the grey mark and goes by itself, in {lang}", out["busy_dot"] == [G.MUTED] and not out["note_stayed"],
              json.dumps({k: out[k] for k in ("busy_dot", "note_stayed")}))

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
