/**
 * Screenshots für README und docs/ — gesteuert von scripts/docs-screenshots.sh.
 *
 * Läuft im Container zenika/alpine-chrome:with-puppeteer gegen eine frische
 * Fotobox (eigene Datenbank, Browser-Kamera). Als „Kamera“ dient Chromiums
 * Test-Kamera, gefüttert mit einem Demo-Bild aus docs/media/demo (Datei .y4m) —
 * das Live-Bild, der Countdown und die Aufnahme sind also echt, nur der Gast
 * ist gezeichnet.
 *
 *   node docs-screenshots.js [phase ...]     Phasen: seed booth admin gallery
 *                                            (ohne Angabe: alle, in dieser Reihenfolge)
 * Umgebung:
 *   BASE   Adresse der Box            (Vorgabe http://pbdocs-app:8080)
 *   OUT    Zielordner für die PNGs    (Vorgabe /out)
 *   DEMO   Ordner mit demo1..8.jpg    (Vorgabe /demo)
 *   Y4M    Kamera-Video für Chromium  (Vorgabe /work/cam.y4m)
 */
const fs = require('fs');
const puppeteer = require('puppeteer');

const BASE = process.env.BASE || 'http://pbdocs-app:8080';
const OUT = process.env.OUT || '/out';
const DEMO = process.env.DEMO || '/demo';
const Y4M = process.env.Y4M || '/work/cam.y4m';
const API = BASE + '/api/v1';
const sleep = ms => new Promise(r => setTimeout(r, ms));

let token = null;
async function api(method, path, body, raw = false) {
    const headers = token ? { Authorization: 'Bearer ' + token } : {};
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const r = await fetch(API + path, { method, headers, body: payload });
    if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`);
    return raw ? r : r.json().catch(() => ({}));
}
async function login() {
    token = (await api('POST', '/auth/login', { username: 'admin', password: 'admin' })).token;
}
const setting = (key, value) => api('PUT', '/settings/' + key, { key, value });

// ── Demo-Inhalte ──────────────────────────────────────────────────────────
// Vorlagen: die mitgelieferten Demo-Vorlagen „Party“ (scripts/install-demo-template.py,
// ruft docs-screenshots.sh vorher auf). Passend dazu ist die Veranstaltung ein Geburtstag.
const EVENT = { name: 'Mias 30. Geburtstag', slug: 'mias-geburtstag',
    location_name: 'Gasthaus Zur Linde, Werder (Havel)', latitude: 52.3787, longitude: 12.9353,
    starts_at: '2026-11-07T18:00:00', ends_at: '2026-11-08T03:00:00' };
const TPL_SINGLE = 'Demo: Party';
const TPL_STRIP = 'Demo: Party-Streifen';

async function seed() {
    await login();
    // Veranstaltungen: die vorhandene Standard-Veranstaltung wird zu einer
    // früheren, der Geburtstag ist die aktive.
    await api('PUT', '/events/default', { name: 'Sommerfest Tennisclub',
        location_name: 'Vereinsheim TC Grün-Weiß', starts_at: '2026-08-22T14:00:00' });
    const events = await api('GET', '/events/');
    if (!events.find(e => e.slug === EVENT.slug)) await api('POST', '/events/', EVENT);
    await api('POST', `/events/${EVENT.slug}/activate`);

    const templates = (await api('GET', '/templates')).templates;
    const single = templates.find(t => t.name === TPL_SINGLE);
    const strip = templates.find(t => t.name === TPL_STRIP);
    if (!single || !strip) throw new Error('Demo-Vorlagen fehlen — erst scripts/install-demo-template.py');

    // Fotos „vom Abend“: Demo-Bild als Kamerabild hochladen, dann auslösen —
    // derselbe Weg wie im Booth. Die kurze Pause füllt den GIF-Puffer.
    const shoot = async (n, filter, part_of_set = false) => {
        const fd = new FormData();
        fd.append('file', new Blob([fs.readFileSync(`${DEMO}/demo${n}.jpg`)], { type: 'image/jpeg' }), 'frame.jpg');
        await api('POST', '/photos/upload', fd);
        await sleep(900);
        return (await api('POST', '/photos/capture', { filter, part_of_set })).id;
    };
    const render = (t, ids) => api('POST', '/templates/render', { template_id: t.id, photo_ids: ids });
    const already = await api('GET', `/gallery/${EVENT.slug}`);
    if (already.length) { console.log('seed: Fotos schon da, übersprungen'); return; }
    for (const [n, f] of [[4, 'warm'], [8, 'none'], [3, 'pop']]) await shoot(n, f);
    await render(single, [await shoot(6, 'none', true)]);
    await shoot(5, 'bw');
    const set = [];
    for (const [n, f] of [[2, 'vintage'], [7, 'vintage'], [4, 'vintage']]) set.push(await shoot(n, f, true));
    await render(strip, set);
    await shoot(7, 'cool');
    await render(single, [await shoot(2, 'none', true)]);
    await sleep(3000);   // GIFs entstehen im Hintergrund
    console.log('seed: fertig');
}

// ── Browser ───────────────────────────────────────────────────────────────
let browser;
async function newPage({ admin = false, expert = false } = {}) {
    const page = await browser.newPage();
    page.on('pageerror', e => console.log('PAGEERR', e.message));
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
    await page.goto(BASE + '/#/blank', { waitUntil: 'domcontentloaded' });
    await page.evaluate((t, ex) => {
        if (t) localStorage.setItem('pb_token', t); else localStorage.removeItem('pb_token');
        localStorage.setItem('pb_admin_mode', ex ? 'expert' : 'simple');
    }, admin ? token : null, expert);
    return page;
}
async function shot(page, name) {
    await page.screenshot({ path: `${OUT}/${name}.png` });
    console.log('  ' + name + '.png');
}
async function go(page, route, settle = 2000) {
    await page.goto(`${BASE}/?r=${Date.now()}#/${route}`, { waitUntil: 'domcontentloaded' });
    await sleep(settle);
}
async function clickCard(page, name) {      // Karte der Layout-Leiste nach Namen
    await page.evaluate(n => {
        const card = [...document.querySelectorAll('.lr-card')]
            .find(c => c.querySelector('strong').textContent.trim() === n);
        if (!card) throw new Error('Layout nicht gefunden: ' + n);
        card.click();
    }, name);
}
async function clickText(page, selector, text) {
    await page.evaluate((s, t) => {
        const el = [...document.querySelectorAll(s)].find(e => e.textContent.trim().includes(t));
        if (!el) throw new Error('nicht gefunden: ' + s + ' ' + t);
        el.click();
    }, selector, text);
}

