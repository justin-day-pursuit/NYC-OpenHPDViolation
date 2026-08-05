"""
API views for violations.

These are the functions/classes that handle HTTP requests under /api/...
"""

import requests
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import data_store
from .analysis_context import build_analysis_context
from .analytics import build_dashboard_stats
from .models import Violation
from .serializers import ViolationSerializer
from .socrata_client import discover_api_limits, get_record_count

# session_ids that already sent their one-time data pack to the AI service
# (process-local; resets when Django restarts — that is OK for local/dev)
_AI_SESSIONS_WITH_DATA: set[str] = set()


class ViolationViewSet(viewsets.ModelViewSet):
    """
    Full CRUD API for Violation records stored in Django's own database.

    Examples (once the server is running):
      GET    /api/violations/       — list all
      POST   /api/violations/       — create one
      GET    /api/violations/1/     — get one by id
      PUT    /api/violations/1/     — replace one
      PATCH  /api/violations/1/     — update some fields
      DELETE /api/violations/1/     — delete one
    """

    queryset = Violation.objects.all()
    serializer_class = ViolationSerializer


@api_view(["GET"])
def soda_violations(request):
    """
    Read the local SODA cache with filters + sorting + pagination.

    Query parameters (all optional):
      search   — free-text match on street, house #, description, id, zip, apt
      boro     — exact borough, e.g. BRONX
      class    — violation class A / B / C
      status   — substring match on currentstatus
      sort     — column name (default: inspectiondate)
      order    — asc or desc (default: desc)
      page     — page number starting at 1
      page_size — rows per page (max 200)

    Example:
      /api/soda-violations/?boro=BRONX&class=C&sort=inspectiondate&order=desc
    """
    def _as_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    payload = data_store.query_violations(
        search=request.query_params.get("search", ""),
        boro=request.query_params.get("boro", ""),
        violation_class=request.query_params.get("class", ""),
        status=request.query_params.get("status", ""),
        sort=request.query_params.get("sort", "inspectiondate"),
        order=request.query_params.get("order", "desc"),
        page=_as_int(request.query_params.get("page", 1), 1),
        page_size=_as_int(request.query_params.get("page_size", 50), 50),
    )
    return Response(payload)


@api_view(["GET"])
def soda_filter_options(request):
    """
    Distinct borough / class / status values for frontend dropdowns.
    """
    return Response(data_store.filter_options())


@api_view(["GET"])
def soda_stats(request):
    """
    Dashboard chart data from the FULL local SODA cache (no AI).

    Returns counts ready for Recharts:
      by_boro, by_class, by_currentstatus, by_month

    Optional query parameters (advanced — defaults are fine for most users):
      status_top_n  — how many status bars to keep (default 15)
      months        — how many recent months on the trend line (default 36)

    Non-technical tip:
      Open this URL in a browser to peek at the numbers:
        http://127.0.0.1:8000/api/soda-violations/stats/
      If it says the cache is empty, run:
        python manage.py fetch_soda_violations
    """

    def _as_int(value, default, *, minimum=1, maximum=120):
        # Clamp so a typo in the URL cannot request millions of buckets
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(n, maximum))

    payload = build_dashboard_stats(
        status_top_n=_as_int(
            request.query_params.get("status_top_n"), 15, minimum=1, maximum=50
        ),
        month_count=_as_int(
            request.query_params.get("months"), 36, minimum=1, maximum=120
        ),
    )
    return Response(payload)


@api_view(["GET"])
def soda_status(request):
    """
    Show whether the local cache is ready.

    Optional query flags:
      ?remote=1  — also COUNT(*) on Socrata (slower)
      ?limits=1  — also probe rate / page limits on Socrata (slower)
    """
    payload = {
        "cache_ready": data_store.cache_exists(),
        "cached_rows": data_store.cached_row_count(),
        "dataset_id": settings.SOCRATA_DATASET_ID,
        "domain": settings.SOCRATA_DOMAIN,
        "has_app_token": bool(settings.SOCRATA_APP_TOKEN),
    }
    if request.query_params.get("limits") in ("1", "true", "yes"):
        try:
            payload["limits"] = discover_api_limits()
        except Exception as exc:  # pragma: no cover - network failures
            payload["limits_error"] = str(exc)
    if request.query_params.get("remote") in ("1", "true", "yes"):
        try:
            payload["remote_rows"] = get_record_count()
        except Exception as exc:  # pragma: no cover - network failures
            payload["remote_error"] = str(exc)
    return Response(payload)


