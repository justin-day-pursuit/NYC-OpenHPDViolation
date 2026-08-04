#!/usr/bin/env bash
# =============================================================================
# Build / smoke tests for local development and CI
# =============================================================================
# What this script DOES:
#   - Installs Python deps (if venvs are missing) enough to run checks
#   - Runs Django checks + unit tests
#   - Runs FastAPI unit tests (health only — no live Gemini call)
#   - Builds the React frontend (production bundle)
#
# What this script intentionally does NOT do:
#   - Browser recording / video capture
#   - Screenshot baselines or visual regression capture
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Repo root: $ROOT_DIR"

# ---------------------------------------------------------------------------
# Backend (Django)
# ---------------------------------------------------------------------------
echo "==> Backend: ensure virtualenv + install"
if [[ ! -d "$ROOT_DIR/backend/.venv" ]]; then
  python3 -m venv "$ROOT_DIR/backend/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/backend/.venv/bin/activate"
pip install -q -r "$ROOT_DIR/backend/requirements.txt"
cd "$ROOT_DIR/backend"
python manage.py check
python manage.py migrate --noinput
python manage.py test
deactivate
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# AI service (FastAPI)
# ---------------------------------------------------------------------------
echo "==> AI service: ensure virtualenv + install + pytest"
if [[ ! -d "$ROOT_DIR/ai-service/.venv" ]]; then
  python3 -m venv "$ROOT_DIR/ai-service/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/ai-service/.venv/bin/activate"
pip install -q -r "$ROOT_DIR/ai-service/requirements.txt"
cd "$ROOT_DIR/ai-service"
pytest -q
deactivate
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# Frontend (React / Vite) — build only, no Playwright recording/screenshots
# ---------------------------------------------------------------------------
echo "==> Frontend: npm install + production build"
cd "$ROOT_DIR/frontend"
npm install
npm run build
cd "$ROOT_DIR"

echo ""
echo "All build checks passed."
echo "(No recording or screenshot tooling is configured in this project.)"
