import { useState, useEffect } from 'react'

import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import * as api from '@/lib/api'
import type { FeedbackRollup } from '@/types/api'
import type { FeedbackEvent } from '@/types/api'
import type { HealthStatus } from '@/types/api'
import { formatInt, formatDate } from '@/lib/format'
import { useCachedFetch } from '@/lib/cache'
import { genieSpaceUrl, genieMessageUrl } from '@/lib/genie'
import { Badge } from '@/components/ui/badge'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'

export function Feedback() {
  const [days, setDays] = useState<number>(30)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { data: health } = useCachedFetch<HealthStatus>('health', () => api.getHealth())
  const workspaceHost = health?.workspace_host ?? null

  const { data, error } = useCachedFetch<FeedbackRollup>(
    `feedback-rollup:${days}:50`,
    () => api.getFeedbackRollup(days, 50),
    [days],
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Feedback</h1>
          <p className="text-sm text-muted">
            Workspace-wide thumbs-up / thumbs-down activity. Audit log lag is typically 1–4 hours.
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

      {error && (
        <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</Card>
      )}

      <StatBand data={data} />
      <NegativesChart data={data ?? null} />
      <FeedbackTable
        data={data ?? null}
        workspaceHost={workspaceHost}
        days={days}
        expandedId={expandedId}
        onToggleExpand={id => setExpandedId(curr => (curr === id ? null : id))}
      />
    </div>
  )
}

function StatBand({ data }: { data: FeedbackRollup | undefined }) {
  if (!data) {
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
      </div>
    )
  }
  const s = data.summary
  const pct = s.pct_positive != null ? `${(s.pct_positive * 100).toFixed(1)}%` : '—'
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard label="Total feedback" value={formatInt(s.total)} />
      <StatCard label="% positive" value={pct} />
      <StatCard label="Spaces with negatives" value={formatInt(s.spaces_with_negatives)} />
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="text-xs uppercase text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </Card>
  )
}

const CHART_COLORS = ['#f87171', '#fb923c', '#facc15', '#a3e635', '#22d3ee', '#a78bfa']
const TOP_N_CHART = 5

