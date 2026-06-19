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
  Countdown, animiertes GIF aus Vorschau-Puffer.
- **Foto-Vorlagen / Mehrbild**: Vorlagen-Editor (Raster *und* freies Drag-&-Drop),
  Hintergrund/Rahmen/Logos/Sticker, serverseitiges Compositing (Pillow),
  Booth-Flow nimmt N Fotos auf und rendert die Collage. Pro Event zuweisbar.
- **Assets**: Browser für Datenspeicher/Wechseldatenträger → Hintergründe, Rahmen,
  Logos, Sticker importieren (mit Pfad-Schutz).
- **Ausgabe/Teilen**: E-Mail (SMTP), Drucken (CUPS + `lp`-Fallback, echte
  Papiergrößen), **CD/DVD brennen** (xorriso, CD/DVD-Auto-Erkennung),
  **USB/Wechseldatenträger-Export** (auswählbares Ziel), Bluetooth,
  QR-Code (mit LAN-IP, nicht localhost), Download.
- **Galerie**: Event-Galerie mit Lightbox, GIF-Anzeige, optionalem Löschmodus.
- **Admin (Web)**: Kameras, Module, Veranstaltungen, Hintergrund-Entfernung,
  Vorlagen/Assets, Auslöser, Drucker, CD/DVD, USB, **WLAN-Verwaltung (nmcli)**,
  Bezahlung, Einstellungen, Tests.
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

```bash
sudo ./scripts/update.sh      # git pull + Deps + Neustart
```

Holt den neuesten Stand aus dem Repo, aktualisiert Abhängigkeiten und startet
neu. Beim **ersten** Lauf wird ein per Tarball deploytes Verzeichnis als
git-Checkout übernommen. `config.yaml`, `data/` und `.venv` sind gitignored und
bleiben erhalten. **Schema-Migrationen laufen automatisch beim Start**
(`database.py` ergänzt fehlende Spalten additiv — siehe unten).

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
`outputs.*`, `cd_burn.*`, `usb_export.*`, `share.base_url` (für QR; sonst
automatische LAN-IP-Erkennung), `auth.default_admin_password`.

---

## Architektur

```
app/
  main.py            FastAPI-App-Factory + Lifespan (lädt Module)
  config.py          3-Schichten-Config
  database.py        SQLModel/SQLite (WAL)
  models.py          ORM (User, Event, Photo, Asset, Template, …)
  api/               Routen: photos, printer, cd_burn, usb_export, wifi,
                     assets, templates, events, settings, system, tests, …
  modules/           Pluggable Module (camera/ trigger/ output/ payment/)
  services/          Logik: photo_service, collage_service, asset_service,
                     cd_burn_service, usb_export_service, wifi_service, …
frontend/
  src/core/          app, router (hash-based), state, ws-client, osk
  src/booth/         booth-flow (FSM), gallery
  src/admin/         admin-shell + je eine Seite pro Bereich
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
- **Drucker-Papiergrößen** kommen live aus CUPS (`lpoptions -p <drucker> -l`).

---

## Lizenz

TBD.
