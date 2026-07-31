/**
 * Booth sounds — countdown beeps and a shutter click.
 *
 * Everything is synthesised with the Web Audio API instead of shipping audio
 * files: the box runs offline, and generated tones cost no assets, no decoding
 * and no cache. Failure is always silent — a booth that cannot beep must still
 * take photos.
 *
 * Browsers block audio until the user has interacted with the page, so call
 * unlock() from a real touch/click (the booth does this on the start button).
 */

let ctx = null;
let enabled = true;
let volume = 0.6;
let unlocked = false;

function ensureCtx() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
        ctx = new AC();
    } catch {
        ctx = null;
    }
    return ctx;
}

export const sounds = {
    configure({ enabled: on = true, volume: vol = 0.6 } = {}) {
        enabled = on !== false;
        volume = Math.max(0, Math.min(1, Number(vol) || 0));
    },

    get enabled() {
        return enabled;
    },

    /** Call from a user gesture — without it every later sound stays muted. */
    unlock() {
        if (unlocked || !enabled) return;
        const c = ensureCtx();
        if (!c) return;
        if (c.state === 'suspended') c.resume().catch(() => {});
        unlocked = true;
    },

    /** One countdown tick. `final` = the last one before the shot (higher, longer). */
    tick(final = false) {
        beep(final ? 1320 : 760, final ? 0.28 : 0.09, final ? 0.5 : 0.32);
    },

    /** Mechanical shutter: mirror up, mirror down. */
    shutter() {
        click(0);
        click(0.075, 0.7);
    },

    /** Short two-note confirmation after a photo was stored. */
    success() {
        beep(880, 0.1, 0.28);
        beep(1320, 0.16, 0.28, 0.1);
    },
};

function beep(freq, duration, gain, delay = 0) {
    if (!enabled) return;
    const c = ensureCtx();
    if (!c) return;
    try {
        const t = c.currentTime + delay;
        const osc = c.createOscillator();
        const amp = c.createGain();
        osc.type = 'triangle';
        osc.frequency.value = freq;
        // Attack/decay envelope — a raw gate would click audibly.
        amp.gain.setValueAtTime(0.0001, t);
        amp.gain.exponentialRampToValueAtTime(Math.max(0.0002, gain * volume), t + 0.012);
        amp.gain.exponentialRampToValueAtTime(0.0001, t + duration);
        osc.connect(amp).connect(c.destination);
        osc.start(t);
        osc.stop(t + duration + 0.02);
    } catch {
        /* never let a sound break the flow */
    }
}

function click(delay = 0, gain = 1) {
    if (!enabled) return;
    const c = ensureCtx();
    if (!c) return;
    try {
        const t = c.currentTime + delay;
        const length = Math.floor(c.sampleRate * 0.035);
        const buffer = c.createBuffer(1, length, c.sampleRate);
        const data = buffer.getChannelData(0);
        // White noise with a steep decay reads as a mechanical shutter snap.
        for (let i = 0; i < length; i++) {
            data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, 6);
        }
        const src = c.createBufferSource();
        src.buffer = buffer;
        const amp = c.createGain();
        amp.gain.value = 0.5 * gain * volume;
        // Band-pass keeps it a "snap" rather than a hiss.
        const filter = c.createBiquadFilter();
        filter.type = 'bandpass';
        filter.frequency.value = 2600;
        filter.Q.value = 0.8;
        src.connect(filter).connect(amp).connect(c.destination);
        src.start(t);
    } catch {
        /* ignore */
    }
}
