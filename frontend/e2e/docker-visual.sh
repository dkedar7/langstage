#!/usr/bin/env bash
# Run the visual-regression suite inside the pinned Playwright Docker image so
# local baseline generation and CI render identically (same browser, fonts, OS).
#
#   check  (default) — diff against committed baselines
#   update           — (re)generate baselines
#
# The image ships Python + Node but no pip, so we bootstrap uv to install the
# app, then build the frontend and run the visual spec.
set -euo pipefail
MODE="${1:-check}"

export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

# Repo root derived from this script's location (frontend/e2e/), so it works
# both for a local `docker run -v repo:/work` and a CI container checkout.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"
uv venv /opt/v
# shellcheck disable=SC1091
. /opt/v/bin/activate
uv pip install -e ".[deepagents]" >/dev/null

cd "$REPO_ROOT/frontend"
npm ci --no-audit --no-fund
npm run build

if [ "$MODE" = "update" ]; then
  npx playwright test visual.spec.ts --update-snapshots
else
  npx playwright test visual.spec.ts
fi
