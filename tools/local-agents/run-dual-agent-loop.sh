#!/usr/bin/env bash
# run-dual-agent-loop.sh
# Orchestrates the dual-agent local loop:
#   - validates main + clean worktree
#   - inits the board
#   - creates worktrees if missing
#   - seeds tasks if the queue is empty
#   - runs codex + claude workers in alternation until duration expires
#   - calls master review at the end
#
# Defaults:
#   LOCAL_AGENT_DURATION_SECONDS=600    (dry run, 10 min)
#   LOCAL_AGENT_MAX_PROTOTYPES=3
#   LOCAL_AGENT_PUSH_BRANCHES=0         (NO remote pushes by default)
#
# Long run: LOCAL_AGENT_DURATION_SECONDS=36000 (10h)

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# ---- safety: clean main only ----
require_clean_main

# ---- init board + worktrees ----
"$LIB_SH_DIR/agent-board.sh" init

if [ ! -d "$CODEX_WORKTREE" ] || [ ! -d "$CLAUDE_WORKTREE" ]; then
  log "One or both worktrees missing — creating them now."
  "$LIB_SH_DIR/create-worktrees.sh"
fi

# ---- seed tasks if the queue is empty ----
TASK_COUNT="$(jq '.tasks | length' "$TASKS_FILE")"
if [ "$TASK_COUNT" -eq 0 ]; then
  log "Queue empty — seeding starter tasks."
  "$LIB_SH_DIR/agent-board.sh" add T-DRY-001 \
    "Confirm backend pytest still 100% green (sanity)" any
  "$LIB_SH_DIR/agent-board.sh" add T-DRY-002 \
    "Confirm frontend next build succeeds (sanity)" any
  "$LIB_SH_DIR/agent-board.sh" add T-DRY-003 \
    "Print app version + manifest dataset coverage (read-only sanity)" any
fi

# ---- run id ----
export LOCAL_AGENT_RUN_ID="$(now_id)"
RUN_LOG_DIR="$RUNS_DIR/$LOCAL_AGENT_RUN_ID"
mkdir -p "$RUN_LOG_DIR"

log "===== Local-agent loop starting ====="
log "  run_id:           $LOCAL_AGENT_RUN_ID"
log "  duration:         ${LOCAL_AGENT_DURATION_SECONDS}s"
log "  max prototypes:   $LOCAL_AGENT_MAX_PROTOTYPES"
log "  push branches:    $LOCAL_AGENT_PUSH_BRANCHES (must stay 0 unless remote configured)"
log "  codex worktree:   $CODEX_WORKTREE"
log "  claude worktree:  $CLAUDE_WORKTREE"

# ---- main loop ----
START="$(date +%s)"
END="$(( START + LOCAL_AGENT_DURATION_SECONDS ))"
ITER=0
while [ "$(date +%s)" -lt "$END" ]; do
  ITER=$((ITER + 1))
  log "--- iteration $ITER ---"

  # Each iteration: try one Codex worker, then one Claude worker. Either may
  # exit immediately if no task is available; that's OK.
  if command -v codex >/dev/null 2>&1; then
    bash "$LIB_SH_DIR/run-codex-worker.sh" || warn "codex worker iteration failed"
  else
    warn "codex CLI not installed — skipping codex worker"
  fi

  # Refresh time check between agents
  [ "$(date +%s)" -ge "$END" ] && break

  if command -v claude >/dev/null 2>&1; then
    bash "$LIB_SH_DIR/run-claude-worker.sh" || warn "claude worker iteration failed"
  else
    warn "claude CLI not installed — skipping claude worker"
  fi

  # Brief pause to avoid burning CPU if no tasks remain
  if [ "$(jq '[.tasks[] | select(.status == "open")] | length' "$TASKS_FILE")" = "0" ]; then
    log "No open tasks remaining — sleeping 60s in case master adds more"
    sleep 60
  fi
done

log "===== Loop time budget exhausted ====="

# ---- master review ----
bash "$LIB_SH_DIR/run-master-review.sh" "$LOCAL_AGENT_RUN_ID" || warn "master review failed"

# ---- final summary ----
log ""
log "===== Final report ====="
"$LIB_SH_DIR/agent-board.sh" status
echo ""
log "Decision report: $DECISIONS_DIR/$LOCAL_AGENT_RUN_ID.md"
log "Run logs:        $RUN_LOG_DIR/"
log "Reminder: NOTHING was pushed (LOCAL_AGENT_PUSH_BRANCHES=$LOCAL_AGENT_PUSH_BRANCHES)."
log "Review accepted branches manually before merging."
