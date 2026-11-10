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
names = re.search(r'^BG, EDGE, TOP, INK, INK2, MUTED, DIM, HOVER, MARK = \(([^)]*)\)', menu, re.M)
bad = re.search(r'^OK, LIT, BAD, TRACK_ON, TRACK_OFF, KNOB = (.*)$', menu, re.M)
colour = dict(zip(("BG", "EDGE", "TOP", "INK", "INK2", "MUTED", "DIM", "HOVER", "MARK"), re.findall(r'"(#[0-9a-f]{6})"', names.group(1))))
colour["BAD"] = re.findall(r'"(#[0-9a-f]{6})"', bad.group(1))[2]
G = en.Glass
mine = {"BG": G.BG, "EDGE": G.EDGE, "TOP": G.TOP, "INK": G.INK, "INK2": G.INK2, "MUTED": G.MUTED, "HOVER": G.HOVER, "MARK": G.MARK,
        "BAD": G.BAD}
check("the windows wear the tray menu's colours, the panel's dark Classic", all(colour[k] == v for k, v in mine.items()),
      str({k: (colour[k], v) for k, v in mine.items() if colour[k] != v}))
# ...and its glass and keys: the same blur, tint and colour, the same key faces (the menu's words are measured on this glass)
glass = dict(re.findall(r'^(BLUR, TINT, VIVID|KEY_FACE, KEY_LIT) = (.*)$', menu, re.M))
check("...and its frosted glass and key faces, the same values", glass.get("BLUR, TINT, VIVID") == f"{G.BLUR}, {G.TINT}, {G.VIVID}"
      and glass.get("KEY_FACE, KEY_LIT") == f"{G.KEY_FACE}, {G.KEY_LIT}", str(glass))
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
words = lambda m: [*m.STEPS, m.t("Starting"), m.t("Running"), m.FAILED, m.BUSY, m.BUSY_TEXT, m.t("Close"), m.t("{n}s", n=3)]
check("in Korean the start's window and the notes speak Korean", all(hangul.search(w) for w in words(ko)) and ko.t("{n}s", n=3) == "3초",
      str([w for w in words(ko) if not hangul.search(w)]))
check("...and in English no Korean at all", not any(hangul.search(w) for w in words(en)), str([w for w in words(en) if hangul.search(w)]))
check("the time a start has taken reads at a glance: seconds, and minutes and seconds past a minute",
      (en.clock(12), en.clock(59), en.clock(74), en.clock(600), ko.clock(12)) == ("12s", "59s", "1:14", "10:00", "12초"),
      str((en.clock(12), en.clock(74), ko.clock(12))))
check("the notes' titles are short phrases, as the panel's are, with no name the window already wears",
      all(len(w) <= 24 and "Sidenote" not in w for w in (en.FAILED, en.BUSY, ko.FAILED, ko.BUSY)), f"{en.FAILED!r} {ko.FAILED!r}")

# The lines a note takes, counted as a Text widget wraps: at words, and a word wider than the line where it runs out
width_of = len                                       # one unit a character
check("a line that fits is one line", en.wrapped("aaaa bbbb", width_of, 10) == 1)
check("words go to the next line whole", en.wrapped("aaaa bbbb cccc", width_of, 10) == 2)
check("a word wider than a line is broken where it runs out", en.wrapped("x" * 25, width_of, 10) == 3)
check("each line of the text starts a line, an empty one too", en.wrapped("a\n\nb", width_of, 10) == 3)
# The note wraps its lines itself, so a long line keeps its end, where the reason is; Windows' own box still cuts it
long_line = "error: " + "x" * 300 + " forbidden by its access permissions"
check("a failure keeps a long line of the launcher's whole: its end is the reason",
      en.last_lines(long_line)[0] == [long_line], str(en.last_lines(long_line)[0])[:120])
check("...and only Windows' own box cuts it, at its width", hasattr(en, "cut") and len(en.cut(long_line, en.WIDTH)) == en.WIDTH
      and en.cut(long_line, en.WIDTH).endswith("…"))
