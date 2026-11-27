#!/usr/bin/env bash
set -euo pipefail
pip install -e ".[local-image]"
version=1.90.9
archive="tailscale_${version}_amd64.tgz"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if (
  cd "$tmp"
  curl -fsSLO "https://pkgs.tailscale.com/stable/$archive"
  curl -fsSLO "https://pkgs.tailscale.com/stable/$archive.sha256"
  expected=$(awk 'NR==1 {print $1}' "$archive.sha256")
  printf '%s  %s\n' "$expected" "$archive" | sha256sum -c -
  tar -xzf "$archive"
); then
  mkdir -p .tailscale
  cp "$tmp/tailscale_${version}_amd64/"{tailscale,tailscaled} .tailscale/
else
  echo "Optional Tailscale install failed; chat remains available"
fi
