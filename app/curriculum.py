"""CNCF CKA 2025/2026 curriculum catalog, neutral namespaces, and cohesive boss-fight blueprints."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app import config

NEUTRAL_NAMESPACES: tuple[str, ...] = (
    "checkout", "billing", "orders", "payments", "inventory", "catalog",
    "analytics", "telemetry", "auth-core", "edge-gw", "media-api", "search-svc",
    "shipping", "ledger", "reporting", "ingest", "portal", "notifications",
    "dispatch", "warehouse", "crm-api", "storefront", "audit-log", "metrics-app",
    "data-sync", "partner-gw", "core-api", "risk-engine", "pricing", "identity",
    "fulfillment", "invoices", "reviews", "sessions-app", "cart-svc", "gateway-edge",
)

DOMAIN_DOCS: dict[str, list[dict[str, str]]] = {
    "Troubleshooting": [
        {"label": "Troubleshoot Applications", "url": "https://kubernetes.io/docs/tasks/debug/debug-application/"},
        {"label": "Troubleshoot Clusters", "url": "https://kubernetes.io/docs/tasks/debug/debug-cluster/"},
    ],
    "Cluster Architecture, Installation & Configuration": [
        {"label": "Using RBAC Authorization", "url": "https://kubernetes.io/docs/reference/access-authn-authz/rbac/"},
        {"label": "Operating etcd clusters", "url": "https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/"},
    ],
    "Services & Networking": [
        {"label": "Service", "url": "https://kubernetes.io/docs/concepts/services-networking/service/"},
        {"label": "Network Policies", "url": "https://kubernetes.io/docs/concepts/services-networking/network-policies/"},
        {"label": "Gateway API", "url": "https://gateway.networking.k8s.io/"},
    ],
    "Workloads & Scheduling": [
        {"label": "Assigning Pods to Nodes", "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/"},
        {"label": "Deployments", "url": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/"},
    ],
    "Storage": [
        {"label": "Persistent Volumes", "url": "https://kubernetes.io/docs/concepts/storage/persistent-volumes/"},
        {"label": "Storage Classes", "url": "https://kubernetes.io/docs/concepts/storage/storage-classes/"},
    ],
}


@dataclass(frozen=True)
class Archetype:
    id: str
    domain: str
    subtopics: tuple[str, ...]
    difficulties: tuple[str, ...]
    example_seed: str
    guidance: str
    requires_addons: tuple[str, ...] = ()
    needs_node_ssh: bool = False
    destructive: bool = False
    required_kinds: tuple[str, ...] = ()
    required_check_types: tuple[str, ...] = ()
    required_keywords: tuple[str, ...] = ()
    anti_patterns: tuple[str, ...] = ()
    canonical_fast_commands: tuple[str, ...] = ()


ARCHETYPES: tuple[Archetype, ...] = (
    # ------------------------------------------------------------ Troubleshooting (9)
    Archetype(
        id="ts-crashloop-cmd",
        domain="Troubleshooting",
        subtopics=("CrashLoopBackOff", "containers", "command"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        guidance=(
            "Setup creates a Deployment with an invalid/exiting container command or args causing CrashLoopBackOff. "
            "Symptom describes failing Pod status/restarts without naming the command. "
            "Validate with deployment_rollout_ready + kubectl_jsonpath confirming image unchanged."
        ),
    ),
    Archetype(
        id="ts-image-pull",
        domain="Troubleshooting",
        subtopics=("ImagePullBackOff", "deployments", "troubleshooting"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-image-pull.json",
        guidance=(
            "Setup sets a nonexistent tag on an allowed arm64 image (e.g. nginx:1.27-missing). "
            "Task asks to restore workload using a specific pinned tag (e.g. nginx:1.27-alpine) without recreating the Deployment."
        ),
    ),
    Archetype(
        id="ts-readiness-probe",
        domain="Troubleshooting",
        subtopics=("readinessProbe", "livenessProbe", "endpoints"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-readiness-probe.json",
        guidance=(
            "Setup puts a Deployment Running but unready due to a failing readinessProbe path or port mismatch (plus optionally a Service with 0 endpoints). "
            "Validate with pod_status_ready and service_endpoints_ready."
        ),
    ),
    Archetype(
        id="ts-liveness-oom",
        domain="Troubleshooting",
        subtopics=("OOMKilled", "resources", "limits"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="wl-resources-too-high.json",
        guidance=(
            "Setup sets memory limit too tight (e.g. 8Mi for nginx or busybox stress) or bad probe initialDelaySeconds. "
            "Task specifies a target memory/CPU limit or healthy rollout without deleting the Deployment."
        ),
    ),
    Archetype(
        id="ts-configmap-env-broken",
        domain="Troubleshooting",
        subtopics=("ConfigMap", "envFrom", "CreateContainerConfigError"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        guidance=(
            "Setup mounts or references a missing/misnamed ConfigMap key in a Deployment causing CreateContainerConfigError. "
            "Solution creates/patches the ConfigMap and verifies deployment_rollout_ready."
        ),
    ),
    Archetype(
        id="ts-kubelet-down",
        domain="Troubleshooting",
        subtopics=("kubelet", "NotReady", "systemd"),
        difficulties=("exam_standard", "killer_hardcore", "boss_fight"),
        example_seed="ts-kubelet-node01.json",
        needs_node_ssh=True,
        guidance=(
            "Setup stops kubelet (or breaks /var/lib/kubelet/config.yaml with backup_paths) on node01/node02 via setup.node_commands. "
            "Solution restores kubelet via solution.node_commands. Validate with node_status_ready + node_command_exit_zero."
        ),
    ),
    Archetype(
        id="ts-static-pod-manifest",
        domain="Troubleshooting",
        subtopics=("static-pods", "kubelet", "controlplane"),
        difficulties=("killer_hardcore", "boss_fight"),
        example_seed="ts-kubelet-node01.json",
        needs_node_ssh=True,
        guidance=(
            "Setup adds or breaks a benign custom static Pod manifest in /etc/kubernetes/manifests/ on node01 or controlplane "
            "(NEVER break kube-apiserver unless destructive=true; prefer a custom static pod like web-static.yaml with wrong image/command and backup_paths). "
            "Validate with pod_status_ready in kube-system or host_file_contains."
        ),
    ),
    Archetype(
        id="ts-coredns-broken",
        domain="Troubleshooting",
        subtopics=("DNS", "Service", "CoreDNS"),
        difficulties=("killer_hardcore",),
        example_seed="sn-networkpolicy-dns.json",
        guidance=(
            "Create a scenario inside the scenario namespace where a client Pod cannot resolve a Service due to missing Service, "
            "wrong port/selector, or restrictive NetworkPolicy egress on UDP/TCP 53 — do NOT break cluster-wide kube-system CoreDNS in study mode."
        ),
    ),
    Archetype(
        id="ts-service-port-mismatch",
        domain="Troubleshooting",
        subtopics=("Service", "Endpoints", "targetPort"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="sn-service-targetport.json",
        guidance=(
            "Setup creates a Deployment + Service with wrong targetPort or selector, plus optionally a client Pod failing HTTP 200. "
            "Validate with service_endpoints_ready + pod_exec_exit_zero."
        ),
    ),
    Archetype(
        id="ts-crictl-container-debug",
        domain="Troubleshooting",
        subtopics=("crictl", "containerd", "logs", "nodes"),
        difficulties=("killer_hardcore",),
        example_seed="ts-kubelet-node01.json",
        needs_node_ssh=True,
        required_check_types=("host_file_contains", "node_command_exit_zero"),
        required_keywords=("crictl", "containerd", "kubelet"),
        guidance=(
            "Require inspecting running/exited containers or image/runtime status on node `node01` or `node02` via `crictl` over SSH, "
            "writing a clean verification artifact to `/opt/cka/<ns>/runtime-check.txt` (cleanup `rm -rf /opt/cka/<ns>`) or fixing containerd/kubelet issue."
        ),
    ),
    Archetype(
        id="ts-dns-search-ndots",
        domain="Troubleshooting",
        subtopics=("DNS", "dnsConfig", "ndots", "CoreDNS"),
        difficulties=("killer_hardcore",),
        example_seed="sn-networkpolicy-dns.json",
        required_keywords=("dns", "ndots", "dnsconfig", "nslookup"),
        guidance=(
            "Setup deploys a Pod/Deployment with a broken `dnsPolicy` (`None` without valid `dnsConfig` nameservers) or wrong cross-namespace FQDN, "
            "causing DNS lookup failures. Solution restores DNS resolution without touching cluster CoreDNS; validate via `pod_exec_exit_zero` (`nslookup`/`getent`)."
        ),
    ),
    Archetype(
        id="ts-initcontainer-blocking",
        domain="Troubleshooting",
        subtopics=("initContainers", "Pod", "Startup"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        required_keywords=("initcontainers",),
        guidance=(
            "Setup creates a Deployment stuck in `Init:0/1` or `Init:Error` because an `initContainer` waits for a non-existent Service name or runs a failing command. "
            "Fix the dependency or initContainer configuration; validate `deployment_rollout_ready` and preserve the main container image."
        ),
    ),
    Archetype(
        id="ts-multi-container-log-sidecar",
        domain="Troubleshooting",
        subtopics=("sidecar", "multi-container", "logs", "shared-volume"),
        difficulties=("killer_hardcore",),
        example_seed="ts-crashloop-fix.json",
        required_keywords=("emptydir", "volumeMounts", "mountpath"),
        guidance=(
            "Setup runs a multi-container Pod/Deployment (writer app + log-reader sidecar) sharing an `emptyDir` volume where the mount path or subPath mismatches. "
            "Solution aligns shared volume paths and validates sidecar sees app output via `pod_exec_exit_zero`."
        ),
    ),

    # ------------------------------------------------------------ Cluster Architecture (13)
    Archetype(
        id="ca-rbac-least-priv",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("RBAC", "ServiceAccount", "Role", "RoleBinding"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-rbac-pod-reader.json",
        guidance=(
            "Setup creates namespace + ServiceAccount (or leaves it for candidate). "
            "Validate both positive and negative permissions using kubectl_auth_can_i (expected_allowed: true and false)."
        ),
    ),
    Archetype(
        id="ca-rolebinding-subject",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("RBAC", "RoleBinding", "ServiceAccount"),
        difficulties=("exam_standard",),
        example_seed="ca-rolebinding-subject.json",
        guidance=(
            "Setup creates a RoleBinding bound to the wrong ServiceAccount. "
            "Validate old SA denied (expected_allowed: false) and target SA allowed (expected_allowed: true)."
        ),
    ),
    Archetype(
        id="ca-clusterrole-sa",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("ClusterRole", "ClusterRoleBinding", "RBAC"),
        difficulties=("killer_hardcore",),
        example_seed="ca-rbac-pod-reader.json",
        guidance=(
            "Require read-only cluster-wide access (e.g. nodes or persistentvolumes) for a namespaced ServiceAccount via ClusterRole + ClusterRoleBinding, "
            "using unique names including the scenario namespace so cluster-scoped cleanup works cleanly (add ClusterRole/ClusterRoleBinding delete in cleanup.commands)."
        ),
    ),
    Archetype(
        id="ca-etcd-snapshot-save",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("etcd", "backup", "etcdctl"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-etcd-snapshot-save.json",
        requires_addons=("etcdctl",),
        needs_node_ssh=True,
        guidance=(
            "Require saving an etcd snapshot on node `controlplane` using `/etc/kubernetes/pki/etcd/` certs to a unique path under `/opt/backup/<ns>-etcd.db`. "
            "Add `rm -f /opt/backup/<ns>-etcd.db` in cleanup.node_commands. Do NOT do etcd restore unless destructive=true."
        ),
    ),
    Archetype(
        id="ca-helm-upgrade",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("Helm", "upgrade", "values"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-helm-upgrade.json",
        requires_addons=("helm",),
        guidance=(
            "ALWAYS use the bundled local Helm chart path `assets/helm-chart` in setup.commands and solution.commands (NEVER invent external repos like bitnami or cka-lab!). "
            "Setup runs `helm upgrade --install <rel> assets/helm-chart -n <ns> --create-namespace`. "
            "Solution upgrades <rel> with `--set image.tag=1.27-alpine --set replicaCount=2`. Cleanup runs `helm uninstall <rel> -n <ns>`."
        ),
    ),
    Archetype(
        id="ca-helm-rollback",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("Helm", "rollback", "history"),
        difficulties=("killer_hardcore",),
        example_seed="ca-helm-upgrade.json",
        requires_addons=("helm",),
        guidance=(
            "Setup installs `assets/helm-chart` at rev 1 (working `image.tag=1.27-alpine`) and then upgrades to rev 2 with a broken tag (`image.tag=1.27-broken`). "
            "Task asks to rollback release to working revision; validate helm_release_state min_revision=3 + pod_status_ready."
        ),
    ),
    Archetype(
        id="ca-kustomize-overlay",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("Kustomize", "deployments", "configuration"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-rbac-pod-reader.json",
        required_keywords=("kustomize", "overlays", "assets/kustomize", "web-app"),
        guidance=(
            "Use the bundled local Kustomize overlay at `assets/kustomize/overlays/prod` (base: Deployment+Service `web-app`). "
            "Candidate applies `kubectl apply -n <ns> -k assets/kustomize/overlays/prod` (solution.commands supports `-k assets/kustomize/overlays/prod`) OR applies tuned rendered resources in `<ns>`. "
            "Validate deployment_rollout_ready (`min_ready_replicas: 2`) + service_endpoints_ready."
        ),
    ),
    Archetype(
        id="ca-crd-inspect",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("CRD", "Gateway API", "API resources"),
        difficulties=("exam_standard",),
        example_seed="ca-rbac-pod-reader.json",
        requires_addons=("gateway",),
        required_keywords=("crd", "customresourcedefinition", "api-resources", "gateway.networking.k8s.io"),
        guidance=(
            "Require inspecting installed CRDs / API resources (e.g., list Gateway API CRDs or inspect `httproutes.gateway.networking.k8s.io` fields) AND saving verifiable inspection findings "
            "or creating a scoped custom resource (`HTTPRoute`/`Gateway`) referencing them. Include a check that explicitly verifies the CRD/CR or saved artifact."
        ),
    ),
    Archetype(
        id="ca-crd-custom-resource",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("CRD", "CustomResource", "extensibility"),
        difficulties=("killer_hardcore",),
        example_seed="ca-rbac-pod-reader.json",
        required_kinds=("CustomResourceDefinition",),
        required_keywords=("customresourcedefinition", "crd"),
        guidance=(
            "Setup creates a lightweight unique namespaced CRD (group `<ns>.cka-arena.io`, clean it up in `cleanup.commands` with `kubectl delete crd ...`) plus a broken Custom Resource. "
            "Candidate fixes/creates a valid CR matching schema rules. Validate with `kubectl_resource_exists` and `kubectl_jsonpath` on the CR."
        ),
    ),
    Archetype(
        id="ca-csr-user-auth",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("CSR", "CertificateSigningRequest", "RBAC", "TLS"),
        difficulties=("killer_hardcore",),
        example_seed="ca-rbac-pod-reader.json",
        required_keywords=("certificatesigningrequest", "csr", "approve"),
        guidance=(
            "Setup creates a pending `CertificateSigningRequest` named `<ns>-dev-csr` (cleanup deletes CSR!) with `signerName: kubernetes.io/kube-apiserver-client` + Role in `<ns>`. "
            "Candidate approves the CSR and binds RBAC Role to the user. Validate `kubectl_jsonpath` CSR condition Approved/certificate not_empty + RBAC check."
        ),
    ),
    Archetype(
        id="ca-cert-expiry-inspect",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("TLS", "certificates", "kubeadm", "controlplane"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-etcd-snapshot-save.json",
        needs_node_ssh=True,
        required_check_types=("host_file_contains",),
        required_keywords=("kubeadm", "certs", "check-expiration", "openssl"),
        guidance=(
            "Require inspecting controlplane PKI certificate expiration via SSH on `controlplane` (`kubeadm certs check-expiration` or `openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -dates`) "
            "and writing the output or subject/expiry summary to `/opt/cka/<ns>/cert-expiry.txt` (cleanup removes `/opt/cka/<ns>`)."
        ),
    ),
    Archetype(
        id="ca-etcd-restore",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("etcd", "restore", "backup", "controlplane"),
        difficulties=("boss_fight",),
        example_seed="ca-etcd-snapshot-save.json",
        requires_addons=("etcdctl",),
        needs_node_ssh=True,
        destructive=True,
        required_keywords=("etcdctl", "snapshot"),
        guidance=(
            "Set `destructive: true`! Require backing up etcd and/or restoring an etcd snapshot to a dedicated data-dir on `controlplane` cleanly, updating `/etc/kubernetes/manifests/etcd.yaml` with `backup_paths` "
            "and restoring in cleanup. Only use when destructive cluster operations are explicitly allowed."
        ),
    ),
    Archetype(
        id="ca-kubeadm-node-upgrade",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("kubeadm", "upgrade", "drain", "cordon"),
        difficulties=("killer_hardcore", "boss_fight"),
        example_seed="ts-kubelet-node01.json",
        needs_node_ssh=True,
        destructive=True,
        required_keywords=("drain", "cordon", "kubelet", "kubeadm"),
        guidance=(
            "Set `destructive: true`! Practice safe worker maintenance: drain `node02` with `--ignore-daemonsets --delete-emptydir-data`, capture `kubeadm upgrade node` / version check on `node02`, and uncordon `node02`. "
            "Cleanup MUST `kubectl uncordon node02`."
        ),
    ),
    Archetype(
        id="ca-controlplane-static-pod-fix",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("kube-scheduler", "kube-controller-manager", "static-pods", "controlplane"),
        difficulties=("killer_hardcore", "boss_fight"),
        example_seed="ts-kubelet-node01.json",
        needs_node_ssh=True,
        destructive=True,
        required_keywords=("/etc/kubernetes/manifests", "kube-scheduler", "kube-controller-manager"),
        guidance=(
            "Set `destructive: true`! Break a non-apiserver control-plane static pod (`kube-scheduler.yaml` or `kube-controller-manager.yaml`) safely via `backup_paths`, "
            "e.g. an invalid CLI flag so Pods stay Pending/Controller fails to scale, and verify Deployment rollout succeeds once repaired."
        ),
    ),

    # ------------------------------------------------------------ Services & Networking (7)
    Archetype(
        id="sn-expose-clusterip",
        domain="Services & Networking",
        subtopics=("Service", "ClusterIP", "expose"),
        difficulties=("exam_standard",),
        example_seed="sn-expose-service.json",
        guidance=(
            "Setup runs a Deployment; task requires creating a ClusterIP Service exposing it on a specific port/targetPort. "
            "Validate with kubectl_resource_exists, service_endpoints_ready and pod_exec_exit_zero HTTP 200."
        ),
    ),
    Archetype(
        id="sn-service-selector",
        domain="Services & Networking",
        subtopics=("Service", "Endpoints", "labels"),
        difficulties=("exam_standard",),
        example_seed="sn-service-selector.json",
        guidance=(
            "Setup creates Deployment + Service whose selector mismatches Pod labels. "
            "Validate with service_endpoints_ready + pod_exec_exit_zero HTTP 200."
        ),
    ),
    Archetype(
        id="sn-service-targetport",
        domain="Services & Networking",
        subtopics=("Service", "targetPort", "ClusterIP"),
        difficulties=("exam_standard",),
        example_seed="sn-service-targetport.json",
        guidance=(
            "Setup creates Service with wrong targetPort (e.g. 8080 when container listens on 80). "
            "Validate targetPort via kubectl_jsonpath + pod_exec_exit_zero HTTP 200."
        ),
    ),
    Archetype(
        id="sn-nodeport-service",
        domain="Services & Networking",
        subtopics=("Service", "NodePort", "networking"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="sn-expose-service.json",
        guidance=(
            "Require exposing Deployment via NodePort (use a safe high port between 31000 and 32600 so it never collides). "
            "Validate type==NodePort, nodePort value, and service_endpoints_ready."
        ),
    ),
    Archetype(
        id="sn-networkpolicy-dns",
        domain="Services & Networking",
        subtopics=("NetworkPolicy", "DNS", "egress", "ingress"),
        difficulties=("killer_hardcore",),
        example_seed="sn-networkpolicy-dns.json",
        requires_addons=("network_policy",),
        guidance=(
            "Setup applies default-deny (Ingress + Egress) plus api Deployment, api-svc, client Pod, and intruder Pod (image curlimages/curl:8.10.1, sleep 3600). "
            "Include BOTH positive proof (client HTTP 200 + nslookup) and negative proof (intruder pod_exec_must_fail with curl --max-time 5)."
        ),
    ),
    Archetype(
        id="sn-networkpolicy-multi-ns",
        domain="Services & Networking",
        subtopics=("NetworkPolicy", "namespaceSelector", "podSelector"),
        difficulties=("killer_hardcore",),
        example_seed="sn-networkpolicy-dns.json",
        requires_addons=("network_policy",),
        guidance=(
            "Use two namespaces in setup.namespaces (e.g. `<ns>` and `<ns>-client`), label `<ns>-client` appropriately, "
            "and enforce namespaceSelector + podSelector Ingress rule with positive + negative pod_exec checks."
        ),
    ),
    Archetype(
        id="sn-gateway-httproute",
        domain="Services & Networking",
        subtopics=("Gateway API", "HTTPRoute", "routing"),
        difficulties=("killer_hardcore",),
        example_seed="sn-gateway-httproute.json",
        requires_addons=("gateway",),
        required_kinds=("HTTPRoute",),
        required_keywords=("httproute", "gateway"),
        guidance=(
            "Setup creates Gateway referencing existing GatewayClass `eg` (gateway.envoyproxy.io/gatewayclass-controller) + Deployment + Service. "
            "Validate HTTPRoute existence, hostnames/backendRefs, and condition Accepted==True (do NOT assert Programmed==True since kubeadm lacks cloud LoadBalancer IP)."
        ),
    ),
    Archetype(
        id="sn-ingress-to-gateway-migration",
        domain="Services & Networking",
        subtopics=("Gateway API", "Ingress", "HTTPRoute", "migration"),
        difficulties=("killer_hardcore",),
        example_seed="sn-gateway-httproute.json",
        requires_addons=("gateway",),
        required_kinds=("HTTPRoute",),
        required_keywords=("httproute", "gateway", "ingress"),
        guidance=(
            "Classic CKA 2025/2026 task: Setup has an existing `Ingress` manifest/object routing hostname+path to Service `<svc>` plus GatewayClass `eg`. "
            "Candidate creates a matching `Gateway` + `HTTPRoute` preserving identical hostnames, path prefixes and backend port while keeping existing Ingress intact if asked. Validate HTTPRoute + Accepted==True."
        ),
    ),
    Archetype(
        id="sn-gateway-canary-weights",
        domain="Services & Networking",
        subtopics=("Gateway API", "HTTPRoute", "traffic-splitting"),
        difficulties=("killer_hardcore",),
        example_seed="sn-gateway-httproute.json",
        requires_addons=("gateway",),
        required_kinds=("HTTPRoute",),
        required_keywords=("httproute", "weight", "backendrefs"),
        guidance=(
            "Setup deploys `v1-svc` and `v2-svc` plus Gateway `eg`. Task requires configuring an `HTTPRoute` splitting traffic with explicit weights (e.g. `weight: 80` to v1 and `weight: 20` to v2). "
            "Validate both `backendRefs[*].weight`, both services' `service_endpoints_ready`, and `HTTPRoute` condition `Accepted==True`."
        ),
    ),
    Archetype(
        id="sn-coredns-config-debug",
        domain="Services & Networking",
        subtopics=("CoreDNS", "Service", "DNS", "Headless"),
        difficulties=("killer_hardcore",),
        example_seed="sn-expose-service.json",
        required_keywords=("dns", "svc.cluster.local", "port 53"),
        guidance=(
            "Setup runs a backend + client Pod in `<ns>` where Service name/port or headless clusterIP (`None`) prevents expected SRV/A record resolution inside `<ns>`. "
            "Solution fixes the Service/Pod DNS configuration; validate `pod_exec_exit_zero` resolving FQDN via `nslookup` and HTTP 200."
        ),
    ),
    Archetype(
        id="sn-headless-service-dns",
        domain="Services & Networking",
        subtopics=("Headless Service", "clusterIP", "DNS", "StatefulSet"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="sn-expose-service.json",
        required_keywords=("clusterip: none", "clusterip"),
        guidance=(
            "Require exposing a multi-pod Deployment or StatefulSet via a headless Service (`clusterIP: None`) so per-pod DNS records resolve cleanly via `nslookup`. "
            "Validate `kubectl_jsonpath` `.spec.clusterIP == None`, `service_endpoints_ready`, and `pod_exec_exit_zero`."
        ),
    ),

    # ------------------------------------------------------------ Workloads & Scheduling (12)
    Archetype(
        id="wl-taint-toleration",
        domain="Workloads & Scheduling",
        subtopics=("taints", "tolerations", "scheduling"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="wl-taint-toleration.json",
        guidance=(
            "Setup taints node02 (`cka-arena/<ns>=locked:NoSchedule`) and pins Deployment with nodeSelector kubernetes.io/hostname=node02. "
            "IMPORTANT: cleanup.commands MUST remove the taint (`kubectl taint nodes node02 cka-arena/<ns>=locked:NoSchedule-`). "
            "Validate pod_status_ready + kubectl_jsonpath confirming nodeSelector preserved."
        ),
    ),
    Archetype(
        id="wl-node-affinity",
        domain="Workloads & Scheduling",
        subtopics=("nodeAffinity", "scheduling", "labels"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="wl-taint-toleration.json",
        guidance=(
            "Setup pins Deployment with requiredDuringSchedulingIgnoredDuringExecution nodeAffinity on key kubernetes.io/hostname or custom node label. "
            "If using a custom node label, clean it up in cleanup.commands (`kubectl label node node01 <key>-`). "
            "Validate with pod_status_ready + LIST-mode kubectl_jsonpath `{.items[*].spec.nodeName}` with operator `all_match`."
        ),
    ),
    Archetype(
        id="wl-resources-cpu",
        domain="Workloads & Scheduling",
        subtopics=("resources", "requests", "limits", "scheduler"),
        difficulties=("exam_standard",),
        example_seed="wl-resources-too-high.json",
        guidance=(
            "Setup creates Deployment requesting impossible CPU (e.g. `cpu: 16`) so Pod stays Pending Unschedulable. "
            "Solution lowers request to e.g. `100m`; validate deployment_rollout_ready + kubectl_jsonpath on requests.cpu."
        ),
    ),
    Archetype(
        id="wl-native-sidecar",
        domain="Workloads & Scheduling",
        subtopics=("initContainers", "sidecar", "shared-volume"),
        difficulties=("killer_hardcore",),
        example_seed="ts-crashloop-fix.json",
        guidance=(
            "Create a Pod or Deployment using a Kubernetes 1.29+ native sidecar (`initContainers` entry with `restartPolicy: Always`) sharing an `emptyDir` volume with the main container "
            "(e.g. sidecar writes content or health file and main container serves/reads it). Validate pod_status_ready + kubectl_jsonpath on initContainers[0].restartPolicy == Always."
        ),
    ),
    Archetype(
        id="wl-daemonset-controlplane",
        domain="Workloads & Scheduling",
        subtopics=("DaemonSet", "tolerations", "control-plane"),
        difficulties=("killer_hardcore",),
        example_seed="wl-taint-toleration.json",
        guidance=(
            "Create or fix a DaemonSet in `<ns>` so it schedules Pods on ALL 3 nodes including `controlplane` (requires toleration for `node-role.kubernetes.io/control-plane:NoSchedule`). "
            "Validate pod_status_ready min_ready=3 + LIST-mode `{.items[*].spec.nodeName}` contains `controlplane`."
        ),
    ),
    Archetype(
        id="wl-cronjob-policy",
        domain="Workloads & Scheduling",
        subtopics=("Job", "CronJob", "completions"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        guidance=(
            "Create or fix a Job/CronJob (e.g. concurrencyPolicy, backoffLimit, successfulJobsHistoryLimit, restartPolicy: Never/OnFailure with busybox command `echo ok`). "
            "Validate with kubectl_resource_exists + kubectl_jsonpath (do NOT use pod_status_ready on completed Jobs since Succeeded pods are not Ready!)."
        ),
    ),
    Archetype(
        id="wl-resource-quota",
        domain="Workloads & Scheduling",
        subtopics=("ResourceQuota", "LimitRange", "Deployments"),
        difficulties=("killer_hardcore",),
        example_seed="wl-resources-too-high.json",
        guidance=(
            "Setup creates a ResourceQuota (e.g. pods: '4', requests.cpu: '500m') and a Deployment that fails ReplicaSet creation because it lacks requests or exceeds quota. "
            "Validate deployment_rollout_ready + ResourceQuota still exists."
        ),
    ),
    Archetype(
        id="wl-hpa-autoscale",
        domain="Workloads & Scheduling",
        subtopics=("HPA", "HorizontalPodAutoscaler", "autoscaling", "metrics-server"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="wl-resources-too-high.json",
        requires_addons=("metrics-server",),
        required_kinds=("HorizontalPodAutoscaler",),
        required_keywords=("horizontalpodautoscaler", "minreplicas", "maxreplicas"),
        guidance=(
            "Setup creates a Deployment with explicit `resources.requests.cpu` (e.g. 50m). Task asks to create or fix an `HorizontalPodAutoscaler` targeting `minReplicas`/`maxReplicas` and average CPU utilization (e.g. `50%`). "
            "Validate HPA exists, `.spec.minReplicas`, `.spec.maxReplicas`, and `.spec.scaleTargetRef.name`."
        ),
    ),
    Archetype(
        id="wl-rollout-undo-strategy",
        domain="Workloads & Scheduling",
        subtopics=("Deployment", "rollingUpdate", "rollback", "strategy"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        required_keywords=("rollingupdate", "maxsurge", "maxunavailable"),
        guidance=(
            "Setup creates a Deployment with `strategy.rollingUpdate` misconfigured or broken image in rev 2 (e.g. via `setup.manifests` + `setup.commands` `kubectl set image` to broken tag). "
            "Candidate rolls back or updates image & rollingUpdate parameters (`maxUnavailable`, `maxSurge`). Validate `deployment_rollout_ready` + strategy jsonpath."
        ),
    ),
    Archetype(
        id="wl-statefulset-headless",
        domain="Workloads & Scheduling",
        subtopics=("StatefulSet", "Headless", "ordered-pods"),
        difficulties=("killer_hardcore",),
        example_seed="st-pod-wrong-claim.json",
        required_kinds=("StatefulSet",),
        required_keywords=("statefulset", "servicename"),
        guidance=(
            "Setup creates a broken StatefulSet (missing headless Service or wrong `serviceName` / bad probe or tight resources). "
            "Do NOT use dynamic PVCs without `local-path` Pod ready; prefer `emptyDir` or explicit PVs (`pv-<ns>-0`, cleaned up in cleanup.commands) and validate `pod_status_ready min_ready=2` + ordered pod names (`-0`, `-1`)."
        ),
    ),
    Archetype(
        id="wl-pdb-priorityclass",
        domain="Workloads & Scheduling",
        subtopics=("PodDisruptionBudget", "PriorityClass", "resilience"),
        difficulties=("killer_hardcore",),
        example_seed="wl-resources-too-high.json",
        required_kinds=("PodDisruptionBudget",),
        required_keywords=("poddisruptionbudget", "minavailable"),
        guidance=(
            "Require creating a `PodDisruptionBudget` (`minAvailable` or `maxUnavailable`) matching a multi-replica Deployment's labels in `<ns>` so availability is protected during drains, "
            "and/or creating a uniquely named `PriorityClass` (`pc-<ns>` cleaned in `cleanup.commands`). Validate `kubectl_resource_exists`, selector match and `deployment_rollout_ready`."
        ),
    ),
    Archetype(
        id="wl-pod-antiaffinity-topology",
        domain="Workloads & Scheduling",
        subtopics=("podAntiAffinity", "topologySpreadConstraints", "HA"),
        difficulties=("killer_hardcore",),
        example_seed="wl-taint-toleration.json",
        required_keywords=("topologykey", "podantiaffinity", "topologyspreadconstraints"),
        guidance=(
            "Require scheduling 2 replicas of Deployment `<name>` across DIFFERENT worker nodes (`node01` and `node02`) using `podAntiAffinity` or `topologySpreadConstraints` (`topologyKey: kubernetes.io/hostname`). "
            "Validate `deployment_rollout_ready min_ready_replicas=2` and check Pod `.items[*].spec.nodeName` includes multiple distinct nodes."
        ),
    ),
    Archetype(
        id="wl-securitycontext-nonroot",
        domain="Workloads & Scheduling",
        subtopics=("SecurityContext", "runAsNonRoot", "capabilities"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        required_keywords=("securitycontext", "runasuser", "allowprivilegeescalation"),
        guidance=(
            "Require hardening a Deployment/Pod using `busybox:1.36` (`command: [\"sh\", \"-c\", \"sleep 3600\"]`) with `runAsNonRoot: true`, explicit UID (`runAsUser: 1000`), `allowPrivilegeEscalation: false`, and `capabilities.drop: [ALL]`. "
            "Avoid nginx:1.27-alpine binding privileged port 80 when non-root (`busybox:1.36` sleeping or custom high port works cleanly!)."
        ),
    ),

    # ------------------------------------------------------------ Storage (8)
    Archetype(
        id="st-pv-claimref",
        domain="Storage",
        subtopics=("PersistentVolume", "PersistentVolumeClaim", "claimRef"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pv-claimref.json",
        guidance=(
            "ALWAYS name the PersistentVolume uniquely using the namespace (e.g. `pv-<ns>`), and delete `pv-<ns>` in cleanup.commands! "
            "Setup creates `pv-<ns>` with stale claimRef + `pvc-data` Pending + Deployment mounting `pvc-data`. Validate with pvc_bound + deployment_rollout_ready."
        ),
    ),
    Archetype(
        id="st-pod-wrong-claim",
        domain="Storage",
        subtopics=("Pod", "PersistentVolumeClaim", "volumes"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pod-wrong-claim.json",
        guidance=(
            "Pod `spec.volumes` is immutable! Setup creates `pv-<ns>`, `pvc-data`, and Pod referencing `pvc-missing`. "
            "Solution MUST delete Pod and recreate it via `solution.manifests` (cleanup deletes `pv-<ns>`). Validate pvc_bound + pod_status_ready."
        ),
    ),
    Archetype(
        id="st-pvc-local-path",
        domain="Storage",
        subtopics=("StorageClass", "PersistentVolumeClaim", "local-path"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pod-wrong-claim.json",
        requires_addons=("local-path",),
        guidance=(
            "Remember StorageClass `local-path` has volumeBindingMode=WaitForFirstConsumer: a PVC using `local-path` stays Pending until a schedulable Pod mounts it! "
            "Do NOT put `pvc_bound` check without a running Pod/Deployment mounting it."
        ),
    ),
    Archetype(
        id="st-pvc-storageclass-mismatch",
        domain="Storage",
        subtopics=("StorageClass", "PersistentVolume", "PersistentVolumeClaim"),
        difficulties=("killer_hardcore",),
        example_seed="st-pv-claimref.json",
        guidance=(
            "Setup creates `pv-<ns>` (`storageClassName: manual-<ns>`) and `pvc-data` requesting wrong storageClassName (`fast-ssd`) + Pod mounting it. "
            "PVC `spec.storageClassName` is IMMUTABLE: solution MUST `kubectl delete pvc` and recreate via `solution.manifests` (do NOT patch PVC!)."
        ),
    ),
    Archetype(
        id="st-configmap-subpath-volume",
        domain="Storage",
        subtopics=("ConfigMap", "volumes", "mountPath"),
        difficulties=("exam_standard",),
        example_seed="ts-crashloop-fix.json",
        guidance=(
            "Setup creates ConfigMap with custom HTML/config and a Deployment missing volumeMount or using wrong key/path. "
            "Validate with pod_status_ready + pod_exec_exit_zero checking mounted file or HTTP response."
        ),
    ),
    Archetype(
        id="st-pvc-expansion",
        domain="Storage",
        subtopics=("PVC", "StorageClass", "allowVolumeExpansion", "resize"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pv-claimref.json",
        requires_addons=("local-path",),
        required_keywords=("allowvolumeexpansion", "storage"),
        guidance=(
            "Require creating a uniquely named StorageClass `sc-<ns>` (provisioner `rancher.io/local-path` or `kubernetes.io/no-provisioner`, `allowVolumeExpansion: true`, cleaned in `cleanup.commands`!) or increasing a PVC's `.spec.resources.requests.storage` request cleanly "
            "on an explicit matching PV+PVC (`pv-<ns>` updated with sufficient capacity) so the spec change succeeds cleanly."
        ),
    ),
    Archetype(
        id="st-reclaim-policy-retain",
        domain="Storage",
        subtopics=("PersistentVolume", "persistentVolumeReclaimPolicy", "Retain"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pv-claimref.json",
        required_keywords=("retain", "persistentvolumereclaimpolicy"),
        guidance=(
            "Setup creates unique PV `pv-<ns>` with `persistentVolumeReclaimPolicy: Delete` bound to `pvc-data` + Pod mounting it. "
            "Task requires ensuring data safety by setting `persistentVolumeReclaimPolicy: Retain` on `pv-<ns>` without deleting existing bound workload/PVC (cleanup deletes `pv-<ns>`)."
        ),
    ),
    Archetype(
        id="st-secret-volume-permissions",
        domain="Storage",
        subtopics=("Secret", "defaultMode", "readOnly", "volumes"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ts-crashloop-fix.json",
        required_keywords=("secret", "defaultmode", "readonly"),
        guidance=(
            "Require mounting an existing Secret `<name>` at a fixed container path with `readOnly: true` and strict octal permissions (`defaultMode: 256` / `0400`) inside a Deployment/Pod. "
            "Validate via `deployment_rollout_ready`, `kubectl_jsonpath`, and `pod_exec_exit_zero` inspecting mounted secret permissions/content."
        ),
    ),
    # ------------------------------------------------------------ Phase 4 High-Yield Expansion (+8 -> 67)
    Archetype(
        id="ca-kubeadm-node-drain",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("drain", "cordon", "maintenance", "uncordon"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-kubeadm-node-drain.json",
        needs_node_ssh=True,
        destructive=True,
        required_kinds=("Deployment",),
        required_keywords=("drain", "node02"),
        guidance=(
            "Opt-in maintenance lab: cordon and safely drain `node02` (--ignore-daemonsets --delete-emptydir-data) so Deployment workloads reschedule cleanly, "
            "run a marker on `node02`, and uncordon `node02` back to Ready/schedulable."
        ),
    ),
    Archetype(
        id="ca-user-kubeconfig-context",
        domain="Cluster Architecture, Installation & Configuration",
        subtopics=("kubeconfig", "context", "auth", "RBAC"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="ca-csr-user-auth.json",
        required_keywords=("kubeconfig", "context"),
        guidance=(
            "Create or inspect a ServiceAccount token / kubeconfig context with Role-scoped access and verify allowed and denied actions via `kubectl_auth_can_i`."
        ),
    ),
    Archetype(
        id="wl-pod-node-selector-hostname",
        domain="Workloads & Scheduling",
        subtopics=("nodeSelector", "scheduling", "Deployment"),
        difficulties=("exam_standard",),
        example_seed="wl-taint-toleration.json",
        required_kinds=("Deployment",),
        required_keywords=("nodeselector",),
        guidance=(
            "Schedule Pods of a Deployment onto a specific labeled worker node using `spec.template.spec.nodeSelector` and verify Pod placement via LIST `kubectl_jsonpath` `{.items[*].spec.nodeName}`."
        ),
    ),
    Archetype(
        id="wl-job-backoff-completions",
        domain="Workloads & Scheduling",
        subtopics=("Job", "completions", "parallelism", "backoffLimit"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="wl-cronjob-policy.json",
        required_kinds=("Job",),
        required_keywords=("job", "completions"),
        guidance=(
            "Create or fix a batch `Job` with explicit `completions`, `parallelism`, and `backoffLimit` and verify `status.succeeded`."
        ),
    ),
    Archetype(
        id="sn-gateway-tls-header-route",
        domain="Services & Networking",
        subtopics=("Gateway API", "HTTPRoute", "headers", "path"),
        difficulties=("killer_hardcore",),
        example_seed="sn-gateway-canary-weights.json",
        requires_addons=("gateway",),
        required_kinds=("HTTPRoute", "Service"),
        required_keywords=("httproute",),
        guidance=(
            "Configure an `HTTPRoute` under an existing `Gateway` (`gatewayClassName: eg`) matching a path prefix or HTTP request header to route traffic to a backend Service."
        ),
    ),
    Archetype(
        id="sn-networkpolicy-egress-cidr",
        domain="Services & Networking",
        subtopics=("NetworkPolicy", "egress", "ipBlock", "DNS"),
        difficulties=("killer_hardcore",),
        example_seed="sn-networkpolicy-dns.json",
        requires_addons=("network_policy",),
        required_kinds=("NetworkPolicy",),
        required_keywords=("networkpolicy", "egress"),
        guidance=(
            "Restrict Pod egress with a `NetworkPolicy` combining DNS (`kube-system` port 53) and explicit `ipBlock` CIDR or namespace/pod rules; validate with `pod_exec_exit_zero` and `pod_exec_must_fail`."
        ),
    ),
    Archetype(
        id="st-emptydir-shared-volume",
        domain="Storage",
        subtopics=("emptyDir", "multi-container", "volumes", "Shared"),
        difficulties=("exam_standard",),
        example_seed="st-pvc-local-path.json",
        required_kinds=("Pod",),
        required_keywords=("emptydir",),
        guidance=(
            "Create a multi-container Pod sharing an `emptyDir` volume where container 1 writes logs/data and container 2 reads/serves it; verify via `pod_exec_exit_zero`."
        ),
    ),
    Archetype(
        id="ts-pvc-pending-storageclass",
        domain="Troubleshooting",
        subtopics=("PersistentVolumeClaim", "StorageClass", "Pending", "troubleshooting"),
        difficulties=("exam_standard", "killer_hardcore"),
        example_seed="st-pvc-local-path.json",
        requires_addons=("local-path",),
        required_kinds=("PersistentVolumeClaim", "Deployment"),
        required_keywords=("local-path", "pvc"),
        guidance=(
            "Troubleshoot a Pending Pod whose PVC references a nonexistent `StorageClass`; recreate the PVC with `local-path` and verify Pod Bound + Running."
        ),
    ),
)

ARCHETYPES_BY_ID: dict[str, Archetype] = {a.id: a for a in ARCHETYPES}


@dataclass(frozen=True)
class CausalIncidentBlueprint:
    id: str
    domain: str
    title_theme: str
    subtopics: tuple[str, ...]
    requires_addons: tuple[str, ...]
    guidance: str
    example_seed: str
    primary_archetype_id: str | None = None
    required_kinds: tuple[str, ...] = ()
    required_check_types: tuple[str, ...] = ()


CAUSAL_INCIDENTS: tuple[CausalIncidentBlueprint, ...] = (
    CausalIncidentBlueprint(
        id="inc-node-workload-svc",
        domain="Troubleshooting",
        title_theme="Node kubelet outage + pinned workload + Service targetPort",
        subtopics=("kubelet", "Service", "scheduling", "troubleshooting"),
        requires_addons=(),
        example_seed="ts-kubelet-node01.json",
        primary_archetype_id="ts-kubelet-down",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node01`: "
            "(1) `kubelet` on `node01` is stopped via setup.node_commands (`systemctl stop kubelet`), causing Pod of Deployment `api` (pinned to `node01` via nodeSelector) to remain Pending/Unscheduled; "
            "(2) Deployment `api` ALSO has a broken container command or wrong image tag so once `node01` recovers it enters CrashLoopBackOff/ImagePullBackOff unless fixed; "
            "(3) Service `api-svc` in `<ns>` has wrong targetPort (`8080` instead of `80`); "
            "(4) Check HTTP 200 through `api-svc` via ephemeral_probe + node_status_ready(node01) + node_command_exit_zero(systemctl is-active kubelet). "
            "All solution steps belong to restoring THIS single application end-to-end!"
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-node-netpol-dns",
        domain="Services & Networking",
        title_theme="Node kubelet + Service selector + default-deny NetworkPolicy with DNS egress",
        subtopics=("kubelet", "NetworkPolicy", "DNS", "Service"),
        requires_addons=("network_policy",),
        example_seed="sn-networkpolicy-dns.json",
        primary_archetype_id="sn-networkpolicy-dns",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node02`: "
            "(1) `kubelet` on `node02` is stopped via setup.node_commands (`systemctl stop kubelet`), stalling `client` / `backend` Pods pinned to `node02`; "
            "(2) Service `backend-svc` has a mismatched selector (`app: wrong`); "
            "(3) `default-deny` NetworkPolicy blocks ingress/egress in `<ns>`: candidate must allow `client` -> `backend` on port 80 AND DNS egress to `kube-system` UDP/TCP 53 while keeping `intruder` blocked (`pod_exec_must_fail` with curl --max-time 5). "
            "Make sure `solution.node_commands` starts `kubelet` on `node02` and cleanup also runs `systemctl start kubelet` on `node02`."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-node-storage-rbac",
        domain="Storage",
        title_theme="Node disk/kubelet + blocked PV claimRef + ServiceAccount RBAC",
        subtopics=("PersistentVolume", "PersistentVolumeClaim", "RBAC", "kubelet"),
        requires_addons=(),
        example_seed="st-pv-claimref.json",
        primary_archetype_id="st-pv-claimref",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node01`: "
            "(1) `kubelet` on `node01` is stopped via setup.node_commands (`systemctl stop kubelet`); "
            "(2) Cluster-scoped PV `pv-<ns>` (remember to delete it in cleanup.commands!) has a stale `claimRef` blocking PVC `data-pvc` in `<ns>`, while Deployment `store` (pinned to `node01`, mounting `data-pvc`) fails to start; "
            "(3) ServiceAccount `store-ops` in `<ns>` has a broken RoleBinding pointing to `wrong-sa` instead of `store-ops`. "
            "Validate node_status_ready, pvc_bound, deployment_rollout_ready, and kubectl_auth_can_i (both allowed and denied)."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-node-helm-gateway",
        domain="Cluster Architecture, Installation & Configuration",
        title_theme="Node recovery + Helm upgrade + Gateway API HTTPRoute",
        subtopics=("Helm", "Gateway API", "HTTPRoute", "kubelet"),
        requires_addons=("helm", "gateway"),
        example_seed="ca-helm-upgrade.json",
        primary_archetype_id="ca-helm-upgrade",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node01`: "
            "(1) `kubelet` on `node01` is stopped via setup.node_commands; "
            "(2) Helm release `web-rel` in `<ns>` was installed from local chart `assets/helm-chart` with defaults (1 replica, wrong tag) and needs upgrade to `image.tag=1.27-alpine`, `replicaCount=2`; "
            "(3) Gateway `edge` (gatewayClassName `eg`) exists in `<ns>` and needs HTTPRoute `web-route` forwarding hostname `app.<ns>.example.com` to Service `web-rel` port 80. "
            "Cleanup must run `helm uninstall web-rel -n <ns>` and `systemctl start kubelet` on `node01`."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-node-daemonset-taint",
        domain="Workloads & Scheduling",
        title_theme="Node kubelet + Taint/Toleration + Native Sidecar + Service",
        subtopics=("taints", "tolerations", "initContainers", "kubelet"),
        requires_addons=(),
        example_seed="wl-taint-toleration.json",
        primary_archetype_id="wl-taint-toleration",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node02`: "
            "(1) `kubelet` on `node02` is stopped via setup.node_commands AND `node02` has taint `cka-arena/<ns>=dedicated:NoSchedule` (cleanup MUST untaint `node02`!); "
            "(2) Deployment `worker` in `<ns>` is pinned to `node02`, lacks the toleration, and has a broken `resources.requests.cpu: 16`; "
            "(3) Service `worker-svc` has wrong selector so endpoints stay 0. "
            "Validate node_status_ready, deployment_rollout_ready, service_endpoints_ready, and pod_exec_exit_zero HTTP 200."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-etcd-backup-rbac-app",
        domain="Cluster Architecture, Installation & Configuration",
        title_theme="Control-plane static file/etcd backup + broken workload + RBAC",
        subtopics=("etcd", "RBAC", "ConfigMap", "troubleshooting"),
        requires_addons=("etcdctl",),
        example_seed="ca-etcd-snapshot-save.json",
        primary_archetype_id="ca-etcd-snapshot-save",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `controlplane`: "
            "(1) Setup writes a service configuration file `/opt/cka/<ns>/config.env` on `controlplane` via setup.node_commands (using `mkdir -p` and cleanup `rm -rf /opt/cka/<ns>`) OR stops kubelet on `node01`; "
            "(2) Candidate must save an etcd snapshot on `controlplane` to `/opt/backup/<ns>-etcd.db` (cleanup deletes `/opt/backup/<ns>-etcd.db`); "
            "(3) Fix Deployment `api` in `<ns>` (missing ConfigMap key `APP_MODE=prod`) and fix RoleBinding for ServiceAccount `api-auditor` in `<ns>`. "
            "Validate etcd snapshot (`node_command_exit_zero` + `host_file_contains`), `deployment_rollout_ready`, and `kubectl_auth_can_i`."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-workloads-hpa-pdb-node",
        domain="Workloads & Scheduling",
        title_theme="Node recovery + ResourceQuota/HPA + PodDisruptionBudget",
        subtopics=("HPA", "ResourceQuota", "PodDisruptionBudget", "kubelet"),
        requires_addons=("metrics-server",),
        example_seed="wl-resources-too-high.json",
        primary_archetype_id="wl-resources-cpu",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node01`: "
            "(1) `kubelet` on `node01` is stopped via setup.node_commands (`systemctl stop kubelet`); "
            "(2) Deployment `api` in `<ns>` (pinned or spread across workers) lacks CPU requests under an active ResourceQuota, preventing scale-up to 2 replicas; "
            "(3) Create an `HorizontalPodAutoscaler` (`minReplicas: 2`, `maxReplicas: 4`) and a `PodDisruptionBudget` (`minAvailable: 1`) for `api`; "
            "(4) Validate `node_status_ready(node01)`, `deployment_rollout_ready(min=2)`, HPA and PDB in `<ns>`."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-storage-stateful-secret-node",
        domain="Storage",
        title_theme="Node kubelet + StatefulSet PV binding + Secret readOnly mount",
        subtopics=("StatefulSet", "PersistentVolume", "Secret", "kubelet"),
        requires_addons=(),
        example_seed="st-pod-wrong-claim.json",
        primary_archetype_id="st-pod-wrong-claim",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node02`: "
            "(1) `kubelet` on `node02` is stopped via setup.node_commands; "
            "(2) Deployment `db-api` mounts Secret `db-creds` with wrong key/missing volume AND references broken PVC `pvc-data` mismatched with `pv-<ns>` (`claimRef` stale); "
            "(3) Solution recovers `node02`, unblocks `pv-<ns>` -> `pvc-data`, fixes Secret mount `readOnly: true`, and achieves Service endpoints ready. Cleanup starts kubelet on `node02` and deletes `pv-<ns>`."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-services-gateway-canary-node",
        domain="Services & Networking",
        title_theme="Node recovery + Service endpoints + Gateway HTTPRoute weight split",
        subtopics=("Gateway API", "HTTPRoute", "Service", "kubelet"),
        requires_addons=("gateway",),
        example_seed="sn-gateway-httproute.json",
        primary_archetype_id="sn-gateway-httproute",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node01`: "
            "(1) `kubelet` on `node01` is stopped via setup.node_commands while `v1` and `v2` Deployments are pinned/scheduled across workers; "
            "(2) Service `v2-svc` has a mismatched targetPort; "
            "(3) Gateway `edge` (`GatewayClass: eg`) lacks an `HTTPRoute` splitting traffic 80/20 between `v1-svc` and `v2-svc` for host `<ns>.example.com`. "
            "Validate `node_status_ready(node01)`, both `service_endpoints_ready`, and `HTTPRoute` Accepted==True with both weights."
        ),
    ),
    CausalIncidentBlueprint(
        id="inc-cluster-kustomize-rbac-app",
        domain="Cluster Architecture, Installation & Configuration",
        title_theme="Node recovery + Kustomize workload overlay + RBAC least-privilege",
        subtopics=("Kustomize", "RBAC", "ServiceAccount", "kubelet"),
        requires_addons=(),
        example_seed="ca-rbac-pod-reader.json",
        primary_archetype_id="ca-rbac-least-priv",
        guidance=(
            "COHESIVE MULTI-LAYER INCIDENT in ONE business namespace `<ns>` + node `node02`: "
            "(1) `kubelet` on `node02` is stopped via setup.node_commands; "
            "(2) Deployment+Service `web-app` must be deployed in `<ns>` using bundled `assets/kustomize/overlays/prod` (2 replicas, tuned resources); "
            "(3) ServiceAccount `release-bot` in `<ns>` has an overly broad or broken RoleBinding that must grant ONLY `get,list` on `deployments` in `<ns>`. "
            "Validate `node_status_ready(node02)`, `deployment_rollout_ready(name=web-app, min=2)`, `service_endpoints_ready`, and `kubectl_auth_can_i` allowed+denied."
        ),
    ),
)


def load_seed_example(filename: str) -> str:
    """Load a compact version of a validated seed as dynamic few-shot anchor."""
    try:
        data = json.loads((config.BASE_DIR / "scenarios" / "seed" / filename).read_text())
        keep = {
            k: data[k]
            for k in (
                "id", "title", "domain", "difficulty", "weight",
                "estimated_minutes", "prompt", "copy_tokens", "docs_links",
                "setup", "checks", "solution", "cleanup",
            )
            if k in data
        }
        keep["prompt"] = str(keep.get("prompt", ""))[:700]
        return json.dumps(keep, indent=1, ensure_ascii=False)
    except Exception:
        return ""


def _constraint_excludes(constraints: list[str]) -> set[str]:
    blob = " ".join(constraints).lower()
    excluded: set[str] = set()
    for term, tag in (
        ("helm", "helm"),
        ("gateway", "gateway"),
        ("etcd", "etcd"),
        ("networkpolicy", "networkpolicy"),
        ("network policy", "networkpolicy"),
        ("kubelet", "kubelet"),
        ("static pod", "static-pods"),
        ("storage", "storage"),
        ("rbac", "rbac"),
    ):
        if any(neg in blob for neg in (f"no {term}", f"exclude {term}", f"without {term}", f"sem {term}")):
            excluded.add(tag)
    return excluded


def eligible_archetypes(
    domain: str,
    difficulty: str,
    available_addons: set[str],
    constraints: list[str] | None = None,
    *,
    allow_destructive: bool | None = None,
) -> list[Archetype]:
    excluded = _constraint_excludes(constraints or [])
    blob = " ".join(constraints or []).lower()
    explicit_destructive = any(
        tok in blob for tok in ("etcd restore", "restore", "kubeadm", "upgrade", "static pod", "apiserver", "destructive")
    )
    if allow_destructive is None:
        allow_destructive = (difficulty == "boss_fight") or explicit_destructive
    out: list[Archetype] = []
    for arch in ARCHETYPES:
        if arch.domain != domain:
            continue
        if arch.destructive and not allow_destructive:
            continue
        if difficulty not in arch.difficulties and difficulty != "boss_fight":
            continue
        if any(req not in available_addons for req in arch.requires_addons):
            continue
        tags = {arch.id.lower(), *(s.lower() for s in arch.subtopics)}
        if excluded & tags:
            continue
        out.append(arch)
    if not out:
        out = [
            arch for arch in ARCHETYPES
            if arch.domain == domain
            and (allow_destructive or not arch.destructive)
            and all(req in available_addons for req in arch.requires_addons)
        ]
    return out


def eligible_incidents(
    domain: str,
    available_addons: set[str],
    constraints: list[str] | None = None,
) -> list[CausalIncidentBlueprint]:
    excluded = _constraint_excludes(constraints or [])
    same_domain = [
        inc for inc in CAUSAL_INCIDENTS
        if inc.domain == domain
        and all(req in available_addons for req in inc.requires_addons)
        and not (excluded & {s.lower() for s in inc.subtopics})
    ]
    if same_domain:
        return same_domain
    return [
        inc for inc in CAUSAL_INCIDENTS
        if all(req in available_addons for req in inc.requires_addons)
        and not (excluded & {s.lower() for s in inc.subtopics})
    ]


SEED_ARCHETYPE_MAP: dict[str, str] = {
    "seed-ca-etcd-snapshot-save": "ca-etcd-snapshot-save",
    "seed-ca-helm-upgrade": "ca-helm-upgrade",
    "seed-ca-rbac-pod-reader": "ca-rbac-least-priv",
    "seed-ca-rolebinding-subject": "ca-rolebinding-subject",
    "seed-sn-expose-service": "sn-expose-clusterip",
    "seed-sn-gateway-httproute": "sn-gateway-httproute",
    "seed-sn-networkpolicy-dns": "sn-networkpolicy-dns",
    "seed-sn-service-selector": "sn-service-selector",
    "seed-sn-service-targetport": "sn-service-targetport",
    "seed-st-pod-wrong-claim": "st-pod-wrong-claim",
    "seed-st-pv-claimref": "st-pv-claimref",
    "seed-ts-crashloop-fix": "ts-crashloop-cmd",
    "seed-ts-image-pull": "ts-image-pull",
    "seed-ts-kubelet-node01": "ts-kubelet-down",
    "seed-ts-readiness-probe": "ts-readiness-probe",
    "seed-wl-resources-too-high": "wl-resources-cpu",
    "seed-wl-taint-toleration": "wl-taint-toleration",
    "seed-ca-kustomize-overlay": "ca-kustomize-overlay",
    "seed-ca-clusterrole-sa": "ca-clusterrole-sa",
    "seed-ca-csr-user-auth": "ca-csr-user-auth",
    "seed-wl-hpa-autoscale": "wl-hpa-autoscale",
    "seed-wl-pdb-priorityclass": "wl-pdb-priorityclass",
    "seed-wl-cronjob-policy": "wl-cronjob-policy",
    "seed-wl-native-sidecar": "wl-native-sidecar",
    "seed-sn-ingress-to-gateway-migration": "sn-ingress-to-gateway-migration",
    "seed-sn-gateway-canary-weights": "sn-gateway-canary-weights",
    "seed-st-pvc-local-path": "st-pvc-local-path",
    "seed-ca-etcd-restore": "ca-etcd-restore",
    "seed-ca-apiserver-static-pod-fix": "ca-controlplane-static-pod-fix",
    "seed-ca-kubeadm-node-drain": "ca-kubeadm-node-drain",
}

_ARCHETYPE_HINTS: tuple[tuple[tuple[str, ...], str, int], ...] = (
    (("gateway", "httproute"), "sn-gateway-httproute", 6),
    (("networkpolicy", "egress", "dns"), "sn-networkpolicy-dns", 6),
    (("networkpolicy", "ingress"), "sn-networkpolicy-multi-ns", 5),
    (("networkpolicy",), "sn-networkpolicy-dns", 5),
    (("nodeport",), "sn-nodeport-service", 7),
    (("targetport",), "sn-service-targetport", 7),
    (("clusterip", "expose"), "sn-expose-clusterip", 6),
    (("selector", "endpoints"), "sn-service-selector", 5),
    (("coredns", "dns"), "sn-coredns-config-debug", 4),
    (("crashloopbackoff", "configmap"), "ts-configmap-env-broken", 6),
    (("crashloopbackoff",), "ts-crashloop-cmd", 6),
    (("imagepullbackoff",), "ts-image-pull", 7),
    (("readinessprobe", "readiness"), "ts-readiness-probe", 6),
    (("kubelet", "notready"), "ts-kubelet-down", 7),
    (("claimref",), "st-pv-claimref", 7),
    (("storageclass",), "st-pvc-storageclass-mismatch", 6),
    (("persistentvolumeclaim", "pvc"), "st-pod-wrong-claim", 4),
    (("rolebinding",), "ca-rolebinding-subject", 6),
    (("rbac", "serviceaccount"), "ca-rbac-least-priv", 5),
    (("etcd", "snapshot"), "ca-etcd-snapshot-save", 7),
    (("helm",), "ca-helm-upgrade", 6),
    (("kustomize",), "ca-kustomize-overlay", 7),
    (("crd", "customresourcedefinition"), "ca-crd-inspect", 6),
    (("nodeselector", "nodeaffinity", "affinity"), "wl-node-affinity", 6),
    (("taint", "toleration"), "wl-taint-toleration", 7),
    (("hpa", "horizontalpodautoscaler"), "wl-hpa-autoscale", 7),
    (("daemonset",), "wl-daemonset-controlplane", 6),
    (("securitycontext", "runasnonroot"), "wl-securitycontext-nonroot", 7),
    (("image", "rollout"), "wl-rollout-undo-strategy", 4),
)


def infer_archetype_id(
    domain: str,
    title: str,
    subtopics: list[str] | tuple[str, ...] = (),
    seed_id: str | None = None,
) -> str | None:
    """Infer the closest curriculum archetype ID for legacy/untagged questions."""
    if seed_id and seed_id in SEED_ARCHETYPE_MAP:
        return SEED_ARCHETYPE_MAP[seed_id]

    import re

    blob = " ".join([title, *(subtopics or ())]).lower()
    compact = re.sub(r"[^a-z0-9]+", " ", blob).strip()
    tokens = set(compact.split())
    if not tokens:
        return None

    candidates = [arch for arch in ARCHETYPES if arch.domain == domain] or list(ARCHETYPES)
    best_id: str | None = None
    best_score = -1

    for arch in candidates:
        id_tokens = set(arch.id.lower().split("-"))
        sub_tokens = {
            tok
            for sub in arch.subtopics
            for tok in re.sub(r"[^a-z0-9]+", " ", sub.lower()).split()
        }
        guide_tokens = set(re.sub(r"[^a-z0-9]+", " ", arch.guidance.lower()).split())
        score = (
            3 * len(tokens & id_tokens)
            + 3 * len(tokens & sub_tokens)
            + len(tokens & guide_tokens)
        )
        for phrase_words, target_id, weight in _ARCHETYPE_HINTS:
            if arch.id == target_id and all(w in tokens for w in phrase_words):
                score += weight
        if score > best_score:
            best_score = score
            best_id = arch.id

    return best_id if best_score > 0 else (candidates[0].id if candidates else None)
