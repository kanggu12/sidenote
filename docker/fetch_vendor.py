"""Fetch the panel's third-party files into a folder, each checked against its sha256 in vendor.json.

    python fetch_vendor.py vendor.json OUT_DIR

Run while building the image (Dockerfile), so the panel loads nothing from a CDN at run time and its
Content-Security-Policy can allow only the server itself. A file whose bytes differ from the pinned
checksum stops the build. An entry with "classic": NAME is an ES module with no imports: it is
wrapped into a plain script that sets window.NAME, because a page opened as a file (the panel's
tests) cannot import modules.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path


def as_classic(src: str, name: str) -> str:
    body, n = re.subn(rf"^export \{{ {re.escape(name)} as default \}};\s*$", "", src, flags=re.M)
    if n != 1 or re.search(r"^\s*(import|export)\b", body, re.M):
        raise SystemExit(f"{name}: not the single-export module this wrapper expects")
    return f'(function () {{\n"use strict";\n{body}\nwindow.{name} = {name};\n}})();\n'


def fetch(url: str, tries: int = 3) -> bytes:
    """One network blip must not fail the whole image build: a few tries, a short pause between."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sidenote-build"})
            return urllib.request.urlopen(req, timeout=60).read()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise AssertionError("unreachable")


def main(manifest: str, out_dir: str) -> None:
    out = Path(out_dir)
    entries = json.loads(Path(manifest).read_text())
    for e in entries:
        data = fetch(e["url"])
        got = hashlib.sha256(data).hexdigest()
        if got != e["sha256"]:
            raise SystemExit(f"checksum mismatch: {e['url']}\n  expected {e['sha256']}\n  got      {got}")
        if e.get("classic"):
            data = as_classic(data.decode("utf-8"), e["classic"]).encode("utf-8")
        dest = out / e["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    print(f"vendor: {len(entries)} files checked and written to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
