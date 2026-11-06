"""Tailscale aus dem Admin-Bereich steuern (verbinden, trennen, abmelden).

Voraussetzung: scripts/setup.sh hat Tailscale installiert und den Dienst-User
per ``tailscale set --operator=<user>`` zum Operator gemacht. Dann laufen
``tailscale up/down/logout`` ohne sudo — ausprobiert mit tailscale 1.104
(ein Nicht-Operator bekommt "Access denied: prefs write access denied").

Anmeldung: ``tailscale up`` blockiert, bis jemand den Anmeldelink im Browser
bestätigt hat. Deshalb läuft der Prozess im Hintergrund; wir lesen nur die
Anmelde-URL aus seiner ``--json``-Ausgabe (Feld ``AuthURL``). Als Rückfall
steht dieselbe URL auch in ``tailscale status --json`` (ebenfalls ``AuthURL``),
solange der Zustand ``NeedsLogin`` ist.
"""

from __future__ import annotations

import getpass
import json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time

log = logging.getLogger(__name__)

# Länger als ein paar Minuten wartet niemand auf den Link — danach den
# Hintergrundprozess beenden, damit keine Leichen herumliegen. Die Anmeldung
# selbst bleibt im tailscaled-Backend gültig; ein neuer Klick holt einen
# frischen Link.
_UP_LIFETIME_S = 15 * 60

_lock = threading.Lock()
_proc: subprocess.Popen | None = None

_HOST_RE = re.compile(r"[^a-z0-9-]+")


class TailscaleError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("tailscale") is not None


def _run(*args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    if not available():
        raise TailscaleError("Tailscale ist nicht installiert (scripts/setup.sh erneut ausführen).")
    try:
        return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TailscaleError(f"tailscale {args[0]} reagiert nicht (Zeitüberschreitung).")


def _explain(stderr: str) -> str:
    """Fehlermeldung von tailscale verständlich machen."""
    msg = (stderr or "").strip()
    if "access denied" in msg.lower() or "sudo tailscale" in msg:
        return ("Keine Berechtigung, Tailscale zu steuern. Der Dienst-Benutzer muss "
                "Tailscale-Operator sein — einmal 'sudo ./scripts/setup.sh' erneut "
                "ausführen (oder 'sudo tailscale set --operator=$USER').")
    if "doesn't appear to be running" in msg or "failed to connect to local tailscaled" in msg:
        return "Der Tailscale-Dienst (tailscaled) läuft nicht."
    return msg or "unbekannter Fehler"


def status() -> dict:
    r = _run("status", "--json")
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        raise TailscaleError(_explain(r.stderr))


def clean_hostname(name: str | None) -> str:
    name = _HOST_RE.sub("-", (name or "").strip().lower()).strip("-")[:63]
    if not name:
        name = _HOST_RE.sub("-", socket.gethostname().lower()).strip("-")[:63] or "mkphotobox"
    return name


def _stop_proc() -> None:
    global _proc
    p = _proc
    _proc = None
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _reaper(p: subprocess.Popen) -> None:
    """Hintergrund-'tailscale up' nach spätestens _UP_LIFETIME_S beenden."""
    try:
        p.wait(timeout=_UP_LIFETIME_S)
    except subprocess.TimeoutExpired:
        with _lock:
            if _proc is p:
                _stop_proc()
            else:
                p.kill()


def up(hostname: str | None = None, auth_key: str | None = None, timeout: float = 25) -> dict:
    """``tailscale up`` im Hintergrund starten.

    Rückgabe: ``{"state": ..., "auth_url": ...}``. Mit Auth-Key ist ``state``
    nach kurzer Zeit ``Running`` und es gibt keine URL; ohne Key liefern wir
    den Anmeldelink, sobald tailscale ihn ausgibt (spätestens nach *timeout*).
    """
    global _proc
    if not available():
        raise TailscaleError("Tailscale ist nicht installiert (scripts/setup.sh erneut ausführen).")

    # --reset: sonst verweigert 'tailscale up' den Start, sobald irgendeine
    # früher gesetzte Einstellung hier nicht erneut genannt wird. Damit --reset
    # nicht die Operator-Rechte wegwirft, nennen wir uns selbst wieder als
    # Operator (als Operator erlaubt, getestet).
    args = ["tailscale", "up", "--json", "--reset", "--ssh",
            f"--hostname={clean_hostname(hostname)}"]
    user = getpass.getuser()
    if user != "root":
        args.append(f"--operator={user}")
    key = (auth_key or "").strip()
    if key:
        args.append(f"--auth-key={key}")

    with _lock:
        _stop_proc()
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        except OSError as e:
            raise TailscaleError(str(e))
        _proc = p

    result: dict = {}
    stderr_lines: list[str] = []
    done = threading.Event()

    def read_stdout() -> None:
        # --json schreibt ein mehrzeiliges JSON-Objekt; Zeilen sammeln, bis es
        # sich parsen lässt. Weitere Objekte (Zustandswechsel) folgen evtl.
        buf = ""
        for line in p.stdout:  # type: ignore[union-attr]
            buf += line
            try:
                obj = json.loads(buf)
            except ValueError:
                continue
            buf = ""
            if isinstance(obj, dict):
                result.update(obj)
                if obj.get("AuthURL") or obj.get("BackendState") == "Running":
                    done.set()
        done.set()

    def read_stderr() -> None:
        for line in p.stderr:  # type: ignore[union-attr]
            stderr_lines.append(line)
            m = re.search(r"https://login\.tailscale\.com/\S+", line)
            if m and not result.get("AuthURL"):
                result["AuthURL"] = m.group(0)
                done.set()

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    deadline = time.monotonic() + timeout
    while not done.is_set() and time.monotonic() < deadline:
        done.wait(1.0)
        if done.is_set():
            break
        # Rückfall: AuthURL steht auch im Status, sobald das Backend sie hat
        try:
            st = status()
            if st.get("AuthURL") or st.get("BackendState") == "Running":
                result.setdefault("AuthURL", st.get("AuthURL") or "")
                result.setdefault("BackendState", st.get("BackendState"))
                break
        except TailscaleError:
            pass

    rc = p.poll()
    if rc is not None and rc != 0 and not result.get("AuthURL"):
        time.sleep(0.2)  # stderr-Leser fertig lesen lassen
        raise TailscaleError(_explain("".join(stderr_lines)))

    if p.poll() is None:
        threading.Thread(target=_reaper, args=(p,), daemon=True).start()

    state = result.get("BackendState") or ""
    try:
        state = status().get("BackendState") or state
    except TailscaleError:
        pass
    return {"state": state, "auth_url": result.get("AuthURL") or ""}


def down() -> None:
    with _lock:
        _stop_proc()
    r = _run("down")
    if r.returncode != 0:
        raise TailscaleError(_explain(r.stderr))


def logout() -> None:
    with _lock:
        _stop_proc()
    r = _run("logout", timeout=30)
    if r.returncode != 0:
        raise TailscaleError(_explain(r.stderr))
