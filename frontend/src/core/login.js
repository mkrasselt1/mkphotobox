/**
 * Login page.
 */

export function render(container, state) {
    const { i18n } = window.pb;

    container.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:center;height:100%;padding:2rem;">
        <div style="background:var(--pb-color-surface);border-radius:var(--pb-radius);padding:2rem;width:100%;max-width:400px;">
            <h2 style="margin-bottom:1.5rem;text-align:center;">${i18n.t('auth.login')}</h2>
            <form id="login-form" style="display:flex;flex-direction:column;gap:1rem;">
                <input type="text" id="username" placeholder="${i18n.t('auth.username')}"
                    style="padding:12px;border-radius:8px;border:1px solid #333;background:#0e1a30;color:white;font-size:1rem;">
                <input type="password" id="password" placeholder="${i18n.t('auth.password')}"
                    style="padding:12px;border-radius:8px;border:1px solid #333;background:#0e1a30;color:white;font-size:1rem;">
                <button type="submit"
                    style="padding:14px;border-radius:8px;border:none;background:var(--pb-color-primary);color:white;font-size:1rem;cursor:pointer;min-height:var(--pb-touch-target);">
                    ${i18n.t('auth.login')}
                </button>
                <p id="login-error" style="color:var(--pb-color-error);text-align:center;display:none;"></p>
            </form>
            <p style="text-align:center;margin-top:1rem;">
                <a href="#/booth" style="color:var(--pb-color-text-muted);text-decoration:none;">
                    &larr; ${i18n.t('booth.welcome')}
                </a>
            </p>
        </div>
    </div>`;

    container.querySelector('#login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = container.querySelector('#username').value;
        const password = container.querySelector('#password').value;
        const errorEl = container.querySelector('#login-error');

        try {
            const res = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            if (!res.ok) throw new Error(i18n.t('auth.invalid_credentials'));
            const data = await res.json();
            state.setAuth(data.token, data.role, data.username);

            // Reconnect WS with new token
            window.pb.ws.connect();

            // Navigate based on role
            if (data.role === 'admin') {
                window.pb.router.navigate('admin');
            } else if (data.role === 'organizer') {
                window.pb.router.navigate('organizer');
            } else {
                window.pb.router.navigate('booth');
            }
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.style.display = 'block';
        }
    });
}
