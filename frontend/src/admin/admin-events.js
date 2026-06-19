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
                <div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;">
                    <div>
                        <strong>${e.name}</strong>
                        <small style="color:var(--pb-color-text-muted);margin-left:0.5rem;">(${e.slug})</small>
                        ${e.is_active ? '<span style="color:var(--pb-color-success);margin-left:0.5rem;">&#9679; aktiv</span>' : ''}
                    </div>
                    <div style="display:flex;gap:0.5rem;">
                        ${!e.is_active ? `<button class="admin-btn admin-btn-outline btn-activate" data-slug="${e.slug}">Aktivieren</button>` : ''}
                        <button class="admin-btn admin-btn-outline btn-delete" data-slug="${e.slug}" data-name="${e.name}"
                            style="color:var(--pb-color-error);border-color:var(--pb-color-error);">Löschen</button>
                    </div>
                </div>
            `).join('') || '<div class="admin-card"><p>Keine Veranstaltungen</p></div>'}
        </div>
        <div id="evt-modal"></div>
    `);

    setupLogout(container);

    container.querySelectorAll('.btn-activate').forEach(btn => {
        btn.addEventListener('click', async () => {
            await fetch(`/api/v1/events/${btn.dataset.slug}/activate`, { method: 'POST', headers });
            render(container, state);
        });
    });

    container.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', () => openDeleteDialog(btn.dataset.slug, btn.dataset.name));
    });

    function openDeleteDialog(slug, name) {
        const modal = container.querySelector('#evt-modal');
        modal.innerHTML = `
        <div style="position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;padding:1.5rem;">
            <div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:480px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
                <h2 style="margin:0 0 0.5rem;">„${name}" löschen?</h2>
                <p style="color:var(--pb-color-text-muted);margin:0 0 1rem;font-size:0.9rem;">
                    Die Veranstaltung wird entfernt. Wähle, was zusätzlich gelöscht werden soll:
                </p>
                <div style="display:flex;flex-direction:column;gap:0.7rem;margin-bottom:1.25rem;">
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-photos" checked style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Fotos (Bilder + Thumbnails)
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-gifs" checked style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> GIFs
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-templates" style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Zugewiesene Vorlagen
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-assets" style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Rahmen/Muster (nur ungenutzte)
                    </label>
                    <p style="font-size:0.78rem;color:var(--pb-color-text-muted);margin:0;">
                        Rahmen/Muster werden nur entfernt, wenn keine andere Vorlage sie noch verwendet.
                    </p>
                </div>
                <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
                    <button id="del-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                    <button id="del-confirm" class="admin-btn admin-btn-primary" style="background:var(--pb-color-error);">Endgültig löschen</button>
                </div>
                <p id="del-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
            </div>
        </div>`;

        const close = () => { modal.innerHTML = ''; };
        modal.querySelector('#del-cancel').addEventListener('click', close);

        modal.querySelector('#del-confirm').addEventListener('click', async () => {
            const payload = {
                photos: modal.querySelector('#del-photos').checked,
                gifs: modal.querySelector('#del-gifs').checked,
                templates: modal.querySelector('#del-templates').checked,
                assets: modal.querySelector('#del-assets').checked,
            };
            const msg = modal.querySelector('#del-msg');
            msg.textContent = 'Lösche…'; msg.style.color = 'var(--pb-color-text-muted)';
            try {
                const res = await fetch(`/api/v1/events/${slug}`, {
                    method: 'DELETE', headers, body: JSON.stringify(payload),
                });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                close();
                render(container, state);
            } catch (err) {
                msg.textContent = 'Fehler: ' + err.message; msg.style.color = 'var(--pb-color-error)';
            }
        });
    }
}
