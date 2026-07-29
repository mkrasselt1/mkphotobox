#!/usr/bin/env bash
#
# MKPhotobox setup — installs system deps, a Python venv, and a systemd service.
# Idempotent: safe to re-run. Tested on Ubuntu 24.04 (x86_64).
#
#   sudo ./scripts/setup.sh
#
# Optional env toggles (default 1 = install):
#   WITH_GPHOTO2=1 WITH_PRINTER=1 WITH_CDBURN=1 WITH_WIFI=1 WITH_AUDIO=1 WITH_OPENCV=1
#   RUN_USER=<user>   (default: the invoking sudo user)
#
set -euo pipefail

# ── locate repo + run user ────────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un)}}"
VENV="$APP_DIR/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

WITH_GPHOTO2="${WITH_GPHOTO2:-1}"
WITH_PRINTER="${WITH_PRINTER:-1}"
WITH_CDBURN="${WITH_CDBURN:-1}"
WITH_WIFI="${WITH_WIFI:-1}"
WITH_AUDIO="${WITH_AUDIO:-0}"
WITH_OPENCV="${WITH_OPENCV:-1}"
WITH_TRIGGERS="${WITH_TRIGGERS:-1}"      # evdev/pynput (host_keyboard, bluetooth, evdev triggers)
WITH_PAYMENT="${WITH_PAYMENT:-1}"        # httpx (SumUp payment) — small
WITH_BLUETOOTH="${WITH_BLUETOOTH:-0}"    # bluez + gnome-bluetooth (bluetooth-sendto)
WITH_BG_AI="${WITH_BG_AI:-0}"            # rembg AI background removal — HEAVY (onnxruntime)
WITH_TAILSCALE="${WITH_TAILSCALE:-0}"    # Tailscale Remote-Zugang (TS_AUTHKEY für nicht-interaktiv)
WITH_CLOUDFLARE="${WITH_CLOUDFLARE:-0}"  # Cloudflare Quick-Tunnel für öffentliche QR-Links (cloudflared)
DISABLE_IPV6="${DISABLE_IPV6:-0}"        # IPv6 systemweit abschalten (hilft bei kaputtem IPv6-Routing)

echo ">>> MKPhotobox setup"
echo "    app dir : $APP_DIR"
echo "    user    : $RUN_USER"

if [[ $EUID -ne 0 ]]; then
  echo "!! Bitte mit sudo ausführen (für apt + systemd)."; exit 1
fi

# ── 1) system packages ────────────────────────────────────────────────────
echo ">>> [1/5] System-Pakete (apt)"
PKGS=(python3-venv python3-pip python3-dev build-essential pkg-config git curl rsync sshpass)
[[ "$WITH_GPHOTO2" == 1 ]] && PKGS+=(libgphoto2-dev)
[[ "$WITH_PRINTER" == 1 ]] && PKGS+=(cups libcups2-dev)
[[ "$WITH_CDBURN"  == 1 ]] && PKGS+=(xorriso)
[[ "$WITH_WIFI"    == 1 ]] && PKGS+=(network-manager)
[[ "$WITH_AUDIO"   == 1 ]] && PKGS+=(libportaudio2)
[[ "$WITH_BLUETOOTH" == 1 ]] && PKGS+=(bluez gnome-bluetooth-sendto)
apt-get update -y
apt-get install -y "${PKGS[@]}"

