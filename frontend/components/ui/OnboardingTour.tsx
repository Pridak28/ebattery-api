'use client'

/**
 * OnboardingTour — lightweight tooltip walkthrough overlay used on the
 * investor dashboard. Renders a backdrop + a floating card per step. If
 * the step has a `target` CSS selector that resolves to a DOM node, the
 * card is positioned relative to its bounding rect; otherwise the card
 * is centered. Pure presentational — all step state lives in the
 * useOnboardingTour hook.
 *
 * No new npm deps; positioning is computed via getBoundingClientRect()
 * and recomputed on resize/scroll.
 */

import { useEffect, useState, useCallback, CSSProperties } from 'react'

export type TourStep = {
  title: string
  description: string
  target?: string
  placement?: 'top' | 'bottom' | 'left' | 'right'
}

export type OnboardingTourProps = {
  steps: TourStep[]
  currentStep: number
  onNext: () => void
  onPrev: () => void
  onDismiss: () => void
  className?: string
}

type Pos = { top: number; left: number }

const CARD_W = 360
const CARD_H_EST = 200
const GAP = 12

function computePosition(step: TourStep | undefined): Pos {
  if (typeof window === 'undefined') return { top: 0, left: 0 }
  const vw = window.innerWidth
  const vh = window.innerHeight
  const center = (): Pos => ({
    top: Math.max(16, vh / 2 - CARD_H_EST / 2),
    left: Math.max(16, vw / 2 - CARD_W / 2),
  })
  const el = step?.target ? (document.querySelector(step.target) as HTMLElement | null) : null
  if (!step || !el) return center()
  const r = el.getBoundingClientRect()
  let top = 0
  let left = 0
  switch (step.placement ?? 'bottom') {
    case 'top':
      top = r.top - CARD_H_EST - GAP
      left = r.left + r.width / 2 - CARD_W / 2
      break
    case 'left':
      top = r.top + r.height / 2 - CARD_H_EST / 2
      left = r.left - CARD_W - GAP
      break
    case 'right':
      top = r.top + r.height / 2 - CARD_H_EST / 2
      left = r.right + GAP
      break
    default:
      top = r.bottom + GAP
      left = r.left + r.width / 2 - CARD_W / 2
  }
  top = Math.max(16, Math.min(top, vh - CARD_H_EST - 16))
  left = Math.max(16, Math.min(left, vw - CARD_W - 16))
  return { top, left }
}

const STYLES: Record<string, CSSProperties> = {
  backdrop: {
    position: 'absolute',
    inset: 0,
    background: 'rgba(2, 6, 23, 0.65)',
    backdropFilter: 'blur(2px)',
  },
  cardBase: {
    position: 'absolute',
    width: CARD_W,
    maxWidth: 'calc(100vw - 32px)',
    background: 'linear-gradient(135deg, #0e152d 0%, #0a1124 100%)',
    border: '1px solid rgba(0, 255, 209, 0.4)',
    borderRadius: 12,
    boxShadow: '0 20px 50px rgba(0,0,0,0.5), 0 0 0 1px rgba(0,255,209,0.1)',
    padding: 20,
    color: '#e2e8f0',
    zIndex: 9999,
  },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  badge: { fontSize: 11, letterSpacing: 1, textTransform: 'uppercase', color: '#00ffd1', fontFamily: 'monospace' },
  skip: { background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '2px 6px' },
  title: { margin: 0, marginBottom: 8, fontSize: 18, fontWeight: 700, color: '#ffffff' },
  desc: { margin: 0, marginBottom: 16, fontSize: 14, lineHeight: 1.5, color: '#cbd5e1' },
  actions: { display: 'flex', justifyContent: 'space-between', gap: 8 },
  next: {
    padding: '8px 16px', borderRadius: 8,
    background: 'linear-gradient(135deg, #00ffd1 0%, #00d4aa 100%)',
    border: 'none', color: '#0f172a', fontWeight: 600, cursor: 'pointer', fontSize: 13,
  },
}

function backBtn(disabled: boolean): CSSProperties {
  return {
    padding: '8px 14px', borderRadius: 8,
    background: 'rgba(148, 163, 184, 0.1)',
    border: '1px solid rgba(148, 163, 184, 0.3)',
    color: disabled ? '#475569' : '#cbd5e1',
    cursor: disabled ? 'not-allowed' : 'pointer', fontSize: 13,
  }
}

export default function OnboardingTour({
  steps,
  currentStep,
  onNext,
  onPrev,
  onDismiss,
  className,
}: OnboardingTourProps) {
  const safeIndex = Math.max(0, Math.min(currentStep, steps.length - 1))
  const step = steps[safeIndex]
  const isLast = safeIndex === steps.length - 1
  const isFirst = safeIndex === 0

  const [pos, setPos] = useState<Pos>({ top: 0, left: 0 })

  const recompute = useCallback(() => setPos(computePosition(step)), [step])

  useEffect(() => {
    recompute()
    const onResize = () => recompute()
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onResize, true)
    const t = window.setTimeout(recompute, 50)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onResize, true)
      window.clearTimeout(t)
    }
  }, [recompute])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onDismiss() }
      else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); onNext() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); onPrev() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onNext, onPrev, onDismiss])

  if (!step) return null

  return (
    <div
      className={className}
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-tour-title"
      style={{ position: 'fixed', inset: 0, zIndex: 9998 }}
    >
      <div onClick={onDismiss} aria-hidden="true" style={STYLES.backdrop} />
      <div style={{ ...STYLES.cardBase, top: pos.top, left: pos.left }}>
        <div style={STYLES.header}>
          <span style={STYLES.badge}>Step {safeIndex + 1} of {steps.length}</span>
          <button type="button" onClick={onDismiss} style={STYLES.skip} aria-label="Skip tour">
            Skip tour
          </button>
        </div>
        <h3 id="onboarding-tour-title" style={STYLES.title}>{step.title}</h3>
        <p style={STYLES.desc}>{step.description}</p>
        <div style={STYLES.actions}>
          <button type="button" onClick={onPrev} disabled={isFirst} style={backBtn(isFirst)}>
            ← Back
          </button>
          <button type="button" onClick={onNext} style={STYLES.next}>
            {isLast ? 'Done →' : 'Next →'}
          </button>
        </div>
      </div>
    </div>
  )
}
