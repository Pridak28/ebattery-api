'use client'

/**
 * /methodology — investor due-diligence page documenting where each BESS
 * number comes from. Mirrors the audit doc and code comments in a
 * customer-facing form so investors / lenders can evaluate sourcing,
 * methodology and regulatory backing without reading the codebase.
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  BookOpen,
  Database,
  Calculator,
  Scale,
  ShieldAlert,
  History,
  ExternalLink,
  Clock,
} from 'lucide-react'
import { dataApi } from '@/lib/api'

type DatasetRow = {
  dataset_id?: string
  min_delivery_date?: string
  max_delivery_date?: string
  bankability_level?: string
  source_kind?: string
}

type Manifest = {
  datasets?: DatasetRow[]
  generated_at_utc?: string
  version?: string
}

type ManifestState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; manifest: Manifest }

const DATA_SOURCES = [
  {
    id: 'opcom_pzu',
    name: 'OPCOM PZU (Day-Ahead Market)',
    fallbackRange: '2022-01-01 → 2025-09-30',
    pricingBasis: 'public_day_ahead_closing_price',
    bankability: 'scenario_public_market_only',
    description:
      'Hourly closing prices from the Romanian day-ahead exchange. Drives all PZU arbitrage simulations.',
    url: 'https://www.opcom.ro/pp/grafice_ip/raportPIPsiVolumTranzactionat.php?lang=ro',
  },
  {
    id: 'damas_clean',
    name: 'Transelectrica DAMAS (aFRR / mFRR)',
    fallbackRange: '2024-01-01 → 2025-09-30',
    pricingBasis: 'capacity_pay_as_bid + activation_marginal',
    bankability: 'historical_backtest_only',
    description:
      'Public capacity/activation history for aFRR and mFRR products. Pay-as-bid settlement since ANRE Order 60/2024 (2024-10-01).',
    url: 'https://newmarkets.transelectrica.ro/',
  },
  {
    id: 'fx_bnr',
    name: 'BNR FX Reference Rates',
    fallbackRange: '2022-01-01 → present',
    pricingBasis: 'public_central_bank_reference',
    bankability: 'scenario_public_market_only',
    description:
      'Daily RON/EUR reference rate from the National Bank of Romania, used for FX hedge cost modelling.',
    url: 'https://www.bnr.ro/Home.aspx',
  },
  {
    id: 'anre_orders',
    name: 'ANRE Regulatory Orders',
    fallbackRange: 'as published',
    pricingBasis: 'tariff_exemption_avoided_cost',
    bankability: 'scenario_public_market_only',
    description:
      'Tariff coefficients and storage exemption parameters from ANRE orders 56/2025, 60/2024 and 127/2021.',
    url: 'https://www.anre.ro/',
  },
] as const

const REGULATIONS = [
  { label: 'ANRE Order 60/2024 — pay-as-bid settlement (2024-10-01)', url: 'https://legislatie.just.ro/Public/DetaliiDocumentAfis/287809' },
  { label: 'ANRE Order 56/2025 — storage tariff exemption', url: 'https://legislatie.just.ro/Public/DetaliiDocumentAfis/299749' },
  { label: 'ANRE Order 127/2021 — FSE / RSF balancing services', url: 'https://legislatie.just.ro/Public/DetaliiDocument/260018' },
  { label: 'Law 123/2012 Art. 66³ — storage exemption legal basis', url: 'https://legislatie.just.ro/Public/DetaliiDocument/183460' },
  { label: 'EU Regulation 2019/943 — internal electricity market', url: 'https://eur-lex.europa.eu/eli/reg/2019/943/oj/' },
  { label: 'EU Regulation 2017/2195 (EBGL) — electricity balancing guideline', url: 'https://eur-lex.europa.eu/eli/reg/2017/2195/oj' },
  { label: 'REMIT Regulation 1227/2011 — wholesale market integrity', url: 'https://eur-lex.europa.eu/eli/reg/2011/1227/oj' },
  { label: 'ENTSO-E PICASSO — pan-European aFRR platform', url: 'https://www.entsoe.eu/network_codes/eb/picasso/' },
  { label: 'ENTSO-E MARI — pan-European mFRR platform', url: 'https://www.entsoe.eu/network_codes/eb/mari/' },
] as const

const COMPLIANCE_GATES = [
  'ANRE license category (storage / trader / supplier / producer)',
  'BRP / PRE balancing responsibility (own or delegated, Reg. 2019/943 Art. 5)',
  'OPCOM short-term participant registration (PZU / IDM)',
  'FSE / BSP convention with Transelectrica (ANRE Order 127/2021)',
  'DAMAS account active for FR product bidding and settlement',
  'Capacity reserve auction register entry (aFRR / mFRR)',
  'RSF / FCR qualification — separate contract from aFRR / mFRR',
  'OPCOM / Transelectrica financial guarantees and settlement account',
  'Real-time telemetry to TSO and ANRE-conformant settlement metering',
  'REMIT Reg. 1227/2011 acknowledgement and ACER registration',
  'Storage tariff exemption metering (Law 123 Art. 66³ + ANRE 56/2025)',
] as const

const PRETTY: Record<string, string> = {
  opcom_pzu: 'OPCOM PZU',
  damas_clean: 'DAMAS aFRR / mFRR',
  fx_bnr: 'BNR FX',
}

function SourceCard({
  source,
  liveRange,
}: {
  source: (typeof DATA_SOURCES)[number]
  liveRange: string | null
}) {
  return (
    <div
      className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 flex flex-col gap-2"
      style={{ background: 'linear-gradient(135deg, rgba(0, 255, 209, 0.04) 0%, rgba(14, 21, 45, 0.9) 100%)' }}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-white">{source.name}</h3>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
          {source.bankability}
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{source.description}</p>
      <dl className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1 text-[11px]">
        <dt className="text-slate-400">Coverage</dt>
        <dd className="font-mono text-slate-300">{liveRange ?? source.fallbackRange}</dd>
        <dt className="text-slate-400">Pricing basis</dt>
        <dd className="font-mono text-[#00ffd1]">{source.pricingBasis}</dd>
      </dl>
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-[11px] text-[#00ffd1] hover:underline mt-1"
      >
        Source <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  )
}

export default function MethodologyPage() {
  const [state, setState] = useState<ManifestState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    dataApi
      .getManifest()
      .then((res) => {
        if (cancelled) return
        setState({ kind: 'ready', manifest: res.data as Manifest })
      })
      .catch(() => {
        if (cancelled) return
        setState({ kind: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const liveRangeFor = (id: string): string | null => {
    if (state.kind !== 'ready') return null
    const ds = (state.manifest.datasets ?? []).find((d) => d.dataset_id === id)
    if (!ds?.min_delivery_date || !ds?.max_delivery_date) return null
    return `${ds.min_delivery_date} → ${ds.max_delivery_date}`
  }

  return (
    <div className="space-y-6 max-w-[1100px] mx-auto pb-12">
      {/* Header */}
      <header className="border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3 mb-2">
          <div
            className="p-2 rounded-lg"
            style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}
          >
            <BookOpen className="w-5 h-5 text-slate-900" />
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-white">Methodology &amp; Sources</h1>
            <p className="text-xs sm:text-sm text-slate-400">
              How battery-analytics-pro computes Romanian BESS revenue and ROI
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed max-w-3xl">
          This page consolidates the data lineage, calculation logic and regulatory backing for every
          number produced by the platform. It is intended for investors, lenders and counterparties
          performing due diligence on a Romanian BESS project.
        </p>
      </header>

      {/* Section 1 — Data sources */}
      <section aria-labelledby="data-sources-heading" className="space-y-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-[#00ffd1]" />
          <h2 id="data-sources-heading" className="text-base font-semibold text-white">
            1. Data sources
          </h2>
        </div>
        <p className="text-xs text-slate-400">
          All revenue projections are anchored on public market data. Coverage windows are pulled
          live from <code className="px-1 py-0.5 rounded bg-slate-800 text-[10px]">/api/v1/data/manifest</code>{' '}
          where available; otherwise the fallback range is shown.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {DATA_SOURCES.map((s) => (
            <SourceCard key={s.id} source={s} liveRange={liveRangeFor(s.id)} />
          ))}
        </div>
      </section>

      {/* Section 2 — Methodology */}
      <section aria-labelledby="methodology-heading" className="space-y-4">
        <div className="flex items-center gap-2">
          <Calculator className="w-4 h-4 text-[#00ffd1]" />
          <h2 id="methodology-heading" className="text-base font-semibold text-white">
            2. Calculation methodology
          </h2>
        </div>

        <article className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-white">PZU arbitrage</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Chronological, SOC-aware dispatch over the day-ahead curve. We brute-force the optimal
            (charge_start, discharge_start) pair across all 24×24 candidates, respecting battery
            capacity and SOC bounds. AC round-trip losses are split symmetrically as √η on both
            charge and discharge legs.
          </p>
          <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/60 rounded p-2 overflow-x-auto">
            <code>{`profit = Σ (P_disch · √η · price_disch) − Σ (P_charge / √η · price_charge)
optimal = argmax over (h_charge, h_discharge) ∈ {0..23}²`}</code>
          </pre>
        </article>

        <article className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-white">Frequency Regulation (aFRR / mFRR)</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Capacity revenue is pay-as-bid since ANRE Order 60/2024 (2024-10-01). Activation revenue
            is the product market_share × market_mwh, capped at the battery&apos;s daily energy
            throughput so we never claim more energy than physically deliverable.
          </p>
          <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/60 rounded p-2 overflow-x-auto">
            <code>{`R_capacity   = P_MW · hours · availability · price_capacity_pay_as_bid
R_activation = min(market_share · market_mwh, P_MW · 24 · cap_factor) · price_activation
R_total      = R_capacity + R_activation`}</code>
          </pre>
        </article>

        <article className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-white">Investment model</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Amortizing PMT loan, calendar + cycle fade on usable capacity, augmentation CAPEX in
            years 5 and 10, FX hedge cost on RON revenue, DSCR covenant flag, capacity-price
            compression with a regulatory floor, and a PICASSO go-live cliff that compresses pre-
            and post-launch capacity prices independently.
          </p>
          <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/60 rounded p-2 overflow-x-auto">
            <code>{`PMT       = P · r / (1 − (1+r)^−n)
SOH(t)    = 1 − cal_fade · t − cycle_fade · cycles(t)
DSCR(t)   = CFADS(t) / debt_service(t)        // covenant if < 1.20
P_cap(t)  = max(P_cap_0 · (1 − comp_rate)^t, P_floor)`}</code>
          </pre>
        </article>

        <article className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-white">Tariff exemption</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Law 123/2012 Art. 66³ combined with ANRE Order 56/2025 grants storage operators an
            exemption from grid tariffs on energy stored and reinjected. We model this as an
            avoided-cost stream over reinjected MWh, conditional on the tariff-exemption metering
            compliance gate being qualified.
          </p>
          <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/60 rounded p-2 overflow-x-auto">
            <code>{`R_exemption = MWh_reinjected · (T_grid + T_system + T_distribution_avoided)`}</code>
          </pre>
        </article>
      </section>

      {/* Section 3 — Regulatory references */}
      <section aria-labelledby="regulatory-heading" className="space-y-3">
        <div className="flex items-center gap-2">
          <Scale className="w-4 h-4 text-[#00ffd1]" />
          <h2 id="regulatory-heading" className="text-base font-semibold text-white">
            3. Regulatory references
          </h2>
        </div>
        <ul className="space-y-1.5">
          {REGULATIONS.map((r) => (
            <li key={r.url} className="text-xs text-slate-300 flex items-start gap-2">
              <span className="text-[#00ffd1] mt-0.5">•</span>
              <a
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-[#00ffd1] hover:underline inline-flex items-center gap-1"
              >
                {r.label}
                <ExternalLink className="w-3 h-3 opacity-60" />
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* Section 4 — Bankability & disclaimers */}
      <section aria-labelledby="bankability-heading" className="space-y-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-amber-400" />
          <h2 id="bankability-heading" className="text-base font-semibold text-white">
            4. Bankability &amp; disclaimers
          </h2>
        </div>

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 space-y-3 text-xs text-slate-300">
          <div>
            <p className="font-semibold text-amber-300 mb-1">
              source_kind: <code className="font-mono">unverified_snapshot</code>
            </p>
            <p className="text-slate-400 leading-relaxed">
              Inputs are public market snapshots collected from OPCOM and Transelectrica. They have
              not been independently audited or counter-signed by the issuing body, so they are
              suitable for scenario analysis but not for settlement-grade evidence.
            </p>
          </div>
          <div>
            <p className="font-semibold text-amber-300 mb-1">
              settlement_grade: <code className="font-mono">false</code>
            </p>
            <p className="text-slate-400 leading-relaxed">
              Outputs are scenario projections, not bankable settlement proof. A lender expecting
              term-sheet-grade numbers must reproduce these calculations against signed DAMAS
              extracts and audited project-specific operating data.
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <h3 className="text-sm font-semibold text-white mb-2">
            11 compliance gates required for legal participation
          </h3>
          <ol className="space-y-1 text-xs text-slate-400 list-decimal list-inside">
            {COMPLIANCE_GATES.map((g) => (
              <li key={g} className="leading-relaxed">
                {g}
              </li>
            ))}
          </ol>
        </div>

        <p className="text-[11px] text-slate-400 italic leading-relaxed">
          This page is for informational purposes only and does not constitute legal, tax, or
          investment advice. Always consult qualified Romanian energy counsel and your own technical
          advisors before committing capital.
        </p>
      </section>

      {/* Section 5 — Audit trail */}
      <section aria-labelledby="audit-heading" className="space-y-3">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-[#00ffd1]" />
          <h2 id="audit-heading" className="text-base font-semibold text-white">
            5. Audit trail
          </h2>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 space-y-2 text-xs">
          {state.kind === 'loading' && (
            <p className="text-slate-400" aria-busy="true">
              Loading data manifest…
            </p>
          )}
          {state.kind === 'error' && (
            <p className="text-amber-300">
              Could not reach{' '}
              <code className="font-mono px-1 bg-slate-800 rounded">/api/v1/data/manifest</code>.
              Backend may be sleeping or offline.
            </p>
          )}
          {state.kind === 'ready' && (
            <>
              <div className="flex items-center justify-between text-slate-300">
                <span className="text-slate-400">Manifest generated</span>
                <span className="font-mono flex items-center gap-1">
                  <Clock className="w-3 h-3 opacity-60" />
                  {state.manifest.generated_at_utc ?? '—'}
                </span>
              </div>
              {state.manifest.version && (
                <div className="flex items-center justify-between text-slate-300">
                  <span className="text-slate-400">Manifest version</span>
                  <span className="font-mono">{state.manifest.version}</span>
                </div>
              )}
              <ul className="space-y-1 pt-1 border-t border-slate-800">
                {(state.manifest.datasets ?? []).map((d) => (
                  <li
                    key={d.dataset_id ?? Math.random()}
                    className="flex items-center justify-between text-slate-300"
                  >
                    <span className="text-slate-400">
                      {PRETTY[d.dataset_id ?? ''] ?? d.dataset_id ?? 'dataset'}
                    </span>
                    <span className="font-mono text-slate-400">
                      {d.min_delivery_date ?? '—'} → {d.max_delivery_date ?? '—'}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <p className="text-[11px] text-slate-400">
          Source code, commit hashes and the underlying audit document are tracked in the project
          repository. Run the simulators on the{' '}
          <Link href="/pzu" className="text-[#00ffd1] hover:underline">
            PZU
          </Link>
          ,{' '}
          <Link href="/fr-simulator" className="text-[#00ffd1] hover:underline">
            FR
          </Link>{' '}
          and{' '}
          <Link href="/investment" className="text-[#00ffd1] hover:underline">
            Investment
          </Link>{' '}
          pages to reproduce any number shown in marketing materials.
        </p>
      </section>
    </div>
  )
}
