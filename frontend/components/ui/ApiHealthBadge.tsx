'use client'

/**
 * ApiHealthBadge — pings ${API_BASE_URL}/api/health and shows a green/red
 * indicator. Replaces the static `LIVE` label that the audit flagged as
 * misleading (Agent 2 Medium).
 */

import { useEffect, useState } from 'react'
import { API_BASE_URL } from '@/lib/api'

type Health = 'connected' | 'connecting' | 'down'

async function checkHealth(signal: AbortSignal): Promise<Health> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`, { signal })
    if (!res.ok) return 'down'
    const body = await res.json()
    return body?.status === 'healthy' ? 'connected' : 'down'
  } catch {
    return 'down'
  }
}

export function ApiHealthBadge({ className = '' }: { className?: string }) {
  const [state, setState] = useState<Health>('connecting')

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    const tick = async () => {
      const h = await checkHealth(controller.signal)
      if (!cancelled) setState(h)
    }
    tick()
    const id = setInterval(tick, 60_000) // re-check every 60s
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(id)
    }
  }, [])

  const colors: Record<Health, { dot: string; text: string; label: string }> = {
    connected: { dot: 'bg-emerald-500', text: 'text-emerald-300', label: 'API CONNECTED' },
    connecting: { dot: 'bg-slate-500 animate-pulse', text: 'text-slate-300', label: 'API CHECKING' },
    down: { dot: 'bg-red-500', text: 'text-red-300', label: 'API DOWN' },
  }
  const c = colors[state]

  return (
    <span
      title={`Backend health probe: ${state}`}
      className={`inline-flex items-center gap-1.5 rounded bg-slate-800/50 px-2 py-1 ring-1 ring-slate-700 ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      <span className={`text-[10px] font-mono uppercase ${c.text}`}>{c.label}</span>
    </span>
  )
}

export default ApiHealthBadge
