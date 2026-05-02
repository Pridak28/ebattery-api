'use client'

/**
 * useOnboardingTour — first-visit walkthrough state for the investor
 * dashboard. Persists dismissal in localStorage so returning visitors
 * are not re-prompted. SSR-safe (no window outside useEffect) and
 * defensive against private-mode storage failures (falls back to an
 * in-memory dismissed flag). No backend involvement.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'bess_onboarding_dismissed_v1'

function isStorageAvailable(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const probe = '__bess_tour_probe__'
    window.localStorage.setItem(probe, probe)
    window.localStorage.removeItem(probe)
    return true
  } catch {
    return false
  }
}

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export type UseOnboardingTourReturn = {
  shouldShow: boolean
  currentStep: number
  next: () => void
  prev: () => void
  dismiss: () => void
  restart: () => void
}

export function useOnboardingTour(stepCount = 4): UseOnboardingTourReturn {
  // Start hidden until we hydrate on client — avoids SSR/CSR mismatch flash.
  const [hydrated, setHydrated] = useState(false)
  const [dismissed, setDismissed] = useState(true)
  const [currentStep, setCurrentStep] = useState(0)
  const availableRef = useRef<boolean>(false)

  useEffect(() => {
    availableRef.current = isStorageAvailable()
    setDismissed(readDismissed())
    setHydrated(true)
  }, [])

  const persist = useCallback((value: boolean) => {
    if (!availableRef.current) return
    try {
      if (value) window.localStorage.setItem(STORAGE_KEY, '1')
      else window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Quota / disabled — keep in-memory state only.
    }
  }, [])

  const dismiss = useCallback(() => {
    setDismissed(true)
    persist(true)
  }, [persist])

  const next = useCallback(() => {
    setCurrentStep((s) => {
      if (s >= stepCount - 1) {
        setDismissed(true)
        persist(true)
        return s
      }
      return s + 1
    })
  }, [stepCount, persist])

  const prev = useCallback(() => {
    setCurrentStep((s) => (s > 0 ? s - 1 : 0))
  }, [])

  const restart = useCallback(() => {
    setCurrentStep(0)
    setDismissed(false)
    persist(false)
  }, [persist])

  return { shouldShow: hydrated && !dismissed, currentStep, next, prev, dismiss, restart }
}

export default useOnboardingTour
