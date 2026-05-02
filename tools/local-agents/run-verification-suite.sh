#!/usr/bin/env bash
# run-verification-suite.sh <worktree_path>
# The "verification team" — runs a battery of checks before a branch is
# considered acceptable:
#   1. backend pytest (if backend/ + venv present)
#   2. frontend tsc + lint + next build (if frontend/ + node_modules present)
#   3. pip check (if Python env present)
#   4. npm audit --omit=dev (if package.json present, advisory-only)
#   5. market-realism guard: scan diff for unsupported claims like
#      "bankable", "settlement-grade", "guaranteed", "live trading"
#      AGAINST public-data sources — flags as needs-review.
#   6. PZU + FR sanity probes against the running app's reality-check bounds:
#      - PZU 12mo profit must be within €100k–€800k for 10MW/20MWh
#      - FR Y1 net profit must be within €1.5M–€4.5M for 10MW/20MWh
#      - Tariff exemption Y1 must be within €150k–€350k
#      (these come from the audit doc; tighter than they look — failures here
#      mean either the model drifted or the user changed the canonical sizing.)
#
# Output: exit 0 if all green; non-zero with a structured failure list otherwise.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# Heuristic checks below tolerate grep "no match" (exit 1) — disable -e for them.
set +e

WORKTREE="${1:-$REPO_ROOT}"
SCORE=10
ISSUES=()

if [ ! -d "$WORKTREE" ]; then
  err "Worktree not found: $WORKTREE"
  exit 1
fi

# ---- 1: backend pytest ----
if [ -d "$WORKTREE/backend" ] && [ -x "$WORKTREE/backend/venv/bin/python" ]; then
  log "▶ pytest in $WORKTREE/backend"
  if ! ( cd "$WORKTREE/backend" && ./venv/bin/python -m pytest tests/ -q 2>&1 | tail -3 ); then
    SCORE=$((SCORE - 4))
    ISSUES+=("pytest_failed")
  fi
else
  warn "skipping pytest (no venv)"
fi

# ---- 2: frontend ----
if [ -d "$WORKTREE/frontend" ] && [ -d "$WORKTREE/frontend/node_modules" ]; then
  log "▶ tsc + lint + next build"
  if ! ( cd "$WORKTREE/frontend" && npx --no-install tsc --noEmit ); then
    SCORE=$((SCORE - 2)); ISSUES+=("tsc_failed")
  fi
  if ! ( cd "$WORKTREE/frontend" && npm run lint 2>&1 | tail -3 ); then
    SCORE=$((SCORE - 1)); ISSUES+=("lint_failed")
  fi
  if ! ( cd "$WORKTREE/frontend" && npx --no-install next build 2>&1 | tail -3 ); then
    SCORE=$((SCORE - 3)); ISSUES+=("next_build_failed")
  fi
else
  warn "skipping frontend (no node_modules)"
fi

# ---- 3: pip check ----
if [ -d "$WORKTREE/backend" ] && [ -x "$WORKTREE/backend/venv/bin/pip" ]; then
  log "▶ pip check"
  if ! ( cd "$WORKTREE/backend" && ./venv/bin/pip check 2>&1 | tail -5 ); then
    SCORE=$((SCORE - 1)); ISSUES+=("pip_check_failed")
  fi
fi

# ---- 4: npm audit (advisory only) ----
if [ -f "$WORKTREE/frontend/package.json" ] && command -v npm >/dev/null 2>&1; then
  log "▶ npm audit --omit=dev (advisory only)"
  if ! ( cd "$WORKTREE/frontend" && npm audit --omit=dev --audit-level=high 2>&1 | tail -5 ); then
    warn "npm audit found issues — flagged but not scored down"
    ISSUES+=("npm_audit_advisory")
  fi
fi

