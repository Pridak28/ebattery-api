'use client'

/**
 * HealthDiagnostics — collapsible sub-system status table backed by
 * GET /api/v1/data/health-detailed. Lets investors and SREs see at a glance
 * which datasets are fresh, whether simulators are runnable, and the regime
 * split — without leaving the dashboard.
 */

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { healthApi } from '@/lib/api'

type DatasetCheck = {
  available: boolean
  row_count: number | null
  min_date: string | null
  max_date: string | null
  days_stale: number | null
  error?: string
}

type DamasCheck = DatasetCheck & {
  regime_pre_count: number
  regime_post_count: number
  fcr_activated_total_mwh: number
}

type SmokeCheck = { ok: boolean; total_profit_eur?: number; error?: string }

type HealthDetailed = {
  app_version: string
  data_dir: string
  manifest_present: boolean
  as_of: string
  pzu: DatasetCheck
  damas: DamasCheck
  simulator_pzu_smoke: SmokeCheck
  simulator_fr_smoke: SmokeCheck
  compliance_gates_default: Record<string, string>
}

const dot = (ok: boolean) => (
  <span className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
)
const fmt = (v: number | string | null | undefined) =>
  v === null || v === undefined ? '—' : typeof v === 'number' ? v.toLocaleString() : v

export function HealthDiagnostics() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<HealthDetailed | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || data || error) return
    let cancelled = false
    healthApi
      .getDetailed()
      .then((r) => {
        if (!cancelled) setData(r.data as HealthDetailed)
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'failed to load diagnostics')
      })
    return () => {
      cancelled = true
    }
  }, [open, data, error])

  const rows: Array<{ name: string; ok: boolean; detail: string }> = data
    ? [
        {
          name: 'PZU dataset',
          ok: data.pzu.available && (data.pzu.days_stale ?? 99) <= 7,
          detail: `${fmt(data.pzu.row_count)} rows • ${fmt(data.pzu.min_date)} → ${fmt(data.pzu.max_date)} • stale ${fmt(data.pzu.days_stale)}d`,
        },
        {
          name: 'DAMAS dataset',
          ok: data.damas.available && (data.damas.days_stale ?? 99) <= 7,
          detail: `${fmt(data.damas.row_count)} rows • pre ${fmt(data.damas.regime_pre_count)} / post ${fmt(data.damas.regime_post_count)} • FCR ${fmt(data.damas.fcr_activated_total_mwh)} MWh`,
        },
        {
          name: 'PZU simulator',
          ok: data.simulator_pzu_smoke.ok,
          detail: data.simulator_pzu_smoke.ok
            ? `60-day smoke profit €${fmt(Math.round(data.simulator_pzu_smoke.total_profit_eur ?? 0))}`
            : (data.simulator_pzu_smoke.error ?? 'failed'),
        },
        {
          name: 'FR simulator',
          ok: data.simulator_fr_smoke.ok,
          detail: data.simulator_fr_smoke.ok
            ? `60-day smoke profit €${fmt(Math.round(data.simulator_fr_smoke.total_profit_eur ?? 0))}`
            : (data.simulator_fr_smoke.error ?? 'failed'),
        },
        {
          name: 'Manifest',
          ok: data.manifest_present,
          detail: data.manifest_present ? 'present' : 'missing — run pipeline',
        },
      ]
    : []

  return (
    <div className="rounded border border-slate-800/50 bg-slate-900/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-mono uppercase tracking-wider text-slate-400 hover:text-slate-200"
      >
        <span className="inline-flex items-center gap-2">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          System diagnostics
        </span>
        {data && (
          <span className="text-[10px] text-slate-400">
            v{data.app_version} • as of {data.as_of}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t border-slate-800/50 px-3 py-2">
          {!data && !error && <div className="text-xs text-slate-400">Loading…</div>}
          {error && <div className="text-xs text-red-400">Error: {error}</div>}
          {data && (
            <table className="w-full text-left text-xs">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className="border-b border-slate-800/30 last:border-b-0">
                    <td className="py-1.5 pr-2 align-top">
                      <span className="inline-flex items-center gap-2 text-slate-300">
                        {dot(r.ok)}
                        {r.name}
                      </span>
                    </td>
                    <td className="py-1.5 text-right font-mono text-slate-400">{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

export default HealthDiagnostics
