import { adminShell, setupLogout } from './admin-shell.js';

// In-app handbook. The repo README only covers installation; everything about
// *operating* the box lives here so it's always available on the device.
const SECTIONS = [
    {
        icon: '🚀', title: 'Erste Schritte',
        html: `
        <p>Die Box wird komplett über den Browser bedient — kein Verlassen des Browsers nötig.</p>
        <ol>
            <li><strong>Veranstaltung</strong> anlegen/aktivieren (Bereich <em>Veranstaltungen</em>).</li>
            <li><strong>Kamera</strong> wählen und testen (<em>Kameras</em>).</li>
            <li>Optional <strong>Foto-Vorlagen</strong> und ein <strong>Ausgabe-Format</strong> einrichten.</li>
            <li><strong>Drucker</strong> bzw. Teilen-Wege (E-Mail, QR, Online-Galerie) konfigurieren.</li>
            <li>Über <em>„Zum Booth"</em> in den Gäste-Modus wechseln.</li>
        </ol>
        <p>Standard-Login ist <code>admin / admin</code> — bitte in den Einstellungen ändern.</p>`,
    },
    {
        icon: '🎉', title: 'Veranstaltungen',
        html: `<p>Pro Event lassen sich eigene Einstellungen und die angebotenen Foto-Vorlagen festlegen.
        Es ist immer genau <strong>eine Veranstaltung aktiv</strong> — deren Fotos landen in der Galerie
        und im Online-Feed. Neue Box-Sessions starten automatisch unter dem aktiven Event.</p>
        <p><strong>Standort:</strong> Unter <em>Bearbeiten</em> lassen sich Ortsbezeichnung und
        GPS-Koordinaten hinterlegen — per Hand, als eingefügtes Koordinatenpaar oder mit
        <em>„Standort dieses Geräts"</em> (Ortung erlauben die Browser meist nur über HTTPS
        oder localhost).</p>
        <p>Veranstaltungsname, Ort, Koordinaten, Aufnahmezeit und die verwendete Kamera schreibt die Box
        in die <strong>EXIF-Informationen</strong> jedes Fotos, jeder Collage und jedes Thumbnails; GIFs
        bekommen die gleichen Angaben als Kommentar (GIF kann kein EXIF). Die Bilddaten selbst bleiben
        dabei unangetastet — es wird nichts neu komprimiert. Abschalten oder um Fotograf/Copyright
        ergänzen lässt sich das im Abschnitt <code>exif</code> der Konfiguration.</p>`,
    },
    {
        icon: '📷', title: 'Kameras',
        html: `<p>Unterstützt werden <strong>DSLR</strong> (gPhoto2), <strong>USB-Webcam</strong> (OpenCV)
        und die <strong>Browser-Kamera</strong> (WebRTC). Wähle die aktive Kamera und teste die Vorschau.</p>
        <ul>
            <li>Die DSLR kann nur von <em>einem</em> Programm gleichzeitig genutzt werden.</li>
            <li>Vorschaugröße, Countdown und der „Auslöse-Vorlauf" (Foto landet exakt bei „0")
                stellst du in den <em>Einstellungen</em> ein.</li>
        </ul>
        <p><strong>Drehen &amp; Spiegeln</strong> gleicht aus, wie die Kamera montiert ist, und wirkt
        bei allen Kameratypen auf Vorschau und Foto gleichermaßen.</p>
        <p><strong>Vorschau spiegeln</strong> ist etwas anderes: Die Gäste sehen sich wie in einem
        Spiegel und posieren dadurch richtig herum — das <em>gespeicherte Foto bleibt seitenrichtig</em>,
        damit Schrift und Logos im Bild lesbar sind. Für eine Fotobox in aller Regel die richtige
        Einstellung, und deshalb ab Werk an.</p>`,
    },
    {
        icon: '🔊', title: 'Ton, Blitz & Boomerang',
        html: `<p>Unter <em>Kameras</em> lassen sich drei Kleinigkeiten schalten, die viel ausmachen:</p>
        <ul>
            <li><strong>Countdown-Piep und Auslöse-Klick.</strong> Die Töne erzeugt der Browser selbst —
                keine Audiodateien, funktioniert also auch ohne Internet. Der Bildschirm muss einmal
                berührt worden sein, bevor Browser überhaupt Ton abspielen; das erledigt der erste
                Tipp im Booth automatisch. Über <em>Probe hören</em> kannst du die Lautstärke einstellen.</li>
            <li><strong>Weißblende</strong> im Moment der Aufnahme.</li>
            <li><strong>Boomerang</strong> — das GIF läuft vorwärts und wieder rückwärts, endlos.
                Nutzt dieselben Bilder wie bisher, kostet also nur Dateigröße.</li>
        </ul>`,
    },
    {
        icon: '🎨', title: 'Looks (Farbfilter)',
        html: `<p>Die Gäste wählen vor der Aufnahme einen Look — Schwarzweiß, Noir, Sepia, Vintage,
        warm, kühl oder knallig. Die Auswahl steht auf der Willkommensseite, und die
        <strong>Live-Vorschau zeigt den Look sofort</strong>, sodass man schon beim Posieren sieht,
        was herauskommt.</p>
        <p>Der Look wird fest ins Foto gerechnet und ist damit überall dabei: in der Collage, im Druck,
        auf dem USB-Stick und im Download der Gäste. Nach jedem Gast steht die Auswahl wieder auf
        „Original".</p>
        <p><strong>Wenn die Live-Vorschau ruckelt:</strong> Den Look im Live-Bild zu zeigen kostet
        pro Einzelbild Rechenzeit im Browser — auf schwacher Hardware wird die Vorschau dadurch zum
        Daumenkino. Unter <em>Kameras → Looks</em> lässt sich <em>„Look schon im Live-Bild zeigen"</em>
        abschalten: Die Gäste wählen weiterhin einen Look und bekommen ihn auch aufs Foto, nur das
        Live-Bild bleibt unbearbeitet und dadurch flüssig.</p>
        <p>Die Auswahl ganz abschalten oder auf einzelne Looks beschränken lässt sich ebenfalls dort
        bzw. im Abschnitt <code>filters</code> der Konfiguration.</p>`,
    },
    {
        icon: '✍️', title: 'Gästebuch',
        html: `<p>Nach der Aufnahme können die Gäste über <em>Grußwort</em> mit dem Finger direkt
        aufs Foto malen und eine kurze Nachricht darunter schreiben — das digitale Gästebuch.</p>
        <ul>
            <li>Sechs Farben, zwei Strichstärken, <em>Zurück</em> und <em>Alles löschen</em>.</li>
            <li>Das Ergebnis wird ins Foto gerechnet und ist damit auch im Druck und im Download dabei.</li>
            <li>Das <strong>unberührte Original</strong> bleibt erhalten (Ordner <code>originals/</code>).
                Ein zweiter Versuch startet deshalb wieder vom sauberen Bild, statt sich zu stapeln.</li>
        </ul>
        <p>Abschalten und die Länge des Grußworts stellst du im Abschnitt <code>guestbook</code> der
        Konfiguration ein.</p>`,
    },
    {
        icon: '⚡', title: 'Auslöser',
        html: `<p>Neben dem Touch-Button gibt es Hardware-Auslöser: <strong>GPIO</strong>, <strong>Akustik</strong>,
        <strong>Tastatur</strong>, <strong>Seriell</strong> und <strong>Bluetooth</strong>. Aktiviere und teste sie hier.</p>`,
    },
    {
        icon: '🧱', title: 'Foto-Vorlagen (Editor)',
        html: `<p>Vorlagen bestimmen, wie Einzelfotos zu einer Collage/zum Layout zusammengesetzt werden.</p>
        <ul>
            <li><strong>Foto-Slots</strong>: per Raster erzeugen oder frei per Drag-&-Drop platzieren,
                drehen, Größe ändern; Füllung <em>cover</em> (füllt, beschneidet) oder <em>contain</em> (ganz).</li>
            <li><strong>Grafiken</strong>: Hintergrund, ganzflächiger Rahmen, Logos/Sticker.</li>
            <li><strong>Text</strong>: Schriftart, Größe, Farbe, Kontur, Ausrichtung, Drehung.</li>
            <li><strong>Ausgabe-Format</strong> zuweisen → die Leinwandgröße folgt dem Format (siehe unten).</li>
            <li><em>Vorschau rendern</em> zeigt das echte Ergebnis (mit Platzhaltern oder echten Fotos).</li>
            <li>Beim Speichern entsteht zusätzlich ein <strong>Vorschaubild</strong>, das in der
                Vorlagenliste und im Booth auf den Karten der Layout-Auswahl erscheint — die Gäste
                sehen also das fertige Layout statt eines Symbols. Es erneuert sich automatisch,
                sobald du die Vorlage änderst; für die Vorschau werden immer nummerierte
                Platzhalter benutzt, nie echte Gästefotos.</li>
        </ul>
        <p>Mehrbild-Vorlagen nimmt der Booth nacheinander auf und erzeugt zusätzlich ein <strong>animiertes GIF</strong> der Aufnahmen.</p>`,
    },
    {
        icon: '📐', title: 'Ausgabe-Formate (Presets)',
        html: `<p>Ein Ausgabe-Format legt die Zielgröße fest und kann einer Vorlage zugewiesen werden.</p>
        <ul>
            <li><strong>Druck-Format</strong>: Drucker + Papier werden <em>live vom Drucker (CUPS)</em> gelesen,
                die Pixel ergeben sich aus der echten physischen Größe × <em>DPI</em> — kein Pixel-Raten.
                Beim Drehen (Hoch/Quer) bleibt das Format erhalten.</li>
            <li><strong>Social-Format</strong>: feste Pixelmaße (Instagram 1:1 / 4:5, TikTok/Story 9:16, 16:9);
                mit <em>„Hoch/Quer tauschen"</em> auch quer.</li>
            <li>Druckt der Booth eine Collage einer Format-gebundenen Vorlage, geht sie automatisch auf den
                im Format hinterlegten <strong>Drucker + Papier</strong> (z. B. Dreier-Set → Panorama-Drucker).</li>
        </ul>
        <p>Im Booth wird der spätere <strong>Zuschnitt</strong> als Rahmen über das Live-Bild gelegt.</p>`,
    },
    {
        icon: '🖼️', title: 'Vorlagen-Assets & Hintergrund',
        html: `<p>Importiere Hintergründe, Rahmen, Logos und Sticker vom Datenspeicher oder USB-Stick
        (<em>Vorlagen-Assets</em>). Unter <em>Hintergrund</em> lässt sich optional die KI-Hintergrund­entfernung nutzen.</p>`,
    },
    {
        icon: '🖨️', title: 'Drucker',
        html: `<p>Zwei Modi: <strong>Browser-Druck</strong> (Druckdialog am Client) oder <strong>Server-Druck</strong>
        (direkt über die Box, Drucker am Server). Im Server-Modus wählst du Drucker, Papierformat (live aus CUPS),
        Ausrichtung, Kopien, Rand.</p>
        <p>Das <strong>Status-Banner</strong> zeigt live, ob der Drucker bereit ist oder ein Problem meldet
        (<em>Papier leer, Tür/Abdeckung offen, offline, Toner/Tinte niedrig …</em>). Im Booth wird nach dem
        Druck gewarnt, falls der Drucker blockiert ist.</p>`,
    },
    {
        icon: '☁️', title: 'Online-Galerie (Server-Sync)',
        html: `<p>Spiegelt <strong>jedes neue Foto</strong> (samt GIF) automatisch auf einen externen Server und legt
        dort eine laufend aktualisierte <code>photos.json</code> + einen Live-Viewer (<code>index.html</code>) ab —
        die Galerie läuft dann komplett auf deinem Server.</p>
        <ul>
            <li>Transport wählbar: <strong>WebDAV</strong>, <strong>FTPS</strong>, <strong>FTP</strong>,
                <strong>rsync</strong>, <strong>SCP</strong>.</li>
            <li><em>Verbindung testen</em> lädt eine kleine Testdatei hoch.</li>
            <li><em>Alles neu hochladen</em> überträgt das ganze aktive Event erneut.</li>
            <li>Für rsync/scp mit Passwort muss <code>sshpass</code> installiert sein — sonst SSH-Key nutzen.</li>
        </ul>`,
    },
    {
        icon: '🔌', title: 'USB-Export & Einstellungen-Backup',
        html: `<p>Kopiert Fotos (optional inkl. GIFs) auf einen Wechseldatenträger — mit mitgeliefertem
        <strong>Offline-Viewer</strong> (<code>index.html</code>), sodass der Stick ohne Software durchgeblättert
        werden kann. Über denselben Bereich lassen sich <strong>Einstellungen sichern/laden</strong> (Übertragung
        auf eine andere Box).</p>`,
    },
    {
        icon: '📺', title: 'Galerie & Teilen',
        html: `<p>Die <strong>Booth-Galerie</strong> (Touch) zeigt alle Fotos des Events mit Lightbox, GIF-Wiedergabe und
        optionalem Löschmodus. Gäste teilen ihr Foto per <strong>QR</strong> (Foto/GIF), E-Mail, Bluetooth oder Druck.</p>
        <p>Die <strong>Live-Web-Galerie</strong> ist unter <code>/live</code> erreichbar (im Share-Screen als QR
        „Galerie (Live)"): eine Seite, die neue Fotos automatisch nachlädt — ideal für einen zweiten Bildschirm
        oder die Handys der Gäste im selben WLAN.</p>`,
    },
    {
        icon: '💿', title: 'CD/DVD brennen',
        html: `<p>Brennt die Event-Fotos auf eine eingelegte CD/DVD (xorriso). Das Laufwerk und der Medientyp
        werden automatisch erkannt; der Fortschritt wird live angezeigt.</p>`,
    },
    {
        icon: '📶', title: 'WLAN & Netzwerk',
        html: `<p>WLAN-Netze suchen/verbinden (NetworkManager). Der <em>Netzwerk-Status</em> zeigt IP-Adressen —
        wichtig, da QR-Codes die LAN-IP der Box verwenden (nicht <code>localhost</code>), damit Gäste-Handys laden können.</p>`,
    },
    {
        icon: '💳', title: 'Bezahlung',
        html: `<p>Optional: Stripe/SumUp (QR & Terminal) und MDB-Münzer. Ist Bezahlung aktiv, fordert der Booth vor
        der Aufnahme die Zahlung an und zeigt den Fortschritt.</p>`,
    },
    {
        icon: '🎨', title: 'Design',
        html: `<p>Farben, Größen (UI-Skalierung), Überschriften-Schrift und ein Hintergrundbild für die
        Gäste-Oberfläche. Änderungen gelten sofort und überleben Neustarts.</p>`,
    },
    {
        icon: '🔑', title: 'Mieter-Rechte',
        html: `<p>Für Untervermietung: ein <em>Organizer/Mieter</em> erhält Zugriff nur auf die hier freigegebenen
        Admin-Bereiche. Admin-only-Bereiche bleiben verborgen.</p>`,
    },
    {
        icon: '⚙️', title: 'System: Aktualisieren & Herunterfahren',
        html: `<p><strong>Software aktualisieren</strong> holt den neuesten Stand von GitHub und startet die Box
        neu — Schema-Migrationen laufen automatisch. <strong>Herunterfahren</strong> fährt die Box sauber herunter
        (warnt bei offenen Druckaufträgen).</p>
        <p>Beides braucht eine Berechtigung, die beim Einrichten (<code>setup.sh</code>) angelegt wird. Fehlt sie,
        meldet der Button „keine Berechtigung" — dann <code>setup.sh</code> erneut ausführen.</p>`,
    },
];

