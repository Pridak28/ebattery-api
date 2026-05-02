'use client'

/**
 * ComplianceGatesWizard — interactive 3-state toggle panel for the 11 Romanian /
 * EU regulatory prerequisites a BESS project must satisfy before it can lawfully
 * earn the simulated revenues. Mirrors the cascade logic from
 * `backend/app/models/investment.py::ComplianceGates.revenue_streams_blocked` so
 * the UI updates instantly without a backend round-trip.
 */

import { ShieldCheck, AlertTriangle, CheckCircle2 } from 'lucide-react'

export type GateStatus = 'not_declared' | 'in_progress' | 'qualified'

export type GateName =
  | 'anre_license_status'
  | 'opcom_short_term_participant'
  | 'brp_pre_responsibility'
  | 'fse_bsp_convention'
  | 'damas_access'
  | 'capacity_reserve_auction_register'
  | 'rsf_fcr_qualification'
  | 'settlement_account_and_guarantees'
  | 'telemetry_and_metering'
  | 'remit_acknowledgement'
  | 'storage_tariff_exemption_metering'

export type ComplianceGatesValue = Record<GateName, GateStatus>

// Order = upstream-to-downstream cascade order, matching backend logic.
const GATES: { name: GateName; label: string; description: string }[] = [
  {
    name: 'anre_license_status',
    label: 'ANRE License Status',
    description:
      'ANRE Order 6/2025 license category (storage/trader/supplier/producer). Most upstream gate — blocks ALL revenue if missing.',
  },
  {
    name: 'brp_pre_responsibility',
    label: 'BRP / PRE Responsibility',
    description:
      'BRP/PRE responsibility (own or delegated). Required by Reg. 2019/943 Art. 5. Blocks ALL market revenue if missing.',
  },
  {
    name: 'opcom_short_term_participant',
    label: 'OPCOM Short-Term Participant',
    description: 'OPCOM PZU/IDM participant registration — required for day-ahead/intraday arbitrage.',
  },
  {
    name: 'fse_bsp_convention',
    label: 'FSE / BSP Convention',
    description: 'FSE/BSP convention with Transelectrica for aFRR/mFRR participation (ANRE Order 127/2021).',
  },
  {
    name: 'damas_access',
    label: 'DAMAS Access',
    description: 'Active DAMAS account for FR product bidding/settlement.',
  },
  {
    name: 'capacity_reserve_auction_register',
    label: 'Capacity Reserve Auction Register',
    description: 'Registered in the capacity reserve auction register (aFRR/mFRR).',
  },
  {
    name: 'rsf_fcr_qualification',
    label: 'RSF / FCR Qualification',
    description: 'Separate RSF qualification + contract for FCR — NOT covered by aFRR/mFRR registration.',
  },
  {
    name: 'settlement_account_and_guarantees',
    label: 'Settlement Account & Guarantees',
    description: 'OPCOM/Transelectrica financial guarantees deposited; settlement account active.',
  },
  {
    name: 'telemetry_and_metering',
    label: 'Telemetry & Metering',
    description: 'Real-time telemetry to TSO + ANRE-conformant settlement metering.',
  },
  {
    name: 'remit_acknowledgement',
    label: 'REMIT Acknowledgement',
    description: 'Reg. 1227/2011 — registered with ACER (if applicable), inside information policy in place.',
  },
  {
    name: 'storage_tariff_exemption_metering',
    label: 'Storage Tariff Exemption Metering',
    description: 'Metering capable of distinguishing stored/reinjected energy under Law 123 Art. 66³ + ANRE Order 56/2025.',
  },
]

export const DEFAULT_COMPLIANCE_GATES: ComplianceGatesValue = GATES.reduce((acc, g) => {
  acc[g.name] = 'not_declared'
  return acc
}, {} as ComplianceGatesValue)

/**
 * Mirror of `ComplianceGates.revenue_streams_blocked` from
 * `backend/app/models/investment.py`. Keep in sync with the backend cascade.
 */
export function getBlockedStreams(gates: ComplianceGatesValue): string[] {
  const blocked: string[] = []
  if (gates.anre_license_status !== 'qualified') {
    blocked.push('ALL revenue (no ANRE-recognized activity)')
    return blocked
  }
  if (gates.brp_pre_responsibility !== 'qualified') {
    blocked.push('ALL market revenue (no BRP/PRE)')
    return blocked
  }
  if (gates.opcom_short_term_participant !== 'qualified') blocked.push('PZU / IDM arbitrage')
  if (
    gates.fse_bsp_convention !== 'qualified' ||
    gates.damas_access !== 'qualified' ||
    gates.capacity_reserve_auction_register !== 'qualified'
  ) {
    blocked.push('aFRR / mFRR capacity + activation')
  }
  if (gates.rsf_fcr_qualification !== 'qualified') blocked.push('FCR (RSF)')
  if (gates.storage_tariff_exemption_metering !== 'qualified') {
    blocked.push('Storage tariff exemption (avoided cost) per Law 123 Art. 66³')
  }
  return blocked
}

/** First not-yet-qualified gate in cascade order — used for "fix first" highlight. */
function getCascadeBlocker(gates: ComplianceGatesValue): GateName | null {
  for (const g of GATES) if (gates[g.name] !== 'qualified') return g.name
  return null
}

