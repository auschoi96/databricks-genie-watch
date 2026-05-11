# Genie Feedback Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a workspace-wide Feedback page to GenieWatch surfacing per-space thumbs-up/down counts, a daily negative-rate trend chart, a stat band, and per-space drill-down with deep-links into the source Genie conversations.

**Architecture:** One new backend endpoint (`/api/feedback/rollup`) backed by a single SQL query against `system.access.audit`. One new frontend page that consumes the rollup endpoint plus the *existing* `/api/spaces/{id}/feedback` for lazy drill-down. No new caching layer, no new dependencies, no `app.yaml` changes.

**Tech Stack:** FastAPI + Pydantic v2 (backend), React 19 + recharts + Tailwind + the existing `components/ui/*` (frontend), `system.access.audit` system table read as the SP. Spec: `docs/superpowers/specs/2026-05-11-genie-feedback-feature-design.md`.

---

## Pre-flight

- [ ] **Confirm clean branch state**

```bash
cd ~/Repos/Personal/databricks-genie-watch
git checkout main && git pull
git checkout -b feedback-overview
git status
```
Expected: on `feedback-overview`, clean working tree.

---

## Task 1: Backend SQL + service function

**Files:**
- Modify: `backend/services/system_tables.py` (append at end of the `─── Feedback (audit log) ───` section, after `feedback_summary_all_spaces` around line 541)

- [ ] **Step 1.1: Add the rollup SQL constant and the wrapper function**

Append to `backend/services/system_tables.py` after the existing `feedback_summary_all_spaces` definition:

```python
_FEEDBACK_ROLLUP_SQL = """
WITH events AS (
    SELECT request_params.space_id AS space_id,
           request_params.feedback_rating AS rating,
           event_time
    FROM system.access.audit
    WHERE service_name = 'aibiGenie'
      AND action_name = 'updateConversationMessageFeedback'
      AND event_time >= current_date() - :days
), agg AS (
    SELECT space_id,
           COUNT(*) AS total,
           SUM(CASE WHEN rating = 'POSITIVE' THEN 1 ELSE 0 END) AS positive,
           SUM(CASE WHEN rating = 'NEGATIVE' THEN 1 ELSE 0 END) AS negative,
           MAX(CASE WHEN rating = 'NEGATIVE' THEN event_time END) AS last_negative_at
    FROM events
    GROUP BY 1
), daily AS (
    SELECT space_id,
           date_trunc('day', event_time) AS day,
           SUM(CASE WHEN rating = 'NEGATIVE' THEN 1 ELSE 0 END) AS neg
    FROM events
    GROUP BY 1, 2
), daily_arr AS (
    SELECT space_id,
           array_sort(collect_list(struct(day, neg))) AS daily_negatives
    FROM daily
    GROUP BY 1
), workspace_summary AS (
    SELECT COUNT(*) AS ws_total,
           SUM(CASE WHEN rating = 'POSITIVE' THEN 1 ELSE 0 END) AS ws_positive,
           SUM(CASE WHEN rating = 'NEGATIVE' THEN 1 ELSE 0 END) AS ws_negative,
           COUNT(DISTINCT CASE WHEN rating = 'NEGATIVE' THEN space_id END) AS ws_spaces_with_negatives
    FROM events
)
SELECT ws.ws_total, ws.ws_positive, ws.ws_negative, ws.ws_spaces_with_negatives,
       a.space_id, a.total, a.positive, a.negative, a.last_negative_at,
       d.daily_negatives
FROM workspace_summary ws CROSS JOIN agg a
LEFT JOIN daily_arr d USING (space_id)
ORDER BY a.negative DESC, a.total DESC
LIMIT :limit
"""


def feedback_rollup(days: int = 30, limit: int = 50) -> list[dict[str, Any]]:
    """Per-space feedback aggregates + per-space daily negative time series.

    Each returned row carries duplicated workspace-wide totals (ws_*) so the
    caller can derive the page's stat band without a second round-trip. The
    duplication is ~32 bytes per row — negligible compared to the cost of
    a second statement execution.

    `daily_negatives` arrives as a JSON-encoded array of {day, neg} structs;
    the caller is responsible for json.loads-ing it.
    """
    return _run(_FEEDBACK_ROLLUP_SQL, [
        _p("days", days, "INT"),
        _p("limit", limit, "INT"),
    ])
```

- [ ] **Step 1.2: Verify the module still imports**

