#!/usr/bin/env bash
# CKA Arena — one-command local setup.
# Detects OS/distro, audits prerequisites, asks before installing, provisions the
# lab nodes (Multipass VMs or kind containers), seeds the bank and starts the app.
#
# Usage: ./setup.sh [--yes] [--check] [--provider multipass|kind]
#                   [--skip-cluster] [--bridge IFACE] [--llm-config PATH]
#                   [--with-addons|--no-addons] [--step NAME]

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CKA_DIR="${CKA_DIR:-$HOME/.cka-arena}"
CKA_SETUP_LOG="${CKA_SETUP_LOG:-$CKA_DIR/setup.log}"
mkdir -p "$CKA_DIR"
: > "$CKA_SETUP_LOG"

# shellcheck source=scripts/lib/ui.sh
. "$SCRIPT_DIR/scripts/lib/ui.sh"
# shellcheck source=scripts/lib/detect.sh
. "$SCRIPT_DIR/scripts/lib/detect.sh"
# shellcheck source=scripts/lib/pkg.sh
. "$SCRIPT_DIR/scripts/lib/pkg.sh"
# shellcheck source=scripts/lib/state.sh
. "$SCRIPT_DIR/scripts/lib/state.sh"

export PATH="$CKA_BIN_DIR:$PATH"
trap ui_cleanup EXIT INT TERM

# ---------------------------------------------------------------- flags
CKA_ASSUME_YES=0
CHECK_ONLY=0
SKIP_CLUSTER=0
BRIDGE_IFACE=""
LLM_CONFIG=""
WITH_ADDONS=1
ONLY_STEP=""
PROVIDER=""
PROVIDER_FLAG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) CKA_ASSUME_YES=1 ;;
    --check) CHECK_ONLY=1 ;;
    --provider) PROVIDER_FLAG="$2"; shift ;;
    --skip-cluster) SKIP_CLUSTER=1 ;;
    --bridge) BRIDGE_IFACE="$2"; shift ;;
    --llm-config) LLM_CONFIG="$2"; shift ;;
    --with-addons) WITH_ADDONS=1 ;;
    --no-addons) WITH_ADDONS=0 ;;
    --step) ONLY_STEP="$2"; shift ;;
    -h|--help)
      cat <<'EOF'
CKA Arena setup

  --yes                 non-interactive: install missing prerequisites without asking
  --check               audit only (no installs, no changes); exit 1 if something is missing
  --provider NAME       multipass (macOS/Linux VMs) or kind (WSL2 / Linux+Docker)
  --skip-cluster        you already have a cluster wired to ~/.cka-arena/kubeconfig
  --bridge IFACE        network interface for Multipass bridged mode (auto-detected)
  --llm-config PATH     copy this LLM provider config to ./llm_config.json
  --with-addons         install metrics-server / Gateway API / local-path (default)
  --no-addons           skip addon installation
  --step NAME           run a single step: deps|cluster|wire|addons|seeds|server
EOF
      exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

export CKA_ASSUME_YES

# ---------------------------------------------------------------- banner
banner() {
  hr 72
  printf '%s\n' "${C_BOLD}  CKA Arena — local setup${C_RESET}"
  printf '%s\n' "${C_DIM}  CKA exam simulator with a real Kubernetes lab and AI scenario generator${C_RESET}"
  hr 72
}

# ---------------------------------------------------------------- prereqs
MISSING=()
declare -a CHECK_NAMES=() CHECK_HINTS=() CHECK_INSTALLERS=()

need() {  # need <display> <tool> <installer-fn>
  if has_cmd "$2"; then
    printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "$1" "${C_DIM}found${C_RESET}"
    return 0
  fi
  printf '  %s %-14s %s\n' "${C_RED}✖${C_RESET}" "$1" "${C_YELLOW}MISSING${C_RESET}"
  MISSING+=("$1")
  CHECK_NAMES+=("$1"); CHECK_HINTS+=("$(package_hint "$2")"); CHECK_INSTALLERS+=("$3")
  return 1
}

need_file() {  # need_file <display> <path>
  if [ -e "$2" ]; then
    printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "$1" "${C_DIM}found${C_RESET}"
    return 0
  fi
  printf '  %s %-14s %s\n' "${C_RED}✖${C_RESET}" "$1" "${C_YELLOW}MISSING${C_RESET}"
  MISSING+=("$1")
  return 1
}

