import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    // Load data
    let info = {}, modules = {};
    try {
        [info, modules] = await Promise.all([
            fetch('/api/v1/system/info', { headers }).then(r => r.json()),
            fetch('/api/v1/modules', { headers }).then(r => r.json()),
        ]);
    } catch {}

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Dashboard</h1>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;">
            <div class="admin-card">
                <h3>System</h3>
                <p>Uptime: ${Math.round((info.uptime_seconds || 0) / 60)} min</p>
                <p>Disk: ${info.disk_free_mb || '?'} MB frei</p>
                <p>Fotos: ${info.photos_count ?? '?'}</p>
                <p>WS: ${info.ws_connections ?? 0} Verbindungen</p>
            </div>
            <div class="admin-card">
                <h3>Kameras</h3>
                ${(modules.cameras || []).map(c =>
                    `<p>${c.name}: ${c.available ? '&#10003; aktiv' : '&#10007;'}</p>`
                ).join('') || '<p>Keine geladen</p>'}
            </div>
            <div class="admin-card">
                <h3>Ausgabe</h3>
                ${(modules.outputs || []).map(o => `<p>${o.name}: &#10003;</p>`).join('') || '<p>Keine</p>'}
            </div>
            <div class="admin-card">
                <h3>Ausl&ouml;ser</h3>
                ${(modules.triggers || []).map(t => `<p>${t.name}: &#10003;</p>`).join('') || '<p>Keine</p>'}
            </div>
        </div>
        <div style="margin-top:1.5rem;">
            <button id="btn-restart" class="admin-btn admin-btn-primary" style="background:var(--pb-color-error);">
                Server neu starten
            </button>
            <span id="restart-status" style="margin-left:0.75rem;font-size:0.85rem;display:none;"></span>
        </div>
    `);

    setupLogout(container);

    container.querySelector('#btn-restart')?.addEventListener('click', async () => {
        if (!confirm('Server wirklich neu starten?')) return;
        const status = container.querySelector('#restart-status');
        const btn = container.querySelector('#btn-restart');
        btn.disabled = true;
        btn.textContent = 'Wird neu gestartet...';
        try {
            await fetch('/api/v1/system/restart', { method: 'POST', headers });
            status.style.display = 'inline';
            status.textContent = 'Neustart läuft... Seite lädt gleich neu.';
            status.style.color = 'var(--pb-color-success)';
            // Wait for server to come back, then reload
            setTimeout(() => {
                const check = setInterval(async () => {
                    try {
                        const r = await fetch('/api/v1/system/health');
                        if (r.ok) { clearInterval(check); location.reload(); }
                    } catch {}
                }, 1000);
            }, 2000);
        } catch {
            status.style.display = 'inline';
            status.textContent = 'Fehler beim Neustart';
            status.style.color = 'var(--pb-color-error)';
            btn.disabled = false;
            btn.textContent = 'Server neu starten';
        }
    });
}