```bash
cd ~/Repos/Personal/databricks-genie-watch
uv run python -c "from backend.services.system_tables import feedback_rollup; print('ok')"
```
Expected: `ok`

- [ ] **Step 1.3: Commit**

```bash
git add backend/services/system_tables.py
git commit -m "feedback: add feedback_rollup SQL + service wrapper"
```

---

## Task 2: Pydantic models + TS type mirror

**Files:**
- Modify: `backend/models.py` (append after `FeedbackSummary` around line 103)
- Modify: `frontend/src/types/api.ts` (append in the feedback section, mirroring the new types)

- [ ] **Step 2.1: Add Pydantic models**

Append to `backend/models.py` after the existing `FeedbackSummary` class:

```python
class FeedbackDailyPoint(BaseModel):
    day: date
    neg: int


class FeedbackRollupItem(BaseModel):
    space_id: str
    title: Optional[str] = None
    total: int
    positive: int
    negative: int
    last_negative_at: Optional[datetime] = None
    daily_negatives: list[FeedbackDailyPoint] = Field(default_factory=list)


class FeedbackWorkspaceSummary(BaseModel):
    total: int
    positive: int
    negative: int
    pct_positive: Optional[float] = None  # positive / total, None when total == 0
    spaces_with_negatives: int


class FeedbackRollup(BaseModel):
    days: int
    summary: FeedbackWorkspaceSummary
    items: list[FeedbackRollupItem] = Field(default_factory=list)
```

Note: `date` may need to be imported. Check the top of `models.py` for `from datetime import date, datetime` — if `date` isn't already imported, add it.

- [ ] **Step 2.2: Verify models import**

```bash
cd ~/Repos/Personal/databricks-genie-watch
uv run python -c "from backend.models import FeedbackRollup, FeedbackRollupItem, FeedbackWorkspaceSummary, FeedbackDailyPoint; print('ok')"
```
Expected: `ok`

- [ ] **Step 2.3: Mirror types in TypeScript**

Open `frontend/src/types/api.ts`, find the existing `FeedbackEvent` / `FeedbackSummary` interfaces, and add below them:

```ts
export interface FeedbackDailyPoint {
  day: string  // ISO date string from the API
  neg: number
}

export interface FeedbackRollupItem {
  space_id: string
  title: string | null
  total: number
  positive: number
  negative: number
  last_negative_at: string | null
  daily_negatives: FeedbackDailyPoint[]
}

export interface FeedbackWorkspaceSummary {
  total: number
  positive: number
  negative: number
  pct_positive: number | null
  spaces_with_negatives: number
}

export interface FeedbackRollup {
  days: number
  summary: FeedbackWorkspaceSummary
  items: FeedbackRollupItem[]
}
```

- [ ] **Step 2.4: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output (clean).

- [ ] **Step 2.5: Commit**

```bash
git add backend/models.py frontend/src/types/api.ts
git commit -m "feedback: add Pydantic + TS types for rollup payload"
```

---

## Task 3: Backend router + register in main

**Files:**
- Create: `backend/routers/feedback.py`
- Modify: `backend/main.py` (add import + `app.include_router(feedback_router)`)

- [ ] **Step 3.1: Create the new router file**

Create `backend/routers/feedback.py`:

