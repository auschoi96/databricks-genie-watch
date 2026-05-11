# Genie feedback overview — design

## Context

Today the only workspace-wide signal for Genie feedback is the positive/negative counter on the Cost Explorer dashboard. To see individual ratings and the user-supplied comment text, an operator has to drill into each space one by one. There's no view that says "across the whole workspace, which spaces are getting the most thumbs-downs, and what are users actually complaining about?"

This design adds a **Feedback** page that surfaces (a) workspace-wide feedback health at a glance, (b) which spaces have the most negative ratings, (c) how negative feedback is trending over time, and (d) the individual comments behind those ratings with deep-links into the original Genie conversations.

The per-space "Recent feedback" panel that already exists in `SpaceDetail.tsx` is kept and reused — this new page is a workspace-wide front door, not a replacement.

## Scope

**In scope**
- New top-level "Feedback" tab between Resources and Settings.
- Time window selector (7d / 30d / 90d).
- Workspace-wide stat band: total feedback events, % positive, # spaces with at least one negative.
- Trend chart: daily count of negative ratings per top-N spaces over the window.
- Ranked table: per-space totals, positive/negative counts, last-negative timestamp.
- Expandable rows showing individual feedback events (rating, comment, user, timestamp) with a deep-link per event back to the source Genie conversation.

**Out of scope (deliberately)**
- Real-time / streaming updates. Audit log lag is 1–4h; the page refetches on focus.
- Notifications, alerts, or Slack integration.
- Per-user feedback views (privacy minefield and not requested).
- Editing or responding to feedback. Read-only, like the rest of GenieWatch.
- Embedding into the Cost Explorer dashboard. Explicitly a separate page.

## Architecture

One new backend endpoint, one new frontend page. Per-space drill-down reuses the existing `/api/spaces/{id}/feedback` endpoint.

```
Browser → /feedback page
    │
    ├─ GET /api/feedback/rollup?days=30                  (new)
    │       └─ system_tables.feedback_rollup(days)        (new SQL)
    │             ├─ workspace_summary: total/pos/neg/spaces_with_neg
    │             └─ items[]: per-space totals + daily neg time series
    │
    └─ user clicks row → expand
        └─ GET /api/spaces/{id}/feedback?days=30          (existing)
              └─ system_tables.feedback_per_space         (existing)
                    → events with rating, comment, conversation_id, message_id
                          │
                          └─ Deep-link → {host}/genie/rooms/<sid>?conversation_id=<cid>&message_id=<mid>
```

No new caching layer; no Lakebase changes. The audit table is the source of truth.

## Backend

### SQL

Added to `backend/services/system_tables.py`. Single statement returning both per-space aggregates and a workspace-wide summary, plus a daily time series array per space.

```sql
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
         SUM(CASE WHEN rating='POSITIVE' THEN 1 ELSE 0 END) AS positive,
         SUM(CASE WHEN rating='NEGATIVE' THEN 1 ELSE 0 END) AS negative,
         MAX(CASE WHEN rating='NEGATIVE' THEN event_time END) AS last_negative_at
  FROM events
  GROUP BY 1
), daily AS (
  SELECT space_id,
         date_trunc('day', event_time) AS day,
         SUM(CASE WHEN rating='NEGATIVE' THEN 1 ELSE 0 END) AS neg
  FROM events
  GROUP BY 1, 2
), daily_arr AS (
  SELECT space_id,
         array_sort(collect_list(struct(day, neg))) AS daily_negatives
  FROM daily
  GROUP BY 1
), workspace_summary AS (
  SELECT COUNT(*)                                                              AS total,
         SUM(CASE WHEN rating='POSITIVE' THEN 1 ELSE 0 END)                    AS positive,
         SUM(CASE WHEN rating='NEGATIVE' THEN 1 ELSE 0 END)                    AS negative,
         COUNT(DISTINCT CASE WHEN rating='NEGATIVE' THEN space_id END)         AS spaces_with_negatives
  FROM events
)
SELECT
  -- Two payloads in one round-trip: per-space rows + workspace totals.
  ws.total AS ws_total, ws.positive AS ws_positive, ws.negative AS ws_negative,
  ws.spaces_with_negatives AS ws_spaces_with_negatives,
  a.space_id, a.total, a.positive, a.negative, a.last_negative_at,
  d.daily_negatives
FROM workspace_summary ws CROSS JOIN agg a
LEFT JOIN daily_arr d USING (space_id)
ORDER BY a.negative DESC, a.total DESC
```