const STATUS_OPTIONS: { value: GateStatus; label: string; activeClasses: string }[] = [
  { value: 'not_declared', label: 'Not declared', activeClasses: 'bg-slate-700 text-slate-100 border-slate-500' },
  { value: 'in_progress', label: 'In progress', activeClasses: 'bg-amber-600/30 text-amber-200 border-amber-500' },
  { value: 'qualified', label: 'Qualified', activeClasses: 'bg-emerald-600/30 text-emerald-200 border-emerald-500' },
]

export interface ComplianceGatesWizardProps {
  value: ComplianceGatesValue
  onChange: (next: ComplianceGatesValue) => void
  blockedStreams?: string[]
  className?: string
}

export function ComplianceGatesWizard({
  value,
  onChange,
  blockedStreams,
  className = '',
}: ComplianceGatesWizardProps) {
  const qualifiedCount = GATES.filter((g) => value[g.name] === 'qualified').length
  const total = GATES.length
  const progressPct = (qualifiedCount / total) * 100
  const cascadeBlocker = getCascadeBlocker(value)
  const effectiveBlocked = blockedStreams ?? getBlockedStreams(value)
  const hasBlocked = effectiveBlocked.length > 0

  const setGate = (name: GateName, status: GateStatus) => onChange({ ...value, [name]: status })

  const barBg =
    qualifiedCount === total
      ? 'linear-gradient(90deg, #10b981, #00ffd1)'
      : qualifiedCount > 0
      ? 'linear-gradient(90deg, #f59e0b, #00ffd1)'
      : '#475569'

  return (
    <div className={`rounded-lg border border-slate-700 bg-slate-900/50 ${className}`}>
      <div className="flex items-center gap-2 px-3 sm:px-4 py-2 sm:py-3 border-b border-slate-700">
        <ShieldCheck className="w-4 h-4 text-[#00ffd1]" />
        <h3 className="text-xs sm:text-sm font-semibold uppercase tracking-wider text-slate-300">
          Compliance Gates Wizard
        </h3>
        <span className="ml-auto text-[10px] sm:text-xs text-slate-400 font-mono">
          {qualifiedCount} of {total} qualified
        </span>
      </div>

      <div className="px-3 sm:px-4 pt-3">
        <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
          <div className="h-full transition-all duration-300" style={{ width: `${progressPct}%`, background: barBg }} />
        </div>
        <p className="mt-1 text-[10px] sm:text-xs text-slate-400">
          {qualifiedCount === 0
            ? 'No gates qualified yet — every revenue stream is currently blocked.'
            : qualifiedCount === total
            ? 'All gates qualified — revenue streams unlocked.'
            : `${qualifiedCount} of ${total} gates qualified.`}
        </p>
      </div>

      <div className="p-3 sm:p-4 space-y-2">
        {GATES.map((g) => {
          const current = value[g.name]
          const isCascadeBlocker = cascadeBlocker === g.name
          const rowCls = isCascadeBlocker
            ? 'border-amber-500/60 bg-amber-500/5'
            : current === 'qualified'
            ? 'border-emerald-700/40 bg-emerald-900/10'
            : 'border-slate-700 bg-slate-900/40'
          return (
            <div key={g.name} className={`rounded border p-2 sm:p-3 transition-colors ${rowCls}`}>
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-xs sm:text-sm font-semibold text-white">{g.label}</p>
                    {isCascadeBlocker && (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-500/20 border border-amber-500/40 px-1.5 py-0.5 text-[9px] sm:text-[10px] uppercase tracking-wider text-amber-200">
                        <AlertTriangle className="w-3 h-3" /> Fix first
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[10px] sm:text-[11px] text-slate-400 leading-snug">{g.description}</p>
                </div>
                <div
                  role="radiogroup"
                  aria-label={`${g.label} status`}
                  className="inline-flex shrink-0 rounded border border-slate-700 overflow-hidden self-start"
                >
                  {STATUS_OPTIONS.map((opt) => {
                    const active = current === opt.value
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setGate(g.name, opt.value)}
                        className={`px-2 sm:px-2.5 py-1 text-[10px] sm:text-[11px] font-medium border-r last:border-r-0 transition-colors ${
                          active
                            ? opt.activeClasses
                            : 'bg-slate-900 text-slate-400 border-slate-700 hover:bg-slate-800 hover:text-slate-200'
                        }`}
                      >
                        {opt.label}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="border-t border-slate-700 p-3 sm:p-4">
        {hasBlocked ? (
          <div className="rounded border border-amber-500/40 bg-amber-500/5 p-2 sm:p-3">
            <p className="text-[10px] sm:text-[11px] uppercase tracking-wider text-amber-300 font-semibold mb-1.5 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> Revenue streams currently blocked
            </p>
            <ul className="space-y-1 text-[11px] sm:text-xs text-amber-100/80">
              {effectiveBlocked.map((s, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-amber-500 mt-0.5">▸</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="rounded border border-emerald-500/40 bg-emerald-500/5 p-2 sm:p-3 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <p className="text-[11px] sm:text-xs text-emerald-200">
              All revenue streams unlocked — every compliance gate is qualified.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

export default ComplianceGatesWizard
