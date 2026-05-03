'use client'

/**
 * FRProductBreakdown — stacked-bar chart of capacity vs activation revenue
 * per FR product (aFRR / mFRR / FCR). Phase E1+E2 (gap audit 2026-05-01).
 *
 * Capacity revenue is paid 24/7 for being available; activation revenue
 * is paid only when called. Romanian aFRR + mFRR settle pay-as-bid (since
 * ANRE Order 60/2024); FCR remains marginal-priced.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type FRProductRow = {
  product: 'aFRR' | 'mFRR' | 'FCR'
  capacity_revenue_eur: number
  activation_revenue_eur: number
  energy_cost_eur: number
  net_revenue_eur: number
  capacity_eur_mw_h: number
  settlement: 'pay_as_bid' | 'marginal'
  activated_mwh: number
  avg_activation_price_eur_mwh: number
  min_bid_mw: number
  symmetric: boolean
  pricing_basis: string
  confidence_label: string
}

const fmtEur = (n: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(n)

export function FRProductBreakdown({ data }: { data: FRProductRow[] }) {
  if (!data?.length) {
    return (
      <div className="rounded border border-slate-700 bg-slate-800/40 p-6 text-sm text-slate-400">
        No FR products selected.
      </div>
    )
  }

  const rows = data.map((p) => ({
    product: p.product,
    Capacity: Math.round(p.capacity_revenue_eur),
    Activation: Math.round(p.activation_revenue_eur),
    EnergyCost: -Math.round(p.energy_cost_eur),
    Net: Math.round(p.net_revenue_eur),
    settlement: p.settlement,
  }))

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-mono uppercase text-slate-300">
          FR product revenue split
        </h3>
        <span className="text-[10px] text-slate-400">
          Capacity (paid 24/7) + Activation (paid when called)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="product" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" tickFormatter={(v) => fmtEur(v as number)} width={90} />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0f172a',
              border: '1px solid #334155',
              fontSize: 12,
            }}
            formatter={(v: number, key) => [fmtEur(v), key]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Capacity" stackId="rev" fill="#10b981" />
          <Bar dataKey="Activation" stackId="rev" fill="#3b82f6" />
          <Bar dataKey="EnergyCost" fill="#ef4444" />
          <Bar dataKey="Net" fill="#a855f7" />
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        {data.map((p) => (
          <div
            key={p.product}
            className="rounded border border-slate-700 bg-slate-900/50 p-2"
          >
            <div className="font-mono uppercase text-slate-300">{p.product}</div>
            <div className="text-slate-400">
              {p.settlement.replace('_', '-')} · {fmtEur(p.capacity_eur_mw_h)}/MW/h
              {p.product === 'aFRR' && (
                <span className="ml-1 text-[10px] uppercase text-amber-300">
                  DAMAS sample
                </span>
              )}
            </div>
            <div className="mt-1 text-slate-400">
              Min bid: {p.min_bid_mw} MW · {p.symmetric ? 'symmetric' : 'directional'}
            </div>
            <div className="mt-1 text-emerald-300">{fmtEur(p.net_revenue_eur)} net</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-slate-500">
        aFRR capacity rate = mean of recent DAMAS public-tender clearing samples
        (NOT bankable — participant settlement required for bankable mode).
      </p>
    </div>
  )
}

export default FRProductBreakdown
