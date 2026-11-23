"""CKA Study Codex v2 — Domain 3: Services & Networking (Topics 18–25)."""

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

DOMAIN = "Services & Networking"

NETWORK_TOPICS: tuple[StudyTopic, ...] = (
    StudyTopic(
        id="sn-cni-kubeproxy",
        order=18,
        domain=DOMAIN,
        title="CNI Plugins (Calico/Flannel/Cilium), CIDRs & `kube-proxy`",
        subtitle="Install/troubleshoot cluster CNI networking, verify Pod/Service CIDRs, and audit `kube-proxy`.",
        estimated_minutes=6,
        exam_frequency="High",
        archetype_ids=("sn-networkpolicy-dns", "ts-coredns-broken"),
        summary=(
            "Every Kubernetes node requires a CNI plugin configured under `/etc/cni/net.d/` with binaries in `/opt/cni/bin/` "
            "before `kubelet` turns `Ready` and assigns Pod IPs from the cluster's `podCIDR`. `kube-proxy` runs on every node as a DaemonSet "
            "synchronizing `Service` ClusterIP virtual routes to backend `EndpointSlices` via `iptables`, `ipvs`, or `nftables`."
        ),
        architecture_flow=(
            "kubeadm init --pod-network-cidr + --service-cidr -> CNI DaemonSet installs /etc/cni/net.d/ -> Pod gets veth + PodIP -> kube-proxy updates node NAT rules for Service ClusterIPs"
        ),
        theory_points=(
            "Inspect node CNI health right on disk: `/etc/cni/net.d/*.conflist` (CNI plugin config) and `/opt/cni/bin/` (binaries like `calico`, `flannel`, `bridge`, `loopback`); missing configs keep ALL nodes `NotReady`.",
            "CNI `--pod-network-cidr` MUST match the CIDR declared at cluster init (`k cluster-info dump` or `/etc/kubernetes/manifests/kube-controller-manager.yaml --cluster-cidr`) — e.g. Flannel defaults `10.244.0.0/16`, Calico often defaults `192.168.0.0/16` unless edited!",
            "**NetworkPolicy CNI rule**: Flannel handles L3 Pod routing ONLY and silently IGNORES `NetworkPolicy` objects! Real isolation requires Calico, Cilium, Weave, or Antrea.",
            "`kube-proxy` modes (`k -n kube-system get cm kube-proxy -o yaml`): `iptables` (default sequential O(N) chains), `ipvs` (hash table O(1) for huge clusters), `nftables` (modern kernel netfilter).",
            "When cross-node Pod-to-Pod traffic fails while same-node traffic passes, check CNI DaemonSet Pod logs (`calico-node` / `kube-flannel-ds` / `cilium`) and verify overlay ports aren't blocked.",
        ),
        decision_matrix=(
            ComparisonRow("Flannel", "Lightweight VXLAN L3 overlay ONLY; zero `NetworkPolicy` enforcement", "Fast basic Pod networking when NetworkPolicies aren't used"),
            ComparisonRow("Calico / Cilium", "CNI networking + full `NetworkPolicy` (+ eBPF/BGP capabilities)", "Production clusters & CKA NetworkPolicy enforcement"),
            ComparisonRow("Pod CIDR (`cluster-cidr`)", "Node-sliced IP pool assigned to individual Pods (`10.244.x.y`)", "Check `k get nodes -o jsonpath='{.items[*].spec.podCIDR}'`"),
            ComparisonRow("Service CIDR (`service-cluster-ip-range`)", "Virtual IPs allocated to Services (`10.96.0.0/12`), routed by `kube-proxy`", "Never overlaps Pod CIDR or Node subnet"),
        ),
        docs_links=(
            StudyDocLink(
                label="Installing Addons & Networking (CNI)",
                url="https://kubernetes.io/docs/concepts/cluster-administration/addons/",
                exam_search_term="Network Policy CNI plugins",
            ),
            StudyDocLink(
                label="Cluster Networking Concepts",
                url="https://kubernetes.io/docs/concepts/cluster-administration/networking/",
                exam_search_term="Cluster Networking kube-proxy",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Identify installed CNI plugin, Pod CIDRs, and `service-cluster-ip-range`",
                explanation="Read live Pod CIDR allocation across nodes and inspect `/etc/cni/net.d/` + DaemonSets in `kube-system`.",
                command="k -n kube-system get ds,pods -o wide | grep -E 'calico|flannel|cilium|weave|kube-proxy' && k get nodes -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.podCIDR}{\"\\n\"}{end}'",
                verify_command="ls -la /etc/cni/net.d/ 2>/dev/null || ssh cka-node01 'ls -la /etc/cni/net.d/'",
                expected_output="One active `.conflist` or `.conf` file plus CNI Pods `1/1 Running`",
            ),
            PracticeStep(
                title="Check `kube-controller-manager` and `kube-apiserver` CIDRs before installing CNI",
                explanation="Ensure any CNI manifest's CIDR (`CALICO_IPV4POOL_CIDR` or Flannel `net-conf.json`) matches cluster Pod CIDR.",
                command="sudo grep -E 'cluster-cidr|service-cluster-ip-range' /etc/kubernetes/manifests/kube-controller-manager.yaml /etc/kubernetes/manifests/kube-apiserver.yaml",
            ),
            PracticeStep(
                title="Audit `kube-proxy` ConfigMap mode and verify DaemonSet health",
                explanation="If Service ClusterIPs refuse connections cluster-wide while Pod IPs respond, check `kube-proxy` Pods and logs.",
                command="k -n kube-system get cm kube-proxy -o yaml | grep -E 'mode:|clusterCIDR' && k -n kube-system logs -l k8s-app=kube-proxy --tail=20",
                verify_command="k -n kube-system rollout status ds/kube-proxy",
                expected_output="`daemon set \"kube-proxy\" successfully rolled out` across every node",
            ),
        ),
        debug_playbook=(
            DebugRow("New Pod stuck `ContainerCreating` (`networkPlugin cni failed to set up pod network`)", "Missing/broken `/etc/cni/net.d/` config or CNI DaemonSet Pod CrashLooping", "Check `k describe pod`, inspect CNI Pods in `kube-system`, verify CIDR match"),
            DebugRow("Nodes stay `NotReady` (`container runtime network not ready: NetworkReady=false`)", "CNI not yet installed or `systemd`/runtime failed to load CNI conf", "Install CNI addon matching `--cluster-cidr` and check `ls /etc/cni/net.d/`"),
            DebugRow("`NetworkPolicy` created accurately yet unauthorized curl still succeeds", "Cluster runs Flannel alone (ignores policies) or CNI Pod unhealthy", "Verify CNI supports NetworkPolicy (`calico`/`cilium`) and CNI agent logs cleanly"),
        ),
        exam_trap=(
            "Installing Calico with its default `192.168.0.0/16` pool onto a kubeadm cluster initialized with `--pod-network-cidr=10.244.0.0/16` leaves Pods failing IP routing unless you align `CALICO_IPV4POOL_CIDR` inside the manifest!"
        ),
        cheatsheet=(
            CheatItem("Node Pod CIDRs", "k get nodes -o jsonpath='{range .items[*]}{.metadata.name}{\"=\"}{.spec.podCIDR}{\"\\n\"}{end}'", "Reveals per-node Pod CIDR"),
            CheatItem("Check cluster CIDRs", "k cluster-info dump | grep -m2 -E 'cluster-cidr|service-cluster-ip-range'", "Fast live cluster audit"),
            CheatItem("Inspect node CNI conf", "sudo ls -la /etc/cni/net.d/ /opt/cni/bin/", "Confirms active CNI plugin files"),
            CheatItem("Audit CNI + kube-proxy pods", "k -n kube-system get pods -o wide", "Spot CrashLoop/Pending per node"),
            CheatItem("Check kube-proxy mode", "k -n kube-system get cm kube-proxy -o yaml | grep mode:", "iptables | ipvs | nftables"),
        ),
        yaml_template=(
            "# Pre-install checklist for ANY CKA CNI manifest:\n"
            "# 1. Confirm `--cluster-cidr` in /etc/kubernetes/manifests/kube-controller-manager.yaml\n"
            "# 2. Confirm CNI manifest CIDR matches (avoid overlapping host LAN or Service CIDR)\n"
            "# 3. Watch `k -n kube-system get pods -w` until CNI + coredns reach Running 1/1"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A cluster uses Flannel (`kube-flannel-ds`) as its sole CNI plugin. You apply a valid default-deny `NetworkPolicy` to namespace `payments`, yet curl requests between Pods still succeed. Why?",
                choices=(
                    "Flannel requires `policyTypes: [All]`",
                    "Flannel only sets up Pod-to-Pod L3 routing and does NOT implement Kubernetes `NetworkPolicy` enforcement",
                    "kube-proxy bypasses NetworkPolicies for `ClusterIP` Services",
                    "`kube-apiserver` disables ingress filters unless Calico etcd exists",
                ),
                correct_index=1,
                explanation="NetworkPolicy enforcement is delegated to the CNI plugin; Flannel handles overlay routing without filtering, whereas Calico/Cilium enforce policies.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="On a worker node whose kubelet reports `NetworkReady=false: CNI config uninitialized`, which host directory do you inspect first for active CNI plugin configurations?",
                choices=(
                    "`/etc/kubernetes/cni/`",
                    "`/etc/cni/net.d/`",
                    "`/var/lib/kubelet/plugins/`",
                    "`/etc/containerd/network/`",
                ),
                correct_index=1,
                explanation="kubelet reads CNI network definitions from `/etc/cni/net.d/` and executes plugins stored in `/opt/cni/bin/`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Pods can reach each other directly by Pod IP across nodes, CoreDNS Pods are healthy, yet EVERY Pod fails to connect to any `Service` ClusterIP (including `kubernetes.default`). Which component should you troubleshoot immediately?",
                choices=(
                    "`kube-scheduler`",
                    "`kube-proxy` DaemonSet (`iptables`/`ipvs`/`nftables` rules on nodes)",
                    "`local-path-provisioner`",
                    "`etcd` compaction",
                ),
                correct_index=1,
                explanation="Pod-to-Pod routing is handled by CNI, while translating Virtual `Service` ClusterIPs to Endpoint Pod IPs is performed locally on each node by `kube-proxy`.",
            ),
        ),
    ),
    StudyTopic(
        id="sn-services-endpoints",
        order=19,
        domain=DOMAIN,
        title="ClusterIP, NodePort, LoadBalancer, ExternalName & Endpoints",
        subtitle="Expose workloads cleanly and diagnose every Service hop (`selector` -> `Endpoints` -> `targetPort`).",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("sn-expose-clusterip", "sn-service-selector", "sn-service-targetport", "sn-nodeport-service"),
        summary=(
            "Services publish virtual IPs tracked dynamically against Ready Pods via `Endpoints` and modern `EndpointSlices`. "
            "Whenever `k get endpoints <svc>` reads `<none>`, `spec.selector` mismatches Pod labels (or Pods fail Readiness); "
            "whenever endpoints exist yet traffic returns `Connection refused`, `targetPort` mismatches the container's listening port."
        ),
        architecture_flow=(
            "Client -> Service DNS -> Virtual ClusterIP / NodeIP:NodePort (kube-proxy) -> Endpoints/EndpointSlices (matching selector + Ready Pods) -> targetPort == Container Port"
        ),
        theory_points=(
            "Four core Service types: `ClusterIP` (internal virtual IP), `NodePort` (`ClusterIP` + node static port `30000–32767`), `LoadBalancer` (provisions external LB + NodePort + ClusterIP), and `ExternalName` (CNAME alias to external DNS name, NO selector/IP).",
            "Distinguish all three ports: `port` (Service virtual port), `targetPort` (container port integer OR named port like `http`), and `nodePort` (`30000–32767` opened on node interfaces).",
            "`k expose deploy <d> --name=<svc> --port=80 --target-port=8080` copies the Deployment's exact selector labels safely; `k create svc nodeport` forces selector `app=<svc>` (watch out if labels say `tier=web`!).",
            "Service DNS resolves both `<svc>` (same namespace) and `<svc>.<ns>.svc.cluster.local` (cross-namespace); SRV records expose named ports too.",
            "`EndpointSlices` scale large clusters cleanly (`< 100` endpoints/slice); Services with `publishNotReadyAddresses: true` expose Pod IPs even before Readiness passes (common in database quorum discovery).",
        ),
        decision_matrix=(
            ComparisonRow("`ClusterIP` (default)", "Internal cluster virtual IP reachable only inside cluster nodes/Pods", "East-west microservice communication"),
            ComparisonRow("`NodePort`", "Exposes Service on `<AnyNodeIP>:<30000-32767>` + internal ClusterIP", "Bare-metal / kubeadm external exposure without cloud LB"),
            ComparisonRow("`clusterIP: None` (Headless)", "No virtual VIP; DNS returns direct Pod A-records directly", "StatefulSets, client-side LB, peer discovery"),
            ComparisonRow("`ExternalName`", "Returns DNS CNAME (`externalName: db.corp.internal`) without proxy", "Aliasing external SaaS/RDS hostname cleanly in Pod config"),
        ),
        docs_links=(
            StudyDocLink(
                label="Service Networking",
                url="https://kubernetes.io/docs/concepts/services-networking/service/",
                exam_search_term="Services Networking",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect Pod labels and real container listening ports",
                explanation="Compare Deployment labels and `containerPort` before exposing or patching a Service.",
                command="k -n web get pods --show-labels && k -n web get deploy -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[*].ports}{\"\\n\"}{end}'",
                verify_command="k -n web get svc,endpoints,endpointslices",
                expected_output="Endpoints list matches exact count and IP:targetPort of Ready Pods",
            ),
            PracticeStep(
                title="Expose Deployment via ClusterIP or fixed NodePort cleanly",
                explanation="Use `k expose deploy` to inherit Pod selectors automatically (avoid `k create svc` guessing `app=<svc>`).",
                command="k -n web expose deploy api --name=api-svc --port=80 --target-port=8080 --type=NodePort",
                yaml_snippet=(
                    "apiVersion: v1\n"
                    "kind: Service\n"
                    "metadata:\n"
                    "  name: api-svc\n"
                    "  namespace: web\n"
                    "spec:\n"
                    "  type: NodePort\n"
                    "  selector:\n"
                    "    app: api\n"
                    "  ports:\n"
                    "  - port: 80\n"
                    "    targetPort: 8080\n"
                    "    nodePort: 31080"
                ),
            ),
            PracticeStep(
                title="Prove live HTTP connectivity across Service DNS and NodePort",
                explanation="Verify DNS + HTTP 200 inside cluster AND curl `<node-ip>:<nodePort>` if NodePort exposed.",
                command="k -n web run nettest --rm -it --restart=Never --image=curlimages/curl:8.10.1 -- curl -fsS http://api-svc.web.svc.cluster.local",
                verify_command="k -n web get endpoints api-svc -o jsonpath='{.subsets[0].addresses[*].ip}{\":\"}{.subsets[0].ports[0].port}'",
                expected_output="Non-empty `<pod-ip>:8080` endpoints and clean HTTP 200 response from curl",
            ),
        ),
        debug_playbook=(
            DebugRow("`kubectl get endpoints <svc>` prints `<none>`", "Service `spec.selector` differs from Pod labels, OR Pod `readinessProbe` is failing", "Compare `k describe svc <svc>` Selector vs `k get pods --show-labels`"),
            DebugRow("Endpoints show `10.244.x.y:80`, yet curl fails `Connection refused`", "`targetPort: 80` forwards to wrong container port (app listens on `8080` or `3000`)", "Check container `ss -tulpn` / Dockerfile / Deployment ports and patch `targetPort`"),
            DebugRow("NodePort rejects connections outside valid range", "Attempted port outside `30000–32767`", "Set `nodePort` strictly within `30000–32767` (default service-node-port-range)"),
        ),
        exam_trap=(
            "`kubectl create service clusterip my-svc --tcp=80:8080` hardcodes `selector: {app: my-svc}` regardless of what Pod labels exist! Using `kubectl expose deployment <deploy>` automatically copies the Deployment's real labels."
        ),
        cheatsheet=(
            CheatItem("Expose deploy safely", "k -n <ns> expose deploy <d> --name=<svc> --port=80 --target-port=8080 --type=ClusterIP", "Copies real Pod selector labels"),
            CheatItem("NodePort template", "k -n <ns> expose deploy <d> --name=<svc> --port=80 --target-port=80 --type=NodePort $do > svc.yaml", "Then add specific `nodePort: 31xxx`"),
            CheatItem("Compare selector vs labels", "k -n <ns> get svc <svc> -o wide && k -n <ns> get pods --show-labels", "Spots selector typos immediately"),
            CheatItem("Verify Endpoints + Slices", "k -n <ns> get endpoints,endpointslices -l kubernetes.io/service-name=<svc>", "Confirms Ready Pod registration"),
            CheatItem("Quick internal curl", "k -n <ns> run tmp --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- curl -fsS http://<svc>:<port>", "Tests end-to-end L4/L7 delivery"),
        ),
        yaml_template=(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: web-svc\n"
            "spec:\n"
            "  type: NodePort\n"
            "  selector:\n"
            "    app: web\n"
            "  ports:\n"
            "  - port: 80\n"
            "    targetPort: 8080\n"
            "    nodePort: 30080"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="`kubectl get endpoints web-svc` prints `<none>`, while matching Pods exist in the same namespace with `STATUS: Running` and `READY: 0/1`. What is preventing Endpoint registration?",
                choices=(
                    "Only NodePort Services populate Endpoints",
                    "The Pods have not passed their `readinessProbe`, so EndpointSlice/Endpoints controllers exclude unready IPs",
                    "CoreDNS blocked registration",
                    "Services ignore Deployments in custom namespaces",
                ),
                correct_index=1,
                explanation="Unready Pods (`READY 0/1`) are excluded from `Endpoints` (`addresses` vs `notReadyAddresses`) until their `readinessProbe` passes (unless `publishNotReadyAddresses: true`).",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Why is `kubectl expose deploy api --name=api-svc --port=80 --target-port=8080` preferred over `kubectl create service clusterip api-svc --tcp=80:8080` in CKA tasks?",
                choices=(
                    "`create service` cannot target port 8080",
                    "`expose` inspects and copies the Deployment's real Pod template labels automatically, whereas `create service` guesses `app=<svc-name>`",
                    "`expose` also creates an HTTPRoute",
                    "`create service` forces `NodePort`",
                ),
                correct_index=1,
                explanation="If Deployment Pods carry `tier: api` or `app: backend`, `create service` creates an empty-endpoint Service guessing `app: api-svc`, whereas `expose` matches labels accurately.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="`kubectl get endpoints web-svc` lists `10.244.1.9:80`, yet `curl http://web-svc` gets `Connection refused` while the container listens on `8080`. Which field needs fixing?",
                choices=(
                    "`spec.selector`",
                    "`spec.ports[0].targetPort` changed from `80` to `8080`",
                    "`spec.clusterIP` to `None`",
                    "`spec.type` to `ExternalName`",
                ),
                correct_index=1,
                explanation="Populated Endpoints prove `selector` already matches; fixing `targetPort` to `8080` forwards traffic to the container's listening port.",
            ),
        ),
    ),
    StudyTopic(
        id="sn-ingress-deep-dive",
        order=20,
        domain=DOMAIN,
        title="Ingress, `IngressClass`, PathTypes (`Prefix`/`Exact`) & TLS",
        subtitle="Create `networking.k8s.io/v1` Ingress rules fast via CLI and troubleshoot 404/502/503 responses.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("sn-ingress-to-gateway-migration", "sn-expose-clusterip"),
        summary=(
            "Ingress (`networking.k8s.io/v1`) exposes HTTP/HTTPS host and path routes via an Ingress Controller (`nginx`, `traefik`, etc.) "
            "selected by `spec.ingressClassName`. Master `k create ingress`, `Prefix` vs `Exact` vs `ImplementationSpecific` path matching, "
            "TLS Secrets (`tls.crt`/`tls.key`), and fast HTTP status triage (`404`, `502`, `503`)."
        ),
        architecture_flow=(
            "External Client (HTTPS Host/Path) -> Ingress Controller Pod (matches IngressClass) -> Evaluates Host + pathType -> Resolves Service Endpoints -> Backend Pod"
        ),
        theory_points=(
            "Always check `k get ingressclass` first! Without an `ingressClassName` (or a default IngressClass marked `ingressclass.kubernetes.io/is-default-class: \"true\"`), the Ingress controller ignores your Ingress and leaves `ADDRESS` blank.",
            "Imperative `k create ingress <name> --class=<cls> --rule=\"host.com/path*=svc:port,tls=secret\"` writes flawless `networking.k8s.io/v1` boilerplate in one command (`*` = `Prefix`, omit `*` = `Exact`)!",
            "`pathType: Prefix` matches trailing path segment boundaries (`/api` matches `/api` and `/api/v1`, NOT `/apiv2`); `pathType: Exact` matches character-for-character cleanly.",
            "Ingress TLS references a `kubernetes.io/tls` Secret in the SAME namespace (`k create secret tls my-tls --cert=c.crt --key=c.key`).",
            "**HTTP error code map**: `404` = wrong hostname/`Host:` header or wrong `path`/`pathType` (or rewrite annotation missing); `503` = matching Service has `<none>` Endpoints; `502` = Service `targetPort` refuses/drops backend connections.",
        ),
        decision_matrix=(
            ComparisonRow("`pathType: Prefix`", "Matches `/foo` and `/foo/...` on `/`-delimited segments", "Standard API/frontend path subtrees (`/api` -> `/api/users`)"),
            ComparisonRow("`pathType: Exact`", "Matches URL path identically (case-sensitive `/healthz` != `/healthz/`)", "Strict single endpoint routing (`/healthz`, `/login`)"),
            ComparisonRow("`ImplementationSpecific`", "Defers matching regex/rules entirely to controller implementation", "Controller-specific regex when explicitly requested"),
            ComparisonRow("`k create ingress ... --rule`", "Imperative CLI using `host/path*=svc:port` syntax", "Fast zero-indentation Ingress creation in exam"),
        ),
        docs_links=(
            StudyDocLink(
                label="Ingress Concepts & PathTypes",
                url="https://kubernetes.io/docs/concepts/services-networking/ingress/",
                exam_search_term="Ingress pathType IngressClass",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Discover active IngressClass and Ingress controller Service",
                explanation="Verify controller exists and note its IngressClass name (and whether it has `is-default-class`).",
                command="k get ingressclass && k get pods,svc -A | grep -i ingress",
                verify_command="k get ingressclass -o custom-columns=NAME:.metadata.name,CONTROLLER:.spec.controller",
                expected_output="Prints active `IngressClass` name (e.g. `nginx`) + controller",
            ),
            PracticeStep(
                title="Create an HTTP or TLS Ingress cleanly via imperative `--rule`",
                explanation="Use `/path*` for `Prefix` matching and omit `*` for `Exact`; append `,tls=<secret>` if HTTPS required.",
                command="k -n web create ingress shop-ing --class=nginx --rule='shop.example.com/api*=api-svc:80' --rule='shop.example.com/=web-svc:80' $do > ingress.yaml",
                yaml_snippet=(
                    "apiVersion: networking.k8s.io/v1\n"
                    "kind: Ingress\n"
                    "metadata:\n"
                    "  name: shop-ing\n"
                    "spec:\n"
                    "  ingressClassName: nginx\n"
                    "  rules:\n"
                    "  - host: shop.example.com\n"
                    "    http:\n"
                    "      paths:\n"
                    "      - path: /api\n"
                    "        pathType: Prefix\n"
                    "        backend:\n"
                    "          service: { name: api-svc, port: { number: 80 } }"
                ),
            ),
            PracticeStep(
                title="Verify Ingress address/rules and test Host-header routing",
                explanation="Use `curl -H 'Host: ...'` (or `--resolve`) against the Ingress controller endpoint cleanly.",
                command="k -n web get ingress && k -n web describe ingress shop-ing",
                verify_command="curl -ks -H 'Host: shop.example.com' http://127.0.0.1/api || k -n web get endpoints api-svc",
                expected_output="Ingress `CLASS` & `HOSTS` set cleanly and backend Service reports valid Ready Endpoints",
            ),
        ),
        debug_playbook=(
            DebugRow("Ingress returns `404 Not Found` from nginx controller", "`Host:` header omitted in curl, missing `ingressClassName`, or `pathType: Exact` used instead of `Prefix`", "Inspect `describe ingress`, test with `curl -H 'Host: ...'`, verify `ingressClassName`"),
            DebugRow("Ingress returns `503 Service Temporarily Unavailable`", "Backend `service.name` doesn't exist in Ingress namespace OR has `<none>` endpoints", "Run `k -n <ns> get svc,endpoints` in the Ingress's namespace"),
            DebugRow("Backend Pod gets `/api/users` instead of `/users` causing backend 404", "Missing URL rewrite annotation on nginx (`nginx.ingress.kubernetes.io/rewrite-target: /`) or wrong app route", "Inspect annotation or migrate cleanly to Gateway API `URLRewrite`"),
        ),
        exam_trap=(
            "Remember `k create ingress` uses `/path*` (`Prefix`) vs `/path` (`Exact`), AND forgetting `--class=<ingressClassName>` when the cluster lacks a default `IngressClass` silently leaves your Ingress unprogrammed!"
        ),
        cheatsheet=(
            CheatItem("Imperative Ingress (Prefix)", "k -n <ns> create ingress app --class=nginx --rule='app.local/*=web:80'", "Trailing `*` generates Prefix"),
            CheatItem("Imperative Ingress (Exact)", "k -n <ns> create ingress app --class=nginx --rule='app.local/health=web:80,tls=app-tls'", "No `*` creates Exact + TLS"),
            CheatItem("Check IngressClasses", "k get ingressclass", "Match spec.ingressClassName"),
            CheatItem("Check Ingress events", "k -n <ns> describe ingress <name>", "Lists host -> path -> backend:endpoints"),
            CheatItem("Test with Host header", "curl -H 'Host: app.local' http://<controller-ip>/", "Tests virtual host cleanly"),
        ),
        yaml_template=(
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: web-ingress\n"
            "spec:\n"
            "  ingressClassName: nginx\n"
            "  tls:\n"
            "  - hosts: [\"app.example.com\"]\n"
            "    secretName: app-tls\n"
            "  rules:\n"
            "  - host: app.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - path: /\n"
            "        pathType: Prefix\n"
            "        backend:\n"
            "          service:\n"
            "            name: web-svc\n"
            "            port:\n"
            "              number: 80"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="With `path: /pay` and `pathType: Prefix`, which URL request path does a compliant Ingress controller NOT route to that backend?",
                choices=(
                    "`/pay`",
                    "`/pay/checkout`",
                    "`/payment` (does not match on `/` path-segment boundary)",
                    "`/pay/`",
                ),
                correct_index=2,
                explanation="Prefix matching aligns strictly on `/` path segment boundaries, so `/pay` matches `/pay` and `/pay/*`, never `/payment`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="In `kubectl create ingress`, what syntax inside `--rule` distinguishes `pathType: Prefix` from `pathType: Exact`?",
                choices=(
                    "Appending `?prefix=true`",
                    "Appending `*` to the path (`/api*` = `Prefix`, `/api` = `Exact`)",
                    "Passing `--prefix=true` flag",
                    "Double slash `//api`",
                ),
                correct_index=1,
                explanation="`--rule='host/api*=svc:80'` generates `pathType: Prefix`, whereas `--rule='host/api=svc:80'` without `*` generates `pathType: Exact`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Your Ingress controller runs cleanly, `k describe ingress web` matches `host: app.local` and `path: /`, yet external requests to `app.local` return `503 Service Temporarily Unavailable`. What is the cause?",
                choices=(
                    "`ingressClassName` was set to `nginx`",
                    "The backend `Service` exists (or is missing) with ZERO Ready Endpoints (`<none>`)",
                    "`tls.secretName` uses HTTP/2",
                    "`pathType: Prefix` forbids root `/`",
                ),
                correct_index=1,
                explanation="HTTP `404` indicates missing route match; HTTP `503` indicates the controller matched the Ingress rule cleanly yet found zero healthy backend endpoints.",
            ),
        ),
    ),
    StudyTopic(
        id="sn-gateway-api-core",
        order=21,
        domain=DOMAIN,
        title="Gateway API: `GatewayClass`, `Gateway`, `HTTPRoute` & `ReferenceGrant`",
        subtitle="Route HTTP hosts/paths natively using the modern CKA 2025/2026 Gateway API (`gateway.networking.k8s.io/v1`).",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("sn-gateway-httproute",),
        summary=(
            "Gateway API separates cluster roles cleanly: Infrastructure defines `GatewayClass` -> `Gateway` listeners (`HTTP`/`HTTPS` + TLS `certificateRefs`), "
            "while application teams create `HTTPRoute` binding via `parentRefs` onto Gateway listeners and routing to `backendRefs`. "
            "Cross-namespace Service references require a `ReferenceGrant` inside the target Service's namespace."
        ),
        architecture_flow=(
            "GatewayClass (Controller) -> Gateway (listeners + TLS + allowedRoutes) <- parentRefs -- HTTPRoute (hostnames + matches + backendRefs) -- [ReferenceGrant if cross-ns] -> Service"
        ),
        theory_points=(
            "Check `k get gatewayclass` and `k get gateway -A` first to get exact `gatewayClassName`, `Gateway` name/namespace, listener `sectionName`, and `allowedRoutes.namespaces.from` (`Same`, `All`, `Selector`).",
            "`HTTPRoute` attaches via `spec.parentRefs[]` (`name`, optional `namespace`, optional `sectionName` targeting a specific listener such as `https`).",
            "Always inspect `k describe httproute <name>` Conditions: **`Accepted: True`** confirms parent Gateway accepted the route (host/allowedRoutes OK); **`ResolvedRefs: True`** confirms backend Services/ReferenceGrants resolve!",
            "Cross-namespace routing (`HTTPRoute` in ns `A` -> `Service` in ns `B`) ALWAYS fails with `ResolvedRefs: False (RefNotPermitted)` unless ns `B` contains a `ReferenceGrant` (`gateway.networking.k8s.io/v1beta1`).",
            "Note on local kubeadm labs without cloud LoadBalancers, `Gateway` `Accepted=True` and `HTTPRoute` `Accepted=True` verify routing correctness even if `Programmed` waits on external LB IP.",
        ),
        decision_matrix=(
            ComparisonRow("`GatewayClass`", "Cluster-scoped controller driver (e.g., `eg`, `cilium`, `nginx`)", "Checking which Gateway controller runs in the cluster"),
            ComparisonRow("`Gateway`", "Opens listener ports (`80`/`443`), TLS certs, and `allowedRoutes` policy", "Infra listener entrypoint bound by HTTPRoutes"),
            ComparisonRow("`HTTPRoute`", "Matches hostnames/paths/headers -> `backendRefs` services", "Application L7 HTTP routing rules"),
            ComparisonRow("`ReferenceGrant`", "Placed in TARGET Service namespace allowing cross-ns `HTTPRoute` refs", "Unlocking `RefNotPermitted` when route & Service live in separate namespaces"),
        ),
        docs_links=(
            StudyDocLink(
                label="Kubernetes Gateway API Documentation",
                url="https://gateway-api.sigs.k8s.io/",
                exam_search_term="Gateway API HTTPRoute",
            ),
            StudyDocLink(
                label="Ingress & Gateway Concepts",
                url="https://kubernetes.io/docs/concepts/services-networking/gateway/",
                exam_search_term="Gateway API",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect GatewayClasses, existing Gateways, and listener rules",
                explanation="Discover `gatewayClassName`, listener names (`sectionName`), ports, and `allowedRoutes`.",
                command="k get gatewayclass && k get gateway -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,CLASS:.spec.gatewayClassName",
                verify_command="k get gateway -A -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.listeners[*].name} {.status.conditions[*].type}={.status.conditions[*].status}{\"\\n\"}{end}'",
                expected_output="Shows listener names and Gateway `Accepted=True`",
            ),
            PracticeStep(
                title="Inspect `HTTPRoute` & `ReferenceGrant` schema via `kubectl explain`",
                explanation="Read exact v1 field names directly from installed CRDs without guessing indentation.",
                command="k explain httproute.spec.parentRefs && k explain referencegrant.spec",
                yaml_snippet=(
                    "apiVersion: gateway.networking.k8s.io/v1\n"
                    "kind: HTTPRoute\n"
                    "metadata:\n"
                    "  name: app-route\n"
                    "  namespace: web\n"
                    "spec:\n"
                    "  parentRefs:\n"
                    "  - name: main-gateway\n"
                    "    namespace: edge-gw\n"
                    "  hostnames: [\"app.example.com\"]\n"
                    "  rules:\n"
                    "  - matches:\n"
                    "    - path: { type: PathPrefix, value: /api }\n"
                    "    backendRefs:\n"
                    "    - name: api-svc\n"
                    "      port: 80"
                ),
            ),
            PracticeStep(
                title="Apply `HTTPRoute` (and `ReferenceGrant` if cross-ns) and check Conditions",
                explanation="Both `Accepted` AND `ResolvedRefs` must report `True` under `describe httproute`.",
                command="k -n web apply -f route.yaml && k -n web describe httproute app-route",
                verify_command="k -n web get httproute app-route -o jsonpath='{.status.parents[0].conditions[*].type}{\"=\"}{.status.parents[0].conditions[*].status}'",
                expected_output="`Accepted` and `ResolvedRefs` both `True`",
            ),
        ),
        debug_playbook=(
            DebugRow("`HTTPRoute` status missing or `Accepted: False` (`NotAllowedByListeners`)", "`Gateway.spec.listeners[].allowedRoutes` restricts namespaces (`Same`), OR `hostnames` doesn't intersect Gateway listener", "Check `Gateway.spec.listeners[]` namespace scope (`All` vs `Selector`) and match `hostnames`"),
            DebugRow("`HTTPRoute` reports `ResolvedRefs: False` (`RefNotPermitted`)", "`backendRefs` targets a `Service` in a DIFFERENT namespace without a `ReferenceGrant`", "Create `ReferenceGrant` in the target Service's namespace permitting `HTTPRoute` from route's ns"),
            DebugRow("`HTTPRoute` rejected on apply: `unknown field`", "Used Ingress field names (`serviceName`, `pathType: Prefix`) instead of Gateway API keys (`PathPrefix`, `backendRefs`)", "Use `type: PathPrefix` and `k explain httproute.spec`"),
        ),
        exam_trap=(
            "Cross-namespace attachment requires BOTH permissions: Gateway -> HTTPRoute needs `Gateway.spec.listeners[].allowedRoutes.namespaces.from: All` (or `Selector`), AND HTTPRoute -> Service needs a `ReferenceGrant` inside the target Service's namespace!"
        ),
        cheatsheet=(
            CheatItem("List Gateway CRDs", "k api-resources --api-group=gateway.networking.k8s.io", "Shows GatewayClass/Gateway/HTTPRoute/ReferenceGrant"),
            CheatItem("Inspect Gateway listeners", "k -n <ns> get gateway <gw> -o yaml", "Check listener names, port, TLS, allowedRoutes"),
            CheatItem("Verify HTTPRoute conditions", "k -n <ns> describe httproute <name>", "Check `Accepted=True` and `ResolvedRefs=True`"),
            CheatItem("Explain ReferenceGrant", "k explain referencegrant.spec", "Cross-namespace `from` & `to` rules"),
            CheatItem("Check backend endpoints", "k -n <ns> get endpoints <svc>", "Missing Service/Endpoints breaks ResolvedRefs"),
        ),
        yaml_template=(
            "apiVersion: gateway.networking.k8s.io/v1beta1\n"
            "kind: ReferenceGrant\n"
            "metadata:\n"
            "  name: allow-web-route\n"
            "  namespace: orders\n"
            "spec:\n"
            "  from:\n"
            "  - group: gateway.networking.k8s.io\n"
            "    kind: HTTPRoute\n"
            "    namespace: web\n"
            "  to:\n"
            "  - group: \"\"\n"
            "    kind: Service"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Where does TLS termination (`certificateRefs` pointing to a TLS Secret) live in Kubernetes Gateway API?",
                choices=(
                    "Inside `HTTPRoute.spec.tls`",
                    "Inside `Gateway.spec.listeners[].tls.certificateRefs`",
                    "Inside `GatewayClass.spec.parametersRef` only",
                    "Inside the Service annotations",
                ),
                correct_index=1,
                explanation="Gateway infrastructure owners configure HTTPS listeners (`mode: Terminate` + `certificateRefs`) directly on the `Gateway` resource.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="In `HTTPRoute`, which field specifies the Gateway (and optional specific listener) the route wants to attach to?",
                choices=(
                    "`spec.gatewayRef`",
                    "`spec.parentRefs` (`name`, optional `namespace`, optional `sectionName`)",
                    "`metadata.ownerReferences`",
                    "`spec.ingressClassName`",
                ),
                correct_index=1,
                explanation="`HTTPRoute.spec.parentRefs[]` binds routes onto Gateways and optional named listeners (`sectionName`).",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="An `HTTPRoute` in namespace `frontend` targets `backendRefs: {name: orders-svc, namespace: orders, port: 80}` and reports `ResolvedRefs: False (RefNotPermitted)`. What fixes it?",
                choices=(
                    "A `ClusterRoleBinding` granting `view` to frontend SA",
                    "Creating a `ReferenceGrant` inside namespace `orders` permitting `HTTPRoute` from `frontend` to reference `Service`",
                    "Moving `Gateway` into `kube-system`",
                    "Adding `allowedRoutes: All` to `HTTPRoute`",
                ),
                correct_index=1,
                explanation="Cross-namespace Service references from an `HTTPRoute` require an explicit `ReferenceGrant` living inside the backend target's namespace (`orders`).",
            ),
        ),
    ),
    StudyTopic(
        id="sn-ingress-to-gateway",
        order=22,
        domain=DOMAIN,
        title="Migrating Legacy Ingress to Gateway API",
        subtitle="Convert Ingress hosts, pathTypes, TLS secrets, and path rewrites onto Gateway + HTTPRoute.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("sn-ingress-to-gateway-migration",),
        summary=(
            "A top CKA 2025/2026 task gives you an existing `networking.k8s.io/v1` `Ingress` and asks you to translate it "
            "into a `Gateway` + `HTTPRoute` using an existing `GatewayClass`. Map TLS onto `Gateway` listeners and map "
            "hosts/paths/rewrites/backends onto `HTTPRoute` accurately without dropping any route."
        ),
        architecture_flow=(
            "Ingress.spec.tls -> Gateway.listeners[https].tls.certificateRefs  |  Ingress.rules[host/http.paths] -> HTTPRoute (hostnames + PathPrefix/Exact + backendRefs)"
        ),
        theory_points=(
            "`Ingress.spec.tls[].secretName` moves to `Gateway.spec.listeners[]` (`protocol: HTTPS`, `port: 443`, `tls: {mode: Terminate, certificateRefs: [{name: <secret>}]}`).",
            "Ingress `pathType: Prefix` becomes `HTTPRoute` `type: PathPrefix`; `Exact` remains `type: Exact`.",
            "Ingress controller rewrite annotations (`nginx.ingress.kubernetes.io/rewrite-target`) convert cleanly to native `HTTPRoute` `filters: [{type: URLRewrite, urlRewrite: {path: {type: ReplacePrefixMatch, replacePrefixMatch: /}}}]`.",
            "Remember if a `Gateway` exposes BOTH `:80` HTTP and `:443` HTTPS listeners, attach `HTTPRoute` via `parentRefs[].sectionName` cleanly so traffic binds to the intended listener.",
            "Only delete the legacy `Ingress` if the exam prompt explicitly instructs you to remove it after migration!",
        ),
        decision_matrix=(
            ComparisonRow("`Ingress.spec.tls[].secretName`", "Moves to `Gateway.spec.listeners[].tls.certificateRefs`", "Migrating HTTPS termination from Ingress -> Gateway"),
            ComparisonRow("`pathType: Prefix`", "Maps to `matches[].path.type: PathPrefix`", "Subtree prefix routes (`/app` -> `/app/v1`)"),
            ComparisonRow("`pathType: Exact`", "Maps to `matches[].path.type: Exact`", "Exact single URL match"),
            ComparisonRow("nginx `rewrite-target`", "Maps to `filters[].type: URLRewrite` (`ReplacePrefixMatch`)", "Stripping `/api` prefix natively without annotations"),
        ),
        docs_links=(
            StudyDocLink(
                label="Migrating from Ingress to Gateway API",
                url="https://gateway-api.sigs.k8s.io/guides/migrating-from-ingress/",
                exam_search_term="Migrating from Ingress",
            ),
            StudyDocLink(
                label="Ingress Concepts",
                url="https://kubernetes.io/docs/concepts/services-networking/ingress/",
                exam_search_term="Ingress",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Dump full legacy Ingress YAML & check available GatewayClass",
                explanation="Record exact `host`, every `path` + `pathType`, backend `service.name`/`port`, and `tls.secretName`.",
                command="k -n <ns> get ingress -o yaml && k get gatewayclass",
                verify_command="k get gatewayclass -o jsonpath='{.items[*].metadata.name}{\"\\n\"}'",
                expected_output="Prints live `GatewayClass` name (e.g. `eg`) and Ingress rules",
            ),
            PracticeStep(
                title="Create `Gateway` with matching HTTP/HTTPS listeners + TLS refs",
                explanation="Place `Gateway` in the target namespace (or verify `allowedRoutes` if shared across namespaces).",
                command="k explain gateway.spec.listeners.tls --recursive",
                yaml_snippet=(
                    "apiVersion: gateway.networking.k8s.io/v1\n"
                    "kind: Gateway\n"
                    "metadata:\n"
                    "  name: prod-gw\n"
                    "spec:\n"
                    "  gatewayClassName: eg\n"
                    "  listeners:\n"
                    "  - name: https\n"
                    "    protocol: HTTPS\n"
                    "    port: 443\n"
                    "    hostname: shop.example.com\n"
                    "    tls:\n"
                    "      mode: Terminate\n"
                    "      certificateRefs: [{ name: shop-tls }]"
                ),
            ),
            PracticeStep(
                title="Create `HTTPRoute` mirroring every host, path, and backend Service",
                explanation="Attach via `parentRefs` and confirm BOTH `Gateway` and `HTTPRoute` report `Accepted: True`.",
                command="k -n <ns> apply -f gateway-and-route.yaml && k -n <ns> describe gateway,httproute",
                verify_command="k -n <ns> get httproute -o jsonpath='{.items[*].status.parents[*].conditions[*].status}'",
                expected_output="Conditions report `True` (`Accepted` & `ResolvedRefs`)",
            ),
        ),
        debug_playbook=(
            DebugRow("Migrated HTTPS route fails handshake / wrong hostname", "`Gateway.spec.listeners[].hostname` omits or mismatches `HTTPRoute.spec.hostnames`", "Ensure `HTTPRoute.spec.hostnames` intersects listener hostname cleanly"),
            DebugRow("Backend Service gets 404 after replacing `rewrite-target` annotation", "Dropped URL path prefix stripping when converting from nginx Ingress", "Add `filters: [{type: URLRewrite, urlRewrite: {path: {type: ReplacePrefixMatch, replacePrefixMatch: /}}}]`"),
            DebugRow("Using `Prefix` as `pathType` value in `HTTPRoute` rejected", "Gateway API uses `PathPrefix` (not `Prefix`)", "Switch `type: Prefix` -> `type: PathPrefix`"),
        ),
        exam_trap=(
            "Ingress uses `pathType: Prefix`, whereas Gateway API `HTTPRoute` strictly requires `type: PathPrefix`! Writing `type: Prefix` fails OpenAPI schema validation immediately."
        ),
        cheatsheet=(
            CheatItem("Inspect source Ingress", "k -n <ns> get ingress -o yaml", "Capture host, paths, port, TLS secret"),
            CheatItem("Check GatewayClass", "k get gatewayclass", "Get exact `gatewayClassName`"),
            CheatItem("Gateway TLS schema", "k explain gateway.spec.listeners.tls.certificateRefs", "Verify TLS block"),
            CheatItem("Verify URLRewrite filter", "k explain httproute.spec.rules.filters.urlRewrite", "Native prefix stripping"),
            CheatItem("Verify route health", "k -n <ns> describe httproute <name>", "Both Accepted & ResolvedRefs = True"),
        ),
        yaml_template=(
            "apiVersion: gateway.networking.k8s.io/v1\n"
            "kind: HTTPRoute\n"
            "metadata:\n"
            "  name: migrated-route\n"
            "spec:\n"
            "  parentRefs:\n"
            "  - name: prod-gw\n"
            "    sectionName: https\n"
            "  hostnames: [\"shop.example.com\"]\n"
            "  rules:\n"
            "  - matches:\n"
            "    - path: { type: PathPrefix, value: / }\n"
            "    backendRefs:\n"
            "    - name: web-svc\n"
            "      port: 80"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="When migrating an Ingress with `tls: [{hosts: [a.com], secretName: a-tls}]` to Gateway API, where does `a-tls` belong?",
                choices=(
                    "Inside `HTTPRoute.spec.tls`",
                    "Inside `Gateway.spec.listeners[].tls.certificateRefs`",
                    "Inside backend Service annotations",
                    "Inside a `ReferenceGrant`",
                ),
                correct_index=1,
                explanation="TLS certificates live directly on `Gateway` listener definitions under `tls.certificateRefs`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="What is the exact `HTTPRoute` equivalent of legacy Ingress `pathType: Prefix`?",
                choices=(
                    "`path.type: Prefix`",
                    "`path.type: PathPrefix`",
                    "`path.type: WildcardPrefix`",
                    "`path.type: ImplementationSpecific`",
                ),
                correct_index=1,
                explanation="Gateway API names prefix matching `PathPrefix` (`Exact` and `RegularExpression` are the other two types).",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="An Ingress used `nginx.ingress.kubernetes.io/rewrite-target: /` on `/v2/orders`. You migrate to `HTTPRoute` with `PathPrefix: /v2/orders` and the backend starts throwing 404 because it expects `/`. Which `HTTPRoute` feature fixes this?",
                choices=(
                    "`parentRefs[].sectionName`",
                    "`rules[].filters` with `type: URLRewrite` (`replacePrefixMatch: /`)",
                    "`backendRefs[].weight`",
                    "`GatewayClass` parameters",
                ),
                correct_index=1,
                explanation="`HTTPRoute` replaces vendor rewrite annotations natively using `filters[].type: URLRewrite` (`path.type: ReplacePrefixMatch`).",
            ),
        ),
    ),
    StudyTopic(
        id="sn-gateway-traffic-split",
        order=23,
        domain=DOMAIN,
        title="Gateway API Canary Splitting, Headers & `URLRewrite`",
        subtitle="Split weighted canary traffic (`80/20`) safely and route by headers or query parameters.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("sn-gateway-canary-weights",),
        summary=(
            "`HTTPRoute` replaces fragile Ingress canary annotations with native first-class traffic management: "
            "proportional weighted splitting across multiple `backendRefs[]` inside a single rule, HTTP header/method matching, "
            "and in-flight request/response header or URL rewrite filters."
        ),
        architecture_flow=(
            "HTTPRoute.rules[] (Rule Precedence: Exact Path > Prefix Length > Headers/Query) -> Single Rule backendRefs: [svc-v1: weight 80, svc-v2: weight 20]"
        ),
        theory_points=(
            "**Golden traffic-splitting rule**: BOTH weighted backends (`v1` and `v2`) MUST live inside ONE rule's `backendRefs[]` list — putting them in two separate `rules[]` items gives 100% traffic to the first matching rule and 0% to the second!",
            "`weight` defaults to `1`; set explicit ratios (e.g., `weight: 80` and `weight: 20`, or `weight: 0` to drain a backend without deleting it).",
            "Rule precedence when multiple rules exist: `Exact` path beats `PathPrefix`; longest prefix beats shorter prefix; header/method/query matches win ties cleanly.",
            "Header matching uses `matches[].headers[]` (`type: Exact | RegularExpression`, `name`, `value`); `RequestHeaderModifier` / `ResponseHeaderModifier` injects or strips headers natively.",
            "Always confirm BOTH `v1` and `v2` Services have healthy Endpoints (`k get endpoints`), otherwise weighted requests hit 503 gaps!",
        ),
        decision_matrix=(
            ComparisonRow("Multiple `backendRefs[]` in ONE rule", "Splits traffic proportionally by `weight` (`w / sum(w)`)", "Canary rollouts (`80/20`, `90/10`) and blue/green drains"),
            ComparisonRow("Separate `rules[]` with `matches[].headers`", "Routes 100% of header-matching requests (`X-Canary: true`) to `v2`", "Header-gated internal QA testing in production"),
            ComparisonRow("`weight: 0` on a backendRef", "Sends 0% traffic while keeping route reference resolved/valid", "Clean instant rollback/drain of canary v2"),
            ComparisonRow("`RequestMirror` filter", "Duplicates live requests asynchronously to mirror Service (fire-and-forget)", "Shadow traffic testing without impacting latency"),
        ),
        docs_links=(
            StudyDocLink(
                label="Gateway API HTTP Traffic Splitting",
                url="https://gateway-api.sigs.k8s.io/guides/traffic-splitting/",
                exam_search_term="traffic splitting HTTPRoute",
            ),
            StudyDocLink(
                label="HTTPRoute API Spec Filters",
                url="https://gateway-api.sigs.k8s.io/guides/http-header-modifier/",
                exam_search_term="HTTPRoute headers filters",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify both `v1` and `v2` Services have healthy Ready Endpoints",
                explanation="Canary splits immediately fail 503 if one target Service has wrong selector or unready Pods.",
                command="k -n <ns> get svc,endpoints",
                verify_command="k -n <ns> get endpoints -o wide",
                expected_output="Both `v1` and `v2` Services display active Pod IP:port addresses",
            ),
            PracticeStep(
                title="Configure weighted `backendRefs` inside ONE `rules[]` item",
                explanation="Use `k explain httproute.spec.rules.backendRefs` if checking field placement under pressure.",
                command="k explain httproute.spec.rules.backendRefs",
                yaml_snippet=(
                    "rules:\n"
                    "- matches:\n"
                    "  - path: { type: PathPrefix, value: / }\n"
                    "  backendRefs:\n"
                    "  - name: web-v1\n"
                    "    port: 80\n"
                    "    weight: 80\n"
                    "  - name: web-v2\n"
                    "    port: 80\n"
                    "    weight: 20"
                ),
            ),
            PracticeStep(
                title="Validate `Accepted=True`, `ResolvedRefs=True`, and exact weights",
                explanation="Print parsed backend weights via jsonpath and verify HTTPRoute Conditions.",
                command="k -n <ns> describe httproute",
                verify_command="k -n <ns> get httproute -o jsonpath='{.items[*].spec.rules[*].backendRefs[*].weight}{\"\\n\"}'",
                expected_output="Prints configured weights (`80 20`) and Conditions `True`",
            ),
        ),
        debug_playbook=(
            DebugRow("Canary `v2` gets 0% traffic despite `weight: 20`", "Placed `v1` and `v2` in two SEPARATE `rules[]` blocks instead of one `backendRefs[]` array", "Combine both `backendRefs` inside the SAME `rules[]` item"),
            DebugRow("Header rule ignored; default catch-all rule always wins", "Header rule lacked path match or conflicted cleanly? Verify `matches` specificity", "Ensure `matches:` inside rule[0] specifies both `path` and `headers` (evaluated as AND within one `matches[]` item)"),
            DebugRow("`ResolvedRefs: False` on canary split", "Typo on `web-v2` Service name or wrong `port:` (Container port vs Service port!)", "Note `backendRefs[].port` MUST match the Kubernetes **`Service.spec.ports[].port`**, NOT containerPort!"),
        ),
        exam_trap=(
            "Putting `v1` (weight 90) and `v2` (weight 10) into two separate `rules[]` objects sends 0% traffic to `v2`! Weighted splitting ONLY works across entries sharing ONE rule's `backendRefs[]` array — and remember `backendRefs[].port` is the **Service port**, not Pod targetPort!"
        ),
        cheatsheet=(
            CheatItem("Weighted split block", "rules[0].backendRefs: [{name: v1, port: 80, weight: 80}, {name: v2, port: 80, weight: 20}]", "Both under SAME rule"),
            CheatItem("Header match block", "matches: [{path: {type: PathPrefix, value: /}, headers: [{name: X-Canary, value: 'true'}]}]", "AND inside one matches item"),
            CheatItem("Inspect weights fast", "k -n <ns> get httproute <r> -o jsonpath='{.spec.rules[*].backendRefs}'", "Verify exact service, port, weight"),
            CheatItem("Explain filters schema", "k explain httproute.spec.rules.filters --recursive", "URLRewrite, Redirect, RequestHeaderModifier"),
            CheatItem("Test canary traffic split", "for i in $(seq 1 10); do curl -s -H 'Host: web.local' http://<gw-ip>/; done", "Observe ~8:2 v1/v2 response mix"),
        ),
        yaml_template=(
            "apiVersion: gateway.networking.k8s.io/v1\n"
            "kind: HTTPRoute\n"
            "metadata:\n"
            "  name: canary-route\n"
            "spec:\n"
            "  parentRefs: [{ name: web-gw }]\n"
            "  rules:\n"
            "  - matches:\n"
            "    - headers: [{ name: X-Canary, value: \"true\" }]\n"
            "    backendRefs: [{ name: web-v2, port: 80 }]\n"
            "  - backendRefs:\n"
            "    - { name: web-v1, port: 80, weight: 80 }\n"
            "    - { name: web-v2, port: 80, weight: 20 }"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="An `HTTPRoute` defines a single rule with `backendRefs`: `svc-a` (`weight: 3`), `svc-b` (`weight: 1`), and `svc-c` (`weight: 0`). What percentage of traffic does `svc-b` receive?",
                choices=(
                    "10%",
                    "25% (`1 / (3 + 1 + 0)`)",
                    "33%",
                    "0% because weights don't sum to 100",
                ),
                correct_index=1,
                explanation="Weights are proportional integers divided by their total sum (`1 / 4 = 25%`); they do not need to sum to 100, and `0` disables `svc-c`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Inside an `HTTPRoute` `matches[]` entry, if you include BOTH `- path: ...` AND `headers: ...` inside ONE array item (single leading `-`), vs two separate list items (`- path:...` and `- headers:...`), what is the difference?",
                choices=(
                    "Single array item performs AND (both path & header must match); two separate `-` items inside `matches[]` perform OR",
                    "YAML rejects headers inside `matches[]`",
                    "They behave identically",
                    "Two items apply `weight: 50`",
                ),
                correct_index=0,
                explanation="Just like `NetworkPolicy` peers, properties sharing one `matches[]` element are ANDed; separate `-` elements in `matches[]` are ORed.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You put `backendRefs` for `svc-v1 (weight: 90)` in `rules[0]` and `svc-v2 (weight: 10)` in `rules[1]`, both matching `/`. How much traffic goes to `svc-v2`?",
                choices=(
                    "10%",
                    "0% — `rules[0]` captures 100% of `/` requests; weighted backends MUST be in the same rule's `backendRefs[]`",
                    "50% round-robin",
                    "API server rejects duplicate paths",
                ),
                correct_index=1,
                explanation="Rules are evaluated independently; weights only divide traffic among backends inside the SAME rule.",
            ),
        ),
    ),
    StudyTopic(
        id="sn-networkpolicies",
        order=24,
        domain=DOMAIN,
        title="NetworkPolicies: Zero-Trust, AND/OR Selectors, `ipBlock` & DNS",
        subtitle="Master Kubernetes Ingress/Egress isolation without breaking CoreDNS or tripping over YAML dash syntax.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("sn-networkpolicy-dns", "sn-networkpolicy-multi-ns"),
        summary=(
            "Pods accept all traffic until ANY `NetworkPolicy` selects them under `Ingress` or `Egress` (`policyTypes`). "
            "Policies are purely additive (never explicit Deny rules), `Ingress` and `Egress` evaluate independently, AND the single most "
            "tested CKA trap is YAML dash indentation separating **AND** (`- namespaceSelector + podSelector`) from **OR** (two `-` entries), alongside keeping UDP/TCP 53 Egress open."
        ),
        architecture_flow=(
            "Target Pods (podSelector) -> Selected by Ingress policy? (Default-Deny unless matched in `from[]` + `ports[]`) | Selected by Egress policy? (Allow matching `to[]` + UDP/TCP 53 CoreDNS)"
        ),
        theory_points=(
            "**YAML Dash Law (`AND` vs `OR`)**: ONE item (`- namespaceSelector: ...` followed WITHOUT a dash by `podSelector: ...`) means **AND** (Pods matching X inside Namespace Y). TWO `-` items mean **OR** (ALL Pods in Namespace Y, OR any matching Pods in the policy's own namespace!).",
            "Namespace scoping quirk: inside `from`/`to`, a bare `podSelector` WITHOUT `namespaceSelector` matches ONLY Pods inside the **policy's own namespace**; a `namespaceSelector: {}` alone allows ALL namespaces.",
            "Every Kubernetes namespace automatically receives label `kubernetes.io/metadata.name=<ns-name>` (`k get ns --show-labels`) — use it cleanly without needing to manually label namespaces unless required!",
            "Whenever `policyTypes` includes `Egress` (`[Ingress, Egress]` or `[Egress]`), outbound DNS resolution BREAKS completely unless you explicitly permit UDP & TCP port `53`!",
            "`ipBlock: {cidr: 10.0.0.0/8, except: [10.0.1.0/24]}` restricts external/CIDR traffic cleanly — note `ipBlock` applies to external/non-Pod CIDRs and cannot mix in the same peer entry as `podSelector`/`namespaceSelector`.",
        ),
        decision_matrix=(
            ComparisonRow("Default-Deny Ingress + Egress", "`podSelector: {}`, `policyTypes: [Ingress, Egress]`, zero rules", "Zero-trust baseline before adding granular allow policies"),
            ComparisonRow("`- namespaceSelector:` + `podSelector:` (1 dash)", "Logical **AND**: matching Pods specifically inside matching namespace", "Allowing ONLY `role=client` Pods from namespace `frontend`"),
            ComparisonRow("`- namespaceSelector:` & `- podSelector:` (2 dashes)", "Logical **OR**: ANY Pod in target ns OR matching Pods in local ns", "Separate independent peer sources (`web` pods OR `monitoring` ns)"),
            ComparisonRow("DNS Egress Allow Block", "`to: [{namespaceSelector: {}}]`, `ports: [UDP/53, TCP/53]`", "MANDATORY whenever restricting Egress on Pods resolving Services"),
        ),
        docs_links=(
            StudyDocLink(
                label="Network Policies",
                url="https://kubernetes.io/docs/concepts/services-networking/network-policies/",
                exam_search_term="Network Policies",
            ),
            StudyDocLink(
                label="Declare Network Policy Guide",
                url="https://kubernetes.io/docs/tasks/administer-cluster/declare-network-policy/",
                exam_search_term="Default deny NetworkPolicy",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Collect Pod labels, namespace labels, and active NetworkPolicies",
                explanation="Inspect built-in `kubernetes.io/metadata.name` labels alongside target Pod labels first.",
                command="k get ns --show-labels && k -n netpol get pods,netpol --show-labels",
                verify_command="k -n netpol describe netpol",
                expected_output="Prints parsed PodSelector, PolicyTypes (`Ingress`/`Egress`), and From/To peer specs cleanly",
            ),
            PracticeStep(
                title="Apply multi-namespace Ingress/Egress policy keeping CoreDNS port 53 open",
                explanation="Notice single-dash AND syntax vs dedicated DNS Egress port 53 rule.",
                command="k -n client apply -f netpol.yaml && k -n client describe netpol client-allow-web-and-dns",
                yaml_snippet=(
                    "apiVersion: networking.k8s.io/v1\n"
                    "kind: NetworkPolicy\n"
                    "metadata:\n"
                    "  name: client-allow-web-and-dns\n"
                    "  namespace: client\n"
                    "spec:\n"
                    "  podSelector:\n"
                    "    matchLabels: { app: client }\n"
                    "  policyTypes: [Egress]\n"
                    "  egress:\n"
                    "  - to:\n"
                    "    - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: web } }\n"
                    "      podSelector: { matchLabels: { app: api } }\n"
                    "    ports:\n"
                    "    - { protocol: TCP, port: 80 }\n"
                    "  - to:\n"
                    "    - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system } }\n"
                    "    ports:\n"
                    "    - { protocol: UDP, port: 53 }\n"
                    "    - { protocol: TCP, port: 53 }"
                ),
            ),
            PracticeStep(
                title="Test BOTH allowed client AND blocked intruder Pods live",
                explanation="Never stop after positive curl — prove disallowed Pods time out with `--max-time 3`.",
                command="k -n client exec deploy/client -- curl -fsS --max-time 3 http://api-svc.web.svc.cluster.local",
                verify_command="k -n other exec deploy/intruder -- curl -fsS --max-time 3 http://api-svc.web.svc.cluster.local",
                expected_output="Client returns HTTP 200; intruder exits non-zero with timeout (`Connection timed out`)",
            ),
        ),
        debug_playbook=(
            DebugRow("Allowed curl times out resolving `api-svc.web.svc.cluster.local` (passes by raw Pod IP)", "Egress policy active on client Pod omitted UDP/TCP port 53 to CoreDNS", "Add Egress rule permitting UDP+TCP port `53` (`k8s-app: kube-dns` in `kube-system`)"),
            DebugRow("Unauthorized Pods in namespace `frontend` CAN still reach `api` Pod", "Used two `-` dashes (`- namespaceSelector` then `- podSelector`) making an OR rule", "Remove the `-` before `podSelector:` so both selectors merge into one AND item"),
            DebugRow("Ingress port rule uses `80`, yet Service `port: 80` forwards `targetPort: 8080` and fails!", "`NetworkPolicy` evaluates traffic AFTER kube-proxy DNAT right at the Pod's interface!", "In `NetworkPolicy` `ports[]`, ALWAYS specify the **container `targetPort` (`8080`)**, NOT Service port (`80`)!"),
        ),
        exam_trap=(
            "TWO top CKA NetworkPolicy traps: (1) adding `- ` before BOTH `namespaceSelector` and `podSelector` turns AND into OR; (2) `NetworkPolicy.ports` filters Pod `targetPort` AFTER kube-proxy NAT (`8080`), NOT the frontend `Service.spec.port` (`80`)!"
        ),
        cheatsheet=(
            CheatItem("Built-in NS labels", "k get ns --show-labels", "Shows `kubernetes.io/metadata.name=<ns>`"),
            CheatItem("Audit parsed policies", "k -n <ns> describe netpol", "Confirms AND vs OR indentation visually!"),
            CheatItem("DNS allow egress rule", "ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]", "Required on Egress policies"),
            CheatItem("Test allowed & blocked", "curl -fsS --max-time 3 http://<svc>.<ns>.svc.cluster.local", "Always verify negative case too"),
            CheatItem("Explain NetworkPolicy", "k explain netpol.spec.ingress.from", "Check ipBlock/namespaceSelector/podSelector"),
        ),
        yaml_template=(
            "apiVersion: networking.k8s.io/v1\n"
            "kind: NetworkPolicy\n"
            "metadata:\n"
            "  name: allow-ingress\n"
            "spec:\n"
            "  podSelector:\n"
            "    matchLabels: { app: api }\n"
            "  policyTypes: [Ingress]\n"
            "  ingress:\n"
            "  - from:\n"
            "    - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: frontend } }\n"
            "      podSelector: { matchLabels: { role: client } }\n"
            "    ports:\n"
            "    - { protocol: TCP, port: 8080 }"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A `ClusterIP` Service `api-svc` exposes `port: 80` mapped to container `targetPort: 8080`. Which port number MUST you allow in an `Ingress` `NetworkPolicy` applied to `api` Pods?",
                choices=(
                    "Port `80` (the Service virtual port)",
                    "Port `8080` (the destination Pod's listening `targetPort` after `kube-proxy` NAT)",
                    "Both `80` and `30080`",
                    "Port `53` only",
                ),
                correct_index=1,
                explanation="Packet filtering for `NetworkPolicy` occurs at the Pod veth boundary after `kube-proxy` translates `ClusterIP:80` to `<PodIP>:8080`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Under `ingress[0].from`, you write:\n`- namespaceSelector: { matchLabels: { env: prod } }`\n`- podSelector: { matchLabels: { app: web } }`\nWhich Pods are permitted?",
                choices=(
                    "Only `app=web` Pods inside namespace `env=prod`",
                    "ALL Pods in any `env=prod` namespace OR any `app=web` Pods inside the policy's own namespace",
                    "API server rejects two selectors under `from:`",
                    "Only CoreDNS Pods",
                ),
                correct_index=1,
                explanation="Two `-` list elements create logical OR; omitting the `-` before `podSelector` merges both conditions into logical AND.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="After applying a strict `policyTypes: [Egress]` NetworkPolicy allowing TCP 8080 to `db-svc`'s namespace, `curl http://db-svc.data.svc.cluster.local:8080` hangs cleanly while `curl http://10.244.2.15:8080` works instantly. What rule was forgotten?",
                choices=(
                    "`ipBlock: 0.0.0.0/0`",
                    "Allowing outbound `UDP` and `TCP` port `53` in `egress` for CoreDNS lookups",
                    "Setting `policyTypes: [Ingress, Egress]`",
                    "Restarting `kube-proxy`",
                ),
                correct_index=1,
                explanation="Restrictive Egress blocks all outbound UDP/TCP unless explicitly allowed — omitting DNS port 53 breaks hostname resolution completely.",
            ),
        ),
    ),
    StudyTopic(
        id="sn-coredns-headless",
        order=25,
        domain=DOMAIN,
        title="Cluster DNS, CoreDNS Corefile & Headless Service DNS",
        subtitle="Trace Pod DNS queries (`<svc>.<ns>.svc.cluster.local`), repair `Corefile`, and configure `clusterIP: None`.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("sn-coredns-config-debug", "sn-headless-service-dns"),
        summary=(
            "CoreDNS (`deploy/coredns` + `cm/coredns` in `kube-system`, fronted by `svc/kube-dns`) resolves internal Kubernetes names: "
            "ClusterIP Services get a single virtual A-record (`<svc>.<ns>.svc.cluster.local`), whereas Headless Services (`clusterIP: None`) "
            "return every Ready Pod IP directly (plus individual `<pod>.<svc>.<ns>.svc.cluster.local` records)."
        ),
        architecture_flow=(
            "Pod (/etc/resolv.conf nameserver -> kube-dns ClusterIP) -> kube-proxy -> coredns Pods (ConfigMap Corefile) -> ClusterIP Service A-Record OR Headless Per-Pod IP list"
        ),
        theory_points=(
            "Pods resolve `nslookup <pod-ip-dashed>.<ns>.pod.cluster.local` for Pods and `<svc>.<ns>.svc.cluster.local` for Services cleanly when `kubernetes cluster.local` plugin runs inside `cm/coredns`.",
            "Edit `k -n kube-system edit configmap coredns` carefully (`Corefile:` plugin order matters: `errors`, `health`, `ready`, `kubernetes`, `forward . /etc/resolv.conf`), then run `k -n kube-system rollout restart deploy/coredns`.",
            "Wait up to 30s or restart CoreDNS after ConfigMap updates so old Pods aren't waiting on kubelet ConfigMap sync cadence (`reload` plugin).",
            "Headless Service (`clusterIP: None`) + StatefulSet (or Deployment/Pod with `hostname` + `subdomain`) enables direct peer DNS resolution without load-balancing VIPs.",
            "Check `k -n kube-system get endpoints kube-dns` FIRST when diagnosing DNS — if empty, CoreDNS Pods aren't Ready!",
        ),
        decision_matrix=(
            ComparisonRow("Normal `ClusterIP` DNS", "Resolves `<svc>.<ns>.svc.cluster.local` to ONE ClusterIP virtual IP", "Standard client-to-backend load balancing via `kube-proxy`"),
            ComparisonRow("Headless (`clusterIP: None`) DNS", "Resolves `<svc>.<ns>.svc.cluster.local` to ALL Ready backend Pod IPs", "StatefulSets, client-side DB clustering, direct Pod peers"),
            ComparisonRow("`dnsPolicy: ClusterFirst` (default)", "Routes Pod queries to `kube-dns` first via `/etc/resolv.conf`", "All normal cluster workloads resolving internal + external names"),
            ComparisonRow("`forward` plugin in `Corefile`", "Forwards non-cluster external lookups to upstream DNS (`/etc/resolv.conf` or corporate DNS)", "Custom external DNS forwarding in exam tasks"),
        ),
        docs_links=(
            StudyDocLink(
                label="DNS for Services and Pods",
                url="https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/",
                exam_search_term="DNS for Services and Pods",
            ),
            StudyDocLink(
                label="Debugging DNS Resolution",
                url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
                exam_search_term="Debugging DNS Resolution",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify CoreDNS health, `kube-dns` Endpoints, and live `Corefile`",
                explanation="Inspect `kube-dns` Service IP, endpoints, and CoreDNS logs right away.",
                command="k -n kube-system get deploy/coredns svc/kube-dns endpoints/kube-dns && k -n kube-system get cm coredns -o yaml",
                verify_command="k -n kube-system logs -l k8s-app=kube-dns --tail=15",
                expected_output="`coredns` `2/2` Running, `kube-dns` Endpoints populated `:53`, clean plugin logs",
            ),
            PracticeStep(
                title="Compare `ClusterIP` vs Headless (`clusterIP: None`) `nslookup` results",
                explanation="Notice headless lookup returns each individual Ready Pod IP rather than a single `10.96.x.y` IP.",
                command="k run dnsutils --rm -it --restart=Never --image=busybox:1.36 -- nslookup kubernetes.default.svc.cluster.local",
                verify_command="k get svc <headless-svc> -o jsonpath='{.spec.clusterIP}{\"\\n\"}'",
                expected_output="`nslookup` prints live Service/Pod A-records; headless prints `None`",
            ),
            PracticeStep(
                title="Restart CoreDNS cleanly after editing `Corefile`",
                explanation="Wait for rollout completion and inspect logs for zero Corefile syntax parse errors.",
                command="k -n kube-system rollout restart deploy/coredns && k -n kube-system rollout status deploy/coredns",
                verify_command="k -n kube-system get pods -l k8s-app=kube-dns",
                expected_output="Updated CoreDNS Pods reach `1/1 Running` with `0` restarts",
            ),
        ),
        debug_playbook=(
            DebugRow("CoreDNS enters `CrashLoopBackOff` right after `Corefile` edit", "Syntax typo or invalid plugin/IP inside `cm/coredns`", "Read `k -n kube-system logs deploy/coredns --previous` and fix Corefile indentation/directive"),
            DebugRow("`nslookup` resolves ClusterIP Services yet fails external `google.com`", "`forward . ...` missing or pointing to unreachable upstream DNS inside `Corefile`", "Verify `forward . /etc/resolv.conf` or host node DNS resolvers"),
            DebugRow("Same-namespace `curl my-svc` fails yet `my-svc.app.svc.cluster.local` works", "Pod runs inside wrong namespace OR `/etc/resolv.conf` `search` domain edited via broken `dnsConfig`", "Inspect `k exec <pod> -- cat /etc/resolv.conf`"),
        ),
        exam_trap=(
            "Editing `ConfigMap coredns` with broken Corefile syntax crashes CoreDNS Pods silently in `CrashLoopBackOff` — ALWAYS inspect `k -n kube-system logs deploy/coredns` right after saving and test an actual `nslookup` from a busybox Pod!"
        ),
        cheatsheet=(
            CheatItem("Inspect CoreDNS Corefile", "k -n kube-system get cm coredns -o yaml", "Audit `kubernetes cluster.local` + `forward`"),
            CheatItem("Read CoreDNS errors", "k -n kube-system logs -l k8s-app=kube-dns --tail=30", "Catches Corefile parse errors"),
            CheatItem("Force CoreDNS reload", "k -n kube-system rollout restart deploy/coredns", "Immediate ConfigMap pickup"),
            CheatItem("Lookup DNS via busybox", "k run d --rm -i --restart=Never --image=busybox:1.36 -- nslookup <svc>.<ns>.svc.cluster.local", "Never `latest` busybox bug -> `:1.28` or `:1.36`!"),
            CheatItem("Create Headless Svc", "k -n <ns> create svc clusterip <name> --clusterip=None --tcp=80:80", "Sets `clusterIP: None` cleanly"),
        ),
        yaml_template=(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: db-headless\n"
            "spec:\n"
            "  clusterIP: None\n"
            "  selector:\n"
            "    app: db\n"
            "  ports:\n"
            "  - port: 5432\n"
            "    targetPort: 5432"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="What IP record(s) does CoreDNS return when a Pod executes `nslookup db-headless.prod.svc.cluster.local` against a Service with `spec.clusterIP: None`?",
                choices=(
                    "10.96.0.10 (the `kube-dns` ClusterIP)",
                    "The individual A-record Pod IPs of every Ready Pod matched by the headless Service's selector",
                    "NXDOMAIN unless an HTTPRoute exists",
                    "Only `controlplane`'s node IP",
                ),
                correct_index=1,
                explanation="Headless Services have no virtual ClusterIP; CoreDNS returns individual Ready Pod A-records directly.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You repaired a broken `forward` plugin line inside `ConfigMap coredns` in `kube-system`. Which command guarantees immediate reload across CoreDNS Pods and verifies clean startup?",
                choices=(
                    "`kubectl restart service kube-dns`",
                    "`kubectl -n kube-system rollout restart deploy/coredns && kubectl -n kube-system rollout status deploy/coredns`",
                    "`kubeadm certs renew coredns`",
                    "`systemctl reload kube-proxy`",
                ),
                correct_index=1,
                explanation="`rollout restart deploy/coredns` immediately cycles CoreDNS Pods onto the updated ConfigMap and exposes any Corefile syntax errors cleanly.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Testing DNS resolution inside an empty namespace reveals `busybox` cannot resolve ANY service, and `k -n kube-system get endpoints kube-dns` prints `<none>`. Which two causes should you inspect FIRST?",
                choices=(
                    "StorageClass default and PVC capacity",
                    "CoreDNS Pods in `kube-system` aren't `Running`/`Ready` (e.g., Corefile crash or node CNI missing)",
                    "NodePort range limits",
                    "RBAC RoleBindings in `default`",
                ),
                correct_index=1,
                explanation="Empty `kube-dns` endpoints means CoreDNS Pods are missing or not Ready (`k -n kube-system get pods -l k8s-app=kube-dns` + logs).",
            ),
        ),
    ),
)
