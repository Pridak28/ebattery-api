'use client'

import { useState, useMemo, useEffect } from 'react'
import { TrendingUp, Battery, DollarSign, Calendar, BarChart2, Info, Target, ArrowUpRight, ArrowDownRight, Zap, Clock, TrendingDown, Layers, ChevronDown, ChevronRight, Activity, Sun, Moon, Sunrise, Sunset, ExternalLink, Table, Search, ChevronLeft } from 'lucide-react'
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
  ComposedChart,
  Line,
  Legend,
  ReferenceLine,
} from 'recharts'
import { formatCurrency, formatCompact, formatNumber, formatPercentage } from '@/lib/utils'
import { API_BASE_URL } from '@/lib/api'

const CHART_COLORS = {
  profit: '#10b981',        // Green
  revenue: '#2563eb',       // eBattery blue
  spread: '#00ffd1',        // eBattery cyan
  cycles: '#00d4aa',        // Lighter cyan
  positive: '#10b981',      // Green
  negative: '#ef4444',      // Red
}

export default function PZUAnalysis() {
  const [params, setParams] = useState({
    power_mw: 15,
    capacity_mwh: 30,
    round_trip_efficiency: 0.90,
    investment_eur: 3500000,
    start_date: '2024-01-01',
    end_date: '2025-12-03',
  })

  const [simulation, setSimulation] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [typicalDay, setTypicalDay] = useState<any[]>([])
  const [chargeHours, setChargeHours] = useState<number[]>([])
  const [dischargeHours, setDischargeHours] = useState<number[]>([])
  const [monthlyOptimal, setMonthlyOptimal] = useState<any[]>([])
  const [monthlyOptimalTotal, setMonthlyOptimalTotal] = useState<number>(0)

  // State for expandable daily breakdown
  const [expandedMonth, setExpandedMonth] = useState<string | null>(null)
  const [dailyData, setDailyData] = useState<any>(null)
  const [loadingDaily, setLoadingDaily] = useState(false)

  // State for OPCOM Price Explorer
  const [availableDates, setAvailableDates] = useState<any[]>([])
  const [selectedDate, setSelectedDate] = useState<string>('')
  const [hourlyPrices, setHourlyPrices] = useState<any>(null)
  const [loadingHourly, setLoadingHourly] = useState(false)
  const [dateFilter, setDateFilter] = useState('')

  // Fetch available dates on mount
  useEffect(() => {
    const fetchAvailableDates = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/pzu/available-dates`)
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
        console.error('Failed to fetch available dates:', err)
      }
    }
    fetchAvailableDates()
  }, [])

  // Fetch hourly prices when date changes
  useEffect(() => {
    if (!selectedDate) return
    const fetchHourlyPrices = async () => {
      setLoadingHourly(true)
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/pzu/hourly-prices/${selectedDate}?power_mw=${params.power_mw}&capacity_mwh=${params.capacity_mwh}&efficiency=${params.round_trip_efficiency}`
        )
        if (response.ok) {
          const data = await response.json()
          setHourlyPrices(data)
        }
      } catch (err) {
        console.error('Failed to fetch hourly prices:', err)
      } finally {
        setLoadingHourly(false)
      }
    }
    fetchHourlyPrices()
  }, [selectedDate, params.power_mw, params.capacity_mwh, params.round_trip_efficiency])

  // Filter dates based on search
  const filteredDates = useMemo(() => {
    if (!dateFilter) return availableDates.slice(-90) // Show last 90 days by default
    return availableDates.filter(d => d.date.includes(dateFilter))
  }, [availableDates, dateFilter])

  const runSimulation = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/pzu/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
      const data = await response.json()
      setSimulation(data)

      try {
        const typicalDayResponse = await fetch(`${API_BASE_URL}/api/v1/pzu/typical-day`)
        if (typicalDayResponse.ok) {
          const typicalDayData = await typicalDayResponse.json()
          setTypicalDay(typicalDayData.hourly_pattern)
          setChargeHours(typicalDayData.charge_hours)
          setDischargeHours(typicalDayData.discharge_hours)
        }
      } catch (err) {
        console.error('Failed to fetch typical day:', err)
      }

      try {
        const monthlyOptimalResponse = await fetch(`${API_BASE_URL}/api/v1/pzu/monthly-optimal`)
        if (monthlyOptimalResponse.ok) {
          const monthlyOptimalData = await monthlyOptimalResponse.json()
          setMonthlyOptimal(monthlyOptimalData.monthly_schedules)
          setMonthlyOptimalTotal(monthlyOptimalData.total_profit_eur)
        }
      } catch (err) {
        console.error('Failed to fetch monthly optimal:', err)
      }
    } catch (err: any) {
      console.error('Simulation error:', err)
      setError(err.message || 'Failed to run simulation')
    } finally {
      setIsLoading(false)
    }
  }


  // Fetch daily breakdown for a month
  const fetchDailyBreakdown = async (month: string) => {
    if (expandedMonth === month) {
      setExpandedMonth(null)
      setDailyData(null)
      return
    }

    setLoadingDaily(true)
    setExpandedMonth(month)

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/pzu/daily-breakdown/${month}?power_mw=${params.power_mw}&capacity_mwh=${params.capacity_mwh}&efficiency=${params.round_trip_efficiency}`
      )
      if (response.ok) {
        const data = await response.json()
        setDailyData(data)
      }
    } catch (err) {
      console.error("Failed to fetch daily breakdown:", err)
    } finally {
      setLoadingDaily(false)
    }
  }
  const derivedMetrics = useMemo(() => {
    if (!simulation?.monthly_results) return null

    const monthCount = simulation.monthly_results.length
    const annualizedProfit = simulation.total_profit_eur * (12 / monthCount)
    const avgSpread = simulation.monthly_results.reduce((acc: number, m: any) => acc + m.avg_spread_eur_mwh, 0) / monthCount
    const totalCycles = simulation.monthly_results.reduce((acc: number, m: any) => acc + m.total_cycles, 0)
    const avgDailyProfit = simulation.monthly_results.reduce((acc: number, m: any) => acc + m.avg_daily_profit_eur, 0) / monthCount
    const profitPerMW = params.power_mw > 0 ? annualizedProfit / params.power_mw : 0

    return {
      annualizedProfit,
      avgSpread,
      totalCycles,
      avgDailyProfit,
      profitPerMW,
      monthCount,
    }
  }, [simulation, params])

  // Scenario calculations based on different profit spreads
  // All scenarios are scaled relative to actual simulation results for consistency
  const scenarioMetrics = useMemo(() => {
    // Get actual metrics from simulation
    const actualSpread = derivedMetrics?.avgSpread || 100 // Default to 100 if no data
    const actualAnnualProfit = derivedMetrics?.annualizedProfit || 0
    const actualDailyProfit = derivedMetrics?.avgDailyProfit || 0
    const actualProfitPerMW = derivedMetrics?.profitPerMW || 0

    // Scenario spreads
    const scenarios: Array<{
      name: string
      profitSpread: number
      color: string
      isActual?: boolean
      dailyProfit: number
      annualProfit: number
      profitPerMW: number
      paybackYears: number
    }> = []

    // For theoretical scenarios, scale proportionally from actual results
    // If actual spread gives actualAnnualProfit, then scenario spread gives:
    // scenarioProfit = actualAnnualProfit * (scenarioSpread / actualSpread)
    const spreadScenarios = [
      { name: 'Optimistic', profitSpread: 131, color: 'green' },
      { name: 'Base Case', profitSpread: 100, color: 'blue' },
      { name: 'Conservative', profitSpread: 80, color: 'amber' },
    ]

    spreadScenarios.forEach(scenario => {
      // Scale annual profit based on spread ratio
      const spreadRatio = actualSpread > 0 ? scenario.profitSpread / actualSpread : 1
      const annualProfit = actualAnnualProfit * spreadRatio
      const dailyProfit = actualDailyProfit * spreadRatio
      const profitPerMW = annualProfit / params.power_mw

      scenarios.push({
        ...scenario,
        dailyProfit,
        annualProfit,
        profitPerMW,
        paybackYears: annualProfit > 0 ? params.investment_eur / annualProfit : 0,
      })
    })

    // Add actual scenario using REAL simulation data
    scenarios.push({
      name: 'Actual (Analysis)',
      profitSpread: Math.round(actualSpread * 10) / 10,
      color: 'cyan',
      isActual: true,
      dailyProfit: actualDailyProfit,
      annualProfit: actualAnnualProfit,
      profitPerMW: actualProfitPerMW,
      paybackYears: actualAnnualProfit > 0 ? params.investment_eur / actualAnnualProfit : 0,
    })

    return scenarios
  }, [params, derivedMetrics])

  const getCumulativeData = () => {
    if (!simulation?.monthly_results) return []
    let cumulative = 0
    return simulation.monthly_results.map((m: any) => {
      cumulative += m.net_profit_eur
      return {
        month: m.month,
        monthly: m.net_profit_eur,
        cumulative,
      }
    })
  }

  const getMonthlyChartData = () => {
    if (!simulation?.monthly_results) return []
    return simulation.monthly_results.map((m: any) => ({
      month: m.month,
      profit: m.net_profit_eur,
      spread: m.avg_spread_eur_mwh,
      cycles: m.total_cycles,
    }))
  }

  // Get buy/sell hours for a specific month from monthlyOptimal
  const getMonthHours = (month: string) => {
    const monthData = monthlyOptimal.find(m => m.month === month)
    if (monthData) {
      return {
        buyHours: monthData.charge_hours.sort((a: number, b: number) => a - b).join(', '),
        sellHours: monthData.discharge_hours.sort((a: number, b: number) => a - b).join(', '),
      }
    }
    return { buyHours: '-', sellHours: '-' }
  }

  return (
    <div className="space-y-4 sm:space-y-6 max-w-[1600px] mx-auto">
      {/* Bloomberg-Style Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="p-1.5 sm:p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <BarChart2 className="w-5 h-5 sm:w-6 sm:h-6 text-slate-900" />
            </div>
            <div>
              <h1 className="text-lg sm:text-xl md:text-2xl font-bold text-white">PZU Day-Ahead Arbitrage</h1>
              <p className="text-xs sm:text-sm text-slate-400">
                OPCOM DAM • Energy Arbitrage
              </p>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-slate-800/50 border border-slate-700">
            <span className="w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] sm:text-xs text-slate-400">OPCOM</span>
          </div>
          <div className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-[#00ffd1]/10 border border-[#00ffd1]/30">
            <span className="text-xs sm:text-sm text-[#00ffd1] font-mono">RO-DAM</span>
          </div>
        </div>
      </div>

      {/* Bloomberg-Style Market Overview Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        {/* Typical Day Profile Card */}
        <div className="lg:col-span-2 bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-lg sm:rounded-xl p-3 sm:p-5">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3 sm:mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              <h2 className="text-sm sm:text-lg font-semibold text-white">Typical Day Price Profile</h2>
            </div>
            <span className="sm:ml-auto text-[10px] sm:text-xs text-slate-400">OPCOM Historical Average</span>
          </div>

          {/* Typical Day Chart */}
          <div className="h-40 sm:h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={typicalDay.length > 0 ? typicalDay : Array.from({length: 24}, (_, i) => ({
                hour: i,
                price: 50 + Math.sin((i - 6) * Math.PI / 12) * 40 + (i >= 17 && i <= 21 ? 30 : 0)
              }))}>
                <defs>
                  <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00ffd1" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#00ffd1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="hour"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  tickFormatter={(v) => `${v}:00`}
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
                  formatter={(value: number) => [`${value.toFixed(1)} €/MWh`, 'Avg Price']}
                  labelFormatter={(label) => `Hour ${label}:00`}
                />
                {/* Highlight charge/discharge zones */}
                <ReferenceLine x={4} stroke="#22c55e" strokeDasharray="3 3" />
                <ReferenceLine x={6} stroke="#22c55e" strokeDasharray="3 3" />
                <ReferenceLine x={18} stroke="#00ffd1" strokeDasharray="3 3" />
                <ReferenceLine x={21} stroke="#00ffd1" strokeDasharray="3 3" />
                <Area
                  type="monotone"
                  dataKey="price"
                  stroke="#00ffd1"
                  fill="url(#priceGradient)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Time Period Indicators */}
          <div className="grid grid-cols-4 gap-2 mt-4">
            <div className="bg-slate-800/50 rounded-lg p-2 text-center">
              <Moon className="w-4 h-4 mx-auto text-blue-400 mb-1" />
              <p className="text-[10px] text-slate-400 uppercase">Night</p>
              <p className="text-xs text-green-400 font-medium">00:00-06:00</p>
              <p className="text-[10px] text-slate-400">CHARGE</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 text-center">
              <Sunrise className="w-4 h-4 mx-auto text-amber-400 mb-1" />
              <p className="text-[10px] text-slate-400 uppercase">Morning</p>
              <p className="text-xs text-slate-300 font-medium">06:00-12:00</p>
              <p className="text-[10px] text-slate-400">HOLD</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 text-center">
              <Sun className="w-4 h-4 mx-auto text-yellow-400 mb-1" />
              <p className="text-[10px] text-slate-400 uppercase">Afternoon</p>
              <p className="text-xs text-slate-300 font-medium">12:00-17:00</p>
              <p className="text-[10px] text-slate-400">HOLD</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2 text-center">
              <Sunset className="w-4 h-4 mx-auto text-orange-400 mb-1" />
              <p className="text-[10px] text-slate-400 uppercase">Evening Peak</p>
              <p className="text-xs text-[#00ffd1] font-medium">17:00-21:00</p>
              <p className="text-[10px] text-[#00ffd1]">DISCHARGE</p>
            </div>
          </div>
        </div>

        {/* Educational Card - Right */}
        <div className="bg-gradient-to-br from-green-900/20 to-slate-900/50 border border-green-500/30 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Info className="w-5 h-5 text-green-400" />
            <h3 className="text-white font-semibold">How Arbitrage Works</h3>
          </div>

          <div className="space-y-4 text-sm">
            <div className="border-l-2 border-green-400 pl-3">
              <p className="text-green-400 font-medium flex items-center gap-1">
                <ArrowDownRight className="w-4 h-4" /> Buy Low (Charge)
              </p>
              <p className="text-slate-400 text-xs mt-1">
                Charge during night hours (00:00-06:00) when solar/wind is producing and demand is low
              </p>
            </div>

            <div className="border-l-2 border-[#00ffd1] pl-3">
              <p className="text-[#00ffd1] font-medium flex items-center gap-1">
                <ArrowUpRight className="w-4 h-4" /> Sell High (Discharge)
              </p>
              <p className="text-slate-400 text-xs mt-1">
                Discharge during evening peak (17:00-21:00) when demand spikes and prices rise
              </p>
            </div>

            <div className="bg-[#00ffd1]/10 border border-[#00ffd1]/30 rounded-lg p-3 mt-4">
              <p className="text-[#00ffd1] text-xs font-medium">Profit Formula</p>
              <p className="text-slate-300 text-[11px] mt-1 font-mono">
                (Peak Price × Discharge × η) - (Off-Peak × Charge)
              </p>
              <p className="text-slate-400 text-[10px] mt-1">
                η = Round-trip efficiency (typically 88-92%)
              </p>
            </div>

            <div className="pt-2 border-t border-slate-800">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Typical Spread:</span>
                <span className="text-[#00ffd1] font-mono">50-150 €/MWh</span>
              </div>
              <div className="flex justify-between text-xs mt-1">
                <span className="text-slate-400">Cycles/Day:</span>
                <span className="text-[#00ffd1] font-mono">1-2 full cycles</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
        <div className="px-3 sm:px-5 py-3 sm:py-4 border-b border-slate-700 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-2">
            <Battery className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
            <h2 className="text-white font-semibold text-sm sm:text-base">Battery Configuration</h2>
          </div>
          <button
            onClick={runSimulation}
            disabled={isLoading}
            className="btn-primary flex items-center justify-center gap-2 w-full sm:w-auto min-h-[44px] sm:min-h-[36px]"
          >
            {isLoading ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Running...
              </>
            ) : (
              <>
                <Zap className="w-4 h-4" />
                Run Simulation
              </>
            )}
          </button>
        </div>
        <div className="p-3 sm:p-5">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-6">
            <div>
              <label htmlFor="pzu-power-mw" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Power (MW)</label>
              <input
                id="pzu-power-mw"
                type="number"
                value={params.power_mw}
                onChange={(e) => setParams({ ...params, power_mw: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Charge/discharge power</p>
            </div>
            <div>
              <label htmlFor="pzu-capacity-mwh" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Capacity (MWh)</label>
              <input
                id="pzu-capacity-mwh"
                type="number"
                value={params.capacity_mwh}
                onChange={(e) => setParams({ ...params, capacity_mwh: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Energy capacity</p>
            </div>
            <div>
              <label htmlFor="pzu-round-trip-efficiency" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Efficiency (%)</label>
              <input
                id="pzu-round-trip-efficiency"
                type="number"
                value={(params.round_trip_efficiency * 100).toFixed(0)}
                onChange={(e) => setParams({ ...params, round_trip_efficiency: (parseFloat(e.target.value) || 0) / 100 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">Round-trip (85-95%)</p>
            </div>
            <div>
              <label htmlFor="pzu-investment-eur" className="block text-slate-400 text-xs sm:text-sm mb-1.5 sm:mb-2">Investment (€)</label>
              <input
                id="pzu-investment-eur"
                type="number"
                value={params.investment_eur}
                onChange={(e) => setParams({ ...params, investment_eur: parseFloat(e.target.value) || 0 })}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]"
                step="100000"
              />
              <p className="text-slate-400 text-[10px] sm:text-xs mt-1">CAPEX for payback</p>
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

      {/* Empty State */}
      {!simulation && !isLoading && !error && (
        <div className="bg-slate-900/30 border border-slate-800 rounded-lg p-12 text-center">
          <Battery className="h-10 w-10 text-slate-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-400">Ready to Simulate</h3>
          <p className="text-slate-400 mt-1 text-sm">
            Configure battery parameters and click Run Simulation to analyze day-ahead arbitrage potential
          </p>
        </div>
      )}

      {/* Results */}
      {simulation && derivedMetrics && (
        <>
          {/* Executive Summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-4">
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 sm:p-5">
              <div className="flex items-center justify-between mb-2 sm:mb-3">
                <span className="text-slate-400 text-xs sm:text-sm">Total Profit</span>
                <DollarSign className="w-4 h-4 sm:w-5 sm:h-5 text-green-400" />
              </div>
              <p className="text-lg sm:text-2xl font-bold text-white font-mono">
                {formatCompact(simulation.total_profit_eur)}
              </p>
              <p className="text-slate-400 text-[10px] sm:text-xs mt-0.5 sm:mt-1">{derivedMetrics.monthCount} months</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 sm:p-5">
              <div className="flex items-center justify-between mb-2 sm:mb-3">
                <span className="text-slate-400 text-xs sm:text-sm">Annualized</span>
                <Target className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              </div>
              <p className="text-lg sm:text-2xl font-bold text-white font-mono">
                {formatCompact(derivedMetrics.annualizedProfit)}
              </p>
              <p className="text-slate-400 text-[10px] sm:text-xs mt-0.5 sm:mt-1">12-month</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 sm:p-5">
              <div className="flex items-center justify-between mb-2 sm:mb-3">
                <span className="text-slate-400 text-xs sm:text-sm">Avg Spread</span>
                <TrendingUp className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              </div>
              <p className="text-lg sm:text-2xl font-bold text-white font-mono">
                {formatNumber(derivedMetrics.avgSpread, { decimals: 1 })}€
              </p>
              <p className="text-slate-400 text-[10px] sm:text-xs mt-0.5 sm:mt-1">Peak-to-trough</p>
            </div>
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 sm:p-5">
              <div className="flex items-center justify-between mb-2 sm:mb-3">
                <span className="text-slate-400 text-xs sm:text-sm">Profit/MW</span>
                <BarChart2 className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
              </div>
              <p className="text-lg sm:text-2xl font-bold text-white font-mono">
                {formatCompact(derivedMetrics.profitPerMW)}
              </p>
              <p className="text-slate-400 text-[10px] sm:text-xs mt-0.5 sm:mt-1">Annual/MW</p>
            </div>
          </div>

          {/* Key Metrics Panel */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-[#00ffd1]" />
              Key Performance Metrics
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-xs mb-1">Avg Monthly</p>
                <p className="text-xl font-bold text-white font-mono">{formatCompact(simulation.avg_monthly_profit_eur)}</p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-xs mb-1">Avg Daily</p>
                <p className="text-xl font-bold text-white font-mono">{formatCurrency(derivedMetrics.avgDailyProfit, { decimals: 0 })}</p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-xs mb-1">Total Cycles</p>
                <p className="text-xl font-bold text-white font-mono">{formatNumber(derivedMetrics.totalCycles, { decimals: 1 })}</p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-xs mb-1">Profit/Cycle</p>
                <p className="text-xl font-bold text-white font-mono">
                  {formatCurrency(derivedMetrics.totalCycles > 0 ? simulation.total_profit_eur / derivedMetrics.totalCycles : 0, { decimals: 0 })}
                </p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <p className="text-slate-400 text-xs mb-1">Efficiency</p>
                <p className="text-xl font-bold text-white font-mono">{formatPercentage(params.round_trip_efficiency * 100, { decimals: 0 })}</p>
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Cumulative Profit Chart */}
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-[#00ffd1]" />
                Cumulative Profit
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={getCumulativeData()}>
                    <defs>
                      <linearGradient id="profitGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} tickFormatter={(v) => `€${(v / 1000).toFixed(0)}K`} />
                    <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '8px', color: '#fff' }} formatter={(value: number) => [formatCurrency(value), 'Cumulative']} />
                    <Area type="monotone" dataKey="cumulative" stroke="#22c55e" strokeWidth={2} fill="url(#profitGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Monthly Profit Bar Chart */}
            <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
              <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                <BarChart2 className="w-5 h-5 text-[#00ffd1]" />
                Monthly Net Profit
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={simulation.monthly_results}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} tickFormatter={(v) => `€${(v / 1000).toFixed(0)}K`} />
                    <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '8px', color: '#fff' }} formatter={(value: number) => [formatCurrency(value), 'Net Profit']} />
                    <Bar dataKey="net_profit_eur" radius={[4, 4, 0, 0]}>
                      {simulation.monthly_results.map((entry: any, index: number) => (
                        <Cell key={`cell-${index}`} fill={entry.net_profit_eur >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Spread & Cycles Chart */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-[#00ffd1]" />
              Price Spread & Trading Cycles
            </h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={getMonthlyChartData()}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} />
                  <YAxis yAxisId="left" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} tickFormatter={(v) => `€${v}`} label={{ value: '€/MWh', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#475569' }} tickLine={{ stroke: '#475569' }} label={{ value: 'Cycles', angle: 90, position: 'insideRight', fill: '#94a3b8', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '8px', color: '#fff' }} />
                  <Legend />
                  <Bar yAxisId="left" dataKey="spread" name="Avg Spread" fill={CHART_COLORS.spread} radius={[4, 4, 0, 0]} opacity={0.8} />
                  <Line yAxisId="right" type="monotone" dataKey="cycles" name="Cycles" stroke={CHART_COLORS.cycles} strokeWidth={2} dot={{ fill: CHART_COLORS.cycles }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Best Trading Hours Heatmap-style Visualization */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-[#00ffd1]" />
              Optimal Trading Hours by Month
            </h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Charge Hours */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <ArrowDownRight className="w-4 h-4 text-green-400" />
                  <span className="text-sm text-green-400 font-medium">Charge Hours (Buy Low)</span>
                </div>
                <div className="space-y-2">
                  {monthlyOptimal.slice(0, 6).map((month: any) => (
                    <div key={month.month} className="flex items-center gap-3">
                      <span className="text-xs text-slate-400 w-20 font-mono">{month.month}</span>
                      <div className="flex gap-1 flex-wrap">
                        {month.charge_hours.sort((a: number, b: number) => a - b).map((hour: number) => (
                          <span
                            key={hour}
                            className="px-1.5 py-0.5 bg-green-500/20 text-green-400 text-[10px] font-mono rounded"
                          >
                            {hour.toString().padStart(2, '0')}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {/* Discharge Hours */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <ArrowUpRight className="w-4 h-4 text-[#00ffd1]" />
                  <span className="text-sm text-[#00ffd1] font-medium">Discharge Hours (Sell High)</span>
                </div>
                <div className="space-y-2">
                  {monthlyOptimal.slice(0, 6).map((month: any) => (
                    <div key={month.month} className="flex items-center gap-3">
                      <span className="text-xs text-slate-400 w-20 font-mono">{month.month}</span>
                      <div className="flex gap-1 flex-wrap">
                        {month.discharge_hours.sort((a: number, b: number) => a - b).map((hour: number) => (
                          <span
                            key={hour}
                            className="px-1.5 py-0.5 bg-[#00ffd1]/20 text-[#00ffd1] text-[10px] font-mono rounded"
                          >
                            {hour.toString().padStart(2, '0')}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-slate-800">
              <p className="text-[10px] text-slate-400">
                Hours shown are optimal based on historical price patterns. The algorithm selects hours that maximize profit spread while respecting battery capacity constraints.
              </p>
            </div>
          </div>

          {/* Monthly Breakdown Table with Buy/Sell Hours - Expandable */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-700">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Calendar className="w-5 h-5 text-[#00ffd1]" />
                Monthly Breakdown
              </h3>
              <p className="text-slate-400 text-sm mt-1">Click on a month to expand daily breakdown</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-800/50">
                    <th className="text-left px-4 py-3 text-slate-400 font-medium text-sm">Month</th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Days</th>
                    <th className="text-center px-4 py-3 text-slate-400 font-medium text-sm">
                      <span className="flex items-center justify-center gap-1">
                        <ArrowDownRight className="w-3 h-3 text-green-400" />
                        Buy Hours
                      </span>
                    </th>
                    <th className="text-center px-4 py-3 text-slate-400 font-medium text-sm">
                      <span className="flex items-center justify-center gap-1">
                        <ArrowUpRight className="w-3 h-3 text-[#00ffd1]" />
                        Sell Hours
                      </span>
                    </th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Avg Spread</th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Cycles</th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Gross Profit</th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Net Profit</th>
                    <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Daily Avg</th>
                  </tr>
                </thead>
                <tbody>
                  {simulation.monthly_results.map((row: any, idx: number) => {
                    const hours = getMonthHours(row.month)
                    const isExpanded = expandedMonth === row.month
                    return (
                      <>
                        <tr
                          key={row.month}
                          className={`${idx % 2 === 0 ? 'bg-slate-900' : 'bg-slate-800/30'} cursor-pointer hover:bg-slate-700/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00ffd1] focus-visible:ring-inset`}
                          onClick={() => fetchDailyBreakdown(row.month)}
                          tabIndex={0}
                          role="button"
                          aria-label={`${isExpanded ? 'Collapse' : 'Expand'} daily breakdown for ${row.month}`}
                          aria-expanded={isExpanded}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              fetchDailyBreakdown(row.month)
                            }
                          }}
                        >
                          <td className="px-4 py-3 text-white font-medium">
                            <span className="flex items-center gap-2">
                              {isExpanded ? (
                                <ChevronDown className="w-4 h-4 text-[#00ffd1]" />
                              ) : (
                                <ChevronRight className="w-4 h-4 text-slate-400" />
                              )}
                              {row.month}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-300 text-right font-mono">{row.days}</td>
                          <td className="px-4 py-3 text-green-400 text-center font-mono text-xs">{hours.buyHours}</td>
                          <td className="px-4 py-3 text-[#00ffd1] text-center font-mono text-xs">{hours.sellHours}</td>
                          <td className="px-4 py-3 text-[#00ffd1] text-right font-mono">
                            {formatNumber(row.avg_spread_eur_mwh, { decimals: 1 })} €
                          </td>
                          <td className="px-4 py-3 text-[#00ffd1] text-right font-mono">
                            {formatNumber(row.total_cycles, { decimals: 1 })}
                          </td>
                          <td className="px-4 py-3 text-[#00ffd1] text-right font-mono">
                            {formatCurrency(row.gross_profit_eur, { decimals: 0 })}
                          </td>
                          <td className={`px-4 py-3 text-right font-mono font-semibold ${row.net_profit_eur >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {formatCurrency(row.net_profit_eur, { decimals: 0 })}
                          </td>
                          <td className="px-4 py-3 text-slate-300 text-right font-mono">
                            {formatCurrency(row.avg_daily_profit_eur, { decimals: 0 })}
                          </td>
                        </tr>
                        {/* Expanded Daily Rows */}
                        {isExpanded && (
                          <tr key={`${row.month}-expanded`}>
                            <td colSpan={9} className="p-0">
                              <div className="bg-slate-950 border-y border-slate-600">
                                {loadingDaily ? (
                                  <div className="flex items-center justify-center py-8">
                                    <div className="w-6 h-6 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin" />
                                    <span className="ml-3 text-slate-400">Loading daily data...</span>
                                  </div>
                                ) : dailyData?.daily_results ? (
                                  <div className="max-h-[400px] overflow-y-auto">
                                    <table className="w-full">
                                      <thead className="sticky top-0 bg-slate-800">
                                        <tr>
                                          <th className="text-left px-4 py-2 text-slate-400 font-medium text-xs">Date</th>
                                          <th className="text-center px-4 py-2 text-slate-400 font-medium text-xs">Day</th>
                                          <th className="text-center px-4 py-2 text-slate-400 font-medium text-xs">Buy Hours</th>
                                          <th className="text-center px-4 py-2 text-slate-400 font-medium text-xs">Sell Hours</th>
                                          <th className="text-right px-4 py-2 text-slate-400 font-medium text-xs">Buy Price</th>
                                          <th className="text-right px-4 py-2 text-slate-400 font-medium text-xs">Sell Price</th>
                                          <th className="text-right px-4 py-2 text-slate-400 font-medium text-xs">Spread</th>
                                          <th className="text-right px-4 py-2 text-slate-400 font-medium text-xs">Profit</th>
                                          <th className="text-right px-4 py-2 text-slate-400 font-medium text-xs">Min/Max</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {dailyData.daily_results.map((day: any, dayIdx: number) => (
                                          <tr key={day.date} className={dayIdx % 2 === 0 ? 'bg-slate-900/50' : 'bg-slate-800/20'}>
                                            <td className="px-4 py-2 text-slate-300 text-sm font-mono">{day.date}</td>
                                            <td className="px-4 py-2 text-slate-400 text-center text-xs">{day.day_of_week}</td>
                                            <td className="px-4 py-2 text-green-400 text-center font-mono text-xs">
                                              {day.buy_hours.sort((a: number, b: number) => a - b).join(', ')}
                                            </td>
                                            <td className="px-4 py-2 text-[#00ffd1] text-center font-mono text-xs">
                                              {day.sell_hours.sort((a: number, b: number) => a - b).join(', ')}
                                            </td>
                                            <td className="px-4 py-2 text-green-400 text-right font-mono text-xs">
                                              {day.avg_buy_price.toFixed(1)} €
                                            </td>
                                            <td className="px-4 py-2 text-[#00ffd1] text-right font-mono text-xs">
                                              {day.avg_sell_price.toFixed(1)} €
                                            </td>
                                            <td className="px-4 py-2 text-[#00ffd1] text-right font-mono text-xs">
                                              {day.spread.toFixed(1)} €
                                            </td>
                                            <td className={`px-4 py-2 text-right font-mono text-xs font-semibold ${day.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                              {formatCurrency(day.profit, { decimals: 0 })}
                                            </td>
                                            <td className="px-4 py-2 text-slate-400 text-right font-mono text-xs">
                                              {day.min_price.toFixed(0)}/{day.max_price.toFixed(0)}
                                            </td>
                                          </tr>
                                        ))}
                                      </tbody>
                                      <tfoot className="sticky bottom-0 bg-slate-800">
                                        <tr className="border-t border-slate-600">
                                          <td colSpan={7} className="px-4 py-2 text-white font-semibold text-sm">
                                            Monthly Total ({dailyData.total_days} days)
                                          </td>
                                          <td className="px-4 py-2 text-green-400 text-right font-mono text-sm font-semibold">
                                            {formatCurrency(dailyData.total_profit, { decimals: 0 })}
                                          </td>
                                          <td className="px-4 py-2 text-slate-400 text-right font-mono text-xs">
                                            Avg: {formatCurrency(dailyData.avg_daily_profit, { decimals: 0 })}/day
                                          </td>
                                        </tr>
                                      </tfoot>
                                    </table>
                                  </div>
                                ) : (
                                  <div className="py-4 text-center text-slate-400">No daily data available</div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-slate-800 border-t border-slate-700">
                    <td className="px-4 py-3 text-white font-semibold">TOTAL</td>
                    <td className="px-4 py-3 text-slate-300 text-right font-mono font-semibold">
                      {simulation.monthly_results.reduce((acc: number, r: any) => acc + r.days, 0)}
                    </td>
                    <td className="px-4 py-3 text-center text-slate-400">-</td>
                    <td className="px-4 py-3 text-center text-slate-400">-</td>
                    <td className="px-4 py-3 text-[#00ffd1] text-right font-mono font-semibold">
                      {formatNumber(derivedMetrics.avgSpread, { decimals: 1 })} €
                    </td>
                    <td className="px-4 py-3 text-[#00ffd1] text-right font-mono font-semibold">
                      {formatNumber(derivedMetrics.totalCycles, { decimals: 1 })}
                    </td>
                    <td className="px-4 py-3 text-[#00ffd1] text-right font-mono font-semibold">
                      {formatCurrency(simulation.monthly_results.reduce((acc: number, r: any) => acc + r.gross_profit_eur, 0), { decimals: 0 })}
                    </td>
                    <td className="px-4 py-3 text-green-400 text-right font-mono font-semibold">
                      {formatCurrency(simulation.total_profit_eur, { decimals: 0 })}
                    </td>
                    <td className="px-4 py-3 text-slate-300 text-right font-mono font-semibold">
                      {formatCurrency(derivedMetrics.avgDailyProfit, { decimals: 0 })}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
          {/* 3-Year Profit Projection */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-[#00ffd1]" />
              3-Year Profit Projection
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-800/50">
                    <th className="text-left px-5 py-3 text-slate-400 font-medium text-sm">Year</th>
                    <th className="text-right px-5 py-3 text-slate-400 font-medium text-sm">Gross Revenue</th>
                    <th className="text-right px-5 py-3 text-slate-400 font-medium text-sm">Net Profit</th>
                    <th className="text-right px-5 py-3 text-slate-400 font-medium text-sm">Cumulative</th>
                    <th className="text-right px-5 py-3 text-slate-400 font-medium text-sm">Profit/MW</th>
                  </tr>
                </thead>
                <tbody>
                  {[1, 2, 3].map((year) => {
                    const annualProfit = derivedMetrics.annualizedProfit
                    const cumulative = annualProfit * year
                    return (
                      <tr key={year} className={year % 2 === 0 ? 'bg-slate-800/30' : 'bg-slate-900'}>
                        <td className="px-5 py-3 text-white font-medium">Year {year}</td>
                        <td className="px-5 py-3 text-[#00ffd1] text-right font-mono">
                          {formatCurrency(annualProfit * 1.1, { decimals: 0 })}
                        </td>
                        <td className="px-5 py-3 text-green-400 text-right font-mono">
                          {formatCurrency(annualProfit, { decimals: 0 })}
                        </td>
                        <td className="px-5 py-3 text-[#00ffd1] text-right font-mono">
                          {formatCurrency(cumulative, { decimals: 0 })}
                        </td>
                        <td className="px-5 py-3 text-[#00ffd1] text-right font-mono">
                          {formatCurrency(derivedMetrics.profitPerMW, { decimals: 0 })}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Profit Spread Scenarios */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-700">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Layers className="w-5 h-5 text-[#00ffd1]" />
                Profit Spread Scenarios
              </h3>
              <p className="text-slate-400 text-sm mt-1">
                Comparison of annual returns based on different effective profit spreads (€/MWh after efficiency losses)
              </p>
            </div>
            <div className="p-5">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Optimistic Scenario - 131 €/MWh */}
                <div className="bg-gradient-to-br from-green-500/10 to-slate-800 border border-green-500/30 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-5 h-5 text-green-400" />
                      <span className="text-green-400 font-semibold">Optimistic</span>
                    </div>
                    <span className="px-2 py-1 bg-green-500/20 text-green-400 text-xs font-mono rounded">
                      131 €/MWh
                    </span>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <p className="text-slate-400 text-xs">Daily Profit</p>
                      <p className="text-2xl font-bold text-white font-mono">
                        {formatCurrency(scenarioMetrics[0].dailyProfit, { decimals: 0 })}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400 text-xs">Annual Profit</p>
                      <p className="text-xl font-bold text-green-400 font-mono">
                        {formatCompact(scenarioMetrics[0].annualProfit)}
                      </p>
                    </div>
                    <div className="pt-3 border-t border-slate-700">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Profit/MW</span>
                        <span className="text-white font-mono">{formatCompact(scenarioMetrics[0].profitPerMW)}</span>
                      </div>
                      <div className="flex justify-between text-sm mt-1">
                        <span className="text-slate-400">Payback</span>
                        <span className="text-white font-mono">{scenarioMetrics[0].paybackYears.toFixed(1)} yrs</span>
                      </div>
                    </div>
                  </div>
                  <p className="text-slate-400 text-xs mt-4">
                    High volatility periods, summer peaks, gas price spikes
                  </p>
                </div>

                {/* Base Case Scenario - 100 €/MWh */}
                <div className="bg-gradient-to-br from-[#00ffd1]/10 to-slate-800 border border-[#00ffd1]/30 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Target className="w-5 h-5 text-[#00ffd1]" />
                      <span className="text-[#00ffd1] font-semibold">Base Case</span>
                    </div>
                    <span className="px-2 py-1 bg-[#00ffd1]/20 text-[#00ffd1] text-xs font-mono rounded">
                      100 €/MWh
                    </span>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <p className="text-slate-400 text-xs">Daily Profit</p>
                      <p className="text-2xl font-bold text-white font-mono">
                        {formatCurrency(scenarioMetrics[1].dailyProfit, { decimals: 0 })}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400 text-xs">Annual Profit</p>
                      <p className="text-xl font-bold text-[#00ffd1] font-mono">
                        {formatCompact(scenarioMetrics[1].annualProfit)}
                      </p>
                    </div>
                    <div className="pt-3 border-t border-slate-700">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Profit/MW</span>
                        <span className="text-white font-mono">{formatCompact(scenarioMetrics[1].profitPerMW)}</span>
                      </div>
                      <div className="flex justify-between text-sm mt-1">
                        <span className="text-slate-400">Payback</span>
                        <span className="text-white font-mono">{scenarioMetrics[1].paybackYears.toFixed(1)} yrs</span>
                      </div>
                    </div>
                  </div>
                  <p className="text-slate-400 text-xs mt-4">
                    Average market conditions, typical seasonal patterns
                  </p>
                </div>

                {/* Conservative Scenario - 80 €/MWh */}
                <div className="bg-gradient-to-br from-amber-500/10 to-slate-800 border border-amber-500/30 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <TrendingDown className="w-5 h-5 text-amber-400" />
                      <span className="text-amber-400 font-semibold">Conservative</span>
                    </div>
                    <span className="px-2 py-1 bg-amber-500/20 text-amber-400 text-xs font-mono rounded">
                      80 €/MWh
                    </span>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <p className="text-slate-400 text-xs">Daily Profit</p>
                      <p className="text-2xl font-bold text-white font-mono">
                        {formatCurrency(scenarioMetrics[2].dailyProfit, { decimals: 0 })}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400 text-xs">Annual Profit</p>
                      <p className="text-xl font-bold text-amber-400 font-mono">
                        {formatCompact(scenarioMetrics[2].annualProfit)}
                      </p>
                    </div>
                    <div className="pt-3 border-t border-slate-700">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Profit/MW</span>
                        <span className="text-white font-mono">{formatCompact(scenarioMetrics[2].profitPerMW)}</span>
                      </div>
                      <div className="flex justify-between text-sm mt-1">
                        <span className="text-slate-400">Payback</span>
                        <span className="text-white font-mono">{scenarioMetrics[2].paybackYears.toFixed(1)} yrs</span>
                      </div>
                    </div>
                  </div>
                  <p className="text-slate-400 text-xs mt-4">
                    Low volatility, mild weather, increased competition
                  </p>
                </div>

                {/* Actual Analysis Scenario - Uses EXACT same values as Executive Summary */}
                <div className="bg-gradient-to-br from-[#00ffd1]/10 to-slate-800 border border-[#00ffd1]/30 rounded-xl p-5 relative">
                  <div className="absolute top-2 right-2">
                    <span className="px-2 py-0.5 bg-[#00ffd1]/30 text-[#00ffd1] text-[10px] font-semibold rounded uppercase">
                      From Data
                    </span>
                  </div>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <BarChart2 className="w-5 h-5 text-[#00ffd1]" />
                      <span className="text-[#00ffd1] font-semibold">Actual</span>
                    </div>
                    <span className="px-2 py-1 bg-[#00ffd1]/20 text-[#00ffd1] text-xs font-mono rounded">
                      {formatNumber(derivedMetrics?.avgSpread || 0, { decimals: 1 })} €/MWh
                    </span>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <p className="text-slate-400 text-xs">Avg Daily Profit</p>
                      <p className="text-2xl font-bold text-white font-mono">
                        {formatCurrency(derivedMetrics?.avgDailyProfit || 0, { decimals: 0 })}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400 text-xs">Annualized Profit</p>
                      <p className="text-xl font-bold text-[#00ffd1] font-mono">
                        {formatCompact(derivedMetrics?.annualizedProfit || 0)}
                      </p>
                    </div>
                    <div className="pt-3 border-t border-slate-700">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Profit/MW</span>
                        <span className="text-white font-mono">{formatCompact(derivedMetrics?.profitPerMW || 0)}</span>
                      </div>
                      <div className="flex justify-between text-sm mt-1">
                        <span className="text-slate-400">Payback</span>
                        <span className="text-white font-mono">{((derivedMetrics?.annualizedProfit || 0) > 0 ? params.investment_eur / (derivedMetrics?.annualizedProfit || 1) : 0).toFixed(1)} yrs</span>
                      </div>
                    </div>
                  </div>
                  <p className="text-slate-400 text-xs mt-4">
                    Based on {derivedMetrics?.monthCount || 0} months of OPCOM historical data
                  </p>
                </div>
              </div>

              {/* Scenario Comparison Table */}
              <div className="mt-6 overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-slate-800/50">
                      <th className="text-left px-4 py-3 text-slate-400 font-medium text-sm">Scenario</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Profit Spread</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Daily</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Monthly</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Annual</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">3-Year</th>
                      <th className="text-right px-4 py-3 text-slate-400 font-medium text-sm">Payback</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="bg-slate-900">
                      <td className="px-4 py-3 text-green-400 font-medium">Optimistic</td>
                      <td className="px-4 py-3 text-white text-right font-mono">131 €/MWh</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCurrency(scenarioMetrics[0].dailyProfit, { decimals: 0 })}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[0].dailyProfit * 30)}</td>
                      <td className="px-4 py-3 text-green-400 text-right font-mono font-semibold">{formatCompact(scenarioMetrics[0].annualProfit)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[0].annualProfit * 3)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{scenarioMetrics[0].paybackYears.toFixed(1)} yrs</td>
                    </tr>
                    <tr className="bg-slate-800/30">
                      <td className="px-4 py-3 text-[#00ffd1] font-medium">Base Case</td>
                      <td className="px-4 py-3 text-white text-right font-mono">100 €/MWh</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCurrency(scenarioMetrics[1].dailyProfit, { decimals: 0 })}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[1].dailyProfit * 30)}</td>
                      <td className="px-4 py-3 text-[#00ffd1] text-right font-mono font-semibold">{formatCompact(scenarioMetrics[1].annualProfit)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[1].annualProfit * 3)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{scenarioMetrics[1].paybackYears.toFixed(1)} yrs</td>
                    </tr>
                    <tr className="bg-slate-900">
                      <td className="px-4 py-3 text-amber-400 font-medium">Conservative</td>
                      <td className="px-4 py-3 text-white text-right font-mono">80 €/MWh</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCurrency(scenarioMetrics[2].dailyProfit, { decimals: 0 })}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[2].dailyProfit * 30)}</td>
                      <td className="px-4 py-3 text-amber-400 text-right font-mono font-semibold">{formatCompact(scenarioMetrics[2].annualProfit)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact(scenarioMetrics[2].annualProfit * 3)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{scenarioMetrics[2].paybackYears.toFixed(1)} yrs</td>
                    </tr>
                    <tr className="bg-slate-800/50 border-t border-[#00ffd1]/30">
                      <td className="px-4 py-3 text-[#00ffd1] font-medium flex items-center gap-2">
                        Actual (Analysis)
                        <span className="px-1.5 py-0.5 bg-[#00ffd1]/30 text-[#00ffd1] text-[10px] rounded">DATA</span>
                      </td>
                      <td className="px-4 py-3 text-white text-right font-mono">{scenarioMetrics[3]?.profitSpread || 0} €/MWh</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCurrency(scenarioMetrics[3]?.dailyProfit || 0, { decimals: 0 })}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact((scenarioMetrics[3]?.dailyProfit || 0) * 30)}</td>
                      <td className="px-4 py-3 text-[#00ffd1] text-right font-mono font-semibold">{formatCompact(scenarioMetrics[3]?.annualProfit || 0)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{formatCompact((scenarioMetrics[3]?.annualProfit || 0) * 3)}</td>
                      <td className="px-4 py-3 text-white text-right font-mono">{(scenarioMetrics[3]?.paybackYears || 0).toFixed(1)} yrs</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <p className="text-slate-400 text-xs mt-4">
                * Profit spread = effective spread after 90% round-trip efficiency. Based on {params.power_mw} MW / {params.capacity_mwh} MWh system with {formatCompact(params.investment_eur)} CAPEX.
              </p>
            </div>
          </div>
        </>
      )}

      {/* OPCOM Price Explorer Section */}
      <div className="bg-gradient-to-br from-slate-900 to-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg" style={{ background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)' }}>
              <Table className="w-5 h-5 text-slate-900" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">OPCOM DAM Price Explorer</h2>
              <p className="text-xs text-slate-400">Hourly prices from Romanian Day-Ahead Market (PZU/OPCOM)</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">{availableDates.length} days available</span>
            {hourlyPrices?.opcom_url && (
              <a
                href={hourlyPrices.opcom_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 bg-[#00ffd1]/10 border border-[#00ffd1]/30 rounded-lg text-[#00ffd1] text-xs hover:bg-[#00ffd1]/20 transition-colors"
              >
                <ExternalLink className="w-3 h-3" />
                View on OPCOM
              </a>
            )}
          </div>
        </div>

        <div className="p-5">
          {/* Date Selection Row */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-6">
            {/* Date Picker */}
            <div className="lg:col-span-1">
              <label htmlFor="pzu-select-date" className="block text-xs text-slate-400 mb-2">Select Date</label>
              <div className="relative">
                <input
                  id="pzu-select-date"
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-[#00ffd1] focus:outline-none"
                />
              </div>
            </div>

            {/* Quick Date Navigation */}
            <div className="lg:col-span-1">
              <label className="block text-xs text-slate-400 mb-2">Quick Select</label>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    const idx = availableDates.findIndex(d => d.date === selectedDate)
                    if (idx > 0) setSelectedDate(availableDates[idx - 1].date)
                  }}
                  className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-300 text-sm hover:bg-slate-700 transition-colors flex items-center justify-center gap-1"
                >
                  <ChevronLeft className="w-4 h-4" />
                  Prev
                </button>
                <button
                  onClick={() => {
                    const idx = availableDates.findIndex(d => d.date === selectedDate)
                    if (idx < availableDates.length - 1) setSelectedDate(availableDates[idx + 1].date)
                  }}
                  className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-300 text-sm hover:bg-slate-700 transition-colors flex items-center justify-center gap-1"
                >
                  Next
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Day Summary */}
            {hourlyPrices && (
              <>
                <div className="bg-slate-800/50 rounded-lg p-3">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Spread</p>
                  <p className="text-xl font-bold text-[#00ffd1] font-mono">{hourlyPrices.spread?.toFixed(1)} €</p>
                  <p className="text-[10px] text-slate-400">{hourlyPrices.day_of_week}</p>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-3">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Daily Profit</p>
                  <p className="text-xl font-bold text-emerald-400 font-mono">{formatCurrency(hourlyPrices.daily_profit, { decimals: 0 })}</p>
                  <p className="text-[10px] text-slate-400">{params.power_mw} MW system</p>
                </div>
              </>
            )}
          </div>

          {/* Hourly Price Chart */}
          {hourlyPrices && (
            <div className="mb-6">
              <h3 className="text-sm text-slate-400 mb-3 flex items-center gap-2">
                <BarChart2 className="w-4 h-4" />
                24-Hour Price Profile for {selectedDate}
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={hourlyPrices.hourly_prices} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="hourlyPriceGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#00ffd1" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#00ffd1" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                      dataKey="hour"
                      tick={{ fill: '#64748b', fontSize: 10 }}
                      tickFormatter={(v) => `${v}:00`}
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
                      formatter={(value: number, name: string) => {
                        if (name === 'price_eur_mwh') return [`${value?.toFixed(2)} €/MWh`, 'Price']
                        return [value, name]
                      }}
                      labelFormatter={(label) => `Hour ${label}:00`}
                    />
                    <ReferenceLine y={hourlyPrices.avg_price} stroke="#64748b" strokeDasharray="5 5" />
                    <Bar
                      dataKey="price_eur_mwh"
                      name="price_eur_mwh"
                      radius={[4, 4, 0, 0]}
                    >
                      {hourlyPrices.hourly_prices.map((entry: any, index: number) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={
                            entry.action === 'charge' ? '#22c55e' :
                            entry.action === 'discharge' ? '#00ffd1' :
                            '#475569'
                          }
                        />
                      ))}
                    </Bar>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="flex items-center justify-center gap-6 mt-3 text-xs">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-green-500" />
                  <span className="text-slate-400">Charge (Buy)</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-[#00ffd1]" />
                  <span className="text-slate-400">Discharge (Sell)</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-slate-600" />
                  <span className="text-slate-400">Idle</span>
                </span>
              </div>
            </div>
          )}

          {/* Hourly Price Table */}
          {hourlyPrices && (
            <div className="bg-slate-800/30 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
                <h3 className="text-sm font-medium text-white flex items-center gap-2">
                  <Clock className="w-4 h-4 text-[#00ffd1]" />
                  Hourly Energy Costs ({params.power_mw} MW)
                </h3>
                <div className="flex items-center gap-4 text-xs">
                  <span className="text-slate-400">
                    Charge: <span className="text-red-400 font-mono">{formatCurrency(hourlyPrices.total_charge_cost, { decimals: 0 })}</span>
                  </span>
                  <span className="text-slate-400">
                    Revenue: <span className="text-emerald-400 font-mono">{formatCurrency(hourlyPrices.total_discharge_revenue, { decimals: 0 })}</span>
                  </span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-800">
                      <th className="px-3 py-2 text-left text-slate-400 font-medium">Hour</th>
                      <th className="px-3 py-2 text-right text-slate-400 font-medium">Price (€/MWh)</th>
                      <th className="px-3 py-2 text-center text-slate-400 font-medium">Action</th>
                      <th className="px-3 py-2 text-right text-slate-400 font-medium">Energy (MWh)</th>
                      <th className="px-3 py-2 text-right text-slate-400 font-medium">Cost/Revenue (€)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hourlyPrices.hourly_prices.map((hour: any) => (
                      <tr
                        key={hour.hour}
                        className={`border-t border-slate-700/50 ${
                          hour.action === 'charge' ? 'bg-green-500/5' :
                          hour.action === 'discharge' ? 'bg-[#00ffd1]/5' :
                          ''
                        }`}
                      >
                        <td className="px-3 py-2 text-slate-300 font-mono">{hour.hour.toString().padStart(2, '0')}:00</td>
                        <td className="px-3 py-2 text-right font-mono text-white">
                          {hour.price_eur_mwh?.toFixed(2) ?? '-'}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-medium uppercase ${
                            hour.action === 'charge' ? 'bg-green-500/20 text-green-400' :
                            hour.action === 'discharge' ? 'bg-[#00ffd1]/20 text-[#00ffd1]' :
                            'bg-slate-700 text-slate-400'
                          }`}>
                            {hour.action}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-300">
                          {hour.energy_mwh > 0 ? hour.energy_mwh.toFixed(1) : '-'}
                        </td>
                        <td className={`px-3 py-2 text-right font-mono ${
                          hour.energy_cost_eur > 0 ? 'text-red-400' :
                          hour.energy_cost_eur < 0 ? 'text-emerald-400' :
                          'text-slate-400'
                        }`}>
                          {hour.energy_cost_eur !== 0 ? (
                            hour.energy_cost_eur > 0
                              ? `-${formatCurrency(hour.energy_cost_eur, { decimals: 0 })}`
                              : `+${formatCurrency(Math.abs(hour.energy_cost_eur), { decimals: 0 })}`
                          ) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 border-t border-slate-700 bg-slate-800/50">
                <div className="flex items-center justify-between">
                  <div className="text-xs text-slate-400">
                    Charge hours: {hourlyPrices.charge_hours.map((h: number) => h.toString().padStart(2, '0')).join(', ')} •
                    Discharge hours: {hourlyPrices.discharge_hours.map((h: number) => h.toString().padStart(2, '0')).join(', ')}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">Min: <span className="text-white font-mono">{hourlyPrices.min_price?.toFixed(1)}€</span></span>
                    <span className="text-slate-400">|</span>
                    <span className="text-xs text-slate-400">Avg: <span className="text-white font-mono">{hourlyPrices.avg_price?.toFixed(1)}€</span></span>
                    <span className="text-slate-400">|</span>
                    <span className="text-xs text-slate-400">Max: <span className="text-white font-mono">{hourlyPrices.max_price?.toFixed(1)}€</span></span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Loading state */}
          {loadingHourly && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#00ffd1]"></div>
              <span className="ml-3 text-slate-400">Loading hourly prices...</span>
            </div>
          )}

          {/* Date Grid - Last 30 days */}
          <div className="mt-6 pt-6 border-t border-slate-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm text-slate-400 flex items-center gap-2">
                <Calendar className="w-4 h-4" />
                Recent Days (click to select)
              </h3>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="text"
                  aria-label="Filter dates"
                  placeholder="Filter dates (e.g. 2024-11)"
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value)}
                  className="pl-9 pr-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-xs focus:border-[#00ffd1] focus:outline-none w-48"
                />
              </div>
            </div>
            <div className="grid grid-cols-5 md:grid-cols-7 lg:grid-cols-10 gap-2 max-h-64 overflow-y-auto">
              {filteredDates.slice(-60).map((dateItem: any) => (
                <button
                  key={dateItem.date}
                  onClick={() => setSelectedDate(dateItem.date)}
                  className={`p-2 rounded-lg text-xs transition-all ${
                    selectedDate === dateItem.date
                      ? 'bg-[#00ffd1]/20 border border-[#00ffd1] text-[#00ffd1]'
                      : 'bg-slate-800/50 border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  <div className="font-mono">{dateItem.date.slice(5)}</div>
                  <div className={`text-[10px] mt-1 ${
                    dateItem.spread > 100 ? 'text-emerald-400' :
                    dateItem.spread > 50 ? 'text-[#00ffd1]' :
                    'text-slate-400'
                  }`}>
                    {dateItem.spread?.toFixed(0)}€
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
