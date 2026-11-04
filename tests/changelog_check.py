"""CHANGELOG.md holds each release's notes, which release.yml publishes (.github/release_notes.py): every
release has its section and its compare link, the script prints a section whole and nothing of the next, and a
version with no section stops the release.

    .venv/bin/python tests/changelog_check.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
SCRIPT = ROOT / ".github" / "release_notes.py"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def notes(version, path=None):
    """What release.yml's notes job prints for a tag: the script's exit code, its output and its complaint."""
    done = subprocess.run([sys.executable, str(SCRIPT), version, *( [str(path)] if path else [])],
                          cwd=str(ROOT), capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", text, re.M)

print("[every release in CHANGELOG.md]")
check("there are releases, each headed '## [x.y.z] - YYYY-MM-DD'", len(versions) >= 2, versions)
check("...newest first", [v for v, _ in versions] == sorted((v for v, _ in versions),
                                                              key=lambda v: tuple(map(int, v.split("."))), reverse=True))
version = re.search(r'^VERSION = "([^"]*)"', (ROOT / "server" / "version.py").read_text(encoding="utf-8"), re.M).group(1)
check("the newest release is the code's own version (server/version.py), so a release cannot go out without its notes",
      versions[0][0] == version, (versions[0][0], version))
check("an Unreleased section above them, for what is not released yet", text.find("## [Unreleased]") != -1
      and text.find("## [Unreleased]") < text.find(f"## [{versions[0][0]}]"))
links = dict(re.findall(r"^\[([^\]]+)\]: (\S+)$", text, re.M))
for v, _ in versions:
    code, out, err = notes(v)
    check(f"{v}: the script prints its section", code == 0 and out.strip() and "## [" not in out, err or out[:120])
    check(f"{v}: ...with a link at the end of the file", v in links and links[v].startswith(
        "https://github.com/kanggu12/sidenote/"), links.get(v))
check("Unreleased has its compare link from the newest release", links.get("Unreleased", "").endswith(
    f"/compare/v{versions[0][0]}...HEAD"), links.get("Unreleased"))

print("[the script release.yml runs]")
code, out, err = notes("v" + versions[0][0])
check("a tag's name (v1.2.3) is taken as its number", code == 0 and out.strip(), err)
code, out, err = notes("9.9.9")
check("a version with no section stops the release, and says what to add", code == 1 and not out
      and "## [9.9.9]" in err, err)
with tempfile.TemporaryDirectory() as d:
    sample = Path(d) / "CHANGELOG.md"
    sample.write_text("# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - 2026-12-01\n\n### Added\n\n- One\n\n"
                      "## [1.0.0] - 2026-11-01\n\n- Two\n\n[Unreleased]: https://x/compare/v1.1.0...HEAD\n"
                      "[1.1.0]: https://x/compare/v1.0.0...v1.1.0\n[1.0.0]: https://x/releases/tag/v1.0.0\n",
                      encoding="utf-8")
    code, out, _ = notes("1.1.0", sample)
    check("a section ends where the next release begins", code == 0 and out.strip() == "### Added\n\n- One", out)
    code, out, _ = notes("1.0.0", sample)
    check("...and the last one where the links begin", code == 0 and out.strip() == "- Two", out)
    sample.write_text("## [2.0.0] - 2026-12-01\n\n## [1.0.0] - 2026-11-01\n\n- Two\n", encoding="utf-8")
    code, _, err = notes("2.0.0", sample)
    check("an empty section stops the release too", code == 1, err)

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
