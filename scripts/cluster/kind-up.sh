#!/usr/bin/env bash
# kind-up.sh — provision a 3-node kind cluster for the WSL2 / Docker provider.
# Pulls the pinned node image via mirror.gcr.io first (bypassing Docker Hub
# anonymous-token timeouts/rate-limits) with clean DOCKER_CONFIG retry and
# docker.io fallback, configures containerd certs.d mirror inside nodes,
# installs Weave/Calico CNI + etcdctl, and writes ~/.cka-arena/{kubeconfig,nodes.json}.
set -euo pipefail

CLUSTER="cka"
CKA_DIR="${CKA_DIR:-$HOME/.cka-arena}"
export PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin"
LOG="${CKA_SETUP_LOG:-$CKA_DIR/setup.log}"
WEAVE_YAML="${WEAVE_YAML:-https://github.com/weaveworks/weave/releases/download/v2.8.1/weave-daemonset-k8s.yaml}"
CALICO_YAML="${CALICO_YAML:-https://raw.githubusercontent.com/projectcalico/calico/v3.28.2/manifests/calico.yaml}"
KIND_NODE_VER="${CKA_KIND_NODE_VER:-v1.31.2@sha256:18fbefc20a7113353c7b75b5c869d7145a6abd6269154825872dc59c1329912e}"
KIND_MIRROR_IMAGE="mirror.gcr.io/kindest/node:${KIND_NODE_VER}"
KIND_DOCKER_IMAGE="docker.io/kindest/node:${KIND_NODE_VER}"
NODE_IMAGE=""

mkdir -p "$CKA_DIR"
say() { echo "[kind-up] $*" | tee -a "$LOG" >/dev/null; }
die() { say "ERROR: $*"; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker daemon is not reachable (start it: sudo systemctl enable --now docker)"
command -v kind >/dev/null || die "kind not found (install: https://kind.sigs.k8s.io)"
command -v kubectl >/dev/null || die "kubectl not found"

_docker_pull_with_fallback() {
  local img="$1" clean_cfg
  if docker pull "$img" >>"$LOG" 2>&1; then
    return 0
  fi
  clean_cfg="$(mktemp -d)"
  if DOCKER_CONFIG="$clean_cfg" docker pull "$img" >>"$LOG" 2>&1; then
    rm -rf "$clean_cfg"
    return 0
  fi
  rm -rf "$clean_cfg"
  return 1
}

resolve_kind_node_image() {
  if [ -n "${CKA_KIND_IMAGE:-}" ]; then
    if docker image inspect "$CKA_KIND_IMAGE" >/dev/null 2>&1 || _docker_pull_with_fallback "$CKA_KIND_IMAGE"; then
      NODE_IMAGE="$CKA_KIND_IMAGE"
      say "using custom node image: $NODE_IMAGE"
      return 0
    fi
    die "failed to pull custom CKA_KIND_IMAGE='$CKA_KIND_IMAGE' — see $LOG"
  fi

  if docker image inspect "$KIND_MIRROR_IMAGE" >/dev/null 2>&1; then
    NODE_IMAGE="$KIND_MIRROR_IMAGE"
    say "using cached mirror node image: $NODE_IMAGE"
    return 0
  fi
  if docker image inspect "$KIND_DOCKER_IMAGE" >/dev/null 2>&1; then
    NODE_IMAGE="$KIND_DOCKER_IMAGE"
    say "using cached node image: $NODE_IMAGE"
    return 0
  fi

  say "pulling kind node image from mirror.gcr.io (avoids Docker Hub anonymous token errors)…"
  if _docker_pull_with_fallback "$KIND_MIRROR_IMAGE"; then
    NODE_IMAGE="$KIND_MIRROR_IMAGE"
    return 0
  fi

  say "WARNING: mirror.gcr.io pull failed — trying docker.io fallback…"
  if _docker_pull_with_fallback "$KIND_DOCKER_IMAGE"; then
    NODE_IMAGE="$KIND_DOCKER_IMAGE"
    return 0
  fi

  die "failed to pull kind node image from mirror.gcr.io or docker.io (check DNS / VPN / proxy / MTU 1350 / WSL clock, or set CKA_KIND_IMAGE) — see $LOG"
}

prepare_kind_cluster() {
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
    local ctr_count cid
    ctr_count="$(docker ps -a --filter "label=io.x-k8s.kind.cluster=${CLUSTER}" -q 2>/dev/null | wc -l | tr -d '[:space:]')"
    if [ "${ctr_count:-0}" -ge 3 ]; then
      say "kind cluster '$CLUSTER' already exists (${ctr_count} nodes)"
      while IFS= read -r cid; do
        if [ -n "$cid" ]; then docker start "$cid" >>"$LOG" 2>&1 || true; fi
      done < <(docker ps -a --filter "label=io.x-k8s.kind.cluster=${CLUSTER}" -q 2>/dev/null)
      return 0
    fi
    say "removing incomplete kind cluster '$CLUSTER' (found ${ctr_count:-0}/3 containers)…"
    kind delete cluster --name "$CLUSTER" >>"$LOG" 2>&1 || true
  fi

  resolve_kind_node_image
  mkdir -p "$CKA_DIR/certs.d/docker.io"
  cat <<'TOML' > "$CKA_DIR/certs.d/docker.io/hosts.toml"
server = "https://registry-1.docker.io"

[host."https://mirror.gcr.io"]
  capabilities = ["pull", "resolve"]
TOML

  say "creating kind cluster '$CLUSTER' (3 nodes, image: $NODE_IMAGE)…"
  kind create cluster --name "$CLUSTER" --image "$NODE_IMAGE" --wait 180s --config - <<EOF >>"$LOG" 2>&1
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  kubeProxyMode: iptables
containerdConfigPatches:
  - |-
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: "${CKA_DIR}/certs.d"
        containerPath: /etc/containerd/certs.d
  - role: worker
    extraMounts:
      - hostPath: "${CKA_DIR}/certs.d"
        containerPath: /etc/containerd/certs.d
  - role: worker
    extraMounts:
      - hostPath: "${CKA_DIR}/certs.d"
        containerPath: /etc/containerd/certs.d
EOF
}

install_etcdctl_in_controlplane() {
  local ctl_ctr arch tmp_dir url tarball etcd_ver="v3.5.16"
  ctl_ctr="${CLUSTER}-control-plane"
  if command -v jq >/dev/null 2>&1 && [ -r "$CKA_DIR/nodes.json" ]; then
    ctl_ctr="$(jq -r '.controlplane.container // "cka-control-plane"' "$CKA_DIR/nodes.json" 2>/dev/null || echo "${CLUSTER}-control-plane")"
  fi
  if docker exec "$ctl_ctr" command -v etcdctl >/dev/null 2>&1; then
    return 0
  fi
  case "$(uname -m)" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64)  arch="amd64" ;;
    *) return 0 ;;
  esac
  tmp_dir="$(mktemp -d)"
  tarball="${tmp_dir}/etcd.tar.gz"
  url="https://github.com/etcd-io/etcd/releases/download/${etcd_ver}/etcd-${etcd_ver}-linux-${arch}.tar.gz"
  say "installing etcdctl (${etcd_ver}, ${arch}) inside ${ctl_ctr}…"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsSL "$url" -o "$tarball" >>"$LOG" 2>&1; then
      rm -rf "$tmp_dir"
      say "WARNING: etcdctl download failed — etcd scenarios may need manual etcdctl"
      return 0
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -qO "$tarball" "$url" >>"$LOG" 2>&1; then
      rm -rf "$tmp_dir"
      say "WARNING: etcdctl download failed — etcd scenarios may need manual etcdctl"
      return 0
    fi
  else
    rm -rf "$tmp_dir"
    return 0
  fi
  if tar -xzf "$tarball" -C "$tmp_dir" >>"$LOG" 2>&1 && [ -f "${tmp_dir}/etcd-${etcd_ver}-linux-${arch}/etcdctl" ]; then
    docker cp "${tmp_dir}/etcd-${etcd_ver}-linux-${arch}/etcdctl" "${ctl_ctr}:/usr/bin/etcdctl" >>"$LOG" 2>&1 || true
    docker exec "$ctl_ctr" chmod +x /usr/bin/etcdctl >>"$LOG" 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}

