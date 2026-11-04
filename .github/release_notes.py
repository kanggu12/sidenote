"""Prints one version's section of CHANGELOG.md, which release.yml publishes as that release's notes.

    python3 .github/release_notes.py 0.1.1 [CHANGELOG.md]

Exits 1, printing why, when the changelog has no section for that version or the section is empty: a release is not
published without its notes, so the tag's run stops before anything is built.
"""
import re
import sys
from pathlib import Path


def section(text: str, version: str) -> str | None:
    """The body under `## [version]`, up to the next `## [` heading or the link list at the end; None if absent."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)", text, re.S | re.M)
    return match.group(1).strip() if match else None


def main() -> int:
    version = sys.argv[1].removeprefix("v")                     # the tag's name or the bare number
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "CHANGELOG.md")
    body = section(path.read_text(encoding="utf-8"), version)
    if not body:
        print(f"{path} has no notes for {version}: add a '## [{version}] - YYYY-MM-DD' section first", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
