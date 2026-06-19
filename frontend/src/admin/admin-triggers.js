import { adminShell, getHeaders, setupLogout } from './admin-shell.js';
import { BrowserTriggers } from '../core/browser-triggers.js';

export async function render(container, state) {
    const headers = getHeaders();
    const ws = window.pb.ws;

    // Initialize browser triggers helper
    const bt = new BrowserTriggers(ws);

    // Load trigger status + config
    let triggers = [];
    let audioDevices = [];
    let serialPorts = [];
    let keyboardDevices = [];

    try {
        const [tRes, aRes, sRes, kRes] = await Promise.all([
            fetch('/api/v1/triggers/', { headers }).then(r => r.json()).catch(() => []),
            fetch('/api/v1/triggers/audio-devices', { headers }).then(r => r.json()).catch(() => []),
            fetch('/api/v1/triggers/serial-ports', { headers }).then(r => r.json()).catch(() => []),
            fetch('/api/v1/triggers/keyboard-devices', { headers }).then(r => r.json()).catch(() => []),
        ]);
        triggers = Array.isArray(tRes) ? tRes : [];
        audioDevices = Array.isArray(aRes) ? aRes : [];
        serialPorts = Array.isArray(sRes) ? sRes : [];
        keyboardDevices = Array.isArray(kRes) ? kRes : [];
    } catch {}

    function getTrigger(id) { return triggers.find(t => t.id === id) || {}; }

    const kbTrigger = getTrigger('keyboard');
    const hostKbTrigger = getTrigger('host_keyboard');
    const acousticTrigger = getTrigger('acoustic');
    const serialTrigger = getTrigger('serial');
    const btTrigger = getTrigger('bluetooth');

    container.innerHTML = adminShell(`
        <h1 style="margin-bottom:0.5rem;">Trigger-Konfiguration</h1>
        <p style="color:var(--pb-color-text-muted);margin-bottom:1.5rem;">
            Konfiguriere wie die Fotoaufnahme ausgel&ouml;st wird.
        </p>

        <!-- Browser Keyboard -->
        <div class="admin-card">
            <h3>Tastatur (Browser) ${_badge(kbTrigger)}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Reagiert auf Tasten im Browser-Fenster. Funktioniert auf jedem Ger&auml;t.
            </p>
            <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <label style="font-size:0.9rem;">Taste:</label>
                <input id="kb-key" class="admin-input" style="width:120px;" value="${kbTrigger.config?.key || 'space'}" readonly>
                <button id="btn-kb-learn" class="admin-btn admin-btn-primary" style="padding:0.4rem 1rem;font-size:0.85rem;">
                    Taste lernen
                </button>
                <span id="kb-status" style="font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
            </div>
        </div>

        <!-- Host Keyboard (USB HID) -->
        <div class="admin-card">
            <h3>Tastatur / USB-HID (Host) ${_badge(hostKbTrigger)}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Lauscht auf Tastaturen und USB-HID-Ger&auml;te die am Server angeschlossen sind.
                Funktioniert auch wenn der Browser auf einem anderen Ger&auml;t l&auml;uft.
            </p>
            ${keyboardDevices.length > 0 ? `
                <p style="font-size:0.85rem;margin-bottom:0.5rem;">Erkannte Ger&auml;te: ${keyboardDevices.map(d => `<strong>${d.name}</strong>`).join(', ')}</p>
            ` : ''}
            <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <label style="font-size:0.9rem;">Taste:</label>
                <input id="hostkb-key" class="admin-input" style="width:180px;" value="${hostKbTrigger.config?.key_code || '(beliebig)'}" readonly>
                <button id="btn-hostkb-learn" class="admin-btn admin-btn-primary" style="padding:0.4rem 1rem;font-size:0.85rem;">
                    Taste lernen (15s)
                </button>
                <span id="hostkb-status" style="font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
            </div>
            <div style="margin-top:0.5rem;display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <label style="font-size:0.9rem;">Ger&auml;tefilter:</label>
                <input id="hostkb-device" class="admin-input" style="width:200px;" placeholder="(alle Ger&auml;te)"
                       value="${hostKbTrigger.config?.device_name || ''}">
            </div>
        </div>

        <!-- Web Bluetooth (Browser) -->
        <div class="admin-card">
            <h3>Bluetooth-Remote (Browser) ${BrowserTriggers.bluetoothSupported ? '' : '<span style="color:var(--pb-color-error);font-size:0.8rem;">&mdash; nicht unterst&uuml;tzt</span>'}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Verbindet BLE-Fernausl&ouml;ser (z.B. Handy-Selfie-Remote) &uuml;ber den Browser.
                Funktioniert auf Chrome/Android/Edge.
            </p>
            <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <button id="btn-ble-connect" class="admin-btn admin-btn-primary" style="padding:0.4rem 1rem;font-size:0.85rem;"
                        ${BrowserTriggers.bluetoothSupported ? '' : 'disabled'}>
                    Bluetooth-Ger&auml;t verbinden
                </button>
                <button id="btn-ble-disconnect" class="admin-btn admin-btn-outline" style="padding:0.4rem 1rem;font-size:0.85rem;display:none;">
                    Trennen
                </button>
                <span id="ble-status" style="font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
            </div>
        </div>

        <!-- Host Bluetooth (evdev) -->
        <div class="admin-card">
            <h3>Bluetooth-Remote (Host/evdev) ${_badge(btTrigger)}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Lauscht auf gekoppelte Bluetooth-HID-Ger&auml;te am Server (nur Linux).
            </p>
            <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <label style="font-size:0.9rem;">Ger&auml;tename-Filter:</label>
                <input id="bt-device" class="admin-input" style="width:200px;" placeholder="(alle BT-Ger&auml;te)"
                       value="${btTrigger.config?.device_name || ''}">
            </div>
        </div>

        <!-- Acoustic -->
        <div class="admin-card">
            <h3>Akustik (Mikrofon) ${_badge(acousticTrigger)}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Erkennt laute Ger&auml;usche (Klatschen, &quot;Cheese!&quot;) &uuml;ber ein Mikrofon am Server.
            </p>
            <div style="display:flex;flex-direction:column;gap:0.5rem;">
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Mikrofon:</label>
                    <select id="audio-device" class="admin-input" style="width:300px;">
                        <option value="">System-Standard</option>
                        ${audioDevices.map(d => `
                            <option value="${d.index}" ${d.index == acousticTrigger.config?.device_index ? 'selected' : ''}>
                                ${d.name} ${d.is_default ? '(Standard)' : ''}
                            </option>
                        `).join('')}
                    </select>
                </div>
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Schwellwert:</label>
                    <input id="audio-threshold" type="range" min="0.1" max="1.0" step="0.05"
                           value="${acousticTrigger.config?.threshold ?? 0.7}" style="width:150px;">
                    <span id="audio-threshold-val" style="font-size:0.85rem;">${acousticTrigger.config?.threshold ?? 0.7}</span>
                </div>
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Cooldown:</label>
                    <input id="audio-cooldown" class="admin-input" type="number" style="width:100px;"
                           value="${acousticTrigger.config?.cooldown_ms ?? 2000}" min="500" step="100"> ms
                </div>
            </div>
        </div>

        <!-- Serial (Host) -->
        <div class="admin-card">
            <h3>Seriell (Host) ${_badge(serialTrigger)}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Lauscht auf Daten &uuml;ber eine serielle Schnittstelle am Server (Arduino, ESP, ext. Button).
            </p>
            <div style="display:flex;flex-direction:column;gap:0.5rem;">
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Port:</label>
                    <select id="serial-port" class="admin-input" style="width:250px;">
                        <option value="">-- Port w&auml;hlen --</option>
                        ${serialPorts.map(p => `
                            <option value="${p.port}" ${p.port === serialTrigger.config?.port ? 'selected' : ''}>
                                ${p.port} &mdash; ${p.name}
                            </option>
                        `).join('')}
                    </select>
                </div>
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Baud:</label>
                    <select id="serial-baud" class="admin-input" style="width:120px;">
                        ${[9600, 19200, 38400, 57600, 115200].map(b => `
                            <option value="${b}" ${b == (serialTrigger.config?.baud || 9600) ? 'selected' : ''}>${b}</option>
                        `).join('')}
                    </select>
                </div>
                <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                    <label style="font-size:0.9rem;">Trigger-Wort:</label>
                    <input id="serial-trigger" class="admin-input" style="width:150px;"
                           value="${_escapeHtml(serialTrigger.config?.trigger_string || '\\n')}" placeholder="\\n">
                    <button id="btn-serial-learn" class="admin-btn admin-btn-primary" style="padding:0.4rem 1rem;font-size:0.85rem;">
                        Lernen (15s)
                    </button>
                    <span id="serial-status" style="font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
                </div>
            </div>
        </div>

        <!-- WebSerial (Browser) -->
        <div class="admin-card">
            <h3>Seriell (Browser / WebSerial) ${BrowserTriggers.serialSupported ? '' : '<span style="color:var(--pb-color-error);font-size:0.8rem;">&mdash; nicht unterst&uuml;tzt</span>'}</h3>
            <p style="font-size:0.85rem;color:var(--pb-color-text-muted);margin-bottom:0.75rem;">
                Verbindet ein serielles Ger&auml;t &uuml;ber den Browser (USB am Client/Tablet).
                Funktioniert auf Chrome/Edge.
            </p>
            <div style="display:flex;gap:0.75rem;align-items:center;flex-wrap:wrap;">
                <button id="btn-webserial-connect" class="admin-btn admin-btn-primary" style="padding:0.4rem 1rem;font-size:0.85rem;"
                        ${BrowserTriggers.serialSupported ? '' : 'disabled'}>
                    Serielles Ger&auml;t verbinden
                </button>
                <button id="btn-webserial-disconnect" class="admin-btn admin-btn-outline" style="padding:0.4rem 1rem;font-size:0.85rem;display:none;">
                    Trennen
                </button>
                <span id="webserial-status" style="font-size:0.85rem;color:var(--pb-color-text-muted);"></span>
            </div>
        </div>

        <!-- Save button -->
        <div style="margin-top:1.5rem;display:flex;gap:0.75rem;align-items:center;">
            <button id="btn-save" class="admin-btn admin-btn-primary">Einstellungen speichern</button>
            <span id="save-status" style="font-size:0.85rem;"></span>
        </div>
    `);

    setupLogout(container);

    // ── Browser Keyboard learn mode ─────────────────────────────────

    const kbKeyInput = container.querySelector('#kb-key');
    const kbStatus = container.querySelector('#kb-status');

    container.querySelector('#btn-kb-learn').addEventListener('click', () => {
        kbStatus.textContent = 'Dr\u00fccke jetzt eine Taste...';
        kbStatus.style.color = 'var(--pb-color-primary)';

        function onKey(e) {
            e.preventDefault();
            document.removeEventListener('keydown', onKey);
            const key = e.code || e.key;
            kbKeyInput.value = key;
            kbStatus.textContent = `Taste "${key}" erkannt`;
            kbStatus.style.color = '#4caf50';
        }
        document.addEventListener('keydown', onKey);

        // Timeout after 10s
        setTimeout(() => {
            document.removeEventListener('keydown', onKey);
            if (kbStatus.textContent.includes('Dr\u00fccke')) {
                kbStatus.textContent = 'Timeout';
                kbStatus.style.color = 'var(--pb-color-text-muted)';
            }
        }, 10000);
    });

    // ── Host Keyboard learn mode ────────────────────────────────────

    const hostKbKeyInput = container.querySelector('#hostkb-key');
    const hostKbStatus = container.querySelector('#hostkb-status');

    container.querySelector('#btn-hostkb-learn').addEventListener('click', async () => {
        hostKbStatus.textContent = 'Warte auf Tastendruck am Server (15s)...';
        hostKbStatus.style.color = 'var(--pb-color-primary)';

        try {
            const resp = await fetch('/api/v1/triggers/learn/host-keyboard', {
                method: 'POST', headers,
            });
            if (resp.status === 408) {
                hostKbStatus.textContent = 'Timeout \u2014 keine Taste gedr\u00fcckt';
                hostKbStatus.style.color = 'var(--pb-color-text-muted)';
                return;
            }
            const data = await resp.json();
            if (data.key_code) {
                hostKbKeyInput.value = data.key_code;
                hostKbStatus.textContent = `"${data.key_code}" von "${data.device}"`;
                hostKbStatus.style.color = '#4caf50';
            } else {
                hostKbStatus.textContent = data.detail || 'Fehler';
                hostKbStatus.style.color = 'var(--pb-color-error)';
            }
        } catch (e) {
            hostKbStatus.textContent = 'Fehler: ' + e.message;
            hostKbStatus.style.color = 'var(--pb-color-error)';
        }
    });

    // ── Web Bluetooth ───────────────────────────────────────────────

    const bleStatus = container.querySelector('#ble-status');
    const btnBleConnect = container.querySelector('#btn-ble-connect');
    const btnBleDisconnect = container.querySelector('#btn-ble-disconnect');

    btnBleConnect.addEventListener('click', async () => {
        bleStatus.textContent = 'Verbinde...';
        bleStatus.style.color = 'var(--pb-color-primary)';
        try {
            const result = await bt.connectBluetooth();
            bleStatus.textContent = `Verbunden: ${result.name}`;
            bleStatus.style.color = '#4caf50';
            btnBleConnect.style.display = 'none';
            btnBleDisconnect.style.display = '';
        } catch (e) {
            bleStatus.textContent = e.message;
            bleStatus.style.color = 'var(--pb-color-error)';
        }
    });

    btnBleDisconnect.addEventListener('click', () => {
        bt.disconnectBluetooth();
        bleStatus.textContent = 'Getrennt';
        bleStatus.style.color = 'var(--pb-color-text-muted)';
        btnBleConnect.style.display = '';
        btnBleDisconnect.style.display = 'none';
    });

    // ── WebSerial ───────────────────────────────────────────────────

    const webserialStatus = container.querySelector('#webserial-status');
    const btnWsConnect = container.querySelector('#btn-webserial-connect');
    const btnWsDisconnect = container.querySelector('#btn-webserial-disconnect');

    btnWsConnect.addEventListener('click', async () => {
        webserialStatus.textContent = 'Verbinde...';
        webserialStatus.style.color = 'var(--pb-color-primary)';
        try {
            const result = await bt.connectSerial({
                baud: parseInt(container.querySelector('#serial-baud').value) || 9600,
                trigger_string: container.querySelector('#serial-trigger').value.replace(/\\n/g, '\n').replace(/\\r/g, '\r') || '\n',
            });
            webserialStatus.textContent = 'Verbunden \u2014 lausche auf Trigger';
            webserialStatus.style.color = '#4caf50';
            btnWsConnect.style.display = 'none';
            btnWsDisconnect.style.display = '';
        } catch (e) {
            webserialStatus.textContent = e.message;
            webserialStatus.style.color = 'var(--pb-color-error)';
        }
    });

    btnWsDisconnect.addEventListener('click', async () => {
        await bt.disconnectSerial();
        webserialStatus.textContent = 'Getrennt';
        webserialStatus.style.color = 'var(--pb-color-text-muted)';
        btnWsConnect.style.display = '';
        btnWsDisconnect.style.display = 'none';
    });

    // ── Serial learn mode (host) ────────────────────────────────────

    const serialStatus = container.querySelector('#serial-status');

    container.querySelector('#btn-serial-learn').addEventListener('click', async () => {
        const port = container.querySelector('#serial-port').value;
        const baud = parseInt(container.querySelector('#serial-baud').value) || 9600;
        if (!port) {
            serialStatus.textContent = 'Bitte Port w\u00e4hlen';
            serialStatus.style.color = 'var(--pb-color-error)';
            return;
        }

        serialStatus.textContent = 'Warte auf Daten (15s)...';
        serialStatus.style.color = 'var(--pb-color-primary)';

        try {
            const resp = await fetch('/api/v1/triggers/learn/serial', {
                method: 'POST', headers,
                body: JSON.stringify({ port, baud }),
            });
            if (resp.status === 408) {
                serialStatus.textContent = 'Timeout \u2014 keine Daten';
                serialStatus.style.color = 'var(--pb-color-text-muted)';
                return;
            }
            const data = await resp.json();
            if (data.text) {
                container.querySelector('#serial-trigger').value = data.text;
                serialStatus.textContent = `Empfangen: "${data.text}"`;
                serialStatus.style.color = '#4caf50';
            } else if (data.detail) {
                serialStatus.textContent = data.detail;
                serialStatus.style.color = 'var(--pb-color-error)';
            }
        } catch (e) {
            serialStatus.textContent = 'Fehler: ' + e.message;
            serialStatus.style.color = 'var(--pb-color-error)';
        }
    });

    // ── Threshold slider live update ────────────────────────────────

    const thresholdSlider = container.querySelector('#audio-threshold');
    const thresholdVal = container.querySelector('#audio-threshold-val');
    thresholdSlider.addEventListener('input', () => {
        thresholdVal.textContent = thresholdSlider.value;
    });

    // ── Save all settings ───────────────────────────────────────────

    container.querySelector('#btn-save').addEventListener('click', async () => {
        const saveStatus = container.querySelector('#save-status');
        saveStatus.textContent = 'Speichere...';
        saveStatus.style.color = 'var(--pb-color-primary)';

        const settings = {
            'triggers.keyboard.key': kbKeyInput.value,
            'triggers.host_keyboard.key_code': hostKbKeyInput.value === '(beliebig)' ? '' : hostKbKeyInput.value,
            'triggers.host_keyboard.device_name': container.querySelector('#hostkb-device').value,
            'triggers.bluetooth.device_name': container.querySelector('#bt-device').value,
            'triggers.acoustic.device_index': container.querySelector('#audio-device').value || null,
            'triggers.acoustic.threshold': parseFloat(thresholdSlider.value),
            'triggers.acoustic.cooldown_ms': parseInt(container.querySelector('#audio-cooldown').value),
            'triggers.serial.port': container.querySelector('#serial-port').value,
            'triggers.serial.baud': parseInt(container.querySelector('#serial-baud').value),
            'triggers.serial.trigger_string': container.querySelector('#serial-trigger').value,
        };

        try {
            const results = await Promise.all(
                Object.entries(settings).map(([key, value]) =>
                    fetch(`/api/v1/settings/${key}`, {
                        method: 'PUT', headers,
                        body: JSON.stringify({ key, value }),
                    })
                )
            );
            const allOk = results.every(r => r.ok);
            if (allOk) {
                saveStatus.textContent = 'Gespeichert! (Neustart f\u00fcr \u00c4nderungen an Host-Triggern n\u00f6tig)';
                saveStatus.style.color = '#4caf50';
            } else {
                saveStatus.textContent = 'Einige Einstellungen konnten nicht gespeichert werden';
                saveStatus.style.color = 'var(--pb-color-error)';
            }
        } catch (e) {
            saveStatus.textContent = 'Fehler: ' + e.message;
            saveStatus.style.color = 'var(--pb-color-error)';
        }
    });
}

// ── Helper functions ────────────────────────────────────────────────────

function _badge(trigger) {
    if (!trigger.id) return '';
    if (trigger.loaded) return '<span style="font-size:0.75rem;padding:2px 8px;border-radius:4px;background:#4caf50;color:white;margin-left:0.5rem;">aktiv</span>';
    if (trigger.enabled) return '<span style="font-size:0.75rem;padding:2px 8px;border-radius:4px;background:#ff9800;color:white;margin-left:0.5rem;">aktiviert, nicht geladen</span>';
    return '<span style="font-size:0.75rem;padding:2px 8px;border-radius:4px;background:#666;color:white;margin-left:0.5rem;">deaktiviert</span>';
}

function _escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
