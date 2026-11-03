"""Builds Sidenote as one folder with its own Python, for people who do not install Python or Docker: Sidenote.exe on
Windows (Sidenote on Linux) with the server, the panel and the capture program inside. Run it on the system it is
for, from the repository's root, after the packages:

    python -m pip install -r server/requirements.txt -r server/requirements-audio.txt -c docker/constraints.txt
    python -m pip install -r client/requirements.txt          (the capture program's, on Linux too)
    python -m pip install -r desktop/requirements-build.txt
    python docker/fetch_vendor.py docker/vendor.json panel/vendor
    python desktop/build.py

It writes dist/Sidenote/ and dist/Sidenote-<system>-x64.zip, then runs the result with --check, which starts its
server with stand-in models and fails the build when something it needs was left out.
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
CAPTURE_IMPORTS += (["mss.windows", "soundcard.mediafoundation", "pystray._win32", "tkinter", "ctypes.wintypes"]
                    if WINDOWS else ["mss.linux", "soundcard.pulseaudio", "pystray._xorg", "pystray._appindicator",
                                     "pystray._gtk"])


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


def main() -> int:
    if not (ROOT / "panel" / "vendor").is_dir():
        print("panel/vendor is missing: python docker/fetch_vendor.py docker/vendor.json panel/vendor")
        return 1
    shutil.rmtree(DIST / "Sidenote", ignore_errors=True)
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
    args.append(str(ROOT / "desktop" / "__main__.py"))
    print(" ".join(args))
    subprocess.run(args, check=True, cwd=str(ROOT))

    print(f"licenses of {licenses(DIST / 'Sidenote' / 'licenses')} packages in {DIST / 'Sidenote' / 'licenses'}")
    exe = DIST / "Sidenote" / ("Sidenote.exe" if WINDOWS else "Sidenote")
    print(f"checking {exe}")
    log = WORK / "check.log"
    log.unlink(missing_ok=True)
    done = subprocess.run([str(exe), "--check"], timeout=300, env={**os.environ, "SIDENOTE_CHECK_LOG": str(log)})
    print(log.read_text(encoding="utf-8") if log.is_file() else "(the check wrote no report)")
    if done.returncode:
        raise SystemExit(f"{exe} --check failed with exit {done.returncode}")

    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                       platform.machine().lower())
    archive = shutil.make_archive(str(DIST / f"Sidenote-{system}-{machine}"), "zip", DIST, "Sidenote")
    print(f"wrote {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
