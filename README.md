# MKPhotobox

Modulare Photo-Booth-Software für Veranstaltungen — **Python (FastAPI)** Backend,
**Vanilla-JS** Single-Page-Frontend, **offline-fähig**, bedienbar komplett über die
Weboberfläche.

> **Bedienung & Handbuch:** Die komplette Erklärung aller Funktionen steht **in
> der Weboberfläche selbst** — im Admin-Bereich unter **„Hilfe"**. Dieses README
> beschreibt nur Installation und Systemvoraussetzungen.

> Zielgerät: x86_64-Mini-PC mit Ubuntu 24.04 (läuft grundsätzlich auch auf
> Raspberry Pi OS / anderen Linuxen).

---

## Systemvoraussetzungen

### Hardware
- x86_64-PC oder Raspberry Pi (3+).
- Kamera: DSLR (USB, gPhoto2-kompatibel) **oder** USB-Webcam.
- Optional: Touchscreen (USB-HID oder seriell/RS232), Fotodrucker (CUPS),
  internes/externes CD/DVD-Laufwerk, WLAN/Ethernet, USB-Stick (Export).

### Software
- **Linux** (Ubuntu 24.04 empfohlen), Python **3.10+**.
- Kern-Abhängigkeiten (siehe `pyproject.toml`): FastAPI, Uvicorn, SQLModel,
  Pillow, PyYAML, python-jose, bcrypt, aiofiles, alembic.
- Optionale Systempakete je nach genutzten Funktionen:

  | Funktion                  | System-Paket(e)                      | Python-Extra        |
  |---------------------------|--------------------------------------|---------------------|
  | DSLR (gPhoto2)            | `libgphoto2-dev`, Toolchain          | `.[gphoto2]`        |
  | USB-Webcam                | —                                    | `.[opencv]`         |
  | Drucken + Status          | `cups`, `libcups2-dev`               | `.[printer-linux]`  |
  | CD/DVD brennen            | `xorriso`                            | —                   |
  | WLAN-Verwaltung           | `network-manager` (nmcli)            | —                   |
  | Online-Galerie (Server-Sync) | `curl`, `rsync`, `sshpass`        | —                   |
  | Öffentliche QR-Links (Cloudflare Quick-Tunnel) | `cloudflared`      | —                   |
  | Akustik-Auslöser          | `libportaudio2`                      | `.[audio]`          |
  | Serieller Auslöser        | —                                    | `.[serial]`         |
  | Tastatur/BT/evdev-Auslöser| Gruppe `input`                       | `.[triggers]`       |
  | Bezahlung (SumUp)         | —                                    | `.[payment]`        |
  | Bluetooth-Versand         | `bluez`, `gnome-bluetooth-sendto`    | —                   |
  | KI-Hintergrund            | — (groß: onnxruntime)                | `.[background-ai]`  |

> **Wichtig (Versions-Pin):** Nur **`fastapi==0.135.3` + `starlette==1.0.0`**
> verwenden. Neuere, untereinander inkompatible Versionen brechen `include_router`
> **stillschweigend** (Routen werden nicht registriert → Features liefern 404, die
> App „startet" aber normal). `setup.sh` pinnt das automatisch.

---

## Installation (Zielgerät)

```bash
git clone https://github.com/mkrasselt1/mkphotobox.git
cd mkphotobox
sudo ./scripts/setup.sh            # System-Deps, venv, systemd-Dienst, sudoers-Regel
sudo ./scripts/kiosk-setup.sh      # optional: Vollbild-Browser-Kiosk + Autologin
```

`setup.sh` ist idempotent (mehrfach ausführbar), richtet den Dienst
`mkphotobox.service` (Autostart, Port **8080**) ein, pinnt fastapi/starlette und
legt die NOPASSWD-sudoers-Regel für Herunterfahren/Neustart/Self-Update an.
Toggles z. B. `WITH_GPHOTO2=1 WITH_PRINTER=1 WITH_TAILSCALE=1 …` — siehe Kopf von
[`scripts/setup.sh`](scripts/setup.sh).

Standard-Login: **`admin` / `admin`** (nach dem ersten Start in den Einstellungen
ändern).

### Schnellstart (Entwicklung, ohne Dienst)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install "fastapi==0.135.3" "starlette==1.0.0"
.venv/bin/python -m app.main               # http://0.0.0.0:8080
```

---

## Update

- **In der Weboberfläche**: Admin → **„Software aktualisieren"** (holt den
  neuesten Stand von GitHub und startet neu).
- **Per SSH**: `sudo ./scripts/update.sh`

`config.yaml`, `data/` und `.venv` sind gitignored und bleiben erhalten.
**Schema-Migrationen laufen automatisch beim Start** (`database.py` ergänzt
fehlende Spalten additiv; Umbenennungen/Drops bräuchten Alembic, `migrations/`).

---

## Remote-Zugang (Tailscale)

Für stabilen Fernzugriff (durch NAT/Firewall, unabhängig vom lokalen Netz):

```bash
sudo ./scripts/tailscale-setup.sh                        # interaktiv (Link bestätigen)
sudo WITH_TAILSCALE=1 TS_AUTHKEY=tskey-... ./scripts/setup.sh   # nicht-interaktiv
```

Aktiviert **Tailscale SSH** → danach `ssh photobooth@mkphotobox` aus dem eigenen
Tailnet, ohne Schlüssel/Port-Freigabe.

## Öffentliche QR-Links (Cloudflare Quick-Tunnel)

Damit die QR-Codes (Foto/GIF/Galerie) auch für Gäste-Handys funktionieren, die
**nicht im WLAN der Box** sind — ohne Cloudflare-Konto/Login. `cloudflared` öffnet
einen Quick-Tunnel mit einer zufälligen `*.trycloudflare.com`-Adresse; die App nutzt
diese automatisch als QR-Basis. Die Bildanzeige in der Steuerung bleibt lokal (LAN).

```bash
sudo ./scripts/cloudflared-setup.sh                 # cloudflared + Dienst installieren
sudo WITH_CLOUDFLARE=1 ./scripts/setup.sh           # beim Setup mit einrichten
```

Ein-/ausschalten im Admin unter **Online-Galerie → Cloudflare Quick-Tunnel** (zeigt die
aktuelle URL). Die URL wird bei jedem Tunnel-Neustart neu vergeben (bei Quick-Tunneln
normal). Für eine feste Adresse stattdessen die **Online-Galerie** mit eigener Domain
nutzen oder `share.base_url` in der `config.yaml` setzen.

---

## Installations-Stolpersteine

- **fastapi/starlette pinnen** (s. o.) — sonst verschwinden Routen.
- **gPhoto2-Binding** muss ins venv (`pip install gphoto2`, braucht
  `libgphoto2-dev`). Die DSLR ist nur von **einem** Prozess gleichzeitig nutzbar.
- **Serieller Touchscreen** (z. B. EETI eGalax): `inputattach` als Dienst +
  `libinput`-Kalibriermatrix — richtet `kiosk-setup.sh` ein (`TOUCH_SERIAL=…`).
- **Herunterfahren / Self-Update**: brauchen die NOPASSWD-sudoers-Regel aus
  `setup.sh` (`/etc/sudoers.d/mkphotobox`). Fehlt sie, melden die Buttons „keine
  Berechtigung".
- **Bedienungsfragen** („wie richte ich X ein?") → **Admin → Hilfe** in der App.

---

## Lizenz

TBD.
