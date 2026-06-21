# MKPhotobox

Modulare Photo-Booth-Software für Veranstaltungen — **Python (FastAPI)** Backend,
**Vanilla-JS** Single-Page-Frontend, **offline-fähig**, bedienbar komplett über die
Weboberfläche (kein Verlassen des Browsers nötig).

> Status: aktiv in Entwicklung. Zielgerät: x86_64-Mini-PC mit Ubuntu 24.04
> (läuft grundsätzlich auch auf Raspberry Pi OS / anderen Linuxen).

---

## Features

- **Aufnahme**: DSLR via gPhoto2 (Canon/Nikon/Sony …), USB-Webcam (OpenCV),
  Browser-Webcam (WebRTC), digiCamControl (Windows). Live-Vorschau + Auslösen,
  Countdown, animiertes GIF aus Vorschau-Puffer. **Live-Crop-Overlay**: der
  spätere Zuschnitt (Ziel-Seitenverhältnis) wird im Live-Bild eingeblendet.
- **Foto-Vorlagen / Mehrbild**: Vorlagen-Editor (Raster *und* freies Drag-&-Drop),
  Hintergrund/Rahmen/Logos/Sticker, serverseitiges Compositing (Pillow),
  Booth-Flow nimmt N Fotos auf und rendert die Collage (samt **Set-GIF** der
  Einzelaufnahmen). Pro Event zuweisbar.
- **Ausgabe-Formate (Presets)**: wiederverwendbare Druck-Presets — Papiergröße
  **live aus CUPS** gelesen, Canvas-Pixel aus physischer Größe × DPI (kein
  Pixel-Raten), Hoch/Quer behält das Format. Plus Social-Formate (Instagram,
  TikTok/Story …). Eine Vorlage wird einem Format zugewiesen; deren Collage
  druckt automatisch auf dem hinterlegten Drucker/Papier (z. B. Dreier-Set →
  Panorama-Drucker).
- **Assets**: Browser für Datenspeicher/Wechseldatenträger → Hintergründe, Rahmen,
  Logos, Sticker importieren (mit Pfad-Schutz).
- **Ausgabe/Teilen**: E-Mail (SMTP), Drucken (CUPS + `lp`-Fallback, echte
  Papiergrößen, **Live-Druckerstatus**: Papier leer / Tür offen / offline …),
  **CD/DVD brennen** (xorriso, CD/DVD-Auto-Erkennung),
  **USB/Wechseldatenträger-Export** (auswählbares Ziel, inkl. mitgeliefertem
  **Offline-Foto-Viewer** `index.html`), Bluetooth, QR-Code (mit LAN-IP, nicht
  localhost), Download.
- **Galerie**: Event-Galerie mit Lightbox, GIF-Anzeige, optionalem Löschmodus.
  Zusätzlich eine **Live-Web-Galerie** (`/live`) mit öffentlichem JSON-Feed, die
  neue Fotos automatisch nachlädt — per QR teilbar.
- **Online-Galerie (Server-Sync)**: spiegelt jedes neue Foto (+ GIF) samt
  `photos.json` und Live-Viewer auf einen **externen Server** — Transport
  wählbar: WebDAV / FTPS / FTP / rsync / SCP.
- **Admin (Web)**: Kameras, Module, Veranstaltungen, Hintergrund-Entfernung,
  Vorlagen/Assets, **Ausgabe-Formate**, Auslöser, Drucker, **Online-Galerie**,
  CD/DVD, USB, **WLAN-Verwaltung (nmcli)**, Bezahlung, Einstellungen, Tests,
  **Herunterfahren** + **Software aktualisieren** (In-App-Self-Update).
- **Touch-tauglich**: integrierte **Bildschirmtastatur (OSK)**, Markieren
  deaktiviert, große Buttons.
- **Bezahlung** (optional): Stripe/SumUp (QR & Terminal), MDB-Münzer.
- **Auslöser**: Touchscreen, GPIO, Akustik, Tastatur, Seriell, Bluetooth.

---

## Anforderungen

### Hardware
- x86_64-PC oder Raspberry Pi (3+).
- Kamera: DSLR (USB, gPhoto2-kompatibel) **oder** USB-Webcam.
- Optional: Touchscreen (USB-HID oder seriell/RS232), Fotodrucker (CUPS),
  internes/externes CD/DVD-Laufwerk, WLAN/Ethernet.

### Software
- **Linux** (Ubuntu 24.04 empfohlen), Python **3.10+**.
- Kern-Abhängigkeiten (siehe `pyproject.toml`): FastAPI, Uvicorn, SQLModel,
  Pillow, PyYAML, python-jose, bcrypt, aiofiles, alembic.
