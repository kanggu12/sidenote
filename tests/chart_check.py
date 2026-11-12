"""The Helm chart rendered for two people sharing a cluster: two releases in one namespace, every part switched on. What
a shared cluster asks of each, checked on what `helm template` writes, with no cluster:

- no two objects share a kind and a name, and none is cluster-wide: a second release installs beside the first;
- every NetworkPolicy selects its own release's pods; each rule that lets something in names its peers, and they are
  its own release's pods; out, a rule with no peers is DNS alone, and addresses (the internet, for the model's pull)
  go out only: the other release's server reaches neither this one's runner, nor its model, nor its search;
- every container, init containers too, asks for CPU and memory and has a limit on both, with every part on and with
  Codex's login from a Secret of one's own (the init container that copies it): a namespace whose quota asks every pod
  for its limits (a shared cluster's often does) refuses a pod without them;
- no pod is given a token for the cluster's API.

    python3 tests/chart_check.py        (helm on the PATH, and PyYAML)

The CI's chart job runs it. That the policies hold on a running cluster is tests/k3d_check.sh's to show.
"""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
CHART = ROOT / "deploy" / "helm" / "sidenote"
NAMESPACED = {"ConfigMap", "Deployment", "Job", "NetworkPolicy", "PersistentVolumeClaim", "Secret", "Service",
              "ServiceAccount", "Role", "RoleBinding", "StatefulSet", "DaemonSet", "CronJob", "Ingress",
              "PodDisruptionBudget", "HorizontalPodAutoscaler"}
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail != "" and not ok else ""), flush=True)


INSTANCE = "app.kubernetes.io/instance"
# Value sets that between them render every container: every part on (the model's pull too), and Codex's login from a
# Secret of one's own, which adds the init container that copies it into a writable home
SETS = {"every part": ["llm.pull.enabled=true"],
        "Codex's login from a Secret": ["llm.pull.enabled=true", "agent.provider=codex", "agent.auth.existingSecret=codex-login"]}


def render(release: str, values=SETS["every part"]) -> list[dict]:
    """The chart as one release writes it, in the namespace both share."""
    sets = [x for v in values for x in ("--set", v)]
    out = subprocess.run(["helm", "template", release, str(CHART), "--namespace", "shared", *sets],
                         capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def pods(doc: dict) -> dict | None:
    """The pod spec a workload makes, or None for what makes no pod."""
    spec = doc.get("spec") or {}
    if doc["kind"] in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
        return spec["template"]["spec"]
    if doc["kind"] == "CronJob":
        return spec["jobTemplate"]["spec"]["template"]["spec"]
    return None


alpha, beta = render("alpha"), render("beta")
print("[two releases in one namespace]")
names = [(d["kind"], d["metadata"]["name"]) for d in alpha + beta]
check(f"no two objects share a kind and a name ({len(names)} objects)", len(set(names)) == len(names),
      sorted({n for n in names if names.count(n) > 1}))
check("none is cluster-wide", all(d["kind"] in NAMESPACED for d in alpha + beta),
      sorted({d["kind"] for d in alpha + beta} - NAMESPACED))

print("\n[each release's network to itself]")
policies = [d for d in alpha if d["kind"] == "NetworkPolicy"]
check(f"each part has a policy ({len(policies)})", len(policies) >= 5, [p["metadata"]["name"] for p in policies])
loose = []
for p in policies:
    name, spec = p["metadata"]["name"], p["spec"]
    if spec["podSelector"].get("matchLabels", {}).get(INSTANCE) != "alpha":
        loose.append(f"{name}: selects pods of any release")
    for rule in spec.get("ingress") or []:
        if not rule.get("from"):   # a rule with no peers lets in every pod and every address
            loose.append(f"{name}: an ingress rule with no peers")
        for peer in rule.get("from") or []:
            if set(peer) != {"podSelector"} or peer["podSelector"].get("matchLabels", {}).get(INSTANCE) != "alpha":
                loose.append(f"{name}: lets in {peer}, which is not this release's pods")
    for rule in spec.get("egress") or []:
        if not rule.get("to"):     # no peers: anywhere, which only DNS may be
            if any(port.get("port") != 53 for port in rule.get("ports") or [{}]):
                loose.append(f"{name}: an egress rule with no peers on {rule.get('ports') or 'every port'}")
            continue
        for peer in rule["to"]:
            if "namespaceSelector" in peer:
                loose.append(f"{name}: lets out to other namespaces")
            elif "podSelector" in peer and peer["podSelector"].get("matchLabels", {}).get(INSTANCE) != "alpha":
                loose.append(f"{name}: lets out to another release's pods")
check("every policy selects its own release's pods, lets in only its own, and lets out no wider than it names",
      not loose, loose)

print("\n[what each container asks of the cluster]")
missing, tokens, seen = [], [], set()
for label, values in SETS.items():
    for d in render("alpha", values):
        spec = pods(d)
        if spec is None:
            continue
        if spec.get("automountServiceAccountToken") is not False:
            tokens.append(f"{d['metadata']['name']} ({label})")
        for c in (spec.get("initContainers") or []) + spec["containers"]:
            seen.add(f"{d['metadata']['name']}/{c['name']}")
            res = c.get("resources") or {}
            for side in ("requests", "limits"):
                for what in ("cpu", "memory"):
                    if what not in (res.get(side) or {}):
                        missing.append(f"{d['metadata']['name']}/{c['name']} ({label}): {side}.{what}")
check(f"every container ({len(seen)}, init containers too) asks for CPU and memory and has a limit on both", not missing, missing)
check("...Codex's copy of its login among them", "alpha-sidenote-server/codex-home" in seen, sorted(seen))
check("no pod is given a token for the cluster's API", not tokens, tokens)

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