```python
"""Feedback rollup router.

Exposes a single workspace-wide aggregate over system.access.audit, used by
the Feedback page. Per-space drill-down lives under /api/spaces/{id}/feedback
(see routers/usage.py) — this router is the workspace-wide front door.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.models import (
    FeedbackDailyPoint,
    FeedbackRollup,
    FeedbackRollupItem,
    FeedbackWorkspaceSummary,
)
from backend.services import lakebase, system_tables

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback")


def _parse_daily_negatives(raw: Any) -> list[FeedbackDailyPoint]:
    """The SQL returns the daily_negatives column as a JSON-encoded array of
    {day, neg} structs. Parse it into a typed list, tolerating None / empty.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Could not parse daily_negatives: %r", raw[:200])
            return []
    if not isinstance(raw, list):
        return []
    points: list[FeedbackDailyPoint] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        day = entry.get("day")
        neg = entry.get("neg")
        if day is None or neg is None:
            continue
        try:
            points.append(FeedbackDailyPoint(day=_to_date(day), neg=int(neg)))
        except (ValueError, TypeError):
            continue
    return points


def _to_date(v: Any) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()


def _to_datetime(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/rollup")
async def get_rollup(days: int = 30, limit: int = 50) -> dict:
    """Return workspace-wide feedback summary + per-space rollup."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    try:
        rows = await asyncio.to_thread(system_tables.feedback_rollup, days, limit)
    except Exception as e:
        logger.exception("feedback_rollup query failed")
        raise HTTPException(status_code=502, detail=f"system table query failed: {e}")

    # Look up space titles once (cached list, then dict for O(1) lookup).
    try:
        cached = await lakebase.list_cached_spaces()
        titles = {s["space_id"]: s.get("title") for s in cached}
    except Exception as e:
        logger.warning("space-cache lookup failed; titles will be missing: %s", e)
        titles = {}

    if not rows:
        return FeedbackRollup(
            days=days,
            summary=FeedbackWorkspaceSummary(
                total=0, positive=0, negative=0, pct_positive=None, spaces_with_negatives=0,
            ),
            items=[],
        ).model_dump(mode="json")

    # All rows share the same ws_* fields (CROSS JOIN with 1-row summary).
    ws_total = int(rows[0].get("ws_total") or 0)
    ws_positive = int(rows[0].get("ws_positive") or 0)
    ws_negative = int(rows[0].get("ws_negative") or 0)
    ws_spaces_neg = int(rows[0].get("ws_spaces_with_negatives") or 0)
    pct_positive = (ws_positive / ws_total) if ws_total > 0 else None

    items: list[FeedbackRollupItem] = []
    for r in rows:
        space_id = str(r.get("space_id") or "")
        if not space_id:
            continue
        items.append(FeedbackRollupItem(
            space_id=space_id,
            title=titles.get(space_id),
            total=int(r.get("total") or 0),
            positive=int(r.get("positive") or 0),
            negative=int(r.get("negative") or 0),
            last_negative_at=_to_datetime(r.get("last_negative_at")),
            daily_negatives=_parse_daily_negatives(r.get("daily_negatives")),
        ))

    return FeedbackRollup(
        days=days,
        summary=FeedbackWorkspaceSummary(
            total=ws_total,
            positive=ws_positive,
            negative=ws_negative,
            pct_positive=pct_positive,
            spaces_with_negatives=ws_spaces_neg,
        ),
        items=items,
    ).model_dump(mode="json")
```

- [ ] **Step 3.2: Register the router in `backend/main.py`**

In `backend/main.py`, find the existing router imports (around line 34-40) and add:

```python
from backend.routers.feedback import router as feedback_router
```

Then find the existing `app.include_router(...)` block (around line 104-111) and add:

```python
app.include_router(feedback_router)
```

- [ ] **Step 3.3: Verify the route is registered**

```bash
cd ~/Repos/Personal/databricks-genie-watch
uv run python -c "
from backend.main import app
print([r.path for r in app.routes if hasattr(r, 'path') and '/feedback' in r.path])
"
```
Expected output contains: `/api/feedback/rollup`

- [ ] **Step 3.4: Commit**

```bash
git add backend/routers/feedback.py backend/main.py
git commit -m "feedback: add /api/feedback/rollup router"
```

---

## Task 4: Frontend API helper + deep-link helper

**Files:**
- Modify: `frontend/src/lib/api.ts` (append after the Dashboards section added in the prior PR)
- Modify: `frontend/src/lib/genie.ts` (append `genieMessageUrl`)

- [ ] **Step 4.1: Add `getFeedbackRollup` to `lib/api.ts`**

At the top of `frontend/src/lib/api.ts`, add `FeedbackRollup` to the existing type import block:

```ts
import type {
  // ...existing imports...
  FeedbackRollup,
} from '@/types/api'
```

Then append at the end of the file:

```ts
// ── Feedback ────────────────────────────────────────────────────────────────

export const getFeedbackRollup = (days = 30, limit = 50) =>
  fetchJson<FeedbackRollup>(`/feedback/rollup?days=${days}&limit=${limit}`)
```

- [ ] **Step 4.2: Add `genieMessageUrl` to `lib/genie.ts`**

Append to `frontend/src/lib/genie.ts`:

```ts
/** Build a Databricks deep-link to a specific Genie conversation / message.
 *
 *  Falls back to the space-level URL when conversation_id is missing.
 *  The exact query-param format is best-effort — the Genie UI may evolve.
 *  Tested empirically against the deployed workspace before relying on it
 *  for navigation.
 */
export function genieMessageUrl(
  spaceId: string,
  conversationId: string | null,
  messageId: string | null,
  workspaceHost: string | null,
): string {
  const base = genieSpaceUrl(spaceId, workspaceHost)
  if (!conversationId) return base
  const qs = new URLSearchParams({ conversation_id: conversationId })
  if (messageId) qs.set('message_id', messageId)
  return `${base}?${qs.toString()}`
}
```

