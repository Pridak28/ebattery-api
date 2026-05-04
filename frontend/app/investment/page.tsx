'use client'

import { useState, useMemo, useEffect } from 'react'
import { TrendingUp, DollarSign, Clock, Award, Zap, Target, BarChart2, PiggyBank, Info, Calendar, Building2, Activity, Shield, ArrowUpRight, ArrowDownRight, Percent, Calculator, Bookmark } from 'lucide-react'
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  AreaChart,
  Area,
  Cell,
  ComposedChart,
  PieChart,
  Pie,
  ReferenceLine,
} from 'recharts'
import { formatCurrency, formatCompact, formatPercentage, formatNumber } from '@/lib/utils'
import { API_BASE_URL, investmentApi } from '@/lib/api'
import CapexBands, { type CapexBand } from '@/components/ui/CapexBands'
import ExportCashflowButton from '@/components/ui/ExportCashflowButton'
import ShareScenarioButton from '@/components/ui/ShareScenarioButton'
import ScenarioJsonButtons from '@/components/ui/ScenarioJsonButtons'
import ComplianceGatesWizard, {
  DEFAULT_COMPLIANCE_GATES,
  getBlockedStreams,
  type ComplianceGatesValue,
} from '@/components/ui/ComplianceGatesWizard'
import RegulatoryTimeline from '@/components/ui/RegulatoryTimeline'
import SensitivityFanChart, { type SensitivitySummary } from '@/components/charts/SensitivityFanChart'
import IrrDistributionHistogram from '@/components/charts/IrrDistributionHistogram'
import DscrTable, { type DscrRow } from '@/components/charts/DscrTable'
import DscrDetailPanel from '@/components/charts/DscrDetailPanel'
import ScenarioComparator from '@/components/charts/ScenarioComparator'
import ScenariosOverview from '@/components/charts/ScenariosOverview'
import ScenarioDiffPanel from '@/components/charts/ScenarioDiffPanel'
import SnapshotButtons from '@/components/ui/SnapshotButtons'
import SavedReportsPanel from '@/components/ui/SavedReportsPanel'
import { useScenarioUrl, type ScenarioSchema } from '@/hooks/useScenarioUrl'

type ScenarioParams = {
  total_investment_eur: number
  equity_percentage: number
  loan_interest_rate: number
  loan_term_years: number
  opex_percentage: number
  insurance_percentage: number
  power_mw: number
  capacity_mwh: number
  include_tariff_exemption: boolean
}

const SCENARIO_SCHEMA: ScenarioSchema<ScenarioParams> = {
  total_investment_eur: 'number',
  equity_percentage: 'number',
  loan_interest_rate: 'number',
  loan_term_years: 'number',
  opex_percentage: 'number',
  insurance_percentage: 'number',
  power_mw: 'number',
  capacity_mwh: 'number',
  include_tariff_exemption: 'boolean',
}

const SCENARIO_DEFAULTS: ScenarioParams = {
  total_investment_eur: 3_500_000, // Sermatec default (cheapest option)
  equity_percentage: 50, // Romanian market standard (50/50 debt-to-equity)
  loan_interest_rate: 6, // 6% p.a.
  loan_term_years: 3, // 3-year short loan term
  opex_percentage: 2,
  insurance_percentage: 0.5,
  // Canonical 10 MW / 20 MWh / €3.5M anchor (user's quote).
  power_mw: 10,
  capacity_mwh: 20,
  include_tariff_exemption: false,
}

const CHART_COLORS = {
  fr: '#00ffd1',            // eBattery cyan for FR
  pzu: '#2563eb',           // eBattery blue for PZU
  profit: '#10b981',        // Green
  cost: '#ef4444',          // Red
  equity: '#00ffd1',        // Cyan for equity
  debt: '#2563eb',          // Blue for debt
  combined: '#a855f7',      // Purple for combined
}

// 4 Battery Vendor Offers — Sermatec is the canonical anchor at
// €3,500,000 for 10 MW / 20 MWh installed (= €175/kWh). Other vendors
// shown for comparison; their figures keep the original normalized basis.
// Source: Streamlit investment.py (real market offers)
const BATTERY_VENDORS = [
  {
    key: 'sermatec',
    name: 'Sermatec',
    orig_power_mw: 15.0,
    orig_energy_mwh: 30.09,
    offer_eur: 2_593_410,
    equip_cost_per_mwh_eur: 86_188,
    norm_equipment_eur: 2_585_653,
    norm_total_eur: 3_500_000,
    norm_total_per_mwh_eur: 116_667,
  },
  {
    key: 'yess',
    name: 'YESS / Cubenergy',
    orig_power_mw: 15.0,
    orig_energy_mwh: 30.86,
    offer_eur: 3_965_500,
    equip_cost_per_mwh_eur: 128_500,
    norm_equipment_eur: 3_854_990,
    norm_total_eur: 4_625_988,
    norm_total_per_mwh_eur: 154_200,
  },
  {
    key: 'byd',
    name: 'BYD',
    orig_power_mw: 25.0,
    orig_energy_mwh: 50.0,
    offer_eur: 5_977_236,
    equip_cost_per_mwh_eur: 119_545,
    norm_equipment_eur: 3_586_342,
    norm_total_eur: 4_303_610,
    norm_total_per_mwh_eur: 143_454,
  },
  {
    key: 'huawei',
    name: 'Huawei',
    orig_power_mw: 15.0,
    orig_energy_mwh: 55.0,
    offer_eur: 13_324_800,
    equip_cost_per_mwh_eur: 242_269,
    norm_equipment_eur: 7_268_073,
    norm_total_eur: 8_721_687,
    norm_total_per_mwh_eur: 290_723,
  },
]

