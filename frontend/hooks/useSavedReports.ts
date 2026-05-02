'use client'

/**
 * useSavedReports — investor-facing localStorage-backed store for saved
 * analysis runs. SSR-safe (no window outside useEffect), defensive against
 * private-browsing localStorage failures (falls back to in-memory), and
 * caps history at MAX_REPORTS via FIFO eviction.
 *
 * No backend involved — this is purely client-side personal scratchpad.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type SavedReport = {
  id: string
  name: string
  savedAt: string // ISO timestamp
  params: any
  analysis: any
}

const STORAGE_KEY = 'bess_saved_reports_v1'
const MAX_REPORTS = 20

function genId(): string {
  // Prefer crypto.randomUUID where available; fall back to a simple
  // timestamp+random combo (no new deps).
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    // ignore
  }
  return `r_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

function isStorageAvailable(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const probe = '__bess_probe__'
    window.localStorage.setItem(probe, probe)
    window.localStorage.removeItem(probe)
    return true
  } catch {
    return false
  }
}

function loadFromStorage(): SavedReport[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // Best-effort shape validation: keep only well-formed rows.
    return parsed.filter(
      (r: any) =>
        r &&
        typeof r.id === 'string' &&
        typeof r.name === 'string' &&
        typeof r.savedAt === 'string',
    ) as SavedReport[]
  } catch (err) {
    // Parse failure → return empty list and log (sanity escape).
    // eslint-disable-next-line no-console
    console.error('useSavedReports: failed to parse localStorage', err)
    return []
  }
}

function persist(reports: SavedReport[], available: boolean) {
  if (!available) return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(reports))
  } catch (err) {
    // Quota exceeded or similar — log and continue with in-memory state.
    // eslint-disable-next-line no-console
    console.error('useSavedReports: failed to write localStorage', err)
  }
}

export type UseSavedReportsReturn = {
  reports: SavedReport[]
  save: (name: string, params: any, analysis: any) => SavedReport
  deleteById: (id: string) => void
  clear: () => void
}

export function useSavedReports(): UseSavedReportsReturn {
  const [reports, setReports] = useState<SavedReport[]>([])
  const availableRef = useRef<boolean>(false)
  const hydratedRef = useRef<boolean>(false)

  // Hydrate once on mount (client only).
  useEffect(() => {
    availableRef.current = isStorageAvailable()
    setReports(loadFromStorage())
    hydratedRef.current = true
  }, [])

  const save = useCallback(
    (name: string, params: any, analysis: any): SavedReport => {
      const trimmed = (name || '').trim() || 'Untitled report'
      const report: SavedReport = {
        id: genId(),
        name: trimmed,
        savedAt: new Date().toISOString(),
        params,
        analysis,
      }
      setReports((prev) => {
        // Newest first; FIFO drop oldest beyond MAX_REPORTS.
        const next = [report, ...prev].slice(0, MAX_REPORTS)
        persist(next, availableRef.current)
        return next
      })
      return report
    },
    [],
  )

  const deleteById = useCallback((id: string) => {
    setReports((prev) => {
      const next = prev.filter((r) => r.id !== id)
      persist(next, availableRef.current)
      return next
    })
  }, [])

  const clear = useCallback(() => {
    setReports(() => {
      persist([], availableRef.current)
      return []
    })
  }, [])

  return { reports, save, deleteById, clear }
}

export default useSavedReports
