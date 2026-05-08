"""Build / update the GenieWatch executive overview Lakeview dashboard.

Three datasets, validated via execute_sql before this script ran:

  - spaces_summary  (1 row): active_spaces, total_queries, distinct_users,
                              approx_usd, pos_feedback, neg_feedback
  - daily_volume   (31 rows): day, queries, active_spaces, distinct_users
  - top_spaces     (25 rows): space_id, query_count, distinct_users, approx_usd

Widget spec follows the databricks-aibi-dashboards skill conventions:
  - text widgets via multilineTextboxSpec (no spec block)
  - counter version=2, disaggregated=true (single-row dataset)
  - table version=2, columns only need fieldName + displayName
  - line version=3, y as fields array with displayName

Run:
  uv run python scripts/setup_dashboard.py
"""
from __future__ import annotations

import json
import subprocess

DASH_ID = "01f14a56ef8f1820a1ad1fd1859eec22"
WAREHOUSE_ID = "4b9b953939869799"

SUMMARY_QUERY = """
WITH q AS (
  SELECT query_source.genie_space_id AS space_id,
         executed_by,
         compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         total_task_duration_ms AS task_ms
  FROM system.query.history
  WHERE query_source.genie_space_id IS NOT NULL
    AND start_time >= date_sub(current_date(), 7)
    AND total_task_duration_ms > 0
), hr_total AS (
  SELECT compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         SUM(total_task_duration_ms) AS hr_task_ms
  FROM system.query.history
  WHERE start_time >= date_sub(current_date(), 7)
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
    AND u.usage_start_time >= date_sub(current_date(), 7)
  GROUP BY 1, 2
), attributed AS (
  SELECT q.space_id,
         q.executed_by,
         (q.task_ms / NULLIF(t.hr_task_ms, 0)) * COALESCE(c.hr_usd, 0) AS query_usd
  FROM q
  JOIN hr_total t USING (wh, hr)
  LEFT JOIN hr_cost c USING (wh, hr)
), totals AS (
  SELECT COUNT(DISTINCT space_id) AS active_spaces,
         COUNT(*) AS total_queries,
         COUNT(DISTINCT executed_by) AS distinct_users,
         ROUND(SUM(query_usd), 2) AS approx_usd
  FROM attributed
), fb AS (
  SELECT SUM(CASE WHEN request_params.feedback_rating = 'POSITIVE' THEN 1 ELSE 0 END) AS pos_feedback,
         SUM(CASE WHEN request_params.feedback_rating = 'NEGATIVE' THEN 1 ELSE 0 END) AS neg_feedback
  FROM system.access.audit
  WHERE service_name = 'aibiGenie'
    AND action_name = 'updateConversationMessageFeedback'
    AND event_time >= date_sub(current_date(), 7)
)
SELECT t.active_spaces,
       t.total_queries,
       t.distinct_users,
       t.approx_usd,
       COALESCE(f.pos_feedback, 0) AS pos_feedback,
       COALESCE(f.neg_feedback, 0) AS neg_feedback
FROM totals t CROSS JOIN fb f
"""

DAILY_QUERY = """
SELECT date_trunc('day', start_time) AS day,
       COUNT(*) AS queries,
       COUNT(DISTINCT query_source.genie_space_id) AS active_spaces,
       COUNT(DISTINCT executed_by) AS distinct_users
FROM system.query.history
WHERE query_source.genie_space_id IS NOT NULL
  AND start_time >= date_sub(current_date(), 30)
GROUP BY 1
ORDER BY 1
"""