# ---- 5: market-realism claim guard ----
log "▶ market-realism claim guard (scan diff vs main)"
if cd "$WORKTREE" && git rev-parse --verify main >/dev/null 2>&1; then
  CLAIM_HITS="$(git diff main..HEAD -- '*.py' '*.tsx' '*.ts' '*.md' '*.json' 2>/dev/null \
    | grep -iE '\b(bankable|guaranteed|settlement-grade|live trading|live api|certified)\b' \
    | grep -v -iE '(bankability_level|settlement_export|public_market_report|public_marginal|live_api|API CONNECTED|LIVE BACKTEST)' \
    | head -10)"
  if [ -n "$CLAIM_HITS" ]; then
    SCORE=$((SCORE - 2))
    ISSUES+=("unverified_market_claims")
    warn "Found unverified market claims in diff:"
    echo "$CLAIM_HITS" | sed 's/^/    /'
  fi
fi

# ---- 6: numerical sanity (only if backend importable) ----
if [ -x "$WORKTREE/backend/venv/bin/python" ]; then
  log "▶ numerical sanity (PZU + FR + tariff exemption probe)"
  SANITY="$( cd "$WORKTREE/backend" && ./venv/bin/python <<'PY' 2>&1 || true
import sys
try:
    from app.services.pzu_service import PZUService
    from app.services.fr_service import FRService
    from app.services.investment_service import InvestmentService
    from app.services.tariff_exemption import TariffExemptionRequest, compute_tariff_exemption
    from app.models.pzu import PZUSimulationParams
    from app.models.fr import FRSimulationParams
    from app.models.investment import InvestmentParams
    from datetime import date

    issues = []

    p = PZUService().simulate(PZUSimulationParams(power_mw=10, capacity_mwh=20,
        round_trip_efficiency=0.88, start_date=date(2025,5,2), end_date=date(2026,5,1)))
    if not (100_000 <= p.total_profit_eur <= 800_000):
        issues.append(f"pzu_12mo_profit_{p.total_profit_eur:.0f}_out_of_range")

    fr = FRService().simulate(FRSimulationParams(capacity_mwh=20,
        afrr_up={"enabled":True,"power_mw":10}, afrr_down={"enabled":True,"power_mw":10},
        start_date=date(2024,10,1), end_date=date(2025,10,1)))
    months = max(1, fr.months_count)
    annual = fr.total_net_profit_eur * (12.0 / months)
    if not (1_500_000 <= annual <= 4_500_000):
        issues.append(f"fr_annual_net_{annual:.0f}_out_of_range")

    t = compute_tariff_exemption(TariffExemptionRequest(power_mw=10, capacity_mwh=20,
        cycles_per_day=1, operating_days_per_year=365))
    if not (150_000 <= t.avoided_cost_eur <= 350_000):
        issues.append(f"tariff_exemption_{t.avoided_cost_eur:.0f}_out_of_range")

    inv = InvestmentService().analyze(InvestmentParams())
    if inv.financing.annual_debt_service_eur < 0:
        issues.append("negative_debt_service")

    if issues:
        print("SANITY_FAIL:" + ",".join(issues))
        sys.exit(2)
    print("SANITY_OK")
except Exception as e:
    print(f"SANITY_ERROR:{type(e).__name__}:{e}")
    sys.exit(3)
PY
)"
  echo "$SANITY"
  case "$SANITY" in
    *SANITY_OK*)     ;;
    *SANITY_FAIL*)   SCORE=$((SCORE - 3)); ISSUES+=("market_realism_drift") ;;
    *SANITY_ERROR*)  SCORE=$((SCORE - 2)); ISSUES+=("sanity_probe_error") ;;
  esac
fi

# ---- summary ----
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Verification suite result"
echo "════════════════════════════════════════════════════════"
echo "  Worktree:  $WORKTREE"
echo "  Score:     $SCORE / 10  (acceptance threshold: 7)"
if [ "${#ISSUES[@]}" -gt 0 ]; then
  echo "  Issues:    ${ISSUES[*]}"
fi
echo "════════════════════════════════════════════════════════"

if [ "$SCORE" -lt 7 ]; then
  exit 1
fi
exit 0
