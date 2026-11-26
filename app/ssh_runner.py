"""Ponte SSH: chave dedicada, ssh-copy-id via expect, ssh/config gerenciado, kubeconfig dedicado."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from app import config


@dataclass
class ProcResult:
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


async def _run(
    cmd: list[str],
    *,
    timeout: float,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
) -> ProcResult:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out_b, err_b = await asyncio.wait_for(
            proc.communicate(stdin_data.encode() if stdin_data is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ProcResult(-1, "", f"timeout after {timeout}s")
    return ProcResult(proc.returncode or 0, out_b.decode(errors="replace"), err_b.decode(errors="replace"))


# ---------------------------------------------------------------- multipass

async def multipass(args: list[str], *, timeout: float = 60) -> ProcResult:
    return await _run(["multipass", *args], timeout=timeout)


async def list_vms() -> dict[str, dict]:
    """{name: {state, ips}} — levanta RuntimeError se o daemon estiver fora."""
    res = await multipass(["list", "--format", "json"], timeout=20)
    if not res.ok:
        raise RuntimeError(f"multipass list falhou: {res.err.strip() or res.out.strip()}")
    data = None
    try:
        data = json.loads(res.out)
    except ValueError as exc:
        raise RuntimeError(f"multipass list retornou JSON inválido: {exc}") from exc
    vms: dict[str, dict] = {}
    for item in (data or {}).get("list", []):
        ips = [ip for ip in (item.get("ipv4") or []) if ip and ip != "--"]
        vms[item.get("name", "")] = {"state": item.get("state", "Unknown"), "ips": ips}
    return vms


# ---------------------------------------------------------------- TCP / SSH

async def tcp_open(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def bridge_ips(ips: list[str]) -> list[str]:
    """Resolve bridged LAN IPs, preferring current BRIDGE_PREFIX and excluding NAT/CNI overlays."""
    prefix = config.bridge_prefix()
    matched = [ip for ip in ips if prefix and ip.startswith(prefix)]
    if matched:
        return matched
    ignored_prefixes = ("127.", "10.32.", "10.38.", "10.40.", "10.44.", "10.46.", "10.244.", "169.254.")
    nat_prefixes = ("192.168.64.", "192.168.252.")
    return [
        ip for ip in ips
        if ip and not ip.startswith(ignored_prefixes) and not ip.startswith(nat_prefixes)
    ]


async def resolve_ip(ips: list[str], port: int = 22) -> str | None:
    for ip in bridge_ips(ips):
        if await tcp_open(ip, port):
            return ip
    return None


def _ssh_base(ip: str) -> list[str]:
    args = [
        "ssh",
        "-i", str(config.SSH_KEY_PATH),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={config.SSH_CONNECT_TIMEOUT}",
        "-o", "LogLevel=ERROR",
    ]
    if config.SSH_CONTROL_PATH.parent.is_dir():
        args += [
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={config.SSH_CONTROL_PATH}",
            "-o", "ControlPersist=120",
        ]
    args.append(f"ubuntu@{ip}")
    return args


async def ssh_run(
    ip: str,
    command: str,
    *,
    timeout: float = config.SSH_EXEC_TIMEOUT,
    stdin_data: str | None = None,
) -> ProcResult:
    # Um único argumento: o OpenSSH o envia verbatim ao shell remoto (sem re-split).
    return await _run(_ssh_base(ip) + [command], timeout=timeout, stdin_data=stdin_data)


async def ssh_authorized(ip: str) -> bool:
    return (await ssh_run(ip, "true", timeout=6)).ok


_ASKPASS_SCRIPT = "#!/bin/sh\nprintf '%s\\n' \"$CKA_SSH_PASSWORD\"\n"

_ASKPASS_REMOTE = (
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
    'chmod 600 ~/.ssh/authorized_keys && key=$(cat) && '
    '(grep -qxF "$key" ~/.ssh/authorized_keys || '
    'printf "%s\\n" "$key" >> ~/.ssh/authorized_keys) && '
    "echo KEY_OK"
)


async def install_key(ip: str, password: str) -> ProcResult:
    """Instala a chave pública via SSH_ASKPASS (OpenSSH >= 8.4) — sem sshpass/expect."""
    config.CKA_DIR.mkdir(parents=True, exist_ok=True)
    askpass = config.CKA_DIR / "askpass.sh"
    if not askpass.exists() or askpass.read_text() != _ASKPASS_SCRIPT:
        askpass.write_text(_ASKPASS_SCRIPT)
    askpass.chmod(0o700)
    env = {
        "CKA_SSH_PASSWORD": password,
        "SSH_ASKPASS": str(askpass),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": ":0",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
    }
    return await _run(
        [
            "ssh",
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={config.SSH_CONNECT_TIMEOUT}",
            "-o", "LogLevel=ERROR",
            f"ubuntu@{ip}",
            _ASKPASS_REMOTE,
        ],
        timeout=25,
        stdin_data=config.SSH_KEY_PUB_PATH.read_text(),
        env=env,
    )


async def sudo_run(
    ip: str,
    script: str,
    *,
    password: str | None = None,
    timeout: float = 60,
) -> ProcResult:
    res = await ssh_run(ip, f"sudo -n bash -c {shlex.quote(script)}", timeout=timeout)
    if res.ok:
        return res
    pw = password or config.LAB_PASSWORD
    return await ssh_run(
        ip,
        f"sudo -S -p '' bash -c {shlex.quote(script)}",
        timeout=timeout,
        stdin_data=pw + "\n",
    )


# ---------------------------------------------------------------- chave + config

def ensure_keypair() -> None:
    config.CKA_DIR.mkdir(parents=True, exist_ok=True)
    if config.SSH_KEY_PATH.exists():
        return
    subprocess.run(
        [
            "ssh-keygen", "-t", "ed25519", "-N", "", "-C", config.SSH_KEY_COMMENT,
            "-f", str(config.SSH_KEY_PATH),
        ],
        check=True,
        capture_output=True,
    )
    config.SSH_KEY_PATH.chmod(0o600)


def render_ssh_block(ips: dict[str, str]) -> str:
    lines = [config.SSH_BLOCK_START]
    for name in config.VM_NAMES:
        ip = ips.get(name)
        if not ip:
            continue
        lines += [
            f"Host {config.NODE_ALIAS[name]}",
            f"  HostName {ip}",
            "  User ubuntu",
            f"  IdentityFile {config.SSH_KEY_PATH}",
            "  StrictHostKeyChecking accept-new",
            f"  ConnectTimeout {config.SSH_CONNECT_TIMEOUT}",
            "",
        ]
    lines.append(config.SSH_BLOCK_END)
    return "\n".join(lines) + "\n"


def write_managed_ssh_config(ips: dict[str, str], path: Path | None = None) -> str:
    """Escreve/atualiza o bloco gerenciado preservando o restante do arquivo."""
    target = path or config.SSH_CONFIG_PATH
    current = target.read_text() if target.exists() else ""
    start, end = config.SSH_BLOCK_START, config.SSH_BLOCK_END
    if start in current and end in current:
        before = current.split(start, 1)[0].rstrip()
        after = current.split(end, 1)[1]
        new = before + "\n\n" + render_ssh_block(ips) + after
    else:
        base = current.rstrip()
        new = (base + "\n\n" if base else "") + render_ssh_block(ips)
    new = new.strip("\n") + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new)
    return new


# ---------------------------------------------------------------- kubeconfig

_SERVER_RE = re.compile(r"(?m)^(\s*server:\s*)https://\S+\s*$")


def rewrite_kubeconfig_server(text: str, ip: str) -> str:
    if not _SERVER_RE.search(text):
        raise ValueError("linha 'server:' não encontrada no kubeconfig")
    return _SERVER_RE.sub(lambda m: f"{m.group(1)}https://{ip}:6443", text, count=1)


async def fetch_admin_conf(ip: str, password: str | None = None) -> str:
    res = await ssh_run(ip, "sudo -n cat /etc/kubernetes/admin.conf", timeout=15)
    if res.ok and "apiVersion:" in res.out:
        return res.out
    pw = password or config.LAB_PASSWORD
    res = await ssh_run(
        ip,
        "sudo -S -p '' cat /etc/kubernetes/admin.conf",
        timeout=15,
        stdin_data=pw + "\n",
    )
    if res.ok and "apiVersion:" in res.out:
        return res.out
    raise RuntimeError(f"não foi possível ler admin.conf em {ip}: {res.err.strip()[:300]}")


def ensure_exam_contexts(kubeconfig_path: Path | None = None) -> list[str]:
    """Ensure multi-context aliases (cka, cka-ops, cka-edge) exist in dedicated kubeconfig."""
    path = kubeconfig_path or config.KUBECONFIG_PATH
    if not path.exists():
        return []
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    contexts = doc.get("contexts")
    if not isinstance(contexts, list) or not contexts:
        return []
    base = next(
        (c for c in contexts if isinstance(c, dict) and c.get("name") == config.KUBECTL_CONTEXT),
        contexts[0] if isinstance(contexts[0], dict) else None,
    )
    if not base or not isinstance(base.get("context"), dict):
        return []
    cluster_ref = base["context"].get("cluster", "kubernetes")
    user_ref = base["context"].get("user", "kubernetes-admin")
    existing = {c.get("name") for c in contexts if isinstance(c, dict)}
    changed = False
    for name in config.KUBECTL_CONTEXTS:
        if name not in existing:
            contexts.append({
                "name": name,
                "context": {"cluster": cluster_ref, "user": user_ref},
            })
            changed = True
    if not doc.get("current-context"):
        doc["current-context"] = config.KUBECTL_CONTEXT
        changed = True
    if changed:
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return [str(c.get("name")) for c in contexts if isinstance(c, dict) and c.get("name")]


async def ensure_dedicated_kubeconfig(control_ip: str, password: str | None = None) -> Path:
    """Materializa ~/.cka-arena/kubeconfig com o IP atual e contexto `cka`."""
    text = await fetch_admin_conf(control_ip, password)
    text = rewrite_kubeconfig_server(text, control_ip)
    path = config.KUBECONFIG_PATH
    path.write_text(text)
    path.chmod(0o600)
    await _run(
        ["kubectl", "--kubeconfig", str(path), "config", "rename-context",
         "kubernetes-admin@kubernetes", config.KUBECTL_CONTEXT],
        timeout=10,
    )
    await _run(
        ["kubectl", "--kubeconfig", str(path), "config", "use-context", config.KUBECTL_CONTEXT],
        timeout=10,
    )
    ensure_exam_contexts(path)
    return path


async def wait_vm_ips(timeout_s: float = 240, interval: float = 3) -> dict[str, str]:
    """Aguarda os 3 nós com SSH acessível e devolve {nome: ip bridged}."""
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            vms = await list_vms()
        except Exception as exc:  # daemon momentaneamente indisponível
            last_error = str(exc)
            await asyncio.sleep(interval)
            continue
        resolved: dict[str, str] = {}
        for name in config.VM_NAMES:
            info = vms.get(name) or {}
            if info.get("state") != "Running":
                resolved = {}
                break
            ip = await resolve_ip(info.get("ips") or [])
            if not ip:
                resolved = {}
                break
            resolved[name] = ip
        if len(resolved) == len(config.VM_NAMES):
            return resolved
        await asyncio.sleep(interval)
    raise RuntimeError(f"SSH não ficou disponível nos 3 nós a tempo. {last_error[:200]}")


async def run_local(
    cmd: list[str],
    *,
    timeout: float = 20,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
) -> ProcResult:
    """Executa um comando local (ex.: helm). `env` explícito substitui o ambiente."""
    return await _run(cmd, timeout=timeout, stdin_data=stdin_data, env=env)


_NODE_EXAM_START = "# >>> cka-arena-exam >>>"
_NODE_EXAM_END = "# <<< cka-arena-exam <<<"
_NODE_BASHRC_SNIPPET = """export KUBE_EDITOR=vim
export EDITOR=vim
export VISUAL=vim
alias vi=vim
alias k=kubectl
export do="--dry-run=client -o yaml"
export now="--force --grace-period=0"
if command -v kubectl >/dev/null 2>&1; then
  source <(kubectl completion bash) 2>/dev/null || true
  complete -o default -F __start_kubectl k 2>/dev/null || true
