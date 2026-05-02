'use client'

/**
 * CapexBands — Romanian vendor band (left) + European-typical band (right).
 * The user's €175/kWh / €3.5M quote is exceptional vs European norms; banks
 * will underwrite at the EU-typical band, not the vendor anchor.
 *
 * Source of truth: backend GET /investment/defaults
 *  -> investment.capex_per_kwh_band             { low, mid, high }   ← Romanian / vendor
 *  -> investment.capex_per_kwh_band_eu_typical  { low, mid, high }   ← European bankability
 */

import { ConfidenceBadge } from './ConfidenceBadge'

export type CapexBand = { low: number; mid: number; high: number }

export interface CapexBandsProps {
  capacityMwh: number
  powerMw: number
  band?: CapexBand
  bandEuTypical?: CapexBand
  midAnchorNote?: string
  className?: string
}

const DEFAULT_BAND: CapexBand = { low: 150, mid: 175, high: 250 }
const DEFAULT_BAND_EU: CapexBand = { low: 300, mid: 400, high: 500 }

function formatEuros(value: number): string {
  if (value >= 1_000_000) return `€${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `€${(value / 1_000).toFixed(0)}k`
  return `€${value.toFixed(0)}`
}

function Card({
  label,
  eurPerKwh,
  capacityMwh,
  tone,
  headerColor,
  anchor,
  highlight,
}: {
  label: string
  eurPerKwh: number
  capacityMwh: number
  tone: string
  headerColor: string
  anchor?: string
  highlight?: boolean
}) {
  const total = eurPerKwh * capacityMwh * 1000
  return (
    <div
      className={`rounded-lg border p-4 ${tone} ${highlight ? 'ring-2 ring-blue-400/40' : ''}`}
    >
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-2xl font-bold ${headerColor}`}>{formatEuros(total)}</div>
      <div className="mt-1 text-sm text-slate-300">€{eurPerKwh.toFixed(0)} / kWh</div>
      {anchor && <div className="mt-2 text-xs text-blue-300/80">{anchor}</div>}
    </div>
  )
}

export function CapexBands({
  capacityMwh,
  powerMw,
  band = DEFAULT_BAND,
  bandEuTypical = DEFAULT_BAND_EU,
  midAnchorNote = "Anchored on your €3.5M quote (Huawei) for 10 MW / 20 MWh",
  className = '',
}: CapexBandsProps) {
  return (
    <section className={`space-y-5 ${className}`}>
      <header className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">
            CAPEX bands — Romanian vendor anchor vs European bankability
          </h3>
          <p className="text-xs text-slate-400">
            Total project cost for{' '}
            <span className="font-medium text-slate-200">
              {powerMw.toFixed(0)} MW / {capacityMwh.toFixed(0)} MWh
            </span>{' '}
            at six €/kWh-installed reference points.
          </p>
        </div>
        <ConfidenceBadge label="Likely-source / Scenario" short />
      </header>

      {/* Romanian / vendor band */}
      <div>
        <h4 className="mb-2 text-xs font-mono uppercase text-emerald-300">
          Romanian vendor quotes (your reference)
        </h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Card
            label="Sermatec-equivalent"
            eurPerKwh={band.low}
            capacityMwh={capacityMwh}
            tone="border-emerald-500/30 bg-emerald-500/5"
            headerColor="text-emerald-300"
          />
          <Card
            label="Huawei anchor (your quote)"
            eurPerKwh={band.mid}
            capacityMwh={capacityMwh}
            tone="border-blue-500/40 bg-blue-500/10 ring-1 ring-blue-500/30"
            headerColor="text-blue-200"
            anchor={midAnchorNote}
            highlight
          />
          <Card
            label="Premium tier-1"
            eurPerKwh={band.high}
            capacityMwh={capacityMwh}
            tone="border-amber-500/30 bg-amber-500/5"
            headerColor="text-amber-300"
          />
        </div>
      </div>

      {/* European-typical band */}
      <div>
        <h4 className="mb-2 text-xs font-mono uppercase text-rose-300">
          European bankability anchors (what lenders underwrite to)
        </h4>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Card
            label="EU low (turnkey, lean BoP)"
            eurPerKwh={bandEuTypical.low}
            capacityMwh={capacityMwh}
            tone="border-rose-500/30 bg-rose-500/5"
            headerColor="text-rose-300"
          />
          <Card
            label="EU typical (full EPC + grid + civils)"
            eurPerKwh={bandEuTypical.mid}
            capacityMwh={capacityMwh}
            tone="border-rose-500/30 bg-rose-500/10"
            headerColor="text-rose-200"
            anchor="What banks (BCR / BRD / EBRD) will model against"
          />
          <Card
            label="EU high (premium spec + contingency)"
            eurPerKwh={bandEuTypical.high}
            capacityMwh={capacityMwh}
            tone="border-rose-500/30 bg-rose-500/5"
            headerColor="text-rose-300"
          />
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Your vendor quote at €{band.mid}/kWh is exceptional — typical European
          BESS EPC including grid connection, BoP, civils, and contingency runs
          €{bandEuTypical.low}–€{bandEuTypical.high}/kWh. ROI calculated on the
          vendor anchor will be 2–3× higher than what a Romanian project-finance
          bank actually underwrites to.
        </p>
      </div>
    </section>
  )
}

export default CapexBands
