/**
 * On-Screen Keyboard (OSK) — global touch keyboard for the photobox.
 *
 * Auto-attaches to any focused text input / textarea (opt out with
 * `data-no-osk`). German QWERTZ layout with umlauts + an email/number layer.
 * Inserts at the caret and fires `input` events so existing handlers react.
 */

const INPUT_SELECTOR = [
    'input:not([type=checkbox]):not([type=radio]):not([type=range])',
    'input:not([type=file]):not([type=color]):not([type=button]):not([type=submit])',
    'textarea',
].join(',');

const LETTERS = [
    ['q', 'w', 'e', 'r', 't', 'z', 'u', 'i', 'o', 'p', 'ü'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'ö', 'ä'],
    ['⇧', 'y', 'x', 'c', 'v', 'b', 'n', 'm', 'ß', '⌫'],
    ['?123', '@', '␣', '.', '↵', '✕'],
];

const SYMBOLS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['@', '.', '-', '_', '/', ':', '+', '=', '#', '!'],
    ['=\\<', ',', '?', '(', ')', '%', '&', '*', '"', '⌫'],
    ['ABC', '.de', '␣', '.com', '↵', '✕'],
];

// Second symbol page — currencies, brackets and the rest of the characters
// that turn up in WiFi passwords. Reached via the `=\<` key, back via `?123`.
const SYMBOLS2 = [
    ['$', '€', '£', '¥', '¢', '§', '°', '^', '~', '`'],
    ['[', ']', '{', '}', '<', '>', '\\', '|', ';', "'"],
    ['?123', '±', '×', '÷', 'µ', '¿', '¡', '…', '⌫'],
    ['ABC', '.de', '␣', '.com', '↵', '✕'],
];

let target = null;
let shift = false;
let layer = 'letters';
let panel = null;
let lastPressTs = 0;
let lastPressKey = '';

export function initOSK() {
    if (panel) return;
    panel = document.createElement('div');
    panel.id = 'pb-osk';
    panel.setAttribute('data-no-osk', '');
    document.body.appendChild(panel);
    injectStyles();
    render();

    document.addEventListener('focusin', (e) => {
        if (e.target.closest('#pb-osk')) return;
        if (e.target.matches?.(INPUT_SELECTOR) && !e.target.hasAttribute('data-no-osk')) {
            target = e.target;
            show();
        }
    });

    document.addEventListener('focusout', (e) => {
        // Key presses preventDefault focus loss, so this only fires on real exits
        setTimeout(() => {
            const a = document.activeElement;
            if (!a || (!a.matches?.(INPUT_SELECTOR) && !a.closest?.('#pb-osk'))) hide();
        }, 50);
    });
}

function show() { panel.classList.add('visible'); }
function hide() { panel.classList.remove('visible'); target = null; }

function activeLayout() {
    if (layer === 'symbols') return SYMBOLS;
    if (layer === 'symbols2') return SYMBOLS2;
    return LETTERS.map(row => row.map(k => (shift && k.length === 1 && /[a-zäöüß]/.test(k)) ? k.toUpperCase() : k));
}

// Keys go into an HTML attribute and a text node, so they must be escaped —
// otherwise `"` closes data-key early (that key inserted nothing at all) and
// `<`, `>`, `&` are parsed as markup instead of shown.
function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function render() {
    panel.innerHTML = activeLayout().map(row =>
        `<div class="osk-row">${row.map(key => {
            const wide = ['␣'].includes(key);
            const special = ['⇧', '⌫', '?123', '=\\<', 'ABC', '↵', '✕', '␣', '.de', '.com'].includes(key);
            const label = key === '␣' ? 'Leerzeichen' : key === '⌫' ? '⌫' : key;
            return `<button class="osk-key${wide ? ' wide' : ''}${special ? ' special' : ''}${key === '⇧' && shift ? ' active' : ''}" data-key="${esc(key)}">${esc(label)}</button>`;
        }).join('')}</div>`
    ).join('');

    panel.querySelectorAll('.osk-key').forEach(btn => {
        // pointerdown + preventDefault keeps the caret in the input.
        // Dedupe duplicate events some touchscreens emit (otherwise every
        // character is entered twice). We use performance.now() — a monotonic
        // clock — because e.timeStamp can have different time origins for touch
        // vs. mouse-compatibility events, which made the old guard unreliable.
        btn.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            e.stopImmediatePropagation();
            handlePress(btn.dataset.key);
        });
        // A real device "bounce" / duplicate can also arrive as a mouse event;
        // pointerdown already handled it, so suppress these to avoid a 2nd char.
        btn.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopImmediatePropagation(); });
        btn.addEventListener('click', (e) => { e.preventDefault(); e.stopImmediatePropagation(); });
    });
}

