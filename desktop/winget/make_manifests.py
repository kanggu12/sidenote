"""Writes the winget manifests of one Sidenote release, laid out as microsoft/winget-pkgs keeps them:
manifests/k/kanggu12/Sidenote/<version>/, with the version, installer and locale files.

    python desktop/winget/make_manifests.py 0.1.1 [--out DIR] [--sha256 HEX] [--date YYYY-MM-DD]

The Windows zip's checksum is read from the release's SHA256SUMS unless --sha256 gives it, and the release date from
the release itself unless --date gives it. Standard library only, so a CI runner runs it as it is.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = "kanggu12/sidenote"
PACKAGE = "kanggu12.Sidenote"            # Publisher.Package, as winget names packages; the publisher part is the account
ZIP = "Sidenote-windows-x64.zip"         # the asset release.yml publishes, the same name in every release
SCHEMA = "1.10.0"                        # winget-pkgs takes it, and so does the winget 1.11 on GitHub's runners
HEADER = "# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{schema}.schema.json\n\n"


def fetch(url: str) -> bytes:
    """A GET with a User-Agent GitHub accepts; a failure ends the run, as a manifest without its facts is no use."""
    request = urllib.request.Request(url, headers={"User-Agent": "sidenote-winget-manifests"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return reply.read()


def release_sha256(version: str) -> str:
    """The Windows zip's line in the release's SHA256SUMS."""
    sums = fetch(f"https://github.com/{REPO}/releases/download/v{version}/SHA256SUMS").decode("utf-8")
    for line in sums.splitlines():
        digest, _, name = line.strip().partition("  ")   # sha256sum's own format: the digest, two spaces, the name
        if name == ZIP:
            return digest
    raise SystemExit(f"SHA256SUMS of v{version} has no line for {ZIP}")


def release_date(version: str) -> str:
    """The day the release was published (YYYY-MM-DD), from GitHub's API."""
    info = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"))
    return info["published_at"][:10]


def block(text: str, indent: str = "  ") -> str:
    """A YAML literal block (|-) of plain lines, indented under its key."""
    return "|-\n" + "\n".join(indent + line for line in text.strip().splitlines())


def manifests(version: str, sha256: str, date: str) -> dict[str, str]:
    """The four files, by name: the version file, the installer, the default locale (English) and Korean."""
    url = f"https://github.com/{REPO}/releases/download/v{version}/{ZIP}"
    notes = f"https://github.com/{REPO}/releases/tag/v{version}"
    common = f"PackageIdentifier: {PACKAGE}\nPackageVersion: {version}\n"
    files = {}
    files[f"{PACKAGE}.yaml"] = (HEADER.format(kind="version", schema=SCHEMA) + common
                                + f"DefaultLocale: en-US\nManifestType: version\nManifestVersion: {SCHEMA}\n")
    # The zip holds the app's folder: winget unpacks all of it and links the command to the program inside, so the
    # program keeps the files beside it. Ollama is what the local model runs on, and the Quick start installs it first.
    files[f"{PACKAGE}.installer.yaml"] = (
        HEADER.format(kind="installer", schema=SCHEMA) + common
        + "InstallerType: zip\n"
        + "NestedInstallerType: portable\n"
        + "NestedInstallerFiles:\n"
        + "- RelativeFilePath: Sidenote\\Sidenote.exe\n"
        + "  PortableCommandAlias: sidenote\n"
        + "Dependencies:\n"
        + "  PackageDependencies:\n"
        + "  - PackageIdentifier: Ollama.Ollama\n"
        + f"ReleaseDate: {date}\n"
        + "Installers:\n"
        + "- Architecture: x64\n"
        + f"  InstallerUrl: {url}\n"
        + f"  InstallerSha256: {sha256.upper()}\n"
        + f"ManifestType: installer\nManifestVersion: {SCHEMA}\n")
    english = """Sidenote reads your screen and listens to your speakers. When a problem appears, such as a practice coding
problem, a question in your course material or an error log, it writes a worked answer into a panel in your browser,
beside your work. A vision model on your own GPU, through Ollama, looks at every screen first; only the hard problems
go to a cloud agent you already use (Claude Code or Codex). It is made for learning, practice and your own work."""
    files[f"{PACKAGE}.locale.en-US.yaml"] = (
        HEADER.format(kind="defaultLocale", schema=SCHEMA) + common
        + "PackageLocale: en-US\n"
        + "Publisher: J.-G. Kang\n"
        + "PublisherUrl: https://github.com/kanggu12\n"
        + f"PublisherSupportUrl: https://github.com/{REPO}/issues\n"
        + "Author: J.-G. Kang\n"
        + "PackageName: Sidenote\n"
        + f"PackageUrl: https://github.com/{REPO}\n"
        + "License: MIT\n"
        + f"LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE\n"
        + "Copyright: Copyright (c) 2026 J.-G. Kang (kanggu12)\n"
        + "ShortDescription: A study and work companion that reads your screen and writes the worked answer beside it.\n"
        + "Description: " + block(english) + "\n"
        + "Moniker: sidenote\n"
        + "Tags:\n- claude-code\n- codex\n- gemma\n- local-llm\n- ollama\n- screen-capture\n- study\n"
        + f"ReleaseNotesUrl: {notes}\n"
        + "Documentations:\n"
        + "- DocumentLabel: User guide\n"
        + f"  DocumentUrl: https://github.com/{REPO}/blob/main/docs/README.md\n"
        + f"ManifestType: defaultLocale\nManifestVersion: {SCHEMA}\n")
    korean = """Sidenote는 화면을 읽고 스피커 소리를 듣습니다. 연습 코딩 문제, 강의 자료 속 질문, 오류 로그 같은 문제가
보이면 풀이를 브라우저의 패널에 적어 작업 옆에 보여 줍니다. Ollama로 내 GPU의 비전 모델이 모든 화면을 먼저 보고,
어려운 문제만 이미 쓰는 클라우드 에이전트(Claude Code, Codex)에 보냅니다. 공부, 연습, 자기 일을 위해 만들었습니다."""
    files[f"{PACKAGE}.locale.ko-KR.yaml"] = (
        HEADER.format(kind="locale", schema=SCHEMA) + common
        + "PackageLocale: ko-KR\n"
        + "ShortDescription: 화면의 문제를 읽고 풀이를 옆에 적어 주는 도우미\n"
        + "Description: " + block(korean) + "\n"
        + "Documentations:\n"
        + "- DocumentLabel: 사용 안내서\n"
        + f"  DocumentUrl: https://github.com/{REPO}/blob/main/docs/README.md\n"
        + f"ManifestType: locale\nManifestVersion: {SCHEMA}\n")
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", help="the release's version, such as 0.1.1 (a leading v is taken off)")
    ap.add_argument("--out", default="dist/winget", help="the folder the manifests/ tree goes into")
    ap.add_argument("--sha256", help="the Windows zip's SHA-256, instead of reading the release's SHA256SUMS")
    ap.add_argument("--date", help="the release date, YYYY-MM-DD, instead of asking GitHub")
    args = ap.parse_args()
    version = args.version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):          # a release tag's number; a pre-release is not packaged
        raise SystemExit(f"not a release version: {args.version}")
    sha256 = (args.sha256 or release_sha256(version)).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise SystemExit(f"not a SHA-256: {sha256}")
    date = args.date or release_date(version)
    folder = Path(args.out) / "manifests" / "k" / "kanggu12" / "Sidenote" / version   # winget-pkgs' own layout
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in manifests(version, sha256, date).items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")   # LF and UTF-8, as winget-pkgs keeps them
    print(folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
