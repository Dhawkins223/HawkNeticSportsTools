#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$repo_root/scripts/local_env.sh"
python_bin="${PYTHON_BIN:-$repo_root/.venv/bin/python}"

"$repo_root/scripts/db_start.sh"
export PYTHONPATH="$repo_root/src"
exec "$python_bin" -m kalshi_research_bot paper --host 127.0.0.1 --port "${RESEARCH_DASHBOARD_PORT:-8765}" --refresh-seconds 0
