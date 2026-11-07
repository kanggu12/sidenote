"""Builds Sidenote as one folder with its own Python, for people who do not install Python or Docker: Sidenote.exe on
Windows, Sidenote.app on macOS (Sidenote on Linux) with the server, the panel and the capture program inside. Run it
on the system it is for, from the repository's root, after the packages:

    python -m pip install -r server/requirements.txt -r server/requirements-audio.txt -c docker/constraints.txt
    python -m pip install -r client/requirements.txt          (the capture program's, on Linux too)
    python -m pip install -r desktop/requirements-build.txt
    python docker/fetch_vendor.py docker/vendor.json panel/vendor
    python desktop/build.py

It writes dist/Sidenote/ (dist/Sidenote.app on macOS) and dist/Sidenote-<system>-<machine>.zip, then runs the result
with --check, which starts its server with stand-in models and fails the build when something it needs was left out.
On macOS it also runs the built capture program against the built server, with its menu bar icon, and quits it.
"""
from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
SEP = os.pathsep                 # PyInstaller's --add-data takes "source<sep>destination", with the system's own sep

# Files the program reads at run time, beside its code: where each goes inside the folder.
DATA = [
    ("panel", "panel"),                                  # the panel, its fonts and its libraries (panel/vendor)
    ("server/assets", "server/assets"),                  # the face finder's model
    ("server/locale", "server/locale"),                  # the server's words in other languages
    ("LICENSE", "."),
    ("docs/THIRD_PARTY_NOTICES.md", "."),                # beside the program, with LICENSE
]
# Imported where PyInstaller cannot see it: uvicorn picks its protocol and loop modules by name, and the speech
# recognizer keeps its voice detector's model as a package file.
COLLECT = ["--collect-submodules", "uvicorn", "--collect-data", "faster_whisper"]
# The text detector (server/requirements-ocr.txt) is optional and not in the server image either; a build made where
# it is installed would carry OpenCV and its libraries, about 190 MB, for a switch that is off.
EXCLUDE = ["--exclude-module", "rapidocr_onnxruntime", "--exclude-module", "cv2", "--exclude-module", "shapely"]
# The capture program is a script the app runs as it is (client/capture.py), so its imports are named here, with the
# modules each package picks for the system at run time. On Windows tkinter draws its tray menu, in a script it
# hands to `python -c`.
CAPTURE_IMPORTS = ["mss", "soundcard", "pystray", "websocket", "numpy", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"]
if WINDOWS:
    CAPTURE_IMPORTS += ["mss.windows", "soundcard.mediafoundation", "pystray._win32", "tkinter", "ctypes.wintypes"]
elif MAC:
    # pystray's menu bar icon is AppKit through PyObjC, and the capture program changes its menu on AppKit's thread
    CAPTURE_IMPORTS += ["mss.darwin", "soundcard.coreaudio", "pystray._darwin", "AppKit", "Foundation", "Quartz",
                        "objc", "PyObjCTools.AppHelper", "PyObjCTools.MachSignals"]
else:
    CAPTURE_IMPORTS += ["mss.linux", "soundcard.pulseaudio", "pystray._xorg", "pystray._appindicator", "pystray._gtk"]
# What the Mac app tells macOS about itself, written into its Info.plist after PyInstaller: the menu bar icon is its
# face, so no Dock icon, and the line macOS shows when the capture program first opens a loopback input.
MAC_PLIST = {
    "LSUIElement": True,
    "NSMicrophoneUsageDescription": "Sidenote listens to the speaker sound through a loopback input such as "
                                    "BlackHole, to write down what is said.",
    "NSHighResolutionCapable": True,
}


# Installed for building, or for the switches EXCLUDE leaves out: not part of the app, so their licenses are not in it.
NOT_IN_APP = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "macholib", "pip",
              "setuptools", "wheel", "rapidocr-onnxruntime", "opencv-python", "opencv-python-headless", "shapely",
              "pyclipper"}


def licenses(dest: Path) -> int:
    """The app carries the packages it was built from, so it carries their terms: each package's license files from its
    install record, in licenses/<package>/, with a line naming its license (some packages ship no file), and Python's.
    Returns how many packages it wrote."""
    count = 0
    for dist in importlib.metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if not name or name in NOT_IN_APP:
            continue
        out = dest / name
        out.mkdir(parents=True, exist_ok=True)
        for f in dist.files or ():
            if re.search(r"(LICEN[CS]E|COPYING|NOTICE)", f.name, re.I):
                src = Path(dist.locate_file(f))
                if src.is_file():
                    shutil.copyfile(src, out / str(f).replace("/", "_").replace("\\", "_"))
        said = dist.metadata.get("License-Expression") or (dist.metadata.get("License") or "").split("\n")[0]
        said = said or "; ".join(c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or ()
                                 if c.startswith("License ::"))
        (out / "LICENSE-SUMMARY.txt").write_text(f"{dist.metadata['Name']} {dist.version}\nLicense: {said or 'see the files here'}\n",
                                                 encoding="utf-8")
        count += 1
    python = dest / "python"
    python.mkdir(parents=True, exist_ok=True)
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
                      Path(f"/usr/share/doc/python{sys.version_info.major}.{sys.version_info.minor}/copyright")):
        if candidate.is_file():
            shutil.copyfile(candidate, python / candidate.name)
            break
    (python / "LICENSE-SUMMARY.txt").write_text(f"Python {platform.python_version()}\nLicense: PSF-2.0\n", encoding="utf-8")
    return count