async function boothShots() {
    await login();
    const page = await newPage();

    // Eigener Layout-Bildschirm (Einstellung „screen“), danach zurück auf die Leiste
    await setting('display.layout_picker', 'screen');
    await go(page, 'booth');
    await page.click('#btn-start');
    await page.waitForSelector('.tpl-card');
    await sleep(1500);
    await shot(page, 'booth-templates');
    await setting('display.layout_picker', 'auto');

    // Startbildschirm mit Layout-Leiste: Party-Rahmen gewählt, der Rahmen im
    // Live-Bild zeigt seinen Ausschnitt
    await go(page, 'booth', 3000);
    await clickCard(page, TPL_SINGLE);
    await sleep(1200);
    await shot(page, 'booth-idle');

    // Look „Sepia“ mit Einzelfoto
    await clickCard(page, 'Einzelfoto');
    await clickText(page, '#filter-bar button', 'Sepia');
    await sleep(1500);
    await shot(page, 'booth-looks');

    // Countdown
    await page.click('#btn-start');
    await sleep(1250);
    await shot(page, 'booth-countdown');

    // Ansehen
    await page.waitForSelector('#review-photo', { timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('#review-photo').complete);
    await sleep(1500);
    await shot(page, 'booth-review');

    // Gästebuch: Herz malen, Emoji, Grußwort
    await page.click('#btn-guestbook');
    await page.waitForSelector('#gb-canvas');
    await sleep(1200);
    await page.click('.gb-color[data-color="#ff4d6d"]');
    await page.click('.gb-size[data-size="10"]');
    const box = await page.$eval('#gb-canvas', c => { const r = c.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
    const cx = box.x + box.w * 0.5, cy = box.y + box.h * 0.17, s = box.h * 0.009;
    const pts = [];
    for (let t = 0; t <= Math.PI * 2 + 0.01; t += 0.05) {
        pts.push([cx + s * 16 * Math.sin(t) ** 3,
                  cy - s * (13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t))]);
    }
    await page.mouse.move(...pts[0]);
    await page.mouse.down();
    for (const p of pts) await page.mouse.move(p[0], p[1], { steps: 2 });
    await page.mouse.up();

    await page.click('#gb-emoji');
    await page.waitForSelector('.pb-emoji-picker .ep-search');
    // Werte per Skript setzen statt tippen: eine Leertaste würde sonst den
    // Tastatur-Auslöser des Startbildschirms erreichen.
    const typeInto = (sel, text) => page.evaluate((s, t) => {
        const el = document.querySelector(s); el.value = t;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }, sel, text);
    await typeInto('.pb-emoji-picker .ep-search', 'Party');
    await sleep(800);
    await page.evaluate(() => {
        const b = document.querySelector('.pb-emoji-picker .ep-emoji[data-e="🎉"]')
               || document.querySelector('.pb-emoji-picker .ep-emoji');
        b.click();
    });
    await sleep(800);
    // Sticker aus der Bildmitte nach oben rechts ziehen und etwas drehen
    const st = await page.$eval('#gb-stickers > div:last-child', e => {
        const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await page.mouse.move(st.x, st.y);
    await page.mouse.down();
    await page.mouse.move(box.x + box.w * 0.82, box.y + box.h * 0.24, { steps: 12 });
    await page.mouse.up();
    await page.click('.gb-st[data-act="right"]');
    await sleep(500);
    await typeInto('#gb-message', 'Alles Liebe, Mia! Ben & Sophie');
    await sleep(1000);
    await shot(page, 'booth-guestbook');
    await page.click('#gb-save');
    await sleep(4000);
    await page.close();
}

async function adminShots() {
    await login();
    // Einfacher Modus — so sieht ein neuer Betreiber den Admin-Bereich
    let page = await newPage({ admin: true });
    await go(page, 'admin/dashboard', 3000); await shot(page, 'admin-dashboard');
    await go(page, 'admin/events', 2500); await shot(page, 'admin-events');
    await go(page, 'admin/templates', 3000); await shot(page, 'admin-templates');
    await go(page, 'admin/help', 2500); await shot(page, 'admin-help');
    await page.close();

    // Expertenmodus: volles Menü; Kameras mit Bild-Transformation und Spiegel-Effekt
    page = await newPage({ admin: true, expert: true });
    await go(page, 'admin/dashboard', 3000); await shot(page, 'admin-expert');
    await go(page, 'admin/cameras', 3000);
    await page.evaluate(() => {
        const h = [...document.querySelectorAll('.admin-card h3')].find(e => e.textContent.includes('Vorschau-Kamera'));
        h.closest('.admin-card').scrollIntoView({ block: 'start' });
    });
    await sleep(800);
    await shot(page, 'admin-cameras');
    await page.close();
}

async function galleryShots() {
    const page = await newPage();
    await go(page, 'gallery', 4000);
    await shot(page, 'gallery');
    await page.close();
}

(async () => {
    const phases = process.argv.slice(2);
    const want = p => !phases.length || phases.includes(p);
    if (want('seed')) await seed();
    browser = await puppeteer.launch({
        executablePath: '/usr/bin/chromium-browser', headless: 'new',
        args: ['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
               '--use-file-for-fake-video-capture=' + Y4M, '--autoplay-policy=no-user-gesture-required',
               '--unsafely-treat-insecure-origin-as-secure=' + BASE, '--lang=de-DE'],
    });
    try {
        if (want('booth')) await boothShots();
        if (want('admin')) await adminShots();
        if (want('gallery')) await galleryShots();
    } finally {
        await browser.close();
    }
})().catch(e => { console.error(e); process.exit(1); });
