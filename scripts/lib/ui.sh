#!/usr/bin/env bash
# ui.sh — colors, logging, spinner, progress, confirm (English output only)
# Sourced by setup.sh. Safe to source multiple times.

if [ -n "${_CKA_UI_SH:-}" ]; then return 0; fi
_CKA_UI_SH=1

# ---------------------------------------------------------------- colors
_cka_colors() {
  if [ -n "${NO_COLOR:-}" ] || [ "${TERM:-dumb}" = "dumb" ] || [ ! -t 1 ]; then
    C_RESET="" C_BOLD="" C_DIM="" C_RED="" C_GREEN="" C_YELLOW="" C_BLUE="" C_CYAN=""
  else
    C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_DIM=$'\033[2m'
    C_RED=$'\033[1;31m' C_GREEN=$'\033[1;32m' C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[1;34m' C_CYAN=$'\033[1;36m'
  fi
}
_cka_colors

UI_STEP_TOTAL="${UI_STEP_TOTAL:-9}"
UI_STEP_CURRENT=0

log_line() { printf '%s\n' "$*" | tee -a "${CKA_SETUP_LOG:-/dev/null}" >/dev/null; }

info()  { printf '%s\n' "${C_BLUE}i${C_RESET} $*"; log_line "info: $*"; }
ok()    { printf '%s\n' "${C_GREEN}✔${C_RESET} $*"; log_line "ok: $*"; }
warn()  { printf '%s\n' "${C_YELLOW}!${C_RESET} $*"; log_line "warn: $*"; }
err()   { printf '%s\n' "${C_RED}✖${C_RESET} $*" >&2; log_line "err: $*"; }
die()   { err "$*"; exit 1; }

hr() {
  local cols="${1:-72}"
  printf '%s\n' "${C_DIM}$(printf '─%.0s' $(seq 1 "$cols"))${C_RESET}"
}

step() {
  UI_STEP_CURRENT=$((UI_STEP_CURRENT + 1))
  printf '\n%s\n' "${C_BOLD}[${UI_STEP_CURRENT}/${UI_STEP_TOTAL}] $*${C_RESET}"
  log_line "step ${UI_STEP_CURRENT}: $*"
}

step_done() { printf '%s\n' "${C_GREEN}  done${C_RESET}${C_DIM} · $*${C_RESET}"; log_line "done: $*"; }

# ---------------------------------------------------------------- spinner
_CKA_SPINNER_PID=""
_CKA_SPINNER_MSG_FILE="${TMPDIR:-/tmp}/cka-spinner-$$.msg"

spinner_start() {
  local msg="$*"
  printf '%s' "$msg" > "$_CKA_SPINNER_MSG_FILE"
  if [ ! -t 2 ]; then return 0; fi
  (
    local frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0 frame
    while :; do
      frame="${frames:$((i % ${#frames})):1}"
      printf '\r%s%s%s %s\033[K' "$C_CYAN" "$frame" "$C_RESET" "$(cat "$_CKA_SPINNER_MSG_FILE" 2>/dev/null)"
      i=$((i + 1))
      sleep 0.08
    done
  ) &
  _CKA_SPINNER_PID=$!
  disown "$_CKA_SPINNER_PID" 2>/dev/null || true
}

spinner_set() { printf '%s' "$*" > "$_CKA_SPINNER_MSG_FILE"; }

spinner_stop() {
  local msg="${1:-}"
  if [ -n "$_CKA_SPINNER_PID" ]; then
    kill "$_CKA_SPINNER_PID" 2>/dev/null || true
    wait "$_CKA_SPINNER_PID" 2>/dev/null || true
    _CKA_SPINNER_PID=""
  fi
  rm -f "$_CKA_SPINNER_MSG_FILE"
  if [ -t 2 ]; then printf '\r\033[K'; fi
  if [ -n "$msg" ]; then ok "$msg"; fi
}

# ---------------------------------------------------------------- progress bar
# bar <done> <total> <label>
bar() {
  local done="$1" total="$2" label="${3:-}" width=24 filled empty pct
  [ "$total" -le 0 ] && total=1
  filled=$((done * width / total))
  empty=$((width - filled))
  pct=$((done * 100 / total))
  printf '  %-28s %s%s%s%s %3d%%\n' "$label" \
    "$C_GREEN" "$(printf '█%.0s' $(seq 1 "$filled" 2>/dev/null))" \
    "$C_DIM" "$(printf '─%.0s' $(seq 1 "$empty" 2>/dev/null))" "$pct"
}

# ---------------------------------------------------------------- confirm
# confirm "question" [default] -> 0 yes / 1 no
confirm() {
  local question="$1" default="${2:-n}" answer
  if [ "${CKA_ASSUME_YES:-0}" = "1" ]; then return 0; fi
  if [ ! -t 0 ]; then return 1; fi
  printf '%s%s%s %s[%s]%s ' "$C_YELLOW" "?" "$C_RESET" "$question" \
    "$([ "$default" = "y" ] && echo "Y/n" || echo "y/N")" ""
  read -r answer || answer=""
  answer="${answer:-$default}"
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------- cleanup
ui_cleanup() {
  spinner_stop
  rm -f "$_CKA_SPINNER_MSG_FILE"
  return 0
}
