#!/usr/bin/env bash
# run-claude-worker.sh
# Single-task Claude worker. Mirrors run-codex-worker.sh but invokes
# the Claude Code CLI in --permission-mode auto.
#
# Hard rules:
#  - Runs ONLY inside CLAUDE_WORKTREE
#  - Calls claude with: --permission-mode auto
#  - Never deploys, never pushes main, never deletes user files
#  - Writes a per-task branch under local-agents/<run_id>/claude-<task>

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

WORKTREE="$CLAUDE_WORKTREE"
AGENT="claude"
RUN_ID="${LOCAL_AGENT_RUN_ID:-$(now_id)}"

# ---- safety ----
if [ ! -d "$WORKTREE" ]; then
  err "Claude worktree missing: $WORKTREE"
  err "Run: bash tools/local-agents/create-worktrees.sh"
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  err "claude CLI not found in PATH. Install Claude Code CLI and 'claude login' first."
  exit 1
fi

# ---- pick a claimable task ----
pick_task() {
  jq -r --arg agent "$AGENT" '
    .tasks[]
    | select(.status == "open")
    | select((.prefer // "any") == $agent or (.prefer // "any") == "any")
    | .id
  ' "$TASKS_FILE" | while read -r id; do
    [ -f "$CLAIMS_DIR/$id.json" ] && continue
    echo "$id"
    break
  done
}

TASK_ID="$(pick_task)"
if [ -z "$TASK_ID" ]; then
  warn "No claimable task for $AGENT. Exiting."
  exit 0
fi

log "Picked task: $TASK_ID"
"$LIB_SH_DIR/agent-board.sh" claim "$TASK_ID" "$AGENT" || { err "Claim failed."; exit 1; }
trap 'warn "Worker exiting; releasing $TASK_ID"; "$LIB_SH_DIR/agent-board.sh" release "$TASK_ID" "$AGENT" >/dev/null 2>&1 || true' EXIT

TASK_SLUG="$(sanitize "$TASK_ID")"
BRANCH="local-agents/$RUN_ID/$AGENT-$TASK_SLUG"
log "Creating branch $BRANCH in $WORKTREE"
cd "$WORKTREE"
git checkout -B "$BRANCH" 2>&1 | tail -3

TASK_TITLE="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .title' "$TASKS_FILE")"
TASK_FILES="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.files_likely_touched // []) | join("\n  - ")' "$TASKS_FILE")"
TASK_DOD="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.definition_of_done // []) | join("\n  - ")' "$TASKS_FILE")"
TASK_VALIDATION="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.validation_commands // []) | join("\n  - ")' "$TASKS_FILE")"

PROMPT_FILE="$(mktemp -t claude-prompt-XXXXXX)"
cat > "$PROMPT_FILE" <<PROMPT
You are the Claude Code worker in a dual-agent system. Working dir: $WORKTREE
Branch: $BRANCH
Task ID: $TASK_ID
Task title: $TASK_TITLE

Files likely to touch:
  - ${TASK_FILES:-(unspecified)}

Definition of done:
  - ${TASK_DOD:-(unspecified)}

Validation commands you must run before exiting:
  - ${TASK_VALIDATION:-(unspecified — at minimum run pytest if backend test exists)}

Hard rules:
  - DO NOT push to any remote.
  - DO NOT deploy.
  - DO NOT delete user files outside the listed task files.
  - DO NOT commit secrets (.env, .pem, .key).
  - DO NOT modify the Codex worktree at $CODEX_WORKTREE.
  - Do not change scope: implement only this task.

Implement the task end-to-end, then run the validation commands.
Report back what you changed and the validation result.
PROMPT

log "Invoking claude (permission-mode=auto)..."
LOG_FILE="$RUNS_DIR/$RUN_ID.$AGENT.$TASK_SLUG.log"
mkdir -p "$RUNS_DIR"
EXIT_CODE=0
if claude --permission-mode auto < "$PROMPT_FILE" 2>&1 | tee "$LOG_FILE"; then
  ok "claude CLI exited 0"
else
  EXIT_CODE=$?
  err "claude CLI exited $EXIT_CODE"
fi
rm -f "$PROMPT_FILE"

VALIDATION_OK=1
VALIDATION_LOG="$RUNS_DIR/$RUN_ID.$AGENT.$TASK_SLUG.validation.log"
: > "$VALIDATION_LOG"
while IFS= read -r vcmd; do
  [ -z "$vcmd" ] || [ "$vcmd" = "(unspecified — at minimum run pytest if backend test exists)" ] && continue
  log "Running validation: $vcmd"
  if ! ( cd "$WORKTREE" && eval "$vcmd" ) >> "$VALIDATION_LOG" 2>&1; then
    VALIDATION_OK=0
    err "Validation FAILED: $vcmd"
  fi
done <<< "$TASK_VALIDATION"

cd "$WORKTREE"
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "$AGENT/$TASK_ID: $TASK_TITLE" 2>&1 | tail -3 || true
fi

if [ "$EXIT_CODE" -ne 0 ]; then
  "$LIB_SH_DIR/agent-board.sh" result-reject "$TASK_ID" "$AGENT" "$BRANCH" "claude_cli_failed_exit_$EXIT_CODE"
elif [ "$VALIDATION_OK" -eq 0 ]; then
  "$LIB_SH_DIR/agent-board.sh" result-reject "$TASK_ID" "$AGENT" "$BRANCH" "validation_failed"
else
  "$LIB_SH_DIR/agent-board.sh" result-accept "$TASK_ID" "$AGENT" "$BRANCH" "verdict_pending_master_review"
fi

trap - EXIT
ok "Claude worker done. Branch=$BRANCH Log=$LOG_FILE"
