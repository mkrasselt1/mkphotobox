import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let events = [];
    try {
        events = await fetch('/api/v1/events/', { headers }).then(r => r.json());
    } catch {}

    container.innerHTML = adminShell(`
        <div style="max-width:600px;display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;gap:1rem;">
            <h1 style="margin:0;">Veranstaltungen</h1>
            <button class="admin-btn admin-btn-primary btn-new">+ Neue Veranstaltung</button>
        </div>
        <div style="max-width:600px;">
            ${events.map(e => `
                <div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;">
                    <div>
                        <strong>${e.name}</strong>
                        <small style="color:var(--pb-color-text-muted);margin-left:0.5rem;">(${e.slug})</small>
                        ${e.is_active ? '<span style="color:var(--pb-color-success);margin-left:0.5rem;">&#9679; aktiv</span>' : ''}
                        ${locationLine(e)}
                    </div>
                    <div style="display:flex;gap:0.5rem;">
                        ${!e.is_active ? `<button class="admin-btn admin-btn-outline btn-activate" data-slug="${e.slug}">Aktivieren</button>` : ''}
                        <button class="admin-btn admin-btn-outline btn-edit" data-slug="${e.slug}">Bearbeiten</button>
                        <button class="admin-btn admin-btn-outline btn-delete" data-slug="${e.slug}" data-name="${e.name}"
                            style="color:var(--pb-color-error);border-color:var(--pb-color-error);">Löschen</button>
                    </div>
                </div>
            `).join('') || '<div class="admin-card"><p>Keine Veranstaltungen</p></div>'}
        </div>
        <div id="evt-modal"></div>
    `);

    setupLogout(container);

    container.querySelector('.btn-new').addEventListener('click', () => openEventDialog(null));

    container.querySelectorAll('.btn-activate').forEach(btn => {
        btn.addEventListener('click', async () => {
            await fetch(`/api/v1/events/${btn.dataset.slug}/activate`, { method: 'POST', headers });
            render(container, state);
        });
    });

    container.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', () => {
            openEventDialog(events.find(e => e.slug === btn.dataset.slug) || null);
        });
    });

    container.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', () => openDeleteDialog(btn.dataset.slug, btn.dataset.name));
    });

    /** FastAPI's `detail` is a string for our errors but a list for 422s. */
    function errText(r) {
        const d = r && r.detail;
        if (!d) return 'Fehler';
        if (typeof d === 'string') return d;
        return d.map(x => x.msg || JSON.stringify(x)).join('; ');
    }

    function slugify(s) {
        return s.toLowerCase().trim()
            .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
            .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    }

    /** Second line under an event name: venue and/or coordinates, if set. */
    function locationLine(e) {
        const bits = [];
        if (e.location_name) bits.push(e.location_name);
        if (e.latitude != null && e.longitude != null) {
            bits.push(`${Number(e.latitude).toFixed(5)}, ${Number(e.longitude).toFixed(5)}`);
        }
        if (!bits.length) return '';
        return `<div style="font-size:0.8rem;color:var(--pb-color-text-muted);margin-top:0.2rem;">&#128205; ${bits.join(' · ')}</div>`;
    }

    /** Create (evt === null) or edit an event, including its EXIF location. */
    function openEventDialog(evt) {
        const isNew = !evt;
        const modal = container.querySelector('#evt-modal');
        const field = 'width:100%;box-sizing:border-box;padding:0.6rem 0.75rem;border-radius:8px;border:1px solid var(--pb-color-border,#2a3a5e);background:var(--pb-color-bg,#0f1729);color:inherit;font-size:1rem;';
        const label = 'display:block;margin-bottom:0.35rem;font-size:0.9rem;color:var(--pb-color-text-muted);';
        const val = v => (v == null ? '' : String(v).replace(/"/g, '&quot;'));

        modal.innerHTML = `
        <div style="position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;padding:1.5rem;overflow:auto;">
            <div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:480px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
                <h2 style="margin:0 0 1rem;">${isNew ? 'Neue Veranstaltung' : 'Veranstaltung bearbeiten'}</h2>
                <label style="display:block;margin-bottom:1rem;">
                    <span style="${label}">Name</span>
                    <input id="evt-name" type="text" placeholder="z. B. Hochzeit Müller" value="${val(evt && evt.name)}" style="${field}">
                </label>
                ${isNew ? `
                <label style="display:block;margin-bottom:1rem;">
                    <span style="${label}">Kurzname (Slug)</span>
                    <input id="evt-slug" type="text" placeholder="hochzeit-mueller" style="${field}">
                    <span style="display:block;margin-top:0.35rem;font-size:0.78rem;color:var(--pb-color-text-muted);">Nur Kleinbuchstaben, Ziffern und Bindestriche.</span>
                </label>` : ''}

                <fieldset style="border:1px solid var(--pb-color-border,#2a3a5e);border-radius:10px;padding:0.9rem 1rem 1rem;margin:0 0 1.25rem;">
                    <legend style="padding:0 0.4rem;font-size:0.9rem;color:var(--pb-color-text-muted);">Standort</legend>
                    <p style="margin:0 0 0.8rem;font-size:0.78rem;color:var(--pb-color-text-muted);">
                        Wird zusammen mit den Veranstaltungs- und Kameradaten in die EXIF-Informationen
                        jedes Fotos, jeder Collage und jedes GIFs geschrieben.
                    </p>
                    <label style="display:block;margin-bottom:0.8rem;">
                        <span style="${label}">Ortsbezeichnung</span>
                        <input id="evt-loc" type="text" placeholder="z. B. Schlosspark Pillnitz" value="${val(evt && evt.location_name)}" style="${field}">
                    </label>
                    <div style="display:flex;gap:0.6rem;margin-bottom:0.8rem;">
                        <label style="flex:1;">
                            <span style="${label}">Breitengrad</span>
                            <input id="evt-lat" type="text" inputmode="decimal" placeholder="51.009600" value="${val(evt && evt.latitude)}" style="${field}">
                        </label>
                        <label style="flex:1;">
                            <span style="${label}">Längengrad</span>
                            <input id="evt-lon" type="text" inputmode="decimal" placeholder="13.870300" value="${val(evt && evt.longitude)}" style="${field}">
                        </label>
                        <label style="width:6.5rem;">
                            <span style="${label}">Höhe (m)</span>
                            <input id="evt-alt" type="text" inputmode="decimal" placeholder="118" value="${val(evt && evt.altitude)}" style="${field}">
                        </label>
                    </div>
                    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                        <button id="evt-here" type="button" class="admin-btn admin-btn-outline">&#128205; Standort dieses Geräts</button>
                        <button id="evt-clear" type="button" class="admin-btn admin-btn-outline">Koordinaten löschen</button>
                    </div>
                    <span style="display:block;margin-top:0.5rem;font-size:0.78rem;color:var(--pb-color-text-muted);">
                        Ein Koordinatenpaar („51.0096, 13.8703") kann auch direkt ins Feld „Breitengrad" eingefügt werden.
                    </span>
                </fieldset>

                ${isNew ? `
                <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;margin-bottom:1.25rem;">
                    <input type="checkbox" id="evt-activate" checked style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Sofort aktivieren
                </label>` : ''}
                <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
                    <button id="evt-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                    <button id="evt-confirm" class="admin-btn admin-btn-primary">${isNew ? 'Anlegen' : 'Speichern'}</button>
                </div>
                <p id="evt-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
            </div>
        </div>`;

        const close = () => { modal.innerHTML = ''; };
        const q = sel => modal.querySelector(sel);
        const nameInput = q('#evt-name');
        const latInput = q('#evt-lat');
        const lonInput = q('#evt-lon');
        const altInput = q('#evt-alt');
        const msg = q('#evt-msg');

        if (isNew) {
            const slugInput = q('#evt-slug');
            let slugEdited = false;
            nameInput.addEventListener('input', () => {
                if (!slugEdited) slugInput.value = slugify(nameInput.value);
            });
            slugInput.addEventListener('input', () => {
                slugEdited = slugInput.value.trim() !== '';
                slugInput.value = slugify(slugInput.value);
            });
        }
        nameInput.focus();

        // "51.0096, 13.8703" pasted into the latitude field fills both fields.
        latInput.addEventListener('input', () => {
            const m = latInput.value.match(/^\s*(-?\d+[.,]?\d*)\s*[,;\s]\s*(-?\d+[.,]?\d*)\s*$/);
            if (m) {
                latInput.value = m[1].replace(',', '.');
                lonInput.value = m[2].replace(',', '.');
            }
        });

        q('#evt-clear').addEventListener('click', () => {
            latInput.value = ''; lonInput.value = ''; altInput.value = '';
        });

        q('#evt-here').addEventListener('click', () => {
            if (!navigator.geolocation) {
                msg.textContent = 'Dieses Gerät kennt keinen Standort.';
                msg.style.color = 'var(--pb-color-error)';
                return;
            }
            msg.textContent = 'Ermittle Standort…'; msg.style.color = 'var(--pb-color-text-muted)';
            navigator.geolocation.getCurrentPosition(pos => {
                latInput.value = pos.coords.latitude.toFixed(6);
                lonInput.value = pos.coords.longitude.toFixed(6);
                if (pos.coords.altitude != null) altInput.value = pos.coords.altitude.toFixed(1);
                msg.textContent = `Standort übernommen (±${Math.round(pos.coords.accuracy)} m).`;
                msg.style.color = 'var(--pb-color-success)';
            }, err => {
                msg.textContent = 'Standort nicht verfügbar: ' + err.message
                    + ' (Browser erlauben Ortung meist nur über HTTPS oder localhost.)';
                msg.style.color = 'var(--pb-color-error)';
            }, { enableHighAccuracy: true, timeout: 10000 });
        });

        q('#evt-cancel').addEventListener('click', close);

        /** '' -> null, otherwise a number; throws on garbage. */
        function num(input, fieldName, min, max) {
            const raw = input.value.trim().replace(',', '.');
            if (!raw) return null;
            const n = Number(raw);
            if (!Number.isFinite(n)) throw new Error(`${fieldName} ist keine Zahl.`);
            if (min != null && (n < min || n > max)) {
                throw new Error(`${fieldName} muss zwischen ${min} und ${max} liegen.`);
            }
            return n;
        }

        q('#evt-confirm').addEventListener('click', async () => {
            const name = nameInput.value.trim();
            if (!name) { msg.textContent = 'Bitte einen Namen eingeben.'; msg.style.color = 'var(--pb-color-error)'; return; }

            let payload;
            try {
                payload = {
                    name,
                    location_name: q('#evt-loc').value.trim() || null,
                    latitude: num(latInput, 'Breitengrad', -90, 90),
                    longitude: num(lonInput, 'Längengrad', -180, 180),
                    altitude: num(altInput, 'Höhe'),
                };
            } catch (err) {
                msg.textContent = err.message; msg.style.color = 'var(--pb-color-error)';
                return;
            }
            if ((payload.latitude == null) !== (payload.longitude == null)) {
                msg.textContent = 'Bitte Breiten- und Längengrad gemeinsam angeben.';
                msg.style.color = 'var(--pb-color-error)';
                return;
            }

            msg.textContent = isNew ? 'Lege an…' : 'Speichere…';
            msg.style.color = 'var(--pb-color-text-muted)';
            try {
                let res;
                if (isNew) {
                    const slug = q('#evt-slug').value.trim() || slugify(name);
                    if (!slug) throw new Error('Bitte einen gültigen Kurznamen eingeben.');
                    res = await fetch('/api/v1/events/', {
                        method: 'POST', headers, body: JSON.stringify({ ...payload, slug }),
                    });
                    const r = await res.json();
                    if (!res.ok) throw new Error(errText(r));
                    if (q('#evt-activate').checked) {
                        await fetch(`/api/v1/events/${slug}/activate`, { method: 'POST', headers });
                    }
                } else {
                    res = await fetch(`/api/v1/events/${evt.slug}`, {
                        method: 'PUT', headers, body: JSON.stringify(payload),
                    });
                    const r = await res.json();
                    if (!res.ok) throw new Error(errText(r));
                }
                close();
                render(container, state);
            } catch (err) {
                msg.textContent = 'Fehler: ' + err.message; msg.style.color = 'var(--pb-color-error)';
            }
        });
    }

    function openDeleteDialog(slug, name) {
        const modal = container.querySelector('#evt-modal');
        modal.innerHTML = `
        <div style="position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;padding:1.5rem;">
            <div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:480px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
                <h2 style="margin:0 0 0.5rem;">„${name}" löschen?</h2>
                <p style="color:var(--pb-color-text-muted);margin:0 0 1rem;font-size:0.9rem;">
                    Die Veranstaltung wird entfernt. Wähle, was zusätzlich gelöscht werden soll:
                </p>
                <div style="display:flex;flex-direction:column;gap:0.7rem;margin-bottom:1.25rem;">
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-photos" checked style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Fotos (Bilder + Thumbnails)
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-gifs" checked style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> GIFs
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-templates" style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Zugewiesene Vorlagen
                    </label>
                    <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;">
                        <input type="checkbox" id="del-assets" style="width:18px;height:18px;accent-color:var(--pb-color-primary);"> Rahmen/Muster (nur ungenutzte)
                    </label>
                    <p style="font-size:0.78rem;color:var(--pb-color-text-muted);margin:0;">
                        Rahmen/Muster werden nur entfernt, wenn keine andere Vorlage sie noch verwendet.
                    </p>
                </div>
                <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
                    <button id="del-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                    <button id="del-confirm" class="admin-btn admin-btn-primary" style="background:var(--pb-color-error);">Endgültig löschen</button>
                </div>
                <p id="del-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
            </div>
        </div>`;

        const close = () => { modal.innerHTML = ''; };
        modal.querySelector('#del-cancel').addEventListener('click', close);

        modal.querySelector('#del-confirm').addEventListener('click', async () => {
            const payload = {
                photos: modal.querySelector('#del-photos').checked,
                gifs: modal.querySelector('#del-gifs').checked,
                templates: modal.querySelector('#del-templates').checked,
                assets: modal.querySelector('#del-assets').checked,
            };
            const msg = modal.querySelector('#del-msg');
            msg.textContent = 'Lösche…'; msg.style.color = 'var(--pb-color-text-muted)';
            try {
                const res = await fetch(`/api/v1/events/${slug}`, {
                    method: 'DELETE', headers, body: JSON.stringify(payload),
                });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                close();
                render(container, state);
            } catch (err) {
                msg.textContent = 'Fehler: ' + err.message; msg.style.color = 'var(--pb-color-error)';
            }
        });
    }
}