export default function InvestmentAnalysis() {
  const [selectedVendor, setSelectedVendor] = useState('sermatec')
  const vendor = BATTERY_VENDORS.find(v => v.key === selectedVendor) || BATTERY_VENDORS[0]

  const [params, setParams, shareUrl] = useScenarioUrl<ScenarioParams>(
    SCENARIO_DEFAULTS,
    SCENARIO_SCHEMA,
  )

  // Update investment when vendor changes
  const handleVendorChange = (vendorKey: string) => {
    setSelectedVendor(vendorKey)
    const newVendor = BATTERY_VENDORS.find(v => v.key === vendorKey)
    if (newVendor) {
      setParams(prev => ({ ...prev, total_investment_eur: newVendor.norm_total_eur }))
    }
  }

  const [analysis, setAnalysis] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Sizing comparator: collapsible section sitting above the main analysis flow.
  const [comparatorOpen, setComparatorOpen] = useState(false)

  // A/B snapshot slots for ScenarioDiffPanel (collapsible, default closed).
  type Snapshot = { a: any; label: string }
  const [snapshotA, setSnapshotA] = useState<Snapshot | null>(null)
  const [snapshotB, setSnapshotB] = useState<Snapshot | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)
  const setSnapshotSlot = (slot: 'A' | 'B', value: any, label: string) => {
    if (slot === 'A') setSnapshotA({ a: value, label })
    else setSnapshotB({ a: value, label })
  }

  // Regulatory timeline — collapsible, default expanded (small panel above
  // Compliance Gates). Surfaces MARI / PICASSO / ANRE 60 milestones.
  const [regulatoryTimelineOpen, setRegulatoryTimelineOpen] = useState(true)

  // Saved Reports — investor-facing localStorage scratchpad. Default collapsed.
  const [savedReportsOpen, setSavedReportsOpen] = useState(false)

  // B2 — compliance gates (Romanian/EU prerequisites). Default collapsed; state
  // local to this page; passed to backend on /analyze when expanded/toggled.
  const [complianceOpen, setComplianceOpen] = useState(false)
  const [complianceGates, setComplianceGates] = useState<ComplianceGatesValue>(
    DEFAULT_COMPLIANCE_GATES,
  )

  // Phase F1 — Monte Carlo sensitivity (Risk & Sensitivity tab).
  const [sensitivity, setSensitivity] = useState<SensitivitySummary | null>(null)
  const [sensitivityRuns, setSensitivityRuns] = useState(500)
  const [isSensitivityLoading, setIsSensitivityLoading] = useState(false)
  const [sensitivityError, setSensitivityError] = useState<string | null>(null)

  // SSOT defaults from backend /investment/defaults — pricing band anchored on
  // user's actual €3.5M / 10MW / 20MWh quote (€175/kWh).
  const [capexBand, setCapexBand] = useState<CapexBand | undefined>(undefined)
  const [capexBandEuTypical, setCapexBandEuTypical] = useState<CapexBand | undefined>(undefined)

  useEffect(() => {
    investmentApi
      .getDefaults()
      .then((res) => {
        const band = res?.data?.capex_per_kwh_band
        if (band && typeof band.low === 'number' && typeof band.mid === 'number' && typeof band.high === 'number') {
          setCapexBand(band)
        }
        const bandEu = res?.data?.capex_per_kwh_band_eu_typical
        if (bandEu && typeof bandEu.low === 'number' && typeof bandEu.mid === 'number' && typeof bandEu.high === 'number') {
          setCapexBandEuTypical(bandEu)
        }
      })
      .catch(() => {
        // backend cold-start or 503 — fall through to component default band
      })
  }, [])

  const runAnalysis = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/investment/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...params, compliance_gates: complianceGates }),
      })

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
      const data = await response.json()
      setAnalysis(data)
    } catch (err: any) {
      console.error('Analysis error:', err)
      setError(err.message || 'Failed to run analysis')
    } finally {
      setIsLoading(false)
    }
  }

  const runSensitivity = async () => {
    setIsSensitivityLoading(true)
    setSensitivityError(null)
    try {
      const res = await investmentApi.sensitivity({
        params: {
          total_investment_eur: params.total_investment_eur,
          equity_percentage: params.equity_percentage,
          loan_interest_rate: params.loan_interest_rate,
          loan_term_years: params.loan_term_years,
          opex_percentage: params.opex_percentage,
          insurance_percentage: params.insurance_percentage,
          power_mw: params.power_mw,
          capacity_mwh: params.capacity_mwh,
        },
        config: { runs: sensitivityRuns, seed: 42 },
      })
      setSensitivity(res.data as SensitivitySummary)
    } catch (err: any) {
      setSensitivityError(err?.message || 'Sensitivity failed')
    } finally {
      setIsSensitivityLoading(false)
    }
  }

  // Auto-derived investor-readable label, e.g. "10MW/20MWh @ €3.5M, 30% equity".
  // Used when stamping a snapshot into slot A or B for the diff panel.
  const snapshotLabel = useMemo(() => {
    const m = (params.total_investment_eur / 1_000_000).toFixed(2).replace(/\.00$/, '')
    return `${params.power_mw}MW/${params.capacity_mwh}MWh @ €${m}M, ${params.equity_percentage}% equity`
  }, [params])

  // Derived metrics
  const derivedMetrics = useMemo(() => {
    if (!analysis) return null

    const equity = params.total_investment_eur * (params.equity_percentage / 100)
    const debt = params.total_investment_eur - equity

    return {
      equity,
      debt,
      frAdvantage: analysis.fr_scenario.net_profit_after_debt_eur - analysis.pzu_scenario.net_profit_after_debt_eur,
      costPerMW: params.total_investment_eur / params.power_mw,
      costPerMWh: params.total_investment_eur / params.capacity_mwh,
    }
  }, [analysis, params])

  return (
    <div className="space-y-4 sm:space-y-6 max-w-[1600px] mx-auto">
      {/* Bloomberg-Style Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <PiggyBank className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
            </div>
            <div>
              <h1 className="text-lg sm:text-xl md:text-2xl font-bold text-white">Investment Analysis</h1>
              <p className="text-xs sm:text-sm text-slate-400">
                Financial Modeling • FR vs PZU
              </p>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-slate-800/50 border border-slate-700">
            <span className="w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] sm:text-xs text-slate-400">LIVE</span>
          </div>
          <div className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-[#00ffd1]/10 border border-[#00ffd1]/30">
            <span className="text-xs sm:text-sm text-[#00ffd1] font-mono">ROI CALC</span>
          </div>
        </div>
      </div>

      {/* Sizing Comparator — collapsible side-by-side runs of /investment/analyze */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setComparatorOpen((v) => !v)}
          aria-expanded={comparatorOpen}
          className="w-full px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex items-center justify-between gap-2 hover:bg-slate-800/40 transition-colors"
        >
          <div className="flex items-center gap-2">
            <BarChart2 className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Sizing Comparator</h2>
            <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
              compare 2-3 BESS sizing options side-by-side
            </span>
          </div>
          <span className="text-slate-400 text-xs font-mono uppercase">
            {comparatorOpen ? 'Hide' : 'Show'}
          </span>
        </button>
        {comparatorOpen && (
          <div className="p-3 sm:p-5">
            <ScenarioComparator />
          </div>
        )}
      </div>

      {/* Real scenario engine — 4 PICASSO/market-share cases (Modeled vs Realistic).
          Live numbers from /api/v1/investment/scenarios. Mirrors the offline
          BESS_Financial_Model_BANK_6tabs Excel. */}
      <div className="my-4 sm:my-6">
        <ScenariosOverview />
      </div>

      {/* Regulatory Timeline — upcoming RO / EU regulatory transitions */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setRegulatoryTimelineOpen((v) => !v)}
          aria-expanded={regulatoryTimelineOpen}
          className="w-full px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex items-center justify-between gap-2 hover:bg-slate-800/40 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Regulatory Timeline</h2>
            <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
              upcoming Romanian / EU transitions — MARI, PICASSO, ANRE 60/2024
            </span>
          </div>
          <span className="text-slate-400 text-xs font-mono uppercase">
            {regulatoryTimelineOpen ? 'Hide' : 'Show'}
          </span>
        </button>
        {regulatoryTimelineOpen && (
          <div className="p-3 sm:p-5">
            <RegulatoryTimeline />
          </div>
        )}
      </div>

      {/* Compliance Gates — Romanian / EU regulatory prerequisites (collapsible) */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setComplianceOpen((v) => !v)}
          aria-expanded={complianceOpen}
          className="w-full px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex items-center justify-between gap-2 hover:bg-slate-800/40 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Compliance Gates</h2>
            <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
              Romanian / EU prerequisites — toggle status to see which revenue streams unlock
            </span>
          </div>
          <span className="text-slate-400 text-xs font-mono uppercase">
            {complianceOpen ? 'Hide' : 'Show'}
          </span>
        </button>
        {complianceOpen && (
          <div className="p-3 sm:p-5">
            <ComplianceGatesWizard
              value={complianceGates}
              onChange={setComplianceGates}
              blockedStreams={
                analysis?.compliance_revenue_streams_blocked ?? getBlockedStreams(complianceGates)
              }
            />
          </div>
        )}
      </div>

      {/* Saved Reports — localStorage-backed personal scratchpad (collapsible) */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setSavedReportsOpen((v) => !v)}
          aria-expanded={savedReportsOpen}
          className="w-full px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex items-center justify-between gap-2 hover:bg-slate-800/40 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Bookmark className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Saved Reports</h2>
            <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
              save analysis runs locally and reload them later (no backend storage)
            </span>
          </div>
          <span className="text-slate-400 text-xs font-mono uppercase">
            {savedReportsOpen ? 'Hide' : 'Show'}
          </span>
        </button>
        {savedReportsOpen && (
          <div className="p-3 sm:p-5">
            <SavedReportsPanel
              currentParams={params}
              currentAnalysis={analysis}
              onLoad={(loadedParams) => setParams(loadedParams)}
            />
          </div>
        )}
      </div>

      {/* CAPEX bands — Romanian vendor anchor + European bankability comparison */}
      <CapexBands
        powerMw={params.power_mw}
        capacityMwh={params.capacity_mwh}
        band={capexBand}
        bandEuTypical={capexBandEuTypical}
      />

      {/* Bloomberg-Style Investment Overview Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        {/* Key Metrics Overview */}
        <div className="lg:col-span-2 bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg sm:rounded-xl p-3 sm:p-5">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3 sm:mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              <h2 className="text-sm sm:text-lg font-semibold text-white">BESS Investment Overview</h2>
            </div>
            <span className="sm:ml-auto text-[10px] sm:text-xs text-slate-400">Romanian Market 2024-2025</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 sm:gap-4 mb-3 sm:mb-4">
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-0.5 sm:mb-1">Typical CAPEX</p>
              <p className="text-base sm:text-xl font-bold text-[#00ffd1] font-mono">€100-150K</p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">per MWh installed</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-0.5 sm:mb-1">FR Revenue</p>
              <p className="text-base sm:text-xl font-bold text-emerald-400 font-mono">€250-400K</p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">per MW/year</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-0.5 sm:mb-1">PZU Revenue</p>
              <p className="text-base sm:text-xl font-bold text-blue-400 font-mono">€80-150K</p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">per MW/year</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-0.5 sm:mb-1">Typical Payback</p>
              <p className="text-base sm:text-xl font-bold text-white font-mono">2-4 yrs</p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">with FR revenue</p>
            </div>
          </div>

          {/* Revenue Stream Comparison */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-4">
            <div className="bg-slate-800/30 rounded-lg p-2 sm:p-3">
              <div className="flex items-center justify-between mb-1.5 sm:mb-2">
                <span className="text-xs sm:text-sm text-[#00ffd1] font-medium flex items-center gap-1">
                  <Zap className="w-3 h-3 sm:w-4 sm:h-4" /> Frequency Regulation
                </span>
                <span className="text-[10px] sm:text-xs text-slate-400">70-80%</span>
              </div>
              <p className="text-[10px] sm:text-xs text-slate-400">
                aFRR capacity + activation. Stable income.
              </p>
              <div className="mt-1.5 sm:mt-2 h-1.5 sm:h-2 bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-[#00d4aa] to-[#00ffd1]" style={{ width: '75%' }} />
              </div>
            </div>
            <div className="bg-slate-800/30 rounded-lg p-2 sm:p-3">
              <div className="flex items-center justify-between mb-1.5 sm:mb-2">
                <span className="text-xs sm:text-sm text-blue-400 font-medium flex items-center gap-1">
                  <TrendingUp className="w-3 h-3 sm:w-4 sm:h-4" /> PZU Arbitrage
                </span>
                <span className="text-[10px] sm:text-xs text-slate-400">20-30%</span>
              </div>
              <p className="text-[10px] sm:text-xs text-slate-400">
                Day-ahead spread trading. Variable returns.
              </p>
              <div className="mt-1.5 sm:mt-2 h-1.5 sm:h-2 bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400" style={{ width: '25%' }} />
              </div>
            </div>
          </div>
        </div>

        {/* Educational Card - Right */}
        <div className="bg-gradient-to-br from-purple-900/20 to-slate-900/50 border border-purple-500/30 rounded-lg sm:rounded-xl p-3 sm:p-5">
          <div className="flex items-center gap-2 mb-3 sm:mb-4">
            <Calculator className="w-4 h-4 sm:w-5 sm:h-5 text-purple-400" />
            <h3 className="text-white font-semibold text-sm sm:text-base">Investment Model</h3>
          </div>

          <div className="space-y-4 text-sm">
            <div className="border-l-2 border-[#00ffd1] pl-3">
              <p className="text-[#00ffd1] font-medium">Step 1: Choose Vendor</p>
              <p className="text-slate-400 text-xs mt-1">
                Select battery provider. CAPEX auto-fills based on normalized 15 MW / 30 MWh pricing.
              </p>
            </div>

            <div className="border-l-2 border-blue-400 pl-3">
              <p className="text-blue-400 font-medium">Step 2: Set Financing</p>
              <p className="text-slate-400 text-xs mt-1">
                Configure equity/debt split, interest rate, and loan term for your project.
              </p>
            </div>

            <div className="border-l-2 border-emerald-400 pl-3">
              <p className="text-emerald-400 font-medium">Step 3: Compare Scenarios</p>
              <p className="text-slate-400 text-xs mt-1">
                Analyze FR vs PZU strategies with ROI, payback, and cashflow projections.
              </p>
            </div>

            <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-3 mt-4">
              <p className="text-purple-400 text-xs font-medium flex items-center gap-1">
                <Shield className="w-3 h-3" /> Key Insight
              </p>
              <p className="text-slate-400 text-[11px] mt-1">
                FR typically outperforms PZU by 2-3x due to capacity payments, but requires TSO certification.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Battery Vendor Selection */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <div className="px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="flex items-center gap-2">
            <Award className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Step 1 - Choose Battery Provider</h2>
          </div>
          <span className="text-slate-400 text-[10px] sm:text-xs">Normalized to 15 MW / 30 MWh</span>
        </div>
        <div className="p-3 sm:p-5">
          {/* Vendor Selector */}
          <div className="mb-4 sm:mb-6">
            <label className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Battery Provider</label>
            <select
              value={selectedVendor}
              onChange={(e) => handleVendorChange(e.target.value)}
              className="w-full md:w-80 px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
            >
              {BATTERY_VENDORS.map(v => (
                <option key={v.key} value={v.key}>
                  {v.name} - €{(v.norm_total_eur / 1_000_000).toFixed(2)}M total
                </option>
              ))}
            </select>
            <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Pick the vendor to finance. CAPEX auto-fills from this choice.</p>
          </div>

          {/* Selected Vendor KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 sm:gap-4 mb-4 sm:mb-6">
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3 text-center">
              <p className="text-slate-400 text-[10px] sm:text-xs mb-0.5 sm:mb-1">Vendor</p>
              <p className="text-white font-semibold text-xs sm:text-sm">{vendor.name}</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3 text-center">
              <p className="text-slate-400 text-[10px] sm:text-xs mb-0.5 sm:mb-1">Offer (full)</p>
              <p className="text-[#00ffd1] font-mono font-semibold text-xs sm:text-sm">€{(vendor.offer_eur / 1_000_000).toFixed(2)}M</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3 text-center">
              <p className="text-slate-400 text-[10px] sm:text-xs mb-0.5 sm:mb-1">Norm. Equip</p>
              <p className="text-blue-400 font-mono font-semibold text-xs sm:text-sm">€{(vendor.norm_equipment_eur / 1_000_000).toFixed(2)}M</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3 text-center">
              <p className="text-slate-400 text-[10px] sm:text-xs mb-0.5 sm:mb-1">Total Project</p>
              <p className="text-emerald-400 font-mono font-semibold text-xs sm:text-sm">€{(vendor.norm_total_eur / 1_000_000).toFixed(2)}M</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3 text-center col-span-2 sm:col-span-1">
              <p className="text-slate-400 text-[10px] sm:text-xs mb-0.5 sm:mb-1">€/MWh (total)</p>
              <p className="text-[#00ffd1] font-mono font-semibold text-xs sm:text-sm">€{vendor.norm_total_per_mwh_eur.toLocaleString()}</p>
            </div>
          </div>

          {/* Full Vendor Comparison Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left px-3 py-2 text-slate-400 font-medium">Vendor</th>
                  <th className="text-left px-3 py-2 text-slate-400 font-medium">Original Offer</th>
                  <th className="text-right px-3 py-2 text-slate-400 font-medium">Offer € (full kit)</th>
                  <th className="text-right px-3 py-2 text-slate-400 font-medium">€/MWh (offered)</th>
                  <th className="text-right px-3 py-2 text-slate-400 font-medium">Norm. Equipment €</th>
                  <th className="text-right px-3 py-2 text-slate-400 font-medium">Total Project €</th>
                  <th className="text-right px-3 py-2 text-slate-400 font-medium">€/MWh (norm.)</th>
                </tr>
              </thead>
              <tbody>
                {BATTERY_VENDORS.map(v => (
                  <tr
                    key={v.key}
                    className={`border-b border-slate-800 cursor-pointer hover:bg-slate-800/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00ffd1] focus-visible:ring-inset ${
                      v.key === selectedVendor ? 'bg-[#00ffd1]/10 border-[#00ffd1]/30' : ''
                    }`}
                    onClick={() => handleVendorChange(v.key)}
                    tabIndex={0}
                    role="button"
                    aria-label={`Select battery vendor ${v.name}`}
                    aria-pressed={v.key === selectedVendor}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleVendorChange(v.key)
                      }
                    }}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${v.key === selectedVendor ? 'bg-[#00ffd1]' : 'bg-slate-600'}`}></div>
                        <span className={v.key === selectedVendor ? 'text-white font-medium' : 'text-slate-300'}>{v.name}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-slate-400">{v.orig_power_mw} MW / {v.orig_energy_mwh.toFixed(1)} MWh</td>
                    <td className="px-3 py-2 text-right font-mono text-white">€{(v.offer_eur / 1_000_000).toFixed(2)}M</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-400">€{v.equip_cost_per_mwh_eur.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono text-blue-400">€{(v.norm_equipment_eur / 1_000_000).toFixed(2)}M</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-400">€{(v.norm_total_eur / 1_000_000).toFixed(2)}M</td>
                    <td className={`px-3 py-2 text-right font-mono ${
                      v.norm_total_per_mwh_eur <= 110_000 ? 'text-emerald-400' :
                      v.norm_total_per_mwh_eur <= 160_000 ? 'text-blue-400' :
                      v.norm_total_per_mwh_eur <= 200_000 ? 'text-[#00ffd1]' : 'text-red-400'
                    }`}>€{v.norm_total_per_mwh_eur.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-slate-400 text-xs mt-3">
            * All values normalized to 15 MW / 30 MWh. Total Project includes ×1.2 BOS (Balance of System) factor.
          </p>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <div className="px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-2">
            <Building2 className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Step 2 - Financing Parameters</h2>
          </div>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto">
            <ShareScenarioButton getUrl={() => shareUrl || (typeof window !== 'undefined' ? window.location.href : '')} />
            <ScenarioJsonButtons
              params={params}
              analysis={analysis}
              onImport={(p) => setParams(p)}
            />
            <button
              onClick={runAnalysis}
              disabled={isLoading}
              className="btn-primary flex items-center justify-center gap-2 w-full sm:w-auto min-h-[44px] sm:min-h-[36px]"
            >
              {isLoading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" />
                  Run Analysis
                </>
              )}
            </button>
          </div>
        </div>
        <div className="p-3 sm:p-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-5">
            <div>
              <label htmlFor="bess-inv-total-investment-eur" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Total Investment (EUR)</label>
              <input
                id="bess-inv-total-investment-eur"
                type="number"
                value={params.total_investment_eur}
                onChange={(e) => setParams({ ...params, total_investment_eur: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">CAPEX total</p>
            </div>
            <div>
              <label htmlFor="bess-inv-equity-percentage" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Equity (%)</label>
              <input
                id="bess-inv-equity-percentage"
                type="number"
                value={params.equity_percentage}
                onChange={(e) => setParams({ ...params, equity_percentage: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Owner contribution</p>
            </div>
            <div>
              <label htmlFor="bess-inv-loan-interest-rate" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Interest Rate (%)</label>
              <input
                id="bess-inv-loan-interest-rate"
                type="number"
                value={params.loan_interest_rate}
                onChange={(e) => setParams({ ...params, loan_interest_rate: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Loan annual rate</p>
            </div>
            <div>
              <label htmlFor="bess-inv-loan-term-years" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Loan Term (years)</label>
              <input
                id="bess-inv-loan-term-years"
                type="number"
                value={params.loan_term_years}
                onChange={(e) => setParams({ ...params, loan_term_years: parseInt(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Repayment period</p>
            </div>
            <div>
              <label htmlFor="bess-inv-power-mw" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Power (MW)</label>
              <input
                id="bess-inv-power-mw"
                type="number"
                value={params.power_mw}
                onChange={(e) => setParams({ ...params, power_mw: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Battery power</p>
            </div>
            <div>
              <label htmlFor="bess-inv-capacity-mwh" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Capacity (MWh)</label>
              <input
                id="bess-inv-capacity-mwh"
                type="number"
                value={params.capacity_mwh}
                onChange={(e) => setParams({ ...params, capacity_mwh: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Energy capacity</p>
            </div>
            <div>
              <label htmlFor="bess-inv-opex-percentage" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">OPEX (%)</label>
              <input
                id="bess-inv-opex-percentage"
                type="number"
                value={params.opex_percentage}
                onChange={(e) => setParams({ ...params, opex_percentage: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Of CAPEX/year</p>
            </div>
            <div>
              <label htmlFor="bess-inv-insurance-percentage" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Insurance (%)</label>
              <input
                id="bess-inv-insurance-percentage"
                type="number"
                value={params.insurance_percentage}
                onChange={(e) => setParams({ ...params, insurance_percentage: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Of CAPEX/year</p>
            </div>
          </div>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <p className="text-red-400">{error}</p>
        </div>
      )}

      {/* Results */}
      {analysis && derivedMetrics && (
        <>
          {/* Recommendation Banner */}
          <div className={`rounded-lg p-6 border ${
            analysis.recommended_scenario === 'FR'
              ? 'bg-blue-500/10 border-blue-500/30'
              : 'bg-green-500/10 border-green-500/30'
          }`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-sm mb-1">Recommended Strategy</p>
                <p className={`text-3xl font-bold ${
                  analysis.recommended_scenario === 'FR' ? 'text-blue-400' : 'text-green-400'
                }`}>
                  {analysis.recommended_scenario === 'FR' ? 'Frequency Regulation' : 'PZU Trading'}
                </p>
              </div>
              <div className="text-right">
                <p className="text-slate-400 text-sm mb-1">Annual Advantage</p>
                <p className="text-2xl font-bold text-white font-mono">
                  {formatCurrency(analysis.advantage_eur, { decimals: 0 })}
                </p>
                <p className="text-green-400 text-sm">
                  +{formatPercentage(analysis.advantage_percentage)}
                </p>
              </div>
            </div>
          </div>

          {/* Export Cashflow CSV + A/B snapshot capture */}
          <div className="flex flex-wrap justify-end gap-2 items-center">
            <SnapshotButtons
              currentAnalysis={analysis}
              currentLabel={snapshotLabel}
              setSlot={setSnapshotSlot}
            />
            <ExportCashflowButton
              frCashflow={analysis.fr_cashflow ?? []}
              pzuCashflow={analysis.pzu_cashflow ?? []}
              params={params}
            />
          </div>

          {/* A/B Scenario Diff — collapsible (default collapsed). */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setDiffOpen((v) => !v)}
              aria-expanded={diffOpen}
              className="w-full px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex items-center justify-between gap-2 hover:bg-slate-800/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
                <h2 className="text-white font-semibold text-sm sm:text-base">
                  A/B Scenario Diff
                </h2>
                <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
                  side-by-side delta on every key metric — Save as A / B from any run
                </span>
                <span className="text-[10px] font-mono text-slate-400 ml-2">
                  [A:{snapshotA ? 'set' : 'empty'} | B:{snapshotB ? 'set' : 'empty'}]
                </span>
              </div>
              <span className="text-slate-400 text-xs font-mono uppercase">
                {diffOpen ? 'Hide' : 'Show'}
              </span>
            </button>
            {diffOpen && (
              <div className="p-3 sm:p-5">
                <ScenarioDiffPanel
                  analysisA={snapshotA?.a ?? null}
                  analysisB={snapshotB?.a ?? null}
                  nameA={snapshotA?.label}
                  nameB={snapshotB?.label}
                />
              </div>
            )}
          </div>

          {/* Executive Summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-slate-400 text-sm">Total CAPEX</span>
                <DollarSign className="w-5 h-5 text-[#00ffd1]" />
              </div>
              <p className="text-2xl font-bold text-white font-mono">
                {formatCompact(params.total_investment_eur)}
              </p>
              <p className="text-slate-400 text-xs mt-1">{formatCompact(derivedMetrics.costPerMW)}/MW</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-slate-400 text-sm">Equity Required</span>
                <PiggyBank className="w-5 h-5 text-green-400" />
              </div>
              <p className="text-2xl font-bold text-white font-mono">
                {formatCompact(derivedMetrics.equity)}
              </p>
              <p className="text-slate-400 text-xs mt-1">{params.equity_percentage}% of CAPEX</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-slate-400 text-sm">Bank Financing</span>
                <Building2 className="w-5 h-5 text-[#00ffd1]" />
              </div>
              <p className="text-2xl font-bold text-white font-mono">
                {formatCompact(derivedMetrics.debt)}
              </p>
              <p className="text-slate-400 text-xs mt-1">{100 - params.equity_percentage}% debt</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-slate-400 text-sm">Annual Debt Service</span>
                <Calendar className="w-5 h-5 text-red-400" />
              </div>
              <p className="text-2xl font-bold text-white font-mono">
                {formatCompact(analysis.financing.annual_debt_service_eur)}
              </p>
              <p className="text-slate-400 text-xs mt-1">{params.loan_term_years} year term</p>
            </div>
          </div>

          {/* Comparison Cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* FR Scenario */}
            <div className={`bg-slate-900 rounded-lg overflow-hidden border-2 ${
              analysis.recommended_scenario === 'FR' ? 'border-blue-500' : 'border-slate-700'
            }`}>
              <div className="px-5 py-4 border-b border-slate-700 flex items-center justify-between bg-blue-500/10">
                <div className="flex items-center gap-2">
                  <Zap className="w-5 h-5 text-blue-400" />
                  <h3 className="text-white font-semibold">Frequency Regulation</h3>
                </div>
                {analysis.recommended_scenario === 'FR' && (
                  <span className="px-2 py-1 bg-blue-500/20 text-blue-400 text-xs rounded-full border border-blue-500/30">
                    RECOMMENDED
                  </span>
                )}
              </div>
              <div className="p-5 space-y-3">
                <div className="flex justify-between">
                  <span className="text-slate-400">Gross Revenue</span>
                  <span className="text-white font-mono">{formatCurrency(analysis.fr_scenario.gross_revenue_eur, { decimals: 0 })}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Energy Cost</span>
                  <span className="text-red-400 font-mono">-{formatCurrency(analysis.fr_scenario.energy_cost_eur, { decimals: 0 })}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Operating Cost</span>
                  <span className="text-red-400 font-mono">-{formatCurrency(analysis.fr_scenario.operating_cost_eur, { decimals: 0 })}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Debt Service</span>
                  <span className="text-red-400 font-mono">-{formatCurrency(analysis.fr_scenario.annual_debt_service_eur, { decimals: 0 })}</span>
                </div>
                <div className="border-t border-slate-700 pt-3 flex justify-between font-semibold">
                  <span className="text-white">Net Profit</span>
                  <span className="text-green-400 font-mono">{formatCurrency(analysis.fr_scenario.net_profit_after_debt_eur, { decimals: 0 })}</span>
                </div>
                <div className="grid grid-cols-2 gap-3 pt-3 border-t border-slate-700">
                  <div className="text-center p-2 bg-slate-800/50 rounded">
                    <p className="text-slate-400 text-xs uppercase tracking-wide">Y1 ROI on Equity</p>
                    <p className="text-blue-400 font-bold">{formatPercentage(analysis.fr_scenario.roi_percentage)}</p>
                    <p className="text-[10px] text-slate-400 mt-1">premium-pricing year</p>
                  </div>
                  <div className="text-center p-2 bg-slate-800/50 rounded">
                    <p className="text-slate-400 text-xs uppercase tracking-wide">Y1 Payback</p>
                    <p className="text-blue-400 font-bold">{analysis.fr_scenario.payback_years.toFixed(1)} yrs</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-blue-500/30 bg-blue-500/5 rounded p-2">
                  <div className="text-center p-2">
                    <p className="text-blue-300 text-xs uppercase tracking-wide font-semibold">Lifetime IRR ({analysis.projection_horizon_years ?? 15}y)</p>
                    <p className="text-blue-200 font-bold">
                      {analysis.fr_lifetime_irr_pct == null
                        ? <span className="text-rose-300">loss-making</span>
                        : formatPercentage(analysis.fr_lifetime_irr_pct)}
                    </p>
                    <p className="text-[10px] text-blue-300/70 mt-1">bankability number</p>
                  </div>
                  <div className="text-center p-2">
                    <p className="text-blue-300 text-xs uppercase tracking-wide font-semibold">Lifetime Payback</p>
                    <p className="text-blue-200 font-bold">
                      {analysis.fr_lifetime_payback_years == null
                        ? <span className="text-rose-300">never</span>
                        : `${analysis.fr_lifetime_payback_years.toFixed(1)} yrs`}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* PZU Scenario */}
            <div className={`bg-slate-900 rounded-lg overflow-hidden border-2 ${
              analysis.recommended_scenario === 'PZU' ? 'border-green-500' : 'border-slate-700'
            }`}>
              <div className="px-5 py-4 border-b border-slate-700 flex items-center justify-between bg-green-500/10">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-green-400" />
                  <h3 className="text-white font-semibold">PZU Trading</h3>
                </div>
                {analysis.recommended_scenario === 'PZU' && (
                  <span className="px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded-full border border-green-500/30">
                    RECOMMENDED
                  </span>
                )}
              </div>
              <div className="p-5 space-y-3">
                <div className="flex justify-between">
                  <span className="text-slate-400">Gross Revenue</span>
                  <span className="text-white font-mono">{formatCurrency(analysis.pzu_scenario.gross_revenue_eur, { decimals: 0 })}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Energy Cost</span>
                  <span className="text-red-400 font-mono">
                    -{formatCurrency(analysis.pzu_scenario.energy_cost_eur || 0, { decimals: 0 })}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Operating Cost</span>
                  <span className="text-red-400 font-mono">-{formatCurrency(analysis.pzu_scenario.operating_cost_eur, { decimals: 0 })}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Debt Service</span>
                  <span className="text-red-400 font-mono">-{formatCurrency(analysis.pzu_scenario.annual_debt_service_eur, { decimals: 0 })}</span>
                </div>
                <div className="border-t border-slate-700 pt-3 flex justify-between font-semibold">
                  <span className="text-white">Net Profit</span>
                  <span className="text-green-400 font-mono">{formatCurrency(analysis.pzu_scenario.net_profit_after_debt_eur, { decimals: 0 })}</span>
                </div>
                <div className="grid grid-cols-2 gap-3 pt-3 border-t border-slate-700">
                  <div className="text-center p-2 bg-slate-800/50 rounded">
                    <p className="text-slate-400 text-xs uppercase tracking-wide">Y1 ROI on Equity</p>
                    <p className="text-green-400 font-bold">{formatPercentage(analysis.pzu_scenario.roi_percentage)}</p>
                    <p className="text-[10px] text-slate-400 mt-1">premium-pricing year</p>
                  </div>
                  <div className="text-center p-2 bg-slate-800/50 rounded">
                    <p className="text-slate-400 text-xs uppercase tracking-wide">Y1 Payback</p>
                    <p className="text-green-400 font-bold">{analysis.pzu_scenario.payback_years.toFixed(1)} yrs</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-green-500/30 bg-green-500/5 rounded p-2">
                  <div className="text-center p-2">
                    <p className="text-green-300 text-xs uppercase tracking-wide font-semibold">Lifetime IRR ({analysis.projection_horizon_years ?? 15}y)</p>
                    <p className="text-green-200 font-bold">
                      {analysis.pzu_lifetime_irr_pct == null
                        ? <span className="text-rose-300">loss-making</span>
                        : formatPercentage(analysis.pzu_lifetime_irr_pct)}
                    </p>
                    <p className="text-[10px] text-green-300/70 mt-1">bankability number</p>
                  </div>
                  <div className="text-center p-2">
                    <p className="text-green-300 text-xs uppercase tracking-wide font-semibold">Lifetime Payback</p>
                    <p className="text-green-200 font-bold">
                      {analysis.pzu_lifetime_payback_years == null
                        ? <span className="text-rose-300">never</span>
                        : `${analysis.pzu_lifetime_payback_years.toFixed(1)} yrs`}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Cashflow Chart */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-[#00ffd1]" />
              Cumulative Cashflow Projection
            </h3>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="year"
                    type="number"
                    domain={[0, params.loan_term_years]}
                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                    axisLine={{ stroke: '#475569' }}
                    tickLine={{ stroke: '#475569' }}
                    tickFormatter={(v) => `Yr ${v}`}
                  />
                  <YAxis
                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                    axisLine={{ stroke: '#475569' }}
                    tickLine={{ stroke: '#475569' }}
                    tickFormatter={(v) => `€${(v / 1_000_000).toFixed(1)}M`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1e293b',
                      border: '1px solid #475569',
                      borderRadius: '8px',
                      color: '#fff',
                    }}
                    formatter={(v: number) => formatCurrency(v, { decimals: 0 })}
                    labelFormatter={(v) => `Year ${v}`}
                  />
                  <Legend />
                  <Line
                    data={analysis.fr_cashflow}
                    type="monotone"
                    dataKey="cumulative_profit_eur"
                    stroke={CHART_COLORS.fr}
                    strokeWidth={3}
                    name="FR Cumulative"
                    dot={{ fill: CHART_COLORS.fr, r: 4 }}
                  />
                  <Line
                    data={analysis.pzu_cashflow}
                    type="monotone"
                    dataKey="cumulative_profit_eur"
                    stroke={CHART_COLORS.pzu}
                    strokeWidth={3}
                    name="PZU Cumulative"
                    dot={{ fill: CHART_COLORS.pzu, r: 4 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Financing Structure */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Building2 className="w-5 h-5 text-[#00ffd1]" />
              Financing Structure
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-4 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-sm mb-2">Total Investment</p>
                <p className="text-2xl font-bold text-white font-mono">
                  {formatCompact(analysis.financing.total_investment_eur)}
                </p>
              </div>
              <div className="text-center p-4 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-sm mb-2">Equity Required</p>
                <p className="text-2xl font-bold text-[#00ffd1] font-mono">
                  {formatCompact(analysis.financing.equity_eur)}
                </p>
                <p className="text-slate-400 text-xs mt-1">{analysis.financing.equity_percentage}%</p>
              </div>
              <div className="text-center p-4 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-sm mb-2">Bank Financing</p>
                <p className="text-2xl font-bold text-[#00ffd1] font-mono">
                  {formatCompact(analysis.financing.debt_eur)}
                </p>
                <p className="text-slate-400 text-xs mt-1">{analysis.financing.debt_percentage}%</p>
              </div>
              <div className="text-center p-4 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-sm mb-2">Annual Debt Service</p>
                <p className="text-2xl font-bold text-red-400 font-mono">
                  {formatCompact(analysis.financing.annual_debt_service_eur)}
                </p>
              </div>
            </div>
          </div>

          {/* Summary Comparison Table */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-700">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <BarChart2 className="w-5 h-5 text-blue-400" />
                Scenario Comparison
              </h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-800/50">
                    <th className="text-left px-5 py-3 text-slate-400 font-medium text-sm">Metric</th>
                    <th className="text-right px-5 py-3 text-blue-400 font-medium text-sm">FR Scenario</th>
                    <th className="text-right px-5 py-3 text-green-400 font-medium text-sm">PZU Scenario</th>
                    <th className="text-right px-5 py-3 text-slate-400 font-medium text-sm">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="bg-slate-900">
                    <td className="px-5 py-3 text-slate-300">Gross Revenue</td>
                    <td className="px-5 py-3 text-right font-mono text-white">{formatCurrency(analysis.fr_scenario.gross_revenue_eur, { decimals: 0 })}</td>
                    <td className="px-5 py-3 text-right font-mono text-white">{formatCurrency(analysis.pzu_scenario.gross_revenue_eur, { decimals: 0 })}</td>
                    <td className="px-5 py-3 text-right font-mono text-slate-400">
                      {formatCurrency(analysis.fr_scenario.gross_revenue_eur - analysis.pzu_scenario.gross_revenue_eur, { decimals: 0, showSign: true })}
                    </td>
                  </tr>
                  <tr className="bg-slate-800/30">
                    <td className="px-5 py-3 text-slate-300">Net Profit (After Debt)</td>
                    <td className="px-5 py-3 text-right font-mono text-green-400 font-semibold">{formatCurrency(analysis.fr_scenario.net_profit_after_debt_eur, { decimals: 0 })}</td>
                    <td className="px-5 py-3 text-right font-mono text-green-400 font-semibold">{formatCurrency(analysis.pzu_scenario.net_profit_after_debt_eur, { decimals: 0 })}</td>
                    <td className={`px-5 py-3 text-right font-mono font-semibold ${derivedMetrics.frAdvantage >= 0 ? 'text-blue-400' : 'text-green-400'}`}>
                      {formatCurrency(derivedMetrics.frAdvantage, { decimals: 0, showSign: true })}
                    </td>
                  </tr>
                  <tr className="bg-slate-900">
                    <td className="px-5 py-3 text-slate-300">ROI on Equity</td>
                    <td className="px-5 py-3 text-right font-mono text-blue-400">{formatPercentage(analysis.fr_scenario.roi_percentage)}</td>
                    <td className="px-5 py-3 text-right font-mono text-green-400">{formatPercentage(analysis.pzu_scenario.roi_percentage)}</td>
                    <td className="px-5 py-3 text-right font-mono text-slate-400">
                      {formatPercentage(analysis.fr_scenario.roi_percentage - analysis.pzu_scenario.roi_percentage, { showSign: true })}
                    </td>
                  </tr>
                  <tr className="bg-slate-800/30">
                    <td className="px-5 py-3 text-slate-300">Payback Period</td>
                    <td className="px-5 py-3 text-right font-mono text-blue-400">{analysis.fr_scenario.payback_years.toFixed(1)} years</td>
                    <td className="px-5 py-3 text-right font-mono text-green-400">{analysis.pzu_scenario.payback_years.toFixed(1)} years</td>
                    <td className="px-5 py-3 text-right font-mono text-slate-400">
                      {(analysis.fr_scenario.payback_years - analysis.pzu_scenario.payback_years).toFixed(1)} years
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Phase D + F — Risk, Sensitivity & Bankability */}
      {analysis && (
        <div className="mt-8 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-white">
                Risk & Sensitivity (Phase F)
              </h2>
              <p className="text-xs text-slate-400">
                Monte Carlo over activation share, RTE, degradation, FX, PZU spread.
                DSCR covenant flagged in red. Augmentation + warranty status from Phase D.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="mc-runs" className="text-xs text-slate-400">Runs</label>
              <select
                id="mc-runs"
                title="Number of Monte Carlo runs"
                value={sensitivityRuns}
                onChange={(e) => setSensitivityRuns(Number(e.target.value))}
                className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
              >
                <option value={200}>200</option>
                <option value={500}>500</option>
                <option value={1000}>1000</option>
              </select>
              <button
                type="button"
                onClick={runSensitivity}
                disabled={isSensitivityLoading}
                className="rounded bg-blue-600 px-3 py-1 text-xs font-mono uppercase text-white hover:bg-blue-500 disabled:opacity-50"
              >
                {isSensitivityLoading ? 'Running…' : 'Run Monte Carlo'}
              </button>
            </div>
          </div>

          {sensitivityError && (
            <div className="rounded border border-rose-700 bg-rose-900/40 p-3 text-xs text-rose-200">
              {sensitivityError}
            </div>
          )}

          {sensitivity && <SensitivityFanChart data={sensitivity} />}

          {/* Phase F1.b — IRR distribution shape (complement to fan chart) */}
          {(sensitivity || isSensitivityLoading) && (
            <IrrDistributionHistogram
              irrSamples={sensitivity?.irr_samples ?? []}
              p10={sensitivity?.p10_irr ?? NaN}
              p50={sensitivity?.p50_irr ?? NaN}
              p90={sensitivity?.p90_irr ?? NaN}
              meanIrr={sensitivity?.mean_irr ?? NaN}
              loading={isSensitivityLoading && !sensitivity}
            />
          )}

          {/* DSCR + warranty + augmentation per year */}
          {analysis?.fr_cashflow?.length ? (
            <DscrTable
              rows={analysis.fr_cashflow.map((cf: any) => ({
                year: cf.year,
                cfads_eur: cf.cfads_eur ?? 0,
                debt_service_eur: cf.debt_service_eur ?? 0,
                dscr: cf.dscr ?? 0,
                capacity_factor: cf.capacity_factor ?? 1,
                warranty_status: cf.warranty_status ?? 'ok',
                augmentation_cost_eur: cf.augmentation_cost_eur ?? 0,
              })) as DscrRow[]}
              violationYears={analysis.dscr_violation_years ?? []}
            />
          ) : null}

          {/* Per-scenario DSCR trajectory (lender covenant view) */}
          {(analysis?.fr_cashflow?.length || analysis?.pzu_cashflow?.length) ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {analysis?.fr_cashflow?.length ? (
                <DscrDetailPanel
                  cashflow={analysis.fr_cashflow}
                  dscr_violation_years={analysis.dscr_violation_years ?? []}
                  scenario_name="FR"
                />
              ) : null}
              {analysis?.pzu_cashflow?.length ? (
                <DscrDetailPanel
                  cashflow={analysis.pzu_cashflow}
                  dscr_violation_years={analysis.dscr_violation_years ?? []}
                  scenario_name="PZU"
                />
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {/* Empty State */}
      {!analysis && !isLoading && (
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-12 text-center">
          <PiggyBank className="h-12 w-12 text-slate-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white">Ready to Analyze</h3>
          <p className="text-slate-400 mt-1">
            Configure investment parameters and click Run Analysis to compare FR vs PZU scenarios
          </p>
        </div>
      )}
    </div>
  )
}
