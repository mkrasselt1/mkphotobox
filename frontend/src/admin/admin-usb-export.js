import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

let _progressHandler = null;
let _completedHandler = null;

function detachWs() {
    const ws = window.pb?.ws;
    if (!ws) return;
    if (_progressHandler) ws.off('usb_export.progress', _progressHandler);
    if (_completedHandler) ws.off('usb_export.completed', _completedHandler);
    _progressHandler = _completedHandler = null;
}

function fmtSize(bytes) {
    if (bytes == null) return '?';
    const gb = bytes / 1_073_741_824;
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    return `${Math.round(bytes / 1_048_576)} MB`;
}

export async function render(container, state) {
    const headers = getHeaders();
    detachWs();

    let status = {}, sources = { events: [], total_photos: 0 }, drivesResp = { drives: [] };
    try {
        [status, sources, drivesResp] = await Promise.all([
            fetch('/api/v1/usb-export/status').then(r => r.json()),
            fetch('/api/v1/usb-export/sources', { headers }).then(r => r.json()),
            fetch('/api/v1/usb-export/drives', { headers }).then(r => r.json()),
        ]);
    } catch {}

    const cfg = status.config || {};
    const drives = drivesResp.drives || [];
    const job = status.job || {};
    const copying = status.busy;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Auf USB / Datenträger kopieren</h1>
        <div style="max-width:650px;">

            <div class="admin-card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                    <h3 style="margin:0;">Zielmedium</h3>
                    <button id="btn-refresh" class="admin-btn admin-btn-outline">Datenträger suchen</button>
                </div>
                ${drives.length
                    ? `<select id="drive-select" class="admin-input" style="width:100%;">
                        ${drives.map(d => `
                            <option value="${encodeURIComponent(d.mountpoint)}">
                                ${d.label}${d.fstype ? ` [${d.fstype}]` : ''} — ${fmtSize(d.free_bytes)} frei von ${fmtSize(d.size_bytes)}
                            </option>`).join('')}
                       </select>`
                    : `<p style="color:var(--pb-color-text-muted);">Keine Wechseldatenträger gefunden.
                       Stecke einen USB-Stick / eine SD-Karte / eine USB-Festplatte ein und klicke auf „Datenträger suchen".</p>`
                }
            </div>

            <div class="admin-card">
                <h3>Was soll kopiert werden?</h3>
                <select id="source-select" class="admin-input" style="width:100%;">
                    <option value="all">Alle Fotos (${sources.total_photos || 0})</option>
                    ${(sources.events || []).map(e =>
                        `<option value="event:${e.event_id}">${e.name} (${e.photo_count})${e.is_active ? ' — aktiv' : ''}</option>`
                    ).join('')}
                </select>
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-top:0.5rem;">
                    Ziel-Unterordner: <code>${cfg.subfolder || '(Wurzel)'}</code> ·
                    ${cfg.include_gifs ? 'GIFs werden mitkopiert.' : 'GIFs werden nicht kopiert.'}
                </p>
            </div>

            <div class="admin-card" id="progress-card" style="${copying ? '' : 'display:none;'}">
                <h3>Kopiervorgang</h3>
                <div style="background:#0e1a30;border-radius:8px;overflow:hidden;height:24px;">
                    <div id="progress-bar" style="height:100%;width:${job.progress || 0}%;background:var(--pb-color-primary);transition:width 0.2s;"></div>
                </div>
                <p id="progress-msg" style="margin-top:0.5rem;font-size:0.9rem;">${job.message || ''}</p>
                <button id="btn-cancel" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;">Abbrechen</button>
            </div>

            <div style="display:flex;gap:0.75rem;margin-top:0.5rem;">
                <button id="btn-copy" class="admin-btn admin-btn-primary" ${copying || !drives.length ? 'disabled' : ''}>
                    Kopieren starten
                </button>
            </div>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>

            <details class="admin-card" style="margin-top:1rem;">
                <summary style="cursor:pointer;color:var(--pb-color-primary);">Einstellungen</summary>
                <div style="margin-top:1rem;">
                    <label style="font-size:0.9rem;">Ziel-Unterordner (leer = Wurzel des Datenträgers)</label>
                    <input id="cfg-subfolder" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${cfg.subfolder || ''}" placeholder="Photobox">
                </div>
                <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;cursor:pointer;">
                    <input type="checkbox" id="cfg-gifs" ${cfg.include_gifs ? 'checked' : ''}> GIFs mitkopieren
                </label>
                <button id="btn-save-cfg" class="admin-btn admin-btn-outline" style="margin-top:1rem;">Speichern</button>
            </details>
        </div>
    `);

    setupLogout(container);

    const setMsg = (text, kind) => {
        const msg = container.querySelector('#msg');
        msg.textContent = text;
        msg.style.color = kind === 'error' ? 'var(--pb-color-error)'
            : kind === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    };

    const updateProgress = (j) => {
        const card = container.querySelector('#progress-card');
        const bar = container.querySelector('#progress-bar');
        const pmsg = container.querySelector('#progress-msg');
        if (!card || !bar) return;
        card.style.display = '';
        bar.style.width = `${j.progress || 0}%`;
        if (pmsg) pmsg.textContent = j.message || '';
        if (['completed', 'failed', 'cancelled'].includes(j.status)) {
            const btn = container.querySelector('#btn-copy');
            if (btn) btn.disabled = false;
            bar.style.background = j.status === 'completed' ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
            setMsg(j.message || '', j.status === 'completed' ? 'ok' : 'error');
        }
    };

    const ws = window.pb?.ws;
    if (ws) {
        _progressHandler = (data) => updateProgress(data);
        _completedHandler = (data) => updateProgress(data);
        ws.on('usb_export.progress', _progressHandler);
        ws.on('usb_export.completed', _completedHandler);
    }

    container.querySelector('#btn-refresh')?.addEventListener('click', () => render(container, state));

    container.querySelector('#btn-copy')?.addEventListener('click', async () => {
        const mountpoint = decodeURIComponent(container.querySelector('#drive-select')?.value || '');
        if (!mountpoint) { setMsg('Bitte ein Zielmedium auswählen.', 'error'); return; }
        const sel = container.querySelector('#source-select').value;
        const body = sel.startsWith('event:')
            ? { mountpoint, scope: 'event', event_id: parseInt(sel.split(':')[1]) }
            : { mountpoint, scope: 'all' };
        setMsg('Starte Kopiervorgang…');
        container.querySelector('#btn-copy').disabled = true;
        try {
            const res = await fetch('/api/v1/usb-export/copy', {
                method: 'POST', headers, body: JSON.stringify(body),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.detail || 'Fehler');
            container.querySelector('#progress-card').style.display = '';
            updateProgress(result);
        } catch (err) {
            setMsg('Fehler: ' + err.message, 'error');
            container.querySelector('#btn-copy').disabled = false;
        }
    });

    container.querySelector('#btn-cancel')?.addEventListener('click', async () => {
        await fetch('/api/v1/usb-export/cancel', { method: 'POST', headers });
        setMsg('Abbruch angefordert…');
    });

    container.querySelector('#btn-save-cfg')?.addEventListener('click', async () => {
        const payload = {
            subfolder: container.querySelector('#cfg-subfolder').value,
            include_gifs: container.querySelector('#cfg-gifs').checked,
        };
        try {
            const res = await fetch('/api/v1/usb-export/configure', {
                method: 'POST', headers, body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error((await res.json()).detail);
            setMsg('Einstellungen gespeichert!', 'ok');
        } catch (err) {
            setMsg('Fehler: ' + err.message, 'error');
        }
    });
}
