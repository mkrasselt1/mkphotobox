import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    // Load test list
    let tests = [];
    try {
        const resp = await fetch('/api/v1/tests/', { headers });
        tests = await resp.json();
    } catch (e) {
        console.error('Failed to load tests:', e);
    }

    // Split into auto and manual, then group by category
    const autoTests = tests.filter(t => !t.manual);
    const manualTests = tests.filter(t => t.manual);

    function groupByCategory(list) {
        const cats = {};
        for (const t of list) {
            if (!cats[t.category]) cats[t.category] = [];
            cats[t.category].push(t);
        }
        return cats;
    }

    const autoCategories = groupByCategory(autoTests);
    const manualCategories = groupByCategory(manualTests);

    function renderTestRows(catTests) {
        return catTests.map(t => `
            <div class="test-row" data-test-id="${t.id}"
                 style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0.75rem;border-radius:6px;background:rgba(255,255,255,0.03);">
                <span class="test-status" style="font-size:1.2rem;width:24px;text-align:center;">&#9679;</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:0.9rem;font-weight:500;">${t.name}</div>
                    <div style="font-size:0.8rem;color:var(--pb-color-text-muted);">${t.description}</div>
                    <div class="test-message" style="font-size:0.8rem;margin-top:2px;display:none;"></div>
                </div>
                <span class="test-duration" style="font-size:0.8rem;color:var(--pb-color-text-muted);min-width:60px;text-align:right;"></span>
                <button class="admin-btn admin-btn-outline btn-run-single" data-test-id="${t.id}"
                        style="padding:0.3rem 0.7rem;font-size:0.8rem;">
                    Start
                </button>
            </div>
        `).join('');
    }

    function renderCategoryCards(categories) {
        return Object.entries(categories).map(([cat, catTests]) => `
            <div class="admin-card" style="margin-bottom:1rem;">
                <h3>${cat}</h3>
                <div style="display:flex;flex-direction:column;gap:0.5rem;">
                    ${renderTestRows(catTests)}
                </div>
            </div>
        `).join('');
    }

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1rem;">Integrationstests</h1>
        <p style="color:var(--pb-color-text-muted);margin-bottom:1.5rem;">
            Echte Tests gegen die laufende Anwendung &mdash; keine Mocks, keine Stubs.
        </p>

        <!-- Automatische Tests -->
        <div style="display:flex;gap:0.75rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center;">
            <button id="btn-run-all" class="admin-btn admin-btn-primary">
                Alle automatischen Tests
            </button>
            <span id="summary" style="font-size:0.9rem;color:var(--pb-color-text-muted);"></span>
        </div>

        <div id="auto-tests">
            ${renderCategoryCards(autoCategories)}
        </div>

        <!-- Manuelle Tests -->
        ${Object.keys(manualCategories).length > 0 ? `
            <div style="margin-top:2rem;margin-bottom:1rem;padding-top:1.5rem;border-top:1px solid rgba(255,255,255,0.1);">
                <h2 style="font-size:1.1rem;margin-bottom:0.25rem;">Manuelle Tests</h2>
                <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:1rem;">
                    Diese Tests brauchen Hardware (Kamera, Drucker, USB...) und m&uuml;ssen einzeln gestartet werden.
                </p>
            </div>
            <div id="manual-tests">
                ${renderCategoryCards(manualCategories)}
            </div>
        ` : ''}

        <style>
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        </style>
    `);

    setupLogout(container);

    const summaryEl = container.querySelector('#summary');

    function setTestStatus(testId, status, message, durationMs, detail) {
        const row = container.querySelector(`.test-row[data-test-id="${testId}"]`);
        if (!row) return;
        const statusEl = row.querySelector('.test-status');
        const msgEl = row.querySelector('.test-message');
        const durEl = row.querySelector('.test-duration');

        if (status === 'running') {
            statusEl.innerHTML = '<span style="animation:spin 1s linear infinite;display:inline-block;">&#8635;</span>';
            statusEl.style.color = 'var(--pb-color-primary)';
            msgEl.style.display = 'none';
            durEl.textContent = '';
        } else if (status === 'passed') {
            statusEl.innerHTML = '&#10003;';
            statusEl.style.color = '#4caf50';
            msgEl.style.display = 'block';
            msgEl.style.color = '#4caf50';
            msgEl.textContent = message || '';
            durEl.textContent = durationMs != null ? `${durationMs}ms` : '';
        } else if (status === 'failed') {
            statusEl.innerHTML = '&#10007;';
            statusEl.style.color = '#f44336';
            msgEl.style.display = 'block';
            msgEl.style.color = '#f44336';
            msgEl.textContent = message || 'Fehlgeschlagen';
            if (detail) {
                msgEl.title = detail;
            }
            durEl.textContent = durationMs != null ? `${durationMs}ms` : '';
        } else {
            statusEl.innerHTML = '&#9679;';
            statusEl.style.color = 'var(--pb-color-text-muted)';
            msgEl.style.display = 'none';
            durEl.textContent = '';
        }
    }

    function updateSummary(results) {
        const passed = results.filter(r => r.passed).length;
        const failed = results.filter(r => !r.passed).length;
        const total = results.length;
        const totalMs = results.reduce((s, r) => s + (r.duration_ms || 0), 0);
        if (failed === 0) {
            summaryEl.innerHTML = `<span style="color:#4caf50;">&#10003; ${passed}/${total} bestanden</span> (${Math.round(totalMs)}ms)`;
        } else {
            summaryEl.innerHTML = `<span style="color:#f44336;">&#10007; ${failed} fehlgeschlagen</span>, <span style="color:#4caf50;">${passed} bestanden</span> von ${total} (${Math.round(totalMs)}ms)`;
        }
    }

    // Run all automatic tests
    const btnRunAll = container.querySelector('#btn-run-all');
    btnRunAll.addEventListener('click', async () => {
        btnRunAll.disabled = true;
        btnRunAll.textContent = 'Tests laufen...';
        summaryEl.textContent = '';

        // Set only auto tests to running
        for (const t of autoTests) setTestStatus(t.id, 'running');

        try {
            const resp = await fetch('/api/v1/tests/run', { method: 'POST', headers });
            const data = await resp.json();
            for (const r of data.results) {
                setTestStatus(r.id, r.passed ? 'passed' : 'failed', r.message, r.duration_ms, r.detail);
            }
            updateSummary(data.results);
        } catch (e) {
            summaryEl.textContent = `Fehler: ${e.message}`;
        }

        btnRunAll.disabled = false;
        btnRunAll.textContent = 'Alle automatischen Tests';
    });

    // Run single test (works for both auto and manual)
    container.querySelectorAll('.btn-run-single').forEach(btn => {
        btn.addEventListener('click', async () => {
            const testId = btn.dataset.testId;
            btn.disabled = true;
            setTestStatus(testId, 'running');

            try {
                const resp = await fetch(`/api/v1/tests/run/${testId}`, { method: 'POST', headers });
                const r = await resp.json();
                setTestStatus(r.id, r.passed ? 'passed' : 'failed', r.message, r.duration_ms, r.detail);
            } catch (e) {
                setTestStatus(testId, 'failed', e.message);
            }

            btn.disabled = false;
        });
    });
}
