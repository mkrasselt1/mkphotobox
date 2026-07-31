/**
 * Booth Flow — The main photo booth user experience.
 * FSM: idle → countdown → capture → processing → review → share → thanks → idle
 *
 * Camera preview supports two modes:
 *   1. WebRTC (browser camera) — <video> with getUserMedia()
 *   2. MJPEG (server-side camera) — <img src="/api/v1/camera/stream">
 */

const STATES = {
    idle:         { timeout: null,   timeoutTarget: null },
    template_select: { timeout: 60000, timeoutTarget: 'idle' },
    payment:      { timeout: 120000, timeoutTarget: 'idle' },
    countdown:    { timeout: null,   timeoutTarget: null },
    capture:      { timeout: 10000,  timeoutTarget: 'idle' },
    processing:   { timeout: 15000,  timeoutTarget: 'idle' },
    review:       { timeout: 60000,  timeoutTarget: 'thanks' },
    share:        { timeout: 120000, timeoutTarget: 'thanks' },
    thanks:       { timeout: 5000,   timeoutTarget: 'idle' },
};

let currentState = 'idle';
let countdownTimer = null;
let captureLeadTimer = null;  // fires the capture a configurable lead before "0"
let stateTimer = null;
let lastPhoto = null;
let pendingPayment = null;
let cameraMode = 'webrtc'; // 'webrtc' | 'server'
let webrtcStream = null;    // keep stream alive across state transitions
let capturedBlob = null;    // JPEG blob captured from video before DOM changes
let captureInFlight = false; // true while a shot's capture/collage render is running
let captureDeadline = 0;     // hard cap (ms epoch) so a truly stuck capture still recovers
let previewSize = 'medium'; // 'small' | 'medium' | 'large' | 'fullscreen'
let countdownSeconds = 3;   // configurable countdown duration
let captureLeadMs = 0;      // ms before "0" at which the capture is triggered
let idleLivePreview = true; // show the live stream on the welcome screen (vs. a static page)
let galleryEnabled = true;
let helpButton = false;      // show the "Hilfe" button (Telegram help active)
// Mirror the browser camera's live image so guests see themselves as in a mirror.
// Server cameras already mirror in the frame itself; only the local <video> needs
// CSS. Whatever we do here is undone again when grabbing the frame, so the saved
// photo stays correct either way. See app/services/image_transform.py.
let mirrorPreview = true;
let flashEnabled = true;     // white flash on the capture screen
// Looks the guests can pick. The CSS goes on the live preview so they see the
// look while posing; the server bakes the matching version into the photo.
let photoFilters = [];       // [{id, label, css}] — empty = feature off
let selectedFilter = 'none';
let guestbookEnabled = true; // let guests draw / write on their photo
let guestbookMaxLen = 120;
let availableOutputs = [];  // loaded output module names (only enabled+available ones)
let templates = [];          // booth templates for the active event
let seq = null;              // active multi-photo sequence: {template, total, shots:[], index}
let lastTemplate = null;     // template of the last capture — so "Nochmal" repeats a set, not a single
let boothInitiated = false;  // true while the booth drives its own capture sequence
let shareBase = '';          // LAN base URL for QR codes (phone-reachable, not localhost)
let remoteGallery = null;    // {active, gallery_url, image_base} when off-box gallery is live
let cropAspect = null;       // {w,h} default output aspect to outline on the live preview
let outputAspect = null;     // {w,h} of the print paper — single-photo framing target

const PREVIEW_MAX_WIDTHS = {
    small: '320px',
    medium: '640px',
    large: '960px',
    fullscreen: '100%',
};

