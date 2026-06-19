/**
 * WSClient — WebSocket client with auto-reconnect.
 */

export class WSClient {
    constructor(state) {
        this.state = state;
        this.ws = null;
        this._handlers = {};
        this._reconnectDelay = 1000;
        this._maxDelay = 30000;
    }

    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = this.state.auth.token || '';
        const url = `${proto}//${location.host}/api/v1/ws?token=${token}`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.state._set('wsConnected', true);
            this._reconnectDelay = 1000;
        };

        this.ws.onclose = () => {
            this.state._set('wsConnected', false);
            this._scheduleReconnect();
        };

        this.ws.onerror = () => {
            this.ws.close();
        };

        this.ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                this._dispatch(msg.type, msg.data);
            } catch {}
        };
    }

    send(type, data = {}) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, data }));
        }
    }

    on(type, handler) {
        if (!this._handlers[type]) this._handlers[type] = [];
        this._handlers[type].push(handler);
    }

    off(type, handler) {
        if (this._handlers[type]) {
            this._handlers[type] = this._handlers[type].filter(h => h !== handler);
        }
    }

    _dispatch(type, data) {
        (this._handlers[type] || []).forEach(h => h(data));
        (this._handlers['*'] || []).forEach(h => h(type, data));
    }

    _scheduleReconnect() {
        setTimeout(() => this.connect(), this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._maxDelay);
    }
}
