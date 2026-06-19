/**
 * Admin Layout — Dashboard with sidebar navigation and sub-pages.
 */

let currentPage = 'dashboard';

export function render(container, state) {
    const { i18n } = window.pb;

    container.innerHTML = `
    <div style="display:flex;height:100%;">
        <!-- Sidebar -->
        <nav id="admin-nav" style="width:220px;background:var(--pb-color-surface);padding:1rem;display:flex;flex-direction:column;gap:0.5rem;overflow-y:auto;flex-shrink:0;">
            <h2 style="font-size:1.25rem;margin-bottom:1rem;">Photobox Admin</h2>
            <button class="nav-item" data-page="dashboard">${i18n.t('admin.dashboard')}</button>
            <button class="nav-item" data-page="cameras">Kameras</button>
            <button class="nav-item" data-page="modules">${i18n.t('admin.modules')}</button>
            <button class="nav-item" data-page="events">${i18n.t('admin.events')}</button>
            <button class="nav-item" data-page="settings">${i18n.t('admin.settings')}</button>
            <div style="flex:1;"></div>
            <a href="#/booth" class="nav-item" style="color:var(--pb-color-text-muted);">&larr; Booth</a>
            <button id="btn-logout" class="nav-item" style="background:none;border:none;color:var(--pb-color-error);cursor:pointer;text-align:left;padding:0.75rem 1rem;">
                ${i18n.t('auth.logout')}
            </button>
        </nav>

        <!-- Content -->
        <main id="admin-content" style="flex:1;padding:2rem;overflow-y:auto;"></main>
    </div>

    <style>
        .nav-item {
            display:block;padding:0.75rem 1rem;border-radius:8px;width:100%;text-align:left;
            color:var(--pb-color-text);text-decoration:none;font-size:0.95rem;cursor:pointer;
            background:none;border:none;font-family:inherit;
        }
        .nav-item:hover { background:rgba(255,255,255,0.1); }
        .nav-item.active { background:var(--pb-color-primary);color:white; }
        .admin-card {
            background: var(--pb-color-surface);
            border-radius: var(--pb-radius);
            padding: 1.25rem;
        }
        .admin-card h3 { margin-bottom: 0.75rem; font-size: 1rem; color: var(--pb-color-primary); }
        .admin-card p { font-size: 0.9rem; margin-bottom: 0.25rem; color: var(--pb-color-text-muted); }
        .admin-btn {
            padding:0.6rem 1.2rem;border-radius:8px;border:none;
            font-size:0.9rem;cursor:pointer;color:white;
        }
        .admin-btn-primary { background:var(--pb-color-primary); }
        .admin-btn-outline { background:transparent;border:1px solid #555;color:var(--pb-color-text); }
        .admin-btn:disabled { opacity:0.5;cursor:not-allowed; }
        .admin-input {
            padding:0.6rem;border-radius:6px;border:1px solid #333;
            background:#0e1a30;color:white;font-size:0.9rem;width:100%;
        }
    </style>`;

    container.querySelector('#btn-logout').addEventListener('click', () => {
        state.clearAuth();
        window.pb.router.navigate('booth');
    });

    // Nav click handlers — use event delegation on the nav element
    const nav = container.querySelector('#admin-nav');
    nav.addEventListener('click', (e) => {
        const item = e.target.closest('.nav-item[data-page]');
        if (!item) return;
        e.preventDefault();
        currentPage = item.dataset.page;
        updateNav();
        loadPage();
    });

    updateNav();
    loadPage();

    function updateNav() {
        nav.querySelectorAll('.nav-item[data-page]').forEach(item => {
            item.classList.toggle('active', item.dataset.page === currentPage);
        });
    }

    function loadPage() {
        const content = document.getElementById('admin-content');
        if (!content) return;
        const token = state.auth.token;
        const headers = { 'Authorization': `Bearer ${token}` };

        // Clear content first to show loading state
        content.innerHTML = '<p style="color:var(--pb-color-text-muted);">Laden...</p>';

        switch (currentPage) {
            case 'dashboard': renderDashboard(content, headers); break;
            case 'cameras': renderCameras(content, headers); break;
            case 'modules': renderModules(content, headers); break;
            case 'events': renderEvents(content, headers); break;
            case 'settings': renderSettings(content, headers); break;
            default: renderDashboard(content, headers);
        }
    }
}

