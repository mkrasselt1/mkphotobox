#!/usr/bin/env python3
"""Installiert die Demo-Vorlagen „Party / Geburtstag“ auf einer Box.

    cd ~/mkphotobox && .venv/bin/python scripts/install-demo-template.py [--reset]

Läuft als Dienstbenutzer direkt gegen Datenbank und Datenablage der App (kein
HTTP, kein Admin-Passwort). Die Rahmen-PNGs und Vorlagen-Beschreibungen kommen
aus ``app/assets/demo/`` (erzeugt von ``scripts/make-demo-frame.py``).

Pro Vorlage:

1. Rahmen-Asset (Typ „frame“) anlegen — genau wie ein Import über die
   Oberfläche: Datei in den Import-Ordner legen, ``asset_service.import_files``
   kopiert sie nach ``data/assets/frame/``, erzeugt das Vorschaubild und den
   DB-Eintrag. Existiert das Asset schon, wird nur die Datei aktualisiert, falls
   sich die Grafik geändert hat.
2. Vorlage mit Foto-Slot(s), Rahmen und Text-Elementen anlegen. Existiert sie
   schon (gleicher Name), bleibt sie unverändert — im Editor angepasste Texte
   gehen nicht verloren. ``--reset`` setzt sie auf den Auslieferungszustand zurück.
3. Gibt es ein Druck-Format (Output-Preset) mit passender Pixelgröße, wird die
   Vorlage damit verknüpft (Druck geht dann an dessen Drucker/Papier).
4. Hat die aktive Veranstaltung eine feste Vorlagen-Auswahl, wird die Vorlage
   dort ergänzt. Ohne Auswahl zeigt die Booth ohnehin alle Vorlagen.
5. Vorschaubild rendern (wie nach dem Speichern im Editor).

Ein zweiter Lauf legt nichts doppelt an.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)                    # Konfig-Pfade (data/…) sind relativ zum App-Verzeichnis
sys.path.insert(0, str(ROOT))

DEMO_DIR = ROOT / "app" / "assets" / "demo"
MANIFEST = DEMO_DIR / "party.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reset", action="store_true",
                    help="bestehende Demo-Vorlagen auf den Auslieferungszustand zurücksetzen")
    args = ap.parse_args()

    from sqlmodel import Session, select

    from app.config import apply_db_settings, load_config
    from app.database import create_db, get_engine
    from app.models import Asset, Event, OutputPreset, Template
    from app.services import asset_service, template_preview
    from app.api.templates import _shot_count

    if not MANIFEST.exists():
        print(f"FEHLER: {MANIFEST} fehlt — erst scripts/make-demo-frame.py ausführen.")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    cfg = load_config()
    create_db()                    # legt fehlende Tabellen/Spalten an (wie beim App-Start)
    engine = get_engine()
    with Session(engine) as session:
        apply_db_settings(session)  # z. B. abweichender Foto-Speicherort aus dem Admin-Bereich
    assets_root = Path(cfg["photos"]["storage_path"]).parent / "assets"

    today = date.today().strftime("%d.%m.%Y")
    installed: list[int] = []

    for spec in manifest["templates"]:
        png = DEMO_DIR / spec["file"]
        if not png.exists():
            print(f"FEHLER: {png} fehlt.")
            return 1
        print(f"\n▸ {spec['name']}")

        # ── 1) Rahmen-Asset ──────────────────────────────────────────────
        with Session(engine) as session:
            asset = session.exec(select(Asset).where(Asset.type == "frame",
                                                     Asset.name == spec["asset_name"])).first()
            asset_id = asset.id if asset else None
            asset_file = (assets_root / asset.filename) if asset else None

        if asset_id is not None and asset_file is not None and asset_file.exists():
            if asset_file.read_bytes() != png.read_bytes():
                shutil.copyfile(png, asset_file)
                asset_service._make_thumbnail(asset_file, assets_root / "frame" / "thumbs"
                                              / f"{asset_file.stem}.jpg")
                print(f"  Rahmen aktualisiert (Asset #{asset_id})")
            else:
                print(f"  Rahmen vorhanden (Asset #{asset_id})")
        else:
            if asset_id is not None:       # DB-Eintrag ohne Datei → sauber neu anlegen
                asset_service.delete_asset(asset_id)
            staged_dir = asset_service._imports_root() / "demo-vorlagen"
            staged_dir.mkdir(parents=True, exist_ok=True)
            staged = staged_dir / f"{spec['asset_name']}.png"
            shutil.copyfile(png, staged)
            try:
                created = asset_service.import_files("frame", [str(staged)])
            finally:
                staged.unlink(missing_ok=True)
                try:
                    staged_dir.rmdir()
                except OSError:
                    pass
            if not created:
                print("FEHLER: Rahmen-Import fehlgeschlagen.")
                return 1
            asset_id = created[0]["id"]
            with Session(engine) as session:   # Name fest, auch wenn die Datei _1 heißt
                a = session.get(Asset, asset_id)
                a.name = spec["asset_name"]
                a.source = f"app/assets/demo/{spec['file']}"
                session.add(a)
                session.commit()
            print(f"  Rahmen importiert (Asset #{asset_id})")

        # ── 2) Vorlage ───────────────────────────────────────────────────
        definition = json.loads(json.dumps(spec["definition"]).replace("{DATUM}", today))
        with Session(engine) as session:
            t = session.exec(select(Template).where(Template.name == spec["name"])).first()
            is_new = t is None
            if is_new or args.reset:
                if is_new:
                    t = Template(name=spec["name"])
                t.mode = spec.get("mode", "free")
                t.canvas_width = spec["canvas_width"]
                t.canvas_height = spec["canvas_height"]
                t.overlay_asset_id = asset_id
                t.background_asset_id = None
                t.definition_json = json.dumps(definition)
                t.photo_count = _shot_count(definition["slots"])

                # ── 3) passendes Druck-Format verknüpfen ────────────────
                presets = session.exec(select(OutputPreset).where(
                    OutputPreset.kind == "print",
                    OutputPreset.width_px == spec["canvas_width"],
                    OutputPreset.height_px == spec["canvas_height"])).all()
                if presets:
                    t.preset_id = presets[0].id
                    print(f"  mit Druck-Format „{presets[0].name}“ verknüpft")
                elif is_new:
                    print(f"  kein Druck-Format mit {spec['canvas_width']}×{spec['canvas_height']} px "
                          "gefunden — Vorlage ohne Format-Verknüpfung (im Editor nachholbar)")
                session.add(t)
                session.commit()
                session.refresh(t)
                print(f"  Vorlage {'angelegt' if is_new else 'zurückgesetzt'} (#{t.id})")
            else:
                if t.overlay_asset_id != asset_id:
                    t.overlay_asset_id = asset_id
                    session.add(t)
                    session.commit()
                    session.refresh(t)
                    print(f"  Vorlage vorhanden (#{t.id}) — Rahmen wieder verknüpft")
                else:
                    print(f"  Vorlage vorhanden (#{t.id}) — unverändert")
            installed.append(t.id)

            # ── 5) Vorschaubild ──────────────────────────────────────────
            prev = template_preview.ensure(cfg, t)
            print(f"  Vorschau: {prev if prev else 'konnte nicht erzeugt werden'}")

    # ── 4) aktive Veranstaltung ──────────────────────────────────────────
    with Session(engine) as session:
        event = session.exec(select(Event).where(Event.is_active == True)).first()  # noqa: E712
        if event is None:
            print("\nKeine aktive Veranstaltung — die Booth zeigt alle Vorlagen.")
        else:
            try:
                ecfg = json.loads(event.config_json or "{}")
            except json.JSONDecodeError:
                ecfg = {}
            ids = list(ecfg.get("template_ids") or [])
            if not ids:
                print(f"\nVeranstaltung „{event.name}“ hat keine feste Vorlagen-Auswahl — "
                      "die Booth zeigt alle Vorlagen, also auch die Demo.")
            else:
                missing = [i for i in installed if i not in ids]
                if missing:
                    ecfg["template_ids"] = ids + missing
                    event.config_json = json.dumps(ecfg)
                    session.add(event)
                    session.commit()
                    print(f"\nVeranstaltung „{event.name}“: Vorlage(n) {missing} freigegeben.")
                else:
                    print(f"\nVeranstaltung „{event.name}“: Demo-Vorlagen bereits freigegeben.")

    print("\nFertig. Booth-Seite neu laden, dann erscheinen die Vorlagen unter „Layout wählen“.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
