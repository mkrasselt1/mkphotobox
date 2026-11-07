/**
 * Admin Shell — Sidebar + content area. Used by all admin sub-pages.
 */

// Sicherer Rand (display.safe_margin) auch im Admin-Bereich — aber nur auf dem
// Kiosk-Bildschirm selbst (der Browser dort öffnet localhost). Am Handy oder
// Laptop gibt es keinen Rahmen, der etwas verdeckt, also keinen Rand.
let kioskMargin = 0;      // zuletzt bekannter Wert — sofort angewendet, dann aufgefrischt
function isKioskScreen() {
    return ['localhost', '127.0.0.1', '::1'].includes(location.hostname);
}
function marginStyle(m) {
    return m ? `margin:${m}px;width:calc(100% - ${2 * m}px);height:calc(100% - ${2 * m}px);`
             : 'height:100%;';
}
function loadKioskMargin() {
    if (!isKioskScreen()) return;
    // Bei jedem Seitenaufbau neu holen: wer den Rand unter Einstellungen
    // ändert, sieht ihn auf der nächsten Seite, nicht erst nach Neuladen.
    fetch('/api/v1/display/config').then(r => r.json()).then(d => {
        kioskMargin = Math.max(0, Math.min(200, Number(d.safe_margin) | 0));
        const root = document.getElementById('admin-root');
        if (root) root.style.cssText += marginStyle(kioskMargin);
    }).catch(() => {});
}

// ── Einfach / Experte ────────────────────────────────────────────────────
// Pro Gerät gemerkt (localStorage), Vorgabe „einfach". Der Modus blendet nur
// aus — er sperrt nichts: jede Seite bleibt per Link erreichbar, die Rechte
// (Admin / Mieter-Bereiche) entscheiden weiterhin allein Router und Backend.
const MODE_KEY = 'pb_admin_mode';
let expertMode = null;          // null = noch nicht gelesen
export function isExpertMode() {
    if (expertMode === null) {
        try { expertMode = localStorage.getItem(MODE_KEY) === 'expert'; } catch { expertMode = false; }
    }
    return expertMode;
}
function setExpertMode(on) {
    expertMode = !!on;
    try { localStorage.setItem(MODE_KEY, on ? 'expert' : 'simple'); } catch { /* privater Modus */ }
    applyModeClass();
}
// Klasse am <html>, nicht am Admin-Root: so greift data-level="expert" auch in
// Dialogen, die Seiten an document.body hängen. Außerhalb des Admins ist die
// zugehörige CSS-Regel (im Shell-<style>) nicht im Dokument — die Klasse stört dort nicht.
function applyModeClass() {
    document.documentElement.classList.toggle('pb-admin-simple', !isExpertMode());
}

