#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

bash .devcontainer/install-cloud-tools.sh

python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

export PYTHON_BIN="$repo_root/.venv/bin/python"
./scripts/local.sh setup

echo
echo "Codespace setup complete."
echo "Start the dashboard with: ./scripts/local.sh dev"
echo "Run all validation with: ./scripts/local.sh verify"
