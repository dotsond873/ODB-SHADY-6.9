#!/usr/bin/env bash
set -u
# Keep chat available even if the optional image network fails.
if [[ -n "${TS_AUTHKEY:-}" && -x .tailscale/tailscaled ]]; then
  state=$(mktemp -d)
  .tailscale/tailscaled --tun=userspace-networking --state=mem: --socket="$state/tailscaled.sock" --outbound-http-proxy-listen=127.0.0.1:1055 >"$state/daemon.log" 2>&1 &
  if timeout 35 .tailscale/tailscale --socket="$state/tailscaled.sock" up --auth-key="$TS_AUTHKEY" --hostname=shady-render --accept-dns=false --accept-routes=false >/dev/null 2>&1; then
    if [[ -n "${LOCAL_DREAM_HOST:-}" ]] && curl --silent --fail --max-time 10 --noproxy "" --proxy http://127.0.0.1:1055 "http://${LOCAL_DREAM_HOST}:8808/models" >/dev/null; then
      echo "Local Dream connectivity probe passed"
    else
      echo "Local Dream connectivity probe failed or host not configured"
    fi
  else
    echo "Tailscale connection failed; starting chat normally"
  fi
else
  echo "Tailscale not configured; starting chat normally"
fi
exec python serve.py
