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
: "${LOCAL_AGENT_MASTER_MODE:=auto}"       # auto|codex|claude|shell

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
# Role-based provider routing
# ============================================================================
# Tasks are role-first. Providers can take over each other's role when the
# preferred provider is rate-limited/unavailable. Older tasks with only `prefer`
# remain valid and are normalized at selection time.

normalize_role() {
  case "${1:-}" in
    master|source-discovery|simulation-research|feature-scout|backend-model|frontend-product|data-pipeline|documentation|verification|critic)
      echo "$1" ;;
    runtime|testing) echo "verification" ;;
    docs) echo "documentation" ;;
    uiux|frontend) echo "frontend-product" ;;
    bess-logic|business-logic) echo "simulation-research" ;;
    architecture) echo "backend-model" ;;
    data) echo "data-pipeline" ;;
    *) echo "verification" ;;
  esac
}

preferred_provider_for_role() {
  case "$(normalize_role "$1")" in
    backend-model|data-pipeline|verification|simulation-research) echo "codex" ;;
    frontend-product|documentation|feature-scout|critic|master) echo "claude" ;;
    source-discovery) echo "any" ;;
    *) echo "any" ;;
  esac
}

fallback_provider_for() {
  case "${1:-any}" in
    codex) echo "claude" ;;
    claude) echo "codex" ;;
    *) echo "any" ;;
  esac
}

agent_cli_available() {
  case "$1" in
    codex) command -v codex >/dev/null 2>&1 ;;
    claude) command -v claude >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

provider_available() {
  local provider="$1"
  if [ "$provider" != "codex" ] && [ "$provider" != "claude" ]; then
    return 1
  fi
  is_exhausted "$provider" && return 1
  agent_cli_available "$provider" || return 1
  return 0
}

provider_unavailable_reason() {
  local provider="$1"
  if [ "$provider" != "codex" ] && [ "$provider" != "claude" ]; then
    echo "provider_not_specific"
  elif is_exhausted "$provider"; then
    echo "${provider}_exhausted"
  elif ! agent_cli_available "$provider"; then
    echo "${provider}_cli_missing"
  else
    echo "available"
  fi
}

resolve_provider() {
  local preferred="${1:-any}" fallback="${2:-any}" requested="${3:-any}"

  if [ "$requested" = "codex" ] || [ "$requested" = "claude" ]; then
    if provider_available "$requested"; then
      echo "$requested|requested_provider_available"
      return 0
    fi
    echo "none|$(provider_unavailable_reason "$requested")"
    return 1
  fi

  if [ "$preferred" = "any" ] || [ -z "$preferred" ]; then
    if provider_available codex; then echo "codex|preferred_any_codex_available"; return 0; fi
    if provider_available claude; then echo "claude|preferred_any_claude_available"; return 0; fi
    echo "none|both_providers_unavailable"
    return 1
  fi

  if provider_available "$preferred"; then
    echo "$preferred|preferred_available"
    return 0
  fi

  local why
  why="$(provider_unavailable_reason "$preferred")"
  if [ "$fallback" = "any" ] || [ -z "$fallback" ]; then
    fallback="$(fallback_provider_for "$preferred")"
  fi
  if provider_available "$fallback"; then
    echo "$fallback|takeover_${why}"
    return 0
  fi

  echo "none|${why}_and_$(provider_unavailable_reason "$fallback")"
  return 1
}

task_json_field() {
  local id="$1" expr="$2"
  jq -r --arg id "$id" "$expr" "$TASKS_FILE"
}

task_role() {
  local id="$1"
  local role prefer
  role="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.role // "")')"
  if [ -n "$role" ] && [ "$role" != "null" ]; then normalize_role "$role"; return; fi
  prefer="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.prefer // "any")')"
  case "$prefer" in
    codex) echo "verification" ;;
    claude) echo "documentation" ;;
    *) echo "source-discovery" ;;
  esac
}

task_preferred_provider() {
  local id="$1" role preferred prefer
  role="$(task_role "$id")"
  preferred="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.preferred_provider // "")')"
  if [ -n "$preferred" ] && [ "$preferred" != "null" ]; then echo "$preferred"; return; fi
  prefer="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.prefer // "")')"
  if [ "$prefer" = "codex" ] || [ "$prefer" = "claude" ] || [ "$prefer" = "any" ]; then
    echo "$prefer"
  else
    preferred_provider_for_role "$role"
  fi
}

task_fallback_provider() {
  local id="$1" fallback preferred
  fallback="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.fallback_provider // "")')"
  if [ -n "$fallback" ] && [ "$fallback" != "null" ]; then echo "$fallback"; return; fi
  preferred="$(task_preferred_provider "$id")"
  fallback_provider_for "$preferred"
}

resolve_task_provider() {
  local id="$1" requested="${2:-any}" preferred fallback
  preferred="$(task_preferred_provider "$id")"
  fallback="$(task_fallback_provider "$id")"
  resolve_provider "$preferred" "$fallback" "$requested"
}

role_instructions() {
  case "$(normalize_role "$1")" in
    master)
      echo "Act as the master quality gate. Select only high-value, low-risk, testable changes. Reject noisy or unsafe work."
      ;;
    source-discovery)
      echo "Find and classify new public/participant/unverified data and information sources. Do not invent bankable claims."
      ;;
    simulation-research)
      echo "Focus on PZU, FR/DAMAS, ROI, degradation, SOC, activation, tariff, and bankability assumptions. Prefer tests and explicit confidence labels."
      ;;
    feature-scout)
      echo "Find product features that improve investor trust, data confidence, controls, exports, and workflow clarity. Avoid decorative changes."
      ;;
    backend-model)
      echo "Focus on backend correctness, schemas, services, data loaders, API contracts, and tests. Keep financial/legal assumptions explicit."
      ;;
    frontend-product)
      echo "Focus on investor-grade UX, labels, charts, workflows, empty/error states, and avoiding overconfident live/bankable wording."
      ;;
    data-pipeline)
      echo "Focus on source manifests, freshness, validation, hashing, public-vs-settlement labels, and deploy-safe processed artifacts."
      ;;
    documentation)
      echo "Focus on clear methodology, runbooks, audit notes, source confidence, and human review instructions."
      ;;
    verification)
      echo "Focus on tests, builds, validation commands, diff safety, secrets checks, and regression risk."
      ;;
    critic)
      echo "Challenge assumptions. Reject unsupported bankable/guaranteed/live/settlement-grade claims and broad risky patches."
      ;;
  esac
}

select_master_provider() {
  case "$LOCAL_AGENT_MASTER_MODE" in
    codex)
      if provider_available codex; then echo "codex|forced_codex"; else echo "shell|forced_codex_unavailable"; fi ;;
    claude)
      if provider_available claude; then echo "claude|forced_claude"; else echo "shell|forced_claude_unavailable"; fi ;;
    shell)
      echo "shell|forced_shell" ;;
    auto|*)
      if provider_available claude; then echo "claude|auto_claude_available"; return; fi
      if provider_available codex; then echo "codex|auto_codex_takeover"; return; fi
      echo "shell|auto_both_providers_unavailable" ;;
  esac
}

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
  then_s="$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$exh_at" +%s 2>/dev/null || echo 0)"
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
  if grep -qiE '(rate.?limit|usage.?limit|hit your limit|you.?ve hit your limit|429|quota.?exceeded|token.?(exhausted|limit)|too many requests|hourly.?limit|daily.?limit|5.?hour.?limit|insufficient_quota|insufficient credits|invalid_api_key|resets [0-9:]+)' "$log_file"; then
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
