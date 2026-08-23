# GNOME / udev Event Interference

## Current Status (Aug 23, 2026)

| Item | Status |
|------|--------|
| Sudo skill in Qwen Code | ✅ Installed (`~/.qwen/skills/sudo/`) |
| Udev rule installed | ✅ `/etc/udev/rules.d/90-media-backup-ignore.rules` |
| Rule matches sr0 | ✅ `UDISKS_IGNORE=1`, `UDISKS_PRESENTATION_HIDE=1` confirmed via `udevadm info` |
| GNOME automount interference | ❌ **Not observed** — zero udisks2 journal activity on sr0 |
| Kernel uevents for tray/media | ❌ **Zero events captured** by `udevadm monitor` over 30s |
| Netlink socket | ✅ Working (monitor starts without error, receives data when events exist) |

## What we verified

### 1. Udev rule is active and matching

```bash
$ udevadm info /dev/sr0 | grep UDISKS_IGNORE
E: UDISKS_IGNORE=1
E: UDISKS_PRESENTATION_HIDE=1
```

The rule matches via:
- `SUBSYSTEM=="block"`
- `KERNEL=="sr[0-9]*"`
- `ENV{ID_TYPE}=="cd"`
- `ENV{ID_VENDOR_ID}=="13fd"` (HL-DT-ST)
- `ENV{ID_MODEL_ID}=="0840"` (BD-RE_BU40N)

### 2. GNOME is NOT stealing events

Even though `gvfs-udisks2-volume-monitor` is running, journalctl shows **zero**
udisks2 activity on sr0 — the udev rule's `UDISKS_IGNORE=1` successfully prevents
udisks2 from touching the device.

### 3. Kernel does NOT generate uevents for this USB drive

We tested two approaches:

- **udevadm monitor** — captured zero events over 30s of idle + physical eject/re-insert
- **pyudev netlink monitor** — same: monitor starts, no events arrive

The kernel never emits `MEDIA_CHANGE`, `add`, `remove`, or any other block event for
`/dev/sr0` when the disc is physically ejected and re-inserted.

**This is a hardware limitation, not a software bug.** Many USB external optical drives
use bridge chips (often Genesys Logic or JMicron) that don't propagate tray/media events
to the kernel. The drive reports as removable (`removable=1`), but media-change events
are not forwarded by the USB bridge controller.

### 4. pyudev API differences (v0.24.4)

The current pyudev version on this system (0.24.4) differs from older docs:

| Old API | Current API | Notes |
|---------|-------------|-------|
| `context.query_by_device_node()` | Not available | Use `ctx.list_devices(subsystem="block")` and iterate |
| `device.device_name` | `device.sys_name` | |
| `Monitor.subscribe()` | `Monitor.filter_by()` | No per-device subscribe |
| `MonitorObserver(callback=fn(action, device))` | `MonitorObserver(callback=fn(device))` | Action on `device.action` |
| `pyudev.NoSuchDeviceError` | `pyudev.DeviceNotFoundError` | |

## Udev Rule

File: `/etc/udev/rules.d/90-media-backup-ignore.rules`

```udev
SUBSYSTEM=="block", \
  KERNEL=="sr[0-9]*", \
  ENV{ID_TYPE}=="cd", \
  ENV{ID_VENDOR_ID}=="13fd", \
  ENV{ID_MODEL_ID}=="0840", \
  ENV{UDISKS_IGNORE}="1", \
  ENV{UDISKS_PRESENTATION_HIDE}="1"
```

Install:
```bash
sudo install -m 0440 /path/to/90-media-backup-ignore.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=block
```

## Next Steps (for context reset)

The remaining issue is **kernel-level: USB external drives don't propagate
tray/media-change events**. Options:

1. **Poll /sys/class/block/sr0/ size** — the size field changes when media changes
   (current disc: 90796672 sectors for a BD-R disc). This is the most reliable
   approach for USB drives that don't generate uevents.

2. **Use `blockdev --rereadpt /dev/sr0` polling** — can detect media presence.

3. **Check if a different USB port or hub works better** — some bridge chips
   on certain USB host controllers do propagate events.

4. **Accept the limitation for USB external drives** — internal SATA optical drives
   on the target build machine should generate uevents natively. The prototype is
   for a USB external drive on the dev workstation, which is not representative
   of the target environment.

The `tests/udev_monitor.py` script already implements a sysfs polling fallback
mode — when netlink is unavailable, it polls `/sys/class/block/sr0/size` and
other attributes to detect media changes. This approach should work for the
polling fallback when netlink events are consumed by GNOME.

## References

- `tests/udev_monitor.py` — the prototype script
- `docs/udev-gnome-interaction.md` — this file
- `docs/adr/` — architecture decision records
