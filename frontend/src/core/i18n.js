/**
 * I18n — Simple translation system.
 */

export class I18n {
    constructor() {
        this.locale = 'de';
        this.messages = {};
    }

    async load(lang) {
        try {
            this.messages = await fetch(`/api/v1/i18n/${lang}`).then(r => r.json());
            this.locale = lang;
        } catch {
            console.warn('Failed to load locale:', lang);
        }
    }

    t(key, params = {}) {
        let str = this.messages[key] || key;
        for (const [k, v] of Object.entries(params)) {
            str = str.replace(`{${k}}`, v);
        }
        return str;
    }
}
