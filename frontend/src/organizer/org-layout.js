/**
 * Organizer Layout — Simplified admin for event organizers.
 */

export function render(container, state) {
    const { i18n } = window.pb;

    container.innerHTML = `
    <div style="display:flex;height:100%;">
        <nav style="width:200px;background:var(--pb-color-surface);padding:1rem;display:flex;flex-direction:column;gap:0.5rem;">
            <h2 style="font-size:1.1rem;margin-bottom:1rem;">Veranstalter</h2>
            <a href="#/organizer" class="nav-item">${i18n.t('organizer.dashboard')}</a>
            <a href="#/organizer/event" class="nav-item">${i18n.t('organizer.event_setup')}</a>
            <a href="#/organizer/theme" class="nav-item">${i18n.t('organizer.theme')}</a>
            <div style="flex:1;"></div>
            <a href="#/booth" class="nav-item" style="color:var(--pb-color-text-muted);">&larr; Booth</a>
        </nav>
        <main style="flex:1;padding:2rem;overflow-y:auto;">
            <h1>${i18n.t('organizer.dashboard')}</h1>
            <p style="margin-top:1rem;color:var(--pb-color-text-muted);">Veranstalter-Bereich wird geladen...</p>
        </main>
    </div>
    <style>
        .nav-item { display:block;padding:0.75rem 1rem;border-radius:8px;color:var(--pb-color-text);text-decoration:none; }
        .nav-item:hover { background:rgba(255,255,255,0.1); }
    </style>`;
}
