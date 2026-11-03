#!/usr/bin/env bash
# The Helm chart on a throwaway k3d cluster: what only a running cluster can show. The pods come up, port-forward
# reaches the panel, the runner reaches nothing and only the server reaches it, a run needs the runner's token (also
# from inside the runner pod), a request from the node is refused (loopback only), the runner cleans up what a run
# left when its container restarts, the token survives an upgrade, and Codex's login is copied into a writable home.
# The cluster and its kubeconfig are removed at the end whatever happens; ~/.kube/config is never touched.
#
#   tests/k3d_check.sh [server image] [runner image]      (default sidenote:local sidenote-runner:local)
#
# K3D_CHECK_WAIT is how long helm waits for the pods (15m), K3D_CHECK_HELM_ARGS adds install arguments, and
# K3D_CHECK_PORT is the port-forward's local port (18777). A failed install prints why the pods are not running.
#
# Needs docker, k3d, helm and kubectl (K3D, HELM, KUBECTL name other binaries), and pulls the k3s image once. The
# local model and web search stay off, so no GPU is used; the speech model is not downloaded (SIDENOTE_TRANSCRIBER).
set -uo pipefail
K3D=${K3D:-k3d}
HELM=${HELM:-helm}
KUBECTL=${KUBECTL:-kubectl}
REPO="$(cd "$(dirname "$0")/.." && pwd)"              # the repository: this file is in tests/
WORK="${SIDENOTE_TEST_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/sidenote-k3d.XXXXXX")}"   # logs and the kubeconfig
mkdir -p "$WORK"
SP="$WORK"                                            # where the logs below go
NAME="sidenote-k3d-$$"                                # a cluster of this run's own
NS=sidenote
PORT=${K3D_CHECK_PORT:-18777}                         # the port-forward's local port, away from compose's 8777
WAIT=${K3D_CHECK_WAIT:-15m}                           # how long helm waits for the pods
read -r -a EXTRA <<< "${K3D_CHECK_HELM_ARGS:-}"       # more helm install arguments (a check of this check sets some)
export KUBECONFIG="$WORK/kubeconfig"                  # this cluster's alone
SERVER_IMG=${1:-sidenote:local}
RUNNER_IMG=${2:-sidenote-runner:local}
for tool in docker "$K3D" "$HELM" "$KUBECTL"; do
  command -v "$tool" > /dev/null || { echo "tests/k3d_check.sh: $tool is not installed" >&2; exit 2; }
