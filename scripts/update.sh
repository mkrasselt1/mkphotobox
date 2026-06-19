#!/usr/bin/env bash
#
# MKPhotobox update — pulls the latest code from git, refreshes deps and
# restarts the service. The schema auto-migrates on startup (see database.py).
# First run adopts an existing (tarball-deployed) directory as a git checkout.
#
#   sudo ./scripts/update.sh
#
# Env: REPO=<git url>  BRANCH=main  RUN_USER=<user>
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(stat -c %U "$APP_DIR")}}"
REPO="${REPO:-https://github.com/mkrasselt1/mkphotobox.git}"
BRANCH="${BRANCH:-main}"
PIP="$APP_DIR/.venv/bin/pip"
RUN() { sudo -u "$RUN_USER" "$@"; }

[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }
cd "$APP_DIR"

echo ">>> Code aktualisieren ($REPO @ $BRANCH)"
if [ ! -d .git ]; then
  echo "   (kein git-Repo — Verzeichnis wird als Clone übernommen)"
  RUN git init -q
  RUN git remote add origin "$REPO" 2>/dev/null || RUN git remote set-url origin "$REPO"
fi
RUN git fetch --depth=1 origin "$BRANCH"
# config.yaml, data/, .venv sind gitignored -> bleiben erhalten
RUN git reset --hard "origin/$BRANCH"

echo ">>> Abhängigkeiten aktualisieren"
RUN "$PIP" install -e . -q
RUN "$PIP" install "fastapi==0.135.3" "starlette==1.0.0" -q   # Pin beibehalten

echo ">>> Neustart (Schema-Migration läuft automatisch beim Start)"
find "$APP_DIR/app" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
systemctl restart mkphotobox.service
sleep 5
if systemctl is-active --quiet mkphotobox.service; then
  echo "OK — aktiv: http://$(hostname -I | awk '{print $1}'):8080"
else
  echo "!! Dienst nicht aktiv:"; journalctl -u mkphotobox.service -n 20 --no-pager
fi
echo ">>> Stand: $(git -C "$APP_DIR" log --oneline -1)"
