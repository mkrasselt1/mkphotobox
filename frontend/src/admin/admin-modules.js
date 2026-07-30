import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();

    let modules = {};
    try {
        modules = await fetch('/api/v1/modules', { headers }).then(r => r.json());
    } catch {}

    const sections = [
        { title: 'Kameras', key: 'cameras', items: modules.cameras || [] },
        { title: 'Ausl\u00f6ser', key: 'triggers', items: modules.triggers || [] },
        { title: 'Ausgabe', key: 'outputs', items: modules.outputs || [] },
        { title: 'Bezahlung', key: 'payments', items: modules.payments || [] },
    ];

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:1.5rem;">Module</h1>
        <div style="max-width:700px;">
            ${sections.map(s => `
                <div class="admin-card">
                    <h3>${s.title} <span style="font-size:0.8rem;color:var(--pb-color-text-muted);font-weight:normal;">
                        (${s.items.filter(m => m.loaded).length}/${s.items.length} geladen)
                    </span></h3>
                    ${s.items.length ? `
                        <div style="display:flex;flex-direction:column;gap:0.4rem;">
                            ${s.items.map(m => `
                                <div style="display:flex;align-items:center;gap:0.75rem;padding:0.4rem 0.5rem;border-radius:6px;background:rgba(255,255,255,0.03);">
                                    <span style="font-size:1.1rem;width:20px;text-align:center;color:${_statusColor(m)};">
                                        ${_statusIcon(m)}
                                    </span>
                                    <div style="flex:1;min-width:0;">
                                        <span style="font-size:0.9rem;">${m.name}</span>
                                        ${m.requirement ? `<div style="font-size:0.75rem;color:var(--pb-color-text-muted);margin-top:2px;">${_esc(m.requirement)}</div>` : ''}
                                    </div>
                                    ${_badge(m)}
                                </div>
                            `).join('')}
                        </div>
                    ` : '<p style="color:var(--pb-color-text-muted);">Keine konfiguriert</p>'}
                </div>
            `).join('')}
        </div>
    `);

    setupLogout(container);
}

function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _statusIcon(m) {
    if (m.loaded) return '&#10003;';
    if (!m.available) return '&#10007;';
    if (m.enabled) return '&#9888;';
    return '&#9679;';
}

function _statusColor(m) {
    if (m.loaded) return '#4caf50';
    if (!m.available) return '#e05252';
    if (m.enabled) return '#ff9800';
    return '#666';
}

function _pill(text, bg, fg) {
    return `<span style="font-size:0.75rem;padding:2px 8px;border-radius:4px;background:${bg};color:${fg};white-space:nowrap;">${text}</span>`;
}

/**
 * Three separate states the old badge lumped together: the box can't run it,
 * it's switched off, or it's on but didn't load (misconfigured). Only the last
 * one is actually a fault to chase.
 */
function _badge(m) {
    if (m.loaded) return _pill('geladen', '#4caf50', 'white');
    if (!m.available) return _pill('nicht m\u00f6glich', '#e05252', 'white');
    if (m.enabled) return _pill('nicht konfiguriert', '#ff9800', 'white');
    return _pill('deaktiviert', '#444', '#aaa');
}
