#!/usr/bin/env bash
#
# MKPhotobox setup — installs system deps, a Python venv, and a systemd service.
# Idempotent: safe to re-run. Tested on Ubuntu 24.04 (x86_64).
#
#   sudo ./scripts/setup.sh
#
# Grundsatz: alles, was ein Modul zum Laufen braucht, wird mitinstalliert — ein
# Modul soll sich im Admin-Bereich einschalten lassen, ohne dass jemand erst ein
# Terminal öffnet. Auf 0 stehen nur Dinge, die das nicht rechtfertigen: sehr
# große Downloads (WITH_BG_AI zieht onnxruntime) und Netzdienste, die eine
# Anmeldung oder ein Konto brauchen (Tailscale, Cloudflare).
#
# Optional env toggles (default 1 = install):
#   WITH_GPHOTO2 WITH_PRINTER WITH_CDBURN WITH_WIFI WITH_AUDIO WITH_OPENCV
#   WITH_TRIGGERS WITH_SERIAL WITH_PAYMENT WITH_BLUETOOTH
# Standardmäßig aus (=0): WITH_BG_AI WITH_TAILSCALE WITH_CLOUDFLARE
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
WITH_AUDIO="${WITH_AUDIO:-1}"            # libportaudio2 + sounddevice (Klatsch-Auslöser)
WITH_OPENCV="${WITH_OPENCV:-1}"
WITH_TRIGGERS="${WITH_TRIGGERS:-1}"      # evdev/pynput (host_keyboard, bluetooth, evdev triggers)
WITH_SERIAL="${WITH_SERIAL:-1}"          # pyserial (serieller Auslöser) — klein
WITH_PAYMENT="${WITH_PAYMENT:-1}"        # httpx (SumUp payment) — small
WITH_BLUETOOTH="${WITH_BLUETOOTH:-1}"    # bluez + bluez-tools (Foto senden/empfangen)
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
if [[ "$WITH_GPHOTO2" == 1 ]]; then PKGS+=(libgphoto2-dev); fi
if [[ "$WITH_PRINTER" == 1 ]]; then PKGS+=(cups libcups2-dev); fi
if [[ "$WITH_CDBURN"  == 1 ]]; then PKGS+=(xorriso); fi
if [[ "$WITH_WIFI"    == 1 ]]; then PKGS+=(network-manager); fi
if [[ "$WITH_AUDIO"   == 1 ]]; then PKGS+=(libportaudio2); fi
# bluez-tools liefert bt-obex/bt-agent (senden + empfangen, headless-tauglich);
# gnome-bluetooth-sendto wäre ein GTK-Dialog und auf einer Kiosk-Box nutzlos.
if [[ "$WITH_BLUETOOTH" == 1 ]]; then PKGS+=(bluez bluez-obexd bluez-tools obexftp); fi
apt-get update -y
apt-get install -y "${PKGS[@]}"

# ── 2) python venv + dependencies ─────────────────────────────────────────
echo ">>> [2/5] Python-venv + Abhängigkeiten"
[[ -d "$VENV" ]] || sudo -u "$RUN_USER" python3 -m venv "$VENV"

# Booths sit on event WLAN, which drops mid-download often enough that a plain
# `pip install` fails with a resume loop. Long timeout + many retries survives it.
PIP_OPTS=(--timeout 120 --retries 15)

sudo -u "$RUN_USER" "$PIP" install "${PIP_OPTS[@]}" --upgrade pip
# Since Python 3.12 `venv` no longer seeds setuptools/wheel, so every package
# built from source (evdev, pyserial) fails in pip's isolated build env with
# "Could not find a version that satisfies the requirement setuptools".
sudo -u "$RUN_USER" "$PIP" install "${PIP_OPTS[@]}" setuptools wheel
sudo -u "$RUN_USER" "$PIP" install "${PIP_OPTS[@]}" -e "$APP_DIR"
# CRITICAL: pin compatible fastapi/starlette (newer versions silently break include_router)
sudo -u "$RUN_USER" "$PIP" install "fastapi==0.135.3" "starlette==1.0.0"
# Optional extras. These used to end in "|| true", which silenced every failure:
# a box could run for months with the OpenCV camera and the evdev triggers simply
# absent, and the admin page had no way to say so. Failures are now collected and
# reported at the end instead of aborting the run (set -e) or vanishing.
PIP_FAILED=()

