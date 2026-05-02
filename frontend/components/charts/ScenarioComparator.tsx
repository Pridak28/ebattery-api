'use client'

/**
 * ScenarioComparator — side-by-side BESS sizing comparison.
 *
 * Lets investors run 2-3 sizing scenarios (Small / Canonical / Large) against
 * the existing /investment/analyze endpoint and compare key bankability
 * metrics in one table. Best value per row is highlighted green, worst amber,
 * so the trade-off between CAPEX and IRR / payback is visible at a glance.
 *
 * Self-contained: no props. Safe to drop into any page as a collapsible section.
 */

import { useState } from 'react'
import { investmentApi } from '@/lib/api'
import { formatCompact } from '@/lib/utils'

type ScenarioInput = {
  id: string
  name: string
  power_mw: number
  capacity_mwh: number
  total_investment_eur: number
  equity_percentage: number
  loan_term_years: number
}

type AnalyzeData = {
  fr_scenario?: { net_profit_after_debt_eur?: number }
  pzu_scenario?: { net_profit_after_debt_eur?: number }
  fr_lifetime_irr_pct?: number | null
  pzu_lifetime_irr_pct?: number | null
  fr_lifetime_payback_years?: number | null
  pzu_lifetime_payback_years?: number | null
  dscr_violation_years?: number[]
  recommended_scenario?: string
}

type ScenarioResult = { loading: boolean; error: string | null; data: AnalyzeData | null }

const DEFAULT_SCENARIOS: ScenarioInput[] = [
  { id: 'small', name: 'Small (5MW/10MWh)', power_mw: 5, capacity_mwh: 10,
    total_investment_eur: 1_750_000, equity_percentage: 30, loan_term_years: 10 },
  { id: 'canonical', name: 'Canonical (10MW/20MWh)', power_mw: 10, capacity_mwh: 20,
    total_investment_eur: 3_500_000, equity_percentage: 30, loan_term_years: 10 },
  { id: 'large', name: 'Large (20MW/40MWh)', power_mw: 20, capacity_mwh: 40,
    total_investment_eur: 7_000_000, equity_percentage: 30, loan_term_years: 10 },
]

// Loan defaults for the analyze() call — match the page's bankability assumptions.
const ANALYZE_DEFAULTS = { loan_interest_rate: 6, opex_percentage: 2, insurance_percentage: 0.5 }

type Direction = 'higher-better' | 'lower-better'

type Row = {
  key: string
  label: string
  direction: Direction | null // null => no highlight (e.g. recommended)
  values: (number | null)[]
  format: (v: number | null) => string
}

