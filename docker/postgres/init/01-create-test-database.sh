#!/usr/bin/env sh
set -eu

if ! printf '%s' "$POSTGRES_TEST_DB" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]{0,62}$'; then
  echo "POSTGRES_TEST_DB must be a PostgreSQL identifier" >&2
  exit 1
fi

existing_database="$(psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_TEST_DB'")"
if [ "$existing_database" != "1" ]; then
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE \"$POSTGRES_TEST_DB\""
fi