pip_extra() {   # pip_extra <Beschriftung> <paket…>
  local label="$1"; shift
  printf '    %-26s' "$label"
  if sudo -u "$RUN_USER" "$PIP" install "${PIP_OPTS[@]}" "$@" >/tmp/mkphotobox-pip.log 2>&1; then
    echo "ok"
  else
    echo "FEHLGESCHLAGEN"
    PIP_FAILED+=("$label")
    tail -3 /tmp/mkphotobox-pip.log | sed 's/^/      /'
  fi
}

echo "  optionale Zusatzpakete:"
if [[ "$WITH_GPHOTO2"  == 1 ]]; then pip_extra "DSLR (gphoto2)"      "gphoto2>=2.5"; fi
if [[ "$WITH_OPENCV"   == 1 ]]; then pip_extra "Webcam (opencv)"     "opencv-python-headless>=4.8"; fi
if [[ "$WITH_PRINTER"  == 1 ]]; then pip_extra "Drucker (pycups)"    "pycups>=2.0"; fi
if [[ "$WITH_AUDIO"    == 1 ]]; then pip_extra "Akustik-Auslöser"    "sounddevice>=0.4" "numpy>=1.24"; fi
if [[ "$WITH_TRIGGERS" == 1 ]]; then pip_extra "Auslöser (evdev)"    "evdev>=1.6" "pynput>=1.7"; fi
if [[ "$WITH_SERIAL"   == 1 ]]; then pip_extra "Serieller Auslöser"  "pyserial>=3.5"; fi
if [[ "$WITH_PAYMENT"  == 1 ]]; then pip_extra "Bezahlung (httpx)"   "httpx>=0.27"; fi
if [[ "$WITH_BG_AI"    == 1 ]]; then pip_extra "KI-Hintergrund"      "rembg>=2.0"; fi
rm -f /tmp/mkphotobox-pip.log

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

# Diese Zeilen endeten früher auf "2>/dev/null || true" und verschluckten damit
# jeden Fehlschlag. Auf einer laufenden Box fehlte dadurch die Gruppe 'input',
# ohne dass es irgendwo sichtbar war: /dev/input war für den Dienst unlesbar,
# also funktionierten Host-Tastatur, Bluetooth-Fernauslöser und der
# Touchscreen-Auslöser schlicht nicht — kommentarlos.
GROUP_FAILED=()

add_group() {   # add_group <gruppe> <wofür>
  local grp="$1" purpose="$2"
  printf '    %-10s (%s) ' "$grp" "$purpose"
  if ! getent group "$grp" >/dev/null; then
    echo "übersprungen — Gruppe existiert auf diesem System nicht"
    return
  fi
  # "|| true" ist hier Absicht: ohne es würde set -e das Skript beenden, bevor
  # die Prüfung unten den Fehlschlag melden kann. Die Ausgabe wird aufgehoben
  # statt verworfen, damit der Grund im Klartext dasteht.
  local err
  err="$(usermod -aG "$grp" "$RUN_USER" 2>&1)" || true
  # Am Ergebnis messen, nicht am Rückgabewert.
  if id -nG "$RUN_USER" | tr ' ' '\n' | grep -qx "$grp"; then
    echo "ok"
  else
    echo "FEHLGESCHLAGEN"
    [[ -n "$err" ]] && echo "      $err"
    GROUP_FAILED+=("$grp ($purpose)")
  fi
}

echo "  Gruppen für $RUN_USER:"
if [[ "$WITH_CDBURN" == 1 ]]; then add_group cdrom "CD/DVD brennen"; fi
add_group dialout "serieller Touchscreen / Auslöser"
if [[ "$WITH_TRIGGERS" == 1 ]]; then add_group input "evdev — Tastatur-/Bluetooth-Auslöser"; fi

# ── 4) systemd service ────────────────────────────────────────────────────
echo ">>> [4/5] systemd-Dienst"
cat > /etc/systemd/system/mkphotobox.service <<UNIT
[Unit]
Description=MKPhotobox
# Bewusst NICHT network-online.target: die Box arbeitet offline. Warten wir auf
# eine Internetverbindung, blockiert NetworkManager-wait-online den Start bis zu
# seinem Timeout (30s) — und der Kiosk zeigt so lange einen schwarzen Bildschirm.
# network.target genügt: der Uvicorn bindet auf 0.0.0.0, eine Route braucht er nicht.
After=network.target

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
add_group netdev "NetworkManager"

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

