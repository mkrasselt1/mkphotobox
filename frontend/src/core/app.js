/**
 * MKPhotobox — Main application entry point.
 * Initializes state, WebSocket, i18n, and router.
 */

import { AppState } from './state.js';
import { Router } from './router.js';
import { WSClient } from './ws-client.js';
import { I18n } from './i18n.js';
import { BrowserTriggers } from './browser-triggers.js';
import { initOSK } from './osk.js';

const state = new AppState();
const i18n = new I18n();
const ws = new WSClient(state);
const router = new Router(state);
const browserTriggers = new BrowserTriggers(ws);

// Make globally accessible for components
window.pb = { state, i18n, ws, router, browserTriggers };

async function init() {
    // Load translations
    const cfg = await fetch('/api/v1/i18n').then(r => r.json()).catch(() => ({ locales: ['de'] }));
    const lang = cfg.locales?.includes('de') ? 'de' : (cfg.locales?.[0] || 'de');
    await i18n.load(lang);

    // Check setup status
    const setup = await fetch('/api/v1/setup/status').then(r => r.json()).catch(() => ({ completed: true }));

    // Check auth
    const token = localStorage.getItem('pb_token');
    if (token) {
        try {
            const me = await fetch('/api/v1/auth/me', {
                headers: { 'Authorization': `Bearer ${token}` }
            }).then(r => r.json());
            state.setAuth(token, me.role, me.username);
            await state.loadSections();
        } catch {
            localStorage.removeItem('pb_token');
        }
    }

    // Connect WebSocket
    ws.connect();

    // On-screen keyboard (touch text entry)
    initOSK();

    // Hide loading, show app
    document.getElementById('loading').style.display = 'none';
    document.getElementById('app').style.display = 'block';

    // Route based on state
    if (!setup.completed) {
        router.navigate('setup');
    } else if (!location.hash) {
        router.navigate('booth');
    } else {
        router.handleRoute();
    }
}

init();
