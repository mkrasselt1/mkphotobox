#!/usr/bin/env python3
"""Touchscreen-Kalibrierung mit Fadenkreuzen auf dem Bildschirm.

Zeigt nacheinander fünf Fadenkreuze (vier mit 10 % Abstand zum Rand, eins in
der Mitte), liest dabei die Rohwerte direkt vom Touch-Gerät und rechnet daraus
per Ausgleichsrechnung die LIBINPUT_CALIBRATION_MATRIX. Die Ränder werden
hochgerechnet — man muss sie also nicht treffen. Genau das war der Haken am
Tippen "so weit außen wie möglich": wo der Finger am Gehäuserahmen hängen
bleibt, landete der Bildrand, und der äußerste Streifen war nicht mehr
erreichbar.

Danach: udev-Regel schreiben, Gerät neu einlesen, Testmodus (jeder Tipp malt
einen Punkt). Esc bricht jederzeit ab, ohne etwas zu ändern.

  sudo ./scripts/kiosk/touch-calibrate.py            # Gerät per Name suchen
  sudo ./scripts/kiosk/touch-calibrate.py --name eGalax
  sudo ./scripts/kiosk/touch-calibrate.py --dry-run  # nur rechnen, nichts schreiben

Läuft als root (Rohwerte lesen, Regel schreiben) und holt sich DISPLAY und
XAUTHORITY aus der laufenden Sitzung, wenn sie fehlen — geht also auch per SSH.
Braucht python3-tk.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import statistics
import struct
import subprocess
import sys

RULE_PATH = "/etc/udev/rules.d/99-touch-calibration.rules"
INSET = 0.10
TARGETS = [(INSET, INSET), (1 - INSET, INSET), (1 - INSET, 1 - INSET),
           (INSET, 1 - INSET), (0.5, 0.5)]
TARGET_NAMES = ["links oben", "rechts oben", "rechts unten", "links unten", "Mitte"]

EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)
EV_KEY, EV_ABS = 1, 3
BTN_TOUCH, ABS_X, ABS_Y = 330, 0, 1


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("E") << 8) | nr


def EVIOCGABS(axis: int) -> int:
    return _ioc(2, 0x40 + axis, 24)


EVIOCGRAB = _ioc(1, 0x90, 4)


# ── Gerät ────────────────────────────────────────────────────────────────
def find_device(name_part: str) -> tuple[str, str] | None:
    """(Gerätename, /dev/input/eventN) des ersten Geräts mit name_part im Namen."""
    name = None
    with open("/proc/bus/input/devices") as f:
        for line in f:
            if line.startswith("N: Name="):
                n = line.split("=", 1)[1].strip().strip('"')
                name = n if name_part.lower() in n.lower() else None
            elif name and line.startswith("H: Handlers="):
                for tok in line.split("=", 1)[1].split():
                    if tok.startswith("event"):
                        return name, "/dev/input/" + tok
    return None


def abs_range(fd: int, axis: int) -> tuple[int, int]:
    buf = fcntl.ioctl(fd, EVIOCGABS(axis), b"\0" * 24)
    _value, minimum, maximum, *_ = struct.unpack("6i", buf)
    return minimum, maximum


# ── Mathe ────────────────────────────────────────────────────────────────
def solve3(A: list[list[float]], b: list[float]) -> list[float]:
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for s in range(3):
        p = max(range(s, 3), key=lambda r: abs(M[r][s]))
        if abs(M[p][s]) < 1e-12:
            raise ValueError("Messpunkte liegen zu dicht beieinander")
        M[s], M[p] = M[p], M[s]
        for r in range(3):
            if r != s:
                f = M[r][s] / M[s][s]
                for c in range(s, 4):
                    M[r][c] -= f * M[s][c]
    return [M[i][3] / M[i][i] for i in range(3)]


def fit_row(points: list[tuple[float, float]], targets: list[float]) -> list[float]:
    """Kleinste Quadrate für  target = a*u + b*v + c."""
    A = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for (u, v), t in zip(points, targets):
        basis = (u, v, 1.0)
        for i in range(3):
            b[i] += basis[i] * t
            for j in range(3):
                A[i][j] += basis[i] * basis[j]
    return solve3(A, b)


# ── X-Sitzung finden (Aufruf per SSH) ────────────────────────────────────
def adopt_session_env() -> None:
    if os.environ.get("DISPLAY"):
        return
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() not in ("openbox", "gnome-shell", "Xwayland"):
                    continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = dict(kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv)
        except OSError:
            continue
        for key in (b"DISPLAY", b"XAUTHORITY"):
            if key in env:
                os.environ[key.decode()] = env[key].decode()
        if os.environ.get("DISPLAY"):
            return
    sys.exit("Keine laufende X-Sitzung gefunden — DISPLAY=:0 setzen?")


# ── Oberfläche ───────────────────────────────────────────────────────────
class Calibrator:
    def __init__(self, tk, dev_name: str, dev_path: str, dry_run: bool):
        self.tk = tk
        self.dev_name, self.dev_path, self.dry_run = dev_name, dev_path, dry_run
        self.fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
        self.xr, self.yr = abs_range(self.fd, ABS_X), abs_range(self.fd, ABS_Y)
        # Solange kalibriert wird, soll X die Tipps nicht sehen — sonst klickt
        # jeder Tipp irgendwo in den Kiosk-Browser unter dem Fenster.
        fcntl.ioctl(self.fd, EVIOCGRAB, 1)

        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black", cursor="none")
        self.root.bind("<Escape>", lambda _e: self.quit(1))
        self.w, self.h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h,
                                bg="black", highlightthickness=0)
        self.canvas.pack()

        self.step = 0
        self.samples: list[tuple[float, float]] = []
        self.touching = False
        self.cur_x = self.cur_y = None
        self.xs: list[int] = []
        self.ys: list[int] = []
        self.exit_code = 0
        self.draw_target()
        self.root.after(10, self.poll)

    # Rohwerte → 0..1, so wie libinput sie vor der Matrix normalisiert.
    def norm(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.xr[0]) / (self.xr[1] - self.xr[0]),
                (y - self.yr[0]) / (self.yr[1] - self.yr[0]))

    def text(self, msg: str, y: float = 0.5, size: int = 22, color: str = "white"):
        self.canvas.create_text(self.w / 2, self.h * y, text=msg, fill=color,
                                font=("Sans", size), justify="center")

    def draw_target(self) -> None:
        c = self.canvas
        c.delete("all")
        tx, ty = TARGETS[self.step]
        x, y = tx * self.w, ty * self.h
        c.create_line(x - 30, y, x + 30, y, fill="red", width=3)
        c.create_line(x, y - 30, x, y + 30, fill="red", width=3)
        c.create_oval(x - 6, y - 6, x + 6, y + 6, outline="red", width=2)
        # Hinweis nicht über das Mittelkreuz legen
        self.text(f"Kreuz {TARGET_NAMES[self.step]} genau in der Mitte antippen\n"
                  f"und kurz halten  ({self.step + 1}/{len(TARGETS)})   ·   Esc = Abbruch",
                  y=0.35 if self.step == len(TARGETS) - 1 else 0.5, size=18)

    def poll(self) -> None:
        try:
            while True:
                data = os.read(self.fd, EVENT_SIZE * 64)
                if not data:
                    break
                for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    self.handle(*struct.unpack(EVENT_FMT, data[off:off + EVENT_SIZE])[2:])
        except BlockingIOError:
            pass
        if self.step < len(TARGETS):
            self.root.after(10, self.poll)

    def handle(self, typ: int, code: int, value: int) -> None:
        if typ == EV_KEY and code == BTN_TOUCH:
            if value == 1:
                self.touching, self.xs, self.ys = True, [], []
            elif self.touching:
                self.touching = False
                if len(self.xs) >= 3:
                    self.accept(statistics.median(self.xs), statistics.median(self.ys))
        elif typ == EV_ABS and self.touching:
            if code == ABS_X:
                self.cur_x = value
            elif code == ABS_Y:
                self.cur_y = value
            if self.cur_x is not None and self.cur_y is not None:
                self.xs.append(self.cur_x)
                self.ys.append(self.cur_y)

    def accept(self, x: float, y: float) -> None:
        self.samples.append(self.norm(x, y))
        self.step += 1
        if self.step < len(TARGETS):
            self.draw_target()
        else:
            self.root.after(50, self.finish)

    def finish(self) -> None:
        fcntl.ioctl(self.fd, EVIOCGRAB, 0)
        os.close(self.fd)
        try:
            a, b, c = fit_row(self.samples, [t[0] for t in TARGETS])
            d, e, f = fit_row(self.samples, [t[1] for t in TARGETS])
        except ValueError as exc:
            return self.fail(f"Kalibrierung fehlgeschlagen: {exc}")

        worst = 0.0
        print("Abweichung je Kreuz nach Korrektur:")
        for name, (u, v), (tx, ty) in zip(TARGET_NAMES, self.samples, TARGETS):
            err = max(abs(a * u + b * v + c - tx), abs(d * u + e * v + f - ty))
            worst = max(worst, err)
            print(f"  {name:12s} {err * 100:4.1f} %")
        matrix = " ".join(f"{v:.6f}" for v in (a, b, c, d, e, f))
        print(f"Matrix: {matrix}")
        # Bei fünf Punkten und einer affinen Abbildung bleibt ein Rest; über 3 %
        # hat man meist danebengetippt oder der Finger ist gerutscht.
        if worst > 0.03:
            return self.fail(f"Ein Kreuz weicht {worst * 100:.0f} % ab — vermutlich daneben"
                             "getippt.\nBitte noch einmal starten. Es wurde nichts geändert.")
        if self.dry_run:
            print("--dry-run: nichts geschrieben")
        else:
            write_rule(self.dev_name, matrix)
        self.test_mode(matrix)

    def fail(self, msg: str) -> None:
        print("!! " + msg.replace("\n", " "))
        self.canvas.delete("all")
        self.text(msg + "\n\n(Fenster schließt in 8 s)", color="orange")
        self.exit_code = 1
        self.root.after(8000, lambda: self.quit(1))

    def test_mode(self, matrix: str) -> None:
        """Ab hier läuft der Touch wieder über X mit der neuen Matrix."""
        c = self.canvas
        c.delete("all")
        c.configure(cursor="")
        for i in range(1, 4):  # Rahmen in 1/2/3 % — so sieht man, wie nah man rankommt
            m = i * 0.01
            c.create_rectangle(self.w * m, self.h * m, self.w * (1 - m), self.h * (1 - m),
                               outline="#333")
        self.text("Test: überall hintippen, besonders an die Ränder.\n"
                  "Jeder Tipp malt einen Punkt.", y=0.4, size=18)
        btn_w, btn_h = 220, 70
        x0, y0 = (self.w - btn_w) / 2, self.h * 0.55
        c.create_rectangle(x0, y0, x0 + btn_w, y0 + btn_h, fill="#2a6", outline="", tags="done")
        c.create_text(self.w / 2, y0 + btn_h / 2, text="Fertig", fill="white",
                      font=("Sans", 20), tags="done")
        c.tag_bind("done", "<Button-1>", lambda _e: self.quit(0))
        c.bind("<Button-1>", self.dot, add="+")
        c.bind("<B1-Motion>", self.dot, add="+")

    def dot(self, ev) -> None:
        self.canvas.create_oval(ev.x - 4, ev.y - 4, ev.x + 4, ev.y + 4, fill="lime", outline="")

    def quit(self, code: int) -> None:
        self.exit_code = code
        self.root.destroy()


def write_rule(dev_name: str, matrix: str) -> None:
    rule = (
        "# Touchscreen-Kalibrierung — erzeugt von scripts/kiosk/touch-calibrate.py\n"
        "# Property heißt CALIBRATION (ein L).\n"
        f'SUBSYSTEM=="input", ATTRS{{name}}=="{dev_name}", '
        f'ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{matrix}"\n'
    )
    # Ältere Regeln für dasselbe Gerät würden je nach Dateiname gewinnen oder
    # verlieren — beiseitelegen, statt zu raten.
    for fn in sorted(os.listdir("/etc/udev/rules.d")):
        p = os.path.join("/etc/udev/rules.d", fn)
        if p == RULE_PATH or not fn.endswith(".rules"):
            continue
        with open(p, errors="replace") as f:
            body = f.read()
        if "LIBINPUT_CALIBRATION_MATRIX" in body and dev_name in body:
            os.rename(p, p + ".disabled")
            print(f"alte Regel beiseitegelegt: {p}.disabled")
    with open(RULE_PATH, "w") as f:
        f.write(rule)
    print(f"Regel geschrieben: {RULE_PATH}")
    subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
    reattach_device(dev_name)


def reattach_device(dev_name: str) -> None:
    """X liest die Matrix nur beim Hinzufügen des Geräts. Ein serielles Gerät
    (inputattach) taucht neu auf, wenn sein Dienst neu startet; sonst reicht
    ein udev-'add'."""
    for unit in ("egalax-inputattach.service", "egalax-touch.service"):
        if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
            subprocess.run(["systemctl", "restart", unit], check=False)
            print(f"{unit} neu gestartet")
            subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
            return
    found = find_device(dev_name)
    if found:
        sys_path = f"/sys/class/input/{os.path.basename(found[1])}"
        subprocess.run(["udevadm", "trigger", "--action=add", sys_path], check=False)
        subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default="touch", help="Teil des Gerätenamens (Vorgabe: touch)")
    ap.add_argument("--dry-run", action="store_true", help="nur rechnen, nichts schreiben")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("Bitte mit sudo starten.")
    found = find_device(args.name)
    if not found:
        sys.exit(f"Kein Eingabegerät mit '{args.name}' im Namen — läuft inputattach?")
    dev_name, dev_path = found
    print(f"Gerät: {dev_name} ({dev_path})")

    try:
        import tkinter
    except ImportError:
        sys.exit("tkinter fehlt:  sudo apt install python3-tk")
    adopt_session_env()
    app = Calibrator(tkinter, dev_name, dev_path, args.dry_run)
    app.root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
