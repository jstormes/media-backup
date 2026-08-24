#!/usr/bin/env python3
"""Diagnostic: does THIS drive produce any disc-insert notification at all?

Watches three independent channels at once and timestamps whichever fires:

  1. udisks2 D-Bus  -- PropertiesChanged on UDisks2.Block  (IdType, Size, ...)
  2. udisks2 D-Bus  -- PropertiesChanged on UDisks2.Drive  (MediaAvailable, ...)
  3. sysfs polling  -- /sys/block/srN/size                 (no uevent required)

Channels 1 and 2 are driven entirely by kernel uevents. Channel 3 is not.
If you insert a disc and only channel 3 reports, the drive emits no uevents
and no amount of udisks2/udev configuration will help.

Run:  python3 watch_disc_probe.py
      (then physically eject and re-insert a disc)

Requires: pip3 install dbus-next
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from dbus_next.aio import MessageBus
from dbus_next.constants import BusType

UDISKS = "org.freedesktop.UDisks2"
BLOCK = f"{UDISKS}.Block"
DRIVE = f"{UDISKS}.Drive"
POLL_SECONDS = 1.0


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def unwrap(variant_dict: dict) -> dict:
    """dbus-next hands back Variant objects; pull out the Python values."""
    return {k: v.value for k, v in variant_dict.items()}


def report(channel: str, target: str, fields: dict) -> None:
    print(f"\n[{ts()}] {channel:<14} {target}")
    for key, value in sorted(fields.items()):
        if isinstance(value, bytes):
            value = value.rstrip(b"\x00").decode("utf-8", "replace")
        if isinstance(value, list):
            value = f"<{len(value)} entries>"
        print(f"    {key:<22} {value}")
    sys.stdout.flush()


async def poll_sysfs(stop: asyncio.Event) -> None:
    """Channel 3 -- works even when the drive emits no uevents.

    Note: an unreadable size is tracked as its own state (None), NOT skipped.
    Skipping it would hide a whole eject/insert cycle: the value goes stale or
    unreadable while the tray is open, then returns to its original number on
    re-insert, so a naive comparison sees no change at all.
    """
    paths = sorted(Path("/sys/block").glob("sr*"))
    if not paths:
        print("[probe] no /sys/block/sr* devices found", flush=True)
        return

    def read(path: Path):
        try:
            raw = (path / "size").read_text().strip()
        except OSError as exc:
            return None, f"read error: {exc.__class__.__name__} {exc}"
        if not raw:
            return None, "read error: empty"
        try:
            return int(raw), None
        except ValueError:
            return None, f"read error: unparseable {raw!r}"

    state = {}
    for path in paths:
        sectors, err = read(path)
        state[path] = sectors
        print(f"[probe] baseline /dev/{path.name}: "
              f"{sectors if err is None else err} sectors "
              f"({'disc present' if sectors else 'empty'})", flush=True)

    ticks = 0
    while not stop.is_set():
        ticks += 1
        for path in paths:
            sectors, err = read(path)
            previous = state[path]
            if sectors == previous:
                continue
            state[path] = sectors
            if sectors is None:
                action = f"UNREADABLE ({err})"
            elif previous is None:
                action = "READABLE AGAIN"
            else:
                action = "INSERTED" if sectors else "EJECTED"
            report("SYSFS POLL", f"/dev/{path.name}", {
                "action": action,
                "size_sectors": sectors,
                "size_mb": sectors // 2048 if sectors else 0,
                "was_sectors": previous,
                "poll_tick": ticks,
            })
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except (asyncio.TimeoutError, TimeoutError):
            pass


async def main() -> None:
    stop = asyncio.Event()
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    def on_message(msg) -> None:
        # PropertiesChanged is emitted ON org.freedesktop.DBus.Properties.
        # The interface that actually changed is body[0], NOT msg.interface.
        if msg.member != "PropertiesChanged" or len(msg.body) < 2:
            return
        iface, changed = msg.body[0], unwrap(msg.body[1])
        name = (msg.path or "").rsplit("/", 1)[-1]

        if iface == BLOCK and name.startswith("sr"):
            interesting = {k: v for k, v in changed.items()
                           if k in ("Size", "IdType", "IdLabel", "IdUUID")}
            if interesting:
                report("DBUS/Block", f"/dev/{name}", interesting)
        elif iface == DRIVE:
            interesting = {k: v for k, v in changed.items()
                           if k.startswith(("Media", "Optical", "Size"))}
            if interesting:
                report("DBUS/Drive", name, interesting)

    bus.add_message_handler(on_message)
    bus._add_match_rule(
        "type='signal',"
        "interface='org.freedesktop.DBus.Properties',"
        "member='PropertiesChanged'"
    )

    print("[probe] watching udisks2 Block + Drive and sysfs size")
    print("[probe] now physically eject and re-insert a disc")
    print("[probe] Ctrl+C to stop\n", flush=True)

    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        import signal as _signal
        loop.add_signal_handler(getattr(_signal, signame), stop.set)

    def on_poller_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print(f"\n[probe] *** SYSFS POLLER DIED: "
                  f"{exc.__class__.__name__}: {exc} ***", flush=True)

    poller = asyncio.create_task(poll_sysfs(stop))
    poller.add_done_callback(on_poller_done)
    try:
        await stop.wait()
    finally:
        poller.cancel()
        bus.disconnect()
        print("\n[probe] stopped.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
