// Scharfstell-Assistent: geführter Ablauf für den Aufbau vor der Party.
//
// Fokus festhalten ist bewusst Aufgabe des Menschen — bei Canon sitzt der
// AF/MF-Schalter am Objektiv, Software kann ihn nicht umlegen. Die Box hilft
// nur: Autofokus einmal auslösen, Schärfe in der Lupe (Live-Bild) oder am
// Testfoto prüfen. Das Testfoto landet nicht in Galerie oder Druck.

const API = '/api/v1/camera/focus';

// Kleine Skizze: Objektiv von der Seite, der Schalter AF/MF hervorgehoben.
const LENS_SKETCH = `
<svg viewBox="0 0 220 90" width="220" height="90" aria-hidden="true" style="flex:none;">
  <rect x="4" y="14" width="62" height="62" rx="8" fill="none" stroke="currentColor" stroke-width="2.5"/>
  <text x="35" y="50" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.7">Kamera</text>
  <rect x="66" y="22" width="120" height="46" rx="4" fill="none" stroke="currentColor" stroke-width="2.5"/>
  <line x1="150" y1="22" x2="150" y2="68" stroke="currentColor" stroke-width="1.5" opacity="0.5"/>
  <line x1="160" y1="22" x2="160" y2="68" stroke="currentColor" stroke-width="1.5" opacity="0.5"/>
  <text x="168" y="16" font-size="9" fill="currentColor" opacity="0.7">Fokusring</text>
  <rect x="84" y="30" width="34" height="18" rx="3" fill="var(--pb-color-primary,#4a90d9)"/>
  <text x="101" y="43" text-anchor="middle" font-size="10" font-weight="bold" fill="#fff">AF·MF</text>
  <path d="M101 52 L101 84" stroke="var(--pb-color-primary,#4a90d9)" stroke-width="2"/>
  <text x="108" y="86" font-size="10" fill="currentColor">Schalter am Objektiv</text>
</svg>`;

/** Bild, das man vergrößern und mit dem Finger verschieben kann. Der
 *  Touchscreen der Box ist Single-Touch und meldet sich als Maus — also kein
 *  Pinch, sondern: antippen = an dieser Stelle vergrößern, ziehen = verschieben,
 *  Knöpfe für + / − / ganzes Bild. */
function zoomViewer(box, img) {
    const st = { scale: 0, cx: 0, cy: 0, fit: true };
    const nat = () => [img.naturalWidth || 1, img.naturalHeight || 1];
    const fitScale = () => {
        const [nw, nh] = nat();
        return Math.min(box.clientWidth / nw, box.clientHeight / nh) || 1;
    };
    img.style.cssText = 'position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;user-select:none;-webkit-user-drag:none;pointer-events:none;';

    function clamp() {
        const [nw, nh] = nat();
        const hw = box.clientWidth / 2 / st.scale, hh = box.clientHeight / 2 / st.scale;
        st.cx = nw <= 2 * hw ? nw / 2 : Math.min(Math.max(st.cx, hw), nw - hw);
        st.cy = nh <= 2 * hh ? nh / 2 : Math.min(Math.max(st.cy, hh), nh - hh);
    }
    function draw() {
        if (st.fit) {
            const [nw, nh] = nat();
            st.scale = fitScale(); st.cx = nw / 2; st.cy = nh / 2;
        }
        clamp();
        const [nw] = nat();
        img.style.width = nw + 'px';
        const tx = box.clientWidth / 2 - st.cx * st.scale;
        const ty = box.clientHeight / 2 - st.cy * st.scale;
        img.style.transform = `translate(${tx}px,${ty}px) scale(${st.scale})`;
        box.dataset.zoom = st.fit ? 'fit' : String(st.scale);
        box.dispatchEvent(new CustomEvent('zoomchange'));
    }
    const toImage = (ev) => {
        const r = box.getBoundingClientRect();
        return [st.cx + (ev.clientX - r.left - box.clientWidth / 2) / st.scale,
                st.cy + (ev.clientY - r.top - box.clientHeight / 2) / st.scale];
    };

    let drag = null;
    box.addEventListener('pointerdown', (ev) => {
        drag = { x: ev.clientX, y: ev.clientY, cx: st.cx, cy: st.cy, moved: false };
        box.setPointerCapture?.(ev.pointerId);
    });
    box.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
        if (drag.moved && !st.fit) {
            st.cx = drag.cx - dx / st.scale; st.cy = drag.cy - dy / st.scale;
            draw();
        }
    });
    box.addEventListener('pointerup', (ev) => {
        const d = drag; drag = null;
        if (!d || d.moved) return;
        // Antippen: ganz → an dieser Stelle groß; groß → dorthin mittig rücken
        const [x, y] = toImage(ev);
        if (st.fit) {
            st.fit = false;
            st.scale = Math.max(1, fitScale() * 3);
        }
        st.cx = x; st.cy = y;
        draw();
    });
    box.addEventListener('pointercancel', () => { drag = null; });

    const api = {
        fit() { st.fit = true; draw(); },
        zoomIn() {
            if (st.fit) { st.fit = false; st.scale = Math.max(1, fitScale() * 3); }
            else st.scale = Math.min(st.scale * 2, 4);
            draw();
        },
        zoomOut() {
            if (st.fit) return;
            st.scale /= 2;
            if (st.scale <= fitScale() * 1.01) st.fit = true;
            draw();
        },
        isFit: () => st.fit,
        redraw: draw,
    };
    img.addEventListener('load', () => draw());
    return api;
}

