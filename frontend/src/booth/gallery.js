/**
 * Gallery page — shows all photos from the active event.
 * Uses GLightbox for lightbox/slideshow with action buttons.
 * Respects gallery.delete_mode config: "off" | "recent" | "all"
 */

export function render(container, state) {
    const { i18n } = window.pb;
    let photos = [];
    let lightbox = null;
    let deleteMode = 'off';
    let deleteRecentMinutes = 5;
    let shareBase = location.origin;
    let remoteGallery = null;   // {active, gallery_url, image_base} when off-box gallery is live
    let availableOutputs = [];

    container.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;padding:1.5rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;">
            <h1 style="font-size:1.6rem;font-weight:700;">${i18n.t('gallery.title')}</h1>
            <a href="#/booth" class="gallery-back">&larr; Zur&uuml;ck</a>
        </div>
        <div id="gallery-grid" style="
            display:grid;
            grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
            grid-auto-rows:200px;
            gap:0.9rem;
            align-content:start;
            overflow-y:auto;
            min-height:0;
            flex:1;
        ">
            <p style="color:var(--pb-color-text-muted);grid-column:1/-1;text-align:center;padding:2rem;">
                ${i18n.t('app.loading')}
            </p>
        </div>
    </div>
    <style>
        .gallery-back {
            color:#fff;text-decoration:none;font-size:1rem;font-weight:600;
            padding:0.5rem 1.1rem;border-radius:10px;
            background:rgba(108,140,255,0.12);border:1.5px solid var(--pb-color-primary);
        }
        .gallery-back:hover { background:rgba(108,140,255,0.25); }
        .gallery-item {
            height:100%; border-radius:14px; overflow:hidden;
            cursor:pointer; position:relative;
            background:var(--pb-color-surface-2,#232c4a);
            border:1px solid var(--pb-color-border,#2a3a5e);
            box-shadow:0 4px 14px rgba(0,0,0,0.30);
            transition:transform 0.15s, box-shadow 0.15s;
        }
        .gallery-item:hover { transform:translateY(-2px); box-shadow:0 8px 22px rgba(0,0,0,0.45); }
        .gallery-item img {
            width:100%;height:100%;object-fit:cover; transition:transform 0.3s;
        }
        .gallery-item:hover img { transform:scale(1.06); }
        .gallery-item .gif-badge {
            position:absolute; top:6px; right:6px; background:rgba(108,140,255,0.92);
            color:#fff; font-size:0.8rem; font-weight:700; padding:6px 10px;
            border:none; border-radius:8px; letter-spacing:0.5px; cursor:pointer;
            z-index:2; min-height:32px; box-shadow:0 2px 8px rgba(0,0,0,0.35);
        }
        .gallery-item .gif-badge.playing { background:rgba(231,76,60,0.95); }
        .gallery-item .gif-badge:active { transform:scale(0.94); }
        /* Upscale lightbox media (small GIFs) to fill the viewport like full-res
           photos do — fixed box + object-fit:contain keeps the aspect ratio. */
        .glightbox-container .gslide-image img {
            width:94vw !important; height:82vh !important; object-fit:contain !important;
            max-width:94vw !important; max-height:82vh !important;
        }
        .gslide-description { background:transparent !important; }
        .gdesc-inner { padding:0.5rem 0 !important; }
        .pb-gallery-actions {
            display:flex; gap:0.5rem; justify-content:center; flex-wrap:wrap;
            padding:0.25rem 0;
        }
        .pb-gallery-actions .ga-btn {
            padding:0.6rem 1.2rem; border-radius:8px; border:none; cursor:pointer;
            font-size:0.9rem; color:white; display:inline-flex; align-items:center;
            gap:0.4rem; text-decoration:none; min-height:44px;
        }
        .pb-gallery-actions .ga-btn:active { transform:scale(0.95); }
    </style>`;

    loadGallery();

    async function loadGallery() {
        const grid = document.getElementById('gallery-grid');
        try {
            // Fetch config and gallery data in parallel
            const [configRes, eventRes] = await Promise.all([
                fetch('/api/v1/display/config'),
                fetch('/api/v1/events/active'),
            ]);
            if (configRes.ok) {
                const cfg = await configRes.json();
                deleteMode = cfg.gallery_delete_mode || 'off';
                deleteRecentMinutes = cfg.gallery_delete_recent_minutes || 5;
            }

            try {
                const sb = await fetch('/api/v1/system/share-base').then(r => r.json());
                shareBase = sb.base_url || location.origin;
                remoteGallery = sb.remote_gallery || null;
            } catch {}
            try {
                availableOutputs = await fetch('/api/v1/outputs/available').then(r => r.json()).then(o => (o || []).map(x => x.name));
            } catch { availableOutputs = []; }

            const event = await eventRes.json();
            if (!event || !event.slug) {
                grid.innerHTML = `<p style="color:var(--pb-color-text-muted);grid-column:1/-1;text-align:center;padding:2rem;">${i18n.t('gallery.empty')}</p>`;
                return;
            }

            const res = await fetch(`/api/v1/gallery/${event.slug}?limit=100`);
            photos = await res.json();

            if (!photos.length) {
                grid.innerHTML = `<p style="color:var(--pb-color-text-muted);grid-column:1/-1;text-align:center;padding:2rem;">${i18n.t('gallery.empty')}</p>`;
                return;
            }

            renderGrid(grid);
        } catch (err) {
            grid.innerHTML = `<p style="color:var(--pb-color-error);grid-column:1/-1;text-align:center;padding:2rem;">Fehler: ${err.message}</p>`;
        }
    }

    function renderGrid(grid) {
        grid.innerHTML = photos.map((p, idx) => {
            const fileUrl = `/api/v1/photos/${p.id}/file`;
            const thumbUrl = `/api/v1/photos/${p.id}/thumb`;
            const gifUrl = `/api/v1/photos/${p.id}/gif`;
            const hasGif = !!p.gif_filename;
            return `
            <div class="gallery-item" data-idx="${idx}" ${hasGif ? `data-gif="${gifUrl}" data-thumb="${thumbUrl}"` : ''}>
                <img src="${thumbUrl}" alt="Foto ${p.id}"
                     onerror="this.src='${fileUrl}'" loading="lazy">
                ${hasGif ? '<button class="gif-badge" data-state="still">GIF&nbsp;▶</button>' : ''}
            </div>`;
        }).join('');

        grid.querySelectorAll('.gallery-item').forEach(item => {
            item.addEventListener('click', () => openLightbox(parseInt(item.dataset.idx)));
            // GIF items: hover-play on desktop + a tappable badge to toggle on touch
            if (item.dataset.gif) {
                const img = item.querySelector('img');
                const badge = item.querySelector('.gif-badge');
                const playing = () => badge.dataset.state === 'playing';
                item.addEventListener('pointerenter', () => { if (!playing()) img.src = item.dataset.gif; });
                item.addEventListener('pointerleave', () => { if (!playing()) img.src = item.dataset.thumb; });
                badge.addEventListener('click', (e) => {
                    e.stopPropagation();   // don't open the lightbox
                    if (playing()) {
                        badge.dataset.state = 'still'; badge.classList.remove('playing');
                        badge.innerHTML = 'GIF&nbsp;▶'; img.src = item.dataset.thumb;
                    } else {
                        badge.dataset.state = 'playing'; badge.classList.add('playing');
                        badge.innerHTML = 'Foto'; img.src = item.dataset.gif;
                    }
                });
            }
        });
    }

    function canDelete(photo) {
        if (deleteMode === 'all') return true;
        if (deleteMode === 'off') return false;
        // "recent" — only if photo is within the time window
        const capturedAt = new Date(photo.captured_at).getTime();
        const cutoff = Date.now() - deleteRecentMinutes * 60 * 1000;
        return capturedAt >= cutoff;
    }

    function openLightbox(startIdx) {
        const slides = photos.map(p => ({
            href: p.gif_filename ? `/api/v1/photos/${p.id}/gif` : `/api/v1/photos/${p.id}/file`,
            type: 'image',
            description: buildActions(p),
        }));

        if (lightbox) lightbox.destroy();

        lightbox = GLightbox({
            elements: slides,
            startAt: startIdx,
            touchNavigation: true,
            loop: true,
            closeOnOutsideClick: true,
            skin: 'clean',
            descPosition: 'bottom',
            openEffect: 'fade',
            closeEffect: 'fade',
        });

        lightbox.on('open', () => {
            // Force the correct slide to render on open
            lightbox.goToSlide(startIdx);
        });

        lightbox.open();

        lightbox.on('close', () => {
            document.removeEventListener('click', onActionClick);
        });
        document.addEventListener('click', onActionClick);
    }

    function buildActions(photo) {
        const fileUrl = `/api/v1/photos/${photo.id}/file`;
        const ico = `style="font-size:2.5rem;line-height:1;"`;
        const gifUrl = `/api/v1/photos/${photo.id}/gif`;
        // Only the QR link (what a guest's phone scans) may point off-box to the
        // remote gallery; the on-screen download link stays box-local (LAN).
        const baseName = (p) => (p || '').split(/[/\\]/).pop();
        const qrUrl = (remoteGallery?.active && photo.filename)
            ? `${remoteGallery.image_base}/${baseName(photo.filename)}`
            : `${shareBase}${fileUrl}`;
        let html = `<div class="pb-gallery-actions">
            <a href="${fileUrl}" download class="ga-btn" style="background:#4a90d9;"><span ${ico}>\u2B07</span> ${i18n.t('share.download')}</a>
            ${availableOutputs.includes('output.printer') ? `<button class="ga-btn ga-print" data-id="${photo.id}" style="background:#8e44ad;"><span ${ico}>\uD83D\uDDA8</span> ${i18n.t('share.print')}</button>` : ''}
            <button class="ga-btn ga-qr" data-url="${qrUrl}" style="background:#2c3e50;"><span ${ico}>\uD83D\uDD17</span> ${i18n.t('share.qr_code')}</button>`;
        if (photo.gif_filename) {
            // The lightbox opens GIF photos as the animation by default \u2192 offer a still toggle
            html += `<button class="ga-btn ga-toggle" data-still="${fileUrl}" data-gif="${gifUrl}" data-showing="gif" style="background:#16a085;"><span ${ico}>\uD83D\uDCF7</span> Standbild</button>`;
        }
        if (canDelete(photo)) {
            html += `<button class="ga-btn ga-delete" data-id="${photo.id}" style="background:#e74c3c;"><span ${ico}>\uD83D\uDDD1</span> L\u00f6schen</button>`;
        }
        html += `</div>`;
        return html;
    }

    function onActionClick(e) {
        const printBtn = e.target.closest('.ga-print');
        if (printBtn) {
            e.preventDefault();
            e.stopPropagation();
            printBtn.disabled = true;
            printBtn.innerHTML = '...';
            fetch('/api/v1/outputs/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ photo_id: parseInt(printBtn.dataset.id), module: 'output.printer' }),
            }).then(r => r.json().then(result => ({ ok: r.ok, result }))).then(({ ok, result }) => {
                if (result && result.status === 'blocked') {          // near-empty: refused
                    printBtn.innerHTML = '⛔ ' + (result.message || 'Kein Medium');
                    printBtn.style.background = 'var(--pb-color-error)';
                    printBtn.disabled = false;
                } else if (ok && result && result.warning) {           // printed but low
                    printBtn.innerHTML = `&#9888; noch ${result.remaining ?? ''}`;
                    printBtn.style.background = '#c77b1a';
                } else {
                    printBtn.innerHTML = ok ? `&#10003; ${i18n.t('share.print_started')}` : '&#10007; Fehler';
                    printBtn.style.background = ok ? 'var(--pb-color-success)' : 'var(--pb-color-error)';
                }
            }).catch(() => {
                printBtn.innerHTML = '&#10007; Fehler';
                printBtn.style.background = 'var(--pb-color-error)';
            });
            return;
        }

        const qrBtn = e.target.closest('.ga-qr');
        if (qrBtn) {
            e.preventDefault();
            e.stopPropagation();
            const actions = qrBtn.closest('.pb-gallery-actions');
            const existing = actions?.querySelector('.qr-display');
            if (existing) { existing.remove(); return; }
            const qrDiv = document.createElement('div');
            qrDiv.className = 'qr-display';
            qrDiv.style.cssText = 'width:100%;padding:1rem;background:white;border-radius:8px;margin-top:0.5rem;text-align:center;';
            try {
                const qr = qrcode(0, 'M');
                qr.addData(qrBtn.dataset.url);
                qr.make();
                qrDiv.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2 });
            } catch {
                qrDiv.innerHTML = `<p style="color:#000;font-size:0.85rem;word-break:break-all;margin:0;">${qrBtn.dataset.url}</p>`;
            }
            actions?.appendChild(qrDiv);
            return;
        }

        const toggleBtn = e.target.closest('.ga-toggle');
        if (toggleBtn) {
            e.preventDefault();
            e.stopPropagation();
            const img = document.querySelector('.gslide.current .gslide-media img')
                || document.querySelector('.gslide.current img');
            if (img) {
                const next = toggleBtn.dataset.showing === 'gif' ? 'still' : 'gif';
                img.src = next === 'gif' ? toggleBtn.dataset.gif : toggleBtn.dataset.still;
                toggleBtn.dataset.showing = next;
                toggleBtn.innerHTML = next === 'gif'
                    ? '<span style="font-size:2.5rem;line-height:1;">📷</span> Standbild'
                    : '<span style="font-size:2.5rem;line-height:1;">🎞</span> GIF';
            }
            return;
        }

        const deleteBtn = e.target.closest('.ga-delete');
        if (deleteBtn) {
            e.preventDefault();
            e.stopPropagation();
            const photoId = parseInt(deleteBtn.dataset.id);
            if (!confirm('Foto wirklich löschen?')) return;
            deleteBtn.disabled = true;
            deleteBtn.innerHTML = '...';
            fetch(`/api/v1/photos/${photoId}`, { method: 'DELETE' }).then(async res => {
                if (res.ok) {
                    photos = photos.filter(p => p.id !== photoId);
                    if (lightbox) lightbox.close();
                    const grid = document.getElementById('gallery-grid');
                    if (grid) {
                        if (photos.length) renderGrid(grid);
                        else grid.innerHTML = `<p style="color:var(--pb-color-text-muted);grid-column:1/-1;text-align:center;padding:2rem;">${i18n.t('gallery.empty')}</p>`;
                    }
                } else {
                    let detail = `HTTP ${res.status}`;
                    try { detail = (await res.json()).detail || detail; } catch {}
                    deleteBtn.innerHTML = '&#10007; Fehler';
                    deleteBtn.style.background = 'var(--pb-color-error)';
                    deleteBtn.title = detail;
                    alert('Löschen fehlgeschlagen: ' + detail);
                }
            }).catch((err) => {
                deleteBtn.innerHTML = '&#10007; Fehler';
                alert('Löschen fehlgeschlagen: ' + err.message);
            });
        }
    }

    // Cleanup on route change
    window.addEventListener('hashchange', () => {
        if (lightbox) lightbox.destroy();
        document.removeEventListener('click', onActionClick);
    }, { once: true });
}
