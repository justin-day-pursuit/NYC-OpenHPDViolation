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
from .models import Violation
from .serializers import ViolationSerializer
from .socrata_client import discover_api_limits, get_record_count


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
