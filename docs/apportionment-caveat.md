# Why GenieWatch's per-space cost is approximate

Databricks SQL warehouses bill at the **warehouse-hour** level. There is no per-query bill — the product publishes total DBUs consumed by a warehouse over each hour to `system.billing.usage`, and that's the only place a dollar figure shows up.

When a Genie Space runs a query, that query is recorded in `system.query.history` with:
- `query_source.genie_space_id` — which space drove the query
- `total_task_duration_ms` — total CPU task time across all parallel tasks
- `compute.warehouse_id` — which warehouse it ran on
- `start_time` — when the query started

GenieWatch attributes warehouse cost to a Genie space using the same per-hour proportional-task-time approach as the [DBSQL Cost Per Query MV](https://github.com/databrickslabs/sandbox/blob/main/dbsql/cost_per_query/PrPr/DBSQL%20Cost%20Per%20Query%20MV%20(PrPr).sql):

```
For each (warehouse, hour) bucket:
    space_share        = sum(space_query_task_ms in that hour)
                       ÷ sum(all_query_task_ms in that hour)
    hour_warehouse_$   = sum(usage_quantity × list_prices.pricing.default in that hour)
    space_hour_$       = space_share × hour_warehouse_$

space_total_$ = sum(space_hour_$ across all hours)
```

This is implemented in `services/system_tables.py::_TOP_SPENDERS_SQL` and `_COST_PER_SPACE_SQL`.

## Why per-hour, not whole-window

An earlier (now-replaced) version computed `(total_genie_task / total_warehouse_task) × total_billing` over the full window. That under-estimated when Genie was active mostly during quiet hours and over-estimated when it was active during busy ones — both with the same window-wide ratio. Per-hour buckets fix that: each hour's share is matched to that hour's bill.

## Why `total_task_duration_ms`, not `total_duration_ms`

`total_duration_ms` includes time the query spent waiting in queue. The warehouse doesn't bill for queue time — it bills for CPU work. `total_task_duration_ms` is the sum of per-node task time and is the right denominator for proportional cost.

## Where this is still an approximation

1. **Idle warehouse hours.** A warehouse can sit idle for an hour and still bill. None of that idle DBU is attributed to any space (no `task_ms` to apportion against). If a Genie space is the *only* user of a warehouse, the idle hours of that warehouse do not appear in the space's cost line — so the number shown is lower than the customer's actual spend on that warehouse.
2. **Hours with only Genie activity.** If Genie was the only thing that ran during an hour, it absorbs 100% of that hour's bill — including any minimum-DBU charge or auto-stop-grace-period cost. That's correct for "this is what enabling Genie cost the warehouse this hour" but generous for "what raw compute did Genie's query consume."
3. **Serverless SQL** uses different SKUs (e.g. `ENTERPRISE_SERVERLESS_SQL_COMPUTE_*`) but the math is the same. List prices are joined on `(sku_name, cloud, time_window)`.
4. **LLM costs are NOT included.** Genie's natural-language → SQL inference runs on Foundation Model APIs and is billed under separate SKUs. None of that is attributed here.
5. **System table retention is 365 days.** Anything older than that simply isn't queryable.

## Per-conversation cost

`system.query.history.query_source` carries `genie_space_id` but **not** `genie_conversation_id`. To attribute query cost to a conversation, GenieWatch correlates each query's `start_time` with the most recent matching `system.access.audit` event:

- `service_name = 'aibiGenie'`
- `request_params.space_id` matches the query's space
- `event_time <= query.start_time`
- within 10 minutes

This is the heuristic Databricks recommends for splitting cost across conversations. It is approximate — if multiple conversations are active concurrently in the same space, attribution will favor whichever started first. The query lives in `services/system_tables.py::_COST_PER_CONVERSATION_SQL` and is invoked only by the per-space Cost tab (never by the spaces list or Cost Explorer).

## What we display in the UI

- Every USD figure has an info icon linking to this doc.
- The Cost tab includes an explicit `apportionment: "warehouse_share"` field in the API response so a future UI can clearly mark "approximate" cells.
- Numbers can lag — `system.query.history` is typically ~5–15 min behind, `system.billing.usage` ~1 day, `system.access.audit` ~1–4 hours.

## What you'd need for exact per-query cost

You would need either:
- A native `system.billing.query_usage` table (does not exist as of 2026), or
- A FinOps-grade tagger that emits a per-query DBU calculation in real time (Genie does not).

For now, treat GenieWatch's cost numbers as **directional and benchmark-grade** — useful for ranking spaces by spend and identifying the heaviest conversations, less useful for pinpoint dollar amounts.
