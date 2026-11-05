#!/usr/bin/env bash
# The server and the code runner brought up by compose.yaml as an ordinary user, with real images: what the launcher's
# stand-ins cannot show. A root with no capabilities cannot read another user's 600 file, so a change that only works as
# root passes every other suite and leaves anyone but root with no agent. The file's own constraints are what is tested:
# compose.yaml is read through `docker compose config`, and only what would collide with a running Sidenote is changed
# (the container names, the images' names, the published port).
#
#   tests/nonroot_check.sh [server image] [runner image]      (default: what ./sidenote up built)
#
#   CHECK_UID, CHECK_GID   the user to run as; default this user, or 1000 when this user is root (0 named here runs as root)
#   CHECK_PROJECT          the compose project's name, which every container and volume here starts with
#   CHECK_PORT             the port published on 127.0.0.1
#   CHECK_TREE             the checkout whose compose.yaml is read; default the one this file is in
#
# The login files are made up and no agent is asked anything over the network. Everything goes away at the end.
set -uo pipefail                      # not -e: a failing check has to print and go on to the next

here="$(cd "$(dirname "$0")" && pwd)"
tree="${CHECK_TREE:-$here/..}"
server_image="${1:-sidenote:local}"
runner_image="${2:-sidenote-runner:local}"
project="${CHECK_PROJECT:-nonroot-check-$$}"
port="${CHECK_PORT:-18777}"
uid="${CHECK_UID:-$(id -u)}"; gid="${CHECK_GID:-$(id -g)}"
if [ -z "${CHECK_UID:-}" ] && [ "$uid" = 0 ]; then uid=1000; gid=1000; fi   # as root the point would be lost, unless asked for
wait_for=240                                     # seconds; what ./sidenote up itself gives a first start

pass=0 fail=0
ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }
check() {                             # check <name> <command...>: passes when the command does, says what it printed
  local name="$1" out; shift
  if out="$("$@" 2>&1)"; then ok "$name"; else bad "$name" "$(tail -3 <<<"$out")"; fi
}

work="$(mktemp -d)"
chmod 755 "$work"                     # the path the mounts are reached by, for the stand-in user
home="$work/home"; logs="$work/logs"
mkdir -p "$home/.claude" "$home/.codex" "$logs"
# Made-up logins, each as the CLIs leave theirs: mode 600 and the user's
secret="made-up-$$"
printf '{"claudeAiOauth":{"accessToken":"%s","refreshToken":"%s","expiresAt":4102444800000,"scopes":["user:inference"]}}\n' \
  "$secret" "$secret" > "$home/.claude/.credentials.json"
printf '{"OPENAI_API_KEY":"%s"}\n' "$secret" > "$home/.codex/auth.json"
mkdir -p "$home/.claude/backups" "$home/.claude/sessions"   # what ./sidenote makes first (ensure_dirs)
chmod 600 "$home/.claude/.credentials.json" "$home/.codex/auth.json"
if [ "$(id -u)" = 0 ]; then chown -R "$uid:$gid" "$home" "$logs"; fi

compose() { docker compose -p "$project" -f "$work/compose.json" "$@"; }
cleanup() {
  compose down -v --remove-orphans > /dev/null 2>&1
  # what a container left under another owner, were the check to end before the folders were handed over
  docker run --rm --name "$project-clean" --user 0:0 --entrypoint rm -v "$work:/w" "$server_image" -rf /w/home /w/logs > /dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT

# compose.yaml as compose reads it, with this user passed in as the launcher passes it. HOME is the made-up one for this
# one command alone, where ${HOME} is filled in; the docker command's own plugins are found through DOCKER_CONFIG.
cpus="$(nproc)"; [ "$cpus" -lt 8 ] || cpus=8
env -u COMPOSE_FILE -u COMPOSE_PROFILES -u SIDENOTE_LOG_PATH DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}" HOME="$home" \
    SIDENOTE_UID="$uid" SIDENOTE_GID="$gid" SIDENOTE_LOG_PATH="$logs" SIDENOTE_CPUS="$cpus" TZ=UTC \
    docker compose -p "$project" --project-directory "$tree" -f "$tree/compose.yaml" config --format json > "$work/config.json" \
  || { echo "compose.yaml did not read"; exit 1; }
python3 - "$work/config.json" "$work/compose.json" "$server_image" "$runner_image" "$port" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
images = {"sidenote:local": sys.argv[3], "sidenote-runner:local": sys.argv[4]}
for svc in cfg["services"].values():
    svc.pop("build", None)            # the images are given
    svc.pop("container_name", None)   # compose's fixed names belong to a Sidenote that may be running here
    svc["image"] = images[svc["image"]]
    for published in svc.get("ports", []):
        published["published"] = sys.argv[5]
# no speech model to download, and no question to GitHub: neither is what this looks at
cfg["services"]["server"].setdefault("environment", {}).update(SIDENOTE_TRANSCRIBER="null", SIDENOTE_UPDATE_CHECK="0")
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
PY

# A log folder as an older image left it: turned over to root, with a file of root's in it
docker run --rm --name "$project-old" --user 0:0 --entrypoint sh -v "$logs:/l" "$server_image" \
  -c 'echo old > /l/old.log; chown -R 0:0 /l' > /dev/null 2>&1

echo "as uid $uid, gid $gid, project $project, port $port"
if ! compose up -d --quiet-pull > "$work/up.log" 2>&1; then
  bad "compose brings the server and the runner up" "$(tail -5 "$work/up.log")"
  printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"; exit 1