// Menü. key = Bereichsschlüssel (wie MIETER_SECTIONS im Backend) — davon hängen die
// Mieter-Rechte ab, also nie umbenennen. adminOnly blendet den Punkt für Mieter aus.
// level 'expert' = nur im Expertenmodus im Menü (für Admins; Mieter sehen immer alles
// Freigegebene — die Freigabe ist schon die Auswahl).
// Reihenfolge = Reihenfolge beim Einrichten einer Veranstaltung, Häufiges zuerst.
const NAV_ITEMS = [
    { key: 'dashboard', href: '#/admin/dashboard', label: 'Dashboard', icon: '📊', group: 'top' },
    // 1 – 6: der Ablauf für eine Veranstaltung
    { key: 'events', href: '#/admin/events', label: 'Veranstaltungen', icon: '🎉', group: 'event' },
    { key: 'assets', href: '#/admin/assets', label: 'Bilder & Logos', icon: '🖼️', group: 'images' },
    { key: 'templates', href: '#/admin/templates', label: 'Foto-Vorlagen', icon: '🧱', group: 'layouts' },
    { key: 'presets', href: '#/admin/presets', label: 'Ausgabe-Formate', icon: '📐', group: 'layouts', level: 'expert' },
    { key: 'appearance', href: '#/admin/appearance', label: 'Booth-Design', icon: '🎨', group: 'layouts', adminOnly: true, level: 'expert' },
    { key: 'cameras', href: '#/admin/cameras', label: 'Kameras', icon: '📷', group: 'capture' },
    { key: 'background', href: '#/admin/background', label: 'Hintergrund', icon: '🪄', group: 'capture', level: 'expert' },
    { key: 'triggers', href: '#/admin/triggers', label: 'Auslöser', icon: '⚡', group: 'capture', adminOnly: true, level: 'expert' },
    { key: 'printer', href: '#/admin/printer', label: 'Drucker', icon: '🖨️', group: 'output' },
    { key: 'remote-gallery', href: '#/admin/remote-gallery', label: 'Online-Galerie', icon: '☁️', group: 'output', adminOnly: true, level: 'expert' },
    { key: 'wifi', href: '#/admin/wifi', label: 'WLAN verbinden', icon: '📶', group: 'onsite' },
    { key: 'usb-export', href: '#/admin/usb-export', label: 'Auf USB kopieren', icon: '🔌', group: 'onsite' },
    { key: 'cd-burn', href: '#/admin/cd-burn', label: 'CD/DVD brennen', icon: '💿', group: 'onsite', level: 'expert' },
    { key: 'telegram', href: '#/admin/telegram', label: 'Telegram-Bot', icon: '📨', group: 'onsite', adminOnly: true, level: 'expert' },
    // Seltener: einmal einrichten, dann in Ruhe lassen
    { key: 'settings', href: '#/admin/settings', label: 'Einstellungen', icon: '⚙️', group: 'system', adminOnly: true },
    { key: 'modules', href: '#/admin/modules', label: 'Module', icon: '🧩', group: 'system', adminOnly: true, level: 'expert' },
    { key: 'tests', href: '#/admin/tests', label: 'Tests', icon: '🧪', group: 'system', adminOnly: true, level: 'expert' },
    { key: 'network', href: '#/admin/network', label: 'Netzwerk & Tailscale', icon: '🌐', group: 'network', adminOnly: true, level: 'expert' },
    { key: 'bluetooth', href: '#/admin/bluetooth', label: 'Bluetooth', icon: '🔵', group: 'network', level: 'expert' },
    { key: 'permissions', href: '#/admin/permissions', label: 'Mieter-Rechte', icon: '🔑', group: 'rental', adminOnly: true, level: 'expert' },
    { key: 'payment', href: '#/admin/payment', label: 'Bezahlung', icon: '💳', group: 'rental', adminOnly: true, level: 'expert' },
    { key: 'help', href: '#/admin/help', label: 'Hilfe', icon: '❓', group: 'end', adminOnly: true },
];

// step = Nummer im Ablauf (wird beim Anzeigen fortlaufend vergeben, damit ein
// Mieter mit wenigen Bereichen keine Lücken sieht).
const GROUPS = [
    { id: 'event', label: 'Veranstaltung', icon: '🎉', step: true },
    { id: 'images', label: 'Bilder & Logos', icon: '🖼️', step: true },
    { id: 'layouts', label: 'Layouts', icon: '🗂️', step: true },
    { id: 'capture', label: 'Aufnahme', icon: '🎬', step: true },
    { id: 'output', label: 'Drucken & Teilen', icon: '📤', step: true },
    { id: 'onsite', label: 'Vor Ort & danach', icon: '📍', step: true },
    { id: 'system', label: 'System' },
    { id: 'network', label: 'Netzwerk & Funk' },
    { id: 'rental', label: 'Vermietung & Bezahlung' },
];

function currentRoute() {
    const hash = location.hash.replace('#/', '');
    return hash === 'admin' ? 'admin/dashboard' : hash;
}

/** Alle Punkte, die diese Rolle überhaupt sehen darf (ohne Modus-Filter). */
function permittedItems() {
    const auth = (window.pb && window.pb.state && window.pb.state.auth) || {};
    if (auth.role === 'admin') return NAV_ITEMS;
    // Mieter: nur freigegebene, nicht-admin-only Bereiche — wie bisher
    const sections = auth.sections || [];
    return NAV_ITEMS.filter(n => !n.adminOnly && sections.includes(n.key));
}

function currentItem() {
    const route = currentRoute();
    return NAV_ITEMS.find(n => n.href.replace('#/', '') === route) || null;
}

/** Ist die aktuelle Seite eine, die im einfachen Modus nicht im Menü steht? */
function currentPageIsExpert() {
    const auth = window.pb.state.auth || {};
    const item = currentItem();
    return auth.role === 'admin' && !!item && item.level === 'expert';
}

