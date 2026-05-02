'use client'

/**
 * SavedReportsPanel — investor-facing scratchpad of saved analysis runs.
 *
 * Persists to localStorage via useSavedReports. Shows a "Save Current" button
 * (disabled when no analysis is loaded) and a list of saved rows with Load
 * and Delete actions. Matches the dark slate-900 / [#00ffd1] accent style
 * used by sibling panels.
 */

import { useMemo, useState } from 'react'
import { Bookmark, Save, Trash2, Upload, X } from 'lucide-react'
import useSavedReports from '@/hooks/useSavedReports'

export type SavedReportsPanelProps = {
  currentParams: any
  currentAnalysis: any | null
  onLoad?: (params: any) => void
  className?: string
}

function formatSize(p: any): string {
  if (!p || typeof p !== 'object') return ''
  const power = typeof p.power_mw === 'number' ? `${p.power_mw}MW` : null
  const cap = typeof p.capacity_mwh === 'number' ? `${p.capacity_mwh}MWh` : null
  const inv =
    typeof p.total_investment_eur === 'number'
      ? `€${(p.total_investment_eur / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`
      : null
  const parts = [power && cap ? `${power}/${cap}` : power || cap, inv ? `@ ${inv}` : null]
  return parts.filter(Boolean).join(' ')
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function SavedReportsPanel({
  currentParams,
  currentAnalysis,
  onLoad,
  className = '',
}: SavedReportsPanelProps) {
  const { reports, save, deleteById } = useSavedReports()
  const [showInput, setShowInput] = useState(false)
  const [draftName, setDraftName] = useState('')

  const canSave = currentAnalysis != null
  const defaultName = useMemo(() => {
    const sized = formatSize(currentParams)
    return sized ? sized : 'Untitled report'
  }, [currentParams])

  const handleSaveClick = () => {
    if (!canSave) return
    setDraftName(defaultName)
    setShowInput(true)
  }

  const handleConfirm = () => {
    if (!canSave) return
    save(draftName, currentParams, currentAnalysis)
    setDraftName('')
    setShowInput(false)
  }

  const handleCancel = () => {
    setDraftName('')
    setShowInput(false)
  }

  return (
    <div className={`bg-slate-900 border border-slate-700 rounded-lg p-3 sm:p-5 ${className}`}>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Bookmark className="w-4 h-4 sm:w-5 sm:h-5 text-[#00ffd1]" />
          <h3 className="text-white font-semibold text-sm sm:text-base">Saved Reports</h3>
          <span className="text-slate-400 text-[10px] sm:text-xs hidden sm:inline">
            {reports.length}/20 stored locally
          </span>
        </div>
        <button
          type="button"
          onClick={handleSaveClick}
          disabled={!canSave}
          title={canSave ? 'Save current analysis' : 'Run an analysis first'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono uppercase tracking-wider border bg-[#00ffd1]/10 border-[#00ffd1]/30 text-[#00ffd1] hover:bg-[#00ffd1]/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Save className="w-3.5 h-3.5" />
          Save Current
        </button>
      </div>

      {showInput && (
        <div className="mb-3 p-3 bg-slate-800/50 border border-slate-700 rounded-md flex flex-col sm:flex-row sm:items-center gap-2">
          <input
            type="text"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConfirm()
              if (e.key === 'Escape') handleCancel()
            }}
            placeholder="Report name"
            autoFocus
            className="flex-1 px-3 py-1.5 rounded-md bg-slate-900 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-[#00ffd1]/50"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleConfirm}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono uppercase border bg-[#00ffd1]/10 border-[#00ffd1]/30 text-[#00ffd1] hover:bg-[#00ffd1]/20"
            >
              Save
            </button>
            <button
              type="button"
              onClick={handleCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono uppercase border bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
            >
              <X className="w-3.5 h-3.5" />
              Cancel
            </button>
          </div>
        </div>
      )}

      {reports.length === 0 ? (
        <p className="text-slate-400 text-xs sm:text-sm py-4 text-center">
          No saved reports yet.
        </p>
      ) : (
        <ul className="divide-y divide-slate-800">
          {reports.map((r) => {
            const sized = formatSize(r.params)
            return (
              <li
                key={r.id}
                className="flex flex-col sm:flex-row sm:items-center gap-2 py-2.5"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm font-medium truncate">{r.name}</p>
                  <p className="text-slate-400 text-[11px] font-mono">
                    {sized && <span className="text-slate-400">{sized}</span>}
                    {sized && <span className="mx-2 text-slate-400">|</span>}
                    <span>{formatDate(r.savedAt)}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onLoad?.(r.params)}
                    disabled={!onLoad}
                    title="Restore these parameters into the form"
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono uppercase border bg-[#00ffd1]/10 border-[#00ffd1]/30 text-[#00ffd1] hover:bg-[#00ffd1]/20 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Upload className="w-3 h-3" />
                    Load
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteById(r.id)}
                    title="Delete this saved report"
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono uppercase border bg-red-500/10 border-red-500/30 text-red-300 hover:bg-red-500/20"
                  >
                    <Trash2 className="w-3 h-3" />
                    Delete
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
