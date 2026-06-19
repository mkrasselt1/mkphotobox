/**
 * Setup Wizard — First-time setup flow.
 */

export function render(container, state) {
    const { i18n } = window.pb;
    let step = 0;

    const formData = {
        language: 'de',
        admin_password: '',
        camera: 'webrtc',
        event_name: '',
        event_slug: '',
    };

    function renderStep() {
        const steps = [renderLanguageStep, renderAdminStep, renderCameraStep, renderEventStep];
        container.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;padding:2rem;">
            <div style="background:var(--pb-color-surface);border-radius:var(--pb-radius);padding:2rem;width:100%;max-width:500px;">
                <h1 style="margin-bottom:0.5rem;">${i18n.t('setup.welcome')}</h1>
                <p style="color:var(--pb-color-text-muted);margin-bottom:1.5rem;">Schritt ${step + 1} von ${steps.length}</p>
                <div id="step-content"></div>
                <div style="display:flex;justify-content:space-between;margin-top:1.5rem;">
                    ${step > 0 ? `<button id="btn-back" class="btn-secondary">${i18n.t('setup.back')}</button>` : '<div></div>'}
                    <button id="btn-next" class="btn-primary">
                        ${step === steps.length - 1 ? i18n.t('setup.finish') : i18n.t('setup.next')}
                    </button>
                </div>
            </div>
        </div>
        <style>
            .btn-primary { padding:12px 24px;border-radius:8px;border:none;background:var(--pb-color-primary);color:white;font-size:1rem;cursor:pointer; }
            .btn-secondary { padding:12px 24px;border-radius:8px;border:1px solid #555;background:transparent;color:white;font-size:1rem;cursor:pointer; }
            .setup-input { width:100%;padding:12px;border-radius:8px;border:1px solid #333;background:#0e1a30;color:white;font-size:1rem;margin-top:0.5rem; }
            .setup-label { display:block;margin-bottom:1rem;color:var(--pb-color-text-muted); }
            .setup-option { display:block;padding:10px 14px;border:1px solid #333;border-radius:8px;margin-bottom:0.5rem;cursor:pointer;color:white; }
            .setup-option.selected { border-color:var(--pb-color-primary);background:rgba(74,144,217,0.15); }
        </style>`;

        steps[step](document.getElementById('step-content'));

        document.getElementById('btn-back')?.addEventListener('click', () => { step--; renderStep(); });
        document.getElementById('btn-next')?.addEventListener('click', async () => {
            if (step === steps.length - 1) {
                await completeSetup();
            } else {
                step++;
                renderStep();
            }
        });
    }

    function renderLanguageStep(el) {
        el.innerHTML = `
            <h3>${i18n.t('setup.step_language')}</h3>
            <div style="margin-top:1rem;">
                <label class="setup-option ${formData.language === 'de' ? 'selected' : ''}" data-lang="de">
                    <input type="radio" name="lang" value="de" ${formData.language === 'de' ? 'checked' : ''} style="display:none;">
                    Deutsch
                </label>
                <label class="setup-option ${formData.language === 'en' ? 'selected' : ''}" data-lang="en">
                    <input type="radio" name="lang" value="en" ${formData.language === 'en' ? 'checked' : ''} style="display:none;">
                    English
                </label>
            </div>`;
        el.querySelectorAll('.setup-option').forEach(opt => {
            opt.addEventListener('click', () => {
                formData.language = opt.dataset.lang;
                el.querySelectorAll('.setup-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');
            });
        });
    }

    function renderAdminStep(el) {
        el.innerHTML = `
            <h3>${i18n.t('setup.step_admin')}</h3>
            <label class="setup-label">
                Passwort
                <input type="password" id="admin-pw" class="setup-input" value="${formData.admin_password}" placeholder="Admin-Passwort">
            </label>`;
        el.querySelector('#admin-pw').addEventListener('input', (e) => {
            formData.admin_password = e.target.value;
        });
    }

    function renderCameraStep(el) {
        const cameras = [
            { id: 'webrtc', label: 'Browser Webcam (WebRTC)', desc: 'Nutzt die im Browser verfügbare Kamera' },
            { id: 'opencv', label: 'USB Webcam (OpenCV)', desc: 'Direkte USB-Kamera über OpenCV' },
            { id: 'gphoto2', label: 'DSLR (gPhoto2 / Linux)', desc: 'Spiegelreflexkamera über USB' },
            { id: 'digicamcontrol', label: 'DSLR (digiCamControl / Windows)', desc: 'Spiegelreflexkamera über digiCamControl' },
        ];
        el.innerHTML = `
            <h3>${i18n.t('setup.step_camera')}</h3>
            <div style="margin-top:1rem;">
                ${cameras.map(c => `
                    <label class="setup-option ${formData.camera === c.id ? 'selected' : ''}" data-cam="${c.id}">
                        <input type="radio" name="camera" value="${c.id}" ${formData.camera === c.id ? 'checked' : ''} style="display:none;">
                        <strong>${c.label}</strong><br><small style="color:var(--pb-color-text-muted);">${c.desc}</small>
                    </label>
                `).join('')}
            </div>`;
        el.querySelectorAll('.setup-option').forEach(opt => {
            opt.addEventListener('click', () => {
                formData.camera = opt.dataset.cam;
                el.querySelectorAll('.setup-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');
            });
        });
    }

    function renderEventStep(el) {
        el.innerHTML = `
            <h3>${i18n.t('setup.step_event')}</h3>
            <label class="setup-label">
                Name
                <input type="text" id="event-name" class="setup-input" value="${formData.event_name}" placeholder="z.B. Hochzeit Müller">
            </label>
            <label class="setup-label">
                URL-Slug
                <input type="text" id="event-slug" class="setup-input" value="${formData.event_slug}" placeholder="z.B. hochzeit-mueller">
            </label>`;
        el.querySelector('#event-name').addEventListener('input', (e) => {
            formData.event_name = e.target.value;
            if (!formData.event_slug) {
                el.querySelector('#event-slug').value = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-');
            }
        });
        el.querySelector('#event-slug').addEventListener('input', (e) => {
            formData.event_slug = e.target.value;
        });
    }

    async function completeSetup() {
        try {
            const res = await fetch('/api/v1/setup/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData),
            });
            if (!res.ok) throw new Error('Setup failed');
            window.pb.router.navigate('booth');
        } catch (err) {
            alert('Setup error: ' + err.message);
        }
    }

    renderStep();
}
