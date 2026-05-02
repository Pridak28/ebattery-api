'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, Download, Check, AlertCircle } from 'lucide-react'

interface ScenarioJsonButtonsProps {
  params: any
  analysis: any | null
  onImport: (params: any) => void
  disabled?: boolean
  className?: string
}

const SCHEMA_VERSION = 'bess_scenario_v1'
const REQUIRED_PARAM_KEYS = ['power_mw', 'capacity_mwh', 'total_investment_eur'] as const
const MAX_FILE_BYTES = 1_048_576 // 1 MB

type Status =
  | { kind: 'idle' }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string }

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function todayStamp(): string {
  const d = new Date()
  return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}`
}

function buildSnapshot(analysis: any | null) {
  if (!analysis) return null
  return {
    fr_y1: analysis?.fr_scenario?.net_profit_after_debt_eur ?? null,
    pzu_y1: analysis?.pzu_scenario?.net_profit_after_debt_eur ?? null,
    fr_irr: analysis?.fr_lifetime_irr_pct ?? analysis?.fr_scenario?.roi_percentage ?? null,
    pzu_irr: analysis?.pzu_lifetime_irr_pct ?? analysis?.pzu_scenario?.roi_percentage ?? null,
  }
}

function buildExport(params: any, analysis: any | null) {
  return {
    schema_version: SCHEMA_VERSION,
    exported_at: new Date().toISOString(),
    params,
    analysis_snapshot: buildSnapshot(analysis),
  }
}

function buildFilename(params: any): string {
  const power = Number(params?.power_mw ?? 0)
  const cap = Number(params?.capacity_mwh ?? 0)
  return `bess_scenario_${power}MW_${cap}MWh_${todayStamp()}.json`
}

function validatePayload(parsed: any): { ok: true; params: any } | { ok: false; error: string } {
  if (!parsed || typeof parsed !== 'object') {
    return { ok: false, error: 'File is not a valid scenario object' }
  }
  if (parsed.schema_version !== SCHEMA_VERSION) {
    return { ok: false, error: 'Unsupported file version' }
  }
  const p = parsed.params
  if (!p || typeof p !== 'object' || Array.isArray(p)) {
    return { ok: false, error: 'Missing params object' }
  }
  for (const key of REQUIRED_PARAM_KEYS) {
    if (!(key in p) || typeof p[key] !== 'number' || !Number.isFinite(p[key])) {
      return { ok: false, error: `Missing or invalid field: ${key}` }
    }
  }
  return { ok: true, params: p }
}

export default function ScenarioJsonButtons({
  params,
  analysis,
  onImport,
  disabled = false,
  className = '',
}: ScenarioJsonButtonsProps) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const flashStatus = useCallback((next: Status, ms: number) => {
    setStatus(next)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setStatus({ kind: 'idle' }), ms)
  }, [])

  const handleExport = useCallback(() => {
    if (typeof window === 'undefined') return
    try {
      const payload = buildExport(params, analysis)
      const json = JSON.stringify(payload, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = buildFilename(params)
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('[ScenarioJsonButtons] export failed', err)
      flashStatus({ kind: 'error', message: 'Export failed' }, 3000)
    }
  }, [params, analysis, flashStatus])

  const handlePickFile = useCallback(() => {
    if (disabled) return
    fileInputRef.current?.click()
  }, [disabled])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      // reset so picking the same file again still triggers change
      e.target.value = ''
      if (!file) return
      if (file.size > MAX_FILE_BYTES) {
        flashStatus({ kind: 'error', message: 'File too large (max 1MB)' }, 3000)
        return
      }
      const reader = new FileReader()
      reader.onerror = () => {
        console.error('[ScenarioJsonButtons] read error', reader.error)
        flashStatus({ kind: 'error', message: 'Could not read file' }, 3000)
      }
      reader.onload = () => {
        const text = typeof reader.result === 'string' ? reader.result : ''
        let parsed: any
        try {
          parsed = JSON.parse(text)
        } catch (err) {
          console.error('[ScenarioJsonButtons] JSON parse error', err)
          flashStatus({ kind: 'error', message: 'Invalid JSON file' }, 3000)
          return
        }
        const result = validatePayload(parsed)
        if (!result.ok) {
          console.error('[ScenarioJsonButtons] validation failed', result.error)
          flashStatus({ kind: 'error', message: result.error }, 3000)
          return
        }
        try {
          onImport(result.params)
          flashStatus({ kind: 'success', message: 'Imported' }, 2000)
        } catch (err) {
          console.error('[ScenarioJsonButtons] onImport threw', err)
          flashStatus({ kind: 'error', message: 'Import handler failed' }, 3000)
        }
      }
      reader.readAsText(file)
    },
    [flashStatus, onImport]
  )

  const baseBtn =
    className ||
    'inline-flex items-center gap-2 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-xs sm:text-sm text-white hover:border-[#00ffd1] hover:text-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px] disabled:opacity-50 disabled:cursor-not-allowed'

  const importLabel = (() => {
    if (status.kind === 'success') {
      return (
        <>
          <Check className="w-4 h-4 text-[#00ffd1]" />
          <span>Imported {String.fromCharCode(0x2713)}</span>
        </>
      )
    }
    if (status.kind === 'error') {
      return (
        <>
          <AlertCircle className="w-4 h-4 text-red-400" />
          <span className="truncate max-w-[14ch]" title={status.message}>
            {status.message}
          </span>
        </>
      )
    }
    return (
      <>
        <Upload className="w-4 h-4" />
        <span>Import JSON</span>
      </>
    )
  })()

  return (
    <div className="flex flex-col sm:flex-row gap-2">
      <button
        type="button"
        onClick={handleExport}
        disabled={disabled}
        aria-label="Export scenario as JSON"
        className={baseBtn}
      >
        <Download className="w-4 h-4" />
        <span>Export JSON</span>
      </button>
      <button
        type="button"
        onClick={handlePickFile}
        disabled={disabled}
        aria-label="Import scenario from JSON"
        aria-live="polite"
        className={baseBtn}
      >
        {importLabel}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={handleFileChange}
      />
    </div>
  )
}
