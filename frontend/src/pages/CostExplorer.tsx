import { useMemo, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { Card } from '@/components/ui/card'
import * as api from '@/lib/api'
import type { CostTopSpender, HealthStatus } from '@/types/api'
import { formatInt, formatUsd } from '@/lib/format'
import { genieSpaceUrl } from '@/lib/genie'
import { useCachedFetch } from '@/lib/cache'

interface Props {
  onOpenSpace: (spaceId: string) => void
}

type SortKey = 'space_id' | 'query_count' | 'approx_usd'

export function CostExplorer({ onOpenSpace }: Props) {
  const [days, setDays] = useState<number>(7)
  const [sortKey, setSortKey] = useState<SortKey>('approx_usd')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data: top } = useCachedFetch<CostTopSpender[]>(
    `top:${days}:50`,
    () => api.getTopSpenders(days, 50),
    [days],
  )
  const { data: health } = useCachedFetch<HealthStatus>('health', () => api.getHealth())

  const sorted = useMemo(() => {
    if (!top) return null
    const dir = sortDir === 'asc' ? 1 : -1
    return [...top].sort((a, b) => {
      switch (sortKey) {
        case 'space_id':
          return a.space_id.localeCompare(b.space_id) * dir
        case 'query_count':
          return (a.query_count - b.query_count) * dir
        case 'approx_usd':
          return ((a.approx_usd ?? 0) - (b.approx_usd ?? 0)) * dir
      }
    })
  }, [top, sortKey, sortDir])

  function toggleSort(k: SortKey) {
    if (k === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(k)
      setSortDir(k === 'space_id' ? 'asc' : 'desc')
    }
  }

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
              <Th onClick={() => toggleSort('space_id')} active={sortKey === 'space_id'} dir={sortDir}>
                Space
              </Th>
              <Th
                onClick={() => toggleSort('query_count')}
                active={sortKey === 'query_count'}
                dir={sortDir}
                align="right"
              >
                Queries
              </Th>
              <Th
                onClick={() => toggleSort('approx_usd')}
                active={sortKey === 'approx_usd'}
                dir={sortDir}
                align="right"
              >
                Approx USD
              </Th>
              <th className="px-4 py-2 w-8" />
            </tr>
          </thead>
          <tbody>
            {sorted?.map(s => (
              <tr
                key={s.space_id}
                className="cursor-pointer border-t border-default/50 hover:bg-elevated/50"
              >
                <td
                  className="px-4 py-2 font-mono text-xs"
                  onClick={() => onOpenSpace(s.space_id)}
                >
                  {s.space_id}
                </td>
                <td
                  className="px-4 py-2 text-right tabular-nums"
                  onClick={() => onOpenSpace(s.space_id)}
                >
                  {formatInt(s.query_count)}
                </td>
                <td
                  className="px-4 py-2 text-right tabular-nums"
                  onClick={() => onOpenSpace(s.space_id)}
                >
                  {formatUsd(s.approx_usd)}
                </td>
                <td className="px-2 py-2 text-right">
                  <a
                    href={genieSpaceUrl(s.space_id, health?.workspace_host ?? null)}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    title="Open Genie Space in Databricks"
                    className="inline-flex items-center text-muted hover:text-fg"
                  >
                    <ExternalLink size={14} />
                  </a>
                </td>
              </tr>
            ))}
            {sorted && !sorted.length && (
              <tr><td colSpan={4} className="p-6 text-center text-muted">No cost data yet.</td></tr>
            )}
            {!sorted && (
              <tr><td colSpan={4} className="p-6 text-center text-muted">Loading…</td></tr>
            )}
          </tbody>
        </table>
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase text-muted">
            Top spenders — approximate USD
          </h2>
          {health?.dashboard_cost_id && health?.workspace_host && (
            <a
              href={`${health.workspace_host}/sql/dashboardsv3/${health.dashboard_cost_id}/published`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded border border-default px-3 py-1 text-xs hover:bg-elevated"
              title="Open the GenieWatch Cost Overview dashboard in Databricks"
            >
              <ExternalLink size={12} /> Open Lakeview dashboard
            </a>
          )}
        </div>
        {!sorted ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : sorted.length === 0 ? (
          <p className="text-sm text-muted">No cost data yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(240, sorted.length * 22)}>
            <BarChart
              data={sorted.slice(0, 25).map(s => ({
                ...s,
                shortId: s.space_id.slice(0, 12) + '…',
              }))}
              layout="vertical"
              margin={{ top: 4, right: 24, left: 8, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis type="number" tickFormatter={(v: number) => formatUsd(v)} />
              <YAxis
                type="category"
                dataKey="shortId"
                width={120}
                tick={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
              />
              <Tooltip
                cursor={{ fillOpacity: 0.05 }}
                formatter={(value, name) => {
                  const n = typeof value === 'number' ? value : Number(value)
                  return name === 'approx_usd' ? formatUsd(n) : formatInt(n)
                }}
                labelFormatter={(_label, payload) => {
                  const row = payload?.[0]?.payload as CostTopSpender | undefined
                  return row?.space_id ?? ''
                }}
              />
              <Bar dataKey="approx_usd" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>
    </div>
  )
}

function Th({
  children, onClick, active, dir, align = 'left',
}: {
  children: React.ReactNode
  onClick?: () => void
  active?: boolean
  dir?: 'asc' | 'desc'
  align?: 'left' | 'right'
}) {
  return (
    <th
      className={`px-4 py-2 ${onClick ? 'cursor-pointer select-none hover:text-fg' : ''} ${
        align === 'right' ? 'text-right' : ''
      }`}
      onClick={onClick}
    >
      {children}
      {active ? <span className="ml-1">{dir === 'asc' ? '▲' : '▼'}</span> : null}
    </th>
  )
}
