import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

// Cache discovered devices — only rescan when user clicks the button
let cachedDevices = null;

export async function render(container, state) {
    const headers = getHeaders();

    let camStatus = {};
    try {
        camStatus = await fetch('/api/v1/camera/status').then(r => r.json());
    } catch {}

    const devices = cachedDevices || [];
    const previewId = camStatus.preview || '';
    const captureId = camStatus.capture || previewId;
    const separateCapture = camStatus.capture && camStatus.capture !== camStatus.preview;

    // Build camera options from cached devices + fixed types
    const usbCameras = devices.map(d => ({
        id: `opencv:${d.index}`,
        label: d.name,
        working: d.working !== false,
        type: 'opencv',
        config: { device_index: d.index },
    }));

    const otherCameras = [
        { id: 'webrtc', label: 'Browser Webcam (WebRTC)', working: true, type: 'webrtc', config: {} },
        { id: 'gphoto2', label: 'DSLR via gPhoto2 (Linux)', working: true, type: 'gphoto2', config: {} },
        { id: 'digicamcontrol', label: 'DSLR via digiCamControl (Windows)', working: true, type: 'digicamcontrol', config: {} },
    ];

    const allCameras = [...usbCameras, ...otherCameras];

    function isActive(cam, activeId) {
        if (!activeId) return false;
        if (cam.type === 'opencv') return activeId.includes('opencv') && activeId.endsWith(`.${cam.config.device_index}`);
        return activeId.includes(cam.type);
    }

    function cameraList(prefix, activeId) {
        return allCameras.map(c => {
            const active = isActive(c, activeId);
            const disabled = !c.working ? 'opacity:0.5;' : '';
            const signal = !c.working ? ' <span style="color:var(--pb-color-error);">[kein Signal]</span>' : '';
            return `
            <label style="display:flex;align-items:center;gap:0.75rem;padding:0.6rem 0.75rem;border-radius:8px;cursor:pointer;margin-bottom:0.3rem;${disabled}
                border:1px solid ${active ? 'var(--pb-color-primary)' : '#333'};
                background:${active ? 'rgba(74,144,217,0.1)' : 'transparent'};">
                <input type="radio" name="${prefix}_cam" value="${c.id}" data-type="${c.type}" data-config='${JSON.stringify(c.config)}' ${active ? 'checked' : ''}>
                <span>${c.label}${signal}</span>
            </label>`;
        }).join('');
    }

    // Current rotation/flip settings
    let settings = {};
    try {
        settings = await fetch('/api/v1/settings/', { headers }).then(r => r.json());
    } catch {}
    const camSettings = settings?.cameras?.transform || {};
    const rotation = camSettings.rotation || 0;
    const flipH = camSettings.flip_horizontal || false;
    const flipV = camSettings.flip_vertical || false;

    const countdownSeconds = settings?.session?.countdown_seconds ?? 3;
    const captureLeadMs = settings?.session?.capture_lead_ms ?? 0;

    // DSLR focus modes (gphoto2) — only meaningful when a gphoto2 camera is active
    let focus = { available: false, choices: [], current: '' };
    try { focus = await fetch('/api/v1/camera/focus-modes').then(r => r.json()); } catch {}
    const gphotoActive = (captureId || previewId || '').includes('gphoto2');
    const focusField = focus.available && (focus.choices || []).length
        ? `<select id="focus-mode" class="admin-input" style="width:220px;">
               <option value="">— Kamera-Standard —</option>
               ${focus.choices.map(c => `<option value="${c}" ${c === focus.current ? 'selected' : ''}>${c}</option>`).join('')}
           </select>`
        : `<input id="focus-mode" class="admin-input" style="width:220px;" placeholder="z. B. One Shot / Manual" value="${focus.current || ''}">`;

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Kamera-Einstellungen</h1>
        <div style="max-width:650px;">

            <div class="admin-card">
                <h3>USB-Kameras suchen</h3>
                ${devices.length
                    ? devices.map(d => `<p>
                        <span style="color:${d.working !== false ? 'var(--pb-color-success)' : 'var(--pb-color-error)'};">
                            ${d.working !== false ? '&#10003;' : '&#10007;'}
                        </span> ${d.name}
                      </p>`).join('')
                    : '<p style="color:var(--pb-color-text-muted);">Noch nicht gesucht — klicke "Kameras suchen".</p>'}
                <button id="btn-rescan" class="admin-btn admin-btn-outline" style="margin-top:0.5rem;font-size:0.85rem;">Kameras suchen</button>
                <span id="scan-status" style="margin-left:0.5rem;font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
            </div>

            <div class="admin-card">
                <h3>Vorschau-Kamera</h3>
                ${cameraList('preview', previewId)}
            </div>

            <div class="admin-card">
                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-bottom:0.75rem;">
                    <input type="checkbox" id="separate-capture" ${separateCapture ? 'checked' : ''}>
                    <strong>Andere Kamera f&uuml;r Fotoaufnahme</strong>
                </label>
                <div id="capture-section" style="${separateCapture ? '' : 'display:none'}">
                    ${cameraList('capture', captureId)}
                </div>
            </div>

            <div class="admin-card">
                <h3>Bild-Transformation</h3>
                <div style="display:flex;flex-wrap:wrap;gap:1.5rem;align-items:flex-start;">
                    <div>
                        <label style="display:block;margin-bottom:0.3rem;font-size:0.9rem;">Drehung</label>
                        <select id="rotation" class="admin-input" style="width:140px;">
                            <option value="0" ${rotation === 0 ? 'selected' : ''}>0° (Normal)</option>
                            <option value="90" ${rotation === 90 ? 'selected' : ''}>90° rechts</option>
                            <option value="180" ${rotation === 180 ? 'selected' : ''}>180°</option>
                            <option value="270" ${rotation === 270 ? 'selected' : ''}>270° links</option>
                        </select>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:0.5rem;">
                        <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                            <input type="checkbox" id="flip-h" ${flipH ? 'checked' : ''}> Horizontal spiegeln
                        </label>
                        <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                            <input type="checkbox" id="flip-v" ${flipV ? 'checked' : ''}> Vertikal spiegeln
                        </label>
                    </div>
                </div>
            </div>

            <div class="admin-card">
                <h3>Countdown &amp; Auslösung</h3>
                <div style="display:flex;flex-wrap:wrap;gap:1.5rem;align-items:flex-start;">
                    <div>
                        <label style="display:block;margin-bottom:0.3rem;font-size:0.9rem;">Countdown-Dauer</label>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            <input id="countdown-seconds" type="number" min="1" max="10" step="1" value="${countdownSeconds}" class="admin-input" style="width:90px;">
                            <span style="color:var(--pb-color-text-muted);font-size:0.9rem;">Sekunden</span>
                        </div>
                    </div>
                    <div>
                        <label style="display:block;margin-bottom:0.3rem;font-size:0.9rem;">Auslöse-Vorlauf</label>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            <input id="capture-lead" type="number" min="0" max="2000" step="50" value="${captureLeadMs}" class="admin-input" style="width:90px;">
                            <span style="color:var(--pb-color-text-muted);font-size:0.9rem;">ms vor der Null</span>
                        </div>
                    </div>
                </div>
                <p style="color:var(--pb-color-text-muted);font-size:0.82rem;margin-top:0.6rem;">
                    Der Vorlauf gleicht die Auslöseverzögerung der Kamera aus, damit das Foto genau bei „0" entsteht.
                    Typisch: DSLR 200–600&nbsp;ms, Webcam 0–100&nbsp;ms.
                </p>
            </div>

            <div class="admin-card">
                <h3>DSLR-Fokus (gPhoto2)</h3>
                ${gphotoActive
                    ? `<p style="color:var(--pb-color-text-muted);font-size:0.85rem;margin-bottom:0.5rem;">
                          ${focus.available ? 'Fokus-Modus der angeschlossenen Kamera.' : (focus.reason || 'Kamera meldet keine Fokus-Modi — Wert wird direkt übergeben.')}
                       </p>`
                    : `<p style="color:var(--pb-color-text-muted);font-size:0.85rem;margin-bottom:0.5rem;">
                          Gilt nur, wenn eine gPhoto2-DSLR als Aufnahme-Kamera aktiv ist. Wird beim Aktivieren mitgespeichert.
                       </p>`}
                <div style="display:flex;flex-wrap:wrap;gap:1.5rem;align-items:center;">
                    <div>
                        <label style="display:block;margin-bottom:0.3rem;font-size:0.9rem;">Fokus-Modus</label>
                        ${focusField}
                    </div>
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-top:1rem;">
                        <input type="checkbox" id="focus-af"> Vor jeder Aufnahme autofokussieren
                    </label>
                </div>
            </div>

            <div class="admin-card">
                <h3>Vorschau</h3>
                <div style="width:100%;max-width:480px;aspect-ratio:4/3;background:#000;border-radius:8px;overflow:hidden;">
                    ${camStatus.mode === 'server'
                        ? '<img src="/api/v1/camera/stream" style="width:100%;height:100%;object-fit:cover;" alt="Preview">'
                        : '<p style="color:#666;text-align:center;padding:2rem;">WebRTC — Vorschau nur im Booth</p>'}
                </div>
            </div>

            <button id="btn-save" class="admin-btn admin-btn-primary">Kamera aktivieren</button>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>
        </div>
    `);

    setupLogout(container);

    container.querySelector('#separate-capture')?.addEventListener('change', (e) => {
        document.getElementById('capture-section').style.display = e.target.checked ? '' : 'none';
    });

    // Rescan — only when button clicked
    container.querySelector('#btn-rescan')?.addEventListener('click', async () => {
        const btn = container.querySelector('#btn-rescan');
        const status = container.querySelector('#scan-status');
        btn.disabled = true;
        btn.textContent = 'Suche...';
        status.textContent = '';
        try {
            const res = await fetch('/api/v1/camera/devices');
            cachedDevices = await res.json();
            status.textContent = `${cachedDevices.length} Gerät(e) gefunden`;
            status.style.color = 'var(--pb-color-success)';
        } catch {
            status.textContent = 'Fehler beim Scannen';
            status.style.color = 'var(--pb-color-error)';
        }
        render(container, state);
    });

    // Save & activate
    container.querySelector('#btn-save')?.addEventListener('click', async () => {
        const msg = container.querySelector('#msg');
        msg.textContent = 'Aktiviere...';
        msg.style.color = 'var(--pb-color-text-muted)';

        const previewRadio = container.querySelector('input[name="preview_cam"]:checked');
        if (!previewRadio) { msg.textContent = 'Bitte Kamera wählen'; return; }
        const separateCapture = container.querySelector('#separate-capture').checked;

        // DSLR focus settings — attached to gphoto2 payloads
        const focusMode = container.querySelector('#focus-mode')?.value || '';
        const autofocus = container.querySelector('#focus-af')?.checked || false;
        const withFocus = (payload) => payload.type === 'gphoto2'
            ? { ...payload, focus_mode: focusMode, autofocus }
            : payload;

        try {
            // Activate preview camera
            const previewPayload = withFocus({
                type: previewRadio.dataset.type,
                role: separateCapture ? 'preview' : 'both',
                ...JSON.parse(previewRadio.dataset.config),
            });
            const r1 = await fetch('/api/v1/camera/activate', {
                method: 'POST', headers, body: JSON.stringify(previewPayload),
            });
            if (!r1.ok) throw new Error((await r1.json()).detail);

            // Separate capture camera
            if (separateCapture) {
                const captureRadio = container.querySelector('input[name="capture_cam"]:checked');
                if (captureRadio) {
                    const capturePayload = withFocus({
                        type: captureRadio.dataset.type,
                        role: 'capture',
                        ...JSON.parse(captureRadio.dataset.config),
                    });
                    const r2 = await fetch('/api/v1/camera/activate', {
                        method: 'POST', headers, body: JSON.stringify(capturePayload),
                    });
                    if (!r2.ok) throw new Error((await r2.json()).detail);
                }
            }

            // Save rotation/flip settings
            const transform = {
                rotation: parseInt(container.querySelector('#rotation').value) || 0,
                flip_horizontal: container.querySelector('#flip-h').checked,
                flip_vertical: container.querySelector('#flip-v').checked,
            };
            await fetch('/api/v1/settings/cameras/transform', {
                method: 'PUT', headers,
                body: JSON.stringify({ key: 'cameras.transform', value: transform }),
            });

            // Countdown duration + capture lead time
            const cdSecs = Math.max(1, Math.min(10, parseInt(container.querySelector('#countdown-seconds').value) || 3));
            const leadMs = Math.max(0, Math.min(2000, parseInt(container.querySelector('#capture-lead').value) || 0));
            await fetch('/api/v1/settings/session.countdown_seconds', {
                method: 'PUT', headers,
                body: JSON.stringify({ key: 'session.countdown_seconds', value: cdSecs }),
            });
            await fetch('/api/v1/settings/session.capture_lead_ms', {
                method: 'PUT', headers,
                body: JSON.stringify({ key: 'session.capture_lead_ms', value: leadMs }),
            });

            msg.style.color = 'var(--pb-color-success)';
            msg.textContent = 'Kamera aktiviert!';
            setTimeout(() => render(container, state), 1500);
        } catch (err) {
            msg.style.color = 'var(--pb-color-error)';
            msg.textContent = 'Fehler: ' + err.message;
        }
    });
}
