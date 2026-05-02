'use client'

/**
 * DscrDetailPanel — per-year DSCR trajectory for a single scenario (FR or PZU).
 *
 * Lender covenants typically demand DSCR ≥ 1.20. This panel shows:
 *   - Stacked bars: CFADS (cash available) vs debt service (what must be paid)
 *   - Right-axis line: DSCR ratio per year, with a covenant reference line
 *   - Violation tally + a one-line driver hint (CFADS decline vs flat debt)
 *
 * Renders nothing useful if `cashflow` is empty (returns a "no projection"
 * placeholder) so it is safe to drop into the page even before analysis runs.
 */

import {
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
  Cell,
} from 'recharts'

export type AnnualCashflow = {
  year: number
  dscr?: number
  cfads_eur?: number
  debt_service_eur?: number
  capacity_factor?: number
  auxiliary_cost_eur?: number
  augmentation_cost_eur?: number
}

const DEFAULT_COVENANT = 1.2

const fmtEur = (n: number) =>
  Number.isFinite(n)
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(n)
    : '—'

const fmtKEur = (n: number) =>
  Number.isFinite(n) ? `€${(n / 1000).toFixed(0)}K` : '—'

type ScenarioName = 'FR' | 'PZU'

const SCENARIO_ACCENT: Record<ScenarioName, string> = {
  FR: '#00ffd1',
  PZU: '#2563eb',
}

