import { useEffect, useState } from 'react'

import { Card } from '@/components/ui/card'
import { DashboardEmbed } from '@/components/DashboardEmbed'
import * as api from '@/lib/api'
import type { CostTopSpender, HealthStatus } from '@/types/api'
import { formatInt, formatUsd } from '@/lib/format'

interface Props {
  onOpenSpace: (spaceId: string) => void
}

export function CostExplorer({ onOpenSpace }: Props) {
  const [top, setTop] = useState<CostTopSpender[] | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [days, setDays] = useState(7)

  useEffect(() => {
    api.getTopSpenders(days, 25).then(setTop).catch(() => setTop([]))
  }, [days])
  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Cost Explorer</h1>
          <p className="text-sm text-muted">
            Top-spending Genie Spaces and the embedded Lakeview dashboard.
          </p>
        </div>
        <select
          value={days}
          onChange={e => setDays(Number(e.target.value))}
          className="rounded border border-default bg-elevated px-2 py-1 text-sm"
        >
          <option value={7}>last 7 days</option>
          <option value={30}>last 30 days</option>
          <option value={90}>last 90 days</option>
        </select>
      </div>

      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-default bg-elevated text-left text-xs uppercase text-muted">
            <tr>
              <th className="px-4 py-2">Space</th>
              <th className="px-4 py-2 text-right">Queries</th>
              <th className="px-4 py-2 text-right">Approx USD</th>
            </tr>
          </thead>
          <tbody>
            {top?.map(s => (
              <tr
                key={s.space_id}
                className="cursor-pointer border-t border-default/50 hover:bg-elevated/50"
                onClick={() => onOpenSpace(s.space_id)}
              >
                <td className="px-4 py-2 font-mono text-xs">{s.space_id}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatInt(s.query_count)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatUsd(s.approx_usd)}</td>
              </tr>
            ))}
            {top && !top.length && (
              <tr><td colSpan={3} className="p-6 text-center text-muted">No cost data yet.</td></tr>
            )}
            {!top && <tr><td colSpan={3} className="p-6 text-center text-muted">Loading…</td></tr>}
          </tbody>
        </table>
      </Card>

      <Card className="p-0">
        <h2 className="border-b border-default px-4 py-2 text-sm font-medium uppercase text-muted">
          Embedded Lakeview dashboard
        </h2>
        <DashboardEmbed dashboardId={health?.dashboard_cost_id || ''} height={720} />
      </Card>
    </div>
  )
}
