#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  printf 'Missing Python environment at %s. Run make setup.\n' "$python_bin" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091
  source "$repo_root/scripts/local_env.sh"
fi

export PYTHONPATH="$repo_root/src"
"$python_bin" -m kalshi_research_bot database-status | "$python_bin" -c '
import json
import sys

status = json.load(sys.stdin)
if not status.get("ready") or status.get("dialect") != "postgres":
    raise SystemExit("local PostgreSQL database status is not ready")
print("PostgreSQL migration status: ready")
'

smoke_port="${SMOKE_PORT:-18765}"
smoke_data_dir="$(mktemp -d)"
smoke_log="$smoke_data_dir/server.log"
RESEARCH_DATA_DIR="$smoke_data_dir" "$python_bin" -m kalshi_research_bot paper --host 127.0.0.1 --port "$smoke_port" --refresh-seconds 0 >"$smoke_log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  rm -rf "$smoke_data_dir"
}
trap cleanup EXIT

for _ in $(seq 1 20); do
  if "$python_bin" - "$smoke_port" 2>/dev/null <<'PY'
import sys
from urllib.request import urlopen

with urlopen(f"http://127.0.0.1:{sys.argv[1]}/healthz", timeout=1) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
  then
    printf 'Application smoke test: healthy.\n'
    exit 0
  fi
  sleep 1
done

cat "$smoke_log" >&2
printf 'Application smoke test did not become healthy.\n' >&2
exit 1
