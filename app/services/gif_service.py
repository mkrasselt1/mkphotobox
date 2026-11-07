"""GIF capture service: buffers preview frames and creates animated GIFs."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import deque
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BufferedFrame:
    jpeg_bytes: bytes
    timestamp: float


class GifService:
    """Continuously buffers preview frames and creates GIFs on demand."""

    def __init__(self):
        self._buffer: deque[BufferedFrame] = deque()
        self._buffer_seconds: float = 5.0
        self._fps: int = 10
        self._running = False
        self._task: asyncio.Task | None = None
        self._enabled = False
        self._gif_width = 480
        self._gif_height = 360
        self._boomerang = False
        # photo_id -> (Ablaufzeit, Bilder): die Clips der letzten Aufnahmen,
        # bis /templates/render sie in die Collage einsetzt (siehe remember()).
        self._clips: OrderedDict[int, tuple[float, list[BufferedFrame]]] = OrderedDict()

    def configure(self, config: dict[str, Any]) -> None:
        gif_cfg = config.get("gif", {})
        self._enabled = gif_cfg.get("enabled", True)
        self._buffer_seconds = gif_cfg.get("buffer_seconds", 5.0)
        self._fps = gif_cfg.get("fps", 10)
        self._gif_width = gif_cfg.get("width", 480)
        self._gif_height = gif_cfg.get("height", 360)
        self._boomerang = bool(gif_cfg.get("boomerang", False))

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start_buffering(self, camera_manager) -> None:
        """Start a background task that continuously grabs preview frames."""
        if not self._enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._buffer_loop(camera_manager))
        logger.info("GIF buffer started (%.1fs @ %dfps)", self._buffer_seconds, self._fps)

    async def _buffer_loop(self, camera_manager) -> None:
        # Hängt am gemeinsamen Vorschau-Strom der Kamera, statt selbst abzufragen.
        # Vorher lief hier eine zweite Abfrage-Schleife — ständig, auch ohne
        # GIF — und nahm der Live-Vorschau die Hälfte der Bilder weg.
        # Passiv: nimmt Bilder, solange jemand die Vorschau sieht (der
        # Kiosk während der Aufnahme immer), hält die DSLR aber nicht allein
        # Tag und Nacht in der Live-View.
        while self._running:
            cam = camera_manager.preview_camera
            if cam is None:
                await asyncio.sleep(1)
                continue
            try:
                async for frame in cam.stream_preview(passive=True):
                    if not self._running or camera_manager.preview_camera is not cam:
                        break  # Kamera gewechselt: neu anhängen
                    if not frame:
                        continue
                    # Dasselbe Bild nicht zweimal: der Strom meldet sich auch
                    # ohne neues Kamerabild (die 700D liefert ~3,4 Bilder/s,
                    # hier kamen 10/s an). Das verdreifachte Bilderzahl, Größe
                    # und Bauzeit des GIFs — 50 statt 17 Bilder, 20 s statt 7 s.
                    if self._buffer and self._buffer[-1].jpeg_bytes == frame:
                        continue
                    now = time.time()
                    self._buffer.append(BufferedFrame(jpeg_bytes=frame, timestamp=now))
                    cutoff = now - self._buffer_seconds
                    while self._buffer and self._buffer[0].timestamp < cutoff:
                        self._buffer.popleft()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("GIF buffer: preview stream interrupted", exc_info=True)
                await asyncio.sleep(1)
                continue
            # Strom regulär zu Ende (Kamera beendet/gewechselt): kurz warten
            # statt im Kreis neu anzuhängen.
            await asyncio.sleep(0.5)

    async def stop_buffering(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._buffer.clear()

    def snapshot(self) -> list[BufferedFrame]:
        """Die Bilder der letzten Sekunden, festgehalten im Moment des Fotos —
        damit das GIF danach im Hintergrund gebaut werden kann, ohne dass
        inzwischen neue Bilder (der nächste Countdown) hineinrutschen."""
        return list(self._buffer)

    async def create_gif(self, output_dir: Path, filename_base: str,
                         comment: bytes | None = None,
                         frames: list[BufferedFrame] | None = None,
                         look: str | None = None) -> Path | None:
        """Create a GIF from the buffered frames. Returns the file path or None.

        ``comment`` is written as the GIF comment block — GIFs cannot carry EXIF,
        so that is where the event/camera/location details go. ``frames``: ein
        vorher mit snapshot() festgehaltener Stand, sonst der aktuelle Puffer.
        ``look``: der beim Foto gewählte Look (photo_filters), damit das GIF
        aussieht wie das Foto."""
        frames = list(self._buffer) if frames is None else frames
        if not frames:
            logger.warning("GIF: no frames in buffer")
            return None
        if len(frames) < 3:
            logger.warning("GIF: only %d frames, need at least 3", len(frames))
            return None

        return await asyncio.to_thread(
            self._build_gif, frames, output_dir, filename_base, comment, look
        )


    # ── Clips für das Collage-GIF ─────────────────────────────────────────
    # Bei einer Vorlage kommt /templates/render erst nach der (letzten)
    # Aufnahme, und der Puffer läuft bis dahin weiter. Deshalb werden die
    # Bilder jeder Aufnahme hier kurz festgehalten. Im Speicher statt aus dem
    # fertigen Roh-GIF gelesen: das ist beim Render evtl. noch gar nicht fertig
    # (läuft im Hintergrund), hat nur noch 256 Farben und den Look schon drin.
    # Die JPEG-Bytes liegen ohnehin im Speicher (Puffer/GIF-Bau) — hier werden
    # nur Verweise gehalten. Nach einem Neustart sind sie weg; dann zeigt die
    # Collage an der Stelle eben das Foto still.
    CLIP_TTL = 600.0               # s — länger dauert keine Runde am Booth
    CLIP_MAX_BYTES = 48 * 2 ** 20  # ~8–10 Aufnahmen bei 960er-Vorschau

    def remember(self, photo_id: int, frames: list[BufferedFrame]) -> None:
        if len(frames) < 3:
            return
        now = time.time()
        self._clips.pop(photo_id, None)
        self._clips[photo_id] = (now + self.CLIP_TTL, list(frames))
        self._prune(now)

    def clip_for(self, photo_id: int) -> list[BufferedFrame] | None:
        self._prune(time.time())
        entry = self._clips.get(photo_id)
        return entry[1] if entry else None

    def forget(self, photo_id: int) -> None:
        self._clips.pop(photo_id, None)

    def _prune(self, now: float) -> None:
        for pid in [k for k, (exp, _) in self._clips.items() if exp < now]:
            del self._clips[pid]
        total = sum(len(f.jpeg_bytes) for _, fr in self._clips.values() for f in fr)
        while self._clips and total > self.CLIP_MAX_BYTES:   # älteste zuerst raus
            _, (_, fr) = self._clips.popitem(last=False)
            total -= sum(len(f.jpeg_bytes) for f in fr)

    async def create_collage_gif(self, layers: dict, clips: dict[int, tuple[list[BufferedFrame], str | None]],
                                 output_dir: Path, filename_base: str,
                                 comment: bytes | None = None) -> Path | None:
        """GIF einer Collage: jeder Slot zeigt den Clip seiner Aufnahme, alle
        gleichzeitig, mit Rahmen/Text/Emojis der Vorlage darüber.

        ``layers`` kommt aus collage_service.render(anim=...), ``clips`` ist
        photo_index -> (Bilder, Look)."""
        clips = {i: c for i, c in clips.items() if c[0] and len(c[0]) >= 3}
        if not clips:
            return None
        return await asyncio.to_thread(
            self._build_collage_gif, layers, clips, output_dir, filename_base, comment)

    # ── Bauen ─────────────────────────────────────────────────────────────

    def _build_gif(self, frames: list[BufferedFrame], output_dir: Path, filename_base: str,
                   comment: bytes | None = None, look: str | None = None) -> Path | None:
        try:
            from PIL import Image

            # Fit each frame into the configured box preserving the source aspect
            # ratio, but NEVER upscale (scale capped at 1.0) — per-frame upscaling
            # was too CPU-heavy during live events. Downscale only, with a cheap
            # BILINEAR filter, and skip the resize entirely when the frame already
            # fits. Display size is handled by the viewers (CSS). Size computed
            # once (all frames share a size).
            look_fn = _look_fn(look)
            pil_frames = []
            target = None
            for f in frames:
                img = Image.open(io.BytesIO(f.jpeg_bytes))
                if target is None:
                    sw, sh = img.size
                    scale = min(self._gif_width / sw, self._gif_height / sh, 1.0)
                    target = (max(1, round(sw * scale)), max(1, round(sh * scale)))
                img = _decode(img, target)
                if img.size != target:
                    img = img.resize(target, Image.BILINEAR)
                if look_fn:
                    # Erst nach dem Verkleinern: der Look kostet pro Pixel.
                    img = look_fn(img)
                pil_frames.append(img)

            if not pil_frames:
                return None
            return self._save_gif(pil_frames, _frame_duration_ms(frames, self._fps),
                                  output_dir / f"{filename_base}.gif", comment)

        except Exception:
            logger.exception("GIF creation failed")
            return None

    def _build_collage_gif(self, layers: dict, clips: dict, output_dir: Path,
                           filename_base: str, comment: bytes | None) -> Path | None:
        try:
            from PIL import Image

            # Gemeinsame Zeitachse: alle Clips enden im Moment ihres Auslösens
            # und werden dort ausgerichtet — das GIF endet also mit allen
            # Gesichtern in Pose. Takt gibt der längste Clip vor (seine echten
            # Bildzeitpunkte); kürzere Clips halten bis zu ihrem Beginn ihr
            # erstes Bild. Ruhiger als Schleifen: da spränge jeder Slot zu
            # einem anderen Zeitpunkt zurück, das Bild zuckte ständig irgendwo.
            ref = max(clips.values(), key=lambda c: c[0][-1].timestamp - c[0][0].timestamp)[0]
            ref_end = ref[-1].timestamp
            times = [f.timestamp - ref_end for f in ref]            # ≤ 0, endet bei 0
            picks: dict[int, list[int]] = {}
            for idx, (frames, _) in clips.items():
                end = frames[-1].timestamp
                rel = [f.timestamp - end for f in frames]
                seq, j = [], 0
                for t in times:
                    while j + 1 < len(rel) and rel[j + 1] <= t + 1e-3:
                        j += 1
                    seq.append(j)
                picks[idx] = seq

            looks = {idx: _look_fn(look) for idx, (_, look) in clips.items()}
            # Ein Slot-Bild hängt nur ab von Aufnahme, Bildnummer und Slot-Maß —
            # Vorlagen mit derselben Aufnahme in zwei Slots (Doppel-Streifen)
            # und gehaltene Bilder rechnen es nur einmal.
            tile_cache: dict[tuple, Any] = {}

            def tile(op: dict, idx: int, fi: int):
                # ohne Position: _place_frame liefert den Versatz zur Slot-Ecke
                key = (idx, fi, op["w"], op["h"], op["fit"], op["rotation"], op["clip"])
                hit = tile_cache.get(key)
                if hit is None:
                    raw = Image.open(io.BytesIO(clips[idx][0][fi].jpeg_bytes))
                    hit = _place_frame(raw, op, looks[idx])
                    tile_cache[key] = hit
                return hit

            base = layers["base"]
            deck_rgb, deck_mask = layers["deck"]
            out_frames = []
            for k in range(len(times)):
                im = base.copy()
                for op in layers["ops"]:
                    if op["kind"] == "anim":
                        idx = op["photo_index"]
                        if idx in clips:
                            img, mask, (dx, dy) = tile(op, idx, picks[idx][k])
                            pos = (op["x"] + dx, op["y"] + dy)
                        else:
                            img, mask, pos = op["still"]
                    else:
                        img, mask, pos = op["piece"]
                    im.paste(img, pos, mask)
                if deck_mask is not None:
                    im.paste(deck_rgb, (0, 0), deck_mask)
                out_frames.append(im)
            tile_cache.clear()

            return self._save_gif(out_frames, _frame_duration_ms(ref, self._fps),
                                  output_dir / f"{filename_base}.gif", comment)
        except Exception:
            logger.exception("Collage GIF creation failed")
            return None

    def _save_gif(self, pil_frames: list, frame_duration: int, gif_path: Path,
                  comment: bytes | None) -> Path:
        from PIL import Image

        # EINE Farbpalette für alle Bilder. GIF kann nur 256 Farben, und
        # Pillow rechnet sonst für jedes Bild eine eigene Palette samt
        # Dithering aus — das war fast die ganze Rechenzeit: 49 Bilder
        # 6,2 s auf der Box (im Betrieb neben Live-Stream bis 20 s), mit
        # gemeinsamer Palette 0,2 s bei gleicher Dateigröße. Gebaut aus
        # mehreren über den Clip verteilten Bildern, damit Farben vom
        # Anfang und Ende nicht fehlen.
        # Die Musterbilder halbiert: für die Farbauswahl reicht das völlig,
        # und MEDIANCUT kostet pro Pixel (bei 640er-Bildern 0,18 s → 0,05 s).
        picks = [im.reduce(2) if min(im.size) >= 200 else im
                 for im in pil_frames[::max(1, len(pil_frames) // 6)][:6]]
        w, h = picks[0].size
        sheet = Image.new("RGB", (w, h * len(picks)))
        for i, im in enumerate(picks):
            sheet.paste(im, (0, i * h))
        palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        sheet.close()
        pal_frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in pil_frames]

        # Boomerang: play the middle frames again in reverse so the loop runs
        # forward and back. The endpoints are left out — otherwise the first and
        # last frame show twice each and the motion stutters exactly there.
        # These are repeated *references*, so only pal_frames gets closed below.
        sequence = pal_frames
        if self._boomerang and len(pal_frames) > 2:
            sequence = pal_frames + pal_frames[-2:0:-1]

        # Erst fertig schreiben, dann umbenennen: wird der Bau abgebrochen
        # (Neustart mitten drin), bleibt keine halbe/leere GIF-Datei liegen.
        tmp_path = gif_path.with_suffix(".gif.part")
        sequence[0].save(
            tmp_path,
            format="GIF",
            save_all=True,
            append_images=sequence[1:],
            duration=frame_duration,
            loop=0,
            **({"comment": comment} if comment else {}),
        )
        tmp_path.replace(gif_path)

        for img in pil_frames + pal_frames:
            img.close()

        file_size = gif_path.stat().st_size
        logger.info("GIF created: %s (%d frames%s, %d KB)", gif_path.name, len(sequence),
                    " boomerang" if sequence is not pal_frames else "", file_size // 1024)
        return gif_path


def _frame_duration_ms(frames: list[BufferedFrame], fps: int) -> int:
    """Abspieltempo aus den echten Zeitstempeln: die Kamera liefert so viele
    Bilder, wie sie schafft, nicht die konfigurierten fps — mit fester Dauer
    liefe das GIF sonst im Zeitraffer."""
    if len(frames) > 1 and frames[-1].timestamp > frames[0].timestamp:
        ms = int(1000 * (frames[-1].timestamp - frames[0].timestamp) / (len(frames) - 1))
    else:
        ms = int(1000 / max(1, fps))
    return max(20, min(ms, 500))


def _look_fn(look: str | None):
    """Der Look als Funktion auf ein RGB-Bild, oder None. Ein Fehler im Filter
    lässt das Bild unverändert — ein GIF ohne Look ist besser als keins."""
    from app.services import photo_filters

    fn = photo_filters.resolve(look)
    if fn is None:
        return None

    def apply(img):
        try:
            return fn(img)
        except Exception:
            logger.exception("Look %r auf GIF-Bild fehlgeschlagen", look)
            return img
    return apply


def _decode(img, min_size: tuple[int, int]):
    """JPEG gleich verkleinert dekodieren (DCT-Skalierung, 1/2 bis 1/8): ein
    960er-Vorschaubild für einen 200-px-Slot muss nicht voll ausgepackt werden.
    draft() bleibt dabei immer ≥ min_size, die Feinarbeit macht resize()."""
    try:
        img.draft("RGB", (max(1, int(min_size[0])), max(1, int(min_size[1]))))
    except Exception:
        pass
    return img.convert("RGB")


def _place_frame(raw, op: dict, look_fn):
    """Ein Vorschaubild so in den (verkleinerten) Slot setzen wie
    collage_service.render das Foto: cover/contain, Drehung, Zuschnitt.
    Ergebnis: (Bild, Maske oder None, Versatz zur Slot-Ecke) für Image.paste —
    relativ, damit dasselbe Bild in mehreren Slots wiederverwendet werden kann."""
    from PIL import Image

    w, h = op["w"], op["h"]
    sw, sh = raw.size
    if op["fit"] == "contain":
        scale = min(w / sw, h / sh)
    else:
        scale = max(w / sw, h / sh)
    img = _decode(raw, (sw * scale, sh * scale))
    sw, sh = img.size
    if op["fit"] == "contain":
        scale = min(w / sw, h / sh)
        nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
        img = img.resize((nw, nh), Image.BILINEAR)
        ox, oy = (w - nw) // 2, (h - nh) // 2
    else:
        # cover: Ausschnitt und Verkleinern in einem Schritt (resize mit box)
        scale = max(w / sw, h / sh)
        cw, ch = w / scale, h / scale
        left, top = (sw - cw) / 2, (sh - ch) / 2
        img = img.resize((w, h), Image.BILINEAR, box=(left, top, left + cw, top + ch))
        ox = oy = 0
    if look_fn:
        img = look_fn(img)
    rot = op["rotation"]
    if not rot:
        return img, None, (ox, oy)
    # Gedreht: wie im Renderer um die Slot-Mitte, Ecken transparent
    rgba = img.convert("RGBA")
    if op["fit"] == "contain":
        pad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pad.paste(rgba, (ox, oy))
        rgba = pad
    rgba = rgba.rotate(-rot, expand=True, resample=Image.BICUBIC)
    if op["clip"]:
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        tile.alpha_composite(rgba, (w // 2 - rgba.width // 2, h // 2 - rgba.height // 2))
        rgba, pos = tile, (0, 0)
    else:
        pos = (w // 2 - rgba.width // 2, h // 2 - rgba.height // 2)
    return rgba.convert("RGB"), rgba.getchannel("A"), pos
