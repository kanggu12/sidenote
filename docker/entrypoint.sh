#!/bin/sh
# The claude CLI in the container signs in with this PC's own Claude Code login: the host's ~/.claude
# is mounted at /root/.claude (compose.yaml), and HOME is /root whichever user this runs as (the launcher starts it as
# the PC's user). Run as root, by `docker compose` by hand or on a PC whose user is root, folders left by the uid 10001 of
# older images are handed back to root. As any other user this has neither the right nor the need: compose.yaml's
# server-init service has already handed these folders to the user.
set -e
export HOME=/root
if [ "$(id -u)" = 0 ]; then
    for d in /data/hf "${SIDENOTE_LOG_DIR:-}"; do
        if [ -n "$d" ] && [ -d "$d" ] && [ "$(stat -c %u "$d")" != 0 ]; then
            chown -R 0:0 "$d" 2>/dev/null || true
        fi
    done
fi
# No per-request access log: the healthcheck alone would add a line every 10 s.
# A 3840x2160 frame of a photo-like screen (a game, a video) can be over 16 MiB as the message that carries it
# (one of random pixels: 23.7 MiB of PNG, 31.7 MiB of message). uvicorn's default limit of 16 MiB closes the
# connection on such a message (code 1009) and the frame is lost; in one run the connection dropped right after
# two of the first frames from this PC's 4K monitor, which fits that.
# A stop waits 5 s at most for open connections: a panel's socket that no longer reads held uvicorn's shutdown for good
# (measured: still waiting after 30 s, when Docker kills it), and the shutdown hook that keeps the remembered problems
# in .restart.npz never ran.
set -- uvicorn server.app:app --host "${SIDENOTE_HOST:-0.0.0.0}" --port "${SIDENOTE_PORT:-8777}" --no-access-log \
    --ws-max-size 67108864 --timeout-graceful-shutdown 5
# Under compose a server that ends by itself (the watchdog ends one whose loop stopped turning) is started again inside
# the container, as the desktop app does: keep-running.sh, beside this file in the image. Kubernetes starts a container
# again itself, and the chart sets SIDENOTE_SELF_RESTART=0 so that a pod's restarts are its own.
if [ "${SIDENOTE_SELF_RESTART:-1}" = 0 ]; then
    exec "$@"
fi
exec /bin/sh "$(dirname "$0")/keep-running.sh" "$@"