done
PF_PID=""
cleanup() {
  [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null
  "$K3D" cluster delete "$NAME" > /dev/null 2>&1
  rm -f "$KUBECONFIG"
  echo "cluster $NAME deleted (logs in $WORK)"
}
trap cleanup EXIT
PASS=0
FAIL=0
check() {   # check <name> <command...>: the command's success is the check
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "  ok $name"; PASS=$((PASS + 1)); else echo "  FAIL $name"; FAIL=$((FAIL + 1)); fi
}
kc() { "$KUBECTL" --namespace "$NS" "$@"; }
diagnose() {   # what a failed install leaves to read: where the pods are, why they are not running, the node's state
  echo "  -- pods"; kc get pods -o wide 2>&1 | sed 's/^/     /'
  echo "  -- events"; kc get events --sort-by=.lastTimestamp 2>&1 | tail -25 | sed 's/^/     /'
  echo "  -- node"; "$KUBECTL" describe nodes 2>&1 | grep -E -A 8 "^(Taints|Conditions):" | sed 's/^/     /'
  echo "  -- disk"; df -h / 2>&1 | sed 's/^/     /'
}

echo "[cluster]"
"$K3D" cluster create "$NAME" --kubeconfig-update-default=false --kubeconfig-switch-context=false --no-lb \
  --k3s-arg "--disable=traefik@server:0" --k3s-arg "--disable=metrics-server@server:0" \
  --k3s-arg "--kubelet-arg=eviction-hard=imagefs.available<1%,nodefs.available<1%@server:0" \
  --k3s-arg "--kubelet-arg=eviction-minimum-reclaim=imagefs.available=1%,nodefs.available=1%@server:0" \
  --wait --timeout 300s \
  > "$SP/k3d_create.log" 2>&1 || { echo "cluster create failed: $(tail -3 "$SP/k3d_create.log")"; exit 1; }
"$K3D" kubeconfig write "$NAME" --output "$KUBECONFIG" > /dev/null
"$K3D" image import -c "$NAME" "$SERVER_IMG" "$RUNNER_IMG" > "$SP/k3d_import.log" 2>&1 || { echo "image import failed"; exit 1; }
"$KUBECTL" get nodes --no-headers | sed 's/^/  /'

echo "[install]"
set_images=(--set "server.image.repository=${SERVER_IMG%:*}" --set "server.image.tag=${SERVER_IMG##*:}"
            --set server.image.pullPolicy=Never --set "runner.image.repository=${RUNNER_IMG%:*}"
            --set "runner.image.tag=${RUNNER_IMG##*:}" --set runner.image.pullPolicy=Never)
"$HELM" install sidenote "$REPO/deploy/helm/sidenote" --namespace "$NS" --create-namespace "${set_images[@]}" \
  --set llm.enabled=false --set search.enabled=false --set-string server.env.SIDENOTE_TRANSCRIBER=null \
  "${EXTRA[@]}" --wait --timeout "$WAIT" > "$SP/k3d_install.log" 2>&1
check "helm install, every pod ready" grep -q "STATUS: deployed" "$SP/k3d_install.log"
kc get pods --no-headers | sed 's/^/  /'
if [ "$FAIL" -gt 0 ]; then
  tail -5 "$SP/k3d_install.log" | sed 's/^/  helm: /'
  diagnose
  echo "==== $PASS passed, $FAIL failed (stopped: nothing else can be checked without the pods) ===="
  exit 1
fi

echo "[the panel through port-forward, on loopback]"
kc port-forward svc/sidenote-server "$PORT:8777" > /dev/null 2>&1 &
PF_PID=$!
for _ in $(seq 30); do curl -sf -m 2 "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 1; done
check "port-forward reaches /health" curl -sf -m 5 "http://127.0.0.1:$PORT/health"

echo "[the runner's network]"
# Each probe prints what it saw: "blocked" only for a connection that timed out or was refused, so a probe that
# never ran (no pod, no image) cannot pass for a blocked one.
BLOCKED='import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5)
    print("open")
except OSError:
    print("blocked")'
OUT=$(kc exec deploy/sidenote-runner -- python3 -c "$BLOCKED" 1.1.1.1 443 2>/dev/null)
check "the runner opens no connection out" test "$OUT" = blocked
kc run netcheck --image="$SERVER_IMG" --image-pull-policy=Never --restart=Never --command -- \
  python3 -c "$BLOCKED" sidenote-runner 8000 > /dev/null 2>&1
kc wait --for=jsonpath='{.status.phase}'=Succeeded pod/netcheck --timeout=90s > /dev/null 2>&1
check "a pod that is not the server cannot reach the runner" test "$(kc logs netcheck 2>/dev/null)" = blocked
kc delete pod netcheck --wait=false > /dev/null 2>&1

echo "[the runner's token]"
PROBE='import json, os, sys, urllib.request, urllib.error
def post(body, token):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request("http://sidenote-runner:8000/run", json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
want = sys.argv[1]
tok = os.environ.get("SIDENOTE_RUNNER_TOKEN", "")
if want == "none":
    sys.exit(0 if post({"lang": "python", "code": "print(1)"}, "")[0] == 403 else 1)
if want == "token":
    s, r = post({"lang": "python", "code": "print(6 * 7)"}, tok)
    sys.exit(0 if s == 200 and r.get("ok") and r.get("stdout", "").strip() == "42" else 1)
if want == "inside":
    code = ("import urllib.request, urllib.error\n"
            "try:\n"
            "    urllib.request.urlopen(urllib.request.Request(\"http://127.0.0.1:8000/run\", b\"{}\"), timeout=5)\n"
            "    print(\"open\")\n"
            "except urllib.error.HTTPError as e:\n"
            "    print(e.code)\n")
    s, r = post({"lang": "python", "code": code}, tok)
    sys.exit(0 if s == 200 and r.get("stdout", "").strip() == "403" else 1)'
check "a run with no token is refused" kc exec deploy/sidenote-server -- python3 -c "$PROBE" none
check "the server's token runs code (6 * 7 = 42), as a run user in the sealed runner" \
  kc exec deploy/sidenote-server -- python3 -c "$PROBE" token
check "a run inside the runner pod that asks the runner itself is refused (403)" \
  kc exec deploy/sidenote-server -- python3 -c "$PROBE" inside

echo "[the server trusts loopback only]"
POD_IP=$(kc get pod -l app.kubernetes.io/component=server -o jsonpath='{.items[0].status.podIP}')
kc run nodecheck --image="$SERVER_IMG" --image-pull-policy=Never --restart=Never \
  --overrides='{"spec": {"hostNetwork": true}}' --command -- python3 -c "
import urllib.request, urllib.error, sys
req = urllib.request.Request('http://$POD_IP:8777/health', headers={'Host': '127.0.0.1'})
try:
    urllib.request.urlopen(req, timeout=5); print('open'); sys.exit(1)
except urllib.error.HTTPError as e:
    print(e.code); sys.exit(0 if e.code == 403 else 1)" > /dev/null 2>&1
kc wait --for=jsonpath='{.status.phase}'=Succeeded pod/nodecheck --timeout=90s > /dev/null 2>&1
check "a request from the node (host network, through the pod's gateway) is refused with 403" \
  test "$(kc get pod nodecheck -o jsonpath='{.status.phase}')" = Succeeded
kc logs nodecheck 2>/dev/null | sed 's/^/    node got: /'
kc delete pod nodecheck --wait=false > /dev/null 2>&1

echo "[the runner cleans up when its container restarts]"
RPOD=$(kc get pod -l app.kubernetes.io/component=runner -o jsonpath='{.items[0].metadata.name}')
BEFORE=$(kc get pod "$RPOD" -o jsonpath='{.status.containerStatuses[0].restartCount}')
check "a file of a run user's is left in /work" \
  kc exec "$RPOD" -- sh -c 'echo left > /work/leftover && chown 10100:10100 /work/leftover && [ "$(stat -c %u /work/leftover)" = 10100 ]'
kc exec "$RPOD" -- python3 -c "
import os, signal
for p in os.listdir('/proc'):
    if p.isdigit():
        try:
            cmd = open('/proc/%s/cmdline' % p, 'rb').read().split(b'\0')
        except OSError:
            continue
        if any(c.endswith(b'runner.py') for c in cmd) and not any(c.startswith(b'--') for c in cmd):
            os.kill(int(p), signal.SIGKILL)" > /dev/null 2>&1
for _ in $(seq 60); do
  [ "$(kc get pod "$RPOD" -o jsonpath='{.status.containerStatuses[0].restartCount}')" != "$BEFORE" ] && \
  [ "$(kc get pod "$RPOD" -o jsonpath='{.status.containerStatuses[0].ready}')" = true ] && break
  sleep 2
done
check "the runner container restarted in the same pod" \
  test "$(kc get pod "$RPOD" -o jsonpath='{.status.containerStatuses[0].restartCount}')" != "$BEFORE"
OUT=$(kc exec "$RPOD" -- sh -c 'test -e /work/leftover && echo present || echo gone' 2>/dev/null)
check "...and the file a run user left in /work is gone" test "$OUT" = gone
check "...and it is healthy" kc exec "$RPOD" -- python3 /app/runner.py --health

echo "[upgrade: the token kept, Codex's login copied into a writable home]"
TOKEN_BEFORE=$(kc get secret sidenote-runner-token -o jsonpath='{.data.token}')
kc create secret generic sidenote-agent --from-literal=auth.json='{"stand-in": true}' > /dev/null
"$HELM" upgrade sidenote "$REPO/deploy/helm/sidenote" --namespace "$NS" --reuse-values \
  --set agent.provider=codex --set agent.auth.existingSecret=sidenote-agent --wait --timeout 10m \
  > "$SP/k3d_upgrade.log" 2>&1
check "helm upgrade to Codex, every pod ready" grep -q "STATUS: deployed" "$SP/k3d_upgrade.log"
check "the runner's token is the same after the upgrade" \
  test -n "$TOKEN_BEFORE" -a "$(kc get secret sidenote-runner-token -o jsonpath='{.data.token}')" = "$TOKEN_BEFORE"
check "Codex's login is in its home, and the home is writable" kc exec deploy/sidenote-server -- \
  sh -c 'test -s /root/.codex/auth.json && touch /root/.codex/written && ls -ld /root/.codex | grep -q "^drwx------"'
check "the server's runs still work after the upgrade" kc exec deploy/sidenote-server -- python3 -c "$PROBE" token

echo
echo "==== $PASS passed, $FAIL failed ===="
exit $((FAIL > 0))
