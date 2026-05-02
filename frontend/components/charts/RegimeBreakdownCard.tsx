'use client'

/**
 * RegimeBreakdownCard — surfaces the FRSimulationResponse.regime_breakdowns
 * (A-1 fix). Pre/post ANRE Order 60/2024 split with side-by-side comparison
 * so investors see how much of the headline number depends on the
 * pre-pay-as-bid regime vs the regime that actually applies to new builds.
 */

import { Calendar, ArrowRight } from 'lucide-react'

type Breakdown = {
  regime: 'pre_order60_2024_marginal' | 'post_order60_2024_pay_as_bid'
  row_count: number
  months_count: number
  capacity_revenue_eur: number
  activation_revenue_eur: number
  total_revenue_eur: number
  energy_cost_eur: number
  net_profit_eur: number
  avg_activation_price_up_eur_mwh: number
  avg_activation_price_down_eur_mwh: number
}

const REGIME_LABEL: Record<string, string> = {
  pre_order60_2024_marginal: 'Pre Order 60/2024 (marginal)',
  post_order60_2024_pay_as_bid: 'Post Order 60/2024 (pay-as-bid)',
}

const REGIME_DESC: Record<string, string> = {
  pre_order60_2024_marginal:
    'Marginal-pricing regime before 2024-10-01. Operators were paid the highest accepted bid, leading to extreme spikes (>€10k/MWh seen in Sept 2024).',
  post_order60_2024_pay_as_bid:
    'Pay-as-bid regime from 2024-10-01. Operators paid their own bid. Use this slice for new-build underwriting.',
}

const fmtEur = (v: number) =>
  v >= 1_000_000 ? `€${(v / 1_000_000).toFixed(2)}M`
  : v >= 1_000 ? `€${(v / 1_000).toFixed(0)}k`
  : `€${v.toFixed(0)}`

export function RegimeBreakdownCard({
  breakdowns,
  className = '',
}: {
  breakdowns?: Breakdown[]
  className?: string
}) {
  if (!breakdowns || breakdowns.length === 0) return null

  // Sort: post first (the one investors care about), pre second.
  const sorted = [...breakdowns].sort((a, b) => {
    if (a.regime === 'post_order60_2024_pay_as_bid') return -1
    if (b.regime === 'post_order60_2024_pay_as_bid') return 1
    return 0
  })

  const showWarning = breakdowns.length > 1

  return (
    <div className={`rounded-lg border border-slate-700 bg-slate-900/50 ${className}`}>
      <div className="flex items-center gap-2 px-3 sm:px-4 py-2 sm:py-3 border-b border-slate-700">
        <Calendar className="w-4 h-4 text-[#00ffd1]" />
        <h3 className="text-xs sm:text-sm font-semibold uppercase tracking-wider text-slate-300">
          Regulatory Regime Split
        </h3>
        {showWarning && (
          <span className="ml-auto text-[10px] font-mono uppercase rounded px-1.5 py-0.5 bg-amber-500/15 text-amber-300">
            mixed window
          </span>
        )}
      </div>

      <div className="p-3 sm:p-4 grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4">
        {sorted.map((b) => (
          <div
            key={b.regime}
            className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 sm:p-4"
          >
            <p className="text-xs sm:text-sm font-medium text-slate-200 mb-1">
              {REGIME_LABEL[b.regime]}
            </p>
            <p className="text-[10px] sm:text-[11px] text-slate-400 mb-3 leading-snug">
              {REGIME_DESC[b.regime]}
            </p>

            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] sm:text-xs">
              <dt className="text-slate-400">rows</dt>
              <dd className="font-mono text-slate-300 text-right">{b.row_count.toLocaleString()}</dd>

              <dt className="text-slate-400">months</dt>
              <dd className="font-mono text-slate-300 text-right">{b.months_count}</dd>

              <dt className="text-slate-400">capacity rev</dt>
              <dd className="font-mono text-emerald-300 text-right">{fmtEur(b.capacity_revenue_eur)}</dd>

              <dt className="text-slate-400">activation rev</dt>
              <dd className="font-mono text-emerald-300 text-right">{fmtEur(b.activation_revenue_eur)}</dd>

              <dt className="text-slate-400">net profit</dt>
              <dd className="font-mono text-emerald-200 text-right font-semibold">{fmtEur(b.net_profit_eur)}</dd>

              <dt className="text-slate-400 col-span-2 mt-2 pt-2 border-t border-slate-800 text-[10px] uppercase tracking-wider">
                avg prices €/MWh
              </dt>

              <dt className="text-slate-400">aFRR up</dt>
              <dd className="font-mono text-amber-300 text-right">€{b.avg_activation_price_up_eur_mwh.toFixed(0)}</dd>

              <dt className="text-slate-400">aFRR down</dt>
              <dd className={`font-mono text-right ${b.avg_activation_price_down_eur_mwh < 0 ? 'text-emerald-300' : 'text-amber-300'}`}>
                €{b.avg_activation_price_down_eur_mwh.toFixed(0)}
              </dd>
            </dl>
          </div>
        ))}
      </div>

      {showWarning && (
        <div className="px-3 sm:px-4 py-2 sm:py-3 border-t border-slate-700 bg-amber-500/5">
          <p className="text-[10px] sm:text-[11px] text-amber-200/80 flex items-start gap-1.5">
            <ArrowRight className="w-3 h-3 mt-0.5 flex-shrink-0" />
            <span>
              The aggregate revenue mixes two regulatory regimes with materially
              different settlement mechanics. For investor underwriting, restrict
              the simulation window to <span className="font-mono">post_order60_2024_pay_as_bid</span> only.
            </span>
          </p>
        </div>
      )}
    </div>
  )
}

export default RegimeBreakdownCard
