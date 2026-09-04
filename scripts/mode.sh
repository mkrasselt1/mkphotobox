#!/usr/bin/env bash
#
# MKPhotobox Modus-Umschalter — wechselt zwischen
#
#   kiosk    SDDM, Autologin, openbox + Vollbild-Browser (Betrieb auf der Box)
#   desktop  GDM3, normaler Anmeldebildschirm (Entwickeln, Warten, Debuggen)
#
# Der Dienst mkphotobox.service läuft in BEIDEN Modi weiter; im Desktop-Modus
# erreichst du die Box einfach im normalen Browser unter http://localhost:8080.
#
#   sudo ./scripts/mode.sh status
#   sudo ./scripts/mode.sh desktop [--now]
#   sudo ./scripts/mode.sh kiosk   [--now]
#
# Ohne --now wird nur umgestellt und der Wechsel greift beim nächsten Neustart.
# Mit --now startet der Displaymanager sofort neu — die laufende grafische
# Sitzung stirbt dabei. Also nur per SSH oder von einer Textkonsole aus.
#
# Env:
#   KIOSK_USER=<user>   Autologin-Benutzer (Vorgabe: aus sddm.conf.d, sonst sudo-Aufrufer)
#
set -euo pipefail

MODE="${1:-status}"
NOW=0
[[ "${2:-}" == "--now" ]] && NOW=1 || true

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTOLOGIN_CONF=/etc/sddm.conf.d/autologin.conf

# Autologin-Benutzer: erst aus einer bestehenden SDDM-Konfiguration lesen, damit
# ein zweiter Aufruf denselben Benutzer trifft wie kiosk-setup.sh beim ersten.
detect_user() {
  local u=""
  [[ -f "$AUTOLOGIN_CONF" ]] && u="$(sed -n 's/^User=//p' "$AUTOLOGIN_CONF" | head -1)"
  echo "${KIOSK_USER:-${u:-${SUDO_USER:-photobooth}}}"
}
KIOSK_USER="$(detect_user)"
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6 || true)"

# Unit-Datei eines Displaymanagers auflösen (gdm heißt bei Ubuntu gdm.service,
# das Paket aber gdm3 — beide Schreibweisen zulassen).
unit_path() {
  local u
  for u in "$@"; do
    local p
    p="$(systemctl show -p FragmentPath --value "$u" 2>/dev/null || true)"
    [[ -n "$p" && -f "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

current_dm() {
  local link=/etc/systemd/system/display-manager.service
  [[ -L "$link" ]] && basename "$(readlink -f "$link")" || echo "(keiner)"
}

# ── Status ────────────────────────────────────────────────────────────────
# Braucht kein root — die Admin-Oberfläche fragt hierüber den aktuellen Modus ab.
if [[ "$MODE" == status ]]; then
  dm="$(current_dm)"
  case "$dm" in
    sddm.service)             mode=kiosk ;;
    gdm.service|gdm3.service) mode=desktop ;;
    *)                        mode=unknown ;;
  esac
  kiosk_ready=false
  unit_path sddm.service >/dev/null 2>&1 && [[ -f /usr/share/xsessions/kiosk.desktop ]] && kiosk_ready=true
  desktop_ready=false
  unit_path gdm.service gdm3.service >/dev/null 2>&1 && desktop_ready=true
  autologin=""
  for f in "$AUTOLOGIN_CONF" "$AUTOLOGIN_CONF.off"; do
    [[ -f "$f" ]] && { autologin="$(sed -n 's/^User=//p' "$f" | head -1)"; break; }
  done
  app="$(systemctl is-active mkphotobox.service 2>/dev/null || true)"
  sessions="$(ls /usr/share/xsessions/*.desktop 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ' || true)"
  dis="$(ls /usr/share/xsessions/*.desktop.disabled 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ' || true)"
  wl="$(ls /usr/share/wayland-sessions/*.desktop 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ' || true)"
  startx=unbekannt
  if [[ -n "$HOME_DIR" && -f "$HOME_DIR/.bash_profile" ]]; then
    startx="$(grep -q '^[^#]*exec startx' "$HOME_DIR/.bash_profile" && echo aktiv || echo aus)"
  fi

  if [[ "${2:-}" == --json ]]; then
    printf '{"mode":"%s","dm":"%s","kiosk_ready":%s,"desktop_ready":%s,' \
      "$mode" "$dm" "$kiosk_ready" "$desktop_ready"
    printf '"autologin_user":"%s","app_service":"%s","tty1_startx":"%s"}\n' \
      "$autologin" "$app" "$startx"
    exit 0
  fi

  echo ">>> Modus: ${mode^^}"
  echo "    Displaymanager : $dm  ($(cat /etc/X11/default-display-manager 2>/dev/null || echo '-'))"
  echo "    Autologin      : ${autologin:--}"
  echo "    Kiosk bereit   : $($kiosk_ready && echo ja || echo 'nein — erst kiosk-setup.sh laufen lassen')"
  echo "    Desktop bereit : $($desktop_ready && echo ja || echo 'nein — sudo apt install gdm3')"
  echo "    App-Dienst     : ${app:-inactive}"
  echo "    X-Sessions     : $sessions"
  [[ -n "$dis" ]] && echo "    deaktiviert    : $dis" || true
  echo "    Wayland        : $wl"
  echo "    tty1-startx    : $startx"
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

