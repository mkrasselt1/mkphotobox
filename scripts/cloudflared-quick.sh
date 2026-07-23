#!/usr/bin/env bash
#
# Run a Cloudflare *quick tunnel* in the foreground and publish its public URL.
#
# A quick tunnel needs no Cloudflare account/login: cloudflared hands out a
# random https://<something>.trycloudflare.com address that proxies to the local
# booth. We parse that URL from cloudflared's output and write it (atomically) to
# data/tunnel_url.txt, which the app reads in /api/v1/system/share-base so guest
# QR codes point at the internet-reachable tunnel instead of the LAN IP.
#
# Meant to be run by the mkphotobox-tunnel.service systemd unit (Restart=always).
# On each (re)start cloudflared issues a NEW url — that's fine, the file follows.
#
#   ./scripts/cloudflared-quick.sh [PORT]     (PORT default 8080)
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8080}"
URLFILE="$APP_DIR/data/tunnel_url.txt"

command -v cloudflared >/dev/null 2>&1 || { echo "cloudflared nicht installiert — scripts/cloudflared-setup.sh ausführen"; exit 1; }
mkdir -p "$APP_DIR/data"

# Start fresh: a stale URL from a previous run must not linger.
rm -f "$URLFILE"

echo ">>> Cloudflare Quick-Tunnel -> http://localhost:$PORT"
# Line-buffer so we can react to the URL as soon as it is printed.
stdbuf -oL -eL cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" 2>&1 | while IFS= read -r line; do
  echo "$line"
  url="$(printf '%s' "$line" | grep -oE 'https://[a-zA-Z0-9._-]+\.trycloudflare\.com' | head -1 || true)"
  if [[ -n "$url" ]]; then
    printf '%s\n' "$url" > "$URLFILE.tmp" && mv "$URLFILE.tmp" "$URLFILE"
    echo ">>> Tunnel-URL: $url  (-> $URLFILE)"
  fi
done
