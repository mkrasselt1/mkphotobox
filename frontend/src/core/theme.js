/**
 * Theme applier — injects the configured colours/sizes/background as CSS
 * variables + overrides. Default values equal index.html, so an unchanged theme
 * looks identical. Optional rules (ui_scale, heading_scale/font, background
 * image) are only emitted when set, to avoid clobbering per-element styling.
 */

export function buildThemeCss(t) {
    if (!t) return '';
    const v = [];
    const root = [];
    const push = (cond, decl) => { if (cond) root.push(decl); };
    push(t.primary, `--pb-color-primary:${t.primary};--pb-color-primary-hover:${t.primary};`);
    push(t.secondary, `--pb-color-secondary:${t.secondary};`);
    push(t.accent, `--pb-color-accent:${t.accent};`);
    push(t.background, `--pb-color-background:${t.background};`);
    push(t.surface, `--pb-color-surface:${t.surface};`);
    push(t.text, `--pb-color-text:${t.text};`);
    push(t.text_muted, `--pb-color-text-muted:${t.text_muted};`);
    push(t.primary && t.secondary, `--pb-gradient:linear-gradient(135deg, ${t.primary} 0%, ${t.secondary} 100%);`);
    if (t.radius != null && t.radius !== '') root.push(`--pb-radius:${parseInt(t.radius)}px;`);
    if (t.heading_font) root.push(`--pb-heading-font:${t.heading_font};`);
    if (root.length) v.push(`:root{${root.join('')}}`);

    const ui = parseFloat(t.ui_scale);
    if (ui && Math.abs(ui - 1) > 0.001) v.push(`html{font-size:${(16 * ui).toFixed(1)}px;}`);

    const hs = parseFloat(t.heading_scale);
    if (hs && Math.abs(hs - 1) > 0.001) {
        // scale the booth's responsive clamp so headings stay fluid
        v.push(`h1{font-size:clamp(${(2 * hs).toFixed(2)}rem, ${(6 * hs).toFixed(1)}vw, ${(3.5 * hs).toFixed(2)}rem) !important;}`);
        v.push(`h2{font-size:clamp(${(1.4 * hs).toFixed(2)}rem, ${(4 * hs).toFixed(1)}vw, ${(2.2 * hs).toFixed(2)}rem) !important;}`);
    }
    if (t.heading_font) v.push(`h1,h2,.admin-brand{font-family:${t.heading_font} !important;}`);

    if (t.background_image) {
        const dim = Math.max(0, Math.min(1, parseFloat(t.background_dim) || 0));
        v.push(`body{background-image:linear-gradient(rgba(0,0,0,${dim}),rgba(0,0,0,${dim})), url("${t.background_image}") !important;`
            + `background-size:cover !important;background-position:center !important;background-attachment:fixed !important;background-repeat:no-repeat !important;}`);
    }
    return v.join('\n');
}

export function applyThemeObject(t) {
    let el = document.getElementById('pb-theme');
    if (!el) {
        el = document.createElement('style');
        el.id = 'pb-theme';
        document.head.appendChild(el);
    }
    el.textContent = buildThemeCss(t);
}

export async function applyTheme() {
    try {
        const t = await fetch('/api/v1/theme').then(r => r.json());
        applyThemeObject(t);
    } catch { /* keep shipped defaults */ }
}
