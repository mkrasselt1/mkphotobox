#!/usr/bin/env bash
#
# Install nice script/handwriting fonts for text elements in photo templates.
# Downloads free OFL fonts from the Google Fonts repository into the bundled
# font directory (app/assets/fonts/), which collage_service picks up first.
#
#   ./scripts/install-fonts.sh
#
# Idempotent: skips fonts that are already present. Needs internet.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$APP_DIR/app/assets/fonts"
mkdir -p "$DEST"

BASE="https://github.com/google/fonts/raw/main"

# label|relative-url (license dir included)|target-filename
FONTS=(
  "Pacifico|ofl/pacifico/Pacifico-Regular.ttf|Pacifico-Regular.ttf"
  "Great Vibes|ofl/greatvibes/GreatVibes-Regular.ttf|GreatVibes-Regular.ttf"
  "Lobster|ofl/lobster/Lobster-Regular.ttf|Lobster-Regular.ttf"
  "Sacramento|ofl/sacramento/Sacramento-Regular.ttf|Sacramento-Regular.ttf"
  "Satisfy|apache/satisfy/Satisfy-Regular.ttf|Satisfy-Regular.ttf"
  "Parisienne|ofl/parisienne/Parisienne-Regular.ttf|Parisienne-Regular.ttf"
  "Dancing Script|ofl/dancingscript/DancingScript%5Bwght%5D.ttf|DancingScript[wght].ttf"
  "Comic Neue|ofl/comicneue/ComicNeue-Regular.ttf|ComicNeue-Regular.ttf"
  "Comic Neue Bold|ofl/comicneue/ComicNeue-Bold.ttf|ComicNeue-Bold.ttf"
)

echo ">>> Installing template fonts into $DEST"
ok=0; skip=0; fail=0
for entry in "${FONTS[@]}"; do
  IFS='|' read -r label url fname <<< "$entry"
  out="$DEST/$fname"
  if [[ -f "$out" ]]; then
    echo "  = $label (bereits vorhanden)"; skip=$((skip+1)); continue
  fi
  if curl -fsSL "$BASE/$url" -o "$out" 2>/dev/null && [[ -s "$out" ]]; then
    echo "  + $label"; ok=$((ok+1))
  else
    rm -f "$out"; echo "  ! $label fehlgeschlagen"; fail=$((fail+1))
  fi
done

echo ">>> Fonts: $ok neu, $skip vorhanden, $fail fehlgeschlagen"
echo "    (Eigene .ttf einfach nach $DEST legen und in collage_service.FONT_FILES eintragen.)"