- [ ] **Step 4.3: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/genie.ts
git commit -m "feedback: add getFeedbackRollup + genieMessageUrl helpers"
```

---

## Task 5a: Feedback page skeleton + stat band

**Files:**
- Create: `frontend/src/pages/Feedback.tsx`

- [ ] **Step 5a.1: Create the page with header, time window, stat band, and fetch**

Create `frontend/src/pages/Feedback.tsx`:

```tsx
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

function StatBand({ data }: { data: FeedbackRollup | null }) {
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
```

- [ ] **Step 5a.2: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 5a.3: Commit**

```bash
git add frontend/src/pages/Feedback.tsx
git commit -m "feedback: page skeleton with stat band"
```

---

## Task 5b: Add the trend chart

**Files:**
- Modify: `frontend/src/pages/Feedback.tsx`

- [ ] **Step 5b.1: Add the chart import and component**

In `frontend/src/pages/Feedback.tsx`, add the recharts import at the top:

```tsx
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
```

Add the chart component below `StatBand` and `StatCard`:

```tsx
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
```

Then in the `Feedback` component's JSX, render the chart below `<StatBand>`:

```tsx
<StatBand data={data} />
<NegativesChart data={data} />
```

- [ ] **Step 5b.2: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 5b.3: Commit**

```bash
git add frontend/src/pages/Feedback.tsx
git commit -m "feedback: add negatives-over-time chart"
```

---

## Task 5c: Add the sortable table

**Files:**
- Modify: `frontend/src/pages/Feedback.tsx`

- [ ] **Step 5c.1: Add the table component below `NegativesChart`**

```tsx
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'

import { formatDate } from '@/lib/format'
import { genieSpaceUrl } from '@/lib/genie'

type SortKey = 'title' | 'total' | 'positive' | 'negative' | 'last_negative_at'

interface TableProps {
  data: FeedbackRollup | null
  workspaceHost: string | null
  expandedId: string | null
  onToggleExpand: (id: string) => void
}

function FeedbackTable({ data, workspaceHost, expandedId, onToggleExpand }: TableProps) {
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
  item, workspaceHost, isOpen, onToggle,
}: {
  item: FeedbackRollup['items'][number]
  workspaceHost: string | null
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
            {/* Drill-down panel is added in Task 5d. */}
            <p className="text-sm text-muted">Loading…</p>
          </td>
        </tr>
      )}
    </>
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
```

- [ ] **Step 5c.2: Wire the table into the `Feedback` component**

Update the top-level `Feedback` component to:
- Track `expandedId` state.
- Fetch the `workspaceHost` from `/api/settings/health` (the existing `HealthStatus` payload has it — same pattern as `CostExplorer.tsx`).
- Render `<FeedbackTable>` below the chart.

Replace the existing `Feedback` body with:

```tsx
import type { HealthStatus } from '@/types/api'

// inside the Feedback() component:
const [days, setDays] = useState<number>(30)
const [expandedId, setExpandedId] = useState<string | null>(null)

const { data, error } = useCachedFetch<FeedbackRollup>(
  `feedback-rollup:${days}:50`,
  () => api.getFeedbackRollup(days, 50),
  [days],
)
const { data: health } = useCachedFetch<HealthStatus>('health', () => api.getHealth())
const workspaceHost = health?.workspace_host ?? null

