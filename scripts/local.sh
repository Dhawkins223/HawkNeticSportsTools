#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-$repo_root/.venv/bin/python}"

print_help() {
  cat <<'EOF'
Usage: ./scripts/local.sh <command>

Commands:
  help              Show this command list
  setup             Create .env and the local Python environment
  dev               Start the local dashboard with PostgreSQL
  stop              Stop only this repository's PostgreSQL container
  logs              Follow local PostgreSQL logs
  db-start          Start and health-check local PostgreSQL
  db-stop           Stop local PostgreSQL without deleting data
  db-reset          Reset only the named local PostgreSQL volume (requires CONFIRM_LOCAL_DB_RESET=1)
  migrate           Apply versioned PostgreSQL migrations
  migration-status  Show migration readiness without credentials
  test              Run tests in the isolated local PostgreSQL test database
  smoke             Start the application and verify /healthz
  sqlite-runtime-check  Confirm SQLite is archive-only
  local-path-check  Confirm runtime configuration has no Windows-mounted paths
  verify            Run all non-destructive local workflow checks
EOF
}

require_python() {
  if [[ ! -x "$python_bin" ]]; then
    printf 'Missing Python environment at %s. Run ./scripts/local.sh setup.\n' "$python_bin" >&2
    exit 1
  fi
}

load_local_environment() {
  # shellcheck disable=SC1091
  source "$repo_root/scripts/local_env.sh"
}

compose_command() {
  docker compose --env-file "$repo_root/.env" -f "$repo_root/compose.yml" "$@"
}

database_start() {
  "$repo_root/scripts/db_start.sh"
}

database_stop() {
  compose_command stop postgres
}

database_reset() {
  if [[ "${CONFIRM_LOCAL_DB_RESET:-}" != "1" ]]; then
    printf 'Refusing local database reset. Re-run with CONFIRM_LOCAL_DB_RESET=1.\n' >&2
    exit 2
  fi
  compose_command down --volumes --remove-orphans
}

migrate() {
  require_python
  database_start
  load_local_environment
  PYTHONPATH="$repo_root/src" "$python_bin" -m kalshi_research_bot database-migrate
}

migration_status() {
  require_python
  database_start
  load_local_environment
  PYTHONPATH="$repo_root/src" "$python_bin" -m kalshi_research_bot database-status
}

run_tests() {
  require_python
  database_start
  PYTHON_BIN="$python_bin" "$repo_root/scripts/test_local.sh"
}

smoke() {
  require_python
  database_start
  PYTHON_BIN="$python_bin" "$repo_root/scripts/smoke_local.sh"
}

verify() {
  require_python
  compose_command config >/dev/null
  database_start
  migrate
  migrate
  migration_status
  "$repo_root/scripts/check_active_sqlite.sh"
  "$repo_root/scripts/check_local_paths.sh"
  run_tests
  smoke
}

dev() {
  require_python
  database_start
  migrate
  PYTHON_BIN="$python_bin" "$repo_root/scripts/dev_local.sh"
}

command="${1:-help}"
case "$command" in
  help|-h|--help) print_help ;;
  setup) "$repo_root/scripts/setup_local.sh" ;;
  dev) dev ;;
  stop) database_stop ;;
  logs) compose_command logs -f postgres ;;
  db-start) database_start ;;
  db-stop) database_stop ;;
  db-reset) database_reset ;;
  migrate) migrate ;;
  migration-status) migration_status ;;
  test) run_tests ;;
  smoke) smoke ;;
  sqlite-runtime-check) "$repo_root/scripts/check_active_sqlite.sh" ;;
  local-path-check) "$repo_root/scripts/check_local_paths.sh" ;;
  verify) verify ;;
  *)
    printf 'Unknown local workflow command: %s\n\n' "$command" >&2
    print_help >&2
    exit 2
    ;;
esac
