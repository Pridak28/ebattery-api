#!/usr/bin/env bash
# run-codex-worker.sh
# Single-task Codex worker. Reads the board, claims one task whose
# prefer ∈ {codex, any}, runs Codex CLI to do the work, captures result,
# writes verdict back to the board.
#
# Hard rules:
#  - Runs ONLY inside CODEX_WORKTREE
#  - Calls codex with: -s workspace-write -a never  (no full filesystem, no auto-approval)
#  - Never deploys, never pushes main, never deletes user files
#  - Writes a per-task branch under local-agents/<run_id>/codex-<task>

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

WORKTREE="$CODEX_WORKTREE"
AGENT="codex"
RUN_ID="${LOCAL_AGENT_RUN_ID:-$(now_id)}"

# ---- safety ----
if [ ! -d "$WORKTREE" ]; then
  err "Codex worktree missing: $WORKTREE"
  err "Run: bash tools/local-agents/create-worktrees.sh"
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  err "codex CLI not found in PATH. Install Codex CLI and 'codex login' first."
  exit 1
fi

# ---- pick a claimable task ----
# Eligible: status=open AND provider resolution says this task should run on Codex.
pick_task() {
  jq -r '.tasks[] | select(.status == "open") | .id' "$TASKS_FILE" | while read -r id; do
    [ -f "$CLAIMS_DIR/$id.json" ] && continue
    IFS='|' read -r resolved reason < <(resolve_task_provider "$id" any || true)
    if [ "$resolved" = "$AGENT" ]; then
      printf '%s|%s\n' "$id" "$reason"
      break
    fi
  done
}

PICKED="$(pick_task)"
TASK_ID="${PICKED%%|*}"
TAKEOVER_REASON="${PICKED#*|}"
if [ -z "$TASK_ID" ]; then
  warn "No claimable task for $AGENT. Exiting."
  exit 0
fi

log "Picked task: $TASK_ID (reason=$TAKEOVER_REASON)"

# Atomic claim
"$LIB_SH_DIR/agent-board.sh" claim "$TASK_ID" "$AGENT" "$TAKEOVER_REASON" || { err "Claim failed."; exit 1; }

# Free the lock if the worker dies before completion
trap 'warn "Worker exiting; releasing $TASK_ID"; "$LIB_SH_DIR/agent-board.sh" release "$TASK_ID" "$AGENT" >/dev/null 2>&1 || true' EXIT

# ---- materialize per-task branch ----
TASK_SLUG="$(sanitize "$TASK_ID")"
BRANCH="local-agents/$RUN_ID/$AGENT-$TASK_SLUG"
log "Creating branch $BRANCH in $WORKTREE"
cd "$WORKTREE"
git checkout -B "$BRANCH" 2>&1 | tail -3

# ---- assemble task brief ----
TASK_TITLE="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .title' "$TASKS_FILE")"
TASK_ROLE="$(task_role "$TASK_ID")"
TASK_PREFERRED="$(task_preferred_provider "$TASK_ID")"
TASK_FALLBACK="$(task_fallback_provider "$TASK_ID")"
TASK_ROLE_INSTRUCTIONS="$(role_instructions "$TASK_ROLE")"
TASK_FILES="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.files_likely_touched // []) | join("\n  - ")' "$TASKS_FILE")"
TASK_DOD="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.definition_of_done // []) | join("\n  - ")' "$TASKS_FILE")"
TASK_VALIDATION="$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | (.validation_commands // []) | join("\n  - ")' "$TASKS_FILE")"

PROMPT_FILE="$(mktemp -t codex-prompt-XXXXXX)"
cat > "$PROMPT_FILE" <<PROMPT
You are the Codex worker in a dual-agent system. Working dir: $WORKTREE
Branch: $BRANCH
Task ID: $TASK_ID
Task title: $TASK_TITLE
Task role: $TASK_ROLE
Original preferred provider: $TASK_PREFERRED
Fallback provider: $TASK_FALLBACK
Actual provider: codex
Provider routing reason: $TAKEOVER_REASON

Role instructions:
  $TASK_ROLE_INSTRUCTIONS

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
  - DO NOT modify the Claude worktree at $CLAUDE_WORKTREE.
  - Do not change scope: implement only this task.
  - Preserve the role behavior above even if Codex is taking over a Claude-preferred role.

Implement the task end-to-end, then run the validation commands.
Report back what you changed and the validation result.
PROMPT

# ---- run Codex CLI (non-interactive 'exec' subcommand) ----
# Note: 'codex exec' is already non-interactive by design — it does not prompt
# for approval. The -a/--ask-for-approval flag exists on the interactive
# 'codex' command but NOT on 'codex exec'. Sandbox stays workspace-write.
log "Invoking codex exec (workspace-write, non-interactive)..."
LOG_FILE="$RUNS_DIR/$RUN_ID.$AGENT.$TASK_SLUG.log"
mkdir -p "$RUNS_DIR"
EXIT_CODE=0
PROMPT_TEXT="$(cat "$PROMPT_FILE")"
if codex exec -s workspace-write --skip-git-repo-check "$PROMPT_TEXT" 2>&1 | tee "$LOG_FILE"; then
  ok "codex CLI exited 0"
else
  EXIT_CODE=$?
  err "codex CLI exited $EXIT_CODE"
fi
rm -f "$PROMPT_FILE"

# ---- run validation commands ourselves (sanity gate) ----
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

# ---- commit changes (without pushing) if anything changed ----
cd "$WORKTREE"
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "$AGENT/$TASK_ID: $TASK_TITLE" 2>&1 | tail -3 || true
fi

# ---- record verdict ----
# Token-exhaustion detection: if the CLI failed AND the log shows rate-limit
# patterns, mark this agent exhausted and RELEASE the task (instead of
# rejecting) so the other agent can claim it next iteration.
if [ "$EXIT_CODE" -ne 0 ] && detect_exhaustion "$LOG_FILE" "$AGENT"; then
  warn "Token exhaustion detected for $AGENT — releasing $TASK_ID for failover."
  "$LIB_SH_DIR/agent-board.sh" release "$TASK_ID" "$AGENT" >/dev/null 2>&1 || true
  trap - EXIT
  exit 75   # 75 = EX_TEMPFAIL
fi

if [ "$EXIT_CODE" -ne 0 ]; then
  "$LIB_SH_DIR/agent-board.sh" result-reject "$TASK_ID" "$AGENT" "$BRANCH" "codex_cli_failed_exit_$EXIT_CODE"
elif [ "$VALIDATION_OK" -eq 0 ]; then
  "$LIB_SH_DIR/agent-board.sh" result-reject "$TASK_ID" "$AGENT" "$BRANCH" "validation_failed"
else
  "$LIB_SH_DIR/agent-board.sh" result-accept "$TASK_ID" "$AGENT" "$BRANCH" "verdict_pending_master_review"
fi

# Disable the EXIT trap (we already recorded a result)
trap - EXIT

ok "Codex worker done. Branch=$BRANCH Log=$LOG_FILE"
