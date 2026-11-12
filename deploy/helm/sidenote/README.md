# Sidenote Helm chart

This chart runs on Kubernetes the stack that the repository's `compose.yaml` runs, with the same hardening. The
capture program (`client/capture.py`, on Windows, a Mac or a Linux desktop with X11) stays on your PC and connects to the
server's WebSocket, as it does with compose.

```bash
helm install sidenote oci://ghcr.io/kanggu12/charts/sidenote \
  --namespace sidenote --create-namespace -f my-values.yaml
```

The chart published with each release pulls that release's images from `ghcr.io/kanggu12`. The chart in the
repository (`deploy/helm/sidenote`) installs the same way and takes images you build yourself ("Images" below).

Every value is described in [`values.yaml`](values.yaml). The sections below cover what has to be in place
first and what differs from compose.

## What it deploys

| Component | compose service | Kubernetes objects | Notes |
|:---|:---:|:---|:---|
| Analysis server and panel | `server` | Deployment, Service (ClusterIP, port 8777), PersistentVolumeClaim, NetworkPolicy | Image built from `docker/Dockerfile`. One replica |
| Code runner | `runner` | Deployment, Service (port 8000), NetworkPolicy, Secret (its token) | Image built from `runner/Dockerfile`. No network at all; see "Code runner isolation" |
| Local model | `llm` | Deployment, Service (port 11434), PersistentVolumeClaim, NetworkPolicy | `ollama/ollama:0.40.5`, on an NVIDIA or AMD GPU (`llm.gpuVendor`). `llm.enabled` |
| Model download | `llm-pull` | Job (Helm hook), NetworkPolicy | Off until `llm.pull.enabled=true` |
| Web search | `searxng` | Deployment, Service (port 8080), ConfigMap, NetworkPolicy | `searxng/searxng:2026.10.7-6671d89be`. `search.enabled` |

The chart points the server at the other components: `SIDENOTE_RUNNER_URL=http://<release>-runner:8000/run`,
`SIDENOTE_LOCAL_URL=http://<release>-llm:11434/v1` and `SIDENOTE_SEARCH_URL=http://<release>-searxng:8080/search`.
A component that is switched off gets an empty address (no run button, no web search). With `llm.enabled=false`
and no `SIDENOTE_LOCAL_URL` of your own, the chart sets `SIDENOTE_ANALYZER=agent` so the agent solves alone.

## Requirements

- Kubernetes 1.25 or later and Helm 3.
- Nodes with x86-64 (amd64) processors for the published images, which are built for linux/amd64 only. On arm64
  nodes build the two images yourself on an arm64 machine (see Images): the Claude Code CLI the server pod downloads
  follows the node's processor.
- A network plugin that enforces NetworkPolicy, such as Calico, Cilium, or k3s with its built-in policy
  controller. flannel alone does not enforce it. Without enforcement the policies are accepted and do nothing,
  and the code runner, which runs code a model read off your screen, can reach the network.
- For the local model: the NVIDIA device plugin (or the GPU Operator), so that pods can request `nvidia.com/gpu`,
  or for `llm.gpuVendor: amd` the AMD GPU device plugin (`amd.com/gpu`, with the ROCm build of the image). Some
  clusters also need a RuntimeClass for GPU pods (`llm.runtimeClassName`, for example `nvidia` on k3s).
- The GPU's memory in `server.env`: the pod cannot read the GPU, so `SIDENOTE_LOCAL_VRAM_GB` picks the model and what
  the pull Job downloads. Without it a 24 GB GPU is assumed (`gemma4:26b`).
- A default StorageClass, or `storageClass` / `existingClaim` in the two `persistence` blocks. The models volume
  needs tens of GB (`llm.persistence.size`, 50Gi by default).
- The namespace must allow the `baseline` Pod Security level. `restricted` refuses the server and the runner:
  both run as root of their container, as in compose, and the runner adds four capabilities.

## Images

The chart from `oci://ghcr.io/kanggu12/charts/sidenote` pulls the published images,
`ghcr.io/kanggu12/sidenote` and `ghcr.io/kanggu12/sidenote-runner`, and needs nothing here. The chart in the
repository names the images by their local names (`sidenote`, `sidenote-runner`): build and push them to a
registry your cluster can pull from, and name it in your values:

```bash
version="$(sed -n 's/^appVersion: "\(.*\)"$/\1/p' deploy/helm/sidenote/Chart.yaml)"
docker build -f docker/Dockerfile -t "registry.example.com/sidenote:$version" .
docker build -f runner/Dockerfile -t "registry.example.com/sidenote-runner:$version" .
docker push "registry.example.com/sidenote:$version"
docker push "registry.example.com/sidenote-runner:$version"
```

