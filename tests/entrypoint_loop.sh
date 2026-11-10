#!/usr/bin/env bash
# The loop that starts a container's program again when it ends by itself (docker/keep-running.sh), and the server's
# entrypoint that runs uvicorn in it (docker/entrypoint.sh). Under compose nothing started a server that ended by
# itself until someone typed ./sidenote up, and compose's own restart policies would also start it at the PC's boot.
#
#   bash tests/entrypoint_loop.sh
#
# The scripts run here as the containers run them, under /bin/sh (dash on Debian and Ubuntu, as in the images), with
# small programs standing in for uvicorn: no Docker, no image. Each line of output is one check:
# - a program that keeps failing is started 5 times and then left ended, with its exit code, and .ended says so;
# - one that ends well is not started again, and one that fails once is started again and goes on;
# - the watchdog's stall.txt, written during a run, is in the note;
# - TERM and INT end the program (INT as TERM) and nothing is started again; USR1 reaches it and it runs on;
# - the note of an earlier container is gone at the start;
# - the entrypoint runs uvicorn in the loop, with the shutdown wait, and with SIDENOTE_SELF_RESTART=0 (Kubernetes) on
#   its own.
set -uo pipefail                      # not -e: a failing check has to print and go on to the next

root="$(cd "$(dirname "$0")/.." && pwd)"   # the checkout (this file is in tests/)
loop="$root/docker/keep-running.sh"
entry="$root/docker/entrypoint.sh"
work="$(mktemp -d)"                   # the log folder, the stand-ins and their records
started=()                            # the process ids this script starts in the background: the only ones it ends
cleanup() {
  local p
  for p in ${started[@]+"${started[@]}"}; do kill -TERM "$p" 2>/dev/null; done
  rm -rf "$work"
}
trap cleanup EXIT

pass=0 fail=0
ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }

# A program for the loop to run: each start appends a line to $work/starts, then it does what its script says
prog() { printf '#!/bin/sh\necho start >> "%s/starts"\n%s\n' "$work" "$1" > "$work/prog"; chmod +x "$work/prog"; : > "$work/starts"; }
starts() { wc -l < "$work/starts" | tr -d ' '; }
note() { cat "$work/logs/.ended" 2>/dev/null; }
fresh() { rm -rf "$work/logs" && mkdir -p "$work/logs"; }
# The loop in the foreground, with the log folder set as the server's container sets it; its exit code in $rc
run_loop() { SIDENOTE_LOG_DIR="$work/logs" timeout 60 /bin/sh "$loop" "$@" > "$work/out" 2>&1; rc=$?; }
# The loop in the background, its process id in $bg once the program has started (it ends with the check that started it).
# Started with INT at its default, as a container's first process is: bash gives a program it starts in the background
# INT ignored, and a shell started that way cannot catch it (python3 sets it back, then becomes the loop's sh)
bg_loop() {
  SIDENOTE_LOG_DIR="$work/logs" python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' \
    /bin/sh "$loop" "$@" > "$work/out" 2>&1 &
  bg=$!
  started+=("$bg")
  local i; for i in $(seq 1 50); do [ "$(starts)" -ge 1 ] && break; sleep 0.1; done
}
# Waits for the background loop to end, up to 10 s, its exit code in $rc ("still running" when it did not)
end_of() { local i; for i in $(seq 1 100); do kill -0 "$1" 2>/dev/null || break; sleep 0.1; done
           if kill -0 "$1" 2>/dev/null; then rc="still running"; else wait "$1"; rc=$?; fi; }

echo "entrypoint_loop ($loop)"

# 1. A program that keeps failing: started 5 times, then left ended with its exit code, and the note says it stopped
fresh; prog 'exit 3'; t0=$(date +%s); run_loop "$work/prog"
read -r when code n what stall <<<"$(note)"
if [ "$rc" = 3 ] && [ "$(starts)" = 5 ] && [ "$code" = 3 ] && [ "$n" = 5 ] && [ "$what" = stopped ] && [ "$stall" = - ] \
   && [ "$when" -ge "$t0" ] && grep -qF "not started again" "$work/out"; then
  ok "a program that keeps failing is started 5 times, then left ended with its code; .ended says it stopped"
else bad "a program that keeps failing is started 5 times, then left ended with its code; .ended says it stopped" \
         "rc $rc, starts $(starts), note '$(note)', said: $(tail -1 "$work/out")"; fi

# 2. One that ends well is not started again, and leaves no note
fresh; prog 'exit 0'; run_loop "$work/prog"
if [ "$rc" = 0 ] && [ "$(starts)" = 1 ] && [ -z "$(note)" ]; then ok "a program that ends with 0 is not started again"
else bad "a program that ends with 0 is not started again" "rc $rc, starts $(starts), note '$(note)'"; fi

# 3. One that fails once is started again a second later and goes on; the note says it was restarted
fresh; prog '[ "$(wc -l < "'"$work"'/starts")" -ge 2 ] && exit 0; exit 1'; t0=$(date +%s); run_loop "$work/prog"; took=$(( $(date +%s) - t0 ))
read -r when code n what stall <<<"$(note)"
if [ "$rc" = 0 ] && [ "$(starts)" = 2 ] && [ "$code" = 1 ] && [ "$n" = 1 ] && [ "$what" = restarted ] && [ "$took" -ge 1 ]; then
  ok "a program that fails once is started again a second later; .ended says it was restarted"
else bad "a program that fails once is started again a second later; .ended says it was restarted" "rc $rc, starts $(starts), $took s, note '$(note)'"; fi

