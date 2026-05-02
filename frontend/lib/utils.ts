import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Bloomberg-style number formatting
export function formatCurrency(
  value: number,
  options: {
    currency?: string
    decimals?: number
    compact?: boolean
    showSign?: boolean
  } = {}
): string {
  const { currency = 'EUR', decimals = 0, compact = false, showSign = false } = options

  if (compact) {
    return formatCompact(value, { currency, showSign })
  }

  const formatted = new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(value))

  if (showSign && value > 0) {
    return '+' + formatted
  }
  if (value < 0) {
    return '-' + formatted
  }
  return formatted
}

export function formatNumber(
  value: number,
  options: {
    decimals?: number
    showSign?: boolean
  } = {}
): string {
  const { decimals = 0, showSign = false } = options

  const formatted = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(value))

  if (showSign && value > 0) {
    return '+' + formatted
  }
  if (value < 0) {
    return '-' + formatted
  }
  return formatted
}

export function formatPercentage(
  value: number,
  options: { decimals?: number; showSign?: boolean } = {}
): string {
  const { decimals = 1, showSign = false } = options
  const prefix = showSign && value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(decimals)}%`
}

export function formatCompact(
  value: number,
  options: { currency?: string; showSign?: boolean } = {}
): string {
  const { currency = 'EUR', showSign = false } = options
  const absValue = Math.abs(value)
  const sign = value < 0 ? '-' : (showSign && value > 0 ? '+' : '')
  const symbol = currency === 'EUR' ? '€' : '$'

  if (absValue >= 1_000_000_000) {
    return `${sign}${symbol}${(absValue / 1_000_000_000).toFixed(2)}B`
  }
  if (absValue >= 1_000_000) {
    return `${sign}${symbol}${(absValue / 1_000_000).toFixed(2)}M`
  }
  if (absValue >= 1_000) {
    return `${sign}${symbol}${(absValue / 1_000).toFixed(1)}K`
  }
  return `${sign}${symbol}${absValue.toFixed(0)}`
}

export function formatMW(value: number): string {
  return `${formatNumber(value, { decimals: 1 })} MW`
}

export function formatMWh(value: number): string {
  if (value >= 1000) {
    return `${formatNumber(value / 1000, { decimals: 2 })} GWh`
  }
  return `${formatNumber(value, { decimals: 1 })} MWh`
}

export function formatEurMW(value: number): string {
  return `${formatNumber(value, { decimals: 2 })} €/MW`
}

export function formatEurMWh(value: number): string {
  return `${formatNumber(value, { decimals: 2 })} €/MWh`
}
