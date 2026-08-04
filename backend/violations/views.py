"""
API views for violations.

These are the functions/classes that handle HTTP requests under /api/...
"""

import requests
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Violation
from .serializers import ViolationSerializer


class ViolationViewSet(viewsets.ModelViewSet):
    """
    Full CRUD API for Violation records.

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
