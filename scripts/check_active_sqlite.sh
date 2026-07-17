#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mapfile -t sqlite_imports < <(grep -RIl --include='*.py' '^import sqlite3$' "$repo_root/src" || true)

allowed=(
  "$repo_root/src/kalshi_research_bot/db_migrations.py"
  "$repo_root/src/kalshi_research_bot/postgres_migration.py"
  "$repo_root/src/kalshi_research_bot/storage.py"
)

for imported_file in "${sqlite_imports[@]}"; do
  allowed_file=false
  for allowed_path in "${allowed[@]}"; do
    if [[ "$imported_file" == "$allowed_path" ]]; then
      allowed_file=true
      break
    fi
  done
  if [[ "$allowed_file" != true ]]; then
    printf 'Unexpected active SQLite import: %s\n' "$imported_file" >&2
    exit 1
  fi
done

if grep -RIn --include='*.py' -E 'from[[:space:]]+\.storage[[:space:]]+import|import[[:space:]]+.*storage' "$repo_root/src"; then
  printf 'Runtime code must not import the legacy SQLite archive module.\n' >&2
  exit 1
fi

printf 'Active runtime SQLite check: archive-only references confirmed.\n'
