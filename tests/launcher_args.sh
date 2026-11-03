#!/usr/bin/env bash
# What ./sidenote hands to Windows, and how it behaves when one of the things it asks is missing or broken.
#
# It runs the launcher itself (a copy of it, in a folder of its own), with every outside program stood in for:
# cmd.exe, powershell.exe, curl and docker are small scripts that write down the arguments they were given and
# act out the few answers the launcher needs. Nothing reaches Windows, Docker or the running server, and the
# capture program is never started. `claude` is not on the PATH here, as on a PC without Claude Code.
#
#   bash tests/launcher_args.sh [path to the launcher]      (default: this checkout's ./sidenote)
#
# What it covers (each line of output is one check):
# - capture options reach capture.py as the words they were typed, a value with spaces in it whole and with no
#   quote characters added, in the windowless start, with --console and with --up (the windowless start used
#   to wrap each one in literal quotes, which WSL passes on, so argparse refused every option; --console and
#   --up split a value with spaces into several words);
# - a character cmd.exe takes for itself (&) is refused before cmd.exe sees it;
# - `up` works without Claude Code installed (it used to end at once with status 127 and no message);
# - SIDENOTE_ANALYZER is read the way the server reads it (any case), so the local model's containers start;
# - a Windows process query that fails is not read as "a capture program is running";
# - the processes capture-stop ends are named exactly (a py*.exe pattern also matched pycharm64.exe);
# - `capture --up` shows why the server could not start (it used to discard every word of it);
# - a missing tray package (pystray) is said, and `install` installs it;
# - --once runs in the terminal, and --no-tray says how the windowless program is ended;
# - the desktop shortcut runs client/launch.pyw with Windows Python's windowless pyw.exe, not wsl.exe in a console
#   window of its own (that window used to come up on every start), and is not made without pyw.exe;
# - launch.pyw runs `./sidenote capture --up` through wsl.exe as a login shell, shows nothing when that works, and
#   when it fails shows the reason in a message box (printed here, with --dry-run): the last lines, without
#   terminal colour codes, wsl.exe's own UTF-16 messages readable, capture options passed on as typed;
# - `capture --up` with no terminal (as launch.pyw runs it) ends with a failing status and waits for no key;
# - the language: the checks above read the Korean words (SIDENOTE_LANG=ko), which are the words the launcher had
#   before it spoke English too. With SIDENOTE_LANG=en every command prints no Korean, a locale picks the language when
#   SIDENOTE_LANG is not set, a SIDENOTE_LANG that is set is handed on to the Windows programs (WSLENV), and launch.pyw's
#   boxes follow the same rule;
# - with no COMPOSE_FILE set, the GPU picks compose.yaml's companion file, and one that is set is left alone;
# - the CI check is opt-in: without SIDENOTE_CI_GATE=1 nothing asks gh and no CI line is printed; with it a commit CI
#   failed is refused, --no-ci and --when-green work, and doctor never fails for CI;
# - setup-capture (and its old name setup-windows) installs the capture packages, a .venv-capture left without pip is
#   made again, and install without Windows Python names python.org and still runs its other steps;
# - Docker's own reason reaches the user: the docker group, the NVIDIA Container Toolkit;
# - with no GPU that fits a model, llm pull, install, doctor and status say one and the same line;
# - status names the engines as the panel does, uninstall on a Linux desktop lists and removes what it made there, and
#   help names the start commands, setup-capture, the capture options and the CI switch.
set -uo pipefail                      # not -e: a failing check has to print and go on to the next

here="$(cd "$(dirname "$0")" && pwd)"             # this script's folder, whatever the caller's cwd
root="$(cd "$here/.." && pwd)"                    # the checkout, where ./sidenote lives (this file is in tests/)
launcher="$(readlink -f "${1:-$root/sidenote}")"  # the launcher under test (an older copy can be passed in)
launch_pyw="$(dirname "$launcher")/client/launch.pyw"   # the shortcut's starter from the same tree (none before it)
distro="${WSL_DISTRO_NAME:-Ubuntu}"               # the distribution the launcher and the shortcut name
work="$(mktemp -d)"                               # the stand-ins, their records and a copy of the launcher
trap 'rm -rf "$work"' EXIT                        # and go away however this ends

pass=0 fail=0                                     # the two counters the last line reports
ok()   { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }

