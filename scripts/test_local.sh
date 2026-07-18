#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${DATABASE_URL:-}" || -z "${DATABASE_TEST_URL:-}" ]]; then
  # shellcheck disable=SC1091
  source "$repo_root/scripts/local_env.sh"
  "$repo_root/scripts/db_start.sh"
fi

python_bin="${PYTHON_BIN:-$repo_root/.venv/bin/python}"
if [[ "$python_bin" != */* ]]; then
  python_bin="$(command -v "$python_bin" || true)"
  if [[ -z "$python_bin" && "${PYTHON_BIN:-}" == "python" && -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  fi
fi
if [[ -z "$python_bin" || ! -x "$python_bin" ]]; then
  printf 'Missing Python environment. Run ./scripts/local.sh setup.\n' >&2
  exit 1
fi

export DATABASE_URL="$DATABASE_TEST_URL"
export DATABASE_MIGRATION_URL="$DATABASE_TEST_URL"
export DATABASE_SCHEMA="test_suite_$$"
export DATABASE_MIGRATION_MODE=apply
export HAWKNETIC_TEST_POSTGRES_SCHEMAS=true
export PYTHONPATH="$repo_root/src"

cleanup() {
  "$python_bin" - <<'PY'
import os
import re

import psycopg

schema = os.environ["DATABASE_SCHEMA"]
if not re.fullmatch(r"test_[a-z0-9_]{1,58}", schema):
    raise SystemExit("invalid local test schema")
with psycopg.connect(os.environ["DATABASE_MIGRATION_URL"], autocommit=True) as connection:
    database_name = str(connection.execute("SELECT current_database()").fetchone()[0])
    if database_name != os.environ["POSTGRES_TEST_DB"]:
        raise SystemExit("refusing cleanup outside the local PostgreSQL test database")
    for (test_schema,) in connection.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name LIKE 'test\\_%' ESCAPE '\\'"
    ).fetchall():
        if not re.fullmatch(r"test_[a-z0-9_]{1,58}", str(test_schema)):
            raise SystemExit("unexpected test schema name")
        connection.execute(f'DROP SCHEMA IF EXISTS "{test_schema}" CASCADE')
PY
}
trap cleanup EXIT

"$python_bin" -m unittest discover -s "$repo_root/tests"
