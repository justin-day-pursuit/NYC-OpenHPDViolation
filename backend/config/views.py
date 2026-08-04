"""
Small shared views that don't belong to a specific app.
"""

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response


def home(request):
    """
    Simple entry page so opening http://127.0.0.1:8000/ shows text
    instead of a Django "Not Found" error.

    The real React UI runs separately with: npm run dev (port 5173).
    """
    return HttpResponse("Hello World", content_type="text/plain; charset=utf-8")


@api_view(["GET"])
def health(request):
    """
    Health check endpoint.

    Used by scripts/test-builds.sh to confirm Django starts and responds.
    Open in a browser: http://127.0.0.1:8000/api/health/
    """
    return Response({"status": "ok", "service": "django-backend"})
