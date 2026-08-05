"""
Deterministic dashboard stats from the local SODA SQLite cache.

What this file does:
  Runs SQL group-bys on the FULL local table and returns counts ready for
  charts (borough, class, status, monthly trend). No AI is involved —
  the numbers come straight from SQLite.

Non-technical tip:
  If charts look empty or out of date:
    1) Make sure Django is running
    2) Re-download data:  python manage.py fetch_soda_violations
  The charts always reflect whatever is in backend/data/soda_violations.sqlite3
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import data_store


def build_dashboard_stats(
    *,
    status_top_n: int = 15,
    month_count: int = 36,
) -> dict[str, Any]:
    """
    Build chart-ready aggregates for the frontend dashboard.

    Returns plain lists of {name, value} so Recharts can draw them
    without extra reshaping in the browser.

    status_top_n  — how many status bars to keep (rest are dropped for readability)
    month_count   — how many recent YYYY-MM buckets to show on the trend line
    """
    # No local file yet → tell the UI to show a friendly "run fetch" message
    if not data_store.cache_exists():
        return {
            "cache_ready": False,
            "row_count": 0,
            "inspectiondate_min": None,
            "inspectiondate_max": None,
            "by_boro": [],
            "by_class": [],
            "by_currentstatus": [],
            "by_month": [],
            "message": (
                "Local SODA cache is empty. Run: "
                "python manage.py fetch_soda_violations"
            ),
        }

    tbl = data_store.table_name()
    path = data_store.sqlite_path()

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row

        # Total rows currently stored locally
        total = int(conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0])

        # Counts by borough (all boroughs — usually only a handful)
        by_boro = _group_counts(conn, tbl, "boro")

        # Counts by violation class (A / B / C, etc.)
        # "class" must be quoted — it is a reserved SQL word
        by_class = _group_counts(conn, tbl, '"class"')

        # Counts by current status (top N only — there can be many statuses)
        by_status = _group_counts(conn, tbl, "currentstatus", top_n=status_top_n)

        # Monthly trend from inspectiondate (recent months, chronological)
        by_month = _monthly_counts(conn, tbl, month_count=month_count)

        # Overall date range (helps the UI caption the trend chart)
        date_row = conn.execute(
            f'SELECT MIN(inspectiondate) AS min_d, MAX(inspectiondate) AS max_d '
            f'FROM "{tbl}" '
            f"WHERE inspectiondate IS NOT NULL AND TRIM(inspectiondate) != '' "
            f"AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099'"
        ).fetchone()

    return {
        "cache_ready": True,
        "row_count": total,
        "inspectiondate_min": date_row["min_d"] if date_row else None,
        "inspectiondate_max": date_row["max_d"] if date_row else None,
        "by_boro": by_boro,
        "by_class": by_class,
        "by_currentstatus": by_status,
        "by_month": by_month,
        "notes": (
            "Counts cover the entire local cache. "
            "by_month uses inspectiondate (YYYY-MM), last "
            f"{month_count} months with plausible years (1990–2099). "
            f"by_currentstatus shows the top {status_top_n} statuses."
        ),
    }


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    column_sql: str,
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """
    Count rows grouped by one column.

    Returns [{"name": "...", "value": 123}, ...] sorted by count descending.
    column_sql may include quotes (needed for the field named "class").
    """
    sql = (
        f"SELECT {column_sql} AS name, COUNT(*) AS value "
        f'FROM "{table}" '
        f"WHERE {column_sql} IS NOT NULL "
        f"AND TRIM(CAST({column_sql} AS TEXT)) != '' "
        f"GROUP BY {column_sql} "
        f"ORDER BY value DESC"
    )
    if top_n:
        sql += f" LIMIT {int(top_n)}"

    rows = conn.execute(sql).fetchall()
    return [{"name": r["name"], "value": int(r["value"])} for r in rows]


def _monthly_counts(
    conn: sqlite3.Connection,
    table: str,
    *,
    month_count: int,
) -> list[dict[str, Any]]:
    """
    Count inspections per calendar month (YYYY-MM from inspectiondate).

    Why filter years 1990–2099?
      A few SODA rows have bad years like "0219-...". Skipping those keeps
      the trend chart readable. Maintainers: if NYC data quality improves,
      you can widen this range — charts will pick up the extra months.

    We fetch the newest N months, then reverse so the line chart reads left→right
    (oldest on the left, newest on the right).
    """
    # First 7 characters of an ISO-ish timestamp are "YYYY-MM"
    sql = (
        f"SELECT substr(inspectiondate, 1, 7) AS name, COUNT(*) AS value "
        f'FROM "{table}" '
        f"WHERE inspectiondate IS NOT NULL "
        f"AND length(trim(inspectiondate)) >= 7 "
        f"AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099' "
        f"GROUP BY name "
        f"ORDER BY name DESC "
        f"LIMIT ?"
    )
    rows = conn.execute(sql, (int(month_count),)).fetchall()
    # Newest-first from SQL → reverse for chronological chart order
    points = [{"name": r["name"], "value": int(r["value"])} for r in rows]
    points.reverse()
    return points