# --- the stand-ins ---------------------------------------------------------------------------------------
mkdir -p "$work/bin" "$work/calls" "$work/state" "$work/home" "$work/logs" "$work/repo/client"
cp "$launcher" "$work/repo/sidenote"              # the launcher cds to its own folder: this one
: > "$work/repo/client/capture.py"                # it only has to exist; nothing runs it
# The GPU the launcher reads (server/hardware.py) stood in for: the one named in state/gpu ("vendor,name,GB"), or none.
# server/models.py is the real one, so what fits a GPU is what the launcher would really pull.
mkdir -p "$work/repo/server"
cp "$root/server/models.py" "$work/repo/server/models.py"
cat > "$work/repo/server/hardware.py" <<'STUB'
"""Stand-in for server/hardware.py: the GPU named in $FAKE/state/gpu as "vendor,name,GB", or no GPU at all."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Gpu:
    vendor: str
    name: str
    memory_gb: float


def detect():
    try:
        vendor, name, gb = open(os.path.join(os.environ["FAKE"], "state", "gpu")).read().strip().split(",")
    except (OSError, KeyError, ValueError):
        return []
    return [Gpu(vendor, name, float(gb))]


def best(gpus):
    return max(gpus, key=lambda g: g.memory_gb) if gpus else None
STUB
# A repository with one commit: with SIDENOTE_CI_GATE=1 the launcher asks gh about the commit it is on (git rev-parse)
git -C "$work/repo" init -q && git -C "$work/repo" add -A \
  && git -C "$work/repo" -c user.name=t -c user.email=t@t commit -qm "the launcher under test"

# cmd.exe: writes its argv down (one record per argument, NUL-separated, so a value with spaces stays whole)
# and answers what the launcher asks Windows Python: its version, whether the capture packages import (and
# whether the tray package is there), pip, and the two ways the capture program is started.
cat > "$work/bin/cmd.exe" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/cmd.$(date +%s%N)"
printf '%s|%s' "${WSLENV:-}" "${SIDENOTE_LANG:-}" > "$FAKE/state/cmd-lang"   # what would cross into Windows, and its value
shift                                             # /c
case "$1" in
  py)
    # no Python for Windows: cmd.exe's own words, on stderr, and a failing status
    [ -f "$FAKE/state/no-py" ] && { echo "'py' is not recognized as an internal or external command," >&2; exit 1; }
    case "$3" in
      --version) echo "Python 3.14.0" ;;
      -c) [ -f "$FAKE/state/no-packages" ] && exit 1   # an import failed
          cat "$FAKE/state/tray" 2>/dev/null || echo tray ;;
      -m) echo "Successfully installed pystray" ;;    # setup-windows
      *) echo "[main] the capture program would run here" ;;   # --console, --list-monitors
    esac ;;
  start) touch "$FAKE/state/running" ;;           # the windowless start: the program is now there
esac
exit 0
STUB

# powershell.exe: counts the capture programs (1 once one was started), ends them, and answers the desktop
# shortcut's two questions. With state/ps-broken it prints nothing and fails, as a broken WMI query does.
cat > "$work/bin/powershell.exe" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/ps.$(date +%s%N)"
[ -f "$FAKE/state/ps-broken" ] && exit 1
case "$3" in
  *Stop-Process*) [ -f "$FAKE/state/unkillable" ] || rm -f "$FAKE/state/running" ;;
  *.Count*) if [ -f "$FAKE/state/running" ]; then echo 1; else echo 0; fi ;;
  *GetFolderPath*) echo 'C:\Users\fake\Desktop' ;;
  *Get-Command*pyw*) [ -f "$FAKE/state/no-pyw" ] || echo 'C:\WINDOWS\pyw.exe' ;;
  *Test-Path*) echo y ;;
esac
exit 0
STUB

# curl: the server's /health (a capture program counts as connected once it was started) and /capture/quit.
# With state/server-down every request fails the way curl does when nothing listens.
cat > "$work/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/curl.$(date +%s%N)"
[ -f "$FAKE/state/server-down" ] && exit 7
case "$*" in
  */capture/quit*) [ -f "$FAKE/state/unkillable" ] || rm -f "$FAKE/state/running"; echo '{"asked": 1}' ;;
  # state/health.json, when a check wrote one, is the answer as it stands (the engines' states the status reads)
  */health*) if [ -f "$FAKE/state/health.json" ]; then cat "$FAKE/state/health.json"; exit 0; fi
             n=0; [ -f "$FAKE/state/running" ] && n=1
             printf '{"ok": true, "audio": true, "paused": false, "engines": {"ready": true}, '
             printf '"capture": {"clients": %d, "screen_on": true, "audio_on": true}}\n' "$n" ;;
esac
exit 0
STUB

# docker: everything succeeds and changes nothing; `info` fails with state/docker-off, and with state/docker-denied
# the way it does for a user outside the docker group (its real words, on stderr). `version` names a server, and with
# state/no-toolkit `compose up` fails as it does when Docker cannot reach the NVIDIA GPU. Each call also notes the
# compose profiles it was given, which is how the local model's containers are switched on.
cat > "$work/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/docker.$(date +%s%N)"
echo "${COMPOSE_PROFILES:-}" >> "$FAKE/state/profiles"
case "$1" in
  info) [ -f "$FAKE/state/docker-off" ] && exit 1
        if [ -f "$FAKE/state/docker-denied" ]; then
          echo "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" >&2; exit 1
        fi ;;
  version) [ -f "$FAKE/state/docker-off" ] || [ -f "$FAKE/state/docker-denied" ] || echo "29.0.0" ;;
  inspect) echo true ;;
  compose) if [ -f "$FAKE/state/no-toolkit" ] && printf '%s\n' "$@" | grep -qx up; then
             echo 'Error response from daemon: could not select device driver "nvidia" with capabilities: [[gpu]]' >&2; exit 1
           fi ;;
esac
exit 0
STUB
# gh: writes down that it was asked, and answers what CI said of the commit as the launcher's --jq prints it
# (state/gh-answer: success, failure, running). Only a launcher with SIDENOTE_CI_GATE=1 may ask it at all.
cat > "$work/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/gh.$(date +%s%N)"
cat "$FAKE/state/gh-answer" 2>/dev/null
exit 0
STUB
# pgrep and pkill, for the runs as a Linux desktop: this checkout's capture programs are counted from
# state/linux-capture, and no process of this machine is ever looked at or ended.
cat > "$work/bin/pgrep" <<'STUB'
#!/usr/bin/env bash
if [ -f "$FAKE/state/linux-capture" ]; then echo 1; else echo 0; exit 1; fi
STUB
cat > "$work/bin/pkill" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/pkill.$(date +%s%N)"
rm -f "$FAKE/state/linux-capture"
STUB
# python3, on the PATH of the Linux setup checks alone: `-m venv` makes a .venv-capture whose python has pip or, with
# state/no-ensurepip, fails halfway as Debian's python3 does without python3-venv, leaving a python and no pip.
# Anything else goes to the real python3 (the launcher reads JSON and the GPU with it).
mkdir -p "$work/venvbin"
cat > "$work/venv-python" <<'STUB'
#!/usr/bin/env bash
# the python of a .venv-capture the stand-in made: pip only where the marker beside it says pip was installed
venv="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = -m ] && [ "${2:-}" = pip ]; then
  [ -f "$venv/pip-ok" ] || { echo "$venv/bin/python: No module named pip" >&2; exit 1; }
  printf '%s\0' "$@" > "$FAKE/calls/pip.$(date +%s%N)"
  echo "pip 24.0"; exit 0
fi
echo tray                                         # the capture packages' question: all there
STUB
cat > "$work/venvbin/python3" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
  printf '%s\0' "$@" > "$FAKE/calls/venv.$(date +%s%N)"
  dir="${*: -1}"                                  # the folder is the last argument
  rm -rf "$dir"; mkdir -p "$dir/bin"; cp "$FAKE/venv-python" "$dir/bin/python"; chmod +x "$dir/bin/python"
  if [ -f "$FAKE/state/no-ensurepip" ]; then
    echo "The virtual environment was not created successfully because ensurepip is not available." >&2; exit 1
  fi
  touch "$dir/pip-ok"; exit 0
fi
exec @PYTHON3@ "$@"
STUB
sed -i "s#@PYTHON3@#$(command -v python3)#" "$work/venvbin/python3"
chmod +x "$work/venvbin/python3"
# wsl.exe, for client/launch.pyw: writes down its arguments and the WSL_UTF8 it was started with, then does what the
# real one does with `-d <distro> --exec <program> <arguments...>`: runs that program with exactly those arguments
# (here, already inside WSL, with the stand-ins first on the PATH). state/wsl-noisy has it print what a terminal
# program prints (colour codes, a window title, a progress line redrawn with \r, more lines than a message box
# shows) and fail; state/wsl-utf16 has it fail the way wsl.exe itself does, with its message in UTF-16.
cat > "$work/bin/wsl.exe" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/wsl.$(date +%s%N)"
printf '%s' "${WSL_UTF8:-}" > "$FAKE/state/wsl-utf8"
printf '%s' "${WSLENV:-}" > "$FAKE/state/wsl-wslenv"
if [ -f "$FAKE/state/wsl-noisy" ]; then
  printf '\033]0;Sidenote Capture\007'
  for i in $(seq 1 30); do printf '  \033[32m✓\033[0m 줄 %d\n' "$i"; done
  printf '  내려받는 중 10%%\r  내려받는 중 100%%\n'
  printf '\033[31m마지막 줄: 서버를 띄우지 못했습니다\033[0m\n' >&2
  exit 2
fi
if [ -f "$FAKE/state/wsl-utf16" ]; then
  printf 'There is no distribution with the supplied name.\r\n제공된 이름의 배포가 없습니다.\r\n' | iconv -f UTF-8 -t UTF-16LE
  exit 255
fi
while [ $# -gt 0 ]; do
  case "$1" in
    -d|--distribution|--shell-type) shift 2 ;;
    --cd) cd "$2" || exit 1; shift 2 ;;
    -e|--exec) shift; exec "$@" ;;
    --) shift; exec bash -c "$*" ;;
    *) echo "wsl.exe stand-in: unexpected argument $1" >&2; exit 1 ;;
  esac
done
exit 1
STUB
chmod +x "$work/bin/"*

# One run of the launcher copy, everything outside it stood in for. HOME and the log folder are scratch, the
# PATH holds the stand-ins and the system's own tools only (no claude, no Windows folders), stdin is empty
# (no terminal, so nothing waits for a key) and the output is kept for the checks. In Korean unless EXTRA_ENV says
# otherwise (a later SIDENOTE_LANG= wins, and an empty one leaves the choice to the locale).
run() {
  rm -rf "$work/calls"/* && mkdir -p "$work/calls"
  env -i PATH="$work/bin:/usr/bin:/bin" HOME="$work/home" FAKE="$work" WSL_DISTRO_NAME="${WSL_DISTRO_NAME:-Ubuntu}" \
      SIDENOTE_LOG_PATH="$work/logs" SIDENOTE_LANG=ko ${EXTRA_ENV:-} \
      timeout 60 bash "$work/repo/sidenote" "$@" > "$work/out" 2>&1 < /dev/null
  echo $? > "$work/rc"
}
state() { rm -f "$work/state"/*; for s in "$@"; do touch "$work/state/$s"; done; }   # set the stand-ins' mood
# One run of client/launch.pyw the way the shortcut runs it, but with --dry-run (it prints the message box it would
# show) and the wsl.exe stand-in for the real one. Linux Python stands in for Windows Python: the file needs Windows
# only for the box itself, the no-window flag and its one-at-a-time lock. WSL_BIN names another wsl.exe.
run_launch() {
  rm -rf "$work/calls"/* && mkdir -p "$work/calls"
  env -i PATH="$work/bin:/usr/bin:/bin" HOME="$work/home" FAKE="$work" WSL_DISTRO_NAME="$distro" \
      SIDENOTE_LOG_PATH="$work/logs" SIDENOTE_LANG=ko ${EXTRA_ENV:-} \
      timeout 60 python3 "$launch_pyw" --dry-run --wsl "${WSL_BIN:-$work/bin/wsl.exe}" --distro "$distro" \
      --repo "$work/repo" "$@" > "$work/out" 2>&1 < /dev/null
  echo $? > "$work/rc"
}
# The text of the message box the last run_launch would have shown, between the lines --dry-run puts around it.
box_text() { sed -n '/^\[dry-run\] text:$/,/^\[dry-run\] end of text$/p' "$work/out" | sed '1d;$d'; }
# The arguments of the last recorded call of one stand-in that has the given word as one of its arguments
# (last_call) or anywhere inside one of them (last_call_with), into the array CALL; empty when there is none.
calls_of() { ls "$work/calls/$1".* 2>/dev/null | sort; }    # the records are named by the time they were made
last_call() {   # $1 = cmd|ps|curl|docker, $2 = a whole argument the call holds
  local f found=""
  for f in $(calls_of "$1"); do tr '\0' '\n' < "$f" | grep -qxF -- "$2" && found="$f"; done
  CALL=(); [ -n "$found" ] && mapfile -d '' -t CALL < "$found"
  return 0
}
last_call_with() {   # $1 = cmd|ps|curl|docker, $2 = text inside one of the call's arguments
  local f found=""
  for f in $(calls_of "$1"); do tr '\0' '\n' < "$f" | grep -qF -- "$2" && found="$f"; done
  CALL=(); [ -n "$found" ] && mapfile -d '' -t CALL < "$found"
  return 0
}
# What follows the given argument in CALL, as one string with each word in <>, for a readable comparison.
after() { local i out=""; for ((i = 0; i < ${#CALL[@]}; i++)); do [ "${CALL[$i]}" = "$1" ] && break; done
          for ((i += 2; i < ${#CALL[@]}; i++)); do out="$out<${CALL[$i]}>"; done; printf '%s' "$out"; }
said() { grep -qF -- "$1" "$work/out"; }          # the launcher printed this
wait_started() { for _ in $(seq 1 40); do [ -f "$work/state/running" ] && return 0; sleep 0.1; done; return 1; }

echo "launcher_args ($launcher)"
want='<--monitor><2><--audio-device><Realtek USB2.0 Audio>'

# 1. The windowless start: what pyw gets after the launcher's own --server and --log.
state; run capture --monitor 2 --audio-device "Realtek USB2.0 Audio"; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "$want" ] && ok "windowless start passes the options as typed" \
  || bad "windowless start passes the options as typed" "got $got"

# 2. --console: the same options after --server, and --console itself not passed on.
state; run capture --console --monitor 2 --audio-device "Realtek USB2.0 Audio"
last_call cmd -u; got="$(after --server)"
[ "$got" = "$want" ] && ok "--console passes the options as typed" || bad "--console passes the options as typed" "got $got"

# 3. --up (what the desktop shortcut uses), with a Korean device name in parentheses, the way Windows names it.
state; run capture --up --audio-device "스피커 (Realtek USB2.0 Audio)"; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "<--audio-device><스피커 (Realtek USB2.0 Audio)>" ] && ok "--up passes the options as typed, without --up" \
  || bad "--up passes the options as typed, without --up" "got $got"

# 4. --list-monitors goes to capture.py directly; the launcher's own --console must not go with it.
state; run capture --console --list-monitors
last_call cmd --list-monitors
if [ ${#CALL[@]} -gt 0 ] && ! printf '%s\n' "${CALL[@]}" | grep -qx -- --console; then ok "--list-monitors is passed on without --console"
else bad "--list-monitors is passed on without --console" "got ${CALL[*]:-no call}"; fi

# 5. A character cmd.exe would act on: the launcher says so instead of letting cmd.exe run part of it.
state; run capture --audio-device "R&B"
last_call cmd start
if [ ${#CALL[@]} = 0 ] && [ "$(cat "$work/rc")" != 0 ]; then ok "a value with & is refused before cmd.exe sees it"
else bad "a value with & is refused before cmd.exe sees it" "rc $(cat "$work/rc"), started: ${#CALL[@]}"; fi

# 6. up on a PC without Claude Code: it must reach docker compose up and finish.
state; run up
last_call docker up
if [ "$(cat "$work/rc")" = 0 ] && [ ${#CALL[@]} -gt 0 ]; then ok "up works without claude installed"
else bad "up works without claude installed" "rc $(cat "$work/rc"), compose up called: ${#CALL[@]}"; fi

# 7. SIDENOTE_ANALYZER in another case: the server reads it as local, so the local profile has to be on too.
state; EXTRA_ENV="SIDENOTE_ANALYZER=Local" run up
if grep -q local "$work/state/profiles" 2>/dev/null; then ok "SIDENOTE_ANALYZER=Local turns the local profile on"
else bad "SIDENOTE_ANALYZER=Local turns the local profile on" "profiles: $(sort -u "$work/state/profiles" 2>/dev/null | tr '\n' ' ')"; fi

# 8. The Windows process query fails: capture must not refuse to start as if one were already running.
state ps-broken; run capture; wait_started
if ! said "이미 실행 중" && [ -f "$work/state/running" ]; then ok "a failed process query does not block capture"
else bad "a failed process query does not block capture" "$(tail -2 "$work/out" | tr '\n' ' ')"; fi

# 9. The same failure in status, with nothing connected: it must not say a capture program is reconnecting.
state ps-broken; run status
if ! said "다시 연결 중"; then ok "a failed process query is not reported as reconnecting"
else bad "a failed process query is not reported as reconnecting" "$(grep -F "캡처 프로그램" "$work/out")"; fi

# 10. What capture-stop asks PowerShell to end: the interpreters by their exact names, never a pattern.
state running; run capture-stop
last_call_with ps Stop-Process; stop="${CALL[2]:-}"     # powershell.exe -NoProfile -Command <the query>
# (The path pattern '*...capture.py*' holds "py*" too, so the name pattern itself is what is looked for.)
if [ -n "$stop" ] && ! grep -qF "py*.exe" <<<"$stop" && grep -qF "'pythonw.exe'" <<<"$stop"; then
  ok "capture-stop names the interpreters exactly"
else bad "capture-stop names the interpreters exactly" "query: ${stop:-none}"; fi

# 11. capture-stop when one will not end: it says how many are left, as the user guide says.
state running unkillable; run capture-stop
if said "1개"; then ok "capture-stop says how many are left"; else bad "capture-stop says how many are left" "$(tail -1 "$work/out")"; fi

# 12. capture --up with Docker off (after a reboot): the reason has to be on screen.
state server-down docker-off; run capture --up
if said "Docker에 연결할 수 없습니다"; then ok "capture --up shows why the server could not start"
else bad "capture --up shows why the server could not start" "output: $(tr '\n' ' ' < "$work/out" | head -c 160)"; fi

# 13. No tray package: the windowless start says there will be no icon, and install installs it.
state; echo notray > "$work/state/tray"; run capture; wait_started
if said "pystray"; then ok "capture says the tray icon is missing"; else bad "capture says the tray icon is missing" "$(tail -3 "$work/out" | tr '\n' ' ')"; fi
state; echo notray > "$work/state/tray"; run install
last_call cmd pip
if [ ${#CALL[@]} -gt 0 ]; then ok "install installs the packages when only the tray one is missing"
else bad "install installs the packages when only the tray one is missing" "$(grep -F "2/4" -A1 "$work/out" | tail -1)"; fi

# 14. --once sends one screen and ends: it runs in this terminal (the --console form), where what it did is
#     printed, rather than windowless, where it could be gone before the start was seen.
state; run capture --once
last_call cmd -u; got="$(after --server)"
[ "$got" = "<--once>" ] && ok "--once runs in this terminal" || bad "--once runs in this terminal" "got ${got:-no console call}"

# 15. --no-tray, windowless: neither a window nor an icon, so the launcher says how it is ended.
state; run capture --no-tray; wait_started
if said "트레이 아이콘 없이" && said "capture-stop"; then ok "--no-tray says how the program is ended"
else bad "--no-tray says how the program is ended" "$(tail -3 "$work/out" | tr '\n' ' ')"; fi

# 16. The desktop shortcut starts the capture program with no window at all: Windows Python's windowless launcher,
#     pyw.exe, runs client/launch.pyw, which runs wsl.exe without a console. The shortcut used to start wsl.exe
#     itself, and wsl.exe opens a console window for the launcher on every start. Its arguments must not hold
#     capture.py's path either: capture and capture-stop find the capture program by that path.
state; run shortcut
last_call_with ps CreateShortcut; script="${CALL[2]:-}"
target="$(sed -n 's/^.*$s\.TargetPath = \(.*\);$/\1/p' <<<"$script")"
args="$(sed -n 's/^.*$s\.Arguments = \(.*\);$/\1/p' <<<"$script")"
want_args="'-3 \"$(wslpath -w "$work/repo/client/launch.pyw")\" --distro $distro --repo \"$work/repo\"'"
if [ "$target" = "'C:\WINDOWS\pyw.exe'" ] && [ "$args" = "$want_args" ] && [[ $args != *capture.py* ]]; then
  ok "the shortcut runs launch.pyw with pyw.exe, not wsl.exe"
else bad "the shortcut runs launch.pyw with pyw.exe, not wsl.exe" "target ${target:-none}, arguments ${args:-none}"; fi

# 17. Without pyw.exe (no Windows Python) the shortcut would have nothing to run: none is made, and it says why.
state no-pyw; run shortcut
last_call_with ps CreateShortcut
if [ "$(cat "$work/rc")" != 0 ] && [ ${#CALL[@]} = 0 ] && said "pyw"; then ok "without pyw.exe no shortcut is made, and it says why"
else bad "without pyw.exe no shortcut is made, and it says why" "rc $(cat "$work/rc"), shortcut written: $([ ${#CALL[@]} -gt 0 ] && echo yes || echo no), $(tail -1 "$work/out")"; fi

# 18. launch.pyw with everything working: the launcher ran in WSL through wsl.exe, in a login shell (bash -l, so
#     ~/.profile puts Claude Code on the PATH, as in a terminal), wsl.exe was asked for UTF-8, the capture program
#     was started, and nothing is shown.
state; run_launch
last_call wsl --exec
if [ "$(cat "$work/rc")" = 0 ] && grep -qx '\[dry-run\] box: none' "$work/out" && [ -f "$work/state/running" ] \
   && [ "${CALL[*]:0:5}" = "-d $distro --exec bash -lc" ] && [ "$(cat "$work/state/wsl-utf8" 2>/dev/null)" = 1 ]; then
  ok "launch.pyw starts the capture program and shows nothing"
else bad "launch.pyw starts the capture program and shows nothing" "rc $(cat "$work/rc"), wsl ${CALL[*]:0:5}, $(tail -2 "$work/out" | tr '\n' ' ')"; fi

# 19. launch.pyw when the server cannot start (Docker off after a reboot): a warning box with the reason, the
#     launcher's failing status, and no "press Enter" (there is no window to keep open).
state server-down docker-off; run_launch
text="$(box_text)"
if [ "$(cat "$work/rc")" != 0 ] && grep -qx '\[dry-run\] box: warning' "$work/out" \
   && grep -qx '\[dry-run\] title: Sidenote 캡처를 시작하지 못했습니다' "$work/out" \
   && grep -qF "Docker에 연결할 수 없습니다" <<<"$text" && ! said "Enter를 누르면"; then
  ok "launch.pyw shows why the server could not start"
else bad "launch.pyw shows why the server could not start" "rc $(cat "$work/rc"), $(tr '\n' ' ' < "$work/out" | head -c 200)"; fi

# 20. What the box shows is cleaned: no colour codes, window titles or carriage returns (a redrawn progress line
#     shows as it last read), only the last lines with a word on where the rest is, and the launcher's status.
state wsl-noisy; run_launch
text="$(box_text)"
if [ "$(cat "$work/rc")" = 2 ] && ! grep -q $'[\x1b\x07\r]' <<<"$text" && grep -qx "마지막 줄: 서버를 띄우지 못했습니다" <<<"$text" \
   && grep -qx "내려받는 중 100%" <<<"$text" && ! grep -q "내려받는 중 10%$" <<<"$text" \
   && grep -qx "✓ 줄 30" <<<"$text" && ! grep -qx "✓ 줄 17" <<<"$text" && grep -qF "./sidenote capture --up" <<<"$text"; then
  ok "launch.pyw shows the last lines, cleaned"
else bad "launch.pyw shows the last lines, cleaned" "rc $(cat "$work/rc"), text: $(head -c 300 <<<"$text" | cat -v | tr '\n' '|')"; fi

# 21. Capture options after the `--` reach capture.py as typed, a Korean device name with spaces and parentheses whole.
state; run_launch -- --audio-device "스피커 (Realtek USB2.0 Audio)" --monitor 2; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "<--audio-device><스피커 (Realtek USB2.0 Audio)><--monitor><2>" ] && ok "launch.pyw passes capture options on as typed" \
  || bad "launch.pyw passes capture options on as typed" "got ${got:-no start}, $(tail -1 "$work/out")"

# 22. No wsl.exe to run (WSL not installed): a warning box that names it.
state; WSL_BIN="$work/nowhere/wsl.exe" run_launch
if [ "$(cat "$work/rc")" != 0 ] && grep -qx '\[dry-run\] box: warning' "$work/out" && grep -qF "wsl.exe" <<<"$(box_text)"; then
  ok "launch.pyw says when wsl.exe cannot be run"
else bad "launch.pyw says when wsl.exe cannot be run" "rc $(cat "$work/rc"), $(tail -2 "$work/out" | tr '\n' ' ')"; fi

# 23. wsl.exe's own messages (a distribution that is gone) are UTF-16 unless WSL_UTF8 is honoured: still readable,
#     in English and in Korean (a Korean Windows writes them in Korean, with few of the NUL bytes English has).
state wsl-utf16; run_launch
if [ "$(cat "$work/rc")" != 0 ] && grep -qx "There is no distribution with the supplied name." <<<"$(box_text)" \
   && grep -qx "제공된 이름의 배포가 없습니다." <<<"$(box_text)"; then
  ok "launch.pyw reads wsl.exe's UTF-16 messages"
else bad "launch.pyw reads wsl.exe's UTF-16 messages" "$(box_text | head -2 | cat -v | tr '\n' '|')"; fi

# 24. What launch.pyw relies on: `capture --up` with no terminal fails with a status, and asks for no key.
state server-down docker-off; run capture --up
if [ "$(cat "$work/rc")" != 0 ] && ! said "Enter를 누르면"; then ok "capture --up with no terminal fails with a status and waits for no key"
else bad "capture --up with no terminal fails with a status and waits for no key" "rc $(cat "$work/rc"), $(tail -1 "$work/out")"; fi

# --- the language --------------------------------------------------------------------------------------
hangul() { python3 -c 'import re, sys; sys.exit(0 if re.search("[가-힣]", open(sys.argv[1], encoding="utf-8", errors="replace").read()) else 1)' "$1"; }

# 25. SIDENOTE_LANG=en: every command, in the states that make it say something, prints no Korean (and does print).
#     Each case is "<stand-ins' mood>|<command and its arguments>"; "notray" has Windows Python without pystray.
cases=("|help" "|bogus" "|up --bogus" "running|status" "ps-broken|status" "server-down|status" "|doctor" "|version"
       "|uninstall" "running|capture-stop" "running unkillable|capture-stop" "|capture-restart" "|capture --no-tray"
       "notray|capture" "|capture --audio-device R&B" "|capture --once" "server-down docker-off|capture --up" "|shortcut"
       "no-pyw|shortcut" "|shortcut --remove" "|login" "|login codex" "|login anthropic-api" "|llm" "|open" "|install"
       "|qa" "|down" "|restart" "|logs" "|gpu off" "|stats" "|setup-capture" "|setup-windows" "no-py|setup-capture"
       "|llm pull" "docker-denied|up" "no-toolkit|up" "|up --when-green" "|gpu status")
korean=() silent=()
for c in "${cases[@]}"; do
  read -r -a mood <<<"${c%%|*}"; read -r -a cmd <<<"${c#*|}"
  state "${mood[@]}"; [ -f "$work/state/notray" ] && echo notray > "$work/state/tray"
  EXTRA_ENV="SIDENOTE_LANG=en" run "${cmd[@]}"
  # The shortcut's old file name is a name on the desktop, not a word of the launcher's (the stand-in finds every file)
  sed -i 's/Sidenote 캡처\.lnk/OLD-SHORTCUT/g' "$work/out"
  if hangul "$work/out"; then korean+=("${c#*|}: $(grep -m1 -P '[\x{AC00}-\x{D7A3}]' "$work/out" 2>/dev/null || head -c 120 "$work/out")"); fi
  [ -s "$work/out" ] || silent+=("${c#*|}")
done
if [ ${#korean[@]} = 0 ] && [ ${#silent[@]} = 0 ]; then ok "with SIDENOTE_LANG=en, ${#cases[@]} commands print English only"
else bad "with SIDENOTE_LANG=en, ${#cases[@]} commands print English only" "Korean: ${korean[*]:-none}; printed nothing: ${silent[*]:-none}"; fi

# 26. Without SIDENOTE_LANG the locale decides: English for an English one, Korean for a Korean one, LC_ALL first.
state running; EXTRA_ENV="SIDENOTE_LANG= LANG=en_US.UTF-8" run status; en_status="$(cat "$work/out")"
EXTRA_ENV="SIDENOTE_LANG= LANG=ko_KR.UTF-8" run status; ko_status="$(cat "$work/out")"
# (bash warns when a locale named here is not installed: the first line of the help is looked for, not the first line)
EXTRA_ENV="SIDENOTE_LANG= LANG=en_US.UTF-8 LC_ALL=ko_KR.UTF-8" run help; all_ko="$(grep -m1 "^Sidenote" "$work/out")"
EXTRA_ENV="SIDENOTE_LANG= LANG=C.UTF-8" run help; c_en="$(grep -m1 "^Sidenote" "$work/out")"
if grep -qF "Server: running" <<<"$en_status" && grep -qF "서버: 실행 중" <<<"$ko_status" && [[ $all_ko == *"화면과 소리"* ]] \
   && [[ $c_en == *"solves the problems"* ]]; then ok "without SIDENOTE_LANG the locale picks the language"
else bad "without SIDENOTE_LANG the locale picks the language" "en: $(head -2 <<<"$en_status" | tail -1) / ko: $(head -2 <<<"$ko_status" | tail -1) / LC_ALL: $all_ko / C: $c_en"; fi

# 27. A SIDENOTE_LANG that is set goes on to the capture program (WSLENV names it); one picked from the locale does not.
state; EXTRA_ENV="SIDENOTE_LANG=en" run capture; wait_started; set_lang="$(cat "$work/state/cmd-lang" 2>/dev/null)"
state; EXTRA_ENV="SIDENOTE_LANG= LANG=ko_KR.UTF-8" run capture; wait_started; locale_lang="$(cat "$work/state/cmd-lang" 2>/dev/null)"
if [[ ":${set_lang%|*}:" == *:SIDENOTE_LANG:* ]] && [ "${set_lang#*|}" = en ] && [[ ":${locale_lang%|*}:" != *:SIDENOTE_LANG:* ]]; then
  ok "a SIDENOTE_LANG that is set reaches the capture program"
else bad "a SIDENOTE_LANG that is set reaches the capture program" "set: ${set_lang:-none}, from the locale: ${locale_lang:-none}"; fi

# 28. launch.pyw in English: the box's title and the launcher's lines in it, a refused argument and a missing wsl.exe.
state server-down docker-off; EXTRA_ENV="SIDENOTE_LANG=en" run_launch; failed="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en" run_launch --bogus; refused="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en" WSL_BIN="$work/nowhere/wsl.exe" run_launch; nowsl="$(cat "$work/out")"
printf '%s\n%s\n%s\n' "$failed" "$refused" "$nowsl" > "$work/boxes"
if ! hangul "$work/boxes" && grep -qx '\[dry-run\] title: Could not start the Sidenote capture' <<<"$failed" \
   && grep -qF "Cannot connect to Docker" <<<"$failed" && grep -qF "./sidenote shortcut" <<<"$refused" && grep -qF "wsl.exe" <<<"$nowsl"; then
  ok "launch.pyw speaks English with SIDENOTE_LANG=en"
else bad "launch.pyw speaks English with SIDENOTE_LANG=en" "$(grep -F 'title:' "$work/boxes" | tr '\n' ' ') $(grep -m2 -P '[\x{AC00}-\x{D7A3}]' "$work/boxes" | tr '\n' ' ')"; fi

# 29. ...hands SIDENOTE_LANG on to the launcher in WSL when it is set on Windows, so the box is in one language, and
#     with nothing set follows the locale (on Windows, the display language).
state; EXTRA_ENV="SIDENOTE_LANG=en" run_launch; wait_started; crossed="$(cat "$work/state/wsl-wslenv" 2>/dev/null)"
state server-down docker-off; EXTRA_ENV="SIDENOTE_LANG= LANG=ko_KR.UTF-8" run_launch
if [[ ":$crossed:" == *:SIDENOTE_LANG:* ]] && grep -qx '\[dry-run\] title: Sidenote 캡처를 시작하지 못했습니다' "$work/out"; then
  ok "launch.pyw hands SIDENOTE_LANG on, and follows the locale without it"
else bad "launch.pyw hands SIDENOTE_LANG on, and follows the locale without it" "WSLENV: ${crossed:-none}, $(grep -F 'title:' "$work/out")"; fi

# 30. With no COMPOSE_FILE set, the GPU picks compose.yaml's companion file (server/hardware.py: nvidia, amd, or cpu
#     when there is neither); one that is set, in the environment or in .env, is left as it is.
top() { sed -n '1,/^LOCAL_MODEL=/p' "$launcher"; }       # the launcher's settings, up to where the models are read
picked="$(cd "$work" && env -u COMPOSE_FILE bash -c 'source /dev/stdin >/dev/null 2>&1; printf %s "$COMPOSE_FILE"' < <(top))"
kept="$(cd "$work" && COMPOSE_FILE=compose.yaml:mine.yaml bash -c 'source /dev/stdin >/dev/null 2>&1; printf %s "$COMPOSE_FILE"' < <(top))"
if [[ "$picked" =~ ^compose\.yaml:docker/compose\.(nvidia|amd|cpu)\.yaml$ ]] && [ "$kept" = compose.yaml:mine.yaml ]; then
  ok "the GPU picks the compose file (${picked#*:}), and a COMPOSE_FILE that is set stays"
else bad "the GPU picks the compose file, and a COMPOSE_FILE that is set stays" "picked: ${picked:-none}, kept: ${kept:-none}"; fi

# --- the CI check, setup-capture, Docker's reasons, a Linux desktop, a PC with no GPU that fits -----------------------
gpu24() { echo "nvidia,NVIDIA GeForce RTX 4090,24" > "$work/state/gpu"; }   # a GPU the local model fits: an engine without an agent
ci_line() { grep -E '(^|[^A-Za-z])CI([^A-Za-z]|$)' "$work/out"; }          # a line about CI (not one about a CLI)

# 31. Without SIDENOTE_CI_GATE nothing asks gh, even of a commit CI failed: up deploys it, status and doctor print no
#     CI line, and doctor's verdict is the setup's alone.
state; gpu24; echo failure > "$work/state/gh-answer"
run up; up_rc="$(cat "$work/rc")"; last_call docker up; up_n=${#CALL[@]}; asked="$(calls_of gh | wc -l)"; lines="$(ci_line)"
run status; asked="$asked$(calls_of gh | wc -l)"; lines="$lines$(ci_line)"
run doctor; doc_rc="$(cat "$work/rc")"; asked="$asked$(calls_of gh | wc -l)"; lines="$lines$(ci_line)"
if [ "$up_rc" = 0 ] && [ "$up_n" -gt 0 ] && [ "$doc_rc" = 0 ] && [ "$asked" = 000 ] && [ -z "$lines" ]; then
  ok "without SIDENOTE_CI_GATE nothing asks gh: up deploys, status and doctor have no CI line"
else bad "without SIDENOTE_CI_GATE nothing asks gh: up deploys, status and doctor have no CI line" \
         "up rc $up_rc (compose up: $up_n), doctor rc $doc_rc, gh asked per command: $asked, CI lines: ${lines:-none}"; fi

# 32. With SIDENOTE_CI_GATE=1 a commit CI failed is not deployed, --no-ci deploys it, and doctor shows the CI line
#     without failing for it (a commit's CI is not this PC's setup).
state; gpu24; echo failure > "$work/state/gh-answer"
EXTRA_ENV="SIDENOTE_CI_GATE=1" run up; refused_rc="$(cat "$work/rc")"; last_call docker up; refused_n=${#CALL[@]}
asked="$(calls_of gh | wc -l)"
EXTRA_ENV="SIDENOTE_CI_GATE=1" run up --no-ci; anyway_rc="$(cat "$work/rc")"; last_call docker up; anyway_n=${#CALL[@]}
EXTRA_ENV="SIDENOTE_CI_GATE=1" run doctor; doc_rc="$(cat "$work/rc")"; lines="$(ci_line)"
if [ "$refused_rc" != 0 ] && [ "$refused_n" = 0 ] && [ "$asked" -gt 0 ] && [ "$anyway_rc" = 0 ] && [ "$anyway_n" -gt 0 ] \
   && [ "$doc_rc" = 0 ] && grep -qF "CI: 이 커밋 실패" <<<"$lines"; then
  ok "with SIDENOTE_CI_GATE=1 a failed commit is refused, --no-ci deploys it, doctor shows CI and still passes"
else bad "with SIDENOTE_CI_GATE=1 a failed commit is refused, --no-ci deploys it, doctor shows CI and still passes" \
         "refused: rc $refused_rc, compose up $refused_n, gh asked $asked; --no-ci: rc $anyway_rc, compose up $anyway_n; doctor rc $doc_rc, CI: ${lines:-none}"; fi

# 33. --when-green asks for CI by name: without the gate it is refused rather than deployed unchecked, and with the gate
#     it deploys a commit CI passed.
state; gpu24; echo success > "$work/state/gh-answer"
run up --when-green; last_call docker up; off_rc="$(cat "$work/rc")"; off_n=${#CALL[@]}; off_asked="$(calls_of gh | wc -l)"
off_said="$(said "SIDENOTE_CI_GATE=1" && echo y)"
EXTRA_ENV="SIDENOTE_CI_GATE=1 CI_WAIT_EVERY=0" run up --when-green; last_call docker up; on_rc="$(cat "$work/rc")"; on_n=${#CALL[@]}
if [ "$off_rc" != 0 ] && [ "$off_n" = 0 ] && [ "$off_asked" = 0 ] && [ "$off_said" = y ] && [ "$on_rc" = 0 ] && [ "$on_n" -gt 0 ] \
   && said "CI를 통과한 커밋"; then ok "--when-green is refused without the gate, and with it deploys a commit CI passed"
else bad "--when-green is refused without the gate, and with it deploys a commit CI passed" \
         "without: rc $off_rc, compose up $off_n, gh asked $off_asked, names the switch: ${off_said:-n}; with: rc $on_rc, compose up $on_n"; fi

# 34. setup-capture is the command's name and setup-windows still works: on WSL both install into Windows Python, and
#     without Windows Python it says where to get it before pip is ever asked.
state; run setup-capture; new_rc="$(cat "$work/rc")"; last_call cmd pip; new_n=${#CALL[@]}
state; run setup-windows; last_call cmd pip; old_n=${#CALL[@]}
state no-py; run setup-capture; nopy_rc="$(cat "$work/rc")"; last_call cmd pip; nopy_n=${#CALL[@]}
if [ "$new_rc" = 0 ] && [ "$new_n" -gt 0 ] && [ "$old_n" -gt 0 ] && [ "$nopy_rc" != 0 ] && [ "$nopy_n" = 0 ] && said "python.org"; then
  ok "setup-capture and setup-windows install the capture packages, and without Windows Python it says python.org"
else bad "setup-capture and setup-windows install the capture packages, and without Windows Python it says python.org" \
         "setup-capture: rc $new_rc, pip $new_n; setup-windows: pip $old_n; no Python: rc $nopy_rc, pip $nopy_n, $(tail -1 "$work/out")"; fi

# 35. install with no Windows Python: step 2 names python.org, the shortcut is skipped, and steps 3 and 4 and doctor
#     still run (cmd.exe's "'py' is not recognized" used to end it at step 2).
state no-py no-pyw; run install
if [ "$(cat "$work/rc")" != 0 ] && said "python.org" && said "3/4" && said "4/4" && said "점검" && ! said "is not recognized"; then
  ok "install without Windows Python says python.org and still runs the other steps and doctor"
else bad "install without Windows Python says python.org and still runs the other steps and doctor" \
         "rc $(cat "$work/rc"), $(tr '\n' ' ' < "$work/out" | head -c 300)"; fi

# 36. A Linux desktop whose first setup ran without python3-venv: that left a .venv-capture with a python and no pip.
#     Once python3-venv is there, the next setup-capture makes it again and installs (it used to reuse it, and pip failed).
linux="WSL_DISTRO_NAME= PATH=$work/venvbin:$work/bin:/usr/bin:/bin"
rm -rf "$work/repo/.venv-capture"
state no-ensurepip; EXTRA_ENV="$linux" run setup-capture; first_rc="$(cat "$work/rc")"; first_said="$(said "python3-venv" && echo y)"
state; EXTRA_ENV="$linux" run setup-capture; second_rc="$(cat "$work/rc")"; last_call venv --clear; cleared=${#CALL[@]}
last_call pip install; installed=${#CALL[@]}
if [ "$first_rc" != 0 ] && [ "$first_said" = y ] && [ "$second_rc" = 0 ] && [ "$cleared" -gt 0 ] && [ "$installed" -gt 0 ]; then
  ok "a .venv-capture left without pip is made again by the next setup-capture"
else bad "a .venv-capture left without pip is made again by the next setup-capture" \
         "first: rc $first_rc, names python3-venv: ${first_said:-n}; second: rc $second_rc, venv --clear $cleared, pip install $installed, $(tail -1 "$work/out")"; fi

# 37. No GPU that fits a model: llm pull, install, doctor and status say one and the same line, once each, with no model
#     "for this GPU" without a name and no other line about the CPU; the agent then gets the whole screen.
# (taken out by fixed text, not a regex: some C.UTF-8 locales do not count every Hangul syllable as a character, and a
# `.` in sed then stops short of the line's end)
state; run llm pull; nofit="$(grep -m1 -F "쓰지 않음, 맞는 GPU 없음 (" "$work/out" | grep -F "  ! " | cut -c5-)"
once() { [ -n "$nofit" ] && [ "$(grep -cxF "  ! $nofit" "$work/out")" = 1 ]; }
cpu_lines() { grep -F "CPU" "$work/out" | grep -vxF "  ! $nofit"; }
o_pull="$(once && echo y)"
state; run install; o_install="$(once && echo y)"; noname="$(said "맞는 모델: ," && echo y)"; cpu="$(cpu_lines)"
state; run doctor; o_doctor="$(once && echo y)"; cpu="$cpu$(cpu_lines)"
state; cat > "$work/state/health.json" <<'JSON'
{"ok": true, "audio": true, "paused": false, "capture": {"clients": 0, "screen_on": true, "audio_on": true},
 "engines": {"ready": true,
   "local": {"present": true, "on": true, "ok": false, "missing": true, "model": "sidenote-gemma4:26b", "fits": false, "gpu_gb": null},
   "agent": {"present": true, "ok": true, "product": "Claude Code", "method": "claude.ai", "mode": "hard", "effective": "all", "payload": "crop"}}}
JSON
run status; o_status="$(once && echo y)"; screen="$(said "보내는 것: 화면 전체" && echo y)"
if [ "$o_pull$o_install$o_doctor$o_status" = yyyy ] && [ -z "$noname$cpu" ] && [ "$screen" = y ]; then
  ok "with no GPU that fits, llm pull, install, doctor and status say the same line once, and the agent gets the whole screen"
else bad "with no GPU that fits, llm pull, install, doctor and status say the same line once, and the agent gets the whole screen" \
         "line: ${nofit:-none}; once in pull, install, doctor, status: ${o_pull:-n}${o_install:-n}${o_doctor:-n}${o_status:-n}; model with no name: ${noname:-n}; other CPU lines: ${cpu:-none}; whole screen: ${screen:-n}"; fi

# 38. The engines in status by the panel's names: the local model idle or on GPU, Solver settings, and what the agent
#     takes beside what it sends (English, where the old names were).
health_with() { cat > "$work/state/health.json" <<JSON
{"ok": true, "audio": true, "paused": false, "capture": {"clients": 0, "screen_on": true, "audio_on": true},
 "engines": {"ready": true, "local": $1,
   "agent": {"present": true, "ok": true, "product": "Claude Code", "method": "claude.ai", "mode": "hard", "effective": "hard", "payload": "crop"}}}
JSON
}
state; health_with '{"present": true, "on": true, "ok": true, "model": "sidenote-gemma4:26b", "loaded": null}'
EXTRA_ENV="SIDENOTE_LANG=en" run status; idle="$(cat "$work/out")"
state; health_with '{"present": true, "on": true, "ok": true, "model": "sidenote-gemma4:26b", "loaded": {"model": "sidenote-gemma4:26b", "vram_gb": 20.5}}'
EXTRA_ENV="SIDENOTE_LANG=en" run status; loaded="$(cat "$work/out")"
state; health_with '{"present": true, "on": false, "ok": true, "model": "sidenote-gemma4:26b"}'
EXTRA_ENV="SIDENOTE_LANG=en" run status; off="$(cat "$work/out")"
if grep -qF "Local model: idle (sidenote-gemma4:26b)" <<<"$idle" && grep -qF "Local model: on GPU (sidenote-gemma4:26b, 20.5 GB)" <<<"$loaded" \
   && grep -qF "Local model: off (Solver settings in the panel)" <<<"$off" \
   && grep -qF "takes hard problems of the chosen types, sends the problem area only" <<<"$idle" \
   && ! grep -qiF "this PC's model" <<<"$idle$loaded$off"; then
  ok "status names the local model, its idle and on-GPU states, Solver settings, and what the agent takes"
else bad "status names the local model, its idle and on-GPU states, Solver settings, and what the agent takes" \
         "$(grep -hE "model|Agent" <<<"$idle$loaded$off" | tr '\n' '|')"; fi

# 39. What Docker itself says is passed on: a user outside the docker group is told so, and an NVIDIA GPU Docker cannot
#     reach names the Container Toolkit and the CPU compose file (they used to read "check that Docker is running" and
#     "exit code 1").
state docker-denied; run up; denied="$(cat "$work/out")"
state no-toolkit; run up; toolkit="$(cat "$work/out")"
if grep -qF "docker 그룹" <<<"$denied" && grep -qF "NVIDIA Container Toolkit" <<<"$toolkit" && grep -qF "compose.cpu.yaml" <<<"$toolkit"; then
  ok "up names the docker group and the NVIDIA Container Toolkit when Docker says those"
else bad "up names the docker group and the NVIDIA Container Toolkit when Docker says those" \
         "denied: $(tail -1 <<<"$denied"); toolkit: $(tail -1 <<<"$toolkit")"; fi

# 40. uninstall on a Linux desktop: no Windows shortcut in the list, the capture packages' .venv-capture in it, the
#     agents' login folders named as kept, and --yes goes on to remove the containers and the venv (it used to stop at
#     the shortcut, which ends the script where there is no WSL).
mkdir -p "$work/repo/.venv-capture/bin"
state; EXTRA_ENV="WSL_DISTRO_NAME=" run uninstall; listed="$(cat "$work/out")"
state; EXTRA_ENV="WSL_DISTRO_NAME=" run uninstall --yes; last_call docker down
if ! grep -qF ".lnk" <<<"$listed" && grep -qF ".venv-capture" <<<"$listed" && grep -qF "~/.claude" <<<"$listed" \
   && [ ${#CALL[@]} -gt 0 ] && [ ! -d "$work/repo/.venv-capture" ]; then
  ok "uninstall on Linux lists what it made there, keeps the agents' logins, and --yes removes it"
else bad "uninstall on Linux lists what it made there, keeps the agents' logins, and --yes removes it" \
         "list: $(tr '\n' '|' <<<"$listed" | head -c 300); compose down: ${#CALL[@]}, venv left: $([ -d "$work/repo/.venv-capture" ] && echo yes || echo no)"; fi

# 41. help, in both languages: README's three commands first, setup-capture, the capture options people type (--up,
#     --no-tray, --no-auto-stitch), gpu status, and the CI check's switch.
missing=""
for lang in en ko; do
  EXTRA_ENV="SIDENOTE_LANG=$lang" run help
  for w in "./sidenote install, " "./sidenote llm pull, " "./sidenote capture --up" "setup-capture" "--no-tray" "--no-auto-stitch" \
           "--up (" "gpu status" "SIDENOTE_CI_GATE=1"; do
    said "$w" || missing="$missing $lang:$w"
  done
done
if [ -z "$missing" ]; then ok "help names the start commands, setup-capture, the capture options, gpu status and the CI switch"
else bad "help names the start commands, setup-capture, the capture options, gpu status and the CI switch" "missing:$missing"; fi

printf '  ==== %d of %d as expected\n' "$pass" "$((pass + fail))"
[ "$fail" = 0 ]
