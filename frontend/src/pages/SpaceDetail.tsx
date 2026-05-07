import { useEffect, useState } from 'react'
import { ArrowLeft, AlertCircle, Info } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import * as api from '@/lib/api'
import type {
  CostRollup, EvalSummary, ResourceUsage, SpaceSummary, UsageRollup,
} from '@/types/api'
import { formatDate, formatInt, formatMs, formatUsd, formatDay } from '@/lib/format'

interface Props {
  spaceId: string
  onBack: () => void
  onOpenSettings: () => void
}

export function SpaceDetail({ spaceId, onBack, onOpenSettings }: Props) {
  const [space, setSpace] = useState<SpaceSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    api.getSpace(spaceId).then(setSpace).catch(e => setError(String(e)))
  }, [spaceId])

  return (
    <div className="space-y-4">
      <Button variant="ghost" onClick={onBack} className="gap-1">
        <ArrowLeft size={16} /> Back to spaces
      </Button>

      {error && (
        <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</Card>
      )}

      {space && (
        <>
          <div>
            <h1 className="text-2xl font-semibold">{space.title || '(untitled)'}</h1>
            <p className="font-mono text-xs text-muted">{space.space_id}</p>
            {space.description && <p className="mt-2 max-w-2xl text-sm text-muted">{space.description}</p>}
          </div>

          <Tabs defaultValue="overview" className="space-y-4">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="usage">Usage</TabsTrigger>
              <TabsTrigger value="cost">Cost</TabsTrigger>
              <TabsTrigger value="resources">Resources</TabsTrigger>
              <TabsTrigger value="evals">Evals</TabsTrigger>
            </TabsList>

            <TabsContent value="overview"><Overview space={space} /></TabsContent>
            <TabsContent value="usage"><UsageTab spaceId={spaceId} /></TabsContent>
            <TabsContent value="cost"><CostTab spaceId={spaceId} /></TabsContent>
            <TabsContent value="resources"><ResourcesTab spaceId={spaceId} /></TabsContent>
            <TabsContent value="evals"><EvalsTab spaceId={spaceId} onOpenSettings={onOpenSettings} /></TabsContent>
          </Tabs>
        </>
      )}
    </div>
  )
}