export function render(container, state) {
    const { i18n, ws } = window.pb;

    // Listen for capture events from WS (external/hardware triggers only —
    // the booth handles its own sequence transitions in capturePhoto()).
    ws.on('capture.completed', (data) => {
        if (boothInitiated) return;
        lastPhoto = data;
        transition('review');
    });
    ws.on('capture.error', () => {
        transition('idle');
    });
    ws.on('camera.switched', (data) => {
        // Camera was changed in admin panel — update mode and restart preview
        cameraMode = data.mode || 'webrtc';
        if (currentState === 'idle') transition('idle');
    });

    // Payment events
    ws.on('payment.required', (data) => {
        pendingPayment = data;
        transition('payment');
    });
    ws.on('payment.progress', (data) => {
        if (currentState === 'payment') updatePaymentProgress(data);
    });
    ws.on('payment.completed', (data) => {
        if (currentState === 'payment') {
            // Brief "paid" confirmation, then proceed
            showPaymentDone(data);
            setTimeout(() => transition('countdown'), 1200);
        }
    });

    container.innerHTML = `<div id="booth" style="width:100%;height:100%;position:relative;overflow:hidden;"></div>`;

    // Keep crop guides correctly sized when the viewport changes
    window.addEventListener('resize', sizeCropGuides);

    // Detect camera mode and preview size from server
    detectSettings().then(() => transition('idle'));

    async function detectSettings() {
        try {
            const [camRes, displayRes] = await Promise.all([
                fetch('/api/v1/camera/status'),
                fetch('/api/v1/display/config'),
            ]);
            const camData = await camRes.json();
            cameraMode = camData.mode || 'webrtc';
            if (displayRes.ok) {
                const displayData = await displayRes.json();
                const val = displayData.preview_size;
                if (val && PREVIEW_MAX_WIDTHS[val]) previewSize = val;
                if (Number.isFinite(displayData.countdown_seconds) && displayData.countdown_seconds > 0)
                    countdownSeconds = Math.round(displayData.countdown_seconds);
                if (Number.isFinite(displayData.capture_lead_ms) && displayData.capture_lead_ms >= 0)
                    captureLeadMs = displayData.capture_lead_ms;
                idleLivePreview = displayData.idle_live_preview !== false;
                galleryEnabled = displayData.gallery_enabled !== false;
                helpButton = displayData.help_button === true;
                mirrorPreview = displayData.mirror_preview !== false;
                guestbookEnabled = displayData.guestbook_enabled !== false;
                if (Number.isFinite(displayData.guestbook_max_len) && displayData.guestbook_max_len > 0)
                    guestbookMaxLen = displayData.guestbook_max_len;
                if (displayData.output_aspect?.w && displayData.output_aspect?.h)
                    outputAspect = displayData.output_aspect;
            }
        } catch {
            cameraMode = 'webrtc';
        }
        try {
            templates = await fetch('/api/v1/templates/booth').then(r => r.json()).then(r => r.templates || []);
        } catch {
            templates = [];
        }
        try {
            const f = await fetch('/api/v1/photos/filters').then(r => r.json());
            // A single entry is only "Original" — not worth a chooser.
            photoFilters = f.enabled && (f.filters || []).length > 1 ? f.filters : [];
        } catch {
            photoFilters = [];
        }
        // Default crop aspect for idle / single-photo framing = the actual print
        // output (e.g. 10x15 = 3:2) so a single photo shows no false crop. Fall
        // back to the first template's canvas only when no print size is known.
        const t0 = templates[0];
        if (outputAspect) {
            cropAspect = outputAspect;
        } else if (t0 && t0.canvas_width && t0.canvas_height) {
            cropAspect = { w: t0.canvas_width, h: t0.canvas_height };
        }
        try {
            const sb = await fetch('/api/v1/system/share-base').then(r => r.json());
            shareBase = sb.base_url || '';
            remoteGallery = sb.remote_gallery || null;
        } catch {
            shareBase = location.origin;
            remoteGallery = null;
        }
        try {
            const outs = await fetch('/api/v1/outputs/available').then(r => r.json());
            availableOutputs = (outs || []).map(o => o.name);
        } catch { availableOutputs = []; }
    }

    function transition(newState) {
        currentState = newState;
        state.setBoothState(newState);
        if (stateTimer) clearTimeout(stateTimer);
        if (countdownTimer) clearInterval(countdownTimer);
        if (captureLeadTimer) { clearTimeout(captureLeadTimer); captureLeadTimer = null; }
        document.getElementById('pb-overlay')?.remove(); // clear any open modal

        const stateConfig = STATES[newState];
        if (stateConfig?.timeout) {
            const target = stateConfig.timeoutTarget || 'idle';
            // Safety net to recover a stuck booth — but NEVER abort a capture/collage
            // that is legitimately still running. Firing here would send us to 'idle',
            // which wipes `seq` and stops a multi-photo series after the first shot.
            // So while a capture is in flight, defer (re-arm) up to a hard deadline.
            const armStateTimer = () => {
                stateTimer = setTimeout(() => {
                    if (captureInFlight && Date.now() < captureDeadline) { armStateTimer(); return; }
                    transition(target);
                }, stateConfig.timeout);
            };
            armStateTimer();
        }

        const booth = document.getElementById('booth');
        if (!booth) return;

        switch (newState) {
            case 'idle':       renderIdle(booth); break;
            case 'template_select': renderTemplateSelect(booth); break;
            case 'payment':    renderPayment(booth); break;
            case 'countdown':  renderCountdown(booth); break;
            case 'capture':    renderCapture(booth); break;
            case 'processing': renderProcessing(booth); break;
            case 'review':     renderReview(booth); break;
            case 'share':      renderShare(booth); break;
            case 'thanks':     renderThanks(booth); break;
        }
    }

    // ── Fullscreen overlay modals (share screen) ─────────────────────
    function closeOverlay() {
        document.getElementById('pb-overlay')?.remove();
    }
    function openOverlay(innerHTML) {
        closeOverlay();
        const o = document.createElement('div');
        o.id = 'pb-overlay';
        o.style.cssText = 'position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.78);' +
            'backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:18px;padding:2rem;max-width:92vw;max-height:92vh;overflow:auto;display:flex;flex-direction:column;align-items:center;gap:1.2rem;box-shadow:0 24px 70px rgba(0,0,0,0.6);">${innerHTML}</div>`;
        o.addEventListener('click', (e) => { if (e.target === o || e.target.hasAttribute('data-close')) closeOverlay(); });
        document.body.appendChild(o);
        return o;
    }

    // ── Camera Preview HTML ──────────────────────────────────────────

    function previewContainerStyle() {
        const isFS = previewSize === 'fullscreen';
        const maxW = PREVIEW_MAX_WIDTHS[previewSize] || '640px';
        if (isFS) {
            return `width:100%;height:100%;background:#000;overflow:hidden;display:flex;align-items:center;justify-content:center;position:relative;`;
        }
        // Box takes the real output/placeholder aspect so the live preview (cover)
        // shows exactly what ends up on the print/slot — WYSIWYG, no false crop.
        const a = currentCropAspect();
        const ar = (a && a.w && a.h) ? `${a.w}/${a.h}` : '4/3';
        return `width:100%;max-width:${maxW};aspect-ratio:${ar};background:#000;border-radius:var(--pb-radius);overflow:hidden;display:flex;align-items:center;justify-content:center;position:relative;`;
    }

    // ── Looks (colour filters) ───────────────────────────────────────

    /** The CSS of the currently chosen look, '' for the untouched image. */
    function currentLookCss() {
        return (photoFilters.find(f => f.id === selectedFilter) || {}).css || '';
    }

    /** Put the chosen look on whatever preview element is on screen right now.
     *  Works for both camera modes — the MJPEG <img> takes a CSS filter just as
     *  well as the WebRTC <video>. */
    function applyLookToPreview() {
        const css = currentLookCss();
        document.querySelectorAll('#preview-img, #preview-video').forEach(elm => {
            elm.style.filter = css;
        });
    }

    /** Touch-friendly row of look buttons. Empty string when looks are off. */
    function filterBarHTML(onDark = false) {
        if (!photoFilters.length) return '';
        const fg = onDark ? 'rgba(255,255,255,0.9)' : 'var(--pb-color-text)';
        const bg = onDark ? 'rgba(0,0,0,0.35)' : 'var(--pb-color-surface)';
        return `
        <div id="filter-bar" style="display:flex;gap:0.5rem;flex-wrap:wrap;justify-content:center;
             padding:0.5rem;border-radius:var(--pb-radius);background:${bg};
             ${onDark ? 'backdrop-filter:blur(8px);' : ''}pointer-events:auto;max-width:100%;">
            ${photoFilters.map(f => `
                <button class="look-btn" data-look="${f.id}" style="
                    padding:0.55rem 0.95rem;border-radius:calc(var(--pb-radius) - 4px);
                    border:2px solid ${f.id === selectedFilter ? 'var(--pb-color-primary)' : 'transparent'};
                    background:${f.id === selectedFilter ? 'var(--pb-color-primary)' : 'rgba(127,127,127,0.18)'};
                    color:${f.id === selectedFilter ? '#fff' : fg};
                    font-size:0.95rem;cursor:pointer;min-height:2.75rem;white-space:nowrap;
                ">${f.label}</button>`).join('')}
        </div>`;
    }

    function wireFilterBar(el) {
        const bar = el.querySelector('#filter-bar');
        if (!bar) return;
        bar.querySelectorAll('.look-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                selectedFilter = btn.dataset.look;
                sounds.unlock();  // a tap here also counts as the audio gesture
                bar.querySelectorAll('.look-btn').forEach(b => {
                    const on = b.dataset.look === selectedFilter;
                    b.style.borderColor = on ? 'var(--pb-color-primary)' : 'transparent';
                    b.style.background = on ? 'var(--pb-color-primary)' : 'rgba(127,127,127,0.18)';
                    if (on) b.style.color = '#fff';
                    else b.style.removeProperty('color');
                });
                applyLookToPreview();
            });
        });
        applyLookToPreview();
    }

    function cameraPreviewHTML(id = 'camera-preview') {
        const style = previewContainerStyle();
        if (cameraMode === 'server') {
            return `
            <div id="${id}" style="${style}">
                <img id="preview-img" src="/api/v1/camera/stream" style="width:100%;height:100%;object-fit:cover;" alt="Live Preview">
                ${cropGuideHTML()}
            </div>`;
        }
        return `
        <div id="${id}" style="${style}">
            <video id="preview-video" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover;${mirrorPreview ? 'transform:scaleX(-1);' : ''}"></video>
            ${cropGuideHTML()}
        </div>`;
    }

    // ── Crop guide: outline the eventual output aspect on the live preview ───
    function currentCropAspect() {
        // In a set, frame each shot to the placeholder it fills (slot i ↔ shot i),
        // so a square/strip/circle slot each gets its own crop — not the whole
        // canvas. Fall back to the template canvas, then the single-photo aspect.
        if (seq && seq.template) {
            const slots = seq.template.slots || [];
            // the first slot filled by the CURRENT shot (photo_index defaults to
            // the slot position; several slots may reuse the same shot)
            const slot = slots.find((s, i) => (s.photo_index ?? i) === seq.index);
            if (slot && slot.w && slot.h) return { w: slot.w, h: slot.h };
            if (seq.template.canvas_width && seq.template.canvas_height)
                return { w: seq.template.canvas_width, h: seq.template.canvas_height };
        }
        return cropAspect;
    }

    function cropGuideHTML() {
        const a = currentCropAspect();
        if (!a || !a.w || !a.h) return '';
        return `
        <div class="crop-guide" data-aw="${a.w}" data-ah="${a.h}" style="
            position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);opacity:0;
            box-shadow:0 0 0 9999px rgba(0,0,0,0.42);
            border:2px solid rgba(255,255,255,0.92);border-radius:6px;
            pointer-events:none;z-index:3;box-sizing:border-box;transition:opacity 0.2s;">
            <span style="position:absolute;top:6px;left:50%;transform:translateX(-50%);
                font-size:0.7rem;color:#fff;background:rgba(0,0,0,0.45);
                padding:1px 9px;border-radius:8px;white-space:nowrap;letter-spacing:0.3px;">Bildausschnitt</span>
        </div>`;
    }

    // Size every crop guide to the largest centred rect of its target aspect that
    // fits its preview container (run after layout; re-run on resize).
    function sizeCropGuides() {
        document.querySelectorAll('#booth .crop-guide').forEach(g => {
            const c = g.parentElement;
            if (!c) return;
            const cw = c.clientWidth, ch = c.clientHeight;
            const aw = parseFloat(g.dataset.aw), ah = parseFloat(g.dataset.ah);
            if (!cw || !ch || !aw || !ah) return;
            const target = aw / ah;
            let w, h;
            if (cw / ch > target) { h = ch; w = ch * target; }
            else { w = cw; h = cw / target; }
            g.style.width = Math.round(w) + 'px';
            g.style.height = Math.round(h) + 'px';
            g.style.opacity = '1';
        });
    }

    function scheduleCropSizing() {
        requestAnimationFrame(sizeCropGuides);
        setTimeout(sizeCropGuides, 120);  // after MJPEG/video lays out
    }

    async function activatePreview() {
        if (cameraMode === 'server') {
            // MJPEG stream is handled by the <img> tag automatically
            return;
        }
        const video = document.getElementById('preview-video');
        if (!video) return;
        try {
            if (webrtcStream) {
                video.srcObject = webrtcStream;
            } else {
                webrtcStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
                    audio: false,
                });
                video.srcObject = webrtcStream;
            }
        } catch (err) {
            console.warn('Camera preview unavailable:', err);
            const parent = video.parentElement;
            if (parent) {
                parent.innerHTML = `<p style="color:var(--pb-color-text-muted);padding:2rem;text-align:center;">
                    Kamera nicht verfügbar<br><small>${err.message}</small>
                </p>`;
            }
        }
    }

    // ── States ───────────────────────────────────────────────────────

    function beginFlow() {
        // If multi-photo templates are configured, let the guest pick one first.
        if (templates && templates.length) {
            transition('template_select');
        } else {
            startCapture(null);
        }
    }

    function startCapture(template) {
        boothInitiated = true;
        lastTemplate = template;   // remember for "Nochmal" (repeat the same set/single)
        if (template && template.photo_count > 1) {
            seq = { template, total: template.photo_count, shots: [], index: 0 };
        } else {
            seq = template ? { template, total: 1, shots: [], index: 0 } : null;
        }
        transition('countdown');
    }

    function renderTemplateSelect(el) {
        el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1.5rem;padding:2rem;overflow-y:auto;">
            <h1 style="font-size:clamp(1.5rem,5vw,2.5rem);text-align:center;">${i18n.t('booth.choose_layout') || 'Layout wählen'}</h1>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;width:100%;max-width:720px;">
                <button class="tpl-card" data-single="1">
                    <span class="tpl-thumb tpl-thumb-icon">📷</span>
                    <strong>Einzelfoto</strong>
                    <small>1 Foto</small>
                </button>
                ${templates.map((t, i) => `
                    <button class="tpl-card" data-idx="${i}">
                        ${t.preview_url
                            // The rendered layout itself — far more telling than an
                            // icon. Falls back to the icon if the render is missing.
                            ? `<img class="tpl-thumb" src="${t.preview_url}" alt=""
                                 onerror="this.outerHTML='<span class=\\'tpl-thumb tpl-thumb-icon\\'>🖼️</span>'">`
                            : `<span class="tpl-thumb tpl-thumb-icon">${t.photo_count > 1 ? '🖼️' : '📷'}</span>`}
                        <strong>${t.name}</strong>
                        <small>${t.photo_count} Foto${t.photo_count > 1 ? 's' : ''}</small>
                    </button>`).join('')}
            </div>
            <button id="btn-tpl-cancel" class="pb-btn pb-btn-outline">${i18n.t('booth.cancel') || 'Abbrechen'}</button>
        </div>
        <style>
            .tpl-card {
                display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.4rem;
                padding:1.25rem 1rem;border-radius:var(--pb-radius);background:var(--pb-color-surface);
                border:1px solid var(--pb-color-border, #2a3a5e);color:var(--pb-color-text);cursor:pointer;
                min-height:120px;transition:transform 0.1s, background 0.15s;
            }
            .tpl-card:active { transform:scale(0.96); }
            .tpl-card:hover { background:var(--pb-color-surface-2, #232c4a); }
            .tpl-card small { color:var(--pb-color-text-muted); }
            /* Fixed box so portrait strips and landscape layouts line up in one
               row; contain keeps every layout's real proportions visible.
               Scales with the screen — a booth runs anywhere from a 10" tablet
               to a 27" upright display. */
            .tpl-thumb {
                height:clamp(150px, 24vh, 260px);width:100%;object-fit:contain;
                display:flex;align-items:center;justify-content:center;margin-bottom:0.35rem;
            }
            .tpl-thumb-icon { font-size:3rem; }
        </style>
        ${btnStyles()}`;

        el.querySelectorAll('.tpl-card').forEach(card => {
            card.addEventListener('click', () => {
                if (card.dataset.single) return startCapture(null);
                startCapture(templates[parseInt(card.dataset.idx)]);
            });
        });
        el.querySelector('#btn-tpl-cancel')?.addEventListener('click', () => transition('idle'));
    }

    // "Hilfe" button (bottom-right) — sends a Telegram message to the operator.
    // Only shown when Telegram help is active (display.help_button).
    function showHelpButton(el) {
        if (!helpButton) return;
        const btn = document.createElement('button');
        btn.id = 'btn-help';
        btn.innerHTML = '🆘 Hilfe';
        btn.style.cssText = `position:absolute;bottom:14px;right:14px;z-index:6;
            padding:0.6rem 1.1rem;border-radius:12px;border:2px solid rgba(255,255,255,0.35);
            background:rgba(198,60,50,0.85);color:#fff;font-size:1rem;font-weight:700;
            cursor:pointer;backdrop-filter:blur(4px);box-shadow:0 4px 14px rgba(0,0,0,0.4);`;
        let busy = false;
        btn.addEventListener('click', async () => {
            if (busy) return;
            const o = openOverlay(`
                <h2 style="margin:0;">Hilfe rufen?</h2>
                <p style="color:var(--pb-color-text-muted);margin:0;text-align:center;">Das Personal wird per Telegram benachrichtigt.</p>
                <div style="display:flex;gap:0.75rem;">
                    <button class="pb-btn pb-btn-outline" data-close>Abbrechen</button>
                    <button id="help-go" class="pb-btn pb-btn-primary">Hilfe rufen</button>
                </div>
                <p id="help-msg" style="margin:0;font-size:0.95rem;"></p>`);
            o.querySelector('#help-go').addEventListener('click', async () => {
                const msg = o.querySelector('#help-msg');
                busy = true; msg.style.color = 'var(--pb-color-text-muted)'; msg.textContent = 'Sende…';
                try {
                    const r = await fetch('/api/v1/telegram/help', { method: 'POST' }).then(r => r.json());
                    msg.style.color = r.ok ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
                    msg.textContent = r.ok ? '✓ Hilfe ist unterwegs!' : ('✗ ' + (r.message || 'Fehler'));
                    if (r.ok) setTimeout(() => { closeOverlay(); }, 1800);
                } catch { msg.style.color = 'var(--pb-color-error)'; msg.textContent = '✗ Fehler beim Senden'; }
                finally { setTimeout(() => { busy = false; }, 3000); }
            });
        });
        el.appendChild(btn);
    }

    async function showStorage(el) {
        let s;
        try { s = await fetch('/api/v1/system/storage').then(r => r.json()); } catch { return; }
        if (!s || s.photos_remaining == null) return;
        const badge = document.createElement('div');
        badge.style.cssText = `position:absolute;top:12px;left:12px;z-index:5;padding:0.45rem 0.85rem;
            border-radius:10px;font-size:0.85rem;font-weight:600;color:#fff;backdrop-filter:blur(4px);pointer-events:none;
            background:${s.low ? 'rgba(249,105,90,0.92)' : 'rgba(0,0,0,0.45)'};`;
        badge.textContent = s.low
            ? `⚠️ Speicher fast voll — noch ca. ${s.photos_remaining} Fotos`
            : `📸 noch ca. ${s.photos_remaining} Fotos`;
        el.appendChild(badge);
    }

    function renderIdle(el) {
        seq = null;
        lastTemplate = null;
        boothInitiated = false;
        selectedFilter = 'none';   // every new guest starts from the untouched image
        const isFS = previewSize === 'fullscreen';
        if (!idleLivePreview) {
            // Normal welcome page without live view — the camera rests until "Start"
            el.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:2rem;padding:2rem;text-align:center;">
                <div style="font-size:clamp(3rem,12vw,6rem);line-height:1;">📸</div>
                <h1 style="font-size:clamp(2rem,6vw,3.5rem);text-align:center;">${i18n.t('booth.welcome')}</h1>
                ${filterBarHTML()}
                <button id="btn-start" style="
                    padding:1.5rem 3rem;border-radius:var(--pb-radius);border:none;
                    background:var(--pb-color-primary);color:white;font-size:1.5rem;
                    cursor:pointer;min-height:var(--pb-touch-target);
                    transition:transform 0.1s;box-shadow:0 4px 20px rgba(74,144,217,0.4);
                ">${i18n.t('booth.start')}</button>
                <div style="display:flex;gap:1.5rem;color:var(--pb-color-text-muted);font-size:0.85rem;">
                    ${galleryEnabled ? `<a href="#/gallery" style="color:inherit;text-decoration:none;">🖼️ ${i18n.t('gallery.title')}</a>` : ''}
                    <a href="#/admin" style="color:inherit;text-decoration:none;">⚙️ Admin</a>
                </div>
            </div>`;
        } else if (isFS) {
            el.innerHTML = `
            <div style="width:100%;height:100%;position:relative;">
                ${cameraPreviewHTML()}
                <div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;flex-direction:column;align-items:center;justify-content:space-between;padding:2rem;pointer-events:none;z-index:2;">
                    <h1 style="font-size:clamp(2rem,6vw,3.5rem);text-align:center;text-shadow:0 2px 12px rgba(0,0,0,0.7);">${i18n.t('booth.welcome')}</h1>
                    <div style="display:flex;flex-direction:column;align-items:center;gap:1rem;pointer-events:auto;">
                        ${filterBarHTML(true)}
                        <button id="btn-start" style="
                            padding:1.5rem 3rem;border-radius:var(--pb-radius);border:none;
                            background:rgba(74,144,217,0.7);backdrop-filter:blur(8px);color:white;font-size:1.5rem;
                            cursor:pointer;min-height:var(--pb-touch-target);
                            transition:transform 0.1s, background 0.2s;box-shadow:0 4px 20px rgba(0,0,0,0.4);
                        ">${i18n.t('booth.start')}</button>
                        <div style="display:flex;gap:1.5rem;font-size:0.85rem;">
                            ${galleryEnabled ? `<a href="#/gallery" style="color:rgba(255,255,255,0.8);text-decoration:none;text-shadow:0 1px 4px rgba(0,0,0,0.6);">🖼️ ${i18n.t('gallery.title')}</a>` : ''}
                            <a href="#/admin" style="color:rgba(255,255,255,0.8);text-decoration:none;text-shadow:0 1px 4px rgba(0,0,0,0.6);">⚙️ Admin</a>
                        </div>
                    </div>
                </div>
            </div>`;
        } else {
            el.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:2rem;padding:2rem;">
                <h1 style="font-size:clamp(2rem,6vw,3.5rem);text-align:center;">${i18n.t('booth.welcome')}</h1>
                ${cameraPreviewHTML()}
                ${filterBarHTML()}
                <button id="btn-start" style="
                    padding:1.5rem 3rem;border-radius:var(--pb-radius);border:none;
                    background:var(--pb-color-primary);color:white;font-size:1.5rem;
                    cursor:pointer;min-height:var(--pb-touch-target);
                    transition:transform 0.1s;box-shadow:0 4px 20px rgba(74,144,217,0.4);
                ">${i18n.t('booth.start')}</button>
                <div style="display:flex;gap:1.5rem;color:var(--pb-color-text-muted);font-size:0.85rem;">
                    ${galleryEnabled ? `<a href="#/gallery" style="color:inherit;text-decoration:none;">🖼️ ${i18n.t('gallery.title')}</a>` : ''}
                    <a href="#/admin" style="color:inherit;text-decoration:none;">⚙️ Admin</a>
                </div>
            </div>`;
        }

        activatePreview();
        scheduleCropSizing();
        showStorage(el);
        showHelpButton(el);
        wireFilterBar(el);

        const btn = el.querySelector('#btn-start');
        btn.addEventListener('click', () => beginFlow());
        btn.addEventListener('pointerdown', () => { btn.style.transform = 'scale(0.95)'; });
        btn.addEventListener('pointerup', () => { btn.style.transform = ''; });
        btn.addEventListener('pointerleave', () => { btn.style.transform = ''; });

        // Keyboard trigger
        const keyHandler = (e) => {
            if (e.code === 'Space' || e.key === 'Enter') {
                e.preventDefault();
                document.removeEventListener('keydown', keyHandler);
                beginFlow();
            }
        };
        document.addEventListener('keydown', keyHandler);
    }

    function renderPayment(el) {
        const data = pendingPayment || {};
        const amount = data.amount_cents || 0;
        const currency = 'EUR';
        const amountStr = (amount / 100).toFixed(2);

        el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:2rem;padding:2rem;">
            <h1 style="font-size:clamp(1.5rem,5vw,2.5rem);text-align:center;">${i18n.t('booth.payment_title') || 'Bitte bezahlen'}</h1>
            <div id="pay-amount" style="font-size:clamp(3rem,10vw,5rem);font-weight:bold;color:var(--pb-color-primary);">
                ${amountStr} ${currency}
            </div>
            <div id="pay-progress-bar" style="width:80%;max-width:400px;height:24px;background:var(--pb-color-surface);border-radius:12px;overflow:hidden;position:relative;">
                <div id="pay-bar-fill" style="width:0%;height:100%;background:var(--pb-color-primary);border-radius:12px;transition:width 0.3s ease;"></div>
            </div>
            <div id="pay-status" style="font-size:1.1rem;color:var(--pb-color-text-muted);text-align:center;">
                ${i18n.t('booth.insert_money') || 'Bitte Geld einwerfen oder Karte bereithalten ...'}
            </div>
            <div id="pay-detail" style="font-size:0.9rem;color:var(--pb-color-text-muted);display:none;"></div>
            <button id="btn-pay-cancel" style="
                margin-top:1rem;padding:0.75rem 2rem;border-radius:var(--pb-radius);
                border:2px solid #555;background:transparent;color:var(--pb-color-text);
                font-size:1rem;cursor:pointer;
            ">${i18n.t('booth.cancel') || 'Abbrechen'}</button>
        </div>`;

        el.querySelector('#btn-pay-cancel')?.addEventListener('click', () => {
            pendingPayment = null;
            transition('idle');
        });
    }

    function updatePaymentProgress(data) {
        const bar = document.getElementById('pay-bar-fill');
        const statusEl = document.getElementById('pay-status');
        const detailEl = document.getElementById('pay-detail');
        const amountEl = document.getElementById('pay-amount');
        if (!bar || !statusEl) return;

        const pct = data.required_cents > 0
            ? Math.min(100, Math.round((data.paid_cents / data.required_cents) * 100))
            : 100;
        bar.style.width = pct + '%';

        const paid = (data.paid_cents / 100).toFixed(2);
        const required = (data.required_cents / 100).toFixed(2);
        const remaining = (data.remaining_cents / 100).toFixed(2);

        if (data.remaining_cents > 0) {
            statusEl.textContent = `Eingeworfen: ${paid} EUR — noch ${remaining} EUR`;
        } else {
            statusEl.textContent = 'Bezahlt!';
            statusEl.style.color = 'var(--pb-color-success)';
            bar.style.background = 'var(--pb-color-success)';
        }

        if (data.credit_cents > 0 && detailEl) {
            detailEl.style.display = 'block';
            detailEl.textContent = `Guthaben: ${(data.credit_cents / 100).toFixed(2)} EUR`;
        }
    }

    function showPaymentDone(data) {
        const statusEl = document.getElementById('pay-status');
        const bar = document.getElementById('pay-bar-fill');
        const cancelBtn = document.getElementById('btn-pay-cancel');
        if (bar) { bar.style.width = '100%'; bar.style.background = 'var(--pb-color-success)'; }
        if (statusEl) {
            statusEl.style.color = 'var(--pb-color-success)';
            statusEl.style.fontSize = '1.5rem';
            statusEl.textContent = 'Bezahlt!';
        }
        if (cancelBtn) cancelBtn.style.display = 'none';

        const detailEl = document.getElementById('pay-detail');
        if (detailEl && data.credit_remaining > 0) {
            detailEl.style.display = 'block';
            detailEl.textContent = `Restguthaben: ${(data.credit_remaining / 100).toFixed(2)} EUR`;
        }
    }

    function renderCountdown(el) {
        const isFS = previewSize === 'fullscreen';
        const containerStyle = previewContainerStyle();
        let count = countdownSeconds;
        const shotLabel = (seq && seq.total > 1) ? ` (Foto ${seq.index + 1} von ${seq.total})` : '';
        const previewContent = cameraMode === 'server'
            ? `<img id="preview-img" src="/api/v1/camera/stream" style="width:100%;height:100%;object-fit:cover;" alt="Preview">`
            : `<video id="preview-video" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover;${mirrorPreview ? 'transform:scaleX(-1);' : ''}"></video>`;
        const countdownOverlay = `<div id="countdown-overlay" style="
            position:absolute;top:0;left:0;right:0;bottom:0;
            display:flex;align-items:center;justify-content:center;
            font-size:clamp(5rem,20vw,10rem);font-weight:bold;color:white;
            text-shadow:0 0 30px rgba(0,0,0,0.8);
            pointer-events:none;
        ">${count}</div>`;

        if (isFS) {
            el.innerHTML = `
            <div style="width:100%;height:100%;position:relative;">
                <div style="${containerStyle}">
                    ${previewContent}
                    ${cropGuideHTML()}
                    ${countdownOverlay}
                </div>
                <p style="position:absolute;bottom:2rem;left:0;right:0;text-align:center;font-size:1.25rem;text-shadow:0 2px 8px rgba(0,0,0,0.7);z-index:2;">${i18n.t('booth.get_ready')}${shotLabel}</p>
            </div>
            <style>
                @keyframes pulse { from { transform: scale(1.5); opacity: 0.5; } to { transform: scale(1); opacity: 1; } }
            </style>`;
        } else {
            el.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1rem;">
                <div style="${containerStyle}">
                    ${previewContent}
                    ${cropGuideHTML()}
                    ${countdownOverlay}
                </div>
                <p style="font-size:1.25rem;">${i18n.t('booth.get_ready')}${shotLabel}</p>
            </div>
            <style>
                @keyframes pulse { from { transform: scale(1.5); opacity: 0.5; } to { transform: scale(1); opacity: 1; } }
            </style>`;
        }

        activatePreview();
        scheduleCropSizing();
        applyLookToPreview();   // keep the chosen look on screen while posing

        sounds.tick(count === 1);

        // Visible countdown ticks once per second (only updates the number).
        countdownTimer = setInterval(() => {
            count--;
            const overlay = document.getElementById('countdown-overlay');
            if (count > 0 && overlay) {
                overlay.textContent = count;
                overlay.style.animation = 'none';
                overlay.offsetHeight;
                overlay.style.animation = 'pulse 0.5s ease-out';
            } else {
                clearInterval(countdownTimer);
                if (overlay) overlay.textContent = '0';
            }
        }, 1000);

        // The actual capture is fired captureLeadMs BEFORE the "0" moment, so the
        // photo (after camera latency) lands exactly at zero. Lead 0 = at zero.
        const fireAt = Math.max(0, countdownSeconds * 1000 - captureLeadMs);
        captureLeadTimer = setTimeout(async () => {
            captureLeadTimer = null;
            if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
            // Capture frame from video BEFORE we destroy the DOM
            await grabFrameFromVideo();
            transition('capture');
        }, fireAt);
    }

    function renderCapture(el) {
        el.innerHTML = `
        <div style="position:absolute;top:0;left:0;right:0;bottom:0;background:white;animation:flash 0.5s ease-out forwards;z-index:10;"></div>
        <div id="capture-status" style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1rem;">
            <div class="spinner" style="width:48px;height:48px;border:4px solid var(--pb-color-surface);border-top-color:var(--pb-color-primary);border-radius:50%;animation:spin 0.8s linear infinite;"></div>
            <p id="capture-msg" style="font-size:1rem;color:var(--pb-color-text-muted);">${i18n.t('booth.processing')}</p>
        </div>
        <style>
            @keyframes flash { from { opacity: 1; } to { opacity: 0; } }
            @keyframes spin { to { transform: rotate(360deg); } }
        </style>`;

        capturePhoto().catch(err => {
            console.error('Capture failed:', err);
            const msg = document.getElementById('capture-msg');
            if (msg) {
                msg.textContent = err.message || 'Fehler bei der Aufnahme';
                msg.style.color = 'var(--pb-color-error)';
            }
            setTimeout(() => transition('idle'), 3000);
        });
    }

    function renderProcessing(el) {
        el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1.5rem;">
            <div class="spinner" style="width:64px;height:64px;border:4px solid var(--pb-color-surface);border-top-color:var(--pb-color-primary);border-radius:50%;animation:spin 0.8s linear infinite;"></div>
            <p style="font-size:1.25rem;">${i18n.t('booth.processing')}</p>
        </div>
        <style>@keyframes spin { to { transform: rotate(360deg); } }</style>`;
    }

    function renderReview(el) {
        const photoUrl = lastPhoto ? `/api/v1/photos/${lastPhoto.photo_id}/file` : '';
        el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1.5rem;padding:2rem;">
            <h2>${i18n.t('booth.review_title')}</h2>
            <img id="review-photo" src="${photoUrl}" style="max-width:100%;max-height:60vh;border-radius:var(--pb-radius);object-fit:contain;box-shadow:0 4px 30px rgba(0,0,0,0.5);" alt="Photo">
            <div style="display:flex;gap:1rem;flex-wrap:wrap;justify-content:center;">
                <button id="btn-retake" class="pb-btn pb-btn-outline">${i18n.t('booth.retake')}</button>
                ${guestbookEnabled && lastPhoto ? '<button id="btn-guestbook" class="pb-btn pb-btn-outline">✍️ Grußwort</button>' : ''}
                <button id="btn-continue" class="pb-btn pb-btn-primary">${i18n.t('booth.continue')}</button>
            </div>
        </div>
        ${btnStyles()}`;

        el.querySelector('#btn-retake').addEventListener('click', () => {
            // Repeat the SAME thing: a set restarts the whole set, a single retakes one.
            if (lastTemplate && lastTemplate.photo_count > 1) startCapture(lastTemplate);
            else transition('countdown');
        });
        el.querySelector('#btn-guestbook')?.addEventListener('click', () => openGuestbook(photoUrl));
        el.querySelector('#btn-continue').addEventListener('click', () => transition('share'));
    }

    // ── Guest book: draw / write on the photo ────────────────────────

    /** Full-screen editor over the photo. Saves a transparent PNG plus an
     *  optional greeting; the server composites both into the photo itself. */
    function openGuestbook(photoUrl) {
        const COLORS = ['#ffffff', '#ff4d6d', '#ffd166', '#4cc9f0', '#7bdc8b', '#1b1b1b'];
        closeOverlay();
        // Deliberately not openOverlay(): that centres a padded card and closes on
        // a tap outside — here the canvas wants the whole screen, and a stray tap
        // must not throw away what someone just drew.
        const o = document.createElement('div');
        o.id = 'pb-overlay';   // same id, so transition() still cleans it up
        o.style.cssText = 'position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.9);' +
            'backdrop-filter:blur(4px);display:flex;';
        document.body.appendChild(o);
        o.innerHTML = `
        <div style="width:100%;height:100%;display:flex;flex-direction:column;gap:0.75rem;padding:1rem;box-sizing:border-box;">
            <div id="gb-stage" style="flex:1;min-height:0;display:flex;align-items:center;justify-content:center;position:relative;">
                <!-- Der Rahmen muss das Bild exakt umschließen (inline-block + line-height:0),
                     sonst ist die Zeichenfläche größer als das Foto: die Striche säßen
                     versetzt und die Fläche würde die Bedienelemente darunter überdecken.
                     Die Höhe begrenzt vh, damit Werkzeuge und Textfeld immer Platz haben. -->
                <div id="gb-frame" style="position:relative;display:inline-block;line-height:0;max-width:100%;">
                    <img id="gb-photo" src="${photoUrl}" style="display:block;max-width:100%;max-height:58vh;border-radius:var(--pb-radius);" alt="">
                    <canvas id="gb-canvas" style="position:absolute;left:0;top:0;width:100%;height:100%;touch-action:none;border-radius:var(--pb-radius);cursor:crosshair;"></canvas>
                </div>
            </div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;justify-content:center;">
                ${COLORS.map((c, i) => `<button class="gb-color" data-color="${c}" style="
                    width:2.75rem;height:2.75rem;border-radius:50%;background:${c};cursor:pointer;
                    border:3px solid ${i === 0 ? 'var(--pb-color-primary)' : 'rgba(255,255,255,0.35)'};"></button>`).join('')}
                <span style="width:1rem;"></span>
                <button class="gb-size" data-size="4" style="min-height:2.75rem;padding:0 0.9rem;border-radius:999px;cursor:pointer;border:2px solid var(--pb-color-primary);background:rgba(127,127,127,0.2);color:inherit;">dünn</button>
                <button class="gb-size" data-size="10" style="min-height:2.75rem;padding:0 0.9rem;border-radius:999px;cursor:pointer;border:2px solid transparent;background:rgba(127,127,127,0.2);color:inherit;">dick</button>
                <button id="gb-undo" class="pb-btn pb-btn-outline" style="min-height:2.75rem;">↶ Zurück</button>
                <button id="gb-clear" class="pb-btn pb-btn-outline" style="min-height:2.75rem;">Alles löschen</button>
            </div>
            <input id="gb-message" type="text" maxlength="${guestbookMaxLen}" placeholder="Grußwort (optional)" style="
                width:100%;box-sizing:border-box;padding:0.75rem 0.9rem;border-radius:var(--pb-radius);
                border:1px solid rgba(255,255,255,0.25);background:rgba(0,0,0,0.4);color:inherit;font-size:1.05rem;">
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;flex-wrap:wrap;">
                <button id="gb-cancel" class="pb-btn pb-btn-outline">Abbrechen</button>
                <button id="gb-save" class="pb-btn pb-btn-primary">Aufs Foto übernehmen</button>
            </div>
            <p id="gb-msg" style="margin:0;text-align:right;font-size:0.9rem;min-height:1.2em;"></p>
        </div>
        ${btnStyles()}`;

        const canvas = o.querySelector('#gb-canvas');
        const photo = o.querySelector('#gb-photo');
        const ctx = canvas.getContext('2d');
        const strokes = [];          // for undo — each entry is one finished stroke
        let current = null;
        let color = COLORS[0];
        let width = 4;

        // The canvas gets the photo's on-screen pixel size; the server scales the
        // exported PNG up to the real photo resolution.
        function sizeCanvas() {
            const r = photo.getBoundingClientRect();
            if (!r.width || !r.height) return;
            canvas.width = Math.round(r.width);
            canvas.height = Math.round(r.height);
            redraw();
        }
        function redraw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            for (const s of strokes) {
                if (s.points.length < 2) continue;
                ctx.strokeStyle = s.color;
                ctx.lineWidth = s.width;
                ctx.beginPath();
                ctx.moveTo(s.points[0].x * canvas.width, s.points[0].y * canvas.height);
                for (const p of s.points.slice(1)) ctx.lineTo(p.x * canvas.width, p.y * canvas.height);
                ctx.stroke();
            }
        }
        // Points are stored 0..1 so a mid-drawing resize (rotation, keyboard
        // opening) keeps the strokes where the guest put them.
        function pos(ev) {
            const r = canvas.getBoundingClientRect();
            return { x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height };
        }

        if (photo.complete) sizeCanvas(); else photo.addEventListener('load', sizeCanvas);
        const onResize = () => sizeCanvas();
        window.addEventListener('resize', onResize);

        canvas.addEventListener('pointerdown', ev => {
            canvas.setPointerCapture(ev.pointerId);
            current = { color, width, points: [pos(ev)] };
            strokes.push(current);
        });
        canvas.addEventListener('pointermove', ev => {
            if (!current) return;
            current.points.push(pos(ev));
            redraw();
        });
        const endStroke = () => { current = null; };
        canvas.addEventListener('pointerup', endStroke);
        canvas.addEventListener('pointercancel', endStroke);
        canvas.addEventListener('pointerleave', endStroke);

        o.querySelectorAll('.gb-color').forEach(btn => btn.addEventListener('click', () => {
            color = btn.dataset.color;
            o.querySelectorAll('.gb-color').forEach(b =>
                b.style.borderColor = b === btn ? 'var(--pb-color-primary)' : 'rgba(255,255,255,0.35)');
        }));
        o.querySelectorAll('.gb-size').forEach(btn => btn.addEventListener('click', () => {
            width = parseInt(btn.dataset.size, 10);
            o.querySelectorAll('.gb-size').forEach(b =>
                b.style.borderColor = b === btn ? 'var(--pb-color-primary)' : 'transparent');
        }));
        o.querySelector('#gb-undo').addEventListener('click', () => { strokes.pop(); redraw(); });
        o.querySelector('#gb-clear').addEventListener('click', () => { strokes.length = 0; redraw(); });

        const close = () => { window.removeEventListener('resize', onResize); o.remove(); };
        o.querySelector('#gb-cancel').addEventListener('click', close);

        o.querySelector('#gb-save').addEventListener('click', async () => {
            const message = o.querySelector('#gb-message').value.trim();
            const msgEl = o.querySelector('#gb-msg');
            if (!strokes.length && !message) {
                msgEl.textContent = 'Erst malen oder etwas schreiben.';
                msgEl.style.color = 'var(--pb-color-error)';
                return;
            }
            msgEl.style.color = 'var(--pb-color-text-muted)';
            msgEl.textContent = 'Übernehme…';
            try {
                const fd = new FormData();
                if (strokes.length) {
                    const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
                    fd.append('overlay', blob, 'guestbook.png');
                }
                fd.append('message', message);
                const res = await fetch(`/api/v1/photos/${lastPhoto.photo_id}/guestbook`,
                    { method: 'POST', body: fd });
                if (!res.ok) {
                    const e = await res.json().catch(() => ({}));
                    throw new Error(e.detail || `HTTP ${res.status}`);
                }
                close();
                // Cache-bust: the file changed behind the same URL.
                const img = document.getElementById('review-photo');
                if (img) img.src = `/api/v1/photos/${lastPhoto.photo_id}/file?v=${Date.now()}`;
            } catch (err) {
                msgEl.style.color = 'var(--pb-color-error)';
                msgEl.textContent = 'Fehler: ' + err.message;
            }
        });
    }

    function renderShare(el) {
        const photoId = lastPhoto?.photo_id;
        const hasGif = !!lastPhoto?.gif;
        const downloadUrl = photoId ? `/api/v1/photos/${photoId}/file` : '#';
        const gifUrl = photoId ? `/api/v1/photos/${photoId}/gif` : '#';

        el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1.5rem;padding:2rem;overflow-y:auto;">
            <h2>${i18n.t('share.title')}</h2>
            <img src="${downloadUrl}" style="max-width:200px;max-height:200px;border-radius:8px;object-fit:contain;" alt="Photo">
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.75rem;width:100%;max-width:600px;">
                <button id="card-photo" class="share-card">
                    <span style="font-size:1.8rem;">📱</span>
                    Foto aufs Handy
                </button>
                <button id="card-live" class="share-card">
                    <span style="font-size:1.8rem;">📺</span>
                    Galerie (Live)
                </button>
                ${hasGif ? `
                <button id="card-gif" class="share-card">
                    <span style="font-size:1.8rem;">🎞️</span>
                    GIF aufs Handy
                </button>` : ''}
                ${availableOutputs.includes('output.email') ? `
                <button id="card-email" class="share-card">
                    <span style="font-size:1.8rem;">✉️</span>
                    Per E-Mail
                </button>` : ''}
                ${availableOutputs.includes('output.bluetooth') ? `
                <button id="card-bt" class="share-card">
                    <span style="font-size:1.8rem;">🔵</span>
                    Bluetooth
                </button>` : ''}
                ${availableOutputs.includes('output.printer') ? `
                <button id="card-print" class="share-card">
                    <span style="font-size:1.8rem;">🖨️</span>
                    Drucken
                </button>` : ''}
            </div>
            <button id="btn-done" class="pb-btn pb-btn-success" style="margin-top:0.5rem;">
                ${i18n.t('booth.thanks')} &rarr;
            </button>
        </div>
        <style>
            .share-card {
                display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.5rem;
                padding:1.4rem 1rem;border-radius:16px;
                background:var(--pb-color-surface-2,#232c4a);
                color:white;text-decoration:none;font-size:1.05rem;font-weight:600;min-height:96px;
                border:2px solid var(--pb-color-primary);cursor:pointer;text-align:center;
                box-shadow:0 6px 18px rgba(0,0,0,0.35);transition:transform 0.1s, background 0.15s, box-shadow 0.15s;
            }
            .share-card:hover { background:var(--pb-color-primary); box-shadow:0 8px 24px rgba(108,140,255,0.45); }
            .share-card:active { transform:scale(0.95); }
            .share-card.uploading { border-color:#c77b1a; cursor:progress; opacity:0.92; }
            .share-card.uploading:hover { background:var(--pb-color-surface-2,#232c4a); box-shadow:0 6px 18px rgba(0,0,0,0.35); }
            .up-spin { width:26px;height:26px;border:3px solid rgba(255,255,255,0.25);
                       border-top-color:#ffb454;border-radius:50%;animation:spin 0.8s linear infinite; }
            @keyframes spin { to { transform: rotate(360deg); } }
        </style>
        ${btnStyles()}`;

        // ── Fullscreen modal overlay (above everything; OSK stays on top) ──
        const fullUrl = (u) => `${shareBase || location.origin}${u}`;

        // Double-click guard + per-action cooldown (avoids "nothing happens" re-taps)
        const cooldownUntil = {};
        const COOLDOWN = { print: 10000, email: 4000, bluetooth: 4000 };
        function tooSoon(action) {
            const now = Date.now();
            if (cooldownUntil[action] && now < cooldownUntil[action]) {
                return Math.ceil((cooldownUntil[action] - now) / 1000);
            }
            cooldownUntil[action] = now + (COOLDOWN[action] || 4000);
            return 0;
        }
        const toast = (text) => {
            const o = openOverlay(`<p style="margin:0;font-size:1.1rem;">${text}</p><button class="pb-btn pb-btn-outline" data-close>OK</button>`);
            setTimeout(() => { if (document.getElementById('pb-overlay') === o) closeOverlay(); }, 1800);
        };

        const showQR = (url, title) => {
            let qrHtml;
            try {
                const qr = qrcode(0, 'M');
                qr.addData(url);
                qr.make();
                qrHtml = qr.createSvgTag({ cellSize: 8, margin: 2 });
            } catch {
                qrHtml = `<p style="color:#000;word-break:break-all;">${url}</p>`;
            }
            const o = openOverlay(`
                <h2 style="margin:0;">${title}</h2>
                <p style="color:var(--pb-color-text-muted);margin:0;">Mit der Handy-Kamera scannen</p>
                <div style="background:#fff;padding:16px;border-radius:14px;">${qrHtml}</div>
                <button class="pb-btn pb-btn-primary" data-close>Schließen</button>
            `);
        };

        // When the remote gallery is live, hand out its off-box (internet-reachable)
        // links so phones that aren't on the booth's network can still download.
        const baseName = (p) => (p || '').split(/[/\\]/).pop();
        const remoteFile = (name) =>
            (remoteGallery?.active && name) ? `${remoteGallery.image_base}/${baseName(name)}` : null;
        const galleryShareUrl = remoteGallery?.active ? remoteGallery.gallery_url : `${shareBase || location.origin}/live`;

        // Gate a share card behind the remote upload: while the off-box file isn't
        // live yet, show a spinner + elapsed counter and block the QR (scanning it
        // would 404). Probe the remote URL with an <img> and enable once it loads.
        // Local (no remote gallery) links are available immediately.
        const gateCard = (card, remoteUrl, localUrl, title) => {
            if (!card) return;
            if (!(remoteGallery?.active && remoteUrl)) {
                card.addEventListener('click', () => showQR(localUrl, title));
                return;
            }
            const orig = card.innerHTML;
            let ready = false, secs = 0;
            const paint = () => { card.innerHTML =
                `<span class="up-spin"></span><small style="font-weight:600;">Wird hochgeladen… ${secs}s</small>`; };
            paint();
            card.classList.add('uploading');
            const tick = setInterval(() => { if (!ready) { secs++; paint(); } }, 1000);
            const probe = () => {
                const img = new Image();
                img.onload = () => {
                    if (ready) return;
                    ready = true; clearInterval(tick);
                    card.classList.remove('uploading'); card.innerHTML = orig;
                };
                img.onerror = () => { if (!ready) setTimeout(probe, 1200); };
                img.src = remoteUrl + (remoteUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
            };
            probe();
            card.addEventListener('click', () => {
                if (ready) showQR(remoteUrl, title);
                else toast('Foto wird noch hochgeladen – gleich bereit…');
            });
        };

        gateCard(el.querySelector('#card-photo'),
                 remoteFile(lastPhoto?.filename), fullUrl(downloadUrl), 'Foto aufs Handy');
        gateCard(el.querySelector('#card-gif'),
                 remoteFile(typeof lastPhoto?.gif === 'string' ? lastPhoto.gif : null), fullUrl(gifUrl), 'GIF aufs Handy');
        el.querySelector('#card-live')?.addEventListener('click', () => showQR(galleryShareUrl, remoteGallery?.active ? 'Galerie öffnen' : 'Live-Galerie öffnen'));

        el.querySelector('#card-email')?.addEventListener('click', () => {
            const o = openOverlay(`
                <h2 style="margin:0;">Per E-Mail senden</h2>
                <input id="m-email" type="email" inputmode="email" placeholder="email@beispiel.de"
                    style="width:min(80vw,380px);padding:0.9rem;border-radius:10px;border:1px solid #444;background:#0e1a30;color:#fff;font-size:1.15rem;text-align:center;">
                <div style="display:flex;gap:0.75rem;">
                    <button class="pb-btn pb-btn-outline" data-close>Abbrechen</button>
                    <button id="m-send" class="pb-btn pb-btn-primary">Senden</button>
                </div>
                <p id="m-msg" style="font-size:0.95rem;min-height:1.3em;margin:0;"></p>
            `);
            const input = o.querySelector('#m-email');
            setTimeout(() => input.focus(), 60); // brings up the on-screen keyboard
            o.querySelector('#m-send').addEventListener('click', async () => {
                const email = input.value.trim();
                const msg = o.querySelector('#m-msg');
                if (!email || !email.includes('@')) {
                    msg.textContent = 'Bitte eine gültige E-Mail eingeben'; msg.style.color = 'var(--pb-color-error)'; return;
                }
                const w = tooSoon('email');
                if (w) { msg.textContent = `Bitte warten… (${w}s)`; msg.style.color = 'var(--pb-color-text-muted)'; return; }
                const sendBtn = o.querySelector('#m-send');
                sendBtn.disabled = true;  // in-flight guard against double-tap
                msg.textContent = 'Wird gesendet…'; msg.style.color = 'var(--pb-color-text-muted)';
                try {
                    const res = await fetch('/api/v1/outputs/send', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ photo_id: photoId, module: 'output.email', target: email }),
                    });
                    const r = await res.json();
                    if (r.status === 'ok') {
                        msg.textContent = 'Gesendet! ✓'; msg.style.color = 'var(--pb-color-success)';
                        setTimeout(closeOverlay, 1500);
                    } else throw new Error(r.message || r.detail || 'Senden fehlgeschlagen');
                } catch (err) {
                    msg.textContent = 'Fehler: ' + err.message; msg.style.color = 'var(--pb-color-error)';
                    sendBtn.disabled = false;  // allow retry after a failure
                }
            });
        });

        el.querySelector('#card-bt')?.addEventListener('click', async () => {
            if (!photoId) return;
            const w = tooSoon('bluetooth'); if (w) return toast(`Bitte warten… (${w}s)`);
            const o = openOverlay(`
                <h2 style="margin:0;">Per Bluetooth senden</h2>
                <p id="m-msg" style="color:var(--pb-color-text-muted);margin:0;">
                    Suche Geräte in der Nähe… (Bluetooth am Handy einschalten und sichtbar machen)
                </p>
                <div id="bt-list" style="display:flex;flex-direction:column;gap:0.5rem;width:100%;max-height:45vh;overflow-y:auto;"></div>
                <button id="bt-again" class="pb-btn pb-btn-outline" style="display:none;">Erneut suchen</button>
                <button class="pb-btn pb-btn-outline" data-close>Schließen</button>
            `);
            const msg = o.querySelector('#m-msg');
            const list = o.querySelector('#bt-list');
            const again = o.querySelector('#bt-again');

            async function sendTo(address, name) {
                list.innerHTML = '';
                again.style.display = 'none';
                msg.style.color = 'var(--pb-color-text-muted)';
                msg.textContent = `Sende an „${name}" — bitte am Handy bestätigen…`;
                try {
                    const res = await fetch('/api/v1/outputs/send', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ photo_id: photoId, module: 'output.bluetooth', target: address }),
                    });
                    const r = await res.json();
                    if (r.status === 'ok') {
                        msg.textContent = 'Gesendet ✓';
                        msg.style.color = 'var(--pb-color-success)';
                    } else throw new Error(r.message || r.detail || 'Senden fehlgeschlagen');
                } catch (err) {
                    msg.textContent = 'Fehler: ' + err.message;
                    msg.style.color = 'var(--pb-color-error)';
                    again.style.display = '';
                }
            }

            async function scan() {
                list.innerHTML = '';
                again.style.display = 'none';
                msg.style.color = 'var(--pb-color-text-muted)';
                msg.textContent = 'Suche Geräte in der Nähe… (Bluetooth am Handy einschalten und sichtbar machen)';
                let devices = [];
                try {
                    const r = await fetch('/api/v1/bluetooth/scan?duration=10').then(r => r.json());
                    devices = r.devices || [];
                } catch { devices = []; }

                if (!devices.length) {
                    msg.textContent = 'Kein Gerät gefunden. Am Handy Bluetooth einschalten und '
                        + 'den Sichtbarkeits-Bildschirm offen lassen, dann erneut suchen.';
                    again.style.display = '';
                    return;
                }
                msg.textContent = 'Gerät auswählen:';
                devices.forEach(d => {
                    const b = document.createElement('button');
                    b.className = 'pb-btn pb-btn-outline';
                    b.style.cssText = 'text-align:left;display:flex;justify-content:space-between;gap:0.75rem;';
                    b.innerHTML = `<span>${d.name}</span>`;
                    b.addEventListener('click', () => sendTo(d.address, d.name));
                    list.appendChild(b);
                });
                again.style.display = '';
            }

            again.addEventListener('click', scan);
            scan();
        });

        el.querySelector('#card-print')?.addEventListener('click', async () => {
            if (!photoId) return;
            const w = tooSoon('print'); if (w) return toast(`Bitte warten… (${w}s)`);
            const o = openOverlay(`
                <h2 style="margin:0;">Drucken</h2>
                <p id="m-msg" style="color:var(--pb-color-text-muted);margin:0;">Sende an Drucker…</p>
                <button class="pb-btn pb-btn-outline" data-close>Schließen</button>
            `);
            const msg = o.querySelector('#m-msg');
            try {
                const res = await fetch('/api/v1/outputs/send', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ photo_id: photoId, module: 'output.printer' }),
                });
                const result = await res.json();
                if (result.status === 'blocked') {
                    msg.innerHTML = `⛔ ${result.message || 'Kein Druckmedium mehr'}<br><small>Bitte Personal informieren.</small>`;
                    msg.style.color = 'var(--pb-color-error)';
                    return;
                }
                if (result.print_mode === 'browser') {
                    const printWin = window.open('', '_blank');
                    if (printWin) {
                        printWin.document.write(`<html><head><title>Drucken</title>
                            <style>@page{margin:0}body{margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#000;}img{max-width:100%;max-height:100vh;object-fit:contain;}</style>
                            </head><body><img src="${location.origin}${downloadUrl}" onload="window.print();setTimeout(()=>window.close(),1000);"></body></html>`);
                        printWin.document.close();
                    }
                    msg.textContent = 'Druckdialog geöffnet'; msg.style.color = 'var(--pb-color-success)';
                } else if (result.status === 'ok') {
                    msg.textContent = 'Wird gedruckt ✓'; msg.style.color = 'var(--pb-color-success)';
                    // Warn on blocking problems (paper out, cover open…) and show
                    // remaining sheets — for the printer this job actually used.
                    try {
                        const q = result.printer ? `?printer=${encodeURIComponent(result.printer)}` : '';
                        const st = await fetch('/api/v1/printer/state' + q).then(r => r.json());
                        const errs = (st.alerts || []).filter(a => a.severity === 'error');
                        const rem = st.media && st.media.remaining_prints;
                        if (errs.length || st.ready === false) {
                            msg.innerHTML = `⚠️ ${st.message || 'Drucker-Problem'}<br><small>Bitte Personal informieren.</small>`;
                            msg.style.color = 'var(--pb-color-error)';
                        } else if (rem != null && rem <= 10) {
                            msg.innerHTML = `Wird gedruckt ✓<br><small style="color:#ff9a3c;">Nur noch ${rem} Blatt — bitte Personal informieren.</small>`;
                        } else if (rem != null) {
                            msg.innerHTML = `Wird gedruckt ✓<br><small style="color:rgba(255,255,255,0.7);">noch ${rem} Drucke</small>`;
                        }
                    } catch {}
                } else throw new Error(result.message || 'Drucken fehlgeschlagen');
            } catch (err) {
                msg.textContent = 'Fehler: ' + err.message; msg.style.color = 'var(--pb-color-error)';
            }
        });

        el.querySelector('#btn-done').addEventListener('click', () => { closeOverlay(); transition('thanks'); });
    }

    function renderThanks(el) {
        el.innerHTML = `
        <div id="thanks-screen" style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1.5rem;cursor:pointer;">
            <h1 style="font-size:clamp(2.5rem,8vw,4rem);">${i18n.t('booth.thanks')}</h1>
            <p style="font-size:1.25rem;color:var(--pb-color-text-muted);">${i18n.t('booth.return_soon')}</p>
            <p style="font-size:0.9rem;color:var(--pb-color-text-muted);opacity:0.6;">${i18n.t('booth.tap_to_start')}</p>
        </div>`;
        el.querySelector('#thanks-screen').addEventListener('click', () => transition('idle'));
    }

    // ── Capture logic ────────────────────────────────────────────────

    async function grabFrameFromVideo() {
        /**
         * Grab a JPEG frame from the live <video> element.
         * MUST be called while the video is still in the DOM (before transition to capture).
         */
        capturedBlob = null;
        if (cameraMode !== 'webrtc') return;

        const video = document.querySelector('video');
        if (!video?.srcObject || !video.videoWidth) return;

        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        // Undo the CSS mirroring of the preview — the guests pose in a mirror, but
        // the saved photo must be the right way round (text/logos stay readable).
        if (mirrorPreview) {
            ctx.translate(canvas.width, 0);
            ctx.scale(-1, 1);
        }
        ctx.drawImage(video, 0, 0);

        capturedBlob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.92));
    }

    async function capturePhoto() {
        // Mark a capture in flight so the state-timeout safety net won't abort the
        // shot (and wipe an in-progress series). Hard cap so a truly stuck capture
        // still recovers instead of hanging the booth forever.
        captureInFlight = true;
        captureDeadline = Date.now() + 60000;
        try {
            await _capturePhoto();
        } finally {
            captureInFlight = false;
        }
    }

    async function _capturePhoto() {
        // For WebRTC: upload the pre-grabbed frame to the server
        if (cameraMode === 'webrtc' && capturedBlob) {
            const fd = new FormData();
            fd.append('file', capturedBlob, 'capture.jpg');
            const uploadRes = await fetch('/api/v1/photos/upload', { method: 'POST', body: fd });
            if (!uploadRes.ok) {
                throw new Error('Frame upload fehlgeschlagen');
            }
            capturedBlob = null;
        }

        // Trigger server-side capture + save. Flag raw set-shots so they aren't
        // mirrored to the remote gallery individually (only the finished collage).
        const partOfSet = !!(seq && seq.total > 1);
        const res = await fetch('/api/v1/photos/capture', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ part_of_set: partOfSet, filter: selectedFilter }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Aufnahme fehlgeschlagen (HTTP ${res.status})`);
        }
        const photo = await res.json();

        // Multi-photo sequence: collect shots, then render the collage
        if (seq) {
            seq.shots.push(photo.id);
            seq.index++;
            if (seq.index < seq.total) {
                transition('countdown');   // next shot
                return;
            }
            // All shots taken — render the template into a collage
            transition('processing');
            const r = await fetch('/api/v1/templates/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ template_id: seq.template.id, photo_ids: seq.shots }),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                throw new Error(err.detail || 'Collage konnte nicht erstellt werden');
            }
            const collage = await r.json();
            seq = null;
            lastPhoto = { photo_id: collage.id, filename: collage.filename, gif: collage.gif };
            transition('review');
            return;
        }

        lastPhoto = { photo_id: photo.id, filename: photo.filename, gif: photo.gif_filename };
        transition('review');
    }

    // ── Shared styles ────────────────────────────────────────────────

    function btnStyles() {
        return `<style>
            .pb-btn {
                padding:1rem 2.5rem;border-radius:14px;border:none;font-weight:700;
                font-size:1.15rem;cursor:pointer;min-height:var(--pb-touch-target);
                box-shadow:0 6px 18px rgba(0,0,0,0.35);transition:transform 0.1s, filter 0.15s;
            }
            .pb-btn:hover { filter:brightness(1.08); }
            .pb-btn:active { transform:scale(0.95); }
            .pb-btn-primary { background:var(--pb-color-primary);color:white; }
            .pb-btn-outline { background:rgba(108,140,255,0.12);border:2px solid var(--pb-color-primary);color:#fff; }
            .pb-btn-success { background:var(--pb-color-success);color:white;box-shadow:0 6px 18px rgba(52,211,153,0.4); }
        </style>`;
    }
}
