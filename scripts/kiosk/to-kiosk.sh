#!/bin/sh
# Verknüpfung "Fotobox-Modus" im Desktop-Modus: schaltet auf Kiosk und startet
# neu. Braucht kein Passwort — beides erlaubt die sudoers-Regel aus setup.sh
# (mkphotobox-mode kiosk, systemctl reboot). Bewusst ein Neustart statt
# 'mode kiosk --now': '--now' bleibt der Konsole vorbehalten, und ein sauberer
# Boot ist ohnehin der Weg, auf dem die Box bei der Veranstaltung hochkommt.

say() {
  if command -v zenity >/dev/null 2>&1; then zenity "$@" 2>/dev/null; else return 0; fi
}

say --question --title="Fotobox-Modus" --ok-label="Umschalten" --cancel-label="Abbrechen" \
  --text="Auf den Fotobox-Modus umschalten?\n\nDie Box startet dafür neu." || exit 0

if ! out="$(sudo -n /usr/local/sbin/mkphotobox-mode kiosk 2>&1)"; then
  msg="Umschalten fehlgeschlagen:\n\n$out\n\nFehlt die sudoers-Regel? Einmal 'sudo ./scripts/setup.sh' ausführen."
  say --error --title="Fotobox-Modus" --text="$msg" || true
  printf '%b\n' "$msg" >&2
  exit 1
fi

sudo -n /usr/bin/systemctl reboot
