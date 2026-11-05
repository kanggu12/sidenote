#!/usr/bin/env bash
# compose.yaml's server and code runner on a network with no way out, set up as docs/air-gapped.md says, with real images:
# that nothing in them waits on the internet, and that everything the panel needs is in the image. compose.yaml is read
# through `docker compose config`, and only what would collide with a running Sidenote is changed (names), besides the network
# and the guide's own settings.
#
#   tests/offline_check.sh [server image] [runner image]      (default: what ./sidenote up built)
#
#   CHECK_PROJECT   the compose project's name, which every container and volume here starts with
#   CHECK_TREE      the checkout whose compose.yaml is read; default the one this file is in
#
# No model is here: the local model's own path is the guide's to walk with a real GPU. Everything goes away at the end.
set -uo pipefail                      # not -e: a failing check has to print and go on to the next

here="$(cd "$(dirname "$0")" && pwd)"
tree="${CHECK_TREE:-$here/..}"
server_image="${1:-sidenote:local}"
runner_image="${2:-sidenote-runner:local}"
project="${CHECK_PROJECT:-offline-check-$$}"
wait_for=120                          # seconds: a start that waits on the internet shows here as a start that does not end

pass=0 fail=0
ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }

work="$(mktemp -d)"
chmod 755 "$work"
home="$work/home"; logs="$work/logs"
mkdir -p "$home/.claude/backups" "$home/.claude/sessions" "$home/.codex" "$logs"

cache="$project-cache" unpacked="$project-unpacked"   # the speech bundle's two volumes, the last check's

compose() { docker compose -p "$project" -f "$work/compose.json" "$@"; }
cleanup() {
  compose down -v --remove-orphans > /dev/null 2>&1
  docker run --rm --name "$project-clean" --user 0:0 --entrypoint rm -v "$work:/w" "$server_image" -rf /w/home /w/logs /w/bundle > /dev/null 2>&1
  docker volume rm "$cache" "$unpacked" > /dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT

cpus="$(nproc)"; [ "$cpus" -lt 8 ] || cpus=8
env -u COMPOSE_FILE -u COMPOSE_PROFILES -u SIDENOTE_LOG_PATH DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}" HOME="$home" \
    SIDENOTE_UID="$(id -u)" SIDENOTE_GID="$(id -g)" SIDENOTE_LOG_PATH="$logs" SIDENOTE_CPUS="$cpus" TZ=UTC \
    docker compose -p "$project" --project-directory "$tree" -f "$tree/compose.yaml" config --format json > "$work/config.json" \
  || { echo "compose.yaml did not read"; exit 1; }
python3 - "$work/config.json" "$work/compose.json" "$server_image" "$runner_image" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
images = {"sidenote:local": sys.argv[3], "sidenote-runner:local": sys.argv[4]}
for svc in cfg["services"].values():
    svc.pop("build", None)            # the images are given
    svc.pop("container_name", None)   # compose's fixed names belong to a Sidenote that may be running here
    svc.pop("ports", None)            # a network with no way out publishes nothing: the checks ask from inside
    svc["image"] = images[svc["image"]]
# the settings the guide puts in .env
cfg["services"]["server"].setdefault("environment", {}).update(
    SIDENOTE_OFFLINE="1", SIDENOTE_AGENT="off", SIDENOTE_SEARCH_URL="", SIDENOTE_UPDATE_CHECK="0", HF_HUB_OFFLINE="1")
for net in cfg.get("networks", {}).values():
    net["internal"] = True            # no way out from any of them
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
PY

echo "project $project"
if ! compose up -d --quiet-pull > "$work/up.log" 2>&1; then
  bad "compose brings the server and the runner up" "$(tail -5 "$work/up.log")"
  printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"; exit 1
fi

# Asked from inside the server's container, as nothing is published
in_server() { compose exec -T server python -c "$1" 2>&1; }

began=$SECONDS health=""
until health="$(in_server "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8777/health', timeout=3).read().decode())")" \
      && [[ $health == "{"* ]]; do
  health=""
  if (( SECONDS - began > wait_for )); then break; fi
  sleep 1
done
if [ -n "$health" ]; then ok "the server answers within ${wait_for} s, $((SECONDS - began)) s here"
else
  bad "the server answers within ${wait_for} s" "$(compose logs --tail 15 server 2>&1 | tail -15)"
  printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"; exit 1
fi

# That this is the state it claims to be: a check of a network that can reach out would pass for the wrong reason
way_out="$(in_server "
import socket
try:
    socket.create_connection(('1.1.1.1', 443), 3); print('out')
except OSError as e:
    print('no way out')")"
if [ "$way_out" = "no way out" ]; then ok "the server's network has no way out"; else bad "the server's network has no way out" "$way_out"; fi

state="$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
a = (d.get('engines') or {}).get('agent') or {}
print('ok' if d.get('ok') and not a.get('ok') else 'not: %s' % a)" "$health")"
if [ "$state" = ok ]; then ok "it is up with no agent to go to"; else bad "it is up with no agent to go to" "$state"; fi

