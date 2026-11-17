"""The capture program as a wheel, the Python package format pip installs: sidenote_capture-<version>-py3-none-any.whl,
for any system with Python 3.10 or newer (py3-none-any: any Python 3, no compiled part, any platform). pip installs the
packages it needs with it and puts a `sidenote-capture` command on the PATH; `python -m sidenote_capture` runs it too.
Written here with the standard library alone, as the wheel format sets it out (a zip with the package and a .dist-info
folder: METADATA, WHEEL, entry_points.txt, RECORD), so it builds the same on any machine with no build tools and no
network. release.yml runs it; tests/version_check.py builds one, installs it and starts it.

    python .github/capture_wheel.py OUT_DIR        writes OUT_DIR/sidenote_capture-<version>-py3-none-any.whl
"""
from __future__ import annotations

import base64
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # the repository: this file is in .github/
PACKAGE = "sidenote_capture"                        # the import name; the wheel's own name uses it too, as the format asks
DIST = "sidenote-capture"                           # the project's name as pip and its listing show it
# Run as `python -m sidenote_capture`: the program's own main, as `python capture.py` runs it
MAIN = '"""`python -m sidenote_capture`: the capture program, as `python capture.py` runs it."""\nfrom .capture import main\n\nmain()\n'
INIT = '"""Sidenote\'s capture program: sends this PC\'s screen and sound to a Sidenote server (`sidenote-capture --help`)."""\n'


def version() -> str:
    """The one version, read from server/version.py as text, as the launcher and the desktop build read it."""
    return re.search(r'^VERSION = "([^"]+)"', (ROOT / "server" / "version.py").read_text(encoding="utf-8"), re.M)[1]


def requirements() -> list[str]:
    """client/requirements.txt's packages, its comments and blank lines left out: the wheel's Requires-Dist."""
    lines = (ROOT / "client" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]


def digest(data: bytes) -> str:
    """A file's line in RECORD: its SHA-256 in unpadded URL-safe base64, as the format writes it."""
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def build(out: Path) -> Path:
    v = version()
    info = f"{PACKAGE}-{v}.dist-info"
    # The package: the program and what it reads beside itself (its logo, the tray icon on Windows, the version it says
    # in its hello, read from version.py beside it as in the release's other folders)
    files: dict[str, bytes] = {
        f"{PACKAGE}/__init__.py": INIT.encode(),
        f"{PACKAGE}/__main__.py": MAIN.encode(),
        f"{PACKAGE}/capture.py": (ROOT / "client" / "capture.py").read_bytes(),
        f"{PACKAGE}/logo.png": (ROOT / "client" / "logo.png").read_bytes(),
        f"{PACKAGE}/sidenote.ico": (ROOT / "client" / "sidenote.ico").read_bytes(),
        f"{PACKAGE}/version.py": (ROOT / "server" / "version.py").read_bytes(),
    }
    readme = (ROOT / "docs" / "capture-client.md").read_text(encoding="utf-8")
    metadata = "\n".join([
        "Metadata-Version: 2.1",
        f"Name: {DIST}",
        f"Version: {v}",
        "Summary: Sidenote's capture program: sends this PC's screen and sound to a Sidenote server",
        "Home-page: https://github.com/kanggu12/sidenote",
        "License: MIT",
        "Requires-Python: >=3.10",
        *[f"Requires-Dist: {r}" for r in requirements()],
        "Description-Content-Type: text/markdown",
        "",
        readme,
    ])
    files[f"{info}/METADATA"] = metadata.encode()
    files[f"{info}/WHEEL"] = "Wheel-Version: 1.0\nGenerator: sidenote capture_wheel.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n".encode()
    # the command pip puts on the PATH, and on Windows its .exe beside python.exe
    files[f"{info}/entry_points.txt"] = f"[console_scripts]\n{DIST} = {PACKAGE}.capture:main\n".encode()
    files[f"{info}/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    # RECORD lists every file with its hash and size, itself last with neither
    record = "".join(f"{name},{digest(data)},{len(data)}\n" for name, data in files.items()) + f"{info}/RECORD,,\n"
    files[f"{info}/RECORD"] = record.encode()
    out.mkdir(parents=True, exist_ok=True)
    wheel = out / f"{PACKAGE}-{v}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            # a fixed time for every entry: the same source makes the same file, byte for byte
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o644 << 16          # an ordinary readable file once unpacked
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, data)
    print(f"wrote {wheel}")
    return wheel


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
