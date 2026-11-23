#!/usr/bin/env bash
# kind-up.sh — provision a 3-node kind cluster for the WSL2 / Docker provider.
# Nodes: 1 control-plane + 2 workers (weave CNI, same as the Multipass lab).
# Writes ~/.cka-arena/kubeconfig (context "cka") and ~/.cka-arena/nodes.json.
set -euo pipefail

CLUSTER="cka"
CKA_DIR="${CKA_DIR:-$HOME/.cka-arena}"
export PATH="$HOME/.local/bin:$PATH"
LOG="${CKA_SETUP_LOG:-$CKA_DIR/setup.log}"
WEAVE_YAML="${WEAVE_YAML:-https://github.com/weaveworks/weave/releases/download/v2.8.1/weave-daemonset-k8s.yaml}"

mkdir -p "$CKA_DIR"
say() { echo "[kind-up] $*" | tee -a "$LOG" >/dev/null; }
die() { say "ERROR: $*"; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker daemon is not reachable (start it: sudo systemctl start docker)"
command -v kind >/dev/null || die "kind not found (install: https://kind.sigs.k8s.io)"
command -v kubectl >/dev/null || die "kubectl not found"

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  say "kind cluster '$CLUSTER' already exists"
else
  say "creating kind cluster '$CLUSTER' (3 nodes)…"
  kind create cluster --name "$CLUSTER" --wait 180s --config - <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  kubeProxyMode: iptables
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF
fi

say "exporting kubeconfig…"
kind export kubeconfig --name "$CLUSTER" --kubeconfig "$CKA_DIR/kubeconfig"
if ! kubectl --kubeconfig "$CKA_DIR/kubeconfig" config get-contexts cka >/dev/null 2>&1; then
  kubectl --kubeconfig "$CKA_DIR/kubeconfig" config rename-context "kind-$CLUSTER" cka
fi
kubectl --kubeconfig "$CKA_DIR/kubeconfig" config use-context cka >/dev/null

say "installing CNI (weave)…"
if kubectl --kubeconfig "$CKA_DIR/kubeconfig" get daemonset -n kube-system weave-net >/dev/null 2>&1; then
  say "weave already present"
elif ! kubectl --kubeconfig "$CKA_DIR/kubeconfig" apply -f "$WEAVE_YAML" >>"$LOG" 2>&1; then
  say "WARNING: weave install failed — falling back to Calico (also enforces NetworkPolicy)"
  kubectl --kubeconfig "$CKA_DIR/kubeconfig" apply -f \
    "https://raw.githubusercontent.com/projectcalico/calico/v3.28.2/manifests/calico.yaml" >>"$LOG" 2>&1 \
    || die "CNI installation failed (weave and calico) — see $LOG"
fi

say "waiting for nodes Ready (up to 5 min)…"
for _ in $(seq 1 60); do
  ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | grep -c " Ready " || true)
  [ "${ready:-0}" -ge 3 ] && break
  sleep 5
done
ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | grep -c " Ready " || true)
[ "${ready:-0}" -ge 3 ] || die "only ${ready}/3 nodes became Ready"

say "writing node mapping (logical names → kind containers)…"
kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes -o json > "$CKA_DIR/nodes.raw.json"
python3 - "$CKA_DIR/nodes.raw.json" "$CKA_DIR/nodes.json" <<'PY'
import json, sys

raw = json.load(open(sys.argv[1]))
names = [item["metadata"]["name"] for item in raw.get("items", [])]
control = next((n for n in names if "control-plane" in n), names[0] if names else "")
workers = sorted(n for n in names if n != control)
mapping = {}
if control:
    mapping["controlplane"] = {"container": control, "node": control}
for index, worker in enumerate(workers[:2], start=1):
    mapping[f"node0{index}"] = {"container": worker, "node": worker}
json.dump(mapping, open(sys.argv[2], "w"), indent=2)
print("mapping:", mapping)
PY

kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes
say "kind lab ready (kubeconfig: $CKA_DIR/kubeconfig)"
