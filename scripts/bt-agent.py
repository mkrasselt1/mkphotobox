#!/usr/bin/env python3
"""BlueZ pairing agent for the photo booth — pairs without anyone typing anything.

Why this exists instead of ``bt-agent`` from bluez-tools:

That tool is from 2017 and, when BlueZ asks it for a PIN, prints ``Enter
passkey:`` and waits for someone to type on **stdin**. As a systemd service it
has no stdin, so it reads NULL, dies with ``g_variant_new_string: assertion
'string != NULL' failed`` and never answers. BlueZ waits, the phone shows a PIN
prompt that can never be satisfied, and pairing times out. Exactly what happened
on the box: several ``Enter passkey`` lines, zero paired devices.

A booth has no keyboard and nobody to watch a screen. The correct capability is
therefore ``NoInputNoOutput``, which makes BlueZ use "Just Works": no number
anywhere, the guest only confirms on their phone. Every callback below answers
immediately and never blocks.

Paired devices are also marked *trusted*, otherwise every single file transfer
asks for authorisation again — with no one there to grant it.

Run it as the user that owns the session bus; it talks to the system bus for
BlueZ but must outlive any login. See scripts/setup.sh.
"""

from __future__ import annotations

import argparse
import logging
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

AGENT_PATH = "/org/mkphotobox/agent"
BLUEZ = "org.bluez"
AGENT_IFACE = "org.bluez.Agent1"

log = logging.getLogger("bt-agent")


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


class BoothAgent(dbus.service.Object):
    """Answers every BlueZ request without human interaction.

    The signatures are fixed by the org.bluez.Agent1 interface; BlueZ picks
    which ones it calls from the capability we register with. With
    NoInputNoOutput it normally only needs RequestAuthorization and
    AuthorizeService — the rest are implemented anyway so that an older phone
    falling back to legacy pairing still gets an answer instead of silence.
    """

    def __init__(self, bus, path: str, pin: str):
        super().__init__(bus, path)
        self._bus = bus
        self._pin = pin

    # ── helpers ──────────────────────────────────────────────────────────

    def _trust(self, device) -> None:
        """Mark a device trusted so later transfers don't ask again."""
        try:
            props = dbus.Interface(
                self._bus.get_object(BLUEZ, device), "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            log.info("Trusted %s", device)
        except Exception:
            log.warning("Could not set Trusted on %s", device, exc_info=True)

    # ── org.bluez.Agent1 ─────────────────────────────────────────────────

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        log.info("Agent released")

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        # Das ist die Rückfrage vor einer Dateiübertragung. Ohne automatisches
        # Ja bleibt jedes Foto hängen, weil niemand an der Box bestätigt.
        log.info("Authorising service %s for %s", uuid, device)
        self._trust(device)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        log.info("Legacy PIN requested by %s — answering automatically", device)
        self._trust(device)
        return self._pin

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        log.info("Passkey requested by %s — answering automatically", device)
        self._trust(device)
        return dbus.UInt32(int(self._pin))

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        # Nichts anzuzeigen — die Box hat dafür keine Anzeige.
        log.info("Passkey for %s: %06d (%d entered)", device, passkey, entered)

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        log.info("PIN for %s: %s", device, pincode)

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log.info("Confirming %06d for %s", passkey, device)
        self._trust(device)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        log.info("Authorising %s", device)
        self._trust(device)

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        log.info("Request cancelled by BlueZ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capability", default="NoInputNoOutput",
                    help="BlueZ agent capability (default: NoInputNoOutput = Just Works)")
    ap.add_argument("--pin", default="0000",
                    help="Fallback for phones that insist on legacy pairing (default: 0000)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.pin.isdigit():
        log.error("--pin muss aus Ziffern bestehen (RequestPasskey liefert eine Zahl)")
        return 2

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    BoothAgent(bus, AGENT_PATH, args.pin)

    manager = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
    manager.RegisterAgent(AGENT_PATH, args.capability)
    # Ohne RequestDefaultAgent bleibt ein anderer Agent zuständig, und unsere
    # Antworten kommen nie zum Zug.
    manager.RequestDefaultAgent(AGENT_PATH)
    log.info("Agent registered as default (capability=%s)", args.capability)

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            manager.UnregisterAgent(AGENT_PATH)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