function Overview({ space }: { space: SpaceSummary }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card className="p-4">
        <h2 className="mb-2 text-sm font-medium uppercase text-muted">Owner</h2>
        <p className="font-medium">{space.owner_email || '—'}</p>
      </Card>
      <Card className="p-4">
        <h2 className="mb-2 text-sm font-medium uppercase text-muted">Permissions</h2>
        <div className="space-y-1">
          {space.permissions.length === 0 && <p className="text-sm text-muted">No ACL data.</p>}
          {space.permissions.map((p, i) => (
            <div key={i} className="flex items-center justify-between text-sm">
              <span className="truncate">{p.principal || '?'}</span>
              <Badge>{p.permission_level || '—'}</Badge>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function UsageTab({ spaceId }: { spaceId: string }) {
  const [data, setData] = useState<UsageRollup | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.getSpaceUsage(spaceId, 30).then(setData).catch(e => setErr(String(e)))
  }, [spaceId])

  if (err) return <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{err}</Card>
  if (!data) return <Card className="p-4 text-sm text-muted">Loading…</Card>

  return (
    <div className="space-y-4">
      <Card className="border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-400">
        <Info className="mr-1 inline" size={14} />
        Feedback events appear with up to 4 hours of audit-log latency. Query metrics typically lag 5–15 min.
      </Card>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Queries (30d)" value={formatInt(data.total_queries)} />
        <Stat label="Errors (30d)" value={formatInt(data.total_errors)} />
        <Stat label="Distinct users" value={formatInt(data.distinct_users)} />
        <Stat
          label="Feedback"
          value={
            <span className="space-x-1">
              <span className="text-emerald-400">+{data.feedback.positive}</span>
              <span className="text-muted">/</span>
              <span className="text-red-400">−{data.feedback.negative}</span>
            </span>
          }
        />
      </div>

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">Daily queries</h3>
        <SimpleBars
          data={data.time_series.map(p => ({ x: formatDay(p.day), y: p.queries }))}
        />
      </Card>

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">Latency p95</h3>
        <SimpleBars
          data={data.time_series.map(p => ({ x: formatDay(p.day), y: p.p95_ms || 0 }))}
          formatY={formatMs as (n: number) => string}
        />
      </Card>

      {data.feedback.sample.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium uppercase text-muted">Recent feedback</h3>
          <ul className="space-y-2 text-sm">
            {data.feedback.sample.map((f, i) => (
              <li key={i} className="rounded border border-default p-2">
                <div className="flex items-center justify-between">
                  <Badge
                    className={
                      (f.rating || '').toUpperCase() === 'POSITIVE'
                        ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                        : 'bg-red-500/20 text-red-400 border-red-500/30'
                    }
                  >
                    {f.rating || '?'}
                  </Badge>
                  <span className="text-xs text-muted">
                    {formatDate(f.event_time)} · {f.user_email || '?'}
                  </span>
                </div>
                {f.comment && <p className="mt-1 text-muted">{f.comment}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.conversations.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-medium uppercase text-muted">
            Recent conversations <span className="text-xs">(cached)</span>
          </h3>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted">
              <tr>
                <th className="py-1">User</th>
                <th>Messages</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {data.conversations.map(c => (
                <tr key={c.conversation_id} className="border-t border-default/50">
                  <td className="py-1.5">{c.user_email || '—'}</td>
                  <td>{c.message_count}</td>
                  <td className="text-muted">{formatDate(c.last_message_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function CostTab({ spaceId }: { spaceId: string }) {
  const [data, setData] = useState<CostRollup | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.getSpaceCost(spaceId, 30).then(setData).catch(e => setErr(String(e)))
  }, [spaceId])

  if (err) return <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{err}</Card>
  if (!data) return <Card className="p-4 text-sm text-muted">Loading…</Card>

  return (
    <div className="space-y-4">
      <Card className="border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-400">
        <AlertCircle className="mr-1 inline" size={14} />
        Cost is approximate. Databricks bills warehouses, not queries — we apportion warehouse-day cost
        by this space's share of warehouse query duration. See <code>docs/apportionment-caveat.md</code>.
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Queries (30d)" value={formatInt(data.total_query_count)} />
        <Stat label="Approx cost (30d)" value={formatUsd(data.total_approx_usd)} />
        <Stat label="DBUs (30d)" value={data.total_approx_dbus != null ? data.total_approx_dbus.toFixed(2) : '—'} />
      </div>

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">Daily approx cost (USD)</h3>
        <SimpleBars
          data={data.time_series.map(p => ({ x: formatDay(p.day), y: p.approx_usd || 0 }))}
          formatY={(v: number) => formatUsd(v)}
        />
      </Card>

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-medium uppercase text-muted">By warehouse</h3>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-muted">
            <tr>
              <th className="py-1">Warehouse</th>
              <th>Queries</th>
              <th>Approx USD</th>
            </tr>
          </thead>
          <tbody>
            {data.by_warehouse.map(w => (
              <tr key={w.warehouse_id} className="border-t border-default/50">
                <td className="py-1.5 font-mono text-xs">{w.warehouse_id || '(unknown)'}</td>
                <td>{formatInt(w.query_count)}</td>
                <td>{formatUsd(w.approx_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function ResourcesTab({ spaceId }: { spaceId: string }) {
  const [data, setData] = useState<ResourceUsage[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.getSpaceResources(spaceId, 30).then(setData).catch(e => setErr(String(e)))
  }, [spaceId])

  if (err) return <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{err}</Card>
  if (!data) return <Card className="p-4 text-sm text-muted">Loading…</Card>

  return (
    <Card className="overflow-hidden p-0">
      <table className="w-full text-sm">
        <thead className="border-b border-default bg-elevated text-left text-xs uppercase text-muted">
          <tr>
            <th className="px-4 py-2">Resource</th>
            <th className="px-4 py-2">Kind</th>
            <th className="px-4 py-2">Source</th>
            <th className="px-4 py-2 text-right">Queries (30d)</th>
            <th className="px-4 py-2">Last used</th>
          </tr>
        </thead>
        <tbody>
          {data.map(r => (
            <tr key={r.full_name} className="border-t border-default/50">
              <td className="px-4 py-2 font-mono text-xs">{r.full_name}</td>
              <td className="px-4 py-2"><Badge>{r.kind}</Badge></td>
              <td className="px-4 py-2">
                <Badge
                  className={
                    r.source === 'both'
                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                      : r.source === 'configured'
                        ? 'bg-blue-500/20 text-blue-400 border-blue-500/30'
                        : 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                  }
                >
                  {r.source}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{formatInt(r.query_count)}</td>
              <td className="px-4 py-2 text-muted">{formatDate(r.last_used)}</td>
            </tr>
          ))}
          {!data.length && (
            <tr><td colSpan={5} className="p-6 text-center text-muted">No resources detected.</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  )
}

function EvalsTab({ spaceId, onOpenSettings }: { spaceId: string; onOpenSettings: () => void }) {
  const [data, setData] = useState<EvalSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.getSpaceEvals(spaceId).then(setData).catch(e => setErr(String(e)))
  }, [spaceId])

  if (err) return <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{err}</Card>
  if (!data) return <Card className="p-4 text-sm text-muted">Loading…</Card>

  if (!data.experiment_id) {
    return (
      <Card className="p-6 text-center">
        <h3 className="mb-2 text-lg font-medium">No MLflow experiment mapped</h3>
        <p className="mb-4 text-sm text-muted">
          Map this space to an MLflow experiment in Settings to surface eval runs.
        </p>
        <Button onClick={onOpenSettings}>Open Settings</Button>
      </Card>
    )
  }

  if (data.permission_denied) {
    return (
      <Card className="border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-400">
        Mapped experiment <code>{data.experiment_id}</code> exists but the app SP cannot read it.
        Grant <code>CAN_READ</code> to the SP and refresh.
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <Card className="p-4">
        <p className="text-xs uppercase text-muted">Experiment</p>
        <p className="font-medium">{data.experiment_name}</p>
        <p className="font-mono text-xs text-muted">{data.experiment_id}</p>
      </Card>
      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-default bg-elevated text-left text-xs uppercase text-muted">
            <tr>
              <th className="px-4 py-2">Run</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Started</th>
              <th className="px-4 py-2">Top metrics</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map(r => (
              <tr key={r.run_id} className="border-t border-default/50">
                <td className="px-4 py-2 font-mono text-xs">{r.run_name || r.run_id.slice(0, 12)}…</td>
                <td className="px-4 py-2"><Badge>{r.status || '—'}</Badge></td>
                <td className="px-4 py-2 text-muted">{r.start_time ? new Date(r.start_time).toLocaleString() : '—'}</td>
                <td className="px-4 py-2 text-xs">
                  {Object.entries(r.metrics).slice(0, 3).map(([k, v]) => (
                    <span key={k} className="mr-2">
                      <span className="text-muted">{k}:</span> {Number(v).toFixed(3)}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
            {!data.runs.length && (
              <tr><td colSpan={4} className="p-6 text-center text-muted">No runs in this experiment.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-xs uppercase text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </Card>
  )
}

function SimpleBars({
  data, formatY,
}: { data: { x: string; y: number }[]; formatY?: (v: number) => string }) {
  const max = Math.max(1, ...data.map(d => d.y))
  return (
    <div className="space-y-1">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 text-muted">{d.x}</span>
          <div className="h-3 flex-1 rounded bg-elevated">
            <div
              className="h-3 rounded bg-blue-500"
              style={{ width: `${(d.y / max) * 100}%` }}
            />
          </div>
          <span className="w-16 shrink-0 text-right tabular-nums">
            {formatY ? formatY(d.y) : d.y.toLocaleString()}
          </span>
        </div>
      ))}
      {!data.length && <p className="text-xs text-muted">No data.</p>}
    </div>
  )
}
