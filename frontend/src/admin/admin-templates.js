import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

const DISPLAY_W = 380;  // canvas preview width in px
let headers;
let assetsByType = { background: [], frame: [], logo: [], sticker: [] };

async function loadAssets() {
    const out = {};
    for (const t of ['background', 'frame', 'logo', 'sticker']) {
        try {
            out[t] = await fetch(`/api/v1/assets?type=${t}`, { headers }).then(r => r.json()).then(r => r.assets || []);
        } catch { out[t] = []; }
    }
    assetsByType = out;
}

export async function render(container, state) {
    headers = getHeaders();
    await loadAssets();
    renderList(container, state);
}

// ── List view ────────────────────────────────────────────────────────────
async function renderList(container, state) {
    let templates = [];
    try { templates = await fetch('/api/v1/templates', { headers }).then(r => r.json()).then(r => r.templates || []); } catch {}

    container.innerHTML = adminShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;">
            <h1 style="margin:0;">Foto-Vorlagen</h1>
            <button id="btn-new" class="admin-btn admin-btn-primary">+ Neue Vorlage</button>
        </div>
        <div style="max-width:900px;">
            ${templates.length ? `
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1rem;">
                    ${templates.map(t => `
                        <div class="admin-card" style="margin:0;">
                            <h3 style="margin-bottom:0.25rem;">${t.name}</h3>
                            <p>${t.photo_count} Foto-Slot(s) · ${t.canvas_width}×${t.canvas_height} · ${t.mode === 'grid' ? 'Raster' : 'Frei'}</p>
                            <div style="display:flex;gap:0.5rem;margin-top:0.75rem;">
                                <button class="edit-tpl admin-btn admin-btn-outline" data-id="${t.id}" style="font-size:0.8rem;">Bearbeiten</button>
                                <button class="del-tpl admin-btn admin-btn-outline" data-id="${t.id}" style="font-size:0.8rem;color:var(--pb-color-error);">Löschen</button>
                            </div>
                        </div>`).join('')}
                </div>` : '<p style="color:var(--pb-color-text-muted);">Noch keine Vorlagen. Lege eine neue an.</p>'}
        </div>
    `);
    setupLogout(container);

    container.querySelector('#btn-new')?.addEventListener('click', () => {
        renderEditor(container, state, {
            id: null, name: 'Neue Vorlage', mode: 'grid',
            canvas_width: 1200, canvas_height: 1800,
            background_asset_id: null, overlay_asset_id: null,
            slots: [], overlays: [],
        });
    });
    container.querySelectorAll('.edit-tpl').forEach(b => b.addEventListener('click', async () => {
        const t = await fetch(`/api/v1/templates/${b.dataset.id}`, { headers }).then(r => r.json());
        renderEditor(container, state, {
            id: t.id, name: t.name, mode: t.mode,
            canvas_width: t.canvas_width, canvas_height: t.canvas_height,
            background_asset_id: t.background_asset_id, overlay_asset_id: t.overlay_asset_id,
            slots: t.definition.slots || [], overlays: t.definition.overlays || [],
        });
    }));
    container.querySelectorAll('.del-tpl').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Vorlage löschen?')) return;
        await fetch(`/api/v1/templates/${b.dataset.id}`, { method: 'DELETE', headers });
        renderList(container, state);
    }));
}

// ── Editor view ────────────────────────────────────────────────────────────
function renderEditor(container, state, ed) {
    let selected = null;  // {kind:'slot'|'overlay', index}
    const scale = DISPLAY_W / ed.canvas_width;

    const assetOptions = (list, selId) =>
        `<option value="">— keins —</option>` +
        list.map(a => `<option value="${a.id}" ${a.id === selId ? 'selected' : ''}>${a.name}</option>`).join('');

    container.innerHTML = adminShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <h1 style="margin:0;">Vorlage bearbeiten</h1>
            <button id="btn-back" class="admin-btn admin-btn-outline">← Zurück</button>
        </div>
        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">

            <div style="flex:0 0 ${DISPLAY_W}px;">
                <div id="canvas" style="position:relative;width:${DISPLAY_W}px;height:${Math.round(ed.canvas_height * scale)}px;background:#fff;border:1px solid #444;overflow:hidden;"></div>
                <div style="display:flex;gap:0.5rem;margin-top:0.75rem;">
                    <button id="btn-preview" class="admin-btn admin-btn-primary" style="flex:1;">Vorschau rendern</button>
                    <label style="display:flex;align-items:center;gap:0.3rem;font-size:0.8rem;"><input type="checkbox" id="use-photos"> echte Fotos</label>
                </div>
                <div id="preview-wrap" style="margin-top:0.75rem;"></div>
            </div>

            <div style="flex:1;min-width:280px;max-width:420px;">
                <div class="admin-card">
                    <label style="font-size:0.9rem;">Name</label>
                    <input id="f-name" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;" value="${ed.name}">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;">
                        <div><label style="font-size:0.85rem;">Breite (px)</label><input id="f-w" type="number" class="admin-input" style="width:100%;" value="${ed.canvas_width}"></div>
                        <div><label style="font-size:0.85rem;">Höhe (px)</label><input id="f-h" type="number" class="admin-input" style="width:100%;" value="${ed.canvas_height}"></div>
                    </div>
                    <button id="btn-orient" class="admin-btn admin-btn-outline" style="margin-top:0.75rem;width:100%;">
                        ${ed.canvas_height >= ed.canvas_width ? '📱 Hochformat' : '🖥️ Querformat'} → wechseln
                    </button>
                </div>

                <div class="admin-card">
                    <h3>Foto-Slots</h3>
                    <div style="display:flex;gap:1rem;margin-bottom:0.5rem;">
                        <label style="font-size:0.85rem;"><input type="radio" name="mode" value="grid" ${ed.mode === 'grid' ? 'checked' : ''}> Raster</label>
                        <label style="font-size:0.85rem;"><input type="radio" name="mode" value="free" ${ed.mode === 'free' ? 'checked' : ''}> Frei</label>
                    </div>
                    <div id="grid-controls" style="display:${ed.mode === 'grid' ? 'block' : 'none'};">
                        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0.4rem;align-items:end;">
                            <div><label style="font-size:0.8rem;">Zeilen</label><input id="g-rows" type="number" class="admin-input" style="width:100%;" value="1" min="1"></div>
                            <div><label style="font-size:0.8rem;">Spalten</label><input id="g-cols" type="number" class="admin-input" style="width:100%;" value="${Math.max(1, ed.slots.length) || 1}" min="1"></div>
                            <div><label style="font-size:0.8rem;">Rand</label><input id="g-margin" type="number" class="admin-input" style="width:100%;" value="40"></div>
                            <div><label style="font-size:0.8rem;">Abstand</label><input id="g-gap" type="number" class="admin-input" style="width:100%;" value="20"></div>
                        </div>
                        <button id="btn-gen-grid" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;">Raster erzeugen</button>
                    </div>
                    <div id="free-controls" style="display:${ed.mode === 'free' ? 'block' : 'none'};">
                        <button id="btn-add-slot" class="admin-btn admin-btn-outline">+ Slot hinzufügen</button>
                    </div>
                    <div id="slot-props" style="margin-top:0.75rem;"></div>
                </div>

                <div class="admin-card">
                    <h3>Grafiken</h3>
                    <label style="font-size:0.85rem;">Hintergrund</label>
                    <select id="f-bg" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">${assetOptions(assetsByType.background, ed.background_asset_id)}</select>
                    <label style="font-size:0.85rem;">Rahmen/Overlay (ganzflächig)</label>
                    <select id="f-frame" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">${assetOptions(assetsByType.frame, ed.overlay_asset_id)}</select>
                    <label style="font-size:0.85rem;">Logo/Sticker hinzufügen</label>
                    <div style="display:flex;gap:0.5rem;margin-top:0.25rem;">
                        <select id="f-logo" class="admin-input" style="flex:1;">
                            <option value="">— wählen —</option>
                            ${[...assetsByType.logo, ...assetsByType.sticker].map(a => `<option value="${a.id}">${a.name}</option>`).join('')}
                        </select>
                        <button id="btn-add-overlay" class="admin-btn admin-btn-outline">+</button>
                    </div>
                </div>

                <button id="btn-save" class="admin-btn admin-btn-primary" style="width:100%;">Vorlage speichern</button>
                <p id="msg" style="margin-top:0.5rem;font-size:0.9rem;"></p>
            </div>
        </div>
    `);
    setupLogout(container);

    const canvas = container.querySelector('#canvas');
    const setMsg = (t, k) => { const m = container.querySelector('#msg'); m.textContent = t; m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)'; };

    function assetThumb(id) { return `/api/v1/assets/${id}/thumb`; }
    function assetFull(id) { return `/api/v1/assets/${id}/file`; }

    function drawCanvas() {
        canvas.innerHTML = '';
        canvas.style.backgroundImage = '';

        // Layer 0: background image (full canvas, behind everything)
        if (ed.background_asset_id) {
            const bg = document.createElement('img');
            bg.src = assetFull(ed.background_asset_id);
            bg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none;z-index:0;';
            canvas.appendChild(bg);
        }

        // Layer 1: photo slots (numbered, draggable, rotatable)
        ed.slots.forEach((s, i) => {
            const b = makeBox(s, i, 'slot', `${i + 1}`);
            b.style.zIndex = '1';
            canvas.appendChild(b);
        });

        // Layer 2: logos / stickers (draggable, rotatable)
        ed.overlays.forEach((o, i) => {
            const b = makeBox(o, i, 'overlay', '', o.asset_id);
            b.style.zIndex = '2';
            canvas.appendChild(b);
        });

        // Layer 3: full-canvas frame overlay on top
        if (ed.overlay_asset_id) {
            const fr = document.createElement('img');
            fr.src = assetFull(ed.overlay_asset_id);
            fr.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none;opacity:0.9;z-index:3;';
            canvas.appendChild(fr);
        }
        drawSlotProps();
    }

    function makeBox(item, index, kind, label, assetId) {
        const box = document.createElement('div');
        const isSel = selected && selected.kind === kind && selected.index === index;
        box.style.cssText = `position:absolute;left:${item.x * scale}px;top:${item.y * scale}px;width:${item.w * scale}px;height:${item.h * scale}px;
            border:2px solid ${kind === 'slot' ? '#5b9bd5' : '#ed7d31'};box-sizing:border-box;cursor:move;
            background:${assetId ? `url(${assetThumb(assetId)}) center/contain no-repeat` : 'rgba(91,155,213,0.25)'};
            transform:rotate(${item.rotation || 0}deg);transform-origin:center center;
            display:flex;align-items:center;justify-content:center;color:#1b3a5b;font-weight:bold;${isSel ? 'outline:2px dashed #fff;outline-offset:1px;' : ''}`;
        if (label) box.textContent = label;

        box.addEventListener('pointerdown', (e) => {
            if (e.target.classList.contains('rsz')) return;
            e.preventDefault();
            selected = { kind, index };
            startDrag(e, item, box, false);
            drawSlotProps();
        });

        const handle = document.createElement('div');
        handle.className = 'rsz';
        handle.style.cssText = 'position:absolute;right:-6px;bottom:-6px;width:14px;height:14px;background:#fff;border:2px solid #333;border-radius:50%;cursor:nwse-resize;';
        handle.addEventListener('pointerdown', (e) => { e.preventDefault(); e.stopPropagation(); selected = { kind, index }; startDrag(e, item, box, true); });
        box.appendChild(handle);
        return box;
    }

    function startDrag(e, item, box, resizing) {
        const startX = e.clientX, startY = e.clientY;
        const orig = { x: item.x, y: item.y, w: item.w, h: item.h };
        const onMove = (ev) => {
            const dx = (ev.clientX - startX) / scale;
            const dy = (ev.clientY - startY) / scale;
            if (resizing) {
                item.w = Math.max(40, Math.round(orig.w + dx));
                item.h = Math.max(40, Math.round(orig.h + dy));
                box.style.width = item.w * scale + 'px';
                box.style.height = item.h * scale + 'px';
            } else {
                item.x = Math.max(0, Math.min(ed.canvas_width - item.w, Math.round(orig.x + dx)));
                item.y = Math.max(0, Math.min(ed.canvas_height - item.h, Math.round(orig.y + dy)));
                box.style.left = item.x * scale + 'px';
                box.style.top = item.y * scale + 'px';
            }
        };
        const onUp = () => {
            document.removeEventListener('pointermove', onMove);
            document.removeEventListener('pointerup', onUp);
            drawSlotProps();
        };
        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', onUp);
    }

    function drawSlotProps() {
        const el = container.querySelector('#slot-props');
        if (!selected) { el.innerHTML = '<p style="font-size:0.8rem;color:var(--pb-color-text-muted);">Klicke einen Slot/Overlay zum Auswählen.</p>'; return; }
        const list = selected.kind === 'slot' ? ed.slots : ed.overlays;
        const item = list[selected.index];
        if (!item) { selected = null; return drawSlotProps(); }
        el.innerHTML = `
            <div style="font-size:0.8rem;background:#0e1a30;padding:0.5rem;border-radius:6px;">
                <strong>${selected.kind === 'slot' ? 'Slot ' + (selected.index + 1) : 'Overlay'}</strong>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;margin-top:0.4rem;">
                    ${selected.kind === 'slot' ? `
                    <label>Füllung
                        <select id="p-fit" class="admin-input" style="width:100%;">
                            <option value="cover" ${item.fit === 'cover' ? 'selected' : ''}>cover (füllen)</option>
                            <option value="contain" ${item.fit === 'contain' ? 'selected' : ''}>contain (ganz)</option>
                        </select></label>` : '<span></span>'}
                    <label>Drehung°<input id="p-rot" type="number" class="admin-input" style="width:100%;" value="${item.rotation || 0}"></label>
                </div>
                <button id="p-del" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;font-size:0.75rem;color:var(--pb-color-error);">Entfernen</button>
            </div>`;
        el.querySelector('#p-fit')?.addEventListener('change', (e) => { item.fit = e.target.value; });
        el.querySelector('#p-rot')?.addEventListener('change', (e) => { item.rotation = parseInt(e.target.value) || 0; drawCanvas(); });
        el.querySelector('#p-del')?.addEventListener('click', () => { list.splice(selected.index, 1); selected = null; drawCanvas(); });
    }

    // Controls
    container.querySelector('#btn-back')?.addEventListener('click', () => renderList(container, state));

    // Swap portrait <-> landscape (transpose canvas + slots + overlays)
    container.querySelector('#btn-orient')?.addEventListener('click', () => {
        const w = ed.canvas_width, h = ed.canvas_height;
        ed.canvas_width = h; ed.canvas_height = w;
        const transpose = (it) => {
            const x = it.x, wd = it.w;
            it.x = it.y; it.y = x;
            it.w = it.h; it.h = wd;
        };
        ed.slots.forEach(transpose);
        ed.overlays.forEach(transpose);
        renderEditor(container, state, ed);  // rescale + redraw
    });
    container.querySelector('#f-name')?.addEventListener('input', (e) => ed.name = e.target.value);
    const reW = container.querySelector('#f-w'), reH = container.querySelector('#f-h');
    [reW, reH].forEach(inp => inp.addEventListener('change', () => {
        ed.canvas_width = parseInt(reW.value) || 1200;
        ed.canvas_height = parseInt(reH.value) || 1800;
        renderEditor(container, state, ed);  // rescale
    }));
    container.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', () => {
        ed.mode = r.value;
        container.querySelector('#grid-controls').style.display = r.value === 'grid' ? 'block' : 'none';
        container.querySelector('#free-controls').style.display = r.value === 'free' ? 'block' : 'none';
    }));
    container.querySelector('#btn-gen-grid')?.addEventListener('click', async () => {
        const body = {
            rows: parseInt(container.querySelector('#g-rows').value) || 1,
            cols: parseInt(container.querySelector('#g-cols').value) || 1,
            canvas_width: ed.canvas_width, canvas_height: ed.canvas_height,
            margin: parseInt(container.querySelector('#g-margin').value) || 0,
            gap: parseInt(container.querySelector('#g-gap').value) || 0,
        };
        const r = await fetch('/api/v1/templates/grid-slots', { method: 'POST', headers, body: JSON.stringify(body) });
        ed.slots = (await r.json()).slots;
        selected = null; drawCanvas();
    });
    container.querySelector('#btn-add-slot')?.addEventListener('click', () => {
        ed.slots.push({ x: 50, y: 50, w: Math.round(ed.canvas_width * 0.4), h: Math.round(ed.canvas_height * 0.25), rotation: 0, fit: 'cover' });
        selected = { kind: 'slot', index: ed.slots.length - 1 }; drawCanvas();
    });
    container.querySelector('#f-bg')?.addEventListener('change', (e) => { ed.background_asset_id = e.target.value ? parseInt(e.target.value) : null; drawCanvas(); });
    container.querySelector('#f-frame')?.addEventListener('change', (e) => { ed.overlay_asset_id = e.target.value ? parseInt(e.target.value) : null; drawCanvas(); });
    container.querySelector('#btn-add-overlay')?.addEventListener('click', () => {
        const sel = container.querySelector('#f-logo');
        const id = sel.value ? parseInt(sel.value) : null;
        if (!id) return;
        ed.overlays.push({ asset_id: id, x: 40, y: 40, w: Math.round(ed.canvas_width * 0.25), h: Math.round(ed.canvas_width * 0.25), rotation: 0 });
        selected = { kind: 'overlay', index: ed.overlays.length - 1 }; drawCanvas();
    });

    function payload() {
        return {
            name: ed.name, mode: ed.mode,
            canvas_width: ed.canvas_width, canvas_height: ed.canvas_height,
            background_asset_id: ed.background_asset_id, overlay_asset_id: ed.overlay_asset_id,
            definition: { slots: ed.slots, overlays: ed.overlays },
        };
    }

    container.querySelector('#btn-preview')?.addEventListener('click', async () => {
        setMsg('Rendere Vorschau…');
        try {
            const body = { ...payload(), use_photos: container.querySelector('#use-photos').checked };
            const res = await fetch('/api/v1/templates/preview', { method: 'POST', headers, body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail);
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            container.querySelector('#preview-wrap').innerHTML = `<img src="${url}" style="width:100%;border:1px solid #444;border-radius:6px;">`;
            setMsg('Vorschau aktualisiert.', 'ok');
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });

    container.querySelector('#btn-save')?.addEventListener('click', async () => {
        setMsg('Speichere…');
        try {
            const url = ed.id ? `/api/v1/templates/${ed.id}` : '/api/v1/templates';
            const method = ed.id ? 'PUT' : 'POST';
            const res = await fetch(url, { method, headers, body: JSON.stringify(payload()) });
            if (!res.ok) throw new Error((await res.json()).detail);
            const saved = await res.json();
            ed.id = saved.id;
            setMsg('Gespeichert!', 'ok');
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });

    drawCanvas();
}
