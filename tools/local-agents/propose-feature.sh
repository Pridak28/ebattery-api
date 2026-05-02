#!/usr/bin/env bash
# propose-feature.sh <agent> <title> [description]
# An agent (Codex or Claude) records a NEW feature idea for the Master to triage.
# Stored as one .json per proposal under reports/local-agents/proposed-features/.
# The Master reviews these and may convert worthy ones into queue tasks.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PROPOSED_DIR="$REPORTS_DIR/proposed-features"
mkdir -p "$PROPOSED_DIR"

if [ $# -lt 2 ]; then
  cat <<USE
Usage: $0 <agent:codex|claude> "<title>" ["<description>"]
Example:
  $0 codex "Add 5-min PZU resolution support" "DAMAS already has 15-min slots; PZU exports often have 5-min in newer drops. Pipeline normalization lacks 5-min handling."
USE
  exit 64
fi

AGENT="$1"; TITLE="$2"; DESC="${3:-}"
FILE="$PROPOSED_DIR/$(now_id).$AGENT.$(sanitize "$TITLE").json"

cat > "$FILE" <<JSON
{
  "proposed_at_utc": "$(now_utc)",
  "proposed_by": "$AGENT",
  "title": $(printf '%s' "$TITLE" | jq -Rs .),
  "description": $(printf '%s' "$DESC" | jq -Rs .),
  "status": "pending_master_review"
}
JSON

ok "Recorded feature proposal: $FILE"
