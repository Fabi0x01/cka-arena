"""Tests for cross-platform setup scripts (macOS Bash 3.2 & WSL2) and runtime helpers."""

from __future__ import annotations

import asyncio
import json
import os
import pty
import select
import subprocess
import tarfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"


def _run_bash(script: str, env: dict[str, str] | None = None, *, stdin_devnull: bool = True) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [BASH, "-c", script],
        cwd=str(REPO_ROOT),
        env=merged_env,
        stdin=subprocess.DEVNULL if stdin_devnull else None,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_shell_scripts_pass_bash_syntax_check() -> None:
    scripts = [
        REPO_ROOT / "setup.sh",
        *sorted((REPO_ROOT / "scripts" / "lib").glob("*.sh")),
        *sorted((REPO_ROOT / "scripts" / "cluster").glob("*.sh")),
    ]
    assert len(scripts) >= 7
    res = subprocess.run(
        [BASH, "-n", *[str(s) for s in scripts]],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


def test_lib_scripts_source_cleanly_under_strict_mode(tmp_path: Path) -> None:
    res = _run_bash(
        """
        set -euo pipefail
        export CKA_SETUP_LOG=/dev/null
        . scripts/lib/ui.sh
        . scripts/lib/detect.sh
        . scripts/lib/pkg.sh
        . scripts/lib/state.sh
        hr 40
        bar 0 10 empty_test
        bar 10 10 full_test
        refresh_path
        """
        ,
        env={"CKA_DIR": str(tmp_path / "cka"), "HOME": str(tmp_path)},
    )
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert "0%" in res.stdout and "100%" in res.stdout


def test_install_kubectl_downloads_correct_os_binary(tmp_path: Path) -> None:
    # macOS without brew MUST request darwin/arm64, NEVER linux/arm64
    mac_script = f"""
    set -euo pipefail
    export CKA_BIN_DIR="{tmp_path}/mac-bin"
    export CKA_SETUP_LOG=/dev/null
    . scripts/lib/ui.sh
    . scripts/lib/detect.sh
    . scripts/lib/pkg.sh
    OS_NAME=macos
    ARCH=arm64
    has_cmd() {{ [ "$1" = "brew" ] && return 1; command -v "$1" >/dev/null 2>&1; }}
    _download() {{ printf '%s\\n' "$1" > "{tmp_path}/mac-url.txt"; printf '#!/bin/sh\\n' > "$2"; }}
    install_kubectl
    """
    res = _run_bash(mac_script)
    assert res.returncode == 0, res.stderr
    mac_url = (tmp_path / "mac-url.txt").read_text().strip()
    assert "/bin/darwin/arm64/kubectl" in mac_url
    assert "/bin/linux/" not in mac_url
    assert os.access(tmp_path / "mac-bin" / "kubectl", os.X_OK)

    # WSL x86_64 MUST request linux/amd64 directly (without snap)
    wsl_script = f"""
    set -euo pipefail
    export CKA_BIN_DIR="{tmp_path}/wsl-bin"
    export CKA_SETUP_LOG=/dev/null
    . scripts/lib/ui.sh
    . scripts/lib/detect.sh
    . scripts/lib/pkg.sh
    OS_NAME=wsl
    ARCH=x86_64
    _sudo() {{ echo "snap-should-not-run" >&2; return 99; }}
    _download() {{ printf '%s\\n' "$1" > "{tmp_path}/wsl-url.txt"; printf '#!/bin/sh\\n' > "$2"; }}
    install_kubectl
    """
    res_wsl = _run_bash(wsl_script)
    assert res_wsl.returncode == 0, res_wsl.stderr
    wsl_url = (tmp_path / "wsl-url.txt").read_text().strip()
    assert "/bin/linux/amd64/kubectl" in wsl_url


def test_install_helm_downloads_and_extracts_correct_tarball(tmp_path: Path) -> None:
    for os_name, arch, expected_os, expected_arch in (
        ("macos", "arm64", "darwin", "arm64"),
        ("wsl", "x86_64", "linux", "amd64"),
    ):
        case_dir = tmp_path / f"{os_name}-{arch}"
        tar_path = case_dir / "fake-helm.tar.gz"
        stage = case_dir / f"{expected_os}-{expected_arch}"
        stage.mkdir(parents=True)
        helm_bin = stage / "helm"
        helm_bin.write_text("#!/bin/sh\necho v3.17.3\n")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(helm_bin, arcname=f"{expected_os}-{expected_arch}/helm")

        script = f"""
        set -euo pipefail
        export CKA_BIN_DIR="{case_dir}/bin"
        export CKA_SETUP_LOG=/dev/null
        . scripts/lib/ui.sh
        . scripts/lib/detect.sh
        . scripts/lib/pkg.sh
        OS_NAME="{os_name}"
        ARCH="{arch}"
        has_cmd() {{ [ "$1" = "brew" ] && return 1; command -v "$1" >/dev/null 2>&1; }}
        _download() {{ printf '%s\\n' "$1" > "{case_dir}/url.txt"; cp "{tar_path}" "$2"; }}
        install_helm
        """
        res = _run_bash(script)
        assert res.returncode == 0, res.stderr
        url = (case_dir / "url.txt").read_text().strip()
        assert f"helm-v3.17.3-{expected_os}-{expected_arch}.tar.gz" in url
        assert os.access(case_dir / "bin" / "helm", os.X_OK)


def test_setup_flags_help_and_invalid_args() -> None:
    help_res = _run_bash("./setup.sh --help")
    assert help_res.returncode == 0
    assert "--check" in help_res.stdout
    assert "--provider" in help_res.stdout

    missing_val = _run_bash("./setup.sh --provider")
    assert missing_val.returncode != 0
    assert "unbound variable" not in missing_val.stderr.lower()

    bad_provider = _run_bash("./setup.sh --provider invalid")
    assert bad_provider.returncode != 0
    assert "invalid --provider" in bad_provider.stderr


def test_setup_check_mode_is_read_only(tmp_path: Path) -> None:
    cka_dir = tmp_path / "cka-state"
    res = subprocess.run(
        [BASH, "./setup.sh", "--check"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "CKA_DIR": str(cka_dir), "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert "unbound variable" not in res.stderr.lower()
    assert not (cka_dir / "provider").exists()
    assert not (cka_dir / "setup.log").exists()
    # --check must inspect core CKA dependencies
    for expected in ("curl", "git", "uv", "kubectl", "helm", "jq", "vim"):
        assert expected in res.stdout


def test_install_missing_requires_permission_and_fails_on_blockers(tmp_path: Path) -> None:
    setup_body = (
        (REPO_ROOT / "setup.sh")
        .read_text()
        .replace(
            'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
            f'SCRIPT_DIR="{REPO_ROOT}"',
        )
        .replace('main "$@"', "")
    )
    harness = tmp_path / "harness.sh"
    harness.write_text(setup_body)

    # 1) Blocker present with empty CHECK_NAMES MUST fail (never silently exit 0)
    blocker_res = _run_bash(
        f"""
        set -- --check
        . "{harness}"
        MISSING=("WSL systemd")
        BLOCKERS=("WSL systemd")
        CHECK_NAMES=(); CHECK_TOOLS=(); CHECK_HINTS=(); CHECK_INSTALLERS=()
        install_missing
        """,
        env={"CKA_DIR": str(tmp_path / "cka1")},
    )
    assert blocker_res.returncode != 0
    assert "WSL systemd" in (blocker_res.stdout + blocker_res.stderr)

    # 2) Non-TTY stdin without --yes MUST NOT install anything
    nontty_marker = tmp_path / "should_not_exist"
    nontty_res = _run_bash(
        f"""
        set --
        . "{harness}"
        MISSING=("helm")
        BLOCKERS=()
        CHECK_NAMES=("helm"); CHECK_TOOLS=("helm")
        CHECK_HINTS=("install helm"); CHECK_INSTALLERS=("fake_install_helm")
        fake_install_helm() {{ touch "{nontty_marker}"; return 0; }}
        install_missing
        """,
        env={"CKA_DIR": str(tmp_path / "cka2")},
        stdin_devnull=True,
    )
    assert nontty_res.returncode != 0
    assert "non-interactive terminal detected" in nontty_res.stderr
    assert not nontty_marker.exists()

    # 3) Interactive PTY answering 'n' refuses installation
    deny_marker = tmp_path / "denied_marker"
    assert _run_install_missing_pty(harness, tmp_path / "cka3", deny_marker, b"n\n") != 0
    assert not deny_marker.exists()

    # 4) Interactive PTY answering 'y' installs tool and succeeds
    allow_marker = tmp_path / "allowed_marker"
    rc = _run_install_missing_pty(harness, tmp_path / "cka4", allow_marker, b"y\n")
    assert rc == 0
    assert allow_marker.exists()


def _run_install_missing_pty(harness: Path, cka_dir: Path, marker: Path, answer: bytes) -> int:
    fake_bin = cka_dir / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    cmd = f"""
    . "{harness}"
    OS_NAME="wsl"
    PKG_MANAGER="apt"
    CKA_BIN_DIR="{fake_bin}"
    MISSING=("jq")
    BLOCKERS=()
    CHECK_NAMES=("jq"); CHECK_TOOLS=("jq")
    CHECK_HINTS=("sudo apt-get install jq"); CHECK_INSTALLERS=("fake_install_jq")
    installer_needs_sudo() {{ return 1; }}
    fake_install_jq() {{
      touch "{marker}"
      printf '#!/bin/sh\\n' > "{fake_bin}/jq"
      chmod +x "{fake_bin}/jq"
      return 0
    }}
    install_missing
    """
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [BASH, "-c", cmd],
        cwd=str(REPO_ROOT),
        env={**os.environ, "CKA_DIR": str(cka_dir), "CKA_ASSUME_YES": "0", "NO_COLOR": "1"},
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    output = b""
    sent = False
    try:
        import time

        deadline = time.time() + 10.0
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if not sent and b"Install jq" in output:
                    os.write(master, answer)
                    sent = True
            elif proc.poll() is not None:
                break
        assert sent, f"Expected permission prompt in output, got: {output.decode(errors='replace')}"
        return proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)


def test_terminal_writes_bashrc_and_resolves_fallback_shell(tmp_path: Path, monkeypatch) -> None:
    from app.terminal import _resolve_host_shell, write_exam_shell_files

    workdir = tmp_path / "scratch-tab"
    write_exam_shell_files(workdir)

    bashrc = (workdir / ".bashrc").read_text()
    zshrc = (workdir / ".zshrc").read_text()
    assert "$HOME/.local/bin" in bashrc
    assert "$HOME/.local/bin" in zshrc
    assert "candidate@cka-arena" in bashrc

    monkeypatch.setenv("SHELL", "/nonexistent/shell/binary")
    resolved = _resolve_host_shell({"SHELL": "/nonexistent/shell/binary"})
    assert os.access(resolved, os.X_OK)


def test_wire_kind_configures_exam_contexts_and_nodes(tmp_path: Path, monkeypatch) -> None:
    from app import config, setup_wire
    from app.ssh_runner import ProcResult

    kc = tmp_path / "kubeconfig"
    kc.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "clusters": [{"name": "kind-cka", "cluster": {"server": "https://127.0.0.1:6443"}}],
                "users": [{"name": "kind-cka", "user": {}}],
                "contexts": [{"name": "cka", "context": {"cluster": "kind-cka", "user": "kind-cka"}}],
                "current-context": "cka",
            },
            sort_keys=False,
        )
    )
    monkeypatch.setattr(config, "KUBECONFIG_PATH", kc)

    async def fake_wait_readyz(timeout_s: float = 60) -> bool:
        return True

    async def fake_get_nodes() -> list[dict]:
        return [{"name": "cka-control-plane", "ready": True, "internal_ip": "172.18.0.2"}]

    calls: list[tuple[str, str]] = []

    class FakeProvider:
        name = "kind"

        async def exec(self, node: str, command: str, *, sudo: bool = False, timeout: float = 20.0) -> ProcResult:
            calls.append((node, command))
            return ProcResult(0, "", "")

    monkeypatch.setattr(setup_wire.cluster, "wait_readyz", fake_wait_readyz)
    monkeypatch.setattr(setup_wire.cluster, "get_nodes", fake_get_nodes)
    monkeypatch.setattr(setup_wire.provider, "get", lambda: FakeProvider())

    rc = asyncio.run(setup_wire.main())
    assert rc == 0
    doc = yaml.safe_load(kc.read_text())
    names = {c["name"] for c in doc["contexts"]}
    assert {"cka", "cka-ops", "cka-edge"}.issubset(names)
    assert len(calls) == 3
    assert all("/root/.vimrc" in cmd for _node, cmd in calls)


