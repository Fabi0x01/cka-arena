"""CKA Study Codex v2 — Domain 2: Workloads & Scheduling (Topics 10–17)."""

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

DOMAIN = "Workloads & Scheduling"

WORKLOAD_TOPICS: tuple[StudyTopic, ...] = (
    StudyTopic(
        id="wl-deployments-rollouts",
        order=10,
        domain=DOMAIN,
        title="Deployments: Strategies, Rollouts, Pausing & Rollbacks",
        subtitle="Control `maxSurge`/`maxUnavailable`, pause multi-step updates, and undo broken ReplicaSets.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("wl-rollout-undo-strategy",),
        summary=(
            "Deployments orchestrate ReplicaSets declaratively using `RollingUpdate` (zero-downtime surge/unavailable tuning) "
            "or `Recreate` (stop all old Pods first). Mastering `set image`, `rollout status/history/undo/pause/resume/restart` "
            "handles almost every workload lifecycle task in seconds."
        ),
        architecture_flow=(
            "Deployment spec.template change -> New ReplicaSet scaled up (maxSurge) -> Readiness passes -> Old ReplicaSet scaled down (maxUnavailable)"
        ),
        theory_points=(
            "`RollingUpdate` accepts integers or percentages for `maxSurge` (default `25%`) and `maxUnavailable` (default `25%`); `maxSurge: 1, maxUnavailable: 0` strictly preserves full capacity during updates.",
            "`Recreate` deletes all old Pods before booting new Pods — required when Pods hold exclusive `ReadWriteOnce` volumes or singleton hardware locks.",
            "`k rollout pause deploy/<name>` batches multiple `set image` / `set resources` edits cleanly into a SINGLE ReplicaSet transition once `k rollout resume` runs.",
            "`progressDeadlineSeconds` (default `600s`) marks a stalled rollout `Progressing=False` (`ProgressDeadlineExceeded`) cleanly without auto-rolling back.",
            "`k set image` + `k annotate deploy/<name> kubernetes.io/change-cause=\"...\"` (deprecated `--record`) keeps `k rollout history` crystal clear.",
        ),
        decision_matrix=(
            ComparisonRow("`maxUnavailable: 0, maxSurge: 1`", "Creates 1 replacement Pod and waits until Ready before terminating 1 old Pod", "Strict zero-capacity-drop production rollouts"),
            ComparisonRow("`maxSurge: 0, maxUnavailable: 1`", "Terminates 1 old Pod before creating 1 new Pod", "Tight node CPU/memory budgets where spare capacity doesn't fit surge"),
            ComparisonRow("`strategy.type: Recreate`", "Terminates ALL old Pods first, then boots new Pods", "Exclusive `RWO` PVC locks or schema upgrades disallowing v1+v2 overlap"),
            ComparisonRow("`rollout pause` / `resume`", "Holds new ReplicaSet creation until multiple edits finish", "Updating image + limits + env together in one clean revision"),
        ),
        docs_links=(
            StudyDocLink(
                label="Deployments Concept & Rollbacks",
                url="https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
                exam_search_term="Deployments Updating",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Generate and tune a Deployment with RollingUpdate bounds",
                explanation="Use `$do` to scaffold YAML fast, add `strategy.rollingUpdate`, and apply cleanly.",
                command="k create deploy web --image=nginx:1.27-alpine --replicas=3 $do > web.yaml && k apply -f web.yaml",
                verify_command="k rollout status deploy/web --timeout=60s",
                expected_output="`deployment \"web\" successfully rolled out`",
            ),
            PracticeStep(
                title="Update container image cleanly after verifying container name",
                explanation="Always inspect container name(s) first so `k set image` never mismatches.",
                command="k get deploy web -o jsonpath='{.spec.template.spec.containers[*].name}' && k set image deploy/web nginx=nginx:1.27",
                verify_command="k rollout history deploy/web",
                expected_output="Revision numbers incrementing cleanly (1, 2, ...)",
            ),
            PracticeStep(
                title="Roll back to a specific healthy revision and verify Ready replicas",
                explanation="Use `--to-revision=1` (or omit for immediate prior healthy ReplicaSet).",
                command="k rollout undo deploy/web --to-revision=1 && k rollout status deploy/web",
                verify_command="k get rs -l app=web",
                expected_output="Old ReplicaSet scaled back to `3/3` DESIRED/READY; broken RS scaled to `0`",
            ),
        ),
        debug_playbook=(
            DebugRow("`unable to find container named ...` on `set image`", "Deployment container is named `app` or `web`, not the image name", "Check `.spec.template.spec.containers[*].name` before running `set image`"),
            DebugRow("Rollout stalls indefinitely at `1/2` new Pods Ready", "New Pods failing `readinessProbe` or `ImagePullBackOff` while `maxUnavailable: 0` blocks old termination", "Run `k describe pod -l app=...` and fix image/probe or `rollout undo`"),
            DebugRow("`k set image` creates NO new rollout at all", "Deployment is currently paused (`k rollout pause` active)", "Run `k rollout resume deploy/<name>`"),
        ),
        exam_trap=(
            "Running `k set image deploy/web nginx=...` fails when the container inside `spec.template.spec.containers` is named `web` instead of `nginx` — always check container names first (`k get deploy -o jsonpath`)."
        ),
        cheatsheet=(
            CheatItem("Deployment YAML fast", "k -n <ns> create deploy web --image=nginx:1.27-alpine --replicas=3 $do > web.yaml", "Generates selector/labels cleanly"),
            CheatItem("Check container name", "k -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[*].name}'", "Prevents `set image` mismatches"),
            CheatItem("Update image", "k -n <ns> set image deploy/<d> <ctr>=<img:tag>", "Triggers rolling update"),
            CheatItem("Rollout status / undo", "k -n <ns> rollout status deploy/<d> && k -n <ns> rollout undo deploy/<d>", "Verifies or reverts rollout"),
            CheatItem("Inspect revision diff", "k -n <ns> rollout history deploy/<d> --revision=2", "Inspects historical Pod template"),
            CheatItem("Restart Pods zero-diff", "k -n <ns> rollout restart deploy/<d>", "Rotates Pods cleanly after CM edits"),
        ),
        yaml_template=(
            "spec:\n"
            "  replicas: 3\n"
            "  revisionHistoryLimit: 5\n"
            "  strategy:\n"
            "    type: RollingUpdate\n"
            "    rollingUpdate:\n"
            "      maxSurge: 1\n"
            "      maxUnavailable: 0"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Which Deployment strategy guarantees Pod count NEVER drops below `replicas: 4` during an update?",
                choices=(
                    "type: Recreate",
                    "type: RollingUpdate with maxSurge: 1, maxUnavailable: 0",
                    "type: RollingUpdate with maxSurge: 0, maxUnavailable: 1",
                    "spec.minReadySeconds: 0",
                ),
                correct_index=1,
                explanation="`maxUnavailable: 0` forces all 4 existing Pods to stay Ready until a surge Pod (`maxSurge: 1`) passes readiness first.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="After editing a `ConfigMap` mounted via volume (without `subPath`), which single command cleanly rotates Deployment `api` Pods so they mount fresh environment/restart cleanly?",
                choices=(
                    "kubectl reload deploy/api",
                    "kubectl rollout restart deploy/api",
                    "kubectl rollout undo deploy/api",
                    "kubectl refresh deploy/api",
                ),
                correct_index=1,
                explanation="`kubectl rollout restart deploy/<name>` patches `restartedAt` annotation on the Pod template, triggering a standard rolling replacement.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You run `kubectl set image deploy/api app=nginx:1.27` followed by another edit, yet `kubectl get rs` shows zero new ReplicaSet created. Inspecting `deploy/api` shows `spec.paused: true`. What fixes it?",
                choices=(
                    "Increase `revisionHistoryLimit` to 10",
                    "Run `kubectl rollout resume deploy/api`",
                    "Switch strategy to `Recreate`",
                    "Restart `kube-controller-manager`",
                ),
                correct_index=1,
                explanation="Paused Deployments accumulate template changes without starting a new ReplicaSet until `kubectl rollout resume` unpauses them.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-taints-affinity",
        order=11,
        domain=DOMAIN,
        title="Taints, Tolerations, `nodeSelector` & `nodeAffinity`",
        subtitle="Master push-away taints (`NoSchedule`/`NoExecute`), tolerations, and hard/soft node attraction.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("wl-taint-toleration", "wl-node-affinity", "wl-pod-node-selector-hostname"),
        summary=(
            "Taints (`kube-scheduler` repels Pods) and `nodeSelector`/`nodeAffinity` (attracts Pods to labeled nodes) solve two opposite "
            "halves of scheduling. Remembering that Tolerations ONLY permit scheduling onto tainted nodes — rather than pinning Pods away from untainted nodes — "
            "prevents the classic CKA dedicated-node scheduling mistake."
        ),
        architecture_flow=(
            "Scheduler Filter Phase: (Node Labels satisfy nodeSelector + required nodeAffinity?) AND (Pod Tolerations match ALL Node Taints?) -> Scoring Phase (preferred nodeAffinity)"
        ),
        theory_points=(
            "Taint effects: `NoSchedule` blocks new Pods; `PreferNoSchedule` avoids if possible; `NoExecute` blocks new Pods AND immediately evicts existing non-tolerating Pods (unless `tolerationSeconds` delays eviction).",
            "`operator: Exists` omits `value:` (matches any value OR empty taint like `node-role.kubernetes.io/control-plane:NoSchedule`); `operator: Equal` matches `key`, `value`, AND `effect`.",
            "Toleration + `nodeSelector`/`nodeAffinity` together = true **dedicated node isolation** (toleration allows tainted node; affinity prevents spilling onto untainted nodes).",
            "`nodeAffinity` expressions use `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt` under `nodeSelectorTerms[].matchExpressions` (multiple `nodeSelectorTerms` are OR'd; multiple `matchExpressions` within a term are AND'd!).",
            "`IgnoredDuringExecution` means already-running Pods keep running even if node labels change later.",
        ),
        decision_matrix=(
            ComparisonRow("Taint + Toleration alone", "Keeps OTHER Pods off the tainted node; Pod CAN still land on untainted nodes", "Protecting GPU/controlplane nodes from stray workloads"),
            ComparisonRow("`nodeSelector`", "Exact `key: value` equality filter (AND across keys)", "Simple single-label placement (`disk=ssd`)"),
            ComparisonRow("`requiredDuringScheduling...`", "Hard scheduling gate with `In`/`NotIn`/`Exists`/`Gt` operators", "Multi-value or negated rules (`zone In [us-a, us-b]`)"),
            ComparisonRow("`preferredDuringScheduling...`", "Weighted preference (`weight: 1..100`) — schedules even if unmatched", "Soft locality without risking `Pending` Pods"),
        ),
        docs_links=(
            StudyDocLink(
                label="Taints and Tolerations",
                url="https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/",
                exam_search_term="Taints and Tolerations",
            ),
            StudyDocLink(
                label="Assigning Pods to Nodes",
                url="https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/",
                exam_search_term="nodeAffinity",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Audit current node taints and labels before editing workloads",
                explanation="Read exact node taint keys, values, effects, and node labels in one command.",
                command="k get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints --show-labels",
                verify_command="k describe node controlplane | grep -A3 Taints",
                expected_output="`node-role.kubernetes.io/control-plane:NoSchedule` (empty value!)",
            ),
            PracticeStep(
                title="Taint or untaint nodes with `kubectl taint`",
                explanation="Append `-` at the end to remove a taint (`key=val:effect-` or `key:effect-`).",
                command="k taint nodes node01 workload=gpu:NoSchedule && k taint nodes node01 workload=gpu:NoSchedule-",
            ),
            PracticeStep(
                title="Pair Toleration + `requiredDuringScheduling` nodeAffinity",
                explanation="Use `k explain` to double-check `nodeSelectorTerms` list nesting under `spec.template.spec`.",
                command="k explain pod.spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution",
                yaml_snippet=(
                    "spec:\n"
                    "  tolerations:\n"
                    "  - key: workload\n"
                    "    operator: Equal\n"
                    "    value: gpu\n"
                    "    effect: NoSchedule\n"
                    "  affinity:\n"
                    "    nodeAffinity:\n"
                    "      requiredDuringSchedulingIgnoredDuringExecution:\n"
                    "        nodeSelectorTerms:\n"
                    "        - matchExpressions:\n"
                    "          - key: disktype\n"
                    "            operator: In\n"
                    "            values: [\"ssd\"]"
                ),
                verify_command="k get pods -o custom-columns=POD:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase",
                expected_output="Pods running strictly on target node with `Running` phase",
            ),
        ),
        debug_playbook=(
            DebugRow("Pod stays `Pending` (`untolerated taint` in Events)", "Toleration used `operator: Equal` on valueless taint or wrong `effect`", "Switch to `operator: Exists` (omit `value`) or align `effect` (`NoSchedule`)"),
            DebugRow("Pod scheduled onto untainted node despite Toleration", "Tolerations only permit landing on tainted nodes — they never require it", "Add `nodeSelector` or `nodeAffinity` matching the tainted node's label"),
            DebugRow("Wrong `nodeAffinity` nesting (`unknown field`)", "Placed `affinity:` at `Deployment.spec` instead of `Deployment.spec.template.spec`", "Indent `affinity:` and `tolerations:` cleanly inside Pod `spec`"),
        ),
        exam_trap=(
            "Remember the boolean difference inside `nodeSelectorTerms`: TWO items under `nodeSelectorTerms:` (`- matchExpressions...` twice) combine with **OR**, whereas two items under ONE `matchExpressions:` list combine with **AND**!"
        ),
        cheatsheet=(
            CheatItem("Dump taints across cluster", "k get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints", "Check exact key/val/effect"),
            CheatItem("Add taint / Remove taint", "k taint node <n> k=v:NoSchedule  |  k taint node <n> k:NoSchedule-", "Trailing `-` removes taint"),
            CheatItem("Label / unlabel node", "k label node <n> tier=gpu  |  k label node <n> tier-", "Instant nodeSelector target"),
            CheatItem("Toleration for valueless taint", "operator: Exists (omit value!)", "Works for control-plane:NoSchedule"),
            CheatItem("Verify landing nodes", "k get pods -o wide -n <ns>", "Checks scheduled `NODE` column"),
        ),
        yaml_template=(
            "spec:\n"
            "  tolerations:\n"
            "  - key: \"node-role.kubernetes.io/control-plane\"\n"
            "    operator: \"Exists\"\n"
            "    effect: \"NoSchedule\""
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Inside `requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms`, how are two separate `matchExpressions` entries inside ONE `nodeSelectorTerms` item evaluated?",
                choices=(
                    "OR — matching either expression schedules the Pod",
                    "AND — all `matchExpressions` inside a single term must match, while separate `nodeSelectorTerms` are OR'd",
                    "XOR — only one label may exist",
                    "Evaluated alphabetically; last wins",
                ),
                correct_index=1,
                explanation="`matchExpressions` within a `nodeSelectorTerm` are ANDed; multiple `nodeSelectorTerms` entries in the outer array are ORed.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Controlplane node carries `node-role.kubernetes.io/control-plane:NoSchedule` with NO value. How do you tolerate it cleanly?",
                choices=(
                    "`operator: Equal, value: \"true\", effect: NoSchedule`",
                    "`operator: Exists, effect: NoSchedule` (omitting `value`)",
                    "`operator: In, values: [NoSchedule]`",
                    "`nodeSelector: {node-role.kubernetes.io/control-plane: \"\"}`",
                ),
                correct_index=1,
                explanation="Taints with empty/absent values require `operator: Exists` without a `value` field.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You add a matching toleration for `node02`'s taint `gpu=true:NoSchedule` onto Deployment `ml-worker`, yet 1 of its 2 replicas lands on untainted `node01`. Why?",
                choices=(
                    "`NoSchedule` rotates replicas across nodes",
                    "Tolerations allow scheduling onto tainted nodes — without `nodeSelector` or `nodeAffinity`, `node01` remains equally eligible",
                    "Deployment replicas cannot use tolerations",
                    "`node02` automatically re-taints after 30s",
                ),
                correct_index=1,
                explanation="To guarantee Pods ONLY land on `node02`, combine the toleration (push permission) with `nodeSelector` or `nodeAffinity` (pull pin).",
            ),
        ),
    ),
    StudyTopic(
        id="wl-resources-quotas",
        order=12,
        domain=DOMAIN,
        title="Requests, Limits, `ResourceQuota` & `LimitRange`",
        subtitle="Size CPU/memory requests/limits, unblock ReplicaSet quota rejections, and set container defaults.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("wl-resources-cpu", "wl-resource-quota"),
        summary=(
            "`resources.requests` reserves node capacity during scheduling (`kube-scheduler`), whereas `resources.limits` caps runtime "
            "cgroups (CPU gets throttled; Memory triggers `OOMKilled` exit 137). In namespaces with a `ResourceQuota`, any container "
            "omitting requests/limits is rejected by the API server unless a `LimitRange` fills `defaultRequest`/`default`."
        ),
        architecture_flow=(
            "API Server Admission (LimitRange injects defaults -> ResourceQuota checks aggregate headroom) -> kube-scheduler fits Pod `requests` into Node `Allocatable` -> Runtime caps at `limits`"
        ),
        theory_points=(
            "Pod `requests` total = sum of all app `containers[].resources.requests`, OR max of any single `initContainer`'s request — whichever is HIGHER (native sidecars add onto main container requests!).",
            "`ResourceQuota` tracking CPU or memory REQUIRES every Pod admitted into that namespace to specify requests/limits (explicitly or via `LimitRange`).",
            "`LimitRange` `min`/`max` validate upper/lower bounds AND optional `maxLimitRequestRatio` per container/Pod, while `defaultRequest`/`default` supply fallbacks.",
            "Remember binary memory (`Mi`, `Gi` = 1024 base) vs SI (`M`, `G` = 1000 base), and `1000m` millicores = `1` vCPU core.",
            "If `kubectl get deploy` shows `READY 0/2` and ZERO Pods exist (`k get pods` empty), inspect `k describe rs <rs-name>` right away for Quota / LimitRange / SA admission errors!",
        ),
        decision_matrix=(
            ComparisonRow("`resources.requests`", "Guaranteed reservation used ONLY by `kube-scheduler` & HPA denominator", "Sizing Pod placement & CPU auto-scaling accurately"),
            ComparisonRow("`resources.limits`", "Kernel cgroup cap: CPU throttles, Memory `OOMKilled` (`137`)", "Stopping runaway Pods from starving node siblings"),
            ComparisonRow("`ResourceQuota`", "Namespace-wide hard ceiling on sum of Pods/CPU/Memory/PVCs/Services", "Capping total team budget in shared namespaces"),
            ComparisonRow("`LimitRange`", "Per-Pod / per-Container defaults + min/max guardrails", "Preventing naked Pods failing `ResourceQuota` admission"),
        ),
        docs_links=(
            StudyDocLink(
                label="Resource Management for Pods and Containers",
                url="https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
                exam_search_term="Resource Management",
            ),
            StudyDocLink(
                label="Resource Quotas",
                url="https://kubernetes.io/docs/concepts/policy/resource-quotas/",
                exam_search_term="Resource Quotas",
            ),
            StudyDocLink(
                label="Limit Ranges",
                url="https://kubernetes.io/docs/concepts/policy/limit-range/",
                exam_search_term="Limit Ranges",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Create a namespace `ResourceQuota` imperatively",
                explanation="Use `k create quota` (`--hard=...`) and verify `Used` vs `Hard` table output.",
                command="k -n pricing create quota ns-quota --hard=pods=4,requests.cpu=500m,requests.memory=256Mi,limits.cpu=1,limits.memory=512Mi",
                verify_command="k -n pricing describe quota ns-quota",
                expected_output="Shows Resource | Used | Hard breakdown clearly",
            ),
            PracticeStep(
                title="Apply a `LimitRange` so unconfigured containers satisfy Quota",
                explanation="Set `defaultRequest` and `default` limits so naked Pods pass Quota admission automatically.",
                command="k -n pricing apply -f limitrange.yaml",
                yaml_snippet=(
                    "apiVersion: v1\n"
                    "kind: LimitRange\n"
                    "metadata:\n"
                    "  name: container-defaults\n"
                    "  namespace: pricing\n"
                    "spec:\n"
                    "  limits:\n"
                    "  - type: Container\n"
                    "    default: { cpu: 200m, memory: 128Mi }\n"
                    "    defaultRequest: { cpu: 100m, memory: 64Mi }"
                ),
            ),
            PracticeStep(
                title="Resize unschedulable or quota-rejected Deployment requests/limits",
                explanation="Patch resource budgets cleanly with `k set resources` without hand-editing full manifests.",
                command="k -n pricing set resources deploy/web --requests=cpu=100m,memory=64Mi --limits=cpu=200m,memory=128Mi",
                verify_command="k -n pricing rollout status deploy/web --timeout=60s && k -n pricing describe quota",
                expected_output="Rollout succeeds and `Used` counters reflect active Pod requests/limits",
            ),
        ),
        debug_playbook=(
            DebugRow("`READY 0/2` on Deployment with zero Pods created", "ReplicaSet rejected by `ResourceQuota` (`exceeded quota` or `must specify limits/requests`)", "Inspect `k -n <ns> describe rs` to read exact admission error; add resources or `LimitRange`"),
            DebugRow("Pod `Pending`: `Insufficient cpu` or `Insufficient memory`", "Requested CPU/memory > remaining free node `Allocatable`", "Check `k describe nodes` Allocated resources and lower Pod `requests` safely"),
            DebugRow("`LimitRange` rejects Pod `max` violation", "Container requested > `LimitRange.spec.limits[].max`", "Inspect `k -n <ns> describe limitrange` and adjust container requests/limits within min/max"),
        ),
        exam_trap=(
            "Remember `ResourceQuota` changes NEVER retroactively evict already-running Pods — only NEW Pod/ReplicaSet creations pass through admission checks, AND `LimitRange` defaults do NOT apply retroactively to existing Pods."
        ),
        cheatsheet=(
            CheatItem("Create ResourceQuota", "k -n <ns> create quota q --hard=pods=4,requests.cpu=1,limits.memory=1Gi", "Imperative budget creation"),
            CheatItem("Inspect Quota usage", "k -n <ns> describe quota", "Prints Used vs Hard columns"),
            CheatItem("Set Deployment resources", "k -n <ns> set resources deploy/<d> --requests=cpu=100m,memory=64Mi --limits=cpu=200m,memory=128Mi", "Fast resize"),
            CheatItem("Check RS admission error", "k -n <ns> describe rs -l app=<name>", "Finds why 0 Pods appear"),
            CheatItem("Audit node reservations", "k describe nodes | grep -A6 'Allocated resources:'", "Shows % reserved per node"),
        ),
        yaml_template=(
            "apiVersion: v1\n"
            "kind: LimitRange\n"
            "metadata:\n"
            "  name: defaults\n"
            "spec:\n"
            "  limits:\n"
            "  - type: Container\n"
            "    default: { cpu: 200m, memory: 128Mi }\n"
            "    defaultRequest: { cpu: 100m, memory: 64Mi }\n"
            "    min: { cpu: 50m, memory: 32Mi }\n"
            "    max: { cpu: 1, memory: 512Mi }"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A Pod contains 2 regular app containers (`200m` CPU request each) plus 1 classic initContainer (`500m` CPU request). What effective CPU request does `kube-scheduler` evaluate for placement?",
                choices=(
                    "400m (sum of regular containers)",
                    "500m (`max(sum(app containers), max(initContainers))` = `max(400m, 500m)`)",
                    "900m (sum of all three)",
                    "200m (average)",
                ),
                correct_index=1,
                explanation="Classic initContainers exit before app containers start, so effective Pod request equals the higher of sum(app) or max(init). (Note: native sidecar initContainers add onto app sums.)",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="A namespace has a `ResourceQuota` enforcing `requests.cpu: 1` and `limits.memory: 1Gi`. Why might applying a Deployment without a `resources:` block yield `READY 0/2` with NO Pods visible?",
                choices=(
                    "Metrics-server must be installed for ResourceQuotas",
                    "The ReplicaSet fails Pod creation at API admission with `must specify requests.cpu, limits.memory` — inspect `kubectl describe rs`",
                    "The Deployment waits in `kube-scheduler`",
                    "LimitRange deletes the Deployment",
                ),
                correct_index=1,
                explanation="ReplicaSet Pod creation errors appear under `describe rs` Events rather than creating broken Pod objects.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You add a `ResourceQuota` limiting `pods: 2` into a namespace already running 5 Pods. What happens to the 5 existing Pods?",
                choices=(
                    "Kubernetes evicts 3 Pods immediately",
                    "The 5 existing Pods continue running untouched; new Pod creations fail until total drops below 2",
                    "Deployment scales down automatically to 2",
                    "kubelet crashes on worker nodes",
                ),
                correct_index=1,
                explanation="`ResourceQuota` is enforced only during admission of new/updated objects, never evicting already-running workloads.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-capacity-qos-monitoring",
        order=13,
        domain=DOMAIN,
        title="Node Capacity Math, QoS Eviction, `metrics-server` & HPA vs VPA",
        subtitle="Compute node headroom safely, predict OOM/eviction order, rank top consumers, and choose autoscalers.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("wl-resources-cpu", "wl-hpa-autoscale"),
        summary=(
            "Real CKA exams test practical capacity planning: dividing a node's remaining free `Allocatable` CPU/memory cleanly across replicas "
            "(leaving headroom for system/existing Pods!), understanding Pod QoS eviction order (`BestEffort` -> `Burstable` -> `Guaranteed`), "
            "querying live metrics via `kubectl top`, and distinguishing Horizontal vs Vertical Pod Autoscaling."
        ),
        architecture_flow=(
            "Node Allocatable - Existing Pod Requests (Allocated) = Remaining Headroom -> Size N Replicas equally | Memory Pressure Eviction: BestEffort -> Burstable -> Guaranteed"
        ),
        theory_points=(
            "**Classic CKA Capacity Math Exam Question**: inspect `k describe node <n>` (`Allocatable` CPU/Mem minus `Allocated resources` Requests), divide remaining memory/CPU across the target `replicas`, and leave ~10–15% headroom so pods never become `Pending`!",
            "Three QoS classes (auto-computed by Kubernetes from container specs, NOT manually configured): `Guaranteed` (EVERY container has CPU & Mem `requests == limits`), `Burstable` (at least one request/limit set without full equality), `BestEffort` (ZERO requests or limits on every container).",
            "Under node memory pressure (`kubelet` eviction / OOM), Kubernetes kills `BestEffort` Pods FIRST, then `Burstable` exceeding requests, and `Guaranteed` LAST.",
            "`kubectl top nodes` and `kubectl top pods -A --sort-by=cpu` (or `memory`) read from `metrics-server` via `metrics.k8s.io` API; check `metrics-server` Deployments/logs in `kube-system` if `Metrics API not available`.",
            "**HPA vs VPA**: HPA scales **number of replicas** horizontally (`Deployment`/`StatefulSet`); VPA recommends or mutates **CPU/Mem requests & limits** per Pod vertically — NEVER attach both HPA and VPA targeting CPU/Mem simultaneously on the same Deployment without `Custom` metrics separation!",
        ),
        decision_matrix=(
            ComparisonRow("`Guaranteed` QoS", "Every container sets `cpu & memory` with `requests == limits`", "Critical stateful/database Pods needing maximum OOM protection"),
            ComparisonRow("`Burstable` QoS", "Some request/limit set (`requests < limits` or CPU-only)", "General web/worker apps wanting baseline + burst room"),
            ComparisonRow("`BestEffort` QoS", "Zero requests & limits anywhere in the Pod", "Dispensable scratch jobs — FIRST evicted under node pressure"),
            ComparisonRow("HPA vs VPA", "HPA = more/fewer Pods; VPA = bigger/smaller containers", "HPA for stateless web pools; VPA for singletons/sizing baselines"),
        ),
        docs_links=(
            StudyDocLink(
                label="Pod Quality of Service Classes",
                url="https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/",
                exam_search_term="Quality of Service Classes",
            ),
            StudyDocLink(
                label="Node-pressure Eviction",
                url="https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/",
                exam_search_term="Node-pressure Eviction",
            ),
            StudyDocLink(
                label="Reserve Compute Resources for System Daemons",
                url="https://kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources/",
                exam_search_term="Allocatable",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Calculate exact free Allocatable CPU and Memory on worker nodes",
                explanation="Look at `Allocatable:` vs `Allocated resources:` (`Requests` column) — `Node Allocatable = Capacity - kube-reserved - system-reserved`.",
                command="k describe node node01 | grep -A10 -E 'Allocatable:|Allocated resources:'",
                verify_command="k get pods -n <ns> -o custom-columns=POD:.metadata.name,QOS:.status.qosClass",
                expected_output="Lists node free Allocatable budget alongside each Pod's computed `qosClass`",
            ),
            PracticeStep(
                title="Find top CPU and Memory consumers via `kubectl top`",
                explanation="Exam task: 'Find the Pod consuming most CPU in namespace X and write its name to `/opt/top-pod.txt`.'",
                command="k top pods -A --sort-by=cpu --no-headers | head -n 5 && k top nodes --sort-by=memory",
                verify_command="k top pods -A --containers | head -n 8",
                expected_output="Ordered live millicore (`m`) and Mebibyte (`Mi`) utilization metrics",
            ),
            PracticeStep(
                title="Configure a `Guaranteed` QoS Deployment fitting remaining node capacity",
                explanation="Match `requests` == `limits` for both `cpu` and `memory` across every container (including initContainers!).",
                command="k explain pod.status.qosClass",
                yaml_snippet=(
                    "resources:\n"
                    "  requests:\n"
                    "    cpu: \"100m\"\n"
                    "    memory: \"128Mi\"\n"
                    "  limits:\n"
                    "    cpu: \"100m\"\n"
                    "    memory: \"128Mi\""
                ),
            ),
        ),
        debug_playbook=(
            DebugRow("`error: Metrics API not available` on `k top`", "`metrics-server` missing, crashed, or kubelet TLS SANs fail without `--kubelet-insecure-tls`", "Check `k -n kube-system logs deploy/metrics-server` and `k get apiservice v1beta1.metrics.k8s.io`"),
            DebugRow("Pod assigned `Burstable` instead of `Guaranteed`", "Set `cpu` `requests == limits` on container 0, but forgot `memory` (or skipped sidecar container)", "Ensure ALL containers declare identical CPU & memory `requests` and `limits`"),
            DebugRow("4-replica Pod splits cleanly mathematically yet 1 stays `Pending`", "DaemonSets (`kube-proxy`, CNI) and existing system Pods already reserve part of `Allocatable`", "Subtract `Allocated resources -> Requests` first from `Allocatable`, then divide cleanly with headroom"),
        ),
        exam_trap=(
            "Setting `requests == limits` on container #1 while leaving an initContainer or sidecar without equal `requests == limits` drops the entire Pod from `Guaranteed` down to `Burstable`! Also note `k top pods --sort-by=cpu` skips `--no-headers` alignment carefully when saving top Pod name."
        ),
        cheatsheet=(
            CheatItem("Top CPU Pod name only", "k -n <ns> top pods --sort-by=cpu --no-headers | head -n1 | awk '{print $1}'", "Classic CKA top-consumer extraction"),
            CheatItem("Top Memory Nodes", "k top nodes --sort-by=memory", "Checks RAM hotspots"),
            CheatItem("Print Pod QoS classes", "k get pods -A -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,QOS:.status.qosClass", "Audits Guaranteed/Burstable/BestEffort"),
            CheatItem("Node Allocatable minus Used", "k describe nodes | grep -A6 'Allocated resources:'", "Verify scheduler CPU/Mem headroom"),
            CheatItem("Check Metrics API health", "k get apiservice v1beta1.metrics.k8s.io", "Confirms `Available: True`"),
        ),
        yaml_template=(
            "# Division formula for CKA node-headroom sizing:\n"
            "# Free_Mem = Node.Allocatable.memory - Node.AllocatedRequests.memory\n"
            "# Per_Replica_Request <= (Free_Mem * 0.85) / target_replicas  (assign equal requests==limits for Guaranteed QoS)"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Under severe node memory pressure, in what order does `kubelet` rank and evict Pods that exceed requests?",
                choices=(
                    "Guaranteed -> Burstable -> BestEffort",
                    "BestEffort -> Burstable -> Guaranteed",
                    "Newest Pods -> Oldest Pods regardless of resources",
                    "DaemonSets -> Static Pods -> Deployments",
                ),
                correct_index=1,
                explanation="`BestEffort` Pods have no memory guarantees and are evicted first, followed by `Burstable` exceeding requests, with `Guaranteed` evicted last.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which combination inside a multi-container Pod gives it `status.qosClass: Guaranteed`?",
                choices=(
                    "Setting `limits.memory == requests.memory` on container 0 only",
                    "Setting `requests == limits` for BOTH `cpu` AND `memory` on EVERY container (and initContainer) in the Pod",
                    "Adding annotation `qos.kubernetes.io/class: Guaranteed`",
                    "Setting `requests` without `limits`",
                ),
                correct_index=1,
                explanation="Every container in the Pod must declare identical non-zero CPU and Memory `requests` and `limits` to earn `Guaranteed` QoS.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Why is running BOTH HPA (scaling on CPU utilization) and VPA (`updateMode: Auto` adjusting CPU requests) simultaneously on the same Deployment dangerous?",
                choices=(
                    "VPA deletes metrics-server",
                    "HPA scales replicas by CPU % while VPA simultaneously mutates the `requests.cpu` denominator, causing thrashing oscillations",
                    "HPA only supports `Guaranteed` Pods",
                    "API server locks VPA on `apps/v1` Deployments",
                ),
                correct_index=1,
                explanation="VPA resizing `requests.cpu` directly changes the CPU utilization percentage seen by HPA (`usage / request`), creating feedback loops.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-hpa-autoscaling",
        order=14,
        domain=DOMAIN,
        title="HorizontalPodAutoscaler (`autoscaling/v2`) & Scaling Behavior",
        subtitle="Autoscale workloads on CPU/memory metrics and tune scale-up/scale-down stabilization windows.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("wl-hpa-autoscale",),
        summary=(
            "`HorizontalPodAutoscaler` (`autoscaling/v2`) polls `metrics-server` every 15s and adjusts target replicas "
            "using `desiredReplicas = ceil(currentReplicas * currentMetric / desiredMetric)`. `autoscaling/v2` adds multiple "
            "Resource/Pod metrics alongside `spec.behavior` stabilization windows to prevent replica flapping."
        ),
        architecture_flow=(
            "metrics-server -> metrics.k8s.io API -> kube-controller-manager (HPA loop ~15s) -> Compute desiredReplicas vs requests -> Scale Deployment/StatefulSet"
        ),
        theory_points=(
            "`k autoscale deploy <d> --min=2 --max=6 --cpu-percent=70` scaffolds a valid `autoscaling/v2` HPA immediately.",
            "HPA `Utilization` percentages divide live usage by `container.resources.requests.<cpu|memory>` — omitting `requests` stalls HPA at `<unknown>` forever!",
            "`autoscaling/v2` supports `Resource` (`cpu`, `memory` via `Utilization` or `AverageValue`), `Pods`, `Object`, and `External` metrics.",
            "`spec.behavior.scaleDown.stabilizationWindowSeconds` (default `300s` = 5 min) delays scale-down to prevent flapping under spiky traffic; `policies` limit step percentages or Pod counts per period.",
            "Remember if HPA scales a Deployment while someone re-applies static `Deployment.spec.replicas`, `kubectl apply` fights HPA unless `replicas` stays managed by HPA.",
        ),
        decision_matrix=(
            ComparisonRow("`type: Utilization`", "Percentage of container `requests` (e.g., `averageUtilization: 60`)", "CPU/Memory scaling relative to requested baseline"),
            ComparisonRow("`type: AverageValue`", "Absolute usage per Pod (e.g., `200Mi`, `500m`) regardless of requests", "When targeting exact MiB or RPS per Pod"),
            ComparisonRow("`behavior.scaleDown.stabilizationWindowSeconds`", "Looks back over N seconds before shrinking replicas (default `300s`)", "Required CKA tasks setting `stabilizationWindowSeconds: 30`"),
            ComparisonRow("`k autoscale ... $do`", "Generates clean `autoscaling/v2` YAML in 2 seconds", "Adding custom `behavior:` or `memory` metrics rapidly"),
        ),
        docs_links=(
            StudyDocLink(
                label="Horizontal Pod Autoscaling",
                url="https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
                exam_search_term="HorizontalPodAutoscaler",
            ),
            StudyDocLink(
                label="HPA Walkthrough (`autoscaling/v2`)",
                url="https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/",
                exam_search_term="stabilizationWindowSeconds",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Confirm the target Deployment declares `resources.requests.cpu`",
                explanation="If missing, add `requests.cpu` first via `k set resources` before testing HPA.",
                command="k -n dispatch get deploy worker -o jsonpath='{.spec.template.spec.containers[*].resources}'",
                verify_command="k -n dispatch top pods",
                expected_output="Deployment lists explicit `requests.cpu` and `k top pods` returns numeric usage",
            ),
            PracticeStep(
                title="Generate `autoscaling/v2` HPA and configure `scaleDown` behavior if required",
                explanation="Start with `k autoscale ... $do > hpa.yaml`, add `behavior:` if asked, and apply cleanly.",
                command="k -n dispatch autoscale deploy worker --min=2 --max=6 --cpu-percent=65 $do > hpa.yaml && k apply -f hpa.yaml",
                yaml_snippet=(
                    "behavior:\n"
                    "  scaleDown:\n"
                    "    stabilizationWindowSeconds: 30\n"
                    "    policies:\n"
                    "    - type: Pods\n"
                    "      value: 1\n"
                    "      periodSeconds: 30"
                ),
            ),
            PracticeStep(
                title="Verify live `TARGETS`, conditions, and replica boundaries",
                explanation="Wait ~15–30s after apply so `TARGETS` leaves `<unknown>` and shows `ScalingActive: True`.",
                command="k -n dispatch get hpa && k -n dispatch describe hpa worker",
                verify_command="k -n dispatch get hpa worker -o jsonpath='{.status.conditions[*].type}{\"=\"}{.status.conditions[*].status}'",
                expected_output="`AbleToScale=True` and `ScalingActive=True`",
            ),
        ),
        debug_playbook=(
            DebugRow("`TARGETS` stays `<unknown>/70%` indefinitely", "Deployment container lacks `resources.requests.cpu` OR `metrics-server` failed", "Inspect `describe hpa` Events (`FailedGetResourceMetric`) and add `requests.cpu`"),
            DebugRow("HPA `ScalingActive: False` (`FailedComputeMetricsReplicas`)", "Multi-container Pod has ONE sidecar missing `requests.cpu`", "All containers inside the target Pod must define `requests` for Resource metrics"),
            DebugRow("`kubectl get hpa` shows HPA not scaling down after load drops", "Default `scaleDown.stabilizationWindowSeconds` waits 5 minutes (`300s`)", "Inspect `spec.behavior` or add `stabilizationWindowSeconds: 30` when requested"),
        ),
        exam_trap=(
            "If a Pod has TWO containers (app + sidecar) and even ONE container omits `resources.requests.cpu`, HPA prints `<unknown>` and refuses to compute CPU utilization across the Pod!"
        ),
        cheatsheet=(
            CheatItem("Imperative HPA", "k -n <ns> autoscale deploy <d> --min=1 --max=5 --cpu-percent=80", "Instant `autoscaling/v2` HPA"),
            CheatItem("HPA YAML template", "k -n <ns> autoscale deploy <d> --min=2 --max=6 --cpu-percent=70 $do > hpa.yaml", "Add behavior/memory quickly"),
            CheatItem("Inspect HPA metrics", "k -n <ns> describe hpa <name>", "Check TARGETS + ScalingActive events"),
            CheatItem("Check stabilization schema", "k explain hpa.spec.behavior.scaleDown --recursive", "Inline v2 behavior syntax"),
            CheatItem("Check metrics-server", "k top pods -n kube-system", "Verify live metrics endpoint"),
        ),
        yaml_template=(
            "apiVersion: autoscaling/v2\n"
            "kind: HorizontalPodAutoscaler\n"
            "metadata:\n"
            "  name: worker-hpa\n"
            "  namespace: dispatch\n"
            "spec:\n"
            "  scaleTargetRef:\n"
            "    apiVersion: apps/v1\n"
            "    kind: Deployment\n"
            "    name: worker\n"
            "  minReplicas: 2\n"
            "  maxReplicas: 6\n"
            "  metrics:\n"
            "  - type: Resource\n"
            "    resource:\n"
            "      name: cpu\n"
            "      target:\n"
            "        type: Utilization\n"
            "        averageUtilization: 70\n"
            "  behavior:\n"
            "    scaleDown:\n"
            "      stabilizationWindowSeconds: 30"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="An HPA sets `minReplicas: 2, maxReplicas: 10, averageUtilization: 50%` on a Deployment running `2` replicas currently averaging `100%` CPU utilization. Roughly how many replicas does the HPA target?",
                choices=(
                    "3 replicas",
                    "4 replicas (`ceil(2 * (100 / 50))` = 4)",
                    "10 replicas immediately",
                    "2 replicas until `scaleDown` expires",
                ),
                correct_index=1,
                explanation="HPA computes `ceil(2 * 100 / 50) = 4` replicas so average per-Pod CPU drops back near `50%`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Your new HPA continuously shows `TARGETS: <unknown>/60%` while `kubectl top pods` works cleanly. What is almost always missing?",
                choices=(
                    "Every container on the target Deployment must declare `resources.requests.cpu`",
                    "HPA requires `autoscaling/v1` API",
                    "Deployment must use `strategy: Recreate`",
                    "CoreDNS lacks `endpointSlices`",
                ),
                correct_index=0,
                explanation="CPU utilization percentages divide real CPU usage by `resources.requests.cpu`; missing requests on ANY container blocks HPA math.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Load spikes for 20 seconds pushing replicas from 2 to 6, then CPU immediately drops to 5%. With default `autoscaling/v2` HPA settings, why do replicas stay at 6 for ~5 minutes?",
                choices=(
                    "kubelet refuses Pod deletion for 300s",
                    "Default `spec.behavior.scaleDown.stabilizationWindowSeconds` is `300` seconds to avoid thrashing",
                    "ReplicaSets cache old metrics for 10 minutes",
                    "`maxSurge` prevents scale-down",
                ),
                correct_index=1,
                explanation="By default, HPA holds the highest recommended scale-down count across a 300-second stabilization window.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-daemonsets-jobs-cron",
        order=15,
        domain=DOMAIN,
        title="DaemonSets, Jobs & CronJobs",
        subtitle="Schedule per-node agents onto controlplane too, and master batch completions, parallelism & cron policies.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("wl-daemonset-controlplane", "wl-cronjob-policy", "wl-job-backoff-completions"),
        summary=(
            "DaemonSets run one Pod per eligible node (requiring a `control-plane:NoSchedule` toleration to cover controlplane hosts). "
            "Jobs execute batch tasks until `completions` succeed (`parallelism`, `backoffLimit`, `activeDeadlineSeconds`, `ttlSecondsAfterFinished`), "
            "while CronJobs trigger recurring Jobs under `concurrencyPolicy` (`Allow`, `Forbid`, `Replace`)."
        ),
        architecture_flow=(
            "DaemonSet -> Watch Nodes -> Schedule 1 Pod/Node (via nodeAffinity/tolerations)  ||  CronJob (Schedule + ConcurrencyPolicy) -> Job (Completions/Parallelism/BackoffLimit) -> Pod (Never/OnFailure)"
        ),
        theory_points=(
            "No `kubectl create daemonset` exists: generate a Deployment with `$do`, switch `kind: DaemonSet`, and delete `replicas:` and `strategy:` (add `control-plane` toleration if all nodes required!).",
            "Jobs/CronJobs require `restartPolicy: Never` (keeps failed Pods for logs!) or `restartPolicy: OnFailure` (restarts container in place); NEVER `Always`.",
            "`completions: 6, parallelism: 2` runs 2 Pods concurrently until 6 Pods reach `Succeeded`; `backoffLimit: 4` retries up to 4 failed Pods; `activeDeadlineSeconds` aborts slow Jobs.",
            "CronJob `concurrencyPolicy`: `Allow` (overlap OK), `Forbid` (skip next if previous still active), `Replace` (terminate old active Job and start new).",
            "`k create job test-run --from=cronjob/<cj>` runs a CronJob immediately without waiting for schedule ticks.",
        ),
        decision_matrix=(
            ComparisonRow("`restartPolicy: Never`", "Creates a NEW Pod upon container failure; old Pod kept for inspection", "Jobs where preserving failed Pod history/logs matters"),
            ComparisonRow("`restartPolicy: OnFailure`", "Restarts container inside the SAME Pod on node until `backoffLimit`", "Cutting API Pod churn during expected transient retries"),
            ComparisonRow("`concurrencyPolicy: Forbid` vs `Replace`", "`Forbid` skips next run; `Replace` cancels active run and replaces", "Preventing overlapping DB backups vs keeping latest run fresh"),
            ComparisonRow("DaemonSet vs Static Pod", "DaemonSet scheduled across nodes by API; Static Pod local disk YAML", "Cluster-wide log/monitoring/CNI agents vs kube-apiserver/etcd"),
        ),
        docs_links=(
            StudyDocLink(
                label="DaemonSet Overview",
                url="https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/",
                exam_search_term="DaemonSet",
            ),
            StudyDocLink(
                label="Jobs — Run to Completion",
                url="https://kubernetes.io/docs/concepts/workloads/controllers/job/",
                exam_search_term="Jobs completions parallelism",
            ),
            StudyDocLink(
                label="CronJob Configuration",
                url="https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/",
                exam_search_term="CronJob concurrencyPolicy",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Convert `$do` Deployment YAML into a controlplane-covering DaemonSet",
                explanation="Strip `replicas` + `strategy`, change `kind: DaemonSet`, and add `node-role.kubernetes.io/control-plane:NoSchedule` `Exists` toleration.",
                command="k create deploy node-agent --image=busybox:1.36 $do -- sleep 3600 > ds.yaml",
                verify_command="k get ds node-agent && k get pods -l app=node-agent -o wide",
                expected_output="`DESIRED == CURRENT == READY` across all nodes including `controlplane`",
            ),
            PracticeStep(
                title="Scaffold a Job or CronJob cleanly with `$do`",
                explanation="Tune `completions`, `parallelism`, `backoffLimit`, `concurrencyPolicy`, and history limits before applying.",
                command="k create cronjob hourly-check --image=busybox:1.36 --schedule='*/5 * * * *' $do -- sh -c 'echo ok' > cj.yaml && k apply -f cj.yaml",
            ),
            PracticeStep(
                title="Trigger an immediate manual Job from the CronJob and wait cleanly",
                explanation="Prove job execution immediately using `create job --from=cronjob/...` + `k wait`.",
                command="k create job test-now --from=cronjob/hourly-check && k wait --for=condition=complete job/test-now --timeout=60s",
                verify_command="k logs job/test-now",
                expected_output="Prints `ok` cleanly with Pod status `Completed`",
            ),
        ),
        debug_playbook=(
            DebugRow("`unknown field \"spec.replicas\"` applying converted DaemonSet", "Converted `$do` Deployment YAML without stripping `replicas` and `strategy`", "Remove `replicas:` and `strategy:` blocks cleanly before applying"),
            DebugRow("DaemonSet runs 2/3 Pods (`DESIRED 2` instead of `3`)", "`controlplane` taint blocks scheduling unless toleration added", "Add `{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}`"),
            DebugRow("Job creation fails `Unsupported value: \"Always\": supported values: \"OnFailure\", \"Never\"`", "Set or inherited `restartPolicy: Always` inside `Job.spec.template.spec`", "Set `restartPolicy: Never` or `OnFailure`"),
        ),
        exam_trap=(
            "Completed Jobs move Pods to `Completed` (`Ready: False`), NOT `Running`! Never expect `READY 1/1` on a finished Job Pod — verify `COMPLETIONS 1/1` on `k get jobs` or `k wait --for=condition=complete`."
        ),
        cheatsheet=(
            CheatItem("Generate Job YAML", "k create job worker --image=busybox:1.36 $do -- sh -c 'echo ok' > job.yaml", "Sets restartPolicy: Never"),
            CheatItem("Generate CronJob YAML", "k create cronjob cj --image=busybox:1.36 --schedule='*/5 * * * *' $do -- date > cj.yaml", "Includes jobTemplate wrapper"),
            CheatItem("Manual CronJob run", "k create job manual --from=cronjob/<cj>", "Instant one-shot test"),
            CheatItem("Wait Job completion", "k wait --for=condition=complete job/<job> --timeout=60s", "Deterministic completion verify"),
            CheatItem("Check DaemonSet spread", "k get ds -A && k get pods -l app=<ds> -o wide", "Verify all cluster nodes covered"),
        ),
        yaml_template=(
            "apiVersion: batch/v1\n"
            "kind: CronJob\n"
            "metadata:\n"
            "  name: cleanup\n"
            "spec:\n"
            "  schedule: \"0 * * * *\"\n"
            "  concurrencyPolicy: Forbid\n"
            "  successfulJobsHistoryLimit: 3\n"
            "  failedJobsHistoryLimit: 1\n"
            "  jobTemplate:\n"
            "    spec:\n"
            "      backoffLimit: 2\n"
            "      activeDeadlineSeconds: 60\n"
            "      template:\n"
            "        spec:\n"
            "          restartPolicy: Never\n"
            "          containers:\n"
            "          - name: runner\n"
            "            image: busybox:1.36\n"
            "            command: [\"sh\", \"-c\", \"echo ok\"]"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A CronJob scheduled every minute (`*/1 * * * *`) triggers a script taking 90 seconds. Which `concurrencyPolicy` prevents overlapping runs by simply skipping the next minute until the active Job ends?",
                choices=(
                    "`Allow`",
                    "`Forbid`",
                    "`Replace`",
                    "`SkipExpired`",
                ),
                correct_index=1,
                explanation="`concurrencyPolicy: Forbid` skips starting a new Job whenever the previous run is still active (`Replace` kills the old one).",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="How can you immediately test an existing CronJob `nightly-audit` without waiting for its cron tick?",
                choices=(
                    "`kubectl rollout restart cronjob/nightly-audit`",
                    "`kubectl create job audit-manual --from=cronjob/nightly-audit`",
                    "`kubectl trigger cronjob/nightly-audit`",
                    "`kubectl exec cronjob/nightly-audit -- date`",
                ),
                correct_index=1,
                explanation="`kubectl create job <name> --from=cronjob/<cj>` instantiates an immediate Job directly from the CronJob's `jobTemplate`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You convert `kubectl create deploy log-agent --image=busybox:1.36 $do` into `kind: DaemonSet`, add a control-plane toleration, and `kubectl apply` rejects it. Which leftover Deployment fields must be deleted?",
                choices=(
                    "`metadata.labels` and `containers[].image`",
                    "`spec.replicas`, `spec.strategy`, and any `status:` block",
                    "`spec.selector.matchLabels`",
                    "`restartPolicy: Always`",
                ),
                correct_index=1,
                explanation="`DaemonSetSpec` has no `replicas` or `strategy` fields (use `updateStrategy` if customizing); strict OpenAPI validation rejects leftover Deployment keys.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-stateful-ha-pdb",
        order=16,
        domain=DOMAIN,
        title="StatefulSets, PDBs, `PriorityClass` & Anti-Affinity HA",
        subtitle="Protect HA services with ordered DNS/storage, voluntary disruption budgets, and node spread.",
        estimated_minutes=6,
        exam_frequency="High",
        archetype_ids=("wl-statefulset-headless", "wl-pdb-priorityclass", "wl-pod-antiaffinity-topology"),
        summary=(
            "StatefulSets provide sticky Pod names (`db-0`, `db-1`), deterministic ordered startup/teardown, and per-ordinal PVCs via "
            "`volumeClaimTemplates` backed by a headless Service (`clusterIP: None`). Pair HA workloads with `PodDisruptionBudget` "
            "(guarding `kubectl drain`), `PriorityClass` preemption, and `podAntiAffinity`/`topologySpreadConstraints` across nodes."
        ),
        architecture_flow=(
            "Headless Svc (clusterIP: None) <-> StatefulSet (pod-0 -> pod-1 + PVC-0/PVC-1) | HA Guards: PDB (drain fence) + TopologySpread/AntiAffinity (node separation) + PriorityClass (preemption order)"
        ),
        theory_points=(
            "Every StatefulSet REQUIRES an existing headless Service (`clusterIP: None`) matching `spec.serviceName`; Pods resolve stably at `<pod>-<ordinal>.<svc>.<ns>.svc.cluster.local`.",
            "Scaling down a StatefulSet deletes highest-ordinal Pods (`-2 -> -1`) cleanly yet NEVER deletes auto-created PVCs automatically (`persistentVolumeClaimRetentionPolicy` defaults to `Retain`).",
            "`PodDisruptionBudget` (`policy/v1`) protects voluntary evictions (`kubectl drain`); specify EITHER `minAvailable` OR `maxUnavailable` (never both!) — remember `minAvailable == replicas` deadlocks drains!",
            "`podAntiAffinity` (`topologyKey: kubernetes.io/hostname`) prevents co-locating replicas on the same node (`required...` blocks 3 replicas on 2 workers; `topologySpreadConstraints` with `maxSkew: 1` balances skew cleanly!).",
            "`PriorityClass` (`scheduling.k8s.io/v1`) sets integer `value` (higher = more important) and `preemptionPolicy: PreemptLowerPriority | Never`, attached via `pod.spec.priorityClassName`.",
        ),
        decision_matrix=(
            ComparisonRow("`podAntiAffinity` (`required...`)", "Hard rule: max 1 matching Pod per `topologyKey` (host/zone)", "Strict separation when `replicas <= nodeCount`"),
            ComparisonRow("`topologySpreadConstraints` (`maxSkew: 1`)", "Balances replica counts evenly across zones/nodes even if `replicas > nodes`", "HA spread across 2–3 worker nodes with >= 3 replicas"),
            ComparisonRow("`PDB` (`minAvailable` vs `maxUnavailable`)", "Minimum surviving Pods vs maximum concurrent evictions during drain", "Zero-downtime quorum apps (`minAvailable: 2` of `3`)"),
            ComparisonRow("`PriorityClass` (`preemptionPolicy: Never`)", "Prioritizes queue order without evicting already-running Pods", "Important batch jobs that must wait rather than kill live services"),
        ),
        docs_links=(
            StudyDocLink(
                label="StatefulSets Basics",
                url="https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/",
                exam_search_term="StatefulSets",
            ),
            StudyDocLink(
                label="Pod Disruption Budgets",
                url="https://kubernetes.io/docs/tasks/run-application/configure-pdb/",
                exam_search_term="PodDisruptionBudget",
            ),
            StudyDocLink(
                label="Pod Topology Spread Constraints",
                url="https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/",
                exam_search_term="topologySpreadConstraints",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Create a Headless Service matching StatefulSet `serviceName`",
                explanation="Use `--clusterip=None` so CoreDNS publishes individual Pod A-records directly.",
                command="k create service clusterip db-headless --clusterip=None --tcp=5432:5432 $do > headless-svc.yaml",
                verify_command="k get svc db-headless -o jsonpath='{.spec.clusterIP}{\"\\n\"}'",
                expected_output="Prints `None`",
            ),
            PracticeStep(
                title="Add a `PodDisruptionBudget` & `PriorityClass` imperatively",
                explanation="Notice `k create pdb` (`--min-available` or `--max-unavailable`) and `k create priorityclass` save massive YAML typing.",
                command="k create pdb web-pdb --selector=app=web --min-available=1 && k create priorityclass high-critical --value=100000 --description='Critical apps'",
                verify_command="k get pdb web-pdb && k get pc high-critical",
                expected_output="PDB displays `ALLOWED DISRUPTIONS >= 1` when `replicas > 1`",
            ),
            PracticeStep(
                title="Spread HA replicas across nodes with Anti-Affinity or TopologySpread",
                explanation="Always inspect `nodeName` across Pods to verify replicas actually landed on distinct nodes.",
                command="k explain pod.spec.topologySpreadConstraints --recursive",
                yaml_snippet=(
                    "topologySpreadConstraints:\n"
                    "- maxSkew: 1\n"
                    "  topologyKey: kubernetes.io/hostname\n"
                    "  whenUnsatisfiable: DoNotSchedule\n"
                    "  labelSelector:\n"
                    "    matchLabels:\n"
                    "      app: web"
                ),
                verify_command="k get pods -l app=web -o custom-columns=POD:.metadata.name,NODE:.spec.nodeName",
                expected_output="Replicas spread evenly across `node01` and `node02`",
            ),
        ),
        debug_playbook=(
            DebugRow("`db-1` never creates even though `db-0` exists", "StatefulSet ordered startup blocks `db-1` until `db-0` turns `1/1 Ready`", "Fix `db-0` image/probe/PVC first (`k describe pod db-0`)"),
            DebugRow("`kubectl drain` loops forever `Cannot evict pod as it would violate PDB`", "`ALLOWED DISRUPTIONS` on PDB is `0` (e.g. `minAvailable == replicas`)", "Raise Deployment replicas above `minAvailable` or lower `minAvailable` / raise `maxUnavailable`"),
            DebugRow("3rd replica stays `Pending` with `did not match pod affinity rules`", "Used `requiredDuringScheduling` `podAntiAffinity` across only 2 worker nodes", "Switch to `topologySpreadConstraints` (`maxSkew: 1`) or `preferredDuringScheduling`"),
        ),
        exam_trap=(
            "Setting `minAvailable: 2` on a PDB covering a 2-replica Deployment sets `ALLOWED DISRUPTIONS = 0`, permanently deadlocking `kubectl drain`! Always allow at least 1 disruption during maintenance (`minAvailable: 1` or `maxUnavailable: 1`)."
        ),
        cheatsheet=(
            CheatItem("Headless Service", "k create svc clusterip <name> --clusterip=None --tcp=80:80 $do", "Required for StatefulSet `serviceName`"),
            CheatItem("Imperative PDB", "k -n <ns> create pdb <name> --selector=app=web --min-available=1", "Check `ALLOWED DISRUPTIONS` column"),
            CheatItem("Imperative PriorityClass", "k create priorityclass <pc> --value=100000 --global-default=false", "Attached via `priorityClassName`"),
            CheatItem("Verify node spread", "k -n <ns> get pods -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName", "Proves distinct node placement"),
            CheatItem("Stateful DNS name", "<sts>-0.<headless-svc>.<ns>.svc.cluster.local", "Stable per-ordinal Pod DNS"),
        ),
        yaml_template=(
            "apiVersion: policy/v1\n"
            "kind: PodDisruptionBudget\n"
            "metadata:\n"
            "  name: web-pdb\n"
            "spec:\n"
            "  minAvailable: 1\n"
            "  selector:\n"
            "    matchLabels:\n"
            "      app: web"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why does scaling a 3-replica `Deployment` with hard (`required...`) `podAntiAffinity` (`topologyKey: kubernetes.io/hostname`) leave the 3rd Pod stuck `Pending` on a 2-worker cluster (`controlplane` tainted)?",
                choices=(
                    "`podAntiAffinity` requires `StatefulSets`",
                    "Hard anti-affinity forbids placing two matching Pods on any single node, leaving no 3rd schedulable host — `topologySpreadConstraints` handles even skew across 2 nodes",
                    "Node hostnames cannot match labels",
                    "kube-proxy blocks > 2 Pods per namespace",
                ),
                correct_index=1,
                explanation="Only 2 nodes allow scheduling, so hard anti-affinity allows at most 2 Pods; `topologySpreadConstraints` with `maxSkew: 1` schedules `2 + 1` cleanly.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which two fields MUST align so StatefulSet Pods obtain stable DNS entries `<pod-name>.<svc>.<ns>.svc.cluster.local`?",
                choices=(
                    "Any ClusterIP Service matching namespace",
                    "A headless Service (`spec.clusterIP: None`) whose `metadata.name` matches `StatefulSet.spec.serviceName`",
                    "An ExternalName Service pointing to CoreDNS",
                    "An Ingress rule with TLS",
                ),
                correct_index=1,
                explanation="StatefulSet Pod DNS records only resolve via a governing headless Service (`clusterIP: None`) matching `spec.serviceName`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="`kubectl drain node01` hangs printing `Cannot evict pod as it would violate the pod's disruption budget`. Running `kubectl get pdb` shows `MIN AVAILABLE: 2, ALLOWED DISRUPTIONS: 0` for a 2-replica Deployment. What caused this?",
                choices=(
                    "PDB `minAvailable` equals active replicas (`2`), leaving zero voluntary evictions permitted",
                    "`--ignore-daemonsets` blocks PDBs",
                    "The Deployment lacks a `PriorityClass`",
                    "CoreDNS is paused",
                ),
                correct_index=0,
                explanation="When healthy Pods <= `minAvailable`, PDBs intentionally freeze `kubectl drain` (`ALLOWED DISRUPTIONS = 0`) until capacity increases or PDB bounds relax.",
            ),
        ),
    ),
    StudyTopic(
        id="wl-sidecars-security",
        order=17,
        domain=DOMAIN,
        title="Native Sidecars & Pod/Container `securityContext`",
        subtitle="Build K8s 1.29+ native sidecars (`initContainers` + `restartPolicy: Always`) and harden least-privilege containers.",
        estimated_minutes=6,
        exam_frequency="High",
        archetype_ids=("wl-native-sidecar", "wl-securitycontext-nonroot"),
        summary=(
            "Modern Kubernetes implements native sidecars as `spec.initContainers[]` carrying `restartPolicy: Always` — starting in order "
            "before main `containers[]`, staying alive alongside them, and terminating cleanly once a Job finishes. "
            "For container hardening, `securityContext` drops Linux capabilities, disables privilege escalation, and runs non-root UIDs cleanly."
        ),
        architecture_flow=(
            "Standard Init (runs & exits 0) -> Native Sidecar (initContainers[].restartPolicy: Always -> passes probe -> stays alive) -> Main Containers (start & run; Job ends -> sidecar stopped cleanly)"
        ),
        theory_points=(
            "**Native Sidecar mechanics**: placing `restartPolicy: Always` inside an `initContainers[]` item starts it first, waits for its `startupProbe`/`readinessProbe` (if configured) before starting subsequent init/main containers, and allows Jobs to reach `Completed` when main `containers[]` finish!",
            "Pod `securityContext` fields apply Pod-wide (`runAsNonRoot`, `runAsUser`, `runAsGroup`, `fsGroup`, `seccompProfile.type: RuntimeDefault`), whereas container `securityContext` fields (`allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: {drop: [\"ALL\"], add: [...]}`) ONLY exist at container level!",
            "If `runAsNonRoot: true` is enforced on an image whose Dockerfile runs as `root` (`USER 0`), `kubelet` aborts with `CreateContainerConfigError` UNLESS you explicitly set a numeric `runAsUser` (e.g., `1000`).",
            "Non-root containers cannot bind privileged ports `< 1024` (unless `NET_BIND_SERVICE` is added AND supported) — and `readOnlyRootFilesystem: true` requires writable `emptyDir` mounts for `/tmp` or `/var/run`!",
            "`PodSecurity` Admission namespace labels (`pod-security.kubernetes.io/enforce: restricted`) reject non-compliant Pods directly at ReplicaSet creation (`describe rs` to see PodSecurity failures!).",
        ),
        decision_matrix=(
            ComparisonRow("Native Sidecar (`initContainers[].restartPolicy: Always`)", "Starts before app; stays alive during Pod lifetime; terminates cleanly on Job end", "Log shippers, Envoy/auth proxies, DB tunnel sidecars"),
            ComparisonRow("Pod `securityContext`", "Supports `fsGroup`, `runAsNonRoot`, `runAsUser`, `seccompProfile`", "Setting shared volume ownership (`fsGroup`) + UID defaults"),
            ComparisonRow("Container `securityContext`", "Supports `allowPrivilegeEscalation`, `readOnlyRootFilesystem`, `capabilities`, `privileged`", "Dropping `ALL` capabilities & locking rootfs read-only"),
            ComparisonRow("`fsGroup: 2000`", "Grants group `2000` RW ownership on mounted volumes (`emptyDir`/PVC)", "Ensuring non-root UID can write into mounted volumes"),
        ),
        docs_links=(
            StudyDocLink(
                label="Sidecar Containers",
                url="https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/",
                exam_search_term="Sidecar Containers",
            ),
            StudyDocLink(
                label="Configure a Security Context",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/security-context/",
                exam_search_term="Security Context",
            ),
            StudyDocLink(
                label="Pod Security Standards",
                url="https://kubernetes.io/docs/concepts/security/pod-security-standards/",
                exam_search_term="Pod Security Standards",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify native sidecar schema and configure `initContainers`",
                explanation="Keep `restartPolicy: Always` directly on the sidecar element inside `initContainers[]` (NOT at `Pod.spec`!).",
                command="k explain pod.spec.initContainers.restartPolicy",
                yaml_snippet=(
                    "initContainers:\n"
                    "- name: log-shipper\n"
                    "  image: busybox:1.36\n"
                    "  restartPolicy: Always\n"
                    "  command: [\"sh\", \"-c\", \"tail -n+1 -F /logs/app.log\"]\n"
                    "  volumeMounts:\n"
                    "  - name: shared-logs\n"
                    "    mountPath: /logs"
                ),
            ),
            PracticeStep(
                title="Harden container with Pod Security Restricted `securityContext`",
                explanation="Drop `ALL` capabilities, forbid privilege escalation, enforce non-root UID, and mount `/tmp` if using read-only rootfs.",
                command="k explain pod.spec.containers.securityContext --recursive | head -n 40",
                yaml_snippet=(
                    "securityContext:\n"
                    "  runAsNonRoot: true\n"
                    "  runAsUser: 1000\n"
                    "  allowPrivilegeEscalation: false\n"
                    "  readOnlyRootFilesystem: true\n"
                    "  seccompProfile:\n"
                    "    type: RuntimeDefault\n"
                    "  capabilities:\n"
                    "    drop: [\"ALL\"]"
                ),
                verify_command="k -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].securityContext}'",
                expected_output="`allowPrivilegeEscalation: false`, `runAsNonRoot: true`, `capabilities.drop: [ALL]` cleanly set",
            ),
            PracticeStep(
                title="Verify sidecar container status & UID inside running Pod",
                explanation="Use `exec -- id` or `logs -c` to confirm UID=1000 non-root execution and clean shared log streaming.",
                command="k -n <ns> exec <pod> -c app -- id && k -n <ns> logs <pod> -c log-shipper --tail=5",
                verify_command="k -n <ns> get pod <pod> -o jsonpath='{.spec.initContainers[0].restartPolicy}'",
                expected_output="`uid=1000` printed from container; `Always` printed for sidecar restartPolicy",
            ),
        ),
        debug_playbook=(
            DebugRow("`CreateContainerConfigError: container has runAsNonRoot and image will run as root`", "Image Dockerfile lacks non-root `USER` and Pod omitted `runAsUser`", "Add numeric `runAsUser: 1000` (non-zero!) alongside `runAsNonRoot: true`"),
            DebugRow("App crashes `Read-only file system` with `readOnlyRootFilesystem: true`", "Process writes PID/cache/temp files into `/tmp` or `/var/cache`", "Add `emptyDir` mounts cleanly on writable runtime folders like `/tmp`"),
            DebugRow("`Pod` rejected at RS level under `pod-security.kubernetes.io/enforce: restricted`", "Missing `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, or `capabilities.drop: [ALL]`", "Inspect `k describe rs` Events and apply all 4 Restricted fields"),
        ),
        exam_trap=(
            "Remember `capabilities` and `allowPrivilegeEscalation` belong STRICTLY inside **container** `securityContext` (`containers[].securityContext`), NOT Pod `spec.securityContext` — placing them at Pod level fails YAML schema validation!"
        ),
        cheatsheet=(
            CheatItem("Native sidecar field", "spec.initContainers[].restartPolicy: Always", "Runs concurrently & stops when Job ends"),
            CheatItem("Restricted 4-pack", "runAsNonRoot: true | allowPrivilegeEscalation: false | capabilities.drop: [ALL] | seccompProfile.type: RuntimeDefault", "Passes Pod Security Restricted"),
            CheatItem("Check effective UID", "k -n <ns> exec <pod> -- id", "Verifies non-root UID"),
            CheatItem("Audit NS PodSecurity", "k get ns --show-labels | grep pod-security", "Spots `enforce=restricted` namespaces"),
            CheatItem("Inspect security fields", "k explain pod.spec.containers.securityContext", "Distinguish container vs pod keys"),
        ),
        yaml_template=(
            "spec:\n"
            "  securityContext:\n"
            "    runAsNonRoot: true\n"
            "    runAsUser: 1000\n"
            "    fsGroup: 2000\n"
            "    seccompProfile:\n"
            "      type: RuntimeDefault\n"
            "  containers:\n"
            "  - name: app\n"
            "    image: busybox:1.36\n"
            "    command: [\"sh\", \"-c\", \"sleep 3600\"]\n"
            "    securityContext:\n"
            "      allowPrivilegeEscalation: false\n"
            "      readOnlyRootFilesystem: true\n"
            "      capabilities:\n"
            "        drop: [\"ALL\"]"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why does a native sidecar (`initContainers[].restartPolicy: Always`) fix `Job` hanging issues compared to a classic 2-container Pod?",
                choices=(
                    "InitContainers always run after main containers exit",
                    "Kubernetes considers a Job Pod `Completed` once main `containers[]` terminate, sending SIGTERM to stop native sidecars cleanly",
                    "Native sidecars ignore namespaces",
                    "They automatically convert Jobs to DaemonSets",
                ),
                correct_index=1,
                explanation="Previously, classic sidecars inside `spec.containers[]` kept running forever blocking Job completion; native sidecars terminate cleanly when main app containers exit.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which two `securityContext` fields are VALID ONLY under a container (`spec.containers[].securityContext`) and INVALID directly under Pod `spec.securityContext`?",
                choices=(
                    "`runAsNonRoot` and `fsGroup`",
                    "`allowPrivilegeEscalation` and `capabilities`",
                    "`runAsUser` and `seccompProfile`",
                    "`supplementalGroups` and `runAsGroup`",
                ),
                correct_index=1,
                explanation="`allowPrivilegeEscalation`, `readOnlyRootFilesystem`, `privileged`, and `capabilities` operate per Linux container process and exist only at container level.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You harden an `nginx:1.27-alpine` Pod by setting `runAsNonRoot: true, runAsUser: 1000` and `readOnlyRootFilesystem: true`. The Pod fails with `CreateContainerError` / crash. What commonly breaks?",
                choices=(
                    "nginx tries binding port 80 (<1024) as non-root and writing `/var/cache/nginx` / `/var/run` onto a read-only rootfs",
                    "`1000` is reserved exclusively for etcd",
                    "Kubelet forbids `nginx` from running in non-default namespaces",
                    "`runAsNonRoot` disables ClusterIP Services",
                ),
                correct_index=0,
                explanation="Non-root users cannot bind ports `< 1024` cleanly and cannot write PID/cache paths without writable `emptyDir` mounts (or non-privileged ports like `8080`).",
            ),
        ),
    ),
)
