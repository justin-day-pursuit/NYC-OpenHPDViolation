"""
Load configuration for the AI service from the root .env file.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

# Repo root is two levels up from this file: ai-service/app/config.py -> repo/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Google Gemini API key — paste your real key into the root .env file
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "")

# Which Gemini model to call (override in .env if Google renames models)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Origins allowed to call this service from a browser (if you ever call it directly)
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