/** Menü-Liste (ohne Kopf und Fußleiste) — wird beim Umschalten neu gezeichnet. */
function navListHtml() {
    const auth = window.pb.state.auth || {};
    const route = currentRoute();
    let items = permittedItems();
    if (auth.role === 'admin' && !isExpertMode()) items = items.filter(n => n.level !== 'expert');

    const isActive = (n) => route === n.href.replace('#/', '');
    const stepBadge = (num) => num ? `<span class="nav-step">${num}</span>` : '';
    const itemHtml = (n, num) => `
        <a href="${n.href}" class="nav-item ${isActive(n) ? 'active' : ''}">
            ${stepBadge(num)}<span class="nav-icon">${n.icon}</span><span>${n.label}</span>
        </a>`;

    // Einklappbare Gruppen: alles auf einmal wäre höher als der Box-Bildschirm,
    // also ist nur eine Gruppe offen — die mit der aktuellen Seite, sonst die
    // zuletzt geöffnete. Eine Gruppe mit nur einem sichtbaren Punkt braucht keine
    // Überschrift: der Punkt steht direkt da (spart einen Tipp und eine Zeile).
    const multi = GROUPS.filter(g => items.filter(n => n.group === g.id).length > 1).map(g => g.id);
    const activeGroup = (items.find(isActive) || {}).group;
    let openGroup = multi.includes(activeGroup) ? activeGroup : null;
    if (!openGroup) {
        try { openGroup = localStorage.getItem('pb_nav_group'); } catch { openGroup = null; }
    }
    if (!multi.includes(openGroup)) openGroup = null;

    let html = items.filter(n => n.group === 'top').map(n => itemHtml(n)).join('');
    let step = 0;
    let sepDone = false;
    for (const g of GROUPS) {
        const gi = items.filter(n => n.group === g.id);
        if (!gi.length) continue;
        const num = g.step ? ++step : 0;
        if (!g.step && !sepDone) { html += '<div class="nav-sep"></div>'; sepDone = true; }
        if (gi.length === 1) { html += itemHtml(gi[0], num); continue; }
        const open = g.id === openGroup;
        html += `
        <button type="button" class="nav-group ${g.step ? 'nav-group-step' : ''}" data-group="${g.id}" aria-expanded="${open}">
            <span class="nav-group-label">${stepBadge(num)}${g.icon ? `<span class="nav-icon">${g.icon}</span>` : ''}<span>${g.label}</span></span><span class="nav-chevron">${open ? '▾' : '▸'}</span>
        </button>
        <div class="nav-group-items" data-group-items="${g.id}" ${open ? '' : 'hidden'}>
            ${gi.map(n => itemHtml(n)).join('')}
        </div>`;
    }
    html += items.filter(n => n.group === 'end').map(n => itemHtml(n)).join('');
    return html;
}

function modeSwitchHtml() {
    const expert = isExpertMode();
    return `
    <div class="nav-mode" role="group" aria-label="Menü-Umfang">
        <button type="button" class="nav-mode-btn ${expert ? '' : 'on'}" data-mode="simple" aria-pressed="${!expert}"
            title="Nur das Wichtigste zeigen"><span class="nav-mode-ico">🐒</span><span>Einfach</span></button>
        <button type="button" class="nav-mode-btn ${expert ? 'on' : ''}" data-mode="expert" aria-pressed="${expert}"
            title="Alle Bereiche und Optionen zeigen"><span class="nav-mode-ico">👷</span><span>Experte</span></button>
    </div>`;
}

