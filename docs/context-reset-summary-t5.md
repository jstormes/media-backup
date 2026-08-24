# Context-Reset Summary: Ticket #5 — Drive-closing copy trigger

> **CORRECTION (Aug 23, 2026, later same day).** The original version of this
> document concluded that this drive emits no kernel uevents and that sysfs
> polling was the only viable trigger. **Both conclusions were wrong.** Live
> testing with a physical eject/re-insert proved that udev events *do* fire and
> that udisks2 reports them over D-Bus. The superseded claims are preserved
> under [Superseded Findings](#superseded-findings) so the reasoning error is
> not repeated. The recommended architecture has changed — see
> [Corrected Recommendation](#corrected-recommendation).

## Key Finding (corrected)

- **The kernel DOES emit uevents for this drive** (HL-DT-ST BD-RE BU40N, ID 13fd:0840).
- Physical eject and re-insert both produce `org.freedesktop.DBus.Properties.PropertiesChanged`
  signals from udisks2, on both the `Drive` and `Block` interfaces.
- udisks2 has no polling of its own — it is driven **entirely** by udev uevents via
  its GUdev client. Its properties changing is therefore proof that uevents reached udev.
- `UDISKS_IGNORE=1` does **not** suppress D-Bus signals. It sets the advisory
  `Block.HintIgnore` property that GNOME/gvfs read to skip automount and auto-open.
  udisks2 itself still probes the device and still emits property changes.

### Verified evidence

Captured with `tests/watch_disc_probe.py` during a physical eject/re-insert:

```
[probe] baseline /dev/sr0: 90796672 sectors (disc present)

[21:18:07.114] DBUS/Drive     HL_DT_ST_BD_RE_BU40N_393032485330313735363920
    Media
    MediaAvailable         False
    Optical                False
    OpticalNumTracks       0
    Size                   0

[21:18:07.115] DBUS/Block     /dev/sr0
    IdLabel
    IdType
    IdUUID
    Size                   0

[21:18:31.953] DBUS/Drive     HL_DT_ST_BD_RE_BU40N_393032485330313735363920
    Media                  optical_bd
    MediaAvailable         True
    Optical                True
    OpticalNumTracks       1
    Size                   46487896064

[21:18:31.953] DBUS/Block     /dev/sr0
    IdLabel                SPIDER_MAN_ACROSS_SPIDER_VERSE
    IdType                 udf
    IdUUID                 8db83afad61fd041
    Size                   46487896064
```

`HintIgnore` was `true` on sr0 throughout — the signals arrived anyway.

## Why the original test produced a false negative

The original run recorded this line in its own output:

```
[MONITOR] Netlink unavailable — falling back to sysfs polling
```

The pyudev netlink monitor **never started**. A monitor that is not running
observes zero events regardless of what the hardware does. "Zero events
captured" was a property of the test harness, not of the drive, and it was
recorded as a hardware limitation.

Note also that `docs/udev-gnome-interaction.md` line 12 asserts the opposite —
"Netlink socket ✅ Working" — so the two documents already contradicted each other.

**Lesson:** a monitor reporting no events is only evidence when the monitor is
independently confirmed to be live. Always establish a positive control (trigger
a known event and see it arrive) before concluding that events do not exist.

## Uevents here are poll-derived, not asynchronous

Important operational caveat — the events exist, but not because the drive
volunteers them:

| Attribute | Value | Meaning |
|-----------|-------|---------|
| `/sys/block/sr0/events_async` | *(blank)* | Drive does **not** support asynchronous event notification |
| `/sys/block/sr0/events_poll_msecs` | `-1` | Inherit the global default |
| `/sys/module/block/parameters/events_dfl_poll_msecs` | `2000` | Block layer polls every 2s |

The kernel's block layer polls the drive every ~2s and synthesises
`media_change` uevents. Consequences:

- Trigger latency is up to ~2s after tray close.
- **This depends on `events_dfl_poll_msecs` staying non-zero.** If it is set to
  `0` (some kernels and tuning guides do this), uevents stop and the D-Bus
  trigger silently dies. Pin it per-device by writing to
  `/sys/block/sr0/events_poll_msecs` if reliability matters.

## Corrected Recommendation

Trigger on **`org.freedesktop.UDisks2.Drive` → `MediaAvailable`**, not on sysfs polling.

| | Eject | Insert |
|---|---|---|
| `MediaAvailable` | `False` | `True` |
| `Media` | `""` | `optical_bd` |
| `Size` | `0` | `46487896064` |
| `OpticalNumTracks` | `0` | `1` |

The matching `Block` signal arrives in the **same millisecond** carrying
`IdLabel`, `IdType`, and `IdUUID` — so the disc label is available at trigger
time with no re-probe needed before starting a copy job.

Implementation notes:

1. `MediaAvailable` lives on the **`Drive`** interface, not `Block`. `Block`
   carries `IdType` / `IdLabel` / `IdUUID` / `Size`.
2. `PropertiesChanged` is emitted **on `org.freedesktop.DBus.Properties`**. The
   interface whose properties changed is the *first body argument*, not
   `msg.interface`. Filtering on `msg.interface == "…UDisks2.Block"` matches
   nothing — this is the bug that made `tests/watch_disc.py` silent.
3. In dbus-next, property values arrive as `Variant` objects; use `.value`.
   Comparing a `Variant` to an `int` raises `TypeError`.
4. A `MediaCompatibility`-only signal follows the insert ~21ms later. Filter on
   `MediaAvailable` being *present* in the changed dict or the trigger fires twice.

## Sysfs Attributes on This Drive (corrected)

| Attribute | Value | Notes |
|-----------|-------|-------|
| `/sys/class/block/sr0/size` | `90796672` | 512-byte sectors; ×512 = 46487896064 bytes, agrees with `Block.Size` |
| `/sys/class/block/sr0/removable` | `1` | Removable media |
| `/sys/class/block/sr0/events` | `media_change eject_request` | Supported event *names*, NOT a counter |
| `/sys/class/block/sr0/events_async` | *(blank)* | **Corrected** — previously recorded as `0 0` / "two counters". Blank means no async event notification. |
| `/sys/class/block/sr0/hidden` | `0` | **Corrected** — previously read as "No media". `hidden` means the device is hidden from userspace; it says nothing about media presence. |
| `/sys/class/block/sr0/media_available` | N/A | Does not exist |

## Open Question: does sysfs `size` track media changes?

**Still unverified.** During the eject/insert cycle above, the sysfs polling
channel reported nothing across a 90796672 → 0 → 90796672 transition.

Two candidate explanations, not yet distinguished:

1. `/sys/block/srN/size` goes stale or unreadable while the tray is open and
   returns to its original value on re-insert, so a naive comparison never sees a change.
2. A bug in the probe's poller: `except OSError: continue` left the previous
   value intact on an unreadable read, masking the whole cycle. **Fixed** in
   `tests/watch_disc_probe.py` — an unreadable size is now tracked as its own
   state, and a `done_callback` surfaces poller exceptions that a cancelled task
   would otherwise swallow.

The original document claimed "✅ Polling fallback works" on the basis of its own
line *"No events captured because disc is static (no change since boot)"* — i.e.
polling was only ever confirmed to read a **baseline**, never to detect a
**change**. Do not rely on it until a physical cycle confirms it.

## Superseded Findings

Retained for the record. **All of the following are refuted** by the evidence above.

- ~~"Kernel does NOT emit uevents for this USB external drive"~~ — it does.
- ~~"Physical eject/re-insert produces ZERO events via `udevadm monitor` or pyudev netlink"~~
  — the netlink monitor was not running.
- ~~"This is a hardware limitation — USB bridge chip does not propagate tray/media-change to the kernel"~~
  — the bridge chip does not support *asynchronous* notification, but block-layer
  polling generates the uevents regardless.
- ~~"✅ Polling fallback works — ready for Rust implementation"~~ — only the
  baseline read was tested; change detection was not.
- ~~"Translate the polling approach to Rust: read `/sys/class/block/srN/size` every 5s"~~
  — wrong architecture. Poll-based detection at 5s would also be *slower* than
  the ~2s uevent cadence it replaces.

## Environment

- OS: Ubuntu 26.04 (sudo-rs)
- Drive: HL-DT-ST BD-RE BU40N via USB (ID 13fd:0840)
- dbus-next 0.2.3, Python 3.14.4
- pyudev 0.24.4 (API differs from older docs — see `docs/udev-gnome-interaction.md`)

## Next Steps

1. Resolve the sysfs open question above with one physical eject/insert cycle
   using the fixed `tests/watch_disc_probe.py`.
2. Correct `docs/udev-gnome-interaction.md`, which still carries the refuted
   "zero uevents / hardware limitation" conclusion (lines 11, 37–50, 87–102).
3. Fix or retire `tests/watch_disc.py` — its interface guard, `Variant` handling,
   and SIGINT handling are all broken (see Implementation notes above).
4. Implement the Rust trigger against `Drive.MediaAvailable` over D-Bus.
5. Confirm behaviour on the target internal SATA drive, which should support
   asynchronous event notification and avoid the 2s polling dependency entirely.

## References

- `tests/watch_disc_probe.py` — three-channel diagnostic (Block / Drive / sysfs)
- `tests/watch_disc.py` — original D-Bus prototype (non-functional)
- `tests/udev_monitor.py` — pyudev prototype with sysfs polling fallback
- `docs/udev-gnome-interaction.md` — udev rule investigation (needs correction)
