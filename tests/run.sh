#!/usr/bin/env bash
# The suites CI runs: the server and the capture program in mock mode, and the panel in a headless browser. Each suite
# ends with its own tally line; this prints that line for every suite and ends non-zero if any of them failed.
#
#   tests/run.sh                  every suite
#   tests/run.sh server           the server and capture suites, each run with $PY (default python3)
#   tests/run.sh panel            the panel suites, each run with $PW (default python3)
#   tests/run.sh --list [group]   the suites a run would start, and with what, without running any
#
# SUITES="panel_layout" runs only the suites named, SKIP_SUITES="panel_layout panel_design" all but those: CI splits the
# panel group between jobs this way, and a panel suite's own ONLY and SKIP pick its groups (tests/README.md).
# Every suite runs with SIDENOTE_ANALYZER=mock. What the suites write (a log for each, screenshots, the settings
# message) goes to $SIDENOTE_TEST_OUT, a new temporary folder unless it is set. The checks that read the measurement
# data, which is not in the repository (SIDENOTE_BENCH, SIDENOTE_CORPUS, SIDENOTE_FACES), are skipped where it is
# missing, and the suite's line says what it skipped: tests/README.md.
set -uo pipefail                       # not -e: a failing suite has to be counted and the next one run

# An interpreter named by a path is made absolute, from the folder this was started in, so a suite finds it from any
# folder it starts it in. Not with readlink -f: that would resolve a virtual environment's python to the system's and
# leave the environment's packages behind.
absolute() {
  case "$1" in
    */*) if [ -d "$(dirname "$1")" ]; then printf '%s/%s' "$(cd "$(dirname "$1")" && pwd)" "$(basename "$1")"
         else printf '%s' "$1"; fi ;;
    *) printf '%s' "$1" ;;
  esac
}
PY="$(absolute "${PY:-python3}")"
PW="$(absolute "${PW:-python3}")"
export PY PW                           # the panel suites ask the server's own code for things through PY (support.py)
export SIDENOTE_LANG=ko                # the server's words in Korean, as the suites' checks read them (i18n_check sets its own)
self="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"   # this script, for its usage text after the cd below

cd "$(dirname "$0")/.." || exit 2      # the repository's root, whatever folder this was started from

# The suites in the order they run. Each is tests/<name>.py, run with its group's interpreter, except launcher_args and
# entrypoint_loop, which are tests/<name>.sh, run with bash.
SERVER=(integ agent_first local_fallback server_review worker_order voice_trigger speech_hints heard_keep lang_vote stall_guard capture_loop up_wait
        report_period capture_update capture_panel capture_skip scroll_auto poll_rate crop_grow audio_path audio_gaps tray_switch launch_window start_output capture_single launch_setup
        codex_agent repeats_check limits_check server_scenarios models_check desktop_check desktop_restart i18n_check history_star history_delete api_check stalled_panel many_clients session_end ci_gate
        update_check version_check changelog_check launcher_args entrypoint_loop)
PANEL=(panel_scroll panel_run panel_asks panel_settings panel_review panel_viz panel_churn panel_limits panel_new panel_star panel_delete panel_heard panel_scenarios panel_study panel_design panel_lang panel_layout panel_reading
       panel_setup panel_capture panel_update)
# What the suites import or start: not suites themselves
HELPERS=(support panel_harness fake_claude fake_codex)

usage() { sed -n '2,13p' "$self" | sed 's/^# \{0,1\}//'; }   # the comment at the top, without its marks

# A suite written and left out of the lists above never runs, here or in CI, and nothing says so. Nor may one go undocumented.
accounted() {
  local bad=0 f n
  for f in tests/*.py tests/*.sh; do
    n="$(basename "${f%.*}")"
    # this script, the three that need Docker and real images, the one that needs helm, and the one that needs the
    # built Mac app, each run by a CI job of its own
    { [ "$n" = run ] || [ "$n" = k3d_check ] || [ "$n" = nonroot_check ] || [ "$n" = offline_check ] \
      || [ "$n" = chart_check ] || [ "$n" = mac_app_open ]; } && continue
    case " ${SERVER[*]} ${PANEL[*]} ${HELPERS[*]} " in
      *" $n "*) ;;
      *) echo "tests/run.sh: $f is in no list of suites" >&2; bad=1 ;;
    esac
  done
  for n in "${SERVER[@]}" "${PANEL[@]}"; do
    [ -f "tests/$n.py" ] || [ -f "tests/$n.sh" ] || { echo "tests/run.sh: suite $n has no file" >&2; bad=1; }
    grep -qE "\`$n\.(py|sh)\`" tests/README.md || { echo "tests/run.sh: suite $n is not in tests/README.md" >&2; bad=1; }
  done
  return "$bad"
}

list=0 group="" only_check=0
for arg in "$@"; do
  case "$arg" in
    --list) list=1 ;;
    --check) only_check=1 ;;
    server|panel)
      [ -z "$group" ] || { echo "tests/run.sh: one group at a time, $group or $arg" >&2; exit 2; }
      group="$arg" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "tests/run.sh: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
  esac
done

# Whether a suite is in this run (SUITES, SKIP_SUITES above)
chosen() {
  { [ -z "${SUITES:-}" ] || [[ " $SUITES " == *" $1 "* ]]; } && [[ " ${SKIP_SUITES:-} " != *" $1 "* ]]
}

suite() {   # suite <name> <interpreter>: the command that runs one suite, into the array CMD
  if [ -f "tests/$1.sh" ]; then CMD=(bash "tests/$1.sh"); else CMD=("$2" "tests/$1.py"); fi   # launcher_args, entrypoint_loop
}

accounted || exit 2
[ "$only_check" = 1 ] && { echo "every suite is in a list and in tests/README.md"; exit 0; }

if [ "$list" = 1 ]; then               # what a run would start, one line a suite, and nothing else
  if [ "$group" != panel ]; then
    echo "server and capture (mock mode)"
    for s in "${SERVER[@]}"; do chosen "$s" || continue; suite "$s" "$PY"; printf '  %-15s %s\n' "$s" "${CMD[*]}"; done
  fi
  if [ "$group" != server ]; then
    echo "panel (headless browser)"
    for s in "${PANEL[@]}"; do chosen "$s" || continue; suite "$s" "$PW"; printf '  %-15s %s\n' "$s" "${CMD[*]}"; done
  fi
  exit 0
fi

# The interpreters this run needs, said once here rather than as a failure of every suite. The panel group needs PY
# too: the settings message it feeds the page and panel_viz's prompt examples come from the server's own code.
for need in PY $([ "$group" != server ] && echo PW); do
  command -v "${!need}" > /dev/null || { echo "tests/run.sh: $need=${!need} is not an interpreter here" >&2; exit 2; }
done

out="${SIDENOTE_TEST_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/sidenote-tests.XXXXXX")}"
mkdir -p "$out/logs" || exit 2
out="$(cd "$out" && pwd)"              # absolute, for the suites and for the paths printed below
export SIDENOTE_TEST_OUT="$out"        # one folder for the whole run: the panel suites share one settings message
echo "output and logs in $out"
fails=0
results="$out/results.md"
printf '| Suite | Result | Checks | Skipped | Seconds |\n|---|---|---:|---|---:|\n' > "$results"
total_ok=0 total_bad=0

# The three forms of tally line the suites print, and whether one says nothing failed.
TALLY='passed, [0-9]+ failed|[0-9]+ of [0-9]+ as expected|[0-9]+ ok, [0-9]+ FAIL'
tally_clean() {
  if [[ $1 =~ ([0-9]+)\ passed,\ ([0-9]+)\ failed ]]; then [ "${BASH_REMATCH[2]}" = 0 ]
  elif [[ $1 =~ ([0-9]+)\ of\ ([0-9]+)\ as\ expected ]]; then [ "${BASH_REMATCH[1]}" = "${BASH_REMATCH[2]}" ]
  elif [[ $1 =~ ([0-9]+)\ ok,\ ([0-9]+)\ FAIL ]]; then [ "${BASH_REMATCH[2]}" = 0 ]
  else return 1
  fi
}

one() {   # one <name> <interpreter>: run a suite with its output in a log of its own, and print one line for it
  local name="$1" log="$out/logs/$1.log" rc tally skipped began=$SECONDS good=0 bad=0
  printf '  %-15s ' "$name"
  # The control script is made for WSL: it turns paths into Windows ones with wslpath and starts Windows programs
  # from /mnt/c, so its suite means nothing on a machine without them (a CI runner) and is skipped there, said so.
  if [ "$name" = launcher_args ] && ! command -v wslpath > /dev/null; then
    echo "skipped: the control script needs WSL (wslpath), which this machine does not have"
    printf '| %s | skipped | | needs WSL | |\n' "$name" >> "$results"
    return
  fi
  suite "$name" "$2"
  # The audit opens a page for each state of each surface at each size, so it has more time than the others, on CI's slower machine too
  local limit=900
  [ "$1" = panel_layout ] && limit=1800
  SIDENOTE_ANALYZER=mock timeout "$limit" "${CMD[@]}" > "$log" 2>&1 < /dev/null   # no terminal, as in CI
  rc=$?
  # the suite's own tally, and the line it prints when it skipped checks for want of measurement data
  tally="$(grep -E "$TALLY" "$log" | tail -1 | sed 's/^ *//')"
  skipped="$(grep -E '^skipped [0-9]+ group' "$log" | tail -1)"
  # The checks it made, for the table and the total
  if [[ $tally =~ ([0-9]+)\ passed,\ ([0-9]+)\ failed ]]; then good="${BASH_REMATCH[1]}"; bad="${BASH_REMATCH[2]}"
  elif [[ $tally =~ ([0-9]+)\ of\ ([0-9]+)\ as\ expected ]]; then good="${BASH_REMATCH[1]}"; bad=$((BASH_REMATCH[2] - BASH_REMATCH[1]))
  elif [[ $tally =~ ([0-9]+)\ ok,\ ([0-9]+)\ FAIL ]]; then good="${BASH_REMATCH[1]}"; bad="${BASH_REMATCH[2]}"
  fi
  total_ok=$((total_ok + good)); total_bad=$((total_bad + bad))
  # A suite passes on a zero exit status and a tally that says nothing failed: the status alone let failures through
  # before (suites that printed their failures and ended with 0).
  if [ "$rc" = 0 ] && [ -n "$tally" ] && tally_clean "$tally"; then
    echo "$tally${skipped:+   ($skipped)}"
    printf '| %s | passed | %s | %s | %s |\n' "$name" "$good" "$(echo "$skipped" | cut -c1-60)" "$((SECONDS - began))" >> "$results"
  else
    printf '| %s | **FAILED** | %s passed, %s failed | | %s |\n' "$name" "$good" "$bad" "$((SECONDS - began))" >> "$results"
    case "$rc" in
      124) echo "FAILED: still running after $limit s (see $log)" ;;
      0) echo "FAILED: ${tally:-no tally line} (see $log)" ;;
      *) echo "FAILED: exit status $rc${tally:+, $tally} (see $log)" ;;
    esac
    # On a CI runner the log is gone with the machine: what failed has to be in what it prints
    grep -E '^[[:space:]]*FAIL' "$log" | head -5 | sed 's/^/      /'
    fails=$((fails + 1))
  fi
}

