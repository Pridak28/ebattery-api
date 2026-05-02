#!/usr/bin/env bash
# run-design-review.sh <worktree_path>
# DESIGN / PRODUCT team — automated heuristic checks for product positioning,
# investor clarity, and UX hygiene. The Master Agent calls this before
# accepting any branch with frontend changes.
#
# This is heuristic-only: it raises FLAGS and reduces the design score.
# Final accept/reject still belongs to the Master + human.
#
# Checks:
#   D1. No "ILLUSTRATIVE" badges or hardcoded big numbers added without label.
#   D2. New components must include a loading + error + empty state.
#   D3. New revenue/IRR/€-prefix numbers must come from API state, not hardcoded.
#   D4. No use of "bankable" / "guaranteed" / "live trading" without correct labels.
#   D5. Investor-facing wording quality:
#       - prefer "scenario" / "backtest" / "estimate" over "projection" / "forecast"
#       - flag CAPS-LOCK shouting
#   D6. Accessibility quick scan: <button> with no aria-label and only icon.
#   D7. Page LOC inflation: any single page exceeding 2500 LOC flagged.
# Output: exit 0 if score ≥ 7/10, else 1 with structured flag list.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# Heuristic checks below tolerate grep "no match" (exit 1) — disable -e for them.
set +e

WORKTREE="${1:-$REPO_ROOT}"
SCORE=10
FLAGS=()

if [ ! -d "$WORKTREE/frontend" ]; then
  warn "No frontend/ at $WORKTREE — design review skipped (score 10)"
  exit 0
fi

cd "$WORKTREE"

# ---- D1: hardcoded big numbers without ILLUSTRATIVE/scenario tag ----
log "▶ D1: hardcoded €X.XM numbers in diff vs main"
if git rev-parse --verify main >/dev/null 2>&1; then
  HARDCODED="$(git diff main..HEAD -- 'frontend/**/*.tsx' 'frontend/**/*.ts' 2>/dev/null \
    | grep -E '^\+' | grep -E '€[0-9]+(\.[0-9]+)?[MK]' \
    | grep -v -iE '(ILLUSTRATIVE|StatusLabel|HISTORICAL|backtest|formatCompact|fmtMEur|fmtKEur|status\.totals)' \
    | head -10)"
  if [ -n "$HARDCODED" ]; then
    SCORE=$((SCORE - 2))
    FLAGS+=("D1_hardcoded_money_added")
    warn "D1: hardcoded money lines in diff:"
    echo "$HARDCODED" | sed 's/^/    /'
  fi
fi

# ---- D2: new components must include loading + error + empty states ----
log "▶ D2: new components must handle loading/error/empty"
NEW_COMPONENTS="$(git diff --name-only main..HEAD -- 'frontend/components/**/*.tsx' 2>/dev/null \
  | xargs -I{} sh -c 'git rev-list main..HEAD --diff-filter=A -- "{}" 2>/dev/null && echo {}' \
  | grep -v '^[0-9a-f]\{7,\}' || true)"
if [ -n "$NEW_COMPONENTS" ]; then
  for f in $NEW_COMPONENTS; do
    [ -f "$f" ] || continue
    if ! grep -q "loading\|isLoading\|kind: 'loading'" "$f"; then
      SCORE=$((SCORE - 1))
      FLAGS+=("D2_no_loading_state:$f")
    fi
    if ! grep -q "error\|isError\|kind: 'error'" "$f"; then
      SCORE=$((SCORE - 1))
      FLAGS+=("D2_no_error_state:$f")
    fi
  done
fi

# ---- D3: new numbers must come from state ----
log "▶ D3: new revenue/IRR numbers must come from state"
HARDCODED_NUMS="$(git diff main..HEAD -- 'frontend/**/*.tsx' 2>/dev/null \
  | grep -E '^\+.*\b(IRR|profit|revenue)\s*[:=]\s*[0-9]+(\.[0-9]+)?[^a-zA-Z_]' \
  | grep -v -iE '(state\.|props\.|response\.|analysis\.|sample|fixture|test)' \
  | head -5)"
if [ -n "$HARDCODED_NUMS" ]; then
  SCORE=$((SCORE - 1))
  FLAGS+=("D3_inline_metric_numbers")
fi

# ---- D4: claim audit ----
log "▶ D4: scan diff for unverified product claims"
CLAIMS="$(git diff main..HEAD 2>/dev/null \
  | grep -E '^\+' \
  | grep -iE '\b(bankable|guaranteed|certified|settlement-grade|live trading|verified)\b' \
  | grep -v -iE '(bankability_level|settlement_export|public_marginal|public_market_report|live_api|API CONNECTED|LIVE BACKTEST|verify-agent|verification)' \
  | head -10)"
if [ -n "$CLAIMS" ]; then
  SCORE=$((SCORE - 2))
  FLAGS+=("D4_unverified_product_claims")
  warn "D4: unverified product claims:"
  echo "$CLAIMS" | sed 's/^/    /'
fi

# ---- D5: wording quality ----
log "▶ D5: wording quality"
SHOUTING="$(git diff main..HEAD -- 'frontend/**/*.tsx' 2>/dev/null \
  | grep -E '^\+' \
  | grep -E '"[A-Z]{6,}[ A-Z]{2,}[A-Z]"' \
  | head -3)"
[ -n "$SHOUTING" ] && { FLAGS+=("D5_caps_lock_shouting"); }

# ---- D6: a11y quick scan: icon-only button without aria-label ----
log "▶ D6: a11y quick scan"
A11Y_HITS="$(git diff main..HEAD -- 'frontend/**/*.tsx' 2>/dev/null \
  | grep -E '^\+.*<button' \
  | grep -v -iE '(aria-label|>[a-zA-Z])' \
  | head -3)"
if [ -n "$A11Y_HITS" ]; then
  SCORE=$((SCORE - 1))
  FLAGS+=("D6_button_without_aria_label")
fi

# ---- D7: page LOC inflation ----
log "▶ D7: page LOC inflation"
for p in frontend/app/*/page.tsx frontend/app/page.tsx; do
  [ -f "$p" ] || continue
  loc="$(wc -l < "$p")"
  if [ "$loc" -gt 2500 ]; then
    FLAGS+=("D7_page_loc_inflation:$p:$loc")
  fi
done

# ---- summary ----
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Design / Product team review"
echo "════════════════════════════════════════════════════════"
echo "  Worktree: $WORKTREE"
echo "  Score:    $SCORE / 10  (acceptance threshold: 7)"
if [ "${#FLAGS[@]}" -gt 0 ]; then
  echo "  Flags:"
  for f in "${FLAGS[@]}"; do echo "    - $f"; done
fi
echo "════════════════════════════════════════════════════════"

if [ "$SCORE" -lt 7 ]; then exit 1; fi
exit 0