return (
  <div className="space-y-4">
    {/* header + selector unchanged */}
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
    <NegativesChart data={data} />
    <FeedbackTable
      data={data}
      workspaceHost={workspaceHost}
      expandedId={expandedId}
      onToggleExpand={id => setExpandedId(curr => (curr === id ? null : id))}
    />
  </div>
)
```

- [ ] **Step 5c.3: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 5c.4: Commit**

```bash
git add frontend/src/pages/Feedback.tsx
git commit -m "feedback: add sortable per-space table"
```

---

## Task 5d: Lazy-load drill-down with deep-links

**Files:**
- Modify: `frontend/src/pages/Feedback.tsx`

- [ ] **Step 5d.1: Add the drill-down panel and replace the placeholder**

In `Feedback.tsx`, add:

```tsx
import { useEffect, useState } from 'react'
import type { FeedbackEvent } from '@/types/api'
import { genieMessageUrl } from '@/lib/genie'
import { Badge } from '@/components/ui/badge'

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
```

Then in `FeedbackRow`, replace the `Loading…` placeholder cell with the real drill-down:

```tsx
{isOpen && (
  <tr className="border-t border-default/30 bg-elevated/30">
    <td colSpan={6} className="px-4 py-3">
      <FeedbackDrillDown spaceId={item.space_id} days={days} workspaceHost={workspaceHost} />
    </td>
  </tr>
)}
```

Note: `FeedbackRow` needs `days` and `workspaceHost` passed in — update its props and the `FeedbackTable` call site to thread them through.

- [ ] **Step 5d.2: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 5d.3: Commit**

```bash
git add frontend/src/pages/Feedback.tsx
git commit -m "feedback: lazy-load drill-down with deep-links"
```

---

## Task 6: Wire the nav entry in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 6.1: Add the route + nav button**

Update `frontend/src/App.tsx`:

1. Add the import near the other page imports:

```tsx
import { Feedback } from './pages/Feedback'
import { MessageSquare } from 'lucide-react'
```

2. Add `'feedback'` to the `View` union type:

```tsx
type View =
  | { kind: 'spaces' }
  | { kind: 'space-detail'; spaceId: string }
  | { kind: 'resources' }
  | { kind: 'cost' }
  | { kind: 'feedback' }
  | { kind: 'settings' }
```

3. Update the `Header`'s `active` type union and `onNavigate` arg type to include `'feedback'`. Add the nav item between `resources` and `settings`:

```tsx
const items: Array<{ kind: typeof active; label: string; icon: React.ReactNode }> = [
  { kind: 'spaces', label: 'Spaces', icon: <LayoutDashboard size={16} /> },
  { kind: 'cost', label: 'Cost', icon: <DollarSign size={16} /> },
  { kind: 'resources', label: 'Resources', icon: <Database size={16} /> },
  { kind: 'feedback', label: 'Feedback', icon: <MessageSquare size={16} /> },
  { kind: 'settings', label: 'Settings', icon: <SettingsIcon size={16} /> },
]
```

4. Extend the `onNavigate` callback's view switch:

```tsx
onNavigate={kind => {
  if (kind === 'spaces') setView({ kind: 'spaces' })
  else if (kind === 'resources') setView({ kind: 'resources' })
  else if (kind === 'cost') setView({ kind: 'cost' })
  else if (kind === 'feedback') setView({ kind: 'feedback' })
  else if (kind === 'settings') setView({ kind: 'settings' })
}}
```

5. Add the route rendering line in the `<main>`:

```tsx
{view.kind === 'feedback' && <Feedback />}
```

- [ ] **Step 6.2: Verify TypeScript builds**

```bash
cd ~/Repos/Personal/databricks-genie-watch/frontend
npx tsc -b
```
Expected: no output.

- [ ] **Step 6.3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feedback: wire Feedback tab in App nav"
```

---

## Task 7: Deploy to the FEVM workspace and smoke-test

**Files:** none (deploy-only)

- [ ] **Step 7.1: Confirm `.env.deploy` still points at the FEVM**

```bash
cd ~/Repos/Personal/databricks-genie-watch
cat .env.deploy
```
Expected:
```
WATCH_DEPLOY_PROFILE=fevm-stable-ekaiik
WATCH_APP_NAME=genie-watch
WATCH_WAREHOUSE_ID=fd0836278b403a0e
...
```

- [ ] **Step 7.2: Run a code-only deploy**

```bash
cd ~/Repos/Personal/databricks-genie-watch
./scripts/deploy.sh --update 2>&1 | tail -40
```
Expected end state: `Deploy complete!` and `State: SUCCEEDED`.

- [ ] **Step 7.3: Open the app and verify the Feedback page**

Open `https://genie-watch-7474645318453588.aws.databricksapps.com` in Chrome. Click the new **Feedback** tab.

Expected:
- Header reads "Feedback", with the time-window selector top-right.
- Stat band shows 3 cards (Total / % positive / Spaces with negatives), populated or showing 0.
- "Negative ratings over time" panel either renders a line chart or the empty-state message ("No negative feedback in the selected window").
- "Spaces by feedback" table either lists rows or shows "No feedback in the last 30 days."
- Time-window selector switches between 7 / 30 / 90 days; spinner shows during fetch.

- [ ] **Step 7.4: If real feedback exists on this workspace, smoke-test the drill-down**