if [ "$group" != panel ]; then
  echo "server and capture (mock mode, $PY)"
  for s in "${SERVER[@]}"; do chosen "$s" && one "$s" "$PY"; done
fi
if [ "$group" != server ]; then
  echo "panel (headless browser, $PW)"
  for s in "${PANEL[@]}"; do chosen "$s" && one "$s" "$PW"; done
fi

echo
printf '\n%s checks passed, %s failed, in this run.\n' "$total_ok" "$total_bad" >> "$results"
# Every test case by name with its result, suite by suite: what was checked, to read or to compare between two runs
for log in "$out"/logs/*.log; do
  [ -e "$log" ] || continue
  printf '## %s\n\n' "$(basename "$log" .log)"
  grep -E '^[[:space:]]*(ok|OK|FAIL)\b' "$log" | sed -E 's/^[[:space:]]+//' | cut -c1-200
  echo
done > "$out/cases.md"
# On a runner the table goes on the run's own page
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then { echo "### tests/run.sh ${group:-all}"; echo; cat "$results"; } >> "$GITHUB_STEP_SUMMARY"; fi
echo "$total_ok checks passed, $total_bad failed (table: $results)"
if [ "$fails" = 0 ]; then echo "all suites passed"; else echo "$fails suite(s) failed: the logs are in $out/logs"; fi
exit $((fails > 0))