def icon(path: Path) -> Path:
    """The app's icon at the sizes Windows asks an .ico for: the capture program's tray icon, drawn by its own code,
    the block between the icon markers in client/capture.py (read here, so the program itself is not imported)."""
    from PIL import Image, ImageDraw
    src = (ROOT / "client" / "capture.py").read_text(encoding="utf-8")
    block = src[src.index("# ---- the icon:"):src.index("# ---- end of the icon ----")]
    scope = {"Image": Image, "ImageDraw": ImageDraw}
    exec(block, scope)
    scope["tray_image"](256).save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                 (256, 256)])
    return path


def version() -> str:
    """The version line of server/version.py, read as text as the launcher reads it."""
    return re.search(r'^VERSION = "([^"]+)"', (ROOT / "server" / "version.py").read_text(encoding="utf-8"), re.M)[1]


# The first bytes of a Mach-O file: 32- and 64-bit, and a universal one holding several
MACH_O = (b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")


def mac_minimum(app: Path) -> str:
    """The newest macOS any program or library in the bundle was built for, from each Mach-O file's own load commands
    (LC_BUILD_VERSION's minos, or the older LC_VERSION_MIN_MACOSX): the app starts on that macOS and newer only, and
    a wheel built for a newer one than the rest (numpy's for Accelerate) raises it for the whole app."""
    newest = (0,)
    for f in app.rglob("*"):
        if f.is_symlink() or not f.is_file():
            continue
        with f.open("rb") as fh:
            if fh.read(4) not in MACH_O:
                continue
        listed = subprocess.run(["otool", "-l", str(f)], capture_output=True, text=True).stdout
        found = re.findall(r"cmd LC_BUILD_VERSION\n.*\n\s*platform 1\n\s*minos ([\d.]+)", listed)
        found += re.findall(r"cmd LC_VERSION_MIN_MACOSX\n.*\n\s*version ([\d.]+)", listed)
        for v in found:
            newest = max(newest, tuple(int(n) for n in v.split(".")))
    return ".".join(map(str, newest + (0,) * (2 - len(newest)))) if newest != (0,) else ""


def mac_bundle(app: Path) -> None:
    """Info.plist as MAC_PLIST, the version and the oldest macOS it starts on say, then the app signed again (ad hoc,
    as PyInstaller signed it): a changed Info.plist breaks the signature, and macOS on Apple silicon refuses to start
    unsigned code. Finder then says which macOS the app needs, where it would otherwise fail to start."""
    import plistlib
    plist = app / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info.update(MAC_PLIST, CFBundleShortVersionString=version(), CFBundleVersion=version())
    oldest = mac_minimum(app)
    if oldest:
        info["LSMinimumSystemVersion"] = oldest
    plist.write_bytes(plistlib.dumps(info))
    print(f"Info.plist: macOS {oldest or '(no minimum found)'} or newer, version {version()}")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def mac_capture_check(exe: Path) -> None:
    """The built capture program against the built server, both from the app, with its menu bar icon on: it has to
    connect and send a screen, and end itself when the server asks it to, as its Quit does. This runs AppKit's loop
    on the main thread and the capture beside it, which no other check reaches."""
    import json
    import socket
    import time
    import urllib.request
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "SIDENOTE_ANALYZER": "mock", "SIDENOTE_TRANSCRIBER": "null",
           "SIDENOTE_DATA_DIR": str(WORK / "mac-check"), "SIDENOTE_LOG_DIR": str(WORK / "mac-check" / "logs")}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def health() -> dict:
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                return json.loads(r.read())
        except OSError:
            return {}

    server = subprocess.Popen([str(exe), "--serve", "--port", str(port)], env=env)
    capture = None
    try:
        for _ in range(240):
            if health():
                break
            time.sleep(0.5)
        else:
            raise SystemExit("the built server did not answer /health")
        capture = subprocess.Popen([str(exe), "--capture", "--server", f"ws://127.0.0.1:{port}/ingest", "--no-audio",
                                    "--no-auto-update"], env=env)
        seen = {}
        for _ in range(120):
            seen = health().get("capture", {})
            if seen.get("clients") and seen.get("last_frame"):
                break
            if capture.poll() is not None:
                raise SystemExit(f"the built capture program ended with exit {capture.returncode}")
            time.sleep(0.5)
        else:
            raise SystemExit(f"the built capture program sent no screen: {seen}")
        print(f"the built capture program connected and sent a screen ({seen.get('info')})")
        # Skip windows reads the window server's list (client/capture.py, _windows_mac); a list it could not read is in
        # caps as skip_limit, which stays out of them while every window can be read
        limit = (seen.get("caps") or {}).get("skip_limit", "")
        if limit:
            raise SystemExit(f"the built capture program cannot read the windows (skip_limit {limit!r})")
        print("...it reads the windows, for Skip windows and the panel's own window")
        opener.open(urllib.request.Request(f"http://127.0.0.1:{port}/capture/quit", data=b"", method="POST"), timeout=5)
        code = capture.wait(timeout=20)
        if code != 0:
            raise SystemExit(f"the built capture program ended with exit {code} when asked to quit")
        print("...and ended itself when asked to, with its menu bar icon")
    finally:
        for proc in (capture, server):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def mac_icon(path: Path) -> Path:
    """The same drawing at 1024 px as a PNG, which PyInstaller turns into the .icns a Mac app carries."""
    from PIL import Image, ImageDraw
    src = (ROOT / "client" / "capture.py").read_text(encoding="utf-8")
    scope = {"Image": Image, "ImageDraw": ImageDraw}
    exec(src[src.index("# ---- the icon:"):src.index("# ---- end of the icon ----")], scope)
    scope["tray_image"](1024).save(path)
    return path


