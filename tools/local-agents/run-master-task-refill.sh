#!/usr/bin/env bash
# run-master-task-refill.sh
#
# Keeps the local-agent task queue fed while the worker loop is running.
# This is intentionally separate from run-dual-agent-loop.sh so it can be
# started or restarted without interrupting a live worker claim.
#
# The refiller is evidence-based by default: it scans recent results, worker
# logs, repo risk patterns, and known product/model gaps, then adds targeted
# tasks. If there is not enough evidence, it falls back to a safe template wave.
#
# Defaults:
#   LOCAL_AGENT_REFILL_DURATION_SECONDS=36000
#   LOCAL_AGENT_REFILL_SLEEP_SECONDS=120
#   LOCAL_AGENT_MIN_OPEN_TASKS=6
#   LOCAL_AGENT_REFILL_BATCH_SIZE=9
#   LOCAL_AGENT_REFILL_MODE=smart

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

: "${LOCAL_AGENT_REFILL_DURATION_SECONDS:=36000}"
: "${LOCAL_AGENT_REFILL_SLEEP_SECONDS:=120}"
: "${LOCAL_AGENT_MIN_OPEN_TASKS:=6}"
: "${LOCAL_AGENT_REFILL_BATCH_SIZE:=9}"
: "${LOCAL_AGENT_REFILL_MODE:=smart}"

"$LIB_SH_DIR/agent-board.sh" init >/dev/null

START="$(date +%s)"
END="$(( START + LOCAL_AGENT_REFILL_DURATION_SECONDS ))"
WAVE=0
REFILL_REPORT_DIR="$REPORTS_DIR/master-refill"
mkdir -p "$REFILL_REPORT_DIR"

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

task_title_active() {
  local title="$1"
  jq -e --arg title "$title" '
    .tasks[]
    | select(.title == $title)
    | select(.status == "open" or .status == "in_progress")
  ' "$TASKS_FILE" >/dev/null
}

add_targeted_task() {
  local id="$1" title="$2" role="$3" report="$4" evidence="$5"
  if [ "${SMART_ADDED:-0}" -ge "$LOCAL_AGENT_REFILL_BATCH_SIZE" ]; then
    printf -- "- skipped batch cap: %s\n" "$title" >> "$report"
    return 0
  fi
  if task_title_active "$title"; then
    printf -- "- skipped active duplicate: %s\n" "$title" >> "$report"
    return 0
  fi
  add_if_missing "$id" "$title" "$role"
  SMART_ADDED=$(( ${SMART_ADDED:-0} + 1 ))
  printf -- "- added `%s` role `%s`: %s\n  evidence: %s\n" "$id" "$role" "$title" "$evidence" >> "$report"
}

