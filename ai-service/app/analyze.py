"""
Ask Gemini to analyze HPD violation data and return charts/tables/narrative.

What this file does:
  1) Builds a careful prompt that includes the one-time data pack (first call)
     or only the new question (later calls in the same session).
  2) Asks Gemini for STRICT JSON the frontend can render.
  3) Parses that JSON (and recovers if Gemini wraps it in markdown fences).

Non-technical tip:
  If charts look empty, check that the AI service is running and that
  GOOGLE_GEMINI_API_KEY is set in the root .env file.
"""

from __future__ import annotations

import json
import re
from typing import Any

from google import genai

from . import sessions
from .config import GEMINI_MODEL, GOOGLE_GEMINI_API_KEY

# Instructions Gemini must follow so the React page can draw charts safely
_SYSTEM_INSTRUCTIONS = """
You are a data analyst for New York City HPD Open Violations.

You receive a dataset SUMMARY of Open HPD Violations only (Socrata csn4-vhvf):
currently open violations — not the full historical violations table.
The summary may be FILTERED to match the inventory toolbar (see context.filters).
row_count is the filtered match count; cache_row_count is the full open table.
sample_rows are examples only. Use the aggregates for accurate counts.

Available aggregate keys (prefer these over guessing):
- by_boro, by_class, by_currentstatus, by_zip_top
- by_month (YYYY-MM inspection trend, chronological)
- by_class_and_boro (each row has boro, class, count)
- by_building_top (buildingid + address fields + count)

Return ONLY valid JSON (no markdown fences) with this shape:
{
  "narrative": "plain-language findings for a non-expert",
  "tables": [
    {
      "title": "short title",
      "columns": ["colA", "colB"],
      "rows": [{"colA": "...", "colB": 123}]
    }
  ],
  "charts": [
    {
      "type": "bar" | "line" | "pie",
      "title": "short title",
      "xKey": "name",
      "yKey": "value",
      "data": [{"name": "BRONX", "value": 123}]
    }
  ],
  "manipulated_rows": [
    {"violationid": "...", "boro": "..."}
  ]
}

Rules:
- Prefer numbers from the provided aggregates.
- Respect context.filters — if filters.active is true, answer about that slice only
  and mention the filter briefly in the narrative.
- For trends use by_month; for class comparisons by borough use by_class_and_boro;
  for "worst buildings" use by_building_top.
- Do not invent closed/historical violation counts — this cache is open violations only.
- Include at least one chart when the question asks for trends, comparisons, or distribution.
- Keep tables/charts small (under 30 rows/points) so the UI stays readable.
- manipulated_rows is optional (use for filtered example rows, max 25).
- If you cannot answer from the data, say so in narrative and return empty arrays.
"""


def analyze_prompt(
    *,
    session_id: str,
    prompt: str,
    data_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Run one analysis turn for a browser session.

    session_id     — browser tab id (keeps data/history together)
    prompt         — the user's question typed in the prompt bar
    data_context   — dataset summary; ONLY required the first time
    """
    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError(
            "GOOGLE_GEMINI_API_KEY is missing. "
            "Copy .env.example to .env and paste your Gemini API key."
        )

    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is empty.")

    # First message in a session must include the data pack
    if data_context is not None:
        sessions.upsert_session_data(session_id, data_context)
    elif not sessions.has_data(session_id):
        raise RuntimeError(
            "No dataset is loaded for this session yet. "
            "Send include_data=true on the first request."
        )

    stored = sessions.get_session(session_id) or {}
    context = stored.get("data_context") or {}
    history = sessions.get_history(session_id)

    # Build the full text Gemini will read
    parts = [_SYSTEM_INSTRUCTIONS.strip(), ""]
    if data_context is not None:
        parts.append("DATASET CONTEXT (sent once for this session):")
        parts.append(json.dumps(context, default=str)[:120000])
        parts.append("")
    else:
        parts.append(
            "DATASET CONTEXT was already provided earlier in this session. "
            "Reuse that context. Do not assume it changed "
            "(unless a later turn sent a replacement pack)."
        )
        filters = context.get("filters") or {}
        parts.append(
            f"(Reminder) row_count={context.get('row_count')} "
            f"cache_row_count={context.get('cache_row_count')} "
            f"filters={json.dumps(filters, default=str)} "
            f"columns={len(context.get('columns') or [])}"
        )
        parts.append("")

    if history:
        parts.append("RECENT CONVERSATION:")
        for turn in history[-8:]:
            parts.append(f"{turn['role'].upper()}: {turn['content'][:2000]}")
        parts.append("")

    parts.append(f"USER REQUEST: {prompt}")
    parts.append("Respond with JSON only.")

    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents="\n".join(parts),
    )
    raw_text = getattr(response, "text", None) or ""
    if not raw_text.strip():
        raise RuntimeError("Gemini returned an empty response.")

    parsed = _parse_json_response(raw_text)

    # Remember this turn so follow-ups can refer to it
    sessions.append_history(session_id, "user", prompt)
    sessions.append_history(session_id, "assistant", parsed.get("narrative", "")[:2000])

    return {
        "session_id": session_id,
        "model": GEMINI_MODEL,
        "data_included": data_context is not None,
        "row_count_context": context.get("row_count"),
        "narrative": parsed.get("narrative") or "",
        "tables": parsed.get("tables") or [],
        "charts": parsed.get("charts") or [],
        "manipulated_rows": parsed.get("manipulated_rows") or [],
    }


def _parse_json_response(text: str) -> dict[str, Any]:
    """
    Turn Gemini's text into a Python dict.

    Sometimes models wrap JSON in ```json ... ``` — this strips that.
    """
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Last resort: find the first {...} block
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # If parsing fails, still show the raw answer as narrative
    return {
        "narrative": text,
        "tables": [],
        "charts": [],
        "manipulated_rows": [],
    }
