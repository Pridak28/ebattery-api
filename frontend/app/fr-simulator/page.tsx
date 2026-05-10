'use client'

import { useState, useMemo, useEffect } from 'react'
import { Zap, Battery, TrendingUp, TrendingDown, Activity, ArrowUpRight, ArrowDownRight, Info, Calendar, Target, AlertTriangle, ChevronLeft, ChevronRight, ExternalLink, Euro, BarChart3 } from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  PieChart as RechartsPieChart,
  Pie,
  Legend,
  Line,
  ComposedChart,
  ReferenceLine,
} from 'recharts'
import { formatCompact, formatNumber, formatPercentage } from '@/lib/utils'
import { API_BASE_URL, frApi } from '@/lib/api'
import { ConfidenceBadge, PricingBasisBadge } from '@/components/ui/ConfidenceBadge'
import FRProductBreakdown, { type FRProductRow } from '@/components/charts/FRProductBreakdown'
import BankabilityBadge from '@/components/ui/BankabilityBadge'
import RegulatoryNotesPanel from '@/components/ui/RegulatoryNotesPanel'
import RegimeBreakdownCard from '@/components/charts/RegimeBreakdownCard'

const CHART_COLORS = {
  capacity: '#00ffd1',      // eBattery cyan
  activation: '#2563eb',    // eBattery blue
  profit: '#10b981',        // Green
  cost: '#ef4444',          // Red
  afrr_up: '#00ffd1',       // Cyan for up-regulation
  afrr_down: '#2563eb',     // Blue for down-regulation
  mfrr_up: '#00d4aa',       // Lighter cyan
  mfrr_down: '#3b82f6',     // Lighter blue
  negative_price: '#f59e0b', // Amber for negative prices
}

