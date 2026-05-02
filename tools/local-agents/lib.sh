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
