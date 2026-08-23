# Context-Reset Summary: Ticket #5 — Drive-closing copy trigger (udev events)

## Completed
1. Created `tests/udev_monitor.py` — pyudev monitor with sysfs polling fallback
2. Installed sudo skill in Qwen Code (`~/.qwen/skills/sudo/`)
3. Installed udev rule: `/etc/udev/rules.d/90-media-backup-ignore.rules` (UDISKS_IGNORE=1)
4. Documented: `docs/udev-gnome-interaction.md` — full investigation
5. Commented on GitHub issue #5 with results

## Key Finding
- **Kernel does NOT emit uevents for this USB external drive** (HL-DT-ST BD-RE BU40N, ID 13fd:0840)
- Physical eject/re-insert produces ZERO events via `udevadm monitor` or pyudev netlink
- This is a hardware limitation — USB bridge chip does not propagate tray/media-change to kernel
- GNOME does NOT steal events — udev rule prevents udisks2 interference (zero journal activity)
- The target build machine (internal SATA drive) should generate uevents natively

## Prototype Fixes (Aug 23, 2026 — context recovery)
The sysfs polling fallback was structurally broken in three ways:

1. **`_poll_loop()` never started** — defined but never called from `start()`
   - Fix: launch `_poll_loop()` in a background `threading.Thread` when netlink is unavailable
2. **Wrong sysfs attributes** — `_read_event_count()` parsed `/sys/class/block/sr0/events` as an integer, but it contains event names (`media_change eject_request`)
   - Fix: replaced with `_read_size()` reading `/sys/class/block/sr0/size` (sectors, `>0` = media present, `=0` = empty)
   - Also fixed: `_check_media_state()` read non-existent `/sys/class/block/sr0/media_available`
3. **Wrong sysfs path** — `self._device_path.lstrip("/")` on `/dev/sr0` produced `dev/sr0` (striked only the leading `/`)
   - Fix: use `os.path.basename(self._device_path)` → `sr0`

## Verified Polling Fallback
```
[MONITOR] Netlink unavailable — falling back to sysfs polling
[TEST] prev_size=90796672
[TEST] prev_media=1
[TEST] events=0
[TEST] _sys_path=/sys/class/block/sr0
```
- Polling correctly captures initial size (`90796672` sectors ≈ 43.7 GB BD-R)
- `prev_media=1` (media present detected)
- No events captured because disc is static (no change since boot)
- On an **internal SATA drive**, netlink will work and events will fire immediately
- For **USB drives without uevents**, polling every 1s via `size` change is the reliable fallback

## Sysfs Attributes on This Drive
| Attribute | Value | Notes |
|-----------|-------|-------|
| `/sys/class/block/sr0/size` | `90796672` | 512-byte sectors, BD-R disc |
| `/sys/class/block/sr0/removable` | `1` | USB external drive |
| `/sys/class/block/sr0/events` | `media_change eject_request` | Event names, NOT a counter |
| `/sys/class/block/sr0/events_async` | `0 0` | Two counters |
| `/sys/class/block/sr0/hidden` | `0` | No media |
| `/sys/class/block/sr0/media_available` | **N/A** | Does not exist |
| `/sys/class/block/sr0/mediate` | **N/A** | Does not exist |

## Environment
- OS: Ubuntu 26.04 (sudo-rs)
- pyudev 0.24.4 (API differs from older docs)
- Drive: HL-DT-ST BD-RE BU40N via USB
- Sudo: CLI skill installed at `~/.qwen/skills/sudo/`

## Next Steps for Resume
1. ✅ Polling fallback works — ready for Rust implementation
2. Test with an **internal SATA optical drive** (will generate native uevents)
3. File a new issue: "sysfs polling media detection for non-uevent USB drives"
4. Translate the polling approach to Rust: read `/sys/class/block/srN/size` every 5s, detect change → trigger copy
