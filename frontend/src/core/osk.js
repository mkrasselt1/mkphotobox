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
    [',', '?', '(', ')', '%', '&', '*', '"', '⌫'],
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
    return LETTERS.map(row => row.map(k => (shift && k.length === 1 && /[a-zäöüß]/.test(k)) ? k.toUpperCase() : k));
}

function render() {
    panel.innerHTML = activeLayout().map(row =>
        `<div class="osk-row">${row.map(key => {
            const wide = ['␣'].includes(key);
            const special = ['⇧', '⌫', '?123', 'ABC', '↵', '✕', '␣', '.de', '.com'].includes(key);
            const label = key === '␣' ? 'Leerzeichen' : key === '⌫' ? '⌫' : key;
            return `<button class="osk-key${wide ? ' wide' : ''}${special ? ' special' : ''}${key === '⇧' && shift ? ' active' : ''}" data-key="${key}">${label}</button>`;
        }).join('')}</div>`
    ).join('');

    panel.querySelectorAll('.osk-key').forEach(btn => {
        // pointerdown + preventDefault keeps the caret in the input.
        // Dedupe duplicate pointer/mouse events some touchscreens emit
        // (otherwise every character would be entered twice).
        btn.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            const key = btn.dataset.key;
            if (key === lastPressKey && (e.timeStamp - lastPressTs) < 60) return;
            lastPressTs = e.timeStamp;
            lastPressKey = key;
            press(key);
        });
    });
}

function press(key) {
    switch (key) {
        case '⇧': shift = !shift; return render();
        case '⌫': return backspace();
        case '?123': layer = 'symbols'; return render();
        case 'ABC': layer = 'letters'; return render();
        case '␣': return insert(' ');
        case '↵': return enter();
        case '✕': return hide();
        default:
            insert(key);
            if (shift && layer === 'letters') { shift = false; render(); }
    }
}

function insert(text) {
    const el = target;
    if (!el) return;
    try {
        const start = el.selectionStart ?? el.value.length;
        const end = el.selectionEnd ?? el.value.length;
        el.value = el.value.slice(0, start) + text + el.value.slice(end);
        const pos = start + text.length;
        el.setSelectionRange(pos, pos);
    } catch {
        // number/email inputs may not support selection — just append
        el.value += text;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function backspace() {
    const el = target;
    if (!el) return;
    try {
        const start = el.selectionStart, end = el.selectionEnd;
        if (start === end && start > 0) {
            el.value = el.value.slice(0, start - 1) + el.value.slice(end);
            el.setSelectionRange(start - 1, start - 1);
        } else {
            el.value = el.value.slice(0, start) + el.value.slice(end);
            el.setSelectionRange(start, start);
        }
    } catch {
        el.value = el.value.slice(0, -1);
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
