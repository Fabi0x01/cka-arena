"""Configuração global do CKA Arena (Fase 1)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DB_PATH = BACKUP_DIR / "cka_arena_backup.db"
BACKUP_MANIFEST_PATH = BACKUP_DIR / "manifest.json"

# Estado local do CKA Arena (fora do repositório)
CKA_DIR = Path.home() / ".cka-arena"
KUBECONFIG_PATH = CKA_DIR / "kubeconfig"
SSH_KEY_PATH = CKA_DIR / "id_ed25519"
SSH_KEY_PUB_PATH = CKA_DIR / "id_ed25519.pub"
SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
SSH_CONTROL_PATH = CKA_DIR / "ssh-mux-%r@%h:%p"
SCRATCH_ROOT = CKA_DIR / "scratch"   # workdir isolada por aba de terminal (ARCHITECTURE.md §8)
ASSETS_DIR = CKA_DIR / "assets"
SOURCE_ASSETS_DIR = BASE_DIR / "scenarios" / "seed" / "assets"
BASELINE_NODES_PATH = CKA_DIR / "baseline_nodes.json"

# Warm Probe Pod namespace (sem label cka-arena.io/managed)
WARM_PROBE_NAMESPACE = "cka-arena-system"
WARM_PROBE_POD = "cka-probe-runner"

# Snapshots/backups nos nós
BACKUP_ROOT = "/var/backups/cka-arena"

# Servidor
HOST = "127.0.0.1"
PORT = int(os.environ.get("CKA_PORT", "8765"))

# Cluster
KUBECTL_CONTEXT = "cka"
KUBECTL_CONTEXTS = ("cka", "cka-ops", "cka-edge")
VM_NAMES = ("controlplane", "node01", "node02")
NODE_ALIAS = {name: f"cka-{name}" for name in VM_NAMES}

def _default_bridge_prefix() -> str:
    explicit = os.environ.get("CKA_BRIDGE_PREFIX", "").strip()
    if explicit:
        return explicit
    try:
        stored = (CKA_DIR / "bridge_prefix").read_text().strip()
        if stored:
            return stored
    except OSError:
        pass
    return "192.168.1."


# SSH
LAB_PASSWORD = os.environ.get("CKA_LAB_PASSWORD", "ubuntu")
BRIDGE_PREFIX = _default_bridge_prefix()
SSH_CONNECT_TIMEOUT = 4
SSH_EXEC_TIMEOUT = 20
SSH_KEY_COMMENT = "cka-arena"


def bridge_prefix() -> str:
    """Resolve current bridged subnet prefix dynamically from env or ~/.cka-arena/bridge_prefix."""
    explicit = os.environ.get("CKA_BRIDGE_PREFIX", "").strip()
    if explicit:
        return explicit
    try:
        stored = (CKA_DIR / "bridge_prefix").read_text().strip()
        if stored:
            return stored
    except OSError:
        pass
    return BRIDGE_PREFIX

# Comportamento (decisões D3)
AUTO_START_ON_LAUNCH = os.environ.get("CKA_AUTO_START", "1") not in ("0", "false", "no")

# Exposição remota opcional (§10)
API_TOKEN = os.environ.get("CKA_ARENA_TOKEN") or None
ALLOW_REMOTE = os.environ.get("CKA_ARENA_ALLOW_REMOTE") == "1"

# Marcadores do bloco gerenciado em ~/.ssh/config
SSH_BLOCK_START = "# >>> CKA-ARENA MANAGED START >>>"
SSH_BLOCK_END = "# <<< CKA-ARENA MANAGED END <<<"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CKA_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    if SOURCE_ASSETS_DIR.is_dir():
        try:
            shutil.copytree(SOURCE_ASSETS_DIR, ASSETS_DIR, dirs_exist_ok=True)
        except OSError:
            pass
    try:
        CKA_DIR.chmod(0o700)
    except OSError:
        pass

# LLM (Fase 3)
LLM_CONFIG_PATH = Path(os.environ.get("CKA_LLM_CONFIG", str(BASE_DIR / "llm_config.json")))
