#!/usr/bin/env bash
#
# Install Tailscale + bring the box onto your tailnet (with Tailscale SSH).
# Gives stable remote access regardless of the local network — ideal for a booth
# behind a flaky/garage connection.
#
#   sudo ./scripts/tailscale-setup.sh
#
# Env:
#   TS_AUTHKEY=tskey-...   non-interactive login (from the Tailscale admin console)
#   TS_HOSTNAME=mkphotobox device name on the tailnet
#   TS_SSH=1               enable Tailscale SSH (default 1)
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

TS_HOSTNAME="${TS_HOSTNAME:-mkphotobox}"
TS_SSH="${TS_SSH:-1}"

# ── install ───────────────────────────────────────────────────────────────
if ! command -v tailscale >/dev/null; then
  echo ">>> Tailscale installieren"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

# ── bring up ──────────────────────────────────────────────────────────────
UP_ARGS=(--hostname="$TS_HOSTNAME")
[[ "$TS_SSH" == 1 ]] && UP_ARGS+=(--ssh)

if [[ -n "${TS_AUTHKEY:-}" ]]; then
  echo ">>> tailscale up (Auth-Key, nicht-interaktiv)"
  tailscale up "${UP_ARGS[@]}" --authkey="$TS_AUTHKEY"
else
  echo ">>> tailscale up — bitte den angezeigten Link im Browser bestätigen:"
  tailscale up "${UP_ARGS[@]}"
fi

# ── report ────────────────────────────────────────────────────────────────
echo ">>> Tailscale aktiv"
echo "    Tailnet-IP : $(tailscale ip -4 2>/dev/null | head -1)"
echo "    Hostname   : $TS_HOSTNAME"
[[ "$TS_SSH" == 1 ]] && echo "    Tailscale SSH aktiviert -> 'ssh photobooth@$TS_HOSTNAME' aus dem Tailnet"
tailscale status 2>/dev/null | head -5 || true
