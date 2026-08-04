"""
Database models (tables) for HPD violations.

Start simple. Add fields later as you connect to NYC Open Data.
"""

from django.db import models


class Violation(models.Model):
    """
    One housing code violation record.

    This is a starter shape — you can expand it to match the NYC HPD
    Open Data columns you care about.
    """

    # Public / agency identifier if available
    violation_id = models.CharField(
        max_length=64,
        unique=True,
        help_text="Unique ID from the source dataset (or a local key).",
    )
    # Human-readable building address
    address = models.CharField(max_length=255, blank=True, default="")
    # Borough name, e.g. "MANHATTAN"
    borough = models.CharField(max_length=64, blank=True, default="")
    # Short description of the issue
    description = models.TextField(blank=True, default="")
    # e.g. "Open", "Closed"
    status = models.CharField(max_length=64, blank=True, default="Open")
    # When we first stored this row
    created_at = models.DateTimeField(auto_now_add=True)
    # When we last updated this row
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        # Shown in Django admin lists
        return f"{self.violation_id} — {self.address or 'No address'}"
