import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'https://ebattery-api.onrender.com'

export const api = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  // Render free tier cold-start can take 30-60s; allow time before failing.
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Cold-start retry: Render free-tier returns 503 / connection-reset for ~30s
// after going to sleep. Any 503 / network / timeout error is retried up to
// MAX_RETRIES times with exponential backoff. Idempotent GETs always retry;
// POSTs only retry on transport errors (no response received), never on
// server-side 5xx (avoids accidental double-execution of simulations).
const MAX_RETRIES = 3
const BACKOFF_MS = [1500, 3000, 6000]

type RetryConfig = InternalAxiosRequestConfig & { __retryCount?: number }

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const cfg = error.config as RetryConfig | undefined
    if (!cfg) return Promise.reject(error)

    cfg.__retryCount = cfg.__retryCount ?? 0
    if (cfg.__retryCount >= MAX_RETRIES) return Promise.reject(error)

    const status = error.response?.status
    const isTransport = !error.response                       // network / timeout / abort
    const isColdStart = status === 503                        // Render asleep
    const isIdempotent = (cfg.method ?? 'get').toLowerCase() === 'get'

    const shouldRetry =
      (isTransport && cfg.__retryCount < MAX_RETRIES) ||
      (isColdStart && isIdempotent)

    if (!shouldRetry) return Promise.reject(error)

    const delay = BACKOFF_MS[cfg.__retryCount] ?? 6000
    cfg.__retryCount += 1
    await new Promise((r) => setTimeout(r, delay))
    return api(cfg)
  },
)

// PZU API
export const pzuApi = {
  getHistory: (params?: { start_date?: string; end_date?: string; aggregate?: string }) =>
    api.get('/pzu/history', { params }),

  simulate: (data: {
    power_mw: number
    capacity_mwh: number
    round_trip_efficiency: number
    start_date?: string
    end_date?: string
  }) => api.post('/pzu/simulate', data),

  getMonthlySummary: (params: {
    power_mw?: number
    capacity_mwh?: number
    efficiency?: number
    year?: number
  }) => api.get('/pzu/monthly-summary', { params }),

  getStats: () => api.get('/pzu/stats'),
}

// FR API
export const frApi = {
  getProducts: () => api.get('/fr/products'),

  getData: (params?: { product?: string; start_date?: string; end_date?: string }) =>
    api.get('/fr/data', { params }),

  simulate: (data: {
    capacity_mwh: number
    round_trip_efficiency: number
    afrr_up: { enabled: boolean; power_mw: number }
    afrr_down: { enabled: boolean; power_mw: number }
    mfrr_up?: { enabled: boolean; power_mw: number }
    mfrr_down?: { enabled: boolean; power_mw: number }
    energy_cost_eur_mwh: number
  }) => api.post('/fr/simulate', data),

  getMonthlyBreakdown: (params: {
    power_mw?: number
    capacity_mwh?: number
    product?: string
  }) => api.get('/fr/monthly-breakdown', { params }),

  getStats: () => api.get('/fr/stats'),

  // Phase E2: Romanian product catalogue (capacity rates, settlement, MARI thresholds).
  getProductCatalog: () => api.get('/fr/product-catalog'),

  // Phase E1+E2: capacity vs activation per product (aFRR/mFRR/FCR).
  multiProduct: (data: {
    products: Array<'aFRR' | 'mFRR' | 'FCR'>
    power_mw: number
    capacity_mwh: number
    round_trip_efficiency?: number
    availability_pct?: number
    energy_cost_eur_mwh?: number
    activation_share?: number
    target_date?: string
    start_date?: string
    end_date?: string
  }) => api.post('/fr/multi-product', data),
}

// Data provenance API
export const dataApi = {
  getManifest: () => api.get('/data/manifest'),
  getStatus: () => api.get('/data/status'),
}

// Extended health diagnostics — sub-system breakdown for investor demos.
export const healthApi = {
  getDetailed: () => api.get('/data/health-detailed'),
}

// Investment API
export const investmentApi = {
  analyze: (data: {
    total_investment_eur: number
    equity_percentage: number
    loan_interest_rate: number
    loan_term_years: number
    opex_percentage?: number
    insurance_percentage?: number
    power_mw: number
    capacity_mwh: number
  }) => api.post('/investment/analyze', data),

  calculateFinancing: (data: {
    total_investment_eur: number
    equity_percentage: number
    loan_interest_rate: number
    loan_term_years: number
  }) => api.post('/investment/financing', data),

  getDefaults: () => api.get('/investment/defaults'),

  // Phase F1: Monte Carlo P10/P50/P90 IRR fan + raw IRR samples.
  sensitivity: (data: {
    params: {
      total_investment_eur: number
      equity_percentage: number
      loan_interest_rate: number
      loan_term_years: number
      opex_percentage?: number
      insurance_percentage?: number
      power_mw: number
      capacity_mwh: number
      rte_ac_ac?: number
      availability_pct?: number
      auxiliary_load_mw?: number
      revenue_currency?: 'EUR' | 'RON'
      fx_hedge_cost_pct?: number
    }
    config?: {
      runs?: number
      discount_rate?: number
      activation_share?: [number, number, number]
      rte_ac_ac?: [number, number, number]
      degradation_y1?: [number, number, number]
      fx_ron_per_eur?: [number, number, number]
      pzu_avg_spread_pct?: [number, number, number]
      seed?: number
    }
  }) => api.post('/investment/sensitivity', data),

  // Real-scenario engine (mirrors scripts/bess_cashflow_scenarios_excel.py).
  // Returns the 4 PICASSO/market-share scenarios with full PF cashflow,
  // both modeled (engineering optimum) and realistic (operator drag +
  // tax + depreciation) views per scenario.
  scenarios: (data: {
    epc_eur?: number
    power_mw?: number
    capacity_mwh?: number
    equity_pct?: number
    loan_pct?: number
    loan_rate?: number
    loan_term_yr?: number
    tax_rate?: number
    discount_rate?: number
    stack_afrr_capacity?: number
    stack_afrr_activation?: number
    stack_pzu?: number
    drag_afrr_capacity?: number
    drag_afrr_activation?: number
    drag_pzu?: number
    scenario_keys?: string[]
  } = {}) => api.post('/investment/scenarios', data),

  scenarioDefaults: () => api.get('/investment/scenarios/defaults'),
}

export default api
