'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

type FieldType = 'number' | 'string' | 'boolean'

export type ScenarioSchema<T> = { [K in keyof T]: FieldType }

function coerce(raw: string, type: FieldType): unknown {
  if (type === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : undefined
  }
  if (type === 'boolean') {
    if (raw === 'true' || raw === '1') return true
    if (raw === 'false' || raw === '0') return false
    return undefined
  }
  return raw
}

function readFromUrl<T extends Record<string, any>>(
  initial: T,
  schema: ScenarioSchema<T>,
): T {
  if (typeof window === 'undefined') return initial
  try {
    const sp = new URLSearchParams(window.location.search)
    const next: Record<string, any> = { ...initial }
    for (const key of Object.keys(schema) as (keyof T)[]) {
      const raw = sp.get(String(key))
      if (raw === null) continue
      const v = coerce(raw, schema[key])
      if (v !== undefined) next[key as string] = v
    }
    return next as T
  } catch {
    return initial
  }
}

function buildUrl<T extends Record<string, any>>(
  state: T,
  schema: ScenarioSchema<T>,
): string {
  if (typeof window === 'undefined') return ''
  const url = new URL(window.location.href)
  // Drop any keys we own first, then write current state.
  for (const key of Object.keys(schema)) url.searchParams.delete(key)
  for (const key of Object.keys(schema) as (keyof T)[]) {
    const v = state[key]
    if (v === undefined || v === null) continue
    if (typeof v === 'number' && !Number.isFinite(v)) continue
    url.searchParams.set(String(key), String(v))
  }
  return url.toString()
}

export function useScenarioUrl<T extends Record<string, any>>(
  initial: T,
  schema: ScenarioSchema<T>,
): [T, (next: T | ((prev: T) => T)) => void, string] {
  // Schema is treated as stable across renders.
  const schemaRef = useRef(schema)
  const [state, setStateInternal] = useState<T>(initial)
  const [shareUrl, setShareUrl] = useState<string>('')

  // Hydrate from URL on mount (client only).
  useEffect(() => {
    const hydrated = readFromUrl(initial, schemaRef.current)
    setStateInternal(hydrated)
    setShareUrl(buildUrl(hydrated, schemaRef.current))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setState = useCallback((next: T | ((prev: T) => T)) => {
    setStateInternal((prev) => {
      const resolved =
        typeof next === 'function' ? (next as (p: T) => T)(prev) : next
      if (typeof window !== 'undefined') {
        try {
          const newUrl = buildUrl(resolved, schemaRef.current)
          window.history.replaceState(null, '', newUrl)
          setShareUrl(newUrl)
        } catch {
          // ignore — keep state update regardless
        }
      }
      return resolved
    })
  }, [])

  return [state, setState, shareUrl]
}

export default useScenarioUrl
