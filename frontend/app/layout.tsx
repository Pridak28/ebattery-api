import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { MobileNav } from '@/components/layouts/MobileNav'
import { Providers } from './providers'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'eBattery Analytics | Energy Storage Platform',
  description: 'Professional Battery Energy Storage Analytics Platform by eBattery.energy',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className}>
        <Providers>
          <MobileNav>
            {children}
          </MobileNav>
        </Providers>
      </body>
    </html>
  )
}
