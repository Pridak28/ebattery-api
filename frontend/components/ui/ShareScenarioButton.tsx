'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Share2, Check } from 'lucide-react'

interface ShareScenarioButtonProps {
  getUrl: () => string
  className?: string
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof window === 'undefined') return false
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export default function ShareScenarioButton({
  getUrl,
  className = '',
}: ShareScenarioButtonProps) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const handleClick = useCallback(async () => {
    const url = (() => {
      try {
        return getUrl()
      } catch {
        return typeof window !== 'undefined' ? window.location.href : ''
      }
    })()
    if (!url) return
    const ok = await copyToClipboard(url)
    if (!ok) return
    setCopied(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setCopied(false), 2000)
  }, [getUrl])

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label="Share scenario URL"
      className={
        className ||
        'inline-flex items-center gap-2 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-xs sm:text-sm text-white hover:border-[#00ffd1] hover:text-[#00ffd1] transition-colors min-h-[44px] sm:min-h-[36px]'
      }
    >
      {copied ? (
        <>
          <Check className="w-4 h-4 text-[#00ffd1]" />
          <span>Copied!</span>
        </>
      ) : (
        <>
          <Share2 className="w-4 h-4" />
          <span>Share scenario</span>
        </>
      )}
    </button>
  )
}