recent_result_summary() {
  if ls "$RESULTS_DIR"/*.json >/dev/null 2>&1; then
    ls -t "$RESULTS_DIR"/*.json | head -12 | while read -r f; do
      jq -r '"\(.task_id) \(.verdict) by \(.agent): \(.reason)"' "$f" 2>/dev/null || true
    done
  fi
}

recent_log_hit_count() {
  local pattern="$1"
  if ! ls "$RUNS_DIR"/*.log >/dev/null 2>&1; then
    echo 0
    return
  fi
  # Keep this bounded so the refiller stays cheap during a 10h run.
  local files count f
  files="$(ls -t "$RUNS_DIR"/*.log 2>/dev/null | head -24 || true)"
  count=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if grep -E -i -l "$pattern" "$f" >/dev/null 2>&1; then
      count=$((count + 1))
    fi
  done <<EOF
$files
EOF
  echo "$count"
}

repo_hit_count() {
  local pattern="$1"
  local hits
  hits="$(cd "$REPO_ROOT" && git grep -I -E -i "$pattern" -- . 2>/dev/null || true)"
  if [ -z "$hits" ]; then
    echo 0
  else
    printf "%s\n" "$hits" | wc -l | tr -d ' '
  fi
}

latest_validation_failures() {
  if ! ls "$RUNS_DIR"/*.validation.log >/dev/null 2>&1; then
    return 0
  fi
  ls -t "$RUNS_DIR"/*.validation.log | head -12 | while read -r f; do
    if [ -s "$f" ] && grep -E -i "failed|error|traceback|command not found|no module named|assert" "$f" >/dev/null 2>&1; then
      basename "$f"
    fi
  done
}

write_smart_report_header() {
  local report="$1" open="$2"
  {
    echo "# Master Refill Evidence Report"
    echo ""
    echo "- generated_at_utc: $(now_utc)"
    echo "- mode: $LOCAL_AGENT_REFILL_MODE"
    echo "- open_tasks_before: $open"
    echo "- min_open_tasks: $LOCAL_AGENT_MIN_OPEN_TASKS"
    echo "- master_provider: $(select_master_provider)"
    echo ""
    echo "## Recent Results"
    recent_result_summary | sed 's/^/- /'
    echo ""
    echo "## Evidence Counters"
    echo "- unsafe/live wording repo hits: $(repo_hit_count 'LIVE|guaranteed|bankable|settlement-grade|settlement grade|real market offers|DAM Open|aFRR Active|mFRR Standby')"
    echo "- fallback/hardcoded repo hits: $(repo_hit_count 'hardcoded|fallback|TODO|FIXME|mock|placeholder|fr_data_clean|market-stats|30 MWh|30 days')"
    echo "- recent log validation/risk hits: $(recent_log_hit_count 'failed|error|traceback|command not found|no module named|unsupported|bankable|guaranteed|hardcoded|fallback')"
    echo ""
    echo "## Latest Validation Failures"
    latest_validation_failures | sed 's/^/- /'
    echo ""
    echo "## Added Tasks"
  } > "$report"
}

seed_smart_wave() {
  WAVE=$((WAVE + 1))
  local stamp base report unsafe_hits fallback_hits validation_hits public_hits endpoint_hits fr_hits pzu_hits manifest_hits
  SMART_ADDED=0
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="T-SMART-${stamp}-W${WAVE}"
  report="$REFILL_REPORT_DIR/$base.md"

  write_smart_report_header "$report" "$(open_task_count)"

  unsafe_hits="$(repo_hit_count 'LIVE|guaranteed|bankable|settlement-grade|settlement grade|real market offers|DAM Open|aFRR Active|mFRR Standby')"
  fallback_hits="$(repo_hit_count 'hardcoded|fallback|TODO|FIXME|mock|placeholder')"
  validation_hits="$(recent_log_hit_count 'failed|error|traceback|command not found|no module named|assert')"
  public_hits="$(repo_hit_count 'public_estimated|public_aggregate|derived_public|participant_export|settlement_export|bankability_level|source_kind')"
  endpoint_hits="$(repo_hit_count '/fr/market-stats|/fr/stats|market-stats')"
  fr_hits="$(repo_hit_count 'fr_data_clean|aFRR|mFRR|DAMAS|30 MWh|30 days')"
  pzu_hits="$(repo_hit_count 'PZU|pzu_history|chronological|SOC|state of charge')"
  manifest_hits="$(repo_hit_count 'DATA_PIPELINE_MANIFEST|manifest.json|source_kind|data_date_max|confidence_label')"

  log "Smart master refill generating targeted tasks (base=$base report=$report)"

  if [ "${unsafe_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-UNSAFE-WORDING" \
      "Smart master: scan and downgrade one unsupported LIVE/guaranteed/bankable/settlement-grade claim with source/confidence wording" \
      critic "$report" "repo grep found $unsafe_hits unsafe/live wording candidates"
  fi

  if [ "${fallback_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-FALLBACKS" \
      "Smart master: inspect one hardcoded/fallback/mock path and add a warning, validation, or focused fix so assumptions are visible" \
      backend-model "$report" "repo grep found $fallback_hits hardcoded/fallback/mock candidates"
  fi

  if [ "${validation_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-VALIDATION" \
      "Smart master: investigate the latest validation/log failure and add the smallest test, dependency, or command fix that prevents recurrence" \
      verification "$report" "recent worker logs contain $validation_hits validation/risk hits"
  fi

  if [ "${public_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-PUBLIC-SETTLEMENT" \
      "Smart master: strengthen one public-data versus participant-settlement gate in code, docs, or UI output" \
      data-pipeline "$report" "repo contains $public_hits source_kind/bankability/public-vs-settlement references"
  fi

  if [ "${endpoint_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-ENDPOINTS" \
      "Smart master: verify one frontend/backend endpoint contract and fix or document any drift with a focused check" \
      verification "$report" "repo grep found $endpoint_hits endpoint drift candidates around FR stats"
  fi

  if [ "${fr_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-FR-REALISM" \
      "Smart master: inspect FR/DAMAS assumptions for capacity/month/pricing-basis realism and add one guardrail, test, or investor warning" \
      simulation-research "$report" "repo grep found $fr_hits FR/DAMAS/aFRR/mFRR assumption references"
  fi

  if [ "${pzu_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-PZU-SOC" \
      "Smart master: improve or verify one PZU chronological SOC/resolution assumption with a focused test or explicit output metadata" \
      simulation-research "$report" "repo grep found $pzu_hits PZU/SOC/chronology references"
  fi

  if [ "${manifest_hits:-0}" -gt 0 ]; then
    add_targeted_task "$base-MANIFEST" \
      "Smart master: make one manifest/source confidence field easier to audit from app output or docs" \
      documentation "$report" "repo grep found $manifest_hits manifest/source confidence references"
  fi

  add_targeted_task "$base-SOURCE" \
    "Smart master: discover one new Romanian BESS data/legal/market source and classify public, participant-only, unverified, or unusable" \
    source-discovery "$report" "continuous source-discovery slot for simulation improvement"

  local added_count
  added_count="$(grep -c '^- added `' "$report" 2>/dev/null || true)"
  added_count="${added_count:-0}"
  if [ "${added_count:-0}" -eq 0 ]; then
    echo "- no evidence-based task was unique; falling back to template wave" >> "$report"
    seed_wave
  fi
  log "Smart master report written: $report"
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
log "  mode:            $LOCAL_AGENT_REFILL_MODE"

while [ "$(date +%s)" -lt "$END" ]; do
  open="$(open_task_count)"
  if [ "$open" -lt "$LOCAL_AGENT_MIN_OPEN_TASKS" ]; then
    log "Open task count is $open (< $LOCAL_AGENT_MIN_OPEN_TASKS); generating more."
    if [ "$LOCAL_AGENT_REFILL_MODE" = "template" ]; then
      seed_wave
    else
      seed_smart_wave
    fi
  else
    log "Open task count is $open; no refill needed."
  fi
  sleep "$LOCAL_AGENT_REFILL_SLEEP_SECONDS"
done

log "===== Master task refill finished ====="
