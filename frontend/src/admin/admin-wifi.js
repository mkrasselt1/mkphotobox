import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

function signalBars(signal) {
    const level = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
    return '▮'.repeat(level) + '▯'.repeat(4 - level);
}

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
}

/** fetch + JSON mit verständlichen Fehlermeldungen statt „Failed to fetch".
 *  Liefert immer ein Objekt; bei Fehlern {status:'error', message}. */
async function api(url, options = {}) {
    let res;
    try {
        res = await fetch(url, options);
    } catch {
        return {
            status: 'error', network: true,
            message: 'Keine Antwort von der Fotobox. Vermutlich hat sich gerade die '
                + 'WLAN-Verbindung geändert — kurz warten und die Seite neu laden '
                + '(ggf. unter der neuen IP-Adresse).',
        };
    }
    let data = null;
    try { data = await res.json(); } catch { /* keine JSON-Antwort */ }
    if (!res.ok) {
        let message = (data && typeof data.detail === 'string') ? data.detail : '';
        if (res.status === 401) message = 'Sitzung abgelaufen — bitte neu anmelden.';
        else if (res.status === 403 && (!message || message === 'Insufficient permissions')) {
            message = 'Keine Berechtigung für diese Aktion.';
        }
        return { status: 'error', message: message || `Serverfehler (HTTP ${res.status}).` };
    }
    return data ?? { status: 'error', message: 'Unerwartete Antwort vom Server.' };
}

