'use client'

import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Sidebar } from './Sidebar'

export function MobileNav({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen" style={{ background: 'linear-gradient(135deg, #0a0f1f 0%, #0e152d 50%, #111827 100%)' }}>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setSidebarOpen(true)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 rounded-lg bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 hover:bg-slate-700/80 transition-colors"
        aria-label="Open menu"
      >
        <Menu className="w-5 h-5 text-slate-300" />
      </button>

      {/* Mobile overlay — decorative click-outside-to-close.
          Keyboard users have a real <button aria-label="Close menu"> below,
          so this layer is hidden from assistive tech via aria-hidden. */}
      {sidebarOpen && (
        <div
          aria-hidden="true"
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar - hidden on mobile, visible on lg+ */}
      <div
        className={`
          fixed lg:relative inset-y-0 left-0 z-50
          transform transition-transform duration-300 ease-in-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
          lg:translate-x-0
        `}
      >
        {/* Close button for mobile */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="lg:hidden absolute top-4 right-4 z-10 p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 transition-colors"
          aria-label="Close menu"
        >
          <X className="w-4 h-4 text-slate-400" />
        </button>
        <Sidebar />
      </div>

      {/* Main content - full width on mobile, with left padding for hamburger */}
      <main className="flex-1 overflow-auto">
        <div className="p-4 pt-16 lg:p-6 lg:pt-6">
          {children}
        </div>
      </main>
    </div>
  )
}