- Optionale Systempakete je nach genutzten Funktionen:
  | Funktion        | System-Paket(e)                                   | Python-Extra        |
  |-----------------|---------------------------------------------------|---------------------|
  | DSLR (gPhoto2)  | `libgphoto2-dev`, Toolchain                        | `.[gphoto2]`        |
  | USB-Webcam      | —                                                 | `.[opencv]`         |
  | Drucken         | `cups`, `libcups2-dev`                             | `.[printer-linux]`  |
  | CD/DVD brennen  | `xorriso`                                          | —                   |
  | WLAN-Verwaltung | `network-manager` (nmcli)                          | —                   |
  | Akustik-Auslöser| `libportaudio2`                                   | `.[audio]`          |
  | Serieller Auslöser | —                                              | `.[serial]`         |
  | Tastatur/BT/evdev-Auslöser | Gruppe `input`                         | `.[triggers]`       |
  | Bezahlung (SumUp) | —                                               | `.[payment]`        |
  | Bluetooth-Versand | `bluez`, `gnome-bluetooth-sendto`               | —                   |
  | KI-Hintergrund  | — (groß: onnxruntime)                              | `.[background-ai]`  |

> **Wichtig (Versions-Pin):** Nur **`fastapi==0.135.3` + `starlette==1.0.0`**
> verwenden. Neuere, untereinander inkompatible Versionen brechen `include_router`
> **stillschweigend** (es werden Routen nicht registriert → Features liefern 404,
> die App „startet" aber normal). Das `setup.sh` pinnt das automatisch.

---

## Schnellstart (Entwicklung)

```bash
git clone https://github.com/mkrasselt1/mkphotobox.git && cd mkphotobox
python3 -m venv .venv
.venv/bin/pip install -e .                 # Kern-Abhängigkeiten
.venv/bin/pip install "fastapi==0.135.3" "starlette==1.0.0"
.venv/bin/python -m app.main               # startet auf http://0.0.0.0:8080
```

Standard-Login: **`admin` / `admin`** (in den Einstellungen ändern).

## Installation auf dem Zielgerät

```bash
sudo ./scripts/setup.sh            # System-Deps, venv, Dienst einrichten
sudo ./scripts/kiosk-setup.sh      # optional: Vollbild-Browser-Kiosk + Autologin
```

Details siehe [`scripts/setup.sh`](scripts/setup.sh) und
[`scripts/kiosk-setup.sh`](scripts/kiosk-setup.sh).

### Update

Zwei Wege:

- **In der Weboberfläche**: Admin → **„Software aktualisieren"** (nur Admin).
  Holt den neuesten Stand von GitHub (`git fetch` + `reset --hard origin/main`,
  läuft als App-Benutzer) und startet den Dienst neu. Erfordert die
  NOPASSWD-sudoers-Regel für `systemctl restart` (legt `setup.sh` an).
- **Per SSH**:
  ```bash
  sudo ./scripts/update.sh      # git pull + Deps + Neustart
  ```

Beide holen den neuesten Stand aus dem Repo und starten neu. Beim **ersten**
SSH-Lauf wird ein per Tarball deploytes Verzeichnis als git-Checkout übernommen.
`config.yaml`, `data/` und `.venv` sind gitignored und bleiben erhalten.
**Schema-Migrationen laufen automatisch beim Start** (`database.py` ergänzt
fehlende Spalten additiv — siehe unten). Das unbundlete Frontend wird mit
`Cache-Control: no-cache` ausgeliefert, damit Browser nach einem Update sofort
die frische UI laden (ETag-Revalidierung → 304 wenn unverändert).

### Datenbank-Migration

`create_db()` legt fehlende Tabellen an **und** ergänzt fehlende Spalten
bestehender Tabellen automatisch beim Start (additiv, NULL-fähig). So überlebt
die Box App-Updates ohne manuellen Migrationsschritt. Umbenennungen/Typänderungen
/Drops bräuchten weiterhin Alembic (`migrations/`).

### Remote-Zugang (Tailscale)

Für stabilen Fernzugriff (unabhängig vom lokalen Netz, durch NAT/Firewall):

```bash
sudo ./scripts/tailscale-setup.sh                 # interaktiv (Link im Browser bestätigen)
sudo TS_AUTHKEY=tskey-... ./scripts/tailscale-setup.sh   # nicht-interaktiv
# oder als Teil des Setups:
sudo WITH_TAILSCALE=1 TS_AUTHKEY=tskey-... ./scripts/setup.sh
```

Aktiviert **Tailscale SSH** → danach `ssh photobooth@mkphotobox` aus dem eigenen
Tailnet, ohne Schlüssel/Port-Freigabe. Ideal für eine Box hinter einer
instabilen Leitung.

---

## Konfiguration

3-Schichten-Merge (spätere gewinnen):
1. `config.defaults.yaml` (mitgeliefert, **nicht** bearbeiten)
2. `config.yaml` (eigene Overrides, gitignored)
3. DB-Settings (zur Laufzeit über das Admin-API)

Wichtige Schlüssel: `server.port`, `photos.storage_path`, `cameras.*`,
`outputs.*`, `cd_burn.*`, `usb_export.*` (inkl. `include_viewer`),
`remote_gallery.*` (Server-Sync: `enabled`, `protocol`, `host`/`url`, `username`,
`password`, `remote_dir`, `key_path`, `public_url`), `share.base_url` (für QR;
sonst automatische LAN-IP-Erkennung), `auth.default_admin_password`.

Ausgabe-Formate (Druck-/Social-Presets) liegen als eigene Tabelle in der DB und
werden im Admin unter **Ausgabe-Formate** gepflegt; die Social-Standardformate
(Instagram/TikTok …) werden beim Start automatisch angelegt.

---

## Architektur

```
app/
  main.py            FastAPI-App-Factory + Lifespan (lädt Module)
  config.py          3-Schichten-Config
  database.py        SQLModel/SQLite (WAL)
  models.py          ORM (User, Event, Photo, Asset, Template, …)
  api/               Routen: photos, printer, presets, remote_gallery, cd_burn,
                     usb_export, wifi, assets, templates, events, settings,
                     system, tests, …
  modules/           Pluggable Module (camera/ trigger/ output/ payment/)
  services/          Logik: photo_service, collage_service, paper_sizes,
                     viewer_assets (geteilter Galerie-Viewer), remote_gallery,
                     asset_service, cd_burn_service, usb_export_service, …
frontend/
  src/core/          app, router (hash-based), state, ws-client, osk
  src/booth/         booth-flow (FSM, inkl. Live-Crop-Overlay), gallery
  src/admin/         admin-shell + je eine Seite pro Bereich (presets,
                     remote-gallery, printer, …)
# Standalone /live-Galerie + öffentlicher Feed: GET /live, /api/v1/photos/feed.json
config.defaults.yaml
scripts/             setup.sh, kiosk-setup.sh (erzeugen systemd-Units etc.)
```

Tests sind **echte Integrationstests** (keine Mocks/Stubs) und laufen über das
Admin-Test-API bzw. `app/api/tests.py`.

---

## Deployment-Hinweise / Stolpersteine

- **fastapi/starlette pinnen** (s. o.) — sonst verschwinden Routen.
- **gPhoto2-Binding** muss ins venv (`pip install gphoto2`, braucht
  `libgphoto2-dev`). DSLR ist nur von **einem** Prozess gleichzeitig nutzbar —
  konkurrierende Tools (z. B. go2rtc `--capture-movie`) vorher stoppen.
- **Kamera-Selbstheilung**: das gPhoto2-Modul serialisiert Zugriffe (Thread-Lock)
  und re-initialisiert die Kamera bei USB-Hängern/leeren Frames automatisch.
- **Serieller Touchscreen** (z. B. EETI eGalax): braucht `inputattach` als
  Dienst, danach Kalibrier-Matrix via `libinput`/xorg.conf.d — richtet
  `kiosk-setup.sh` mit `TOUCH_SERIAL=eetiegalax TOUCH_PORT=/dev/ttyS0
  TOUCH_MATRIX="…"` ein.
- **QR-Codes**: nutzen die LAN-IP der Box (`/api/v1/system/share-base`), nicht
  `localhost` — sonst kann das Gast-Handy nichts laden.
- **Drucker-Papiergrößen** kommen live aus CUPS (`lpoptions -p <drucker> -l`);
  der **Druckerstatus** (Papier leer, Tür offen, offline) aus
  `printer-state-reasons` (pycups, `lpstat`-Fallback).
- **Herunterfahren / Neustart / Self-Update** brauchen eine NOPASSWD-sudoers-Regel
  für den App-Benutzer (`/etc/sudoers.d/mkphotobox`: `systemctl poweroff, reboot,
  restart mkphotobox.service`). `setup.sh` legt sie an — fehlt sie, melden die
  Buttons „keine Berechtigung". Der Code prüft die konkrete Erlaubnis via
  `sudo -n -l <cmd>` (nicht `sudo -n true`, das nur per Credential-Cache passt).
- **Online-Galerie / Server-Sync**: WebDAV/FTPS/FTP via `curl`, rsync/SCP via
  `ssh` (SSH-Key oder `sshpass`). `setup.sh` installiert `rsync` + `sshpass`.

---

## Lizenz

TBD.
