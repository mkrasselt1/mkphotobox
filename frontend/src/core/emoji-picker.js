/**
 * Emoji-Picker — gemeinsam für Vorlagen-Editor (Admin) und Gästebuch (Booth).
 *
 * Offline: die Liste (Namen, Suchwörter, Kategorien) liegt als JSON im Repo
 * (core/emoji-list.json, erzeugt von scripts/build-emoji-list.py). Angezeigt
 * werden die Twemoji-SVGs der Box — dieselben Grafiken, aus denen der Server das
 * Foto rendert, die Vorschau zeigt also genau das spätere Emoji. Fehlen die
 * SVGs (install-emoji.sh nicht gelaufen), zeigt der Picker die System-Emojis.
 *
 * Touch-tauglich: große Kacheln, Kategorie-Reiter, Suche (die Bildschirm-
 * tastatur hängt sich automatisch an das Suchfeld).
 */

let dataPromise = null;
let statusPromise = null;

/** Emoji-Liste laden (einmal pro Seite). */
export function loadEmojiData() {
    if (!dataPromise) {
        dataPromise = fetch('/src/core/emoji-list.json')
            .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
            .catch(err => { dataPromise = null; throw err; });
    }
    return dataPromise;
}

/** Status der Emoji-Grafiken auf der Box: {high_res, svg_count, renderer, …}. */
export function emojiStatus() {
    if (!statusPromise) {
        statusPromise = fetch('/api/v1/templates/emoji/status')
            .then(r => r.json())
            .catch(() => ({ high_res: false, svg_count: 0 }));
    }
    return statusPromise;
}

/** Twemoji-Dateiname: FE0F fällt weg, außer in ZWJ-Sequenzen (wie emoji_service.svg_name). */
export function emojiSvgName(emoji) {
    const s = emoji.includes('‍') ? emoji : emoji.replace(/️/g, '');
    return Array.from(s).map(c => c.codePointAt(0).toString(16)).join('-');
}

export function emojiSvgUrl(emoji) {
    return `/api/v1/templates/emoji/${emojiSvgName(emoji)}.svg`;
}

/** Ein Emoji als DOM-Element, das seine Box ganz ausfüllt: SVG wenn vorhanden,
 *  sonst (oder wenn das Bild nicht lädt) das System-Emoji. */
export function emojiElement(emoji, useSvg) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;pointer-events:none;';
    const asText = () => {
        wrap.innerHTML = '';
        const span = document.createElement('span');
        span.textContent = emoji;
        span.style.cssText = 'line-height:1;font-family:"Noto Color Emoji","Apple Color Emoji","Segoe UI Emoji",sans-serif;';
        wrap.appendChild(span);
        // Schriftgröße an die Box anpassen, sobald sie im DOM ist.
        requestAnimationFrame(() => {
            const r = wrap.getBoundingClientRect();
            span.style.fontSize = Math.max(8, Math.min(r.width, r.height) * 0.86) + 'px';
        });
    };
    if (useSvg) {
        const img = document.createElement('img');
        img.src = emojiSvgUrl(emoji);
        img.alt = emoji;
        img.draggable = false;
        img.style.cssText = 'width:100%;height:100%;object-fit:contain;pointer-events:none;';
        img.addEventListener('error', asText, { once: true });
        wrap.appendChild(img);
    } else {
        asText();
    }
    return wrap;
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/**
 * Picker als Vollbild-Overlay öffnen. ``onPick(emoji)`` wird beim Antippen
 * aufgerufen; danach schließt der Picker. Liefert eine close()-Funktion.
 */
