#!/usr/bin/env bash
# state.sh — idempotency markers for setup steps (English only)

if [ -n "${_CKA_STATE_SH:-}" ]; then return 0; fi
_CKA_STATE_SH=1

CKA_STATE_FILE="${CKA_STATE_FILE:-$HOME/.cka-arena/setup.state}"

state_init() { mkdir -p "$(dirname "$CKA_STATE_FILE")"; touch "$CKA_STATE_FILE"; }

state_get() { grep -E "^$1=" "$CKA_STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2-; }

state_set() {
  state_init
  local key="$1" value="${2:-done}"
  grep -vE "^${key}=" "$CKA_STATE_FILE" > "${CKA_STATE_FILE}.tmp" 2>/dev/null || true
  printf '%s=%s\n' "$key" "$value" >> "${CKA_STATE_FILE}.tmp"
  mv "${CKA_STATE_FILE}.tmp" "$CKA_STATE_FILE"
}

state_has() { [ "$(state_get "$1")" = "done" ]; }

state_clear() {
  local key="$1"
  [ -f "$CKA_STATE_FILE" ] || return 0
  grep -vE "^${key}=" "$CKA_STATE_FILE" > "${CKA_STATE_FILE}.tmp" || true
  mv "${CKA_STATE_FILE}.tmp" "$CKA_STATE_FILE"
}
