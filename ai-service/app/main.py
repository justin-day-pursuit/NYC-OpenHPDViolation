"""
FastAPI AI service entry point.

Start locally (from ai-service/):
  uvicorn app.main:app --reload --port 8001

Docs (interactive):
  http://127.0.0.1:8001/docs

Main jobs:
  /health  — is the service up?
  /ask     — simple Q&A (no dataset session)
  /analyze — data analysis with charts/tables (session-aware)
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .analyze import analyze_prompt
from .config import CORS_ALLOWED_ORIGINS, GEMINI_MODEL
from .gemini_client import ask_gemini
from . import sessions

# Create the web app
app = FastAPI(
    title="NYC Open HPD Violation — AI Service",
    description="Gemini helpers for Q&A and session-based data analysis.",
    version="0.2.0",
)

# Allow the React frontend (and local tools) to call this API from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    """JSON body for POST /ask"""

    question: str = Field(..., min_length=1, description="User question about HPD violations")


class AskResponse(BaseModel):
    """JSON response for POST /ask"""

    answer: str
    model: str


class AnalyzeRequest(BaseModel):
    """
    JSON body for POST /analyze.

    session_id   — stable id from the browser tab (sessionStorage)
    prompt       — what the user typed in the analysis prompt bar
    data_context — dataset summary; send ONLY on the first call for a session
    """

    session_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    data_context: dict[str, Any] | None = None


@app.get("/health")
def health():
    """
    Health check used by scripts/test-builds.sh.
    Does not call Gemini — just confirms the service process is up.
    """
    return {"status": "ok", "service": "fastapi-ai"}


@app.get("/sessions/{session_id}")
def session_status(session_id: str):
    """
    Tiny helper so Django/frontend can ask:
    "Has this session already received its one-time data pack?"
    """
    return {
        "session_id": session_id,
        "has_data": sessions.has_data(session_id),
    }


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    """
    Ask Gemini a question and return the answer text.
    """
    try:
        answer = ask_gemini(payload.question.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/API failures
        raise HTTPException(
            status_code=502,
            detail=f"Gemini request failed: {exc}",
        ) from exc

    return AskResponse(answer=answer, model=GEMINI_MODEL)


@app.post("/analyze")
def analyze(payload: AnalyzeRequest):
    """
    Session-aware data analysis.

    First call for a session_id should include data_context.
    Later calls only need session_id + prompt (saves tokens).
    """
    try:
        return analyze_prompt(
            session_id=payload.session_id.strip(),
            prompt=payload.prompt.strip(),
            data_context=payload.data_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=502,
            detail=f"Analysis failed: {exc}",
        ) from exc
