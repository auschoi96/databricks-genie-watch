import { useState } from 'react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import * as api from '@/lib/api'
import type { FeedbackRollup } from '@/types/api'
import { formatInt } from '@/lib/format'
import { useCachedFetch } from '@/lib/cache'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'

export function Feedback() {
  const [days, setDays] = useState<number>(30)

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
