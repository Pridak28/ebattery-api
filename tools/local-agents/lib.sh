#!/usr/bin/env bash
# tools/local-agents/lib.sh — shared helpers for the dual-agent system.
# Sourced by every other script. Keep deterministic + safe.

set -euo pipefail

# --- absolute paths anchored on the repo root ---
LIB_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIB_SH_DIR/../.." && pwd)"

CODEX_WORKTREE="/Users/seversilaghi/Documents/battery-analytics-pro-codex"
CLAUDE_WORKTREE="/Users/seversilaghi/Documents/battery-analytics-pro-claude"

# --- board paths inside the canonical repo ---
BOARD_DIR="$REPO_ROOT/reports/local-agents"
QUEUE_DIR="$BOARD_DIR/queue"
TASKS_FILE="$QUEUE_DIR/tasks.json"
CLAIMS_DIR="$QUEUE_DIR/claims"
RESULTS_DIR="$QUEUE_DIR/results"
REPORTS_DIR="$BOARD_DIR/reports"
DECISIONS_DIR="$REPORTS_DIR/master-decisions"
RUNS_DIR="$BOARD_DIR/runs"

# --- defaults the loop honors ---
: "${LOCAL_AGENT_DURATION_SECONDS:=600}"   # 10 min default
: "${LOCAL_AGENT_MAX_PROTOTYPES:=3}"
: "${LOCAL_AGENT_PUSH_BRANCHES:=0}"        # never push by default

# --- pretty printers (portable: macOS bash 3.2 doesn't support printf %(...)T) ---
_ts() { date +"%H:%M:%S"; }
log()  { printf "[%s] %s\n" "$(_ts)" "$*" >&2; }
warn() { printf "[%s] ⚠ %s\n" "$(_ts)" "$*" >&2; }
err()  { printf "[%s] ✗ %s\n" "$(_ts)" "$*" >&2; }
ok()   { printf "[%s] ✓ %s\n" "$(_ts)" "$*" >&2; }

now_utc() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
now_id()  { date -u +"%Y%m%dT%H%M%SZ"; }

# --- jq with a friendly error if missing ---
ensure_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    err "jq not installed. Install with 'brew install jq' and re-run."
    exit 1
  fi
}

# --- safety guard: must be run from a real git repo at REPO_ROOT ---
require_root_git() {
  if [ ! -d "$REPO_ROOT/.git" ]; then
    err "Not a git repo at $REPO_ROOT/.git — run setup first."
    exit 1
  fi
  local actual; actual="$(cd "$REPO_ROOT" && git rev-parse --show-toplevel)"
  if [ "$actual" != "$REPO_ROOT" ]; then
    err "Repo root mismatch (expected $REPO_ROOT, got $actual)."
    exit 1
  fi
}

# --- safety guard: clean main only ---
require_clean_main() {
  require_root_git
  local branch; branch="$(cd "$REPO_ROOT" && git symbolic-ref --short HEAD 2>/dev/null || echo '')"
  if [ "$branch" != "main" ]; then
    err "Refusing to start: current branch is '$branch', expected 'main'."
    err "Switch to main: cd $REPO_ROOT && git checkout main"
    exit 1
  fi
  if [ -n "$(cd "$REPO_ROOT" && git status --porcelain)" ]; then
    err "Refusing to start: $REPO_ROOT working tree is dirty."
    err "Commit or stash first."
    exit 1
  fi
  ok "Repo is on clean main."
}

# --- agent → worktree resolver ---
agent_worktree() {
  case "$1" in
    codex)  echo "$CODEX_WORKTREE" ;;
    claude) echo "$CLAUDE_WORKTREE" ;;
    *) err "Unknown agent '$1' (expected: codex|claude)"; exit 1 ;;
  esac
}

# --- a sanitized sub-id for filenames (lower / dash) ---
sanitize() { echo "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/--*/-/g; s/^-//; s/-$//'; }

# ============================================================================
# Token-exhaustion / rate-limit failover
# ============================================================================
# When one agent's CLI signals it's out of tokens, write a marker file so the
# loop knows to skip it AND so the other agent picks up its task. The marker
# carries a reset timestamp; once expired the agent is eligible again.

EXHAUSTION_DIR="$BOARD_DIR/queue/exhausted"

# Default cool-down windows (seconds) when CLI doesn't tell us:
#   Claude: ~5h between rate-limit resets in practice
#   Codex:  ~1h
DEFAULT_CLAUDE_RESET=18000
DEFAULT_CODEX_RESET=3600

ensure_exhaustion_dir() { mkdir -p "$EXHAUSTION_DIR"; }

# is_exhausted <agent> → 0 if currently exhausted (skip), 1 if eligible
is_exhausted() {
  ensure_exhaustion_dir
  local marker="$EXHAUSTION_DIR/$1.json"
  [ -f "$marker" ] || return 1
  ensure_jq
  local exh_at reset
  exh_at="$(jq -r '.exhausted_at_utc' "$marker" 2>/dev/null)"
  reset="$(jq -r '.reset_after_seconds' "$marker" 2>/dev/null)"
  [ -z "$exh_at" ] || [ -z "$reset" ] && return 1
  local then_s now_s
  then_s="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$exh_at" +%s 2>/dev/null || echo 0)"
  now_s="$(date -u +%s)"
  if [ $((now_s - then_s)) -lt "$reset" ]; then
    return 0
  fi
  # Expired — clear marker
  rm -f "$marker"
  return 1
}

mark_exhausted() {
  local agent="$1" reason="${2:-unknown}" reset="${3:-3600}"
  ensure_exhaustion_dir
  local marker="$EXHAUSTION_DIR/$agent.json"
  cat > "$marker" <<JSON
{
  "agent": "$agent",
  "exhausted_at_utc": "$(now_utc)",
  "reason": "$reason",
  "reset_after_seconds": $reset
}
JSON
  warn "Marked $agent as exhausted (reason=$reason, reset_after=${reset}s) — failover to the other agent."
}

clear_exhausted() {
  rm -f "$EXHAUSTION_DIR/$1.json"
}

# detect_exhaustion <log_file> <agent> → 0 if exhausted detected (and marker written)
# Inspects CLI log for known rate-limit / quota / token-exhausted patterns.
detect_exhaustion() {
  local log_file="$1" agent="$2"
  [ -f "$log_file" ] || return 1
  local default_reset
  if [ "$agent" = "claude" ]; then default_reset=$DEFAULT_CLAUDE_RESET; else default_reset=$DEFAULT_CODEX_RESET; fi

  # Generic rate-limit / token / quota / 429 patterns:
  if grep -qiE '(rate.?limit|usage.?limit|429|quota.?exceeded|token.?(exhausted|limit)|too many requests|hourly.?limit|daily.?limit|5.?hour.?limit|insufficient_quota|insufficient credits|invalid_api_key)' "$log_file"; then
    local reason="rate_limit_pattern_matched"
    # Try to extract a hint about reset duration (very rough):
    if grep -qiE 'reset.+([0-9]+).*(min|minute)' "$log_file"; then
      reason="rate_limit_with_reset_minutes_hint"
    elif grep -qiE 'reset.+([0-9]+).*(hour)' "$log_file"; then
      reason="rate_limit_with_reset_hours_hint"
    fi
    mark_exhausted "$agent" "$reason" "$default_reset"
    return 0
  fi
  return 1
}
