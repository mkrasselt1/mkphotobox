import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

function esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Anmeldelink als QR-Code (vendor/qrcode.min.js, global `qrcode`) — so lässt
// sich die Box vom Handy aus anmelden, ohne am Kiosk-Bildschirm zu tippen.
function qrSvg(url) {
    try {
        const qr = qrcode(0, 'M');
        qr.addData(url);
        qr.make();
        return qr.createSvgTag({ cellSize: 4, margin: 2 });
    } catch {
        return '';
    }
}

export async function render(container, state) {
    const headers = getHeaders();
    let timer = null;
    let last = null;          // letzte Antwort von /system/network

    // Tailscale-Bedienung: überlebt das Neuzeichnen alle 8 s
    const tsUi = {
        busy: false,
        msg: '', msgError: false,
        authUrl: '',           // Anmeldelink aus POST /tailscale/up
        authKey: '',           // Inhalt des Auth-Key-Felds
        keyOpen: false,        // Auth-Key-Bereich aufgeklappt?
        waitTimer: null,       // schnelles Nachfragen, bis BackendState "Running"
    };

    async function load() {
        try { return await fetch('/api/v1/system/network', { headers }).then(r => r.json()); }
        catch (e) { return { error: e.message }; }
    }

    function dot(ok) {
        const c = ok ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
        return `<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:${c};box-shadow:0 0 8px ${c};vertical-align:middle;"></span>`;
    }

    function ifaceIcon(name) {
        const n = (name || '').toLowerCase();
        if (n.startsWith('wl') || n.startsWith('wlan')) return '📶';
        if (n.startsWith('en') || n.startsWith('eth')) return '🔌';
        if (n.startsWith('usb') || n.startsWith('rndis')) return '📱';
        if (n.startsWith('tailscale') || n.startsWith('ts')) return '🔐';
        return '🌐';
    }

    function tailscaleBox(ts) {
        const tsRunning = ts.available && ts.backend_state === 'Running';

        if (!ts.available) {
            return `<p style="color:var(--pb-color-text-muted);">${esc(ts.reason || 'Tailscale nicht verfügbar.')}</p>
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);">Tailscale wird von <code>scripts/setup.sh</code> mitinstalliert — das Setup einmal erneut ausführen.</p>`;
        }

        // Anmeldelink: aus dem Verbinden-Aufruf oder (nach Neuladen der Seite)
        // aus dem Status, solange tailscale auf die Anmeldung wartet.
        const authUrl = tsRunning ? ''
            : (tsUi.authUrl || (ts.backend_state === 'NeedsLogin' ? ts.auth_url : '') || '');

        const stateText = tsRunning ? 'Verbunden'
            : ts.backend_state === 'NeedsLogin' ? 'Nicht angemeldet'
            : ts.backend_state === 'Stopped' ? 'Getrennt'
            : (ts.backend_state || 'unbekannt');

        let html = `
            <p>${dot(tsRunning)} <strong>Status:</strong> ${esc(stateText)}</p>
            ${ts.dns_name ? `<p><strong>Name:</strong> <span style="font-family:monospace;">${esc(ts.dns_name)}</span></p>` : ''}
            <p><strong>Tailscale-IP:</strong> <span style="font-family:monospace;color:var(--pb-color-primary);">${esc(ts.self_ip || '—')}</span></p>
            <p><strong>Geräte online:</strong> ${ts.peers_online ?? '?'} / ${ts.peers_total ?? '?'}</p>`;

        if (authUrl) {
            const svg = qrSvg(authUrl);
            html += `
            <div style="margin:0.75rem 0;padding:0.75rem;border:1px solid var(--pb-color-border);border-radius:8px;">
                <p style="margin-top:0;"><strong>Anmeldung bestätigen:</strong> Link öffnen oder den QR-Code mit dem Handy scannen und dort bei Tailscale anmelden.</p>
                <p style="word-break:break-all;"><a href="${esc(authUrl)}" target="_blank" rel="noopener" style="color:var(--pb-color-primary);">${esc(authUrl)}</a></p>
                ${svg ? `<div style="display:inline-block;padding:0.75rem;background:white;border-radius:10px;line-height:0;">${svg}</div>` : ''}
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0;">⏳ Warte auf Anmeldung …</p>
            </div>`;
        }

        const dis = tsUi.busy ? 'disabled' : '';
        if (tsRunning) {
            html += `
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.75rem;">
                <button id="ts-down" class="admin-btn admin-btn-outline" ${dis}>Trennen</button>
                <button id="ts-logout" class="admin-btn admin-btn-outline" ${dis} title="Box vom Tailnet abmelden — danach ist eine neue Anmeldung nötig">Abmelden</button>
            </div>`;
        } else {
            html += `
            <details id="ts-key-box" style="margin-top:0.75rem;" ${tsUi.keyOpen ? 'open' : ''}>
                <summary style="cursor:pointer;">Mit Auth-Key verbinden (optional)</summary>
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);">Auth-Key aus der Tailscale-Verwaltung (Settings → Keys). Dann ist kein Anmeldelink nötig.</p>
                <input type="password" id="ts-key" class="admin-input" style="width:100%;" autocomplete="off" placeholder="tskey-auth-…" value="${esc(tsUi.authKey)}">
            </details>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.75rem;">
                <button id="ts-up" class="admin-btn admin-btn-primary" ${dis}>${tsUi.busy ? 'Bitte warten …' : 'Verbinden'}</button>
                ${ts.backend_state === 'NeedsLogin' ? '' : `<button id="ts-logout" class="admin-btn admin-btn-outline" ${dis} title="Box vom Tailnet abmelden — danach ist eine neue Anmeldung nötig">Abmelden</button>`}
            </div>`;
        }
        if (tsUi.msg) {
            html += `<p style="margin-top:0.75rem;color:${tsUi.msgError ? 'var(--pb-color-error)' : 'var(--pb-color-text-muted)'};">${esc(tsUi.msg)}</p>`;
        }
        return html;
    }

    function draw(n) {
        if (n.error) {
            container.innerHTML = adminShell(`<h1 style="margin-bottom:1.5rem;">Netzwerk</h1>
                <div class="admin-card"><h3>Fehler</h3><p>${esc(n.error)}</p></div>`);
            setupLogout(container);
            return;
        }

        const ifaceRows = (n.interfaces || []).length
            ? n.interfaces.map(i => `
                <div style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0;border-bottom:1px solid var(--pb-color-border);">
                    <span style="font-size:1.2rem;">${ifaceIcon(i.name)}</span>
                    <div style="flex:1;">
                        <div style="font-weight:600;">${i.name}
                            <span style="font-size:0.78rem;color:var(--pb-color-text-muted);font-weight:400;">${i.state || ''}</span>
                        </div>
                        <div style="font-family:monospace;font-size:0.85rem;color:var(--pb-color-primary);">
                            ${(i.addresses || []).join(', ') || '—'}
                        </div>
                    </div>
                    ${dot((i.addresses || []).length > 0)}
                </div>`).join('')
            : '<p style="color:var(--pb-color-text-muted);">Keine aktiven Schnittstellen gefunden.</p>';

        container.innerHTML = adminShell(`
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;">
                <h1 style="margin:0;">Netzwerk-Status</h1>
                <button id="btn-refresh" class="admin-btn admin-btn-outline">↻ Aktualisieren</button>
            </div>
            <div style="max-width:650px;">

                <div class="admin-card">
                    <h3>Internet</h3>
                    <p style="font-size:1.05rem;">${dot(n.internet)} ${n.internet ? 'Online — Internet erreichbar' : 'Offline — keine Internetverbindung'}</p>
                    <p><strong>Hostname:</strong> ${n.hostname || '—'}</p>
                    <p><strong>Gateway:</strong> <span style="font-family:monospace;">${n.gateway || '—'}</span></p>
                </div>

                <div class="admin-card">
                    <h3>Schnittstellen</h3>
                    ${ifaceRows}
                </div>

                <div class="admin-card">
                    <h3>🔐 Tailscale (Fernzugriff)</h3>
                    ${tailscaleBox(n.tailscale || {})}
                </div>

                <p style="font-size:0.8rem;color:var(--pb-color-text-muted);">Aktualisiert sich automatisch alle 8 Sekunden.</p>
            </div>
        `);

        setupLogout(container);
        container.querySelector('#btn-refresh')?.addEventListener('click', refresh);
        bindTailscale();
    }

    // ── Tailscale-Knöpfe ──────────────────────────────────────────────
    function bindTailscale() {
        const key = container.querySelector('#ts-key');
        key?.addEventListener('input', () => { tsUi.authKey = key.value; });
        container.querySelector('#ts-key-box')?.addEventListener('toggle', e => { tsUi.keyOpen = e.target.open; });
        container.querySelector('#ts-up')?.addEventListener('click', tsConnect);
        container.querySelector('#ts-down')?.addEventListener('click', () => tsAction('down', 'Getrennt.'));
        container.querySelector('#ts-logout')?.addEventListener('click', () => {
            if (!confirm('Box wirklich von Tailscale abmelden? Für den Fernzugriff ist danach eine neue Anmeldung nötig.')) return;
            tsAction('logout', 'Abgemeldet.');
        });
    }

    async function post(path, body) {
        const r = await fetch(`/api/v1/system/tailscale/${path}`, {
            method: 'POST',
            headers: { ...headers, 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || `Fehler ${r.status}`);
        return data;
    }

    async function tsConnect() {
        stopWaiting();
        tsUi.busy = true;
        tsUi.msg = 'Verbinde … (kann bis zu 30 Sekunden dauern)';
        tsUi.msgError = false;
        tsUi.authUrl = '';
        if (last) draw(last);
        try {
            const res = await post('up', { auth_key: tsUi.authKey.trim() || undefined });
            tsUi.authUrl = res.auth_url || '';
            tsUi.authKey = '';
            tsUi.msg = res.state === 'Running' ? 'Verbunden.'
                : tsUi.authUrl ? '' : 'Tailscale startet — Status wird aktualisiert …';
            if (res.state !== 'Running') startWaiting();
        } catch (e) {
            tsUi.msg = e.message;
            tsUi.msgError = true;
        }
        tsUi.busy = false;
        await refresh();
    }

    async function tsAction(path, okText) {
        stopWaiting();
        tsUi.busy = true;
        tsUi.authUrl = '';
        tsUi.msg = '';
        if (last) draw(last);
        try {
            await post(path);
            tsUi.msg = okText;
            tsUi.msgError = false;
        } catch (e) {
            tsUi.msg = e.message;
            tsUi.msgError = true;
        }
        tsUi.busy = false;
        await refresh();
    }

    // Nach dem Verbinden alle 3 s nachsehen, bis tailscale "Running" meldet
    // (höchstens 15 min — so lange lebt auch der Anmeldeprozess im Backend).
    function startWaiting() {
        stopWaiting();
        const until = Date.now() + 15 * 60 * 1000;
        tsUi.waitTimer = setInterval(async () => {
            if (!pageShown() || Date.now() > until) { stopWaiting(); return; }
            const n = await load();
            if (n.tailscale?.backend_state === 'Running') {
                stopWaiting();
                tsUi.authUrl = '';
                tsUi.msg = 'Verbunden.';
                tsUi.msgError = false;
            }
            last = n;
            if (!keyFocused()) draw(n);
        }, 3000);
    }

    function stopWaiting() {
        if (tsUi.waitTimer) clearInterval(tsUi.waitTimer);
        tsUi.waitTimer = null;
    }

    function pageShown() {
        return document.body.contains(container) && location.hash.includes('admin/network');
    }

    // Beim Tippen des Auth-Keys nicht neu zeichnen (Fokus/Cursor gingen verloren)
    function keyFocused() {
        return document.activeElement?.id === 'ts-key';
    }

    async function refresh() {
        last = await load();
        draw(last);
    }

    await refresh();

    // auto-refresh while this page is shown; stop when navigating away
    timer = setInterval(async () => {
        if (!pageShown()) {
            clearInterval(timer);
            stopWaiting();
            return;
        }
        if (tsUi.busy || tsUi.waitTimer || keyFocused()) return;
        await refresh();
    }, 8000);
}