Python deserializes this once, splits into a `summary` and `items[]`. Cap items at top 50 by negative count, fall back to top 50 by total when negatives < 50.

### Title enrichment

The audit table carries `space_id` but no title. The router enriches each item by looking up `lakebase.get_space_cache(space_id)`. Spaces without a cache entry get `title=None` and the frontend renders "Unknown space" — matches the existing pattern in the Resource Graph.

### Router

`backend/routers/feedback.py`:

- `GET /api/feedback/rollup?days=30&limit=50` → `FeedbackRollup`

Registered in `backend/main.py` alongside the existing routers. No new OBO scopes — this is SP-only because `system.access.audit` always queries as the SP (consistent with the rest of the system-table pages).

### Models

Added to `backend/models.py`. Mirrored verbatim in `frontend/src/types/api.ts`.

```python
class FeedbackDailyPoint(BaseModel):
    day: date
    neg: int

class FeedbackRollupItem(BaseModel):
    space_id: str
    title: Optional[str]
    total: int
    positive: int
    negative: int
    last_negative_at: Optional[datetime]
    daily_negatives: list[FeedbackDailyPoint]

class FeedbackWorkspaceSummary(BaseModel):
    total: int
    positive: int
    negative: int
    pct_positive: Optional[float]  # positive / total, null when total = 0
    spaces_with_negatives: int

class FeedbackRollup(BaseModel):
    days: int
    summary: FeedbackWorkspaceSummary
    items: list[FeedbackRollupItem]
```

## Frontend

### New page

`frontend/src/pages/Feedback.tsx`. Single file, ~250 lines, mirrors the structure of `CostExplorer.tsx` and `ResourceRollup.tsx`.

Layout, top to bottom:

1. **Title row** with the time-window selector right-aligned (7d / 30d / 90d).
2. **Stat band** — three KPI cards:
   - **Total feedback** — `summary.total`.
   - **% positive** — `summary.pct_positive`, formatted as `92.3%`. Renders "—" when `total = 0`.
   - **Spaces with negatives** — `summary.spaces_with_negatives`.
3. **Chart card** — "Negative ratings over time".
   - `recharts` `LineChart`, X = day, Y = negative count.
   - One line per top N spaces (N = 5). Spaces ranked by total negatives in the window.
   - Color palette paired to the table rows so a reader can trace a line back to its row.
   - Days with zero negatives plot as `y=0`; only entirely-missing days produce a gap.
4. **Table card** — "Spaces by feedback".
   - Columns: Space (title or "Unknown space") | Total | Positive | Negative | Last negative | ↗.
   - Sortable on all numeric columns. Default sort: Negative desc, tiebroken by Total desc.
   - "↗" column = existing `genieSpaceUrl` helper, opens the space in Databricks.
   - Row is clickable to expand; chevron flips.
5. **Expanded row** (lazy-loaded). On first expand, fetches `GET /api/spaces/{id}/feedback?days=N`. Caches per row so subsequent collapses/expands don't refetch.
   - List of feedback events: rating chip (green/red), comment text (italic if present), user email, relative timestamp.
   - Per-event "↗" deep-link → `genieMessageUrl(spaceId, conversationId, messageId, workspaceHost)`.
   - Empty case: "No individual events visible (audit log lag is 1–4h)."

### Deep-link helper

New helper in `frontend/src/lib/genie.ts`:

```ts
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

**Open question:** the exact query-param vs hash-fragment format used by the Databricks Genie UI for deep-linking into a specific conversation/message. This design assumes `?conversation_id=&message_id=`; if Genie uses a different format, the helper is one place to fix. Falls back to space-only link when `conversationId` is null.

### API helper

Added to `frontend/src/lib/api.ts`:

```ts
export const getFeedbackRollup = (days = 30, limit = 50) =>
  fetchJson<FeedbackRollup>(`/feedback/rollup?days=${days}&limit=${limit}`)
