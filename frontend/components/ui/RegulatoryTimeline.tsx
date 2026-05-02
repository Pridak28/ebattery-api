'use client'

/**
 * RegulatoryTimeline — surfaces upcoming Romanian / EU regulatory transitions
 * with countdown timers and one-line revenue-impact predictions.
 *
 * Data is hardcoded (regulatory milestones, not market data — embedding is
 * fine and keeps this component dependency-free).
 *
 * SSR safety: the date used to compute past/upcoming status is captured
 * inside `useMemo` with `[]` deps and compared at ISO-date granularity
 * (YYYY-MM-DD strings) so server and first-client renders agree.
 */

import { useMemo } from 'react'
import { Calendar, CheckCircle2, Clock, ExternalLink, AlertTriangle } from 'lucide-react'

type Severity = 'info' | 'warning' | 'critical'
type Status = 'past' | 'upcoming'

type Milestone = {
  id: string
  name: string
  effective_date: string // YYYY-MM-DD
  impact: string
  severity: Severity
  source_url?: string
}

const MILESTONES: Milestone[] = [
  {
    id: 'mari',
    name: 'MARI go-live (aFRR/mFRR)',
    effective_date: '2026-04-01',
    impact: 'Min bid raises 1 MW → 5 MW for aFRR/mFRR. Smaller assets aggregate or exit.',
    severity: 'critical',
    source_url: 'https://www.entsoe.eu/network_codes/eb/mari/',
  },
  {
    id: 'picasso_ro',
    name: 'PICASSO connection — Romania',
    effective_date: '2026-12-01', // estimate; pending Hungarian MAVIR
    impact:
      'Cross-border aFRR exchange begins. Expect 25-45% Romanian activation-price compression toward EU baseline.',
    severity: 'warning',
    source_url: 'https://www.entsoe.eu/network_codes/eb/picasso/',
  },
  {
    id: 'anre_60_2024',
    name: 'ANRE Order 60/2024 — pay-as-bid',
    effective_date: '2024-10-01',
    impact:
      'Settlement switched marginal → pay-as-bid. Already in effect for all current backtests.',
    severity: 'info',
    source_url: 'https://legislatie.just.ro/Public/DetaliiDocumentAfis/287809',
  },
]

// Today as YYYY-MM-DD using local time (cap at 1-day granularity to keep
// SSR + first client render in agreement once hydration completes).
function todayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// Days between two YYYY-MM-DD strings (b - a). Positive = b is after a.
function diffDaysIso(a: string, b: string): number {
  const ta = Date.parse(`${a}T00:00:00Z`)
  const tb = Date.parse(`${b}T00:00:00Z`)
  return Math.round((tb - ta) / (1000 * 60 * 60 * 24))
}

function formatRelative(days: number, status: Status): string {
  const abs = Math.abs(days)
  if (status === 'upcoming') {
    if (abs === 0) return 'today'
    if (abs === 1) return '1 day to go'
    if (abs < 31) return `${abs} days to go`
    if (abs < 365) {
      const months = Math.round(abs / 30)
      return months === 1 ? '~1 month to go' : `~${months} months to go`
    }
    const years = (abs / 365).toFixed(1)
    return `~${years} years to go`
  }
  // past
  if (abs === 0) return 'effective today'
  if (abs === 1) return '1 day ago'
  if (abs < 31) return `${abs} days ago`
  if (abs < 365) {
    const months = Math.round(abs / 30)
    return months === 1 ? '~1 month ago' : `~${months} months ago`
  }
  const years = (abs / 365).toFixed(1)
  return `~${years} years ago`
}

const SEVERITY_STYLES: Record<
  Severity,
  { border: string; dot: string; chip: string; chipText: string; label: string }
> = {
  critical: {
    border: 'border-red-500/40',
    dot: 'bg-red-500',
    chip: 'bg-red-500/15 border-red-500/40',
    chipText: 'text-red-300',
    label: 'CRITICAL',
  },
  warning: {
    border: 'border-amber-500/40',
    dot: 'bg-amber-400',
    chip: 'bg-amber-500/10 border-amber-500/30',
    chipText: 'text-amber-300',
    label: 'WARNING',
  },
  info: {
    border: 'border-slate-600',
    dot: 'bg-slate-400',
    chip: 'bg-slate-700/40 border-slate-600',
    chipText: 'text-slate-300',
    label: 'INFO',
  },
}

type ResolvedMilestone = Milestone & { status: Status; days: number }

export function RegulatoryTimeline({ className = '' }: { className?: string }) {
  const items: ResolvedMilestone[] = useMemo(() => {
    const today = todayIso()
    const resolved: ResolvedMilestone[] = MILESTONES.map((m) => {
      const days = diffDaysIso(today, m.effective_date)
      const status: Status = days >= 0 ? 'upcoming' : 'past'
      return { ...m, status, days }
    })
    // upcoming first (closest first), then past (most recent first).
    resolved.sort((a, b) => {
      if (a.status !== b.status) return a.status === 'upcoming' ? -1 : 1
      if (a.status === 'upcoming') return a.days - b.days
      return b.days - a.days // past: less-negative (more recent) first
    })
    return resolved
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={`space-y-3 ${className}`}>
      <ol className="relative border-l border-slate-700 ml-2">
        {items.map((m) => {
          const style = SEVERITY_STYLES[m.severity]
          const isPast = m.status === 'past'
          return (
            <li key={m.id} className="ml-4 mb-3 last:mb-0">
              <span
                className={`absolute -left-[7px] flex h-3.5 w-3.5 items-center justify-center rounded-full ring-2 ring-slate-900 ${style.dot}`}
                aria-hidden="true"
              />
              <div
                className={`rounded-lg border bg-slate-900/60 p-3 ${style.border}`}
              >
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border ${style.chip} ${style.chipText}`}
                  >
                    {style.label}
                  </span>
                  <h4 className="text-sm font-semibold text-white">{m.name}</h4>
                  <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {m.effective_date}
                  </span>
                  <span
                    className={`ml-auto text-[11px] font-mono flex items-center gap-1 ${
                      isPast ? 'text-emerald-300' : 'text-[#00ffd1]'
                    }`}
                  >
                    {isPast ? (
                      <CheckCircle2 className="w-3.5 h-3.5" />
                    ) : (
                      <Clock className="w-3.5 h-3.5" />
                    )}
                    {formatRelative(m.days, m.status)}
                  </span>
                </div>
                <p className="text-[11px] sm:text-xs text-slate-300">
                  <span className="text-slate-400 uppercase tracking-wider text-[9px] mr-1">
                    Revenue impact:
                  </span>
                  {m.impact}
                </p>
                {m.source_url && (
                  <a
                    href={m.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 mt-1.5 text-[10px] sm:text-[11px] text-[#00ffd1] hover:text-[#00ffd1]/80 hover:underline"
                  >
                    Source <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      <p className="text-[10px] text-slate-400 flex items-center gap-1">
        <AlertTriangle className="w-3 h-3" />
        Dates for upcoming milestones are estimates; actuals subject to TSO/regulator timing.
      </p>
    </div>
  )
}

export default RegulatoryTimeline
