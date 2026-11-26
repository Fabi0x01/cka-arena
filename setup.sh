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
FORCE_RESTART=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) CKA_ASSUME_YES=1 ;;
    --check) CHECK_ONLY=1 ;;
    --provider)
      [ $# -ge 2 ] || { printf '✖ --provider requires a value (multipass or kind)\n' >&2; exit 1; }
      PROVIDER_FLAG="$2"; shift ;;
    --skip-cluster) SKIP_CLUSTER=1 ;;
    --restart) FORCE_RESTART=1 ;;
    --bridge)
      [ $# -ge 2 ] || { printf '✖ --bridge requires a value\n' >&2; exit 1; }
      BRIDGE_IFACE="$2"; shift ;;
    --llm-config)
      [ $# -ge 2 ] || { printf '✖ --llm-config requires a value\n' >&2; exit 1; }
      LLM_CONFIG="$2"; shift ;;
    --with-addons) WITH_ADDONS=1 ;;
    --no-addons) WITH_ADDONS=0 ;;
    --step)
      [ $# -ge 2 ] || { printf '✖ --step requires a value\n' >&2; exit 1; }
      ONLY_STEP="$2"; shift ;;
    -h|--help)
      cat <<'EOF'
CKA Arena setup

  --yes                 non-interactive: install missing prerequisites without asking
  --check               audit only (no installs, no changes); exit 1 if something is missing
  --provider NAME       multipass (macOS/Linux VMs) or kind (WSL2 / Linux+Docker)
  --skip-cluster        you already have a cluster wired to ~/.cka-arena/kubeconfig
  --restart             force restarting the platform server even if a session is active
  --bridge IFACE        network interface for Multipass bridged mode (auto-detected)
  --llm-config PATH     copy this LLM provider config to ./llm_config.json
  --with-addons         install metrics-server / Gateway API / local-path (default)
  --no-addons           skip addon installation
  --step NAME           run a single step: deps|cluster|wire|addons|seeds|server
EOF
      exit 0 ;;
    *)
      printf '✖ unknown option: %s (try --help)\n' "$1" >&2
      exit 1 ;;
  esac
  shift
done

CKA_DIR="${CKA_DIR:-$HOME/.cka-arena}"
if [ "$CHECK_ONLY" = "1" ]; then
  CKA_SETUP_LOG="/dev/null"
else
  CKA_SETUP_LOG="${CKA_SETUP_LOG:-$CKA_DIR/setup.log}"
  mkdir -p "$CKA_DIR"
  : > "$CKA_SETUP_LOG"
fi
export CKA_DIR CKA_SETUP_LOG CKA_ASSUME_YES

# shellcheck source=scripts/lib/ui.sh
. "$SCRIPT_DIR/scripts/lib/ui.sh"
# shellcheck source=scripts/lib/detect.sh
. "$SCRIPT_DIR/scripts/lib/detect.sh"
# shellcheck source=scripts/lib/pkg.sh
. "$SCRIPT_DIR/scripts/lib/pkg.sh"
# shellcheck source=scripts/lib/state.sh
. "$SCRIPT_DIR/scripts/lib/state.sh"

refresh_path
trap ui_cleanup EXIT INT TERM

if [ "$CHECK_ONLY" = "1" ]; then
  UI_STEP_TOTAL=2
elif [ -n "$ONLY_STEP" ]; then
  UI_STEP_TOTAL=3
else
  UI_STEP_TOTAL=8
fi

if [ -n "$PROVIDER_FLAG" ] && [ "$PROVIDER_FLAG" != "multipass" ] && [ "$PROVIDER_FLAG" != "kind" ]; then
  die "invalid --provider '$PROVIDER_FLAG' (expected: multipass or kind)"
fi

# ---------------------------------------------------------------- banner
banner() {
  hr 72
  printf '%s\n' "${C_BOLD}  CKA Arena — local setup${C_RESET}"
  printf '%s\n' "${C_DIM}  CKA exam simulator with a real Kubernetes lab and AI scenario generator${C_RESET}"
  hr 72
}

