'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Home,
  BarChart3,
  Zap,
  TrendingUp,
  Settings,
  Battery,
  BookOpen,
  Printer,
  ExternalLink
} from 'lucide-react'

const navigation = [
  { name: 'Dashboard', href: '/', icon: Home },
  { name: 'PZU Analysis', href: '/pzu', icon: BarChart3 },
  { name: 'FR Simulator', href: '/fr-simulator', icon: Zap },
  { name: 'Investment', href: '/investment', icon: TrendingUp },
  { name: 'Investor Quick-Look', href: '/investor-summary', icon: Printer },
  { name: 'Methodology', href: '/methodology', icon: BookOpen },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <div className="flex h-full w-56 flex-col" style={{ background: 'linear-gradient(180deg, #0e152d 0%, #0a0f1f 100%)' }}>
      {/* Logo */}
      <a
        href="https://ebattery.energy"
        target="_blank"
        rel="noopener noreferrer"
        className="flex h-16 items-center px-4 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors group"
      >
        <div className="flex items-center gap-2">
          {/* eBattery Logo Icon */}
          <div className="relative">
            <Battery className="h-7 w-7" style={{ color: '#00ffd1' }} />
            <div className="absolute inset-0 blur-sm opacity-50">
              <Battery className="h-7 w-7" style={{ color: '#00ffd1' }} />
            </div>
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-bold tracking-tight">
              <span style={{ color: '#00ffd1' }}>e</span>
              <span className="text-white">Battery</span>
              <span className="text-slate-400">.energy</span>
            </span>
            <span className="text-[9px] text-slate-400 uppercase tracking-widest">Analytics Platform</span>
          </div>
        </div>
        <ExternalLink className="w-3 h-3 text-slate-400 ml-auto opacity-0 group-hover:opacity-100 transition-opacity" />
      </a>

      {/* Live Status */}
      <div className="px-4 py-2 border-b border-slate-800/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="status-dot status-live" />
          <span className="text-[10px] text-slate-400 uppercase tracking-wider">Live Data</span>
        </div>
        <span className="text-[10px] font-mono" style={{ color: '#00ffd1' }}>RO</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        <div className="text-[10px] uppercase tracking-widest text-slate-400 px-3 mb-2">Analytics</div>
        {navigation.map((item) => {
          const isActive = pathname === item.href
          return (
            <Link
              key={item.name}
              href={item.href}
              className={`
                flex items-center px-3 py-2.5 text-sm font-medium rounded-lg transition-all
                ${isActive
                  ? 'text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                }
              `}
              style={isActive ? {
                background: 'linear-gradient(135deg, rgba(0, 255, 209, 0.15) 0%, rgba(0, 255, 209, 0.05) 100%)',
                borderLeft: '2px solid #00ffd1',
              } : { borderLeft: '2px solid transparent' }}
            >
              <item.icon
                className="mr-2.5 h-4 w-4"
                style={{ color: isActive ? '#00ffd1' : '#64748b' }}
              />
              {item.name}
            </Link>
          )
        })}
      </nav>

      {/* Market Status */}
      <div className="px-3 py-3 border-t border-slate-800/50">
        <div className="text-[10px] uppercase tracking-widest text-slate-400 mb-2 px-1">Market Status</div>
        <div className="space-y-1.5 px-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">DAM (PZU)</span>
            <span style={{ color: '#00ffd1' }}>Open</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">aFRR</span>
            <span style={{ color: '#00ffd1' }}>Active</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">mFRR</span>
            <span className="text-slate-400">Standby</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-slate-800/50 p-3">
        <Link
          href="/settings"
          className="flex items-center px-2 py-1.5 text-xs font-medium text-slate-400 rounded hover:bg-slate-800/50 hover:text-slate-300 transition-colors"
        >
          <Settings className="mr-2 h-3.5 w-3.5" />
          Settings
        </Link>
        <div className="mt-3 px-2 text-[10px] text-slate-400">
          <p className="flex items-center gap-1">
            <span>Powered by</span>
            <a
              href="https://ebattery.energy"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
              style={{ color: '#00ffd1' }}
            >
              eBattery.energy
            </a>
          </p>
          <p className="text-slate-400 mt-0.5">Romanian Energy Markets</p>
        </div>
      </div>
    </div>
  )
}
