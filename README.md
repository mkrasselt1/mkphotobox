# MKPhotobox

**Die Fotobox, die einem ganzen Abend gewachsen ist.** Gäste tippen auf den
Bildschirm, posen, bekommen ihr Foto gedruckt und aufs Handy — und du musst nichts
tun außer den Strom einzuschalten.

Modulare Photo-Booth-Software für Veranstaltungen: **Python (FastAPI)** im Rücken,
**Vanilla-JS**-Oberfläche im Vordergrund, **komplett offline lauffähig**, bedienbar
vollständig über den Browser.

![Die Willkommensseite der Fotobox mit Live-Vorschau und Look-Auswahl](docs/media/booth-idle.png)

---

## Warum diese Box

- **Läuft ohne Internet.** WLAN-Ausfall auf der Hochzeit? Egal. Aufnehmen,
  drucken, Galerie, USB-Export — alles lokal. Online-Dienste sind Zugabe, nie
  Voraussetzung.
- **Ein Rechner, keine Cloud-Abos.** Ein gebrauchter Mini-PC reicht. Keine
  Lizenzschlüssel, keine Bilder auf fremden Servern.
- **Für Vermieter gebaut.** Ein eingeschränkter *Mieter*-Login lässt Kunden ihre
  Veranstaltung selbst einrichten, ohne an Netzwerk, Zahlung oder System zu kommen.
- **Modular.** Kamera, Auslöser, Ausgabe und Bezahlung sind austauschbare Module.
  DSLR oder Webcam, Touch oder Klingelknopf, Druck oder QR — kombinierbar.
- **Erklärt sich selbst.** Das komplette Handbuch steckt in der Oberfläche unter
  **Hilfe**; dieses README behandelt nur Installation und Systemvoraussetzungen.

> Zielgerät: x86_64-Mini-PC mit Ubuntu 24.04 (läuft grundsätzlich auch auf
> Raspberry Pi OS / anderen Linuxen).

---

## So läuft ein Abend

**1 · Look wählen, dann posieren.** Schwarzweiß, Noir, Sepia, Vintage, warm, kühl
oder knallig. Die Live-Vorschau zeigt den Look sofort — man sieht vorher, was
hinterher herauskommt.

![Booth mit ausgewähltem Sepia-Look, die Vorschau ist bereits sepiafarben](docs/media/booth-looks.png)

**2 · Layout wählen.** Einzelfoto oder Mehrbild-Streifen — was du für die
Veranstaltung freigegeben hast.

![Layout-Auswahl mit Einzelfoto und Dreier-Streifen](docs/media/booth-templates.png)

**3 · Countdown.** Mit Piepton, Auslöse-Klick und Weißblende. Der Auslöse-Vorlauf
gleicht die Verzögerung der Kamera aus, damit das Foto exakt bei „0" entsteht.

![Countdown über der Live-Vorschau](docs/media/booth-countdown.png)

**4 · Ansehen — und verewigen.** Nicht gefallen? *Nochmal*. Sonst: mit dem Finger
aufs Foto malen und ein Grußwort dazuschreiben. Das digitale Gästebuch.

![Fotoansicht mit den Schaltflächen Nochmal, Grußwort und Weiter](docs/media/booth-review.png)

![Gästebuch: ein gemaltes Herz über der Gruppe, darunter ein Grußwort](docs/media/booth-guestbook.png)

**5 · Mitnehmen.** Drucken, per QR aufs Handy, E-Mail, Bluetooth, USB-Stick oder
auf CD/DVD gebrannt. Und alles landet in der Galerie.

![Galerie mit den Fotos des Abends, Collagen und GIF-Markierungen](docs/media/gallery.png)

---

## Was die Box kann

**Aufnehmen**
- DSLR über gPhoto2 (Linux) oder digiCamControl (Windows), USB-Webcam über
  OpenCV, oder die Kamera des Browsers — auch getrennt für Vorschau und Aufnahme
  (Webcam zeigt live, DSLR schießt).
- Auslöser: Touch, GPIO-Knopf, Tastatur, seriell, Bluetooth oder Klatschen.
- Drehen und Spiegeln für schräg montierte Kameras. Getrennt davon der
  **Spiegel-Effekt**: Gäste sehen sich wie im Spiegel und posieren richtig herum,
  das gespeicherte Foto bleibt seitenrichtig — Schrift und Logos bleiben lesbar.
- Hintergrund ersetzen per Greenscreen oder KI-Freisteller.
- **Animiertes GIF** aus den Sekunden vor dem Auslösen, wahlweise als
  **Boomerang** (vorwärts und wieder rückwärts).

**Gestalten**
- Vorlagen-Editor mit frei platzierbaren Foto-Slots, Rahmen, Logos und Text
  (Schriftart, Kontur, Drehung) — direkt auf dem Touchscreen bedienbar.
- Ausgabe-Formate (10×15, A6, A4 …) bestimmen die Leinwandgröße der Vorlage.
- Ein Foto darf in mehreren Slots auftauchen: zwei Aufnahmen füllen ein
  Drei-Bilder-Layout.

**Ausgeben**
- Druck über CUPS mit **Papierstand-Überwachung** — die Box warnt und stoppt,
  bevor mitten in der Nacht das Papier ausgeht.
