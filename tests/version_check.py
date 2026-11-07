"""One version, in every place that says it: server/version.py as the source, the Helm chart agreeing with it, the
release step's script (.github/check_version.py) passing a tag that matches and refusing one that does not, release.yml
running that script before it builds or publishes anything, and `./sidenote version` printing the number from the file.
With them, what the release files and the documents say of a release: what a pre-release tag publishes, and the
versions, paths and prerequisites people copy from the documents.

    .venv/bin/python tests/version_check.py

The script runs on fake trees as well as on this one, and the launcher in a copy of its own with every outside
program it calls stood in for: nothing reaches Docker, a server or the network.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
SCRIPT = ROOT / ".github" / "check_version.py"
PASS, FAIL = [], []
WORK = Path(tempfile.mkdtemp(prefix="sidenote-version-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)


def tree(name: str, version: str | None, chart: str | None, app: str | None) -> Path:
    """A fake tree with the two files the script reads: server/version.py saying `version` (none: no such line) and a
    Chart.yaml with `chart` and `app` as its version and appVersion (none: the key left out)."""
    root = WORK / name
    (root / "server").mkdir(parents=True)
    (root / "deploy" / "helm" / "sidenote").mkdir(parents=True)
    (root / "server" / "version.py").write_text('"""The version."""\n\n# a comment\n'
                                                + (f'VERSION = "{version}"\n' if version is not None else "VERSION = None\n"),
                                                encoding="utf-8")
    lines = ["apiVersion: v2", "name: sidenote", "description: >-", "  a chart, with version: 9.9.9 in its words", "type: application"]
    lines += [f"version: {chart}"] if chart is not None else []
    lines += [f'appVersion: "{app}"'] if app is not None else []
    lines += ["dependencies:", "  - name: other", "    version: 7.7.7"]   # a dependency's version is not the chart's
    (root / "deploy" / "helm" / "sidenote" / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def script(tag: str, root: Path | None = None) -> tuple[int, str]:
    """The release step's script as release.yml runs it: its exit status and what it printed."""
    args = [sys.executable, str(SCRIPT), tag] + (["--root", str(root)] if root else [])
    done = subprocess.run(args, capture_output=True, text=True, timeout=60)
    return done.returncode, done.stdout + done.stderr


