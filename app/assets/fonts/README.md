# Template fonts

Fonts available for **text elements** in photo templates (see the template editor).

`collage_service` searches this folder first, then the system font directories
(`/usr/share/fonts`, Windows `Fonts`, etc.). The label → filename mapping lives in
`app/services/collage_service.py` → `FONT_FILES`.

## Add nice script/handwriting fonts

```bash
./scripts/install-fonts.sh
```

downloads free OFL fonts (Pacifico, Great Vibes, Lobster, Sacramento, Satisfy,
Parisienne, Dancing Script, Comic Neue) into this folder.

## Add your own

1. Drop a `.ttf`/`.otf` here.
2. Add a label and the filename to `FONT_FILES` in `collage_service.py`.
3. Optionally add a CSS fallback in `frontend/src/admin/admin-templates.js` → `fontCss()`.

The editor's font dropdown only lists fonts that actually resolve on the machine,
so a missing file simply won't appear.
