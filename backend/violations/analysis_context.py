"""
Build a compact "data pack" for Gemini from the LIVE SODA API.

Why not send every row?
  The Open HPD Violations table can be ~3 million rows. Instead we ask the
  NYC Open Data API for SQL-style aggregates (counts / group-bys) and a small
  sample of rows, then send that summary to Gemini.

Filter-scoped analysis:
  Inventory toolbar filters (Search / Borough / Class / Status) become a SoQL
  WHERE clause so Gemini answers about the same slice the list shows.

No local SQLite cache — every pack is built from the live source.

Non-technical tip:
  The first AI ask can take several minutes (remote GROUP BY on ~3M rows).
  Ensure SOCRATA_APP_TOKEN is set in the root .env file.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from . import data_store, socrata_client


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
    Create the dataset summary Gemini will use for analysis (LIVE API).
    """
    where = data_store.build_soql_where(
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

    try:
        cache_total = socrata_client.get_record_count()
        total = socrata_client.get_record_count(where=where)

        by_boro = _as_value_count(
            socrata_client.fetch_group_counts("boro", where=where)
        )
        by_class = _as_value_count(
            socrata_client.fetch_group_counts("class", where=where)
        )
        by_status = _as_value_count(
            socrata_client.fetch_group_counts(
                "currentstatus", where=where, top_n=top_n
            )
        )
        by_zip = _as_value_count(
            socrata_client.fetch_group_counts("zip", where=where, top_n=top_n)
        )
        by_month = _as_value_count(
            socrata_client.fetch_monthly_counts(where=where, month_count=month_count)
        )
        by_class_and_boro = _class_by_boro(where=where)
        by_building_top = _top_buildings(where=where, top_n=building_top_n)

        sample_rows = socrata_client.fetch_page(
            limit=sample_size,
            offset=0,
            where=where,
            order="inspectiondate DESC",
        )
        # Normalize blanks for the AI
        sample_rows = [
            {k: ("" if v is None else v) for k, v in row.items()}
            for row in sample_rows
        ]

        date_bounds = _date_bounds(where=where)
    except Exception as exc:
        raise RuntimeError(
            "Could not build analysis context from the live SODA API. "
            f"Detail: {exc}. Check SOCRATA_APP_TOKEN in .env."
        ) from exc

    columns = list(sample_rows[0].keys()) if sample_rows else list(data_store.ALL_COLUMNS)

    scope_note = (
        f"Aggregates use the current inventory filters "
        f"(search={filters['search']!r}, boro={filters['boro']!r}, "
        f"class={filters['class']!r}, status={filters['status']!r}). "
        f"{total:,} of {cache_total:,} open-violation rows match."
        if filters_active
        else (
            "No inventory filters applied — aggregates cover the full live "
            f"open-violations table ({cache_total:,} rows)."
        )
    )

    return {
        "dataset_id": settings.SOCRATA_DATASET_ID,
        "dataset_name": "Open HPD Violations",
        "source": "live_socrata_soda_api",
        "row_count": total,
        "cache_row_count": cache_total,  # full live table size (name kept for AI prompts)
        "filters": {**filters, "active": filters_active},
        "columns": columns,
        "inspectiondate_min": date_bounds.get("min"),
        "inspectiondate_max": date_bounds.get("max"),
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
            "Dataset is Open HPD Violations only (csn4-vhvf) — currently open rows "
            "from the LIVE NYC Open Data API. Not a local file cache. "
            f"{scope_note} "
            "sample_rows is only a small example set for illustration."
        ),
    }


def _as_value_count(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert {name,value} chart rows into {value,count} for Gemini."""
    return [{"value": r["name"], "count": int(r["value"])} for r in rows]


def _class_by_boro(*, where: str | None) -> list[dict[str, Any]]:
    """Live borough × class crosstab."""
    kwargs: dict[str, Any] = {
        "select": "boro, class, count(*) as count",
        "group": "boro, class",
        "order": "count DESC",
    }
    if where:
        kwargs["where"] = where
    rows = socrata_client.soda_get(**kwargs)
    return [
        {
            "boro": r.get("boro"),
            "class": r.get("class"),
            "count": int(r.get("count") or 0),
        }
        for r in rows or []
        if r.get("boro") and r.get("class")
    ]


def _top_buildings(*, where: str | None, top_n: int) -> list[dict[str, Any]]:
    """
    Buildings with the most matching open violations (live).

    Returns buildingid + count. (Address lookup would need extra API calls;
    Gemini can still rank buildings by id and count.)
    """
    kwargs: dict[str, Any] = {
        "select": "buildingid, count(*) as count",
        "group": "buildingid",
        "order": "count DESC",
        "limit": int(top_n),
    }
    if where:
        kwargs["where"] = where
    rows = socrata_client.soda_get(**kwargs)
    return [
        {
            "buildingid": r.get("buildingid"),
            "boro": "",
            "housenumber": "",
            "streetname": "",
            "count": int(r.get("count") or 0),
        }
        for r in rows or []
        if r.get("buildingid")
    ]


def _date_bounds(*, where: str | None) -> dict[str, Any]:
    """Best-effort min/max inspectiondate from the live API."""
    kwargs: dict[str, Any] = {
        "select": "min(inspectiondate) as min_d, max(inspectiondate) as max_d",
    }
    if where:
        kwargs["where"] = where
    try:
        rows = socrata_client.soda_get(**kwargs)
        if not rows:
            return {"min": None, "max": None}
        return {"min": rows[0].get("min_d"), "max": rows[0].get("max_d")}
    except Exception:
        return {"min": None, "max": None}
