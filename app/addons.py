"""addons — idempotent cluster addon installation (metrics-server, Gateway API + Envoy,
local-path-provisioner). Used by setup.sh; safe to re-run.

Every addon is installed through the dedicated kubeconfig (context `cka`) and is
skipped when already present. Failures are reported per-addon without aborting the
rest (practice works without addons; only addon-dependent scenarios are affected).
"""

from __future__ import annotations

import asyncio
import os
import shutil

from app import cluster, config

METRICS_SERVER = (
    "https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
)
GATEWAY_CRDS = (
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml"
)
LOCAL_PATH = (
    "https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.30/"
    "deploy/local-path-storage.yaml"
)
ENVOY_VERSION = "v1.2.0"


def log(message: str) -> None:
    print(f"[addons] {message}", flush=True)


async def _present(args: list[str]) -> bool:
    return (await cluster.kubectl(args, timeout=15)).ok


async def install_metrics_server() -> bool:
    if await _present(["get", "deployment", "metrics-server", "-n", "kube-system"]):
        log("metrics-server: already present")
        return True
    res = await cluster.kubectl(["apply", "-f", METRICS_SERVER], timeout=120)
    if not res.ok:
        log(f"metrics-server: apply failed — {(res.err or res.out).strip()[:200]}")
        return False
    # kubeadm kubelets use self-signed serving certs
    patch = (
        '[{"op": "add", "path": "/spec/template/spec/containers/0/args/-",'
        ' "value": "--kubelet-insecure-tls"}]'
    )
    patched = await cluster.kubectl([
        "-n", "kube-system", "patch", "deployment", "metrics-server",
        "--type=json", "-p", patch,
    ], timeout=30)
    if patched.ok:
        log("metrics-server: installed (kubelet-insecure-tls)")
    else:
        log("metrics-server: installed (patch skipped — already has the flag?)")
    return True


async def install_gateway() -> bool:
    if await _present(["get", "crd", "gatewayclasses.gateway.networking.k8s.io"]):
        log("gateway-api: already present")
    else:
        res = await cluster.kubectl(["apply", "-f", GATEWAY_CRDS], timeout=120)
        if not res.ok:
            log(f"gateway-api: apply failed — {(res.err or res.out).strip()[:200]}")
            return False
        log("gateway-api: CRDs installed")

    if await _present(["get", "deployment", "-n", "envoy-gateway-system", "envoy-gateway"]):
        log("envoy-gateway: already present")
        return True
    if not shutil.which("helm"):
        log("envoy-gateway: helm not found — skipped (Gateway scenarios need it)")
        return True
    from app.ssh_runner import run_local

    old = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(config.KUBECONFIG_PATH)
    try:
        res = await run_local([
            "helm", "upgrade", "--install", "eg", "oci://docker.io/envoyproxy/gateway-helm",
            "--version", ENVOY_VERSION, "-n", "envoy-gateway-system", "--create-namespace",
        ], timeout=300)
    finally:
        if old is None:
            os.environ.pop("KUBECONFIG", None)
        else:
            os.environ["KUBECONFIG"] = old
    if not res.ok:
        log(f"envoy-gateway: helm failed — {(res.err or res.out).strip()[:200]}")
        return False
    log("envoy-gateway: installed via helm")
    return True


async def install_local_path() -> bool:
    if await _present(["get", "storageclass", "local-path"]):
        log("local-path: already present")
        return True
    res = await cluster.kubectl(["apply", "-f", LOCAL_PATH], timeout=120)
    if not res.ok:
        log(f"local-path: apply failed — {(res.err or res.out).strip()[:200]}")
        return False
    log("local-path: installed")
    return True


async def main() -> int:
    if not await cluster.readyz():
        log("cluster API is not ready — cannot install addons")
        return 1
    results = [
        await install_metrics_server(),
        await install_gateway(),
        await install_local_path(),
    ]
    failed = sum(1 for ok in results if not ok)
    if failed:
        log(f"{failed} addon(s) failed — the platform still works for core scenarios")
        return 1
    log("all addons ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
