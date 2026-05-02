'use client'

/**
 * Investor Quick-Look — single printable A4 one-pager an investor can hand
 * to a lender or co-investor without explanation. Reads the most-recent
 * saved report from localStorage (`bess_saved_reports_v1`); if none exists
 * we fall back to a "go save one first" prompt rather than guessing.
 *
 * SSR-safe: localStorage access is gated through a useEffect; nothing
 * touches `window` during render.
 */

import { useEffect, useMemo, useState } from 'react'
import { Printer, ShieldCheck, ShieldAlert, AlertTriangle, FileText } from 'lucide-react'
import { formatCurrency, formatCompact, formatPercentage } from '@/lib/utils'

const STORAGE_KEY = 'bess_saved_reports_v1'

type SavedReport = {
  id: string
  name: string
  savedAt: string
  params: any
  analysis: any
}

function loadLatest(): SavedReport | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length === 0) return null
    // useSavedReports persists newest-first; defensive sort by savedAt desc anyway.
    const sorted = [...parsed].sort(
      (a, b) => (Date.parse(b?.savedAt ?? '') || 0) - (Date.parse(a?.savedAt ?? '') || 0),
    )
    return (sorted[0] as SavedReport) || null
  } catch { return null }
}

type IrrTier = { label: string; color: string; bg: string }
function tierForIrr(irr: number | null | undefined): IrrTier {
  if (irr == null || Number.isNaN(irr)) return { label: 'n/a', color: '#6b7280', bg: '#f3f4f6' }
  if (irr > 12) return { label: 'strong', color: '#047857', bg: '#d1fae5' }
  if (irr >= 6) return { label: 'marginal', color: '#b45309', bg: '#fef3c7' }
  return { label: 'weak', color: '#b91c1c', bg: '#fee2e2' }
}

function fmtDateLong(iso: string): string {
  try { return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) }
  catch { return iso }
}

const GATE_TOTAL = 11