The tag defaults to the chart's `appVersion`; set `server.image.tag` and `runner.image.tag` for another.
An image you build yourself carries the Claude Code CLI at the version of its `CLAUDE_VERSION` build argument
(`--build-arg CLAUDE_VERSION=...`); the published images carry none (`WITH_CLAUDE_CODE=0`), as Claude Code is
Anthropic's to distribute. With `agent.provider: claude-code` an init container copies the image's CLI into the
pod, or downloads release `agent.claudeCodeVersion` and checks it against that release's manifest when the image has
none. A download is kept on the server's volume (`agent/` beside `logs/`) with that checksum, so a pod started again
has the agent without downloading it. A kept copy is checked against the release's manifest whenever the manifest can be
read, and against the checksum kept beside it only when it cannot; one that no longer matches is downloaded again, and
another version replaces it. A private registry needs `imagePullSecrets`. On a single-node cluster you can instead load the images into
the node's container runtime, for k3s with `docker save -o sidenote.tar <image>` and
`sudo k3s ctr images import sidenote.tar`.

## Install

A values file for a 16 GB GPU, a Claude Code login in a Secret, and the models downloaded on install:

```yaml
# my-values.yaml
server:
  # image:                                     # only for the chart in the repository, with images you built
  #   repository: registry.example.com/sidenote
  env:
    SIDENOTE_LOCAL_VRAM_GB: "16"               # the GPU's memory: gemma4:e4b, with gemma4:e2b while it is busy
# runner:
#   image:
#     repository: registry.example.com/sidenote-runner
agent:
  provider: claude-code
  auth:
    existingSecret: sidenote-agent
llm:
  pull:
    enabled: true
```

```bash
kubectl create namespace sidenote
# create the agent's Secret here (next section)
helm install sidenote oci://ghcr.io/kanggu12/charts/sidenote \
  --namespace sidenote -f my-values.yaml --timeout 2h
```

Helm waits for the model-pull Job, and the first download is tens of GB, hence `--timeout 2h`. With
`llm.pull.enabled` left false, the install returns once the objects are created, and the models can be pulled later
with `helm upgrade ... --set llm.pull.enabled=true --timeout 2h`. A pull that stopped part way resumes where it
stopped. Until a model is on the volume, a signed-in agent solves everything.

## Agent login

The server asks a coding agent for the problems that need reasoning (`agent.provider`). Its login comes from a
Secret you create in the release's namespace and name in `agent.auth.existingSecret`.

**claude-code, from a machine where you ran `claude login`.** The login is the file `~/.claude/.credentials.json`
(on macOS Claude Code keeps it in the Keychain instead, so make the Secret on Linux or WSL, or use the token
below):

```bash
kubectl --namespace sidenote create secret generic sidenote-agent \
  --from-file=.credentials.json="$HOME/.claude/.credentials.json"
```

The chart mounts the Secret read-only at `/root/.claude`, where the CLI and the server's sign-in check read it.

**claude-code, with a long-lived token.** `claude setup-token` signs in once in a browser and prints a
long-lived token, for machines with no browser of their own. The chart passes the Secret's `CLAUDE_CODE_OAUTH_TOKEN`
key to the server as that environment variable, and `claude auth status` in the pod then reports the CLI as signed
in:

```bash
read -rs CLAUDE_TOKEN    # paste the token, then Enter; it is not echoed or kept in the shell history
kubectl --namespace sidenote create secret generic sidenote-agent \
  --from-literal=CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_TOKEN"
unset CLAUDE_TOKEN
```

**codex, from a machine where you ran `codex login`:**

```bash
kubectl --namespace sidenote create secret generic sidenote-agent \
  --from-file=auth.json="$HOME/.codex/auth.json"
```

Codex writes into its home as it works (a refreshed sign-in, its own records), so the Secret is not mounted there:
an init container (`codex-home`) copies it into `/root/.codex` in the pod's home, which lives in memory, at every
start. A refresh lasts as long as the pod; the next pod starts again from what the Secret holds.

A ChatGPT sign-in copied this way is the same login as the machine it came from, with one refresh token between
them. If the sign-in service lets a refresh token be used only once, whichever side refreshes first ends the other,
and every new pod starts from the used one in the Secret and comes up signed out. For a cluster, sign in with an
API key instead, on a machine of its own or in a separate `CODEX_HOME` so your own login is left as it is
(`codex login --with-api-key`; `codex login status` then says "API key configured"), and put that `auth.json` in
the Secret. Or keep a ChatGPT login used by the pod only.

**anthropic-api:**