function NegativesChart({ data }: { data: FeedbackRollup | null }) {
  if (!data) {
    return (
      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">Negative ratings over time</h3>
        <Skeleton className="h-72 w-full" />
      </Card>
    )
  }

  const top = [...data.items]
    .sort((a, b) => b.negative - a.negative)
    .slice(0, TOP_N_CHART)
    .filter(s => s.negative > 0)

  if (top.length === 0) {
    return (
      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">Negative ratings over time</h3>
        <p className="text-sm text-muted">No negative feedback in the selected window.</p>
      </Card>
    )
  }

  // Merge per-space daily series into one wide table keyed by day.
  const dayMap = new Map<string, Record<string, number | string>>()
  for (const space of top) {
    const label = space.title || `Space ${space.space_id.slice(0, 6)}`
    for (const pt of space.daily_negatives) {
      const day = pt.day
      const row = dayMap.get(day) ?? { day }
      row[label] = pt.neg
      dayMap.set(day, row)
    }
  }
  const chartData = Array.from(dayMap.values()).sort((a, b) =>
    String(a.day).localeCompare(String(b.day)),
  )
  const seriesLabels = top.map(s => s.title || `Space ${s.space_id.slice(0, 6)}`)

  return (
    <Card className="p-4">
      <h3 className="mb-2 text-sm font-medium uppercase text-muted">Negative ratings over time</h3>
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
            <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {seriesLabels.map((label, i) => (
              <Line
                key={label}
                type="monotone"
                dataKey={label}
                stroke={CHART_COLORS[i % CHART_COLORS.length]}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

type SortKey = 'title' | 'total' | 'positive' | 'negative' | 'last_negative_at'

interface FeedbackTableProps {
  data: FeedbackRollup | null
  workspaceHost: string | null
  days: number
  expandedId: string | null
  onToggleExpand: (id: string) => void
}

function FeedbackTable({ data, workspaceHost, days, expandedId, onToggleExpand }: FeedbackTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('negative')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  if (!data) {
    return (
      <Card className="p-4 space-y-2">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
      </Card>
    )
  }
  if (data.items.length === 0) {
    return (
      <Card className="p-6 text-center text-sm text-muted">
        No feedback in the last {data.days} days.
      </Card>
    )
  }

  const dir = sortDir === 'asc' ? 1 : -1
  const sorted = [...data.items].sort((a, b) => {
    switch (sortKey) {
      case 'title':
        return ((a.title || '').localeCompare(b.title || '')) * dir
      case 'total':
        return (a.total - b.total) * dir
      case 'positive':
        return (a.positive - b.positive) * dir
      case 'negative':
        return ((a.negative - b.negative) || (a.total - b.total)) * dir
      case 'last_negative_at': {
        const av = a.last_negative_at ?? ''
        const bv = b.last_negative_at ?? ''
        return av.localeCompare(bv) * dir
      }
    }
  })

  function toggleSort(k: SortKey) {
    if (k === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(k)
      setSortDir(k === 'title' ? 'asc' : 'desc')
    }
  }

  return (
    <Card className="overflow-hidden p-0">
      <table className="w-full text-sm">
        <thead className="border-b border-default bg-elevated text-left text-xs uppercase text-muted">
          <tr>
            <Th onClick={() => toggleSort('title')} active={sortKey === 'title'} dir={sortDir}>
              Space
            </Th>
            <Th onClick={() => toggleSort('total')} active={sortKey === 'total'} dir={sortDir} align="right">
              Total
            </Th>
            <Th onClick={() => toggleSort('positive')} active={sortKey === 'positive'} dir={sortDir} align="right">
              Positive
            </Th>
            <Th onClick={() => toggleSort('negative')} active={sortKey === 'negative'} dir={sortDir} align="right">
              Negative
            </Th>
            <Th onClick={() => toggleSort('last_negative_at')} active={sortKey === 'last_negative_at'} dir={sortDir}>
              Last negative
            </Th>
            <th className="px-2 py-2 w-8" />
          </tr>
        </thead>
        <tbody>
          {sorted.map(item => {
            const isOpen = expandedId === item.space_id
            return (
              <FeedbackRow
                key={item.space_id}
                item={item}
                workspaceHost={workspaceHost}
                days={days}
                isOpen={isOpen}
                onToggle={() => onToggleExpand(item.space_id)}
              />
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}

function FeedbackRow({
  item, workspaceHost, days, isOpen, onToggle,
}: {
  item: FeedbackRollup['items'][number]
  workspaceHost: string | null
  days: number
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr className="cursor-pointer border-t border-default/50 hover:bg-elevated/50" onClick={onToggle}>
        <td className="px-4 py-2">
          <span className="inline-flex items-center gap-1">
            {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span>{item.title || <span className="text-muted">Unknown space</span>}</span>
          </span>
        </td>
        <td className="px-4 py-2 text-right tabular-nums">{formatInt(item.total)}</td>
        <td className="px-4 py-2 text-right tabular-nums text-emerald-400">{formatInt(item.positive)}</td>
        <td className="px-4 py-2 text-right tabular-nums text-red-400">{formatInt(item.negative)}</td>
        <td className="px-4 py-2 text-muted">{formatDate(item.last_negative_at)}</td>
        <td className="px-2 py-2 text-right">
          <a
            href={genieSpaceUrl(item.space_id, workspaceHost)}
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
      {isOpen && (
        <tr className="border-t border-default/30 bg-elevated/30">
          <td colSpan={6} className="px-4 py-3">
            <FeedbackDrillDown spaceId={item.space_id} days={days} workspaceHost={workspaceHost} />
          </td>
        </tr>
      )}
    </>
  )
}

function FeedbackDrillDown({
  spaceId, days, workspaceHost,
}: {
  spaceId: string
  days: number
  workspaceHost: string | null
}) {
  const [events, setEvents] = useState<FeedbackEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setEvents(null)
    setError(null)
    api.getSpaceFeedback(spaceId, days, 200).then(
      rows => { if (!cancelled) setEvents(rows) },
      e => { if (!cancelled) setError(String(e?.message ?? e)) },
    )
    return () => { cancelled = true }
  }, [spaceId, days])

  if (error) return <p className="text-sm text-red-400">Could not load feedback: {error}</p>
  if (events === null) return <p className="text-sm text-muted">Loading…</p>
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted">
        No individual events visible (audit log lag is 1–4h, or this space has no comment-bearing events).
      </p>
    )
  }

  return (
    <ul className="space-y-2 text-sm">
      {events.map((f, i) => {
        const url = genieMessageUrl(
          spaceId,
          f.conversation_id ?? null,
          f.message_id ?? null,
          workspaceHost,
        )
        const isPos = (f.rating || '').toUpperCase() === 'POSITIVE'
        return (
          <li key={i} className="rounded border border-default p-2">
            <div className="flex items-center justify-between">
              <Badge
                className={
                  isPos
                    ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                    : 'bg-red-500/20 text-red-400 border-red-500/30'
                }
              >
                {f.rating || '?'}
              </Badge>
              <div className="flex items-center gap-2 text-xs text-muted">
                <span>{formatDate(f.event_time)} · {f.user_email || '?'}</span>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  title="Open in Databricks Genie"
                  className="inline-flex items-center hover:text-fg"
                >
                  <ExternalLink size={12} />
                </a>
              </div>
            </div>
            {f.comment && <p className="mt-1 text-muted">{f.comment}</p>}
          </li>
        )
      })}
    </ul>
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