export default function InvestorSummaryPage() {
  const [hydrated, setHydrated] = useState(false)
  const [report, setReport] = useState<SavedReport | null>(null)

  useEffect(() => {
    setReport(loadLatest())
    setHydrated(true)
  }, [])

  const computed = useMemo(() => {
    if (!report) return null
    const a = report.analysis ?? {}
    const p = report.params ?? {}

    const fr = a.fr_scenario ?? {}
    const pzu = a.pzu_scenario ?? {}
    const recommended = a.recommended_scenario ?? 'FR'
    const headline = recommended === 'PZU' ? pzu : fr
    const lifetimeIrr = recommended === 'PZU' ? a.pzu_lifetime_irr_pct : a.fr_lifetime_irr_pct

    // Tariff exemption Y1 — first-year cashflow row carries it; prefer the recommended
    // scenario's cashflow, then either side as fallback.
    const cfList: any[] = recommended === 'PZU'
      ? (a.pzu_cashflow ?? a.fr_cashflow ?? [])
      : (a.fr_cashflow ?? a.pzu_cashflow ?? [])
    const altYr1 = (a.fr_cashflow?.[0] ?? a.pzu_cashflow?.[0] ?? {})
    const tariffY1 = Number(cfList[0]?.tariff_exemption_eur ?? altYr1.tariff_exemption_eur ?? 0)

    const frRevY1 = Number(fr.gross_revenue_eur ?? 0)
    const pzuRevY1 = Number(pzu.gross_revenue_eur ?? 0)

    // DSCR snapshot — drawn from FR cashflow (the lender covenant view).
    const dscrSeries: number[] = (a.fr_cashflow ?? [])
      .map((cf: any) => Number(cf?.dscr ?? 0))
      .filter((x: number) => Number.isFinite(x) && x > 0)
    const violations: number[] = Array.isArray(a.dscr_violation_years) ? a.dscr_violation_years : []
    const blockedStreams: string[] = Array.isArray(a.compliance_revenue_streams_blocked)
      ? a.compliance_revenue_streams_blocked : []

    // Bankability — driven by recommended scenario's pricing_basis.
    const pricingBasis = headline.pricing_basis ?? 'scenario'
    const settlementGrade = pricingBasis === 'settlement_export'
    const bankabilityLevel = settlementGrade
      ? 'bankable_settlement_grade'
      : pricingBasis === 'participant_bid' ? 'participant_only_for_bankability'
      : pricingBasis === 'public_marginal' ? 'scenario_public_market_only'
      : 'historical_backtest_only'

    // Compliance gates qualified count (Object.values is string[] only when typed).
    const qualified = Object.values(a.compliance_gates ?? {})
      .filter((v) => v === 'qualified').length

    return {
      capex: Number(p.total_investment_eur ?? 0),
      powerMw: Number(p.power_mw ?? 10),
      capacityMwh: Number(p.capacity_mwh ?? 20),
      headlineNet: Number(headline.net_profit_after_debt_eur ?? 0),
      lifetimeIrr: lifetimeIrr == null ? null : Number(lifetimeIrr),
      recommended,
      frRevY1, pzuRevY1, tariffY1,
      combinedY1: frRevY1 + pzuRevY1 + tariffY1,
      y1Dscr: dscrSeries[0] ?? 0,
      worstDscr: dscrSeries.length ? Math.min(...dscrSeries) : 0,
      violationCount: violations.length,
      qualified,
      mostBlocking: blockedStreams[0] ?? null,
      bankabilityLevel, settlementGrade, pricingBasis,
      auditRef: a.audit_reference ?? 'audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT.md',
    }
  }, [report])

  // Gate render: keep SSR markup deterministic (localStorage is client-only).
  if (!hydrated) {
    return <div className="p-6 text-slate-400 text-sm">Loading Investor Quick-Look…</div>
  }

  if (!report || !computed) {
    return (
      <div className="p-6">
        <div className="max-w-xl rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h1 className="text-lg font-semibold text-white mb-2">No saved report yet</h1>
          <p className="text-sm text-slate-400">
            Run an analysis on the <span className="text-[#00ffd1]">Investment</span> page first,
            then save it from there to generate a Quick-Look.
          </p>
        </div>
      </div>
    )
  }

  const tier = tierForIrr(computed.lifetimeIrr)

  return (
    <>
      {/* Screen-only toolbar */}
      <div className="no-print mb-4 flex items-center justify-between gap-3">
        <div className="text-xs text-slate-400">
          Loaded report:{' '}
          <span className="font-mono text-slate-200">{report.name}</span>
          {' · saved '}
          <span className="font-mono">{fmtDateLong(report.savedAt)}</span>
        </div>
        <button
          type="button"
          onClick={() => window.print()}
          className="inline-flex items-center gap-2 rounded bg-[#00ffd1] px-3 py-1.5 text-xs font-bold uppercase tracking-wide text-slate-900 hover:bg-[#00e6bb]"
        >
          <Printer className="h-3.5 w-3.5" /> Print this page
        </button>
      </div>

      <div className="ql-page">
        {/* 1 — Header */}
        <div className="ql-row" style={{ alignItems: 'flex-start', gap: '12px' }}>
          <div className="ql-col">
            <div className="ql-h1">BESS Investor Quick-Look</div>
            <div className="ql-meta">
              Generated {fmtDateLong(new Date().toISOString())}
              {' · '}sourced from saved analysis “{report.name}” ({fmtDateLong(report.savedAt)})
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="ql-meta">Project sizing</div>
            <div className="ql-kbd" style={{ fontSize: 13, fontWeight: 700 }}>
              {computed.powerMw} MW / {computed.capacityMwh} MWh
            </div>
            <div className="ql-meta" style={{ marginTop: 2 }}>CAPEX</div>
            <div className="ql-kbd" style={{ fontSize: 13, fontWeight: 700 }}>
              {formatCurrency(computed.capex, { decimals: 0 })}
            </div>
          </div>
        </div>

        <div className="ql-divider" />

        {/* 2 — Headline */}
        <div
          style={{
            background: tier.bg,
            border: `1px solid ${tier.color}55`,
            borderRadius: 8,
            padding: '12px 14px',
          }}
        >
          <div className="ql-meta" style={{ color: tier.color, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Headline ({computed.recommended})
          </div>
          <div className="ql-headline" style={{ color: tier.color }}>
            FR Y1 net profit:{' '}
            {formatCompact(computed.headlineNet)}
            {' · '}Lifetime IRR:{' '}
            {computed.lifetimeIrr == null
              ? 'loss-making'
              : formatPercentage(computed.lifetimeIrr)}
          </div>
          <div className="ql-meta" style={{ color: tier.color, marginTop: 3 }}>
            Bankability tier: <strong>{tier.label}</strong> ({'>'}12 % strong · 6–12 % marginal · {'<'}6 % weak)
          </div>
        </div>

        {/* 3 + 4 — Revenue table + bankability strip */}
        <div className="ql-row" style={{ marginTop: 10 }}>
          <div className="ql-col">
            <div className="ql-h2">Revenue Breakdown (Year 1)</div>
            <div className="ql-card" style={{ padding: 0 }}>
              <table className="ql-table">
                <thead>
                  <tr>
                    <th>Stream</th>
                    <th style={{ textAlign: 'right' }}>Y1 (€)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>FR aFRR (capacity + activation)</td>
                    <td className="num">{formatCurrency(computed.frRevY1, { decimals: 0 })}</td>
                  </tr>
                  <tr>
                    <td>PZU arbitrage (day-ahead)</td>
                    <td className="num">{formatCurrency(computed.pzuRevY1, { decimals: 0 })}</td>
                  </tr>
                  <tr>
                    <td>Tariff exemption (avoided cost, Law 123 Art. 66³)</td>
                    <td className="num">{formatCurrency(computed.tariffY1, { decimals: 0 })}</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: 700 }}>Combined</td>
                    <td className="num" style={{ fontWeight: 700 }}>
                      {formatCurrency(computed.combinedY1, { decimals: 0 })}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="ql-col" style={{ flex: '0 0 38%' }}>
            <div className="ql-h2">Bankability Strip</div>
            <div className="ql-card">
              <div style={{ marginBottom: 6 }}>
                <span
                  className="ql-badge"
                  style={{
                    background: computed.settlementGrade ? '#d1fae5' : '#fef3c7',
                    color: computed.settlementGrade ? '#047857' : '#b45309',
                  }}
                >
                  {computed.bankabilityLevel.replace(/_/g, ' ')}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                {computed.settlementGrade
                  ? <ShieldCheck className="h-3.5 w-3.5" color="#047857" />
                  : <ShieldAlert className="h-3.5 w-3.5" color="#b45309" />}
                <span className="ql-kbd">
                  Settlement-grade: {computed.settlementGrade ? '✓' : '✗'}
                </span>
              </div>
              <div className="ql-meta">
                Source: <span className="ql-kbd">OPCOM PZU + DAMAS aFRR</span>
              </div>
              <div className="ql-meta" style={{ marginTop: 2 }}>
                Pricing basis: <span className="ql-kbd">{computed.pricingBasis}</span>
              </div>
            </div>
          </div>
        </div>

        {/* 5 + 6 — DSCR snapshot + Compliance gates */}
        <div className="ql-row" style={{ marginTop: 10 }}>
          <div className="ql-col">
            <div className="ql-h2">DSCR Snapshot</div>
            <div className="ql-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span>Y1 DSCR</span>
                <span className="ql-kbd" style={{ fontWeight: 700 }}>
                  {computed.y1Dscr ? computed.y1Dscr.toFixed(2) + 'x' : 'n/a'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span>Worst-year DSCR</span>
                <span
                  className="ql-kbd"
                  style={{
                    fontWeight: 700,
                    color: computed.worstDscr && computed.worstDscr < 1.2 ? '#b91c1c' : '#111827',
                  }}
                >
                  {computed.worstDscr ? computed.worstDscr.toFixed(2) + 'x' : 'n/a'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Covenant breaches (DSCR &lt; 1.20)</span>
                <span
                  className="ql-kbd"
                  style={{
                    fontWeight: 700,
                    color: computed.violationCount > 0 ? '#b91c1c' : '#047857',
                  }}
                >
                  {computed.violationCount}
                </span>
              </div>
            </div>
          </div>

          <div className="ql-col">
            <div className="ql-h2">Compliance Gates</div>
            <div className="ql-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span>Qualified</span>
                <span
                  className="ql-kbd"
                  style={{
                    fontWeight: 700,
                    color: computed.qualified === GATE_TOTAL ? '#047857' : '#b45309',
                  }}
                >
                  {computed.qualified} / {GATE_TOTAL}
                </span>
              </div>
              <div className="ql-meta" style={{ marginBottom: 2 }}>Most-blocking missing gate</div>
              <div className="ql-kbd" style={{ fontSize: 10.5 }}>
                {computed.mostBlocking ?? 'None — all streams unlocked'}
              </div>
            </div>
          </div>
        </div>

        {/* 7 — Risk factors */}
        <div style={{ marginTop: 10 }}>
          <div className="ql-h2">Risk Factors (auto-derived)</div>
          <div className="ql-card">
            <ul className="ql-risk-list">
              <li>
                <strong>PICASSO go-live cliff</strong> modeled — cross-border aFRR exchange
                opens RO market to platform-wide marginal pricing; Y1 figures assume RO-only regime.
              </li>
              <li>
                <strong>MARI 2026-04-01 minimum-bid threshold</strong> — mFRR product unification
                may reset capacity rents; not in baseline.
              </li>
              <li>
                <strong>Pay-as-bid since ANRE Order 60/2024</strong> — no marginal-clearing uplift
                on aFRR capacity since enforcement; revenue assumes participant-bid economics.
              </li>
            </ul>
          </div>
        </div>

        {/* 8 — Disclaimer */}
        <div className="ql-disclaimer">
          <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <AlertTriangle className="h-3 w-3 mt-0.5" color="#b45309" />
            <div>
              <strong>Not bankable settlement proof unless source labeled <code>settlement_export</code>.</strong>
              {' '}Year-1 figures use historical / participant-bid public pricing; lender DD must be
              backed by signed BSP/FSE settlement extracts.
            </div>
          </div>
          <div style={{ marginTop: 4, display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <FileText className="h-3 w-3 mt-0.5" color="#4b5563" />
            <div>Audit reference: <span className="ql-kbd">{computed.auditRef}</span></div>
          </div>
        </div>
      </div>
    </>
  )
}
