'use client'

/**
 * LiveMarketChart — replaces the dashboard's hardcoded MARKET_DATA fake series
 * with real per-month PZU + FR revenue pulled from the API. Falls back to a
 * skeleton on load and an error band on failure (instead of theatre).
 *
 * - PZU: /api/v1/pzu/monthly-summary
 * - FR : /api/v1/fr/monthly-breakdown (aFRR+)
 *
 * Both feed into a single ComposedChart (Area aFRR / Area PZU / Line price).
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TrendingUp } from 'lucide-react'
import { pzuApi, frApi } from '@/lib/api'
import StatusLabel from '@/components/ui/StatusLabel'

type MergedRow = {
  month: string          // 'YYYY-MM'
  monthShort: string     // 'Jan'
  pzu: number            // kEUR (PZU net profit)
  afrr: number           // kEUR (aFRR+ total revenue, scaled)
  price: number          // EUR/MWh (avg sell price PZU)
}

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; rows: MergedRow[]; totals: { pzu: number; afrr: number; combined: number; avgPrice: number } }

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function lastNMonthsKeys(n: number, today = new Date()): string[] {
  const out: string[] = []
  const y = today.getFullYear()
  const m = today.getMonth() // 0-based
  for (let i = n - 1; i >= 0; i--) {
    const dt = new Date(y, m - i, 1)
    const yy = dt.getFullYear()
    const mm = String(dt.getMonth() + 1).padStart(2, '0')
    out.push(`${yy}-${mm}`)
  }
  return out
}

export function LiveMarketChart({ className = '' }: { className?: string }) {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const today = new Date()
    const wantedKeys = lastNMonthsKeys(12, today)

    Promise.all([
      pzuApi.getMonthlySummary({ power_mw: 10, capacity_mwh: 20, efficiency: 0.88, year: today.getFullYear() }),
      frApi.getMonthlyBreakdown({ product: 'aFRR+' }),
    ])
      .then(([pzuRes, frRes]) => {
        if (cancelled) return
        const pzuMonths: any[] = pzuRes.data?.monthly_results ?? []
        const frMonths: any[] = frRes.data?.monthly_results ?? []
        const pzuByMonth: Record<string, any> = {}
        for (const m of pzuMonths) pzuByMonth[m.month] = m
        const frByMonth: Record<string, any> = {}
        for (const m of frMonths) frByMonth[m.month] = m

        const rows: MergedRow[] = wantedKeys.map((key) => {
          const p = pzuByMonth[key]
          const f = frByMonth[key]
          const monthIdx = Number(key.slice(5, 7)) - 1
          return {
            month: key,
            monthShort: MONTH_LABELS[monthIdx] ?? key,
            pzu: p ? Number(p.net_profit_eur) / 1000 : 0,
            afrr: f ? Number(f.total_revenue_eur) / 1000 : 0,
            price: p ? Number(p.avg_sell_price_eur_mwh) : 0,
          }
        })

        const totals = rows.reduce(
          (acc, r) => ({
            pzu: acc.pzu + r.pzu,
            afrr: acc.afrr + r.afrr,
            combined: acc.combined + r.pzu + r.afrr,
            priceSum: acc.priceSum + (r.price > 0 ? r.price : 0),
            priceCount: acc.priceCount + (r.price > 0 ? 1 : 0),
          }),
          { pzu: 0, afrr: 0, combined: 0, priceSum: 0, priceCount: 0 },
        )

        setState({
          kind: 'ready',
          rows,
          totals: {
            pzu: totals.pzu,
            afrr: totals.afrr,
            combined: totals.combined,
            avgPrice: totals.priceCount > 0 ? totals.priceSum / totals.priceCount : 0,
          },
        })
      })
      .catch((err) => {
        if (cancelled) return
        setState({ kind: 'error', message: err?.message ?? 'unknown error' })
      })

    return () => {
      cancelled = true
    }
  }, [])

  const fmtKEur = (v: number) => `€${v.toFixed(0)}K`
  const fmtMEur = (v: number) => (v >= 1000 ? `€${(v / 1000).toFixed(2)}M` : `€${v.toFixed(0)}K`)

  return (
    <div className={`bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg sm:rounded-xl overflow-hidden ${className}`}>
      <div className="px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
            <TrendingUp className="w-4 h-4 sm:w-5 sm:h-5 text-slate-900" />
          </div>
          <div>
            <h2 className="text-sm sm:text-lg font-semibold text-white">Last 12 months — Real Market Backtest</h2>
            <p className="text-[10px] sm:text-xs text-slate-400">10 MW / 20 MWh BESS · OPCOM PZU + DAMAS aFRR · live API</p>
          </div>
        </div>
        <StatusLabel kind="HISTORICAL" label="LIVE BACKTEST" />
      </div>

      <div className="p-3 sm:p-5">
        <div className="h-56 sm:h-80">
          {state.kind === 'loading' && (
            <div className="h-full flex flex-col gap-3 justify-center px-4" aria-busy="true">
              <div className="h-3 bg-slate-800 rounded animate-pulse w-2/3" />
              <div className="h-3 bg-slate-800 rounded animate-pulse w-1/2" />
              <div className="h-32 bg-slate-800/50 rounded animate-pulse" />
              <p className="text-xs text-slate-400 text-center">Loading 12-month backtest…</p>
            </div>
          )}
          {state.kind === 'error' && (
            <div className="h-full flex flex-col items-center justify-center gap-2 px-4">
              <div className="text-sm text-amber-300">Live data unavailable.</div>
              <div className="text-[11px] text-slate-400 text-center max-w-md">
                Backend may be sleeping or offline. Run `uvicorn app.main:app` and refresh. Error: {state.message}
              </div>
            </div>
          )}
          {state.kind === 'ready' && (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={state.rows} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <defs>
                  <linearGradient id="afrrGradientLive" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00ffd1" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#00ffd1" stopOpacity={0.1} />
                  </linearGradient>
                  <linearGradient id="pzuGradientLive" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0.1} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                <XAxis dataKey="monthShort" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={{ stroke: '#334155' }} />
                <YAxis
                  yAxisId="left"
                  tick={{ fill: '#64748b', fontSize: 11 }}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={fmtKEur}
                  label={{ value: 'Revenue (€K)', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 10 }}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fill: '#f59e0b', fontSize: 11 }}
                  axisLine={{ stroke: '#f59e0b', strokeOpacity: 0.5 }}
                  tickFormatter={(v) => `${v}€`}
                  label={{ value: 'PZU sell €/MWh', angle: 90, position: 'insideRight', fill: '#f59e0b', fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    boxShadow: '0 10px 40px rgba(0,0,0,0.5)',
                  }}
                  labelStyle={{ color: '#e2e8f0', fontWeight: 'bold', marginBottom: '8px' }}
                  itemStyle={{ color: '#94a3b8', fontSize: '12px' }}
                  formatter={(value: number, name: string) => {
                    if (name === 'afrr') return [`€${value.toFixed(0)}K`, 'aFRR+ Revenue']
                    if (name === 'pzu') return [`€${value.toFixed(0)}K`, 'PZU Net Profit']
                    if (name === 'price') return [`${value.toFixed(0)} €/MWh`, 'PZU avg sell price']
                    return [value, name]
                  }}
                />
                <Legend wrapperStyle={{ paddingTop: '20px' }} />
                <Area yAxisId="left" type="monotone" dataKey="afrr" stroke="#00ffd1" strokeWidth={2} fill="url(#afrrGradientLive)" name="afrr" />
                <Area yAxisId="left" type="monotone" dataKey="pzu" stroke="#2563eb" strokeWidth={2} fill="url(#pzuGradientLive)" name="pzu" />
                <Line yAxisId="right" type="monotone" dataKey="price" stroke="#f59e0b" strokeWidth={2.5} dot={{ fill: '#f59e0b', strokeWidth: 2, r: 3 }} name="price" />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {state.kind === 'ready' && (
          <div className="mt-3 sm:mt-4 pt-3 sm:pt-4 border-t border-slate-700">
            <div className="flex items-center justify-end mb-2">
              <StatusLabel kind="LIVE_API" label="LIVE 12-MO BACKTEST" />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-4">
              <div className="text-center">
                <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400">12-mo aFRR</p>
                <p className="text-base sm:text-lg font-bold text-[#00ffd1] font-mono">{fmtMEur(state.totals.afrr)}</p>
              </div>
              <div className="text-center">
                <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400">12-mo PZU</p>
                <p className="text-base sm:text-lg font-bold text-blue-400 font-mono">{fmtMEur(state.totals.pzu)}</p>
              </div>
              <div className="text-center">
                <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400">Combined</p>
                <p className="text-base sm:text-lg font-bold text-emerald-400 font-mono">{fmtMEur(state.totals.combined)}</p>
              </div>
              <div className="text-center">
                <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400">Avg sell €/MWh</p>
                <p className="text-base sm:text-lg font-bold text-amber-400 font-mono">{state.totals.avgPrice.toFixed(0)}€</p>
              </div>
            </div>
            <p className="text-[10px] text-slate-400 mt-2 text-center">
              From real OPCOM + DAMAS data · {state.rows.length} months · 10 MW / 20 MWh canonical sizing
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

export default LiveMarketChart
