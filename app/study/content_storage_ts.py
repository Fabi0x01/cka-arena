"""CKA Study Codex v2 — Domains 4 & 5: Storage & Troubleshooting (Topics 26–36)."""

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

ST_DOMAIN = "Storage"
TS_DOMAIN = "Troubleshooting"

STORAGE_TS_TOPICS: tuple[StudyTopic, ...] = (
    StudyTopic(
        id="st-pv-pvc-binding",
        order=26,
        domain=ST_DOMAIN,
        title="PVs, PVCs, AccessModes, `claimRef` & Reclaim Policies",
        subtitle="Bind static PVs to PVCs accurately, rescue `Released` Retained PVs, and fix broken Pod volume claims.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("st-pv-claimref", "st-pod-wrong-claim", "st-reclaim-policy-retain"),
        summary=(
            "PersistentVolumes (`PV`, cluster-scoped) bind 1-to-1 with PersistentVolumeClaims (`PVC`, namespace-scoped) ONLY when "
            "`storageClassName` (`\"\"` vs `<name>`), `accessModes` (`RWO`/`ROX`/`RWX`), and `capacity >= request` match (or `claimRef` pins it). "
            "A PV with `Retain` reclaim policy moves to `Released` when its PVC deletes and stays locked by stale `spec.claimRef` until cleared."
        ),
        architecture_flow=(
            "PV (Available, storageClassName, accessModes, capacity) <-- 1:1 Match --> PVC (Bound) <-- mount -- Pod.spec.volumes (Immutable!)"
        ),
        theory_points=(
            "**3-Gate Binding Rule**: PVC -> PV binds iff (1) `storageClassName` matches identically (note: omitting `storageClassName` on PVC picks the default StorageClass, whereas `storageClassName: \"\"` requests static no-class PVs!), (2) PV supports all requested `accessModes`, and (3) PV `capacity >= PVC request`.",
            "`persistentVolumeReclaimPolicy`: `Retain` keeps the PV (`Released` state) + underlying files after PVC deletion; `Delete` destroys both PV object and dynamically provisioned backing storage.",
            "Rescuing a `Released` PV cleanly without losing disk data: run `kubectl patch pv <pv> --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/claimRef\"}]'` -> status turns back `Available` for re-binding!",
            "Use `spec.claimRef` inside a `PV` (or `volumeName:` inside a `PVC`) when pre-binding a specific PV to a specific PVC unambiguously.",
            "`Pod.spec.volumes` is IMMUTABLE once created — fixing a Pod referencing a wrong PVC (`claimName`) requires exporting `-o yaml`, editing `claimName`, deleting, and re-applying (`k replace --force -f pod.yaml`).",
        ),
        decision_matrix=(
            ComparisonRow("`ReadWriteOnce` (`RWO`)", "Read-write mounted by ONE node at a time", "Databases, single-replica block disks, `hostPath`/`local-path`"),
            ComparisonRow("`ReadOnlyMany` (`ROX`)", "Read-only across many nodes concurrently", "Shared static datasets / ML weights"),
            ComparisonRow("`ReadWriteMany` (`RWX`)", "Read-write across multiple nodes simultaneously", "Shared NFS / CephFS multi-replica web uploads"),
            ComparisonRow("`Retain` vs `Delete` ReclaimPolicy", "`Retain` leaves `Released` PV + files; `Delete` wipes volume", "Protecting critical data from accidental PVC deletion"),
        ),
        docs_links=(
            StudyDocLink(
                label="Persistent Volumes",
                url="https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
                exam_search_term="Persistent Volumes claimRef",
            ),
            StudyDocLink(
                label="Configure a Pod to Use a PersistentVolume",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/configure-persistent-volume-storage/",
                exam_search_term="Configure PersistentVolume",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Compare PV and PVC specs side by side",
                explanation="Audit STATUS (`Available`/`Released`/`Bound`/`Pending`), CAPACITY, ACCESS MODES, and STORAGECLASS.",
                command="k get pv && k -n cka-st-pv get pvc",
                verify_command="k get pv -o custom-columns=NAME:.metadata.name,CAP:.spec.capacity.storage,MODES:.spec.accessModes,SC:.spec.storageClassName,STATUS:.status.phase,CLAIM:.spec.claimRef.name",
                expected_output="Immediately pinpoints mismatched `storageClassName`, `accessModes`, capacity, or stale `claimRef`",
            ),
            PracticeStep(
                title="Rescue a `Released` Retain PV by removing stale `spec.claimRef`",
                explanation="Clearing `/spec/claimRef` preserves existing disk contents and flips PV status back to `Available`.",
                command="k patch pv pv-data --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/claimRef\"}]'",
                verify_command="k get pv pv-data",
                expected_output="STATUS becomes `Available` or immediately `Bound` to waiting matching PVC",
            ),
            PracticeStep(
                title="Fix a Pod referencing a wrong PVC via export + `replace --force`",
                explanation="Strip stale status/resourceVersion if needed or edit `pod.yaml` and run `replace --force` cleanly.",
                command="k -n <ns> get pod web -o yaml > pod.yaml && k -n <ns> replace --force -f pod.yaml",
                verify_command="k -n <ns> get pvc,pod",
                expected_output="PVC status `Bound` and Pod status `Running` (`1/1 Ready`)",
            ),
        ),
        debug_playbook=(
            DebugRow("PVC stuck `Pending` even though larger `Available` PV exists", "`storageClassName` mismatch (PVC picked cluster default SC vs static PV's `manual` or `\"\"`) OR `accessModes` mismatch", "Compare `k describe pvc` & `k get pv -o yaml` for `storageClassName` & `accessModes`"),
            DebugRow("PV shows `Released` cleanly after PVC recreation with identical name", "PV holds stale UID inside `spec.claimRef` pointing to old deleted PVC", "Remove `/spec/claimRef` via JSON patch so new PVC binds cleanly"),
            DebugRow("`Pod updates may not change fields other than ...` editing `claimName`", "`Pod.spec.volumes` cannot be modified in place", "Export Pod YAML, edit `claimName`, and run `k replace --force -f pod.yaml`"),
        ),
        exam_trap=(
            "Remember the difference on a PVC between omitting `spec.storageClassName` (uses the cluster's default StorageClass!) vs setting `storageClassName: \"\"` (disables dynamic provisioning to match static `storageClassName: \"\"` PVs)!"
        ),
        cheatsheet=(
            CheatItem("Inspect PV + PVC columns", "k get pv,pvc -A", "Compare Status, Capacity, Modes, StorageClass"),
            CheatItem("Unbind Released PV", "k patch pv <pv> --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/claimRef\"}]'", "Reuses Retained PV data safely"),
            CheatItem("Switch Delete -> Retain", "k patch pv <pv> -p '{\"spec\":{\"persistentVolumeReclaimPolicy\":\"Retain\"}}'", "Preserves disk after PVC delete"),
            CheatItem("Force-replace immutable Pod", "k -n <ns> replace --force -f pod.yaml", "Recreates Pod cleanly"),
            CheatItem("Inspect PV bind events", "k -n <ns> describe pvc <pvc>", "Explains why PVC hasn't bound"),
        ),
        yaml_template=(
            "apiVersion: v1\n"
            "kind: PersistentVolumeClaim\n"
            "metadata:\n"
            "  name: app-pvc\n"
            "spec:\n"
            "  accessModes: [\"ReadWriteOnce\"]\n"
            "  storageClassName: \"\"\n"
            "  resources:\n"
            "    requests:\n"
            "      storage: 1Gi"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A cluster has an `Available` static PV with `capacity: 5Gi`, `accessModes: [ReadWriteOnce]`, and `storageClassName: \"\"` (empty string). Why does a PVC omitting `storageClassName` stay `Pending` when a default dynamic `StorageClass` exists?",
                choices=(
                    "PVs require `ReadWriteMany`",
                    "Omitting `storageClassName` tells the PVC to ask the cluster's default `StorageClass`, which mismatches `storageClassName: \"\"`",
                    "Static PVs only bind to Deployments, never PVCs directly",
                    "Storage size must be `< 5Gi`",
                ),
                correct_index=1,
                explanation="Explicit `storageClassName: \"\"` is required on a PVC to match static no-class PVs whenever a default StorageClass exists.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="A `Retain` PV sits in `Released` state preserving important files after its old PVC was deleted. Which command makes that same PV `Available` so a new PVC can bind it?",
                choices=(
                    "`kubectl rollout restart pv/pv-data`",
                    "`kubectl patch pv pv-data --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/claimRef\"}]'`",
                    "`kubectl uncordon pv/pv-data`",
                    "`kubectl delete pv pv-data`",
                ),
                correct_index=1,
                explanation="Removing the stale `/spec/claimRef` pointer returns a `Released` PV to `Available` without wiping backing storage.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You try running `kubectl edit pod web` to fix `volumes[0].persistentVolumeClaim.claimName` from `pvc-wrong` to `pvc-right`, and Kubernetes rejects saving. Why?",
                choices=(
                    "`Pod.spec.volumes` is immutable once created — export YAML, delete, and recreate the Pod (`replace --force`)",
                    "Only StatefulSets can mount PVCs",
                    "You must unbind the PV first",
                    "Secrets must mount before PVCs",
                ),
                correct_index=0,
                explanation="Pod volume declarations are immutable; replace the Pod cleanly from exported YAML.",
            ),
        ),
    ),
    StudyTopic(
        id="st-storageclass-dynamic",
        order=27,
        domain=ST_DOMAIN,
        title="StorageClasses, CSI Dynamic Provisioning & Binding Modes",
        subtitle="Manage default StorageClasses, `WaitForFirstConsumer` vs `Immediate`, and immutable PVC class swaps.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("st-pvc-local-path", "st-pvc-storageclass-mismatch"),
        summary=(
            "StorageClasses enable automatic dynamic PV creation via CSI/external provisioners without admin pre-allocation. "
            "Understanding `volumeBindingMode: WaitForFirstConsumer` vs `Immediate`, toggling the default StorageClass annotation "
            "`storageclass.kubernetes.io/is-default-class`, and handling immutable `PVC.spec.storageClassName` avoids top storage pitfalls."
        ),
        architecture_flow=(
            "PVC (requests StorageClass) -> WaitForFirstConsumer: Pod Scheduled to Node X first -> CSI Provisioner creates PV on Node X -> PVC Bound -> Pod Mounts Volume"
        ),
        theory_points=(
            "`WaitForFirstConsumer` intentionally keeps a dynamic PVC in `Pending` until a Pod mounts it AND `kube-scheduler` picks a node — guaranteeing local node storage lands on the same host as the Pod!",
            "`volumeBindingMode: Immediate` creates/binds the PV the instant the PVC appears (can trap a Pod onto a wrong zone/node for local storage).",
            "Cluster default StorageClass carries annotation `storageclass.kubernetes.io/is-default-class: \"true\"` (string `'true'`). Ensure ONLY ONE StorageClass holds `'true'` when reassigning defaults!",
            "`PVC.spec.storageClassName` is IMMUTABLE after creation: switching a wrong StorageClass requires deleting and recreating the PVC.",
            "Remember StorageClass `reclaimPolicy` (`Delete` by default if omitted vs `Retain`) dictates what happens to dynamically created PVs when PVCs delete.",
        ),
        decision_matrix=(
            ComparisonRow("`WaitForFirstConsumer`", "Delays PV binding until consuming Pod gets node-scheduled", "Node-local PVs (`local-path`, host disks, zoned cloud disks)"),
            ComparisonRow("`Immediate`", "Provisions and binds PV the second PVC is applied", "Cluster-wide network storage (NFS/EFS/shared CSI)"),
            ComparisonRow("Default StorageClass annotation", "`storageclass.kubernetes.io/is-default-class: \"true\"`", "Allowing PVCs omitting `storageClassName` to provision dynamically"),
            ComparisonRow("`kubectl delete pvc && apply`", "Replaces immutable `spec.storageClassName` safely", "Fixing PVCs pointing to nonexistent/wrong StorageClass"),
        ),
        docs_links=(
            StudyDocLink(
                label="Storage Classes",
                url="https://kubernetes.io/docs/concepts/storage/storage-classes/",
                exam_search_term="Storage Classes WaitForFirstConsumer",
            ),
            StudyDocLink(
                label="Dynamic Volume Provisioning",
                url="https://kubernetes.io/docs/concepts/storage/dynamic-provisioning/",
                exam_search_term="Dynamic Volume Provisioning",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Audit StorageClasses, default flag, provisioner, and binding modes",
                explanation="Inspect `(default)` marker, provisioner name, reclaimPolicy, and `allowVolumeExpansion`.",
                command="k get sc -o custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,BINDING:.volumeBindingMode,RECLAIM:.reclaimPolicy,EXPAND:.allowVolumeExpansion",
                verify_command="k get sc",
                expected_output="Shows exact `(default)` StorageClass name and binding modes cleanly",
            ),
            PracticeStep(
                title="Separate healthy `WaitForFirstConsumer` PVCs from class mismatches",
                explanation="`k describe pvc` confirms `waiting for first consumer` (healthy!) vs `storageclass.storage.k8s.io \"missing\" not found` (error!).",
                command="k -n <ns> describe pvc <pvc>",
                verify_command="k -n <ns> get events --field-selector involvedObject.kind=PersistentVolumeClaim",
                expected_output="`WaitForFirstConsumer` event vs provisioner error clearly distinguished",
            ),
            PracticeStep(
                title="Switch the cluster default StorageClass cleanly",
                explanation="Always unset `'false'` or `-` on the old default BEFORE or alongside setting `'true'` on the new default.",
                command="k annotate sc <old-sc> storageclass.kubernetes.io/is-default-class=false --overwrite && k annotate sc <new-sc> storageclass.kubernetes.io/is-default-class=true --overwrite",
                verify_command="k get sc",
                expected_output="Only `<new-sc> (default)` shows `(default)` marker",
            ),
        ),
        debug_playbook=(
            DebugRow("`local-path` PVC sits `Pending` while waiting on Deployment", "StorageClass uses `WaitForFirstConsumer`, and consuming Pod itself stays `Pending` (taint/insufficient CPU)", "Fix Pod scheduling issue first (`k describe pod`); once Pod schedules to a node, PVC binds immediately"),
            DebugRow("`kubectl edit pvc` rejects changing `storageClassName`", "`PVC.spec.storageClassName` is immutable", "Export PVC `-o yaml`, delete PVC, edit `storageClassName`, re-apply"),
            DebugRow("Two StorageClasses show `(default)` simultaneously", "Annotated new SC `true` without unsetting previous default SC", "Set `is-default-class=false` (or remove `-`) on the old default"),
        ),
        exam_trap=(
            "If you leave TWO StorageClasses marked `is-default-class: \"true\"`, behavior across Kubernetes controllers becomes ambiguous/unpredictable depending on creation timestamps — ALWAYS unmark the old default StorageClass too!"
        ),
        cheatsheet=(
            CheatItem("Inspect StorageClasses", "k get sc -o wide", "Spot `(default)` + provisioner + WaitForFirstConsumer"),
            CheatItem("Inspect PVC events", "k -n <ns> describe pvc <pvc>", "Separates WaitingForFirstConsumer from errors"),
            CheatItem("Set new default SC", "k annotate sc <sc> storageclass.kubernetes.io/is-default-class=true --overwrite", "Quoted string `'true'`"),
            CheatItem("Unset old default SC", "k annotate sc <old> storageclass.kubernetes.io/is-default-class=false --overwrite", "Keep strictly 1 default SC"),
            CheatItem("Fix wrong PVC StorageClass", "k -n <ns> get pvc <p> -o yaml > p.yaml && k -n <ns> delete pvc <p> && k apply -f p.yaml", "`storageClassName` is immutable"),
        ),
        yaml_template=(
            "apiVersion: storage.k8s.io/v1\n"
            "kind: StorageClass\n"
            "metadata:\n"
            "  name: fast-local\n"
            "provisioner: rancher.io/local-path\n"
            "volumeBindingMode: WaitForFirstConsumer\n"
            "reclaimPolicy: Retain\n"
            "allowVolumeExpansion: true"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why does `local-path` StorageClass configure `volumeBindingMode: WaitForFirstConsumer` by default?",
                choices=(
                    "To make backups faster",
                    "Because host-local directories live on specific nodes — delaying binding until the scheduler places the Pod ensures the PV is provisioned on that exact host",
                    "To force `ReadWriteMany` across nodes",
                    "Because `etcd` forbids dynamic PVs",
                ),
                correct_index=1,
                explanation="If `Immediate` bound a local PV to `node01` while the Pod required `node02`, the Pod would deadlock; `WaitForFirstConsumer` binds after node scheduling.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which annotation key and value marks a `StorageClass` as the cluster's default dynamic provisioner?",
                choices=(
                    "`kubernetes.io/default-storageclass: true`",
                    "`storageclass.kubernetes.io/is-default-class: \"true\"`",
                    "`storage.k8s.io/default: \"yes\"`",
                    "`spec.isDefault: true` inside `StorageClass.spec`",
                ),
                correct_index=1,
                explanation="Default StorageClass status lives in metadata annotation `storageclass.kubernetes.io/is-default-class: \"true\"` (string value).",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You create a PVC with `storageClassName: wait-for-sc`, realize it doesn't exist, and try `kubectl patch pvc data -p '{\"spec\":{\"storageClassName\":\"local-path\"}}'`. Why does it fail?",
                choices=(
                    "`storageClassName` on an existing PVC is immutable — you must delete and recreate the PVC",
                    "`local-path` forbids patches unless `allowVolumeExpansion: true`",
                    "Only cluster-admins can patch PVCs",
                    "You forgot `--type=json`",
                ),
                correct_index=0,
                explanation="Like Pod `volumes`, `PVC.spec.storageClassName` cannot change after creation; recreate the PVC cleanly.",
            ),
        ),
    ),
    StudyTopic(
        id="st-pvc-volume-expansion",
        order=28,
        domain=ST_DOMAIN,
        title="PVC Volume Expansion & Ephemeral vs Persistent Storage",
        subtitle="Grow active Bound PVCs safely without data loss, handle `FileSystemResizePending`, and compare volume types.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("st-pvc-expansion",),
        summary=(
            "Kubernetes allows increasing `PVC.spec.resources.requests.storage` (NEVER shrinking!) strictly when the backing `StorageClass` "
            "declares `allowVolumeExpansion: true`. Volume expansion happens in two phases: CSI controller grows the block/disk volume first, "
            "then node kubelet expands the filesystem (online, or offline upon Pod restart if `FileSystemResizePending` appears)."
        ),
        architecture_flow=(
            "SC allowVolumeExpansion: true -> Patch PVC spec.resources.requests.storage -> CSI expands backing volume -> FileSystemResizePending -> Kubelet grows FS (live or on Pod restart)"
        ),
        theory_points=(
            "Prerequisite check: verify `k get sc <name> -o jsonpath='{.allowVolumeExpansion}'` equals `true`; patch the `StorageClass` (`{\"allowVolumeExpansion\":true}`) first if unset/false!",
            "Kubernetes permits expanding ONLY (`2Gi -> 5Gi`), NEVER shrinking an existing PVC (`5Gi -> 2Gi` rejected at API admission).",
            "Some CSI drivers require Pod restart to complete offline filesystem expansion — watch `describe pvc` Conditions for `FileSystemResizePending: Waiting for user to (re-)start a pod`.",
            "Remember `volumeMode` defaults to `Filesystem` (mounted at `volumeMounts[].mountPath`) vs raw `Block` (`volumeDevices[].devicePath`).",
            "**Storage lifecycle contrast**: `emptyDir` shares Pod lifecycle (wiped on Pod delete, preserved across container crashes — `medium: Memory` uses RAM `tmpfs`!); `hostPath` ties to specific node files; `PVC` persists across Pod reschedules cleanly.",
        ),
        decision_matrix=(
            ComparisonRow("`emptyDir` (`{}` vs `Memory`)", "Created empty with Pod; wiped cleanly on Pod deletion", "Shared Pod log/cache scratch between sidecars & app containers"),
            ComparisonRow("`hostPath`", "Mounts host node file/dir (`DirectoryOrCreate`, `File`)", "Node system agents (`/etc/kubernetes`, `/var/log`, container sockets)"),
            ComparisonRow("`PVC` (`allowVolumeExpansion: true`)", "Lifecycle independent of Pod; grows upward on request patch", "Stateful apps/DBs outgrowing initial capacity without downtime"),
            ComparisonRow("`FileSystemResizePending`", "Disk expanded; awaiting mounted Pod restart/node resize", "Rollout restart Deployment cleanly if PVC Capacity hasn't updated yet"),
        ),
        docs_links=(
            StudyDocLink(
                label="Resizing Persistent Volumes",
                url="https://kubernetes.io/docs/concepts/storage/persistent-volumes/#expanding-persistent-volumes-claims",
                exam_search_term="allowVolumeExpansion",
            ),
            StudyDocLink(
                label="Ephemeral Volumes & emptyDir",
                url="https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/",
                exam_search_term="emptyDir medium Memory",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify or enable `allowVolumeExpansion: true` on the backing StorageClass",
                explanation="Note `allowVolumeExpansion` is a top-level field on `StorageClass` (NOT under `.spec`!).",
                command="k patch sc <sc-name> -p '{\"allowVolumeExpansion\":true}'",
                verify_command="k get sc <sc-name> -o jsonpath='{.allowVolumeExpansion}{\"\\n\"}'",
                expected_output="Prints `true`",
            ),
            PracticeStep(
                title="Patch `PVC.spec.resources.requests.storage` upward",
                explanation="Use strategic merge patch (`k patch pvc`) keeping `accessModes` and `storageClassName` untouched.",
                command="k -n <ns> patch pvc <pvc> -p '{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"2Gi\"}}}}'",
                verify_command="k -n <ns> get pvc <pvc> && k -n <ns> describe pvc <pvc>",
                expected_output="`CAPACITY` shows `2Gi` (or `FileSystemResizePending` clears after Pod restart)",
            ),
            PracticeStep(
                title="Inspect expanded filesystem size directly inside the running Pod",
                explanation="Confirm OS mount inside the Pod (`df -h`) reflects the grown capacity if CSI resized FS live.",
                command="k -n <ns> exec deploy/<d> -- df -h",
            ),
        ),
        debug_playbook=(
            DebugRow("`Forbidden: only dynamically provisioned pvc can be resized and storageclass must support resize`", "Backing `StorageClass.allowVolumeExpansion` is false/missing", "Patch StorageClass `{\"allowVolumeExpansion\":true}` first (`top-level` field, NOT `spec`!)"),
            DebugRow("`Forbidden: field can not be less than previous value`", "Attempted shrinking `spec.resources.requests.storage`", "Keep new storage request strictly larger than current request"),
            DebugRow("`PVC.spec` shows `5Gi`, yet `STATUS.CAPACITY` stuck at `1Gi`", "CSI awaits Pod restart (`FileSystemResizePending`) OR static `hostPath` doesn't support resize", "Inspect `describe pvc`; run `rollout restart` if `FileSystemResizePending` shown"),
        ),
        exam_trap=(
            "Careful with `StorageClass` YAML structure: `provisioner`, `reclaimPolicy`, `volumeBindingMode`, and `allowVolumeExpansion` sit at **TOP LEVEL** of `StorageClass`, NOT nested inside `.spec:`!"
        ),
        cheatsheet=(
            CheatItem("Allow resize on SC", "k patch sc <sc> -p '{\"allowVolumeExpansion\":true}'", "Top-level key on StorageClass"),
            CheatItem("Expand PVC safely", "k -n <ns> patch pvc <pvc> -p '{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"5Gi\"}}}}'", "Increase capacity only"),
            CheatItem("Check resize condition", "k -n <ns> describe pvc <pvc>", "Spot FileSystemResizePending"),
            CheatItem("Restart consuming Pod", "k -n <ns> rollout restart deploy/<d>", "Completes offline CSI filesystem grow"),
            CheatItem("Inspect SC schema", "k explain sc --recursive", "Confirms top-level keys (no `.spec`!)"),
        ),
        yaml_template=(
            "# Remember StorageClass has NO .spec object:\n"
            "apiVersion: storage.k8s.io/v1\n"
            "kind: StorageClass\n"
            "metadata:\n"
            "  name: expandable-sc\n"
            "provisioner: rancher.io/local-path\n"
            "allowVolumeExpansion: true\n"
            "volumeBindingMode: WaitForFirstConsumer"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A Bound PVC was patched from `2Gi` to `5Gi` and shows condition `FileSystemResizePending: Waiting for user to (re-)start a pod to finish file system resize`. What completes resizing?",
                choices=(
                    "Deleting and recreating the PVC",
                    "Deleting/restarting the consuming Pod (`kubectl rollout restart`) so kubelet expands the filesystem cleanly on remount",
                    "Restarting `etcd`",
                    "Changing `reclaimPolicy` to `Delete`",
                ),
                correct_index=1,
                explanation="Volume drivers needing offline filesystem resize complete automatically as soon as the mounted Pod cycles onto its node cleanly.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You attempt `kubectl patch pvc data -p '{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"4Gi\"}}}}'` and Kubernetes rejects it because resizing isn't allowed on that `StorageClass`. Which patch fixes the StorageClass?",
                choices=(
                    "`k patch sc standard -p '{\"spec\":{\"allowVolumeExpansion\":true}}'`",
                    "`k patch sc standard -p '{\"allowVolumeExpansion\":true}'` (top-level key, NO `.spec`)",
                    "`k annotate sc standard allowVolumeExpansion=true`",
                    "`k patch sc standard -p '{\"volumeBindingMode\":\"Expand\"}'`",
                ),
                correct_index=1,
                explanation="`StorageClass` defines `provisioner`, `allowVolumeExpansion`, `reclaimPolicy`, and `volumeBindingMode` at the root object level (not inside `.spec`).",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="A teammate asks you to reclaim disk space by shrinking an over-allocated `10Gi` Bound PVC down to `4Gi` using `kubectl patch pvc`. What happens?",
                choices=(
                    "Kubernetes shrinks the filesystem online automatically",
                    "Kubernetes API server rejects the update because shrinking `PVC.spec.resources.requests.storage` is forbidden",
                    "Kubernetes deletes the PV and recreates a 4Gi PV",
                    "Data is preserved only if `Retain` is set",
                ),
                correct_index=1,
                explanation="Kubernetes validates `requests.storage` monotonically upward; shrinking PVCs requires migrating data to a brand-new smaller PVC.",
            ),
        ),
    ),
    StudyTopic(
        id="st-configmap-secret-vols",
        order=29,
        domain=ST_DOMAIN,
        title="ConfigMap `subPath`, Secret Permissions (`defaultMode`) & Projection",
        subtitle="Mount single config files without wiping directories, lock octal permissions cleanly, and project sources.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("st-configmap-subpath-volume", "st-secret-volume-permissions", "st-emptydir-shared-volume"),
        summary=(
            "Mounting a ConfigMap or Secret directly onto an existing directory like `/etc/nginx/conf.d` hides every baked-in image file "
            "unless you use `subPath` targeting a specific filename. Secret volumes accept YAML octal `defaultMode` (`0400` unquoted = decimal `256`) "
            "and `readOnly: true` to enforce file-mode hygiene cleanly."
        ),
        architecture_flow=(
            "CM/Secret keys -> Volume (items / defaultMode: 0400) -> Container volumeMount: Directory Mount (auto-updates, replaces dir) OR subPath (preserves siblings, static)"
        ),
        theory_points=(
            "**`subPath` rule**: setting `mountPath: /etc/nginx/nginx.conf` + `subPath: nginx.conf` mounts ONLY that single file cleanly without hiding `/etc/nginx/mime.types` or other directory siblings — tradeoff: `subPath` mounts do NOT auto-refresh if the ConfigMap updates later!",
            "`defaultMode` in YAML accepts unquoted integer/octal (`defaultMode: 0400` -> `-r--------`, `0440`, `0644`); quoting `\"0400\"` fails Pod schema validation (`expected int32, got string`)!",
            "Generate Secrets cleanly via CLI (`k create secret generic db-sec --from-literal=pass=s3cr3t` or `--from-file=tls.key`) rather than hand-encoding base64 (`echo -n` trailing newline bugs!).",
            "Env injection (`envFrom: [{configMapRef: ...}]` or `valueFrom.secretKeyRef`) vs Volume mount: Env vars NEVER hot-reload dynamically in running processes, whereas whole-directory volume mounts DO sync updates after ~60s!",
            "Combined `projected` volumes merge multiple Secrets, ConfigMaps, and downwardAPI/serviceAccountToken into one unified mount directory.",
        ),
        decision_matrix=(
            ComparisonRow("Whole-Dir Volume Mount", "Replaces target dir contents; auto-syncs CM updates in ~60s", "Dedicated config dirs like `/etc/app/conf/`"),
            ComparisonRow("`subPath` Single-File Mount", "Preserves sibling image files cleanly; NEVER auto-updates", "Injecting one file into `/etc/nginx/conf.d/` or `/etc/ssl/`"),
            ComparisonRow("`items:` key projection", "Renames key inside volume (`key: app.ini -> path: config.ini`)", "Container expects different filename than ConfigMap key name"),
            ComparisonRow("`defaultMode: 0400`", "Unquoted YAML octal file permission (`256` decimal = owner read)", "Tightening mounted SSH/TLS private keys against world reads"),
        ),
        docs_links=(
            StudyDocLink(
                label="Configure a Pod to Use a ConfigMap",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/",
                exam_search_term="ConfigMap subPath",
            ),
            StudyDocLink(
                label="Distribute Credentials Securely Using Secrets",
                url="https://kubernetes.io/docs/concepts/configuration/secret/",
                exam_search_term="Secrets defaultMode",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Create ConfigMaps & Secrets cleanly with `kubectl create`",
                explanation="Avoid hand-base64 mistakes (`echo` newline injection) by using `--from-literal` or `--from-file`.",
                command="k -n <ns> create cm app-cfg --from-literal=app.conf='listen 80;' && k -n <ns> create secret generic db-tls --from-literal=tls.key=dummy",
                verify_command="k -n <ns> describe cm app-cfg && k -n <ns> describe secret db-tls",
                expected_output="Exact keys listed without accidental trailing whitespace or base64 mismatch",
            ),
            PracticeStep(
                title="Configure `subPath` single-file mount and `defaultMode: 0400` Secret",
                explanation="Ensure `defaultMode` is unquoted YAML octal (`0400`) and `readOnly: true` is set cleanly.",
                command="k explain pod.spec.volumes.secret.defaultMode",
                yaml_snippet=(
                    "volumeMounts:\n"
                    "- name: cfg-vol\n"
                    "  mountPath: /etc/app/app.conf\n"
                    "  subPath: app.conf\n"
                    "  readOnly: true\n"
                    "- name: tls-vol\n"
                    "  mountPath: /etc/tls\n"
                    "  readOnly: true\n"
                    "volumes:\n"
                    "- name: cfg-vol\n"
                    "  configMap: { name: app-cfg }\n"
                    "- name: tls-vol\n"
                    "  secret:\n"
                    "    secretName: db-tls\n"
                    "    defaultMode: 0400"
                ),
            ),
            PracticeStep(
                title="Verify mounted file permissions and sibling preservation inside Pod",
                explanation="Run `ls -la` inside the container via `kubectl exec` to prove exact file mode (`-r--------`) and file contents.",
                command="k -n <ns> exec <pod> -- ls -la /etc/app /etc/tls",
                verify_command="k -n <ns> exec <pod> -- stat -c '%a %n' /etc/tls/tls.key",
                expected_output="Prints `400 /etc/tls/tls.key` cleanly while sibling files in `/etc/app` remain intact",
            ),
        ),
        debug_playbook=(
            DebugRow("`spec.volumes[0].secret.defaultMode: Invalid value: \"0400\"`", "Wrapped octal `0400` in quotes turning it into a YAML string", "Remove quotes cleanly: `defaultMode: 0400` (or integer `256`)"),
            DebugRow("Container fails starting because `/etc/nginx/mime.types` disappeared", "Mounted ConfigMap directly at `/etc/nginx` without `subPath`", "Use `mountPath: /etc/nginx/nginx.conf` + `subPath: nginx.conf`"),
            DebugRow("Pod stuck `CreateContainerConfigError` (`references non-existent secret key`)", "Mismatch between `items[].key` / `subPath` and actual key name inside Secret/ConfigMap", "Inspect exact keys via `k describe cm/secret` (`subPath` checks key inside mounted volume)"),
        ),
        exam_trap=(
            "Quoting `defaultMode: \"0400\"` causes immediate YAML integer schema rejection (`0400` unquoted = YAML octal -> decimal `256`), AND forgetting `subPath` when injecting one file into `/etc/nginx/conf.d/` hides every baked-in file inside that folder!"
        ),
        cheatsheet=(
            CheatItem("Create ConfigMap CLI", "k -n <ns> create cm <cm> --from-literal=k=v --from-file=path", "Auto-escapes multiline files"),
            CheatItem("Create Secret CLI", "k -n <ns> create secret generic <sec> --from-literal=pass=abc", "Avoid manual base64 encoding"),
            CheatItem("Decode Secret key fast", "k -n <ns> get secret <sec> -o jsonpath='{.data.pass}' | base64 -d", "Inspects stored credential"),
            CheatItem("Single-file subPath", "mountPath: /etc/app/app.conf + subPath: app.conf", "Preserves sibling files"),
            CheatItem("Octal Secret perms", "volumes[].secret.defaultMode: 0400", "Unquoted YAML octal!"),
        ),
        yaml_template=(
            "volumeMounts:\n"
            "- name: secret-vol\n"
            "  mountPath: /etc/certs\n"
            "  readOnly: true\n"
            "volumes:\n"
            "- name: secret-vol\n"
            "  secret:\n"
            "    secretName: app-secret\n"
            "    defaultMode: 0400"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Why does updating a `ConfigMap` key fail to propagate inside a running container when mounted via `subPath`, whereas whole-directory mounts DO refresh automatically?",
                choices=(
                    "`subPath` uses a bind-mount directly to a single inode that never updates when kubelet atomically swaps directory symlinks (`..data`)",
                    "ConfigMaps are immutable after `subPath` mount",
                    "Only Secrets refresh under `subPath`",
                    "`readOnly: true` locks content",
                ),
                correct_index=0,
                explanation="kubelet rotates ConfigMap/Secret updates by flipping symlink `..data`; `subPath` binds the single target file inode directly so Pods must restart cleanly to pick up changes.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You want a Secret volume file mounted exclusively readable by container root (`-r--------` = `0400`). Which YAML value under `spec.volumes[].secret` passes API validation?",
                choices=(
                    "`defaultMode: \"0400\"`",
                    "`defaultMode: 0400` (unquoted octal YAML integer, or `256`)",
                    "`defaultMode: r--`",
                    "`permissions: 0400`",
                ),
                correct_index=1,
                explanation="Kubernetes API validates `defaultMode` as `int32`; unquoted `0400` in YAML parses to decimal `256` cleanly while quotes make it an invalid string.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="You mount ConfigMap key `custom.conf` directly onto `/etc/nginx/conf.d/` without `subPath`. What happens to `default.conf` already baked inside that image folder?",
                choices=(
                    "Both files merge alphabetically",
                    "`default.conf` becomes completely hidden underneath the mounted ConfigMap directory",
                    "nginx merges keys automatically",
                    "kubelet rejects overlapping mounts",
                ),
                correct_index=1,
                explanation="Standard Linux volume mounts hide existing folder contents; pairing `mountPath: /etc/nginx/conf.d/custom.conf` with `subPath: custom.conf` preserves existing sibling files.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-controlplane-failures",
        order=30,
        domain=TS_DOMAIN,
        title="Control Plane Failure Triage: `apiserver`, `scheduler` & `controller-manager`",
        subtitle="Diagnose `connection refused` API outages and stalled scheduling directly on `controlplane` via `crictl` & manifests.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ca-controlplane-static-pod-fix", "ca-etcd-restore"),
        summary=(
            "Highest-impact CKA troubleshooting scenarios break controlplane static Pods in `/etc/kubernetes/manifests/`: "
            "if `kube-apiserver` fails (`connection refused` on every `kubectl` call!), you cannot use `kubectl logs` — switch to SSH on `controlplane` "
            "using `sudo crictl ps -a`, `sudo crictl logs`, `/var/log/pods/kube-system_*`, and `kubelet` logs."
        ),
        architecture_flow=(
            "kubectl broken? -> SSH controlplane -> 1. crictl ps -a | grep kube- -> 2. crictl logs <id> / /var/log/pods -> 3. Back up to /tmp/ -> 4. Fix /etc/kubernetes/manifests/<comp>.yaml"
        ),
        theory_points=(
            "**Symptom map across controlplane components**: (1) `kubectl` refuses port `6443` = `kube-apiserver` OR `etcd` down! (2) Pods stuck `Pending` forever with zero Events = `kube-scheduler` down! (3) Deployments create zero ReplicaSets / Nodes stay stale = `kube-controller-manager` down!",
            "Every static Pod YAML lives in `/etc/kubernetes/manifests/` (`kube-apiserver.yaml`, `kube-controller-manager.yaml`, `kube-scheduler.yaml`, `etcd.yaml`). NEVER leave `.bak` files inside `/etc/kubernetes/manifests/`!",
            "Common `kube-apiserver.yaml` breakages: bad CLI flag (`--etcd-servers=https://127.0.0.1:2379` port typo like `2378`), bad TLS cert path, invalid `--authorization-mode`, or invalid `--service-cluster-ip-range`.",
            "Common `kube-scheduler` / `kube-controller-manager` breakages: wrong `--kubeconfig=/etc/kubernetes/scheduler.conf` (`controller-manager.conf`), wrong image tag, wrong `hostPath`, or unknown CLI flag typo!",
            "If `sudo crictl ps -a` shows NOTHING starting for a modified manifest, check `sudo journalctl -u kubelet -n 40` immediately — syntax errors in YAML stop kubelet from even launching the container!",
        ),
        decision_matrix=(
            ComparisonRow("`kubectl` -> `connection refused :6443`", "`kube-apiserver` or backing `etcd` static Pod crashed", "SSH controlplane -> `crictl ps -a`, `crictl logs`, `/var/log/pods/`"),
            ComparisonRow("Pods stuck `Pending` with EMPTY Events", "`kube-scheduler` crashed or missing (`kubectl` still works!)", "`k -n kube-system get pods` or fix `kube-scheduler.yaml` on disk"),
            ComparisonRow("Scaling Deployment adds ZERO new Pods", "`kube-controller-manager` down / unhealthy", "Check `kube-controller-manager-*` Pod logs + `--kubeconfig` path"),
            ComparisonRow("YAML parse bug in manifest", "Container doesn't even appear in `crictl ps -a`", "Read `sudo journalctl -u kubelet -n 40` for YAML decode errors"),
        ),
        docs_links=(
            StudyDocLink(
                label="Troubleshooting Clusters",
                url="https://kubernetes.io/docs/tasks/debug/debug-cluster/",
                exam_search_term="Troubleshoot Clusters",
            ),
            StudyDocLink(
                label="Create Static Pods",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/static-pod/",
                exam_search_term="static Pods",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Identify crashed or missing controlplane static Pods via `crictl`",
                explanation="Use `crictl ps -a` on `controlplane` directly — works completely independently of `kube-apiserver`!",
                command="ssh controlplane 'sudo crictl ps -a | grep -E \"kube-apiserver|kube-scheduler|kube-controller-manager|etcd\"'",
                verify_command="ssh controlplane 'sudo crictl logs --tail=25 $(sudo crictl ps -a --name=kube-apiserver -q | head -n1)'",
                expected_output="Reveals exact flag/TLS/YAML/port failure reason in stderr",
            ),
            PracticeStep(
                title="Back up manifest outside `/etc/kubernetes/manifests` & inspect CLI flags",
                explanation="Always save copies in `/tmp/` — never in `/etc/kubernetes/manifests/`! Inspect args, kubeconfig paths, and volumes.",
                command="sudo cp /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/sched.yaml.bak && sudo grep -nE 'command:|--|--kubeconfig|path:|image:' /etc/kubernetes/manifests/kube-scheduler.yaml",
            ),
            PracticeStep(
                title="Verify kubelet logs + controlplane API & scheduling recovery",
                explanation="If static Pod didn't update within 15s, confirm `kubelet` sees clean YAML and test scheduling a Pod.",
                command="sudo journalctl -u kubelet -n 20 --no-pager && k -n kube-system get pods",
                verify_command="k get --raw='/readyz?verbose' | tail -n 10",
                expected_output="`readyz check passed` and all `kube-system` controlplane Pods `1/1 Running`",
            ),
        ),
        debug_playbook=(
            DebugRow("`kube-apiserver` exits `unknown flag: --enable-admission-plugins=...`", "Misspelled CLI flag or deprecated flag inside `kube-apiserver.yaml`", "Inspect `crictl logs <exited-id>` or `/var/log/pods/kube-system_kube-apiserver*`, fix flag spelling"),
            DebugRow("`kube-scheduler` crashes `stat /etc/kubernetes/scheduler.conf: no such file`", "Wrong `--kubeconfig` flag OR wrong `hostPath.path` volume mount in `kube-scheduler.yaml`", "Compare `hostPath.path` + `mountPath` against real file on host (`/etc/kubernetes/scheduler.conf`)"),
            DebugRow("Edited `/etc/kubernetes/manifests/etcd.yaml` yet Pod unchanged for 60s", "YAML indentation typo caused kubelet manifest parser to reject update", "Run `sudo journalctl -u kubelet -n 30` to see exact line number of YAML error"),
        ),
        exam_trap=(
            "Running `kubectl logs kube-scheduler-controlplane -n kube-system` or `kubectl edit pod` will NEVER survive static Pod restarts — ALL edits to controlplane core services MUST happen inside `/etc/kubernetes/manifests/*.yaml` on the controlplane node (and keep backups outside that folder)!"
        ),
        cheatsheet=(
            CheatItem("Check controlplane containers", "sudo crictl ps -a | grep -E 'apiserver|scheduler|controller|etcd'", "Works even with dead API"),
            CheatItem("Read latest crash log", "sudo crictl logs --tail=30 <container-id>", "Fastest root cause finder"),
            CheatItem("Read pod log fallback", "sudo tail -n 40 /var/log/pods/kube-system_kube-apiserver*/kube-apiserver/*.log", "Persists logs across restarts"),
            CheatItem("Check kubelet manifest errors", "sudo journalctl -u kubelet -n 30 --no-pager", "Catches invalid YAML indentation"),
            CheatItem("Verify API health", "k get --raw='/readyz?verbose'", "Confirms etcd + apiserver health checks"),
        ),
        yaml_template=(
            "# Safe static Pod edit loop on controlplane:\n"
            "# 1. sudo cp /etc/kubernetes/manifests/<comp>.yaml /tmp/<comp>.bak\n"
            "# 2. sudo crictl ps -a && sudo crictl logs <exited-id>\n"
            "# 3. sudo vim /etc/kubernetes/manifests/<comp>.yaml\n"
            "# 4. Wait ~15s -> k get nodes && k -n kube-system get pods"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="`kubectl get pods` works normally, yet every new Deployment stays at `READY 0/1` and new Pods sit `Pending` with zero `Scheduled` events. Which static Pod component is most likely broken?",
                choices=(
                    "`kube-proxy`",
                    "`kube-scheduler` (`/etc/kubernetes/manifests/kube-scheduler.yaml`)",
                    "`CoreDNS`",
                    "`metrics-server`",
                ),
                correct_index=1,
                explanation="If API calls succeed and Pods are created (`Pending`) yet never assigned `.spec.nodeName`, `kube-scheduler` is down or misconfigured.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="`kube-apiserver` is crashing continuously (`connection to localhost:6443 refused`), so `kubectl` cannot run. Which command on `controlplane` reveals why `kube-apiserver` exited?",
                choices=(
                    "`kubectl describe pod kube-apiserver-controlplane -n kube-system`",
                    "`sudo crictl ps -a` to grab container ID + `sudo crictl logs <id>` (or `/var/log/pods/kube-system_kube-apiserver*`)",
                    "`helm list -A`",
                    "`sudo systemctl status kube-apiserver` (systemd unit)",
                ),
                correct_index=1,
                explanation="kubeadm runs `kube-apiserver` as a containerd static Pod, not a systemd service — `crictl ps -a` + `crictl logs` inspects container logs without touching the API.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="After editing `/etc/kubernetes/manifests/kube-controller-manager.yaml` with wrong indentation, `sudo crictl ps -a` stops showing any new container attempts. Where does the exact YAML parse error appear?",
                choices=(
                    "Inside `etcdctl snapshot status`",
                    "Inside `sudo journalctl -u kubelet` on `controlplane`",
                    "Inside `CoreDNS` logs",
                    "Inside `kubeconfig`",
                ),
                correct_index=1,
                explanation="`kubelet` parses `/etc/kubernetes/manifests/*.yaml`; malformed YAML errors are logged directly to kubelet's systemd journal.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-pod-crash-image",
        order=31,
        domain=TS_DOMAIN,
        title="Pod Failures: `CrashLoopBackOff`, `ImagePull` & `OOMKilled`",
        subtitle="Follow deterministic Pod triage (`get -> describe -> logs -p`) and fix exit codes `1`, `127`, and `137`.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ts-crashloop-cmd", "ts-image-pull", "ts-liveness-oom"),
        summary=(
            "App troubleshooting follows a strict 3-command sequence: `kubectl get pods` -> `describe pod` (read `State`, `Last State` termination reason/exit code, and `Events`) "
            "-> `logs -p` (`--previous`). Exit `137` = OOM/SIGKILL, Exit `127` = binary/command missing, Exit `1` = runtime/config error, `ImagePullBackOff` = bad image tag or missing `imagePullSecrets`."
        ),
        architecture_flow=(
            "1. k get pods (Status/Restarts) -> 2. k describe pod (Events + Last State Exit Code) -> 3. k logs <pod> --previous -> Patch Deployment (NEVER edit running Pod template directly)"
        ),
        theory_points=(
            "**Exit Code Key**: `0` = clean exit (normal only on Jobs), `1` = app error/missing config file, `126/127` = permission denied or missing executable/command typo, `137` (`128+9`) = `SIGKILL` / **`OOMKilled`** (check `Last State: Terminated, Reason: OOMKilled`), `143` (`128+15`) = `SIGTERM` graceful stop.",
            "`ImagePullBackOff` / `ErrImagePull`: ALWAYS check exact Events text (`Failed to pull image \"nginx:1.27-missing\"` -> tag typo, private registry without `imagePullSecrets`, or node DNS failure).",
            "Do NOT edit Deployment Pod replicas casually — fix the underlying **`Deployment`** (`set image`, `set resources`, `edit deploy`, `patch deploy`), NOT the ephemeral Pod owned by a ReplicaSet!",
            "Note a broken `livenessProbe` (wrong path/port or low `initialDelaySeconds`) ALSO kills healthy containers with Exit `137`/`143` -> producing `CrashLoopBackOff`!",
            "Use `kubectl logs <pod> -p -c <container>` when debugging multi-container crashed Pods.",
        ),
        decision_matrix=(
            ComparisonRow("`CrashLoopBackOff` (`Last State: Error`, Exit `1`/`127`)", "Container entrypoint or args exits immediately", "Read `k logs <pod> -p` + inspect `command`/`args` on Deployment"),
            ComparisonRow("`OOMKilled` (`Last State: OOMKilled`, Exit `137`)", "Process exceeded cgroup `resources.limits.memory`", "Raise `limits.memory` via `k set resources deploy/<d> --limits=...`"),
            ComparisonRow("`ImagePullBackOff` / `ErrImagePull`", "CRI failed to fetch image tag/registry", "Inspect `describe pod` Events; fix tag via `k set image` or `imagePullSecrets`"),
            ComparisonRow("`Liveness probe failed` in Events -> restarts", "Healthy app killed by bad `livenessProbe`", "Inspect Events for `Unhealthy: Liveness probe failed` & fix probe"),
        ),
        docs_links=(
            StudyDocLink(
                label="Debug Running Pods",
                url="https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/",
                exam_search_term="Debug Running Pods",
            ),
            StudyDocLink(
                label="Determine Reason for Pod Failure",
                url="https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/",
                exam_search_term="Determine Reason for Pod Failure",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Execute the 3-step Pod failure triage sequence",
                explanation="Grab status, `Last State` termination reason/exit code, Events, and previous container logs.",
                command="k -n <ns> get pods && k -n <ns> describe pod <pod> | tail -n 25 && k -n <ns> logs <pod> --previous",
                verify_command="k -n <ns> get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}{\" exit=\"}{.status.containerStatuses[0].lastState.terminated.exitCode}'",
                expected_output="Clear root reason (`OOMKilled exit=137`, `Error exit=127`, or Events image pull URL)",
            ),
            PracticeStep(
                title="Apply clean imperative Deployment fix (image, resources, or command)",
                explanation="Keep image unchanged if fixing memory/command (`set resources` or `patch --type=json` removing bogus override).",
                command="k -n <ns> set image deploy/web web=nginx:1.27-alpine",
            ),
            PracticeStep(
                title="Confirm Deployment rollout finishes cleanly with `1/1 Ready`",
                explanation="Wait briefly so delayed liveness kills or OOM spikes don't mask a bad pass.",
                command="k -n <ns> rollout status deploy/web --timeout=60s",
                verify_command="k -n <ns> get pods",
                expected_output="New Pod `Running`, `READY 1/1`, `RESTARTS 0`",
            ),
        ),
        debug_playbook=(
            DebugRow("`k logs <pod>` prints empty output in `CrashLoopBackOff`", "Currently waiting in backoff delay with no running container", "Pass `-p` (`--previous`) to inspect stderr from the crashed attempt"),
            DebugRow("Fixed Deployment `command`, yet container still crashes with old command", "Accidentally edited the ephemeral `Pod` instead of owning `Deployment`!", "Inspect `k describe pod | grep Controlled` -> fix the owning Deployment/DaemonSet/StatefulSet"),
            DebugRow("Raised `limits.memory` fails admission `must be >= request`", "`limits.memory` set lower than existing `requests.memory`", "Keep `requests <= limits` (raise both or update limits above existing requests)"),
        ),
        exam_trap=(
            "Whenever `k logs <pod>` on a CrashLoopBackOff Pod shows nothing (or `unable to retrieve container logs`), add `--previous` (`-p`) immediately — AND remember NEVER to leave an `OOMKilled` app with removed limits if the prompt states a specific `limits.memory` target!"
        ),
        cheatsheet=(
            CheatItem("Events + Last State", "k -n <ns> describe pod <pod>", "Check Image, State, Last State, Events"),
            CheatItem("Previous crash logs", "k -n <ns> logs <pod> -c <ctr> -p", "Prints stdout/stderr before crash"),
            CheatItem("Fix broken image tag", "k -n <ns> set image deploy/<d> <ctr>=<img:tag>", "Avoid full YAML edit"),
            CheatItem("Fix OOMKilled budget", "k -n <ns> set resources deploy/<d> -c <ctr> --limits=memory=256Mi --requests=memory=128Mi", "Resolves Exit 137 safely"),
            CheatItem("Drop invalid command", "k -n <ns> patch deploy/<d> --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/containers/0/command\"}]'", "Restores container ENTRYPOINT"),
        ),
        yaml_template=(
            "# Exit Code Triage Card:\n"
            "#   137 -> SIGKILL / OOMKilled (raise limits.memory or check livenessProbe)\n"
            "#   127 -> command/file not found (fix spec.containers[].command / args)\n"
            "#   1   -> application runtime failure (read logs --previous)"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A Pod owned by a Deployment logs `Last State: Terminated, Reason: Error, Exit Code: 127` and enters `CrashLoopBackOff`. Why isn't deleting the Pod a real fix?",
                choices=(
                    "ReplicaSet protects deleting crashed Pods",
                    "The Deployment's ReplicaSet immediately creates a replacement Pod from the same broken `spec.template`",
                    "Exit 127 locks etcd writes",
                    "kube-proxy replays old Pod YAMLs",
                ),
                correct_index=1,
                explanation="Fixing a Deployment-managed Pod requires updating the owning Deployment's `.spec.template` (`patch`, `edit`, `set image`, `set resources`).",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Which flag MUST you pass to `kubectl logs` to capture stderr from a container that exited 15 seconds ago and is currently sleeping in `CrashLoopBackOff`?",
                choices=(
                    "`--follow` (`-f`)",
                    "`--previous` (`-p`)",
                    "`--all-containers`",
                    "`--tail=0`",
                ),
                correct_index=1,
                explanation="`-p` / `--previous` reads logs from the most recently terminated container instance in that Pod.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="`kubectl describe pod api` shows `State: Waiting (CrashLoopBackOff)` and `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`. What caused the crash?",
                choices=(
                    "Wrong `imagePullSecrets`",
                    "Container exceeded its cgroup `resources.limits.memory` cap and was killed by Linux OOM killer",
                    "Missing `ServiceAccount`",
                    "Node taint `NoSchedule`",
                ),
                correct_index=1,
                explanation="`OOMKilled` (Exit Code `137` = `128+9`) occurs when container memory hits `limits.memory`; raising limits (keeping `requests <= limits`) fixes it.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-probes-config-init",
        order=32,
        domain=TS_DOMAIN,
        title="Readiness/Liveness/Startup Probes, ConfigMaps & `initContainers`",
        subtitle="Debug `0/1 Running` Pods, `CreateContainerConfigError`, and `Init:CrashLoopBackOff` blockages.",
        estimated_minutes=5,
        exam_frequency="Critical",
        archetype_ids=("ts-readiness-probe", "ts-configmap-env-broken", "ts-initcontainer-blocking", "ts-pvc-pending-storageclass"),
        summary=(
            "Pod startup traverses sequential gates: `initContainers` (must exit `0` cleanly) -> kubelet volume/env resolution "
            "(`CreateContainerConfigError` if ConfigMap/Secret missing) -> `startupProbe` -> continuous `readinessProbe` (gates Service traffic) + `livenessProbe` (triggers container restart)."
        ),
        architecture_flow=(
            "1. initContainers (must exit 0) -> 2. env/envFrom ConfigMap/Secret resolve -> 3. startupProbe passes -> 4. readinessProbe (Endpoints ON) & livenessProbe (restart if hung)"
        ),
        theory_points=(
            "**3 Probe Roles**: `startupProbe` guards slow boots (disables readiness/liveness until passing once!); `readinessProbe` toggles Pod IP inside Service `Endpoints` without killing container; `livenessProbe` kills & restarts deadlocked containers (`RESTARTS` climbs!).",
            "`Init:0/1` or `Init:Error`: read logs specifically on the init container with `k logs <pod> -c <init-name>` (`--previous` if crashing).",
            "`CreateContainerConfigError` means kubelet cannot resolve an `envFrom` / `valueFrom.configMapKeyRef` / `secretKeyRef` (wrong ConfigMap name, wrong namespace, or missing key name!).",
            "When `k get pods` says `Running` + `READY 0/1`, inspect `describe pod` Events for `Unhealthy: Readiness probe failed` and verify `httpGet.path` / `port` / `exec.command` matches the running app!",
            "Avoid placing `exec` checks or fragile external calls inside `readinessProbe` when a simple HTTP `path: /` or TCP port matches what the workload actually listens on.",
        ),
        decision_matrix=(
            ComparisonRow("`startupProbe`", "Runs first; keeps `liveness`/`readiness` paused until first success", "Slow-booting Java/legacy apps (`failureThreshold * periodSeconds`)"),
            ComparisonRow("`readinessProbe`", "Removes Pod from Service `Endpoints` on failure without restart", "Graceful drain / dependency warmup (`0/1 Running`)"),
            ComparisonRow("`livenessProbe`", "Kills & restarts container (`SIGKILL`) on consecutive failures", "Self-healing deadlocked processes"),
            ComparisonRow("`CreateContainerConfigError`", "Blocked BEFORE container starts due to missing CM/Secret key", "Check `describe pod` Events -> create/fix ConfigMap or key name"),
        ),
        docs_links=(
            StudyDocLink(
                label="Configure Liveness, Readiness and Startup Probes",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
                exam_search_term="Readiness Probes",
            ),
            StudyDocLink(
                label="Init Containers",
                url="https://kubernetes.io/docs/concepts/workloads/pods/init-containers/",
                exam_search_term="Init Containers",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect Pod Events and initContainer logs cleanly",
                explanation="Target initContainer explicitly by `-c <init-name>` (`k describe pod` reveals exact init name).",
                command="k -n <ns> describe pod <pod> | grep -A12 Events && k -n <ns> logs <pod> -c <init-name>",
                verify_command="k -n <ns> get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].name}{\"=\"}{.status.initContainerStatuses[*].state}'",
                expected_output="Prints initContainer name and exact failing exit code or reason",
            ),
            PracticeStep(
                title="Audit missing ConfigMap/Secret env keys before patching",
                explanation="Compare Deployment `env`/`envFrom` references against actual objects & keys in that namespace.",
                command="k -n <ns> get cm,secret && k -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[*].env}{.spec.template.spec.containers[*].envFrom}'",
            ),
            PracticeStep(
                title="Fix broken `readinessProbe` path or port and confirm Service Endpoints return",
                explanation="Patch Deployment probe cleanly and verify BOTH `1/1 Ready` AND `k get endpoints` populate immediately.",
                command="k -n <ns> patch deploy web --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/readinessProbe/httpGet/path\",\"value\":\"/\"}]'",
                verify_command="k -n <ns> rollout status deploy/web --timeout=60s && k -n <ns> get endpoints",
                expected_output="Pod turns `1/1 Ready` and Service displays active Pod endpoints",
            ),
        ),
        debug_playbook=(
            DebugRow("Created empty ConfigMap `app-env`, yet `CreateContainerConfigError` remains", "`valueFrom.configMapKeyRef.key: API_URL` expects that exact key inside `app-env`", "Read `describe pod` Events for exact missing key and add `--from-literal=API_URL=...`"),
            DebugRow("`readinessProbe` `Get http://...:8080/healthz: connection refused`", "Nginx/app serves port `80` at `/`, not `8080` or `/healthz`", "Check container listening port/route and align `httpGet.port` & `path` cleanly"),
            DebugRow("InitContainer loops `nslookup db-svc` (`can't resolve`)", "Typo in target Service name (`db-service` vs `db-svc`) or missing Service", "Inspect init `command`/`args`, verify real `k -n <ns> get svc` names"),
        ),
        exam_trap=(
            "Remember `ConfigMap` keys are CASE-SENSITIVE! Fixing `CreateContainerConfigError` by creating the missing ConfigMap with `api_url` instead of `API_URL` keeps Pod startup blocked until exact key spelling matches `configMapKeyRef.key`."
        ),
        cheatsheet=(
            CheatItem("Read initContainer logs", "k -n <ns> logs <pod> -c <init-name> [-p]", "Debugs Init:0/1 / Init:Error"),
            CheatItem("Inspect probes & envs", "k -n <ns> get deploy <d> -o yaml | grep -A10 -E 'Probe:|env'", "Spot wrong path/port/CM key"),
            CheatItem("JSONPatch probe path", "k -n <ns> patch deploy <d> --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/readinessProbe/httpGet/path\",\"value\":\"/\"}]'", "Surgical probe fix"),
            CheatItem("Add key to ConfigMap", "k -n <ns> patch cm <cm> -p '{\"data\":{\"KEY\":\"VAL\"}}'", "Fixes missing configMapKeyRef"),
            CheatItem("Verify Ready + Endpoints", "k -n <ns> get pods,endpoints", "Confirms traffic readiness"),
        ),
        yaml_template=(
            "readinessProbe:\n"
            "  httpGet:\n"
            "    path: /\n"
            "    port: 80\n"
            "  initialDelaySeconds: 2\n"
            "  periodSeconds: 3"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Your new app requires 45 seconds to warm caches before responding on `:8080/health`, while `livenessProbe` runs every 5 seconds with `failureThreshold: 3`. What cleanly prevents premature restarts without delaying normal runtime health checks?",
                choices=(
                    "Delete `readinessProbe`",
                    "Add a `startupProbe` covering startup time (`failureThreshold: 12, periodSeconds: 5`); `liveness` and `readiness` pause until `startupProbe` passes once",
                    "Set `restartPolicy: Never`",
                    "Add `initContainers` sleeping 45s after app starts",
                ),
                correct_index=1,
                explanation="`startupProbe` gates `livenessProbe` and `readinessProbe` until initial boot succeeds, letting liveness stay tight (`5s`) afterward.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="A Pod stays `Init:0/1` (`Init:CrashLoopBackOff`). Which command prints the failing script stderr inside its init container named `wait-db`?",
                choices=(
                    "`kubectl logs <pod>`",
                    "`kubectl logs <pod> -c wait-db --previous`",
                    "`kubectl describe node01`",
                    "`kubectl get svc wait-db`",
                ),
                correct_index=1,
                explanation="`kubectl logs` requires `-c <container-name>` for init containers or multi-container Pods (`--previous` prints previous failed attempt).",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="A Pod sits stuck in `CreateContainerConfigError`. `Events` prints `Error: couldn't find key DB_HOST in ConfigMap app-ns/web-cfg`, even though `kubectl get cm web-cfg` exists. Why?",
                choices=(
                    "ConfigMaps require a restart",
                    "The Pod uses `configMapKeyRef.key: DB_HOST` (mandatory by default), and `web-cfg` lacks key `DB_HOST`",
                    "`envFrom` ignores ConfigMaps",
                    "`kube-scheduler` cannot read secrets",
                ),
                correct_index=1,
                explanation="`configMapKeyRef` defaults `optional: false`; if the exact key is missing inside an existing ConfigMap, container creation stops cleanly in `CreateContainerConfigError`.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-sidecar-logging",
        order=33,
        domain=TS_DOMAIN,
        title="Multi-Container Sidecars, Shared Log Volumes & `kubectl debug`",
        subtitle="Attach/repair `emptyDir` streaming sidecars cleanly and debug minimal/distroless Pods via ephemeral containers.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("ts-multi-container-log-sidecar",),
        summary=(
            "Exam questions routinely require attaching a busybox streaming sidecar (`tail -n+1 -F`) via shared `emptyDir` volume, "
            "troubleshooting mismatched `volumeMounts` between app & sidecar containers, or inspecting scratch/distroless containers lacking shells "
            "via `kubectl debug <pod> -it --image=busybox:1.36 --target=<ctr>`."
        ),
        architecture_flow=(
            "App Container (writes /var/log/app.log) -> Shared emptyDir Volume (identical volumes[].name) -> Sidecar Container (mounts volume, tails -n+1 -F -> stdout) -> kubectl logs -c sidecar"
        ),
        theory_points=(
            "App and sidecar MUST mount the SAME `volumes[].name` (`emptyDir: {}`) — exact `mountPath` strings can differ ONLY if the file path tailed by the sidecar matches where the app actually writes relative to its own mount!",
            "Always specify `-c <container>` (`k logs <pod> -c sidecar`) or `--all-containers=true --prefix` on multi-container Pods.",
            "In `busybox`, use `tail -n+1 -F /var/log/legacy.log` (capital `-F` retries cleanly if file doesn't exist for the first 1–2s!).",
            "Do NOT touch existing app `command`/`args` or legacy file paths when adding a logging adapter sidecar — wire `emptyDir` onto the existing log folder cleanly.",
            "**Ephemeral Debug Containers (`kubectl debug`)**: when a container has NO shell (`distroless`/`scratch`), attach an interactive troubleshooting image (`k debug -it <pod> --image=busybox:1.36 --target=<ctr>`) or copy a crashing Pod (`--copy-to=dbg --container=app -- sh`)!",
        ),
        decision_matrix=(
            ComparisonRow("Shared `emptyDir` + `tail -F` sidecar", "Persists only for Pod lifetime; streams legacy log files to stdout", "Legacy apps writing files instead of stdout/stderr"),
            ComparisonRow("`kubectl logs <pod> -c <ctr>`", "Streams logs from ONE named container", "Inspecting multi-container or sidecar stdout"),
            ComparisonRow("`kubectl debug <pod> --target=<ctr>`", "Injects ephemeral debug container sharing process namespace without restarting Pod", "Inspecting distroless/minimal Pods lacking `sh`/`curl`"),
            ComparisonRow("`kubectl debug <pod> --copy-to=...`", "Clones crashed Pod with altered command/image so you can exec in", "Troubleshooting `CrashLoopBackOff` Pods you can't `exec` into"),
        ),
        docs_links=(
            StudyDocLink(
                label="Logging Architecture (Sidecar Streaming)",
                url="https://kubernetes.io/docs/concepts/cluster-administration/logging/#sidecar-container-with-a-logging-agent",
                exam_search_term="Sidecar Container Logging",
            ),
            StudyDocLink(
                label="Debugging with Ephemeral Containers (`kubectl debug`)",
                url="https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/#ephemeral-container",
                exam_search_term="kubectl debug ephemeral",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Audit container names and shared `volumeMounts` on the Pod/Deployment",
                explanation="Compare `name`, `mountPath`, and `subPath` across every container immediately.",
                command="k -n <ns> get pod <pod> -o jsonpath='{range .spec.containers[*]}{.name}: {.volumeMounts}{\"\\n\"}{end}'",
                verify_command="k -n <ns> get pod <pod> -o jsonpath='{.spec.volumes}'",
                expected_output="Lists container mountPaths alongside `emptyDir` volume declarations cleanly",
            ),
            PracticeStep(
                title="Add or repair shared `emptyDir` + `tail -n+1 -F` logging sidecar",
                explanation="Mount identical `emptyDir` volume (`name: varlog`) at the directory where the app writes logs.",
                command="k -n <ns> get deploy <d> -o yaml > app-sidecar.yaml",
                yaml_snippet=(
                    "containers:\n"
                    "- name: app\n"
                    "  image: busybox:1.36\n"
                    "  args: [\"/bin/sh\", \"-c\", \"while true; do date >> /var/log/legacy.log; sleep 2; done\"]\n"
                    "  volumeMounts: [{ name: varlog, mountPath: /var/log }]\n"
                    "- name: log-sidecar\n"
                    "  image: busybox:1.36\n"
                    "  args: [\"/bin/sh\", \"-c\", \"tail -n+1 -F /var/log/legacy.log\"]\n"
                    "  volumeMounts: [{ name: varlog, mountPath: /var/log, readOnly: true }]\n"
                    "volumes:\n"
                    "- name: varlog\n"
                    "  emptyDir: {}"
                ),
            ),
            PracticeStep(
                title="Verify sidecar streams live lines via `kubectl logs -c`",
                explanation="Always confirm actual log lines stream from the sidecar container stdout.",
                command="k -n <ns> logs <pod> -c log-sidecar --tail=10",
                verify_command="k -n <ns> get pod <pod>",
                expected_output="Prints live streamed log lines; Pod shows `READY 2/2` cleanly",
            ),
        ),
        debug_playbook=(
            DebugRow("`k logs -c sidecar` prints `can't open '/var/log/app.log': No such file`", "App wrote `/var/log/app.log` inside container layer while `emptyDir` was mounted at `/logs`, OR typo in `volumes[].name`", "Align BOTH containers to the same `volumes[].name` & matching file directory path"),
            DebugRow("`error: a container name must be specified` on `k logs`", "Multi-container Pods have no implicit default container", "Pass `-c <container>` or `--all-containers=true --prefix`"),
            DebugRow("App crashes when mounting emptyDir at `/etc/app/`", "Mounted `emptyDir` over a non-empty folder containing default configs, hiding baked files", "Mount `emptyDir` strictly at the dedicated log folder (`/var/log/...`)"),
        ),
        exam_trap=(
            "Mounting the sidecar at `/logs` while the app writes to `/var/log/legacy.log` (or giving the two containers different `volumes[].name` values) leaves the sidecar waiting forever on `No such file or directory`!"
        ),
        cheatsheet=(
            CheatItem("Logs for specific container", "k -n <ns> logs <pod> -c <container>", "Required on multi-container Pods"),
            CheatItem("Stream all containers", "k -n <ns> logs <pod> --all-containers --prefix", "Labels each log line by container"),
            CheatItem("List Pod containers", "k -n <ns> get pod <pod> -o jsonpath='{.spec.containers[*].name}'", "Fast container inventory"),
            CheatItem("Inject debug container", "k -n <ns> debug -it <pod> --image=busybox:1.36 --target=<ctr>", "Debugs distroless Pods without shell"),
            CheatItem("Clone crashed Pod w/ sh", "k -n <ns> debug <pod> -it --copy-to=dbg-pod --container=<ctr> -- sh", "Inspects CrashLoopBackOff filesystems"),
        ),
        yaml_template=(
            "volumes:\n"
            "- name: log-share\n"
            "  emptyDir: {}"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A Pod runs container `api` writing to `/var/log/events.log` and `adapter` running `tail -n+1 -F /var/log/events.log`. Both reference `emptyDir` `varlog`, yet `api` has `mountPath: /tmp` while `adapter` has `mountPath: /var/log`. Why does `adapter` see zero logs?",
                choices=(
                    "`emptyDir` fails across two containers",
                    "`api` wrote `/var/log/events.log` into its isolated rootfs rather than its `/tmp` emptyDir mount, so `adapter` never sees the file",
                    "`readOnly: true` blocks `tail -F`",
                    "busybox `tail` cannot read emptyDir",
                ),
                correct_index=1,
                explanation="Files only cross into an `emptyDir` volume when written inside that container's `mountPath` directory.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="A production Pod uses a minimal `distroless` image containing NO `/bin/sh`, `ls`, or `curl`, and you cannot edit the Deployment. How can you inspect its network/filesystem state live in Kubernetes?",
                choices=(
                    "`kubectl exec <pod> -- bash`",
                    "`kubectl debug -it <pod> --image=busybox:1.36 --target=<container>` (attaches an ephemeral container)",
                    "`kubectl ssh <pod>`",
                    "`kubectl patch pod` to add a new regular container",
                ),
                correct_index=1,
                explanation="`kubectl debug` injects an `ephemeralContainers` shell alongside the running Pod without restarting it or modifying `spec.containers`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Why should a busybox log-reader sidecar prefer `tail -n+1 -F /var/log/app.log` rather than `tail -f /var/log/app.log`?",
                choices=(
                    "`-F` deletes old rotated logs automatically",
                    "`-F` (`--follow=name --retry`) retries gracefully if `/var/log/app.log` hasn't been created yet or rotates, while `-n+1` prints from line 1",
                    "`-f` crashes kubelet",
                    "`-F` disables emptyDir sync",
                ),
                correct_index=1,
                explanation="Sidecars often start milliseconds before the app creates the log file; `-F` retries opening the file until present instead of exiting.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-service-dns-debug",
        order=34,
        domain=TS_DOMAIN,
        title="End-to-End Service, CoreDNS, `ndots` & `dnsConfig` Debugging",
        subtitle="Trace connectivity hops methodically across Pod port, Endpoints, CoreDNS, `dnsPolicy`, and `ndots`.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ts-service-port-mismatch", "ts-coredns-broken", "ts-dns-search-ndots"),
        summary=(
            "Never guess network bugs blindly — walk the 4-hop connectivity chain systematically: "
            "(1) Backend Pod `1/1 Ready` + container listening port (`wget localhost`), (2) Service `Endpoints` populated + `targetPort` match, "
            "(3) `kube-dns` Endpoints & CoreDNS health, (4) Client Pod `/etc/resolv.conf` (`dnsPolicy` / `dnsConfig` / `ndots` / `NetworkPolicy`)."
        ),
        architecture_flow=(
            "1. Pod resolv.conf (dnsPolicy/ndots) -> 2. CoreDNS (kube-dns Endpoints) -> 3. Service (Selector + targetPort -> Endpoints) -> 4. NetworkPolicy / Backend Container"
        ),
        theory_points=(
            "`dnsPolicy` modes: `ClusterFirst` (default — forwards cluster + upstream via CoreDNS), `Default` (inherits node `/etc/resolv.conf` directly, IGNORING cluster DNS!), `None` (uses custom `dnsConfig` exclusively), `ClusterFirstWithHostNet` (mandatory for `hostNetwork: true` Pods needing cluster DNS!).",
            "Default Kubernetes `options ndots:5`: ANY query containing `< 5` dots (e.g., `api.external.com` = 2 dots!) searches ALL cluster suffixes (`ns.svc.cluster.local`, `svc.cluster.local`, `cluster.local`) BEFORE trying external DNS — tuning `ndots: 2` cuts wasted lookups cleanly.",
            "`dnsPolicy: None` without listing `kube-dns` IP (`10.96.0.10` / `k -n kube-system get svc kube-dns`) breaks `*.svc.cluster.local` lookups completely even when external domains (`google.com`) succeed!",
            "Always isolate DNS failures vs Service port bugs quickly: test raw Pod IP (`curl <pod-ip>:<cport>`) -> ClusterIP (`curl <svc-ip>:<port>`) -> FQDN (`nslookup <svc>.<ns>.svc.cluster.local`).",
            "Check `k describe svc <svc>` + `k get endpoints <svc>` BEFORE touching CoreDNS — 80% of connectivity questions are simple `selector` or `targetPort` mismatches or blocked by a `NetworkPolicy`!",
        ),
        decision_matrix=(
            ComparisonRow("`ClusterFirst` (default)", "Sends all DNS to `kube-dns` (`CoreDNS`), preserves cluster search domains", "Standard cluster workloads resolving internal + external DNS"),
            ComparisonRow("`Default`", "Copies underlying Linux node's `/etc/resolv.conf` directly", "External-only legacy behavior (BREAKS `svc.cluster.local`!)"),
            ComparisonRow("`ClusterFirstWithHostNet`", "Uses `kube-dns` even when `spec.hostNetwork: true`", "Host-networked DaemonSets/Gateways resolving Services"),
            ComparisonRow("`None` + `dnsConfig`", "Custom `nameservers`/`searches`/`options` strictly", "Pinning custom external resolvers (`ndots`, corporate DNS)"),
        ),
        docs_links=(
            StudyDocLink(
                label="Debug Services",
                url="https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/",
                exam_search_term="Debug Services",
            ),
            StudyDocLink(
                label="Debugging DNS Resolution",
                url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
                exam_search_term="Debugging DNS Resolution",
            ),
            StudyDocLink(
                label="DNS `dnsPolicy` & `dnsConfig`",
                url="https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/#pod-s-dns-policy",
                exam_search_term="dnsPolicy ClusterFirstWithHostNet",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Inspect Pod `/etc/resolv.conf` and trace IP vs DNS hop",
                explanation="Compare `nameserver`, `search`, and `options ndots` directly inside the failing client Pod.",
                command="k -n <ns> exec <client-pod> -- cat /etc/resolv.conf",
                verify_command="k -n <ns> exec <client-pod> -- nslookup <svc>.<ns>.svc.cluster.local",
                expected_output="`nameserver 10.96.0.10` (`kube-dns`) and valid A-record resolution",
            ),
            PracticeStep(
                title="Compare Service `selector` + `targetPort` against Endpoints & Pod labels",
                explanation="Test raw Pod IP vs ClusterIP to pinpoint Service NAT vs container port refusal.",
                command="k -n <ns> get svc,endpoints -o wide && k -n <ns> get pods --show-labels",
                verify_command="k -n <ns> describe svc <svc>",
                expected_output="Endpoints list active `<pod-ip>:<targetPort>` matching listening container port",
            ),
            PracticeStep(
                title="Audit CoreDNS health and `kube-dns` Service when DNS fails cluster-wide",
                explanation="Check CoreDNS replicas, logs, and Corefile if `nslookup` fails everywhere.",
                command="k -n kube-system get deploy/coredns endpoints/kube-dns && k -n kube-system logs -l k8s-app=kube-dns --tail=25",
            ),
        ),
        debug_playbook=(
            DebugRow("`hostNetwork: true` Pod resolves `google.com`, fails `my-svc.app.svc.cluster.local`", "`hostNetwork: true` defaults `dnsPolicy` to `ClusterFirst` ONLY if `ClusterFirstWithHostNet` is set — default falls back to node `/etc/resolv.conf`!", "Set `dnsPolicy: ClusterFirstWithHostNet` on host-networked Pods needing cluster DNS"),
            DebugRow("Custom `dnsPolicy: None` resolves `8.8.8.8` queries, fails `*.svc.cluster.local`", "Missing `kube-dns` ClusterIP in `dnsConfig.nameservers` (or wrong `dnsPolicy`)", "Restore `dnsPolicy: ClusterFirst` or include `kube-dns` Service IP + `searches`"),
            DebugRow("Curl to ClusterIP returns `Connection timed out` (`0` endpoints? Or NetPol)", "Unready Pods, wrong Service selector, OR `NetworkPolicy` dropping traffic", "Test raw Pod IP first -> check `endpoints` -> check `k -n <ns> get netpol`"),
        ),
        exam_trap=(
            "A Pod configured with `hostNetwork: true` IGNORES `kube-dns` unless you set `dnsPolicy: ClusterFirstWithHostNet`! And remember `dnsPolicy: None` ALWAYS ignores cluster DNS unless `kube-dns`'s ClusterIP sits in `nameservers:`."
        ),
        cheatsheet=(
            CheatItem("Inspect client DNS config", "k -n <ns> exec <pod> -- cat /etc/resolv.conf", "Check `nameserver`, `search`, `ndots`"),
            CheatItem("Locate kube-dns VIP", "k -n kube-system get svc,endpoints kube-dns", "Confirms DNS Service + Pods alive"),
            CheatItem("Full Service triage", "k -n <ns> describe svc <svc> && k -n <ns> get pods --show-labels", "Check Selector, Port, TargetPort, Endpoints"),
            CheatItem("HostNet cluster DNS fix", "spec.hostNetwork: true + spec.dnsPolicy: ClusterFirstWithHostNet", "Required for host-network Pods"),
            CheatItem("Test FQDN direct bypass", "k -n <ns> exec <pod> -- nslookup <svc>.<ns>.svc.cluster.local", "Bypasses search/ndots expansion"),
        ),
        yaml_template=(
            "spec:\n"
            "  dnsPolicy: ClusterFirst\n"
            "  dnsConfig:\n"
            "    options:\n"
            "    - name: ndots\n"
            "      value: \"2\""
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="A Pod uses `spec.hostNetwork: true` and default `dnsPolicy`, and fails `nslookup api-svc.web.svc.cluster.local` cleanly. Which `dnsPolicy` fixes internal cluster Service resolution?",
                choices=(
                    "`Default`",
                    "`ClusterFirstWithHostNet`",
                    "`None`",
                    "`ClusterFirst` alone",
                ),
                correct_index=1,
                explanation="`hostNetwork: true` defaults to node host DNS unless `dnsPolicy: ClusterFirstWithHostNet` explicitly points it back to `kube-dns`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="Why does Kubernetes' default `/etc/resolv.conf` inside Pods trigger extra CoreDNS search attempts (`api.company.com.default.svc.cluster.local...`) for external domains containing 2 dots?",
                choices=(
                    "CoreDNS ignores TLDs",
                    "`options ndots:5` tells glibc/musl to append cluster search domains whenever a hostname has fewer than `5` dots",
                    "`kube-proxy` rewrites dots to dashes",
                    "`StatefulSet` suffixes override DNS",
                ),
                correct_index=1,
                explanation="With `ndots:5`, only names with `>= 5` dots (or a trailing dot like `api.company.com.`) resolve as absolute FQDNs right away.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="A Pod resolves external domains via `dnsConfig.nameservers: [8.8.8.8]` with `dnsPolicy: None`, yet fails `api-svc.payments.svc.cluster.local`. Why?",
                choices=(
                    "`kube-proxy` disables cluster DNS on `ClusterFirst`",
                    "`8.8.8.8` has no knowledge of `.svc.cluster.local` — internal names require `ClusterFirst` or `kube-dns`'s ClusterIP in `nameservers`",
                    "Port 53/UDP only works with NodePort",
                    "`ndots` must be set to `10`",
                ),
                correct_index=1,
                explanation="Public upstream resolvers cannot answer internal Kubernetes cluster domain queries; restore `ClusterFirst` or configure `kube-dns`'s IP + searches.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-node-kubelet-systemd",
        order=35,
        domain=TS_DOMAIN,
        title="Node Troubleshooting: `NotReady` Kubelet, `systemd` & Pressures",
        subtitle="Bring broken worker/controlplane nodes back `Ready` via `systemctl`, `journalctl`, kubelet configs & certificates.",
        estimated_minutes=6,
        exam_frequency="Critical",
        archetype_ids=("ts-kubelet-down",),
        summary=(
            "A node stuck `NotReady` (often printing `Kubelet stopped posting node status` inside `Conditions`) requires SSH "
            "directly onto that node. Troubleshoot sequentially: `systemctl status kubelet containerd` -> `journalctl -u kubelet` -> "
            "`/var/lib/kubelet/config.yaml` & `/etc/systemd/system/kubelet.service.d/10-kubeadm.conf` -> `/etc/kubernetes/kubelet.conf` + node disk/PID pressures."
        ),
        architecture_flow=(
            "1. k get nodes / describe node (Conditions) -> 2. ssh node -> 3. systemctl status kubelet containerd -> 4. journalctl -u kubelet -xe -> 5. Fix config/drop-in -> 6. daemon-reload && restart kubelet"
        ),
        theory_points=(
            "**4-step node triage over SSH**: (1) `sudo systemctl status kubelet containerd` (`inactive`, `failed`, or `masked`!), (2) `sudo journalctl -u kubelet -n 50 --no-pager` (exact flag, config path, or TLS error), (3) inspect `/etc/systemd/system/kubelet.service.d/10-kubeadm.conf`, `/var/lib/kubelet/config.yaml`, and `/etc/kubernetes/kubelet.conf`, (4) `df -h` (`DiskPressure`) / `free -m` (`MemoryPressure`).",
            "After editing ANY systemd unit or `/etc/systemd/system/kubelet.service.d/*`, ALWAYS run `sudo systemctl daemon-reload && sudo systemctl restart kubelet`!",
            "Notice common exam sabotage lines: disabled/stopped/masked `kubelet` (`systemctl unmask kubelet && systemctl enable --now kubelet`), wrong `--kubeconfig=/etc/kubernetes/kubelet.conf` path, wrong API server port in `kubelet.conf` (`6444` instead of `6443`!), or stopped `containerd`.",
            "Remember if a node was upgraded or drained previously and says `Ready,SchedulingDisabled`, `kubelet` IS healthy — the node simply needs `k uncordon <node>`!",
            "Verify `kubelet` client certificate validity (`openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates`) if journal logs report `x509` or `Unauthorized`.",
        ),
        decision_matrix=(
            ComparisonRow("`NotReady` (`Unknown` Conditions)", "`kubelet` service down/failed OR `containerd` dead OR CNI down", "SSH into node -> check `systemctl status kubelet containerd` + `journalctl`"),
            ComparisonRow("`Ready,SchedulingDisabled`", "Node healthy; explicitly cordoned (`spec.unschedulable: true`)", "Check prompt first; restore with `k uncordon <node>`"),
            ComparisonRow("`DiskPressure` / `MemoryPressure`", "Host rootfs/imagefs disk > eviction threshold (e.g. >85%)", "`df -h` -> clean unused images `crictl rmi --prune` / stale logs"),
            ComparisonRow("`/var/lib/kubelet/config.yaml` vs `10-kubeadm.conf`", "Kubelet component config vs systemd launch args/kubeconfig flags", "Follow `journalctl -u kubelet` directly to whichever file errored"),
        ),
        docs_links=(
            StudyDocLink(
                label="Troubleshooting Clusters (`NotReady` Nodes)",
                url="https://kubernetes.io/docs/tasks/debug/debug-cluster/",
                exam_search_term="Troubleshoot Clusters NotReady",
            ),
            StudyDocLink(
                label="Reconfiguring a kubeadm Node / Kubelet",
                url="https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/kubelet-integration/",
                exam_search_term="10-kubeadm.conf kubelet.conf",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Identify the `NotReady` node and inspect `Conditions`",
                explanation="Spot `Ready=Unknown` (`Kubelet stopped posting node status`) or `DiskPressure=True`.",
                command="k get nodes && k describe node node01 | grep -A8 Conditions",
                verify_command="k get node node01 -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].message}'",
                expected_output="`Kubelet stopped posting node status.` (or exact pressure condition)",
            ),
            PracticeStep(
                title="SSH into target node and inspect `kubelet`, `containerd`, and `journalctl`",
                explanation="Read the last 40 systemd journal lines to locate the exact error without guessing.",
                command="ssh node01 'sudo systemctl status kubelet containerd --no-pager; sudo journalctl -u kubelet -n 40 --no-pager'",
            ),
            PracticeStep(
                title="Repair unit/config, reload daemon, enable/start kubelet & verify `Ready`",
                explanation="Remember BOTH `daemon-reload` and `enable --now` (or `restart`) so changes take effect and persist reboots.",
                command="ssh node01 'sudo systemctl daemon-reload && sudo systemctl enable --now kubelet' && k wait --for=condition=Ready node/node01 --timeout=60s",
                verify_command="k get nodes",
                expected_output="`node01` status flips back to `Ready` cleanly",
            ),
        ),
        debug_playbook=(
            DebugRow("`kubelet` status says `Unit kubelet.service is masked`", "Unit symlinked to `/dev/null` intentionally", "Run `sudo systemctl unmask kubelet && sudo systemctl enable --now kubelet`"),
            DebugRow("`journalctl -u kubelet`: `failed to load kubelet config file /var/lib/kubelet/config.yaml`", "Typo inside `--config` path in `10-kubeadm.conf` or YAML typo in `config.yaml`", "Fix `--config` path or YAML syntax, then `systemctl daemon-reload && systemctl restart kubelet`"),
            DebugRow("`journalctl -u kubelet`: `connection refused 127.0.0.1:6443` on WORKER node!", "Worker `/etc/kubernetes/kubelet.conf` `server:` points to `127.0.0.1` instead of controlplane IP", "Update `server: https://<controlplane-ip>:6443` matching other workers/admin.conf, restart kubelet"),
        ),
        exam_trap=(
            "Fixing a broken flag or `--kubeconfig` path in `/etc/systemd/system/kubelet.service.d/10-kubeadm.conf` does NOTHING until `sudo systemctl daemon-reload` AND `sudo systemctl restart kubelet` execute!"
        ),
        cheatsheet=(
            CheatItem("Inspect Node Conditions", "k describe node <node> | grep -A7 Conditions", "Ready / DiskPressure / MemoryPressure"),
            CheatItem("Audit systemd services", "sudo systemctl status kubelet containerd --no-pager", "Both must be active (running)"),
            CheatItem("Read kubelet error log", "sudo journalctl -u kubelet -n 40 --no-pager", "Pinpoints exact broken path/cert"),
            CheatItem("Reload + enable/restart", "sudo systemctl daemon-reload && sudo systemctl unmask kubelet 2>/dev/null; sudo systemctl enable --now kubelet && sudo systemctl restart kubelet", "Full recovery sequence"),
            CheatItem("Check kubelet API endpoint", "sudo grep 'server:' /etc/kubernetes/kubelet.conf", "Must point to real controlplane IP:6443"),
        ),
        yaml_template=(
            "# Standard worker node troubleshooting files (Ubuntu + kubeadm):\n"
            "#   /etc/systemd/system/kubelet.service.d/10-kubeadm.conf\n"
            "#   /var/lib/kubelet/config.yaml\n"
            "#   /etc/kubernetes/kubelet.conf\n"
            "#   /etc/containerd/config.toml"
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="`kubectl get node node02` prints `NotReady`, and `ssh node02 'sudo journalctl -u kubelet -n 20'` reports `connection refused https://127.0.0.1:6443`. What is wrong on `node02`?",
                choices=(
                    "node02 needs `etcdctl snapshot restore`",
                    "`/etc/kubernetes/kubelet.conf` on worker `node02` points `server:` to `127.0.0.1` instead of the `controlplane` API IP",
                    "Worker nodes require `kube-apiserver.yaml`",
                    "`br_netfilter` is disabled",
                ),
                correct_index=1,
                explanation="Worker nodes have no local `kube-apiserver`; `/etc/kubernetes/kubelet.conf` must reference the `controlplane` endpoint IP on port `6443`.",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="After editing `/etc/systemd/system/kubelet.service.d/10-kubeadm.conf` on `node01`, which two commands make systemd reload the unit drop-in and restart kubelet?",
                choices=(
                    "`systemctl check kubelet` and `kubeadm reset`",
                    "`sudo systemctl daemon-reload` and `sudo systemctl restart kubelet`",
                    "`kubectl reload node01` and `systemctl status kubelet`",
                    "`systemctl reload-or-try kubelet` alone",
                ),
                correct_index=1,
                explanation="`systemd` caches unit drop-in files until `systemctl daemon-reload` runs, followed by `systemctl restart kubelet`.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="`systemctl start kubelet` fails immediately on `node01` printing `Failed to start kubelet.service: Unit kubelet.service is masked`. What fixes this?",
                choices=(
                    "`sudo systemctl unmask kubelet && sudo systemctl enable --now kubelet`",
                    "`kubeadm init phase kubelet-start` without unmasking",
                    "Reinstall `kubectl`",
                    "Delete `/var/lib/kubelet`",
                ),
                correct_index=0,
                explanation="A masked unit links to `/dev/null` and refuses `start`/`enable` until `systemctl unmask kubelet` removes the lock.",
            ),
        ),
    ),
    StudyTopic(
        id="ts-staticpods-crictl",
        order=36,
        domain=TS_DOMAIN,
        title="Container Runtime (`crictl`/`containerd`), Static Pods & Node Logs",
        subtitle="Inspect CRI containers directly when the API is dead, check `staticPodPath`, and audit node artifacts.",
        estimated_minutes=5,
        exam_frequency="High",
        archetype_ids=("ts-static-pod-manifest", "ts-crictl-container-debug"),
        summary=(
            "Whenever `kube-apiserver` is offline OR a task inspects containers/images directly on worker nodes, `crictl` talks straight "
            "to `/run/containerd/containerd.sock` (`crictl ps -a`, `crictl pods`, `crictl logs`, `crictl inspect`, `crictl images`). "
            "Meanwhile kubelet manages static Pods automatically from `staticPodPath` (`/etc/kubernetes/manifests`) appending `-<nodeName>`."
        ),
        architecture_flow=(
            "Disk (/etc/kubernetes/manifests/*.yaml) -> kubelet staticPodPath loop -> containerd CRI (/run/containerd/containerd.sock) <- sudo crictl ps/pods/logs/inspect"
        ),
        theory_points=(
            "Always run `crictl` with `sudo` (or verify `/etc/crictl.yaml` sets `runtime-endpoint: unix:///run/containerd/containerd.sock`) to avoid permission denied on the socket!",
            "Inspect `staticPodPath` inside `/var/lib/kubelet/config.yaml` — tasks sometimes break static Pods by changing `staticPodPath` or dropping bad manifests inside `/etc/kubernetes/manifests/`.",
            "NEVER leave backup `.bak` files inside `/etc/kubernetes/manifests/` — kubelet loads EVERY readable file inside `staticPodPath`, launching conflicting duplicates!",
            "Useful `crictl` inspection flags for CKA runtime questions: `sudo crictl ps -a --name <x>`, `sudo crictl logs <cid>`, `sudo crictl inspect <cid> | grep -i -A4 env/mounts`, and `sudo crictl inspectp <pod-id>`.",
            "`crictl pods` lists sandbox Pods independently of `kubectl get pods` (crucial when verifying whether containers exist on a specific node!).",
        ),
        decision_matrix=(
            ComparisonRow("`crictl pods`", "Lists CRI Pod sandboxes directly on the node", "Verifying static Pods or node sandboxes when API is down"),
            ComparisonRow("`crictl ps -a`", "Lists Running AND Exited/Dead containers + Exit Code", "Grabbing exited controlplane container IDs for `crictl logs`"),
            ComparisonRow("`crictl logs <cid>`", "Reads container stdout/stderr via containerd directly", "Debugging dead `kube-apiserver`/`etcd`/app without `kubectl`"),
            ComparisonRow("`crictl inspect <cid>`", "Full low-level CRI container JSON (mounts, args, image, pid, state)", "Extracting runtime args/image/exitReason right on node"),
        ),
        docs_links=(
            StudyDocLink(
                label="Debugging Kubernetes nodes with `crictl`",
                url="https://kubernetes.io/docs/tasks/debug/debug-cluster/crictl/",
                exam_search_term="crictl",
            ),
            StudyDocLink(
                label="Static Pods",
                url="https://kubernetes.io/docs/tasks/configure-pod-container/static-pod/",
                exam_search_term="staticPodPath",
            ),
        ),
        practice_steps=(
            PracticeStep(
                title="Verify `kubelet`'s configured `staticPodPath` and clean manifest directory",
                explanation="Check `staticPodPath` in `/var/lib/kubelet/config.yaml` matches `/etc/kubernetes/manifests` and has no leftover `.bak` files.",
                command="sudo grep staticPodPath /var/lib/kubelet/config.yaml && sudo ls -la /etc/kubernetes/manifests/",
                verify_command="sudo ls /etc/kubernetes/manifests/ | grep -vE '\\.ya?ml$' || echo CLEAN_DIR",
                expected_output="`staticPodPath: /etc/kubernetes/manifests` and `CLEAN_DIR` (zero non-YAML backup files)",
            ),
            PracticeStep(
                title="List CRI sandboxes and stopped/running containers via `crictl`",
                explanation="Compare `crictl pods` (sandboxes) and `crictl ps -a` (individual containers including exited).",
                command="sudo crictl pods && sudo crictl ps -a",
                verify_command="sudo crictl ps -a -o table | head -n 15",
                expected_output="Prints CONTAINER ID, IMAGE, CREATED, STATE (`Running`/`Exited`), NAME, POD ID",
            ),
            PracticeStep(
                title="Extract stderr logs or runtime inspection details via `crictl`",
                explanation="Inspect stderr of any stopped/failing container cleanly without API server dependency.",
                command="sudo crictl logs --tail=30 $(sudo crictl ps -a -q | head -n1)",
            ),
        ),
        debug_playbook=(
            DebugRow("`crictl ps` warns `connect: permission denied` on `/run/containerd/...`", "Ran `crictl` as unprivileged user without `sudo` or missing `/etc/crictl.yaml`", "Prefix `sudo crictl ...` (or pass `--runtime-endpoint unix:///run/containerd/containerd.sock`)"),
            DebugRow("Static Pod YAML created in `/etc/kubernetes/manifests/`, yet NEVER starts", "`kubelet`'s `/var/lib/kubelet/config.yaml` points `staticPodPath` elsewhere, OR invalid YAML syntax", "Inspect `grep staticPodPath /var/lib/kubelet/config.yaml` and `journalctl -u kubelet -n 30`"),
            DebugRow("`kubectl delete pod web-static-node01` immediately recreates the Pod!", "Static mirror Pods cannot be deleted via API server while manifest stays on node", "SSH to that node and remove/move `/etc/kubernetes/manifests/web-static.yaml`"),
        ),
        exam_trap=(
            "Leaving a backup inside `/etc/kubernetes/manifests/` (like `etcd.yaml.bak`) causes kubelet to launch BOTH manifests simultaneously; AND `kubectl delete pod <static-pod>` deletes only the API mirror while kubelet immediately recreates it from disk!"
        ),
        cheatsheet=(
            CheatItem("List all CRI containers", "sudo crictl ps -a", "Includes Exited containers"),
            CheatItem("List CRI Pod sandboxes", "sudo crictl pods", "Lists Pods locally on node"),
            CheatItem("Tail container logs offline", "sudo crictl logs --tail=30 <container-id>", "Works with dead kube-apiserver"),
            CheatItem("Inspect CRI container JSON", "sudo crictl inspect <cid> | grep -E 'exitCode|reason|image'", "Low-level runtime audit"),
            CheatItem("Check staticPodPath", "sudo grep staticPodPath /var/lib/kubelet/config.yaml", "Confirms where kubelet scans YAMLs"),
            CheatItem("Prune unused images (DiskPressure)", "sudo crictl rmi --prune", "Frees node disk quickly"),
        ),
        yaml_template=(
            "# Check /etc/crictl.yaml endpoint & validate YAML before kubelet loads it:\n"
            "# runtime-endpoint: unix:///run/containerd/containerd.sock\n"
            "# python3 -c \"import yaml; yaml.safe_load(open('/etc/kubernetes/manifests/app.yaml'))\""
        ),
        quizzes=(
            RecallQuiz(
                tag="Architecture",
                question="Before editing `/etc/kubernetes/manifests/kube-apiserver.yaml`, you run `sudo cp /etc/kubernetes/manifests/kube-apiserver.yaml /etc/kubernetes/manifests/kube-apiserver.yaml.bak`. What happens?",
                choices=(
                    "kubelet ignores files ending in `.bak`",
                    "kubelet tries launching BOTH manifests as static Pods causing name & port conflicts",
                    "containerd deletes `.bak` automatically",
                    "`crictl` switches to read-only mode",
                ),
                correct_index=1,
                explanation="kubelet reads EVERY readable manifest inside `staticPodPath`; keep backups outside that folder (e.g. `/tmp/`).",
            ),
            RecallQuiz(
                tag="CLI & YAML",
                question="You SSH to `node01` to inspect an exited container's stderr and run `crictl logs <id>`, which fails with `permission denied` on `containerd.sock`. What is the immediate fix?",
                choices=(
                    "Pass `--namespace=kube-system` to `crictl`",
                    "Run `sudo crictl logs <id>` so it can access `/run/containerd/containerd.sock`",
                    "Run `kubectl auth can-i exec crictl`",
                    "Edit `/etc/hosts`",
                ),
                correct_index=1,
                explanation="Root privileges (`sudo`) are required to connect to the local containerd CRI UNIX socket.",
            ),
            RecallQuiz(
                tag="Exam Trap",
                question="Running `kubectl delete pod audit-agent-node01 -n default` succeeds (`pod deleted`), yet 3 seconds later `audit-agent-node01` reappears `Running`. Why?",
                choices=(
                    "A ReplicaSet owns it",
                    "It is a kubelet Static Pod whose YAML still sits in `staticPodPath` on `node01` — remove the file on `node01` to delete it permanently",
                    "etcd snapshot restore ran automatically",
                    "A CronJob runs every 3 seconds",
                ),
                correct_index=1,
                explanation="Static Pods are reconciled by `kubelet` from local node disk (`/etc/kubernetes/manifests`), so deleting the API mirror Pod never removes the manifest on disk.",
            ),
        ),
    ),
)
