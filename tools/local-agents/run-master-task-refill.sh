#!/usr/bin/env bash
# run-master-task-refill.sh
#
# Keeps the local-agent task queue fed while the worker loop is running.
# This is intentionally separate from run-dual-agent-loop.sh so it can be
# started or restarted without interrupting a live worker claim.
#
# Defaults:
#   LOCAL_AGENT_REFILL_DURATION_SECONDS=36000
#   LOCAL_AGENT_REFILL_SLEEP_SECONDS=120
#   LOCAL_AGENT_MIN_OPEN_TASKS=6
#   LOCAL_AGENT_REFILL_BATCH_SIZE=9

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

: "${LOCAL_AGENT_REFILL_DURATION_SECONDS:=36000}"
: "${LOCAL_AGENT_REFILL_SLEEP_SECONDS:=120}"
: "${LOCAL_AGENT_MIN_OPEN_TASKS:=6}"
: "${LOCAL_AGENT_REFILL_BATCH_SIZE:=9}"

"$LIB_SH_DIR/agent-board.sh" init >/dev/null

START="$(date +%s)"
END="$(( START + LOCAL_AGENT_REFILL_DURATION_SECONDS ))"
WAVE=0

open_task_count() {
  jq '[.tasks[] | select(.status == "open")] | length' "$TASKS_FILE"
}

add_if_missing() {
  local id="$1" title="$2" role="$3"
  if jq -e --arg id "$id" '.tasks[] | select(.id == $id)' "$TASKS_FILE" >/dev/null; then
    return 0
  fi
  "$LIB_SH_DIR/agent-board.sh" add "$id" "$title" "$role"
}

seed_wave() {
  WAVE=$((WAVE + 1))
  local stamp base
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="T-MASTER-${stamp}-W${WAVE}"

  log "Master refill generating task wave $WAVE (base=$base)"

  add_if_missing "$base-SOURCE" \
    "Master-generated source discovery: find or validate one public/participant/unverified source and document source_kind/bankability impact" \
    source-discovery

  add_if_missing "$base-SIM" \
    "Master-generated simulation improvement: improve or document one PZU/FR/ROI/SOC/degradation assumption with validation" \
    simulation-research

  add_if_missing "$base-FEATURE" \
    "Master-generated product feature: improve one investor workflow, confidence label, fallback state, or report artifact without unsupported claims" \
    feature-scout

  add_if_missing "$base-BACKEND" \
    "Master-generated backend task: improve one model, API contract, service guardrail, or focused test for BESS calculations" \
    backend-model

  add_if_missing "$base-FRONTEND" \
    "Master-generated frontend task: improve one UI wording, source label, confidence state, or chart explanation for investor trust" \
    frontend-product

  add_if_missing "$base-DATA" \
    "Master-generated data task: strengthen one data manifest, source-kind, freshness, duplicate, outlier, or public-vs-settlement check" \
    data-pipeline

  add_if_missing "$base-DOCS" \
    "Master-generated documentation task: update methodology, runbook, audit notes, or morning-review instructions with concrete evidence" \
    documentation

  add_if_missing "$base-VERIFY" \
    "Master-generated verification task: add or improve one test/build/static check for unsafe wording, generated files, or takeover metadata" \
    verification

  add_if_missing "$base-CRITIC" \
    "Master-generated critic task: challenge one ROI/legal/data/live-market claim and fix wording or write a concrete rejection/recommendation" \
    critic
}

log "===== Master task refill starting ====="
log "  duration:        $LOCAL_AGENT_REFILL_DURATION_SECONDS"
log "  sleep seconds:   $LOCAL_AGENT_REFILL_SLEEP_SECONDS"
log "  min open tasks:  $LOCAL_AGENT_MIN_OPEN_TASKS"
log "  batch size:      $LOCAL_AGENT_REFILL_BATCH_SIZE"

while [ "$(date +%s)" -lt "$END" ]; do
  open="$(open_task_count)"
  if [ "$open" -lt "$LOCAL_AGENT_MIN_OPEN_TASKS" ]; then
    log "Open task count is $open (< $LOCAL_AGENT_MIN_OPEN_TASKS); generating more."
    seed_wave
  else
    log "Open task count is $open; no refill needed."
  fi
  sleep "$LOCAL_AGENT_REFILL_SLEEP_SECONDS"
done

log "===== Master task refill finished ====="