# The launcher's marks: on its last lines, each ended where the launcher ended it. A value printed on the way that holds a
# carriage return (a model's name in a status, which a restored backup could set) is no mark, though splitlines() made it a line
honest = b"Starting\nSIDENOTE-LANG\ten\r\nSIDENOTE-START\tC:\\x\\client\\capture.py\t--server\tws://127.0.0.1:8777/ingest\n"
forged = b"Model: x\rSIDENOTE-START\t-c\timport os\n" + b"line\n" * 2
check("the launcher's marks are read from its last lines", en.marked(honest, en.START_MARK) == ["C:\\x\\client\\capture.py", "--server", "ws://127.0.0.1:8777/ingest"]
      and en.marked(honest, en.LANG_MARK) == ["en"], str(en.marked(honest, en.START_MARK)))
check("...and a carriage return inside a printed value makes no mark", en.marked(forged, en.START_MARK) is None, str(en.marked(forged, en.START_MARK)))
check("...nor does a mark far above the end", en.marked(b"SIDENOTE-OPEN\thttp://x\n" + b"later\n" * 10, en.OPEN_MARK) is None)

# Drawn, where Tk and a virtual display are at hand (not on CI)
DRAW = r"""
import gc, importlib.machinery, importlib.util, json, sys, tkinter
loader = importlib.machinery.SourceFileLoader("launch", sys.argv[1])
spec = importlib.util.spec_from_loader("launch", loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)
out = {}
# The glass as drawn (Glass._art), kept as a picture to measure: what each PhotoImage is made from
from PIL import ImageTk
pictures, photo = [], ImageTk.PhotoImage
ImageTk.PhotoImage = lambda img, master=None: (pictures.append(img), photo(img, master=master))[1]
lum = lambda c: sum(k * ((v / 255) / 12.92 if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4) for k, v in zip((0.2126, 0.7152, 0.0722), c))


def glass_over(colour):
    # A start's window over a desk of one colour (a window over the whole screen), at its first step: how much the least of
    # its words stands out on the lightest of what is behind it, the glass's mean light and colour, and the window's own
    # see-through. The words are the canvas's (the release, the pill, the times and names): the logo is in the picture
    desk = tkinter.Tk(); desk.overrideredirect(True); desk.geometry(f"{desk.winfo_screenwidth()}x{desk.winfo_screenheight()}+0+0")
    desk.configure(bg=colour); desk.update()   # a Tk of its own: a Toplevel made the default root, and a note's mainloop never ended
    g = m.Starting(tkinter); g.show(0, False); g.draw()
    import time as clock_
    until = clock_.monotonic() + 0.5           # in as a notification comes: up and from clear, done in a fifth of a second
    while clock_.monotonic() < until:
        g.root.update(); clock_.sleep(0.02)
    if g.tick is not None:                     # held still: the next frame would write the time again
        g.root.after_cancel(g.tick); g.tick = None
    g.c.itemconfigure(g.seconds, text=m.clock(74))
    words = [i for i in g.c.find_all() if g.c.type(i) == "text" and g.c.itemcget(i, "text")]
    pic = [x for x in pictures if x.size == (g.width, g.height)][-1].convert("RGB")   # the window's own picture
    worst = (99.0, "")
    for i in words:
        x0, y0, x1, y1 = g.c.bbox(i)
        behind = sorted((pic.getpixel((x, y)) for x in range(x0, x1) for y in range(y0, y1)), key=lum)
        light = lum(behind[len(behind) // 2])          # the lightest of the darker half: the glass between the letters
        word = lum(tuple(int(g.c.itemcget(i, "fill")[k:k + 2], 16) for k in (1, 3, 5)))
        worst = min(worst, (round((max(word, light) + 0.05) / (min(word, light) + 0.05), 2), g.c.itemcget(i, "text")))
    small = pic.resize((32, 16)).getdata()
    mean = sum(map(lum, small)) / (32 * 16)
    hue = [round(sum(px[k] for px in small) / (32 * 16)) for k in range(3)]   # the glass's mean colour
    seen = {"contrast": worst[0], "least": worst[1], "light": round(mean, 4), "colour": hue, "frosted": g.behind is not None,
            "alpha": float(g.root.attributes("-alpha")), "words": [g.c.itemcget(i, "text") for i in words],
            "logo": g.logo_at is not None}
    g.close(); desk.destroy()
    return seen


out["over_white"], out["over_dark"], out["over_blue"] = glass_over("#ffffff"), glass_over("#0d0e10"), glass_over("#2f6fde")
w = m.Starting(tkinter)
w.show(0, False); w.draw(); w.root.update()
out["start_place"] = [w.root.winfo_y(), w.root.winfo_height()]
# What goes on in detail: the launcher's last line as it is written, its colour codes out and its own markers left out
import tempfile
said = tempfile.TemporaryFile()
said.write("Starting the server\n\x1b[32m Container sidenote  Started\x1b[0m\r\nSIDENOTE-LANG\ten\n".encode()); said.flush()
m.LIVE["read"] = m.reader(said)              # read as the window reads it while the launcher writes
w.read_at = 0.0; w.draw()
out["detail"] = w.c.itemcget(w.detail, "text")
said.write(("x" * 300 + " the end").encode()); said.flush()
w.read_at = 0.0; w.draw()
out["detail_long"] = w.c.itemcget(w.detail, "text")
m.LIVE["read"] = None; said.close()
# The part under way: drawn again each frame as a patch of the picture, nothing filled before it is as long as it is
# tall (a sliver sat at the corner as a dot); a few seconds on, filled part of the way and no further than most of it
out["moving_first"] = {"patch": w.bar_patch is not None, "short": w.part * max(0.0, w.fill - w.step) < 6 * w.scale,
                       "breath": w.light_patch is not None}
w.since -= 6.0
for _ in range(120):
    w.draw()
out["moving_later"] = {"share": round(w.fill - w.step, 2)}
import time
for step, finished in ((0, False), (1, False), (2, True)):
    w.show(step, finished)
    if step == 1:                              # the server took 3 s, and the capture has been starting 2 s
        now = time.monotonic()
        w.started, w.began = now - 5.0, [now - 5.0, now - 2.0]
    w.draw(); w.root.update()
    # the window's own words: the launcher's line under the bar is the launcher's (checked above)
    texts = [w.c.itemcget(i, "text") for i in w.c.find_all() if w.c.type(i) == "text" and i != w.detail]
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
# A failure the start's window saw: the steps with the one it failed at, and the times
m.FAILED_AT[0] = (1, [3.1, 9.4, None])
n = m.Notice(tkinter, m.FAILED, "the reason", failed=True); n.root.update()
out["failed_at"] = [n.c.itemcget(i, "text") for i in n.c.find_all() if n.c.type(i) == "text"]
m.FAILED_AT[0] = None
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
n.root.update()
out["busy_place"] = [n.root.winfo_y(), n.root.winfo_height()]
n.root.after(1500, lambda: (out.__setitem__("note_stayed", True), n.root.destroy()))
n.root.mainloop()
out.setdefault("note_stayed", False)
# With no picture (Pillow missing, or a slip in the drawing) the bar keeps its parts, the done one filled, and the logo is
# written in words where it was to be
m.Glass.art = lambda self, shapes: None
w = m.Starting(tkinter)
w.show(1, False); w.draw(); w.root.update()
parts = [w.c.itemcget(i, "fill") for i in w.c.find_withtag("art") if w.c.type(i) == "rectangle" and w.c.itemcget(i, "fill")]
out["plain_marks"] = {"parts": len(parts), "done": parts.count(m.Glass.OK),     # the panel's green, as its load steps
                      "words": [w.c.itemcget(i, "text") for i in w.c.find_all() if w.c.type(i) == "text"][:4]}
w.close()
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
        check(f"the start's window draws every step, in {lang}: the three steps' names under the bar, the time taken, and the state in its pill",
              all(all(n in texts for n in m.STEPS) for texts in steps) and m.t("Starting") in steps[0] and m.clock(5) in steps[1]
              and m.t("Running") in steps[2] and not any(x.startswith("-") for t_ in steps for x in t_)
              and out["start_bg"] == G.BG, json.dumps(steps, ensure_ascii=False))
        check(f"...no sentence in it: the words are the release, the pill, the names and the time, in {lang}",
              all(len(x) <= 12 for texts in steps for x in texts), json.dumps(steps, ensure_ascii=False))
        check(f"under the bar the launcher's last line as it is written, its colour codes and markers out, cut to the window, in {lang}",
              out["detail"] == "Container sidenote  Started" and out["detail_long"].endswith("…") and len(out["detail_long"]) < 80,
              json.dumps({k: out[k] for k in ("detail", "detail_long")}))
        check(f"the part under way is drawn again each frame, nothing filled before it has some length, and the pill's light breathes, in {lang}",
              out["moving_first"] == {"patch": True, "short": True, "breath": True}, json.dumps(out["moving_first"]))
        check(f"...and a few seconds on it is filled part of the way, never past most of its part, in {lang}",
              0.2 <= out["moving_later"]["share"] <= 0.86, json.dumps(out["moving_later"]))
        check(f"a failure the start's window saw shows the bar's steps under it and the time taken, in {lang}",
              all(n in out["failed_at"] for n in m.STEPS) and m.clock(12.5, tenths=True) in out["failed_at"]
              and m.FAILED in out["failed_at"], json.dumps(out["failed_at"], ensure_ascii=False))
        f = out["failed"]
        check(f"a failure shows its title by a red mark and the launcher's lines, read only, in {lang}",
              m.FAILED in f["title"] and f["dot"] == [G.BAD] and f["text"] and f["state"] == "disabled", json.dumps(f, ensure_ascii=False))
        check(f"...with the end in view and the start a scroll away, in a window shorter than the screen, in {lang}",
              f["end_seen"] and not f["start_seen"] and f["height"] < f["screen"], json.dumps(f, ensure_ascii=False))
        check(f"...and Esc or its Close key takes it away, in {lang}", f["closed_by_esc"] and out["closed_by_key"], json.dumps(out, ensure_ascii=False)[:300])
        check(f"a note wears the grey mark and goes by itself, in {lang}", out["busy_dot"] == [G.MUTED] and not out["note_stayed"],
              json.dumps({k: out[k] for k in ("busy_dot", "note_stayed")}))
        (sy, sh), (ny, nh) = out["start_place"], out["busy_place"]
        check(f"...and stands above the start's window it is about, which it covered, in {lang}", ny + nh <= sy,
              json.dumps({"start": out["start_place"], "note": out["busy_place"]}))
        check(f"with no picture the bar keeps its three parts, the done one filled, and the logo is written in words, in {lang}",
              out["plain_marks"]["parts"] == 3 and out["plain_marks"]["done"] == 1 and "sidenote" in out["plain_marks"]["words"],
              json.dumps(out["plain_marks"]))
        white, dark, blue = out["over_white"], out["over_dark"], out["over_blue"]
        # ...and shows it: over a white desk its mean light is 0.07 at least (0.089 measured), where the first frosted glass,
        # tinted 55 to 90%, was 0.048 and read as a grey board with nothing behind it
        check(f"the glass is frosted: the desk shows through it, lighter over a white desk than over a dark one, in {lang}",
              all(x["frosted"] and x["alpha"] == 1.0 for x in (white, dark, blue)) and white["light"] > dark["light"] * 2
              and white["light"] >= 0.07, json.dumps({"white": white, "dark": dark}))
        check(f"...and its colour: over a blue desk the glass is blue, in {lang}",
              blue["colour"][2] - blue["colour"][0] >= 20 and dark["light"] < blue["light"] < white["light"], json.dumps(blue))
        check(f"...and every word on it, the release and the time among them, keeps 4.5:1 over each desk, in {lang}",
              min(x["contrast"] for x in (white, dark, blue)) >= 4.5 and any(x.startswith("v") for x in white["words"])
              and m.clock(74) in white["words"], json.dumps({"white": white, "dark": dark, "blue": blue}, ensure_ascii=False))
        check(f"the logo is the picture beside launch.pyw (client/logo.png), in {lang}", white["logo"], json.dumps(white))

print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