# ---------------------------------------------------------------- prereqs
MISSING=()
BLOCKERS=()
CHECK_NAMES=()
CHECK_TOOLS=()
CHECK_HINTS=()
CHECK_INSTALLERS=()
USE_SG_DOCKER=0
DOCKER_GROUP_ADDED=0

need() {  # need <display> <tool> <installer-fn>
  local hint
  if has_cmd "$2"; then
    printf '  %s %-14s %s\n' "${C_GREEN}✔${C_RESET}" "$1" "${C_DIM}found${C_RESET}"
    return 0
  fi
  printf '  %s %-14s %s\n' "${C_RED}✖${C_RESET}" "$1" "${C_YELLOW}MISSING${C_RESET}"
  hint="$(package_hint "$2")"
  MISSING+=("$1")
  CHECK_NAMES+=("$1")
  CHECK_TOOLS+=("$2")
  CHECK_HINTS+=("$hint")
  CHECK_INSTALLERS+=("$3")
  return 0
}

_detect_default_iface() {
  if [ "$OS_NAME" = "macos" ]; then
    route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}'
  else
    ip route 2>/dev/null | awk '$1=="default" {print $5; exit}'
  fi
}

_docker_reachable() {
  has_cmd docker || return 1
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  if has_cmd sg && sg docker -c "docker info" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

audit_prereqs() {
  MISSING=(); BLOCKERS=()
  CHECK_NAMES=(); CHECK_TOOLS=(); CHECK_HINTS=(); CHECK_INSTALLERS=()

  info "Provider: ${C_BOLD}${PROVIDER}${C_RESET} · OS: ${C_BOLD}${OS_NAME}${C_RESET} (${ARCH})"
  echo
  need "curl" curl install_curl
  need "git" git install_git
  need "uv" uv install_uv
  need "kubectl" kubectl install_kubectl
  need "helm" helm install_helm
  need "jq" jq install_jq
  need "vim" vim install_vim
  if [ "$PROVIDER" = "multipass" ]; then
    need "multipass" multipass install_multipass
    need "ssh" ssh install_openssh
  else
    need "docker" docker install_docker
    need "kind" kind install_kind
  fi

  # On macOS without Homebrew, offer Homebrew first if any brew-managed dependency is missing.
  if [ "$OS_NAME" = "macos" ] && ! has_cmd brew && [ "${#CHECK_TOOLS[@]}" -gt 0 ]; then
    local needs_brew=0 idx=0 t brew_hint
    while [ "$idx" -lt "${#CHECK_TOOLS[@]}" ]; do
      t="${CHECK_TOOLS[$idx]}"
      case "$t" in
        curl|git|jq|vim|multipass|ssh|docker) needs_brew=1; break ;;
      esac
      idx=$((idx + 1))
    done
    if [ "$needs_brew" = "1" ]; then
      printf '  %s %-14s %s\n' "${C_RED}✖${C_RESET}" "homebrew" "${C_YELLOW}MISSING${C_RESET}"
      brew_hint="$(package_hint homebrew)"
      MISSING=("homebrew" "${MISSING[@]}")
      CHECK_NAMES=("homebrew" "${CHECK_NAMES[@]}")
      CHECK_TOOLS=("homebrew" "${CHECK_TOOLS[@]}")
      CHECK_HINTS=("$brew_hint" "${CHECK_HINTS[@]}")
      CHECK_INSTALLERS=("install_homebrew" "${CHECK_INSTALLERS[@]}")
    fi
  fi

  echo
  detect_memory_gb; detect_disk_free_gb
  if [ "$MEM_GB" -lt 8 ]; then
    err "RAM: ${MEM_GB} GB — at least 8 GB required (16 GB recommended)"
    BLOCKERS+=("8 GB RAM (found ${MEM_GB} GB)")
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
    local docker_ok=0
    if _docker_reachable; then docker_ok=1; fi

    if [ "$OS_NAME" = "wsl" ] && [ "$WSL_SYSTEMD" != "1" ]; then
      if [ "$docker_ok" = "1" ] || [ "$WSL_DOCKER_DESKTOP" = "1" ]; then
        warn "WSL systemd is off (using Docker Desktop integration)"
      else
        err "systemd is not PID 1 inside WSL — enable it in /etc/wsl.conf ([boot] systemd=true), run 'wsl --shutdown' in PowerShell, and reopen WSL"
        BLOCKERS+=("WSL systemd")
        MISSING+=("WSL systemd")
      fi
    fi
    if [ "$OS_NAME" = "wsl" ] && [ "$WSL_CGROUP_V2" != "1" ]; then
      if [ "$docker_ok" = "1" ] || [ "$WSL_DOCKER_DESKTOP" = "1" ]; then
        warn "cgroup v2 not detected in WSL distro (using Docker Desktop)"
      else
        err "cgroup v2 not detected — required by native kind nodes (run 'wsl --update' and enable systemd)"
        BLOCKERS+=("WSL cgroup v2")
        MISSING+=("WSL cgroup v2")
      fi
    fi
    if has_cmd docker && [ "$docker_ok" = "0" ]; then
      if [ "$CHECK_ONLY" = "1" ]; then
        err "docker is installed but the daemon is not reachable (start docker or add user to docker group)"
        BLOCKERS+=("docker daemon")
        MISSING+=("docker daemon")
      else
        warn "docker is installed but the daemon is not reachable — setup will ask before starting/configuring it"
      fi
    fi
  fi
}

