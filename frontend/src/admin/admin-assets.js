import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

const TYPES = [
    { id: 'background', label: 'Hintergründe' },
    { id: 'frame', label: 'Rahmen/Overlays' },
    { id: 'logo', label: 'Logos' },
    { id: 'sticker', label: 'Sticker' },
];

let activeType = 'background';
let browseState = { path: null, dirs: [], files: [], parent: null, selected: new Set() };

export async function render(container, state) {
    const headers = getHeaders();

    let assets = [], sources = [];
    try {
        [assets, sources] = await Promise.all([
            fetch(`/api/v1/assets?type=${activeType}`, { headers }).then(r => r.json()).then(r => r.assets || []),
            fetch('/api/v1/assets/sources', { headers }).then(r => r.json()).then(r => r.sources || []),
        ]);
    } catch {}

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1rem;">Vorlagen-Assets</h1>
        <div style="max-width:900px;">

            <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">
                ${TYPES.map(t => `
                    <button class="admin-btn ${t.id === activeType ? 'admin-btn-primary' : 'admin-btn-outline'}" data-type="${t.id}">${t.label}</button>
                `).join('')}
            </div>

            <div class="admin-card">
                <h3>Importierte ${TYPES.find(t => t.id === activeType).label}</h3>
                ${assets.length ? `
                    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:0.75rem;margin-top:0.75rem;">
                        ${assets.map(a => `
                            <div style="background:#0e1a30;border-radius:8px;padding:0.5rem;text-align:center;">
                                <img src="/api/v1/assets/${a.id}/thumb" alt="${a.name}"
                                     style="width:100%;height:90px;object-fit:contain;background:#fff;border-radius:4px;">
                                <div style="font-size:0.75rem;margin-top:0.25rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${a.name}</div>
                                <button class="del-asset admin-btn admin-btn-outline" data-id="${a.id}"
                                        style="font-size:0.7rem;padding:0.2rem 0.5rem;margin-top:0.25rem;">Löschen</button>
                            </div>
                        `).join('')}
                    </div>
                ` : '<p style="color:var(--pb-color-text-muted);margin-top:0.5rem;">Noch nichts importiert.</p>'}
            </div>

            <div class="admin-card">
                <h3>Importieren</h3>
                <label style="font-size:0.9rem;">Quelle</label>
                <div style="display:flex;gap:0.5rem;margin-top:0.25rem;">
                    <select id="source-select" class="admin-input" style="flex:1;">
                        <option value="">— Quelle wählen —</option>
                        ${sources.map(s => `<option value="${encodeURIComponent(s.path)}">${s.label}</option>`).join('')}
                    </select>
                    <button id="btn-refresh-src" class="admin-btn admin-btn-outline">Datenträger neu suchen</button>
                </div>

                <div id="browser" style="margin-top:1rem;"></div>

                <div id="import-bar" style="display:none;margin-top:1rem;align-items:center;gap:0.75rem;">
                    <span id="sel-count" style="font-size:0.9rem;"></span>
                    <span style="flex:1;"></span>
                    <button id="btn-import" class="admin-btn admin-btn-primary">Auswahl importieren</button>
                </div>
                <p id="msg" style="margin-top:0.5rem;font-size:0.9rem;"></p>
            </div>
        </div>
    `);

    setupLogout(container);

    const setMsg = (t, kind) => {
        const m = container.querySelector('#msg');
        m.textContent = t;
        m.style.color = kind === 'error' ? 'var(--pb-color-error)' : kind === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    };

    // Type tabs
    container.querySelectorAll('[data-type]').forEach(btn => {
        btn.addEventListener('click', () => { activeType = btn.dataset.type; render(container, state); });
    });

    // Delete asset
    container.querySelectorAll('.del-asset').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Asset wirklich löschen?')) return;
            await fetch(`/api/v1/assets/${btn.dataset.id}`, { method: 'DELETE', headers });
            render(container, state);
        });
    });

    container.querySelector('#btn-refresh-src')?.addEventListener('click', () => render(container, state));

    async function loadBrowser(path) {
        browseState.selected = new Set();
        try {
            const r = await fetch(`/api/v1/assets/browse?path=${encodeURIComponent(path)}`, { headers });
            if (!r.ok) throw new Error((await r.json()).detail);
            const data = await r.json();
            browseState = { ...data, selected: new Set() };
            drawBrowser();
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    }

    function drawBrowser() {
        const el = container.querySelector('#browser');
        const { path, parent, dirs, files, selected } = browseState;
        el.innerHTML = `
            <div style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.5rem;">${path || ''}</div>
            <div style="background:#0e1a30;border-radius:8px;padding:0.5rem;max-height:300px;overflow-y:auto;">
                ${parent ? `<div class="dir-row" data-path="${encodeURIComponent(parent)}" style="padding:0.4rem;cursor:pointer;">📁 ..</div>` : ''}
                ${dirs.map(d => `<div class="dir-row" data-path="${encodeURIComponent(d.path)}" style="padding:0.4rem;cursor:pointer;">📁 ${d.name}</div>`).join('')}
                ${files.map(f => `
                    <label style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem;cursor:pointer;">
                        <input type="checkbox" class="file-cb" data-path="${encodeURIComponent(f.path)}" ${selected.has(f.path) ? 'checked' : ''}>
                        🖼️ ${f.name}
                        <span style="margin-left:auto;font-size:0.75rem;color:var(--pb-color-text-muted);">${f.size_bytes ? Math.round(f.size_bytes / 1024) + ' KB' : ''}</span>
                    </label>`).join('')}
                ${(!dirs.length && !files.length) ? '<div style="padding:0.5rem;color:var(--pb-color-text-muted);">Keine Bilder/Ordner hier.</div>' : ''}
            </div>
        `;
        el.querySelectorAll('.dir-row').forEach(row =>
            row.addEventListener('click', () => loadBrowser(decodeURIComponent(row.dataset.path))));
        el.querySelectorAll('.file-cb').forEach(cb =>
            cb.addEventListener('change', () => {
                const p = decodeURIComponent(cb.dataset.path);
                if (cb.checked) browseState.selected.add(p); else browseState.selected.delete(p);
                updateImportBar();
            }));
        updateImportBar();
    }

    function updateImportBar() {
        const bar = container.querySelector('#import-bar');
        const n = browseState.selected.size;
        bar.style.display = n ? 'flex' : 'none';
        container.querySelector('#sel-count').textContent = `${n} Datei(en) ausgewählt → importieren als „${TYPES.find(t => t.id === activeType).label}"`;
    }

    container.querySelector('#source-select')?.addEventListener('change', (e) => {
        if (e.target.value) loadBrowser(decodeURIComponent(e.target.value));
    });

    container.querySelector('#btn-import')?.addEventListener('click', async () => {
        const paths = [...browseState.selected];
        if (!paths.length) return;
        setMsg('Importiere…');
        try {
            const res = await fetch('/api/v1/assets/import', {
                method: 'POST', headers, body: JSON.stringify({ type: activeType, paths }),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.detail);
            setMsg(`${result.imported} Asset(s) importiert!`, 'ok');
            setTimeout(() => render(container, state), 800);
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });
}
