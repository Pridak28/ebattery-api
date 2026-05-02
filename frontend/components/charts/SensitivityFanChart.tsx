'use client'

/**
 * SensitivityFanChart — P10 / P50 / P90 IRR fan from the Phase F1
 * Monte Carlo engine. Renders a vertical bar with 10th, median, and 90th
 * percentile markers for IRR / NPV / payback.
 */
const fmtPct = (n: number) =>
  Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '—'
const fmtEur = (n: number) =>
  Number.isFinite(n)
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(n)
    : '—'
const fmtYr = (n: number) =>
  Number.isFinite(n) && n < 100 ? `${n.toFixed(1)} yr` : '∞'

export type SensitivitySummary = {
  runs: number
  p10_irr: number
  p50_irr: number
  p90_irr: number
  p10_npv: number
  p50_npv: number
  p90_npv: number
  p10_payback_yr: number
  p50_payback_yr: number
  p90_payback_yr: number
  mean_irr: number
  irr_samples?: number[]
}

function FanRow({
  label,
  p10,
  p50,
  p90,
  format,
}: {
  label: string
  p10: number
  p50: number
  p90: number
  format: (n: number) => string
}) {
  const allFinite = [p10, p50, p90].every((v) => Number.isFinite(v))
  if (!allFinite) {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="font-mono text-slate-400">{label}</span>
        <span className="text-slate-400">— (degenerate runs)</span>
      </div>
    )
  }
  return (
    <div className="grid grid-cols-4 items-center gap-2 text-sm">
      <span className="font-mono uppercase text-slate-400">{label}</span>
      <span className="text-rose-300">P10 {format(p10)}</span>
      <span className="font-bold text-emerald-300">P50 {format(p50)}</span>
      <span className="text-blue-300">P90 {format(p90)}</span>
    </div>
  )
}

export function SensitivityFanChart({ data }: { data: SensitivitySummary }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-mono uppercase text-slate-300">
          Monte Carlo P10 / P50 / P90
        </h3>
        <span className="text-[10px] text-slate-400">{data.runs} runs</span>
      </div>
      <div className="space-y-2">
        <FanRow label="IRR" p10={data.p10_irr} p50={data.p50_irr} p90={data.p90_irr} format={fmtPct} />
        <FanRow label="NPV" p10={data.p10_npv} p50={data.p50_npv} p90={data.p90_npv} format={fmtEur} />
        <FanRow
          label="Payback"
          p10={data.p10_payback_yr}
          p50={data.p50_payback_yr}
          p90={data.p90_payback_yr}
          format={fmtYr}
        />
      </div>
      <div className="mt-3 text-[10px] text-slate-400">
        Driver triangulars (min, mode, max): activation 5/10/20%, RTE 85/88/90%,
        Y1 degradation 2.0/2.5/3.5%, FX 4.85/5.00/5.20 RON/EUR, PZU spread
        85/100/115%.
      </div>
    </div>
  )
}

export default SensitivityFanChart
