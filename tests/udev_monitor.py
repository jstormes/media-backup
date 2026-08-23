#!/usr/bin/env python3
"""
Prototype: Drive-closing copy trigger (udev events)
Issue #5

Monitors udev events for optical drives and validates:
  1. Tray open/close detection
  2. Media insert/eject detection
  3. Device path in events
  4. Event timing (delay from physical action)
  5. Device path → logical drive name mapping

Usage:
  python3 udev_monitor.py                    # Monitor all block devices
  python3 udev_monitor.py --device /dev/sr0  # Monitor specific device
  python3 udev_monitor.py --config           # Show drive config mapping
  python3 udev_monitor.py --simulate         # Show what events look like (dry run)
"""

import pyudev
import time
import json
import os
import sys
import argparse
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Drive config mapping
# ---------------------------------------------------------------------------

DRIVE_CONFIG_PATH = os.path.expanduser("~/.config/media-backup/drives.json")


@dataclass
class DriveMapping:
    logical_name: str
    device_path: str
    description: str = ""


class DriveMapper:
    """Map /dev/srN device paths to logical drive names (A, B, …).

    Config file format (drives.json):
    {
      "drive-a": "/dev/sr0",
      "drive-b": "/dev/sr1"
    }
    """

    def __init__(self, config_path: str = DRIVE_CONFIG_PATH) -> None:
        self.config_path = config_path
        self.mappings: dict[str, DriveMapping] = {}

    def load(self) -> dict[str, DriveMapping]:
        """Load mappings from config file. Returns empty dict if missing."""
        if not os.path.exists(self.config_path):
            print(f"[CONFIG] {self.config_path} not found — no drive mapping configured.")
            return {}
        with open(self.config_path, "r") as f:
            raw = json.load(f)
        self.mappings = {}
        for logical, devpath in raw.items():
            # Normalize logical name to "Drive-A" style
            logical_display = logical.replace("-", " ").title().replace("Drive", "Drive-")
            self.mappings[logical] = DriveMapping(
                logical_name=logical_display,
                device_path=devpath,
            )
        return self.mappings

    def resolve(self, device_path: str) -> Optional[str]:
        """Given a /dev/srN path, return the logical drive name, or None."""
        for key, mapping in self.mappings.items():
            if mapping.device_path == device_path:
                return mapping.logical_name
        return None

    def display_status(self) -> None:
        """Print current drive configuration to stdout."""
        mappings = self.load()
        if not mappings:
            print("No drive mappings configured.")
            print(
                f"  Expected format for {self.config_path}:\n"
                f'    {{"drive-a": "/dev/sr0", "drive-b": "/dev/sr1"}}'
            )
            return
        print(f"Drive mappings ({self.config_path}):")
        for key, m in mappings.items():
            print(f"  {m.logical_name:10s} -> {m.device_path}")


# ---------------------------------------------------------------------------
# Udev event monitoring
# ---------------------------------------------------------------------------

@dataclass
class UdevEvent:
    timestamp: str
    unix_ts: float
    action: str  # add, remove, change, switch, bind, unbind
    device_path: str
    subsystem: str
    sys_name: str
    driver: Optional[str]
    vendor: Optional[str]
    model: Optional[str]
    media_available: Optional[str]
    trigger_description: Optional[str] = None


