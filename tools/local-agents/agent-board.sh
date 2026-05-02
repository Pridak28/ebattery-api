#!/usr/bin/env bash
# agent-board.sh <command> [args...]
#
# Commands:
#   init                          create board folders + empty tasks.json if missing
#   status                        print board state
#   add <id> <title> <role>       add a task; role or legacy provider
#   tasks                         list all tasks
#   claim <task_id> <agent>       atomically claim a task (creates lock file)
#   release <task_id> <agent>     remove the claim (e.g. on cancel)
#   result-accept <id> <agent> <branch> <reason>
#   result-reject <id> <agent> <branch> <reason>
#   result-needs-review <id> <agent> <branch> <reason>

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ensure_jq

cmd="${1:-status}"
shift || true

case "$cmd" in
  init)
    mkdir -p "$CLAIMS_DIR" "$RESULTS_DIR" "$DECISIONS_DIR" "$RUNS_DIR" "$EXHAUSTION_DIR"
    if [ ! -f "$TASKS_FILE" ]; then
      cat > "$TASKS_FILE" <<JSON
{
  "schema_version": "local_agents_tasks_v2",
  "generated_at_utc": "$(now_utc)",
  "tasks": []
}
JSON
      ok "Created empty tasks.json at $TASKS_FILE"
    fi
    ok "Board initialized at $BOARD_DIR"
    ;;

  status)
    echo "════════════════════════════════════════════════════════"
    echo "  Local-agent board — $(now_utc)"
    echo "════════════════════════════════════════════════════════"
    echo "  REPO_ROOT:        $REPO_ROOT"
    echo "  CODEX_WORKTREE:   $CODEX_WORKTREE  $([ -d "$CODEX_WORKTREE" ] && echo '✓' || echo '(missing)')"
    echo "  CLAUDE_WORKTREE:  $CLAUDE_WORKTREE  $([ -d "$CLAUDE_WORKTREE" ] && echo '✓' || echo '(missing)')"
    IFS='|' read -r master_provider master_reason < <(select_master_provider)
    echo "  CURRENT MASTER:   $master_provider ($master_reason)"
    echo ""
    if [ ! -f "$TASKS_FILE" ]; then
      echo "  (tasks.json missing — run 'agent-board.sh init')"
      exit 0
    fi
    echo "  Tasks:"
    jq -r '
      .tasks[]
      | "    \(.id) [\(.status)] role=\(.role // "legacy") preferred=\(.preferred_provider // .prefer // "any") fallback=\(.fallback_provider // "auto") assigned=\(.assigned_provider // .owner // "—") reason=\(.takeover_reason // "—") :: \(.title)"
    ' "$TASKS_FILE" 2>/dev/null || echo "    (parse error)"
    echo ""
    echo "  Active claims (lock files):"
    if ls "$CLAIMS_DIR"/*.json >/dev/null 2>&1; then
      for f in "$CLAIMS_DIR"/*.json; do
        echo "    $(basename "$f"): $(jq -r '.task_id + " by " + .agent + " at " + .claimed_at_utc' "$f")"
      done
    else
      echo "    (none)"
    fi
    echo ""
    echo "  Recent results:"
    ls -t "$RESULTS_DIR"/*.json 2>/dev/null | head -5 | while read -r f; do
      [ -z "$f" ] && continue
      echo "    $(basename "$f"): $(jq -r '.verdict + " by " + .agent + " — " + .reason' "$f" 2>/dev/null || echo '(parse error)')"
    done
    echo ""
    echo "  Exhaustion markers (active rate-limit failover):"
    if ls "$EXHAUSTION_DIR"/*.json >/dev/null 2>&1; then
      for f in "$EXHAUSTION_DIR"/*.json; do
        echo "    $(jq -r '.agent + " until reset_after=" + (.reset_after_seconds|tostring) + "s from " + .exhausted_at_utc' "$f")"
      done
    else
      echo "    (none — both agents eligible)"
    fi
    echo "════════════════════════════════════════════════════════"
    ;;

  add)
    id="${1:?need id}"; title="${2:?need title}"; role_or_provider="${3:-source-discovery}"
    [ -f "$TASKS_FILE" ] || { err "Run 'init' first."; exit 1; }
    if jq -e --arg id "$id" '.tasks[] | select(.id == $id)' "$TASKS_FILE" >/dev/null; then
      err "Task $id already exists."
      exit 1
    fi
    if [ "$role_or_provider" = "codex" ] || [ "$role_or_provider" = "claude" ] || [ "$role_or_provider" = "any" ]; then
      role="source-discovery"
      preferred="$role_or_provider"
    else
      role="$(normalize_role "$role_or_provider")"
      preferred="$(preferred_provider_for_role "$role")"
    fi
    fallback="$(fallback_provider_for "$preferred")"
    tmp="$(mktemp)"
    jq --arg id "$id" --arg t "$title" --arg role "$role" --arg preferred "$preferred" --arg fallback "$fallback" --arg now "$(now_utc)" \
       '.schema_version = "local_agents_tasks_v2" |
        .tasks += [{"id":$id,"title":$t,"status":"open","owner":null,"role":$role,"preferred_provider":$preferred,"fallback_provider":$fallback,"assigned_provider":null,"takeover_reason":null,"created_at_utc":$now,"files_likely_touched":[],"validation_commands":[],"definition_of_done":[]}]' \
       "$TASKS_FILE" > "$tmp" && mv "$tmp" "$TASKS_FILE"
    ok "Added task $id: $title (role=$role preferred=$preferred fallback=$fallback)"
    ;;

  tasks)
    [ -f "$TASKS_FILE" ] || { err "tasks.json missing — run init."; exit 1; }
    jq -r '.tasks[] | "\(.id) [\(.status)] role=\(.role // "legacy") preferred=\(.preferred_provider // .prefer // "any") assigned=\(.assigned_provider // .owner // "-") :: \(.title)"' "$TASKS_FILE"
    ;;

  claim)
    id="${1:?need task id}"; agent="${2:?need agent name}"; takeover_reason="${3:-manual_claim}"
    if [ "$agent" != "codex" ] && [ "$agent" != "claude" ]; then
      err "Agent must be codex or claude."; exit 1
    fi
    [ -f "$TASKS_FILE" ] || { err "tasks.json missing — run init."; exit 1; }
    # Verify task exists and is open
    status="$(jq -r --arg id "$id" '.tasks[] | select(.id == $id) | .status // "missing"' "$TASKS_FILE")"
    [ "$status" = "missing" ] && { err "Task $id not found."; exit 1; }
    [ "$status" != "open" ] && { err "Task $id status is '$status', cannot claim."; exit 1; }
    IFS='|' read -r resolved_provider resolved_reason < <(resolve_task_provider "$id" any || true)
    if [ "$resolved_provider" != "$agent" ]; then
      err "Task $id resolves to '$resolved_provider' ($resolved_reason), not '$agent'."
      exit 1
    fi
    if [ "$takeover_reason" = "manual_claim" ]; then
      takeover_reason="$resolved_reason"
    fi

    lock_file="$CLAIMS_DIR/$id.json"
    # Lock-file based atomic-ish claim:
    role="$(task_role "$id")"
    preferred="$(task_preferred_provider "$id")"
    fallback="$(task_fallback_provider "$id")"
    if ! ( set -o noclobber; printf '{"task_id":"%s","agent":"%s","role":"%s","preferred_provider":"%s","fallback_provider":"%s","takeover_reason":"%s","claimed_at_utc":"%s","pid":%d}\n' \
                "$id" "$agent" "$role" "$preferred" "$fallback" "$takeover_reason" "$(now_utc)" "$$" > "$lock_file" ) 2>/dev/null; then
      existing="$(jq -r '.agent' "$lock_file" 2>/dev/null || echo unknown)"
      err "Task $id is already claimed by '$existing' (lock at $lock_file)."
      exit 2
    fi
    # Update tasks.json
    tmp="$(mktemp)"
    jq --arg id "$id" --arg a "$agent" --arg role "$role" --arg preferred "$preferred" --arg fallback "$fallback" --arg reason "$takeover_reason" \
       '(.tasks[] | select(.id == $id) | .owner) = $a |
        (.tasks[] | select(.id == $id) | .assigned_provider) = $a |
        (.tasks[] | select(.id == $id) | .role) = $role |
        (.tasks[] | select(.id == $id) | .preferred_provider) = $preferred |
        (.tasks[] | select(.id == $id) | .fallback_provider) = $fallback |
        (.tasks[] | select(.id == $id) | .takeover_reason) = $reason |
        (.tasks[] | select(.id == $id) | .status) = "in_progress"' \
       "$TASKS_FILE" > "$tmp" && mv "$tmp" "$TASKS_FILE"
    ok "$agent claimed $id (role=$role preferred=$preferred fallback=$fallback reason=$takeover_reason)"
    echo "  lock: $lock_file"
    ;;

  release)
    id="${1:?need task id}"; agent="${2:?need agent name}"
    lock_file="$CLAIMS_DIR/$id.json"
    if [ -f "$lock_file" ]; then
      lock_agent="$(jq -r '.agent' "$lock_file")"
      if [ "$lock_agent" != "$agent" ]; then
        err "Lock owned by '$lock_agent', refused to release as '$agent'."
        exit 1
      fi
      rm -f "$lock_file"
    fi
    tmp="$(mktemp)"
    jq --arg id "$id" \
       '(.tasks[] | select(.id == $id) | .owner) = null |
        (.tasks[] | select(.id == $id) | .assigned_provider) = null |
        (.tasks[] | select(.id == $id) | .takeover_reason) = null |
        (.tasks[] | select(.id == $id) | .status) = "open"' \
       "$TASKS_FILE" > "$tmp" && mv "$tmp" "$TASKS_FILE"
    ok "Released $id"
    ;;

  result-accept|result-reject|result-needs-review)
    verdict="${cmd#result-}"
    id="${1:?need task id}"; agent="${2:?need agent name}"; branch="${3:?need branch}"; reason="${4:-no-reason}"
    rfile="$RESULTS_DIR/$id.$agent.$(now_id).json"
    role="$(task_role "$id")"
    preferred="$(task_preferred_provider "$id")"
    fallback="$(task_fallback_provider "$id")"
    takeover_reason="$(task_json_field "$id" '.tasks[] | select(.id == $id) | (.takeover_reason // "direct")')"
    cat > "$rfile" <<JSON
{
  "task_id": "$id",
  "role": "$role",
  "preferred_provider": "$preferred",
  "fallback_provider": "$fallback",
  "agent": "$agent",
  "actual_provider": "$agent",
  "takeover_reason": "$takeover_reason",
  "branch": "$branch",
  "verdict": "$verdict",
  "reason": "$reason",
  "recorded_at_utc": "$(now_utc)"
}
JSON
    # Update task status
    tmp="$(mktemp)"
    case "$verdict" in
      accept)        new_status="awaiting_master_review" ;;
      reject)        new_status="rejected" ;;
      needs-review)  new_status="needs_human_review" ;;
    esac
    jq --arg id "$id" --arg s "$new_status" \
       '(.tasks[] | select(.id == $id) | .status) = $s' \
       "$TASKS_FILE" > "$tmp" && mv "$tmp" "$TASKS_FILE"
    # Remove the claim lock so the next agent can pick a new task
    rm -f "$CLAIMS_DIR/$id.json"
    ok "Recorded $verdict for $id by $agent at $rfile"
    ;;

  exhaustion)
    # exhaustion list / clear-claude / clear-codex
    sub="${1:-list}"
    case "$sub" in
      list)
        if ls "$EXHAUSTION_DIR"/*.json >/dev/null 2>&1; then
          for f in "$EXHAUSTION_DIR"/*.json; do
            jq -r '"\(.agent): exhausted_at=\(.exhausted_at_utc) reason=\(.reason) reset_after_s=\(.reset_after_seconds)"' "$f"
          done
        else
          echo "(no exhaustion markers — both agents eligible)"
        fi ;;
      clear-claude) clear_exhausted claude; ok "Cleared claude exhaustion marker." ;;
      clear-codex)  clear_exhausted codex;  ok "Cleared codex exhaustion marker." ;;
      *) err "Unknown exhaustion subcommand: $sub (expected: list|clear-claude|clear-codex)"; exit 1 ;;
    esac ;;

  *)
    err "Unknown command: $cmd"
    cat <<HELP
Usage: $0 <command> [args]

Commands:
  init                                       create folders + empty tasks.json
  status                                     show board state (default if no command)
  tasks                                      list tasks (one per line)
  add <id> <title> <role|legacy-provider>       add a new open task
  claim <task_id> <agent>                    atomically claim (creates lock file)
  release <task_id> <agent>                  release a claim
  result-accept <id> <agent> <branch> <reason>
  result-reject <id> <agent> <branch> <reason>
  result-needs-review <id> <agent> <branch> <reason>
  exhaustion list                            show current rate-limit markers
  exhaustion clear-claude                    clear Claude rate-limit marker
  exhaustion clear-codex                     clear Codex rate-limit marker

Paths:
  tasks:    $TASKS_FILE
  claims:   $CLAIMS_DIR
  results:  $RESULTS_DIR
HELP
    exit 64
    ;;
esac
