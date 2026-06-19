import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let settings = {};
    let modules = {};
    try {
        [settings, modules] = await Promise.all([
            fetch('/api/v1/settings/', { headers }).then(r => r.json()),
            fetch('/api/v1/modules', { headers }).then(r => r.json()),
        ]);
    } catch {}

    const pay = settings?.payment || {};
    const prices = pay.prices || {};
    const paymentModules = modules.payments || [];

    const inputStyle = `padding:0.6rem;border-radius:6px;border:1px solid #333;
        background:#0e1a30;color:white;font-size:0.9rem;width:100px;`;
    const selectStyle = `padding:0.75rem 1rem;border-radius:8px;border:1px solid #333;
        background:var(--pb-color-surface);color:var(--pb-color-text);
        font-size:1rem;width:100%;max-width:300px;cursor:pointer;`;

    // Known payment modules with labels
    const knownModules = [
        { id: 'sumup_qr', label: 'SumUp QR-Code' },
        { id: 'sumup_terminal', label: 'SumUp Terminal' },
        { id: 'stripe_qr', label: 'Stripe QR-Code' },
        { id: 'mdb', label: 'Münzprüfer (MDB)' },
    ];

    // Price action labels
    const priceActions = [
        { key: 'capture', label: 'Foto aufnehmen' },
        { key: 'print', label: 'Foto drucken' },
        { key: 'gif', label: 'GIF erstellen' },
        { key: 'collage', label: 'Collage erstellen' },
    ];

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Bezahlung</h1>
        <div style="max-width:700px;">

            <!-- Grundeinstellungen -->
            <div class="admin-card">
                <h3>Grundeinstellungen</h3>
                <div style="margin-top:1rem;display:flex;flex-direction:column;gap:1rem;">
                    <label style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;">
                        <input type="checkbox" id="pay-enabled" ${pay.enabled ? 'checked' : ''}
                            style="width:20px;height:20px;accent-color:var(--pb-color-primary);cursor:pointer;">
                        <span>Bezahlung aktiviert</span>
                    </label>
                    <label style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;">
                        <input type="checkbox" id="pay-required" ${pay.required_before_capture ? 'checked' : ''}
                            style="width:20px;height:20px;accent-color:var(--pb-color-primary);cursor:pointer;">
                        <span>Bezahlung vor Foto-Aufnahme erforderlich</span>
                    </label>
                    <div>
                        <label style="display:block;margin-bottom:0.5rem;font-weight:500;">Währung</label>
                        <input type="text" id="pay-currency" value="${pay.currency || 'EUR'}"
                            style="${inputStyle}" maxlength="3" placeholder="EUR">
                    </div>
                </div>
            </div>

            <!-- Zahlungsmodul auswählen -->
            <div class="admin-card">
                <h3>Zahlungsmodul</h3>
                <div style="margin-top:1rem;display:flex;flex-direction:column;gap:1rem;">
                    ${knownModules.map(m => {
                        const conf = pay[m.id] || {};
                        const loaded = paymentModules.find(p => p.id === 'payment.' + m.id);
                        const statusDot = loaded
                            ? `<span style="color:var(--pb-color-success)">&#10003;</span>`
                            : `<span style="color:var(--pb-color-text-muted)">&#8226;</span>`;
                        return `
                        <div style="background:#0a0e1a;border-radius:8px;padding:1rem;">
                            <label style="display:flex;align-items:center;gap:0.75rem;cursor:pointer;">
                                <input type="checkbox" class="mod-enabled" data-module="${m.id}"
                                    ${conf.enabled ? 'checked' : ''}
                                    style="width:18px;height:18px;accent-color:var(--pb-color-primary);cursor:pointer;">
                                <span style="font-weight:500;">${statusDot} ${m.label}</span>
                                ${loaded ? '<span style="font-size:0.75rem;color:var(--pb-color-success);margin-left:auto;">geladen</span>' : ''}
                            </label>
                            <div class="mod-config" data-module="${m.id}"
                                style="margin-top:0.75rem;display:${conf.enabled ? 'flex' : 'none'};flex-direction:column;gap:0.5rem;padding-left:2.5rem;">
                                ${renderModuleConfig(m.id, conf)}
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>

            <!-- Preise pro Aktion -->
            <div class="admin-card">
                <h3>Preise pro Aktion</h3>
                <p style="margin-bottom:1rem;">Preise in Cent. Setze 0, um eine Aktion kostenlos zu lassen.</p>
                <div style="display:flex;flex-direction:column;gap:0.75rem;">
                    ${priceActions.map(a => `
                        <div style="display:flex;align-items:center;gap:1rem;">
                            <label style="width:160px;font-weight:500;">${a.label}</label>
                            <input type="number" class="price-input" data-action="${a.key}"
                                value="${prices[a.key] ?? 200}" min="0" step="10"
                                style="${inputStyle}">
                            <span style="font-size:0.85rem;color:var(--pb-color-text-muted);">Cent</span>
                            <span style="font-size:0.85rem;color:var(--pb-color-text-muted);">=
                                <span class="price-euro" data-action="${a.key}">
                                    ${((prices[a.key] ?? 200) / 100).toFixed(2)}
                                </span> ${pay.currency || 'EUR'}
                            </span>
                        </div>
                    `).join('')}
                </div>
            </div>

            <button id="btn-save-payment" class="admin-btn admin-btn-primary"
                style="margin-top:0.5rem;padding:0.75rem 2rem;font-size:1rem;">
                Einstellungen speichern
            </button>
            <span id="save-status" style="margin-left:0.75rem;font-size:0.85rem;display:none;"></span>
        </div>
    `);

    setupLogout(container);

    // Toggle module config visibility
    container.querySelectorAll('.mod-enabled').forEach(cb => {
        cb.addEventListener('change', () => {
            const cfg = container.querySelector(`.mod-config[data-module="${cb.dataset.module}"]`);
            cfg.style.display = cb.checked ? 'flex' : 'none';
        });
    });

    // Live euro preview for prices
    container.querySelectorAll('.price-input').forEach(inp => {
        inp.addEventListener('input', () => {
            const euro = container.querySelector(`.price-euro[data-action="${inp.dataset.action}"]`);
            euro.textContent = ((parseInt(inp.value) || 0) / 100).toFixed(2);
        });
    });

    // Save
    container.querySelector('#btn-save-payment')?.addEventListener('click', async () => {
        const status = container.querySelector('#save-status');
        const saves = [
            { key: 'payment.enabled', value: container.querySelector('#pay-enabled').checked },
            { key: 'payment.required_before_capture', value: container.querySelector('#pay-required').checked },
            { key: 'payment.currency', value: container.querySelector('#pay-currency').value.toUpperCase() },
        ];

        // Prices
        container.querySelectorAll('.price-input').forEach(inp => {
            saves.push({
                key: `payment.prices.${inp.dataset.action}`,
                value: parseInt(inp.value) || 0,
            });
        });

        // Module configs
        for (const m of knownModules) {
            const enabled = container.querySelector(`.mod-enabled[data-module="${m.id}"]`).checked;
            saves.push({ key: `payment.${m.id}.enabled`, value: enabled });

            const cfgDiv = container.querySelector(`.mod-config[data-module="${m.id}"]`);
            cfgDiv.querySelectorAll('[data-field]').forEach(el => {
                const val = el.type === 'number' ? (parseInt(el.value) || 0) : el.value;
                saves.push({ key: `payment.${m.id}.${el.dataset.field}`, value: val });
            });
        }

        try {
            const results = await Promise.all(saves.map(s =>
                fetch(`/api/v1/settings/${s.key}`, {
                    method: 'PUT', headers,
                    body: JSON.stringify({ key: s.key, value: s.value }),
                })
            ));
            const allOk = results.every(r => r.ok);
            status.style.display = 'inline';
            status.textContent = allOk ? 'Gespeichert!' : 'Teilweise fehlgeschlagen';
            status.style.color = allOk ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
            setTimeout(() => { status.style.display = 'none'; }, 2500);
        } catch (err) {
            status.style.display = 'inline';
            status.textContent = `Fehler (${err.message || 'Netzwerk'})`;
            status.style.color = 'var(--pb-color-error)';
        }
    });
}

function renderModuleConfig(moduleId, conf) {
    const fieldStyle = `padding:0.5rem;border-radius:6px;border:1px solid #333;
        background:#0e1a30;color:white;font-size:0.85rem;width:100%;max-width:280px;`;

    switch (moduleId) {
        case 'sumup_qr':
            return `
                <label>API-Key
                    <input type="text" data-field="api_key" value="${conf.api_key || ''}"
                        style="${fieldStyle}" placeholder="sup_sk_...">
                </label>
                <label>Merchant Code
                    <input type="text" data-field="merchant_code" value="${conf.merchant_code || ''}"
                        style="${fieldStyle}" placeholder="MXXXXXXX">
                </label>`;
        case 'sumup_terminal':
            return `
                <label>API-Key
                    <input type="text" data-field="api_key" value="${conf.api_key || ''}"
                        style="${fieldStyle}" placeholder="sup_sk_...">
                </label>
                <label>Merchant Code
                    <input type="text" data-field="merchant_code" value="${conf.merchant_code || ''}"
                        style="${fieldStyle}" placeholder="MXXXXXXX">
                </label>
                <label>Terminal-ID
                    <input type="text" data-field="terminal_id" value="${conf.terminal_id || ''}"
                        style="${fieldStyle}" placeholder="T12345678">
                </label>`;
        case 'stripe_qr':
            return `
                <label>API-Key
                    <input type="text" data-field="api_key" value="${conf.api_key || ''}"
                        style="${fieldStyle}" placeholder="sk_live_...">
                </label>`;
        case 'mdb':
            return `
                <label>Serieller Port
                    <input type="text" data-field="serial_port" value="${conf.serial_port || '/dev/ttyUSB1'}"
                        style="${fieldStyle}">
                </label>
                <label>Baudrate
                    <input type="number" data-field="baud" value="${conf.baud || 9600}"
                        style="${fieldStyle}">
                </label>`;
        default:
            return '';
    }
}
