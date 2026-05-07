# Why GenieWatch's per-space cost is approximate

Databricks SQL warehouses bill at the **warehouse-day** level. There is no per-query bill — the product publishes total DBUs consumed by a warehouse on a given day to `system.billing.usage`, and that's the only place a dollar figure shows up.

When a Genie Space runs a query, that query is recorded in `system.query.history` with:
- `query_source.genie_space_id` — which space drove the query
- `total_duration_ms` — how long the query ran
- `compute.warehouse_id` — which warehouse it ran on

So we can attribute a *fraction* of the warehouse's daily cost to a space:

```
space_share_of_warehouse_day = sum(query.total_duration_ms WHERE query_source.genie_space_id = X)
                             ÷ sum(query.total_duration_ms WHERE warehouse = W)
                             on the same day
                             
space_approx_cost = space_share × warehouse_day_dbus × list_price
```

This is what `services/system_tables.cost_per_space` does.

## Where this is wrong

1. **Idle warehouse time isn't queried.** A warehouse can sit idle for hours between queries and still bill. None of that idle DBU is attributed to any space — so every space's "share" is artificially deflated against the warehouse's true cost. If a space is the only thing on a warehouse, its number is too low; if many spaces share a warehouse heavily, the proportions are accurate.
2. **Serverless SQL has different billing units.** `list_price` for serverless is per-DBU but the duration math still applies. Numbers should be order-of-magnitude correct.
3. **Concurrent queries.** Two queries running at once on a warehouse don't double the warehouse cost, but they do double the `total_duration_ms` denominator — apportionment stays internally consistent.

## What we display

- Every USD figure has an info icon linking to this doc.
- The Cost tab includes an explicit `apportionment: "warehouse_share"` field in the API response so a future UI can clearly mark "approximate" cells.
- A "data freshness" hint shows next to numbers (system.query.history lag is ~5–15 min; billing lag is ~1 day).

## What you'd need for exact per-query cost

You would need either:
- A native `system.billing.query_usage` table (does not exist as of 2026).
- A FinOps-grade tagger that tags every Genie-driven query with `genie_space_id` *and* attaches a per-query DBU calculation. Genie does the first half today; the second half is unsolved at the platform level.

For now, treat GenieWatch's cost numbers as **directional** — useful for ranking spaces by spend, less useful for pinpoint dollar amounts. The query count and resource lineage are exact; only the dollar conversion is approximate.
