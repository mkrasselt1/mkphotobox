/**
 * Router — Hash-based routing with lazy-loaded page components.
 * Sub-routes like #/admin/cameras are supported: base="admin", sub="cameras".
 */

export class Router {
    constructor(state) {
        this.state = state;
        this.app = document.getElementById('app');
        this.routes = {
            'booth':              () => import('../booth/booth-flow.js'),
            'gallery':            () => import('../booth/gallery.js'),
            'login':              () => import('../core/login.js'),
            'setup':              () => import('../setup/setup-wizard.js'),
            'admin':              () => import('../admin/admin-dashboard.js'),
            'admin/dashboard':    () => import('../admin/admin-dashboard.js'),
            'admin/cameras':      () => import('../admin/admin-cameras.js'),
            'admin/modules':      () => import('../admin/admin-modules.js'),
            'admin/events':       () => import('../admin/admin-events.js'),
            'admin/presets':      () => import('../admin/admin-presets.js'),
            'admin/remote-gallery': () => import('../admin/admin-remote-gallery.js'),
            'admin/printer':      () => import('../admin/admin-printer.js'),
            'admin/cd-burn':      () => import('../admin/admin-cd-burn.js'),
            'admin/usb-export':   () => import('../admin/admin-usb-export.js'),
            'admin/assets':       () => import('../admin/admin-assets.js'),
            'admin/templates':    () => import('../admin/admin-templates.js'),
            'admin/wifi':         () => import('../admin/admin-wifi.js'),
            'admin/network':      () => import('../admin/admin-network.js'),
            'admin/payment':      () => import('../admin/admin-payment.js'),
            'admin/telegram':     () => import('../admin/admin-telegram.js'),
            'admin/settings':     () => import('../admin/admin-settings.js'),
            'admin/appearance':   () => import('../admin/admin-appearance.js'),
            'admin/permissions':  () => import('../admin/admin-permissions.js'),
            'admin/background':   () => import('../admin/admin-background.js'),
            'admin/triggers':     () => import('../admin/admin-triggers.js'),
            'admin/tests':        () => import('../admin/admin-tests.js'),
            'admin/help':         () => import('../admin/admin-help.js'),
            'organizer':          () => import('../organizer/org-layout.js'),
        };

        window.addEventListener('hashchange', () => this.handleRoute());
    }

    navigate(route) {
        location.hash = `#/${route}`;
    }

    handleRoute() {
        const hash = location.hash.replace('#/', '') || 'booth';
        const base = hash.split('/')[0];
        this.state.currentRoute = hash;

        // Auth gate
        if (base === 'admin') {
            const role = this.state.auth.role;
            if (role === 'admin') {
                // full access
            } else if (role === 'organizer') {
                // Mieter: only the sections granted by the admin
                const sub = hash.split('/')[1] || 'dashboard';
                const sections = this.state.auth.sections || [];
                if (!sections.includes(sub)) {
                    const target = sections.find(s => s !== 'dashboard') || sections[0];
                    this.navigate(target ? `admin/${target}` : 'booth');
                    return;
                }
            } else {
                this.navigate('login');
                return;
            }
        }
        if (base === 'organizer' && !['admin', 'organizer'].includes(this.state.auth.role)) {
            this.navigate('login');
            return;
        }

        const loader = this.routes[hash] || this.routes[base];
        if (loader) {
            loader().then(mod => {
                if (mod.render) {
                    this.app.innerHTML = '';
                    mod.render(this.app, this.state);
                }
            }).catch(err => {
                console.error('Route load error:', err);
                this.app.innerHTML = `<div style="padding:2rem;text-align:center;">
                    <h2>Fehler beim Laden</h2>
                    <p>${err.message}</p>
                </div>`;
            });
        } else {
            this.navigate('booth');
        }
    }
}
