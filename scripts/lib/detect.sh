#!/usr/bin/env bash
# shellcheck disable=SC2034  # globals consumed by setup.sh via sourcing
# detect.sh — OS/distro/arch/env detection (English only)

if [ -n "${_CKA_DETECT_SH:-}" ]; then return 0; fi
_CKA_DETECT_SH=1

has_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
  OS_NAME="unknown"; DISTRO=""; OS_VERSION=""; ARCH="$(uname -m)"
  IS_WSL=0
  if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
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
  if [ "$OS_NAME" = "macos" ] && has_cmd brew; then
    PKG_MANAGER="brew"
  elif [ "$OS_NAME" = "wsl" ] || [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "debian" ]; then
    if has_cmd apt-get; then PKG_SUDO=1; PKG_MANAGER="apt"; fi
  elif [ "$OS_NAME" = "fedora" ]; then
    has_cmd dnf && PKG_MANAGER="dnf"
  elif [ "$OS_NAME" = "arch" ]; then
    has_cmd pacman && PKG_MANAGER="pacman"
  elif has_cmd snap; then
    PKG_MANAGER="snap"
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
  if [ "$OS_NAME" = "macos" ]; then
    MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  else
    MEM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1048576 ))
  fi
}

detect_disk_free_gb() {
  DISK_FREE_GB=$(df -Pk "${PWD}" | awk 'NR==2 {printf "%d", $4/1048576}')
}

detect_bridge_subnet() {
  BRIDGE_SUBNET=""
  local gw
  if [ "$OS_NAME" = "macos" ]; then
    gw=$(netstat -rn -f inet 2>/dev/null | awk '$1=="default" {print $2; exit}')
  else
    gw=$(ip route 2>/dev/null | awk '$1=="default" {print $3; exit}')
  fi
  if [ -n "$gw" ]; then
    BRIDGE_SUBNET="$(printf '%s' "$gw" | awk -F. '{printf "%s.%s.%s.", $1, $2, $3}')"
  fi
}

# systemd + cgroup v2 are required inside WSL for kind nodes
detect_wsl_capabilities() {
  WSL_SYSTEMD=0; WSL_CGROUP_V2=0
  if [ "$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]')" = "systemd" ]; then WSL_SYSTEMD=1; fi
  if [ "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" = "cgroup2fs" ]; then WSL_CGROUP_V2=1; fi
}