export async function openEmojiPicker({ onPick, title = 'Emoji wählen', zIndex = 9500 } = {}) {
    const o = document.createElement('div');
    o.className = 'pb-emoji-picker';
    o.style.cssText = `position:fixed;inset:0;z-index:${zIndex};background:rgba(0,0,0,0.85);` +
        'display:flex;align-items:stretch;justify-content:center;padding:max(1rem, 2vh) 1rem;box-sizing:border-box;';
    o.innerHTML = `
        <div style="width:100%;max-width:900px;display:flex;flex-direction:column;gap:0.6rem;
                    background:var(--pb-color-surface, #16213e);color:var(--pb-color-text, #fff);
                    border-radius:var(--pb-radius, 12px);padding:0.9rem;box-sizing:border-box;min-height:0;">
            <div style="display:flex;gap:0.6rem;align-items:center;">
                <strong style="font-size:1.1rem;white-space:nowrap;">${esc(title)}</strong>
                <input class="ep-search" type="search" placeholder="Suchen… (z. B. Herz, Party, Katze)" autocomplete="off"
                    style="flex:1;min-width:0;min-height:2.75rem;padding:0 0.8rem;border-radius:999px;font-size:1rem;
                           border:1px solid rgba(255,255,255,0.25);background:rgba(0,0,0,0.3);color:inherit;">
                <button class="ep-close" aria-label="Schließen" style="min-width:2.75rem;min-height:2.75rem;border-radius:50%;
                    border:none;background:rgba(127,127,127,0.3);color:inherit;font-size:1.3rem;cursor:pointer;">✕</button>
            </div>
            <div class="ep-tabs" style="display:flex;gap:0.3rem;overflow-x:auto;flex-shrink:0;padding-bottom:0.2rem;"></div>
            <div class="ep-grid" style="flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;
                 display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:0.3rem;align-content:start;">
                <p style="grid-column:1/-1;opacity:0.7;">Lade Emojis…</p>
            </div>
            <p class="ep-foot" style="margin:0;font-size:0.72rem;opacity:0.6;"></p>
        </div>`;
    document.body.appendChild(o);

    const close = () => o.remove();
    o.querySelector('.ep-close').addEventListener('click', close);
    // Tipp neben die Karte schließt — innerhalb nie (Scrollen soll nichts verwerfen).
    o.addEventListener('click', e => { if (e.target === o) close(); });

    let data, status;
    try {
        [data, status] = await Promise.all([loadEmojiData(), emojiStatus()]);
    } catch (err) {
        o.querySelector('.ep-grid').innerHTML = `<p style="grid-column:1/-1;color:var(--pb-color-error,#f66);">
            Emoji-Liste konnte nicht geladen werden (${esc(err.message)}).</p>`;
        return close;
    }
    const useSvg = !!(status && status.svg_count);
    o.querySelector('.ep-foot').textContent = useSvg
        ? 'Emoji-Grafiken: Twemoji © Twitter, Inc. und Mitwirkende, CC-BY 4.0'
        : 'Hinweis: Emoji-Grafiken nicht installiert (scripts/install-emoji.sh) — Druck in geringer Auflösung.';

    const tabs = [{ id: 'fav', icon: '⭐', name: 'Beliebt' }, ...data.groups];
    let current = 'fav';
    const tabBar = o.querySelector('.ep-tabs');
    const grid = o.querySelector('.ep-grid');
    const search = o.querySelector('.ep-search');

    tabBar.innerHTML = tabs.map(t => `
        <button class="ep-tab" data-id="${t.id}" title="${esc(t.name)}" style="flex:0 0 auto;min-width:3.2rem;min-height:3rem;
            font-size:1.5rem;border-radius:10px;cursor:pointer;color:inherit;border:2px solid transparent;
            background:rgba(127,127,127,0.18);">${t.icon}</button>`).join('');

    const cell = (e) => useSvg
        ? `<img src="${emojiSvgUrl(e)}" alt="${esc(e)}" loading="lazy" draggable="false"
                style="width:44px;height:44px;pointer-events:none;"
                onerror="this.replaceWith(document.createTextNode(this.alt))">`
        : esc(e);

    function show(list, heading) {
        grid.innerHTML = (heading ? `<p style="grid-column:1/-1;margin:0.2rem 0;opacity:0.75;font-size:0.9rem;">${esc(heading)}</p>` : '') +
            (list.length ? list.map(([e, label]) => `
                <button class="ep-emoji" data-e="${esc(e)}" title="${esc(label)}" style="height:64px;border:none;border-radius:10px;
                    background:transparent;cursor:pointer;font-size:2.4rem;line-height:1;color:inherit;
                    display:flex;align-items:center;justify-content:center;padding:0;
                    font-family:'Noto Color Emoji','Apple Color Emoji','Segoe UI Emoji',sans-serif;">${cell(e)}</button>`).join('')
                : '<p style="grid-column:1/-1;opacity:0.7;">Nichts gefunden.</p>');
        grid.scrollTop = 0;
    }

    const byEmoji = new Map(data.emojis.map(x => [x[0], x]));
    function showTab(id) {
        current = id;
        tabBar.querySelectorAll('.ep-tab').forEach(b => {
            b.style.borderColor = b.dataset.id === String(id) ? 'var(--pb-color-primary, #4a90d9)' : 'transparent';
        });
        const tab = tabs.find(t => String(t.id) === String(id));
        if (id === 'fav') show(data.favorites.map(e => byEmoji.get(e)).filter(Boolean), tab.name);
        else show(data.emojis.filter(x => String(x[3]) === String(id)), tab.name);
    }

    // Suche: alle Wörter müssen in Name oder Suchwörtern vorkommen (Groß/Klein egal).
    const norm = s => s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
    const index = data.emojis.map(x => norm(`${x[1]} ${x[2]}`));
    let timer = null;
    search.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            const words = norm(search.value.trim()).split(/\s+/).filter(Boolean);
            if (!words.length) { showTab(current); return; }
            tabBar.querySelectorAll('.ep-tab').forEach(b => { b.style.borderColor = 'transparent'; });
            const hits = [];
            for (let i = 0; i < data.emojis.length && hits.length < 300; i++) {
                if (words.every(w => index[i].includes(w))) hits.push(data.emojis[i]);
            }
            show(hits, `${hits.length}${hits.length >= 300 ? '+' : ''} Treffer`);
        }, 150);
    });

    tabBar.addEventListener('click', e => {
        const b = e.target.closest('.ep-tab');
        if (!b) return;
        search.value = '';
        showTab(b.dataset.id === 'fav' ? 'fav' : parseInt(b.dataset.id, 10));
    });
    grid.addEventListener('click', e => {
        const b = e.target.closest('.ep-emoji');
        if (!b) return;
        close();
        onPick?.(b.dataset.e);
    });

    showTab('fav');
    return close;
}
