'use client'

import { BarChart3, Zap, TrendingUp, Battery, Activity, Clock, Shield, ArrowUpDown, Info, ChevronRight, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import StatusLabel from '@/components/ui/StatusLabel'
import ApiHealthBadge from '@/components/ui/ApiHealthBadge'
import DataFreshnessBadge from '@/components/ui/DataFreshnessBadge'
import HealthDiagnostics from '@/components/ui/HealthDiagnostics'
import LiveMarketChart from '@/components/charts/LiveMarketChart'
import OnboardingTour, { TourStep } from '@/components/ui/OnboardingTour'
import { useOnboardingTour } from '@/hooks/useOnboardingTour'

const TOUR_STEPS: TourStep[] = [
  {
    title: 'Welcome',
    description:
      'Welcome to eBattery Analytics. This tool models Romanian BESS revenue using real OPCOM PZU + DAMAS aFRR data. Click Next to learn the key sections.',
  },
  {
    // W5-FRONTEND (T-MASTER-20260503T112225Z): the prior copy here read
    // `title: 'Live data'` / `description: 'All numbers are backed by
    // real Romanian market data, refreshed daily.'`. Both halves drifted
    // from what the dashboard actually shows:
    //   1. The two summary cards above the badge (aFRR €4.3M, PZU €1.8M)
    //      are explicitly tagged `ILLUSTRATIVE` and quote hardcoded
    //      figures — they are NOT backed by real market data; only the
    //      simulators on /pzu, /fr-simulator and /investment are. So
    //      "all numbers are backed by real Romanian market data" was
    //      false on the very page the tour ran on.
    //   2. The badge itself (`DataFreshnessBadge`) renders the actual
    //      delivery-date range pulled from `/api/v1/data/manifest` and
    //      lights up an amber `stale` chip when the lag exceeds 60 days
    //      — so "refreshed daily" overclaims the cadence.
    //   3. The `Live data` step title reintroduces the same overconfident
    //      "live" framing the W1 / W2 unsafe-wording passes explicitly
    //      downgraded on the `/investment` header `LIVE` chip
    //      (commit 3275e29) and the global Sidebar `Live Data` chip
    //      (commit 5a913e1) — see SOURCE_CONFIDENCE_AUDIT §7
    //      ("live vs historical" wording).
    // Reframed to match the badge's actual heading ("Market data backing")
    // and to scope the claim to what the badge actually shows: the date
    // range and freshness lag of the manifest datasets feeding the
    // simulators, not a blanket guarantee about every figure on the page.
    title: 'Market data backing',
    description:
      'The badge above reads /api/v1/data/manifest and shows the delivery-date range and freshness lag for the OPCOM PZU + DAMAS aFRR datasets feeding the simulators. The two summary cards above it are tagged ILLUSTRATIVE — for real numbers, run a simulator.',
    target: '[data-tour="step-2"]',
    placement: 'bottom',
  },
  {
    title: 'Live backtest',
    description:
      'This 12-month backtest is computed live from API. Replaces the previous illustrative chart.',
    target: '[data-tour="step-3"]',
    placement: 'top',
  },
  {
    title: 'Try the simulators',
    description:
      'Run PZU arbitrage, FR simulator, or Investment analysis. Saved reports persist locally.',
    target: '[data-tour="step-4"]',
    placement: 'top',
  },
]

const modules = [
  {
    name: 'PZU Analysis',
    description: 'Day-Ahead Market arbitrage simulation',
    href: '/pzu',
    icon: BarChart3,
  },
  {
    name: 'FR Simulator',
    description: 'Frequency Regulation revenue simulation',
    href: '/fr-simulator',
    icon: Zap,
  },
  {
    name: 'Investment Analysis',
    description: 'Financial modeling and ROI comparison',
    href: '/investment',
    icon: TrendingUp,
  },
]

export default function Dashboard() {
  const tour = useOnboardingTour(TOUR_STEPS.length)
  return (
    <div className="space-y-4 sm:space-y-6 max-w-[1600px] mx-auto">
      {/* Bloomberg-Style Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-4 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <Activity className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
            </div>
            <div>
              <h1 className="text-lg sm:text-xl md:text-2xl font-bold text-white flex items-center gap-1 sm:gap-2">
                <span className="gradient-text">eBattery</span>
                <span className="text-white">Analytics</span>
              </h1>
              <p className="text-xs sm:text-sm text-slate-400">
                Romanian Energy Market • BESS Revenue Platform
              </p>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          {/* Real backend health probe replaces the static `LIVE` label
              flagged by audit BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01. */}
          <ApiHealthBadge />
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg" style={{ background: 'rgba(0, 255, 209, 0.1)', border: '1px solid rgba(0, 255, 209, 0.2)' }}>
            <Battery className="w-3 h-3 sm:w-4 sm:h-4" style={{ color: '#00ffd1' }} />
            <span className="text-slate-300 text-xs sm:text-sm font-mono">10MW/20MWh</span>
          </div>
          <div className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-[#00ffd1]/10 border border-[#00ffd1]/30">
            <span className="text-xs sm:text-sm text-[#00ffd1] font-mono">RO-BESS</span>
          </div>
        </div>
      </div>

      {/* Bloomberg-Style Market Summary Panel
          Audit fix: cards previously showed hardcoded annual numbers as if
          they were live API output. Now tagged ILLUSTRATIVE so investors
          know to run the simulators for real numbers. */}
      <div className="grid grid-cols-2 gap-2 sm:gap-4">
        <div className="bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg sm:rounded-xl p-3 sm:p-4">
          <div className="flex items-center justify-between gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
            <div className="flex items-center gap-1.5">
              <Zap className="w-3 h-3 sm:w-4 sm:h-4 text-[#00ffd1]" />
              <span className="text-[9px] sm:text-xs text-slate-400 uppercase tracking-wider">aFRR Revenue</span>
            </div>
            <StatusLabel kind="ILLUSTRATIVE" />
          </div>
          <p className="text-lg sm:text-2xl font-bold text-[#00ffd1] font-mono">€4.3M</p>
          <p className="text-[10px] sm:text-xs text-slate-400 mt-0.5 sm:mt-1">Projected annual (10 MW)</p>
          <p className="text-[10px] text-slate-400 mt-0.5">Source: DAMAS aFRR history 2024-2025 · Run FR Simulator for real number</p>
        </div>
        <div className="bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg sm:rounded-xl p-3 sm:p-4">
          <div className="flex items-center justify-between gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
            <div className="flex items-center gap-1.5">
              <BarChart3 className="w-3 h-3 sm:w-4 sm:h-4 text-blue-400" />
              <span className="text-[9px] sm:text-xs text-slate-400 uppercase tracking-wider">PZU Revenue</span>
            </div>
            <StatusLabel kind="ILLUSTRATIVE" />
          </div>
          <p className="text-lg sm:text-2xl font-bold text-blue-400 font-mono">€1.8M</p>
          <p className="text-[10px] sm:text-xs text-slate-400 mt-0.5 sm:mt-1">Projected annual (20 MWh)</p>
          <p className="text-[10px] text-slate-400 mt-0.5">Source: OPCOM PZU history 2022-2025 · Run PZU page for real number</p>
        </div>
      </div>

      {/* Live data freshness — single piece of dashboard wired to the API,
          gives investors something concretely "live" alongside the
          ILLUSTRATIVE summary cards. */}
      <div data-tour="step-2">
        <DataFreshnessBadge />
      </div>

      {/* Live 12-month market backtest from real OPCOM PZU + DAMAS aFRR data.
          Replaces the previous hardcoded MARKET_DATA "illustrative" series. */}
      <div data-tour="step-3">
        <LiveMarketChart />
      </div>

      {/* Two Column Info Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">

        {/* PZU - Day-Ahead Market Arbitrage */}
        <div className="rounded-lg sm:rounded-xl p-4 sm:p-6 card-hover" style={{ background: 'linear-gradient(135deg, rgba(0, 255, 209, 0.1) 0%, rgba(14, 21, 45, 0.9) 100%)', border: '1px solid rgba(0, 255, 209, 0.3)' }}>
          <div className="flex items-center gap-2 sm:gap-3 mb-3 sm:mb-4">
            <div className="rounded-lg p-2 sm:p-2.5" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
            </div>
            <div>
              <h2 className="text-base sm:text-xl font-bold text-white">PZU - Day-Ahead Market</h2>
              <p style={{ color: '#00ffd1' }} className="text-xs sm:text-sm">Energy Arbitrage Strategy</p>
            </div>
          </div>

          <div className="space-y-4 text-slate-300">
            <p className="text-sm leading-relaxed">
              The <span style={{ color: '#00ffd1' }} className="font-semibold">Day-Ahead Market (PZU/DAM)</span> operated by OPCOM
              enables battery storage to profit from daily price spreads through buy-low/sell-high arbitrage.
            </p>

            <div className="rounded-lg p-4 space-y-3" style={{ background: 'rgba(14, 21, 45, 0.6)' }}>
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Clock className="w-4 h-4" style={{ color: '#00ffd1' }} />
                How It Works
              </h3>
              <ul className="text-sm space-y-2 text-slate-400">
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">Charge</strong> during low-price hours (typically night: 00:00-06:00)</span>
                </li>
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">Discharge</strong> during peak-price hours (typically evening: 17:00-21:00)</span>
                </li>
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">Profit</strong> = (Sell Price × Discharge) - (Buy Price × Charge) × Efficiency</span>
                </li>
              </ul>
            </div>

            <div className="rounded-lg p-3 sm:p-4" style={{ background: 'rgba(14, 21, 45, 0.6)' }}>
              <h3 className="text-white font-semibold mb-2 flex items-center gap-2 text-sm sm:text-base">
                <Info className="w-3 h-3 sm:w-4 sm:h-4" style={{ color: '#00ffd1' }} />
                Key Metrics
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:gap-3 text-xs sm:text-sm">
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Typical Daily Spread</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">50-150 €/MWh</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Cycles per Day</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">1-2 cycles</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Market Hours</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">24h ahead</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Settlement</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">Hourly</p>
                </div>
              </div>
            </div>
          </div>

          <Link
            href="/pzu"
            className="mt-3 sm:mt-4 inline-flex items-center gap-2 px-3 sm:px-4 py-2 text-slate-900 rounded-lg transition-all font-medium btn-primary text-sm"
          >
            <BarChart3 className="w-4 h-4" />
            Run PZU Simulation
          </Link>
        </div>

        {/* aFRR - Frequency Regulation Reserve */}
        <div className="rounded-lg sm:rounded-xl p-4 sm:p-6 card-hover" style={{ background: 'linear-gradient(135deg, rgba(0, 255, 209, 0.1) 0%, rgba(14, 21, 45, 0.9) 100%)', border: '1px solid rgba(0, 255, 209, 0.3)' }}>
          <div className="flex items-center gap-2 sm:gap-3 mb-3 sm:mb-4">
            <div className="rounded-lg p-2 sm:p-2.5" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <Zap className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
            </div>
            <div>
              <h2 className="text-base sm:text-xl font-bold text-white">aFRR - Balancing Reserve</h2>
              <p style={{ color: '#00ffd1' }} className="text-xs sm:text-sm">Automatic Frequency Restoration</p>
            </div>
          </div>

          <div className="space-y-4 text-slate-300">
            <p className="text-sm leading-relaxed">
              <span style={{ color: '#00ffd1' }} className="font-semibold">aFRR (Automatic Frequency Restoration Reserve)</span> is
              an ancillary service where batteries provide grid balancing capacity to Transelectrica TSO.
            </p>

            <div className="rounded-lg p-4 space-y-3" style={{ background: 'rgba(14, 21, 45, 0.6)' }}>
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Shield className="w-4 h-4" style={{ color: '#00ffd1' }} />
                Revenue Streams
              </h3>
              <ul className="text-sm space-y-2 text-slate-400">
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">Capacity Payment</strong> - Paid for being available (€/MW/h)</span>
                </li>
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">Activation Payment</strong> - Paid when energy is delivered (€/MWh)</span>
                </li>
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">aFRR+</strong> (upward) - Discharge to grid when frequency low</span>
                </li>
                <li className="flex items-start gap-2">
                  <ChevronRight className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: '#00ffd1' }} />
                  <span><strong className="text-slate-300">aFRR-</strong> (downward) - Charge from grid when frequency high</span>
                </li>
              </ul>
            </div>

            <div className="rounded-lg p-3 sm:p-4" style={{ background: 'rgba(14, 21, 45, 0.6)' }}>
              <h3 className="text-white font-semibold mb-2 flex items-center gap-2 text-sm sm:text-base">
                <ArrowUpDown className="w-3 h-3 sm:w-4 sm:h-4" style={{ color: '#00ffd1' }} />
                Market Parameters
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:gap-3 text-xs sm:text-sm">
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Capacity Price</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">10-20 €/MW/h</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Activation Rate</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">5-15%</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Contract Period</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">4h blocks</p>
                </div>
                <div>
                  <p className="text-slate-400 text-[10px] sm:text-xs">Response Time</p>
                  <p style={{ color: '#00ffd1' }} className="font-mono font-bold text-xs sm:text-sm">&lt; 5 min</p>
                </div>
              </div>
            </div>
          </div>

          <Link
            href="/fr-simulator"
            className="mt-3 sm:mt-4 inline-flex items-center gap-2 px-3 sm:px-4 py-2 text-slate-900 rounded-lg transition-all font-medium btn-primary text-sm"
          >
            <Zap className="w-4 h-4" />
            Run FR Simulation
          </Link>
        </div>
      </div>

      {/* Combined Strategy Note */}
      <div className="rounded-lg sm:rounded-xl p-4 sm:p-6" style={{ background: 'linear-gradient(135deg, rgba(0, 255, 209, 0.05) 0%, rgba(37, 99, 235, 0.05) 50%, rgba(14, 21, 45, 0.9) 100%)', border: '1px solid rgba(0, 255, 209, 0.2)' }}>
        <h2 className="text-base sm:text-lg font-semibold text-white mb-2 sm:mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 sm:w-5 sm:h-5" style={{ color: '#00ffd1' }} />
          Revenue Stacking Strategy
        </h2>
        <p className="text-slate-400 text-xs sm:text-sm leading-relaxed">
          Modern BESS projects in Romania combine multiple revenue streams for optimal returns.
          <span style={{ color: '#00ffd1' }} className="font-semibold"> aFRR typically provides 70-80% of revenue</span> through
          guaranteed capacity payments, while <span className="text-blue-400 font-semibold">PZU arbitrage adds 20-30%</span> during
          off-contract hours.
        </p>
        <Link
          href="/investment"
          className="mt-3 sm:mt-4 inline-flex items-center gap-2 px-3 sm:px-4 py-2 text-slate-900 rounded-lg transition-all font-medium btn-primary text-sm"
        >
          <TrendingUp className="w-4 h-4" />
          Investment Analysis
        </Link>
      </div>

      {/* Module Cards */}
      <div data-tour="step-4">
        <h2 className="text-base sm:text-lg font-semibold text-white mb-3 sm:mb-4 flex items-center gap-2">
          <Activity className="w-4 h-4 sm:w-5 sm:h-5" style={{ color: '#00ffd1' }} />
          Analytics Modules
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
          {modules.map((module) => (
            <Link
              key={module.name}
              href={module.href}
              className="group stat-card card-hover"
            >
              <div className="flex items-center gap-3 sm:gap-4">
                <div
                  className="rounded-lg p-2.5 sm:p-3 text-slate-900 group-hover:scale-110 transition-transform"
                  style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}
                >
                  <module.icon className="h-5 w-5 sm:h-6 sm:w-6" />
                </div>
                <div>
                  <h3 className="text-base sm:text-lg font-semibold text-white group-hover:text-[#00ffd1] transition-colors">
                    {module.name}
                  </h3>
                  <p className="text-xs sm:text-sm text-slate-400">{module.description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="pt-4 sm:pt-6 border-t border-slate-800/50 space-y-3">
        <HealthDiagnostics />
        <div className="text-center">
        <a
          href="https://ebattery.energy"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 sm:gap-2 text-xs sm:text-sm text-slate-400 hover:text-[#00ffd1] transition-colors"
        >
          <span>Powered by</span>
          <span style={{ color: '#00ffd1' }} className="font-semibold">eBattery.energy</span>
          <ExternalLink className="w-3 h-3" />
        </a>
        </div>
      </div>

      {tour.shouldShow && (
        <OnboardingTour
          steps={TOUR_STEPS}
          currentStep={tour.currentStep}
          onNext={tour.next}
          onPrev={tour.prev}
          onDismiss={tour.dismiss}
        />
      )}
    </div>
  )
}
