#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$repo_root/scripts/local_env.sh"

compose=(docker compose --env-file "$env_file" -f "$repo_root/compose.yml")
"${compose[@]}" up -d postgres

for _ in $(seq 1 24); do
  if "${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    "$repo_root/scripts/ensure_test_database.sh"
    printf 'Local PostgreSQL is healthy on 127.0.0.1:%s.\n' "$POSTGRES_PORT"
    exit 0
  fi
  sleep 2
done

printf 'Local PostgreSQL did not become healthy within 48 seconds.\n' >&2
"${compose[@]}" ps >&2
exit 1