fi"""


async def sync_node_exam_profile(
    ips: dict[str, str],
    vimrc_text: str | None = None,
) -> dict[str, bool]:
    """Install PSI exam .vimrc and bash profile on ubuntu + root across cluster nodes."""
    if vimrc_text is None:
        from app.terminal import EXAM_VIMRC_TEXT

        vimrc_text = EXAM_VIMRC_TEXT

    block = f"{_NODE_EXAM_START}\n{_NODE_BASHRC_SNIPPET}\n{_NODE_EXAM_END}\n"
    update_script = "\n".join([
        "set -e",
        f"cat <<'CKA_VIMRC_EOF' > /home/ubuntu/.vimrc\n{vimrc_text.rstrip()}\nCKA_VIMRC_EOF",
        "sudo mkdir -p /root",
        "sudo cp /home/ubuntu/.vimrc /root/.vimrc",
        "sudo chmod 0644 /home/ubuntu/.vimrc /root/.vimrc",
        "for rc in /home/ubuntu/.bashrc /root/.bashrc; do",
        '  sudo python3 - "$rc" <<\'PY\'',
        "import pathlib, sys",
        "p = pathlib.Path(sys.argv[1])",
        "cur = p.read_text() if p.exists() else ''",
        f"s, e = {_NODE_EXAM_START!r}, {_NODE_EXAM_END!r}",
        f"blk = {block.strip()!r}",
        "if s in cur and e in cur:",
        "    new = cur.split(s, 1)[0].rstrip() + '\\n\\n' + blk + cur.split(e, 1)[1]",
        "else:",
        "    new = (cur.rstrip() + '\\n\\n' if cur.strip() else '') + blk",
        "p.write_text(new.strip('\\n') + '\\n')",
        "PY",
        "done",
    ])
    results: dict[str, bool] = {}
    for name, ip in ips.items():
        if not ip:
            results[name] = False
            continue
        res = await ssh_run(ip, "bash -s", timeout=20, stdin_data=update_script + "\n")
        results[name] = res.ok
    return results
