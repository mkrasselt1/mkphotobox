#!/usr/bin/env bash
#
# Lädt die Twemoji-Vektorgrafiken (SVG) für Emoji-Sticker auf Fotos und Vorlagen
# nach app/assets/emoji/svg/. Der Server rendert daraus jedes Emoji in genau der
# Größe, die der Druck braucht — scharf auch bei 300 dpi.
#
#   ./scripts/install-emoji.sh
#
# Idempotent: steht die gewünschte Version schon da, passiert nichts.
# Braucht einmal Internet (ca. 6 MB Download, ca. 10 MB entpackt).
#
# Grafiken: Twemoji, © Twitter, Inc. und weitere Mitwirkende,
# Lizenz CC-BY 4.0 — https://creativecommons.org/licenses/by/4.0/
# (Attribution steht in app/assets/emoji/README.md und im Admin-Bereich.)
set -euo pipefail

VERSION="17.0.3"   # passend zu frontend/src/core/emoji-list.json (scripts/build-emoji-list.py)
URL="https://codeload.github.com/jdecked/twemoji/tar.gz/refs/tags/v$VERSION"

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$APP_DIR/app/assets/emoji"
MARK="$DEST/svg/.version"

if [[ -f "$MARK" && "$(cat "$MARK")" == "$VERSION" ]]; then
  echo ">>> Emoji-Grafiken (Twemoji $VERSION) bereits vorhanden"; exit 0
fi

echo ">>> Lade Emoji-Grafiken (Twemoji $VERSION)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 5 --retry-delay 3 -m 300 "$URL" -o "$TMP/twemoji.tgz"
# Nur die SVGs und die Lizenz auspacken — der Rest des Repos wird nicht gebraucht.
tar -xzf "$TMP/twemoji.tgz" -C "$TMP" --wildcards \
  "twemoji-$VERSION/assets/svg/*.svg" "twemoji-$VERSION/LICENSE-GRAPHICS"

count="$(find "$TMP/twemoji-$VERSION/assets/svg" -name '*.svg' | wc -l)"
if [[ "$count" -lt 1000 ]]; then
  echo "!! Nur $count SVGs im Archiv — Abbruch, vorhandene Grafiken bleiben."; exit 1
fi

mkdir -p "$DEST"
rm -rf "$DEST/svg.new"
mv "$TMP/twemoji-$VERSION/assets/svg" "$DEST/svg.new"
cp "$TMP/twemoji-$VERSION/LICENSE-GRAPHICS" "$DEST/svg.new/LICENSE-GRAPHICS"
echo "$VERSION" > "$DEST/svg.new/.version"
rm -rf "$DEST/svg"
mv "$DEST/svg.new" "$DEST/svg"

echo ">>> Emoji: $count Grafiken in $DEST/svg"
