#!/usr/bin/env python3
"""Monitor for disc insertion/removal via udisks2 D-Bus signals.

Same mechanism GNOME uses — listens on the system bus for
org.freedesktop.UDisks2.Block.PropertiesChanged signals.

Run with:
    python3 udisks_monitor.py          # watch all block devices
    python3 udisks_monitor.py --dev sr0  # watch only /dev/sr0
"""
import sys
import signal
import argparse
import asyncio
from datetime import datetime, timezone
from dbus_next.aio import MessageBus
from dbus_next.constants import BusType


def main():
    parser = argparse.ArgumentParser(
        description="Monitor disc insertion/removal via udisks2 D-Bus signals"
    )
    parser.add_argument(
        "--dev", "-d",
        default="sr0",
        help="Device name to watch (default: sr0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after first event",
    )
    args = parser.parse_args()

    target_dev = args.dev
    print(f"[MONITOR] Watching /dev/{target_dev} for disc changes (udisks2 D-Bus).")
    print("[MONITOR] Press Ctrl+C to stop.\n")

    # State tracking: was_media_present per device
    last_seen: dict[str, bool | None] = {}

    # Collect results for the async callback to access
    results: list[str] = []

    async def run() -> None:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        # Add a match rule so we only receive PropertiesChanged on
        # org.freedesktop.UDisks2.Block interfaces.
        bus._add_match_rule(
            "type='signal',"
            "interface='org.freedesktop.DBus.Properties',"
            "member='PropertiesChanged',"
            f"arg0namespace='org.freedesktop.UDisks2.Block'"
        )

        def on_signal(message):
            if message.interface != "org.freedesktop.UDisks2.Block":
                return

            body = message.body
            if len(body) < 2:
                return
            changed = body[1]  # dict of changed properties

            # Device path: /org/freedesktop/UDisks2/block_devices/sr0
            dev_short = message.path.split("/")[-1].replace("_", "/")

            if args.once and len(target_dev) == len(dev_short):
                # For simplicity, accept any device — the user can filter later
                pass
            elif args.dev and dev_short != args.dev:
                return

            media_available = changed.get("MediaAvailable")
            id_type = changed.get("IdType", "n/a")
            size = changed.get("Size", 0)

            if media_available is None and id_type == "n/a" and size == 0:
                return  # nothing interesting

            prev = last_seen.get(dev_short)

            if media_available is True and prev is not True:
                action = "INSERTED"
            elif media_available is False and prev is not False:
                action = "EJECTED"
            else:
                action = "CHANGED"

            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            size_mb = size / (1024 * 1024) if size > 0 else 0

            msg = (
                f"\n[{now}] {action} /dev/{dev_short}\n"
                f"         IdType:    {id_type}\n"
                f"         Size:      {size_mb:.0f} MB ({size} bytes)" if size > 0
                else f"\n[{now}] {action} /dev/{dev_short}\n"
                     f"         IdType:    {id_type}\n"
                     f"         Size:      (none)\n"
                     f"         MediaAvailable: {media_available}"
            )
            print(msg)
            results.append(msg)

            last_seen[dev_short] = media_available

        bus.add_message_handler(on_signal)

        if args.once:
            # Just wait for one event
            while not results:
                await asyncio.sleep(0.5)
            print("\n[MONITOR] Received event. Done.")
        else:
            while True:
                await asyncio.sleep(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(signum, frame):
        print("\n[MONITOR] Stopped.")
        loop.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        task = loop.create_task(run())
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        print("\n[MONITOR] Stopped.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
