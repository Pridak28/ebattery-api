'use client'

/**
 * IrrDistributionHistogram — complementary view to SensitivityFanChart.
 *
 * Bins the raw Monte Carlo `irr_samples` returned by
 * POST /api/v1/investment/sensitivity into 25 equal-width buckets and
 * overlays vertical reference lines at P10 / P50 / P90 / mean so investors
 * can see the *shape* of the IRR distribution (skew, tails, multimodality)
 * not just the percentile waterfall.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BarChart3 } from 'lucide-react'

const BIN_COUNT = 25

const COLOR_P10 = '#f59e0b'    // amber
const COLOR_P50 = '#22d3ee'    // cyan
const COLOR_P90 = '#34d399'    // emerald
const COLOR_MEAN = '#94a3b8'   // slate
const COLOR_BAR = '#475569'    // slate-600

const fmtPct = (n: number) =>
  Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '—'

type Bin = {
  binStart: number
  binEnd: number
  binMid: number
  count: number
  label: string
}

function buildBins(samples: number[]): Bin[] {
  if (samples.length === 0) return []

  const finite = samples.filter((s) => Number.isFinite(s))
  if (finite.length === 0) return []

  const min = Math.min(...finite)
  const max = Math.max(...finite)

  // Degenerate case: all samples identical — collapse to a single bar
  // so the chart still renders something meaningful instead of NaN-ing out.
  if (max === min) {
    return [
      {
        binStart: min,
        binEnd: min,
        binMid: min,
        count: finite.length,
        label: fmtPct(min),
      },
    ]
  }

  const width = (max - min) / BIN_COUNT
  const bins: Bin[] = Array.from({ length: BIN_COUNT }, (_, i) => {
    const binStart = min + i * width
    const binEnd = binStart + width
    return {
      binStart,
      binEnd,
      binMid: binStart + width / 2,
      count: 0,
      label: fmtPct(binStart + width / 2),
    }
  })

  for (const s of finite) {
    // Last bin is inclusive on the right edge so max value lands somewhere.
    let idx = Math.floor((s - min) / width)
    if (idx >= BIN_COUNT) idx = BIN_COUNT - 1
    if (idx < 0) idx = 0
    bins[idx].count += 1
  }

  return bins
}

type Props = {
  irrSamples: number[]
  p10: number
  p50: number
  p90: number
  meanIrr: number
  className?: string
  loading?: boolean
}

export function IrrDistributionHistogram({
  irrSamples,
  p10,
  p50,
  p90,
  meanIrr,
  className = '',
  loading = false,
}: Props) {
  const wrapperCls =
    `rounded border border-slate-700 bg-slate-800/40 p-4 ${className}`.trim()

  if (loading) {
    return (
      <div className={wrapperCls}>
        <div className="mb-3 flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-slate-400" />
          <h3 className="font-mono text-sm uppercase text-slate-300">
            IRR Distribution
          </h3>
        </div>
        <div className="h-64 animate-pulse rounded bg-slate-700/30" />
      </div>
    )
  }

  if (!irrSamples || irrSamples.length === 0) {
    return (
      <div className={wrapperCls}>
        <div className="mb-3 flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-slate-400" />
          <h3 className="font-mono text-sm uppercase text-slate-300">
            IRR Distribution
          </h3>
        </div>
        <div className="flex h-64 items-center justify-center text-sm text-slate-400">
          Run sensitivity to see distribution
        </div>
      </div>
    )
  }

  const bins = buildBins(irrSamples)

  return (
    <div className={wrapperCls}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-[#22d3ee]" />
          <h3 className="font-mono text-sm uppercase text-slate-300">
            IRR Distribution
          </h3>
        </div>
        <span className="text-[10px] text-slate-400">
          {irrSamples.length} samples • {bins.length} bins
        </span>
      </div>

      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        <span className="text-amber-400">P10 {fmtPct(p10)}</span>
        <span className="font-bold text-cyan-300">P50 {fmtPct(p50)}</span>
        <span className="text-emerald-300">P90 {fmtPct(p90)}</span>
        <span className="text-slate-400">Mean {fmtPct(meanIrr)}</span>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bins} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="binMid"
              type="number"
              domain={['dataMin', 'dataMax']}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              axisLine={{ stroke: '#475569' }}
              tickLine={{ stroke: '#475569' }}
              tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              axisLine={{ stroke: '#475569' }}
              tickLine={{ stroke: '#475569' }}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #475569',
                borderRadius: '6px',
                color: '#fff',
                fontSize: '12px',
              }}
              formatter={(value: number) => [`${value} runs`, 'Count']}
              labelFormatter={(v: number) => `IRR ≈ ${(v * 100).toFixed(2)}%`}
            />
            {Number.isFinite(p10) && (
              <ReferenceLine
                x={p10}
                stroke={COLOR_P10}
                strokeWidth={2}
                label={{ value: 'P10', position: 'top', fill: COLOR_P10, fontSize: 10 }}
              />
            )}
            {Number.isFinite(p50) && (
              <ReferenceLine
                x={p50}
                stroke={COLOR_P50}
                strokeWidth={2}
                label={{ value: 'P50', position: 'top', fill: COLOR_P50, fontSize: 10 }}
              />
            )}
            {Number.isFinite(p90) && (
              <ReferenceLine
                x={p90}
                stroke={COLOR_P90}
                strokeWidth={2}
                label={{ value: 'P90', position: 'top', fill: COLOR_P90, fontSize: 10 }}
              />
            )}
            {Number.isFinite(meanIrr) && (
              <ReferenceLine
                x={meanIrr}
                stroke={COLOR_MEAN}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                label={{ value: 'Mean', position: 'insideTopRight', fill: COLOR_MEAN, fontSize: 10 }}
              />
            )}
            <Bar dataKey="count" fill={COLOR_BAR} stroke="#64748b" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 text-[10px] text-slate-400">
        Histogram of Monte Carlo IRR realisations. Tail width ≈ project risk;
        skew indicates whether downside or upside dominates.
      </div>
    </div>
  )
}

export default IrrDistributionHistogram
