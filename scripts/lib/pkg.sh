#!/usr/bin/env bash
# shellcheck disable=SC2034
# pkg.sh — prerequisite installation per package manager (English only).
# Every install is invoked by setup.sh ONLY after an explicit user confirmation.

if [ -n "${_CKA_PKG_SH:-}" ]; then return 0; fi
_CKA_PKG_SH=1

CKA_BIN_DIR="${CKA_BIN_DIR:-$HOME/.local/bin}"
_APT_UPDATED=0

_sudo() {
  if [ "$(id -u)" = "0" ]; then "$@"; else sudo "$@"; fi
}

_apt_update_once() {
  [ "$_APT_UPDATED" = "1" ] && return 0
  _sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 || return 1
  _APT_UPDATED=1
}

_apt_install() {
  _apt_update_once || return 1
  _sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1
}

_brew()   { has_cmd brew && brew "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }
_dnf()    { _sudo dnf install -y "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }
_pacman() { _sudo pacman -S --noconfirm "$@" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; }

# Prompt for sudo credentials BEFORE starting any spinner so the password prompt stays clean.
ensure_sudo() {
  if [ "$(id -u)" = "0" ]; then return 0; fi
  if sudo -n true 2>/dev/null; then return 0; fi
  info "Administrator (sudo) password is required for system package installation"
  sudo -v
}

installer_needs_sudo() {
  case "$1" in
    install_homebrew|install_multipass|install_docker)
      return 0 ;;
    install_curl|install_git|install_jq|install_vim|install_openssh)
      case "${PKG_MANAGER:-}" in
        apt|dnf|pacman|snap) return 0 ;;
        *) return 1 ;;
      esac ;;
    install_kubectl|install_helm)
      case "${OS_NAME:-}" in
        fedora|arch) return 0 ;;
        *) return 1 ;;
      esac ;;
    *)
      return 1 ;;
  esac
}

_norm_arch() {
  case "$ARCH" in
    arm64|aarch64) echo "arm64" ;;
    x86_64|amd64)  echo "amd64" ;;
    *) return 1 ;;
  esac
}

_norm_os() {
  if [ "$OS_NAME" = "macos" ]; then echo "darwin"; else echo "linux"; fi
}

# download <url> <dest> — curl or wget, atomic
_download() {
  local url="$1" dest="$2" tmp="${2}.part"
  if has_cmd curl; then
    curl -fsSL "$url" -o "$tmp" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 || { rm -f "$tmp"; return 1; }
  elif has_cmd wget; then
    wget -qO "$tmp" "$url" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 || { rm -f "$tmp"; return 1; }
  else
    return 1
  fi
  mv "$tmp" "$dest"
}

install_homebrew() {
  [ "$OS_NAME" = "macos" ] || return 1
  has_cmd curl || return 1
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 || return 1
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  refresh_path
  detect_pkg_manager
  has_cmd brew
}

install_curl() {
  case "${PKG_MANAGER:-}" in
    brew)   _brew install curl ;;
    apt)    _apt_install curl ca-certificates ;;
    dnf)    _dnf curl ca-certificates ;;
    pacman) _pacman curl ca-certificates ;;
    *)      return 1 ;;
  esac || return 1
  refresh_path
}

install_git() {
  case "${PKG_MANAGER:-}" in
    brew)   _brew install git ;;
    apt)    _apt_install git ;;
    dnf)    _dnf git ;;
    pacman) _pacman git ;;
    *)      return 1 ;;
  esac || return 1
  refresh_path
}

install_vim() {
  case "${PKG_MANAGER:-}" in
    brew)   _brew install vim ;;
    apt)    _apt_install vim ;;
    dnf)    _dnf vim-enhanced ;;
    pacman) _pacman vim ;;
    *)      return 1 ;;
  esac || return 1
  refresh_path
}

install_uv() {
  if ! has_cmd curl && ! has_cmd wget; then return 1; fi
  local script rc
  script="$(mktemp)"
  _download "https://astral.sh/uv/install.sh" "$script" || { rm -f "$script"; return 1; }
  sh "$script" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1
  rc=$?
  rm -f "$script"
  [ "$rc" -eq 0 ] || return "$rc"
  refresh_path
}

install_kubectl() {
  local ver="v1.31.4" arch os
  arch="$(_norm_arch)" || return 1
  os="$(_norm_os)"
  case "$OS_NAME" in
    macos)
      if has_cmd brew; then
        _brew install kubectl || return 1
        refresh_path
        return 0
      fi
      ;;
    fedora)
      if has_cmd dnf; then
        _dnf kubernetes-client || return 1
        refresh_path
        return 0
      fi
      ;;
    arch)
      if has_cmd pacman; then
        _pacman kubectl || return 1
        refresh_path
        return 0
      fi
      ;;
  esac
  mkdir -p "$CKA_BIN_DIR"
  _download "https://dl.k8s.io/release/${ver}/bin/${os}/${arch}/kubectl" "$CKA_BIN_DIR/kubectl" || return 1
  chmod +x "$CKA_BIN_DIR/kubectl"
  refresh_path
}