const fmtPct = (v: number | null) =>
  v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(1)}%`
const fmtYears = (v: number | null) =>
  v == null || !Number.isFinite(v) ? 'never' : `${v.toFixed(1)} yr`
const fmtCount = (v: number | null) => (v == null ? '—' : v.toString())
const fmtEur = (v: number | null) =>
  v == null || !Number.isFinite(v) ? '—' : formatCompact(v)

// Best/worst classification across a row. Skips nulls; if all values equal, no highlight.
function classify(values: (number | null)[], direction: Direction): ('best' | 'worst' | null)[] {
  const valid = values
    .map((v, i) => ({ v, i }))
    .filter((p): p is { v: number; i: number } => p.v != null && Number.isFinite(p.v))
  if (valid.length < 2) return values.map(() => null)
  const nums = valid.map((p) => p.v)
  const max = Math.max(...nums)
  const min = Math.min(...nums)
  const best = direction === 'higher-better' ? max : min
  const worst = direction === 'higher-better' ? min : max
  if (best === worst) return values.map(() => null)
  return values.map((v) => {
    if (v == null || !Number.isFinite(v)) return null
    if (v === best) return 'best'
    if (v === worst) return 'worst'
    return null
  })
}

export function ScenarioComparator() {
  const [scenarios] = useState<ScenarioInput[]>(DEFAULT_SCENARIOS)
  const [results, setResults] = useState<Record<string, ScenarioResult>>(() =>
    Object.fromEntries(DEFAULT_SCENARIOS.map((s) => [s.id, { loading: false, error: null, data: null }])),
  )

  const runOne = async (scenario: ScenarioInput) => {
    setResults((prev) => ({
      ...prev,
      [scenario.id]: { loading: true, error: null, data: prev[scenario.id]?.data ?? null },
    }))
    try {
      const res = await investmentApi.analyze({
        total_investment_eur: scenario.total_investment_eur,
        equity_percentage: scenario.equity_percentage,
        loan_interest_rate: ANALYZE_DEFAULTS.loan_interest_rate,
        loan_term_years: scenario.loan_term_years,
        opex_percentage: ANALYZE_DEFAULTS.opex_percentage,
        insurance_percentage: ANALYZE_DEFAULTS.insurance_percentage,
        power_mw: scenario.power_mw,
        capacity_mwh: scenario.capacity_mwh,
      })
      setResults((prev) => ({ ...prev, [scenario.id]: { loading: false, error: null, data: res.data } }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Analyze failed'
      setResults((prev) => ({ ...prev, [scenario.id]: { loading: false, error: message, data: null } }))
    }
  }

  const runAll = () => { scenarios.forEach((s) => { void runOne(s) }) }

  const rows: Row[] = [
    { key: 'fr-y1', label: 'FR Y1 net profit', direction: 'higher-better',
      values: scenarios.map((s) => results[s.id]?.data?.fr_scenario?.net_profit_after_debt_eur ?? null),
      format: fmtEur },
    { key: 'pzu-y1', label: 'PZU Y1 net profit', direction: 'higher-better',
      values: scenarios.map((s) => results[s.id]?.data?.pzu_scenario?.net_profit_after_debt_eur ?? null),
      format: fmtEur },
    { key: 'fr-irr', label: 'FR lifetime IRR', direction: 'higher-better',
      values: scenarios.map((s) => results[s.id]?.data?.fr_lifetime_irr_pct ?? null),
      format: fmtPct },
    { key: 'pzu-irr', label: 'PZU lifetime IRR', direction: 'higher-better',
      values: scenarios.map((s) => results[s.id]?.data?.pzu_lifetime_irr_pct ?? null),
      format: fmtPct },
    // FR is the page's headline payback — use it here for the cross-scenario view.
    { key: 'payback', label: 'Lifetime payback', direction: 'lower-better',
      values: scenarios.map((s) => results[s.id]?.data?.fr_lifetime_payback_years ?? null),
      format: fmtYears },
    { key: 'dscr', label: 'DSCR violations', direction: 'lower-better',
      values: scenarios.map((s) => {
        const v = results[s.id]?.data?.dscr_violation_years
        return Array.isArray(v) ? v.length : null
      }),
      format: fmtCount },
    { key: 'rec', label: 'Recommended', direction: null,
      values: scenarios.map(() => null), format: () => '' },
  ]

  const anyLoading = scenarios.some((s) => results[s.id]?.loading)

  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 p-4">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-mono uppercase text-slate-300">Sizing scenario comparator</h3>
          <p className="text-[11px] text-slate-400">
            Compare 2-3 BESS sizing options side-by-side. Best value per row in green, worst in amber.
          </p>
        </div>
        <button
          type="button"
          onClick={runAll}
          disabled={anyLoading}
          className="rounded bg-[#00ffd1] px-3 py-1 text-xs font-mono uppercase text-slate-900 hover:bg-[#00d4aa] disabled:opacity-50"
        >
          {anyLoading ? 'Running…' : 'Run all'}
        </button>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {scenarios.map((s) => {
          const r = results[s.id]
          return (
            <div key={s.id} className="rounded border border-slate-700 bg-slate-900/60 p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-white">{s.name}</p>
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    {formatCompact(s.total_investment_eur)} · {s.equity_percentage}% eq · {s.loan_term_years}yr
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void runOne(s)}
                  disabled={r?.loading}
                  className="rounded border border-[#00ffd1]/40 px-2 py-0.5 text-[10px] font-mono uppercase text-[#00ffd1] hover:bg-[#00ffd1]/10 disabled:opacity-50"
                >
                  {r?.loading ? '…' : 'Run'}
                </button>
              </div>
              {r?.error && <p className="mt-2 text-[10px] text-rose-300">{r.error}</p>}
              {!r?.error && r?.loading && <p className="mt-2 text-[10px] text-slate-400">Analyzing…</p>}
              {!r?.error && !r?.loading && r?.data && <p className="mt-2 text-[10px] text-emerald-300">Done</p>}
            </div>
          )
        })}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-700 text-left">
              <th className="px-2 py-2 font-mono uppercase text-slate-400">Metric</th>
              {scenarios.map((s) => (
                <th key={s.id} className="px-2 py-2 text-right font-mono uppercase text-slate-400">{s.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const classes = row.direction == null
                ? row.values.map(() => null)
                : classify(row.values, row.direction)
              return (
                <tr key={row.key} className="border-b border-slate-800">
                  <td className="px-2 py-2 text-slate-300">{row.label}</td>
                  {row.values.map((v, i) => {
                    if (row.key === 'rec') {
                      const rec = results[scenarios[i].id]?.data?.recommended_scenario
                      return (
                        <td key={i} className="px-2 py-2 text-right font-mono text-slate-200">
                          {rec ?? '—'}
                        </td>
                      )
                    }
                    const cls = classes[i]
                    const color = cls === 'best' ? 'text-emerald-300'
                      : cls === 'worst' ? 'text-amber-300'
                      : 'text-slate-200'
                    return (
                      <td key={i} className={`px-2 py-2 text-right font-mono ${color}`}>
                        {row.format(v)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[10px] text-slate-400">
        Uses /investment/analyze with {ANALYZE_DEFAULTS.loan_interest_rate}% rate,
        {' '}{ANALYZE_DEFAULTS.opex_percentage}% OPEX, {ANALYZE_DEFAULTS.insurance_percentage}% insurance.
      </p>
    </div>
  )
}

export default ScenarioComparator
