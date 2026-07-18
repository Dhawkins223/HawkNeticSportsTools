#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  printf 'Created ignored local .env from .env.example.\n'
fi

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  rm -rf .venv
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
printf 'Local Python environment is ready.\n'
