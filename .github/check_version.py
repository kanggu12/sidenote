"""The version a release names, in every place that names it: the tag (v1.2.3), server/version.py, and the Helm chart's
version and appVersion (deploy/helm/sidenote/Chart.yaml). release.yml's first job runs this before anything is built,
so a release cannot go out under a number its own code and chart do not carry.

    python3 .github/check_version.py v1.2.3                  exit 0 when all agree, 1 with what differs
    python3 .github/check_version.py v1.2.3 --root DIR       the files of another tree (tests/version_check.py)

The standard library only, and nothing imported from the server: the step runs on the runner's own Python, before any
setup. Each file is read as text, the way the launcher reads server/version.py.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # the repository: this file is in .github/
# MAJOR.MINOR.PATCH with an optional pre-release and build part, as semver.org writes it and Helm takes it
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")


def code_version(root: Path) -> str:
    """VERSION in server/version.py, or "" when the file or its line is not there."""
    try:
        text = (root / "server" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r'^VERSION = "([^"]*)"\s*$', text, re.M)    # the one line, as the file says it stays
    return found.group(1) if found else ""


def chart_versions(root: Path) -> tuple[str, str]:
    """The chart's version and appVersion, each "" when it is not there. Top-level keys only, quotes taken off."""
    try:
        text = (root / "deploy" / "helm" / "sidenote" / "Chart.yaml").read_text(encoding="utf-8")
    except OSError:
        return "", ""

    def key(name: str) -> str:
        found = re.search(rf"^{name}:\s*(\S+?)\s*(?:#.*)?$", text, re.M)   # at the line's start: not a dependency's
        return found.group(1).strip("\"'") if found else ""

    return key("version"), key("appVersion")


def problems(tag: str, root: Path) -> list[str]:
    """What does not agree, one line each; an empty list when the tag, the code and the chart name one version."""
    version = code_version(root)
    chart, app = chart_versions(root)
    out = []
    if not version:
        return [f"no VERSION = \"...\" line in {root / 'server' / 'version.py'}"]
    if not SEMVER.fullmatch(version):
        out.append(f"server/version.py says {version!r}, which is not MAJOR.MINOR.PATCH")
    if tag != f"v{version}":
        out.append(f"the tag is {tag!r}, and server/version.py says {version!r}: the tag must be v{version}")
    if chart != version:
        out.append(f"deploy/helm/sidenote/Chart.yaml has version {chart or '(none)'!r}, not {version!r}")
    if app != version:
        out.append(f"deploy/helm/sidenote/Chart.yaml has appVersion {app or '(none)'!r}, not {version!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check that a release tag names the version the code and the chart carry.")
    ap.add_argument("tag", help="the tag being released, such as v1.2.3 (GITHUB_REF_NAME)")
    ap.add_argument("--root", type=Path, default=ROOT, help="the tree to read (default: this repository)")
    args = ap.parse_args(argv)
    found = problems(args.tag, args.root)
    for line in found:
        print(f"version mismatch: {line}", file=sys.stderr)
    if found:
        print("Set server/version.py and deploy/helm/sidenote/Chart.yaml (version and appVersion) to the release's "
              "number, commit, and tag that commit.", file=sys.stderr)
        return 1
    print(f"{args.tag}: server/version.py and the chart's version and appVersion agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
