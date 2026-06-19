import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();
    let timer = null;

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

    function draw(n) {
        if (n.error) {
            container.innerHTML = adminShell(`<h1 style="margin-bottom:1.5rem;">Netzwerk</h1>
                <div class="admin-card"><h3>Fehler</h3><p>${n.error}</p></div>`);
            setupLogout(container);
            return;
        }

        const ts = n.tailscale || {};
        const tsRunning = ts.available && ts.backend_state === 'Running';

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

        let tsBox;
        if (!ts.available) {
            tsBox = `<p style="color:var(--pb-color-text-muted);">${ts.reason || 'Tailscale nicht verfügbar.'}</p>`;
        } else {
            tsBox = `
                <p>${dot(tsRunning)} <strong>Status:</strong> ${tsRunning ? 'Verbunden' : (ts.backend_state || 'unbekannt')}</p>
                ${ts.dns_name ? `<p><strong>Name:</strong> <span style="font-family:monospace;">${ts.dns_name}</span></p>` : ''}
                <p><strong>Tailscale-IP:</strong> <span style="font-family:monospace;color:var(--pb-color-primary);">${ts.self_ip || '—'}</span></p>
                <p><strong>Geräte online:</strong> ${ts.peers_online ?? '?'} / ${ts.peers_total ?? '?'}</p>`;
        }

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
                    ${tsBox}
                </div>

                <p style="font-size:0.8rem;color:var(--pb-color-text-muted);">Aktualisiert sich automatisch alle 8 Sekunden.</p>
            </div>
        `);

        setupLogout(container);
        container.querySelector('#btn-refresh')?.addEventListener('click', refresh);
    }

    async function refresh() {
        draw(await load());
    }

    await refresh();

    // auto-refresh while this page is shown; stop when navigating away
    timer = setInterval(async () => {
        if (!document.body.contains(container) || !location.hash.includes('admin/network')) {
            clearInterval(timer);
            return;
        }
        draw(await load());
    }, 8000);
}
