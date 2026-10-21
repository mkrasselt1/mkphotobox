#!/bin/sh
# MKPhotobox Lüftersteuerung — für jeden Chip unter /sys/class/hwmon.
#
#   mkphotobox-fan list                       Kanäle als Zeilen: chip kanal pwm enable rpm
#   mkphotobox-fan set <chip> <kanal> <0..255>  fester Wert (manuell)
#   mkphotobox-fan set <chip> <kanal> auto      zurück zur Regelung des Chips
#   mkphotobox-fan apply                      gespeicherte Werte setzen (beim Booten)
#
# Gespeichert in /etc/mkphotobox/fans.conf, eine Zeile pro Kanal:
#   <chip> <kanal> <wert|auto> <ursprünglicher pwmN_enable>
# Der ursprüngliche enable-Wert wird beim ersten manuellen Setzen gemerkt —
# "auto" heißt je nach Treiber 2 (it87), 5 (nct6775) oder anderes, also stellt
# "auto" genau den Zustand wieder her, den der Chip vorher hatte.
#
# Chips werden über ihren Namen gesucht: die hwmon-Nummern (hwmon0, hwmon3 …)
# vergibt der Kernel bei jedem Boot neu.
#
# Läuft als root-eigene Kopie unter /usr/local/sbin (setup.sh); die Oberfläche
# ruft sie über eine sudoers-Regel auf. Darum werden alle Argumente streng
# geprüft — sie landen als Pfadteile in /sys.
set -eu

CONF=/etc/mkphotobox/fans.conf

die() { echo "$*" >&2; exit 1; }

hwmon_of() {  # Chipname -> hwmon-Verzeichnis
  for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = "$1" ] && { echo "$h"; return 0; }
  done
  return 1
}

check_args() {  # chip kanal wert
  case "$1" in *[!A-Za-z0-9_.-]*|"") die "ungültiger Chipname: $1" ;; esac
  case "$2" in *[!0-9]*|"") die "ungültiger Kanal: $2" ;; esac
  case "$3" in
    auto) ;;
    *[!0-9]*|"") die "Wert muss 0..255 oder auto sein: $3" ;;
    *) [ "$3" -le 255 ] || die "Wert muss 0..255 sein: $3" ;;
  esac
}

write_pwm() {  # chip kanal wert orig_enable
  h="$(hwmon_of "$1")" || die "Chip $1 nicht gefunden"
  [ -e "$h/pwm$2" ] || die "$1 hat keinen Kanal pwm$2"
  if [ "$3" = auto ]; then
    echo "$4" > "$h/pwm$2_enable"
  else
    echo 1 > "$h/pwm$2_enable"
    echo "$3" > "$h/pwm$2"
  fi
}

case "${1:-}" in
  list)
    for h in /sys/class/hwmon/hwmon*; do
      name="$(cat "$h/name" 2>/dev/null)" || continue
      for p in "$h"/pwm[0-9]*; do
        case "$p" in *_*) continue ;; esac
        [ -e "$p" ] || continue
        n="${p##*/pwm}"
        rpm=-; [ -r "$h/fan${n}_input" ] && rpm="$(cat "$h/fan${n}_input")"
        echo "$name $n $(cat "$p") $(cat "$h/pwm${n}_enable" 2>/dev/null || echo -) $rpm"
      done
    done
    ;;

  set)
    [ "$(id -u)" -eq 0 ] || die "nur als root"
    [ $# -eq 4 ] || die "Aufruf: $0 set <chip> <kanal> <0..255|auto>"
    check_args "$2" "$3" "$4"
    h="$(hwmon_of "$2")" || die "Chip $2 nicht gefunden"
    [ -e "$h/pwm$3_enable" ] || die "$2 hat keinen steuerbaren Kanal pwm$3"
    mkdir -p "${CONF%/*}"; touch "$CONF"
    orig="$(awk -v c="$2" -v k="$3" '$1==c && $2==k {print $4}' "$CONF")"
    [ -n "$orig" ] || orig="$(cat "$h/pwm$3_enable")"
    write_pwm "$2" "$3" "$4" "$orig"
    tmp="$(mktemp)"
    awk -v c="$2" -v k="$3" '!($1==c && $2==k)' "$CONF" > "$tmp"
    # "auto" bleibt gespeichert, solange der Kanal einmal angefasst wurde —
    # so überlebt auch der Rückweg zur Chip-Regelung einen Neustart.
    echo "$2 $3 $4 $orig" >> "$tmp"
    install -m 644 "$tmp" "$CONF"; rm -f "$tmp"
    ;;

  apply)
    [ -r "$CONF" ] || exit 0
    # Das Treibermodul lädt beim Booten evtl. erst nach diesem Dienst.
    rc=0
    while read -r chip ch val orig; do
      case "$chip" in ''|\#*) continue ;; esac
      # Subshells: ein kaputter Eintrag soll die übrigen nicht verhindern.
      ( check_args "$chip" "$ch" "$val" ) || { rc=1; continue; }
      i=0
      until hwmon_of "$chip" >/dev/null; do
        i=$((i + 1)); [ $i -le 10 ] || break; sleep 1
      done
      ( write_pwm "$chip" "$ch" "$val" "$orig" ) || rc=1
    done < "$CONF"
    exit $rc
    ;;

  *)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
