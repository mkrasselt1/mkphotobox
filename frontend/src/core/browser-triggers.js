/**
 * Browser-side triggers: Web Bluetooth + WebSerial.
 *
 * These use browser APIs to connect to hardware attached to the CLIENT
 * (tablet/phone) and send trigger events to the server via WebSocket.
 */

export class BrowserTriggers {
    constructor(ws) {
        this.ws = ws;
        this._bleDevice = null;
        this._bleChar = null;
        this._serialPort = null;
        this._serialReader = null;
        this._serialRunning = false;
    }

    // ── Web Bluetooth ───────────────────────────────────────────────

    static get bluetoothSupported() {
        return !!navigator.bluetooth;
    }

    async connectBluetooth() {
        if (!navigator.bluetooth) {
            throw new Error('Web Bluetooth wird von diesem Browser nicht unterstützt');
        }

        // Request any BLE device that exposes HID-like services
        // Common BLE remotes use these service UUIDs
        const device = await navigator.bluetooth.requestDevice({
            acceptAllDevices: true,
            optionalServices: [
                'human_interface_device',
                'generic_access',
                0xFFE0,  // Common for BLE buttons/remotes
                0x1812,  // HID over GATT
            ],
        });

        this._bleDevice = device;
        device.addEventListener('gattserverdisconnected', () => {
            console.log('BLE device disconnected');
            this._bleDevice = null;
            this._bleChar = null;
        });

        const server = await device.gatt.connect();

        // Try to find a notification characteristic (button press)
        const services = await server.getPrimaryServices();
        for (const service of services) {
            try {
                const chars = await service.getCharacteristics();
                for (const char of chars) {
                    if (char.properties.notify) {
                        await char.startNotifications();
                        char.addEventListener('characteristicvaluechanged', () => {
                            this._onBleTrigger(device.name || 'BLE Remote');
                        });
                        this._bleChar = char;
                        return {
                            name: device.name || 'Unknown BLE',
                            id: device.id,
                            service: service.uuid,
                            characteristic: char.uuid,
                        };
                    }
                }
            } catch { /* service not accessible, skip */ }
        }

        // Fallback: some devices don't expose GATT properly
        // Still connected — user can use the BLE keyboard fallback
        return {
            name: device.name || 'Unknown BLE',
            id: device.id,
            note: 'Kein Notification-Characteristic gefunden — Gerät sendet evtl. als HID-Tastatur',
        };
    }

    _onBleTrigger(deviceName) {
        console.log('BLE trigger from:', deviceName);
        this.ws.send('trigger.fire', { source: 'web_bluetooth', device: deviceName });
    }

    disconnectBluetooth() {
        if (this._bleDevice?.gatt?.connected) {
            this._bleDevice.gatt.disconnect();
        }
        this._bleDevice = null;
        this._bleChar = null;
    }

    get bluetoothConnected() {
        return !!(this._bleDevice?.gatt?.connected);
    }

    get bluetoothDeviceName() {
        return this._bleDevice?.name || null;
    }

    // ── WebSerial ───────────────────────────────────────────────────

    static get serialSupported() {
        return !!navigator.serial;
    }

    async connectSerial(options = {}) {
        if (!navigator.serial) {
            throw new Error('WebSerial wird von diesem Browser nicht unterstützt');
        }

        const port = await navigator.serial.requestPort();
        const baud = options.baud || 9600;
        const triggerString = options.trigger_string || '\n';

        await port.open({ baudRate: baud });
        this._serialPort = port;
        this._serialRunning = true;

        // Read loop in background
        this._readSerial(port, triggerString);

        return {
            info: port.getInfo(),
            baud,
            trigger_string: triggerString,
        };
    }

    async _readSerial(port, triggerString) {
        const triggerBytes = new TextEncoder().encode(triggerString);
        let buffer = new Uint8Array();

        try {
            while (this._serialRunning && port.readable) {
                const reader = port.readable.getReader();
                this._serialReader = reader;
                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;
                        if (!this._serialRunning) break;

                        // Append to buffer
                        const newBuf = new Uint8Array(buffer.length + value.length);
                        newBuf.set(buffer);
                        newBuf.set(value, buffer.length);
                        buffer = newBuf;

                        // Check for trigger string
                        if (this._containsBytes(buffer, triggerBytes)) {
                            buffer = new Uint8Array();
                            this._onSerialTrigger();
                        }
                    }
                } finally {
                    reader.releaseLock();
                }
            }
        } catch (e) {
            if (this._serialRunning) {
                console.error('WebSerial read error:', e);
            }
        }
    }

    _containsBytes(haystack, needle) {
        for (let i = 0; i <= haystack.length - needle.length; i++) {
            let match = true;
            for (let j = 0; j < needle.length; j++) {
                if (haystack[i + j] !== needle[j]) { match = false; break; }
            }
            if (match) return true;
        }
        return false;
    }

    _onSerialTrigger() {
        console.log('WebSerial trigger');
        this.ws.send('trigger.fire', { source: 'web_serial' });
    }

    async disconnectSerial() {
        this._serialRunning = false;
        if (this._serialReader) {
            try { await this._serialReader.cancel(); } catch {}
            this._serialReader = null;
        }
        if (this._serialPort) {
            try { await this._serialPort.close(); } catch {}
            this._serialPort = null;
        }
    }

    get serialConnected() {
        return !!(this._serialPort?.readable);
    }

    // ── Cleanup ─────────────────────────────────────────────────────

    async disconnectAll() {
        this.disconnectBluetooth();
        await this.disconnectSerial();
    }
}