# Displaymanager setzen: Symlink und /etc/X11/default-display-manager müssen
# zusammenpassen, sonst zieht Debians Paketlogik den alten wieder hoch.
set_dm() {
  local bin="$1"; shift
  local path
  path="$(unit_path "$@")" || { echo "!! Unit nicht gefunden: $*"; exit 1; }
  ln -sf "$path" /etc/systemd/system/display-manager.service
  echo "$bin" > /etc/X11/default-display-manager
  systemctl daemon-reload
}

# ~/.bash_profile aus kiosk-setup.sh startet auf tty1 ein eigenes X. Im
# Desktop-Modus stört das (Textkonsole kippt in den Kiosk), also auskommentieren
# statt löschen — im Kiosk-Modus wieder aktivieren.
tty1_startx() {
  local want="$1" f="$HOME_DIR/.bash_profile"
  [[ -n "$HOME_DIR" && -f "$f" ]] || return 0
  if [[ "$want" == on ]]; then
    sed -i 's|^# \[mode.sh\] ||' "$f"
  else
    sed -i '/^[^#]*exec startx/s|^|# [mode.sh] |' "$f"
  fi
}

OLD_DM="$(current_dm)"

case "$MODE" in
  desktop)
    unit_path gdm.service gdm3.service >/dev/null || {
      echo "!! GDM3 ist nicht installiert:  sudo apt install gdm3"; exit 1; }
    echo ">>> Desktop-Modus (GDM3)"

    # Von kiosk-setup.sh beiseitegeschobene Sitzungen zurückholen.
    shopt -s nullglob
    for s in /usr/share/xsessions/*.desktop.disabled; do
      mv "$s" "${s%.disabled}" && echo "    reaktiviert: $(basename "${s%.disabled}")"
    done
    shopt -u nullglob

    # Autologin abschalten, aber die Datei aufheben — der Kiosk-Modus baut sie
    # sonst jedes Mal neu und vergisst dabei einen abweichenden Benutzer.
    if [[ -f "$AUTOLOGIN_CONF" ]]; then
      mv "$AUTOLOGIN_CONF" "$AUTOLOGIN_CONF.off"; echo "    Autologin aus"
    fi

    tty1_startx off
    if unit_path sddm.service >/dev/null; then
      systemctl disable sddm.service >/dev/null 2>&1 || true
    fi
    set_dm /usr/sbin/gdm3 gdm.service gdm3.service
    systemctl enable gdm.service >/dev/null 2>&1 || systemctl enable gdm3.service >/dev/null 2>&1 || true
    ;;

  kiosk)
    unit_path sddm.service >/dev/null || {
      echo "!! SDDM ist nicht installiert. Einmalig einrichten mit:"
      echo "     sudo $APP_DIR/scripts/kiosk-setup.sh"; exit 1; }
    [[ -f /usr/share/xsessions/kiosk.desktop ]] || {
      echo "!! /usr/share/xsessions/kiosk.desktop fehlt. Einmalig einrichten mit:"
      echo "     sudo $APP_DIR/scripts/kiosk-setup.sh"; exit 1; }
    echo ">>> Kiosk-Modus (SDDM, Autologin als $KIOSK_USER)"

    mkdir -p /etc/sddm.conf.d
    if [[ -f "$AUTOLOGIN_CONF.off" ]]; then
      mv "$AUTOLOGIN_CONF.off" "$AUTOLOGIN_CONF"
    else
      cat > "$AUTOLOGIN_CONF" <<SD
[Autologin]
User=$KIOSK_USER
Session=kiosk
Relogin=true
SD
    fi
    rm -f /var/lib/sddm/state.conf   # gemerkte letzte Sitzung verwerfen

    # Andere X-Sessions aus dem Weg räumen (wie kiosk-setup.sh). Die
    # Wayland-Sitzungen bleiben unangetastet — der Autologin greift ohnehin.
    shopt -s nullglob
    for s in /usr/share/xsessions/*.desktop; do
      [[ "$(basename "$s")" == kiosk.desktop ]] && continue
      mv "$s" "$s.disabled" && echo "    deaktiviert: $(basename "$s")"
    done
    shopt -u nullglob

    tty1_startx on
    if unit_path gdm.service gdm3.service >/dev/null; then
      systemctl disable gdm.service >/dev/null 2>&1 || systemctl disable gdm3.service >/dev/null 2>&1 || true
    fi
    set_dm /usr/bin/sddm sddm.service
    systemctl enable sddm.service >/dev/null 2>&1 || true
    ;;

  *)
    echo "Aufruf: sudo $0 {status|desktop|kiosk} [--now]"; exit 2 ;;
esac

NEW_DM="$(current_dm)"
echo "    Displaymanager: $OLD_DM -> $NEW_DM"

if [[ $NOW -eq 1 ]]; then
  echo ">>> Wechsel sofort — die laufende grafische Sitzung wird beendet."
  [[ "$OLD_DM" != "$NEW_DM" && "$OLD_DM" != "(keiner)" ]] && systemctl stop "$OLD_DM" || true
  systemctl restart display-manager.service
else
  echo ">>> Aktiv beim nächsten Neustart (oder jetzt: sudo $0 $MODE --now)"
fi