export function DscrDetailPanel({
  cashflow,
  dscr_violation_years,
  scenario_name,
  covenant = DEFAULT_COVENANT,
}: {
  cashflow: AnnualCashflow[]
  dscr_violation_years: number[]
  scenario_name: ScenarioName
  covenant?: number
}) {
  if (!cashflow || cashflow.length === 0) {
    return (
      <div className="rounded border border-slate-700 bg-slate-900/60 p-6 text-sm text-slate-400">
        No {scenario_name} cashflow projection available — run the analysis first.
      </div>
    )
  }

  // Only consider years where debt service is actually scheduled — once the
  // loan is repaid DSCR is structurally infinite and not interesting.
  const debtRows = cashflow.filter((r) => (r.debt_service_eur ?? 0) > 0)
  const projectionYears = debtRows.length
  const violationSet = new Set(dscr_violation_years ?? [])

  const chartData = debtRows.map((r) => {
    const cfads = r.cfads_eur ?? 0
    const debt = r.debt_service_eur ?? 0
    const dscr = r.dscr ?? (debt > 0 ? cfads / debt : 0)
    const isViolation =
      violationSet.has(r.year) || (debt > 0 && dscr < covenant)
    return {
      year: r.year,
      cfads,
      debt,
      dscr,
      isViolation,
    }
  })

  const violationCount = chartData.filter((r) => r.isViolation).length

  // Driver hint: compare first-quartile vs last-quartile CFADS to see if the
  // cash flow is declining (degradation / augmentation eating into revenue)
  // versus debt service that is typically flat for a French-style amortising
  // loan. This makes the hint actually informative for a lender.
  let driverHint = `${scenario_name} scenario clears the ${covenant.toFixed(2)}x covenant in every modelled year.`
  if (violationCount > 0) {
    const q = Math.max(1, Math.floor(chartData.length / 4))
    const earlyCfads =
      chartData.slice(0, q).reduce((s, r) => s + r.cfads, 0) / q
    const lateCfads =
      chartData.slice(-q).reduce((s, r) => s + r.cfads, 0) / q
    const cfadsDelta = earlyCfads > 0 ? (lateCfads - earlyCfads) / earlyCfads : 0
    if (cfadsDelta < -0.1) {
      driverHint = `CFADS erodes ${Math.abs(cfadsDelta * 100).toFixed(0)}% from early to late years while debt service stays flat — covenant breach is degradation- / augmentation-driven.`
    } else if (cfadsDelta > 0.1) {
      driverHint = `CFADS grows ${(cfadsDelta * 100).toFixed(0)}% over time; breach is concentrated in early years — consider grace period or lower initial gearing.`
    } else {
      driverHint = `CFADS is roughly flat; covenant breach indicates debt service is sized too aggressively versus steady-state cash flow.`
    }
  }

  const accent = SCENARIO_ACCENT[scenario_name]

  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-mono uppercase text-slate-300">
            {scenario_name} DSCR trajectory
          </h3>
          <p className="text-[11px] text-slate-400">
            CFADS vs debt service · covenant ≥ {covenant.toFixed(2)}x
          </p>
        </div>
        <div
          className={`rounded px-2 py-1 text-[11px] font-mono uppercase ${
            violationCount > 0
              ? 'bg-rose-900/60 text-rose-200'
              : 'bg-emerald-900/40 text-emerald-300'
          }`}
        >
          {violationCount} / {projectionYears} breach{violationCount === 1 ? '' : 'es'}
        </div>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 10, right: 30, left: 10, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="year"
              tick={{ fill: '#64748b', fontSize: 11 }}
              axisLine={{ stroke: '#334155' }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: '#64748b', fontSize: 11 }}
              axisLine={{ stroke: '#334155' }}
              tickFormatter={fmtKEur}
              label={{
                value: 'EUR',
                angle: -90,
                position: 'insideLeft',
                fill: '#64748b',
                fontSize: 10,
              }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: accent, fontSize: 11 }}
              axisLine={{ stroke: accent, strokeOpacity: 0.5 }}
              tickFormatter={(v: number) => `${v.toFixed(2)}x`}
              domain={[0, (dataMax: number) => Math.max(2, dataMax * 1.1)]}
              label={{
                value: 'DSCR',
                angle: 90,
                position: 'insideRight',
                fill: accent,
                fontSize: 10,
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
              }}
              labelStyle={{ color: '#e2e8f0', fontWeight: 'bold' }}
              itemStyle={{ color: '#94a3b8', fontSize: '12px' }}
              formatter={(value: number, name: string) => {
                if (name === 'cfads') return [fmtEur(value), 'CFADS']
                if (name === 'debt') return [fmtEur(value), 'Debt service']
                if (name === 'dscr') return [`${value.toFixed(2)}x`, 'DSCR']
                return [value, name]
              }}
              labelFormatter={(v: number) => `Year ${v}`}
            />
            <Legend
              wrapperStyle={{ paddingTop: '8px', fontSize: '11px' }}
              formatter={(value: string) => {
                if (value === 'cfads') return 'CFADS'
                if (value === 'debt') return 'Debt service'
                if (value === 'dscr') return `DSCR (cov. ${covenant.toFixed(2)}x)`
                return value
              }}
            />
            <ReferenceLine
              yAxisId="right"
              y={covenant}
              stroke="#f43f5e"
              strokeDasharray="4 4"
              label={{
                value: `cov. ${covenant.toFixed(2)}x`,
                fill: '#fda4af',
                fontSize: 10,
                position: 'right',
              }}
            />
            <Bar yAxisId="left" dataKey="cfads" name="cfads" stackId={undefined}>
              {chartData.map((row) => (
                <Cell
                  key={`cfads-${row.year}`}
                  fill={row.isViolation ? '#7f1d1d' : accent}
                  fillOpacity={0.55}
                />
              ))}
            </Bar>
            <Bar yAxisId="left" dataKey="debt" name="debt" fill="#475569" fillOpacity={0.7} />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="dscr"
              name="dscr"
              stroke={accent}
              strokeWidth={2.5}
              dot={(props: { cx?: number; cy?: number; payload?: { isViolation?: boolean; year?: number } }) => {
                const { cx, cy, payload } = props
                if (cx == null || cy == null) {
                  return <g key={`dot-empty-${payload?.year ?? 'x'}`} />
                }
                const fill = payload?.isViolation ? '#f43f5e' : '#10b981'
                return (
                  <circle
                    key={`dot-${payload?.year ?? cx}`}
                    cx={cx}
                    cy={cy}
                    r={4}
                    fill={fill}
                    stroke="#0f172a"
                    strokeWidth={1}
                  />
                )
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 border-t border-slate-700 pt-3">
        <p
          className={`text-xs ${
            violationCount > 0 ? 'text-rose-300' : 'text-emerald-300'
          }`}
        >
          {violationCount} violation year{violationCount === 1 ? '' : 's'} out of{' '}
          {projectionYears} projection year{projectionYears === 1 ? '' : 's'}
          {violationCount > 0 && dscr_violation_years && dscr_violation_years.length > 0 && (
            <span className="text-slate-400"> · breach years: {dscr_violation_years.join(', ')}</span>
          )}
        </p>
        <p className="mt-1 text-[11px] text-slate-400">{driverHint}</p>
      </div>
    </div>
  )
}

export default DscrDetailPanel
