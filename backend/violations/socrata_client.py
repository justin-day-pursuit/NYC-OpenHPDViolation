"""
Talk to NYC Open Data (Socrata / SODA) using sodapy — LIVE queries only.

Dataset (OPEN violations only):
  https://data.cityofnewyork.us/api/v3/views/csn4-vhvf/query.json
  Dataset id: csn4-vhvf  (~2.9 million currently open rows)

This module does NOT download or store a local SQLite copy.
Every list page, chart, and AI summary asks the SODA API for fresh data.

Non-technical tip:
  Put SOCRATA_APP_TOKEN in the root .env file. Without it, requests are
  slower and more likely to time out. Restart Django after editing .env.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings
from requests.exceptions import ReadTimeout, RequestException
from sodapy import Socrata

logger = logging.getLogger(__name__)

SODA_DEFAULT_PAGE_SIZE = 1000
SODA_ABSOLUTE_MAX_PAGE_SIZE = 50_000
SODA_APP_TOKEN_REQUESTS_PER_HOUR = 1000
SODA_NO_TOKEN_REQUESTS_PER_HOUR = 100
DEFAULT_RETRIES = 3


def _build_client() -> Socrata:
    """Create a sodapy client from Django settings / root .env values."""
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
    """Pull any rate-limit style headers the portal returns."""
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
    for key, value in response.headers.items():
        lowered = key.lower()
        if any(word in lowered for word in ("rate", "limit", "throttl")):
            found[key] = value
    return found


def soda_get(
    client: Socrata | None = None,
    *,
    retries: int = DEFAULT_RETRIES,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Call sodapy get() with retries for timeouts / brief portal hiccups.

    Non-technical tip:
      If charts or the list keep failing, wait a minute and click Refresh,
      and confirm SOCRATA_APP_TOKEN is set in .env.
    """
    owns = client is None
    client = client or _build_client()
    dataset_id = settings.SOCRATA_DATASET_ID
    last_error: Exception | None = None
    attempts = max(1, int(retries))

    try:
        for attempt in range(1, attempts + 1):
            try:
                return client.get(dataset_id, **kwargs)
            except (ReadTimeout, RequestException) as exc:
                last_error = exc
                message = str(exc).lower()
                retryable = (
                    isinstance(exc, ReadTimeout)
                    or "429" in message
                    or "rate" in message
                    or "throttl" in message
                    or "timeout" in message
                )
                if not retryable or attempt >= attempts:
                    break
                delay = 2.0 * attempt
                logger.warning(
                    "SODA request failed (attempt %s/%s): %s — sleeping %.1fs",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
            except Exception as exc:
                # sodapy sometimes wraps HTTP errors as generic Exception
                last_error = exc
                message = str(exc).lower()
                if ("429" in message or "rate" in message) and attempt < attempts:
                    time.sleep(2.0 * attempt)
                    continue
                raise
    finally:
        if owns:
            client.close()

    raise RuntimeError(
        f"SODA request failed after {attempts} attempts: {last_error}"
    )


def discover_api_limits() -> dict[str, Any]:
    """
    Probe the SODA endpoint for practical page / rate limits.

    Still useful for status displays; we no longer use this to download
    the whole table into a file.
    """
    has_app_token = bool((settings.SOCRATA_APP_TOKEN or "").strip())
    page_limit = min(
        int(settings.SOCRATA_PAGE_SIZE or SODA_ABSOLUTE_MAX_PAGE_SIZE),
        SODA_ABSOLUTE_MAX_PAGE_SIZE,
    )
    # Tiny probe request — confirms the endpoint answers
    headers = _app_token_headers()
    response = requests.get(
        _resource_url(),
        params={"$limit": 1},
        headers=headers,
        timeout=min(60, settings.SOCRATA_TIMEOUT),
    )
    response.raise_for_status()
    rate_headers = _extract_rate_headers(response)
    return {
        "page_limit": page_limit,
        "default_page_size": SODA_DEFAULT_PAGE_SIZE,
        "absolute_max_page_size": SODA_ABSOLUTE_MAX_PAGE_SIZE,
        "has_app_token": has_app_token,
        "requests_per_hour_estimate": (
            SODA_APP_TOKEN_REQUESTS_PER_HOUR
            if has_app_token
            else SODA_NO_TOKEN_REQUESTS_PER_HOUR
        ),
        "rate_headers": rate_headers,
        "source": "live_socrata_soda_api",
    }


def get_record_count(
    client: Socrata | None = None,
    *,
    where: str | None = None,
) -> int:
    """Ask the LIVE SODA endpoint how many rows match (optional SoQL where)."""
    owns = client is None
    client = client or _build_client()
    kwargs: dict[str, Any] = {"select": "count(*)"}
    if where:
        kwargs["where"] = where
    try:
        rows = soda_get(client, **kwargs)
    finally:
        if owns:
            client.close()
    if not rows:
        return 0
    raw = rows[0].get("count") or rows[0].get("COUNT") or 0
    return int(raw)


def fetch_page(
    *,
    limit: int,
    offset: int,
    where: str | None = None,
    order: str | None = None,
    client: Socrata | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch one page of violation rows from the LIVE API.

    Used by the inventory list (filter + sort + pagination).
    """
    kwargs: dict[str, Any] = {
        "limit": max(1, int(limit)),
        "offset": max(0, int(offset)),
    }
    if where:
        kwargs["where"] = where
    if order:
        kwargs["order"] = order
    return soda_get(client, **kwargs)


def fetch_group_counts(
    column: str,
    *,
    where: str | None = None,
    top_n: int | None = None,
    client: Socrata | None = None,
) -> list[dict[str, Any]]:
    """
    Live SoQL GROUP BY count for one column.

    Returns [{"name": "...", "value": 123}, ...] sorted by count descending.
    """
    kwargs: dict[str, Any] = {
        "select": f"{column}, count(*) as count",
        "group": column,
        "order": "count DESC",
    }
    if where:
        kwargs["where"] = where
    if top_n:
        kwargs["limit"] = int(top_n)

    rows = soda_get(client, **kwargs)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        name = row.get(column)
        if name is None or str(name).strip() == "":
            continue
        out.append({"name": str(name), "value": int(row.get("count") or 0)})
    return out


def fetch_monthly_counts(
    *,
    where: str | None = None,
    month_count: int = 36,
    client: Socrata | None = None,
) -> list[dict[str, Any]]:
    """
    Live monthly inspection counts via date_trunc_ym(inspectiondate).

    Returns oldest → newest [{"name": "YYYY-MM", "value": n}, ...].
    """
    kwargs: dict[str, Any] = {
        "select": "date_trunc_ym(inspectiondate) as month, count(*) as count",
        "group": "month",
        "order": "month DESC",
        "limit": int(month_count),
    }
    if where:
        kwargs["where"] = where

    rows = soda_get(client, **kwargs)
    points: list[dict[str, Any]] = []
    for row in rows or []:
        month = str(row.get("month") or "")
        if len(month) < 7:
            continue
        points.append({"name": month[:7], "value": int(row.get("count") or 0)})
    points.reverse()
    return points
