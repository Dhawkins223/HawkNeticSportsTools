#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
found_path=false
while IFS= read -r -d '' candidate; do
  if [[ "$candidate" == "$repo_root/scripts/check_local_paths.sh" ]]; then
    continue
  fi
  if grep -nE 'OneDrive|/mnt/[a-zA-Z]/|[A-Za-z]:\\Users\\' "$candidate"; then
    found_path=true
  fi
done < <(
  find "$repo_root/src" "$repo_root/scripts" "$repo_root/compose.yml" "$repo_root/.env.example" \
    -type f \( -name '*.py' -o -name '*.sh' -o -name '*.yml' -o -name '*.yaml' -o -name '*.toml' -o -name '.env.example' \) \
    -print0
)

if [[ "$found_path" == true ]]; then
  printf 'Runtime configuration contains a OneDrive, /mnt, or hardcoded Windows user path.\n' >&2
  exit 1
fi
printf 'Local path check: no hardcoded OneDrive or Windows runtime paths.\n'