audit_prereqs() {
  MISSING=(); CHECK_NAMES=(); CHECK_HINTS=(); CHECK_INSTALLERS=()
  info "Provider: ${C_BOLD}${PROVIDER}${C_RESET} · OS: ${C_BOLD}${OS_NAME}${C_RESET} (${ARCH})"
  echo
  need "uv" uv install_uv
  need "kubectl" kubectl install_kubectl
  need "jq" jq install_jq
  if [ "$PROVIDER" = "multipass" ]; then
    need "multipass" multipass install_multipass
    need "ssh" ssh install_openssh
  else
    need "docker" docker install_docker
    need "kind" kind install_kind
  fi

  echo
  detect_memory_gb; detect_disk_free_gb
  if [ "$MEM_GB" -lt 8 ]; then
    err "RAM: ${MEM_GB} GB — at least 8 GB required (16 GB recommended)"
    MISSING+=("8 GB RAM")
  elif [ "$MEM_GB" -lt 16 ]; then
    warn "RAM: ${MEM_GB} GB — 16 GB recommended for a smooth lab"
  else
    printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "memory" "${MEM_GB} GB"
  fi
  if [ "$DISK_FREE_GB" -lt 30 ]; then
    warn "disk: ${DISK_FREE_GB} GB free — 30 GB recommended"
  else
    printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "disk" "${DISK_FREE_GB} GB free"
  fi

  if [ "$PROVIDER" = "multipass" ]; then
    if [ "$OS_NAME" != "macos" ] && [ ! -e /dev/kvm ]; then
      warn "/dev/kvm not available — Multipass needs virtualization enabled in BIOS"
    fi
    detect_bridge_subnet
    [ -n "${BRIDGE_IFACE:-}" ] || BRIDGE_IFACE="$(_detect_default_iface)"
    if [ -n "$BRIDGE_SUBNET" ]; then
      printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "bridge subnet" "${BRIDGE_SUBNET}0/24"
    else
      warn "bridge subnet not detected — pass --bridge <iface> if the cluster cannot be reached"
    fi
  else
    detect_wsl_capabilities
    if [ "$OS_NAME" = "wsl" ] && [ "$WSL_SYSTEMD" != "1" ]; then
      err "systemd is not PID 1 inside WSL — kind nodes need it (enable systemd in /etc/wsl.conf, Windows 11)"
      MISSING+=("WSL systemd")
    fi
    if [ "$OS_NAME" = "wsl" ] && [ "$WSL_CGROUP_V2" != "1" ]; then
      err "cgroup v2 not detected — required by kind nodes"
      MISSING+=("WSL cgroup v2")
    fi
    if has_cmd docker && ! docker info >/dev/null 2>&1; then
      warn "docker is installed but the daemon is not reachable (start Docker / systemctl start docker)"
    fi
  fi
}

_detect_default_iface() {
  if [ "$OS_NAME" = "macos" ]; then
    route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}'
  else
    ip route 2>/dev/null | awk '$1=="default" {print $5; exit}'
  fi
}

install_missing() {
  local i tool
  [ "${#MISSING[@]}" -eq 0 ] && return 0
  echo
  warn "Missing prerequisites: ${MISSING[*]}"
  if [ "$CHECK_ONLY" = "1" ]; then return 1; fi
  for i in "${!CHECK_NAMES[@]}"; do
    tool="${CHECK_NAMES[$i]}"
    if [ -z "${CHECK_INSTALLERS[$i]:-}" ]; then
      err "cannot auto-install ${tool} — ${CHECK_HINTS[$i]}"
      return 1
    fi
    if confirm "Install ${tool} now?" "y"; then
      spinner_start "installing ${tool}…"
      if "${CHECK_INSTALLERS[$i]}"; then
        spinner_stop "${tool} installed"
      else
        spinner_stop
        err "failed to install ${tool} — ${CHECK_HINTS[$i]}"
        log_line "hint: ${CHECK_HINTS[$i]}"
        return 1
      fi
    else
      err "skipped ${tool} — ${CHECK_HINTS[$i]}"
      return 1
    fi
  done
}

