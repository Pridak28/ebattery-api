'use client'

/**
 * ExportCashflowButton — downloads the FR + PZU cashflow projection as a
 * single CSV file (Excel-friendly, RFC 4180 quoted, with UTF-8 BOM).
 *
 * Pure frontend BLOB download — no backend touch.
 */

import { Download } from 'lucide-react'

export type AnnualCashflow = {
  year: number
  gross_revenue_eur: number
  energy_cost_eur: number
  operating_cost_eur: number
  debt_service_eur: number
  net_profit_eur: number
  cumulative_profit_eur: number
  auxiliary_cost_eur: number
  augmentation_cost_eur: number
  cumulative_efc: number
  warranty_status: string
  calendar_fade: number
  cycle_fade: number
  capacity_factor: number
  cfads_eur: number
  dscr: number
  fx_hedge_cost_eur: number
  tariff_exemption_eur: number
}

type ExportParams = {
  power_mw?: number
  capacity_mwh?: number
  [key: string]: any
}

export interface ExportCashflowButtonProps {
  frCashflow: AnnualCashflow[]
  pzuCashflow: AnnualCashflow[]
  params: ExportParams
  disabled?: boolean
  className?: string
}

const COLUMNS: Array<keyof AnnualCashflow | 'scenario'> = [
  'year',
  'scenario',
  'gross_revenue_eur',
  'energy_cost_eur',
  'operating_cost_eur',
  'debt_service_eur',
  'auxiliary_cost_eur',
  'augmentation_cost_eur',
  'tariff_exemption_eur',
  'fx_hedge_cost_eur',
  'capacity_factor',
  'cumulative_efc',
  'warranty_status',
  'cfads_eur',
  'dscr',
  'net_profit_eur',
  'cumulative_profit_eur',
]

const CURRENCY_FIELDS = new Set([
  'gross_revenue_eur',
  'energy_cost_eur',
  'operating_cost_eur',
  'debt_service_eur',
  'auxiliary_cost_eur',
  'augmentation_cost_eur',
  'tariff_exemption_eur',
  'fx_hedge_cost_eur',
  'cfads_eur',
  'net_profit_eur',
  'cumulative_profit_eur',
])

const RATIO_FIELDS = new Set(['capacity_factor', 'cumulative_efc', 'dscr'])

function csvQuote(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

function formatCell(field: string, raw: unknown): string {
  if (raw === null || raw === undefined) return ''
  if (field === 'year') {
    const n = Number(raw)
    return Number.isFinite(n) ? String(Math.trunc(n)) : ''
  }
  if (field === 'scenario' || field === 'warranty_status') {
    return csvQuote(String(raw))
  }
  if (CURRENCY_FIELDS.has(field)) {
    const n = Number(raw)
    return Number.isFinite(n) ? n.toFixed(2) : ''
  }
  if (RATIO_FIELDS.has(field)) {
    const n = Number(raw)
    return Number.isFinite(n) ? n.toFixed(4) : ''
  }
  // Fallback: stringify + quote.
  return csvQuote(String(raw))
}

function buildCsv(fr: AnnualCashflow[], pzu: AnnualCashflow[]): string {
  const lines: string[] = []
  lines.push(COLUMNS.map((c) => csvQuote(String(c))).join(','))

  const rowFor = (row: AnnualCashflow, scenario: 'FR' | 'PZU'): string =>
    COLUMNS.map((field) => {
      if (field === 'scenario') return formatCell('scenario', scenario)
      return formatCell(field, (row as any)[field])
    }).join(',')

  for (const r of fr) lines.push(rowFor(r, 'FR'))
  for (const r of pzu) lines.push(rowFor(r, 'PZU'))

  return lines.join('\r\n')
}

function todayStamp(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

function buildFilename(params: ExportParams): string {
  const power = params?.power_mw ?? 'NA'
  const cap = params?.capacity_mwh ?? 'NA'
  return `bess_cashflow_${power}MW_${cap}MWh_${todayStamp()}.csv`
}

export function ExportCashflowButton({
  frCashflow,
  pzuCashflow,
  params,
  disabled = false,
  className = '',
}: ExportCashflowButtonProps) {
  const noData = (frCashflow?.length ?? 0) === 0 && (pzuCashflow?.length ?? 0) === 0
  const isDisabled = disabled || noData

  const handleClick = () => {
    if (isDisabled) return
    const csv = buildCsv(frCashflow ?? [], pzuCashflow ?? [])
    // UTF-8 BOM so Excel opens it as UTF-8.
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = buildFilename(params)
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    // Defer revoke so Safari finishes the download.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isDisabled}
      title={
        isDisabled
          ? 'Run the analysis first to enable cashflow export'
          : 'Download FR + PZU cashflow projection as CSV'
      }
      className={
        'inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs sm:text-sm font-mono uppercase tracking-wide text-slate-200 hover:bg-slate-700 hover:border-[#00ffd1]/40 hover:text-[#00ffd1] transition-colors disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-slate-800 disabled:hover:border-slate-700 disabled:hover:text-slate-200 ' +
        className
      }
    >
      <Download className="h-4 w-4" />
      Export Cashflow CSV
    </button>
  )
}

export default ExportCashflowButton
