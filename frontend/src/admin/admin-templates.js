import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

const DISPLAY_W = 520;  // canvas preview width in px
let headers;
let assetsByType = { background: [], frame: [], logo: [], sticker: [] };
let availableFonts = ['Sans', 'Serif', 'Mono'];
let presets = [];  // output presets (print paper / social formats)

async function loadPresets() {
    try {
        presets = await fetch('/api/v1/presets', { headers }).then(r => r.json()).then(r => r.presets || []);
    } catch { presets = []; }
}

async function loadAssets() {
    const out = {};
    for (const t of ['background', 'frame', 'logo', 'sticker']) {
        try {
            out[t] = await fetch(`/api/v1/assets?type=${t}`, { headers }).then(r => r.json()).then(r => r.assets || []);
        } catch { out[t] = []; }
    }
    assetsByType = out;
}

async function loadFonts() {
    try {
        const r = await fetch('/api/v1/templates/fonts', { headers }).then(r => r.json());
        if (r.fonts && r.fonts.length) availableFonts = r.fonts;
    } catch {}
}

// Approximate the backend fonts in the browser preview (authoritative render is server-side).
// Script fonts: use the real family name (the .ttf is installed on the box) with a
// cursive fallback so the preview at least looks flowing even on the dev machine.
function fontCss(label) {
    switch (label) {
        case 'Serif': return 'Georgia, "Times New Roman", serif';
        case 'Mono': return '"Courier New", monospace';
        case 'Ubuntu': return 'Ubuntu, "Segoe UI", sans-serif';
        case 'Pacifico': return 'Pacifico, cursive';
        case 'Dancing Script': return '"Dancing Script", cursive';
        case 'Great Vibes': return '"Great Vibes", cursive';
        case 'Lobster': return 'Lobster, cursive';
        case 'Sacramento': return 'Sacramento, cursive';
        case 'Satisfy': return 'Satisfy, cursive';
        case 'Parisienne': return 'Parisienne, cursive';
        case 'Comic': return '"Comic Neue", "Comic Sans MS", cursive';
        default: return 'Arial, Helvetica, sans-serif';
    }
}