function handlePress(key) {
    // Drop a duplicate of the SAME key within a short window (device bounce /
    // duplicated event). 180ms is comfortably below a deliberate double-tap of
    // the same character but absorbs hardware double-fires.
    const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    if (key === lastPressKey && (now - lastPressTs) < 180) return;
    lastPressTs = now;
    lastPressKey = key;
    press(key);
}

function press(key) {
    switch (key) {
        case '⇧': shift = !shift; return render();
        case '⌫': return backspace();
        case '?123': layer = 'symbols'; return render();
        case '=\\<': layer = 'symbols2'; return render();
        case 'ABC': layer = 'letters'; return render();
        case '␣': return insert(' ');
        case '↵': return enter();
        case '✕': return hide();
        default:
            insert(key);
            if (shift && layer === 'letters') { shift = false; render(); }
    }
}

/**
 * Current caret as [start, end].
 *
 * input[type=number] and [type=email] don't support selection: per spec the
 * getters return null, older engines throw. Both mean "no caret", so we work
 * at the end of the value.
 */
function caretRange(el) {
    try {
        const start = el.selectionStart;
        if (start === null || start === undefined) return [el.value.length, el.value.length];
        return [start, el.selectionEnd ?? start];
    } catch {
        return [el.value.length, el.value.length];
    }
}

/**
 * Move the caret, tolerating types that don't support it.
 *
 * Must stay separate from the value update: setSelectionRange throws on
 * number/email inputs, and when that throw shared a try-block with the
 * assignment, the catch re-appended the character — every digit landed twice.
 */
function setCaret(el, pos) {
    try { el.setSelectionRange(pos, pos); } catch { /* type has no caret */ }
}

function insert(text) {
    const el = target;
    if (!el) return;
    const [start, end] = caretRange(el);
    el.value = el.value.slice(0, start) + text + el.value.slice(end);
    setCaret(el, start + text.length);
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function backspace() {
    const el = target;
    if (!el) return;
    const [start, end] = caretRange(el);
    if (start === end) {
        if (start === 0) return;               // nothing before the caret
        el.value = el.value.slice(0, start - 1) + el.value.slice(end);
        setCaret(el, start - 1);
    } else {
        el.value = el.value.slice(0, start) + el.value.slice(end);
        setCaret(el, start);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function enter() {
    const el = target;
    if (!el) return;
    if (el.tagName === 'TEXTAREA') return insert('\n');
    el.dispatchEvent(new Event('change', { bubbles: true }));
    const form = el.closest('form');
    if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    hide();
}

function injectStyles() {
    const s = document.createElement('style');
    s.textContent = `
    #pb-osk {
        position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999;
        background: var(--pb-color-surface, #16213e);
        border-top: 1px solid rgba(255,255,255,0.12);
        box-shadow: 0 -8px 30px rgba(0,0,0,0.45);
        padding: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem;
        transform: translateY(110%); transition: transform 0.22s ease;
        max-width: 920px; margin: 0 auto; border-radius: 16px 16px 0 0;
    }
    #pb-osk.visible { transform: translateY(0); }
    .osk-row { display: flex; gap: 0.4rem; justify-content: center; }
    .osk-key {
        flex: 1 1 0; min-width: 0; height: 52px; border: none; cursor: pointer;
        border-radius: 10px; font-size: 1.1rem; font-weight: 600;
        background: #2a3a5e; color: #fff; transition: background 0.1s, transform 0.05s;
        user-select: none; -webkit-user-select: none;
    }
    .osk-key:active { transform: scale(0.94); background: var(--pb-color-primary, #4a90d9); }
    .osk-key.special { background: #1f2c4a; color: var(--pb-color-text-muted, #cbd5e1); font-size: 0.95rem; }
    .osk-key.active { background: var(--pb-color-primary, #4a90d9); color: #fff; }
    .osk-key.wide { flex: 4 1 0; }
    @media (max-width: 600px) { .osk-key { height: 46px; font-size: 1rem; } }
    `;
    document.head.appendChild(s);
}
