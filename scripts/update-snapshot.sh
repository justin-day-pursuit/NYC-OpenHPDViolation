#!/usr/bin/env bash
# =============================================================================
# update-snapshot.sh — rebuild the public static site into snapshot/
# =============================================================================
#
# What this does (plain English):
#   1) Builds the React app in “static snapshot” mode (no live Django API).
#   2) Copies the build into snapshot/ (the folder Vercel serves).
#   3) Checks that the Analysis journey JSON was included.
#
# When to run:
#   - After you change the frontend UI, OR
#   - After you refresh analysis JSON with the notebooks (C → D → E), THEN
#   - Commit + push so Vercel updates.
#
# How to run (from the project root):
#   chmod +x scripts/update-snapshot.sh   # once
#   ./scripts/update-snapshot.sh
#
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
SNAPSHOT="$ROOT/snapshot"
DIST="$FRONTEND/dist"
ANALYSIS_JSON="$SNAPSHOT/analysis/building_concentration.json"

echo "==> Project root: $ROOT"
echo "==> Building frontend with VITE_STATIC_SNAPSHOT=true …"

cd "$FRONTEND"

if [[ ! -d node_modules ]]; then
  echo "==> Installing frontend npm packages …"
  npm install
fi

# Static mode disables live /api calls; Analysis journey uses /analysis/*.json
VITE_STATIC_SNAPSHOT=true npm run build

if [[ ! -f "$DIST/index.html" ]]; then
  echo "ERROR: Build did not produce frontend/dist/index.html" >&2
  exit 1
fi

echo "==> Syncing frontend/dist → snapshot/ …"

# Keep snapshot/README.md (maintainer notes); replace everything else.
mkdir -p "$SNAPSHOT"
README_BAK="$(mktemp)"
if [[ -f "$SNAPSHOT/README.md" ]]; then
  cp "$SNAPSHOT/README.md" "$README_BAK"
else
  README_BAK=""
fi

rm -rf "$SNAPSHOT"
mkdir -p "$SNAPSHOT"

# Copy built site (includes public/analysis copied by Vite into dist/analysis)
cp -R "$DIST"/. "$SNAPSHOT"/

if [[ -n "$README_BAK" && -f "$README_BAK" ]]; then
  cp "$README_BAK" "$SNAPSHOT/README.md"
  rm -f "$README_BAK"
fi

if [[ ! -f "$ANALYSIS_JSON" ]]; then
  echo "ERROR: Missing $ANALYSIS_JSON" >&2
  echo "       Run notebooks/run_building_concentration.py (and later passes) first." >&2
  exit 1
fi

echo "==> Snapshot ready."
echo "    Analysis JSON: $ANALYSIS_JSON"
echo ""
echo "Next steps for a non-technical maintainer:"
echo "  git add snapshot frontend/public/analysis"
echo "  git commit -m \"Refresh static snapshot\""
echo "  git push"
echo ""
echo "Vercel serves the snapshot/ folder (see root vercel.json)."
