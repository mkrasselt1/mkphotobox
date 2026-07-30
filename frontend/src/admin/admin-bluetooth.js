import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

function esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fmtSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtTime(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleString('de-DE');
}

export async function render(container, state) {
    const headers = getHeaders();

    let status = { adapter: {}, receiver: {} };
    let devices = [];
    let received = [];

    async function load() {
        try {
            status = await fetch('/api/v1/bluetooth/status', { headers }).then(r => r.json());
        } catch { status = { adapter: { available: false, reason: 'Status nicht abrufbar' }, receiver: {} }; }
        try {
            const r = await fetch('/api/v1/bluetooth/devices', { headers }).then(r => r.json());
            devices = r.devices || [];
        } catch { devices = []; }
        try {
            const r = await fetch('/api/v1/bluetooth/received', { headers }).then(r => r.json());
            received = r.files || [];
        } catch { received = []; }
    }

    function setMsg(text, kind) {
        const msg = container.querySelector('#bt-msg');
        if (!msg) return;
        msg.textContent = text;
        msg.style.color = kind === 'error' ? 'var(--pb-color-error)'
            : kind === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    }

    function draw() {
        const a = status.adapter || {};
        const r = status.receiver || {};

        if (!a.available) {
            container.innerHTML = adminShell(`
                <h1 style="margin-bottom:1.5rem;">Bluetooth</h1>
                <div class="admin-card">
                    <h3>Nicht verfügbar</h3>
                    <p>${esc(a.reason || 'Bluetooth wird auf diesem System nicht unterstützt.')}</p>
                </div>
            `);
            setupLogout(container);
            return;
        }

        container.innerHTML = adminShell(`
            <h1 style="margin-bottom:1.5rem;">Bluetooth</h1>
            <div style="max-width:650px;">

                <div class="admin-card">
                    <h3>Adapter</h3>
                    <p><strong>Name:</strong> ${esc(a.name || '—')}</p>
                    <p><strong>Adresse:</strong> <code>${esc(a.address || '—')}</code></p>
                    <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;cursor:pointer;">
                        <input type="checkbox" id="bt-visible" ${a.discoverable ? 'checked' : ''}>
                        Für Handys sichtbar (koppelbar)
                    </label>
                    <p style="font-size:0.8rem;color:var(--pb-color-text-muted);margin-top:0.4rem;">
                        Solange aktiv, findet jedes Handy die Box unter „${esc(a.name || 'photobooth')}".
                    </p>
                </div>

                <div class="admin-card">
                    <h3>Dateiempfang</h3>
                    <p><strong>Status:</strong> ${r.receiving
                        ? '<span style="color:var(--pb-color-success);">aktiv — eingehende Dateien werden angenommen</span>'
                        : '<span style="color:var(--pb-color-error);">nicht aktiv</span>'}</p>
                    ${r.receiving ? '' : `<p style="font-size:0.85rem;color:var(--pb-color-text-muted);">
                        Dienst <code>${esc(r.unit || 'mkphotobox-btrecv.service')}</code> läuft nicht —
                        <code>scripts/setup.sh</code> mit <code>WITH_BLUETOOTH=1</code> ausführen.</p>`}
                    <p style="font-size:0.85rem;color:var(--pb-color-text-muted);">
                        Ordner: <code>${esc(r.directory || '—')}</code></p>
                </div>

                <div class="admin-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                        <h3 style="margin:0;">Empfangene Dateien</h3>
                        <button id="bt-refresh" class="admin-btn admin-btn-outline">Aktualisieren</button>
                    </div>
                    ${received.length ? `
                        <div style="display:flex;flex-direction:column;gap:0.3rem;">
                            ${received.map(f => `
                                <div style="display:flex;gap:0.75rem;align-items:center;padding:0.4rem 0.5rem;border-radius:6px;background:rgba(255,255,255,0.03);">
                                    <span style="flex:1;min-width:0;font-size:0.9rem;overflow:hidden;text-overflow:ellipsis;">${esc(f.name)}</span>
                                    <span style="font-size:0.8rem;color:var(--pb-color-text-muted);">${fmtSize(f.size)}</span>
                                    <span style="font-size:0.8rem;color:var(--pb-color-text-muted);">${fmtTime(f.mtime)}</span>
                                </div>`).join('')}
                        </div>`
                        : '<p style="color:var(--pb-color-text-muted);">Noch nichts empfangen.</p>'}
                </div>

                <div class="admin-card">
                    <h3>Gekoppelte Geräte</h3>
                    ${devices.length ? `
                        <div style="display:flex;flex-direction:column;gap:0.3rem;">
                            ${devices.map(d => `
                                <div style="display:flex;gap:0.75rem;align-items:center;padding:0.4rem 0.5rem;border-radius:6px;background:rgba(255,255,255,0.03);">
                                    <span style="flex:1;">${esc(d.name)}</span>
                                    <code style="font-size:0.8rem;color:var(--pb-color-text-muted);">${esc(d.address)}</code>
                                </div>`).join('')}
                        </div>`
                        : `<p style="color:var(--pb-color-text-muted);">Keine gekoppelten Geräte. Sichtbarkeit
                           einschalten und am Handy die Box auswählen — nur gekoppelte Geräte können Fotos empfangen.</p>`}
                </div>

                <p id="bt-msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>
            </div>
        `);

        setupLogout(container);
        attach();
    }

    async function refresh() {
        await load();
        draw();
    }

    function attach() {
        container.querySelector('#bt-visible')?.addEventListener('change', async (e) => {
            const on = e.target.checked;
            setMsg(on ? 'Schalte Sichtbarkeit ein…' : 'Verberge die Box…');
            try {
                const res = await fetch('/api/v1/bluetooth/visible', {
                    method: 'POST', headers, body: JSON.stringify({ on }),
                }).then(r => r.json());
                if (res.status === 'ok') setMsg(on ? 'Box ist jetzt sichtbar.' : 'Box ist verborgen.', 'ok');
                else setMsg('Fehler: ' + (res.message || 'fehlgeschlagen'), 'error');
            } catch (err) {
                setMsg('Fehler: ' + err.message, 'error');
            }
            await refresh();
        });

        container.querySelector('#bt-refresh')?.addEventListener('click', refresh);
    }

    await load();
    draw();
}