install_missing() {
  local i=0 name tool hint fn desc summary="" verify_cmd=""
  if [ "${#BLOCKERS[@]}" -gt 0 ]; then
    echo
    warn "Missing / blocked prerequisites: ${MISSING[*]}"
    if [ "${#CHECK_NAMES[@]}" -gt 0 ]; then
      warn "Note: fix the system blocker(s) (${BLOCKERS[*]}) in addition to installing: ${CHECK_NAMES[*]}"
    else
      err "System blocker(s) require manual action: ${BLOCKERS[*]}"
    fi
    return 1
  fi

  [ "${#CHECK_NAMES[@]}" -eq 0 ] && return 0

  while [ "$i" -lt "${#CHECK_NAMES[@]}" ]; do
    summary="${summary:+${summary}, }${CHECK_NAMES[$i]}"
    i=$((i + 1))
  done
  echo
  warn "Missing prerequisites: ${summary}"
  if [ "$CHECK_ONLY" = "1" ]; then return 1; fi

  if [ "${CKA_ASSUME_YES:-0}" != "1" ] && [ ! -t 0 ]; then
    err "non-interactive terminal detected — re-run interactively to approve installs, or pass --yes"
    return 1
  fi

  i=0
  while [ "$i" -lt "${#CHECK_NAMES[@]}" ]; do
    name="${CHECK_NAMES[$i]}"
    tool="${CHECK_TOOLS[$i]}"
    hint="${CHECK_HINTS[$i]}"
    fn="${CHECK_INSTALLERS[$i]}"

    if [ -z "$fn" ]; then
      err "cannot auto-install ${name} — ${hint}"
      return 1
    fi

    desc="$(install_description "$tool")"
    if confirm "Install ${name} (${desc})?" "y"; then
      if installer_needs_sudo "$fn"; then
        if ! ensure_sudo; then
          err "sudo authentication failed — cannot install ${name}"
          return 1
        fi
      fi
      spinner_start "installing ${name}…"
      if "$fn"; then
        refresh_path
        if [ "$tool" = "homebrew" ]; then detect_pkg_manager; fi
        verify_cmd="$tool"
        [ "$tool" = "homebrew" ] && verify_cmd="brew"
        if has_cmd "$verify_cmd"; then
          spinner_stop "${name} installed"
        else
          spinner_stop
          err "${name} installer finished, but '${verify_cmd}' is not in PATH — see ${CKA_SETUP_LOG}"
          return 1
        fi
      else
        spinner_stop
        err "failed to install ${name} — manual option: ${hint}"
        log_line "hint: ${hint}"
        return 1
      fi
    else
      err "installation declined for ${name} — install manually: ${hint}"
      return 1
    fi
    i=$((i + 1))
  done
  return 0
}

