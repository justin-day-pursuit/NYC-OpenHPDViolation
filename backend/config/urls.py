"""
Root URL map for the Django project.

Think of this file as the "table of contents" for all web addresses
this backend understands.
"""

from django.contrib import admin
from django.urls import include, path

from .views import health, home

urlpatterns = [
    # Entry page — open http://127.0.0.1:8000/ to see "Hello World"
    path("", home, name="home"),
    # Django admin site (http://127.0.0.1:8000/admin/)
    path("admin/", admin.site.urls),
    # Simple health check used by build/smoke tests
    path("api/health/", health, name="health"),
    # Violation-related API routes live in the violations app
    path("api/", include("violations.urls")),
]
