"""Acoustic trigger — detects loud sounds (clap, "cheese!", etc.)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger
from app.modules.base import missing_python_package

logger = logging.getLogger(__name__)


class AcousticTrigger(AbstractTrigger):
    name = "trigger.acoustic"

    def __init__(self):
        self._threshold = 0.7
        self._cooldown_ms = 2000
        self._device_index: int | None = None  # None = system default
        self._callback: Callable | None = None
        self._running = False
        self._task = None
        self._last_trigger = 0.0

    async def initialize(self, config: dict[str, Any]) -> None:
        self._threshold = config.get("threshold", 0.7)
        self._cooldown_ms = config.get("cooldown_ms", 2000)
        dev = config.get("device_index")
        self._device_index = int(dev) if dev is not None and dev != "" else None

    async def shutdown(self) -> None:
        await self.stop_listening()

    @classmethod
    def system_requirement(cls) -> str | None:
        return missing_python_package(
            "sounddevice", "sudo apt install libportaudio2 && pip install sounddevice")

    def is_available(self) -> bool:
        try:
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401
            return True
        except ImportError:
            return False

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        import numpy as np
        import sounddevice as sd

        loop = asyncio.get_event_loop()
        block_size = 1024
        sample_rate = 16000  # Low sample rate is fine for volume detection

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.debug("Audio status: %s", status)
            # Calculate RMS amplitude (0.0 to 1.0)
            rms = float(np.sqrt(np.mean(indata ** 2)))
            if rms >= self._threshold:
                now = time.time()
                if now - self._last_trigger > self._cooldown_ms / 1000:
                    self._last_trigger = now
                    # Schedule callback on the event loop
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        self._fire(rms)
                    )

        try:
            with sd.InputStream(
                device=self._device_index,
                samplerate=sample_rate,
                channels=1,
                blocksize=block_size,
                callback=audio_callback,
            ):
                while self._running:
                    await asyncio.sleep(0.1)
        except Exception:
            logger.exception("Acoustic trigger stream error")

    async def _fire(self, amplitude: float):
        if self._callback:
            await self._callback("trigger.fired", {
                "source": "acoustic",
                "amplitude": round(amplitude, 3),
            })

    async def stop_listening(self) -> None:
        self._running = False
        self._callback = None
        if self._task:
            self._task.cancel()
            self._task = None

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number", "default": 0.7, "minimum": 0.1, "maximum": 1.0,
                    "description": "Volume threshold (0.0-1.0) to trigger",
                },
                "cooldown_ms": {
                    "type": "integer", "default": 2000, "minimum": 500,
                    "description": "Minimum time between triggers in ms",
                },
                "device_index": {
                    "type": ["integer", "null"], "default": None,
                    "description": "Audio input device index (null = system default)",
                },
            },
        }
