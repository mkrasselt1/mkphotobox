#!/usr/bin/env python3
"""Erzeugt die Demo-Rahmen „Party / Geburtstag“ (wiederholbar).

    .venv/bin/python scripts/make-demo-frame.py

Ausgabe nach ``app/assets/demo/``:

* ``party-frame-1800x1200.png`` — Einzelfoto, 10×15 cm quer bei 300 dpi
  (Mitsubishi CP9550, Papier ``w288h432`` im Querformat)
* ``party-strip-1200x1800.png`` — Doppel-Streifen, 10×15 cm hoch: zwei
  identische 5×15-cm-Streifen mit je drei Fenstern (in der Mitte schneiden)
* ``party.json`` — Vorlagen-Beschreibung (Fenster = Foto-Slots, Text-Elemente),
  die ``scripts/install-demo-template.py`` in die Datenbank übernimmt

Die Fenster der PNGs sind voll transparent: der Rahmen liegt in der Vorlage als
„Rahmen“ (``overlay_asset_id``) *über* den Fotos. Texte („Happy Birthday!“,
Datum) sind bewusst nicht eingebrannt, sondern Text-Elemente der Vorlage —
änderbar im Vorlagen-Editor.

Grafik komplett selbst erzeugt: Farbverlauf, Konfetti, Luftschlangen und
Wimpelkette aus Pillow-Formen, dazu Twemoji-Emojis (CC-BY 4.0, © Twitter, Inc.
und Mitwirkende) über ``app/services/emoji_service.py``. Die Emoji-SVGs müssen
installiert sein (``bash scripts/install-emoji.sh``).
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from app.services import emoji_service  # noqa: E402

OUT_DIR = ROOT / "app" / "assets" / "demo"

#: Zeichnen in doppelter Auflösung, dann herunterrechnen = weiche Kanten.
SS = 2

# ── Farben ──────────────────────────────────────────────────────────────────
GRAD_TOP = (52, 24, 104)       # tiefes Violett
GRAD_MID = (128, 36, 120)      # Beere
GRAD_BOTTOM = (206, 62, 98)    # Himbeer-Koralle
CONFETTI = [
    (255, 210, 63),    # Gold
    (59, 206, 172),    # Türkis
    (255, 107, 157),   # Pink
    (255, 255, 255),   # Weiß
    (127, 219, 255),   # Hellblau
    (255, 159, 28),    # Orange
]
PENNANTS = [(255, 210, 63), (59, 206, 172), (255, 107, 157), (127, 219, 255),
            (255, 159, 28), (255, 255, 255)]
MAT = (255, 255, 255)          # Passepartout-Rand ums Fenster
MAT_WIDTH = 14
WINDOW_RADIUS = 22
TEXT_STROKE = "#2a0f45"


# ── Bausteine ───────────────────────────────────────────────────────────────

def gradient(w: int, h: int) -> Image.Image:
    """Diagonaler Drei-Farben-Verlauf (oben links → unten rechts)."""
    sw, sh = 160, max(2, round(160 * h / w))
    small = Image.new("RGB", (sw, sh))
    px = []
    for y in range(sh):
        for x in range(sw):
            t = 0.7 * (y / (sh - 1)) + 0.3 * (x / (sw - 1))
            if t < 0.5:
                a, b, u = GRAD_TOP, GRAD_MID, t / 0.5
            else:
                a, b, u = GRAD_MID, GRAD_BOTTOM, (t - 0.5) / 0.5
            px.append(tuple(round(a[c] + (b[c] - a[c]) * u) for c in range(3)))
    small.putdata(px)
    return small.resize((w, h), Image.BICUBIC).convert("RGBA")


def _inflate(r, d):
    x0, y0, x1, y1 = r
    return (x0 - d, y0 - d, x1 + d, y1 + d)


def _hits(px, py, rects, pad):
    return any(r[0] - pad <= px <= r[2] + pad and r[1] - pad <= py <= r[3] + pad for r in rects)


def confetti(draw: ImageDraw.ImageDraw, w: int, h: int, avoid: list, rng: random.Random,
             count: int, scale: float) -> None:
    """Streu-Konfetti: Rechtecke, Punkte, kleine Kringel — nicht über den Fenstern."""
    placed = 0
    tries = 0
    while placed < count and tries < count * 20:
        tries += 1
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        if _hits(x, y, avoid, 26 * scale):
            continue
        col = rng.choice(CONFETTI)
        kind = rng.random()
        if kind < 0.5:                       # gedrehtes Rechteck
            lw, lh = rng.uniform(8, 18) * scale, rng.uniform(4, 8) * scale
            a = rng.uniform(0, math.pi)
            ca, sa = math.cos(a), math.sin(a)
            pts = [(x + dx * ca - dy * sa, y + dx * sa + dy * ca)
                   for dx, dy in ((-lw, -lh), (lw, -lh), (lw, lh), (-lw, lh))]
            draw.polygon(pts, fill=col)
        elif kind < 0.8:                     # Punkt
            r = rng.uniform(4, 9) * scale
            draw.ellipse((x - r, y - r, x + r, y + r), fill=col)
        else:                                # Kringel (kurze Welle)
            amp, length = rng.uniform(5, 9) * scale, rng.uniform(28, 44) * scale
            a = rng.uniform(0, math.pi)
            pts = []
            for i in range(13):
                s = (i / 12 - 0.5) * length
                o = math.sin(i / 12 * 2 * math.pi) * amp
                pts.append((x + s * math.cos(a) - o * math.sin(a),
                            y + s * math.sin(a) + o * math.cos(a)))
            draw.line(pts, fill=col, width=max(2, round(4 * scale)), joint="curve")
        placed += 1


def streamer(draw, x0, y0, x1, y1, color, scale, waves=3.0, amp=26.0, width=9):
    """Geschwungene Luftschlange von (x0,y0) nach (x1,y1)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1
    nx, ny = -dy / length, dx / length
    pts = []
    for i in range(121):
        t = i / 120
        o = math.sin(t * waves * 2 * math.pi) * amp * scale * (0.4 + 0.6 * t)
        pts.append((x0 + dx * t + nx * o, y0 + dy * t + ny * o))
    draw.line(pts, fill=color, width=round(width * scale), joint="curve")


