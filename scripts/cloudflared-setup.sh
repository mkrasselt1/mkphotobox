#!/usr/bin/env bash
#
# Install cloudflared + a systemd service that runs a Cloudflare *quick tunnel*
# for the booth, giving guest phones an internet-reachable URL for QR codes
# (no Cloudflare account/login required).
#
#   sudo ./scripts/cloudflared-setup.sh
#
# Env:
#   RUN_USER=<user>   (default: the invoking sudo user / owner of the app dir)
#   PORT=8080         local port the booth serves on
#   ENABLE=1          enable+start the tunnel now (default 1). ENABLE=0 only
#                     installs the binary + unit; the app toggles it later.
#
# Idempotent: safe to re-run (also used by scripts/update.sh to refresh things).
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(stat -c %U "$APP_DIR")}}"
PORT="${PORT:-8080}"
ENABLE="${ENABLE:-1}"

# ── 1) install cloudflared (static binary from GitHub releases) ────────────
if ! command -v cloudflared >/dev/null 2>&1; then
  case "$(uname -m)" in
    x86_64|amd64)   ARCH=amd64 ;;
    aarch64|arm64)  ARCH=arm64 ;;
    armv7l|armhf)   ARCH=arm   ;;
    *) echo "!! Nicht unterstützte Architektur: $(uname -m)"; exit 1 ;;
  esac
  echo ">>> cloudflared installieren ($ARCH)"
  curl -fsSL -o /usr/local/bin/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH"
  chmod +x /usr/local/bin/cloudflared
else
  echo ">>> cloudflared bereits installiert: $(command -v cloudflared)"
fi
cloudflared --version || true

# ── 2) systemd service (quick tunnel wrapper) ──────────────────────────────
echo ">>> systemd-Dienst mkphotobox-tunnel"
cat > /etc/systemd/system/mkphotobox-tunnel.service <<UNIT
[Unit]
Description=MKPhotobox Cloudflare Quick Tunnel (öffentliche QR-Links)
After=network-online.target mkphotobox.service
Wants=network-online.target

[Service]
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env bash $APP_DIR/scripts/cloudflared-quick.sh $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload

# ── 3) let the app user control the tunnel service without a password ───────
# (admin toggle: start/stop/restart mkphotobox-tunnel)
echo ">>> sudoers: Tunnel-Dienst ohne Passwort steuerbar"
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start mkphotobox-tunnel.service, /usr/bin/systemctl stop mkphotobox-tunnel.service, /usr/bin/systemctl restart mkphotobox-tunnel.service, /usr/bin/systemctl enable mkphotobox-tunnel.service, /usr/bin/systemctl disable mkphotobox-tunnel.service\n' "$RUN_USER" > /tmp/mkphotobox-tunnel-sudoers
if visudo -cf /tmp/mkphotobox-tunnel-sudoers >/dev/null 2>&1; then
  install -m 440 -o root -g root /tmp/mkphotobox-tunnel-sudoers /etc/sudoers.d/mkphotobox-tunnel
  echo "  sudoers-Regel installiert"
else
  echo "  WARN: sudoers-Regel ungültig — übersprungen"
fi
rm -f /tmp/mkphotobox-tunnel-sudoers

# ── 4) enable + start now (optional) ───────────────────────────────────────
if [[ "$ENABLE" == 1 ]]; then
  echo ">>> Tunnel aktivieren + starten"
  systemctl enable --now mkphotobox-tunnel.service
  sleep 6
  URLFILE="$APP_DIR/data/tunnel_url.txt"
  if [[ -s "$URLFILE" ]]; then
    echo "    Tunnel-URL: $(cat "$URLFILE")"
  else
    echo "    (URL noch nicht geschrieben — 'journalctl -u mkphotobox-tunnel -n 30' prüfen)"
  fi
else
  echo ">>> Tunnel installiert, aber NICHT gestartet (ENABLE=0). App-Toggle startet ihn."
fi

echo ">>> Fertig. Aktivierung in der App: config share.tunnel.enabled = true"
