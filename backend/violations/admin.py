"""
Register models with the Django admin site.
Visit /admin/ after creating a superuser to edit data in a web UI.
"""

from django.contrib import admin

from .models import Violation


@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ("violation_id", "address", "borough", "status", "updated_at")
    search_fields = ("violation_id", "address", "description")
    list_filter = ("borough", "status")