# ── 2) python venv + dependencies ─────────────────────────────────────────
echo ">>> [2/5] Python-venv + Abhängigkeiten"
[[ -d "$VENV" ]] || sudo -u "$RUN_USER" python3 -m venv "$VENV"
sudo -u "$RUN_USER" "$PIP" install --upgrade pip
sudo -u "$RUN_USER" "$PIP" install -e "$APP_DIR"
# CRITICAL: pin compatible fastapi/starlette (newer versions silently break include_router)
sudo -u "$RUN_USER" "$PIP" install "fastapi==0.135.3" "starlette==1.0.0"
# optional extras (best effort)
[[ "$WITH_GPHOTO2" == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "gphoto2>=2.5"   || true
[[ "$WITH_OPENCV"  == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "opencv-python-headless>=4.8" || true
[[ "$WITH_PRINTER" == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "pycups>=2.0"    || true
[[ "$WITH_AUDIO"   == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "sounddevice>=0.4" "numpy>=1.24" || true
[[ "$WITH_TRIGGERS" == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "evdev>=1.6" "pynput>=1.7" || true
[[ "$WITH_PAYMENT"  == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "httpx>=0.27" || true
[[ "$WITH_BG_AI"    == 1 ]] && sudo -u "$RUN_USER" "$PIP" install "rembg>=2.0"  || true

echo ">>> verify imports + route registration"
sudo -u "$RUN_USER" "$PY" - <<PYEOF
import app.main as m
print("routes:", len(m.app.routes))
assert len(m.app.routes) > 80, "too few routes — check fastapi/starlette versions!"
print("OK")
PYEOF

# ── 2b) ensure a real JWT secret_key (avoid the public dev fallback) ──────
echo ">>> [2b] secret_key sicherstellen"
sudo -u "$RUN_USER" "$PY" - "$APP_DIR/config.yaml" <<'PYEOF'
import os, sys, secrets, yaml
p = sys.argv[1]
data = {}
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
auth = data.setdefault("auth", {})
if not auth.get("secret_key"):
    auth["secret_key"] = secrets.token_urlsafe(48)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    print("  secret_key generiert -> config.yaml")
else:
    print("  secret_key bereits gesetzt")
PYEOF

# ── 2c) nice script/handwriting fonts for template text (best effort) ─────
echo ">>> [2c] Schriftarten für Text-Elemente"
sudo -u "$RUN_USER" bash "$APP_DIR/scripts/install-fonts.sh" || echo "  (Font-Download übersprungen — kein Internet?)"

# ── 3) data dirs + groups ─────────────────────────────────────────────────
echo ">>> [3/5] Datenverzeichnisse + Gruppen"
sudo -u "$RUN_USER" mkdir -p "$APP_DIR/data/photos/thumbs" "$APP_DIR/data/assets" "$APP_DIR/data/imports"
# allow access to optical drive / serial without sudo
[[ "$WITH_CDBURN" == 1 ]] && usermod -aG cdrom "$RUN_USER" 2>/dev/null || true
usermod -aG dialout "$RUN_USER" 2>/dev/null || true   # serial touchscreen / triggers
[[ "$WITH_TRIGGERS" == 1 ]] && usermod -aG input "$RUN_USER" 2>/dev/null || true   # evdev /dev/input access

# ── 4) systemd service ────────────────────────────────────────────────────
echo ">>> [4/5] systemd-Dienst"
cat > /etc/systemd/system/mkphotobox.service <<UNIT
[Unit]
Description=MKPhotobox
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$PY -m app.main
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mkphotobox.service

# allow the app user to power off / reboot / restart-itself without a password
# (admin Herunterfahren + Software-aktualisieren buttons)
echo ">>> sudoers: Herunterfahren/Neustart/Service-Restart ohne Passwort"
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot, /usr/bin/systemctl restart mkphotobox.service, /usr/bin/systemctl restart mkphotobox\n' "$RUN_USER" > /tmp/mkphotobox-sudoers
if visudo -cf /tmp/mkphotobox-sudoers >/dev/null 2>&1; then
  install -m 440 -o root -g root /tmp/mkphotobox-sudoers /etc/sudoers.d/mkphotobox
  echo "  sudoers-Regel installiert"
else
  echo "  WARN: sudoers-Regel ungültig — übersprungen"
fi
rm -f /tmp/mkphotobox-sudoers

# ── 4a) polkit: WLAN-Verwaltung für den Dienst-User ───────────────────────
# Der Dienst läuft als $RUN_USER ohne aktive Login-Session. NetworkManager
# fragt für alles Schreibende (Verbinden, Profile, Funk an/aus) polkit —
# ohne Session gibt es keinen "aktiven" Subject, also lehnt polkit ab:
# "Not authorized to control networking". Scannen geht ohne Auth, deshalb
# sieht man die SSIDs, aber Verbinden schlägt fehl.
echo ">>> polkit: WLAN-Verwaltung erlauben"
usermod -aG netdev "$RUN_USER" 2>/dev/null || true

# polkit >= 0.106 (Ubuntu 24.04): JS-Regeln
if [[ -d /etc/polkit-1/rules.d ]]; then
  cat > /etc/polkit-1/rules.d/50-mkphotobox-network.rules <<RULES
// MKPhotobox: dem Dienst-User NetworkManager-Steuerung erlauben (WLAN-Seite
// im Admin-Bereich). Ohne diese Regel: "Not authorized to control networking".
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 &&
        subject.user === "$RUN_USER") {
        return polkit.Result.YES;
    }
});
RULES
  chmod 644 /etc/polkit-1/rules.d/50-mkphotobox-network.rules
  echo "  polkit-Regel installiert (rules.d)"
fi

# polkit 0.105 (ältere Debian/Raspbian): .pkla-Fallback
if [[ -d /etc/polkit-1/localauthority/50-local.d ]]; then
  cat > /etc/polkit-1/localauthority/50-local.d/50-mkphotobox-network.pkla <<PKLA
[MKPhotobox network control]
Identity=unix-user:$RUN_USER
Action=org.freedesktop.NetworkManager.*
ResultAny=yes
ResultInactive=yes
ResultActive=yes
PKLA
  echo "  polkit-Regel installiert (pkla)"
fi

systemctl restart polkit 2>/dev/null || systemctl restart polkitd 2>/dev/null || true

# ── 4b) optional: Tailscale remote access ─────────────────────────────────
if [[ "$WITH_TAILSCALE" == 1 ]]; then
  echo ">>> [4b] Tailscale (Remote-Zugang)"
  bash "$APP_DIR/scripts/tailscale-setup.sh" || echo "  (Tailscale-Setup übersprungen/fehlgeschlagen)"
fi

# ── 4c) optional: Cloudflare quick tunnel (public QR links) ────────────────
if [[ "$WITH_CLOUDFLARE" == 1 ]]; then
  echo ">>> [4c] Cloudflare Quick-Tunnel (öffentliche QR-Links)"
  # Install binary + unit; ENABLE=0 so it only runs when turned on in the app.
  ENABLE=0 RUN_USER="$RUN_USER" bash "$APP_DIR/scripts/cloudflared-setup.sh" \
    || echo "  (Cloudflare-Setup übersprungen/fehlgeschlagen)"
fi

# ── 5) done ───────────────────────────────────────────────────────────────
echo ">>> [5/5] Fertig"
sleep 4
systemctl is-active --quiet mkphotobox.service \
  && echo "    Dienst läuft: http://$(hostname -I | awk '{print $1}'):8080" \
  || { echo "!! Dienst nicht aktiv — Log:"; journalctl -u mkphotobox.service -n 20 --no-pager; }
echo "    Admin-Login: admin / admin  (bitte ändern)"
echo "    Optional Kiosk: sudo ./scripts/kiosk-setup.sh"
