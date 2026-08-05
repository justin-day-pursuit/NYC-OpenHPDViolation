"""
Live NYC Open Data (SODA) helpers for notebooks and scripts.

IMPORTANT — where the data comes from:
  These helpers call the public Socrata / SODA API for Open HPD Violations
  (dataset id csn4-vhvf) DIRECTLY. They do NOT read backend/data/*.sqlite3.

  That means charts and counts reflect the current source on NYC Open Data,
  not a possibly stale local download.

How a non-technical maintainer runs this:
  1) Put SOCRATA_APP_TOKEN in the project-root .env file
     (copy from .env.example if needed).
  2) From notebooks/:
       python3 -m venv .venv
       source .venv/bin/activate
       pip install -r requirements.txt
  3) Open open_hpd_live_analysis.ipynb  OR  run:
       python run_live_analysis.py

Dataset page:
  https://data.cityofnewyork.us/Housing-Development/Open-HPD-Violations/csn4-vhvf
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sodapy import Socrata
from requests.exceptions import ReadTimeout, RequestException

# Project root = parent of notebooks/
ROOT_DIR = Path(__file__).resolve().parents[1]

# Defaults match the main app (.env.example)
DEFAULT_DOMAIN = "data.cityofnewyork.us"
DEFAULT_DATASET_ID = "csn4-vhvf"
DEFAULT_TIMEOUT = 300  # big COUNT / GROUP BY queries can be slow
DEFAULT_RETRIES = 3


def load_socrata_settings(env_path: Path | None = None) -> dict[str, Any]:
    """
    Read Socrata settings from the root .env file.

    Non-technical tip:
      Edit the file named ".env" in the project root (not this folder).
      Restart the notebook kernel after changing .env.
    """
    path = env_path or (ROOT_DIR / ".env")
    # override=False keeps any values already exported in the shell
    load_dotenv(path, override=False)

    token = (os.getenv("SOCRATA_APP_TOKEN") or "").strip()
    return {
        "domain": (os.getenv("SOCRATA_DOMAIN") or DEFAULT_DOMAIN).strip(),
        "dataset_id": (os.getenv("SOCRATA_DATASET_ID") or DEFAULT_DATASET_ID).strip(),
        "app_token": token or None,
        "timeout": int(os.getenv("SOCRATA_TIMEOUT") or DEFAULT_TIMEOUT),
        "env_path": str(path),
        "has_app_token": bool(token),
    }


def make_client(settings: dict[str, Any] | None = None) -> Socrata:
    """
    Create a sodapy client pointed at NYC Open Data.

    An app token is strongly recommended (higher rate limits / fewer timeouts).
    """
    cfg = settings or load_socrata_settings()
    return Socrata(
        cfg["domain"],
        cfg["app_token"],
        timeout=cfg["timeout"],
    )


def _soda_get(
    client: Socrata,
    dataset_id: str,
    *,
    retries: int = DEFAULT_RETRIES,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Call client.get with simple retries.

    NYC Open Data sometimes times out on COUNT/GROUP BY for ~3M rows.
    Maintainers: if this still fails, wait a minute and re-run the cell/script,
    or add/check SOCRATA_APP_TOKEN in the root .env file.
    """
    last_error: Exception | None = None
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            return client.get(dataset_id, **kwargs)
        except (ReadTimeout, RequestException) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            # Brief pause before retry (portal can be busy)
            time.sleep(2 * attempt)
            print(
                f"SODA request timed out/failed (attempt {attempt}/{attempts}); retrying…"
            )
    assert last_error is not None
    raise last_error


def get_live_count(
    client: Socrata | None = None,
    dataset_id: str | None = None,
    where: str | None = None,
) -> int:
    """
    Ask the LIVE SODA endpoint how many open-violation rows exist right now.

    Pass where= (SoQL) to count a filtered slice, e.g. where=\"boro='BRONX'\".
    """
    cfg = load_socrata_settings()
    owns = client is None
    client = client or make_client(cfg)
    ds = dataset_id or cfg["dataset_id"]
    kwargs: dict[str, Any] = {"select": "count(*)"}
    if where:
        kwargs["where"] = where
    try:
        rows = _soda_get(client, ds, **kwargs)
    finally:
        if owns:
            client.close()
    if not rows:
        return 0
    raw = rows[0].get("count") or rows[0].get("COUNT") or 0
    return int(raw)


