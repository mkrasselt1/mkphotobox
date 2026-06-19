import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let events = [];
    try {
        events = await fetch('/api/v1/events/', { headers }).then(r => r.json());
    } catch {}

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Veranstaltungen</h1>
        <div style="max-width:600px;">
            ${events.map(e => `
                <div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <strong>${e.name}</strong>
                        <small style="color:var(--pb-color-text-muted);margin-left:0.5rem;">(${e.slug})</small>
                        ${e.is_active ? '<span style="color:var(--pb-color-success);margin-left:0.5rem;">&#9679; aktiv</span>' : ''}
                    </div>
                    ${!e.is_active ? `<button class="admin-btn admin-btn-outline btn-activate" data-slug="${e.slug}">Aktivieren</button>` : ''}
                </div>
            `).join('') || '<div class="admin-card"><p>Keine Veranstaltungen</p></div>'}
        </div>
    `);

    setupLogout(container);

    container.querySelectorAll('.btn-activate').forEach(btn => {
        btn.addEventListener('click', async () => {
            await fetch(`/api/v1/events/${btn.dataset.slug}/activate`, { method: 'POST', headers });
            render(container, state);
        });
    });
}