```bash
read -rs ANTHROPIC_API_KEY
kubectl --namespace sidenote create secret generic sidenote-agent \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
unset ANTHROPIC_API_KEY
```

`agent.model` and `agent.effort` reach the server as `SIDENOTE_AGENT_MODEL` and `SIDENOTE_AGENT_EFFORT`, and the
provider as `SIDENOTE_AGENT`.

When you replace a Secret, the files mounted from it change in the pod within a minute or two, and the CLI reads
them the next time it starts. A key given as an environment variable (`ANTHROPIC_API_KEY`,
`CLAUDE_CODE_OAUTH_TOKEN`) is read when the pod starts: `kubectl --namespace sidenote rollout restart
deployment/sidenote-server`.

What to weigh before you do this:

- The Secret is a credential. Anyone who can read Secrets in the namespace, or exec into the server pod, can use
  the account behind it and spend its usage. Keep the namespace to yourself, limit who may read Secrets there,
  and turn on encryption of Secrets at rest if the cluster is shared.
- A copied `.credentials.json` is the same login as the machine it came from: both hold the same refresh token.
  The pod cannot write a refreshed token back into a read-only Secret, so each new CLI process in the pod
  refreshes again from the copy. Depending on how the sign-in service treats a refresh token that was used
  before, the copy can stop working, or a refresh on one side can end the session on the other. A token from
  `claude setup-token` is a credential of its own and needs no refresh, which suits a cluster better. Codex's
  `auth.json` is a copied login in the same way.
- With compose the CLI uses your PC's own login folder and takes Claude Code's lock there when it refreshes. In
  the cluster it has its own read-only copy and shares no lock with anything.

## Open the panel and connect the capture program

The panel has no login and shows your screen. The server accepts requests addressed to `127.0.0.1` or
`localhost` that come from its own pod: the chart sets `SIDENOTE_TRUST_GATEWAY=0`, because the pod's gateway is the
node's bridge, which anything on the node could connect from, and the chart's NetworkPolicy lets no other pod
connect to it. `kubectl port-forward` arrives inside the pod, so it works:

```bash
kubectl --namespace sidenote port-forward svc/sidenote-server 8777:8777
```

Then open `http://127.0.0.1:8777`. Keep the forward on 127.0.0.1, its default; `--address 0.0.0.0` would open the
panel to your network.