export function adminShell(contentHTML) {
    const { i18n } = window.pb;
    loadKioskMargin();
    applyModeClass();
    const auth = window.pb.state.auth || {};
    const isAdmin = auth.role === 'admin';

    // Hinweise oben auf der Seite — nur im einfachen Modus sichtbar (pb-only-simple),
    // so verschwinden sie beim Umschalten ohne Neuzeichnen.
    const pageHint = currentPageIsExpert()
        ? `<div class="admin-mode-hint pb-only-simple">👷 Experten-Seite — im einfachen Modus steht sie nicht im Menü.
               <button type="button" class="admin-mode-link" data-set-mode="expert">Expertenmodus einschalten</button></div>`
        : contentHTML.includes('data-level="expert"')
            ? `<div class="admin-mode-hint admin-mode-hint-quiet pb-only-simple">🐒 Einfacher Modus — Experten-Optionen sind ausgeblendet.
                   <button type="button" class="admin-mode-link" data-set-mode="expert">Alle zeigen</button></div>`
            : '';

    return `
    <div id="admin-root" style="display:flex;box-sizing:border-box;${marginStyle(kioskMargin || 0)}">
        <nav class="admin-nav">
            <div class="admin-nav-head">
                <div class="admin-brand"><span class="admin-brand-dot"></span> Photobox Admin</div>
                <button type="button" class="nav-burger" aria-expanded="false" aria-label="Menü öffnen">
                    <span>${(currentItem() || {}).label || 'Menü'}</span><span class="nav-burger-ico">☰</span>
                </button>
            </div>
            <div class="nav-list" id="nav-list">${navListHtml()}</div>
            <div style="flex:1;"></div>
            ${modeSwitchHtml()}
            <a href="#/booth" class="nav-item nav-muted"><span class="nav-icon">↩️</span><span>Zum Booth</span></a>
            ${isAdmin ? '<a href="#" class="nav-item" id="btn-update" data-level="expert"><span class="nav-icon">⬆️</span><span>Software aktualisieren</span></a>' : ''}
            ${isAdmin ? '<a href="#" class="nav-item" id="btn-mode" data-level="expert"><span class="nav-icon">🖥️</span><span>Anzeigemodus</span></a>' : ''}
            <a href="#/booth" class="nav-item nav-danger" id="btn-logout"><span class="nav-icon">🚪</span><span>${i18n.t('auth.logout')}</span></a>
            ${isAdmin ? '<a href="#" class="nav-item nav-danger" id="btn-shutdown"><span class="nav-icon">⏻</span><span>Herunterfahren</span></a>' : ''}
        </nav>
        <main style="flex:1;padding:2rem;overflow-y:auto;min-width:0;">
            ${pageHint}
            ${contentHTML}
        </main>
    </div>
    <style>
        /* Einfach/Experte: Elemente mit data-level="expert" sind im einfachen Modus weg.
           !important, weil Seiten display oft per JS/Inline-Style setzen. */
        html.pb-admin-simple [data-level="expert"] { display:none !important; }
        html:not(.pb-admin-simple) .pb-only-simple { display:none !important; }
        .admin-nav {
            width:240px;background:linear-gradient(180deg, var(--pb-color-surface) 0%, var(--pb-color-background) 100%);
            padding:1rem 0.75rem;display:flex;flex-direction:column;gap:0.15rem;overflow-y:auto;flex-shrink:0;
            border-right:1px solid var(--pb-color-border);
        }
        .nav-list { display:flex;flex-direction:column;gap:0.15rem; }
        .admin-brand {
            display:flex;align-items:center;gap:0.5rem;font-size:1.15rem;font-weight:700;
            padding:0.5rem 0.75rem 1rem;letter-spacing:0.2px;
        }
        .admin-brand-dot { width:12px;height:12px;border-radius:50%;background:var(--pb-gradient);box-shadow:0 0 12px var(--pb-color-primary); }
        .nav-item {
            display:flex;align-items:center;gap:0.7rem;padding:0.65rem 0.85rem;border-radius:10px;
            color:var(--pb-color-text);text-decoration:none;font-size:0.93rem;
            transition:background 0.15s, transform 0.05s;position:relative;
        }
        .nav-group {
            display:flex;align-items:center;justify-content:space-between;width:100%;
            font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;
            color:var(--pb-color-text-muted);padding:0.7rem 0.85rem 0.35rem;opacity:0.8;
            background:none;border:none;cursor:pointer;font-family:inherit;text-align:left;
        }
        .nav-group:hover { opacity:1; }
        .nav-group-label { display:flex;align-items:center;gap:0.5rem; }
        /* Schritt-Gruppen (1–6) sehen aus wie Menüpunkte — sie sind ja Teil des Ablaufs */
        .nav-group-step {
            font-size:0.93rem;font-weight:400;text-transform:none;letter-spacing:0;opacity:1;
            color:var(--pb-color-text);padding:0.65rem 0.85rem;border-radius:10px;
        }
        .nav-group-step .nav-group-label { gap:0.7rem; }
        .nav-group-step .nav-step { margin-right:-0.3rem; }
        .nav-group-step:hover { background:rgba(255,255,255,0.07); }
        .nav-group-step[aria-expanded="true"] + .nav-group-items { padding-left:1.1rem; }
        /* Box-Bildschirm (768 px hoch, dazu sicherer Rand): Zeilen etwas dichter,
           damit das Menü möglichst ohne Scrollen passt. Tippfläche bleibt ≥ 36 px. */
        /* Handy: Menü oben als aufklappbare Leiste statt fester 240-px-Spalte */
        .admin-nav-head { display:flex;align-items:center;justify-content:space-between;gap:0.5rem; }
        .nav-burger { display:none; }
        @media (max-width: 700px) {
            #admin-root { flex-direction:column; }
            .admin-nav {
                width:auto;max-height:none;overflow:visible;padding:0.5rem 0.75rem;
                border-right:none;border-bottom:1px solid var(--pb-color-border);
            }
            .admin-nav.nav-open { max-height:75vh;overflow-y:auto; }
            .admin-nav:not(.nav-open) > :not(.admin-nav-head) { display:none !important; }
            .admin-nav > div[style*="flex:1"] { display:none !important; }
            .admin-brand { padding:0.25rem 0.25rem;font-size:1rem; }
            .nav-burger {
                display:flex;align-items:center;gap:0.5rem;padding:0.5rem 0.8rem;border-radius:10px;
                border:1px solid var(--pb-color-border);background:rgba(255,255,255,0.05);
                color:var(--pb-color-text);font-family:inherit;font-size:0.9rem;cursor:pointer;
                max-width:60%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;
            }
            .nav-burger-ico { font-size:1.1rem; }
            #admin-root > main { padding:1rem !important;flex:1; }
        }
        @media (max-height: 820px) {
            .admin-brand { padding:0.25rem 0.75rem 0.5rem; }
            .nav-item, .nav-group-step { padding:0.5rem 0.85rem; }
            .nav-group:not(.nav-group-step) { padding:0.5rem 0.85rem 0.3rem; }
            .nav-mode { margin:0.35rem 0 0.2rem; }
            .nav-mode-btn { padding:0.4rem; }
        }
        .nav-chevron { font-size:0.85rem;line-height:1; }
        .nav-group-items { display:flex;flex-direction:column;gap:0.15rem; }
        .nav-group-items[hidden] { display:none; }
        .nav-step {
            display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;
            width:1.15rem;height:1.15rem;border-radius:50%;font-size:0.68rem;font-weight:700;letter-spacing:0;
            border:1.5px solid var(--pb-color-primary);color:var(--pb-color-primary);
        }
        .nav-item .nav-step { margin-right:-0.3rem; }
        .nav-item.active .nav-step { border-color:#fff;color:#fff; }
        .nav-sep { height:1px;background:var(--pb-color-border);margin:0.5rem 0.85rem; }
        .nav-icon { width:1.4rem;text-align:center;font-size:1.05rem;flex-shrink:0; }
        .nav-item:hover { background:rgba(255,255,255,0.07); }
        .nav-item:active { transform:scale(0.98); }
        .nav-item.active { background:var(--pb-gradient);color:#fff;box-shadow:var(--pb-shadow-sm); }
        .nav-muted { color:var(--pb-color-text-muted); }
        .nav-danger { color:var(--pb-color-error); }
        .nav-mode {
            display:flex;gap:0.25rem;padding:0.25rem;margin:0.5rem 0 0.35rem;border-radius:12px;
            background:rgba(0,0,0,0.2);border:1px solid var(--pb-color-border);
        }
        .nav-mode-btn {
            flex:1;display:flex;align-items:center;justify-content:center;gap:0.35rem;
            padding:0.5rem 0.4rem;border:none;border-radius:9px;background:none;cursor:pointer;
            color:var(--pb-color-text-muted);font-family:inherit;font-size:0.85rem;font-weight:600;
        }
        .nav-mode-btn.on { background:var(--pb-gradient);color:#fff;box-shadow:var(--pb-shadow-sm); }
        .nav-mode-ico { font-size:1.15rem;line-height:1; }
        .admin-mode-hint {
            display:flex;align-items:center;flex-wrap:wrap;gap:0.4rem 0.75rem;max-width:680px;
            margin:-0.75rem 0 1.25rem;padding:0.55rem 0.85rem;border-radius:10px;font-size:0.85rem;
            background:rgba(108,140,255,0.10);border:1px solid var(--pb-color-border);color:var(--pb-color-text);
        }
        .admin-mode-hint-quiet { background:none;color:var(--pb-color-text-muted); }
        .admin-mode-link {
            background:none;border:none;padding:0;cursor:pointer;font:inherit;font-weight:600;
            color:var(--pb-color-primary);text-decoration:underline;
        }
        .admin-card {
            background:var(--pb-color-surface);border:1px solid var(--pb-color-border);
            border-radius:var(--pb-radius);padding:1.25rem;margin-bottom:1rem;box-shadow:var(--pb-shadow-sm);
        }
        .admin-card h3 { margin-bottom:0.75rem;font-size:1rem;color:var(--pb-color-primary); }
        .admin-card p { font-size:0.9rem;margin-bottom:0.25rem;color:var(--pb-color-text-muted); }
        .admin-btn {
            padding:0.6rem 1.2rem;border-radius:10px;border:none;font-size:0.9rem;font-weight:600;
            cursor:pointer;color:white;transition:filter 0.15s, transform 0.05s, background 0.15s;
        }
        .admin-btn:hover { filter:brightness(1.08); }
        .admin-btn:active { transform:scale(0.97); }
        .admin-btn-primary { background:var(--pb-gradient);box-shadow:0 4px 14px rgba(108,140,255,0.35); }
        .admin-btn-outline {
            background:rgba(108,140,255,0.10);border:1.5px solid var(--pb-color-primary);color:var(--pb-color-text);
        }
        .admin-btn-outline:hover { background:rgba(108,140,255,0.22); }
        .admin-input {
            padding:0.6rem 0.7rem;border-radius:10px;border:1px solid var(--pb-color-border);
            background:rgba(0,0,0,0.25);color:var(--pb-color-text);font-size:0.9rem;transition:border-color 0.15s;
        }
        .admin-input:focus { border-color:var(--pb-color-primary);outline:none; }
        h1 { font-weight:700;letter-spacing:0.2px; }
    </style>`;
}

