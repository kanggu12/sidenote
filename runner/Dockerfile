# sidenote code runner: Python, C, C++, JavaScript, TypeScript, Java, Kotlin, Go and Bash toolchains, nothing
# else. It is network-isolated by compose and runs as a non-root user with a read-only root
# filesystem; the only writable places are the /work and /tmp tmpfs mounts.
# Debian 13 for current toolchains: Go 1.24, Node 20, g++ 14, OpenJDK 21, TypeScript 4.9 (Debian 12's Go 1.19 had
# no min or max, its Node 18 no toSorted).
FROM python:3.12-slim-trixie

# Lets ./sidenote up remove this project's dangling images after a rebuild, and nothing else.
LABEL org.sidenote.image="runner"

# gcc/g++ for C and C++, nodejs with the TypeScript compiler's module for JavaScript and TypeScript, a headless
# JDK for Java (and to run Kotlin), Go; Bash is in the base image. No recommends, caches cleaned.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ nodejs node-typescript openjdk-21-jdk-headless golang-go \
    && rm -rf /var/lib/apt/lists/*

# sortedcontainers for Python: the one package LeetCode's judge has that the standard library does not, so an
# answer written there uses SortedList without importing it (measured: 15 problems of a public corpus failed on
# that alone). Pinned and checked by hash, like the Kotlin compiler below.
ARG SORTEDCONTAINERS_VERSION=2.4.0
ARG SORTEDCONTAINERS_SHA256=a163dcaede0f1c021485e957a39245190e74249897e2ae4b2aa38595db237ee0
RUN printf 'sortedcontainers==%s --hash=sha256:%s\n' "${SORTEDCONTAINERS_VERSION}" "${SORTEDCONTAINERS_SHA256}" \
    > /tmp/req.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/req.txt \
    && rm /tmp/req.txt

# The packages LeetCode's JavaScript judge has ready, which an answer written there uses without importing
# them: a heap, a deque and lodash. They are plain JavaScript, so the tarballs are unpacked where node finds
# them from any folder (/node_modules), each checked against its sha256 as the compiler below is. The version
# is this image's choice, not that judge's, which is not published.
ARG NPM_PACKAGES="\
lodash 4.18.1 lodash 696942c2a488c9d7428e9ca5f12ccf03b52de01dcdbfe4d4751d392f0491ae16 \
@datastructures-js/priority-queue 6.4.0 priority-queue 5c567a500d1869e1de9cbe97b0d99a3731f3cc00d3c56acd25d7fb45f38a228a \
@datastructures-js/heap 4.3.7 heap d9ede1351b2ecb50cfd3cf346b2c3a455d9019b57c4512032dcb63d18e7b9b9f \
@datastructures-js/deque 1.0.8 deque fe15942ef520a6855f1f5d89b0ee42432be4877b6c412c09d2e9478b30ed452f"
COPY runner/js_packages.py /tmp/js_packages.py
RUN python3 -I /tmp/js_packages.py ${NPM_PACKAGES} \
    && rm /tmp/js_packages.py \
    && node -e "require('lodash'); require('@datastructures-js/priority-queue'); require('@datastructures-js/deque')"

# Preloaded for every JavaScript and TypeScript run, so those names are there without an import.
COPY runner/js_globals.js /app/js_globals.js

# Kotlin: Debian's is 1.3 (2019), so the compiler comes from JetBrains' release, checked against its sha256 (a
# file whose bytes differ stops the build). GitHub's download now and then answers 502 or 504, so it is asked up to
# four times, five seconds apart, and the fourth failure stops the build.
ARG KOTLIN_VERSION=2.0.21
ARG KOTLIN_SHA256=0352c0a45bd22f80f6b26e485cd04da8047baa5de54865281fb9f89a4a7bcf2a
RUN for n in 1 2 3 4; do \
      python3 -c "import hashlib, io, urllib.request, zipfile; \
d = urllib.request.urlopen('https://github.com/JetBrains/kotlin/releases/download/v${KOTLIN_VERSION}/kotlin-compiler-${KOTLIN_VERSION}.zip', timeout=300).read(); \
assert hashlib.sha256(d).hexdigest() == '${KOTLIN_SHA256}', 'kotlin compiler: checksum differs'; \
zipfile.ZipFile(io.BytesIO(d)).extractall('/opt')" && break; \
      [ "$n" = 4 ] && exit 1; sleep 5; \
    done \
    && chmod 755 /opt/kotlinc/bin/* \
    && ln -s /opt/kotlinc/bin/kotlinc /usr/local/bin/kotlinc

# The Go build cache every Go compile starts from (a copy of it, so no run can change another's): the standard
# packages compiled once here, with the settings a run's compile has.
COPY runner/go_warm.go /tmp/gowarm/main.go
RUN cd /tmp/gowarm && GOCACHE=/opt/gocache GOPATH=/tmp/gowarm/gopath GOFLAGS=-buildvcs=false GOTOOLCHAIN=local \
        go build -o /dev/null main.go \
    && rm -rf /tmp/gowarm && chmod -R a+rX /opt/gocache

# The users every compile and every run of an input is started as, one after another (RUN_UIDS in runner.py),
# each with a group of its own and no home. /work, /tmp and /out are tmpfs mounts made by compose.
RUN for u in $(seq 10100 10131); do \
        groupadd --gid "$u" "run$u" && useradd --uid "$u" --gid "$u" -M --home-dir /nonexistent \
            --shell /usr/sbin/nologin "run$u" || exit 1; \
    done \
    && mkdir -p /work /out

COPY runner/runner.py runner/ts_strip.js /app/

# The runner itself is root of the container, with only the capabilities compose grants it (SETUID, SETGID,
# CHOWN, KILL): it starts the runs as the users above, which can neither signal nor read it.
WORKDIR /
# The server asks /health too (and tells the panel when the runner is down); this makes
# `docker ps` show it as well.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=2 \
    CMD ["python3", "-I", "/app/runner.py", "--health"]
CMD ["python3", "-I", "/app/runner.py"]
