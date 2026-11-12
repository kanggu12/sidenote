#!/bin/sh
# Runs a program and starts it again when it ends by itself in failure, as the desktop app does for the server it starts
# (desktop/app.py). compose.yaml keeps `restart: "no"`: Docker applies a restart policy at its own start too, and a PC
# switched off with Sidenote running would bring it up again at the next boot. This loop lives only as long as its
# container, so nothing outlasts `./sidenote down`, and a container that is not running starts nothing.
#
#   keep-running.sh <program> [arguments ...]
#
# Each run is a process group of its own (setsid, which every image this runs in has), and what is left of the group
# when the run ends is ended with it. A program killed outright (an out-of-memory kill) left its own children running
# beside the next run: SearXNG's worker went on serving after its main process was killed (measured), and Ollama's model
# runners would hold the GPU's memory. Without setsid each run starts as before, and only the program itself ends.
#
# When the program ends:
# - with exit code 0, or after a stop was asked for (TERM or INT, which docker stop sends): this ends with its code;
# - otherwise it is started again a second later, unless it was started LIMIT times in the last WINDOW seconds: then
#   this ends with its code, and the container stays ended until someone starts it (./sidenote up).
# TERM and INT go on to the program as TERM (a program started in the background here ignores INT), and USR1 as USR1:
# the server writes its threads' stacks on it (docker kill -s USR1 sidenote, server/watchdog.py).
# With SIDENOTE_LOG_DIR set (the server's container) each end that was not asked for leaves one line in .ended there,
# which ./sidenote status reads:
#   <when, seconds since 1970> <exit code> <starts in the last WINDOW seconds> <restarted|stopped> <stall|->
# "stall" when stall.txt was written during that run: the watchdog ends a server whose loop stopped turning, with its
# stacks in that file. The note goes when the container starts, so a line there is about the container there now.
# No `set -e`: wait reports the program's failures, which are this script's to read.

LIMIT=5      # starts within WINDOW, the same limit the desktop app sets (10 minutes, 5 times)
WINDOW=600   # seconds

note=""
if [ -n "${SIDENOTE_LOG_DIR:-}" ]; then
  note="$SIDENOTE_LOG_DIR/.ended"
  rm -f "$note" 2>/dev/null || true   # this container's start: an older note is about a container that is gone
fi

asked=0      # a stop was asked for: the program's end is then no failure, and nothing is started again
child=""     # the program's process id while it runs, and its process group's
own=""       # setsid where there is one: each run in a group of its own
if command -v setsid > /dev/null 2>&1; then own=setsid; fi
# What is left of a run's group, ended. dash takes `kill -s KILL -- -group`; busybox reads `--` as a number and fails,
# so its own form comes after it. Quiet when nothing is left.
end_group() { kill -s KILL -- "-$1" 2> /dev/null || kill -s KILL "-$1" 2> /dev/null || true; }
pass() { if [ -n "$child" ]; then kill "-$1" "$child" 2>/dev/null; fi; }
trap 'asked=1; pass TERM' TERM INT
trap 'pass USR1' USR1

starts=""    # when each run began, seconds since 1970, the last WINDOW seconds' only
while :; do
  began=$(date +%s)
  starts="$starts $began"
  $own "$@" &   # setsid starts the program in its place (a job here leads no group), so $! is the program and its group
  child=$!
  # A signal caught here cuts wait short (status above 128) while the program still runs: wait again until it has ended.
  # Status 128 or less is the program's own end; above, a program that is gone was ended by a signal.
  while :; do
    wait "$child"
    code=$?
    if [ "$code" -le 128 ] || ! kill -0 "$child" 2>/dev/null; then break; fi
  done
  if [ -n "$own" ]; then end_group "$child"; fi   # its children it did not end itself, before anything else starts
  child=""
  if [ "$code" = 0 ] || [ "$asked" = 1 ]; then exit "$code"; fi
  # Ended by itself, in failure: the runs begun in the last WINDOW seconds, this one among them
  now=$(date +%s)
  recent=""
  n=0
  for t in $starts; do
    if [ $((now - t)) -lt "$WINDOW" ]; then recent="$recent $t"; n=$((n + 1)); fi
  done
  starts="$recent"
  stall=-
  if [ -n "$note" ] && [ -f "$SIDENOTE_LOG_DIR/stall.txt" ] \
     && [ "$(stat -c %Y "$SIDENOTE_LOG_DIR/stall.txt" 2>/dev/null || echo 0)" -ge "$began" ]; then
    stall=stall
  fi
  if [ "$n" -ge "$LIMIT" ]; then what=stopped; else what=restarted; fi
  if [ -n "$note" ]; then
    printf '%s %s %s %s %s\n' "$now" "$code" "$n" "$what" "$stall" > "$note" 2>/dev/null || true
  fi
  if [ "$what" = stopped ]; then
    echo "keep-running: $1 ended with exit code $code, $n times within $WINDOW seconds: not started again" >&2
    exit "$code"
  fi
  echo "keep-running: $1 ended with exit code $code: starting it again" >&2
  sleep 1 &    # in the background, so a stop asked for meanwhile is read at once
  wait $!
  if [ "$asked" = 1 ]; then exit "$code"; fi
done
