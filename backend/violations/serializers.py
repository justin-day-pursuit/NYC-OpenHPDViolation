"""
Serializers convert model instances <-> JSON for the API.
"""

from rest_framework import serializers

from .models import Violation


class ViolationSerializer(serializers.ModelSerializer):
    """JSON shape for a Violation record."""

    class Meta:
        model = Violation
        fields = [
            "id",
            "violation_id",
            "address",
            "borough",
            "description",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
