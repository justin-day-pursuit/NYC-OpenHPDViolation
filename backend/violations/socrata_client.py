"""
Talk to NYC Open Data (Socrata / SODA) using sodapy + pandas.

Dataset used by this project:
  https://data.cityofnewyork.us/api/v3/views/csn4-vhvf/query.json
  Dataset id: csn4-vhvf

Download flow (required order):
  1) Ask the API about rate / page limits (probe request + headers).
  2) Ask how many entries exist (COUNT(*)).
  3) Download every row with limit + offset paging (sodapy + pandas).

App token / credentials come from the root .env file
(see SOCRATA_* variables). Restart Django after editing .env.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from django.conf import settings
from sodapy import Socrata

logger = logging.getLogger(__name__)

# SODA defaults from Socrata docs:
#   - default page size is 1000
#   - maximum rows per request is typically 50_000
#   - with an app token, ~1000 requests / rolling hour is common
SODA_DEFAULT_PAGE_SIZE = 1000
SODA_ABSOLUTE_MAX_PAGE_SIZE = 50_000
SODA_APP_TOKEN_REQUESTS_PER_HOUR = 1000
SODA_NO_TOKEN_REQUESTS_PER_HOUR = 100  # shared IP pool — keep conservative


def _build_client() -> Socrata:
    """
    Create a sodapy Socrata client from Django settings / .env values.

    App token is strongly recommended (higher rate limits).
    Username/password are optional — only needed for write access.
    """
    return Socrata(
        settings.SOCRATA_DOMAIN,
        settings.SOCRATA_APP_TOKEN or None,
        username=settings.SOCRATA_USERNAME or None,
        password=settings.SOCRATA_PASSWORD or None,
        timeout=settings.SOCRATA_TIMEOUT,
    )


def _resource_url() -> str:
    """Classic SODA resource URL used by sodapy under the hood."""
    return (
        f"https://{settings.SOCRATA_DOMAIN}/resource/"
        f"{settings.SOCRATA_DATASET_ID}.json"
    )


def _app_token_headers() -> dict[str, str]:
    """HTTP headers for authenticated SODA requests (preferred X-App-Token)."""
    token = (settings.SOCRATA_APP_TOKEN or "").strip()
    if not token:
        return {}
    return {"X-App-Token": token}


def _extract_rate_headers(response: requests.Response) -> dict[str, str]:
    """
    Pull any rate-limit style headers the portal returns.

    Socrata does not always send these, so values may be empty —
    we still record whatever is present.
    """
    interesting = [
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "Retry-After",
        "X-Socrata-RequestId",
    ]
    found: dict[str, str] = {}
    for key in interesting:
        value = response.headers.get(key)
        if value:
            found[key] = value
    # Also catch any other header that mentions rate/limit/throttle
    for key, value in response.headers.items():
        lowered = key.lower()
        if any(word in lowered for word in ("rate", "limit", "throttle")):
            found[key] = value
    return found


def _probe_max_page_size() -> int:
    """
    Ask the API how large a single page can be.

    Tries the documented SODA max (50_000) with a tiny SELECT.
    If that is rejected, falls back to the default 1000.
    """
    url = _resource_url()
    headers = _app_token_headers()
    # Prefer configured page size, but never exceed the SODA absolute max
    desired = min(
        int(settings.SOCRATA_PAGE_SIZE or SODA_ABSOLUTE_MAX_PAGE_SIZE),
        SODA_ABSOLUTE_MAX_PAGE_SIZE,
    )

    for candidate in (desired, SODA_ABSOLUTE_MAX_PAGE_SIZE, SODA_DEFAULT_PAGE_SIZE):
        try:
            response = requests.get(
                url,
                params={"$select": "violationid", "$limit": candidate},
                headers=headers,
                timeout=settings.SOCRATA_TIMEOUT,
            )
            if response.status_code == 200:
                return candidate
            logger.warning(
                "Page-size probe failed for limit=%s (HTTP %s)",
                candidate,
                response.status_code,
            )
        except requests.RequestException as exc:
            logger.warning("Page-size probe error for limit=%s: %s", candidate, exc)

    return SODA_DEFAULT_PAGE_SIZE


def discover_api_limits() -> dict[str, Any]:
    """
    Step 1 — ask the API about rate / page limits before downloading.

    Makes a lightweight probe request, reads rate-limit headers (when present),
    and discovers the max rows-per-request (page size) we can use with $limit.
    """
    url = _resource_url()
    headers = _app_token_headers()
    has_app_token = bool(headers)

    response = requests.get(
        url,
        params={"$select": "violationid", "$limit": 1},
        headers=headers,
        timeout=settings.SOCRATA_TIMEOUT,
    )
    response.raise_for_status()

    rate_headers = _extract_rate_headers(response)
    page_limit = _probe_max_page_size()

    # Documented / inferred throttle when headers do not include a number
    documented_requests_per_hour = (
        SODA_APP_TOKEN_REQUESTS_PER_HOUR
        if has_app_token
        else SODA_NO_TOKEN_REQUESTS_PER_HOUR
    )
    header_limit = None
    for key in ("X-RateLimit-Limit", "RateLimit-Limit"):
        if key in rate_headers:
            try:
                header_limit = int(rate_headers[key])
            except ValueError:
                header_limit = None
            break

    limits = {
        "has_app_token": has_app_token,
        "page_limit": page_limit,  # use this as $limit when paging
        "default_page_limit": SODA_DEFAULT_PAGE_SIZE,
        "absolute_max_page_limit": SODA_ABSOLUTE_MAX_PAGE_SIZE,
        "requests_per_hour": header_limit or documented_requests_per_hour,
        "requests_per_hour_source": (
            "response_header" if header_limit is not None else "socrata_docs"
        ),
        "rate_limit_headers": rate_headers,
        "probe_status_code": response.status_code,
        "resource_url": url,
        "soda3_query_url": (
            f"https://{settings.SOCRATA_DOMAIN}/api/v3/views/"
            f"{settings.SOCRATA_DATASET_ID}/query.json"
        ),
    }
    logger.info(
        "SODA limits: page_limit=%s, requests_per_hour=%s (%s), app_token=%s",
        limits["page_limit"],
        limits["requests_per_hour"],
        limits["requests_per_hour_source"],
        has_app_token,
    )
    return limits


def get_record_count(client: Socrata | None = None) -> int:
    """
    Step 2 — ask the SODA endpoint how many rows are in the dataset.

    Uses: select="count(*)"  (SoQL)
    """
    owns_client = client is None
    client = client or _build_client()
    dataset_id = settings.SOCRATA_DATASET_ID

    try:
        result = client.get(dataset_id, select="count(*)")
    finally:
        if owns_client:
            client.close()

    if not result:
        return 0

    row = result[0]
    raw = row.get("count", row.get("COUNT", row.get("count_1", 0)))
    return int(raw)


def fetch_all_to_sqlite(
    sqlite_file: Path,
    table: str,
    page_size: int | None = None,
    max_rows: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """
    Download the SODA table into a local SQLite file.

    Required order:
      1. discover_api_limits()  — rate / page limits
      2. get_record_count()     — total entries
      3. page with limit+offset until the whole table is saved

    Each page is converted with pandas, then appended to SQLite.
    """
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)

    # Start from a fresh file so a failed mid-run does not leave a half-old table
    if sqlite_file.exists():
        sqlite_file.unlink()

    # ---- Step 1: rate / page limits -----------------------------------------
    limits = discover_api_limits()
    # Prefer the probed page limit; allow an explicit override from the caller
    effective_page_size = page_size or limits["page_limit"]
    if effective_page_size < 1:
        raise ValueError("page_size must be at least 1")

    client = _build_client()
    columns: list[str] = []
    rows_saved = 0

    try:
        # ---- Step 2: total entry count --------------------------------------
        remote_total = get_record_count(client)
        target = remote_total if max_rows is None else min(remote_total, max_rows)
        logger.info(
            "Socrata dataset %s reports %s rows; downloading %s with page_limit=%s",
            settings.SOCRATA_DATASET_ID,
            remote_total,
            target,
            effective_page_size,
        )

        if progress_callback:
            progress_callback(0, target)

        if target == 0:
            with sqlite3.connect(sqlite_file) as conn:
                conn.execute(f'CREATE TABLE "{table}" (violationid TEXT)')
            return {
                "rows_saved": 0,
                "columns": ["violationid"],
                "sqlite_path": str(sqlite_file),
                "remote_total": 0,
                "limits": limits,
            }

        # ---- Step 3: limit + offset paging ----------------------------------
        offset = 0
        first_page = True

        while offset < target:
            this_limit = min(effective_page_size, target - offset)
            chunk = _get_page_with_retry(
                client,
                settings.SOCRATA_DATASET_ID,
                limit=this_limit,
                offset=offset,
            )
            if not chunk:
                break

            df = pd.DataFrame.from_records(chunk)
            if first_page:
                columns = list(df.columns)

            with sqlite3.connect(sqlite_file) as conn:
                df.to_sql(
                    table,
                    conn,
                    if_exists="replace" if first_page else "append",
                    index=False,
                )

            first_page = False
            rows_saved += len(df)
            offset += len(chunk)

            if progress_callback:
                progress_callback(min(rows_saved, target), target)

            if len(chunk) < this_limit:
                break

        with sqlite3.connect(sqlite_file) as conn:
            conn.execute(f'CREATE INDEX IF NOT EXISTS idx_soda_boro ON "{table}" (boro)')
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS idx_soda_class ON "{table}" ("class")'
            )
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS idx_soda_status '
                f'ON "{table}" (currentstatus)'
            )
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS idx_soda_insp '
                f'ON "{table}" (inspectiondate)'
            )

        return {
            "rows_saved": rows_saved,
            "columns": columns,
            "sqlite_path": str(sqlite_file),
            "remote_total": remote_total,
            "page_limit_used": effective_page_size,
            "limits": limits,
        }
    finally:
        client.close()


def _get_page_with_retry(
    client: Socrata,
    dataset_id: str,
    *,
    limit: int,
    offset: int,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    """
    Fetch one page. If we hit HTTP 429 (rate limited), wait and retry.
    """
    delay = 2.0
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return client.get(dataset_id, limit=limit, offset=offset)
        except Exception as exc:  # sodapy raises on HTTP errors
            last_error = exc
            message = str(exc).lower()
            if "429" in message or "rate" in message or "throttl" in message:
                logger.warning(
                    "Rate limited on offset=%s (attempt %s/%s). Sleeping %.1fs",
                    offset,
                    attempt,
                    attempts,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise

    raise RuntimeError(
        f"Failed to fetch page at offset={offset} after {attempts} attempts: {last_error}"
    )


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Convert a DataFrame to JSON-safe list-of-dicts for the API response.
    Replaces pandas NaN with None so JSON encoding works cleanly.
    """
    if df is None or df.empty:
        return []
    clean = df.where(pd.notnull(df), None)
    return clean.to_dict(orient="records")
