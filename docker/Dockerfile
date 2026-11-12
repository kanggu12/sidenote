# Sidenote analysis server: FastAPI + faster-whisper, and the CLIs of the cloud agents it can hand problems to (Claude Code, Codex).
# Built and run by ./sidenote (docker compose). No OCR: the pipeline is screen capture -> local model or cloud agent.
FROM python:3.10-slim-bookworm

# Lets ./sidenote up remove this project's dangling images after a rebuild, and nothing else.
LABEL org.sidenote.image="server"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
 && rm -rf /var/lib/apt/lists/*

# server/requirements-ocr.txt (the text detector) is deliberately not here. It was measured against
# the free ink walk that grows a crop to its block of writing: on the 102 recorded boxes the walk
# alone holds the whole problem on 98 and the detector adds one, for about 1.2 s of CPU on every
# crop and some 70 MB in the image. Anyone who wants it installs it into this image and sets
# SIDENOTE_CROP_SNAP=detector or SIDENOTE_GATE; note that rapidocr asks for opencv-python, which is
# built against X11 and dies here with "libxcb.so.1: cannot open shared object file", so the
# headless build has to replace it.
COPY server/requirements.txt server/requirements-audio.txt docker/constraints.txt /tmp/req/
RUN pip install -r /tmp/req/requirements.txt -r /tmp/req/requirements-audio.txt -c /tmp/req/constraints.txt \
 && rm -rf /tmp/req

# The panel's libraries and fonts, pinned and checksum-verified (docker/vendor.json): the server
# serves them, so the panel loads nothing from a CDN and its CSP allows only the server itself.
COPY docker/vendor.json docker/fetch_vendor.py /tmp/vendor/
RUN python /tmp/vendor/fetch_vendor.py /tmp/vendor/vendor.json /app/panel/vendor && rm -rf /tmp/vendor

# Claude Code CLI, the same version as this PC's own (./sidenote up passes it in), because both use
# the PC's ~/.claude login; checksum-verified against the release manifest (the official install.sh
# always fetches the latest build first). After pip, so a CLI update re-downloads only this layer.
# WITH_CLAUDE_CODE=0 leaves it out: the published images are built so, as Claude Code is Anthropic's to distribute;
# a pod then fetches it when it starts (the Helm chart), and `./sidenote up` builds the image with it on the PC.
# Each agent's build for the machine the image is built on, x64 or arm64 (a Mac with Apple silicon builds arm64), read
# from uname: an ARG TARGETARCH given a default kept that default on an arm64 builder.
ARG CLAUDE_VERSION=2.1.307
ARG WITH_CLAUDE_CODE=1
RUN set -eu; \
    [ "$WITH_CLAUDE_CODE" = 1 ] || { echo "Claude Code left out of this image"; exit 0; }; \
    case "$(uname -m)" in aarch64|arm64) plat=linux-arm64 ;; *) plat=linux-x64 ;; esac; \
    base="https://downloads.claude.ai/claude-code-releases/${CLAUDE_VERSION}"; \
    sum="$(curl -fsSL --retry 3 --retry-delay 2 "$base/manifest.json" | python -c 'import json,sys; print(json.load(sys.stdin)["platforms"][sys.argv[1]]["checksum"])' "$plat")"; \
    curl -fsSL --retry 3 --retry-delay 2 -o /usr/local/bin/claude "$base/$plat/claude"; \
    echo "$sum  /usr/local/bin/claude" | sha256sum -c -; \
    chmod 755 /usr/local/bin/claude

RUN mkdir -p /data/hf /data/logs
# Codex CLI (OpenAI), for SIDENOTE_AGENT=codex: the static Linux build npm publishes as @openai/codex@<v>-linux-x64 (or
# -linux-arm64), checked against the registry's own sha512 before it is unpacked; the pinned sum is the x64 one. ./sidenote up passes this PC's own version when
# it has Codex, so the container and the PC's ~/.codex are on the same release; otherwise this one.
ARG CODEX_VERSION=0.165.0
ARG CODEX_SHA512=FotDc7bVHwaommtsdDP8PPrH0a5IwC/t8H/LhdEcH4EBqgeYFRCtptiHcuwgvNRCLbTbOyFE/Ur6GzYCljgaSQ==
RUN set -eu; \
    case "$(uname -m)" in aarch64|arm64) plat=linux-arm64; triple=aarch64-unknown-linux-musl ;; *) plat=linux-x64; triple=x86_64-unknown-linux-musl ;; esac; \
    url="https://registry.npmjs.org/@openai/codex/-/codex-${CODEX_VERSION}-${plat}.tgz"; \
    curl -fsSL --retry 3 --retry-delay 2 -o /tmp/codex.tgz "$url"; \
    want="${CODEX_SHA512}"; \
    if [ "$CODEX_VERSION" != "0.165.0" ] || [ "$plat" != linux-x64 ]; then \
      want="$(curl -fsSL --retry 3 "https://registry.npmjs.org/@openai/codex/${CODEX_VERSION}-${plat}" \
              | python -c 'import json,sys; print(json.load(sys.stdin)["dist"]["integrity"].split("-",1)[1])')"; \
    fi; \
    got="$(python -c 'import base64,hashlib,sys; print(base64.b64encode(hashlib.sha512(open(sys.argv[1],"rb").read()).digest()).decode())' /tmp/codex.tgz)"; \
    [ "$got" = "$want" ] || { echo "codex tarball checksum mismatch"; exit 1; }; \
    mkdir -p /tmp/codex && tar -xzf /tmp/codex.tgz -C /tmp/codex; \
    install -m 755 "/tmp/codex/package/vendor/$triple/bin/codex" /usr/local/bin/codex; \
    rm -rf /tmp/codex /tmp/codex.tgz; \
    codex --version

COPY server /app/server
COPY panel /app/panel
COPY --chmod=755 docker/entrypoint.sh /app/entrypoint.sh
# The loop that starts the server again when it ends by itself (entrypoint.sh runs it)
COPY --chmod=755 docker/keep-running.sh /app/keep-running.sh

WORKDIR /app
# Inside the container the server listens on all interfaces; compose publishes it on the host's
# 127.0.0.1 only. ./sidenote runs it as the PC's user, who owns the ~/.claude it signs in with (SIDENOTE_UID in
# compose.yaml); by default, and on a PC whose user is root, it is root of the container with no capabilities but
# CHOWN. A read-only root filesystem either way, and nothing in the image is writable or private: any uid can run it.
ENV HOME=/root \
    SIDENOTE_HOST=0.0.0.0 \
    SIDENOTE_PORT=8777 \
    SIDENOTE_WHERE=container \
    HF_HOME=/data/hf \
    SIDENOTE_LOG_DIR=/data/logs
EXPOSE 8777
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8777/health', timeout=4)"
ENTRYPOINT ["/app/entrypoint.sh"]
