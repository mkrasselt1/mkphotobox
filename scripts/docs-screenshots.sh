#!/usr/bin/env bash
#
# Erneuert die Screenshots in docs/media/ (README und docs/INSTALLATION.md).
#
#   ./scripts/docs-screenshots.sh            alle Bilder neu
#   ./scripts/docs-screenshots.sh admin      nur einzelne Phasen (seed booth admin gallery);
#                                            ohne „seed“ bleibt die Datenbank vom letzten Lauf
#
# Braucht nur Docker (und einmal Internet für Images, pip-Pakete und die
# Schrift Inter). Das data/ und die config.yaml im Repository werden NICHT
# angefasst: Die App läuft auf einer Kopie des Arbeitsverzeichnisses mit eigener,
# frischer Datenbank in $WORK (Vorgabe: /tmp/mkphotobox-docs).
#
# Ablauf:
#   1. Kopie des Repos nach $WORK/app, eigene config.yaml (Browser-Kamera)
#   2. App im Container python:3.12-slim starten, Demo-Vorlagen „Party“ eintragen
#      (scripts/install-demo-template.py)
#   3. scripts/docs-screenshots.js im Container zenika/alpine-chrome:with-puppeteer:
#      Veranstaltung + Fotos anlegen (Demo-Bilder aus docs/media/demo), dann
#      Booth, Admin und Galerie fotografieren — 1440×900 bei doppelter
#      Pixeldichte, also 2880×1800 wie bisher. Die Kamera ist Chromiums
#      Test-Kamera, gefüttert mit docs/media/demo/demo1.jpg.
#   4. PNGs mit pngquant verkleinern und nach docs/media/ kopieren
#   5. Container wieder entfernen ($WORK bleibt für einen zweiten Lauf liegen;
#      KEEP=1 lässt auch die App laufen)
#
# Danach jedes Bild ansehen, bevor es committet wird.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${WORK:-/tmp/mkphotobox-docs}"
NET=pbdocs
APP=pbdocs-app
PY_IMAGE=python:3.12-slim
CHROME_IMAGE=zenika/alpine-chrome:with-puppeteer

mkdir -p "$WORK"/{out,fonts,work}

cleanup() {
  [[ "${KEEP:-0}" == 1 ]] || docker rm -f "$APP" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo ">>> Repo-Kopie nach $WORK/app (ohne data/, .venv, .git)"
rsync -a --delete --exclude .git --exclude .venv --exclude data --exclude config.yaml \
  --exclude __pycache__ --exclude .claude "$REPO/" "$WORK/app/"
# Frische Datenbank, außer es laufen nur einzelne Phasen ohne „seed“
if [[ $# -eq 0 || " $* " == *" seed "* ]]; then
  # gehört root (vom App-Container angelegt) — also auch im Container löschen
  docker run --rm -v "$WORK/app:/app" "$PY_IMAGE" rm -rf /app/data
fi
cat > "$WORK/app/config.yaml" <<'EOF'
setup:
  completed: true
i18n:
  default_locale: de
auth:
  secret_key: "docs-screenshots-only"
cameras:
  webrtc:
    enabled: true
EOF

if [[ ! -s "$WORK/fonts/Inter.ttf" ]]; then
  echo ">>> Schrift Inter laden (wie auf Rechnern, die sie installiert haben)"
  curl -fsSL -o "$WORK/fonts/Inter.ttf" \
    'https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf' \
    || echo "!! Inter nicht geladen — Chromium nimmt dann eine Ersatzschrift"
fi

echo ">>> App starten"
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$APP" >/dev/null 2>&1 || true
docker run -d --name "$APP" --network "$NET" -v "$WORK/app:/app" -w /app "$PY_IMAGE" sh -c \
  "pip install -q --root-user-action=ignore /app 'fastapi==0.135.3' 'starlette==1.0.0' numpy opencv-python-headless \
   && touch /tmp/ready && python -m uvicorn app.main:app --host 0.0.0.0 --port 8080" >/dev/null
for i in $(seq 1 120); do
  docker exec "$APP" python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/api/v1/events/active',timeout=2)" \
    >/dev/null 2>&1 && break
  sleep 2
  [[ $i == 120 ]] && { docker logs --tail 30 "$APP"; echo "!! App startet nicht"; exit 1; }
done

echo ">>> Demo-Vorlagen und Kamera-Bild"
docker exec "$APP" python scripts/install-demo-template.py
docker exec -i "$APP" python - /app/docs/media/demo/demo1.jpg /tmp/cam.y4m <<'EOF'
# Chromiums Test-Kamera liest .y4m (rohes YUV 4:2:0) — ein Standbild genügt.
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("YCbCr")
w, h = (d - d % 2 for d in im.size)
y, cb, cr = im.crop((0, 0, w, h)).split()
frame = y.tobytes() + cb.resize((w // 2, h // 2)).tobytes() + cr.resize((w // 2, h // 2)).tobytes()
with open(sys.argv[2], "wb") as f:
    f.write(f"YUV4MPEG2 W{w} H{h} F10:1 Ip A1:1 C420jpeg\n".encode())
    for _ in range(5):
        f.write(b"FRAME\n" + frame)
EOF
docker cp "$APP:/tmp/cam.y4m" "$WORK/work/cam.y4m"

echo ">>> Screenshots"
rm -f "$WORK"/out/*.png
docker run --rm --network "$NET" \
  -v "$WORK/work:/work:ro" -v "$WORK/out:/out" -v "$WORK/fonts:/home/chrome/.fonts:ro" \
  -v "$REPO/docs/media/demo:/demo:ro" -v "$REPO/scripts:/scripts:ro" \
  -e NODE_PATH=/usr/src/app/node_modules -e BASE="http://$APP:8080" \
  --entrypoint node "$CHROME_IMAGE" /scripts/docs-screenshots.js "$@"

echo ">>> Verkleinern und nach docs/media/ kopieren"
docker exec "$APP" rm -rf /tmp/shots
docker cp "$WORK/out" "$APP:/tmp/shots"
docker exec "$APP" sh -c 'command -v pngquant >/dev/null || \
  (export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq pngquant >/dev/null)'
docker exec "$APP" sh -c 'cd /tmp/shots && for f in *.png; do
  pngquant --force --skip-if-larger --quality 70-95 --speed 1 --output "$f" -- "$f" || true
  echo "  $f: $(( $(stat -c %s "$f") / 1024 )) KB"; done'
docker cp "$APP:/tmp/shots/." "$REPO/docs/media/"
echo ">>> Fertig: $(ls "$WORK"/out/*.png | wc -l) Bilder in docs/media/"
