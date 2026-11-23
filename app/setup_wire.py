"""setup_wire — SSH key bridge + dedicated kubeconfig for the Multipass lab.

Used by setup.sh (step "wire"). Idempotent: skips what is already in place and
re-verifies the effect. The kind provider needs nothing here (kubeconfig is
exported by scripts/cluster/kind-up.sh and nodes are reached via docker exec).
"""

from __future__ import annotations

import asyncio

from app import cluster, config, provider, ssh_runner


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
    if not await cluster.wait_readyz(timeout_s=120):
        print("[wire] kube-apiserver is not ready — check the cluster")
        return 1
    nodes = await cluster.get_nodes()
    for node in nodes:
        print(f"[wire] node {node['name']}: ready={node['ready']} ip={node['internal_ip']}")
    synced = await ssh_runner.sync_node_exam_profile(ips)
    print(f"[wire] exam vim/bashrc synced: {synced}")
    return 0


async def main() -> int:
    if provider.get().name != "multipass":
        print("[wire] provider kind: kubeconfig + node mapping are written by kind-up.sh")
        return 0
    return await wire_multipass()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
