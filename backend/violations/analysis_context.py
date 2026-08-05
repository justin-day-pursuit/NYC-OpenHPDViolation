"""
Build a compact "data pack" from the local Open HPD Violations cache for Gemini.

Why not send every row?
  The Open HPD Violations table can be ~3 million rows. Sending that to an
  AI model would be extremely slow and expensive. Instead we:

  1) Download the open table once into SQLite (fetch_soda_violations).
  2) Summarize with SQL (counts, group-bys, sample rows).
  3) Send that summary to Gemini when a browser session needs a fresh pack.

Filter-scoped analysis (inventory toolbar):
  If the user sets Search / Borough / Class / Status on the list, those same
  filters are applied here. Gemini then answers about the filtered slice —
  not always the full ~2.9M rows.

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
  Changing list filters and asking again refreshes the AI data pack for that
  filtered view (first ask after a filter change can take longer).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import data_store


def build_analysis_context(
    *,
    search: str = "",
    boro: str = "",
    violation_class: str = "",
    status: str = "",
    sample_size: int = 40,
    top_n: int = 20,
    month_count: int = 36,
    building_top_n: int = 20,
) -> dict[str, Any]:
    """
    Create the dataset summary Gemini will use for analysis.

    Optional filters match the inventory toolbar (search / boro / class / status).
    When any filter is set, every count below is for that filtered subset only.

    What this returns (plain English):
      - how many open-violation rows match the filters
      - which filters were applied
      - counts by borough / class / status / ZIP / month / building
      - class × borough crosstab
      - a small sample of real matching rows
    """
    if not data_store.cache_exists():
        raise RuntimeError(
            "Local SODA cache is empty. Run: python manage.py fetch_soda_violations"
        )

    tbl = data_store.table_name()
    path = data_store.sqlite_path()

    # Same WHERE clause the inventory list uses
    where_sql, where_params = data_store.build_filter_clause(
        search=search or "",
        boro=boro or "",
        violation_class=violation_class or "",
        status=status or "",
    )
    filters = {
        "search": (search or "").strip(),
        "boro": (boro or "").strip(),
        "class": (violation_class or "").strip(),
        "status": (status or "").strip(),
    }
    filters_active = any(filters.values())

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row

        # Full open-table size (helps the AI say "X of Y open violations")
        cache_total = int(conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0])

        # Rows matching the current inventory filters
        total = int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{tbl}" {where_sql}',
                where_params,
            ).fetchone()[0]
        )

        # Column list (same order the inventory list uses)
        col_info = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        columns = [c["name"] for c in col_info]

        # ---- Core group-bys (respect filters) ------------------------------
        by_boro = _group_counts(
            conn, tbl, "boro", where_sql, where_params, top_n=None
        )
        by_class = _group_counts(
            conn, tbl, '"class"', where_sql, where_params, top_n=None, key_name="class"
        )
        by_status = _group_counts(
            conn, tbl, "currentstatus", where_sql, where_params, top_n=top_n
        )
        by_zip = _group_counts(
            conn, tbl, "zip", where_sql, where_params, top_n=top_n
        )

        # ---- Richer aggregates ---------------------------------------------
        by_month = _monthly_counts(
            conn, tbl, where_sql, where_params, month_count=month_count
        )
        by_class_and_boro = _class_by_boro(conn, tbl, where_sql, where_params)
        by_building_top = _top_buildings(
            conn, tbl, where_sql, where_params, top_n=building_top_n
        )

        # Date range within the filtered slice (plausible years only)
        date_where = _and_where(
            where_sql,
            "inspectiondate IS NOT NULL AND TRIM(inspectiondate) != '' "
            "AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099'",
        )
        date_row = conn.execute(
            f'SELECT MIN(inspectiondate) AS min_d, MAX(inspectiondate) AS max_d '
            f'FROM "{tbl}" {date_where}',
            where_params,
        ).fetchone()

        # Sample of matching rows (newest inspections first)
        sample_where = _and_where(where_sql, "1=1")
        sample_rows = [
            {k: ("" if r[k] is None else r[k]) for k in r.keys()}
            for r in conn.execute(
                f'SELECT * FROM "{tbl}" {sample_where} '
                f"ORDER BY inspectiondate DESC "
                f"LIMIT ?",
                [*where_params, sample_size],
            ).fetchall()
        ]

    scope_note = (
        f"Aggregates use the current inventory filters "
        f"(search={filters['search']!r}, boro={filters['boro']!r}, "
        f"class={filters['class']!r}, status={filters['status']!r}). "
        f"{total:,} of {cache_total:,} open-violation rows match."
        if filters_active
        else (
            "No inventory filters applied — aggregates cover the entire local "
            f"open-violations cache ({cache_total:,} rows)."
        )
    )

    return {
        "dataset_id": "csn4-vhvf",
        "dataset_name": "Open HPD Violations",
        "source": "local_sqlite_cache_of_open_hpd_violations_only",
        "row_count": total,
        "cache_row_count": cache_total,
        "filters": {**filters, "active": filters_active},
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
            "about ~2.9 million in the full cache. Not the full historical table. "
            f"{scope_note} "
            "sample_rows is only a small example set for illustration. "
            f"by_month is the last {month_count} months (inspectiondate, years 1990–2099). "
            f"by_building_top lists the {building_top_n} buildings with the most matching rows."
        ),
    }


def _and_where(base_where: str, extra_sql: str) -> str:
    """
    Combine the inventory filter WHERE with an extra AND clause.

    base_where is "" or "WHERE ...".
    Maintainers: keep extra_sql as plain SQL fragments you trust (not user text).
    """
    extra = (extra_sql or "").strip()
    if not extra:
        return base_where
    if base_where:
        return f"{base_where} AND ({extra})"
    return f"WHERE {extra}"


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    column_sql: str,
    where_sql: str,
    where_params: list[Any],
    *,
    top_n: int | None,
    key_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Count rows grouped by one column, inside the filtered slice.

    column_sql may include quotes (needed for the field named "class").
    """
    label = key_name or column_sql.strip('"')
    combined = _and_where(
        where_sql,
        f"{column_sql} IS NOT NULL AND TRIM(CAST({column_sql} AS TEXT)) != ''",
    )
    sql = (
        f'SELECT {column_sql} AS value, COUNT(*) AS count '
        f'FROM "{table}" '
        f"{combined} "
        f"GROUP BY {column_sql} "
        f"ORDER BY count DESC"
    )
    if top_n:
        sql += f" LIMIT {int(top_n)}"

    rows = conn.execute(sql, where_params).fetchall()
    _ = label
    return [{"value": r["value"], "count": int(r["count"])} for r in rows]