fi
url="http://127.0.0.1:$port"
began=$SECONDS health=""
until health="$(curl --noproxy '*' -fsS --max-time 3 "$url/health" 2>/dev/null)"; do
  if (( SECONDS - began > wait_for )); then break; fi
  sleep 1
done
if [ -n "$health" ]; then ok "the server answers /health"
else
  bad "the server answers /health" "$(compose logs --tail 15 server 2>&1 | tail -15)"
  printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"; exit 1
fi

server="$project-server-1"; runner="$project-runner-1"
in_server() { docker exec "$server" sh -c "$1"; }
owner() { stat -c %u "$1"; }

check "the server runs as the user" test "$(docker exec "$server" id -u):$(docker exec "$server" id -g)" = "$uid:$gid"
check "its HOME is /root" test "$(docker exec "$server" sh -c 'echo $HOME')" = /root
# The folder given back: as an older image left it, and what the server has written since
check "the log folder is the user's again" test "$(owner "$logs")" = "$uid"
check "...and the file an older image left in it" test "$(owner "$logs/old.log")" = "$uid"
check "the server wrote its log there, as the user" test "$(owner "$logs/server.log")" = "$uid"
# Every place it writes in, as the user
for place in /data/logs /data/hf /tmp /root /root/.claude /root/.codex /root/.claude/backups /root/.claude/sessions; do
  check "it can write in $place" in_server "touch $place/.written && rm $place/.written"
done
# Docker gives a named volume the image's owner again while it is empty, so the handover has to hold across a new container
docker run --rm --name "$project-again" --user "$uid:$gid" --entrypoint touch -v "${project}_hf-cache:/data/hf" "$server_image" \
  /data/hf/.again > /dev/null 2>&1
rc=$?; check "the speech model's volume stays the user's in the next container" test "$rc" = 0
# The login, the whole reason for this: a root with no capabilities gets "Permission denied" on both
check "it reads Claude Code's login" test "$(in_server 'cat /root/.claude/.credentials.json' 2>&1 | grep -c "$secret")" = 1
check "it reads Codex's login" test "$(in_server 'cat /root/.codex/auth.json' 2>&1 | grep -c "$secret")" = 1
check "the claude CLI runs" docker exec "$server" claude --version
check "the claude CLI finds its login" sh -c "docker exec '$server' claude auth status --json | grep -q '\"loggedIn\": *true'"
check "the codex CLI runs" docker exec "$server" codex --version
check "the codex CLI finds its login" sh -c "docker exec '$server' codex login status 2>&1 | grep -q 'API key configured'"
# What ./sidenote status prints comes from here: signed in on the PC and "login needed" from the server must not both be said
agent_ok() { curl --noproxy '*' -fsS --max-time 3 "$url/health" \
  | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['engines']['agent'].get('ok') else 1)" 2>/dev/null; }
for _ in $(seq 1 30); do agent_ok && break; sleep 1; done
check "the server says the agent is signed in" agent_ok
check "the login file is still the user's, mode 600" test "$(stat -c '%u %a' "$home/.claude/.credentials.json")" = "$uid 600"
check "what the CLI wrote in ~/.claude is the user's" test -z "$(find "$home" ! -uid "$uid" 2>/dev/null | head -1)"
# What the llm service writes as root, with this file's own volume and its umask
docker run --rm --name "$project-gpu" --user 0:0 --entrypoint sh -v "${project}_gpu-stat:/gpu" "$server_image" \
  -c 'echo "1,2,3,4,5" > /gpu/now.tmp && mv -f /gpu/now.tmp /gpu/now.csv' > /dev/null 2>&1
check "it reads what the GPU's writer left" test "$(in_server 'cat /gpu/now.csv')" = "1,2,3,4,5"
check "it reads every file of the panel" test -z "$(in_server 'find /app/panel /app/server ! -readable' 2>&1)"
check "the panel's page is served" sh -c "curl --noproxy '*' -fsS --max-time 5 '$url/' | grep -qi '<html'"
# The code runner, through its socket: reachable from the server, closed to a run, and its own health check still works
check "the server reaches the code runner" python3 -c "import json,sys; sys.exit(0 if json.loads(sys.argv[1])['runner']['ok'] else 1)" "$health"
check "the runner's own health check answers" docker exec "$runner" python3 -I /app/runner.py --health
post='
import http.client, json, socket, sys
class C(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.connect("/sock/runner.sock")
c = C("runner", timeout=60)
c.request("POST", "/run", json.dumps({"lang": "python", "code": sys.argv[1], "stdin": "", "timeout": 10}), {"Content-Type": "application/json"})
print(json.loads(c.getresponse().read()).get("stdout", ""))
'
said="$(docker exec "$server" python -c "$post" 'import os; print("ran as", os.getuid())' 2>&1)"
if [[ $said == "ran as 101"* ]]; then ok "a run goes through the socket, as a run's user"; else bad "a run goes through the socket, as a run's user" "$said"; fi
said="$(docker exec "$server" python -c "$post" '
import socket
try:
    socket.socket(socket.AF_UNIX).connect("/sock/runner.sock"); print("connected")
except OSError as e:
    print(type(e).__name__)' 2>&1)"
if [ "$said" = PermissionError ]; then ok "a run cannot open the socket"; else bad "a run cannot open the socket" "$said"; fi

printf '  ==== %d ok, %d FAIL\n' "$pass" "$fail"
[ "$fail" = 0 ]
