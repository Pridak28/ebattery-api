'use client'

/**
 * StatusLabel — small pill that distinguishes data sources/quality so users
 * can't mistake hardcoded illustrations for live API output.
 *
 * Audit: BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md (Agent 2 Medium).
 */

export type StatusKind =
  | 'LIVE_API'
  | 'HISTORICAL'
  | 'SIMULATED'
  | 'FALLBACK'
  | 'NOT_VERIFIED'
  | 'ILLUSTRATIVE'
  | 'DEMO'

const STYLES: Record<StatusKind, { bg: string; text: string; ring: string; help: string }> = {
  LIVE_API: {
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-300',
    ring: 'ring-emerald-500/30',
    help: 'Number is fetched live from the API right now.',
  },
  HISTORICAL: {
    bg: 'bg-blue-500/15',
    text: 'text-blue-300',
    ring: 'ring-blue-500/30',
    help: 'Computed from historical Romanian market data.',
  },
  SIMULATED: {
    bg: 'bg-purple-500/15',
    text: 'text-purple-300',
    ring: 'ring-purple-500/30',
    help: 'Output of a simulation model — not real settlement.',
  },
  FALLBACK: {
    bg: 'bg-amber-500/15',
    text: 'text-amber-300',
    ring: 'ring-amber-500/30',
    help: 'Backend simulation failed; shown value is a fallback estimate.',
  },
  NOT_VERIFIED: {
    bg: 'bg-slate-500/15',
    text: 'text-slate-300',
    ring: 'ring-slate-500/30',
    help: 'Needs counsel/operator confirmation before use.',
  },
  ILLUSTRATIVE: {
    bg: 'bg-blue-500/15',
    text: 'text-blue-300',
    ring: 'ring-blue-500/30',
    help: 'Hardcoded example value, not from the API.',
  },
  DEMO: {
    bg: 'bg-slate-500/15',
    text: 'text-slate-300',
    ring: 'ring-slate-500/30',
    help: 'Demo mode — not connected to live trading.',
  },
}

export function StatusLabel({
  kind,
  label,
  className = '',
}: {
  kind: StatusKind
  label?: string
  className?: string
}) {
  const style = STYLES[kind]
  return (
    <span
      title={style.help}
      className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-mono font-medium uppercase tracking-wide ring-1 ${style.bg} ${style.text} ${style.ring} ${className}`}
    >
      {label ?? kind}
    </span>
  )
}

export default StatusLabel
