# NYC Open HPD Violation

Starter codebase for exploring New York City HPD housing violations.

**Stack**

| Layer | Tech | Default local URL |
| --- | --- | --- |
| Frontend | React (Vite) | http://127.0.0.1:5173 |
| Backend API | Django + Django REST Framework | http://127.0.0.1:8000 |
| AI service | FastAPI + Google Gemini | http://127.0.0.1:8001 |

Code is commented so a less technical maintainer can find the right file and understand each section.

---

## 1) One-time setup

### Prerequisites

- Python 3.11+ (3.12 recommended)
- Node.js 20+ and npm
- A Google Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey))

### Create your `.env` file (API keys live here)

From the project root:

```bash
cp .env.example .env
```

Open `.env` and paste your key:

```bash
GOOGLE_GEMINI_API_KEY=paste_your_key_here
```

`.env` is listed in `.gitignore` and must not be committed.

### Backend (Django)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver         # http://127.0.0.1:8000
```

Useful endpoints:

- `GET /api/health/`
- `GET/POST /api/violations/`
- `POST /api/ask-ai/` (forwards to the AI service)

### AI service (FastAPI + Gemini)

In a second terminal:

```bash
cd ai-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Useful endpoints:

- `GET /health`
- `POST /ask` with JSON `{ "question": "..." }`
- Interactive docs: http://127.0.0.1:8001/docs

### Frontend (React)

In a third terminal:

```bash
cd frontend
npm install
npm run dev                        # http://127.0.0.1:5173
```

During `npm run dev`, requests to `/api/...` are proxied to Django (see `frontend/vite.config.js`).

---

## 2) Day-to-day development

Start these three processes (three terminals):

1. Django — `backend/` → `python manage.py runserver`
2. FastAPI — `ai-service/` → `uvicorn app.main:app --reload --port 8001`
3. React — `frontend/` → `npm run dev`

Then open http://127.0.0.1:5173

---

## 3) Testing builds (no recording / screenshots)

This project **tests builds and unit checks only**. It does **not** set up browser video recording or screenshot capture tooling.

Run everything from the repo root:

```bash
chmod +x scripts/test-builds.sh
./scripts/test-builds.sh
```

That script:

- runs Django `check`, migrations, and unit tests
- runs FastAPI health unit tests (does not call Gemini)
- runs `npm run build` for the React app

GitHub Actions runs the same script on push/PR (`.github/workflows/build-checks.yml`).

---

## 4) Project map (where to edit things)

```text
.
├── .env.example              # Template for secrets — copy to .env
├── .gitignore                # Keeps .env, venvs, node_modules out of git
├── README.md
├── scripts/test-builds.sh    # Local/CI build checks
├── backend/                  # Django + DRF
│   ├── manage.py
│   ├── config/               # Project settings + root URLs
│   └── violations/           # Violation models, API, admin
├── ai-service/               # FastAPI + Gemini
│   └── app/
│       ├── main.py           # HTTP routes
│       ├── gemini_client.py  # Talks to Google Gemini
│       └── config.py         # Reads root .env
└── frontend/                 # React (Vite)
    └── src/
        ├── App.jsx           # Main page UI
        └── api.js            # Calls Django
```

---

## 5) Common problems

| Symptom | Likely fix |
| --- | --- |
| Frontend says Django is not reachable | Start Django on port 8000 |
| Ask AI returns 502 / cannot reach AI service | Start FastAPI on port 8001 |
| Gemini error about missing API key | Put `GOOGLE_GEMINI_API_KEY` in the root `.env`, then restart FastAPI |
| CORS errors in the browser | Confirm `CORS_ALLOWED_ORIGINS` in `.env` includes your frontend URL |

---

## 6) Security notes

- Never commit `.env`
- Never put the Gemini key in frontend code or any `VITE_` variable
- Rotate a key immediately if it was ever pushed to GitHub
