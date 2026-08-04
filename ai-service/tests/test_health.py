"""
Lightweight tests for the AI service.

We only verify the app can start and /health works.
We do NOT call Gemini here (that would need a live API key).
No screenshots or video recording.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "fastapi-ai"
