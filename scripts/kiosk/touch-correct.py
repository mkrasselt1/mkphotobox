#!/usr/bin/env python3
"""Entzerrt einen Touchscreen nichtlinear und gibt ihn als virtuelles Gerät weiter.

Ältere resistive Panels messen nicht linear: die Kantenmitten werden nach
innen gezogen ("Kissen"), an den Seiten bleiben halbrunde Streifen, die man
nicht erreicht. Eine libinput-Kalibriermatrix ist nur affin — gerade Linien
bleiben gerade — und kann das grundsätzlich nicht ausgleichen.

Dieser Dienst liest das echte Gerät exklusiv (EVIOCGRAB, X sieht es dann
nicht mehr), bildet jeden Punkt über ein Polynom 3. Grades auf den Bildschirm
ab und schreibt ihn in ein virtuelles Gerät (uinput) mit denselben Fähigkeiten.
Die Koeffizienten erzeugt  touch-calibrate.py --grid  in
/etc/mkphotobox/touch-correction.json.

Läuft als systemd-Dienst mkphotobox-touch.service. Verschwindet das Gerät
(z. B. inputattach startet neu), wartet er und hängt sich wieder an.
"""
from __future__ import annotations

import json
import sys
import time

CONF = "/etc/mkphotobox/touch-correction.json"
VIRTUAL_NAME = "MKPhotobox Touch (entzerrt)"


def poly_terms(u: float, v: float, degree: int) -> list[float]:
    """1, u, v, u², uv, v², … bis Grad ``degree`` — dieselbe Reihenfolge wie
    beim Anpassen in touch-calibrate.py."""
    return [u ** (d - j) * v ** j for d in range(degree + 1) for j in range(d + 1)]


def evaluate(coef: list[float], u: float, v: float, degree: int) -> float:
    return sum(c * t for c, t in zip(coef, poly_terms(u, v, degree)))


def find_device(evdev, name: str):
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == name:
            return dev
        dev.close()
    return None


def run(cfg: dict) -> None:
    import evdev
    from evdev import UInput, ecodes as e

    name, degree = cfg["device"], int(cfg["degree"])
    cx, cy = cfg["x"], cfg["y"]
    while True:
        dev = find_device(evdev, name)
        if dev is None:
            time.sleep(2)
            continue
        ax, ay = dev.absinfo(e.ABS_X), dev.absinfo(e.ABS_Y)
        sx, sy = ax.max - ax.min, ay.max - ay.min
        try:
            ui = UInput.from_device(dev, name=VIRTUAL_NAME, input_props=dev.input_props())
        except TypeError:  # ältere python-evdev ohne input_props
            ui = UInput.from_device(dev, name=VIRTUAL_NAME)
        print(f"entzerre {dev.path} ({name}) -> {ui.device.path}", flush=True)
        raw_x = raw_y = None
        pending = []
        try:
            dev.grab()
            for ev in dev.read_loop():
                if ev.type == e.EV_ABS and ev.code == e.ABS_X:
                    raw_x = ev.value
                elif ev.type == e.EV_ABS and ev.code == e.ABS_Y:
                    raw_y = ev.value
                elif ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
                    for p in pending:
                        ui.write_event(p)
                    pending.clear()
                    if raw_x is not None and raw_y is not None:
                        u, v = (raw_x - ax.min) / sx, (raw_y - ay.min) / sy
                        x = min(1.0, max(0.0, evaluate(cx, u, v, degree)))
                        y = min(1.0, max(0.0, evaluate(cy, u, v, degree)))
                        ui.write(e.EV_ABS, e.ABS_X, round(ax.min + x * sx))
                        ui.write(e.EV_ABS, e.ABS_Y, round(ay.min + y * sy))
                    ui.syn()
                elif ev.type != e.EV_SYN:
                    pending.append(ev)
        except OSError as exc:
            print(f"Gerät weg ({exc}) — warte auf Wiederkehr", flush=True)
        finally:
            ui.close()
            try:
                dev.close()
            except OSError:
                pass
        time.sleep(1)


def main() -> int:
    try:
        with open(CONF) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"{CONF} fehlt — erst  sudo touch-calibrate.py --grid 5", file=sys.stderr)
        return 1
    run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
