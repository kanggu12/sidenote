"""The capture's windows as a real Windows desktop draws them, on a CI runner (the desktop workflow's Windows job), never
anyone's own screen: it draws a desk over the whole screen and the windows over it. Over that desk (a gradient, a light
document window, a picture on it, a taskbar's strip): the shortcut's start window at each of its three steps, a
failure's note (client/launch.pyw), and the tray's menu (TRAY_MENU in client/capture.py), each made by its own code with
Windows' own calls, then shot off the screen with what Windows draws round it. Pictures and look.json in the folder
given; the run ends 1 when a window is not as it is meant to be:

- opaque once it has come in, the frosted glass and the logo drawn (the start window);
- no taskbar button, and no activation where it is not to be read (the start window): Tk's alpha changes wrote the
  frame's extended style from Tk's own record, and both went, until Glass.restyle;
- a shadow under it (shadows under windows are turned on for the runner's session first, as Windows 11 has them);
- every word at 4.5:1 or more on what is behind it.

Rounded corners are read and written down only: the runner's display (Hyper-V's, no GPU) rounds no popup window, a raw
Win32 one included, whatever DWM is asked.

    python .github/look/windows.py <out folder>
"""
import ctypes
import importlib.machinery
import importlib.util
import json
import os
import platform
import re
import sys
import tempfile
import time
import tkinter
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk

if os.environ.get("GITHUB_ACTIONS") != "true":              # it covers the whole screen and takes clicks: a runner's only
    sys.exit(".github/look/windows.py draws over the whole screen: it runs on a CI runner only")
ROOT = Path(__file__).resolve().parents[2]                  # the repository: this file is in .github/look/
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
user32, dwmapi = ctypes.windll.user32, ctypes.windll.dwmapi
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2, as both programs set it before any window
user32.GetClassLongW.restype = ctypes.c_ulong

loader = importlib.machinery.SourceFileLoader("launch", str(ROOT / "client" / "launch.pyw"))
spec = importlib.util.spec_from_loader("launch", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)                                       # definitions only: its window starts under __main__ alone

SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
probe = tkinter.Tk()
SCALE = probe.winfo_fpixels("1i") / 96.0
probe.destroy()


def P(n: float) -> int:
    return round(n * SCALE)


# Shadows under windows on, for the runner's session (a person's own setting is theirs; this runs on runners alone): the
# shadow each window asks for (CS_DROPSHADOW) is then drawn, as on Windows 11, and can be looked for
shadows = wintypes.BOOL()
user32.SystemParametersInfoW(0x1024, 0, ctypes.byref(shadows), 0)            # SPI_GETDROPSHADOW
if not shadows.value:
    user32.SystemParametersInfoW(0x1025, 0, ctypes.c_void_p(1), 0x3)          # SPI_SETDROPSHADOW, update and send the change


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32), ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD), ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


dev = DISPLAY_DEVICEW()
dev.cb = ctypes.sizeof(dev)
user32.EnumDisplayDevicesW(None, 0, ctypes.byref(dev), 0)   # the display adapter, for what the corners say
report = {"windows": platform.version(), "screen": [SW, SH], "scale": SCALE, "adapter": dev.DeviceString, "shots": {}}

# The desk: a wallpaper's gradient, a light document window over the bottom right where the windows stand, a picture on
# it, a taskbar's strip. Known pixel by pixel, so a window's corners and shadow are read against it
desk = Image.new("RGB", (SW, SH))
dd = ImageDraw.Draw(desk)
for y in range(SH):                                         # teal to violet, top to bottom
    k = y / max(1, SH - 1)
    dd.line([(0, y), (SW, y)], fill=(round(20 + 90 * k), round(110 - 60 * k), round(140 + 60 * k)))
x0, y0 = SW - P(620), SH - P(48) - P(420)
dd.rectangle([x0, y0, SW - P(20), SH - P(56)], fill="#ffffff", outline="#c8c8c8")
try:
    ui = ImageFont.truetype("segoeui.ttf", P(14))
except OSError:
    ui = ImageFont.load_default()
for i in range(15):
    dd.text((x0 + P(24), y0 + P(24) + i * P(24)), "Quarterly revenue grew 12.4 percent while margins held"[: 30 + (i * 7) % 24],
            fill="#1f1f1f", font=ui)
