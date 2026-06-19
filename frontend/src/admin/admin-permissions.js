import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let data = { all: [], granted: [] };
    try {
        data = await fetch('/api/v1/auth/mieter-sections', { headers }).then(r => r.json());
    } catch {}

    const granted = new Set(data.granted || []);

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Mieter-Rechte</h1>
        <div style="max-width:620px;">
            <div class="admin-card">
                <h3>🔑 Welche Bereiche darf der Mieter sehen?</h3>
                <p style="font-size:0.88rem;color:var(--pb-color-text-muted);margin-bottom:1rem;">
                    Der Login „Mieter" sieht nur die hier aktivierten Bereiche. Sensible Bereiche
                    (Module, Auslöser, Bezahlung, Einstellungen, Herunterfahren) bleiben dem Admin vorbehalten.
                </p>
                <div style="display:flex;flex-direction:column;gap:0.1rem;">
                    ${(data.all || []).map(s => `
                        <label style="display:flex;align-items:center;gap:0.7rem;padding:0.6rem 0.5rem;border-radius:8px;cursor:pointer;border-bottom:1px solid var(--pb-color-border);">
                            <input type="checkbox" class="sec-cb" value="${s.key}" ${granted.has(s.key) ? 'checked' : ''}
                                ${s.key === 'dashboard' ? 'checked disabled' : ''}>
                            <span>${s.label}</span>
                            ${s.key === 'dashboard' ? '<span style="font-size:0.78rem;color:var(--pb-color-text-muted);">(immer)</span>' : ''}
                        </label>`).join('')}
                </div>
                <button id="btn-save" class="admin-btn admin-btn-primary" style="margin-top:1rem;">Speichern</button>
                <p id="msg" style="margin-top:0.6rem;font-size:0.9rem;"></p>
            </div>

            <div class="admin-card">
                <h3>Mieter-Passwort ändern</h3>
                <p style="font-size:0.88rem;color:var(--pb-color-text-muted);margin-bottom:0.5rem;">
                    Login-Konto „Mieter". Leer lassen, um es nicht zu ändern.
                </p>
                <input id="m-pass" type="password" class="admin-input" style="width:100%;" placeholder="Neues Mieter-Passwort">
                <button id="btn-pass" class="admin-btn admin-btn-outline" style="margin-top:0.75rem;">Passwort setzen</button>
                <p id="pmsg" style="margin-top:0.5rem;font-size:0.9rem;"></p>
            </div>
        </div>
    `);
    setupLogout(container);

    const setMsg = (id, t, k) => {
        const m = container.querySelector(id);
        m.textContent = t;
        m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    };

    container.querySelector('#btn-save')?.addEventListener('click', async () => {
        const sections = [...container.querySelectorAll('.sec-cb')].filter(c => c.checked).map(c => c.value);
        setMsg('#msg', 'Speichere…');
        try {
            const res = await fetch('/api/v1/auth/mieter-sections', {
                method: 'PUT', headers, body: JSON.stringify({ sections }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
            setMsg('#msg', 'Gespeichert! Der Mieter sieht beim nächsten Login nur diese Bereiche.', 'ok');
        } catch (err) { setMsg('#msg', 'Fehler: ' + err.message, 'error'); }
    });

    container.querySelector('#btn-pass')?.addEventListener('click', async () => {
        const pass = container.querySelector('#m-pass').value;
        if (!pass) { setMsg('#pmsg', 'Bitte ein Passwort eingeben.', 'error'); return; }
        setMsg('#pmsg', 'Setze Passwort…');
        try {
            // find the mieter user id, then update its password
            const users = await fetch('/api/v1/users/', { headers }).then(r => r.json());
            const mieter = (users || []).find(u => u.username === 'mieter');
            if (!mieter) throw new Error('Mieter-Konto nicht gefunden');
            const res = await fetch(`/api/v1/users/${mieter.id}`, {
                method: 'PUT', headers, body: JSON.stringify({ password: pass }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
            container.querySelector('#m-pass').value = '';
            setMsg('#pmsg', 'Mieter-Passwort geändert.', 'ok');
        } catch (err) { setMsg('#pmsg', 'Fehler: ' + err.message, 'error'); }
    });
}
