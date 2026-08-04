"""
App configuration for the violations Django app.
Django reads this when loading INSTALLED_APPS.
"""

from django.apps import AppConfig


class ViolationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "violations"
    verbose_name = "HPD Violations"
