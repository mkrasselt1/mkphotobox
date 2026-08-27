#!/usr/bin/env bash
#
# MKPhotobox kiosk — boots straight into a fullscreen browser on a minimal X11
# session (openbox), with autologin via SDDM. X11 (not Wayland) keeps rustdesk
# screen-sharing working. Optionally sets up a serial touchscreen (inputattach).
#
#   sudo ./scripts/kiosk-setup.sh
#
# Env:
#   KIOSK_USER=<user>            (default: invoking sudo user)
#   KIOSK_URL=http://localhost:8080
#   BROWSER=auto                 (auto|google-chrome-stable|chromium|firefox)
#   DISABLE_OTHER_SESSIONS=1     (move non-kiosk xsessions out of the way)
#   TOUCH_SERIAL=                (e.g. eetiegalax — enables serial touch setup)
#   TOUCH_PORT=/dev/ttyS0
#   TOUCH_MATRIX="0 -1.3 1.15 -1.3 0 1.15 0 0 1"   (libinput CalibrationMatrix)
#   TOUCH_PRODUCT="EETI eGalaxTouch Serial TouchScreen"
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-photobooth}}"
KIOSK_URL="${KIOSK_URL:-http://localhost:8080}"
BROWSER="${BROWSER:-auto}"
DISABLE_OTHER_SESSIONS="${DISABLE_OTHER_SESSIONS:-1}"
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Loading screen shown immediately (no black wait); it redirects to KIOSK_URL
# once the app is up. The target is passed via the hash so loading.html is generic.
LOADING_URL="file://$APP_DIR/scripts/kiosk/loading.html#$KIOSK_URL"

echo ">>> Kiosk für $KIOSK_USER -> $KIOSK_URL"

# ── packages (minimal X + WM) ─────────────────────────────────────────────
apt-get update -y
apt-get install -y xserver-xorg xinit openbox unclutter x11-xserver-utils curl sddm

# ── resolve browser ───────────────────────────────────────────────────────
pick_browser() {
  for b in google-chrome-stable chromium chromium-browser firefox; do
    command -v "$b" >/dev/null && { echo "$b"; return; }
  done
  echo ""
}
[[ "$BROWSER" == auto ]] && BROWSER="$(pick_browser)"
[[ -n "$BROWSER" ]] || { echo "!! Kein Browser gefunden. Installiere google-chrome-stable, chromium oder firefox."; exit 1; }
echo "    Browser: $BROWSER"

case "$BROWSER" in
  firefox) CMD="firefox --kiosk $LOADING_URL" ;;
  *) CMD="$BROWSER --kiosk --noerrordialogs --disable-infobars --disable-session-crashed-bubble --disable-translate --no-first-run --no-default-browser-check --incognito --check-for-update-interval=31536000 --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required --overscroll-history-navigation=0 --disable-pinch $LOADING_URL" ;;
esac

# ── openbox autostart: respawn loop + health watchdog (unattended) ────────
# Quoted heredoc keeps runtime $-vars literal; __CMD__/__URL__ injected via sed.
install -d -o "$KIOSK_USER" -g "$KIOSK_USER" "$HOME_DIR/.config/openbox"
cat > "$HOME_DIR/.config/openbox/autostart" <<'AUTO'
#!/bin/sh
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &

# Watchdog: once the app has been reachable, kill the browser if it later goes
# away for ~30s so the respawn loop relaunches it (recovers frozen pages / long
# app outages). up_once guard keeps it from killing the loading screen at boot.
(
  up_once=0
  fails=0
  while true; do
    if curl -s -o /dev/null --max-time 5 __URL__; then
      up_once=1
      fails=0
    else
      fails=$((fails + 1))
    fi
    if [ "$up_once" -eq 1 ] && [ "$fails" -ge 6 ]; then
      pkill -f 'google-chrome|chromium|firefox' 2>/dev/null
      fails=0
    fi
    sleep 5
  done
) &

# Respawn loop: launch the browser immediately on the loading screen (no black
# wait) — loading.html polls the app and redirects to the booth once it's up.
# Blocks until the browser exits, then relaunches (survives crashes/closes).
while true; do
  __CMD__
  sleep 2
done
AUTO
sed -i "s|__URL__|$KIOSK_URL|g; s|__CMD__|$CMD|g" "$HOME_DIR/.config/openbox/autostart"
chmod +x "$HOME_DIR/.config/openbox/autostart"
chown -R "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.config/openbox"