def test_kind_up_uses_mirror_first_isolated_docker_config_and_recovers_partial_cluster(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cka_dir = tmp_path / "cka"
    cka_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    trace_file = state_dir / "trace.log"
    kind_cfg_copy = state_dir / "kind-config.yaml"

    # Mock docker:
    # - ps -a for incomplete cluster -> returns 1 container initially, simulating broken cluster
    # - pull -> fails once when DOCKER_CONFIG is unset/default, succeeds when DOCKER_CONFIG is isolated temp dir
    # - image inspect -> returns 1 (not cached yet)
    # - info/exec/cp -> succeed cleanly
    (bin_dir / "docker").write_text(f"""#!/usr/bin/env bash
set -u
echo "docker DOCKER_CONFIG=${{DOCKER_CONFIG:-UNSET}} $*" >> "{trace_file}"
case "${{1:-}}" in
  info) exit 0 ;;
  image)
    if [ "${{2:-}}" = "inspect" ]; then exit 1; fi
    exit 0 ;;
  pull)
    if [ -z "${{DOCKER_CONFIG:-}}" ]; then
      echo "failed to authorize: failed to fetch anonymous token" >&2
      exit 1
    fi
    exit 0 ;;
  ps)
    echo "ctr1"
    exit 0 ;;
  exec)
    if [ "${{3:-}}" = "command" ]; then exit 0; fi
    exit 0 ;;
  *) exit 0 ;;
esac
""")

    (bin_dir / "kind").write_text(f"""#!/usr/bin/env bash
set -u
echo "kind $*" >> "{trace_file}"
case "${{1:-}}" in
  get)
    echo "cka"
    exit 0 ;;
  delete)
    exit 0 ;;
  create)
    cat > "{kind_cfg_copy}"
    exit 0 ;;
  export)
    cat <<'KC' > "{cka_dir}/kubeconfig"
apiVersion: v1
kind: Config
clusters:
- name: kind-cka
  cluster:
    server: https://127.0.0.1:6443
users:
- name: kind-cka
  user: {{}}
contexts:
- name: kind-cka
  context:
    cluster: kind-cka
    user: kind-cka
current-context: kind-cka
KC
    exit 0 ;;
esac
""")

    (bin_dir / "kubectl").write_text("""#!/usr/bin/env bash
set -u
case "$*" in
  *"get daemonset -n kube-system weave-net"*) exit 0 ;;
  *"get nodes --no-headers"*)
    printf "cka-control-plane   Ready    control-plane   1m   v1.31.2\n"
    printf "cka-worker          Ready    <none>          1m   v1.31.2\n"
    printf "cka-worker2         Ready    <none>          1m   v1.31.2\n"
    exit 0 ;;
  *"get nodes -o json"*)
    cat <<'JSON'
{"items":[
  {"metadata":{"name":"cka-control-plane"}},
  {"metadata":{"name":"cka-worker2"}},
  {"metadata":{"name":"cka-worker"}}
]}
JSON
    exit 0 ;;
  *) exit 0 ;;
esac
""")
    for tool in ("docker", "kind", "kubectl"):
        (bin_dir / tool).chmod(0o755)

    res = subprocess.run(
        [BASH, str(REPO_ROOT / "scripts" / "cluster" / "kind-up.sh")],
        cwd=str(REPO_ROOT),
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
            "HOME": str(tmp_path),
            "CKA_DIR": str(cka_dir),
            "CKA_SETUP_LOG": str(cka_dir / "setup.log"),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, f"stderr={res.stderr}\nlog={(cka_dir / 'setup.log').read_text()}"

    trace = trace_file.read_text()
    # Incomplete cluster must be deleted before fresh creation
    assert "kind delete cluster --name cka" in trace
    # Must try mirror.gcr.io first, fail without isolated config, then recover with isolated DOCKER_CONFIG
    assert "docker pull mirror.gcr.io/kindest/node:" in trace.replace("DOCKER_CONFIG=UNSET ", "")
    assert "kind create cluster --name cka --image mirror.gcr.io/kindest/node:" in trace
    # hosts.toml + containerd certs.d mount must be configured
    hosts_toml = (cka_dir / "certs.d" / "docker.io" / "hosts.toml").read_text()
    assert "https://mirror.gcr.io" in hosts_toml
    cfg_text = kind_cfg_copy.read_text()
    assert 'config_path = "/etc/containerd/certs.d"' in cfg_text
    assert str(cka_dir / "certs.d") in cfg_text
    # nodes.json must map logical names to real kind names
    nodes_map = json.loads((cka_dir / "nodes.json").read_text())
    assert nodes_map["controlplane"]["node"] == "cka-control-plane"
    assert nodes_map["node01"]["node"] == "cka-worker"
    assert nodes_map["node02"]["node"] == "cka-worker2"


def test_addons_install_gateway_tries_mirror_and_falls_back_with_kubeconfig(tmp_path: Path, monkeypatch) -> None:
    from app import addons, config
    from app.ssh_runner import ProcResult

    monkeypatch.setattr(config, "KUBECONFIG_PATH", tmp_path / "kubeconfig")
    monkeypatch.setattr(addons.shutil, "which", lambda name: "/usr/bin/helm" if name == "helm" else None)

    present_calls: list[list[str]] = []

    async def fake_present(args: list[str]) -> bool:
        present_calls.append(args)
        # CRD already present, deployment absent
        return args[:2] == ["get", "crd"]

    helm_calls: list[tuple[list[str], dict | None]] = []

    async def fake_run_local(cmd: list[str], *, timeout: float = 20, stdin_data=None, env=None) -> ProcResult:
        helm_calls.append((cmd, env))
        if len(helm_calls) == 1:
            return ProcResult(1, "", "mirror temporary failure")
        return ProcResult(0, "", "")

    monkeypatch.setattr(addons, "_present", fake_present)
    monkeypatch.setattr("app.ssh_runner.run_local", fake_run_local)

    assert asyncio.run(addons.install_gateway()) is True
    assert len(helm_calls) == 2
    assert "oci://mirror.gcr.io/envoyproxy/gateway-helm" in helm_calls[0][0]
    assert "oci://docker.io/envoyproxy/gateway-helm" in helm_calls[1][0]
    assert helm_calls[0][1]["KUBECONFIG"] == str(tmp_path / "kubeconfig")
    assert helm_calls[1][1]["KUBECONFIG"] == str(tmp_path / "kubeconfig")


def test_kind_provider_node_translation_across_validator_doctor_commands_and_engine(tmp_path: Path, monkeypatch) -> None:
    from app import commands, config, provider, validator
    from app.doctor import ClusterDoctor
    from app.models import ScenarioEnvelope
    from app.scenario_engine import ScenarioEngine
    from app.ssh_runner import ProcResult

    cka_dir = tmp_path / "cka"
    cka_dir.mkdir()
    (cka_dir / "provider").write_text("kind\n")
    (cka_dir / "nodes.json").write_text(json.dumps({
        "controlplane": {"container": "cka-control-plane", "node": "cka-control-plane"},
        "node01": {"container": "cka-worker", "node": "cka-worker"},
        "node02": {"container": "cka-worker2", "node": "cka-worker2"},
    }))
    monkeypatch.setattr(config, "CKA_DIR", cka_dir)
    monkeypatch.setattr(config, "KUBECONFIG_PATH", cka_dir / "kubeconfig")
    monkeypatch.delenv("CKA_PROVIDER", raising=False)
    provider.reset()

    try:
        # 1) commands.py translates node targets on kind
        seen_k8s: list[list[str]] = []

        async def fake_kubectl(args: list[str], timeout: float = 20, stdin_data=None) -> ProcResult:
            seen_k8s.append(args)
            if args[:2] == ["get", "deployment"]:
                return ProcResult(0, "cka-worker2", "")
            return ProcResult(0, "", "")

        monkeypatch.setattr("app.cluster.kubectl", fake_kubectl)
        asyncio.run(commands.run_tool_command("kubectl taint nodes node02 cka-arena/practice=critical:NoSchedule --overwrite"))
        assert seen_k8s[-1][:3] == ["taint", "nodes", "cka-worker2"]

        # 2) ScenarioEngine translates nodeSelector hostname in setup & solution manifests
        engine = ScenarioEngine()
        env = ScenarioEnvelope.model_validate({
            "schema_version": "1.2",
            "id": "test-taint",
            "title": "Schedule on node02",
            "domain": "Workloads & Scheduling",
            "difficulty": "exam_standard",
            "weight": 4,
            "prompt": "Schedule Pod on node02",
            "setup": {
                "namespaces": ["ns-taint"],
                "manifests": [
                    "apiVersion: v1\nkind: Pod\nmetadata:\n  name: p\nspec:\n  nodeSelector:\n    kubernetes.io/hostname: node02\n  containers:\n  - name: c\n    image: nginx:1.27-alpine\n"
                ],
            },
            "checks": [
                {"id": "c1", "description": "ok", "type": "node_status_ready", "params": {"node_name": "node01"}}
            ],
            "solution": {
                "manifests": [
                    "apiVersion: v1\nkind: Pod\nmetadata:\n  name: p\nspec:\n  nodeName: node02\n  containers:\n  - name: c\n    image: nginx:1.27-alpine\n"
                ],
                "commands": [],
            },
            "cleanup": {"namespaces": ["ns-taint"], "commands": []},
        })
        labeled = engine._labeled_manifests(env)
        assert labeled[0]["spec"]["nodeSelector"]["kubernetes.io/hostname"] == "cka-worker2"
        rendered_sol = engine.render_manifests_payload(env.solution.manifests)
        assert "nodeName: cka-worker2" in rendered_sol

        # 3) Validator resolves logical node01 -> cka-worker and helm KUBECONFIG
        async def fake_get_nodes(*, timeout: float = 15):
            return [
                {"name": "cka-control-plane", "ready": True, "internal_ip": "172.18.0.2"},
                {"name": "cka-worker", "ready": True, "internal_ip": "172.18.0.3"},
                {"name": "cka-worker2", "ready": True, "internal_ip": "172.18.0.4"},
            ]

        monkeypatch.setattr("app.cluster.get_nodes", fake_get_nodes)
        status, _ev = asyncio.run(validator.chk_node_status_ready({"node_name": "node01"}))
        assert status == validator.PASS
        status_jp, _ = asyncio.run(validator.chk_kubectl_jsonpath({
            "kind": "deployment",
            "name": "web",
            "namespace": "ns",
            "jsonpath": "{.spec.template.spec.nodeSelector}",
            "operator": "equals",
            "expected": "node02",
        }))
        assert status_jp == validator.PASS

        helm_seen: dict = {}

        async def fake_helm_local(cmd: list[str], *, timeout: float = 20, stdin_data=None, env=None):
            helm_seen["cmd"] = cmd
            helm_seen["env"] = env
            return ProcResult(0, json.dumps([{"name": "app", "status": "deployed", "revision": "2"}]), "")

        monkeypatch.setattr(validator, "run_local", fake_helm_local)
        h_status, _ = asyncio.run(validator.chk_helm_release_state({"namespace": "default", "release_name": "app"}))
        assert h_status == validator.PASS
        assert helm_seen["env"]["KUBECONFIG"] == str(cka_dir / "kubeconfig")

        # 4) Doctor health matches kind real node names & calico network policy
        async def fake_docker(args: list[str], timeout: float = 20):
            if args[0] == "inspect":
                return ProcResult(0, "true", "")
            if args[0] == "exec" and "kubectl" not in args:
                return ProcResult(0, "yes", "")
            return ProcResult(0, "", "")

        monkeypatch.setattr("app.provider.kind._docker", fake_docker)

        async def fake_kubectl_doctor(args: list[str], timeout: float = 15, stdin_data=None):
            if args[:2] == ["get", "nodes"]:
                return ProcResult(0, json.dumps({
                    "items": [
                        {"metadata": {"name": n}, "status": {"addresses": [{"type": "InternalIP", "address": "172.18.0.2"}], "conditions": [{"type": "Ready", "status": "True"}]}}
                        for n in ("cka-control-plane", "cka-worker", "cka-worker2")
                    ]
                }), "")
            if args[:3] == ["get", "pods", "-n"]:
                return ProcResult(0, json.dumps({
                    "items": [{"metadata": {"name": "calico-node-abc"}, "status": {"containerStatuses": [{"name": "calico-node", "ready": True}]}}]
                }), "")
            if args[:2] == ["get", "apiservice"]:
                return ProcResult(0, json.dumps({"status": {"conditions": [{"type": "Available", "status": "True"}]}}), "")
            return ProcResult(0, "ok", "")

        monkeypatch.setattr("app.cluster.kubectl", fake_kubectl_doctor)
        doc_health = asyncio.run(ClusterDoctor().health())
        assert doc_health["nodes_ready"] == 3
        netpol_state, _ = asyncio.run(ClusterDoctor()._network_policy_state())
        assert netpol_state == "present"
    finally:
        provider.reset()


def test_sync_cluster_profile_supports_kind_endpoint(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import config, main, provider

    cka_dir = tmp_path / "cka"
    cka_dir.mkdir()
    (cka_dir / "provider").write_text("kind\n")
    monkeypatch.setattr(config, "CKA_DIR", cka_dir)
    monkeypatch.delenv("CKA_PROVIDER", raising=False)
    provider.reset()

    async def fake_sync() -> dict[str, bool]:
        return {"controlplane": True, "node01": True, "node02": True}

    monkeypatch.setattr(main.setup_wire, "sync_kind_node_exam_profile", fake_sync)
    try:
        with TestClient(main.app) as client:
            resp = client.post("/api/cluster/sync-profile")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["nodes"]["controlplane"] is True
    finally:
        provider.reset()