dd.rectangle([x0 + P(330), y0 + P(170), x0 + P(580), y0 + P(320)], fill="#2f6fde")
dd.rectangle([0, SH - P(48), SW, SH], fill="#1c1c1c")
back = tkinter.Tk()
back.overrideredirect(True)
back.geometry(f"{SW}x{SH}+0+0")
cv = tkinter.Canvas(back, width=SW, height=SH, highlightthickness=0, bd=0)
cv.pack()
pic = ImageTk.PhotoImage(desk, master=back)
cv.create_image(0, 0, anchor="nw", image=pic)
back.update()
time.sleep(0.8)


def lum(col) -> float:
    return sum(k * ((v / 255) / 12.92 if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4)
               for k, v in zip((0.2126, 0.7152, 0.0722), col[:3]))


def shoot(name: str, root, words_of) -> dict:
    """The window and what Windows draws round it, off the screen, and what it wears. Its own loop runs first until it
    has come in: it rises from clear over a fifth of a second on Tk's timers, and a sleep that ran no loop shot it a
    third opaque, the desk's lines plain through it"""
    end = time.monotonic() + 1.2
    while time.monotonic() < end:
        root.update()
        time.sleep(0.015)
    hwnd = int(root.wm_frame(), 16)                         # the frame Tk made round the window
    r = wintypes.RECT()
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))   # DWMWA_EXTENDED_FRAME_BOUNDS
    l, t, rr, b = r.left, r.top, r.right, r.bottom
    margin = P(24)
    shot = ImageGrab.grab(bbox=(l - margin, t - margin, rr + margin, b + margin), all_screens=True).convert("RGB")
    shot.save(OUT / f"{name}.png")
    w, h = rr - l, b - t
    inside = shot.getpixel((margin + w // 2, margin + P(4)))
    # A corner: the window's outermost pixel there shows the desk (rounded) or the window's own colour (square)
    corners = []
    for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        got = shot.getpixel((margin + cx, margin + cy))
        under = desk.getpixel((min(SW - 1, max(0, l + cx)), min(SH - 1, max(0, t + cy))))
        corners.append(sum(abs(a - c) for a, c in zip(got, under)) < sum(abs(a - c) for a, c in zip(got, inside)))
    # The shadow: strips under the window's foot and beside its right side darker than the desk drawn there (a window
    # standing on the taskbar has its foot's shadow on black, where it does not show)
    strip = ([(margin + x, margin + h + P(3)) for x in range(P(12), w - P(12), max(1, w // 60))]
             + [(margin + w + P(3), margin + y) for y in range(P(12), h - P(4), max(1, h // 30))])
    seen = sum(lum(shot.getpixel(p)) for p in strip) / len(strip)
    drawn = sum(lum(desk.getpixel((min(SW - 1, l + p[0] - margin), min(SH - 1, t + p[1] - margin)))) for p in strip) / len(strip)
    words = []
    for text, (a, c, e, f), fill in words_of():
        px = sorted((shot.getpixel((margin + x, margin + y)) for x in range(max(0, a), min(w, e)) for y in range(max(0, c), min(h, f))),
                    key=lum)
        if not px or not fill.startswith("#"):
            continue
        bg = px[len(px) // 2]
        hi, lo = sorted([lum(tuple(int(fill[k:k + 2], 16) for k in (1, 3, 5))), lum(bg)], reverse=True)
        words.append([text[:28], round((hi + 0.05) / (lo + 0.05), 2)])
    ex = user32.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF      # GWL_EXSTYLE
    return {"size": [w, h], "alpha": float(root.attributes("-alpha")), "no_taskbar_button": bool(ex & 0x80),
            "no_activation": bool(ex & 0x08000000), "shadow": round(drawn - seen, 4), "corners_rounded": corners,
            "least_contrast": min((x[1] for x in words), default=None), "words": words}


def canvas_words(c):
    return lambda: [(c.itemcget(i, "text"), c.bbox(i), c.itemcget(i, "fill")) for i in c.find_all()
                    if c.type(i) == "text" and c.itemcget(i, "text") and c.itemcget(i, "state") != "hidden"]


# The start window, its last line read as it reads it while the launcher writes (reader: the handle of its own)
said = tempfile.TemporaryFile()
said.write("[+] Running 3/3\n ✔ Container sidenote-llm  Healthy\n ✔ Container sidenote  Started\n"
           "Waiting for the server on 127.0.0.1:8777\n".encode())
said.flush()
m.LIVE["read"] = m.reader(said)
w = m.Starting(tkinter)
t0 = time.monotonic()
for name, step, done, began, waited in (("start-server", 0, False, [t0 - 6.4], 6.4),
                                         ("start-capture", 1, False, [t0 - 14.2, t0 - 11.1], 11.1),
                                         ("start-ready", 2, True, [t0 - 16.0, t0 - 12.9, t0 - 3.5], 0)):
    w.show(step, done)
    w.began, w.started = list(began), began[0]
    w.since = time.monotonic() - waited
    if done:
        w.ended = time.monotonic()
    w.read_at = 0.0
    w.draw()
    w.root.update()
    w.fill = w.goal()                                       # as far as it would have filled by now
    w.draw()
    w.root.update()
    report["shots"][name] = shoot(name, w.root, canvas_words(w.c))
    report["shots"][name].update(logo=w.logo_at is not None, frosted=w.behind is not None)
w.close()
m.LIVE["read"] = None
m.FAILED_AT[0] = (1, [3.1, 9.4, None])
n = m.Notice(tkinter, m.FAILED, "error: the capture program did not connect within 20 s\nRun ./sidenote logs to see why", failed=True)
report["shots"]["failed"] = shoot("failed", n.root, canvas_words(n.c))
n.root.destroy()

# The tray's menu by its own code, from capture.py, with the rows the tray gives it; shot where it opens instead of waiting
# for a click away (watch)
menu = re.search(r'TRAY_MENU = r"""(.*?)"""', (ROOT / "client" / "capture.py").read_text(encoding="utf-8"), re.S).group(1)
assert "watch()\nroot.mainloop()" in menu
version = re.search(r'^VERSION = "([0-9.]+)"', (ROOT / "server" / "version.py").read_text(encoding="utf-8"), re.M).group(1)
ROWS = [{"sep": False, "text": "Open the panel", "enabled": True, "checked": None, "default": True, "mark": "open", "tone": None},
        {"sep": False, "text": "Capturing: Screen · Sound", "enabled": False, "checked": None, "default": False, "mark": None, "tone": "on"},
        {"sep": True, "text": "", "enabled": False, "checked": None, "default": False, "mark": None, "tone": None},
        {"sep": False, "text": "Screen capture", "enabled": True, "checked": True, "default": False, "mark": "screen", "tone": None},
        {"sep": False, "text": "Sound capture", "enabled": True, "checked": False, "default": False, "mark": "sound", "tone": None},
        {"sep": True, "text": "", "enabled": False, "checked": None, "default": False, "mark": None, "tone": None},
        {"sep": False, "text": "Restart capture", "enabled": True, "checked": None, "default": False, "mark": "restart", "tone": None},
        {"sep": False, "text": "Quit", "enabled": True, "checked": None, "default": False, "mark": "quit", "tone": None}]
held = {}
code = menu.replace("watch()\nroot.mainloop()", "root.update(); HELD['root'] = root; HELD['c'] = c")
sys.argv = ["menu", json.dumps({"rows": ROWS, "at": [SW - P(160), SH - P(56)], "parent": os.getpid(), "lang": "en",
                                "version": version, "logo": str(ROOT / "client" / "logo.png")})]
exec(compile(code, "TRAY_MENU", "exec"), {"__name__": "__main__", "HELD": held})
report["shots"]["tray-menu"] = shoot("tray-menu", held["root"], canvas_words(held["c"]))
held["root"].destroy()
back.destroy()

# What each window is meant to be, against what it is
bad = []
for name, s in report["shots"].items():
    start = name.startswith("start-")
    if s["alpha"] < 1.0:
        bad.append(f"{name}: alpha {s['alpha']} once come in")
    if not s["no_taskbar_button"]:
        bad.append(f"{name}: a taskbar button")
    if start and not s["no_activation"]:
        bad.append(f"{name}: a click on it takes the focus")
    if s["shadow"] < 0.02:
        bad.append(f"{name}: no shadow ({s['shadow']})")
    if s["least_contrast"] is None or s["least_contrast"] < 4.5:
        bad.append(f"{name}: a word under 4.5:1 ({s['least_contrast']})")
    if start and not (s["logo"] and s["frosted"]):
        bad.append(f"{name}: logo {s['logo']}, frosted glass {s['frosted']}")
report["not_as_meant"] = bad
(OUT / "look.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
for name, s in report["shots"].items():
    print(f"{name:14} alpha {s['alpha']} no-taskbar {s['no_taskbar_button']} no-activation {s['no_activation']} "
          f"shadow {s['shadow']} least {s['least_contrast']} corners {s['corners_rounded']}")
print("Windows", report["windows"], report["screen"], "scale", report["scale"], report["adapter"])
print("not as meant:" if bad else "every window as meant", *bad, sep="\n  ")
sys.exit(1 if bad else 0)
