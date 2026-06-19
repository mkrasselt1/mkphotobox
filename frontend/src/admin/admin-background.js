import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let status = {};
    try {
        status = await fetch('/api/v1/background/status').then(r => r.json());
    } catch {}

    const currentMode = status.mode || 'none';
    const rembgAvail = status.rembg_available || false;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Hintergrund-Entfernung</h1>
        <div style="max-width:650px;">

            <div class="admin-card">
                <h3>Modus</h3>
                <div style="display:flex;flex-direction:column;gap:0.5rem;">
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                        <input type="radio" name="bg_mode" value="none" ${currentMode === 'none' ? 'checked' : ''}>
                        <strong>Aus</strong>
                    </label>
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;${rembgAvail ? '' : 'opacity:0.5;'}">
                        <input type="radio" name="bg_mode" value="ai" ${currentMode === 'ai' ? 'checked' : ''} ${rembgAvail ? '' : 'disabled'}>
                        <div>
                            <strong>KI-basiert (rembg)</strong> — Erkennt Personen automatisch<br>
                            <small style="color:var(--pb-color-text-muted);">
                                ${rembgAvail
                                    ? 'Wird nur auf das finale Foto angewendet (ca. 5-10s). Vorschau bleibt normal.'
                                    : 'Nicht installiert. <code>pip install rembg[cpu]</code>'}
                            </small>
                        </div>
                    </label>
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                        <input type="radio" name="bg_mode" value="chromakey" ${currentMode === 'chromakey' ? 'checked' : ''}>
                        <div>
                            <strong>Greenscreen / Chroma Key</strong> — Farbe per Klick w&auml;hlen<br>
                            <small style="color:var(--pb-color-text-muted);">Schnell, funktioniert in Echtzeit auch in der Vorschau.</small>
                        </div>
                    </label>
                </div>
                <button id="btn-set-mode" class="admin-btn admin-btn-primary" style="margin-top:1rem;">Aktivieren</button>
                <span id="mode-msg" style="margin-left:0.75rem;font-size:0.85rem;"></span>
            </div>

            <!-- Chroma key settings -->
            <div class="admin-card" id="chroma-section" style="${currentMode === 'chromakey' ? '' : 'display:none'}">
                <h3>Greenscreen-Farbe w&auml;hlen</h3>
                <p style="color:var(--pb-color-text-muted);font-size:0.85rem;margin-bottom:0.75rem;">
                    Klicke auf den Hintergrund im Bild um die Farbe zu setzen.
                </p>
                <div style="width:100%;max-width:480px;aspect-ratio:4/3;background:#000;border-radius:8px;overflow:hidden;cursor:crosshair;" id="chroma-preview">
                    <img src="/api/v1/camera/snapshot" style="width:100%;height:100%;object-fit:cover;" id="chroma-img">
                </div>
                <div style="display:flex;gap:1rem;align-items:center;margin-top:0.75rem;">
                    <button id="btn-refresh-snap" class="admin-btn admin-btn-outline" style="font-size:0.85rem;">Neues Bild</button>
                    <span id="chroma-msg" style="font-size:0.85rem;"></span>
                </div>
                <div style="margin-top:1rem;">
                    <label style="font-size:0.9rem;">
                        Toleranz: <strong id="tol-val">${status.chromakey_tolerance || 30}</strong>
                        <input type="range" id="chroma-tolerance" min="5" max="80" value="${status.chromakey_tolerance || 30}" style="width:100%;margin-top:0.25rem;">
                    </label>
                </div>
            </div>

            <!-- Replacement background -->
            <div class="admin-card" id="replacement-section" style="${currentMode !== 'none' ? '' : 'display:none'}">
                <h3>Ersatz-Hintergrund</h3>
                <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">
                        Farbe: <input type="color" id="replacement-color" value="#000000" style="vertical-align:middle;">
                    </label>
                    <span style="color:var(--pb-color-text-muted);">oder</span>
                    <label class="admin-btn admin-btn-outline" style="cursor:pointer;font-size:0.85rem;">
                        Hintergrundbild hochladen
                        <input type="file" id="upload-replacement" accept="image/*" style="display:none;">
                    </label>
                </div>
                <div id="replacement-preview" style="margin-top:0.75rem;${status.has_replacement_image ? '' : 'display:none'}">
                    <p style="color:var(--pb-color-success);font-size:0.85rem;display:inline;">Hintergrundbild geladen</p>
                    <button id="btn-remove-replacement" class="admin-btn admin-btn-outline" style="margin-left:0.75rem;font-size:0.8rem;padding:0.3rem 0.8rem;">Entfernen</button>
                </div>
                <p id="replacement-msg" style="margin-top:0.5rem;font-size:0.85rem;"></p>
            </div>

            <!-- Live preview -->
            <div class="admin-card">
                <h3>Live-Vorschau</h3>
                <div style="width:100%;max-width:480px;aspect-ratio:4/3;background:#000;border-radius:8px;overflow:hidden;">
                    <img id="live-preview" src="/api/v1/camera/stream" style="width:100%;height:100%;object-fit:cover;" alt="Preview">
                </div>
                <button id="btn-reload-preview" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;font-size:0.85rem;">Vorschau neu laden</button>
            </div>
        </div>
    `);

    setupLogout(container);

    function reloadPreview() {
        const img = container.querySelector('#live-preview');
        if (img) img.src = '/api/v1/camera/stream?t=' + Date.now();
    }
    container.querySelector('#live-preview')?.addEventListener('error', () => setTimeout(reloadPreview, 1000));
    container.querySelector('#btn-reload-preview')?.addEventListener('click', reloadPreview);

    // Show/hide sections
    container.querySelectorAll('input[name="bg_mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            document.getElementById('chroma-section').style.display = radio.value === 'chromakey' ? '' : 'none';
            document.getElementById('replacement-section').style.display = radio.value !== 'none' ? '' : 'none';
        });
    });

    // Set mode
    container.querySelector('#btn-set-mode')?.addEventListener('click', async () => {
        const mode = container.querySelector('input[name="bg_mode"]:checked')?.value;
        const msg = container.querySelector('#mode-msg');
        try {
            const res = await fetch('/api/v1/background/enable', {
                method: 'POST', headers, body: JSON.stringify({ enabled: mode !== 'none', mode }),
            });
            if (!res.ok) throw new Error((await res.json()).detail);
            msg.textContent = mode === 'none' ? 'Deaktiviert' : 'Aktiviert!';
            msg.style.color = 'var(--pb-color-success)';
            setTimeout(reloadPreview, 500);
        } catch (err) {
            msg.textContent = 'Fehler: ' + err.message;
            msg.style.color = 'var(--pb-color-error)';
        }
    });

    // Color picker — click on image to pick chroma key color
    container.querySelector('#chroma-img')?.addEventListener('click', async (e) => {
        const img = e.target;
        const rect = img.getBoundingClientRect();
        const scaleX = (img.naturalWidth || 640) / rect.width;
        const scaleY = (img.naturalHeight || 480) / rect.height;
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);
        const msg = container.querySelector('#chroma-msg');
        try {
            const res = await fetch('/api/v1/background/pick-color', {
                method: 'POST', headers, body: JSON.stringify({ x, y }),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.detail);

            const hex = result.picked_color || '#000000';
            const rgb = result.rgb || {};
            msg.innerHTML = `Farbe gesetzt: <span style="
                display:inline-block;width:20px;height:20px;border-radius:4px;
                background:${hex};border:2px solid white;vertical-align:middle;margin:0 6px;
            "></span> ${hex} (R:${rgb.r} G:${rgb.g} B:${rgb.b})`;
            msg.style.color = 'var(--pb-color-success)';
            setTimeout(reloadPreview, 500);
        } catch (err) {
            msg.textContent = 'Fehler: ' + (err.message || 'Farbauswahl fehlgeschlagen');
            msg.style.color = 'var(--pb-color-error)';
        }
    });

    container.querySelector('#btn-refresh-snap')?.addEventListener('click', () => {
        const img = container.querySelector('#chroma-img');
        if (img) img.src = '/api/v1/camera/snapshot?t=' + Date.now();
    });

    // Tolerance slider
    container.querySelector('#chroma-tolerance')?.addEventListener('input', (e) => {
        container.querySelector('#tol-val').textContent = e.target.value;
    });
    container.querySelector('#chroma-tolerance')?.addEventListener('change', async (e) => {
        await fetch('/api/v1/background/settings', {
            method: 'POST', headers,
            body: JSON.stringify({ chromakey_tolerance: parseInt(e.target.value) }),
        });
        setTimeout(reloadPreview, 300);
    });

    // Remove replacement image
    container.querySelector('#btn-remove-replacement')?.addEventListener('click', async () => {
        const msg = container.querySelector('#replacement-msg');
        try {
            await fetch('/api/v1/background/remove-replacement', { method: 'POST', headers });
            container.querySelector('#replacement-preview').style.display = 'none';
            msg.textContent = 'Hintergrundbild entfernt — Farbe wird verwendet';
            msg.style.color = 'var(--pb-color-success)';
        } catch (err) {
            msg.textContent = 'Fehler';
            msg.style.color = 'var(--pb-color-error)';
        }
    });

    // Replacement color
    container.querySelector('#replacement-color')?.addEventListener('change', async (e) => {
        const msg = container.querySelector('#replacement-msg');
        try {
            await fetch('/api/v1/background/settings', {
                method: 'POST', headers,
                body: JSON.stringify({ replacement_color: e.target.value }),
            });
            msg.textContent = 'Farbe gesetzt: ' + e.target.value;
            msg.style.color = 'var(--pb-color-success)';
            // Clear replacement image when color is chosen
            container.querySelector('#replacement-preview').style.display = 'none';
        } catch (err) {
            msg.textContent = 'Fehler';
            msg.style.color = 'var(--pb-color-error)';
        }
    });

    // Upload replacement image
    container.querySelector('#upload-replacement')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const msg = container.querySelector('#replacement-msg');
        msg.textContent = 'Wird hochgeladen...';
        msg.style.color = 'var(--pb-color-text-muted)';

        const fd = new FormData();
        fd.append('file', file);
        try {
            // Important: only send Authorization header, NOT Content-Type (browser sets multipart boundary)
            const authToken = window.pb.state.auth.token;
            const res = await fetch('/api/v1/background/upload-replacement', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${authToken}` },
                body: fd,
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.detail || 'Upload fehlgeschlagen');

            msg.textContent = 'Hintergrundbild hochgeladen: ' + file.name;
            msg.style.color = 'var(--pb-color-success)';
            container.querySelector('#replacement-preview').style.display = 'block';
        } catch (err) {
            msg.textContent = 'Fehler: ' + err.message;
            msg.style.color = 'var(--pb-color-error)';
        }
    });
}
