import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

// Module-level so we can detach stale handlers when the page is re-entered.
let _progressHandler = null;
let _completedHandler = null;

function detachWs() {
    const ws = window.pb?.ws;
    if (!ws) return;
    if (_progressHandler) ws.off('cd_burn.progress', _progressHandler);
    if (_completedHandler) ws.off('cd_burn.completed', _completedHandler);
    _progressHandler = _completedHandler = null;
}

export async function render(container, state) {
    const headers = getHeaders();
    detachWs();

    let status = {}, sources = { events: [], total_photos: 0 };
    try {
        [status, sources] = await Promise.all([
            fetch('/api/v1/cd-burn/status').then(r => r.json()),
            fetch('/api/v1/cd-burn/sources', { headers }).then(r => r.json()),
        ]);
    } catch {}

    const cfg = status.config || {};
    const media = status.media || {};

    if (!status.available) {
        container.innerHTML = adminShell(`
            <h1 style="margin-bottom:1.5rem;">CD/DVD brennen</h1>
            <div class="admin-card">
                <h3>Nicht verfügbar</h3>
                <p>${media.reason || 'Das Brenn-Werkzeug (xorriso) ist nicht installiert.'}</p>
                <p style="margin-top:0.5rem;">Installieren mit: <code>sudo apt install xorriso</code></p>
            </div>
        `);
        setupLogout(container);
        return;
    }

    const mediaLine = media.present
        ? `${media.media_type || 'Medium'} — ${media.status || ''}${media.free_mb != null ? ` · ${Math.round(media.free_mb)} MB frei` : ''}`
        : 'Kein Medium eingelegt';
    const mediaColor = media.present && media.writable ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';

    const job = status.job || {};
    const burning = status.busy;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">CD/DVD brennen</h1>
        <div style="max-width:650px;">

            <div class="admin-card">
                <h3>Laufwerk &amp; Medium</h3>
                <p><strong>Laufwerk:</strong> ${cfg.device || '/dev/sr0'}</p>
                <p style="color:${mediaColor};"><strong>Medium:</strong> ${mediaLine}</p>
                ${media.present && !media.writable
                    ? `<p style="color:var(--pb-color-error);">${media.reason || 'Medium nicht beschreibbar.'}</p>` : ''}
                <button id="btn-refresh" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;">Aktualisieren</button>
            </div>

            <div class="admin-card">
                <h3>Was soll gebrannt werden?</h3>
                <select id="source-select" class="admin-input" style="width:100%;">
                    <option value="all">Alle Fotos (${sources.total_photos || 0})</option>
                    ${(sources.events || []).map(e =>
                        `<option value="event:${e.event_id}">${e.name} (${e.photo_count})${e.is_active ? ' — aktiv' : ''}</option>`
                    ).join('')}
                </select>
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-top:0.5rem;">
                    ${cfg.include_gifs ? 'Animierte GIFs werden mitgebrannt.' : 'GIFs werden nicht gebrannt.'}
                </p>
            </div>

            <div class="admin-card" id="progress-card" style="${burning ? '' : 'display:none;'}">
                <h3>Brennvorgang</h3>
                <div style="background:#0e1a30;border-radius:8px;overflow:hidden;height:24px;">
                    <div id="progress-bar" style="height:100%;width:${job.progress || 0}%;background:var(--pb-color-primary);transition:width 0.3s;"></div>
                </div>
                <p id="progress-msg" style="margin-top:0.5rem;font-size:0.9rem;">${job.message || ''}</p>
                <button id="btn-cancel" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;">Abbrechen</button>
            </div>

            <div style="display:flex;gap:0.75rem;margin-top:0.5rem;">
                <button id="btn-burn" class="admin-btn admin-btn-primary" ${burning ? 'disabled' : ''}>
                    Brennen starten
                </button>
            </div>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>

            <details class="admin-card" style="margin-top:1rem;">
                <summary style="cursor:pointer;color:var(--pb-color-primary);">Brenner-Einstellungen</summary>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem;">
                    <div>
                        <label style="font-size:0.9rem;">Laufwerk</label>
                        <input id="cfg-device" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${cfg.device || '/dev/sr0'}">
                    </div>
                    <div>
                        <label style="font-size:0.9rem;">Datenträgername</label>
                        <input id="cfg-label" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${cfg.volume_label || 'PHOTOBOX'}">
                    </div>
                    <div>
                        <label style="font-size:0.9rem;">Geschwindigkeit (leer = auto)</label>
                        <input id="cfg-speed" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${cfg.speed || ''}" placeholder="z.B. 8">
                    </div>
                </div>
                <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;cursor:pointer;">
                    <input type="checkbox" id="cfg-gifs" ${cfg.include_gifs ? 'checked' : ''}> GIFs mitbrennen
                </label>
                <label style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem;cursor:pointer;">
                    <input type="checkbox" id="cfg-eject" ${cfg.eject_when_done ? 'checked' : ''}> Nach dem Brennen auswerfen
                </label>
                <button id="btn-save-cfg" class="admin-btn admin-btn-outline" style="margin-top:1rem;">Einstellungen speichern</button>
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
            const burnBtn = container.querySelector('#btn-burn');
            if (burnBtn) burnBtn.disabled = false;
            bar.style.background = j.status === 'completed' ? 'var(--pb-color-success)'
                : 'var(--pb-color-error)';
            setMsg(j.message || '', j.status === 'completed' ? 'ok' : 'error');
        }
    };

    // Live progress via WebSocket
    const ws = window.pb?.ws;
    if (ws) {
        _progressHandler = (data) => updateProgress(data);
        _completedHandler = (data) => updateProgress(data);
        ws.on('cd_burn.progress', _progressHandler);
        ws.on('cd_burn.completed', _completedHandler);
    }

    container.querySelector('#btn-refresh')?.addEventListener('click', () => render(container, state));

    container.querySelector('#btn-burn')?.addEventListener('click', async () => {
        const sel = container.querySelector('#source-select').value;
        const body = sel.startsWith('event:')
            ? { scope: 'event', event_id: parseInt(sel.split(':')[1]) }
            : { scope: 'all' };
        setMsg('Starte Brennvorgang…');
        container.querySelector('#btn-burn').disabled = true;
        try {
            const res = await fetch('/api/v1/cd-burn/burn', {
                method: 'POST', headers, body: JSON.stringify(body),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.detail || 'Fehler');
            container.querySelector('#progress-card').style.display = '';
            updateProgress(result);
        } catch (err) {
            setMsg('Fehler: ' + err.message, 'error');
            container.querySelector('#btn-burn').disabled = false;
        }
    });

    container.querySelector('#btn-cancel')?.addEventListener('click', async () => {
        await fetch('/api/v1/cd-burn/cancel', { method: 'POST', headers });
        setMsg('Abbruch angefordert…');
    });

    container.querySelector('#btn-save-cfg')?.addEventListener('click', async () => {
        const payload = {
            device: container.querySelector('#cfg-device').value,
            volume_label: container.querySelector('#cfg-label').value,
            speed: container.querySelector('#cfg-speed').value,
            include_gifs: container.querySelector('#cfg-gifs').checked,
            eject_when_done: container.querySelector('#cfg-eject').checked,
        };
        try {
            const res = await fetch('/api/v1/cd-burn/configure', {
                method: 'POST', headers, body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error((await res.json()).detail);
            setMsg('Einstellungen gespeichert!', 'ok');
        } catch (err) {
            setMsg('Fehler: ' + err.message, 'error');
        }
    });
}
