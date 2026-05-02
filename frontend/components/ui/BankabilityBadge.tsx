'use client'

/**
 * BankabilityBadge — surfaces a FRSimulationResponse's bankability provenance
 * at the top of the simulator results so investors can't miss it.
 *
 * Shows: bankability_level, settlement_grade, source_kind, max date,
 * and a one-line bankability_summary if present.
 */

import { ShieldAlert, ShieldCheck, Info } from 'lucide-react'

type Props = {
  bankabilityLevel?: string
  settlementGrade?: boolean
  sourceKind?: string
  dataDateMax?: string | null
  bankabilitySummary?: string
  className?: string
}

const COLOR_BY_LEVEL: Record<string, { bg: string; ring: string; text: string; icon: typeof ShieldCheck }> = {
  bankable_settlement_grade: { bg: 'bg-emerald-500/10', ring: 'ring-emerald-500/30', text: 'text-emerald-300', icon: ShieldCheck },
  participant_only_for_bankability: { bg: 'bg-blue-500/10', ring: 'ring-blue-500/30', text: 'text-blue-300', icon: Info },
  scenario_public_market_only: { bg: 'bg-amber-500/10', ring: 'ring-amber-500/30', text: 'text-amber-300', icon: ShieldAlert },
  historical_backtest_only: { bg: 'bg-amber-500/10', ring: 'ring-amber-500/30', text: 'text-amber-300', icon: ShieldAlert },
}

export function BankabilityBadge({
  bankabilityLevel,
  settlementGrade,
  sourceKind,
  dataDateMax,
  bankabilitySummary,
  className = '',
}: Props) {
  if (!bankabilityLevel && !sourceKind) return null

  const level = bankabilityLevel ?? 'historical_backtest_only'
  const style = COLOR_BY_LEVEL[level] ?? COLOR_BY_LEVEL.historical_backtest_only
  const Icon = style.icon

  return (
    <div
      className={`rounded-lg border ring-1 ${style.bg} ${style.ring} p-3 sm:p-4 ${className}`}
      role="status"
    >
      <div className="flex items-start gap-2 sm:gap-3">
        <Icon className={`w-4 h-4 sm:w-5 sm:h-5 mt-0.5 flex-shrink-0 ${style.text}`} />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className={`text-xs sm:text-sm font-mono font-bold uppercase tracking-wider ${style.text}`}>
              {level.replace(/_/g, ' ')}
            </span>
            {settlementGrade != null && (
              <span
                className={`text-[10px] font-mono uppercase rounded px-1.5 py-0.5 ${
                  settlementGrade
                    ? 'bg-emerald-500/15 text-emerald-300'
                    : 'bg-slate-500/15 text-slate-300'
                }`}
              >
                {settlementGrade ? 'settlement-grade ✓' : 'NOT settlement-grade'}
              </span>
            )}
          </div>
          {bankabilitySummary && (
            <p className="text-[11px] sm:text-xs font-mono text-slate-400 break-all">
              {bankabilitySummary}
            </p>
          )}
          <p className="text-[10px] sm:text-[11px] text-slate-400 mt-1">
            source: <span className="font-mono">{sourceKind ?? 'unknown'}</span>
            {dataDateMax && (
              <>
                {' · '}
                latest data: <span className="font-mono">{dataDateMax}</span>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

export default BankabilityBadge
