import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();
    let data = { config: {}, state: {}, protocols: ['webdav', 'ftps', 'ftp', 'rsync', 'scp'] };
    try { data = await fetch('/api/v1/remote-gallery/status', { headers }).then(r => r.json()); } catch {}
    let tunnel = { enabled: false, installed: false, service_active: false, url: '' };
    try { tunnel = await fetch('/api/v1/system/tunnel', { headers }).then(r => r.json()); } catch {}
    const c = data.config || {};
    const st = data.state || {};
    const protos = data.protocols || ['webdav', 'ftps', 'ftp', 'rsync', 'scp'];
    const proto = c.protocol || 'webdav';

    const PROTO_LABEL = { webdav: 'WebDAV (Nextcloud/ownCloud …)', ftps: 'FTPS (FTP über TLS)', ftp: 'FTP (unverschlüsselt)', rsync: 'rsync über SSH', scp: 'SCP über SSH' };

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:0.5rem;">Online-Galerie (Server-Sync)</h1>
        <p style="color:var(--pb-color-text-muted);max-width:680px;margin-bottom:1.25rem;font-size:0.9rem;">
            Schiebt <strong>jedes neue Foto</strong> (samt GIF) automatisch auf einen externen Server und legt dort eine
            laufend aktualisierte <code>photos.json</code> + einen Live-Viewer (<code>index.html</code>) ab — die Galerie
            läuft dann komplett auf deinem Server. Transport wählbar.
        </p>
        <div style="max-width:600px;">
            <div class="admin-card" style="display:flex;align-items:center;gap:0.75rem;">
                <span id="st-dot" style="width:12px;height:12px;border-radius:50%;background:${st.enabled ? (st.last_error ? 'var(--pb-color-error)' : 'var(--pb-color-success)') : '#888'};"></span>
                <div style="flex:1;font-size:0.9rem;">
                    <strong>${st.enabled ? 'Aktiv' : 'Deaktiviert'}</strong>
                    · hochgeladen: ${st.uploaded || 0} · Warteschlange: ${st.queued || 0}${st.skipped ? ` · übersprungen: ${st.skipped}` : ''}
                    ${st.last_error ? `<div style="color:var(--pb-color-error);font-size:0.82rem;">Fehler: ${st.last_error}</div>` : ''}
                    ${st.last_ok ? `<div style="color:var(--pb-color-text-muted);font-size:0.8rem;">Zuletzt ok: ${new Date(st.last_ok + 'Z').toLocaleString()}</div>` : ''}
                </div>
            </div>

            <div class="admin-card">
                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-bottom:0.75rem;">
                    <input type="checkbox" id="f-enabled" ${c.enabled ? 'checked' : ''}> <strong>Aktivieren</strong>
                </label>
                <label style="font-size:0.85rem;">Transport</label>
                <select id="f-protocol" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">
                    ${protos.map(p => `<option value="${p}" ${p === proto ? 'selected' : ''}>${PROTO_LABEL[p] || p}</option>`).join('')}
                </select>

                <div id="webdav-fields" style="display:${proto === 'webdav' ? 'block' : 'none'};">
                    <label style="font-size:0.85rem;">WebDAV-URL (Ordner)</label>
                    <input id="f-url" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;" placeholder="https://cloud.example.com/remote.php/dav/files/USER/Galerie" value="${c.url || ''}">
                </div>

                <div id="ssh-fields" style="display:${['ftps', 'ftp', 'rsync', 'scp'].includes(proto) ? 'block' : 'none'};">
                    <div style="display:grid;grid-template-columns:2fr 1fr;gap:0.5rem;">
                        <div><label style="font-size:0.85rem;">Host</label><input id="f-host" class="admin-input" style="width:100%;" placeholder="server.example.com" value="${c.host || ''}"></div>
                        <div><label style="font-size:0.85rem;">Port</label><input id="f-port" type="number" class="admin-input" style="width:100%;" placeholder="${proto === 'ftp' || proto === 'ftps' ? '21' : '22'}" value="${c.port || ''}"></div>
                    </div>
                    <label style="font-size:0.85rem;margin-top:0.5rem;display:block;">Ziel-Ordner (auf dem Server)</label>
                    <input id="f-remote_dir" class="admin-input" style="width:100%;margin-top:0.25rem;" placeholder="galerie" value="${c.remote_dir || ''}">
                    <div id="key-field" style="display:${['rsync', 'scp'].includes(proto) ? 'block' : 'none'};">
                        <label style="font-size:0.85rem;margin-top:0.5rem;display:block;">SSH-Key-Datei (optional, sonst Passwort)</label>
                        <input id="f-key_path" class="admin-input" style="width:100%;margin-top:0.25rem;" placeholder="/home/photobooth/.ssh/id_ed25519" value="${c.key_path || ''}">
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.75rem;">
                    <div><label style="font-size:0.85rem;">Benutzer</label><input id="f-username" class="admin-input" style="width:100%;" value="${c.username || ''}"></div>
                    <div><label style="font-size:0.85rem;">Passwort ${c.has_password ? '(gesetzt)' : ''}</label><input id="f-password" type="password" class="admin-input" style="width:100%;" placeholder="${c.has_password ? '•••••• (unverändert)' : ''}"></div>
                </div>

                <label style="font-size:0.85rem;margin-top:0.75rem;display:block;">Öffentliche URL der Galerie (für QR/Link, optional)</label>
                <input id="f-public_url" class="admin-input" style="width:100%;margin-top:0.25rem;" placeholder="https://example.com/galerie/" value="${c.public_url || ''}">
                <label style="font-size:0.85rem;margin-top:0.75rem;display:block;">Galerie-Titel</label>
                <input id="f-title" class="admin-input" style="width:100%;margin-top:0.25rem;" placeholder="Foto-Galerie" value="${c.title || ''}">
            </div>

            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                <button id="btn-save" class="admin-btn admin-btn-primary">Speichern</button>
                <button id="btn-test" class="admin-btn admin-btn-outline">Verbindung testen</button>
                <button id="btn-resync" class="admin-btn admin-btn-outline" title="Gleicht ab, was schon auf dem Server liegt, und lädt nur Fehlendes hoch">Abgleichen &amp; Fehlendes hochladen</button>
            </div>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>
            <p style="margin-top:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                Hinweis: Für rsync/scp mit Passwort muss auf der Box <code>sshpass</code> installiert sein — sonst SSH-Key nutzen.
            </p>

            <h2 style="margin-top:2rem;margin-bottom:0.4rem;font-size:1.15rem;">Cloudflare Quick-Tunnel</h2>
            <p style="color:var(--pb-color-text-muted);font-size:0.85rem;margin-bottom:0.75rem;">
                Macht die QR-Codes (Foto/GIF/Galerie) <strong>ohne Account</strong> aus dem Internet erreichbar — für Gäste-Handys,
                die nicht im WLAN der Box sind. Die Anzeige in der Steuerung bleibt lokal.
            </p>
            <div class="admin-card">
                ${tunnel.installed ? '' : `<p style="color:var(--pb-color-error);font-size:0.85rem;margin-top:0;">
                    <code>cloudflared</code> ist nicht installiert — auf der Box <code>sudo ./scripts/cloudflared-setup.sh</code> ausführen
                    (oder beim Setup <code>WITH_CLOUDFLARE=1</code>).</p>`}
                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                    <input type="checkbox" id="f-tunnel" ${tunnel.enabled ? 'checked' : ''} ${tunnel.installed ? '' : 'disabled'}>
                    <strong>Tunnel aktivieren</strong>
                </label>
                <div id="tunnel-status" style="margin-top:0.6rem;font-size:0.85rem;color:var(--pb-color-text-muted);">
                    <span id="tunnel-dot" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${tunnel.service_active ? 'var(--pb-color-success)' : '#888'};margin-right:0.4rem;"></span>
                    <span id="tunnel-state">${tunnel.service_active ? 'Läuft' : 'Gestoppt'}</span>
                    ${tunnel.url ? `· URL: <a href="${tunnel.url}" target="_blank" style="color:var(--pb-color-primary);word-break:break-all;">${tunnel.url}</a>` : ''}
                </div>
            </div>
        </div>
    `);
    setupLogout(container);

    const setMsg = (t, k) => { const m = container.querySelector('#msg'); m.textContent = t; m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)'; };

    container.querySelector('#f-protocol').addEventListener('change', (e) => {
        const p = e.target.value;
        container.querySelector('#webdav-fields').style.display = p === 'webdav' ? 'block' : 'none';
        container.querySelector('#ssh-fields').style.display = ['ftps', 'ftp', 'rsync', 'scp'].includes(p) ? 'block' : 'none';
        container.querySelector('#key-field').style.display = ['rsync', 'scp'].includes(p) ? 'block' : 'none';
    });

    const collect = () => ({
        enabled: container.querySelector('#f-enabled').checked,
        protocol: container.querySelector('#f-protocol').value,
        url: container.querySelector('#f-url').value.trim(),
        host: container.querySelector('#f-host').value.trim(),
        port: container.querySelector('#f-port').value.trim(),
        remote_dir: container.querySelector('#f-remote_dir').value.trim(),
        key_path: container.querySelector('#f-key_path').value.trim(),
        username: container.querySelector('#f-username').value.trim(),
        password: container.querySelector('#f-password').value,
        public_url: container.querySelector('#f-public_url').value.trim(),
        title: container.querySelector('#f-title').value.trim(),
    });

    async function save() {
        const res = await fetch('/api/v1/remote-gallery/configure', { method: 'POST', headers, body: JSON.stringify(collect()) });
        if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
        return res.json();
    }

    container.querySelector('#btn-save').addEventListener('click', async () => {
        setMsg('Speichere…');
        try { await save(); setMsg('Gespeichert!', 'ok'); } catch (e) { setMsg('Fehler: ' + e.message, 'error'); }
    });

    container.querySelector('#btn-test').addEventListener('click', async () => {
        setMsg('Speichere & teste Verbindung…');
        try {
            await save();
            const r = await fetch('/api/v1/remote-gallery/test', { method: 'POST', headers }).then(r => r.json());
            setMsg(r.ok ? '✓ ' + r.message : '✗ ' + r.message, r.ok ? 'ok' : 'error');
        } catch (e) { setMsg('Fehler: ' + e.message, 'error'); }
    });

    const tunnelToggle = container.querySelector('#f-tunnel');
    if (tunnelToggle) {
        tunnelToggle.addEventListener('change', async (e) => {
            const enabled = e.target.checked;
            const stateEl = container.querySelector('#tunnel-state');
            const dotEl = container.querySelector('#tunnel-dot');
            const statusEl = container.querySelector('#tunnel-status');
            stateEl.textContent = enabled ? 'Starte…' : 'Stoppe…';
            e.target.disabled = true;
            try {
                const r = await fetch('/api/v1/system/tunnel', {
                    method: 'POST', headers, body: JSON.stringify({ enabled }),
                }).then(r => r.json());
                dotEl.style.background = r.service_active ? 'var(--pb-color-success)' : '#888';
                stateEl.textContent = r.service_active ? 'Läuft' : 'Gestoppt';
                let extra = '';
                if (r.url) extra = ` · URL: <a href="${r.url}" target="_blank" style="color:var(--pb-color-primary);word-break:break-all;">${r.url}</a>`;
                else if (enabled) extra = ' · <span style="color:var(--pb-color-text-muted);">URL wird vergeben… (ein paar Sekunden, dann Seite neu laden)</span>';
                if (r.error) extra += ` <span style="color:var(--pb-color-error);">(${r.error})</span>`;
                statusEl.innerHTML = `<span id="tunnel-dot" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${r.service_active ? 'var(--pb-color-success)' : '#888'};margin-right:0.4rem;"></span><span id="tunnel-state">${r.service_active ? 'Läuft' : 'Gestoppt'}</span>${extra}`;
            } catch (err) {
                stateEl.textContent = 'Fehler: ' + err.message;
            } finally {
                e.target.disabled = false;
            }
        });
    }

    container.querySelector('#btn-resync').addEventListener('click', async () => {
        if (!confirm('Alle Fotos des aktiven Events abgleichen? Vorhandene werden übersprungen, nur Fehlendes wird hochgeladen.')) return;
        setMsg('Speichere & gleiche ab…');
        try {
            await save();
            const r = await fetch('/api/v1/remote-gallery/resync', { method: 'POST', headers }).then(r => r.json());
            setMsg(r.status === 'ok' ? `✓ ${r.queued} Fotos werden geprüft — nur Fehlendes wird hochgeladen (Status oben).` : '✗ ' + (r.message || 'Fehler'), r.status === 'ok' ? 'ok' : 'error');
        } catch (e) { setMsg('Fehler: ' + e.message, 'error'); }
    });
}
