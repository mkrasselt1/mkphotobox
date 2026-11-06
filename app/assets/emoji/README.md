# Emoji-Grafiken

Emoji-Sticker (Vorlagen-Editor und Gästebuch auf dem Foto) werden serverseitig
aus **Vektorgrafiken** gerendert — in genau der Pixelgröße, die das Bild braucht.
Damit bleibt ein Emoji auch auf einem 300-dpi-Druck scharf (ein System-Emoji-Font
wie Noto Color Emoji ist nur ein 136-px-Bitmap).

## Installation

```bash
./scripts/install-emoji.sh
```

lädt die Twemoji-SVGs (ca. 6 MB) nach `svg/` (nicht im Git). Gerendert wird mit
dem Python-Paket `resvg-py` (fertige Wheels für aarch64/armv7/x86_64, keine
System-Bibliotheken nötig).

Fehlen die SVGs oder `resvg-py`, fällt der Server auf einen installierten
Farb-Emoji-Font zurück (grob, aber besser als nichts); der Vorlagen-Editor zeigt
dann einen Hinweis.

## Emoji-Liste

`frontend/src/core/emoji-list.json` (im Repo) enthält Namen, Suchwörter und
Kategorien. Sie wird mit `scripts/build-emoji-list.py` aus emojibase-data und dem
SVG-Ordner erzeugt — bei einem Twemoji-Update beides zusammen anheben
(`VERSION` in `scripts/install-emoji.sh`).

## Lizenzen

* **Grafiken:** Twemoji — Copyright 2019 Twitter, Inc. and other contributors,
  Copyright 2024 jdecked and other contributors.
  Lizenz [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/),
  Quelle <https://github.com/jdecked/twemoji>. Die Grafiken werden beim Rendern
  skaliert und gedreht, sonst nicht verändert.
* **Namen/Schlagwörter:** [emojibase-data](https://github.com/milesj/emojibase)
  (MIT), basierend auf Unicode CLDR (Unicode License v3).
