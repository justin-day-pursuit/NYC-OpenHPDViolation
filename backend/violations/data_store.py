"""
Live Open HPD Violations queries (no local SQLite cache).

What this file does:
  Translates inventory filters into SoQL, then asks the NYC Open Data SODA
  API for pages, counts, and filter dropdown values — always fresh from source.

Non-technical tip:
  If the list is empty or slow, check SOCRATA_APP_TOKEN in the root .env and
  that your machine can reach data.cityofnewyork.us. You do NOT need to run
  fetch_soda_violations anymore (that command was removed).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from . import socrata_client

# Full SODA column set for Open HPD Violations (csn4-vhvf).
# The frontend shows every one of these, even when a cell is blank.
ALL_COLUMNS = [
    "violationid",
    "buildingid",
    "registrationid",
    "boroid",
    "boro",
    "housenumber",
    "lowhousenumber",
    "highhousenumber",
    "streetname",
    "streetcode",
    "zip",
    "apartment",
    "story",
    "block",
    "lot",
    "class",
    "inspectiondate",
    "approveddate",
    "originalcertifybydate",
    "originalcorrectbydate",
    "newcertifybydate",
    "newcorrectbydate",
    "certifieddate",
    "ordernumber",
    "novid",
    "novdescription",
    "novissueddate",
    "currentstatusid",
    "currentstatus",
    "currentstatusdate",
]

SORTABLE_COLUMNS = set(ALL_COLUMNS)


def escape_soql(value: str) -> str:
    """Escape single quotes for safe SoQL string literals."""
    return (value or "").replace("'", "''")


def build_soql_where(
    *,
    search: str = "",
    boro: str = "",
    violation_class: str = "",
    status: str = "",
) -> str | None:
    """
    Build a SoQL WHERE clause from inventory toolbar filters.

    Same meaning as the old SQLite filters — Search / Borough / Class / Status.
    Returns None when nothing is filtered (whole open-violations table).
    """
    clauses: list[str] = []

    if boro:
        clauses.append(f"upper(boro)='{escape_soql(boro.strip().upper())}'")

    if violation_class:
        # Field name is literally "class" (works in SoQL without quotes here)
        clauses.append(f"upper(class)='{escape_soql(violation_class.strip().upper())}'")

    if status:
        needle = escape_soql(status.strip().upper())
        clauses.append(f"upper(currentstatus) like '%{needle}%'")

    if search:
        needle = escape_soql(search.strip().upper())
        clauses.append(
            "("
            f"upper(streetname) like '%{needle}%' OR "
            f"upper(housenumber) like '%{needle}%' OR "
            f"upper(novdescription) like '%{needle}%' OR "
            f"upper(violationid) like '%{needle}%' OR "
            f"upper(zip) like '%{needle}%' OR "
            f"upper(apartment) like '%{needle}%'"
            ")"
        )

    if not clauses:
        return None
    return " AND ".join(clauses)


# Back-compat name used by analysis_context / older call sites
def build_filter_clause(
    *,
    search: str = "",
    boro: str = "",
    violation_class: str = "",
    status: str = "",
) -> tuple[str | None, list[Any]]:
    """
    Return (soql_where, []) — second value kept empty for call-site compatibility.
    (We no longer use SQL bound parameters; SoQL is a single where string.)
    """
    return (
        build_soql_where(
            search=search,
            boro=boro,
            violation_class=violation_class,
            status=status,
        ),
        [],
    )


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
    Filter + sort + page LIVE from SODA.

    Returns the same JSON shape the frontend inventory list already expects.
    """
    sort_col = sort if sort in SORTABLE_COLUMNS else "inspectiondate"
    order_sql = "DESC" if str(order).lower() == "desc" else "ASC"

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    offset = (page - 1) * page_size

    where = build_soql_where(
        search=search,
        boro=boro,
        violation_class=violation_class,
        status=status,
    )

    try:
        total = socrata_client.get_record_count(where=where)
        rows = socrata_client.fetch_page(
            limit=page_size,
            offset=offset,
            where=where,
            order=f"{sort_col} {order_sql}",
        )
    except Exception as exc:
        return {
            "count": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "results": [],
            "columns": list(ALL_COLUMNS),
            "source": "live_socrata_soda_api",
            "error": str(exc),
            "message": (
                "Could not load violations from NYC Open Data. "
                "Check SOCRATA_APP_TOKEN in .env and your network connection."
            ),
        }

    # Prefer columns from the first live row, then fill known SODA fields
    columns = list(rows[0].keys()) if rows else list(ALL_COLUMNS)
    for name in ALL_COLUMNS:
        if name not in columns:
            columns.append(name)

    results = []
    for raw in rows:
        normalized = {}
        for name in columns:
            value = raw.get(name)
            normalized[name] = "" if value is None else value
        results.append(normalized)

    total_pages = (total + page_size - 1) // page_size if total else 0

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "results": results,
        "columns": columns,
        "source": "live_socrata_soda_api",
        "dataset_id": settings.SOCRATA_DATASET_ID,
    }


def filter_options() -> dict[str, list[str]]:
    """
    Distinct borough / class / status values for frontend dropdowns (LIVE).
    """
    try:
        boros = [r["name"] for r in socrata_client.fetch_group_counts("boro")]
        classes = [r["name"] for r in socrata_client.fetch_group_counts("class")]
        statuses = [
            r["name"]
            for r in socrata_client.fetch_group_counts("currentstatus", top_n=200)
        ]
    except Exception:
        return {"boro": [], "class": [], "currentstatus": []}

    # Sort for stable dropdowns
    return {
        "boro": sorted(boros),
        "class": sorted(classes),
        "currentstatus": sorted(statuses),
    }


def remote_status() -> dict[str, Any]:
    """
    Lightweight status for the topbar: live API reachability + row count.
    """
    payload: dict[str, Any] = {
        "source": "live_socrata_soda_api",
        "dataset_id": settings.SOCRATA_DATASET_ID,
        "domain": settings.SOCRATA_DOMAIN,
        "has_app_token": bool(settings.SOCRATA_APP_TOKEN),
        "api_ready": False,
        "remote_rows": None,
    }
    try:
        payload["remote_rows"] = socrata_client.get_record_count()
        payload["api_ready"] = True
    except Exception as exc:
        payload["error"] = str(exc)
    return payload
