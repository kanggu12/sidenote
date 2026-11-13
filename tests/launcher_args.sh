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
# - a `capture --up` that brought the server up hands the capture program this checkout (--stop-server-on-quit, whose
#   ./sidenote down its Quit runs), on WSL's own start and on the one launch.pyw makes on Windows; one that found the
#   server running hands nothing on;
# - a missing tray package (pystray) is said, and `install` installs it;
# - --once runs in the terminal, and --no-tray says how the windowless program is ended;
# - the desktop shortcut runs client/launch.pyw with Windows Python's windowless pyw.exe, not wsl.exe in a console
#   window of its own (that window used to come up on every start), and is not made without pyw.exe;
# - launch.pyw runs `./sidenote capture --up` through wsl.exe as a login shell, shows nothing when that works, and
#   when it fails shows the reason in a message box (printed here, with --dry-run): the last lines, without
#   terminal colour codes, wsl.exe's own UTF-16 messages readable, capture options passed on as typed;
# - `capture --up` with no terminal (as launch.pyw runs it) ends with a failing status and waits for no key;
# - up gives a local model server that is starting a moment before it reports on it;
# - on a PC with no internet up builds and pulls nothing, and the capture packages come from a folder of wheels;
# - with a model server already running (SIDENOTE_LOCAL_URL) up leaves the llm container out, and nothing pulls a model;
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
#   help names the start commands, setup-capture, the capture options and the CI switch;
# - the server's user: up passes this user to compose and 0 under rootless Docker, makes the folders Docker would make as
#   root, and compose.yaml uses it (tests/nonroot_check.sh runs that for real);
# - with the Windows folders off WSL's PATH ([interop] appendWindowsPath=false) cmd.exe and powershell.exe are found on
#   the Windows drive the mount table names, and capture starts; with interop off, or no Windows drive, that is what is
#   said (not "no Windows Python"), and nothing is run;
# - the time zone comes from the PC, .env first; what PowerShell prints is read as UTF-8; no python3 is said;
# - a first install ends well with what is left to do, and uninstall takes the images it pulled;
# - uninstall lists what goes and what stays (the history, settings and logs, with their size), and --data removes
#   what Sidenote wrote in the log folder by name, leaving the folder with anything else in it;
# - where WSL cannot start Windows programs, uninstall prints the launch.pyw --remove command, and that command with
#   --dry-run removes nothing;
# - backup copies the history (the server's own SQLite copy while it runs) and the settings into a 600 tar.gz of plain
#   names, never over a file that is there;
# - restore refuses what is no backup, asks first, keeps what was there in a before-restore folder (each one kept), stops and starts a
#   running server, and puts everything back when it fails halfway;
# - llm rm removes a model with its tuned copy after a yes, and says one that is not there;
# - the GPU picks compose.amd.yaml only for an AMD GPU a model runs on, with /dev/kfd there and its group by number;
# - with the server off, bash 3.2 says why instead of ending with curl's status (open, capture-restart, capture);
# - the setup command for Windows is on a line of its own, and WSL 1 is said as WSL 1;
# - Docker without the Compose plugin, or with one older than 2.24, is said before up starts anything, and doctor names
#   the version; doctor reads the log's days as the server does;
# - a port taken: up says what a port change leaves behind;
# - status says why the server is off (exit code, memory, its own loop giving up), a restart within ten minutes, and a
#   local model whose container is off;
# - capture-stop names the tray icon's Quit first, and within down Windows out of reach is one quiet line;
# - capture --console refused by a capture program already running ends 1 and stops nothing;
# - interop off: the language and the launcher's own setup command reach launch.pyw, and with a capture program
#   holding its guard for the server, launch.pyw opens the panel and starts no second one;
# - --help after a command prints that command's lines of the help and does nothing else, with no python3 too;
# - another program answering on the port is no server: status says off, install starts it, open opens nothing;
# - login with the agent off, or the stand-in for tests, says so;
# - the lines printed to be typed again (restore, llm rm) read back as the words asked, and backup takes a folder;
# - events and report with the server off mount no log folder that is not there, and up leaves no temporary file.
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
: > "$work/repo/client/sidenote.ico"               # the shortcut's icon: only its path matters here
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
      # --console, --list-monitors. With state/capture-busy the program finds another one running for the server and
      # ends as capture.py does then (CAPTURE_BUSY): its first line, and exit code 76
      *) if [ -f "$FAKE/state/capture-busy" ]; then
           echo "[main] Another capture program is already running for this server, so this one ends."; exit 76
         fi
         echo "[main] the capture program would run here" ;;
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
  # With state/korean-desktop, a folder with Korean in it, as PowerShell 5.1 writes it into a pipe: UTF-8 only when asked
  *GetFolderPath*) if [ ! -f "$FAKE/state/korean-desktop" ]; then echo 'C:\Users\fake\Desktop'
                   elif [[ $3 == *OutputEncoding*UTF8* ]]; then echo 'C:\Users\진구\OneDrive\바탕 화면'
                   else echo 'C:\Users\진구\OneDrive\바탕 화면' | iconv -f UTF-8 -t CP949; fi ;;
  *Get-Command*pyw*) [ -f "$FAKE/state/no-pyw" ] || echo 'C:\WINDOWS\pyw.exe' ;;
  *sidenote.ico*) [ -f "$FAKE/state/no-icon-copy" ] || echo 'C:\Users\fake\AppData\Local\Sidenote\sidenote.ico' ;;
  *Test-Path*) echo y ;;
esac
exit 0
STUB

# curl: the server's /health (a capture program counts as connected once it was started) and /capture/quit.
# With state/server-down every request fails the way curl does when nothing listens. Each /health answer has the
# "ok": true and the analyzer the server's own has, which is how the launcher knows it from another program's.
cat > "$work/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/curl.$(date +%s%N)"
[ -f "$FAKE/state/server-down" ] && exit 7
case "$*" in
  */capture/quit*) [ -f "$FAKE/state/unkillable" ] || rm -f "$FAKE/state/running"; echo '{"asked": 1}' ;;
  # state/health.json, when a check wrote one, is the answer as it stands (the engines' states the status reads), and
  # state/health-later.json the answer from the fifth ask on: what is still starting when the first ones ask
  */health*) if [ -f "$FAKE/state/health-later.json" ]; then
               asks="$(cat "$FAKE/state/health-asks" 2>/dev/null || echo 0)"; echo $((asks + 1)) > "$FAKE/state/health-asks"
               if [ "$asks" -ge 4 ]; then cat "$FAKE/state/health-later.json"; exit 0; fi
             fi
             if [ -f "$FAKE/state/health.json" ]; then cat "$FAKE/state/health.json"; exit 0; fi
             n=0; [ -f "$FAKE/state/running" ] && n=1
             printf '{"ok": true, "analyzer": "local", "audio": true, "paused": false, "engines": {"ready": true}, '
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
# `ollama list`: with state/llm-models the models in $FAKE/ollama-list, otherwise the header alone, as an Ollama with no
# model prints it
ollama_list() { if [ -f "$FAKE/state/llm-models" ]; then cat "$FAKE/ollama-list"; else echo 'NAME    ID    SIZE    MODIFIED '; fi; }
case "$1" in
  info) [ -f "$FAKE/state/docker-off" ] && exit 1
        [ -f "$FAKE/state/rootless" ] && echo '["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]'
        if [ -f "$FAKE/state/docker-denied" ]; then
          echo "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" >&2; exit 1
        fi ;;
  version) [ -f "$FAKE/state/docker-off" ] || [ -f "$FAKE/state/docker-denied" ] || echo "29.0.0" ;;
  # the server's container with state/server-running, the local model's with state/llm-running
  ps) [ -f "$FAKE/state/server-running" ] && echo sidenote
      [ -f "$FAKE/state/llm-running" ] && echo sidenote-llm
      exit 0 ;;
  # the token the server's container was made with, from state/served-token (none: printenv fails). The server's copy of
  # the history for a backup: the Python it is given, run here with the log folder where the container has /data/logs.
  # The local model server's models: the list in $FAKE/ollama-list, as `ollama list` prints it; `ollama rm` is written down.
  exec) if [[ " $* " == *" printenv CLAUDE_CODE_OAUTH_TOKEN "* ]]; then cat "$FAKE/state/served-token" 2>/dev/null || exit 1
        elif [ "${2:-}" = sidenote ] && [ "${3:-}" = python ] && [ "${4:-}" = -c ]; then python3 -c "${5//\/data\/logs/$FAKE/logs}" || exit 1
        elif [ "${2:-}" = sidenote-llm ] && [ "${4:-}" = list ]; then ollama_list
        fi ;;
  # a container that runs; with state/container-ended one that ended, its "<status> <exit code> <OOM killed>" in that file
  inspect) if [ -f "$FAKE/state/container-ended" ]; then
             case "$*" in *State.Status*State.ExitCode*) cat "$FAKE/state/container-ended" ;; *State.Status*) echo exited ;; *) echo false ;; esac
           else echo true; fi ;;
  # state/no-compose: a Docker without the Compose plugin (a distribution's docker.io), in Docker's own words; the
  # version from state/compose-version when a check wrote one. state/port-taken: up fails as when the port is taken.
  # state/compose-warn: the warning compose writes to stderr for a variable .env leaves unset, on every call; with
  # state/compose-broken, `ps` fails after it, with compose's own last line
  compose) if [ -f "$FAKE/state/no-compose" ]; then printf "docker: 'compose' is not a docker command.\nSee 'docker --help'\n" >&2; exit 1; fi
           if [ "${2:-}" = version ]; then cat "$FAKE/state/compose-version" 2>/dev/null || echo 2.29.7; exit 0; fi
           if [ -f "$FAKE/state/port-taken" ] && printf '%s\n' "$@" | grep -qx up; then
             echo 'Error response from daemon: driver failed programming external connectivity on endpoint sidenote: Bind for 127.0.0.1:8777 failed: port is already allocated' >&2
             exit 1
           fi
           [ -f "$FAKE/state/compose-warn" ] && echo 'WARN[0000] The "SIDENOTE_X" variable is not set. Defaulting to a blank string.' >&2
           if [ -f "$FAKE/state/compose-broken" ] && printf '%s\n' "$@" | grep -qx ps; then
             echo 'no configuration file provided: not found' >&2; exit 1
           fi
           if [ -f "$FAKE/state/no-toolkit" ] && printf '%s\n' "$@" | grep -qx up; then
             echo 'Error response from daemon: could not select device driver "nvidia" with capabilities: [[gpu]]' >&2; exit 1
           fi
           # state/up-starts-server: the server was off and `compose up` brings it up, so /health answers from here on
           if [ -f "$FAKE/state/up-starts-server" ] && printf '%s\n' "$@" | grep -qx up; then rm -f "$FAKE/state/server-down"; fi
           # what compose.yaml would be filled in with, for the checks of the server's user and the time zone
           if printf '%s\n' "$@" | grep -qx up; then
             printf '%s:%s %s' "${SIDENOTE_UID:-}" "${SIDENOTE_GID:-}" "${TZ:-}" > "$FAKE/state/compose-env"
           fi
           # the tools container's Ollama, with no llm container running: the list, or nothing for `ollama rm`
           if printf '%s\n' "$@" | grep -qx llm-pull && [[ $* == *"; ollama list" ]]; then
             ollama_list
           fi ;;
  # With state/image-in-use, the way Docker refuses to remove an image a container of another project runs
  image) if [ "$2" = rm ] && [ -f "$FAKE/state/image-in-use" ] && [[ $* == *ollama/ollama* ]]; then exit 1; fi
         if [ "$2" = inspect ] && [ -f "$FAKE/state/no-image" ]; then exit 1; fi ;;
  # A throwaway container with a folder of this PC mounted (-v source:target): Docker makes a source that is missing, and
  # each missing folder above it, itself (as root, mode 755). Made here too, and each one written down in state/docker-made
  run) prev=""
       for a in "$@"; do
         if [ "$prev" = -v ]; then src="${a%%:*}"; [ -e "$src" ] || { mkdir -p "$src"; echo "$src" >> "$FAKE/state/docker-made"; }; fi
         prev="$a"
       done ;;
esac
exit 0
STUB
# id: an ordinary user unless a check says otherwise, whoever runs this suite
cat > "$work/bin/id" <<'STUB'
#!/usr/bin/env bash
case "$1" in -u) echo 1000 ;; -g) echo 1001 ;; *) exec /usr/bin/id "$@" ;; esac
STUB
# timedatectl: what the system says of its time zone (state/system-tz), or nothing, as under WSL without systemd
cat > "$work/bin/timedatectl" <<'STUB'
#!/usr/bin/env bash
cat "$FAKE/state/system-tz" 2>/dev/null
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
if [ -f "$FAKE/state/linux-capture" ]; then echo 4242; else exit 1; fi   # one process id a line, as pgrep prints them
STUB
cat > "$work/bin/pkill" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/pkill.$(date +%s%N)"
rm -f "$FAKE/state/linux-capture"
STUB
# xdg-open, for the runs as a Linux desktop that open the panel: it writes down what it was given. This PC has a real one,
# which in WSL can open a browser on the desktop the user is looking at, and no run may reach it
cat > "$work/bin/xdg-open" <<'STUB'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$FAKE/calls/xdg.$(date +%s%N)"
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
for a in "$@"; do                                 # the capture program itself: started, as pgrep then counts it
  if [ "$a" = client/capture.py ]; then touch "$FAKE/state/linux-capture"; exit 0; fi
done
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
# Another bash for the launcher and the stand-ins, when SIDENOTE_TEST_BASH names one (macOS ships bash 3.2): first on the
# PATH of every run below, so `bash` there is that one
if [ -n "${SIDENOTE_TEST_BASH:-}" ]; then ln -sf "$SIDENOTE_TEST_BASH" "$work/bin/bash"; fi
# The local model server's models, as `ollama list` prints them (its header read from ollama/ollama 0.40.5, columns
# padded with spaces and a space at each line's end; SIZE is two words)
printf '%s\n' 'NAME                   ID              SIZE      MODIFIED     ' \
  'gemma4:e4b             c6eb396dbd59    9.6 GB    2 days ago      ' \
  'sidenote-gemma4:e4b    0d1b2c3a4e5f    9.6 GB    2 days ago      ' \
  'gemma4:e2b             a2af6cc3eb7f    7.2 GB    5 days ago      ' \
  'qwen3:8b               500a1f067a9f    5.2 GB    3 weeks ago     ' > "$work/ollama-list"
# mv, for the restore that fails halfway: it fails to move the restore's last file into place, as a disk that fills up
# would, and moves everything else as mv does. On the PATH of that one run alone.
mkdir -p "$work/mvbin"
cat > "$work/mvbin/mv" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in */.restore.*/.switches.json) echo "mv: cannot move '$a': No space left on device" >&2; exit 1 ;; esac
done
exec /bin/mv "$@"
STUB
chmod +x "$work/mvbin/mv"