export async function render(container, state) {
    headers = getHeaders();
    await loadAssets();
    await loadFonts();
    await loadPresets();
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
            canvas_width: 1200, canvas_height: 1800, preset_id: null,
            background_asset_id: null, overlay_asset_id: null,
            slots: [], overlays: [], texts: [],
        });
    });
    container.querySelectorAll('.edit-tpl').forEach(b => b.addEventListener('click', async () => {
        const t = await fetch(`/api/v1/templates/${b.dataset.id}`, { headers }).then(r => r.json());
        renderEditor(container, state, {
            id: t.id, name: t.name, mode: t.mode,
            canvas_width: t.canvas_width, canvas_height: t.canvas_height, preset_id: t.preset_id ?? null,
            background_asset_id: t.background_asset_id, overlay_asset_id: t.overlay_asset_id,
            slots: t.definition.slots || [], overlays: t.definition.overlays || [],
            texts: t.definition.texts || [],
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
    let selected = null;  // {kind:'slot'|'overlay'|'text', index}
    const boundPreset = ed.preset_id != null ? presets.find(p => p.id === ed.preset_id) : null;
    const scale = DISPLAY_W / ed.canvas_width;
    let editMode = 'move';  // 'move' | 'resize' | 'rotate' — touch-friendly: drag anywhere
    let snapEnabled = true;   // snap to guides + other elements while dragging
    let showGuides = true;    // show the static division guide lines (½, ⅓, ⅔)

    const assetOptions = (list, selId) =>
        `<option value="">— keins —</option>` +
        list.map(a => `<option value="${a.id}" ${a.id === selId ? 'selected' : ''}>${a.name}</option>`).join('');

    container.innerHTML = adminShell(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
            <h1 style="margin:0;">Vorlage bearbeiten</h1>
            <button id="btn-back" class="admin-btn admin-btn-outline">← Zurück</button>
        </div>
        <div class="admin-card" style="margin-bottom:1rem;display:flex;align-items:center;gap:0.75rem;">
            <label style="font-size:0.9rem;white-space:nowrap;">Name der Vorlage</label>
            <input id="f-name" class="admin-input" style="flex:1;" value="${ed.name}">
        </div>
        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">

            <div style="flex:0 0 ${DISPLAY_W}px;">
                <div style="display:flex;gap:0.4rem;margin-bottom:0.5rem;">
                    <button class="mode-btn admin-btn" data-mode="move" style="flex:1;">✋ Verschieben</button>
                    <button class="mode-btn admin-btn" data-mode="resize" style="flex:1;">⤡ Größe</button>
                    <button class="mode-btn admin-btn" data-mode="rotate" style="flex:1;">⟳ Drehen</button>
                </div>
                <div style="display:flex;gap:1rem;margin-bottom:0.5rem;font-size:0.8rem;color:var(--pb-color-text-muted);">
                    <label style="display:flex;align-items:center;gap:0.3rem;cursor:pointer;"><input type="checkbox" id="t-snap" checked> Einrasten</label>
                    <label style="display:flex;align-items:center;gap:0.3rem;cursor:pointer;"><input type="checkbox" id="t-guides" checked> Hilfslinien</label>
                </div>
                <div id="canvas" style="position:relative;width:${DISPLAY_W}px;height:${Math.round(ed.canvas_height * scale)}px;background:#fff;border:1px solid #444;overflow:hidden;touch-action:none;"></div>
                <div style="display:flex;gap:0.5rem;margin-top:0.75rem;">
                    <button id="btn-preview" class="admin-btn admin-btn-primary" style="flex:1;">Vorschau rendern</button>
                    <label style="display:flex;align-items:center;gap:0.3rem;font-size:0.8rem;"><input type="checkbox" id="use-photos"> echte Fotos</label>
                </div>
                <div id="preview-wrap" style="margin-top:0.75rem;"></div>
            </div>

            <div style="flex:1;min-width:280px;max-width:420px;">
                <div class="admin-card">
                    <label style="font-size:0.85rem;">Ausgabe-Format</label>
                    <select id="f-preset" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;">
                        <option value="">Benutzerdefiniert (freie Pixel)</option>
                        ${presets.map(p => `<option value="${p.id}" ${p.id === ed.preset_id ? 'selected' : ''}>${p.kind === 'print' ? '🖨️' : '📱'} ${p.name} — ${p.width_px}×${p.height_px}</option>`).join('')}
                    </select>
                    ${boundPreset ? `
                        <p style="font-size:0.8rem;color:var(--pb-color-text-muted);margin:0;">
                            Canvas folgt dem Format <strong>${boundPreset.name}</strong> (${ed.canvas_width}×${ed.canvas_height} px).
                            ${boundPreset.kind === 'print' ? 'Ausrichtung/Drehung wird im Format selbst eingestellt.' : ''}
                        </p>` : `
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;">
                            <div><label style="font-size:0.85rem;">Breite (px)</label><input id="f-w" type="number" class="admin-input" style="width:100%;" value="${ed.canvas_width}"></div>
                            <div><label style="font-size:0.85rem;">Höhe (px)</label><input id="f-h" type="number" class="admin-input" style="width:100%;" value="${ed.canvas_height}"></div>
                        </div>
                        <button id="btn-orient" class="admin-btn admin-btn-outline" style="margin-top:0.75rem;width:100%;">
                            ${ed.canvas_height >= ed.canvas_width ? '📱 Hochformat' : '🖥️ Querformat'} → wechseln
                        </button>`}
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

                <div class="admin-card">
                    <h3>Text</h3>
                    <div style="display:flex;gap:0.5rem;align-items:center;">
                        <input id="f-text" class="admin-input" style="flex:1;" placeholder="Text eingeben…">
                        <button id="btn-add-text" class="admin-btn admin-btn-outline">+ Text</button>
                    </div>
                    <p style="font-size:0.78rem;color:var(--pb-color-text-muted);margin-top:0.4rem;">
                        Schriftart, Größe, Farbe und Stil werden nach dem Hinzufügen unten eingestellt.
                    </p>
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

        // Layer 4: text elements (on top of everything, draggable)
        ed.texts.forEach((t, i) => {
            const b = makeBox(t, i, 'text', '');
            b.style.zIndex = '4';
            canvas.appendChild(b);
        });

        // Static division guide lines (½, ⅓, ⅔)
        if (showGuides) {
            const g = document.createElement('div');
            g.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:6;';
            const W = ed.canvas_width, H = ed.canvas_height;
            const verticals = [W / 3, W / 2, 2 * W / 3];
            const horizontals = [H / 3, H / 2, 2 * H / 3];
            verticals.forEach(v => {
                const l = document.createElement('div');
                l.style.cssText = `position:absolute;left:${v * scale}px;top:0;width:1px;height:100%;background:rgba(255,59,154,0.25);`;
                g.appendChild(l);
            });
            horizontals.forEach(v => {
                const l = document.createElement('div');
                l.style.cssText = `position:absolute;top:${v * scale}px;left:0;height:1px;width:100%;background:rgba(255,59,154,0.25);`;
                g.appendChild(l);
            });
            canvas.appendChild(g);
        }
        drawSlotProps();
    }

    // ── Snapping + dynamic guide lines ──────────────────────────────────
    const SNAP = 8 / scale;  // snap threshold in canvas px (≈8 screen px)

    function snapTargets(exKind, exIndex) {
        const W = ed.canvas_width, H = ed.canvas_height;
        const xs = [0, W / 4, W / 3, W / 2, 2 * W / 3, 3 * W / 4, W].map(Math.round);
        const ys = [0, H / 4, H / 3, H / 2, 2 * H / 3, 3 * H / 4, H].map(Math.round);
        const all = [
            ...ed.slots.map((it, i) => ({ it, kind: 'slot', i })),
            ...ed.overlays.map((it, i) => ({ it, kind: 'overlay', i })),
            ...ed.texts.map((it, i) => ({ it, kind: 'text', i })),
        ];
        all.forEach(({ it, kind, i }) => {
            if (kind === exKind && i === exIndex) return;
            xs.push(it.x, it.x + it.w / 2, it.x + it.w);
            ys.push(it.y, it.y + it.h / 2, it.y + it.h);
        });
        return { xs, ys };
    }

    function nearest(value, targets) {
        let best = null;
        targets.forEach(t => {
            const d = Math.abs(value - t);
            if (d <= SNAP && (best === null || d < best.d)) best = { d, t };
        });
        return best;
    }

    // Snap position (move): align left/center/right & top/middle/bottom edges
    function applySnapMove(item, exKind, exIndex) {
        if (!snapEnabled) return [];
        const { xs, ys } = snapTargets(exKind, exIndex);
        const guides = [];
        const xc = [[item.x, 0], [item.x + item.w / 2, item.w / 2], [item.x + item.w, item.w]];
        let bx = null;
        xc.forEach(([val, off]) => { const n = nearest(val, xs); if (n && (!bx || n.d < bx.d)) bx = { ...n, off }; });
        if (bx) { item.x = Math.round(bx.t - bx.off); guides.push({ axis: 'x', pos: bx.t }); }
        const yc = [[item.y, 0], [item.y + item.h / 2, item.h / 2], [item.y + item.h, item.h]];
        let by = null;
        yc.forEach(([val, off]) => { const n = nearest(val, ys); if (n && (!by || n.d < by.d)) by = { ...n, off }; });
        if (by) { item.y = Math.round(by.t - by.off); guides.push({ axis: 'y', pos: by.t }); }
        return guides;
    }

    // Snap size (resize): align the right/bottom edges
    function applySnapResize(item, exKind, exIndex) {
        if (!snapEnabled) return [];
        const { xs, ys } = snapTargets(exKind, exIndex);
        const guides = [];
        const nx = nearest(item.x + item.w, xs);
        if (nx) { item.w = Math.max(40, Math.round(nx.t - item.x)); guides.push({ axis: 'x', pos: nx.t }); }
        const ny = nearest(item.y + item.h, ys);
        if (ny) { item.h = Math.max(40, Math.round(ny.t - item.y)); guides.push({ axis: 'y', pos: ny.t }); }
        return guides;
    }

    function drawGuides(guides) {
        let layer = canvas.querySelector('#guide-dyn');
        if (!layer) {
            layer = document.createElement('div');
            layer.id = 'guide-dyn';
            layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:10;';
            canvas.appendChild(layer);
        }
        layer.innerHTML = '';
        guides.forEach(g => {
            const l = document.createElement('div');
            l.style.cssText = g.axis === 'x'
                ? `position:absolute;left:${g.pos * scale}px;top:0;width:1px;height:100%;background:#ff3b9a;box-shadow:0 0 4px #ff3b9a;`
                : `position:absolute;top:${g.pos * scale}px;left:0;height:1px;width:100%;background:#ff3b9a;box-shadow:0 0 4px #ff3b9a;`;
            layer.appendChild(l);
        });
    }
    function clearGuides() { const l = canvas.querySelector('#guide-dyn'); if (l) l.innerHTML = ''; }

    function makeBox(item, index, kind, label, assetId) {
        const box = document.createElement('div');
        const isSel = selected && selected.kind === kind && selected.index === index;
        const border = kind === 'slot' ? '#5b9bd5' : kind === 'text' ? '#70ad47' : '#ed7d31';
        box.style.cssText = `position:absolute;left:${item.x * scale}px;top:${item.y * scale}px;width:${item.w * scale}px;height:${item.h * scale}px;
            border:2px ${kind === 'text' ? 'dashed' : 'solid'} ${border};box-sizing:border-box;cursor:move;
            background:${assetId ? `url(${assetThumb(assetId)}) center/contain no-repeat` : kind === 'text' ? 'transparent' : 'rgba(91,155,213,0.25)'};
            transform:rotate(${item.rotation || 0}deg);transform-origin:center center;
            display:flex;align-items:center;justify-content:center;color:#1b3a5b;font-weight:bold;${isSel ? 'outline:2px dashed #fff;outline-offset:1px;' : ''}`;
        if (kind === 'text') {
            box.style.color = item.color || '#000';
            box.style.fontFamily = fontCss(item.font);
            box.style.fontSize = ((item.size || 48) * scale) + 'px';
            box.style.fontWeight = item.bold ? '700' : '400';
            box.style.fontStyle = item.italic ? 'italic' : 'normal';
            box.style.justifyContent = item.align === 'left' ? 'flex-start' : item.align === 'right' ? 'flex-end' : 'center';
            box.style.alignItems = item.valign === 'top' ? 'flex-start' : item.valign === 'bottom' ? 'flex-end' : 'center';
            box.style.textAlign = item.align || 'center';
            box.style.overflow = 'hidden';
            box.style.whiteSpace = 'pre-wrap';
            box.style.lineHeight = '1.1';
            box.style.padding = '0';
            box.textContent = item.text || 'Text';
        } else if (label) {
            box.textContent = label;
        }

        box.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            selected = { kind, index };
            startDrag(e, item, box);
            drawSlotProps();
        });
        return box;
    }

    // Touch-friendly: the WHOLE box is the drag target; the active mode
    // (move/resize/rotate) decides what dragging does — no tiny corner handle.
    function startDrag(e, item, box) {
        const startX = e.clientX, startY = e.clientY;
        const orig = { x: item.x, y: item.y, w: item.w, h: item.h, rotation: item.rotation || 0 };
        const rect = box.getBoundingClientRect();
        const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
        const startAng = Math.atan2(startY - cy, startX - cx) * 180 / Math.PI;
        try { box.setPointerCapture(e.pointerId); } catch {}
        const onMove = (ev) => {
            const dx = (ev.clientX - startX) / scale;
            const dy = (ev.clientY - startY) / scale;
            if (editMode === 'resize') {
                item.w = Math.max(40, Math.round(orig.w + dx));
                item.h = Math.max(40, Math.round(orig.h + dy));
                drawGuides(applySnapResize(item, selected.kind, selected.index));
                box.style.width = item.w * scale + 'px';
                box.style.height = item.h * scale + 'px';
            } else if (editMode === 'rotate') {
                const ang = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI;
                item.rotation = Math.round(orig.rotation + (ang - startAng));
                box.style.transform = `rotate(${item.rotation}deg)`;
            } else {
                item.x = Math.max(0, Math.min(ed.canvas_width - item.w, Math.round(orig.x + dx)));
                item.y = Math.max(0, Math.min(ed.canvas_height - item.h, Math.round(orig.y + dy)));
                drawGuides(applySnapMove(item, selected.kind, selected.index));
                box.style.left = item.x * scale + 'px';
                box.style.top = item.y * scale + 'px';
            }
        };
        const onUp = (ev) => {
            box.removeEventListener('pointermove', onMove);
            box.removeEventListener('pointerup', onUp);
            try { box.releasePointerCapture(ev.pointerId); } catch {}
            clearGuides();
            drawSlotProps();
        };
        box.addEventListener('pointermove', onMove);
        box.addEventListener('pointerup', onUp);
    }

    function drawSlotProps() {
        const el = container.querySelector('#slot-props');
        if (!selected) { el.innerHTML = '<p style="font-size:0.8rem;color:var(--pb-color-text-muted);">Klicke einen Slot/Overlay zum Auswählen.</p>'; return; }
        const list = selected.kind === 'slot' ? ed.slots : selected.kind === 'text' ? ed.texts : ed.overlays;
        const item = list[selected.index];
        if (!item) { selected = null; return drawSlotProps(); }

        if (selected.kind === 'text') {
            const fontOpts = availableFonts.map(f => `<option value="${f}" ${item.font === f ? 'selected' : ''}>${f}</option>`).join('');
            el.innerHTML = `
            <div style="font-size:0.8rem;background:#0e1a30;padding:0.5rem;border-radius:6px;display:flex;flex-direction:column;gap:0.45rem;">
                <strong>Text</strong>
                <textarea id="t-content" class="admin-input" style="width:100%;min-height:48px;resize:vertical;">${item.text || ''}</textarea>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;">
                    <label>Schriftart<select id="t-font" class="admin-input" style="width:100%;">${fontOpts}</select></label>
                    <label>Größe (px)<input id="t-size" type="number" class="admin-input" style="width:100%;" value="${item.size || 48}"></label>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.4rem;align-items:end;">
                    <label>Farbe<input id="t-color" type="color" class="admin-input" style="width:100%;height:34px;padding:2px;" value="${item.color || '#000000'}"></label>
                    <label>Ausrichtung<select id="t-align" class="admin-input" style="width:100%;">
                        <option value="left" ${item.align === 'left' ? 'selected' : ''}>links</option>
                        <option value="center" ${(item.align || 'center') === 'center' ? 'selected' : ''}>zentriert</option>
                        <option value="right" ${item.align === 'right' ? 'selected' : ''}>rechts</option>
                    </select></label>
                    <label>Drehung°<input id="t-rot" type="number" class="admin-input" style="width:100%;" value="${item.rotation || 0}"></label>
                </div>
                <div style="display:flex;gap:1rem;align-items:center;">
                    <label style="display:flex;gap:0.3rem;align-items:center;"><input type="checkbox" id="t-bold" ${item.bold ? 'checked' : ''}> Fett</label>
                    <label style="display:flex;gap:0.3rem;align-items:center;"><input type="checkbox" id="t-italic" ${item.italic ? 'checked' : ''}> Kursiv</label>
                    <label style="display:flex;gap:0.3rem;align-items:center;">Kontur<input type="number" id="t-stroke" class="admin-input" style="width:48px;" value="${item.stroke_width || 0}"></label>
                </div>
                <button id="p-del" class="admin-btn admin-btn-outline" style="font-size:0.75rem;color:var(--pb-color-error);">Entfernen</button>
            </div>`;
            const upd = (k, v) => { item[k] = v; drawCanvas(); };
            el.querySelector('#t-content').addEventListener('input', e => upd('text', e.target.value));
            el.querySelector('#t-font').addEventListener('change', e => upd('font', e.target.value));
            el.querySelector('#t-size').addEventListener('change', e => upd('size', parseInt(e.target.value) || 48));
            el.querySelector('#t-color').addEventListener('input', e => upd('color', e.target.value));
            el.querySelector('#t-align').addEventListener('change', e => upd('align', e.target.value));
            el.querySelector('#t-rot').addEventListener('change', e => upd('rotation', parseInt(e.target.value) || 0));
            el.querySelector('#t-bold').addEventListener('change', e => upd('bold', e.target.checked));
            el.querySelector('#t-italic').addEventListener('change', e => upd('italic', e.target.checked));
            el.querySelector('#t-stroke').addEventListener('change', e => upd('stroke_width', Math.max(0, parseInt(e.target.value) || 0)));
            el.querySelector('#p-del').addEventListener('click', () => { ed.texts.splice(selected.index, 1); selected = null; drawCanvas(); });
            return;
        }

        el.innerHTML = `
            <div style="font-size:0.8rem;background:#0e1a30;padding:0.5rem;border-radius:6px;">
                <strong>${selected.kind === 'slot' ? 'Slot ' + (selected.index + 1) : 'Overlay'}</strong>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;margin-top:0.4rem;">
                    ${selected.kind === 'slot' ? `
                    <label>Füllung
                        <select id="p-fit" class="admin-input" style="width:100%;">
                            <option value="cover" ${item.fit === 'cover' ? 'selected' : ''}>cover (füllen)</option>
                            <option value="contain" ${item.fit === 'contain' ? 'selected' : ''}>contain (ganz)</option>
                        </select></label>
                    <label>Aufnahme Nr.
                        <input id="p-shot" type="number" min="1" class="admin-input" style="width:100%;"
                            value="${(item.photo_index != null ? item.photo_index : selected.index) + 1}"></label>` : '<span></span>'}
                    <label>Drehung°<input id="p-rot" type="number" class="admin-input" style="width:100%;" value="${item.rotation || 0}"></label>
                </div>
                ${selected.kind === 'slot' ? `<p style="font-size:0.72rem;color:var(--pb-color-text-muted);margin:0.4rem 0 0;">
                    Gleiche <strong>Aufnahme Nr.</strong> in mehreren Slots = dasselbe Foto mehrfach. Die Box nimmt nur so viele Fotos auf, wie es verschiedene Nummern gibt.</p>` : ''}
                <button id="p-del" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;font-size:0.75rem;color:var(--pb-color-error);">Entfernen</button>
            </div>`;
        el.querySelector('#p-fit')?.addEventListener('change', (e) => { item.fit = e.target.value; });
        el.querySelector('#p-shot')?.addEventListener('change', (e) => {
            item.photo_index = Math.max(1, parseInt(e.target.value) || 1) - 1;   // store 0-based
        });
        el.querySelector('#p-rot')?.addEventListener('change', (e) => { item.rotation = parseInt(e.target.value) || 0; drawCanvas(); });
        el.querySelector('#p-del')?.addEventListener('click', () => { list.splice(selected.index, 1); selected = null; drawCanvas(); });
    }

    // Controls
    container.querySelector('#btn-back')?.addEventListener('click', () => renderList(container, state));

    // Mode switch: move / resize / rotate (touch-friendly)
    function updateModeButtons() {
        container.querySelectorAll('.mode-btn').forEach(b => {
            const on = b.dataset.mode === editMode;
            b.classList.toggle('admin-btn-primary', on);
            b.classList.toggle('admin-btn-outline', !on);
        });
    }
    container.querySelectorAll('.mode-btn').forEach(b => {
        b.addEventListener('click', () => { editMode = b.dataset.mode; updateModeButtons(); });
    });
    updateModeButtons();

    container.querySelector('#t-snap')?.addEventListener('change', e => { snapEnabled = e.target.checked; });
    container.querySelector('#t-guides')?.addEventListener('change', e => { showGuides = e.target.checked; drawCanvas(); });

    container.querySelector('#btn-add-text')?.addEventListener('click', () => {
        const input = container.querySelector('#f-text');
        const txt = (input.value || '').trim() || 'Text';
        ed.texts.push({
            text: txt, x: Math.round(ed.canvas_width * 0.1), y: Math.round(ed.canvas_height * 0.4),
            w: Math.round(ed.canvas_width * 0.8), h: Math.round(ed.canvas_height * 0.12),
            rotation: 0, font: availableFonts[0] || 'Sans', size: Math.round(ed.canvas_width * 0.06),
            color: '#000000', align: 'center', valign: 'middle', bold: false, italic: false, stroke_width: 0,
        });
        input.value = '';
        selected = { kind: 'text', index: ed.texts.length - 1 };
        drawCanvas();
    });

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

    // Output-format (preset) selector: binds the canvas to a print paper / social
    // format. The backend keeps the canvas in sync with the chosen preset.
    container.querySelector('#f-preset')?.addEventListener('change', (e) => {
        const val = e.target.value ? parseInt(e.target.value) : null;
        ed.preset_id = val;
        const p = val != null ? presets.find(x => x.id === val) : null;
        if (p) { ed.canvas_width = p.width_px; ed.canvas_height = p.height_px; }
        renderEditor(container, state, ed);  // rescale + reflect bound/free state
    });

    const reW = container.querySelector('#f-w'), reH = container.querySelector('#f-h');
    if (reW && reH) [reW, reH].forEach(inp => inp.addEventListener('change', () => {
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
            preset_id: ed.preset_id ?? null,
            background_asset_id: ed.background_asset_id, overlay_asset_id: ed.overlay_asset_id,
            definition: { slots: ed.slots, overlays: ed.overlays, texts: ed.texts },
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