ensure_docker_ready() {
  [ "$PROVIDER" = "kind" ] || return 0
  [ "$CHECK_ONLY" = "1" ] && return 0

  if docker info >/dev/null 2>&1; then
    USE_SG_DOCKER=0
    return 0
  fi
  if has_cmd sg && sg docker -c "docker info" >/dev/null 2>&1; then
    USE_SG_DOCKER=1
    ok "docker reachable via 'docker' group"
    return 0
  fi

  if [ "$OS_NAME" = "macos" ]; then
    err "Docker daemon is not running — open Docker Desktop (or OrbStack/Colima) and re-run ./setup.sh"
    return 1
  fi

  # Start docker daemon via systemd if inactive (always ask first)
  if has_cmd systemctl && ! systemctl is-active --quiet docker 2>/dev/null; then
    if confirm "Docker daemon is stopped. Enable and start it now (sudo systemctl enable --now docker)?" "y"; then
      ensure_sudo || { err "sudo authentication failed"; return 1; }
      spinner_start "starting docker daemon…"
      if _sudo systemctl enable --now docker >>"$CKA_SETUP_LOG" 2>&1; then
        sleep 2
        spinner_stop "docker daemon started"
      else
        spinner_stop
        err "failed to start docker daemon — see $CKA_SETUP_LOG"
        return 1
      fi
    else
      err "Docker daemon is required — run: sudo systemctl enable --now docker"
      return 1
    fi
  fi

  if docker info >/dev/null 2>&1; then
    USE_SG_DOCKER=0
    return 0
  fi
  if has_cmd sg && sg docker -c "docker info" >/dev/null 2>&1; then
    USE_SG_DOCKER=1
    ok "docker reachable via 'docker' group"
    return 0
  fi

  # Grant user access to docker socket if needed (always ask first)
  local current_user
  current_user="${USER:-$(id -un)}"
  if [ "$(id -u)" != "0" ] && has_cmd usermod; then
    if confirm "Add user '${current_user}' to the 'docker' group so kind can access Docker without sudo?" "y"; then
      ensure_sudo || { err "sudo authentication failed"; return 1; }
      if _sudo usermod -aG docker "$current_user" >>"$CKA_SETUP_LOG" 2>&1; then
        DOCKER_GROUP_ADDED=1
        if has_cmd sg && sg docker -c "docker info" >/dev/null 2>&1; then
          USE_SG_DOCKER=1
          ok "added ${current_user} to 'docker' group (active via 'sg docker' for this setup run)"
          return 0
        fi
        err "added ${current_user} to 'docker' group, but the daemon is still unreachable — re-login to WSL (or run 'newgrp docker') and re-run ./setup.sh"
        return 1
      else
        err "failed to add ${current_user} to 'docker' group — run manually: sudo usermod -aG docker ${current_user}"
        return 1
      fi
    else
      err "Docker socket access is required — run: sudo usermod -aG docker ${current_user} && newgrp docker"
      return 1
    fi
  fi

  err "docker daemon is not reachable — verify Docker installation and re-run ./setup.sh"
  return 1
}