# One run of the launcher copy, everything outside it stood in for. HOME, the log folder and the temporary folder
# (TMPDIR: a capture program's guard file, mktemp) are scratch, the
# PATH holds the stand-ins and the system's own tools only (no claude, no Windows folders), stdin is empty
# (no terminal, so nothing waits for a key) and the output is kept for the checks. In Korean unless EXTRA_ENV says
# otherwise (a later SIDENOTE_LANG= wins, and an empty one leaves the choice to the locale).
run() {
  rm -rf "$work/calls"/* && mkdir -p "$work/calls"
  env -i TMPDIR="$work" PATH="$work/bin:/usr/bin:/bin" HOME="$work/home" FAKE="$work" WSL_DISTRO_NAME="${WSL_DISTRO_NAME:-Ubuntu}" \
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
  env -i TMPDIR="$work" PATH="$work/bin:/usr/bin:/bin" HOME="$work/home" FAKE="$work" WSL_DISTRO_NAME="$distro" \
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
  CALL=(); [ -n "$found" ] && while IFS= read -r -d '' x; do CALL+=("$x"); done < "$found"   # not mapfile -d: bash 3.2
  return 0
}
last_call_with() {   # $1 = cmd|ps|curl|docker, $2 = text inside one of the call's arguments
  local f found=""
  for f in $(calls_of "$1"); do tr '\0' '\n' < "$f" | grep -qF -- "$2" && found="$f"; done
  CALL=(); [ -n "$found" ] && while IFS= read -r -d '' x; do CALL+=("$x"); done < "$found"   # not mapfile -d: bash 3.2
  return 0
}
# What follows the given argument in CALL, as one string with each word in <>, for a readable comparison.
after() { local i out=""; for ((i = 0; i < ${#CALL[@]}; i++)); do [ "${CALL[$i]}" = "$1" ] && break; done
          for ((i += 2; i < ${#CALL[@]}; i++)); do out="$out<${CALL[$i]}>"; done; printf '%s' "$out"; }
said() { grep -qF -- "$1" "$work/out"; }          # the launcher printed this
wait_started() { for _ in $(seq 1 40); do [ -f "$work/state/running" ] && return 0; sleep 0.1; done; return 1; }

echo "launcher_args ($launcher)"
want='<--monitor><2><--audio-device><Realtek USB2.0 Audio>'
# How it was started, which the launcher hands on ahead of the options as typed (the panel's Capture connection shows it):
# a terminal's start says terminal, the desktop shortcut's starter (launch.pyw, --from-windows) shortcut
term='<--started><terminal>'

# 1. The windowless start: what pyw gets after the launcher's own --server and --log.
state; run capture --monitor 2 --audio-device "Realtek USB2.0 Audio"; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "$term$want" ] && ok "windowless start passes the options as typed" \
  || bad "windowless start passes the options as typed" "got $got"

# 2. --console: the same options after --server, and --console itself not passed on.
state; run capture --console --monitor 2 --audio-device "Realtek USB2.0 Audio"
last_call cmd -u; got="$(after --server)"
[ "$got" = "$term$want" ] && ok "--console passes the options as typed" || bad "--console passes the options as typed" "got $got"

# 3. --up (what the desktop shortcut uses), with a Korean device name in parentheses, the way Windows names it.
state; run capture --up --audio-device "스피커 (Realtek USB2.0 Audio)"; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "$term<--audio-device><스피커 (Realtek USB2.0 Audio)>" ] && ok "--up passes the options as typed, without --up" \
  || bad "--up passes the options as typed, without --up" "got $got"

# 3b. Whoever starts the server stops it: --up that brought the server up hands the program this checkout, whose
# ./sidenote down the program's Quit runs too, and says how to end both. One that found it running hands nothing (3).
state server-down up-starts-server; run capture --up --monitor 2; wait_started
last_call cmd start; got="$(after --log)"; owned="$(wslpath -w "$work/repo")"
if [ "$got" = "$term<--monitor><2><--stop-server-on-quit><$owned>" ] && said "Sidenote 끝내기" && said "./sidenote down"; then
  ok "--up that brought the server up hands the capture program this checkout, and says Quit Sidenote ends both"
else bad "--up that brought the server up hands the capture program this checkout, and says Quit Sidenote ends both" \
         "got $got, said: $(grep -aF "끝내기" "$work/out" | tail -1)"; fi

# 3c. A server whose container runs but whose /health is slow (a model loading, a long answer) is no server this start
# brought up: up runs as before, and nothing is handed on, or the session's Quit would end a server someone else started.
state server-running server-down up-starts-server; run capture --up --monitor 2; wait_started
last_call cmd start; got="$(after --log)"
[ "$got" = "$term<--monitor><2>" ] && ok "a running server that answers late is not claimed: nothing handed on" \
  || bad "a running server that answers late is not claimed: nothing handed on" "got $got"
# 3d. A down on its way (the tray's Quit Sidenote runs one) holds its lock, and a start with --up waits for it: then it
# finds the server off and brings it up for its own session, and the down does not end the program it starts.
mkdir -p "$work/logs"; ( flock "$work/logs/.down.lock" sleep 2 ) & holder=$!; started+=("$holder"); sleep 0.3
state server-down up-starts-server; t0=$(date +%s%N); run capture --up --monitor 2; wait_started; took=$(( ($(date +%s%N) - t0) / 1000000 ))
last_call cmd start; got="$(after --log)"; wait "$holder" 2>/dev/null || true
if [ "$took" -ge 1500 ] && [ "$got" = "$term<--monitor><2><--stop-server-on-quit><$owned>" ]; then
  ok "a start with --up waits for a down on its way, then brings the server up for its own session"
else bad "a start with --up waits for a down on its way, then brings the server up for its own session" "took ${took} ms, got $got"; fi

# 4. --list-monitors goes to capture.py directly; the launcher's own --console must not go with it.
state; run capture --console --list-monitors
last_call cmd --list-monitors
if [ ${#CALL[@]} -gt 0 ] && ! printf '%s\n' ${CALL[@]+"${CALL[@]}"} | grep -qx -- --console; then ok "--list-monitors is passed on without --console"
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
[ "$got" = "$term<--once>" ] && ok "--once runs in this terminal" || bad "--once runs in this terminal" "got ${got:-no console call}"

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
want_args="'-3 \"$(wslpath -w "$work/repo/client/launch.pyw")\" --distro $distro --repo \"$work/repo\" --port 8777'"
if [ "$target" = "'C:\WINDOWS\pyw.exe'" ] && [ "$args" = "$want_args" ] && [[ $args != *capture.py* ]]; then
  ok "the shortcut runs launch.pyw with pyw.exe, not wsl.exe"
else bad "the shortcut runs launch.pyw with pyw.exe, not wsl.exe" "target ${target:-none}, arguments ${args:-none}"; fi

# 16a. The start's window asks the server on its own port: the shortcut once named none, and on SIDENOTE_PORT=8779 the window
#     waited on 8777, at "Starting the server", for a server that was up all along.
state; EXTRA_ENV="SIDENOTE_PORT=8779" run shortcut
last_call_with ps CreateShortcut; script="${CALL[2]:-}"
args="$(sed -n 's/^.*$s\.Arguments = \(.*\);$/\1/p' <<<"$script")"
if [[ $args == *"--port 8779'" ]]; then ok "the shortcut gives the start's window the server's port (SIDENOTE_PORT)"
else bad "the shortcut gives the start's window the server's port (SIDENOTE_PORT)" "arguments ${args:-none}"; fi

# 16b. It wears Sidenote's own icon, copied to a Windows folder. It used to name shell32.dll's picture 16, a printer.
icon="$(sed -n 's/^.*$s\.IconLocation = \(.*\);$/\1/p' <<<"$script")"
last_call_with ps Copy-Item; copied="${CALL[2]:-}"
if [ "$icon" = "'C:\Users\fake\AppData\Local\Sidenote\sidenote.ico,0'" ] && [[ $script != *shell32* ]] \
   && [[ $copied == *"$(wslpath -w "$work/repo/client/sidenote.ico")"* ]]; then
  ok "the shortcut wears Sidenote's icon, copied to a Windows folder, and no picture out of shell32.dll"
else bad "the shortcut wears Sidenote's icon, copied to a Windows folder, and no picture out of shell32.dll" "icon ${icon:-none}"; fi
[ -f "$root/client/sidenote.ico" ] && ok "the icon is in the repository" || bad "the icon is in the repository" "$root/client/sidenote.ico"

# 16c. A copy that fails costs no shortcut: it wears the checkout's own file, which serves while WSL runs.
state no-icon-copy; run shortcut
last_call_with ps CreateShortcut; icon="$(sed -n 's/^.*$s\.IconLocation = \(.*\);$/\1/p' <<<"${CALL[2]:-}")"
if [ "$(cat "$work/rc")" = 0 ] && [ "$icon" = "'$(wslpath -w "$work/repo/client/sidenote.ico"),0'" ]; then
  ok "with the icon not copied the shortcut is still made, with the checkout's file"
else bad "with the icon not copied the shortcut is still made, with the checkout's file" "rc $(cat "$work/rc"), icon ${icon:-none}"; fi

# 16d. Removing the shortcut takes the icon with it, and only the icon: the app keeps its data in the same folder.
state; run shortcut --remove
last_call_with ps "Remove-Item -LiteralPath (Join-Path"; removed="${CALL[2]:-}"
if [[ $removed == *"sidenote.ico"* ]] && [[ $removed == *"Get-ChildItem"* ]] && [[ $removed != *"-Recurse"* ]]; then
  ok "--remove takes the icon too, and its folder only when that is empty"
else bad "--remove takes the icon too, and its folder only when that is empty" "${removed:-no such call}"; fi

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
   && grep -qx '\[dry-run\] title: 캡처를 시작하지 못함' "$work/out" \
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
[ "$got" = "<--started><shortcut><--audio-device><스피커 (Realtek USB2.0 Audio)><--monitor><2>" ] && ok "launch.pyw passes capture options on as typed, the start said to be the shortcut's" \
  || bad "launch.pyw passes capture options on as typed, the start said to be the shortcut's" "got ${got:-no start}, $(tail -1 "$work/out")"

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
       "|llm pull" "docker-denied|up" "no-toolkit|up" "|up --when-green" "|gpu status"
       "|uninstall --data" "|uninstall --bogus" "|backup $work/never.tar.gz" "|backup --bogus" "|restore" "|llm rm"
       "llm-running llm-models|llm rm nosuch:1b")   # (backup with a file named: one made with no name would land in this folder)
korean=() silent=()
for c in ${cases[@]+"${cases[@]}"}; do
  read -r -a mood <<<"${c%%|*}"; read -r -a cmd <<<"${c#*|}"
  state ${mood[@]+"${mood[@]}"}; [ -f "$work/state/notray" ] && echo notray > "$work/state/tray"
  EXTRA_ENV="SIDENOTE_LANG=en" run ${cmd[@]+"${cmd[@]}"}
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
if ! hangul "$work/boxes" && grep -qx '\[dry-run\] title: Capture did not start' <<<"$failed" \
   && grep -qF "Cannot connect to Docker" <<<"$failed" && grep -qF "./sidenote shortcut" <<<"$refused" && grep -qF "wsl.exe" <<<"$nowsl"; then
  ok "launch.pyw speaks English with SIDENOTE_LANG=en"
else bad "launch.pyw speaks English with SIDENOTE_LANG=en" "$(grep -F 'title:' "$work/boxes" | tr '\n' ' ') $(grep -m2 -P '[\x{AC00}-\x{D7A3}]' "$work/boxes" | tr '\n' ' ')"; fi

# 29. ...hands SIDENOTE_LANG on to the launcher in WSL when it is set on Windows, so the box is in one language; with
#     nothing set it speaks English whatever the locale (the system's language is not read), and Korean with ko.
state; EXTRA_ENV="SIDENOTE_LANG=en" run_launch; wait_started; crossed="$(cat "$work/state/wsl-wslenv" 2>/dev/null)"
state server-down docker-off; EXTRA_ENV="SIDENOTE_LANG= LANG=ko_KR.UTF-8" run_launch; unset_title="$(grep -m1 -F 'title:' "$work/out")"
state server-down docker-off; EXTRA_ENV="SIDENOTE_LANG=ko" run_launch; ko_title="$(grep -m1 -F 'title:' "$work/out")"
if [[ ":$crossed:" == *:SIDENOTE_LANG:* ]] && [ "$unset_title" = "[dry-run] title: Capture did not start" ] \
   && [ "$ko_title" = "[dry-run] title: 캡처를 시작하지 못함" ]; then
  ok "launch.pyw hands SIDENOTE_LANG on, speaks English without it whatever the locale, and Korean with ko"
else bad "launch.pyw hands SIDENOTE_LANG on, speaks English without it whatever the locale, and Korean with ko" \
  "WSLENV: ${crossed:-none}, unset: ${unset_title:-none}, ko: ${ko_title:-none}"; fi

# 30. With no COMPOSE_FILE set, the GPU picks compose.yaml's companion file (server/hardware.py: nvidia, amd, or cpu
#     when there is neither); one that is set, in the environment or in .env, is left as it is.
top() { sed -n '1,/^LOCAL_MODEL=/p' "$launcher"; }       # the launcher's settings, up to where the models are read
top > "$work/top.sh"   # a file, not /dev/stdin: bash 3.2's source reads nothing from a pipe
picked="$(cd "$work" && env -u COMPOSE_FILE bash -c 'source ./top.sh >/dev/null 2>&1; printf %s "$COMPOSE_FILE"')"
kept="$(cd "$work" && COMPOSE_FILE=compose.yaml:mine.yaml bash -c 'source ./top.sh >/dev/null 2>&1; printf %s "$COMPOSE_FILE"')"
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
{"ok": true, "analyzer": "local", "audio": true, "paused": false, "capture": {"clients": 0, "screen_on": true, "audio_on": true},
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
{"ok": true, "analyzer": "local", "audio": true, "paused": false, "capture": {"clients": 0, "screen_on": true, "audio_on": true},
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

# 42. The local model's server is started beside the server, and answers a moment later: up gives it that moment, so its
#     status does not call a model server that is starting "not responding". One that does not come is still called
#     that, and up does not wait on it for longer than it takes.
starting='{"present": true, "on": true, "ok": false, "model": "sidenote-gemma4:26b", "error": "the local LLM server does not answer"}'
state; health_with "$starting"; mv "$work/state/health.json" "$work/state/first.json"
health_with '{"present": true, "on": true, "ok": true, "model": "sidenote-gemma4:26b", "loaded": null}'
mv "$work/state/health.json" "$work/state/health-later.json"; mv "$work/state/first.json" "$work/state/health.json"
EXTRA_ENV="SIDENOTE_LANG=en" run up; came="$(cat "$work/out")"
state; health_with "$starting"; began=$SECONDS
EXTRA_ENV="SIDENOTE_LANG=en" run up; never="$(cat "$work/out")"; took=$((SECONDS - began))
if grep -qF "Local model: idle (sidenote-gemma4:26b)" <<<"$came" && ! grep -qF "not responding (./sidenote llm logs)" <<<"$came"; then
  ok "up gives a local model server that is starting its moment, and reports how it stands"
else bad "up gives a local model server that is starting its moment, and reports how it stands" "$(grep -F "Local model" <<<"$came")"; fi
if grep -qF "Local model: not responding (./sidenote llm logs)" <<<"$never" && [ "$took" -lt 30 ]; then
  ok "up still says not responding of one that does not come, and goes on after a bounded wait"
else bad "up still says not responding of one that does not come, and goes on after a bounded wait" "$took s: $(grep -F "Local model" <<<"$never")"; fi

# 43. Who the server runs as: this user, whose 600 login files it has to read, and root where that root is this user. A run
#     as root with no capabilities reads neither, and says "login needed" while `./sidenote login` says "signed in".
state; run up; plain="$(cat "$work/state/compose-env" 2>/dev/null)"
state rootless; run up; rootless="$(cat "$work/state/compose-env" 2>/dev/null)"
if [ "${plain%% *}" = 1000:1001 ]; then ok "up passes this user to compose"
else bad "up passes this user to compose" "$plain"; fi
if [ "${rootless%% *}" = 0:0 ]; then ok "under rootless Docker up keeps the container's root, which is this user"
else bad "under rootless Docker up keeps the container's root, which is this user" "$rootless"; fi

# 44. What Docker would make as root for a mount that is missing, made first as this user; a new log folder is private.
state; rm -rf "$work/home/.claude" "$work/home/.codex" "$work/newlogs"
EXTRA_ENV="SIDENOTE_LOG_PATH=$work/newlogs/here" run up
if [ -d "$work/home/.claude/backups" ] && [ -d "$work/home/.claude/sessions" ] && [ -d "$work/home/.codex" ]; then
  ok "up makes the agents' folders itself, before Docker would"
else bad "up makes the agents' folders itself, before Docker would" "$(ls -A "$work/home/.claude" 2>&1 | tr '\n' ' ')"; fi
if [ "$(stat -c %a "$work/newlogs/here" 2>/dev/null)" = 700 ]; then ok "a new log folder is this user's alone"
else bad "a new log folder is this user's alone" "mode $(stat -c %a "$work/newlogs/here" 2>&1)"; fi

# 45. compose.yaml as the launcher beside it is meant to fill it in: the user in the server and in its home, the service that
#     hands the folders over and that the server waits for, and no one's own time zone as the default.
tree="$(dirname "$launcher")"
compose_text="$(cat "$tree/compose.yaml" 2>/dev/null)"
if grep -qF 'user: "${SIDENOTE_UID:-0}:${SIDENOTE_GID:-0}"' <<<"$compose_text" \
   && grep -qF '/root:size=256m,uid=${SIDENOTE_UID:-0}' <<<"$compose_text" \
   && grep -qF 'service_completed_successfully' <<<"$compose_text" && grep -qF 'server-init:' <<<"$compose_text"; then
  ok "compose.yaml runs the server as the user passed in, after the folders are handed over, and as root by default"
else bad "compose.yaml runs the server as the user passed in, after the folders are handed over, and as root by default"; fi
if ! grep -qF 'Asia/Seoul' "$tree/compose.yaml" "$tree/deploy/helm/sidenote/values.yaml" 2>/dev/null \
   && [ -f "$tree/compose.yaml" ]; then ok "neither compose.yaml nor the chart assumes one country's time zone"
else bad "neither compose.yaml nor the chart assumes one country's time zone"; fi

# 46. The time zone: the environment and .env first, then the system's, in order, and only what is a zone's name.
etc="$work/etc"; mkdir -p "$etc" "$work/zoneinfo/Pacific"; : > "$work/zoneinfo/Pacific/Fiji"
tz_of() {                             # the launcher's own function, cut out, with a folder in place of /etc: $1 = TZ
  { sed -n '/^host_tz() {$/,/^}$/p' "$launcher"
    printf 'setting() { printf %%s "$TZ_GIVEN"; }\nhost_tz "$1"\n'; } > "$work/tz.sh"
  TZ_GIVEN="$1" PATH="$work/bin:/usr/bin:/bin" FAKE="$work" bash "$work/tz.sh" "$etc"
}
state; echo 'Asia/Tokyo' > "$work/state/system-tz"; echo 'Europe/Paris' > "$etc/timezone"
ln -sf "$work/zoneinfo/Pacific/Fiji" "$etc/localtime"
a="$(tz_of "America/New_York")"; b="$(tz_of "")"; c="$(tz_of ":/etc/localtime")"
echo 'n/a' > "$work/state/system-tz"; d="$(tz_of "")"
rm -f "$etc/timezone"; e="$(tz_of "")"
rm -f "$etc/localtime"; f="$(tz_of "")"
if [ "$a|$b|$c|$d|$e|$f" = "America/New_York|Asia/Tokyo|Asia/Tokyo|Europe/Paris|Pacific/Fiji|UTC" ]; then
  ok "the time zone: TZ, timedatectl, /etc/timezone, the /etc/localtime link, then UTC, and only a zone's name"
else bad "the time zone: TZ, timedatectl, /etc/timezone, the /etc/localtime link, then UTC, and only a zone's name" "$a|$b|$c|$d|$e|$f"; fi
state; echo 'TZ=Europe/Berlin' > "$work/repo/.env"; run up; from_env="$(cat "$work/state/compose-env" 2>/dev/null)"
EXTRA_ENV="TZ=Asia/Tokyo" run up; from_shell="$(cat "$work/state/compose-env" 2>/dev/null)"; rm -f "$work/repo/.env"
if [ "${from_env##* }" = Europe/Berlin ] && [ "${from_shell##* }" = Asia/Tokyo ]; then ok "up gives compose .env's TZ, and the environment's over it"
else bad "up gives compose .env's TZ, and the environment's over it" "$from_env | $from_shell"; fi

# 47. A path with Korean in it, read from PowerShell and handed back to it: as bytes of the console's code page it is no
#     longer that path, and the shortcut could not be made.
state korean-desktop; run shortcut; last_call_with ps "CreateShortcut"
if [[ ${CALL[*]:-} == *'바탕 화면\Sidenote Capture.lnk'* ]]; then ok "a Windows path with Korean in it comes back from PowerShell whole"
else bad "a Windows path with Korean in it comes back from PowerShell whole" "$(grep -a -m1 -o 'CreateShortcut([^)]*)' <<<"${CALL[*]:-}")"; fi

# 48. No python3: it is said first. It used to pick the CPU's compose file for an NVIDIA GPU and end `up` in the middle of its
#     status with status 127 and no word of why.
mkdir -p "$work/nopy"
for tool in /usr/bin/* /bin/*; do
  case "${tool##*/}" in python*|pydoc*) ;; *) ln -sf "$tool" "$work/nopy/${tool##*/}" 2>/dev/null ;; esac
done
state; EXTRA_ENV="PATH=$work/bin:$work/nopy SIDENOTE_LANG=en" run status; said_status="$(cat "$work/out")"; rc_status="$(cat "$work/rc")"
EXTRA_ENV="PATH=$work/bin:$work/nopy SIDENOTE_LANG=en" run help; rc_help="$(cat "$work/rc")"
if [ "$rc_status" = 1 ] && grep -qF "python3 is not installed" <<<"$said_status" && [ "$rc_help" = 0 ]; then
  ok "without python3 a command says so, and help still answers"
else bad "without python3 a command says so, and help still answers" "status $rc_status: $(tail -1 <<<"$said_status"); help $rc_help"; fi

# 49. A first install: no model and no login are what comes next, in the README's order, and not a failed install. doctor
#     asked later still fails on them, and an install with something really missing still fails.
fresh='{"present": true, "on": true, "ok": false, "missing": true, "fits": true, "model": "sidenote-gemma4:e4b"}'
state; echo "nvidia,Test GPU,16" > "$work/state/gpu"; health_with "$fresh"
python3 - "$work/state/health.json" <<'FIX'
import json, sys
d = json.load(open(sys.argv[1]))
d["engines"]["ready"] = False
d["engines"]["agent"] = {"present": True, "ok": False, "mode": "hard", "login": "./sidenote login"}
json.dump(d, open(sys.argv[1], "w"))
FIX
EXTRA_ENV="SIDENOTE_LANG=en" run install; first="$(cat "$work/out")"; rc_first="$(cat "$work/rc")"
next="$(sed -n '/^Next$/,$p' <<<"$first")"
EXTRA_ENV="SIDENOTE_LANG=en" run doctor; rc_doctor="$(cat "$work/rc")"
if [ "$rc_first" = 0 ] && ! grep -qF "✗" <<<"$first"; then ok "a first install with no model and no login ends well"
else bad "a first install with no model and no login ends well" "exit $rc_first: $(grep -F "✗" <<<"$first" | tr '\n' '|')"; fi
pull_at="$(grep -n "llm pull" <<<"$next" | head -1 | cut -d: -f1)"; up_at="$(grep -n "capture --up" <<<"$next" | head -1 | cut -d: -f1)"
if [ -n "$pull_at" ] && [ -n "$up_at" ] && [ "$pull_at" -lt "$up_at" ] && grep -qF "./sidenote login" <<<"$next"; then
  ok "...and names what is next: the model, the login, the start"
else bad "...and names what is next: the model, the login, the start" "$next"; fi
if ! grep -qF "Until then the agent solves every problem" <<<"$first" && ! grep -qF "The agent solves every problem" <<<"$first"; then
  ok "...and does not promise an agent that is not signed in"
else bad "...and does not promise an agent that is not signed in"; fi
if [ "$rc_doctor" = 1 ]; then ok "doctor asked later still fails on them"; else bad "doctor asked later still fails on them" "exit $rc_doctor"; fi
state no-py; health_with "$fresh"; EXTRA_ENV="SIDENOTE_LANG=en" run install; rc_broken="$(cat "$work/rc")"
if [ "$rc_broken" = 1 ]; then ok "an install with something really missing still fails"; else bad "an install with something really missing still fails" "exit $rc_broken"; fi

# 50. uninstall takes the images the setup pulled too, says what stays, and one that another project is running stops nothing.
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall; listed="$(cat "$work/out")"
state image-in-use; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --yes; rc_gone="$(cat "$work/rc")"; last_call_with docker "searxng/searxng"
search_rm="${CALL[*]:-}"; last_call_with docker "ollama/ollama"
if grep -qF "ollama/ollama:" <<<"$listed" && grep -qF "searxng/searxng:" <<<"$listed" && grep -qF "Windows Python" <<<"$listed"; then
  ok "uninstall lists the pulled images, and the capture packages it leaves in Windows Python"
else bad "uninstall lists the pulled images, and the capture packages it leaves in Windows Python" "$(grep -F "Images" <<<"$listed")"; fi
if [ "$rc_gone" = 0 ] && [[ $search_rm == "image rm searxng/searxng:"* ]] && [[ ${CALL[*]:-} != *" -f "* ]]; then
  ok "uninstall --yes removes them unforced, and goes on past one that is in use"
else bad "uninstall --yes removes them unforced, and goes on past one that is in use" "exit $rc_gone; $search_rm; ${CALL[*]:-}"; fi

# 43. A PC with no internet (docs/air-gapped.md): up builds nothing and pulls nothing, and leaves the search engine out; it
#     names what is missing where compose would stop on the pull; a model is not downloaded; and the capture packages come
#     from a folder of wheels. Without the switch nothing of this happens.
state; EXTRA_ENV="SIDENOTE_OFFLINE=1" run up; last_call docker build; o_build=${#CALL[@]}; last_call docker up; o_up=" ${CALL[*]} "; o_rc="$(cat "$work/rc")"
state; run up; last_call docker build; p_build=${#CALL[@]}; last_call docker up; p_up=" ${CALL[*]} "
if [ "$o_rc" = 0 ] && [ "$o_build" = 0 ] && [[ $o_up == *" --no-build --pull never "* ]] && [[ $o_up == *" server runner llm "* ]]; then
  ok "offline, up builds nothing, pulls nothing and starts the server, the runner and the local model"
else bad "offline, up builds nothing, pulls nothing and starts the server, the runner and the local model" "rc $o_rc, build calls $o_build, up:$o_up"; fi
if [ "$p_build" -gt 0 ] && [[ $p_up != *" --pull never "* ]] && [[ $p_up != *" server runner"* ]]; then ok "...and without the switch up is as it was"
else bad "...and without the switch up is as it was" "build calls $p_build, up:$p_up"; fi
state no-image; EXTRA_ENV="SIDENOTE_OFFLINE=1 SIDENOTE_LANG=en" run up; last_call docker up; none=${#CALL[@]}
if [ "$(cat "$work/rc")" != 0 ] && [ "$none" = 0 ] && said "sidenote:local is not on this PC" && said "docs/air-gapped.md"; then ok "offline, an image that is not here is named, with the way out"
else bad "offline, an image that is not here is named, with the way out" "rc $(cat "$work/rc"), compose up calls $none: $(tail -1 "$work/out")"; fi
state; EXTRA_ENV="SIDENOTE_OFFLINE=1 SIDENOTE_LANG=en" run llm pull gemma4:e4b; last_call docker llm-pull; pulled=${#CALL[@]}
if [ "$(cat "$work/rc")" != 0 ] && [ "$pulled" = 0 ] && said "docs/air-gapped.md"; then ok "offline, a model is not downloaded, and it says where one comes from"
else bad "offline, a model is not downloaded, and it says where one comes from" "rc $(cat "$work/rc"), pulls $pulled: $(tail -1 "$work/out")"; fi
state; EXTRA_ENV="SIDENOTE_WHEELS=/mnt/c/bundle/wheels" run setup-capture; last_call cmd pip; wheels=" ${CALL[*]-} "
state; run setup-capture; last_call cmd pip; online=" ${CALL[*]-} "
if [[ $wheels == *" --no-index --find-links "* ]] && [[ $online != *"--no-index"* ]]; then ok "the capture packages come from a folder of wheels when one is named"
else bad "the capture packages come from a folder of wheels when one is named" "with:$wheels without:$online"; fi

# 44. A model server already running (SIDENOTE_LOCAL_URL, docs/air-gapped.md): up names the services and leaves the llm
#     container out, offline too; llm pull and install say whose models they are and pull nothing; with Ollama's own
#     address, or none, everything is as it was.
other="http://model-server.internal:8000/v1"
state; EXTRA_ENV="SIDENOTE_LOCAL_URL=$other" run up; last_call docker up; x_up=" ${CALL[*]} "; x_rc="$(cat "$work/rc")"
state; EXTRA_ENV="SIDENOTE_OFFLINE=1 SIDENOTE_LOCAL_URL=$other" run up; last_call docker up; xo_up=" ${CALL[*]} "
state; EXTRA_ENV="SIDENOTE_LOCAL_URL=http://llm:11434/v1" run up; last_call docker up; own_up=" ${CALL[*]} "
state; EXTRA_ENV="SIDENOTE_OFFLINE=1 SIDENOTE_LOCAL_URL=http://llm:11434/v1" run up; last_call docker up; owno_up=" ${CALL[*]} "
if [ "$x_rc" = 0 ] && [[ $x_up == *" server runner searxng "* ]] && [[ $x_up != *" llm "* ]] \
   && [[ $xo_up == *" server runner "* ]] && [[ $xo_up != *" llm "* ]]; then
  ok "with another model server up starts the server, the runner and the search engine, and no llm container"
else bad "with another model server up starts the server, the runner and the search engine, and no llm container" "rc $x_rc, up:$x_up, offline:$xo_up"; fi
if [[ $own_up != *" server runner"* ]] && [[ $owno_up == *" server runner llm "* ]]; then ok "...and with Ollama's own address up is as it was"
else bad "...and with Ollama's own address up is as it was" "up:$own_up, offline:$owno_up"; fi
state; EXTRA_ENV="SIDENOTE_LOCAL_URL=$other SIDENOTE_LANG=en" run llm pull gemma4:e4b; last_call docker llm-pull; pulled=${#CALL[@]}
if [ "$(cat "$work/rc")" != 0 ] && [ "$pulled" = 0 ] && said "served by $other"; then ok "...llm pull pulls nothing, and says the models are that server's"
else bad "...llm pull pulls nothing, and says the models are that server's" "rc $(cat "$work/rc"), pulls $pulled: $(tail -1 "$work/out")"; fi
state; EXTRA_ENV="SIDENOTE_LOCAL_URL=$other SIDENOTE_LANG=en" run install; last_call docker llm-pull; pulled=${#CALL[@]}
if [ "$pulled" = 0 ] && said "Served by $other (SIDENOTE_LOCAL_URL): no model to download here"; then ok "...and install points at no download"
else bad "...and install points at no download" "pulls $pulled: $(grep -F "3/4" -A2 "$work/out" | tr '\n' ' ')"; fi

# 45. A Mac (uname says Darwin): it reads its own screen with no X11 display, so capture goes on past that to the server,
#     doctor does not ask for one, and open uses macOS's own open. On Linux with no DISPLAY, capture still stops there.
mkdir -p "$work/macbin"
printf '#!/usr/bin/env bash\necho Darwin\n' > "$work/macbin/uname"
printf '#!/usr/bin/env bash\nprintf "%%s\\0" "$@" > "$FAKE/calls/open.$(date +%%s%%N)"\n' > "$work/macbin/open"
chmod +x "$work/macbin/uname" "$work/macbin/open"
mac="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/macbin:$work/venvbin:$work/bin:/usr/bin:/bin"
state server-down; EXTRA_ENV="$mac" run capture; mac_capture="$(cat "$work/out")"
state server-down; EXTRA_ENV="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/venvbin:$work/bin:/usr/bin:/bin" run capture; linux_capture="$(cat "$work/out")"
state; EXTRA_ENV="$mac" run doctor; mac_doctor="$(cat "$work/out")"
state; EXTRA_ENV="$mac" run open; last_call open "http://127.0.0.1:8777"; opened=${#CALL[@]}
if ! grep -qF "X11" <<<"$mac_capture$mac_doctor" && grep -qF "The server is off" <<<"$mac_capture" \
   && grep -qF "No X11 display" <<<"$linux_capture" && [ "$opened" -gt 0 ]; then
  ok "on a Mac capture needs no X11 display, doctor asks for none, and open uses macOS's open"
else bad "on a Mac capture needs no X11 display, doctor asks for none, and open uses macOS's open" \
         "mac capture: $(tail -1 <<<"$mac_capture"); linux: $(tail -1 <<<"$linux_capture"); X11 in doctor: $(grep -c X11 <<<"$mac_doctor"); open calls: $opened"; fi

# On a Linux desktop too, capture --up with the capture running opens the panel and ends well, as on WSL; a plain capture is
# told and fails (xdg-open is the stand-in: no browser opens anywhere)
lnx="WSL_DISTRO_NAME= SIDENOTE_LANG=en DISPLAY=:0 PATH=$work/venvbin:$work/bin:/usr/bin:/bin"   # xdg-open: the stand-in in bin
state linux-capture; EXTRA_ENV="$lnx" run capture --up; lup="$(cat "$work/out")"; lup_rc="$(cat "$work/rc")"
last_call xdg "http://127.0.0.1:8777"; lopened=${#CALL[@]}
state linux-capture; EXTRA_ENV="$lnx" run capture; lplain="$(cat "$work/out")"; lplain_rc="$(cat "$work/rc")"
if [ "$lup_rc" = 0 ] && grep -qF "already running" <<<"$lup" && [ "$lopened" -gt 0 ] \
   && [ "$lplain_rc" != 0 ] && grep -qF "already running" <<<"$lplain"; then
  ok "on Linux, capture --up with the capture running opens the panel and ends well; a plain capture is told and fails"
else bad "on Linux, capture --up with the capture running opens the panel and ends well; a plain capture is told and fails" \
         "--up rc $lup_rc, opened $lopened: $(tail -1 <<<"$lup") | plain rc $lplain_rc: $(tail -1 <<<"$lplain")"; fi
# A capture started on a Linux desktop says where its tray icon is, and with --no-tray that it has none: it said there
# was one in the notification area
state; EXTRA_ENV="$lnx" run capture; lstart="$(cat "$work/out")"
state; EXTRA_ENV="$lnx" run capture --no-tray; lnotray="$(cat "$work/out")"; lnotray_rc="$(cat "$work/rc")"
if grep -qF "(a tray icon, where the desktop shows them)" <<<"$lstart" && [ "$lnotray_rc" = 0 ] && grep -qF "(no tray icon)" <<<"$lnotray" \
   && ! grep -qF "a tray icon, where" <<<"$lnotray"; then
  ok "on Linux, a capture started says where its tray icon is, and with --no-tray that it has none"
else bad "on Linux, a capture started says where its tray icon is, and with --no-tray that it has none" \
         "plain: $(grep -F "capture started" <<<"$lstart" | tail -1) | --no-tray rc $lnotray_rc: $(grep -F "capture started" <<<"$lnotray" | tail -1)"; fi

# 46. Claude Code on a Mac keeps its login in the Keychain, which the server in Docker cannot read, so there the login that
#     counts is a token in .env. With the Mac's own Claude Code signed in and no token, doctor says the agent is not signed
#     in (it used to say "the server uses this login"). login makes a token with `claude setup-token` and reads it pasted
#     at the terminal, showing nothing: a token copied as two lines (wider than the window), the whole block the command
#     printed and the line it suggests all give the token; a line with no token in it is refused. The token takes the
#     place of an old one in .env, keeps the rest of the file, and leaves the file this user's alone. A server made before
#     the token is started again with it, and one that rejected the token gets a new one. Without Claude Code on the Mac a
#     token still counts. On Linux the same Claude Code login is the server's.
mkdir -p "$work/macclaude"
cat > "$work/macclaude/claude" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  --version) echo "2.1.307 (Claude Code)" ;;
  auth) echo '{"loggedIn": true, "authMethod": "claude.ai"}' ;;   # this PC's own login, which on a Mac is in the Keychain
  setup-token) touch "$FAKE/state/token-made"; printf 'Your OAuth token (valid for 1 year):\n\nsk-ant-oat01-PRINTED\n' ;;
esac
STUB
chmod +x "$work/macclaude/claude"
# run, with a terminal as the launcher's input: $1 is typed into it as it is ("\n" is Enter, EOF is Ctrl+D) once the
# launcher has printed $2. What the terminal itself shows of it (its echo) is kept in $work/tty. The launcher runs in a
# session of its own, and is ended with all it started if it outlasts the minute.
run_tty() {
  local typed="$1" asked="$2"; shift 2
  rm -rf "$work/calls"/* && mkdir -p "$work/calls"
  env -i TMPDIR="$work" PATH="$work/bin:/usr/bin:/bin" HOME="$work/home" FAKE="$work" WSL_DISTRO_NAME="${WSL_DISTRO_NAME:-Ubuntu}" \
      SIDENOTE_LOG_PATH="$work/logs" SIDENOTE_LANG=ko ${EXTRA_ENV:-} \
      python3 -c '
import os, select, subprocess, sys, time
typed, asked, out, tty, cmd = sys.argv[1], sys.argv[2].encode(), sys.argv[3], sys.argv[4], sys.argv[5:]
master, slave = os.openpty()
with open(out, "wb") as f:
    p = subprocess.Popen(cmd, stdin=slave, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
os.close(slave)
shown, end = b"", time.time() + 70
while p.poll() is None and time.time() < end:
    if asked and asked in open(out, "rb").read():
        os.write(master, b"\x04" if typed == "EOF" else typed.encode())
        asked = b""
    if select.select([master], [], [], 0.05)[0]:
        try:
            shown += os.read(master, 4096)
        except OSError:
            pass
if p.poll() is None:
    os.killpg(p.pid, 9)
open(tty, "wb").write(shown)
sys.exit(p.wait())
' "$typed" "$asked" "$work/out" "$work/tty" timeout 60 bash "$work/repo/sidenote" "$@"
  echo $? > "$work/rc"
}
mac_claude="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/macbin:$work/macclaude:$work/venvbin:$work/bin:/usr/bin:/bin"
env_now() { cat "$work/repo/.env" 2>/dev/null; }
made() { [ -f "$work/state/token-made" ] && echo 1 || echo 0; }
# .env as each paste below finds it: an empty token, as a first edit of .env might leave, in a file others may read
fresh_env() { printf 'KEEP_ME=1\nexport CLAUDE_CODE_OAUTH_TOKEN=\n' > "$work/repo/.env"; chmod 644 "$work/repo/.env"; }
fresh_env; start_env="$(env_now)"
state; EXTRA_ENV="$mac_claude" run doctor; mac_none="$(cat "$work/out")"
state; EXTRA_ENV="$mac_claude" run login; nottl_rc="$(cat "$work/rc")"; nottl="$(cat "$work/out")"; nottl_env="$(env_now)"
state; EXTRA_ENV="$mac_claude" run_tty EOF "Paste the token" login; eof_rc="$(cat "$work/rc")"; eof="$(cat "$work/out")"; eof_env="$(env_now)"
state; EXTRA_ENV="$mac_claude" run_tty $'export CLAUDE_CODE_OAUTH_TOKEN=<token>\n' "Paste the token" login
hint_rc="$(cat "$work/rc")"; hint="$(cat "$work/out")"; hint_env="$(env_now)"
fresh_env; state; EXTRA_ENV="$mac_claude" run_tty $'sk-ant-oat01-FIRSTHALF0123456789\nSECONDHALF-abc_xyz' "Paste the token" login
two_rc="$(cat "$work/rc")"; two="$(cat "$work/out")"; two_tty="$(cat "$work/tty")"; two_env="$(env_now)"; two_made="$(made)"
two_mode="$(stat -c %a "$work/repo/.env" 2>/dev/null || stat -f %Lp "$work/repo/.env")"
fresh_env; state; EXTRA_ENV="$mac_claude" run_tty $'Your OAuth token (valid for 1 year):\n\n  sk-ant-oat01-WHOLEBLOCK0123456789abc\n\nStore this token securely.\n' "Paste the token" login
block_env="$(env_now)"
fresh_env; state; EXTRA_ENV="$mac_claude" run_tty $'export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-EXPORTED0123456789abc\n' "Paste the token" login
export_env="$(env_now)"
state; EXTRA_ENV="$mac_claude" run doctor; mac_token="$(cat "$work/out")"
state; EXTRA_ENV="$mac_claude" run login; again="$(cat "$work/out")"; made_again="$(made)"
state; EXTRA_ENV="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/macbin:$work/venvbin:$work/bin:/usr/bin:/bin" run doctor; no_cli="$(cat "$work/out")"
# a server made before the token: it holds none
state server-running; health_with '{"present": false}'
EXTRA_ENV="$mac_claude" run doctor; stale_doctor="$(cat "$work/out")"
EXTRA_ENV="$mac_claude" run login; stale="$(cat "$work/out")"; last_call docker up; stale_up=${#CALL[@]}; stale_made="$(made)"
# a server that holds the token and has had it rejected
state server-running; health_with '{"present": false}'
python3 -c 'import json, sys; p = sys.argv[1]; d = json.load(open(p)); d["auth"] = {"rejected": True}; json.dump(d, open(p, "w"))' "$work/state/health.json"
printf 'sk-ant-oat01-EXPORTED0123456789abc' > "$work/state/served-token"
EXTRA_ENV="$mac_claude" run_tty $'sk-ant-oat01-RENEWED0123456789abcd\n' "Paste the token" login; renewed="$(cat "$work/out")"
last_call docker up; renew_up=${#CALL[@]}; renewed_env="$(env_now)"
state; EXTRA_ENV="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/macclaude:$work/venvbin:$work/bin:/usr/bin:/bin" run doctor; linux_claude="$(cat "$work/out")"
rm -f "$work/repo/.env"
if grep -qF "Claude Code not signed in (./sidenote login)" <<<"$mac_none" && ! grep -qF "the server uses this login" <<<"$mac_none"; then
  ok "on a Mac, Claude Code's own login is not the server's: doctor says it is not signed in"
else bad "on a Mac, Claude Code's own login is not the server's: doctor says it is not signed in" "$(grep -F "Claude Code" <<<"$mac_none")"; fi
if [ "$nottl_rc" != 0 ] && grep -qF "Run the login in a terminal" <<<"$nottl" && [ "$nottl_env" = "$start_env" ]; then
  ok "...login with no terminal says where to run it and leaves .env alone"
else bad "...login with no terminal says where to run it and leaves .env alone" "exit $nottl_rc: $(tail -1 <<<"$nottl"); .env: $nottl_env"; fi
if [ "$eof_rc" != 0 ] && grep -qF "No token was pasted" <<<"$eof" && [ "$eof_env" = "$start_env" ]; then
  ok "...Ctrl+D at the prompt says no token was pasted, and leaves .env alone"
else bad "...Ctrl+D at the prompt says no token was pasted, and leaves .env alone" "exit $eof_rc: $(tail -1 <<<"$eof"); .env: $eof_env"; fi
if [ "$hint_rc" != 0 ] && grep -qF "That is not the token claude setup-token printed" <<<"$hint" && [ "$hint_env" = "$start_env" ]; then
  ok "...a line with no token in it is refused, and .env is left alone"
else bad "...a line with no token in it is refused, and .env is left alone" "exit $hint_rc: $(tail -1 <<<"$hint"); .env: $hint_env"; fi
if [ "$two_rc" = 0 ] && [ "$two_made" = 1 ] && [ "$two_env" = "$(printf 'KEEP_ME=1\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-FIRSTHALF0123456789SECONDHALF-abc_xyz')" ] \
   && grep -qF "Token saved in .env" <<<"$two" && grep -qF "Next: ./sidenote up" <<<"$two"; then
  ok "...a token pasted as two lines is saved whole, in place of the old line, with the rest of .env kept"
else bad "...a token pasted as two lines is saved whole, in place of the old line, with the rest of .env kept" \
         "exit $two_rc, made $two_made, .env: $(tr '\n' '|' <<<"$two_env"); $(tail -2 <<<"$two" | tr '\n' '|')"; fi
if ! grep -qF "FIRSTHALF" <<<"$two_tty$two" && [ "$two_mode" = 600 ]; then ok "...nothing of it is shown or printed, and .env is this user's alone"
else bad "...nothing of it is shown or printed, and .env is this user's alone" "mode $two_mode; shown: $(tr -cd '[:print:]' <<<"$two_tty" | cut -c1-80)"; fi
if [ "$block_env" = "$(printf 'KEEP_ME=1\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-WHOLEBLOCK0123456789abc')" ] \
   && [ "$export_env" = "$(printf 'KEEP_ME=1\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-EXPORTED0123456789abc')" ]; then
  ok "...the whole block the command printed, or the export line, gives the token alone"
else bad "...the whole block the command printed, or the export line, gives the token alone" "$(tr '\n' '|' <<<"$block_env") / $(tr '\n' '|' <<<"$export_env")"; fi
if grep -qF "signed in (token in .env), and the server uses this login" <<<"$mac_token" \
   && grep -qF "The server signs in with the token in .env" <<<"$again" && [ "$made_again" = 0 ] \
   && grep -qF "signed in (token in .env), and the server uses this login" <<<"$no_cli"; then
  ok "...with a token, doctor and login say so (doctor without Claude Code on the Mac too), and login makes no other"
else bad "...with a token, doctor and login say so (doctor without Claude Code on the Mac too), and login makes no other" \
         "$(grep -F "Claude Code" <<<"$mac_token"); $(tail -1 <<<"$again"); made again: $made_again; no CLI: $(grep -F "Claude Code" <<<"$no_cli")"; fi
if grep -qF "the server started before the token in .env (./sidenote login)" <<<"$stale_doctor" && grep -qF "The server started before this token" <<<"$stale" \
   && [ "$stale_up" -gt 0 ] && [ "$stale_made" = 0 ]; then
  ok "...a server made before the token: doctor says so, and login starts it again with it and makes none"
else bad "...a server made before the token: doctor says so, and login starts it again with it and makes none" \
         "$(grep -F "Claude Code" <<<"$stale_doctor"); compose up calls $stale_up, made $stale_made; $(tail -1 <<<"$stale")"; fi
if grep -qF "rejected the token in .env" <<<"$renewed" && [ "$renewed_env" = "$(printf 'KEEP_ME=1\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-RENEWED0123456789abcd')" ] \
   && [ "$renew_up" -gt 0 ]; then
  ok "...a token the server rejected is made again, and the server is started again with it"
else bad "...a token the server rejected is made again, and the server is started again with it" \
         "compose up calls $renew_up, .env: $(tr '\n' '|' <<<"$renewed_env"); $(tail -2 <<<"$renewed" | tr '\n' '|')"; fi
if grep -qF "signed in (claude.ai), and the server uses this login" <<<"$linux_claude"; then ok "...and on Linux the PC's own Claude Code login is the server's, as before"
else bad "...and on Linux the PC's own Claude Code login is the server's, as before" "$(grep -F "Claude Code" <<<"$linux_claude")"; fi

# The desktop shortcut clicked while its capture program runs opens the panel and ends well (it ended in a failure box
# saying the capture was running); the terminal's capture, with no --up, is told and fails, as before.
state running; EXTRA_ENV="SIDENOTE_LANG=en" run capture --up; again="$(cat "$work/out")"; again_rc="$(cat "$work/rc")"
last_call_with cmd "127.0.0.1:"; opened="${CALL[*]-}"
state running; EXTRA_ENV="SIDENOTE_LANG=en" run capture; term="$(cat "$work/out")"; term_rc="$(cat "$work/rc")"
if [ "$again_rc" = 0 ] && grep -qF "The capture is already running" <<<"$again" && [[ $opened == *start* ]] \
   && [ "$term_rc" != 0 ] && grep -qF "Quit it from the tray icon" <<<"$term"; then
  ok "capture --up with the capture running opens the panel and ends well; the terminal's capture is told and fails"
else bad "capture --up with the capture running opens the panel and ends well; the terminal's capture is told and fails" \
         "--up rc $again_rc, open call: ${opened:-none}: $(tail -1 <<<"$again") | plain rc $term_rc: $(tail -1 <<<"$term")"; fi

# --- Windows off WSL's PATH ([interop] appendWindowsPath=false), interop off, no Windows drive -----------------------
# The stand-ins move from the PATH to a Windows drive the mount table names, as on a WSL whose wsl.conf leaves the Windows
# folders off the PATH: the launcher finds cmd.exe and powershell.exe there by their full paths (it said "no Windows
# Python" and capture did not start). With a real cmd.exe (a PE file) and no WSLInterop entry, and with no Windows drive
# at all, it says why Windows is out of reach, ends with a failing status and asks nothing of it.
mkdir -p "$work/nowin" "$work/drive/Windows/System32/WindowsPowerShell/v1.0" "$work/pe/Windows/System32" "$work/binfmt" "$work/wsl1"
: > "$work/binfmt/register"   # binfmt_misc mounted, as on WSL 2; $work/wsl1 has none, as on WSL 1
for f in "$work/bin/"*; do case "$(basename "$f")" in cmd.exe|powershell.exe) ;; *) ln -sf "$f" "$work/nowin/" ;; esac; done
cp "$work/bin/cmd.exe" "$work/drive/Windows/System32/cmd.exe"
cp "$work/bin/powershell.exe" "$work/drive/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
printf 'MZ\220\0' > "$work/pe/Windows/System32/cmd.exe"                         # a Windows program's first bytes
# Never executable: on WSL an executable file that starts with MZ is handed to Windows, which cannot run these four bytes
# and puts "Unsupported 16-Bit Application" on the user's screen. The launcher only reads its first bytes here
chmod 0644 "$work/pe/Windows/System32/cmd.exe"
[ ! -x "$work/pe/Windows/System32/cmd.exe" ] || { echo "the stand-in Windows program is executable: stopped before anything runs it"; exit 2; }
printf 'C:\\134 %s 9p rw,aname=drvfs 0 0\n' "$work/drive" > "$work/mounts"     # as /proc/mounts lists a WSL drive
printf 'C:\\134 %s 9p rw,aname=drvfs 0 0\n' "$work/pe" > "$work/mounts-pe"
nowin="PATH=$work/nowin:/usr/bin:/bin SIDENOTE_BINFMT=$work/binfmt"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts" run doctor; nowin_doctor="$(cat "$work/out")"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts" run capture --console --list-monitors; last_call cmd --list-monitors
nowin_list="${CALL[*]-}"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts" run capture --monitor 2; wait_started; nowin_start="$(cat "$work/rc")"
if grep -qF "Windows Python: Python 3.14.0" <<<"$nowin_doctor" && [ -n "$nowin_list" ] && [ "$nowin_start" = 0 ] \
   && [ -f "$work/state/running" ]; then
  ok "Windows off WSL's PATH: cmd.exe and powershell.exe are found on the Windows drive, and capture starts"
else bad "Windows off WSL's PATH: cmd.exe and powershell.exe are found on the Windows drive, and capture starts" \
         "$(grep -F "Python" <<<"$nowin_doctor" | head -2 | tr '\n' '|') list call: ${nowin_list:-none}, capture rc $nowin_start"; fi
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture; off="$(cat "$work/out")"; off_rc="$(cat "$work/rc")"
off_calls="$(calls_of cmd | wc -l)"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run shortcut --remove; off_short="$(cat "$work/out")"; off_short_rc="$(cat "$work/rc")"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture-stop; off_stop="$(cat "$work/out")"; off_stop_rc="$(cat "$work/rc")"
state running; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture-stop; off_stopped="$(cat "$work/out")"; off_stopped_rc="$(cat "$work/rc")"
state running unkillable; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture-stop; off_left="$(cat "$work/out")"; off_left_rc="$(cat "$work/rc")"
state server-down; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture-stop; off_down="$(cat "$work/out")"; off_down_rc="$(cat "$work/rc")"
state; EXTRA_ENV="PATH=$work/nowin:/usr/bin:/bin SIDENOTE_BINFMT=$work/wsl1 SIDENOTE_KERNEL=4.4.0-19041-Microsoft SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run doctor; wsl1="$(cat "$work/out")"
state; EXTRA_ENV="PATH=$work/nowin:/usr/bin:/bin SIDENOTE_BINFMT=$work/wsl1 SIDENOTE_KERNEL=5.15.167.4-microsoft-standard-WSL2 SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run doctor; unmounted="$(cat "$work/out")"
echo enabled > "$work/binfmt/WSLInterop"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run doctor; on_doctor="$(cat "$work/out")"
rm -f "$work/binfmt/WSLInterop"
if grep -qF "interop is off" <<<"$off" && grep -qF -- "launch.pyw\" --setup --distro $distro --repo \"" <<<"$off" \
   && [ "$off_rc" != 0 ] && [ "$off_calls" = 0 ] && ! grep -qF "interop" <<<"$on_doctor"; then
  ok "...interop off: said with the one command that sets the capture up from Windows, nothing run, and not said when on"
else bad "...interop off: said with the one command that sets the capture up from Windows, nothing run, and not said when on" \
         "rc $off_rc, cmd calls $off_calls: $(tail -1 <<<"$off")"; fi
if grep -qF "interop is off" <<<"$off_short" && [ "$off_short_rc" != 0 ]; then
  ok "...and shortcut --remove says it too (it ended silently)"
else bad "...and shortcut --remove says it too (it ended silently)" "shortcut rc $off_short_rc: $(tail -1 <<<"$off_short")"; fi
# capture-stop reads the server's count, which interop does not touch: a program started from Windows is asked to end and
# is gone (it said "failed" and pointed at the setting), one that stays is said with where to end it, and with the server
# off, that nothing can be known from here
if grep -qF "No capture program is connected" <<<"$off_stop" && [ "$off_stop_rc" = 0 ] \
   && grep -qF "Capture stopped" <<<"$off_stopped" && [ "$off_stopped_rc" = 0 ] \
   && grep -qF "still connected" <<<"$off_left" && grep -qF "Task Manager" <<<"$off_left" && [ "$off_left_rc" != 0 ] \
   && grep -qF "not known" <<<"$off_down" && [ "$off_down_rc" != 0 ] && ! grep -qF "by force" <<<"$off_down"; then
  ok "...and capture-stop asks through the server and reads its count: stopped, none, one left, or not known"
else bad "...and capture-stop asks through the server and reads its count: stopped, none, one left, or not known" \
         "none rc $off_stop_rc: $(tail -1 <<<"$off_stop") | one rc $off_stopped_rc: $(tail -1 <<<"$off_stopped") | left rc $off_left_rc: $(tail -1 <<<"$off_left") | down rc $off_down_rc: $(tail -1 <<<"$off_down")"; fi
if ! grep -qF "interop is off" <<<"$wsl1" && grep -qF "interop is off" <<<"$unmounted"; then
  ok "...WSL 1 (its kernel) is not judged, and WSL 2 with no binfmt_misc mounted is judged off"
else bad "...WSL 1 (its kernel) is not judged, and WSL 2 with no binfmt_misc mounted is judged off" \
         "WSL 1: $(grep -F interop <<<"$wsl1" | head -1) | WSL 2 unmounted: $(grep -cF "interop is off" <<<"$unmounted")"; fi
state no-py; EXTRA_ENV="SIDENOTE_LANG=en" run capture --list-monitors; nopy_list="$(cat "$work/out")"; nopy_rc="$(cat "$work/rc")"
if grep -qF "No Python (py) on Windows" <<<"$nopy_list" && [ "$nopy_rc" != 0 ] && ! grep -qF "is not recognized" <<<"$nopy_list"; then
  ok "capture --list-monitors without Windows Python says so and fails (cmd.exe's own line, with status 0, was all)"
else bad "capture --list-monitors without Windows Python says so and fails (cmd.exe's own line, with status 0, was all)" "rc $nopy_rc: $nopy_list"; fi
state ps-broken; EXTRA_ENV="SIDENOTE_LANG=en" run shortcut; broken_short="$(cat "$work/out")"
if grep -qF "Could not find the Windows desktop folder" <<<"$broken_short"; then ok "shortcut with PowerShell failing says it found no desktop folder (it ended with no word)"
else bad "shortcut with PowerShell failing says it found no desktop folder (it ended with no word)" "$broken_short"; fi
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=/dev/null SIDENOTE_LANG=en" run setup-capture; gone="$(cat "$work/out")"; gone_rc="$(cat "$work/rc")"
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=/dev/null SIDENOTE_LANG=en" run doctor; gone_doctor="$(cat "$work/out")"
if grep -qF "Windows cannot be found from WSL" <<<"$gone" && [ "$gone_rc" != 0 ] && grep -qF "Windows cannot be found from WSL" <<<"$gone_doctor" \
   && ! grep -qF "No Windows Python" <<<"$gone_doctor"; then
  ok "...no Windows drive: setup-capture and doctor say Windows cannot be found, not that Python is missing"
else bad "...no Windows drive: setup-capture and doctor say Windows cannot be found, not that Python is missing" \
         "rc $gone_rc: $(tail -1 <<<"$gone") | $(grep -F "Windows" <<<"$gone_doctor" | head -1)"; fi

# down reads compose's container list from its stdout alone: the warning compose writes to stderr was taken for a
# container, and "stopped" was said with nothing running; a compose that fails says its error, its last line
state compose-warn; EXTRA_ENV="SIDENOTE_LANG=en" run down; warned="$(cat "$work/out")"
warned_down="$(for f in $(calls_of docker); do tr '\0' ' ' < "$f"; echo; done | grep -c ' down' || true)"
state compose-warn compose-broken; EXTRA_ENV="SIDENOTE_LANG=en" run down; broken="$(cat "$work/out")"; broken_rc="$(cat "$work/rc")"
if grep -qF "Already stopped" <<<"$warned" && [ "$warned_down" = 0 ] \
   && grep -qF "docker compose failed: no configuration file provided" <<<"$broken" && [ "$broken_rc" != 0 ]; then
  ok "down: a warning compose prints is no container, and a failing compose says its error, not the warning"
else bad "down: a warning compose prints is no container, and a failing compose says its error, not the warning" \
         "warned: $(tail -1 <<<"$warned") (down calls $warned_down) | broken rc $broken_rc: $(tail -1 <<<"$broken")"; fi

# With interop off the desktop shortcut still starts the capture: WSL brings the server up and hands the start back, and
# client/launch.pyw starts the program with its own Windows Python (starting a Windows program from Windows asks nothing of
# WSL's interop). A capture program connected already: the panel to open. Nothing is asked of Windows from WSL.
offwin="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en"
state; EXTRA_ENV="$offwin" run capture --up --from-windows --monitor 2; handed="$(cat "$work/out")"; handed_rc="$(cat "$work/rc")"
handed_calls="$(calls_of cmd | wc -l)$(calls_of ps | wc -l)"
start_line="$(grep -a $'^SIDENOTE-START\t' <<<"$handed" | tail -1)"
state running; EXTRA_ENV="$offwin" run capture --up --from-windows; open_line="$(grep -a $'^SIDENOTE-OPEN\t' "$work/out" | tail -1)"
if [ "$handed_rc" = 0 ] && [[ $start_line == *$'\t--server\tws://127.0.0.1:8777/ingest\t--log\t'*$'\t--started\tshortcut\t--monitor\t2' ]] \
   && [ "$handed_calls" = 00 ] && [ "$open_line" = $'SIDENOTE-OPEN\thttp://127.0.0.1:8777' ]; then
  ok "interop off, from the shortcut: the server up and the capture's start handed to Windows (or the panel, one running)"
else bad "interop off, from the shortcut: the server up and the capture's start handed to Windows (or the panel, one running)" \
         "rc $handed_rc, Windows calls $handed_calls, start: ${start_line:-none} | open: ${open_line:-none} | $(tail -1 <<<"$handed")"; fi
state server-down up-starts-server; EXTRA_ENV="$offwin" run capture --up --from-windows --monitor 2
owned_line="$(grep -a $'^SIDENOTE-START\t' "$work/out" | tail -1)"
if [[ $owned_line == *$'\t--monitor\t2\t--stop-server-on-quit\t'"$(wslpath -w "$work/repo")" ]] \
   && [[ $start_line != *stop-server-on-quit* ]]; then
  ok "...a start there that brought the server up hands this checkout on too, and one that found it running does not"
else bad "...a start there that brought the server up hands this checkout on too, and one that found it running does not" \
         "brought up: ${owned_line:-none} | found running: ${start_line:-none}"; fi
mkdir -p "$work/pymods"   # stand-ins for the capture packages, which launch.pyw looks up (never imports) in its own Python
for m in mss soundcard numpy PIL websocket; do mkdir -p "$work/pymods/$m"; : > "$work/pymods/$m/__init__.py"; done
state; EXTRA_ENV="$offwin PYTHONPATH=$work/pymods" run_launch; chain="$(cat "$work/out")"; chain_rc="$(cat "$work/rc")"
if [ "$chain_rc" = 0 ] && grep -qF -- "-X utf8 " <<<"$chain" && grep -qF "capture.py --server ws://127.0.0.1:8777/ingest --log" <<<"$chain" \
   && grep -q '^\[dry-run\] start: ' <<<"$chain" && grep -qF "[dry-run] box: none" <<<"$chain"; then
  ok "...and launch.pyw starts it with its own Python, windowless, and shows no box"
else bad "...and launch.pyw starts it with its own Python, windowless, and shows no box" "rc $chain_rc: $(grep -a '\[dry-run\]' <<<"$chain" | tr '\n' '|')"; fi
state server-down up-starts-server; EXTRA_ENV="$offwin PYTHONPATH=$work/pymods" run_launch; owned_chain="$(cat "$work/out")"
if grep -q '^\[dry-run\] start: ' <<<"$owned_chain" && grep -qF -- "--stop-server-on-quit" <<<"$owned_chain" \
   && ! grep -qF -- "--stop-server-on-quit" <<<"$chain"; then
  ok "...launch.pyw hands the checkout on to the program it starts, after a start that brought the server up"
else bad "...launch.pyw hands the checkout on to the program it starts, after a start that brought the server up" \
         "$(grep -a '\[dry-run\] start' <<<"$owned_chain" | cut -c1-300)"; fi
state; EXTRA_ENV="$offwin PYTHONPATH=$work/nopymods" run_launch; nopkg="$(box_text)"; nopkg_rc="$(cat "$work/rc")"
if [ "$nopkg_rc" != 0 ] && grep -qF "mss" <<<"$nopkg" && grep -qF -- "--setup --distro $distro --repo \"$work/repo\" --port 8777" <<<"$nopkg" \
   && ! grep -q '^\[dry-run\] start: ' "$work/out"; then
  ok "...without the capture packages in that Python it starts nothing and its box gives the setup command"
else bad "...without the capture packages in that Python it starts nothing and its box gives the setup command" "rc $nopkg_rc: $(tr '\n' '|' <<<"$nopkg")"; fi
state; EXTRA_ENV="$offwin" run_launch --setup; setup_out="$(cat "$work/out")"; setup_rc="$(cat "$work/rc")"
if [ "$setup_rc" = 0 ] && grep -qF -- "-m pip install --user -r $(dirname "$launch_pyw")/requirements.txt" <<<"$setup_out" \
   && grep -qF -- "\"$launch_pyw\" --distro $distro --repo \"$work/repo\" --port 8777" <<<"$setup_out" \
   && ! ls "$work/calls"/wsl.* >/dev/null 2>&1; then
  ok "launch.pyw --setup (from Windows): the packages into its own Python and the shortcut the launcher makes, WSL not asked"
else bad "launch.pyw --setup (from Windows): the packages into its own Python and the shortcut the launcher makes, WSL not asked" \
         "rc $setup_rc: $(tr '\n' '|' <<<"$setup_out")"; fi
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run capture --up; term_off="$(cat "$work/out")"
if grep -qF "interop is off" <<<"$term_off" && ! grep -q $'^SIDENOTE-START\t' <<<"$term_off"; then
  ok "...from a terminal (no --from-windows) it is said, with nothing handed on"
else bad "...from a terminal (no --from-windows) it is said, with nothing handed on" "$(tail -2 <<<"$term_off" | tr '\n' '|')"; fi

# --- the history and settings: uninstall --data, backup, restore, llm rm ---------------------------------------------
logs="$work/logs"
here="$work/here"                     # the folder a backup is typed in: a file made with no name lands here
mkdir -p "$here"
# The log folder's files and folders, each with its content's hash: what "nothing changed" is checked against
logsum() { (cd "$logs" 2>/dev/null && find . -type d | LC_ALL=C sort && find . -type f -exec sha256sum {} + | LC_ALL=C sort); }
# A history as the server keeps it (an SQLite file) with one answer in it, and the answer read back from one
mkdb() { python3 -c 'import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("create table answers (id integer, text text)")
c.execute("insert into answers values (1, ?)", (sys.argv[2],)); c.commit(); c.close()' "$1" "$2"; }
answer_in() { python3 -c 'import sqlite3, sys; print(sqlite3.connect(sys.argv[1]).execute("select text from answers").fetchone()[0])' "$1" 2>&1; }
# The log folder as a server leaves it: the history with the two files SQLite keeps beside it, the settings, the
# switches, what the server measured, its logs and their rotated copies, the frames it keeps, and the folders a restore
# and an ended backup leave
fill_logs() {
  rm -rf "$logs" && mkdir -p "$logs/before-restore-20260101-000000" "$logs/.backup.AbC123"
  mkdb "$logs/history.sqlite" "the answer there now"
  local f
  for f in history.sqlite-wal history.sqlite-shm .settings.json .switches.json .pace.json .spend.json .speed.json \
           .account.json .restart.npz stall.txt server.log server.log.1 events.jsonl events.jsonl.3 capture.log capture.log.2 \
           none_7.png none_7_frame.png .ended .settings.tmp; do
    printf 'there now: %s\n' "$f" > "$logs/$f"
  done
  printf 'older\n' > "$logs/before-restore-20260101-000000/history.sqlite"
  printf 'half\n' > "$logs/.backup.AbC123/history.sqlite"
}

# 51. uninstall says in two blocks what goes and what stays: the history and settings stay, with their folder's size,
#     and how to keep a copy or remove them too; --data moves them to what goes. An unknown option removes nothing, and
#     without --yes, --data changes the list alone.
fill_logs; before_sum="$(logsum)"
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall; u_plain="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --data; u_data="$(cat "$work/out")"; u_data_rc="$(cat "$work/rc")"
state; EXTRA_ENV="SIDENOTE_LANG=ko" run uninstall; u_ko="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --bogus; u_bogus="$(cat "$work/out")"; u_bogus_rc="$(cat "$work/rc")"; last_call docker down
u_bogus_down=${#CALL[@]}
kept_block() { sed -n '/^  Kept:/,$p' <<<"$1"; }                  # what the list says stays
gone_block() { sed -n '/Removed with --yes:/,/^  Kept:/p' <<<"$1"; }  # and what goes
if grep -qF "History, settings and logs: $logs (" <<<"$(kept_block "$u_plain")" \
   && ! grep -qF "History, settings" <<<"$(gone_block "$u_plain")" && grep -qF "./sidenote backup" <<<"$u_plain" \
   && grep -qF -- "--data" <<<"$u_plain" && grep -qF "Images:" <<<"$(gone_block "$u_plain")" \
   && grep -qF "~/.claude" <<<"$(kept_block "$u_plain")"; then
  ok "uninstall lists what goes and what stays: the history, settings and logs stay, with their size, a copy and --data named"
else bad "uninstall lists what goes and what stays: the history, settings and logs stay, with their size, a copy and --data named" \
         "$(tr '\n' '|' <<<"$u_plain" | head -c 900)"; fi
if grep -qF "History, settings and logs: $logs (" <<<"$(gone_block "$u_data")" \
   && ! grep -qF "History, settings" <<<"$(kept_block "$u_data")" && grep -qF "./sidenote uninstall --yes --data" <<<"$u_data" \
   && [ "$u_data_rc" = 0 ] && [ "$(logsum)" = "$before_sum" ] \
   && grep -qF "남기는 것:" <<<"$u_ko" && grep -qF "기록, 설정, 로그: $logs (" <<<"$u_ko"; then
  ok "...--data moves them to what goes, and without --yes changes nothing; the same list in Korean"
else bad "...--data moves them to what goes, and without --yes changes nothing; the same list in Korean" \
         "rc $u_data_rc, changed: $([ "$(logsum)" = "$before_sum" ] && echo no || echo yes) | $(tr '\n' '|' <<<"$u_data" | head -c 600)"; fi
if [ "$u_bogus_rc" != 0 ] && grep -qF "Unknown option: --bogus" <<<"$u_bogus" && [ "$u_bogus_down" = 0 ]; then
  ok "...and an option it does not know is said, with nothing removed"
else bad "...and an option it does not know is said, with nothing removed" "rc $u_bogus_rc, down calls $u_bogus_down: $(tail -1 <<<"$u_bogus")"; fi

# 52. uninstall --yes --data removes what Sidenote wrote in the log folder, by name, and the folders a backup and a
#     restore leave there; a file of the user's stays, and the folder with it. With nothing else in it the folder goes
#     too, and a server still running keeps all of it.
fill_logs; printf 'mine\n' > "$logs/notes.txt"
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --data --yes; d_out="$(cat "$work/out")"; d_rc="$(cat "$work/rc")"
d_left="$(cd "$logs" 2>/dev/null && find . | LC_ALL=C sort | tr '\n' ' ')"
fill_logs
state; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --yes --data; d2_out="$(cat "$work/out")"
d2_gone=yes; if [ -e "$logs" ]; then d2_gone=no; fi
fill_logs; d3_before="$(logsum)"
state server-running; EXTRA_ENV="SIDENOTE_LANG=en" run uninstall --yes --data; d3_out="$(cat "$work/out")"; d3_after="$(logsum)"
if [ "$d_rc" = 0 ] && [ "$d_left" = ". ./notes.txt " ] && grep -qF "The folder stays, with what is still in it: notes.txt" <<<"$d_out" \
   && [ "$d2_gone" = yes ] && grep -qF "Removed the history, settings and logs, and their folder: $logs" <<<"$d2_out" \
   && [ "$d3_after" = "$d3_before" ] && grep -qF "The server is still running" <<<"$d3_out"; then
  ok "uninstall --yes --data removes Sidenote's files by name and the folder when empty; a user's file stays, a running server keeps all"
else bad "uninstall --yes --data removes Sidenote's files by name and the folder when empty; a user's file stays, a running server keeps all" \
         "rc $d_rc, left: $d_left | empty run: $(tail -1 <<<"$d2_out") | running: $(tail -1 <<<"$d3_out")"; fi

# 53. Where WSL cannot start Windows programs, uninstall --yes prints the command that removes the shortcut and its icon
#     from Windows (launch.pyw --remove), on a line of its own, and asks nothing of Windows. launch.pyw --remove --dry-run
#     says what it would remove (the shortcut under each name it has had, the icon, the folder if empty) and removes nothing.
state; EXTRA_ENV="$offwin" run uninstall --yes; off_un="$(cat "$work/out")"; off_un_calls="$(calls_of cmd | wc -l | tr -d ' ')$(calls_of ps | wc -l | tr -d ' ')"
off_remove="py -3 \"$(wslpath -w "$work/repo/client/launch.pyw" 2>/dev/null)\" --remove"
mkdir -p "$work/local/Sidenote" && : > "$work/local/Sidenote/sidenote.ico"
state; EXTRA_ENV="LOCALAPPDATA=$work/local SIDENOTE_LANG=en" run_launch --remove; rm_dry="$(cat "$work/out")"; rm_dry_rc="$(cat "$work/rc")"
if grep -qxF "      $off_remove" <<<"$off_un" && grep -qF "In a Windows terminal this removes them:" <<<"$off_un" && [ "$off_un_calls" = 00 ]; then
  ok "interop off, uninstall prints the command that removes the shortcut from Windows, and asks nothing of Windows"
else bad "interop off, uninstall prints the command that removes the shortcut from Windows, and asks nothing of Windows" \
         "Windows calls $off_un_calls, want '$off_remove': $(grep -F "launch.pyw" <<<"$off_un" | head -2 | tr '\n' '|')"; fi
if [ "$rm_dry_rc" = 0 ] && grep -qxF "[dry-run] remove shortcut: Sidenote Capture.lnk" <<<"$rm_dry" \
   && grep -qxF "[dry-run] remove icon: $work/local/Sidenote/sidenote.ico" <<<"$rm_dry" \
   && grep -qF "pip uninstall -y -r" <<<"$rm_dry" && [ -f "$work/local/Sidenote/sidenote.ico" ] && [ -z "$(calls_of ps)" ]; then
  ok "launch.pyw --remove --dry-run says what it would remove and the pip line, and removes nothing"
else bad "launch.pyw --remove --dry-run says what it would remove and the pip line, and removes nothing" "rc $rm_dry_rc: $(tr '\n' '|' <<<"$rm_dry")"; fi

# 54. backup: with nothing to back up it ends 1; with the server off it takes the files, the history one file with its -wal
#     merged in, with the server running the server's own SQLite copy; the members by plain name, the archive this
#     user's alone, a file already there never written over, and with no name one in the folder it was typed in.
rm -rf "$logs" && mkdir -p "$logs"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/none.tar.gz"; b_none_rc="$(cat "$work/rc")"; b_none="$(cat "$work/out")"
# the history as SQLite leaves one a server was writing: its latest answer still in the -wal beside it
python3 -c 'import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("pragma journal_mode=wal"); c.execute("pragma wal_autocheckpoint=0")
c.execute("create table answers (id integer, text text)"); c.execute("insert into answers values (1, ?)", (sys.argv[2],)); c.commit()
os._exit(0)' "$logs/history.sqlite" "the answer kept"
rm -f "$logs/history.sqlite-shm"
printf '{"lang": "en"}\n' > "$logs/.settings.json"
printf '{"screen": true}\n' > "$logs/.switches.json"
printf 'a log line\n' > "$logs/server.log"
state; (cd "$here" && EXTRA_ENV="SIDENOTE_LANG=en" run backup); b_off_rc="$(cat "$work/rc")"; b_off="$(cat "$work/out")"
b_off_file="$(ls "$here"/sidenote-backup-*.tar.gz 2>/dev/null | head -1)"
b_off_members="$(tar -tzf "$b_off_file" 2>/dev/null | LC_ALL=C sort | tr '\n' ' ')"
b_off_mode="$(stat -c %a "$b_off_file" 2>/dev/null)"
b_off_txt="$(tar -xzOf "$b_off_file" sidenote-backup.txt 2>/dev/null)"
rm -rf "$work/off" && mkdir -p "$work/off" && tar -xzf "$b_off_file" -C "$work/off" 2>/dev/null
b_off_wal="$(answer_in "$work/off/history.sqlite")"
last_call_with docker "python"; b_off_exec=${#CALL[@]}
if [ "$b_none_rc" = 1 ] && grep -qF "Nothing to back up yet" <<<"$b_none" && [ ! -e "$here/none.tar.gz" ]; then
  ok "backup with no history and no settings says so, ends 1 and makes no file"
else bad "backup with no history and no settings says so, ends 1 and makes no file" "rc $b_none_rc: $(tail -1 <<<"$b_none")"; fi
if [ "$b_off_rc" = 0 ] && [ "$b_off_members" = ".settings.json .switches.json history.sqlite sidenote-backup.txt " ] \
   && [ "$b_off_mode" = 600 ] && [[ $b_off_txt =~ ^sidenote\ [^\ ]+\ [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
   && [ "$b_off_wal" = "the answer kept" ] && [ -f "$logs/history.sqlite-wal" ] && [ "$b_off_exec" = 0 ] && [ -z "$(ls -A "$logs" | grep -F .backup)" ] \
   && grep -qF "Backed up: $b_off_file" <<<"$b_off"; then
  ok "...server off: the history one file with its -wal merged in (the log folder's left as it is), plain names, mode 600, named for the time in the folder typed in"
else bad "...server off: the history one file with its -wal merged in (the log folder's left as it is), plain names, mode 600, named for the time in the folder typed in" \
         "rc $b_off_rc, file ${b_off_file:-none} mode $b_off_mode, members: $b_off_members, txt: $b_off_txt, exec calls $b_off_exec, $(tail -2 <<<"$b_off" | tr '\n' '|')"; fi
# a server that runs has its history open, with its own -wal: the server's copy (the stand-in copies the file) is one file
rm -f "$logs/history.sqlite" "$logs/history.sqlite-wal" && mkdb "$logs/history.sqlite" "the answer kept"
state server-running; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/running.tar.gz"; b_run_rc="$(cat "$work/rc")"; b_run="$(cat "$work/out")"
last_call_with docker "python"; b_run_exec="${CALL[*]:0:4}"
mkdir -p "$work/unpacked" && rm -f "$work/unpacked/"* && tar -xzf "$here/running.tar.gz" -C "$work/unpacked" 2>/dev/null
b_run_members="$(tar -tzf "$here/running.tar.gz" 2>/dev/null | LC_ALL=C sort | tr '\n' ' ')"
if [ "$b_run_rc" = 0 ] && [ "$b_run_exec" = "exec sidenote python -c" ] && [ "$(answer_in "$work/unpacked/history.sqlite")" = "the answer kept" ] \
   && [ "$b_run_members" = ".settings.json .switches.json history.sqlite sidenote-backup.txt " ] && [ ! -e "$logs/.backup.sqlite" ] \
   && [ -z "$(ls -A "$logs" | grep -F .backup)" ]; then
  ok "...server running: the history is the server's own SQLite copy, and nothing of the copy is left in the log folder"
else bad "...server running: the history is the server's own SQLite copy, and nothing of the copy is left in the log folder" \
         "rc $b_run_rc, exec: $b_run_exec, answer: $(answer_in "$work/unpacked/history.sqlite"), members: $b_run_members, $(tail -1 <<<"$b_run")"; fi
printf 'keep me\n' > "$here/taken.tar.gz"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/taken.tar.gz"; b_taken_rc="$(cat "$work/rc")"
if [ "$b_taken_rc" = 1 ] && [ "$(cat "$here/taken.tar.gz")" = "keep me" ] && said "is there already"; then
  ok "...and a file already there is not written over"
else bad "...and a file already there is not written over" "rc $b_taken_rc: $(tail -1 "$work/out")"; fi
# ...a history with an answer in Recently deleted: it is left out of the backup's copy, which says so, and the history in
# the log folder keeps it
python3 -c 'import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("create table answers (id integer, text text, deleted real)")
c.execute("insert into answers values (1, ?, null)", ("the answer kept",)); c.execute("insert into answers values (2, ?, 1.0)", ("a deleted one",))
c.commit(); c.close()' "$logs/history.sqlite.new" && mv "$logs/history.sqlite.new" "$logs/history.sqlite"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/left.tar.gz"; b_left_rc="$(cat "$work/rc")"; b_left="$(cat "$work/out")"
rm -rf "$work/left" && mkdir -p "$work/left" && tar -xzf "$here/left.tar.gz" -C "$work/left" 2>/dev/null
rows_of() { python3 -c 'import sqlite3, sys; print("|".join(r[0] for r in sqlite3.connect(sys.argv[1]).execute("select text from answers order by id")))' "$1" 2>&1; }
if [ "$b_left_rc" = 0 ] && [ "$(rows_of "$work/left/history.sqlite")" = "the answer kept" ] && grep -qF "Recently deleted is left out of it: 1" <<<"$b_left" \
   && [ "$(rows_of "$logs/history.sqlite")" = "the answer kept|a deleted one" ] && ! tar -tzf "$here/left.tar.gz" | grep -qx history.sqlite-wal; then
  ok "...an answer in Recently deleted is left out of the backup's copy, which says so, and stays in the history itself"
else bad "...an answer in Recently deleted is left out of the backup's copy, which says so, and stays in the history itself" \
         "rc $b_left_rc, copy: $(rows_of "$work/left/history.sqlite"), log folder: $(rows_of "$logs/history.sqlite"), $(tail -2 <<<"$b_left" | tr '\n' '|')"; fi
# ...a link among the files (one the server's container could leave there) is refused, and no archive made
printf 'not for the backup\n' > "$work/someone-elses"
mv "$logs/.settings.json" "$logs/.settings.json.real" && ln -s "$work/someone-elses" "$logs/.settings.json"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/linked.tar.gz"; b_link_rc="$(cat "$work/rc")"
rm -f "$logs/.settings.json" && mv "$logs/.settings.json.real" "$logs/.settings.json"
if [ "$b_link_rc" = 1 ] && said "is a link, not a file of Sidenote's" && [ ! -e "$here/linked.tar.gz" ]; then
  ok "...and a link among its files is refused, with no archive made"
else bad "...and a link among its files is refused, with no archive made" "rc $b_link_rc: $(tail -1 "$work/out")"; fi

# 55. restore: what is no backup is refused with nothing changed (not gzip, ../x, /etc/x, a link, a name a backup does
#     not have, no sidenote-backup.txt); with no terminal it asks for --yes, and n keeps everything; y and --yes put the
#     backup in place: what was there in one before-restore folder, no -wal or -shm of the old history beside the new
#     one, .restart.npz gone, the files this user's alone; a running server stopped and started again, one that is off
#     left off; and a failure halfway puts everything back as it was.
good="$here/running.tar.gz"
python3 - "$work/bad" "$work" <<'BAD'
import io, os, sys, tarfile
out, work = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
def make(name, members):
    with tarfile.open(os.path.join(out, name), "w:gz") as tar:
        for member, kind in members:
            info = tarfile.TarInfo(member)
            if kind == "link":
                info.type, info.linkname = tarfile.SYMTYPE, os.path.join(work, "elsewhere")
                tar.addfile(info)
            else:
                data = b"sidenote 0.6.0 2026-11-10T00:00:00Z\n"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
make("dotdot.tar.gz", [("sidenote-backup.txt", "file"), ("../x", "file")])
make("absolute.tar.gz", [("sidenote-backup.txt", "file"), ("/etc/x", "file")])
make("link.tar.gz", [("sidenote-backup.txt", "file"), ("history.sqlite", "link")])
make("other.tar.gz", [("sidenote-backup.txt", "file"), (".settings.json", "file"), ("notes.txt", "file")])
make("no-txt.tar.gz", [("history.sqlite", "file")])
open(os.path.join(out, "not-gzip.tar.gz"), "w").write("not an archive\n")
BAD
# the log folder as a restore finds it: a history of its own with both SQLite files beside it, settings, switches, the
# problems the server remembered, a log, and the folder an earlier restore left
now_logs() {
  rm -rf "$logs" && mkdir -p "$logs/before-restore-20260101-000000"
  mkdb "$logs/history.sqlite" "the answer there now"
  printf 'old wal\n' > "$logs/history.sqlite-wal"; printf 'old shm\n' > "$logs/history.sqlite-shm"
  printf '{"now": 1}\n' > "$logs/.settings.json"; printf '{"screen": false}\n' > "$logs/.switches.json"
  printf 'remembered\n' > "$logs/.restart.npz"; printf 'a log line\n' > "$logs/server.log"
  printf 'older\n' > "$logs/before-restore-20260101-000000/history.sqlite"
}
now_logs; r_sum="$(logsum)"; refused=""
for f in not-gzip dotdot absolute link other no-txt; do
  state; EXTRA_ENV="SIDENOTE_LANG=en" run restore --yes "$work/bad/$f.tar.gz"
  if [ "$(cat "$work/rc")" = 0 ] || ! said "Not a Sidenote backup" || [ "$(logsum)" != "$r_sum" ]; then refused="$refused $f:$(tail -1 "$work/out")"; fi
done
if [ -z "$refused" ] && [ ! -e "$work/x" ] && [ ! -e "$work/elsewhere" ]; then
  ok "restore refuses what is no backup (not gzip, ../x, /etc/x, a link, another name, no sidenote-backup.txt), with nothing changed"
else bad "restore refuses what is no backup (not gzip, ../x, /etc/x, a link, another name, no sidenote-backup.txt), with nothing changed" "accepted or changed:$refused"; fi
state; EXTRA_ENV="SIDENOTE_LANG=en" run restore "$good"; r_notty_rc="$(cat "$work/rc")"; r_notty="$(cat "$work/out")"; r_notty_sum="$(logsum)"
state; EXTRA_ENV="SIDENOTE_LANG=en" run_tty $'n\n' "Restore it?" restore "$good"; r_no_rc="$(cat "$work/rc")"; r_no="$(cat "$work/out")"
if [ "$r_notty_rc" = 1 ] && grep -qF "./sidenote restore $good --yes" <<<"$r_notty" && [ "$r_notty_sum" = "$r_sum" ] \
   && [ "$r_no_rc" = 1 ] && grep -qF "Nothing changed." <<<"$r_no" && [ "$(logsum)" = "$r_sum" ]; then
  ok "...with no terminal it names the line with --yes, and n at the question keeps everything"
else bad "...with no terminal it names the line with --yes, and n at the question keeps everything" "no terminal rc $r_notty_rc: $(tail -1 <<<"$r_notty") | n rc $r_no_rc: $(tail -1 <<<"$r_no")"; fi
state; EXTRA_ENV="SIDENOTE_LANG=en" run_tty $'y\n' "Restore it?" restore "$good"; r_yes_rc="$(cat "$work/rc")"; r_yes="$(cat "$work/out")"
r_folders="$(cd "$logs" && ls -d before-restore-* 2>/dev/null | tr '\n' ' ')"
r_new="$(cd "$logs" && ls -d before-restore-* 2>/dev/null | tail -1)"   # this restore's: the last by name
r_kept="$(cd "$logs/$r_new" 2>/dev/null && ls -A | LC_ALL=C sort | tr '\n' ' ')"
r_old_answer="$(answer_in "$logs/$r_new/history.sqlite")"
last_call_with docker stop; r_yes_stop=${#CALL[@]}
if [ "$r_yes_rc" = 0 ] && [ "$(answer_in "$logs/history.sqlite")" = "the answer kept" ] && [ "$(cat "$logs/.settings.json")" = '{"lang": "en"}' ] \
   && [ ! -e "$logs/history.sqlite-wal" ] && [ ! -e "$logs/history.sqlite-shm" ] && [ ! -e "$logs/.restart.npz" ] \
   && [ -f "$logs/server.log" ] && [ "$(stat -c %a "$logs/history.sqlite")" = 600 ] && [ "$(stat -c %a "$logs/.settings.json")" = 600 ] \
   && [[ $r_folders =~ ^before-restore-20260101-000000\ before-restore-[0-9]{8}-[0-9]{6}\ $ ]] \
   && [ "$(cat "$logs/before-restore-20260101-000000/history.sqlite")" = older ] \
   && [ "$r_kept" = ".settings.json .switches.json history.sqlite history.sqlite-shm history.sqlite-wal " ] \
   && [ "$r_old_answer" = "the answer there now" ] && [ "$r_yes_stop" = 0 ] && grep -qF "The server is off" <<<"$r_yes" \
   && [ -z "$(ls -A "$logs" | grep -F .restore)" ]; then
  ok "...y restores: what was there in a before-restore folder, the earlier one kept, no old -wal or -shm beside the new history, .restart.npz gone, 600"
else bad "...y restores: what was there in a before-restore folder, the earlier one kept, no old -wal or -shm beside the new history, .restart.npz gone, 600" \
         "rc $r_yes_rc, folders: $r_folders, kept: $r_kept, now: $(ls -A "$logs" | tr '\n' ' '), stop calls $r_yes_stop, $(tail -3 <<<"$r_yes" | tr '\n' '|')"; fi
now_logs
state server-running; EXTRA_ENV="SIDENOTE_LANG=en" run restore "$good" --yes; r_run_rc="$(cat "$work/rc")"; r_run="$(cat "$work/out")"
r_order="$(for f in $(calls_of docker); do tr '\0' ' ' < "$f"; echo; done | grep -E '^compose (stop|start) server' | tr '\n' '|')"
r_run_folders="$(cd "$logs" && ls -d before-restore-* 2>/dev/null | wc -l | tr -d ' ')"
if [ "$r_run_rc" = 0 ] && [ "$r_order" = "compose stop server |compose start server |" ] && [ "$r_run_folders" = 2 ] \
   && [ "$(answer_in "$logs/history.sqlite")" = "the answer kept" ] && grep -qF "The server was started again." <<<"$r_run"; then
  ok "...--yes with the server running stops it for the swap and starts it again, and one before-restore folder is kept"
else bad "...--yes with the server running stops it for the swap and starts it again, and one before-restore folder is kept" \
         "rc $r_run_rc, compose: $r_order, folders $r_run_folders, $(tail -2 <<<"$r_run" | tr '\n' '|')"; fi
now_logs; r_fail_sum="$(logsum)"
state server-running; EXTRA_ENV="SIDENOTE_LANG=en PATH=$work/mvbin:$work/bin:/usr/bin:/bin" run restore "$good" --yes
r_fail_rc="$(cat "$work/rc")"; r_fail="$(cat "$work/out")"
r_fail_order="$(for f in $(calls_of docker); do tr '\0' ' ' < "$f"; echo; done | grep -E '^compose (stop|start) server' | tr '\n' '|')"
if [ "$r_fail_rc" = 1 ] && grep -qF "nothing changed" <<<"$r_fail" && [ "$(logsum)" = "$r_fail_sum" ] \
   && [ "$r_fail_order" = "compose stop server |compose start server |" ]; then
  ok "...a failure halfway puts back what was there, says nothing changed, and starts the server again"
else bad "...a failure halfway puts back what was there, says nothing changed, and starts the server again" \
         "rc $r_fail_rc, compose: $r_fail_order, same files: $([ "$(logsum)" = "$r_fail_sum" ] && echo yes || echo no) | $(tail -2 <<<"$r_fail" | tr '\n' '|')"; fi

# 56. llm rm removes a model with its tuned copy after a yes, showing their sizes; a model that is not there is said and
#     ends 1 with nothing removed; no terminal asks for --yes; the model set for solving gets a line naming llm pull,
#     another does not; with the llm container off the tools container removes them; another model server is left alone.
rm_calls() { for f in $(calls_of docker); do tr '\0' ' ' < "$f"; echo; done | grep -E 'ollama rm|llm-pull' | grep -v '; ollama list *$' | tr '\n' '|'; }
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_LOCAL_MODEL=gemma4:e4b" run llm rm gemma4:e4b --yes; m_rc="$(cat "$work/rc")"; m_out="$(cat "$work/out")"; m_calls="$(rm_calls)"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_LOCAL_MODEL=gemma4:e4b" run llm rm qwen3:8b --yes; m_other="$(cat "$work/out")"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run llm rm nosuch:1b --yes; m_none_rc="$(cat "$work/rc")"; m_none="$(cat "$work/out")"; m_none_calls="$(rm_calls)"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run llm rm gemma4:e4b; m_notty_rc="$(cat "$work/rc")"; m_notty="$(cat "$work/out")"; m_notty_calls="$(rm_calls)"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run_tty $'n\n' "Remove them?" llm rm gemma4:e4b; m_n_calls="$(rm_calls)"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run_tty $'y\n' "Remove them?" llm rm gemma4:e4b; m_y_calls="$(rm_calls)"
state llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run llm rm gemma4:e2b --yes; m_tools_rc="$(cat "$work/rc")"; m_tools_calls="$(rm_calls)"
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_LOCAL_URL=http://model-server.internal:8000/v1" run llm rm gemma4:e4b --yes
m_url_rc="$(cat "$work/rc")"; m_url_calls="$(rm_calls)"
pair="exec sidenote-llm ollama rm gemma4:e4b |exec sidenote-llm ollama rm sidenote-gemma4:e4b |"
if [ "$m_rc" = 0 ] && [ "$m_calls" = "$pair" ] && grep -qF "9.6 GB" <<<"$m_out" \
   && grep -qF "gemma4:e4b is the model set for solving here: ./sidenote llm pull downloads it again." <<<"$m_out" \
   && ! grep -qF "set for solving" <<<"$m_other"; then
  ok "llm rm removes a model with its tuned copy, shows their sizes, and names llm pull for the model set for solving"
else bad "llm rm removes a model with its tuned copy, shows their sizes, and names llm pull for the model set for solving" \
         "rc $m_rc, calls: $m_calls | $(tr '\n' '|' <<<"$m_out")"; fi
if [ "$m_none_rc" = 1 ] && grep -qF "Not on this PC: nosuch:1b" <<<"$m_none" && [ -z "$m_none_calls" ] \
   && [ "$m_notty_rc" = 1 ] && grep -qF "./sidenote llm rm gemma4:e4b --yes" <<<"$m_notty" && [ -z "$m_notty_calls" ] \
   && [ -z "$m_n_calls" ] && [ "$m_y_calls" = "$pair" ]; then
  ok "...a model not there is said and ends 1; with no terminal it names --yes; n removes nothing, y removes"
else bad "...a model not there is said and ends 1; with no terminal it names --yes; n removes nothing, y removes" \
         "none rc $m_none_rc calls '$m_none_calls' | no terminal rc $m_notty_rc calls '$m_notty_calls' | n '$m_n_calls' | y '$m_y_calls'"; fi
if [ "$m_tools_rc" = 0 ] && [[ $m_tools_calls == *"llm-pull -c "*"ollama rm \"\$m\""*" sh gemma4:e2b |" ]] \
   && [ "$m_url_rc" = 1 ] && [ -z "$m_url_calls" ]; then
  ok "...with the llm container off the tools container removes it, and another model server's models are left alone"
else bad "...with the llm container off the tools container removes it, and another model server's models are left alone" \
         "tools rc $m_tools_rc: $m_tools_calls | other server rc $m_url_rc: $m_url_calls"; fi

# 57. help names backup, restore, llm rm and uninstall --data, in both languages
missing=""
for lang in en ko; do
  EXTRA_ENV="SIDENOTE_LANG=$lang" run help
  for w in "./sidenote backup [" "./sidenote restore " "./sidenote llm rm " "--data"; do said "$w" || missing="$missing $lang:$w"; done
done
if [ -z "$missing" ]; then ok "help names backup, restore, llm rm and uninstall --data"
else bad "help names backup, restore, llm rm and uninstall --data" "missing:$missing"; fi

# --- the GPU, Docker Compose, a port taken, why a server stopped, the capture's guard ---------------------------------
# 58. The GPU picks compose.amd.yaml only for an AMD GPU a model can run on (one that fits, or a model named) and only
#     with its ROCm device there, and then hands the device's group to compose by number: an integrated Radeon with
#     512 MB, or no /dev/kfd, picked the ROCm image, whose container cannot start. compose.amd.yaml takes the number.
top > "$work/repo/top.sh"
vendor_of() {   # $1 = the GPU as state/gpu holds it ("" for none), $2 = the device node's path, $3 = SIDENOTE_LOCAL_MODEL
  rm -f "$work/state/gpu"; if [ -n "$1" ]; then printf '%s' "$1" > "$work/state/gpu"; fi
  (cd "$work/repo" && env -u COMPOSE_FILE -u SIDENOTE_RENDER_GID FAKE="$work" SIDENOTE_KFD="$2" SIDENOTE_LOCAL_MODEL="$3" \
     bash -c 'source ./top.sh >/dev/null 2>&1; printf "%s %s" "${COMPOSE_FILE#compose.yaml:docker/compose.}" "${SIDENOTE_RENDER_GID:-none}"')
}
: > "$work/kfd"; kfd_gid="$(stat -c %g "$work/kfd")"
picks="$(vendor_of "amd,Radeon 780M,0.5" "$work/kfd" "") | $(vendor_of "amd,Radeon 780M,0.5" "$work/kfd" gemma4:e2b) | $(vendor_of "amd,Radeon RX 7900 XTX,24" "$work/no-kfd" "") | $(vendor_of "amd,Radeon RX 7900 XTX,24" "$work/kfd" "") | $(vendor_of "nvidia,GeForce RTX 4090,24" "$work/no-kfd" "") | $(vendor_of "nvidia,GeForce GT 710,1" "$work/no-kfd" "")"
rm -f "$work/state/gpu"
want="cpu.yaml none | amd.yaml $kfd_gid | cpu.yaml none | amd.yaml $kfd_gid | nvidia.yaml none | cpu.yaml none"
if [ "$picks" = "$want" ] && grep -qF -- '- ${SIDENOTE_RENDER_GID:-0}' "$tree/docker/compose.amd.yaml" && ! grep -qxF '      - render' "$tree/docker/compose.amd.yaml"; then
  ok "AMD only for a GPU a model runs on and with /dev/kfd there, with the device's group by number for compose.amd.yaml"
else bad "AMD only for a GPU a model runs on and with /dev/kfd there, with the device's group by number for compose.amd.yaml" "got:  $picks | want: $want"; fi

# 59. bash 3.2 (a Mac's /bin/bash) ended the whole launcher with curl's status 7 and no word when the server did not
#     answer: open, capture-restart and capture said nothing. Each says why, and ends 1. (Run under 3.2 by
#     SIDENOTE_TEST_BASH; under bash 5 it never failed.)
quiet_end=""
for c in open capture-restart capture; do
  state server-down; EXTRA_ENV="SIDENOTE_LANG=en" run $c
  if [ "$(cat "$work/rc")" != 1 ] || ! grep -qF "The server is off" "$work/out"; then quiet_end="$quiet_end $c:rc $(cat "$work/rc") '$(tail -1 "$work/out")'"; fi
done
if [ -z "$quiet_end" ]; then ok "with the server off, open, capture-restart and capture say so and end 1 (bash 3.2 ended them with curl's 7)"
else bad "with the server off, open, capture-restart and capture say so and end 1 (bash 3.2 ended them with curl's 7)" "$quiet_end"; fi

# 60. Where WSL cannot start Windows programs the command that sets the capture up from Windows is on a line of its own,
#     nothing after it (copied out of a sentence it took the next words along, which launch.pyw refused as arguments);
#     on WSL 1 that is said as WSL 1, not as interop turned off.
state; EXTRA_ENV="$nowin SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run setup-capture; own_line="$(cat "$work/out")"
setup_re="^      py -3 \"[^\"]*launch\.pyw\" --setup --distro [^ ]+ --repo \"[^\"]*\" --port 8777$"
state; EXTRA_ENV="PATH=$work/nowin:/usr/bin:/bin SIDENOTE_BINFMT=$work/wsl1 SIDENOTE_KERNEL=4.4.0-19041-Microsoft SIDENOTE_MOUNTS=$work/mounts-pe SIDENOTE_LANG=en" run setup-capture
wsl1_said="$(cat "$work/out")"
if grep -qE "$setup_re" <<<"$own_line" && grep -qF "WSL 1 cannot start Windows programs here: cmd.exe does not run (exit code 126)." <<<"$wsl1_said" \
   && grep -qE "$setup_re" <<<"$wsl1_said" && ! grep -qF "interop is off" <<<"$wsl1_said"; then
  ok "interop off and WSL 1: the setup command on a line of its own, and WSL 1 said as WSL 1"
else bad "interop off and WSL 1: the setup command on a line of its own, and WSL 1 said as WSL 1" \
         "off: $(grep -F "launch.pyw" <<<"$own_line" | head -1) | WSL 1: $(head -2 <<<"$wsl1_said" | tr '\n' '|')"; fi

# 61. Docker without the Compose plugin, or with one older than 2.24, is said with what to install before up starts
#     anything (every command ended on Docker's "See 'docker --help'"); doctor names the version, or the reason.
state no-compose; EXTRA_ENV="SIDENOTE_LANG=en" run up; nc_rc="$(cat "$work/rc")"; nc="$(cat "$work/out")"; last_call docker up; nc_up=${#CALL[@]}
state; echo 2.20.2 > "$work/state/compose-version"; EXTRA_ENV="SIDENOTE_LANG=en" run up; old_rc="$(cat "$work/rc")"; old_c="$(cat "$work/out")"
state; echo 2.24.0-desktop.1 > "$work/state/compose-version"; EXTRA_ENV="SIDENOTE_LANG=en" run doctor; new_c="$(cat "$work/out")"
state no-compose; EXTRA_ENV="SIDENOTE_LANG=en" run doctor; nc_doctor="$(cat "$work/out")"
if [ "$nc_rc" = 1 ] && grep -qF "Docker has no Compose here (docker compose)" <<<"$nc" && [ "$nc_up" = 0 ] \
   && [ "$old_rc" = 1 ] && grep -qF "Docker Compose is older than 2.24 (it is 2.20.2)" <<<"$old_c" \
   && grep -qF "docker compose 2.24.0-desktop.1" <<<"$new_c" && grep -qF "Docker has no Compose here" <<<"$nc_doctor"; then
  ok "no Compose plugin, or one older than 2.24, is said before up starts anything; doctor names the version"
else bad "no Compose plugin, or one older than 2.24, is said before up starts anything; doctor names the version" \
         "none rc $nc_rc up calls $nc_up: $(tail -1 <<<"$nc") | 2.20 rc $old_rc: $(tail -1 <<<"$old_c") | doctor: $(grep -F "compose" <<<"$new_c" | head -1)"; fi

# 62. doctor reads the log's days as the server does (server/config.py): +30, 1e2 and .5 as numbers, nan as the default,
#     at least a day, and one day as "1 day".
days_said=""
for d in "+30|kept 30 days" "1e2|kept 100 days" ".5|kept 1 day)" "nan|kept 14 days" "7|kept 7 days"; do
  state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_LOG_DAYS=${d%%|*}" run doctor
  said "${d#*|}" || days_said="$days_said ${d%%|*}:'$(grep -F "Log folder" "$work/out")'"
done
if [ -z "$days_said" ]; then ok "doctor reads the log's days as the server does (+30, 1e2, .5, nan), and says 1 day"
else bad "doctor reads the log's days as the server does (+30, 1e2, .5, nan), and says 1 day" "$days_said"; fi

# 63. A port another program holds: up says so, and that a capture program started before a port change keeps asking
#     the old port (and on WSL the shortcut holds it too).
state port-taken; EXTRA_ENV="SIDENOTE_LANG=en" run up; pt_rc="$(cat "$work/rc")"; pt="$(cat "$work/out")"
state port-taken; EXTRA_ENV="WSL_DISTRO_NAME= SIDENOTE_LANG=en PATH=$work/venvbin:$work/bin:/usr/bin:/bin" run up; pt_lx="$(cat "$work/out")"
if [ "$pt_rc" = 1 ] && grep -qF "Another program is using port 8777" <<<"$pt" \
   && grep -qF "keeps asking the old one: ./sidenote capture-stop, then ./sidenote capture." <<<"$pt" \
   && grep -qF "./sidenote shortcut makes it again" <<<"$pt" && grep -qF "keeps asking the old one" <<<"$pt_lx" \
   && ! grep -qF "shortcut" <<<"$pt_lx"; then
  ok "a port taken: up says what a port change leaves behind (the capture program, and on WSL the shortcut)"
else bad "a port taken: up says what a port change leaves behind (the capture program, and on WSL the shortcut)" \
         "rc $pt_rc: $(tail -2 <<<"$pt" | tr '\n' '|') | Linux: $(tail -2 <<<"$pt_lx" | tr '\n' '|')"; fi

# 64. status says why a server is off when that can be known: its container's exit code, Docker ending it for memory, or
#     its own loop giving up (with the stacks of one that stopped answering); a server its loop started again in the
#     last ten minutes is said once; a local model whose container is off says so, and that up starts it.
state server-down container-ended; echo "exited 1 false" > "$work/state/container-ended"; EXTRA_ENV="SIDENOTE_LANG=en" run status; st_code="$(cat "$work/out")"
state server-down container-ended; echo "exited 137 true" > "$work/state/container-ended"; EXTRA_ENV="SIDENOTE_LANG=en" run status; st_oom="$(cat "$work/out")"
printf '%s 1 5 stopped stall\n' "$(date +%s)" > "$logs/.ended"
state server-down; EXTRA_ENV="SIDENOTE_LANG=en" run status; st_gave="$(cat "$work/out")"
printf '%s 1 2 restarted -\n' "$(date +%s)" > "$logs/.ended"
state; EXTRA_ENV="SIDENOTE_LANG=en" run status; st_again="$(cat "$work/out")"
rm -f "$logs/.ended"
state container-ended; echo "exited 1 false" > "$work/state/container-ended"
health_with '{"present": true, "on": true, "ok": false, "model": "sidenote-gemma4:26b", "loaded": null}'
EXTRA_ENV="SIDENOTE_LANG=en" run status; st_llm="$(cat "$work/out")"
if grep -qF "Server: off: its container ended (exit code 1)" <<<"$st_code" \
   && grep -qF "Server: off: it went over its memory limit and Docker ended it" <<<"$st_oom" \
   && grep -qF "it ended 5 times within 10 minutes and was not started again (last exit code 1), it had stopped answering: the stacks are in $logs/stall.txt" <<<"$st_gave" \
   && grep -qF "Server: it ended by itself (exit code 1) and was started again just now" <<<"$st_again"; then
  ok "status says why the server is off: its exit code, memory, or its own loop giving up; and a restart within 10 minutes"
else bad "status says why the server is off: its exit code, memory, or its own loop giving up; and a restart within 10 minutes" \
         "code: $(grep -F "Server" <<<"$st_code") | oom: $(grep -F "Server" <<<"$st_oom") | gave up: $(grep -F "Server" <<<"$st_gave") | again: $(grep -F "Server" <<<"$st_again")"; fi
if grep -qF "Local model: its container is off: its container ended (exit code 1)" <<<"$st_llm" && grep -qF "./sidenote up starts it" <<<"$st_llm"; then
  ok "...and of a local model whose container is off, that up starts it"
else bad "...and of a local model whose container is off, that up starts it" "$(grep -F "Local model" <<<"$st_llm")"; fi

# 65. capture-stop's words for a capture program it could not end name the tray icon's Quit first and Task Manager for
#     one without an icon; within down, with the server off and Windows out of reach, it is one dim line, no "!".
state running unkillable; EXTRA_ENV="SIDENOTE_LANG=en" run capture-stop; cs_left="$(cat "$work/out")"
state server-down; EXTRA_ENV="$offwin" run down; cs_down="$(cat "$work/out")"
if grep -qF "1 capture program still running. Right-click its tray icon > Quit. With no icon, end python.exe or pythonw.exe in Task Manager." <<<"$cs_left" \
   && grep -qF "(with the server off and Windows out of reach, a capture program that is left cannot be seen from here: its tray icon > Quit ends it)" <<<"$cs_down" \
   && ! grep -qF "!" <<<"$(grep -F "Windows out of reach" <<<"$cs_down")"; then
  ok "capture-stop names the tray icon's Quit, then Task Manager; within down, Windows out of reach is one quiet line"
else bad "capture-stop names the tray icon's Quit, then Task Manager; within down, Windows out of reach is one quiet line" \
         "left: $(tail -1 <<<"$cs_left") | down: $(grep -F "Windows" <<<"$cs_down" | head -1)"; fi

# 66. capture --console with another capture program running for the server: the program ends with 76 (its guard), and
#     the launcher ends 1 without stopping the one that runs and without saying the capture ended.
state capture-busy; EXTRA_ENV="SIDENOTE_LANG=en" run capture --console; cb_rc="$(cat "$work/rc")"; cb="$(cat "$work/out")"; last_call_with curl "/capture/quit"
cb_quit=${#CALL[@]}
if [ "$cb_rc" = 1 ] && grep -qF "Another capture program is already running for this server" <<<"$cb" && ! grep -qF "Capture ended." <<<"$cb" \
   && [ "$cb_quit" = 0 ]; then
  ok "capture --console refused by a running capture program ends 1, stops nothing and does not say the capture ended"
else bad "capture --console refused by a running capture program ends 1, stops nothing and does not say the capture ended" "rc $cb_rc, quit asked $cb_quit: $(tail -2 <<<"$cb" | tr '\n' '|')"; fi

# 67. Interop off, from the shortcut: the launcher hands launch.pyw the language set for Sidenote and its own setup
#     command (with the wheels folder of a PC without internet), and launch.pyw starts the program with that language;
#     with a capture program already holding its guard for the server (reconnecting, so the server does not count it),
#     launch.pyw opens the panel and starts no second one.
state; EXTRA_ENV="$offwin SIDENOTE_WHEELS=/mnt/c/bundle/wheels" run capture --up --from-windows; marks="$(grep -aE $'^SIDENOTE-(LANG|SETUP|START)\t' "$work/out" | cut -f1 | tr '\n' ' ')"
setup_line="$(grep -a $'^SIDENOTE-SETUP\t' "$work/out" | cut -f2)"
state; EXTRA_ENV="$offwin PYTHONPATH=$work/pymods" run_launch; lang_chain="$(cat "$work/out")"
state; EXTRA_ENV="$offwin SIDENOTE_WHEELS=/mnt/c/bundle/wheels PYTHONPATH=$work/nopymods" run_launch; wheels_box="$(box_text)"
if [ "$marks" = "SIDENOTE-LANG SIDENOTE-SETUP SIDENOTE-START " ] && [[ $setup_line == *' --setup --distro '*' --port 8777 --wheels "'* ]] \
   && grep -qxF "[dry-run] env: SIDENOTE_LANG=en" <<<"$lang_chain" && grep -q '^\[dry-run\] start: ' <<<"$lang_chain" \
   && grep -qF -- "--wheels \"" <<<"$wheels_box"; then
  ok "interop off: the language and the launcher's own setup command (with --wheels) reach launch.pyw, and the program gets the language"
else bad "interop off: the language and the launcher's own setup command (with --wheels) reach launch.pyw, and the program gets the language" \
         "marks: $marks | setup: $setup_line | $(grep -a '\[dry-run\] env\|\[dry-run\] start' <<<"$lang_chain" | tr '\n' '|') | box: $(tr '\n' '|' <<<"$wheels_box")"; fi
# a capture program for the server, as far as its guard goes: a lock held on the file launch.pyw looks for, until this
# script closes the program's input (a FIFO); its process id is kept, and only that process is ever ended
holder_py='import fcntl, importlib.machinery, importlib.util, os, sys
loader = importlib.machinery.SourceFileLoader("launch_guard", sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
fd = os.open(m.guard_file(m.instance_name(sys.argv[2])), os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("held", flush=True)
sys.stdin.read()'
rm -f "$work/hold" "$work/held" && mkfifo "$work/hold"
env -i TMPDIR="$work" PATH=/usr/bin:/bin python3 -c "$holder_py" "$launch_pyw" "ws://127.0.0.1:8777/ingest" < "$work/hold" > "$work/held" 2>&1 &
holder_pid=$!
exec 9> "$work/hold"                  # the program's input, open until the check is done
for _ in $(seq 1 50); do grep -q held "$work/held" 2>/dev/null && break; sleep 0.1; done
state; EXTRA_ENV="$offwin PYTHONPATH=$work/pymods" run_launch; guarded="$(cat "$work/out")"
exec 9>&-                             # its input closes: it lets the lock go and ends
for _ in $(seq 1 50); do kill -0 "$holder_pid" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$holder_pid" 2>/dev/null; then kill "$holder_pid"; fi   # (the one process started here, by its id)
wait "$holder_pid" 2>/dev/null
if grep -q held "$work/held" && grep -qxF "[dry-run] open: http://127.0.0.1:8777" <<<"$guarded" && ! grep -q '^\[dry-run\] start: ' <<<"$guarded"; then
  ok "...and with a capture program holding its guard for the server, launch.pyw opens the panel and starts no second one"
else bad "...and with a capture program holding its guard for the server, launch.pyw opens the panel and starts no second one" \
         "holder: $(cat "$work/held" | tr '\n' '|') | $(grep -a '\[dry-run\]' <<<"$guarded" | tr '\n' '|')"; fi

# 68. install and restart say an option they do not know before doing anything: install dropped one without a word and ran
#     without it, and restart took anything but --now as nothing
state; EXTRA_ENV="SIDENOTE_LANG=en" run install --with-modles; i_bogus="$(cat "$work/out")"; i_bogus_rc="$(cat "$work/rc")"
last_call docker compose; i_calls=${#CALL[@]}
state server-running; EXTRA_ENV="SIDENOTE_LANG=en" run restart --soon; r_bogus="$(cat "$work/out")"; r_bogus_rc="$(cat "$work/rc")"
last_call docker up; r_calls=${#CALL[@]}
if [ "$i_bogus_rc" != 0 ] && grep -qF "Unknown option: --with-modles (./sidenote install [--with-models])" <<<"$i_bogus" && [ "$i_calls" = 0 ] \
   && ! grep -qF "Installing Sidenote" <<<"$i_bogus" \
   && [ "$r_bogus_rc" != 0 ] && grep -qF "Unknown option: --soon (./sidenote restart [--now])" <<<"$r_bogus" && [ "$r_calls" = 0 ]; then
  ok "install and restart say an option they do not know, and do nothing"
else bad "install and restart say an option they do not know, and do nothing" \
         "install rc $i_bogus_rc calls $i_calls: $(tail -2 <<<"$i_bogus" | tr '\n' '|') | restart rc $r_bogus_rc calls $r_calls: $(tail -2 <<<"$r_bogus" | tr '\n' '|')"; fi

# --- a command's own help, the server that answers, an agent with no login, what is printed to be typed again ----------
# 69. --help (or -h) after a command prints that command's lines of the help, as `help` prints them, and does nothing
#     else: no Docker, no Windows program, no server asked, no browser, no pip. Taken as one more word it stopped
#     everything (down), ended the capture (capture-stop), opened the browser (open), made the shortcut (shortcut), ran
#     pip (setup-capture) and asked for a model named --help (llm pull). llm and gpu take the word after them, the other
#     names are the help's own, a name that is no command's is said as before, and no python3 is needed.
#     Each case: "<what is typed>;<the start of each of its lines>;<how many lines>" (the lines under one are indented)
help_cases=("down --help;down;1" "stop -h;down;1" "capture-stop --help;capture-stop;1" "open --help;open;1"
            "shortcut --help;shortcut;1" "shortcut --remove --help;shortcut;1" "setup-capture --help;setup-capture;2"
            "setup-windows -h;setup-capture;2" "llm pull --help;llm pull;1" "llm --help;llm;3" "llm rm gemma4:e4b --help;llm rm;1"
            "llm logs --help;llm list|logs;1" "gpu off --help;gpu off|on;1" "gpu --help;gpu;2" "login --help;login;1"
            "login codex --help;login;1" "capture --monitor 2 --help;capture;9" "capture -h;capture;9" "up --now --help;up;4"
            "start --help;up;4" "restart -h;restart;2" "backup --help;backup;1" "restore x.tar.gz --help;restore;1"
            "status --help;status;1" "events -n 5 --help;events;1" "report --help;report;1" "stats --help;stats;1"
            "logs --help;logs;1" "doctor --help;doctor;1" "install --help;install;1" "uninstall --yes --help;uninstall;1"
            "version --help;version;1" "capture-restart --help;capture-restart;1" "qa --help;qa;1")
helped=""
for lang in en ko; do
  state; EXTRA_ENV="SIDENOTE_LANG=$lang" run help; whole="$(cat "$work/out")"
  for c in "${help_cases[@]}"; do
    IFS=';' read -r typed start n <<<"$c"
    if [ "$lang" = ko ]; then case "$typed" in down*|llm\ pull*|capture\ -h|gpu\ off*|open*) ;; *) continue ;; esac; fi   # a few in Korean
    read -r -a argv <<<"$typed"
    state running server-running; EXTRA_ENV="SIDENOTE_LANG=$lang" run "${argv[@]}"
    got="$(cat "$work/out")"; why=""
    [ "$(cat "$work/rc")" = 0 ] || why="exit $(cat "$work/rc")"
    [ "$(grep -c '' <<<"$got")" = "$n" ] || why="$why, $(grep -c '' <<<"$got") lines"
    [[ $(head -1 <<<"$got") == "    ./sidenote $start "* ]] || why="$why, first line: $(head -1 <<<"$got" | cut -c1-60)"
    while IFS= read -r line; do   # each line is the command's own, or one under it, and is the help's word for word
      [[ $line == "    ./sidenote $start "* || $line == "      "* ]] || why="$why, not its line: ${line:0:50}"
      grep -qxF -- "$line" <<<"$whole" || why="$why, not in the help: ${line:0:50}"
    done <<<"$got"
    [ -z "$(ls -A "$work/calls")" ] || why="$why, called: $(ls "$work/calls" | sed 's/\..*//' | sort -u | tr '\n' ' ')"
    [ -z "$why" ] || helped="$helped [$lang] $typed: ${why#, };"
  done
done
state; EXTRA_ENV="SIDENOTE_LANG=en" run nosuch --help; h_unknown_rc="$(cat "$work/rc")"; h_unknown="$(head -1 "$work/out")"
state; EXTRA_ENV="PATH=$work/bin:$work/nopy SIDENOTE_LANG=en" run down --help; h_nopy_rc="$(cat "$work/rc")"; h_nopy="$(cat "$work/out")"
if [ -z "$helped" ] && [ "$h_unknown_rc" = 1 ] && [ "$h_unknown" = "Unknown command: nosuch" ] \
   && [ "$h_nopy_rc" = 0 ] && [[ $h_nopy == "    ./sidenote down "* ]]; then
  ok "--help after a command prints its own lines of the help and does nothing else, in both languages and with no python3"
else bad "--help after a command prints its own lines of the help and does nothing else, in both languages and with no python3" \
         "${helped:-} unknown: rc $h_unknown_rc '$h_unknown'; no python3: rc $h_nopy_rc '$(head -1 <<<"$h_nopy")'"; fi

# 70. Only Sidenote's server is taken for the server: another program on the port that answers 200, with a web page or with
#     JSON of its own ({"ok": true} and no analyzer, or ok false), is no server. status says the server is off and ends
#     well (it said "running", then ended 1 without a word or in a KeyError traceback), install starts the server rather
#     than saying it runs, and open says it is off and opens nothing. The server's own answer still reads as running.
foreign=""
for answer in '<!doctype html><html><body>another program</body></html>' '{"ok": true}' '{"ok": false, "analyzer": "local"}'; do
  state; printf '%s\n' "$answer" > "$work/state/health.json"
  EXTRA_ENV="SIDENOTE_LANG=en" run status; f_status="$(cat "$work/out")"; f_status_rc="$(cat "$work/rc")"
  EXTRA_ENV="SIDENOTE_LANG=en" run install; f_install="$(cat "$work/out")"; last_call docker up; f_up=${#CALL[@]}
  EXTRA_ENV="SIDENOTE_LANG=en" run open; f_open="$(cat "$work/out")"; f_open_rc="$(cat "$work/rc")"; last_call cmd start; f_start=${#CALL[@]}
  if [ "$f_status_rc" != 0 ] || ! grep -qF "Server: off" <<<"$f_status" || grep -qE "Server: running|Traceback" <<<"$f_status"; then
    foreign="$foreign status, $answer: exit $f_status_rc, $(tr '\n' '|' <<<"$f_status" | head -c 160);"
  fi
  if grep -qF "Already running" <<<"$f_install" || [ "$f_up" = 0 ]; then foreign="$foreign install, $answer: compose up $f_up;"; fi
  if [ "$f_open_rc" = 0 ] || [ "$f_start" != 0 ] || ! grep -qF "The server is off" <<<"$f_open"; then
    foreign="$foreign open, $answer: exit $f_open_rc, browser $f_start;"
  fi
done
state; EXTRA_ENV="SIDENOTE_LANG=en" run status; f_own="$(cat "$work/out")"
if [ -z "$foreign" ] && grep -qF "Server: running" <<<"$f_own"; then
  ok "another program answering on the port is no server: status says off, install starts it, open opens nothing"
else bad "another program answering on the port is no server: status says off, install starts it, open opens nothing" \
         "${foreign:-} own server: $(grep -F "Server:" <<<"$f_own" | head -1)"; fi

# 71. login with the agent off, or the stand-in for tests (SIDENOTE_AGENT=mock, or SIDENOTE_ANALYZER=mock with no agent
#     named), says that, with the way to check a real one, and ends 1 having signed nothing in: both were called an
#     unknown agent. An agent named after login still signs in, and a word that names none is still unknown.
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_AGENT=off" run login; l_off="$(cat "$work/out")"; l_off_rc="$(cat "$work/rc")"
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_AGENT=mock" run login; l_mock="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_ANALYZER=mock" run login; l_amock="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_AGENT=off" run login; l_ko="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_AGENT=off" run login codex; l_codex="$(cat "$work/out")"
state; EXTRA_ENV="SIDENOTE_LANG=en SIDENOTE_AGENT=off" run login bogus; l_bogus="$(cat "$work/out")"
if [ "$l_off_rc" = 1 ] && grep -qF "The agent is off (SIDENOTE_AGENT=off), so there is no login to check" <<<"$l_off" \
   && grep -qF "./sidenote login codex" <<<"$l_off" && grep -qF "The agent is the stand-in for tests (mock)" <<<"$l_mock" \
   && grep -qF "The agent is the stand-in for tests (mock)" <<<"$l_amock" && grep -qF "에이전트가 꺼져 있어(SIDENOTE_AGENT=off)" <<<"$l_ko" \
   && ! grep -qF "Unknown agent" <<<"$l_off$l_mock$l_amock" && ! grep -qF "알 수 없는 에이전트" <<<"$l_ko" \
   && grep -qF "./sidenote login codex" <<<"$l_codex" && ! grep -qF "The agent is off" <<<"$l_codex" \
   && grep -qF "Unknown agent: bogus" <<<"$l_bogus"; then
  ok "login with the agent off or the stand-in for tests says so, and an agent named after login still signs in"
else bad "login with the agent off or the stand-in for tests says so, and an agent named after login still signs in" \
         "off (exit $l_off_rc): $(tail -1 <<<"$l_off") | mock: $(tail -1 <<<"$l_mock") | analyzer mock: $(tail -1 <<<"$l_amock") | ko: $(tail -1 <<<"$l_ko") | codex: $(tail -1 <<<"$l_codex") | bogus: $(tail -1 <<<"$l_bogus")"; fi

# 72. The lines printed to be typed again name a path with a space or a quote in it as one word: backup's restore line,
#     restore's line with --yes when there is no terminal to ask in, and llm rm's. Read back by a shell, each gives the
#     words it was asked with; printed as they were, the path came back as two words, which restore refused.
words_of() { local line="$1"; set --; eval "set -- $line" 2>/dev/null || return 1; printf '<%s>' "$@"; }   # as a shell reads them
rm -rf "$logs" && mkdir -p "$logs" && printf '{"lang": "en"}\n' > "$logs/.settings.json"
spaced="$here/my backups"; mkdir -p "$spaced"; q_file="$spaced/it's a backup.tar.gz"; rm -f "$q_file"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$q_file"; q_backup_rc="$(cat "$work/rc")"
q_back="$(grep -F "(to put it back: ./sidenote restore " "$work/out" | sed 's/.*(to put it back: \.\/sidenote restore //; s/)$//')"
state; EXTRA_ENV="SIDENOTE_LANG=en" run restore "$q_file"; q_rest="$(grep -F "To restore it: ./sidenote restore " "$work/out" | sed 's/.*To restore it: \.\/sidenote restore //')"
state llm-running llm-models; EXTRA_ENV="SIDENOTE_LANG=en" run llm rm gemma4:e4b "no such"
q_rm="$(grep -F "To remove them: ./sidenote llm rm " "$work/out" | sed 's/.*To remove them: \.\/sidenote llm rm //')"
if [ "$q_backup_rc" = 0 ] && [ "$(words_of "$q_back")" = "<$q_file>" ] && [ "$(words_of "$q_rest")" = "<$q_file><--yes>" ] \
   && [ "$(words_of "$q_rm")" = "<gemma4:e4b><no such><--yes>" ]; then
  ok "the lines printed to be typed again (restore after backup, restore --yes, llm rm --yes) read back as the words asked"
else bad "the lines printed to be typed again (restore after backup, restore --yes, llm rm --yes) read back as the words asked" \
         "backup exit $q_backup_rc: '$q_back' | restore: '$q_rest' | llm rm: '$q_rm'"; fi

# 73. backup given a folder makes its file in it, named for the date and time: "." in the folder it is typed in, a
#     folder by its path, and one that is not there (a name that ends in /) is said as such. "." was said to be a file
#     that was there already, and no backup was made.
mkdir -p "$here/into" "$here/dot"; rm -rf "$here/nowhere"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/into"; f_into_rc="$(cat "$work/rc")"
f_into="$(ls "$here/into"/sidenote-backup-*.tar.gz 2>/dev/null | head -1)"
state; (cd "$here/dot" && EXTRA_ENV="SIDENOTE_LANG=en" run backup .); f_dot_rc="$(cat "$work/rc")"; f_dot_out="$(cat "$work/out")"
f_dot="$(ls "$here/dot"/sidenote-backup-*.tar.gz 2>/dev/null | head -1)"
state; EXTRA_ENV="SIDENOTE_LANG=en" run backup "$here/nowhere/"; f_none_rc="$(cat "$work/rc")"; f_none="$(cat "$work/out")"
if [ "$f_into_rc" = 0 ] && [ -n "$f_into" ] && tar -tzf "$f_into" 2>/dev/null | grep -qx .settings.json \
   && [ "$f_dot_rc" = 0 ] && [ -n "$f_dot" ] && grep -qF "Backed up: $f_dot (" <<<"$f_dot_out" \
   && [ "$f_none_rc" = 1 ] && grep -qF "No such folder: $here/nowhere/" <<<"$f_none" && [ ! -e "$here/nowhere" ]; then
  ok "backup into a folder (., or one by its path) makes its file there, and one that is not there is said"
else bad "backup into a folder (., or one by its path) makes its file there, and one that is not there is said" \
         "folder: exit $f_into_rc ${f_into:-no file} | .: exit $f_dot_rc ${f_dot:-no file}, $(tail -3 <<<"$f_dot_out" | head -1) | none: exit $f_none_rc $(tail -1 <<<"$f_none")"; fi

# 74. events and report with the server off read the log folder in a throwaway container, which mounts it only when it is
#     there: Docker makes a missing one itself, and each missing folder above it, as root with mode 755, where up makes it
#     this user's alone. With none the report is given the folder's path, and nothing is made; with one it is mounted
#     read-only, as it was.
gone_logs="$work/nothere/logs"; rm -rf "$work/nothere"
state; EXTRA_ENV="SIDENOTE_LOG_PATH=$gone_logs" run events; last_call docker run; e_call=" ${CALL[*]-} "; e_made="$(cat "$work/state/docker-made" 2>/dev/null)"
state; EXTRA_ENV="SIDENOTE_LOG_PATH=$gone_logs" run report --days 3; last_call docker run; r_call=" ${CALL[*]-} "
r_made="$(cat "$work/state/docker-made" 2>/dev/null)"
mkdir -p "$logs"; state; run events -n 5; last_call docker run; h_call=" ${CALL[*]-} "
if [ ! -e "$work/nothere" ] && [ -z "$e_made$r_made" ] && [[ $e_call == *" -e SIDENOTE_LOG_DIR=$gone_logs "* ]] && [[ $e_call != *" -v "* ]] \
   && [[ $r_call == *" -e SIDENOTE_LOG_DIR=$gone_logs "*" server.report report --days 3 " ]] && [[ $h_call == *" -v $logs:/data/logs:ro "* ]]; then
  ok "events and report with the server off mount the log folder only when it is there, and make none"
else bad "events and report with the server off mount the log folder only when it is there, and make none" \
         "made: ${e_made:-}${r_made:-none} | events:$e_call | report:$r_call | with the folder:$h_call"; fi

# 75. up that ends before compose (offline, with an image that is not here) leaves no temporary file behind, nor does one
#     that starts the server
mkdir -p "$work/uptmp" && rm -rf "$work/uptmp"/*
state no-image; EXTRA_ENV="SIDENOTE_OFFLINE=1 SIDENOTE_LANG=en TMPDIR=$work/uptmp" run up; t_rc="$(cat "$work/rc")"; t_out="$(cat "$work/out")"
t_left="$(ls -A "$work/uptmp")"
state; EXTRA_ENV="SIDENOTE_LANG=en TMPDIR=$work/uptmp" run up; t2_rc="$(cat "$work/rc")"; t2_left="$(ls -A "$work/uptmp")"
if [ "$t_rc" != 0 ] && grep -qF "sidenote:local is not on this PC" <<<"$t_out" && [ -z "$t_left" ] && [ "$t2_rc" = 0 ] && [ -z "$t2_left" ]; then
  ok "up leaves no temporary file behind, when it ends early as when it starts the server"
else bad "up leaves no temporary file behind, when it ends early as when it starts the server" \
         "early: exit $t_rc, left: ${t_left:-nothing}, $(tail -1 <<<"$t_out") | started: exit $t2_rc, left: ${t2_left:-nothing}"; fi

printf '  ==== %d of %d as expected\n' "$pass" "$((pass + fail))"
[ "$fail" = 0 ]
