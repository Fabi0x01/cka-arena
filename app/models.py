"""Modelos Pydantic — Fase 1 (cluster/SSH)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PowerAction(str, Enum):
    start = "start"
    stop = "stop"
    restart = "restart"


class PowerRequest(BaseModel):
    action: PowerAction


class VMInfo(BaseModel):
    name: str
    state: str
    ips: list[str] = Field(default_factory=list)


class PowerStatus(BaseModel):
    state: str
    vms: list[VMInfo] = Field(default_factory=list)
    last_ready_at: float | None = None
    active_job: str | None = None
    detail: str | None = None


class NodeHealth(BaseModel):
    name: str
    ready: bool = False
    internal_ip: str | None = None
    ssh_ip: str | None = None
    ssh_ok: bool = False
    ssh_ms: float | None = None


class AddonHealth(BaseModel):
    name: str
    status: str  # present | absent | degraded
    detail: str | None = None


class HealthResponse(BaseModel):
    nodes_ready: int
    total_nodes: int
    nodes: list[NodeHealth]
    kubectl_ok: bool
    k8s_version: str | None = None
    kubeconfig: str
    addons: list[AddonHealth]
    bootstrap_plan: list[dict] = Field(default_factory=list)
    baseline_files: bool
    checked_at: float


class SetupSshRequest(BaseModel):
    password: str | None = None


class SetupSshResponse(BaseModel):
    ok: bool
    nodes: list[dict]
    ssh_config_path: str
    kubeconfig_path: str


# ---------------------------------------------------------------- ScenarioEnvelope (v1.1)

from typing import Any, Literal

NODE_NAMES = ("controlplane", "node01", "node02")

CHECK_TYPES = (
    "kubectl_resource_exists",
    "kubectl_jsonpath",
    "pod_status_ready",
    "node_status_ready",
    "kubectl_auth_can_i",
    "pod_exec_exit_zero",
    "pod_exec_must_fail",
    "node_command_exit_zero",
    "host_file_contains",
    "helm_release_state",
    "service_endpoints_ready",
    "deployment_rollout_ready",
    "pvc_bound",
)

DIFFICULTIES = ("exam_standard", "killer_hardcore", "boss_fight")

DOMAINS = (
    "Troubleshooting",
    "Cluster Architecture, Installation & Configuration",
    "Services & Networking",
    "Workloads & Scheduling",
    "Storage",
)


class DocLink(BaseModel):
    label: str
    url: str


class NodeCommand(BaseModel):
    node: Literal["controlplane", "node01", "node02"]
    command: str
    backup_paths: list[str] = Field(default_factory=list)
    sudo: bool = False


class SetupSpec(BaseModel):
    namespaces: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)  # ferramentas locais: kubectl/helm
    node_commands: list[NodeCommand] = Field(default_factory=list)


class SolutionSpec(BaseModel):
    manifests: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)  # kubectl/helm
    node_commands: list[NodeCommand] = Field(default_factory=list)


class CleanupSpec(BaseModel):
    namespaces: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)  # kubectl/helm
    kubectl_commands: list[str] = Field(default_factory=list)  # legado
    node_commands: list[NodeCommand] = Field(default_factory=list)


class CheckSpec(BaseModel):
    id: str
    description: str
    type: Literal[
        "kubectl_resource_exists",
        "kubectl_jsonpath",
        "pod_status_ready",
        "node_status_ready",
        "kubectl_auth_can_i",
        "pod_exec_exit_zero",
        "pod_exec_must_fail",
        "node_command_exit_zero",
        "host_file_contains",
        "helm_release_state",
        "service_endpoints_ready",
        "deployment_rollout_ready",
        "pvc_bound",
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    failure_hint: str | None = None
    weight_ratio: float | None = Field(default=None, gt=0)


class ScenarioEnvelope(BaseModel):
    schema_version: str = "1.2"
    id: str
    title: str
    domain: Literal[
        "Troubleshooting",
        "Cluster Architecture, Installation & Configuration",
        "Services & Networking",
        "Workloads & Scheduling",
        "Storage",
    ]
    subtopics: list[str] = Field(default_factory=list)
    difficulty: Literal["exam_standard", "killer_hardcore", "boss_fight"]
    weight: int = Field(ge=1, le=100)
    estimated_minutes: float = 5.0
    context_command: str = "kubectl config use-context cka"
    ssh_target: str | None = None
    prompt: str
    copy_tokens: list[str] = Field(default_factory=list)
    docs_links: list[DocLink] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    fast_solution_commands: list[str] = Field(default_factory=list)
    setup: SetupSpec
    checks: list[CheckSpec]
    solution: SolutionSpec = Field(default_factory=SolutionSpec)
    cleanup: CleanupSpec = Field(default_factory=CleanupSpec)
    reference_solution: str = ""
    destructive: bool = False
    archetype_id: str | None = None
