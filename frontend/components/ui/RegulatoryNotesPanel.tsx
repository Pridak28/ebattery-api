'use client'

/**
 * RegulatoryNotesPanel — surfaces regulatory_notes + data_warnings from a
 * FRSimulationResponse so investors see the regime/MARI/PICASSO context.
 */

import { Gavel, AlertTriangle } from 'lucide-react'

export function RegulatoryNotesPanel({
  notes,
  warnings,
  className = '',
}: {
  notes?: string[]
  warnings?: string[]
  className?: string
}) {
  const hasNotes = (notes?.length ?? 0) > 0
  const hasWarnings = (warnings?.length ?? 0) > 0
  if (!hasNotes && !hasWarnings) return null

  return (
    <div className={`rounded-lg border border-slate-700 bg-slate-900/50 ${className}`}>
      <div className="flex items-center gap-2 px-3 sm:px-4 py-2 sm:py-3 border-b border-slate-700">
        <Gavel className="w-4 h-4 text-[#00ffd1]" />
        <h3 className="text-xs sm:text-sm font-semibold uppercase tracking-wider text-slate-300">
          Regulatory & Data Notes
        </h3>
      </div>

      <div className="p-3 sm:p-4 space-y-3">
        {hasWarnings && (
          <div>
            <p className="text-[10px] sm:text-[11px] uppercase tracking-wider text-amber-300 font-semibold mb-1.5 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              Data warnings
            </p>
            <ul className="space-y-1 text-[11px] sm:text-xs text-amber-100/80">
              {warnings!.map((w, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-amber-500 mt-0.5">▸</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasNotes && (
          <div>
            <p className="text-[10px] sm:text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
              Regulatory context
            </p>
            <ul className="space-y-1 text-[11px] sm:text-xs text-slate-300">
              {notes!.map((n, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-[#00ffd1] mt-0.5">•</span>
                  <span>{n}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default RegulatoryNotesPanel
