import { useState } from 'react'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import * as api from '@/lib/api'
import type { FeedbackRollup } from '@/types/api'
import { formatInt } from '@/lib/format'
import { useCachedFetch } from '@/lib/cache'

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
