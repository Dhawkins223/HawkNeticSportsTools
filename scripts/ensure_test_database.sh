#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$repo_root/scripts/local_env.sh"

compose=(docker compose --env-file "$env_file" -f "$repo_root/compose.yml")
existing_database="$(${compose[@]} exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_TEST_DB'")"
if [[ "$existing_database" != "1" ]]; then
  "${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE \"$POSTGRES_TEST_DB\""
fi
