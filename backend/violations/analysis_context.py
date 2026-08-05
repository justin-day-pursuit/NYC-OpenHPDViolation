"""
Build a compact "data pack" from the FULL local SODA cache for Gemini.

Why not send every row?
  The Open HPD Violations table can be ~3 million rows. Sending that to an
  AI model would be extremely slow and expensive. Instead we:

  1) Download the whole table once into SQLite (fetch_soda_violations).
  2) Summarize the WHOLE table with SQL (counts, group-bys, sample rows).
  3) Send that summary to Gemini the FIRST time in a browser session.

Dataset scope (important):
  This project caches ONLY "Open HPD Violations" (Socrata id csn4-vhvf),
  about ~2.9 million currently open rows. We do NOT download the full
  historical Housing Maintenance Code Violations table.

What the richer aggregates add (for better AI answers):
  - by_month              — inspection counts over recent months (trends)
  - by_class_and_boro     — class A/B/C broken down by borough
  - by_building_top       — buildings with the most open violations (+ address)

Non-technical tip:
  If AI answers feel out of date, re-run:
    python manage.py fetch_soda_violations
  so the local SQLite file matches NYC Open Data again.

  The first AI question in a tab can take longer because these SQL summaries
  run once; later questions in the same tab reuse the stored pack.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import data_store


def build_analysis_context(
    sample_size: int = 40,
    top_n: int = 20,
    month_count: int = 36,
    building_top_n: int = 20,
) -> dict[str, Any]:
    """
    Create the dataset summary Gemini will use for analysis.

    What this returns (plain English):
      - how many open-violation rows are in the local cache (~2.9M)
      - every column name
      - counts by borough / class / status / ZIP / month / building
      - class × borough crosstab
      - a small sample of real rows (so the AI can see real examples)

    This is computed from the ENTIRE local Open Violations cache, not just
    the current page shown in the browser.
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

        # ---- Core group-bys (same idea as the overview dashboard) -----------
        by_boro = _group_counts(conn, tbl, "boro", top_n=None)
        by_class = _group_counts(conn, tbl, '"class"', top_n=None, key_name="class")
        by_status = _group_counts(conn, tbl, "currentstatus", top_n=top_n)
        by_zip = _group_counts(conn, tbl, "zip", top_n=top_n)

        # ---- Richer aggregates for trend / comparison questions ------------
        # Monthly inspection trend (newest months, then chronological order)
        by_month = _monthly_counts(conn, tbl, month_count=month_count)

        # Class broken down inside each borough (answers "Class C in Bronx?")
        by_class_and_boro = _class_by_boro(conn, tbl)

        # Buildings with the most open violations (helps "worst buildings" questions)
        by_building_top = _top_buildings(conn, tbl, top_n=building_top_n)

        # Date range for inspectiondate (helps time-based questions)
        # Plausible years only — skips a few bad SODA years like "0219-..."
        date_row = conn.execute(
            f'SELECT MIN(inspectiondate) AS min_d, MAX(inspectiondate) AS max_d '
            f'FROM "{tbl}" '
            f"WHERE inspectiondate IS NOT NULL AND TRIM(inspectiondate) != '' "
            f"AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099'"
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
        "source": "local_sqlite_cache_of_open_hpd_violations_only",
        "row_count": total,
        "columns": columns,
        "inspectiondate_min": date_row["min_d"] if date_row else None,
        "inspectiondate_max": date_row["max_d"] if date_row else None,
        "aggregates": {
            "by_boro": by_boro,
            "by_class": by_class,
            "by_currentstatus": by_status,
            "by_zip_top": by_zip,
            "by_month": by_month,
            "by_class_and_boro": by_class_and_boro,
            "by_building_top": by_building_top,
        },
        "sample_rows": sample_rows,
        "notes": (
            "Dataset is Open HPD Violations only (csn4-vhvf) — currently open rows, "
            "about ~2.9 million. Not the full historical violations table. "
            "Aggregates cover the entire local open-violations cache. "
            "sample_rows is only a small example set for illustration. "
            f"by_month is the last {month_count} months (inspectiondate, years 1990–2099). "
            f"by_building_top lists the {building_top_n} buildings with the most open rows."
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


def _monthly_counts(
    conn: sqlite3.Connection,
    table: str,
    *,
    month_count: int,
) -> list[dict[str, Any]]:
    """
    Count inspections per calendar month (YYYY-MM from inspectiondate).

    Same idea as the overview dashboard trend chart. Returned oldest→newest
    so Gemini can describe trends in order.
    """
    sql = (
        f"SELECT substr(inspectiondate, 1, 7) AS value, COUNT(*) AS count "
        f'FROM "{table}" '
        f"WHERE inspectiondate IS NOT NULL "
        f"AND length(trim(inspectiondate)) >= 7 "
        f"AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099' "
        f"GROUP BY value "
        f"ORDER BY value DESC "
        f"LIMIT ?"
    )
    rows = conn.execute(sql, (int(month_count),)).fetchall()
    points = [{"value": r["value"], "count": int(r["count"])} for r in rows]
    points.reverse()
    return points


def _class_by_boro(
    conn: sqlite3.Connection,
    table: str,
) -> list[dict[str, Any]]:
    """
    Count rows for every borough × class combination.

    Example row: {"boro": "BRONX", "class": "C", "count": 180816}
    Maintainers: if this feels slow on first AI ask, that is normal on ~3M rows.
    """
    sql = (
        f'SELECT boro AS boro, "class" AS class, COUNT(*) AS count '
        f'FROM "{table}" '
        f"WHERE boro IS NOT NULL AND TRIM(boro) != '' "
        f'AND "class" IS NOT NULL AND TRIM(CAST("class" AS TEXT)) != \'\' '
        f'GROUP BY boro, "class" '
        f"ORDER BY count DESC"
    )
    rows = conn.execute(sql).fetchall()
    return [
        {"boro": r["boro"], "class": r["class"], "count": int(r["count"])}
        for r in rows
    ]


def _top_buildings(
    conn: sqlite3.Connection,
    table: str,
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """
    Buildings with the most violation rows, plus a simple address snapshot.

    MAX(boro/housenumber/streetname) is just a representative address for that
    buildingid (values are usually the same across rows for one building).
    """
    sql = (
        f"SELECT buildingid AS buildingid, "
        f"MAX(boro) AS boro, "
        f"MAX(housenumber) AS housenumber, "
        f"MAX(streetname) AS streetname, "
        f"COUNT(*) AS count "
        f'FROM "{table}" '
        f"WHERE buildingid IS NOT NULL AND TRIM(buildingid) != '' "
        f"GROUP BY buildingid "
        f"ORDER BY count DESC "
        f"LIMIT ?"
    )
    rows = conn.execute(sql, (int(top_n),)).fetchall()
    return [
        {
            "buildingid": r["buildingid"],
            "boro": r["boro"],
            "housenumber": r["housenumber"],
            "streetname": r["streetname"],
            "count": int(r["count"]),
        }
        for r in rows
    ]