def bunting(draw, x_start, x_end, y, sag, flag_w, flag_h, scale, rng, segments=1):
    """Wimpelkette: durchhängende Schnur(en) mit Dreieckswimpeln."""
    seg_w = (x_end - x_start) / segments
    ci = rng.randrange(len(PENNANTS))
    for s in range(segments):
        a = x_start + s * seg_w

        def curve(t, a=a):
            return a + seg_w * t, y + sag * 4 * t * (1 - t)

        pts = [curve(i / 60) for i in range(61)]
        draw.line(pts, fill=(255, 240, 210), width=round(3 * scale), joint="curve")
        n = max(2, round(seg_w / (flag_w * 1.25)))
        for k in range(n):
            t = (k + 0.5) / n
            cx, cy = curve(t)
            # Tangente → Wimpel steht senkrecht zur Schnur
            tx, ty = seg_w, sag * 4 * (1 - 2 * t)
            tl = math.hypot(tx, ty)
            tx, ty = tx / tl, ty / tl
            nx, ny = -ty, tx
            hw = flag_w / 2
            p1 = (cx - tx * hw, cy - ty * hw)
            p2 = (cx + tx * hw, cy + ty * hw)
            p3 = (cx + nx * flag_h, cy + ny * flag_h)
            col = PENNANTS[ci % len(PENNANTS)]
            ci += 1
            draw.polygon([p1, p2, p3], fill=col)
            # dezente Mittelnaht für Tiefe
            shade = tuple(max(0, c - 40) for c in col)
            draw.line([((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2), p3],
                      fill=shade, width=max(1, round(1.5 * scale)))


def windows_and_mat(img: Image.Image, windows: list, scale: float) -> Image.Image:
    """Schatten + weißer Rand um jedes Fenster, dann das Fenster ausstanzen."""
    w, h = img.size
    # Schatten
    shadow = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(shadow)
    for r in windows:
        sd.rounded_rectangle(_inflate((r[0], r[1] + 8 * scale, r[2], r[3] + 8 * scale),
                                      MAT_WIDTH * scale),
                             radius=(WINDOW_RADIUS + MAT_WIDTH) * scale, fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(10 * scale))
    dark = Image.new("RGBA", (w, h), (20, 0, 30, 255))
    dark.putalpha(shadow)
    img.alpha_composite(dark)
    # Passepartout
    d = ImageDraw.Draw(img)
    for r in windows:
        d.rounded_rectangle(_inflate(r, MAT_WIDTH * scale),
                            radius=(WINDOW_RADIUS + MAT_WIDTH) * scale, fill=MAT + (255,))
    # Fenster transparent ausstanzen
    alpha = img.getchannel("A")
    ad = ImageDraw.Draw(alpha)
    for r in windows:
        ad.rounded_rectangle(r, radius=WINDOW_RADIUS * scale, fill=0)
    img.putalpha(alpha)
    return img


def emoji(img: Image.Image, ch: str, cx, cy, size, rot=0.0) -> None:
    if not emoji_service.place(img, ch, cx, cy, size, rot):
        raise SystemExit(f"Emoji {ch!r} nicht gefunden — erst `bash scripts/install-emoji.sh` ausführen.")


def finish(big: Image.Image, w: int, h: int, windows_1x: list) -> Image.Image:
    """Herunterrechnen und die Fenster hart transparent nachziehen (exakt slot-genau)."""
    out = big.resize((w, h), Image.LANCZOS)
    alpha = out.getchannel("A")
    ad = ImageDraw.Draw(alpha)
    for (x0, y0, x1, y1) in windows_1x:
        # Kern ohne die runden Ecken sicher 0 — die Ecken kommen aus dem Supersampling
        ad.rectangle((x0 + WINDOW_RADIUS, y0, x1 - WINDOW_RADIUS - 1, y1 - 1), fill=0)
        ad.rectangle((x0, y0 + WINDOW_RADIUS, x1 - 1, y1 - WINDOW_RADIUS - 1), fill=0)
    out.putalpha(alpha)
    return out


# ── Einzelfoto 1800×1200 ───────────────────────────────────────────────────

SINGLE_W, SINGLE_H = 1800, 1200
SINGLE_WINDOW = (220, 150, 1580, 1000)   # x0, y0, x1, y1 (1360×850)


def make_single() -> tuple[Image.Image, dict]:
    s = SS
    W, H = SINGLE_W * s, SINGLE_H * s
    rng = random.Random(20261107)
    win = [tuple(v * s for v in SINGLE_WINDOW)]
    img = gradient(W, H)
    d = ImageDraw.Draw(img)

    # Luftschlangen aus den unteren Ecken und seitlich
    streamer(d, -20 * s, 1150 * s, 200 * s, 860 * s, (255, 210, 63), s, waves=2.5)
    streamer(d, 1820 * s, 1150 * s, 1600 * s, 860 * s, (59, 206, 172), s, waves=2.5)
    streamer(d, -30 * s, 300 * s, 120 * s, 560 * s, (255, 107, 157), s, waves=1.5, amp=18, width=7)
    streamer(d, 1830 * s, 300 * s, 1680 * s, 560 * s, (127, 219, 255), s, waves=1.5, amp=18, width=7)

    text_zone = (330 * s, 1020 * s, 1470 * s, 1185 * s)   # „Happy Birthday!“ + Datum frei halten
    confetti(d, W, H, win + [(0, 0, W, 120 * s), text_zone], rng, 230, s)
    bunting(d, -10 * s, (SINGLE_W + 10) * s, 14 * s, 44 * s, 54 * s, 62 * s, s, rng, segments=3)

    img = windows_and_mat(img, win, s)

    # Emojis als Akzente am Rand (Mittelpunkt, Kantenlänge, Drehung)
    for ch, cx, cy, size, rot in [
        ("🎈", 108, 330, 200, -10),
        ("✨", 70, 560, 100, 0),
        ("🎈", 128, 720, 150, 8),
        ("🎁", 120, 1080, 170, -6),
        ("🥳", 1690, 320, 190, 8),
        ("✨", 1735, 545, 100, 0),
        ("🎂", 1685, 745, 165, 0),
        ("🎉", 1685, 1075, 180, 0),
    ]:
        emoji(img, ch, cx * s, cy * s, size * s, rot)

    out = finish(img, SINGLE_W, SINGLE_H, [SINGLE_WINDOW])
    x0, y0, x1, y1 = SINGLE_WINDOW
    template = {
        "name": "Demo: Party",
        "asset_name": "demo-party-frame",
        "file": "party-frame-1800x1200.png",
        "canvas_width": SINGLE_W, "canvas_height": SINGLE_H,
        "orientation": "landscape",
        "mode": "free",
        "definition": {
            "slots": [{"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "rotation": 0, "fit": "cover"}],
            "overlays": [],
            "emojis": [],
            "texts": [
                {"text": "Happy Birthday!", "x": 300, "y": 1012, "w": 1200, "h": 128,
                 "rotation": 0, "font": "Lobster", "size": 104, "color": "#ffffff",
                 "align": "center", "valign": "middle", "bold": False, "italic": False,
                 "stroke_width": 5, "stroke_color": TEXT_STROKE},
                {"text": "{DATUM}", "x": 500, "y": 1134, "w": 800, "h": 54,
                 "rotation": 0, "font": "Sans", "size": 38, "color": "#ffe9a8",
                 "align": "center", "valign": "middle", "bold": True, "italic": False,
                 "stroke_width": 2, "stroke_color": TEXT_STROKE},
            ],
        },
    }
    return out, template


# ── Doppel-Streifen 1200×1800 (2 × 5×15 cm, je 3 Fenster) ─────────────────

STRIP_W, STRIP_H = 1200, 1800
STRIP_COL = 600
STRIP_WIN_W, STRIP_WIN_H = 520, 370
STRIP_WIN_Y = (150, 560, 970)


def strip_windows() -> list:
    out = []
    for col in range(2):
        ox = col * STRIP_COL + (STRIP_COL - STRIP_WIN_W) // 2
        for y in STRIP_WIN_Y:
            out.append((ox, y, ox + STRIP_WIN_W, y + STRIP_WIN_H))
    return out


def make_strip() -> tuple[Image.Image, dict]:
    s = SS
    W, H = STRIP_W * s, STRIP_H * s
    rng = random.Random(1107)
    wins_1x = strip_windows()
    wins = [tuple(v * s for v in r) for r in wins_1x]
    img = gradient(W, H)
    d = ImageDraw.Draw(img)

    for col in range(2):
        ox = col * STRIP_COL
        streamer(d, (ox - 10) * s, 1790 * s, (ox + 150) * s, 1560 * s, (255, 210, 63), s,
                 waves=2, amp=18, width=7)
        streamer(d, (ox + 610) * s, 1790 * s, (ox + 450) * s, 1560 * s, (59, 206, 172), s,
                 waves=2, amp=18, width=7)

    text_zones = [((ox + 50) * s, 1370 * s, (ox + 550) * s, 1530 * s) for ox in (0, STRIP_COL)]
    confetti(d, W, H, wins + [(0, 0, W, 120 * s)] + text_zones, rng, 150, s)
    for col in range(2):
        ox = col * STRIP_COL
        bunting(d, (ox - 6) * s, (ox + STRIP_COL + 6) * s, 14 * s, 40 * s,
                46 * s, 54 * s, s, rng, segments=1)

    # Schnittmarke in der Mitte (nur oben/unten, nicht durchs Bild)
    for y0, y1 in ((0, 26), (STRIP_H - 26, STRIP_H)):
        d.line([(STRIP_COL * s, y0 * s), (STRIP_COL * s, y1 * s)],
               fill=(255, 255, 255, 200), width=2 * s)

    img = windows_and_mat(img, wins, s)

    for col in range(2):
        ox = col * STRIP_COL
        for ch, cx, cy, size, rot in [
            ("🎈", 85, 1650, 130, -10),
            ("🎂", 300, 1660, 170, 0),
            ("🎁", 515, 1665, 125, 6),
            ("✨", 175, 1570, 60, 0),
            ("✨", 425, 1575, 55, 0),
        ]:
            emoji(img, ch, (ox + cx) * s, cy * s, size * s, rot)

    out = finish(img, STRIP_W, STRIP_H, wins_1x)

    slots, texts = [], []
    for i, (x0, y0, x1, y1) in enumerate(wins_1x):
        slots.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "rotation": 0,
                      "fit": "cover", "photo_index": i % 3})
    for col in range(2):
        ox = col * STRIP_COL
        texts.append({"text": "Happy Birthday!", "x": ox + 30, "y": 1362, "w": 540, "h": 110,
                      "rotation": 0, "font": "Lobster", "size": 74, "color": "#ffffff",
                      "align": "center", "valign": "middle", "bold": False, "italic": False,
                      "stroke_width": 4, "stroke_color": TEXT_STROKE})
        texts.append({"text": "{DATUM}", "x": ox + 60, "y": 1470, "w": 480, "h": 46,
                      "rotation": 0, "font": "Sans", "size": 30, "color": "#ffe9a8",
                      "align": "center", "valign": "middle", "bold": True, "italic": False,
                      "stroke_width": 2, "stroke_color": TEXT_STROKE})
    template = {
        "name": "Demo: Party-Streifen",
        "asset_name": "demo-party-strip",
        "file": "party-strip-1200x1800.png",
        "canvas_width": STRIP_W, "canvas_height": STRIP_H,
        "orientation": "portrait",
        "mode": "free",
        "definition": {"slots": slots, "overlays": [], "emojis": [], "texts": texts},
    }
    return out, template


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "_comment": "Erzeugt von scripts/make-demo-frame.py — nicht von Hand ändern. "
                    "{DATUM} ersetzt scripts/install-demo-template.py durch das Installationsdatum.",
        "attribution": "Emoji-Grafiken: Twemoji © Twitter, Inc. und Mitwirkende, CC-BY 4.0",
        "templates": [],
    }
    for maker in (make_single, make_strip):
        img, tpl = maker()
        path = OUT_DIR / tpl["file"]
        img.save(path, "PNG", optimize=True)
        manifest["templates"].append(tpl)
        print(f"  {path.relative_to(ROOT)}  {img.width}×{img.height}")
    (OUT_DIR / "party.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    print(f"  {(OUT_DIR / 'party.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