def fetch_group_counts(
    column: str,
    *,
    client: Socrata | None = None,
    dataset_id: str | None = None,
    where: str | None = None,
    top_n: int | None = None,
) -> pd.DataFrame:
    """
    Live SoQL group-by: COUNT(*) for each value of `column`.

    Example:
      fetch_group_counts("boro")
      fetch_group_counts("class", where="boro='BRONX'")

    Returns a DataFrame with columns: name, value  (ready for plotting).
    """
    cfg = load_socrata_settings()
    owns = client is None
    client = client or make_client(cfg)
    ds = dataset_id or cfg["dataset_id"]

    # "class" is a reserved word in SoQL — leave it unquoted; sodapy/Socrata accept it
    select = f"{column}, count(*) as count"
    kwargs: dict[str, Any] = {
        "select": select,
        "group": column,
        "order": "count DESC",
    }
    if where:
        kwargs["where"] = where
    if top_n:
        kwargs["limit"] = int(top_n)

    try:
        rows = _soda_get(client, ds, **kwargs)
    finally:
        if owns:
            client.close()

    frame = pd.DataFrame.from_records(rows or [])
    if frame.empty:
        return pd.DataFrame(columns=["name", "value"])

    # Normalize to name/value for charts
    name_col = column if column in frame.columns else frame.columns[0]
    out = pd.DataFrame(
        {
            "name": frame[name_col].astype(str),
            "value": pd.to_numeric(frame["count"], errors="coerce").fillna(0).astype(int),
        }
    )
    return out


def fetch_monthly_counts(
    *,
    client: Socrata | None = None,
    dataset_id: str | None = None,
    where: str | None = None,
    month_count: int = 36,
) -> pd.DataFrame:
    """
    Live monthly inspection counts using SoQL date_trunc_ym(inspectiondate).

    Returns DataFrame columns: name (YYYY-MM), value (count), oldest → newest.
    """
    cfg = load_socrata_settings()
    owns = client is None
    client = client or make_client(cfg)
    ds = dataset_id or cfg["dataset_id"]

    kwargs: dict[str, Any] = {
        "select": "date_trunc_ym(inspectiondate) as month, count(*) as count",
        "group": "month",
        "order": "month DESC",
        "limit": int(month_count),
    }
    if where:
        kwargs["where"] = where

    try:
        rows = _soda_get(client, ds, **kwargs)
    finally:
        if owns:
            client.close()

    frame = pd.DataFrame.from_records(rows or [])
    if frame.empty:
        return pd.DataFrame(columns=["name", "value"])

    # month comes back like "2026-07-01T00:00:00.000" → keep YYYY-MM
    months = (
        frame["month"]
        .astype(str)
        .str.slice(0, 7)
    )
    out = pd.DataFrame(
        {
            "name": months,
            "value": pd.to_numeric(frame["count"], errors="coerce").fillna(0).astype(int),
        }
    )
    # API returned newest-first; reverse for left→right charts
    return out.iloc[::-1].reset_index(drop=True)


def fetch_sample_rows(
    *,
    client: Socrata | None = None,
    dataset_id: str | None = None,
    limit: int = 500,
    where: str | None = None,
    order: str = "inspectiondate DESC",
) -> pd.DataFrame:
    """
    Pull a small LIVE sample of rows into pandas (for tables / spot-checks).

    Do NOT ask for millions of rows here — use group-by helpers for totals.
    """
    cfg = load_socrata_settings()
    owns = client is None
    client = client or make_client(cfg)
    ds = dataset_id or cfg["dataset_id"]

    kwargs: dict[str, Any] = {
        "limit": int(limit),
        "order": order,
    }
    if where:
        kwargs["where"] = where

    try:
        rows = _soda_get(client, ds, **kwargs)
    finally:
        if owns:
            client.close()

    return pd.DataFrame.from_records(rows or [])


def fetch_live_overview(
    *,
    where: str | None = None,
    status_top_n: int = 15,
    month_count: int = 36,
) -> dict[str, Any]:
    """
    One-stop live summary for notebooks: count + common group-bys.

    Reuses one HTTP client for all queries, then closes it.
    """
    cfg = load_socrata_settings()
    client = make_client(cfg)
    try:
        # Filtered count when where= is set; otherwise full open table
        total = get_live_count(client, cfg["dataset_id"], where=where)
        by_boro = fetch_group_counts(
            "boro", client=client, dataset_id=cfg["dataset_id"], where=where
        )
        by_class = fetch_group_counts(
            "class", client=client, dataset_id=cfg["dataset_id"], where=where
        )
        by_status = fetch_group_counts(
            "currentstatus",
            client=client,
            dataset_id=cfg["dataset_id"],
            where=where,
            top_n=status_top_n,
        )
        by_month = fetch_monthly_counts(
            client=client,
            dataset_id=cfg["dataset_id"],
            where=where,
            month_count=month_count,
        )
        sample = fetch_sample_rows(
            client=client,
            dataset_id=cfg["dataset_id"],
            where=where,
            limit=20,
        )
    finally:
        client.close()

    return {
        "settings": {
            "domain": cfg["domain"],
            "dataset_id": cfg["dataset_id"],
            "has_app_token": cfg["has_app_token"],
            "source": "live_socrata_soda_api",
            "where": where or "",
        },
        "row_count": total,
        "by_boro": by_boro,
        "by_class": by_class,
        "by_currentstatus": by_status,
        "by_month": by_month,
        "sample_rows": sample,
    }
