import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

function signalBars(signal) {
    const level = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
    return '▮'.repeat(level) + '▯'.repeat(4 - level);
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

    let status = await loadStatus();
    let networks = status.available ? await loadNetworks(false) : [];

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
        draw();
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
            } catch (err) {
                setMsg('Fehler: ' + err.message, 'error');
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
