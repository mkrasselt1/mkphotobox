/**
 * Admin Shell — Sidebar + content area. Used by all admin sub-pages.
 */

export function adminShell(contentHTML) {
    const { i18n } = window.pb;
    const hash = location.hash.replace('#/', '');
    const auth = window.pb.state.auth || {};
    const isAdmin = auth.role === 'admin';

    // key = section key (matches backend MIETER_SECTIONS); adminOnly hides it from a Mieter
    // group = nav grouping; 'top' items sit above the groups and are always visible.
    let navItems = [
        { key: 'dashboard', href: '#/admin/dashboard', label: 'Dashboard', icon: '📊', group: 'top' },
        { key: 'events', href: '#/admin/events', label: 'Veranstaltungen', icon: '🎉', group: 'event' },
        { key: 'payment', href: '#/admin/payment', label: 'Bezahlung', icon: '💳', group: 'event', adminOnly: true },
        { key: 'permissions', href: '#/admin/permissions', label: 'Mieter-Rechte', icon: '🔑', group: 'event', adminOnly: true },
        { key: 'cameras', href: '#/admin/cameras', label: 'Kameras', icon: '📷', group: 'capture' },
        { key: 'triggers', href: '#/admin/triggers', label: 'Auslöser', icon: '⚡', group: 'capture', adminOnly: true },
        { key: 'background', href: '#/admin/background', label: 'Hintergrund', icon: '🪄', group: 'capture' },
        { key: 'templates', href: '#/admin/templates', label: 'Foto-Vorlagen', icon: '🧱', group: 'design' },
        { key: 'assets', href: '#/admin/assets', label: 'Vorlagen-Assets', icon: '🖼️', group: 'design' },
        { key: 'presets', href: '#/admin/presets', label: 'Ausgabe-Formate', icon: '📐', group: 'design' },
        { key: 'appearance', href: '#/admin/appearance', label: 'Design', icon: '🎨', group: 'design', adminOnly: true },
        { key: 'printer', href: '#/admin/printer', label: 'Drucker', icon: '🖨️', group: 'output' },
        { key: 'remote-gallery', href: '#/admin/remote-gallery', label: 'Online-Galerie', icon: '☁️', group: 'output', adminOnly: true },
        { key: 'cd-burn', href: '#/admin/cd-burn', label: 'CD/DVD brennen', icon: '💿', group: 'output' },
        { key: 'usb-export', href: '#/admin/usb-export', label: 'Auf USB kopieren', icon: '🔌', group: 'output' },
        { key: 'settings', href: '#/admin/settings', label: 'Einstellungen', icon: '⚙️', group: 'system', adminOnly: true },
        { key: 'wifi', href: '#/admin/wifi', label: 'WLAN', icon: '📶', group: 'system' },
        { key: 'bluetooth', href: '#/admin/bluetooth', label: 'Bluetooth', icon: '🔵', group: 'system' },
        { key: 'network', href: '#/admin/network', label: 'Netzwerk-Status', icon: '🌐', group: 'system', adminOnly: true },
        { key: 'telegram', href: '#/admin/telegram', label: 'Telegram-Bot', icon: '📨', group: 'system', adminOnly: true },
        { key: 'modules', href: '#/admin/modules', label: 'Module', icon: '🧩', group: 'system', adminOnly: true },
        { key: 'tests', href: '#/admin/tests', label: 'Tests', icon: '🧪', group: 'system', adminOnly: true },
        { key: 'help', href: '#/admin/help', label: 'Hilfe', icon: '❓', group: 'top', adminOnly: true },
    ];

    if (!isAdmin) {
        // Mieter: only the granted, non-admin-only sections
        const sections = auth.sections || [];
        navItems = navItems.filter(n => !n.adminOnly && sections.includes(n.key));
    }

    // Collapsible groups: listing all 22 entries at once makes the sidebar taller
    // than a booth screen, so only the group holding the current page is open.
    // Everything else is one tap away and the whole nav fits without scrolling.
    const GROUPS = [
        { id: 'event', label: 'Veranstaltung' },
        { id: 'capture', label: 'Aufnahme' },
        { id: 'design', label: 'Gestaltung' },
        { id: 'output', label: 'Ausgabe' },
        { id: 'system', label: 'System' },
    ];
    const isActive = (n) => hash === n.href.replace('#/', '');
    const itemHtml = (n) => `
        <a href="${n.href}" class="nav-item ${isActive(n) ? 'active' : ''}">
            <span class="nav-icon">${n.icon}</span><span>${n.label}</span>
        </a>`;

    // The group containing the current page wins; otherwise fall back to the last
    // one the user opened, so navigating back and forth doesn't fight them.
    const activeGroup = (navItems.find(isActive) || {}).group;
    let openGroup = activeGroup && activeGroup !== 'top' ? activeGroup : null;
    if (!openGroup) {
        try { openGroup = localStorage.getItem('pb_nav_group'); } catch { openGroup = null; }
    }
    if (!GROUPS.some(g => g.id === openGroup)) openGroup = GROUPS[0].id;

    let navHtml = navItems.filter(n => n.group === 'top').map(itemHtml).join('');
    for (const g of GROUPS) {
        const items = navItems.filter(n => n.group === g.id);
        if (!items.length) continue;
        const open = g.id === openGroup;
        navHtml += `
        <button class="nav-group" data-group="${g.id}" aria-expanded="${open}">
            <span>${g.label}</span><span class="nav-chevron">${open ? '▾' : '▸'}</span>
        </button>
        <div class="nav-group-items" data-group-items="${g.id}" ${open ? '' : 'hidden'}>
            ${items.map(itemHtml).join('')}
        </div>`;
    }

    return `
    <div style="display:flex;height:100%;">
        <nav class="admin-nav">
            <div class="admin-brand"><span class="admin-brand-dot"></span> Photobox Admin</div>
            ${navHtml}
            <div style="flex:1;"></div>
            <a href="#/booth" class="nav-item nav-muted"><span class="nav-icon">↩️</span><span>Zum Booth</span></a>
            ${isAdmin ? '<a href="#" class="nav-item" id="btn-update"><span class="nav-icon">⬆️</span><span>Software aktualisieren</span></a>' : ''}
            <a href="#/booth" class="nav-item nav-danger" id="btn-logout"><span class="nav-icon">🚪</span><span>${i18n.t('auth.logout')}</span></a>
            ${isAdmin ? '<a href="#" class="nav-item nav-danger" id="btn-shutdown"><span class="nav-icon">⏻</span><span>Herunterfahren</span></a>' : ''}
        </nav>
        <main style="flex:1;padding:2rem;overflow-y:auto;">
            ${contentHTML}
        </main>
    </div>
    <style>
        .admin-nav {
            width:240px;background:linear-gradient(180deg, var(--pb-color-surface) 0%, var(--pb-color-background) 100%);
            padding:1rem 0.75rem;display:flex;flex-direction:column;gap:0.15rem;overflow-y:auto;flex-shrink:0;
            border-right:1px solid var(--pb-color-border);
        }
        .admin-brand {
            display:flex;align-items:center;gap:0.5rem;font-size:1.15rem;font-weight:700;
            padding:0.5rem 0.75rem 1rem;letter-spacing:0.2px;
        }
        .admin-brand-dot { width:12px;height:12px;border-radius:50%;background:var(--pb-gradient);box-shadow:0 0 12px var(--pb-color-primary); }
        .nav-item {
            display:flex;align-items:center;gap:0.7rem;padding:0.65rem 0.85rem;border-radius:10px;
            color:var(--pb-color-text);text-decoration:none;font-size:0.93rem;
            transition:background 0.15s, transform 0.05s;position:relative;
        }
        .nav-group {
            display:flex;align-items:center;justify-content:space-between;width:100%;
            font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;
            color:var(--pb-color-text-muted);padding:0.7rem 0.85rem 0.35rem;opacity:0.8;
            background:none;border:none;cursor:pointer;font-family:inherit;text-align:left;
        }
        .nav-group:hover { opacity:1; }
        .nav-chevron { font-size:0.85rem;line-height:1; }
        .nav-group-items { display:flex;flex-direction:column;gap:0.15rem; }
        .nav-group-items[hidden] { display:none; }
        .nav-icon { width:1.4rem;text-align:center;font-size:1.05rem;flex-shrink:0; }
        .nav-item:hover { background:rgba(255,255,255,0.07); }
        .nav-item:active { transform:scale(0.98); }
        .nav-item.active { background:var(--pb-gradient);color:#fff;box-shadow:var(--pb-shadow-sm); }
        .nav-muted { color:var(--pb-color-text-muted); }
        .nav-danger { color:var(--pb-color-error); }
        .admin-card {
            background:var(--pb-color-surface);border:1px solid var(--pb-color-border);
            border-radius:var(--pb-radius);padding:1.25rem;margin-bottom:1rem;box-shadow:var(--pb-shadow-sm);
        }
        .admin-card h3 { margin-bottom:0.75rem;font-size:1rem;color:var(--pb-color-primary); }
        .admin-card p { font-size:0.9rem;margin-bottom:0.25rem;color:var(--pb-color-text-muted); }
        .admin-btn {
            padding:0.6rem 1.2rem;border-radius:10px;border:none;font-size:0.9rem;font-weight:600;
            cursor:pointer;color:white;transition:filter 0.15s, transform 0.05s, background 0.15s;
        }
        .admin-btn:hover { filter:brightness(1.08); }
        .admin-btn:active { transform:scale(0.97); }
        .admin-btn-primary { background:var(--pb-gradient);box-shadow:0 4px 14px rgba(108,140,255,0.35); }
        .admin-btn-outline {
            background:rgba(108,140,255,0.10);border:1.5px solid var(--pb-color-primary);color:var(--pb-color-text);
        }
        .admin-btn-outline:hover { background:rgba(108,140,255,0.22); }
        .admin-input {
            padding:0.6rem 0.7rem;border-radius:10px;border:1px solid var(--pb-color-border);
            background:rgba(0,0,0,0.25);color:var(--pb-color-text);font-size:0.9rem;transition:border-color 0.15s;
        }
        .admin-input:focus { border-color:var(--pb-color-primary);outline:none; }
        h1 { font-weight:700;letter-spacing:0.2px; }
    </style>`;
}