off="$(in_server "
from server.settings import SETTINGS
from server.updates import allowed
print('web' if SETTINGS.get('web_search') else '', 'update' if allowed() else '')" | tail -1 | tr -d ' ')"
if [ -z "$off" ]; then ok "web search and the release check are off, so nothing asks for them"
else bad "web search and the release check are off, so nothing asks for them" "still on: $off"; fi

# The page, and everything it loads by itself, from this server: scripts, styles and fonts. A link someone may press is no load
page="$(in_server "
import re, urllib.request as u
base = 'http://127.0.0.1:8777/'
html = u.urlopen(base, timeout=5).read().decode()
tags = re.findall(r'<(?:script|img|iframe|source)[^>]*\ssrc=\"([^\"]+)\"|<link[^>]*\shref=\"([^\"]+)\"', html)
wanted = [a or b for a, b in tags]
css = re.findall(r'@import[^;]*?(https?://[^\"\')]+)|url\(\s*[\"\']?(https?://[^\"\')]+)', html)
out = [w for w in wanted if re.match(r'(https?:)?//', w)] + [a or b for a, b in css]
missing = []
for w in wanted:
    if not re.match(r'(https?:|data:|//)', w):
        try:
            u.urlopen(base + w.lstrip('./'), timeout=5).read()
        except OSError as e:
            missing.append(w)
print(len(wanted), 'loaded', 'outside:', out, 'missing:', missing)")"
if [[ $page == *"outside: [] missing: []"* ]] && [[ $page != 0\ * ]]; then ok "the page loads all of its own from this server ($(cut -d' ' -f1 <<<"$page") files)"
else bad "the page loads all of its own from this server" "$page"; fi

# The speech model is not on this PC here: the server says so and goes on, where a start that downloads would have sat there
if grep -aq 'faster-whisper unavailable' "$logs/server.log" && compose ps --status running --services 2>/dev/null | grep -qx server; then
  ok "with no speech model the server says so and goes on"
else bad "with no speech model the server says so and goes on" "$(tail -5 "$logs/server.log" 2>&1)"; fi

if python3 -c "
import json, sys
sys.exit(0 if ((json.loads(sys.argv[1]).get('runner') or {}).get('ok')) else 1)" "$health"; then ok "the code runner is ready"
else
  sleep 8
  health="$(in_server "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8777/health', timeout=3).read().decode())")"
  if python3 -c "
import json, sys
sys.exit(0 if ((json.loads(sys.argv[1]).get('runner') or {}).get('ok')) else 1)" "$health"; then ok "the code runner is ready"
  else bad "the code runner is ready" "$health"; fi
fi

# The guide's speech bundle, from a cache laid out as the library leaves it: a snapshot's file is a link to the repo's blobs,
# and that a link to the store the repos share. Written with the guide's own arguments, it has to hold the file itself, as a
# link does not unpack on a Windows with no Developer Mode, and the library has to find it there with no network.
read -ra speech_args <<<"$(sed -n 's|^ *cf /out/speech\.tar ||p' "$tree/docs/air-gapped.md")"
mkdir -p "$work/bundle"
docker run --rm --network none --entrypoint sh -v "$cache:/v" "$server_image" -c '
  repo=/v/hub/models--Systran--faster-whisper-small rev=0123456789012345678901234567890123456789
  mkdir -p "$repo/refs" "$repo/blobs" "$repo/snapshots/$rev" /v/hub/blobs/42 /v/xet
  printf %s "$rev" > "$repo/refs/main"
  echo "the model" > /v/hub/blobs/42/abc
  ln -s ../../blobs/42/abc "$repo/blobs/abc"
  ln -s ../../blobs/abc "$repo/snapshots/$rev/model.bin"' > /dev/null 2>&1
docker run --rm --network none --entrypoint tar -v "$cache:/v:ro" -v "$work/bundle:/out" "$server_image" \
  cf /out/speech.tar "${speech_args[@]}" > "$work/bundle.log" 2>&1
listing="$(tar tvf "$work/bundle/speech.tar" 2>&1)"
inside="$(tar xOf "$work/bundle/speech.tar" --wildcards '*/snapshots/*/model.bin' 2>&1)"
if [ "${#speech_args[@]}" -gt 0 ] && ! grep -q '^l' <<<"$listing" && ! grep -q blobs <<<"$listing" && [ "$inside" = "the model" ]; then
  ok "the speech bundle holds the model's files, with no link and nothing twice"
else bad "the speech bundle holds the model's files, with no link and nothing twice" "${speech_args[*]}: $inside; $listing"; fi

docker run --rm --network none --entrypoint tar -v "$unpacked:/v" -v "$work/bundle:/in:ro" "$server_image" xf /in/speech.tar -C /v > /dev/null 2>&1
found="$(docker run --rm --network none -e HF_HOME=/data/hf -e HF_HUB_OFFLINE=1 -v "$unpacked:/data/hf" --entrypoint python "$server_image" -c "
from faster_whisper import download_model
print(open(download_model('small') + '/model.bin').read().strip())" 2>&1 | tail -1)"
if [ "$found" = "the model" ]; then ok "unpacked, the library finds that model with no network"
else bad "unpacked, the library finds that model with no network" "$found"; fi

printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"
[ "$fail" = 0 ]
