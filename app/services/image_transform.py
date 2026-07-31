"""Geometry of the camera image: rotation, flipping and the mirror preview.

Two different things live in ``cameras.transform`` and they must not be confused:

``rotation`` / ``flip_horizontal`` / ``flip_vertical``
    Corrections for how the camera is physically mounted (upside down, portrait,
    shooting into a mirror). They apply to the **live preview and the saved
    photo alike** — otherwise what the guests frame is not what they get.

``mirror_preview``
    The classic photo booth trick: the live image is mirrored so guests see
    themselves as in a mirror and move the right way, while the **saved photo
    stays correct** — otherwise every sign, logo and T-shirt print in the shot
    comes out backwards.

Applied per camera type in whichever representation is cheapest: OpenCV
transforms numpy frames, every other module hands us JPEG bytes. A JPEG is only
ever re-encoded when there is something to do — an unconfigured box pays nothing.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Transform:
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    mirror_preview: bool = True

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "Transform":
        tf = ((cfg or {}).get("cameras") or {}).get("transform") or {}
        try:
            rotation = int(tf.get("rotation", 0)) % 360
        except (TypeError, ValueError):
            rotation = 0
        if rotation not in VALID_ROTATIONS:
            logger.warning("Ignoring unsupported camera rotation %r", tf.get("rotation"))
            rotation = 0
        return cls(
            rotation=rotation,
            flip_horizontal=bool(tf.get("flip_horizontal", False)),
            flip_vertical=bool(tf.get("flip_vertical", False)),
            mirror_preview=bool(tf.get("mirror_preview", True)),
        )

    @classmethod
    def current(cls) -> "Transform":
        from app.config import get_config

        return cls.from_config(get_config())

    def horizontal_flip(self, preview: bool) -> bool:
        """Mirroring the preview is one more horizontal flip on top of the
        mounting correction — two flips cancel out, which is correct."""
        return self.flip_horizontal != (preview and self.mirror_preview)

    def is_noop(self, preview: bool) -> bool:
        return (self.rotation == 0
                and not self.flip_vertical
                and not self.horizontal_flip(preview))


# ── numpy / OpenCV path (live frames, cheap) ─────────────────────────────

def apply_to_frame(frame, tf: Transform, *, preview: bool):
    """Rotate/flip an OpenCV BGR frame in place-ish. Returns the new frame."""
    if tf.is_noop(preview):
        return frame
    import cv2

    if tf.rotation == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif tf.rotation == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif tf.rotation == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    flip_h = tf.horizontal_flip(preview)
    if flip_h and tf.flip_vertical:
        frame = cv2.flip(frame, -1)
    elif flip_h:
        frame = cv2.flip(frame, 1)
    elif tf.flip_vertical:
        frame = cv2.flip(frame, 0)
    return frame


# ── JPEG path (DSLR captures, digiCamControl, browser uploads) ───────────

def apply_to_jpeg(data: bytes, tf: Transform, *, preview: bool, quality: int = 90) -> bytes:
    """Rotate/flip JPEG bytes.

    Returns *data* untouched when there is nothing to do, so an unconfigured box
    never re-encodes. Any EXIF the camera wrote is carried over; the orientation
    tag is resolved and cleared so the result cannot be rotated twice.
    """
    if not data or tf.is_noop(preview):
        return data
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as src:
            # Resolve a camera-set orientation tag first — otherwise our rotation
            # and the viewer's interpretation of that tag would stack.
            img = ImageOps.exif_transpose(src)
            exif = img.info.get("exif")

            if tf.rotation:
                # PIL rotates counter-clockwise; our setting means clockwise.
                img = img.transpose({
                    90: Image.ROTATE_270,
                    180: Image.ROTATE_180,
                    270: Image.ROTATE_90,
                }[tf.rotation])
            if tf.horizontal_flip(preview):
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if tf.flip_vertical:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, **({"exif": exif} if exif else {}))
            return buf.getvalue()
    except Exception:
        logger.exception("Could not transform frame — using it unchanged")
        return data
