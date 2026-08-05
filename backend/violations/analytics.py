"""
Dashboard chart stats from the LIVE SODA API (no local SQLite cache).

What this file does:
  Asks NYC Open Data for group-by counts (borough, class, status, monthly)
  and returns them ready for Recharts on the frontend.

Non-technical tip:
  Charts can take 1–3 minutes the first time because the portal aggregates
  ~3 million rows remotely. Click Refresh on the dashboard to pull again.
  Make sure SOCRATA_APP_TOKEN is set in the root .env file.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from . import socrata_client


def build_dashboard_stats(
    *,
    status_top_n: int = 15,
    month_count: int = 36,
    where: str | None = None,
) -> dict[str, Any]:
    """
    Build chart-ready aggregates from the LIVE Open HPD Violations API.

    Returns lists of {name, value} so Recharts can draw them without reshaping.
    """
    try:
        total = socrata_client.get_record_count(where=where)
        by_boro = socrata_client.fetch_group_counts("boro", where=where)
        by_class = socrata_client.fetch_group_counts("class", where=where)
        by_status = socrata_client.fetch_group_counts(
            "currentstatus", where=where, top_n=status_top_n
        )
        by_month = socrata_client.fetch_monthly_counts(
            where=where, month_count=month_count
        )
    except Exception as exc:
        return {
            "api_ready": False,
            "source": "live_socrata_soda_api",
            "dataset_id": settings.SOCRATA_DATASET_ID,
            "row_count": 0,
            "by_boro": [],
            "by_class": [],
            "by_currentstatus": [],
            "by_month": [],
            "error": str(exc),
            "message": (
                "Could not load live chart counts from NYC Open Data. "
                "Check SOCRATA_APP_TOKEN in .env, then click Refresh."
            ),
        }

    return {
        "api_ready": True,
        "source": "live_socrata_soda_api",
        "dataset_id": settings.SOCRATA_DATASET_ID,
        "row_count": total,
        "by_boro": by_boro,
        "by_class": by_class,
        "by_currentstatus": by_status,
        "by_month": by_month,
        "notes": (
            "Counts come from the LIVE NYC Open Data SODA API (not a local file). "
            f"by_month uses inspectiondate (YYYY-MM), last {month_count} months. "
            f"by_currentstatus shows the top {status_top_n} statuses."
        ),
    }
