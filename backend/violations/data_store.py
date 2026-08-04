"""
Local cache of the SODA table.

Why a local cache?
  The Open HPD Violations dataset has millions of rows. We download it once
  into a SQLite file, then filter/sort/page from that file for the frontend.

Files live under backend/data/ (gitignored — too large to commit).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings

from .socrata_client import fetch_all_to_sqlite


# Columns we allow the API/frontend to sort by (must match SODA field names)
SORTABLE_COLUMNS = {
    "violationid",
    "buildingid",
    "boro",
    "housenumber",
    "streetname",
    "zip",
    "apartment",
    "class",
    "inspectiondate",
    "currentstatus",
    "currentstatusdate",
    "novdescription",
}


def sqlite_path() -> Path:
    """Full path to the local SQLite cache file."""
    return Path(settings.SOCRATA_SQLITE_PATH)


def table_name() -> str:
    """SQL table name inside the SQLite file."""
    return settings.SOCRATA_TABLE_NAME


def cache_exists() -> bool:
    """True when the local SQLite file already has our table."""
    path = sqlite_path()
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name(),),
        ).fetchone()
    return row is not None


def cached_row_count() -> int:
    """How many rows are currently stored locally."""
    if not cache_exists():
        return 0
    with sqlite3.connect(sqlite_path()) as conn:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table_name()}"').fetchone()
    return int(row[0]) if row else 0


def refresh_from_socrata(progress_callback=None, max_rows=None) -> dict[str, Any]:
    """
    One-time (or re-run) download of the SODA table into SQLite.

    1) COUNT(*) from the remote API
    2) Page through rows (past the 1000 default limit)
    3) Append each pandas page into backend/data/soda_violations.sqlite3

    Pass max_rows to download only a sample (for a quicker smoke test).
    """
    Path(settings.SOCRATA_DATA_DIR).mkdir(parents=True, exist_ok=True)
    return fetch_all_to_sqlite(
        sqlite_file=sqlite_path(),
        table=table_name(),
        page_size=settings.SOCRATA_PAGE_SIZE,
        max_rows=max_rows,
        progress_callback=progress_callback,
    )


def _build_where(
    *,
    search: str,
    boro: str,
    violation_class: str,
    status: str,
) -> tuple[str, list[Any]]:
    """
    Build a SQL WHERE clause + bound parameters from filter inputs.
    Using ? placeholders avoids SQL injection from user text.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if boro:
        clauses.append("UPPER(boro) = UPPER(?)")
        params.append(boro.strip())

    if violation_class:
        # SODA field name is literally "class"
        clauses.append('UPPER("class") = UPPER(?)')
        params.append(violation_class.strip())

    if status:
        clauses.append("currentstatus LIKE ?")
        params.append(f"%{status.strip()}%")

    if search:
        needle = f"%{search.strip()}%"
        clauses.append(
            "("
            "streetname LIKE ? OR housenumber LIKE ? OR novdescription LIKE ? "
            "OR violationid LIKE ? OR zip LIKE ? OR apartment LIKE ?"
            ")"
        )
        params.extend([needle, needle, needle, needle, needle, needle])

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def query_violations(
    *,
    search: str = "",
    boro: str = "",
    violation_class: str = "",
    status: str = "",
    sort: str = "inspectiondate",
    order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """
    Filter + sort + page the local SODA cache using SQL.

    Returns a dict ready for the JSON API:
      { count, page, page_size, total_pages, results, columns, ... }
    """
    if not cache_exists():
        return {
            "count": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "results": [],
            "columns": [],
            "cache_ready": False,
            "message": (
                "Local SODA cache is empty. Run: "
                "python manage.py fetch_soda_violations"
            ),
        }

    sort_col = sort if sort in SORTABLE_COLUMNS else "inspectiondate"
    # Quote "class" because it is a SQL keyword
    sort_sql = f'"{sort_col}"' if sort_col == "class" else sort_col
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    page = max(1, int(page))
    # Frontend inventory list can request larger pages for dynamic sizing
    page_size = max(1, min(int(page_size), 500))
    offset = (page - 1) * page_size

    where_sql, params = _build_where(
        search=search,
        boro=boro,
        violation_class=violation_class,
        status=status,
    )
    tbl = table_name()

    with sqlite3.connect(sqlite_path()) as conn:
        conn.row_factory = sqlite3.Row

        count_row = conn.execute(
            f'SELECT COUNT(*) AS n FROM "{tbl}" {where_sql}',
            params,
        ).fetchone()
        total = int(count_row["n"]) if count_row else 0

        rows = conn.execute(
            f'SELECT * FROM "{tbl}" {where_sql} '
            f"ORDER BY {sort_sql} {order_sql} "
            f"LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()

        # Column names from SQLite (stable order)
        col_info = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        columns = [c["name"] for c in col_info]

    results = [dict(row) for row in rows]
    total_pages = (total + page_size - 1) // page_size if total else 0

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "results": results,
        "columns": columns,
        "cache_ready": True,
        "cached_total": cached_row_count(),
    }


def filter_options() -> dict[str, list[str]]:
    """
    Distinct values for dropdown filters on the frontend.
    """
    if not cache_exists():
        return {"boro": [], "class": [], "currentstatus": []}

    tbl = table_name()
    with sqlite3.connect(sqlite_path()) as conn:
        boros = [
            r[0]
            for r in conn.execute(
                f'SELECT DISTINCT boro FROM "{tbl}" '
                f"WHERE boro IS NOT NULL AND TRIM(boro) != '' ORDER BY boro"
            )
        ]
        classes = [
            r[0]
            for r in conn.execute(
                f'SELECT DISTINCT "class" FROM "{tbl}" '
                f'WHERE "class" IS NOT NULL AND TRIM("class") != "" '
                f'ORDER BY "class"'
            )
        ]
        statuses = [
            r[0]
            for r in conn.execute(
                f'SELECT DISTINCT currentstatus FROM "{tbl}" '
                f"WHERE currentstatus IS NOT NULL AND TRIM(currentstatus) != '' "
                f"ORDER BY currentstatus"
            )
        ]

    return {"boro": boros, "class": classes, "currentstatus": statuses}