def _monthly_counts(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str,
    where_params: list[Any],
    *,
    month_count: int,
) -> list[dict[str, Any]]:
    """Count inspections per calendar month inside the filtered slice."""
    combined = _and_where(
        where_sql,
        "inspectiondate IS NOT NULL "
        "AND length(trim(inspectiondate)) >= 7 "
        "AND substr(inspectiondate, 1, 4) BETWEEN '1990' AND '2099'",
    )
    sql = (
        f"SELECT substr(inspectiondate, 1, 7) AS value, COUNT(*) AS count "
        f'FROM "{table}" '
        f"{combined} "
        f"GROUP BY value "
        f"ORDER BY value DESC "
        f"LIMIT ?"
    )
    rows = conn.execute(sql, [*where_params, int(month_count)]).fetchall()
    points = [{"value": r["value"], "count": int(r["count"])} for r in rows]
    points.reverse()
    return points


def _class_by_boro(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str,
    where_params: list[Any],
) -> list[dict[str, Any]]:
    """Count borough × class combinations inside the filtered slice."""
    combined = _and_where(
        where_sql,
        "boro IS NOT NULL AND TRIM(boro) != '' "
        'AND "class" IS NOT NULL AND TRIM(CAST("class" AS TEXT)) != \'\'',
    )
    sql = (
        f'SELECT boro AS boro, "class" AS class, COUNT(*) AS count '
        f'FROM "{table}" '
        f"{combined} "
        f'GROUP BY boro, "class" '
        f"ORDER BY count DESC"
    )
    rows = conn.execute(sql, where_params).fetchall()
    return [
        {"boro": r["boro"], "class": r["class"], "count": int(r["count"])}
        for r in rows
    ]


def _top_buildings(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str,
    where_params: list[Any],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Buildings with the most matching rows (+ a simple address snapshot)."""
    combined = _and_where(
        where_sql,
        "buildingid IS NOT NULL AND TRIM(buildingid) != ''",
    )
    sql = (
        f"SELECT buildingid AS buildingid, "
        f"MAX(boro) AS boro, "
        f"MAX(housenumber) AS housenumber, "
        f"MAX(streetname) AS streetname, "
        f"COUNT(*) AS count "
        f'FROM "{table}" '
        f"{combined} "
        f"GROUP BY buildingid "
        f"ORDER BY count DESC "
        f"LIMIT ?"
    )
    rows = conn.execute(sql, [*where_params, int(top_n)]).fetchall()
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
