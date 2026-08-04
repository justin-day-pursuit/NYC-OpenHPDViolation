"""
In-memory AI analysis sessions.

Purpose (plain English):
  The first time a browser tab talks to the AI, we store the dataset summary
  under a session_id. Later prompts in that same session only send the new
  question — not the whole dataset again — which saves tokens and time.

How to maintain:
  - Restarting the AI service clears all sessions (users just ask again;
    the first new question will re-send the data pack).
  - This is intentional for local development (no Redis/database required).
"""

from __future__ import annotations

from threading import Lock
from typing import Any

# session_id -> { "data_context": {...}, "history": [ {role, content}, ... ] }
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = Lock()


def upsert_session_data(session_id: str, data_context: dict[str, Any]) -> None:
    """
    Save (or replace) the dataset summary for this session.
    Call this only on the first request that includes data.
    """
    with _LOCK:
        bucket = _SESSIONS.setdefault(session_id, {"history": []})
        bucket["data_context"] = data_context


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return the session dict, or None if we have never seen this id."""
    with _LOCK:
        return _SESSIONS.get(session_id)


def has_data(session_id: str) -> bool:
    """True when this session already received its one-time data pack."""
    with _LOCK:
        bucket = _SESSIONS.get(session_id) or {}
        return bool(bucket.get("data_context"))


def append_history(session_id: str, role: str, content: str) -> None:
    """
    Keep a short chat history so follow-up questions make sense.
    Caps at 20 messages so memory does not grow forever.
    """
    with _LOCK:
        bucket = _SESSIONS.setdefault(session_id, {"history": []})
        history = bucket.setdefault("history", [])
        history.append({"role": role, "content": content})
        if len(history) > 20:
            del history[:-20]


def get_history(session_id: str) -> list[dict[str, str]]:
    """Return prior prompts/answers for this session (may be empty)."""
    with _LOCK:
        bucket = _SESSIONS.get(session_id) or {}
        return list(bucket.get("history") or [])