# ---------------------------------------------------------------- python deps
run_deps() {
  if [ -n "$LLM_CONFIG" ]; then
    if [ -f "$LLM_CONFIG" ]; then
      cp "$LLM_CONFIG" "$SCRIPT_DIR/llm_config.json"
      ok "LLM config copied to ./llm_config.json (git-ignored)"
    else
      warn "--llm-config path not found: $LLM_CONFIG"
    fi
  fi
  step "Installing Python dependencies"
  spinner_start "uv sync…"
  if uv sync --quiet >>"$CKA_SETUP_LOG" 2>&1; then
    spinner_stop "Python dependencies ready"
    state_set deps "done"
  else
    spinner_stop; err "uv sync failed — see $CKA_SETUP_LOG"; exit 1
  fi
}

# ---------------------------------------------------------------- cluster
run_cluster() {
  step "Provisioning the Kubernetes lab (${PROVIDER})"
  if [ "$SKIP_CLUSTER" = "1" ]; then
    if ! uv run python - <<'PY' >>"$CKA_SETUP_LOG" 2>&1
import asyncio, sys
from app import cluster
sys.exit(0 if asyncio.run(cluster.ready()) else 1)
PY
    then
      warn "--skip-cluster given but the API at ~/.cka-arena/kubeconfig is not ready"
    else
      step_done "cluster already ready — skipping provisioning"
      return 0
    fi
  elif state_has cluster_up; then
    if uv run python - <<'PY' >>"$CKA_SETUP_LOG" 2>&1
import asyncio, sys
from app import cluster
sys.exit(0 if asyncio.run(cluster.ready()) else 1)
PY
    then
      step_done "cluster already ready — skipping provisioning"
      return 0
    fi
    warn "state says cluster is up, but the API is not ready — reprovisioning"
    state_clear cluster_up
  fi
  local script
  if [ "$PROVIDER" = "kind" ]; then script="$SCRIPT_DIR/scripts/cluster/kind-up.sh"; else script="$SCRIPT_DIR/scripts/cluster/up.sh"; fi
  [ -x "$script" ] || die "missing $script"
  spinner_start "provisioning nodes (this takes a few minutes)…"
  if "$script" >>"$CKA_SETUP_LOG" 2>&1; then
    spinner_stop "nodes ready"
    state_set cluster_up "done"
  else
    spinner_stop
    err "cluster provisioning failed — last lines of $CKA_SETUP_LOG:"
    tail -20 "$CKA_SETUP_LOG" >&2 || true
    exit 1
  fi
}

# ---------------------------------------------------------------- wiring (multipass)
run_wire() {
  step "Wiring access (kubeconfig + SSH bridge)"
  if [ "$PROVIDER" = "kind" ]; then
    step_done "kind kubeconfig already exported by kind-up.sh"
    return 0
  fi
  spinner_start "installing SSH key and dedicated kubeconfig…"
  if CKA_BRIDGE_IFACE="${BRIDGE_IFACE}" uv run python -m app.setup_wire >>"$CKA_SETUP_LOG" 2>&1; then
    spinner_stop "SSH bridge + kubeconfig ready"
    state_set wire "done"
  else
    spinner_stop; err "wiring failed — see $CKA_SETUP_LOG"; exit 1
  fi
}

# ---------------------------------------------------------------- addons
run_addons() {
  step "Installing cluster addons"
  if [ "$WITH_ADDONS" = "0" ]; then
    step_done "skipped (--no-addons)"
    return 0
  fi
  spinner_start "metrics-server · Gateway API/Envoy · local-path…"
  if uv run python -m app.addons >>"$CKA_SETUP_LOG" 2>&1; then
    spinner_stop "addons ready"
    state_set addons "done"
  else
    spinner_stop; warn "addon installation had problems — see $CKA_SETUP_LOG (practice still works)"
  fi
}

# ---------------------------------------------------------------- seeds
run_seeds() {
  step "Seeding the question bank"
  spinner_start "publishing seed questions…"
  if uv run python -m app.seed >>"$CKA_SETUP_LOG" 2>&1; then
    local count
    count="$(sqlite3 "$SCRIPT_DIR/data/cka_arena.db" "select count(*) from bank_questions where state='published'" 2>/dev/null || echo '?')"
    spinner_stop "question bank ready (${count} published)"
    state_set seeds "done"
  else
    spinner_stop; err "seeding failed — see $CKA_SETUP_LOG"; exit 1
  fi
}