ensure_docker_registry_ready() {
  [ "$PROVIDER" = "kind" ] || return 0
  [ "$CHECK_ONLY" = "1" ] && return 0
  [ "$SKIP_CLUSTER" = "1" ] && return 0

  local ctr_count kind_img_ver
  kind_img_ver="${CKA_KIND_NODE_VER:-v1.31.2@sha256:18fbefc20a7113353c7b75b5c869d7145a6abd6269154825872dc59c1329912e}"
  ctr_count="$(_run_with_docker_group docker ps -a --filter "label=io.x-k8s.kind.cluster=cka" -q 2>/dev/null | wc -l | tr -d '[:space:]')"
  if [ "${ctr_count:-0}" -ge 3 ]; then return 0; fi
  if _run_with_docker_group docker image inspect "mirror.gcr.io/kindest/node:${kind_img_ver}" >/dev/null 2>&1 \
    || _run_with_docker_group docker image inspect "docker.io/kindest/node:${kind_img_ver}" >/dev/null 2>&1; then
    return 0
  fi

  if [ -f "$HOME/.docker/config.json" ] && grep -qE '"credsStore"[[:space:]]*:[[:space:]]*".*desktop\.exe"' "$HOME/.docker/config.json" 2>/dev/null; then
    if ! has_cmd docker-credential-desktop.exe; then
      warn "detected Windows Docker Desktop credsStore in ~/.docker/config.json (kind-up.sh uses an isolated config for public pulls)"
    fi
  fi

  local shell_http shell_https shell_noproxy daemon_proxy=""
  shell_http="${HTTP_PROXY:-${http_proxy:-}}"
  shell_https="${HTTPS_PROXY:-${https_proxy:-}}"
  shell_noproxy="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1,.svc,.cluster.local}}"
  if [ "$OS_NAME" != "macos" ] && [ "${WSL_DOCKER_DESKTOP:-0}" != "1" ] && has_cmd systemctl \
    && [ -n "${shell_http}${shell_https}" ]; then
    daemon_proxy="$(_run_with_docker_group docker info --format '{{.HTTPProxy}}{{.HTTPSProxy}}' 2>/dev/null || true)"
    if [ -z "$daemon_proxy" ]; then
      if confirm "Proxy env vars are set in your shell, but Docker daemon has no proxy configured. Configure /etc/systemd/system/docker.service.d/http-proxy.conf and restart Docker?" "y"; then
        ensure_sudo || return 1
        _sudo mkdir -p /etc/systemd/system/docker.service.d
        printf '[Service]\n' | _sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null
        if [ -n "$shell_http" ]; then
          printf 'Environment="HTTP_PROXY=%s"\n' "$shell_http" | _sudo tee -a /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null
        fi
        if [ -n "$shell_https" ]; then
          printf 'Environment="HTTPS_PROXY=%s"\n' "$shell_https" | _sudo tee -a /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null
        fi
        printf 'Environment="NO_PROXY=%s"\n' "$shell_noproxy" | _sudo tee -a /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null
        spinner_start "restarting docker with proxy configuration…"
        if _sudo systemctl daemon-reload >>"$CKA_SETUP_LOG" 2>&1 && _sudo systemctl restart docker >>"$CKA_SETUP_LOG" 2>&1; then
          sleep 2
          spinner_stop "docker restarted with proxy configuration"
        else
          spinner_stop
          warn "failed to restart docker after proxy update — see $CKA_SETUP_LOG"
        fi
      fi
    fi
  fi

  has_cmd curl || return 0
  local probe_rc=0
  curl -fsSI --max-time 8 "https://mirror.gcr.io/v2/" >/dev/null 2>&1 || probe_rc=$?
  [ "$probe_rc" -eq 0 ] && return 0

  if [ "$probe_rc" -eq 60 ] && [ "$OS_NAME" = "wsl" ] && has_cmd hwclock; then
    if confirm "TLS certificate validation failed (common after WSL sleep clock drift). Sync WSL clock now (sudo hwclock -s)?" "y"; then
      ensure_sudo || return 1
      _sudo hwclock -s >>"$CKA_SETUP_LOG" 2>&1 || true
    fi
  elif [ "$probe_rc" -eq 6 ] && [ "$OS_NAME" != "macos" ] && [ "${WSL_DOCKER_DESKTOP:-0}" != "1" ] && has_cmd systemctl && has_cmd jq; then
    if confirm "DNS resolution failed for container registries. Configure fallback DNS (1.1.1.1, 8.8.8.8) in /etc/docker/daemon.json and restart Docker?" "y"; then
      ensure_sudo || return 1
      local existing="{}" updated_json
      if _sudo test -s /etc/docker/daemon.json; then
        existing="$(_sudo cat /etc/docker/daemon.json 2>/dev/null || echo "{}")"
      fi
      updated_json="$(printf '%s' "$existing" | jq '. + {"dns": ["1.1.1.1", "8.8.8.8"]}' 2>/dev/null || echo '{"dns": ["1.1.1.1", "8.8.8.8"]}')"
      _sudo mkdir -p /etc/docker
      printf '%s\n' "$updated_json" | _sudo tee /etc/docker/daemon.json >/dev/null
      spinner_start "restarting docker with fallback DNS…"
      if _sudo systemctl restart docker >>"$CKA_SETUP_LOG" 2>&1; then
        sleep 2
        spinner_stop "docker restarted with fallback DNS"
      else
        spinner_stop
        warn "failed to restart docker after DNS update — see $CKA_SETUP_LOG"
      fi
    fi
  elif [ "$OS_NAME" = "wsl" ] && has_cmd ip && { [ "$probe_rc" -eq 28 ] || [ "$probe_rc" -eq 35 ] || [ "$probe_rc" -eq 56 ]; }; then
    local iface mtu
    iface="$(_detect_default_iface)"
    if [ -n "$iface" ]; then
      mtu="$(ip link show "$iface" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="mtu"){print $(i+1); exit}}')"
      if [ "${mtu:-1500}" -ge 1500 ]; then
        if confirm "Registry connection timed out (common WSL2 MTU issue on '${iface}' with MTU ${mtu}). Temporarily set MTU to 1350?" "y"; then
          ensure_sudo || return 1
          _sudo ip link set dev "$iface" mtu 1350 >>"$CKA_SETUP_LOG" 2>&1 || true
        fi
      fi
    fi
  fi
  return 0
}

