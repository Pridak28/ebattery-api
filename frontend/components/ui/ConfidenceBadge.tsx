'use client'

/**
 * ConfidenceBadge — surfaces the audit-mandated confidence label that the
 * backend attaches to every FR / PZU / Investment result.
 *
 * Sources:
 *   - audit/ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md (Confidence Labels)
 *   - backend FRMonthlyResult.confidence_label
 */

import {
  ShieldCheck,
  Database,
  FlaskConical,
  Info,
  AlertTriangle,
  HelpCircle,
  Tag,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'

export type ConfidenceLabel =
  | 'Confirmed-source'
  | 'Likely-source'
  | 'Likely-source / Scenario'
  | 'Participant-only'
  | 'Public-data / Participant-only-for-bankability'
  | 'Scenario'
  | 'Unverified'

const STYLES: Record<
  string,
  { bg: string; text: string; ring: string; help: string; Icon: LucideIcon }
> = {
  'Confirmed-source': {
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-300',
    ring: 'ring-emerald-500/30',
    help: 'Primary source supports the value AND project implementation matches.',
    Icon: ShieldCheck,
  },
  'Likely-source': {
    bg: 'bg-blue-500/15',
    text: 'text-blue-300',
    ring: 'ring-blue-500/30',
    help: 'Primary source supports the market rule. Project applicability is conditional.',
    Icon: Info,
  },
  'Likely-source / Scenario': {
    bg: 'bg-blue-500/15',
    text: 'text-blue-300',
    ring: 'ring-blue-500/30',
    help: 'Reasonable Romanian market assumption, presented as scenario — not bankable.',
    Icon: FlaskConical,
  },
  'Participant-only': {
    bg: 'bg-amber-500/15',
    text: 'text-amber-300',
    ring: 'ring-amber-500/30',
    help: 'Public data cannot prove this value. Participant settlement export required.',
    Icon: AlertTriangle,
  },
  'Public-data / Participant-only-for-bankability': {
    bg: 'bg-amber-500/15',
    text: 'text-amber-300',
    ring: 'ring-amber-500/30',
    help: 'Computed from public DAMAS marginal data. NOT a project-specific settlement number.',
    Icon: Database,
  },
  Scenario: {
    bg: 'bg-purple-500/15',
    text: 'text-purple-300',
    ring: 'ring-purple-500/30',
    help: 'Model assumption / sensitivity, not proven revenue.',
    Icon: FlaskConical,
  },
  Unverified: {
    bg: 'bg-slate-500/15',
    text: 'text-slate-300',
    ring: 'ring-slate-500/30',
    help: 'Needs counsel, operator confirmation, or source documents before use.',
    Icon: HelpCircle,
  },
}

const FALLBACK = STYLES.Unverified

export function ConfidenceBadge({
  label,
  className = '',
  short = false,
}: {
  label?: string | null
  className?: string
  short?: boolean
}) {
  if (!label) return null
  const style = STYLES[label] ?? FALLBACK
  const display = short ? shortLabel(label) : label
  const Icon = style.Icon
  return (
    <span
      title={style.help}
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ring-1 ${style.bg} ${style.text} ${style.ring} ${className}`}
    >
      <Icon className="w-3.5 h-3.5" aria-hidden="true" />
      {display}
    </span>
  )
}

export function PricingBasisBadge({
  basis,
  className = '',
}: {
  basis?: string | null
  className?: string
}) {
  if (!basis) return null
  const map: Record<string, { color: string; help: string; Icon: LucideIcon }> = {
    participant_bid: {
      color: 'bg-blue-500/15 text-blue-300 ring-blue-500/30',
      help: 'Revenue = participant bid price × cleared MWh (pay-as-bid).',
      Icon: Tag,
    },
    public_marginal: {
      color: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
      help: 'Revenue uses DAMAS public marginal prices, NOT participant settlement.',
      Icon: TrendingUp,
    },
    settlement_export: {
      color: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
      help: 'Revenue derived from real participant settlement export (bankable).',
      Icon: ShieldCheck,
    },
    scenario: {
      color: 'bg-purple-500/15 text-purple-300 ring-purple-500/30',
      help: 'Scenario / sensitivity assumption.',
      Icon: FlaskConical,
    },
  }
  const cfg =
    map[basis] ?? {
      color: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
      help: 'Unknown basis.',
      Icon: HelpCircle,
    }
  const Icon = cfg.Icon
  return (
    <span
      title={cfg.help}
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ring-1 ${cfg.color} ${className}`}
    >
      <Icon className="w-3.5 h-3.5" aria-hidden="true" />
      {basis}
    </span>
  )
}

function shortLabel(label: string): string {
  if (label.includes('/')) return label.split('/')[0].trim()
  return label
}

export default ConfidenceBadge
