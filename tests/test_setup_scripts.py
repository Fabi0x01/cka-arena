"""Tests for cross-platform setup scripts (macOS Bash 3.2 & WSL2) and runtime helpers."""

from __future__ import annotations

import asyncio
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