```

`getSpaceFeedback(spaceId, days)` already exists and is reused for the drill-down.

### Nav

`frontend/src/App.tsx` adds a new nav entry between **Resources** and **Settings**, routes `/feedback` to the new page.

### Loading / empty / error states

- Loading: skeleton stat band + skeleton chart placeholder + skeleton table rows. Reuse `<Skeleton>` already in `components/ui/`.
- Empty (total = 0): muted message — "No feedback in the last X days. Audit log lag is typically 1–4 hours." The audit-lag note matches the existing language on `SpaceDetail.tsx:124`.
- API error: red error card with the message and a retry button (reuse `Card` styling).

## Data flow

1. User opens `/feedback`. Page fetches `/api/feedback/rollup?days=30`.
2. Stat band renders from `summary`.
3. Chart renders from the top N items' `daily_negatives`.
4. Table renders from all items, sortable client-side.
5. User clicks a table row → page fetches `/api/spaces/{id}/feedback?days=30`. Cached per row.
6. Expanded panel shows events. User clicks a per-event "↗" → opens new tab to the Genie conversation deep-link.

Worst case payload size: ~50 items × (small aggregate + 90 daily points) + summary ≈ <50 KB. Single round-trip.

## Performance

- Rollup query touches `system.access.audit` with `event_time` partition pruning by `days`. Workspaces with thousands of spaces but only dozens of feedback events return in <5s on a small serverless warehouse.
- The frontend caches per-row drill-down responses so an opened-and-collapsed row doesn't refetch.
- Polling: refetch the rollup on tab focus (existing `useCachedFetch` behavior). No interval polling.

## Error handling

- Rollup fetch fails → red error card + retry button. The rest of the app keeps working.
- Drill-down fetch fails → inline error message in the expanded panel; other rows unaffected.
- Empty / missing data → muted "no data" treatment with the audit-lag disclaimer, not an error.
- Audit table missing the SP grant → backend returns 502 with a message pointing to `docs/system-tables-grants.md`. Same failure mode as every other page that hits system tables; no new handling needed.

## Testing

Per the repo's CLAUDE.md, all testing is by deploy. Before deploy:

1. **SQL validation** — run `feedback_rollup(days=7)` via `databricks api execute` against the FEVM warehouse. Confirm shape and runtime <5s.
2. **Backend import-check** — `uv run python -c "from backend.main import app; ..."`. Confirms the new router registers.
3. **Frontend type-check** — `npx tsc -b` in `frontend/`. Must be clean.

Post-deploy on the FEVM workspace (`fevm-stable-ekaiik`):

4. Open `/feedback`. Empty state should render with the audit-lag disclaimer (no real Genie activity on this workspace).
5. Time-window selector switches between 7d / 30d / 90d.
6. Nav shows the new Feedback entry in the correct position.
7. The deep-link helper produces a syntactically correct URL when called with a fake conversation_id.

Full UX validation (chart shape, table sort, drill-down expand, real deep-link) requires a workspace with real Genie feedback traffic — flag in the PR as deferred.

## Files touched

**Backend (new):**
- `backend/routers/feedback.py`

**Backend (modified):**
- `backend/services/system_tables.py` — add `feedback_rollup()`.
- `backend/main.py` — register `feedback_router`.
- `backend/models.py` — add `FeedbackDailyPoint`, `FeedbackRollupItem`, `FeedbackWorkspaceSummary`, `FeedbackRollup`.

**Frontend (new):**
- `frontend/src/pages/Feedback.tsx`.

**Frontend (modified):**
- `frontend/src/App.tsx` — nav entry + route.
- `frontend/src/lib/api.ts` — `getFeedbackRollup`.
- `frontend/src/lib/genie.ts` — `genieMessageUrl`.
- `frontend/src/types/api.ts` — mirror the new Pydantic models.

No `app.yaml` changes (no new scopes). No `deploy.sh` changes (no new permissions to grant). No new dependencies on either side.
