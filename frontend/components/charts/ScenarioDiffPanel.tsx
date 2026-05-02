'use client'

/**
 * ScenarioDiffPanel — 2-way A/B diff between two saved analysis runs.
 *
 * Companion to ScenarioComparator. Where the comparator iterates over fixed
 * sizing presets, this panel takes any two `InvestmentComparisonResponse`
 * payloads (slot A, slot B) and surfaces the per-metric delta. Useful when
 * an investor tweaks a single parameter (CAPEX +20%, equity 30→50, etc.) and
 * needs to see exactly which downstream numbers move and by how much.
 *
 * Self-contained, no new deps. Renders an empty state when either slot is null.
 */

import { ArrowRight } from 'lucide-react'
import { formatCompact, formatPercentage } from '@/lib/utils'

type AnyAnalysis = any | null

export type ScenarioDiffPanelProps = {
  analysisA: AnyAnalysis
  analysisB: AnyAnalysis
  nameA?: string
  nameB?: string
  className?: string
}

type Direction = 'higher-better' | 'lower-better'

type NumericRow = {
  kind: 'num'
  key: string
  label: string
  direction: Direction
  format: (v: number) => string
  pickA: number | null
  pickB: number | null
}

type StringRow = {
  kind: 'str'
  key: string
  label: string
  pickA: string | null
  pickB: string | null
}

type Row = NumericRow | StringRow

const EM_DASH = '—'

// Safe path getter that tolerates null/undefined at any depth.
function getPath(obj: any, path: string): unknown {
  if (obj == null) return null
  let cur: any = obj
  for (const p of path.split('.')) {
    if (cur == null) return null
    cur = cur[p]
  }
  return cur ?? null
}