The capture program sends to `ws://127.0.0.1:8777/ingest` by default. Run the port-forward on the Windows PC, or
in WSL on that PC (Windows reaches WSL's localhost), and start the program as usual: `./sidenote capture` from
the repository in WSL (it only checks that `http://127.0.0.1:8777/health` answers), or on Windows
`py -3 client\capture.py --server ws://127.0.0.1:8777/ingest`. A port-forward ends when the pod behind it is
replaced, after an upgrade or a restart; start it again, and the capture program and the panel reconnect by
themselves.

## Code runner isolation

compose runs the code runner with `network_mode: none`, and the server reaches it through a Unix socket in a
volume the two share, which only the runner and the server's group may open. The chart keeps the runner in a Deployment of its own and lets it
listen on TCP (`RUNNER_PORT`, 8000; `runner/runner.py` does this when `RUNNER_SOCKET` is not set):

- A Unix socket needs a volume both sides mount, which works only for containers in one pod or on one node.
- A sidecar in the server's pod would share the server's network namespace: the code it runs would have the
  server's internet access, and it could reach the server's panel over loopback, which the server trusts. The
  server's peer check exists to keep the runner out.
- A NetworkPolicy gives the runner's pods no egress at all (not even DNS) and lets in only the server's pods, on
  the runner's port. The server's `SIDENOTE_RUNNER_URL` is `http://<release>-runner:8000/run`.
- `shareProcessNamespace: true` makes the pod's pause container PID 1, which reaps the processes a run leaves
  behind, as compose's `init: true` does.
- An init container sets the scratch folders' modes as compose's tmpfs options do: `/work` and `/tmp` 1777, `/out`
  0700.
- The capabilities, the read-only root filesystem, the memory-backed `/work` (256 MiB), `/tmp` (64 MiB) and `/out`
  (96 MiB), and the 2 CPU and 1 GiB limits are compose's.

**The isolation depends on a network plugin that enforces NetworkPolicy.** On a cluster without one, the
runner can open connections anywhere and any pod can send it code. Check it once after installing; both commands
should fail with a timeout:

```bash
# out of the runner: should time out
kubectl --namespace sidenote exec deploy/sidenote-runner -- \
  python3 -c "import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)"
# into the runner from a pod that is not the server: should time out
kubectl --namespace sidenote run netcheck --rm -i --restart=Never --image=busybox:1.36 -- \
  wget -qO- -T 5 http://sidenote-runner:8000/health
```

What the chart cannot reproduce:

- Kubernetes NetworkPolicy does not block traffic from a pod's own node: processes on the runner's node, including
  pods with host networking, can reach its port, and inside the runner pod a run can reach it over loopback. In
  compose only the server's container could open the socket. Here the runner takes a run only with a
  token (`RUNNER_TOKEN`, from the Secret `<release>-runner-token`, which the chart makes on the first install and
  keeps on upgrades; the server sends it as `SIDENOTE_RUNNER_TOKEN`). Keeping the token across upgrades needs Helm
  to read the Secret from the cluster. Where the chart is rendered without a cluster (`helm template`, Argo CD,
  Flux), every render makes a new token: set `runner.token`, or `runner.existingSecret` for a Secret of your own
  with a `token` key. The runner takes the token out of its environment before any run starts and is not
  dumpable, so a run cannot read it. `/health` answers without it.
- `pids_limit` and `ulimits` have no pod field. The node's kubelet sets a process limit per pod (`podPidsLimit`).
  The runner still gives every run its own process, CPU, memory, file size and core dump limits.
- An emptyDir lives as long as the pod: a runner that could not clean up after a run ends a second later (exit
  code 3) and the kubelet starts it again, and the same folders (and `/dev/shm` and the pod's IPC objects) come back
  with whatever was left. The runner cleans them up when it starts, as it does after every run. If it keeps ending
  (the pod in `CrashLoopBackOff`), delete the pod: `kubectl --namespace sidenote delete pod -l app.kubernetes.io/component=runner`.

## Several people on one cluster

Give each person a release in a namespace of their own: the agent's Secret is a credential that anyone who can read
Secrets in its namespace can use (Agent login). Two releases in one namespace still keep apart where the chart can keep
them apart. Every object's name starts with its release's, nothing is cluster-wide, and each NetworkPolicy selects its
own release's pods and lets in only its own release's server, so another release's server reaches neither this one's
runner, nor its model, nor its search. Every container asks for CPU and memory and has a limit on both, so a namespace
whose ResourceQuota asks each pod for them takes the pods; the `resources` of each part change them.
`tests/chart_check.py` checks these on what the chart writes, and `tests/k3d_check.sh` sends another release's server
at the runner on a running cluster. A release name that has `sidenote` in it is the prefix as it is, so `a` and
`a-sidenote` would both name their objects `a-sidenote-...`: Helm refuses the second of them in one namespace.

A release serves one person. One capture program feeds its server: a second one that connects takes over, and the one
before ends itself.

## Security compared with compose

| compose.yaml | This chart |
|:---|:---|
| `cap_drop: [ALL]`, `cap_add` (server CHOWN; runner SETUID, SETGID, CHOWN, KILL) | `securityContext.capabilities`, the same lists |
| `security_opt: no-new-privileges:true` | `allowPrivilegeEscalation: false` |
| Docker's default seccomp profile | `seccompProfile: RuntimeDefault` |
| `read_only: true` (server, runner, search) | `readOnlyRootFilesystem: true` (the LLM's stays writable, as in compose) |
| `tmpfs` mounts with sizes | `emptyDir` with `medium: Memory` and the same `sizeLimit` |
| tmpfs `noexec,nosuid,nodev` (Docker's defaults) | emptyDir has no mount options; `/work` is executable in both, and setuid bits have no effect without privilege escalation |
| Server published on the host's `127.0.0.1` only, Docker's gateway trusted | ClusterIP Service, a NetworkPolicy that lets no pod in, `kubectl port-forward`, and only loopback trusted (`SIDENOTE_TRUST_GATEWAY=0`) |
| Runner `network_mode: none`, Unix socket of mode 0600 | Own Deployment, TCP port, NetworkPolicy with no egress and the server as the only client, and a token for every run |
| `llmnet` (`internal: true`): the LLM reaches nothing | NetworkPolicy: only the server reaches the LLM, and the LLM reaches nothing |
| `llm-pull` on the default network | A hook Job whose NetworkPolicy allows DNS and HTTPS out, nothing in |
| `init: true` for the runner | `shareProcessNamespace: true` |
| `mem_limit`, `cpus`, `memswap_limit` | `resources.limits`; nodes run without swap unless set up for it |
| `pids_limit`, `ulimits: core: 1` | Not in a pod spec: the node's `podPidsLimit`; the server sets its own core-dump limit to 1 at start (the CLIs inherit it), and the runner gives every run none |
| GPU `count: all` | `nvidia.com/gpu: 1` or `amd.com/gpu: 1` (`llm.gpu`, `llm.gpuVendor`); with 0 on NVIDIA, `NVIDIA_VISIBLE_DEVICES=void` keeps the image's `all` from exposing every GPU |
| (no cluster API to reach) | `automountServiceAccountToken: false`, `enableServiceLinks: false` on every pod |

## No Ingress

The chart has no Ingress, because the server would refuse what comes through one. It accepts only a `Host` of
`127.0.0.1` or `localhost` (so a web page cannot reach it under a domain of its own), and only connections from its
own pod (so another container cannot drive the panel). A request through an ingress
controller carries the Ingress's host name and comes from the controller's pod. The panel also has no login and
shows your screen, the transcript of what is heard and the answers, so anything in front of it would need
authentication of its own. Use `kubectl port-forward` ("Open the panel and connect the capture program").

## Upgrade and uninstall

`helm upgrade` stops the old server and LLM pods before it starts their replacements (strategy `Recreate`, since
their volumes are ReadWriteOnce), and runs the model-pull Job again while `llm.pull.enabled` is true; with the
models in place that takes seconds.

The server's claim is 4Gi from this release on (it was 2Gi). An upgrade asks Kubernetes to grow a claim made
before, which a StorageClass without `allowVolumeExpansion: true` refuses, and the upgrade with it. There, keep the
old size: `--set server.persistence.size=2Gi`.

`helm uninstall` leaves both claims in place (`helm.sh/resource-policy: keep`): the models are tens of GB, and
the server's claim holds the logs and the panel's saved settings. Delete them yourself when you want them gone:

```bash
kubectl --namespace sidenote delete pvc sidenote-llm-models sidenote-server-data
```

## Keeping the chart in step with compose.yaml

- `files/searxng.yml` is a copy of `docker/searxng.yml` (Helm reads files from inside the chart only). After a
  change there, copy it again: `cmp docker/searxng.yml deploy/helm/sidenote/files/searxng.yml` says whether they
  differ. `search.settings` replaces the file from your values.
- The image tags in `llm.image.tag` and `search.image.tag` are compose's `SIDENOTE_OLLAMA_VERSION` and
  `SIDENOTE_SEARXNG_VERSION` defaults, and `llm.env` is the `llm` service's environment.
- The server's fixed variables (`SIDENOTE_HOST`, `SIDENOTE_PORT`, `SIDENOTE_LOG_DIR`, `OMP_*`, the CLI switches)
  are the `server` service's `environment` block.

## Checking it on a throwaway cluster

`tests/k3d_check.sh` installs the chart on a k3d cluster of its own and checks the things a render cannot: the pods
come up, port-forward reaches the panel, the runner's NetworkPolicy holds both ways (another release's server in the
namespace is kept out too), a run needs the runner's token,
a request from the node is refused, the runner cleans up after a restart, the token survives an upgrade, and
Codex's login lands in a writable home. It deletes the cluster at the end and leaves `~/.kube/config` alone; the
chart-e2e workflow runs it in CI.

```bash
./sidenote up                 # builds sidenote:local and sidenote-runner:local
tests/k3d_check.sh            # needs docker, k3d, helm and kubectl
```

## Troubleshooting

- The model-pull Job stays Pending: it runs on the LLM pod's node (a ReadWriteOnce volume is shared on one node
  only). Check that the LLM pod is scheduled, and that `llm.tolerations` include the GPU nodes' taint: the Job
  asks for no GPU, so it does not get a toleration the cluster adds to GPU pods by itself.
- `helm install` ended with "timed out waiting for the condition": the download took longer than `--timeout`. Run
  `helm upgrade --install` with the same values and a longer `--timeout`; the Job starts again and the download
  resumes.
- The panel says the code runner is down: `kubectl --namespace sidenote get pods -l
  app.kubernetes.io/component=runner`, and see the last point of "Code runner isolation".
- The panel shows the agent signed out: `kubectl --namespace sidenote exec deploy/sidenote-server --
  /opt/agent-bin/claude auth status` shows what the CLI sees.
- The panel's agent card says **Optional**, with `agent.provider: claude-code`: the server's first container could
  not download Claude Code, and the server started without it. `kubectl --namespace sidenote logs
  deploy/sidenote-server -c claude-code` shows why; the pod needs to reach downloads.claude.ai on port 443 once, as
  a copy is kept after that. Once it can, `kubectl --namespace sidenote rollout restart deploy/sidenote-server`
  downloads it again.
- SearXNG does not start on nodes without IPv6: set `search.env.GRANIAN_HOST: "0.0.0.0"`.
