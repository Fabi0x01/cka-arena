"""setup_wire — SSH key bridge + dedicated kubeconfig for Multipass and kind labs.

Used by setup.sh (step "wire"). Idempotent: skips what is already in place and
re-verifies the effect.
"""

from __future__ import annotations

import asyncio
import base64

from app import cluster, config, provider, ssh_runner
from app.terminal import EXAM_VIMRC_TEXT


async def wire_multipass() -> int:
    ips = await ssh_runner.wait_vm_ips(timeout_s=240)
    ssh_runner.ensure_keypair()
    for name, ip in ips.items():
        if await ssh_runner.ssh_authorized(ip):
            print(f"[wire] {name}: key already authorized ({ip})")
            continue
        res = await ssh_runner.install_key(ip, config.LAB_PASSWORD)
        if not res.ok and not await ssh_runner.ssh_authorized(ip):
            print(f"[wire] {name}: ssh-copy-id failed — {(res.err or res.out).strip()[:200]}")
            return 1
        print(f"[wire] {name}: key installed ({ip})")
    ssh_runner.write_managed_ssh_config(ips)
    print("[wire] ~/.ssh/config managed block updated")

    if not config.KUBECONFIG_PATH.exists() or not await cluster.readyz():
        await ssh_runner.ensure_dedicated_kubeconfig(
            ips["controlplane"], config.LAB_PASSWORD
        )
        print("[wire] dedicated kubeconfig refreshed from controlplane")
    ssh_runner.ensure_exam_contexts(config.KUBECONFIG_PATH)
    if not await cluster.wait_readyz(timeout_s=120):
        print("[wire] kube-apiserver is not ready — check the cluster")
        return 1
    nodes = await cluster.get_nodes()
    for node in nodes:
        print(f"[wire] node {node['name']}: ready={node['ready']} ip={node['internal_ip']}")
    synced = await ssh_runner.sync_node_exam_profile(ips)
    print(f"[wire] exam vim/bashrc synced: {synced}")
    return 0


async def sync_kind_node_exam_profile() -> dict[str, bool]:
    """Install PSI exam .vimrc and bash profile inside running kind node containers."""
    node_provider = provider.get()
    vimrc_b64 = base64.b64encode((EXAM_VIMRC_TEXT.rstrip() + "\n").encode()).decode("ascii")
    block_text = (
        f"{ssh_runner._NODE_EXAM_START}\n"
        f"{ssh_runner._NODE_BASHRC_SNIPPET}\n"
        f"{ssh_runner._NODE_EXAM_END}\n"
    )
    block_b64 = base64.b64encode(block_text.encode()).decode("ascii")
    cmd = (
        f"printf '%s' '{vimrc_b64}' | base64 -d > /root/.vimrc && "
        f"touch /root/.bashrc && "
        f"(grep -q '{ssh_runner._NODE_EXAM_START}' /root/.bashrc || "
        f"printf '\\n%s\\n' \"$(printf '%s' '{block_b64}' | base64 -d)\" >> /root/.bashrc)"
    )
    synced: dict[str, bool] = {}
    for name in config.VM_NAMES:
        try:
            res = await node_provider.exec(name, cmd, timeout=15)
            synced[name] = res.ok
        except Exception:
            synced[name] = False
    return synced


async def wire_kind() -> int:
    contexts = ssh_runner.ensure_exam_contexts(config.KUBECONFIG_PATH)
    print(f"[wire] kind kubeconfig contexts: {contexts}")
    if not await cluster.wait_readyz(timeout_s=60):
        print("[wire] kube-apiserver is not ready — check the kind cluster")
        return 1
    nodes = await cluster.get_nodes()
    for node in nodes:
        print(f"[wire] node {node['name']}: ready={node['ready']} ip={node['internal_ip']}")
    synced = await sync_kind_node_exam_profile()
    print(f"[wire] kind node exam vim/bashrc synced: {synced}")
    return 0


async def main() -> int:
    if provider.get().name == "kind":
        return await wire_kind()
    return await wire_multipass()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
