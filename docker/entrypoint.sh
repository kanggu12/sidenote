#!/bin/sh
# The claude CLI in the container signs in with this PC's own Claude Code login: the host's ~/.claude
# is mounted at /root/.claude (compose.yaml). Older images ran as uid 10001; folders they
# left behind are handed back to root, the owner of everything else here and on the host.
set -e
export HOME=/root
for d in /data/hf "${SIDENOTE_LOG_DIR:-}"; do
    if [ -n "$d" ] && [ -d "$d" ] && [ "$(stat -c %u "$d")" != 0 ]; then
        chown -R 0:0 "$d" 2>/dev/null || true
    fi
done
# No per-request access log: the healthcheck alone would add a line every 10 s.
# A 3840x2160 frame of a photo-like screen (a game, a video) can be over 16 MiB as the message that carries it
# (one of random pixels: 23.7 MiB of PNG, 31.7 MiB of message). uvicorn's default limit of 16 MiB closes the
# connection on such a message (code 1009) and the frame is lost; in one run the connection dropped right after
# two of the first frames from this PC's 4K monitor, which fits that.
exec uvicorn server.app:app --host "${SIDENOTE_HOST:-0.0.0.0}" --port "${SIDENOTE_PORT:-8777}" --no-access-log \
    --ws-max-size 67108864
