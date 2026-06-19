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
  firefox) CMD="firefox --kiosk $KIOSK_URL" ;;
  *) CMD="$BROWSER --kiosk --noerrordialogs --disable-infobars --disable-session-crashed-bubble --disable-translate --no-first-run --no-default-browser-check --incognito --check-for-update-interval=31536000 --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required --overscroll-history-navigation=0 --disable-pinch $KIOSK_URL" ;;
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

# Watchdog: if the app is unreachable for ~30s, kill the browser so the
# respawn loop relaunches it fresh (recovers from frozen pages / app restarts).
(
  fails=0
  while true; do
    if curl -s -o /dev/null --max-time 5 __URL__; then
      fails=0
    else
      fails=$((fails + 1))
    fi
    if [ "$fails" -ge 6 ]; then
      pkill -f 'google-chrome|chromium|firefox' 2>/dev/null
      fails=0
    fi
    sleep 5
  done
) &

# Respawn loop: wait for the app, launch the browser (blocks until it exits),
# then relaunch — survives browser crashes/closes.
while true; do
  until curl -s -o /dev/null __URL__; do sleep 1; done
  __CMD__
  sleep 2
done
AUTO
sed -i "s|__URL__|$KIOSK_URL|g; s|__CMD__|$CMD|g" "$HOME_DIR/.config/openbox/autostart"
chmod +x "$HOME_DIR/.config/openbox/autostart"
chown -R "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.config/openbox"

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
