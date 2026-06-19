import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let printerStatus = {}, printers = [];
    try {
        [printerStatus, printers] = await Promise.all([
            fetch('/api/v1/printer/status').then(r => r.json()),
            fetch('/api/v1/printer/list').then(r => r.json()).then(r => r.printers || []),
        ]);
    } catch {}

    const mode = printerStatus.mode || 'browser';
    const currentPrinter = printerStatus.printer_name || '';

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Drucker-Einstellungen</h1>
        <div style="max-width:650px;">

            <div class="admin-card">
                <h3>Druck-Modus</h3>
                <div style="display:flex;flex-direction:column;gap:0.5rem;">
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                        <input type="radio" name="print_mode" value="browser" ${mode === 'browser' ? 'checked' : ''}>
                        <div>
                            <strong>Browser-Druck</strong><br>
                            <small style="color:var(--pb-color-text-muted);">
                                &Ouml;ffnet den Druckdialog auf dem Client-Ger&auml;t. Funktioniert &uuml;berall.
                            </small>
                        </div>
                    </label>
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                        <input type="radio" name="print_mode" value="server" ${mode === 'server' ? 'checked' : ''}>
                        <div>
                            <strong>Server-Druck</strong><br>
                            <small style="color:var(--pb-color-text-muted);">
                                Druckt direkt &uuml;ber den Server. Drucker muss am Server angeschlossen sein.
                            </small>
                        </div>
                    </label>
                </div>
            </div>

            <div class="admin-card" id="server-settings" style="${mode === 'server' ? '' : 'display:none'}">
                <h3>Drucker</h3>
                ${printers.length
                    ? `<select id="printer-select" class="admin-input" style="width:100%;">
                        <option value="">(Systemstandard)</option>
                        ${printers.map(p => `
                            <option value="${p.name}" ${p.name === currentPrinter ? 'selected' : ''}>
                                ${p.name}${p.default ? ' (Standard)' : ''} — ${p.driver}
                            </option>
                        `).join('')}
                       </select>`
                    : '<p style="color:var(--pb-color-text-muted);">Keine Drucker gefunden</p>'
                }

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem;">
                    <div>
                        <label style="font-size:0.9rem;">Papierformat</label>
                        <select id="paper-size" class="admin-input" style="width:100%;margin-top:0.25rem;">
                            ${['4x6', '10x15', 'A6', 'A5', 'A4', 'Letter', '5x7'].map(s =>
                                `<option value="${s}" ${s === printerStatus.paper_size ? 'selected' : ''}>${s}</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div>
                        <label style="font-size:0.9rem;">Ausrichtung</label>
                        <select id="orientation" class="admin-input" style="width:100%;margin-top:0.25rem;">
                            <option value="portrait" ${printerStatus.orientation === 'portrait' ? 'selected' : ''}>Hochformat</option>
                            <option value="landscape" ${printerStatus.orientation === 'landscape' ? 'selected' : ''}>Querformat</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size:0.9rem;">Kopien</label>
                        <input type="number" id="copies" class="admin-input" value="${printerStatus.copies || 1}" min="1" max="10" style="width:100%;margin-top:0.25rem;">
                    </div>
                    <div>
                        <label style="font-size:0.9rem;">Rand (mm)</label>
                        <input type="number" id="margin" class="admin-input" value="${printerStatus.margin_mm || 0}" min="0" max="50" style="width:100%;margin-top:0.25rem;">
                    </div>
                </div>

                <label style="display:flex;align-items:center;gap:0.5rem;margin-top:1rem;cursor:pointer;">
                    <input type="checkbox" id="fit-to-page" ${printerStatus.fit_to_page !== false ? 'checked' : ''}>
                    An Seitengr&ouml;&szlig;e anpassen
                </label>
            </div>

            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:0.5rem;">
                <button id="btn-save" class="admin-btn admin-btn-primary">Speichern</button>
                <button id="btn-test" class="admin-btn admin-btn-outline">Testdruck</button>
            </div>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>
        </div>
    `);

    setupLogout(container);

    // Toggle server settings
    container.querySelectorAll('input[name="print_mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            document.getElementById('server-settings').style.display = radio.value === 'server' ? '' : 'none';
        });
    });

    // Gutenprint media codes (wWhH in 1/72") -> human-readable cm/inch
    function prettyPaper(name) {
        const m = /^w(\d+)h(\d+)(.*)$/i.exec(name);
        if (!m) return name; // A4, Letter, 10x15 etc. already readable
        const fin = v => (Math.round(v * 10) / 10).toString().replace(/\.0$/, '');
        const win = +m[1] / 72, hin = +m[2] / 72;
        let label = `${Math.round(win * 2.54)}×${Math.round(hin * 2.54)} cm (${fin(win)}×${fin(hin)}″)`;
        const suf = m[3] || '';
        if (suf) label += suf.toLowerCase().includes('div2') ? ' · 2-geteilt' : ` ${suf}`;
        return label;
    }

    // Load real paper sizes for the selected printer (CUPS/Windows)
    async function loadPaperSizes(printerName) {
        const sel = container.querySelector('#paper-size');
        if (!sel) return;
        let data = { sizes: [], default: null };
        try {
            data = await fetch(`/api/v1/printer/paper-sizes?printer=${encodeURIComponent(printerName || '')}`).then(r => r.json());
        } catch {}
        if (data.sizes && data.sizes.length) {
            const want = sel.value || printerStatus.paper_size;
            const chosen = data.sizes.includes(want) ? want : (data.default || data.sizes[0]);
            sel.innerHTML = data.sizes.map(s => `<option value="${s}" ${s === chosen ? 'selected' : ''}>${prettyPaper(s)}</option>`).join('');
        }
    }
    if (mode === 'server' && currentPrinter) loadPaperSizes(currentPrinter);
    container.querySelector('#printer-select')?.addEventListener('change', (e) => loadPaperSizes(e.target.value));

    // Save
    container.querySelector('#btn-save')?.addEventListener('click', async () => {
        const msg = container.querySelector('#msg');
        const selectedMode = container.querySelector('input[name="print_mode"]:checked')?.value;

        const payload = {
            enabled: true,
            mode: selectedMode,
        };

        if (selectedMode === 'server') {
            payload.printer_name = container.querySelector('#printer-select')?.value || '';
            payload.paper_size = container.querySelector('#paper-size').value;
            payload.orientation = container.querySelector('#orientation').value;
            payload.copies = parseInt(container.querySelector('#copies').value) || 1;
            payload.margin_mm = parseInt(container.querySelector('#margin').value) || 0;
            payload.fit_to_page = container.querySelector('#fit-to-page').checked;
        }

        try {
            const res = await fetch('/api/v1/printer/configure', {
                method: 'POST', headers, body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error((await res.json()).detail);
            msg.textContent = 'Gespeichert!';
            msg.style.color = 'var(--pb-color-success)';
        } catch (err) {
            msg.textContent = 'Fehler: ' + err.message;
            msg.style.color = 'var(--pb-color-error)';
        }
    });

    // Test print
    container.querySelector('#btn-test')?.addEventListener('click', async () => {
        const msg = container.querySelector('#msg');
        msg.textContent = 'Testdruck wird gesendet...';
        msg.style.color = 'var(--pb-color-text-muted)';

        try {
            const res = await fetch('/api/v1/printer/test', { method: 'POST', headers });
            const result = await res.json();

            if (result.print_mode === 'browser') {
                // Open print dialog for test
                const printWin = window.open('', '_blank');
                if (printWin) {
                    printWin.document.write(`<html><head><title>Testdruck</title>
                        <style>@page{margin:0}body{margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fff;}
                        div{text-align:center;font-family:sans-serif;}</style></head>
                        <body><div><h1>Photobox Testdruck</h1><p>Drucker funktioniert!</p><p>${new Date().toLocaleString()}</p></div>
                        <script>window.print();setTimeout(()=>window.close(),2000)</script></body></html>`);
                    printWin.document.close();
                }
                msg.textContent = 'Druckdialog geöffnet';
                msg.style.color = 'var(--pb-color-success)';
            } else if (result.status === 'ok') {
                msg.textContent = `Gedruckt auf: ${result.printer}`;
                msg.style.color = 'var(--pb-color-success)';
            } else {
                throw new Error(result.message || 'Drucken fehlgeschlagen');
            }
        } catch (err) {
            msg.textContent = 'Fehler: ' + err.message;
            msg.style.color = 'var(--pb-color-error)';
        }
    });
}