TOP_QUERY = """
WITH q AS (
  SELECT query_source.genie_space_id AS space_id,
         executed_by,
         compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         total_task_duration_ms AS task_ms
  FROM system.query.history
  WHERE query_source.genie_space_id IS NOT NULL
    AND start_time >= date_sub(current_date(), 7)
    AND total_task_duration_ms > 0
), hr_total AS (
  SELECT compute.warehouse_id AS wh,
         date_trunc('hour', start_time) AS hr,
         SUM(total_task_duration_ms) AS hr_task_ms
  FROM system.query.history
  WHERE start_time >= date_sub(current_date(), 7)
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
    AND u.usage_start_time >= date_sub(current_date(), 7)
  GROUP BY 1, 2
)
SELECT q.space_id,
       COUNT(*) AS query_count,
       COUNT(DISTINCT q.executed_by) AS distinct_users,
       ROUND(SUM((q.task_ms / NULLIF(t.hr_task_ms, 0)) * COALESCE(c.hr_usd, 0)), 2) AS approx_usd
FROM q
JOIN hr_total t USING (wh, hr)
LEFT JOIN hr_cost c USING (wh, hr)
GROUP BY q.space_id
ORDER BY query_count DESC
LIMIT 25
"""


def _kpi(name: str, dataset: str, field: str, display: str, title: str,
         x: int, y: int, fmt: dict | None = None) -> dict:
    encoding: dict = {"fieldName": field, "displayName": display}
    if fmt:
        encoding["format"] = fmt
    return {
        "widget": {
            "name": name,
            "queries": [{
                "name": "main_query",
                "query": {
                    "datasetName": dataset,
                    "fields": [{"name": field, "expression": f"`{field}`"}],
                    "disaggregated": True,
                },
            }],
            "spec": {
                "version": 2,
                "widgetType": "counter",
                "encodings": {"value": encoding},
                "frame": {"showTitle": True, "title": title},
            },
        },
        "position": {"x": x, "y": y, "width": 2, "height": 3},
    }


def _text(name: str, line: str, y: int, height: int = 1) -> dict:
    return {
        "widget": {"name": name, "multilineTextboxSpec": {"lines": [line]}},
        "position": {"x": 0, "y": y, "width": 6, "height": height},
    }


USD_FMT = {
    "type": "number-currency", "currencyCode": "USD",
    "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 2},
}
NUM_FMT = {
    "type": "number", "abbreviation": "compact",
    "decimalPlaces": {"type": "max", "places": 1},
}


