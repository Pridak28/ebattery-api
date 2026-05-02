#!/usr/bin/env bash
# run-master-review.sh [run_id]
# Reads recent results, scores them, picks the best ≤ MAX_PROTOTYPES,
# writes a markdown decision report to reports/local-agents/reports/master-decisions/.
#
# This is intentionally simple/heuristic — humans still review accepted branches.
# Master sees verdicts from the worker scripts plus loose signals.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

RUN_ID="${1:-${LOCAL_AGENT_RUN_ID:-$(now_id)}}"
DECISION_FILE="$DECISIONS_DIR/$RUN_ID.md"
mkdir -p "$DECISIONS_DIR"

log "Master review for run $RUN_ID → $DECISION_FILE"

# Collect results from the run (filename pattern: <task>.<agent>.<ts>.json)
mapfile -t RESULT_FILES < <(ls -t "$RESULTS_DIR"/*.json 2>/dev/null || true)
if [ "${#RESULT_FILES[@]}" -eq 0 ]; then
  warn "No results in $RESULTS_DIR — nothing to review."
  cat > "$DECISION_FILE" <<MD
# Master decision report — $RUN_ID

No results to review.
MD
  exit 0
fi

ACCEPTED=()
REJECTED=()
NEEDS_REVIEW=()
UNSAFE=()

for f in "${RESULT_FILES[@]}"; do
  v="$(jq -r '.verdict' "$f")"
  case "$v" in
    accept)        ACCEPTED+=("$f") ;;
    reject)        REJECTED+=("$f") ;;
    needs-review)  NEEDS_REVIEW+=("$f") ;;
    *)             UNSAFE+=("$f") ;;
  esac
done

# Master must re-verify each "accepted" worker result against
#   1. verification suite (pytest, build, market-realism guard, sanity probes)
#   2. design/product review (positioning, investor clarity, a11y)
# An accept is only KEPT if BOTH pass. Otherwise demoted to needs-review.
log "Master re-verification on each worker-accepted result..."
KEEP="${LOCAL_AGENT_MAX_PROTOTYPES:-3}"
MASTER_KEPT=()
MASTER_DEMOTED=()
for f in "${ACCEPTED[@]}"; do
  branch="$(jq -r '.branch' "$f")"
  agent="$(jq -r '.agent' "$f")"
  worktree="$(agent_worktree "$agent" 2>/dev/null || echo "")"
  if [ -z "$worktree" ] || [ ! -d "$worktree" ]; then
    MASTER_DEMOTED+=("$f::worktree_missing")
    continue
  fi
  # Make sure the agent worktree is on the result's branch
  ( cd "$worktree" && git checkout "$branch" 2>/dev/null ) || true
  # Run verification + design review
  VERIFY_OK=1; DESIGN_OK=1
  if ! "$LIB_SH_DIR/run-verification-suite.sh" "$worktree" >/dev/null 2>&1; then VERIFY_OK=0; fi
  if ! "$LIB_SH_DIR/run-design-review.sh"      "$worktree" >/dev/null 2>&1; then DESIGN_OK=0; fi
  if [ "$VERIFY_OK" = "1" ] && [ "$DESIGN_OK" = "1" ]; then
    MASTER_KEPT+=("$f")
  else
    MASTER_DEMOTED+=("$f::verify=$VERIFY_OK design=$DESIGN_OK")
  fi
done

# Limit accepted to MAX_PROTOTYPES — keep the most recent ones
ACCEPTED_TOP=("${MASTER_KEPT[@]:0:$KEEP}")

# ---- compose markdown ----
{
  echo "# Master decision report"
  echo ""
  echo "- Run id: \`$RUN_ID\`"
  echo "- Generated: $(now_utc)"
  echo "- Results scanned: ${#RESULT_FILES[@]}"
  echo "- Max prototypes to keep: $KEEP"
  echo ""
  echo "## Accepted (kept for human review)"
  if [ "${#ACCEPTED_TOP[@]}" -eq 0 ]; then
    echo "_(none)_"
  else
    for f in "${ACCEPTED_TOP[@]}"; do
      task="$(jq -r '.task_id' "$f")"
      agent="$(jq -r '.agent' "$f")"
      branch="$(jq -r '.branch' "$f")"
      reason="$(jq -r '.reason' "$f")"
      ts="$(jq -r '.recorded_at_utc' "$f")"
      echo "- **$task** by **$agent** — branch \`$branch\`"
      echo "  - reason: $reason"
      echo "  - at: $ts"
      echo "  - file: \`${f#$REPO_ROOT/}\`"
    done
  fi
  echo ""
  echo "## Demoted by Master (verify or design review failed)"
  if [ "${#MASTER_DEMOTED[@]}" -eq 0 ]; then echo "_(none)_"; else
    for entry in "${MASTER_DEMOTED[@]}"; do echo "- $entry"; done
  fi
  echo ""
  echo "## Proposed features (pending Master triage)"
  if [ -d "$REPORTS_DIR/proposed-features" ] && ls "$REPORTS_DIR/proposed-features"/*.json >/dev/null 2>&1; then
    for pf in "$REPORTS_DIR/proposed-features"/*.json; do
      echo "- $(jq -r '"\(.proposed_by) — \(.title)"' "$pf")"
    done
  else
    echo "_(none)_"
  fi
  echo ""
  echo "## Rejected"
  if [ "${#REJECTED[@]}" -eq 0 ]; then echo "_(none)_"; else
    for f in "${REJECTED[@]}"; do
      echo "- $(jq -r '"\(.task_id) by \(.agent) [branch \(.branch)] — \(.reason)"' "$f")"
    done
  fi
  echo ""
  echo "## Needs human review"
  if [ "${#NEEDS_REVIEW[@]}" -eq 0 ]; then echo "_(none)_"; else
    for f in "${NEEDS_REVIEW[@]}"; do
      echo "- $(jq -r '"\(.task_id) by \(.agent) [branch \(.branch)] — \(.reason)"' "$f")"
    done
  fi
  echo ""
  echo "## Unsafe / unknown verdict"
  if [ "${#UNSAFE[@]}" -eq 0 ]; then echo "_(none)_"; else
    for f in "${UNSAFE[@]}"; do
      echo "- file: \`${f#$REPO_ROOT/}\` — verdict: $(jq -r '.verdict' "$f")"
    done
  fi
  echo ""
  echo "## Next steps for the human reviewer"
  echo ""
  echo "1. \`cd $REPO_ROOT && git fetch --all && git branch -a | grep local-agents/\`"
  echo "2. For each accepted branch above: \`git diff main..<branch>\` and decide."
  echo "3. NOTHING was merged automatically. NOTHING was pushed."
  echo ""
  echo "## Hard limits enforced this run"
  echo "- LOCAL_AGENT_PUSH_BRANCHES=$LOCAL_AGENT_PUSH_BRANCHES (0 = no remote pushes)"
  echo "- LOCAL_AGENT_MAX_PROTOTYPES=$LOCAL_AGENT_MAX_PROTOTYPES"
  echo "- LOCAL_AGENT_DURATION_SECONDS=$LOCAL_AGENT_DURATION_SECONDS"
} > "$DECISION_FILE"

ok "Decision report at $DECISION_FILE"
echo ""
sed -n '1,40p' "$DECISION_FILE"