export async function render(container, state) {
    const headers = getHeaders();

    async function loadStatus() {
        try { return await fetch('/api/v1/wifi/status').then(r => r.json()); }
        catch { return { available: false, reason: 'Status nicht abrufbar' }; }
    }

    async function loadNetworks(rescan) {
        try {
            const r = await fetch(`/api/v1/wifi/scan?rescan=${rescan ? 'true' : 'false'}`).then(r => r.json());
            return r.networks || [];
        } catch { return []; }
    }

    async function loadSaved() {
        const r = await api('/api/v1/wifi/saved', { headers });
        return { list: r.networks || [], error: r.status === 'error' ? r.message : (r.message || '') };
    }

    let status = await loadStatus();
    let networks = status.available ? await loadNetworks(false) : [];
    let saved = status.available ? await loadSaved() : { list: [], error: '' };

    function savedRows() {
        if (saved.error && !saved.list.length) {
            return `<p style="color:var(--pb-color-error);">${esc(saved.error)}</p>`;
        }
        if (!saved.list.length) {
            return '<p style="color:var(--pb-color-text-muted);">Noch keine Netze gespeichert.</p>';
        }
        return saved.list.map((n, i) => `
            <div class="saved-row" data-uuid="${esc(n.uuid)}"
                 style="display:flex;align-items:center;gap:0.5rem;padding:0.5rem 0.6rem;border-radius:8px;flex-wrap:wrap;${n.active ? 'background:rgba(255,255,255,0.06);' : ''}">
                <span style="flex:1;min-width:8rem;">
                    ${esc(n.ssid)}${n.active ? ' <strong style="color:var(--pb-color-success);">✓ aktiv</strong>' : ''}
                    ${n.name !== n.ssid ? `<br><span style="font-size:0.75rem;color:var(--pb-color-text-muted);">Profil: ${esc(n.name)}</span>` : ''}
                    ${!n.autoconnect ? '<br><span style="font-size:0.75rem;color:var(--pb-color-text-muted);">automatisches Verbinden aus</span>' : ''}
                </span>
                <span style="display:flex;align-items:center;gap:0.25rem;" title="Priorität (höher = bevorzugt)">
                    <button class="admin-btn admin-btn-outline btn-prio-up" style="padding:0.2rem 0.5rem;" ${i === 0 ? 'disabled' : ''} title="Bevorzugen">▲</button>
                    <input type="number" class="admin-input prio-input" value="${n.priority}" min="-999" max="999" style="width:4.5rem;text-align:center;">
                    <button class="admin-btn admin-btn-outline btn-prio-down" style="padding:0.2rem 0.5rem;" ${i === saved.list.length - 1 ? 'disabled' : ''} title="Zurückstufen">▼</button>
                </span>
                <button class="admin-btn admin-btn-outline btn-saved-connect" ${n.active ? 'disabled' : ''}>Verbinden</button>
                <button class="admin-btn admin-btn-outline btn-saved-delete">Entfernen</button>
            </div>`).join('');
    }

    function draw() {
        if (!status.available) {
            container.innerHTML = adminShell(`
                <h1 style="margin-bottom:1.5rem;">WLAN</h1>
                <div class="admin-card">
                    <h3>Nicht verfügbar</h3>
                    <p>${status.reason || 'WLAN-Verwaltung wird auf diesem System nicht unterstützt.'}</p>
                    <p style="margin-top:0.5rem;">Benötigt NetworkManager (<code>nmcli</code>) auf einem Linux-Gerät.</p>
                </div>
            `);
            setupLogout(container);
            return;
        }

        const connBox = status.connected
            ? `<p><strong>Verbunden mit:</strong> ${status.ssid || '—'}</p>
               <p><strong>IP-Adresse:</strong> ${status.ip || '—'}</p>
               ${status.signal != null ? `<p><strong>Signal:</strong> ${status.signal}%</p>` : ''}
               <button id="btn-disconnect" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;">Trennen</button>`
            : `<p style="color:var(--pb-color-text-muted);">Nicht verbunden.</p>`;

        container.innerHTML = adminShell(`
            <h1 style="margin-bottom:1.5rem;">WLAN-Verwaltung</h1>
            <div style="max-width:650px;">

                <div class="admin-card">
                    <h3>Status</h3>
                    ${connBox}
                    <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;cursor:pointer;">
                        <input type="checkbox" id="radio-toggle" ${status.radio_enabled ? 'checked' : ''}>
                        WLAN-Funk aktiviert
                    </label>
                </div>

                <div class="admin-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                        <h3 style="margin:0;">Verfügbare Netzwerke</h3>
                        <button id="btn-scan" class="admin-btn admin-btn-outline">Neu suchen</button>
                    </div>
                    <div id="net-list">
                        ${networks.length
                            ? networks.map(n => `
                                <div class="wifi-row" data-ssid="${encodeURIComponent(n.ssid)}" data-secured="${n.secured}"
                                     style="display:flex;align-items:center;gap:0.75rem;padding:0.6rem;border-radius:8px;cursor:pointer;${n.active ? 'background:rgba(255,255,255,0.06);' : ''}">
                                    <span style="font-family:monospace;color:var(--pb-color-primary);">${signalBars(n.signal)}</span>
                                    <span style="flex:1;">${n.ssid}${n.active ? ' ✓' : ''}</span>
                                    <span style="font-size:0.8rem;color:var(--pb-color-text-muted);">${n.secured ? '🔒 ' + n.security : 'offen'}</span>
                                </div>`).join('')
                            : '<p style="color:var(--pb-color-text-muted);">Keine Netzwerke gefunden. Klicke auf „Neu suchen".</p>'
                        }
                    </div>
                </div>

                <div class="admin-card">
                    <h3>Bekannte Netze</h3>
                    <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                        Die Box verbindet sich automatisch mit dem verfügbaren Netz mit der höchsten Priorität.
                    </p>
                    <div id="saved-list">${savedRows()}</div>

                    <h4 style="margin-top:1.25rem;margin-bottom:0.5rem;">Netz hinzufügen</h4>
                    <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.5rem;">
                        Das Netz muss dafür nicht in Reichweite sein — z. B. die Event-Location oder den Handy-Hotspot vorab eintragen.
                    </p>
                    <form id="add-form" autocomplete="off">
                        <label style="font-size:0.9rem;">Netzwerkname (SSID)</label>
                        <input type="text" id="add-ssid" class="admin-input" style="width:100%;margin:0.25rem 0 0.5rem;" maxlength="32" placeholder="z. B. Mein-Hotspot">
                        <label style="font-size:0.9rem;">Passwort (leer lassen bei offenem Netz)</label>
                        <input type="password" id="add-pass" class="admin-input" style="width:100%;margin:0.25rem 0 0.5rem;" maxlength="64" placeholder="8–63 Zeichen" autocomplete="new-password">
                        <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                            <input type="checkbox" id="add-hidden"> Verstecktes Netz (SSID wird nicht ausgestrahlt)
                        </label>
                        <button type="submit" id="btn-add" class="admin-btn admin-btn-primary" style="margin-top:0.75rem;">Speichern</button>
                    </form>
                </div>

                <div class="admin-card" id="connect-box" style="display:none;">
                    <h3>Verbinden mit „<span id="connect-ssid"></span>"</h3>
                    <div id="pw-wrap">
                        <label style="font-size:0.9rem;">Passwort</label>
                        <input type="password" id="wifi-pass" class="admin-input" style="width:100%;margin-top:0.25rem;" placeholder="WLAN-Passwort">
                    </div>
                    <div style="display:flex;gap:0.75rem;margin-top:1rem;">
                        <button id="btn-connect" class="admin-btn admin-btn-primary">Verbinden</button>
                        <button id="btn-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                    </div>
                </div>

                <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>
            </div>
        `);

        setupLogout(container);
        attach();
    }

    function setMsg(text, kind) {
        const msg = container.querySelector('#msg');
        if (!msg) return;
        msg.textContent = text;
        msg.style.color = kind === 'error' ? 'var(--pb-color-error)'
            : kind === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    }

    async function refresh() {
        status = await loadStatus();
        networks = status.available ? await loadNetworks(false) : [];
        saved = status.available ? await loadSaved() : { list: [], error: '' };
        draw();
    }

    /** Aktion ausführen, Ergebnis melden, danach neu laden (Meldung bleibt stehen). */
    async function runAction(pending, url, options, okText) {
        setMsg(pending);
        const result = await api(url, { headers, ...options });
        // Box nicht erreichbar → nicht neu zeichnen, sonst verschwindet die Meldung
        if (!result.network) await refresh();
        if (result.status === 'ok') setMsg(okText, 'ok');
        else setMsg('Fehler: ' + (result.message || 'Aktion fehlgeschlagen'), 'error');
        return result;
    }

    function setPriority(uuid, priority) {
        return runAction('Ändere Priorität…', `/api/v1/wifi/saved/${encodeURIComponent(uuid)}/priority`,
            { method: 'POST', body: JSON.stringify({ priority }) }, 'Priorität geändert.');
    }

    function attach() {
        let selected = null;

        container.querySelector('#btn-scan')?.addEventListener('click', async () => {
            setMsg('Suche nach Netzwerken…');
            networks = await loadNetworks(true);
            draw();
        });

        container.querySelectorAll('.wifi-row').forEach(row => {
            row.addEventListener('click', () => {
                selected = {
                    ssid: decodeURIComponent(row.dataset.ssid),
                    secured: row.dataset.secured === 'true',
                };
                container.querySelector('#connect-box').style.display = '';
                container.querySelector('#connect-ssid').textContent = selected.ssid;
                container.querySelector('#pw-wrap').style.display = selected.secured ? '' : 'none';
                container.querySelector('#wifi-pass').value = '';
            });
        });

        container.querySelectorAll('.saved-row').forEach(row => {
            const uuid = row.dataset.uuid;
            const idx = saved.list.findIndex(n => n.uuid === uuid);
            const net = saved.list[idx];
            if (!net) return;

            row.querySelector('.btn-saved-connect')?.addEventListener('click', () =>
                runAction(`Verbinde mit „${net.ssid}"…`,
                    `/api/v1/wifi/saved/${encodeURIComponent(uuid)}/connect`,
                    { method: 'POST' }, `Verbunden mit „${net.ssid}"`));

            row.querySelector('.btn-saved-delete')?.addEventListener('click', () => {
                const warn = net.active
                    ? `„${net.ssid}" entfernen? Die Box ist gerade damit verbunden und wird getrennt — `
                      + 'wenn du über dieses WLAN zugreifst, bricht die Verbindung zur Admin-Seite ab.'
                    : `Gespeichertes Netz „${net.ssid}" entfernen?`;
                if (!confirm(warn)) return;
                runAction(`Entferne „${net.ssid}"…`, `/api/v1/wifi/saved/${encodeURIComponent(uuid)}`,
                    { method: 'DELETE' }, `„${net.ssid}" entfernt.`);
            });

            // ▲/▼: knapp über bzw. unter den Nachbarn setzen
            row.querySelector('.btn-prio-up')?.addEventListener('click', () => {
                const above = saved.list[idx - 1];
                if (above) setPriority(uuid, Math.min(999, above.priority + 1));
            });
            row.querySelector('.btn-prio-down')?.addEventListener('click', () => {
                const below = saved.list[idx + 1];
                if (below) setPriority(uuid, Math.max(-999, below.priority - 1));
            });
            row.querySelector('.prio-input')?.addEventListener('change', (e) => {
                const v = parseInt(e.target.value, 10);
                if (Number.isNaN(v) || v < -999 || v > 999) {
                    setMsg('Fehler: Priorität muss eine Zahl zwischen -999 und 999 sein.', 'error');
                    e.target.value = net.priority;
                    return;
                }
                if (v !== net.priority) setPriority(uuid, v);
            });
        });

        container.querySelector('#add-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const ssid = container.querySelector('#add-ssid').value.trim();
            const password = container.querySelector('#add-pass').value;
            const hidden = container.querySelector('#add-hidden').checked;
            if (!ssid) { setMsg('Fehler: Bitte einen Netzwerknamen (SSID) angeben.', 'error'); return; }
            if (new TextEncoder().encode(ssid).length > 32) {
                setMsg('Fehler: Der Netzwerkname darf höchstens 32 Byte lang sein.', 'error'); return;
            }
            if (password && !/^[0-9a-fA-F]{64}$/.test(password) && (password.length < 8 || password.length > 63)) {
                setMsg('Fehler: Das WLAN-Passwort muss 8 bis 63 Zeichen lang sein.', 'error'); return;
            }
            const btn = container.querySelector('#btn-add');
            if (btn) btn.disabled = true;
            const result = await runAction(`Speichere „${ssid}"…`, '/api/v1/wifi/saved',
                { method: 'POST', body: JSON.stringify({ ssid, password, hidden }) },
                `„${ssid}" gespeichert. Die Box verbindet sich automatisch, sobald das Netz in Reichweite ist.`);
            if (result.status === 'ok' && result.replaced) {
                setMsg(`„${ssid}" aktualisiert (vorheriges Profil ersetzt).`, 'ok');
            }
            if (result.status !== 'ok') {
                // Eingaben nach Fehler wiederherstellen (draw() hat das Formular neu gebaut)
                const s = container.querySelector('#add-ssid'); if (s) s.value = ssid;
                const h = container.querySelector('#add-hidden'); if (h) h.checked = hidden;
            }
        });

        container.querySelector('#btn-cancel')?.addEventListener('click', () => {
            container.querySelector('#connect-box').style.display = 'none';
            selected = null;
        });

        container.querySelector('#btn-connect')?.addEventListener('click', async () => {
            if (!selected) return;
            const password = container.querySelector('#wifi-pass')?.value || '';
            setMsg(`Verbinde mit „${selected.ssid}"…`);
            try {
                const res = await fetch('/api/v1/wifi/connect', {
                    method: 'POST', headers,
                    body: JSON.stringify({ ssid: selected.ssid, password }),
                });
                const result = await res.json();
                if (result.status === 'ok') {
                    setMsg(`Verbunden mit „${selected.ssid}"`, 'ok');
                    await refresh();
                } else {
                    setMsg('Fehler: ' + (result.message || 'Verbindung fehlgeschlagen'), 'error');
                }
            } catch {
                setMsg('Fehler: Keine Antwort von der Fotobox — evtl. hat sich die WLAN-Verbindung '
                    + 'gerade geändert. Kurz warten und die Seite neu laden.', 'error');
            }
        });

        container.querySelector('#btn-disconnect')?.addEventListener('click', async () => {
            setMsg('Trenne Verbindung…');
            await fetch('/api/v1/wifi/disconnect', { method: 'POST', headers });
            await refresh();
        });

        container.querySelector('#radio-toggle')?.addEventListener('change', async (e) => {
            const on = e.target.checked;
            setMsg(on ? 'Schalte WLAN ein…' : 'Schalte WLAN aus…');
            await fetch('/api/v1/wifi/radio', {
                method: 'POST', headers, body: JSON.stringify({ on }),
            });
            await refresh();
        });
    }

    draw();
}