_run_with_docker_group() {
  if [ "${USE_SG_DOCKER:-0}" != "1" ]; then
    "$@"
    return $?
  fi
  local cmd_str="" arg quoted path_q
  path_q="$(printf '%q' "$PATH")"
  for arg in "$@"; do
    quoted="$(printf '%q' "$arg")"
    cmd_str="${cmd_str:+${cmd_str} }${quoted}"
  done
  sg docker -c "export PATH=${path_q}; ${cmd_str}"
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
_cluster_readyz() {
  uv run python - <<'PY' >>"$CKA_SETUP_LOG" 2>&1
import asyncio, sys
from app import cluster
sys.exit(0 if asyncio.run(cluster.readyz()) else 1)
PY
}

run_cluster() {
  step "Provisioning the Kubernetes lab (${PROVIDER})"
  if [ "$SKIP_CLUSTER" = "1" ]; then
    if ! _cluster_readyz; then
      warn "--skip-cluster given but the API at ~/.cka-arena/kubeconfig is not ready"
    else
      step_done "cluster already ready — skipping provisioning"
      return 0
    fi
  elif state_has cluster_up; then
    if _cluster_readyz; then
      step_done "cluster already ready — skipping provisioning"
      return 0
    fi
    warn "state says cluster is up, but the API is not ready — reprovisioning"
    state_clear cluster_up
  fi

  local script
  if [ "$PROVIDER" = "kind" ]; then
    script="$SCRIPT_DIR/scripts/cluster/kind-up.sh"
  else
    script="$SCRIPT_DIR/scripts/cluster/up.sh"
  fi
  [ -x "$script" ] || die "missing $script"

  spinner_start "provisioning nodes (this takes a few minutes)…"
  if [ "$PROVIDER" = "kind" ]; then
    if _run_with_docker_group "$script" >>"$CKA_SETUP_LOG" 2>&1; then
      spinner_stop "nodes ready"
      state_set cluster_up "done"
      return 0
    fi
  else
    if CKA_BRIDGE_IFACE="${BRIDGE_IFACE}" "$script" >>"$CKA_SETUP_LOG" 2>&1; then
      spinner_stop "nodes ready"
      state_set cluster_up "done"
      return 0
    fi
  fi

  spinner_stop
  err "cluster provisioning failed — last lines of $CKA_SETUP_LOG:"
  tail -20 "$CKA_SETUP_LOG" >&2 || true
  if grep -qiE "failed to fetch anonymous token|i/o timeout|TLS handshake|x509|temporary failure in name resolution|server misbehaving" "$CKA_SETUP_LOG" 2>/dev/null; then
    echo >&2
    warn "Container registry network issue detected on WSL2/Linux:"
    warn "  1. Clock drift (TLS/x509):  sudo hwclock -s"
    warn "  2. MTU timeout/reset:       sudo ip link set dev eth0 mtu 1350"
    warn "  3. DNS lookup failure:      set [network] generateResolvConf=false in /etc/wsl.conf + nameserver 1.1.1.1 in /etc/resolv.conf"
    warn "  4. Stale Docker login/VPN:  docker logout && disconnect VPN (or set HTTP_PROXY/HTTPS_PROXY before ./setup.sh)"
    warn "  5. Custom mirror override:  CKA_KIND_IMAGE=<your-mirror>/kindest/node:v1.31.2 ./setup.sh"
  fi
  exit 1
}

# ---------------------------------------------------------------- wiring
run_wire() {
  step "Wiring access (kubeconfig + exam environment)"
  if [ "$PROVIDER" = "multipass" ] && [ -n "${BRIDGE_SUBNET:-}" ]; then
    printf '%s\n' "$BRIDGE_SUBNET" > "$CKA_DIR/bridge_prefix" 2>/dev/null || true
  fi

  spinner_start "wiring kubeconfig + node exam profile…"
  if [ "$PROVIDER" = "kind" ]; then
    if _run_with_docker_group uv run python -m app.setup_wire >>"$CKA_SETUP_LOG" 2>&1; then
      spinner_stop "kubeconfig contexts + node exam profile ready"
      state_set wire "done"
      return 0
    fi
  else
    if CKA_BRIDGE_IFACE="${BRIDGE_IFACE}" CKA_BRIDGE_PREFIX="${BRIDGE_SUBNET:-}" \
      uv run python -m app.setup_wire >>"$CKA_SETUP_LOG" 2>&1; then
      spinner_stop "SSH bridge + kubeconfig ready"
      state_set wire "done"
      return 0
    fi
  fi
  spinner_stop; err "wiring failed — see $CKA_SETUP_LOG"; exit 1
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
  step "Seeding the question bank & initializing database"
  if [ -f "$SCRIPT_DIR/data/cka_arena.db" ]; then
    spinner_start "syncing schema & publishing seeds (existing DB preserved)…"
  else
    spinner_start "restoring portable backup (fresh install) + publishing seeds…"
  fi
  if uv run python -m app.seed >>"$CKA_SETUP_LOG" 2>&1; then
    local count
    count="$(uv run python -c "from app import bank, db; db.init_db(); print(bank.count_published())" 2>/dev/null || echo '?')"
    spinner_stop "question bank ready (${count} published)"
    state_set seeds "done"
  else
    spinner_stop; err "seeding failed — see $CKA_SETUP_LOG"; exit 1
  fi
}

# ---------------------------------------------------------------- server
SERVER_URL="http://127.0.0.1:8765"

server_healthy() { curl -fsS --max-time 2 "$SERVER_URL/api/health" >/dev/null 2>&1; }

_server_has_active_session() {
  local raw
  raw="$(curl -fsS --max-time 2 "$SERVER_URL/api/sessions/active" 2>/dev/null || true)"
  [ -n "$raw" ] || return 1
  printf '%s' "$raw" | uv run python -c "import json, sys; data = json.load(sys.stdin); sys.exit(0 if data.get('active') else 1)" 2>/dev/null
}

_stop_running_server() {
  local pids="" pid_file="$CKA_DIR/server.pid" w=0
  if [ -f "$pid_file" ]; then
    pids="$(cat "$pid_file" 2>/dev/null || true)"
  fi
  if has_cmd lsof; then
    pids="${pids} $(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
  fi
  for pid in $pids; do
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  done
  while [ "$w" -lt 10 ]; do
    server_healthy || break
    sleep 0.5
    w=$((w + 1))
  done
  if server_healthy && has_cmd lsof; then
    for pid in $(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true); do
      kill -9 "$pid" 2>/dev/null || true
    done
    sleep 0.5
  fi
}

run_server() {
  step "Starting the platform"
  if server_healthy; then
    if [ "$FORCE_RESTART" != "1" ] && _server_has_active_session; then
      warn "active exam/practice session detected at $SERVER_URL — keeping running server (pass --restart to force)"
      return 0
    fi
    spinner_start "restarting running server to load latest code & config…"
    _stop_running_server
    spinner_stop "previous server stopped"
  fi
  spinner_start "starting server…"
  if [ "$PROVIDER" = "kind" ] && [ "${USE_SG_DOCKER:-0}" = "1" ]; then
    local uv_bin path_q uv_q
    uv_bin="$(command -v uv)"
    path_q="$(printf '%q' "$PATH")"
    uv_q="$(printf '%q' "$uv_bin")"
    nohup sg docker -c "export PATH=${path_q}; exec ${uv_q} run cka-arena" >>"$CKA_DIR/server.log" 2>&1 &
  elif [ "$PROVIDER" = "multipass" ] && [ -n "${BRIDGE_SUBNET:-}" ]; then
    CKA_BRIDGE_PREFIX="$BRIDGE_SUBNET" nohup uv run cka-arena >>"$CKA_DIR/server.log" 2>&1 &
  else
    nohup uv run cka-arena >>"$CKA_DIR/server.log" 2>&1 &
  fi
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
  local term_note="tab \"mac\" (zsh), isolated scratch dir"
  if [ "$PROVIDER" = "kind" ]; then
    provider_note="containers via kind (node shells open with docker exec)"
    if [ "$OS_NAME" = "wsl" ]; then term_note="host WSL shell (bash/zsh), isolated scratch dir"; fi
  fi
  hr 72
  printf '%s\n' "${C_GREEN}${C_BOLD} ✔ CKA Arena is ready${C_RESET}"
  echo
  printf ' %s Open:       %s%s%s\n' "▸" "$C_CYAN" "$SERVER_URL" "$C_RESET"
  printf ' %s Terminal:   real shell on this machine (%s)\n' "▸" "$term_note"
  printf ' %s Lab nodes:  %s\n' "▸" "$provider_note"
  if [ "$DOCKER_GROUP_ADDED" = "1" ]; then
    echo
    printf ' %s Note:       open a new WSL shell so your user inherits the '\''docker'\'' group for manual CLI calls\n' "▸"
  fi
  echo
  printf '%s\n' "${C_BOLD} Configure (all optional):${C_RESET}"
  printf ' %s AI generation — put a provider key in %sllm_config.json%s (or Settings in the UI)\n' "▸" "$C_DIM" "$C_RESET"
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
  if [ "$CHECK_ONLY" != "1" ]; then
    printf '%s\n' "$PROVIDER" > "$CKA_DIR/provider" 2>/dev/null || true
  fi
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

  if ! ensure_docker_ready; then
    echo
    err "setup stopped — resolve the Docker issue above and re-run ./setup.sh"
    exit 1
  fi
  if ! ensure_docker_registry_ready; then
    echo
    err "setup stopped — resolve the Docker registry network issue above and re-run ./setup.sh"
    exit 1
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
