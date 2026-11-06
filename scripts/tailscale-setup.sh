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
#   UP=1                   gleich 'tailscale up' (Anmeldung). UP=0 installiert
#                          nur — so ruft setup.sh das Skript auf; angemeldet
#                          wird später im Admin-Bereich (Netzwerk → Verbinden).
#   OPERATOR=<user>        diesen Benutzer zum Tailscale-Operator machen: er
#                          darf dann 'tailscale up/down/logout' ohne sudo (die
#                          App steuert Tailscale so). setup.sh setzt $RUN_USER.
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

TS_HOSTNAME="${TS_HOSTNAME:-mkphotobox}"
TS_SSH="${TS_SSH:-1}"
UP="${UP:-1}"
OPERATOR="${OPERATOR:-}"

# ── install ───────────────────────────────────────────────────────────────
# install.sh richtet das Paketquellen-Repo von Tailscale ein und installiert
# per apt. Ohne Internet schlägt das fehl — dann sauber mit Fehlercode raus
# (setup.sh fängt das ab und läuft weiter; ein späterer Lauf holt es nach).
if ! command -v tailscale >/dev/null; then
  echo ">>> Tailscale installieren"
  if ! curl -fsSL --connect-timeout 15 https://tailscale.com/install.sh | sh; then
    echo "!! Tailscale-Installation fehlgeschlagen (kein Internet?)"
    exit 1
  fi
fi
systemctl enable --now tailscaled

# ── operator ──────────────────────────────────────────────────────────────
# Ausprobiert (tailscale 1.104): als Operator gehen 'tailscale up --ssh',
# 'down' und 'logout' ohne root; ohne kommt "prefs write access denied".
# Die App ruft 'tailscale up --reset --operator=<sich selbst>' auf, damit der
# Operator beim Verbinden nicht wieder zurückgesetzt wird.
if [[ -n "$OPERATOR" ]]; then
  # tailscaled braucht nach dem Start einen Moment, bis sein Socket da ist
  OP_OK=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if tailscale set --operator="$OPERATOR" 2>/dev/null; then OP_OK=1; break; fi
    sleep 1
  done
  if [[ "$OP_OK" == 1 ]]; then
    echo "    Operator: $OPERATOR (darf Tailscale ohne sudo steuern)"
  else
    echo "!! Konnte $OPERATOR nicht zum Tailscale-Operator machen — 'Verbinden' im Admin-Bereich geht dann nicht"
  fi
fi

if [[ "$UP" != 1 ]]; then
  echo ">>> Tailscale installiert — anmelden im Admin-Bereich unter Netzwerk → Verbinden"
  exit 0
fi

# ── bring up ──────────────────────────────────────────────────────────────
UP_ARGS=(--hostname="$TS_HOSTNAME")
[[ "$TS_SSH" == 1 ]] && UP_ARGS+=(--ssh)
# 'tailscale up' verlangt, dass alle schon gesetzten Einstellungen erneut
# genannt werden — sonst bricht es ab. Der Operator ist so eine.
[[ -n "$OPERATOR" ]] && UP_ARGS+=(--operator="$OPERATOR")

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
