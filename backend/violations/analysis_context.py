"""
Build a compact "data pack" from the FULL local SODA cache for Gemini.

Why not send every row?
  The Open HPD Violations table can be ~3 million rows. Sending that to an
  AI model would be extremely slow and expensive. Instead we:

  1) Download the whole table once into SQLite (fetch_soda_violations).
  2) Summarize the WHOLE table with SQL (counts, group-bys, sample rows).
  3) Send that summary to Gemini the FIRST time in a browser session.

Non-technical tip:
  If AI answers feel out of date, re-run:
    python manage.py fetch_soda_violations
  so the local SQLite file matches NYC Open Data again.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import data_store


def build_analysis_context(
    sample_size: int = 40,
    top_n: int = 20,
) -> dict[str, Any]:
    """
    Create the dataset summary Gemini will use for analysis.

    What this returns (plain English):
      - how many rows are in the local full table
      - every column name
      - counts by borough / class / status / top ZIP codes
      - a small sample of real rows (so the AI can see real examples)

    This is computed from the ENTIRE local cache, not just the current
    page shown in the browser.
    """
    if not data_store.cache_exists():
        raise RuntimeError(
            "Local SODA cache is empty. Run: python manage.py fetch_soda_violations"
        )

    tbl = data_store.table_name()
    path = data_store.sqlite_path()

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row

        # Total rows in the downloaded table
        total = int(conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0])

        # Column list (same order the inventory list uses)
        col_info = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        columns = [c["name"] for c in col_info]

        # Group-by summaries across the WHOLE table
        by_boro = _group_counts(conn, tbl, "boro", top_n=None)
        by_class = _group_counts(conn, tbl, '"class"', top_n=None, key_name="class")
        by_status = _group_counts(conn, tbl, "currentstatus", top_n=top_n)
        by_zip = _group_counts(conn, tbl, "zip", top_n=top_n)

        # Date range for inspectiondate (helps time-based questions)
        date_row = conn.execute(
            f'SELECT MIN(inspectiondate) AS min_d, MAX(inspectiondate) AS max_d '
            f'FROM "{tbl}" WHERE inspectiondate IS NOT NULL AND TRIM(inspectiondate) != ""'
        ).fetchone()

        # Small sample of real rows (newest inspections first)
        sample_rows = [
            {k: ("" if r[k] is None else r[k]) for k in r.keys()}
            for r in conn.execute(
                f'SELECT * FROM "{tbl}" '
                f"ORDER BY inspectiondate DESC "
                f"LIMIT ?",
                (sample_size,),
            ).fetchall()
        ]

    return {
        "dataset_id": "csn4-vhvf",
        "dataset_name": "Open HPD Violations",
        "source": "local_sqlite_cache_of_full_soda_table",
        "row_count": total,
        "columns": columns,
        "inspectiondate_min": date_row["min_d"] if date_row else None,
        "inspectiondate_max": date_row["max_d"] if date_row else None,
        "aggregates": {
            "by_boro": by_boro,
            "by_class": by_class,
            "by_currentstatus": by_status,
            "by_zip_top": by_zip,
        },
        "sample_rows": sample_rows,
        "notes": (
            "Aggregates cover the entire local cache. "
            "sample_rows is only a small example set for illustration."
        ),
    }


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    column_sql: str,
    *,
    top_n: int | None,
    key_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Count rows grouped by one column.

    column_sql may include quotes (needed for the field named "class").
    key_name is the JSON key shown to the AI (defaults to column_sql).
    """
    label = key_name or column_sql.strip('"')
    sql = (
        f'SELECT {column_sql} AS value, COUNT(*) AS count '
        f'FROM "{table}" '
        f"WHERE {column_sql} IS NOT NULL AND TRIM(CAST({column_sql} AS TEXT)) != '' "
        f"GROUP BY {column_sql} "
        f"ORDER BY count DESC"
    )
    if top_n:
        sql += f" LIMIT {int(top_n)}"

    rows = conn.execute(sql).fetchall()
    # Always return {value, count} so Gemini / the frontend can read them easily
    _ = label  # kept for clearer call sites / future labeled exports
    return [{"value": r["value"], "count": int(r["count"])} for r in rows]