export function getHeaders() {
    const token = window.pb.state.auth.token;
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

/** Wire the collapsible nav groups. Called from setupLogout so every admin page
 *  gets it without each one having to remember. */
export function setupNav(container) {
    container.querySelectorAll('.nav-group').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.group;
            const items = container.querySelector(`[data-group-items="${id}"]`);
            if (!items) return;
            const open = items.hasAttribute('hidden');
            // One group at a time — that is what keeps the nav on one screen.
            container.querySelectorAll('[data-group-items]').forEach(el => el.setAttribute('hidden', ''));
            container.querySelectorAll('.nav-group').forEach(b => {
                b.setAttribute('aria-expanded', 'false');
                b.querySelector('.nav-chevron').textContent = '▸';
            });
            if (open) {
                items.removeAttribute('hidden');
                btn.setAttribute('aria-expanded', 'true');
                btn.querySelector('.nav-chevron').textContent = '▾';
                try { localStorage.setItem('pb_nav_group', id); } catch { /* private mode */ }
            }
        });
    });
}

export function setupLogout(container) {
    setupNav(container);

    container.querySelector('#btn-logout')?.addEventListener('click', (e) => {
        e.preventDefault();
        window.pb.state.clearAuth();
        window.pb.router.navigate('booth');
    });

    container.querySelector('#btn-update')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const h = getHeaders();
        let info = { is_git: true, head: '', can_restart: true };
        try { info = await fetch('/api/v1/system/update-check', { headers: h }).then(r => r.json()); } catch {}
        const o = document.createElement('div');
        o.id = 'pb-update';
        o.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:480px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
            <h2 style="margin:0 0 0.75rem;">Software aktualisieren</h2>
            ${info.is_git
                ? `<p style="color:var(--pb-color-text-muted);font-size:0.9rem;margin:0;">Holt die neueste Version von GitHub und startet die Box-Software neu.</p>
                   <p style="font-size:0.82rem;color:var(--pb-color-text-muted);margin:0.5rem 0 0;">Aktuell: <code>${info.head || '—'}</code></p>
                   ${info.can_restart ? '' : '<p style="color:var(--pb-color-error);font-size:0.85rem;margin:0.5rem 0 0;">⚠️ Neustart nicht erlaubt (sudoers-Regel fehlt) — Update wird geladen, Dienst muss manuell neu starten.</p>'}`
                : '<p style="color:var(--pb-color-error);margin:0;">Kein git-Repo auf der Box — Update nur über SSH (scripts/update.sh).</p>'}
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:1.25rem;">
                <button id="up-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                ${info.is_git ? '<button id="up-go" class="admin-btn admin-btn-primary">Jetzt aktualisieren</button>' : ''}
            </div>
            <p id="up-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
        </div>`;
        document.body.appendChild(o);
        o.querySelector('#up-cancel').addEventListener('click', () => o.remove());
        o.querySelector('#up-go')?.addEventListener('click', async () => {
            const msg = o.querySelector('#up-msg');
            const go = o.querySelector('#up-go');
            go.disabled = true; msg.style.color = 'var(--pb-color-text-muted)'; msg.textContent = 'Lade Update…';
            try {
                const res = await fetch('/api/v1/system/update', { method: 'POST', headers: h });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                if (!r.changed) {
                    msg.style.color = 'var(--pb-color-success)';
                    msg.textContent = '✓ Bereits aktuell (' + (r.head || r.after) + ')';
                    go.disabled = false;
                    return;
                }
                if (r.status === 'updated_no_restart') {
                    msg.style.color = 'var(--pb-color-error)';
                    msg.textContent = r.message;
                    return;
                }
                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = `✓ Aktualisiert auf ${r.after}. Starte neu…`;
                // poll until the service is back, then reload
                let tries = 0;
                const poll = setInterval(async () => {
                    tries++;
                    try {
                        const ok = await fetch('/api/v1/system/update-check', { headers: h });
                        if (ok.ok) { clearInterval(poll); msg.textContent = '✓ Neu gestartet — lade neu…'; setTimeout(() => location.reload(), 800); }
                    } catch {}
                    if (tries > 30) { clearInterval(poll); msg.textContent = 'Neustart dauert — bitte Seite manuell neu laden.'; }
                }, 1500);
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
                go.disabled = false;
            }
        });
    });

    container.querySelector('#btn-shutdown')?.addEventListener('click', async (e) => {
        e.preventDefault();
        const h = getHeaders();
        let check = { pending_jobs: 0 };
        try { check = await fetch('/api/v1/system/shutdown-check', { headers: h }).then(r => r.json()); } catch {}
        const pending = check.pending_jobs || 0;
        const status = pending > 0
            ? `<p style="color:var(--pb-color-error);margin:0;">⚠️ ${pending} offene(r) Druckauftrag/-aufträge — bitte erst fertig drucken lassen.</p>`
            : `<p style="color:var(--pb-color-success);margin:0;">✓ Keine offenen Druckaufträge.</p>`;
        const o = document.createElement('div');
        o.id = 'pb-shutdown';
        o.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:1.5rem;';
        o.innerHTML = `<div style="background:var(--pb-color-surface);border:1px solid var(--pb-color-border,#2a3a5e);border-radius:16px;padding:1.75rem;max-width:460px;width:100%;box-shadow:0 24px 70px rgba(0,0,0,0.6);">
            <h2 style="margin:0 0 0.75rem;">Box herunterfahren oder neu starten?</h2>
            ${status}
            <p style="color:var(--pb-color-text-muted);font-size:0.9rem;margin:0.5rem 0 0;"><strong>Herunterfahren:</strong> Box wird ausgeschaltet (zum Einschalten den Power-Knopf drücken). <strong>Neustarten:</strong> Box startet neu und ist gleich wieder da.</p>
            <div style="display:flex;gap:0.75rem;justify-content:flex-end;flex-wrap:wrap;margin-top:1.25rem;">
                <button id="sd-cancel" class="admin-btn admin-btn-outline">Abbrechen</button>
                <button id="sd-reboot" class="admin-btn admin-btn-primary" style="background:var(--pb-color-warning,#c77b1a);">${pending > 0 ? 'Trotzdem neu starten' : 'Neustarten'}</button>
                <button id="sd-go" class="admin-btn admin-btn-primary" style="background:var(--pb-color-error);">${pending > 0 ? 'Trotzdem ausschalten' : 'Herunterfahren'}</button>
            </div>
            <p id="sd-msg" style="margin:0.75rem 0 0;font-size:0.9rem;"></p>
        </div>`;
        document.body.appendChild(o);
        o.querySelector('#sd-cancel').addEventListener('click', () => o.remove());

        const powerAction = async (path, doingText, doneText) => {
            const msg = o.querySelector('#sd-msg');
            o.querySelectorAll('button').forEach(b => b.disabled = true);
            msg.style.color = 'var(--pb-color-text-muted)';
            msg.textContent = doingText;
            try {
                const res = await fetch(path, {
                    method: 'POST', headers: h, body: JSON.stringify({ force: pending > 0 }),
                });
                const r = await res.json();
                if (!res.ok) throw new Error(r.detail || 'Fehler');
                msg.style.color = 'var(--pb-color-success)';
                msg.textContent = doneText;
            } catch (err) {
                msg.style.color = 'var(--pb-color-error)';
                msg.textContent = 'Fehler: ' + err.message;
                o.querySelectorAll('button').forEach(b => b.disabled = false);
            }
        };

        o.querySelector('#sd-go').addEventListener('click', () =>
            powerAction('/api/v1/system/shutdown', 'Fahre herunter…', 'Box fährt herunter…'));
        o.querySelector('#sd-reboot').addEventListener('click', () =>
            powerAction('/api/v1/system/reboot', 'Starte neu…', 'Box startet neu… Seite in ~1 Min. neu laden.'));
    });
}