export default function FRSimulator() {
  // Phase E (gap audit 2026-05-01) — multi-product (aFRR/mFRR/FCR) state.
  const [mpSelected, setMpSelected] = useState<Array<'aFRR' | 'mFRR' | 'FCR'>>(['aFRR'])
  const [mpData, setMpData] = useState<{
    products: FRProductRow[]
    min_bid_violations: string[]
    mari_active: boolean
    target_date: string
  } | null>(null)
  const [mpLoading, setMpLoading] = useState(false)
  const [mpError, setMpError] = useState<string | null>(null)

  const [params, setParams] = useState({
    // Canonical 10 MW / 20 MWh / €3.5M anchor (user's quote).
    capacity_mwh: 20,
    round_trip_efficiency: 0.97, // Backend default (commit 929db9a, 2026-05-03): 3% loss
    afrr_up: { enabled: true, power_mw: 10 },
    afrr_down: { enabled: true, power_mw: 10 },
    mfrr_up: { enabled: false, power_mw: 0 },
    mfrr_down: { enabled: false, power_mw: 0 },
    energy_cost_eur_mwh: 80,
    capacity_price_eur_mw_h: 11.64, // Live DAMAS rate (commit 97e4d2e); auto-refreshed from /fr/capacity-prices/canonical
    activation_rate: 0.10,
    activation_price_up_eur_mwh: 170, // Live last-12mo weighted avg
    activation_price_down_eur_mwh: 130,
    start_date: '2024-07-01',
    end_date: '2025-11-06',
    investment_eur: 3500000,
  })

  // Live DAMAS canonical capacity rate, fetched once on mount. Drives a "Live"
  // badge on the capacity-price input + scenario calibration.
  const [liveCanonical, setLiveCanonical] = useState<{
    aFRRUp_eur_mw_h: number
    aFRRDown_eur_mw_h: number
    combined_eur_mw_h: number
    window_start: string
    window_end: string
    n_samples: number
  } | null>(null)

  const [simulation, setSimulation] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [marketStats, setMarketStats] = useState<any>(null)

  // State for DAMAS Price Explorer
  const [availableDates, setAvailableDates] = useState<any[]>([])
  const [selectedDate, setSelectedDate] = useState<string>('')
  const [slotPrices, setSlotPrices] = useState<any>(null)
  const [loadingSlots, setLoadingSlots] = useState(false)
  // (dateFilter removed — was declared but never read in JSX or any handler)

  // State for Bidding Optimizer
  const [biddingStrategy, setBiddingStrategy] = useState<any>(null)
  const [optimalBids, setOptimalBids] = useState<any>(null)
  const [revenueProjection, setRevenueProjection] = useState<any>(null)
  const [selectedStrategy, setSelectedStrategy] = useState<string>('balanced')
  const [targetAcceptance, setTargetAcceptance] = useState<number>(0.80)
  const [loadingBidding, setLoadingBidding] = useState(false)

  // State for Safe Bid Calculator
  const [safeBidsData, setSafeBidsData] = useState<any>(null)
  const [safeBidAcceptance, setSafeBidAcceptance] = useState<number>(0.90)
  const [loadingSafeBids, setLoadingSafeBids] = useState(false)
  const [safeBidsError, setSafeBidsError] = useState<string | null>(null)

  // Fetch market stats on mount
  useEffect(() => {
    const ctrl = new AbortController()
    const fetchMarketStats = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/fr/stats`, { signal: ctrl.signal })
        if (response.ok) {
          const data = await response.json()
          setMarketStats(data)
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch market stats:', err)
        }
      }
    }
    fetchMarketStats()
    return () => ctrl.abort()
  }, [])

  // Fetch live DAMAS canonical capacity rate on mount. Keeps the displayed
  // capacity_price_eur_mw_h synchronized with backend reality (commit 97e4d2e
  // replaced the synthetic 22% rule with real DAMAS-derived prices).
  useEffect(() => {
    const ctrl = new AbortController()
    const fetchCanonical = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/fr/capacity-prices/canonical`, { signal: ctrl.signal })
        if (response.ok) {
          const data = await response.json()
          const up = data?.aFRRUp?.price_eur_mw_h ?? 0
          const down = data?.aFRRDown?.price_eur_mw_h ?? 0
          const combined = up + down
          setLiveCanonical({
            aFRRUp_eur_mw_h: up,
            aFRRDown_eur_mw_h: down,
            combined_eur_mw_h: combined,
            window_start: data?.aFRRUp?.window_start ?? '',
            window_end: data?.aFRRUp?.window_end ?? '',
            n_samples: data?.aFRRUp?.n_samples ?? 0,
          })
          // Sync the input default to the live combined rate (only if the user
          // hasn't manually overridden it from the seeded 11.64 default).
          setParams((p) => (p.capacity_price_eur_mw_h === 11.64 ? { ...p, capacity_price_eur_mw_h: Number(combined.toFixed(2)) } : p))
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch canonical capacity prices:', err)
        }
      }
    }
    fetchCanonical()
    return () => ctrl.abort()
  }, [])

  // Fetch available dates for DAMAS Price Explorer
  useEffect(() => {
    const ctrl = new AbortController()
    const fetchAvailableDates = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/fr/available-dates`, { signal: ctrl.signal })
        if (response.ok) {
          const data = await response.json()
          setAvailableDates(data.dates || [])
          // Set default to latest date
          if (data.dates && data.dates.length > 0) {
            const latestDate = data.dates[data.dates.length - 1].date
            setSelectedDate(latestDate)
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch available dates:', err)
        }
      }
    }
    fetchAvailableDates()
    return () => ctrl.abort()
  }, [])

  // Fetch slot prices when date changes
  useEffect(() => {
    if (!selectedDate) return
    const ctrl = new AbortController()
    const fetchSlotPrices = async () => {
      setLoadingSlots(true)
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/fr/slot-prices/${selectedDate}?power_mw=${params.afrr_up.power_mw}`,
          { signal: ctrl.signal }
        )
        if (response.ok) {
          const data = await response.json()
          setSlotPrices(data)
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch slot prices:', err)
        }
      } finally {
        setLoadingSlots(false)
      }
    }
    fetchSlotPrices()
    return () => ctrl.abort()
  }, [selectedDate, params.afrr_up.power_mw])

  // Fetch bidding strategy when power changes (was: mount-only — stale state bug)
  useEffect(() => {
    const ctrl = new AbortController()
    const fetchBiddingStrategy = async () => {
      setLoadingBidding(true)
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/fr/bidding-strategy?power_mw=${params.afrr_up.power_mw}`,
          { signal: ctrl.signal }
        )
        if (response.ok) {
          const data = await response.json()
          setBiddingStrategy(data)
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch bidding strategy:', err)
        }
      } finally {
        setLoadingBidding(false)
      }
    }
    fetchBiddingStrategy()
    return () => ctrl.abort()
  }, [params.afrr_up.power_mw])

  // Fetch optimal bids when date or acceptance rate changes
  useEffect(() => {
    if (!selectedDate) return
    const ctrl = new AbortController()
    const fetchOptimalBids = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/fr/optimal-bids/${selectedDate}?power_mw=${params.afrr_up.power_mw}&target_acceptance=${targetAcceptance}`,
          { signal: ctrl.signal }
        )
        if (response.ok) {
          const data = await response.json()
          setOptimalBids(data)
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch optimal bids:', err)
        }
      }
    }
    fetchOptimalBids()
    return () => ctrl.abort()
  }, [selectedDate, params.afrr_up.power_mw, targetAcceptance])

  // Fetch revenue projection when strategy changes
  useEffect(() => {
    const ctrl = new AbortController()
    const fetchRevenueProjection = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/fr/revenue-projection?power_mw=${params.afrr_up.power_mw}&strategy=${selectedStrategy}`,
          { cache: 'no-store', signal: ctrl.signal }
        )
        if (response.ok) {
          const data = await response.json()
          setRevenueProjection(data)
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to fetch revenue projection:', err)
        }
      }
    }
    fetchRevenueProjection()
    return () => ctrl.abort()
  }, [params.afrr_up.power_mw, selectedStrategy])

  // Fetch safe bid calculator data when acceptance rate changes
  // Includes retry logic for Render cold start (free tier sleeps after inactivity)
  useEffect(() => {
    const fetchSafeBids = async (retryCount = 0) => {
      setLoadingSafeBids(true)
      setSafeBidsError(null)
      try {
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 30000) // 30s timeout for cold start

        const response = await fetch(
          `${API_BASE_URL}/api/v1/fr/safe-bid-calculator?power_mw=${params.afrr_up.power_mw}&target_acceptance=${safeBidAcceptance}`,
          { signal: controller.signal }
        )
        clearTimeout(timeoutId)

        if (response.ok) {
          const data = await response.json()
          if (data.error) {
            setSafeBidsError(data.error)
          } else {
            setSafeBidsData(data)
          }
        } else {
          setSafeBidsError(`Failed to fetch safe bids: ${response.status}`)
        }
      } catch (err: any) {
        console.error('Failed to fetch safe bids:', err)
        // Retry once on timeout (handles Render cold start)
        if (retryCount < 1 && (err.name === 'AbortError' || err.message?.includes('fetch'))) {
          // Retry once after Render cold start; surface progress to the user
          // via the visible error banner instead of console output.
          setSafeBidsError('Server is waking up... Please wait.')
          setTimeout(() => fetchSafeBids(retryCount + 1), 2000)
          return
        }
        setSafeBidsError(err.message || 'Failed to fetch safe bid data. Try refreshing the page.')
      } finally {
        setLoadingSafeBids(false)
      }
    }
    fetchSafeBids()
  }, [params.afrr_up.power_mw, safeBidAcceptance])

  const runSimulation = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/fr/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
      const data = await response.json()
      setSimulation(data)
    } catch (err: any) {
      console.error('Simulation error:', err)
      setError(err.message || 'Failed to run simulation')
    } finally {
      setIsLoading(false)
    }
  }

  const toggleProduct = (product: string) => {
    const key = product as keyof typeof params
    if (typeof params[key] === 'object' && 'enabled' in (params[key] as any)) {
      setParams({
        ...params,
        [key]: { ...(params[key] as any), enabled: !(params[key] as any).enabled },
      })
    }
  }

  // Calculate derived metrics
  const derivedMetrics = useMemo(() => {
    if (!simulation) return null

    // Use months_count (unique months) not monthly_results.length (rows)
    // When multiple products enabled, monthly_results has multiple rows per month
    const monthsCount = simulation.months_count || simulation.monthly_results?.length || 1
    const annualRevenue = simulation.total_revenue_eur * (12 / monthsCount)
    const annualProfit = simulation.total_net_profit_eur * (12 / monthsCount)
    const totalPower = params.afrr_up.power_mw
    const revenuePerMW = totalPower > 0 ? annualRevenue / totalPower : 0
    const profitPerMW = totalPower > 0 ? annualProfit / totalPower : 0
    const capacityFactor = simulation.total_capacity_revenue_eur / simulation.total_revenue_eur
    const activationFactor = simulation.total_activation_revenue_eur / simulation.total_revenue_eur

    return {
      annualRevenue,
      annualProfit,
      revenuePerMW,
      profitPerMW,
      capacityFactor,
      activationFactor,
      profitMargin: simulation.total_net_profit_eur / simulation.total_revenue_eur,
    }
  }, [simulation, params])

  // Chart data processors
  const getMonthlyChartData = () => {
    if (!simulation?.monthly_results) return []
    const monthlyMap = new Map()
    simulation.monthly_results.forEach((row: any) => {
      const existing = monthlyMap.get(row.month) || { month: row.month, capacity: 0, activation: 0, cost: 0, profit: 0, revenue: 0 }
      existing.capacity += row.capacity_revenue_eur
      existing.activation += row.activation_revenue_eur
      existing.cost += row.energy_cost_eur
      existing.profit += row.net_profit_eur
      existing.revenue += row.total_revenue_eur
      monthlyMap.set(row.month, existing)
    })
    return Array.from(monthlyMap.values())
  }

  const getRevenueBreakdownData = () => {
    if (!simulation) return []
    return [
      { name: 'Capacity', value: simulation.total_capacity_revenue_eur, color: CHART_COLORS.capacity },
      { name: 'Activation', value: simulation.total_activation_revenue_eur, color: CHART_COLORS.activation },
    ]
  }

  const getProductBreakdownData = () => {
    if (!simulation?.product_summaries) return []
    return Object.entries(simulation.product_summaries).map(([name, data]: [string, any]) => ({
      name,
      revenue: data.total_revenue_eur,
      profit: data.net_profit_eur,
      color: name === 'aFRR+' ? CHART_COLORS.afrr_up :
             name === 'aFRR-' ? CHART_COLORS.afrr_down :
             name === 'mFRR+' ? CHART_COLORS.mfrr_up : CHART_COLORS.mfrr_down
    }))
  }

  const getCumulativeData = () => {
    const monthly = getMonthlyChartData()
    let cumulative = 0
    return monthly.map(m => {
      cumulative += m.profit
      return { ...m, cumulative }
    })
  }

  const getAnnualCashFlow = () => {
    if (!derivedMetrics) return []
    const monthsCount = simulation.months_count || simulation.monthly_results?.length || 1
    return [
      { category: 'Capacity Revenue', amount: simulation.total_capacity_revenue_eur * (12 / monthsCount), type: 'revenue' },
      { category: 'Activation Revenue', amount: simulation.total_activation_revenue_eur * (12 / monthsCount), type: 'revenue' },
      { category: 'Energy Cost (netted)', amount: simulation.total_energy_cost_eur * (12 / monthsCount), type: 'cost' },
      { category: 'Net Profit', amount: derivedMetrics.annualProfit, type: 'profit' },
    ]
  }

  const getThreeYearProjection = () => {
    if (!derivedMetrics) return []
    const baseRevenue = derivedMetrics.annualRevenue
    const baseProfit = derivedMetrics.annualProfit
    // Conservative, Base, Optimistic scenarios
    return [
      { year: 'Year 1', conservative: baseProfit * 0.85, base: baseProfit, optimistic: baseProfit * 1.15 },
      { year: 'Year 2', conservative: baseProfit * 0.90, base: baseProfit * 1.05, optimistic: baseProfit * 1.25 },
      { year: 'Year 3', conservative: baseProfit * 0.95, base: baseProfit * 1.10, optimistic: baseProfit * 1.35 },
    ]
  }

  return (
    <div className="space-y-4 sm:space-y-6 max-w-[1600px] mx-auto px-3 sm:px-0">
      {/* Bloomberg-Style Header - Mobile Optimized */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-slate-800 pb-3 sm:pb-4 gap-3 sm:gap-0">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
            <Zap className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
          </div>
          <div>
            <h1 className="text-lg sm:text-2xl font-bold text-white">aFRR Revenue Simulator</h1>
            <p className="text-xs sm:text-sm text-slate-400">
              Transelectrica Balancing Market • DAMAS
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-4">
          <div className="flex items-center gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-slate-800/50 border border-slate-700">
            <span className="w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] sm:text-xs text-slate-400">
              {marketStats?.data_metadata?.source_kind ? marketStats.data_metadata.source_kind.replaceAll('_', ' ').toUpperCase() : 'DATA SOURCE'}
            </span>
          </div>
          <div className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-[#00ffd1]/10 border border-[#00ffd1]/30">
            <span className="text-xs sm:text-sm text-[#00ffd1] font-mono">RO-TSO</span>
          </div>
        </div>
      </div>

      {/* Bloomberg-Style Market Overview Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        {/* Market Stats Card - Left */}
        <div className="lg:col-span-2 bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-xl p-3 sm:p-5">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3 sm:mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              <h2 className="text-base sm:text-lg font-semibold text-white">Romanian aFRR Market Overview</h2>
            </div>
            <span className="text-[10px] sm:text-xs text-slate-400 sm:ml-auto">{marketStats?.data_metadata?.bankability_level || 'source pending'}</span>
          </div>

          {marketStats?.data_metadata && (
            <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Source: {marketStats.data_metadata.source_kind} | Max date: {marketStats.data_metadata.data_date_max || 'unknown'} | Bankability: {marketStats.data_metadata.bankability_level}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-4 md:gap-4 mb-3 sm:mb-4">
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-1">aFRR+ Avg Price</p>
              <p className="text-base sm:text-xl font-bold text-[#00ffd1] font-mono">
                {marketStats?.afrr_stats?.up?.avg_price?.toFixed(1) || '175.0'} €
              </p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">per MWh activated</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-1">aFRR- Avg Price</p>
              <p className="text-base sm:text-xl font-bold text-amber-400 font-mono">
                {marketStats?.afrr_stats?.down?.avg_price?.toFixed(1) || '-33.0'} €
              </p>
              <p className="text-[9px] sm:text-[10px] text-amber-500 mt-0.5 sm:mt-1">Negative = You GET PAID!</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-1">% Negative Prices</p>
              <p className="text-base sm:text-xl font-bold text-amber-400 font-mono">
                {marketStats?.afrr_stats?.down?.pct_negative?.toFixed(0) || '41'}%
              </p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">of DOWN activations</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 sm:p-3">
              <p className="text-[9px] sm:text-[10px] uppercase tracking-wider text-slate-400 mb-1">Data Range</p>
              <p className="text-base sm:text-lg font-bold text-white font-mono">
                {marketStats?.total_slots ? (marketStats.total_slots / 96).toFixed(0) : '639'} days
              </p>
              <p className="text-[9px] sm:text-[10px] text-slate-400 mt-0.5 sm:mt-1">
                {marketStats?.date_range?.start || '2024-01'} → {marketStats?.date_range?.end || '2025-10'}
              </p>
            </div>
          </div>

          {/* Price Range Visualization */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-800/30 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-[#00ffd1] font-medium flex items-center gap-1">
                  <ArrowUpRight className="w-4 h-4" /> aFRR+ (UP)
                </span>
                <span className="text-xs text-slate-400">Discharge to grid</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-400">Min:</span>
                <span className="font-mono text-white">{marketStats?.afrr_stats?.up?.min_price?.toFixed(0) || '50'}€</span>
                <span className="text-slate-400 mx-2">|</span>
                <span className="text-slate-400">Max:</span>
                <span className="font-mono text-white">{marketStats?.afrr_stats?.up?.max_price?.toFixed(0) || '450'}€</span>
              </div>
              <div className="mt-2 h-2 bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-[#00d4aa] to-[#00ffd1]" style={{ width: '75%' }} />
              </div>
            </div>
            <div className="bg-slate-800/30 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-blue-400 font-medium flex items-center gap-1">
                  <ArrowDownRight className="w-4 h-4" /> aFRR- (DOWN)
                </span>
                <span className="text-xs text-slate-400">Charge from grid</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-400">Min:</span>
                <span className="font-mono text-amber-400">{marketStats?.afrr_stats?.down?.min_price?.toFixed(0) || '-150'}€</span>
                <span className="text-slate-400 mx-2">|</span>
                <span className="text-slate-400">Max:</span>
                <span className="font-mono text-white">{marketStats?.afrr_stats?.down?.max_price?.toFixed(0) || '200'}€</span>
              </div>
              <div className="mt-2 h-2 bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-amber-500 to-blue-500" style={{ width: '60%' }} />
              </div>
            </div>
          </div>
        </div>

        {/* Educational Card - Right */}
        <div className="bg-gradient-to-br from-blue-900/20 to-slate-900/50 border border-blue-500/30 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Info className="w-5 h-5 text-blue-400" />
            <h3 className="text-white font-semibold">How aFRR Works</h3>
          </div>

          <div className="space-y-4 text-sm">
            <div className="border-l-2 border-[#00ffd1] pl-3">
              <p className="text-[#00ffd1] font-medium">aFRR+ (Up-Regulation)</p>
              <p className="text-slate-400 text-xs mt-1">
                Grid frequency LOW → Battery DISCHARGES → Get paid activation price → Recharge later at PZU
              </p>
            </div>

            <div className="border-l-2 border-blue-400 pl-3">
              <p className="text-blue-400 font-medium">aFRR- (Down-Regulation)</p>
              <p className="text-slate-400 text-xs mt-1">
                Grid frequency HIGH → Battery CHARGES → Often GET PAID (negative prices!) → Save PZU cost
              </p>
            </div>

            <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 mt-4">
              <p className="text-amber-400 text-xs font-medium flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Romanian Market Insight
              </p>
              <p className="text-slate-400 text-[11px] mt-1">
                ~41% of aFRR- activations have negative prices. This means you GET PAID to charge your battery!
              </p>
            </div>

            <div className="pt-2 border-t border-slate-800">
              <p className="text-[10px] text-slate-400">
                Settlement: Pay-as-Bid per ANRE Order 2024. Capacity + Activation payments.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-5">
        <div className="panel-header mb-4">
          <span className="panel-title">Battery & Market Configuration</span>
        </div>

        {/* Product Selection */}
        <div className="mb-5">
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-3">
            FR Products
          </label>
          <div className="flex flex-wrap gap-2">
            {[
              { key: 'afrr_up', label: 'aFRR+ (Up)', color: 'blue', desc: 'Discharge' },
              { key: 'afrr_down', label: 'aFRR- (Down)', color: 'emerald', desc: 'Charge' },
              { key: 'mfrr_up', label: 'mFRR+ (Up)', color: 'cyan', desc: 'Discharge' },
              { key: 'mfrr_down', label: 'mFRR- (Down)', color: 'blue', desc: 'Charge' },
            ].map(({ key, label, color, desc }) => {
              const isEnabled = (params[key as keyof typeof params] as any)?.enabled
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleProduct(key)}
                  className={`px-4 py-2 rounded border text-sm font-medium transition-all ${
                    isEnabled
                      ? `border-${color}-500/50 bg-${color}-500/10 text-${color}-400`
                      : 'border-slate-700 bg-slate-800/50 text-slate-400'
                  }`}
                >
                  <span>{label}</span>
                  <span className="text-[10px] ml-1 opacity-60">({desc})</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Parameters Grid - Row 1: Battery Parameters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-3 sm:mb-4">
          <div>
            <label htmlFor="fr-power-mw" className="block text-[10px] sm:text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Power (MW)
            </label>
            <input
              id="fr-power-mw"
              type="number"
              min="0"
              value={params.afrr_up.power_mw}
              onChange={(e) => {
                const power = parseFloat(e.target.value) || 0
                setParams({
                  ...params,
                  afrr_up: { ...params.afrr_up, power_mw: power },
                  afrr_down: { ...params.afrr_down, power_mw: power },
                  mfrr_up: { ...params.mfrr_up, power_mw: power },
                  mfrr_down: { ...params.mfrr_down, power_mw: power },
                })
              }}
              className="input-dark w-full font-mono text-base sm:text-sm min-h-[44px] sm:min-h-[36px]"
            />
          </div>
          <div>
            <label htmlFor="fr-capacity-mwh" className="block text-[10px] sm:text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Capacity (MWh)
            </label>
            <input
              id="fr-capacity-mwh"
              type="number"
              min="0.1"
              value={params.capacity_mwh}
              onChange={(e) => setParams({ ...params, capacity_mwh: parseFloat(e.target.value) || 0 })}
              className="input-dark w-full font-mono text-base sm:text-sm min-h-[44px] sm:min-h-[36px]"
            />
          </div>
          <div>
            <label htmlFor="fr-round-trip-efficiency" className="block text-[10px] sm:text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Efficiency (%)
            </label>
            <input
              id="fr-round-trip-efficiency"
              type="number"
              step="1"
              value={Math.round(params.round_trip_efficiency * 100)}
              onChange={(e) => setParams({ ...params, round_trip_efficiency: (parseFloat(e.target.value) || 88) / 100 })}
              className="input-dark w-full font-mono text-base sm:text-sm min-h-[44px] sm:min-h-[36px]"
            />
          </div>
          <div>
            <label htmlFor="fr-investment-eur" className="block text-[10px] sm:text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Investment (€)
            </label>
            <input
              id="fr-investment-eur"
              type="number"
              min="0"
              value={params.investment_eur}
              onChange={(e) => setParams({ ...params, investment_eur: parseFloat(e.target.value) || 0 })}
              className="input-dark w-full font-mono text-base sm:text-sm min-h-[44px] sm:min-h-[36px]"
              step="100000"
            />
            <div className="text-[9px] sm:text-[10px] text-slate-400 mt-1">CAPEX for payback calc</div>
          </div>
        </div>

        {/* Parameters Grid - Row 2: Market Parameters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-3 sm:mb-4">
          <div>
            <label htmlFor="fr-capacity-price-eur-mw-h" className="flex items-center justify-between text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              <span>Capacity Price (EUR/MW/h)</span>
              {liveCanonical && (
                <span
                  className="px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[10px] font-mono normal-case"
                  title={`Live DAMAS combined UP+DOWN rate: €${liveCanonical.combined_eur_mw_h.toFixed(2)}/MW/h (window ${liveCanonical.window_start} → ${liveCanonical.window_end}, ${liveCanonical.n_samples} samples)`}
                >
                  Live €{liveCanonical.combined_eur_mw_h.toFixed(2)}
                </span>
              )}
            </label>
            <input
              id="fr-capacity-price-eur-mw-h"
              type="number"
              step="0.5"
              min="0"
              value={params.capacity_price_eur_mw_h}
              onChange={(e) => setParams({ ...params, capacity_price_eur_mw_h: parseFloat(e.target.value) || 0 })}
              className="input-dark w-full font-mono"
            />
            {liveCanonical && Math.abs(params.capacity_price_eur_mw_h - liveCanonical.combined_eur_mw_h) > 0.5 && (
              <button
                type="button"
                onClick={() => setParams((p) => ({ ...p, capacity_price_eur_mw_h: Number(liveCanonical.combined_eur_mw_h.toFixed(2)) }))}
                className="text-[10px] text-emerald-400 hover:text-emerald-300 mt-1"
              >
                ↻ Reset to live DAMAS rate
              </button>
            )}
          </div>
          <div>
            <label htmlFor="fr-activation-rate-slider" className="block text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Market Share / Activation Rate (%)
            </label>
            <div className="flex items-center gap-2">
              <input
                id="fr-activation-rate-slider"
                type="range"
                min="1"
                max="50"
                value={params.activation_rate * 100}
                onChange={(e) => setParams({ ...params, activation_rate: parseFloat(e.target.value) / 100 })}
                className="flex-1 h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
                aria-valuetext={`${(params.activation_rate * 100).toFixed(0)} percent market share / activation rate`}
              />
              <span className="text-sm font-mono text-[#00ffd1] w-12">{(params.activation_rate * 100).toFixed(0)}%</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-1">
              10% = realistic market share for 15MW new entrant. Higher rates (20-30%) = optimistic scenarios.
            </div>
          </div>
          <div>
            <label htmlFor="fr-energy-cost-eur-mwh" className="block text-xs uppercase tracking-wider text-slate-400 mb-1.5">
              Recharge Cost (EUR/MWh)
            </label>
            <input
              id="fr-energy-cost-eur-mwh"
              type="number"
              min="0"
              value={params.energy_cost_eur_mwh}
              onChange={(e) => setParams({ ...params, energy_cost_eur_mwh: parseFloat(e.target.value) || 0 })}
              className="input-dark w-full font-mono"
            />
            <div className="text-[10px] text-slate-400 mt-1">PZU price to recharge after UP activations</div>
          </div>
          <div className="flex items-end sm:col-span-1">
            <button
              type="button"
              onClick={runSimulation}
              disabled={isLoading}
              className="btn-primary w-full h-[48px] sm:h-[38px] text-base sm:text-sm font-semibold"
            >
              {isLoading ? 'Running...' : 'Run Simulation'}
            </button>
          </div>
        </div>

        {/* Pay-as-Bid Pricing */}
        <div className="border-t border-slate-800 pt-3 sm:pt-4 mt-3 sm:mt-4">
          <label className="block text-[10px] sm:text-xs uppercase tracking-wider text-slate-400 mb-2 sm:mb-3">
            Pay-as-Bid Activation Prices
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div>
              <label htmlFor="fr-activation-price-up-eur-mwh" className="block text-[10px] uppercase tracking-wider text-blue-400/70 mb-1">
                UP Activation (EUR/MWh)
              </label>
              <input
                id="fr-activation-price-up-eur-mwh"
                type="number"
                value={params.activation_price_up_eur_mwh}
                onChange={(e) => setParams({ ...params, activation_price_up_eur_mwh: parseFloat(e.target.value) || 0 })}
                className="input-dark w-full font-mono"
              />
            </div>
            <div>
              <label htmlFor="fr-activation-price-down-eur-mwh" className="block text-[10px] uppercase tracking-wider text-emerald-400/70 mb-1">
                DOWN Activation (EUR/MWh)
              </label>
              <input
                id="fr-activation-price-down-eur-mwh"
                type="number"
                value={params.activation_price_down_eur_mwh}
                onChange={(e) => setParams({ ...params, activation_price_down_eur_mwh: parseFloat(e.target.value) || 0 })}
                className="input-dark w-full font-mono"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <p className="text-red-400 text-sm">{error}</p>
          <p className="text-red-500/70 text-xs mt-1">API connection failed. Please try again.</p>
        </div>
      )}

      {/* Empty State */}
      {!simulation && !isLoading && !error && (
        <div className="bg-slate-900/30 border border-slate-800 rounded-lg p-12 text-center">
          <Zap className="h-10 w-10 text-slate-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-400">Ready to Simulate</h3>
          <p className="text-slate-400 mt-1 text-sm">
            Configure battery and market parameters, then run simulation
          </p>
        </div>
      )}

      {/* Results */}
      {simulation && derivedMetrics && (
        <>
          {/* A-1 / A-5: bankability + regime breakdown + regulatory notes
              surface BEFORE the headline numbers so investors see the
              context before they anchor on the revenue figure. */}
          <BankabilityBadge
            bankabilityLevel={simulation.bankability_level}
            settlementGrade={simulation.settlement_grade}
            sourceKind={simulation.source_kind}
            dataDateMax={simulation.data_date_max}
            bankabilitySummary={simulation.bankability_summary}
          />
          <RegimeBreakdownCard breakdowns={simulation.regime_breakdowns} />
          <RegulatoryNotesPanel
            notes={simulation.regulatory_notes}
            warnings={simulation.data_warnings}
          />

          {/* Executive Summary */}
          <div className="bg-gradient-to-r from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg p-3 sm:p-6">
            <div className="flex items-center gap-2 mb-3 sm:mb-4">
              <Target className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              <h2 className="text-base sm:text-lg font-semibold text-white">Executive Summary</h2>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4 lg:gap-6">
              <div>
                <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-slate-400 mb-1">Annual Revenue</div>
                <div className="text-lg sm:text-2xl font-bold text-white font-mono">
                  {formatCompact(derivedMetrics.annualRevenue)}
                </div>
                <div className="text-[10px] sm:text-xs text-slate-400 mt-1">
                  {formatCompact(derivedMetrics.revenuePerMW)}/MW
                </div>
              </div>
              <div>
                <div className="text-[10px] sm:text-[11px] uppercase tracking-wider text-slate-400 mb-1">Annual Net Profit</div>
                <div className="text-lg sm:text-2xl font-bold text-emerald-400 font-mono">
                  {formatCompact(derivedMetrics.annualProfit)}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {formatCompact(derivedMetrics.profitPerMW)}/MW
                </div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-1">Profit Margin</div>
                <div className="text-2xl font-bold text-[#00ffd1] font-mono">
                  {formatPercentage(derivedMetrics.profitMargin * 100)}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  After energy costs
                </div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-1">Monthly Average</div>
                <div className="text-2xl font-bold text-white font-mono">
                  {formatCompact(simulation.avg_monthly_net_profit_eur)}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  Net profit
                </div>
              </div>
            </div>
          </div>

          {/* KPI Cards Row - Annualized (12 months) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            <div className="stat-card">
              <div className="stat-label">Annual Revenue</div>
              <div className="stat-value text-white font-mono">
                {formatCompact(simulation.annual_revenue_eur)}
              </div>
              <div className="flex items-center mt-2 text-xs">
                <span className="text-slate-400">12-month projection (from {simulation.months_count} months data)</span>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Annual Capacity Revenue</div>
              <div className="stat-value text-[#00ffd1] font-mono">
                {formatCompact(simulation.annual_capacity_revenue_eur)}
              </div>
              <div className="text-xs text-slate-400 mt-2">
                {formatPercentage(derivedMetrics.capacityFactor * 100)} of total
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Annual Activation Revenue</div>
              <div className="stat-value text-emerald-400 font-mono">
                {formatCompact(simulation.annual_activation_revenue_eur)}
              </div>
              <div className="text-xs text-slate-400 mt-2">
                {formatPercentage(derivedMetrics.activationFactor * 100)} of total
              </div>
            </div>
            <div className="stat-card border-emerald-500/30">
              <div className="stat-label">Annual Net Profit</div>
              <div className="stat-value text-emerald-400 font-mono">
                {formatCompact(simulation.annual_net_profit_eur)}
              </div>
              <div className="text-xs text-slate-400 mt-2">
                -{formatCompact(simulation.annual_energy_cost_eur)} energy cost
              </div>
            </div>
          </div>

          {/* Monthly Price Trends - New Bloomberg-style Chart */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-[#00ffd1]" />
                <span className="panel-title">Monthly aFRR Price Trends</span>
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-[#00ffd1]" />
                  <span className="text-slate-400">aFRR+ (UP)</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-amber-500" />
                  <span className="text-slate-400">aFRR- (DOWN)</span>
                </span>
              </div>
            </div>
            <div className="p-4 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={simulation.monthly_results?.reduce((acc: any[], row: any) => {
                  const existing = acc.find(a => a.month === row.month)
                  if (existing) {
                    if (row.product === 'aFRR+') existing.upPrice = row.avg_activation_price_eur_mwh
                    if (row.product === 'aFRR-') existing.downPrice = row.avg_activation_price_eur_mwh
                  } else {
                    acc.push({
                      month: row.month,
                      upPrice: row.product === 'aFRR+' ? row.avg_activation_price_eur_mwh : 0,
                      downPrice: row.product === 'aFRR-' ? row.avg_activation_price_eur_mwh : 0,
                    })
                  }
                  return acc
                }, []) || []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="month"
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    tickFormatter={(v) => v.slice(5)}
                    axisLine={{ stroke: '#334155' }}
                  />
                  <YAxis
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    tickFormatter={(v) => `${v}€`}
                    axisLine={{ stroke: '#334155' }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1e293b',
                      border: '1px solid #334155',
                      borderRadius: '6px',
                      fontSize: '12px',
                    }}
                    formatter={(value: number, name: string) => [
                      `${value?.toFixed(1) || 0} €/MWh`,
                      name === 'upPrice' ? 'aFRR+ Price' : 'aFRR- Price'
                    ]}
                  />
                  <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
                  <Bar dataKey="upPrice" fill={CHART_COLORS.capacity} name="upPrice" radius={[4, 4, 0, 0]} />
                  <Line
                    type="monotone"
                    dataKey="downPrice"
                    stroke={CHART_COLORS.negative_price}
                    strokeWidth={3}
                    dot={{ fill: CHART_COLORS.negative_price, r: 4 }}
                    name="downPrice"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="px-4 py-2 bg-slate-900/50 border-t border-slate-800">
              <p className="text-[10px] text-slate-400">
                Note: aFRR- prices below zero (yellow line below axis) indicate you GET PAID to charge. This is common in Romania due to renewable oversupply.
              </p>
            </div>
          </div>

          {/* Revenue Breakdown Section */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Revenue Pie Chart */}
            <div className="chart-container">
              <div className="panel-header">
                <span className="panel-title">Revenue Breakdown</span>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <RechartsPieChart>
                    <Pie
                      data={getRevenueBreakdownData()}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                    >
                      {getRevenueBreakdownData().map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number) => formatCompact(value)}
                    />
                    <Legend
                      formatter={(value) => <span className="text-slate-400 text-xs">{value}</span>}
                    />
                  </RechartsPieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Product Performance */}
            <div className="chart-container">
              <div className="panel-header">
                <span className="panel-title">Product Performance</span>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={getProductBreakdownData()} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => formatCompact(v)}
                      axisLine={{ stroke: '#334155' }}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fill: '#94a3b8', fontSize: 11 }}
                      axisLine={{ stroke: '#334155' }}
                      width={60}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number, name: string) => [formatCompact(value), name === 'revenue' ? 'Revenue' : 'Profit']}
                    />
                    <Bar dataKey="revenue" fill={CHART_COLORS.capacity} name="Revenue" radius={[0, 4, 4, 0]} />
                    <Bar dataKey="profit" fill={CHART_COLORS.profit} name="Profit" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Cash Flow Metrics */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
              <div className="panel-header mb-4">
                <span className="panel-title">Key Metrics</span>
              </div>
              <div className="space-y-3">
                <div className="flex justify-between items-center py-2 border-b border-slate-800">
                  <span className="text-sm text-slate-400">Capacity Price</span>
                  <span className="font-mono text-[#00ffd1]">{params.capacity_price_eur_mw_h} EUR/MW/h</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-800">
                  <span className="text-sm text-slate-400">Activation Rate</span>
                  <span className="font-mono text-emerald-400">{(params.activation_rate * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-800">
                  <span className="text-sm text-slate-400">Avg Activation Price</span>
                  <span className="font-mono text-blue-400">
                    {(() => {
                      const totalEnergy = simulation.monthly_results?.reduce((sum: number, r: any) => sum + (r.activation_energy_mwh || 0), 0) || 0
                      const weightedSum = simulation.monthly_results?.reduce((sum: number, r: any) =>
                        sum + (r.avg_activation_price_eur_mwh || 0) * (r.activation_energy_mwh || 0), 0) || 0
                      const avgPrice = totalEnergy > 0 ? weightedSum / totalEnergy : 0
                      return formatNumber(avgPrice, { decimals: 2 })
                    })()} EUR/MWh
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-800">
                  <span className="text-sm text-slate-400">Energy Cost (netted)</span>
                  <span className="font-mono text-red-400">-{formatCompact(simulation.total_energy_cost_eur)}</span>
                </div>
                <div className="flex justify-between items-center py-2">
                  <span className="text-sm text-white font-medium">Revenue per MW/year</span>
                  <span className="font-mono text-white font-bold">{formatCompact(derivedMetrics.revenuePerMW)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
            {/* Monthly Revenue Trend */}
            <div className="chart-container">
              <div className="panel-header">
                <span className="panel-title">Monthly Revenue Trend</span>
                <span className="text-xs text-slate-400">Capacity vs Activation</span>
              </div>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={getMonthlyChartData()}>
                    <defs>
                      <linearGradient id="capacityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={CHART_COLORS.capacity} stopOpacity={0.4} />
                        <stop offset="95%" stopColor={CHART_COLORS.capacity} stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="activationGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={CHART_COLORS.activation} stopOpacity={0.4} />
                        <stop offset="95%" stopColor={CHART_COLORS.activation} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="month"
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => v.slice(5)}
                      axisLine={{ stroke: '#334155' }}
                    />
                    <YAxis
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => formatCompact(v)}
                      axisLine={{ stroke: '#334155' }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number, name: string) => [
                        formatCompact(value),
                        name === 'capacity' ? 'Capacity' : 'Activation'
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="capacity"
                      stroke={CHART_COLORS.capacity}
                      fill="url(#capacityGradient)"
                      strokeWidth={2}
                      stackId="1"
                    />
                    <Area
                      type="monotone"
                      dataKey="activation"
                      stroke={CHART_COLORS.activation}
                      fill="url(#activationGradient)"
                      strokeWidth={2}
                      stackId="1"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Cumulative Profit Chart */}
            <div className="chart-container">
              <div className="panel-header">
                <span className="panel-title">Cumulative Net Profit</span>
                <span className="text-xs text-slate-400">Running total</span>
              </div>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={getCumulativeData()}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="month"
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => v.slice(5)}
                      axisLine={{ stroke: '#334155' }}
                    />
                    <YAxis
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => formatCompact(v)}
                      axisLine={{ stroke: '#334155' }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number, name: string) => [
                        formatCompact(value),
                        name === 'profit' ? 'Monthly' : 'Cumulative'
                      ]}
                    />
                    <Bar dataKey="profit" fill={CHART_COLORS.profit} opacity={0.5} radius={[4, 4, 0, 0]} />
                    <Line type="monotone" dataKey="cumulative" stroke="#fff" strokeWidth={2} dot={{ fill: '#fff', r: 3 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Annual Cash Flow & 3-Year Projection */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Annual Cash Flow */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-[#00ffd1]" />
                  <span className="panel-title">Annual Cash Flow (Projected)</span>
                </div>
              </div>
              <div className="p-4">
                <div className="space-y-3">
                  {getAnnualCashFlow().map((item, idx) => (
                    <div key={idx} className={`flex justify-between items-center py-2 ${idx < getAnnualCashFlow().length - 1 ? 'border-b border-slate-800' : 'border-t border-slate-700 pt-3'}`}>
                      <span className={`text-sm ${item.type === 'profit' ? 'text-white font-semibold' : 'text-slate-400'}`}>
                        {item.category}
                      </span>
                      <span className={`font-mono ${
                        item.type === 'cost' ? 'text-red-400' :
                        item.type === 'profit' ? 'text-emerald-400 font-bold' :
                        'text-slate-200'
                      }`}>
                        {item.type === 'cost' ? '-' : '+'}{formatCompact(item.amount)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* 3-Year Projection */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-emerald-500" />
                  <span className="panel-title">3-Year Profit Projection</span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="data-grid">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th className="text-right text-red-400">Conservative</th>
                      <th className="text-right text-[#00ffd1]">Base</th>
                      <th className="text-right text-emerald-400">Optimistic</th>
                    </tr>
                  </thead>
                  <tbody>
                    {getThreeYearProjection().map((row, idx) => (
                      <tr key={idx}>
                        <td className="text-slate-300 font-medium">{row.year}</td>
                        <td className="text-right text-red-400 font-mono">{formatCompact(row.conservative)}</td>
                        <td className="text-right text-[#00ffd1] font-mono">{formatCompact(row.base)}</td>
                        <td className="text-right text-emerald-400 font-mono">{formatCompact(row.optimistic)}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-slate-700">
                      <td className="text-white font-semibold">3Y Total</td>
                      <td className="text-right text-red-400 font-mono font-bold">
                        {formatCompact(getThreeYearProjection().reduce((sum, r) => sum + r.conservative, 0))}
                      </td>
                      <td className="text-right text-[#00ffd1] font-mono font-bold">
                        {formatCompact(getThreeYearProjection().reduce((sum, r) => sum + r.base, 0))}
                      </td>
                      <td className="text-right text-emerald-400 font-mono font-bold">
                        {formatCompact(getThreeYearProjection().reduce((sum, r) => sum + r.optimistic, 0))}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Monthly Breakdown Table */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800">
              <span className="panel-title">Monthly Breakdown by Product</span>
            </div>
            <div className="overflow-x-auto">
              <table className="data-grid">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Product</th>
                    <th className="text-right">Slots</th>
                    <th className="text-right">Capacity Rev</th>
                    <th className="text-right">Activation Rev</th>
                    <th className="text-right">Energy (MWh)</th>
                    <th className="text-right">Energy Cost</th>
                    <th className="text-right">Net Profit</th>
                    <th>Pricing</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {simulation.monthly_results?.map((row: any, idx: number) => (
                    <tr key={idx}>
                      <td className="text-slate-300">{row.month}</td>
                      <td>
                        <span className={`px-2 py-0.5 text-[10px] font-medium rounded ${
                          row.product === 'aFRR+' ? 'bg-blue-500/20 text-blue-400' :
                          row.product === 'aFRR-' ? 'bg-emerald-500/20 text-emerald-400' :
                          row.product === 'mFRR+' ? 'bg-[#00ffd1]/20 text-[#00ffd1]' :
                          'bg-blue-500/20 text-blue-400'
                        }`}>
                          {row.product}
                        </span>
                      </td>
                      <td className="text-right text-slate-400 font-mono">
                        {formatNumber(row.total_slots)}
                      </td>
                      <td className="text-right text-[#00ffd1] font-mono">
                        {formatCompact(row.capacity_revenue_eur)}
                      </td>
                      <td className="text-right text-emerald-400 font-mono">
                        {formatCompact(row.activation_revenue_eur)}
                      </td>
                      <td className="text-right text-slate-400 font-mono">
                        {formatNumber(row.activation_energy_mwh, { decimals: 1 })}
                      </td>
                      <td className="text-right text-red-400 font-mono">
                        -{formatCompact(row.energy_cost_eur)}
                      </td>
                      <td className="text-right font-medium text-emerald-400 font-mono">
                        {formatCompact(row.net_profit_eur)}
                      </td>
                      <td>
                        <PricingBasisBadge basis={row.pricing_basis} />
                      </td>
                      <td>
                        <ConfidenceBadge label={row.confidence_label} short />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
      {/* 4 Scenarios Comparison - Dynamic */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Battery className="w-4 h-4 text-[#00ffd1]" />
            <span className="panel-title">FR Market Scenarios ({params.afrr_up.power_mw} MW / {params.capacity_mwh} MWh)</span>
          </div>
          <p className="text-xs text-slate-400 mt-1">Based on catalogued Romanian market data. Not participant settlement unless source_kind is settlement_export.</p>

          {/* Disclaimer for simplified calculations */}
          <div className="mt-3 bg-amber-500/10 border border-amber-500/30 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs font-semibold text-amber-400">
                  Calibrated to live DAMAS rates · Indicative only
                </p>
                <p className="text-xs text-amber-300/80 mt-1">
                  Capacity prices anchored to the live DAMAS rate (€11.64/MW/h, post-commit 97e4d2e).
                  Activation revenue scales linearly with PICASSO market share around the live 10% baseline (7,361 MWh/yr observed).
                  OPEX 2.5% of CAPEX. Use the main simulation above for full SOC trajectory + degradation + 15-yr cashflow.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="data-grid">
            <thead>
              <tr>
                <th>Scenario</th>
                <th className="text-center">Activation Rate</th>
                <th className="text-center">Capacity Price</th>
                <th className="text-center">Activation Price</th>
                <th className="text-right">Annual Revenue</th>
                <th className="text-right">Annual Profit</th>
                <th className="text-right">ROI ({formatCompact(params.investment_eur)})</th>
              </tr>
            </thead>
            <tbody>
              {[
                // Capacity prices = COMBINED UP+DOWN rate per MW per hour.
                // Live anchor: €11.64/MW/h (last-12mo, both directions). Activation
                // prices = volume-weighted across UP+DOWN dispatch (live observed
                // €146/MWh). Activation rate = PICASSO market-share fraction.
                { name: 'Pessimistic', desc: 'Post-MARI compression, 5% share', actRate: 0.05, capPrice: 9, actPrice: 130, color: 'red' },
                { name: 'Base Case', desc: 'Live last-12mo, 10% share', actRate: 0.10, capPrice: 11.64, actPrice: 146, color: 'emerald', highlight: true },
                { name: 'Moderate', desc: 'Established player, 12% share', actRate: 0.12, capPrice: 12, actPrice: 155, color: 'blue' },
                { name: 'Optimistic', desc: 'Premium ops, 20% share', actRate: 0.20, capPrice: 13, actPrice: 170, color: 'emerald' },
              ].map((scenario) => {
                const power = params.afrr_up.power_mw
                const hoursPerYear = 8760
                const efficiency = params.round_trip_efficiency
                const rechargeCost = params.energy_cost_eur_mwh
                const capexEur = params.investment_eur

                // Capacity revenue: power × capacity_price × 8760h.
                // capPrice already represents the combined UP+DOWN rate per MW.h
                // (live = €11.64/MW/h), so NO ×2 multiplier.
                const capacityRevenue = power * scenario.capPrice * hoursPerYear

                // Activation revenue: live observation = ~7,361 MWh/yr at 10% PICASSO share.
                // Scale linearly with share.
                const liveActivationMwhAt10pct = 7361
                const activationMwh = liveActivationMwhAt10pct * (scenario.actRate / 0.10)
                const activationRevenue = activationMwh * scenario.actPrice

                // Recharge cost: only UP-direction activations require buying energy back from PZU.
                // Live data shows roughly 50/50 UP/DOWN split, so ~half the activation MWh needs recharge.
                const rechargeMwh = (activationMwh * 0.5) / efficiency
                const rechargeCosts = rechargeMwh * rechargeCost

                // OPEX: 2.5% of CAPEX (2.0% O&M + 0.5% insurance).
                const opex = capexEur * 0.025

                const annualRevenue = capacityRevenue + activationRevenue
                const annualProfit = annualRevenue - rechargeCosts - opex
                const roi = (annualProfit / capexEur) * 100

                return (
                  <tr key={scenario.name} className={scenario.highlight ? 'bg-slate-800/30' : ''}>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full bg-${scenario.color}-500`}></div>
                        <span className={scenario.highlight ? 'text-white font-medium' : 'text-slate-300 font-medium'}>{scenario.name}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 ml-4">{scenario.desc}</div>
                    </td>
                    <td className={`text-center text-${scenario.color}-400 font-mono`}>{(scenario.actRate * 100).toFixed(0)}%</td>
                    <td className="text-center text-slate-400 font-mono">{scenario.capPrice} €/MW/h</td>
                    <td className="text-center text-slate-400 font-mono">{scenario.actPrice} €/MWh</td>
                    <td className="text-right text-slate-200 font-mono">{formatCompact(annualRevenue)}</td>
                    <td className="text-right text-emerald-400 font-mono">{formatCompact(annualProfit)}</td>
                    <td className={`text-right text-${scenario.color}-400 font-mono`}>{roi.toFixed(1)}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-slate-800 bg-slate-900/30">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-400">
            <div>
              <span className="text-[#00ffd1] font-medium">System:</span> {params.afrr_up.power_mw} MW / {params.capacity_mwh} MWh, {(params.round_trip_efficiency * 100).toFixed(0)}% efficiency
            </div>
            <div>
              <span className="text-emerald-400 font-medium">Products:</span> aFRR+/aFRR- bidirectional
            </div>
            <div>
              <span className="text-blue-400 font-medium">Recharge Cost:</span> {params.energy_cost_eur_mwh} €/MWh (PZU avg)
            </div>
          </div>
          <p className="text-[10px] text-slate-400 mt-2">
            * PICASSO market share: 5% = entrant, 10% = live last-12mo baseline, 12% = established, 20% = premium ops.
            Capacity revenue paid for both UP + DOWN envelopes (×2). Activation MWh scales linearly with share from live 7,361 MWh/yr at 10%.
          </p>
        </div>
      </div>
        </>
      )}

      {/* DAMAS Price Explorer Section */}
      <div className="mt-8 bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
        <div className="bg-gradient-to-r from-slate-900 to-slate-800 px-6 py-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Activity className="w-6 h-6 text-[#00ffd1]" />
              <h2 className="text-lg font-semibold text-white">DAMAS aFRR Price Explorer</h2>
            </div>
            <span className="px-2 py-1 bg-[#00ffd1]/10 border border-[#00ffd1]/30 text-[#00ffd1] text-xs font-mono rounded">
              15-min slots
            </span>
          </div>
        </div>

        <div className="p-6">
          {/* Date Selector */}
          <div className="flex items-center gap-4 mb-6">
            <button
              type="button"
              aria-label="Previous date"
              onClick={() => {
                const currentIndex = availableDates.findIndex(d => d.date === selectedDate)
                if (currentIndex > 0) {
                  setSelectedDate(availableDates[currentIndex - 1].date)
                }
              }}
              disabled={!selectedDate || availableDates.findIndex(d => d.date === selectedDate) === 0}
              className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed rounded border border-slate-700 transition-colors"
            >
              <ChevronLeft className="w-5 h-5 text-slate-300" />
            </button>

            <input
              type="date"
              aria-label="Selected date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="flex-1 px-4 py-2 bg-slate-800 border border-slate-700 rounded text-white font-mono"
            />

            <button
              type="button"
              aria-label="Next date"
              onClick={() => {
                const currentIndex = availableDates.findIndex(d => d.date === selectedDate)
                if (currentIndex < availableDates.length - 1 && currentIndex !== -1) {
                  setSelectedDate(availableDates[currentIndex + 1].date)
                }
              }}
              disabled={!selectedDate || availableDates.findIndex(d => d.date === selectedDate) === availableDates.length - 1}
              className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed rounded border border-slate-700 transition-colors"
            >
              <ChevronRight className="w-5 h-5 text-slate-300" />
            </button>
          </div>

          {loadingSlots && (
            <div className="text-center py-12 text-slate-400">
              <Activity className="w-8 h-8 mx-auto mb-3 animate-spin" />
              <p>Loading slot data...</p>
            </div>
          )}

          {slotPrices && !loadingSlots && (
            <>
              {/* Summary Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-slate-400 text-sm">Date</span>
                    <Calendar className="w-4 h-4 text-slate-400" />
                  </div>
                  <p className="text-xl font-bold text-white font-mono">{slotPrices.date}</p>
                  <p className="text-xs text-slate-400 mt-1">{slotPrices.day_of_week}</p>
                </div>

                <div className="bg-slate-800/50 border border-[#00ffd1]/30 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-slate-400 text-sm">aFRR+ Revenue</span>
                    <ArrowUpRight className="w-4 h-4 text-[#00ffd1]" />
                  </div>
                  <p className="text-2xl font-bold text-[#00ffd1] font-mono">€{slotPrices.total_afrr_up_revenue.toLocaleString()}</p>
                  <p className="text-xs text-slate-400 mt-1">Avg: {slotPrices.afrr_up_avg_price} €/MWh</p>
                </div>

                <div className="bg-slate-800/50 border border-blue-500/30 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-slate-400 text-sm">aFRR- Revenue</span>
                    <ArrowDownRight className="w-4 h-4 text-blue-400" />
                  </div>
                  <p className="text-2xl font-bold text-blue-400 font-mono">€{slotPrices.total_afrr_down_revenue.toLocaleString()}</p>
                  <p className="text-xs text-slate-400 mt-1">Avg: {slotPrices.afrr_down_avg_price} €/MWh</p>
                </div>

                <div className="bg-slate-800/50 border border-emerald-500/30 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-slate-400 text-sm">Total Revenue</span>
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  </div>
                  <p className="text-2xl font-bold text-emerald-400 font-mono">€{slotPrices.total_revenue.toLocaleString()}</p>
                  <p className="text-xs text-slate-400 mt-1">{params.afrr_up.power_mw} MW system</p>
                </div>
              </div>

              {/* 96-Slot Bar Chart (15-minute intervals) */}
              <div className="bg-slate-800/30 border border-slate-700 rounded-lg p-4 mb-6">
                <h3 className="text-sm font-medium text-slate-300 mb-4">15-Minute Slot Revenues (96 slots)</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={slotPrices.slot_prices}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="hour"
                      stroke="#94a3b8"
                      tick={{ fontSize: 10 }}
                      interval={7}
                    />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '6px' }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Bar dataKey="afrr_up_revenue" fill="#00ffd1" name="aFRR+ Revenue (€)" />
                    <Bar dataKey="afrr_down_revenue" fill="#3b82f6" name="aFRR- Revenue (€)" />
                  </BarChart>
                </ResponsiveContainer>
                <div className="flex items-center justify-center gap-6 mt-3 text-xs">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 bg-[#00ffd1] rounded"></div>
                    <span className="text-slate-400">aFRR+ (UP regulation)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 bg-blue-500 rounded"></div>
                    <span className="text-slate-400">aFRR- (DOWN regulation)</span>
                  </div>
                </div>
              </div>

              {/* Slot Price Table (showing every 4th slot = hourly) */}
              <div className="bg-slate-800/30 border border-slate-700 rounded-lg overflow-hidden mb-6">
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-800 sticky top-0 z-10">
                      <tr>
                        <th className="text-left px-4 py-3 text-slate-300 font-medium">Time</th>
                        <th className="text-center px-4 py-3 text-slate-300 font-medium">Selected</th>
                        <th className="text-right px-4 py-3 text-slate-300 font-medium">aFRR+ Price</th>
                        <th className="text-right px-4 py-3 text-slate-300 font-medium">aFRR- Price</th>
                        <th className="text-right px-4 py-3 text-slate-300 font-medium">Revenue</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono">
                      {slotPrices.slot_prices.filter((_: any, idx: number) => idx % 4 === 0).map((slot: any) => (
                        <tr key={slot.slot} className="border-t border-slate-700 hover:bg-slate-800/50">
                          <td className="px-4 py-2 text-white">{slot.hour}</td>
                          <td className="px-4 py-2 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                              slot.selected_service === 'aFRR+'
                                ? 'bg-[#00ffd1]/20 text-[#00ffd1]'
                                : 'bg-blue-500/20 text-blue-400'
                            }`}>
                              {slot.selected_service}
                            </span>
                          </td>
                          <td className={`px-4 py-2 text-right ${
                            slot.selected_service === 'aFRR+'
                              ? 'text-[#00ffd1] font-semibold'
                              : 'text-slate-400'
                          }`}>
                            {slot.afrr_up_price.toFixed(2)} €
                          </td>
                          <td className={`px-4 py-2 text-right ${
                            slot.selected_service === 'aFRR-'
                              ? slot.afrr_down_price < 0
                                ? 'text-amber-400 font-semibold'
                                : 'text-blue-400 font-semibold'
                              : 'text-slate-400'
                          }`}>
                            {slot.afrr_down_price.toFixed(2)} €
                            {slot.afrr_down_price < 0 && slot.selected_service === 'aFRR-' && <span className="text-amber-400 ml-1">⚡</span>}
                          </td>
                          <td className="px-4 py-2 text-right text-emerald-400 font-semibold">
                            €{(slot.afrr_up_revenue + slot.afrr_down_revenue).toFixed(0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-4 py-2 bg-slate-900/50 border-t border-slate-700 text-xs">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="text-slate-400">
                      <span className="text-amber-400">⚡</span> = Negative price (you get paid to charge!)
                    </div>
                    <div className="text-slate-400">
                      <span className="text-[#00ffd1] font-semibold">Note:</span> Battery can only provide ONE service per slot (aFRR+ OR aFRR-, not both). Selected service is the most profitable option.
                    </div>
                  </div>
                </div>
              </div>

              {/* Date Grid (Last 60 days) */}
              <div className="bg-slate-800/30 border border-slate-700 rounded-lg p-4 mb-4">
                <h3 className="text-sm font-medium text-slate-300 mb-3">Quick Date Selection (Recent 60 days)</h3>
                <div className="grid grid-cols-10 gap-1">
                  {availableDates.slice(-60).map((dateInfo: any) => (
                    <button
                      key={dateInfo.date}
                      type="button"
                      onClick={() => setSelectedDate(dateInfo.date)}
                      className={`p-1 text-[10px] rounded transition-colors ${
                        dateInfo.date === selectedDate
                          ? 'bg-[#00ffd1] text-slate-900 font-bold'
                          : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                      }`}
                      title={`${dateInfo.date}\naFRR+: ${dateInfo.afrr_up_avg}€\naFRR-: ${dateInfo.afrr_down_avg}€`}
                    >
                      {dateInfo.date.split('-')[2]}
                    </button>
                  ))}
                </div>
              </div>

              {/* DAMAS Link */}
              {slotPrices.damas_url && (
                <a
                  href={slotPrices.damas_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-[#00ffd1] font-medium transition-colors"
                >
                  <span>View on DAMAS Transelectrica</span>
                  <ExternalLink className="w-4 h-4" />
                </a>
              )}
            </>
          )}
        </div>
      </div>

      {/* Bidding Optimizer Section */}
      <div className="mt-8 bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
        <div className="bg-gradient-to-r from-slate-900 to-slate-800 px-6 py-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Target className="w-6 h-6 text-[#00ffd1]" />
              <h2 className="text-lg font-semibold text-white">aFRR Bidding Optimizer</h2>
            </div>
            <span className="px-2 py-1 bg-[#00ffd1]/10 border border-[#00ffd1]/30 text-[#00ffd1] text-xs font-mono rounded">
              AI-Powered
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-2">
            Analyze {biddingStrategy?.analysis_period?.total_days || 638} days of historical data to optimize your bidding strategy
          </p>
        </div>

        <div className="p-6 space-y-6">
          {loadingBidding && (
            <div className="text-center py-12 text-slate-400">
              <Activity className="w-8 h-8 mx-auto mb-3 animate-spin" />
              <p>Analyzing historical data...</p>
            </div>
          )}

          {!loadingBidding && biddingStrategy && (
            <>
              {/* Optimal Bid Prices for Selected Date */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* aFRR+ Optimal Bid */}
                <div className="bg-slate-800/50 border border-[#00ffd1]/30 rounded-lg p-6">
                  <div className="flex items-center gap-2 mb-4">
                    <ArrowUpRight className="w-5 h-5 text-[#00ffd1]" />
                    <h3 className="text-lg font-semibold text-white">aFRR+ Optimal Bid</h3>
                  </div>

                  {optimalBids && (
                    <>
                      <div className="mb-4">
                        <label htmlFor="fr-target-acceptance-slider" className="block text-sm text-slate-400 mb-2">Target Acceptance Rate</label>
                        <input
                          id="fr-target-acceptance-slider"
                          type="range"
                          min="0.5"
                          max="0.95"
                          step="0.05"
                          value={targetAcceptance}
                          onChange={(e) => setTargetAcceptance(parseFloat(e.target.value))}
                          className="w-full"
                          aria-valuetext={`${(targetAcceptance * 100).toFixed(0)} percent target acceptance rate`}
                        />
                        <div className="flex justify-between text-xs text-slate-400 mt-1">
                          <span>50%</span>
                          <span className="text-[#00ffd1] font-bold">{(targetAcceptance * 100).toFixed(0)}%</span>
                          <span>95%</span>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">Recommended Capacity Bid:</span>
                          <span className="text-2xl font-bold text-[#00ffd1] font-mono">
                            {optimalBids.optimal_bids.afrr_up.recommended_capacity_bid} €/MW/h
                          </span>
                        </div>
                        <div className="flex justify-between items-center text-sm">
                          <span className="text-slate-400">Based on activation price:</span>
                          <span className="text-slate-300 font-mono">
                            {optimalBids.optimal_bids.afrr_up.based_on_activation_price} €/MWh
                          </span>
                        </div>
                        <div className="border-t border-slate-700 pt-3">
                          <div className="flex justify-between items-center mb-2">
                            <span className="text-slate-400">Est. Daily Revenue:</span>
                            <span className="text-xl font-bold text-emerald-400 font-mono">
                              €{optimalBids.optimal_bids.afrr_up.estimated_daily_revenue.toLocaleString()}
                            </span>
                          </div>
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div className="bg-slate-900/50 rounded p-2">
                              <div className="text-slate-400">Capacity</div>
                              <div className="text-white font-mono">€{optimalBids.optimal_bids.afrr_up.capacity_component.toLocaleString()}</div>
                            </div>
                            <div className="bg-slate-900/50 rounded p-2">
                              <div className="text-slate-400">Activation</div>
                              <div className="text-white font-mono">€{optimalBids.optimal_bids.afrr_up.activation_component.toLocaleString()}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </div>

                {/* aFRR- Optimal Bid */}
                <div className="bg-slate-800/50 border border-blue-500/30 rounded-lg p-6">
                  <div className="flex items-center gap-2 mb-4">
                    <ArrowDownRight className="w-5 h-5 text-blue-400" />
                    <h3 className="text-lg font-semibold text-white">aFRR- Optimal Bid</h3>
                  </div>

                  {optimalBids && (
                    <>
                      <div className="mb-4">
                        <label className="block text-sm text-slate-400 mb-2">Target Acceptance Rate</label>
                        <div className="h-12 flex items-center justify-center">
                          <span className="text-slate-400 text-sm">(Same as aFRR+)</span>
                        </div>
                        <div className="flex justify-center text-xs text-blue-400 font-bold mt-1">
                          {(targetAcceptance * 100).toFixed(0)}%
                        </div>
                      </div>

                      <div className="space-y-3">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-400">Recommended Capacity Bid:</span>
                          <span className="text-2xl font-bold text-blue-400 font-mono">
                            {optimalBids.optimal_bids.afrr_down.recommended_capacity_bid} €/MW/h
                          </span>
                        </div>
                        <div className="flex justify-between items-center text-sm">
                          <span className="text-slate-400">Based on activation price:</span>
                          <span className="text-slate-300 font-mono">
                            {optimalBids.optimal_bids.afrr_down.based_on_activation_price} €/MWh
                          </span>
                        </div>
                        <div className="border-t border-slate-700 pt-3">
                          <div className="flex justify-between items-center mb-2">
                            <span className="text-slate-400">Est. Daily Revenue:</span>
                            <span className="text-xl font-bold text-emerald-400 font-mono">
                              €{optimalBids.optimal_bids.afrr_down.estimated_daily_revenue.toLocaleString()}
                            </span>
                          </div>
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div className="bg-slate-900/50 rounded p-2">
                              <div className="text-slate-400">Capacity</div>
                              <div className="text-white font-mono">€{optimalBids.optimal_bids.afrr_down.capacity_component.toLocaleString()}</div>
                            </div>
                            <div className="bg-slate-900/50 rounded p-2">
                              <div className="text-slate-400">Activation</div>
                              <div className="text-white font-mono">€{optimalBids.optimal_bids.afrr_down.activation_component.toLocaleString()}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Recommendation Banner */}
              {optimalBids && (
                <div className={`border rounded-lg p-4 ${
                  optimalBids.recommendation === 'aFRR+'
                    ? 'bg-[#00ffd1]/10 border-[#00ffd1]/30'
                    : 'bg-blue-500/10 border-blue-500/30'
                }`}>
                  <div className="flex items-center gap-3">
                    <TrendingUp className={`w-5 h-5 ${
                      optimalBids.recommendation === 'aFRR+' ? 'text-[#00ffd1]' : 'text-blue-400'
                    }`} />
                    <div>
                      <div className="font-semibold text-white">
                        Recommended: <span className={
                          optimalBids.recommendation === 'aFRR+' ? 'text-[#00ffd1]' : 'text-blue-400'
                        }>{optimalBids.recommendation}</span>
                      </div>
                      <div className="text-sm text-slate-400 mt-1">
                        For {selectedDate} with {(targetAcceptance * 100).toFixed(0)}% acceptance rate
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Historical Strategy Analysis */}
              <div className="bg-slate-800/30 border border-slate-700 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-white mb-4">Historical Performance Analysis</h3>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <ArrowUpRight className="w-4 h-4 text-[#00ffd1]" />
                      <span className="text-slate-300 font-medium">aFRR+ Statistics</span>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Avg Price:</span>
                        <span className="text-[#00ffd1] font-mono">{biddingStrategy.afrr_up.avg_price} €/MWh</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Conservative (90%):</span>
                        <span className="text-slate-300 font-mono">{biddingStrategy.afrr_up.percentiles.p20} €/MWh</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Balanced (80%):</span>
                        <span className="text-slate-300 font-mono">{biddingStrategy.afrr_up.percentiles.p50} €/MWh</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Aggressive (60%):</span>
                        <span className="text-slate-300 font-mono">{biddingStrategy.afrr_up.percentiles.p70} €/MWh</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <ArrowDownRight className="w-4 h-4 text-blue-400" />
                      <span className="text-slate-300 font-medium">aFRR- Statistics</span>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Avg Price:</span>
                        <span className="text-blue-400 font-mono">{biddingStrategy.afrr_down.avg_price} €/MWh</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Negative Price %:</span>
                        <span className="text-amber-400 font-mono">{biddingStrategy.afrr_down.negative_price_percentage}%</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Conservative (90%):</span>
                        <span className="text-slate-300 font-mono">{biddingStrategy.afrr_down.percentiles.p20} €/MWh</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Balanced (80%):</span>
                        <span className="text-slate-300 font-mono">{biddingStrategy.afrr_down.percentiles.p50} €/MWh</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-4">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-emerald-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="font-semibold text-emerald-300 mb-1">Strategy Recommendation</div>
                      <div className="text-sm text-slate-300">
                        {biddingStrategy.profitability_comparison.recommendation}
                      </div>
                      <div className="text-xs text-slate-400 mt-2">
                        Profitability Ratio (UP/DOWN): {biddingStrategy.profitability_comparison.ratio}x
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* 12-Month Revenue Projection */}
              <div className="bg-slate-800/30 border border-slate-700 rounded-lg p-6">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-white">12-Month Revenue Projection</h3>
                  <div className="flex gap-2">
                    {['conservative', 'balanced', 'aggressive'].map((strategy) => (
                      <button
                        key={strategy}
                        type="button"
                        onClick={() => setSelectedStrategy(strategy)}
                        className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                          selectedStrategy === strategy
                            ? 'bg-[#00ffd1] text-slate-900'
                            : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                        }`}
                      >
                        {strategy.charAt(0).toUpperCase() + strategy.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                {revenueProjection && (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                      <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                        <div className="text-slate-400 text-sm mb-1">Acceptance Rate</div>
                        <div className="text-2xl font-bold text-[#00ffd1] font-mono">
                          {(revenueProjection.acceptance_rate * 100).toFixed(0)}%
                        </div>
                      </div>
                      <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                        <div className="text-slate-400 text-sm mb-1">Projected Annual Revenue</div>
                        <div className="text-2xl font-bold text-emerald-400 font-mono">
                          €{(revenueProjection.total_projected_annual_revenue / 1000000).toFixed(2)}M
                        </div>
                      </div>
                      <div className="bg-slate-900/50 border border-slate-700 rounded-lg p-4">
                        <div className="text-slate-400 text-sm mb-1">Avg Monthly Revenue</div>
                        <div className="text-2xl font-bold text-white font-mono">
                          €{revenueProjection.avg_monthly_revenue.toLocaleString()}
                        </div>
                      </div>
                    </div>

                    {/* Monthly Breakdown Table */}
                    <div className="bg-slate-900/30 border border-slate-700 rounded-lg overflow-hidden">
                      <div className="overflow-x-auto max-h-96">
                        <table className="w-full text-sm">
                          <thead className="bg-slate-800 sticky top-0 z-10">
                            <tr>
                              <th className="text-left px-4 py-3 text-slate-300 font-medium">Month</th>
                              <th className="text-center px-4 py-3 text-slate-300 font-medium">Selected Service</th>
                              <th className="text-right px-4 py-3 text-slate-300 font-medium">aFRR+ Revenue</th>
                              <th className="text-right px-4 py-3 text-slate-300 font-medium">aFRR- Revenue</th>
                              <th className="text-right px-4 py-3 text-slate-300 font-medium">Monthly Revenue</th>
                            </tr>
                          </thead>
                          <tbody className="font-mono">
                            {revenueProjection.monthly_projections.map((month: any) => (
                              <tr key={month.month} className="border-t border-slate-700 hover:bg-slate-800/50">
                                <td className="px-4 py-2 text-white">{month.month}</td>
                                <td className="px-4 py-2 text-center">
                                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                                    month.selected_service === 'aFRR+'
                                      ? 'bg-[#00ffd1]/20 text-[#00ffd1]'
                                      : 'bg-blue-500/20 text-blue-400'
                                  }`}>
                                    {month.selected_service}
                                  </span>
                                </td>
                                <td className={`px-4 py-2 text-right ${
                                  month.selected_service === 'aFRR+' ? 'text-[#00ffd1] font-semibold' : 'text-slate-400'
                                }`}>
                                  €{month.afrr_up_revenue.toLocaleString()}
                                </td>
                                <td className={`px-4 py-2 text-right ${
                                  month.selected_service === 'aFRR-' ? 'text-blue-400 font-semibold' : 'text-slate-400'
                                }`}>
                                  €{month.afrr_down_revenue.toLocaleString()}
                                </td>
                                <td className="px-4 py-2 text-right text-emerald-400 font-semibold">
                                  €{month.monthly_revenue.toLocaleString()}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="mt-4 text-xs text-slate-400">
                      <div className="flex items-start gap-2">
                        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <div>
                          <strong className="text-slate-400">{selectedStrategy.charAt(0).toUpperCase() + selectedStrategy.slice(1)} Strategy:</strong>
                          {selectedStrategy === 'conservative' && ' 90% acceptance rate with lower bid prices. Safest returns with minimal risk.'}
                          {selectedStrategy === 'balanced' && ' 80% acceptance rate with moderate bid prices. Optimal risk/reward balance.'}
                          {selectedStrategy === 'aggressive' && ' 60% acceptance rate with higher bid prices. Higher potential returns but lower acceptance.'}
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </>
          )}
        </div>

        {/* Safe Bid Calculator Section */}
        <div className="space-y-8 mt-12">
          <div className="border-t border-slate-700 pt-8">
            <h2 className="text-3xl font-bold text-white mb-6 flex items-center gap-3">
              <Target className="w-8 h-8 text-emerald-400" />
              Safe Bid Calculator
            </h2>
            <p className="text-slate-300 mb-8 leading-relaxed">
              Calculate optimal bid prices that maximize battery utilization while maintaining high acceptance rates.
              For batteries with capacity constraints (900 MWh/month), <strong className="text-emerald-400">utilization rate matters more than price per MWh</strong>.
            </p>

            {/* Acceptance Rate Slider */}
            <div className="bg-slate-800/50 backdrop-blur-sm rounded-xl border border-slate-700/50 p-6 mb-6">
              <div className="flex items-center justify-between mb-4">
                <label htmlFor="fr-safe-bid-acceptance-slider" className="text-sm font-medium text-slate-300">
                  Target Acceptance Rate
                </label>
                <span className="text-2xl font-bold text-emerald-400">
                  {Math.round(safeBidAcceptance * 100)}%
                </span>
              </div>

              <input
                id="fr-safe-bid-acceptance-slider"
                type="range"
                min="0.80"
                max="0.95"
                step="0.05"
                value={safeBidAcceptance}
                onChange={(e) => setSafeBidAcceptance(parseFloat(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                aria-valuetext={`${Math.round(safeBidAcceptance * 100)} percent safe bid target acceptance rate`}
              />

              <div className="flex justify-between mt-2 text-xs text-slate-400">
                <span>80% (Balanced)</span>
                <span>85% (Moderate)</span>
                <span>90% (Conservative)</span>
                <span>95% (Ultra-Safe)</span>
              </div>

              <div className="mt-4 p-3 bg-slate-900/50 rounded-lg border border-slate-700/50">
                <p className="text-xs text-slate-400">
                  {safeBidAcceptance >= 0.95 && '🛡️ Ultra-safe: Almost guaranteed acceptance, lowest risk, consistent returns.'}
                  {safeBidAcceptance >= 0.90 && safeBidAcceptance < 0.95 && '🎯 Conservative: Very high acceptance probability, safe and predictable.'}
                  {safeBidAcceptance >= 0.85 && safeBidAcceptance < 0.90 && '⚖️ Moderate-safe: Good balance between safety and returns.'}
                  {safeBidAcceptance < 0.85 && '📊 Balanced: Standard acceptance rate, optimized for typical market conditions.'}
                </p>
              </div>
            </div>

            {/* Safe Bid Results */}
            {loadingSafeBids ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-400"></div>
              </div>
            ) : safeBidsError ? (
              <div className="bg-red-500/10 border border-red-500/50 rounded-xl p-6">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <h3 className="text-red-400 font-semibold mb-1">Error Loading Safe Bids</h3>
                    <p className="text-red-300 text-sm">{safeBidsError}</p>
                  </div>
                </div>
              </div>
            ) : safeBidsData ? (
              <>
                {/* Recommended Bid Prices */}
                <div className="grid md:grid-cols-2 gap-6 mb-8">
                  {/* aFRR+ Bids */}
                  <div className="bg-gradient-to-br from-emerald-500/10 to-teal-500/10 rounded-xl border border-emerald-500/30 p-6">
                    <div className="flex items-center gap-3 mb-4">
                      <TrendingUp className="w-6 h-6 text-emerald-400" />
                      <h3 className="text-xl font-bold text-white">aFRR+ Safe Bids</h3>
                    </div>

                    <div className="space-y-4">
                      <div>
                        <div className="text-sm text-slate-400 mb-1">Capacity Bid</div>
                        <div className="text-3xl font-bold text-emerald-400">
                          €{safeBidsData.safe_bids.afrr_up.capacity_bid.toFixed(2)}
                          <span className="text-lg text-slate-400 ml-2">/ MW / hour</span>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm text-slate-400 mb-1">Activation Bid</div>
                        <div className="text-3xl font-bold text-emerald-400">
                          €{safeBidsData.safe_bids.afrr_up.activation_bid.toFixed(2)}
                          <span className="text-lg text-slate-400 ml-2">/ MWh</span>
                        </div>
                      </div>

                      <div className="pt-3 border-t border-emerald-500/20">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-400">vs Market Average:</span>
                          <span className={`font-semibold ${safeBidsData.safe_bids.afrr_up.vs_market_avg < 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
                            {safeBidsData.safe_bids.afrr_up.vs_market_avg > 0 ? '+' : ''}{safeBidsData.safe_bids.afrr_up.vs_market_avg}%
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm mt-2">
                          <span className="text-slate-400">Percentile:</span>
                          <span className="font-semibold text-emerald-400">{safeBidsData.safe_bids.afrr_up.percentile}th</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* aFRR- Bids */}
                  <div className="bg-gradient-to-br from-blue-500/10 to-cyan-500/10 rounded-xl border border-blue-500/30 p-6">
                    <div className="flex items-center gap-3 mb-4">
                      <TrendingDown className="w-6 h-6 text-blue-400" />
                      <h3 className="text-xl font-bold text-white">aFRR- Safe Bids</h3>
                    </div>

                    <div className="space-y-4">
                      <div>
                        <div className="text-sm text-slate-400 mb-1">Capacity Bid</div>
                        <div className="text-3xl font-bold text-blue-400">
                          €{safeBidsData.safe_bids.afrr_down.capacity_bid.toFixed(2)}
                          <span className="text-lg text-slate-400 ml-2">/ MW / hour</span>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm text-slate-400 mb-1">Activation Bid</div>
                        <div className="text-3xl font-bold text-blue-400">
                          €{Math.abs(safeBidsData.safe_bids.afrr_down.activation_bid).toFixed(2)}
                          <span className="text-lg text-slate-400 ml-2">/ MWh</span>
                        </div>
                      </div>

                      <div className="pt-3 border-t border-blue-500/20">
                        <div className="text-xs text-slate-400">
                          Negative pricing reflects charging cost compensation
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Expected Revenue */}
                <div className="bg-slate-800/50 backdrop-blur-sm rounded-xl border border-slate-700/50 p-6 mb-8">
                  <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                    <Euro className="w-6 h-6 text-emerald-400" />
                    Expected Revenue with Safe Bidding
                  </h3>

                  <div className="grid md:grid-cols-3 gap-6">
                    <div>
                      <div className="text-sm text-slate-400 mb-1">Monthly Revenue</div>
                      <div className="text-2xl font-bold text-white">
                        €{(safeBidsData.expected_revenue.monthly / 1000).toFixed(1)}K
                      </div>
                    </div>

                    <div>
                      <div className="text-sm text-slate-400 mb-1">Annual Revenue</div>
                      <div className="text-3xl font-bold text-emerald-400">
                        €{(safeBidsData.expected_revenue.annual / 1000000).toFixed(2)}M
                      </div>
                    </div>

                    <div>
                      <div className="text-sm text-slate-400 mb-1">Utilization Rate</div>
                      <div className="text-2xl font-bold text-white">
                        {safeBidsData.comparison.safe_strategy.utilization}
                      </div>
                    </div>
                  </div>

                  <div className="mt-6 pt-6 border-t border-slate-700">
                    <div className="grid md:grid-cols-2 gap-4">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-400">Capacity Revenue:</span>
                        <span className="font-semibold text-white">
                          €{(safeBidsData.expected_revenue.capacity_component / 1000000).toFixed(2)}M
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-400">Activation Revenue:</span>
                        <span className="font-semibold text-white">
                          €{(safeBidsData.expected_revenue.activation_component / 1000000).toFixed(2)}M
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Strategy Comparison */}
                <div className="bg-slate-800/50 backdrop-blur-sm rounded-xl border border-slate-700/50 p-6 mb-8">
                  <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                    <BarChart3 className="w-6 h-6 text-amber-400" />
                    Strategy Comparison
                  </h3>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-700">
                          <th className="text-left py-3 px-4 text-slate-400 font-medium">Strategy</th>
                          <th className="text-right py-3 px-4 text-slate-400 font-medium">Acceptance Rate</th>
                          <th className="text-right py-3 px-4 text-slate-400 font-medium">Annual Revenue</th>
                          <th className="text-right py-3 px-4 text-slate-400 font-medium">Utilization</th>
                          <th className="text-right py-3 px-4 text-slate-400 font-medium">Risk Level</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b border-slate-700/50 bg-emerald-500/5">
                          <td className="py-4 px-4">
                            <div className="flex items-center gap-2">
                              <div className="w-2 h-2 rounded-full bg-emerald-400"></div>
                              <span className="font-semibold text-white">Safe</span>
                            </div>
                          </td>
                          <td className="text-right py-4 px-4 text-white font-semibold">
                            {Math.round(safeBidsData.comparison.safe_strategy.acceptance_rate * 100)}%
                          </td>
                          <td className="text-right py-4 px-4 text-emerald-400 font-bold">
                            €{(safeBidsData.comparison.safe_strategy.annual_revenue / 1000000).toFixed(2)}M
                          </td>
                          <td className="text-right py-4 px-4 text-white">
                            {safeBidsData.comparison.safe_strategy.utilization}
                          </td>
                          <td className="text-right py-4 px-4">
                            <span className="px-2 py-1 rounded-full text-xs bg-emerald-500/20 text-emerald-400">
                              Low
                            </span>
                          </td>
                        </tr>

                        <tr className="border-b border-slate-700/50">
                          <td className="py-4 px-4">
                            <div className="flex items-center gap-2">
                              <div className="w-2 h-2 rounded-full bg-amber-400"></div>
                              <span className="font-semibold text-white">Aggressive</span>
                            </div>
                          </td>
                          <td className="text-right py-4 px-4 text-white font-semibold">
                            {Math.round(safeBidsData.comparison.aggressive_strategy.acceptance_rate * 100)}%
                          </td>
                          <td className="text-right py-4 px-4 text-amber-400 font-bold">
                            €{(safeBidsData.comparison.aggressive_strategy.annual_revenue / 1000000).toFixed(2)}M
                          </td>
                          <td className="text-right py-4 px-4 text-white">
                            {safeBidsData.comparison.aggressive_strategy.utilization}
                          </td>
                          <td className="text-right py-4 px-4">
                            <span className="px-2 py-1 rounded-full text-xs bg-amber-500/20 text-amber-400">
                              High
                            </span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* Advantage Display */}
                  <div className={`mt-6 p-4 rounded-lg border ${
                    safeBidsData.comparison.advantage.advantage_percentage > 0
                      ? 'bg-emerald-500/10 border-emerald-500/30'
                      : 'bg-amber-500/10 border-amber-500/30'
                  }`}>
                    <div className="flex items-center gap-3">
                      <Info className={`w-5 h-5 flex-shrink-0 ${
                        safeBidsData.comparison.advantage.advantage_percentage > 0
                          ? 'text-emerald-400'
                          : 'text-amber-400'
                      }`} />
                      <div>
                        <p className={`text-sm font-semibold ${
                          safeBidsData.comparison.advantage.advantage_percentage > 0
                            ? 'text-emerald-400'
                            : 'text-amber-400'
                        }`}>
                          {safeBidsData.comparison.advantage.advantage_percentage > 0
                            ? `Safe strategy generates €${Math.abs(safeBidsData.comparison.advantage.additional_revenue_eur / 1000).toFixed(0)}K more annually (+${safeBidsData.comparison.advantage.advantage_percentage.toFixed(1)}%)`
                            : `Aggressive strategy generates €${Math.abs(safeBidsData.comparison.advantage.additional_revenue_eur / 1000).toFixed(0)}K more annually (+${Math.abs(safeBidsData.comparison.advantage.advantage_percentage).toFixed(1)}%)`
                          }
                        </p>
                        <p className="text-xs text-slate-400 mt-1">
                          {safeBidsData.comparison.advantage.advantage_percentage > 0
                            ? 'Higher utilization rate compensates for lower prices. Recommended for batteries with capacity constraints.'
                            : 'Higher capacity payments outweigh lower utilization. Aggressive bidding may be optimal if acceptance rate stays above 60%.'
                          }
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Market Context */}
                <div className="bg-slate-800/50 backdrop-blur-sm rounded-xl border border-slate-700/50 p-6">
                  <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                    <Info className="w-6 h-6 text-blue-400" />
                    Market Context
                  </h3>

                  <div className="grid md:grid-cols-3 gap-6 mb-6">
                    <div className="p-4 bg-slate-900/50 rounded-lg border border-slate-700/50">
                      <div className="text-sm text-slate-400 mb-1">Market Average Price</div>
                      <div className="text-2xl font-bold text-white">
                        €{safeBidsData.market_context.avg_activation_price.toFixed(2)}
                      </div>
                      <div className="text-xs text-slate-400 mt-1">EUR/MWh</div>
                    </div>

                    <div className="p-4 bg-slate-900/50 rounded-lg border border-slate-700/50">
                      <div className="text-sm text-slate-400 mb-1">Market Median Price</div>
                      <div className="text-2xl font-bold text-white">
                        €{safeBidsData.market_context.median_activation_price.toFixed(2)}
                      </div>
                      <div className="text-xs text-slate-400 mt-1">EUR/MWh</div>
                    </div>

                    <div className="p-4 bg-emerald-500/10 rounded-lg border border-emerald-500/30">
                      <div className="text-sm text-slate-400 mb-1">Your Safe Bid</div>
                      <div className="text-2xl font-bold text-emerald-400">
                        €{safeBidsData.market_context.your_safe_bid.toFixed(2)}
                      </div>
                      <div className="text-xs text-emerald-500 mt-1">
                        {safeBidsData.market_context.your_safe_bid < safeBidsData.market_context.avg_activation_price
                          ? `${Math.abs((safeBidsData.market_context.your_safe_bid - safeBidsData.market_context.avg_activation_price) / safeBidsData.market_context.avg_activation_price * 100).toFixed(0)}% below average`
                          : 'Above average'
                        }
                      </div>
                    </div>
                  </div>

                  <div className="p-4 bg-blue-500/10 rounded-lg border border-blue-500/30">
                    <p className="text-sm text-blue-300">
                      <strong className="text-blue-400">📊 Interpretation:</strong> {safeBidsData.market_context.interpretation}
                    </p>
                  </div>

                  <div className="mt-6 p-4 bg-slate-900/50 rounded-lg border border-slate-700/50">
                    <h4 className="text-sm font-semibold text-white mb-3">💡 Strategic Insights</h4>
                    <ul className="space-y-2 text-sm text-slate-400">
                      <li className="flex items-start gap-2">
                        <span className="text-emerald-400 mt-0.5">•</span>
                        <span>
                          For a 15MW/30MWh battery with <strong className="text-white">900 MWh/month throughput limit</strong>,
                          maximizing utilization is critical to revenue optimization.
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="text-emerald-400 mt-0.5">•</span>
                        <span>
                          Bidding at the <strong className="text-white">{safeBidsData.safe_bids.afrr_up.percentile}th percentile</strong> ensures
                          your bids are accepted <strong className="text-emerald-400">{Math.round(safeBidAcceptance * 100)}% of the time</strong>,
                          keeping your battery fully utilized.
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="text-emerald-400 mt-0.5">•</span>
                        <span>
                          Romanian FR market uses <strong className="text-white">merit-order dispatch</strong>:
                          cheapest bids activated first. Safe bidding = competitive positioning.
                        </span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="text-amber-400 mt-0.5">•</span>
                        <span>
                          <strong className="text-amber-400">Trade-off:</strong> Lower prices per MWh vs higher activation frequency.
                          {safeBidsData.comparison.advantage.advantage_percentage > 0
                            ? ' In this scenario, higher frequency wins.'
                            : ' In this scenario, higher prices win due to capacity payment structure.'
                          }
                        </span>
                      </li>
                    </ul>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
      </div>

      {/* Phase E — Multi-product (aFRR / mFRR / FCR) revenue split */}
      <div className="mx-auto max-w-7xl px-4 pb-12 pt-2">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Multi-product revenue split (Phase E)
            </h2>
            <p className="text-xs text-slate-400">
              Capacity (€/MW/h paid 24/7) vs activation (€/MWh paid when called).
              aFRR + mFRR settle pay-as-bid since ANRE Order 60/2024;
              FCR remains marginal-priced. Min-bid raises from 1 to 5 MW under
              MARI (2026-04-01).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(['aFRR', 'mFRR', 'FCR'] as const).map((p) => {
              const active = mpSelected.includes(p)
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() =>
                    setMpSelected((prev) =>
                      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
                    )
                  }
                  className={`rounded px-3 py-1 text-xs font-mono uppercase transition ${
                    active
                      ? 'bg-emerald-600 text-white'
                      : 'border border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  {p}
                </button>
              )
            })}
            <button
              type="button"
              disabled={mpLoading || mpSelected.length === 0}
              onClick={async () => {
                setMpLoading(true)
                setMpError(null)
                try {
                  const totalPower =
                    (params.afrr_up.power_mw || 0) + (params.mfrr_up.power_mw || 0)
                  const power_mw = totalPower > 0 ? totalPower : 10
                  const res = await frApi.multiProduct({
                    products: mpSelected,
                    power_mw,
                    capacity_mwh: params.capacity_mwh,
                    round_trip_efficiency: params.round_trip_efficiency,
                    availability_pct: 97.5,
                    energy_cost_eur_mwh: params.energy_cost_eur_mwh,
                    activation_share: params.activation_rate,
                    start_date: params.start_date,
                    end_date: params.end_date,
                  })
                  setMpData(res.data)
                } catch (err: any) {
                  setMpError(
                    err?.response?.data?.detail || err?.message || 'Multi-product failed'
                  )
                } finally {
                  setMpLoading(false)
                }
              }}
              className="rounded bg-blue-600 px-3 py-1 text-xs font-mono uppercase text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {mpLoading ? 'Running…' : 'Run multi-product'}
            </button>
          </div>
        </div>
        {mpError && (
          <div className="mb-3 rounded border border-rose-700 bg-rose-900/40 p-3 text-xs text-rose-200">
            {mpError}
          </div>
        )}
        {mpData?.min_bid_violations && mpData.min_bid_violations.length > 0 && (
          <div className="mb-3 rounded border border-amber-700 bg-amber-900/40 p-3 text-xs text-amber-200">
            <strong>Min-bid violations:</strong>
            <ul className="mt-1 list-inside list-disc">
              {mpData.min_bid_violations.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ul>
          </div>
        )}
        {mpData && <FRProductBreakdown data={mpData.products} />}
      </div>
    </div>
  )
}