# ---------------------------------------------------------------- server
SERVER_URL="http://127.0.0.1:8765"

server_healthy() { curl -fsS --max-time 2 "$SERVER_URL/api/health" >/dev/null 2>&1; }

run_server() {
  step "Starting the platform"
  if server_healthy; then
    step_done "server already running at $SERVER_URL"
    return 0
  fi
  spinner_start "starting server…"
  nohup uv run cka-arena >>"$CKA_DIR/server.log" 2>&1 &
  echo $! > "$CKA_DIR/server.pid"
  local i
  for i in $(seq 1 30); do
    sleep 1
    if server_healthy; then
      spinner_stop "server ready"
      state_set server "done"
      return 0
    fi
  done
  spinner_stop; err "server did not become healthy — see $CKA_DIR/server.log"; exit 1
}

# ---------------------------------------------------------------- final banner
final_banner() {
  local provider_note="VMs via Multipass (user ${C_BOLD}ubuntu${C_RESET} / password ${C_BOLD}ubuntu${C_RESET})"
  [ "$PROVIDER" = "kind" ] && provider_note="containers via kind (node shells open with docker exec)"
  hr 72
  printf '%s\n' "${C_GREEN}${C_BOLD} ✔ CKA Arena is ready${C_RESET}"
  echo
  printf ' %s Open:       %s%s%s\n' "▸" "$C_CYAN" "$SERVER_URL" "$C_RESET"
  printf ' %s Terminal:   real shell on this machine (tab "mac", isolated scratch dir)\n' "▸"
  printf ' %s Lab nodes:  %s\n' "▸" "$provider_note"
  echo
  printf '%s\n' "${C_BOLD} Configure (all optional):${C_RESET}"
  printf ' %s AI generation — put a provider key in %sllm_config.json%s\n' "▸" "$C_DIM" "$C_RESET"
  printf '                  (%ssee llm_config.example.json; Practice works without it%s)\n' "$C_DIM" "$C_RESET"
  printf ' %s Lab password  — override with %sCKA_LAB_PASSWORD%s before re-running setup\n' "▸" "$C_DIM" "$C_RESET"
  printf ' %s Power          — start/stop the lab from the header pill\n' "▸"
  echo
  printf '%s\n' "${C_DIM} Logs: $CKA_DIR/setup.log · data: $SCRIPT_DIR/data · state: $CKA_DIR${C_RESET}"
  hr 72
}

# ---------------------------------------------------------------- main
main() {
  banner
  step "Detecting environment"
  detect_os; detect_pkg_manager; detect_provider
  # explicit --provider wins over detection
  if [ -n "$PROVIDER_FLAG" ]; then PROVIDER="$PROVIDER_FLAG"; fi
  echo "$PROVIDER" > "$CKA_DIR/provider" 2>/dev/null || true
  printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "os" "${OS_NAME} ${OS_VERSION} (${ARCH})"
  printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "provider" "$PROVIDER"
  printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "package mgr" "${PKG_MANAGER:-none}"

  step "Checking prerequisites"
  audit_prereqs
  if ! install_missing; then
    echo
    if [ "$CHECK_ONLY" = "1" ]; then
      err "prerequisite audit failed — nothing was changed (--check mode)"
    else
      err "setup stopped — fix the items above and re-run ./setup.sh"
    fi
    exit 1
  fi
  if [ "$CHECK_ONLY" = "1" ]; then
    step_done "all prerequisites present"
    exit 0
  fi

  if [ -n "$ONLY_STEP" ]; then
    case "$ONLY_STEP" in
      deps) run_deps ;;
      cluster) run_cluster ;;
      wire) run_wire ;;
      addons) run_addons ;;
      seeds) run_seeds ;;
      server) run_server ;;
      *) die "unknown step: $ONLY_STEP" ;;
    esac
    final_banner
    exit 0
  fi

  run_deps
  run_cluster
  run_wire
  run_addons
  run_seeds
  run_server
  final_banner
}

main "$@"
