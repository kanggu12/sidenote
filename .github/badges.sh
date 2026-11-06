#!/bin/sh
# Write the README's badges into docs/assets/badges/. GitHub shows an image from another site through a proxy that gives
# up after about four seconds, and a badge shields.io works out from GitHub's API took longer: the README showed it as a
# broken image. A file in the repository is served without that proxy. Run it after the release's number is set in
# server/version.py:
#
#   sh .github/badges.sh
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
dir=docs/assets/badges
mkdir -p "$dir"

version=$(sed -n 's/^VERSION = "\([0-9][0-9.]*\)".*/\1/p' server/version.py)
[ -n "$version" ] || { echo "server/version.py names no version" >&2; exit 1; }

# badge NAME SPEC writes shields.io's static badge SPEC (label-message-color, spaces as %20, "|" as %7C) to NAME.svg,
# whole or not at all
badge() {
  tmp="$dir/$1.svg.tmp"
  curl -fsS --retry 3 --max-time 30 -o "$tmp" "https://img.shields.io/badge/$2.svg"
  # an error page in place of a badge must not replace the one there is
  grep -q '<svg' "$tmp" || { echo "shields.io sent no SVG for $1" >&2; rm -f "$tmp"; exit 1; }
  mv "$tmp" "$dir/$1.svg"
}

badge release "release-v$version-ea7233"
badge license "license-MIT-2a78d6"
badge runs-on "runs%20on-Windows%20%7C%20Linux%20%7C%20macOS-555"
badge gpu "GPU-NVIDIA%20%7C%20AMD%20%7C%20none-555"

# the README's alt text says the same, for a reader without images
sed -i -e "s/alt=\"Release v[0-9][0-9.]*\"/alt=\"Release v$version\"/" README.md
echo "wrote $dir: release v$version"
