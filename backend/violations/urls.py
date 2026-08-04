"""
URL routes for the violations app (mounted under /api/ in config/urls.py).
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ViolationViewSet, ask_ai

# DefaultRouter auto-builds list/detail routes for the ViewSet
router = DefaultRouter()
router.register("violations", ViolationViewSet, basename="violation")

urlpatterns = [
    # AI helper endpoint: POST /api/ask-ai/
    path("ask-ai/", ask_ai, name="ask-ai"),
    # Router routes: /api/violations/, /api/violations/<id>/, etc.
    path("", include(router.urls)),
]