export function getHeaders() {
    const token = window.pb.state.auth.token;
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

/** Wire the collapsible nav groups and the Einfach/Experte switch. Called from
 *  setupLogout so every admin page gets it without each one having to remember. */
export function setupNav(container) {
    const list = container.querySelector('#nav-list');
    // Delegiert: die Liste wird beim Umschalten neu gezeichnet, die Handler bleiben.
    list?.addEventListener('click', (e) => {
        const btn = e.target.closest('.nav-group');
        if (!btn) return;
        const id = btn.dataset.group;
        const items = list.querySelector(`[data-group-items="${id}"]`);
        if (!items) return;
        const open = items.hasAttribute('hidden');
        // One group at a time — that is what keeps the nav on one screen.
        list.querySelectorAll('[data-group-items]').forEach(el => el.setAttribute('hidden', ''));
        list.querySelectorAll('.nav-group').forEach(b => {
            b.setAttribute('aria-expanded', 'false');
            b.querySelector('.nav-chevron').textContent = '▸';
        });
        if (open) {
            items.removeAttribute('hidden');
            btn.setAttribute('aria-expanded', 'true');
            btn.querySelector('.nav-chevron').textContent = '▾';
            try { localStorage.setItem('pb_nav_group', id); } catch { /* private mode */ }
        }
    });

    // Umschalten zeichnet nur das Menü neu und setzt die Klasse — die Seite selbst
    // bleibt stehen, halb ausgefüllte Formulare gehen nicht verloren.
    const switchTo = (expert) => {
        setExpertMode(expert);
        if (list) list.innerHTML = navListHtml();
        container.querySelectorAll('.nav-mode-btn').forEach(b => {
            const on = (b.dataset.mode === 'expert') === expert;
            b.classList.toggle('on', on);
            b.setAttribute('aria-pressed', String(on));
        });
    };
    container.querySelectorAll('.nav-mode-btn').forEach(b =>
        b.addEventListener('click', () => switchTo(b.dataset.mode === 'expert')));
    container.querySelectorAll('[data-set-mode]').forEach(b =>
        b.addEventListener('click', () => switchTo(b.dataset.setMode === 'expert')));

    // Handy: Menü auf-/zuklappen (am Desktop ist der Knopf unsichtbar)
    const burger = container.querySelector('.nav-burger');
    burger?.addEventListener('click', () => {
        const nav = container.querySelector('.admin-nav');
        const open = nav.classList.toggle('nav-open');
        burger.setAttribute('aria-expanded', String(open));
    });
}

export function setupLogout(container) {
    setupNav(container);

    container.querySelector('#btn-logout')?.addEventListener('click', (e) => {
        e.preventDefault();
        window.pb.state.clearAuth();
        window.pb.router.navigate('booth');
    });

    container.querySelector('#btn-update')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const h = getHeaders();
        let info = { is_git: true, head: '', can_restart: true };
        try { info = await fetch('/api/v1/system/update-check', { headers: h }).then(r => r.json()); } catch {}
        const o = document.createElement('div');
        o.id = 'pb-update';
        o.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:480px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
            <h2 style="margin:0 0 0.75rem;">Software aktualisieren</h2>
            ${info.is_git
                ? `<p style="color:var(--pb-color-text-muted);font-size:0.9rem;margin:0;">Holt die neueste Version von GitHub und startet die Box-Software neu.</p>
                   <p style="font-size:0.82rem;color:var(--pb-color-text-muted);margin:0.5rem 0 0;">Aktuell: <code>${info.head || '—'}</code></p>
                   ${info.can_restart ? '' : '<p style="color:var(--pb-color-error);font-size:0.85rem;margin:0.5rem 0 0;">⚠️ Neustart nicht erlaubt (sudoers-Regel fehlt) — Update wird geladen, Dienst muss manuell neu starten.</p>'}`
                : '<p style="color:var(--pb-color-error);margin:0;">Kein git-Repo auf der Box — Update nur über SSH (scripts/update.sh).</p>'}
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:1.25rem;">
                <button id="up-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                ${info.is_git ? '<button id="up-go" class="admin-btn admin-btn-primary">Jetzt aktualisieren</button>' : ''}
            </div>
            <p id="up-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
        </div>`;
        document.body.appendChild(o);
        o.querySelector('#up-cancel').addEventListener('click', () => o.remove());
        o.querySelector('#up-go')?.addEventListener('click', async () => {
            const msg = o.querySelector('#up-msg');
            const go = o.querySelector('#up-go');
            go.disabled = true; msg.style.color = 'var(--pb-color-text-muted)'; msg.textContent = 'Lade Update…';
            try {
                const res = await fetch('/api/v1/system/update', { method: 'POST', headers: h });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                if (!r.changed) {
                    msg.style.color = 'var(--pb-color-success)';
                    msg.textContent = '✓ Bereits aktuell (' + (r.head || r.after) + ')';
                    go.disabled = false;
                    return;
                }
                if (r.status === 'updated_no_restart') {
                    msg.style.color = 'var(--pb-color-error)';
                    msg.textContent = r.message;
                    return;
                }
                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = `✓ Aktualisiert auf ${r.after}. Starte neu…`;
                // poll until the service is back, then reload
                let tries = 0;
                const poll = setInterval(async () => {
                    tries++;
                    try {
                        const ok = await fetch('/api/v1/system/update-check', { headers: h });
                        if (ok.ok) { clearInterval(poll); msg.textContent = '✓ Neu gestartet — lade neu…'; setTimeout(() => location.reload(), 800); }
                    } catch {}
                    if (tries > 30) { clearInterval(poll); msg.textContent = 'Neustart dauert — bitte Seite manuell neu laden.'; }
                }, 1500);
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
                go.disabled = false;
            }
        });
    });

    container.querySelector('#btn-mode')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const h = getHeaders();
        let info = { mode: 'unknown', kiosk_ready: false, desktop_ready: false, can_switch: false };
        try { info = await fetch('/api/v1/system/mode', { headers: h }).then(r => r.json()); } catch {}

        const MODES = {
            kiosk: {
                label: 'Fotobox', icon: '📸',
                desc: 'Startet automatisch in den Vollbild-Browser. Kein Anmeldebildschirm, keine Fenster — das ist der Betriebsmodus für die Veranstaltung.',
                ready: info.kiosk_ready,
                missing: 'Auf dieser Box noch nicht eingerichtet — einmalig <code>sudo ./scripts/kiosk-setup.sh</code> über SSH ausführen.',
            },
            desktop: {
                label: 'Desktop', icon: '🖥️',
                desc: 'Normaler Anmeldebildschirm mit Schreibtisch. Zum Einrichten, Warten und Debuggen. Die Box-Software läuft weiter und ist unter localhost:8080 erreichbar.',
                ready: info.desktop_ready,
                missing: 'Kein Anmeldebildschirm installiert — <code>sudo apt install gdm3</code>.',
            },
        };
        const current = MODES[info.mode];

        const card = (key) => {
            const m = MODES[key];
            const isCurrent = info.mode === key;
            return `<div style="border:1px solid ${isCurrent ? 'var(--pb-color-primary,#6c8cff)' : 'var(--pb-color-border,#2a3a5e)'};border-radius:12px;padding:0.9rem 1rem;margin-top:0.75rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span style="font-size:1.2rem;">${m.icon}</span>
                    <strong>${m.label}</strong>
                    ${isCurrent ? '<span style="margin-left:auto;font-size:0.78rem;color:var(--pb-color-success);">● aktiv</span>' : ''}
                </div>
                <p style="margin:0.4rem 0 0;font-size:0.86rem;color:var(--pb-color-text-muted);">${m.desc}</p>
                ${m.ready ? '' : `<p style="margin:0.4rem 0 0;font-size:0.82rem;color:var(--pb-color-error);">⚠️ ${m.missing}</p>`}
                ${isCurrent || !m.ready || !info.can_switch ? '' :
                    `<button class="admin-btn admin-btn-primary md-switch" data-mode="${key}" style="margin-top:0.7rem;">Auf „${m.label}" umschalten</button>`}
            </div>`;
        };

        const o = document.createElement('div');
        o.id = 'pb-mode';
        o.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:520px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
            <h2 style="margin:0 0 0.25rem;">Anzeigemodus</h2>
            <p style="margin:0;font-size:0.9rem;color:var(--pb-color-text-muted);">
                Aktuell: <strong>${current ? current.label : 'unbekannt'}</strong>${info.dm ? ` <code style="font-size:0.8rem;">(${info.dm})</code>` : ''}
            </p>
            ${info.can_switch ? '' : `<p style="margin:0.6rem 0 0;font-size:0.85rem;color:var(--pb-color-error);">⚠️ Umschalten ist nicht erlaubt${info.installed ? ' (sudoers-Regel fehlt)' : ' (Umschalter nicht installiert)'} — einmalig <code>sudo ./scripts/setup.sh</code> ausführen.</p>`}
            ${card('kiosk')}
            ${card('desktop')}
            <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;font-size:0.88rem;">
                <input type="checkbox" id="md-reboot" checked> Direkt neu starten (sonst beim nächsten Einschalten)
            </label>
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:1.25rem;">
                <button id="md-cancel" class="admin-btn admin-btn-outline">Schließen</button>
            </div>
            <p id="md-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
        </div>`;
        document.body.appendChild(o);
        o.querySelector('#md-cancel').addEventListener('click', () => o.remove());

        o.querySelectorAll('.md-switch').forEach(btn => btn.addEventListener('click', async () => {
            const mode = btn.dataset.mode;
            const reboot = o.querySelector('#md-reboot').checked;
            const msg = o.querySelector('#md-msg');
            o.querySelectorAll('button, input').forEach(b => b.disabled = true);
            msg.style.color = 'var(--pb-color-text-muted)';
            msg.textContent = 'Schalte um…';
            try {
                const res = await fetch('/api/v1/system/mode', {
                    method: 'POST', headers: h, body: JSON.stringify({ mode, reboot }),
                });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = r.rebooting
                    ? `✓ Umgeschaltet auf „${MODES[mode].label}" — Box startet neu…`
                    : `✓ Umgeschaltet auf „${MODES[mode].label}" — aktiv beim nächsten Neustart.`;
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
                o.querySelectorAll('button, input').forEach(b => b.disabled = false);
            }
        }));
    });

    container.querySelector('#btn-shutdown')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const h = getHeaders();
        let check = { pending_jobs: 0 };
        try { check = await fetch('/api/v1/system/shutdown-check', { headers: h }).then(r => r.json()); } catch {}
        const pending = check.pending_jobs || 0;
        const status = pending > 0
            ? `<p style="color:var(--pb-color-error);margin:0;">⚠️ ${pending} offene(r) Druckauftrag/-aufträge — bitte erst fertig drucken lassen.</p>`
            : `<p style="color:var(--pb-color-success);margin:0;">✓ Keine offenen Druckaufträge.</p>`;
        const o = document.createElement('div');
        o.id = 'pb-shutdown';
        o.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:460px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
            <h2 style="margin:0 0 0.75rem;">Box herunterfahren oder neu starten?</h2>
            ${status}
            <p style="color:var(--pb-color-text-muted);font-size:0.9rem;margin:0.5rem 0 0;"><strong>Herunterfahren:</strong> Box wird ausgeschaltet (zum Einschalten den Power-Knopf drücken). <strong>Neustarten:</strong> Box startet neu und ist gleich wieder da.</p>
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;flex-wrap:wrap;margin-top:1.25rem;">
                <button id="sd-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                <button id="sd-reboot" class="admin-btn admin-btn-primary" style="background:var(--pb-color-warning,#c77b1a);">${pending > 0 ? 'Trotzdem neu starten' : 'Neustarten'}</button>
                <button id="sd-go" class="admin-btn admin-btn-primary" style="background:var(--pb-color-error);">${pending > 0 ? 'Trotzdem ausschalten' : 'Herunterfahren'}</button>
            </div>
            <p id="sd-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
        </div>`;
        document.body.appendChild(o);
        o.querySelector('#sd-cancel').addEventListener('click', () => o.remove());

        const powerAction = async (path, doingText, doneText) => {
            const msg = o.querySelector('#sd-msg');
            o.querySelectorAll('button').forEach(b => b.disabled = true);
            msg.style.color = 'var(--pb-color-text-muted)';
            msg.textContent = doingText;
            try {
                const res = await fetch(path, {
                    method: 'POST', headers: h, body: JSON.stringify({ force: pending > 0 }),
                });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = doneText;
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
                o.querySelectorAll('button').forEach(b => b.disabled = false);
            }
        };

        o.querySelector('#sd-go').addEventListener('click', () =>
            powerAction('/api/v1/system/shutdown', 'Fahre herunter…', 'Box fährt herunter…'));
        o.querySelector('#sd-reboot').addEventListener('click', () =>
            powerAction('/api/v1/system/reboot', 'Starte neu…', 'Box startet neu… Seite in ~1 Min. neu laden.'));
    });
}
