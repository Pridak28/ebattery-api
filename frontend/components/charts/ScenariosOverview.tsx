'use client'

/**
 * ScenariosOverview — investor-facing card that calls /investment/scenarios
 * and renders the 4 PICASSO/market-share scenarios (Modeled vs Realistic).
 *
 * Mirrors the offline Excel `BESS_Financial_Model_BANK_6tabs_*.xlsx`:
 * each row shows a scenario, its modeled (engineering-optimum) IRR/Y1
 * revenue, and the realistic (operator drag + tax + depreciation)
 * version a lender would underwrite. Source label is "Public-data /
 * Backtest-only" — NOT bankable without participant settlement.
 */
import { useEffect, useState } from 'react'
import { investmentApi } from '@/lib/api'

type KPIs = {
  y1_revenue_eur: number | null
  y1_ebitda_eur: number | null
  y1_ebitda_margin_pct: number | null
  y1_equity_fcf_eur: number | null
  equity_irr_pct: number | null
  project_irr_pct: number | null
  equity_mirr_pct: number | null
  moic: number | null
  equity_payback_years: number | null
  equity_discounted_payback_years: number | null
  equity_npv_8_eur: number | null
  min_dscr: number | null
  avg_dscr: number | null
  llcr: number | null
  plcr: number | null
  dscr_breach_years: number[]
}

type ScenarioResult = {
  scenario_key: string
  label: string
  color: string
  description: string
  modeled: { kpis: KPIs }
  realistic: { kpis: KPIs }
}

type ScenariosResponse = {
  inputs: Record<string, number>
  scenarios: ScenarioResult[]
  bankability_label: string
  source_note: string
}

const fmtEur = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return 'n/a'
  if (Math.abs(v) >= 1_000_000) return `€${(v / 1_000_000).toFixed(2)}M`
  if (Math.abs(v) >= 1_000) return `€${Math.round(v / 1_000)}k`
  return `€${Math.round(v)}`
}
const fmtPct = (v: number | null | undefined): string =>
  v === null || v === undefined ? 'n/a' : `${v.toFixed(2)}%`
const fmtYr = (v: number | null | undefined): string =>
  v === null || v === undefined ? 'never' : `${v.toFixed(1)} yr`
const fmtX = (v: number | null | undefined): string =>
  v === null || v === undefined ? 'n/a' : `${v.toFixed(2)}x`

export function ScenariosOverview() {
  const [data, setData] = useState<ScenariosResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    investmentApi
      .scenarios({})
      .then((res) => {
        if (cancelled) return
        setData(res.data as ScenariosResponse)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err?.message ?? String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return (
      <div className="rounded border border-slate-700 bg-slate-800/40 p-6 text-sm text-slate-400">
        Loading scenarios…
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="rounded border border-red-700 bg-red-900/20 p-6 text-sm text-red-300">
        Could not load scenarios: {error ?? 'unknown error'}
      </div>
    )
  }

  const colorMap: Record<string, string> = {
    A_current: 'border-blue-500/40 bg-blue-500/5',
    B_picasso: 'border-orange-500/40 bg-orange-500/5',
    C_mature: 'border-yellow-500/40 bg-yellow-500/5',
    D_bear: 'border-red-500/40 bg-red-500/5',
  }

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-mono uppercase text-slate-300">
          Scenario engine — 4 cases (Modeled vs Realistic)
        </h3>
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono uppercase text-amber-300">
          {data.bankability_label}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {data.scenarios.map((s) => {
          const m = s.modeled.kpis
          const r = s.realistic.kpis
          const dscrOk = (r.min_dscr ?? 0) >= 1.2
          return (
            <div
              key={s.scenario_key}
              className={`rounded border p-3 text-xs ${colorMap[s.scenario_key] ?? ''}`}
            >
              <div className="mb-2 font-mono uppercase text-slate-200">{s.label}</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-400">
                <div>
                  <div className="text-[10px] uppercase text-slate-500">
                    Modeled (engineering)
                  </div>
                  <div className="text-slate-300">
                    Y1 {fmtEur(m.y1_revenue_eur)} · IRR {fmtPct(m.equity_irr_pct)}
                  </div>
                  <div className="text-slate-500">
                    Payback {fmtYr(m.equity_payback_years)}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase text-emerald-400">
                    Realistic (lender-grade)
                  </div>
                  <div className="text-emerald-300">
                    Y1 {fmtEur(r.y1_revenue_eur)} · IRR {fmtPct(r.equity_irr_pct)}
                  </div>
                  <div className="text-slate-400">
                    Payback {fmtYr(r.equity_payback_years)} · MOIC {fmtX(r.moic)}
                  </div>
                </div>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 border-t border-slate-700/50 pt-2 text-[10px]">
                <div>
                  <div className="text-slate-500">Min DSCR</div>
                  <div className={dscrOk ? 'text-emerald-300' : 'text-red-300'}>
                    {fmtX(r.min_dscr)}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">LLCR</div>
                  <div className="text-slate-300">{fmtX(r.llcr)}</div>
                </div>
                <div>
                  <div className="text-slate-500">PLCR</div>
                  <div className="text-slate-300">{fmtX(r.plcr)}</div>
                </div>
              </div>
              {r.dscr_breach_years && r.dscr_breach_years.length > 0 && (
                <div className="mt-2 rounded border border-red-500/40 bg-red-900/20 px-2 py-1 text-[10px] text-red-300">
                  ⚠ DSCR &lt; 1.20 in years: {r.dscr_breach_years.join(', ')} — covenant breach
                </div>
              )}
            </div>
          )
        })}
      </div>

      <p className="mt-3 text-[10px] text-slate-500">
        {data.source_note} Source: app/services/scenario_engine.py — same logic as
        backend/scripts/bess_cashflow_scenarios_excel.py.
      </p>
    </div>
  )
}

export default ScenariosOverview
