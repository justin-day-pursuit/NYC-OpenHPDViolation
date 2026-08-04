"""
FastAPI AI service entry point.

Start locally (from ai-service/):
  uvicorn app.main:app --reload --port 8001

Docs (interactive):
  http://127.0.0.1:8001/docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import CORS_ALLOWED_ORIGINS, GEMINI_MODEL
from .gemini_client import ask_gemini

# Create the web app
app = FastAPI(
    title="NYC Open HPD Violation — AI Service",
    description="Small FastAPI service that answers questions with Google Gemini.",
    version="0.1.0",
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


@app.get("/health")
def health():
    """
    Health check used by scripts/test-builds.sh.
    Does not call Gemini — just confirms the service process is up.
    """
    return {"status": "ok", "service": "fastapi-ai"}


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    """
    Ask Gemini a question and return the answer text.
    """
    try:
        answer = ask_gemini(payload.question.strip())
    except RuntimeError as exc:
        # Missing key / empty response / config problems
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/API failures
        raise HTTPException(
            status_code=502,
            detail=f"Gemini request failed: {exc}",
        ) from exc

    return AskResponse(answer=answer, model=GEMINI_MODEL)