async function renderDashboard(el, headers) {
    try {
        const [health, modules, info] = await Promise.all([
            fetch('/api/v1/system/health').then(r => r.json()),
            fetch('/api/v1/modules', { headers }).then(r => r.json()),
            fetch('/api/v1/system/info', { headers }).then(r => r.json()),
        ]);

        el.innerHTML = `
        <h1 style="margin-bottom:1.5rem;">Dashboard</h1>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;">
            <div class="admin-card">
                <h3>System</h3>
                <p>Uptime: ${Math.round(info.uptime_seconds / 60)} min</p>
                <p>Disk: ${info.disk_free_mb} MB frei</p>
                <p>Fotos: ${info.photos_count}</p>
                <p>WS: ${info.ws_connections} Verbindungen</p>
            </div>
            <div class="admin-card">
                <h3>Kameras</h3>
                ${(modules.cameras || []).map(c => `<p>${c.name}: ${c.available ? '&#10003; aktiv' : '&#10007;'}</p>`).join('') || '<p>Keine</p>'}
            </div>
            <div class="admin-card">
                <h3>Ausgabe</h3>
                ${(modules.outputs || []).map(o => `<p>${o.name}: &#10003;</p>`).join('') || '<p>Keine</p>'}
            </div>
            <div class="admin-card">
                <h3>Ausl&ouml;ser</h3>
                ${(modules.triggers || []).map(t => `<p>${t.name}: &#10003;</p>`).join('') || '<p>Keine</p>'}
            </div>
        </div>`;
    } catch (err) {
        el.innerHTML = `<p style="color:var(--pb-color-error);">Fehler: ${err.message}</p>`;
    }
}

async function renderCameras(el, headers) {
    el.innerHTML = `<h1 style="margin-bottom:1.5rem;">Kamera-Einstellungen</h1><p>Wird geladen...</p>`;

    try {
        const [camStatus, settings] = await Promise.all([
            fetch('/api/v1/camera/status').then(r => r.json()),
            fetch('/api/v1/settings', { headers }).then(r => r.json()),
        ]);

        const cameras = [
            { id: 'webrtc', label: 'Browser Webcam (WebRTC)', desc: 'Nutzt getUserMedia im Browser' },
            { id: 'opencv', label: 'USB Webcam (OpenCV)', desc: 'Direkte USB-Kamera, Device-Index wählbar' },
            { id: 'gphoto2', label: 'DSLR (gPhoto2 / Linux)', desc: 'Spiegelreflexkamera über USB' },
            { id: 'digicamcontrol', label: 'DSLR (digiCamControl / Windows)', desc: 'Über digiCamControl HTTP API' },
        ];

        const activeCam = camStatus.active || '';
        const currentType = activeCam.replace('camera.', '');
        const deviceIndex = settings?.cameras?.opencv?.device_index ?? 0;

        el.innerHTML = `
        <h1 style="margin-bottom:1.5rem;">Kamera-Einstellungen</h1>

        <div style="display:flex;flex-direction:column;gap:1rem;max-width:600px;">
            <div class="admin-card">
                <h3>Aktive Kamera</h3>
                <p style="font-size:1.1rem;color:white;margin-bottom:1rem;">
                    ${activeCam || 'Keine'} (${camStatus.mode})
                </p>

                <h3 style="margin-top:1rem;">Kamera wählen</h3>
                ${cameras.map(c => `
                    <label style="display:flex;align-items:center;gap:0.75rem;padding:0.75rem;border-radius:8px;cursor:pointer;margin-bottom:0.5rem;
                        border:1px solid ${currentType === c.id ? 'var(--pb-color-primary)' : '#333'};
                        background:${currentType === c.id ? 'rgba(74,144,217,0.1)' : 'transparent'};">
                        <input type="radio" name="camera" value="${c.id}" ${currentType === c.id ? 'checked' : ''}>
                        <div>
                            <strong>${c.label}</strong><br>
                            <small style="color:var(--pb-color-text-muted);">${c.desc}</small>
                        </div>
                    </label>
                `).join('')}
            </div>

            <div class="admin-card" id="opencv-settings" style="${currentType === 'opencv' ? '' : 'display:none'}">
                <h3>OpenCV Einstellungen</h3>
                <label style="display:block;margin-bottom:0.5rem;">
                    Device Index (0, 1, 2, ...):
                    <input type="number" id="device-index" class="admin-input" value="${deviceIndex}" min="0" max="10" style="width:80px;margin-left:0.5rem;">
                </label>
                <p style="font-size:0.8rem;color:var(--pb-color-text-muted);">
                    0 = erste Kamera, 1 = zweite, usw. Probiere verschiedene Werte wenn die falsche Kamera gewählt wird.
                </p>
            </div>

            <div class="admin-card" id="preview-card">
                <h3>Vorschau</h3>
                <div id="cam-preview" style="width:100%;max-width:480px;aspect-ratio:4/3;background:#000;border-radius:8px;overflow:hidden;">
                    ${camStatus.mode === 'server'
                        ? '<img src="/api/v1/camera/stream" style="width:100%;height:100%;object-fit:cover;" alt="Preview">'
                        : '<p style="color:#666;text-align:center;padding:2rem;">WebRTC — Vorschau nur im Booth-Modus</p>'
                    }
                </div>
            </div>

            <button id="btn-save-camera" class="admin-btn admin-btn-primary" style="align-self:flex-start;">
                Kamera speichern &amp; aktivieren
            </button>
            <p id="camera-msg" style="display:none;font-size:0.9rem;"></p>
        </div>`;

        // Show/hide opencv settings based on selection
        el.querySelectorAll('input[name="camera"]').forEach(radio => {
            radio.addEventListener('change', () => {
                document.getElementById('opencv-settings').style.display =
                    radio.value === 'opencv' ? '' : 'none';
            });
        });

        // Save button
        el.querySelector('#btn-save-camera').addEventListener('click', async () => {
            const selected = el.querySelector('input[name="camera"]:checked')?.value;
            if (!selected) return;

            const msg = el.querySelector('#camera-msg');
            msg.style.display = 'block';
            msg.style.color = 'var(--pb-color-text-muted)';
            msg.textContent = 'Speichere...';

            try {
                // Build camera config
                const allCams = ['gphoto2', 'digicamcontrol', 'webrtc', 'opencv'];
                const camerasConfig = {};
                for (const cam of allCams) {
                    camerasConfig[cam] = { enabled: cam === selected };
                }
                if (selected === 'opencv') {
                    const idx = parseInt(el.querySelector('#device-index').value) || 0;
                    camerasConfig.opencv.device_index = idx;
                }

                // Save via settings API
                await fetch('/api/v1/settings/cameras', {
                    method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'cameras', value: camerasConfig }),
                });

                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = 'Gespeichert! Server muss neu gestartet werden damit die Kamera wechselt.';
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
            }
        });

    } catch (err) {
        el.innerHTML = `<p style="color:var(--pb-color-error);">Fehler: ${err.message}</p>`;
    }
}

async function renderModules(el, headers) {
    try {
        const modules = await fetch('/api/v1/modules', { headers }).then(r => r.json());
        const sections = [
            { title: 'Kameras', items: modules.cameras || [] },
            { title: 'Auslöser', items: modules.triggers || [] },
            { title: 'Ausgabe', items: modules.outputs || [] },
            { title: 'Bezahlung', items: modules.payments || [] },
        ];

        el.innerHTML = `
        <h1 style="margin-bottom:1.5rem;">Module</h1>
        <div style="display:flex;flex-direction:column;gap:1rem;max-width:600px;">
            ${sections.map(s => `
                <div class="admin-card">
                    <h3>${s.title}</h3>
                    ${s.items.length ? s.items.map(m => `
                        <p>
                            <span style="color:${m.available !== false ? 'var(--pb-color-success)' : 'var(--pb-color-error)'}">
                                ${m.available !== false ? '&#10003;' : '&#10007;'}
                            </span>
                            ${m.name} ${m.active ? '(aktiv)' : ''}
                        </p>
                    `).join('') : '<p>Keine geladen</p>'}
                </div>
            `).join('')}
        </div>`;
    } catch (err) {
        el.innerHTML = `<p style="color:var(--pb-color-error);">Fehler: ${err.message}</p>`;
    }
}

async function renderEvents(el, headers) {
    try {
        const events = await fetch('/api/v1/events/', { headers }).then(r => r.json());

        el.innerHTML = `
        <h1 style="margin-bottom:1.5rem;">Veranstaltungen</h1>
        <div style="display:flex;flex-direction:column;gap:0.75rem;max-width:600px;">
            ${events.map(e => `
                <div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <strong>${e.name}</strong>
                        <small style="color:var(--pb-color-text-muted);margin-left:0.5rem;">(${e.slug})</small>
                        ${e.is_active ? '<span style="color:var(--pb-color-success);margin-left:0.5rem;">&#9679; aktiv</span>' : ''}
                    </div>
                    ${!e.is_active ? `<button class="admin-btn admin-btn-outline btn-activate" data-slug="${e.slug}">Aktivieren</button>` : ''}
                </div>
            `).join('')}
        </div>`;

        el.querySelectorAll('.btn-activate').forEach(btn => {
            btn.addEventListener('click', async () => {
                await fetch(`/api/v1/events/${btn.dataset.slug}/activate`, {
                    method: 'POST', headers,
                });
                renderEvents(el, headers);
            });
        });
    } catch (err) {
        el.innerHTML = `<p style="color:var(--pb-color-error);">Fehler: ${err.message}</p>`;
    }
}

async function renderSettings(el, headers) {
    try {
        const settings = await fetch('/api/v1/settings', { headers }).then(r => r.json());

        el.innerHTML = `
        <h1 style="margin-bottom:1.5rem;">Einstellungen</h1>
        <div style="max-width:600px;">
            <div class="admin-card">
                <h3>Konfiguration (JSON)</h3>
                <pre style="background:#0a0e1a;padding:1rem;border-radius:8px;overflow:auto;max-height:60vh;font-size:0.8rem;color:var(--pb-color-text-muted);">${JSON.stringify(settings, null, 2)}</pre>
            </div>
        </div>`;
    } catch (err) {
        el.innerHTML = `<p style="color:var(--pb-color-error);">Fehler: ${err.message}</p>`;
    }
}