def main() -> int:
    if not (ROOT / "panel" / "vendor").is_dir():
        print("panel/vendor is missing: python docker/fetch_vendor.py docker/vendor.json panel/vendor")
        return 1
    shutil.rmtree(DIST / "Sidenote", ignore_errors=True)
    shutil.rmtree(DIST / "Sidenote.app", ignore_errors=True)
    WORK.mkdir(exist_ok=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "Sidenote",
            "--distpath", str(DIST), "--workpath", str(WORK / "pyinstaller"), "--specpath", str(WORK),
            # the folder holding Sidenote.exe keeps the other files in _internal/, out of sight
            "--contents-directory", "_internal"]
    for source, dest in DATA:
        args += ["--add-data", f"{ROOT / source}{SEP}{dest}"]
    args += COLLECT + EXCLUDE
    args += ["--add-data", f"{ROOT / 'client' / 'capture.py'}{SEP}client"]
    for name in CAPTURE_IMPORTS:
        args += ["--hidden-import", name]
    if WINDOWS:
        # no console window: the tray icon and the panel are the program's face, and a problem shows in a message box
        args += ["--windowed", "--icon", str(icon(WORK / "sidenote.ico"))]
    elif MAC:
        # an app bundle, opened from the Finder; its menu bar icon and the panel are its face. PyInstaller makes the
        # .icns from the PNG, and the speaker sound's cffi headers are package data
        args += ["--windowed", "--icon", str(mac_icon(WORK / "sidenote.png")),
                 "--osx-bundle-identifier", "io.github.kanggu12.sidenote", "--collect-data", "soundcard"]
    args.append(str(ROOT / "desktop" / "__main__.py"))
    print(" ".join(args))
    subprocess.run(args, check=True, cwd=str(ROOT))

    # the app's own folder: beside Sidenote.exe, or the bundle's Resources on macOS
    home = DIST / "Sidenote.app" / "Contents" / "Resources" if MAC else DIST / "Sidenote"
    print(f"licenses of {licenses(home / 'licenses')} packages in {home / 'licenses'}")
    if MAC:
        mac_bundle(DIST / "Sidenote.app")
    exe = (DIST / "Sidenote.app" / "Contents" / "MacOS" / "Sidenote" if MAC
           else DIST / "Sidenote" / ("Sidenote.exe" if WINDOWS else "Sidenote"))
    print(f"checking {exe}")
    log = WORK / "check.log"
    log.unlink(missing_ok=True)
    done = subprocess.run([str(exe), "--check"], timeout=300, env={**os.environ, "SIDENOTE_CHECK_LOG": str(log)})
    print(log.read_text(encoding="utf-8") if log.is_file() else "(the check wrote no report)")
    if done.returncode:
        raise SystemExit(f"{exe} --check failed with exit {done.returncode}")
    if MAC:
        mac_capture_check(exe)

    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                       platform.machine().lower())
    name = DIST / f"Sidenote-{system}-{machine}.zip"
    if MAC:
        # ditto, as the Finder's own Compress does: it keeps the bundle's links and signature, which a plain zip breaks
        name.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(DIST / "Sidenote.app"), str(name)],
                       check=True)
    else:
        shutil.make_archive(str(name.with_suffix("")), "zip", DIST, "Sidenote")
    print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
