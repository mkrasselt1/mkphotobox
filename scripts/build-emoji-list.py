#!/usr/bin/env python3
"""Erzeugt frontend/src/core/emoji-list.json — die Emoji-Liste für den Picker.

Entwicklerwerkzeug, läuft NICHT auf der Box. Die fertige JSON-Datei liegt im
Repo, damit der Picker auch offline und ohne diesen Schritt funktioniert.

Quellen (vorher von Hand herunterladen und entpacken):
  * emojibase-data (MIT, Namen/Schlagwörter aus Unicode CLDR):
      https://registry.npmjs.org/emojibase-data/-/emojibase-data-<ver>.tgz
      -> package/de/compact.json, package/de/messages.json, package/en/compact.json
  * Twemoji-SVGs (Grafiken CC-BY 4.0), dieselbe Version wie in
    scripts/install-emoji.sh:
      https://codeload.github.com/jdecked/twemoji/tar.gz/refs/tags/v<ver>
      -> twemoji-<ver>/assets/svg

Aufnehmen werden nur Emojis, für die es ein Twemoji-SVG gibt — sonst könnte der
Server ein im Picker angebotenes Emoji nicht hochauflösend rendern.

  python3 scripts/build-emoji-list.py <emojibase/package> <twemoji/assets/svg>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "src" / "core" / "emoji-list.json"

# Symbol je Kategorie (Reiter im Picker). Gruppe 2 = Hautfarben-Bausteine — kein
# eigenständiges Emoji, wird ausgelassen.
GROUP_ICONS = {0: "😀", 1: "👋", 3: "🐶", 4: "🍕", 5: "✈️", 6: "⚽", 7: "💡", 8: "❤️", 9: "🏁"}

# Vorne im Picker: was auf Fotobox-Bildern am häufigsten gebraucht wird.
FAVORITES = (
    "🎉 🥳 🎊 🎈 🎂 🍾 🥂 🍻 💍 👰 🤵 💒 ❤️ 💕 💖 😍 😘 💋 😎 🤪 😂 🤣 😜 🤩 "
    "👑 🦄 🌈 ⭐ ✨ 🔥 💯 🤘 ✌️ 👍 🙌 🕺 💃 🎵 🎶 📸 🌹 🌸 🌻 🍀 🐶 🐱 🦊 🐼 🦋 "
    "👻 🎃 🎄 🎅 🎁 🍕 🍔 🍦 🍓 🍉 🍹 ☀️ 🌙 🚀 🏆 🥇 ⚽ 💩 😈 🤡 👽 🤖 💀 🙈"
).split()


def twemoji_name(emoji: str) -> str:
    """Dateiname nach Twemoji-Regel: FE0F fällt weg, außer in ZWJ-Sequenzen."""
    if "‍" not in emoji:
        emoji = emoji.replace("️", "")
    return "-".join(f"{ord(c):x}" for c in emoji)


def main(base: Path, svg_dir: Path) -> None:
    de = json.loads((base / "de" / "compact.json").read_text(encoding="utf-8"))
    en = {e["hexcode"]: e.get("label", "")
          for e in json.loads((base / "en" / "compact.json").read_text(encoding="utf-8"))}
    messages = json.loads((base / "de" / "messages.json").read_text(encoding="utf-8"))
    group_names = {g["order"]: g["message"] for g in messages["groups"]}
    svgs = {p.stem for p in svg_dir.glob("*.svg")}

    entries = []
    missing = 0
    for e in sorted(de, key=lambda x: x.get("order", 1 << 30)):
        g = e.get("group")
        if g is None or g not in GROUP_ICONS:
            continue
        if twemoji_name(e["unicode"]) not in svgs:
            missing += 1
            continue
        words = {w for w in [en.get(e["hexcode"], "")] + list(e.get("tags", [])) if w}
        words.discard(e["label"])
        entries.append([e["unicode"], e["label"], " ".join(sorted(words)), g])

    known = {x[0] for x in entries}
    favorites = [f for f in FAVORITES if f in known]
    out = {
        "source": "emojibase-data (MIT, CLDR) + Twemoji (CC-BY 4.0)",
        "groups": [{"id": g, "name": group_names.get(g, str(g)), "icon": icon}
                   for g, icon in GROUP_ICONS.items()],
        "favorites": favorites,
        # [emoji, deutscher Name, Suchwörter (dt. Schlagwörter + engl. Name), Gruppe]
        "emojis": entries,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(entries)} Emojis, {len(favorites)} Favoriten, {missing} ohne SVG übersprungen "
          f"-> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
