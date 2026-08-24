#!/usr/bin/env python3
"""Watch for D-Bus signals from udisks2 about optical drives.

Run as:
    python3 watch_disc.py

Press Ctrl+C to stop.

Requires:  pip3 install dbus-next
"""
import sys
import asyncio
import signal
from datetime import datetime, timezone

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType

# ─── what to listen for ───────────────────────────────────────────
# udisks2 fires PropertiesChanged on org.freedesktop.UDisks2.Block
# whenever a block device's properties change.  On a SATA drive this
# includes MediaAvailable, IdType, Size when a disc is inserted or
# ejected.
#
# This will NOT fire for a USB external drive whose bridge chip
# silently drops media-change events (our HL-DT-ST BU40N).
# It WILL fire for a built-in / SATA optical drive.
# ──────────────────────────────────────────────────────────────────

async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    def on_signal(msg):
        if msg.interface != "org.freedesktop.UDisks2.Block":
            return

        body = msg.body
        if len(body) < 2:
            return
        changed = body[1]  # dict

        dev = msg.path.split("/")[-1].replace("_", "/")
        if not dev.startswith("sr"):
            return  # not an optical drive

        media_available = changed.get("MediaAvailable")
        id_type = changed.get("IdType", "n/a")
        size = changed.get("Size", 0)

        if media_available is None and id_type == "n/a" and size == 0:
            return

        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        size_mb = size / (1024 * 1024) if size > 0 else 0

        # ── pretty print ──────────────────────────────────────────
        if media_available is True:
            action = "INSERTED"
        elif media_available is False:
            action = "EJECTED"
        else:
            action = "CHANGED"
        # ──────────────────────────────────────────────────────────

        print(f"\n[{now}] {action:8s} /dev/{dev}")
        print(f"         IdType:    {id_type}")
        print(f"         Size:      {size_mb:.0f} MB ({size} bytes)" if size else "         Size:      (none)")
        print(f"         MediaAvail:{media_available}")
        sys.stdout.flush()

    bus.add_message_handler(on_signal)

    # Only receive PropertiesChanged on org.freedesktop.UDisks2.Block
    bus._add_match_rule(
        "type='signal',"
        "interface='org.freedesktop.DBus.Properties',"
        "member='PropertiesChanged',"
        "arg0namespace='org.freedesktop.UDisks2.Block'"
    )

    print("[MONITOR] Watching for D-Bus signals from optical drives…")
    print("[MONITOR] Press Ctrl+C to stop.\n")

    # ─── keep running ─────────────────────────────────────────────
    running = asyncio.get_event_loop()
    def shutdown(_sig, _frame):
        print("\n[MONITOR] Stopped.")
        running.stop()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        await asyncio.Future()  # runs forever
    finally:
        await bus.disconnect()

if __name__ == "__main__":
    asyncio.run(main(), debug=True)