print("\n[the source]")
text = (ROOT / "server" / "version.py").read_text(encoding="utf-8")
lines = re.findall(r'^VERSION = "([^"]*)"\s*$', text, re.M)
VERSION = lines[0] if lines else ""
check("server/version.py has one VERSION line, read as text", len(lines) == 1, lines)
check(f"...MAJOR.MINOR.PATCH ({VERSION})", re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", VERSION) is not None, VERSION)
sys.path.insert(0, str(ROOT))
from server.version import VERSION as IMPORTED  # noqa: E402
check("...the same value the server imports", IMPORTED == VERSION, (IMPORTED, VERSION))
chart = (ROOT / "deploy" / "helm" / "sidenote" / "Chart.yaml").read_text(encoding="utf-8")
check("the chart's version and appVersion are the same version", re.search(rf"^version: {re.escape(VERSION)}$", chart, re.M)
      and re.search(rf'^appVersion: "{re.escape(VERSION)}"$', chart, re.M), re.findall(r"^(?:version|appVersion):.*$", chart, re.M))

print("\n[the release step's script]")
rc, out = script("v" + VERSION)
check(f"this tree with its own tag (v{VERSION}): passes", rc == 0, out)
major, minor, patch = (int(x) for x in VERSION.split("."))
rc, out = script(f"v{major}.{minor}.{patch + 1}")
check("this tree with another version's tag: refused, saying which", rc == 1 and f"v{major}.{minor}.{patch + 1}" in out
      and f"v{VERSION}" in out, out)
rc, out = script(VERSION)
check("a tag without its v: refused", rc == 1, out)
good = tree("good", "1.2.3", "1.2.3", "1.2.3")
for tag, want in (("v1.2.3", 0), ("v1.2.4", 1), ("v1.2.3-rc.1", 1), ("v1.2", 1), ("1.2.3", 1), ("", 1)):
    rc, out = script(tag, good)
    check(f"a fake tree at 1.2.3, the tag {tag or '(empty)'}: {'passes' if not want else 'refused'}", rc == want, out)
for name, args in (("the chart's version behind", ("1.2.3", "1.2.2", "1.2.3")),
                   ("the chart's appVersion behind", ("1.2.3", "1.2.3", "1.2.2")),
                   ("the chart with no appVersion", ("1.2.3", "1.2.3", None)),
                   ("server/version.py with no VERSION line", (None, "1.2.3", "1.2.3")),
                   ("server/version.py not a version", ("1.2", "1.2", "1.2"))):
    rc, out = script("v" + (args[0] or "1.2.3"), tree(name.replace(" ", "-").replace("'", ""), *args))
    check(f"{name}: refused, saying what differs", rc == 1 and ("Chart.yaml" in out or "version.py" in out), out)
rc, out = script("v2.0.0-rc.1", tree("pre", "2.0.0-rc.1", "2.0.0-rc.1", "2.0.0-rc.1"))
check("a pre-release named the same everywhere: passes (what it publishes as is the workflow's to say)", rc == 0, out)

print("\n[release.yml]")
wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
first = wf[wf.find("\n  notes:"):wf.find("\n  checks:")]
step = first.find('python3 .github/check_version.py "$GITHUB_REF_NAME"')
check("the workflow's first job runs the script on the tag", step > 0, step)
check("...right after the checkout", step > 0 and first.rfind("actions/checkout", 0, step) > 0
      and first.count("- name:", first.rfind("actions/checkout", 0, step), step) == 1, first[:400])
release = wf[wf.find("\n  release:"):]
check("...and the release job, which builds, pushes and publishes, waits for it", "needs: [notes," in release, release[:120])
check("the first job builds and pushes nothing", not any(x in first for x in ("docker/build-push-action", "helm push",
                                                                               "softprops/action-gh-release")), first[:200])

print("\n[a pre-release tag]")
version_step = release[release.find("Version and names"):release.find("docker/setup-buildx-action")]
check("the release job reads a pre-release from the tag's -", '*-*) echo "pre=true"' in version_step, version_step[:300])
check("...publishes it as one", "prerelease: ${{ steps.v.outputs.pre == 'true' }}" in release)
check("...and moves neither image's latest", not re.search(r"^\s+ghcr\.io/\S+:latest\s*$", release, re.M)
      and release.count("steps.v.outputs.pre == 'false' && format(") == 2, re.findall(r".*:latest.*", release))

print("\n[what the documents name]")
chart_readme = (ROOT / "deploy" / "helm" / "sidenote" / "README.md").read_text(encoding="utf-8")
named = re.findall(r"--version (\S+)|appVersion` \((\S+?)\)|registry\.example\.com/sidenote(?:-runner)?:([0-9]\S*)", chart_readme)
check("the chart's README names no other version", all(VERSION in group for group in named), named)
guide = (ROOT / "docs" / "air-gapped.md").read_text(encoding="utf-8")
releases = re.findall(r"^V=(\S+)", guide, re.M)
check("the guide for no internet takes this release", releases and all(v == VERSION for v in releases), releases)
notes = (ROOT / "deploy" / "helm" / "sidenote" / "templates" / "NOTES.txt").read_text(encoding="utf-8")
check("the chart's NOTES asks for no path of a checkout", "deploy/helm/sidenote" not in notes
      and "oci://ghcr.io/kanggu12/charts/sidenote --version {{ .Chart.Version }}" in notes)
values = (ROOT / "deploy" / "helm" / "sidenote" / "values.yaml").read_text(encoding="utf-8")
check("the chart's values say the published chart needs no image built", "published chart" in values)
doc = lambda *parts: (ROOT.joinpath(*parts)).read_text(encoding="utf-8")   # noqa: E731
# The badges are files in the repository (.github/badges.sh): one shields.io worked out from GitHub's API as the page was shown
# came slower than GitHub's image proxy waits (504 after 4 s), and the README showed it as a broken picture
readme = doc("README.md")
release_svg = (ROOT / "docs" / "assets" / "badges" / "release.svg")
check("README's badges are files in the repository, none from another site but CI's own",
      "img.shields.io" not in readme and all((ROOT / src).is_file() for src in re.findall(r'src="(docs/assets/badges/[^"]+)"', readme))
      and len(re.findall(r'src="docs/assets/badges/', readme)) == 4)
check("...and the release badge and its alt text name this release",
      release_svg.is_file() and f"release: v{VERSION}" in release_svg.read_text(encoding="utf-8")
      and f'alt="Release v{VERSION}"' in readme)
check("README's Docker setup names python3", "`python3`" in doc("README.md").split("### With Docker")[1].split("```")[0])
check("the guide's requirements name python3", "`python3`" in doc("docs", "README.md").split("## 2. Requirements")[1].split("## 3.")[0])
check("the guide names the TZ setting", "| `TZ` |" in doc("docs", "README.md"))
check("the architecture's list of notes counts nothing that goes stale", not re.search(r"\b\d+ numbered notes", doc("docs", "ARCHITECTURE.md"))
      and "| Topic | Notes |" not in doc("docs", "ARCHITECTURE.md"))
check("CONTRIBUTING claims no restart policy compose.yaml does not have", "restart policy" not in doc("CONTRIBUTING.md"))
capture_doc = doc("docs", "capture-client.md")
pictures = re.findall(r'src="(assets/[^"]+)"', capture_doc)
check("the capture zip carries the pictures of its README", pictures and all(f"cp docs/{p} dist/sidenote-capture/assets/" in release for p in pictures), pictures)

print("\n[./sidenote version]")
# A copy of the launcher beside a version.py of its own (the launcher works from its own folder), and the programs it
# asks stood in for: docker and the agents' CLIs answer nothing, curl finds no server
bin_dir = WORK / "bin"
bin_dir.mkdir()
for name, status in (("docker", 1), ("claude", 1), ("codex", 1), ("curl", 7)):
    (bin_dir / name).write_text(f"#!/bin/sh\nexit {status}\n", encoding="utf-8")
    (bin_dir / name).chmod(0o755)
env = {k: v for k, v in os.environ.items() if not k.startswith("SIDENOTE_")}
env.update(PATH=f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}", COMPOSE_FILE="compose.yaml", SIDENOTE_LANG="en",
           SIDENOTE_LOG_PATH=str(WORK / "logs"), HOME=str(WORK))


