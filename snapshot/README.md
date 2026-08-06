# Static site snapshot (Vercel)

**Do not edit files in this folder by hand.**

This directory is the built public website that Vercel serves. It is generated
from the React app in `frontend/` plus the analysis JSON under
`frontend/public/analysis/`.

## How a non-technical maintainer refreshes it

From the **project root**:

```bash
./scripts/update-snapshot.sh
```

Then commit and push:

```bash
git add snapshot frontend/public/analysis
git commit -m "Refresh static snapshot"
git push
```

Vercel will pick up the new `snapshot/` contents on the next deploy.

## When to refresh

1. After changing the React UI (`frontend/src/…`)
2. After refreshing analysis data with the notebooks:

```bash
cd notebooks
source .venv/bin/activate
python run_building_concentration.py
python run_hazard_theme_analysis.py
python run_final_insight.py
cd ..
./scripts/update-snapshot.sh
```

Local development (`frontend/` + Django + AI) is separate and unchanged.
