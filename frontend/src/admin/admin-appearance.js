import { adminShell, getHeaders, setupLogout } from './admin-shell.js';
import { applyThemeObject, applyTheme } from '../core/theme.js';

const COLOR_FIELDS = [
    ['primary', 'Primärfarbe (Buttons, Akzente)'],
    ['secondary', 'Sekundärfarbe (Verlauf)'],
    ['accent', 'Akzentfarbe'],
    ['background', 'Hintergrund'],
    ['surface', 'Flächen / Karten'],
    ['text', 'Text'],
    ['text_muted', 'Text (gedämpft)'],
];

const HEADING_FONTS = [
    ['', 'Standard'],
    ['Pacifico, cursive', 'Pacifico (verschnörkelt)'],
    ['"Great Vibes", cursive', 'Great Vibes (elegant)'],
    ['"Dancing Script", cursive', 'Dancing Script'],
    ['Lobster, cursive', 'Lobster'],
    ['Sacramento, cursive', 'Sacramento'],
    ['Georgia, serif', 'Serif (Georgia)'],
    ['"Courier New", monospace', 'Monospace'],
];

export async function render(container, state) {
    const headers = getHeaders();
    const authHeader = { 'Authorization': `Bearer ${state.auth.token}` };

    let theme = {};
    try { theme = await fetch('/api/v1/theme').then(r => r.json()); } catch {}

    const slider = (id, label, min, max, step, val, unit = '') => `
        <div style="margin-bottom:0.85rem;">
            <label style="font-size:0.88rem;display:flex;justify-content:space-between;">
                <span>${label}</span><span id="${id}-out" style="color:var(--pb-color-text-muted);">${val}${unit}</span>
            </label>
            <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}" style="width:100%;">
        </div>`;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Design / Oberfläche</h1>
        <div style="max-width:680px;">

            <div class="admin-card">
                <h3>🎨 Farben</h3>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.6rem 1rem;">
                    ${COLOR_FIELDS.map(([k, label]) => `
                        <label style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;">
                            <input type="color" class="th-color" data-key="${k}" value="${theme[k] || '#000000'}"
                                style="width:40px;height:30px;padding:2px;border-radius:6px;border:1px solid var(--pb-color-border);">
                            <span>${label}</span>
                        </label>`).join('')}
                </div>
            </div>

            <div class="admin-card">
                <h3>🔠 Größen &amp; Schrift</h3>
                ${slider('radius', 'Eckenrundung', 0, 32, 1, theme.radius ?? 14, ' px')}
                ${slider('ui_scale', 'Gesamtgröße der Oberfläche', 0.8, 1.4, 0.05, theme.ui_scale ?? 1)}
                ${slider('heading_scale', 'Überschriften-Größe', 0.7, 1.8, 0.05, theme.heading_scale ?? 1)}
                <label style="font-size:0.88rem;display:block;margin-top:0.5rem;">Überschriften-Schriftart
                    <select id="heading_font" class="admin-input" style="width:100%;margin-top:0.25rem;">
                        ${HEADING_FONTS.map(([v, l]) => `<option value='${v}' ${(theme.heading_font || '') === v ? 'selected' : ''}>${l}</option>`).join('')}
                    </select>
                </label>
            </div>

            <div class="admin-card">
                <h3>🖼️ Hintergrundbild (für alles)</h3>
                <div id="bg-preview" style="height:120px;border-radius:10px;border:1px solid var(--pb-color-border);margin-bottom:0.6rem;
                    background:${theme.background_image ? `center/cover no-repeat url("${theme.background_image}")` : 'var(--pb-color-surface)'};
                    display:flex;align-items:center;justify-content:center;color:var(--pb-color-text-muted);font-size:0.85rem;">
                    ${theme.background_image ? '' : 'Kein Hintergrundbild'}
                </div>
                <div style="display:flex;gap:0.6rem;flex-wrap:wrap;align-items:center;">
                    <input type="file" id="bg-file" accept="image/*" style="font-size:0.85rem;">
                    <button id="bg-remove" class="admin-btn admin-btn-outline" style="font-size:0.82rem;">Entfernen</button>
                </div>
                ${slider('background_dim', 'Abdunklung (Lesbarkeit)', 0, 0.8, 0.05, theme.background_dim ?? 0)}
                <p id="bg-msg" style="font-size:0.85rem;margin-top:0.4rem;color:var(--pb-color-text-muted);"></p>
            </div>

            <div style="display:flex;gap:0.75rem;margin-top:0.5rem;">
                <button id="btn-save" class="admin-btn admin-btn-primary">Speichern</button>
                <button id="btn-reset" class="admin-btn admin-btn-outline">Zurücksetzen</button>
            </div>
            <p id="msg" style="margin-top:0.6rem;font-size:0.9rem;"></p>
        </div>
    `);
    setupLogout(container);

    const setMsg = (t, k) => { const m = container.querySelector('#msg'); m.textContent = t; m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)'; };

    // Collect the current form into a theme object
    const collect = () => {
        const t = {};
        container.querySelectorAll('.th-color').forEach(c => { t[c.dataset.key] = c.value; });
        t.radius = parseInt(container.querySelector('#radius').value);
        t.ui_scale = parseFloat(container.querySelector('#ui_scale').value);
        t.heading_scale = parseFloat(container.querySelector('#heading_scale').value);
        t.heading_font = container.querySelector('#heading_font').value;
        t.background_image = theme.background_image || '';
        t.background_dim = parseFloat(container.querySelector('#background_dim').value);
        return t;
    };

    // Live preview on any change
    const preview = () => {
        const t = collect();
        applyThemeObject(t);
        container.querySelector('#radius-out').textContent = t.radius + ' px';
        container.querySelector('#ui_scale-out').textContent = t.ui_scale;
        container.querySelector('#heading_scale-out').textContent = t.heading_scale;
        container.querySelector('#background_dim-out').textContent = t.background_dim;
    };
    container.querySelectorAll('.th-color, #radius, #ui_scale, #heading_scale, #background_dim, #heading_font')
        .forEach(el => el.addEventListener('input', preview));

    container.querySelector('#btn-save')?.addEventListener('click', async () => {
        setMsg('Speichere…');
        try {
            const res = await fetch('/api/v1/theme', { method: 'PUT', headers, body: JSON.stringify(collect()) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
            theme = await res.json();
            setMsg('Gespeichert! Das Design gilt jetzt überall (Booth & Admin).', 'ok');
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });

    container.querySelector('#btn-reset')?.addEventListener('click', async () => {
        if (!confirm('Design auf Standard zurücksetzen?')) return;
        try {
            await fetch('/api/v1/theme/reset', { method: 'POST', headers });
            await applyTheme();
            render(container, state);
        } catch (err) { setMsg('Fehler: ' + err.message, 'error'); }
    });

    // Background image upload
    container.querySelector('#bg-file')?.addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const bgMsg = container.querySelector('#bg-msg');
        bgMsg.textContent = 'Lade hoch…';
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch('/api/v1/theme/background', { method: 'POST', headers: authHeader, body: fd });
            const r = await res.json();
            if (!res.ok) throw new Error(r.detail || 'Fehler');
            theme.background_image = r.background_image;
            container.querySelector('#bg-preview').style.background = `center/cover no-repeat url("${r.background_image}")`;
            container.querySelector('#bg-preview').textContent = '';
            bgMsg.textContent = 'Hochgeladen. Mit „Speichern" übernehmen.';
            preview();
        } catch (err) { bgMsg.textContent = 'Fehler: ' + err.message; }
    });

    container.querySelector('#bg-remove')?.addEventListener('click', async () => {
        try {
            await fetch('/api/v1/theme/background', { method: 'DELETE', headers });
            theme.background_image = '';
            const p = container.querySelector('#bg-preview');
            p.style.background = 'var(--pb-color-surface)';
            p.textContent = 'Kein Hintergrundbild';
            preview();
        } catch {}
    });
}