SPEC = {
    "datasets": [
        {"name": "spaces_summary", "displayName": "Workspace summary",
         "query": " ".join(SUMMARY_QUERY.split())},
        {"name": "daily_volume", "displayName": "Daily query volume",
         "query": " ".join(DAILY_QUERY.split())},
        {"name": "top_spaces", "displayName": "Top spaces by activity",
         "query": " ".join(TOP_QUERY.split())},
    ],
    "pages": [
        {
            "name": "main",
            "displayName": "Genie Spaces Overview",
            "layout": [
                _text("title", "## GenieWatch — Genie Spaces Overview", y=0),
                _text("subtitle", "Workspace-wide health for Genie Spaces over the last 7 days.", y=1),

                _kpi("kpi-active", "spaces_summary", "active_spaces",
                     "Active Spaces", "Active Genie Spaces (7d)",
                     x=0, y=2, fmt=NUM_FMT),
                _kpi("kpi-queries", "spaces_summary", "total_queries",
                     "Total Queries", "Total Queries (7d)",
                     x=2, y=2, fmt=NUM_FMT),
                _kpi("kpi-users", "spaces_summary", "distinct_users",
                     "Distinct Users", "Distinct Users (7d)",
                     x=4, y=2, fmt=NUM_FMT),

                _kpi("kpi-cost", "spaces_summary", "approx_usd",
                     "Approx Cost", "Approx Cost (7d)",
                     x=0, y=5, fmt=USD_FMT),
                _kpi("kpi-pos", "spaces_summary", "pos_feedback",
                     "Thumbs up", "Positive Feedback (7d)",
                     x=2, y=5, fmt=NUM_FMT),
                _kpi("kpi-neg", "spaces_summary", "neg_feedback",
                     "Thumbs down", "Negative Feedback (7d)",
                     x=4, y=5, fmt=NUM_FMT),

                _text("trends-header", "## Trends (last 30 days)", y=8),
                {
                    "widget": {
                        "name": "daily-volume-chart",
                        "queries": [{
                            "name": "main_query",
                            "query": {
                                "datasetName": "daily_volume",
                                "fields": [
                                    {"name": "day", "expression": "`day`"},
                                    {"name": "queries", "expression": "`queries`"},
                                    {"name": "active_spaces", "expression": "`active_spaces`"},
                                    {"name": "distinct_users", "expression": "`distinct_users`"},
                                ],
                                "disaggregated": True,
                            },
                        }],
                        "spec": {
                            "version": 3,
                            "widgetType": "line",
                            "encodings": {
                                "x": {"fieldName": "day", "scale": {"type": "temporal"},
                                      "displayName": "Day"},
                                "y": {
                                    "scale": {"type": "quantitative"},
                                    "fields": [
                                        {"fieldName": "queries", "displayName": "Queries"},
                                        {"fieldName": "active_spaces", "displayName": "Active spaces"},
                                        {"fieldName": "distinct_users", "displayName": "Distinct users"},
                                    ],
                                },
                            },
                            "frame": {"showTitle": True,
                                      "title": "Daily Genie activity"},
                        },
                    },
                    "position": {"x": 0, "y": 9, "width": 6, "height": 5},
                },

                _text("top-header", "## Top Spaces by Activity (7d)", y=14),
                {
                    "widget": {
                        "name": "top-spaces-table",
                        "queries": [{
                            "name": "main_query",
                            "query": {
                                "datasetName": "top_spaces",
                                "fields": [
                                    {"name": "space_id", "expression": "`space_id`"},
                                    {"name": "query_count", "expression": "`query_count`"},
                                    {"name": "distinct_users", "expression": "`distinct_users`"},
                                    {"name": "approx_usd", "expression": "`approx_usd`"},
                                ],
                                "disaggregated": True,
                            },
                        }],
                        "spec": {
                            "version": 2,
                            "widgetType": "table",
                            "encodings": {
                                "columns": [
                                    {"fieldName": "space_id", "displayName": "Space"},
                                    {"fieldName": "query_count", "displayName": "Queries"},
                                    {"fieldName": "distinct_users", "displayName": "Users"},
                                    {"fieldName": "approx_usd", "displayName": "Approx USD"},
                                ],
                            },
                            "frame": {"showTitle": True,
                                      "title": "Top spaces by query volume"},
                        },
                    },
                    "position": {"x": 0, "y": 15, "width": 6, "height": 6},
                },
            ],
        },
    ],
}


def main() -> None:
    get_out = subprocess.check_output([
        "databricks", "api", "get",
        f"/api/2.0/lakeview/dashboards/{DASH_ID}",
        "--profile", "DEFAULT",
    ])
    current = json.loads(get_out)
    payload = {
        "display_name": "GenieWatch — Genie Spaces Overview",
        "warehouse_id": current.get("warehouse_id", WAREHOUSE_ID),
        "serialized_dashboard": json.dumps(SPEC),
        "etag": current.get("etag"),
    }
    with open("/tmp/dash-update.json", "w") as f:
        json.dump(payload, f)
    upd = subprocess.check_output([
        "databricks", "api", "patch",
        f"/api/2.0/lakeview/dashboards/{DASH_ID}",
        "--profile", "DEFAULT", "--json", "@/tmp/dash-update.json",
    ])
    print("update:", upd.decode()[:300])
    pub = subprocess.check_output([
        "databricks", "api", "post",
        f"/api/2.0/lakeview/dashboards/{DASH_ID}/published",
        "--profile", "DEFAULT", "--json",
        json.dumps({"warehouse_id": payload["warehouse_id"], "embed_credentials": True}),
    ])
    print("publish:", pub.decode()[:200])


if __name__ == "__main__":
    main()
