"""
Basic Django tests — kept lightweight; no screenshots or browser recording.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Violation


class HealthAndViolationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_create_and_list_violation(self):
        Violation.objects.create(
            violation_id="TEST-1",
            address="123 Example St",
            borough="BROOKLYN",
            description="Sample open violation",
            status="Open",
        )
        response = self.client.get("/api/violations/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
