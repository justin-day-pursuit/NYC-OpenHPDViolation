"""
Thin wrapper around the Google Gemini API.

If Gemini starts failing, check:
  1. GOOGLE_GEMINI_API_KEY is set in the root .env
  2. The key is valid at https://aistudio.google.com/apikey
  3. GEMINI_MODEL still exists (Google renames models occasionally)
"""

from google import genai

from .config import GEMINI_MODEL, GOOGLE_GEMINI_API_KEY


def ask_gemini(question: str) -> str:
    """
    Send a text question to Gemini and return the model's text answer.
    """
    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError(
            "GOOGLE_GEMINI_API_KEY is missing. "
            "Copy .env.example to .env and paste your Gemini API key."
        )

    # Create a client with your API key
    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)

    # Keep the system guidance short and focused on this project's domain
    prompt = (
        "You are a helpful assistant for New York City HPD housing violations. "
        "Explain clearly for non-experts. If you are unsure, say so.\n\n"
        f"Question: {question}"
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    # google-genai returns .text for the main answer string
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text
