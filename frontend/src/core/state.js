/**
 * AppState — Global reactive state using EventTarget.
 */

export class AppState extends EventTarget {
    constructor() {
        super();
        this.auth = { token: null, role: null, username: null, sections: null };
        this.currentRoute = '';
        this.wsConnected = false;
        this.offline = !navigator.onLine;
        this.currentEvent = null;
        this.boothState = 'idle'; // idle|payment|countdown|capture|processing|review|collage_pick|share|thanks

        window.addEventListener('online', () => this._set('offline', false));
        window.addEventListener('offline', () => this._set('offline', true));
    }

    setAuth(token, role, username) {
        this.auth = { token, role, username, sections: null };
        localStorage.setItem('pb_token', token);
        this._emit('auth');
    }

    clearAuth() {
        this.auth = { token: null, role: null, username: null, sections: null };
        localStorage.removeItem('pb_token');
        this._emit('auth');
    }

    /** Load the admin sections this user may access (for nav + routing). */
    async loadSections() {
        if (!this.auth.token) { this.auth.sections = []; return []; }
        try {
            const r = await fetch('/api/v1/auth/my-sections', {
                headers: { 'Authorization': `Bearer ${this.auth.token}` },
            }).then(res => res.json());
            this.auth.sections = r.sections || [];
        } catch {
            this.auth.sections = [];
        }
        this._emit('auth');
        return this.auth.sections;
    }

    setBoothState(s) {
        this.boothState = s;
        this._emit('boothState');
    }

    _set(key, value) {
        this[key] = value;
        this._emit(key);
    }

    _emit(key) {
        this.dispatchEvent(new CustomEvent('change', { detail: { key } }));
        this.dispatchEvent(new CustomEvent(`change:${key}`));
    }

    on(key, fn) {
        this.addEventListener(`change:${key}`, fn);
    }

    off(key, fn) {
        this.removeEventListener(`change:${key}`, fn);
    }
}
