"""Unpacks the packages LeetCode's JavaScript judge has ready into /node_modules, where node finds them from
any folder. Build time only (runner/Dockerfile): the runner itself has no network. Each tarball is
checked against the sha256 runner/Dockerfile pins, so a package whose bytes differ stops the build.

  python3 js_packages.py <name> <version> <file> <sha256> [<name> ...]
"""
import hashlib
import io
import os
import shutil
import sys
import tarfile
import urllib.request

REGISTRY = "https://registry.npmjs.org/%s/-/%s-%s.tgz"
ROOT = "/node_modules"


def main(words: list) -> int:
    if not words or len(words) % 4:
        return print(__doc__.strip().splitlines()[-1], file=sys.stderr) or 2
    for name, version, file, want in (words[i:i + 4] for i in range(0, len(words), 4)):
        url = REGISTRY % (name.replace("/", "%2f"), file, version)
        data = urllib.request.urlopen(url, timeout=300).read()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            print(f"{name}@{version}: checksum differs ({got})", file=sys.stderr)
            return 1
        where = os.path.join(ROOT, name)
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            # every npm tarball holds one "package" folder, which is the module itself
            tar.extractall(where + ".tmp", members=[m for m in tar if m.name.startswith("package/")],
                           filter="data")
        shutil.rmtree(where, ignore_errors=True)
        os.rename(os.path.join(where + ".tmp", "package"), where)
        shutil.rmtree(where + ".tmp", ignore_errors=True)
        print(f"{name}@{version} unpacked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