def launcher(folder: Path, *args, **more) -> tuple[int, str]:
    done = subprocess.run(["bash", str(folder / "sidenote"), *args], capture_output=True, text=True, timeout=120,
                          env={**env, **more}, stdin=subprocess.DEVNULL)
    return done.returncode, done.stdout + done.stderr


rc, out = launcher(ROOT, "version")
check(f"./sidenote version starts with Sidenote {VERSION}", rc == 0 and out.splitlines()[:1] == [f"Sidenote {VERSION}"], out[:300])
rc, out = launcher(ROOT, "version", SIDENOTE_LANG="ko")
check("...in Korean too", rc == 0 and out.splitlines()[:1] == [f"Sidenote {VERSION}"], out[:300])
copy = WORK / "copy"
(copy / "server").mkdir(parents=True)
shutil.copy(ROOT / "sidenote", copy / "sidenote")
(copy / "server" / "version.py").write_text('"""Another."""\nVERSION = "9.8.7"\n', encoding="utf-8")
rc, out = launcher(copy, "version")
check("...the number read from server/version.py, whatever it says", rc == 0 and out.splitlines()[:1] == ["Sidenote 9.8.7"], out[:300])
(copy / "server" / "version.py").unlink()
rc, out = launcher(copy, "version")
check("...and without the file, the name alone and the rest of its lines", rc == 0 and out.splitlines()[:1] == ["Sidenote"]
      and "Source" in out, out[:300])
rc, out = launcher(ROOT, "--version")
check("./sidenote --version is the same", rc == 0 and out.splitlines()[:1] == [f"Sidenote {VERSION}"], out[:200])

shutil.rmtree(WORK, ignore_errors=True)
print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)   # tests/run.sh counts a suite by its exit status