# 4. The watchdog's stall.txt, written during the run that ended, is in the note
fresh; prog '[ "$(wc -l < "'"$work"'/starts")" -ge 2 ] && exit 0; echo stacks > "'"$work"'/logs/stall.txt"; exit 1'; run_loop "$work/prog"
read -r when code n what stall <<<"$(note)"
if [ "$rc" = 0 ] && [ "$what" = restarted ] && [ "$stall" = stall ]; then ok "a run that wrote stall.txt is noted as a stall"
else bad "a run that wrote stall.txt is noted as a stall" "rc $rc, note '$(note)'"; fi

# 5. TERM (docker stop) reaches the program, which ends, and nothing is started again: the loop ends with its code
fresh; prog 'trap "exit 0" TERM; while :; do sleep 0.1; done'; bg_loop "$work/prog"; kill -TERM "$bg"; end_of "$bg"
term_rc="$rc"; term_starts="$(starts)"
fresh; prog 'while :; do sleep 0.1; done'; bg_loop "$work/prog"; kill -TERM "$bg"; end_of "$bg"
killed_rc="$rc"; killed_starts="$(starts)"
if [ "$term_rc" = 0 ] && [ "$term_starts" = 1 ] && [ "$killed_rc" = 143 ] && [ "$killed_starts" = 1 ] && [ -z "$(note)" ]; then
  ok "TERM reaches the program and nothing is started again (its code: 0 when it closed down, 143 when TERM ended it)"
else bad "TERM reaches the program and nothing is started again (its code: 0 when it closed down, 143 when TERM ended it)" \
         "closed down: rc $term_rc, starts $term_starts | ended by TERM: rc $killed_rc, starts $killed_starts, note '$(note)'"; fi

# 6. INT reaches it as TERM (a program in the background ignores INT), and USR1 as USR1 while it runs on
fresh; prog 'trap "echo usr1 >> '"$work"'/signals" USR1; trap "echo term >> '"$work"'/signals; exit 0" TERM; while :; do sleep 0.1; done'
: > "$work/signals"; bg_loop "$work/prog"
kill -USR1 "$bg"; for _ in $(seq 1 30); do grep -q usr1 "$work/signals" && break; sleep 0.1; done
alive=no; kill -0 "$bg" 2>/dev/null && alive=yes
kill -INT "$bg"; end_of "$bg"
if [ "$(tr '\n' ' ' < "$work/signals")" = "usr1 term " ] && [ "$alive" = yes ] && [ "$rc" = 0 ] && [ "$(starts)" = 1 ]; then
  ok "USR1 reaches the running program, which runs on; INT reaches it as TERM, and nothing is started again"
else bad "USR1 reaches the running program, which runs on; INT reaches it as TERM, and nothing is started again" \
         "signals: $(tr '\n' ' ' < "$work/signals"), alive after USR1: $alive, rc $rc, starts $(starts)"; fi

# 7. The note of an earlier container is gone when the loop starts
fresh; echo "1700000000 1 5 stopped -" > "$work/logs/.ended"; prog 'exit 0'; run_loop "$work/prog"
if [ "$rc" = 0 ] && [ ! -e "$work/logs/.ended" ]; then ok "an earlier container's .ended is gone at the start"
else bad "an earlier container's .ended is gone at the start" "rc $rc, note '$(note)'"; fi

# 8. The entrypoint runs uvicorn in the loop with the shutdown wait; with SIDENOTE_SELF_RESTART=0 it runs it alone, and
#    one that fails is then not started again (Kubernetes does that)
mkdir -p "$work/bin"
printf '#!/bin/sh\necho "$*" >> "%s/uvicorn-args"\nexit "${UVICORN_EXIT:-0}"\n' "$work" > "$work/bin/uvicorn"; chmod +x "$work/bin/uvicorn"
fresh; : > "$work/uvicorn-args"
SIDENOTE_LOG_DIR="$work/logs" UVICORN_EXIT=3 PATH="$work/bin:/usr/bin:/bin" timeout 60 /bin/sh "$entry" > "$work/out" 2>&1; looped_rc=$?
looped="$(wc -l < "$work/uvicorn-args" | tr -d ' ')"; args="$(head -1 "$work/uvicorn-args")"
: > "$work/uvicorn-args"
SIDENOTE_LOG_DIR="$work/logs" UVICORN_EXIT=3 SIDENOTE_SELF_RESTART=0 PATH="$work/bin:/usr/bin:/bin" timeout 60 /bin/sh "$entry" > "$work/out" 2>&1; alone_rc=$?
alone="$(wc -l < "$work/uvicorn-args" | tr -d ' ')"
if [ "$looped_rc" = 3 ] && [ "$looped" = 5 ] && [ "$alone_rc" = 3 ] && [ "$alone" = 1 ] \
   && [[ $args == "server.app:app --host 0.0.0.0 --port 8777 --no-access-log --ws-max-size 67108864 --timeout-graceful-shutdown 5" ]]; then
  ok "the entrypoint runs uvicorn in the loop, with a 5 s shutdown wait; with SIDENOTE_SELF_RESTART=0 alone"
else bad "the entrypoint runs uvicorn in the loop, with a 5 s shutdown wait; with SIDENOTE_SELF_RESTART=0 alone" \
         "looped: rc $looped_rc, starts $looped | alone: rc $alone_rc, starts $alone | args: $args"; fi

printf '  ==== %d of %d as expected\n' "$pass" "$((pass + fail))"
[ "$fail" = 0 ]
