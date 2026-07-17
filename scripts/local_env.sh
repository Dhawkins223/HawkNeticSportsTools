#!/usr/bin/env bash
# Source this file from a WSL shell to configure the repository-owned local database.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${HAWKNETIC_ENV_FILE:-$repo_root/.env}"

if [[ ! -f "$env_file" ]]; then
  printf 'Missing %s. Run make setup from the repository root.\n' "$env_file" >&2
  return 1 2>/dev/null || exit 1
fi

read_env_value() {
  local name="$1"
  local line
  line="$(grep -m1 "^${name}=" "$env_file" || true)"
  printf '%s' "${line#*=}"
}

for required_name in POSTGRES_DB POSTGRES_TEST_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_PORT; do
  if [[ -z "${!required_name:-}" ]]; then
    export "$required_name=$(read_env_value "$required_name")"
  fi
  if [[ -z "${!required_name:-}" ]]; then
    printf 'Missing %s in %s.\n' "$required_name" "$env_file" >&2
    return 1 2>/dev/null || exit 1
  fi
done

if ! [[ "$POSTGRES_PORT" =~ ^[0-9]{2,5}$ ]]; then
  printf 'POSTGRES_PORT must be numeric.\n' >&2
  return 1 2>/dev/null || exit 1
fi

for database_name in "$POSTGRES_DB" "$POSTGRES_TEST_DB"; do
  if ! [[ "$database_name" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
    printf 'Local database names must be PostgreSQL identifiers.\n' >&2
    return 1 2>/dev/null || exit 1
  fi
done

if ! [[ "$POSTGRES_USER" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  printf 'POSTGRES_USER must be a PostgreSQL identifier.\n' >&2
  return 1 2>/dev/null || exit 1
fi

if ! [[ "$POSTGRES_PASSWORD" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  printf 'POSTGRES_PASSWORD must use URL-safe characters for the local connection string.\n' >&2
  return 1 2>/dev/null || exit 1
fi

export DATABASE_BACKEND=postgres
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
export DATABASE_MIGRATION_URL="$DATABASE_URL"
export DATABASE_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_TEST_DB}"
export DATABASE_SCHEMA=public
export DATABASE_MIGRATION_MODE=check
export APP_ENV=local
export RESEARCH_ONLY=true
export LIVE_EXECUTION_ENABLED=false
export AUTO_TRADE_ENABLED=false
export AUTO_UPLOAD_ENABLED=false
export KALSHI_ORDER_UPLOAD_ENABLED=false
export MODEL_PROMOTION_ENABLED=false
export STALE_CACHE_AS_FRESH=false

# A local workflow must never inherit a hosted Railway identity or database URL.
unset RAILWAY_ENVIRONMENT RAILWAY_PROJECT_ID RAILWAY_SERVICE_ID