export function openFocusAssistant({ headers }) {
    const old = document.getElementById('focus-assistant');
    if (old) old.remove();

    const ov = document.createElement('div');
    ov.id = 'focus-assistant';
    ov.style.cssText = `position:fixed;inset:0;z-index:2000;background:var(--pb-color-background,#111);
        color:var(--pb-color-text,#eee);display:flex;flex-direction:column;overflow:auto;`;
    document.body.appendChild(ov);

    let info = { available: false, autofocus: false, zoom: false, server_preview: true, same_camera: true };
    let step = 1;
    let camZoom = 1;          // Kamera-Lupe (eoszoom), 1 = aus
    let zoomKeepAlive = null; // Lupe schaltet sich in der Kamera nach 90 s ab
    let infoPoll = null;
    let photoUrl = null;
    let checkMode = 'live';   // 'live' | 'photo'

    const isDslr = () => info.available === true;
    const steps = () => isDslr()
        ? ['Hinstellen', 'Scharfstellen', 'Festhalten', 'Prüfen']
        : ['Hinstellen', 'Scharfstellen', 'Prüfen'];
    const stepName = () => steps()[step - 1];

    const post = (path, body) => fetch(API + path, {
        method: 'POST', headers, body: JSON.stringify(body || {}),
    });

    async function loadInfo() {
        try {
            const r = await fetch(API + '/info', { headers });
            if (r.ok) info = await r.json();
        } catch {}
    }

    async function setCamZoom(level) {
        if (!info.zoom) return false;
        try {
            const r = await post('/zoom', { level }).then(x => x.json());
            if (!r.ok) return false;
        } catch { return false; }
        camZoom = level;
        clearInterval(zoomKeepAlive);
        zoomKeepAlive = level === 1 ? null
            : setInterval(() => post('/zoom', { level: camZoom }).catch(() => {}), 60000);
        return true;
    }

    function close() {
        clearInterval(zoomKeepAlive); clearInterval(infoPoll);
        if (camZoom !== 1) post('/zoom', { level: 1 }).catch(() => {});
        // Live-Bild abbestellen, sonst hält der offene MJPEG-Strom die Live-View an
        ov.querySelectorAll('img').forEach(i => { i.src = ''; });
        if (photoUrl) URL.revokeObjectURL(photoUrl);
        ov.remove();
        document.removeEventListener('keydown', onKey);
    }
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);

    const btn = (id, label, kind = 'outline', extra = '') =>
        `<button id="${id}" class="admin-btn admin-btn-${kind}" style="font-size:1rem;padding:0.7rem 1.1rem;${extra}">${label}</button>`;
    const muted = 'color:var(--pb-color-text-muted);';

    function liveBox(height = '46vh') {
        if (!info.server_preview) {
            return `<p style="${muted}padding:1rem;">Die Vorschau läuft im Browser (WebRTC) — hier kein Live-Bild. Bitte am Booth-Bildschirm prüfen.</p>`;
        }
        return `<div id="fa-view" style="position:relative;width:100%;height:${height};background:#000;border-radius:10px;overflow:hidden;touch-action:none;cursor:zoom-in;">
                    <img id="fa-img" src="/api/v1/camera/stream?fa=${Date.now()}" alt="Live-Bild">
                    <div style="position:absolute;left:50%;top:50%;width:46px;height:46px;margin:-23px 0 0 -23px;border:2px solid rgba(255,255,255,0.75);border-radius:6px;pointer-events:none;"
                         id="fa-center" title="Hier stellt die Kamera scharf"></div>
                </div>`;
    }

    function stepBody() {
        const name = stepName();
        if (name === 'Hinstellen') {
            return `
                <p style="font-size:1.1rem;line-height:1.5;margin:0 0 0.8rem;">
                    Stell eine Person — oder etwas mit <strong>Schrift oder feinem Muster</strong> —
                    genau dorthin, wo nachher die Gäste stehen, <strong>mitten ins Bild</strong>
                    (in das Kästchen).
                </p>
                ${liveBox()}
                <div style="display:flex;justify-content:flex-end;margin-top:1rem;">${btn('fa-next', 'Weiter ›', 'primary')}</div>`;
        }
        if (name === 'Scharfstellen') {
            const how = isDslr()
                ? `<ol style="font-size:1.05rem;line-height:1.6;margin:0 0 0.8rem;padding-left:1.3rem;">
                       <li>Schalter am Objektiv auf <strong>AF</strong> stellen.</li>
                       <li>${info.autofocus
                           ? '<strong>„Scharfstellen“</strong> tippen — die Kamera stellt auf die Bildmitte scharf (oft mit Piep).'
                           : 'Den <strong>Auslöser an der Kamera halb drücken</strong>, bis es piept.'}</li>
                   </ol>
                   ${info.autofocus ? `<p style="${muted}font-size:0.88rem;margin:-0.3rem 0 0.8rem;">Klappt nicht? Einfach den Auslöser an der Kamera halb drücken — das ist dasselbe.</p>` : ''}`
                : `<p style="font-size:1.05rem;line-height:1.5;margin:0 0 0.8rem;">
                       Webcams stellen meist selbst scharf. Hat deine einen Fokusring, dreh daran,
                       bis das Motiv in der Mitte scharf ist.
                   </p>`;
            return `
                <div style="display:flex;flex-wrap:wrap;gap:1rem;align-items:center;">
                    ${isDslr() ? LENS_SKETCH : ''}
                    <div style="flex:1;min-width:240px;">${how}</div>
                </div>
                ${isDslr() && info.autofocus ? `<div style="display:flex;gap:0.75rem;align-items:center;margin-bottom:0.8rem;">
                    ${btn('fa-af', '🎯 Scharfstellen', 'primary')}
                    <span id="fa-af-msg" style="${muted}"></span></div>` : ''}
                ${liveBox('40vh')}
                <div style="display:flex;justify-content:space-between;margin-top:1rem;">
                    ${btn('fa-back', '‹ Zurück')}${btn('fa-next', 'Weiter ›', 'primary')}</div>`;
        }
        if (name === 'Festhalten') {
            return `
                <div style="display:flex;flex-wrap:wrap;gap:1rem;align-items:center;">
                    ${LENS_SKETCH}
                    <div style="flex:1;min-width:240px;font-size:1.1rem;line-height:1.55;">
                        Jetzt den Schalter am Objektiv auf <strong>MF</strong> stellen.<br>
                        <span style="${muted}font-size:0.95rem;">Dabei nicht am Fokusring drehen. Ab jetzt bleibt
                        die Schärfe den ganzen Abend genau hier — auch wenn niemand in der Mitte steht.</span>
                    </div>
                </div>
                <p id="fa-mf-state" style="font-size:1rem;margin:1rem 0;min-height:1.4em;"></p>
                <div style="display:flex;justify-content:space-between;margin-top:1rem;">
                    ${btn('fa-back', '‹ Zurück')}${btn('fa-next', 'Ist auf MF › Prüfen', 'primary')}</div>`;
        }
        // Prüfen
        const camLupe = info.zoom && info.same_camera;
        return `
            <p style="font-size:1.05rem;line-height:1.5;margin:0 0 0.7rem;">
                Ganz nah ranzoomen: <strong>Augen, Haare oder Schrift</strong> müssen knackscharf sein.
                Ins Bild tippen = dort vergrößern, ziehen = verschieben.
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.7rem;">
                ${btn('fa-mode-live', '🔍 Lupe im Live-Bild', checkMode === 'live' ? 'primary' : 'outline')}
                ${btn('fa-mode-photo', '📷 Testfoto', checkMode === 'photo' ? 'primary' : 'outline')}
            </div>
            ${checkMode === 'live'
                ? `${camLupe ? `<div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;margin-bottom:0.6rem;">
                        <span style="${muted}">Kamera-Lupe (Bildmitte):</span>
                        ${[1, 5, 10].map(l => btn(`fa-cz-${l}`, l === 1 ? 'aus' : `${l}×`, camZoom === l ? 'primary' : 'outline', 'padding:0.5rem 0.9rem;')).join('')}
                    </div>` : ''}
                   ${liveBox('52vh')}`
                : `<div style="display:flex;gap:0.75rem;align-items:center;margin-bottom:0.6rem;">
                        ${btn('fa-shoot', photoUrl ? 'Neues Testfoto' : 'Testfoto machen', 'primary')}
                        <span id="fa-shoot-msg" style="${muted}font-size:0.9rem;">Wird nicht gespeichert, nicht gedruckt.</span>
                   </div>
                   <div id="fa-view" style="position:relative;width:100%;height:52vh;background:#000;border-radius:10px;overflow:hidden;touch-action:none;cursor:zoom-in;">
                        ${photoUrl ? `<img id="fa-img" src="${photoUrl}" alt="Testfoto">`
                                   : `<p style="color:#888;text-align:center;padding-top:20vh;">Noch kein Testfoto</p>`}
                   </div>`}
            <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.6rem;">
                ${btn('fa-zin', '＋ Vergrößern')}${btn('fa-zout', '－ Verkleinern')}${btn('fa-zfit', 'Ganzes Bild')}
            </div>
            <p style="${muted}font-size:0.92rem;margin:0.9rem 0 0;">
                Unscharf? ${isDslr() ? '„Zurück“ zu Scharfstellen, Schalter wieder auf <strong>AF</strong>, erneut scharfstellen.' : 'Zurück zu Scharfstellen.'}
            </p>
            <div style="display:flex;justify-content:space-between;margin-top:1rem;">
                ${btn('fa-back', '‹ Zurück')}${btn('fa-done', '✓ Fertig, ist scharf', 'primary')}</div>`;
    }

    function render() {
        clearInterval(infoPoll); infoPoll = null;
        // Altes Live-Bild sauber beenden, bevor das neue kommt
        ov.querySelectorAll('img').forEach(i => { if (i.src.includes('/camera/stream')) i.src = ''; });
        const names = steps();
        ov.innerHTML = `
            <div style="max-width:900px;width:100%;margin:0 auto;padding:1rem 1rem 2rem;box-sizing:border-box;">
                <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.8rem;">
                    <h2 style="margin:0;flex:1;">Scharfstellen</h2>
                    <button id="fa-close" class="admin-btn admin-btn-outline" style="font-size:1rem;">✕ Schließen</button>
                </div>
                <div style="display:flex;gap:0.4rem;margin-bottom:1.1rem;flex-wrap:wrap;">
                    ${names.map((n, i) => `<span style="padding:0.3rem 0.7rem;border-radius:999px;font-size:0.88rem;
                        border:1px solid ${i + 1 === step ? 'var(--pb-color-primary)' : 'var(--pb-color-border,#333)'};
                        background:${i + 1 === step ? 'var(--pb-color-primary)' : 'transparent'};
                        color:${i + 1 === step ? '#fff' : 'var(--pb-color-text-muted)'};">${i + 1}. ${n}</span>`).join('')}
                </div>
                ${stepBody()}
            </div>`;
        wire();
    }

    function go(delta) {
        step = Math.min(Math.max(step + delta, 1), steps().length);
        // Kamera-Lupe nur in "Prüfen" — beim Scharfstellen soll das ganze Bild zu sehen sein
        if (stepName() !== 'Prüfen' && camZoom !== 1) setCamZoom(1);
        render();
    }

    function wire() {
        const $ = (s) => ov.querySelector(s);
        $('#fa-close')?.addEventListener('click', close);
        $('#fa-next')?.addEventListener('click', () => go(1));
        $('#fa-back')?.addEventListener('click', () => go(-1));
        $('#fa-done')?.addEventListener('click', close);

        const view = $('#fa-view'), img = $('#fa-img');
        let viewer = null;
        if (view && img) {
            viewer = zoomViewer(view, img);
            const center = $('#fa-center');
            view.addEventListener('zoomchange', () => { if (center) center.style.display = viewer.isFit() ? '' : 'none'; });
            // Vor "Prüfen" nur anschauen, nicht zoomen (Tippen soll nichts verstellen)
            if (stepName() !== 'Prüfen') {
                view.style.cursor = 'default';
                view.style.pointerEvents = 'none';
            }
            if (img.complete && img.naturalWidth) viewer.redraw();
        }
        $('#fa-zin')?.addEventListener('click', () => viewer?.zoomIn());
        $('#fa-zout')?.addEventListener('click', () => viewer?.zoomOut());
        $('#fa-zfit')?.addEventListener('click', () => viewer?.fit());

        $('#fa-af')?.addEventListener('click', async () => {
            const b = $('#fa-af'), m = $('#fa-af-msg');
            b.disabled = true; m.textContent = 'Stellt scharf …'; m.style.color = '';
            try {
                const r = await post('/autofocus').then(x => x.json());
                m.textContent = r.ok ? '✓ Fertig — passt das Live-Bild?' : (r.message || r.detail || 'Hat nicht geklappt');
                m.style.color = r.ok ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
            } catch {
                m.textContent = 'Keine Verbindung zur Box'; m.style.color = 'var(--pb-color-error)';
            }
            b.disabled = false;
        });

        if (stepName() === 'Festhalten') {
            const show = async () => {
                await loadInfo();
                const el = $('#fa-mf-state');
                if (!el || !el.isConnected) return;
                if (!info.focus_mode) { el.textContent = ''; return; }
                el.innerHTML = info.manual
                    ? '<span style="color:var(--pb-color-success);">✓ Kamera meldet: manueller Fokus (MF)</span>'
                    : `<span style="color:var(--pb-color-text-muted);">Kamera meldet noch: ${info.focus_mode} — Schalter schon auf MF?</span>`;
            };
            show();
            infoPoll = setInterval(show, 2500);
        }

        [1, 5, 10].forEach(l => $(`#fa-cz-${l}`)?.addEventListener('click', async () => {
            const ok = await setCamZoom(l);
            if (!ok) { const b = $(`#fa-cz-${l}`); if (b) b.textContent = 'geht nicht'; return; }
            render();
        }));
        $('#fa-mode-live')?.addEventListener('click', () => { checkMode = 'live'; render(); });
        $('#fa-mode-photo')?.addEventListener('click', async () => {
            if (camZoom !== 1) await setCamZoom(1);
            checkMode = 'photo'; render();
        });

        $('#fa-shoot')?.addEventListener('click', async () => {
            const b = $('#fa-shoot'), m = $('#fa-shoot-msg');
            b.disabled = true; m.textContent = 'Kamera löst aus …'; m.style.color = '';
            try {
                const r = await fetch(API + '/test-photo', { method: 'POST', headers });
                if (!r.ok) {
                    let d = ''; try { d = (await r.json()).detail; } catch {}
                    throw new Error(d || r.status);
                }
                const blob = await r.blob();
                if (photoUrl) URL.revokeObjectURL(photoUrl);
                photoUrl = URL.createObjectURL(blob);
                render();
            } catch (e) {
                m.textContent = 'Fehler: ' + e.message; m.style.color = 'var(--pb-color-error)';
                b.disabled = false;
            }
        });
    }

    ov.innerHTML = `<p style="padding:2rem;${muted}">Kamera wird gefragt …</p>`;
    loadInfo().then(render);
}
