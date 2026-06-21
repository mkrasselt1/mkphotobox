import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

let headers;
let printers = [];

// Gutenprint media codes (wWhH in 1/72") -> human-readable cm/inch (mirrors admin-printer.js)
function prettyPaper(name) {
    const m = /^w(\d+)h(\d+)(.*)$/i.exec(name);
    if (!m) return name;
    const fin = v => (Math.round(v * 10) / 10).toString().replace(/\.0$/, '');
    const win = +m[1] / 72, hin = +m[2] / 72;
    let label = `${Math.round(win * 2.54)}×${Math.round(hin * 2.54)} cm (${fin(win)}×${fin(hin)}″)`;
    const suf = m[3] || '';
    if (suf) label += suf.toLowerCase().includes('div2') ? ' · 2-geteilt' : ` ${suf}`;
    return label;
}

export async function render(container, state) {
    headers = getHeaders();
    try {
        printers = await fetch('/api/v1/printer/list', { headers }).then(r => r.json()).then(r => r.printers || []);
    } catch { printers = []; }
    renderList(container, state);
}

async function renderList(container, state) {
    let presets = [];
    try { presets = await fetch('/api/v1/presets', { headers }).then(r => r.json()).then(r => r.presets || []); } catch {}

    const prints = presets.filter(p => p.kind === 'print');
    const socials = presets.filter(p => p.kind === 'social');

    const card = (p) => {
        const ar = p.aspect ? p.aspect.toFixed(2) : '–';
        const phys = (p.kind === 'print' && p.width_mm && p.height_mm)
            ? `${Math.round(p.width_mm)}×${Math.round(p.height_mm)} mm @ ${p.dpi} dpi`
            : (p.kind === 'social' ? 'Digital' : '— kein Format gewählt —');
        const printerLine = p.kind === 'print'
            ? `<p>🖨️ ${p.printer_name || '(Standard)'} · ${p.paper_size ? prettyPaper(p.paper_size) : '—'} · ${p.copies}×</p>` : '';
        return `
        <div class="admin-card" style="margin:0;">
            <h3 style="margin-bottom:0.25rem;">${p.name} ${p.builtin ? '<span style="font-size:0.7rem;color:var(--pb-color-text-muted);">(fix)</span>' : ''}</h3>
            <p>${p.width_px}×${p.height_px} px · ${p.kind === 'print' ? (p.orientation === 'landscape' ? 'Quer' : 'Hoch') : 'Seitenv.'} ${ar}</p>
            <p>${phys}</p>
            ${printerLine}
            <div style="display:flex;gap:0.5rem;margin-top:0.75rem;">
                <button class="edit-p admin-btn admin-btn-outline" data-id="${p.id}" style="font-size:0.8rem;">Bearbeiten</button>
                ${p.builtin ? '' : `<button class="del-p admin-btn admin-btn-outline" data-id="${p.id}" style="font-size:0.8rem;color:var(--pb-color-error);">Löschen</button>`}
            </div>
        </div>`;
    };

    const grid = (items) => items.length
        ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:1rem;">${items.map(card).join('')}</div>`
        : '<p style="color:var(--pb-color-text-muted);">Noch keine.</p>';

    container.innerHTML = adminShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <h1 style="margin:0;">Ausgabe-Formate</h1>
            <div style="display:flex;gap:0.5rem;">
                <button id="new-print" class="admin-btn admin-btn-primary">+ Druck-Format</button>
                <button id="new-social" class="admin-btn admin-btn-outline">+ Social-Format</button>
            </div>
        </div>
        <p style="color:var(--pb-color-text-muted);max-width:640px;margin-bottom:1.25rem;font-size:0.9rem;">
            Ein Druck-Format liest die echte Papiergröße vom Drucker (kein Pixel-Raten) und kann einer Vorlage
            zugewiesen werden — die passende Collage druckt dann automatisch auf diesem Drucker. Social-Formate
            (Instagram, TikTok …) legen feste Pixelmaße fürs Teilen fest.
        </p>
        <div style="max-width:900px;">
            <h2 style="font-size:1rem;color:var(--pb-color-primary);margin:0 0 0.5rem;">🖨️ Druck-Formate</h2>
            ${grid(prints)}
            <h2 style="font-size:1rem;color:var(--pb-color-primary);margin:1.5rem 0 0.5rem;">📱 Social / Digital</h2>
            ${grid(socials)}
        </div>
    `);
    setupLogout(container);

    container.querySelector('#new-print')?.addEventListener('click', () => renderEditor(container, state, {
        id: null, name: 'Neues Druck-Format', kind: 'print', dpi: 300, orientation: 'portrait',
        copies: 1, margin_mm: 0, fit_to_page: true, printer_name: '', paper_size: '',
        width_px: 1200, height_px: 1800,
    }));
    container.querySelector('#new-social')?.addEventListener('click', () => renderEditor(container, state, {
        id: null, name: 'Neues Social-Format', kind: 'social', width_px: 1080, height_px: 1080,
    }));
    container.querySelectorAll('.edit-p').forEach(b => b.addEventListener('click', async () => {
        const p = presets.find(x => String(x.id) === b.dataset.id);
        if (p) renderEditor(container, state, { ...p });
    }));
    container.querySelectorAll('.del-p').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Format löschen?')) return;
        await fetch(`/api/v1/presets/${b.dataset.id}`, { method: 'DELETE', headers });
        renderList(container, state);
    }));
}

function renderEditor(container, state, p) {
    const isPrint = p.kind === 'print';
    const setMsg = (t, k) => { const m = container.querySelector('#msg'); if (!m) return; m.textContent = t; m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)'; };

    container.innerHTML = adminShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <h1 style="margin:0;">${isPrint ? 'Druck-Format' : 'Social-Format'} ${p.id ? 'bearbeiten' : 'anlegen'}</h1>
            <button id="back" class="admin-btn admin-btn-outline">← Zurück</button>
        </div>
        <div style="max-width:560px;">
            <div class="admin-card">
                <label style="font-size:0.85rem;">Name</label>
                <input id="f-name" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.name}" ${p.builtin ? 'disabled' : ''}>
            </div>

            ${isPrint ? `
            <div class="admin-card">
                <h3>Drucker & Papier</h3>
                <label style="font-size:0.85rem;">Drucker</label>
                <select id="f-printer" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">
                    <option value="">(Systemstandard)</option>
                    ${printers.map(pr => `<option value="${pr.name}" ${pr.name === p.printer_name ? 'selected' : ''}>${pr.name}${pr.default ? ' (Standard)' : ''}</option>`).join('')}
                </select>
                <label style="font-size:0.85rem;">Papierformat (vom Drucker)</label>
                <select id="f-paper" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">
                    ${p.paper_size ? `<option value="${p.paper_size}" selected>${prettyPaper(p.paper_size)}</option>` : '<option value="">— Drucker wählen —</option>'}
                </select>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
                    <div><label style="font-size:0.85rem;">DPI</label><input id="f-dpi" type="number" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.dpi || 300}" min="72" max="1200"></div>
                    <div><label style="font-size:0.85rem;">Ausrichtung</label>
                        <select id="f-orient" class="admin-input" style="width:100%;margin-top:0.25rem;">
                            <option value="portrait" ${p.orientation !== 'landscape' ? 'selected' : ''}>Hochformat</option>
                            <option value="landscape" ${p.orientation === 'landscape' ? 'selected' : ''}>Querformat</option>
                        </select></div>
                    <div><label style="font-size:0.85rem;">Kopien</label><input id="f-copies" type="number" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.copies || 1}" min="1" max="20"></div>
                    <div><label style="font-size:0.85rem;">Rand (mm)</label><input id="f-margin" type="number" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.margin_mm || 0}" min="0" max="50"></div>
                </div>
                <label style="display:flex;align-items:center;gap:0.5rem;margin-top:0.75rem;cursor:pointer;font-size:0.9rem;">
                    <input type="checkbox" id="f-fit" ${p.fit_to_page !== false ? 'checked' : ''}> An Seitengröße anpassen
                </label>
                <p id="px-out" style="margin-top:0.75rem;font-size:0.9rem;color:var(--pb-color-text-muted);"></p>
            </div>
            ` : `
            <div class="admin-card">
                <h3>Pixelmaße</h3>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.75rem;align-items:center;">
                    ${[['1:1', 1080, 1080], ['4:5', 1080, 1350], ['9:16', 1080, 1920], ['16:9', 1920, 1080]].map(([l, w, h]) =>
                        `<button class="ratio-btn admin-btn admin-btn-outline" data-w="${w}" data-h="${h}" style="font-size:0.8rem;">${l}</button>`).join('')}
                    <button id="s-swap" class="admin-btn admin-btn-outline" style="font-size:0.8rem;margin-left:auto;">↔ Hoch/Quer tauschen</button>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
                    <div><label style="font-size:0.85rem;">Breite (px)</label><input id="s-w" type="number" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.width_px}" min="1"></div>
                    <div><label style="font-size:0.85rem;">Höhe (px)</label><input id="s-h" type="number" class="admin-input" style="width:100%;margin-top:0.25rem;" value="${p.height_px}" min="1"></div>
                </div>
                <p id="s-ar" style="margin-top:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);"></p>
            </div>
            `}

            <button id="save" class="admin-btn admin-btn-primary" style="width:100%;">Speichern</button>
            <p id="msg" style="margin-top:0.5rem;font-size:0.9rem;"></p>
        </div>
    `);
    setupLogout(container);
    container.querySelector('#back')?.addEventListener('click', () => renderList(container, state));

    if (isPrint) {
        const paperSel = container.querySelector('#f-paper');
        async function loadPaper(printerName, keep) {
            let data = { sizes: [], default: null };
            try { data = await fetch(`/api/v1/printer/paper-sizes?printer=${encodeURIComponent(printerName || '')}`, { headers }).then(r => r.json()); } catch {}
            if (data.sizes && data.sizes.length) {
                const want = keep || p.paper_size || data.default || data.sizes[0];
                paperSel.innerHTML = data.sizes.map(s => `<option value="${s}" ${s === want ? 'selected' : ''}>${prettyPaper(s)}</option>`).join('');
            } else if (!keep) {
                paperSel.innerHTML = '<option value="">— keine Formate gefunden —</option>';
            }
            updatePx();
        }
        async function updatePx() {
            const out = container.querySelector('#px-out');
            const paper = paperSel.value;
            const dpi = parseInt(container.querySelector('#f-dpi').value) || 300;
            const orient = container.querySelector('#f-orient').value;
            if (!paper) { out.textContent = 'Kein Format gewählt.'; return; }
            try {
                const d = await fetch(`/api/v1/presets/paper-dimensions?paper=${encodeURIComponent(paper)}&dpi=${dpi}`, { headers }).then(r => r.json());
                if (d.resolved) {
                    let w = d.width_px, h = d.height_px;
                    if (orient === 'landscape') [w, h] = [Math.max(w, h), Math.min(w, h)]; else [w, h] = [Math.min(w, h), Math.max(w, h)];
                    out.textContent = `→ ${d.width_mm}×${d.height_mm} mm · Canvas ${w}×${h} px`;
                } else {
                    out.textContent = 'Größe nicht automatisch erkennbar — Pixel werden aus dem Druckertreiber übernommen.';
                }
            } catch { out.textContent = ''; }
        }
        container.querySelector('#f-printer')?.addEventListener('change', e => loadPaper(e.target.value, null));
        paperSel.addEventListener('change', updatePx);
        container.querySelector('#f-dpi')?.addEventListener('change', updatePx);
        container.querySelector('#f-orient')?.addEventListener('change', updatePx);
        // initial: load sizes for the currently-selected printer, keeping current paper
        loadPaper(p.printer_name || '', p.paper_size || null);
    } else {
        const sw = container.querySelector('#s-w'), sh = container.querySelector('#s-h');
        const arOut = container.querySelector('#s-ar');
        const showAr = () => {
            const w = parseInt(sw.value) || 0, h = parseInt(sh.value) || 0;
            arOut.textContent = (w && h) ? `Seitenverhältnis ${(w / h).toFixed(2)} · ${w > h ? 'Querformat' : w < h ? 'Hochformat' : 'Quadrat'}` : '';
        };
        container.querySelectorAll('.ratio-btn').forEach(b => b.addEventListener('click', () => {
            sw.value = b.dataset.w; sh.value = b.dataset.h; showAr();
        }));
        container.querySelector('#s-swap')?.addEventListener('click', () => {
            const w = sw.value; sw.value = sh.value; sh.value = w; showAr();
        });
        sw.addEventListener('input', showAr); sh.addEventListener('input', showAr);
        showAr();
    }

    container.querySelector('#save')?.addEventListener('click', async () => {
        setMsg('Speichere…');
        const body = { name: container.querySelector('#f-name').value, kind: p.kind };
        if (isPrint) {
            body.printer_name = container.querySelector('#f-printer').value;
            body.paper_size = container.querySelector('#f-paper').value;
            body.dpi = parseInt(container.querySelector('#f-dpi').value) || 300;
            body.orientation = container.querySelector('#f-orient').value;
            body.copies = parseInt(container.querySelector('#f-copies').value) || 1;
            body.margin_mm = parseFloat(container.querySelector('#f-margin').value) || 0;
            body.fit_to_page = container.querySelector('#f-fit').checked;
        } else {
            body.width_px = parseInt(container.querySelector('#s-w').value) || 1080;
            body.height_px = parseInt(container.querySelector('#s-h').value) || 1080;
        }
        try {
            const url = p.id ? `/api/v1/presets/${p.id}` : '/api/v1/presets';
            const res = await fetch(url, { method: p.id ? 'PUT' : 'POST', headers, body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
            setMsg('Gespeichert!', 'ok');
            setTimeout(() => renderList(container, state), 600);
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });
}