function getNum(obj: any, path: string): number | null {
  const v = getPath(obj, path)
  if (v == null) return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

function getStr(obj: any, path: string): string | null {
  const v = getPath(obj, path)
  return v == null ? null : String(v)
}

function getArrayLen(obj: any, path: string): number | null {
  const v = getPath(obj, path)
  return Array.isArray(v) ? v.length : null
}

const fmtEur = (v: number) => formatCompact(v)
const fmtPct = (v: number) => `${v.toFixed(1)}%`
const fmtYears = (v: number) => `${v.toFixed(1)} yr`
const fmtCount = (v: number) => v.toString()

// [key, label, path, direction, format] — driven by NumericSpec for terseness.
type NumericSpec = [string, string, string, Direction, (v: number) => string]

const NUMERIC_SPECS: NumericSpec[] = [
  ['fr_y1_net', 'FR Y1 Net Profit', 'fr_scenario.net_profit_after_debt_eur', 'higher-better', fmtEur],
  ['pzu_y1_net', 'PZU Y1 Net Profit', 'pzu_scenario.net_profit_after_debt_eur', 'higher-better', fmtEur],
  ['fr_irr', 'FR Lifetime IRR', 'fr_lifetime_irr_pct', 'higher-better', fmtPct],
  ['pzu_irr', 'PZU Lifetime IRR', 'pzu_lifetime_irr_pct', 'higher-better', fmtPct],
  ['fr_payback', 'FR Lifetime Payback', 'fr_lifetime_payback_years', 'lower-better', fmtYears],
  ['pzu_payback', 'PZU Lifetime Payback', 'pzu_lifetime_payback_years', 'lower-better', fmtYears],
  ['capex', 'Total CAPEX', 'params.total_investment_eur', 'lower-better', fmtEur],
  ['debt_service', 'Annual Debt Service', 'financing.annual_debt_service_eur', 'lower-better', fmtEur],
]

function buildRows(a: AnyAnalysis, b: AnyAnalysis): Row[] {
  const numeric: Row[] = NUMERIC_SPECS.map(([key, label, path, direction, format]) => ({
    kind: 'num',
    key,
    label,
    direction,
    format,
    pickA: getNum(a, path),
    pickB: getNum(b, path),
  }))
  // DSCR violations: lower-better count from array length.
  numeric.splice(6, 0, {
    kind: 'num',
    key: 'dscr_violations',
    label: 'DSCR Violations',
    direction: 'lower-better',
    format: fmtCount,
    pickA: getArrayLen(a, 'dscr_violation_years'),
    pickB: getArrayLen(b, 'dscr_violation_years'),
  })
  // Recommended scenario: string compare.
  numeric.splice(7, 0, {
    kind: 'str',
    key: 'recommended',
    label: 'Recommended Scenario',
    pickA: getStr(a, 'recommended_scenario'),
    pickB: getStr(b, 'recommended_scenario'),
  })
  return numeric
}

// Color rule: increase that improves the metric => green; that worsens => red.
function deltaColor(absDelta: number, direction: Direction): string {
  if (absDelta === 0) return 'text-slate-400'
  const isIncrease = absDelta > 0
  const goodIncrease = direction === 'higher-better'
  const isGood = isIncrease === goodIncrease
  return isGood ? 'text-emerald-400' : 'text-rose-400'
}

function renderNumericDelta(row: NumericRow): React.ReactNode {
  const { pickA, pickB, format, direction } = row
  if (pickA == null || pickB == null) {
    return <span className="text-slate-400">{EM_DASH}</span>
  }
  const abs = pickB - pickA
  if (abs === 0) {
    return <span className="text-slate-400 font-mono">0</span>
  }
  const arrow = abs > 0 ? '↑' : '↓'
  const sign = abs > 0 ? '+' : ''
  // Percent change vs A. If A == 0, fall back to absolute-only.
  const pct = pickA === 0 ? null : (abs / Math.abs(pickA)) * 100
  const color = deltaColor(abs, direction)
  return (
    <span className={`${color} font-mono text-xs sm:text-sm`}>
      {arrow} {sign}
      {format(abs)}
      {pct != null && (
        <span className="ml-1 opacity-80">({formatPercentage(pct, { showSign: true })})</span>
      )}
    </span>
  )
}

function renderStringDelta(row: StringRow): React.ReactNode {
  const { pickA, pickB } = row
  if (pickA == null || pickB == null) {
    return <span className="text-slate-400">{EM_DASH}</span>
  }
  if (pickA === pickB) {
    return <span className="text-slate-400 font-mono">=</span>
  }
  return (
    <span className="inline-flex items-center gap-1 text-amber-300 font-mono text-xs sm:text-sm">
      <span>{pickA}</span>
      <ArrowRight className="w-3 h-3" />
      <span>{pickB}</span>
    </span>
  )
}

function formatValue(row: Row, side: 'A' | 'B'): React.ReactNode {
  if (row.kind === 'num') {
    const v = side === 'A' ? row.pickA : row.pickB
    if (v == null) return <span className="text-slate-400">{EM_DASH}</span>
    return <span className="font-mono text-white">{row.format(v)}</span>
  }
  const v = side === 'A' ? row.pickA : row.pickB
  if (v == null) return <span className="text-slate-400">{EM_DASH}</span>
  return <span className="font-mono text-white">{v}</span>
}

export default function ScenarioDiffPanel({
  analysisA,
  analysisB,
  nameA,
  nameB,
  className = '',
}: ScenarioDiffPanelProps) {
  if (!analysisA || !analysisB) {
    return (
      <div
        className={`bg-slate-900 border border-slate-700 rounded-lg p-6 text-center ${className}`}
      >
        <p className="text-slate-400 text-sm">Run two scenarios to compare</p>
        <p className="text-slate-400 text-xs mt-1">
          Use &quot;Save as A&quot; and &quot;Save as B&quot; on a completed analysis to populate
          both slots.
        </p>
      </div>
    )
  }

  const rows = buildRows(analysisA, analysisB)
  const labelA = nameA || 'Scenario A'
  const labelB = nameB || 'Scenario B'

  return (
    <div
      className={`bg-slate-900 border border-slate-700 rounded-lg overflow-hidden ${className}`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-800/50 border-b border-slate-700">
              <th className="text-left px-4 py-2 text-slate-400 font-medium">Metric</th>
              <th className="text-right px-4 py-2 text-blue-300 font-medium">
                <div className="text-[10px] uppercase tracking-wider text-slate-400">A</div>
                <div className="font-mono truncate max-w-[260px]" title={labelA}>
                  {labelA}
                </div>
              </th>
              <th className="text-right px-4 py-2 text-emerald-300 font-medium">
                <div className="text-[10px] uppercase tracking-wider text-slate-400">B</div>
                <div className="font-mono truncate max-w-[260px]" title={labelB}>
                  {labelB}
                </div>
              </th>
              <th className="text-right px-4 py-2 text-slate-400 font-medium">{'Δ (B - A)'}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={row.key}
                className={idx % 2 === 0 ? 'bg-slate-900' : 'bg-slate-800/30'}
              >
                <td className="px-4 py-2 text-slate-300">{row.label}</td>
                <td className="px-4 py-2 text-right">{formatValue(row, 'A')}</td>
                <td className="px-4 py-2 text-right">{formatValue(row, 'B')}</td>
                <td className="px-4 py-2 text-right">
                  {row.kind === 'num' ? renderNumericDelta(row) : renderStringDelta(row)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 text-[10px] text-slate-400 border-t border-slate-700 bg-slate-900/50">
        Green = change moves metric in the favorable direction. Red = unfavorable. Em-dash = data
        missing in one slot.
      </div>
    </div>
  )
}
