"""Update the GenieWatch dashboard with a corrected widget spec.

The first version used short-hand encoding shapes that the Lakeview
renderer rejects ("Visualization has no fields selected"). This version
uses the full encoding shape: each query is named "main_query", each
table column has type/displayAs/visible/order, and the line chart uses
v3 encoding with `y` as an array.
"""
from __future__ import annotations

import json
import subprocess

DASH_ID = "01f14a56ef8f1820a1ad1fd1859eec22"

TOP_SPENDERS_QUERY = """
WITH q AS (
  SELECT query_source.genie_space_id AS space_id,
         compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         SUM(total_task_duration_ms) AS task_ms,
         COUNT(*) AS n
  FROM system.query.history
  WHERE query_source.genie_space_id IS NOT NULL
    AND start_time >= current_date() - 30
    AND total_task_duration_ms > 0
  GROUP BY 1, 2, 3
), hr_total AS (
  SELECT compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         SUM(total_task_duration_ms) AS hr_task_ms
  FROM system.query.history
  WHERE start_time >= current_date() - 30
    AND total_task_duration_ms > 0
  GROUP BY 1, 2
), hr_cost AS (
  SELECT u.usage_metadata.warehouse_id AS wh,
         date_trunc('hour', u.usage_start_time) AS hr,
         SUM(u.usage_quantity * COALESCE(p.pricing.default, 0)) AS hr_usd
  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name AND u.cloud = p.cloud
   AND u.usage_start_time >= p.price_start_time
   AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  WHERE u.usage_metadata.warehouse_id IS NOT NULL
    AND u.usage_start_time >= current_date() - 30
  GROUP BY 1, 2
)
SELECT q.space_id,
       SUM(q.n) AS query_count,
       ROUND(SUM((q.task_ms / NULLIF(t.hr_task_ms, 0)) * COALESCE(c.hr_usd, 0)), 2) AS approx_usd
FROM q
JOIN hr_total t USING (wh, hr)
LEFT JOIN hr_cost c USING (wh, hr)
GROUP BY q.space_id
ORDER BY approx_usd DESC NULLS LAST
LIMIT 25
"""

DAILY_QUERIES_QUERY = """
SELECT date_trunc('day', start_time) AS day,
       COUNT(*) AS queries,
       COUNT(DISTINCT query_source.genie_space_id) AS active_spaces
FROM system.query.history
WHERE query_source.genie_space_id IS NOT NULL
  AND start_time >= current_date() - 30
GROUP BY 1
ORDER BY 1
"""

spec = {
    "datasets": [
        {
            "name": "top_spenders",
            "displayName": "Top spending Genie spaces",
            "query": " ".join(TOP_SPENDERS_QUERY.split()),
        },
        {
            "name": "daily_query_volume",
            "displayName": "Daily Genie query volume",
            "query": " ".join(DAILY_QUERIES_QUERY.split()),
        },
    ],
    "pages": [
        {
            "name": "main",
            "displayName": "Genie Cost Overview",
            "layout": [
                {
                    "widget": {
                        "name": "title_top",
                        "textbox_spec": "## Top spending Genie Spaces (last 30 days)",
                    },
                    "position": {"x": 0, "y": 0, "width": 6, "height": 1},
                },
                {
                    "widget": {
                        "name": "top_spenders_table",
                        "queries": [{
                            "name": "main_query",
                            "query": {
                                "datasetName": "top_spenders",
                                "fields": [
                                    {"name": "space_id", "expression": "`space_id`"},
                                    {"name": "query_count", "expression": "`query_count`"},
                                    {"name": "approx_usd", "expression": "`approx_usd`"},
                                ],
                                "disaggregated": True,
                            },
                        }],
                        "spec": {
                            "version": 1,
                            "widgetType": "table",
                            "encodings": {
                                "columns": [
                                    {
                                        "fieldName": "space_id",
                                        "type": "string",
                                        "displayName": "Space",
                                        "displayAs": "string",
                                        "visible": True,
                                        "order": 0,
                                    },
                                    {
                                        "fieldName": "query_count",
                                        "type": "integer",
                                        "displayName": "Queries",
                                        "displayAs": "number",
                                        "visible": True,
                                        "order": 1,
                                        "numberFormat": "0",
                                    },
                                    {
                                        "fieldName": "approx_usd",
                                        "type": "float",
                                        "displayName": "Approx USD",
                                        "displayAs": "number",
                                        "visible": True,
                                        "order": 2,
                                        "numberFormat": "$0.00",
                                    },
                                ],
                            },
                            "frame": {"showTitle": True, "title": "Top spenders"},
                        },
                    },
                    "position": {"x": 0, "y": 1, "width": 6, "height": 7},
                },
                {
                    "widget": {
                        "name": "title_daily",
                        "textbox_spec": "## Daily query volume across Genie Spaces",
                    },
                    "position": {"x": 0, "y": 8, "width": 6, "height": 1},
                },
                {
                    "widget": {
                        "name": "daily_chart",
                        "queries": [{
                            "name": "main_query",
                            "query": {
                                "datasetName": "daily_query_volume",
                                "fields": [
                                    {"name": "day", "expression": "`day`"},
                                    {"name": "queries", "expression": "`queries`"},
                                    {"name": "active_spaces", "expression": "`active_spaces`"},
                                ],
                                "disaggregated": True,
                            },
                        }],
                        "spec": {
                            "version": 3,
                            "widgetType": "line",
                            "encodings": {
                                "x": {
                                    "fieldName": "day",
                                    "scale": {"type": "temporal"},
                                    "displayName": "Day",
                                },
                                "y": [{
                                    "fieldName": "queries",
                                    "scale": {"type": "quantitative"},
                                    "displayName": "Queries",
                                }],
                            },
                            "frame": {"showTitle": True, "title": "Daily Genie queries"},
                        },
                    },
                    "position": {"x": 0, "y": 9, "width": 6, "height": 7},
                },
            ],
        },
    ],
}

# Fetch current dashboard for etag
get_out = subprocess.check_output([
    "databricks", "api", "get",
    f"/api/2.0/lakeview/dashboards/{DASH_ID}",
    "--profile", "DEFAULT",
])
current = json.loads(get_out)
etag = current.get("etag")
print(f"current etag: {etag}")

payload = {
    "display_name": current.get("display_name", "GenieWatch — Cost Overview"),
    "warehouse_id": current.get("warehouse_id"),
    "serialized_dashboard": json.dumps(spec),
    "etag": etag,
}

with open("/tmp/dash-update.json", "w") as f:
    json.dump(payload, f)

# Update
upd_out = subprocess.check_output([
    "databricks", "api", "patch",
    f"/api/2.0/lakeview/dashboards/{DASH_ID}",
    "--profile", "DEFAULT", "--json", "@/tmp/dash-update.json",
])
print("update response:", upd_out.decode()[:300])

# Republish
pub_out = subprocess.check_output([
    "databricks", "api", "post",
    f"/api/2.0/lakeview/dashboards/{DASH_ID}/published",
    "--profile", "DEFAULT", "--json",
    json.dumps({"warehouse_id": current.get("warehouse_id"), "embed_credentials": True}),
])
print("publish response:", pub_out.decode()[:300])
