/**
 * AppState — Global reactive state using EventTarget.
 */

export class AppState extends EventTarget {
    constructor() {
        super();
        this.auth = { token: null, role: null, username: null };
        this.currentRoute = '';
        this.wsConnected = false;
        this.offline = !navigator.onLine;
        this.currentEvent = null;
        this.boothState = 'idle'; // idle|payment|countdown|capture|processing|review|collage_pick|share|thanks

        window.addEventListener('online', () => this._set('offline', false));
        window.addEventListener('offline', () => this._set('offline', true));
    }

    setAuth(token, role, username) {
        this.auth = { token, role, username };
        localStorage.setItem('pb_token', token);
        this._emit('auth');
    }

    clearAuth() {
        this.auth = { token: null, role: null, username: null };
        localStorage.removeItem('pb_token');
        this._emit('auth');
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
