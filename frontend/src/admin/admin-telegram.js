import { adminShell, getHeaders, setupLogout } from './admin-shell.js';

export async function render(container, state) {
    const headers = getHeaders();
    let c = { enabled: false, has_token: false, chat_id: '', notify_help: true, notify_media: true };
    try { c = await fetch('/api/v1/telegram/status', { headers }).then(r => r.json()); } catch {}

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:0.5rem;">Telegram-Bot</h1>
        <p style="color:var(--pb-color-text-muted);max-width:680px;margin-bottom:1.25rem;font-size:0.9rem;">
            Schickt Benachrichtigungen an einen Telegram-Chat: den <strong>Hilfe-Ruf</strong> vom Booth und
            Warnungen wie <strong>„Drucker fast leer"</strong>. Der Hilfe-Knopf erscheint im Booth nur, wenn
            der Bot aktiv ist.
        </p>
        <div style="max-width:600px;">
            <div class="admin-card">
                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-bottom:0.75rem;">
                    <input type="checkbox" id="f-enabled" ${c.enabled ? 'checked' : ''}> <strong>Aktivieren</strong>
                </label>

                <label style="font-size:0.85rem;">Bot-Token ${c.has_token ? '(gesetzt)' : ''}</label>
                <input id="f-token" type="password" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;"
                    placeholder="${c.has_token ? '•••••• (unverändert)' : '123456789:ABC...'}"
                    autocomplete="off">

                <label style="font-size:0.85rem;">Chat-ID</label>
                <input id="f-chat" class="admin-input" style="width:100%;margin:0.25rem 0 0.75rem;"
                    placeholder="z. B. 123456789 oder -100123..." value="${c.chat_id || ''}">

                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-top:0.5rem;">
                    <input type="checkbox" id="f-help" ${c.notify_help !== false ? 'checked' : ''}> Hilfe-Knopf im Booth senden
                </label>
                <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;margin-top:0.4rem;">
                    <input type="checkbox" id="f-media" ${c.notify_media !== false ? 'checked' : ''}> Warnung bei (fast) leerem Drucker
                </label>
            </div>

            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                <button id="btn-save" class="admin-btn admin-btn-primary">Speichern</button>
                <button id="btn-test" class="admin-btn admin-btn-outline">Test senden</button>
            </div>
            <p id="msg" style="margin-top:0.75rem;font-size:0.9rem;"></p>

            <details style="margin-top:1.25rem;font-size:0.85rem;color:var(--pb-color-text-muted);">
                <summary style="cursor:pointer;">So bekommst du Token &amp; Chat-ID</summary>
                <ol style="margin:0.5rem 0 0;padding-left:1.2rem;line-height:1.6;">
                    <li>In Telegram <code>@BotFather</code> öffnen → <code>/newbot</code> → Namen vergeben → du bekommst den <strong>Bot-Token</strong>.</li>
                    <li>Dem neuen Bot (oder in einer Gruppe mit dem Bot) eine Nachricht schicken.</li>
                    <li><strong>Chat-ID</strong> holen: <code>@userinfobot</code> anschreiben (zeigt deine ID) oder
                        <code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code> im Browser öffnen und die <code>chat.id</code> ablesen.</li>
                    <li>Token + Chat-ID hier eintragen, <strong>Aktivieren</strong>, <strong>Speichern</strong>, dann <strong>Test senden</strong>.</li>
                </ol>
            </details>
        </div>
    `);
    setupLogout(container);

    const setMsg = (t, k) => {
        const m = container.querySelector('#msg');
        m.textContent = t;
        m.style.color = k === 'error' ? 'var(--pb-color-error)' : k === 'ok' ? 'var(--pb-color-success)' : 'var(--pb-color-text-muted)';
    };

    const collect = () => ({
        enabled: container.querySelector('#f-enabled').checked,
        bot_token: container.querySelector('#f-token').value.trim(),   // blank = keep stored
        chat_id: container.querySelector('#f-chat').value.trim(),
        notify_help: container.querySelector('#f-help').checked,
        notify_media: container.querySelector('#f-media').checked,
    });

    async function save() {
        const res = await fetch('/api/v1/telegram/configure', {
            method: 'POST', headers, body: JSON.stringify(collect()),
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Fehler');
        return res.json();
    }

    container.querySelector('#btn-save').addEventListener('click', async () => {
        setMsg('Speichere…');
        try { await save(); setMsg('Gespeichert!', 'ok'); }
        catch (e) { setMsg('Fehler: ' + e.message, 'error'); }
    });

    container.querySelector('#btn-test').addEventListener('click', async () => {
        setMsg('Speichere & sende Test…');
        try {
            await save();
            const r = await fetch('/api/v1/telegram/test', { method: 'POST', headers }).then(r => r.json());
            setMsg(r.ok ? '✓ Test gesendet — schau in den Telegram-Chat.' : '✗ ' + (r.message || 'Fehler'), r.ok ? 'ok' : 'error');
        } catch (e) { setMsg('Fehler: ' + e.message, 'error'); }
    });
}
