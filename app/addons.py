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
ENVOY_CHARTS = (
    "oci://mirror.gcr.io/envoyproxy/gateway-helm",
    "oci://docker.io/envoyproxy/gateway-helm",
)


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

    helm_env = {**os.environ, "KUBECONFIG": str(config.KUBECONFIG_PATH)}
    last_err = ""
    for chart in ENVOY_CHARTS:
        res = await run_local([
            "helm", "upgrade", "--install", "eg", chart,
            "--version", ENVOY_VERSION, "-n", "envoy-gateway-system", "--create-namespace",
        ], timeout=300, env=helm_env)
        if res.ok:
            log(f"envoy-gateway: installed via helm ({chart})")
            return True
        last_err = (res.err or res.out).strip()[:200]
        log(f"envoy-gateway: helm attempt failed ({chart}) — {last_err}")
    log(f"envoy-gateway: all helm chart registries failed — {last_err}")
    return False


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


async def install_etcdutl(etcd_ver: str = "v3.5.17") -> bool:
    """Install etcdutl on controlplane if absent (idempotent, works on Multipass & kind)."""
    from app import provider

    prov = provider.get()
    try:
        control = (await prov.nodes()).get("controlplane")
    except Exception:
        control = None
    if not control or control.state != "Running":
        log("etcdutl: controlplane not running — skipped")
        return False

    probe = await prov.exec("controlplane", "command -v etcdutl", timeout=8)
    if probe.ok:
        log("etcdutl: already present on controlplane")
        return True

    script = (
        "set -e; "
        "ARCH=$(uname -m); "
        "case \"$ARCH\" in aarch64|arm64) E_ARCH=arm64;; x86_64|amd64) E_ARCH=amd64;; *) exit 1;; esac; "
        f"URL=\"https://github.com/etcd-io/etcd/releases/download/{etcd_ver}/etcd-{etcd_ver}-linux-${{E_ARCH}}.tar.gz\"; "
        "TMP=$(mktemp -d); trap 'rm -rf \"$TMP\"' EXIT; "
        "curl -fsSL \"$URL\" -o \"$TMP/etcd.tgz\"; "
        "tar -xzf \"$TMP/etcd.tgz\" -C \"$TMP\"; "
        f"install -m 0755 \"$TMP/etcd-{etcd_ver}-linux-${{E_ARCH}}/etcdutl\" /usr/local/bin/etcdutl"
    )
    res = await prov.exec("controlplane", script, sudo=True, timeout=90)
    if not res.ok:
        log(f"etcdutl: install failed — {(res.err or res.out).strip()[:200]}")
        return False
    log(f"etcdutl: installed ({etcd_ver}) on controlplane")
    return True


async def main() -> int:
    if not await cluster.readyz():
        log("cluster API is not ready — cannot install addons")
        return 1
    results = [
        await install_metrics_server(),
        await install_gateway(),
        await install_local_path(),
        await install_etcdutl(),
    ]
    failed = sum(1 for ok in results if not ok)
    if failed:
        log(f"{failed} addon(s) failed — the platform still works for core scenarios")
        return 1
    log("all addons ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