class UdevEventMonitor:
    """Monitors udev events for block devices and captures optical drive events.

    Uses pyudev netlink MonitorObserver when available, with a polling fallback
    for /sys/class/block/sr0/ attributes when another process (e.g. GNOME)
    has already consumed the netlink socket.
    """

    def __init__(self, context: Optional[pyudev.Context] = None) -> None:
        self.context = context or pyudev.Context()
        self.events: list[UdevEvent] = []
        self.start_time: float = 0.0
        self._monitor: Optional[pyudev.Monitor] = None
        self._observer: Optional[pyudev.MonitorObserver] = None
        self._running = False
        self._device_filter: Optional[str] = None
        self._device_path: str = ""  # e.g. "/dev/sr0"
        self._last_event_cnt: Optional[int] = None

    # -- public API ----------------------------------------------------------

    def start(self, device_filter: Optional[str] = None) -> None:
        """Start monitoring. If device_filter is given, only that device."""
        self.start_time = time.time()
        self.events = []
        self._running = True
        self._device_filter = device_filter
        self._device_path = device_filter or "/dev/sr0"

        # Determine the sysfs path for polling fallback
        dev_name = os.path.basename(self._device_path)  # "sr0"
        self._sys_path = f"/sys/class/block/{dev_name}"

        # Attempt netlink monitoring first
        self._try_netlink()

        # If netlink failed (GNOME likely consumed the socket), switch to polling
        if not self._observer:
            print("[MONITOR] Netlink unavailable — falling back to sysfs polling")
            self._prev_size = self._read_size()
            self._prev_media = self._check_media_state()
            # Launch the polling loop in a background thread.
            self._poll_thread = threading.Thread(
                target=self._poll_loop, daemon=True
            )
            self._poll_thread.start()
        else:
            self._prev_media = None

        target = device_filter if device_filter else "all block devices"
        method = "polling" if not self._observer else "netlink"
        print(f"[MONITOR] Started at {datetime.now(timezone.utc).isoformat()}")
        print(f"[MONITOR] Watching {target} ({method})")
        print("[MONITOR] Press Ctrl+C to stop.\n")

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[MONITOR] Stopped by user.")
        finally:
            self.stop()

    def _try_netlink(self) -> None:
        """Attempt to start netlink monitoring. Returns False on failure."""
        try:
            self._monitor = pyudev.Monitor.from_netlink(self.context)
            self._monitor.filter_by("block")
            self._observer = pyudev.MonitorObserver(
                self._monitor,
                callback=self._on_event,
            )
            self._observer.start()
        except Exception:
            self._observer = None

    def stop(self) -> None:
        """Stop monitoring and summarize."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
        if hasattr(self, "_poll_thread") and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2)
        self._print_summary()

    def stop_event(self) -> None:
        """Signal the monitor to stop."""
        self._running = False

    # -- internal ------------------------------------------------------------

    def _on_event(self, device: pyudev.Device) -> None:
        """Callback for each udev event (single-arg callback for pyudev ≥0.24)."""
        # Filter by device path if requested
        if self._device_filter:
            dev_path = f"/{device.device_node}" if device.device_node else ""
            if dev_path != self._device_filter:
                return

        if device.subsystem != "block":
            return

        ts = time.time()
        now = datetime.now(timezone.utc).isoformat()
        delay = ts - self.start_time

        dev_path = f"/{device.device_node}" if device.device_node else "(none)"
        sys_name = device.sys_name
        action = device.action or "unknown"

        vendor = device.get("ID_VENDOR", "")
        model = device.get("ID_MODEL", "")
        media_available = device.get("MEDIA", "")
        driver = device.get("DRIVER", "")

        description = self._describe_event(action, media_available)

        event = UdevEvent(
            timestamp=now,
            unix_ts=ts,
            action=action,
            device_path=dev_path,
            subsystem=device.subsystem,
            sys_name=sys_name,
            driver=driver if driver != "" else None,
            vendor=vendor if vendor != "" else None,
            model=model if model != "" else None,
            media_available=media_available if media_available != "" else None,
            trigger_description=description,
        )

        self.events.append(event)
        self._print_event(event, delay)

    # -- polling fallback ----------------------------------------------------

    def _read_size(self) -> Optional[int]:
        """Read /sys/class/block/<dev>/size in 512-byte sectors.

        size = 0  ⇒  no media in tray.
        size > 0  ⇒  media present.
        """
        try:
            with open(f"{self._sys_path}/size", "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _check_media_state(self) -> Optional[str]:
        """Check if media is available via sysfs size.

        Returns '1' when size > 0 (media present), '0' when size == 0 (empty/ejected),
        or None when the sysfs entry is unreadable.
        """
        size = self._read_size()
        if size is None:
            return None
        return "1" if size > 0 else "0"

    def _poll_loop(self) -> None:
        """Poll sysfs for media-size changes (fallback when netlink is unavailable)."""
        while self._running:
            current_size = self._read_size()
            if current_size is not None:
                if self._prev_size is not None and current_size != self._prev_size:
                    # Size changed — media was inserted or ejected
                    self._capture_poll_event(current_size)
                self._prev_size = current_size
            time.sleep(1)

    def _capture_poll_event(self, current_size: int) -> None:
        """Capture an event based on current sysfs size."""
        ts = time.time()
        now = datetime.now(timezone.utc).isoformat()
        delay = ts - self.start_time

        # Read current media state
        media = self._check_media_state()

        # Determine action from previous vs current size
        prev_size = self._prev_size

        if current_size > 0 and prev_size == 0:
            action = "change"
            description = f"MEDIA_INSERTED ({current_size * 512 // (1024*1024)} MB)"
        elif current_size == 0 and prev_size > 0:
            action = "change"
            description = "MEDIA_EJECTED"
        else:
            action = "change"
            description = f"MEDIA_CHANGED (size={current_size})"

        event = UdevEvent(
            timestamp=now,
            unix_ts=ts,
            action=action,
            device_path=self._device_path,
            subsystem="block",
            sys_name=self._device_path.lstrip("/"),
            driver=None,
            vendor=None,
            model=None,
            media_available=media,
            trigger_description=description,
        )

        self.events.append(event)
        self._print_event(event, delay)
        print(f"         Size: {current_size} sectors ({current_size * 512 // (1024*1024)} MB)  Media: {media}")

    # -- event display -------------------------------------------------------

    def _print_event(self, event: UdevEvent, delay: float) -> None:
        """Print a single event to stdout."""
        drive_name = None
        mapper = DriveMapper()
        mappings = mapper.load()
        if mappings:
            drive_name = mapper.resolve(event.device_path)

        header = (
            f"[EVENT] t+{delay:.3f}s  {event.action:8s}  "
            f"{event.device_path:10s}  {event.trigger_description}"
        )
        if drive_name:
            header += f"  [{drive_name}]"

        print(header)

        # Print device details (limited for optical drives)
        if "sr" in event.sys_name:
            if event.vendor or event.model:
                print(f"         Device: {event.vendor} {event.model}".strip())
            if event.media_available:
                print(f"         Media:  {event.media_available}")
            if event.driver:
                print(f"         Driver: {event.driver}")

    def _print_summary(self) -> None:
        """Print summary after monitoring stops."""
        print(f"\n{'=' * 60}")
        print(f"SUMMARY — {len(self.events)} event(s) captured")
        print(f"{'=' * 60}")

        # Group by action
        by_action: dict[str, list[UdevEvent]] = {}
        for e in self.events:
            by_action.setdefault(e.action, []).append(e)

        for action, evts in sorted(by_action.items()):
            print(f"\n  {action.upper()}: {len(evts)} event(s)")
            for e in evts:
                drive_name = None
                mapper = DriveMapper()
                mappings = mapper.load()
                if mappings:
                    drive_name = mapper.resolve(e.device_path)
                detail = f"  {e.device_path}  {e.trigger_description}"
                if drive_name:
                    detail += f"  [{drive_name}]"
                print(detail)
                if e.vendor or e.model:
                    print(f"    Device: {e.vendor} {e.model}".strip())

        # Timing analysis
        if len(self.events) >= 2:
            deltas = [
                self.events[i].unix_ts - self.events[i - 1].unix_ts
                for i in range(1, len(self.events))
            ]
            print(f"\n  Timing between events:")
            for i, d in enumerate(deltas):
                print(f"    event {i + 1} → {i + 2}:  {d:.3f}s")

        # Check for copy-trigger-worthy events
        copy_triggers = [
            e for e in self.events
            if e.action == "change" and e.media_available
        ]
        if copy_triggers:
            print(f"\n  Copy-trigger candidates (media inserted): {len(copy_triggers)}")
            for e in copy_triggers:
                print(f"    {e.device_path} at t+{e.unix_ts - self.start_time:.3f}s")
        elif self.events:
            print(f"\n  No media-inserted events captured.")
            print(f"  (Try ejecting and reinserting a disc to see copy-trigger events.)")


# ---------------------------------------------------------------------------
# Simulation / dry-run
# ---------------------------------------------------------------------------

def print_simulation() -> None:
    """Print what events will look like (for documentation / validation)."""
    print("Simulated udev events for optical drive:\n")
    sim_events = [
        {
            "desc": "Disc in tray, tray closes",
            "action": "change",
            "media": "1",
            "detail": "HL-DT-ST BD-RE BU40N",
        },
        {
            "desc": "Disc ejected",
            "action": "change",
            "media": "0",
            "detail": "HL-DT-ST BD-RE BU40N",
        },
        {
            "desc": "Disc inserted (new media)",
            "action": "change",
            "media": "1",
            "detail": "HL-DT-ST BD-RE BU40N",
        },
    ]
    for i, ev in enumerate(sim_events):
        print(f"  [{i + 1}] {ev['desc']}")
        print(f"      action={ev['action']}  media_available={ev['media']}")
        print(f"      device=HL-DT-ST BD-RE BU40N  /dev/sr0")
        if ev["action"] == "change" and ev["media"] == "1":
            print("      >>> COPY TRIGGER: drive closing / media inserted")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prototype: udev event monitor for optical drive copy trigger"
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Monitor only this device (e.g. /dev/sr0)",
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Show drive config file and mappings",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Print simulated events without monitoring",
    )
    args = parser.parse_args()

    if args.config:
        DriveMapper().display_status()
        sys.exit(0)

    if args.simulate:
        print_simulation()
        sys.exit(0)

    # Live monitoring mode (default)
    context = pyudev.Context()
    monitor = UdevEventMonitor(context)

    if args.device:
        # Validate the device exists by searching via list_devices
        dev_node = args.device.lstrip("/")  # e.g. "sr0"
        device = None
        for d in context.list_devices(subsystem="block"):
            if d.device_node == args.device:
                device = d
                break
        if not device:
            print(f"[ERROR] Device {args.device} not found.")
            sys.exit(1)
        print(f"[CONFIG] Monitoring device: {args.device}")
        print(f"[CONFIG] Model: {device.get('ID_MODEL', 'unknown')}")
        print(f"[CONFIG] Vendor: {device.get('ID_VENDOR', 'unknown')}")
        mapper = DriveMapper()
        logical = mapper.resolve(args.device)
        if logical:
            print(f"[CONFIG] Logical name: {logical}")
        else:
            print(f"[CONFIG] Not in drive config — update {DRIVE_CONFIG_PATH}")
    else:
        # Show available block devices
        devs = context.list_devices(subsystem="block")
        devs.reload()
        optical = [d for d in devs if d.get("ID_TYPE") == "cd"]
        if optical:
            print(f"[CONFIG] Found {len(optical)} optical drive(s):")
            for d in optical:
                dev_path = f"/{d.device_node}" if d.device_node else "?"
                model = d.get("ID_MODEL", "unknown")
                vendor = d.get("ID_VENDOR", "unknown")
                mapper = DriveMapper()
                logical = mapper.resolve(dev_path)
                logical_str = f"  [{logical}]" if logical else ""
                print(f"  {dev_path}  {vendor} {model}{logical_str}")

    monitor.start(device_filter=args.device)


if __name__ == "__main__":
    main()