- QR-Code aufs Gäste-Handy, E-Mail oder Bluetooth — beim Bluetooth-Versand sucht
  die Box Geräte in der Nähe, der Gast tippt seins an; vorheriges Koppeln ist
  nicht nötig. Umgekehrt nimmt die Box auch Dateien per Bluetooth entgegen.
- USB-Stick-Export und CD/DVD-Brennen für die Übergabe an den Veranstalter.
- Online-Galerie: spiegelt jedes neue Foto auf einen eigenen Server.

**Verwalten**
- Mehrere Veranstaltungen, jede mit eigenen Vorlagen und eigenem Standort.
- **Metadaten**: Veranstaltungsname, Ort, GPS-Koordinaten, Aufnahmezeit und
  Kameramodell landen in den EXIF-Daten jedes Fotos, jeder Collage und jedes
  Thumbnails; GIFs bekommen dieselben Angaben als Kommentar. Die Bilddaten selbst
  bleiben dabei unangetastet — es wird nichts neu komprimiert.
- Bezahlung per SumUp (QR oder Terminal) oder Münzprüfer, wenn die Box Geld
  verdienen soll.
- Telegram-Benachrichtigungen: Hilfe-Knopf im Booth und Warnung bei leerem Drucker.
- Eingebauter **Selbsttest** prüft Kamera, Datenbank, Drucker, Auslöser und
  Bildverarbeitung auf Knopfdruck.

---

## Die Steuerung

Alles über den Browser — vom Handy, Tablet oder direkt am Touchscreen der Box.

![Admin-Dashboard mit System-, Kamera-, Ausgabe- und Druckerstatus](docs/media/admin-dashboard.png)

Die Kamera-Einstellungen mit Drehung, Spiegelung und dem Spiegel-Effekt:

![Kamera-Einstellungen mit Bild-Transformation und Spiegel-Effekt](docs/media/admin-cameras.png)

Veranstaltungen — inklusive Standort, der in die Fotos geschrieben wird:

![Veranstaltungsverwaltung mit hinterlegtem Standort](docs/media/admin-events.png)

Und das Handbuch, das immer auf der Box liegt:

![Das eingebaute Handbuch im Admin-Bereich](docs/media/admin-help.png)

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
  | Bluetooth senden/empfangen| `bluez`, `bluez-obexd`, `bluez-tools`, `obexftp` | —       |
  | KI-Hintergrund            | — (groß: onnxruntime)                | `.[background-ai]`  |

> **Wichtig (Versions-Pin):** Nur **`fastapi==0.135.3` + `starlette==1.0.0`**
> verwenden. Neuere, untereinander inkompatible Versionen brechen `include_router`
> **stillschweigend** (Routen werden nicht registriert → Features liefern 404, die
> App „startet" aber normal). `setup.sh` pinnt das automatisch.

Die Töne im Booth erzeugt der Browser selbst (Web Audio) — es werden keine
Audiodateien gebraucht. Browser lassen Ton allerdings erst zu, nachdem der
Bildschirm einmal berührt wurde; im Kiosk-Dauerbetrieb kann der allererste
Countdown nach einem Neustart daher stumm bleiben.

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
- **WLAN verbinden schlägt fehl, obwohl Netze gefunden werden**: Der Dienst läuft
  ohne Login-Sitzung, deshalb lehnt polkit alle schreibenden NetworkManager-
  Aktionen ab („Not authorized to control networking"). Scannen braucht keine
  Berechtigung — daher erscheinen die Netze ganz normal. `setup.sh` legt dafür
  `/etc/polkit-1/rules.d/50-mkphotobox-network.rules` an; fehlt die Datei, das
  Setup erneut ausführen.
- **Bluetooth**: Das Senden nutzt `bt-obex` aus `bluez-tools`, nicht den
  GTK-Dialog `bluetooth-sendto` (auf einer Kiosk-Box ohne Desktop-Sitzung
  nutzlos). `obexd` hängt am D-Bus-**Session**-Bus, den ein System-Dienst nicht
  hat — `setup.sh` aktiviert deshalb Lingering für den Dienst-Benutzer. Empfangen
  übernehmen die Units `mkphotobox-btrecv` und `mkphotobox-btagent`.
- **Ein Modul lässt sich einschalten, tut aber nichts**: **Admin → Module** nennt
  den Grund samt Installationsbefehl. Fehlt ein Python-Paket, ist beim Setup
  meist der Download abgebrochen — dann `setup.sh` einfach erneut ausführen.
- **Kein AirDrop / Quick Share**: Beides sind geschlossene Protokolle, die Box
  kann sich nicht als Ziel anbieten. Gäste teilen stattdessen vom eigenen Handy
  aus, nachdem sie das Foto über den QR-Code geöffnet haben.
- **Bedienungsfragen** („wie richte ich X ein?") → **Admin → Hilfe** in der App.

---

## Zu den Bildern in diesem README

Die Screenshots zeigen die echte Oberfläche. Die abgebildeten „Gäste" sind
allerdings keine Fotos, sondern mit Pillow gezeichnete Illustrationen aus
[`docs/media/demo/`](docs/media/demo/) — sie stammen aus diesem Repository, zeigen
keine realen Personen und sind damit uneingeschränkt frei verwendbar.

---

## Lizenz

TBD.
