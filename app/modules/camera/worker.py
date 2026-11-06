"""Der eine Kamera-Thread pro physischer Kamera.

Vorher holte die Vorschau jedes Bild per ``asyncio.to_thread`` — jedes Mal ein
anderer Pool-Thread — und Aufnahme, Fokus-Abfrage und Status griffen aus wieder
anderen Threads zu, nur durch ein Lock getrennt. gphoto2 ist nicht threadsicher;
das Lock verhinderte zwar gleichzeitige Zugriffe, aber eine Aufnahme wartete
dann einfach, bis die Vorschau das Lock zufällig freigab, und eine hängende
Abfrage im Executor hielt beim Beenden den ganzen Dienst fest (der
Default-Executor wartet bis zu 300 s auf seine Threads).

Jetzt fasst genau dieser Thread die Kamera an — sonst niemand:

* Läuft die Vorschau, liest er fortlaufend Bilder (Webcam/HDMI-Grabber: echter
  Strom über ``cap.read()``; DSLR über USB: Live-View-Abfrage über
  ``capture_preview`` — PTP liefert dort technisch nur Einzel-JPEGs) und reicht
  jedes an ``on_frame`` weiter.
* Alles andere (Foto, Konfig-Abfragen, Rohbild) ist ein Auftrag in seiner
  Queue. Aufträge haben Vorrang vor dem nächsten Vorschaubild; ein Foto-Auftrag
  beendet vorher die Live-View, der nächste Schleifendurchlauf startet sie neu.
* Will niemand Bilder, pausiert er die Live-View (Spiegel runter, Akku und
  Sensor geschont), hält aber die Verbindung.
"""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_STOP = object()
_WAKE = object()


class CameraWorker:
    #: Wie lange nach dem letzten Zuschauer die Live-View noch weiterläuft. Ein
    #: Seitenwechsel im Browser schließt den MJPEG-Strom und öffnet ihn sofort
    #: neu — ohne Gnadenfrist klappte der Spiegel dabei jedes Mal runter und hoch.
    idle_grace = 3.0

    def __init__(self, cam, *, on_frame: Callable[[bytes], None],
                 on_state: Callable[[str], None] | None = None,
                 max_fps: float = 15.0):
        self._cam = cam
        self._on_frame = on_frame
        self._on_state = on_state or (lambda _s: None)
        self._interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self._jobs: queue.Queue = queue.Queue()
        self._want_stream = False
        self._idle_since = time.monotonic()
        self._live = False
        self._stopped = False
        self.ident: int | None = None
        self._thread = threading.Thread(
            target=self._run, name=f"camera:{getattr(cam, 'name', '?')}", daemon=True)
        self._thread.start()

    # ── Schnittstelle für den asyncio-Teil ──────────────────────────────

    @property
    def alive_thread(self) -> bool:
        return self._thread.is_alive()

    def set_streaming(self, wanted: bool) -> None:
        if wanted == self._want_stream:
            return
        self._want_stream = wanted
        if not wanted:
            self._idle_since = time.monotonic()
        self._jobs.put(_WAKE)

    def submit(self, fn: Callable[..., Any], *args, pauses_stream: bool = False
               ) -> concurrent.futures.Future:
        """Auftrag an den Kamera-Thread. ``pauses_stream`` für alles, was die
        Live-View nicht verträgt (das Foto)."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        if self._stopped:
            fut.set_exception(RuntimeError("Kamera wurde beendet"))
            return fut
        if threading.get_ident() == self.ident:
            # Aus dem Kamera-Thread selbst (z. B. ein Hook, der eine öffentliche
            # Methode ruft): direkt ausführen statt sich selbst zu blockieren.
            try:
                fut.set_result(fn(*args))
            except BaseException as e:  # noqa: BLE001
                fut.set_exception(e)
            return fut
        self._jobs.put((fn, args, pauses_stream, fut))
        return fut

    def stop(self) -> None:
        """Thread beenden; er gibt die Kamera selbst frei (``_release_sync``)."""
        if not self._stopped:
            self._stopped = True
            self._jobs.put(_STOP)

    # ── Der Thread ──────────────────────────────────────────────────────

    def _run(self) -> None:
        self.ident = threading.get_ident()
        cam = self._cam
        try:
            cam._open_sync()
        except Exception as e:
            # Kein Abbruch: die Lese-/Foto-Hooks verbinden bei Bedarf neu.
            logger.warning("%s: Verbindung beim Start fehlgeschlagen (%s)", cam.name, e)
        backoff = 0.0
        wait_until = 0.0  # frühester Zeitpunkt für das nächste Vorschaubild
        try:
            while True:
                now = time.monotonic()
                if self._want_stream:
                    timeout = max(0.0, wait_until - now)
                elif self._live:
                    timeout = max(0.0, self._idle_since + self.idle_grace - now)
                else:
                    timeout = None  # nichts zu tun: schlafen bis Auftrag/Zuschauer
                try:
                    item = (self._jobs.get_nowait() if timeout == 0.0
                            else self._jobs.get(timeout=timeout))
                except queue.Empty:
                    item = None

                if item is _STOP:
                    break
                if item is _WAKE:
                    continue
                if item is not None:
                    self._run_job(*item)
                    continue

                if not self._want_stream:
                    if self._live and time.monotonic() - self._idle_since >= self.idle_grace:
                        self._pause()
                        self._on_state("idle")
                    continue

                # Vorschaubild lesen
                started = time.monotonic()
                if not self._live:
                    try:
                        cam._stream_start_sync()
                    except Exception:
                        logger.debug("%s: Live-View-Start fehlgeschlagen", cam.name, exc_info=True)
                    self._live = True
                    self._on_state("live")
                try:
                    frame = cam._preview_sync()
                except Exception:
                    logger.debug("%s: Vorschaubild fehlgeschlagen", cam.name, exc_info=True)
                    frame = b""
                if frame:
                    backoff = 0.0
                    self._on_frame(frame)
                    wait_until = started + self._interval
                else:
                    # Kamera weg oder beschäftigt: nicht im Kreis reconnecten.
                    backoff = min(2.0, max(0.2, backoff * 2))
                    wait_until = time.monotonic() + backoff
        finally:
            self._stopped = True
            # Liegengebliebene Aufträge nicht ewig warten lassen.
            while True:
                try:
                    item = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, tuple) and not item[3].done():
                    item[3].set_exception(RuntimeError("Kamera wurde beendet"))
            try:
                cam._release_sync()
            except Exception:
                logger.debug("%s: Freigeben fehlgeschlagen", cam.name, exc_info=True)

    def _pause(self, for_capture: bool = False) -> None:
        if not self._live:
            return
        self._live = False
        try:
            self._cam._stream_stop_sync(for_capture)
        except Exception:
            logger.debug("%s: Live-View-Stopp fehlgeschlagen", self._cam.name, exc_info=True)

    def _run_job(self, fn, args, pauses_stream: bool, fut: concurrent.futures.Future) -> None:
        if not fut.set_running_or_notify_cancel():
            return
        if pauses_stream:
            self._on_state("capturing")
            self._pause(for_capture=True)
        try:
            fut.set_result(fn(*args))
        except BaseException as e:  # noqa: BLE001 — geht an den Aufrufer
            fut.set_exception(e)
        finally:
            if pauses_stream:
                # Live-View startet der nächste Schleifendurchlauf neu, sofern
                # noch jemand zuschaut.
                self._on_state("live" if self._want_stream else "idle")