@api_view(["POST"])
def soda_refresh(request):
    """
    Re-download the full SODA table into the local SQLite cache.

    This can take a long time (~3 million rows). Prefer the management command
    for the first load:
      python manage.py fetch_soda_violations
    """
    try:
        summary = data_store.refresh_from_socrata()
    except Exception as exc:
        return Response(
            {
                "error": "SODA refresh failed.",
                "detail": str(exc),
                "hint": (
                    "Check SOCRATA_APP_TOKEN in .env and that the dataset id "
                    "csn4-vhvf is reachable."
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response({"status": "ok", **summary})


@api_view(["POST"])
def ask_ai(request):
    """
    Proxy a question to the FastAPI AI service.

    Body JSON example:
      { "question": "What does an open Class C violation mean?" }

    Why proxy? The Gemini API key stays on the AI service / server side,
    not in the browser.
    """
    question = (request.data or {}).get("question", "").strip()
    if not question:
        return Response(
            {"error": "Please provide a non-empty 'question' field."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ai_url = f"{settings.AI_SERVICE_URL.rstrip('/')}/ask"
    try:
        # Forward the question to FastAPI (timeout so we don't hang forever)
        upstream = requests.post(ai_url, json={"question": question}, timeout=60)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        return Response(
            {
                "error": "Could not reach the AI service.",
                "detail": str(exc),
                "hint": "Is the FastAPI AI service running on port 8001?",
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(upstream.json())


@api_view(["POST"])
def analyze_data(request):
    """
    Analyze the local Open HPD Violations cache with Gemini (via the AI service).

    Body JSON:
      {
        "prompt": "Compare Class C violations by borough",
        "session_id": "optional-stable-id-from-browser",
        "include_data": true,   // first call, or when inventory filters change
        "filters": {            // same controls as the inventory toolbar
          "search": "",
          "boro": "BRONX",
          "class": "C",
          "status": ""
        }
      }

    Token-saving rule:
      For each session_id, the dataset summary is attached when include_data
      is true (first ask, or after the user changes list filters). Later
      prompts with the same filters only send the new question.

    Non-technical tip:
      1) Download the open table: python manage.py fetch_soda_violations
      2) Start AI service on port 8001
      3) Optionally filter the inventory list, then ask in the prompt bar
    """
    body_in = request.data or {}
    prompt = (body_in.get("prompt") or "").strip()
    session_id = (body_in.get("session_id") or "").strip()
    include_data_flag = bool(body_in.get("include_data", False))

    # Inventory filters (optional) — empty strings mean "no filter"
    raw_filters = body_in.get("filters") or {}
    if not isinstance(raw_filters, dict):
        raw_filters = {}
    search = str(raw_filters.get("search") or "").strip()
    boro = str(raw_filters.get("boro") or "").strip()
    violation_class = str(
        raw_filters.get("class") or raw_filters.get("violation_class") or ""
    ).strip()
    status_filter = str(raw_filters.get("status") or "").strip()

    if not prompt:
        return Response(
            {"error": "Please provide a non-empty 'prompt' field."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not session_id:
        # Fallback id so older clients still work
        session_id = "default-session"

    # Has this session already stored a pack on the AI service?
    already_sent = session_id in _AI_SESSIONS_WITH_DATA
    if not already_sent:
        try:
            check = requests.get(
                f"{settings.AI_SERVICE_URL.rstrip('/')}/sessions/{session_id}",
                timeout=10,
            )
            if check.ok and check.json().get("has_data"):
                already_sent = True
                _AI_SESSIONS_WITH_DATA.add(session_id)
        except requests.RequestException:
            pass

    # Send a fresh pack when the browser asks (first time OR filters changed).
    # Otherwise reuse the AI service's stored context for this session.
    should_include_data = include_data_flag or not already_sent

    data_context = None
    if should_include_data:
        try:
            # Summarize the filtered open-violations slice (or full cache)
            data_context = build_analysis_context(
                search=search,
                boro=boro,
                violation_class=violation_class,
                status=status_filter,
            )
        except RuntimeError as exc:
            return Response(
                {
                    "error": str(exc),
                    "hint": "Run: python manage.py fetch_soda_violations",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    ai_payload = {
        "session_id": session_id,
        "prompt": prompt,
        "data_context": data_context,
    }

    ai_url = f"{settings.AI_SERVICE_URL.rstrip('/')}/analyze"
    try:
        upstream = requests.post(ai_url, json=ai_payload, timeout=180)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        return Response(
            {
                "error": "Could not reach the AI analysis service.",
                "detail": str(exc),
                "hint": "Is the FastAPI AI service running on port 8001?",
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    body = upstream.json()
    if body.get("data_included") or should_include_data:
        _AI_SESSIONS_WITH_DATA.add(session_id)

    # Helpful flags for the frontend status line
    body["session_data_was_sent"] = bool(body.get("data_included"))
    body["local_cached_rows"] = data_store.cached_row_count()
    if data_context is not None:
        body["analysis_row_count"] = data_context.get("row_count")
        body["analysis_filters"] = data_context.get("filters")
    return Response(body)
