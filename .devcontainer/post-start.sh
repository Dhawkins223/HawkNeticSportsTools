#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -x .venv/bin/python && -f .env ]]; then
  export PYTHON_BIN="$repo_root/.venv/bin/python"
  ./scripts/local.sh db-start
fi
