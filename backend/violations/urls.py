"""
URL routes for the violations app (mounted under /api/ in config/urls.py).
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ViolationViewSet,
    analyze_data,
    ask_ai,
    soda_filter_options,
    soda_refresh,
    soda_stats,
    soda_status,
    soda_violations,
)

# DefaultRouter auto-builds list/detail routes for the ViewSet
router = DefaultRouter()
router.register("violations", ViolationViewSet, basename="violation")

urlpatterns = [
    # AI helper endpoint: POST /api/ask-ai/
    path("ask-ai/", ask_ai, name="ask-ai"),
    # Session-aware data analysis (Gemini + charts/tables)
    path("analyze/", analyze_data, name="analyze-data"),
    # SODA / NYC Open Data cache endpoints
    path("soda-violations/", soda_violations, name="soda-violations"),
    path("soda-violations/filters/", soda_filter_options, name="soda-filters"),
    # Chart numbers for the dashboard (borough / class / status / monthly)
    path("soda-violations/stats/", soda_stats, name="soda-stats"),
    path("soda-violations/status/", soda_status, name="soda-status"),
    path("soda-violations/refresh/", soda_refresh, name="soda-refresh"),
    # Router routes: /api/violations/, /api/violations/<id>/, etc.
    path("", include(router.urls)),
]
