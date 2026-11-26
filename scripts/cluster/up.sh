#!/usr/bin/env bash
# up.sh — provision the 3-node kubeadm lab as Multipass VMs (macOS / Linux).
# Bridge networking (the platform needs routable node IPs for SSH + checks).
# Idempotent: reuses running VMs, only provisions what is missing.
set -euo pipefail

CKA_DIR="${CKA_DIR:-$HOME/.cka-arena}"
export PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin"
LOG="${CKA_SETUP_LOG:-$CKA_DIR/setup.log}"
POD_CIDR="10.244.0.0/16"
K8S_REPO="${K8S_REPO:-v1.34}"
ETCD_VER="${ETCD_VER:-v3.5.17}"
WEAVE_YAML="${WEAVE_YAML:-https://github.com/weaveworks/weave/releases/download/v2.8.1/weave-daemonset-k8s.yaml}"
CALICO_YAML="${CALICO_YAML:-https://raw.githubusercontent.com/projectcalico/calico/v3.28.2/manifests/calico.yaml}"

mkdir -p "$CKA_DIR"
say() { echo "[cluster-up] $*" | tee -a "$LOG" >/dev/null; }
die() { say "ERROR: $*"; exit 1; }

command -v multipass >/dev/null || die "multipass not found"
command -v kubectl   >/dev/null || die "kubectl not found"

# ---------------------------------------------------------------- bridge interface
iface="${CKA_BRIDGE_IFACE:-}"
if [ -z "$iface" ] || [ "$iface" = "auto" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    iface=$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')
  else
    iface=$(ip route 2>/dev/null | awk '$1=="default" {print $5; exit}')
  fi
fi
[ -n "$iface" ] || die "could not detect the bridged network interface (pass --bridge <iface>)"
say "bridged network interface: $iface"

# ---------------------------------------------------------------- cloud-init (base packages)
base_cloud_init() {
  cat <<EOF
#cloud-config
hostname: \$HOSTNAME_PLACEHOLDER
manage_etc_hosts: true
ssh_pwauth: true
chpasswd:
  expire: false
  list: |
    ubuntu:ubuntu
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
package_update: true
packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - jq
  - vim
  - etcd-client
  - containerd
  - conntrack
  - socat
write_files:
  - path: /etc/modules-load.d/k8s.conf
    content: |
      overlay
      br_netfilter
  - path: /etc/sysctl.d/k8s.conf
    content: |
      net.bridge.bridge-nf-call-iptables = 1
      net.bridge.bridge-nf-call-ip6tables = 1
      net.ipv4.ip_forward = 1
  - path: /etc/containerd/certs.d/docker.io/hosts.toml
    content: |
      server = "https://registry-1.docker.io"
      [host."https://mirror.gcr.io"]
        capabilities = ["pull", "resolve"]
  - path: /etc/containerd/config.toml
    content: |
      version = 2
      [plugins."io.containerd.grpc.v1.cri".registry]
        config_path = "/etc/containerd/certs.d"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
        SystemdCgroup = true
runcmd:
  - modprobe overlay
  - modprobe br_netfilter
  - sysctl --system
  - systemctl restart containerd
  - systemctl enable containerd
  - curl -fsSL https://pkgs.k8s.io/core:/stable:/${K8S_REPO}/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
  - echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_REPO}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list
  - apt-get update
  - apt-get install -y kubelet kubeadm kubectl
  - apt-mark hold kubelet kubeadm kubectl
  - swapoff -a
  - sed -ri '/\sswap\s/s/^#?/#/' /etc/fstab
  - |
    if ! command -v etcdutl >/dev/null 2>&1; then
      ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && E_ARCH="arm64" || E_ARCH="amd64"
      curl -fsSL "https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-${E_ARCH}.tar.gz" -o /tmp/etcd.tgz && tar -xzf /tmp/etcd.tgz -C /tmp && install -m 0755 "/tmp/etcd-${ETCD_VER}-linux-${E_ARCH}/etcdutl" /usr/local/bin/etcdutl && rm -rf /tmp/etcd.tgz "/tmp/etcd-${ETCD_VER}-linux-${E_ARCH}" || true
    fi
  - touch /var/lib/cloud/instance/boot-finished
EOF
}

