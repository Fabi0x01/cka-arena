#!/usr/bin/env bash
# shellcheck disable=SC2034  # globals consumed by setup.sh via sourcing
# detect.sh — OS/distro/arch/env detection & PATH normalization (English only)

if [ -n "${_CKA_DETECT_SH:-}" ]; then return 0; fi
_CKA_DETECT_SH=1

has_cmd() { command -v "$1" >/dev/null 2>&1; }

_prepend_path_dir() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  case ":${PATH}:" in
    *":${dir}:"*) ;;
    *) PATH="${dir}:${PATH}" ;;
  esac
}

refresh_path() {
  _prepend_path_dir "/usr/local/bin"
  _prepend_path_dir "/opt/homebrew/bin"
  _prepend_path_dir "$HOME/.cargo/bin"
  _prepend_path_dir "$HOME/.local/bin"
  _prepend_path_dir "${CKA_BIN_DIR:-$HOME/.local/bin}"
  export PATH
  hash -r 2>/dev/null || true
}

detect_os() {
  OS_NAME="unknown"; DISTRO=""; OS_VERSION=""; ARCH="$(uname -m)"
  IS_WSL=0
  if [ -n "${WSL_DISTRO_NAME:-}" ] || [ -n "${WSL_INTEROP:-}" ] || grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    IS_WSL=1
  fi
  case "$(uname -s)" in
    Darwin)
      OS_NAME="macos"
      OS_VERSION="$(sw_vers -productVersion 2>/dev/null || echo '')"
      ;;
    Linux)
      if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        DISTRO="${ID:-linux}"
        OS_VERSION="${VERSION_ID:-}"
        case "$ID" in
          ubuntu) OS_NAME="ubuntu" ;;
          debian|linuxmint|pop) OS_NAME="debian" ;;
          fedora|rhel|centos|rocky|alma) OS_NAME="fedora" ;;
          arch|manjaro) OS_NAME="arch" ;;
          *) OS_NAME="linux" ;;
        esac
      else
        OS_NAME="linux"
      fi
      ;;
    *)
      OS_NAME="unknown"
      ;;
  esac
  if [ "$IS_WSL" = "1" ]; then OS_NAME="wsl"; fi
}

detect_pkg_manager() {
  PKG_MANAGER=""
  PKG_SUDO=0
  if [ "$OS_NAME" = "macos" ]; then
    if has_cmd brew || [ -x /opt/homebrew/bin/brew ] || [ -x /usr/local/bin/brew ]; then
      refresh_path
      PKG_MANAGER="brew"
    fi
  elif [ "$OS_NAME" = "wsl" ] || [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "debian" ]; then
    if has_cmd apt-get; then PKG_SUDO=1; PKG_MANAGER="apt"; fi
  elif [ "$OS_NAME" = "fedora" ]; then
    if has_cmd dnf; then PKG_SUDO=1; PKG_MANAGER="dnf"; fi
  elif [ "$OS_NAME" = "arch" ]; then
    if has_cmd pacman; then PKG_SUDO=1; PKG_MANAGER="pacman"; fi
  elif has_cmd snap; then
    PKG_SUDO=1; PKG_MANAGER="snap"
  fi
}

# Desired provider: multipass (macOS/Linux) or kind (WSL/Linux+docker).
# Honours CKA_PROVIDER and ~/.cka-arena/provider, then environment.
detect_provider() {
  if [ -n "${CKA_PROVIDER:-}" ]; then
    PROVIDER="$CKA_PROVIDER"
  elif [ -r "${CKA_DIR:-$HOME/.cka-arena}/provider" ]; then
    PROVIDER="$(tr -d '[:space:]' < "${CKA_DIR:-$HOME/.cka-arena}/provider")"
  elif [ "$OS_NAME" = "wsl" ]; then
    PROVIDER="kind"
  elif [ "$OS_NAME" = "macos" ]; then
    PROVIDER="multipass"
  else
    # Linux: prefer Multipass when installed, else kind when Docker exists
    if has_cmd multipass; then PROVIDER="multipass"; elif has_cmd docker; then PROVIDER="kind"; else PROVIDER="multipass"; fi
  fi
}

detect_memory_gb() {
  local bytes kb
  if [ "$OS_NAME" = "macos" ]; then
    bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    MEM_GB=$(( ${bytes:-0} / 1073741824 ))
  else
    kb="$(awk '/MemTotal/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"
    MEM_GB=$(( ${kb:-0} / 1048576 ))
  fi
}

detect_disk_free_gb() {
  local val
  val="$(df -Pk "${PWD}" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')"
  DISK_FREE_GB="${val:-0}"
}

detect_bridge_subnet() {
  BRIDGE_SUBNET=""
  local gw=""
  if [ "$OS_NAME" = "macos" ]; then
    gw=$(netstat -rn -f inet 2>/dev/null | awk '$1=="default" {print $2; exit}')
  else
    gw=$(ip route 2>/dev/null | awk '$1=="default" {print $3; exit}')
  fi
  if [ -n "$gw" ]; then
    BRIDGE_SUBNET="$(printf '%s' "$gw" | awk -F. '{printf "%s.%s.%s.", $1, $2, $3}')"
  fi
}

# systemd + cgroup v2 are required inside WSL for native Docker + kind nodes
# (or Docker Desktop WSL integration may supply the Docker daemon).
detect_wsl_capabilities() {
  WSL_SYSTEMD=0
  WSL_CGROUP_V2=0
  WSL_DOCKER_DESKTOP=0
  [ "$OS_NAME" = "wsl" ] || return 0
  local pid1 fs_type docker_os
  pid1="$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]')"
  if [ "$pid1" = "systemd" ]; then WSL_SYSTEMD=1; fi
  fs_type="$(stat -fc %T /sys/fs/cgroup 2>/dev/null || true)"
  if [ "$fs_type" = "cgroup2fs" ] || [ -d /sys/fs/cgroup/unified ]; then
    WSL_CGROUP_V2=1
  fi
  if [ -d /mnt/wsl/docker-desktop ]; then
    WSL_DOCKER_DESKTOP=1
  elif has_cmd docker; then
    docker_os="$(docker info --format '{{.OperatingSystem}}' 2>/dev/null || true)"
    case "$docker_os" in
      *[Dd]ocker\ [Dd]esktop*) WSL_DOCKER_DESKTOP=1 ;;
    esac
  fi
}