install_helm() {
  local ver="v3.17.3" arch os tmp_dir tarball
  arch="$(_norm_arch)" || return 1
  os="$(_norm_os)"
  if [ "$OS_NAME" = "macos" ] && has_cmd brew; then
    _brew install helm || return 1
    refresh_path
    return 0
  fi
  if [ "$OS_NAME" = "fedora" ] && has_cmd dnf; then
    _dnf helm || return 1
    refresh_path
    return 0
  fi
  if [ "$OS_NAME" = "arch" ] && has_cmd pacman; then
    _pacman helm || return 1
    refresh_path
    return 0
  fi
  mkdir -p "$CKA_BIN_DIR"
  tmp_dir="$(mktemp -d)"
  tarball="${tmp_dir}/helm.tar.gz"
  if ! _download "https://get.helm.sh/helm-${ver}-${os}-${arch}.tar.gz" "$tarball"; then
    rm -rf "$tmp_dir"
    return 1
  fi
  if ! tar -xzf "$tarball" -C "$tmp_dir" >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1; then
    rm -rf "$tmp_dir"
    return 1
  fi
  if [ ! -f "${tmp_dir}/${os}-${arch}/helm" ]; then
    rm -rf "$tmp_dir"
    return 1
  fi
  mv "${tmp_dir}/${os}-${arch}/helm" "$CKA_BIN_DIR/helm"
  chmod +x "$CKA_BIN_DIR/helm"
  rm -rf "$tmp_dir"
  refresh_path
}

install_kind() {
  local ver="v0.25.0" os arch dest
  arch="$(_norm_arch)" || return 1
  os="$(_norm_os)"
  mkdir -p "$CKA_BIN_DIR"
  dest="$CKA_BIN_DIR/kind"
  _download "https://kind.sigs.k8s.io/dl/${ver}/kind-${os}-${arch}" "$dest" || return 1
  chmod +x "$dest"
  refresh_path
}

install_multipass() {
  case "$OS_NAME" in
    macos)
      if has_cmd brew; then
        _brew install --cask multipass || return 1
        refresh_path
        return 0
      fi ;;
    ubuntu|debian|wsl)
      if has_cmd snap; then
        _sudo snap install multipass >>"${CKA_SETUP_LOG:-/dev/null}" 2>&1 || return 1
        refresh_path
        return 0
      fi ;;
  esac
  return 1
}

install_docker() {
  # Native Docker Engine inside WSL2/Linux, or Docker Desktop cask on macOS
  case "$OS_NAME" in
    macos)
      if has_cmd brew; then
        _brew install --cask docker || return 1
        refresh_path
        return 0
      fi ;;
    wsl|ubuntu|debian)
      _apt_install docker.io || return 1
      refresh_path
      return 0 ;;
    fedora)
      _dnf docker || return 1
      refresh_path
      return 0 ;;
    arch)
      _pacman docker || return 1
      refresh_path
      return 0 ;;
  esac
  return 1
}

install_jq() {
  case "${PKG_MANAGER:-}" in
    brew)   _brew install jq ;;
    apt)    _apt_install jq ;;
    dnf)    _dnf jq ;;
    pacman) _pacman jq ;;
    *)      return 1 ;;
  esac || return 1
  refresh_path
}

install_openssh() {
  case "${PKG_MANAGER:-}" in
    brew)   _brew install openssh ;;
    apt)    _apt_install openssh-client ;;
    dnf)    _dnf openssh-clients ;;
    pacman) _pacman openssh ;;
    *)      return 1 ;;
  esac || return 1
  refresh_path
}

install_description() {
  case "$1" in
    homebrew)  echo "macOS Homebrew package manager" ;;
    curl)      echo "via ${PKG_MANAGER:-package manager} (curl)" ;;
    git)       echo "via ${PKG_MANAGER:-package manager} (git)" ;;
    uv)        echo "official installer (astral.sh) -> ~/.local/bin/uv" ;;
    kubectl)
      if [ "$OS_NAME" = "macos" ] && has_cmd brew; then echo "via brew install kubectl"
      else echo "official Kubernetes v1.31.4 binary -> ${CKA_BIN_DIR}/kubectl"; fi ;;
    helm)
      if [ "$OS_NAME" = "macos" ] && has_cmd brew; then echo "via brew install helm"
      else echo "official Helm v3.17.3 binary -> ${CKA_BIN_DIR}/helm"; fi ;;
    jq)        echo "via ${PKG_MANAGER:-package manager} (jq)" ;;
    vim)       echo "via ${PKG_MANAGER:-package manager} (vim)" ;;
    multipass)
      if [ "$OS_NAME" = "macos" ]; then echo "via brew install --cask multipass"
      else echo "via sudo snap install multipass"; fi ;;
    ssh)       echo "via ${PKG_MANAGER:-package manager} (openssh)" ;;
    docker)
      if [ "$OS_NAME" = "macos" ]; then echo "via brew install --cask docker"
      else echo "via ${PKG_MANAGER:-apt-get} (docker.io Engine)"; fi ;;
    kind)      echo "official kind v0.25.0 binary -> ${CKA_BIN_DIR}/kind" ;;
    *)         echo "via ${PKG_MANAGER:-package manager}" ;;
  esac
}

# package_hint <tool> — what the user can run manually if they decline
package_hint() {
  case "$1" in
    homebrew)  echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' ;;
    curl)      echo "brew install curl  ·  sudo apt-get install curl" ;;
    git)       echo "brew install git  ·  sudo apt-get install git" ;;
    uv)        echo "curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
    kubectl)   echo "brew install kubectl  ·  https://dl.k8s.io/release/v1.31.4" ;;
    helm)      echo "brew install helm  ·  https://helm.sh/docs/intro/install/" ;;
    jq)        echo "brew install jq  ·  sudo apt-get install jq" ;;
    vim)       echo "brew install vim  ·  sudo apt-get install vim" ;;
    multipass) echo "brew install --cask multipass  ·  sudo snap install multipass" ;;
    ssh)       echo "brew install openssh  ·  sudo apt-get install openssh-client" ;;
    docker)    echo "brew install --cask docker  ·  sudo apt-get install docker.io && sudo systemctl enable --now docker" ;;
    kind)      echo "https://kind.sigs.k8s.io/docs/user/quick-start/#installation" ;;
    *)         echo "install $1 with your package manager" ;;
  esac
}
