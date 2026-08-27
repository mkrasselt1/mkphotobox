import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let settings = {};
    try {
        settings = await fetch('/api/v1/settings/', { headers }).then(r => r.json());
    } catch {}

    let adminAccess = { local_only: false, allowed_ips: [], your_ip: '' };
    try {
        adminAccess = await fetch('/api/v1/system/admin-access', { headers }).then(r => r.json());
    } catch {}

    const currentPreview = settings?.display?.preview_size || 'medium';
    const galleryEnabled = settings?.gallery?.enabled !== false;
    const deleteMode = settings?.gallery?.delete_mode || 'off';
    const deleteMinutes = settings?.gallery?.delete_recent_minutes ?? 5;

    const selectStyle = `padding:0.75rem 1rem;border-radius:8px;border:1px solid #333;
        background:var(--pb-color-surface);color:var(--pb-color-text);
        font-size:1rem;width:100%;max-width:300px;cursor:pointer;`;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Einstellungen</h1>
        <div style="max-width:700px;">

            <div class="admin-card" style="margin-bottom:1.5rem;">
                <h3>Anzeige</h3>
                <div style="margin-top:1rem;">
                    <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Vorschaubild-Größe</label>
                    <select id="preview-size-select" style="${selectStyle}">
                        ${[
                            { value: 'small', label: 'Klein (320px)' },
                            { value: 'medium', label: 'Mittel (640px)' },
                            { value: 'large', label: 'Groß (960px)' },
                            { value: 'fullscreen', label: 'Vollbild' },
                        ].map(o => `<option value="${o.value}" ${o.value === currentPreview ? 'selected' : ''}>${o.label}</option>`).join('')}
                    </select>
                    <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                        Im Vollbild-Modus werden Tasten halbtransparent über dem Kamerabild angezeigt.
                    </p>
                </div>
                <div style="margin-top:1.25rem;">
                    <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Sicherer Rand (Pixel)</label>
                    <input id="safe-margin" type="number" min="0" max="200" step="5"
                           value="${Number(settings?.display?.safe_margin) || 0}" style="${selectStyle}">
                    <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                        Wenn am Bildschirmrand etwas fehlt: hochdrehen, bis alles zu sehen ist.
                        Viele Kiosk-Bildschirme zeigen nicht das ganze Bild — analoge VGA-Panels sitzen
                        oft ein Stück daneben, Fernseher schneiden per Overscan ab, Einbaurahmen
                        verdecken den Rest. Das lässt sich nicht messen, nur sehen. 20 bis 40 reichen meist.
                    </p>
                </div>
                <div style="margin-top:1.25rem;">
                    <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Speicheranzeige im Booth</label>
                    <select id="storage-badge" style="${selectStyle}">
                        ${[
                            { value: 'low', label: 'Nur wenn es eng wird' },
                            { value: 'always', label: 'Immer anzeigen' },
                            { value: 'never', label: 'Nie anzeigen' },
                        ].map(o => `<option value="${o.value}" ${o.value === (settings?.display?.storage_badge || 'low') ? 'selected' : ''}>${o.label}</option>`).join('')}
                    </select>
                    <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                        Die freie Plattenkapazität interessiert die Gäste nicht — sichtbar sein muss sie erst,
                        wenn es knapp wird. „Immer" ist für den Aufbau nützlich.
                    </p>
                </div>
            </div>

            <div class="admin-card" style="margin-bottom:1.5rem;">
                <h3>Galerie</h3>
                <div style="margin-top:1rem;display:flex;flex-direction:column;gap:1rem;">
                    <label style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;">
                        <input type="checkbox" id="gallery-enabled" ${galleryEnabled ? 'checked' : ''}
                            style="width:20px;height:20px;accent-color:var(--pb-color-primary);cursor:pointer;">
                        <span>Galerie auf der Startseite anzeigen</span>
                    </label>
                    <div>
                        <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Fotos löschen erlauben</label>
                        <select id="delete-mode-select" style="${selectStyle}">
                            <option value="off" ${deleteMode === 'off' ? 'selected' : ''}>Aus — Löschen nicht möglich</option>
                            <option value="recent" ${deleteMode === 'recent' ? 'selected' : ''}>Nur kürzlich aufgenommene Fotos</option>
                            <option value="all" ${deleteMode === 'all' ? 'selected' : ''}>Alle Fotos löschbar</option>
                        </select>
                    </div>
                    <div id="delete-minutes-row" style="display:${deleteMode === 'recent' ? 'block' : 'none'};">
                        <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Zeitfenster (Minuten)</label>
                        <input type="number" id="delete-minutes" value="${deleteMinutes}" min="1" max="60"
                            style="padding:0.6rem;border-radius:6px;border:1px solid #333;background:#0e1a30;color:white;font-size:1rem;width:100px;">
                        <p style="margin-top:0.25rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                            Fotos können nur innerhalb dieses Zeitfensters nach der Aufnahme gelöscht werden.
                        </p>
                    </div>
                </div>
            </div>

            <div class="admin-card" style="margin-bottom:1.5rem;">
                <h3>Admin-Zugriff (Sicherheit)</h3>
                <div style="margin-top:1rem;display:flex;flex-direction:column;gap:1rem;">
                    <label style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;">
                        <input type="checkbox" id="admin-local-only" ${adminAccess.local_only ? 'checked' : ''}
                            style="width:20px;height:20px;accent-color:var(--pb-color-primary);cursor:pointer;">
                        <span>Admin nur lokal erreichbar (localhost + erlaubte IPs)</span>
                    </label>
                    <div>
                        <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Erlaubte IP-Adressen (kommagetrennt)</label>
                        <input type="text" id="admin-allowed-ips" value="${(adminAccess.allowed_ips || []).join(', ')}"
                            placeholder="z.B. 192.168.16.50, 192.168.16.51"
                            style="padding:0.6rem;border-radius:6px;border:1px solid #333;background:#0e1a30;color:white;font-size:1rem;width:100%;max-width:420px;">
                        <p style="margin-top:0.25rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                            Deine aktuelle IP (<code>${adminAccess.your_ip || '?'}</code>) wird beim Aktivieren automatisch ergänzt — damit du dich nicht aussperrst.
                        </p>
                    </div>
                    <div>
                        <button id="btn-save-admin-access" class="admin-btn admin-btn-primary">Admin-Zugriff speichern</button>
                        <span id="admin-access-status" style="margin-left:0.75rem;font-size:0.85rem;"></span>
                    </div>
                </div>
            </div>

            <button id="btn-save-all" style="
                padding:0.75rem 2rem;border-radius:8px;border:none;
                background:var(--pb-color-primary);color:white;cursor:pointer;font-size:1rem;
                margin-bottom:1rem;
            ">Alle Einstellungen speichern</button>
            <span id="save-status" style="margin-left:0.75rem;font-size:0.85rem;display:none;"></span>

            <div class="admin-card" style="margin-top:1rem;">
                <h3>Aktuelle Konfiguration</h3>
                <pre style="background:#0a0e1a;padding:1rem;border-radius:8px;overflow:auto;max-height:60vh;font-size:0.8rem;color:var(--pb-color-text-muted);white-space:pre-wrap;">${JSON.stringify(settings, null, 2)}</pre>
            </div>
        </div>
    `);

    setupLogout(container);

    // Admin-Zugriff (local-only) speichern
    container.querySelector('#btn-save-admin-access')?.addEventListener('click', async () => {
        const st = container.querySelector('#admin-access-status');
        const payload = {
            local_only: container.querySelector('#admin-local-only').checked,
            allowed_ips: container.querySelector('#admin-allowed-ips').value,
        };
        try {
            const res = await fetch('/api/v1/system/admin-access', { method: 'POST', headers, body: JSON.stringify(payload) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
            const r = await res.json();
            st.textContent = `Gespeichert (erlaubt: ${r.allowed_ips.join(', ') || 'nur localhost'})`;
            st.style.color = 'var(--pb-color-success)';
        } catch (err) {
            st.textContent = 'Fehler: ' + err.message;
            st.style.color = 'var(--pb-color-error)';
        }
    });

    // Show/hide minutes input based on delete mode
    container.querySelector('#delete-mode-select')?.addEventListener('change', (e) => {
        const row = container.querySelector('#delete-minutes-row');
        row.style.display = e.target.value === 'recent' ? 'block' : 'none';
    });

    // Save all settings
    container.querySelector('#btn-save-all')?.addEventListener('click', async () => {
        const status = container.querySelector('#save-status');
        const saves = [
            { key: 'display.preview_size', value: container.querySelector('#preview-size-select').value },
            { key: 'display.safe_margin',
              value: Math.max(0, Math.min(200, parseInt(container.querySelector('#safe-margin').value) || 0)) },
            { key: 'display.storage_badge', value: container.querySelector('#storage-badge').value },
            { key: 'gallery.enabled', value: container.querySelector('#gallery-enabled').checked },
            { key: 'gallery.delete_mode', value: container.querySelector('#delete-mode-select').value },
            { key: 'gallery.delete_recent_minutes', value: parseInt(container.querySelector('#delete-minutes').value) || 5 },
        ];

        try {
            const results = await Promise.all(saves.map(s =>
                fetch(`/api/v1/settings/${s.key}`, {
                    method: 'PUT',
                    headers,
                    body: JSON.stringify({ key: s.key, value: s.value }),
                })
            ));

            const allOk = results.every(r => r.ok);
            status.style.display = 'inline';
            if (allOk) {
                status.textContent = 'Gespeichert!';
                status.style.color = 'var(--pb-color-success)';
            } else {
                status.textContent = 'Teilweise fehlgeschlagen';
                status.style.color = 'var(--pb-color-error)';
            }
            setTimeout(() => { status.style.display = 'none'; }, 2500);
        } catch (err) {
            status.style.display = 'inline';
            status.textContent = `Fehler (${err.message || 'Netzwerk'})`;
            status.style.color = 'var(--pb-color-error)';
        }
    });
}