prepare_kind_cluster

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
  kubectl --kubeconfig "$CKA_DIR/kubeconfig" apply -f "$CALICO_YAML" >>"$LOG" 2>&1 \
    || die "CNI installation failed (weave and calico) — see $LOG"
fi

say "waiting for nodes Ready (up to 5 min)…"
ready=0
for _ in $(seq 1 60); do
  ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | awk '$2=="Ready" {c++} END {print c+0}')
  [ "${ready:-0}" -ge 3 ] && break
  sleep 5
done
ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | awk '$2=="Ready" {c++} END {print c+0}')
[ "${ready:-0}" -ge 3 ] || die "only ${ready}/3 nodes became Ready"

say "writing node mapping (logical names → kind containers)…"
kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes -o json > "$CKA_DIR/nodes.raw.json"
if command -v jq >/dev/null 2>&1; then
  jq '{
    controlplane: ([.items[] | .metadata.name | select(contains("control-plane"))][0] // .items[0].metadata.name // ""),
    workers: ([.items[] | .metadata.name | select(contains("control-plane") | not)] | sort)
  } | (
    (if .controlplane != "" then {controlplane: {container: .controlplane, node: .controlplane}} else {} end)
    + (if (.workers | length) > 0 then {node01: {container: .workers[0], node: .workers[0]}} else {} end)
    + (if (.workers | length) > 1 then {node02: {container: .workers[1], node: .workers[1]}} else {} end)
  )' "$CKA_DIR/nodes.raw.json" > "$CKA_DIR/nodes.json"
else
  uv run python - "$CKA_DIR/nodes.raw.json" "$CKA_DIR/nodes.json" <<'PY'
import json, sys

with open(sys.argv[1]) as fh:
    raw = json.load(fh)
names = [item["metadata"]["name"] for item in raw.get("items", [])]
control = next((n for n in names if "control-plane" in n), names[0] if names else "")
workers = sorted(n for n in names if n != control)
mapping = {}
if control:
    mapping["controlplane"] = {"container": control, "node": control}
for index, worker in enumerate(workers[:2], start=1):
    mapping[f"node0{index}"] = {"container": worker, "node": worker}
with open(sys.argv[2], "w") as fh:
    json.dump(mapping, fh, indent=2)
print("mapping:", mapping)
PY
fi

install_etcdctl_in_controlplane

kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes
say "kind lab ready (kubeconfig: $CKA_DIR/kubeconfig)"
