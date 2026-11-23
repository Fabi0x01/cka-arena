#!/usr/bin/env bash
# pkg.sh — prerequisite installation per package manager (English only).
# Every install is invoked by setup.sh only after an explicit user confirmation.

if [ -n "${_CKA_PKG_SH:-}" ]; then return 0; fi
_CKA_PKG_SH=1

CKA_BIN_DIR="${CKA_BIN_DIR:-$HOME/.local/bin}"

_sudo() {
  if [ "$(id -u)" = "0" ]; then "$@"; else sudo "$@"; fi
}

_brew()  { has_cmd brew && brew "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }
_apt()   { _sudo apt-get "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }
_dnf()   { _sudo dnf "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }
_pacman(){ _sudo pacman -S --noconfirm "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }

# download <url> <dest> — curl or wget, atomic
_download() {
  local url="$1" dest="$2" tmp="${2}.part"
  if has_cmd curl; then
    curl -fsSL "$url" -o "$tmp" || return 1
  elif has_cmd wget; then
    wget -qO "$tmp" "$url" || return 1
  else
    return 1
  fi
  mv "$tmp" "$dest"
}

install_kubectl() {
  local ver="v1.31.4" arch
  case "$ARCH" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64)  arch="amd64" ;;
    *) return 1 ;;
  esac
  case "$OS_NAME" in
    macos)
      has_cmd brew && { _brew install kubectl; return $?; } ;;
    ubuntu|debian|wsl)
      if has_cmd snap; then _sudo snap install kubectl --classic >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 && return 0; fi ;;
    fedora) has_cmd dnf && { _sudo dnf install -y kubernetes-client >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 && return 0; } ;;
    arch) has_cmd pacman && { _pacman kubectl && return 0; } ;;
  esac
  mkdir -p "$CKA_BIN_DIR"
  _download "https://dl.k8s.io/release/${ver}/bin/linux/${arch}/kubectl" "$CKA_BIN_DIR/kubectl" \
    || _download "https://dl.k8s.io/release/${ver}/bin/darwin/${arch}/kubectl" "$CKA_BIN_DIR/kubectl" \
    || return 1
  chmod +x "$CKA_BIN_DIR/kubectl"
}

install_kind() {
  local ver="v0.25.0" os arch dest
  case "$ARCH" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64)  arch="amd64" ;;
    *) return 1 ;;
  esac
  os="linux"; [ "$OS_NAME" = "macos" ] && os="darwin"
  mkdir -p "$CKA_BIN_DIR"
  dest="$CKA_BIN_DIR/kind"
  _download "https://kind.sigs.k8s.io/dl/${ver}/kind-${os}-${arch}" "$dest" || return 1
  chmod +x "$dest"
}

install_uv() {
  has_cmd curl || return 1
  curl -LsSf https://astral.sh/uv/install.sh | sh >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1
}

install_multipass() {
  case "$OS_NAME" in
    macos)
      has_cmd brew && { _brew install --cask multipass; return $?; } ;;
    ubuntu|debian|wsl)
      has_cmd snap && { _sudo snap install multipass >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 && return 0; } ;;
  esac
  return 1
}

install_docker() {
  # Native Docker Engine inside the distro (no Docker Desktop dependency)
  case "$OS_NAME" in
    wsl|ubuntu|debian)
      _apt update && _apt install -y docker.io && return 0 ;;
    fedora) _sudo dnf install -y docker && _sudo systemctl enable --now docker && return 0 ;;
    arch) _pacman docker && _sudo systemctl enable --now docker && return 0 ;;
  esac
  return 1
}

install_jq() {
  case "$PKG_MANAGER" in
    brew) _brew install jq ;;
    apt)  _apt install -y jq ;;
    dnf)  _sudo dnf install -y jq ;;
    pacman) _pacman jq ;;
    *) return 1 ;;
  esac
}

install_openssh() {
  case "$PKG_MANAGER" in
    brew) _brew install openssh ;;
    apt)  _apt install -y openssh-client ;;
    dnf)  _sudo dnf install -y openssh-clients ;;
    pacman) _pacman openssh ;;
    *) return 1 ;;
  esac
}

# package_hint <tool> — what the user can run manually if they decline
package_hint() {
  case "$1" in
    multipass) echo "brew install --cask multipass  ·  sudo snap install multipass" ;;
    kubectl)   echo "brew install kubectl  ·  sudo snap install kubectl --classic  ·  https://dl.k8s.io" ;;
    kind)      echo "https://kind.sigs.k8s.io/docs/user/quick-start/#installation" ;;
    docker)    echo "sudo apt-get install docker.io && sudo systemctl enable --now docker" ;;
    uv)        echo "curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
    jq)        echo "brew install jq  ·  sudo apt-get install jq" ;;
    ssh)       echo "brew install openssh  ·  sudo apt-get install openssh-client" ;;
    *)         echo "install $1 with your package manager" ;;
  esac
}
