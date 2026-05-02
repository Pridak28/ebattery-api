'use client'

/**
 * SnapshotButtons — companion controls for ScenarioDiffPanel.
 *
 * Two buttons: "Save as A" / "Save as B". Click captures the current analysis
 * payload + an investor-readable label (e.g. "10MW/20MWh @ €3.5M, 30% equity")
 * into the parent's snapshot slot. Buttons disable when no analysis is loaded.
 */

import { Save } from 'lucide-react'

export type SnapshotButtonsProps = {
  currentAnalysis: any
  currentLabel: string
  setSlot: (slot: 'A' | 'B', value: any, label: string) => void
  className?: string
}

export default function SnapshotButtons({
  currentAnalysis,
  currentLabel,
  setSlot,
  className = '',
}: SnapshotButtonsProps) {
  const disabled = currentAnalysis == null

  const handle = (slot: 'A' | 'B') => {
    if (disabled) return
    setSlot(slot, currentAnalysis, currentLabel)
  }

  const baseClass =
    'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-mono uppercase tracking-wider border transition-colors disabled:opacity-40 disabled:cursor-not-allowed'

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <button
        type="button"
        onClick={() => handle('A')}
        disabled={disabled}
        title={
          disabled
            ? 'Run an analysis first'
            : `Save current run to slot A: ${currentLabel}`
        }
        className={`${baseClass} bg-blue-500/10 border-blue-500/30 text-blue-300 hover:bg-blue-500/20`}
      >
        <Save className="w-3.5 h-3.5" />
        Save as A
      </button>
      <button
        type="button"
        onClick={() => handle('B')}
        disabled={disabled}
        title={
          disabled
            ? 'Run an analysis first'
            : `Save current run to slot B: ${currentLabel}`
        }
        className={`${baseClass} bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20`}
      >
        <Save className="w-3.5 h-3.5" />
        Save as B
      </button>
    </div>
  )
}
