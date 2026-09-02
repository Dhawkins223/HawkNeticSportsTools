#!/usr/bin/env bash
set -euo pipefail

# Version and digest pins make a new Codespace repeatable. The SHA-256 values
# come from each project's GitHub release metadata.
bun_version="1.3.10"
bun_x64_sha="f57bc0187e39623de716ba3a389fda5486b2d7be7131a980ba54dc7b733d2e08"
bun_arm64_sha="fa5ecb25cafa8e8f5c87a0f833719d46dd0af0a86c7837d806531212d55636d3"
railway_version="5.47.2"
railway_x64_sha="0a87d39f14d9163326879f9a786f406b3f98ba6465d7a8c2b1ad68311953dc85"
railway_arm64_sha="2cd9039d62253f42f5767fdba25d290a163d25072082939c338babb9bd939ce8"
gstack_ref="0d1bd5616c0ef096bb7ccee336f63c60ee408618"

bin_dir="${HOME}/.local/bin"
bun_dir="${HOME}/.bun/bin"
mkdir -p "$bin_dir" "$bun_dir"

case "$(uname -m)" in
  x86_64|amd64)
    bun_asset="bun-linux-x64.zip"
    bun_sha="$bun_x64_sha"
    railway_asset="railway-v${railway_version}-x86_64-unknown-linux-gnu.tar.gz"
    railway_sha="$railway_x64_sha"
    ;;
  aarch64|arm64)
    bun_asset="bun-linux-aarch64.zip"
    bun_sha="$bun_arm64_sha"
    railway_asset="railway-v${railway_version}-aarch64-unknown-linux-musl.tar.gz"
    railway_sha="$railway_arm64_sha"
    ;;
  *)
    echo "Unsupported Codespace architecture: $(uname -m)" >&2
    exit 2
    ;;
esac

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

if [[ ! -x "$bun_dir/bun" ]] || [[ "$("$bun_dir/bun" --version)" != "$bun_version" ]]; then
  curl -fsSL \
    "https://github.com/oven-sh/bun/releases/download/bun-v${bun_version}/${bun_asset}" \
    -o "$tmp_dir/bun.zip"
  printf '%s  %s\n' "$bun_sha" "$tmp_dir/bun.zip" | sha256sum -c -
  unzip -q "$tmp_dir/bun.zip" -d "$tmp_dir/bun"
  install -m 0755 "$(find "$tmp_dir/bun" -type f -name bun -print -quit)" "$bun_dir/bun"
fi
# Bun's release archive contains the runtime binary; gstack invokes the bunx
# alias that the official Bun installer normally creates beside it.
ln -sfn bun "$bun_dir/bunx"

if [[ ! -x "$bin_dir/railway" ]] || [[ "$("$bin_dir/railway" --version)" != "railway ${railway_version}" ]]; then
  curl -fsSL \
    "https://github.com/railwayapp/cli/releases/download/v${railway_version}/${railway_asset}" \
    -o "$tmp_dir/railway.tar.gz"
  printf '%s  %s\n' "$railway_sha" "$tmp_dir/railway.tar.gz" | sha256sum -c -
  mkdir -p "$tmp_dir/railway"
  tar -xzf "$tmp_dir/railway.tar.gz" -C "$tmp_dir/railway"
  install -m 0755 "$(find "$tmp_dir/railway" -type f -name railway -print -quit)" "$bin_dir/railway"
fi

gstack_root="${HOME}/.claude/skills/gstack"
if [[ ! -d "$gstack_root/.git" ]]; then
  mkdir -p "$(dirname "$gstack_root")"
  git clone https://github.com/garrytan/gstack.git "$gstack_root"
fi
git -C "$gstack_root" fetch --depth 1 origin "$gstack_ref"
git -C "$gstack_root" checkout --detach "$gstack_ref"
(cd "$gstack_root" && PATH="$bun_dir:$bin_dir:$PATH" "$bun_dir/bun" install --frozen-lockfile)
playwright_deps_marker="/usr/local/share/hawknetic-gstack-playwright-deps"
if [[ ! -f "$playwright_deps_marker" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    (cd "$gstack_root" && PATH="$bun_dir:$bin_dir:$PATH" "$bun_dir/bunx" playwright install-deps chromium)
    install -d "$(dirname "$playwright_deps_marker")"
    touch "$playwright_deps_marker"
  elif command -v sudo >/dev/null 2>&1; then
    (cd "$gstack_root" && sudo env PATH="$bun_dir:$bin_dir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      "$bun_dir/bunx" playwright install-deps chromium)
    sudo install -d "$(dirname "$playwright_deps_marker")"
    sudo touch "$playwright_deps_marker"
  else
    echo "gstack requires Playwright system packages; sudo is unavailable." >&2
    exit 2
  fi
fi
PATH="$bun_dir:$bin_dir:$PATH" "$gstack_root/setup" --team

# This is deliberately written as a literal for future login shells.
# shellcheck disable=SC2016
profile_line='export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"'
grep -Fqx "$profile_line" "${HOME}/.profile" 2>/dev/null \
  || printf '\n%s\n' "$profile_line" >> "${HOME}/.profile"

PATH="$bun_dir:$bin_dir:$PATH" bun --version
PATH="$bun_dir:$bin_dir:$PATH" railway --version
test -d "$gstack_root/bin"
echo "Cloud development tools are installed."