# ── 4a2) optional: Bluetooth-Dateiempfang ─────────────────────────────────
# obexd hängt am D-Bus *Session*-Bus, der Dienst läuft aber als System-Unit
# ohne Sitzung. Lingering hält /run/user/<uid>/bus dauerhaft am Leben, die
# Units zeigen DBUS_SESSION_BUS_ADDRESS dann explizit dorthin.
if [[ "$WITH_BLUETOOTH" == 1 ]]; then
  echo ">>> [4a2] Bluetooth-Empfang (OBEX)"
  RUN_UID="$(id -u "$RUN_USER")"
  RECV_DIR="$APP_DIR/data/bluetooth_in"
  sudo -u "$RUN_USER" mkdir -p "$RECV_DIR"
  loginctl enable-linger "$RUN_USER" 2>/dev/null || true
  add_group bluetooth "Bluetooth-Adapter steuern"

  # Kopplungsanfragen ohne Tastatur/Display annehmen (Gast tippt am Handy).
  cat > /etc/systemd/system/mkphotobox-btagent.service <<UNIT
[Unit]
Description=MKPhotobox Bluetooth-Kopplungsagent
After=bluetooth.service user@$RUN_UID.service
Requires=bluetooth.service

[Service]
User=$RUN_USER
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$RUN_UID/bus
Environment=XDG_RUNTIME_DIR=/run/user/$RUN_UID
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  # OBEX-Push-Server: eingehende Dateien landen ohne Rückfrage in RECV_DIR.
  cat > /etc/systemd/system/mkphotobox-btrecv.service <<UNIT
[Unit]
Description=MKPhotobox Bluetooth-Dateiempfang (OBEX Object Push)
After=bluetooth.service user@$RUN_UID.service mkphotobox-btagent.service
Requires=bluetooth.service

[Service]
User=$RUN_USER
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$RUN_UID/bus
Environment=XDG_RUNTIME_DIR=/run/user/$RUN_UID
ExecStart=/usr/bin/bt-obex --server $RECV_DIR --auto-accept
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable --now mkphotobox-btagent.service mkphotobox-btrecv.service || \
    echo "  WARN: Bluetooth-Units nicht gestartet"

  # Sichtbar bleiben, statt nach 180s zu verschwinden.
  sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/$RUN_UID" \
    bluetoothctl discoverable-timeout 0 >/dev/null 2>&1 || true
  echo "  Empfangsordner: $RECV_DIR"
fi

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
# Neu starten, bevor der Status gemeldet wird: frisch hinzugefügte Gruppen
# greifen erst ab dem nächsten Prozessstart, sonst läuft der Dienst mit den
# alten Rechten weiter und findet z.B. kein /dev/input.
systemctl restart mkphotobox.service 2>/dev/null || true

echo ">>> [5/5] Fertig"
sleep 4
systemctl is-active --quiet mkphotobox.service \
  && echo "    Dienst läuft: http://$(hostname -I | awk '{print $1}'):8080" \
  || { echo "!! Dienst nicht aktiv — Log:"; journalctl -u mkphotobox.service -n 20 --no-pager; }
echo "    Admin-Login: admin / admin  (bitte ändern)"
echo "    Optional Kiosk: sudo ./scripts/kiosk-setup.sh"

if [[ ${#PIP_FAILED[@]} -gt 0 ]]; then
  echo
  echo "!! Diese optionalen Pakete wurden NICHT installiert:"
  for f in "${PIP_FAILED[@]}"; do echo "     - $f"; done
  echo "   Die zugehörigen Module bleiben deaktiviert; Admin → Module nennt den Grund."
  echo "   Häufigste Ursache ist eine abbrechende Internetverbindung — dann einfach"
  echo "   das Setup erneut ausführen."
fi

if [[ ${#GROUP_FAILED[@]} -gt 0 ]]; then
  echo
  echo "!! $RUN_USER konnte diesen Gruppen NICHT hinzugefügt werden:"
  for f in "${GROUP_FAILED[@]}"; do echo "     - $f"; done
  echo "   Ohne sie kommt der Dienst nicht an die Geräte und die betroffenen Auslöser"
  echo "   bleiben still, ohne eine Fehlermeldung zu zeigen. Von Hand nachholen mit"
  echo "   'sudo usermod -aG <gruppe> $RUN_USER', danach 'sudo systemctl restart"
  echo "   mkphotobox.service' — Gruppen gelten erst ab dem nächsten Prozessstart."
fi
