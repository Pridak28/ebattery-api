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
    "Confirm backend pytest still 100% green (sanity)" verification
  "$LIB_SH_DIR/agent-board.sh" add T-DRY-002 \
    "Confirm frontend next build succeeds (sanity)" frontend-product
  "$LIB_SH_DIR/agent-board.sh" add T-DRY-003 \
    "Print app version + manifest dataset coverage (read-only sanity)" source-discovery
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
IFS='|' read -r START_MASTER START_MASTER_REASON < <(select_master_provider)
log "  master provider:  $START_MASTER ($START_MASTER_REASON)"

# ---- main loop ----
START="$(date +%s)"
END="$(( START + LOCAL_AGENT_DURATION_SECONDS ))"
ITER=0
while [ "$(date +%s)" -lt "$END" ]; do
  ITER=$((ITER + 1))
  log "--- iteration $ITER ---"

  # Failover-aware: skip an agent that's marked exhausted; if BOTH exhausted
  # sleep until the soonest one resets.
  CODEX_OK=1; CLAUDE_OK=1
  if is_exhausted codex;  then warn "codex is rate-limited; skipping this iteration."; CODEX_OK=0; fi
  if is_exhausted claude; then warn "claude is rate-limited; skipping this iteration."; CLAUDE_OK=0; fi
  IFS='|' read -r LOOP_MASTER LOOP_MASTER_REASON < <(select_master_provider)
  log "Current master provider: $LOOP_MASTER ($LOOP_MASTER_REASON)"

  if [ "$CODEX_OK" = "0" ] && [ "$CLAUDE_OK" = "0" ]; then
    warn "Both agents exhausted — sleeping 300s before re-checking markers."
    sleep 300
    continue
  fi

  if [ "$CODEX_OK" = "1" ] && command -v codex >/dev/null 2>&1; then
    set +e
    bash "$LIB_SH_DIR/run-codex-worker.sh"
    rc=$?
    set -e
    if [ "$rc" = "75" ]; then
      warn "codex hit token exhaustion this iteration; failover engaged."
    elif [ "$rc" -ne 0 ]; then
      warn "codex worker iteration returned $rc (non-fatal)"
    fi
  elif [ "$CODEX_OK" = "1" ]; then
    warn "codex CLI not installed — skipping codex worker"
  fi

  # Refresh time check between agents
  [ "$(date +%s)" -ge "$END" ] && break

  if [ "$CLAUDE_OK" = "1" ] && command -v claude >/dev/null 2>&1; then
    set +e
    bash "$LIB_SH_DIR/run-claude-worker.sh"
    rc=$?
    set -e
    if [ "$rc" = "75" ]; then
      warn "claude hit token exhaustion this iteration; failover engaged."
    elif [ "$rc" -ne 0 ]; then
      warn "claude worker iteration returned $rc (non-fatal)"
    fi
  elif [ "$CLAUDE_OK" = "1" ]; then
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
IFS='|' read -r FINAL_MASTER FINAL_MASTER_REASON < <(select_master_provider)
bash "$LIB_SH_DIR/run-master-review.sh" "$LOCAL_AGENT_RUN_ID" "$FINAL_MASTER" "$FINAL_MASTER_REASON" || warn "master review failed"

# ---- final summary ----
log ""
log "===== Final report ====="
"$LIB_SH_DIR/agent-board.sh" status
echo ""
log "Decision report: $DECISIONS_DIR/$LOCAL_AGENT_RUN_ID.md"
log "Run logs:        $RUN_LOG_DIR/"
log "Reminder: NOTHING was pushed (LOCAL_AGENT_PUSH_BRANCHES=$LOCAL_AGENT_PUSH_BRANCHES)."
log "Review accepted branches manually before merging."