# ── zweiter Startweg: tty1-Autologin + startx (~/.xinitrc) ────────────────
# Nicht jede Box hat SDDM. Wo die Sitzung über die Konsole hochkommt, startet
# `openbox &` aus ~/.xinitrc — und dann wird ~/.config/openbox/autostart NICHT
# ausgeführt (das macht nur openbox-session). Ohne eine gepflegte ~/.xinitrc
# läuft dort also weiter eine alte Fassung, typischerweise die, die vor dem
# Browserstart auf die App wartet: minutenlang schwarzer Bildschirm.
# Darum hier dieselbe Logik ein zweites Mal ablegen, aus derselben Quelle.
if [[ -f "$HOME_DIR/.xinitrc" ]] && ! cmp -s "$APP_DIR/scripts/kiosk/xinitrc" "$HOME_DIR/.xinitrc"; then
  cp -a "$HOME_DIR/.xinitrc" "$HOME_DIR/.xinitrc.bak-$(date +%Y%m%d-%H%M%S)"
  echo "    alte ~/.xinitrc gesichert"
fi
sed -e "s|^APP_DIR=.*|APP_DIR=\"$APP_DIR\"|" \
    -e "s|^URL=.*|URL=\"$KIOSK_URL\"|" \
    "$APP_DIR/scripts/kiosk/xinitrc" > "$HOME_DIR/.xinitrc"
chmod +x "$HOME_DIR/.xinitrc"
chown "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.xinitrc"

# Autologin-Shell auf tty1 startet X, falls dieser Weg genutzt wird.
PROFILE="$HOME_DIR/.bash_profile"
LINE='if [ "$(tty)" = "/dev/tty1" ] && [ -z "$DISPLAY" ]; then exec startx -- -nocursor; fi'
if ! grep -qF 'exec startx' "$PROFILE" 2>/dev/null; then
  printf '%s\n' '#!/bin/sh' "$LINE" >> "$PROFILE"
  chown "$KIOSK_USER:$KIOSK_USER" "$PROFILE"
fi
echo "    ~/.xinitrc aktualisiert (Ladebildschirm sofort, kein schwarzes Warten)"

# ── Chrome-Richtlinien: keine Sprechblasen vor Gästen ─────────────────────
# Startparameter reichen nicht. Google entfernt sie (--disable-infobars ist seit
# Chrome 76 wirkungslos), und im Kiosk-Modus erscheinen die Blasen oben links,
# weil sie an der fehlenden Adressleiste hängen. Richtlinien überleben Updates.
if [[ "$BROWSER" == google-chrome-stable || "$BROWSER" == chromium* ]]; then
  case "$BROWSER" in
    chromium*) POLICY_DIR=/etc/chromium/policies/managed ;;
    *)         POLICY_DIR=/etc/opt/chrome/policies/managed ;;
  esac
  install -d "$POLICY_DIR"
  install -m 0644 "$APP_DIR/scripts/kiosk/chrome-policy.json" "$POLICY_DIR/mkphotobox.json"
  echo "    Browser-Richtlinien: $POLICY_DIR/mkphotobox.json"
fi

# ── kiosk X session + SDDM autologin ──────────────────────────────────────
cat > /usr/share/xsessions/kiosk.desktop <<'XS'
[Desktop Entry]
Name=Kiosk
Comment=MKPhotobox Kiosk
Exec=openbox-session
Type=Application
XS

if [[ "$DISABLE_OTHER_SESSIONS" == 1 ]]; then
  for s in /usr/share/xsessions/*.desktop; do
    [[ "$(basename "$s")" == kiosk.desktop ]] && continue
    mv "$s" "$s.disabled" && echo "    deaktiviert: $(basename "$s")"
  done
fi

mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/autologin.conf <<SD
[Autologin]
User=$KIOSK_USER
Session=kiosk
Relogin=true
SD
rm -f /var/lib/sddm/state.conf   # drop remembered last session

# ── optional: serial touchscreen (inputattach + libinput calibration) ─────
if [[ -n "${TOUCH_SERIAL:-}" ]]; then
  TOUCH_PORT="${TOUCH_PORT:-/dev/ttyS0}"
  TOUCH_PRODUCT="${TOUCH_PRODUCT:-EETI eGalaxTouch Serial TouchScreen}"
  TOUCH_MATRIX="${TOUCH_MATRIX:-1 0 0 0 1 0 0 0 1}"
  echo ">>> Serieller Touch: --$TOUCH_SERIAL $TOUCH_PORT"
  apt-get install -y inputattach

  cat > /etc/systemd/system/egalax-touch.service <<UNIT
[Unit]
Description=Serial touchscreen (inputattach)
After=systemd-udev-settle.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/inputattach --$TOUCH_SERIAL $TOUCH_PORT
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

  cat > /etc/X11/xorg.conf.d/98-touch-calibration.conf <<XC
Section "InputClass"
    Identifier "touch calibration"
    MatchProduct "$TOUCH_PRODUCT"
    Driver "libinput"
    Option "CalibrationMatrix" "$TOUCH_MATRIX"
EndSection
XC
  systemctl daemon-reload
  systemctl enable --now egalax-touch.service
fi

# ── apply ─────────────────────────────────────────────────────────────────
systemctl restart sddm
echo ">>> Kiosk eingerichtet. Anzeige startet neu."
echo "    (Browser=$BROWSER, Session=kiosk, User=$KIOSK_USER)"