export async function render(container, state) {
    const sectionHtml = SECTIONS.map((s, i) => `
        <details class="help-card" ${i === 0 ? 'open' : ''}>
            <summary><span class="help-ico">${s.icon}</span> ${s.title}</summary>
            <div class="help-body">${s.html}</div>
        </details>`).join('');

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:0.5rem;">Hilfe &amp; Handbuch</h1>
        <p style="color:var(--pb-color-text-muted);max-width:720px;margin-bottom:1.25rem;font-size:0.9rem;">
            Kurzerklärungen zu allen Bereichen. Tippe auf einen Punkt zum Auf-/Zuklappen.
        </p>
        <div style="max-width:760px;">${sectionHtml}</div>
        <style>
            .help-card {
                background:var(--pb-color-surface);border:1px solid var(--pb-color-border);
                border-radius:var(--pb-radius);margin-bottom:0.6rem;overflow:hidden;
            }
            .help-card > summary {
                cursor:pointer;padding:0.9rem 1.1rem;font-weight:600;list-style:none;
                display:flex;align-items:center;gap:0.6rem;user-select:none;
            }
            .help-card > summary::-webkit-details-marker { display:none; }
            .help-card[open] > summary { border-bottom:1px solid var(--pb-color-border); }
            .help-ico { font-size:1.1rem; }
            .help-body { padding:0.5rem 1.1rem 1rem;font-size:0.9rem;line-height:1.55;color:var(--pb-color-text); }
            .help-body p { margin:0.5rem 0;color:var(--pb-color-text); }
            .help-body ul, .help-body ol { margin:0.4rem 0 0.4rem 1.1rem;padding:0; }
            .help-body li { margin:0.25rem 0; }
            .help-body code { background:rgba(0,0,0,0.25);padding:1px 5px;border-radius:5px;font-size:0.85em; }
            .help-body em { color:var(--pb-color-text-muted);font-style:normal; }
        </style>
    `);
    setupLogout(container);
}
