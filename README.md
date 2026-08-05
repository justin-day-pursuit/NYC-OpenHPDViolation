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

Open `.env` and paste your keys:

```bash
GOOGLE_GEMINI_API_KEY=paste_your_key_here
SOCRATA_APP_TOKEN=paste_your_nyc_open_data_app_token_here
```

Optional Socrata login fields (only needed to create/update remote rows):

```bash
SOCRATA_USERNAME=
SOCRATA_PASSWORD=
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

Useful endpoints (all Open HPD Violations traffic is **live SODA** — no local data file):

- `GET /api/health/`
- `GET/POST /api/violations/`
- `GET /api/soda-violations/` (live filterable / sortable / paged rows)
- `GET /api/soda-violations/filters/`
- `GET /api/soda-violations/stats/` (live dashboard chart counts; can take 1–3 min)
- `GET /api/soda-violations/status/` (live API reachability + row count)
- `POST /api/ask-ai/` (forwards to the AI service)
- `POST /api/analyze/` (session-aware Gemini analysis + charts/tables)

Set `SOCRATA_APP_TOKEN` in `.env` before using list/charts/AI. The inventory list pages the SODA API with `$limit` / `$offset`; overview charts use live SoQL `GROUP BY`. Use the dashboard **Refresh** button to re-query NYC Open Data.

### AI data analysis (Gemini)

1. Set `SOCRATA_APP_TOKEN` in the root `.env`.
2. Start the AI service on port 8001.
3. On the frontend, scroll under the inventory list to **Ask AI to analyze the data**.
4. Type a prompt and press **Enter**.

Token-saving rule: each browser tab sends a dataset summary to Gemini on the first ask, and again if you change the inventory filters (Search / Borough / Class / Status). Follow-up prompts with the same filters only send the new question. Open a new tab (or clear sessionStorage) to start a fresh AI session.

The data pack is built from **live** SODA aggregates (monthly trend, class × borough, top buildings) scoped to the current list filters. Source is **Open HPD Violations only** (`csn4-vhvf`) — not the full historical violations dataset. First ask can take several minutes.

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

## 4) Live analysis notebooks (same SODA source as the app)

For offline / exploratory pandas analysis against **current** NYC Open Data,
use the helpers under `notebooks/`. They call the Socrata SODA API directly
(`csn4-vhvf`), same live source the Django app uses.

```bash
cd notebooks
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Option A — Jupyter notebook
jupyter notebook open_hpd_live_analysis.ipynb

# Option B — plain script (prints tables + writes PNGs to notebooks/output/)
python run_live_analysis.py
# Optional SoQL filter:
python run_live_analysis.py --where "boro='BRONX'"

# Option C — building concentration analysis (feeds the website section)
# Counts distinct violationid only; writes frontend/public/analysis/*.json
# Can take 10–20 minutes (pages every building aggregate from SODA).
python run_building_concentration.py

# Option D — hazard persistence + NOV problem-theme clustering (extends Option C)
# Requires Option C JSON first. Usually 2–5 minutes.
python run_hazard_theme_analysis.py

# Option E — final insight (Class B moisture × multi-dwelling × age×theme)
# Requires Option C JSON first. Usually a few minutes.
python run_final_insight.py
```

Needs `SOCRATA_APP_TOKEN` in the root `.env`. First COUNT/GROUP BY calls can take
1–3 minutes on ~3M remote rows. Django does **not** need to be running.

The **Analysis journey** block on the homepage (directly under Overview charts) reads
`frontend/public/analysis/building_concentration.json`. Re-run Options C → D → E to refresh it.

---

## 5) Project map (where to edit things)

```text
.
├── .env.example              # Template for secrets — copy to .env
├── .gitignore                # Keeps .env, venvs, node_modules out of git
├── README.md
├── scripts/test-builds.sh    # Local/CI build checks
├── notebooks/                # Live SODA pandas analysis (same source as the app)
│   ├── soda_live.py          # API helpers (sodapy)
│   ├── open_hpd_live_analysis.ipynb
│   ├── run_live_analysis.py  # Same analysis without Jupyter
│   └── run_building_concentration.py  # Building concentration → website JSON
├── frontend/public/analysis/ # Snapshot JSON for the Analysis journey section
├── backend/                  # Django + DRF (live SODA queries, no data cache file)
│   ├── manage.py
│   ├── config/               # Project settings + root URLs
│   └── violations/           # SODA client, list/stats/AI context APIs
├── ai-service/               # FastAPI + Gemini
│   └── app/
│       ├── main.py           # HTTP routes
│       ├── gemini_client.py  # Talks to Google Gemini
│       └── config.py         # Reads root .env
└── frontend/                 # React (Vite)
    └── src/
        ├── App.jsx              # Main page UI
        ├── StatsDashboard.jsx   # SQL overview charts (no AI)
        ├── AnalysisPanel.jsx    # Gemini prompt + charts/tables
        └── api.js               # Calls Django
```

---

## 6) Common problems

| Symptom | Likely fix |
| --- | --- |
| Frontend says Django is not reachable | Start Django on port 8000 |
| Ask AI returns 502 / cannot reach AI service | Start FastAPI on port 8001 |
| Gemini error about missing API key | Put `GOOGLE_GEMINI_API_KEY` in the root `.env`, then restart FastAPI |
| Charts / list fail or time out | Set `SOCRATA_APP_TOKEN` in `.env`, restart Django, wait and click Refresh |
| Overview charts take a long time | Expected on first load (live GROUP BY on ~3M rows); use Refresh later |
| CORS errors in the browser | Confirm `CORS_ALLOWED_ORIGINS` in `.env` includes your frontend URL |

---

## 7) Security notes

- Never commit `.env`
- Never put the Gemini key in frontend code or any `VITE_` variable
- Rotate a key immediately if it was ever pushed to GitHub