# launch_vm <name>
launch_vm() {
  local name="$1" userdata
  if multipass info "$name" >/dev/null 2>&1; then
    say "$name already exists"
    multipass start "$name" >/dev/null 2>&1 || true
    return 0
  fi
  userdata="$(mktemp)"
  base_cloud_init | sed "s/\\\$HOSTNAME_PLACEHOLDER/$name/" > "$userdata"
  say "launching $name (2 CPU / 3 GB / 12 GB disk)…"
  multipass launch jammy --name "$name" --cpus 2 --memory 3G --disk 12G \
    --network "$iface" --cloud-init "$userdata" >>"$LOG" 2>&1 \
    || die "multipass launch failed for $name (see $LOG)"
  rm -f "$userdata"
  say "$name launched"
}

vm_ip() {
  local name="$1" ip
  for _ in $(seq 1 60); do
    ip=$(multipass info "$name" --format csv 2>/dev/null | awk -F, 'NR==2 {print $3}' | tr -d ' ')
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi
    sleep 3
  done
  return 1
}

wait_cloud_init() {
  local name="$1"
  say "waiting for cloud-init on $name (packages install)…"
  for _ in $(seq 1 100); do
    if multipass exec "$name" -- sudo test -f /var/lib/cloud/instance/boot-finished >/dev/null 2>&1; then
      return 0
    fi
    sleep 6
  done
  die "cloud-init did not finish on $name"
}

launch_vm controlplane
wait_cloud_init controlplane
launch_vm node01
launch_vm node02

ctl_ip="$(vm_ip controlplane)" || die "controlplane has no IP"
say "controlplane IP: $ctl_ip"

# ---------------------------------------------------------------- kubeadm init
if ! multipass exec controlplane -- sudo test -f /etc/kubernetes/admin.conf >/dev/null 2>&1; then
  say "kubeadm init on controlplane…"
  multipass exec controlplane -- sudo kubeadm init \
    --apiserver-advertise-address="$ctl_ip" \
    --pod-network-cidr="$POD_CIDR" >>"$LOG" 2>&1 \
    || die "kubeadm init failed (see $LOG)"
else
  say "controlplane already initialized"
fi

say "exporting kubeconfig…"
multipass exec controlplane -- sudo cat /etc/kubernetes/admin.conf > "$CKA_DIR/kubeconfig"
kubectl --kubeconfig "$CKA_DIR/kubeconfig" config rename-context kubernetes-admin@kubernetes cka >/dev/null 2>&1 || true
kubectl --kubeconfig "$CKA_DIR/kubeconfig" config use-context cka >/dev/null

# ---------------------------------------------------------------- workers join
join_cmd="$(multipass exec controlplane -- sudo kubeadm token create --print-join-command)"
wait_cloud_init node01
wait_cloud_init node02
for worker in node01 node02; do
  if kubectl --kubeconfig "$CKA_DIR/kubeconfig" get node "$worker" >/dev/null 2>&1; then
    say "$worker already joined"
    continue
  fi
  say "$worker joining…"
  multipass exec "$worker" -- sudo bash -c "$join_cmd" >>"$LOG" 2>&1 \
    || die "$worker failed to join (see $LOG)"
done

# ---------------------------------------------------------------- CNI
if kubectl --kubeconfig "$CKA_DIR/kubeconfig" get daemonset -n kube-system weave-net >/dev/null 2>&1; then
  say "weave already installed"
elif ! kubectl --kubeconfig "$CKA_DIR/kubeconfig" apply -f "$WEAVE_YAML" >>"$LOG" 2>&1; then
  say "WARNING: weave install failed — falling back to Calico (also enforces NetworkPolicy)"
  kubectl --kubeconfig "$CKA_DIR/kubeconfig" apply -f "$CALICO_YAML" >>"$LOG" 2>&1 \
    || die "CNI installation failed (weave and calico) — see $LOG"
fi

say "waiting for 3 nodes Ready (up to 5 min)…"
ready=0
for _ in $(seq 1 60); do
  ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | awk '$2=="Ready" {c++} END {print c+0}')
  [ "${ready:-0}" -ge 3 ] && break
  sleep 5
done
ready=$(kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes --no-headers 2>/dev/null | awk '$2=="Ready" {c++} END {print c+0}')
[ "${ready:-0}" -ge 3 ] || die "only ${ready}/3 nodes became Ready"

cat <<'EOF' > "$CKA_DIR/nodes.json"
{
  "controlplane": {"container": null, "node": "controlplane"},
  "node01": {"container": null, "node": "node01"},
  "node02": {"container": null, "node": "node02"}
}
EOF

kubectl --kubeconfig "$CKA_DIR/kubeconfig" get nodes
say "multipass lab ready (kubeconfig: $CKA_DIR/kubeconfig)"
