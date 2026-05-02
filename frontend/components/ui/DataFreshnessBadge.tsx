'use client'

/**
 * DataFreshnessBadge — pulls /api/v1/data/manifest and shows the latest delivery
 * date per dataset. Replaces a static "live" feel on the dashboard with one
 * actually-live signal so investors can see the platform is backed by real data.
 */

import { useEffect, useState } from 'react'
import { Database, Clock } from 'lucide-react'
import { dataApi } from '@/lib/api'

type DatasetRow = {
  dataset_id?: string
  min_delivery_date?: string
  max_delivery_date?: string
  bankability_level?: string
}

type Manifest = {
  datasets?: DatasetRow[]
  generated_at_utc?: string
}

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; manifest: Manifest }

const PRETTY: Record<string, string> = {
  opcom_pzu: 'OPCOM PZU',
  damas_clean: 'DAMAS aFRR',
}

function daysBetween(a: string, b: string): number {
  const ms = Math.abs(new Date(a).getTime() - new Date(b).getTime())
  return Math.round(ms / (1000 * 60 * 60 * 24))
}

export function DataFreshnessBadge({ className = '' }: { className?: string }) {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    dataApi
      .getManifest()
      .then((res) => {
        if (cancelled) return
        setState({ kind: 'ready', manifest: res.data as Manifest })
      })
      .catch((err) => {
        if (cancelled) return
        setState({
          kind: 'error',
          message: err?.message ?? 'unknown error',
        })
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (state.kind === 'loading') {
    return (
      <div
        className={`rounded-lg border border-slate-700 bg-slate-900/50 p-3 sm:p-4 ${className}`}
        aria-busy="true"
      >
        <div className="flex items-center gap-2 mb-2">
          <Database className="w-4 h-4 text-slate-400" />
          <span className="text-[10px] sm:text-xs uppercase tracking-wider text-slate-400">
            Market Data
          </span>
        </div>
        <div className="space-y-2">
          <div className="h-3 w-3/4 rounded bg-slate-800 animate-pulse" />
          <div className="h-3 w-2/3 rounded bg-slate-800 animate-pulse" />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div
        className={`rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 sm:p-4 ${className}`}
      >
        <div className="flex items-center gap-2 mb-1">
          <Database className="w-4 h-4 text-amber-400" />
          <span className="text-[10px] sm:text-xs uppercase tracking-wider text-amber-400">
            Market Data Unavailable
          </span>
        </div>
        <p className="text-[11px] text-slate-400">
          Could not reach data manifest. Backend may be sleeping or offline.
        </p>
      </div>
    )
  }

  const datasets = state.manifest.datasets ?? []
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div
      className={`rounded-lg border border-slate-700 bg-slate-900/50 p-3 sm:p-4 ${className}`}
    >
      <div className="flex items-center justify-between mb-2 sm:mb-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-[#00ffd1]" />
          <span className="text-[10px] sm:text-xs uppercase tracking-wider text-slate-400">
            Market Data Backing
          </span>
        </div>
        <span className="text-[10px] font-mono text-slate-400 hidden sm:inline">
          /api/v1/data/manifest
        </span>
      </div>

      {datasets.length === 0 ? (
        <p className="text-[11px] text-slate-400">No datasets registered.</p>
      ) : (
        <ul className="space-y-2">
          {datasets.map((d) => {
            const id = d.dataset_id ?? 'dataset'
            const max = d.max_delivery_date
            const min = d.min_delivery_date
            const lag = max ? daysBetween(today, max) : null
            const stale = lag !== null && lag > 60
            return (
              <li
                key={id}
                className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:justify-between text-[11px] sm:text-xs"
              >
                <span className="text-slate-200 font-medium">
                  {PRETTY[id] ?? id}
                </span>
                <span className="font-mono text-slate-400 flex items-center gap-1.5">
                  <Clock className="w-3 h-3 opacity-60" />
                  {min ?? '—'} → {max ?? '—'}
                  {lag !== null && (
                    <span
                      className={`ml-1 rounded px-1 py-0.5 text-[10px] ${
                        stale
                          ? 'bg-amber-500/15 text-amber-300'
                          : 'bg-emerald-500/15 text-emerald-300'
                      }`}
                    >
                      {lag === 0 ? 'today' : `${lag}d ago`}
                    </span>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default DataFreshnessBadge
