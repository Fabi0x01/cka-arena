"""CKA Study Codex v2 — Domain 1: Cluster Architecture, Installation & Configuration (Topics 1–9)."""

from __future__ import annotations

from app.study.models import (
    CheatItem,
    ComparisonRow,
    DebugRow,
    PracticeStep,
    RecallQuiz,
    StudyDocLink,
    StudyTopic,
)

DOMAIN = "Cluster Architecture, Installation & Configuration"

ARCH_TOPICS: tuple[StudyTopic, ...] = (
    StudyTopic(
        id="ca-rbac-foundations",
        order=1,
        domain=DOMAIN,
        title="RBAC: ServiceAccounts, Roles & ClusterRoles",
        subtitle="Enforce least-privilege API access for Pods, Users, and Groups cleanly.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-rbac-least-priv", "ca-rolebinding-subject", "ca-clusterrole-sa"),
        summary=(
            "Kubernetes authorization is strictly additive and deny-by-default after authentication. "
            "Namespace-scoped rules pair a `Role` with a `RoleBinding`, while cluster-wide resources (`nodes`, `pv`, "
            "`clusterroles`) or cross-namespace access use a `ClusterRole` paired with a `ClusterRoleBinding` — or a "
            "`RoleBinding` referencing a `ClusterRole` to stamp reusable rules into a single namespace."
        ),
        architecture_flow=(
            "Request -> AuthN (Cert/SA Token) -> RBAC Evaluator (RoleBinding -> Role OR ClusterRoleBinding -> ClusterRole) -> Allow | Deny"
        ),
        theory_points=(
            "Every rule needs three slices: `apiGroups` (`\"\"` for core Pods/Services/CM/Secrets, `\"apps\"` for Deployments/StatefulSets), `resources` (plural lowercase + subresources like `pods/log`, `pods/exec`), and `verbs` (`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`).",
            "`RoleBinding` -> `ClusterRole` grants ONLY the permissions within the `RoleBinding`'s `metadata.namespace`, letting teams reuse built-in roles like `view` or `edit` per namespace.",
            "`resourceNames` narrows rules to specific named objects (e.g., `[\"db-creds\"]` Secret), though `list` and `watch` cannot filter by `resourceNames` reliably on older paths — `get`/`update` works cleanly.",
            "Built-in user-facing ClusterRoles: `view` (read most), `edit` (read/write apps), `admin` (manage namespace + Roles), `cluster-admin` (super-user); labels `rbac.authorization.k8s.io/aggregate-to-edit: \"true\"` extend aggregated ClusterRoles automatically.",
            "Modern Pods automatically get bound ServiceAccount tokens via projected volumes (`/var/run/secrets/kubernetes.io/serviceaccount/token`); issue ad-hoc bound short-lived tokens with `k -n <ns> create token <sa> --duration=1h` instead of legacy long-lived Secret tokens, and set `automountServiceAccountToken: false` on sensitive Pods/SAs when API access is unnecessary.",
            "Always prove BOTH positive and negative bounds with `k auth can-i <verb> <resource> --as=system:serviceaccount:<ns>:<sa>` (and `User` / `--as-group` for X.509 users).",
        ),
        decision_matrix=(
            ComparisonRow("`Role` + `RoleBinding`", "Permissions scoped strictly to one namespace", "App ServiceAccount reading Pods/Secrets in its own namespace"),
            ComparisonRow("`ClusterRole` + `RoleBinding`", "Reuses cluster template inside ONE namespace only", "Granting namespace-isolated `view`/`edit` without copying Rules"),
            ComparisonRow("`ClusterRole` + `ClusterRoleBinding`", "Grants permissions across ALL namespaces + cluster resources", "Monitoring nodes, PVs, StorageClasses, or cluster-wide watchers"),
            ComparisonRow("`kubectl auth can-i --as=...`", "Evaluates RBAC without mutating cluster state", "Checking exact allowed/denied verbs before finishing task"),
        ),
        docs_links=(
            StudyDocLink(
                label="Using RBAC Authorization",
                url="https://kubernetes.io/docs/reference/access-authn-authz/rbac/",
                exam_search_term="Using RBAC Authorization",
            ),
            StudyDocLink(
                label="Configure Service Accounts for Pods",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/",
                exam_search_term="Service Accounts for Pods",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Create the ServiceAccount and least-privilege Role",
                explanation="Use imperative `kubectl create` flags so `apiGroups`, `resources`, and `verbs` are generated accurately.",
                command="k -n app create sa inspector && k -n app create role pod-reader --verb=get,list,watch --resource=pods,pods/log",
                verify_command="k -n app get role pod-reader -o yaml",
                expected_output="rules with apiGroups: [\"\"], resources: [\"pods\", \"pods/log\"], verbs: [\"get\", \"list\", \"watch\"]",
            ),
            PracticeStep(
                title="Bind Role or ClusterRole to the ServiceAccount or User",
                explanation="Always qualify ServiceAccounts as `--serviceaccount=<ns>:<sa>`; pass `--user=<cn>` or `--group=<o>` for CSR users.",
                command="k -n app create rolebinding app-pod-reader --role=pod-reader --serviceaccount=app:inspector",
                yaml_snippet=(
                    "apiVersion: rbac.authorization.k8s.io/v1\n"
                    "kind: RoleBinding\n"
                    "metadata:\n"
                    "  name: app-pod-reader\n"
                    "  namespace: app\n"
                    "subjects:\n"
                    "- kind: ServiceAccount\n"
                    "  name: inspector\n"
                    "  namespace: app\n"
                    "roleRef:\n"
                    "  kind: Role\n"
                    "  name: pod-reader\n"
                    "  apiGroup: rbac.authorization.k8s.io"
                ),
            ),
            PracticeStep(
                title="Impersonate to verify allowed AND denied actions",
                explanation="Verify least privilege cleanly — confirm target verb returns `yes` while `delete` or cross-namespace queries return `no`.",
                command="k auth can-i list pods -n app --as=system:serviceaccount:app:inspector",
                verify_command="k auth can-i delete pods -n app --as=system:serviceaccount:app:inspector",
                expected_output="yes for list pods; no for delete pods",
            ),
        ),
        debug_playbook=(
            DebugRow("`Error from server (Forbidden)` on Deployment action", "Used `apiGroups: [\"\"]` instead of `\"apps\"` on `deployments`", "Pass `--resource=deployments.apps` in CLI or `apiGroups: [\"apps\"]` in YAML"),
            DebugRow("Binding exists yet `auth can-i` still prints `no`", "Wrong `subject.namespace` or binding swapped `kind: Role` vs `ClusterRole`", "Delete and recreate RoleBinding with exact `roleRef.kind` & subject namespace"),
            DebugRow("`roleRef: Invalid value: ... field is immutable`", "Attempted `kubectl edit rolebinding` to point to a different Role", "Export with `-o yaml > rb.yaml`, edit `roleRef.name`, run `k replace --force -f rb.yaml`"),
        ),
        exam_trap=(
            "`roleRef` on an existing RoleBinding/ClusterRoleBinding is IMMUTABLE. `kubectl edit` only succeeds when editing `subjects[]`; changing `roleRef.name` requires deleting and recreating the binding."
        ),
        cheatsheet=(
            CheatItem("Create Role fast", "k -n <ns> create role <r> --verb=get,list --resource=pods,deployments.apps", "Notice `.apps` qualifies non-core group"),
            CheatItem("Create RoleBinding", "k -n <ns> create rolebinding <rb> --role=<r> --serviceaccount=<ns>:<sa>", "Pairs SA inside namespace"),
            CheatItem("Create ClusterRole", "k create clusterrole <cr> --verb=get,list --resource=nodes,persistentvolumes", "Cluster-scoped objects"),
            CheatItem("ClusterRoleBinding", "k create clusterrolebinding <crb> --clusterrole=<cr> --serviceaccount=<ns>:<sa>", "Cluster-wide grant"),
            CheatItem("Check SA permission", "k auth can-i <verb> <res> -n <ns> --as=system:serviceaccount:<ns>:<sa>", "Returns yes or no"),
            CheatItem("Check User permission", "k auth can-i get pods -n <ns> --as=<user> --as-group=<group>", "Tests X.509 user/group RBAC"),
            CheatItem("Short-lived SA token", "k -n <ns> create token <sa> --duration=1h", "Bound projected TokenRequest token (v1.24+)"),
        ),
        yaml_template=(
            "apiVersion: rbac.authorization.k8s.io/v1\n"
            "kind: ClusterRole\n"
            "metadata:\n"
            "  name: node-reader\n"
            "rules:\n"
            "- apiGroups: [\"\"]\n"
            "  resources: [\"nodes\", \"persistentvolumes\"]\n"
            "  verbs: [\"get\", \"list\", \"watch\"]"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="You bind an existing ClusterRole named `view` using a `RoleBinding` in namespace `payments`. What scope does the ServiceAccount get?",
                choices=(
                    "Read access across all namespaces in the cluster",
                    "Read access only inside namespace `payments`",
                    "API server rejects RoleBinding referencing a ClusterRole",
                    "Cluster-scoped `nodes` read access only",
                ),
                correct_index=1,
                explanation="A `RoleBinding` restricts even a referenced `ClusterRole`'s permissions strictly to the `RoleBinding`'s `metadata.namespace`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which imperative command creates a Role in namespace `billing` granting `get,list` on Deployments without manual YAML edits?",
                choices=(
                    "k -n billing create role deploy-read --verb=get,list --resource=deployments",
                    "k -n billing create role deploy-read --verb=get,list --resource=deployments.apps",
                    "k -n billing create role deploy-read --rules=apps/deployments:get,list",
                    "k -n billing create clusterrole deploy-read --scope=apps",
                ),
                correct_index=1,
                explanation="`deployments` resolves to `apps` in newer kubectl, and qualifying `--resource=deployments.apps` guarantees `apiGroups: [\"apps\"]` safely across versions.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="After editing `spec.roleRef.name` on an existing `RoleBinding`, `kubectl apply` returns `Invalid value: ... field is immutable`. What is the fastest fix?",
                choices=(
                    "Restart `kube-apiserver`",
                    "Delete the existing `RoleBinding` and recreate it cleanly with the new `roleRef`",
                    "Add `immutable: false` to metadata",
                    "Patch `roleRef.apiGroup` to empty string first",
                ),
                correct_index=1,
                explanation="`roleRef` cannot be patched or updated on existing RoleBindings/ClusterRoleBindings; delete + apply (or `kubectl replace --force -f`) fixes it immediately.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-kubeadm-bootstrap",
        order=2,
        domain=DOMAIN,
        title="Cluster Bootstrap (`kubeadm init/join`), HA & CRI Prep",
        subtitle="Configure kernel sysctls, containerd `SystemdCgroup`, bootstrap controlplane, and join workers.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-kubeadm-node-upgrade", "ca-cert-expiry-inspect"),
        summary=(
            "`kubeadm` cluster creation follows a predictable 4-phase flow: OS/kernel preflight (disable swap, load `overlay` & `br_netfilter`, "
            "enable `ip_forward`), CRI runtime (`containerd` with `SystemdCgroup = true`), `kubeadm init --pod-network-cidr=...` + CNI install, "
            "and joining additional nodes via short-lived bootstrap tokens + CA cert hash."
        ),
        architecture_flow=(
            "Swap Off + Kernel Modules (overlay, br_netfilter, ip_forward=1) -> containerd (SystemdCgroup=true) -> kubeadm init -> Copy admin.conf -> Apply CNI -> kubeadm join"
        ),
        theory_points=(
            "Preflight requirements before `kubeadm init`: swap MUST be off (`sudo swapoff -a` + comment swap in `/etc/fstab`), kernel modules `overlay` & `br_netfilter` loaded, and sysctls `net.bridge.bridge-nf-call-iptables=1` & `net.ipv4.ip_forward=1` applied via `sysctl --system`.",
            "Mismatch between containerd's cgroup driver and kubelet causes kubelet crash loops: set `SystemdCgroup = true` in `/etc/containerd/config.toml` (generated via `containerd config default`) and restart `containerd`.",
            "`kubeadm init --pod-network-cidr=<cidr> --apiserver-advertise-address=<ip>` initializes static Pods, PKI under `/etc/kubernetes/pki`, and `/etc/kubernetes/admin.conf` (copy to `~/.kube/config` for `kubectl`).",
            "Worker nodes stay `NotReady` after `kubeadm init` UNTIL a CNI plugin (Calico, Flannel, Cilium) matching `--pod-network-cidr` is installed.",
            "`kubeadm` bootstrap tokens expire in **24 hours**; regenerate anytime on controlplane via `kubeadm token create --print-join-command` (or `--control-plane --certificate-key ...` for HA controlplanes).",
            "Stacked etcd HA co-locates etcd static Pods on each controlplane behind a load balancer (`--control-plane-endpoint`); External etcd runs dedicated etcd quorum nodes separately.",
        ),
        decision_matrix=(
            ComparisonRow("Stacked etcd HA", "Each controlplane runs `kube-apiserver` + local etcd", "Simpler ops; requires odd quorum (3/5) controlplanes behind `--control-plane-endpoint`"),
            ComparisonRow("External etcd HA", "Dedicated etcd cluster outside controlplane nodes", "Maximum isolation if controlplane crashes; doubles node footprint"),
            ComparisonRow("`SystemdCgroup = true`", "containerd & kubelet share `systemd` cgroup manager", "Mandatory on modern systemd Linux distributions (`cgroup v2`)"),
            ComparisonRow("`kubeadm join --control-plane`", "Joins node as additional HA controlplane + etcd member", "Requires `--certificate-key` uploaded via `kubeadm init phase upload-certs`"),
        ),
        docs_links=(
            StudyDocLink(
                label="Creating a cluster with kubeadm",
                url="https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/",
                exam_search_term="Creating a cluster with kubeadm",
            ),
            StudyDocLink(
                label="Container Runtimes (containerd systemd)",
                url="https://kubernetes.io/docs/setup/production-environment/container-runtimes/",
                exam_search_term="SystemdCgroup",
            ),
            StudyDocLink(
                label="HA Topology Options",
                url="https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/",
                exam_search_term="Stacked etcd topology",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify swap, kernel modules, sysctls, and containerd SystemdCgroup",
                explanation="Check OS prerequisites cleanly before running `kubeadm init` or `join`.",
                command="sudo modprobe overlay br_netfilter && sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables && grep -n SystemdCgroup /etc/containerd/config.toml",
                verify_command="swapon --show | wc -l && grep -E 'SystemdCgroup' /etc/containerd/config.toml",
                expected_output="0 swap active lines; SystemdCgroup = true",
            ),
            PracticeStep(
                title="Initialize controlplane with explicit Pod CIDR",
                explanation="Use `--pod-network-cidr` matching your chosen CNI (e.g. `10.244.0.0/16` Flannel, `192.168.0.0/16` Calico) and copy `admin.conf`.",
                command="sudo kubeadm init --pod-network-cidr=10.244.0.0/16 && mkdir -p $HOME/.kube && sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config",
            ),
            PracticeStep(
                title="Generate a fresh join command for worker nodes",
                explanation="Prints full `kubeadm join <ip:6443> --token ... --discovery-token-ca-cert-hash sha256:...`.",
                command="kubeadm token create --print-join-command",
                verify_command="kubeadm token list",
                expected_output="At least one active token with TTL remaining",
            ),
        ),
        debug_playbook=(
            DebugRow("`kubeadm init` fails preflight: `Swap is enabled`", "Swap partition/file still active or enabled in `/etc/fstab`", "Run `sudo swapoff -a` and comment out swap lines in `/etc/fstab`"),
            DebugRow("`kubelet` flaps with containerd cgroup driver mismatch", "containerd uses `cgroupfs` (`SystemdCgroup = false`) while kubelet expects `systemd`", "Edit `/etc/containerd/config.toml` -> `SystemdCgroup = true`, then `systemctl restart containerd kubelet`"),
            DebugRow("Controlplane stays `NotReady` right after `kubeadm init`", "No CNI plugin installed yet (`ls /etc/cni/net.d/` empty)", "Apply CNI manifest (Calico/Flannel/Cilium) and verify `coredns` Pods turn `Running`"),
        ),
        exam_trap=(
            "If asked to prepare containerd on a fresh Linux node, NEVER forget to run `sudo systemctl restart containerd` after flipping `SystemdCgroup = true` in `/etc/containerd/config.toml` (and reload sysctls with `sudo sysctl --system`)."
        ),
        cheatsheet=(
            CheatItem("Load required modules", "sudo modprobe overlay && sudo modprobe br_netfilter", "Needed for containerd + CNI bridging"),
            CheatItem("Apply sysctls", "sudo sysctl --system", "Applies /etc/sysctl.d/*.conf changes"),
            CheatItem("Default containerd TOML", "containerd config default | sudo tee /etc/containerd/config.toml", "Then flip SystemdCgroup = true"),
            CheatItem("Print worker join cmd", "kubeadm token create --print-join-command", "Run on controlplane"),
            CheatItem("Print HA CP join key", "sudo kubeadm init phase upload-certs --upload-certs", "Generates 2h certificate-key for `--control-plane`"),
            CheatItem("Cleanup failed init", "sudo kubeadm reset -f && sudo rm -rf /etc/cni/net.d", "Clean slate before re-running init"),
        ),
        yaml_template=(
            "# /etc/modules-load.d/k8s.conf\n"
            "overlay\n"
            "br_netfilter\n\n"
            "# /etc/sysctl.d/k8s.conf\n"
            "net.bridge.bridge-nf-call-iptables  = 1\n"
            "net.bridge.bridge-nf-call-ip6tables = 1\n"
            "net.ipv4.ip_forward                 = 1\n\n"
            "# /etc/containerd/config.toml (cri plugin section)\n"
            "[plugins.\"io.containerd.grpc.v1.cri\".containerd.runtimes.runc.options]\n"
            "  SystemdCgroup = true\n\n"
            "# Bootstrap primary controlplane:\n"
            "# sudo kubeadm init --pod-network-cidr=192.168.0.0/16 --cri-socket=unix:///run/containerd/containerd.sock"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Immediately after `kubeadm init` succeeds on a clean node, `kubectl get nodes` reports the node status as `NotReady`. What is almost always missing?",
                choices=(
                    "A StorageClass named `standard`",
                    "A Container Network Interface (CNI) plugin installed on the cluster",
                    "A LoadBalancer Service in `default`",
                    "`kubeadm certs renew all`",
                ),
                correct_index=1,
                explanation="kubelet marks nodes `NotReady` until a CNI network plugin configures `/etc/cni/net.d/` and Pod networking becomes operational.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which command on controlplane creates a fresh bootstrap token and outputs the complete ready-to-paste `kubeadm join` command for a worker?",
                choices=(
                    "kubeadm join --generate",
                    "kubeadm token create --print-join-command",
                    "kubectl cluster-info join",
                    "kubeadm config print join-defaults",
                ),
                correct_index=1,
                explanation="`kubeadm token create --print-join-command` issues a new 24h token, computes the CA cert SHA256 pin, and formats the exact `kubeadm join` line.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="On a newly provisioned Ubuntu node, kubelet logs `misconfiguration: kubelet cgroup driver: \"systemd\" is different from docker/containerd cgroup driver: \"cgroupfs\"`. Where do you fix this?",
                choices=(
                    "Set `SystemdCgroup = true` inside `/etc/containerd/config.toml` and restart `containerd`",
                    "Delete `/etc/kubernetes/pki/ca.crt`",
                    "Pass `--pod-network-cidr=0.0.0.0/0` to `kubeadm init`",
                    "Mount `/sys/fs/cgroup` read-only on CoreDNS",
                ),
                correct_index=0,
                explanation="Generating `/etc/containerd/config.toml`, setting `SystemdCgroup = true` under the CRI runc systemd options, and restarting `containerd` aligns cgroup drivers cleanly.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-etcd-backup-restore",
        order=3,
        domain=DOMAIN,
        title="etcd Snapshot Backup & Cluster Restore",
        subtitle="Capture TLS-authenticated snapshots and restore offline without corrupting kubelet static Pods.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-etcd-snapshot-save", "ca-etcd-restore"),
        summary=(
            "etcd persists every cluster object on controlplane nodes, typically running as a static Pod declared in "
            "`/etc/kubernetes/manifests/etcd.yaml`. Snapshot capture connects live over TLS (`127.0.0.1:2379`); restore runs offline "
            "against a brand-new `--data-dir` via `etcdutl` (or `etcdctl snapshot restore`) before repointing `etcd.yaml`'s `hostPath.path`."
        ),
        architecture_flow=(
            "Save (Online): etcdctl --cacert/cert/key snapshot save -> /path/snap.db  ||  Restore (Offline): etcdutl snapshot restore -> New --data-dir -> Update etcd.yaml hostPath -> kubelet restarts etcd & apiserver"
        ),
        theory_points=(
            "Always read exact TLS paths (`--trusted-ca-file`, `--cert-file`, `--key-file`) and listen endpoints directly from `/etc/kubernetes/manifests/etcd.yaml`.",
            "Set `ETCDCTL_API=3` before `etcdctl` (legacy v2 defaults break `snapshot save`); modern Kubernetes v1.34+ clusters prefer `etcdutl` for `snapshot status` and `snapshot restore`, while `etcdctl snapshot save` remains the live backup CLI.",
            "Never overwrite a live `/var/lib/etcd` directory while etcd is running — always restore into a NEW `--data-dir` (e.g. `/var/lib/etcd-restored`), passing `--name`, `--initial-cluster`, and `--initial-advertise-peer-urls` matching `/etc/kubernetes/manifests/etcd.yaml` for kubeadm stacked etcd.",
            "Inside `/etc/kubernetes/manifests/etcd.yaml`, container `volumeMounts` keep mounting `/var/lib/etcd`, so you MUST update `spec.volumes[name=etcd-data].hostPath.path` (and `--data-dir` only if hostPath wasn't abstracted).",
            "For an external etcd cluster (non-stacked), pass `--endpoints=https://<ETCD_HOST_IP>:2379` (listed in `kube-apiserver.yaml --etcd-servers`), NOT `127.0.0.1`.",
            "After editing `etcd.yaml`, expect 15–45 seconds of `kubectl` TLS/connection-refused retries while `kubelet` recreates `etcd` and `kube-apiserver` static Pods; watch directly with `sudo crictl ps`.",
        ),
        decision_matrix=(
            ComparisonRow("`etcdctl snapshot save`", "Reads consistent snapshot over HTTPS from live etcd", "Backup task on running controlplane/external etcd"),
            ComparisonRow("`etcdutl` / `etcdctl snapshot restore`", "Unpacks snapshot offline to new data directory + initializes member", "Restoring cluster state into `/var/lib/etcd-restored`"),
            ComparisonRow("`hostPath.path` edit in `etcd.yaml`", "Swaps physical host dir backing `/var/lib/etcd` inside container", "Clean kubeadm etcd restore keeping container command flags intact"),
            ComparisonRow("`etcdctl snapshot status`", "Prints hash, revision, total keys, total size (`-w table`)", "Proving backup integrity right after saving"),
        ),
        docs_links=(
            StudyDocLink(
                label="Operating etcd clusters for Kubernetes",
                url="https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/",
                exam_search_term="Operating etcd clusters",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Extract exact TLS flags and endpoint from etcd.yaml",
                explanation="Read `/etc/kubernetes/manifests/etcd.yaml` (or `kube-apiserver.yaml --etcd-servers` for external etcd).",
                command="sudo grep -E 'cert-file|key-file|trusted-ca-file|listen-client-urls|path:' /etc/kubernetes/manifests/etcd.yaml",
                verify_command="sudo grep -E 'ca.crt|server.crt|server.key' /etc/kubernetes/manifests/etcd.yaml",
                expected_output="Paths under /etc/kubernetes/pki/etcd/{ca,server}.{crt,key}",
            ),
            PracticeStep(
                title="Save and verify an etcd v3 snapshot",
                explanation="Save to target filename and immediately verify key count/revision with `snapshot status`.",
                command=(
                    "sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 "
                    "--cacert=/etc/kubernetes/pki/etcd/ca.crt "
                    "--cert=/etc/kubernetes/pki/etcd/server.crt "
                    "--key=/etc/kubernetes/pki/etcd/server.key snapshot save /opt/backup/etcd.db"
                ),
                verify_command="sudo etcdutl snapshot status /opt/backup/etcd.db -w table",
                expected_output="Table showing HASH, REVISION, TOTAL KEYS, and non-zero TOTAL SIZE",
            ),
            PracticeStep(
                title="Restore offline to fresh data-dir and repoint `etcd.yaml`",
                explanation="Unpack to `/var/lib/etcd-restored`, swap `volumes[name=etcd-data].hostPath.path`, and verify via `crictl`.",
                command="sudo etcdutl snapshot restore /opt/backup/etcd.db --data-dir=/var/lib/etcd-restored",
                yaml_snippet=(
                    "# Inside /etc/kubernetes/manifests/etcd.yaml:\n"
                    "volumes:\n"
                    "- hostPath:\n"
                    "    path: /var/lib/etcd-restored\n"
                    "    type: DirectoryOrCreate\n"
                    "  name: etcd-data"
                ),
                verify_command="sudo crictl ps | grep -E 'etcd|kube-apiserver' && k get nodes",
                expected_output="Both static containers Running cleanly and `kubectl get nodes` returning Ready",
            ),
        ),
        debug_playbook=(
            DebugRow("`Error: context deadline exceeded` during `snapshot save`", "Wrong `--endpoints`, firewall block, or missing `--cacert`", "Inspect `--listen-client-urls` in `etcd.yaml` and `--etcd-servers` in `kube-apiserver.yaml`"),
            DebugRow("`etcdctl snapshot restore` command not found in new etcd v3.6+", "Upstream separated offline ops into `etcdutl` binary", "Run `sudo etcdutl snapshot restore <snap> --data-dir=/var/lib/etcd-restored`"),
            DebugRow("Restore done yet `kubectl get ns` shows post-backup objects", "Edited `--data-dir` instead of `volumes[].hostPath.path`, or kubelet cached old pod", "Update `etcd.yaml` `hostPath.path` and move/touch manifest if needed; check `crictl ps`"),
        ),
        exam_trap=(
            "Never keep backup `.yaml.bak` files inside `/etc/kubernetes/manifests/` while editing `etcd.yaml` — move backups to `/tmp/` so kubelet does not launch two conflicting etcd Pods on ports 2379/2380."
        ),
        cheatsheet=(
            CheatItem("Inspect etcd certs", "sudo grep -E 'ca|cert|key|data-dir' /etc/kubernetes/manifests/etcd.yaml", "Run on controlplane"),
            CheatItem("Snapshot save", "sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key snapshot save /tmp/etcd.db", "Live encrypted snapshot"),
            CheatItem("Verify snapshot", "sudo etcdutl snapshot status /tmp/etcd.db -w table", "Confirms valid snapshot file (etcdctl fallback if absent)"),
            CheatItem("Snapshot restore", "sudo etcdutl snapshot restore /tmp/etcd.db --name=<NAME> --initial-cluster=<CLUSTER> --initial-advertise-peer-urls=<PEER> --data-dir=/var/lib/etcd-restored", "Modern v1.34+ offline restore CLI with kubeadm member flags from etcd.yaml"),
            CheatItem("Check static containers", "sudo crictl ps -a | grep -E 'etcd|kube-apiserver'", "Verify clean restart without CrashLoop"),
        ),
        yaml_template=(
            "# /etc/kubernetes/manifests/etcd.yaml (critical fields to inspect/swap)\n"
            "spec:\n"
            "  containers:\n"
            "  - command:\n"
            "    - etcd\n"
            "    - --data-dir=/var/lib/etcd-restored   # update only if mountPath changed\n"
            "    - --listen-client-urls=https://127.0.0.1:2379,https://10.0.0.10:2379\n"
            "    volumeMounts:\n"
            "    - mountPath: /var/lib/etcd            # keep container mountPath synced with --data-dir\n"
            "      name: etcd-data\n"
            "  volumes:\n"
            "  - hostPath:\n"
            "      path: /var/lib/etcd-restored          # point hostPath to clean offline restore dir\n"
            "      type: DirectoryOrCreate\n"
            "    name: etcd-data"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why should you restore an etcd snapshot into `/var/lib/etcd-restored` rather than directly overwriting `/var/lib/etcd`?",
                choices=(
                    "etcd requires two snapshots simultaneously to boot",
                    "Live etcd holds active locks/WAL files in `/var/lib/etcd`; restoring offline to a new directory avoids corruption and cleanly swaps `hostPath.path`",
                    "`kube-scheduler` writes directly to `/var/lib/etcd`",
                    "Linux forbids overwriting files ending in `.snap`",
                ),
                correct_index=1,
                explanation="Offline snapshot restore writes a clean member directory with fresh WAL/snap files; swapping `hostPath.path` in `etcd.yaml` restarts etcd safely.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You saved `/opt/snap.db`. Which command verifies the snapshot header, revision, and key count safely without writing to etcd?",
                choices=(
                    "ETCDCTL_API=3 etcdctl snapshot verify /opt/snap.db",
                    "ETCDCTL_API=3 etcdctl snapshot status /opt/snap.db -w table",
                    "etcdctl get / --from-file=/opt/snap.db",
                    "kubeadm etcd check /opt/snap.db",
                ),
                correct_index=1,
                explanation="`etcdctl snapshot status <file> -w table` (or `etcdutl snapshot status`) validates snapshot integrity and prints revision/key stats.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You restored a backup to `/var/lib/etcd-new` and updated `spec.volumes[etcd-data].hostPath.path`, yet left `/etc/kubernetes/manifests/etcd.yaml.bak` inside `/etc/kubernetes/manifests/`. What goes wrong?",
                choices=(
                    "Nothing, kubelet skips `.bak` files",
                    "kubelet parses both YAML files as separate static Pods causing port `2379`/`2380` collisions",
                    "kubeadm automatically restores `/etc/kubernetes/manifests/etcd.yaml` to old state",
                    "CoreDNS shuts down intentionally",
                ),
                correct_index=1,
                explanation="kubelet treats EVERY readable manifest file inside `staticPodPath` (`/etc/kubernetes/manifests`) as a static Pod — always save backups to `/tmp/` or `/root/`.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-kubeadm-upgrades",
        order=4,
        domain=DOMAIN,
        title="Cluster Upgrades with `kubeadm` & Node Drain",
        subtitle="Upgrade apt/pkgs, controlplane, worker nodes, and kubelet cleanly one minor release at a time.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-kubeadm-node-upgrade", "ca-kubeadm-node-drain"),
        summary=(
            "Upgrading a kubeadm cluster follows a strict minor-version order (`1.X -> 1.X+1`, primary controlplane first, "
            "then workers): drain the node safely, switch apt package repo minor version if bumping minor, unhold/upgrade `kubeadm`, "
            "run `kubeadm upgrade apply` (controlplane) or `kubeadm upgrade node` (worker), upgrade `kubelet` + `kubectl`, reload/restart kubelet, and uncordon."
        ),
        architecture_flow=(
            "1. k drain <node> -> 2. apt unhold & upgrade kubeadm -> 3. kubeadm upgrade [plan + apply vX.Y.Z | node] -> 4. upgrade kubelet + kubectl -> 5. daemon-reload + restart kubelet -> 6. k uncordon"
        ),
        theory_points=(
            "Never skip a minor release (`1.33 -> 1.34 -> 1.35`); on Ubuntu/Debian switching minor versions requires updating `/etc/apt/sources.list.d/kubernetes.list` (`pkgs.k8s.io/core:/stable:/v1.XX/deb/`) before `apt-get update`.",
            "Always upgrade the FIRST controlplane node before secondary controlplanes or workers; controlplane runs `kubeadm upgrade apply vX.Y.Z` (preview first with `kubeadm upgrade plan` / `diff`), whereas workers and extra controlplanes run `kubeadm upgrade node`.",
            "`kubectl drain` refuses Pods managed by DaemonSets (add `--ignore-daemonsets`) or local emptyDir volumes (add `--delete-emptydir-data`).",
            "Active `PodDisruptionBudgets` (PDBs) can stall `kubectl drain` cleanly by design — inspect `k get pdb -A` if drain hangs rather than blindly passing `--force` unless losing an unmanaged Pod.",
            "Remember `apt-mark hold kubeadm kubelet kubectl` after installing pinned packages (`=1.X.Y-*`) so unattended upgrades never drift cluster versions.",
        ),
        decision_matrix=(
            ComparisonRow("`kubeadm upgrade apply v1.X.Y`", "Rewrites controlplane static Pods + cluster config + CoreDNS/kube-proxy", "Primary controlplane node ONLY"),
            ComparisonRow("`kubeadm upgrade node`", "Syncs local kubelet configuration (and static Pods on secondary CPs)", "Worker nodes and secondary controlplanes"),
            ComparisonRow("`kubectl cordon <node>`", "Marks `SchedulingDisabled` without evicting running Pods", "Halting new Pods while letting existing jobs finish"),
            ComparisonRow("`kubectl drain <node>`", "Cordons node AND gracefully evicts Pods honoring PDBs", "Preparing node for upgrade/maintenance"),
        ),
        docs_links=(
            StudyDocLink(
                label="Upgrading kubeadm clusters",
                url="https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/",
                exam_search_term="Upgrading kubeadm clusters",
            ),
            StudyDocLink(
                label="Safely Drain a Node",
                url="https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/",
                exam_search_term="Safely Drain a Node",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Drain the target node from admin workstation",
                explanation="Evict workloads safely while preserving DaemonSet Pods (`kube-proxy`, CNI) and cleaning ephemeral data.",
                command="k drain node01 --ignore-daemonsets --delete-emptydir-data",
                verify_command="k get node node01",
                expected_output="STATUS displays `Ready,SchedulingDisabled`",
            ),
            PracticeStep(
                title="Upgrade kubeadm, check plan, and upgrade cluster/node config",
                explanation="Inspect exact available version via `apt-cache madison kubeadm`; swap repo `/v1.XX/` if upgrading minor versions.",
                command="sudo apt-mark unhold kubeadm && sudo apt-get update && sudo apt-get install -y kubeadm=1.34.0-* && sudo kubeadm upgrade node",
                verify_command="kubeadm version -o short && sudo kubelet --version",
                expected_output="Updated kubeadm version matches target `v1.34.x`",
            ),
            PracticeStep(
                title="Upgrade kubelet + kubectl, restart systemd, and uncordon",
                explanation="Re-hold packages cleanly, reload systemd daemon, restart kubelet, then allow scheduling again.",
                command="sudo apt-mark unhold kubelet kubectl && sudo apt-get install -y kubelet=1.34.0-* kubectl=1.34.0-* && sudo apt-mark hold kubeadm kubelet kubectl && sudo systemctl daemon-reload && sudo systemctl restart kubelet",
                verify_command="k uncordon node01 && k get nodes",
                expected_output="STATUS is `Ready` and VERSION reflects upgraded kubelet",
            ),
        ),
        debug_playbook=(
            DebugRow("`apt-cache madison kubeadm` lacks target minor `1.XX`", "Apt source file still points to older `/core:/stable:/v1.(X-1)/deb/`", "Run `sed -i 's/v1.33/v1.34/g' /etc/apt/sources.list.d/kubernetes.list && apt-get update`"),
            DebugRow("`kubectl drain` errors on DaemonSet or `local storage`", "DaemonSets and `emptyDir` Pods block default drain safety checks", "Pass `--ignore-daemonsets` and `--delete-emptydir-data`"),
            DebugRow("`kubectl get nodes` shows old `kubeletVersion` after `upgrade node`", "Forgot to upgrade `kubelet` package or forgot `systemctl restart kubelet`", "Install matching `kubelet=1.X.Y-*`, run `daemon-reload && restart kubelet`"),
        ),
        exam_trap=(
            "Carefully read the prompt wording: if a question asks to drain `node01` (or upgrade controlplane ONLY without upgrading workers), check whether uncordoning at the end is requested — AND never forget `systemctl daemon-reload && systemctl restart kubelet`!"
        ),
        cheatsheet=(
            CheatItem("Drain node safely", "k drain <node> --ignore-daemonsets --delete-emptydir-data", "Cordon + safe Pod eviction"),
            CheatItem("List apt versions", "sudo apt-cache madison kubeadm | head", "Confirm exact `1.X.Y-*` package string"),
            CheatItem("Switch apt minor repo", "sudo sed -i 's/v1.33/v1.34/g' /etc/apt/sources.list.d/kubernetes.list", "Required when crossing minor releases"),
            CheatItem("Controlplane upgrade", "sudo kubeadm upgrade plan && sudo kubeadm upgrade apply v1.X.Y", "First controlplane node only"),
            CheatItem("Worker/extra CP upgrade", "sudo kubeadm upgrade node", "Run after upgrading kubeadm on workers"),
            CheatItem("Restart kubelet & restore", "sudo systemctl daemon-reload && sudo systemctl restart kubelet && k uncordon <node>", "Finalizes node upgrade"),
        ),
        yaml_template=(
            "# Canonical kubeadm minor upgrade sequence (e.g. v1.33 -> v1.34)\n"
            "# 1. On workstation: drain target node safely\n"
            "kubectl drain controlplane --ignore-daemonsets --delete-emptydir-data\n\n"
            "# 2. On node: switch minor channel + upgrade kubeadm + upgrade cluster/node\n"
            "sudo sed -i 's/v1.33/v1.34/g' /etc/apt/sources.list.d/kubernetes.list\n"
            "sudo apt-mark unhold kubeadm && sudo apt-get update && sudo apt-get install -y kubeadm=1.34.0-*\n"
            "sudo kubeadm upgrade plan && sudo kubeadm upgrade apply v1.34.0   # CP1 only (workers run: kubeadm upgrade node)\n\n"
            "# 3. Upgrade kubelet + kubectl, restart daemon, uncordon, and verify\n"
            "sudo apt-mark unhold kubelet kubectl && sudo apt-get install -y kubelet=1.34.0-* kubectl=1.34.0-*\n"
            "sudo apt-mark hold kubeadm kubelet kubectl && sudo systemctl daemon-reload && sudo systemctl restart kubelet\n"
            "kubectl uncordon controlplane && kubectl get nodes -o wide"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Before upgrading `kubeadm` packages from `v1.33.x` to `v1.34.x` on Ubuntu using the Kubernetes community pkgs.k8s.io repo, what prerequisite step makes `1.34` packages visible to apt?",
                choices=(
                    "Run `kubectl uncordon controlplane`",
                    "Update the repository path inside `/etc/apt/sources.list.d/kubernetes.list` from `v1.33` to `v1.34` and run `apt-get update`",
                    "Delete `/etc/kubernetes/admin.conf`",
                    "Set `ETCDCTL_API=3` in bashrc",
                ),
                correct_index=1,
                explanation="`pkgs.k8s.io` splits each Kubernetes minor version into its own apt channel (`/v1.33/`, `/v1.34/`), so `sources.list.d` must point to the target minor channel.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which command upgrades local kubelet configuration on a WORKER node after installing the new `kubeadm` package?",
                choices=(
                    "sudo kubeadm upgrade apply v1.34.0",
                    "sudo kubeadm upgrade node",
                    "sudo kubectl upgrade node01",
                    "sudo kubeadm init phase kubelet-start",
                ),
                correct_index=1,
                explanation="`kubeadm upgrade apply` runs only on the primary controlplane; worker and secondary controlplane nodes run `sudo kubeadm upgrade node`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="`kubectl drain node02 --ignore-daemonsets` fails with `error when evicting pods: pods with local storage: web-cache-xyz`. What flag fixes eviction safely?",
                choices=(
                    "`--skip-wait-for-delete-timeout=0`",
                    "`--delete-emptydir-data`",
                    "`--ignore-errors=true`",
                    "`--disable-eviction=false`",
                ),
                correct_index=1,
                explanation="`emptyDir` volumes are ephemeral and disappear upon Pod eviction, so drain requires explicit opt-in via `--delete-emptydir-data`.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-tls-csr-certs",
        order=5,
        domain=DOMAIN,
        title="User Auth CSRs, Kubeadm PKI & Cert Renewal",
        subtitle="Issue user client certs via CSRs, build kubeconfigs, and audit/renew cluster PKI.",
        estimated_minutes=6,
        exam_frequency="High",
        archetype_ids=("ca-csr-user-auth", "ca-cert-expiry-inspect"),
        summary=(
            "Kubeadm uses X.509 client certificates where `/CN=` sets the Kubernetes username and `/O=` sets groups. "
            "Candidates must generate/encode `.csr` files into `CertificateSigningRequest` (`certificates.k8s.io/v1`), approve & decode "
            "`.crt` outputs, wire `kubectl config set-credentials/set-context`, and inspect/renew controlplane certs with `kubeadm certs` + `openssl`."
        ),
        architecture_flow=(
            "openssl genrsa -> openssl req -new (.csr) -> base64 -> CSR YAML (signer: kube-apiserver-client) -> k certificate approve -> base64 -d .crt -> kubeconfig + RBAC RoleBinding"
        ),
        theory_points=(
            "`CertificateSigningRequest.spec.request` requires single-line base64 (`base64 -w0` on Linux, or `tr -d '\\n'`), `signerName: kubernetes.io/kube-apiserver-client`, and `usages: [client auth]`.",
            "After `k certificate approve <csr>`, decode `.status.certificate` (`| base64 -d > user.crt`) and verify Subject CN/O via `openssl x509 -in user.crt -noout -subject`.",
            "Creating & approving a CSR ONLY creates an **authenticated identity** (`CN` = `User`, `O` = `Group`); you still need an RBAC `RoleBinding` or `ClusterRoleBinding` for authorization!",
            "`sudo kubeadm certs check-expiration` audits remaining days on `apiserver`, `apiserver-kubelet-client`, `front-proxy-client`, `etcd-server`, etc.; `sudo kubeadm certs renew all` extends them 1 year (restart controlplane static Pods after renewing!).",
            "On worker/controlplane nodes, `/etc/kubernetes/pki/apiserver.crt` SANs and expiration dates are verifiable offline anytime with `openssl x509 -in <cert> -noout -dates -text`.",
        ),
        decision_matrix=(
            ComparisonRow("`CN=<user>` in X.509 Subject", "Maps to RBAC subject `kind: User`", "Identifying individual developer or automation client"),
            ComparisonRow("`O=<group>` in X.509 Subject", "Maps to RBAC subject `kind: Group`", "Granting team-wide permissions across developers"),
            ComparisonRow("`kubeadm certs check-expiration`", "Summarizes all kubeadm-managed PKI cert dates + CA flags", "Auditing controlplane expiry quickly on controlplane"),
            ComparisonRow("`openssl x509 -in ... -noout -dates`", "Reads NotBefore/NotAfter on ANY raw `.crt` file directly", "Checking custom certs, CSR output, or kubelet client certs"),
        ),
        docs_links=(
            StudyDocLink(
                label="Manage TLS Certificates in a Cluster",
                url="https://kubernetes.io/docs/tasks/tls/managing-tls-in-a-cluster/",
                exam_search_term="Managing TLS Certificates in a Cluster",
            ),
            StudyDocLink(
                label="Certificate Management with kubeadm",
                url="https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/",
                exam_search_term="kubeadm certs",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Create a CertificateSigningRequest YAML from a `.csr` file",
                explanation="Strip all line breaks (`base64 -w 0`) before pasting into `spec.request`.",
                command="cat client.csr | base64 -w 0 2>/dev/null || base64 < client.csr | tr -d '\\n'",
                yaml_snippet=(
                    "apiVersion: certificates.k8s.io/v1\n"
                    "kind: CertificateSigningRequest\n"
                    "metadata:\n"
                    "  name: dev-user\n"
                    "spec:\n"
                    "  request: <BASE64_SINGLE_LINE_CSR>\n"
                    "  signerName: kubernetes.io/kube-apiserver-client\n"
                    "  expirationSeconds: 86400\n"
                    "  usages:\n"
                    "  - client auth"
                ),
            ),
            PracticeStep(
                title="Approve CSR, decode signed certificate, and verify identity",
                explanation="Verify `.status.conditions[].type` equals `Approved` and extract `.status.certificate` to `.crt`.",
                command="k certificate approve dev-user && k get csr dev-user -o jsonpath='{.status.certificate}' | base64 -d > dev-user.crt",
                verify_command="openssl x509 -in dev-user.crt -noout -subject -dates",
                expected_output="Subject CN matching user plus valid NotBefore / NotAfter dates",
            ),
            PracticeStep(
                title="Audit cluster PKI expiry dates via kubeadm & openssl",
                explanation="Check controlplane cert expiration and inspect `apiserver.crt` Subject Alternative Names.",
                command="sudo kubeadm certs check-expiration && openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -dates -ext subjectAltName",
                verify_command="sudo kubeadm certs check-expiration | grep -E 'apiserver|etcd-server'",
                expected_output="RESIDUAL TIME >= 1 day and `CERTIFICATE` expiration listed clearly",
            ),
        ),
        debug_playbook=(
            DebugRow("`CSR ... spec.request: Invalid value ... illegal base64`", "Multiline linebreaks left inside `spec.request`", "Encode using `cat user.csr | base64 -w 0` (`tr -d '\\n'` on macOS)"),
            DebugRow("Approved CSR user gets `Forbidden` on `kubectl get pods`", "CSR grants AuthN only; missing `RoleBinding` for `kind: User`", "Run `k -n <ns> create rolebinding ... --user=<CN> --role=<role>`"),
            DebugRow("After `kubeadm certs renew all`, API still serves expired cert", "Static Pods didn't reload newly written certs in `/etc/kubernetes/pki/`", "Restart controlplane containers cleanly via `crictl stopp` / move manifests briefly"),
        ),
        exam_trap=(
            "Wait until `k get csr <name>` shows `Approved,Issued` before extracting `.status.certificate` (`empty` right after apply), AND remember to bind an RBAC `RoleBinding`/`ClusterRoleBinding` matching `kind: User` (the CSR's `CN`)."
        ),
        cheatsheet=(
            CheatItem("Generate key + CSR", "openssl genrsa -out dev.key 2048 && openssl req -new -key dev.key -out dev.csr -subj '/CN=dev/O=devs'", "Sets User=dev, Group=devs"),
            CheatItem("Encode CSR 1-line", "base64 -w 0 dev.csr 2>/dev/null || base64 < dev.csr | tr -d '\\n'", "Single-line spec.request"),
            CheatItem("Approve / Deny CSR", "k certificate approve <csr-name>", "Signs cert via controller-manager"),
            CheatItem("Export signed CRT", "k get csr <name> -o jsonpath='{.status.certificate}' | base64 -d > dev.crt", "Decodes signed X.509 cert"),
            CheatItem("Check PKI expiry", "sudo kubeadm certs check-expiration", "Audits all kubeadm cluster certs"),
            CheatItem("Renew cluster certs", "sudo kubeadm certs renew all", "Renews controlplane certs (+1 yr)"),
        ),
        yaml_template=(
            "apiVersion: certificates.k8s.io/v1\n"
            "kind: CertificateSigningRequest\n"
            "metadata:\n"
            "  name: jane\n"
            "spec:\n"
            "  request: REPLACE_WITH_BASE64\n"
            "  signerName: kubernetes.io/kube-apiserver-client\n"
            "  expirationSeconds: 86400\n"
            "  usages:\n"
            "  - client auth"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A client presents an X.509 certificate with Subject `/CN=alice/O=ops-team` signed by the cluster CA. How does Kubernetes map that certificate for RBAC?",
                choices=(
                    "ServiceAccount `alice` in namespace `ops-team`",
                    "User `alice` belonging to Group `ops-team`",
                    "ClusterRole `ops-team` named `alice`",
                    "Anonymous user unless `token` header exists",
                ),
                correct_index=1,
                explanation="Kubernetes maps `CN` (Common Name) to `kind: User` and `O` (Organization) values to `kind: Group` during client-cert authentication.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which `signerName` is required on a `certificates.k8s.io/v1` CSR for authenticating a new `kubectl` user?",
                choices=(
                    "kubernetes.io/kubelet-serving",
                    "kubernetes.io/kube-apiserver-client",
                    "kubernetes.io/legacy-unknown",
                    "cert-manager.io/ca-issuer",
                ),
                correct_index=1,
                explanation="`kubernetes.io/kube-apiserver-client` issues client auth certs accepted by `kube-apiserver`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You approved CSR `bob` and configured `kubectl` with `bob.crt` + `bob.key`, yet running `kubectl get pods -n dev` fails with `Forbidden`. Why?",
                choices=(
                    "You used `expirationSeconds: 86400` instead of `0`",
                    "Certificate approval authenticates identity ONLY — you still need an RBAC `RoleBinding`/`ClusterRoleBinding` granting `User: bob` permissions",
                    "`bob.crt` must also be copied into `/etc/kubernetes/pki/`",
                    "The CSR must be renewed with `kubeadm certs renew` first",
                ),
                correct_index=1,
                explanation="Authentication (X.509 cert) and Authorization (RBAC) are separate stages; `bob` defaults to deny-all until bound via RBAC.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-kubeconfig-jsonpath",
        order=6,
        domain=DOMAIN,
        title="`kubeconfig` Contexts, `jsonpath`, `--sort-by` & PSI Speed",
        subtitle="Master multi-cluster context switching, kubeconfig repairs, `jsonpath`, and `kubectl explain`.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("ca-csr-user-auth", "ca-crd-inspect", "ca-user-kubeconfig-context"),
        summary=(
            "Every CKA task starts with switching context (`kubectl config use-context <ctx>`) or fixing broken `kubeconfig` endpoints/credentials. "
            "Pairing `kubeconfig` mastery with `-o jsonpath`, `-o custom-columns`, `--sort-by`, and `kubectl explain --recursive` eliminates guesswork "
            "and slashes completion time across all 17–20 exam questions."
        ),
        architecture_flow=(
            "kubeconfig = clusters[] (API URL + CA) + users[] (client cert/token) + contexts[] (cluster + user + default namespace) -> current-context"
        ),
        theory_points=(
            "Always run `kubectl config use-context <target>` BEFORE every CKA question — solving a task perfectly on the wrong context scores 0 points.",
            "A `kubeconfig` binds three named sections: `clusters` (`server: https://<ip>:6443`, `certificate-authority-data`), `users` (`client-certificate-data`, `client-key-data`), and `contexts` (`cluster`, `user`, optional `namespace`).",
            "Pass `--kubeconfig=/root/broken.kubeconfig` or merge configs cleanly via `KUBECONFIG=cfg1:cfg2 kubectl config view --flatten > merged.cfg`.",
            "Extract arrays safely in `-o jsonpath='{range .items[*]}{.metadata.name}{\"\\t\"}{.status.phase}{\"\\n\"}{end}'` — escape dots in annotation/label keys with backslashes (`metadata.labels['app\\.kubernetes\\.io/name']`).",
            "`--sort-by=.status.capacity.cpu` or `--sort-by='.metadata.creationTimestamp'` + `| tac` orders lists cleanly when asked for highest CPU node or oldest/newest Pod.",
            "Use `kubectl explain <resource>.<field> --recursive | grep -A10 <key>` offline right in the terminal faster than searching web docs!",
        ),
        decision_matrix=(
            ComparisonRow("`-o jsonpath='...'`", "Extracts exact nested scalars or looped fields (script-friendly)", "Tasks asking for raw IPs, cert strings, sorted names -> file"),
            ComparisonRow("`-o custom-columns=COL:.path`", "Clean human-readable tabular columns automatically with newline", "Auditing Pods/Nodes/SCs quickly during troubleshooting"),
            ComparisonRow("`--sort-by=.path`", "Sorts `.items[]` ascending by any JSONPath field", "Finding highest restart Pod or most recent Event"),
            ComparisonRow("`kubectl config set-context --current --namespace=...`", "Pins default namespace on current context without retyping `-n`", "Staying locked to task namespace cleanly"),
        ),
        docs_links=(
            StudyDocLink(
                label="Organizing Cluster Access Using kubeconfig Files",
                url="https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/",
                exam_search_term="kubeconfig",
            ),
            StudyDocLink(
                label="JSONPath Support",
                url="https://kubernetes.io/docs/reference/kubectl/jsonpath/",
                exam_search_term="JSONPath Support",
            ),
            StudyDocLink(
                label="kubectl Quick Reference",
                url="https://kubernetes.io/docs/reference/kubectl/quick-reference/",
                exam_search_term="kubectl Quick Reference",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect and switch contexts / default namespace safely",
                explanation="Verify active context name and server IP before touching resources.",
                command="k config get-contexts && k config current-context",
                verify_command="k config view --minify -o jsonpath='{.clusters[0].cluster.server}{\"\\n\"}'",
                expected_output="Prints `https://<controlplane-ip>:6443` of current context only",
            ),
            PracticeStep(
                title="Write a loop-based `jsonpath` + `--sort-by` query to a file",
                explanation="Common exam task pattern: extract node internal IPs or sort PVCs/Pods and save lines into `/opt/...`.",
                command="k get nodes -o jsonpath='{range .items[*]}{.metadata.name}{\" \"}{.status.addresses[?(@.type==\"InternalIP\")].address}{\"\\n\"}{end}'",
                verify_command="k get pods -A --sort-by='.status.containerStatuses[0].restartCount' -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name | tail -n 5",
                expected_output="Shows space-separated node IPs and pods sorted ascending by restarts",
            ),
            PracticeStep(
                title="Assemble or repair a `kubeconfig` context cleanly",
                explanation="Use `set-cluster`, `set-credentials`, `set-context`, or `--kubeconfig=<path>` rather than hand-indentation mistakes.",
                command="k config --kubeconfig=/tmp/test.cfg set-cluster lab --server=https://127.0.0.1:6443 --certificate-authority=/etc/kubernetes/pki/ca.crt --embed-certs=true",
            ),
        ),
        debug_playbook=(
            DebugRow("`The connection to the server localhost:8080 was refused`", "`KUBECONFIG` unset or file missing at `~/.kube/config`", "Export `KUBECONFIG=/etc/kubernetes/admin.conf` or pass `--kubeconfig=...`"),
            DebugRow("`x509: certificate signed by unknown authority` on custom kubeconfig", "Wrong port (`6444` vs `6443`), wrong CA, or stale `insecure-skip-tls-verify`", "Verify `server: https://<ip>:6443` and CA data match `/etc/kubernetes/admin.conf`"),
            DebugRow("`error: error executing jsonpath` with dots in key name", "Labels like `node-role.kubernetes.io/control-plane` split at dots unescaped", "Wrap bracket key and escape dots: `{.metadata.labels['kubernetes\\.io/hostname']}`"),
        ),
        exam_trap=(
            "Note `--kubeconfig` edits ONLY that file, whereas `KUBECONFIG=file1:file2 k config view --flatten` prints secrets redacted UNLESS you add `--raw`! Missing `--raw` replaces all certs with `REDACTED`."
        ),
        cheatsheet=(
            CheatItem("Switch context", "k config use-context <context-name>", "Always run at start of every question"),
            CheatItem("Merge kubeconfigs w/ secrets", "KUBECONFIG=a.cfg:b.cfg k config view --flatten --raw > all.cfg", "`--raw` preserves private keys/certs"),
            CheatItem("Pin default namespace", "k config set-context --current --namespace=<ns>", "Saves `-n <ns>` keystrokes"),
            CheatItem("Node InternalIPs", "k get nodes -o jsonpath='{.items[*].status.addresses[?(@.type==\"InternalIP\")].address}'", "Standard CKA exam output query"),
            CheatItem("Loop JSONPath lines", "k get pv --sort-by=.spec.capacity.storage -o jsonpath='{range .items[*]}{.metadata.name}{\"\\n\"}{end}'", "One object per line"),
            CheatItem("Inspect any field offline", "k explain <kind>.spec --recursive | grep -C3 <term>", "Faster than docs search"),
        ),
        yaml_template=(
            "# Minimal kubeconfig anatomy (Cluster + User + Context)\n"
            "apiVersion: v1\n"
            "kind: Config\n"
            "current-context: dev@prod-cluster\n"
            "clusters:\n"
            "- name: prod-cluster\n"
            "  cluster:\n"
            "    certificate-authority-data: <base64-ca>\n"
            "    server: https://10.0.0.10:6443\n"
            "contexts:\n"
            "- name: dev@prod-cluster\n"
            "  context: { cluster: prod-cluster, namespace: apps, user: dev-user }\n"
            "users:\n"
            "- name: dev-user\n"
            "  user: { client-certificate-data: <b64>, client-key-data: <b64> }\n"
            "# Export isolated file cleanly: k --context=dev@prod-cluster config view --minify --raw > /tmp/dev.cfg"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="What three top-level blocks inside a `kubeconfig` are joined together by a `context` entry?",
                choices=(
                    "namespace, node, pod",
                    "cluster (`server` + CA), user (client creds), and optional default `namespace`",
                    "Deployment, Service, Ingress",
                    "CertificateSigningRequest, Role, Group",
                ),
                correct_index=1,
                explanation="A `context` maps one `cluster` entry + one `user` identity (+ optional default `namespace`), selected via `current-context`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You merge two kubeconfig files using `KUBECONFIG=a:b kubectl config view --flatten > out.cfg`, and `out.cfg` fails auth because certs say `DATA+OMITTED`. What flag was missing?",
                choices=(
                    "`--embed-certs`",
                    "`--raw`",
                    "`--minify`",
                    "`--unsafe-tls`",
                ),
                correct_index=1,
                explanation="`kubectl config view` redacts certificate/token bytes by default; passing `--raw` keeps base64 credentials intact.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Why does `kubectl get pods -o jsonpath='{.items[*].metadata.labels.app.kubernetes.io/part-of}'` return empty even when Pods carry that label?",
                choices=(
                    "jsonpath cannot read labels",
                    "Unescaped `.` dots are parsed as nested objects; dots in label keys require `['app\\.kubernetes\\.io/part-of']`",
                    "`*` only reads the first Pod",
                    "`custom-columns` must be enabled in kube-apiserver",
                ),
                correct_index=1,
                explanation="kubectl JSONPath splits on `.`, so keys containing dots or slashes must be quoted with escaped dots inside brackets.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-helm-lifecycle",
        order=7,
        domain=DOMAIN,
        title="Helm Releases: Repos, Values, Upgrade & Rollback",
        subtitle="Add repos, inspect defaults, template/validate charts, upgrade safely, and rollback failures.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-helm-upgrade", "ca-helm-rollback"),
        summary=(
            "Helm v3 manages versioned chart releases stored natively as Secrets in each release namespace. "
            "Master repo management (`helm repo add/update`, `search`), preflight (`helm show values`, `helm template`), "
            "upgrades (`-f` / `--set` / `--reuse-values`), and revision rollbacks (`helm history` + `helm rollback`)."
        ),
        architecture_flow=(
            "Chart Repo / Local Dir + Values (values.yaml -> -f custom.yaml -> --set) -> Rendered Manifests -> Release Secret (sh.helm.release.v1.<rel>.vN) -> Cluster"
        ),
        theory_points=(
            "Helm releases are namespace-scoped: ALWAYS pass `-n <ns>` on `install/upgrade/history/rollback/uninstall`, or `-A` on `helm list`.",
            "Values precedence (lowest to highest): chart `values.yaml` < `-f overrides.yaml` (later `-f` wins) < `--set key=val`.",
            "`helm upgrade` without `--reuse-values` or `-f` resets previous user `--set` overrides to chart defaults; use `--reuse-values` ONLY when bumping values incrementally without changing chart version.",
            "`helm template <rel> <chart> -f vals.yaml > rendered.yaml` renders pure Kubernetes manifests offline (useful when auditing CRDs or installing via `kubectl apply`).",
            "On `helm rollback <rel> <rev> -n <ns>`, `rev = 0` rolls back to the immediately preceding revision and bumps the history counter (`N+1`).",
        ),
        decision_matrix=(
            ComparisonRow("`helm template`", "Renders YAML locally without touching API server", "Generating manifests to inspect or apply with kubectl"),
            ComparisonRow("`helm upgrade --install`", "Creates release if missing, upgrades if already installed", "Idempotent exam installs & upgrades"),
            ComparisonRow("`-f custom.yaml` vs `--set k=v`", "Structured YAML file overrides vs inline CLI flag overrides", "Prefer `-f` for nested dicts/lists; `--set` for 1–2 scalars"),
            ComparisonRow("`helm rollback <rel> <rev>`", "Restores exact manifest snapshot of revision `<rev>`", "Fixing failed/broken chart upgrade in seconds"),
        ),
        docs_links=(
            StudyDocLink(
                label="Helm Using Helm Guide",
                url="https://helm.sh/docs/intro/using_helm/",
                exam_search_term="helm upgrade rollback",
            ),
            StudyDocLink(
                label="Helm Commands Reference",
                url="https://helm.sh/docs/helm/helm/",
                exam_search_term="helm show template",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Discover repos, releases across namespaces, and active values",
                explanation="Locate chart metadata, live user overrides, and Chart defaults before modifying anything.",
                command="helm list -A --all && helm get values cka-web -n cka-helm --all | head -n 30",
                verify_command="helm history cka-web -n cka-helm",
                expected_output="Revision table listing REVISION, UPDATED, STATUS, CHART, and APP VERSION",
            ),
            PracticeStep(
                title="Preview changes or upgrade a release cleanly",
                explanation="Use `helm show values` or `--dry-run --debug` when unsure about nested value keys.",
                command="helm upgrade --install cka-web assets/helm-chart -n cka-helm --create-namespace --set image.tag=1.27-alpine --set replicaCount=2",
                verify_command="helm status cka-web -n cka-helm && k -n cka-helm get deploy,pods",
                expected_output="STATUS: deployed; Pods Running with updated image & replicaCount=2",
            ),
            PracticeStep(
                title="Roll back a broken revision to last deployed state",
                explanation="Check `helm history` for last healthy `revision` (`deployed` or `superseded`) and roll back cleanly.",
                command="helm history cka-web -n cka-helm && helm rollback cka-web 1 -n cka-helm",
                verify_command="helm list -n cka-helm && k -n cka-helm rollout status deploy --all",
                expected_output="Release shows `deployed` at new incremented revision and Pods Ready",
            ),
        ),
        debug_playbook=(
            DebugRow("`Error: release: not found`", "Release lives in another namespace (or deleted) and `-n` was omitted", "Run `helm list -A --all` (includes `pending`/`failed` releases)"),
            DebugRow("`Error: another operation (install/upgrade/rollback) is in progress`", "Previous Helm job crashed leaving release Secret stuck in `pending-upgrade`", "Inspect `helm history`, then run `helm rollback <rel> <last-ok> -n <ns>`"),
            DebugRow("Upgrade loses prior `-f`/`--set` config", "Upgraded without passing original `-f` or `--reuse-values`", "Export old values with `helm get values <rel> -n <ns> > vals.yaml`, re-upgrade with `-f vals.yaml`"),
        ),
        exam_trap=(
            "Running `helm list` without `-A` hides releases outside `default`, AND installing Helm charts that ship CRDs when task says 'generate manifests via helm template' may omit CRDs unless you pass `--include-crds`!"
        ),
        cheatsheet=(
            CheatItem("Add & refresh repo", "helm repo add bitnami https://... && helm repo update", "Pulls latest chart index"),
            CheatItem("List all releases", "helm list -A --all", "Shows failed/pending releases too"),
            CheatItem("Inspect chart defaults", "helm show values <chart> > defaults.yaml", "Discover exact value keys"),
            CheatItem("Render YAML w/ CRDs", "helm template <rel> <chart> -n <ns> --include-crds > out.yaml", "Generates manifests without installing"),
            CheatItem("Upgrade w/ values", "helm upgrade --install <rel> <chart> -n <ns> -f vals.yaml --set k=v", "Applies overrides cleanly"),
            CheatItem("Rollback release", "helm rollback <rel> <rev> -n <ns>", "Use 0 for immediate prior revision"),
        ),
        yaml_template=(
            "# values-override.yaml (apply with: helm upgrade --install web repo/chart -n web -f values-override.yaml)\n"
            "replicaCount: 2\n"
            "image:\n"
            "  repository: nginx\n"
            "  tag: 1.27-alpine\n"
            "service:\n"
            "  type: ClusterIP\n"
            "  port: 80\n"
            "resources:\n"
            "  requests: { cpu: 50m, memory: 64Mi }\n"
            "  limits:   { cpu: 200m, memory: 128Mi }\n"
            "# Render w/ CRDs before install: helm template web repo/chart -n web --include-crds -f values-override.yaml"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Where does Helm v3 store revision history and rendered release state inside a Kubernetes cluster?",
                choices=(
                    "Inside a Tiller Pod in `kube-system`",
                    "As `sh.helm.release.v1.*` Secrets inside each release's target namespace",
                    "Inside `/etc/kubernetes/helm/` on worker nodes",
                    "Inside cluster-scoped PersistentVolumes",
                ),
                correct_index=1,
                explanation="Helm v3 removed Tiller and persists each release revision as a compressed Secret inside the release's own namespace.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="A release `api` in namespace `prod` failed at revision 4, while revision 2 was last healthy. Which command restores revision 2?",
                choices=(
                    "helm undo api 2 -n prod",
                    "helm rollback api 2 -n prod",
                    "helm rollout undo api --to-revision=2 -n prod",
                    "kubectl rollout undo release/api -n prod",
                ),
                correct_index=1,
                explanation="`helm rollback <RELEASE> [REVISION] -n <NAMESPACE>` restores revision 2's manifest state cleanly as revision 5.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Running `helm template my-app ./chart -n web` omits a CustomResourceDefinition shipped inside `chart/crds/`. Which flag includes CRDs in rendered output?",
                choices=(
                    "`--with-crds`",
                    "`--include-crds`",
                    "`--all-resources`",
                    "`--dry-run=server`",
                ),
                correct_index=1,
                explanation="`helm template` skips `crds/` by default; `--include-crds` emits CRDs together with the chart templates.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-kustomize-overlays",
        order=8,
        domain=DOMAIN,
        title="Kustomize Bases, Overlays, Patches & Apply `-k`",
        subtitle="Compose environment overrides cleanly with `kustomization.yaml`, generators, and `kubectl apply -k`.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("ca-kustomize-overlay",),
        summary=(
            "Kustomize ships built right into `kubectl` (`kubectl kustomize <dir>` and `kubectl apply -k <dir>`). "
            "Bases hold canonical manifests while `overlays/<env>/kustomization.yaml` inherits them via `resources:` and transforms "
            "`namespace:`, `labels:`, `images:`, `replicas:`, strategic/JSON6902 `patches:`, and hash-suffixed `configMapGenerator`."
        ),
        architecture_flow=(
            "base/ (Deployment + Service YAML) -> overlays/prod/kustomization.yaml (resources + patches + images + generators) -> kubectl kustomize | kubectl apply -k"
        ),
        theory_points=(
            "Always preview rendered output first via `k kustomize <dir>` before applying (`k apply -k <dir> --dry-run=server && k apply -k <dir>`).",
            "Modern `kustomize.config.k8s.io/v1beta1` replaces deprecated `bases:` with `resources:` and deprecated `patchesStrategicMerge:` with `patches:` (`path:` + optional `target:` for JSON 6902 patches).",
            "`namespace:` in `kustomization.yaml` injects `metadata.namespace` across namespaced resources AND updates RoleBinding/Service references cleanly.",
            "`configMapGenerator` / `secretGenerator` append a content hash suffix (`app-cfg-8t9c2k...`) automatically updating `Deployment` references to trigger zero-downtime ConfigMap rollouts.",
            "Quick transformers (`images:`, `replicas:`) save time compared to writing full patch files when only image tags or replica counts differ.",
        ),
        decision_matrix=(
            ComparisonRow("Strategic Merge Patch", "Partial YAML snippet matching structure + `kind/name`", "Adding/editing Pod container flags, env vars, or resources"),
            ComparisonRow("JSON 6902 Patch (`op/path/value`)", "Exact `target: {kind, name}` + array ops (`replace/add/remove`)", "Targeting exact array index (`ports/0`) or non-mergeable CRDs"),
            ComparisonRow("`images:` / `replicas:` transformers", "Built-in Kustomize scalar overrides in `kustomization.yaml`", "Fast tag bump or environment replica scaling without extra files"),
            ComparisonRow("`kubectl apply -f` vs `-k`", "`-f` applies raw files; `-k` compiles directory `kustomization.yaml`", "ALWAYS `-k` for Kustomize directories"),
        ),
        docs_links=(
            StudyDocLink(
                label="Declarative Management Using Kustomize",
                url="https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/",
                exam_search_term="Kustomize",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect directory layout and render full YAML preview",
                explanation="Verify base relative paths (`../../base`) and inspect compiled namespaces/images before apply.",
                command="ls -R assets/kustomize && k kustomize assets/kustomize/overlays/prod | head -n 45",
                verify_command="k kustomize assets/kustomize/overlays/prod | grep -E 'kind:|namespace:|image:'",
                expected_output="Rendered manifests display overlay namespace and updated image tag",
            ),
            PracticeStep(
                title="Author or tune overlay transformers & patches",
                explanation="Use declarative `resources:`, `images:`, `replicas:`, and `patches:` entries.",
                command="cat assets/kustomize/overlays/prod/kustomization.yaml",
                yaml_snippet=(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
                    "kind: Kustomization\n"
                    "namespace: catalog\n"
                    "resources:\n"
                    "- ../../base\n"
                    "replicas:\n"
                    "- name: web-app\n"
                    "  count: 3\n"
                    "images:\n"
                    "- name: nginx\n"
                    "  newTag: 1.27-alpine"
                ),
            ),
            PracticeStep(
                title="Validate server-side dry-run and apply with `-k`",
                explanation="Confirms OpenAPI schema + quota admission pass cleanly before mutating cluster state.",
                command="k apply -k assets/kustomize/overlays/prod --dry-run=server && k apply -k assets/kustomize/overlays/prod",
                verify_command="k -n catalog get deploy,svc,pods",
                expected_output="Deployment & Service exist in overlay namespace with target Ready replicas",
            ),
        ),
        debug_playbook=(
            DebugRow("`kubectl apply -f overlays/prod` fails `no matches for kind Kustomization`", "Passed `-f` instead of `-k` on a Kustomize folder", "Run `kubectl apply -k overlays/prod`"),
            DebugRow("`security/file outside root` error referencing `../shared`", "Newer Kustomize restricts loading raw files outside the directory tree without an intermediate base", "Keep shared files inside a parent `base/kustomization.yaml` referenced as `../../base`"),
            DebugRow("Strategic merge patch silently ignored on Deployment container", "Container `name:` or Deployment `metadata.name` didn't match base manifest", "Match exact base `metadata.name` + `containers[].name` keys in the patch"),
        ),
        exam_trap=(
            "Passing `kubectl apply -f overlays/prod` tries to send `kind: Kustomization` directly to the API server and errors immediately. Always use `kubectl apply -k <dir>` (and test with `kubectl kustomize <dir>` first)."
        ),
        cheatsheet=(
            CheatItem("Compile preview", "k kustomize <overlay-dir> > rendered.yaml", "Renders complete final YAML"),
            CheatItem("Server dry-run", "k apply -k <overlay-dir> --dry-run=server", "Validates against live cluster"),
            CheatItem("Apply overlay", "k apply -k <overlay-dir>", "Built-in Kustomize apply"),
            CheatItem("Delete overlay", "k delete -k <overlay-dir>", "Cleans up overlay resources"),
            CheatItem("Preview diff", "k diff -k <overlay-dir>", "Shows exact live cluster delta"),
        ),
        yaml_template=(
            "# overlays/prod/kustomization.yaml\n"
            "apiVersion: kustomize.config.k8s.io/v1beta1\n"
            "kind: Kustomization\n"
            "namespace: prod\n"
            "namePrefix: prod-\n"
            "resources:\n"
            "- ../../base\n"
            "configMapGenerator:\n"
            "- name: app-env\n"
            "  literals:\n"
            "  - LOG_LEVEL=warn\n"
            "patches:\n"
            "- path: replica-patch.yaml\n"
            "# Preview & apply: kubectl kustomize overlays/prod && kubectl apply -k overlays/prod"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why does a `configMapGenerator` in Kustomize append a short hash suffix (`app-env-7k9f8h2d4m`) to generated ConfigMaps?",
                choices=(
                    "To work around etcd 1KB key size limits",
                    "So Deployment Pod templates reference a new immutable name, triggering automatic rolling restarts on config changes",
                    "To prevent Service selectors from matching Pods",
                    "To make secrets readable by unauthenticated curl",
                ),
                correct_index=1,
                explanation="Standard ConfigMap edits don't restart Deployments automatically; changing the hashed name forces Pod templates to roll safely.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which command renders all transformed Kubernetes manifests from `overlays/prod/` to stdout without touching the cluster?",
                choices=(
                    "kubectl apply -k overlays/prod --output=yaml",
                    "kubectl kustomize overlays/prod",
                    "kubectl create -k overlays/prod --dry-run=client",
                    "kubectl explain kustomization",
                ),
                correct_index=1,
                explanation="`kubectl kustomize <dir>` compiles and prints all YAML objects so you can audit patches before applying.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You run `kubectl apply -f ./overlays/prod/` and get `error: resource mapping not found for name: \"\" namespace: \"\" from \"overlays/prod/kustomization.yaml\": no matches for kind \"Kustomization\"`. Why?",
                choices=(
                    "Kustomize requires Helm v3",
                    "`-f` feeds raw YAML to the API server; directories containing `kustomization.yaml` must use `-k`",
                    "`kind: Kustomization` needs `apiVersion: apps/v1`",
                    "Overriding replicas removes apiVersion headers",
                ),
                correct_index=1,
                explanation="Always pass `-k` (`kubectl apply -k <dir>`) rather than `-f` when working with Kustomize directories.",
            ),
        ),
    ),
    StudyTopic(
        id="ca-crds-operators",
        order=9,
        domain=DOMAIN,
        title="CRDs, Custom Resources, API Groups & Operators",
        subtitle="Inspect API extensions with `api-resources`/`explain`, validate OpenAPI schemas, and deploy CRs.",
        estimated_minutes=6,
        exam_frequency="High",
        archetype_ids=("ca-crd-inspect", "ca-crd-custom-resource"),
        summary=(
            "CustomResourceDefinitions (`apiextensions.k8s.io/v1`) extend `kube-apiserver` with new `Kind` resources validated by "
            "OpenAPI v3 structural schemas (`openAPIV3Schema`), while Operators/Controllers watch CRs and reconcile cluster state. "
            "On the exam, inspect CRDs directly via `kubectl api-resources`, `get crd`, and `kubectl explain <kind>.spec --recursive`."
        ),
        architecture_flow=(
            "Apply CRD (OpenAPI v3 Schema + Group/Versions + Scope) -> API Server registers endpoint -> Custom Controller/Operator watches CRs -> Create CR -> Reconcile Status"
        ),
        theory_points=(
            "Check `k api-resources --namespaced=true/false` and `k get crd` first to learn exact `GROUP`, `VERSION`, `SHORTNAMES`, and whether custom objects are `Namespaced` or `Cluster` scoped.",
            "`k explain <custom-kind>.spec --recursive` reads the CRD's OpenAPI schema live from the API server even when external docs lack that custom Operator.",
            "CRDs enforce structural schema validation (`openAPIV3Schema`) — unknown fields or wrong types (`string` vs `integer`) reject `kubectl apply` cleanly unless `additionalProperties` / `x-kubernetes-preserve-unknown-fields: true` allows them.",
            "Remember CRD `spec.versions[]` can serve multiple versions (`v1alpha1`, `v1`) with ONLY ONE version marked `storage: true`.",
            "Do NOT delete an active `CustomResourceDefinition` casually — deleting a CRD cascade-deletes every custom resource instance of that kind cluster-wide!",
        ),
        decision_matrix=(
            ComparisonRow("`kubectl get crd`", "Lists installed CustomResourceDefinition objects + groups", "Finding installed Gateway/Operator CRDs + versions"),
            ComparisonRow("`kubectl explain <kind>.spec --recursive`", "Prints full nested field tree + descriptions from OpenAPI schema", "Authoring/fixing Custom Resource YAML without guessing keys"),
            ComparisonRow("`scope: Namespaced` vs `Cluster`", "Lives inside a namespace (`-n`) vs cluster-wide root", "Preventing `namespaces may not be specified` errors on CRs"),
            ComparisonRow("Operator vs Static Manifest", "Controller loop actively reconciles drift, status, backups, upgrades", "Managing stateful/complex lifecycles (`cert-manager`, `envoy-gateway`, DBs)"),
        ),
        docs_links=(
            StudyDocLink(
                label="Extend the Kubernetes API with CustomResourceDefinitions",
                url="https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/",
                exam_search_term="CustomResourceDefinitions",
            ),
            StudyDocLink(
                label="Operator Pattern",
                url="https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
                exam_search_term="Operator pattern",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Discover CRDs, API groups, versions, and scope",
                explanation="Inspect installed custom resources, API group versions, and namespaced scope quickly.",
                command="k get crd && k api-resources --api-group=gateway.networking.k8s.io",
                verify_command="k get crd -o custom-columns=NAME:.metadata.name,GROUP:.spec.group,SCOPE:.spec.scope,VERSION:.spec.versions[0].name",
                expected_output="Prints CRD names alongside exact Group, Namespaced/Cluster scope, and served version",
            ),
            PracticeStep(
                title="Inspect OpenAPI v3 schema via `kubectl explain`",
                explanation="Read required fields, types, and sub-fields right from the terminal before creating or fixing any CR.",
                command="k explain httproute.spec --recursive | head -n 45",
            ),
            PracticeStep(
                title="Inspect or repair a Custom Resource and verify status",
                explanation="Always confirm both creation and operator status conditions (`Accepted`/`Ready`).",
                command="k get crd | awk 'NR>1 {print $1}' | head -n 5 && k api-versions | grep -E 'gateway|cert|storage'",
                verify_command="k explain <kind>.status",
                expected_output="Shows controller status condition fields reported by the CRD/Operator",
            ),
        ),
        debug_playbook=(
            DebugRow("`unknown field \"spec.foo\"` applying a CR", "CRD `openAPIV3Schema` rejects misspelled or obsolete API keys", "Run `k explain <kind>.spec --recursive` and fix exact key name/type"),
            DebugRow("CR hangs indefinitely in `Terminating` when deleting", "A finalizer (`metadata.finalizers`) waits on an uninstalled or broken Operator", "Inspect Operator Pod logs first; if Operator is permanently gone, patch finalizers cleanly if instructed"),
            DebugRow("Error `cluster-scoped resource must not have namespace`", "Applied a `-n` flag or `metadata.namespace` to a `scope: Cluster` CRD", "Omit `metadata.namespace` (confirm with `k api-resources --namespaced=false`)"),
        ),
        exam_trap=(
            "Before deleting a CRD during troubleshooting or cleanup, stop and verify — deleting a `CustomResourceDefinition` automatically destroys ALL custom resources (such as every `Certificate` or `HTTPRoute`) across the entire cluster."
        ),
        cheatsheet=(
            CheatItem("List all CRDs", "k get crd", "Installed API extensions"),
            CheatItem("Filter API group resources", "k api-resources --api-group=<group>", "Shows Kind, shortNames, namespaced"),
            CheatItem("Read full schema inline", "k explain <kind>.spec --recursive", "Live OpenAPI v3 field reference"),
            CheatItem("Check CRD served versions", "k get crd <name> -o jsonpath='{.spec.versions[*].name}'", "Spot valid `apiVersion`"),
            CheatItem("List all instances of CR", "k get <cr-kind> -A", "Find existing Custom Resources"),
        ),
        yaml_template=(
            "apiVersion: apiextensions.k8s.io/v1\n"
            "kind: CustomResourceDefinition\n"
            "metadata:\n"
            "  name: backups.ops.example.com\n"
            "spec:\n"
            "  group: ops.example.com\n"
            "  scope: Namespaced\n"
            "  names:\n"
            "    plural: backups\n"
            "    singular: backup\n"
            "    kind: Backup\n"
            "  versions:\n"
            "  - name: v1\n"
            "    served: true\n"
            "    storage: true"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="What happens immediately in Kubernetes if an administrator runs `kubectl delete crd httproutes.gateway.networking.k8s.io`?",
                choices=(
                    "Only future `HTTPRoute` creations are blocked; existing routes keep running",
                    "The API server deletes ALL existing `HTTPRoute` custom resources across every namespace alongside the CRD",
                    "Only CRDs in `default` are removed",
                    "etcd enters read-only maintenance mode",
                ),
                correct_index=1,
                explanation="Deleting a CRD removes its API endpoint and garbage-collects all instances of that Custom Resource cluster-wide.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which single command reveals the exact nested field structure and allowed types for an unfamiliar Custom Resource kind named `AlertRule`?",
                choices=(
                    "kubectl describe crd alertrules",
                    "kubectl explain alertrule.spec --recursive",
                    "kubectl api-versions --all",
                    "kubectl get alertrule --schema",
                ),
                correct_index=1,
                explanation="`kubectl explain <kind>.spec --recursive` reads the CRD's OpenAPIv3 structural schema directly from the live API server.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="A CRD YAML fails admission with `spec.versions: Invalid value: must have exactly one version marked as storage`. How do you fix it?",
                choices=(
                    "Set `storage: true` on ONE version entry and `storage: false` on any older served versions",
                    "Set `served: true` only on `v1alpha1`",
                    "Change `scope: Namespaced` to `Cluster`",
                    "Remove `names.plural` from the CRD",
                ),
                correct_index=0,
                explanation="A multi-version CRD may serve multiple versions (`served: true`), yet etcd can persist only ONE canonical storage version (`storage: true`).",
            ),
        ),
    ),
)
