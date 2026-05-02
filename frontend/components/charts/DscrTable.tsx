'use client'

/**
 * DscrTable — Phase F2: per-year DSCR (CFADS / debt service). Lender
 * covenant typically requires DSCR ≥ 1.20; rows below that threshold
 * highlight in red so investors see covenant breach risk at a glance.
 */
const fmtEur = (n: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(n)

export type DscrRow = {
  year: number
  cfads_eur: number
  debt_service_eur: number
  dscr: number
  capacity_factor: number
  warranty_status: 'ok' | 'exceeded'
  augmentation_cost_eur: number
}

const DSCR_COVENANT = 1.2

export function DscrTable({
  rows,
  violationYears = [],
}: {
  rows: DscrRow[]
  violationYears?: number[]
}) {
  if (!rows?.length) {
    return (
      <div className="rounded border border-slate-700 bg-slate-800/40 p-6 text-sm text-slate-400">
        No cashflow rows to display.
      </div>
    )
  }
  const violationSet = new Set(violationYears)
  return (
    <div className="overflow-x-auto rounded border border-slate-700 bg-slate-800/40">
      <table className="w-full text-sm">
        <caption className="px-3 py-2 text-left font-mono text-xs uppercase text-slate-300">
          DSCR per year (covenant: ≥ {DSCR_COVENANT.toFixed(2)})
        </caption>
        <thead className="bg-slate-900/60 text-[11px] uppercase text-slate-400">
          <tr>
            <th className="px-3 py-2 text-left">Year</th>
            <th className="px-3 py-2 text-right">CFADS</th>
            <th className="px-3 py-2 text-right">Debt service</th>
            <th className="px-3 py-2 text-right">DSCR</th>
            <th className="px-3 py-2 text-right">Capacity</th>
            <th className="px-3 py-2 text-right">Warranty</th>
            <th className="px-3 py-2 text-right">Augmentation</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isViolation =
              row.debt_service_eur > 0 && row.dscr > 0 && row.dscr < DSCR_COVENANT
            const flagged = isViolation || violationSet.has(row.year)
            return (
              <tr
                key={row.year}
                className={
                  flagged
                    ? 'bg-rose-900/40 text-rose-200'
                    : row.warranty_status === 'exceeded'
                      ? 'bg-amber-900/30 text-amber-200'
                      : 'odd:bg-slate-900/30'
                }
              >
                <td className="px-3 py-1 font-mono">{row.year}</td>
                <td className="px-3 py-1 text-right">{fmtEur(row.cfads_eur)}</td>
                <td className="px-3 py-1 text-right">{fmtEur(row.debt_service_eur)}</td>
                <td className="px-3 py-1 text-right font-mono">
                  {row.debt_service_eur > 0 ? row.dscr.toFixed(2) : '—'}
                </td>
                <td className="px-3 py-1 text-right">
                  {(row.capacity_factor * 100).toFixed(1)}%
                </td>
                <td className="px-3 py-1 text-right">
                  {row.warranty_status === 'exceeded' ? (
                    <span className="text-amber-300">EXCEEDED</span>
                  ) : (
                    <span className="text-emerald-300">ok</span>
                  )}
                </td>
                <td className="px-3 py-1 text-right">
                  {row.augmentation_cost_eur > 0 ? fmtEur(row.augmentation_cost_eur) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {violationYears.length > 0 && (
        <p className="border-t border-slate-700 px-3 py-2 text-xs text-rose-300">
          Lender covenant DSCR &lt; {DSCR_COVENANT.toFixed(2)} in years:{' '}
          {violationYears.join(', ')}. Consider lower gearing or longer tenor.
        </p>
      )}
    </div>
  )
}

export default DscrTable