Click a table row. Expected:
- Row expands inline.
- "Loading…" appears, then a list of feedback events (or the audit-lag message).
- Per-event `↗` deep-link opens a new tab to Databricks Genie at the right space (and conversation, if the URL format guess is correct).

If `genieMessageUrl` produces a URL that doesn't land on the conversation, capture the actual Genie URL format from the Databricks UI and update `frontend/src/lib/genie.ts`. Commit any fix.

- [ ] **Step 7.5: Check the app logs for errors**

```bash
databricks apps logs genie-watch --profile fevm-stable-ekaiik 2>&1 | grep -E "ERROR|Traceback|feedback" | tail -30
```
Expected: no errors related to `feedback_rollup`. The `/api/feedback/rollup` request should show as a clean 200 in access logs.

---

## Task 8: Bundle the spec doc and open the PR

**Files:**
- `docs/superpowers/specs/2026-05-11-genie-feedback-feature-design.md` (already on disk, uncommitted)

- [ ] **Step 8.1: Stage and commit the spec alongside the implementation**

```bash
cd ~/Repos/Personal/databricks-genie-watch
git add docs/superpowers/specs/2026-05-11-genie-feedback-feature-design.md \
        docs/superpowers/plans/2026-05-11-genie-feedback-feature.md
git commit -m "feedback: design spec + implementation plan"
```

- [ ] **Step 8.2: Push the branch**

```bash
git push -u origin feedback-overview 2>&1 | tail -5
```
Expected: `set up to track 'origin/feedback-overview'`.

- [ ] **Step 8.3: Open the PR**

```bash
cd ~/Repos/Personal/databricks-genie-watch
gh pr create --title "Feedback: workspace-wide overview page with drill-down" --body "$(cat <<'EOF'
## Summary

Adds a new **Feedback** tab to GenieWatch showing workspace-wide thumbs-up / thumbs-down activity.

- **Stat band:** total feedback events, % positive, # spaces with at least one negative.
- **Trend chart:** daily negative-rating count for the top 5 spaces in the window.
- **Sortable table:** per-space totals + positive/negative counts + last-negative timestamp.
- **Drill-down:** clicking a row lazy-loads the existing `/api/spaces/{id}/feedback` endpoint to show individual events with user comments and a per-event deep-link back to the source Genie conversation.

Single new endpoint (`GET /api/feedback/rollup`), single SQL query against `system.access.audit`. No new dependencies, no `app.yaml` changes, no new permissions to grant.

## Test plan

- [x] Backend imports clean (`uv run python -c "from backend.main import app"`).
- [x] Frontend type-check clean (`npx tsc -b`).
- [x] Deployed to FEVM workspace `fevm-stable-ekaiik` via `./scripts/deploy.sh --update`. Page renders, time-window selector works, empty state shows correctly.
- [ ] Smoke-test on a workspace with real Genie feedback traffic: chart shape, table sort, drill-down expand, per-event deep-link URL format.

## Notes

- Design spec: `docs/superpowers/specs/2026-05-11-genie-feedback-feature-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-11-genie-feedback-feature.md`
- The Genie message deep-link URL format (`?conversation_id=&message_id=`) is best-effort; if it's wrong, the helper in `lib/genie.ts` is the only place to fix and falls back to the space-level URL.

This pull request and its description were written by Isaac.
EOF
)" 2>&1 | tail -3
```

Expected: PR URL printed.

---

## Self-review

Run through these before handing off:

**Spec coverage**
- Stat band → Task 5a ✓
- Chart → Task 5b ✓
- Table → Task 5c ✓
- Drill-down with deep-links → Task 5d ✓
- Workspace-wide summary → Task 1 (SQL) + Task 3 (router) ✓
- Backend SP-only data path → Task 1 reuses `_run` which already runs as SP ✓
- No new `app.yaml` scopes → confirmed; rollup uses system tables which are SP-only ✓
- Audit-lag disclaimer in UI → present in Task 5a header and drill-down empty state ✓
- New nav entry between Resources and Settings → Task 6 ✓
- Bundle spec with implementation → Task 8.1 ✓

**Placeholder scan:** none. Every step has the actual code.

**Type consistency:** `FeedbackDailyPoint`, `FeedbackRollupItem`, `FeedbackWorkspaceSummary`, `FeedbackRollup` are used consistently in models, types, router parsing, and frontend rendering. `daily_negatives` is a list of `FeedbackDailyPoint` in both Python and TS.

**Scope:** one focused feature, one PR. Spec + plan + implementation all in scope.
